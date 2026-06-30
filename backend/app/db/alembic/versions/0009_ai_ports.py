"""0009 AI function-port schema foundation — 3 tables + parity columns + RLS.

Phase 7 substrate. Every ported AI handler (transcribe-audio, extract-insights,
apply-intake-skill, generate-context-pack, embed/search) reads/writes through the
schema this migration lands. It closes the three documented schema gaps up front
(07-RESEARCH Pitfalls 1/2/3) so the per-function plans implement against final
tables.

Adds, under schema ``nestor``:

  - 3 tenant-OWNED tables — ``intake_sources``, ``transcripts``,
    ``extracted_insights`` — each with ``space_id UUID NOT NULL REFERENCES
    organizations(id) ON DELETE CASCADE`` + ``ix_<t>_space_id`` and the
    ``space_id``-leading composite ``idx_<t>_space_intake`` (TENANT-01). Index
    names match app/db/models/{sources,transcripts,insights}.py 1:1 so
    ``alembic check`` stays clean. ``transcripts.source_id`` FKs
    ``intake_sources`` ON DELETE CASCADE.
  - 11 NULLABLE parity columns: 7 on ``skill_runs`` (input_tokens, output_tokens,
    cost_estimate_usd, output, prompt_system, prompt_user, skill_version — Pitfall
    2 / Open Q1 cost observability) and 4 on ``intake_answers`` (respondent_id,
    confidence, source_chunk_id, extracted_by — Pitfall 3 / A6 LLM provenance).
    All nullable so the save-as-you-go upsert is byte-for-byte unaffected and the
    existing ``uq_intake_answers_intake_field`` unique constraint is untouched.

RLS (the inherited-Supabase permissive-policy bug must NOT recur): for EACH new
table this migration emits ENABLE + FORCE ROW LEVEL SECURITY, a
``<t>_space_isolation`` policy with the MANDATORY ``NULLIF(current_setting(
'app.current_space_id', true), '')::uuid`` form (empty-string reversion safety,
0002), and a ``<t>_superadmin_all`` bypass policy keyed on the real
``current_user = 'app_superadmin'`` predicate (0003 — REQUIRED or a superadmin,
which carries no GUC, cannot touch the new tables). Grants: explicit per-table
GRANT to ``app_superadmin`` (belt-and-braces over 0003's ALTER DEFAULT
PRIVILEGES) plus the env-guarded runtime-SA DO-block (0005/0006 idiom).

Scope ceiling (Pitfall 1 / Open Q2): this migration deliberately does NOT widen
the ``intake_status`` enum with ``transcribed`` — the audio path is E2E-deferred
and out-of-flow; the ported transcribe handler records progress on
``intake_sources`` / ``transcripts``, never an intake-status bump. The flow
ceiling stays at ``decomposed``.

Live ``alembic upgrade`` is DEFERRED (author-by-construction, D-10); the bar is
``alembic check`` clean (ORM metadata == this migration, index names included).

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-30
"""

from __future__ import annotations

import logging
import os
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# The three NEW tenant-owned tables this migration creates (RLS + grants loop).
_NEW_TABLES = ("intake_sources", "transcripts", "extracted_insights")

# Env var carrying the grantee role name = the runtime SA email WITHOUT the
# ".gserviceaccount.com" suffix (mirrors 0005/0006). UNSET on the testcontainer,
# where the runtime-SA grant must no-op cleanly.
RUNTIME_DB_USER_ENV = "RUNTIME_DB_USER"

logger = logging.getLogger("alembic.runtime.migration")


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _id_col():
    """id UUID PK, server_default gen_random_uuid() (pgcrypto, installed in 0001).

    Mirrors the ORM models' ``server_default=text("gen_random_uuid()")`` so ORM and
    migration agree exactly (belt-and-braces; the ORM also supplies uuid4 client-side).
    """
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


def _created_at():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _runtime_db_user() -> str | None:
    """The grantee role name from the environment, or None when unset/blank."""
    value = os.environ.get(RUNTIME_DB_USER_ENV, "").strip()
    return value or None


def _grant_new_tables_to_runtime_sa() -> None:
    """Env-guarded GRANT of the 3 new tables to the runtime SA (0005/0006 idiom)."""
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0009: %s unset -- skipping runtime-SA GRANT on the new AI tables "
            "(no IAM DB user to grant in this environment).",
            RUNTIME_DB_USER_ENV,
        )
        return

    role_literal = role.replace("'", "''")
    for table in _NEW_TABLES:
        op.execute(
            f"""
            DO $$
            DECLARE
                r text := '{role_literal}';
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO %I', r);
                ELSE
                    RAISE EXCEPTION '0009: RUNTIME_DB_USER role % does not exist -- the IAM DB user must exist before the migration Job GRANTs {table}. Refusing to silently skip.', r;
                END IF;
            END
            $$;
            """
        )


def _revoke_new_tables_from_runtime_sa() -> None:
    """Symmetric, role-existence-guarded REVOKE for downgrade (0005/0006 idiom)."""
    role = _runtime_db_user()
    if role is None:
        logger.info(
            "0009 downgrade: %s unset -- nothing to revoke on the new AI tables.",
            RUNTIME_DB_USER_ENV,
        )
        return

    role_literal = role.replace("'", "''")
    for table in _NEW_TABLES:
        op.execute(
            f"""
            DO $$
            DECLARE
                r text := '{role_literal}';
            BEGIN
                IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
                    EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} FROM %I', r);
                END IF;
            END
            $$;
            """
        )


