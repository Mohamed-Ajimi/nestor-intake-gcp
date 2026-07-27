"""0015 run_event -- the append-only run feed substrate (Phase 15.3, D-04).

ONE new table, ONE index, ENABLE + FORCE row level security and ONE
tenant-isolation policy. No column is added to any existing table and no
existing policy, index or privilege is re-issued.

WHY A TABLE AND NOT MORE `stage_detail`
---------------------------------------
`runs/stages.py::set_stage` writes

    stage_detail = COALESCE(stage_detail, '{}'::jsonb) || CAST(:entry AS JSONB)

and `||` is a MERGE KEYED BY STAGE: it replaces the whole top-level key. So a
stage that reports twice OVERWRITES ITSELF. There is no ordering and there is
no history -- the intermediate states a feed is made of are gone before
anything reads them, and a sequence like "Dispatching 3 agents -> three
indented children -> one completes" cannot be reconstructed from that column at
all. That is defect D-04, and it is why the operator watching run `d6bb3aae`
(2026-07-27) could not tell what the engine was doing.

An APPEND-ONLY row with a monotonic `seq` fixes exactly that: ordering comes
from `seq`, the rows survive the run that produced them, and closing and
reopening the run page shows real history rather than a snapshot. Appending to
`stage_detail` instead was rejected -- it grows a hot row without bound, every
write rewrites the whole blob, and it still guarantees no ordering.

`stage_detail` STAYS. This table is written ALONGSIDE it, never in place of it:
the intake-page summary card reads `stage_detail` today and keeps doing so.

SEQ IS DELIBERATELY NOT UNIQUE
------------------------------
`seq` is a plain bigint assigned IN PROCESS by `runs/run_events.py`, seeded at
`open_run` from `COALESCE(MAX(seq), 0)` so a RESUMED run continues its own
numbering instead of colliding with its own history. There is deliberately no
`UNIQUE (run_id, seq)`: a resume race would turn a duplicate number into a
FAILED INSERT, and an event write is never allowed to fail a run (D-06). A
duplicated `seq` costs the feed one mis-ordered line; a raised insert costs a
paid deep-research run. The index below is for the read path, not a constraint.

NO PRIVILEGE STATEMENT AND NO `worker_all` POLICY -- BOTH OMISSIONS ARE DELIBERATE
---------------------------------------------------------------------------------
Do not "fix" either one. 0008's `ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN
SCHEMA tribunal` block already covers DML for `worker_user` on tables created
by LATER migrations, so this revision needs no privilege statement of its own.
And `run_event` gets no `run_event_worker_all` policy because `worker_all`
exists for exactly one thing -- the cross-tenant SKIP LOCKED claim scan in
`runs/worker.py`, which must read rows before it knows their tenant. Nothing
ever scans this table cross-tenant: every write goes through
`run_events._insert_events`, which binds `app.tenant_id` first, and every read
is a tenant-scoped API verb. Adding a permissive `current_user = 'worker_user'`
policy here would widen the tenant wall for no caller that needs it.

RETENTION IS NOT SOLVED HERE -- IT IS SIZED HERE
------------------------------------------------
The retention/pruning policy is an explicitly deferred decision (15.3-CONTEXT
"Deferred"). What follows is the arithmetic that decision will need, recorded
now so it is made with a number beside it instead of being rediscovered as a
surprise on a full disk.

  * ROWS PER RUN. The observed shape is a 24-angle tribunal run across 14
    stages running 30-60 minutes. With per-poll provider transitions, per-angle
    dispatch/run/done lines, workshop tournament rounds and per-stage
    summaries, that is ON THE ORDER OF A FEW THOUSAND EVENTS. Take 3,000 as
    the working figure.

  * BYTES PER ROW. Fixed columns are 64 bytes (16 id + 16 tenant_id + 16
    run_id + 8 seq + 8 ts). `stage` averages ~18 bytes and `kind` ~11. `text`
    is CLAMPED by the emitter at `NESTOR_RUN_EVENT_TEXT_MAX` (400 chars), so
    ~401 bytes worst case and ~120 typical. `meta` is a whitelisted JSONB of at
    most 13 keys whose string values carry the same clamp: ~150 bytes typical.
    With the 24-byte heap tuple header and alignment that is roughly
    700 BYTES PER ROW WORST CASE and ~400 typical, plus ~48 bytes per row for
    the btree index below. Call it 750 worst / 450 typical.

  * THEREFORE: ~2.2 MB per run worst case (~1.3 MB typical), and
    ~220 MB PER HUNDRED RUNS worst case (~135 MB typical). At 100 runs a month
    that is roughly 1.6-2.6 GB per year.

  * NO PRUNING JOB EXISTS. This table GROWS MONOTONICALLY. The only deletion
    path today is the `ON DELETE CASCADE` from `run` and from `org` -- rows go
    away when the run row or the tenant goes away, and never otherwise. When a
    pruning decision is finally made, the natural shape is a retention window
    on `ts` for runs in a terminal status, because the index below is already
    ordered `(tenant_id, run_id, seq)` and a delete-by-run is therefore cheap.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head
was 0014 (`0014_run_liveness_and_reclaim.py`) and whose version table is
`tribunal.tribunal_alembic_version`. This is NOT the intake `nestor` line under
`backend/app/db/alembic/versions/` -- two schemas, two version tables, two
independent revision sequences (Pitfall 2). Do not cross the two lines. No
`schema=` kwarg is passed: env.py has already pointed search_path at the
`tribunal` schema, exactly as 0011-0014 are written.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields
on `audit_log`. This revision creates a NEW table and alters no hashed column,
so `verify_chain` cannot move off `(True, None)` and the frozen payload field
count stays 11 (EU AI Act Art. 12 audit-trail gate, deadline 2026-08-02).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-27
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------- run_event table
    # Column set is the wire contract fixed in the plan's <interfaces> block and
    # consumed unchanged by plans 15.3-02…05. FK shape + the RLS block below are
    # copied verbatim from 0011's verification_verdict table.
    op.create_table(
        "run_event",
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
        # Monotonic per run, assigned in process. NOT unique -- see the module
        # docstring: a resume race must degrade to a mis-ordered line, never to
        # a failed insert (D-06).
        sa.Column("seq", sa.BigInteger(), nullable=False),
        sa.Column(
            "ts",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # An ENGINE_STAGES key (runs/stages.py). Doubles as the feed group key.
        sa.Column("stage", sa.Text(), nullable=False),
        # One of run_events.RUN_EVENT_KINDS -- the twelve LineKind values of the
        # design of record. Clamped to that vocabulary by the emitter, not by a
        # CHECK constraint: an out-of-vocabulary kind must drop the ROW, not
        # raise into the run that produced it.
        sa.Column("kind", sa.Text(), nullable=False),
        # Scrubbed by pii.scrub_pii and THEN clamped, in that order (D-07).
        sa.Column("text", sa.Text(), nullable=False),
        # Whitelisted keys only (run_events._META_FIELDS).
        sa.Column("meta", postgresql.JSONB(), nullable=True),
    )
    # The read path is always "this tenant, this run, in seq order" -- the
    # backfill read that makes reopening the run page work (D-01/D-05).
    op.create_index(
        "idx_run_event_tenant_run_seq",
        "run_event",
        ["tenant_id", "run_id", "seq"],
    )
    op.execute("ALTER TABLE run_event ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE run_event FORCE ROW LEVEL SECURITY")
    # WITH CHECK is included on purpose: the pipeline INSERTs into this table,
    # and a USING-only policy would let the read pass while the write failed.
    op.execute(
        """
        CREATE POLICY run_event_tenant_isolation ON run_event
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )
    # Deliberately NOTHING further here. See the module docstring for why this
    # revision issues no privilege statement (0008 ALTER DEFAULT PRIVILEGES
    # already covers future tables) and no worker_all policy (nothing scans
    # this table cross-tenant).


def downgrade() -> None:
    # Exact inverse order: policy, NO FORCE, DISABLE, index, table.
    op.execute("DROP POLICY IF EXISTS run_event_tenant_isolation ON run_event")
    op.execute("ALTER TABLE run_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE run_event DISABLE ROW LEVEL SECURITY")
    op.drop_index("idx_run_event_tenant_run_seq", table_name="run_event")
    op.drop_table("run_event")
