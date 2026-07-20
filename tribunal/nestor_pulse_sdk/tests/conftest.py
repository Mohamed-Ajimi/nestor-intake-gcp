"""
Pytest fixtures for the Nestor Pulse SDK test suite.

Authoritative references:
- .planning/phases/01-production-foundation/01-VALIDATION.md
    -- Wave 0 Requirements + Per-Task Verification Map
- .planning/phases/01-production-foundation/01-RESEARCH.md
    -- Pitfall 1 (SET LOCAL with third-arg `true`)
    -- Pattern 1 (tenant context dependency)
- .planning/phases/01-production-foundation/01-PATTERNS.md
    -- Shared Patterns: Tenant context dependency (RLS guard)
- .planning/phases/01-production-foundation/01-CONTEXT.md
    -- D-05 (RLS), D-10 (AuthProvider abstraction)

Design notes:
- testcontainers PostgresContainer is session-scoped and SKIPPED cleanly
  when Docker is not reachable (per 01-VALIDATION.md § Environment Notes:
  Docker may be missing on Mohamed's dev box).
- All fixtures that depend on as-yet-unbuilt modules use
  pytest.importorskip(...) so the suite can stay green via xfail before
  the owning plans land. This is the canonical Wave 0 scaffolding shape.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Session-scoped Postgres container fixture (testcontainers)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def postgres_container():
    """
    Spin up an ephemeral postgres:15 container via testcontainers.

    Skipped (not errored) if Docker is not reachable -- per
    01-VALIDATION.md § Environment Notes, Docker availability is a known
    gap on Mohamed's dev box. The suite must still exit 0 in that case.
    """
    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore
    except ImportError:
        pytest.skip("testcontainers not installed yet (Wave 0 deps pending)")

    try:
        container = PostgresContainer("postgres:15")
        container.start()
    except Exception as exc:  # noqa: BLE001 -- catch DockerException family
        pytest.skip(f"Docker not available for testcontainers: {exc}")
        return None  # unreachable; pytest.skip raises

    try:
        yield container
    finally:
        try:
            container.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Function-scoped async engine fixture
# ---------------------------------------------------------------------------

@pytest.fixture
async def async_engine(postgres_container):
    """
    Yield a SQLAlchemy 2.x async engine pointed at the testcontainers
    Postgres instance. Returns a usable engine even before Plan 03's
    schema modules exist -- consumers that need the schema use
    pytest.importorskip("nestor_pulse_sdk.db.base") to xfail cleanly.
    """
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")

    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = sa.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Tenant-context helper (canonical SET LOCAL pattern -- Pitfall 1)
# ---------------------------------------------------------------------------

@pytest.fixture
def set_tenant():
    """
    Canonical helper that Plan 04 imports for production. Sets the
    `app.tenant_id` Postgres config key for the current transaction.

    Mirrors 01-RESEARCH.md lines 354-359 verbatim:
        SELECT set_config('app.tenant_id', :t, true)
    The third argument `true` makes it transaction-local, NOT session-
    local (Pitfall 1).
    """
    sa_text = pytest.importorskip("sqlalchemy").text

    async def _set_tenant(session: Any, tenant_id: Any) -> None:
        await session.execute(
            sa_text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(tenant_id)},
        )

    return _set_tenant


# ---------------------------------------------------------------------------
# Fake AuthProvider fixture (D-10 abstraction)
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_auth_provider():
    """
    In-memory AuthProvider implementation for unit tests so we never hit
    Firebase / Identity Platform during unit runs.

    The real AuthProvider abstract base lives in
    `nestor_pulse_sdk.auth.provider` (Plan 04). Until Plan 04 lands the
    interface, this fixture importorskip's that module so tests
    referencing it xfail cleanly.
    """
    provider_mod = pytest.importorskip(
        "nestor_pulse_sdk.auth.provider",
        reason="AuthProvider interface lands in Plan 04",
    )

    class _FakeAuthProvider(provider_mod.AuthProvider):  # type: ignore[name-defined]
        def __init__(self) -> None:
            self._tokens: dict[str, Any] = {}

        def add_token(self, token: str, claims: Any) -> None:
            self._tokens[token] = claims

        async def verify_id_token(self, token: str):
            if token not in self._tokens:
                raise provider_mod.InvalidTokenError(  # type: ignore[attr-defined]
                    "unknown token"
                )
            return self._tokens[token]

    return _FakeAuthProvider()


# ---------------------------------------------------------------------------
# Two-tenant UUID pair for RLS cross-tenant tests
# ---------------------------------------------------------------------------

@pytest.fixture
def two_tenants():
    """Return a `(tenant_a, tenant_b)` UUID tuple for RLS isolation tests."""
    return uuid.uuid4(), uuid.uuid4()
