"""0012 research_run_chain_bundle — Phase-17 chain-guard / raw-output columns.

Phase 17 foundation (RUN-03). Adds THREE nullable columns to the existing
``nestor.research_runs`` mirror table (0011) so the Phase-16 poll driver's
completion path (Plan 02) can record the audit-chain verdict and the materialized
raw-output bundle reference, and the SSE dict + download/re-verify routes (Plan 03)
can read them:

  - ``chain_status``  TEXT NULL  — ``"verified"`` | ``"broken"`` (D-06); NULL until
    the completion path runs ``verify_chain``. A ``"broken"`` value locks the
    raw-output download until a re-verify lifts it (D-08).
  - ``chain_broken_at`` INTEGER NULL — the divergent row index ``verify_chain``
    returns on a broken chain; NULL when verified or unrun.
  - ``bundle_key`` TEXT NULL — the GCS object key of the materialized raw-output
    zip (D-04/D-05); NULL until the completion path builds + uploads it.

All three are NULLABLE with NO ``server_default`` — pre-existing live rows (smoke
intake e08620c5 carries 3) must not break, and the completion path (not the DB) is
the sole writer of these values.

This migration is a PURE add-column: it touches NO RLS policy, grant, or index.
The new columns inherit ``research_runs``' existing FORCE-RLS row policy and the
0011 grants (a column added to an already-granted, already-policied table needs no
re-grant / re-policy). This keeps the migration minimal and the isolation contract
unchanged (the row-level ``space_isolation`` + ``superadmin_all`` policies from 0011
apply to every column of the row).

Live ``alembic upgrade`` is DEFERRED on the dev box (author-by-construction, D-10);
the bar is a clean ``alembic check`` (ORM metadata == this migration) + the
migration source/integration tests (``test_research_runs_migration.py``) in Cloud
Build.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-22
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "research_runs"


def upgrade() -> None:
    # Three NULLABLE columns, NO server_default — the completion path (Plan 02)
    # is the sole writer; pre-existing rows stay NULL and unaffected.
    op.add_column(
        _TABLE,
        sa.Column("chain_status", sa.String(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("chain_broken_at", sa.Integer(), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column("bundle_key", sa.String(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    # Reverse order of the adds.
    op.drop_column(_TABLE, "bundle_key", schema=SCHEMA)
    op.drop_column(_TABLE, "chain_broken_at", schema=SCHEMA)
    op.drop_column(_TABLE, "chain_status", schema=SCHEMA)
