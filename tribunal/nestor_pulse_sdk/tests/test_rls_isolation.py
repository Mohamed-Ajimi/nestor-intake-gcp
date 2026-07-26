"""
PHASE1-02 -- RLS cross-tenant isolation (owning plan: 05 [BLOCKING])

Per 01-VALIDATION.md row:
  "Wrong-tenant request returns 0 rows from RLS-protected tables"
  Test type: integration (against live Cloud SQL via Cloud SQL Auth Proxy)
  Command: DATABASE_URL=... pytest nestor_pulse_sdk/tests/test_rls_isolation.py -x

This is the Wave 2 gate suite. After Plan 05 pushes 0001-0003 migrations
to the live Cloud SQL via `infrastructure/gcloud/alembic-push.sh`, these
tests run against the same DATABASE_URL to prove cross-tenant isolation
is enforced by Postgres RLS policies, not by application WHERE clauses.

Required env: DATABASE_URL (postgresql+asyncpg://app_user:<pw>@127.0.0.1:5433/nestor_db)
              with the Cloud SQL Auth Proxy already running.
              See infrastructure/gcloud/alembic-push.sh for the proxy
              startup pattern.

Tests skip cleanly (rather than error) if DATABASE_URL is unset, so the
suite still exits 0 on a dev box that has not yet performed the schema
push. The orchestrator-specified <success_criteria> is that this suite
exits 0 against live Cloud SQL post-push.

What each test proves:

| Test | Threat | Reference |
|------|--------|-----------|
| test_wrong_tenant_returns_zero_rows | T-05-01 information disclosure | RESEARCH § Pattern 1 |
| test_force_row_level_security_applies_to_owner | T-05-04 elevation | RESEARCH line 378 |
| test_no_tenant_context_returns_empty | T-05-02 RLS bypass | RESEARCH Pitfall 1 |
| test_concurrent_different_tenants_stay_isolated | T-05-02 SET-LOCAL regression | RESEARCH Pitfall 1 |
| test_research_gap_cross_tenant_denied | T-15.2-01 information disclosure | 15.2-01 / D-13 |
| test_research_gap_write_without_tenant_context_rejected | T-15.2-03 WITH CHECK + T-15.2-04 uuid-cast crash-loop | 15.2-01 / migrations 0009+0010 |

Phase 15.2 (plan 15.2-01) added the last two rows for the `research_gap` table
created by migration 0013, plus a `require_non_superuser` guard so this file can
never pass VACUOUSLY on a superuser DSN again. The harness that runs it
faithfully -- and that treats a skip as a build failure -- is
`tribunal/cloudbuild.test-rls.yaml`.

The Pitfall 1 regression test forces pool reuse (size=1, max_overflow=0)
so two sequential transactions land on the SAME physical connection.
If `set_tenant_context` used SET (session-scoped) instead of
SET LOCAL / set_config(..., true), the second tenant would inherit the
first tenant's context. With the canonical pattern, COMMIT discards the
GUC and the second transaction starts clean.
"""

from __future__ import annotations

import os
import uuid

import pytest


# ---------------------------------------------------------------------------
# Live-Postgres fixtures (skip cleanly when DATABASE_URL is unset)
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set -- run via "
            "`infrastructure/gcloud/alembic-push.sh` env or set manually "
            "after starting the Cloud SQL Auth Proxy"
        )
    return url


@pytest.fixture
async def live_engine():
    """Async engine bound to the live Cloud SQL (via Auth Proxy)."""
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
    assertion run as a superuser proves NOTHING (it would pass even with a
    completely broken policy). `tribunal/cloudbuild.test-critical.yaml` connects
    as the `postgres` superuser and excludes this file for exactly that reason.
    This guard makes the file self-excluding on a superuser DSN -- a loud skip,
    never a false green -- and meaningful only under the non-superuser app_user
    DSN of `tribunal/cloudbuild.test-rls.yaml`, which is the harness that runs it
    faithfully (and which treats a skip as a build failure). Threat T-15.2-07.

    Mirrors `test_seam_rls_denial.py::require_non_superuser` in shape and register.
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
            "only under a non-superuser DSN (tribunal/cloudbuild.test-rls.yaml)."
        )


