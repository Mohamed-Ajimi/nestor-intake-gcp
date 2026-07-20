"""
Projects API -- CRUD for long-lived client engagements (D-06).

WHY this exists: the runs endpoints (runs/api.py) assume a project already
exists -- create_run / create_comparison 404 when payload.project_id has no
row. Nothing in the production app created those rows; only tests (via the ORM)
and the demo fixtures did. This router is where projects actually get created
and listed, so real-mode (non-demo) operation has a project to hang runs off of.

The list/detail responses mirror the demo GET /api/projects shape
(demo/api.py::_project_summary) so the same UI (Home/Projects/Project/
NewBriefing) renders identically in demo and real mode.

All queries are tenant-scoped via RLS (get_db_session SET LOCAL app.tenant_id
before the handler runs). The explicit tenant_id assignment on INSERT is both
required by the project_tenant_isolation WITH CHECK policy and additive D-05
defense; reads lean on RLS plus the natural tenant scoping of the policy.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.auth.deps import get_current_user, get_db_session
from nestor_pulse_sdk.auth.provider import AuthClaims
from nestor_pulse_sdk.db.models import Project, Run, User
from nestor_pulse_sdk.projects.schemas import CreateProjectRequest, ProjectResponse

router = APIRouter(prefix="/api/projects", tags=["projects"])

# Run statuses that count as "in flight" for the active-count badge (D-09).
_ACTIVE_STATUSES = ("queued", "running")


def _updated_rel(updated_at: datetime) -> str:
    """Human 'Updated Nd ago' string for the project card (Home.jsx strips
    the leading 'Updated '). Coarse buckets -- minutes / hours / days /
    months / years -- enough for an at-a-glance grid."""
    now = datetime.now(timezone.utc)
    # updated_at is timezone-aware (server_default now()); guard naive just in case.
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    secs = max(0, int((now - updated_at).total_seconds()))
    if secs < 60:
        return "Updated just now"
    if secs < 3600:
        return f"Updated {secs // 60}m ago"
    if secs < 86400:
        return f"Updated {secs // 3600}h ago"
    days = secs // 86400
    if days < 30:
        return f"Updated {days}d ago"
    if days < 365:
        return f"Updated {days // 30}mo ago"
    return f"Updated {days // 365}y ago"


def _summary(p: Project, briefing_count: int, active_count: int, owner_email: str | None) -> dict:
    """Grid/list summary matching demo/api.py::_project_summary keys."""
    return {
        "id": str(p.id),
        "name": p.name,
        "client_name": p.client_name,
        "status": p.status,
        "owner": owner_email,
        "team": [],  # no team model yet (D-06 single-owner); UI tolerates empty.
        "briefing_count": briefing_count,
        "active_count": active_count,
        "updated_rel": _updated_rel(p.updated_at),
        "created_at": p.created_at.isoformat(),
        "updated_at": p.updated_at.isoformat(),
    }


async def _run_counts(session: AsyncSession, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, tuple[int, int]]:
    """Map project_id -> (total_runs, active_runs) in one grouped query.

    FILTER (WHERE status IN (...)) gives the active count without a second
    round-trip. RLS scopes the run table to the tenant already."""
    if not project_ids:
        return {}
    rows = (await session.execute(
        select(
            Run.project_id,
            func.count().label("total"),
            func.count().filter(Run.status.in_(_ACTIVE_STATUSES)).label("active"),
        )
        .where(Run.project_id.in_(project_ids))
        .group_by(Run.project_id)
    )).all()
    return {r.project_id: (int(r.total), int(r.active)) for r in rows}


async def _owner_emails(session: AsyncSession, owner_ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Map app_user.id -> email for the given owners (avatar label)."""
    if not owner_ids:
        return {}
    rows = (await session.execute(
        select(User.id, User.email).where(User.id.in_(owner_ids))
    )).all()
    return {r.id: r.email for r in rows}


@router.post("", status_code=status.HTTP_201_CREATED, response_model=ProjectResponse)
async def create_project(
    payload: CreateProjectRequest,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> ProjectResponse:
    """
    Create a long-lived client engagement (D-06) for the caller's tenant.

    tenant_id comes from the JWT (never the body) so the project_tenant_isolation
    WITH CHECK passes and a caller can't plant a row in another tenant. The
    creating user becomes owner_user_id (FK app_user.id; get_current_user has
    already proven that app_user row exists for this tenant).
    """
    tenant_uuid = uuid.UUID(user.tenant_id)
    proj = Project(
        tenant_id=tenant_uuid,
        name=payload.name,
        client_name=payload.client_name,
        status="active",
        owner_user_id=uuid.UUID(user.app_user_id) if user.app_user_id else None,
    )
    session.add(proj)
    await session.flush()  # populate id / server defaults before serializing
    return ProjectResponse.model_validate(proj, from_attributes=True)


@router.get("")
async def list_projects(
    q: Optional[str] = Query(None, description="case-insensitive name/client filter"),
    status_filter: Optional[str] = Query(None, alias="status"),
    sort: Optional[str] = Query(None, description="alphabetical | most-briefings | recent"),
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> list[dict]:
    """
    List the tenant's projects as UI grid summaries (RLS-scoped).

    Same query params + ordering semantics as the demo endpoint so the
    Home / Projects screens behave identically in real mode.
    """
    projects = (await session.execute(
        select(Project).order_by(Project.updated_at.desc())
    )).scalars().all()

    counts = await _run_counts(session, [p.id for p in projects])
    emails = await _owner_emails(session, {p.owner_user_id for p in projects if p.owner_user_id})

    rows: list[dict] = []
    for p in projects:
        total, active = counts.get(p.id, (0, 0))
        rows.append(_summary(p, total, active, emails.get(p.owner_user_id)))

    # Filter / sort in-process to mirror demo semantics exactly.
    if q:
        ql = q.lower()
        rows = [r for r in rows if ql in r["name"].lower() or ql in (r["client_name"] or "").lower()]
    if status_filter and status_filter != "all":
        rows = [r for r in rows if r["status"] == status_filter]
    if sort == "alphabetical":
        rows.sort(key=lambda r: r["name"].lower())
    elif sort == "most-briefings":
        rows.sort(key=lambda r: -r["briefing_count"])
    # default: recently-updated (already ordered by the SQL above)
    return rows


@router.get("/{project_id}")
async def get_project(
    project_id: uuid.UUID,
    user: AuthClaims = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """
    Single project detail (RLS-scoped). Returns the grid summary plus the
    detail-view fields the UI reads (about / documents / collaborators).
    Those three have no DB backing yet (demo-only embellishments), so they
    come back empty -- the Project / NewBriefing screens tolerate that.
    """
    p = (await session.execute(
        select(Project).where(Project.id == project_id)
    )).scalar_one_or_none()
    if p is None:
        raise HTTPException(404, "project not found")

    counts = await _run_counts(session, [p.id])
    total, active = counts.get(p.id, (0, 0))
    emails = await _owner_emails(session, {p.owner_user_id} if p.owner_user_id else set())

    return {
        **_summary(p, total, active, emails.get(p.owner_user_id)),
        "about": None,
        "documents": [],
        "collaborators": [],
    }
