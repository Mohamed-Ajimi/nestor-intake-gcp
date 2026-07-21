"""0011 research_runs — the intake-side Tribunal run mirror table + RLS.

Phase 16 foundation (ENGINE-03). Lands ONE new tenant-OWNED table,
``nestor.research_runs``, that the Phase-16 trigger writes and the poll driver /
SSE stream read. Because it is a fresh tenant surface, it lands with the FULL
isolation contract from day one (Pitfall 5 — a new table is a fresh chance to
reintroduce the broken-RLS bug class):

  - ``space_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE`` +
    the space-LEADING composite indexes whose names match
    ``app/db/models/research_runs.py`` ``__table_args__`` 1:1 (so ``alembic check``
    stays clean).
  - ENABLE + FORCE ROW LEVEL SECURITY, a ``research_runs_space_isolation`` policy
    with the MANDATORY ``NULLIF(current_setting('app.current_space_id', true),
    '')::uuid`` form (empty-string reversion safety, 0002), and a
    ``research_runs_superadmin_all`` bypass policy keyed on the real
    ``current_user = 'app_superadmin'`` predicate (0003 — REQUIRED or a superadmin,
    which carries no GUC, cannot touch the table).
  - Grants: explicit per-table GRANT to ``app_superadmin`` (belt-and-braces over
    0003 ALTER DEFAULT PRIVILEGES) plus the env-guarded runtime-SA DO-block
    (0005/0006/0009 idiom).

STATUS carries the Tribunal literals verbatim ({queued, running, completed,
failed, cancelled}); server_default is ``'queued'``. The model NEVER remaps to the
skill-run vocabulary (D-05 boundary) — the migration mirrors that column shape.

Live ``alembic upgrade`` is DEFERRED on the dev box (author-by-construction, D-10);
the bar is a clean ``alembic check`` (ORM metadata == this migration, index names
included) + the migration-apply test (``test_research_runs_migration.py``) run in
Cloud Build.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-21
"""

from __future__ import annotations

import logging
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# The ONE new tenant-owned table this migration creates (RLS + grants).
_NEW_TABLE = "research_runs"

# Env var carrying the grantee role name = the runtime SA email WITHOUT the
# ".gserviceaccount.com" suffix (mirrors 0005/0006/0009). UNSET on the
# testcontainer, where the runtime-SA grant must no-op cleanly.
RUNTIME_DB_USER_ENV = "RUNTIME_DB_USER"

logger = logging.getLogger("alembic.runtime.migration")


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _id_col():
    """id UUID PK, server_default gen_random_uuid() (pgcrypto, installed in 0001)."""
    return sa.Column(
        "id",
        _uuid(),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _space_id_col():
    """space_id UUID NOT NULL REFERENCES nestor.organizations(id) ON DELETE CASCADE."""
    return sa.Column(
        "space_id",
        _uuid(),
        sa.ForeignKey(f"{SCHEMA}.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )


def _intake_id_col():
    """intake_id UUID NOT NULL REFERENCES nestor.intakes(id) ON DELETE CASCADE."""
    return sa.Column(
        "intake_id",
        _uuid(),
        sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
        nullable=False,
    )


def _runtime_db_user() -> str | None:
    """The grantee role name from the environment, or None when unset/blank."""
    value = os.environ.get(RUNTIME_DB_USER_ENV, "").strip()
    return value or None


def _grant_new_table_to_runtime_sa() -> None:
    """Env-guarded GRANT of the new table to the runtime SA (0005/0006/0009 idiom)."""
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0011: %s unset -- skipping runtime-SA GRANT on research_runs "
            "(no IAM DB user to grant in this environment).",
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
                EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{_NEW_TABLE} TO %I', r);
            ELSE
                RAISE EXCEPTION '0011: RUNTIME_DB_USER role % does not exist -- the IAM DB user must exist before the migration Job GRANTs {_NEW_TABLE}. Refusing to silently skip.', r;
            END IF;
        END
        $$;
        """
    )


def _revoke_new_table_from_runtime_sa() -> None:
    """Symmetric, role-existence-guarded REVOKE for downgrade (0005/0006/0009 idiom)."""
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0011 downgrade: %s unset -- nothing to revoke on research_runs.",
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
                EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{_NEW_TABLE} FROM %I', r);
            END IF;
        END
        $$;
        """
    )


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE RLS + space_isolation (NULLIF form) + superadmin_all bypass.

    Mirrors 0009's ``_enable_rls`` verbatim: 0002 (the mandatory NULLIF
    empty-string-reversion form) + 0003 (the real ``current_user = 'app_superadmin'``
    bypass predicate, NOT the banned constant-true).
    """
    op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_space_isolation ON {SCHEMA}.{table}
            USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
            WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        """
    )
    op.execute(
        f"""
        CREATE POLICY {table}_superadmin_all ON {SCHEMA}.{table}
            USING (current_user = 'app_superadmin')
            WITH CHECK (current_user = 'app_superadmin')
        """
    )


