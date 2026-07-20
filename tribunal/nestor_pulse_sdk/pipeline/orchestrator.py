"""SDKPipeline -- the real Plan 09 pipeline (replaces SDKPipelineStub).

The Runner protocol from `nestor_pulse_sdk/runs/adapter.py` is the contract:

    async def run(*, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID) -> dict

Pipeline shape (Phase 1 minimum):

    brief
      |
      v
    _extract_mission_brief        Phase 1 minimum: pass-through stub with the
      |                           brief as deep_research_prompt. Phase 2 expands
      |                           into a Claude Agent SDK lead-agent intake.
      v
    degraded_parallel             3 audited deep-research adapters; if Gemini
      |                           fails, brief still completes with the other 2.
      v
    extract_and_persist_citations claim/source/claim_source rows per D-07.
      |
      v
    run_synthesis                 final_synthesis_audited (audited Gemini call)
      |                           + build_quality_gate() grading.
      v
    {output_text, claim_count, verdict}

Plan 12 (closing-wave A/B) is the forcing function for fleshing out the
intake step, the full 10-step synthesis pipeline, and the citation
fine-grained extractor.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Optional

from nestor_pulse_sdk.pipeline.deep_researchers.degraded_parallel import (
    run_all_with_degradation,
)
from nestor_pulse_sdk.pipeline.synthesis.orchestrator import run_synthesis
from nestor_pulse_sdk.citations.extractor import extract_and_persist_citations

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)


class SDKPipeline:
    """Plan 09 Claude Agent SDK pipeline (Phase 1 minimum shape).

    Match the Runner protocol from `nestor_pulse_sdk/runs/adapter.py`.

    `audited` may be injected for tests. In production the worker calls
    `dispatch_runner('sdk')` which constructs `SDKPipeline()` with no
    argument; `run()` then lazily builds the audited client via
    `build_audited_client()` from the audit package.
    """

    def __init__(self, audited: Optional["AuditedLLMClient"] = None) -> None:
        self._audited = audited

    async def run(
        self, *, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> dict:
        log.info("sdk_pipeline_invoked", extra={"run_id": str(run_id)})

        audited = self._audited
        if audited is None:
            # Lazy build so test harnesses can inject a fake without forcing
            # provider clients to construct.
            from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client
            audited = build_audited_client()

        mission_brief = await self._extract_mission_brief(brief)

        # PHASE1-07: brief completes if >=2 of 3 providers succeed.
        provider_results = await run_all_with_degradation(
            query=mission_brief["deep_research_prompt"],
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )

        # Persist citation 3-table rows (D-07) BEFORE synthesis so the
        # synthesised brief can reference real source_ids if the synthesis
        # port grows to do so.
        from nestor_pulse_sdk.db.base import get_sessionmaker
        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            async with session.begin():
                await extract_and_persist_citations(
                    provider_results=provider_results,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    session=session,
                )

        synthesis = await run_synthesis(
            mission_brief=mission_brief,
            provider_results=provider_results,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )

        return {
            "output_text": synthesis["text"],
            "claim_count": synthesis.get("claim_count", 0),
            "verdict": synthesis.get("verdict"),
        }

    async def _extract_mission_brief(self, brief: str) -> dict:
        """Phase 1 minimum: pass-through.

        Phase 2 expands this into a Claude Agent SDK intake subagent that
        produces a structured mission_brief with focus_areas, topic, etc.
        For Plan 09 we pass the raw brief as the deep-research prompt and
        synthesise a single 'general' focus area.
        """
        return {
            "deep_research_prompt": brief,
            "focus_areas": [{"focus_area": "general"}],
        }
