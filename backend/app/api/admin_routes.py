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
handlers in a threadpool (mirrors ``intake_routes.py`` / ``auth_routes.py``).
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
from app.mail import render as mail_render
from app.mail import resend as mail_resend

# Dutch subject for the set-password invite mail (the ONLY link-carrying mail, D-09).
_INVITE_SUBJECT = "Welkom bij Nestor Pulse — stel je wachtwoord in"

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


class MailResult(BaseModel):
    """Invite-mail response — a bare success flag, NEVER the action link (D-03 / T-5-14).

    The invite-mail endpoint SENDS the link (it does not hand it back to the browser),
    so unlike ``InviteResult`` it carries no ``action_link`` — the link only ever lives in
    the mail body and is never logged/audited.
    """

    success: bool


@admin_router.post("/users/{membership_id}/invite-mail")
def send_invite_mail(
    membership_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> MailResult:
    """Send a fresh-link set-password invite mail to a member (USER-01 / D-10 / QA-04).

    Mirrors ``invite_user``'s compose-external-then-audit shape. ``repo.get_membership``
    404-gates an unknown membership; a membership with NO email → 409 (do NOT send to
    ``None``). A FRESH action link is regenerated per send (D-10 — ``generate_set_password_link``,
    whose continue URL is the branded ``/auth/action`` handler from Task 2). The invite
    body (the only link-carrying mail, D-09) is rendered and sent via the faked Resend
    seam; a ``mail.sent`` audit row is written on the SAME session with structured
    metadata ONLY (NEVER the action link — Phase-5 audit contract, T-5-16). One handler
    serves both the InviteUserDialog resend and the member-list resend (D-10).
    """
    membership = repo.get_membership(membership_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    if not membership.email:
        # Never send to None — a membership without an email cannot be invited by mail.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Member has no email address to invite"
        )

    # Fresh action link per send (D-10). Its continue URL is /auth/action (Task 2).
    action_link = admin_users.generate_set_password_link(membership.email)
    html = mail_render.render_invite(cta_url=action_link)
    mail_resend.send(to=[membership.email], subject=_INVITE_SUBJECT, html=html)

    # QA-04 / T-5-16: audit on the SAME session — structured metadata ONLY, NEVER the link.
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="mail.sent",
        target=membership.provider_user_id or str(membership.id),
        space_id=membership.organization_id,
        metadata={"type": "invite"},
    )
    return MailResult(success=True)


# ===========================================================================
# Spaces — create / edit / soft-deactivate / reactivate (USER-03, no hard-delete)
# ===========================================================================


class SpaceCreateBody(BaseModel):
    """Create-space request — ``name`` + an optional ``slug``."""

    name: str
    slug: str | None = None


class SpacePatchBody(BaseModel):
    """Edit-space request — name/slug ONLY.

    There is deliberately NO ``status`` field here: deactivate/reactivate go through the
    dedicated POST routes, so a benign PATCH can never soft-delete a space (USER-03).
    """

    name: str | None = None
    slug: str | None = None


class SpaceView(BaseModel):
    """Safe projection of an organization (space)."""

    id: str
    name: str
    slug: str | None = None
    status: str


def _space_view(space) -> SpaceView:
    """Project an ``Organization`` ORM row onto the safe ``SpaceView``."""
    return SpaceView(
        id=str(space.id),
        name=space.name,
        slug=space.slug,
        status=space.status,
    )


@admin_router.get("/spaces")
def list_spaces(repo: AdminRepo = Depends(get_admin_session)) -> list[SpaceView]:
    """List all spaces (superadmin only), projected to safe views."""
    return [_space_view(row) for row in repo.list_spaces()]


