"""USER-01 / AUTH-04 invite/deactivate/reactivate composition suite — faked Admin SDK.

This is a **Wave 0 RED scaffold** (the established Phase-1 precedent): the production
module ``app.auth.admin_users`` lands in plan 03, so these cases are RED until then. The
file must still *collect* cleanly on this dev box (no firebase-admin, no live IdP), so the
module is pulled via a module-level ``pytest.importorskip`` (skips, never errors, when the
wrapper does not exist yet).

Every Admin-SDK interaction is **mocked** by patching the wrapper module's own ``auth``
symbol (``app.auth.admin_users.auth.<call>``) — the exact patch-target style
``test_auth_session.py`` uses for ``set_custom_user_claims``. No test ever touches a live
Identity Platform (threat T-03-02 / the test-harness trust boundary): the wrapper's ``auth``
symbol is the ONLY patch target.

Contract authored against (plan 03 implements these signatures — 05-RESEARCH Patterns 1/5,
05-PATTERNS § test_admin_users.py):

    create_invited_user(email, *, role, space_id) -> uid
        auth.create_user(...) -> set_custom_user_claims(uid, {"role", "space_id"})
    generate_set_password_link(email) -> auth.generate_password_reset_link(email)
    deactivate_user(uid) -> auth.update_user(uid, disabled=True) + revoke_refresh_tokens(uid)
        (there is NO disable_user() — Anti-Patterns line 345)
    reactivate_user(uid) -> auth.update_user(uid, disabled=False)
    re-invite (EmailAlreadyExistsError) -> reconcile via auth.get_user_by_email(email)

Authoritative references:
- .planning/phases/05-user-space-management/05-RESEARCH.md
    § Pattern 1 (invite composition) / § Pattern 5 (deactivate/reactivate) /
    § Code Examples (faked-SDK invite test, lines ~419-431) / § Pitfall 5 (re-invite)
- .planning/phases/05-user-space-management/05-PATTERNS.md § test_admin_users.py
- backend/tests/test_auth_session.py (the patch.object(<module>.auth, ...) seam)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# app.auth.admin_users lands in plan 03 — skip cleanly until then so this collects.
admin_users = pytest.importorskip("app.auth.admin_users")


# ---------------------------------------------------------------------------
# (a) invite composition — create_user + set_custom_user_claims, returns the uid
# ---------------------------------------------------------------------------


def test_invite_creates_user_and_sets_claims():
    """``create_invited_user`` composes ``create_user`` -> ``set_custom_user_claims`` and
    returns the new uid; the claim payload carries exactly ``{"role", "space_id"}``."""
    fake_user = MagicMock(uid="new-uid")
    with patch.object(
        admin_users.auth, "create_user", return_value=fake_user
    ) as create_user, patch.object(
        admin_users.auth, "set_custom_user_claims"
    ) as set_claims:
        uid = admin_users.create_invited_user(
            "a@x.com", role="user", space_id="SPACE-UUID"
        )

    assert uid == "new-uid"
    create_user.assert_called_once()
    # The claim must carry the role + space_id for the invited user (USER-01 / Pattern 1).
    set_claims.assert_called_once_with(
        "new-uid", {"role": "user", "space_id": "SPACE-UUID"}
    )


def test_invite_role_is_user_for_invite_flow():
    """The invite flow assigns ``role="user"`` (D-01a — invites NEVER mint superadmins)."""
    fake_user = MagicMock(uid="invited-uid")
    with patch.object(
        admin_users.auth, "create_user", return_value=fake_user
    ), patch.object(admin_users.auth, "set_custom_user_claims") as set_claims:
        admin_users.create_invited_user(
            "b@x.com", role="user", space_id="00000000-0000-0000-0000-0000000000aa"
        )

    _uid, claims = set_claims.call_args[0]
    assert claims["role"] == "user", "invite must never set a superadmin role (D-01a)"


# ---------------------------------------------------------------------------
# (b) deactivate_user — update_user(disabled=True) AND revoke_refresh_tokens; NO disable_user
# ---------------------------------------------------------------------------


def test_deactivate_disables_and_revokes():
    """``deactivate_user`` calls BOTH ``update_user(uid, disabled=True)`` AND
    ``revoke_refresh_tokens(uid)`` — the IdP enforcement half of D-05/AUTH-04."""
    with patch.object(admin_users.auth, "update_user") as update_user, patch.object(
        admin_users.auth, "revoke_refresh_tokens"
    ) as revoke:
        admin_users.deactivate_user("victim-uid")

    update_user.assert_called_once()
    args, kwargs = update_user.call_args
    assert "victim-uid" in args, "update_user must target the deactivated uid"
    assert kwargs.get("disabled") is True, (
        "deactivate must call update_user(uid, disabled=True) — there is NO disable_user()"
    )
    revoke.assert_called_once_with("victim-uid")


def test_deactivate_goes_through_update_user_not_disable_user():
    """There is NO ``disable_user()`` in the Admin SDK (Anti-Patterns line 345). The
    behavioral guard is that deactivate routes through ``update_user`` (asserted in
    ``test_deactivate_disables_and_revokes``); this module must contain NO ``disable_user``
    call — enforced additionally by the acceptance grep on the source."""
    # update_user IS the deactivation primitive; revoke_refresh_tokens is the second half.
    # If a regression swaps in a (nonexistent) disable_user, the patch target above changes
    # and test_deactivate_disables_and_revokes fails — the source-grep is the static backstop.
    with patch.object(admin_users.auth, "update_user") as update_user, patch.object(
        admin_users.auth, "revoke_refresh_tokens"
    ):
        admin_users.deactivate_user("u")
    assert update_user.called, "deactivate must use update_user, never disable_user"


# ---------------------------------------------------------------------------
# (c) reactivate_user — update_user(disabled=False)
# ---------------------------------------------------------------------------


def test_reactivate_re_enables():
    """``reactivate_user`` calls ``update_user(uid, disabled=False)`` (D-06). Claims are
    unchanged on the membership row, so no claim re-issue is needed."""
    with patch.object(admin_users.auth, "update_user") as update_user:
        admin_users.reactivate_user("returning-uid")

    update_user.assert_called_once()
    args, kwargs = update_user.call_args
    assert "returning-uid" in args
    assert kwargs.get("disabled") is False, (
        "reactivate must call update_user(uid, disabled=False)"
    )


# ---------------------------------------------------------------------------
# (d) generate_set_password_link — same mechanism serves invite + forgot (D-02)
# ---------------------------------------------------------------------------


def test_generate_set_password_link_uses_password_reset_link():
    """``generate_set_password_link`` delegates to ``auth.generate_password_reset_link``
    (the SAME one-time action link serves invite 'set password' and 'forgot password', D-02)."""
    with patch.object(
        admin_users.auth,
        "generate_password_reset_link",
        return_value="https://idp/action?oobCode=xyz",
    ) as gen_link:
        link = admin_users.generate_set_password_link("a@x.com")

    gen_link.assert_called_once_with("a@x.com")
    assert link == "https://idp/action?oobCode=xyz"


# ---------------------------------------------------------------------------
# (e) re-invite — EmailAlreadyExistsError reconciled via get_user_by_email (Pitfall 5)
# ---------------------------------------------------------------------------


def test_reinvite_reconciles_existing_account_via_get_user_by_email():
    """Re-inviting an email whose IdP account already exists raises
    ``EmailAlreadyExistsError`` from ``create_invited_user`` (the wrapper does NOT
    swallow it — the endpoint catches it, per the documented contract); the
    reconcile seam is ``resolve_existing_uid`` via ``auth.get_user_by_email``
    (Pitfall 5)."""
    with patch.object(
        admin_users.auth,
        "create_user",
        side_effect=admin_users.auth.EmailAlreadyExistsError(
            "exists", cause=None, http_response=None
        ),
    ), patch.object(admin_users.auth, "set_custom_user_claims") as set_claims:
        with pytest.raises(admin_users.auth.EmailAlreadyExistsError):
            admin_users.create_invited_user(
                "dup@x.com", role="user", space_id="SPACE-UUID"
            )
    # No claims write may happen for an account that was not created here.
    set_claims.assert_not_called()

    existing = MagicMock(uid="existing-uid")
    with patch.object(
        admin_users.auth, "get_user_by_email", return_value=existing
    ) as get_by_email:
        uid = admin_users.resolve_existing_uid("dup@x.com")

    get_by_email.assert_called_once_with("dup@x.com")
    assert uid == "existing-uid", (
        "re-invite must reconcile to the existing account's uid via the seam"
    )