def upgrade() -> None:
    # =====================================================================
    # research_runs — the intake-side Tribunal run mirror (tenant-OWNED).
    # =====================================================================
    op.create_table(
        _NEW_TABLE,
        _id_col(),
        _space_id_col(),
        _intake_id_col(),
        # Tribunal literals carried VERBATIM; default 'queued' (birth state).
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("tribunal_run_id", sa.String(), nullable=True),
        sa.Column("current_stage", sa.String(), nullable=True),
        sa.Column("stage_detail", postgresql.JSONB(), nullable=True),
        sa.Column("cost_usd_total", sa.Numeric(), nullable=True),
        # D-04 attempt tracking: NOT NULL, starts at 1.
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("error_message", sa.Text(), nullable=True),
        # A4: persist raw output on completion so Phase 17 is a pure UI add.
        sa.Column("output_markdown", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    # Space-LEADING composite indexes — names MUST match the ORM __table_args__ 1:1.
    op.create_index(
        "ix_research_runs_space_id", _NEW_TABLE, ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_research_runs_space_intake",
        _NEW_TABLE,
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_research_runs_space_status",
        _NEW_TABLE,
        ["space_id", "status"],
        schema=SCHEMA,
    )

    # =====================================================================
    # RLS: ENABLE+FORCE+space_isolation+superadmin_all for the new table.
    # =====================================================================
    _enable_rls(_NEW_TABLE)

    # =====================================================================
    # Grants (belt-and-braces over 0003 ALTER DEFAULT PRIVILEGES): explicit
    # GRANT to app_superadmin + the env-guarded runtime-SA DO-block.
    # =====================================================================
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{_NEW_TABLE} TO app_superadmin"
    )
    _grant_new_table_to_runtime_sa()


def downgrade() -> None:
    # Reverse order: revoke grants -> drop policies/RLS -> drop indexes + table.
    _revoke_new_table_from_runtime_sa()
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{_NEW_TABLE} FROM app_superadmin"
    )

    op.execute(
        f"DROP POLICY IF EXISTS {_NEW_TABLE}_superadmin_all ON {SCHEMA}.{_NEW_TABLE}"
    )
    op.execute(
        f"DROP POLICY IF EXISTS {_NEW_TABLE}_space_isolation ON {SCHEMA}.{_NEW_TABLE}"
    )
    op.execute(f"ALTER TABLE {SCHEMA}.{_NEW_TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{_NEW_TABLE} DISABLE ROW LEVEL SECURITY")

    op.drop_index("idx_research_runs_space_status", _NEW_TABLE, schema=SCHEMA)
    op.drop_index("idx_research_runs_space_intake", _NEW_TABLE, schema=SCHEMA)
    op.drop_index("ix_research_runs_space_id", _NEW_TABLE, schema=SCHEMA)
    op.drop_table(_NEW_TABLE, schema=SCHEMA)
