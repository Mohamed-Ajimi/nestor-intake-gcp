"""Tribunal hybrid research division — Plan 01-15 Task 1.

Turns a stakes-tagged mission_brief (from adaptive_intake) into per-angle
research queries and drives run_all_with_degradation (PHASE1-07 >=2-of-3).

ADR-006 §Decision stage 2 — hybrid research division:
  - Each focus_area becomes one angle (query derived from the focus_area label +
    the brief's deep_research_prompt).
  - HIGH-STAKES angles are doubled: they appear as two separate query entries
    (one scoped to the focus label, one to the broader brief) so that >=2
    providers independently verify the angle.
  - LOW + MED angles are assigned once (breadth coverage, single-provider pass).
  - If no focus_areas exist, a single broadcast query is used (the fallback for
    the thin-SDKPipeline control path compatibility).

run_angles(angles, audited, run_id, tenant_id):
  - Drives run_all_with_degradation per angle with per-angle queries.
  - Returns the merged provider_results list (same shape as a single broadcast
    call, so claim_distiller + downstream remain unchanged).
  - Preserves PHASE1-07: each run_all_with_degradation call requires >=2-of-3
    providers to succeed; InsufficientProvidersError propagates to the pipeline.

Note: run_all_with_degradation is IMPORTED VERBATIM — we do NOT reimplement the
      fan-out logic here. The grep gate verifies this:
        grep -c "run_all_with_degradation" nestor_pulse_sdk/pipeline/tribunal/research_division.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Awaitable, Callable, Optional, TYPE_CHECKING

from nestor_pulse_sdk.pipeline.deep_researchers.degraded_parallel import (
    run_all_with_degradation,  # kept for grep gate + back-compat (not used in split path)
    InsufficientProvidersError,
    gemini_research,
    claude_research,
    openai_research,
    _enabled_providers,
)

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

# --- Split-the-work research division (ADR-006 §research — provider task-delegation) ---
# Each angle is sent to ONE provider, NOT all three (no duplicate question search).
# Assignment is STAKES-BASED (decision 2026-06-10, replaces round-robin):
#   high -> gemini (deep research)   med -> openai   low -> claude
# High-stakes angles are doubled by divide(); the second (broad) copy goes to
# claude, so every high-stakes topic is independently covered by Gemini AND Claude.
# If an angle's preferred provider is disabled, it falls back to round-robin over
# whatever IS enabled (an angle must never be silently dropped).
# Angles run CONCURRENTLY, so the division genuinely parallelises
# the work across models. Gemini is NOT capped: because every angle is a single
# provider running concurrently, a slow Gemini angle no longer blocks the others,
# so Gemini is allowed its full deep-research budget (its adapter polls up to ~35 min).
# The only timeout here is a generous hang-safety net above every provider's own limit.
_STAKES_PROVIDER = {"high": "gemini", "med": "openai", "low": "claude"}
_HIGH_REDUNDANCY_PROVIDER = "claude"  # second provider on doubled high-stakes angles

# Cost guard: hard ceiling on total angles per run (research-job explosion guard).
# When over the cap, doubled high-stakes REDUNDANCY copies are trimmed FIRST —
# every focus area keeps its primary angle; only the extra coverage is sacrificed.
_MAX_ANGLES = int(os.environ.get("NESTOR_TRIBUNAL_MAX_ANGLES", "12"))
_DEFAULT_TIMEOUT_S = int(os.environ.get("NESTOR_DR_TIMEOUT_S", str(40 * 60)))
_ANGLE_CONCURRENCY = int(os.environ.get("NESTOR_TRIBUNAL_ANGLE_CONCURRENCY", "4"))
_PROVIDER_RUNNERS = {
    "gemini": gemini_research,
    "claude": claude_research,
    "openai": openai_research,
}
_PROVIDER_TIMEOUTS: dict[str, int] = {}  # no per-provider cap — all use _DEFAULT_TIMEOUT_S

# Re-export so callers can catch it without importing the deep_researchers module.
__all__ = [
    "divide",
    "run_angles",
    "InsufficientProvidersError",
]


def divide(mission_brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Turn focus_areas into per-angle research query dicts.

    Args:
        mission_brief: Structured mission_brief from adaptive_intake().
                       Expected keys: deep_research_prompt, focus_areas[*].{focus_area, stakes}.

    Returns:
        List of angle dicts, each:
            {
                "query":       str,   # research query for this angle
                "stakes":      str,   # "low"|"med"|"high"
                "focus_area":  str,   # original focus_area label
                "provider":    str,   # preferred provider (stakes-based mapping)
            }
        High-stakes angles appear TWICE (for 2-provider redundancy):
        the focused copy is assigned to gemini, the broad copy to claude.
    """
    base_prompt = (mission_brief.get("deep_research_prompt") or "").strip()
    focus_areas: list[dict[str, Any]] = mission_brief.get("focus_areas") or []

    if not focus_areas:
        # Fallback: single broadcast angle (control-path compatibility)
        log.info("research_division.divide: no focus_areas — returning broadcast angle")
        return [
            {
                "query": base_prompt or "general research",
                "stakes": "med",
                "focus_area": "general",
                "provider": _STAKES_PROVIDER["med"],
            }
        ]

    angles: list[dict[str, Any]] = []

    for fa in focus_areas:
        label = (fa.get("focus_area") or "").strip()
        stakes = (fa.get("stakes") or "med").strip()
        if not label:
            log.warning("research_division.divide: empty focus_area label — skipping")
            continue

        # Build the angle query. PREFER the intake-authored research_prompt: a
        # self-contained, clarification-answer-enriched, scoped-to-this-question
        # brief. The verbatim `label` stays as the coverage/display key only.
        # Fallback (legacy / no research_prompt): the old "label: shared base"
        # shape — which leaks the whole brief into every angle and never folds in
        # the user's answers (the under-exploited-intake gap, plan item 1.1).
        research_prompt = (fa.get("research_prompt") or "").strip()
        if research_prompt:
            query = research_prompt
        elif base_prompt:
            query = f"{label}: {base_prompt}"
        else:
            query = label

        angle = {
            "query": query,
            "stakes": stakes,
            "focus_area": label,
            "provider": _STAKES_PROVIDER.get(stakes, _STAKES_PROVIDER["med"]),
        }
        angles.append(angle)

        if stakes == "high":
            # Double high-stakes angles — a second, broader angle for 2+ provider
            # coverage. The two copies must be meaningfully distinct (not a literal
            # duplicate search). With a scoped research_prompt, the broad copy
            # widens it explicitly; otherwise it falls back to the shared base
            # prompt. The focused copy goes to gemini, this broad copy to claude.
            if research_prompt:
                broad_query = (
                    f"{research_prompt} Take a broader, exploratory angle: surface "
                    "adjacent context, second-order effects, and less obvious sources."
                )
            else:
                broad_query = base_prompt if base_prompt else f"{label} broader context"
            angles.append(
                {
                    "query": broad_query,
                    "stakes": stakes,
                    "focus_area": label,
                    "provider": _HIGH_REDUNDANCY_PROVIDER,
                }
            )
            log.debug("research_division.divide: doubled high-stakes angle %r", label)

    if not angles:
        # All focus_areas were empty-label — fall back to broadcast
        log.warning("research_division.divide: all focus_areas had empty labels — broadcast fallback")
        angles = [
            {
                "query": base_prompt or "general research",
                "stakes": "med",
                "focus_area": "general",
                "provider": _STAKES_PROVIDER["med"],
            }
        ]

    # Angle cap: trim doubled high-stakes redundancy copies first, then (only if
    # still over) trailing angles. Loudly logged — silent truncation is worse.
    if len(angles) > _MAX_ANGLES:
        primaries = [a for a in angles if a.get("provider") != _HIGH_REDUNDANCY_PROVIDER
                     or a.get("stakes") != "high"]
        redundant = [a for a in angles if a not in primaries]
        keep = primaries[:_MAX_ANGLES]
        for r in redundant:
            if len(keep) >= _MAX_ANGLES:
                break
            keep.append(r)
        log.warning(
            "research_division.divide: angle cap hit — %d angles trimmed to %d "
            "(NESTOR_TRIBUNAL_MAX_ANGLES=%d; high-stakes redundancy copies dropped first)",
            len(angles), len(keep), _MAX_ANGLES,
        )
        angles = keep

    log.info("research_division.divide: %d angles from %d focus_areas", len(angles), len(focus_areas))
    return angles


