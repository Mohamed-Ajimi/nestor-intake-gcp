"""
RunEvent -- one append-only line of a run's activity feed (Phase 15.3, D-04).

WHY THIS TABLE EXISTS RATHER THAN MORE `stage_detail`. `runs/stages.py::set_stage`
writes `stage_detail = COALESCE(stage_detail,'{}') || CAST(:entry AS JSONB)`, and
`||` is a MERGE KEYED BY STAGE -- it replaces the whole top-level key. A stage
that reports twice OVERWRITES ITSELF, so there is no ordering and no history, and
the intermediate states a feed is made of are gone before anything reads them.
That is why the operator watching run `d6bb3aae` (2026-07-27) could not tell what
the engine was doing. An append-only row with a monotonic `seq` is what makes
"close the run page and reopen it" show real history instead of a snapshot.

`stage_detail` is NOT replaced. These rows are written ALONGSIDE it.

Mirrors migration 0015's `run_event` table EXACTLY. FK shape + tenant scoping
copied from verification_verdict.py; the RLS ENABLE/FORCE + the
`run_event_tenant_isolation` policy live in the MIGRATION, not the ORM, exactly
as claim / source / verification_verdict do.

NOTHING WRITES THROUGH THIS CLASS TODAY. `runs/run_events.py` inserts with a
batched multi-row `INSERT` under an explicitly bound tenant GUC, because the emit
path must stay cheap and must never open the ORM's identity map inside a paid
run. This model exists so the table is registered in `Base.metadata` (which is
what makes alembic autogenerate aware of it) and so read-side code has a typed
handle. Keep the two definitions in step.

Columns:
  - id         UUID PK (default uuid4)
  - tenant_id  UUID FK org.id CASCADE (the RLS tenant key)
  - run_id     UUID FK run.id CASCADE
  - seq        BIGINT -- monotonic per run, assigned IN PROCESS by the emitter and
               seeded at open_run from COALESCE(MAX(seq),0) so a RESUMED run
               continues its own numbering. Deliberately NOT unique: a resume
               race must degrade to a mis-ordered line, never to a failed insert,
               because an event write may never fail a run (D-06).
  - ts         timestamptz server_default now(); the emitter supplies it at EMIT
               time so ordering survives a batch written seconds later.
  - stage      TEXT -- an ENGINE_STAGES key (runs/stages.py); also the feed's
               group key.
  - kind       TEXT -- one of run_events.RUN_EVENT_KINDS, the twelve LineKind
               values of the design of record. Clamped by the emitter rather than
               by a CHECK constraint, so an out-of-vocabulary kind drops the ROW
               instead of raising into the run.
  - text       TEXT -- scrubbed by pii.scrub_pii and THEN clamped, in that order
               (D-07): clamping first can bisect an email and leave a fragment
               the scrubber no longer matches.
  - meta       JSONB nullable -- whitelisted keys only
               (run_events._META_FIELDS), string values scrubbed too.

The attribute is named `text` on purpose. It shadows nothing in this module, and
both the wire contract and the design of record call it `text` -- do not rename
it to `body` for tidiness.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class RunEvent(Base):
    __tablename__ = "run_event"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Monotonic per run. NOT unique -- see the module docstring.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    # Scrubbed then clamped, in that order (D-07).
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Whitelisted keys only; string values scrubbed.
    meta: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    __table_args__ = (
        Index(
            "idx_run_event_tenant_run_seq",
            "tenant_id",
            "run_id",
            "seq",
        ),
    )
