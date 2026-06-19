"""0005 GRANT the runtime SA IAM DB user into the space-scoped nestor role.

This is the single most load-bearing piece of SQL in Phase 2 (OQ1 / Assumption
A5 in 02-RESEARCH.md). On Cloud SQL the Cloud Run runtime service account
connects with IAM database authentication as a ``google_sql_user`` of
``type = CLOUD_IAM_SERVICE_ACCOUNT``. That user is created with **login only and
ZERO Postgres privileges** (verified: docs.cloud.google.com/sql/docs/postgres/
iam-logins). Until it is GRANTed USAGE on schema ``nestor`` + DML on the tenant
tables, the very first live ``/readyz`` real query (and every Phase 3/4 query)
fails with ``permission denied for schema nestor`` (RESEARCH Pitfall 3). This
migration performs that GRANT, versioned and reproducible, so the privilege is
not a hand-run runbook side effect.

WHY a migration (not runbook-only): the GRANT is durable, ordered DB state that
must travel with the schema. Encoding it as Alembic revision 0005 makes it
reproducible against any instance, re-runnable, and reverted by ``downgrade`` —
unlike a one-off ``psql`` step in the runbook that drifts and is easy to skip.

WHAT this grantee gets (the de-facto SPACE-SCOPED app role):
  - ``GRANT USAGE ON SCHEMA nestor``
  - ``GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA nestor``
  - ``GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA nestor``
  - ``ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER`` covering FUTURE tables +
    sequences (mirrors 0003's future-object coverage, keyed on the migration
    owner role at apply time so it stays instance-portable).

WHAT this grantee deliberately does NOT get (Pitfall 3 — RLS MUST still apply):
  - NOT membership of / privileges of the Phase-1 superadmin role — that role
    carries the 0003 ``*_superadmin_all`` cross-tenant BYPASS policy. Granting it
    would let the runtime SA read/write EVERY space, defeating tenant isolation.
  - NO new RLS policy created — this migration adds zero policies. The runtime SA
    stays subject to the 0002 ``*_space_isolation`` policies, so RLS scopes it by
    the transaction-local ``app.current_space_id`` GUC (rls.py contract, the
    space context the backend sets per request in Phase 4).
The runtime SA is therefore exactly a NON-superadmin login: it has the table
DML the isolation policies need, and RLS narrows every row to the active space.

ROLE MODEL NOTE (verified against Phase-1 migrations 0002/0003): Phase 1 creates
ONLY ONE named role out of band — the superadmin LOGIN role (with the bypass
policy). There is NO separate named "app" role to ``GRANT app TO <sa>``. The
"app role" is simply "whatever non-superadmin login connects", scoped by RLS. So
the runtime SA receives the space-scoped privileges DIRECTLY (the same schema
USAGE + table DML that 0003 gave the superadmin role, MINUS the bypass policy),
which makes it a non-superadmin == space-scoped login by construction.

PARAMETERIZATION + FAIL-SAFE (so the testcontainer chain stays green):
The SA email (the grantee role NAME) is only known at provisioning time, so it
is read from the ``RUNTIME_DB_USER`` env var (the migration Job sets it to
``trimsuffix(<runtime SA email>, ".gserviceaccount.com")`` — same value the
Cloud Run service uses for ``DB_USER``). When ``RUNTIME_DB_USER`` is UNSET (the
pgvector testcontainer in conftest — which never provisions an IAM SA user),
this migration NO-OPs cleanly with a logged notice, so ``alembic upgrade head``
over 0001->0005 still succeeds on the container. When it IS set but the role
does not yet exist, the GRANTs are wrapped in a DO block that checks
``pg_roles`` first (mirroring conftest's role-ensure guard) so a
fresh apply ordering cannot fail.

CONFIDENCE FLAG (Manual-Only — 02-VALIDATION.md): this IAM-SA-user <-> Phase-1
RLS role mapping is the LOW-confidence research item (A5). The live GRANT/role
behavior (does ``/readyz``'s real query succeed under the granted SA, and does
RLS still scope it?) is verified by the user in GCP per D-10, not on this dev
box. The 02-03 Task 4 checkpoint hands that verification off; if a
``permission denied for schema nestor`` surfaces, this mapping is the thing to
correct.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-19
"""

from __future__ import annotations

import logging
import os
from typing import Sequence, Union

from alembic import op


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# Env var carrying the grantee role name = the runtime SA email WITHOUT the
# ".gserviceaccount.com" suffix (the IAM DB username). The Cloud Run migration
# Job sets this (infra/main.tf google_cloud_run_v2_job env RUNTIME_DB_USER). It
# is UNSET on the testcontainer, where this migration must no-op.
RUNTIME_DB_USER_ENV = "RUNTIME_DB_USER"

