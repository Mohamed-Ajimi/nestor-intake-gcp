"""0013 research_run_event_seq — the run-event FEED CURSOR on the intake mirror.

Phase 15.3 (plan 15.3-06, D-05). Adds ONE nullable column to the existing
``nestor.research_runs`` mirror table (0011):

  - ``event_seq`` BIGINT NULL — the highest ``run_event.seq`` the engine has
    written for this run, mirrored from ``RunMetrics.event_seq`` (plan 15.3-02)
    by the poll driver and re-emitted on the existing SSE frame
    (``read_latest_research_run_dict``).

What this column IS, and what it is NOT
---------------------------------------
It is a POSITION, never a payload. The SSE frame tells the page that events past
its own cursor exist; the page then fetches only that delta from the 15.3-07
proxy. A tick whose cursor did not move issues no request at all, and a run's
thousand-row history is never re-sent on a connection that already re-sends its
whole body on every change.

It is NOT a completion signal. ``completed_at`` answers "has this run ended";
``event_seq`` answers "how far has its feed got". The two are deliberately
decoupled — a ``parked`` run keeps advancing this cursor (see
``run_task.finalize_parked``), because the feed a parked run produced is exactly
the feed the operator reads before deciding whether to resume.

Why BIGINT
----------
Matches the source column 1:1: tribunal migration 0015 declares
``run_event.seq`` as ``sa.BigInteger()``. A narrower mirror would silently
saturate on a long-lived tenant, and a saturating cursor stops advancing —
which reads exactly like a run that stopped emitting.

Why nullable, with no server_default
------------------------------------
NULL is the honest value for a run that has produced NO events, and for every
row written before this revision (the live smoke intakes carry several). A
``server_default`` of ``0`` would be a LIE: it would claim the run has an event
stream positioned at the start, and the frontend would then issue a delta fetch
for a run that has no events at all. There is no backfill and no behaviour
change on legacy rows — the poll driver (not the DB) is the sole writer.

Why no index
------------
The column is READ only through the already-indexed single-row
``latest_for_intake`` lookup (``idx_research_runs_space_intake``) and WRITTEN
only by the poll driver's PATCH of that same row by primary key. Nothing filters
or orders by it, so an index would be pure write cost.

Which alembic line
------------------
The INTAKE ``nestor`` line (``backend/app/db/alembic/versions/``), whose head was
0012 (``0012_research_run_chain_bundle.py``) and whose version table is the
intake schema's own ``alembic_version``. This is NOT the TRIBUNAL line under
``tribunal/nestor_pulse_sdk/alembic/versions/``, which is separately at its own
0015 (``0015_run_events.py``, the table this cursor points INTO) and whose
version table is ``tribunal.tribunal_alembic_version`` — two schemas, two version
tables, two independent revision sequences (v1.1 roadmap decision, Pitfall 2).
Do not cross the two lines.

Like 0012 this is a PURE add-column: it touches NO RLS policy, grant, or index.
The new column inherits ``research_runs``' existing FORCE-RLS row policy and the
0011 grants (a column added to an already-granted, already-policied table needs
no re-grant / re-policy).

Live ``alembic upgrade`` is DEFERRED on the dev box (author-by-construction,
D-10 — no local Python, no Docker). The bar here is a clean ``alembic check``
(ORM metadata == this migration) plus the source/integration tests in Cloud
Build. When this IS applied, the proof is the literal
``Running upgrade 0012 -> 0013`` line in the migrate-job log; an ``exit(0)`` is
never proof.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "research_runs"


def upgrade() -> None:
    # ONE nullable column, NO server_default — the poll driver's mirror is the
    # sole writer; pre-existing rows stay NULL and unaffected.
    op.add_column(
        _TABLE,
        sa.Column("event_seq", sa.BigInteger(), nullable=True),
        schema=SCHEMA,
    )


def downgrade() -> None:
    op.drop_column(_TABLE, "event_seq", schema=SCHEMA)
