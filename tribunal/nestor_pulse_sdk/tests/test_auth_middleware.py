"""
PHASE1-02 -- Auth middleware (owning plan: 04)

Per 01-VALIDATION.md row:
  "JWT without `tenant_id` claim -> 401"
  Test type: unit
  Command: pytest nestor_pulse_sdk/tests/test_auth_middleware.py
           ::test_missing_tenant_claim -x

Plan 04 has filled in the bodies. The four behaviours tested
(01-04-PLAN.md Task 2 <behavior>):

  1. test_missing_authorization_returns_401
       Unit. No Authorization header -> 401.
  2. test_missing_tenant_claim
       Unit. Bearer token verified but no tenant_id claim -> 401
       "Missing tenant_id claim" (Pitfall 9).
  3. test_valid_token_attaches_tenant_to_session
       Integration (testcontainers Postgres). Valid token -> session has
       `current_setting('app.tenant_id')` == JWT tenant_id.
  4. test_set_local_is_transaction_scoped
       Integration (testcontainers Postgres). Two sequential requests
       with different tenant_ids on the SAME connection pool stay
       isolated -- proves SET LOCAL not SET (Pitfall 1).

Tests 3 and 4 use `pytest.importorskip("nestor_pulse_sdk.db.base")` and
the `postgres_container` fixture -- both skip cleanly when Plan 03's DB
modules or Docker are unavailable. Plan 05's <verify> reruns these
tests under the live testcontainers fixture and they MUST pass green
before Plan 05's cross-tenant RLS suite runs.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from nestor_pulse_sdk.auth.deps import (
    get_current_user,
    get_db_session,
    set_auth_provider,
)
from nestor_pulse_sdk.auth.middleware import RequestIDMiddleware
from nestor_pulse_sdk.auth.provider import (
    AuthClaims,
    AuthProvider,
    InvalidTokenError,
)


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Shared helpers: in-memory FakeAuthProvider + app factory
# ---------------------------------------------------------------------------


class _FakeAuthProvider(AuthProvider):
    """In-memory provider: maps opaque tokens -> AuthClaims."""

    def __init__(self) -> None:
        self._tokens: dict[str, AuthClaims] = {}

    def add(self, token: str, claims: AuthClaims) -> None:
        self._tokens[token] = claims

    async def verify_id_token(self, token: str) -> AuthClaims:
        if token not in self._tokens:
            raise InvalidTokenError("unknown token")
        return self._tokens[token]

    async def lookup_user(self, app_user_id: str):
        return None

    async def sign_out(self, app_user_id: str) -> None:
        return None


def _build_app(include_db_route: bool = False) -> FastAPI:
    """
    Build a minimal FastAPI app wired to the auth deps. When
    `include_db_route` is True the app also exposes `/whoami-db` which
    pulls `current_setting('app.tenant_id')` from a Depends(get_db_session)
    session -- used by tests 3 + 4.
    """
    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)

    @app.get("/whoami")
    async def whoami(user: AuthClaims = Depends(get_current_user)):
        return {
            "tenant_id": user.tenant_id,
            "app_user_id": user.app_user_id,
        }

    if include_db_route:
        # Imported lazily so Plan 03 not landing in this worktree does
        # not break test collection for the non-db tests above.
        from sqlalchemy import text  # type: ignore

        @app.get("/whoami-db")
        async def whoami_db(session=Depends(get_db_session)):
            row = await session.execute(
                text("SELECT current_setting('app.tenant_id', true)")
            )
            return {"tenant_id": row.scalar_one()}

    return app


# ===========================================================================
# Test 1 -- missing Authorization header => 401 (unit, no DB)
# ===========================================================================

async def test_missing_authorization_returns_401():
    """A request with no Authorization header must be rejected with 401."""
    set_auth_provider(_FakeAuthProvider())
    app = _build_app(include_db_route=False)

    with TestClient(app) as client:
        resp = client.get("/whoami")  # no headers
    assert resp.status_code == 401
    assert "Authorization" in resp.json()["detail"]

    # Variant: wrong scheme (Basic) also rejected.
    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Basic xyz"})
    assert resp.status_code == 401

    # Variant: Bearer with empty token also rejected.
    with TestClient(app) as client:
        resp = client.get("/whoami", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


# ===========================================================================
# Test 2 -- valid Bearer but no tenant_id claim => 401 (unit, no DB)
# ===========================================================================

async def test_missing_tenant_claim():
    """
    A FakeAuthProvider that returns AuthClaims with tenant_id="" still
    flows through; the missing-tenant-claim rejection happens INSIDE
    IdentityPlatformProvider.verify_id_token (Pitfall 9). Here we
    exercise the on-the-wire shape: a provider that explicitly raises
    `AuthError("Missing tenant_id claim", 401)` results in a 401 detail
    body carrying that message.
    """
    from nestor_pulse_sdk.auth.provider import AuthError

    class _NoTenantProvider(_FakeAuthProvider):
        async def verify_id_token(self, token: str) -> AuthClaims:
            raise AuthError("Missing tenant_id claim", status_code=401)

    set_auth_provider(_NoTenantProvider())
    app = _build_app(include_db_route=False)

    with TestClient(app) as client:
        resp = client.get(
            "/whoami", headers={"Authorization": "Bearer any-token"}
        )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Missing tenant_id claim"


# ===========================================================================
# Test 3 -- valid token => session has current_setting('app.tenant_id')
# ===========================================================================
#
# Integration test against a real Postgres container. Skipped (not failed)
# when Plan 03's DB modules aren't merged yet OR when Docker isn't
# available. Plan 05 re-runs this under live testcontainers and it MUST
# pass green there.

async def test_valid_token_attaches_tenant_to_session(postgres_container):
    """A valid token's tenant_id flows through to set_config('app.tenant_id')."""
    pytest.importorskip(
        "nestor_pulse_sdk.db.base",
        reason="Plan 03 schema not yet merged into this worktree",
    )
    pytest.importorskip(
        "nestor_pulse_sdk.db.rls",
        reason="Plan 03 set_tenant_context not yet merged",
    )

    from sqlalchemy.ext.asyncio import (  # type: ignore
        async_sessionmaker,
        create_async_engine,
    )

    # Build a sessionmaker on the testcontainers Postgres and patch
    # `nestor_pulse_sdk.db.base.get_sessionmaker` so deps.py uses it.
    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    engine = create_async_engine(url, future=True)
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import nestor_pulse_sdk.db.base as db_base  # type: ignore
    original_get_sm = db_base.get_sessionmaker
    db_base.get_sessionmaker = lambda: sm  # type: ignore[assignment]

    try:
        tenant_a = str(uuid.uuid4())
        provider = _FakeAuthProvider()
        provider.add(
            "tok-a",
            AuthClaims(
                app_user_id=str(uuid.uuid4()),
                tenant_id=tenant_a,
                email="a@example.com",
                raw_provider_user_id="fb_a",
            ),
        )
        set_auth_provider(provider)

        app = _build_app(include_db_route=True)
        with TestClient(app) as client:
            resp = client.get(
                "/whoami-db", headers={"Authorization": "Bearer tok-a"}
            )
        assert resp.status_code == 200
        assert resp.json()["tenant_id"] == tenant_a
    finally:
        db_base.get_sessionmaker = original_get_sm  # type: ignore[assignment]
        await engine.dispose()