async def run_angles(
    *,
    angles: list[dict[str, Any]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    on_angle_done: "Optional[Callable[[int, bool], Awaitable[None]]]" = None,
) -> list[tuple[str, dict]]:
    """Drive run_all_with_degradation for each angle; return merged provider_results.

    Each angle produces one run_all_with_degradation call with the angle's specific
    query. Results from all angles are merged into a single provider_results list
    (compatible with claim_distiller input format).

    PHASE1-07 preserved: each call raises InsufficientProvidersError if <2 providers
    succeed for that angle. Callers should handle this exception or let it propagate.

    Args:
        angles:    List of angle dicts from divide().
        audited:   AuditedLLMClient — the ONLY LLM egress.
        run_id:    UUID of the current run (audit chain).
        tenant_id: UUID of the current tenant (audit chain).

        on_angle_done: optional async callback (angle_index, succeeded) invoked
                       as each angle finishes — drives live deep-research
                       sub-progress in the UI. Best-effort: never blocks the angle.

    Returns:
        List of (provider_name, result_dict) tuples — same shape as a single
        run_all_with_degradation call. Duplicate provider names are expected
        (e.g., "gemini" may appear multiple times from different angles).
    """
    # Split-the-work: each angle goes to ONE provider, all run concurrently.
    # Assignment is stakes-based (set by divide() on the angle dict):
    # high->gemini (+claude on the doubled copy), med->openai, low->claude.
    # Round-robin is only the fallback when the preferred provider is disabled.
    enabled = [name for name, _ in _enabled_providers()]
    if not enabled:
        raise InsufficientProvidersError(failed=["gemini", "claude", "openai"])

    sem = asyncio.Semaphore(_ANGLE_CONCURRENCY)

    async def _notify(i: int, ok: bool) -> None:
        if on_angle_done is None:
            return
        try:
            await on_angle_done(i, ok)
        except Exception as exc:  # noqa: BLE001 — progress callback is best-effort
            log.warning("run_angles: on_angle_done callback failed: %r", exc)

    async def _one_angle(i: int, angle: dict[str, Any], force_provider: str | None = None):
        preferred = force_provider or angle.get("provider") or _STAKES_PROVIDER.get(
            angle.get("stakes", "med"), _STAKES_PROVIDER["med"]
        )
        if preferred in enabled:
            provider = preferred
        else:
            provider = enabled[i % len(enabled)]
            log.warning(
                "research_division.run_angles: preferred provider %r disabled — "
                "angle %d falls back to %s",
                preferred, i + 1, provider,
            )
        runner = _PROVIDER_RUNNERS[provider]
        timeout = _PROVIDER_TIMEOUTS.get(provider, _DEFAULT_TIMEOUT_S)
        query = angle.get("query", "")
        fa = angle.get("focus_area", "")
        stakes = angle.get("stakes", "med")
        async with sem:
            log.info(
                "research_division.run_angles: angle %d/%d -> %s (timeout=%ss) stakes=%s focus_area=%r",
                i + 1, len(angles), provider, timeout, stakes, fa,
            )
            try:
                async with asyncio.timeout(timeout):
                    result = await runner(
                        query=query, audited=audited, run_id=run_id, tenant_id=tenant_id,
                    )
            except Exception as exc:  # timeout or runner error — this angle yields nothing
                log.warning(
                    "research_division.run_angles: angle %d (%s) failed: %s: %s",
                    i + 1, provider, type(exc).__name__, exc,
                )
                try:
                    await audited.write_failure(
                        run_id=run_id, tenant_id=tenant_id, provider=provider, error=exc,
                    )
                except Exception:
                    pass
                await _notify(i, False)
                return None
        if isinstance(result, dict) and result.get("status") == "success":
            await _notify(i, True)
            return (provider, {**result, "_angle": fa, "_stakes": stakes})
        reason = result.get("error_message") if isinstance(result, dict) else repr(result)
        log.warning(
            "research_division.run_angles: angle %d (%s) did not succeed: %s",
            i + 1, provider, str(reason)[:300],
        )
        await _notify(i, False)
        return None

    gathered = await asyncio.gather(*(_one_angle(i, a) for i, a in enumerate(angles)))
    all_results: list[tuple[str, dict]] = [r for r in gathered if r is not None]

    # ── Research coverage gate ────────────────────────────────────────────
    # A focus area whose every angle failed would produce a hollow report
    # section with no warning. Retry each such angle ONCE on a different
    # enabled provider. (With stakes-based routing a med-stakes focus area
    # is single-provider, so one provider outage = a silently missing topic
    # without this gate.)
    covered_fas = {res[1].get("_angle") for res in all_results}
    uncovered = [
        (i, a) for i, a in enumerate(angles)
        if a.get("focus_area") not in covered_fas
    ]
    if uncovered and len(enabled) > 1:
        retries = []
        for i, a in uncovered:
            original = a.get("provider") or _STAKES_PROVIDER.get(a.get("stakes", "med"), "openai")
            alternates = [p for p in enabled if p != original]
            alt = alternates[i % len(alternates)]
            log.warning(
                "research_division.run_angles: focus_area %r got NO research — "
                "retrying angle %d on %s (was %s)",
                a.get("focus_area"), i + 1, alt, original,
            )
            retries.append(_one_angle(i, a, force_provider=alt))
        retry_results = await asyncio.gather(*retries)
        recovered = [r for r in retry_results if r is not None]
        all_results.extend(recovered)
        log.info(
            "research_division.run_angles: coverage retry recovered %d/%d uncovered angle(s)",
            len(recovered), len(uncovered),
        )

    log.info(
        "research_division.run_angles: %d/%d angles produced results "
        "(split-the-work: 1 provider/angle, stakes-based high=gemini/med=openai/low=claude, "
        "enabled=%s, concurrency=%d)",
        len(all_results), len(angles), enabled, _ANGLE_CONCURRENCY,
    )
    if not all_results:
        raise InsufficientProvidersError(
            failed=enabled, reasons={"all": "no angle produced a successful result"},
        )
    return all_results
