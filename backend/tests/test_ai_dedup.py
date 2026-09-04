"""COST-01 / D-23.1-04 — ONE running skill run per (intake, skill), enforced by the DB.

``23.1-CONTEXT.md`` § 3: ``ai_session.create_running_skill_run`` inserted a fresh
``running`` row on EVERY call — no active-run check, no idempotency key, no uniqueness
constraint. Double-clicking "Run skill" bought two paid Claude generations, and the
operator had no way to tell from the UI that they had paid twice.

D-23.1-04 is explicit about the mechanism: **a DB invariant, not an app check.** An
app-level "is one already running?" query races — two requests both read "no" and both
insert. So the arbiter is a PARTIAL UNIQUE INDEX (migration 0014) and the app's only job is
to translate the refusal into a readable ``409``.

Two halves, both BEHAVIOURAL:

  * **Migration half (8 cases)** — asserts against the LIVE database, never against the
    migration file's source text. ``test_research_runs_migration.py``'s AST/source style is
    deliberately NOT copied: two of its cases are red at HEAD precisely because they match
    prose instead of code (plan 23.1-14 fixes them). Here ``pg_indexes.indexdef`` and real
    INSERTs are the witnesses.

  * **Route half (7 cases)** — the second dispatch returns ``409`` with a readable detail
    that names the skill and leaks no driver or constraint string (T-23.1-51), the session
    is not poisoned by the failed flush (T-23.1-52), and the two legitimately-allowed cases
    (a different skill, and the same skill after the first finished) still return ``202``.

``test_upgrade_resolves_preexisting_duplicates`` is the case that decides whether the
production deploy works: ``CREATE UNIQUE INDEX`` ABORTS on a table that already violates
it, and nothing has constrained duplicate ``running`` rows since Phase 7 (D-23.1-12). It
seeds the violation at revision **0013** and then upgrades.

NO PROVIDER CALL: the route half no-ops the background handlers, so no Claude/OpenAI client
is ever constructed. The point under test is the SYNCHRONOUS dispatch step, which happens
strictly before the background task in every one of the six dispatching routes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# External deps — skip-clean when not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("alembic")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

from app.api import ai_routes as ai_routes_mod  # noqa: E402
from app.db import ai_session as ai_session_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
TABLE = "skill_runs"

#: The index name. It MUST match ``models/skill_run.py``'s ``__table_args__`` entry and the
#: 0014 migration BYTE-FOR-BYTE, or ``alembic check`` reports drift (and a later
#: autogenerate would try to re-create it).
INDEX_NAME = "uq_skill_runs_one_running_per_intake_skill"

#: The revision that introduces the index, and the one immediately below it.
REVISION = "0014"
PREVIOUS_REVISION = "0013"

# backend/tests/test_ai_dedup.py -> backend/ is parents[1]
_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Alembic helpers — drive the REAL migration against the container
# ---------------------------------------------------------------------------


def _alembic_cfg(engine):
    """An alembic ``Config`` bound to the test engine's DSN (mirrors conftest)."""
    from alembic.config import Config

    cfg = Config(str(_BACKEND / "alembic.ini"))
    # render_as_string(hide_password=False): str(engine.url) masks the password as
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
# Seeding helpers — every write is space-scoped (skill_runs is FORCE-RLS, 0009)
# ---------------------------------------------------------------------------


def _seed_space_and_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI dedup space"},
        )
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'submitted')"
            ),
            {"id": intake_id, "space_id": space_id},
        )


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )


def _insert_run(
    conn,
    set_space,
    space_id,
    intake_id,
    *,
    skill: str = "apply-intake-skill",
    status: str = "running",
    created_at: datetime | None = None,
    run_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """INSERT one ``skill_runs`` row on an already-open connection. Returns its id."""
    from sqlalchemy import text

    set_space(conn, space_id)
    rid = run_id or uuid.uuid4()
    params = {
        "id": rid,
        "space_id": space_id,
        "intake_id": intake_id,
        "skill": skill,
        "status": status,
    }
    if created_at is None:
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} (id, space_id, intake_id, skill, status) "
                "VALUES (:id, :space_id, :intake_id, :skill, :status)"
            ),
            params,
        )
    else:
        params["created_at"] = created_at
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(id, space_id, intake_id, skill, status, created_at) "
                "VALUES (:id, :space_id, :intake_id, :skill, :status, :created_at)"
            ),
            params,
        )
    return rid


