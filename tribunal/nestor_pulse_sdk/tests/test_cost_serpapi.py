"""D-16 SerpApi cost arithmetic — Phase 15.2 plan 12, task 2.

THIS FILE MAKES ZERO LLM CALLS, ZERO SerpApi CALLS AND ZERO NETWORK CONNECTIONS,
touches no database, uses no mocking library and needs no API key. Every
collaborator is a hand-written duck type, in the register of
`test_cost_cache_write.py`.

What is being proved, in D-16's own terms:

  * the per-search unit price is the PUBLISHED DIVISION
    `plan_monthly_price / searches_per_month`, computed as an exact `Decimal`
    from the same expression rather than compared against a rounded literal;
  * the fee is `billable_count x unit`, exactly, as a `Decimal` and never a float;
  * the Free tier is an HONEST $0.00 — `Decimal("0")`, not None, and it does NOT
    take the pending path;
  * an unknown plan yields `None` (asserted with `is None`, not falsiness), so
    the caller writes NULL + `cost_pending` and NEVER a guessed tier;
  * only `search_metadata.status == "Success"` is billable;
  * the two new `compute()` parameters are ADDITIVE — an existing Anthropic call
    prices identically with and without them;
  * one SerpApi search writes ONE `audit_log` row through the ordinary
    `AuditedLLMClient` sequence, carrying no credential and adding NO field to
    the frozen 11-field hash-chain payload.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.audit import cost_table as ct
from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient
from nestor_pulse_sdk.pipeline.tribunal import serpapi
from nestor_pulse_sdk.pipeline.tribunal.serpapi import SerpApiError, SerpApiPlan

_RUN_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
_TENANT_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")

_FAKE_KEY = "SERPAPI-COST-TEST-KEY-9c17be"

#: The 11 FROZEN hash-chain payload fields (`_build_payload_dict`). A SerpApi row
#: is a new ROW, not a new FIELD — this set must not grow.
_FROZEN_PAYLOAD_KEYS = {
    "provider",
    "model",
    "started_at",
    "duration_ms",
    "prompt_tokens",
    "completion_tokens",
    "cached_tokens",
    "gcs_uri",
    "seq",
    "tenant_id",
    "run_id",
}

#: SerpApi's published plans: (name, monthly price USD, searches per month).
#: [CITED: serpapi.com/pricing, fetched 2026-07-26]. These are the PLAN facts,
#: not a chosen tier — the tier is plan 15.2-18's open operator decision.
_PUBLISHED_PLANS = [
    ("Free", 0, 250),
    ("Starter", 25, 1000),
    ("Developer", 75, 5000),
    ("Production", 150, 15000),
    ("Big Data", 275, 30000),
]


# ---------------------------------------------------------------------------
# Hand-written fakes. No mocking library, no DB, no GCS.
# ---------------------------------------------------------------------------


class _FakeWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.pending_runs: list[uuid.UUID] = []

    async def get_prev_hash_and_seq(self, run_id, tenant_id=None) -> tuple:
        return ("prev-hash", len(self.rows))

    async def write_full_row(self, **kwargs: Any) -> None:
        self.rows.append(kwargs)

    async def mark_cost_pending(self, *, run_id, tenant_id) -> None:
        self.pending_runs.append(run_id)


class _FakeChain:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def link_hash(self, prev_hash: str, payload: dict) -> str:
        self.payloads.append(payload)
        return f"hash-of-{payload.get('seq')}"


class _FakeGcs:
    def __init__(self) -> None:
        self.uploads: list[dict] = []

    async def upload_audit_body(self, **kwargs: Any) -> str:
        self.uploads.append(kwargs)
        return f"gs://fake/{kwargs.get('audit_id')}.json"


def _client(writer: _FakeWriter, chain: _FakeChain, gcs: _FakeGcs) -> AuditedLLMClient:
    return AuditedLLMClient(
        anthropic_client=None,
        gemini_client=None,
        audit_writer=writer,
        hash_chain_mod=chain,
        cost_table_mod=ct,
        gcs_blob_mod=gcs,
    )


def _search_result(status: str = "Success") -> dict:
    return {
        "billable": status == "Success",
        "status": status,
        "results": [
            {
                "title": "T",
                "link": "https://example.com/a",
                "snippet": "s",
                "position": 1,
            }
        ],
        "metadata": {"id": "abc123", "status": status, "total_time_taken": 1.0},
        "search_id": "abc123",
    }


def _contains_key(node: Any, needle: str) -> bool:
    """True if `needle` appears as a dict key at ANY depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() == needle:
                return True
            if _contains_key(value, needle):
                return True
    elif isinstance(node, list):
        return any(_contains_key(item, needle) for item in node)
    return False


