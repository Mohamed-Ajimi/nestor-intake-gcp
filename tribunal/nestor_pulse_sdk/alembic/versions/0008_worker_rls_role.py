"""0008 worker_user role privileges + "worker sees all" RLS policies.

The async worker (runs/worker.py) must claim queued runs ACROSS all tenants
(it does not know a run's tenant until it reads the row), then SET LOCAL
app.tenant_id to the claimed run's tenant for all subsequent work.

worker.py's docstring assumed a BYPASSRLS role. **Cloud SQL does NOT permit
BYPASSRLS** -- only the Google-internal `cloudsqladmin` role carries it, and
neither `postgres` (cloudsqlsuperuser, not a true superuser) nor `app_user`
can grant it (PostgreSQL: you can only grant BYPASSRLS if you have it).

Cloud-SQL-compatible equivalent: a dedicated login role `worker_user` plus a
permissive per-table RLS policy `USING (current_user = 'worker_user')`. RLS
policies are OR'd, so:
  - worker_user matches the worker_all policy -> sees/writes ALL rows (the
    cross-tenant claim works), exactly like BYPASSRLS.
  - app_user (the API) does NOT match worker_all; it still matches only the
    tenant_isolation policy -> stays tenant-scoped. API isolation is unchanged.

Security is equivalent to BYPASSRLS: worker_user's credentials live only in
Secret Manager (DATABASE_URL_WORKER), used solely by the worker Cloud Run
service. Tenants never hold that role; the API connects as app_user.

worker_user is created out-of-band as a Cloud SQL BUILT_IN user
(`gcloud sql users create worker_user ...`), mirroring how app_user was
created. This migration only grants it privileges + adds the policies, so it
is reproducible against any instance where the role already exists.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-15
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tenant-scoped tables carrying RLS (0002 + 0003). Org is excluded (it IS the
# tenant and is not RLS-scoped).
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


def upgrade() -> None:
    # ---- Privileges: worker_user needs DML on every tenant table + sequences.
    op.execute("GRANT USAGE ON SCHEMA public TO worker_user")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "TO worker_user"
    )
    op.execute(
        "GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO worker_user"
    )
    # Cover tables/sequences created by FUTURE migrations too (app_user owns them).
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO worker_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public "
        "GRANT USAGE, SELECT ON SEQUENCES TO worker_user"
    )

    # ---- "worker sees all" policy on each tenant table (OR'd with isolation).
    for table in _RLS_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_worker_all ON {table}
                USING (current_user = 'worker_user')
                WITH CHECK (current_user = 'worker_user')
            """
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_worker_all ON {table}")

    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM worker_user"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN SCHEMA public "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM worker_user"
    )
    op.execute(
        "REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public FROM worker_user"
    )
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
        "FROM worker_user"
    )
    op.execute("REVOKE USAGE ON SCHEMA public FROM worker_user")
