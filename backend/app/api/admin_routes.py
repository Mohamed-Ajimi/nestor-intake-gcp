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

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.errors import INVALID_LOCALE, CodedError
from app.auth import admin_users
from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.db import audit
from app.db.admin_repo import (
    AdminRepo,
    # The membership-status vocabulary lives with the accessors that read it. Imported
    # rather than re-typed as literals here so the space cascade's third value
    # (``space_deactivated``) can never drift between the write side (this module) and
    # the allow-list reads (``admin_repo.py``) — a silent drift would make the selective
    # reactivate restore nothing.
    _STATUS_ACTIVE,
    _STATUS_DEACTIVATED,
    _STATUS_SPACE_DEACTIVATED,
)
from app.db.session import get_admin_session
from app.mail import render as mail_render
from app.mail import resend as mail_resend

_log = logging.getLogger(__name__)

# Per-locale subjects for the set-password invite mail (the ONLY link-carrying mail,
# D-09). Mirrors intake_routes._SUBJECTS (D-12): the subject is selected with the SAME
# resolved locale as the rendered body so the two can never desync; an unknown locale
# falls back to "nl" (the render layer's fallback base).
_INVITE_SUBJECTS: dict[str, str] = {
    "nl": "Welkom bij Nestor Pulse — stel je wachtwoord in",
    "fr": "Bienvenue chez Nestor Pulse — définissez votre mot de passe",
    "en": "Welcome to Nestor Pulse — set your password",
}


def _invite_subject_for(locale: str) -> str:
    """Return the invite subject in ``locale`` (nl fallback — matches the body fallback)."""
    return _INVITE_SUBJECTS.get(locale) or _INVITE_SUBJECTS["nl"]

# The app-level allowed space-locale set (D-07 / V5 input validation). Enforced IN CODE,
# NOT a PG enum (mirrors the organizations.default_locale / status column rationale, 0010).
# MUST match me_routes._ALLOWED and the frontend switcher's fixed nl/fr/en options.
_ALLOWED_LOCALES = {"nl", "fr", "en"}

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

    D-23.2-10: the target space must also be ACTIVE. A space cascade only ever visits the
    members that existed when it ran, so an invite accepted afterwards mints an ACTIVE
    member inside a deactivated space — a hole in SEC-02 that no cascade will ever close,
    and one the operator cannot see because their console reads "deactivated".
    """
    # The target space must exist (a cross-space superadmin reaches any org).
    space = repo.get_space(body.space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    # D-23.2-10 — refuse BEFORE the duplicate check and BEFORE any IdP call, so a refusal
    # never leaves an enabled Identity Platform account with no membership row pointing at
    # it. 409 rather than 404: the caller is a superadmin who legitimately lists this
    # space, so hiding it would be a lie about a resource they can already see. The
    # message must stay distinct from the duplicate 409 below — both are 409, so the text
    # is the only thing telling the operator which problem they actually have.
    if space.status != _STATUS_ACTIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot invite a user into a deactivated space",
        )

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

    D-23.2-10: refuses (409) when the member's SPACE is deactivated. Without that guard
    this verb hands access back inside a dead space one member at a time — an undocumented
    way to walk a space cascade backwards while the operator's console still reads
    "deactivated". Its sibling :func:`deactivate_user` deliberately carries NO such guard:
    deactivating a member of a deactivated space only ever NARROWS access, so it stays
    allowed. Do not symmetrise the two.
    """
    membership = repo.get_membership(membership_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    # D-23.2-10 — evaluated before the IdP call, the flip and the audit row, so a refusal
    # has NO side effect at all. A missing space is a data-integrity impossibility here
    # (organization_id is a NOT NULL FK), so it is folded into the same 409 rather than
    # given its own arm — an unreachable branch would be untestable and would rot.
    space = repo.get_space(membership.organization_id)
    if space is None or space.status != _STATUS_ACTIVE:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Cannot reactivate a user in a deactivated space",
        )

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

    # WR-04 / D-16: mirror `_run_intake_send`'s failure discipline so the two send surfaces
    # share ONE contract (HTTP 200 + `{success: false}` on transport failure, not a raw 500).
    # Any transport failure — a Resend non-2xx (`raise_for_status`), a network error, a
    # missing RESEND_API_KEY (`KeyError`), or an IdP failure generating the fresh link —
    # returns `MailResult(success=False)` with NO audit row (audit-on-success-only).
    # D-07 (Phase 11): the invitee has NO membership locale yet at invite time, so the
    # invite body resolves to the TARGET SPACE's default_locale -> "nl" (never the sending
    # superadmin's UI). A missing space row (should not happen for a real membership) -> "nl".
    space = repo.get_space(membership.organization_id)
    invite_locale = (space.default_locale if space is not None else None) or "nl"

    try:
        # Fresh action link per send (D-10). Its continue URL is /auth/action (Task 2).
        action_link = admin_users.generate_set_password_link(membership.email)
        html = mail_render.render_invite(cta_url=action_link, locale=invite_locale)
        mail_resend.send(
            to=[membership.email],
            subject=_invite_subject_for(invite_locale),
            html=html,
        )
    except Exception:  # noqa: BLE001 -- any transport/link failure is a non-send.
        _log.warning("invite mail send failed for membership %s", membership_id)
        return MailResult(success=False)

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
    """Create-space request — ``name`` + an optional ``slug`` + an optional ``default_locale``.

    ``default_locale`` (D-07 / D-10) is the space's base display language. When omitted the
    ``organizations.default_locale`` column ``server_default`` ("nl") applies. A supplied
    value is validated against {nl,fr,en} in the handler (``CodedError`` INVALID_LOCALE).
    """

    name: str
    slug: str | None = None
    default_locale: str | None = None