def _runs_for(engine, set_space, space_id, intake_id, skill: str):
    """Every ``(id, status, error_message)`` for one (intake, skill), newest first."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT id, status, error_message FROM {SCHEMA}.{TABLE} "
                "WHERE intake_id = :iid AND skill = :skill "
                "ORDER BY created_at DESC, id DESC"
            ),
            {"iid": intake_id, "skill": skill},
        ).all()


# ===========================================================================
# THE decisive case — the migration must survive a database that already
# violates the invariant it introduces (D-23.1-12 / T-23.1-50).
# ===========================================================================


def test_upgrade_resolves_preexisting_duplicates(engine, set_space):
    """Seeded at revision 0013 with duplicate ``running`` rows, ``upgrade`` SUCCEEDS.

    THE case that decides whether the production deploy works. ``CREATE UNIQUE INDEX``
    aborts outright on a table that already violates it, and nothing has constrained
    duplicate ``running`` rows since Phase 7 — ``sweep_orphaned_skill_runs`` only runs at
    startup and only clears rows older than 30 minutes. So ``upgrade()`` must resolve the
    duplicates BEFORE creating the index: all but the NEWEST per ``(intake_id, skill)``
    group flipped to ``failed``, keeping the newest so an actually in-flight run is not
    killed by its own migration.

    Two groups are seeded, because production carries both shapes:

      * **group A — distinct ``created_at``**: the ordinary case; the newest survives.
      * **group B — IDENTICAL ``created_at``**: ``created_at`` has ``server_default
        now()``, and ``now()`` is fixed for a whole transaction — so two rows inserted in
        one tx carry the SAME timestamp. A resolution ordered on ``created_at`` alone
        leaves BOTH running and the index creation still aborts. The tie must break on a
        second, total-ordered column.

    Also proves the resolution is RLS-aware: ``skill_runs`` is FORCE-RLS (0009) and the
    migration runs as the table owner with no ``app.current_space_id`` GUC set, so a naive
    ``UPDATE`` matches ZERO rows — silently — and the index creation then aborts.
    """
    from alembic import command
    from sqlalchemy import text

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    cfg = _alembic_cfg(engine)
    now = datetime.now(timezone.utc)

    assert _current_revision(engine) is not None, (
        "the engine fixture should have run 'alembic upgrade head' already."
    )

    try:
        # --- Go back to 0013: the state production is in right now. ------------
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert _current_revision(engine) == PREVIOUS_REVISION, (
            f"expected the DB to sit at {PREVIOUS_REVISION} before seeding the violation."
        )

        _seed_space_and_intake(engine, set_space, space, intake_id)

        # group A — three running rows, distinct created_at. Newest must survive.
        with engine.begin() as conn:
            a_old = _insert_run(
                conn, set_space, space, intake_id,
                skill="apply-intake-skill", created_at=now - timedelta(hours=3),
            )
            a_mid = _insert_run(
                conn, set_space, space, intake_id,
                skill="apply-intake-skill", created_at=now - timedelta(hours=2),
            )
            a_new = _insert_run(
                conn, set_space, space, intake_id,
                skill="apply-intake-skill", created_at=now - timedelta(hours=1),
            )

        # group B — two running rows sharing ONE created_at (the server_default shape).
        tied_at = now - timedelta(minutes=30)
        with engine.begin() as conn:
            b_one = _insert_run(
                conn, set_space, space, intake_id,
                skill="context-pack", created_at=tied_at,
            )
            b_two = _insert_run(
                conn, set_space, space, intake_id,
                skill="context-pack", created_at=tied_at,
            )

        # Sanity: the violation really exists at 0013 (no index stopped these inserts).
        assert len(_runs_for(engine, set_space, space, intake_id, "apply-intake-skill")) == 3
        assert len(_runs_for(engine, set_space, space, intake_id, "context-pack")) == 2

        # --- The upgrade under test. It must NOT raise. ------------------------
        command.upgrade(cfg, "head")

        assert _current_revision(engine) is not None
        with engine.begin() as conn:
            idx = conn.execute(
                text(
                    "SELECT 1 FROM pg_indexes WHERE schemaname = :s "
                    "AND tablename = :t AND indexname = :n"
                ),
                {"s": SCHEMA, "t": TABLE, "n": INDEX_NAME},
            ).first()
        assert idx is not None, (
            f"{INDEX_NAME} must exist after the upgrade — if the upgrade silently "
            "skipped it the invariant is not enforced at all."
        )

        # group A: exactly one running, and it is the NEWEST.
        rows_a = _runs_for(engine, set_space, space, intake_id, "apply-intake-skill")
        running_a = [r for r in rows_a if r[1] == "running"]
        assert len(running_a) == 1, (
            f"group A must retain exactly one running row, got {len(running_a)}: {rows_a!r}"
        )
        assert running_a[0][0] == a_new, (
            "the surviving running row must be the NEWEST by created_at — killing the "
            "newest would abort an actually in-flight run with its own migration."
        )
        closed_a = {r[0]: r[2] for r in rows_a if r[1] == "failed"}
        assert set(closed_a) == {a_old, a_mid}, (
            f"the two older rows must be closed 'failed', got {closed_a!r}"
        )
        for rid, msg in closed_a.items():
            assert msg, f"closed row {rid} must carry a non-empty error_message."

        # group B: the created_at tie must still resolve to exactly one survivor.
        rows_b = _runs_for(engine, set_space, space, intake_id, "context-pack")
        running_b = [r for r in rows_b if r[1] == "running"]
        assert len(running_b) == 1, (
            "two rows sharing ONE created_at must still resolve to a single survivor — "
            "created_at has server_default now(), which is fixed per transaction, so "
            "ordering on it alone leaves both running and CREATE UNIQUE INDEX aborts. "
            f"got {len(running_b)}: {rows_b!r}"
        )
        assert running_b[0][0] in (b_one, b_two)
        closed_b = [r for r in rows_b if r[1] == "failed"]
        assert len(closed_b) == 1 and closed_b[0][2], (
            f"the losing tied row must be 'failed' with an error_message, got {rows_b!r}"
        )
    finally:
        _cleanup(engine, space)
        # Restore the session-scoped engine to head for every following test.
        command.upgrade(cfg, "head")


# ===========================================================================
# The index itself — asserted against the LIVE catalog, never the source text
# ===========================================================================


def test_partial_unique_index_exists_on_skill_runs(engine):
    """``pg_indexes`` carries the index, and its ``indexdef`` is UNIQUE *and* PARTIAL.

    Read from the database, not from the migration file: a source-text assertion passes
    on a migration that was written but never applied, and on prose in a docstring that
    merely mentions the words (the failure mode plan 23.1-14 is cleaning up in
    ``test_research_runs_migration.py``).
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = :t AND indexname = :n"
            ),
            {"s": SCHEMA, "t": TABLE, "n": INDEX_NAME},
        ).first()

    assert row is not None, (
        f"{INDEX_NAME} is absent from pg_indexes — the invariant is not enforced."
    )
    indexdef = row[0]
    upper = indexdef.upper()
    assert "UNIQUE" in upper, f"the index must be UNIQUE, got: {indexdef}"
    assert "WHERE" in upper, (
        "the index must be PARTIAL — a full UNIQUE (intake_id, skill) would forbid any "
        f"second run of a skill FOREVER, not just a concurrent one. got: {indexdef}"
    )
    assert "status" in indexdef and "running" in indexdef, (
        f"the partial predicate must select status = 'running', got: {indexdef}"
    )
    assert "intake_id" in indexdef and "skill" in indexdef, (
        f"the key must be (intake_id, skill), got: {indexdef}"
    )
    assert "space_id" not in indexdef, (
        "space_id must NOT be in the key — intake_id is already a globally unique "
        f"primary key, and widening the key would weaken the invariant. got: {indexdef}"
    )


