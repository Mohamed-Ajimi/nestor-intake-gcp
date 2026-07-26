"""Audited adapter for the SDK Gemini deep researcher.

Consumes Plan 07's two-phase AuditedLLMClient API (start_call -> AuditHandle ->
end_call). Calls AuditedLLMClient.gemini_deep_research_raw() directly — the
legacy nestor_pulse/tools/gemini_deep_researcher is NOT touched (D-01 / Pitfall 8).

Model: deep-research-max-preview-04-2026 (current-gen "Deep Research Max" on
Gemini 3.1 Pro; env-overridable via NESTOR_GEMINI_DR_AGENT).
"""
from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Awaitable, Callable

from nestor_pulse_sdk.audit.audited_llm_client import GEMINI_DEEP_RESEARCH_AGENT

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

PROVIDER = "google"
MODEL = GEMINI_DEEP_RESEARCH_AGENT


async def deep_research_audited(
    *,
    query: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    resume_job_id: str | None = None,
    on_job_started: "Callable[[str], Awaitable[None]] | None" = None,
) -> dict:
    """Returns the same {status, report|error_message} envelope as the legacy tool.

    On exception, writes a failure audit row via write_failure.

    R7 (plan 15.2-16): `resume_job_id` / `on_job_started` are forwarded verbatim
    to the raw method and change nothing here. The audit row is written the SAME
    way on a resumed poll as on a fresh dispatch — start_call, status clamp,
    end_call — so a resumed job still lands in the Art. 12 chain.
    """
    handle = await audited.start_call(
        provider=PROVIDER,
        model=MODEL,
        run_id=run_id,
        tenant_id=tenant_id,
        request={"query": query[:5000]},
    )
    try:
        result = await audited.gemini_deep_research_raw(
            query, resume_job_id=resume_job_id, on_job_started=on_job_started,
        )
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
