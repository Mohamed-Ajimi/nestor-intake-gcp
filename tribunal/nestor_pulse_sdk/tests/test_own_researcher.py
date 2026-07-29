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

  FEED (plan 15.3-04) — the emit sites, in this same file because
  `test_own_researcher.py` is ALREADY registered in the engine gate and this
  plan therefore adds no test file and does not touch `EXPECTED_FILES`
   17. the tool line names both spending ceilings
   18. the search line equals the CLAMPED, SCRUBBED string actually dispatched
   19. a fetched page is named BY HOST and never by URL (T-15.3-30)
   20. a refused search is NOT reported as a search
   21. the stream that never ran, and the stream that stops halfway, say so
   22. `thinking` is capped at one line per tool round (T-15.3-33)
   23. a recorder that RAISES changes nothing about the session
   24. NOR does a turn whose shape makes the LINE ITSELF raise — driven through
       the real emitter, with a negative control (T-15.3-34b)
   25. a long provider poll narrates itself in words: elapsed minutes, attempt
       number, and the sentence that separates a wait from a stall
   26. a rejoined job says so; a refused job id never reaches a stored row

WHY 23 AND 24 ARE BOTH HERE. A raising recorder proves CALLING the emitter is
safe. It is structurally incapable of proving that BUILDING the arguments is
safe, because by the time any recorder runs they already exist. 24 uses the REAL
`run_events` module — nothing on it monkeypatched — and hands the loop a turn
whose `agent_done` counts and whose fetched URL cannot be read.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import pathlib
import uuid
from decimal import Decimal
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.audit import gcs_blob
from nestor_pulse_sdk.pipeline.tribunal import own_researcher, reliability, serpapi
from nestor_pulse_sdk.pipeline.tribunal.checkpoints import safe_job_id
from nestor_pulse_sdk.pipeline.tribunal.serpapi import SerpApiError, SerpApiPlan
from nestor_pulse_sdk.runs import run_events

# The emit-site recorder, IMPORTED rather than rebuilt — the same reason
# `test_run_event_emit.py` gives for importing the stubbed engine harness: a
# second recorder is a second thing to drift. It is installed over `emit` and
# NEVER over `emit_safe`, so the real thunk call and the real try/except stay in
# the path under test; patching `emit_safe` would turn every assertion below
# into an assertion about the test double.
from nestor_pulse_sdk.tests.test_run_event_emit import _Recorder

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


# ===========================================================================
# LOOP HALF — own_researcher.py
# ===========================================================================

_PLAN = SerpApiPlan(
    plan_name="Starter",
    plan_monthly_price=Decimal("25"),
    searches_per_month=1000,
    total_searches_left=900,
    unit_price_usd=Decimal("0.025"),
    source="account.json",
)


class _ScriptedResponse:
    """The two attributes the loop reads off a provider response."""

    def __init__(self, *, stop_reason: str, content: list) -> None:
        self.stop_reason = stop_reason
        self.content = content


class _ScriptedOwnAudited:
    """A hand-written stand-in for AuditedLLMClient. Zero network, zero LLM.

    `anthropic_messages` returns pre-scripted responses in order and snapshots
    the messages list it was handed (deep-copied, because the loop mutates it in
    place). `serpapi_search` returns canned results and counts calls.
    """

    def __init__(
        self,
        responses: list,
        *,
        results: Optional[list] = None,
        search_error: Optional[BaseException] = None,
    ) -> None:
        self._responses = list(responses)
        self.results = results if results is not None else []
        self.search_error = search_error
        self.messages_calls: list[list] = []
        self.search_calls: list[dict] = []

    async def anthropic_messages(
        self,
        *,
        run_id,
        tenant_id,
        model,
        messages,
        tools=None,
        max_tokens=None,
        audit_out=None,
        **kwargs,
    ):
        self.messages_calls.append(copy.deepcopy(messages))
        if isinstance(audit_out, dict):
            audit_out["audit_id"] = "aud-1"
            audit_out["cost_usd"] = "0.001"
        assert self._responses, "scripted responses exhausted — the loop over-called"
        return self._responses.pop(0)

    async def serpapi_search(
        self, *, run_id, tenant_id, q, hl="", gl="", num=10, plan=None, **kwargs
    ):
        self.search_calls.append({"q": q, "hl": hl, "gl": gl, "num": num})
        if self.search_error is not None:
            # Mirrors the real client's documented contract: the breaker sees the
            # failure BEFORE the exception reaches the loop.
            serpapi.note_failure(self.search_error)
            raise self.search_error
        return {
            "billable": True,
            "status": "Success",
            "results": list(self.results),
            "metadata": {"id": "abc", "status": "Success"},
            "cost_usd": Decimal("0.025"),
            "audit_id": "aud-serp",
        }


