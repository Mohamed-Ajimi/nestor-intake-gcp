"""
WorkshopRoundYield -- one workshop-loop round's population and cost (D-R8).

WHY THIS TABLE EXISTS RATHER THAN `run_events` (D-W5-1, operator ruling).
`runs/run_events.py::_normalise_meta` passes `meta` through the `_META_FIELDS`
ALLOWLIST and drops every unknown key WITH A WARNING BUT OUT OF THE ROW -- none
of the counters below is in that tuple, so every one of them would vanish. That
is the inert-instrumentation class this project has been burned by three times
(V-01's stage logging, D-W4-11's workshop notes, the out-of-vocabulary `kind`
trap). `run_event.text` is scrubbed AND CLAMPED TO 400 CHARS, and the feed is
PER-RUN -- while CROSS-RUN IS THE ENTIRE POINT OF D-R8. `audit_log` was rejected
too: it is the hash-chained EU AI Act Art. 12 record whose `verify_chain` is
re-gated on every deploy against a legal deadline.

THE QUESTION THIS TABLE EXISTS TO ANSWER
----------------------------------------
`new_entrants_top_n` IS THE COUNTER THE WHOLE LOOP'S JUSTIFICATION RESTS ON:

    IF ROUND 7+ NEVER PRODUCES A NEW ENTRANT ACROSS SEVERAL RUNS, DROP THE CAP
    AND KEEP THE MONEY.

"Across several runs" is why a per-run feed was rejected. One run cannot answer
it; a table read across runs can.

Mirrors migration 0018's `workshop_round_yield` table EXACTLY. The RLS
ENABLE/FORCE plus the `workshop_round_yield_tenant_isolation` policy live in the
MIGRATION, not here -- exactly as `run_event.py` says of 0015.

NOTHING WRITES THROUGH THIS CLASS. `runs/yield_records.py::record_round` inserts
with bound parameters under an explicitly bound tenant GUC. This model exists so
the table is registered in `Base.metadata` (which is what makes alembic
autogenerate aware of it) and so read-side code has a typed handle. Keep the two
definitions in step.

THREE BINDINGS A WRITER WILL GET WRONG IF THIS IS NOT SAID OUT LOUD
-------------------------------------------------------------------
`workshop_loop.round_metrics(...)` returns `{round_no, candidates_in,
new_candidates, winners, weak_winners, barred, dropped_as_reproposal, lookups,
calls, cost_usd}`. THAT IS NOT ONE RENAME AWAY FROM THIS COLUMN SET, and nobody
may treat it as one. 15.8-10 must EXTEND `round_metrics`, not map onto it
(D-W5-11).

  1. `keep_count` IS THE KEEP CRITIQUE-VERDICT COUNT AND NOT THE WINNER-SET SIZE.
     `round_metrics`' `winners` is `len(entries)`; KEEP is a critique verdict
     (`workshop_loop._KEEP` / `_WEAK` / `_KILL`). Binding one as the other writes
     a different number into the only measuring run, AND IT WOULD LOOK PLAUSIBLE.
  2. `kill_count` HAS NO PRODUCER IN `round_metrics` TODAY.
  3. `new_entrants_top_n` HAS NO PRODUCER IN `round_metrics` TODAY EITHER. It is
     computed inside `workshop_loop.exit_verdict` (winners whose
     `born_round == current`) and returned in THAT function's dict -- it never
     reaches `round_metrics`.

`barred_drops` MEANS THE BARRED CAUSE AND NOTHING ELSE (D-W5-6)
---------------------------------------------------------------
`workshop_register.record_drop` appends BOTH drop causes to ONE
`register["drops"]` list, and `workshop_rank.py` reads that list BY BARE LENGTH
in three places, all three named for the barred cause only (`drops_before` at
:4527, the delta feeding `round_metrics(dropped_as_reproposal=...)` at :4540, and
`"dropped_as_reproposal": len(register.get("drops") or [])` at :5007).

Today only the barred cause can ever be written, so a bare length is
ACCIDENTALLY CORRECT. The moment 15.8-04 lands a production
`DROP_CLUSTERED_ONTO_LIVE` writer, a bare length starts counting ordinary
near-copy merges -- so THE "LOOP IS SPINNING" METRIC WOULD SILENTLY ABSORB THE
OPPOSITE FAILURE IT EXISTS TO DISTINGUISH. D-W5-6 rules that 15.8-10 swaps all
three reads to the cause-filtered `count_drops` BEFORE persisting into this
column. An inflated `barred_drops` in the ONE measuring run is not recoverable.

NULLABILITY. NOT NULL: `id`, `tenant_id`, `run_id`, `round_no`, `created_at` --
identity and scoping. NULLABLE: every measured counter, because A NOT NULL ON A
TELEMETRY COUNTER TURNS A MISSING MEASUREMENT INTO A FAILED INSERT INSIDE A ~$45
RUN. NULL means "not recorded"; 0 means "measured zero"; they must stay
distinguishable. There is deliberately NO CHECK and NO UNIQUE constraint on this
table for the same reason.

Columns:
  - id                  UUID PK (default uuid4)
  - tenant_id           UUID FK org.id CASCADE (the RLS tenant key)
  - run_id              UUID FK run.id CASCADE
  - round_no            INTEGER -- the loop round this row measures.
  - candidates_in       INTEGER nullable
  - new_candidates      INTEGER nullable
  - keep_count          INTEGER nullable -- the KEEP CRITIQUE VERDICT count, NOT
                        `len(entries)`. See binding note 1 above.
  - weak_count          INTEGER nullable
  - kill_count          INTEGER nullable -- no producer in `round_metrics` today.
  - new_entrants_top_n  INTEGER nullable -- the counter the loop's justification
                        rests on; computed in `exit_verdict` today, not in
                        `round_metrics`.
  - barred_drops        INTEGER nullable -- THE BARRED CAUSE ONLY (D-W5-6).
  - round_cost_usd      NUMERIC(12,6) nullable -- the `audit_log` convention.
                        SUM skips NULLs SILENTLY.
  - created_at          timestamptz server_default now(); what makes a cross-run
                        time query possible at all.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class WorkshopRoundYield(Base):
    __tablename__ = "workshop_round_yield"

    # 1
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 2
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 3
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 4
    round_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 5
    candidates_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 6
    new_candidates: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 7 -- the KEEP critique-verdict count, NOT the winner-set size.
    keep_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 8
    weak_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 9 -- no producer in `round_metrics` today; 15.8-10 extends it.
    kill_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 10 -- the counter the loop's whole justification rests on.
    new_entrants_top_n: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 11 -- THE BARRED CAUSE ONLY (D-W5-6). A bare `len(register["drops"])` is
    # only accidentally correct today and becomes wrong the moment a live-drop
    # writer lands.
    barred_drops: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 12
    round_cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 6), nullable=True
    )
    # 13
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_workshop_round_yield_tenant_run_round",
            "tenant_id",
            "run_id",
            "round_no",
        ),
    )
