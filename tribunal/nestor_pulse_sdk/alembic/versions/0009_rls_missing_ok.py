"""0009 make tenant_isolation policies tolerate an unset app.tenant_id.

Migration 0002/0003 wrote the tenant_isolation policies with the bare
`current_setting('app.tenant_id')::uuid` (no missing_ok arg), deliberately
so an unset GUC raises ("fail loud"). That works when app_user always sets
the context — but it breaks the worker.

The worker connects as worker_user and relies on the `*_worker_all` policy
(0008, `current_user = 'worker_user'`) to claim across all tenants WITHOUT
setting app.tenant_id. RLS policies are OR'd, but PostgreSQL still EVALUATES
the tenant_isolation branch, and `current_setting('app.tenant_id')::uuid`
raises `unrecognized configuration parameter` when unset — even though the
worker_all branch is true. The worker crash-loops on its first claim.

Fix: recreate every tenant_isolation policy with the missing_ok form
`current_setting('app.tenant_id', true)::uuid`. When unset this yields NULL:
  - USING:  `tenant_id = NULL` -> no rows (safe; no error). For app_user with a
    forgotten context this now returns EMPTY instead of erroring — fail-SAFE
    rather than fail-loud, but still no cross-tenant leak.
  - WITH CHECK: `tenant_id = NULL` -> NULL -> INSERT/UPDATE REJECTED. Writes
    still fail loud, so a missing context can never silently write wrong-tenant
    rows.
  - worker_user (app.tenant_id unset): tenant_isolation -> no match, worker_all
    -> true -> sees/writes all rows. No error.

Tables: the five from 0002 (app_user, project, run, output, audit_log) plus the
three citation tables from 0003 (source, claim, claim_source).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RLS_TABLES = (
    "app_user",
    "project",
    "run",
    "output",
    "audit_log",
    "source",
    "claim",
    "claim_source",
)


def _recreate(table: str, missing_ok: bool) -> None:
    arg = "'app.tenant_id', true" if missing_ok else "'app.tenant_id'"
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = current_setting({arg})::uuid)
            WITH CHECK (tenant_id = current_setting({arg})::uuid)
        """
    )


def upgrade() -> None:
    for table in _RLS_TABLES:
        _recreate(table, missing_ok=True)


def downgrade() -> None:
    for table in _RLS_TABLES:
        _recreate(table, missing_ok=False)