def test_second_running_row_same_intake_and_skill_is_rejected(engine, set_space):
    """The DB — not the app — refuses the duplicate. This is the whole point (COST-01)."""
    from sqlalchemy.exc import IntegrityError

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")

        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")

        rows = _runs_for(engine, set_space, space, intake_id, "apply-intake-skill")
        assert len(rows) == 1, f"the rejected insert must leave exactly one row, got {rows!r}"
    finally:
        _cleanup(engine, space)


def test_running_row_for_a_different_skill_is_allowed(engine, set_space):
    """The invariant is per-(intake, SKILL) — two different skills may run together."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, skill="context-pack")

        assert len(_runs_for(engine, set_space, space, intake_id, "apply-intake-skill")) == 1
        assert len(_runs_for(engine, set_space, space, intake_id, "context-pack")) == 1
    finally:
        _cleanup(engine, space)


@pytest.mark.parametrize("terminal", ["succeeded", "failed"])
def test_second_running_row_after_the_first_finished_is_allowed(engine, set_space, terminal):
    """THE case that proves the index is PARTIAL and not a plain unique constraint.

    Once the first row leaves ``running`` the partial predicate no longer covers it, so
    the next run of the same skill inserts fine. A non-partial ``UNIQUE (intake_id,
    skill)`` would refuse this forever and would break the ordinary retry path — a bigger
    outage than the double-spend this plan exists to stop.
    """
    from sqlalchemy import text

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            first = _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")

        with engine.begin() as conn:
            set_space(conn, space)
            conn.execute(
                text(f"UPDATE {SCHEMA}.{TABLE} SET status = :st WHERE id = :id"),
                {"st": terminal, "id": first},
            )

        # Must NOT raise.
        with engine.begin() as conn:
            second = _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")

        rows = _runs_for(engine, set_space, space, intake_id, "apply-intake-skill")
        assert len(rows) == 2, f"expected both runs to survive, got {rows!r}"
        running = [r for r in rows if r[1] == "running"]
        assert len(running) == 1 and running[0][0] == second
    finally:
        _cleanup(engine, space)


def test_many_terminal_rows_for_one_intake_and_skill_coexist(engine, set_space):
    """Run HISTORY is unconstrained — only the in-flight slot is exclusive."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        for status in ("succeeded", "succeeded", "failed", "queued"):
            with engine.begin() as conn:
                _insert_run(
                    conn,
                    set_space,
                    space,
                    intake_id,
                    skill="apply-intake-skill",
                    status=status,
                )

        rows = _runs_for(engine, set_space, space, intake_id, "apply-intake-skill")
        assert len(rows) == 4, (
            "four non-running rows for one (intake, skill) must coexist — the index "
            f"covers only status='running'. got {rows!r}"
        )
    finally:
        _cleanup(engine, space)


