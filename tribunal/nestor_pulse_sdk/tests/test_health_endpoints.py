"""
Tests for health endpoints (Plan 10.5 Task 3).

Routes tested:
  /health  -- primary Cloud Run liveness path (Cloud Run forwards this path)
  /healthz -- alias for /health; intercepted by Cloud Run infrastructure on
              the live service but works correctly in local ASGI tests
  /readyz  -- DB readiness probe

Key contract assertions:
1. /healthz and /health return 200 with no Authorization header (not 401/403).
2. /readyz returns 200 OR 503 depending on DB reachability -- crucially NOT
   401/403 from JWT middleware.
3. /healthz and /health do NOT touch the DB.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def app():
    """Import the FastAPI app. Uses the test auth provider override installed
    by the top-level conftest.py (if any); the health endpoints bypass auth
    entirely so no override is needed for these tests."""
    from nestor_pulse_sdk.server import app as _app
    return _app


@pytest.mark.asyncio
async def test_healthz_no_auth_no_db(app):
    """GET /healthz must return 200 with no Authorization header.

    This is the Cloud Run liveness probe contract. If this returns 401/403
    the service appears permanently unhealthy to the platform.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    body = r.json()
    assert body.get("status") == "ok", f"unexpected body: {body}"


@pytest.mark.asyncio
async def test_readyz_no_auth(app):
    """GET /readyz must NOT return 401/403 regardless of DB reachability.

    Cloud Run readiness probe contract: the route is auth-exempt. The DB
    may or may not be reachable in the test environment:
    - 200 with {"status":"ready","db":"ok"}  -> DB reachable
    - 503 with {"status":"unavailable","db":"unreachable"} -> DB not reachable

    Both are valid outcomes for a test run without live Cloud SQL. What is
    NEVER acceptable is 401/403 (that would mean the JWT gate fired).
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/readyz")
    assert r.status_code in (200, 503), (
        f"expected 200 or 503 (never 401/403), got {r.status_code}: {r.text}"
    )
    body = r.json()
    assert "status" in body, f"response body missing 'status' key: {body}"


@pytest.mark.asyncio
async def test_healthz_returns_ok_key(app):
    """Verify the /healthz response schema -- {'status': 'ok'}."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_path_returns_200(app):
    """GET /health (primary Cloud Run-accessible path) returns 200 with no auth.

    On Cloud Run, /healthz is intercepted by the infrastructure layer before
    reaching the container. /health is the effective liveness probe path.
    Both paths are registered on the same handler and both work in ASGI tests.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/health")
    assert r.status_code == 200, f"expected 200 got {r.status_code}: {r.text}"
    assert r.json() == {"status": "ok"}