def _tool_use_search(tool_id: str = "tu_1", **args) -> _ScriptedResponse:
    return _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {
                "type": "tool_use",
                "id": tool_id,
                "name": "serpapi_search",
                "input": args or {"q": "some query"},
            }
        ],
    )


def _server_fetch_turn(url: str = "https://example.com/page") -> _ScriptedResponse:
    """A turn in which the model used the SERVER tool web_fetch only."""
    return _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {"type": "server_tool_use", "id": "srv_1", "name": "web_fetch", "input": {}},
            {
                "type": "web_fetch_tool_result",
                "tool_use_id": "srv_1",
                "content": {"url": url},
            },
        ],
    )


def _emit_turn(facts: Optional[list] = None, not_found: Optional[list] = None) -> _ScriptedResponse:
    return _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {"type": "text", "text": "Here is what I established."},
            {
                "type": "tool_use",
                "id": "tu_emit",
                "name": "emit_fact_list",
                "input": {
                    "facts": facts
                    if facts is not None
                    else [
                        {
                            "statement": "Diesel duty in Belgium rose in April 2026.",
                            "source_url": "https://fin.belgium.be/duty",
                            "quality": "official",
                            "certainty": "certain",
                            "evidence": "The excise duty was raised on 1 April 2026.",
                        }
                    ],
                    "not_found": not_found if not_found is not None else ["retail margin data"],
                },
            },
        ],
    )


def _tool_result_blocks(messages: list) -> list[dict]:
    """Every tool_result block present anywhere in a messages snapshot."""
    found = []
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                found.append(block)
    return found


async def test_missing_key_degrades_cleanly():
    """D-12: no key -> empty, named, ZERO LLM calls, ZERO SerpApi calls, no raise."""
    audited = _ScriptedOwnAudited([])

    result = await own_researcher.run_own_research(
        question="anything", facet="pricing", audited=audited,
        run_id=_RUN_ID, tenant_id=_TENANT_ID,
    )

    assert result["facts"] == []
    assert result["degraded"] is True
    assert result["degradation_reasons"] == ["serpapi_key_missing"]
    assert result["searches"] == 0
    assert result["billable_searches"] == 0
    assert result["cost_usd"] == Decimal("0")
    # The whole point: nothing was attempted at all.
    assert audited.messages_calls == []
    assert audited.search_calls == []


async def test_pause_turn_continues(monkeypatch):
    """F8: a paused turn is a continuation, not a failure."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [_ScriptedResponse(stop_reason="pause_turn", content=[]), _emit_turn()]
    )

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert len(audited.messages_calls) == 2
    assert len(result["facts"]) == 1
    assert result["degraded"] is False
    assert "own_researcher_no_fact_list" not in result["degradation_reasons"]


async def test_client_tool_gets_real_tool_result(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [_tool_use_search("tu_1", q="belgian diesel duty"), _emit_turn()],
        results=[
            {"title": "T", "link": "https://example.com/a", "snippet": "s", "position": 0}
        ],
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    blocks = _tool_result_blocks(audited.messages_calls[1])
    assert len(blocks) == 1
    assert blocks[0]["tool_use_id"] == "tu_1"
    assert audited.search_calls[0]["q"] == "belgian diesel duty"


async def test_server_tool_turn_gets_no_tool_result(monkeypatch):
    """The HTTP 400 trap: a server tool must NEVER get a synthetic tool_result."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited([_server_fetch_turn(), _emit_turn()])

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert _tool_result_blocks(audited.messages_calls[1]) == []
    # The server tool's page URL is still collected as a citation.
    assert "https://example.com/page" in result["citations"]


