"""0016 research_runs_single_inflight — ONE in-flight research run per intake.

Phase 23.2 (plan 23.2-10, COST-01 / D-23.2-12 / F-05). Adds ONE partial unique index to
the existing ``nestor.research_runs`` table (0011, extended by 0012/0013):

  - ``uq_research_runs_one_inflight_per_intake``
    UNIQUE ``(intake_id)`` WHERE ``status IN ('queued', 'running', 'needs_report_spec')``

plus a one-shot pre-flight that resolves the duplicate in-flight rows the live database may
already hold, because the index cannot be created while they exist.

What this invariant IS, and what it is NOT
------------------------------------------
It IS: at most one IN-FLIGHT deep-research run per intake. A second trigger while the first
run is still alive is refused by the DATABASE, and ``trigger_research`` translates that
refusal into a ``409``.

It is NOT a rate limit — an operator may research the same intake again once the previous
run is done, subject to the app's own ``_MAX_ATTEMPTS = 3`` cap, which is a separate rule
this index neither implements nor weakens. It does NOT dedupe across INTAKES: two intakes
may research concurrently, which is the ordinary case. And it does NOT stop a retrigger
after a run reaches ``completed`` / ``completed_degraded`` / ``failed`` / ``cancelled`` /
``parked``: once the row leaves the predicate the next insert is accepted. That last
property is what the PARTIAL predicate buys; a plain ``UNIQUE (intake_id)`` would forbid it
and would break the 16-04 failure-card retry path and the Resume verb outright — a bigger
outage than the double-spend this revision exists to stop.

Why an index and not an app-level check
---------------------------------------
D-23.2-12 rejects the app check BY NAME: it races. ``trigger_research`` read the intake's
status and its prior runs on the request session and then opened a SEPARATE
``tenant_session`` that flipped the status and inserted the run row, so two concurrent
authorized requests both read the same ``prior``, both computed ``attempt = 1``, and both
inserted and dispatched — roughly $45 spent twice on a path that runs with
``NESTOR_TRIBUNAL_UNCAPPED=1``, with nothing in the UI to tell the operator. Only the
database can arbitrate, because only the database serializes the two inserts.

The application's job is to TRANSLATE the refusal, never to pre-empt it. The compare-and-
swap that ships with this revision (``patch_if`` on the status flip) is NOT a substitute:
on the RETRY path the handler sets ``new_status = "in_research"`` for an intake that is
ALREADY ``in_research``, so a CAS of ``expected={"status": "in_research"}`` matches for BOTH
concurrent callers — ``rowcount == 1`` twice. There, this index is the only arbiter. Do not
delete it as redundant.

The predicate is DERIVED, not guessed — and it has THREE literals
-----------------------------------------------------------------
``mirror_tick`` (``app/research/run_task.py``) writes ``metrics.get("status")`` VERBATIM
from the Tribunal engine, and the column is a plain ``String`` with no CHECK constraint
(verified: no ``CheckConstraint`` in the model, no ``ck_`` in 0011). The measured status
vocabulary is NINE values: ``queued``, ``running``, ``cancelled``, ``needs_input``,
``failed``, ``completed``, ``needs_report_spec``, ``completed_degraded``, ``parked``.

The predicate is the COMPLEMENT of the two app-level "this run is done with" sets:

  * ``_RETRYABLE_RUN_STATUSES = {"failed", "cancelled", "needs_input"}``
    (``app/api/research_routes.py``)
  * ``RESEARCH_TERMINAL = {"completed", "completed_degraded", "failed", "cancelled",
    "parked"}`` (``app/research/run_status.py``)
  * union = six statuses; complement over the nine = ``{queued, running,
    needs_report_spec}``.

``needs_report_spec`` is the one that is easy to miss, and leaving it out is the subtle
error: it is NOT retryable. A run sitting there is ALIVE, awaiting an operator's report
spec, and ``POST /report-spec`` re-queues that SAME run. A ``('queued','running')`` index
would admit a concurrent trigger in exactly that state, making this backstop DISAGREE with
the app rule it exists to enforce.

HONEST NOTE ON REACHABILITY — do not read this revision as closing a window that was open.
On the intake seam path ``needs_report_spec`` is documented as UNREACHABLE today:
``app/research/brief.py`` never appends the ``[INTERACTIVE_REPORT]`` marker and the seam
never calls ``/report-spec``, so "a seam run therefore can never reach needs_report_spec"
(``run_task.py`` calls it a residual response-Literal gap). Including it is DEFENCE-IN-DEPTH
against a design change, NOT a fix for a live hole. What keeps the two rules aligned if the
seam ever does opt in is the correspondence test in
``tests/test_research_dispatch_dedup.py``, which reads the DEPLOYED predicate out of
``pg_indexes`` and asserts every status outside it is retryable or terminal.

Why a POSITIVE ``IN (...)`` list and never ``NOT IN (terminal)``
----------------------------------------------------------------
Because statuses are written verbatim, the engine can start emitting a status this
repository has never heard of. Under a negated predicate that unknown status would count as
in-flight and would block that intake's triggers PERMANENTLY, with no operator remedy. The
positive list fails OPEN on an unknown status instead — which is the right direction here,
because the app-level 409 still sits in front of it, so failing open costs a race window
rather than a guarantee.

Why ``space_id`` is absent from the key
---------------------------------------
``intake_id`` is the UUID primary key of a space-owned table, so ``(intake_id)`` is already
globally unambiguous. Adding ``space_id`` would WIDEN the key and thereby WEAKEN the
invariant: two spaces could then each hold an in-flight run for the same intake id — an
impossible state that the narrow key rules out by construction. 0014 makes this same
argument for ``skill_runs``.

Why the pre-flight, and why it runs FIRST
-----------------------------------------
``CREATE UNIQUE INDEX`` ABORTS if the table already violates the constraint. NOTHING has
constrained duplicate in-flight ``research_runs`` rows since Phase 11 — the F-05 race has
been live that whole time and the trigger is a double-clickable button — so duplicates can
and plausibly DO exist in production. Without the pre-flight this migration fails the
deploy.

The resolution keeps the NEWEST in-flight row of each ``intake_id`` group and closes every
older one. Keeping the newest matters: an actually in-flight run must not be killed by its
own migration.

The closing status is ``cancelled``, not ``failed``, and the choice is deliberate: the row
was SUPERSEDED, not attempted-and-broken, and ``cancelled`` is already a member of
``_RETRYABLE_RUN_STATUSES``, so an operator whose row was closed here can simply retrigger.
``failed`` would be a claim about the run that is not true. The ``error_message`` is written
in the register of ``run_task``'s own finalize messages: short, operator-readable, and
honest about WHY the row was closed.

Two details in that one statement are load-bearing:

1. **The tie-break is ``(created_at, id)``, not ``created_at`` alone.** ``created_at``
   carries ``server_default now()``, and ``now()`` is fixed for a whole transaction — two
   rows inserted in one transaction share a timestamp to the microsecond. Ordering on
   ``created_at`` alone would leave BOTH in flight and the index creation would still abort.
   The ``id`` component makes the order total, so exactly one row survives every group no
   matter how the duplicates were produced.

2. **RLS is temporarily unforced around it.** ``research_runs`` carries ENABLE + FORCE ROW
   LEVEL SECURITY (0011) with its space-isolation policy, and FORCE binds the table OWNER
   too — which is the role alembic runs as. With no ``app.current_space_id`` GUC set, the
   policy evaluates to NULL and a plain cross-space ``UPDATE`` would match ZERO rows,
   SILENTLY, leaving every duplicate in place for ``CREATE UNIQUE INDEX`` to abort on.
   ``SET row_security = off`` is NOT the fix — for a FORCE-RLS table it makes the statement
   ERROR rather than bypass. So the migration drops FORCE for the length of the one
   statement and restores it in a ``finally:``, inside the same (transactional) migration:
   if anything raises in between, the rollback restores FORCE with it. The policies
   themselves are never dropped, altered or re-created.

The statement is idempotent — after it runs, no group has more than one in-flight row, so a
re-run matches nothing.

Grants and policies
-------------------
Following 0012's, 0013's and 0014's precedent: an index added to an already-granted,
already-policied table needs NO re-grant and NO re-policy. The new index is covered by
``research_runs``' existing FORCE-RLS policies and the 0011 grants; this migration creates
no policy, grants nothing, and revokes nothing.

Which alembic line
------------------
The INTAKE ``nestor`` line (``backend/app/db/alembic/versions/``), whose head was 0015
(``0015_drop_skill_runs_started_at.py``) and whose version table is the default-schema
``alembic_version``. This is NOT the TRIBUNAL line under
``tribunal/nestor_pulse_sdk/alembic/versions/``, which numbers itself independently, sits at
0018, and ALREADY HAS an unrelated ``0016_source_resolved_url.py`` — grepping this
repository for ``0016`` therefore finds TWO migration files. The two are not versions of
each other and neither is ahead of the other. Do not cross the lines.

Both directions were executed FOR REAL against a live Postgres
(``pgvector/pgvector:pg16``) by ``tests/test_research_dispatch_dedup.py``, which drives the
real alembic commands and asserts on ``pg_indexes`` and on real INSERTs — never on this
file's source text. The proof of an application is the literal ``Running upgrade 0015 ->
0016`` line; an ``exit(0)`` is never proof.

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
_TABLE = "research_runs"

#: The index name. It MUST match ``app/db/models/research_runs.py``'s ``__table_args__``
#: entry BYTE-FOR-BYTE, or the ORM and the database disagree: a downgrade drops a name that
#: is not there and a later autogenerate emits a duplicate CREATE.
#: ``tests/test_research_dispatch_dedup.py`` pins the same literal a third time and compares
#: the two declarations against the DEPLOYED ``pg_indexes.indexdef``.
_INDEX = "uq_research_runs_one_inflight_per_intake"

#: The IN-FLIGHT statuses — the complement of ``_RETRYABLE_RUN_STATUSES`` ∪
#: ``RESEARCH_TERMINAL`` over the nine measured statuses. POSITIVE by design (see the
#: docstring): an unknown future engine status must fail OPEN, never block an intake
#: forever. ONE source for the three values, so the pre-flight and the index cannot
#: disagree about what "in flight" means.
_INFLIGHT = ("queued", "running", "needs_report_spec")


def _inflight_predicate(column: str = "status") -> str:
    """``<column> IN ('queued', 'running', 'needs_report_spec')``.

    Built from :data:`_INFLIGHT` rather than by string-substituting a template, because
    ``"needs_report_spec"``-style literals and a column name called ``status`` are exactly
    the shape that makes a naive ``.replace("status", ...)`` rewrite the wrong token one
    refactor from now.
    """
    literals = ", ".join(f"'{value}'" for value in _INFLIGHT)
    return f"{column} IN ({literals})"

#: The register of ``run_task``'s own finalize messages: short, operator-readable, honest
#: about WHY the row was closed.
_SUPERSEDED_MESSAGE = (
    "superseded by a newer in-flight run; closed when the "
    "single-in-flight-run invariant was introduced"
)


def upgrade() -> None:
    # ---------------------------------------------------------------- pre-flight
    # Resolve the duplicates the live table may already hold, BEFORE creating the
    # index — CREATE UNIQUE INDEX aborts on a table that violates it, and nothing
    # has constrained duplicate in-flight research_runs rows since Phase 11.
    #
    # FORCE RLS (0011) binds the table owner, which is the role alembic runs as, and
    # no app.current_space_id GUC is set here — so this cross-space UPDATE has to run
    # with FORCE lifted or it matches zero rows silently. Lifted for exactly one
    # statement and restored in the finally; a raise in between rolls both back.
    op.execute(f"ALTER TABLE {SCHEMA}.{_TABLE} NO FORCE ROW LEVEL SECURITY")
    try:
        # Idempotent: keeps the NEWEST in-flight row per intake_id and closes every
        # older one as 'cancelled' (superseded, NOT attempted-and-broken — and
        # 'cancelled' is retryable, so the operator can retrigger). The
        # (created_at, id) tuple is a TOTAL order — created_at alone ties for rows
        # written in one transaction (server_default now()).
        op.execute(
            sa.text(
                f"""
                UPDATE {SCHEMA}.{_TABLE} AS r
                   SET status = 'cancelled',
                       error_message = :msg,
                       completed_at = COALESCE(r.completed_at, now())
                 WHERE {_inflight_predicate("r.status")}
                   AND EXISTS (
                        SELECT 1
                          FROM {SCHEMA}.{_TABLE} AS newer
                         WHERE {_inflight_predicate("newer.status")}
                           AND newer.intake_id = r.intake_id
                           AND (newer.created_at, newer.id) > (r.created_at, r.id)
                   )
                """
            ).bindparams(msg=_SUPERSEDED_MESSAGE)
        )
    finally:
        op.execute(f"ALTER TABLE {SCHEMA}.{_TABLE} FORCE ROW LEVEL SECURITY")

    # ---------------------------------------------------------------- the invariant
    # PARTIAL: terminal rows are unconstrained, so the full run history and every
    # legitimate retrigger (after failed/cancelled/needs_input, and the Resume verb
    # after a park) stay legal.
    op.create_index(
        _INDEX,
        _TABLE,
        ["intake_id"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(_inflight_predicate()),
    )


def downgrade() -> None:
    # Drop the index and NOTHING else. The pre-flight's duplicate resolution is NOT
    # un-done: those rows' pre-migration status is gone and there is no record of which
    # of them were genuinely in flight. Inventing a reversal would fabricate state —
    # admitting the one-way step is the honest option. Everything else this revision
    # touched (NO FORCE / FORCE) was already restored inside upgrade().
    op.drop_index(_INDEX, table_name=_TABLE, schema=SCHEMA)
