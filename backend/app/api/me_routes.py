"""``/me`` locale surface — ``GET /me`` + ``PATCH /me/locale`` (Phase 11 / I18N-01 / I18N-02).

The server home for the frontend's language state. The switcher (11-01) and the client boot
read the resolved locale from ``GET /me``, and the switcher persists a user's choice via
``PATCH /me/locale``. Both handlers derive the caller's identity ONLY from the verified token
(``get_current_identity`` -> ``identity.uid`` / ``identity.space_id``), NEVER from request input.

Resolution chain (D-07): ``locale`` (the user override, may be null) resolves to
``membership.locale`` for the caller's membership row; ``space_default_locale`` resolves to the
caller's organization ``default_locale``, falling back to ``"nl"`` when the caller is a
superadmin with NO membership / NO space (Open Q1). The frontend applies the chain
(user override -> space default -> nl) client-side.

SECURITY (T-11-03 EoP / T-11-04 Input Validation): locale is DISPLAY-ONLY, never an authz
input. ``PATCH /me/locale`` re-derives the user server-side (``identity.uid``) and scopes the
write to the caller's own membership, so a client-supplied locale can only change DISPLAY,
never widen access or touch another user's row. ``PATCH`` validates ``locale ∈ {nl,fr,en}`` and
rejects anything else with a ``CodedError(422, "INVALID_LOCALE", ...)`` (the first CodedError
consumer) — the write never runs on a rejected value.

Mounted UNDER ``protected_router`` in ``main.py`` (inherits ``Depends(get_current_identity)``),
exactly like every other feature router. Sync ``def`` handlers (pg8000 is blocking; FastAPI
runs sync handlers in a threadpool) — never ``async def``.

Authoritative references:
- backend/app/api/admin_routes.py (the PATCH+Pydantic+404 shape; sync-def rationale)
- backend/app/db/session.py `get_me_session` (the both-roles session dependency)
- backend/app/api/errors.py `CodedError` / INVALID_LOCALE (the additive error-code contract)
- .planning/phases/11-internationalization-nl-fr-en/11-PATTERNS.md § me_routes.py
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.errors import INVALID_LOCALE, CodedError
from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.db.models.membership import OrganizationMembership
from app.db.models.organization import Organization
from app.db.session import get_me_session

# The app-level allowed locale set (V5 input validation — Security Domain). Enforced in code,
# NOT a PG enum (mirrors the status/default_locale column rationale). MUST match the frontend
# switcher's fixed nl/fr/en options and the 0010 model docstrings.
_ALLOWED = {"nl", "fr", "en"}

# The resolution fallback when a caller has no space default (superadmin with no membership).
_DEFAULT_LOCALE = "nl"

# The feature router. NO auth dependency of its own — mounted UNDER protected_router in
# app/main.py (inheriting Depends(get_current_identity)); each handler additionally
# Depends(get_me_session) for its both-roles data access.
me_router = APIRouter(tags=["me"])


class Me(BaseModel):
    """The ``/me`` response — the caller's locale state (resolution chain inputs)."""

    #: The user's OWN override; ``null`` means "no override -> inherit the space default"
    #: (D-07). Superadmin with no membership row: also ``null``.
    locale: str | None
    #: The caller's organization ``default_locale``, or ``"nl"`` when there is no space
    #: (superadmin with no membership — Open Q1).
    space_default_locale: str


class LocalePatchBody(BaseModel):
    """The ``PATCH /me/locale`` body — the user's chosen override."""

    locale: str


def _resolve_me(session: Session, identity: Identity) -> Me:
    """Build the :class:`Me` response for ``identity`` from its membership + org (D-07).

    Reads the caller's membership row (keyed on the VERIFIED ``identity.uid`` via
    ``provider_user_id``) and the organization ``default_locale`` for ``identity.space_id``.
    A superadmin with no membership / no space resolves to ``locale=None`` +
    ``space_default_locale="nl"`` (Open Q1). Never reads locale/identity from request input.
    """
    membership = _load_membership(session, identity)

    user_locale = membership.locale if membership is not None else None

    space_default = _DEFAULT_LOCALE
    if identity.space_id:
        org = session.execute(
            select(Organization).where(Organization.id == identity.space_id)
        ).scalar_one_or_none()
        if org is not None:
            space_default = org.default_locale

    return Me(locale=user_locale, space_default_locale=space_default)


def _load_membership(
    session: Session, identity: Identity
) -> OrganizationMembership | None:
    """Return the caller's OWN membership row (keyed on the verified token), or ``None``.

    The lookup is on ``provider_user_id == identity.uid`` — the Identity Platform subject id
    the invite flow stamps onto the membership. Identity is the ONLY source (never request
    input). A superadmin with no membership row returns ``None`` (Open Q1).
    """
    return session.execute(
        select(OrganizationMembership).where(
            OrganizationMembership.provider_user_id == identity.uid
        )
    ).scalar_one_or_none()


@me_router.get("/me")
def get_me(
    identity: Identity = Depends(get_current_identity),
    session: Session = Depends(get_me_session),
) -> Me:
    """Return the caller's resolved locale state (D-07 chain), derived from the token only."""
    return _resolve_me(session, identity)


@me_router.patch("/me/locale")
def patch_locale(
    body: LocalePatchBody,
    identity: Identity = Depends(get_current_identity),
    session: Session = Depends(get_me_session),
) -> Me:
    """Persist the caller's locale override onto THEIR OWN membership row; return the resolved Me.

    Validation (T-11-04): reject ``locale ∉ {nl,fr,en}`` with ``CodedError(422, INVALID_LOCALE)``
    BEFORE any write. Security (T-11-03 EoP): the write is scoped to the caller's membership
    (re-derived from ``identity.uid``) — a client cannot set another user's locale, and locale
    is display-only (never widens access). A superadmin with NO membership row persists NOTHING
    (the localStorage-only path, Open Q1) and gets the resolved ``Me`` back without a write.
    """
    if body.locale not in _ALLOWED:
        raise CodedError(422, INVALID_LOCALE, "Invalid locale")

    membership = _load_membership(session, identity)
    if membership is not None:
        # Scoped to the caller's OWN row (re-derived from the verified token). Display-only.
        membership.locale = body.locale
        session.flush()
    # else: superadmin with no membership row -> persist nothing (localStorage-only, Open Q1).

    return _resolve_me(session, identity)
