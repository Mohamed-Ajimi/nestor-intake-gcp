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
| test_superadmin_bypass_reads_across_spaces    | WR-02 (a) | app_superadmin SELECT spans BOTH spaces (0003)  |
| test_superadmin_bypass_writes_across_spaces   | WR-02 (a) | app_superadmin INSERT into either space succeeds|
| test_app_role_select_scoped_to_its_space      | WR-02 (b) | non-owner app role sees ONLY its space's rows   |
| test_app_role_cross_space_write_rejected      | WR-02 (b) | non-owner app role's cross-space write rejected |
| test_app_role_no_context_returns_zero_rows    | WR-02 (b) | non-owner app role with NO GUC sees zero rows   |

WR-02 gap closure (01-REVIEW.md): the original four tests all connect as the
migration/owner role under FORCE RLS. They never exercise the two roles that
actually matter in production:
  (a) ``app_superadmin`` — the 0003 ``current_user = 'app_superadmin'`` BYPASS
      policy (``*_superadmin_all``), OR'd with 0002's isolation policy. A broken
      0003 would otherwise ship green.
  (b) a plain NON-owner, NON-superadmin application LOGIN role under the per-
      session GUC — the REAL production access path, where RLS (not table
      ownership) is what enforces isolation.
The tests below close that gap. They assert against the ACTUAL predicates:
  - 0003 bypass:    USING/WITH CHECK ``current_user = 'app_superadmin'``
  - 0002 isolation: USING/WITH CHECK
                    ``space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid``
Role names + predicates were cross-checked against
``0002_rls_policies.py`` and ``0003_superadmin_bypass.py``.

