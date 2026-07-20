"""Audited adapter for the SDK OpenAI deep researcher.

Consumes Plan 07's two-phase AuditedLLMClient API. Calls
AuditedLLMClient.openai_deep_research_raw() directly — the legacy
nestor_pulse/tools/openai_deep_researcher is NOT touched (D-01 / Pitfall 8).

Model is o4-mini-deep-research (CLAUDE.md Critical rules: o3-deep-research
requires org verification).

Transient connection/timeout errors on create() are retried automatically
inside openai_deep_research_raw (max_connect_retries=3, exponential back-off).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from nestor_pulse_sdk.audit.audited_llm_client import OPENAI_DEEP_RESEARCH_MODEL

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

PROVIDER = "openai"
MODEL = OPENAI_DEEP_RESEARCH_MODEL


async def deep_research_audited(
    *,
    query: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Returns the same {status, report|error_message} envelope as the legacy tool."""
    handle = await audited.start_call(
        provider=PROVIDER,
        model=MODEL,
        run_id=run_id,
        tenant_id=tenant_id,
        request={"query": query[:5000]},
    )
    try:
        result = await audited.openai_deep_research_raw(query)
        status = result.get("status", "error")
        if status not in ("success", "error", "timeout"):
            status = "error"
        await audited.end_call(handle, response=result, status=status)
        return result
    except Exception as exc:
        await audited.write_failure(
            run_id=run_id,
            tenant_id=tenant_id,
            provider=PROVIDER,
            error=exc,
        )
        return {"status": "error", "error_message": f"Research error: {exc}"}
