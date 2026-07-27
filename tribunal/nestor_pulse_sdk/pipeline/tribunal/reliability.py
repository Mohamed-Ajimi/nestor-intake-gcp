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
import time
from typing import Any, Callable, Sequence

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

# Wording that marks a REFUSED MODEL ID — a statement about this deployment's
# CONFIGURATION, not about the provider's health. Same comment discipline as
# _CAP_MARKERS: each phrase must be specific enough not to match ordinary
# claim-bearing error text, because a false positive here kills a healthy
# provider's stream after ONE failure.
#   "model_not_found"     the API error CODE. Underscored, so it cannot occur in prose.
#   "model not found"     the spaced spelling some providers use in the message body.
#   "unknown model"       two words that only ever appear together about a model id.
#   "has been deprecated" the exact D-A wording. A deprecation notice IS a
#                         configuration statement whatever it is about, so the
#                         phrase is deliberately not model-scoped.
# DELIBERATELY NOT A BARE SUBSTRING: "does not exist". On its own it also matches
# "the requested file does not exist" and a resumed background response that is
# past its ~10-minute retention window (R7/DEC-2) — neither is a configuration
# error, and treating either as one would open the circuit on a healthy provider.
# It is honoured in its MODEL-SCOPED form only, via _MODEL_MISSING_RE below.
_CONFIG_ERROR_MARKERS = (
    "model_not_found",
    "model not found",
    "unknown model",
    "has been deprecated",
)

# "The model `gpt-5.6-sol` does not exist or you do not have access to it." —
# OpenAI's phrasing. The bounded `.{0,120}` keeps "model" and "does not exist" in
# the same clause, so a message that merely mentions a model somewhere and a
# missing file somewhere else does not match.
_MODEL_MISSING_RE = re.compile(r"\bmodel\b.{0,120}?\bdoes not exist", re.DOTALL)


def _is_config_error(msg: str) -> bool:
    """True when a lowercased exception message names a refused model id."""
    if any(marker in msg for marker in _CONFIG_ERROR_MARKERS):
        return True
    return bool(_MODEL_MISSING_RE.search(msg))


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

    THE REFUSED MODEL ID (D-A, run d6bb3aae, 2026-07-27). A `model_not_found` is
    a STATEMENT ABOUT THE CONFIGURATION. OpenAI shut both deep-research models
    down on 2026-07-23; the deployed worker still asked for one of them, and
    every one of the seven OpenAI angles failed — one at a time, each a WARNING,
    none of them saying that the model this deployment is configured with does
    not exist. Retrying it can only produce more of the same, and degrading it
    PER ANGLE turns one configuration error into N identical warnings and a whole
    silently-dead stream. So the wording is checked BEFORE the status code: a
    refused model id arrives as a 400 on one provider and a 404 on another, and
    on the deep-research path it arrives asynchronously with no status at all.
    """
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True

    msg = f"{type(exc).__name__} {exc}".lower()

    # Hard account refusal — never retried, whatever status it claims to carry.
    if any(marker in msg for marker in _CAP_MARKERS):
        return False

    # Refused model id — never retried, whatever status it claims to carry.
    if _is_config_error(msg):
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
CONFIG_ERROR = "config_error"

FAILURE_CLASSES: tuple[str, ...] = (
    TRANSIENT,
    RATE_LIMIT,
    OVERLOAD,
    HARD,
    HARD_WALL,
    CONFIG_ERROR,
)


def classify(exc: BaseException) -> str:
    """Classify a provider failure into one of `FAILURE_CLASSES`. Never raises.

    Evaluation order, and why each rung sits where it does:

      (a) HARD_WALL — cap/billing wording, or HTTP 402. 402 `billing_error` is
          Anthropic's documented "credits exhausted" code and is NEW to this
          codebase; D-17 makes it a PARK trigger, not a degrade trigger. A hard
          wall is a statement about the account: it trips the breaker on its
          FIRST occurrence and is never retried.
      (a2) CONFIG_ERROR — a REFUSED MODEL ID (D-A, run d6bb3aae). Decided on the
          WORDING and ahead of every status rung, because `model_not_found`
          arrives as a 400 from one provider, a 404 from another, and with no
          status at all on the deep-research path. Like a hard wall it is a
          STATEMENT rather than a blip, so it takes the SAME breaker path and
          trips on its FIRST occurrence — seven identical per-angle warnings is
          exactly the disguise this class exists to remove. It is a SEPARATE
          class from HARD_WALL because the remedy differs in kind: a wall wants
          the operator's wallet, a refused model id wants an env var.
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
        if _is_config_error(msg):
            return CONFIG_ERROR
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