@pytest.fixture
async def isolated_two_tenants(live_engine):
    """
    Create two ephemeral orgs (tenant_a, tenant_b) directly via the
    superuser-equivalent role (RLS-bypassing INSERT into `org`, which is
    NOT itself RLS-scoped because org IS the tenant). The orgs are
    cleaned up at fixture teardown so the suite is rerunnable.
    """
    from sqlalchemy import text

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Make slugs unique-per-run so concurrent CI sessions don't collide.
    slug_a = f"tenant-a-{tenant_a.hex[:8]}"
    slug_b = f"tenant-b-{tenant_b.hex[:8]}"

    async with live_engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            [
                {"id": tenant_a, "name": "Tenant A (RLS test)", "slug": slug_a},
                {"id": tenant_b, "name": "Tenant B (RLS test)", "slug": slug_b},
            ],
        )

    yield tenant_a, tenant_b

    # Teardown: CASCADE deletes everything created during the test.
    async with live_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM org WHERE id IN (:a, :b)"),
            {"a": tenant_a, "b": tenant_b},
        )


# ---------------------------------------------------------------------------
# Test 1: cross-tenant SELECT returns zero rows (the headline assertion)
# ---------------------------------------------------------------------------

async def test_wrong_tenant_returns_zero_rows(live_engine, isolated_two_tenants):
    """
    PHASE1-02 -- a session set to tenant_a MUST NOT see rows owned by
    tenant_b. The headline RLS assertion.
    """
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import Project
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_a, tenant_b = isolated_two_tenants
    Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)

    # Insert project as tenant_a.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            session.add(
                Project(
                    tenant_id=tenant_a,
                    name="A's secret project",
                )
            )

    # Insert project as tenant_b.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            session.add(
                Project(
                    tenant_id=tenant_b,
                    name="B's secret project",
                )
            )

    # Read as tenant_a -- MUST see only A's project, not B's.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            result = await session.execute(select(Project.name))
            names_a = sorted(r[0] for r in result)
            assert "A's secret project" in names_a, (
                f"tenant_a should see its own project; got: {names_a}"
            )
            assert "B's secret project" not in names_a, (
                f"RLS LEAK: tenant_a saw tenant_b's project: {names_a}"
            )

    # Read as tenant_b -- MUST see only B's project, not A's.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            result = await session.execute(select(Project.name))
            names_b = sorted(r[0] for r in result)
            assert "B's secret project" in names_b
            assert "A's secret project" not in names_b, (
                f"RLS LEAK: tenant_b saw tenant_a's project: {names_b}"
            )


# ---------------------------------------------------------------------------
# Test 2: FORCE ROW LEVEL SECURITY applies even to the table owner
# ---------------------------------------------------------------------------

async def test_force_row_level_security_applies_to_owner(live_engine):
    """
    RESEARCH line 378 -- FORCE RLS DDL means even the table owner cannot
    bypass the policy. Without FORCE, the owner reads as if RLS were off.
    Per Plan 03's 0002 migration, every tenant-scoped table carries both
    ENABLE and FORCE.
    """
    from sqlalchemy import text

    tenant_scoped = (
        "app_user",
        "project",
        "run",
        "output",
        "audit_log",
        "source",
        "claim",
        "claim_source",
        # Added by migration 0013 (Phase 15.2 D-13). FORCE is what binds the
        # policy on app_user, the table OWNER -- without it the API role would
        # read every tenant's gap rows (threat T-15.2-02).
        "research_gap",
    )

    async with live_engine.connect() as conn:
        for tbl in tenant_scoped:
            row = (
                await conn.execute(
                    text(
                        "SELECT relrowsecurity, relforcerowsecurity "
                        "FROM pg_class WHERE relname = :t"
                    ),
                    {"t": tbl},
                )
            ).one()
            assert row.relrowsecurity is True, (
                f"{tbl}: RLS is NOT enabled (Plan 03 0002 migration missing?)"
            )
            assert row.relforcerowsecurity is True, (
                f"{tbl}: FORCE RLS is NOT set -- table owner could bypass!"
            )


