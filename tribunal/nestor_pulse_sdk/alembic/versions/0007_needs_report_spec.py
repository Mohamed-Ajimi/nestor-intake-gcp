"""0007 interactive report shaping -- needs_report_spec status.

A Tribunal run can pause AFTER scrubbing (before final synthesis) to let the
user shape the report: an LLM "report planner" reads the scrubbed research and
proposes focus areas / length / table format; the user picks; only then does
synthesis run. The scrubbed research is cached (Output 'synthesis_cache') so the
resume — and any later "Rewrite report" — re-runs ONLY synthesis, never the
expensive deep research.

`run.status` gains a seventh allowed value, 'needs_report_spec': the run paused
to ask the user how to shape the report. The worker sets this when the Tribunal
runner returns {needs_report_spec: True}. The user submits a spec via
POST /runs/{id}/report-spec, which flips the run back to 'queued'; the worker
re-claims it and the pipeline resumes from the cached bundle.

Backward-compatible: existing rows keep their status.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-14
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "status IN ('queued','running','completed','failed','cancelled',"
        "'needs_input','needs_report_spec')",
    )


def downgrade() -> None:
    # Any 'needs_report_spec' rows must be resolved first or this will fail.
    op.drop_constraint("ck_run_status", "run", type_="check")
    op.create_check_constraint(
        "ck_run_status",
        "run",
        "status IN ('queued','running','completed','failed','cancelled','needs_input')",
    )
