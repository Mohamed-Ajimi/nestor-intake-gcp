"""R2 circuit breaker — the state machine, on an injected clock (Phase 15.2).

WHY: on run 4cbb5311 the same hard failure was re-issued 776 times in 55
seconds. A breaker is the second half of that fix — `with_retry` stops one call
site from hammering, the breaker stops the STAGE from re-entering a provider
that has already said no five times in a row.

The two properties that are easy to get wrong, and are therefore tested hardest:

  1. A PLAIN 429 MUST NEVER TRIP THE CIRCUIT. Rate limiting is not a failure —
     it means the provider is healthy and we are sending too fast. A breaker
     that opens on 429 takes a working provider offline. 100 of them here leave
     the circuit closed.
  2. "IDENTICAL" MUST SURVIVE REQUEST IDS. Without digit stripping, the request
     id embedded in each message makes every error unique, the consecutive
     counter resets forever and the breaker never trips at all — a breaker that
     silently does nothing is worse than no breaker, because it is believed.

NO REAL SLEEPING. `CircuitBreaker` takes an injected `clock`, so the 60-second
open window is exercised by stepping a fake clock by hand. This whole file runs
in milliseconds and calls neither `time.sleep` nor a non-zero `asyncio.sleep`.

Pure tests: hand-written fake exceptions, no network, no DB, no provider key, no
mocking library.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import asyncio

import pytest

from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    BREAKER_OPEN_MAX_S,
    BreakerSet,
    CircuitBreaker,
    CircuitOpenError,
    error_signature,
    with_retry,
)


class _Clock:
    """A hand-cranked monotonic clock. `c.t = 61.0` advances time by fiat."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeHTTPError(Exception):
    def __init__(self, status_code=None, message="", headers=None) -> None:
        super().__init__(message)
        if status_code is not None:
            self.status_code = status_code
        if headers is not None:
            self.headers = headers


def _breaker(clock: _Clock | None = None, **kwargs) -> CircuitBreaker:
    return CircuitBreaker("anthropic", clock=clock or _Clock(), **kwargs)


def _hard_401(message: str = "authentication_error invalid x-api-key"):
    return _FakeHTTPError(401, message)


# ---------------------------------------------------------------------------
# 1. Tripping on consecutive IDENTICAL hard failures.
# ---------------------------------------------------------------------------


def test_five_identical_hard_failures_trip_the_circuit():
    b = _breaker()
    for _ in range(4):
        b.record_failure(_hard_401())
    assert b.state == "closed", "four is not five — do not trip early"
    assert b.allow() is True

    b.record_failure(_hard_401())
    assert b.state == "open"
    assert b.allow() is False
    assert b.consecutive_hard == 5


def test_different_signatures_do_not_trip():
    """The counter RESETS on a changed signature — R2 says IDENTICAL."""
    b = _breaker()
    for message in (
        "invalid model name",
        "unknown field in body",
        "malformed request shape",
        "unsupported parameter foo",
        "bad content type",
    ):
        b.record_failure(_FakeHTTPError(400, message))
    assert b.state == "closed"
    assert b.consecutive_hard == 1, "each new signature restarts the count at 1"


def test_messages_differing_only_by_a_request_id_are_identical():
    """Digit stripping is what makes the breaker able to trip at all."""
    b = _breaker()
    for i in range(5):
        b.record_failure(_hard_401(f"authentication_error invalid key (request req_{i}9271)"))
    assert b.state == "open", (
        "without digit stripping every request id makes each error unique and "
        "the breaker would never trip"
    )
    assert b.consecutive_hard == 5


def test_error_signature_normalises_digits_and_whitespace():
    a = error_signature(_hash_free_error("request 12345 failed"))
    z = error_signature(_hash_free_error("request 98765   failed"))
    assert a == z


def _hash_free_error(message: str):
    return _FakeHTTPError(401, message)


# ---------------------------------------------------------------------------
# 2. The 429 rule — the single most important line in `record_failure`.
# ---------------------------------------------------------------------------


def test_a_hundred_plain_429s_never_trip_the_circuit():
    """Rate limiting is not a failure: the API is healthy, we are too fast."""
    b = _breaker()
    for _ in range(100):
        b.record_failure(_FakeHTTPError(429, "rate limit exceeded"))
    assert b.state == "closed"
    assert b.allow() is True
    assert b.rate_limited == 100, "counted, visibly, but never held against the provider"
    assert b.consecutive_hard == 0
    assert b.overload == 0


# ---------------------------------------------------------------------------
# 3. Hard walls trip on the FIRST occurrence; overload gets a higher threshold.
# ---------------------------------------------------------------------------


def test_a_cap_400_trips_on_the_first_occurrence():
    b = _breaker()
    b.record_failure(_FakeHTTPError(400, "monthly usage cap reached for this account"))
    assert b.state == "open", "waiting for five is how 776 requests went out in 55s"
    assert "account level" in b.reason


