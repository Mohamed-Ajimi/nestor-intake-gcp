"""
Phase 14 (SEAM-02 / D-08) -- tribunal.* cross-tenant RLS DENIAL on the seam-provisioned
tables (owning plan: 14-03 Task 2).

Extends the two-tenant asyncpg harness of ``test_rls_isolation.py`` to the tables the
internal seam provisions -- ``project`` (and ``run``) -- proving that the GUC-name mismatch
firewall holds at the DB layer too: a session scoped to tenant_a NEVER sees tenant_b's
project/run rows, and a session with NO tenant context is denied. ``org.id == space_id``
(identity mapping), so the seam's per-space provisioning lands rows on exactly these
RLS-FORCED tables, and this suite is the DB-side proof that the ensure_org / ensure_project
path (Plan 01) can never leak across tenants.

This is the Tribunal-native half of the SEAM-02 denial gate (D-08: each layer tested in its
native harness, no driver mixing). The intake seam boundary is proven separately in
``backend/tests/test_tribunal_seam_denial.py`` (pg8000 harness). Here we use the SAME async
asyncpg surface as ``test_rls_isolation.py`` -- ``set_tenant_context`` + the ORM models over
``sqlalchemy.ext.asyncio`` -- with ZERO pg8000 anywhere.

What each test proves:

| Test                                      | Threat    | Proves                                   |
|-------------------------------------------|-----------|------------------------------------------|
| test_seam_project_run_cross_tenant_denied | T-14-10   | tenant_a never sees tenant_b's project   |
|                                           |           | AND run rows (the headline seam-table    |
|                                           |           | isolation assertion).                    |
| test_seam_no_tenant_context_denied        | T-14-10   | an unset app.tenant_id returns zero rows |
|                                           |           | OR raises the GUC/uuid-cast error (never |
|                                           |           | leaks) -- mirrors                        |
|                                           |           | test_no_tenant_context_returns_empty.    |

RLS FAITHFULNESS (why this test guards on a NON-superuser role):
FORCE ROW LEVEL SECURITY binds table OWNERS, but a Postgres SUPERUSER bypasses RLS
UNCONDITIONALLY. The phase-critical CI subset (``tribunal/cloudbuild.test-critical.yaml``)
connects as the ``postgres`` superuser and therefore EXCLUDES ``test_rls_isolation.py`` for
exactly this reason. To stay faithful, this suite SKIPS CLEANLY when the connected role is a
superuser (``SELECT current_setting('is_superuser')``), so it only asserts anything under a
NON-superuser DSN. That makes it meaningful under the full-suite run
(``tribunal/cloudbuild.test.yaml``, testcontainers ``postgres:15`` where the test connects as
a non-superuser app role) -- NOT under the superuser critical subset. Recorded in
14-03-SUMMARY.

Required env: DATABASE_URL (postgresql+asyncpg://<non-superuser>:<pw>@host:port/db). Skips
cleanly (never errors) when unset, so the suite still exits 0 on a dev box with no live DB.
"""

from __future__ import annotations

import os
import uuid

import pytest


pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Live-Postgres fixtures (skip cleanly when DATABASE_URL is unset) -- mirrors
# the shape of test_rls_isolation.py so both files read identically.
# ---------------------------------------------------------------------------


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set -- run under tribunal/cloudbuild.test.yaml "
            "(full-suite testcontainers, non-superuser) or set manually after "
            "starting the Cloud SQL Auth Proxy"
        )
    return url


@pytest.fixture
async def live_engine():
    """Async engine bound to the live Postgres (via Auth Proxy / testcontainer)."""
    url = _require_database_url()
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")
    engine = sa.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def require_non_superuser(live_engine):
    """Skip CLEANLY unless the connected role is a NON-superuser.

    RLS is bypassed unconditionally by a Postgres superuser, so an isolation
    assertion run as a superuser proves NOTHING (it would pass even with a broken
    policy). The phase-critical subset connects as the superuser and excludes the
    RLS suites for this reason; this guard makes the new suite self-excluding on a
    superuser DSN (skip, never a false green) and meaningful only under the
    non-superuser full-suite DSN.
    """
    from sqlalchemy import text

    async with live_engine.connect() as conn:
        is_super = (
            await conn.execute(text("SELECT current_setting('is_superuser')"))
        ).scalar_one()
    if str(is_super).lower() in ("on", "true", "yes", "1"):
        pytest.skip(
            "connected as a Postgres SUPERUSER -- RLS is bypassed, so this "
            "cross-tenant denial test would be a false green. Runs faithfully "
            "only under a non-superuser DSN (tribunal/cloudbuild.test.yaml)."
        )


@pytest.fixture
async def isolated_two_tenants(live_engine):
    """
    Create two ephemeral orgs (tenant_a, tenant_b) directly (org is NOT itself
    RLS-scoped because org IS the tenant -- identity mapping, org.id == space_id).
    CASCADE-deleted at teardown so the suite is rerunnable. Mirrors the
    ``isolated_two_tenants`` fixture in ``test_rls_isolation.py`` verbatim in shape.
    """
    from sqlalchemy import text

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Unique-per-run slugs so concurrent CI sessions don't collide on the UNIQUE column.
    slug_a = f"seam-a-{tenant_a.hex[:8]}"
    slug_b = f"seam-b-{tenant_b.hex[:8]}"

    async with live_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            [
                {"id": tenant_a, "name": "Seam Tenant A (RLS test)", "slug": slug_a},
                {"id": tenant_b, "name": "Seam Tenant B (RLS test)", "slug": slug_b},
            ],
        )

    yield tenant_a, tenant_b

    async with live_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM org WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )


