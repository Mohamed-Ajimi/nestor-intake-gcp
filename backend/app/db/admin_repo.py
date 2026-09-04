"""``AdminRepo`` — the root + cross-space data-access seam for the superadmin path.

Lives INSIDE ``app/db/`` (alongside ``repository.py`` / ``audit.py``) so it stays on
the right side of ``scripts/ci_no_raw_db_access.sh`` (the D-03 grep-guard whitelists
``app/db/``). The superadmin admin endpoints reach every accessor here through
``Depends(get_admin_session)`` — they import NO raw DB symbol.

WHY THIS IS NOT A ``TenantRepository`` SUBCLASS (D-05 / 05-PATTERNS § admin_repo.py):
    ``TenantRepository`` exists to apply the un-omittable ``WHERE space_id =`` wall for a
    ``user`` (D-01). The admin path is the deliberate cross-space / root-table seam: it
    operates on tenant ROOT tables (``organizations``, ``organization_memberships``,
    ``audit_log``) AND reaches templates across ANY space. There is therefore NO
    ``_scope`` filter and NO ``model.space_id ==`` predicate anywhere in this module —
    cross-space reach comes from the ``app_superadmin`` engine + the 0003 bypass policy
    (selected in :func:`app.db.session.get_admin_session`), never from an app-layer
    filter. This module is reachable ONLY behind the superadmin-only ``get_admin_session``
    gate; a ``user`` Identity is rejected with 403 before any session opens.

NO HARD-DELETE ANYWHERE (D-10 / USER-03): there is intentionally no ``delete`` method.
    Spaces, memberships, and templates are soft-deactivated via a ``status`` flip; the
    audit trail outlives its subject. A hard-delete affordance would violate D-10 and is
    structurally absent (the route layer has no DELETE route to call into either).

Patch shape mirrors ``repository.py`` (return ``rowcount``) so the endpoints feel
identical to the tenant path: 0 rows -> the handler maps to 404.

Pitfall 6 (id coercion): ``Identity.space_id`` is a ``str`` and the path params arrive
as ``str``; the ORM columns are ``UUID(as_uuid=True)``. Coerce to ``uuid.UUID`` at the
boundary so the pg8000 bind/compare is unambiguous.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.db.models.audit import AuditLog  # noqa: F401 -- audit rows are read in tests via this seam's tables
from app.db.models.intake import IntakeTemplate
from app.db.models.membership import OrganizationMembership
from app.db.models.organization import Organization

# App-level allowed status set (NOT a PG enum — mirrors the model docstrings).
_STATUS_ACTIVE = "active"
_STATUS_DEACTIVATED = "deactivated"

# The space-cascade status (SEC-02 / D-23.1-03, D-23.1-11). A THIRD value exists so the
# reactivate inverse can be SELECTIVE: it restores exactly the memberships the cascade
# took down and never un-fires a member who was deactivated INDIVIDUALLY before the space
# went down. With only two values, deactivate-then-reactivate a space would be an
# undocumented way to restore revoked access.
#
# NO MIGRATION IS NEEDED: ``organization_memberships.status`` is a plain ``String`` with a
# server_default and no PG enum / CHECK constraint (``models/membership.py:43``, migration
# 0006), so a third value simply stores.
#
# WHY IT READS AS INACTIVE EVERYWHERE BY CONSTRUCTION: every membership-status read in
# ``backend/app/`` that carries LOGIC is an ALLOW-LIST (``== "active"``) at five sites —
# ``admin_repo.py`` :meth:`find_active_membership` and :meth:`count_active_superadmins`,
# ``admin_routes.py``'s last-superadmin guard, ``intake_routes.py``'s member lookup, and
# ``me_routes.py``'s membership resolution. There is not one deny-list
# (``!= "deactivated"``) comparison, so an unknown value reads as "not active" rather than
# as "not deactivated". A future deny-list would silently break that, which is why
# ``tests/test_space_deactivation_cascade.py`` pins both directions.
#
# NOT the whole picture (D-23.1-11 CORRECTED / D-23.1-13): there is a SIXTH site,
# ``_find_membership`` in ``app/auth/session.py``, and it is a NO-list — no status
# predicate at all — so login-sync would mint claims for a cascaded member. That is closed
# separately by D-23.1-13 (plan 16) and is what makes this cascade safe when an IdP call
# fails. Do not restate the survey as "five sites, no deny-list anywhere".
_STATUS_SPACE_DEACTIVATED = "space_deactivated"


def _as_uuid(value: Any) -> uuid.UUID:
    """Coerce a ``str``/``UUID`` id to ``uuid.UUID`` (Pitfall 6).

    Path params and ``Identity.space_id`` arrive as ``str``; the ORM columns are
    ``UUID(as_uuid=True)``. Coercing here keeps the pg8000 bind unambiguous and raises
    a ``ValueError`` (-> the handler's 422/400) for a malformed id rather than silently
    comparing against nothing.
    """
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class AdminRepo:
    """Root + cross-space accessors bound to a per-request superadmin ``Session``.

    Constructed by :func:`app.db.session.get_admin_session` (the superadmin-only gate)
    with the request's bound ``Session`` and the verified superadmin ``Identity``. Every
    method runs on the ``app_superadmin`` engine, so the 0003 bypass policy provides
    cross-space reach with NO per-method ``space_id`` filter (D-05). NO delete method
    exists (D-10).
    """

    def __init__(self, session: Session, identity: Identity) -> None:
        self._s = session
        self._identity = identity

    @property
    def session(self) -> Session:
        """The request's bound ``Session`` — the audit-write target (QA-04).

        Exposed so a mutation handler can pass the SAME session to
        :func:`app.db.audit.log`, keeping the ``audit_log`` row in the action's
        transaction (T-5-16). This is the request session, NOT a new engine/session —
        the no-raw-DB grep-guard stays green.
        """
        return self._s

    # -- users / memberships (root table; not RLS-scoped) -------------------

    def list_users(self):
        """Return every ``organization_memberships`` row (cross-space; root table)."""
        return self._s.execute(select(OrganizationMembership)).scalars().all()

    def get_membership(self, membership_id):
        """Return one membership by id, or ``None`` (handler -> 404)."""
        return self._s.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.id == _as_uuid(membership_id)
            )
        ).scalar_one_or_none()

    def find_active_membership(self, organization_id, email):
        """Return an ACTIVE membership for ``(organization_id, email)`` or ``None``.

        Used by the invite duplicate-guard (Pitfall 5): an already-active membership for
        that email in the target space is an intentional duplicate -> the handler maps it
        to 409 rather than letting a second row / 500 happen.
        """
        return self._s.execute(
            select(OrganizationMembership).where(
                OrganizationMembership.organization_id == _as_uuid(organization_id),
                OrganizationMembership.email == email,
                OrganizationMembership.status == _STATUS_ACTIVE,
            )
        ).scalar_one_or_none()

    def list_memberships_for_space(self, organization_id):
        """Return EVERY membership row of one space, regardless of ``status`` (SEC-02).

        The space-deactivation cascade's read half. It is deliberately status-BLIND, and
        that is load-bearing for the RETRY path: the IdP call cannot join the request
        transaction, so a member whose ``deactivate_user`` call failed is already
        ``space_deactivated`` in the DB while still enabled in the IdP. A status-filtered
        accessor would hand a second press of ``POST /spaces/{id}/deactivate`` an empty
        list and the retry would silently do nothing.

        Explicitly filtered on ``organization_id``: this module has no ``_scope`` wall
        (D-05) — every method runs on the ``app_superadmin`` engine (0003 bypass), so this
        WHERE clause is the only thing keeping the cascade inside one tenant.
        """
        return (
            self._s.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == _as_uuid(organization_id)
                )
            )
            .scalars()
            .all()
        )

    def create_membership(
        self,
        organization_id,
        provider_user_id: str,
        email: str | None,
        role: str = "user",
        status: str = _STATUS_ACTIVE,
    ):
        """Insert one membership row and return it (the invite write, USER-01).

        ``role`` is supplied by the caller (the invite endpoint hard-codes ``"user"`` per
        D-01a — this repo faithfully writes what it is handed). Returns the persisted ORM
        instance so the handler can project a safe view.
        """
        membership = OrganizationMembership(
            organization_id=_as_uuid(organization_id),
            provider_user_id=provider_user_id,
            email=email,
            role=role,
            status=status,
        )
        self._s.add(membership)
        self._s.flush()
        return membership

    def set_membership_status(self, membership_id, status: str):
        """Flip a membership's ``status`` (deactivate/reactivate); return rowcount.

        0 rows -> the handler maps to 404 (no such membership). Mirrors
        ``repository.py``'s rowcount-returning patch shape.
        """
        result = self._s.execute(
            update(OrganizationMembership)
            .where(OrganizationMembership.id == _as_uuid(membership_id))
            .values(status=status)
        )
        return result.rowcount

    def count_active_superadmins(self) -> int:
        """Count ACTIVE ``superadmin`` memberships (last-superadmin guardrail).

        The deactivate handler refuses (409) if disabling the target would drop this
        count to zero — preventing a superadmin self-lockout (T-5-15).
        """
        return self._s.execute(
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.role == "superadmin",
                OrganizationMembership.status == _STATUS_ACTIVE,
            )
        ).scalar_one()

    # -- spaces (organizations root table; not RLS-scoped) -----------------

    def list_spaces(self):
        """Return every organization (space) row (cross-space; root table)."""
        return self._s.execute(select(Organization)).scalars().all()

    def get_space(self, space_id):
        """Return one organization by id, or ``None`` (handler -> 404)."""
        return self._s.execute(
            select(Organization).where(Organization.id == _as_uuid(space_id))
        ).scalar_one_or_none()

    def create_space(
        self, name: str, slug: str | None = None, default_locale: str | None = None
    ):
        """Insert one organization (status defaults to ``active``); return it.

        ``default_locale`` (D-07 / D-10) is optional: when omitted, the
        ``organizations.default_locale`` column ``server_default`` ("nl") applies, so a
        create that never mentions a locale still lands a non-null "nl" base. The route
        layer validates the value against {nl,fr,en} BEFORE calling here.
        """
        kwargs: dict[str, Any] = {"name": name, "slug": slug}
        if default_locale is not None:
            kwargs["default_locale"] = default_locale
        space = Organization(**kwargs)
        self._s.add(space)
        self._s.flush()
        return space

    def update_space(self, space_id, **values):
        """Patch non-status fields (name/slug/default_locale) on a space; return rowcount.

        ``status`` is NEVER routed through here — deactivate/reactivate use
        :meth:`set_space_status` so a benign PATCH can never soft-delete a space.
        ``default_locale`` (D-07 / D-10) is validated against {nl,fr,en} at the route
        layer before it reaches this generic value setter.
        """
        result = self._s.execute(
            update(Organization)
            .where(Organization.id == _as_uuid(space_id))
            .values(**values)
        )
        return result.rowcount

    def set_space_status(self, space_id, status: str):
        """Flip a space's ``status`` (soft deactivate/reactivate); return rowcount."""
        result = self._s.execute(
            update(Organization)
            .where(Organization.id == _as_uuid(space_id))
            .values(status=status)
        )
        return result.rowcount

    # -- templates (tenant-owned; the superadmin engine reaches any space) --

    def list_templates(self, space_id):
        """Return every template owned by ``space_id`` (the admin engine reaches any)."""
        return (
            self._s.execute(
                select(IntakeTemplate).where(
                    IntakeTemplate.space_id == _as_uuid(space_id)
                )
            )
            .scalars()
            .all()
        )

    def get_template(self, template_id):
        """Return one template by id, or ``None`` (handler -> 404)."""
        return self._s.execute(
            select(IntakeTemplate).where(IntakeTemplate.id == _as_uuid(template_id))
        ).scalar_one_or_none()

    def clone_template(self, space_id, name: str, schema: dict | None):
        """Create a template in ``space_id`` from a name + schema JSON; return it.

        "Clone a default into a space" (USER-03): the operator supplies the new
        template's name and its schema payload, which lands as a fresh row scoped to the
        TARGET space (the clone belongs to the right org — the test asserts
        ``space_id == target``). Returns the persisted ORM instance for the view.
        """
        template = IntakeTemplate(
            space_id=_as_uuid(space_id),
            name=name,
            schema=schema,
        )
        self._s.add(template)
        self._s.flush()
        return template

    def update_template(self, template_id, schema: dict):
        """Replace a template's ``schema`` JSON; return rowcount (0 -> handler 404)."""
        result = self._s.execute(
            update(IntakeTemplate)
            .where(IntakeTemplate.id == _as_uuid(template_id))
            .values(schema=schema)
        )
        return result.rowcount
