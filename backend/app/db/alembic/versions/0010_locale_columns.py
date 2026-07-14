"""0010 locale columns — space ``default_locale`` + per-user membership ``locale`` override.

Phase 11 (i18n) backend foundation (I18N-01 / I18N-02). Adds the two columns the
``GET /me`` / ``PATCH /me/locale`` resolution chain (D-07 user->space->nl) reads and writes:

  - ``organizations.default_locale`` — ``String NOT NULL DEFAULT 'nl'``. The space-level
    default language. The ``server_default=sa.text("'nl'")`` backfills every EXISTING org row
    non-null on apply (mirrors 0006's ``status`` backfill), so no row is ever null after the
    migration. App-level allowed set {"nl","fr","en"} is enforced IN CODE (the ``_ALLOWED``
    guard in ``me_routes.py`` + the model docstring), NOT a PG enum — matching the ``status``
    column rationale (avoids alembic enum-alter friction / a 0009->0010 replay if a locale
    is ever added).

  - ``organization_memberships.locale`` — ``String`` **nullable**. The per-user override
    (D-07): ``null`` means "no override -> inherit the space default". A non-null value
    ({"nl","fr","en"}) is the user's persisted choice.

SUPERADMIN LOCALE HOME (Open Q1 — DECIDED): a superadmin may have NO membership row
(``role="superadmin"`` is cross-tenant, ``space_id`` None). The per-user override therefore
lives in this SAME nullable membership ``locale`` column WHEN a membership row exists; when a
superadmin has NO membership row, ``GET /me`` returns ``locale: null`` and
``space_default_locale: "nl"``, and the frontend falls back to its browser-detected / stored
preference (the LanguageSwitcher ``persist=false`` localStorage path from 11-01). NO separate
``user_preferences`` table is introduced in v1 — a superadmin with no membership persists
NOTHING server-side. (Threat T-11-06 disposition: accept — no new writable surface.)

No new index: both are scalar columns read by a membership/org lookup that already hits the
existing PK / FK indexes. Adding a locale index would drift the ORM<->migration index-name
1:1 match the project relies on for a clean ``alembic check``.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"


def upgrade() -> None:
    # ---- space default_locale: NOT NULL, server_default 'nl' backfills existing rows
    #      (D-07 base of the resolution chain; mirrors 0006's status backfill).
    op.add_column(
        "organizations",
        sa.Column(
            "default_locale",
            sa.String(),
            nullable=False,
            server_default=sa.text("'nl'"),
        ),
        schema=SCHEMA,
    )
    # ---- per-user membership override: NULLABLE (null = inherit space default, D-07).
    #      Also the superadmin's own locale home WHEN a membership row exists (Open Q1).
    op.add_column(
        "organization_memberships",
        sa.Column("locale", sa.String(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # Reverse order: drop the membership override first, then the space default.
    op.drop_column("organization_memberships", "locale", schema=SCHEMA)
    op.drop_column("organizations", "default_locale", schema=SCHEMA)
