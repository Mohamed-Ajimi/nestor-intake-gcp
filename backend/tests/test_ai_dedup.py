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
    """ORM metadata == the migrations, checked against HEAD — so 0014 AND 0015.

    A name mismatch between the model's ``Index(...)`` and the migration's
    ``create_index(...)`` is invisible at runtime — both create *an* index — and only
    surfaces on a downgrade (which drops a name that is not there) or on the next
    autogenerate (which emits a duplicate CREATE). ``alembic check`` is what catches it.

    It is also the ONLY gate on plan 23.1-13's half of the pair: 0015 drops
    ``skill_runs.started_at`` and ``models/skill_run.py`` removes the matching
    ``mapped_column``. Do either one without the other and this goes red — a column in
    the ORM but not the DB, or in the DB but not the ORM, is exactly the drift
    ``command.check`` reports. That is why the 23.1-13 section below does not restate it.
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


# ===========================================================================
# Route half — the DB's refusal, translated into a readable 409
# ===========================================================================

#: Substrings that must NEVER reach a client. A leaked constraint or driver name is
#: information disclosure (T-23.1-51) and reads to the operator like a crash rather than
#: like "that run is already going".
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

#: (route path suffix, skill literal, the ai_routes background handler to no-op).
_DISPATCH_ROUTES = [
    ("skills/apply", "apply-intake-skill", "run_apply_intake_skill"),
    ("skills/context-pack", "context-pack", "run_context_pack"),
    ("embeddings", "generate-embeddings", "run_embeddings"),
]

#: Password granted to app_superadmin for the connect-as engine (test only — the SAME
#: literal the other AI suites use, so the role's password stays stable no matter which
#: suite touches it first).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


def _superadmin() -> "Identity":
    """``ai_router`` is superadmin-gated (D-23.1-02, plan 23.1-11) — a user gets 404."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (the D-05 two-engine routing).

    ``app_superadmin`` is a plain non-superuser LOGIN role, so the superadmin write path
    exercises the 0003 bypass POLICY + GRANTs rather than superuser ambient authority.
    Shape copied from ``test_ai_apply_skill.superadmin_engine``.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(ai_routes_mod.ai_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _patch_engine_factories(monkeypatch, user_engine, sa_engine=None) -> None:
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    if sa_engine is not None:
        monkeypatch.setattr(
            ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
        )


def _freeze_background_tasks(monkeypatch) -> None:
    """No-op every AI background handler so the dispatched run STAYS ``running``.

    Under ``TestClient`` a background task runs synchronously after the response, which
    would finalize the run and make the second dispatch legal — the conflict this suite
    measures would never occur. No-opping them freezes the run in flight, which is the
    real-world state a double-click hits.

    It also guarantees ZERO PROVIDER SPEND: no Anthropic/OpenAI client is ever
    constructed, because the only code that would construct one never runs. The point
    under test is the SYNCHRONOUS dispatch step, which precedes the background task on
    every one of the six dispatching routes.
    """
    for handler in (
        "run_apply_intake_skill",
        "run_context_pack",
        "run_embeddings",
        "run_extract_insights",
        "run_structure_answers",
        "run_transcribe",
    ):
        monkeypatch.setattr(ai_routes_mod, handler, lambda *a, **k: None)


def _count_runs(engine, set_space, space_id, intake_id) -> int:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{TABLE} WHERE intake_id = :iid"),
            {"iid": intake_id},
        ).scalar_one()


