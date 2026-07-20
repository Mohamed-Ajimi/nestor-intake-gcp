"""Unit tests for the SDK deep-research raw methods on AuditedLLMClient.

Owning plan: 01-16.

Tests:
  1. gemini_deep_research_raw: completed -> success envelope with report text.
  2. gemini_deep_research_raw: failed -> error envelope.
  3. gemini_deep_research_raw: timeout (max_attempts=1) -> timeout envelope.
  4. gemini_deep_research_raw: missing API key -> error envelope (no network).

  Gemini deep research now uses the REST /interactions endpoint (May-2026 'steps'
  schema, Api-Revision header) because google-adk pins google-genai<2; the tests
  mock httpx, not the SDK.
  5. openai_deep_research_raw: completed -> success envelope.
  6. openai_deep_research_raw: retry on transient connection error, then success.
  7. openai_deep_research_raw: clean "failed" status NOT retried.
  8. openai_deep_research_raw: all retries exhausted -> error envelope.

All tests mock provider clients where they are constructed (in audited_llm_client).
No network or API calls happen.
"""
from __future__ import annotations

import asyncio
import os
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Build a minimal AuditedLLMClient instance for testing.
# We only need the two new methods; the other constructor args are not used.
# ---------------------------------------------------------------------------

from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient


def _make_client() -> AuditedLLMClient:
    """Return an AuditedLLMClient with stub collaborators (not used by raw methods)."""
    return AuditedLLMClient(
        anthropic_client=None,
        gemini_client=None,  # raw methods construct their own client
        audit_writer=None,
        hash_chain_mod=None,
        cost_table_mod=None,
        gcs_blob_mod=None,
    )


# ---------------------------------------------------------------------------
# Helpers for building fake provider responses.
# ---------------------------------------------------------------------------


def _gemini_interaction(status: str, text: str = "", error: str = "") -> dict:
    """Build a NEW-schema (May-2026 'steps') interaction JSON body.

    The deep-research call now hits the REST /interactions endpoint, so the
    fakes return plain dicts (what httpx .json() yields) rather than SDK objects.
    """
    body: dict = {"id": "iact-1", "status": status}
    if text:
        body["steps"] = [
            {
                "type": "model_output",
                "content": [{"type": "text", "text": text, "annotations": []}],
            }
        ]
    if error:
        body["error"] = error
    return body


