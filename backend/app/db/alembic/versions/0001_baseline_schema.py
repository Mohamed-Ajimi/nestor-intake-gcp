"""0001 baseline schema — the full nestor schema on an empty database.

Builds, on an empty pgvector/pgvector:pg16 database:
  - CREATE SCHEMA nestor (all application tables live here, D-01/D-03)
  - CREATE EXTENSION pgcrypto + vector (D-08)
  - 3 enum types in nestor: intake_status (full 8-value set, D-04 fidelity),
    question_type, finding_kind
  - 2 tenant-ROOT tables (NO space_id): organizations, organization_memberships
  - 12 tenant-OWNED tables, each with
    space_id UUID NOT NULL REFERENCES nestor.organizations(id) ON DELETE CASCADE
    + ix_<t>_space_id (from index=True on the column) + a space_id-leading
    composite index (TENANT-01)
  - artifact_embeddings.embedding = vector(1536) with NO index (criterion 4):
    IVFFlat is forbidden (needs training rows), HNSW is deferred by policy.
    The HNSW intent is recorded in a comment for the future index migration.

findings / deliverables are created schema-only and come up empty (D-04 —
Tribunal handoff contract). Out-of-scope objects (Tally mapping tables,
intake_respondents, jotform, the sales schema) are never created (D-05).

This migration mirrors app/db/models/*.py exactly so `alembic check` stays
clean after any future autogenerate run.

Revision ID: 0001
Revises: None
Create Date: 2026-06-19
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql


revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"

# Enum value sets (must match app/db/models/*.py).
INTAKE_STATUS_VALUES = (
    "draft",
    "submitted",
    "reviewed",
    "validated_by_client",
    "decomposed",
    "in_research",
    "delivered",
    "archived",
)
QUESTION_TYPE_VALUES = ("descriptive", "comparative", "causal", "predictive")
FINDING_KIND_VALUES = ("fact", "insight", "risk", "opportunity")

# Enum column types — create_type=False because upgrade() creates the types
# explicitly first (so create_table only references them).
intake_status = postgresql.ENUM(
    *INTAKE_STATUS_VALUES, name="intake_status", schema=SCHEMA, create_type=False
)
question_type = postgresql.ENUM(
    *QUESTION_TYPE_VALUES, name="question_type", schema=SCHEMA, create_type=False
)
finding_kind = postgresql.ENUM(
    *FINDING_KIND_VALUES, name="finding_kind", schema=SCHEMA, create_type=False
)


def _uuid():
    return postgresql.UUID(as_uuid=True)


def _space_id_col():
    """space_id UUID NOT NULL REFERENCES nestor.organizations(id) ON DELETE CASCADE."""
    return sa.Column(
        "space_id",
        _uuid(),
        sa.ForeignKey(
            f"{SCHEMA}.organizations.id", ondelete="CASCADE"
        ),
        nullable=False,
    )


def _created_at():
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def _updated_at():
    return sa.Column(
        "updated_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    # ---------------------------------------------------------- schema + ext
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    # gen_random_uuid() availability (belt-and-braces; ORM uses uuid4 client-side).
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    # D-08: the vector type. Installed into public (default) — `vector` resolves
    # on the search_path for the nestor.artifact_embeddings.embedding column.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # -------------------------------------------------------------- enum types
    bind = op.get_bind()
    intake_status.create(bind, checkfirst=True)
    question_type.create(bind, checkfirst=True)
    finding_kind.create(bind, checkfirst=True)

    # =========================================================================
    # Tenant ROOT tables (NO space_id — they ARE the space / the user->space map)
    # =========================================================================

    # --------------------------------------------------------- organizations
    op.create_table(
        "organizations",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=True, unique=True),
        _created_at(),
        schema=SCHEMA,
    )

    # ---------------------------------------------- organization_memberships
    op.create_table(
        "organization_memberships",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column(
            "organization_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", _uuid(), nullable=True),
        sa.Column("provider_user_id", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="user"),
        _created_at(),
        sa.UniqueConstraint(
            "organization_id", "user_id", name="uq_membership_org_user"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_organization_memberships_organization_id",
        "organization_memberships",
        ["organization_id"],
        schema=SCHEMA,
    )

    # =========================================================================
    # Tenant-OWNED tables (space_id NOT NULL FK -> organizations.id), FK order
    # =========================================================================

    # ------------------------------------------------------------- products
    op.create_table(
        "products",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index("ix_products_space_id", "products", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_products_space_name", "products", ["space_id", "name"], schema=SCHEMA
    )

    # ------------------------------------------------------ intake_templates
    op.create_table(
        "intake_templates",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("schema", postgresql.JSONB(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intake_templates_space_id",
        "intake_templates",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_intake_templates_space_name",
        "intake_templates",
        ["space_id", "name"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------- intakes
    op.create_table(
        "intakes",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "template_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intake_templates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("client_name", sa.String(), nullable=True),
        sa.Column("status", intake_status, nullable=False, server_default="draft"),
        sa.Column(
            "validation_link_sent_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "results_link_sent_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("context_pack_artifact_id", _uuid(), nullable=True),
        sa.Column("final_report_artifact_id", _uuid(), nullable=True),
        _created_at(),
        _updated_at(),
        schema=SCHEMA,
    )
    op.create_index("ix_intakes_space_id", "intakes", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_intakes_space_status", "intakes", ["space_id", "status"], schema=SCHEMA
    )
    op.create_index(
        "idx_intakes_space_created",
        "intakes",
        ["space_id", "created_at"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------- intake_answers
    op.create_table(
        "intake_answers",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("field_key", sa.String(), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("value_json", postgresql.JSONB(), nullable=True),
        sa.Column("artifact_id", _uuid(), nullable=True),
        _created_at(),
        _updated_at(),
        sa.UniqueConstraint(
            "intake_id", "field_key", name="uq_intake_answers_intake_field"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_intake_answers_space_id",
        "intake_answers",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_intake_answers_space_intake",
        "intake_answers",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # ---------------------------------------------------------- skill_runs
    op.create_table(
        "skill_runs",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "skill",
            sa.String(),
            nullable=False,
            server_default="apply-intake-skill",
        ),
        sa.Column("status", sa.String(), nullable=False, server_default="queued"),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("output_parsed", postgresql.JSONB(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        _created_at(),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_skill_runs_space_id", "skill_runs", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_skill_runs_space_intake",
        "skill_runs",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_skill_runs_space_status",
        "skill_runs",
        ["space_id", "status"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------- decompositions
    op.create_table(
        "decompositions",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_decompositions_space_id",
        "decompositions",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_decompositions_space_intake",
        "decompositions",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # ---------------------------------------------------- research_questions
    op.create_table(
        "research_questions",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "decomposition_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.decompositions.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column(
            "question_type",
            question_type,
            nullable=False,
            server_default="descriptive",
        ),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="open"),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_research_questions_space_id",
        "research_questions",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_research_questions_space_intake",
        "research_questions",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_research_questions_space_status",
        "research_questions",
        ["space_id", "status"],
        schema=SCHEMA,
    )

    # ---------------------------------------------------- research_artifacts
    op.create_table(
        "research_artifacts",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_question_id",
            _uuid(),
            sa.ForeignKey(
                f"{SCHEMA}.research_questions.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("source", sa.String(), nullable=True),
        sa.Column("artifact_type", sa.String(), nullable=True),
        sa.Column("filename", sa.String(), nullable=True),
        sa.Column("storage_bucket", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column("mime_type", sa.String(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=True),
        sa.Column(
            "embed_status", sa.String(), nullable=False, server_default="pending"
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_research_artifacts_space_id",
        "research_artifacts",
        ["space_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_research_artifacts_space_intake",
        "research_artifacts",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )
    op.create_index(
        "idx_research_artifacts_space_embed",
        "research_artifacts",
        ["space_id", "embed_status"],
        schema=SCHEMA,
    )

    # --------------------------------------------------------------- findings
    # Schema-only / kept empty (D-04, Tribunal handoff). Columns mirror
    # BACKEND-MAP.md line 47 exactly, plus the space_id isolation key.
    op.create_table(
        "findings",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "research_question_id",
            _uuid(),
            sa.ForeignKey(
                f"{SCHEMA}.research_questions.id", ondelete="SET NULL"
            ),
            nullable=True,
        ),
        sa.Column("kind", finding_kind, nullable=False),
        sa.Column("label", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("supporting_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("sources", postgresql.JSONB(), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("reviewed_by", _uuid(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "archived", sa.Boolean(), nullable=False, server_default="false"
        ),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index("ix_findings_space_id", "findings", ["space_id"], schema=SCHEMA)
    op.create_index(
        "idx_findings_space_intake",
        "findings",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # ----------------------------------------------------------- deliverables
    # Schema-only / kept empty (D-04).
    op.create_table(
        "deliverables",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("storage_bucket", sa.String(), nullable=True),
        sa.Column("storage_path", sa.String(), nullable=True),
        sa.Column("client_view_token", sa.String(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_deliverables_space_id", "deliverables", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_deliverables_space_intake",
        "deliverables",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------- artifact_embeddings
    # embedding = vector(1536). NO index this phase (criterion 4):
    #   IVFFlat is FORBIDDEN (needs training rows the empty table lacks).
    #   An HNSW (vector_cosine_ops) index is DEFERRED by policy; build it in a
    #   later index migration once embeddings data exists. No vector index DDL
    #   is emitted here (the source carries no hnsw/ivfflat index statement).
    op.create_table(
        "artifact_embeddings",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "artifact_id",
            _uuid(),
            sa.ForeignKey(
                f"{SCHEMA}.research_artifacts.id", ondelete="CASCADE"
            ),
            nullable=True,
        ),
        sa.Column("embedding", Vector(1536), nullable=True),
        sa.Column("chunk_text", sa.Text(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_artifact_embeddings_space_id",
        "artifact_embeddings",
        ["space_id"],
        schema=SCHEMA,
    )
    # space_id-leading composite (a btree on scalar cols — NOT a vector index).
    op.create_index(
        "idx_artifact_embeddings_space_artifact",
        "artifact_embeddings",
        ["space_id", "artifact_id"],
        schema=SCHEMA,
    )

    # ------------------------------------------------------------ search_index
    op.create_table(
        "search_index",
        sa.Column("id", _uuid(), primary_key=True),
        _space_id_col(),
        sa.Column(
            "intake_id",
            _uuid(),
            sa.ForeignKey(f"{SCHEMA}.intakes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "artifact_id",
            _uuid(),
            sa.ForeignKey(
                f"{SCHEMA}.research_artifacts.id", ondelete="CASCADE"
            ),
            nullable=True,
        ),
        sa.Column("kind", sa.String(), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        _created_at(),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_search_index_space_id", "search_index", ["space_id"], schema=SCHEMA
    )
    op.create_index(
        "idx_search_index_space_intake",
        "search_index",
        ["space_id", "intake_id"],
        schema=SCHEMA,
    )


def downgrade() -> None:
    # Reverse FK-dependency order so dependents drop before their targets.
    bind = op.get_bind()

    op.drop_index(
        "idx_search_index_space_intake", table_name="search_index", schema=SCHEMA
    )
    op.drop_index(
        "ix_search_index_space_id", table_name="search_index", schema=SCHEMA
    )
    op.drop_table("search_index", schema=SCHEMA)

    op.drop_index(
        "idx_artifact_embeddings_space_artifact",
        table_name="artifact_embeddings",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_artifact_embeddings_space_id",
        table_name="artifact_embeddings",
        schema=SCHEMA,
    )
    op.drop_table("artifact_embeddings", schema=SCHEMA)

    op.drop_index(
        "idx_deliverables_space_intake", table_name="deliverables", schema=SCHEMA
    )
    op.drop_index(
        "ix_deliverables_space_id", table_name="deliverables", schema=SCHEMA
    )
    op.drop_table("deliverables", schema=SCHEMA)

    op.drop_index(
        "idx_findings_space_intake", table_name="findings", schema=SCHEMA
    )
    op.drop_index("ix_findings_space_id", table_name="findings", schema=SCHEMA)
    op.drop_table("findings", schema=SCHEMA)

    op.drop_index(
        "idx_research_artifacts_space_embed",
        table_name="research_artifacts",
        schema=SCHEMA,
    )
    op.drop_index(
        "idx_research_artifacts_space_intake",
        table_name="research_artifacts",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_research_artifacts_space_id",
        table_name="research_artifacts",
        schema=SCHEMA,
    )
    op.drop_table("research_artifacts", schema=SCHEMA)

    op.drop_index(
        "idx_research_questions_space_status",
        table_name="research_questions",
        schema=SCHEMA,
    )
    op.drop_index(
        "idx_research_questions_space_intake",
        table_name="research_questions",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_research_questions_space_id",
        table_name="research_questions",
        schema=SCHEMA,
    )
    op.drop_table("research_questions", schema=SCHEMA)

    op.drop_index(
        "idx_decompositions_space_intake",
        table_name="decompositions",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_decompositions_space_id",
        table_name="decompositions",
        schema=SCHEMA,
    )
    op.drop_table("decompositions", schema=SCHEMA)

    op.drop_index(
        "idx_skill_runs_space_status", table_name="skill_runs", schema=SCHEMA
    )
    op.drop_index(
        "idx_skill_runs_space_intake", table_name="skill_runs", schema=SCHEMA
    )
    op.drop_index(
        "ix_skill_runs_space_id", table_name="skill_runs", schema=SCHEMA
    )
    op.drop_table("skill_runs", schema=SCHEMA)

    op.drop_index(
        "idx_intake_answers_space_intake",
        table_name="intake_answers",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_intake_answers_space_id",
        table_name="intake_answers",
        schema=SCHEMA,
    )
    op.drop_table("intake_answers", schema=SCHEMA)

    op.drop_index(
        "idx_intakes_space_created", table_name="intakes", schema=SCHEMA
    )
    op.drop_index(
        "idx_intakes_space_status", table_name="intakes", schema=SCHEMA
    )
    op.drop_index("ix_intakes_space_id", table_name="intakes", schema=SCHEMA)
    op.drop_table("intakes", schema=SCHEMA)

    op.drop_index(
        "idx_intake_templates_space_name",
        table_name="intake_templates",
        schema=SCHEMA,
    )
    op.drop_index(
        "ix_intake_templates_space_id",
        table_name="intake_templates",
        schema=SCHEMA,
    )
    op.drop_table("intake_templates", schema=SCHEMA)

    op.drop_index(
        "idx_products_space_name", table_name="products", schema=SCHEMA
    )
    op.drop_index("ix_products_space_id", table_name="products", schema=SCHEMA)
    op.drop_table("products", schema=SCHEMA)

    op.drop_index(
        "ix_organization_memberships_organization_id",
        table_name="organization_memberships",
        schema=SCHEMA,
    )
    op.drop_table("organization_memberships", schema=SCHEMA)

    op.drop_table("organizations", schema=SCHEMA)

    # Drop enum types (after the tables that reference them).
    finding_kind.drop(bind, checkfirst=True)
    question_type.drop(bind, checkfirst=True)
    intake_status.drop(bind, checkfirst=True)

    # Leave the nestor schema and the pgcrypto/vector extensions installed
    # (idempotent + harmless; other revisions / the test DB may reuse them).
