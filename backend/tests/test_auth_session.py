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

D-23.1-13 — THE MEMBERSHIP-STATUS BACKSTOP (phase 23.1):
    Until phase 23.1 ``_find_membership`` filtered on NO status at all — neither the
    ``provider_user_id`` arm nor the ``email`` arm carried a status predicate — so
    login-sync would happily mint ``role``/``space_id`` claims for a ``deactivated``
    and (after plan 23.1-03's space cascade) a ``space_deactivated`` membership. The
    ONLY thing preventing that was the IdP-side ``disabled=True`` +
    ``revoke_refresh_tokens`` round-trip.

    The DB predicate added in plan 23.1-16 is a BACKSTOP to that IdP disablement, not
    a replacement for it. It matters because the cascade issues N IdP calls for N
    members and commits its DB flip even when some of those calls fail: in that window
    the database says ``space_deactivated`` while the member can still authenticate.
    The cases below are written around that window, not around the happy path — a
    refusal suite that stays green with no predicate in the code is testing nothing.

    Every case asserts on the RECORDED ``set_custom_user_claims`` CALL LIST, not merely
    on the returned ``SyncResult``: minting a claim is the harm, and a result value
    alone does not prove nothing was minted.
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


# ---------------------------------------------------------------------------
# D-23.1-13 (SEC-01 / SEC-02): only an ACTIVE membership earns a claim.
#
# THE WINDOW THESE CASES LIVE IN. Two exclusions bound the defect, and both are
# outside this file: ``sync_claims_from_membership`` short-circuits with NO DB READ
# when the token already carries a ``role`` (``ALREADY_SYNCED``), and
# ``auth_routes.py`` catches ``UserDisabledError`` -> 401 before login-sync runs. What
# is left is exactly one window — a token WITHOUT baked-in claims requesting a sync,
# for a member whose IdP disable did not land. That is the partial-cascade failure,
# and it is what ``test_partial_cascade_failure_is_refused_by_the_db_alone`` drives.
#
# ALLOW-LIST, NEVER DENY-LIST. The predicate under test is ``== "active"``. A
# predicate that merely excluded ``deactivated`` would ADMIT ``space_deactivated``
# — the exact value plan 23.1-03's cascade writes — so every refusal below is
# asserted for BOTH inactive values on BOTH arms.
# ---------------------------------------------------------------------------


def _seed_space_with_membership(
    factory,
    *,
    space_id: str,
    slug: str,
    email: str | None = None,
    provider_user_id: str | None = None,
    role: str = "user",
    status: str = "active",
):
    """Seed one Organization + one OrganizationMembership through the ORM.

    The same seeding path the pre-existing cases use (no raw SQL), factored out
    because these cases need the SAME row shape at three different ``status``
    values. Idempotent per space, since the container/engine fixture is
    session-scoped and rows outlive a single test.
    """
    from sqlalchemy import select

    from app.db.models import Organization, OrganizationMembership

    with factory() as s:
        with s.begin():
            if s.get(Organization, space_id) is None:
                s.add(Organization(id=space_id, name=slug, slug=slug))
            existing = (
                s.execute(
                    select(OrganizationMembership).where(
                        OrganizationMembership.organization_id == space_id
                    )
                )
                .scalars()
                .first()
            )
            if existing is None:
                s.add(
                    OrganizationMembership(
                        organization_id=space_id,
                        email=email,
                        provider_user_id=provider_user_id,
                        role=role,
                        status=status,
                    )
                )


def _claims_of(mock_set):
    """Pull the claims payload out of the recorded ``set_custom_user_claims`` call
    (mirrors the extraction the pre-existing cases do inline)."""
    _args, kwargs = mock_set.call_args
    return kwargs.get("claims") if "claims" in kwargs else mock_set.call_args[0][-1]


# --- UID ARM ---------------------------------------------------------------


@pytest.mark.integration
def test_uid_arm_deactivated_membership_mints_nothing(engine):
    """A membership matched by ``provider_user_id`` whose status is ``deactivated``
    must be invisible to login-sync: ``NO_MEMBERSHIP`` and ZERO claim writes.

    The returned ``SyncResult`` is not the property that matters — the claim call
    list is. A minted ``role``/``space_id`` claim is what every later request's
    ``get_current_identity`` trusts (``dependencies.py`` makes no DB call, D-06), so
    one write here hands a revoked member a working session.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b101"
    uid = "uid-deactivated-1"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="uid-deactivated-space",
        email="uid-deactivated-1@example.com",
        provider_user_id=uid,
        role="user",
        status="deactivated",
    )

    decoded = {"uid": uid, "email": "uid-deactivated-1@example.com", "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "a deactivated uid row must mint NOTHING; recorded calls: "
        f"{mock_set.call_args_list}"
    )


@pytest.mark.integration
def test_uid_arm_space_deactivated_membership_mints_nothing(engine):
    """The same on the uid arm for ``space_deactivated`` — the value plan 23.1-03's
    cascade writes.

    This case is what makes the allow-list non-optional: a deny-list that merely
    excluded ``deactivated`` would pass every other refusal test in this file and
    ADMIT this one.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b102"
    uid = "uid-space-deactivated-1"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="uid-space-deactivated-space",
        email="uid-space-deactivated-1@example.com",
        provider_user_id=uid,
        role="user",
        status="space_deactivated",
    )

    decoded = {
        "uid": uid,
        "email": "uid-space-deactivated-1@example.com",
        "email_verified": True,
    }
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "a space_deactivated uid row must mint NOTHING (a deny-list would admit it); "
        f"recorded calls: {mock_set.call_args_list}"
    )