# ---------------------------------------------------------------------------
# Test 3: Pitfall 1 — session without tenant context returns zero rows
# ---------------------------------------------------------------------------

async def test_no_tenant_context_returns_empty(live_engine, isolated_two_tenants):
    """
    RESEARCH Pitfall 1 -- a session that does NOT call set_tenant_context
    returns zero rows from tenant-scoped tables. RLS denies when the GUC
    is unset because `current_setting('app.tenant_id')::uuid` raises.

    Either zero-rows OR a thrown exception about app.tenant_id is acceptable
    here; what is NOT acceptable is rows leaking back.
    """
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import Project
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_a, _ = isolated_two_tenants
    Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)

    # First, plant a row so there IS something to leak.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            session.add(Project(tenant_id=tenant_a, name="A's no-context row"))

    # Now query WITHOUT calling set_tenant_context. RLS must deny.
    leak_count = None
    error_seen = None
    async with Session() as session:
        try:
            async with session.begin():
                # Intentionally DO NOT call set_tenant_context.
                # Explicit reset of any inherited GUC just to be sure.
                await session.execute(
                    text("SELECT set_config('app.tenant_id', '', true)")
                )
                result = await session.execute(select(Project))
                leak_count = len(result.all())
        except Exception as exc:  # noqa: BLE001 -- Postgres GUC-cast error is fine
            error_seen = str(exc)

    if leak_count is not None:
        assert leak_count == 0, (
            f"RLS BYPASS: query without tenant context returned {leak_count} "
            f"rows (must be 0). Pitfall 1 mitigation failed."
        )
    else:
        # Exception path -- as long as it's a GUC/uuid-cast error.
        assert (
            "app.tenant_id" in (error_seen or "")
            or "invalid input syntax" in (error_seen or "").lower()
            or "uuid" in (error_seen or "").lower()
        ), f"Unexpected error shape: {error_seen!r}"


# ---------------------------------------------------------------------------
# Test 4: Pitfall 1 regression — concurrent tenants on SAME pooled connection
# ---------------------------------------------------------------------------

