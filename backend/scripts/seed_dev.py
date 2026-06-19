"""Standalone DEV seed — run MANUALLY, AFTER ``alembic upgrade head`` (D-09).

This script is DELIBERATELY OUTSIDE the Alembic migration path. Production must
come up EMPTY (INFRA-02): no migration imports, references, or calls this
module, so an ``alembic upgrade head`` against a fresh Cloud SQL instance leaves
every tenant table with zero rows. The seed only ever runs when an operator
invokes it by hand against a local / dev database.

What it seeds (idempotent get-or-create):
  - one demo ``organization`` (the demo space, fixed UUID ``DEV_SPACE_ID``),
  - one ``organization_memberships`` row marking the demo SUPERADMIN
    (``role = 'superadmin'``), and
  - one sample ``intake_template`` in that space.

Idempotency: every insert is guarded by a get-or-create on a deterministic key
(the fixed UUIDs / the org+role pair), so re-running creates no duplicates.

RLS bypass: connect as the local superuser or ``app_superadmin`` so the inserts
are not blocked by the per-space ``*_space_isolation`` policies (the seed writes
ACROSS the space boundary by definition — it creates the space). No
``app.current_space_id`` GUC needs to be set.

Usage (PowerShell):

    $env:DATABASE_URL = "postgresql+pg8000://app_superadmin@localhost:5432/nestor"
    cd backend
    python -m scripts.seed_dev

Driver: pg8000 (Q1 RESOLVED), matching ``app/db/base.py``.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.base import get_sessionmaker
from app.db.models import (
    Intake,  # noqa: F401 — ensures the full metadata is registered
    IntakeTemplate,
    Organization,
    OrganizationMembership,
)

# Deterministic dev identifiers so the seed is idempotent across runs and so
# tests can assert on known values.
DEV_SPACE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d0")
DEV_TEMPLATE_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d1")
DEV_SUPERADMIN_MEMBERSHIP_ID = uuid.UUID("00000000-0000-0000-0000-0000000000d2")

DEV_ORG_NAME = "Demo Space (dev)"
DEV_ORG_SLUG = "demo-space"
DEV_SUPERADMIN_EMAIL = "superadmin@agenic.be"

# Minimal but valid intake schema (intake-types.ts IntakeSchema shape): one
# section with one text field, enough to render the demo form.
DEV_TEMPLATE_NAME = "Demo Intake Template"
DEV_TEMPLATE_SCHEMA: dict = {
    "sections": [
        {
            "key": "about",
            "title": "About the project",
            "fields": [
                {
                    "key": "project_goal",
                    "label": "What is the goal of this project?",
                    "type": "textarea",
                    "required": True,
                }
            ],
        }
    ]
}


def seed(session_factory=None) -> dict:
    """Idempotently seed the demo space, superadmin membership, and template.

    Returns a dict summarising what was created vs. already present so callers
    (CLI + tests) can inspect the outcome. Accepts an optional ``session_factory``
    so the test suite can bind the seed to its own engine instead of the
    process-wide one.
    """
    maker = session_factory if session_factory is not None else get_sessionmaker()
    summary: dict[str, str] = {}

    with maker() as session:
        with session.begin():
            # --- demo organization (the space) -------------------------------
            org = session.get(Organization, DEV_SPACE_ID)
            if org is None:
                session.add(
                    Organization(
                        id=DEV_SPACE_ID,
                        name=DEV_ORG_NAME,
                        slug=DEV_ORG_SLUG,
                    )
                )
                summary["organization"] = "created"
            else:
                summary["organization"] = "exists"

            # --- superadmin membership (role marker) -------------------------
            membership = session.execute(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id == DEV_SPACE_ID,
                    OrganizationMembership.role == "superadmin",
                )
            ).scalar_one_or_none()
            if membership is None:
                session.add(
                    OrganizationMembership(
                        id=DEV_SUPERADMIN_MEMBERSHIP_ID,
                        organization_id=DEV_SPACE_ID,
                        email=DEV_SUPERADMIN_EMAIL,
                        role="superadmin",
                    )
                )
                summary["superadmin"] = "created"
            else:
                summary["superadmin"] = "exists"

            # --- sample intake template --------------------------------------
            template = session.get(IntakeTemplate, DEV_TEMPLATE_ID)
            if template is None:
                session.add(
                    IntakeTemplate(
                        id=DEV_TEMPLATE_ID,
                        space_id=DEV_SPACE_ID,
                        name=DEV_TEMPLATE_NAME,
                        schema=DEV_TEMPLATE_SCHEMA,
                    )
                )
                summary["intake_template"] = "created"
            else:
                summary["intake_template"] = "exists"

    for what, state in summary.items():
        sign = "+" if state == "created" else "="
        print(f"{sign} {what}: {state}")
    print("dev seed complete.")
    return summary


if __name__ == "__main__":
    seed()
