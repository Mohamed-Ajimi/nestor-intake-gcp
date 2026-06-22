"""AUTH-03 / D-04 login-sync suite — ``sync_claims_from_membership`` mirrors the
membership row into Identity Platform custom claims exactly once at login.

Contract (plan 03 implements ``app.auth.session``):
- a ``superadmin`` / ``user`` membership row exists for the decoded user's email
  -> write the ``role`` (+ ``space_id``) custom claim and return ``True``;
- no membership row -> return ``False`` and DO NOT write a claim (the caller then
  responds 403 — an authenticated user with no space is not authorized);
- the decoded token ALREADY carries a ``role`` -> no-op (return ``False``, no Admin
  SDK call) so we don't re-write claims on every request.

**Wave 0 RED scaffold** (D-09): ``app.auth.session`` lands in plan 03, so these
cases are RED until then; the file must still *collect* on this dev box, hence the
module-level ``pytest.importorskip``. The Admin SDK is **mocked** —
``app.auth.session.auth.set_custom_user_claims`` is patched in every case; no live
``set_custom_user_claims`` call is ever made (threat T-03-02). The live-DB
membership-lookup cases are ``@pytest.mark.integration`` so they SKIP without
Docker, mirroring ``test_health.py::test_readyz_db_ok``.

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md
    § Code Examples (login-sync: membership -> set_custom_user_claims) +
      § Validation Architecture (AUTH-03 / D-04 row)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md
    § test_auth_session.py -- engine fixture via session factory, mocked Admin SDK
- backend/scripts/seed_dev.py -- the membership select().scalar_one_or_none() the
    sync mirrors, and the ``session_factory`` injection seam reused here
- D-09 (mocks only; live IdP deferred) / threat_model T-03-02
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# app.auth.session lands in plan 03 — skip cleanly until then so this collects.
session_mod = pytest.importorskip("app.auth.session")

sync_claims_from_membership = session_mod.sync_claims_from_membership
SyncResult = session_mod.SyncResult


@pytest.fixture(autouse=True)
def _clear_engine_caches():
    """Reset the engine lru_cache around every test so a fixture-bound engine
    never leaks into the next case (idiom borrowed from test_health.py)."""
    from app.db import base

    base.get_engine.cache_clear()
    base._get_connector.cache_clear()
    yield
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()


def _session_factory(engine):
    """Build a sessionmaker bound to the conftest ``engine`` fixture so the
    sync reads the membership row from the live test DB (mirrors seed_dev's
    ``session_factory`` injection seam)."""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.mark.integration
def test_membership_found_writes_claim(engine):
    """A superadmin/user membership exists for the decoded email -> the claim is
    written once and the function returns True."""
    from sqlalchemy import select

    from app.db.models import Organization, OrganizationMembership

    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000a001"
    email = "synced-user@example.com"

    # Seed one org + one membership the sync should find.
    with factory() as s:
        with s.begin():
            if s.get(Organization, space_id) is None:
                s.add(Organization(id=space_id, name="Sync Space", slug="sync-space"))
            existing = s.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == space_id,
                    OrganizationMembership.email == email,
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(
                    OrganizationMembership(
                        organization_id=space_id,
                        email=email,
                        role="user",
                    )
                )

    # CR-01: the row has no provider_user_id yet (email-only seed), so this matches
    # by email — which is now trusted ONLY when the token asserts email_verified.
    decoded = {"uid": "uid-sync-1", "email": email, "email_verified": True}  # needs sync
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.WROTE
    mock_set.assert_called_once()
    # The claim payload must carry the role (and the space_id) from the membership.
    _args, kwargs = mock_set.call_args
    claims = kwargs.get("claims") if "claims" in kwargs else mock_set.call_args[0][-1]
    assert claims.get("role") == "user"
    assert str(claims.get("space_id")) == space_id


@pytest.mark.integration
def test_no_membership_no_write(engine):
    """No membership row for the decoded email -> return False and NEVER write a
    claim (the caller responds 403)."""
    factory = _session_factory(engine)
    decoded = {"uid": "uid-orphan", "email": "no-membership@example.com", "email_verified": True}

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    mock_set.assert_not_called()


@pytest.mark.integration
def test_unverified_email_does_not_match_seeded_row(engine):
    """CR-01: a signature-valid token whose email matches a seeded row but whose
    email is NOT verified must NOT inherit that row's claim. The attacker registers
    a seeded member's email (e.g. the superadmin), gets a valid token with
    email_verified=False, and must be treated as having NO membership (no claim
    write, 403) — the uid does not match the seeded row either."""
    from sqlalchemy import select

    from app.db.models import Organization, OrganizationMembership

    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000a002"
    email = "victim-superadmin@example.com"

    # Seed an email-only row (no provider_user_id yet) the attacker tries to hijack.
    with factory() as s:
        with s.begin():
            if s.get(Organization, space_id) is None:
                s.add(Organization(id=space_id, name="Victim Space", slug="victim-space"))
            existing = s.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == space_id,
                    OrganizationMembership.email == email,
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(
                    OrganizationMembership(
                        organization_id=space_id,
                        email=email,
                        role="superadmin",
                    )
                )

    # Attacker token: matches the seeded email, but email_verified is falsy and the
    # uid does NOT match any row.
    decoded = {"uid": "uid-attacker", "email": email, "email_verified": False}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    mock_set.assert_not_called()


def test_already_synced_is_noop():
    """The decoded token already carries a ``role`` claim -> no DB lookup, no
    Admin SDK call, return False (idempotent: claims aren't re-written per request).

    No integration marker: this short-circuits before any DB access, so it runs
    on the dev box without Docker.
    """
    decoded = {"uid": "uid-already", "email": "already@example.com", "role": "superadmin"}

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=None)

    assert result is SyncResult.ALREADY_SYNCED
    mock_set.assert_not_called()


# ---------------------------------------------------------------------------
# USER-02 (Phase 5): login-sync against an INVITE-created membership row (JIT)
#
# The Phase-5 invite flow (plan 04) writes an organization_memberships row carrying
# the invited user's provider_user_id (= the IdP uid set at invite) plus role="user"
# and status="active". USER-02 is proven by driving the EXISTING
# ``sync_claims_from_membership`` against exactly that row shape and asserting it
# attaches the role/space_id claim — no NEW production code (Pattern 2). This case is
# selectable with ``-k invite_created_row`` per 05-VALIDATION's requirement map.
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_login_sync_invite_created_row(engine):
    """First login of an invited user -> claims attached from the invite-created membership
    row, matched by ``provider_user_id`` (= the invited uid). The claim payload carries the
    row's ``role`` and ``space_id`` (USER-02 / JIT provisioning)."""
    from sqlalchemy import select

    from app.db.models import Organization, OrganizationMembership

    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000a003"
    invited_uid = "uid-invited-1"
    email = "invited-user@example.com"

    # Seed an INVITE-shaped membership row: provider_user_id set to the invited uid (the
    # invite flow stamps it), role="user", and the row exists BEFORE the user's first login.
    with factory() as s:
        with s.begin():
            if s.get(Organization, space_id) is None:
                s.add(
                    Organization(id=space_id, name="Invite Space", slug="invite-space")
                )
            existing = s.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == space_id,
                    OrganizationMembership.provider_user_id == invited_uid,
                )
            ).scalar_one_or_none()
            if existing is None:
                s.add(
                    OrganizationMembership(
                        organization_id=space_id,
                        provider_user_id=invited_uid,
                        email=email,
                        role="user",
                    )
                )

    # The invited user's first verified token: uid matches the invite-stamped
    # provider_user_id, email_verified True (they set their password via the action link).
    decoded = {"uid": invited_uid, "email": email, "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.WROTE
    mock_set.assert_called_once()
    _args, kwargs = mock_set.call_args
    claims = kwargs.get("claims") if "claims" in kwargs else mock_set.call_args[0][-1]
    assert claims.get("role") == "user", "invite-created row must yield role='user' claim"
    assert str(claims.get("space_id")) == space_id, (
        "the claim's space_id must be the invited user's assigned space (USER-02)"
    )
