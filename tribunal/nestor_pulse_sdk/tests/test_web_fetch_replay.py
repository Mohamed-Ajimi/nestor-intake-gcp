"""D-B / D-A regression gate — replaying a FAILED web_fetch turn (Phase 15.2, plan 22).

WHY THIS FILE EXISTS. On run `d6bb3aae` (2026-07-27) two of four research streams
were dead for the whole run, and neither death was visible as a configuration
problem:

  D-B — the own-researcher 400'd on 6 of 6 sessions:
        messages.N.content.M.web_fetch_tool_result.content.RequestWebFetchToolResultError:
        Input does not match the expected shape.
        The block is a PRIOR turn being echoed back, and specifically the ERROR
        variant of a web_fetch result. The stream worked until a fetch failed;
        after that the malformed error result was replayed into every subsequent
        request. The culprit is `skeptic._content_to_serialisable`, which every
        hand-written loop uses to append its assistant turn and which was a
        ONE-LEVEL `__dict__` copy — so a nested provider object survived the copy
        as a LIVE OBJECT rather than the plain dict the request schema accepts.

  D-A — every OpenAI deep-research angle failed with `model_not_found`
        ("The model `o4-mini-deep-research` has been deprecated"). Seven identical
        WARNINGs, none of which said "the model this deployment is configured with
        does not exist". Seven identical warnings is how a configuration error
        disguises itself as flaky providers.

WHY CI MISSED D-B. `test_engine_e2e_stubbed.py` stubs the provider, so it can
never produce Anthropic's real server-tool ERROR payload. The fixture next door
(`fixtures/web_fetch_error_turn.json`) is that payload; this module replays it
through the REAL serialiser.

PURE. No DATABASE_URL, no network, no provider key, no mocking library, no sleep.
Everything here is a recorded payload or a hand-written exception.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from nestor_pulse_sdk.pipeline.tribunal.skeptic import _content_to_serialisable

# ---------------------------------------------------------------------------
# Fixture loading — same `Path(__file__).resolve().parent` idiom as
# tests/fixtures/run_4cbb5311/loader.py, so the file resolves wherever the
# suite is invoked from.
# ---------------------------------------------------------------------------

_FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "web_fetch_error_turn.json"


def _fixture() -> dict[str, Any]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Rehydration. THE FIXTURE IS JSON, BUT THE BUG WAS IN THE OBJECT PATH.
#
# `_content_to_serialisable`'s `isinstance(block, dict)` arm was never broken —
# a fixture replayed as plain dicts would go green while proving nothing. So
# every dict in the recorded turn is rehydrated into a small object carrying
# `__dict__` (exactly what a pydantic v2 SDK model exposes), INCLUDING the
# nested `content` value that the 400 named.
# ---------------------------------------------------------------------------


class _SDKish:
    """A stand-in for an Anthropic SDK content block: attributes, `__dict__`, no `model_dump`.

    Also carries a private attribute, because the SDK's models do and the
    serialiser has always filtered `_`-prefixed keys out.
    """

    def __init__(self, **fields: Any) -> None:
        self.__dict__.update(fields)
        self._private_should_be_dropped = "never sent to the API"

    def __repr__(self) -> str:  # pragma: no cover — debugging aid only
        return f"_SDKish({self.__dict__!r})"


class _PydanticIsh:
    """An object whose `model_dump()` is canonical and whose `__dict__` is NOT.

    This is the load-bearing preference: `model_dump` is the provider's own
    serialisation and is guaranteed to match the request schema, so it must win
    over an attribute copy. The `__dict__` here deliberately carries a live
    nested object so a serialiser that ignored `model_dump` would fail the test.
    """

    def __init__(self, dumped: dict[str, Any]) -> None:
        self._dumped = dumped
        self.type = dumped.get("type")
        self.content = _SDKish(**{"type": "leaked_from_dunder_dict"})

    def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
        return json.loads(json.dumps(self._dumped))


def _rehydrate(value: Any) -> Any:
    """dict -> `_SDKish`, list -> list of rehydrated, primitives unchanged."""
    if isinstance(value, dict):
        return _SDKish(**{k: _rehydrate(v) for k, v in value.items()})
    if isinstance(value, list):
        return [_rehydrate(v) for v in value]
    return value


def _drop_none(value: Any) -> Any:
    """The expected shape: `None`-valued fields are ABSENT, not null.

    A response model declares every optional field, so an attribute copy leaks
    them into the request as explicit nulls. The request schema wants them
    absent, so the serialiser drops them and the expectation must too.
    """
    if isinstance(value, dict):
        return {k: _drop_none(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_none(v) for v in value]
    return value


_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _assert_plain(value: Any, path: str = "$") -> None:
    """Fail with a PATH if any live object survived the conversion.

    `json.dumps` alone would also fail, but with `Object of type _SDKish is not
    JSON serializable` and no location — and the whole D-B incident was about
    locating which nested value was still an object.
    """
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"{path}: non-string key {key!r}"
            _assert_plain(item, f"{path}.{key}")
        return
    if isinstance(value, list):
        for i, item in enumerate(value):
            _assert_plain(item, f"{path}[{i}]")
        return
    assert isinstance(value, _JSON_PRIMITIVES), (
        f"{path}: a live {type(value).__name__} survived serialisation — this is "
        f"exactly the D-B 400 ('Input does not match the expected shape')"
    )


# ===========================================================================
# Behaviour 1 — THE D-B REGRESSION
# ===========================================================================


def test_failed_web_fetch_turn_serialises_to_plain_json() -> None:
    """A failed web_fetch assistant turn round-trips with no live object left.

    This is the exact turn that poisoned the own-researcher's message list.
    `json.dumps` is called with NO `default=` hook on purpose: the request body
    the SDK builds gets no such hook either.
    """
    recorded = _fixture()["error_turn"]["content"]
    blocks = _rehydrate(recorded)

    out = _content_to_serialisable(blocks)

    _assert_plain(out)
    encoded = json.dumps(out)  # no default= — must not raise
    assert json.loads(encoded) == _drop_none(recorded)

    fetch = [b for b in out if b.get("type") == "web_fetch_tool_result"]
    assert len(fetch) == 1, "the recorded turn carries exactly one web_fetch result"
    inner = fetch[0]["content"]
    assert isinstance(inner, dict), (
        "the ERROR variant's `content` must be a plain dict — leaving it as a "
        "RequestWebFetchToolResultError is the 400"
    )
    assert inner["type"] == "web_fetch_tool_result_error"
    assert inner["error_code"] == "url_not_accessible"


def test_private_attributes_are_never_echoed_back() -> None:
    """`_`-prefixed attributes stay out of the request (unchanged contract)."""
    out = _content_to_serialisable(_rehydrate(_fixture()["error_turn"]["content"]))
    assert "_private_should_be_dropped" not in json.dumps(out)


# ===========================================================================
# Behaviour 2 — the SUCCESS variant must not be flattened
# ===========================================================================


def test_successful_web_fetch_turn_round_trips_unchanged() -> None:
    """Fixing the error variant must not break the variant that already worked.

    The success variant's `content` is a nested document block, two levels deep
    (`content.content.source`), so this also proves the conversion recurses
    rather than stopping at the first object it flattens.
    """
    recorded = _fixture()["success_turn"]["content"]

    out = _content_to_serialisable(_rehydrate(recorded))

    _assert_plain(out)
    assert json.loads(json.dumps(out)) == _drop_none(recorded)

    fetch = [b for b in out if b.get("type") == "web_fetch_tool_result"][0]
    document = fetch["content"]["content"]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "text/plain"
    assert document["citations"] == {"enabled": True}


def test_model_dump_is_preferred_over_dunder_dict() -> None:
    """`model_dump()` wins: it is the provider's own canonical serialisation.

    The stand-in's `__dict__` carries a live nested object; its `model_dump()`
    carries the canonical dict. A serialiser that copied attributes would leak
    `leaked_from_dunder_dict` into the request.
    """
    canonical = {
        "type": "web_fetch_tool_result",
        "tool_use_id": "srvtoolu_01ModelDumpWins",
        "content": {"type": "web_fetch_tool_result_error", "error_code": "url_too_long"},
    }

    out = _content_to_serialisable([_PydanticIsh(canonical)])

    _assert_plain(out)
    assert out == [canonical]
    assert "leaked_from_dunder_dict" not in json.dumps(out)


# ===========================================================================
# Behaviour 3 — the existing arms, and the never-raise floor
# ===========================================================================


def test_dict_blocks_pass_through_unchanged() -> None:
    """A block that is already a dict comes back equal, and JSON-clean."""
    blocks = [
        {"type": "text", "text": "already a dict", "cache_control": {"type": "ephemeral"}},
        {"type": "tool_use", "id": "toolu_01", "name": "emit_verdict", "input": {"verdict": "support"}},
    ]

    out = _content_to_serialisable(blocks)

    assert out == blocks
    _assert_plain(out)


def test_exotic_block_degrades_to_a_type_only_dict() -> None:
    """Neither `__dict__` nor a usable `.type`: the never-raise floor holds."""

    class _Exotic:
        __slots__ = ()

    out = _content_to_serialisable([_Exotic()])

    assert out == [{"type": "unknown"}]


def test_a_block_that_cannot_be_converted_does_not_kill_the_loop() -> None:
    """One unconvertible block degrades to `{"type": ...}` instead of raising.

    An assistant turn that cannot be serialised must not throw away a paid loop.
    """

    class _Hostile:
        # `__slots__` means there is no `__dict__` to fall back to, and the
        # canonical dump raises — so both conversion routes are dead ends.
        __slots__ = ()
        type = "web_fetch_tool_result"

        def model_dump(self, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("provider model exploded on dump")

    out = _content_to_serialisable([_Hostile()])

    assert out == [{"type": "web_fetch_tool_result"}]
    _assert_plain(out)


# ===========================================================================
# Behaviour 4 — the same bug one level down: lists of nested objects
# ===========================================================================


def test_lists_of_nested_objects_are_deep_converted() -> None:
    """`citations` is a LIST of provider objects — element-by-element, or it 400s."""
    recorded = {
        "type": "text",
        "text": "The filing puts first-half growth at 12 percent.",
        "citations": [
            {"type": "web_search_result_location", "url": "https://a.example.com", "title": "A"},
            {"type": "web_search_result_location", "url": "https://b.example.com", "title": "B"},
        ],
    }

    out = _content_to_serialisable([_rehydrate(recorded)])

    _assert_plain(out)
    assert out[0]["citations"] == recorded["citations"]
    assert all(isinstance(c, dict) for c in out[0]["citations"])


def test_tuples_are_converted_to_json_lists() -> None:
    """A tuple is not JSON — it must come back as a list, not as a live object."""
    block = _SDKish(type="text", text="x", citations=({"url": "https://a.example.com"},))

    out = _content_to_serialisable([block])

    _assert_plain(out)
    assert out[0]["citations"] == [{"url": "https://a.example.com"}]


# ===========================================================================
# Behaviour 5 — the bounded poison-turn predicate
# ===========================================================================


class _FakeHTTPError(Exception):
    """Hand-written provider error: a status attribute and a message. No SDK."""

    def __init__(self, status_code: int | None = None, message: str = "") -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code


_POISON_MESSAGE = (
    "invalid_request_error: messages.3.content.2.web_fetch_tool_result.content."
    "RequestWebFetchToolResultError: Input does not match the expected shape."
)


def test_is_poisoned_turn_error_recognises_the_d_b_400() -> None:
    from nestor_pulse_sdk.pipeline.tribunal.skeptic import is_poisoned_turn_error

    assert is_poisoned_turn_error(_FakeHTTPError(400, _POISON_MESSAGE)) is True


@pytest.mark.parametrize(
    "exc",
    [
        # A cap 400 that happens to mention the block — the 776-error class must
        # NEVER be swallowed by a "drop the turn and retry" recovery.
        _FakeHTTPError(400, "monthly usage cap reached; last call sent a web_fetch_tool_result"),
        _FakeHTTPError(400, "billing_error: your credit balance is too low. web_fetch_tool_result"),
        # Right wording, wrong status: a 429 is a rate limit, not a poisoned turn.
        _FakeHTTPError(429, _POISON_MESSAGE),
        # A plain server error carries no shape information at all.
        _FakeHTTPError(500, "internal server error"),
        # A 400 about something else entirely.
        _FakeHTTPError(400, "max_tokens: must be greater than 0"),
    ],
    ids=["cap-400", "billing-400", "rate-limit-429", "server-500", "unrelated-400"],
)
def test_is_poisoned_turn_error_is_false_for_everything_else(exc: Exception) -> None:
    from nestor_pulse_sdk.pipeline.tribunal.skeptic import is_poisoned_turn_error

    assert is_poisoned_turn_error(exc) is False


def test_is_poisoned_turn_error_never_raises() -> None:
    """A predicate that raises is worse than a wrong answer."""
    from nestor_pulse_sdk.pipeline.tribunal.skeptic import is_poisoned_turn_error

    class _Unprintable(Exception):
        def __str__(self) -> str:
            raise RuntimeError("nope")

    assert is_poisoned_turn_error(_Unprintable()) is False


# ===========================================================================
# Behaviours 6-9 — D-A: a refused model id is a CONFIGURATION error
#
# On run d6bb3aae seven OpenAI angles failed one at a time, each a WARNING, none
# of them saying "the model this deployment is configured with does not exist".
# The point of these four behaviours is that the eighth angle never gets sent.
# ===========================================================================


class _Clock:
    """A hand-cranked monotonic clock. `c.t = 61.0` advances time by fiat."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


