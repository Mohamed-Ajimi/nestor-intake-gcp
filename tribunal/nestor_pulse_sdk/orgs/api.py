"""
nestor_pulse_sdk.orgs.api — POST /api/orgs/bootstrap

Plan: 01-17 Task 2 (D-16).

WHAT THIS ENDPOINT DOES:
  First-login org provisioning for admin-created Identity Platform testers.
  Called ONCE per new user immediately after their first sign-in, BEFORE
  any other API call (because all other routes require an existing app_user
  row via IdentityPlatformProvider.verify_id_token, which raises 403 if the
  row is absent — closing that hook is this endpoint's job).

SECURITY:
  T-17-02 (HIGH) — tenant-isolation escape prevention:
    - The endpoint uses a DEDICATED UNSCOPED DEPENDENCY (get_unscoped_token)
      that verifies the JWT but does NOT call get_db_session (which presupposes
      an existing tenant row and would 403 before bootstrap can run).
    - tenant_id is read ONLY from the signed JWT claim, NEVER from the request
      body (acceptance criterion grep: no read of tenant_id/org_id off the payload).
    - The provisioner (ensure_org_for_user) derives Org.id from the JWT-supplied
      tenant_id, not from any mutable caller-supplied field.

DEPENDENCY DESIGN (the "unscoped dep" pattern):
  The standard get_db_session dep (auth/deps.py) calls:
    1. get_current_user → verify_id_token → reads tenant_id from JWT
    2. get_db_session   → opens a session, calls set_tenant_context
  Step 2 requires the org row to exist (RLS needs a valid tenant UUID to set
  and the app_user row must exist for set_tenant_context to be meaningful).

  The bootstrap path legitimately bypasses this: the JWT is verified (step 1),
  but no existing tenant row is required. We open the DB session WITHOUT calling
  set_tenant_context first. The Org row is inserted in that unscoped session,
  making the row exist for all subsequent calls.

REFERENCES:
  - 01-CONTEXT.md D-16, D-05 (RLS), D-10 (AuthProvider abstraction)
  - identity-platform-bootstrap.md § "The post-signup tenant_id custom-claim flow"
  - nestor_pulse_sdk/auth/provider.py — the "/api/orgs/bootstrap unscoped dep" note
  - nestor_pulse_sdk/auth/identity_platform.py — the 403 hook this closes
  - nestor_pulse_sdk/auth/deps.py — get_current_user (NOT used here; get_db_session
    NOT used here — acceptance criterion verified by grep)
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from nestor_pulse_sdk.orgs.provision import ensure_org_for_user

router = APIRouter(prefix="/api/orgs", tags=["orgs"])


# ---------------------------------------------------------------------------
# Unscoped dependency — verifies JWT but does NOT require an existing app_user
# ---------------------------------------------------------------------------

async def get_unscoped_token(request: Request) -> dict:
    """
    Verify the bearer token and return the raw decoded claims dict.

    Unlike get_current_user, this dep:
      - Calls verify_id_token to validate signature/audience/expiry/revocation
      - Does NOT require a tenant_id custom claim (the user has none yet)
      - Does NOT look up an app_user row (the user has none yet)
      - Does NOT open an RLS-scoped session

    Returns a dict with at least:
      uid          — firebase uid (== provider_user_id)
      email        — user email
      tenant_id    — custom claim if already set (may be absent on first call)

    Raises HTTPException(401) on any token verification failure.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    parts = auth_header.split(None, 1)
    if len(parts) < 2:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    token = parts[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Lazy import — same pattern as identity_platform.py
    try:
        from firebase_admin import auth as fb_auth  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=503,
            detail="firebase-admin not installed; bootstrap unavailable",
        )

    # Ensure the Firebase Admin default app is initialized. This dep is the
    # FIRST authenticated call a brand-new tester makes (Login -> bootstrap,
    # before any get_current_user / provider call), so on a fresh instance the
    # provider's lazy _ensure_initialized has not run yet. Without this,
    # fb_auth.verify_id_token raises "The default Firebase app does not exist".
    from nestor_pulse_sdk.auth.identity_platform import _ensure_initialized
    project_id = os.environ.get("IDENTITY_PLATFORM_PROJECT_ID")
    if project_id:
        _ensure_initialized(project_id)

    try:
        decoded = fb_auth.verify_id_token(token, check_revoked=True)
    except Exception as exc:
        raise HTTPException(
            status_code=401, detail=f"Invalid token: {exc}"
        ) from exc

    return decoded


