"""0015 drop_skill_runs_started_at — remove the DEAD ``started_at`` column.

Phase 23.1 (plan 23.1-13, COST-01). Drops ONE nullable column from the existing
``nestor.skill_runs`` table (0001, extended by 0009/0014):

  - ``started_at`` TIMESTAMPTZ NULL — never written, by anything, ever.

Why it is dead, and how that was established
--------------------------------------------
``grep -rn "started_at" backend/app --include='*.py'`` at ``21f02b0`` returns eleven
hits. Every single one that WRITES the name writes ``research_runs.started_at``:
``research/run_task.py`` (the poll driver's ``_stamps``), ``db/stream_session.py``
(the SSE frame), ``db/models/research_runs.py`` (that table's own column), and
``research/tribunal_client.py`` (a docstring describing the ENGINE's run payload).
The only two ``skill_runs`` hits were this column's ``mapped_column`` and the
``SkillRunView`` docstring explaining that it is dead. Neither was a write.

``research_runs.started_at`` is a DIFFERENT column on a DIFFERENT table and is
load-bearing on both sides of the seam — the run page's elapsed clock reads it, and
the tribunal worker's fencing token IS a ``started_at`` value. This revision does not
touch it.

Why a permanently-NULL column is worth a migration
--------------------------------------------------
A nullable column that nothing writes is a standing invitation to write it. The next
reader who reaches for "when did this skill run start?" finds TWO candidates, picks the
one whose NAME says start, and ships a clock that reads 00:00 forever. That is not
hypothetical: ``intake_routes.py``'s ``SkillRunView`` carries an explicit note warning
the reader off this column precisely because the frontend once had no start timestamp
at all and synthesised one with ``new Date()``, restarting the elapsed clock on every
mount and every SSE event. Deleting the wrong candidate is a cheaper fix than a comment
that has to be read first.

``created_at`` is — and always was — the run's real start timestamp: Postgres ``now()``
stamped at INSERT by ``create_running_skill_run`` (``server_default=func.now()``, NOT
NULL). It is what ``GET /intakes/{id}/skill-runs`` projects and what ``useElapsed``
consumes. Nothing about the clock changes here.

The downgrade restores the COLUMN, not any data
-----------------------------------------------
``downgrade()`` re-adds ``started_at`` exactly as it was: TIMESTAMPTZ, NULLABLE, NO
``server_default``, NO index. That is a full reversal of the SCHEMA and it is stated
plainly that it is not a reversal of the DATA — a ``DROP COLUMN`` discards values
irrecoverably. It costs nothing here only because the column held no values to discard:
every row's ``started_at`` was NULL, in every environment, because no writer existed.
This is not a claim that column drops are generally lossless.

Why no RLS dance
----------------
``skill_runs`` carries ENABLE + FORCE ROW LEVEL SECURITY with the
``skill_runs_space_isolation`` policy (0009), and FORCE binds the table OWNER too —
which is the role alembic runs as. 0014 had to lift FORCE for the length of its
duplicate-resolution statement, because that statement was a cross-space ``UPDATE`` and
a row policy with no ``app.current_space_id`` GUC set matches ZERO rows SILENTLY.

That does not apply here. Row-level security governs DML — SELECT/INSERT/UPDATE/DELETE
row visibility. ``ALTER TABLE ... DROP COLUMN`` is DDL: it is authorised by table
ownership, and no row policy is consulted. So this revision runs a bare
``op.drop_column`` with no ``NO FORCE`` / ``FORCE`` bracket and no ``SET row_security``
(which, on a FORCE-RLS table, ERRORS rather than bypasses anyway). The claim is not
taken on faith: ``tests/test_ai_dedup.py::test_0015_drops_started_at_from_skill_runs``
reads ``information_schema.columns`` after a real upgrade, so a silently no-op'd drop
would leave the column visible and turn that test red.

Grants, policies and indexes
----------------------------
Following 0012's, 0013's and 0014's precedent: a column dropped from an
already-granted, already-policied table needs NO re-grant and NO re-policy. This
migration creates no policy, grants nothing, and revokes nothing.

It also disturbs no index. ``started_at`` was in no index key and in no partial
predicate, so 0014's ``uq_skill_runs_one_running_per_intake_skill`` — the partial unique
index that is the whole COST-01 double-click defence — is untouched by the drop. No
``CASCADE`` is used, deliberately: a plain ``DROP COLUMN`` fails loudly if some
dependent object ever did reference the column, where a ``CASCADE`` would take that
object down silently. ``test_0015_leaves_the_0014_unique_index_intact`` asserts the
index's survival against ``pg_indexes``.

Which alembic line
------------------
The INTAKE ``nestor`` line (``backend/app/db/alembic/versions/``), whose head was 0014
(``0014_skill_runs_single_running.py``, plan 23.1-12) and whose version table is the
default-schema ``public.alembic_version``. This is NOT the TRIBUNAL line under
``tribunal/nestor_pulse_sdk/alembic/versions/``, which numbers itself independently and
books into ``tribunal.tribunal_alembic_version`` — two schemas, two version tables, two
independent revision sequences (v1.1 roadmap decision, Pitfall 2).

The warning is not theoretical. Grepping this repository for ``0014`` already found TWO
migration files (the tribunal line has its own ``0014_run_liveness_and_reclaim.py``),
and the tribunal line sits past 0015 of its own. Neither line is "ahead" of the other.
Do not cross them.

Like 0014, this revision was applied FOR REAL on the dev box against
``pgvector/pgvector:pg16`` — 0013's "Live ``alembic upgrade`` is DEFERRED ... no local
Python, no Docker" sentence is no longer true and is not repeated here. Both directions
were executed by ``tests/test_ai_dedup.py``, which drives the real alembic commands and
asserts on ``information_schema`` and ``pg_indexes`` — never on this file's source text.
The proof of an application is the literal ``Running upgrade 0014 -> 0015`` line; an
``exit(0)`` is never proof.

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-04
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "skill_runs"
_COLUMN = "started_at"


def upgrade() -> None:
    # Plain DROP COLUMN — no CASCADE (fail loudly rather than take a dependent object
    # down silently) and no RLS bracket (DDL is not filtered by a row policy; see the
    # module docstring). ``started_at`` is in no index key and no partial predicate, so
    # 0014's uq_skill_runs_one_running_per_intake_skill is unaffected.
    op.drop_column(_TABLE, _COLUMN, schema=SCHEMA)


def downgrade() -> None:
    # Restore the column EXACTLY as it was: timestamptz, nullable, NO server_default, NO
    # index. A default here would invent a start timestamp for rows that never had one,
    # and NOT NULL would fail the downgrade outright on any table holding rows.
    #
    # This restores the SCHEMA, never the DATA — a DROP COLUMN discards values
    # irrecoverably. It happens to cost nothing only because the column held no values:
    # nothing ever wrote it. Do not read this as a lossless column drop in general.
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.DateTime(timezone=True), nullable=True),
        schema=SCHEMA,
    )
