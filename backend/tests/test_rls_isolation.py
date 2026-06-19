"""
RLS cross-tenant isolation suite — covers TENANT-05.

Ported near-verbatim from the sibling repo
``C:/Users/ajimimo/Desktop/MOELD/Nestor/nestor_pulse_sdk/tests/test_rls_isolation.py``
with the global rename applied (tenant -> space, app.tenant_id ->
app.current_space_id, org -> organizations, project -> intakes) and the engine
switched from async asyncpg to **sync pg8000** per Q1 RESOLVED.

These tests are RED-by-design in Wave 0: the schema (plan 01-02) and the RLS
policies (plan 01-03) do not exist yet. They turn GREEN once 0001 (schema),
0002 (ENABLE+FORCE+isolation policy) and 0003 (superadmin bypass) land.

What each test proves (01-RESEARCH.md § Security Domain / threat register):

| Test                                          | Threat ID | What it proves                                  |
|-----------------------------------------------|-----------|-------------------------------------------------|
| test_wrong_space_returns_zero_rows            | T-01-01   | space_b's rows invisible to a space_a session   |
| test_force_rls_applies_to_owner               | T-01-02   | relrowsecurity AND relforcerowsecurity on all 12|
| test_no_space_context_returns_empty           | T-01-04   | no-context query fails safe (0 rows / GUC error)|
| test_concurrent_different_spaces_stay_isolated| T-01-03   | pooled-connection reuse does NOT leak context   |

The Pitfall 1 regression test forces pool reuse (pool_size=1, max_overflow=0)
so two sequential transactions land on the SAME physical connection. If the
GUC were set session-scoped (`set_config(..., false)` / bare SET) instead of
transaction-local (`..., true`), the second space would inherit the first
space's context. With the canonical pattern COMMIT discards the GUC and the
second transaction starts clean.
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import _sync_pg8000_url

pytestmark = pytest.mark.integration

SCHEMA = "nestor"

# The 12 tenant-owned tables — single source for the iterating FORCE-RLS test.
# Mirrors test_schema_shape.TENANT_TABLES (kept local so this file is
# self-describing for the FORCE check). D-03.
TENANT_TABLES = (
    "products",
    "intakes",
    "intake_answers",
    "intake_templates",
    "skill_runs",
    "decompositions",
    "research_questions",
    "research_artifacts",
    "findings",
    "deliverables",
    "artifact_embeddings",
    "search_index",
)


# ---------------------------------------------------------------------------
# Helpers: minimal space + intake seeding via raw SQL (connect as owner)
# ---------------------------------------------------------------------------

def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    """Insert an organization (a space). `organizations` is the tenant root and
    is NOT RLS-scoped, so no space context is needed to insert it."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organizations (id, name) "
            "VALUES (:id, :name)"
        ),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID) -> None:
    """Insert one intake into a space, with the GUC set so WITH CHECK passes."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
            "VALUES (:id, :space_id, 'draft')"
        ),
        {"id": intake_id, "space_id": space_id},
    )


def _count_visible_intakes(conn, set_space, space_id: uuid.UUID) -> int:
    from sqlalchemy import text

    set_space(conn, space_id)
    return conn.execute(text(f"SELECT count(*) FROM {SCHEMA}.intakes")).scalar_one()


# ---------------------------------------------------------------------------
# Test 1: cross-space SELECT returns zero rows (the headline assertion)
# ---------------------------------------------------------------------------

def test_wrong_space_returns_zero_rows(engine, set_space, two_spaces):
    """A session scoped to space_a MUST NOT see rows owned by space_b.

    The headline RLS assertion (T-01-01, information disclosure).
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        # Seed: one intake per space (each transaction sets its own context).
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (RLS test)")
            _create_space(conn, space_b, "Space B (RLS test)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # Read as space_a -> sees only A's intake.
        with engine.begin() as conn:
            set_space(conn, space_a)
            ids_a = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_a in ids_a, "space_a should see its own intake"
            assert intake_b not in ids_a, "RLS LEAK: space_a saw space_b's intake"

        # Read as space_b -> sees only B's intake.
        with engine.begin() as conn:
            set_space(conn, space_b)
            ids_b = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_b in ids_b, "space_b should see its own intake"
            assert intake_a not in ids_b, "RLS LEAK: space_b saw space_a's intake"
    finally:
        # Cleanup as the owner; CASCADE removes the intakes.
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


# ---------------------------------------------------------------------------
# Test 2: FORCE ROW LEVEL SECURITY applies even to the table owner
# ---------------------------------------------------------------------------

def test_force_rls_applies_to_owner(engine):
    """Every tenant table has both `relrowsecurity` AND `relforcerowsecurity`.

    Without FORCE, the table owner (the migration/app role that owns the
    tables) bypasses RLS entirely (T-01-02, elevation of privilege). Plan
    01-03's 0002 migration must ENABLE *and* FORCE on all 12 tenant tables.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        for tbl in TENANT_TABLES:
            row = conn.execute(
                text(
                    "SELECT c.relrowsecurity, c.relforcerowsecurity "
                    "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = :schema AND c.relname = :tbl"
                ),
                {"schema": SCHEMA, "tbl": tbl},
            ).one()
            assert row[0] is True, (
                f"{SCHEMA}.{tbl}: RLS is NOT enabled (0002 migration missing?)"
            )
            assert row[1] is True, (
                f"{SCHEMA}.{tbl}: FORCE RLS is NOT set — the table owner could bypass!"
            )


# ---------------------------------------------------------------------------
# Test 3: no space context -> zero rows / fails safe (never a leak)
# ---------------------------------------------------------------------------

def test_no_space_context_returns_empty(engine, set_space, two_spaces):
    """A session that never sets `app.current_space_id` returns 0 rows.

    With NULL context the isolation policy matches nothing (USING returns no
    rows). Either zero-rows OR a thrown GUC/uuid-cast error is acceptable; what
    is NOT acceptable is rows leaking back (T-01-04, tampering / fail-safe).
    """
    from sqlalchemy import text

    space_a, _ = two_spaces
    intake_a = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (no-context test)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)

        leak_count = None
        error_seen = None
        try:
            with engine.begin() as conn:
                # Intentionally DO NOT set a real space context. Explicitly clear
                # any inherited GUC to the empty string to exercise the NULLIF path.
                conn.execute(
                    text("SELECT set_config('app.current_space_id', '', true)")
                )
                leak_count = conn.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.intakes")
                ).scalar_one()
        except Exception as exc:  # noqa: BLE001 -- a GUC/uuid-cast error is acceptable
            error_seen = str(exc)

        if leak_count is not None:
            assert leak_count == 0, (
                f"RLS BYPASS: query with empty space context returned {leak_count} "
                "rows (must be 0). NULLIF/Pitfall-1 mitigation failed."
            )
        else:
            low = (error_seen or "").lower()
            assert (
                "app.current_space_id" in (error_seen or "")
                or "invalid input syntax" in low
                or "uuid" in low
            ), f"Unexpected error shape: {error_seen!r}"
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :a"),
                {"a": space_a},
            )


# ---------------------------------------------------------------------------
# Test 4: Pitfall 1 regression — concurrent spaces on the SAME pooled connection
# ---------------------------------------------------------------------------

def test_concurrent_different_spaces_stay_isolated(engine, pg_container):
    """Two sequential transactions on the SAME pooled connection (pool_size=1,
    max_overflow=0) with DIFFERENT spaces must NOT cross-contaminate.

    This is the canonical transaction-pooling (PgBouncer) regression
    (T-01-03). If the GUC were set session-scoped instead of transaction-local
    (`set_config(..., true)`), the second transaction would inherit the first
    space's context and see its rows. With the canonical pattern, COMMIT
    discards the GUC and the second transaction starts clean.
    """
    from sqlalchemy import create_engine, text

    url = _sync_pg8000_url(pg_container)

    # Force a single shared physical connection.
    pooled = create_engine(
        url,
        echo=False,
        future=True,
        pool_size=1,
        max_overflow=0,
        pool_pre_ping=True,
    )

    space_a, space_b = uuid.uuid4(), uuid.uuid4()
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    def _set_space(conn, sid):
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(sid)},
        )

    try:
        with pooled.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
                [
                    {"id": space_a, "name": "Space A (pool reuse)"},
                    {"id": space_b, "name": "Space B (pool reuse)"},
                ],
            )

        with pooled.begin() as conn:
            _set_space(conn, space_a)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_a, "sid": space_a},
            )
        with pooled.begin() as conn:
            _set_space(conn, space_b)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_b, "sid": space_b},
            )

        # Read as space_b on the SAME pool — must NOT see space_a's row.
        with pooled.begin() as conn:
            _set_space(conn, space_b)
            ids_b = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_b in ids_b
            assert intake_a not in ids_b, (
                "Pitfall 1 REGRESSION: space_b saw space_a's row on a reused "
                "pooled connection. SET LOCAL leak."
            )

        # Reverse direction.
        with pooled.begin() as conn:
            _set_space(conn, space_a)
            ids_a = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_a in ids_a
            assert intake_b not in ids_a, (
                "Pitfall 1 REGRESSION: space_a saw space_b's row on a reused "
                "pooled connection. SET LOCAL leak."
            )
    finally:
        with pooled.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )
        pooled.dispose()
