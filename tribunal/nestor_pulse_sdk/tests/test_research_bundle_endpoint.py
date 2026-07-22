"""``GET /api/runs/{run_id}/research-bundle`` — the Phase-17 raw-output seam (D-01).

WHY this matters: the intake poll driver's finalize step calls this endpoint to
materialize the raw-output bundle. The download must expose ONLY the scrubbed
per-provider research (``cleaned_reports``) — the discredited-content ledger
(``rejected_claims``) is DELIBERATELY EXCLUDED (D-01). These tests pin that
contract, the completed-only gate, and RLS tenant isolation.

Tiers mirror ``test_projects_api.py``:
- DB-backed tests use the testcontainers Postgres engine and are xfail
  (strict=True) so the suite still skips cleanly when Docker is unreachable
  (Mohamed's dev box may lack Docker) — they xpass once the schema + endpoint land.
"""
from __future__ import annotations

import json
import uuid

import pytest


# ---------------------------------------------------------------------------
# DB-backed -- xfail (strict) when Docker is unreachable
# ---------------------------------------------------------------------------

dbtest = pytest.mark.xfail(
    reason="requires Docker + testcontainers Postgres; xpasses with the schema",
    strict=True,
)


async def _seed_tenant(session, set_tenant):
    """Create org + owner app_user, set the RLS tenant context. Returns
    (tenant_id, owner_id, owner_email)."""
    from nestor_pulse_sdk.db.models import Org, User

    tenant_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    owner_email = f"owner-{owner_id.hex[:8]}@example.com"
    async with session.begin():
        session.add(Org(id=tenant_id, name="Acme", slug=f"acme-{tenant_id.hex[:8]}"))
    async with session.begin():
        await set_tenant(session, tenant_id)
        session.add(User(
            id=owner_id,
            tenant_id=tenant_id,
            email=owner_email,
            provider_user_id=f"fb-{owner_id.hex[:8]}",
        ))
    return tenant_id, owner_id, owner_email


async def _seed_run(session, set_tenant, tenant_id, owner_id, *, status, cache_body):
    """Create a project + run (+ optional synthesis_cache Output). Returns run_id."""
    from nestor_pulse_sdk.db.models import Output, Project, Run

    project_id = uuid.uuid4()
    run_id = uuid.uuid4()
    async with session.begin():
        await set_tenant(session, tenant_id)
        session.add(Project(
            id=project_id, tenant_id=tenant_id, name="Scan",
            owner_user_id=owner_id, status="active",
        ))
        session.add(Run(
            id=run_id, tenant_id=tenant_id, project_id=project_id,
            engine="tribunal", brief="brief", status=status,
            idempotency_key=uuid.uuid4(),
        ))
        if cache_body is not None:
            session.add(Output(
                tenant_id=tenant_id, run_id=run_id,
                format="synthesis_cache", body=json.dumps(cache_body),
            ))
    return run_id


def _new_session(async_engine):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    return async_sessionmaker(
        async_engine, class_=AsyncSession, expire_on_commit=False
    )()


# A realistic synthesis_cache body: cleaned_reports survive; rejected_claims must
# NEVER surface in the response (D-01).
_CACHE_BODY = {
    "mission_brief": {"topic": "market scan"},
    "cleaned_reports": [
        ["angle-a", {"report": "verified passage A"}],
        ["angle-b", {"report": "verified passage B"}],
    ],
    "rejected_claims": [{"claim": "discredited — must never leak"}],
    "contested_notes": ["contested — excluded"],
    "verification": {"passed": 2, "dropped": 1},
}


@dbtest
async def test_completed_run_returns_cleaned_reports_only(async_engine, set_tenant):
    """Happy path: cleaned_reports returned; rejected_claims/contested/verification absent."""
    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.runs.api import get_run_research_bundle

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _new_session(async_engine) as session:
        tenant_id, owner_id, _ = await _seed_tenant(session, set_tenant)
        run_id = await _seed_run(
            session, set_tenant, tenant_id, owner_id,
            status="completed", cache_body=_CACHE_BODY,
        )

        async with session.begin():
            await set_tenant(session, tenant_id)
            body = await get_run_research_bundle(run_id, session=session)

    # Only cleaned_reports — every discredited-content key is excluded (D-01).
    assert set(body.keys()) == {"cleaned_reports"}
    assert body["cleaned_reports"] == _CACHE_BODY["cleaned_reports"]
    assert "rejected_claims" not in body
    assert "contested_notes" not in body
    assert "verification" not in body
    # Belt-and-braces: the discredited text never appears anywhere in the response.
    assert "discredited" not in json.dumps(body)


@dbtest
async def test_non_completed_run_409(async_engine, set_tenant):
    """A running/queued run is not downloadable yet -> 409."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.runs.api import get_run_research_bundle

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _new_session(async_engine) as session:
        tenant_id, owner_id, _ = await _seed_tenant(session, set_tenant)
        run_id = await _seed_run(
            session, set_tenant, tenant_id, owner_id,
            status="running", cache_body=None,
        )
        async with session.begin():
            await set_tenant(session, tenant_id)
            with pytest.raises(HTTPException) as ei:
                await get_run_research_bundle(run_id, session=session)
    assert ei.value.status_code == 409


@dbtest
async def test_completed_run_without_cache_409(async_engine, set_tenant):
    """A completed run with no synthesis_cache Output -> 409 (nothing to serve)."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.runs.api import get_run_research_bundle

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _new_session(async_engine) as session:
        tenant_id, owner_id, _ = await _seed_tenant(session, set_tenant)
        run_id = await _seed_run(
            session, set_tenant, tenant_id, owner_id,
            status="completed", cache_body=None,
        )
        async with session.begin():
            await set_tenant(session, tenant_id)
            with pytest.raises(HTTPException) as ei:
                await get_run_research_bundle(run_id, session=session)
    assert ei.value.status_code == 409


@dbtest
async def test_unknown_run_404(async_engine, set_tenant):
    """An unknown run_id -> 404."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.runs.api import get_run_research_bundle

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _new_session(async_engine) as session:
        tenant_id, _, _ = await _seed_tenant(session, set_tenant)
        async with session.begin():
            await set_tenant(session, tenant_id)
            with pytest.raises(HTTPException) as ei:
                await get_run_research_bundle(uuid.uuid4(), session=session)
    assert ei.value.status_code == 404


@dbtest
async def test_cross_tenant_run_not_visible(async_engine, set_tenant):
    """Tenant B cannot read tenant A's completed run — RLS hides it as a 404."""
    from fastapi import HTTPException

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.runs.api import get_run_research_bundle

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with _new_session(async_engine) as session:
        tenant_a, owner_a, _ = await _seed_tenant(session, set_tenant)
        run_id = await _seed_run(
            session, set_tenant, tenant_a, owner_a,
            status="completed", cache_body=_CACHE_BODY,
        )
        # A different tenant B seeded in the SAME session.
        tenant_b, _, _ = await _seed_tenant(session, set_tenant)

        # Reading run A while scoped to tenant B: RLS hides the row -> 404.
        async with session.begin():
            await set_tenant(session, tenant_b)
            with pytest.raises(HTTPException) as ei:
                await get_run_research_bundle(run_id, session=session)
    assert ei.value.status_code == 404
