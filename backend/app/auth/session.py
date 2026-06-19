"""``sync_claims_from_membership`` — login-sync (membership -> custom claims, AUTH-03 / D-04).

This is the PROVISIONING side of auth: the single place that mirrors the
``organization_memberships`` source-of-truth row into Identity Platform custom
claims. ``get_current_identity`` (the per-request boundary, plan 02) reads
``role``/``space_id`` ONLY from the verified token; those claims are put there
HERE, server-side, exactly once at login — never trusted from the browser
(D-03 / threat T-03-11).

CRITICAL — claims come from the DB, never from client input (D-03/D-04 / T-03-11):
    ``role`` and ``space_id`` are derived from the membership row matched against the
    VERIFIED token's ``uid``/``email``. Nothing in the request body influences the
    claim. No membership -> no write -> the caller responds 403 (an authenticated user
    with no space is not authorized).

D-02 — no public self-registration: login-sync NEVER creates a user. It only syncs
    claims for an ALREADY-provisioned membership (the seed/CLI creates the first
    account here; Phase-5 invites create the rest). A decoded user with no membership
    row simply gets ``False`` back — no account, no claim, no row is created.

THE GOTCHA (threat T-03-13 / Pitfall 2): ``auth.set_custom_user_claims`` does NOT
    mutate the client's CURRENT ID token — the new claim only lands in the NEXT minted
    token. After a ``{"synced": true}`` response the frontend MUST force
    ``getIdToken(true)`` to pull a fresh token carrying the claim, otherwise every
    subsequent request 403s on a missing ``role`` claim in a silent loop. Plan 04
    implements that client handshake.

Claim-size budget (RESEARCH § THE-GOTCHA): the custom-claims blob has a hard 1000-byte
    limit. ``{"role": ..., "space_id": <uuid str>}`` is ~60 bytes — never add more.

Idempotency: when the decoded token ALREADY carries a ``role`` claim the function
    short-circuits with NO DB read and NO Admin SDK call (we don't re-write claims on
    every request — that would be a needless IdP round-trip per request).

Test seam: ``app.auth.session.auth.set_custom_user_claims`` is the patch target the
    plan-01 suite mocks — no live IdP is ever called in tests (threat T-03-02). The
    ``session_factory`` argument mirrors ``seed_dev.py``'s injection seam so the suite
    binds its conftest engine.

Authoritative references:
- .planning/phases/03-identity-platform-auth/03-RESEARCH.md § Architecture Patterns 3
    (sync_claims_from_membership + THE-GOTCHA refresh note + the 1000-byte claim limit)
- .planning/phases/03-identity-platform-auth/03-PATTERNS.md § "session.py"
- backend/scripts/seed_dev.py — the select().scalar_one_or_none() lookup + session_factory seam
- backend/tests/test_auth_session.py — the exact contract (found-writes / no-membership / already-synced)
- D-02 (no self-registration) / D-03 (server-set claims) / D-04 (login-sync)
"""

from __future__ import annotations

from enum import Enum

from firebase_admin import auth
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import OrganizationMembership


class SyncResult(str, Enum):
    """Authoritative outcome of ``sync_claims_from_membership`` (WR-04).

    The route maps this 3-state result cleanly to an HTTP status WITHOUT
    re-inspecting the decoded token (which conflated "already synced" and
    "no membership" under a single ``False`` return):

    - ``WROTE``          -> a claim was written this call            -> 200 {"synced": true}
    - ``ALREADY_SYNCED`` -> the token already carried a ``role``     -> 200 {"synced": true}
    - ``NO_MEMBERSHIP``  -> verified user has no membership row      -> 403 (T-03-11)
    """

    WROTE = "wrote"
    ALREADY_SYNCED = "already_synced"
    NO_MEMBERSHIP = "no_membership"


def _find_membership(session, provider_user_id: str, email: str | None):
    """Return the single membership row matching the verified token, or None.

    DETERMINISTIC, uid-first (CR-01 / CR-02):
    - First match strictly on ``provider_user_id == uid`` — the uid is bound by the
      IdP and is the authoritative subject; this never requires a verified email.
    - Only when NO uid row exists do we fall back to ``email`` — and the caller passes
      ``email=None`` unless the token asserts ``email_verified`` (CR-01), so an
      unverified email never matches a row (no superadmin-claim hijack).

    Both arms resolve to a single row via ``.scalars().first()`` (CR-02): this can
    NEVER raise ``MultipleResultsFound``, so the ``/auth/session`` handshake stays a
    deterministic auth decision instead of an unhandled 500 when a user has both a
    uid row and a separate email-only row.
    """
    row = (
        session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.provider_user_id == provider_user_id
            )
        )
        .scalars()
        .first()
    )
    if row is not None:
        return row
    if email is None:
        return None
    return (
        session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.email == email
            )
        )
        .scalars()
        .first()
    )


def sync_claims_from_membership(decoded: dict, session_factory=None) -> SyncResult:
    """Mirror the membership row into Identity Platform custom claims (AUTH-03).

    Returns an authoritative :class:`SyncResult` (WR-04) so the route maps the
    outcome to a status WITHOUT re-inspecting ``decoded``:
      - ``decoded`` already carries a ``role`` -> no-op (no DB read, no Admin call)
        -> ``SyncResult.ALREADY_SYNCED``.
      - membership found -> ``set_custom_user_claims`` once with ``role`` + ``space_id``
        (``None`` for superadmin = cross-tenant, ``str(organization_id)`` for a user)
        -> ``SyncResult.WROTE``.
      - no membership -> no write (caller responds 403; D-02: never create a user)
        -> ``SyncResult.NO_MEMBERSHIP``.

    Accepts an optional ``session_factory`` (testability seam, mirrors ``seed_dev.py``).

    CR-01: the email is trusted for matching ONLY when the verified token asserts
    ``email_verified``. Identity Platform issues fully signature-valid tokens for
    UNVERIFIED accounts; matching a seeded row (e.g. the ``superadmin``
    ``yanick@agenic.be`` row) by an unverified email would hand that row's claim to
    an attacker who merely self-registered the address. The uid match (bound by the
    IdP) needs no such guard.
    """
    # Already synced: the token carries a role claim, so there is nothing to do.
    # Short-circuit BEFORE any DB access or Admin SDK call so we don't re-write
    # claims (and incur an IdP round-trip) on every authenticated request.
    if decoded.get("role") is not None:
        return SyncResult.ALREADY_SYNCED

    uid = decoded["uid"]
    # CR-01: only trust the email for matching when the IdP says it is verified.
    # Otherwise pass None so _find_membership drops the email arm entirely.
    email = decoded.get("email") if decoded.get("email_verified") else None

    maker = session_factory if session_factory is not None else get_sessionmaker()
    with maker() as session:
        membership = _find_membership(session, provider_user_id=uid, email=email)
        if membership is None:
            # D-02: login-sync never creates a user — it only syncs claims for an
            # already-provisioned membership. No row -> no claim write; the caller
            # responds 403 (authenticated but unauthorized — no space).
            return SyncResult.NO_MEMBERSHIP

        # Claims are written SERVER-SIDE only (D-03), derived from the DB row — never
        # from client input. superadmin is cross-tenant (space_id=None); a user is
        # scoped to its organization (= space). Payload stays tiny (<1000-byte limit).
        space_id = (
            None
            if membership.role == "superadmin"
            else str(membership.organization_id)
        )
        auth.set_custom_user_claims(
            uid,
            {"role": membership.role, "space_id": space_id},
        )
        return SyncResult.WROTE
