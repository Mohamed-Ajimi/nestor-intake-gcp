"""COST-01 / D-23.2-12 (F-05) — ONE in-flight research run per intake, enforced by the DB.

``23.2-CONTEXT.md`` § 6: ``trigger_research`` read the intake's status and its prior runs on
``repo.session``, then opened a SEPARATE ``tenant_session`` that patched the status
UNCONDITIONALLY and inserted a run row. ``research_runs`` carried three plain indexes and
none was unique. Two concurrent authorized requests therefore both read the same ``prior``,
both computed ``attempt = 1``, and both inserted and dispatched — roughly $45 spent twice,
with nothing in the UI to tell the operator they had paid for the same research twice.

D-23.2-12 mandates THREE changes and says plainly that no one of them is sufficient:

  1. **Migration 0016** — a PARTIAL UNIQUE index on ``research_runs (intake_id)``
     WHERE ``status IN ('queued','running','needs_report_spec')``.
  2. **A compare-and-swap on the status flip** (``patch_if``), expecting the ``old_status``
     that was read; ``rowcount == 0`` -> 409.
  3. **``attempt`` computed INSIDE the write transaction**, not from the earlier read.

Why all three, concretely — this is the paragraph that stops a later reader deleting one:

  * The CAS does NOT cover the RETRY path. When ``old_status == "in_research"`` the handler
    sets ``new_status = "in_research"``, so a CAS of ``expected={"status": "in_research"}``
    setting ``status="in_research"`` matches for BOTH concurrent callers — ``rowcount == 1``
    twice. On that path ONLY the unique index arbitrates
    (``test_duplicate_run_through_the_retry_path_returns_409``).
  * The index alone would leave the intake row flipped by the loser before its insert
    failed, and would leave ``attempt`` wrong.
  * The in-tx ``attempt`` alone changes nothing about who dispatches.

Two halves, both BEHAVIOURAL — the style of ``test_ai_dedup.py`` (23.1-12), deliberately
NOT the source-text style of ``test_research_runs_migration.py``:

  * **Migration half** — every assertion is against the LIVE database
    (``pg_indexes.indexdef``, real INSERTs, real ``alembic upgrade`` / ``downgrade``),
    never against this repository's migration source text.
  * **Route half** — the DB's refusal and the CAS's refusal are both translated into a
    readable ``409``, and a refused trigger leaves NO run row, NO audit row and schedules
    NO poll driver. That last negative is the one that costs $45 when it is false.

ZERO PROVIDER SPEND: the route half drives ``fake_tribunal_client``; no test in this file
reaches the real Tribunal seam, and the refusal cases assert that ``create_run`` was never
called at all.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# External deps — skip-clean when not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("alembic")
pytest.importorskip("httpx")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")

from app.api import research_routes as research_mod  # noqa: E402
from app.db.models.research_runs import ResearchRun  # noqa: E402
from app.research.run_status import RESEARCH_TERMINAL  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
TABLE = "research_runs"

#: The index name. It MUST match ``models/research_runs.py``'s ``__table_args__`` entry and
#: migration 0016 BYTE-FOR-BYTE — a mismatch is invisible at runtime (both create *an*
#: index) and only surfaces on a downgrade or the next autogenerate.
INDEX_NAME = "uq_research_runs_one_inflight_per_intake"

#: The revision that introduces the index, and the one immediately below it.
REVISION = "0016"
PREVIOUS_REVISION = "0015"

#: The THREE in-flight statuses the partial predicate must cover. Derived, not guessed —
#: see ``test_index_predicate_and_the_app_retry_rule_cannot_drift``.
INFLIGHT = frozenset({"queued", "running", "needs_report_spec"})

#: Every status that can land in ``research_runs.status``. ``mirror_tick``
#: (``app/research/run_task.py``, the ``"status": metrics.get("status")`` line) writes the
#: engine's value VERBATIM and the column is a plain ``String`` with no CHECK constraint, so
#: this set is a MEASURED vocabulary, not a declared enum. Sources:
#:   * ``app/research/run_status.py`` — ``RESEARCH_SUCCESS`` gives ``completed`` +
#:     ``completed_degraded``; ``RESEARCH_TERMINAL`` adds ``failed``/``cancelled``/``parked``.
#:   * ``app/api/research_routes.py`` — ``_RETRYABLE_RUN_STATUSES`` gives ``needs_input``.
#:   * ``app/research/run_task.py`` — the engine's ``queued`` / ``running`` /
#:     ``needs_report_spec`` ticks, mirrored verbatim.
ALL_STATUSES = frozenset(
    {
        "queued",
        "running",
        "cancelled",
        "needs_input",
        "failed",
        "completed",
        "needs_report_spec",
        "completed_degraded",
        "parked",
    }
)

#: The five statuses in which a run is DONE and the in-flight slot is free again. Kept as a
#: tuple (not a set) so the sweep below is order-stable and its count is assertable.
TERMINALS = ("completed", "completed_degraded", "failed", "cancelled", "parked")

# backend/tests/test_research_dispatch_dedup.py -> backend/ is parents[1]
_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Alembic helpers — drive the REAL migration against the container
# ---------------------------------------------------------------------------


def _alembic_cfg(engine):
    """An alembic ``Config`` bound to the test engine's DSN (mirrors conftest)."""
    from alembic.config import Config

    cfg = Config(str(_BACKEND / "alembic.ini"))
    # render_as_string(hide_password=False): str(engine.url) masks the password as the
    # literal "***", which alembic would then use as the real password (conftest:172).
    cfg.set_main_option(
        "sqlalchemy.url", engine.url.render_as_string(hide_password=False)
    )
    return cfg


