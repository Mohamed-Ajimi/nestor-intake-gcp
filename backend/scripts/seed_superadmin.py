"""First-superadmin bootstrap (D-05) — run MANUALLY, ONCE, AFTER ``alembic upgrade head``.

This is the D-02 account-creation path. There is NO public self-registration: the
first superadmin is created HERE (by an operator / a one-shot Cloud Run Job), and
Phase-5 invites create everyone else. ``login-sync`` (``app.auth.session``) never
creates a user — it only syncs claims for an already-provisioned membership, so this
seed is what bootstraps that very first membership + IdP user so the whole auth path
can be exercised in GCP.

Like ``seed_dev.py`` this is DELIBERATELY OUTSIDE the Alembic migration path
(production comes up EMPTY, INFRA-02). It is idempotent — re-running promotes the
existing user / row instead of duplicating.

What it does (RESEARCH Pattern 4):
  1. IdP: ``auth.get_user_by_email(email)``; on ``UserNotFoundError`` create the user
     (``auth.create_user``) — promote-or-create. Then
     ``auth.set_custom_user_claims(uid, {"role": "superadmin", "space_id": None})``.
  2. DB: get-or-create a SYSTEM organization (fixed ``SYSTEM_ORG_ID``, name "Agenic")
     to satisfy the NOT-NULL ``organization_id`` FK, then UPSERT the superadmin
     ``organization_memberships`` row (keyed on ``uq_membership_org_user``).

Open Q3 RESOLVED — the membership's ``organization_id`` is an FK ANCHOR ONLY (the
schema requires it NOT NULL); it does NOT scope the superadmin. The superadmin CLAIM
carries ``space_id=None`` (cross-tenant) and authorization (Phase 4) reads the CLAIM,
never the row's org. So the superadmin is "all spaces" while the model stays honest
(no NULL FK) — threat T-03-16.

Credentials: ADC only (Cloud Shell / the runtime SA) — NO JSON SA key (threat
T-03-15 / D-09). The claim write + user creation need ``roles/identitytoolkit.admin``
on the identity running this (the runtime SA has it via ``infra/main.tf``).

Usage (PowerShell — local against the Firebase Auth emulator + a local DB):

    $env:FIREBASE_AUTH_EMULATOR_HOST = "localhost:9099"   # optional, local only (D-09)
    $env:DATABASE_URL = "postgresql+pg8000://app_superadmin@localhost:5432/nestor"
    $env:SUPERADMIN_EMAIL = "yanick@agenic.be"
    $env:SUPERADMIN_PASSWORD = "<choose-one>"             # optional; required only when creating
    cd backend
    python -m scripts.seed_superadmin
    #   or: python -m scripts.seed_superadmin yanick@agenic.be <password>

In GCP it is run as a one-shot Cloud Run Job reusing the service image with an alt
entrypoint (mirroring the migration Job) — see ``infra/README.md``.

Driver: pg8000 (Q1 RESOLVED), matching ``app/db/base.py``.
"""

from __future__ import annotations

import os
import sys
import uuid

import firebase_admin
from firebase_admin import auth
from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import (
    Intake,  # noqa: F401 — ensures the full metadata is registered
    Organization,
    OrganizationMembership,
)

# Deterministic system identifiers so the seed is idempotent across runs. The system
# org is the FK ANCHOR for the superadmin membership row (Open Q3) — NOT an
# authorization scope. The superadmin claim is space_id=None (cross-tenant).
SYSTEM_ORG_ID = uuid.UUID("00000000-0000-0000-0000-0000000000a0")
SYSTEM_ORG_NAME = "Agenic"
SYSTEM_ORG_SLUG = "agenic"

DEFAULT_SUPERADMIN_EMAIL = "yanick@agenic.be"


def _ensure_app() -> None:
    """Initialize the Admin SDK once via ADC (no JSON key — T-03-15 / D-09)."""
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _ensure_idp_user(email: str, password: str | None):
    """Promote-or-create the IdP user, then set the cross-tenant superadmin claim.

    Idempotent: ``get_user_by_email`` first; only ``create_user`` on
    ``UserNotFoundError``. The claim is ALWAYS (re)written so a re-run repairs a
    missing/incorrect claim. ``space_id=None`` => cross-tenant superadmin (T-03-16).
    """
    try:
        user = auth.get_user_by_email(email)
        created = False
    except auth.UserNotFoundError:
        user = auth.create_user(email=email, password=password)
        created = True

    # Server-side claim write (D-03). superadmin is cross-tenant: space_id is None.
    auth.set_custom_user_claims(user.uid, {"role": "superadmin", "space_id": None})
    return user, created


def seed(email: str | None = None, password: str | None = None, session_factory=None) -> dict:
    """Idempotently bootstrap the first superadmin (IdP user + claim + FK-anchored row).

    Accepts an optional ``session_factory`` (testability seam, mirrors ``seed_dev.py``).
    Returns a ``+``/``=`` summary dict (created vs. already-present) for CLI + tests.
    """
    email = email or os.environ.get("SUPERADMIN_EMAIL") or DEFAULT_SUPERADMIN_EMAIL
    password = password or os.environ.get("SUPERADMIN_PASSWORD")

    _ensure_app()
    summary: dict[str, str] = {}

    # --- Identity Platform: promote-or-create + superadmin claim ----------------
    user, created = _ensure_idp_user(email, password)
    summary["idp_user"] = "created" if created else "exists"
    summary["claim"] = "set"

    # --- DB: system org (FK anchor) + superadmin membership UPSERT --------------
    maker = session_factory if session_factory is not None else get_sessionmaker()
    with maker() as session:
        with session.begin():
            # System org — satisfies the NOT NULL organization_id FK (Open Q3). It is
            # a bookkeeping anchor; the superadmin claim above is space_id=None.
            org = session.get(Organization, SYSTEM_ORG_ID)
            if org is None:
                session.add(
                    Organization(
                        id=SYSTEM_ORG_ID,
                        name=SYSTEM_ORG_NAME,
                        slug=SYSTEM_ORG_SLUG,
                    )
                )
                summary["system_org"] = "created"
            else:
                summary["system_org"] = "exists"

            # Superadmin membership — UPSERT keyed on uq_membership_org_user
            # (organization_id + user_id). We match on the org + provider_user_id/email
            # so a re-run promotes the existing row rather than inserting a duplicate.
            membership = session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == SYSTEM_ORG_ID,
                    OrganizationMembership.email == email,
                )
            ).scalar_one_or_none()
            if membership is None:
                session.add(
                    OrganizationMembership(
                        organization_id=SYSTEM_ORG_ID,
                        provider_user_id=user.uid,
                        email=email,
                        role="superadmin",
                    )
                )
                summary["membership"] = "created"
            else:
                # Repair the row in place (promote-or-fix): ensure provider_user_id +
                # role are correct on a re-run without creating a duplicate.
                membership.provider_user_id = user.uid
                membership.role = "superadmin"
                summary["membership"] = "exists"

    for what, state in summary.items():
        sign = "+" if state in ("created", "set") else "="
        print(f"{sign} {what}: {state}")
    print(f"superadmin seed complete for {email}.")
    return summary


if __name__ == "__main__":
    # CLI: `python -m scripts.seed_superadmin [email] [password]` (env fallbacks above).
    cli_email = sys.argv[1] if len(sys.argv) > 1 else None
    cli_password = sys.argv[2] if len(sys.argv) > 2 else None
    seed(email=cli_email, password=cli_password)
