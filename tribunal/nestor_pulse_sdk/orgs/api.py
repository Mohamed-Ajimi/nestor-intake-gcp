"""
nestor_pulse_sdk.orgs.api -- the internal-seam provisioning endpoints.

Phase 14 (SEAM-02). The user-facing first-login bootstrap endpoint
(`POST /api/orgs/bootstrap`) + its unscoped Firebase dependency are RETIRED.
In their place are two idempotent seam endpoints driven ONLY by the intake
backend (verified by InternalCallerProvider):

  POST /api/orgs/ensure      -> {"tenant_id": <space_id>}
  POST /api/projects/ensure  -> {"tenant_id": <space_id>, "project_id": <id>}

Both use the STANDARD scoped session wiring (mirrors projects/api.py):
`user: AuthClaims = Depends(get_current_user)` + `session = Depends(get_db_session)`.
This works because server.py overrides get_current_user with get_internal_claims,
so `user.tenant_id` is the verified space_id and get_db_session has already
SET LOCAL app.tenant_id before the handler runs.

SECURITY (T-14-03): space_id is read ONLY from `user.tenant_id` (the verified
internal caller's header), NEVER from the request body.

REFERENCES:
  - 14-RESEARCH.md Pattern 3 (identity mapping, lazy idempotent provisioning)
  - nestor_pulse_sdk/orgs/provision.py -- ensure_org / ensure_project (salvaged)
  - nestor_pulse_sdk/projects/api.py -- the get_current_user + get_db_session wiring
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from nestor_pulse_sdk.auth.deps import get_current_user, get_db_session
from nestor_pulse_sdk.auth.provider import AuthClaims
from nestor_pulse_sdk.orgs.provision import ensure_org, ensure_project

router = APIRouter(tags=["orgs"])


@router.post("/api/orgs/ensure")
async def ensure_org_endpoint(
    user: AuthClaims = Depends(get_current_user),
    session: Any = Depends(get_db_session),
) -> dict:
    """Idempotently provision the Org for the caller's space (org.id == space_id).

    space_id comes from the verified internal caller (user.tenant_id), never the
    body. Returns the tenant_id for the caller to confirm the mapping.
    """
    tenant_id = await ensure_org(
        space_id=user.tenant_id, email=user.email, session=session
    )
    return {"tenant_id": tenant_id}


@router.post("/api/projects/ensure")
async def ensure_project_endpoint(
    user: AuthClaims = Depends(get_current_user),
    session: Any = Depends(get_db_session),
) -> dict:
    """Idempotently provision org + exactly one project for the caller's space.

    ensure_org runs first (creates the Org if absent and sets the tenant context
    for the RLS-FORCED project table), then ensure_project get-or-creates the
    single project. Returns the tenant_id + project_id; Phase 16 persists the
    project_id intake-side (D-06 boundary -- no intake column added now).
    """
    await ensure_org(space_id=user.tenant_id, email=user.email, session=session)
    project_id = await ensure_project(space_id=user.tenant_id, session=session)
    return {"tenant_id": user.tenant_id, "project_id": project_id}