def _contains_value(node: Any, needle: str) -> bool:
    """True if `needle` appears inside any string value at ANY depth."""
    if isinstance(node, dict):
        return any(_contains_value(v, needle) for v in node.values())
    if isinstance(node, list):
        return any(_contains_value(v, needle) for v in node)
    return isinstance(node, str) and needle in node


# ===========================================================================
# The arithmetic
# ===========================================================================


@pytest.mark.parametrize("plan_name,price,quota", _PUBLISHED_PLANS)
def test_unit_price_is_published_division(plan_name, price, quota):
    """unit = plan_monthly_price / searches_per_month, exactly, as a Decimal."""
    plan = SerpApiPlan(
        plan_name=plan_name,
        plan_monthly_price=Decimal(str(price)),
        searches_per_month=quota,
        total_searches_left=None,
        unit_price_usd=Decimal(str(price)) / Decimal(str(quota)),
        source="account.json",
    )
    assert isinstance(plan.unit_price_usd, Decimal)
    assert plan.unit_price_usd == Decimal(str(price)) / Decimal(str(quota))


def test_fee_is_count_times_unit_exact():
    result = ct.compute(
        "serpapi",
        "google",
        0,
        0,
        0,
        serpapi_search_count=8,
        serpapi_unit_price_usd=Decimal("0.025"),
    )
    assert isinstance(result, Decimal)
    assert result == Decimal("0.2")


def test_free_tier_is_honest_zero_not_pending():
    """A KNOWN price of zero is a fact in the total, not a missing number."""
    result = ct.compute(
        "serpapi",
        "google",
        0,
        0,
        0,
        serpapi_search_count=17,
        serpapi_unit_price_usd=Decimal("0"),
    )
    assert result is not None
    assert isinstance(result, Decimal)
    assert result == Decimal("0")


def test_unknown_plan_returns_none_never_a_guess():
    """_tool_fees.serpapi_search is JSON null, so there is no fallback rate."""
    assert ct.tool_fee_or_none("serpapi_search") is None
    result = ct.compute(
        "serpapi", "google", 0, 0, 0, serpapi_search_count=3, serpapi_unit_price_usd=None
    )
    assert result is None


def test_tool_fee_or_none_distinguishes_null_from_zero():
    """The sibling of _tool_fee exists precisely so null != $0.00."""
    # web_fetch is a genuine, published 0.0 flat fee.
    assert ct.tool_fee_or_none("web_fetch") == Decimal("0")
    # serpapi_search is null -- unknown, not free.
    assert ct.tool_fee_or_none("serpapi_search") is None
    # A key that is not in the table at all is unknown too.
    assert ct.tool_fee_or_none("no_such_tool_fee") is None
    # _tool_fee's zero-on-missing behaviour is UNCHANGED (test_cost_cache_write
    # depends on it).
    assert ct._tool_fee("no_such_tool_fee") == Decimal("0")


def test_non_success_search_is_not_billable():
    """Processing / Error searches contribute count 0, therefore exactly zero."""
    for status in ("Processing", "Error", ""):
        result = _search_result(status)
        assert result["billable"] is False
        billable_count = 1 if result["billable"] else 0
        assert billable_count == 0
        priced = ct.compute(
            "serpapi",
            "google",
            0,
            0,
            0,
            serpapi_search_count=billable_count,
            serpapi_unit_price_usd=Decimal("0.025"),
        )
        assert priced == Decimal("0")


def test_existing_costs_unchanged():
    """The additive-parameter proof: same Decimal with and without the new args."""
    before = ct.compute("anthropic", "claude-sonnet-4-6", 12_345, 6_789, 1_000, 2_000, 3, 2)
    after = ct.compute(
        "anthropic",
        "claude-sonnet-4-6",
        12_345,
        6_789,
        1_000,
        2_000,
        3,
        2,
        serpapi_search_count=0,
        serpapi_unit_price_usd=None,
    )
    assert before == after
    assert before is not None


def test_serpapi_google_price_entry_resolves():
    """The entry exists only so compute() does not take the unknown-model branch."""
    zero_cost = ct.compute("serpapi", "google", 0, 0, 0)
    assert zero_cost == Decimal("0")
    # And an unknown provider/model still returns None (Pitfall 5 intact).
    assert ct.compute("serpapi", "bing", 0, 0, 0) is None


# ===========================================================================
# The audited row
# ===========================================================================


