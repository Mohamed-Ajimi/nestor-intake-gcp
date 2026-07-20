"""
PHASE1-06 / D-09 -- Run status survives browser disconnect (owning plan: 06)

Tests:
  1. POST /api/runs creates a queued run (201).
  2. GET /api/runs/{id} returns the run under repeated polling (status stable).
  3. Manual status transitions queued -> running -> completed reflect via GET.
  4. POST twice with same (tenant_id, idempotency_key) returns same run (200 or 201, no dup).
  5. POST with engine='foo' returns 422 validation error (Literal type).
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient


TENANT_ID = str(uuid.uuid4())
TOKEN = "test-token-resilience"


# ---------------------------------------------------------------------------
# Minimal fake auth provider
# ---------------------------------------------------------------------------

def _make_fake_provider(token: str, claims):
    from nestor_pulse_sdk.auth.provider import AuthProvider, InvalidTokenError

    class _FakeProvider(AuthProvider):
        async def verify_id_token(self, tok):
            if tok != token:
                raise InvalidTokenError("unknown token")
            return claims

        async def lookup_user(self, _):
            return None

        async def sign_out(self, _):
            return None

    return _FakeProvider()


def _make_claims(tenant_id: str):
    from nestor_pulse_sdk.auth.provider import AuthClaims
    return AuthClaims(
        app_user_id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email="test@example.com",
        raw_provider_user_id="fb_test",
    )


# ---------------------------------------------------------------------------
# In-memory mock session factory
# ---------------------------------------------------------------------------

def make_run_store_session(run_store: dict, tenant_id: str, project_id: uuid.UUID):
    """
    Returns a mock AsyncSession that:
      - Returns a fake Project for Project selects (project existence check).
      - Handles Run inserts via flush() with idempotency check.
      - Returns Runs from run_store for Run selects.
      - Handles rollback() for IntegrityError recovery path.
    """
    from nestor_pulse_sdk.db.models.run import Run
    from nestor_pulse_sdk.db.models.project import Project
    from sqlalchemy.exc import IntegrityError

    session = MagicMock()

    _pending: list = []

    def _add(obj):
        _pending.append(obj)

    session.add = _add

    async def _flush():
        for obj in _pending[:]:
            if isinstance(obj, Run):
                key = (str(obj.tenant_id), str(obj.idempotency_key))
                # Check for existing entry with same idempotency key
                for rid, rdata in run_store.items():
                    if (str(rdata["tenant_id"]) == str(obj.tenant_id)
                            and str(rdata["idempotency_key"]) == str(obj.idempotency_key)):
                        _pending.clear()
                        raise IntegrityError("dup key", None, None)
                # New run: populate fields from object, add to store
                now = datetime.datetime.now(datetime.timezone.utc)
                if not hasattr(obj, "id") or obj.id is None:
                    obj.id = uuid.uuid4()
                run_store[obj.id] = {
                    "id": obj.id,
                    "tenant_id": obj.tenant_id if isinstance(obj.tenant_id, uuid.UUID)
                                 else uuid.UUID(str(obj.tenant_id)),
                    "project_id": obj.project_id if isinstance(obj.project_id, uuid.UUID)
                                  else uuid.UUID(str(obj.project_id)),
                    "engine": obj.engine,
                    "brief": obj.brief,
                    "status": obj.status,
                    "idempotency_key": obj.idempotency_key if isinstance(obj.idempotency_key, uuid.UUID)
                                       else uuid.UUID(str(obj.idempotency_key)),
                    "worker_id": None,
                    "created_at": now,
                    "started_at": None,
                    "completed_at": None,
                    "error_message": None,
                    "cost_usd_total": None,
                    "comparison_id": getattr(obj, "comparison_id", None),
                }
                # sync obj attributes from store so model_validate works
                for k, v in run_store[obj.id].items():
                    object.__setattr__(obj, k, v) if hasattr(type(obj), '__slots__') else setattr(obj, k, v)
            _pending.clear()

    session.flush = _flush

    async def _rollback():
        _pending.clear()

    session.rollback = _rollback

    class _Result:
        def __init__(self, rows):
            self._rows = list(rows)

        def scalar_one_or_none(self):
            return self._rows[0] if self._rows else None

        def scalar_one(self):
            if not self._rows:
                raise Exception("no rows")
            return self._rows[0]

        def scalars(self):
            return self

        def all(self):
            return self._rows

    async def _execute(stmt, params=None):
        # 1. set_config (tenant context) -- always OK
        stmt_str = str(stmt)
        if "set_config" in stmt_str:
            return _Result([])

        # 2. Raw text SQL (UPDATE, etc.)
        from sqlalchemy import text as sa_text
        if hasattr(stmt, "text") and callable(stmt.text):
            return _Result([])
        try:
            from sqlalchemy.sql.elements import TextClause
            if isinstance(stmt, TextClause):
                return _Result([])
        except Exception:
            pass

        # 3. Inspect the SELECT to determine if it's Project or Run
        try:
            from sqlalchemy import inspect as _inspect
            from sqlalchemy.orm.context import QueryContext
        except Exception:
            pass

        # Use entity detection heuristic: check the first column/table
        try:
            # Get the entity being selected (SQLAlchemy 2.x ORM select)
            entities = []
            if hasattr(stmt, "columns_clause_froms"):
                for frm in stmt.columns_clause_froms:
                    if hasattr(frm, "entity"):
                        entities.append(frm.entity)
            if hasattr(stmt, "_raw_columns"):
                for col in stmt._raw_columns:
                    if hasattr(col, "entity_zero") and col.entity_zero is not None:
                        entities.append(col.entity_zero.mapper.class_)
        except Exception:
            pass

        # Fallback: compile and check the SQL string
        try:
            from sqlalchemy.dialects import postgresql
            sql_str = stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": False}).string.lower()
        except Exception:
            sql_str = stmt_str.lower()

        # Check if this is a Project query
        if "from project" in sql_str or "join project" in sql_str:
            p = MagicMock(spec=Project)
            p.id = project_id
            p.tenant_id = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id
            p.name = "Test Project"
            return _Result([p])

        # Check if this is a Run query
        if "from run" in sql_str or '"run"' in sql_str:
            # Extract filters if present (for idempotency lookup and get_run)
            # Just search the entire run store for matching rows, bounded by tenant
            tenant_uuid = uuid.UUID(tenant_id) if isinstance(tenant_id, str) else tenant_id

            # Get WHERE clause conditions from the stmt to detect idempotency_key filter
            where_parts = []
            try:
                if hasattr(stmt, "whereclause") and stmt.whereclause is not None:
                    where_parts.append(str(stmt.whereclause))
            except Exception:
                pass

            where_str = " ".join(where_parts).lower()

            results = []
            for rid, rdata in run_store.items():
                if str(rdata["tenant_id"]) != str(tenant_uuid):
                    continue
                # For idempotency lookup: filter by idempotency_key and run_id
                # We return all runs for this tenant and let scalar_one_or_none work
                r = MagicMock(spec=Run)
                for k, v in rdata.items():
                    setattr(r, k, v)
                results.append(r)

            # If looking for a specific run_id (GET /api/runs/{id}),
            # the stmt will have a WHERE run.id = <uuid> clause
            # We detect this by checking if ANY run_id is in the where clause
            if where_str:
                # Filter by run id if present in WHERE clause
                filtered = []
                for r in results:
                    if where_str and str(r.id).lower() in where_str:
                        filtered.append(r)
                # Also filter by idempotency_key if present
                for r in results:
                    if where_str and str(r.idempotency_key).lower() in where_str:
                        if r not in filtered:
                            filtered.append(r)
                if filtered:
                    return _Result(filtered)

            return _Result(results)

        return _Result([])

    session.execute = _execute
    return session


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _tenant_id():
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def _project_id():
    return uuid.uuid4()


@pytest.fixture(scope="module")
def _claims(_tenant_id):
    return _make_claims(_tenant_id)


@pytest.fixture(scope="module")
def _provider(_claims):
    return _make_fake_provider(TOKEN, _claims)


@pytest.fixture
def client_with_store(_tenant_id, _project_id, _claims, _provider):
    """
    TestClient + shared run_store dict.
    We override get_current_user and get_db_session to avoid hitting real DB.
    """
    from nestor_pulse_sdk.auth.deps import get_db_session, get_current_user, set_auth_provider
    from nestor_pulse_sdk.runs.api import router

    set_auth_provider(_provider)

    run_store: dict[uuid.UUID, dict] = {}

    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.include_router(router)

    # Override auth dep to return claims without hitting Identity Platform
    app.dependency_overrides[get_current_user] = lambda: _claims
    # Override DB dep to yield our mock session
    app.dependency_overrides[get_db_session] = lambda: make_run_store_session(
        run_store, _tenant_id, _project_id
    )

    tc = TestClient(app)
    return tc, run_store, _project_id, _tenant_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestRunStatusResilience:

    def test_post_runs_creates_queued(self, client_with_store):
        tc, run_store, project_id, tenant_id = client_with_store
        idem_key = str(uuid.uuid4())

        resp = tc.post(
            "/api/runs",
            json={
                "project_id": str(project_id),
                "brief": "Test brief for new run",
                "engine": "sdk",
                "idempotency_key": idem_key,
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["status"] == "queued"
        assert "id" in body
        assert body["engine"] == "sdk"
        assert body["brief"] == "Test brief for new run"

    def test_get_runs_id_returns_status_under_polling(self, client_with_store):
        tc, run_store, project_id, tenant_id = client_with_store
        idem_key = str(uuid.uuid4())

        # Create a run first
        create_resp = tc.post(
            "/api/runs",
            json={
                "project_id": str(project_id),
                "brief": "Polling test brief",
                "engine": "adk",
                "idempotency_key": idem_key,
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert create_resp.status_code == 201, create_resp.text
        run_id = create_resp.json()["id"]

        # Poll 3 times -- status must be consistent
        for _ in range(3):
            poll_resp = tc.get(
                f"/api/runs/{run_id}",
                headers={"Authorization": f"Bearer {TOKEN}"},
            )
            assert poll_resp.status_code == 200, poll_resp.text
            assert poll_resp.json()["status"] == "queued"
            assert poll_resp.json()["id"] == run_id

    def test_status_transitions_queued_running_completed(self, client_with_store):
        tc, run_store, project_id, tenant_id = client_with_store
        idem_key = str(uuid.uuid4())

        # Create
        create_resp = tc.post(
            "/api/runs",
            json={
                "project_id": str(project_id),
                "brief": "Transition test brief",
                "engine": "sdk",
                "idempotency_key": idem_key,
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert create_resp.status_code == 201, create_resp.text
        run_id = create_resp.json()["id"]
        run_uuid = uuid.UUID(run_id)

        # Manually transition: queued -> running
        run_store[run_uuid]["status"] = "running"
        now = datetime.datetime.now(datetime.timezone.utc)
        run_store[run_uuid]["started_at"] = now

        get_resp = tc.get(
            f"/api/runs/{run_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert get_resp.status_code == 200, get_resp.text
        assert get_resp.json()["status"] == "running"

        # Transition: running -> completed
        run_store[run_uuid]["status"] = "completed"
        run_store[run_uuid]["completed_at"] = datetime.datetime.now(datetime.timezone.utc)

        get_resp2 = tc.get(
            f"/api/runs/{run_id}",
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert get_resp2.status_code == 200, get_resp2.text
        assert get_resp2.json()["status"] == "completed"

    def test_idempotency_key_returns_existing(self, client_with_store):
        tc, run_store, project_id, tenant_id = client_with_store
        idem_key = str(uuid.uuid4())

        payload = {
            "project_id": str(project_id),
            "brief": "Idempotency test brief",
            "engine": "adk",
            "idempotency_key": idem_key,
        }

        # First POST -> 201
        resp1 = tc.post(
            "/api/runs",
            json=payload,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp1.status_code == 201, resp1.text
        run_id_1 = resp1.json()["id"]

        # Second POST with same idempotency_key -> returns same run (200 or 201, not 409)
        resp2 = tc.post(
            "/api/runs",
            json=payload,
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp2.status_code in (200, 201), resp2.text
        run_id_2 = resp2.json()["id"]
        assert run_id_1 == run_id_2, (
            f"Expected same run ID on retry but got {run_id_1} vs {run_id_2}"
        )

    def test_engine_must_be_adk_or_sdk(self, client_with_store):
        tc, run_store, project_id, tenant_id = client_with_store

        resp = tc.post(
            "/api/runs",
            json={
                "project_id": str(project_id),
                "brief": "Engine validation test",
                "engine": "foo",
                "idempotency_key": str(uuid.uuid4()),
            },
            headers={"Authorization": f"Bearer {TOKEN}"},
        )
        assert resp.status_code == 422, (
            f"Expected 422 but got {resp.status_code}: {resp.text}"
        )