#: Alembic's own bookkeeping table. env.py sets no ``version_table_schema``, so it lands in
#: the connection's default schema (``public``) — NOT in ``nestor``.
_VERSION_TABLE = "public.alembic_version"


def _current_revision(engine) -> str | None:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text(f"SELECT version_num FROM {_VERSION_TABLE}")).first()
    return None if row is None else row[0]


# ---------------------------------------------------------------------------
# Seeding helpers — every write is space-scoped (research_runs is FORCE-RLS, 0011)
# ---------------------------------------------------------------------------


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Research dedup space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="decomposed") -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
                "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status), :name)"
            ),
            {"id": intake_id, "space_id": space_id, "status": status, "name": "Acme"},
        )


def _seed_space_and_intake(
    engine, set_space, space_id, intake_id, status="decomposed"
) -> None:
    _seed_space(engine, space_id)
    _seed_intake(engine, set_space, space_id, intake_id, status=status)


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )
    # audit_log is deliberately NOT space-cascaded (0006, D-07) — the trail outlives its
    # subject — so its rows have to be cleared explicitly.
    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
        )


def _insert_run(
    conn,
    set_space,
    space_id,
    intake_id,
    *,
    status: str = "queued",
    attempt: int = 1,
    created_at: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """INSERT one ``research_runs`` row on an already-open connection. Returns its id."""
    from sqlalchemy import text

    set_space(conn, space_id)
    rid = run_id or uuid.uuid4()
    params = {
        "id": rid,
        "space_id": space_id,
        "intake_id": intake_id,
        "status": status,
        "attempt": attempt,
    }
    cols = "id, space_id, intake_id, status, attempt"
    vals = ":id, :space_id, :intake_id, :status, :attempt"
    if created_at is not None:
        params["created_at"] = created_at
        cols += ", created_at"
        vals += ", :created_at"
    conn.execute(text(f"INSERT INTO {SCHEMA}.{TABLE} ({cols}) VALUES ({vals})"), params)
    return rid


def _runs_for(engine, set_space, space_id, intake_id):
    """Every ``(id, status, error_message, attempt)`` for one intake, newest first."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT id, status, error_message, attempt FROM {SCHEMA}.{TABLE} "
                "WHERE intake_id = :iid ORDER BY created_at DESC, id DESC"
            ),
            {"iid": intake_id},
        ).all()


def _indexdef(engine) -> str | None:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = :t AND indexname = :n"
            ),
            {"s": SCHEMA, "t": TABLE, "n": INDEX_NAME},
        ).first()
    return None if row is None else row[0]


def _statuses_in(predicate: str) -> frozenset[str]:
    """Every single-quoted literal in a predicate string.

    Postgres renders the deployed predicate as
    ``WHERE ((status)::text = ANY ((ARRAY['queued'::character varying, ...])::text[]))`` —
    the ``::character varying`` casts are NOT quoted, so the quoted literals are exactly the
    status values. The ORM's own ``text("status IN ('queued', ...)")`` yields the same set,
    which is what makes the two comparable without pinning either one's rendering.
    """
    return frozenset(re.findall(r"'([^']*)'", predicate))


def _where_of(indexdef: str) -> str:
    upper = indexdef.upper()
    assert "WHERE" in upper, f"the index must be PARTIAL, got: {indexdef}"
    return indexdef[upper.index("WHERE") :]


# ===========================================================================
# THE decisive case — the migration must survive a database that already
# violates the invariant it introduces (T-23.2-10-04 / T-23.2-10-05).
# ===========================================================================


def test_upgrade_resolves_preexisting_duplicates(engine, set_space):
    """Seeded at revision 0015 with duplicate in-flight rows, ``upgrade`` SUCCEEDS.

    THE case that decides whether the production deploy works. ``CREATE UNIQUE INDEX``
    aborts outright on a table that already violates it, and NOTHING has constrained
    duplicate ``queued``/``running`` rows on ``research_runs`` since Phase 11 — the F-05
    race has been live that whole time. So ``upgrade()`` must resolve the duplicates BEFORE
    creating the index: all but the NEWEST per ``intake_id`` closed, keeping the newest so
    an actually in-flight run is not killed by its own migration.

    Two groups are seeded, because production carries both shapes:

      * **group A — two ``queued`` rows, distinct ``created_at``**: the ordinary
        double-click; the newest survives.
      * **group B — one ``queued`` + one ``running``, IDENTICAL ``created_at``**: two
        things at once. First, the predicate covers the PAIR, not each literal separately —
        a ``WHERE status = 'queued'`` index would have passed this. Second, ``created_at``
        has ``server_default now()`` and ``now()`` is fixed for a whole transaction, so two
        rows written in one tx share a timestamp to the microsecond; a resolution ordered
        on ``created_at`` alone leaves BOTH in flight and the index creation still aborts.

    Also proves the resolution is RLS-aware: ``research_runs`` is ENABLE + FORCE ROW LEVEL
    SECURITY (0011) and the migration runs as the table OWNER with no ``app.current_space_id``
    GUC set, so a naive cross-space ``UPDATE`` matches ZERO rows — silently — and the index
    creation then aborts. (``SET row_security = off`` is not the fix: on a FORCE-RLS table
    it ERRORS rather than bypassing.)
    """
    from alembic import command

    space = uuid.uuid4()
    intake_a = uuid.uuid4()
    intake_b = uuid.uuid4()
    cfg = _alembic_cfg(engine)
    now = datetime.now(timezone.utc)

    assert _current_revision(engine) is not None, (
        "the engine fixture should have run 'alembic upgrade head' already."
    )

    try:
        # --- Go back to 0015: the state production is in right now. ------------
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert _current_revision(engine) == PREVIOUS_REVISION, (
            f"expected the DB to sit at {PREVIOUS_REVISION} before seeding the violation."
        )

        _seed_space_and_intake(engine, set_space, space, intake_a, status="in_research")
        _seed_intake(engine, set_space, space, intake_b, status="in_research")

        # group A — two queued rows, distinct created_at. Newest must survive.
        with engine.begin() as conn:
            a_old = _insert_run(
                conn,
                set_space,
                space,
                intake_a,
                status="queued",
                attempt=1,
                created_at=now - timedelta(hours=2),
            )
            a_new = _insert_run(
                conn,
                set_space,
                space,
                intake_a,
                status="queued",
                attempt=2,
                created_at=now - timedelta(hours=1),
            )

        # group B — queued + running sharing ONE created_at (the server_default shape).
        tied_at = now - timedelta(minutes=30)
        with engine.begin() as conn:
            b_one = _insert_run(
                conn, set_space, space, intake_b, status="queued", created_at=tied_at
            )
            b_two = _insert_run(
                conn,
                set_space,
                space,
                intake_b,
                status="running",
                attempt=2,
                created_at=tied_at,
            )

        # Sanity: the violation really exists at 0015 (no index stopped these inserts).
        assert len(_runs_for(engine, set_space, space, intake_a)) == 2
        assert len(_runs_for(engine, set_space, space, intake_b)) == 2

        # --- The upgrade under test. It must NOT raise. ------------------------
        command.upgrade(cfg, "head")

        assert _indexdef(engine) is not None, (
            f"{INDEX_NAME} must exist after the upgrade — if the upgrade silently skipped "
            "it the invariant is not enforced at all."
        )

        # group A: exactly one in-flight row, and it is the NEWEST.
        rows_a = _runs_for(engine, set_space, space, intake_a)
        inflight_a = [r for r in rows_a if r[1] in INFLIGHT]
        assert len(inflight_a) == 1, (
            f"group A must retain exactly one in-flight row, got {len(inflight_a)}: "
            f"{rows_a!r}"
        )
        assert inflight_a[0][0] == a_new, (
            "the surviving in-flight row must be the NEWEST — killing the newest would "
            "abort an actually in-flight ~$45 run with its own migration."
        )
        closed_a = [r for r in rows_a if r[0] == a_old]
        assert len(closed_a) == 1
        assert closed_a[0][1] in RESEARCH_TERMINAL, (
            "a superseded row must be closed with an honest TERMINAL status, got "
            f"{closed_a[0][1]!r}"
        )
        assert closed_a[0][2], "the closed row must carry a non-empty error_message."

        # group B: the created_at tie must still resolve to exactly one survivor, and the
        # queued/running PAIR must have been seen as a conflict at all.
        rows_b = _runs_for(engine, set_space, space, intake_b)
        inflight_b = [r for r in rows_b if r[1] in INFLIGHT]
        assert len(inflight_b) == 1, (
            "a queued row and a running row for ONE intake are a conflict — the predicate "
            "covers the pair, not each literal separately. And two rows sharing ONE "
            "created_at must still resolve to a single survivor: created_at has "
            "server_default now(), fixed per transaction, so ordering on it alone leaves "
            f"both in flight and CREATE UNIQUE INDEX aborts. got {len(inflight_b)}: "
            f"{rows_b!r}"
        )
        assert inflight_b[0][0] in (b_one, b_two)
        closed_b = [r for r in rows_b if r[0] != inflight_b[0][0]]
        assert len(closed_b) == 1
        assert closed_b[0][1] in RESEARCH_TERMINAL and closed_b[0][2], (
            f"the losing tied row must be closed terminal with an error_message, got "
            f"{rows_b!r}"
        )
    finally:
        _cleanup(engine, space)
        # Restore the session-scoped engine to head for every following test.
        command.upgrade(cfg, "head")


# ===========================================================================
# The index itself — asserted against the LIVE catalog, never the source text
# ===========================================================================


def test_partial_unique_index_exists_on_research_runs(engine):
    """``pg_indexes`` carries the index, and its ``indexdef`` is UNIQUE *and* PARTIAL.

    Read from the database, not from the migration file: a source-text assertion passes on
    a migration that was written but never applied, and on prose in a docstring that merely
    mentions the words.
    """
    indexdef = _indexdef(engine)
    assert indexdef is not None, (
        f"{INDEX_NAME} is absent from pg_indexes — the invariant is not enforced."
    )
    upper = indexdef.upper()
    assert "UNIQUE" in upper, f"the index must be UNIQUE, got: {indexdef}"
    assert "WHERE" in upper, (
        "the index must be PARTIAL — a plain UNIQUE (intake_id) would forbid EVERY "
        "retrigger forever, not just a concurrent one, and would break the retry path "
        f"and the Resume verb outright. got: {indexdef}"
    )
    assert _statuses_in(_where_of(indexdef)) == INFLIGHT, (
        "the partial predicate must name exactly queued, running AND needs_report_spec. "
        "needs_report_spec is NOT in _RETRYABLE_RUN_STATUSES, so a run sitting there is "
        "ALIVE and a concurrent trigger must be refused — a ('queued','running') index "
        f"would let one through in exactly that state. got: {indexdef}"
    )
    assert "intake_id" in indexdef, f"the key must be (intake_id), got: {indexdef}"
    assert "space_id" not in indexdef, (
        "space_id must NOT be in the key — intake_id is already the globally unique "
        "primary key of a space-owned table, and widening the key would WEAKEN the "
        "invariant (two spaces could each hold an in-flight run for the same intake id). "
        f"got: {indexdef}"
    )


def test_predicate_is_a_positive_list_not_a_negated_terminal_set(engine):
    """T-23.2-10-10 — an unknown FUTURE status must fail OPEN, never block an intake.

    ``mirror_tick`` writes ``metrics.get("status")`` verbatim and the column has no CHECK
    constraint, so the engine can start emitting a status this repository has never heard
    of. Under a ``NOT IN (terminal)`` predicate that unknown status would be treated as
    in-flight and would block that intake's triggers PERMANENTLY, with no operator remedy.
    A positive ``IN (...)`` list fails open instead — and the app-level 409 still sits in
    front of it, so failing open costs a race window, not a guarantee.
    """
    indexdef = _indexdef(engine)
    assert indexdef is not None
    upper = indexdef.upper()
    assert "NOT IN" not in upper, f"the predicate must not be negated, got: {indexdef}"
    assert "<> ALL" not in upper, (
        "`<> ALL (ARRAY[...])` is how Postgres renders a NOT IN list — the predicate must "
        f"be the POSITIVE `= ANY` form. got: {indexdef}"
    )
    assert "= ANY" in upper or " IN " in upper, (
        f"expected a positive membership predicate, got: {indexdef}"
    )


def test_index_predicate_and_the_app_retry_rule_cannot_drift(engine):
    """T-23.2-10-11 — every status OUTSIDE the predicate is retryable or terminal.

    The index exists to back up ONE app rule: ``trigger_research`` refuses a new trigger on
    an ``in_research`` intake unless the latest run's status is in
    ``_RETRYABLE_RUN_STATUSES``. If a future engine status is added to one side only, the
    database backstop silently stops matching the rule it exists to enforce — and nothing
    else in the suite would notice.

    So: read the predicate off the DEPLOYED index (not off a literal in this test), and
    check every status the vocabulary allows but the predicate excludes against the app's
    OWN constants. ``len(ALL_STATUSES) == 9`` is the anti-vacuity guard; ``checked == 6``
    is the size of the COMPLEMENT (9 - 3), not of the vocabulary.
    """
    indexdef = _indexdef(engine)
    assert indexdef is not None
    predicate = _statuses_in(_where_of(indexdef))

    assert len(ALL_STATUSES) == 9, (
        "anti-vacuity: the measured status vocabulary is NINE values. If a status was "
        f"added or removed, re-derive the predicate — do not edit this number. got "
        f"{sorted(ALL_STATUSES)!r}"
    )
    assert predicate <= ALL_STATUSES, (
        "the index predicate names a status outside the known vocabulary: "
        f"{sorted(predicate - ALL_STATUSES)!r}"
    )

    retryable = research_mod._RETRYABLE_RUN_STATUSES
    checked = 0
    for status in sorted(ALL_STATUSES - predicate):
        assert status in retryable or status in RESEARCH_TERMINAL, (
            f"{status!r} is outside the index predicate, so the database treats it as a "
            "FREE in-flight slot — but the app treats it as neither retryable nor "
            "terminal, so trigger_research would 409 it. The two rules have drifted: "
            "either add it to the predicate (it is alive) or to _RETRYABLE_RUN_STATUSES / "
            "RESEARCH_TERMINAL (it is done)."
        )
        checked += 1
    assert checked == 6, (
        "the complement of the 3-status predicate over the 9-status vocabulary is SIX. "
        f"got {checked} — the predicate or the vocabulary changed without this test."
    )


def test_orm_declaration_matches_the_deployed_index(engine):
    """The ORM entry and the DEPLOYED index agree — name, uniqueness, key and predicate.

    A name mismatch between ``models/research_runs.py``'s ``Index(...)`` and 0016's
    ``create_index(...)`` is invisible at runtime — both create *an* index — and surfaces
    only on a downgrade (which drops a name that is not there) or on the next autogenerate
    (which emits a duplicate CREATE).

    ⚠ This is deliberately NOT ``alembic check``. Two reasons, both measured:

      * The CLI form fails on EVERY tree, correct or not: ``alembic.ini``'s
        ``sqlalchemy.url`` is empty and ``env.py`` falls back to an unset ``DATABASE_URL``,
        so ``python -m alembic check`` raises ``ArgumentError: Could not parse SQLAlchemy
        URL``. A command that always fails is not a gate.
      * Even bound to a live DSN, alembic's postgresql ``compare_indexes`` compares the
        unique flag and the index EXPRESSIONS — it never looks at ``postgresql_where``. So
        a predicate that drifted from the migration would pass ``alembic check`` silently.
        This test is what closes that specific hole.
    """
    indexdef = _indexdef(engine)
    assert indexdef is not None

    orm_index = {ix.name: ix for ix in ResearchRun.__table__.indexes}.get(INDEX_NAME)
    assert orm_index is not None, (
        f"the ORM declares no index named {INDEX_NAME!r}, but the database has one. The "
        "name must match BYTE-FOR-BYTE. declared: "
        f"{sorted(ix.name for ix in ResearchRun.__table__.indexes)!r}"
    )
    assert orm_index.unique is True, "the ORM entry must be unique=True."
    assert [c.name for c in orm_index.columns] == ["intake_id"], (
        "the ORM key must be exactly (intake_id), got "
        f"{[c.name for c in orm_index.columns]!r}"
    )

    orm_where = orm_index.dialect_options["postgresql"].get("where")
    assert orm_where is not None, (
        "the ORM entry must declare postgresql_where — without it the ORM claims a FULL "
        "unique index, which would forbid every retrigger."
    )
    assert _statuses_in(str(orm_where)) == _statuses_in(_where_of(indexdef)), (
        "the ORM predicate and the deployed predicate name different statuses. "
        f"orm={str(orm_where)!r} deployed={indexdef!r}"
    )


def test_second_queued_row_for_the_same_intake_is_rejected(engine, set_space):
    """The DB — not the app — refuses the duplicate. This is the whole point (F-05)."""
    from sqlalchemy.exc import IntegrityError

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="queued")

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_run(conn, set_space, space, intake_id, status="queued")

        rows = _runs_for(engine, set_space, space, intake_id)
        assert len(rows) == 1, (
            f"the rejected insert must leave exactly one row, got {rows!r}"
        )
    finally:
        _cleanup(engine, space)


def test_queued_plus_running_for_the_same_intake_is_rejected(engine, set_space):
    """The predicate covers the PAIR, not each literal separately.

    This is the case a ``WHERE status = 'queued'`` predicate would pass, and it is the case
    that matters: a run transitions ``queued -> running`` on its first mirror tick, so the
    second trigger of a double-click very often arrives when the first row is already
    ``running``.
    """
    from sqlalchemy.exc import IntegrityError

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="running")

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_run(conn, set_space, space, intake_id, status="queued", attempt=2)

        assert len(_runs_for(engine, set_space, space, intake_id)) == 1
    finally:
        _cleanup(engine, space)


def test_needs_report_spec_also_holds_the_in_flight_slot(engine, set_space):
    """A run parked at ``needs_report_spec`` is ALIVE — a concurrent trigger is refused.

    ``needs_report_spec`` is NOT in ``_RETRYABLE_RUN_STATUSES``: the run is waiting for an
    operator's report spec and ``POST /report-spec`` re-queues that SAME run. Including it
    is what keeps the DB backstop and the app rule in agreement.

    HONEST NOTE ON REACHABILITY: on the intake seam path this state is documented as
    UNREACHABLE today. ``app/research/brief.py`` never appends the ``[INTERACTIVE_REPORT]``
    marker and the seam never calls ``/report-spec``, so "a seam run therefore can never
    reach needs_report_spec". Covering it is DEFENCE-IN-DEPTH against a future design
    change, NOT the closing of a window that is open today. This test seeds the status
    directly for that reason.
    """
    from sqlalchemy.exc import IntegrityError

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="needs_report_spec")

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_run(conn, set_space, space, intake_id, status="queued", attempt=2)

        assert len(_runs_for(engine, set_space, space, intake_id)) == 1
    finally:
        _cleanup(engine, space)


def test_queued_row_for_a_different_intake_is_allowed(engine, set_space):
    """The invariant is per-INTAKE — two intakes may research concurrently."""
    space = uuid.uuid4()
    intake_a = uuid.uuid4()
    intake_b = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_a)
        _seed_intake(engine, set_space, space, intake_b)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_a, status="queued")
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_b, status="queued")

        assert len(_runs_for(engine, set_space, space, intake_a)) == 1
        assert len(_runs_for(engine, set_space, space, intake_b)) == 1
    finally:
        _cleanup(engine, space)


def test_a_new_run_after_every_terminal_status_is_allowed(engine, set_space):
    """THE case that proves the index is PARTIAL — swept over all FIVE terminal statuses.

    Once the first row leaves the in-flight set the predicate no longer covers it, so the
    next run inserts fine. A non-partial ``UNIQUE (intake_id)`` would refuse this forever:
    it would break ``test_retrigger_after_dead_run_202``, the whole 16-04 failure-card retry
    path, and the Resume verb after a park — a far bigger outage than the double-spend this
    plan exists to stop.

    Written as ONE test with a counter rather than a ``parametrize``, because the assertion
    that matters (``checked == 5``) is about the SWEEP being complete, and a parametrized
    case that silently stopped being generated would not fail.
    """
    from sqlalchemy import text

    space = uuid.uuid4()
    checked = 0
    try:
        _seed_space(engine, space)
        intakes = []
        for _ in TERMINALS:
            iid = uuid.uuid4()
            _seed_intake(engine, set_space, space, iid)
            intakes.append(iid)

        for terminal, intake_id in zip(TERMINALS, intakes):
            with engine.begin() as conn:
                first = _insert_run(conn, set_space, space, intake_id, status="queued")
            with engine.begin() as conn:
                set_space(conn, space)
                conn.execute(
                    text(f"UPDATE {SCHEMA}.{TABLE} SET status = :st WHERE id = :id"),
                    {"st": terminal, "id": first},
                )
            # Must NOT raise.
            with engine.begin() as conn:
                second = _insert_run(
                    conn, set_space, space, intake_id, status="queued", attempt=2
                )

            rows = _runs_for(engine, set_space, space, intake_id)
            assert len(rows) == 2, (
                f"after {terminal!r} the retrigger must be accepted, got {rows!r}"
            )
            inflight = [r for r in rows if r[1] in INFLIGHT]
            assert len(inflight) == 1 and inflight[0][0] == second
            checked += 1

        assert checked == 5, (
            "all FIVE terminal statuses must have been swept (completed, "
            f"completed_degraded, failed, cancelled, parked) — got {checked}."
        )
    finally:
        _cleanup(engine, space)


def test_many_terminal_rows_for_one_intake_coexist(engine, set_space):
    """Run HISTORY is unconstrained — only the in-flight slot is exclusive."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        for n, status in enumerate(("failed", "cancelled", "completed"), start=1):
            with engine.begin() as conn:
                _insert_run(conn, set_space, space, intake_id, status=status, attempt=n)

        rows = _runs_for(engine, set_space, space, intake_id)
        assert len(rows) == 3, (
            "three terminal rows for one intake must coexist — the index covers only the "
            f"in-flight statuses. got {rows!r}"
        )
    finally:
        _cleanup(engine, space)


def test_downgrade_removes_the_index_and_re_allows_duplicates(engine, set_space):
    """0016 -> 0015 drops the index and leaves no other trace; the re-upgrade restores it.

    Exercises the migration in BOTH directions against a real database. After the downgrade
    a second in-flight row inserts fine (the only thing that was ever stopping it was the
    index), which also proves nothing ELSE — no trigger, no constraint — was quietly added.
    """
    from alembic import command
    from sqlalchemy import text

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    cfg = _alembic_cfg(engine)

    def _index_names():
        with engine.begin() as conn:
            return {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = :s AND tablename = :t"
                    ),
                    {"s": SCHEMA, "t": TABLE},
                ).all()
            }

    before = _index_names()
    assert INDEX_NAME in before

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert _current_revision(engine) == PREVIOUS_REVISION

        after = _index_names()
        assert INDEX_NAME not in after, "downgrade must drop the index."
        assert after == before - {INDEX_NAME}, (
            "downgrade must drop the index and NOTHING else — the other research_runs "
            f"indexes must survive untouched. before={before!r} after={after!r}"
        )

        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="queued")
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="running", attempt=2)
        assert len(_runs_for(engine, set_space, space, intake_id)) == 2, (
            "with the index gone the duplicate must be accepted again — otherwise "
            "something OTHER than the index was enforcing the invariant."
        )
        _cleanup(engine, space)

        command.upgrade(cfg, "head")
        assert _index_names() == before, "the re-upgrade must restore exactly the index."
    finally:
        _cleanup(engine, space)
        command.upgrade(cfg, "head")


