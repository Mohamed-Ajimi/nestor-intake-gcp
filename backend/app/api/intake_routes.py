"""The real intake feature router — the RPC-equivalent backend (INTAKE-01/02/03/04).

This GENERALIZES the throwaway ``sample_routes.py`` seam-prover into the full
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
event loop (mirrors ``sample_routes.py`` / ``main.py``).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    IntakeTemplateRepository,
    SkillRunRepository,
)
from app.db.session import (
    get_intake_answer_repo,
    get_intake_template_repo,
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


def _template_view(template) -> TemplateView:
    """Project an ``IntakeTemplate`` ORM row onto the template response."""
    return TemplateView(
        id=str(template.id),
        name=template.name,
        schema=template.schema,
    )


# ---------------------------------------------------------------------------
# Collection handlers
# ---------------------------------------------------------------------------


@intake_router.get("")
def list_intakes(
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> list[IntakeView]:
    """List intakes visible to the caller — own-space rows only for a user (TENANT-02).

    The repository applies the explicit ``WHERE space_id =`` for a user (and omits it for a
    superadmin, who reads across spaces). The handler passes NO scope argument.
    """
    return [_view(row) for row in repo.list()]


@intake_router.post("", status_code=status.HTTP_201_CREATED)
def create_intake(
    body: IntakeCreate,
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Create an intake in the caller's space -> ``draft`` (fires ``trg_prefill_intake_answers``).

    ``space_id`` is injected by the repo from the verified Identity — never read from the
    body (TENANT-02). The DB ``server_default`` sets the initial ``draft`` status.
    """
    values = body.model_dump(exclude_unset=True)
    # Coerce an optional template reference to UUID for the pg8000 bind; ``space_id`` is
    # NEVER in ``values`` (not a field on IntakeCreate) — the repo injects it from identity.
    if values.get("template_id"):
        values["template_id"] = uuid.UUID(values["template_id"])
    intake = repo.create(**values)
    return _view(intake)


@intake_router.get("/templates")
def list_templates(
    repo: IntakeTemplateRepository = Depends(get_intake_template_repo),
) -> list[TemplateView]:
    """List the intake templates in the caller's space (own-space only for a user).

    Declared BEFORE ``/{intake_id}`` so the literal ``templates`` segment is not captured
    as a path parameter.
    """
    return [_template_view(row) for row in repo.list()]


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
    repo: IntakeAnswerRepository = Depends(get_intake_answer_repo),
) -> list[AnswerView]:
    """Upsert a section's answers in one round-trip (save-as-you-go, D-03).

    Each item contributes only ``field_key`` / ``value`` / ``value_json``; the repo injects
    ``space_id`` from the verified Identity and ``intake_id`` from the path — never from the
    item dict (T-06-03). The upsert targets the EXISTING ``(intake_id, field_key)`` unique
    constraint, so re-saving a section UPDATES rather than duplicating (Pitfall 6). Returns
    the intake's answers as persisted.
    """
    items = [item.model_dump() for item in body.answers]
    repo.upsert_batch(intake_id, items)
    return [_answer_view(row) for row in repo.list_for_intake(intake_id)]


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
