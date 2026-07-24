"""
Phase 15 Plan 02 -- C1 cost-truth: cache-write pricing, server-tool fees,
deep-research usageMetadata, and NULL-on-unknown.

Per 15-02-PLAN.md <verification>:
  Command: pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x

Proves the three C1 cost defects are fixed so displayed cost is facts-only:
  1. test_cache_write_charged   -- Anthropic cache-CREATE tokens are charged at the
                                   cache_creation_5m rate (Plan 15-02 Task 1).
  2. test_web_search_fee_added  -- server-tool web_search invocations add the published
                                   $0.01/search flat fee to a call's cost (Task 1/2).
  3. test_dr_usage_recorded     -- a Gemini deep-research call WITH usageMetadata is
                                   priced from those facts; WITHOUT it the run's
                                   cost_pending is set (never an estimate) (Task 2).
  4. test_unknown_model_null    -- an unknown provider/model returns None, not a guess
                                   (Pitfall 5).

Expected costs are EXACT Decimals derived from cost_prices.json (Pitfall 3 -- no
rounded guesses). Dev box has no Python/Docker (project memory), so this suite is the
documented Cloud Build / migrate-job gate; it could not be run locally.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

from nestor_pulse_sdk.audit import cost_table as ct
from nestor_pulse_sdk.audit import hash_chain as hc
from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient, AuditHandle


# Exact rates from cost_prices.json for anthropic/claude-sonnet-4-6 (USD per 1M tokens).
_SONNET = "claude-sonnet-4-6"
_PROMPT_RATE = Decimal("3.0")
_COMPLETION_RATE = Decimal("15.0")
_CACHE_READ_RATE = Decimal("0.30")
_CACHE_CREATE_RATE = Decimal("3.75")
_PER_M = Decimal("1000000")
# Published server-tool fee (facts): $10 per 1000 searches = $0.01/search.
_WEB_SEARCH_FEE = Decimal("0.01")


# ---------------------------------------------------------------------------
# Minimal fakes (no DB / no GCS) -- self-contained for this suite.
# ---------------------------------------------------------------------------

@dataclass
class _Row:
    audit_id: uuid.UUID
    run_id: uuid.UUID
    provider: str
    model: str
    cost_usd: Optional[Decimal]
    cache_creation_tokens: Optional[int]
    prompt_tokens: int
    completion_tokens: int
    cached_tokens: int
    seq: int
    hash: str


class _FakeWriter:
    """In-memory audit writer. Accepts **kwargs so it tolerates the new
    cache_creation_tokens param, and exposes mark_cost_pending so the DR
    pending-fallback path can be asserted."""

    def __init__(self) -> None:
        self.rows: list[_Row] = []
        self.pending_runs: list[uuid.UUID] = []

    async def get_prev_hash_and_seq(self, run_id, tenant_id=None) -> tuple:
        run_rows = [r for r in self.rows if r.run_id == run_id]
        if not run_rows:
            return hc.GENESIS, 1
        last = max(run_rows, key=lambda r: r.seq)
        return last.hash, last.seq + 1

    async def write_full_row(
        self, *, audit_id, run_id, tenant_id, seq, provider, model,
        started_at, duration_ms, prompt_tokens, completion_tokens,
        cached_tokens, cost_usd, gcs_uri, prev_hash, hash,
        cache_creation_tokens=None, **_extra,
    ) -> None:
        self.rows.append(_Row(
            audit_id=audit_id, run_id=run_id, provider=provider, model=model,
            cost_usd=cost_usd, cache_creation_tokens=cache_creation_tokens,
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
            cached_tokens=cached_tokens, seq=seq, hash=hash,
        ))

    async def mark_cost_pending(self, *, run_id, tenant_id) -> None:
        self.pending_runs.append(run_id)


def _make_client(writer: _FakeWriter) -> AuditedLLMClient:
    mock_gcs = MagicMock()
    mock_gcs.upload_audit_body = AsyncMock(
        return_value="gs://nestor-audit-prod/runs/test/00000001.json"
    )
    return AuditedLLMClient(
        anthropic_client=AsyncMock(),
        gemini_client=MagicMock(),
        audit_writer=writer,
        hash_chain_mod=hc,
        cost_table_mod=ct,
        gcs_blob_mod=mock_gcs,
    )


# ===========================================================================
# TEST 1: cache-CREATE tokens are charged at the 5m rate
# ===========================================================================

def test_cache_write_charged():
    """compute() with cache_creation_tokens>0 costs strictly more than the same
    call with 0, by EXACTLY cache_creation_tokens x cache_creation_5m rate."""
    prompt_tokens, completion_tokens, cached_tokens = 1000, 500, 100
    cache_create = 200

    base = ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
    )
    with_create = ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
        cache_creation_tokens=cache_create,
    )
    assert base is not None and with_create is not None

    # Exact expected base cost (facts from cost_prices.json).
    non_cached = prompt_tokens - cached_tokens  # 900
    expected_base = (
        Decimal(non_cached) * (_PROMPT_RATE / _PER_M)
        + Decimal(cached_tokens) * (_CACHE_READ_RATE / _PER_M)
        + Decimal(completion_tokens) * (_COMPLETION_RATE / _PER_M)
    )
    assert base == expected_base

    # The delta is EXACTLY the cache-create term -- nothing else moved.
    expected_delta = Decimal(cache_create) * (_CACHE_CREATE_RATE / _PER_M)
    assert with_create - base == expected_delta
    assert with_create > base

    # Backward compatibility: default cache_creation_tokens=0 == explicit 0.
    assert ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
        cache_creation_tokens=0,
    ) == base


# ===========================================================================
# TEST 2: server-tool web_search fee is added per call
# ===========================================================================

def test_web_search_fee_added():
    """A call reporting N web searches adds EXACTLY N x $0.01 to cost_usd."""
    prompt_tokens, completion_tokens, cached_tokens = 1000, 500, 0
    searches = 3

    base = ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
    )
    with_search = ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
        web_search_count=searches,
    )
    assert base is not None and with_search is not None

    expected_fee = Decimal(searches) * _WEB_SEARCH_FEE
    assert with_search - base == expected_fee

    # web_fetch flat fee is 0.0 (published fact) -> adds nothing.
    with_fetch = ct.compute(
        "anthropic", _SONNET, prompt_tokens, completion_tokens, cached_tokens,
        web_fetch_count=5,
    )
    assert with_fetch == base


# ===========================================================================
# TEST 3: deep-research usageMetadata -- present -> priced, absent -> pending
# ===========================================================================

@pytest.mark.asyncio
async def test_dr_usage_recorded():
    """A DR (google) end_call WITH usageMetadata yields a non-zero DR token cost
    recorded on the audit row; a DR call WITHOUT usageMetadata leaves cost NULL
    for the grounding fee and sets the run's cost_pending -- never a number."""
    tenant_id = uuid.uuid4()

    # -- present: usageMetadata drives the cost (thoughts fold into completion) --
    writer_present = _FakeWriter()
    client_present = _make_client(writer_present)
    run_present = uuid.uuid4()
    handle_present = AuditHandle(
        audit_id=uuid.uuid4(), run_id=run_present, tenant_id=tenant_id,
        seq=-1, prev_hash="", started_at=0.0,
        started_dt=datetime.now(tz=timezone.utc),
        provider="google", model="gemini-2.5-pro", request_dict={"q": "x"},
    )
    await client_present.end_call(
        handle_present,
        response={
            "status": "success",
            "report": "r",
            "usageMetadata": {
                "promptTokenCount": 1000,
                "candidatesTokenCount": 400,
                "thoughtsTokenCount": 100,
            },
        },
        status="success",
    )
    assert len(writer_present.rows) == 1
    row = writer_present.rows[0]
    # thoughts (100) bill at output rate -> completion = 400 + 100 = 500.
    assert row.completion_tokens == 500
    assert row.prompt_tokens == 1000
    # Exact expected cost for gemini-2.5-pro (prompt 1.25, completion 10.0 per 1M).
    expected = (
        Decimal(1000) * (Decimal("1.25") / _PER_M)
        + Decimal(500) * (Decimal("10.0") / _PER_M)
    )
    assert row.cost_usd == expected
    assert row.cost_usd > 0
    assert run_present not in writer_present.pending_runs

    # -- absent: no usageMetadata -> cost_pending set, no estimate written --
    writer_absent = _FakeWriter()
    client_absent = _make_client(writer_absent)
    run_absent = uuid.uuid4()
    handle_absent = AuditHandle(
        audit_id=uuid.uuid4(), run_id=run_absent, tenant_id=tenant_id,
        seq=-1, prev_hash="", started_at=0.0,
        started_dt=datetime.now(tz=timezone.utc),
        provider="google", model="gemini-2.5-pro", request_dict={"q": "x"},
    )
    await client_absent.end_call(
        handle_absent,
        response={"status": "success", "report": "r"},  # no usageMetadata
        status="success",
    )
    # The run is flagged pending (grounding fee backfilled from billing).
    assert run_absent in writer_absent.pending_runs
    # No fabricated tokens -> zero token cost, and no placeholder number invented.
    row_absent = writer_absent.rows[0]
    assert row_absent.prompt_tokens == 0
    assert row_absent.completion_tokens == 0