# ---------------------------------------------------------------------------
# R2 — the per-provider circuit breaker.
#
# THESE FIVE NUMBERS ARE MEDIUM-CONFIDENCE DEFAULTS. RESEARCH grounds them in
# community consensus and standard published practice, not in vendor
# documentation — the trip threshold of 5, the 60 s open window and the 10×
# overload allowance are all "widely used", not "measured here". The August live
# run (V-01/V-02) is what calibrates them against real provider behaviour, which
# is exactly why every one of them is env-tunable: retuning must cost an env-var
# change, not a code change and a new image.
#   BREAKER_HARD_THRESHOLD      consecutive IDENTICAL hard failures before trip.
#   BREAKER_OVERLOAD_THRESHOLD  separate, HIGHER threshold for 529/timeouts, so a
#                               capacity blip does not kill a research stream.
#   BREAKER_OPEN_S              first open window; each re-open doubles it.
#   BREAKER_OPEN_MAX_S          ceiling on that escalation.
#   BREAKER_SIGNATURE_CHARS     how much of the message defines "identical".
BREAKER_HARD_THRESHOLD = int(
    os.environ.get("NESTOR_TRIBUNAL_BREAKER_HARD_THRESHOLD", "5")
)
BREAKER_OVERLOAD_THRESHOLD = int(
    os.environ.get("NESTOR_TRIBUNAL_BREAKER_OVERLOAD_THRESHOLD", "10")
)
BREAKER_OPEN_S = float(os.environ.get("NESTOR_TRIBUNAL_BREAKER_OPEN_S", "60"))
BREAKER_OPEN_MAX_S = float(os.environ.get("NESTOR_TRIBUNAL_BREAKER_OPEN_MAX_S", "600"))
BREAKER_SIGNATURE_CHARS = int(
    os.environ.get("NESTOR_TRIBUNAL_BREAKER_SIGNATURE_CHARS", "80")
)

CLOSED = "closed"
OPEN = "open"
HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    """Raised instead of calling a provider whose circuit is open.

    Carries the plain-words `reason` that D-12 puts in a degraded run's
    `degradation_reasons` list. A lost stream is always NAMED — never a silent
    absence (Shared Pattern 5, T-15.2-05).
    """

    def __init__(
        self,
        provider: str,
        reason: str,
        opened_at: float = 0.0,
        retry_at: float = 0.0,
    ) -> None:
        self.provider = provider
        self.reason = reason
        self.opened_at = float(opened_at)
        self.retry_at = float(retry_at)
        window = max(0.0, self.retry_at - self.opened_at)
        super().__init__(
            f"{provider}: circuit open — {reason}. No further {provider} calls "
            f"will be made for {window:.0f}s, then one probe decides whether to "
            f"close it."
        )


