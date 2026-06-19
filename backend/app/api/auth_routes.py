"""Auth routers — the login-sync handshake + the default-deny base router (AUTH-01).

Two routers with deliberately different trust postures:

(a) ``auth_router`` — carries the ANONYMOUS ``POST /auth/session`` login-sync
    handshake. It must be reachable by a user who has NO ``role`` claim yet (that is
    the whole point — they call it to GET their claim), so it does NOT depend on
    ``get_current_identity`` (which 403s on a missing role). Instead it self-verifies:
    it extracts the bearer via ``_bearer`` and validates the token itself with
    ``auth.verify_id_token`` before deriving anything (threat T-03-12 — never trust an
    unverified caller). It then calls ``sync_claims_from_membership`` (the DB-driven,
    server-side claim write — D-03/D-04). No membership -> 403, no claim write
    (T-03-11). A forged/expired token -> 401 (verification fails).

(b) ``protected_router`` — ``APIRouter(dependencies=[Depends(get_current_identity)])``:
    the DEFAULT-DENY base every future feature router inherits, so every business
    endpoint requires a verified token carrying a ``role`` claim (AUTH-01 / threat
    T-03-17). It carries NO routes this phase (no feature endpoints yet); Phase 4+
    includes feature routers under it.

THE GOTCHA (threat T-03-13 / Pitfall 2): ``set_custom_user_claims`` does NOT refresh
    the CALLER's current token. After a ``{"synced": true}`` response the frontend MUST
    call ``getIdToken(true)`` to mint a token carrying the new claim — otherwise the very
    next protected request 403s on the still-missing claim in a silent loop. Plan 04
    implements that client handshake.

Sync ``def`` handler (not ``async def``): pg8000 is a blocking driver and the login-sync
    DB read runs in FastAPI's threadpool for sync handlers; an ``async def`` calling the
    sync engine would block the event loop (mirrors ``main.py``'s health handlers).

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md § Architecture Patterns 2
    ("Apply globally" — APIRouter(dependencies=[...])) + § Pitfall 1 (anonymous probes)
    + Pattern 3 (the /auth/session handshake)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "auth_routes.py" + § "main.py"
- D-03 (server-set claims) / D-04 (login-sync) / AUTH-01 (default-deny) / T-03-11,12,13,17
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials
from firebase_admin import auth

from app.auth.dependencies import _bearer, get_current_identity
from app.auth.session import sync_claims_from_membership

# ANONYMOUS router: /auth/session must be reachable by an un-synced user (no role
# claim yet), so this router carries NO get_current_identity dependency. The handler
# self-verifies the bearer instead (see below).
auth_router = APIRouter(prefix="/auth", tags=["auth"])

# DEFAULT-DENY base router (AUTH-01): every future feature router is included UNDER
# this one so it inherits get_current_identity and rejects unauthenticated/role-less
# callers by default. No routes here yet — Phase 4+ mounts feature routers (threat
# T-03-17). Exported for downstream include_router(..., parent=protected_router) wiring.
protected_router = APIRouter(dependencies=[Depends(get_current_identity)])


@auth_router.post("/session")
def post_session(
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Login-sync handshake: verify the token, then sync claims from the membership.

    ANONYMOUS-but-self-verifying: this endpoint does NOT use ``get_current_identity``
    (an un-synced user has no ``role`` claim and would 403 there before they could ever
    get synced). It instead extracts the bearer and verifies it itself, then writes the
    claim from the DB membership (server-side only — D-03).

    Returns ``{"synced": true}`` when claims were written OR were already present, and
    403 (no claim write) when the verified user has no membership (T-03-11). A forged or
    expired token fails ``verify_id_token`` -> 401.

    THE GOTCHA: on ``{"synced": true}`` the client MUST call ``getIdToken(true)`` to pull
    a fresh token carrying the new claim (T-03-13 / Pitfall 2 — plan 04 does this).
    """
    # Self-verify the caller's token before deriving ANYTHING from it (T-03-12). No
    # check_revoked (D-07), consistent with get_current_identity.
    try:
        decoded = auth.verify_id_token(cred.credentials)
    except auth.ExpiredIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except auth.InvalidIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    # sync_claims_from_membership returns True when it wrote a claim, False when the
    # token already carried a role (already synced) OR no membership exists. The
    # already-synced case carries a role claim, so distinguish it from the no-membership
    # case by re-checking the decoded token: if a role is already present it is "synced".
    wrote = sync_claims_from_membership(decoded)
    if wrote or decoded.get("role") is not None:
        return {"synced": True}

    # Verified user, but no membership row -> not authorized for any space (D-02: no
    # account was created). 403, with NO claim written (T-03-11).
    raise HTTPException(status.HTTP_403_FORBIDDEN, "No membership — not authorized")
