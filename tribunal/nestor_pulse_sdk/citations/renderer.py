"""GET /api/sources/{source_id} -- the citation side-panel data contract.

Per CONTEXT.md `<ui_import>` Data contracts:
  - UI calls this endpoint and renders `snapshot_text` directly.
  - UI MUST NOT re-fetch the source's `url` (snapshot is the authority --
    dead URLs do not invalidate old reports).
  - Tenant context is scoped via JWT -> RLS; no tenant_id in the URL.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.auth.deps import get_db_session
from nestor_pulse_sdk.db.models import Source

router = APIRouter(prefix="/api/sources", tags=["sources"])


@router.get("/{source_id}")
async def get_source(
    source_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, Any]:
    """Return one source row in the UI-rendering shape.

    Returns 404 when the source doesn't exist OR exists in another tenant
    (RLS hides it -- both look identical to the client by design).
    """
    result = await session.execute(select(Source).where(Source.id == source_id))
    src = result.scalar_one_or_none()
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="source not found",
        )
    return {
        "id": str(src.id),
        "url": src.url,
        "title": src.title,
        "provider": src.provider,
        "fetched_at": src.fetched_at.isoformat() if src.fetched_at else None,
        "snapshot_text": src.snapshot_text,
    }
