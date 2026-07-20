"""0002 RLS policies for tenant-scoped tables.

RLS policies per D-05 -- enforced at the DB layer; application MUST NOT
rely on WHERE clauses alone. Pitfall 1: every caller MUST use SET LOCAL
(third-arg-true) before any tenant-scoped query.

Per 01-RESEARCH.md § Pattern 1 (lines 374-387):
- ENABLE + FORCE ROW LEVEL SECURITY on every tenant-scoped table.
  FORCE applies even to the table owner (defense-in-depth against a
  misconfigured GRANT or a runaway migration script).
- One `<table>_tenant_isolation` policy per table with USING + WITH CHECK
  both equal to `tenant_id = current_setting('app.tenant_id')::uuid`.

current_setting uses the 2-arg form inside the policy. The session-side
helper (db.rls.set_tenant_context) uses
set_config('app.tenant_id', :tid, true) -- the policy then reads the value
via current_setting. The READ does NOT use the missing_ok arg here: if no
value has been set, the cast to uuid raises, which is the correct
fail-loud behaviour (Pitfall 1: never silently allow a wildcard tenant).

Citation tables (source/claim/claim_source) get their RLS in 0003 (with
the citation schema itself).

Tables in scope here: app_user, project, run, output, audit_log.
Org is NOT included because it IS the tenant.

The policies are written out inline (rather than via a Python loop)
so the migration file is verbatim-greppable and matches the verbatim
DDL example in RESEARCH lines 374-387.

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------------- app_user
    op.execute("ALTER TABLE app_user ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_user FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY app_user_tenant_isolation ON app_user
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # ----------------------------------------------------------- project
    op.execute("ALTER TABLE project ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE project FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY project_tenant_isolation ON project
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # --------------------------------------------------------------- run
    op.execute("ALTER TABLE run ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE run FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY run_tenant_isolation ON run
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # ------------------------------------------------------------ output
    op.execute("ALTER TABLE output ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE output FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY output_tenant_isolation ON output
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # --------------------------------------------------------- audit_log
    op.execute("ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY audit_log_tenant_isolation ON audit_log
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )


def downgrade() -> None:
    # Reverse order -- DROP POLICY first, then NO FORCE, then DISABLE.

    op.execute("DROP POLICY IF EXISTS audit_log_tenant_isolation ON audit_log")
    op.execute("ALTER TABLE audit_log NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE audit_log DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS output_tenant_isolation ON output")
    op.execute("ALTER TABLE output NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE output DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS run_tenant_isolation ON run")
    op.execute("ALTER TABLE run NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE run DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS project_tenant_isolation ON project")
    op.execute("ALTER TABLE project NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE project DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS app_user_tenant_isolation ON app_user")
    op.execute("ALTER TABLE app_user NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE app_user DISABLE ROW LEVEL SECURITY")