async def test_concurrent_different_tenants_stay_isolated():
    """
    Pitfall 1 at the integration level: two sequential transactions on
    the SAME pooled connection (pool_size=1, max_overflow=0) with DIFFERENT
    tenants must NOT cross-contaminate. This is the canonical PgBouncer
    transaction-pooling regression.

    If `set_tenant_context` accidentally used SET (session-scoped) instead
    of SET LOCAL / set_config(..., true), this test would fail: the second
    transaction would inherit tenant_a's context and see tenant_a's rows
    when querying as tenant_b.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    from nestor_pulse_sdk.db.models import Project
    from nestor_pulse_sdk.db.rls import set_tenant_context

    url = _require_database_url()

    # Force a single shared connection.
    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )
    try:
        Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Set up two tenants with one project each (via a non-pooled path
        # so the proper pool is reserved for the regression check).
        from sqlalchemy import text

        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        slug_a = f"rls-pool-a-{tenant_a.hex[:8]}"
        slug_b = f"rls-pool-b-{tenant_b.hex[:8]}"

        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO org (id, name, slug, retention_days) "
                    "VALUES (:id, :name, :slug, 180)"
                ),
                [
                    {"id": tenant_a, "name": "Tenant A (pool reuse)", "slug": slug_a},
                    {"id": tenant_b, "name": "Tenant B (pool reuse)", "slug": slug_b},
                ],
            )

        try:
            async with Session() as session:
                async with session.begin():
                    await set_tenant_context(session, tenant_a)
                    session.add(
                        Project(tenant_id=tenant_a, name="A pool-reuse project")
                    )

            async with Session() as session:
                async with session.begin():
                    await set_tenant_context(session, tenant_b)
                    session.add(
                        Project(tenant_id=tenant_b, name="B pool-reuse project")
                    )

            # Now exercise the regression: read as tenant_b on the SAME
            # pool. If SET LOCAL leaked, this would see A's row.
            async with Session() as session:
                async with session.begin():
                    await set_tenant_context(session, tenant_b)
                    result = await session.execute(select(Project.name))
                    names_b = sorted(r[0] for r in result)
                    assert "B pool-reuse project" in names_b
                    assert "A pool-reuse project" not in names_b, (
                        "Pitfall 1 REGRESSION: tenant_b saw tenant_a's row "
                        "on a reused pooled connection. SET LOCAL leak."
                    )

            # And the reverse direction.
            async with Session() as session:
                async with session.begin():
                    await set_tenant_context(session, tenant_a)
                    result = await session.execute(select(Project.name))
                    names_a = sorted(r[0] for r in result)
                    assert "A pool-reuse project" in names_a
                    assert "B pool-reuse project" not in names_a
        finally:
            # Clean up the two ephemeral orgs (CASCADE removes projects).
            async with engine.begin() as conn:
                await conn.execute(
                    text("DELETE FROM org WHERE id IN (:a, :b)"),
                    {"a": tenant_a, "b": tenant_b},
                )
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Seed helper -- one project + one run + one research_gap per tenant, all
# inserted under that tenant's OWN context so the RLS WITH CHECK admits them
# (this is exactly the `persist_tribunal_claims` write path of plan 15.2-15).
# ---------------------------------------------------------------------------


async def _seed_gap(Session, tenant_id, provider, gap_text):
    """Insert the FK chain a `research_gap` row needs, for ``tenant_id``.

    Creates one Project, one Run (engine='tribunal' to satisfy ck_run_engine) and
    one ResearchGap, all through the ORM models -- which additionally proves the
    ORM declarations of migration 0013 match the shipped DDL.

    Returns the ``run_id``, so a caller can attempt a no-context INSERT against a
    run that genuinely exists.
    """
    from nestor_pulse_sdk.db.models import Project, ResearchGap, Run
    from nestor_pulse_sdk.db.rls import set_tenant_context

    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            project = Project(
                tenant_id=tenant_id, name=f"{tenant_id} gap project", status="active"
            )
            session.add(project)
            await session.flush()  # populate project.id for the run FK
            run = Run(
                tenant_id=tenant_id,
                project_id=project.id,
                engine="tribunal",  # D-02 CHECK: one of adk/sdk/tribunal
                brief="rls seed",
                status="queued",
                idempotency_key=uuid.uuid4(),
            )
            session.add(run)
            await session.flush()  # populate run.id for the gap FK
            session.add(
                ResearchGap(
                    tenant_id=tenant_id,
                    run_id=run.id,
                    provider=provider,
                    text=gap_text,
                )
            )
            run_id = run.id
    return run_id


# ---------------------------------------------------------------------------
# Test 5: research_gap cross-tenant SELECT returns zero foreign rows (D-13)
# ---------------------------------------------------------------------------


async def test_research_gap_cross_tenant_denied(
    live_engine, require_non_superuser, isolated_two_tenants
):
    """T-15.2-01 -- a session set to tenant_a MUST NOT see tenant_b's research_gap rows.

    The headline D-13 denial assertion, and D-13's "cross-tenant denial test on
    day one" requirement for the table created by migration 0013: every new
    tenant-scoped table gets FORCE RLS plus this test IN THE PLAN THAT CREATES IT.
    `research_gap` carries the per-provider "couldn't find" list, i.e. a statement
    about what a client's research did NOT establish -- leaking it across tenants
    would disclose one client's research shape to another.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import ResearchGap
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_a, tenant_b = isolated_two_tenants
    Session = async_sessionmaker(
        live_engine, class_=AsyncSession, expire_on_commit=False
    )

    await _seed_gap(Session, tenant_a, "gemini", "A's unfound fact")
    await _seed_gap(Session, tenant_b, "openai", "B's unfound fact")

    # Read as tenant_a -- MUST see only A's gap, never B's.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_a)
            texts = sorted(
                r[0] for r in (await session.execute(select(ResearchGap.text)))
            )
            assert "A's unfound fact" in texts, (
                f"tenant_a should see its own research_gap row; got: {texts}"
            )
            assert "B's unfound fact" not in texts, (
                f"RLS LEAK: tenant_a saw tenant_b's research_gap row: {texts}"
            )

    # And the reverse direction.
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_b)
            texts = sorted(
                r[0] for r in (await session.execute(select(ResearchGap.text)))
            )
            assert "B's unfound fact" in texts
            assert "A's unfound fact" not in texts, (
                f"RLS LEAK: tenant_b saw tenant_a's research_gap row: {texts}"
            )


