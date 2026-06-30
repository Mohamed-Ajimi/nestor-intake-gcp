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

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.intake_canonical import (
    CANONICAL_TEMPLATE_ID,
    CANONICAL_TEMPLATE_NAME,
    CANONICAL_TEMPLATE_SCHEMA,
)
from app.db import audit
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    SkillRunRepository,
)
from app.db.session import (
    get_intake_and_answer_repos,
    get_intake_answer_repo,
    get_skill_run_repo,
    get_tenant_repo,
)

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
    value_json: dict | None = None


class AnswerItem(BaseModel):
    """One inbound answer in a section batch. Carries NO ``space_id`` / ``intake_id`` — the
    repo injects ``space_id`` from the Identity and ``intake_id`` from the path (D-03).
    """

    field_key: str
    value: str | None = None
    value_json: dict | None = None


class AnswerBatch(BaseModel):
    """A section's worth of answers to upsert in one round-trip (save-as-you-go, D-03)."""

    answers: list[AnswerItem]


class SkillRunView(BaseModel):
    """Read-shaped view of one skill run — ``status`` is mapped VERBATIM (Pitfall 1)."""

    id: str
    status: str
    applied_at: str | None = None
    completed_at: str | None = None


class SkillRunsView(BaseModel):
    """The skill-run read projection: the latest run plus the full list (newest first)."""

    latest: SkillRunView | None = None
    runs: list[SkillRunView]


class TemplateView(BaseModel):
    """Read-shaped view of an intake template (the form schema the UI renders)."""

    id: str
    name: str
    schema: dict | None = None


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


def _skill_run_view(run) -> SkillRunView:
    """Project a ``SkillRun`` ORM row — ``status`` mapped verbatim, no remap (Pitfall 1)."""
    return SkillRunView(
        id=str(run.id),
        status=run.status,
        applied_at=(run.applied_at.isoformat() if run.applied_at else None),
        completed_at=(run.completed_at.isoformat() if run.completed_at else None),
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
def list_templates() -> list[TemplateView]:
    """Return the single CANONICAL intake template (D-CANON).

    The Pulse intake form is shared product config, identical for every space, so it is
    served from the in-repo canonical asset (``app.intake_canonical``) rather than per-space
    ``intake_templates`` rows — no per-space copies, no operator-edited JSON. EVERY
    authenticated caller (user or superadmin, any space) receives the same template; there
    is no longer a per-space template read here, so the handler needs no repo/scope.

    Declared BEFORE ``/{intake_id}`` so the literal ``templates`` segment is not captured
    as a path parameter.
    """
    return [
        TemplateView(
            id=str(CANONICAL_TEMPLATE_ID),
            name=CANONICAL_TEMPLATE_NAME,
            schema=CANONICAL_TEMPLATE_SCHEMA,
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
) -> list[AnswerView]:
    """Read this intake's answers within scope (own-space only for a user)."""
    return [_answer_view(row) for row in repo.list_for_intake(intake_id)]


@intake_router.patch("/{intake_id}/answers")
def upsert_answers(
    intake_id: str,
    body: AnswerBatch,
    repos: tuple[IntakeRepository, IntakeAnswerRepository] = Depends(get_intake_and_answer_repos),
) -> list[AnswerView]:
    """Upsert a section's answers in one round-trip (save-as-you-go, D-03).

    OWNERSHIP GATE (T-06-20 / D-07): BEFORE any write, ``intake_repo.get`` verifies the
    caller owns ``intake_id`` on the SAME tx as the upsert (the combined dependency yields
    both repos on one session — D-02). A cross-tenant/missing id -> ``None`` -> 404 (never
    403, never 200-with-data). Each item carries only ``field_key`` / ``value`` /
    ``value_json``; the repo injects ``space_id`` (Identity) + ``intake_id`` (path), never
    from the item dict (T-06-03), targeting the ``(intake_id, field_key)`` constraint.
    """
    intake_repo, answers_repo = repos
    # Ownership pre-check (D-07): a cross-tenant/missing id is hidden as 404 BEFORE any write.
    if intake_repo.get(intake_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    items = [item.model_dump() for item in body.answers]
    answers_repo.upsert_batch(intake_id, items)
    return [_answer_view(row) for row in answers_repo.list_for_intake(intake_id)]


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

    updated = repo.get(intake_id)
    if updated is None:  # pragma: no cover - patched row is in-scope by construction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(updated)


@intake_router.post("/{intake_id}/review")
def review_intake(
    intake_id: str,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> IntakeView:
    """Advance an intake along the review transition (``submitted`` -> ``reviewed``),
    auditing the change in the SAME tx.

    404 if the (in-scope) intake does not exist (D-07); 409 if the current status is not in
    the review allow-list. The ``audit_log`` row is written on ``repo.session`` (one-tx,
    QA-04 / Pitfall 2); ``metadata`` is structured ``{"from","to"}`` only (T-06-09).
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