class SpacePatchBody(BaseModel):
    """Edit-space request — name/slug/default_locale ONLY.

    There is deliberately NO ``status`` field here: deactivate/reactivate go through the
    dedicated POST routes, so a benign PATCH can never soft-delete a space (USER-03).
    ``default_locale`` (D-07) — when present — is validated against {nl,fr,en} in the
    handler before the write.
    """

    name: str | None = None
    slug: str | None = None
    default_locale: str | None = None


class SpaceView(BaseModel):
    """Safe projection of an organization (space)."""

    id: str
    name: str
    slug: str | None = None
    status: str
    default_locale: str


def _space_view(space) -> SpaceView:
    """Project an ``Organization`` ORM row onto the safe ``SpaceView``."""
    return SpaceView(
        id=str(space.id),
        name=space.name,
        slug=space.slug,
        status=space.status,
        default_locale=space.default_locale,
    )


def _validate_locale(value: str) -> None:
    """Reject a ``default_locale`` outside {nl,fr,en} with ``CodedError`` INVALID_LOCALE.

    Reuses the 11-02 additive error-code contract (T-11-04 Input Validation): a bad locale
    is a curated, user-visible 422 the frontend maps to a translated message, and the write
    NEVER runs on a rejected value. Mirrors ``me_routes.patch_locale``'s guard.
    """
    if value not in _ALLOWED_LOCALES:
        raise CodedError(422, INVALID_LOCALE, "Invalid locale")


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
    """Create a space (status defaults to ``active``) + ``space.created`` audit (USER-03).

    ``default_locale`` (D-07) — when supplied — is validated against {nl,fr,en} BEFORE any
    write (``CodedError`` INVALID_LOCALE) and recorded in the audit metadata. When omitted the
    column ``server_default`` ("nl") applies.
    """
    if body.default_locale is not None:
        _validate_locale(body.default_locale)

    space = repo.create_space(
        name=body.name, slug=body.slug, default_locale=body.default_locale
    )
    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.created",
        target=str(space.id),
        space_id=space.id,
        metadata={
            "name": body.name,
            "slug": body.slug,
            "default_locale": space.default_locale,
        },
    )
    return _space_view(space)


