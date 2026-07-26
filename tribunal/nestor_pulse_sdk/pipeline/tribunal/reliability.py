"""Shared reliability primitives for the research engine — Phase 15.2 (R1/R2/R4/R6/F8).

WHAT THIS IS: an EXTRACTION, not an invention. `_status_of`, `_CAP_MARKERS`,
`_TRANSIENT_MARKERS` and `_is_transient` were written for `gates.py` (lines
261-345) in phase 15.1 and are moved here verbatim, comments and incident
docstring included. `gates.py` keeps a thin re-export so the two tests that
address those names through `gates.` keep resolving.

WHY IT IS A MODULE. Phase 15.2's dominant failure mode is building a SECOND
retry policy. There is exactly one, and it lives here: plans 15.2-07, -10, -12
and -16 import `with_retry` / `CircuitBreaker` / `PauseContinuation` /
`terminal_state` from this module rather than writing their own loop. If you are
about to add an `except ... : await asyncio.sleep(...)` retry anywhere in the
pipeline, use `with_retry` instead.

WHAT IS DELIBERATELY NOT HERE:
  - No provider client, and no `audit/` import. This module never performs LLM
    egress, so it cannot break the EU AI Act Art. 12 audit hash chain. All LLM
    egress stays in `audited.*` (phase rule 1).
  - No `tenacity` (pinned but deliberately unused), no `pybreaker`, no agent
    framework. Hand-written async loops are the Tribunal convention, and no
    package is added by this phase.
  - No database and no persistence. Breaker state is in-process and run-scoped.
  - `_gate_batch` is NOT migrated onto `with_retry`. Its inline loop and its
    `_GATE_RETRIES` / `_GATE_BACKOFF_S` knobs stay exactly as they are, because
    `test_gate_failure_modes.py:40` and `test_gate_replay.py:75` monkeypatch
    `gates._GATE_BACKOFF_S = 0.0` and rewiring that seam would break it
    silently. Migrating the gate is out of scope for phase 15.2.

EVERY PARAMETER IS ENV-TUNABLE via the `NESTOR_TRIBUNAL_*` idiom. RESEARCH rates
the breaker numbers MEDIUM confidence (community consensus, not vendor
documentation), so the August live run is what calibrates them — and retuning
must not require a code change or a new image.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import Any, Callable

log = logging.getLogger(__name__)

# Same NESTOR_TRIBUNAL_* + os.environ.get(..., default) idiom as gates.py:76-81
# and grouping.py:97-100, so a tuning change needs no code change to deploy.
#   RETRY_ATTEMPTS          TOTAL attempts, not extra ones (1 initial + 3 retries).
#                           R1 says "~3-5"; Anthropic's own SDKs retry twice by
#                           default, and gates.py already uses 3 total for the
#                           cheap classification calls. 4 for the expensive
#                           skeptic/research calls.
#   RETRY_BASE_S            base sleep; attempt N waits base * 2**N (2/4/8 s).
#   RETRY_JITTER            FULL jitter on/off. On by default: 529 is a GLOBAL
#                           capacity signal, and naive exponential backoff lands
#                           every retrying client in the same overload window.
#   RETRY_AFTER_MAX_S       ceiling on a provider-supplied retry-after. An
#                           unclamped one is a denial-of-service vector.
#   MAX_PAUSE_CONTINUATIONS bounded budget for F8 `pause_turn` continuations.
RETRY_ATTEMPTS = int(os.environ.get("NESTOR_TRIBUNAL_RETRY_ATTEMPTS", "4"))
RETRY_BASE_S = float(os.environ.get("NESTOR_TRIBUNAL_RETRY_BASE_S", "2.0"))
RETRY_JITTER = os.environ.get("NESTOR_TRIBUNAL_RETRY_JITTER", "true").lower() == "true"
RETRY_AFTER_MAX_S = float(os.environ.get("NESTOR_TRIBUNAL_RETRY_AFTER_MAX_S", "300"))
MAX_PAUSE_CONTINUATIONS = int(
    os.environ.get("NESTOR_TRIBUNAL_MAX_PAUSE_CONTINUATIONS", "3")
)


# ---------------------------------------------------------------------------
# Secret redaction. Exception messages are third-party data and they can carry a
# credential: SerpApi's key rides in a query string, so a failed-request repr can
# contain it verbatim. Signatures and retry log lines are written to logs and to
# the operator feed, so they must be safe to display (T-15.2-02).
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    # key=value / key: value forms, including api_key, api-key, apikey, token,
    # secret, password. The value runs to the next separator so a query string
    # ("...&q=lukoil") does not swallow the rest of the URL.
    re.compile(
        r"(?i)\b(?:api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
        r"secret[_-]?key|client[_-]?secret|token|secret|password|passwd|pwd|key)\b"
        r"\s*[:=]\s*[^\s&;,)\"'|]+"
    ),
    # Authorization headers, with or without a scheme word.
    re.compile(r"(?i)\bauthorization\b\s*[:=]?\s*(?:bearer|basic)?\s*[^\s;,)\"'|]+"),
    re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._\-+/=]{8,}"),
)

_REDACTED = "<redacted>"


def redact(text: str) -> str:
    """Replace anything that looks like a credential with `<redacted>`.

    Best-effort and never raises: a failure to redact must not turn into a
    failure to report. Called BEFORE truncation, so a long key cannot survive by
    being cut in half.
    """
    try:
        out = str(text)
        for pattern in _SECRET_PATTERNS:
            out = pattern.sub(_REDACTED, out)
        return out
    except Exception:  # noqa: BLE001 — redaction is best-effort by design
        return "<unprintable>"


# ---------------------------------------------------------------------------
# R1 — retry classification. MOVED VERBATIM from gates.py:261-345.
# ---------------------------------------------------------------------------


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status from a provider exception, or None."""
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            m = re.fullmatch(r"\s*(\d{3})\s*", value.strip())
            if m:
                return int(m.group(1))
    return None