# ===========================================================================
# Route half — the two refusals, translated into readable 409s
# ===========================================================================

#: Substrings that must NEVER reach a client. A leaked constraint or driver name is
#: information disclosure (T-23.2-10-07) and reads to the operator like a crash rather than
#: like "that research is already going".
_FORBIDDEN_IN_DETAIL = (
    "IntegrityError",
    "UniqueViolation",
    "psycopg",
    "pg8000",
    "sqlalchemy",
    "SQL:",
    "23505",
    "duplicate key",
    INDEX_NAME,
)

#: Same literal the other research suites use, so the app_superadmin role's password stays
#: stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


def _superadmin() -> "Identity":
    """``trigger_research`` is superadmin-gated (D-23.1-16) — a user gets 404."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engines(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(
        ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
    )


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (the D-05 two-engine routing).

    Shape copied verbatim from ``test_research_routes.superadmin_engine``: a connect-as
    engine, not ``SET ROLE``, so the 0003/0011 bypass policies match the way they do in
    production.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER ROLE app_superadmin WITH LOGIN PASSWORD "
                f"'{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(
        username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD
    )
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


def _build_app():
    """Mount ``research_router`` under ``protected_router`` (mirrors app/main.py wiring)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_decomposition_and_questions(engine, set_space, space_id, intake_id) -> None:
    """One decomposition + two prioritized questions, so the brief is never empty.

    Without these the handler short-circuits on the empty-brief 422 and never reaches the
    write transaction this half exists to test.
    """
    from sqlalchemy import text

    decomp_id = uuid.uuid4()
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.decompositions (id, space_id, intake_id, summary) "
                "VALUES (:id, :space_id, :intake_id, :summary)"
            ),
            {
                "id": decomp_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "summary": "Marktverkenning voor Acme.",
            },
        )
        for prio, qtext in ((2, "Wat is de marktomvang?"), (1, "Wie zijn de concurrenten?")):
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.research_questions "
                    "(id, space_id, intake_id, decomposition_id, question_text, priority) "
                    "VALUES (:id, :space_id, :intake_id, :decomp_id, :qtext, :prio)"
                ),
                {
                    "id": uuid.uuid4(),
                    "space_id": space_id,
                    "intake_id": intake_id,
                    "decomp_id": decomp_id,
                    "qtext": qtext,
                    "prio": prio,
                },
            )


