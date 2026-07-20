"""0010 make tenant_isolation policies tolerate an EMPTY-STRING app.tenant_id.

Migration 0009 made the policies tolerate an *unset* `app.tenant_id` via the
missing_ok form `current_setting('app.tenant_id', true)` (unset -> NULL ->
`NULL::uuid` -> no match, no error). That fixed the worker's FIRST claim.

But a subtle PostgreSQL behaviour defeats it on later claims: `app.tenant_id`
is a *custom* (placeholder) GUC. Once any transaction on a connection runs
`SET LOCAL app.tenant_id = '<uuid>'` (which execute_run does, via
set_tenant_context, right after claiming a run), the GUC becomes "known" on
that pooled connection. When that transaction ends the value does NOT revert
to unset -- it reverts to the EMPTY STRING ''. So the next claim poll that
reuses the connection sees:

    current_setting('app.tenant_id', true)  ->  ''        (not NULL!)
    ''::uuid                                 ->  ERROR: invalid input syntax for type uuid: ""

RLS policies are OR'd and `worker_all` (current_user='worker_user') is true,
but PostgreSQL still EVALUATES the tenant_isolation branch, and the cast error
aborts the whole statement. The claim raises, propagates out of worker_loop
(the claim step has no try/except) and the worker exit(1)s / crash-loops.

Symptom observed in prod (worker 87497ace): the worker claims one run, then a
later poll dies with
`asyncpg.exceptions.InvalidTextRepresentationError: invalid input syntax for type uuid: ""`.

Fix: wrap the GUC read in `NULLIF(..., '')` so BOTH unset (NULL) and the
empty-string reversion ('') collapse to NULL -> no match -> safe, no error:

    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)

Semantics are otherwise identical to 0009:
  - app_user with a real context: unchanged (exact tenant match).
  - app_user with NO/empty context: USING -> no rows (fail-safe), WITH CHECK ->
    NULL -> writes rejected (fail-loud).
  - worker_user (app.tenant_id unset OR ''): tenant_isolation -> no match,
    worker_all -> true -> sees/writes all rows. No error on either value.

Tables: the five from 0002 (app_user, project, run, output, audit_log) plus the
three citation tables from 0003 (source, claim, claim_source).

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0010"
down_revision: Union[str, None] = "0009"
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


def _recreate(table: str, expr: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_tenant_isolation ON {table}")
    op.execute(
        f"""
        CREATE POLICY {table}_tenant_isolation ON {table}
            USING (tenant_id = {expr})
            WITH CHECK (tenant_id = {expr})
        """
    )


# 0010: NULLIF collapses both unset (NULL) and the empty-string ('') GUC
# reversion to NULL before the uuid cast.
_EXPR_EMPTY_OK = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
# 0009 form (missing_ok only) -- used by downgrade to restore prior behaviour.
_EXPR_MISSING_OK = "current_setting('app.tenant_id', true)::uuid"


def upgrade() -> None:
    for table in _RLS_TABLES:
        _recreate(table, _EXPR_EMPTY_OK)


def downgrade() -> None:
    for table in _RLS_TABLES:
        _recreate(table, _EXPR_MISSING_OK)
