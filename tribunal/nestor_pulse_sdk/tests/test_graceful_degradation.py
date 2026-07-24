"""PHASE1-07 -- graceful degradation when a deep-research provider fails.

Owning plan: 01-09.

Per 01-VALIDATION.md row:
  "Simulated Gemini outage; brief completes with Claude + OpenAI only;
   audit log records the failure"

Tests (Plan 09 Task 1):
  1. test_two_of_three_succeed_brief_completes  -- Gemini times out, brief completes.
  2. test_one_of_three_fails_insufficient_raises -- only Claude succeeds, raises.
  3. test_failure_audit_log_recorded           -- write_failure is called on Gemini error.
  4. test_adapter_preserves_envelope           -- legacy {status, report} envelope passes through.
  5. test_legacy_tools_not_modified            -- SHA-256 snapshot of nestor_pulse/tools/* (Pitfall 8).
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from pathlib import Path
from typing import Callable

import pytest

from nestor_pulse_sdk.pipeline.deep_researchers import degraded_parallel
from nestor_pulse_sdk.pipeline.deep_researchers.degraded_parallel import (
    InsufficientProvidersError,
    MIN_SUCCESSES,
    PROVIDER_TIMEOUT_S,
    run_all_with_degradation,
)
from nestor_pulse_sdk.tools import gemini_adapter, claude_adapter, openai_adapter


# ---------------------------------------------------------------------------
# Fake AuditedLLMClient -- records calls without touching DB/GCS.
#
# gemini_deep_research_raw / openai_deep_research_raw are now methods on
# AuditedLLMClient (Plan 16 upgrade).  FakeAudited exposes stub versions that
# tests can override via set_gemini_raw() / set_openai_raw().
# ---------------------------------------------------------------------------


class _FakeHandle:
    def __init__(self, run_id, tenant_id, provider, model):
        self.audit_id = uuid.uuid4()
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model


class FakeAudited:
    """Mimics the subset of AuditedLLMClient the adapters touch."""

    def __init__(self):
        self.start_calls: list[dict] = []
        self.end_calls: list[dict] = []
        self.failures: list[dict] = []
        # Default raw implementations -- tests override these via set_*_raw().
        self._gemini_raw: Callable | None = None
        self._openai_raw: Callable | None = None

    def set_gemini_raw(self, fn: Callable) -> None:
        """Replace the gemini_deep_research_raw implementation for this test."""
        self._gemini_raw = fn

    def set_openai_raw(self, fn: Callable) -> None:
        """Replace the openai_deep_research_raw implementation for this test."""
        self._openai_raw = fn

    async def gemini_deep_research_raw(self, query: str, **kwargs) -> dict:
        if self._gemini_raw is not None:
            return await self._gemini_raw(query)
        return {"status": "success", "report": "gemini default"}

    async def openai_deep_research_raw(self, query: str, **kwargs) -> dict:
        if self._openai_raw is not None:
            return await self._openai_raw(query)
        return {"status": "success", "report": "openai default"}

    async def start_call(self, *, run_id, tenant_id, provider, model, request):
        self.start_calls.append({
            "run_id": run_id, "tenant_id": tenant_id,
            "provider": provider, "model": model, "request": request,
        })
        return _FakeHandle(run_id, tenant_id, provider, model)

    async def end_call(self, handle, *, response, status):
        self.end_calls.append({
            "handle": handle, "response": response, "status": status,
            "provider": handle.provider,
        })

    async def write_failure(self, *, run_id, tenant_id, provider, error):
        self.failures.append({
            "run_id": run_id, "tenant_id": tenant_id,
            "provider": provider, "error": error,
        })


@pytest.fixture
def audited() -> FakeAudited:
    return FakeAudited()


@pytest.fixture
def ids() -> tuple[uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4()


@pytest.fixture(autouse=True)
def enable_all_providers(monkeypatch):
    monkeypatch.setattr(degraded_parallel, "ALLOW_DEEP_RESEARCH_GEMINI", True)
    monkeypatch.setattr(degraded_parallel, "ALLOW_DEEP_RESEARCH_CLAUDE", True)
    monkeypatch.setattr(degraded_parallel, "ALLOW_DEEP_RESEARCH_OPENAI", True)


# ---------------------------------------------------------------------------
# Test 1: Gemini timeout, Claude + OpenAI succeed -> brief completes.
# ---------------------------------------------------------------------------


async def test_two_of_three_succeed_brief_completes(monkeypatch, audited, ids):
    run_id, tenant_id = ids
    success = {"status": "success", "report": "ok"}

    async def gemini_timeout(query):
        raise asyncio.TimeoutError("simulated gemini outage")

    async def claude_ok(query):
        return success

    # Gemini raises from gemini_deep_research_raw; claude uses legacy path (patched below).
    audited.set_gemini_raw(gemini_timeout)
    audited.set_openai_raw(lambda q: _async_return(success))
    monkeypatch.setattr(claude_adapter, "legacy_claude_deep_research", claude_ok)

    results = await run_all_with_degradation(
        query="q", audited=audited, run_id=run_id, tenant_id=tenant_id,
    )

    names = sorted(name for name, _ in results)
    assert names == ["claude", "openai"]
    assert len(results) >= MIN_SUCCESSES


async def _async_return(val):
    return val


# ---------------------------------------------------------------------------
# Test 2: Only 1 provider succeeds -> InsufficientProvidersError.
# ---------------------------------------------------------------------------


async def test_one_of_three_fails_insufficient_raises(monkeypatch, audited, ids):
    run_id, tenant_id = ids
    error_envelope = {"status": "error", "error_message": "boom"}

    async def claude_ok(query):
        return {"status": "success", "report": "ok"}

    audited.set_gemini_raw(lambda q: _async_return(error_envelope))
    audited.set_openai_raw(lambda q: _async_return(error_envelope))
    monkeypatch.setattr(claude_adapter, "legacy_claude_deep_research", claude_ok)

    with pytest.raises(InsufficientProvidersError) as exc_info:
        await run_all_with_degradation(
            query="q", audited=audited, run_id=run_id, tenant_id=tenant_id,
        )

    assert "gemini" in exc_info.value.failed
    assert "openai" in exc_info.value.failed
    assert "claude" not in exc_info.value.failed


# ---------------------------------------------------------------------------
# Test 3: Gemini failure -> AuditedLLMClient.write_failure called.
# ---------------------------------------------------------------------------


async def test_failure_audit_log_recorded(monkeypatch, audited, ids):
    run_id, tenant_id = ids
    boom = RuntimeError("simulated gemini outage")

    async def gemini_raises(query):
        raise boom

    async def claude_ok(query):
        return {"status": "success", "report": "ok"}

    async def openai_ok(query):
        return {"status": "success", "report": "ok"}

    audited.set_gemini_raw(gemini_raises)
    audited.set_openai_raw(openai_ok)
    monkeypatch.setattr(claude_adapter, "legacy_claude_deep_research", claude_ok)

    await run_all_with_degradation(
        query="q", audited=audited, run_id=run_id, tenant_id=tenant_id,
    )

    gemini_failures = [f for f in audited.failures if f["provider"] == gemini_adapter.PROVIDER]
    assert len(gemini_failures) == 1
    assert gemini_failures[0]["error"] is boom
    assert gemini_failures[0]["run_id"] == run_id
    assert gemini_failures[0]["tenant_id"] == tenant_id


# ---------------------------------------------------------------------------
# Test 4: Adapter passes {status, report} envelope through unchanged
#         + invokes start_call/end_call exactly once for a success.
# ---------------------------------------------------------------------------


async def test_adapter_preserves_envelope(audited, ids):
    run_id, tenant_id = ids
    envelope = {"status": "success", "report": "the report text"}

    audited.set_gemini_raw(lambda q: _async_return(envelope))

    result = await gemini_adapter.deep_research_audited(
        query="q", audited=audited, run_id=run_id, tenant_id=tenant_id,
    )

    assert result == envelope
    assert len(audited.start_calls) == 1
    assert audited.start_calls[0]["provider"] == gemini_adapter.PROVIDER
    assert audited.start_calls[0]["model"] == gemini_adapter.MODEL
    assert len(audited.end_calls) == 1
    assert audited.end_calls[0]["status"] == "success"
    assert audited.end_calls[0]["response"] is envelope
    assert audited.failures == []


# ---------------------------------------------------------------------------
# Test 5: Legacy nestor_pulse/tools/*.py files unchanged (Pitfall 8 / D-01).
# ---------------------------------------------------------------------------


def test_legacy_tools_not_modified():
    """Compare SHA-256 of each legacy deep-researcher against the snapshot.

    If a legacy file is intentionally updated, regenerate the snapshot in
    the same commit so the diff is visible during PR review.
    """
    repo_root = Path(__file__).resolve().parents[2]
    snapshot_path = (
        repo_root
        / "nestor_pulse_sdk"
        / "tests"
        / "fixtures"
        / "legacy_tools_snapshot.json"
    )
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))["files"]

    # The Phase-13 re-home carried only the legacy tools the engine imports
    # (claude_deep_researcher); the gemini/openai researchers were never
    # brought into this repo. Guard the carried files; report never-carried
    # entries as an explicit skip rather than a phantom D-01 violation.
    mismatches: list[str] = []
    not_carried: list[str] = []
    for rel_path, expected in snapshot.items():
        target = repo_root / rel_path
        if not target.is_file():
            not_carried.append(rel_path)
            continue
        # Normalize CRLF -> LF before hashing: the snapshot hashes LF bytes,
        # but Windows checkouts (and Cloud Build archives made from them)
        # carry CRLF, which is not a content change.
        content = target.read_bytes().replace(b"\r\n", b"\n")
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            mismatches.append(
                f"{rel_path}: expected {expected[:12]}..., got {actual[:12]}..."
            )

    assert not mismatches, (
        "Legacy nestor_pulse/tools/*.py modified (D-01 violation). "
        "If intentional, regenerate "
        "nestor_pulse_sdk/tests/fixtures/legacy_tools_snapshot.json "
        "in the same commit. Mismatches:\n" + "\n".join(mismatches)
    )
    if not_carried:
        pytest.skip(
            "never-carried legacy tools (Phase-13 re-home, expected): "
            + ", ".join(not_carried)
        )