# The literal message from run d6bb3aae, and its siblings across providers.
_D_A_MESSAGE = "ResponseError(code='model_not_found', message='The model `o4-mini-deep-research` has been deprecated')"

_CONFIG_ERROR_CASES = [
    (_FakeHTTPError(404, _D_A_MESSAGE), "the-d-a-message"),
    (_FakeHTTPError(400, "model_not_found"), "model-not-found-code"),
    (_FakeHTTPError(404, "The model `gpt-5.6-sol` does not exist or you do not have access to it."), "does-not-exist"),
    (_FakeHTTPError(400, "unknown model: claude-opus-9"), "unknown-model"),
    (_FakeHTTPError(400, "this model has been deprecated"), "deprecated"),
    # No status at all — the WORDING is the signal, not the code.
    (Exception("model_not_found: no such deep-research model"), "no-status"),
]


@pytest.mark.parametrize(
    "exc", [c[0] for c in _CONFIG_ERROR_CASES], ids=[c[1] for c in _CONFIG_ERROR_CASES]
)
def test_a_refused_model_id_classifies_as_a_configuration_error(exc: BaseException) -> None:
    """Behaviour 6 — the class exists and the wording reaches it."""
    from nestor_pulse_sdk.pipeline.tribunal.reliability import CONFIG_ERROR, classify

    assert classify(exc) == CONFIG_ERROR


