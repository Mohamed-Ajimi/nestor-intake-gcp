"""Degraded-parallel runner over the 3 audited deep-research adapters.

PHASE1-07: brief completes if at least MIN_SUCCESSES=2 of the 3 enabled providers
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

PROVIDER_TIMEOUT_S = 35 * 60  # CLAUDE.md Critical rules section 4
MIN_SUCCESSES = 2              # PHASE1-07


class InsufficientProvidersError(Exception):
    """Raised when fewer than MIN_SUCCESSES providers return status='success'."""

    def __init__(self, failed: list[str], reasons: dict[str, str] | None = None) -> None:
        succeeded = 3 - len(failed)
        reasons = reasons or {}
        detail = "; ".join(f"{n}: {reasons.get(n, 'unknown')}" for n in failed)
        super().__init__(
            f"Only {succeeded} of 3 providers succeeded; failed: {failed}"
            + (f" ({detail})" if detail else "")
        )
        self.failed = failed
        self.reasons = reasons


def _enabled_providers() -> list[tuple[str, object]]:
    """Resolve the (name, runner) list from current module-level flag values.

    Resolved on each call so monkeypatched flag overrides take effect.
    """
    providers: list[tuple[str, object]] = []
    if ALLOW_DEEP_RESEARCH_GEMINI:
        providers.append(("gemini", gemini_research))
    if ALLOW_DEEP_RESEARCH_CLAUDE:
        providers.append(("claude", claude_research))
    if ALLOW_DEEP_RESEARCH_OPENAI:
        providers.append(("openai", openai_research))
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
        raise InsufficientProvidersError(failed=["gemini", "claude", "openai"])

    results = await asyncio.gather(*tasks)
    successes: list[tuple[str, dict]] = [
        (name, result) for name, result in results if result is not None
    ]
    if len(successes) < MIN_SUCCESSES:
        failed = [name for name, result in results if result is None]
        raise InsufficientProvidersError(failed=failed, reasons=failures)
    return successes