def error_signature(exc: BaseException) -> str:
    """A normalised fingerprint that makes "the same error again" decidable.

    R2 trips on consecutive IDENTICAL hard failures, so "identical" needs a
    definition. Without digit stripping every request id in the message makes
    each error unique and the breaker NEVER TRIPS — which is the failure this
    whole primitive exists to prevent.

    Pipeline: lowercase -> redact credentials -> strip digit runs -> collapse
    whitespace -> truncate -> prefix with the HTTP status (which keeps its
    digits, because 401 and 403 are different errors).

    Redaction happens BEFORE truncation and is not optional (T-15.2-02): a
    SerpApi failure carries the API key in the query string, and this signature
    is written to WARNING logs, to `snapshot()` and to the operator feed, so it
    must be safe to display. Never raises.
    """
    try:
        status = _status_of(exc)
        text = redact(f"{type(exc).__name__} {exc}".lower())
        text = re.sub(r"\d+", "", text)
        text = re.sub(r"\s+", " ", text).strip()[:BREAKER_SIGNATURE_CHARS]
        return f"{status if status is not None else 'none'}|{text}"
    except Exception:  # noqa: BLE001 — a signature that raises is worse than a vague one
        return "none|<unprintable>"


class CircuitBreaker:
    """One provider's circuit. In-process, RUN-SCOPED, per (provider, stage).

    SCOPE DECISION: one worker runs one run (`runs/worker.py`), so there is no
    shared state to coordinate, no database and no cross-request surface. State
    carries provider names, counts and status codes only — no tenant data
    (T-15.2-07). Construct these through a per-run `BreakerSet`; NEVER at module
    level, or one run's failures would open another run's circuit.

    The `clock` is injected so the open window is testable without sleeping:
    the tests pass a fake clock and step it forward by hand.

    State machine:
        closed  -- `allow()` True, calls flow.
        open    -- `allow()` False until `retry_at`. Nothing is sent, nothing is
                   billed.
        half_open -- exactly ONE probe is allowed through. Success closes the
                   circuit; failure re-opens it for twice as long, capped.
    """

    def __init__(
        self,
        name: str,
        *,
        hard_threshold: int = BREAKER_HARD_THRESHOLD,
        overload_threshold: int = BREAKER_OVERLOAD_THRESHOLD,
        open_s: float = BREAKER_OPEN_S,
        max_open_s: float = BREAKER_OPEN_MAX_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.name = name
        self.hard_threshold = max(1, int(hard_threshold))
        self.overload_threshold = max(1, int(overload_threshold))
        self.open_s = float(open_s)
        self.max_open_s = float(max_open_s)
        self._clock = clock

        self.consecutive_hard = 0
        self.overload = 0
        self.rate_limited = 0
        self.signature: str | None = None
        self.reason = ""
        self.opened_at = 0.0
        self.retry_at = 0.0

        self._open = False
        self._probe_in_flight = False
        self._open_cycles = 0

    # -- state -------------------------------------------------------------

    @property
    def state(self) -> str:
        """"closed" / "open" / "half_open", derived from the injected clock."""
        if not self._open:
            return CLOSED
        if self._probe_in_flight or self._clock() >= self.retry_at:
            return HALF_OPEN
        return OPEN

    def allow(self) -> bool:
        """May a call go out right now? Consumes the half-open probe if so."""
        if not self._open:
            return True
        if self._probe_in_flight:
            return False  # somebody else already took the one probe
        if self._clock() >= self.retry_at:
            self._probe_in_flight = True
            return True
        return False

    def raise_if_open(self) -> None:
        """Raise `CircuitOpenError` when no call may go out."""
        if not self.allow():
            raise CircuitOpenError(
                self.name,
                self.reason or "circuit open after repeated hard failures",
                self.opened_at,
                self.retry_at,
            )

    # -- outcomes ----------------------------------------------------------

    def record_success(self) -> None:
        """A call worked: close the circuit and forget the failure history."""
        self._open = False
        self._probe_in_flight = False
        self._open_cycles = 0
        self.consecutive_hard = 0
        self.overload = 0
        self.signature = None
        self.reason = ""
        self.opened_at = 0.0
        self.retry_at = 0.0

    def record_failure(self, exc: BaseException) -> None:
        """Book a failure against the right counter. Only some kinds trip."""
        failure_class = classify(exc)

        if failure_class == RATE_LIMIT:
            # R2, verbatim: rate limiting is NOT a failure — it means the API is
            # healthy and we are sending too much. Plain 429s are retried, never
            # counted, and never trip the breaker. This is the single most
            # important line in this method: treating 429 as a failure would
            # open the circuit on a perfectly healthy provider.
            self.rate_limited += 1
            return

        if failure_class in (HARD_WALL, CONFIG_ERROR):
            # ONE rule, two causes, because the response is identical: both are
            # STATEMENTS rather than blips, so both trip on the FIRST occurrence.
            #   HARD_WALL    the monthly cap / exhausted credits. Waiting for
            #                five is how 776 requests went out in 55 seconds.
            #   CONFIG_ERROR a refused model id (D-A). Waiting for five is how
            #                seven angles were dispatched at a model OpenAI had
            #                switched off four days earlier.
            # Only the REASON differs, because what the operator must do differs.
            self.signature = error_signature(exc)
            self.consecutive_hard += 1
            if failure_class == CONFIG_ERROR:
                self.trip(
                    f"{self.name} refused the model id this deployment is "
                    f"configured with ({self.signature}) — this is a "
                    f"CONFIGURATION error, not a provider outage: no retry and "
                    f"no other angle can fix it"
                )
            else:
                self.trip(
                    f"{self.name} refused the request at the account level "
                    f"(hard wall: {self.signature}) — no retry can fix this"
                )
            return

        if self._probe_in_flight:
            # The one half-open probe failed: re-open immediately, for longer,
            # whatever the class. The provider is not back yet.
            self._probe_in_flight = False
            self.trip(
                f"{self.name} failed its recovery probe ({failure_class}) — "
                f"circuit re-opened for longer"
            )
            return

        if failure_class == HARD:
            signature = error_signature(exc)
            if signature != self.signature:
                self.signature = signature
                self.consecutive_hard = 1
            else:
                self.consecutive_hard += 1
            if self.consecutive_hard >= self.hard_threshold:
                self.trip(
                    f"{self.name} returned the same hard failure "
                    f"{self.consecutive_hard} times in a row ({self.signature})"
                )
            return

        if failure_class == OVERLOAD:
            self.overload += 1
            if self.overload >= self.overload_threshold:
                self.trip(
                    f"{self.name} has been overloaded or timing out "
                    f"{self.overload} times — backing off this provider"
                )
            return

        # TRANSIENT: a 5xx blip that `with_retry` already handles. No counter
        # moves, because a recovered retry is not a failure of the provider.
        return

    # -- transitions -------------------------------------------------------

    def trip(self, reason: str) -> None:
        """Open the circuit, with an escalating window on each successive trip."""
        self.opened_at = self._clock()
        self._open_cycles += 1
        window = min(self.open_s * (2 ** (self._open_cycles - 1)), self.max_open_s)
        self.retry_at = self.opened_at + window
        self.reason = reason
        self._open = True
        self._probe_in_flight = False
        log.warning(
            "circuit breaker %s OPEN for %.0fs — %s (signature: %s)",
            self.name,
            window,
            reason,
            self.signature or "n/a",
        )

    def force_open(self, reason: str) -> None:
        """Open the circuit with an arbitrary reason and NO exception.

        This is the startup seam plan 15.2-12 uses for "`SERPAPI_API_KEY` is not
        configured": the own-researcher's breaker is forced open before the run
        starts, so the stream is never attempted, the reason is named in D-12's
        degradation list, and the run finishes as a clean 3-stream
        `completed_degraded` instead of failing mid-flight on a missing secret.
        """
        self.trip(reason)

    def snapshot(self) -> dict[str, Any]:
        """Plain, JSON-safe data for the operator feed and the verification report."""
        return {
            "provider": self.name,
            "state": self.state,
            "reason": self.reason,
            "consecutive_hard": self.consecutive_hard,
            "overload": self.overload,
            "rate_limited": self.rate_limited,
            "opened_at": self.opened_at,
            "retry_at": self.retry_at,
        }


class BreakerSet:
    """The RUN-SCOPED registry of per-provider breakers. Create one PER RUN.

    NEVER instantiate this at module level. Breaker state is per run by design:
    a module-level set would carry one run's provider failures into the next
    run — and, in a multi-tenant system, across tenants.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._breakers: dict[str, CircuitBreaker] = {}

    def get(self, name: str) -> CircuitBreaker:
        """The breaker for `name`, created on first use."""
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(name, clock=self._clock)
        return self._breakers[name]

    def all(self) -> dict[str, CircuitBreaker]:
        return dict(self._breakers)

    def open_providers(self) -> list[str]:
        """Providers whose circuit is not closed (open or awaiting a probe)."""
        return [n for n, b in self._breakers.items() if b.state != CLOSED]

    def reasons(self) -> list[str]:
        """The plain-words reasons, ready for D-12's `degradation_reasons`."""
        return [
            b.reason for b in self._breakers.values() if b.state != CLOSED and b.reason
        ]

    def snapshot(self) -> list[dict[str, Any]]:
        return [b.snapshot() for b in self._breakers.values()]


# ---------------------------------------------------------------------------
# R4/R6 — D-17's terminal-state boundary, as a pure function.
#
# `failed` and `cancelled` are written elsewhere (`runs/worker.py`) and are
# deliberately OUTSIDE this function's range: they mean "the run crashed" and
# "a human stopped it", neither of which is a judgement about the output. The
# status VOCABULARY sites — `runs/schemas.py::RunStatus` and
# `db/models/run.py::ck_run_status` — are owned by plans 15.2-09 and 15.2-01;
# this module owns only the decision.
# ---------------------------------------------------------------------------

ENGINE_TERMINAL_STATES: tuple[str, ...] = ("completed", "completed_degraded", "parked")


def terminal_state(
    *,
    streams_lost: int,
    streams_total: int,
    verify_ran: bool,
    synthesis_ran: bool,
    hard_wall: bool,
    degradation_reasons: Sequence[str],
) -> str:
    """Decide a run's terminal state. Pure: no I/O, no clock, no LLM.

    Returns one of `ENGINE_TERMINAL_STATES`. D-17's truth table:

      PARK — "no honest deliverable is possible". A hard wall (the Anthropic
        monthly cap, exhausted credits — the settled R4 case), no streams at
        all, EVERY research provider walled, verification entirely unable to
        run, or the synthesis model walled. Park means "this genuinely needs
        you": resume is a superadmin click, and checkpoint resumes are free.

      COMPLETED_DEGRADED — the output fell short and every reason is named. One
        or two streams lost, a non-empty bucket 3, a workshop that fell back, a
        skipped stage.

      COMPLETED — clean.

    TWO CASES THAT DELIBERATELY DO NOT DEGRADE A RUN (D-12 — do not add them):
      * RECOVERED RETRIES do not degrade. R5 already shows them in the feed as
        recovery; demoting them would make nearly every run degraded and drain
        the status of its meaning.
      * `cost_pending` does not degrade. Pending-then-backfill-exact is the
        designed path for Gemini grounding fees (C1), not a shortfall.

    The `streams_lost > 0` with no reason recorded branch degrades ANYWAY and
    logs the inconsistency at WARNING. Losing a stream without naming why is a
    bookkeeping bug, and the honest resolution is to say so out loud rather than
    report a clean `completed` (fail loud, never a silent green).
    """
    reasons = [
        r for r in (degradation_reasons or []) if isinstance(r, str) and r.strip()
    ]

    if hard_wall:
        return "parked"
    if streams_total <= 0:
        return "parked"
    if streams_lost >= streams_total:
        return "parked"
    if not verify_ran:
        return "parked"
    if not synthesis_ran:
        return "parked"

    if reasons:
        return "completed_degraded"

    if streams_lost > 0:
        log.warning(
            "terminal_state: %d of %d research streams were lost but no "
            "degradation reason was recorded — degrading anyway. This is a "
            "bookkeeping bug: every lost stream must be named (D-12).",
            streams_lost,
            streams_total,
        )
        return "completed_degraded"

    return "completed"
