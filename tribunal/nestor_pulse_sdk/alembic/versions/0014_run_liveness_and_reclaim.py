"""0014 run liveness + bounded reclaim (Phase 15.2 gap closure, D-E).

Additive-only migration: TWO columns on the EXISTING `run` table. No table, no
index, no security DDL (see the comment block in `upgrade()` for why re-issuing
any of that would be regression risk, not a hardening step).

What the columns carry
----------------------
`heartbeat_at` (timestamptz NULL) -- the LIVENESS CLOCK. The worker that is
executing a run bumps it on a timer while `runner.run()` is awaited, so a live
process has a fresh heartbeat even during a silent 35-minute deep-research
long-poll, and a dead process stops writing within one interval. `worker.py`'s
CLAIM_SQL reads staleness as `COALESCE(heartbeat_at, started_at)`.

This column exists because `started_at` CANNOT carry liveness. `started_at` is
the CR-01 FENCING TOKEN: `runs/execute.py::_CONSUME_CLAIM_SQL` matches
`AND started_at = :token` to guarantee a claim dispatches at most once
(ENGINE-08, legally load-bearing for the audit chain). Bumping it on a timer
would make every heartbeat invalidate the run's own claim token. A separate
column is the only safe carrier -- and `runs/execute.py` is not edited.

`reclaim_count` (int NOT NULL DEFAULT 0) -- the number of CRASH RECOVERIES a
single run has been granted. The claim increments it only when it re-claims a
row that was already `running`; a fresh `queued` claim leaves it at 0. Past
`NESTOR_WORKER_MAX_RECLAIMS` the run is FAILED with a worded message rather than
started again. Defect D-E fired for real on 2026-07-27: killing a stuck worker
started a fresh one that was seconds from re-executing run `d6bb3aae` at full
cost, unattended, on a 60-minute loop. This column is what makes that loop
structurally unreachable.

Why nullable / why NOT NULL
---------------------------
`heartbeat_at` is NULLABLE with NO server default. NULL is the honest value for
a run that has not started, and for every row written before this revision.
The claim reads it through `COALESCE(heartbeat_at, started_at)`, so a pre-0014
row behaves EXACTLY as it does today -- no backfill, no behaviour change on
legacy data.

`reclaim_count` is NOT NULL with `server_default 0`. NOT NULL because the
ceiling arithmetic (`reclaim_count < :max_reclaims`, `reclaim_count + 1`) must
never meet a NULL and silently evaluate to NULL -- that would make the ceiling
match nothing and re-open the very loop this migration closes. The server
default backfills existing rows as part of the DDL, so no separate UPDATE is
needed and no row starts life with a spent recovery.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head
was 0013 (`0013_fact_metadata_research_gap.py`) and whose version table is
`tribunal.tribunal_alembic_version`. This is NOT the intake `nestor` line under
`backend/app/db/alembic/versions/`, which stays at its own 0012 -- two schemas,
two version tables, two independent revision sequences (v1.1 roadmap decision,
Pitfall 2). Do not cross the two lines.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields.
Neither `heartbeat_at` nor `reclaim_count` is among them, and neither enters
that payload. This revision names and alters no hashed table column that the
chain reads, so `verify_chain` cannot move off `(True, None)` and the frozen
payload field count stays 11 (threat T-15.2-201; EU AI Act Art. 12 audit-trail
gate, deadline 2026-08-02).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # EXACTLY TWO DDL statements. No schema= kwarg: env.py has already pointed
    # search_path at the `tribunal` schema, the same way every additive column
    # in 0011, 0012 and 0013 is written.
    #
    # Deliberately NO security DDL. `run` already carries ENABLE + FORCE ROW
    # LEVEL SECURITY, its `run_tenant_isolation` policy and its `run_worker_all`
    # policy (0008). A PostgreSQL row-level POLICY is a TABLE-level object
    # evaluated against row values, so a newly added column is covered BY
    # CONSTRUCTION. Re-issuing any policy, index or privilege grant here would
    # be pure regression risk with zero security benefit -- the same reasoning
    # 0012 and 0013 record (threat T-15.2-205, accepted).

    # ------------------------------------------------------- (1) heartbeat_at
    # The liveness clock the stale reclaim reads. Deliberately NOT the fencing
    # token -- see the docstring.
    op.add_column(
        "run",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ----------------------------------------------------- (2) reclaim_count
    # Bounded crash recoveries. NOT NULL + server default so the ceiling
    # arithmetic never meets a NULL and existing rows are backfilled by the DDL.
    op.add_column(
        "run",
        sa.Column(
            "reclaim_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    # Exact inverse order.
    op.drop_column("run", "reclaim_count")
    op.drop_column("run", "heartbeat_at")
