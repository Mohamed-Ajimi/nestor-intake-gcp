"""Synthesis orchestrator -- runs the (Phase 1 minimum) audited synthesis flow.

Plan 09 Task 2 ships a single-step orchestrator: `final_synthesis_audited`
produces the brief, then `build_quality_gate()` (Plan 08) grades it. The
full 10-step iterate-loop port (Chunker -> ... -> QualityGate with retries)
is deferred to Plan 12 (closing-wave A/B), per the scope note in steps.py.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from nestor_pulse_sdk.pipeline.synthesis.steps import (
    extract_focus_areas,
    final_synthesis_audited,
)
from nestor_pulse_sdk.pipeline.synthesis.quality_gate import build_quality_gate

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)


async def run_synthesis(
    *,
    mission_brief: dict,
    provider_results: list[tuple[str, dict]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Run the audited synthesis flow and return {text, claim_count, verdict}.

    Returns a dict so the SDKPipeline caller can surface either the success
    payload or the verdict for downstream UI / closing-wave A/B analysis.
    """
    focus_areas = extract_focus_areas(mission_brief) or ["general"]

    synthesis_text = await final_synthesis_audited(
        mission_brief=mission_brief,
        provider_reports=provider_results,
        audited=audited,
        run_id=run_id,
        tenant_id=tenant_id,
    )

    gate = build_quality_gate()
    try:
        verdict = await gate.grade(
            synthesis=synthesis_text,
            mission_brief=mission_brief,
            focus_areas=focus_areas,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )
        verdict_dict = verdict.as_dict()
    except Exception as exc:
        # Phase 1 minimum: don't block the run on a gate failure. Surface
        # the error in the returned dict so Plan 11 / Plan 12 visibility
        # works without aborting the worker.
        log.warning("quality_gate_error", exc_info=exc)
        verdict_dict = {"pass": None, "error": str(exc)}

    return {
        "text": synthesis_text,
        "claim_count": 0,  # Plan 12 fills this from the per-step claim list.
        "verdict": verdict_dict,
    }
