"""``get_current_identity`` — the per-request auth boundary (verify on every request).

This is the single seam that turns an untrusted ``Authorization: Bearer <id token>``
into a trusted :class:`app.auth.identity.Identity`. It realizes AUTH-02 (server-side
``verify_id_token`` on every protected request) and the enforcement half of AUTH-01
(default-deny; the legacy client-only guard is replaced by real server verification).

CRITICAL — read role/space_id ONLY from the verified token (D-03 / threat T-03-06):
    ``role`` and ``space_id`` come straight from the SDK-verified token's claims. NEVER
    read them from the request body, path, query, or any client-supplied header — that is
    the exact legacy elevation-of-privilege flaw this phase exists to kill. There is also
    NO DB lookup on this hot path (D-06): claims ride in the token (populated at
    login-sync), so verification is one Admin-SDK call and zero queries.

401 vs 403 split (pinned by ``backend/tests/test_auth_dependency.py``):
- **401** — authentication failed: no/blank bearer (HTTPBearer rejects), expired token,
  or any invalid/forged/tampered token (``verify_id_token`` raises).
- **403** — authenticated but NOT authorized: a verified token carrying no ``role`` claim
  (the user has no membership / login-sync has not run). The message points the client at
  the ``/auth/session`` sync handshake (plan 03).

D-07 (revocation re-check is Phase 5 / AUTH-04): ``verify_id_token`` is called WITHOUT
``check_revoked`` (defaults False) — no extra per-request Identity Platform round-trip
here. A revoked/disabled user keeps access until token expiry; short TTL bounds the window
(threat T-03-09, accepted).

Test seam: ``app.auth.dependencies.auth.verify_id_token`` is the patch target the
dependency suite mocks — no live IdP is ever called (threat T-03-02).

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md § Architecture Patterns 2
    + § Anti-Patterns (no check_revoked; never trust role from body/path/query)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "dependencies.py"
- D-03 (claims from token only) / D-06 (no DB on hot path) / D-07 (no check_revoked)
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth

from app.auth.identity import Identity

# auto_error=True: a missing/blank Authorization header is rejected by HTTPBearer
# itself (before the body runs), so unauthenticated requests never reach the handler.
_bearer = HTTPBearer(auto_error=True)


def get_current_identity(
    cred: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Identity:
    """Verify the bearer ID token and return the trusted :class:`Identity`.

    Raises ``HTTPException`` 401 on a missing/expired/invalid token and 403 on a verified
    token with no ``role`` claim. Claims are read ONLY from the verified token (D-03); no
    DB lookup happens here (D-06); ``check_revoked`` is never enabled (D-07).
    """
    try:
        # No check_revoked (defaults False) — revocation re-check is Phase 5 / AUTH-04
        # (D-07). The SDK validates signature/iss/aud/exp against Google's rotating keys.
        decoded = auth.verify_id_token(cred.credentials)
    except auth.ExpiredIdTokenError:
        # ExpiredIdTokenError subclasses InvalidIdTokenError — catch it FIRST so the
        # expired case gets its specific message instead of the generic "Invalid token".
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except auth.InvalidIdTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token")

    role = decoded.get("role")
    if role is None:
        # Authenticated, but the role custom claim is absent — login-sync has not run /
        # the user has no membership. 403 (not 401): the token is valid (D-03).
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "No role claim — sync session"
        )

    return Identity(
        uid=decoded["uid"],
        email=decoded.get("email"),
        role=role,
        space_id=decoded.get("space_id"),
    )
