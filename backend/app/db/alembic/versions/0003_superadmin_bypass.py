"""0003 app_superadmin cross-tenant bypass (grants + per-table bypass policy).

The Agenic superadmin must operate ACROSS all spaces (cross-tenant reads and
writes) — it is the ONLY role permitted to cross the per-space isolation
boundary the 0002 ``*_space_isolation`` policies enforce. The normal app role
stays scoped to its ``app.current_space_id`` GUC.

Why NOT ``BYPASSRLS``: **Cloud SQL does NOT permit BYPASSRLS.** Only the
Google-internal ``cloudsqladmin`` role carries it; neither ``postgres``
(``cloudsqlsuperuser`` — not a true superuser) nor the app role can grant it
(PostgreSQL: you may only grant BYPASSRLS if you already hold it). So this
migration uses the Cloud-SQL-compatible equivalent: a dedicated login role
``app_superadmin`` plus a permissive per-table RLS policy keyed on a REAL
predicate ``current_user = 'app_superadmin'``. This is NOT the banned
constant-true predicate (QA-02 / D-07) — it matches one specific role only.

RLS policies are OR'd, so once both 0002 and 0003 are applied:
  - ``app_superadmin`` matches the ``<t>_superadmin_all`` policy -> sees/writes
    ALL rows in every space (the cross-tenant bypass), exactly like BYPASSRLS.
  - the normal app role does NOT match ``<t>_superadmin_all``; it still matches
    only ``<t>_space_isolation`` -> stays space-scoped. Tenant isolation for the
    app role is unchanged.

PREREQUISITE — the ``app_superadmin`` LOGIN role is created OUT OF BAND, before
this migration runs:
  - on real Cloud SQL: ``gcloud sql users create app_superadmin ...`` (a
    BUILT_IN user), mirroring how the app role is provisioned;
  - in the test suite: ``tests/conftest.py::_ensure_app_superadmin`` creates it
    in the pgvector container (idempotent DO-block).
This migration assumes the role already exists and only grants it privileges +
adds the bypass policies, so it is reproducible against any instance/container
where the role is present. ``app_superadmin``'s credentials live only in Secret
Manager and are used solely by the superadmin code path; tenants never hold it.

The bypass policy is created in a LOOP here (acceptable — unlike 0002, the
policy predicate is a real ``current_user =`` literal, not the greppable
constant-true predicate the QA-02 guard bans).

Tables in scope: the 12 tenant-OWNED tables that carry 0002's isolation
policies. organizations + organization_memberships are the tenant ROOT and are
not RLS-scoped.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# The 12 tenant-owned tables carrying 0002's *_space_isolation policies. The
# bypass policy is OR'd with isolation, one per table.
_RLS_TABLES = (
    "products",
    "intake_templates",
    "intakes",
    "intake_answers",
    "skill_runs",
    "decompositions",
    "research_questions",
    "research_artifacts",
    "findings",
    "deliverables",
    "artifact_embeddings",
    "search_index",
)


def upgrade() -> None:
    # ---- Privileges: app_superadmin needs schema usage + DML on every tenant
    #      table + sequences in schema nestor (it is the cross-tenant operator).
    op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO app_superadmin")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
        "TO app_superadmin"
    )
    op.execute(
        f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO app_superadmin"
    )
    # Cover tables/sequences created by FUTURE migrations too. Default privileges
    # are keyed on the role that CREATES the objects; the migration role (the
    # table owner from 0001) creates them, so grant FOR that role. CURRENT_USER
    # is the migration/owner role at apply time, keeping this instance-portable.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} "
        "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_superadmin"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} "
        "GRANT USAGE, SELECT ON SEQUENCES TO app_superadmin"
    )

    # ---- "superadmin sees all" bypass policy per tenant table (OR'd with the
    #      0002 *_space_isolation policy). Real current_user predicate, NOT the
    #      banned constant-true predicate.
    for table in _RLS_TABLES:
        op.execute(
            f"""
            CREATE POLICY {table}_superadmin_all ON {SCHEMA}.{table}
                USING (current_user = 'app_superadmin')
                WITH CHECK (current_user = 'app_superadmin')
            """
        )


def downgrade() -> None:
    for table in _RLS_TABLES:
        op.execute(
            f"DROP POLICY IF EXISTS {table}_superadmin_all ON {SCHEMA}.{table}"
        )

    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} "
        "REVOKE USAGE, SELECT ON SEQUENCES FROM app_superadmin"
    )
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} "
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM app_superadmin"
    )
    op.execute(
        f"REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} "
        "FROM app_superadmin"
    )
    op.execute(
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} "
        "FROM app_superadmin"
    )
    op.execute(f"REVOKE USAGE ON SCHEMA {SCHEMA} FROM app_superadmin")
