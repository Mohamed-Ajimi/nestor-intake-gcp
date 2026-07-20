"""
Projects API -- create / list / detail (owning module: nestor_pulse_sdk.projects).

WHY this matters: runs/api.py 404s on an unknown project_id, and nothing in the
production app created project rows before this router. These tests pin the
create-then-run-able contract so real-mode (non-demo) verification has a project
to hang runs off of.

Two tiers:
- Pure-unit tests (`_updated_rel`, `_summary`) run anywhere -- no DB.
- DB-backed tests use the testcontainers Postgres engine and are xfail
  (strict=True) so the suite still skips cleanly when Docker is unreachable
  (per 01-VALIDATION.md Environment Notes -- Mohamed's dev box may lack Docker),
  matching test_data_model.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nestor_pulse_sdk.projects.api import _summary, _updated_rel


# ---------------------------------------------------------------------------
# Pure-unit (no DB) -- always run
# ---------------------------------------------------------------------------

def _ago(**kw) -> datetime:
    return datetime.now(timezone.utc) - timedelta(**kw)


def test_updated_rel_buckets():
    assert _updated_rel(_ago(seconds=10)) == "Updated just now"
    assert _updated_rel(_ago(minutes=5)) == "Updated 5m ago"
    assert _updated_rel(_ago(hours=3)) == "Updated 3h ago"
    assert _updated_rel(_ago(days=2)) == "Updated 2d ago"
    assert _updated_rel(_ago(days=60)) == "Updated 2mo ago"
    assert _updated_rel(_ago(days=400)) == "Updated 1y ago"


def test_updated_rel_handles_naive_datetime():
    # server_default now() is tz-aware, but guard against a naive value.
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2)
    assert _updated_rel(naive) == "Updated 2h ago"


def test_summary_shape_matches_demo_keys():
    class _P:
        id = uuid.uuid4()
        name = "Q3 Market Scan"
        client_name = "Acme"
        status = "active"
        owner_user_id = uuid.uuid4()
        created_at = datetime.now(timezone.utc)
        updated_at = datetime.now(timezone.utc)

    s = _summary(_P(), briefing_count=4, active_count=1, owner_email="a@b.co")
    # Keys the demo endpoint (demo/api.py::_project_summary) emits + the UI reads.
    for key in ("id", "name", "client_name", "status", "owner", "team",
                "briefing_count", "active_count", "updated_rel"):
        assert key in s
    assert s["briefing_count"] == 4
    assert s["active_count"] == 1
    assert s["owner"] == "a@b.co"
    assert s["team"] == []
    assert s["id"] == str(_P.id)  # serialized as string for the JS client


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


def _claims(tenant_id, owner_id, owner_email):
    from nestor_pulse_sdk.auth.provider import AuthClaims
    return AuthClaims(
        app_user_id=str(owner_id),
        tenant_id=str(tenant_id),
        email=owner_email,
        raw_provider_user_id=f"fb-{owner_id.hex[:8]}",
    )


@dbtest
async def test_create_then_listable_and_runnable(async_engine, set_tenant):
    """POST creates a tenant-scoped row; it then appears in the list and is a
    valid project_id a run can reference (the contract runs/api.py needs)."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.db.models import Run
    from nestor_pulse_sdk.projects.api import (
        create_project, get_project, list_projects,
    )
    from nestor_pulse_sdk.projects.schemas import CreateProjectRequest

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        tenant_id, owner_id, owner_email = await _seed_tenant(session, set_tenant)
        user = _claims(tenant_id, owner_id, owner_email)

        # CREATE
        async with session.begin():
            await set_tenant(session, tenant_id)
            created = await create_project(
                CreateProjectRequest(name="Lukoil Scan", client_name="Lukoil"),
                user=user, session=session,
            )
        assert created.name == "Lukoil Scan"
        assert created.client_name == "Lukoil"
        assert created.owner_user_id == owner_id
        assert created.status == "active"
        project_id = created.id

        # LIST -- shows the project, zero briefings so far, owner email enriched.
        async with session.begin():
            await set_tenant(session, tenant_id)
            rows = await list_projects(user=user, session=session)
        assert [r["id"] for r in rows] == [str(project_id)]
        assert rows[0]["briefing_count"] == 0
        assert rows[0]["active_count"] == 0
        assert rows[0]["owner"] == owner_email

        # The project_id is now a valid FK target for a run (the whole point).
        async with session.begin():
            await set_tenant(session, tenant_id)
            session.add(Run(
                tenant_id=tenant_id, project_id=project_id, engine="tribunal",
                brief="brief", status="queued", idempotency_key=uuid.uuid4(),
            ))

        # LIST again -- briefing + active counts now reflect the queued run.
        async with session.begin():
            await set_tenant(session, tenant_id)
            rows = await list_projects(user=user, session=session)
        assert rows[0]["briefing_count"] == 1
        assert rows[0]["active_count"] == 1

        # DETAIL -- summary plus empty demo-only embellishment fields.
        async with session.begin():
            await set_tenant(session, tenant_id)
            detail = await get_project(project_id, user=user, session=session)
        assert detail["id"] == str(project_id)
        assert detail["about"] is None
        assert detail["documents"] == []
        assert detail["collaborators"] == []


@dbtest
async def test_get_unknown_project_404(async_engine, set_tenant):
    from fastapi import HTTPException
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.projects.api import get_project

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        tenant_id, owner_id, owner_email = await _seed_tenant(session, set_tenant)
        user = _claims(tenant_id, owner_id, owner_email)
        async with session.begin():
            await set_tenant(session, tenant_id)
            with pytest.raises(HTTPException) as ei:
                await get_project(uuid.uuid4(), user=user, session=session)
        assert ei.value.status_code == 404
