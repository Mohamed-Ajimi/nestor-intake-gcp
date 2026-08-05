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
from nestor_pulse_sdk.audit import gcs_blob
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


# ===========================================================================
# gpt-5.6-sol cost row — the state pin AND its positive control (plan 15.8-08)
#
# THESE TWO TESTS ARE A PAIR AND BELONG ADJACENT. Read them together.
#
# `compute()` has TWO different failure-ish paths and they are NOT the same:
#
#   * key ABSENT from cost_prices.json -> the `key not in prices` branch ->
#     returns None -> the caller writes NULL cost_usd. This is the HONEST
#     "we do not know" state.
#   * key PRESENT with null rates -> `_rate()` maps every None to Decimal("0")
#     -> compute returns a CONFIDENT Decimal("0"). This is a FABRICATED price.
#
# The operator ruled `published-rates` on 2026-08-04, so the key is present
# with real numbers. The positive control below is what keeps that meaningful:
# without it, a future "the model is missing, just add the key" fix could land
# null rates and every assertion here would still pass while the audit record
# silently priced five deep-research calls at $0.00.
#
# NOTE ON ASSERTION STYLE: `Decimal("0")` is FALSY. Every assertion in this pair
# uses `is None` / `== Decimal(...)` and never truthiness — a truthiness check
# would pass on exactly the defect being guarded against.
# ===========================================================================

#: The operator-ruled published rates, USD per 1M tokens (2026-08-04).
#: THIRD-PARTY figures: openai.com/api/pricing returned HTTP 403, so these come
#: from four agreeing aggregators. See `_gpt_5_6_sol_source` in cost_prices.json
#: for the full provenance, the recorded source conflict on `prompt`, and the
#: 272K long-context meter that makes these rates a FLOOR above that boundary.
_GPT_5_6_SOL_RATES = {
    "prompt": Decimal("5.0"),
    "completion": Decimal("30.0"),
    "cache_read": Decimal("0.50"),
    "cache_creation_5m": Decimal("6.25"),
}


def test_gpt_5_6_sol_prices_at_the_published_rate_not_a_fabricated_zero():
    """STATE PIN: the ruled `published-rates` state, one field at a time.

    `gpt-5.6-sol` is the pinned OPENAI_DEEP_RESEARCH_MODEL default and is called
    on the deep-research path, so before the 2026-08-04 ruling these calls wrote
    NULL cost_usd and `SUM(cost_usd)` silently skipped them.

    Each rate is exercised in ISOLATION (1M tokens in exactly one bucket) so a
    transposed pair in cost_prices.json cannot hide inside a summed total.
    """
    # prompt: 1M uncached input tokens.
    assert ct.compute("openai", "gpt-5.6-sol", 1_000_000, 0, 0) == _GPT_5_6_SOL_RATES[
        "prompt"
    ]
    # completion: 1M output tokens.
    assert ct.compute("openai", "gpt-5.6-sol", 0, 1_000_000, 0) == _GPT_5_6_SOL_RATES[
        "completion"
    ]
    # cache_read: all 1M input tokens are cache hits, so none bill at `prompt`.
    assert ct.compute(
        "openai", "gpt-5.6-sol", 1_000_000, 0, 1_000_000
    ) == _GPT_5_6_SOL_RATES["cache_read"]
    # cache_creation_5m: the FIRST non-zero cache-write rate for any openai model
    # in this file. If this asserts 0, someone "normalised" it to match gpt-4o.
    assert ct.compute(
        "openai", "gpt-5.6-sol", 0, 0, 0, 1_000_000
    ) == _GPT_5_6_SOL_RATES["cache_creation_5m"]

    # The whole point: NOT the fabricated zero, and NOT the unknown-model branch.
    priced = ct.compute("openai", "gpt-5.6-sol", 1_000_000, 0, 0)
    assert priced is not None
    assert priced != Decimal("0")


