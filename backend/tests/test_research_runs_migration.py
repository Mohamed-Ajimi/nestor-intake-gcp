"""Migration-apply verification for 0011 ``research_runs`` (Phase 16, ENGINE-03)
and 0012 ``research_run_chain_bundle`` (Phase 17, RUN-03).

Split in two:

  * A pure SOURCE/AST suite (no DB, no Docker) that runs on the dev box (D-10):
    revision chaining (0011 -> 0010), both RLS policy forms present, the three
    index names matching the ORM 1:1, and the grants (app_superadmin + env-guarded
    runtime-SA DO-block) — mirrors ``test_grant_migration.py``'s no-DB discipline.
    Phase-17 adds the 0012 add-column suite: it chains 0012 -> 0011, adds exactly
    the three nullable columns (``chain_status`` / ``chain_broken_at`` /
    ``bundle_key``), and touches NO RLS policy, grant, or index (the new columns
    inherit ``research_runs``' existing FORCE-RLS row policy from 0011).

  * An ``integration``-marked suite that consumes the conftest ``engine`` fixture
    (which runs ``alembic upgrade head`` as the non-superuser owner) and asserts
    against the LIVE schema: the table exists, both ``research_runs`` RLS policies
    exist (``pg_policies``), the three named indexes exist (``pg_indexes``), and
    the three Phase-17 columns exist and are nullable (``information_schema``).
    Skipped cleanly on a box with no Docker/DSN (Wave-0 harness contract).

Authoritative references:
- .planning/phases/16-research-trigger-progress-bridge/16-01-PLAN.md Task 2.
- .planning/phases/17-raw-output-audit-chain-guard/17-01-PLAN.md Task 1.
- backend/app/db/alembic/versions/0009_ai_ports.py (the RLS + grants analog).
- backend/tests/test_schema_shape.py (the pg_policies / index / table probes).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# backend/tests/test_research_runs_migration.py -> backend/ is parents[1]
_BACKEND = Path(__file__).resolve().parents[1]
_MIGRATION = (
    _BACKEND / "app" / "db" / "alembic" / "versions" / "0011_research_runs.py"
)
_MIGRATION_0012 = (
    _BACKEND
    / "app"
    / "db"
    / "alembic"
    / "versions"
    / "0012_research_run_chain_bundle.py"
)

SCHEMA = "nestor"
TABLE = "research_runs"

# The three nullable columns 0012 adds (Phase 17, RUN-03).
_CHAIN_BUNDLE_COLUMNS = (
    "chain_status",
    "chain_broken_at",
    "bundle_key",
)

# The three index names the ORM __table_args__ declares — MUST match 1:1.
_EXPECTED_INDEXES = (
    "ix_research_runs_space_id",
    "idx_research_runs_space_intake",
    "idx_research_runs_space_status",
)

# The two RLS policies every new tenant table must carry (0002 + 0003 forms).
_EXPECTED_POLICIES = (
    "research_runs_space_isolation",
    "research_runs_superadmin_all",
)


def _source() -> str:
    return _MIGRATION.read_text(encoding="utf-8")


def _source_0012() -> str:
    return _MIGRATION_0012.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Source/AST suite — no DB, runs on the dev box (D-10).
# ---------------------------------------------------------------------------

def test_migration_file_exists() -> None:
    assert _MIGRATION.is_file(), f"missing migration file: {_MIGRATION}"


def test_revision_chains_onto_0010() -> None:
    """0011 must declare revision '0011' and chain onto down_revision '0010'."""
    tree = ast.parse(_source())
    assigns: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                assigns[node.target.id] = node.value.value

    assert assigns.get("revision") == "0011", assigns
    assert assigns.get("down_revision") == "0010", assigns


def test_creates_research_runs_with_space_fk() -> None:
    """The migration creates research_runs with a space_id NOT NULL FK."""
    src = _source()
    assert 'op.create_table(' in src
    assert '_NEW_TABLE = "research_runs"' in src
    # space_id FK to organizations(id) ON DELETE CASCADE (via the _space_id_col helper).
    assert "organizations.id" in src
    assert 'ondelete="CASCADE"' in src


def test_declares_both_rls_policies_correct_forms() -> None:
    """Both policies exist with the mandatory forms (NULLIF GUC + current_user bypass)."""
    src = _source()
    # space_isolation with the empty-string-reversion NULLIF form (0002).
    assert "research_runs_space_isolation" in src
    assert (
        "NULLIF(current_setting('app.current_space_id', true), '')::uuid" in src
    )
    # superadmin_all with the real current_user predicate (0003) — NOT constant-true.
    assert "research_runs_superadmin_all" in src
    assert "current_user = 'app_superadmin'" in src
    # The banned permissive form must NOT appear anywhere.
    assert "USING (true)" not in src


def test_declares_three_named_indexes_matching_orm() -> None:
    """The migration creates exactly the three ORM index names."""
    src = _source()
    for idx in _EXPECTED_INDEXES:
        assert f'"{idx}"' in src, f"migration missing index {idx}"


def test_carries_grants() -> None:
    """Explicit app_superadmin GRANT + the env-guarded runtime-SA DO-block are present."""
    src = _source()
    assert (
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{TABLE} TO app_superadmin"
        in src
    )
    # Env-guarded runtime-SA grant (RUNTIME_DB_USER + pg_roles existence guard).
    assert "RUNTIME_DB_USER" in src
    assert "pg_roles" in src


def test_status_default_queued_not_remapped() -> None:
    """status server_default is 'queued'; the skill-run 'succeeded' literal is absent."""
    src = _source()
    assert 'server_default="queued"' in src
    # D-05 boundary: the run-status column must NOT carry the skill-run vocabulary.
    assert "succeeded" not in src


def test_defines_symmetric_downgrade() -> None:
    src = _source()
    assert "def downgrade" in src
    assert "op.drop_table" in src
    assert "REVOKE" in src
    for idx in _EXPECTED_INDEXES:
        assert f'op.drop_index("{idx}"' in src, f"downgrade missing drop_index {idx}"


# ---------------------------------------------------------------------------
# 0012 source/AST suite (Phase 17) — no DB, runs on the dev box (D-10).
# ---------------------------------------------------------------------------

def test_0012_migration_file_exists() -> None:
    assert _MIGRATION_0012.is_file(), f"missing migration file: {_MIGRATION_0012}"


def test_0012_revision_chains_onto_0011() -> None:
    """0012 must declare revision '0012' and chain onto down_revision '0011'."""
    tree = ast.parse(_source_0012())
    assigns: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if isinstance(node.value, ast.Constant) and isinstance(
                node.value.value, str
            ):
                assigns[node.target.id] = node.value.value
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (
                    isinstance(tgt, ast.Name)
                    and isinstance(node.value, ast.Constant)
                    and isinstance(node.value.value, str)
                ):
                    assigns[tgt.id] = node.value.value

    assert assigns.get("revision") == "0012", assigns
    assert assigns.get("down_revision") == "0011", assigns


def test_0012_adds_three_nullable_columns() -> None:
    """upgrade() adds exactly the three nullable chain/bundle columns."""
    src = _source_0012()
    for col in _CHAIN_BUNDLE_COLUMNS:
        assert f'"{col}"' in src, f"0012 missing add_column for {col}"
    # Each new column is nullable (pre-existing live rows must not break).
    assert "nullable=True" in src
    # Exactly three op.add_column calls (no stray column additions).
    assert src.count("op.add_column(") == 3, "0012 must add exactly 3 columns"
    # The columns target the mirror table under the nestor schema qualifier.
    assert '"research_runs"' in src
    assert 'schema="nestor"' in src or "schema=SCHEMA" in src


def test_0012_no_rls_policy_grant_or_index() -> None:
    """The add-column migration touches NO policy, grant, or index (inherits 0011's)."""
    src = _source_0012()
    assert "op.create_index" not in src, "0012 must not create an index"
    assert "CREATE POLICY" not in src, "0012 must not create an RLS policy"
    assert "GRANT" not in src, "0012 must not issue a GRANT"


def test_0012_no_server_default_on_new_columns() -> None:
    """The three columns are added WITHOUT a server_default (completion path sets them)."""
    src = _source_0012()
    assert "server_default" not in src, (
        "0012 columns must be NULL until the completion path writes them"
    )


def test_0012_symmetric_downgrade_drops_three_columns() -> None:
    """downgrade() drops exactly the three columns (reverse order)."""
    src = _source_0012()
    assert "def downgrade" in src
    assert src.count("op.drop_column(") == 3, "0012 must drop exactly 3 columns"
    for col in _CHAIN_BUNDLE_COLUMNS:
        assert col in src, f"0012 downgrade missing drop_column for {col}"


# ---------------------------------------------------------------------------
# Integration suite — needs a live migrated DB (skipped without Docker/DSN).
# ---------------------------------------------------------------------------

integration = pytest.mark.integration


@integration
def test_research_runs_table_exists(engine) -> None:
    """``nestor.research_runs`` is present after ``alembic upgrade head``."""
    from sqlalchemy import text

    with engine.connect() as conn:
        present = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = :schema AND table_name = :tbl"
            ),
            {"schema": SCHEMA, "tbl": TABLE},
        ).first()
    assert present is not None, f"missing table {SCHEMA}.{TABLE}"


