"""
Schema-shape verification suite — covers INFRA-02, TENANT-01, and success
criterion 4 (vector(1536), no index).

These tests are RED-by-design in Wave 0: the schema does not exist until plan
01-02 lands the Alembic baseline migration. They turn GREEN once
`alembic upgrade head` (driven by the conftest `engine` fixture) builds the
`nestor` schema.

Authoritative references:
- .planning/phases/01-schema-migrations/01-VALIDATION.md § Per-Task Verification Map
    INFRA-02: all 14 tables exist; findings/deliverables empty
    TENANT-01: every tenant table has space_id NOT NULL FK -> organizations
    crit. 4 : artifact_embeddings.embedding is vector(1536); NO vector index
- docs/BACKEND-MAP.md (the 14-table list; 12 tenant-owned + 2 roots)
- 01-PATTERNS.md § tests/test_schema_shape.py assignment (relforcerowsecurity check is in
    test_rls_isolation.py; this file owns presence + FK + embedding-column shape)
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

# The Postgres schema all application tables live in.
SCHEMA = "nestor"

# The tenant-ROOT tables — NOT RLS-scoped, NO space_id (an org IS the space;
# membership maps users to spaces). D-01 / D-03 / D-07.
#
# Phase 5 adds `audit_log` (plan 02 / 0006 migration): a ROOT table (D-07) — it is
# nullable-`space_id` (NO FK) and NOT RLS-scoped, so it belongs here, NOT in
# TENANT_TABLES. Including it here makes `test_all_expected_tables_exist` cover it and
# (because it is ABSENT from TENANT_TABLES) the `space_id`-FK / RLS loop correctly skips it.
ROOT_TABLES = (
    "organizations",
    "organization_memberships",
    "audit_log",
)

# The 12 tenant-OWNED tables — every one carries `space_id NOT NULL` -> organizations(id).
# Single source of truth for the iterating FK test. D-03.
TENANT_TABLES = (
    "products",
    "intakes",
    "intake_answers",
    "intake_templates",
    "skill_runs",
    "decompositions",
    "research_questions",
    "research_artifacts",
    "findings",
    "deliverables",
    "artifact_embeddings",
    "search_index",
)

# All expected tables: 14 from Phase 1 (INFRA-02) + `audit_log` from Phase 5 (0006).
ALL_TABLES = ROOT_TABLES + TENANT_TABLES


# ---------------------------------------------------------------------------
# INFRA-02: all 14 tables exist; findings/deliverables exist AND are empty
# ---------------------------------------------------------------------------

def test_all_expected_tables_exist(engine):
    """All 14 `nestor` tables are present after `alembic upgrade head`."""
    from sqlalchemy import text

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": SCHEMA},
        ).all()
    present = {r[0] for r in rows}

    missing = sorted(t for t in ALL_TABLES if t not in present)
    assert not missing, f"missing {SCHEMA} tables: {missing} (present: {sorted(present)})"


def test_findings_and_deliverables_exist_and_empty(engine):
    """`findings` and `deliverables` ship as schema-only (Tribunal handoff, D-04).

    They must exist but contain zero rows — production comes up empty and the
    Tribunal track (out of scope) is the only writer.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        for tbl in ("findings", "deliverables"):
            count = conn.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{tbl}")
            ).scalar_one()
            assert count == 0, f"{SCHEMA}.{tbl} must be empty (D-04); found {count} rows"


# ---------------------------------------------------------------------------
# TENANT-01: every tenant table has space_id NOT NULL FK -> organizations(id)
# ---------------------------------------------------------------------------

