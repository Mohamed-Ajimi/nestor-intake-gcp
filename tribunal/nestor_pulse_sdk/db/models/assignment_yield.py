"""
AssignmentYield -- one research assignment's cost and its yield (Phase 15.8, D-R8).

WHY THIS TABLE EXISTS RATHER THAN `run_events` (D-W5-1, operator ruling).
`runs/run_events.py::_normalise_meta` passes `meta` through the `_META_FIELDS`
ALLOWLIST and drops every unknown key WITH A WARNING BUT OUT OF THE ROW. None of
the yield keys below is in that tuple, so every one of them would vanish. That is
the inert-instrumentation class this project has been burned by three times --
V-01's stage logging, D-W4-11's workshop notes, and the out-of-vocabulary `kind`
trap. `run_event.text` is also scrubbed AND CLAMPED TO 400 CHARS, and the feed is
PER-RUN, while CROSS-RUN IS THE ENTIRE POINT OF D-R8: "which provider actually
yields surviving claims per dollar" is a query over MANY runs, not one.
`audit_log` was rejected for a different reason -- it is the hash-chained EU AI
Act Art. 12 record whose `verify_chain` is re-gated on every deploy against a
legal deadline. Do not re-litigate either rejection.

Mirrors migration 0018's `assignment_yield` table EXACTLY. The RLS ENABLE/FORCE
plus the `assignment_yield_tenant_isolation` policy live in the MIGRATION, not
here -- exactly as `run_event.py` says of 0015.

NOTHING WRITES THROUGH THIS CLASS. `runs/yield_records.py` inserts with bound
parameters under an explicitly bound tenant GUC. This model exists so the table
is registered in `Base.metadata` (which is what makes alembic autogenerate aware
of it) and so read-side code has a typed handle. Keep the two definitions in
step.

THE THREE SHAPES A ROW CAN HAVE (D-W5-2)
----------------------------------------
  * CROSS-CUTTING `d1` GROUP -- `client_question = NULL`,
    `parent_kind = 'cross_cutting'`. It genuinely has no single parent (there is
    never a `d2`), and NULL is the honest record. Inventing a parent would
    fabricate provenance in a row whose whole purpose is to be trusted later.
  * DISCOVERY RIDER -- `parent_kind = 'discovery_rider'`, and `client_question`
    IS ITS OWN: under D-W3-5.2 a discovery question parented to a
    client-question label joins that label's mandate group.
  * ORDINARY MANDATE ASSIGNMENT -- `parent_kind = 'client_question'`.

`parent_kind` MUST NOT BE INFERRED FROM `client_question IS NULL`. It is a real
column because the two encode DIFFERENT THINGS and a future reader will conflate
them: a row may legitimately carry `client_question = NULL` with
`parent_kind = 'client_question'`.

NULLABILITY, STATED ONCE SO IT IS NOT RE-DERIVED
-----------------------------------------------
NOT NULL: `id`, `tenant_id`, `run_id`, `provider`, `parent_kind`, `created_at` --
identity and scoping. NULLABLE: EVERY MEASURED VALUE, without exception. Three
reasons, all load-bearing: (a) `client_question` is ruled nullable;
(b) `claims_surviving_verification` is genuinely unknown at INSERT time; and
(c) A NOT NULL ON A TELEMETRY COUNTER TURNS A MISSING MEASUREMENT INTO A FAILED
INSERT INSIDE A ~$45 RUN. A NULL means "not recorded"; a 0 means "measured
zero". They must stay distinguishable -- a coercion that turns garbage into 0
fabricates a measurement, which is exactly what this table exists to stop.

A BAD DISCRIMINATOR IS CLAMPED TO A SENTINEL AND THE ROW IS STILL WRITTEN
------------------------------------------------------------------------
(D-W5-10, operator ruling -- it OVERRULES the `run_event.kind` drop precedent.)

`parent_kind` and `provider` may both hold the sentinel `'unknown'`. The emitter
CLAMPS to it and WRITES THE ROW with every other column intact; it NEVER drops
the row, and THERE IS DELIBERATELY NO CHECK CONSTRAINT on either column.

  * `run_event.kind`'s precedent DOES drop, but read its stated reason: "an
    out-of-vocabulary kind renders as a BLANK LINE IN THE FEED, which is worse
    than an absent one". THAT RATIONALE IS DISPLAY-SPECIFIC AND DOES NOT
    TRANSFER. A blank line in a UI feed is noise. A dropped row here is a LOST
    MEASUREMENT -- `cost_usd`, `claims_kept`, `resolvable_sources` and
    `duration_s` all discarded because one discriminator column was wrong.
  * `parent_kind` is ENGINE-AUTHORED, not model-authored, so an
    out-of-vocabulary value means an ENGINE BUG -- precisely the run whose
    telemetry you most want to keep. Dropping it makes the one condition that
    most needs measuring the one condition that erases itself.
  * AND IT WOULD SILENTLY UNDERSTATE SPEND. `SUM(cost_usd)` SKIPS NULL ROWS, and
    `runs/worker.py` totals spend across four `COALESCE(...)` sites, so missing
    cost data DOES NOT ANNOUNCE ITSELF -- the total simply LOOKS complete. A row
    carrying `provider = 'unknown'` still carries its dollars.
  * A CHECK constraint would turn the same event into a FAILED TRANSACTION in a
    paid run, which is worse still.

A `log.warning` is not persistence. That is the V-01 lesson stated exactly.
Neither sentinel belongs to any vocabulary tuple, so `parent_kind IN
PARENT_KINDS` still returns exactly the three ruled shapes while
`parent_kind = 'unknown'` is the engine-bug query.

THE NATURAL KEY, AND THE KEY-SYMMETRY RULE
------------------------------------------
`(run_id, provider, group_id, client_question)` is the NATURAL KEY that
`runs/yield_records.py::complete_assignment` uses to find this row again after
verification. It is NOT the row id: a parked run RESUMES IN A DIFFERENT PROCESS,
where an in-memory row id is gone, and the natural key survives a restart.

THREE OF THE FOUR KEY MEMBERS ARE NORMALISED: `provider` is clamped to the
sentinel, `group_id` has `''` turned into NULL and is length-clamped, and
`client_question` is SCRUBBED AND THEN CLAMPED. So BOTH HALVES MUST BUILD THE KEY
THROUGH THE ONE SHARED `_natural_key()` HELPER. If the completer built its key
from RAW values while the INSERT stored normalised ones, the UPDATE would match
NOTHING -- and the emitter's own warning reads an affected-row count of 0 as "the
INSERT half never landed", producing a SPECIFIC, CONFIDENT AND COMPLETELY WRONG
diagnosis of a different failure, in the one run there is.

INSERT AT RESEARCH-RESOLVE, UPDATE AFTER VERIFICATION
-----------------------------------------------------
The research half (cost, duration, claims kept, sources, the parse/retry flags)
is DURABLE and paid for the moment research resolves.
`claims_surviving_verification` only exists later, so it is written by a SEPARATE
UPDATE. Writing one row late would lose the paid half on a run parked between the
two stages.

`verified_at` exists because `claims_surviving_verification IS NULL` is otherwise
AMBIGUOUS between "verification never ran for this row" and "verification kept
zero claims" -- and telling those apart is the difference between a broken
pipeline and a bad provider, which is the exact question this table is for.

Columns:
  - id                             UUID PK (default uuid4)
  - tenant_id                      UUID FK org.id CASCADE (the RLS tenant key)
  - run_id                         UUID FK run.id CASCADE; natural-key member
  - provider                       TEXT -- a `_D6_STREAMS` value, or 'unknown';
                                   natural-key member, normalised on BOTH paths
  - group_id                       TEXT nullable -- the `corroboration_key`
                                   ('w01' / 'w02' / ...). An ABSENT key is bound
                                   as NULL and NEVER as '' (migration 0017's own
                                   rule): "no key recorded" and "recorded as the
                                   empty key" are different facts. Natural-key
                                   member.
  - client_question                TEXT nullable (D-W5-2) -- NULL for
                                   cross-cutting. Scrubbed THEN clamped, in that
                                   order (D-07). Natural-key member.
  - parent_kind                    TEXT -- client_question | discovery_rider |
                                   cross_cutting, or 'unknown'. NOT a key member.
  - stakes                         TEXT nullable -- high | med | low.
  - fact_list_parsed               BOOLEAN nullable
  - retry_used                     BOOLEAN nullable
  - claims_kept                    INTEGER nullable
  - claims_surviving_verification  INTEGER nullable -- WRITTEN BY THE UPDATE HALF
                                   ONLY; deliberately no default of any kind.
  - resolvable_sources             INTEGER nullable
  - cost_usd                       NUMERIC(12,6) nullable -- the `audit_log`
                                   convention. SUM skips NULLs SILENTLY.
  - duration_s                     NUMERIC(10,3) nullable -- NUMERIC and not
                                   FLOAT: a float renders differently per
                                   serialiser and a human compares these.
  - created_at                     timestamptz server_default now(); what makes a
                                   cross-run time query possible at all.
  - verified_at                    timestamptz nullable -- set by the UPDATE half.

NO UNIQUE CONSTRAINT. `divide()`'s focus-area fallback path doubles a high-stakes
angle with a second copy to `_HIGH_REDUNDANCY_PROVIDER`, which can produce two
rows sharing the natural key. A UNIQUE over it would convert that into a FAILED
INSERT inside a paid run. The completer reports the affected row count instead.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class AssignmentYield(Base):
    __tablename__ = "assignment_yield"

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
    # 3 -- natural-key member.
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 4 -- one of `research_division._D6_STREAMS`, or the 'unknown' sentinel.
    # Natural-key member: normalised on BOTH the INSERT and the UPDATE path.
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    # 5 -- the corroboration key. ABSENT is NULL, never '' (0017's rule).
    # Natural-key member.
    group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 6 -- D-W5-2: NULLABLE. NULL for a cross-cutting group. Scrubbed then
    # clamped, in that order (D-07). Natural-key member.
    client_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 7 -- a real column, NOT inferred from `client_question IS NULL`. Clamped to
    # 'unknown' by the emitter rather than by a CHECK constraint: an
    # out-of-vocabulary value must keep its row, not fail the transaction.
    parent_kind: Mapped[str] = mapped_column(Text, nullable=False)
    # 8
    stakes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 9
    fact_list_parsed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 10
    retry_used: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # 11
    claims_kept: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 12 -- filled by `complete_assignment` only. No default, so "never verified"
    # reads back as NULL and not as a placeholder that looks like data.
    claims_surviving_verification: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    # 13
    resolvable_sources: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 14 -- matches audit_log.cost_usd / run.cost_usd_total. SUM skips NULLs.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    # 15 -- seconds to ms. NUMERIC, not FLOAT.
    duration_s: Mapped[Decimal | None] = mapped_column(Numeric(10, 3), nullable=True)
    # 16
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # 17 -- disambiguates "verification never ran" from "verification kept zero".
    verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index(
            "idx_assignment_yield_tenant_run",
            "tenant_id",
            "run_id",
        ),
    )
