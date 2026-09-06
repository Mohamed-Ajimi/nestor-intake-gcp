"""The real intake feature router — the RPC-equivalent backend (INTAKE-01/02/03/04).

This GENERALIZES the earlier throwaway seam-prover scaffold into the full
authenticated intake surface, bounded by the scope ceiling at ``decomposed``: list /
create / get / patch intakes, read + section-batch-save answers (D-03), discrete named
status transitions (``/submit`` / ``/review`` — Task 2), and read-only skill-run +
template projections that feed the admin phase machine (``derivePhase``). This module is
the CONTRACT SOURCE OF TRUTH — the ``IntakeView`` / ``AnswerView`` / ``SkillRunView``
shapes and the endpoint paths here are mirrored by the frontend API seam (plan 05).

Locked decisions / invariants realized here:

* D-08 / D-03 — every handler acquires data access ONLY via a ``Depends(get_*_repo)``
  injected repository; this module imports NO raw DB symbol (``get_engine`` /
  ``get_superadmin_engine`` / ``sessionmaker`` / ``create_engine`` / ``Session``). The
  ``ci_no_raw_db_access.sh`` grep-guard scans ``app/`` outside ``app/db/`` and would fail
  the build if any leaked in here.
* TENANT-02 — ``space_id`` is NEVER read from the request (body / path / query). Only the
  path ``intake_id`` plus benign body fields flow to the repo; the tenant scope comes
  solely from the injected ``Identity`` inside the dependency. ``IntakePatch`` deliberately
  carries no ``space_id`` and no lifecycle/status field (status changes ONLY via the
  allow-listed transition verbs in Task 2).
* D-07 — 404 is the ONLY data-route denial code: ``repo.get`` -> ``None`` and ``repo.patch``
  -> ``rowcount == 0`` (the cross-tenant-by-id outcomes) both map to HTTP 404, never 403,
  never 200-with-data (existence is hidden; no BOLA/IDOR enumeration). The single 403 in
  the stack is the null-space default-deny inside the dependency (D-04).
* Scope ceiling (INTAKE-05) — this module defines NO deep-research-stage route and no
  post-``decomposed`` transition, ever. The intake surface stops at ``decomposed``; the
  later lifecycle stages are a separate, out-of-scope track.
* AUTH-01 — mounted UNDER ``protected_router`` in ``app/main.py``, so it inherits
  ``Depends(get_current_identity)`` and is never anonymous.

Sync ``def`` handlers (not ``async def``): pg8000 is a blocking driver and FastAPI runs
sync handlers in a threadpool; an ``async def`` calling the sync engine would stall the
event loop (mirrors ``admin_routes.py`` / ``main.py``).
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import anyio
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.auth.dependencies import get_current_identity
from app.auth.gates import superadmin_gate
from app.auth.identity import Identity
from app.core.config import get_settings
from app.intake_canonical import (
    CANONICAL_TEMPLATE_ID,
    CANONICAL_TEMPLATE_NAME,
    CANONICAL_TEMPLATE_SCHEMA,
    admin_only_field_keys,
    client_visible_schema,
)
from app.intake_write_policy import AnswerWriteViolation, check_answer_batch
from app.db import audit
from app.db.ai_session import tenant_session
from app.db.models.membership import OrganizationMembership
from app.db.models.organization import Organization
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    IntakeSourceRepository,
    ResearchArtifactRepository,
    SkillRunRepository,
)
from app.mail import render as mail_render
from app.mail import resend as mail_resend

_log = logging.getLogger(__name__)
from app.db.session import (
    get_intake_and_answer_repos,
    get_intake_answer_repo,
    get_intake_source_repo,
    get_research_artifact_repo,
    get_skill_run_repo,
    get_tenant_repo,
)
# The stream's DB access lives in app/db/stream_session.py — NOT a raw DB symbol — so this
# route module stays clean for the ci_no_raw_db_access.sh grep-guard (docstring above).
from app.db.stream_session import check_intake_in_scope, read_latest_run_dict

# The intake feature router. It carries NO auth dependency of its own — it is mounted
# UNDER protected_router in app/main.py, inheriting Depends(get_current_identity), and
# each handler additionally Depends(get_*_repo) for its tenant-scoped data access.
intake_router = APIRouter(prefix="/intakes", tags=["intakes"])


# ---------------------------------------------------------------------------
# Response / request models (the contract plan 05 mirrors)
# ---------------------------------------------------------------------------


class IntakeView(BaseModel):
    """Read-shaped view of an intake — carries the FIVE phase markers ``derivePhase`` reads.

    ``validation_link_sent_at`` / ``results_link_sent_at`` /
    ``context_pack_artifact_id`` / ``final_report_artifact_id`` are surfaced (alongside
    ``status``) so the admin phase machine can be driven entirely off this projection. No
    relationships, answers, or out-of-scope surface are exposed (scope ceiling).
    """

    id: str
    space_id: str
    status: str
    client_name: str | None = None
    validation_link_sent_at: str | None = None
    results_link_sent_at: str | None = None
    context_pack_artifact_id: str | None = None
    final_report_artifact_id: str | None = None


class IntakeCreate(BaseModel):
    """The benign create body. ``space_id`` is NEVER accepted — it is injected by the repo
    from the verified Identity (TENANT-02). Only the display name and an optional template
    reference may be supplied.
    """

    client_name: str | None = None
    template_id: str | None = None


class IntakePatch(BaseModel):
    """Benign mutable subset of an intake — only the display name may be set here."""

    client_name: str | None = None


class AnswerView(BaseModel):
    """Read-shaped view of one answer row (the section batch save round-trips this)."""

    field_key: str
    value: str | None = None
    # Any JSON value, not just objects — the frontend routes every non-string form value
    # here (arrays from list/files fields, booleans, numbers) and the column is JSONB.
    value_json: Any = None


class AnswerItem(BaseModel):
    """One inbound answer in a section batch. Carries NO ``space_id`` / ``intake_id`` — the
    repo injects ``space_id`` from the Identity and ``intake_id`` from the path (D-03).
    """

    field_key: str
    value: str | None = None
    # Mirrors AnswerView: any JSON value (arrays/booleans/numbers), matching the JSONB
    # column and the frontend's string->value / everything-else->value_json split.
    value_json: Any = None


class AnswerBatch(BaseModel):
    """A section's worth of answers to upsert in one round-trip (save-as-you-go, D-03)."""

    answers: list[AnswerItem]


class SkillRunView(BaseModel):
    """Read-shaped view of one skill run — ``status`` is mapped VERBATIM (Pitfall 1).

    ``skill`` is the run's skill NAME (``apply-intake-skill`` / ``context-pack`` / ...) so
    the frontend can DISAMBIGUATE which flow produced a run. With context-pack now also
    landing ``succeeded`` runs (07-09), consumers that used to assume "newest succeeded run
    == apply-intake-skill" can filter on this field instead (07-10). The ORM column carries
    ``server_default="apply-intake-skill"`` so legacy rows read back a non-null value.

    ``created_at`` is the run's REAL START timestamp — the Postgres ``now()`` stamped at
    INSERT by ``create_running_skill_run`` (``models/skill_run.py`` gives it
    ``server_default=func.now()``, NOT NULL). It exists because this view previously
    projected NO start timestamp at all, so the frontend synthesised one with
    ``new Date()`` for any run still in flight (both ``applied_at`` and ``completed_at``
    are null while running). That made the intake page's AI skill-run elapsed clock restart
    from 00:00 on every mount AND on every SSE event. There is no rival candidate to pick
    by mistake: ``skill_runs`` once carried a ``started_at`` that nothing ever wrote, and
    migration 0015 (phase 23.1) DROPPED it. Only ``research_runs.started_at`` — a different
    column on a different table — is a real, written start timestamp.
    """

    id: str
    skill: str
    status: str
    created_at: str | None = None
    applied_at: str | None = None
    completed_at: str | None = None


class SkillRunsView(BaseModel):
    """The skill-run read projection: the latest run plus the full list (newest first)."""

    latest: SkillRunView | None = None
    runs: list[SkillRunView]


class SkillRunFullView(BaseModel):
    """Full read of ONE skill run — the D-08 projection the AIReviewPanel consumes.

    Phase 7 writes ``output_parsed`` (the parsed Claude JSON: refined/additional/dropped
    questions + gaps) and ``cost_estimate_usd`` on a finished run, but nothing projected
    them until now — the review flow was a dead end. This surfaces exactly those two fields
    (plus the id) within scope; the terminal SSE event finally leads somewhere.
    """

    id: str
    output_parsed: dict | None = None
    cost_estimate_usd: float | None = None


class TemplateView(BaseModel):
    """Read-shaped view of an intake template (the form schema the UI renders)."""

    id: str
    name: str
    schema: dict | None = None


class ContextPackView(BaseModel):
    """Read-shaped view of ONE context-pack artifact — the briefing markdown the admin reads.

    Projects ONLY in-scope, non-identifying fields (T-7-09-02): the id, the briefing
    ``text_content``, its ``created_at``, and the free-text ``notes``. Deliberately carries
    NO ``space_id``, no ``storage_bucket`` / ``storage_path``, and no cross-tenant identifier
    (mirrors the ``SkillRunFullView`` projection discipline).
    """

    id: str
    text_content: str | None = None
    created_at: str | None = None
    notes: str | None = None


class IntakeSourceView(BaseModel):
    """Read-shaped view of ONE intake source upload — the transcribe CTA's source list.

    Projects ONLY in-scope, non-identifying fields (T-12-08): the id, the ``kind``
    ('audio'|'document'|...), the display ``file_name``, its ``language``, and
    ``created_at``. Deliberately carries NO ``space_id`` and no ``storage_bucket`` /
    ``storage_path`` — no tenant identifier and no GCS object location ever leak to the
    browser (mirrors the ``ContextPackView`` / ``SkillRunFullView`` projection discipline).
    """

    id: str
    kind: str | None = None
    file_name: str | None = None
    language: str | None = None
    created_at: str | None = None


