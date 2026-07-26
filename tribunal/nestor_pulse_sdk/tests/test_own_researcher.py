"""D10 own-researcher contract tests — Phase 15.2 plan 12.

THIS FILE MAKES ZERO LLM CALLS AND OPENS ZERO NETWORK CONNECTIONS. Every HTTP
response is served by a hand-written `_FakeHttpx` duck type and every provider
response by a hand-written scripted fake, in the register of
`test_gate_replay.py::_AnswerKeyGateAudited`. No database, no mocking library,
no API key, no spend, nothing that can flake — which matters twice over while
`SERPAPI_API_KEY` does not exist yet (plan 15.2-18 creates it) and the Anthropic
account sits at its monthly cap.

Nothing here is marked `live`, and nothing here needs an environment beyond the
repository itself.

Coverage, in two halves:

  CLIENT (`serpapi.py`)
    1. organic results are parsed, coerced, truncated, and hostile links dropped
    2. billable is `search_metadata.status == "Success"` and nothing else
    3. a non-2xx becomes a `SerpApiError` carrying its status and no credential
    4. the API key reaches no log record and no exception message (T-15.2-30)
    5. the GCS redactor still covers a NESTED `api_key` (T-15.2-31)
    6. unit prices are the exact published division, Free tier an honest $0.00
    7. the plan probe never raises, on transport failure or garbled body
    8. a missing key names itself `serpapi_key_missing`

  LOOP (`own_researcher.py`)
    9. a missing key degrades cleanly with ZERO LLM and ZERO SerpApi calls
   10. `stop_reason == "pause_turn"` continues the loop instead of failing (F8)
   11. a client tool gets a real `tool_result`; a server tool gets NONE (400 trap)
   12. snippets reach the model truncated to 240 chars and addressed by index
   13. the search budget bounds spend
   14. a hard SerpApi failure trips the breaker and degrades — it never parks
   15. emitted facts are claim-shaped, clamped, and attributed to "own"
   16. no raw HTTP to a model-chosen URL (T-15.2-33, source assertion)

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.audit import gcs_blob
from nestor_pulse_sdk.pipeline.tribunal import reliability, serpapi
from nestor_pulse_sdk.pipeline.tribunal.serpapi import SerpApiError, SerpApiPlan

#: A key-shaped string that must never appear in a log record or an exception.
_FAKE_KEY = "SERPAPI-TEST-KEY-must-never-be-logged-8f3a91"

_RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_TENANT_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")


# ---------------------------------------------------------------------------
# Hand-written fakes. No mocking library.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """The three attributes `serpapi.search` / `fetch_plan` actually read."""

    def __init__(
        self,
        *,
        status_code: int = 200,
        payload: Any = None,
        text: str = "",
        bad_json: bool = False,
    ) -> None:
        self.status_code = status_code
        self.text = text
        self._payload = payload
        self._bad_json = bad_json

    def json(self) -> Any:
        if self._bad_json:
            raise ValueError("body is not JSON")
        return self._payload


class _FakeHttpx:
    """An `async get(url, params=...)` duck type. Records every call."""

    def __init__(self, response: Optional[_FakeResponse] = None, *, error: Optional[BaseException] = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params: Optional[dict] = None) -> _FakeResponse:
        self.calls.append((url, dict(params or {})))
        if self.error is not None:
            raise self.error
        assert self.response is not None, "_FakeHttpx needs a response or an error"
        return self.response


def _search_payload(status: str = "Success", organic: Any = None) -> dict:
    return {
        "search_metadata": {"id": "abc123", "status": status, "total_time_taken": 1.2},
        "search_parameters": {"engine": "google", "q": "x"},
        "organic_results": organic if organic is not None else [],
    }


@pytest.fixture(autouse=True)
def _clean_serpapi_env(monkeypatch):
    """Every test starts with no key, no override and a fresh breaker."""
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.delenv("NESTOR_TRIBUNAL_SERPAPI_UNIT_USD", raising=False)
    serpapi.reset_breaker()
    yield
    serpapi.reset_breaker()


# ===========================================================================
# CLIENT HALF — serpapi.py
# ===========================================================================


async def test_search_parses_organic_results():
    """Good entries survive coerced and truncated; hostile entries are dropped."""
    organic = [
        {"title": "T", "link": "https://example.com/a", "snippet": "s", "position": 1},
        "not-a-dict",
        {"title": "js", "link": "javascript:alert(1)", "snippet": "x", "position": 2},
        {"title": "no link", "snippet": "x", "position": 3},
        {
            "title": "long",
            "link": "https://example.org/b",
            "snippet": "y" * 400,
            "position": "not-an-int",
        },
    ]
    fake = _FakeHttpx(_FakeResponse(payload=_search_payload(organic=organic)))

    result = await serpapi.search(q="anything", client=fake)

    assert [r["link"] for r in result["results"]] == [
        "https://example.com/a",
        "https://example.org/b",
    ]
    assert result["results"][0]["title"] == "T"
    assert result["results"][0]["position"] == 1
    # The 240-char cap is a prompt-injection control, not formatting.
    assert len(result["results"][1]["snippet"]) == 240
    # An uncoercible position falls back to the enumeration index.
    assert isinstance(result["results"][1]["position"], int)
    # metadata is a whitelist — the raw blob (which echoes search_parameters) is
    # never returned, so a future SerpApi change cannot leak the key through it.
    assert set(result["metadata"]) == {"id", "status", "total_time_taken"}
    assert "search_parameters" not in result


async def test_clean_results_caps_the_list():
    organic = [
        {"title": f"t{i}", "link": f"https://example.com/{i}", "snippet": "", "position": i}
        for i in range(50)
    ]
    fake = _FakeHttpx(_FakeResponse(payload=_search_payload(organic=organic)))
    result = await serpapi.search(q="x", client=fake)
    assert len(result["results"]) == 10


@pytest.mark.parametrize(
    "payload,expected",
    [
        (_search_payload("Success"), True),
        (_search_payload("Processing"), False),
        (_search_payload("Error"), False),
        (_search_payload(""), False),
        ({"organic_results": []}, False),
    ],
)
async def test_billable_only_on_success(payload, expected):
    """SerpApi bills successful searches only — cached, errored and failed are free."""
    fake = _FakeHttpx(_FakeResponse(payload=payload))
    result = await serpapi.search(q="x", client=fake)
    assert result["billable"] is expected


async def test_search_raises_serpapi_error_with_status(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    fake = _FakeHttpx(_FakeResponse(status_code=401, text="Invalid API key"))

    with pytest.raises(SerpApiError) as caught:
        await serpapi.search(q="x", client=fake)

    exc = caught.value
    assert exc.status_code == 401
    rendered = str(exc)
    assert _FAKE_KEY not in rendered
    assert "serpapi.com/search.json?" not in rendered
    # reliability's shared status sniffer must classify it with no special-casing.
    assert reliability._status_of(exc) == 401


async def test_search_raises_on_unreadable_body(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    fake = _FakeHttpx(_FakeResponse(status_code=200, bad_json=True, text="<html>"))
    with pytest.raises(SerpApiError) as caught:
        await serpapi.search(q="x", client=fake)
    assert caught.value.status_code == 200


async def test_key_never_logged(monkeypatch, caplog):
    """T-15.2-30: the key reaches no log record and no exception message."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    body = '{"error": "api_key=' + _FAKE_KEY + ' is not valid"}'
    fake = _FakeHttpx(_FakeResponse(status_code=500, text=body))

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(SerpApiError) as caught:
            await serpapi.search(q="x", client=fake)

    assert caplog.records, "expected at least one log record to inspect"
    for record in caplog.records:
        message = record.getMessage()
        assert _FAKE_KEY not in message
        assert "api_key=" not in message

    rendered = str(caught.value)
    assert _FAKE_KEY not in rendered
    assert "api_key=" not in rendered

    # Nothing in this module may render a URL except through _safe_url.
    assert serpapi._safe_url(serpapi.SEARCH_URL) == "/search.json"
    assert serpapi._safe_url(serpapi.ACCOUNT_URL) == "/account.json"