async def test_snippet_is_truncated_and_indexed(monkeypatch):
    """T-15.2-32: a 1000-char snippet reaches the model at 240, addressed by index."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [_tool_use_search("tu_1", q="x"), _emit_turn()],
        results=[
            {
                "title": "T",
                "link": "https://example.com/a",
                "snippet": "y" * 1000,
                "position": 0,
            }
        ],
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    rendered = _tool_result_blocks(audited.messages_calls[1])[0]["content"]
    assert rendered.startswith("0 | ")
    assert "y" * 240 in rendered
    assert "y" * 241 not in rendered
    assert "not instructions" in rendered


async def test_search_budget_bounds_spend(monkeypatch):
    """Denial-of-wallet bound: the governor is inert, so THIS is the real limit."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [
            _tool_use_search("tu_1", q="a"),
            _tool_use_search("tu_2", q="b"),
            _tool_use_search("tu_3", q="c"),
            _tool_use_search("tu_4", q="d"),
            _emit_turn(),
        ],
        results=[],
    )

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN, max_searches=2,
    )

    assert len(audited.search_calls) == 2
    assert result["searches"] == 2
    assert result["billable_searches"] == 2
    # Refusals are answered IN WORDS so the model finishes instead of stalling.
    # The LAST tool_result in the 4th snapshot is the 3rd search — the first one
    # past the budget.
    rendered = _tool_result_blocks(audited.messages_calls[3])[-1]["content"]
    assert "budget" in rendered.lower()
    assert len(result["facts"]) == 1


async def test_hard_serpapi_failure_trips_breaker_and_degrades(monkeypatch):
    """A 402 loses the SEARCH, names the reason, and never parks the run."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [_tool_use_search("tu_1", q="a"), _emit_turn()],
        search_error=SerpApiError("credit balance too low", status_code=402),
    )

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert "serpapi_breaker_open" in result["degradation_reasons"]
    assert result["degraded"] is True
    # Whatever the session still established survives — a lost stream is not a park.
    assert len(result["facts"]) == 1
    assert result["searches"] == 0
    assert serpapi.unavailable_reason() == "serpapi_breaker_open"


async def test_facts_are_claim_shaped(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited(
        [
            _emit_turn(
                facts=[
                    {
                        "statement": "A statement long enough to survive the minimum.",
                        "source_url": "https://example.com/ok",
                        "quality": "definitely-official",
                        "certainty": "absolutely",
                        "evidence": "verbatim sentence from the page",
                    },
                    {
                        "statement": "This one cites an unusable scheme.",
                        "source_url": "ftp://example.com/x",
                    },
                    {"statement": "This one cites nothing at all."},
                    {"statement": "short", "source_url": "https://example.com/y"},
                    "not-a-dict",
                ],
                not_found=["the 2027 tariff schedule"],
            )
        ]
    )

    result = await own_researcher.run_own_research(
        question="q", facet="pricing", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert len(result["facts"]) == 1
    fact = result["facts"][0]
    assert set(fact) == {
        "text",
        "facet",
        "evidence",
        "found_by",
        "source_urls",
        "certainty",
        "provider_quality",
    }
    assert fact["found_by"] == ["own"]
    assert fact["facet"] == "pricing"
    assert fact["source_urls"] == ["https://example.com/ok"]
    # G-11: an unrecognised enum fails toward MORE checking, never less.
    assert fact["provider_quality"] == "other"
    assert fact["certainty"] == "single"
    assert result["not_found"] == ["the 2027 tariff schedule"]


async def test_loop_exhaustion_degrades_with_a_named_reason(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    audited = _ScriptedOwnAudited([_server_fetch_turn(), _server_fetch_turn()])

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN, max_turns=2,
    )

    assert result["facts"] == []
    assert result["degraded"] is True
    assert "own_researcher_no_fact_list" in result["degradation_reasons"]


def test_no_raw_http_to_model_url():
    """T-15.2-33: page reads go through build_web_fetch's server-side bounds only."""
    source = pathlib.Path(own_researcher.__file__).read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )
    assert "httpx" not in code
    assert "build_web_fetch" in code
    assert "build_web_search" not in source


def test_deep_research_audited_matches_the_provider_runner_contract():
    params = sorted(inspect.signature(own_researcher.deep_research_audited).parameters)
    assert params == ["audited", "query", "run_id", "tenant_id"]


async def test_deep_research_audited_error_envelope_without_a_key():
    audited = _ScriptedOwnAudited([])
    envelope = await own_researcher.deep_research_audited(
        query="q", audited=audited, run_id=_RUN_ID, tenant_id=_TENANT_ID
    )
    assert envelope["status"] == "error"
    assert envelope["error_message"] == "serpapi_key_missing"
    assert envelope["fact_source"] == "emit_fact_list"
    assert audited.messages_calls == []