logger = logging.getLogger("alembic.runtime.migration")


def _runtime_db_user() -> str | None:
    """The grantee role name from the environment, or None when unset/blank."""
    value = os.environ.get(RUNTIME_DB_USER_ENV, "").strip()
    return value or None


def upgrade() -> None:
    role = _runtime_db_user()
    if role is None:
        # Testcontainer / local path: no IAM SA user exists to grant. Skip
        # cleanly so the 0001->0005 chain still applies (RUNTIME_DB_USER unset).
        logger.info(
            "0005: %s unset -- skipping runtime-SA GRANT (no IAM DB user to "
            "grant in this environment).",
            RUNTIME_DB_USER_ENV,
        )
        return

    # Quote the role identifier as a literal inside the DO block. IAM SA usernames
    # contain '@' and '.', so they MUST be double-quoted everywhere they are used
    # as identifiers. We build a quoted identifier and embed it; the role string
    # itself is also passed through a guard that checks pg_roles first so a not-yet
    # -existing role cannot abort the migration.
    quoted = '"' + role.replace('"', '""') + '"'
    role_literal = role.replace("'", "''")

    # Fail-safe: only run the GRANTs if the role actually exists (the IAM SA user
    # is created out of band by Terraform's google_sql_user / the runbook). The
    # DO block mirrors the conftest role-ensure pg_roles guard.
    #
    # WR-04: reaching this DO block means RUNTIME_DB_USER IS set (the env-unset
    # path already returned early above -- that is the clean testcontainer no-op).
    # So a set-but-absent role here means the migration Job was told to grant a
    # role that does not exist. That must FAIL LOUD (RAISE EXCEPTION), not be a
    # silent NOTICE-skip that leaves the runtime SA with zero privileges and a live
    # /readyz returning 503 with no migration error to point at. The exception
    # aborts `alembic upgrade head` with a non-zero exit, surfacing in
    # `gcloud run jobs execute --wait` so the broken-GRANT state is detectable.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_literal}') THEN
                -- USAGE on the schema (the runtime SA must reach nestor objects).
                EXECUTE 'GRANT USAGE ON SCHEMA {SCHEMA} TO {quoted}';
                -- DML on every tenant table so the 0002 *_space_isolation policies
                -- can apply (RLS needs the base privilege to then narrow rows).
                EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} TO {quoted}';
                -- Sequences backing any serial/identity columns.
                EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} TO {quoted}';
                -- Cover FUTURE tables/sequences created by later migrations. Keyed
                -- on the migration owner (CURRENT_USER) exactly like 0003.
                EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted}';
                EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} GRANT USAGE, SELECT ON SEQUENCES TO {quoted}';
                -- NOTE: deliberately NO grant of the superadmin role and NO
                -- new policy here. The runtime SA stays a non-superadmin,
                -- space-scoped login subject to RLS (Pitfall 3).
            ELSE
                -- WR-04: RUNTIME_DB_USER is set but the role is missing -> FAIL
                -- LOUD instead of silently skipping the load-bearing GRANT. The
                -- env-unset testcontainer skip never reaches here (handled in
                -- Python above), so this exception only fires under the Job.
                RAISE EXCEPTION '0005: RUNTIME_DB_USER role % does not exist -- the IAM DB user must exist before the migration Job runs the GRANT (create the google_sql_user / IAM DB user, then re-run alembic upgrade head). Refusing to silently skip the runtime-SA GRANT.', '{role_literal}';
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0005 downgrade: %s unset -- nothing to revoke.", RUNTIME_DB_USER_ENV
        )
        return

    quoted = '"' + role.replace('"', '""') + '"'
    role_literal = role.replace("'", "''")

    # Symmetric REVOKE, also guarded on role existence so a downgrade on an
    # instance where the role was already dropped does not fail.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role_literal}') THEN
                EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} REVOKE USAGE, SELECT ON SEQUENCES FROM {quoted}';
                EXECUTE 'ALTER DEFAULT PRIVILEGES FOR ROLE CURRENT_USER IN SCHEMA {SCHEMA} REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {quoted}';
                EXECUTE 'REVOKE USAGE, SELECT ON ALL SEQUENCES IN SCHEMA {SCHEMA} FROM {quoted}';
                EXECUTE 'REVOKE SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA {SCHEMA} FROM {quoted}';
                EXECUTE 'REVOKE USAGE ON SCHEMA {SCHEMA} FROM {quoted}';
            END IF;
        END
        $$;
        """
    )
