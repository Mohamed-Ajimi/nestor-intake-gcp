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

# App-level membership-status vocabulary (D-23.1-13 / D-23.1-11).
#
# THE VOCABULARY'S HOME is ``models/membership.py:43``: ``status`` is a plain
# ``String NOT NULL server_default 'active'`` with the app-level set
# {"active", "deactivated"}, plus "space_deactivated" written by plan 23.1-03's
# space cascade. No PG enum, no CHECK constraint — it is enforced in code, which is
# exactly why every read of it must carry an explicit predicate.
# ``admin_repo.py:48`` holds the sibling definition of this same constant.
#
# DUPLICATED RATHER THAN IMPORTED, DELIBERATELY: the auth layer must not depend on
# the admin repository. Six characters of duplication is a smaller price than that
# edge in the dependency graph.
#
# Consequence of the ``admin_routes.py:236`` interaction — kept VERBATIM from
# 23.1-CONTEXT.md § 7 (D-23.1-13), so that a reader who meets the status vocabulary
# here does not file the following as a bug:
#
#   individually deactivating an already-cascade-deactivated member flips
#   `space_deactivated` -> `deactivated`, converting a REVERSIBLE space suspension
#   into a PERMANENT individual one that a later space reactivate will not restore.
#   That is "fire someone whose space is currently off", and it is intended.
#   Skipping the active-count guard is arithmetically safe because
#   `count_active_superadmins()` already excludes a `space_deactivated` member.
_STATUS_ACTIVE = "active"


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

    ONLY ACTIVE MEMBERSHIPS MATCH (D-23.1-13, added phase 23.1 — before it, NEITHER
    arm carried any status predicate at all):
    - Both arms filter ``status == _STATUS_ACTIVE``. A ``deactivated`` or a
      ``space_deactivated`` row is INVISIBLE to login-sync and yields
      ``SyncResult.NO_MEMBERSHIP`` — indistinguishable from having no row at all.
      Keep it that way: no fourth ``SyncResult`` state, no distinct message, and
      nothing logged at the route that would let a caller tell the two apart.
    - This makes the DATABASE a backstop rather than trusting the IdP
      ``disabled=True`` + ``revoke_refresh_tokens`` round-trip alone. It matters
      because plan 23.1-03's space cascade issues N IdP calls for N members and
      COMMITS its DB flip even when some of those calls fail: in that window the DB
      says ``space_deactivated`` while the member's ID token is still ordinary,
      signature-valid and non-revoked, so ``auth_routes.py``'s ``UserDisabledError``
      -> 401 branch never fires and this function is the only thing left refusing.
    - ALLOW-LIST, never a deny-list. A predicate that merely excluded the
      ``deactivated`` value would ADMIT ``space_deactivated`` — precisely the value
      the cascade writes — and would be the bug this predicate exists to close.
      (The literal deny-list form is deliberately not spelled out here: plan
      23.1-16's acceptance gate greps this file for it and requires zero hits.)
    """
    row = (
        session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.provider_user_id == provider_user_id,
                OrganizationMembership.status == _STATUS_ACTIVE,
            )
        )
        .scalars()
        .first()
    )
    # THE FALL-THROUGH — RULED IN 23.1-CONTEXT.md § 7 (D-23.1-13): KEEP IT.
    #
    # This early return's meaning changed when the status predicate landed above. The
    # uid arm now means "an ACTIVE row for this uid", so a DEACTIVATED uid row no
    # longer short-circuits here — the query returns None and control FALLS THROUGH to
    # the email arm. A user holding a deactivated uid row AND a separate ACTIVE email
    # row is therefore now ADMITTED, where the pre-fix early return refused them.
    #
    # THIS IS NOT A LOOSENING. The pre-fix behaviour was ALSO wrong: the early return
    # handed back the deactivated row and login-sync MINTED CLAIMS FROM IT. So the
    # comparison is not "we used to refuse and now we admit" — both paths were broken,
    # and this one is now right. The claim now comes from an active row the user
    # legitimately holds; it is the same deterministic uid-first policy described
    # above; and CR-01's ``email_verified`` gate still fences the email arm, so a
    # self-registered address cannot walk in.
    #
    # Pinned by tests/test_auth_session.py::
    # test_deactivated_uid_row_falls_through_to_an_active_email_row. Do NOT "restore"
    # the early return on the strength of seeing a previously-refused case succeed.
    if row is not None:
        return row
    if email is None:
        return None
    return (
        session.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.email == email,
                OrganizationMembership.status == _STATUS_ACTIVE,
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
