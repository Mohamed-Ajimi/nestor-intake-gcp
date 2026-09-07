"""0017 research_runs_reconciler_columns — the four facts a stateless sweep needs.

Phase 23.3 (plan 23.3-04, COST-01 / DEF-23.2-03). Adds FOUR nullable columns and ONE
partial index to ``nestor.research_runs``. It ships NO reconciler — it only makes one
possible, and it is a strict no-op for every existing code path.

The defect this revision serves
-------------------------------
``run_poll_driver`` (``backend/app/research/run_task.py``) is a ``while True`` inside a
FastAPI ``BackgroundTask`` with no wall-clock cap. If that nestor-api instance recycles — a
deploy, a scale event, Cloud Run's own lifecycle — the driver dies SILENTLY: the engine
keeps executing and spending (~$25-45 per run, measured $24.78 on ``fb9484dd``, with
``NESTOR_TRIBUNAL_UNCAPPED=1`` live on the worker), ``research_runs`` is never mirrored or
finalized, and NOTHING sweeps it. 23.3-CONTEXT.md § 8 scopes the fix as a stateless
RECONCILER inside nestor-api rather than a dispatch rewrite. A stateless reconciler needs
four things this table does not have.

1. WHO — ``acting_user_id`` / ``acting_email``
----------------------------------------------
The Tribunal seam REQUIRES non-empty ``X-Acting-User-Id`` and ``X-Acting-User-Email`` and
answers 400 without them (``tribunal/nestor_pulse_sdk/auth/internal_caller.py``), because
the D-05 acting-user attribution is a hard legal constraint on a FROZEN audit chain. Today
the actor is derived in-process from the live request ``Identity``
(``run_task.load_trigger_context``), which a sweep does not have and cannot obtain. A
reconciler that invented a system actor would corrupt exactly the attribution the audit
chain exists to carry, so the row must carry the ORIGINAL human's and the sweep must replay
it. ``acting_email`` has a second consumer: the D-10 completion / park mail, which otherwise
has nobody to write to when a run is finished by a sweep instead of by its own driver.

``Identity.email`` is ``str | None``. A superadmin token without an email stores NULL here,
deliberately — NOT ``''`` and NOT a placeholder address. Plan 05's reconciler must SKIP such
a row rather than call a seam that will answer 400. A fabricated actor on a legally
load-bearing chain is worse than a skipped sweep.

2. LIVENESS — ``driver_heartbeat_at``
-------------------------------------
There is NO ``updated_at`` on this table (0011 gives ``created_at`` / ``started_at`` /
``completed_at``, and 0012/0013 add no clock). Orphan detection keyed on ``created_at``
would reproduce the D-E defect this project has already paid for: ``created_at`` and
``started_at`` are stamped ONCE and never move, so "35 minutes since that timestamp" says
nothing about whether the process is alive — a live 35-minute provider long-poll
(``PROVIDER_TIMEOUT_S``) is indistinguishable from a process that died 35 minutes ago, and
the designed response to a dead process is to re-run at FULL COST.

A heartbeat is the honest signal because it MOVES. ``mirror_tick`` already runs every
~3 s (``POLL_SECONDS``), and it stamps this column UNCONDITIONALLY — it is the driver's
assertion about ITSELF, never a value mirrored from the seam.

3. A LEASE — ``reconcile_lease_until``
--------------------------------------
nestor-api runs ``maxScale=4``. Two instances mirroring the same run concurrently is the
defect this phase must not introduce (§ 8). A sweep stamps this when it claims a row so a
second instance skips it. A LEASE, not a lock: it EXPIRES, so a sweep that dies mid-flight
cannot strand the row forever — which is the same failure mode this whole revision exists
to end, and it would be absurd to reintroduce it one layer up.

Why NULLABLE with NO server default
-----------------------------------
``research_runs`` holds paid, IN-FLIGHT rows. Four nullable columns with no default is a
metadata-only ``ADD COLUMN`` in Postgres 11+ — no table rewrite, no long ACCESS EXCLUSIVE
hold, nothing for a live run to trip over. A NOT NULL column would fail outright on the
existing rows; a defaulted one would rewrite the table. NULL also carries a true meaning
here: "this run predates the reconciler", which is precisely what plan 05 must observe and
skip. Following 0012's / 0013's / 0016's precedent, columns and an index added to an
already-granted, already-policied table need NO re-grant and NO re-policy: they inherit
``research_runs``' 0011 FORCE-RLS space-isolation policy and its 0011 grants. This
revision creates no policy, grants nothing and revokes nothing.

The orphan-candidate index, and its non-obvious half
----------------------------------------------------
``ix_research_runs_orphan_candidates`` is a PARTIAL btree on ``driver_heartbeat_at`` WHERE
``status IN ('queued', 'running', 'needs_report_spec')`` — the SAME three literals as
``uq_research_runs_one_inflight_per_intake`` (0016), sourced from the same tuple below so
the two cannot disagree about what "in flight" means.

The predicate is a POSITIVE ``IN (...)`` and never a ``NOT IN (terminal)``, for the same
documented reason 0016 gives: ``mirror_tick`` writes the engine's status VERBATIM into a
plain ``String`` column with no CHECK constraint, so the engine can start emitting a status
this repository has never heard of. Under a negated predicate that unknown status would
count as a candidate and the sweep would treat a perfectly healthy run as an ORPHAN — and
the response to an orphan is to take it over. The positive list fails OPEN instead: an
unknown status is simply not a candidate. **That is the non-obvious half: here, failing
open costs a missed sweep; failing closed costs a live run being seized.**

``needs_report_spec`` is the literal that is easy to drop and the one that matters most to
include: a run sitting there is ALIVE, awaiting an operator's report spec. It is documented
as UNREACHABLE on the seam path today (``app/research/brief.py`` never opts into the
interactive-report gate) — it is here as defence-in-depth against a design change, exactly
as 0016 argues, NOT as a fix for a live hole.

⚠ ``alembic check`` will NOT protect this predicate. Its postgresql ``compare_indexes``
inspects the unique flag and the expressions only and never looks at ``postgresql_where``,
so a predicate that drifted from the model passes it SILENTLY (DEF-23.2-15; the same note
sits above the sibling index in ``app/db/models/research_runs.py``). That is why
``tests/test_research_run_reconciler_columns.py`` pins the index NAME and the three
predicate literals against the DEPLOYED ``pg_indexes.indexdef``, never against this file's
source text.

Which alembic line
------------------
The INTAKE ``nestor`` line (``backend/app/db/alembic/versions/``), whose head was 0016 and
whose version table is the default-schema ``alembic_version``. This is NOT the TRIBUNAL
line under ``tribunal/nestor_pulse_sdk/alembic/versions/``, which numbers itself
independently — grepping this repository for a four-digit revision therefore finds TWO
files. Do not cross the lines. ``0019`` is deliberately NOT taken here: ROADMAP Phase 24
records that DEF-22-06 already claims it for the write-side source-identity fix.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-07
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "research_runs"

#: The orphan-candidate index name. It MUST match ``app/db/models/research_runs.py``'s
#: ``__table_args__`` entry BYTE-FOR-BYTE, or the ORM and the database disagree: a
#: downgrade drops a name that is not there and a later autogenerate emits a duplicate
#: CREATE. ``tests/test_research_run_reconciler_columns.py`` pins the same literal a third
#: time and compares it against the DEPLOYED ``pg_indexes.indexdef``.
_ORPHAN_INDEX = "ix_research_runs_orphan_candidates"

#: The IN-FLIGHT statuses — the SAME three 0016's ``_INFLIGHT`` carries, restated here
#: because a migration must be readable standalone (importing another revision's private
#: constant would couple two files alembic is free to run in isolation). POSITIVE by
#: design: an unknown future engine status must NOT be swept as an orphan.
_INFLIGHT = ("queued", "running", "needs_report_spec")

#: The four columns, in the order they are added and the reverse of the order they are
#: dropped. ONE source, so upgrade and downgrade cannot drift.
_COLUMNS = (
    "acting_user_id",
    "acting_email",
    "driver_heartbeat_at",
    "reconcile_lease_until",
)


def _inflight_predicate(column: str = "status") -> str:
    """``<column> IN ('queued', 'running', 'needs_report_spec')``.

    Built from :data:`_INFLIGHT` rather than by string-substituting a template, for the
    reason 0016 gives: a ``needs_report_spec``-shaped literal and a column named ``status``
    are exactly the shape that makes a naive ``.replace("status", ...)`` rewrite the wrong
    token one refactor from now.
    """
    literals = ", ".join(f"'{value}'" for value in _INFLIGHT)
    return f"{column} IN ({literals})"


def upgrade() -> None:
    # ---------------------------------------------------------------- WHO
    # The acting human, persisted so a recovery path REPLAYS the original D-05
    # attribution across the seam instead of inventing a system actor. NULLABLE: a
    # superadmin token without an email stores NULL and plan 05 skips that row.
    op.add_column(
        _TABLE,
        sa.Column(
            "acting_user_id",
            sa.String(),
            nullable=True,
            comment=(
                "Identity.uid of the human who triggered or resumed this run. Persisted so "
                "a stateless reconciler can REPLAY the original actor's D-05 attribution "
                "across the Tribunal seam (which requires a non-empty X-Acting-User-Id and "
                "answers 400 without one) rather than inventing a system actor on a frozen "
                "audit chain. NULL = the run predates 0017."
            ),
        ),
        schema=SCHEMA,
    )
    op.add_column(
        _TABLE,
        sa.Column(
            "acting_email",
            sa.String(),
            nullable=True,
            comment=(
                "The same human's address. Two consumers: the seam's required "
                "X-Acting-User-Email header, and the D-10 completion / park mail, which "
                "otherwise has nobody to write to when a run is finished by a sweep "
                "instead of by its own driver. NULL is DELIBERATE when Identity.email is "
                "None — never '' and never a placeholder address; a fabricated actor on a "
                "legally load-bearing chain is worse than a skipped sweep."
            ),
        ),
        schema=SCHEMA,
    )

    # ---------------------------------------------------------------- LIVENESS
    op.add_column(
        _TABLE,
        sa.Column(
            "driver_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "LIVENESS. Bumped by run_task.mirror_tick on EVERY tick (~3s), "
                "unconditionally — the driver's assertion about ITSELF, never a value "
                "mirrored from the seam. MUST NOT be confused with created_at or "
                "started_at: those are stamped ONCE and never move, which is exactly why "
                "the D-E defect happened — a live 35-minute provider long-poll was "
                "indistinguishable from a process that died 35 minutes ago, and the "
                "designed response to a dead process is to re-run at full cost. A liveness "
                "signal is the one that MOVES."
            ),
        ),
        schema=SCHEMA,
    )

    # ---------------------------------------------------------------- THE LEASE
    op.add_column(
        _TABLE,
        sa.Column(
            "reconcile_lease_until",
            sa.DateTime(timezone=True),
            nullable=True,
            comment=(
                "Set by a sweep when it CLAIMS this row, so a second nestor-api instance "
                "(maxScale=4) skips it. A LEASE, not a lock: it EXPIRES, so a sweep that "
                "dies mid-flight cannot strand the row — which is the very failure mode "
                "the reconciler exists to end."
            ),
        ),
        schema=SCHEMA,
    )

    # ---------------------------------------------------------------- the scan
    # PARTIAL btree on the liveness column over the three in-flight statuses, so the
    # orphan-candidate scan never seq-scans a table of terminal, paid runs.
    #
    # POSITIVE IN (...), never NOT IN (terminal): statuses are written VERBATIM from the
    # engine into a String column with no CHECK, so an unknown FUTURE status must fail
    # OPEN — simply not a candidate — instead of being swept as an orphan. Failing open
    # here costs a missed sweep; failing closed would cost a LIVE run being seized.
    op.create_index(
        _ORPHAN_INDEX,
        _TABLE,
        ["driver_heartbeat_at"],
        unique=False,
        schema=SCHEMA,
        postgresql_where=sa.text(_inflight_predicate()),
    )


def downgrade() -> None:
    # Index first (it depends on driver_heartbeat_at), then the columns in reverse.
    # Fully reversible: unlike 0016's pre-flight, this revision changes no row's data, so
    # there is nothing here that a downgrade would have to fabricate.
    op.drop_index(_ORPHAN_INDEX, table_name=_TABLE, schema=SCHEMA)
    for column in reversed(_COLUMNS):
        op.drop_column(_TABLE, column, schema=SCHEMA)