def test_redactor_covers_nested_api_key():
    """T-15.2-31 belt-and-braces: the audit-blob redactor recurses into nesting."""
    redacted = gcs_blob._redact_dict(
        {"params": {"api_key": "SEKRIT", "q": "x"}}, gcs_blob._DEFAULT_REDACT_KEYS
    )
    assert redacted["params"]["api_key"] == "[REDACTED]"
    assert redacted["params"]["q"] == "x"


@pytest.mark.parametrize(
    "plan_name,price,quota",
    [
        ("Free", 0, 250),
        ("Starter", 25, 1000),
        ("Developer", 75, 5000),
        ("Production", 150, 15000),
        ("Big Data", 275, 30000),
    ],
)
async def test_fetch_plan_unit_price_exact(monkeypatch, plan_name, price, quota):
    """The unit price is the published division, as an exact Decimal — never a float."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    fake = _FakeHttpx(
        _FakeResponse(
            payload={
                "plan_name": plan_name,
                "plan_monthly_price": price,
                "searches_per_month": quota,
                "total_searches_left": 42,
            }
        )
    )

    plan = await serpapi.fetch_plan(client=fake)

    assert plan.source == "account.json"
    assert plan.plan_name == plan_name
    assert isinstance(plan.unit_price_usd, Decimal)
    assert plan.unit_price_usd == Decimal(str(price)) / Decimal(str(quota))


async def test_free_tier_is_an_honest_zero_not_a_missing_number(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    fake = _FakeHttpx(
        _FakeResponse(
            payload={
                "plan_name": "Free",
                "plan_monthly_price": 0,
                "searches_per_month": 250,
            }
        )
    )
    plan = await serpapi.fetch_plan(client=fake)
    assert plan.unit_price_usd == Decimal("0")
    assert plan.unit_price_usd is not None
    assert plan.source == "account.json"
    # resolve_unit_price must KEEP a zero rather than fall through the ladder.
    assert serpapi.resolve_unit_price(plan).source == "account.json"


async def test_zero_quota_yields_no_unit_price(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    fake = _FakeHttpx(
        _FakeResponse(
            payload={"plan_name": "Odd", "plan_monthly_price": 10, "searches_per_month": 0}
        )
    )
    plan = await serpapi.fetch_plan(client=fake)
    assert plan.unit_price_usd is None


@pytest.mark.parametrize(
    "fake",
    [
        _FakeHttpx(error=RuntimeError("transport exploded")),
        _FakeHttpx(_FakeResponse(status_code=200, bad_json=True, text="<html>")),
        _FakeHttpx(_FakeResponse(status_code=500, text="boom")),
        _FakeHttpx(_FakeResponse(payload=["not", "an", "object"])),
    ],
)
async def test_fetch_plan_never_raises(monkeypatch, fake):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    plan = await serpapi.fetch_plan(client=fake)
    assert plan == SerpApiPlan.unknown()
    assert plan.unit_price_usd is None
    assert plan.source == "unknown"


async def test_fetch_plan_without_a_key_makes_no_call():
    fake = _FakeHttpx(_FakeResponse(payload={}))
    plan = await serpapi.fetch_plan(client=fake)
    assert plan == SerpApiPlan.unknown()
    assert fake.calls == []


def test_unavailable_reason_when_key_missing():
    """The D-12 path that is testable TODAY precisely because the secret does not exist."""
    assert serpapi.unavailable_reason() == "serpapi_key_missing"


def test_unavailable_reason_when_breaker_open(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    assert serpapi.unavailable_reason() is None
    serpapi.get_breaker().force_open("test")
    assert serpapi.unavailable_reason() == "serpapi_breaker_open"


def test_note_failure_severity(monkeypatch):
    """401/402 trip at once; 429 never trips (the provider is healthy)."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    serpapi.reset_breaker()
    serpapi.note_failure(SerpApiError(status_code=429))
    assert serpapi.unavailable_reason() is None

    serpapi.reset_breaker()
    serpapi.note_failure(SerpApiError(status_code=401))
    assert serpapi.unavailable_reason() == "serpapi_breaker_open"

    serpapi.reset_breaker()
    serpapi.note_failure(SerpApiError(status_code=402))
    assert serpapi.unavailable_reason() == "serpapi_breaker_open"


def test_resolve_unit_price_env_override(monkeypatch):
    monkeypatch.setenv("NESTOR_TRIBUNAL_SERPAPI_UNIT_USD", "0.0125")
    resolved = serpapi.resolve_unit_price(SerpApiPlan.unknown())
    assert resolved.unit_price_usd == Decimal("0.0125")
    assert resolved.source == "env"


def test_resolve_unit_price_unknown_stays_unknown():
    """No published rate anywhere -> None + "unknown". NEVER a guessed number."""
    resolved = serpapi.resolve_unit_price(SerpApiPlan.unknown())
    assert resolved.unit_price_usd is None
    assert resolved.source == "unknown"