@pytest.mark.parametrize(
    "exc", [c[0] for c in _CONFIG_ERROR_CASES], ids=[c[1] for c in _CONFIG_ERROR_CASES]
)
def test_a_refused_model_id_is_never_retried(exc: BaseException) -> None:
    """Behaviour 7 — retrying a dead model id can only produce more of the same."""
    from nestor_pulse_sdk.pipeline.tribunal.reliability import is_transient

    assert is_transient(exc) is False


def test_a_configuration_error_trips_the_breaker_on_the_first_occurrence() -> None:
    """Behaviour 8 — the SECOND angle of that provider is refused without a call.

    Seven identical warnings is how a configuration error disguises itself as a
    flaky provider. One is a configuration error.
    """
    from nestor_pulse_sdk.pipeline.tribunal.reliability import (
        CLOSED,
        CircuitBreaker,
        CircuitOpenError,
    )

    breaker = CircuitBreaker("openai", clock=_Clock())
    assert breaker.state == CLOSED

    breaker.record_failure(_FakeHTTPError(404, _D_A_MESSAGE))

    assert breaker.state != CLOSED, "one refused model id must be enough"
    assert breaker.allow() is False
    with pytest.raises(CircuitOpenError):
        breaker.raise_if_open()
    assert breaker.reason, "a lost stream is always NAMED, never a silent absence"


