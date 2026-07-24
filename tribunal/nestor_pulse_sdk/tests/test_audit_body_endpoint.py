"""
Audit-body drill-down endpoint tests (Phase 15 ENGINE-09, Plan 15-03 Task 4).

GET /api/runs/{run_id}/audit/{audit_id} is the feed's audit_id drill-down: it
returns the ALREADY-REDACTED request/response of one LLM call, read back from GCS.

Two cases (per acceptance):

  (a) HAPPY PATH -- a same-tenant call for a known audit_id returns the redacted
      body carrying request + response keys and NO hash / prev_hash key. The
      audit_log SELECT resolves (tenant sees its own row) and download_audit_body
      is MOCKED (no live GCS in tests) to return the stored redacted body.

  (b) RLS DENIAL -- a foreign-tenant audit_id (or one whose run_id != the path
      run_id) reads as absent under RLS, so the audit_log scalar_one_or_none is
      None -> EXACTLY 404, and the foreign audit_id string is not in the body.

Mirrors the FastAPI TestClient + fake-db-session pattern of test_seam_denial.py /
test_run_status_resilience.py. DB-free by design (the SELECT result is faked; the
GCS read is mocked) so it runs on a box with no Postgres and no GCP.

Cloud Build gate:
  pytest nestor_pulse_sdk/tests/test_audit_body_endpoint.py -x
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient transport

from unittest.mock import AsyncMock, patch  # noqa: E402 -- after importorskip guards


# ---------------------------------------------------------------------------
# Fake audit_log row + SELECT result plumbing
# ---------------------------------------------------------------------------

class _FakeAuditRow:
    """Minimal AuditLog stand-in carrying the fields the endpoint reads."""

    def __init__(self, gcs_uri: str, provider: str, model: str):
        self.gcs_uri = gcs_uri
        self.provider = provider
        self.model = model


class _Result:
    def __init__(self, row):
        self._row = row

    def scalar_one_or_none(self):
        return self._row


class _Session:
    """Fake AsyncSession whose SELECT yields `row` (a _FakeAuditRow or None).

    None models an RLS miss -- Postgres hides a cross-tenant audit row, so the
    endpoint's scalar_one_or_none is None and it 404s.
    """

    def __init__(self, row):
        self._row = row

    async def execute(self, *_args, **_kwargs):
        return _Result(self._row)


def _build_app(row):
    from fastapi import FastAPI

    from nestor_pulse_sdk.auth.deps import get_db_session
    from nestor_pulse_sdk.runs.api import router as runs_router

    app = FastAPI()
    app.include_router(runs_router)

    async def _fake_db_session():
        yield _Session(row)

    app.dependency_overrides[get_db_session] = _fake_db_session
    return app


# The dotted path the endpoint imports download_audit_body from (patched per case).
_DL = "nestor_pulse_sdk.audit.gcs_blob.download_audit_body"


# ===========================================================================
# Case (a): happy path -- redacted body, request+response present, NO hash key
# ===========================================================================

def test_happy_path_returns_redacted_body_without_hash():
    """Same-tenant drill-down returns the redacted request+response, no hash key."""
    from fastapi.testclient import TestClient

    run_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    row = _FakeAuditRow(
        gcs_uri=f"gs://nestor-audit-prod/runs/{run_id}/{audit_id}_anthropic_claude.json",
        provider="anthropic",
        model="claude-sonnet-4",
    )

    # The stored body is ALREADY redacted at upload (x-api-key -> [REDACTED]).
    stored_body = {
        "run_id": str(run_id),
        "audit_id": str(audit_id),
        "seq": 3,
        "provider": "anthropic",
        "model": "claude-sonnet-4",
        "request": {
            "headers": {"x-api-key": "[REDACTED]"},
            "messages": [{"role": "user", "content": "verify claim X"}],
        },
        "response": {"content": [{"type": "text", "text": "verdict: refute"}]},
    }

    app = _build_app(row)
    try:
        with patch(_DL, new=AsyncMock(return_value=stored_body)):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run_id}/audit/{audit_id}")

        assert resp.status_code == 200, (
            f"same-tenant drill-down should be 200, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        payload = resp.json()
        assert payload["audit_id"] == str(audit_id)
        assert payload["provider"] == "anthropic"
        assert payload["model"] == "claude-sonnet-4"
        # request + response ride through.
        assert payload["request"]["messages"][0]["content"] == "verify claim X"
        assert payload["response"]["content"][0]["text"] == "verdict: refute"
        # Redaction preserved (never re-exposed).
        assert payload["request"]["headers"]["x-api-key"] == "[REDACTED]"
        # hash / prev_hash NEVER present (T-15-08c; mirrors _audit_row_dto omission).
        assert "hash" not in payload
        assert "prev_hash" not in payload
        assert "hash" not in resp.text and "prev_hash" not in resp.text
    finally:
        app.dependency_overrides.clear()


def test_missing_gcs_body_is_404():
    """A resolvable row but a missing/unreadable GCS body (None) -> 404."""
    from fastapi.testclient import TestClient

    run_id = uuid.uuid4()
    audit_id = uuid.uuid4()
    row = _FakeAuditRow(gcs_uri="error://never-uploaded", provider="google", model="gemini")

    app = _build_app(row)
    try:
        with patch(_DL, new=AsyncMock(return_value=None)):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run_id}/audit/{audit_id}")
        assert resp.status_code == 404, (
            f"a None GCS body must 404, got {resp.status_code} (body={resp.text!r})."
        )
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# Case (b): RLS denial -- foreign audit_id -> EXACTLY 404, id not leaked
# ===========================================================================

def test_cross_tenant_audit_id_returns_exactly_404_no_id_leak():
    """A foreign-tenant audit_id reads as absent (RLS) -> EXACTLY 404, no id leak.

    The audit_log SELECT (filtered by id + run_id under the caller's tenant
    context) returns None for a cross-tenant row, so the endpoint 404s BEFORE any
    GCS read. download_audit_body is patched to blow up if reached, proving the
    denial fires at the RLS layer, not the storage layer. The foreign audit_id
    string must not appear in the body (T-15-08b).
    """
    from fastapi.testclient import TestClient

    run_id = uuid.uuid4()
    foreign_audit_id = uuid.uuid4()

    app = _build_app(row=None)  # SELECT yields None == RLS miss
    try:
        must_not_run = AsyncMock(side_effect=AssertionError("GCS must not be read on RLS miss"))
        with patch(_DL, new=must_not_run):
            client = TestClient(app)
            resp = client.get(f"/api/runs/{run_id}/audit/{foreign_audit_id}")

        assert resp.status_code == 404, (
            f"cross-tenant audit_id must be EXACTLY 404 (RLS-miss == absent, "
            f"T-15-08b), got {resp.status_code} (body={resp.text!r})."
        )
        assert str(foreign_audit_id) not in resp.text, (
            "404 body leaked the foreign audit_id -- must not echo it back."
        )
        must_not_run.assert_not_awaited()
    finally:
        app.dependency_overrides.clear()
