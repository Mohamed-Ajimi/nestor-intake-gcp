"""0005 clarification loop -- needs_input status + clarifying_questions.

When a brief is too vague, an engine asks 2-3 clarifying questions instead of
researching. Two additive changes let the app surface that and resume:

1. `run.status` gains a sixth allowed value, 'needs_input': the run paused to
   ask the user something. The worker sets this (instead of 'completed') when a
   runner returns {needs_clarification: True}. The user answers, and the answer
   endpoint folds the replies into the brief and re-queues a NEW run.

2. `run.clarifying_questions` (nullable JSONB) holds the list of questions the
   engine asked. NULL for every normal run.

Both changes are backward-compatible: existing rows keep their status and get a
NULL clarifying_questions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-08
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Relax the status CHECK constraint to allow 'needs_input'.
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "status IN ('queued','running','completed','failed','cancelled','needs_input')",
    )

    # 2. clarifying_questions: the questions an engine asked when the brief was
    #    vague (NULL for normal runs).
    op.add_column(
        "run",
        sa.Column("clarifying_questions", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("run", "clarifying_questions")

    # Restore the original five-value status constraint. Any 'needs_input' rows
    # must be resolved first or this will fail (intentional).
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "status IN ('queued','running','completed','failed','cancelled')",
    )