def test_the_second_call_after_a_refused_model_id_is_never_dispatched() -> None:
    """Behaviour 8, end to end through `with_retry` — no call, no spend."""
    import asyncio

    from nestor_pulse_sdk.pipeline.tribunal.reliability import (
        CircuitBreaker,
        CircuitOpenError,
    )

    breaker = CircuitBreaker("openai", clock=_Clock())
    calls: list[int] = []

    async def _angle() -> None:
        calls.append(1)
        raise _FakeHTTPError(404, _D_A_MESSAGE)

    async def _drive() -> None:
        from nestor_pulse_sdk.pipeline.tribunal.reliability import with_retry

        with pytest.raises(_FakeHTTPError):
            await with_retry(_angle, label="openai-angle-1", breaker=breaker)
        # The next angle is refused BEFORE `fn` is called at all.
        with pytest.raises(CircuitOpenError):
            await with_retry(_angle, label="openai-angle-2", breaker=breaker)

    asyncio.run(_drive())

    assert calls == [1], (
        f"the dead model id was dispatched {len(calls)} times; on run d6bb3aae it "
        f"was dispatched seven"
    )


@pytest.mark.parametrize(
    "message",
    [
        "monthly usage cap reached for this account",
        "billing_error: your credit balance is too low",
        "insufficient_quota",
        "you have exceeded your quota",
    ],
    ids=["usage-cap", "billing", "insufficient-quota", "exceeded"],
)
def test_cap_and_billing_wording_still_classifies_as_a_hard_wall(message: str) -> None:
    """Behaviour 9 — the 776-error rules are EXTENDED, never re-tuned.

    A regression here would be silent and expensive, so it is asserted on the
    existing `_CAP_MARKERS` wording directly.
    """
    from nestor_pulse_sdk.pipeline.tribunal.reliability import (
        CONFIG_ERROR,
        HARD_WALL,
        classify,
        is_transient,
    )

    exc = _FakeHTTPError(400, message)
    assert classify(exc) == HARD_WALL
    assert classify(exc) != CONFIG_ERROR
    assert is_transient(exc) is False