class IntakeSourcesView(BaseModel):
    """The sources read projection: the intake's uploads (a ``{ sources: [...] }`` wrapper).

    A wrapper (not a bare list) so the shape is additively extensible and matches the
    frontend seam's ``{ sources }`` contract (plan 05 / 12-03 Task 2).
    """

    sources: list[IntakeSourceView]


class MemberView(BaseModel):
    """One ACTIVE member of the intake's space — the RecipientPicker (Plan 04) list row.

    The ``organization_memberships`` table has NO ``name`` column, so ``name`` is
    always ``None`` here (kept in the shape so a later name source is additive). The
    read is scoped to the intake's OWN space and active members only — a deactivated
    member never appears (T-10-13).
    """

    id: str
    email: str | None = None
    name: str | None = None


class MailRecipients(BaseModel):
    """Send-endpoint body — membership ids ONLY (D-06 / TENANT-02).

    Carries ``recipients: list[str]`` (``organization_memberships`` ids) and NOTHING
    else — deliberately NO ``to`` / ``email`` / ``space_id`` field so a free-text
    recipient address can never be honored (D-06 no-free-address; ``extra="forbid"``
    rejects a smuggled ``to``/``email`` with a 422). The server resolves the emails
    from ACTIVE memberships of the intake's own space; the client never names an
    address.
    """

    model_config = {"extra": "forbid"}

    recipients: list[str]


class DeliverBody(BaseModel):
    """Deliver / replace body — the staged report key + membership-id recipients (D-06 / D-10).

    Extends the :class:`MailRecipients` shape with the staged ``storage_path`` (the
    server-authored key the report PDF was uploaded under). ``model_config`` forbids extra
    fields for the SAME reason ``MailRecipients`` does — no smuggled ``to``/``email`` free
    address (D-06 no-free-address) and no smuggled ``space_id`` / ``status`` (TENANT-02): the
    tenant scope comes from the verified Identity, the status transition from the discrete
    verb, never the body. ``recipients`` are ``organization_memberships`` ids ONLY; the
    server resolves emails + per-recipient locale. On ``/report/replace`` ``recipients`` may
    be empty (a silent replace — D-05); on ``/deliver`` the picker supplies at least one.
    """

    model_config = {"extra": "forbid"}

    storage_path: str
    recipients: list[str] = []


class ReportView(BaseModel):
    """Read-shaped view of the delivered report artifact (REPORT-02 — client read).

    The projection ``GET /intakes/{id}/report`` returns once (and ONLY once) the intake is
    exactly ``delivered``. ``delivered_at`` mirrors ``results_link_sent_at`` (the delivery
    mail stamp — no separate delivered-at column; the phase machine reads
    delivered + results_link_sent_at == completed). ``storage_path`` IS surfaced here
    (unlike the context-pack view) because the client download flow feeds it back to the
    existing ``GET /intakes/{id}/storage/signed-url?path=...`` seam, whose own prefix-assert
    walls a forged key — and the client only ever receives its OWN report's key.
    """

    filename: str | None = None
    delivered_at: str | None = None
    byte_size: int | None = None
    mime_type: str | None = None
    storage_path: str | None = None


# ---------------------------------------------------------------------------
# Projection helpers (no leakage — only in-scope fields)
# ---------------------------------------------------------------------------


def _view(intake) -> IntakeView:
    """Project an ``Intake`` ORM row onto the response, carrying all five phase markers."""
    return IntakeView(
        id=str(intake.id),
        space_id=str(intake.space_id),
        status=intake.status,
        client_name=intake.client_name,
        validation_link_sent_at=(
            intake.validation_link_sent_at.isoformat()
            if intake.validation_link_sent_at
            else None
        ),
        results_link_sent_at=(
            intake.results_link_sent_at.isoformat()
            if intake.results_link_sent_at
            else None
        ),
        context_pack_artifact_id=(
            str(intake.context_pack_artifact_id)
            if intake.context_pack_artifact_id
            else None
        ),
        final_report_artifact_id=(
            str(intake.final_report_artifact_id)
            if intake.final_report_artifact_id
            else None
        ),
    )


def _answer_view(answer) -> AnswerView:
    """Project an ``IntakeAnswer`` ORM row onto the answer response."""
    return AnswerView(
        field_key=answer.field_key,
        value=answer.value,
        value_json=answer.value_json,
    )


# ---------------------------------------------------------------------------
# Field-level confidentiality projections (F-01 / D-23.2-03)
#
# THE POLARITY IS ``!= "superadmin"``, NOT ``== "user"``. Deny by default: any role value
# that is not exactly the superadmin literal gets the filtered projection, so a role added
# later is withheld-from until someone decides otherwise. An ``== "user"`` test would leak
# to every future role by omission.
#
# NO FIELD KEY IS WRITTEN OUT HERE. Both helpers derive their key set from
# ``app.intake_canonical.admin_only_field_keys()``, which reads the section-level
# ``admin_only`` flag out of the canonical schema (D-23.2-02). A fifth admin-only field
# added to ``app/data/pulse_intake_v1.json`` therefore closes in both helpers with no code
# change. Do not "simplify" either of these to a literal set.
# ---------------------------------------------------------------------------


def _visible_answer_rows(rows, *, role):
    """Drop admin-only answer rows for a non-superadmin caller (D-23.2-03).

    The canonical form marks the ``strategic_perspective`` SECTION ``admin_only``, and that
    section's own description reads *"Visible only to admin, not to the client and not in
    the handoff PDF."* Until phase 23.2 that flag was honoured only in the browser
    (``IntakeForm.tsx:164``), so ``GET /intakes/{id}/answers`` handed the operator's private
    bias analysis of a client straight to that client (F-01 hop 1, 23.2-CONTEXT.md § 2).

    NAMED rather than inlined, deliberately: ``upsert_answers`` returns the SAME
    ``list_for_intake`` row list, so a successful client WRITE would otherwise hand straight
    back the rows the READ just withheld. One rule, two call sites, never two copies — an
    inline comprehension here is how that seam reopens.

    A superadmin gets the list back unchanged (the AI review panel consumes these rows).
    """
    if role == "superadmin":
        return rows
    admin_keys = admin_only_field_keys()
    return [row for row in rows if row.field_key not in admin_keys]


def _visible_output_parsed(parsed, *, role):
    """Withhold the admin-only members of a skill run's ``output_parsed`` (D-23.2-03).

    The AI's output shape is NOT the schema's shape (``ai/skills/apply.py:17-21``): it
    carries ``decision_or_goal``, ``research_questions_refined``, ``additional_questions``,
    ``dropped_questions``, ``gaps_flagged`` plus two admin-only members. One of those is an
    admin field key verbatim; the OTHER — THE REASON THIS HELPER EXISTS — is a NESTED
    object: its parent key is NOT itself a field key, but its three members
    (``{upstream, downstream, perspectief}``) map one-for-one onto three admin field keys
    that share that parent as their prefix. See ``app/ai/prompts.py:139-145`` for the two
    keys by name and ``AIReviewPanel.tsx:127-129`` for the mapping. A plain membership test
    misses the nested one entirely and leaks the whole object.

    Deliberately NOT naming those two keys here: this module must contain no admin field-key
    literal at all (D-23.2-02), so that a grep of THIS file proves no key drives policy.

    So the rule is DERIVED, never hand-written:

        drop top-level key K if K is an admin key, OR some admin key A starts with K + "_"

    Against today's four admin keys that drops exactly two of the seven and keeps five. It
    closes automatically for a fifth admin-only field, and it errs toward OVER-dropping for a
    non-superadmin, which is the safe direction for a confidentiality filter.

    ``None`` stays ``None``. A non-dict value (a legacy/odd row) is returned UNCHANGED rather
    than raising — a projection must never be the thing that 500s on odd data. Note that the
    ``SkillRunFullView.output_parsed`` field is declared ``dict | None``, so a non-dict value
    is still rejected downstream by response validation; that is a pre-existing contract, not
    this helper's business, and widening it is not in scope for D-23.2-03.
    """
    if role == "superadmin" or not isinstance(parsed, dict):
        return parsed
    admin_keys = admin_only_field_keys()
    return {
        key: value
        for key, value in parsed.items()
        if key not in admin_keys
        and not any(admin_key.startswith(key + "_") for admin_key in admin_keys)
    }


def _skill_run_view(run) -> SkillRunView:
    """Project a ``SkillRun`` ORM row — ``status`` mapped verbatim, no remap (Pitfall 1)."""
    return SkillRunView(
        id=str(run.id),
        skill=run.skill,
        status=run.status,
        # The run's real start (dispatch time) — see SkillRunView. Guarded with a
        # truthiness check like its siblings even though the column is NOT NULL, so a
        # legacy/partial row can never raise here.
        created_at=(run.created_at.isoformat() if run.created_at else None),
        applied_at=(run.applied_at.isoformat() if run.applied_at else None),
        completed_at=(run.completed_at.isoformat() if run.completed_at else None),
    )


def _context_pack_view(artifact) -> ContextPackView:
    """Project a ``ResearchArtifact`` (context-pack) ORM row — in-scope fields only."""
    return ContextPackView(
        id=str(artifact.id),
        text_content=artifact.text_content,
        created_at=(artifact.created_at.isoformat() if artifact.created_at else None),
        notes=artifact.notes,
    )


def _intake_source_view(source) -> IntakeSourceView:
    """Project an ``IntakeSource`` ORM row — id/kind/file_name/language/created_at ONLY.

    NEVER projects ``space_id`` / ``storage_bucket`` / ``storage_path`` (T-12-08 — no
    tenant/storage identifier leaks to the browser; same discipline as _context_pack_view).
    """
    return IntakeSourceView(
        id=str(source.id),
        kind=source.kind,
        file_name=source.file_name,
        language=source.language,
        created_at=(source.created_at.isoformat() if source.created_at else None),
    )


