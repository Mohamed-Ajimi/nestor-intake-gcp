"""0006 live stage progress -- current_stage + stage_detail on run.

So the UI can show WHICH pipeline stage each engine is in (and live sub-progress
within the heavy stages), the run row carries its own progress signal. Both
columns are additive and nullable:

1. `run.current_stage` (nullable TEXT): the key of the stage the engine is
   currently executing (e.g. 'deep_research', 'verify'), or 'done' when the
   pipeline finished. NULL for queued runs and for legacy rows. The ordered
   stage SCHEMA per engine lives in code (nestor_pulse_sdk/runs/stages.py), not
   the DB -- this column only stores the current position.

2. `run.stage_detail` (nullable JSONB): optional sub-progress for the current
   stage, shape {"items": [{"name": str, "status": "done|running|pending"}]}.
   Used by Tribunal for per-angle deep-research and per-batch skeptic progress.
   NULL when the current stage has no sub-progress.

Backward-compatible: existing rows get NULL/NULL and render as "stage unknown"
(the UI falls back to status-based display).

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-13
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("run", sa.Column("current_stage", sa.Text(), nullable=True))
    op.add_column("run", sa.Column("stage_detail", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("run", "stage_detail")
    op.drop_column("run", "current_stage")