def test_a_402_billing_error_trips_on_the_first_occurrence():
    b = _breaker()
    b.record_failure(_FakeHTTPError(402, "billing_error: credit balance too low"))
    assert b.state == "open"


def test_overload_uses_a_separate_higher_threshold():
    """A capacity blip must not kill a research stream."""
    b = _breaker()
    for _ in range(9):
        b.record_failure(_FakeHTTPError(529, "overloaded_error"))
    assert b.state == "closed", "nine 529s is a blip, not a broken provider"
    assert b.overload == 9

    b.record_failure(_FakeHTTPError(529, "overloaded_error"))
    assert b.state == "open"
    assert b.overload == 10


def test_timeouts_count_as_overload_not_as_hard():
    b = _breaker()
    for _ in range(3):
        b.record_failure(asyncio.TimeoutError("read timed out"))
    assert b.overload == 3
    assert b.consecutive_hard == 0
    assert b.state == "closed"


def test_a_transient_5xx_moves_no_counter():
    b = _breaker()
    for _ in range(20):
        b.record_failure(_FakeHTTPError(503, "service unavailable"))
    assert b.state == "closed"
    assert b.consecutive_hard == 0
    assert b.overload == 0


# ---------------------------------------------------------------------------
# 4. open -> half_open -> closed / re-open, on the fake clock.
# ---------------------------------------------------------------------------


def _tripped(clock: _Clock, open_s: float = 60.0) -> CircuitBreaker:
    b = CircuitBreaker("anthropic", clock=clock, open_s=open_s)
    for _ in range(5):
        b.record_failure(_hard_401())
    assert b.state == "open"
    return b


def test_an_open_circuit_refuses_work_for_its_window():
    clock = _Clock()
    b = _tripped(clock)

    assert b.allow() is False
    clock.t = 59.0
    assert b.allow() is False, "the window has not elapsed"
    assert b.state == "open"


def test_exactly_one_half_open_probe_is_allowed_through():
    clock = _Clock()
    b = _tripped(clock)

    clock.t = 61.0
    assert b.state == "half_open"
    assert b.allow() is True, "one probe decides whether the provider is back"
    assert b.allow() is False, "a second concurrent caller must NOT get a probe too"
    assert b.allow() is False


def test_a_successful_probe_closes_the_circuit_and_zeroes_the_counters():
    clock = _Clock()
    b = _tripped(clock)
    clock.t = 61.0
    assert b.allow() is True

    b.record_success()
    assert b.state == "closed"
    assert b.consecutive_hard == 0
    assert b.overload == 0
    assert b.signature is None
    assert b.reason == ""
    assert b.allow() is True


def test_a_failed_probe_reopens_for_twice_as_long():
    clock = _Clock()
    b = _tripped(clock, open_s=60.0)
    first_window = b.retry_at - b.opened_at
    assert first_window == 60.0

    clock.t = 61.0
    assert b.allow() is True  # take the probe
    b.record_failure(_hard_401())

    assert b.state == "open"
    assert b.retry_at - b.opened_at == 120.0, "the window doubles on re-open"
    assert b.allow() is False


def test_the_open_window_escalation_is_capped():
    clock = _Clock()
    b = CircuitBreaker("anthropic", clock=clock, open_s=60.0, max_open_s=BREAKER_OPEN_MAX_S)
    for cycle in range(1, 8):
        b.trip(f"cycle {cycle}")
        window = b.retry_at - b.opened_at
        assert window <= BREAKER_OPEN_MAX_S
        clock.t = b.retry_at + 1.0
        assert b.allow() is True
    assert b.retry_at - b.opened_at == BREAKER_OPEN_MAX_S, "capped at 600s, not unbounded"


def test_a_transient_failure_during_the_probe_also_reopens():
    """The probe is the question "is the provider back?" — any failure is a no."""
    clock = _Clock()
    b = _tripped(clock)
    clock.t = 61.0
    assert b.allow() is True

    b.record_failure(_FakeHTTPError(503, "service unavailable"))
    assert b.state == "open"
    assert "recovery probe" in b.reason


def test_a_429_during_the_probe_does_not_reopen():
    """Even here, a 429 is not evidence that the provider is broken."""
    clock = _Clock()
    b = _tripped(clock)
    clock.t = 61.0
    assert b.allow() is True

    b.record_failure(_FakeHTTPError(429, "rate limit exceeded"))
    assert b.rate_limited == 1
    assert b.state == "half_open", "still awaiting a verdict on the probe"


# ---------------------------------------------------------------------------
# 5. force_open — plan 15.2-12's "SERPAPI_API_KEY absent" startup seam.
# ---------------------------------------------------------------------------


def test_force_open_refuses_work_and_names_the_reason_verbatim():
    clock = _Clock()
    b = CircuitBreaker("serpapi", clock=clock)
    b.force_open("SERPAPI_API_KEY not configured")

    assert b.allow() is False
    assert b.snapshot()["reason"] == "SERPAPI_API_KEY not configured"
    assert b.snapshot()["state"] == "open"


