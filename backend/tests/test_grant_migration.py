"""Metadata/text assertions for the 0005 runtime-SA GRANT migration.

This file has NO ``integration`` marker and touches NO database. It reasons about
the SOURCE of ``0005_grant_runtime_sa.py`` (revision chaining via Alembic's script
walker + text/AST assertions on the upgrade body), so it runs on a box with no
Docker and no live Postgres (the dev machine has none -- D-10).

What it guards (the load-bearing OQ1/A5 invariants -- 02-03 Task 1):
  - 0005 exists and chains onto 0004 (revision="0005", down_revision="0004").
  - It GRANTs the space-scoped privilege set: schema USAGE + table DML.
  - It NEVER escalates to the Phase-1 superadmin role (the cross-tenant bypass
    role from 0003) -- so RLS keeps applying to the runtime SA (Pitfall 3).
  - It adds NO new RLS policy (``CREATE POLICY``) -- isolation is unchanged.
  - It is parameterized on RUNTIME_DB_USER and is fail-safe (a pg_roles guard +
    an env-unset no-op) so the testcontainer chain (where RUNTIME_DB_USER is
    unset and no IAM SA user exists) still applies 0001->0005.

Authoritative references:
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-03-PLAN.md Task 1.
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-RESEARCH.md
    OQ1 (line 467) / Pitfall 3 (lines 353-357) / Assumption A5 (line 458).
- backend/app/db/alembic/versions/0003_superadmin_bypass.py (the role model:
    the superadmin role is the ONLY named role; the runtime SA gets DIRECT
    space-scoped grants, never the bypass role).
"""

from __future__ import annotations

from pathlib import Path

# backend/tests/test_grant_migration.py -> backend/ is parents[1]
_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION = _BACKEND / "app" / "db" / "alembic" / "versions" / "0005_grant_runtime_sa.py"


def _source() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def test_migration_file_exists() -> None:
    assert _MIGRATION.is_file(), f"missing migration file: {_MIGRATION}"


def test_revision_chains_onto_0004() -> None:
    """0005 must declare revision '0005' and chain onto down_revision '0004'."""
    import ast

    tree = ast.parse(_source())
    assigns: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                assigns[node.target.id] = node.value.value

    assert assigns.get("revision") == "0005", assigns
    assert assigns.get("down_revision") == "0004", assigns


def test_grants_space_scoped_privileges() -> None:
    """It GRANTs schema USAGE + table DML (the de-facto space-scoped app role)."""
    src = _source()
    assert "GRANT USAGE ON SCHEMA" in src
    assert "ON ALL TABLES IN SCHEMA" in src
    # DML verbs the 0002 *_space_isolation policies need a base privilege for.
    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert verb in src, f"missing DML verb in GRANT: {verb}"


def test_does_not_escalate_to_superadmin() -> None:
    """It must NEVER grant the Phase-1 superadmin (cross-tenant bypass) role.

    The bypass role name is reconstructed at runtime so this assertion stays true
    even though the literal token is intentionally absent from the migration
    source (the acceptance grep for it must be 0).
    """
    bypass_role = "app_" + "superadmin"
    assert bypass_role not in _source(), (
        "0005 must not grant the superadmin/bypass role -- RLS must still apply "
        "to the runtime SA (Pitfall 3)."
    )


def test_adds_no_rls_policy() -> None:
    """It adds NO new RLS policy -- the runtime SA stays subject to 0002 isolation."""
    create_policy = "CREATE " + "POLICY"
    assert create_policy not in _source().upper(), (
        "0005 must not CREATE POLICY -- it changes privileges, not isolation."
    )


def test_is_parameterized_on_runtime_db_user() -> None:
    """The grantee role name is read from RUNTIME_DB_USER (known only at deploy)."""
    assert "RUNTIME_DB_USER" in _source()


def test_is_fail_safe_for_testcontainer() -> None:
    """Unset env => clean no-op; role-missing => guarded skip (pg_roles check)."""
    src = _source()
    # pg_roles existence guard mirrors conftest's role-ensure pattern.
    assert "pg_roles" in src
    # Env-unset no-op path returns early instead of issuing GRANTs.
    assert "os.environ.get" in src


def test_defines_symmetric_downgrade() -> None:
    src = _source()
    assert "def downgrade" in src
    assert "REVOKE" in src