class _FakeResp:
    """Minimal stand-in for an httpx.Response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # never errors in these tests
        return None

    def json(self) -> dict:
        return self._payload


class _FakeHTTPX:
    """Async-context-manager fake for httpx.AsyncClient.

    `post` always returns `created`; `get` returns each item of `get_returns` in
    turn (last value repeats), so a test can model in_progress→completed.
    """

    def __init__(self, created: dict, get_returns: list[dict]) -> None:
        self._created = created
        self._get_returns = get_returns
        self._get_idx = 0
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []

    def __call__(self, *args, **kwargs):  # httpx.AsyncClient(timeout=...) -> self
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers=None, json=None):
        self.post_calls.append({"url": url, "headers": headers or {}, "json": json})
        return _FakeResp(self._created)

    async def get(self, url, *, headers=None):
        self.get_calls.append(url)
        i = min(self._get_idx, len(self._get_returns) - 1)
        self._get_idx += 1
        return _FakeResp(self._get_returns[i])


def _openai_response(status: str, output_text: str = "", error=None) -> SimpleNamespace:
    return SimpleNamespace(id="resp-1", status=status, output_text=output_text, error=error)


# ---------------------------------------------------------------------------
# 1. Gemini: completed -> success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_completed_returns_success(monkeypatch):
    client_obj = _make_client()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake = _FakeHTTPX(
        created=_gemini_interaction("in_progress"),
        get_returns=[
            _gemini_interaction("in_progress"),
            _gemini_interaction("completed", text="Research summary here."),
        ],
    )

    with patch("httpx.AsyncClient", fake), \
         patch("nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client_obj.gemini_deep_research_raw(
            "test query", max_attempts=3, poll_interval=0
        )

    assert result["status"] == "success"
    assert result["report"] == "Research summary here."
    # The Api-Revision header MUST be sent or the server rejects the legacy schema.
    assert fake.post_calls[0]["headers"].get("Api-Revision") == "2026-05-20"
    assert fake.post_calls[0]["url"].endswith("/interactions")


# ---------------------------------------------------------------------------
# 2. Gemini: failed -> error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_failed_returns_error(monkeypatch):
    client_obj = _make_client()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake = _FakeHTTPX(
        created=_gemini_interaction("in_progress"),
        get_returns=[_gemini_interaction("failed", error="Model overloaded")],
    )

    with patch("httpx.AsyncClient", fake), \
         patch("nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client_obj.gemini_deep_research_raw(
            "test query", max_attempts=2, poll_interval=0
        )

    assert result["status"] == "error"
    assert "failed" in result["error_message"].lower() or "Model overloaded" in result["error_message"]


# ---------------------------------------------------------------------------
# 3. Gemini: timeout (max_attempts=1, still in_progress) -> timeout envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_timeout_returns_timeout_envelope(monkeypatch):
    client_obj = _make_client()
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")

    fake = _FakeHTTPX(
        created=_gemini_interaction("in_progress"),
        get_returns=[_gemini_interaction("in_progress")],  # never completes
    )

    with patch("httpx.AsyncClient", fake), \
         patch("nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep", new_callable=AsyncMock):
        result = await client_obj.gemini_deep_research_raw(
            "test query", max_attempts=1, poll_interval=0
        )

    assert result["status"] == "timeout"
    assert "timed out" in result["error_message"].lower()


# ---------------------------------------------------------------------------
# 4. Gemini: missing API key -> clean error envelope (no network call).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_missing_api_key_returns_error(monkeypatch):
    client_obj = _make_client()
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = await client_obj.gemini_deep_research_raw(
        "test query", max_attempts=1, poll_interval=0
    )

    assert result["status"] == "error"
    assert "api_key" in result["error_message"].lower() or "API_KEY" in result["error_message"]


# ---------------------------------------------------------------------------
# 5. OpenAI: completed -> success
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_completed_returns_success(monkeypatch):
    client_obj = _make_client()

    queued = _openai_response("queued")
    completed = _openai_response("completed", output_text="OpenAI report text.")

    fake_client = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=queued)
    fake_client.responses.retrieve = AsyncMock(return_value=completed)

    async def fake_sleep(_):
        pass

    with patch("openai.AsyncOpenAI", return_value=fake_client), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        monkeypatch.setattr(
            "nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep",
            fake_sleep,
        )
        result = await client_obj.openai_deep_research_raw(
            "test query", max_attempts=2, poll_interval=0
        )

    assert result["status"] == "success"
    assert result["report"] == "OpenAI report text."


# ---------------------------------------------------------------------------
# 6. OpenAI: retry on transient connection error, second attempt succeeds.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_retries_transient_connection_error(monkeypatch):
    """First responses.create raises a transient error; second call succeeds."""
    client_obj = _make_client()

    queued = _openai_response("queued")
    completed = _openai_response("completed", output_text="Retried report.")

    call_count = 0

    async def create_with_transient_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("Transient network blip")
        return queued

    fake_client = MagicMock()
    fake_client.responses.create = create_with_transient_error
    fake_client.responses.retrieve = AsyncMock(return_value=completed)

    async def fake_sleep(_):
        pass

    with patch("openai.AsyncOpenAI", return_value=fake_client), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        monkeypatch.setattr(
            "nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep",
            fake_sleep,
        )
        result = await client_obj.openai_deep_research_raw(
            "test query",
            max_attempts=2,
            poll_interval=0,
            max_connect_retries=3,
        )

    assert result["status"] == "success"
    assert result["report"] == "Retried report."
    assert call_count == 2, "Should have been called exactly twice (1 fail + 1 success)"


# ---------------------------------------------------------------------------
# 7. OpenAI: clean "failed" status is NOT retried.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_failed_status_not_retried(monkeypatch):
    """A 'failed' response status returns immediately without retry."""
    client_obj = _make_client()

    queued = _openai_response("queued")
    failed = _openai_response("failed", error="Content policy violation")

    fake_client = MagicMock()
    fake_client.responses.create = AsyncMock(return_value=queued)
    retrieve_calls = 0

    async def retrieve_returns_failed(response_id):
        nonlocal retrieve_calls
        retrieve_calls += 1
        return failed

    fake_client.responses.retrieve = retrieve_returns_failed

    async def fake_sleep(_):
        pass

    with patch("openai.AsyncOpenAI", return_value=fake_client), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        monkeypatch.setattr(
            "nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep",
            fake_sleep,
        )
        result = await client_obj.openai_deep_research_raw(
            "test query",
            max_attempts=5,
            poll_interval=0,
        )

    # Should return after first failed status, not poll all max_attempts times.
    assert result["status"] == "error"
    assert "failed" in result["error_message"].lower()
    assert retrieve_calls == 1, "Failed status should stop polling immediately"


# ---------------------------------------------------------------------------
# 8. OpenAI: all retries exhausted -> error envelope.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_all_retries_exhausted_returns_error(monkeypatch):
    """All max_connect_retries attempts fail with transient error -> error envelope."""
    client_obj = _make_client()

    async def always_fails(*args, **kwargs):
        raise ConnectionError("Persistent network failure")

    fake_client = MagicMock()
    fake_client.responses.create = always_fails

    async def fake_sleep(_):
        pass

    with patch("openai.AsyncOpenAI", return_value=fake_client), \
         patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
        monkeypatch.setattr(
            "nestor_pulse_sdk.audit.audited_llm_client.asyncio.sleep",
            fake_sleep,
        )
        result = await client_obj.openai_deep_research_raw(
            "test query",
            max_attempts=2,
            poll_interval=0,
            max_connect_retries=3,
        )

    assert result["status"] == "error"
    assert "error_message" in result
