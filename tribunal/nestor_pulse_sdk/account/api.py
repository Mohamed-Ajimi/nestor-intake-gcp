"""
Account API -- GET /api/me (current user + workspace for the app chrome).

The web UI (Home/Projects/Project/NewBriefing/Report corners) calls /api/me on
load to render the workspace name + user avatar. The demo router provided this;
real mode had no equivalent, so the corner rendered empty and every call 401'd.

Shape mirrors demo/api.py::me -> {"workspace": {...}, "user": {...}}. The app_user
table has no display-name column (email only), so the name + initials are derived
from the email local-part -- works for any real user, not just the dev identity.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.auth.deps import get_current_user, get_db_session
from nestor_pulse_sdk.auth.provider import AuthClaims
from nestor_pulse_sdk.db.models import Org

router = APIRouter(tags=["account"])


def _display_name(email: str) -> str:
    """'jane.doe@acme.co' -> 'Jane Doe'."""
    local = (email or "").split("@")[0]
    cleaned = local.replace(".", " ").replace("_", " ").replace("-", " ").strip()
    return cleaned.title() or "User"


def _initials(name: str, email: str) -> str:
    parts = [p for p in name.split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    if parts:
        return parts[0][:2].upper()
    return (email or "?")[:2].upper()


@router.get("/api/me")
async def get_me(
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Current identity + workspace name for the app chrome (tenant-scoped)."""
    org = (await session.execute(
        select(Org).where(Org.id == uuid.UUID(user.tenant_id))
    )).scalar_one_or_none()

    name = _display_name(user.email)
    return {
        "workspace": {"name": org.name if org else "Workspace"},
        "user": {
            "name": name,
            "initials": _initials(name, user.email),
            "email": user.email,
        },
    }
