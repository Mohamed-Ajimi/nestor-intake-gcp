"""0004 A/B comparison support -- tribunal engine arm + comparison_id.

Two additive changes that let the UI run the Phase 1 A/B (Plan 01-12) as a
single fan-out across engines:

1. `run.engine` gains a third allowed value, 'tribunal', so the adaptive
   Tribunal engine is selectable per-run instead of only via the process-level
   NESTOR_SDK_ORCHESTRATOR env var. The worker dispatches straight off
   `engine` (runs/worker.py CLAIM_SQL RETURNING ... engine), so no worker
   change is needed -- dispatch_runner() maps 'tribunal' -> TribunalPipeline.

2. `run.comparison_id` (nullable UUID) groups the N child runs of one A/B
   fan-out. NULL for ordinary single-engine runs. Indexed leading with
   tenant_id (Pitfall 2) for the GET /api/runs/compare/{id} lookup.

Both changes are backward-compatible: existing 'adk'/'sdk' runs are untouched
and comparison_id defaults NULL.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-05
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Relax the engine CHECK constraint to allow the 'tribunal' arm.
    op.drop_constraint("ck_run_engine", "run", type_="check")
    op.create_check_constraint(
        "ck_run_engine",
        "run",
        "engine IN ('adk','sdk','tribunal')",
    )

    # 2. comparison_id: groups the child runs of one A/B fan-out (NULL otherwise).
    op.add_column(
        "run",
        sa.Column("comparison_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Index leads with tenant_id (Pitfall 2) -- compare lookup is tenant-scoped.
    op.create_index(
        "idx_run_tenant_comparison",
        "run",
        ["tenant_id", "comparison_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_run_tenant_comparison", table_name="run")
    op.drop_column("run", "comparison_id")

    # Restore the original two-value engine constraint. Any 'tribunal' rows must
    # be migrated/removed first or this will fail -- intentional (D-02 invariant).
    op.drop_constraint("ck_run_engine", "run", type_="check")
    op.create_check_constraint(
        "ck_run_engine",
        "run",
        "engine IN ('adk','sdk')",
    )