def test_force_open_reason_reaches_the_breaker_set_degradation_list():
    """This is what makes a missing secret a clean 3-stream degraded run."""
    clock = _Clock()
    breakers = BreakerSet(clock=clock)
    breakers.get("serpapi").force_open("SERPAPI_API_KEY not configured")

    assert breakers.open_providers() == ["serpapi"]
    assert breakers.reasons() == ["SERPAPI_API_KEY not configured"]


def test_breaker_set_creates_on_demand_and_keeps_them_separate():
    clock = _Clock()
    breakers = BreakerSet(clock=clock)
    anthropic = breakers.get("anthropic")

    assert breakers.get("anthropic") is anthropic, "one breaker per provider name"
    breakers.get("gemini")
    assert set(breakers.all()) == {"anthropic", "gemini"}

    for _ in range(5):
        anthropic.record_failure(_hard_401())
    assert breakers.open_providers() == ["anthropic"]
    assert breakers.get("gemini").allow() is True, "one provider's wall is not another's"


def test_snapshot_is_plain_json_safe_data():
    b = _breaker()
    b.record_failure(_FakeHTTPError(429, "slow down"))
    snap = b.snapshot()

    assert set(snap) == {
        "provider",
        "state",
        "reason",
        "consecutive_hard",
        "overload",
        "rate_limited",
        "opened_at",
        "retry_at",
    }
    for value in snap.values():
        assert isinstance(value, (str, int, float)), "the feed serialises this as JSON"


# ---------------------------------------------------------------------------
# 6. Secrets never reach a signature, a log line or the feed (T-15.2-02).
# ---------------------------------------------------------------------------


def test_error_signature_redacts_an_api_key():
    """A SerpApi failure carries the key in the query string."""
    exc = _FakeHTTPError(401, "unauthorized for search?api_key=abc123secret")
    signature = error_signature(exc)

    assert "abc123secret" not in signature
    assert "<redacted>" in signature
    assert signature.startswith("401|")


def test_error_signature_is_bounded_in_length():
    exc = _FakeHTTPError(500, "x" * 5000)
    signature = error_signature(exc)
    assert len(signature) < 200, "signatures are logged and fed — they stay small"


def test_error_signature_never_raises():
    class _Hostile(Exception):
        def __str__(self):  # noqa: D105
            raise RuntimeError("boom")

    assert error_signature(_Hostile()) == "none|<unprintable>"


# ---------------------------------------------------------------------------
# 7. The with_retry <-> breaker seam.
# ---------------------------------------------------------------------------


class _Counter:
    def __init__(self, exc: BaseException, fail_times: int = 10**6) -> None:
        self.exc = exc
        self.fail_times = fail_times
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return "ok"


async def test_an_open_circuit_costs_zero_calls():
    """The whole point: an open circuit sends NOTHING and bills NOTHING."""
    clock = _Clock()
    b = _tripped(clock)
    fn = _Counter(_hard_401())

    with pytest.raises(CircuitOpenError) as caught:
        await with_retry(fn, attempts=4, base_s=0.0, label="skeptic", breaker=b)

    assert fn.calls == 0, "no call was made at all"
    assert caught.value.provider == "anthropic"
    assert "circuit open" in str(caught.value)


async def test_with_retry_records_the_hard_wall_on_the_breaker():
    clock = _Clock()
    b = CircuitBreaker("anthropic", clock=clock)
    fn = _Counter(_FakeHTTPError(400, "monthly usage cap reached"))

    with pytest.raises(_FakeHTTPError):
        await with_retry(fn, attempts=4, base_s=0.0, breaker=b)

    assert fn.calls == 1, "a hard wall is never retried"
    assert b.state == "open", "and it trips the circuit on the first occurrence"


async def test_with_retry_records_success_and_closes_the_breaker():
    clock = _Clock()
    b = CircuitBreaker("anthropic", clock=clock)
    for _ in range(3):
        b.record_failure(_hard_401())
    assert b.consecutive_hard == 3

    fn = _Counter(_hard_401(), fail_times=0)
    assert await with_retry(fn, attempts=4, base_s=0.0, breaker=b) == "ok"
    assert b.consecutive_hard == 0, "a success clears the run of bad luck"
    assert b.state == "closed"


async def test_a_breaker_that_misbehaves_does_not_break_the_call():
    """Reliability plumbing must never be the thing that fails a run."""

    class _BrokenBreaker:
        def raise_if_open(self):
            return None

        def record_success(self):
            raise RuntimeError("breaker exploded")

        def record_failure(self, exc):
            raise RuntimeError("breaker exploded")

    fn = _Counter(_hard_401(), fail_times=0)
    assert await with_retry(fn, attempts=2, base_s=0.0, breaker=_BrokenBreaker()) == "ok"
