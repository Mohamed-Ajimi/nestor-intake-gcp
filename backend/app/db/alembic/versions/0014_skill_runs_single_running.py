"""0014 skill_runs_single_running — ONE running skill run per (intake, skill).

Phase 23.1 (plan 23.1-12, COST-01 / D-23.1-04). Adds ONE partial unique index to the
existing ``nestor.skill_runs`` table (0001, extended by 0009):

  - ``uq_skill_runs_one_running_per_intake_skill``
    UNIQUE ``(intake_id, skill)`` WHERE ``status = 'running'``

plus a one-shot pre-flight that resolves the duplicate ``running`` rows the live database
already holds, because the index cannot be created while they exist.

What this invariant IS, and what it is NOT
------------------------------------------
It IS: at most one IN-FLIGHT run per intake per skill. A second dispatch while the first is
still ``running`` is refused by the database, and ``ai_session.create_running_skill_run``
translates that refusal into a ``409`` (``ActiveSkillRunExistsError`` ->
``ai_routes._dispatch_skill_run``).

It is NOT a rate limit — a caller may run the same skill again and again, as fast as each
one finishes. It does NOT dedupe ACROSS skills: ``apply-intake-skill`` and ``context-pack``
on the same intake are independent and may be in flight together. And it does NOT stop a
re-run after completion: once the first row leaves ``running``, the predicate no longer
covers it and the next insert is accepted. That last property is what the PARTIAL predicate
buys; a plain ``UNIQUE (intake_id, skill)`` would forbid it and would break the ordinary
retry path outright.

Why an index and not an app-level check
---------------------------------------
D-23.1-04 rejects the app check BY NAME: it races. Two requests arriving together both read
"nothing is running" and both insert, which is exactly the double-click that buys two paid
Claude generations. Only the database can arbitrate, because only the database serializes
the two inserts. The application layer's whole job here is to TRANSLATE the refusal, never
to pre-empt it — the ``except IntegrityError`` in ``ai_session.py`` is deliberately the only
place that knows about this index.

Why ``space_id`` is absent from the key
---------------------------------------
``intake_id`` is the UUID primary key of a space-owned table, so ``(intake_id, skill)`` is
already globally unambiguous. Adding ``space_id`` would WIDEN the key and thereby WEAKEN
the invariant (two spaces could then each hold a running row for the same intake id — an
impossible state that the narrow key rules out by construction).

Why the pre-flight, and why it runs FIRST
-----------------------------------------
``CREATE UNIQUE INDEX`` ABORTS if the table already violates the constraint. Nothing has
constrained duplicate ``running`` rows since Phase 7, and ``sweep_orphaned_skill_runs``
(``ai_session.py:195``) only runs at app startup and only clears rows older than 30
minutes — so duplicates can and very probably DO exist in production (D-23.1-12). Without
the pre-flight this migration fails the deploy.

The resolution keeps the NEWEST row of each ``(intake_id, skill)`` group running and closes
every older one as ``failed``, in the register of ``sweep_orphaned_skill_runs``' own
``error_message``. Keeping the newest matters: an actually in-flight run must not be killed
by its own migration.

Two details in that one statement are load-bearing:

1. **The tie-break is ``(created_at, id)``, not ``created_at`` alone.** ``created_at``
   carries ``server_default now()``, and ``now()`` is fixed for a whole transaction — two
   rows inserted in one transaction share a timestamp to the microsecond. Ordering on
   ``created_at`` alone would leave BOTH of them running and the index creation would still
   abort. The ``id`` component makes the order total, so exactly one row survives every
   group no matter how the duplicates were produced.

2. **RLS is temporarily unforced around it.** ``skill_runs`` carries ENABLE + FORCE ROW
   LEVEL SECURITY with the ``skill_runs_space_isolation`` policy (0009), and FORCE binds the
   table OWNER too — which is the role alembic runs as. With no ``app.current_space_id``
   GUC set, the policy evaluates to NULL and a plain cross-space ``UPDATE`` would match ZERO
   rows, SILENTLY, leaving every duplicate in place for ``CREATE UNIQUE INDEX`` to abort on.
   ``SET row_security = off`` is not the fix — for a FORCE-RLS table it makes the statement
   ERROR rather than bypass. So the migration drops FORCE for the length of the one
   statement and restores it immediately, inside the same (transactional) migration: if
   anything raises in between, the rollback restores FORCE with it. The policies themselves
   are never dropped, altered or re-created.

The statement is idempotent — after it runs, no group has more than one ``running`` row, so
a re-run matches nothing. It prints nothing beyond what alembic already logs.

Grants and policies
-------------------
Following 0012's and 0013's precedent: an index added to an already-granted,
already-policied table needs NO re-grant and NO re-policy. The new index is covered by
``skill_runs``' existing FORCE-RLS policies and the 0009 grants; this migration creates no
policy, grants nothing, and revokes nothing.

Which alembic line
------------------
The INTAKE ``nestor`` line (``backend/app/db/alembic/versions/``), whose head was 0013
(``0013_research_run_event_seq.py``) and whose version table is the default-schema
``alembic_version``. This is NOT the TRIBUNAL line under
``tribunal/nestor_pulse_sdk/alembic/versions/``, which numbers itself independently (it
sits at 0018 today and DEF-22-06 claims 0019 THERE) and books into
``tribunal.tribunal_alembic_version`` — two schemas, two version tables, two independent
revision sequences (v1.1 roadmap decision, Pitfall 2).

The warning is not theoretical: grepping this repository for ``0014`` finds TWO migration
files, because the tribunal line already has its own
(``0014_run_liveness_and_reclaim.py``, an unrelated change to unrelated tables). The two
are not versions of each other and neither is "ahead" of the other. Do not cross the
lines. Plan 23.1-13 takes 0015 on THIS line.

Unlike 0013, this revision was applied FOR REAL on the dev box: 0013's docstring line "Live
``alembic upgrade`` is DEFERRED ... no local Python, no Docker" is no longer true. Both
``upgrade`` and ``downgrade`` were executed against a real Postgres
(``pgvector/pgvector:pg16``) by ``tests/test_ai_dedup.py``, which drives the real alembic
commands and asserts on ``pg_indexes`` and on real INSERTs — never on this file's source
text. The proof of an application is the literal ``Running upgrade 0013 -> 0014`` line; an
``exit(0)`` is never proof.

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-04
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "skill_runs"

#: The index name. It MUST match ``app/db/models/skill_run.py``'s ``__table_args__`` entry
#: BYTE-FOR-BYTE, or ``alembic check`` reports drift and a later autogenerate emits a
#: duplicate CREATE. ``tests/test_ai_dedup.py`` pins the same literal a third time.
_INDEX = "uq_skill_runs_one_running_per_intake_skill"

#: The register of ``sweep_orphaned_skill_runs``' own ``error_message`` (ai_session.py:195):
#: short, operator-readable, and honest about WHY the row was closed.
_SUPERSEDED_MESSAGE = (
    "superseded by a newer run of the same skill; closed when the "
    "single-active-run invariant was introduced"
)


def upgrade() -> None:
    # ---------------------------------------------------------------- pre-flight
    # Resolve the duplicates the live table already holds, BEFORE creating the
    # index — CREATE UNIQUE INDEX aborts on a table that violates it (D-23.1-12).
    #
    # FORCE RLS (0009) binds the table owner, which is the role alembic runs as, and
    # no app.current_space_id GUC is set here — so this cross-space UPDATE has to run
    # with FORCE lifted or it matches zero rows silently. Lifted for exactly one
    # statement and restored on the next line; a raise in between rolls both back.
    op.execute(f"ALTER TABLE {SCHEMA}.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        # Idempotent: keeps the NEWEST running row per (intake_id, skill) and closes
        # every older one. The (created_at, id) tuple is a TOTAL order — created_at
        # alone ties for rows written in one transaction (server_default now()).
        op.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA}.{_TABLE} AS s
                   SET status = 'failed',
                       error_message = :msg,
                       completed_at = COALESCE(s.completed_at, now())
                 WHERE s.status = 'running'
                   AND EXISTS (
                        SELECT 1
                          FROM {SCHEMA}.{_TABLE} AS newer
                         WHERE newer.status = 'running'
                           AND newer.intake_id = s.intake_id
                           AND newer.skill = s.skill
                           AND (newer.created_at, newer.id) > (s.created_at, s.id)
                   )
                """
            ).bindparams(msg=_SUPERSEDED_MESSAGE)
        )
    finally:
        op.execute(f"ALTER TABLE {SCHEMA}.{_TABLE} FORCE ROW LEVEL SECURITY")

    # ---------------------------------------------------------------- the invariant
    # PARTIAL (WHERE status = 'running'): terminal rows are unconstrained, so a
    # re-run after completion — and a full history of past runs — stay legal.
    op.create_index(
        _INDEX,
        _TABLE,
        ["intake_id", "skill"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text("status = 'running'"),
    )


def downgrade() -> None:
    # Drop the index and NOTHING else. The pre-flight's duplicate resolution is NOT
    # un-done: those rows' pre-migration status is gone and there is no record of which
    # of them were genuinely in flight. Inventing a reversal would fabricate state —
    # admitting the one-way step is the honest option. Everything else this revision
    # touched (NO FORCE / FORCE) was already restored inside upgrade().
    op.drop_index(_INDEX, table_name=_TABLE, schema=SCHEMA)
