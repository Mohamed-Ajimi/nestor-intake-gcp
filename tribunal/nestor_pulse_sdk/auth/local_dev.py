"""
Local dev-auth shim (LOCAL_DEV_AUTH) -- a FIXED dev identity for clicking
through the REAL app (real DB, real routers, real RLS tenant context, real
engines) WITHOUT standing up Identity Platform / Firebase login.

SECURITY: this is an auth bypass. It is wired in server.py ONLY when
`LOCAL_DEV_AUTH=1` AND DEMO_MODE is off -- mirroring the DEMO_MODE gate. It
must NEVER be enabled in a deployed environment; Cloud Run deploys never set
LOCAL_DEV_AUTH, and that env check is the only gate. Unlike DEMO_MODE (which
bypasses the DB + auth entirely and serves fixtures), this shim keeps the
ENTIRE real stack -- it only short-circuits token verification, returning a
fixed dev identity so the browser doesn't need a signed JWT.

The dev tenant/user UUIDs MUST match the rows seed_local_dev.py inserts, so
the (JWT-trusted) tenant_id maps to a real org row and the project-owner FK
(project.owner_user_id -> app_user.id) resolves.
"""
from __future__ import annotations

import uuid

from nestor_pulse_sdk.auth.provider import AuthClaims

# Fixed dev identity. Stable UUIDs so the seed + the shim agree across restarts.
DEV_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
DEV_USER_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
DEV_EMAIL = "dev@nestor.local"
DEV_PROVIDER_UID = "local-dev-user"
DEV_ORG_NAME = "Local Dev Workspace"
DEV_ORG_SLUG = "local-dev"


def dev_claims() -> AuthClaims:
    """The fixed AuthClaims returned for every request under LOCAL_DEV_AUTH.

    Installed as a FastAPI dependency override for get_current_user in
    server.py, so it transparently flows into get_db_session (which SET LOCALs
    app.tenant_id = DEV_TENANT_ID) and into every route that depends on the
    current user."""
    return AuthClaims(
        app_user_id=str(DEV_USER_ID),
        tenant_id=str(DEV_TENANT_ID),
        email=DEV_EMAIL,
        raw_provider_user_id=DEV_PROVIDER_UID,
    )
