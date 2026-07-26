"""R1 retry policy — classification, backoff, retry-after, pause_turn (Phase 15.2).

WHY THIS FILE EXISTS: on run 4cbb5311 (2026-07-22) the fact-checking stage issued
776 hard HTTP 400s in 55 seconds against an account that had already hit its
monthly usage cap. The account-level refusal was retried as if it were a blip.
`test_reliability_retry.py::test_cap_400_costs_exactly_one_attempt` is that
incident turned into a gate (T-15.2-01): a hard wall costs exactly ONE call, and
if that ever regresses this test goes red before any money is spent.

Also gates the CI config itself (T-15.2-06). `cloudbuild.test-engine.yaml` builds
its file list with `ls ... || true`, so a dropped or misnamed entry makes the gate
go green having run nothing. The last test in this file asserts that all 22
planned 15.2 test paths, the `-m "not live"` marker filter and the `|| true`
guard are still present in that YAML — which is what makes "no later plan edits
this config" enforceable rather than merely written down.

Pure tests: hand-written fake exceptions and counter-driven async callables. No
network, no DB, no provider key, no mocking library. `asyncio_mode = "auto"`
(tribunal/pyproject.toml) so plain `async def test_...` is enough.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import asyncio
import random
from pathlib import Path

import pytest

from nestor_pulse_sdk.pipeline.tribunal import reliability
from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    HARD,
    HARD_WALL,
    OVERLOAD,
    RATE_LIMIT,
    RETRY_AFTER_MAX_S,
    TRANSIENT,
    PauseContinuation,
    classify,
    is_pause_turn,
    is_transient,
    retry_after,
    with_retry,
)

# ---------------------------------------------------------------------------
# Fakes. A provider exception is anything carrying a status and maybe headers;
# duck typing is all `_status_of` and `retry_after` ever look at.
# ---------------------------------------------------------------------------


class _FakeHTTPError(Exception):
    """Duck-types the shape every provider SDK exception shares."""

    def __init__(self, status_code=None, message="", headers=None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if headers is not None:
            self.headers = headers


class _FakeResponse:
    """A provider response — only `stop_reason` matters to the pause helper."""

    def __init__(self, stop_reason: str) -> None:
        self.stop_reason = stop_reason


class _Counter:
    """An async callable that fails `fail_times` times, then succeeds."""

    def __init__(self, exc: BaseException, fail_times: int = 10**6, result="ok") -> None:
        self.exc = exc
        self.fail_times = fail_times
        self.result = result
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return self.result


# ---------------------------------------------------------------------------
# 1. Classification. Every rung of `classify`, and the `is_transient` answer that
#    decides whether a second call is ever made.
# ---------------------------------------------------------------------------

_CLASSIFICATION_TABLE = [
    # (exception, expected class, expected is_transient)
    (_FakeHTTPError(429, "rate limit exceeded for requests"), RATE_LIMIT, True),
    (_FakeHTTPError(529, "overloaded_error: the API is temporarily overloaded"), OVERLOAD, True),
    (_FakeHTTPError(503, "service unavailable"), TRANSIENT, True),
    (asyncio.TimeoutError("read timed out"), OVERLOAD, True),
    (ConnectionError("connection reset by peer"), OVERLOAD, True),
    (_FakeHTTPError(400, "monthly usage cap reached for this account"), HARD_WALL, False),
    (_FakeHTTPError(402, "billing_error: your credit balance is too low"), HARD_WALL, False),
    (_FakeHTTPError(401, "authentication_error: invalid x-api-key"), HARD, False),
    (_FakeHTTPError(403, "permission_error: not allowed"), HARD, False),
    (_FakeHTTPError(404, "not_found_error: unknown model"), HARD, False),
    (Exception("weird"), HARD, False),
]


@pytest.mark.parametrize(
    "exc,expected_class,expected_transient",
    _CLASSIFICATION_TABLE,
    ids=[f"{e[1]}-{type(e[0]).__name__}-{i}" for i, e in enumerate(_CLASSIFICATION_TABLE)],
)
def test_classification_table(exc, expected_class, expected_transient):
    """429/529/5xx/timeouts retry; cap-400, 402, 401, 403, 404 and the unknown do not."""
    assert classify(exc) == expected_class
    assert is_transient(exc) is expected_transient


def test_unknown_exception_fails_closed():
    """An unrecognised error costs ONE attempt, not a storm (fail closed)."""
    assert classify(Exception("something nobody has seen before")) == HARD
    assert is_transient(Exception("something nobody has seen before")) is False


def test_402_is_a_hard_wall_even_without_cap_wording():
    """402 billing_error is the documented "credits exhausted" code — D-17 parks on it."""
    assert classify(_FakeHTTPError(402, "payment required")) == HARD_WALL


def test_429_is_never_a_hard_wall():
    """A 429 means the provider is healthy and we are too fast — retry, never park."""
    assert classify(_FakeHTTPError(429, "too many requests")) == RATE_LIMIT


def test_classify_never_raises_on_a_hostile_exception():
    class _Hostile(Exception):
        def __str__(self):  # noqa: D105 — deliberately explodes
            raise RuntimeError("boom")

    assert classify(_Hostile()) == HARD


# ---------------------------------------------------------------------------
# 2. with_retry — the transient path, the exhaustion path, and the hard wall.
# ---------------------------------------------------------------------------


async def test_transient_failure_is_retried_then_succeeds():
    fn = _Counter(_FakeHTTPError(503, "service unavailable"), fail_times=2)
    result = await with_retry(fn, attempts=4, base_s=0.0, label="test")
    assert result == "ok"
    assert fn.calls == 3, "two failures then a success is three calls"


async def test_exhaustion_makes_exactly_attempts_calls_and_reraises():
    fn = _Counter(_FakeHTTPError(503, "service unavailable"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0, label="test")
    assert fn.calls == 4, "attempts is TOTAL calls, not extra ones"


async def test_with_retry_never_returns_none_on_exhaustion():
    """T-15.2-05: exhaustion re-raises. It must never degrade to a silent None."""
    fn = _Counter(_FakeHTTPError(500, "internal error"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=2, base_s=0.0)


async def test_cap_400_costs_exactly_one_attempt():
    """THE 776-ERROR REGRESSION GATE (T-15.2-01). A cap-400 is never retried."""
    fn = _Counter(_FakeHTTPError(400, "monthly usage cap reached for this account"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0, label="skeptic")
    assert fn.calls == 1, (
        "a usage-cap 400 is a statement about the ACCOUNT — retrying it can only "
        "produce more 400s, faster (776 in 55 seconds on run 4cbb5311)"
    )


async def test_402_costs_exactly_one_attempt():
    fn = _Counter(_FakeHTTPError(402, "billing_error: credit balance too low"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0)
    assert fn.calls == 1


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_other_hard_statuses_cost_exactly_one_attempt(status):
    fn = _Counter(_FakeHTTPError(status, "hard refusal"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0)
    assert fn.calls == 1


async def test_success_on_the_first_call_makes_one_call():
    fn = _Counter(Exception("never raised"), fail_times=0)
    assert await with_retry(fn, attempts=4, base_s=0.0) == "ok"
    assert fn.calls == 1


# ---------------------------------------------------------------------------
# 3. Backoff — full jitter, and the retry-after override.
# ---------------------------------------------------------------------------


async def _waits_for(exc, *, attempts=4, base_s=0.0):
    """Run the retry path to exhaustion and collect the wait each retry chose."""
    seen: list[tuple[int, int, float, str]] = []

    async def _on_retry(attempt, maximum, wait_s, label):
        seen.append((attempt, maximum, wait_s, label))

    fn = _Counter(exc)
    with pytest.raises(Exception):
        await with_retry(
            fn, attempts=attempts, base_s=base_s, on_retry=_on_retry, label="jit"
        )
    return seen


async def test_full_jitter_stays_inside_the_exponential_ceiling(monkeypatch):
    """`sleep = uniform(0, base * 2**n)` — never above the ceiling, never negative.

    529 is a GLOBAL capacity signal: if every client backed off to exactly the
    same instant they would all land in the same overload window. Jitter is the
    fix, so the bound is what is asserted, not a fixed number.

    `asyncio.sleep` is stubbed out so a large `base_s` costs no wall clock.
    """
    slept: list[float] = []

    async def _no_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(reliability.asyncio, "sleep", _no_sleep)
    random.seed(1234)

    base_s = 8.0
    seen = await _waits_for(
        _FakeHTTPError(503, "service unavailable"), attempts=4, base_s=base_s
    )

    assert len(seen) == 3, "4 attempts means 3 retries"
    for attempt, _maximum, wait_s, _label in seen:
        ceiling = base_s * (2 ** (attempt - 1))
        assert 0.0 <= wait_s <= ceiling, f"attempt {attempt}: {wait_s} outside [0,{ceiling}]"
    assert slept == [w for _, _, w, _ in seen], "the chosen wait is the wait slept"


async def test_jitter_can_be_switched_off_from_the_environment(monkeypatch):
    """NESTOR_TRIBUNAL_RETRY_JITTER=false gives the plain deterministic ramp."""
    monkeypatch.setattr(reliability, "RETRY_JITTER", False)

    async def _no_sleep(seconds):
        return None

    monkeypatch.setattr(reliability.asyncio, "sleep", _no_sleep)
    seen = await _waits_for(
        _FakeHTTPError(503, "service unavailable"), attempts=3, base_s=2.0
    )
    assert [w for _, _, w, _ in seen] == [2.0, 4.0]


def test_retry_after_numeric_header_is_honoured():
    assert retry_after(_FakeHTTPError(429, "slow down", headers={"retry-after": "7"})) == 7.0


def test_retry_after_is_case_insensitive():
    assert retry_after(_FakeHTTPError(429, "slow down", headers={"Retry-After": "5"})) == 5.0


def test_retry_after_reads_a_nested_response_headers():
    class _Resp:
        headers = {"retry-after": "3"}

    exc = _FakeHTTPError(429, "slow down")
    exc.response = _Resp()
    assert retry_after(exc) == 3.0


def test_retry_after_http_date_form_is_ignored():
    """An HTTP-date is not parsed — return None and use the computed backoff."""
    exc = _FakeHTTPError(429, "slow", headers={"retry-after": "Wed, 21 Oct 2026 07:28:00 GMT"})
    assert retry_after(exc) is None


def test_retry_after_is_clamped():
    """T-15.2-03: an unclamped provider-supplied sleep is a DoS vector."""
    exc = _FakeHTTPError(429, "slow", headers={"retry-after": "99999"})
    assert retry_after(exc) == RETRY_AFTER_MAX_S
    assert retry_after(exc) == 300.0


def test_retry_after_negative_is_floored_and_garbage_is_none():
    assert retry_after(_FakeHTTPError(429, "x", headers={"retry-after": "-5"})) == 0.0
    assert retry_after(_FakeHTTPError(429, "x", headers={"retry-after": "soon"})) is None
    assert retry_after(_FakeHTTPError(429, "x", headers={"retry-after": "nan"})) is None
    assert retry_after(_FakeHTTPError(429, "x")) is None
    assert retry_after(Exception("no headers at all")) is None


def test_retry_after_bare_attribute():
    exc = _FakeHTTPError(429, "slow")
    exc.retry_after = 11
    assert retry_after(exc) == 11.0


async def test_retry_after_wins_over_the_computed_backoff(monkeypatch):
    slept: list[float] = []

    async def _no_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(reliability.asyncio, "sleep", _no_sleep)
    exc = _FakeHTTPError(429, "rate limited", headers={"retry-after": "7"})
    seen = await _waits_for(exc, attempts=3, base_s=100.0)

    assert [w for _, _, w, _ in seen] == [7.0, 7.0], (
        "Anthropic's documented rule: a provider-supplied retry-after wins"
    )
    assert slept == [7.0, 7.0]


# ---------------------------------------------------------------------------
# 4. on_retry — the R5 feed callback. Best-effort, never load-bearing.
# ---------------------------------------------------------------------------


async def test_on_retry_receives_attempt_max_wait_and_label():
    seen = await _waits_for(_FakeHTTPError(503, "unavailable"), attempts=3, base_s=0.0)
    assert [(a, m, lbl) for a, m, _w, lbl in seen] == [(1, 3, "jit"), (2, 3, "jit")]
    assert all(isinstance(w, float) for _a, _m, w, _lbl in seen)


async def test_a_raising_on_retry_does_not_break_with_retry():
    """A feed write is best-effort (Shared Pattern 6); the RETRY is not."""

    async def _boom(*_args):
        raise RuntimeError("stage feed is down")

    fn = _Counter(_FakeHTTPError(503, "unavailable"), fail_times=1)
    assert await with_retry(fn, attempts=3, base_s=0.0, on_retry=_boom) == "ok"
    assert fn.calls == 2


async def test_a_synchronous_on_retry_is_accepted():
    seen: list[int] = []
    fn = _Counter(_FakeHTTPError(503, "unavailable"), fail_times=1)
    await with_retry(
        fn,
        attempts=3,
        base_s=0.0,
        on_retry=lambda attempt, maximum, wait_s, label: seen.append(attempt),
    )
    assert seen == [1]


async def test_on_retry_is_not_called_for_a_hard_wall():
    """A hard wall is not a retry, so no `retry` row is written to the feed."""
    seen: list[int] = []

    async def _on_retry(attempt, maximum, wait_s, label):
        seen.append(attempt)

    fn = _Counter(_FakeHTTPError(400, "monthly usage cap reached"))
    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0, on_retry=_on_retry)
    assert seen == []


# ---------------------------------------------------------------------------
# 5. F8 — the bounded pause_turn continuation.
# ---------------------------------------------------------------------------


def test_is_pause_turn_reads_stop_reason_defensively():
    assert is_pause_turn(_FakeResponse("pause_turn")) is True
    assert is_pause_turn(_FakeResponse("PAUSE_TURN")) is True
    assert is_pause_turn(_FakeResponse("tool_use")) is False
    assert is_pause_turn(_FakeResponse("")) is False
    assert is_pause_turn(object()) is False
    assert is_pause_turn(None) is False


def test_pause_continuation_is_bounded():
    """T-15.2-04: a hostile or buggy stream cannot drive an unbounded billed loop."""
    pause = PauseContinuation(max_pauses=3, label="group_skeptic")
    paused = _FakeResponse("pause_turn")

    assert [pause.consume(paused) for _ in range(3)] == [True, True, True]
    assert pause.used == 3
    assert pause.consume(paused) is False, "budget spent — the caller's failure path takes over"
    assert pause.used == 3, "a refused continuation does not spend budget"


def test_a_non_pause_stop_reason_does_not_consume_budget():
    pause = PauseContinuation(max_pauses=3)
    assert pause.consume(_FakeResponse("tool_use")) is False
    assert pause.consume(_FakeResponse("end_turn")) is False
    assert pause.used == 0
    assert pause.consume(_FakeResponse("pause_turn")) is True
    assert pause.used == 1


def test_pause_continuation_default_budget_is_env_tunable():
    assert PauseContinuation().max_pauses == reliability.MAX_PAUSE_CONTINUATIONS
    assert PauseContinuation(max_pauses=0).consume(_FakeResponse("pause_turn")) is False


# ---------------------------------------------------------------------------
# 6. Secret redaction in anything destined for a log line or the feed.
# ---------------------------------------------------------------------------


def test_redact_removes_credentials():
    """T-15.2-02: a SerpApi failure message can carry the key in a query string."""
    dirty = "HTTPError 401 for https://serpapi.com/search?q=lukoil&api_key=abc123secret"
    clean = reliability.redact(dirty)
    assert "abc123secret" not in clean
    assert "<redacted>" in clean
    assert "serpapi.com" in clean, "redaction must not destroy the diagnostic context"


def test_redact_handles_bearer_and_authorization():
    assert "sk-livekey123456" not in reliability.redact("authorization: Bearer sk-livekey123456")
    assert "sk-livekey123456" not in reliability.redact("Bearer sk-livekey123456")
    assert "hunter2hunter2" not in reliability.redact("password=hunter2hunter2")


def test_redact_never_raises():
    class _Hostile:
        def __str__(self):  # noqa: D105
            raise RuntimeError("boom")

    assert reliability.redact(_Hostile()) == "<unprintable>"


# ---------------------------------------------------------------------------
# 7. The CI-gate config guard (T-15.2-06).
#
# `cloudbuild.test-engine.yaml` builds its file list with `ls ... || true`, so a
# dropped entry, a typo or a removed marker filter does not fail the build — the
# gate just runs less, or runs something that costs money. These assertions are
# what make plan 15.2-02's exclusive ownership of that config enforceable.
# ---------------------------------------------------------------------------

# The 22 paths pre-registered in the engine gate: 19 new 15.2 files plus the 3
# existing pure files 15.2 extends. Deliberately duplicated here rather than
# parsed out of the YAML — a guard that derives its expectation from the artifact
# it guards cannot detect a deletion.
_PHASE_15_2_TEST_FILES: tuple[str, ...] = (
    "test_reliability_retry.py",
    "test_reliability_breaker.py",
    "test_terminal_states.py",
    "test_feed_enrichment.py",
    "test_fact_list_parser.py",
    "test_citation_anchors.py",
    "test_report_sections.py",
    "test_status_gates.py",
    "test_coverage_reentry.py",
    "test_workshop_critique.py",
    "test_workshop_scope_guard.py",
    "test_workshop_tournament.py",
    "test_workshop_languages.py",
    "test_own_researcher.py",
    "test_cost_serpapi.py",
    "test_factlist_fallback.py",
    "test_checkpoint_resume.py",
    "test_provider_resume.py",
    "test_engine_e2e_stubbed.py",
    "test_research_division_assignment.py",
    "test_distiller_coverage.py",
    "test_hash_chain_replay.py",
)

# tests -> nestor_pulse_sdk -> tribunal. Resolved from __file__, never from a
# repo-root-relative path: Cloud Build mounts `tribunal/` AS /workspace, so a
# path built from the repo root does not exist inside the container.
_ENGINE_GATE = Path(__file__).resolve().parents[2] / "cloudbuild.test-engine.yaml"


def test_engine_gate_config_exists():
    assert _ENGINE_GATE.is_file(), (
        f"{_ENGINE_GATE} is missing — phase 15.2 has no runnable gate without it"
    )


def test_engine_gate_filters_out_live_tests():
    """LOAD-BEARING: pyproject only REGISTERS the `live` marker; it does not deselect it."""
    text = _ENGINE_GATE.read_text(encoding="utf-8")
    assert '-m "not live"' in text, (
        "without this filter a live-marked test fires a real LLM call from CI, "
        "against an account at its monthly cap (resets 2026-08-01)"
    )


def test_engine_gate_tolerates_not_yet_created_files():
    text = _ENGINE_GATE.read_text(encoding="utf-8")
    assert "|| true" in text, (
        "under `set -e` a bare FILES=$(ls missing-file) aborts the script; the "
        "guard is what lets wave 1 pre-register the files waves 2-11 add"
    )


@pytest.mark.parametrize("filename", _PHASE_15_2_TEST_FILES)
def test_engine_gate_pre_registers_every_planned_test_file(filename):
    """No later 15.2 plan edits that config, so every planned file is listed NOW."""
    text = _ENGINE_GATE.read_text(encoding="utf-8")
    assert f"nestor_pulse_sdk/tests/{filename}" in text, (
        f"{filename} is not listed in cloudbuild.test-engine.yaml — the `|| true` "
        f"guard means it would be silently skipped and the gate would go green "
        f"having never run it"
    )


def test_engine_gate_provisions_no_database_and_consumes_no_secret():
    text = _ENGINE_GATE.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("#")
    )
    for forbidden in ("POSTGRES", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "SERPAPI"):
        assert forbidden not in code, (
            f"the 15.2 fast gate must stay keyless and DB-less; found {forbidden}"
        )


def test_engine_gate_lists_files_explicitly_not_by_glob():
    text = _ENGINE_GATE.read_text(encoding="utf-8")
    assert "tests/*.py" not in text and "test_*.py" not in text, (
        "the explicit list is what keeps DB-bound and unrelated suite files out "
        "of this fast gate"
    )
