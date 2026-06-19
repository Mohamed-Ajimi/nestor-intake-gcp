"""
Pytest fixtures for the Nestor Intake (GCP re-platform) backend test suite.

This is the **Wave 0** harness: the schema (plan 01-02) and RLS policies
(plan 01-03) do NOT exist yet, so the schema-shape and RLS-isolation suites
that consume these fixtures are RED by design until those plans land. The
harness itself must collect cleanly and skip — never hard-error — when no
Postgres is reachable.

Authoritative references (this repo):
- .planning/phases/01-schema-migrations/01-RESEARCH.md
    § Environment Availability  -- pgvector/pgvector:pg16 image requirement;
                                   app_superadmin out-of-band role (fixture fallback)
    § Common Pitfalls / Pitfall 1 -- set_config(..., true) transaction-local GUC
    § Open Questions / Q1 RESOLVED -- sync pg8000 driver (NOT the sibling's async asyncpg)
- .planning/phases/01-schema-migrations/01-PATTERNS.md
    § tests/conftest.py assignment -- fixture list (pgvector container, async/sync
      engine, set_space helper, two_spaces, app_superadmin role creation)

Ported from the sibling repo
``C:/Users/ajimimo/Desktop/MOELD/Nestor/nestor_pulse_sdk/tests/conftest.py``
with the global rename applied:
    tenant_id          -> space_id
    app.tenant_id (GUC)-> app.current_space_id
    worker_user (role) -> app_superadmin
    two_tenants        -> two_spaces
    set_tenant         -> set_space
and the engine switched from async asyncpg to **sync pg8000** per Q1.

Design notes:
- The Postgres container is session-scoped and SKIPPED cleanly when Docker is
  not reachable (Docker availability is a known gap on the dev box per
  01-RESEARCH.md § Environment Availability). The suite must still exit 0 in
  that case (`pytest --collect-only` must succeed with no Docker).
- The engine fixture exposes a single ``alembic upgrade head`` call site
  (``_run_migrations``). It may fail RED until plan 01-02 lands the migrations;
  that is the intended Wave 0 state.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

# The literal Postgres image that ships the `vector` extension. Plain
# `postgres:16` would NOT have pgvector, so the schema's `vector(1536)` column
# and `CREATE EXTENSION vector` would fail. This MUST be pgvector/pgvector:pg16.
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"

# The transaction-local GUC key. MUST match the policy expression authored in
# plan 01-03's 0002 migration: NULLIF(current_setting('app.current_space_id', true), '')::uuid
SPACE_GUC_KEY = "app.current_space_id"


# ---------------------------------------------------------------------------
# Skip-clean guard: no Docker AND no DATABASE_URL -> skip, never error
# ---------------------------------------------------------------------------

def _database_url_from_env() -> str | None:
    """Return an explicit DATABASE_URL if one is set, else None.

    Mirrors the sibling `_require_database_url` pattern, but as a soft probe:
    when DATABASE_URL is provided (e.g. a Cloud SQL Auth Proxy DSN in CI) we
    use it directly and skip the container spin-up entirely.
    """
    return os.environ.get("DATABASE_URL") or None


# ---------------------------------------------------------------------------
# Session-scoped Postgres (pgvector) container fixture (testcontainers)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """Spin up an ephemeral `pgvector/pgvector:pg16` container.

    Skipped (NOT errored) when:
      - testcontainers is not installed yet (Wave 0 deps pending), OR
      - Docker is not reachable on this box.
    so the suite exits 0 on a dev machine with no live DB.

    When DATABASE_URL is set the container is bypassed (yields None) and the
    engine fixture binds to that DSN instead.
    """
    if _database_url_from_env():
        # An explicit DSN was provided; no container needed.
        yield None
        return

    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore
    except ImportError:
        pytest.skip("testcontainers not installed yet (Wave 0 dev deps pending)")
        return  # unreachable; pytest.skip raises

    try:
        container = PostgresContainer(PGVECTOR_IMAGE)
        container.start()
    except Exception as exc:  # noqa: BLE001 -- DockerException family + connection errors
        pytest.skip(f"Docker not available for testcontainers: {exc}")
        return  # unreachable; pytest.skip raises

    try:
        yield container
    finally:
        try:
            container.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Connection-URL resolution (sync pg8000 driver — Q1 RESOLVED)
# ---------------------------------------------------------------------------

def _sync_pg8000_url(pg_container: Any) -> str:
    """Resolve a `postgresql+pg8000://` DSN from the container or env.

    Q1 RESOLVED: Phase 1 standardizes on the sync **pg8000** driver (matching
    the Cloud SQL connector's documented sync driver), so the test engine and
    Alembic env.py agree on one driver.
    """
    explicit = _database_url_from_env()
    if explicit:
        # Normalize any driver the env DSN happens to carry to pg8000.
        for prefix in (
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            "postgresql://",
        ):
            if explicit.startswith(prefix):
                return "postgresql+pg8000://" + explicit[len(prefix):]
        return explicit

    if pg_container is None:  # pragma: no cover - guarded by pg_container skip
        pytest.skip("No Postgres container and no DATABASE_URL available")

    # testcontainers hands back a psycopg2 URL by default; swap the driver.
    url = pg_container.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql+pg8000://")


def _run_migrations(engine: Any) -> None:
    """Single call site for building the schema into the container.

    Runs ``alembic upgrade head`` against the test engine's URL. This is the
    ONE place the suite materializes the schema; the schema-shape and RLS
    suites depend on it. It WILL fail RED until plan 01-02 lands the Alembic
    migrations — that is the intended Wave 0 state, so failures here are
    surfaced as skips so the harness itself stays collectable.
    """
    try:
        from alembic import command  # type: ignore
        from alembic.config import Config  # type: ignore
    except ImportError:
        pytest.skip("alembic not installed yet (Wave 0 dev deps pending)")
        return

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(backend_root, "alembic.ini")
    if not os.path.exists(alembic_ini):
        # Plans 01-02/01-03 land alembic.ini + versions/. Until then there is
        # no schema to build; the consuming suites are RED-by-design.
        pytest.skip("alembic.ini not present yet (schema lands in plan 01-02)")
        return

    cfg = Config(alembic_ini)
    cfg.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# app_superadmin role fixture (Cloud SQL has no BYPASSRLS — bypass via role)
# ---------------------------------------------------------------------------

def _ensure_app_superadmin(engine: Any) -> None:
    """Create the `app_superadmin` LOGIN role if it does not already exist.

    On real Cloud SQL this role is created out-of-band (`gcloud sql users
    create app_superadmin ...`); in the local/test container we create it in
    this fixture. Idempotent: guards against the duplicate-role error so a
    re-run of the session-scoped fixture (or a reused DSN) does not blow up.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'app_superadmin'")
        ).first()
        if exists is None:
            # DO block so concurrent CI sessions racing the CREATE both succeed.
            conn.execute(
                text(
                    "DO $$ BEGIN "
                    "  CREATE ROLE app_superadmin LOGIN; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$;"
                )
            )


