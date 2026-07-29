"""Degraded-parallel runner over the audited deep-research adapters.

FOUR peer streams since plan 15.2-13: gemini, claude, openai and `own` (the D10
own-researcher, 15.2-12). The fourth is flag-gated AND probe-gated, so a run with
no web-search credential completes cleanly on three streams with the loss named
in words — `own_stream_unavailable_reason()` is that sentence.

PHASE1-07: brief completes if at least MIN_SUCCESSES=2 of the enabled providers
return status='success'. Failed providers are recorded via AuditedLLMClient
(write_failure inside the adapter on exception, or end_call(status='error')
on graceful failure).

Per-provider timeout is PROVIDER_TIMEOUT_S (35 min), matching the legacy
35-minute polling budget (CLAUDE.md Critical rules section 4: deep research
polls every 30s, max 70 attempts).

Reference: 01-RESEARCH.md lines 780-802 verbatim.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import TYPE_CHECKING

log = logging.getLogger(__name__)

from nestor_pulse_sdk.tools.gemini_adapter import (
    deep_research_audited as gemini_research,
)
from nestor_pulse_sdk.tools.claude_adapter import (
    deep_research_audited as claude_research,
)
from nestor_pulse_sdk.tools.openai_adapter import (
    deep_research_audited as openai_research,
)

# The FOURTH stream (D10, plan 15.2-12), imported under a guard while the other
# three are unconditional. That asymmetry is deliberate: the three adapters have
# always existed and an ImportError from any of them is a broken install, but
# this one is new. A partially-merged tree — or a future removal — must degrade
# the run to three streams, not break every import of this module and take the
# whole engine down with it.
try:
    from nestor_pulse_sdk.pipeline.tribunal.own_researcher import (
        deep_research_audited as own_research,
    )
    from nestor_pulse_sdk.pipeline.tribunal import serpapi as _own_search
except ImportError as _own_import_exc:  # pragma: no cover — a broken tree, not a run
    own_research = None
    _own_search = None
    log.warning(
        "the own-researcher stream could not be imported (%r) — this run has three "
        "research streams instead of four", _own_import_exc,
    )

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient


def _flag(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).lower() == "true"


# Flag shape carries verbatim from nestor_pulse/research_agent.py lines 17-22
# (PATTERNS Carry-Over Index). Resolved at import time so tests can patch
# the resolved booleans rather than env vars.
ALLOW_DEEP_RESEARCH_GEMINI = _flag("ALLOW_DEEP_RESEARCH_GEMINI")
ALLOW_DEEP_RESEARCH_CLAUDE = _flag("ALLOW_DEEP_RESEARCH_CLAUDE")
ALLOW_DEEP_RESEARCH_OPENAI = _flag("ALLOW_DEEP_RESEARCH_OPENAI")
ALLOW_DEEP_RESEARCH_OWN = _flag("ALLOW_DEEP_RESEARCH_OWN")

#: Every peer research stream this engine knows about. The ONE place the number
#: four is written down — `InsufficientProvidersError` and `research_division`
#: both read it rather than re-typing a literal list that then drifts.
#:
#: ACCEPTED KNOWN GAP — A DELIBERATE WAVE 3 BOUNDARY. NOT AN OVERSIGHT.
#:
#: Phase 15.6 removed `own` from `research_division._D6_STREAMS` per D-W3-3, on the
#: evidence that 2 of its 4 angles failed outright on run 7dcf51d5, that it
#: reported English in a Dutch run, and that it contributed 2 unique URLs across
#: the whole run. THIS TUPLE STILL LISTS IT, on purpose.
#:
#: The consequence, stated plainly rather than left to be discovered: this module
#: is LIVE AND REACHABLE — it is imported by `pipeline.py`, by
#: `research_division.py` and by `orchestrator.py` — so a DEGRADED BROADCAST run
#: can still route research to the provider the main rotation just dropped. The
#: operator was shown the wider option (removing `own` here too) and chose
#: rotation-only, because the split-the-work angle path is where the V-01 evidence
#: was gathered and the broadcast path is a different, rarely-taken contract.
#:
#: Phase 15.8's measuring run MUST know this: if `own` output appears in a run
#: whose rotation is three streams, the run took a degraded broadcast path, and
#: that is information about the path rather than a bug in the rotation.
#:
#: THIS IS NOT AN OVERSIGHT AND MUST NOT BE "FIXED" AS ONE. Changing this tuple
#: also changes `InsufficientProvidersError`'s arithmetic (it counts this tuple)
#: and `MIN_SUCCESSES`'s 2-of-N contract, neither of which Wave 3 has any remit
#: over. Closing the gap is explicitly out of scope: comment it, do not fix it.
ALL_PROVIDERS = ("gemini", "claude", "openai", "own")

PROVIDER_TIMEOUT_S = 35 * 60  # CLAUDE.md Critical rules section 4
# PHASE1-07's 2-of-N contract for `run_all_with_degradation`, and NOT changed by
# the arrival of a fourth stream. That rule governs the BROADCAST path (one query
# to every provider); the split-the-work angle path in `research_division` sends
# each angle to ONE stream and never calls this function. Raising it here would
# silently retighten a rule plan 15.2-13 has no remit over.
MIN_SUCCESSES = 2              # PHASE1-07


class InsufficientProvidersError(Exception):
    """Raised when fewer than MIN_SUCCESSES providers return status='success'."""

    def __init__(
        self,
        failed: list[str],
        reasons: dict[str, str] | None = None,
        *,
        total: int | None = None,
    ) -> None:
        # `total` defaults to the real stream count instead of a hardcoded 3,
        # which under four streams reported "Only 2 of 3 succeeded" for a
        # one-provider outage — an operator-facing arithmetic lie. Keyword-only
        # and defaulted, so every existing call site stays valid.
        total = len(ALL_PROVIDERS) if total is None else int(total)
        succeeded = max(0, total - len(failed))
        reasons = reasons or {}
        detail = "; ".join(f"{n}: {reasons.get(n, 'unknown')}" for n in failed)
        super().__init__(
            f"Only {succeeded} of {total} providers succeeded; failed: {failed}"
            + (f" ({detail})" if detail else "")
        )
        self.failed = failed
        self.reasons = reasons
        self.total = total


def _own_stream_available() -> bool:
    """True when the fourth stream may be called right now.

    Reads 15.2-12's OWN availability gate rather than inventing a second state
    machine: the search endpoint's circuit lives in `serpapi`, and this is the
    same predicate `run_own_research` applies before its first call. NOT
    memoised — the breaker's half-open state must be able to re-admit the stream
    part-way through a run.
    """
    if _own_search is None:
        return False
    try:
        return _own_search.unavailable_reason() is None
    except Exception as exc:  # noqa: BLE001 — an unreadable probe refuses the stream
        log.warning(
            "the own-researcher availability probe failed (%r) — treating the "
            "stream as unavailable for now", exc,
        )
        return False


def own_stream_unavailable_reason() -> str | None:
    """None when the fourth stream is enabled, else ONE plain-words sentence.

    This is the D-12 reason string `pipeline.py` records when a run completes on
    three streams instead of four. Fail loud, in words — the register of
    `verification/report.py`, never a code and never an icon.

    IT NAMES A CONDITION AND NOTHING ELSE (T-15.2-65). No credential value, no
    credential variable name, no endpoint URL and no query string ever appears
    here: the search endpoint takes its credential as a URL parameter, so a
    reason string that quoted a URL would put a secret into `run.stage_detail`,
    which a superadmin's browser polls.
    """
    if not ALLOW_DEEP_RESEARCH_OWN:
        return (
            "The own-researcher stream is switched off for this run by "
            "configuration, so the research ran on three streams instead of four."
        )
    if own_research is None or _own_search is None:
        return (
            "The own-researcher stream could not be loaded in this build, so the "
            "research ran on three streams instead of four."
        )
    try:
        reason = _own_search.unavailable_reason()
    except Exception:  # noqa: BLE001 — an unreadable probe is itself the reason
        return (
            "The own-researcher stream could not be checked for availability, so "
            "it was left out and the research ran on three streams."
        )
    if reason is None:
        return None
    if reason == _own_search.REASON_KEY_MISSING:
        return (
            "The own-researcher stream had no web-search credential in this "
            "environment, so it was refused before any call was made and the "
            "research ran on three streams instead of four."
        )
    if reason == _own_search.REASON_BREAKER_OPEN:
        return (
            "The own-researcher stream's web-search endpoint was refusing "
            "requests after repeated failures, so the stream was left out and "
            "the research ran on three streams instead of four."
        )
    return (
        "The own-researcher stream was unavailable for this run, so the research "
        "ran on three streams instead of four."
    )


def _enabled_providers() -> list[tuple[str, object]]:
    """Resolve the (name, runner) list from current module-level flag values.

    Resolved on each call so monkeypatched flag overrides take effect — and, for
    the fourth stream, so a breaker that closes part-way through a run re-admits
    it. Do NOT cache this list at module scope.
    """
    providers: list[tuple[str, object]] = []
    if ALLOW_DEEP_RESEARCH_GEMINI:
        providers.append(("gemini", gemini_research))
    if ALLOW_DEEP_RESEARCH_CLAUDE:
        providers.append(("claude", claude_research))
    if ALLOW_DEEP_RESEARCH_OPENAI:
        providers.append(("openai", openai_research))
    if ALLOW_DEEP_RESEARCH_OWN and own_research is not None and _own_stream_available():
        providers.append(("own", own_research))
    return providers


async def run_all_with_degradation(
    *,
    query: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[tuple[str, dict]]:
    """Run all enabled providers in parallel; return (name, result) for successes.

    Raises InsufficientProvidersError if fewer than MIN_SUCCESSES providers
    return status='success' (whether by exception, timeout, or envelope error).
    """

    # Per-provider failure reasons (envelope error_message or exception text).
    # Surfaced via logging AND the raised exception so a provider never fails
    # silently (ops principle: no silent caps / swallowed errors).
    failures: dict[str, str] = {}

    async def _one(name: str, runner) -> tuple[str, dict | None]:
        try:
            async with asyncio.timeout(PROVIDER_TIMEOUT_S):
                result = await runner(
                    query=query,
                    audited=audited,
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
                if isinstance(result, dict) and result.get("status") == "success":
                    return name, result
                # Graceful error envelope (adapter caught the error itself).
                if isinstance(result, dict):
                    reason = result.get("error_message") or f"status={result.get('status')!r}"
                else:
                    reason = f"non-dict result: {result!r}"
                failures[name] = str(reason)[:600]
                log.warning("deep-research provider %s did not succeed: %s", name, failures[name])
                return name, None
        except Exception as exc:
            # Defense-in-depth: adapter usually catches exceptions itself,
            # but if write_failure inside the adapter raises (or asyncio.timeout
            # fires above the adapter's try/except), capture here as well.
            failures[name] = f"{type(exc).__name__}: {exc}"[:600]
            log.warning("deep-research provider %s raised: %s", name, failures[name])
            try:
                await audited.write_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    provider=name,
                    error=exc,
                )
            except Exception:
                # Audit-write failure must not block the degraded-parallel flow
                pass
            return name, None

    tasks = [_one(name, runner) for name, runner in _enabled_providers()]
    if not tasks:
        raise InsufficientProvidersError(failed=list(ALL_PROVIDERS))

    results = await asyncio.gather(*tasks)
    successes: list[tuple[str, dict]] = [
        (name, result) for name, result in results if result is not None
    ]
    if len(successes) < MIN_SUCCESSES:
        failed = [name for name, result in results if result is None]
        raise InsufficientProvidersError(failed=failed, reasons=failures)
    return successes