def test_null_rate_entry_returns_confident_zero_not_none(monkeypatch, tmp_path):
    """POSITIVE CONTROL: this is what a null-rate entry actually does.

    This test does NOT test the shipped price file. It builds a throwaway one in
    which `openai/gpt-5.6-sol` is PRESENT with all four rates null, and proves
    `compute` returns a confident `Decimal("0")` rather than None.

    That is the trap the operator ruling exists to avoid: adding the key with
    nulls would price five deep-research calls at $0.00 and make the run total
    LOOK complete while still being a floor — strictly worse than the NULL rows
    it replaced, because NULLs are at least countable via
    `SELECT count(*) FROM audit_log WHERE run_id = :id AND cost_usd IS NULL`.

    A DISTINCT temp path per test sidesteps `_load_prices`' (path, mtime) cache
    entirely, which is more honest than trying to invalidate it.
    """
    import json as _json

    null_prices = tmp_path / "null_rate_prices.json"
    null_prices.write_text(
        _json.dumps(
            {
                "openai/gpt-5.6-sol": {
                    "prompt": None,
                    "completion": None,
                    "cache_read": None,
                    "cache_creation_5m": None,
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("COST_PRICES_PATH", str(null_prices))

    fabricated = ct.compute("openai", "gpt-5.6-sol", 1_000_000, 0, 0)

    # The defect, stated as an assertion: a null-rate entry is NOT unknown.
    assert fabricated is not None
    assert fabricated == Decimal("0")
    assert isinstance(fabricated, Decimal)

    # And a MISSING key on the very same file still takes the honest branch —
    # which is what makes `is None` in the state pin above a real assertion.
    assert ct.compute("openai", "gpt-4o", 1_000_000, 0, 0) is None


def test_missing_key_and_null_rates_are_distinguishable_by_the_caller(
    monkeypatch, tmp_path
):
    """The two paths must stay TYPE-distinguishable, not merely value-distinct.

    A caller deciding whether to write NULL cost_usd branches on `is None`. If
    the two paths ever collapse to the same value, that decision silently
    becomes "price everything at zero".
    """
    import json as _json

    # Path A: key genuinely absent.
    empty_prices = tmp_path / "empty_prices.json"
    empty_prices.write_text(_json.dumps({"_comment": "no models"}), encoding="utf-8")
    monkeypatch.setenv("COST_PRICES_PATH", str(empty_prices))
    unknown = ct.compute("openai", "gpt-5.6-sol", 1_000_000, 0, 0)

    # Path B: key present, rates null.
    null_prices = tmp_path / "null_prices_b.json"
    null_prices.write_text(
        _json.dumps({"openai/gpt-5.6-sol": {"prompt": None}}), encoding="utf-8"
    )
    monkeypatch.setenv("COST_PRICES_PATH", str(null_prices))
    fabricated = ct.compute("openai", "gpt-5.6-sol", 1_000_000, 0, 0)

    assert unknown is None
    assert fabricated is not None
    assert type(unknown) is not type(fabricated)
    # Both are falsy. This line is why every assertion in this pair avoids
    # truthiness: `if not cost:` cannot tell these two apart.
    assert not unknown and not fabricated


# ===========================================================================
# Credentials in URL QUERY PARAMETERS (plan 15.8-08)
#
# This module's docstring already claimed a SerpApi audit row "carr[ies] no
# credential". These tests make that claim TESTABLE instead of asserted.
#
# THE THREAT: audit objects are written under SEVEN-YEAR retention. SerpApi
# authenticates by QUERY PARAMETER, so a URL is a credential-bearing value. The
# pre-existing `_redact_dict` matches DICT KEY NAMES ONLY and never inspects a
# value, so `{"url": "...?api_key=LIVE"}` sailed straight through it. Worse, the
# RESPONSE half of the blob was a bare `deepcopy` with NO redaction of any kind,
# while `AuditedLLMClient.write_failure` writes `{"error": str(error)}` there and
# `serpapi.search` does not wrap its httpx call -- so a transport exception
# rendering the request URL was frozen verbatim for seven years.
#
# These tests assert the BYTES THAT REACH STORAGE via the real
# `upload_audit_body` + its NESTOR_AUDIT_LOCAL_DIR file:// fallback -- not what a
# helper returned. A helper's return value is not what gets retained.
# ===========================================================================

_LIVE_SECRET = "LIVE-KEY-VALUE-do-not-retain-9f3c2a"


def _stored_bytes(tmp_dir) -> bytes:
    """Read back every byte written under the local audit dir."""
    written = list(tmp_dir.rglob("*.json"))
    assert written, "upload_audit_body wrote nothing"
    return b"".join(p.read_bytes() for p in written)


async def test_credential_in_request_url_never_reaches_storage(monkeypatch, tmp_path):
    """Test D: a credential in a REQUEST url is scrubbed in the stored bytes."""
    monkeypatch.setenv("NESTOR_AUDIT_LOCAL_DIR", str(tmp_path))

    await gcs_blob.upload_audit_body(
        run_id=_RUN_ID,
        audit_id=uuid.uuid4(),
        provider="serpapi",
        model="google",
        request_dict={
            "url": f"https://serpapi.com/search.json?q=coffee&api_key={_LIVE_SECRET}"
        },
        response_dict={},
    )

    body = _stored_bytes(tmp_path)
    assert _LIVE_SECRET.encode() not in body
    assert b"[REDACTED]" in body
    # Not over-redacted: the evidence the record exists to hold survives.
    assert b"serpapi.com/search.json" in body
    assert b"q=coffee" in body


async def test_credential_in_response_half_never_reaches_storage(monkeypatch, tmp_path):
    """Test E: THE HALF THAT HAD NO REDACTION AT ALL before plan 15.8-08.

    This is the exact shape `AuditedLLMClient.write_failure` produces.
    """
    monkeypatch.setenv("NESTOR_AUDIT_LOCAL_DIR", str(tmp_path))

    await gcs_blob.upload_audit_body(
        run_id=_RUN_ID,
        audit_id=uuid.uuid4(),
        provider="serpapi",
        model="google",
        request_dict={},
        response_dict={
            "error": (
                "ConnectError: failed to reach "
                f"https://serpapi.com/search.json?q=x&api_key={_LIVE_SECRET}"
            ),
            "type": "ConnectError",
        },
    )

    body = _stored_bytes(tmp_path)
    assert _LIVE_SECRET.encode() not in body
    assert b"[REDACTED]" in body
    # The diagnostic value of the error survives the scrub.
    assert b"ConnectError" in body


async def test_response_half_also_gets_key_name_redaction(monkeypatch, tmp_path):
    """The response half gains BOTH mechanisms, not just the URL scrub."""
    monkeypatch.setenv("NESTOR_AUDIT_LOCAL_DIR", str(tmp_path))

    await gcs_blob.upload_audit_body(
        run_id=_RUN_ID,
        audit_id=uuid.uuid4(),
        provider="openai",
        model="gpt-5.6-sol",
        request_dict={},
        response_dict={"echo": {"api_key": _LIVE_SECRET}},
    )

    body = _stored_bytes(tmp_path)
    assert _LIVE_SECRET.encode() not in body
    assert b"[REDACTED]" in body


@pytest.mark.parametrize(
    "url",
    [
        f"https://a.example/s?api_key={_LIVE_SECRET}",
        f"https://a.example/s?apikey={_LIVE_SECRET}",
        f"https://a.example/s?api-key={_LIVE_SECRET}",
        f"https://a.example/s?key={_LIVE_SECRET}",
        f"https://a.example/s?token={_LIVE_SECRET}",
        f"https://a.example/s?access_token={_LIVE_SECRET}",
        f"https://a.example/s?serpapi_key={_LIVE_SECRET}",
        # Case-insensitive, and in a trailing `&` position rather than after `?`.
        f"https://a.example/s?q=1&API_KEY={_LIVE_SECRET}",
        f"https://a.example/s?q=1&ApiKey={_LIVE_SECRET}&page=2",
    ],
)
def test_every_credential_parameter_spelling_is_scrubbed(url):
    """Test F: spellings, cases and both `?`/`&` positions."""
    scrubbed = gcs_blob._scrub_urls_in_value(url)
    assert _LIVE_SECRET not in scrubbed
    assert "[REDACTED]" in scrubbed
    assert scrubbed.startswith("https://a.example/s?")
    # EXACTLY the credential's value changed and nothing else: substituting the
    # secret back reconstructs the original URL byte-for-byte. This catches both
    # over-redaction and a scrubber that rewrites/re-orders the query string.
    assert scrubbed.replace("[REDACTED]", _LIVE_SECRET) == url


def test_scrub_stops_at_the_parameter_boundary():
    """The value terminator must stop at `&` -- NOT swallow the rest of the query.

    A too-greedy terminator (`[^\\s]*` instead of `[^&\\s]*`) still hides the
    credential, so every "is the secret gone?" assertion passes while the
    scrubber silently eats every following parameter. That is over-redaction
    wearing a passing test, and it destroys audit evidence.
    """
    scrubbed = gcs_blob._scrub_urls_in_value(
        f"https://a.example/s?q=1&api_key={_LIVE_SECRET}&page=2&lang=nl"
    )
    assert _LIVE_SECRET not in scrubbed
    assert scrubbed == "https://a.example/s?q=1&api_key=[REDACTED]&page=2&lang=nl"


def test_only_the_credential_parameter_is_touched_among_many():
    """Two credentials and three innocents in one URL: exactly two get replaced."""
    scrubbed = gcs_blob._scrub_urls_in_value(
        f"https://a.example/s?utm=a&api_key={_LIVE_SECRET}&q=b&token={_LIVE_SECRET}&page=9"
    )
    assert scrubbed == (
        "https://a.example/s?utm=a&api_key=[REDACTED]&q=b&token=[REDACTED]&page=9"
    )


def test_every_declared_credential_parameter_is_actually_scrubbed():
    """THE VOCABULARY ITSELF IS PINNED -- every entry, not just the popular ones.

    Added after a mutation run: deleting `auth_token`, `x_api_key`, `secret` and
    `password` from `_CREDENTIAL_QUERY_PARAMS` left the whole suite GREEN,
    because no test named them. An unpinned entry can be dropped by a future
    edit with nothing going red -- on a 7-year-retention store.

    TWO ASSERTIONS ARE REQUIRED HERE AND THE FIRST IS NOT OPTIONAL. Deriving the
    cases from the constant alone is SELF-REFERENTIAL: shrink the constant and a
    derived-only test simply tests less and stays green -- verified by mutation,
    which is how the explicit floor below came to be written. The literal set is
    the INVARIANT; the derived loop is the forward-compatibility half that picks
    up names added later.
    """
    # (1) THE FLOOR -- literal, so a deletion cannot go unnoticed.
    required = {
        "api_key",
        "apikey",
        "key",
        "token",
        "access_token",
        "auth_token",
        "serpapi_key",
        "x_api_key",
        "secret",
        "password",
    }
    missing = required - set(gcs_blob._CREDENTIAL_QUERY_PARAMS)
    assert not missing, f"credential parameter(s) removed from the vocabulary: {missing}"

    # (2) THE DERIVED HALF -- every declared name genuinely scrubs.
    for name in gcs_blob._CREDENTIAL_QUERY_PARAMS:
        url = f"https://a.example/s?{name}={_LIVE_SECRET}&keep=1"
        scrubbed = gcs_blob._scrub_urls_in_value(url)
        assert _LIVE_SECRET not in scrubbed, f"{name} was NOT scrubbed"
        assert scrubbed == f"https://a.example/s?{name}=[REDACTED]&keep=1"

        # And the `-` spelling of the same name is covered by the same entry.
        dashed = name.replace("_", "-")
        dashed_url = f"https://a.example/s?{dashed}={_LIVE_SECRET}&keep=1"
        assert _LIVE_SECRET not in gcs_blob._scrub_urls_in_value(dashed_url), (
            f"{dashed} was NOT scrubbed"
        )


def test_credential_url_scrubbed_when_nested_in_list_or_subdict():
    """Test F (cont.): the walker reaches into lists and sub-dicts."""
    nested = {
        "outer": [
            {"inner": {"url": f"https://a.example/s?api_key={_LIVE_SECRET}"}},
            [f"https://b.example/s?token={_LIVE_SECRET}"],
        ]
    }
    scrubbed = gcs_blob._scrub_urls_in_value(nested)
    flattened = repr(scrubbed)
    assert _LIVE_SECRET not in flattened
    assert flattened.count("[REDACTED]") == 2


@pytest.mark.parametrize(
    "clean_url",
    [
        "https://example.com/a?utm_source=x&q=coffee",
        "https://news.example/article?id=42&page=2",
        # `monkey` ENDS in `key` and `api_keyx` STARTS with `api_key`: neither is a
        # credential parameter, and a sloppier pattern would maul both.
        "https://example.com/s?monkey=banana",
        "https://example.com/s?api_keyx=notacredential",
        "https://example.com/path/keyword/token",
    ],
)
def test_clean_urls_are_returned_byte_identical(clean_url):
    """Test G: NO OVER-REDACTION.

    A scrubber that mangles every URL destroys the audit evidence it exists to
    protect. Asserted as byte-identity, not as "no [REDACTED]".
    """
    assert gcs_blob._scrub_urls_in_value(clean_url) == clean_url


@pytest.mark.parametrize(
    "value",
    [
        None,
        42,
        3.14,
        True,
        b"\xff\xfe\x00 undecodable binary",
        {"deep": [{"deeper": [{"deepest": ["no urls here"]}]}]},
        "http://[malformed::url?api_key=",
        "?????&&&&=====",
        "",
    ],
)
def test_scrubber_never_raises(value):
    """Test H: this sits in the LIVE audit-write path.

    A redactor that raises turns a failure to redact into a failure to RECORD,
    which is strictly worse. Same discipline as `serpapi._safe_excerpt`.
    """
    gcs_blob._scrub_urls_in_value(value)  # must simply not raise


def test_bytes_values_are_scrubbed_and_keep_their_type():
    """Bytes are NOT inert: `json.dumps(default=str)` stringifies them INTO the blob.

    Found while executing plan 15.8-08 -- the first draft of the scrubber passed
    bytes through untouched, which would have written a credential to a
    7-year-retained object via the `default=str` serialiser.
    """
    scrubbed = gcs_blob._scrub_urls_in_value(f"x?api_key={_LIVE_SECRET}".encode())
    assert isinstance(scrubbed, bytes)
    assert _LIVE_SECRET.encode() not in scrubbed
    assert b"[REDACTED]" in scrubbed

    # A clean bytes value is returned untouched, and undecodable binary is left
    # strictly alone rather than corrupted by a lossy decode.
    assert gcs_blob._scrub_urls_in_value(b"x?q=coffee") == b"x?q=coffee"
    assert gcs_blob._scrub_urls_in_value(b"\xff\xfe") == b"\xff\xfe"


def test_key_name_redaction_still_works_unchanged():
    """The pre-existing mechanism must not regress -- it is the header control.

    `test_own_researcher.py` also pins this; asserted here so a change to
    `gcs_blob` that breaks it fails in the module that owns the contract too.
    """
    redacted = gcs_blob._redact_dict(
        {"params": {"api_key": _LIVE_SECRET}}, gcs_blob._DEFAULT_REDACT_KEYS
    )
    assert redacted["params"]["api_key"] == "[REDACTED]"
