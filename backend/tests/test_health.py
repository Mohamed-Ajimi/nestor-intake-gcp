"""Health-endpoint suite — covers the split liveness/readiness probes (D-07)
and the no-detail-leak readiness failure path (T-02-01).

Marker split (per 02-PATTERNS.md):
- ``test_healthz_no_db``   -- TestClient, NO marker, runs without Docker; asserts
                              /healthz never touches the DB (liveness, Pitfall 4).
- ``test_readyz_db_ok``    -- integration-marked; binds the app engine to the
                              conftest ``engine`` fixture URL and asserts SELECT 1 -> 200.
- ``test_readyz_db_down``  -- unit (NO marker); monkeypatches get_engine to an engine
                              whose .connect() raises; asserts 503 + no DSN/exception leak.

The integration marker is applied PER-TEST (only on test_readyz_db_ok) so the no-DB
cases run on the dev box.

Authoritative references:
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-RESEARCH.md
    § Validation Architecture (test map) -- test_healthz_no_db / test_readyz_db_ok /
      test_readyz_db_down rows (API-01 / INFRA-04 / D-07)
    § Pattern 2 (lines 219-250) -- split health endpoints, sync handlers, 200/503 codes
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-PATTERNS.md
    § backend/tests/test_health.py -- TestClient + marker split + engine binding
- threat_model T-02-01 -- /readyz returns generic error, never echoes exception/DSN text.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.db import base
from app.main import app


@pytest.fixture(autouse=True)
def _clear_engine_caches():
    """Reset the engine lru_cache around every test so a monkeypatched or
    fixture-bound engine never leaks into the next case."""
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()
    yield
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()


def test_healthz_no_db(monkeypatch):
    """GET /healthz -> 200 {"status":"ok"} and NEVER opens a DB connection.

    We replace get_engine with a sentinel that fails if invoked: liveness must
    not depend on the DB (Pitfall 4 — a Cloud SQL blip must not fail liveness
    and cycle instances).
    """

    def _boom(*args, **kwargs):  # pragma: no cover - asserts it is never called
        raise AssertionError("/healthz must not call get_engine()")

    # Patch the name as imported into app.main (handlers call get_engine there).
    monkeypatch.setattr(main_module, "get_engine", _boom, raising=True)

    client = TestClient(app)
    resp = client.get("/healthz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.integration
def test_readyz_db_ok(engine, monkeypatch):
    """GET /readyz -> 200 {"status":"ready","db":"ok"} against a reachable DB.

    Bind the app's engine to the conftest ``engine`` fixture's URL via the
    explicit get_engine(database_url=...) path so readiness runs SELECT 1 through
    the testcontainer, not the Cloud SQL connector. Skips cleanly without Docker
    (the ``engine`` fixture handles the skip).
    """
    bound = base.get_engine(database_url=str(engine.url))
    monkeypatch.setattr(main_module, "get_engine", lambda: bound, raising=True)

    client = TestClient(app)
    resp = client.get("/readyz")

    assert resp.status_code == 200
    assert resp.json() == {"status": "ready", "db": "ok"}


def test_readyz_db_down(monkeypatch):
    """GET /readyz -> 503 {"status":"not-ready","db":"error"} when the DB is
    unreachable, leaking NO DSN / exception text (T-02-01)."""
    secret_detail = "postgresql+pg8000://secret-user:secret-pass@10.0.0.1:5432/prod"

    failing_engine = MagicMock()
    failing_engine.connect.side_effect = RuntimeError(secret_detail)

    monkeypatch.setattr(main_module, "get_engine", lambda: failing_engine, raising=True)

    client = TestClient(app)
    resp = client.get("/readyz")

    assert resp.status_code == 503
    assert resp.json() == {"status": "not-ready", "db": "error"}
    # No part of the connection string / exception text may surface in the body.
    body = resp.text
    assert "secret-user" not in body
    assert "secret-pass" not in body
    assert "10.0.0.1" not in body
    assert secret_detail not in body
