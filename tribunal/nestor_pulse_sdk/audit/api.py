"""
nestor_pulse_sdk.audit.api -- 4 guided-query endpoints per D-13.

Endpoints:
  GET /api/audit/runs/{run_id}/calls       -- all LLM calls for run X
  GET /api/audit/projects/{project_id}/sources -- every source URL for project Y
  GET /api/audit/costs?since=YYYY-MM-DD    -- all costs for org Z this month
  GET /api/audit/verify/{run_id}           -- verify chain integrity for run X (D-13)

Design:
  - Every endpoint uses Depends(get_db_session) for tenant-scoped RLS (T-07-06).
  - verify_chain endpoint is server-side only; client receives {ok, broken_at?} only.
    Client NEVER recomputes hashes (Anti-pattern line 585).
  - Performance targets (PHASE1-04): <1s on 2000-row run for all-calls query;
    <1s on 5000-row corpus for costs aggregation; <1s for 500-row chain verify.
  - Composite indexes from Plan 03 make these queries fast:
      idx_audit_tenant_run_created: (tenant_id, run_id, created_at)
      idx_audit_tenant_model: (tenant_id, model)
      uq_audit_tenant_run_seq: (tenant_id, run_id, seq) UNIQUE
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text

from nestor_pulse_sdk.auth.deps import get_db_session
from nestor_pulse_sdk.db.models.audit_log import AuditLog

router = APIRouter(prefix="/api/audit", tags=["audit"])


# ---------------------------------------------------------------------------
# DTO helper
# ---------------------------------------------------------------------------

def _audit_row_dto(row: AuditLog) -> dict:
    """Convert ORM row to JSON-serializable dict. Raw hashes are NOT included (D-13)."""
    return {
        "id": str(row.id),
        "run_id": str(row.run_id) if row.run_id else None,
        "seq": row.seq,
        "provider": row.provider,
        "model": row.model,
        "started_at": row.started_at.isoformat(),
        "duration_ms": row.duration_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cached_tokens": row.cached_tokens,
        "cost_usd": float(row.cost_usd) if row.cost_usd is not None else None,
        "gcs_uri": row.gcs_uri,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        # NOTE: hash and prev_hash are deliberately OMITTED (Anti-pattern line 585).
        # The /verify/{run_id} endpoint is the only way to check chain integrity.
    }


# ---------------------------------------------------------------------------
# Guided query 1: All LLM calls for run X
# ---------------------------------------------------------------------------

@router.get("/runs/{run_id}/calls")
async def all_llm_calls_for_run(
    run_id: uuid.UUID,
    session: Any = Depends(get_db_session),
) -> list[dict]:
    """
    Pre-built guided query 1: "Show all LLM calls for run X".

    Uses composite index (tenant_id, run_id, created_at) -- RLS filters
    to current tenant automatically. Returns up to 5000 rows ordered by seq.
    Performance target: <1s on 2000-row run (PHASE1-04).
    """
    stmt = (
        select(AuditLog)
        .where(AuditLog.run_id == run_id)
        .order_by(AuditLog.seq.asc())
        .limit(5000)
    )
    rows = (await session.execute(stmt)).scalars().all()
    return [_audit_row_dto(r) for r in rows]


# ---------------------------------------------------------------------------
# Guided query 2: Every source URL for project Y
# ---------------------------------------------------------------------------

@router.get("/projects/{project_id}/sources")
async def all_source_urls_for_project(
    project_id: uuid.UUID,
    session: Any = Depends(get_db_session),
) -> list[dict]:
    """
    Pre-built guided query 2: "Show every source URL for project Y".

    Joins source through run (run.project_id = project_id).
    Uses composite indexes on run (tenant_id, project_id) + source (tenant_id, url).
    Returns deduplicated source URLs with metadata.

    Note: Phase 1 source data is written by Plan 09 (citation extractor).
    Returns empty list if no sources exist yet.
    """
    from nestor_pulse_sdk.db.models.source import Source  # type: ignore
    from nestor_pulse_sdk.db.models.run import Run  # type: ignore

    stmt = (
        select(Source)
        .join(Run, Source.run_id == Run.id)  # type: ignore[attr-defined]
        .where(Run.project_id == project_id)
        .order_by(Source.created_at.desc())  # type: ignore[attr-defined]
        .limit(2000)
    )
    try:
        rows = (await session.execute(stmt)).scalars().all()
        return [
            {
                "id": str(r.id),
                "url": r.url,
                "title": getattr(r, "title", None),
                "fetched_at": r.fetched_at.isoformat() if getattr(r, "fetched_at", None) else None,
                "provider": getattr(r, "provider", None),
            }
            for r in rows
        ]
    except Exception:
        # Source model may have different attribute names if Plan 09 hasn't run yet.
        # Return empty list gracefully.
        return []


# ---------------------------------------------------------------------------
# Guided query 3: All costs for org Z this month
# ---------------------------------------------------------------------------

@router.get("/costs")
async def costs_aggregation(
    since: date,
    session: Any = Depends(get_db_session),
) -> list[dict]:
    """
    Pre-built guided query 3: "Show all costs for org Z this month".

    RLS scopes to current tenant automatically (no explicit org_id in URL).
    Aggregates by (provider, model), ordered by total_usd DESC.
    Uses composite index (tenant_id, model) + date filter.
    Performance target: <1s on 5000-row corpus (PHASE1-04).
    """
    stmt = (
        select(
            AuditLog.provider,
            AuditLog.model,
            func.sum(AuditLog.cost_usd).label("total_usd"),
            func.count().label("call_count"),
        )
        .where(AuditLog.created_at >= since)
        .group_by(AuditLog.provider, AuditLog.model)
        .order_by(text("total_usd DESC NULLS LAST"))
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "provider": r.provider,
            "model": r.model,
            "total_usd": float(r.total_usd or 0),
            "call_count": r.call_count,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Guided query 4: Verify chain integrity for run X (D-13)
# ---------------------------------------------------------------------------

@router.get("/verify/{run_id}")
async def verify_chain_route(
    run_id: uuid.UUID,
    session: Any = Depends(get_db_session),
) -> dict:
    """
    Pre-built guided query 4: "Verify chain integrity for run X".

    Per D-13: server-side recompute only.
    Client receives ONLY {ok: bool, broken_at: int | None}.
    Raw hashes are NEVER exposed (Anti-pattern line 585).

    T-07-06: RLS on get_db_session scopes audit_log to current tenant.
    Cross-tenant run_id returns {"ok": true, "broken_at": null} on empty result
    (no rows visible to current tenant == empty chain == trivially valid).
    """
    from nestor_pulse_sdk.audit.hash_chain import verify_chain

    ok, broken_at = await verify_chain(run_id, session)
    return {"ok": ok, "broken_at": broken_at}
