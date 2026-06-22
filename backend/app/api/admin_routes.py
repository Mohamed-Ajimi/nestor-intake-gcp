"""Superadmin admin API — invite / deactivate / spaces / templates (Phase 5).

The HTTP surface where USER-01 (invite), USER-03 (space + template management), AUTH-04
(deactivate/reactivate enforcement), and QA-04 (audit instrumentation) become real. The
router carries NO auth dependency of its own: it is mounted UNDER ``protected_router`` in
``app/main.py`` (inheriting ``Depends(get_current_identity)``) and every handler acquires
data access ONLY via ``Depends(get_admin_session)`` — the superadmin-only gate that
returns 403 for any non-superadmin BEFORE a session opens (T-5-13).

NO RAW DB SYMBOL is imported here (D-03 / T-5-17): all reads/writes go through the
injected :class:`app.db.admin_repo.AdminRepo`, and every mutation writes its
``audit_log`` row on the SAME request session via :func:`app.db.audit.log` (T-5-16 — no
orphan/missing audit rows). ``scripts/ci_no_raw_db_access.sh`` enforces the no-raw-DB
rule against this file.

Locked decisions realized here:

* D-01a / T-5-12 — the invite handler HARD-CODES ``role="user"``; ``role`` is not a body
  field, so the invite flow can never mint a superadmin.
* D-03 / T-5-14 — the invite response carries ONLY the action link; never a password or
  token. Reads are projected via ``_view`` helpers to safe fields only.
* T-5-15 — self-deactivation and last-active-superadmin deactivation both return 409
  BEFORE any IdP/DB mutation (superadmin self-lockout guard). Duplicate invite -> 409.
* D-10 / USER-03 — there is NO DELETE route for spaces (or anything): deactivation is a
  POST .../deactivate that flips ``status``; a hard-delete affordance is structurally
  absent.

Sync ``def`` handlers (not ``async def``): pg8000 is blocking and FastAPI runs sync
handlers in a threadpool (mirrors ``sample_routes.py`` / ``auth_routes.py``).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth import admin_users
from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.db import audit
from app.db.admin_repo import AdminRepo
from app.db.session import get_admin_session

# The admin feature router. NO auth dependency of its own — mounted UNDER
# protected_router in app/main.py, and each handler additionally Depends(get_admin_session)
# (the superadmin-only gate) for its root + cross-space data access.
admin_router = APIRouter(prefix="/admin", tags=["admin"])


# ===========================================================================
# Pydantic request/response shapes (T-5-12 / T-5-14)
# ===========================================================================


class InviteBody(BaseModel):
    """Invite request — ``email`` + the target ``space_id`` ONLY.

    There is deliberately NO ``role`` field (T-5-12 / D-01a): the handler hard-codes
    ``role="user"`` so the invite flow can never mint a superadmin from client input.
    """

    email: str
    space_id: str


class UserView(BaseModel):
    """Safe projection of a membership — no secrets, no tokens (T-5-14)."""

    id: str
    email: str | None = None
    space_id: str
    role: str
    status: str


class InviteResult(BaseModel):
    """Invite response — carries ONLY the action link (D-03 / T-5-14).

    NEVER a password or an IdP token: the invited user sets their own password via this
    one-time action link (the SAME mechanism later serves "forgot password", D-02).
    """

    uid: str
    space_id: str
    action_link: str


def _user_view(membership) -> UserView:
    """Project an ``OrganizationMembership`` ORM row onto the safe ``UserView``."""
    return UserView(
        id=str(membership.id),
        email=membership.email,
        space_id=str(membership.organization_id),
        role=membership.role,
        status=membership.status,
    )


# ===========================================================================
# Users — invite / list / deactivate / reactivate (USER-01, AUTH-04, QA-04)
# ===========================================================================


@admin_router.get("/users")
def list_users(repo: AdminRepo = Depends(get_admin_session)) -> list[UserView]:
    """List all memberships across spaces (superadmin only), projected to safe views."""
    return [_user_view(row) for row in repo.list_users()]


@admin_router.post("/users")
def invite_user(
    body: InviteBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> InviteResult:
    """Invite a USER-role account into exactly one space (USER-01 / QA-04).

    Ordering (Pattern 1): validate the target space exists -> reject an intentional
    duplicate (an already-active membership for that email in the space) with 409
    (Pitfall 5) -> mint the IdP account via the Admin-SDK wrapper with ``role="user"``
    (HARD-CODED, D-01a / T-5-12 — never a body field) -> write the membership row on the
    request tx -> generate the one-time action link -> write the ``user.invited`` audit
    row on the SAME session (QA-04 / T-5-16). The response carries ONLY the action link —
    never a password/token (D-03 / T-5-14).
    """
    # The target space must exist (a cross-space superadmin reaches any org).
    space = repo.get_space(body.space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    # Pitfall 5: an already-active membership for this email in the target space is an
    # intentional duplicate -> 409 BEFORE any IdP/DB mutation (never a second row/500).
    if repo.find_active_membership(body.space_id, body.email) is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "User already invited to this space"
        )

    # Mint the IdP account. role is HARD-CODED "user" (D-01a / T-5-12) — never client
    # input. A re-invite of an already-provisioned email raises EmailAlreadyExistsError;
    # we reconcile to the existing uid and map the intentional duplicate to 409.
    try:
        uid = admin_users.create_invited_user(
            body.email, role="user", space_id=body.space_id
        )
    except admin_users.auth.EmailAlreadyExistsError:
        admin_users.resolve_existing_uid(body.email)
        raise HTTPException(
            status.HTTP_409_CONFLICT, "User already exists"
        ) from None

    # Write the membership row on the request tx (role="user", status="active").
    repo.create_membership(
        organization_id=body.space_id,
        provider_user_id=uid,
        email=body.email,
        role="user",
        status="active",
    )

    # One-time action link for the invitee to set their own password (D-02 / D-03).
    action_link = admin_users.generate_set_password_link(body.email)

    # QA-04 / T-5-16: one audit row on the SAME session — structured metadata ONLY, never
    # the link/token/password (audit.log security contract).
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="user.invited",
        target=uid,
        space_id=space.id,
        metadata={
            "email": body.email,
            "assigned_space_id": body.space_id,
            "role": "user",
        },
    )

    return InviteResult(uid=uid, space_id=body.space_id, action_link=action_link)


@admin_router.post("/users/{membership_id}/deactivate")
def deactivate_user(
    membership_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> UserView:
    """Deactivate a member: IdP disable+revoke + status flip + audit (AUTH-04 / QA-04).

    Guardrails FIRST (T-5-15), BEFORE any IdP/DB mutation:
    * self-deactivation (target's ``provider_user_id`` == the acting ``identity.uid``)
      -> 409;
    * deactivating the LAST active superadmin (target role is ``superadmin`` and the
      active-superadmin count would drop to 0) -> 409.
    Then ``admin_users.deactivate_user`` (``update_user(disabled=True)`` +
    ``revoke_refresh_tokens`` — AUTH-04) -> ``set_membership_status(..., "deactivated")``
    -> ``user.deactivated`` audit row on the request session.
    """
    membership = repo.get_membership(membership_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # T-5-15 self-lockout guards — return 409 before touching the IdP or DB.
    if membership.provider_user_id == identity.uid:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cannot deactivate yourself"
        )
    if (
        membership.role == "superadmin"
        and membership.status == "active"
        and repo.count_active_superadmins() <= 1
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cannot deactivate the last active superadmin"
        )

    # AUTH-04: disable + revoke in the IdP, then flip the membership status.
    if membership.provider_user_id:
        admin_users.deactivate_user(membership.provider_user_id)
    repo.set_membership_status(membership_id, "deactivated")

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="user.deactivated",
        target=membership.provider_user_id,
        space_id=membership.organization_id,
        metadata={},
    )

    membership = repo.get_membership(membership_id)
    return _user_view(membership)


@admin_router.post("/users/{membership_id}/reactivate")
def reactivate_user(
    membership_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> UserView:
    """Reactivate a member: IdP un-disable + status flip + audit (AUTH-04 / D-06).

    ``admin_users.reactivate_user`` (``update_user(disabled=False)``) ->
    ``set_membership_status(..., "active")`` -> ``user.reactivated`` audit row. Claims are
    NOT re-issued here (login-sync is idempotent — A3).
    """
    membership = repo.get_membership(membership_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if membership.provider_user_id:
        admin_users.reactivate_user(membership.provider_user_id)
    repo.set_membership_status(membership_id, "active")

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="user.reactivated",
        target=membership.provider_user_id,
        space_id=membership.organization_id,
        metadata={},
    )

    membership = repo.get_membership(membership_id)
    return _user_view(membership)