The Pitfall 1 regression test forces pool reuse (pool_size=1, max_overflow=0)
so two sequential transactions land on the SAME physical connection. If the
GUC were set session-scoped (`set_config(..., false)` / bare SET) instead of
transaction-local (`..., true`), the second space would inherit the first
space's context. With the canonical pattern COMMIT discards the GUC and the
second transaction starts clean.
"""

from __future__ import annotations

import contextlib
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


# ===========================================================================
# WR-02 gap closure — the two production roles the owner tests never exercise.
# ===========================================================================
#
# These tests reuse the existing conftest fixtures (engine, set_space,
# two_spaces) and the module-level `integration` marker, so they skip cleanly
# when no DB/Docker is present. They keep the canonical transaction-local GUC
# semantics (set_config(..., true) / SET LOCAL) throughout.


# The non-owner application LOGIN role. Mirrors conftest's
# `_ensure_app_superadmin` role-creation pattern, but this role is deliberately
# NON-superadmin and NON-owner: it must be isolated by RLS (0002), NOT by table
# ownership. This is the real production access path.
APP_ROLE = "app_user_rls_test"


@contextlib.contextmanager
def _as_role(engine, role: str):
    """Yield a connection in an open transaction with ``SET ROLE <role>`` applied,
    guaranteeing ``RESET ROLE`` runs before the connection returns to the pool.

    ``SET ROLE`` is SESSION-scoped (not transaction-local), so a leaked role on a
    pooled connection would corrupt later tests. This helper:
      - opens an explicit transaction and applies SET ROLE,
      - on clean exit: commits, then RESET ROLE on a fresh statement,
      - on exception (e.g. a row-security violation that aborts the tx): rolls
        back FIRST (clearing the aborted state) so the subsequent RESET ROLE
        succeeds and does NOT mask the original error, then re-raises.

    Using a manual begin()/commit() (rather than ``engine.begin()``) is what lets
    us run RESET ROLE on a non-aborted connection in both paths.
    """
    from sqlalchemy import text

    conn = engine.connect()
    trans = conn.begin()
    try:
        conn.execute(text(f"SET ROLE {role}"))
        yield conn
        trans.commit()
    except Exception:
        trans.rollback()  # clear any aborted-tx state before RESET ROLE
        raise
    finally:
        try:
            conn.execute(text("RESET ROLE"))
        except Exception:  # noqa: BLE001 -- best-effort; connection is disposed next
            pass
        conn.close()


def _ensure_app_role(conn) -> None:
    """Create the non-owner, non-superadmin app LOGIN role and GRANT it the
    privileges the production app role holds (schema usage + DML on the tenant
    tables + sequence usage). Idempotent — guards the duplicate-role error so a
    re-run does not blow up. Mirrors `_ensure_app_superadmin` in conftest.py.

    Note: this role is NOT GRANTed via 0003 (that GRANT targets app_superadmin),
    so the privileges are granted here. The role owns nothing, so under FORCE
    RLS the only thing standing between it and another space's rows is the
    0002 `*_space_isolation` policy — exactly what we want to prove.
    """
    from sqlalchemy import text

    conn.execute(
        text(
            "DO $$ BEGIN "
            f"  CREATE ROLE {APP_ROLE} LOGIN; "
            "EXCEPTION WHEN duplicate_object THEN NULL; "
            "END $$;"
        )
    )
    conn.execute(text(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {APP_ROLE}"))
    conn.execute(
        text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
            f"TO {APP_ROLE}"
        )
    )
    conn.execute(
        text(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {APP_ROLE}"
        )
    )


# ---------------------------------------------------------------------------
# WR-02 (a): app_superadmin BYPASS — proves the 0003 `*_superadmin_all` policy
# ---------------------------------------------------------------------------

def test_superadmin_bypass_reads_across_spaces(engine, set_space, two_spaces):
    """`app_superadmin` SELECT over a tenant table returns rows from BOTH spaces.

    Proves the 0003 bypass policy
    (``USING (current_user = 'app_superadmin')``) OR'd with 0002's isolation:
    once SET ROLE app_superadmin makes ``current_user = 'app_superadmin'``, the
    per-space boundary is crossed and every space's rows are visible — the
    cross-tenant operator path. A broken 0003 would make this test RED (the
    superadmin would see only its GUC's space, or zero rows).

    The `app_superadmin` role is created by conftest's `_ensure_app_superadmin`
    (run once in the `engine` fixture) and GRANTed by migration 0003.
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        # Seed one intake per space AS THE OWNER (each tx sets its own GUC so
        # the 0002 WITH CHECK passes for the owner under FORCE RLS).
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (superadmin read)")
            _create_space(conn, space_b, "Space B (superadmin read)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # Read AS app_superadmin with NO space GUC set: the *_superadmin_all
        # policy (current_user = 'app_superadmin') matches, so BOTH spaces are
        # visible. We deliberately do NOT call set_space here — the bypass must
        # not depend on the GUC.
        with _as_role(engine, "app_superadmin") as conn:
            ids = {
                r[0]
                for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))
            }
            assert intake_a in ids, (
                "0003 BYPASS BROKEN: app_superadmin could not see space_a's "
                "intake (superadmin must cross every space boundary)."
            )
            assert intake_b in ids, (
                "0003 BYPASS BROKEN: app_superadmin could not see space_b's "
                "intake (superadmin must cross every space boundary)."
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


def test_superadmin_bypass_writes_across_spaces(engine, set_space, two_spaces):
    """`app_superadmin` INSERT succeeds into EITHER space, with NO GUC set.

    The 0003 bypass policy's WITH CHECK is ``current_user = 'app_superadmin'``,
    so a superadmin write is admitted regardless of ``app.current_space_id``.
    This is the positive write side of the cross-tenant operator path; it would
    be RED if 0003 only added a USING (read) clause and forgot WITH CHECK.

    We then read the rows back as the OWNER (per space, with the GUC) to confirm
    the inserts actually landed in the intended spaces.
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (superadmin write)")
            _create_space(conn, space_b, "Space B (superadmin write)")

        # Insert into BOTH spaces as app_superadmin in a single tx, NO GUC set.
        with _as_role(engine, "app_superadmin") as conn:
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_a, "sid": space_a},
            )
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_b, "sid": space_b},
            )

        # Confirm each row landed in its intended space (read back as owner with
        # the matching GUC — the isolation policy scopes the owner per space).
        with engine.begin() as conn:
            set_space(conn, space_a)
            ids_a = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_a in ids_a, (
                "0003 BYPASS BROKEN: app_superadmin's INSERT into space_a was "
                "rejected or landed elsewhere (WITH CHECK current_user="
                "'app_superadmin' must admit the write)."
            )
            assert intake_b not in ids_a, (
                "space_a session saw space_b's superadmin-inserted row — "
                "isolation regression."
            )
        with engine.begin() as conn:
            set_space(conn, space_b)
            ids_b = {r[0] for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))}
            assert intake_b in ids_b, (
                "0003 BYPASS BROKEN: app_superadmin's INSERT into space_b was "
                "rejected or landed elsewhere."
            )
            assert intake_a not in ids_b, (
                "space_b session saw space_a's superadmin-inserted row — "
                "isolation regression."
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


# ---------------------------------------------------------------------------
# WR-02 (b): NON-owner app role is isolated by RLS (not by ownership)
# ---------------------------------------------------------------------------

def test_app_role_select_scoped_to_its_space(engine, set_space, two_spaces):
    """A plain NON-owner, NON-superadmin app role sees ONLY its space's rows.

    This is the REAL production access path: the app connects as a dedicated app
    role (not the table owner), so RLS — not table ownership — is what enforces
    isolation. Under `SET ROLE app_user_rls_test` with the GUC set to space_a:
      - a SELECT returns ONLY space_a's intake, NEVER space_b's.
    The role does NOT match 0003's `*_superadmin_all` (current_user is the app
    role, not 'app_superadmin'), so ONLY 0002's `*_space_isolation` governs it —
    closing the "only the owner is tested" gap.
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        # Owner-side setup: create the app role + GRANTs, then seed one intake
        # per space (each with its GUC so the owner's WITH CHECK passes).
        with engine.begin() as conn:
            _ensure_app_role(conn)
            _create_space(conn, space_a, "Space A (app-role read)")
            _create_space(conn, space_b, "Space B (app-role read)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # Read AS the non-owner app role, scoped to space_a. The GUC must be set
        # AFTER SET ROLE so it lives in the same transaction (SET LOCAL).
        with _as_role(engine, APP_ROLE) as conn:
            set_space(conn, space_a)
            ids = {
                r[0]
                for r in conn.execute(text(f"SELECT id FROM {SCHEMA}.intakes"))
            }
            assert intake_a in ids, (
                "app role scoped to space_a should see space_a's intake."
            )
            assert intake_b not in ids, (
                "RLS LEAK: non-owner app role scoped to space_a saw space_b's "
                "intake — 0002 isolation policy does not protect the app role."
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


def test_app_role_cross_space_write_rejected(engine, set_space, two_spaces):
    """A non-owner app role scoped to space_a CANNOT write into space_b.

    With the GUC set to space_a, both an INSERT and an UPDATE targeting space_b
    are rejected by the 0002 policy:
      - INSERT into space_b -> WITH CHECK
        (space_b = NULLIF(current_setting('app.current_space_id', true),'')::uuid
         where the GUC = space_a) -> false -> RowSecurity violation (fail-LOUD).
      - UPDATE of an existing space_b row -> USING does not see the row (the app
        role scoped to space_a cannot even select it), so 0 rows are affected
        and the foreign row is never mutated.
    Proves cross-tenant writes are denied for the real app role.
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()
    rogue_intake = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _ensure_app_role(conn)
            _create_space(conn, space_a, "Space A (app-role write deny)")
            _create_space(conn, space_b, "Space B (app-role write deny)")
        # Seed an existing intake in space_b (as owner) to attempt to UPDATE.
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # As the app role scoped to space_a, INSERT into space_b must be rejected.
        # `SET ROLE` is session-scoped, so we MUST reset it before the connection
        # returns to the pool (a leaked role would corrupt later tests). But on
        # the failure path the tx is aborted and `RESET ROLE` would itself error
        # and mask the row-security violation — so the reset is wrapped in
        # `_as_role(...)` which rolls back first when needed.
        insert_rejected = False
        try:
            with _as_role(engine, APP_ROLE) as conn:
                set_space(conn, space_a)
                conn.execute(
                    text(
                        f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                        "VALUES (:id, :sid, 'draft')"
                    ),
                    {"id": rogue_intake, "sid": space_b},
                )
        except Exception as exc:  # noqa: BLE001 -- a row-security violation is expected
            insert_rejected = True
            low = str(exc).lower()
            assert (
                "row-level security" in low
                or "row security" in low
                or "policy" in low
                or "violates" in low
            ), f"Unexpected error shape for cross-space INSERT denial: {exc!r}"

        assert insert_rejected, (
            "RLS BYPASS: non-owner app role scoped to space_a inserted a row into "
            "space_b — 0002 WITH CHECK failed to reject the cross-space write."
        )

        # As the app role scoped to space_a, UPDATE of space_b's row affects 0
        # rows (USING hides the foreign row); the row stays untouched.
        with _as_role(engine, APP_ROLE) as conn:
            set_space(conn, space_a)
            result = conn.execute(
                text(
                    f"UPDATE {SCHEMA}.intakes SET status = 'submitted' "
                    "WHERE id = :id"
                ),
                {"id": intake_b},
            )
            assert result.rowcount == 0, (
                "RLS LEAK: non-owner app role scoped to space_a updated "
                f"space_b's row ({result.rowcount} rows) — USING did not hide "
                "the foreign row."
            )

        # Confirm space_b's row was never mutated (read back as owner).
        with engine.begin() as conn:
            set_space(conn, space_b)
            status = conn.execute(
                text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_b},
            ).scalar_one()
            assert status == "draft", (
                f"space_b's intake status changed to {status!r} — a cross-space "
                "write leaked through despite rowcount==0."
            )
    finally:
        with engine.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


def test_app_role_no_context_returns_zero_rows(engine, set_space, two_spaces):
    """A non-owner app role with NO GUC set sees ZERO rows (fail-safe read).

    With no `app.current_space_id` (or an empty-string reversion on a pooled
    connection), 0002's
    ``NULLIF(current_setting('app.current_space_id', true), '')::uuid`` predicate
    yields NULL, so ``space_id = NULL`` is never true and the app role sees no
    rows. This is the app-role analogue of `test_no_space_context_returns_empty`
    (which only covered the owner), proving the real production role also fails
    safe with no context.
    """
    from sqlalchemy import text

    space_a, _ = two_spaces
    intake_a = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _ensure_app_role(conn)
            _create_space(conn, space_a, "Space A (app-role no-context)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)

        leak_count = None
        error_seen = None
        try:
            # `_as_role` guarantees RESET ROLE even when the count(*) raises a
            # uuid-cast error (it rolls back the aborted tx before resetting), so
            # the role never leaks and the acceptable cast error still surfaces.
            with _as_role(engine, APP_ROLE) as conn:
                # Explicitly clear the GUC to the empty string to exercise the
                # NULLIF path (the pooled-reuse reversion case).
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
                f"RLS BYPASS: non-owner app role with empty space context returned "
                f"{leak_count} rows (must be 0). NULLIF/fail-safe path failed."
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