# Wording that marks a HARD account-level refusal rather than a transient blip.
# Deliberately specific phrases: "cap" alone would match "capability"/"capacity"
# in ordinary claim-bearing error text.
_CAP_MARKERS = (
    "usage limit",
    "usage cap",
    "monthly limit",
    "monthly cap",
    "spend limit",
    "hard cap",
    "credit balance",
    "out of credit",
    "insufficient_quota",
    "insufficient quota",
    "quota exceeded",
    "exceeded your",
    "billing",
)

# Signals of a genuinely transient failure when the exception carries no status.
_TRANSIENT_MARKERS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "connection reset",
    "connection aborted",
    "connection refused",
    "temporarily unavailable",
    "service unavailable",
    "overloaded",
    "try again",
)


def is_transient(exc: BaseException) -> bool:
    """Retry predicate: True only for failures that a second attempt could fix.

    THE 776-ERROR INCIDENT. On run 4cbb5311 (2026-07-22) the fact-checking stage
    kept re-issuing calls against an account that had already hit its monthly
    usage cap: 776 hard HTTP 400s in 55 seconds, no result, and the run's
    verification silently covering only 198 of 1,162 claims. A cap 400 is a
    STATEMENT ABOUT THE ACCOUNT, not a blip — retrying it can only produce more
    400s, faster. So: cap/billing wording is never transient, 4xx is never
    transient, and only 429 / 5xx / timeouts / connection resets are retried.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True

    msg = f"{type(exc).__name__} {exc}".lower()

    # Hard account refusal — never retried, whatever status it claims to carry.
    if any(marker in msg for marker in _CAP_MARKERS):
        return False

    status = _status_of(exc)
    if status is not None:
        if status == 429:
            return True
        return 500 <= status < 600

    # No status on the exception: sniff the message for transient signals only.
    # Anything unrecognised is treated as NON-transient, so an unknown hard error
    # costs one attempt instead of a storm.
    if "400" in msg:
        return False
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


# The private spelling stays bound: `gates.py` re-exports it under this name and
# `test_gate_replay.py:228` names `gates._is_transient` in a docstring.
_is_transient = is_transient


# ---------------------------------------------------------------------------
# The failure taxonomy. `is_transient` answers "retry?"; `classify` answers "what
# KIND of failure was that?", which is what the breaker and D-17 need — a plain
# 429 and an exhausted account are both "not a success" and must be treated
# completely differently.
# ---------------------------------------------------------------------------

TRANSIENT = "transient"
RATE_LIMIT = "rate_limit"
OVERLOAD = "overload"
HARD = "hard"
HARD_WALL = "hard_wall"

FAILURE_CLASSES: tuple[str, ...] = (TRANSIENT, RATE_LIMIT, OVERLOAD, HARD, HARD_WALL)


def classify(exc: BaseException) -> str:
    """Classify a provider failure into one of `FAILURE_CLASSES`. Never raises.

    Evaluation order, and why each rung sits where it does:

      (a) HARD_WALL — cap/billing wording, or HTTP 402. 402 `billing_error` is
          Anthropic's documented "credits exhausted" code and is NEW to this
          codebase; D-17 makes it a PARK trigger, not a degrade trigger. A hard
          wall is a statement about the account: it trips the breaker on its
          FIRST occurrence and is never retried.
      (b) RATE_LIMIT — HTTP 429. Rate limiting is not a failure: it means the
          provider is healthy and we are sending too fast. It IS retried and it
          must NEVER trip the breaker.
      (c) OVERLOAD — HTTP 529, timeouts, connection errors. Genuine capacity
          trouble across all users. Retried, and counted against the breaker's
          separate HIGHER threshold so a capacity blip does not kill a stream.
      (d) TRANSIENT — anything else `is_transient` accepts (5xx, transient
          wording).
      (e) HARD — everything else: 400/401/403/404/413 and any unrecognised
          exception. FAIL CLOSED — an unknown error costs one attempt, not a
          storm.
    """
    try:
        msg = f"{type(exc).__name__} {exc}".lower()
        status = _status_of(exc)

        if any(marker in msg for marker in _CAP_MARKERS) or status == 402:
            return HARD_WALL
        if status == 429:
            return RATE_LIMIT
        if status == 529 or isinstance(
            exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)
        ):
            return OVERLOAD
        if is_transient(exc):
            return TRANSIENT
        return HARD
    except Exception:  # noqa: BLE001 — a classifier that raises is worse than a wrong class
        return HARD


def retry_after(exc: BaseException) -> float | None:
    """Seconds the provider asked us to wait, or None. Best-effort, never raises.

    Anthropic's documented rule is that a provider-supplied `retry-after` WINS
    over any computed backoff, so this is consulted on every retry. Looked for in
    `exc.headers`, in `exc.response.headers`, then in a bare `exc.retry_after`.

    SECURITY (T-15.2-03): the result is CLAMPED to `[0, RETRY_AFTER_MAX_S]`
    (300 s by default, env-tunable). An unclamped provider- or MITM-supplied
    sleep is a denial-of-service vector — `Retry-After: 999999` would park a
    worker for eleven days. Only a plain non-negative number of seconds is
    accepted; the HTTP-date form returns None and the caller falls back to the
    computed jittered backoff (ASVS V5: never trust third-party text, never
    raise from the parser).
    """
    try:
        candidates: list[Any] = []
        for holder in (exc, getattr(exc, "response", None)):
            headers = getattr(holder, "headers", None)
            if headers is None:
                continue
            try:
                for key, value in dict(headers).items():
                    if str(key).strip().lower() == "retry-after":
                        candidates.append(value)
            except Exception:  # noqa: BLE001 — an exotic headers object is not an error
                getter = getattr(headers, "get", None)
                if callable(getter):
                    for spelling in ("retry-after", "Retry-After"):
                        try:
                            found = getter(spelling)
                        except Exception:  # noqa: BLE001
                            found = None
                        if found is not None:
                            candidates.append(found)

        bare = getattr(exc, "retry_after", None)
        if bare is not None:
            candidates.append(bare)

        for value in candidates:
            if value is None or isinstance(value, bool):
                continue
            try:
                seconds = float(str(value).strip())
            except (TypeError, ValueError):
                continue  # HTTP-date or garbage — fall back to computed backoff
            if seconds != seconds or seconds in (float("inf"), float("-inf")):
                continue  # NaN / inf
            return max(0.0, min(seconds, RETRY_AFTER_MAX_S))
        return None
    except Exception:  # noqa: BLE001 — header parsing never breaks a retry
        return None


async def _maybe_await(result: Any) -> None:
    """Await `result` if it is awaitable. Lets `on_retry` be sync or async."""
    if result is not None and hasattr(result, "__await__"):
        await result


async def with_retry(
    fn: Callable[[], Any],
    *,
    attempts: int = RETRY_ATTEMPTS,
    base_s: float = RETRY_BASE_S,
    on_retry: Callable[..., Any] | None = None,
    label: str = "",
    breaker: Any | None = None,
) -> Any:
    """Call `fn()` with the ONE retry policy this phase has. Returns its result.

    This generalises the loop at `gates.py:379-393`; it adds full jitter, the
    `retry-after` rule, the R5 `on_retry` feed callback and the R2 breaker hook.

    Semantics:
      - A HARD failure is re-raised after exactly ONE attempt. Retrying an
        account-level refusal only produces more of them, faster — that is the
        776-in-55-seconds incident, and this is its regression gate (T-15.2-01).
      - A transient failure waits `random.uniform(0, base_s * 2**attempt)` (full
        jitter; set `NESTOR_TRIBUNAL_RETRY_JITTER=false` for the plain ramp).
      - A provider-supplied `retry_after(exc)` WINS over the computed wait.
      - `on_retry(attempt, max, wait_s, label)` is called before sleeping, with
        `attempt` 1-based. It may be sync or async. A callback that raises is
        logged at WARNING and swallowed — a feed write is best-effort and must
        never break a run — but the RETRY itself is never swallowed.
      - `breaker` (a `CircuitBreaker`) is consulted BEFORE the first attempt: an
        open circuit raises `CircuitOpenError` without calling `fn` at all. Every
        outcome is then recorded on it.
      - On exhaustion the LAST EXCEPTION IS RE-RAISED. This function never
        returns None to mean failure and never swallows anything (T-15.2-05).
    """
    total = max(1, int(attempts))

    # An open circuit refuses the work outright — no call, no spend.
    if breaker is not None:
        breaker.raise_if_open()

    last_exc: BaseException | None = None

    for attempt in range(total):
        try:
            result = await fn()
        except Exception as exc:  # noqa: BLE001 — classified and re-raised below
            last_exc = exc
            if breaker is not None:
                try:
                    breaker.record_failure(exc)
                except Exception as breaker_exc:  # noqa: BLE001
                    log.warning(
                        "with_retry(%s): breaker.record_failure failed: %s",
                        label,
                        redact(repr(breaker_exc)),
                    )

            if attempt + 1 >= total or not is_transient(exc):
                log.warning(
                    "with_retry(%s): giving up after attempt %d/%d — %s failure: %s",
                    label,
                    attempt + 1,
                    total,
                    classify(exc),
                    redact(f"{type(exc).__name__}: {exc}"),
                )
                raise

            ceiling = float(base_s) * (2 ** attempt)
            wait = random.uniform(0.0, ceiling) if RETRY_JITTER else ceiling
            asked = retry_after(exc)
            if asked is not None:
                wait = asked

            log.warning(
                "with_retry(%s): attempt %d/%d failed (%s) — retrying in %.2fs: %s",
                label,
                attempt + 1,
                total,
                classify(exc),
                wait,
                redact(f"{type(exc).__name__}: {exc}"),
            )

            if on_retry is not None:
                try:
                    await _maybe_await(on_retry(attempt + 1, total, wait, label))
                except Exception as cb_exc:  # noqa: BLE001 — feed writes are best-effort
                    log.warning(
                        "with_retry(%s): on_retry callback failed, continuing: %s",
                        label,
                        redact(repr(cb_exc)),
                    )

            await asyncio.sleep(wait)
            continue

        if breaker is not None:
            try:
                breaker.record_success()
            except Exception as breaker_exc:  # noqa: BLE001
                log.warning(
                    "with_retry(%s): breaker.record_success failed: %s",
                    label,
                    redact(repr(breaker_exc)),
                )
        return result

    # Unreachable in practice: the loop either returns or re-raises. Kept so no
    # code path can fall out of this function returning None (a silent green).
    if last_exc is not None:
        raise last_exc
    raise AssertionError("with_retry: exhausted the loop with no result and no error")


# ---------------------------------------------------------------------------
# F8 — the `pause_turn` continuation. A provider may end a turn with
# stop_reason == "pause_turn" simply because a long server-side tool run needs
# another round trip. `group_skeptic.py:260-265` currently reads ANY non-tool_use
# stop_reason as failure and returns "insufficient", so a paused turn throws away
# a paid, half-finished adversarial session. Plan 15.2-07 applies the branch at
# that call site; this is the shared, bounded helper it applies.
# ---------------------------------------------------------------------------

PAUSE_TURN = "pause_turn"


def is_pause_turn(resp: Any) -> bool:
    """True when a provider response ended with stop_reason == "pause_turn".

    `stop_reason` is provider-controlled text (ASVS V5): read defensively, and
    never raise.
    """
    try:
        return str(getattr(resp, "stop_reason", None) or "").strip().lower() == PAUSE_TURN
    except Exception:  # noqa: BLE001
        return False


class PauseContinuation:
    """A BOUNDED, per-loop continuation budget for `pause_turn` responses.

    Caller contract — on `consume(resp) is True`:
        msgs.append({"role": "assistant", "content": serialise(resp.content)})
        continue   # and DO NOT count this as one of the tool-use turns

    i.e. append the paused assistant message back UNCHANGED and go round again.
    The paused turn does not consume the turn budget, because no reasoning
    happened in it. Serialisation stays at the call site (`group_skeptic`'s
    `_content_to_serialisable`) so this module needs no skeptic import and no
    import cycle exists.

    SECURITY (T-15.2-04): `stop_reason` is provider-controlled, so a malformed or
    hostile stream could otherwise drive an unbounded, billed loop. The budget is
    `MAX_PAUSE_CONTINUATIONS` (3, env-tunable) PER INSTANCE — construct one per
    loop, never one at module level. Once it is spent `consume` returns False and
    the caller's existing failure path takes over, in words, at WARNING.
    """

    def __init__(
        self, *, max_pauses: int = MAX_PAUSE_CONTINUATIONS, label: str = ""
    ) -> None:
        self.max_pauses = max(0, int(max_pauses))
        self.label = label
        self.used = 0

    def consume(self, resp: Any) -> bool:
        """True iff `resp` is a pause_turn AND budget remains (then spend one)."""
        if not is_pause_turn(resp):
            return False
        if self.used >= self.max_pauses:
            log.warning(
                "pause_turn budget spent for %s (%d/%d used) — treating this "
                "paused turn as a failure and falling through",
                self.label or "provider loop",
                self.used,
                self.max_pauses,
            )
            return False
        self.used += 1
        log.info(
            "pause_turn on %s — continuing the loop (continuation %d/%d)",
            self.label or "provider loop",
            self.used,
            self.max_pauses,
        )
        return True