@integration
def test_research_runs_both_policies_exist(engine) -> None:
    """Both RLS policies exist on ``research_runs`` (pg_policies)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT policyname FROM pg_policies "
                "WHERE schemaname = :schema AND tablename = :tbl"
            ),
            {"schema": SCHEMA, "tbl": TABLE},
        ).all()
    present = {r[0] for r in rows}
    missing = [p for p in _EXPECTED_POLICIES if p not in present]
    assert not missing, f"missing policies on {TABLE}: {missing} (present: {sorted(present)})"


@integration
def test_research_runs_three_indexes_exist(engine) -> None:
    """The three space-leading composite indexes exist (pg_indexes)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = :schema AND tablename = :tbl"
            ),
            {"schema": SCHEMA, "tbl": TABLE},
        ).all()
    present = {r[0] for r in rows}
    missing = [i for i in _EXPECTED_INDEXES if i not in present]
    assert not missing, f"missing indexes on {TABLE}: {missing} (present: {sorted(present)})"


@integration
def test_research_runs_chain_bundle_columns_nullable(engine) -> None:
    """0012's three chain/bundle columns exist and are nullable (information_schema)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = :tbl "
                "AND column_name = ANY(:cols)"
            ),
            {
                "schema": SCHEMA,
                "tbl": TABLE,
                "cols": list(_CHAIN_BUNDLE_COLUMNS),
            },
        ).all()
    nullable_by_name = {r[0]: r[1] for r in rows}
    for col in _CHAIN_BUNDLE_COLUMNS:
        assert col in nullable_by_name, (
            f"missing column {col} on {TABLE} (present: {sorted(nullable_by_name)})"
        )
        assert nullable_by_name[col] == "YES", (
            f"column {col} must be nullable (is_nullable={nullable_by_name[col]!r})"
        )