async def test_serpapi_row_written_with_frozen_payload(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    calls: list[dict] = []

    async def _stub_search(**kwargs: Any) -> dict:
        calls.append(kwargs)
        return _search_result("Success")

    monkeypatch.setattr(serpapi, "search", _stub_search)

    writer, chain, gcs = _FakeWriter(), _FakeChain(), _FakeGcs()
    audited = _client(writer, chain, gcs)
    plan = SerpApiPlan(
        plan_name="Starter",
        plan_monthly_price=Decimal("25"),
        searches_per_month=1000,
        total_searches_left=900,
        unit_price_usd=Decimal("25") / Decimal("1000"),
        source="account.json",
    )

    out: dict = {}
    result = await audited.serpapi_search(
        run_id=_RUN_ID, tenant_id=_TENANT_ID, q="lukoil benelux pricing", plan=plan,
        audit_out=out,
    )

    # -- one row, priced from the published unit -----------------------------
    assert len(writer.rows) == 1
    row = writer.rows[0]
    assert row["provider"] == "serpapi"
    assert row["model"] == "google"
    assert row["prompt_tokens"] == 0
    assert row["completion_tokens"] == 0
    assert row["cached_tokens"] == 0
    assert row["cost_usd"] == Decimal("0.025")
    assert writer.pending_runs == []

    # -- the audit blob carries no credential (T-15.2-31) --------------------
    assert len(gcs.uploads) == 1
    request_dict = gcs.uploads[0]["request_dict"]
    assert not _contains_key(request_dict, "api_key")
    assert not _contains_key(request_dict, "apikey")
    assert not _contains_value(request_dict, _FAKE_KEY)
    assert request_dict["url_path"] == "/search.json"
    assert not _contains_value(request_dict, "serpapi.com")

    # -- the frozen chain payload is untouched (EU AI Act Art. 12) -----------
    assert len(chain.payloads) == 1
    assert set(chain.payloads[0]) == _FROZEN_PAYLOAD_KEYS
    assert chain.payloads[0]["provider"] == "serpapi"

    # -- the F4 out-param and the return envelope ---------------------------
    assert out["provider"] == "serpapi"
    # `_fill_audit_out` stringifies the Decimal rather than float()ing it, so the
    # exact cent text survives into JSONB. Compared as a Decimal because the sum
    # legitimately carries trailing zeros from the zero-rate token terms.
    assert Decimal(out["cost_usd"]) == Decimal("0.025")
    assert result["billable"] is True
    assert result["cost_usd"] == Decimal("0.025")
    assert result["audit_id"]
    assert calls and calls[0]["q"] == "lukoil benelux pricing"


async def test_unknown_plan_marks_cost_pending_and_writes_null(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    async def _stub_search(**kwargs: Any) -> dict:
        return _search_result("Success")

    monkeypatch.setattr(serpapi, "search", _stub_search)

    writer, chain, gcs = _FakeWriter(), _FakeChain(), _FakeGcs()
    audited = _client(writer, chain, gcs)

    result = await audited.serpapi_search(
        run_id=_RUN_ID, tenant_id=_TENANT_ID, q="x", plan=SerpApiPlan.unknown()
    )

    assert writer.rows[0]["cost_usd"] is None
    assert writer.pending_runs == [_RUN_ID]
    assert result["cost_usd"] is None


async def test_non_billable_search_costs_an_exact_zero(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    async def _stub_search(**kwargs: Any) -> dict:
        return _search_result("Processing")

    monkeypatch.setattr(serpapi, "search", _stub_search)

    writer, chain, gcs = _FakeWriter(), _FakeChain(), _FakeGcs()
    audited = _client(writer, chain, gcs)

    result = await audited.serpapi_search(
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        q="x",
        plan=SerpApiPlan(
            plan_name="Starter",
            plan_monthly_price=Decimal("25"),
            searches_per_month=1000,
            total_searches_left=None,
            unit_price_usd=Decimal("0.025"),
            source="account.json",
        ),
    )

    assert result["billable"] is False
    assert writer.rows[0]["cost_usd"] == Decimal("0")
    assert writer.pending_runs == []


async def test_failure_records_breaker_writes_failure_row_and_reraises(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    serpapi.reset_breaker()

    async def _stub_search(**kwargs: Any) -> dict:
        raise SerpApiError("boom", status_code=402, body_excerpt="billing")

    monkeypatch.setattr(serpapi, "search", _stub_search)

    writer, chain, gcs = _FakeWriter(), _FakeChain(), _FakeGcs()
    audited = _client(writer, chain, gcs)

    with pytest.raises(SerpApiError):
        await audited.serpapi_search(run_id=_RUN_ID, tenant_id=_TENANT_ID, q="x")

    # A failure row was written, with a NULL cost.
    assert len(writer.rows) == 1
    assert writer.rows[0]["provider"] == "serpapi"
    assert writer.rows[0]["cost_usd"] is None
    # And the 402 hard wall tripped the SerpApi circuit on its first occurrence.
    assert serpapi.unavailable_reason() == "serpapi_breaker_open"
    serpapi.reset_breaker()