@admin_router.post("/spaces")
def create_space(
    body: SpaceCreateBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Create a space (status defaults to ``active``) + ``space.created`` audit (USER-03)."""
    space = repo.create_space(name=body.name, slug=body.slug)
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.created",
        target=str(space.id),
        space_id=space.id,
        metadata={"name": body.name, "slug": body.slug},
    )
    return _space_view(space)


@admin_router.patch("/spaces/{space_id}")
def update_space(
    space_id: str,
    body: SpacePatchBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Edit a space's name/slug (never status) + ``space.updated`` audit.

    Empty patch -> 400; missing space -> 404 (the rowcount-0 outcome). The audit
    ``metadata`` records only the changed fields.
    """
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    rowcount = repo.update_space(space_id, **values)
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.updated",
        target=space_id,
        metadata=values,
    )
    return _space_view(repo.get_space(space_id))


@admin_router.post("/spaces/{space_id}/deactivate")
def deactivate_space(
    space_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Soft-deactivate a space (status -> ``deactivated``) + audit. NO hard-delete (D-10)."""
    rowcount = repo.set_space_status(space_id, "deactivated")
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.deactivated",
        target=space_id,
        metadata={},
    )
    return _space_view(repo.get_space(space_id))


@admin_router.post("/spaces/{space_id}/reactivate")
def reactivate_space(
    space_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Reactivate a space (status -> ``active``) + ``space.reactivated`` audit."""
    rowcount = repo.set_space_status(space_id, "active")
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.reactivated",
        target=space_id,
        metadata={},
    )
    return _space_view(repo.get_space(space_id))


# ===========================================================================
# Templates — clone a default into a space / edit the schema JSON (USER-03)
# ===========================================================================


class TemplateCloneBody(BaseModel):
    """Clone-template request — the new template's ``name`` + its ``schema`` JSON.

    "Clone a default into a space": the operator supplies the name and schema payload,
    which lands as a fresh template row scoped to the target space.
    """

    name: str
    schema: dict | None = None
    source_template_id: str | None = None


class TemplatePatchBody(BaseModel):
    """Edit-template request — the replacement ``schema`` JSON object."""

    schema: dict


class TemplateView(BaseModel):
    """Safe projection of an intake template."""

    id: str
    space_id: str
    name: str
    schema: dict | None = None


def _template_view(template) -> TemplateView:
    """Project an ``IntakeTemplate`` ORM row onto the safe ``TemplateView``."""
    return TemplateView(
        id=str(template.id),
        space_id=str(template.space_id),
        name=template.name,
        schema=template.schema,
    )


@admin_router.get("/spaces/{space_id}/templates")
def list_templates(
    space_id: str,
    repo: AdminRepo = Depends(get_admin_session),
) -> list[TemplateView]:
    """List templates owned by a space (the superadmin engine reaches any space)."""
    return [_template_view(row) for row in repo.list_templates(space_id)]


@admin_router.post("/spaces/{space_id}/templates")
def clone_template(
    space_id: str,
    body: TemplateCloneBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> TemplateView:
    """Clone a template into a space (USER-03) + ``template.cloned`` audit.

    The target space must exist (404 otherwise). The clone lands scoped to THAT space —
    the test asserts the new row's ``space_id`` equals the target.
    """
    if repo.get_space(space_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    template = repo.clone_template(space_id, name=body.name, schema=body.schema)
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="template.cloned",
        target=str(template.id),
        space_id=template.space_id,
        metadata={"source_template_id": body.source_template_id},
    )
    return _template_view(template)


@admin_router.patch("/spaces/{space_id}/templates/{template_id}")
def update_template(
    space_id: str,
    template_id: str,
    body: TemplatePatchBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> TemplateView:
    """Replace a template's ``schema`` JSON (USER-03) + ``template.updated`` audit.

    Pydantic guarantees ``schema`` parsed as a JSON object (a non-object body is a 422);
    a missing template -> 404 (the rowcount-0 outcome).
    """
    rowcount = repo.update_template(template_id, body.schema)
    if rowcount == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template not found")
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="template.updated",
        target=template_id,
        metadata={"schema_updated": True},
    )
    return _template_view(repo.get_template(template_id))