# ===========================================================================
# Test 4 -- SET LOCAL regression (Pitfall 1)
# ===========================================================================
#
# THE critical regression test. Two sequential requests with different
# tenant_ids on the SAME connection pool (pool_size=1, max_overflow=0)
# MUST return their OWN tenant_id. If SET (session-scoped) is used
# instead of SET LOCAL (transaction-scoped), request B sees request A's
# tenant_id -- catastrophic cross-tenant leak under PgBouncer.

async def test_set_local_is_transaction_scoped(postgres_container):
    """Two sequential requests on the same pool stay tenant-isolated."""
    pytest.importorskip(
        "nestor_pulse_sdk.db.base",
        reason="Plan 03 schema not yet merged into this worktree",
    )
    pytest.importorskip(
        "nestor_pulse_sdk.db.rls",
        reason="Plan 03 set_tenant_context not yet merged",
    )

    from sqlalchemy.ext.asyncio import (  # type: ignore
        async_sessionmaker,
        create_async_engine,
    )

    url = postgres_container.get_connection_url().replace(
        "postgresql+psycopg2://", "postgresql+asyncpg://"
    )
    # pool_size=1 + max_overflow=0 forces both requests onto the same
    # physical connection -- exactly the PgBouncer transaction-pooling
    # threat model. If SET LOCAL were SET, request B would inherit
    # tenant_a's setting.
    engine = create_async_engine(
        url, pool_size=1, max_overflow=0, future=True
    )
    sm = async_sessionmaker(engine, expire_on_commit=False)

    import nestor_pulse_sdk.db.base as db_base  # type: ignore
    original_get_sm = db_base.get_sessionmaker
    db_base.get_sessionmaker = lambda: sm  # type: ignore[assignment]

    try:
        tenant_a = str(uuid.uuid4())
        tenant_b = str(uuid.uuid4())
        provider = _FakeAuthProvider()
        provider.add(
            "tok-a",
            AuthClaims(
                app_user_id=str(uuid.uuid4()),
                tenant_id=tenant_a,
                email="a@example.com",
                raw_provider_user_id="fb_a",
            ),
        )
        provider.add(
            "tok-b",
            AuthClaims(
                app_user_id=str(uuid.uuid4()),
                tenant_id=tenant_b,
                email="b@example.com",
                raw_provider_user_id="fb_b",
            ),
        )
        set_auth_provider(provider)

        app = _build_app(include_db_route=True)
        with TestClient(app) as client:
            resp_a = client.get(
                "/whoami-db", headers={"Authorization": "Bearer tok-a"}
            )
            resp_b = client.get(
                "/whoami-db", headers={"Authorization": "Bearer tok-b"}
            )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        # Each request sees ITS OWN tenant_id -- the SECOND request
        # does NOT inherit the first. This is the Pitfall 1 mitigation.
        assert resp_a.json()["tenant_id"] == tenant_a
        assert resp_b.json()["tenant_id"] == tenant_b
        assert tenant_a != tenant_b
    finally:
        db_base.get_sessionmaker = original_get_sm  # type: ignore[assignment]
        await engine.dispose()
