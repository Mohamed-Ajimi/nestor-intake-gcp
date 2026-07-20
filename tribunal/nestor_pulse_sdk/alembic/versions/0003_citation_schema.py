"""0003 citation schema -- source, claim, claim_source (D-07).

Verbatim port of 01-RESEARCH.md § Pattern 4 (lines 524-575). Three tables
with snapshot_text captured at fetch time so dead URLs don't break old
reports' citation recall. Phase 2 PHASE2-05 will fill claim_source.confidence;
Phase 1 leaves it NULL.

Partial UNIQUE index `(tenant_id, content_hash) WHERE content_hash IS
NOT NULL` provides per-tenant dedupe (RESEARCH line 539).

RLS for these three tables also lives in this migration -- they belong
with the schema they protect, rather than backfilled into 0002.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------ source
    op.create_table(
        "source",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("provider", sa.String(), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("snapshot_text", sa.Text(), nullable=True),
        sa.Column("snapshot_gcs_uri", sa.String(), nullable=True),
        sa.Column("content_hash", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_source_tenant_url", "source", ["tenant_id", "url"])
    # Partial UNIQUE -- RESEARCH line 539 verbatim.
    op.create_index(
        "idx_source_tenant_content_hash",
        "source",
        ["tenant_id", "content_hash"],
        unique=True,
        postgresql_where=sa.text("content_hash IS NOT NULL"),
    )
    op.execute("ALTER TABLE source ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE source FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY source_tenant_isolation ON source
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # ------------------------------------------------------------ claim
    op.create_table(
        "claim",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("run.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("facet", sa.String(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("idx_claim_tenant_run", "claim", ["tenant_id", "run_id"])
    op.execute("ALTER TABLE claim ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY claim_tenant_isolation ON claim
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )

    # ------------------------------------------------------ claim_source
    op.create_table(
        "claim_source",
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("claim.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("source.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("org.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snippet", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
    )
    op.create_index("idx_claim_source_tenant", "claim_source", ["tenant_id"])
    op.execute("ALTER TABLE claim_source ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim_source FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY claim_source_tenant_isolation ON claim_source
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )


def downgrade() -> None:
    # claim_source first -- it FKs to both claim and source.
    op.execute(
        "DROP POLICY IF EXISTS claim_source_tenant_isolation ON claim_source"
    )
    op.execute("ALTER TABLE claim_source NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim_source DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_claim_source_tenant", table_name="claim_source")
    op.drop_table("claim_source")

    op.execute("DROP POLICY IF EXISTS claim_tenant_isolation ON claim")
    op.execute("ALTER TABLE claim NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE claim DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_claim_tenant_run", table_name="claim")
    op.drop_table("claim")

    op.execute("DROP POLICY IF EXISTS source_tenant_isolation ON source")
    op.execute("ALTER TABLE source NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE source DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_source_tenant_content_hash", table_name="source")
    op.drop_index("idx_source_tenant_url", table_name="source")
    op.drop_table("source")
