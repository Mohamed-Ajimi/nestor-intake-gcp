"""``admin_users`` — the privileged Admin-SDK user-lifecycle seam (USER-01 / AUTH-04).

This is the single place that wraps every privileged Identity Platform *Admin SDK*
call used by the Phase-5 user-management flows (invite / set-password link /
deactivate / reactivate). The browser NEVER touches these calls — they are all
server-side, mediated by the superadmin-only admin endpoints (threat T-5-10). This
module mirrors ``app/auth/session.py``'s established **mockable seam**: it imports
``from firebase_admin import auth`` at module level so the unit suite patches
``app.auth.admin_users.auth.<call>`` and no live IdP is ever reached in CI
(author-by-construction; threat T-5-10).

CRITICAL — claims come from the CALLER's ``role`` argument, never invented here
(D-01a / threat T-5-09):
    ``create_invited_user`` sets ``{"role": role, "space_id": space_id}`` with ``role``
    passed by the endpoint. The invite endpoint hard-codes ``role="user"`` (D-01a), so
    this flow can never mint a superadmin — but the WRAPPER does not encode that policy;
    it faithfully writes whatever role the caller hands it. The space_id is the org/space
    UUID string (``None`` only for a superadmin, which the invite path never produces).

CRITICAL — there is NO ``auth.disable_user()`` (Pattern 5 / Anti-Patterns):
    Deactivation is ``auth.update_user(uid, disabled=True)`` followed by
    ``auth.revoke_refresh_tokens(uid)``. Do NOT reference a ``disable_user`` call — it
    does not exist on the Admin SDK. ``revoke_refresh_tokens`` bumps the
    ``tokens_valid_after`` timestamp so that ``verify_id_token(..., check_revoked=True)``
    (the dependency boundary, AUTH-04) fails immediately for existing tokens.

Random password, never surfaced (D-02 / Anti-Patterns guard):
    ``create_invited_user`` creates the account with ``secrets.token_urlsafe(32)`` — a
    strong random password that is NEVER returned or logged. The invited user sets their
    own password via the action link from ``generate_set_password_link`` (the SAME
    Firebase mechanism serves invite "set password" and later "forgot password", D-02).
    Do NOT create a passwordless account.

Re-invite reconcile (Pitfall 5): a re-invite of an already-provisioned email makes
    ``auth.create_user`` raise ``auth.EmailAlreadyExistsError``. The endpoint catches it
    and calls :func:`resolve_existing_uid` (``auth.get_user_by_email``) to map the
    intentional duplicate to the existing uid (the endpoint then responds 409).

Test seam: ``app.auth.admin_users.auth.<call>`` is the patch target the
    ``test_admin_users.py`` suite mocks (mirrors ``test_auth_session.py``'s
    ``app.auth.session.auth.set_custom_user_claims`` patch). No live IdP is ever called
    (threat T-5-10). Firebase init is the process singleton in ``app/core/firebase.py``
    (ADC, no SA JSON key) — this module never re-initializes it.

Authoritative references:
- .planning/phases/05-user-space-management/05-RESEARCH.md
    § Pattern 1 (invite composition + ordering), § Pattern 5 (deactivate/reactivate —
    update_user, not disable_user), § Pitfall 5 (EmailAlreadyExistsError reconcile)
- .planning/phases/05-user-space-management/05-PATTERNS.md § "admin_users.py"
- backend/app/auth/session.py (the `from firebase_admin import auth` mockable-seam analog)
- USER-01 (invite) / AUTH-04 (deactivate) / D-01a (role hard-coded by endpoint) /
    D-02 (random password + action link) / D-05 (deactivate = disable + revoke)
"""

from __future__ import annotations

import secrets

from firebase_admin import auth


def create_invited_user(email: str, *, role: str, space_id: str) -> str:
    """Create the IdP account with a random password and set role/space_id claims.

    Composes the two privileged Admin-SDK calls of the invite flow (Pattern 1):
    ``auth.create_user`` with a strong random password (never surfaced — the user sets
    their own via the action link, D-02) then ``auth.set_custom_user_claims`` with
    ``{"role": role, "space_id": space_id}``. Returns the new uid.

    ``role`` is supplied by the CALLER (the invite endpoint hard-codes ``"user"`` per
    D-01a); this wrapper does not invent it (threat T-5-09). ``space_id`` is the
    org/space UUID string. A re-invite of an existing email raises
    ``auth.EmailAlreadyExistsError`` here — the caller catches it and reconciles via
    :func:`resolve_existing_uid` (Pitfall 5).
    """
    # Strong random password: it is NEVER returned or logged. The invited user sets
    # their own via generate_set_password_link's action link (D-02). Do NOT create a
    # passwordless account (Anti-Patterns guard).
    user = auth.create_user(email=email, password=secrets.token_urlsafe(32))
    # Claims are written SERVER-SIDE only, from the caller's role arg — never invented
    # here and never trusted from client input (D-03 / T-5-09). Payload stays tiny.
    auth.set_custom_user_claims(user.uid, {"role": role, "space_id": space_id})
    return user.uid


def generate_set_password_link(email: str) -> str:
    """Return a one-time Firebase action link for the user to set their password.

    The SAME mechanism serves the invite "set password" and later "forgot password"
    flows (D-02). The operator conveys this link to the invitee manually until the
    self-service email flow lands (Phase 10). ``ActionCodeSettings`` is optional and
    omitted here — the bare link is sufficient for Phase 5.
    """
    return auth.generate_password_reset_link(email)


def deactivate_user(uid: str) -> None:
    """IdP enforcement half of deactivation (AUTH-04 / D-05).

    ``auth.update_user(uid, disabled=True)`` blocks new sign-in AND — paired with the
    AUTH-04 ``check_revoked=True`` boundary — makes ``verify_id_token`` fail for the
    disabled account; ``auth.revoke_refresh_tokens(uid)`` bumps ``tokens_valid_after``
    so existing tokens are rejected immediately. There is NO ``auth.disable_user()`` —
    deactivation is ``update_user`` (Anti-Patterns); do not reference a disable_user call.
    """
    auth.update_user(uid, disabled=True)
    auth.revoke_refresh_tokens(uid)


def reactivate_user(uid: str) -> None:
    """Un-disable the IdP account (AUTH-04 / D-06).

    Only flips the ``disabled`` flag back to ``False``. Claims are UNCHANGED on the
    membership row, so they are NOT re-issued here (A3) — the user's next valid token /
    ``/auth/session`` already carries ``role``/``space_id`` and login-sync is idempotent.
    """
    auth.update_user(uid, disabled=False)


def resolve_existing_uid(email: str) -> str:
    """Resolve the uid of an already-provisioned email (re-invite reconcile, Pitfall 5).

    On a re-invite, ``create_invited_user`` raises ``auth.EmailAlreadyExistsError``; the
    endpoint catches that and calls this helper to map the intentional duplicate to the
    existing account's uid via ``auth.get_user_by_email`` (the endpoint then responds
    409 Conflict). Kept here so all Admin-SDK reads stay behind the same mockable seam.
    """
    return auth.get_user_by_email(email).uid