# ---------------------------------------------------------------------------
# Session-scoped engine fixture (sync pg8000) — builds schema via Alembic
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def engine(pg_container):
    """Yield a sync SQLAlchemy engine bound to the pgvector container / DSN.

    Side effects (session-scoped, run once):
      1. create the `app_superadmin` bypass role,
      2. run `alembic upgrade head` to build the schema (RED until plan 01-02).
    """
    sa = pytest.importorskip("sqlalchemy")

    url = _sync_pg8000_url(pg_container)
    eng = sa.create_engine(url, echo=False, future=True, pool_pre_ping=True)
    try:
        _ensure_app_superadmin(eng)
        _run_migrations(eng)
        yield eng
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# Transaction-local GUC helper (canonical SET LOCAL pattern — Pitfall 1)
# ---------------------------------------------------------------------------

@pytest.fixture
def set_space():
    """Return a helper that sets `app.current_space_id` for the current tx.

    Mirrors `backend/app/db/rls.py::set_space_context` (plan 01-02):

        SELECT set_config('app.current_space_id', :sid, true)

    The third argument `true` makes the setting **transaction-local**
    (equivalent to `SET LOCAL`), NOT session-local. NEVER pass `false` — a
    session-scoped GUC leaks across pooled connections and is a catastrophic
    cross-tenant data leak (01-RESEARCH.md Pitfall 1).
    """
    from sqlalchemy import text

    def _set_space(conn_or_session: Any, space_id: Any) -> None:
        conn_or_session.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )

    return _set_space


# ---------------------------------------------------------------------------
# Two-space UUID pair for cross-tenant RLS tests
# ---------------------------------------------------------------------------

@pytest.fixture
def two_spaces():
    """Return a deterministic-per-call `(space_a, space_b)` UUID tuple.

    Distinct UUIDs so the cross-tenant denial test can prove space_b's rows
    are invisible to a session scoped to space_a.
    """
    return uuid.uuid4(), uuid.uuid4()