@admin_router.patch("/spaces/{space_id}")
def update_space(
    space_id: str,
    body: SpacePatchBody,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Edit a space's name/slug/default_locale (never status) + ``space.updated`` audit.

    Empty patch -> 400; missing space -> 404 (the rowcount-0 outcome). A supplied
    ``default_locale`` is validated against {nl,fr,en} BEFORE the write (``CodedError``
    INVALID_LOCALE — T-11-04). The audit ``metadata`` records only the changed fields.
    """
    values = body.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No fields to update")

    if "default_locale" in values and values["default_locale"] is not None:
        _validate_locale(values["default_locale"])

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


def _apply_to_idp(uids: list[str], apply, *, verb: str) -> list[str]:
    """Call an ``admin_users`` verb once per uid; return the uids it FAILED for.

    The Admin SDK cannot join the request transaction, so the cascade's enforcement half
    is a best-effort loop rather than part of the atomic write. It never returns early: a
    member the IdP rejects must not shield the members after them in the list. Failures
    are logged here (uid + exception) and reported to the caller as a COUNT only — never
    as identifiers in a response body (T-06-09).
    """
    failed: list[str] = []
    for uid in uids:
        try:
            apply(uid)
        except Exception:  # noqa: BLE001 -- any SDK/transport error is "still enabled"
            _log.exception("space cascade: %s failed for uid=%s", verb, uid)
            failed.append(uid)
    return failed


@admin_router.post("/spaces/{space_id}/deactivate")
def deactivate_space(
    space_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Deactivate a space AND every member in it (SEC-02 / D-23.1-03). NO hard-delete (D-10).

    Flipping ``organizations.status`` is BOOKKEEPING, not enforcement: nothing in any auth
    path reads that column (23.1-CONTEXT § 2) and this handler deliberately does not add
    such a read — D-23.1-03 rejects an org-status lookup in ``get_current_identity``
    because ``dependencies.py`` has no DB call by design (D-06). The ENFORCEMENT is the
    same per-user machinery :func:`deactivate_user` uses, applied once per member:
    ``admin_users.deactivate_user`` = ``update_user(disabled=True)`` +
    ``revoke_refresh_tokens``, which the AUTH-04 ``check_revoked=True`` boundary
    (``dependencies.py:78``) turns into a rejection on the member's NEXT request.

    Order — **IdP FIRST, DB second** (D-23.2-09; the IdP cannot join the DB transaction):
      1. 404 if the space does not exist; read its memberships ONCE.
      2. Both T-5-15 guards, evaluated against that list BEFORE any write: never disable
         the ACTING superadmin, and never take the last active superadmin(s) down.
      3. IdP: one ``deactivate_user`` per member with a non-null ``provider_user_id``,
         collecting failures instead of stopping at the first.
      4. DB: flip to ``space_deactivated`` (a THIRD status, so :func:`reactivate_space`
         can restore exactly what this took and never un-fire an individually deactivated
         member) ONLY the members the IdP did not refuse, and the space to ``deactivated``.
      5. All-clear -> 200. Any failure -> commit the partial flip and the audit row FIRST
         (so the record of intent survives), then 502 whose detail carries a COUNT only —
         the uids go to the audit ``metadata`` and the log, never to the browser.

    WHY THAT ORDER (23.2-CONTEXT § 5, F-04). ``get_current_identity`` reads role/space
    purely from token claims with zero DB reads (D-06), so the membership row is not what
    denies a member — the IdP flag is. Flipping the row for a member the IdP REFUSED to
    disable would make the database claim access is revoked when it is not, and the
    operator's console would repeat that claim. Under this ordering the DB can never
    over-claim.

    A crash between steps 3 and 5 leaves members DENIED at the IdP while their rows still
    read ``active``: they are locked out and the console under-claims. That is fail-CLOSED,
    and it is the direction to fail in.

    SAFE TO PRESS TWICE. Both steps are idempotent, and the member list deliberately
    includes rows that are ALREADY ``space_deactivated``, so re-issuing this verb on an
    already-deactivated space re-attempts the IdP call for every member — which is the only
    way a member whose disable failed in an earlier attempt ever gets disabled. A
    status-filtered member list would make the retry a silent no-op.
    """
    space = repo.get_space(space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    memberships = list(repo.list_memberships_for_space(space_id))

    # T-5-15 self-lockout guards — 409 BEFORE any DB write and before any IdP call, and
    # evaluated against the list already read (no second query, no re-derivation in the
    # loop). These are the per-user guards at :func:`deactivate_user` raised to the space.
    if any(m.provider_user_id and m.provider_user_id == identity.uid for m in memberships):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot deactivate yourself")

    cascaded_superadmins = sum(
        1
        for m in memberships
        if m.role == "superadmin" and m.status == _STATUS_ACTIVE
    )
    # ``> 0`` matters: a space holding NO active superadmin cascades zero of them, and
    # ``0 >= count`` would refuse every deactivation on an installation whose superadmins
    # have no membership rows at all (the count is global). The guard only bites when this
    # space actually holds active superadmins AND they are all of the remaining ones.
    if cascaded_superadmins > 0 and cascaded_superadmins >= repo.count_active_superadmins():
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Cannot deactivate the last active superadmin"
        )

    # The cascade set: active members plus any already carrying the cascade status (the
    # retry path). An individually ``deactivated`` member is left exactly as they are —
    # they must stay deactivated through a later reactivate.
    targets = [
        m
        for m in memberships
        if m.status in (_STATUS_ACTIVE, _STATUS_SPACE_DEACTIVATED)
    ]

    # STEP 3 — the IdP goes FIRST (D-23.2-09). A membership whose provider_user_id is NULL
    # (created before the IdP account exists) has nothing to disable and is skipped here.
    uids = [m.provider_user_id for m in targets if m.provider_user_id]
    failed = _apply_to_idp(uids, admin_users.deactivate_user, verb="deactivate_user")
    failed_uids = set(failed)

    # STEP 4 — flip ONLY what the IdP actually disabled. Two DIFFERENT things both test
    # False here and the distinction matters: a member the IdP disabled (succeeded), and a
    # member with no provider_user_id who was never in ``uids`` at all (nothing to
    # disable). Both are correctly flipped; only a REFUSED member keeps its old status, so
    # the DB never claims a revocation the IdP did not perform.
    members_cascaded = 0
    for membership in targets:
        if membership.provider_user_id in failed_uids:
            continue
        # Re-writing an already-correct status is a pointless UPDATE; this guard is what
        # makes the retry cheap. It is also why the count below is PER-CALL (see the
        # audit metadata comment).
        if membership.status != _STATUS_SPACE_DEACTIVATED:
            repo.set_membership_status(membership.id, _STATUS_SPACE_DEACTIVATED)
            members_cascaded += 1
    # The space row is flipped even on partial failure. ``organizations.status`` is
    # bookkeeping and grants no access (nothing in any auth path reads it), so recording
    # the operator's full intent here over-claims nothing — it is the one place the DB
    # deliberately still records the whole intent.
    repo.set_space_status(space_id, _STATUS_DEACTIVATED)

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.deactivated",
        target=space_id,
        space_id=space.id,
        metadata={
            # PER-CALL, never a running total: an audit row records what ITS OWN event
            # did, and a reader reconstructs total state by summing the sequence. A clean
            # retry after a partial failure therefore reports 1 while three members are
            # down — that is CORRECT, not a second partial failure. It is deliberately not
            # ``len(targets)``, which would make the trail inherit the very over-claim
            # D-23.2-09 removes from the membership rows.
            "members_cascaded": members_cascaded,
            "idp_disabled": len(uids) - len(failed),
            # Identifiers belong in the audit trail (T-23.1-10 repudiation), NOT in the
            # response body (T-23.1-11 / T-06-09).
            "idp_failed_uids": failed,
        },
    )

    if failed:
        # Commit the flip + the audit row BEFORE raising: the request tx would otherwise
        # roll back on the exception, erasing the record of a cascade that DID disable
        # some members in the IdP. Verified against SQLAlchemy 2.0's ``sessionmaker.begin``
        # — an explicit commit here survives the raise and the dependency exits cleanly.
        repo.session.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Space deactivated, but {len(failed)} of {len(uids)} members could not be "
            "disabled in the identity provider. Re-issue this request to retry.",
        )

    return _space_view(repo.get_space(space_id))


