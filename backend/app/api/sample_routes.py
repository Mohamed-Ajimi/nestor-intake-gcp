"""Throwaway tenant-scoped sample endpoint over ``intakes`` (D-08 scaffolding).

This is DELIBERATELY disposable scaffolding: a minimal list/get/patch surface over
ONE tenant table (``nestor.intakes``) whose only job is to prove the whole Phase 4
stack end-to-end — verified token -> :func:`app.auth.dependencies.get_current_identity`
-> :func:`app.db.session.get_tenant_repo` -> :class:`app.db.repository.IntakeRepository`
(explicit ``WHERE`` + RLS) -> 404/403 HTTP mapping. The full-stack cross-tenant denial
suite (``tests/test_cross_tenant_denial.py``, QA-01) drives exactly these three handlers
as user-A / user-B / superadmin. Phase 6 GENERALIZES this pattern (one feature router +
one ``TenantRepository`` subclass per entity); it does NOT extend THIS module — pull no
research / phase-machine / Tribunal / run-research surface in here (scope ceiling,
INTAKE-05). When the real intake endpoints land in Phase 6 this file is deleted.

Locked decisions realized here (04-CONTEXT.md / 04-RESEARCH.md):

* D-08 — the sample router's handlers acquire data access ONLY via
  ``Depends(get_tenant_repo)``; this module imports NO raw DB symbol
  (``get_engine`` / ``get_superadmin_engine`` / ``sessionmaker`` / ``create_engine`` /
  ``Session``). The D-03 grep-guard (``scripts/ci_no_raw_db_access.sh``) scans ``app/``
  outside ``app/db/`` and would fail the build if any leaked in here.
* TENANT-02 — ``space_id`` is NEVER read from the request (body / path / query). Only the
  path ``intake_id`` flows to ``repo.get`` / ``repo.patch``; the tenant scope comes solely
  from the injected ``Identity`` inside ``get_tenant_repo``. A client cannot target a
  foreign space.
* D-07 — 404 is the ONLY data-route denial code. ``repo.get`` returning ``None`` and
  ``repo.patch`` returning ``rowcount == 0`` (the cross-tenant-by-id outcomes) both map to
  HTTP 404 — never 403, never 200-with-data (existence is hidden; no enumeration via code
  differences). The single 403 in the stack is the null-space default-deny in
  ``get_tenant_repo`` (D-04), not anything here.
* AUTH-01 / D-08 — this router is mounted UNDER ``protected_router`` in ``app/main.py``,
  so it inherits ``Depends(get_current_identity)`` and is never anonymous.

Sync ``def`` handlers (not ``async def``): pg8000 is a blocking driver and FastAPI runs
sync handlers in a threadpool; an ``async def`` calling the sync engine would stall the
event loop (mirrors ``auth_routes.py`` / ``main.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.db.repository import IntakeRepository
from app.db.session import get_tenant_repo

# The sample feature router. It carries NO auth dependency of its own — it is mounted
# UNDER protected_router in app/main.py, inheriting Depends(get_current_identity) (the
# default-deny base), and each handler additionally Depends(get_tenant_repo) for its
# tenant-scoped data access.
sample_router = APIRouter(prefix="/sample", tags=["sample"])


class IntakeView(BaseModel):
    """Read-shaped view of an intake — ONLY intake-shaped fields are returned.

    No relationships, answers, or out-of-scope surface are exposed (scope ceiling).
    """

    id: str
    space_id: str
    status: str
    client_name: str | None = None


class IntakePatch(BaseModel):
    """The benign, in-scope mutable subset for the sample PATCH.

    Only ``status`` / ``client_name`` may be set — NO ``space_id`` (the tenant key is
    never client-supplied, TENANT-02) and no lifecycle/research markers (scope ceiling).
    All fields optional; only those provided are written.
    """

    status: str | None = None
    client_name: str | None = None


def _view(intake) -> IntakeView:
    """Project an ``Intake`` ORM row onto the intake-shaped response (no leakage)."""
    return IntakeView(
        id=str(intake.id),
        space_id=str(intake.space_id),
        status=intake.status,
        client_name=intake.client_name,
    )


@sample_router.get("/intakes")
def list_intakes(
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> list[IntakeView]:
    """List intakes visible to the caller — own-space rows only for a user.

    The repository applies the explicit ``WHERE space_id =`` for a user (and omits it
    for a superadmin, who reads across spaces). The handler passes NO scope argument;
    tenant scope lives entirely in the injected repo (TENANT-02).
    """
    return [_view(row) for row in repo.list()]


@sample_router.get("/intakes/{intake_id}")
def get_intake(
    intake_id: str,
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Get one intake by id within the caller's scope, or 404 (D-07).

    A cross-tenant ``intake_id`` is excluded by the repo's scoped ``WHERE`` (and RLS),
    so ``repo.get`` returns ``None`` — which becomes a 404, NEVER a 403 and NEVER a
    200-with-data (existence is hidden; no BOLA/IDOR disclosure).
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(intake)


@sample_router.patch("/intakes/{intake_id}")
def patch_intake(
    intake_id: str,
    body: IntakePatch,
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> IntakeView:
    """Patch a benign field on an in-scope intake, or 404 (D-07).

    Only the path ``intake_id`` plus the benign body fields flow to the repo — never a
    ``space_id`` from the request (TENANT-02). A cross-tenant id matches the scoped
    ``WHERE`` against nothing, so ``repo.patch`` returns ``rowcount == 0`` and the
    foreign row is left untouched — which the handler maps to 404 (never 403, never a
    silent success).
    """
    # Only forward fields the client actually supplied (exclude_unset) — and NEVER a
    # space_id (it is not even a field on IntakePatch, TENANT-02).
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    rowcount = repo.patch(intake_id, **values)
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Re-read within scope to return the updated, intake-shaped view.
    updated = repo.get(intake_id)
    if updated is None:  # pragma: no cover - patched row is in-scope by construction
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return _view(updated)