async def test_deep_research_audited_report_carries_the_d8_block(monkeypatch):
    """All four streams hand the merge the same shape."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    async def _stub_fetch_plan(**kwargs):
        return _PLAN

    async def _stub_record(*args, **kwargs):
        return None

    monkeypatch.setattr(serpapi, "fetch_plan", _stub_fetch_plan)
    monkeypatch.setattr(serpapi, "record_plan_for_run", _stub_record)

    audited = _ScriptedOwnAudited([_emit_turn()])
    envelope = await own_researcher.deep_research_audited(
        query="q", audited=audited, run_id=_RUN_ID, tenant_id=_TENANT_ID
    )

    assert envelope["status"] == "success"
    assert "FACTS_START" in envelope["report"]
    assert "FACTS_END" in envelope["report"]
    assert "NOT_FOUND_START" in envelope["report"]
    assert "Here is what I established." in envelope["report"]
    assert envelope["fact_source"] == "emit_fact_list"
    assert envelope["facts"][0]["found_by"] == ["own"]


# ===========================================================================
# FEED HALF — the run-event emit sites (plan 15.3-04)
#
# Nothing here opens a run. `open_run` is 15.3-03's and a second call is refused
# with a warning; these tests record what the SITES produce, which is the only
# thing this plan owns.
# ===========================================================================


def _install_recorder(monkeypatch, *, raises: bool = False) -> _Recorder:
    recorder = _Recorder(raises=raises)
    monkeypatch.setattr(run_events, "emit", recorder)
    return recorder


def _emitter_log(caplog) -> str:
    """Only what the EMITTER logged. Records from other loggers would make an
    assertion about the swallowed exception type pass or fail for the wrong
    reason."""
    return "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("nestor_pulse_sdk.runs.run_events")
    )


def _fetch_turn_with(content: Any) -> _ScriptedResponse:
    """A server-tool turn whose `web_fetch_tool_result` carries `content` verbatim."""
    return _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {"type": "server_tool_use", "id": "srv_1", "name": "web_fetch", "input": {}},
            {
                "type": "web_fetch_tool_result",
                "tool_use_id": "srv_1",
                "content": content,
            },
        ],
    )


def _emit_turn_with_raw_input(raw_input: Any) -> _ScriptedResponse:
    """An emit_fact_list turn whose tool input is whatever the model shaped it as."""
    return _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {
                "type": "tool_use",
                "id": "tu_emit",
                "name": "emit_fact_list",
                "input": raw_input,
            }
        ],
    )


async def test_the_tool_line_names_both_spending_ceilings(monkeypatch):
    """The design's "Loaded X — Y" line, with the two numbers that bound spend."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited([_emit_turn()])

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN, max_searches=4, max_fetch_uses=5,
    )

    tools = recorder.texts("tool")
    assert len(tools) == 1, "the tool set is loaded once per session, so say it once"
    assert "serpapi_search" in tools[0]
    assert "web_fetch" in tools[0]
    assert "4 searches" in tools[0]
    assert "5 page reads" in tools[0]
    assert all(row["stage"] == "own_research" for row in recorder.rows)