@admin_router.post("/spaces/{space_id}/reactivate")
def reactivate_space(
    space_id: str,
    repo: AdminRepo = Depends(get_admin_session),
    identity: Identity = Depends(get_current_identity),
) -> SpaceView:
    """Reactivate a space and ONLY the members its deactivation took down (SEC-02).

    The SELECTIVE inverse of :func:`deactivate_space`. It restores exactly the memberships
    carrying ``space_deactivated`` and deliberately leaves ``deactivated`` rows alone: a
    member fired INDIVIDUALLY before the space went down must stay fired. Without the
    third status value, deactivate-then-reactivate a space would be an undocumented way to
    restore revoked access (T-23.1-08).

    Same order and the same honesty as deactivate — **IdP FIRST** (one
    ``admin_users.reactivate_user`` = ``update_user(disabled=False)`` per member), THEN
    the DB flip, applied only to the members the IdP actually re-enabled, then 200; or a
    committed partial flip plus a 502 carrying a COUNT only. Claims are NOT re-issued
    (A3 — login-sync is idempotent).

    WHY THAT ORDER (23.2-CONTEXT § 5, F-07 — this verb's version of the bug is worse than
    deactivate's). The target filter selects EXACTLY ``space_deactivated`` rows, and it
    cannot be widened to ``!= active`` without sweeping up the individually deactivated
    members and undoing T-23.1-08. So under the old DB-first ordering the first press
    marked every row ``active`` and the retry found nothing to do: it returned 200 having
    attempted NOTHING while the account stayed disabled, making the 502's "Re-issue this
    request to retry" a no-op. Flipping AFTER the IdP call leaves a refused member at
    ``space_deactivated`` — the exact status the retry selects on. The ordering is the
    whole fix; the filter is unchanged.

    A crash between the IdP call and the commit leaves members ENABLED at the IdP with
    ``space_deactivated`` rows. Nothing reads that column for authorization, so this is the
    one asymmetry with deactivate: the re-enable simply stands and the next press
    reconciles the row. Safe to press twice — un-disabling an already-enabled account is a
    no-op.

    As on deactivate, ``organizations.status`` is bookkeeping — the IdP flag is what lets
    the member back in, so the space row is flipped even on the partial-failure path as the
    operator's record of intent.
    """
    space = repo.get_space(space_id)
    if space is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Space not found")

    memberships = list(repo.list_memberships_for_space(space_id))
    # EXACTLY the cascade's own rows. Never ``!= _STATUS_ACTIVE`` — that would sweep up
    # the individually deactivated.
    targets = [m for m in memberships if m.status == _STATUS_SPACE_DEACTIVATED]

    # The IdP goes FIRST (D-23.2-09). A membership with no provider_user_id has nothing to
    # re-enable and is skipped here.
    uids = [m.provider_user_id for m in targets if m.provider_user_id]
    failed = _apply_to_idp(uids, admin_users.reactivate_user, verb="reactivate_user")
    failed_uids = set(failed)

    # Flip ONLY what the IdP actually re-enabled. As on deactivate, two different cases
    # both test False here — the IdP succeeded, or there was no uid to call for — and both
    # are correctly flipped. A REFUSED member keeps ``space_deactivated``, which is exactly
    # what keeps them in ``targets`` on the next press (F-07).
    members_restored = 0
    for membership in targets:
        if membership.provider_user_id in failed_uids:
            continue
        repo.set_membership_status(membership.id, _STATUS_ACTIVE)
        members_restored += 1
    # Bookkeeping only, kept as the record of intent even on partial failure — see the
    # docstring and the matching comment in :func:`deactivate_space`.
    repo.set_space_status(space_id, _STATUS_ACTIVE)

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="space.reactivated",
        target=space_id,
        space_id=space.id,
        metadata={
            # PER-CALL, never a running total — see the matching comment in
            # :func:`deactivate_space`. A clean retry reports 1 while three members are
            # back up, and that is CORRECT.
            "members_restored": members_restored,
            "idp_enabled": len(uids) - len(failed),
            "idp_failed_uids": failed,
        },
    )

    if failed:
        repo.session.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Space reactivated, but {len(failed)} of {len(uids)} members could not be "
            "re-enabled in the identity provider. Re-issue this request to retry.",
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