# ---------------------------------------------------------------------------
# Seed helper -- one project + one run per tenant, each under its OWN tenant
# context so the RLS WITH CHECK admits the insert (the seam's write path).
# ---------------------------------------------------------------------------


async def _seed_project_and_run(Session, tenant_id):
    """Insert one Project + one Run for ``tenant_id`` under its own tenant context.

    Mirrors the seam's provisioning: ensure_project creates exactly one project per space
    under the set tenant context; a run is added to exercise a second RLS-FORCED child table.
    Returns ``(project_name, run_brief)`` for the isolation assertions.
    """
    from nestor_pulse_sdk.db.models import Project, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context

    project_name = f"{tenant_id} secret project"
    run_brief = f"{tenant_id} secret brief"

    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            project = Project(tenant_id=tenant_id, name=project_name, status="active")
            session.add(project)
            await session.flush()  # populate project.id for the run FK
            session.add(
                Run(
                    tenant_id=tenant_id,
                    project_id=project.id,
                    engine="sdk",  # D-02 CHECK: one of adk/sdk/tribunal
                    brief=run_brief,
                    status="queued",
                    idempotency_key=uuid.uuid4(),
                )
            )
    return project_name, run_brief


# ===========================================================================
# Test 1: cross-tenant SELECT on project + run returns zero foreign rows
# ===========================================================================


async def test_seam_project_run_cross_tenant_denied(
    live_engine, require_non_superuser, isolated_two_tenants
):
    """T-14-10 -- a session set to tenant_a MUST NOT see tenant_b's project OR run rows.

    The headline seam-table isolation assertion, applied to the two RLS-FORCED tables the
    internal seam provisions (org.id == space_id, so ensure_org/ensure_project land rows
    here). Proves the DB-layer half of the GUC-name-mismatch firewall: a space-A tenant
    context can only ever read space-A's project/run, never space-B's.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import Project, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_a, tenant_b = isolated_two_tenants
    Session = async_sessionmaker(
        live_engine, class_=AsyncSession, expire_on_commit=False
    )

    project_a, brief_a = await _seed_project_and_run(Session, tenant_a)
    project_b, brief_b = await _seed_project_and_run(Session, tenant_b)

    # Read as tenant_a -- MUST see only A's project + run, never B's.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            projects_a = sorted(
                r[0] for r in (await session.execute(select(Project.name)))
            )
            briefs_a = sorted(
                r[0] for r in (await session.execute(select(Run.brief)))
            )
            assert project_a in projects_a, (
                f"tenant_a should see its own seam project; got: {projects_a}"
            )
            assert project_b not in projects_a, (
                f"RLS LEAK: tenant_a saw tenant_b's seam project: {projects_a}"
            )
            assert brief_a in briefs_a, (
                f"tenant_a should see its own seam run; got: {briefs_a}"
            )
            assert brief_b not in briefs_a, (
                f"RLS LEAK: tenant_a saw tenant_b's seam run: {briefs_a}"
            )

    # Read as tenant_b -- MUST see only B's rows, never A's (the reverse direction).
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            projects_b = sorted(
                r[0] for r in (await session.execute(select(Project.name)))
            )
            briefs_b = sorted(
                r[0] for r in (await session.execute(select(Run.brief)))
            )
            assert project_b in projects_b
            assert project_a not in projects_b, (
                f"RLS LEAK: tenant_b saw tenant_a's seam project: {projects_b}"
            )
            assert brief_b in briefs_b
            assert brief_a not in briefs_b, (
                f"RLS LEAK: tenant_b saw tenant_a's seam run: {briefs_b}"
            )


# ===========================================================================
# Test 2: no tenant context -> zero rows OR GUC/uuid-cast error (never a leak)
# ===========================================================================


async def test_seam_no_tenant_context_denied(
    live_engine, require_non_superuser, isolated_two_tenants
):
    """T-14-10 -- a session that NEVER sets the tenant context is denied.

    Mirrors ``test_no_tenant_context_returns_empty``: with ``app.tenant_id`` unset the
    RLS policy either returns zero rows or raises on ``current_setting('app.tenant_id')::uuid``
    -- what is NOT acceptable is a seam project row leaking back. Proves that an ensure_*
    provisioning path that somehow reached the DB WITHOUT a tenant context (a bug) cannot read
    across tenants: the DB denies by default.
    """
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import Project

    tenant_a, _ = isolated_two_tenants
    Session = async_sessionmaker(
        live_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Plant a row so there IS something that could leak.
    await _seed_project_and_run(Session, tenant_a)

    leak_count = None
    error_seen = None
    async with Session() as session:
        try:
            async with session.begin():
                # Intentionally DO NOT call set_tenant_context; explicitly clear any
                # inherited GUC to be certain the context is unset.
                await session.execute(
                    text("SELECT set_config('app.tenant_id', '', true)")
                )
                result = await session.execute(select(Project))
                leak_count = len(result.all())
        except Exception as exc:  # noqa: BLE001 -- a Postgres GUC/uuid-cast error is fine
            error_seen = str(exc)

    if leak_count is not None:
        assert leak_count == 0, (
            f"RLS BYPASS: seam-table query without tenant context returned "
            f"{leak_count} rows (must be 0)."
        )
    else:
        assert (
            "app.tenant_id" in (error_seen or "")
            or "invalid input syntax" in (error_seen or "").lower()
            or "uuid" in (error_seen or "").lower()
        ), f"Unexpected error shape: {error_seen!r}"