def _enable_rls(table: str) -> None:
    """ENABLE + FORCE RLS + space_isolation (NULLIF form) + superadmin_all bypass.

    Mirrors 0002 (the mandatory NULLIF empty-string-reversion form) + 0003 (the real
    ``current_user = 'app_superadmin'`` bypass predicate, NOT the banned constant-true).
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
    # New tenant-OWNED tables (FK order: intake_sources before transcripts).
    # =====================================================================

    # ------------------------------------------------------ intake_sources
    op.create_table(
        "intake_sources",
        _id_col(),
        _space_id_col(),
        _intake_id_col(),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("storage_bucket", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=True),
        sa.Column("file_name", sa.String(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intake_sources_space_id", "intake_sources", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_intake_sources_space_intake",
        "intake_sources",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # ---------------------------------------------------------- transcripts
    op.create_table(
        "transcripts",
        _id_col(),
        _space_id_col(),
        _intake_id_col(),
        sa.Column(
            "source_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intake_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("language", sa.String(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("speaker", sa.String(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_transcripts_space_id", "transcripts", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_transcripts_space_intake",
        "transcripts",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # --------------------------------------------------- extracted_insights
    op.create_table(
        "extracted_insights",
        _id_col(),
        _space_id_col(),
        _intake_id_col(),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("supporting_text", sa.Text(), nullable=True),
        sa.Column("source_chunk_id", _uuid(), nullable=True),
        sa.Column("source_answer_id", _uuid(), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_extracted_insights_space_id",
        "extracted_insights",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_extracted_insights_space_intake",
        "extracted_insights",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # =====================================================================
    # Parity columns (11 total: 7 skill_runs + 4 intake_answers), all nullable.
    # =====================================================================
    op.add_column(
        "skill_runs", sa.Column("input_tokens", sa.Integer(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "skill_runs", sa.Column("output_tokens", sa.Integer(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "skill_runs",
        sa.Column("cost_estimate_usd", sa.Numeric(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "skill_runs", sa.Column("output", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "skill_runs", sa.Column("prompt_system", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "skill_runs", sa.Column("prompt_user", sa.Text(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "skill_runs", sa.Column("skill_version", sa.String(), nullable=True), schema=SCHEMA
    )

    op.add_column(
        "intake_answers", sa.Column("respondent_id", _uuid(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "intake_answers", sa.Column("confidence", sa.Float(), nullable=True), schema=SCHEMA
    )
    op.add_column(
        "intake_answers",
        sa.Column("source_chunk_id", _uuid(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        "intake_answers", sa.Column("extracted_by", sa.String(), nullable=True), schema=SCHEMA
    )

    # =====================================================================
    # RLS: ENABLE+FORCE+space_isolation+superadmin_all for each new table.
    # =====================================================================
    for table in _NEW_TABLES:
        _enable_rls(table)

    # =====================================================================
    # Grants (belt-and-braces over 0003 ALTER DEFAULT PRIVILEGES): explicit
    # per-table GRANT to app_superadmin + the env-guarded runtime-SA DO-block.
    # =====================================================================
    for table in _NEW_TABLES:
        op.execute(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} TO app_superadmin"
        )
    _grant_new_tables_to_runtime_sa()


def downgrade() -> None:
    # Reverse order: revoke grants -> drop policies/RLS -> drop parity columns
    # -> drop indexes + tables (transcripts before intake_sources for the FK).
    _revoke_new_tables_from_runtime_sa()
    for table in _NEW_TABLES:
        op.execute(
            f"REVOKE SELECT, INSERT, UPDATE, DELETE ON {SCHEMA}.{table} FROM app_superadmin"
        )

    for table in _NEW_TABLES:
        op.execute(f"DROP POLICY IF EXISTS {table}_superadmin_all ON {SCHEMA}.{table}")
        op.execute(f"DROP POLICY IF EXISTS {table}_space_isolation ON {SCHEMA}.{table}")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {SCHEMA}.{table} DISABLE ROW LEVEL SECURITY")

    # ---- parity columns (reverse of the add order)
    op.drop_column("intake_answers", "extracted_by", schema=SCHEMA)
    op.drop_column("intake_answers", "source_chunk_id", schema=SCHEMA)
    op.drop_column("intake_answers", "confidence", schema=SCHEMA)
    op.drop_column("intake_answers", "respondent_id", schema=SCHEMA)

    op.drop_column("skill_runs", "skill_version", schema=SCHEMA)
    op.drop_column("skill_runs", "prompt_user", schema=SCHEMA)
    op.drop_column("skill_runs", "prompt_system", schema=SCHEMA)
    op.drop_column("skill_runs", "output", schema=SCHEMA)
    op.drop_column("skill_runs", "cost_estimate_usd", schema=SCHEMA)
    op.drop_column("skill_runs", "output_tokens", schema=SCHEMA)
    op.drop_column("skill_runs", "input_tokens", schema=SCHEMA)

    # ---- indexes + tables (transcripts first — it FKs intake_sources)
    op.drop_index(
        "idx_extracted_insights_space_intake", "extracted_insights", schema=SCHEMA
    )
    op.drop_index("ix_extracted_insights_space_id", "extracted_insights", schema=SCHEMA)
    op.drop_table("extracted_insights", schema=SCHEMA)

    op.drop_index("idx_transcripts_space_intake", "transcripts", schema=SCHEMA)
    op.drop_index("ix_transcripts_space_id", "transcripts", schema=SCHEMA)
    op.drop_table("transcripts", schema=SCHEMA)

    op.drop_index("idx_intake_sources_space_intake", "intake_sources", schema=SCHEMA)
    op.drop_index("ix_intake_sources_space_id", "intake_sources", schema=SCHEMA)
    op.drop_table("intake_sources", schema=SCHEMA)
