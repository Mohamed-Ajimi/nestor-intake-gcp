"""Audited adapter for the legacy Claude deep researcher.

Consumes Plan 07's two-phase AuditedLLMClient API. Wraps
nestor_pulse/tools/claude_deep_researcher.deep_research_async WITHOUT
modifying it (D-01 / Pitfall 8).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from nestor_pulse.tools.claude_deep_researcher import (
    deep_research_async as legacy_claude_deep_research,
)

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

PROVIDER = "anthropic"
MODEL = "claude-sonnet-4-6"


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
        result = await legacy_claude_deep_research(query)
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