# ---------------------------------------------------------------------------
# Test 6: research_gap with NO tenant context -- empty read, REJECTED write
# ---------------------------------------------------------------------------


async def test_research_gap_write_without_tenant_context_rejected(
    live_engine, require_non_superuser, isolated_two_tenants
):
    """T-15.2-03 (WITH CHECK) + T-15.2-04 (the 0009/0010 crash-loop guard), in one test.

    Reproduces the EMPTY-STRING GUC reversion documented in migration 0010: once
    any transaction on a pooled connection has SET the custom `app.tenant_id` GUC,
    it reverts to '' -- NOT to unset -- when that transaction ends. Then asserts
    BOTH halves of the policy:

    (a) the SELECT returns zero rows and RAISES NOTHING. This is what the
        `NULLIF(current_setting('app.tenant_id', true), '')::uuid` form buys. The
        bare `current_setting('app.tenant_id')::uuid` form that RESEARCH.md
        drafted would raise `invalid input syntax for type uuid: ""` right here --
        the exact worker crash-loop that migrations 0009 and 0010 exist to fix.
    (b) the INSERT is REJECTED by the policy's WITH CHECK, because NULL is not a
        match. A silent success here would be a cross-tenant write hole.
    """
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.models import ResearchGap

    tenant_a, _ = isolated_two_tenants
    Session = async_sessionmaker(
        live_engine, class_=AsyncSession, expire_on_commit=False
    )

    # Plant a row under a REAL tenant context, so there is something to leak and a
    # genuinely existing run_id to aim the rejected INSERT at.
    run_id_a = await _seed_gap(Session, tenant_a, "gemini", "A's no-context gap")

    # ---- (a) read with an EMPTY-STRING GUC: zero rows, and NO exception.
    async with Session() as session:
        async with session.begin():
            # Intentionally do NOT call set_tenant_context. Reproduce 0010's
            # empty-string reversion explicitly.
            await session.execute(
                text("SELECT set_config('app.tenant_id', '', true)")
            )
            try:
                rows = (await session.execute(select(ResearchGap))).all()
            except Exception as exc:  # noqa: BLE001
                pytest.fail(
                    "research_gap SELECT with an EMPTY app.tenant_id raised "
                    f"{type(exc).__name__}: {exc}. The policy must use the "
                    "NULLIF(current_setting('app.tenant_id', true), '')::uuid "
                    "form -- the bare current_setting(...)::uuid form raises on "
                    "'' and crash-loops the worker (migrations 0009/0010)."
                )
            assert len(rows) == 0, (
                f"RLS BYPASS: research_gap read without tenant context returned "
                f"{len(rows)} rows (must be 0)."
            )

    # ---- (b) write with an EMPTY-STRING GUC: REJECTED by WITH CHECK.
    write_error = None
    async with Session() as session:
        try:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', '', true)")
                )
                session.add(
                    ResearchGap(
                        tenant_id=tenant_a,
                        run_id=run_id_a,
                        provider="gemini",
                        text="smuggled with no tenant context",
                    )
                )
                await session.flush()
        except Exception as exc:  # noqa: BLE001 -- the RLS policy violation we want
            write_error = str(exc)

    assert write_error is not None, (
        "CROSS-TENANT WRITE HOLE: inserting a research_gap row with no tenant "
        "context SUCCEEDED. The policy's WITH CHECK must reject it (NULL is not "
        "a match)."
    )
    assert (
        "row-level security" in write_error.lower()
        or "violates" in write_error.lower()
        or "policy" in write_error.lower()
    ), f"Unexpected error shape for the rejected write: {write_error!r}"
