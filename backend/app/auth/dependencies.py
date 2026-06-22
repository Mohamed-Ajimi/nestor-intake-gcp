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

AUTH-04 / D-04 (revocation re-check is ENABLED, Phase 5): ``verify_id_token`` is called
WITH ``check_revoked=True``. This adds one ``get_user`` round-trip to Identity Platform
per request (to read the revocation timestamp / disabled flag) — the deliberate,
accepted relaxation of Phase-3 D-06 "no extra lookup on the hot path," scoped to
admin-scale traffic (D-04). A deactivated user (``update_user(disabled=True)`` +
``revoke_refresh_tokens``) is therefore rejected IMMEDIATELY rather than keeping access
until token expiry (threat T-5-08). The earlier D-07 posture ("no check_revoked") is
superseded here — do not reintroduce it.

Exception ordering is LOAD-BEARING (Pattern 4 / threat T-5-08): ``RevokedIdTokenError``
and ``UserDisabledError`` are SUBCLASSES of ``InvalidIdTokenError``, so their ``except``
clauses MUST precede the generic ``InvalidIdTokenError`` clause — otherwise a
revoked/disabled token is swallowed as a vanilla "Invalid token" 401 and the precise
"Session revoked" / "Account disabled" signal is lost.

Test seam: ``app.auth.dependencies.auth.verify_id_token`` is the patch target the
dependency suite mocks — no live IdP is ever called (threat T-03-02).

Authoritative references:
- .planning/phases/05-user-space-management/05-RESEARCH.md § Pattern 4
    (the load-bearing exception order) + § Pitfall 2
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md § Architecture Patterns 2
    + § Anti-Patterns (never trust role from body/path/query)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "dependencies.py"
- D-03 (claims from token only) / AUTH-04 / D-04 (check_revoked=True, accepted get_user cost)
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

    Raises ``HTTPException`` 401 on a missing/expired/revoked/disabled/invalid token and
    403 on a verified token with no ``role`` claim. Claims are read ONLY from the verified
    token (D-03); no DB lookup happens here. ``check_revoked=True`` is enabled (AUTH-04 /
    D-04) so a deactivated user is rejected immediately (accepted ``get_user`` round-trip).
    """
    try:
        # check_revoked=True (AUTH-04 / D-04): re-check the revocation list + disabled
        # flag on every request so a deactivated user fails IMMEDIATELY (threat T-5-08).
        # The SDK validates signature/iss/aud/exp against Google's rotating keys.
        decoded = auth.verify_id_token(cred.credentials, check_revoked=True)
    except auth.ExpiredIdTokenError:
        # ExpiredIdTokenError subclasses InvalidIdTokenError — catch it FIRST so the
        # expired case gets its specific message instead of the generic "Invalid token".
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token expired")
    except auth.RevokedIdTokenError:
        # NEW (AUTH-04): refresh tokens revoked (deactivation). SUBCLASS of
        # InvalidIdTokenError — MUST precede the generic clause below (Pattern 4).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session revoked")
    except auth.UserDisabledError:
        # NEW (AUTH-04): account disabled (deactivation). SUBCLASS of
        # InvalidIdTokenError — MUST precede the generic clause below (Pattern 4).
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    except auth.InvalidIdTokenError:
        # Generic — MUST stay LAST of the four (the three above subclass it).
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