async def test_the_search_line_is_the_string_that_actually_left_the_platform(
    monkeypatch,
):
    """(a) EQUALITY, not containment, against the value handed to the provider.

    The model authors a query carrying an email address. `_clamp_search_input`
    scrubs it before dispatch (D-I), and the feed row must carry the SCRUBBED,
    CLAMPED string — a row describing a different string from the one that left
    the platform would be a false record, and one carrying the unscrubbed
    original would be the disclosure the scrub exists to prevent.
    """
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    authored = "roaster margins contact someone@example.com for the dataset"
    audited = _ScriptedOwnAudited(
        [_tool_use_search("tu_1", q=authored), _emit_turn()], results=[]
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    dispatched = audited.search_calls[0]["q"]
    assert "someone@example.com" not in dispatched, (
        "precondition: the clamp must have scrubbed this query"
    )
    searches = [
        text for text in recorder.texts("search") if text.startswith("Searching — ")
    ]
    assert len(searches) == 1
    assert searches[0] == f"Searching — {dispatched}"
    assert "someone@example.com" not in searches[0]


async def test_a_refused_search_is_not_reported_as_a_search(monkeypatch):
    """(20) The budget is spent, so nothing left the platform and nothing is claimed."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited(
        [
            _tool_use_search("tu_1", q="a"),
            _tool_use_search("tu_2", q="b"),
            _tool_use_search("tu_3", q="c"),
            _emit_turn(),
        ],
        results=[],
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN, max_searches=1,
    )

    dispatched = [text for text in recorder.texts("search") if text.startswith("Searching")]
    assert len(audited.search_calls) == 1
    assert dispatched == ["Searching — a"], (
        "two of the three searches never ran; a feed line for them would assert "
        "work this run did not do"
    )


async def test_a_fetched_page_is_named_by_host_and_never_by_url(monkeypatch):
    """(b) T-15.3-30: the host, and no scheme, path or query string."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited(
        [
            _server_fetch_turn("https://beliancoffee.be/prices?client=acme&id=8891"),
            _emit_turn(),
        ]
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    fetches = [text for text in recorder.texts("search") if text.startswith("Fetching")]
    assert fetches == ["Fetching beliancoffee.be"]
    for text in recorder.texts("search"):
        assert "//" not in text, "no scheme reaches the feed row"
        assert "client=acme" not in text, "no query string reaches the feed row"
        assert "8891" not in text


async def test_the_stream_that_never_ran_says_why(monkeypatch):
    """(c) The D-12 path stops being SILENT. Silence reads as absence."""
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited([])

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited,
        run_id=_RUN_ID, tenant_id=_TENANT_ID,
    )

    assert result["degradation_reasons"] == ["serpapi_key_missing"]
    fails = recorder.texts("agent_fail")
    assert len(fails) == 1
    assert "serpapi_key_missing" in fails[0], "a lost stream is always NAMED"
    assert "continues" in fails[0]
    # Nothing else was claimed: the stream never loaded a tool or ran a search.
    assert recorder.of("tool") == []
    assert recorder.of("search") == []


