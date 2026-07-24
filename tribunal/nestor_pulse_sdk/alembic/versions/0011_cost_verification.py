"""0011 cost + verification foundation (Phase 15 ENGINE-09).

Additive-only migration that lays the data contract every other Phase-15
surface reads from. THREE additive columns + ONE new RLS read-model table.
Nothing here enters the frozen audit hash-chain payload
(nestor_pulse_sdk/audit/hash_chain.py:_payload_for_row -- 11 fields), and
nothing is written into the intake `nestor` Alembic line
(backend/app/db/alembic/versions/). This lives in the TRIBUNAL Alembic line
only -- a SEPARATE alembic_version from intake (Pitfall 2).

1. audit_log.cache_creation_tokens (INTEGER, nullable):
   mirrors the existing audit_log.cached_tokens column so the C1 cost fix
   (Plan 15-02) can price Anthropic cache-CREATION tokens at 1.25x. Nullable
   because legacy rows never captured it. OUTSIDE the hashed payload -- adding
   it does NOT break any existing chain (T-15-01).

2. run.cost_pending (BOOLEAN, not-null, default false):
   flags a run whose per-call costs are not yet fully reconciled (some models
   were unknown at write time -- Pitfall 5). The cost recompute job clears it.

3. run.verification_summary (JSONB, nullable):
   the run-level verification FUNNEL store -- distilled / selected / sessions /
   verdicts / skipped / failed counts. Populated by the verification report
   builder (Plan 15-03); nullable now.

4. verification_verdict (NEW TABLE, FORCE RLS):
   the queryable per-claim verdict read-model. One row per emitted verdict from
   the group-skeptic. Carries verdict / confidence / evidence_refs /
   reconciliation so the verification report (Plan 15-03) and the operator
   drill-down render REAL verdict data instead of re-parsing raw blobs.
   ENABLE + FORCE ROW LEVEL SECURITY + tenant_id policy from day one
   (T-15-02) -- copied verbatim from 0003_citation_schema.py's claim table.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-24
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---------------------------------------------------- additive columns
    # (1) Anthropic cache-CREATION tokens (1.25x) -- mirrors cached_tokens.
    #     nullable=True: legacy rows never captured it. OUTSIDE the frozen
    #     hash-chain payload -- no chain break (T-15-01).
    op.add_column(
        "audit_log",
        sa.Column("cache_creation_tokens", sa.Integer(), nullable=True),
    )

    # (2) run.cost_pending -- costs not yet fully reconciled (Pitfall 5).
    op.add_column(
        "run",
        sa.Column(
            "cost_pending",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )

    # (3) run.verification_summary -- the run-level verification funnel store
    #     (distilled/selected/sessions/verdicts/skipped/failed). Populated by
    #     Plan 15-03; nullable now.
    op.add_column(
        "run",
        sa.Column("verification_summary", postgresql.JSONB(), nullable=True),
    )

    # ------------------------------------------- verification_verdict table
    # Per-claim verdict read-model. FK shape + RLS policy copied verbatim from
    # 0003_citation_schema.py's claim table.
    op.create_table(
        "verification_verdict",
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
        # nullable: the group's claim is not always resolvable back to a
        # claim.id at extraction time (the recorded run predates claim linkage).
        sa.Column(
            "claim_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("verdict", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Text(), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=True),
        # carries disputed / relation / note / canonical (group reconciliation).
        sa.Column("reconciliation", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_verification_verdict_tenant_run",
        "verification_verdict",
        ["tenant_id", "run_id"],
    )
    op.execute("ALTER TABLE verification_verdict ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE verification_verdict FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY verification_verdict_tenant_isolation ON verification_verdict
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )


def downgrade() -> None:
    # Inverse order: drop policy + table first, then the additive columns.
    op.execute(
        "DROP POLICY IF EXISTS verification_verdict_tenant_isolation "
        "ON verification_verdict"
    )
    op.execute(
        "ALTER TABLE verification_verdict NO FORCE ROW LEVEL SECURITY"
    )
    op.execute(
        "ALTER TABLE verification_verdict DISABLE ROW LEVEL SECURITY"
    )
    op.drop_index(
        "idx_verification_verdict_tenant_run",
        table_name="verification_verdict",
    )
    op.drop_table("verification_verdict")

    op.drop_column("run", "verification_summary")
    op.drop_column("run", "cost_pending")
    op.drop_column("audit_log", "cache_creation_tokens")
