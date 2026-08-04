"""0018 yield instrumentation -- two new tables (Phase 15.8, D-R8 / D-W5-1).

TWO new tables, TWO indexes, ENABLE + FORCE row level security and ONE
tenant-isolation policy each. No column is added to any existing table and no
existing policy, index or privilege is re-issued.

WHY THIS EXISTS
---------------
The redesigned engine is about to be measured ONCE, and the two questions the
measurement must answer --

    which provider actually yields SURVIVING claims per dollar, and
    does round 7+ of the workshop loop EVER produce a new entrant

-- are QUERIES OVER MANY RUNS. There is nowhere in this schema to record either
today. That is what these two tables are for, and the cross-run shape is the
whole reason they are tables at all.

WHY NOT `run_events`, AND WHY NOT `audit_log` (D-W5-1, operator ruling)
-----------------------------------------------------------------------
`runs/run_events.py::_normalise_meta` passes `meta` through the `_META_FIELDS`
ALLOWLIST and drops every unknown key WITH A WARNING BUT OUT OF THE ROW. Not one
of the yield keys below is in that tuple, so every one of them would vanish --
the inert-instrumentation class this project has been burned by three times
(V-01's stage logging, D-W4-11's workshop notes, the out-of-vocabulary `kind`
trap). `run_event.text` is also scrubbed AND CLAMPED TO 400 CHARS, and the feed
is PER-RUN, while cross-run is the entire point of D-R8.

`audit_log` was rejected for a different reason: it is the HASH-CHAINED EU AI Act
Art. 12 record whose `verify_chain` is re-gated on every deploy against a legal
deadline. Widening it to carry telemetry would put a compliance artefact on the
same change path as an engine metric.

Do not re-litigate either rejection.

D-W5-2: `client_question` IS NULLABLE, BESIDE A REAL `parent_kind` COLUMN
-------------------------------------------------------------------------
A cross-cutting `d1` group has NO SINGLE PARENT (there is never a `d2`), so it
records `client_question = NULL, parent_kind = 'cross_cutting'` -- inventing a
parent would fabricate provenance in a row whose whole purpose is to be trusted
later. A discovery rider parented to a client-question label (D-W3-5.2) joins
that label's mandate group and records ITS OWN `client_question` with
`parent_kind = 'discovery_rider'`. An ordinary mandate assignment records
`parent_kind = 'client_question'`.

`parent_kind` is a REAL COLUMN and must NOT be inferred from
`client_question IS NULL`: the two encode different things and a future reader
will conflate them.

NULLABILITY
-----------
NOT NULL: identity and scoping only -- `id`, `tenant_id`, `run_id`, `provider`,
`parent_kind`, `created_at`, and `round_no` on the round table. NULLABLE: EVERY
MEASURED VALUE, without exception, because a NOT NULL on a telemetry counter
turns a MISSING MEASUREMENT into a FAILED INSERT inside a ~$45 run. NULL means
"not recorded"; 0 means "measured zero"; the two must stay distinguishable.

THE NATURAL KEY -- AND WHY A LATER UNIQUE CONSTRAINT OVER IT WOULD BE A DEFECT
------------------------------------------------------------------------------
`(run_id, provider, group_id, client_question)` is the NATURAL KEY that
`runs/yield_records.py::complete_assignment` uses to find an assignment row again
after verification, to fill `claims_surviving_verification` and `verified_at`. It
is the natural key and not a returned row id because A PARKED RUN RESUMES IN A
DIFFERENT PROCESS, where an in-memory row id is gone.

DO NOT ADD A UNIQUE CONSTRAINT OVER IT IN A LATER MIGRATION. `divide()`'s
focus-area fallback path doubles a high-stakes angle with a second copy to
`_HIGH_REDUNDANCY_PROVIDER`, which can legitimately produce two rows sharing that
key. A UNIQUE would convert that into a FAILED INSERT inside a paid run. The
emitter reports the affected row count and warns instead.

THREE DELIBERATE OMISSIONS -- DO NOT "FIX" ANY OF THEM
-------------------------------------------------------
1. NO PRIVILEGE STATEMENT. 0008's `ALTER DEFAULT PRIVILEGES FOR ROLE app_user IN
   SCHEMA tribunal` block already covers DML for `worker_user` on tables created
   by LATER migrations, so this revision needs none of its own. (0015's reasoning,
   unchanged.)

2. NO `worker_all` POLICY on either table. `worker_all` exists for exactly one
   thing -- the cross-tenant SKIP LOCKED claim scan in `runs/worker.py`, which
   must read rows before it knows their tenant. Nothing ever scans these two
   tables cross-tenant: every write goes through `runs/yield_records.py`, which
   binds `app.tenant_id` first. A permissive `current_user = 'worker_user'`
   policy here would widen the tenant wall for no caller that needs it.

3. NO CHECK CONSTRAINT on `parent_kind` or on `provider` -- and this one is new
   to this revision, so read it before "tightening" anything. D-W5-10 rules that
   an out-of-vocabulary value CLAMPS TO THE SENTINEL `'unknown'` AND THE ROW IS
   STILL WRITTEN. `run_event.kind` does drop such a row, but its stated reason is
   DISPLAY-SPECIFIC -- "renders as a blank line in the feed" -- and does not
   transfer to a telemetry table. A dropped row here is a LOST MEASUREMENT
   (`cost_usd`, `claims_kept`, `resolvable_sources`, `duration_s` all discarded),
   and worse, A SILENT UNDERSTATEMENT OF SPEND: `SUM(cost_usd)` SKIPS NULL ROWS
   across four `COALESCE(...)` sites in `runs/worker.py`, so missing cost data
   does not announce itself -- the total simply LOOKS complete. `parent_kind` is
   ENGINE-AUTHORED, so an out-of-vocabulary value means an ENGINE BUG: precisely
   the run whose telemetry is most worth keeping.

   A CHECK constraint would turn that same event into a FAILED TRANSACTION inside
   a paid run, which is worse still. This is the same reasoning that leaves
   `run_event.seq` deliberately non-unique and `claim.corroboration_key`
   deliberately un-CHECKed.

The indexes below are READ-PATH shaped and are NOT constraints.

Which alembic line
------------------
The TRIBUNAL line (`tribunal/nestor_pulse_sdk/alembic/versions/`), whose head is
0017 (`0017_claim_attribution.py`) and whose version table is
`tribunal.tribunal_alembic_version`. This is NOT the intake `nestor` line under
`backend/app/db/alembic/versions/` -- two schemas, two version tables, two
independent revision sequences, NEVER CROSSED (Pitfall 2). A revision id borrowed
from the other line is how one of them silently stops upgrading. No `schema=`
kwarg is passed: env.py has already pointed search_path at the `tribunal` schema,
exactly as 0011-0017 are written.

Hash-chain safety
-----------------
`nestor_pulse_sdk/audit/hash_chain.py::_payload_for_row` freezes ELEVEN fields on
`audit_log`. This revision creates NEW tables and alters no hashed column, so
`verify_chain` cannot move off `(True, None)` and the frozen payload field count
stays 11 -- unaffected BY CONSTRUCTION, not by inspection (EU AI Act Art. 12
audit-trail gate).

Deploy-time proof -- OWED, NOT CLAIMED. THIS IS THE THIRD UNPAID MIGRATION.
---------------------------------------------------------------------------
THE PROOF OF A MIGRATION IS ITS LITERAL LOG LINE, on one line and unwrapped. Three
are owed at this one deploy, because `0015 -> 0016` and `0016 -> 0017` HAVE NEVER
TOUCHED A DATABASE -- 0017 is the head of the FILES, not of any live schema:

    Running upgrade 0015 -> 0016
    Running upgrade 0016 -> 0017
    Running upgrade 0017 -> 0018

IT IS NEVER exit code 0. This repository has a recorded incident of an alembic
step that exited 0 without ever printing an upgrade line, and reported green. An
exit code 0 with no upgrade line is a FAILED proof, not a passed one.

This plan PERFORMS NO DEPLOY. It writes a migration; it does not run one. All
three lines are produced by the migrate job in 15.8-14.
The proof is therefore OWED AT PHASE 15.8, and until all three lines print, all
three revisions are WRITTEN, NOT APPLIED. Do not assert that any of them ran.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-04
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------- assignment_yield table
    # The column set is the contract fixed in plan 15.8-05's <column_contract>
    # block and consumed unchanged by 15.8-09 and 15.8-10. Order is NORMATIVE
    # and is asserted against the ORM by tests/test_yield_schema.py. FK shape and
    # the RLS block below are copied from 0015's run_event table.
    op.create_table(
        "assignment_yield",
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
        # A `research_division._D6_STREAMS` value, or the 'unknown' SENTINEL.
        # Clamped by the emitter, NOT by a CHECK constraint -- see omission 3.
        # Natural-key member: normalised on the INSERT and the UPDATE path alike.
        sa.Column("provider", sa.Text(), nullable=False),
        # The corroboration key ('w01' / 'w02' / ...). An ABSENT key is bound as
        # NULL and NEVER as '' -- migration 0017's own rule, because "no key
        # recorded" and "recorded as the empty key" are different facts.
        # Natural-key member.
        sa.Column("group_id", sa.Text(), nullable=True),
        # D-W5-2: NULLABLE. NULL for a cross-cutting group, which genuinely has
        # no single parent. Scrubbed by pii.scrub_pii and THEN clamped, in that
        # order (D-07). Natural-key member.
        sa.Column("client_question", sa.Text(), nullable=True),
        # client_question | discovery_rider | cross_cutting, or 'unknown'. A REAL
        # column: it must NOT be inferred from `client_question IS NULL`. NOT a
        # natural-key member.
        sa.Column("parent_kind", sa.Text(), nullable=False),
        # high | med | low.
        sa.Column("stakes", sa.Text(), nullable=True),
        sa.Column("fact_list_parsed", sa.Boolean(), nullable=True),
        sa.Column("retry_used", sa.Boolean(), nullable=True),
        sa.Column("claims_kept", sa.Integer(), nullable=True),
        # Filled by the UPDATE half only, keyed on the natural key. No default of
        # any kind: "verification never ran" must read back as NULL.
        sa.Column("claims_surviving_verification", sa.Integer(), nullable=True),
        sa.Column("resolvable_sources", sa.Integer(), nullable=True),
        # Matches audit_log.cost_usd / run.cost_usd_total. SUM skips NULLs.
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=True),
        # Seconds to ms. NUMERIC and not FLOAT: a float renders differently per
        # serialiser and a human compares these numbers.
        sa.Column("duration_s", sa.Numeric(10, 3), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # Set by the UPDATE half. Without it `claims_surviving_verification IS
        # NULL` is AMBIGUOUS between "verification never ran for this row" and
        # "verification kept zero claims" -- the difference between a broken
        # pipeline and a bad provider.
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )

    # -------------------------------------------- workshop_round_yield table
    op.create_table(
        "workshop_round_yield",
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
        sa.Column("round_no", sa.Integer(), nullable=False),
        sa.Column("candidates_in", sa.Integer(), nullable=True),
        sa.Column("new_candidates", sa.Integer(), nullable=True),
        # The KEEP CRITIQUE-VERDICT count -- NOT the winner-set size. Binding
        # `round_metrics`' `winners` (which is len(entries)) here would write a
        # different number into the only measuring run, and it would look
        # plausible.
        sa.Column("keep_count", sa.Integer(), nullable=True),
        sa.Column("weak_count", sa.Integer(), nullable=True),
        # No producer in `round_metrics` today; 15.8-10 EXTENDS it.
        sa.Column("kill_count", sa.Integer(), nullable=True),
        # The counter the loop's whole justification rests on: if round 7+ never
        # produces a new entrant across several runs, drop the cap and keep the
        # money. Computed in `exit_verdict` today, not in `round_metrics`.
        sa.Column("new_entrants_top_n", sa.Integer(), nullable=True),
        # THE BARRED CAUSE ONLY (D-W5-6). `record_drop` appends both drop causes
        # to one list which `workshop_rank` reads by BARE LENGTH in three places;
        # that is only accidentally correct today and becomes wrong the moment a
        # live-drop writer lands.
        sa.Column("barred_drops", sa.Integer(), nullable=True),
        sa.Column("round_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------- indexes
    # Read-path shaped, NOT constraints. The assignment read is always "this
    # tenant, this run"; the round read adds the round number because the
    # cross-run question is asked per round ("does round 7+ ever...").
    op.create_index(
        "idx_assignment_yield_tenant_run",
        "assignment_yield",
        ["tenant_id", "run_id"],
    )
    op.create_index(
        "idx_workshop_round_yield_tenant_run_round",
        "workshop_round_yield",
        ["tenant_id", "run_id", "round_no"],
    )

    # ----------------------------------------------------------- RLS blocks
    # WITH CHECK is included on purpose, on BOTH policies: the pipeline INSERTs
    # into both tables, and a USING-only policy would let the read pass while the
    # write failed -- a failure that would only surface mid-run.
    op.execute("ALTER TABLE assignment_yield ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assignment_yield FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY assignment_yield_tenant_isolation ON assignment_yield
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )
    op.execute("ALTER TABLE workshop_round_yield ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workshop_round_yield FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY workshop_round_yield_tenant_isolation ON workshop_round_yield
            USING (tenant_id = current_setting('app.tenant_id')::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id')::uuid)
        """
    )
    # Deliberately NOTHING further here. See the module docstring for the three
    # omissions: no privilege statement (0008 already covers later tables), no
    # worker_all policy (nothing scans these tables cross-tenant), and no CHECK
    # constraint on either discriminator (D-W5-10 -- a clamped row, never a
    # failed transaction in a paid run).


def downgrade() -> None:
    # Exact inverse order, per table: policy, NO FORCE, DISABLE -- then the
    # indexes, then the tables, each in reverse creation order.
    op.execute(
        "DROP POLICY IF EXISTS workshop_round_yield_tenant_isolation "
        "ON workshop_round_yield"
    )
    op.execute("ALTER TABLE workshop_round_yield NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE workshop_round_yield DISABLE ROW LEVEL SECURITY")
    op.execute(
        "DROP POLICY IF EXISTS assignment_yield_tenant_isolation ON assignment_yield"
    )
    op.execute("ALTER TABLE assignment_yield NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE assignment_yield DISABLE ROW LEVEL SECURITY")
    op.drop_index(
        "idx_workshop_round_yield_tenant_run_round",
        table_name="workshop_round_yield",
    )
    op.drop_index(
        "idx_assignment_yield_tenant_run",
        table_name="assignment_yield",
    )
    op.drop_table("workshop_round_yield")
    op.drop_table("assignment_yield")