def _read_intake_status(engine, set_space, space_id, intake_id) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _set_intake_status(engine, set_space, space_id, intake_id, status) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"UPDATE {SCHEMA}.intakes "
                "SET status = CAST(:st AS nestor.intake_status) WHERE id = :id"
            ),
            {"st": status, "id": intake_id},
        )


def _count_audit_rows(engine, intake_id) -> int:
    """``audit_log`` is deliberately NOT RLS-scoped (0006, D-07) — a plain count is safe."""
    from sqlalchemy import text

    with engine.begin() as conn:
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.audit_log WHERE target = :t"),
            {"t": str(intake_id)},
        ).scalar_one()


def _interleave_before_the_write(monkeypatch, hook) -> None:
    """Run ``hook()`` between the handler's READ and its write transaction.

    ``trigger_research`` reads the intake and its prior runs on ``repo.session``, then calls
    ``read_brief_inputs`` to compose the brief, and only THEN opens the ``tenant_session``
    that flips the status and inserts the run row. Wrapping ``read_brief_inputs`` therefore
    lands the hook squarely inside the read-then-write window that F-05 lives in — which
    makes the race DETERMINISTIC instead of a sleep-and-hope.

    The wrapper delegates to the real function afterwards, so the brief the handler
    composes is the real one and no behaviour is stubbed out.
    """
    real = research_mod.read_brief_inputs

    def _wrapped(identity, intake_id, *args, **kwargs):
        hook()
        return real(identity, intake_id, *args, **kwargs)

    monkeypatch.setattr(research_mod, "read_brief_inputs", _wrapped)