# ---------------------------------------------------------------------------
# Unscoped session dependency — opens a raw async session (no tenant context)
# ---------------------------------------------------------------------------

async def _get_unscoped_session():
    """
    Open an SQLAlchemy async session WITHOUT setting app.tenant_id.

    This is intentional: the Org row does not exist yet, so there is no
    valid tenant to scope to. The session runs as the application role with
    the org row INSERT bypassing RLS (Org is not RLS-scoped; it IS the tenant).
    """
    from nestor_pulse_sdk.db.base import get_sessionmaker  # type: ignore

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            yield session


# ---------------------------------------------------------------------------
# Bootstrap endpoint
# ---------------------------------------------------------------------------

@router.post("/bootstrap", tags=["orgs"])
async def bootstrap_org(
    request: Request,
    decoded: dict = Depends(get_unscoped_token),
    session: Any = Depends(_get_unscoped_session),
) -> dict:
    """
    POST /api/orgs/bootstrap

    First-login provisioning: creates the caller's org, app_user, and starter
    project (D-16). Idempotent — safe to call again if the first attempt failed.

    SECURITY: tenant_id comes ONLY from the signed JWT (decoded["tenant_id"]
    custom claim). It is NEVER read from the request body.

    If the user's JWT does not yet carry a tenant_id custom claim (first call),
    the endpoint assigns a fresh org_id (UUID4) as the tenant. On subsequent
    calls the claim is already set, so the same org_id is reused (idempotent).

    Returns
    -------
    {
        "tenant_id":        "<org UUID as str>",
        "app_user_id":      "<user UUID as str>",
        "starter_project_id": "<project UUID as str | null>",
    }
    """
    provider_uid: str = decoded.get("uid") or decoded.get("sub", "")
    if not provider_uid:
        raise HTTPException(status_code=401, detail="Token missing uid")

    email: str = decoded.get("email", "")

    # tenant_id from the signed JWT claim (T-17-02: never from request body).
    # On FIRST bootstrap the claim is absent → assign a new org_id.
    # On idempotent re-runs the claim is already set → reuse it.
    raw_tenant_id = decoded.get("tenant_id")
    if raw_tenant_id:
        tenant_id = str(raw_tenant_id)
        # Reuse the stable app_user_id if available from a prior run.
        # We generate a new UUID here since we can't look up the user
        # without a tenant context (the whole point of bootstrap).
        # The provisioner's get-or-create will match on org_id + provider_uid.
        app_user_id = str(uuid.uuid4())
    else:
        # First-time: generate both new IDs
        tenant_id = str(uuid.uuid4())
        app_user_id = str(uuid.uuid4())

    tenant_id_out = await ensure_org_for_user(
        app_user_id=app_user_id,
        tenant_id=tenant_id,
        provider_uid=provider_uid,
        email=email,
        session=session,
    )

    # Retrieve the starter project id for the response
    starter_project_id = None
    try:
        from sqlalchemy import select  # type: ignore
        from nestor_pulse_sdk.db.models import Project  # type: ignore
        from nestor_pulse_sdk.db.rls import set_tenant_context  # type: ignore

        await set_tenant_context(session, tenant_id_out)
        result = await session.execute(
            select(Project.id).where(
                Project.tenant_id == uuid.UUID(tenant_id_out)
            ).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is not None:
            starter_project_id = str(row)
    except Exception:  # noqa: BLE001 — project id is informational only
        pass

    return {
        "tenant_id": tenant_id_out,
        "app_user_id": app_user_id,
        "starter_project_id": starter_project_id,
    }