@pytest.mark.integration
def test_uid_arm_active_membership_writes_claim(engine):
    """The unchanged happy path on the uid arm — kept adjacent to the two refusals
    so a regression in EITHER direction (over-refusing, or under-refusing) is one
    file away."""
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b103"
    uid = "uid-active-1"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="uid-active-space",
        email="uid-active-1@example.com",
        provider_user_id=uid,
        role="user",
        status="active",
    )

    decoded = {"uid": uid, "email": "uid-active-1@example.com", "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.WROTE
    mock_set.assert_called_once()
    claims = _claims_of(mock_set)
    assert claims.get("role") == "user"
    assert str(claims.get("space_id")) == space_id


# --- EMAIL ARM -------------------------------------------------------------


@pytest.mark.integration
def test_email_arm_deactivated_membership_mints_nothing(engine):
    """A membership matched ONLY by ``email`` (no ``provider_user_id`` on the row)
    whose status is ``deactivated`` -> ``NO_MEMBERSHIP``, zero claim writes.

    The email arm is tested independently of the uid arm on purpose: patching one
    select and missing the other is the exact half-fix D-23.1-13 exists to avoid, and
    the email arm is the one an attacker self-registering a known address reaches.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b104"
    email = "email-deactivated-1@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="email-deactivated-space",
        email=email,
        provider_user_id=None,
        role="user",
        status="deactivated",
    )

    decoded = {"uid": "uid-no-row-b104", "email": email, "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "a deactivated email-only row must mint NOTHING; recorded calls: "
        f"{mock_set.call_args_list}"
    )


@pytest.mark.integration
def test_email_arm_space_deactivated_membership_mints_nothing(engine):
    """The same on the email arm for ``space_deactivated`` — again the deny-list
    trap, asserted on the arm a half-fix is most likely to miss."""
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b105"
    email = "email-space-deactivated-1@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="email-space-deactivated-space",
        email=email,
        provider_user_id=None,
        role="user",
        status="space_deactivated",
    )

    decoded = {"uid": "uid-no-row-b105", "email": email, "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "a space_deactivated email-only row must mint NOTHING; recorded calls: "
        f"{mock_set.call_args_list}"
    )


@pytest.mark.integration
def test_email_arm_active_membership_writes_claim(engine):
    """The unchanged happy path on the email arm."""
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b106"
    email = "email-active-1@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="email-active-space",
        email=email,
        provider_user_id=None,
        role="user",
        status="active",
    )

    decoded = {"uid": "uid-no-row-b106", "email": email, "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.WROTE
    mock_set.assert_called_once()
    claims = _claims_of(mock_set)
    assert claims.get("role") == "user"
    assert str(claims.get("space_id")) == space_id


@pytest.mark.integration
def test_cr01_unverified_email_refused_against_an_active_row(engine):
    """CR-01 STILL HOLDS after the status predicate lands.

    The pre-existing ``test_unverified_email_does_not_match_seeded_row`` proves the
    same guard, but this phase adds a way for that test to pass for the WRONG reason:
    if the seeded row were inactive, the status predicate alone would refuse it and
    the case would stay green even with ``email_verified`` gating deleted. So this
    case seeds an ACTIVE superadmin row — the status predicate cannot refuse it, and
    the ONLY thing standing between the attacker and a superadmin claim is CR-01's
    ``email_verified`` check in ``sync_claims_from_membership``.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b107"
    email = "active-victim-superadmin@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="active-victim-space",
        email=email,
        provider_user_id=None,
        role="superadmin",
        status="active",
    )

    # Attacker self-registered the known address: signature-valid token, matching
    # email, but email_verified is falsy and the uid matches no row.
    decoded = {"uid": "uid-attacker-b107", "email": email, "email_verified": False}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "an unverified email must not inherit an ACTIVE row's claim (CR-01); "
        f"recorded calls: {mock_set.call_args_list}"
    )