async def test_a_stream_that_loses_its_provider_halfway_says_so(monkeypatch):
    """(21, second half) A 402 mid-session is a named loss, not fewer lines."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited(
        [_tool_use_search("tu_1", q="a"), _emit_turn()],
        search_error=SerpApiError("credit balance too low", status_code=402),
    )

    result = await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert "serpapi_breaker_open" in result["degradation_reasons"]
    fails = recorder.texts("agent_fail")
    assert len(fails) == 1
    assert "serpapi_breaker_open" in fails[0]
    assert "mid-session" in fails[0]


async def test_thinking_is_capped_at_one_line_per_tool_round(monkeypatch):
    """(22) T-15.3-33: a chatty turn cannot flood the stage."""
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    chatty = _ScriptedResponse(
        stop_reason="tool_use",
        content=[
            {"type": "text", "text": "First I will check the duty schedule."},
            {"type": "text", "text": "Then the retail margin series."},
            {"type": "text", "text": "And finally the import volumes."},
            {"type": "tool_use", "id": "tu_1", "name": "serpapi_search",
             "input": {"q": "belgian diesel duty"}},
        ],
    )
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited([chatty, _emit_turn()], results=[])

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    thinking = recorder.texts("thinking")
    # Two turns produced text (the chatty one and the emit turn's prose), so at
    # most two lines — never one per text block.
    assert len(thinking) == 2
    assert "First I will check the duty schedule." in thinking[0]
    assert "And finally the import volumes." in thinking[0]
    assert len(thinking[0]) <= own_researcher._THINKING_FEED_CHARS


async def test_the_done_line_counts_facts_pages_and_what_was_skipped(monkeypatch):
    """The design's own-query result line, with a skipped count that is real.

    Two of the three entries the model emitted have no usable source URL, so
    this module dropped them. `2 skipped` is that difference and nothing else.
    """
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)
    recorder = _install_recorder(monkeypatch)
    audited = _ScriptedOwnAudited(
        [
            _server_fetch_turn("https://fin.belgium.be/duty"),
            _emit_turn(
                facts=[
                    {
                        "statement": "Diesel duty in Belgium rose in April 2026.",
                        "source_url": "https://fin.belgium.be/duty",
                    },
                    {"statement": "This one cites a scheme we refuse.",
                     "source_url": "ftp://example.com/x"},
                    {"statement": "This one cites nothing at all."},
                ],
                not_found=[],
            ),
        ]
    )

    await own_researcher.run_own_research(
        question="q", facet="f", audited=audited, run_id=_RUN_ID,
        tenant_id=_TENANT_ID, plan=_PLAN,
    )

    done = recorder.texts("agent_done")
    assert done == ["Own query done — 1 facts from 1 pages · 2 skipped"]


async def test_a_recorder_that_raises_changes_nothing(monkeypatch):
    """(d) CALLING the emitter is safe — every site, on the real path.

    This says nothing about BUILDING what is passed to it; that is the next
    test's job, and no raising recorder can ever do it.
    """
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    def _script():
        return [
            _server_fetch_turn("https://example.com/page"),
            _tool_use_search("tu_1", q="a"),
            _emit_turn(),
        ]

    clean = await own_researcher.run_own_research(
        question="q", facet="f", audited=_ScriptedOwnAudited(_script(), results=[]),
        run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
    )

    broken_recorder = _install_recorder(monkeypatch, raises=True)
    broken = await own_researcher.run_own_research(
        question="q", facet="f", audited=_ScriptedOwnAudited(_script(), results=[]),
        run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert broken_recorder.rows, "negative control: the broken recorder was reached"
    assert broken == clean


async def test_a_turn_whose_shape_makes_the_line_itself_raise_changes_nothing(
    monkeypatch, caplog
):
    """(d2) THE ARGUMENT-CONSTRUCTION TEST. The REAL `emit_safe`, both halves.

    `emit_safe` is NEVER monkeypatched here — the real `build()` call and the
    real try/except are in the path, which is the whole point. (15.4-05 installs
    a recorder over `emit` so half 1 can assert on the ROW rather than only on a
    log line; that leaves `emit_safe` untouched, exactly as `_Recorder`'s own
    docstring requires.) A recorder alone cannot exercise this: by the time one
    runs, the arguments have already been built successfully. Each half carries
    a NEGATIVE CONTROL that the construction genuinely raises when performed
    outside the emitter, so a green result cannot mean "the input was harmless
    after all".

    15.4-05 CHANGED HALF 1 AND LEFT HALF 2 ALONE, and the asymmetry is the point.

    Half 1 used to assert that a `KeyError` from `_raw_fact_count` reached the
    emitter's WARNING log. That assertion was demanding the defect: a swallowed
    build is a LOST ROW, and every own-research `agent_done` line died whenever
    that raise fired (D-V01-7). The raise itself is still correct — a skipped
    count that cannot be computed must not be printed as zero — so the guard went
    to the one caller that would rather print "unknown" than nothing,
    `_skipped_label`. Half 1 now asserts the LINE SURVIVES with the skipped term
    admitted as unknown.

    Half 2 is untouched, and it is what keeps this test a D-06 proof: `_host_of`
    still raises on a `web_fetch` block with no URL, the fetch line is still
    dropped rather than fabricated, and the session still completes. If anyone
    ever hoists `build()` above `emit_safe`'s try, half 2 goes red.
    """
    monkeypatch.setenv("SERPAPI_API_KEY", _FAKE_KEY)

    # --- half 1: the done line's counts, off a tool input with no `facts` ----
    malformed_block = {
        "type": "tool_use", "id": "tu_emit", "name": "emit_fact_list",
        "input": {"not_found": ["the 2027 tariff schedule"]},
    }
    # NEGATIVE CONTROL, and it now controls the FIX rather than the defect: the
    # raw count genuinely refuses this block, so a green result below means the
    # guard did the work — not that the input was countable after all.
    with pytest.raises((KeyError, TypeError)):
        own_researcher._raw_fact_count(malformed_block)
    assert (
        own_researcher._skipped_label(malformed_block, 0)
        == own_researcher._UNKNOWN_SKIPPED
    )

    recorder = _install_recorder(monkeypatch)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nestor_pulse_sdk.runs.run_events"):
        degraded = await own_researcher.run_own_research(
            question="q", facet="f",
            audited=_ScriptedOwnAudited(
                [_emit_turn_with_raw_input({"not_found": ["the 2027 tariff schedule"]})]
            ),
            run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
        )
    degraded_log = _emitter_log(caplog)
    degraded_done = recorder.texts("agent_done")

    recorder = _install_recorder(monkeypatch)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nestor_pulse_sdk.runs.run_events"):
        well_formed = await own_researcher.run_own_research(
            question="q", facet="f",
            audited=_ScriptedOwnAudited(
                [
                    _emit_turn_with_raw_input(
                        {"facts": [], "not_found": ["the 2027 tariff schedule"]}
                    )
                ]
            ),
            run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
        )
    well_formed_log = _emitter_log(caplog)
    well_formed_done = recorder.texts("agent_done")

    assert degraded == well_formed, (
        "a model that omitted a key it usually sends costs a FEED LINE, never "
        "the session that produced it"
    )
    # THE ROW SURVIVES. This is the assertion that inverted: before 15.4-05 the
    # degraded shape recorded ZERO done lines.
    assert len(degraded_done) == 1, (
        f"the degraded shape recorded {len(degraded_done)} done line(s), not 1 — "
        f"the row was dropped rather than emitted: {degraded_done}"
    )
    assert own_researcher._UNKNOWN_SKIPPED in degraded_done[0], (
        f"the uncomputable skipped count was not admitted as unknown: "
        f"{degraded_done[0]!r}"
    )
    assert "0 skipped" not in degraded_done[0], (
        "a skipped count that cannot be computed was fabricated as zero"
    )
    # The countable shape still renders its real difference: nothing emitted,
    # nothing kept, so `0 skipped` here is a MEASURED zero, not an invented one.
    assert well_formed_done == ["Own query done — 0 facts from 0 pages · 0 skipped"]
    for name, text in (("degraded", degraded_log), ("well_formed", well_formed_log)):
        assert "KeyError" not in text and "TypeError" not in text, (
            f"a build failure was still reported for the {name} shape, so its row "
            f"was DROPPED by the emitter rather than emitted: {text!r}"
        )

    # --- half 2: the fetch line's host, off a web_fetch block with no URL ---
    with pytest.raises((TypeError, ValueError)):
        own_researcher._host_of(None)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nestor_pulse_sdk.runs.run_events"):
        no_url = await own_researcher.run_own_research(
            question="q", facet="f",
            audited=_ScriptedOwnAudited([_fetch_turn_with({}), _emit_turn()]),
            run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
        )
    no_url_log = _emitter_log(caplog)

    with_url = await own_researcher.run_own_research(
        question="q", facet="f",
        audited=_ScriptedOwnAudited(
            [_fetch_turn_with({"url": "https://example.com/page"}), _emit_turn()]
        ),
        run_id=_RUN_ID, tenant_id=_TENANT_ID, plan=_PLAN,
    )

    assert "TypeError" in no_url_log, (
        "the host construction must actually have been reached and swallowed"
    )
    # Everything the session PRODUCED is identical. `citations` is the one key
    # that differs, and it differs because one turn really did surface a page
    # URL and the other did not — a fact about `_collect_citation_urls`, not
    # about events.
    assert no_url["citations"] == []
    assert with_url["citations"] == ["https://example.com/page"]
    assert {k: v for k, v in no_url.items() if k != "citations"} == {
        k: v for k, v in with_url.items() if k != "citations"
    }


# ---------------------------------------------------------------------------
# The long poll — audit/audited_llm_client.py
#
# The provider fakes are IMPORTED from `test_provider_resume.py` rather than
# rebuilt, and imported INSIDE each test: that module gates itself on httpx with
# `importorskip`, and doing it at module level here would skip this whole file —
# including the sixteen own-researcher tests that need no such thing.
# ---------------------------------------------------------------------------


async def _no_sleep(_seconds: Any) -> None:
    """A poll cadence of 30 s, without waiting 30 s. Never a real delay in a test."""
    return None


async def test_a_long_poll_says_in_words_that_it_is_a_wait(monkeypatch):
    """(e) THE WITHDRAWN-D-C FIX, asserted as behaviour.

    Thirty polls at the production cadence. The count of lines is asserted as an
    UPPER BOUND (a stride, not an exact schedule), and the content is asserted
    exactly: minutes elapsed, attempt out of max, and the sentence that tells an
    operator to wait instead of killing a paid run.
    """
    from nestor_pulse_sdk.tests import test_provider_resume as _pr

    fake = _pr._FakeHTTP(
        get_script=[{"status": "running"}] * 30 + [{"status": "completed"}]
    )
    _pr._install_gemini(monkeypatch, fake)
    monkeypatch.setattr(asyncio, "sleep", _no_sleep)
    recorder = _install_recorder(monkeypatch)

    client = _pr._client()
    await client.start_call(
        run_id=_RUN_ID, tenant_id=_TENANT_ID, provider="google", model="m",
        request={"query": "q"},
    )
    result = await client.gemini_deep_research_raw(
        "q", poll_interval=30, max_attempts=70,
    )

    assert result["status"] == "success"
    thinking = recorder.texts("thinking")
    assert 2 <= len(thinking) <= 8, (
        f"a 31-poll wait must produce a handful of lines, not seventy: {len(thinking)}"
    )
    assert any(text.startswith("Waiting on Google") for text in thinking)
    heartbeats = [text for text in thinking if text.startswith("Still waiting")]
    assert heartbeats, "a wait with no heartbeat is indistinguishable from a hang"
    assert any("5 min elapsed" in text for text in heartbeats), (
        "the elapsed-minute arithmetic is the operator's whole basis for waiting"
    )
    assert any("poll 10 of 70" in text for text in heartbeats)
    assert all("NOT A STALL" in text for text in heartbeats), (
        "the wording is the deliverable — this run was misread as a stall once"
    )
    assert all(
        row["stage"] == "deep_research" for row in recorder.rows
    )
    assert all(
        row["meta"] and row["meta"].get("provider") == "google"
        for row in recorder.of("thinking")
    )


async def test_a_poll_with_no_run_context_emits_nothing(monkeypatch):
    """No `start_call`, no run: the client NEVER invents one and never opens one."""
    from nestor_pulse_sdk.tests import test_provider_resume as _pr

    fake = _pr._FakeHTTP(get_script=[{"status": "completed"}])
    _pr._install_gemini(monkeypatch, fake)
    recorder = _install_recorder(monkeypatch)

    result = await _pr._client().gemini_deep_research_raw("q", poll_interval=0)

    assert result["status"] == "success"
    assert recorder.rows == [], (
        "a tenant-less write is the isolation defect this project forbids, so a "
        "call path with no run context emits nothing at all"
    )


async def test_a_rejoined_job_says_so_and_a_refused_id_is_never_quoted(monkeypatch):
    """(f) The money-relevant fact, and the id guard, on the same branch pair."""
    from nestor_pulse_sdk.tests import test_provider_resume as _pr

    # --- accepted: the reconnect branch names the rejoin -------------------
    fake = _pr._FakeHTTP(get_script=[{"status": "completed"}])
    _pr._install_gemini(monkeypatch, fake)
    recorder = _install_recorder(monkeypatch)
    client = _pr._client()
    await client.start_call(
        run_id=_RUN_ID, tenant_id=_TENANT_ID, provider="google", model="m",
        request={"query": "q"},
    )
    result = await client.gemini_deep_research_raw(
        "q", poll_interval=0, resume_job_id="interaction_in_flight_42",
    )

    assert result["status"] == "success"
    assert len(fake.posts) == 0, "precondition: this was a reconnect, not a dispatch"
    rejoins = [text for text in recorder.texts("thinking") if "Rejoined" in text]
    assert len(rejoins) == 1
    assert "job interaction_in_flight_42" in rejoins[0]
    assert "charged twice" in rejoins[0]

    # --- refused: the id never reaches a stored row ------------------------
    poisoned = "../../secrets/interactions/9"
    assert safe_job_id(poisoned) is None, (
        "precondition: this id must be one the guard refuses"
    )
    fake2 = _pr._FakeHTTP(get_script=[{"status": "completed"}])
    _pr._install_gemini(monkeypatch, fake2)
    recorder2 = _install_recorder(monkeypatch)
    client2 = _pr._client()
    await client2.start_call(
        run_id=_RUN_ID, tenant_id=_TENANT_ID, provider="google", model="m",
        request={"query": "q"},
    )
    result2 = await client2.gemini_deep_research_raw(
        "q", poll_interval=0, resume_job_id=poisoned,
    )

    assert result2["status"] == "success"
    assert len(fake2.posts) == 1, "a refused id falls through to a fresh dispatch"
    refusals = [text for text in recorder2.texts("thinking") if "refused" in text]
    assert len(refusals) == 1
    assert "paid for again" in refusals[0], (
        "the operator's question about a refused resume is what it costs"
    )
    for row in recorder2.rows:
        assert poisoned not in row["text"], "T-15.3-32: an unvalidated id is never stored"
        assert ".." not in row["text"]
