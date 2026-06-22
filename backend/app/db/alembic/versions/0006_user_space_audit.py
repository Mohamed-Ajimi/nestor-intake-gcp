"""0006 user/space management — status columns + root audit_log + grants.

Phase 5 data-layer foundation. Adds:

  - ``organization_memberships.status`` and ``organizations.status`` — both
    ``String NOT NULL DEFAULT 'active'`` (app-level set {"active","deactivated"};
    NOT a PG enum, to avoid alembic enum-alter friction). The ``server_default``
    backfills every existing row non-null on apply.
  - ``nestor.audit_log`` — a tenant ROOT table (D-07), the tamper-evident operator
    action trail (QA-04). It is created EXACTLY like the 0001 root tables
    (organizations / organization_memberships): NO ``space_id NOT NULL`` column,
    NO RLS. ``space_id`` is recorded as a *plain nullable* UUID with NO FK so the
    trail survives a soft-deactivated (or later removed) space — the audit row
    must outlive its subject.

CRITICAL — audit_log is NEVER RLS-scoped (D-07 / 05-RESEARCH Anti-Patterns):
this migration deliberately does NOT add ``audit_log`` to 0002's
``*_space_isolation`` loop or 0003's ``_RLS_TABLES`` / ``*_superadmin_all`` loop.
Those loops cover ONLY the 12 tenant-OWNED tables. Read access to ``audit_log``
flows solely through the superadmin engine (0003 bypass), never a space GUC a
user could set.

GRANTS (RESEARCH Pitfall 1 — belt-and-suspenders): a NEW root table created by a
later migration is reachable at runtime only if it is explicitly GRANTed to the
roles that query it. ``ALTER DEFAULT PRIVILEGES`` (0003/0005) covers FUTURE
objects created by the migration owner, but we add explicit per-table GRANTs too
so a missed default-privilege inheritance cannot produce a runtime
``permission denied for table audit_log``:
  - ``app_superadmin`` (the cross-tenant operator role, 0003) — verbatim GRANT.
  - the runtime SA (env ``RUNTIME_DB_USER``, 0005) — the SAME env-guarded
    DO-block, no-oping cleanly on the testcontainer where the env is unset and
    failing loud when the env is set but the role is absent.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-22
"""

from __future__ import annotations

import logging
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# Env var carrying the grantee role name = the runtime SA email WITHOUT the
# ".gserviceaccount.com" suffix (mirrors 0005). UNSET on the testcontainer,
# where the runtime-SA grant must no-op cleanly.
RUNTIME_DB_USER_ENV = "RUNTIME_DB_USER"

logger = logging.getLogger("alembic.runtime.migration")


def _runtime_db_user() -> str | None:
    """The grantee role name from the environment, or None when unset/blank."""
    value = os.environ.get(RUNTIME_DB_USER_ENV, "").strip()
    return value or None


def _grant_audit_log_to_runtime_sa() -> None:
    """Env-guarded GRANT of the new audit_log table to the runtime SA (0005 idiom)."""
    role = _runtime_db_user()
    if role is None:
        # Testcontainer / local path: no IAM SA user to grant. Skip cleanly so the
        # 0001->0006 chain still applies (RUNTIME_DB_USER unset).
        logger.info(
            "0006: %s unset -- skipping runtime-SA GRANT on audit_log (no IAM DB "
            "user to grant in this environment).",
            RUNTIME_DB_USER_ENV,
        )
        return

    # WR-01 (0005): role declared ONCE as a SQL literal inside the DO block; every
    # identifier use goes through format(... %I ...).
    role_literal = role.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
            r text := '{role_literal}';
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.audit_log TO %I', r);
            ELSE
                -- RUNTIME_DB_USER set but role absent -> fail loud (0005 WR-04), so a
                -- broken-grant state is detectable in the migration Job, never a silent
                -- runtime "permission denied for table audit_log".
                RAISE EXCEPTION '0006: RUNTIME_DB_USER role % does not exist -- the IAM DB user must exist before the migration Job GRANTs audit_log. Refusing to silently skip.', r;
            END IF;
        END
        $$;
        """
    )


def _revoke_audit_log_from_runtime_sa() -> None:
    """Symmetric, role-existence-guarded REVOKE for downgrade (0005 idiom)."""
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0006 downgrade: %s unset -- nothing to revoke on audit_log.",
            RUNTIME_DB_USER_ENV,
        )
        return

    role_literal = role.replace("'", "''")
    op.execute(
        f"""
        DO $$
        DECLARE
            r text := '{role_literal}';
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.audit_log FROM %I', r);
            END IF;
        END
        $$;
        """
    )


def upgrade() -> None:
    # ---- status columns (soft-deactivate flags). server_default backfills every
    #      existing row non-null on apply (D-05 / D-10).
    op.add_column(
        "organization_memberships",
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        schema=SCHEMA,
    )
    op.add_column(
        "organizations",
        sa.Column(
            "status", sa.String(), nullable=False, server_default="active"
        ),
        schema=SCHEMA,
    )

    # ---- audit_log ROOT table (D-07). Created exactly like the 0001 root tables:
    #      NO _space_id_col(), NO RLS. space_id is a plain nullable UUID with NO FK
    #      so the trail survives a soft-deactivated space.
    op.create_table(
        "audit_log",
        # No server_default on the PK — mirrors the 0001 root tables exactly
        # (the ORM supplies the uuid client-side via default=uuid.uuid4), so
        # `alembic check` sees no drift.
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("actor_uid", sa.String(), nullable=False),
        sa.Column(
            "actor_membership_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA}.organization_memberships.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("target", sa.String(), nullable=True),
        # D-07 root: plain nullable UUID, NO ForeignKey.
        sa.Column("space_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema=SCHEMA,
    )
    # Explicit indexes (names match app/db/models/audit.py — alembic-check clean).
    op.create_index(
        "ix_audit_log_space_id", "audit_log", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "ix_audit_log_created_at", "audit_log", ["created_at"], schema=SCHEMA
    )
    op.create_index(
        "idx_audit_log_event_created",
        "audit_log",
        ["event_type", "created_at"],
        schema=SCHEMA,
    )

    # ---- grants (Pitfall 1): explicit per-table GRANT to BOTH roles. audit_log is
    #      NOT added to any RLS / isolation / superadmin POLICY loop (D-07 root).
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON nestor.audit_log TO app_superadmin"
    )
    _grant_audit_log_to_runtime_sa()


def downgrade() -> None:
    # Reverse order: revoke -> drop indexes -> drop table -> drop status columns.
    _revoke_audit_log_from_runtime_sa()
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON nestor.audit_log FROM app_superadmin"
    )

    op.drop_index("idx_audit_log_event_created", "audit_log", schema=SCHEMA)
    op.drop_index("ix_audit_log_created_at", "audit_log", schema=SCHEMA)
    op.drop_index("ix_audit_log_space_id", "audit_log", schema=SCHEMA)
    op.drop_table("audit_log", schema=SCHEMA)

    op.drop_column("organizations", "status", schema=SCHEMA)
    op.drop_column("organization_memberships", "status", schema=SCHEMA)