def test_downgrade_removes_the_index_and_re_allows_duplicates(engine, set_space):
    """0014 -> 0013 drops the index and leaves no other trace; the upgrade re-applies.

    Exercises the migration in BOTH directions against a real database. After the
    downgrade a second ``running`` row inserts fine (the only thing that was ever
    stopping it was the index), and the re-upgrade restores the invariant.
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
            "downgrade must drop the index and NOTHING else — the other skill_runs "
            f"indexes must survive untouched. before={before!r} after={after!r}"
        )

        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")
        with engine.begin() as conn:
            _insert_run(conn, set_space, space, intake_id, skill="apply-intake-skill")
        assert len(_runs_for(engine, set_space, space, intake_id, "apply-intake-skill")) == 2, (
            "with the index gone the duplicate must be accepted again — otherwise "
            "something OTHER than the index was enforcing the invariant."
        )
        _cleanup(engine, space)

        command.upgrade(cfg, "head")
        assert _index_names() == before, "the re-upgrade must restore exactly the index."
    finally:
        _cleanup(engine, space)
        command.upgrade(cfg, "head")


def test_alembic_check_reports_no_drift(engine):
    """ORM metadata == the migrations: ``__table_args__`` and 0014 agree on the NAME.

    A name mismatch between the model's ``Index(...)`` and the migration's
    ``create_index(...)`` is invisible at runtime — both create *an* index — and only
    surfaces on a downgrade (which drops a name that is not there) or on the next
    autogenerate (which emits a duplicate CREATE). ``alembic check`` is what catches it.
    """
    from alembic import command
    from alembic.util.exc import AutogenerateDiffsDetected

    cfg = _alembic_cfg(engine)
    try:
        command.check(cfg)
    except AutogenerateDiffsDetected as exc:  # pragma: no cover - failure path
        pytest.fail(
            "alembic check found drift between Base.metadata and the migrations — "
            "most likely the ORM index name / predicate does not match 0014's:\n"
            f"{exc}"
        )