def test_the_ordinary_failure_classes_are_untouched() -> None:
    """Behaviour 9, the other side: nothing else moved class."""
    from nestor_pulse_sdk.pipeline.tribunal.reliability import (
        HARD,
        OVERLOAD,
        RATE_LIMIT,
        TRANSIENT,
        classify,
    )

    assert classify(_FakeHTTPError(429, "too many requests")) == RATE_LIMIT
    assert classify(_FakeHTTPError(529, "overloaded_error")) == OVERLOAD
    assert classify(_FakeHTTPError(503, "service unavailable")) == TRANSIENT
    assert classify(_FakeHTTPError(401, "authentication_error invalid x-api-key")) == HARD
    assert classify(Exception("something nobody has seen before")) == HARD


def test_does_not_exist_is_scoped_to_MODELS_not_to_any_missing_thing() -> None:
    """A bare "does not exist" must NOT trip a provider's breaker on first sight.

    The plan named `does not exist` as a marker. Taken as a bare substring it
    also matches "the requested file does not exist" and a resumed background
    response that is past its retention window — neither of which is a statement
    about this deployment's configuration, and both of which would then open the
    circuit on a healthy provider after ONE failure. So the phrase is honoured in
    its model-scoped form only.
    """
    from nestor_pulse_sdk.pipeline.tribunal.reliability import (
        CONFIG_ERROR,
        HARD,
        classify,
    )

    assert classify(_FakeHTTPError(404, "The requested file does not exist")) == HARD
    assert classify(_FakeHTTPError(404, "response resp_0182 does not exist")) == HARD
    assert (
        classify(_FakeHTTPError(404, "The model `gpt-5.6-sol` does not exist"))
        == CONFIG_ERROR
    )


# ===========================================================================
# The committed model id — D-A's other half. `o4-mini-deep-research` was the
# CODE DEFAULT and the deploy script never bound the env var, so the deployed
# worker ran on the dead default. Both places are now pinned.
# ===========================================================================


def test_the_committed_openai_deep_research_default_is_not_the_dead_id() -> None:
    """No live code path may resolve to `o4-mini-deep-research`."""
    import os

    from nestor_pulse_sdk.audit import audited_llm_client

    if os.environ.get("NESTOR_OPENAI_DR_MODEL"):
        pytest.skip("NESTOR_OPENAI_DR_MODEL is set in this environment; the DEFAULT is what this asserts")
    assert audited_llm_client.OPENAI_DEEP_RESEARCH_MODEL == "gpt-5.6-sol"


def test_the_resolved_deep_research_models_are_logged_once(caplog: Any) -> None:
    """An operator must be able to READ the configuration, not infer it from failures."""
    import logging

    from nestor_pulse_sdk.audit import audited_llm_client

    audited_llm_client._DR_MODELS_LOGGED = False
    with caplog.at_level(logging.INFO, logger=audited_llm_client.__name__):
        audited_llm_client.log_resolved_dr_models()
        audited_llm_client.log_resolved_dr_models()

    lines = [r for r in caplog.records if "deep-research model" in r.getMessage()]
    assert len(lines) == 1, "once per process, not once per call"
    message = lines[0].getMessage()
    assert audited_llm_client.OPENAI_DEEP_RESEARCH_MODEL in message
    assert audited_llm_client.GEMINI_DEEP_RESEARCH_AGENT in message