# --- THE PARTIAL-CASCADE SCENARIO — the reason this plan exists -------------


@pytest.mark.integration
def test_partial_cascade_failure_is_refused_by_the_db_alone(engine):
    """THE WINDOW. The DB is the backstop; the IdP round-trip is the thing that failed.

    Scenario, exactly as plan 23.1-03's cascade can leave production: the operator
    deactivates a space, the cascade commits the DB flip to ``space_deactivated`` for
    every member, then its ``deactivate_user`` Admin SDK call for THIS member raises
    and the cascade reports 502. Nothing about this member's IdP account changed — no
    ``disabled=True``, no ``revoke_refresh_tokens`` — so their existing ID token is
    ordinary, signature-valid and non-revoked, and ``auth_routes.py``'s
    ``UserDisabledError`` -> 401 branch never fires.

    Note what is DELIBERATELY absent from this test: any simulation of IdP-side
    disablement. That absence IS the test. If login-sync only refuses this member
    when the IdP also refuses them, then the IdP is the sole control and the cascade's
    accepted partial-failure mode is a live authorization hole.

    The token carries no ``role`` claim, so the ``ALREADY_SYNCED`` short-circuit does
    not fire either and the DB read really happens.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b108"
    uid = "uid-cascade-orphan"
    email = "cascade-orphan@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="cascade-orphan-space",
        email=email,
        provider_user_id=uid,
        role="superadmin",
        status="space_deactivated",
    )

    decoded = {"uid": uid, "email": email, "email_verified": True}
    assert decoded.get("role") is None, "the ALREADY_SYNCED short-circuit must not fire"

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.NO_MEMBERSHIP
    assert mock_set.call_args_list == [], (
        "a space_deactivated member whose IdP disable never landed must be refused by "
        f"the DB alone; recorded calls: {mock_set.call_args_list}"
    )


# --- INDISTINGUISHABILITY --------------------------------------------------


@pytest.mark.integration
def test_deactivated_member_is_indistinguishable_from_a_non_member(engine):
    """A deactivated member and a user with NO row at all produce the IDENTICAL result.

    Asserted by COMPARING the two results, not by asserting each is
    ``NO_MEMBERSHIP`` separately. The property being pinned is that a caller cannot
    tell the two apart (T-23.1-75); two independent ``is NO_MEMBERSHIP`` assertions
    would still pass if a future change gave one of them its own distinct state, and
    would say nothing about the pair. Equality says it directly.
    """
    factory = _session_factory(engine)
    space_id = "00000000-0000-0000-0000-00000000b109"
    uid = "uid-deactivated-b109"
    email = "deactivated-b109@example.com"
    _seed_space_with_membership(
        factory,
        space_id=space_id,
        slug="indistinguishable-space",
        email=email,
        provider_user_id=uid,
        role="user",
        status="deactivated",
    )

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_deactivated:
        deactivated_result = sync_claims_from_membership(
            {"uid": uid, "email": email, "email_verified": True},
            session_factory=factory,
        )

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_stranger:
        stranger_result = sync_claims_from_membership(
            {
                "uid": "uid-stranger-b109",
                "email": "stranger-b109@example.com",
                "email_verified": True,
            },
            session_factory=factory,
        )

    assert deactivated_result == stranger_result, (
        "a deactivated member and a non-member must be INDISTINGUISHABLE; got "
        f"{deactivated_result!r} vs {stranger_result!r}"
    )
    assert deactivated_result is SyncResult.NO_MEMBERSHIP
    assert mock_deactivated.call_args_list == mock_stranger.call_args_list == []


# --- THE CHANGED FALL-THROUGH (ruled in 23.1-CONTEXT § 7, D-23.1-13) -------


@pytest.mark.integration
def test_deactivated_uid_row_falls_through_to_an_active_email_row(engine):
    """RULED: KEEP the fall-through. Pinned here so it is a decision on record.

    Adding the predicate changes CONTROL FLOW, because the uid arm is an EARLY
    RETURN. Before the fix, a deactivated uid row was returned and the email arm never
    ran. After the fix the uid query yields None for that row and control FALLS
    THROUGH — so this user, who holds a deactivated row in one space AND a separate
    ACTIVE row in another, is now ADMITTED via the active row where before they were
    refused.

    THIS IS NOT A LOOSENING. The pre-fix behaviour was ALSO wrong: it handed back the
    deactivated uid row and login-sync minted claims FROM IT. Both paths were broken;
    this one is now right. The claim now comes from access the user legitimately
    holds, it is the same deterministic uid-first policy the docstring describes, and
    CR-01's ``email_verified`` guard still fences the email arm.

    The assertion is on the SPACE the claim carries, not merely on ``WROTE``: before
    the fix this returned ``WROTE`` too, from the DEACTIVATED row's space. Asserting
    the active row's space is what distinguishes the two behaviours.
    """
    factory = _session_factory(engine)
    dead_space = "00000000-0000-0000-0000-00000000b110"
    live_space = "00000000-0000-0000-0000-00000000b111"
    uid = "uid-two-rows"
    email = "two-rows@example.com"

    # Row 1: matched by uid, DEACTIVATED. Pre-fix this short-circuited the email arm.
    _seed_space_with_membership(
        factory,
        space_id=dead_space,
        slug="fallthrough-dead-space",
        email=email,
        provider_user_id=uid,
        role="user",
        status="deactivated",
    )
    # Row 2: same person, same verified email, a DIFFERENT space, ACTIVE.
    _seed_space_with_membership(
        factory,
        space_id=live_space,
        slug="fallthrough-live-space",
        email=email,
        provider_user_id=None,
        role="user",
        status="active",
    )

    decoded = {"uid": uid, "email": email, "email_verified": True}
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is SyncResult.WROTE
    mock_set.assert_called_once()
    claims = _claims_of(mock_set)
    assert str(claims.get("space_id")) == live_space, (
        "the claim must come from the ACTIVE email row, not the deactivated uid row "
        f"({dead_space}); got {claims.get('space_id')!r}"
    )