def _assert_detail_is_readable(response) -> str:
    """The 409 body is an operator-readable sentence that leaks no database internals."""
    body = response.json()
    detail = body.get("detail")
    assert isinstance(detail, str) and detail, (
        "the 409 must carry a plain-string detail (the frontend transport reads it "
        f"verbatim), got {body!r}"
    )
    raw = response.text
    for needle in _FORBIDDEN_IN_DETAIL:
        assert needle.lower() not in raw.lower(), (
            f"the 409 body leaks {needle!r} — a driver/constraint string is information "
            f"disclosure and reads like a crash. body={raw!r}"
        )
    return detail


def test_cas_refuses_a_stale_flip_and_writes_nothing(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """The status changed between the read and the write -> 409, and NOTHING was written.

    This is the CAS half of D-23.2-12. Before it, the handler patched the status
    UNCONDITIONALLY, so the loser of the race flipped an intake that the winner had already
    flipped, wrote an audit row claiming a transition that had already happened, inserted a
    second run row and scheduled a second ~$45 driver.

    THREE negatives are asserted, not one. A 409 that still dispatched the poll driver is
    the failure that costs the money — the status code alone would not have caught it.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id, status="decomposed")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        # The concurrent winner: it flips the intake after this request read 'decomposed'
        # and before this request writes.
        _interleave_before_the_write(
            monkeypatch,
            lambda: _set_intake_status(
                engine, set_space, space, intake_id, "in_research"
            ),
        )

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )

        assert resp.status_code == 409, (
            "a flip whose precondition no longer holds must be refused — got "
            f"{resp.status_code} ({resp.text!r})"
        )
        _assert_detail_is_readable(resp)

        assert _runs_for(engine, set_space, space, intake_id) == [], (
            "the refused request must insert NO research_runs row."
        )
        assert _count_audit_rows(engine, intake_id) == 0, (
            "the refused request must write NO audit row — an audit row for a transition "
            "that did not happen is a false trail."
        )
        assert not fake_tribunal_client["create_run"], (
            "the refused request must schedule NO poll driver. This is the assertion that "
            "is worth ~$45; a 409 that still dispatched would satisfy the status code and "
            "spend the money anyway."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_duplicate_run_through_the_retry_path_returns_409(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """THE case that proves the index is not redundant with the CAS (T-23.2-10-02).

    The real retry race: an ``in_research`` intake whose latest run is ``failed`` is legally
    retriggerable, and TWO concurrent triggers both pass that app rule. Both then CAS
    ``in_research -> in_research``, which MATCHES for both — ``rowcount == 1`` twice. The
    compare-and-swap cannot arbitrate here, by construction. Only the unique index can.

    The interleave inserts the winner's ``queued`` row inside the loser's read-then-write
    window, so the loser's own insert is the one the index refuses. The refusal must surface
    as a 409 (a 500 would mean the ``IntegrityError`` escaped untranslated) and must leave
    the intake exactly as it was.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id, status="in_research")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        # The dead run that makes the retrigger legal at the app level.
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="failed", attempt=1)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        def _concurrent_winner():
            with engine.begin() as conn:
                _insert_run(
                    conn, set_space, space, intake_id, status="queued", attempt=2
                )

        _interleave_before_the_write(monkeypatch, _concurrent_winner)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )

        assert resp.status_code == 409, (
            "the second concurrent retrigger must be a 409 — a 500 means the "
            "IntegrityError escaped untranslated, a 202 means it dispatched a duplicate "
            f"~$45 run. got {resp.status_code} ({resp.text!r})"
        )
        _assert_detail_is_readable(resp)

        rows = _runs_for(engine, set_space, space, intake_id)
        assert len(rows) == 2, (
            "exactly the failed row and the winner's queued row must remain — the loser's "
            f"insert must have been rolled back. got {rows!r}"
        )
        assert len([r for r in rows if r[1] in INFLIGHT]) == 1
        assert _read_intake_status(engine, set_space, space, intake_id) == "in_research", (
            "the refused request must leave the intake status untouched."
        )
        assert not fake_tribunal_client["create_run"], (
            "the refused request must schedule NO poll driver."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_attempt_is_computed_inside_the_write_transaction(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """``attempt`` counts the runs that exist AT WRITE TIME, not at read time.

    A PROOF, not a reading: the handler reads ``prior == []`` (so the old code computed
    ``attempt = 1``), and the interleave then inserts one terminal run inside the
    read-then-write window. The inserted row must carry ``attempt = 2``.

    Without the in-tx recount two concurrent triggers both stamp ``attempt = 1`` and the
    audit trail claims one attempt where two were paid for.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id, status="decomposed")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        def _concurrent_run_appears():
            # TERMINAL, so the index still admits this request's own insert — the point
            # under test is the COUNT, not the refusal.
            with engine.begin() as conn:
                _insert_run(
                    conn, set_space, space, intake_id, status="failed", attempt=1
                )

        _interleave_before_the_write(monkeypatch, _concurrent_run_appears)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )

        assert resp.status_code == 202, (
            f"expected 202, got {resp.status_code} ({resp.text!r})"
        )
        new_run_id = uuid.UUID(resp.json()["research_run_id"])
        rows = {r[0]: r for r in _runs_for(engine, set_space, space, intake_id)}
        assert len(rows) == 2
        assert rows[new_run_id][3] == 2, (
            "attempt must be recomputed INSIDE the write transaction. The handler read "
            "zero prior runs, so a read-time computation yields 1; one run existed by the "
            f"time the row was written, so the answer is 2. got {rows[new_run_id][3]}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_ordinary_retrigger_after_a_dead_run_still_stamps_attempt_2(
    engine, set_space, monkeypatch, superadmin_engine, fake_tribunal_client, fake_resend
):
    """The uncontended retry path is unchanged: one prior run -> ``attempt = 2``, 202.

    The counterweight to the refusal cases. Moving ``attempt`` into the write transaction
    must not shift the ordinary numbering by one in either direction, and the legitimate
    retrigger after a dead run must still be ACCEPTED — the index is partial precisely so
    that it is.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id, status="in_research")
        _seed_decomposition_and_questions(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, status="failed", attempt=1)
        _patch_engines(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/research",
            headers={"Authorization": "Bearer overridden"},
        )

        assert resp.status_code == 202, (
            f"expected 202, got {resp.status_code} ({resp.text!r})"
        )
        new_run_id = uuid.UUID(resp.json()["research_run_id"])
        rows = {r[0]: r for r in _runs_for(engine, set_space, space, intake_id)}
        assert len(rows) == 2, f"the retrigger must insert a second row, got {rows!r}"
        assert rows[new_run_id][3] == 2, (
            f"the second attempt must be numbered 2, got {rows[new_run_id][3]}"
        )
        assert fake_tribunal_client["create_run"], (
            "the accepted retrigger must reach create_run — the index must not have "
            "swallowed a legitimate retry."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_the_gate_still_precedes_the_repo_in_the_signature():
    """CONTEXT § 11 trap 3, as a machine-checked residue.

    In ``trigger_research`` the superadmin gate MUST be declared ABOVE ``get_tenant_repo``:
    FastAPI resolves the signature in order, so with the gate below, a null-space caller
    gets ``get_tenant_repo``'s 403 ("No space — not authorized") instead of the
    existence-hidden 404 — an existence ORACLE on the one verb whose existence is worth the
    most to learn.

    Green at HEAD by construction (this plan adds no dependency and does not touch the
    signature) — it is a regression tripwire, not a gate. The behavioural denial proof lives
    in ``test_research_trigger_gate.py``, including its ordering-mutation case, which is
    what actually demonstrates the oracle.
    """
    import inspect

    from app.auth.gates import superadmin_gate

    params = list(inspect.signature(research_mod.trigger_research).parameters)
    assert "identity" in params and "repo" in params, (
        f"the signature lost a parameter this test relies on: {params!r}"
    )
    assert params.index("identity") < params.index("repo"), (
        "the superadmin gate must stay ABOVE get_tenant_repo — any new Depends goes "
        f"AFTER the gate. got {params!r}"
    )

    gate_param = inspect.signature(research_mod.trigger_research).parameters["identity"]
    assert getattr(gate_param.default, "dependency", None) is superadmin_gate, (
        "the first-resolved dependency must be the shared superadmin gate itself, not a "
        f"look-alike. got {gate_param.default!r}"
    )