def test_space_id_not_null_fk(engine):
    """Each of the 12 tenant-owned tables has a `space_id` column that is
    NOT NULL and carries a FK to `organizations(id)`.

    Iterates the single TENANT_TABLES source so adding a table updates exactly
    one place. The 2 root tables are deliberately NOT checked (they have no
    space_id — they ARE the space / the user->space map).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        for tbl in TENANT_TABLES:
            # 1. space_id column exists and is NOT NULL.
            col = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :tbl "
                    "AND column_name = 'space_id'"
                ),
                {"schema": SCHEMA, "tbl": tbl},
            ).first()
            assert col is not None, f"{SCHEMA}.{tbl}: missing space_id column (TENANT-01)"
            assert col[0] == "NO", (
                f"{SCHEMA}.{tbl}.space_id must be NOT NULL (got is_nullable={col[0]!r})"
            )

            # 2. space_id has a FK to organizations(id).
            fk = conn.execute(
                text(
                    """
                    SELECT ccu.table_name AS ref_table, ccu.column_name AS ref_col
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                      ON tc.constraint_name = kcu.constraint_name
                     AND tc.table_schema = kcu.table_schema
                    JOIN information_schema.constraint_column_usage ccu
                      ON tc.constraint_name = ccu.constraint_name
                     AND tc.table_schema = ccu.table_schema
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                      AND tc.table_schema = :schema
                      AND tc.table_name = :tbl
                      AND kcu.column_name = 'space_id'
                    """
                ),
                {"schema": SCHEMA, "tbl": tbl},
            ).first()
            assert fk is not None, (
                f"{SCHEMA}.{tbl}.space_id has no FOREIGN KEY (TENANT-01)"
            )
            assert fk[0] == "organizations" and fk[1] == "id", (
                f"{SCHEMA}.{tbl}.space_id FK must reference organizations(id); "
                f"got {fk[0]}({fk[1]})"
            )


# ---------------------------------------------------------------------------
# Criterion 4: artifact_embeddings.embedding is vector(1536); NO vector index
# ---------------------------------------------------------------------------

def test_embedding_column_no_index(engine):
    """`artifact_embeddings.embedding` is `vector(1536)` and has NO index.

    HNSW/IVFFlat indexes are deferred (D-08, criterion 4): IVFFlat needs
    training rows the empty table lacks, and HNSW is a policy deferral. So the
    embedding column must exist with the right type and dimension, but NO
    vector index may exist on it this phase.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        # 1. Column type is vector(1536). format_type renders the typmod-bearing
        #    dimension, e.g. 'vector(1536)'.
        type_str = conn.execute(
            text(
                """
                SELECT format_type(a.atttypid, a.atttypmod)
                FROM pg_attribute a
                JOIN pg_class c       ON c.oid = a.attrelid
                JOIN pg_namespace n   ON n.oid = c.relnamespace
                WHERE n.nspname = :schema
                  AND c.relname = 'artifact_embeddings'
                  AND a.attname = 'embedding'
                  AND a.attnum > 0
                  AND NOT a.attisdropped
                """
            ),
            {"schema": SCHEMA},
        ).scalar_one()
        assert type_str == "vector(1536)", (
            f"artifact_embeddings.embedding must be vector(1536); got {type_str!r}"
        )

        # 2. NO index touches the embedding column (no hnsw/ivfflat/btree on it).
        idx_rows = conn.execute(
            text(
                """
                SELECT i.relname AS index_name, am.amname AS access_method
                FROM pg_index x
                JOIN pg_class t       ON t.oid = x.indrelid
                JOIN pg_class i       ON i.oid = x.indexrelid
                JOIN pg_namespace n   ON n.oid = t.relnamespace
                JOIN pg_am am         ON am.oid = i.relam
                JOIN pg_attribute a   ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                WHERE n.nspname = :schema
                  AND t.relname = 'artifact_embeddings'
                  AND a.attname = 'embedding'
                """
            ),
            {"schema": SCHEMA},
        ).all()
        assert idx_rows == [], (
            "NO index may exist on artifact_embeddings.embedding this phase "
            f"(criterion 4); found: {[(r[0], r[1]) for r in idx_rows]}"
        )


# ---------------------------------------------------------------------------
# Phase 5 (USER-03 / AUTH-04 / D-05/D-10): status columns exist NOT NULL on the
# two root tables; audit_log stays a ROOT (non-RLS) table.
#
# The 0006 migration adds `status` (String NOT NULL, server_default 'active') to
# `organization_memberships` (deactivate/reactivate, D-05) and `organizations`
# (soft-deactivate a space, D-10). Both MUST be NOT NULL so existing rows carry a
# non-null status after the migration's server_default backfill.
# ---------------------------------------------------------------------------

# The root tables that gain a Phase-5 `status` column (D-05 / D-10).
STATUS_TABLES = (
    "organization_memberships",
    "organizations",
)


def test_status_columns_exist_not_null(engine):
    """`organization_memberships.status` and `organizations.status` exist and are NOT NULL.

    Reuses the `information_schema.columns` is_nullable query shape (the same probe
    `test_space_id_not_null_fk` uses). A nullable status would let an existing row carry a
    NULL after the 0006 backfill — breaking the {active, deactivated} app-layer contract.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        for tbl in STATUS_TABLES:
            col = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :tbl "
                    "AND column_name = 'status'"
                ),
                {"schema": SCHEMA, "tbl": tbl},
            ).first()
            assert col is not None, f"{SCHEMA}.{tbl}: missing status column (Phase 5 / 0006)"
            assert col[0] == "NO", (
                f"{SCHEMA}.{tbl}.status must be NOT NULL (got is_nullable={col[0]!r}) — a "
                "nullable status breaks the active/deactivated contract (D-05/D-10)"
            )


def test_audit_log_is_root_not_tenant_scoped():
    """`audit_log` is a ROOT table (D-07): it is in ROOT_TABLES and ABSENT from
    TENANT_TABLES, so the `space_id`-FK / RLS loop (`test_space_id_not_null_fk`) skips it.

    This is a pure list-membership assertion — no DB needed, so it runs on the dev box and
    statically pins the "do NOT RLS-scope audit_log" decision (05-RESEARCH Anti-Patterns).
    """
    assert "audit_log" in ROOT_TABLES, "audit_log must be a root table (D-07)"
    assert "audit_log" not in TENANT_TABLES, (
        "audit_log must NOT be in TENANT_TABLES — it is a ROOT table with a nullable, "
        "FK-less space_id and is NOT RLS-scoped (D-07 / 05-RESEARCH Anti-Patterns)"
    )