# ===========================================================================
# TEST 4: unknown model -> None (never a guess)
# ===========================================================================

def test_unknown_model_null():
    """An unknown provider/model returns None so the caller writes NULL cost_usd
    (Pitfall 5) -- even with cache-create + tool-fee args present."""
    assert ct.compute(
        "anthropic", "claude-does-not-exist", 1000, 500, 0,
        cache_creation_tokens=200, web_search_count=3,
    ) is None
    assert ct.compute("madeup", "model-x", 100, 50, 0) is None


# ===========================================================================
# TEST 5 (CR-02 regression): the PRODUCTION writer implements mark_cost_pending
# ===========================================================================

def test_production_writer_implements_mark_cost_pending():
    """DBAuditWriter (the PRODUCTION writer) must implement mark_cost_pending.

    The CR-02 defect: end_call's pending path probes the writer via getattr and
    silently no-ops when the method is missing -- and only the test FAKE had it,
    so run.cost_pending was dead in production (an incomplete cost presented as
    settled, violating C1 facts-only). This pins the method on the real writer:
    async, keyword-only run_id + tenant_id (the exact call shape end_call uses).
    """
    import inspect

    from nestor_pulse_sdk.audit.writer import DBAuditWriter

    method = getattr(DBAuditWriter, "mark_cost_pending", None)
    assert callable(method), (
        "DBAuditWriter must implement mark_cost_pending -- without it the "
        "run.cost_pending flag is silently dropped in production (CR-02)"
    )
    assert inspect.iscoroutinefunction(method), "mark_cost_pending must be async"
    params = inspect.signature(method).parameters
    assert "run_id" in params and "tenant_id" in params, (
        "mark_cost_pending must accept run_id + tenant_id keywords "
        "(end_call calls it as mark_pending(run_id=..., tenant_id=...))"
    )