# ---------------------------------------------------------------------------
# Collection handlers
# ---------------------------------------------------------------------------


@intake_router.get("")
def list_intakes(
    space_id: str | None = None,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> list[IntakeView]:
    """List intakes visible to the caller — own-space rows only for a user (TENANT-02).

    The repository applies the explicit ``WHERE space_id =`` for a user (and omits it for a
    superadmin, who reads across spaces); the handler passes NO scope argument to the repo.

    ``space_id`` is an optional SUPERADMIN-ONLY view-filter (TENANT-04 / T-06-22): when a
    superadmin supplies it the already-cross-tenant result is NARROWED to that space at the
    HANDLER layer (a list comprehension over ``repo.list()`` rows — never a repo argument, so
    the repository's no-``space_id``-parameter invariant holds). For a user the param is INERT
    — their rows are already token-scoped by the repo, so it can neither widen nor narrow.
    """
    rows = repo.list()
    if identity.role == "superadmin" and space_id:
        rows = [r for r in rows if str(r.space_id) == space_id]
    return [_view(row) for row in rows]


@intake_router.post("", status_code=status.HTTP_201_CREATED)
def create_intake(
    body: IntakeCreate,
    space_id: str | None = None,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> IntakeView:
    """Create an intake -> ``draft`` (fires ``trg_prefill_intake_answers``).

    A USER creates in their OWN space — the repo injects ``space_id`` from the verified
    Identity (TENANT-02), and the optional ``space_id`` query param is INERT for them (it can
    neither widen nor retarget). A SUPERADMIN has no own space, so they create into a CHOSEN
    target space — the active-client switcher, threaded as ``?space_id=`` — via the superadmin
    write path (``create_in_space``). ``space_id`` is NEVER read from the create BODY; the
    query param is honored ONLY for a superadmin (mirrors the 06-13 list filter). A superadmin
    with no client selected gets 422 — pick a client first. The DB ``server_default`` sets the
    initial ``draft`` status.
    """
    values = body.model_dump(exclude_unset=True)
    # Coerce an optional template reference to UUID for the pg8000 bind; ``space_id`` is
    # NEVER in ``values`` (not honored from the body) — see the role branch below.
    if values.get("template_id"):
        values["template_id"] = uuid.UUID(values["template_id"])

    if identity.role == "superadmin":
        if not space_id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Select a client (space) before creating an intake.",
            )
        intake = repo.create_in_space(uuid.UUID(space_id), **values)
    else:
        # User path: the repo forces the caller's own space onto the row (TENANT-02);
        # any ``space_id`` query param is ignored.
        intake = repo.create(**values)
    return _view(intake)


@intake_router.get("/templates")
def list_templates(
    identity: Identity = Depends(get_current_identity),
) -> list[TemplateView]:
    """Return the single CANONICAL intake template, projected by role (D-CANON / D-23.2-04).

    The Pulse intake form is shared product config, identical for every space, so it is
    served from the in-repo canonical asset (``app.intake_canonical``) rather than per-space
    ``intake_templates`` rows — no per-space copies, no operator-edited JSON. EVERY
    authenticated caller (user or superadmin, any space) receives the same template; there
    is no longer a per-space template read here, so the handler stays DB-free (no repo, no
    scope — ``identity`` is read for the projection only).

    WHAT IS WITHHELD, AND FROM WHOM (D-23.2-04). A non-superadmin receives
    ``client_visible_schema()`` — the canonical schema minus every section flagged
    ``admin_only`` (today: 13 of 14 sections). This is SCHEMA disclosure rather than answer
    disclosure and so a lower severity than F-01's other hops, but serving it tells a client
    exactly which private field keys exist and what they are for: the withheld section's
    labels and help text are the operator's own bias/blind-spot analysis prompts. Both
    frontend consumers already discard the section (``IntakeForm.tsx:164``,
    ``intake.$id.results.tsx:163``), so filtering server-side makes them redundant, not
    wrong. A superadmin still receives the full schema verbatim.

    ⚠ ``client_visible_schema()`` returns ONE SHARED import-time object. It is serialised
    here and never mutated; a handler that popped sections off it would corrupt every later
    response in the process, for every role.

    The route stays OPEN to ``role=user`` — EXACTLY 200 (pinned client route row 2). This is
    a body projection, never a gate; without the template the client form has no schema to
    render at all.

    Declared BEFORE ``/{intake_id}`` so the literal ``templates`` segment is not captured
    as a path parameter.
    """
    schema = (
        CANONICAL_TEMPLATE_SCHEMA
        if identity.role == "superadmin"
        else client_visible_schema()
    )
    return [
        TemplateView(
            id=str(CANONICAL_TEMPLATE_ID),
            name=CANONICAL_TEMPLATE_NAME,
            schema=schema,
        )
    ]


# ---------------------------------------------------------------------------
# Item handlers
# ---------------------------------------------------------------------------


@intake_router.get("/{intake_id}")
def get_intake(
    intake_id: str,
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Get one intake by id within scope, or 404 (D-07).

    A cross-tenant ``intake_id`` is excluded by the repo's scoped ``WHERE`` (+ RLS), so
    ``repo.get`` returns ``None`` — which becomes a 404, NEVER a 403 and NEVER a
    200-with-data (existence is hidden; no BOLA/IDOR disclosure).
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(intake)


@intake_router.patch("/{intake_id}")
def patch_intake(
    intake_id: str,
    body: IntakePatch,
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Patch a benign field on an in-scope intake, or 404 (D-07).

    Only the path ``intake_id`` plus the benign body fields flow to the repo — never a
    ``space_id`` from the request (TENANT-02), and never a lifecycle/status field (those
    move ONLY through the allow-listed transition verbs). A cross-tenant id matches the
    scoped ``WHERE`` against nothing, so ``repo.patch`` returns ``rowcount == 0`` and the
    foreign row is untouched -> 404.
    """
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    rowcount = repo.patch(intake_id, **values)
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    updated = repo.get(intake_id)
    if updated is None:  # pragma: no cover - patched row is in-scope by construction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(updated)


# ---------------------------------------------------------------------------
# Answers (read + section-batch upsert — D-03)
# ---------------------------------------------------------------------------


@intake_router.get("/{intake_id}/answers")
def list_answers(
    intake_id: str,
    repo: IntakeAnswerRepository = Depends(get_intake_answer_repo),
    identity: Identity = Depends(get_current_identity),
) -> list[AnswerView]:
    """Read this intake's answers within scope, projected by role (D-23.2-03).

    Tenant scope is unchanged: the repo already restricts a user to their OWN space. What is
    new is FIELD-level confidentiality WITHIN that space.

    WHAT IS WITHHELD, AND FROM WHOM. A non-superadmin does not receive answers whose
    ``field_key`` belongs to an ``admin_only`` SECTION of the canonical form (today the four
    ``strategic_perspective`` keys — the operator's private bias-radar and blind-spot
    analysis OF this client). The source of truth is the section-level ``admin_only`` flag in
    ``app/data/pulse_intake_v1.json``, read once by ``app.intake_canonical``; no key is
    written out here (D-23.2-02). A superadmin sees every row — the AI review panel depends
    on it.

    The rule lives in :func:`_visible_answer_rows` because the WRITE path shares it:
    ``upsert_answers`` returns this same row list, so an inline filter here would let a
    client read back through a PATCH what a GET withheld.

    The route stays OPEN to ``role=user`` — EXACTLY 200 (pinned client route row 4). This is
    a body projection, never a gate.
    """
    rows = _visible_answer_rows(repo.list_for_intake(intake_id), role=identity.role)
    return [_answer_view(row) for row in rows]


@intake_router.patch("/{intake_id}/answers")
def upsert_answers(
    intake_id: str,
    body: AnswerBatch,
    repos: tuple[IntakeRepository, IntakeAnswerRepository] = Depends(get_intake_and_answer_repos),
    identity: Identity = Depends(get_current_identity),
) -> list[AnswerView]:
    """Upsert a section's answers in one round-trip (save-as-you-go, D-03).

    OWNERSHIP GATE (T-06-20 / D-07): BEFORE any write, ``intake_repo.get`` verifies the
    caller owns ``intake_id`` on the SAME tx as the upsert (the combined dependency yields
    both repos on one session — D-02). A cross-tenant/missing id -> ``None`` -> 404 (never
    403, never 200-with-data). Each item carries only ``field_key`` / ``value`` /
    ``value_json``; the repo injects ``space_id`` (Identity) + ``intake_id`` (path), never
    from the item dict (T-06-03), targeting the ``(intake_id, field_key)`` constraint.

    WRITE POLICY (D-23.2-05/06/07, 23.2-CONTEXT.md § 3). Until phase 23.2 this handler checked
    ownership and NOTHING else — a client could write an undefined field key onto a
    ``delivered`` intake, i.e. mutate the research inputs after the pack was built, after a
    ~$45 research run consumed them, and after delivery. ``check_answer_batch`` now enforces,
    for a ``role=user``:

    ================================  ==============================================
    Intake status                     may write
    ================================  ==============================================
    ``draft``                         any canonical field that is not admin-only
    ``reviewed`` /                    ONLY fields whose canonical ``type`` is
    ``validated_by_client``           ``proposal_list``
    anything else                     nothing (409)
    ================================  ==============================================

    ⛔ The middle row is NOT decoration and the policy is NOT "only ``draft`` is writable":
    ``IntakeForm.tsx:501`` keeps ``proposal_list`` fields enabled through the validation phase
    — the client's "keep Nestor's proposal" tick, shipped 2026-08-31. A draft-only rule kills
    it silently.

    CODE PRECEDENCE: ownership 404 -> lifecycle 409 -> schema membership 422 -> admin-only 404
    -> status/field 409 -> value 422. **The ownership check stays FIRST**, above the policy
    call: a cross-tenant caller writing a non-canonical key must get the existence-hidden 404,
    not the policy's 422, or the response code becomes an oracle for field validity across a
    tenant boundary (``tests/test_intake_cross_tenant.py::
    test_upsert_answers_cross_tenant_returns_404_answers_unchanged``). All-or-nothing: the
    policy is evaluated for the WHOLE batch before the repo sees anything.

    SUPERADMIN IS EXEMPT — ``check_answer_batch`` returns immediately for it, so the AI-review
    apply path and the admin edit-mode save (``admin.pulse.intakes.$id.tsx:951``, which writes
    the admin-only fields) are unaffected.

    The 200 body is projected through :func:`_visible_answer_rows`, EXACTLY like
    ``list_answers`` — this handler returns the same ``list_for_intake`` rows, so an unfiltered
    return here would hand a client back through a PATCH what the GET withholds (F-01).
    """
    intake_repo, answers_repo = repos
    # Ownership pre-check (D-07): a cross-tenant/missing id is hidden as 404 BEFORE any write.
    intake = intake_repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    items = [item.model_dump() for item in body.answers]
    try:
        check_answer_batch(items, intake_status=intake.status, role=identity.role)
    except AnswerWriteViolation as exc:
        # ``from None``: a policy refusal is an expected outcome, not an internal fault — it
        # must never carry an internal traceback into the response chain.
        raise HTTPException(exc.code, exc.detail) from None

    if identity.role == "superadmin":
        # Superadmin has NO own space (null-space repo) — target the intake's OWN space,
        # mirroring the storage CR-02 / intake-create fix. A plain upsert_batch() would
        # hit the null-space RuntimeError guard -> 500 (live-UAT regression 2026-07-13:
        # the admin AI-review apply path writes answers as superadmin).
        answers_repo.upsert_batch_in_space(intake.space_id, intake_id, items)
    else:
        answers_repo.upsert_batch(intake_id, items)
    # Same projection as ``list_answers`` — ONE helper, two call sites, never two copies.
    rows = _visible_answer_rows(answers_repo.list_for_intake(intake_id), role=identity.role)
    return [_answer_view(row) for row in rows]


# ---------------------------------------------------------------------------
# Skill runs (read-only projection feeding derivePhase)
# ---------------------------------------------------------------------------


@intake_router.get("/{intake_id}/skill-runs")
def list_skill_runs(
    intake_id: str,
    repo: SkillRunRepository = Depends(get_skill_run_repo),
) -> SkillRunsView:
    """Return the latest skill run plus the full list (newest first) within scope.

    ``SkillRun.status`` is mapped VERBATIM into ``SkillRunView`` (no remap) so the phase
    machine sees the exact DB status value (Pitfall 1).
    """
    latest = repo.latest_for_intake(intake_id)
    runs = repo.list_for_intake(intake_id)
    return SkillRunsView(
        latest=_skill_run_view(latest) if latest is not None else None,
        runs=[_skill_run_view(run) for run in runs],
    )


# ---------------------------------------------------------------------------
# Context pack (read-only projection of the generated briefing — 07-09)
# ---------------------------------------------------------------------------


@intake_router.get("/{intake_id}/context-pack")
def get_context_pack(
    intake_id: str,
    repo: ResearchArtifactRepository = Depends(get_research_artifact_repo),
) -> dict:
    """Return the generated context pack (latest + history) for an in-scope intake (07-09).

    The generate-context-pack WRITE path lands a ``research_artifacts`` row
    (``source="context-pack-generator"``, ``text_content`` = briefing markdown) but nothing
    projected it — ``ContextPackBlock.loadLatest`` / ``loadHistory`` were stubbed. This is
    that read surface.

    EXISTENCE-HIDDEN (D-07 / T-7-09-01): the scoped repo applies the per-user space ``WHERE``
    (omitted for superadmin via the 0003 bypass). A cross-tenant or missing intake matches
    ZERO in-scope artifacts, so it reads ``{"latest": None, "history": []}`` — identical to an
    in-scope intake that simply has no pack yet. Absence of a pack is NOT absence of the
    intake, so this is a scoped-empty 200, never a 404 and never a distinguishable 403; a
    stranger cannot tell "no pack" from "not your intake" (no BOLA/IDOR enumeration).
    """
    latest = repo.latest_context_pack_for_intake(intake_id)
    if latest is None:
        return {"latest": None, "history": []}
    history = repo.list_context_packs_for_intake(intake_id)
    return {
        "latest": _context_pack_view(latest),
        "history": [_context_pack_view(a) for a in history],
    }


# ---------------------------------------------------------------------------
# Sources (read-only projection feeding the transcribe CTA — 12-03 / QA-05)
# ---------------------------------------------------------------------------


@intake_router.get("/{intake_id}/sources")
def list_intake_sources(
    intake_id: str,
    repo: IntakeSourceRepository = Depends(get_intake_source_repo),
) -> IntakeSourcesView:
    """Return the intake's source uploads within scope — the transcribe CTA's list (12-03).

    A sibling of :func:`list_skill_runs` (same router, same scoped-repo Depends pattern).
    The transcribe dispatch (``POST /sources/{source_id}/transcribe``) already exists; this
    is the missing READ that feeds it real ``source_id`` values. Each row is projected
    through :func:`_intake_source_view` to id/kind/file_name/language/created_at ONLY —
    NEVER space_id/storage_bucket/storage_path (T-12-08 — no tenant/storage leak).

    EXISTENCE-HIDDEN (D-07 / T-12-07, mirrors :func:`get_context_pack`): the scoped repo
    applies the per-user space ``WHERE`` (omitted for superadmin via the 0003 bypass). A
    cross-tenant or missing intake matches ZERO in-scope sources, so it reads
    ``{"sources": []}`` — identical to an in-scope intake that simply has no uploads yet.
    Absence of sources is NOT absence of the intake, so this is a scoped-empty 200, never a
    404 and never a distinguishable 403; a stranger cannot tell "no sources" from "not your
    intake" (no BOLA/IDOR enumeration).
    """
    rows = repo.list_for_intake(intake_id)
    return IntakeSourcesView(sources=[_intake_source_view(row) for row in rows])


# ---------------------------------------------------------------------------
# Members read + intake-scoped mail send endpoints (NOTIF-01/02, Plan 10-03)
# ---------------------------------------------------------------------------
#
# The members read is the concrete list the Plan-04 RecipientPicker consumes; the three
# send endpoints resolve recipients server-side from ACTIVE memberships of the intake's
# OWN space (D-06 — never a client-named address) and stamp the sent-at column ONLY on a
# successful (2xx) Resend send (D-16 / Pitfall 1 — send THEN timestamp). A cross-space
# intake id is an existence-hidden 404 for BOTH the read and every send (D-07 / T-10-06).

# The Dutch subject lines, ported verbatim from the legacy send-pulse-mail.ts (:61-77) —
# the parity source. `{client}` is the intake's client_name display value.
_SUBJECT_VALIDATION = "Even valideren — onderzoeksvragen voor {client}"
_SUBJECT_REMINDER = "Herinnering — onderzoeksvragen wachten op validatie ({client})"
_SUBJECT_RESULTS = "Onderzoeksresultaten klaar — {client}"
_SUBJECT_ADMIN_VALIDATED = "[Nestor Pulse] Klant heeft gevalideerd — {client}"

# Per-locale subject lines (D-12) so the subject matches the recipient's resolved body
# variant. The NL rows are the parity source above; FR/EN are authored to preserve the
# recognizable shape. Keyed by (locale, mail_type). An unknown locale falls back to "nl"
# (the render layer's fallback base) so the subject never desyncs from the body.
_SUBJECTS: dict[str, dict[str, str]] = {
    "nl": {
        "validation": _SUBJECT_VALIDATION,
        "reminder": _SUBJECT_REMINDER,
        "results": _SUBJECT_RESULTS,
        "intake": "Jullie intake staat klaar — {client}",
    },
    "fr": {
        "validation": "À valider — questions de recherche pour {client}",
        "reminder": "Rappel — les questions de recherche attendent votre validation ({client})",
        "results": "Résultats de la recherche prêts — {client}",
        "intake": "Votre intake est prêt — {client}",
    },
    "en": {
        "validation": "To validate — research questions for {client}",
        "reminder": "Reminder — research questions awaiting validation ({client})",
        "results": "Research results ready — {client}",
        "intake": "Your intake is ready — {client}",
    },
}


def _subject_for(locale: str, mail_type: str, client: str) -> str:
    """Return the ``mail_type`` subject in ``locale`` (nl fallback), formatted with ``client``."""
    row = _SUBJECTS.get(locale) or _SUBJECTS["nl"]
    template = row.get(mail_type) or _SUBJECTS["nl"][mail_type]
    return template.format(client=client)


def _active_members_stmt(space_id):
    """Return the base SELECT for ACTIVE ``organization_memberships`` rows in ``space_id``.

    The single active-member query shared by the members read and the send-endpoint
    recipient resolution — filtered ``organization_id == space_id AND status ==
    "active"`` so a deactivated member is NEVER surfaced NOR emailed (T-10-13 / D-06).
    ``organization_memberships`` is a tenant ROOT table (not RLS-scoped), so the
    ``space_id`` gate here is the isolation wall — it is derived from the intake row the
    caller was already proven to own (repo.get 404-gate), never from the request.
    """
    return select(OrganizationMembership).where(
        OrganizationMembership.organization_id == space_id,
        OrganizationMembership.status == "active",
    )


def _resolve_active_member_emails(session, space_id, recipient_ids: list[str]) -> list[str]:
    """Resolve ``recipient_ids`` to ACTIVE-member emails in ``space_id`` (D-06).

    Every requested id MUST be an ACTIVE member of ``space_id`` — a requested id that is
    not (a deactivated member, a foreign-space id, or a bogus id) is REJECTED with a 422
    (never silently dropped-and-sent-to-fewer). An empty resolved list also raises — a
    zero-recipient send never leaves the building. The emails come ONLY from the
    membership rows (D-06 no-free-address); the request never names an address.
    """
    # Coerce the string ids to UUID for the pg8000 bind (membership.id is UUID).
    try:
        wanted = {uuid.UUID(str(rid)) for rid in recipient_ids}
    except (ValueError, TypeError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid recipient id"
        )
    if not wanted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No recipients supplied"
        )

    rows = (
        session.execute(
            _active_members_stmt(space_id).where(
                OrganizationMembership.id.in_(wanted)
            )
        )
        .scalars()
        .all()
    )
    resolved = {row.id: row.email for row in rows if row.email}

    # Reject any requested id that is not an active member with a usable email — do NOT
    # silently send to fewer than requested (the picker must not think a deactivated /
    # unknown id was mailed).
    missing = wanted - set(resolved)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "One or more recipients are not active members of this space",
        )
    return list(resolved.values())


def _resolve_recipient_locales(
    session, space_id, recipient_ids: list[str]
) -> list[tuple[str, str]]:
    """Resolve ``recipient_ids`` to ``(email, locale)`` pairs in ``space_id`` (D-06 / D-07).

    A sibling to :func:`_resolve_active_member_emails` that ALSO carries each recipient's
    SERVER-SIDE resolved locale via the D-07 chain: ``membership.locale`` (the user's own
    override) -> ``organization.default_locale`` (the intake's space) -> ``"nl"``. Locale is
    NEVER taken from the sending admin's request/UI — only from the recipient's OWN
    membership row and the intake's OWN space (the ``space_id`` isolation wall the caller
    already proved, T-11-11). The SAME validation as :func:`_resolve_active_member_emails`
    applies: every requested id MUST be an ACTIVE member with a usable email, else the whole
    batch is 422-rejected (never silently dropped-and-sent-to-fewer); an empty resolved set
    also raises. Email-less active members are rejected (a mail with no ``to`` is never sent).
    """
    try:
        wanted = {uuid.UUID(str(rid)) for rid in recipient_ids}
    except (ValueError, TypeError):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid recipient id"
        )
    if not wanted:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "No recipients supplied"
        )

    # The space default_locale is the chain's middle rung (org, from 11-02) — one read for
    # the whole batch. A missing org row (should not happen for an owned intake) -> "nl".
    space_default = (
        session.execute(
            select(Organization.default_locale).where(Organization.id == space_id)
        ).scalar_one_or_none()
        or "nl"
    )

    rows = (
        session.execute(
            _active_members_stmt(space_id).where(
                OrganizationMembership.id.in_(wanted)
            )
        )
        .scalars()
        .all()
    )
    # membership.locale (user override) -> space_default -> "nl" (the D-07 resolution chain).
    resolved = {
        row.id: (row.email, row.locale or space_default or "nl")
        for row in rows
        if row.email
    }

    missing = wanted - set(resolved)
    if missing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "One or more recipients are not active members of this space",
        )
    return list(resolved.values())


@intake_router.get("/{intake_id}/members")
def list_members(
    intake_id: str,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> list[MemberView]:
    """List the intake space's ACTIVE members ({id, email}), or 404 (D-07 / T-10-13).

    The concrete read the Plan-04 RecipientPicker (``listSpaceMembers``) lists from.
    ``repo.get`` 404-gates a cross-space/unknown intake id (existence-hidden, D-07) —
    for the read as for the sends — BEFORE any membership query. Then the ACTIVE members
    of the intake's OWN space are returned (deactivated members excluded). This reuses
    the same active-member query the send endpoints resolve against.

    Email-less members are filtered out (``email IS NOT NULL``): an active membership with
    no email can never be a recipient — ``_resolve_active_member_emails`` builds ``resolved``
    only from rows ``if row.email`` and would 422-reject the whole send if such a row were
    preselected by the picker. Excluding it here keeps the picker's preselect-all default
    sendable and never renders a blank, label-less checkbox row (WR-02).

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    rows = (
        repo.session.execute(
            _active_members_stmt(intake.space_id).where(
                OrganizationMembership.email.is_not(None)
            )
        )
        .scalars()
        .all()
    )
    return [
        MemberView(id=str(row.id), email=row.email, name=None) for row in rows
    ]


@intake_router.post("/{intake_id}/mail/validation")
def send_validation_mail(
    intake_id: str,
    body: MailRecipients,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Send the validation-request mail; stamp ``validation_link_sent_at`` on 2xx only.

    404 on a cross-space/unknown intake id (existence-hidden, D-07). Recipients resolve
    ONLY from ACTIVE memberships of the intake's own space (D-06). The CTA is the
    token-free ``{app_base_url}/intake/{intake_id}`` app route (NOTIF-01). On a
    successful send the ``validation_link_sent_at`` column is stamped and a ``mail.sent``
    audit row (no link) is written; on a send failure neither is (D-16 / Pitfall 1).

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    return _run_intake_send(
        intake_id, body, repo, identity, is_reminder=False, is_results=False
    )


@intake_router.post("/{intake_id}/mail/reminder")
def send_reminder_mail(
    intake_id: str,
    body: MailRecipients,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Send the reminder (isReminder) validation mail; writes NO timestamp (legacy parity).

    404 on a cross-space/unknown intake id (D-07). Same recipient resolution + CTA as the
    validation send, but the reminder path stamps NO column (there is no reminder-sent
    column — legacy parity) and still audits ``mail.sent`` on a successful send only.

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    return _run_intake_send(
        intake_id, body, repo, identity, is_reminder=True, is_results=False
    )


@intake_router.post("/{intake_id}/mail/results")
def send_results_mail(
    intake_id: str,
    body: MailRecipients,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Send the results-ready mail; stamp ``results_link_sent_at`` on 2xx only.

    404 on a cross-space/unknown intake id (D-07). Recipients resolve ONLY from ACTIVE
    memberships of the intake's own space (D-06). The CTA is the token-free
    ``{app_base_url}/intake/{intake_id}/results`` app route (NOTIF-01). On a successful
    send the ``results_link_sent_at`` column is stamped + a ``mail.sent`` audit row (no
    link) written; on failure neither is (D-16 / Pitfall 1).

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    return _run_intake_send(
        intake_id, body, repo, identity, is_reminder=False, is_results=True
    )


@intake_router.post("/{intake_id}/mail/intake")
def send_intake_mail(
    intake_id: str,
    body: MailRecipients,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Send the intake-invite mail (draft only); writes NO timestamp column.

    404 on a cross-space/unknown intake id (existence-hidden, D-07). 409 when the
    intake is not in ``draft`` — the invite only makes sense before the client has
    submitted (the transition-guard idiom, 260716-ji9). Recipients resolve ONLY from
    ACTIVE memberships of the intake's own space (D-06). The CTA is the token-free
    ``{app_base_url}/intake/{intake_id}`` app route (NOTIF-01). On a successful send
    a ``mail.sent`` audit row (no link) is written; there is no intake-sent-at column
    (no migration — like the reminder path), so nothing is stamped.

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    return _run_intake_send(
        intake_id,
        body,
        repo,
        identity,
        is_reminder=False,
        is_results=False,
        is_intake=True,
    )


def _run_intake_send(
    intake_id: str,
    body: MailRecipients,
    repo: IntakeRepository,
    identity: Identity,
    *,
    is_reminder: bool,
    is_results: bool,
    is_intake: bool = False,
) -> dict:
    """404-gate the intake then render+send; stamp+audit on 2xx only (shared verb body).

    The single body the three send endpoints delegate to: ``repo.get`` 404-gates a
    cross-space/unknown intake id (existence-hidden, D-07 / T-10-06), recipient emails are
    resolved server-side from ACTIVE memberships (D-06), the mail is sent FIRST, and only
    on success is the sent-at column stamped (validation/results) and a ``mail.sent``
    audit row written with structured metadata (no link/token). A send failure returns
    ``{"success": False}`` with no timestamp / no audit (D-16 / Pitfall 1).
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Draft-only gate for the intake-invite type (260716-ji9) — the transition-guard
    # idiom (cf. _next_submit_status). The other three types stay ungated (parity).
    if is_intake and intake.status != "draft":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot send the intake mail in status {intake.status!r}",
        )

    # (email, locale) per active recipient — locale resolved SERVER-SIDE per recipient
    # (membership.locale -> space default_locale -> "nl"), NEVER from the sending admin's UI
    # (D-07 / T-11-11). Same 422 rejection of foreign/deactivated/email-less ids as before.
    recipients = _resolve_recipient_locales(
        repo.session, intake.space_id, body.recipients
    )
    # Group emails by their resolved locale so we render+send once per distinct locale.
    emails_by_locale: dict[str, list[str]] = {}
    for email, locale in recipients:
        emails_by_locale.setdefault(locale, []).append(email)
    total_recipients = len(recipients)

    settings = get_settings()
    # WR-01 / D-16: every client-facing CTA is `{app_base_url}/intake/...`. With
    # APP_BASE_URL unset the link degrades to a relative `/intake/{id}` (dead in every mail
    # client) and the logo renders `None/agenic-logo.png`. Refuse the send (like
    # `_send_admin_validated` refuses when NESTOR_ADMIN_EMAIL is unset) so we NEVER stamp a
    # sent-at for a broken mail — mirrors the transport-failure `{"success": False}` shape.
    if not settings.app_base_url:
        _log.warning(
            "APP_BASE_URL unset — refusing mail send for intake %s", intake.id
        )
        return {"success": False}
    base = settings.app_base_url.rstrip("/")
    client = intake.client_name or "team"

    # cta_url + mail_type + timestamp_field are locale-INDEPENDENT; only the rendered body
    # and the subject line vary per recipient locale (below).
    if is_results:
        cta_url = f"{base}/intake/{intake.id}/results"
        mail_type = "results"
        timestamp_field: str | None = "results_link_sent_at"
    elif is_intake:
        cta_url = f"{base}/intake/{intake.id}"
        mail_type = "intake"
        timestamp_field = None  # no intake-sent-at column (no migration, 260716-ji9)
    else:
        cta_url = f"{base}/intake/{intake.id}"
        mail_type = "reminder" if is_reminder else "validation"
        timestamp_field = None if is_reminder else "validation_link_sent_at"

    # SEND FIRST (D-16 / Pitfall 1): render + send ONCE PER DISTINCT LOCALE GROUP so each
    # recipient gets the variant for their OWN resolved locale (never the sending admin's).
    # A non-2xx on ANY group raises → NO timestamp, NO audit row (the whole send is a
    # non-send; the failure path is preserved exactly). Deterministic locale order for a
    # stable, testable send sequence.
    try:
        for locale in sorted(emails_by_locale):
            group_emails = emails_by_locale[locale]
            subject = _subject_for(locale, mail_type, client)
            if is_results:
                html = mail_render.render_results(
                    first_name=client,
                    project_title=client,
                    cta_url=cta_url,
                    app_base_url=settings.app_base_url,
                    locale=locale,
                )
            elif is_intake:
                html = mail_render.render_intake(
                    first_name=client,
                    project_title=client,
                    cta_url=cta_url,
                    app_base_url=settings.app_base_url,
                    locale=locale,
                )
            else:
                html = mail_render.render_validation(
                    first_name=client,
                    project_title=client,
                    cta_url=cta_url,
                    is_reminder=is_reminder,
                    app_base_url=settings.app_base_url,
                    locale=locale,
                )
            mail_resend.send(to=group_emails, subject=subject, html=html)
    except Exception:  # noqa: BLE001 -- any transport failure is a non-send.
        _log.warning("mail send failed for intake %s (type=%s)", intake.id, mail_type)
        return {"success": False}

    # 2xx only: stamp the sent-at column ONCE (not per locale group) then audit on the SAME
    # tx. recipient_count is the TOTAL across all locale groups (D-16 audit contract).
    if timestamp_field is not None:
        repo.patch(intake_id, **{timestamp_field: datetime.now(timezone.utc)})
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="mail.sent",
        target=str(intake_id),
        space_id=intake.space_id,
        metadata={"type": mail_type, "recipient_count": total_recipients},
    )
    return {"success": True, "recipient_count": total_recipients, "type": mail_type}


# ---------------------------------------------------------------------------
# Skill-run progress SSE stream (API-04) + full-run read (D-08)
# ---------------------------------------------------------------------------
#
# The stream is the DB-backed, stateless, tenant-scoped replacement for the interim 5s poll
# (and the retired Supabase Realtime subscription). Statelessness (criterion #2) and
# cross-tenant denial (criterion #3) hold BY CONSTRUCTION: every tick is a fresh scoped
# SELECT via ``read_latest_run_dict`` (no in-memory run state — a reconnecting client on any
# instance sees identical state), and a cross-space intake is an existence-hidden 404 raised
# in the pre-flight BEFORE any stream opens (D-04).
#
# Injectable knobs (module-level so tests can ``monkeypatch`` them tiny — RESEARCH Pitfall 4):
TICK_SECONDS = 2.0  # D-07 — one indexed SELECT every 2s
HEARTBEAT_SECONDS = 15.0  # D-06 — ``: ping`` keeps proxies/Cloud Run from reaping idle streams
MAX_STREAM_SECONDS = 10 * 60  # D-07 — in-handler cap (MAX_POLL_MS parity); a run this long hung
# The ONLY terminal statuses (D-05 / skill-run-status-succeeded-contract) — verbatim, no synonyms.
TERMINAL = {"succeeded", "failed"}
# Defeat proxy buffering so events arrive live per-tick, not in a burst at close (Pitfall 3).
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_data(view: dict | None) -> str:
    """Frame one SSE data event. ``view`` may be ``None`` → emits ``data: null`` (Open Q2)."""
    return f"data: {json.dumps(view)}\n\n"


@intake_router.get("/{intake_id}/skill-runs/stream")
async def stream_skill_runs(
    intake_id: str,
    request: Request,
    identity: Identity = Depends(get_current_identity),
) -> StreamingResponse:
    """Stream the intake's latest skill-run status as ``text/event-stream`` (API-04).

    The codebase's FIRST and ONLY ``async def`` handler (deliberate, surgical): every DB
    touch goes through :func:`run_in_threadpool` so the blocking pg8000 read never runs on
    the event loop, and ``anyio.sleep`` between ticks releases the thread (Pitfall 1). Do
    NOT convert any other handler to async.

    PRE-FLIGHT (D-04, runs BEFORE the stream opens so the denial test is a plain GET):
    ``check_intake_in_scope`` in the threadpool — a ``PermissionError`` (null-space user)
    → 403, a falsy result (cross-tenant / missing) → existence-hidden 404.

    STREAM: a snapshot event at connect, then data events only when the DB state differs
    from the last sent (emit-on-change, D-06), a ``: ping`` comment every ~15s, and a hard
    10-min cap. Closes on the terminal event (``succeeded``/``failed``) or on client
    disconnect. This handler is defined BEFORE ``get_skill_run_full`` so the literal
    ``/skill-runs/stream`` route is matched before the parameterized ``/skill-runs/{run_id}``.
    """
    # Pre-flight in-scope 404/403 (D-04) — the sync/pg8000 read runs in the threadpool.
    try:
        in_scope = await run_in_threadpool(check_intake_in_scope, identity, intake_id)
    except PermissionError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No space — not authorized")
    if not in_scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    async def event_gen():
        started = anyio.current_time()
        last_beat = started
        # Snapshot at connect (D-06). view may be None → ``data: null``.
        view = await run_in_threadpool(read_latest_run_dict, identity, intake_id)
        yield _sse_data(view)
        last_sent = view
        if view is not None and view["status"] in TERMINAL:
            return
        while True:
            if await request.is_disconnected():  # free abandoned streams promptly
                return
            if anyio.current_time() - started > MAX_STREAM_SECONDS:  # 10-min cap (D-07)
                return
            await anyio.sleep(TICK_SECONDS)  # thread released here
            if await request.is_disconnected():  # re-check post-sleep — skip the wasted read
                return
            view = await run_in_threadpool(read_latest_run_dict, identity, intake_id)
            if view != last_sent:  # emit-on-change (D-06)
                yield _sse_data(view)
                last_sent = view
                # Reset the heartbeat clock on ANY frame — the invariant is "some byte
                # every ~15s", so a data emit defers the next ping just like a ping does.
                last_beat = anyio.current_time()
                if view is not None and view["status"] in TERMINAL:
                    return
            elif anyio.current_time() - last_beat >= HEARTBEAT_SECONDS:
                yield ": ping\n\n"  # comment heartbeat (D-06)
                last_beat = anyio.current_time()

    return StreamingResponse(
        event_gen(), media_type="text/event-stream", headers=SSE_HEADERS
    )


@intake_router.get("/{intake_id}/skill-runs/{run_id}")
def get_skill_run_full(
    intake_id: str,
    run_id: str,
    repo: SkillRunRepository = Depends(get_skill_run_repo),
    identity: Identity = Depends(get_current_identity),
) -> SkillRunFullView:
    """Read ONE skill run's full projection within scope, or 404 (D-08 / D-04).

    A sibling of :func:`list_skill_runs` (same router, same scoped repo). ``repo.get`` is
    space-scoped, so a cross-tenant ``run_id`` returns ``None`` → existence-hidden 404. A
    run whose ``intake_id`` does not match the path ``intake_id`` is ALSO a 404 (the BOLA
    guard — never leak that the run exists under a different intake). Projects
    ``output_parsed`` + ``cost_estimate_usd`` (Numeric → float) for the AIReviewPanel.

    WHAT IS WITHHELD, AND FROM WHOM (D-23.2-03). ``output_parsed`` is the model's raw
    output, and two of its seven top-level members are the admin-only bias-radar and
    blind-spots analysis (F-01 hop 2). A non-superadmin receives the remaining five;
    a superadmin receives all seven, which is what ``AIReviewPanel.tsx:114-129`` renders.
    The drop rule is DERIVED from the canonical schema's ``admin_only`` sections — see
    :func:`_visible_output_parsed` for why a plain membership test is not enough.

    The route stays OPEN to ``role=user`` — EXACTLY 200 (pinned client route row 8; the
    client form's proposal tick reads it). This is a body projection, never a gate, and the
    404 arms above are untouched.
    """
    run = repo.get(run_id)
    if run is None or str(run.intake_id) != intake_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Skill run not found")
    return SkillRunFullView(
        id=str(run.id),
        output_parsed=_visible_output_parsed(run.output_parsed, role=identity.role),
        cost_estimate_usd=(
            float(run.cost_estimate_usd) if run.cost_estimate_usd is not None else None
        ),
    )


# ---------------------------------------------------------------------------
# Status transitions (discrete named verbs, allow-listed to <= decomposed)
# ---------------------------------------------------------------------------
#
# The transition maps are the data-layer enforcement of the scope ceiling (INTAKE-05 /
# T-06-06): the ONLY reachable targets are the in-scope ``<= decomposed`` statuses. A
# status with no entry raises 409 — so a jump toward the out-of-scope later stages is
# STRUCTURALLY impossible here, not merely blocked by CI. Discrete ``/submit`` / ``/review``
# verbs (NOT a generic ``PATCH status``) keep each transition a single allow-listed step and
# a natural audit call-site.
_SUBMIT_TRANSITIONS: dict[str, str] = {
    "draft": "submitted",
    "reviewed": "validated_by_client",
}
_REVIEW_TRANSITIONS: dict[str, str] = {
    "submitted": "reviewed",
}
# The SOLE in_research -> delivered transition (REPORT-01 / D-01). Run `completed` NEVER
# auto-delivers — the explicit Deliver verb owns this flip (PROJECT.md v1.1 / 16-CONTEXT).
# A jump from any other status raises 409, so the delivery wall is structural, not merely
# gated by CI (mirrors _SUBMIT_TRANSITIONS / _REVIEW_TRANSITIONS).
_DELIVER_TRANSITIONS: dict[str, str] = {"in_research": "delivered"}


def _next_submit_status(current: str) -> str:
    """Return the submit-transition target for ``current``, or 409 if not allow-listed."""
    try:
        return _SUBMIT_TRANSITIONS[current]
    except KeyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot submit an intake in status {current!r}",
        )


def _next_review_status(current: str) -> str:
    """Return the review-transition target for ``current``, or 409 if not allow-listed."""
    try:
        return _REVIEW_TRANSITIONS[current]
    except KeyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot review an intake in status {current!r}",
        )


@intake_router.post("/{intake_id}/submit")
def submit_intake(
    intake_id: str,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> IntakeView:
    """Advance an intake along the submit transition (``draft`` -> ``submitted`` or
    ``reviewed`` -> ``validated_by_client``), auditing the change in the SAME tx.

    404 if the (in-scope) intake does not exist (D-07); 409 if the current status is not in
    the submit allow-list (the scope-ceiling wall — T-06-06). The ``audit_log`` row is
    written on ``repo.session`` so it commits/rolls back together with the status change
    (one-tx, QA-04 / Pitfall 2). ``metadata`` is structured ``{"from","to"}`` only — never a
    link or token (T-06-09).
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    old_status = intake.status
    new_status = _next_submit_status(old_status)
    repo.patch(intake_id, status=new_status)
    audit.log(repo.session, actor_uid=identity.uid,
              event_type="intake.status_changed", target=str(intake_id),
              space_id=intake.space_id,
              metadata={"from": old_status, "to": new_status})

    # admin_validated auto-fire (D-03 / RESEARCH Pattern 4): when the client's submit
    # advances reviewed → validated_by_client, notify the ops address. This is fire-and-
    # forget from the CLIENT's perspective — a mail failure must NEVER fail the validate
    # (Pitfall 4). It is wrapped in try/except so the handler still returns the
    # transitioned view; it does NOT share a tx that would roll back the status change on
    # a mail error (the send is the LAST thing, after the status flip + audit).
    if new_status == "validated_by_client":
        try:
            _send_admin_validated(intake)
        except Exception:  # noqa: BLE001 -- operator-mail failure is silent-logged (Pitfall 4)
            _log.warning(
                "admin_validated mail failed for intake %s (client validate unaffected)",
                intake_id,
            )

    updated = repo.get(intake_id)
    if updated is None:  # pragma: no cover - patched row is in-scope by construction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(updated)


def _send_admin_validated(intake) -> None:
    """Fire the ``admin_validated`` ("klant heeft gevalideerd") ops mail (D-03 / D-08).

    Reads the single ops address from ``get_settings().nestor_admin_email`` (D-08); if it
    is unset, LOG and RETURN (do NOT raise — an unconfigured ops address must not fail the
    client's validate). The CTA is the admin app route
    ``{app_base_url}/admin/pulse/intakes/{intake_id}`` (token-free, NOTIF-01). Renders and
    sends via the faked Resend seam. The CALLER wraps this in try/except so ANY failure
    here (including a raised send) never fails the client's submit (Pitfall 4).
    """
    settings = get_settings()
    admin_email = settings.nestor_admin_email
    if not admin_email:
        _log.info(
            "NESTOR_ADMIN_EMAIL unset — skipping admin_validated mail for intake %s",
            intake.id,
        )
        return

    base = (settings.app_base_url or "").rstrip("/")
    client = intake.client_name or "team"
    html = mail_render.render_admin_validated(
        client_name=client,
        project_title=client,
        cta_url=f"{base}/admin/pulse/intakes/{intake.id}",
        app_base_url=settings.app_base_url,
    )
    mail_resend.send(
        to=[admin_email],
        subject=_SUBJECT_ADMIN_VALIDATED.format(client=client),
        html=html,
    )


@intake_router.post("/{intake_id}/review")
def review_intake(
    intake_id: str,
    identity: Identity = Depends(superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Advance an intake along the review transition (``submitted`` -> ``reviewed``),
    auditing the change in the SAME tx.

    404 if the (in-scope) intake does not exist (D-07); 409 if the current status is not in
    the review allow-list. The ``audit_log`` row is written on ``repo.session`` (one-tx,
    QA-04 / Pitfall 2); ``metadata`` is structured ``{"from","to"}`` only (T-06-09).

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied here, not at the
    scope check. The gate is declared BEFORE ``get_tenant_repo`` so it resolves first and
    a null-space caller gets that 404 rather than the repo's null-space 403, which would
    leak that this endpoint exists.
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    old_status = intake.status
    new_status = _next_review_status(old_status)
    repo.patch(intake_id, status=new_status)
    audit.log(repo.session, actor_uid=identity.uid,
              event_type="intake.status_changed", target=str(intake_id),
              space_id=intake.space_id,
              metadata={"from": old_status, "to": new_status})

    updated = repo.get(intake_id)
    if updated is None:  # pragma: no cover - patched row is in-scope by construction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(updated)


# ---------------------------------------------------------------------------
# Human-report delivery lifecycle (REPORT-01/02/03 / D-01..D-11) — Phase 18
# ---------------------------------------------------------------------------
#
# The superadmin stages the externally-crafted final report PDF through the existing storage
# seam (server-authored key {space_id}/{intake_id}/reports/{uuid}-{name}.pdf), then explicitly
# DELIVERS: a single verb that (1) links the staged file as a research_artifacts `report` row,
# (2) flips the SOLE in_research -> delivered transition, (3) audits in the SAME tx, and only
# THEN (4) sends the client the results-family mail deep-linking to the client report page.
# Replace repoints the report post-delivery without changing status (D-04/D-05); the client
# read is invisible (404) for every status other than exactly `delivered` (REPORT-02, absolute).


def _report_filename(storage_path: str) -> str:
    """Recover a human download filename from a server-authored report object key.

    Copies :func:`app.api.storage_routes._filename_from_key` verbatim so this module imports
    NO route-module symbol. ``build_object_key`` produces ``.../{uuid4}-{sanitized_name}``;
    strip the trailing path segment and drop the ``{uuid4}-`` prefix. Falls back to the last
    path segment (or ``"download"``).
    """
    tail = storage_path.rsplit("/", 1)[-1] or "download"
    # The uuid4 prefix is 36 chars + a single '-'; split once past it if present.
    if len(tail) > 37 and tail[36] == "-":
        candidate = tail[37:]
        if candidate:
            return candidate
    return tail


def _assert_report_key(intake, storage_path: str) -> None:
    """Reject a non-PDF (422, D-10) or a forged / cross-prefix report key (404, D-08).

    Server-side PDF-only enforcement (``storage_path.lower().endswith(".pdf")``) — not just
    the file input — is the D-10 wall a crafted request cannot bypass. The prefix-assert
    (``{space_id}/{intake_id}/reports/``) denies a storage_path aimed at another tenant's
    tree (or another intake's) with an existence-hidden 404 BEFORE any artifact row is linked
    (D-08 — the storage-route prefix-assert idiom applied at the write).
    """
    if not storage_path.lower().endswith(".pdf"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "Report must be a PDF"
        )
    prefix = f"{intake.space_id}/{intake.id}/reports/"
    if not storage_path.startswith(prefix):
        # A forged / cross-tenant / cross-intake key on an owned intake — existence hidden.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Object not found")


def _create_report_artifact(session, identity: Identity, intake, storage_path: str):
    """Create the report ``research_artifacts`` row in the intake's OWN space; return it.

    Superadmin-safe (Pitfall 4 / T-18-06): a superadmin has a null-space repo, so a plain
    ``create()`` would hit the ``RuntimeError`` guard (repository.py:167) -> 500; it must use
    ``create_in_space(intake.space_id, ...)``. A user writes via ``create()`` (space_id
    injected from the verified Identity, TENANT-02). Mirrors the role-branch every other
    create site uses (``storage_routes`` audio row, ``create_running_skill_run``,
    ``research_routes`` run row). The row carries ``artifact_type="report"`` /
    ``source="human-report"`` (distinct from the context-pack ``source`` so the two never
    collide, D-11 single-report) and ``mime_type="application/pdf"``.
    """
    values = dict(
        intake_id=intake.id,
        artifact_type="report",
        source="human-report",
        storage_path=storage_path,
        filename=_report_filename(storage_path),
        mime_type="application/pdf",
    )
    artifact_repo = ResearchArtifactRepository(session, identity)
    if identity.role == "superadmin":
        # No own space — write into the intake's OWN space (audited superadmin path).
        return artifact_repo.create_in_space(intake.space_id, **values)
    return artifact_repo.create(**values)  # space_id injected from Identity


def _send_report_mail(session, identity: Identity, intake, recipient_ids: list[str]) -> bool:
    """Send the results-family delivery mail with a ``/report`` CTA; return the sent flag.

    Reuses the ``_run_intake_send`` mail body, changing ONLY the CTA path
    (``/intake/{id}/report``, NOT ``/results`` — the client report page, D-07). Recipients are
    resolved SERVER-SIDE from ACTIVE memberships of the intake's OWN space (D-06); a
    foreign/deactivated/email-less id 422s the whole batch (the resolver raises). With
    ``APP_BASE_URL`` unset the send is refused (WR-01 — never a dead-link mail). A transport
    failure returns ``False`` (the caller leaves the delivery committed + ``results_link_sent_at``
    NULL — recoverable, T-18-05). On a 2xx send a ``mail.sent`` audit row is written on the
    SAME ``session``.
    """
    recipients = _resolve_recipient_locales(session, intake.space_id, recipient_ids)
    emails_by_locale: dict[str, list[str]] = {}
    for email, locale in recipients:
        emails_by_locale.setdefault(locale, []).append(email)
    total_recipients = len(recipients)

    settings = get_settings()
    if not settings.app_base_url:
        _log.warning(
            "APP_BASE_URL unset — refusing report delivery mail for intake %s", intake.id
        )
        return False
    base = settings.app_base_url.rstrip("/")
    client = intake.client_name or "team"
    cta_url = f"{base}/intake/{intake.id}/report"  # /report (client report page), NOT /results

    try:
        for locale in sorted(emails_by_locale):
            subject = _subject_for(locale, "results", client)
            html = mail_render.render_results(
                first_name=client,
                project_title=client,
                cta_url=cta_url,
                app_base_url=settings.app_base_url,
                locale=locale,
            )
            mail_resend.send(to=emails_by_locale[locale], subject=subject, html=html)
    except Exception:  # noqa: BLE001 -- any transport failure is a non-send (recoverable).
        _log.warning("report delivery mail failed for intake %s", intake.id)
        return False

    audit.log(
        session,
        actor_uid=identity.uid,
        event_type="mail.sent",
        target=str(intake.id),
        space_id=intake.space_id,
        metadata={"type": "results", "recipient_count": total_recipients},
    )
    return True


@intake_router.post("/{intake_id}/deliver")
def deliver_report(
    intake_id: str,
    body: DeliverBody,
    identity: Identity = Depends(superadmin_gate),
) -> IntakeView:
    """Deliver the staged report: link it, flip in_research -> delivered, mail the client.

    REPORT-01 / D-01: the SOLE ``in_research -> delivered`` transition (run ``completed``
    never auto-delivers). 404 on a cross-space/unknown intake (existence-hidden, D-07); 409 on
    any status other than ``in_research``; 422 on a non-PDF key (D-10); 404 on a forged /
    cross-prefix key (D-08).

    ORDERING (RESEARCH A3 / Pitfall 3 — the delivery is the primary effect): the artifact
    create + status flip + audit run in ONE committed tenant transaction FIRST; the mail is
    sent LAST and ``results_link_sent_at`` is stamped only on a 2xx send. A mail failure leaves
    the intake ``delivered`` with ``results_link_sent_at`` NULL — a recoverable
    ``awaiting_results_send`` the phase machine surfaces (T-18-05). Because the send runs after
    the commit, a bad recipient id 422s AFTER the report is already delivered (the operator
    simply re-sends) — the report reaching the client is never held hostage to the mail.

    The flip+link+audit and the mail run in SEPARATE ``tenant_session`` transactions on
    purpose: the artifact write + the intake patch must commit TOGETHER (one tx) BEFORE the
    mail is attempted. This mirrors ``research_routes.trigger`` (committed-before-schedule) and
    is why a request-injected repo (its own separate tx) is NOT used for the write here.

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied before the
    handler body opens its ``tenant_session`` at all.
    """
    # (1) Flip + link + audit — ONE committed tenant tx (the primary delivery effect).
    with tenant_session(identity) as txs:
        intake = IntakeRepository(txs, identity).get(intake_id)
        if intake is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        if intake.status not in _DELIVER_TRANSITIONS:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot deliver in status {intake.status!r}",
            )
        _assert_report_key(intake, body.storage_path)

        old_status = intake.status
        new_status = _DELIVER_TRANSITIONS[old_status]
        artifact = _create_report_artifact(txs, identity, intake, body.storage_path)
        IntakeRepository(txs, identity).patch(
            intake_id, status=new_status, final_report_artifact_id=artifact.id
        )
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="intake.status_changed",
            target=str(intake_id),
            space_id=intake.space_id,
            metadata={"from": old_status, "to": new_status},
        )

    # (2) Mail LAST — in its OWN tx, after the delivery is committed. A failure here leaves the
    # intake delivered + results_link_sent_at NULL (recoverable). The mail.sent audit + the
    # results_link_sent_at stamp are written only on a 2xx send, in the send tx.
    with tenant_session(identity) as txs:
        intake = IntakeRepository(txs, identity).get(intake_id)
        if intake is None:  # pragma: no cover - just-committed row is in-scope
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        if _send_report_mail(txs, identity, intake, body.recipients):
            IntakeRepository(txs, identity).patch(
                intake_id, results_link_sent_at=datetime.now(timezone.utc)
            )

    # (3) Re-read the now-delivered intake for the response projection.
    with tenant_session(identity) as txs:
        updated = IntakeRepository(txs, identity).get(intake_id)
        if updated is None:  # pragma: no cover - delivered row is in-scope by construction
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        return _view(updated)


@intake_router.post("/{intake_id}/report/replace")
def replace_report(
    intake_id: str,
    body: DeliverBody,
    identity: Identity = Depends(superadmin_gate),
) -> IntakeView:
    """Repoint the delivered report to a NEW file; status stays ``delivered`` (D-04/D-05).

    404 on a cross-space/unknown intake (D-07); 409 unless the current status is exactly
    ``delivered`` (there is nothing to replace before delivery); 422 on a non-PDF key (D-10);
    404 on a forged / cross-prefix key (D-08). A NEW ``research_artifacts`` row is created and
    ``final_report_artifact_id`` is repointed to it — the OLD artifact row + its GCS object are
    kept (D-04 / A7 audit posture, no delete). ``status`` is UNTOUCHED (no transition verb).

    Re-notify (D-05): if ``recipients`` is non-empty the SAME results-family mail is re-sent
    (``/report`` CTA) and ``results_link_sent_at`` re-stamped on a 2xx; an empty
    ``recipients`` is a SILENT replace (the default path — the client gets the newest file with
    no fresh mail). A mail failure leaves the (already committed) new link intact.

    SUPERADMIN-ONLY via ``superadmin_gate`` (existence-hidden 404, D-23.1-02): a
    role=``user`` caller — including the intake's own client — is denied before the
    handler body opens its ``tenant_session`` at all.
    """
    # (1) Repoint + audit — ONE committed tenant tx (status stays delivered).
    with tenant_session(identity) as txs:
        intake = IntakeRepository(txs, identity).get(intake_id)
        if intake is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        if intake.status != "delivered":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Cannot replace in status {intake.status!r}",
            )
        _assert_report_key(intake, body.storage_path)

        artifact = _create_report_artifact(txs, identity, intake, body.storage_path)
        IntakeRepository(txs, identity).patch(
            intake_id, final_report_artifact_id=artifact.id
        )
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="report.replaced",
            target=str(intake_id),
            space_id=intake.space_id,
            metadata={"artifact_id": str(artifact.id)},
        )

    # (2) Optional re-notify (D-05) — only when recipients were supplied.
    if body.recipients:
        with tenant_session(identity) as txs:
            intake = IntakeRepository(txs, identity).get(intake_id)
            if intake is None:  # pragma: no cover - just-committed row is in-scope
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
            if _send_report_mail(txs, identity, intake, body.recipients):
                IntakeRepository(txs, identity).patch(
                    intake_id, results_link_sent_at=datetime.now(timezone.utc)
                )

    with tenant_session(identity) as txs:
        updated = IntakeRepository(txs, identity).get(intake_id)
        if updated is None:  # pragma: no cover - delivered row is in-scope by construction
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        return _view(updated)


@intake_router.get("/{intake_id}/report")
def get_report(
    intake_id: str,
    repo: ResearchArtifactRepository = Depends(get_research_artifact_repo),
    identity: Identity = Depends(get_current_identity),
) -> ReportView:
    """Return the delivered report's metadata — 404 unless status is EXACTLY ``delivered``.

    REPORT-02 (absolute invisibility gate, Pitfall 2 / T-18-01): the report is 404 for EVERY
    status other than exactly ``delivered`` — an EQUALITY check, NEVER a rank/``>=`` comparison
    that would leak the report at an earlier lifecycle stage. The intake is read through a
    scoped ``IntakeRepository`` sharing the artifact repo's session, so a cross-space/unknown
    intake is an existence-hidden 404 too (T-18-02). A ``delivered`` intake with no linked
    artifact (``final_report_artifact_id`` NULL) is also 404 (no report to show). The linked
    artifact is fetched within the SAME scoped repo (its ``_scope`` walls a cross-tenant
    artifact id); ``delivered_at`` mirrors ``results_link_sent_at`` (the delivery-mail stamp).

    ``storage_path`` IS returned (unlike the context-pack view) because the client download
    flow feeds it back to ``GET /intakes/{id}/storage/signed-url?path=...``, whose own
    prefix-assert walls a forged key — and the client only ever receives its OWN report's key.
    """
    # Read the intake through a scoped IntakeRepository on the SAME session the artifact repo
    # already holds (its space GUC / superadmin routing is set). One scoped tx for the read.
    intake = IntakeRepository(repo.session, identity).get(intake_id)
    if intake is None or intake.status != "delivered":
        # Existence-hidden AND pre-delivery invisible — one code for both (REPORT-02).
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    if intake.final_report_artifact_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")

    artifact = repo.get(intake.final_report_artifact_id)
    if artifact is None:  # a linked-but-missing artifact row — hide it (D-07)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")

    return ReportView(
        filename=artifact.filename,
        delivered_at=(
            intake.results_link_sent_at.isoformat()
            if intake.results_link_sent_at
            else None
        ),
        byte_size=artifact.byte_size,
        mime_type=artifact.mime_type,
        storage_path=artifact.storage_path,
    )
