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

    decoded = {"uid": "uid-sync-1", "email": email}  # no role yet -> needs sync
    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is True
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
    decoded = {"uid": "uid-orphan", "email": "no-membership@example.com"}

    with patch.object(session_mod.auth, "set_custom_user_claims") as mock_set:
        result = sync_claims_from_membership(decoded, session_factory=factory)

    assert result is False
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

    assert result is False
    mock_set.assert_not_called()