@pytest.mark.parametrize("path,skill,_handler", _DISPATCH_ROUTES)
def test_second_dispatch_of_the_same_skill_returns_409(
    engine, set_space, monkeypatch, superadmin_engine, path, skill, _handler
):
    """202 then 409, and exactly ONE ``skill_runs`` row — the double-click is not paid for.

    Parametrized over three of the six dispatching routes to prove the arm lives in
    ``_dispatch_skill_run`` and is inherited, not copy-pasted per route.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        first = client.post(f"/intakes/{intake_id}/{path}")
        assert first.status_code == 202, (
            f"the FIRST dispatch must be accepted, got {first.status_code} "
            f"(body={first.text!r})"
        )

        second = client.post(f"/intakes/{intake_id}/{path}")
        assert second.status_code == 409, (
            "a second dispatch while the first is still running must be a 409 — a 500 "
            f"would mean the IntegrityError escaped untranslated. got "
            f"{second.status_code} (body={second.text!r})"
        )

        assert _count_runs(engine, set_space, space, intake_id) == 1, (
            "the refused dispatch must leave exactly ONE row. More than one means the "
            "index did not arbitrate; the whole point of COST-01 is that the operator "
            "does not pay twice."
        )
        rows = _runs_for(engine, set_space, space, intake_id, skill)
        assert len(rows) == 1 and rows[0][1] == "running"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_409_detail_names_the_skill_and_leaks_no_driver_string(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The body is a readable sentence, not a database error (T-23.1-51).

    Asserted on the RESPONSE BODY, not merely on the status code: a 409 whose detail
    carries ``duplicate key value violates unique constraint
    "uq_skill_runs_one_running_per_intake_skill"`` discloses the schema and reads to the
    operator like a crash.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 202
        conflict = client.post(f"/intakes/{intake_id}/skills/apply")
        assert conflict.status_code == 409

        body = conflict.json()
        detail = body.get("detail")
        assert isinstance(detail, str) and detail, (
            f"the 409 must carry a plain-string detail (the frontend transport reads it "
            f"verbatim), got {body!r}"
        )
        assert "apply-intake-skill" in detail, (
            f"the detail must name the skill so the operator knows WHICH run is in "
            f"flight, got {detail!r}"
        )
        raw = conflict.text
        for needle in _FORBIDDEN_IN_DETAIL:
            assert needle.lower() not in raw.lower(), (
                f"the 409 body leaks {needle!r} — a driver/constraint string is "
                f"information disclosure and reads like a crash. body={raw!r}"
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_second_dispatch_of_a_different_skill_still_returns_202(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The invariant is per-SKILL — two different skills may be in flight together."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 202
        other = client.post(f"/intakes/{intake_id}/skills/context-pack")
        assert other.status_code == 202, (
            "a DIFFERENT skill on the same intake must still dispatch — over-broad "
            f"blocking would be an outage, not a saving. got {other.status_code} "
            f"(body={other.text!r})"
        )
        assert _count_runs(engine, set_space, space, intake_id) == 2
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_same_skill_after_the_first_run_finished_still_returns_202(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The ordinary retry path: once the run is terminal, the next dispatch is accepted."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 202
        # Finalize it the way the background task would (D-09 terminal literal).
        with engine.begin() as conn:
            set_space(conn, space)
            conn.execute(
                text(
                    f"UPDATE {SCHEMA}.{TABLE} SET status = 'succeeded' "
                    "WHERE intake_id = :iid"
                ),
                {"iid": intake_id},
            )

        again = client.post(f"/intakes/{intake_id}/skills/apply")
        assert again.status_code == 202, (
            "re-running a skill after the previous run finished must be accepted — this "
            "is the case that would break under a NON-partial unique index. got "
            f"{again.status_code} (body={again.text!r})"
        )
        assert _count_runs(engine, set_space, space, intake_id) == 2
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_a_conflict_does_not_poison_the_following_request(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The failed flush must not leave a rolled-back session in play (T-23.1-52).

    A SQLAlchemy session that has seen a failed flush raises ``PendingRollbackError`` on
    its next statement, which would turn the clean 409 into a 500 — for the CONFLICTING
    request or for the one after it. ``tenant_session``'s ``maker.begin()`` exit rolls the
    transaction back and returns the connection; this case proves it by driving a further
    request through the same machinery afterwards.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    other_intake = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        from sqlalchemy import text

        with engine.begin() as conn:
            set_space(conn, space)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :space_id, 'submitted')"
                ),
                {"id": other_intake, "space_id": space},
            )

        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 202
        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 409

        # Same skill, DIFFERENT intake — a fresh session through the same code path.
        after = client.post(f"/intakes/{other_intake}/skills/apply")
        assert after.status_code == 202, (
            "the request after a conflict must succeed cleanly — a 500 here means the "
            "rolled-back session was reused (PendingRollbackError). got "
            f"{after.status_code} (body={after.text!r})"
        )
        assert _count_runs(engine, set_space, space, other_intake) == 1
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_search_route_is_unaffected(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The one NON-dispatching AI route never touches ``_dispatch_skill_run`` — still 200.

    Guards the blast radius: the new ``except`` arm sits in ``_dispatch_skill_run``, and
    ``GET /intakes/{id}/search`` does not go through it. A regression here would mean the
    arm was added somewhere far too broad.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        _freeze_background_tasks(monkeypatch)
        monkeypatch.setattr(ai_routes_mod, "semantic_search", lambda *a, **k: [])
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 202
        assert client.post(f"/intakes/{intake_id}/skills/apply").status_code == 409

        found = client.get(f"/intakes/{intake_id}/search", params={"q": "anything"})
        assert found.status_code == 200, (
            f"search must be untouched by the conflict arm, got {found.status_code} "
            f"(body={found.text!r})"
        )
        assert found.json() == {"results": []}
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# PLAN 23.1-13 — migration 0015 drops the DEAD ``skill_runs.started_at``
# ===========================================================================
#
# These belong to a DIFFERENT plan than everything above, but to the SAME table and the
# SAME migration chain: 0015 sits directly on top of 0014, and every one of the cases
# above drives ``alembic upgrade head`` — which, after 0015, means running 0015 too. A
# separate fifteen-line module for five schema assertions would hide that coupling and
# would re-implement this file's alembic + seeding helpers verbatim.
#
# ``started_at`` was dead: NOTHING in the codebase ever wrote it. Only
# ``research_runs.started_at`` is written (``run_task.py``, ``stream_session.py``), and
# that is a DIFFERENT column on a DIFFERENT table which this plan does not touch. The
# skill-run elapsed clock reads ``created_at`` and always did — see ``SkillRunView``'s
# docstring in ``intake_routes.py``.
#
# Every case below reads the LIVE catalog (``information_schema`` / ``pg_indexes``) or
# drives a real HTTP request. None of them greps a source file: a source assertion passes
# on a migration that was written and never applied.
#
# The sixth ``<behavior>`` item — "``alembic check`` reports no drift" — is NOT restated
# here. ``test_alembic_check_reports_no_drift`` above already runs ``command.check`` against
# HEAD, and HEAD is now 0015; it is exactly the assertion that catches an ORM column removed
# without a migration, or a migration written without the ORM removal. A second identical
# call would be decoration, not a gate.

#: Plan 23.1-13's revision, and the one immediately below it (23.1-12's).
REVISION_0015 = "0015"
REVISION_0014 = "0014"

#: The column this plan removes, and the three that must survive it.
_DROPPED_COLUMN = "started_at"
_SURVIVING_TIMESTAMPS = ("created_at", "completed_at", "applied_at")


def _skill_run_columns(engine) -> dict[str, tuple]:
    """``{column_name: (is_nullable, column_default)}`` for ``nestor.skill_runs``, LIVE."""
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": SCHEMA, "t": TABLE},
        ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


def _skill_run_index_names(engine) -> set[str]:
    from sqlalchemy import text

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


def test_0015_drops_started_at_from_skill_runs(engine):
    """At head, ``nestor.skill_runs`` has NO ``started_at`` column.

    Asserted from ``information_schema``, not from ``models/skill_run.py``'s source: the
    ORM losing a ``mapped_column`` proves only that the ORM lost it. The point of the
    migration is that the COLUMN is gone from the database, so the next reader looking for
    "when did this run start?" finds exactly one candidate instead of two.

    Note the drop needs no RLS dance. ``skill_runs`` carries FORCE ROW LEVEL SECURITY
    (0009) and FORCE binds the table owner — which is the role alembic runs as — so 0014's
    cross-space *UPDATE* had to lift FORCE or match zero rows silently. RLS governs DML
    only; ``ALTER TABLE ... DROP COLUMN`` is DDL and no row policy is consulted. If that
    reasoning were wrong, this assertion is what catches it: a silently no-op'd drop leaves
    the column right here.
    """
    columns = _skill_run_columns(engine)

    assert columns, f"{SCHEMA}.{TABLE} must exist in information_schema."
    assert _DROPPED_COLUMN not in columns, (
        f"{SCHEMA}.{TABLE}.{_DROPPED_COLUMN} must be gone after 0015, found it with "
        f"(is_nullable, column_default) = {columns.get(_DROPPED_COLUMN)!r}"
    )


def test_0015_leaves_the_neighbouring_timestamp_columns_intact(engine):
    """``created_at``, ``completed_at`` and ``applied_at`` survive the drop.

    ``started_at`` sat BETWEEN ``created_at`` and ``completed_at`` in the model, and
    ``created_at`` is the one the elapsed clock actually reads. Collateral damage to any of
    the three is the expensive failure here, so all three are asserted from the live
    catalog rather than assumed from the diff.

    ``created_at``'s NOT NULL + ``now()`` default is asserted too, because that pair is the
    whole reason it — and not the dropped column — is the run's real start timestamp.
    """
    columns = _skill_run_columns(engine)

    for name in _SURVIVING_TIMESTAMPS:
        assert name in columns, (
            f"{SCHEMA}.{TABLE}.{name} must survive 0015 — the drop must take "
            f"{_DROPPED_COLUMN} and nothing else. present: {sorted(columns)!r}"
        )

    created_nullable, created_default = columns["created_at"]
    assert created_nullable == "NO", (
        "created_at must stay NOT NULL — it is the run's real start timestamp and the "
        f"clock's only data source, got is_nullable={created_nullable!r}"
    )
    assert created_default is not None and "now()" in created_default, (
        "created_at must keep its server_default now(); without it a run could be "
        f"inserted with no start time at all, got {created_default!r}"
    )


def test_0015_leaves_the_0014_unique_index_intact(engine):
    """0014's partial unique index survives 0015 untouched.

    A ``DROP COLUMN`` on an unrelated column should not disturb an index that does not
    reference it — but a CASCADE, or a table rewrite, would take it silently, and the first
    symptom in production would be a double-clicked skill run billed twice (COST-01). Cheap
    to assert here, expensive to discover there.
    """
    names = _skill_run_index_names(engine)

    assert INDEX_NAME in names, (
        f"{INDEX_NAME} must survive 0015 — losing it silently un-does 23.1-12's "
        f"single-running invariant. present: {sorted(names)!r}"
    )


def test_the_skill_run_list_projection_still_carries_created_at(
    engine, set_space, monkeypatch
):
    """``GET /intakes/{id}/skill-runs`` still returns ``created_at`` for a seeded run.

    The behavioural half: the elapsed clock's data source is intact after the column drop.
    This is the LIST route (``SkillRunsView`` -> ``SkillRunView``), which is what
    ``frontend/src/lib/api/skillRuns.ts:44`` fetches and what ``useElapsed`` reads.

    NOT the single-run route. Plan 23.1-13 named ``GET /skill-runs/{run_id}`` in this
    criterion, but ``SkillRunFullView`` projects only ``{id, output_parsed,
    cost_estimate_usd}`` — it has never carried a ``created_at``, so asserting one there
    would be red forever regardless of this migration. The criterion's PURPOSE — "the
    elapsed clock's data source is intact" — is what this pins, on the route that actually
    carries it.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api import intake_routes as intake_routes_mod
    from app.api.auth_routes import protected_router
    from app.db import session as session_mod

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()

    protected_router.include_router(intake_routes_mod.intake_router)
    app = FastAPI()
    app.include_router(protected_router)

    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            _insert_run(
                conn,
                set_space,
                space,
                intake_id,
                skill="apply-intake-skill",
                status="running",
                run_id=run_id,
            )
        # The list read runs through get_skill_run_repo, which reads session.get_engine
        # (NOT ai_session.get_engine, which the dispatch half above patches).
        monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: engine)
        app.dependency_overrides[get_current_identity] = _as(
            Identity(uid="u", email="u@x", role="user", space_id=str(space))
        )

        r = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 200, r.text
        body = r.json()

        assert body["latest"] is not None, body
        assert body["latest"]["id"] == str(run_id), body
        assert body["latest"]["created_at"], (
            "the latest run must project a non-empty created_at — it is the elapsed "
            f"clock's ONLY start timestamp now that started_at is gone. got {body!r}"
        )
        assert body["runs"] and body["runs"][0]["created_at"], body
        # The dropped column must not have crept back into the projection.
        assert _DROPPED_COLUMN not in body["latest"], (
            f"{_DROPPED_COLUMN} must not appear in the view, got {body['latest']!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_0015_downgrade_restores_a_nullable_defaultless_started_at(engine):
    """``downgrade -1`` re-adds ``started_at`` NULLABLE, with NO default and NO index.

    A reversal that lands the column NOT NULL, or with a ``server_default``, is not a
    reversal — it is a different column wearing the same name, and on a table with rows a
    NOT NULL re-add fails the downgrade outright. ``is_nullable`` and ``column_default``
    are read straight out of ``information_schema``, never from the migration's source.

    The re-upgrade must then remove it again, which is also what leaves the session-scoped
    engine at head for every following test.
    """
    from alembic import command

    cfg = _alembic_cfg(engine)

    assert _current_revision(engine) == REVISION_0015, (
        "the engine fixture should have run 'alembic upgrade head', and head must be "
        f"{REVISION_0015} — found {_current_revision(engine)!r}"
    )
    indexes_before = _skill_run_index_names(engine)

    try:
        command.downgrade(cfg, "-1")
        assert _current_revision(engine) == REVISION_0014, (
            f"downgrade -1 from {REVISION_0015} must land on {REVISION_0014} — a "
            "different landing point means the chain is not linear."
        )

        columns = _skill_run_columns(engine)
        assert _DROPPED_COLUMN in columns, (
            f"downgrade must re-add {_DROPPED_COLUMN}; present: {sorted(columns)!r}"
        )
        is_nullable, column_default = columns[_DROPPED_COLUMN]
        assert is_nullable == "YES", (
            "the restored column must be NULLABLE — a NOT NULL re-add would fail the "
            f"downgrade on any table that already holds rows. got {is_nullable!r}"
        )
        assert column_default is None, (
            "the restored column must have NO default — a default would invent a start "
            f"timestamp for rows that never had one. got {column_default!r}"
        )
        assert _skill_run_index_names(engine) == indexes_before, (
            "the downgrade must add no index and drop none — including 0014's. "
            f"before={indexes_before!r} after={_skill_run_index_names(engine)!r}"
        )
    finally:
        command.upgrade(cfg, "head")

    assert _current_revision(engine) == REVISION_0015
    assert _DROPPED_COLUMN not in _skill_run_columns(engine), (
        "the re-upgrade must drop the column again — both directions are exercised here, "
        "so neither is a one-way door."
    )
    assert _skill_run_index_names(engine) == indexes_before
