"""23.6-01 — ``research_runs.chosen_at``: the internal "which run is the report based on" mark.

Phase 23.6 (D-23.6-02 revised) lets a superadmin rerun deep research on one intake as many
times as they like, and lets the operator record WHICH of those runs the final report is
based on. That record is a flag on the RUN (``chosen_at``), not a pointer on the intake:

* no ``intakes <-> research_runs`` FK cycle (research_runs already cascades from intakes, and
  the D-23.5-06 intake delete must keep working unchanged);
* the "at most ONE chosen run per intake" rule is a DATABASE invariant — the partial unique
  index ``uq_research_runs_one_chosen_per_intake`` — the same technique 0016 uses for the
  single in-flight run.

The newest-finished DEFAULT is display-only and is never stored (UI-SPEC UI-8): nothing
writes ``chosen_at`` except :meth:`ResearchRunRepository.set_chosen`.

Test style copies ``test_research_run_reconciler_columns.py``: every schema/index assertion
reads the DEPLOYED catalog (``information_schema`` / ``pg_indexes``), never migration source
text, because ``alembic check`` does NOT compare ``postgresql_where`` (DEF-23.2-15).
``pytestmark = pytest.mark.integration`` because the committed backend gate runs
``pytest tests -m integration``.

ZERO PROVIDER SPEND: no seam, no bucket, no Tribunal — the database only.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# External deps — skip-clean when not installed on this box.
pytest.importorskip("sqlalchemy")
identity_mod = pytest.importorskip("app.auth.identity")
repository_mod = pytest.importorskip("app.db.repository")

Identity = identity_mod.Identity
ResearchRunRepository = repository_mod.ResearchRunRepository

SCHEMA = "nestor"
TABLE = "research_runs"
COLUMN = "chosen_at"

#: BYTE-IDENTICAL to migration 0018's and to the model's ``__table_args__`` entry.
CHOSEN_INDEX = "uq_research_runs_one_chosen_per_intake"

REVISION = "0018"
PREVIOUS_REVISION = "0017"

# backend/tests/test_research_run_chosen.py -> backend/ is parents[1]
_BACKEND = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Seeding + catalog helpers
# ---------------------------------------------------------------------------

def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Chosen run space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="delivered") -> None:
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


def _seed_run(engine, set_space, space_id, intake_id, run_id, *, attempt=1,
              status="completed", chosen=False) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.{TABLE} "
                "(id, space_id, intake_id, status, attempt, chosen_at) "
                "VALUES (:id, :space_id, :intake_id, :status, :attempt, "
                "CASE WHEN :chosen THEN now() ELSE NULL END)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "attempt": attempt,
                "chosen": chosen,
            },
        )


def _chosen_map(engine, set_space, space_id, intake_id) -> dict:
    """``{run_id: chosen_at}`` for every run of the intake."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        rows = conn.execute(
            text(
                f"SELECT id, chosen_at, status FROM {SCHEMA}.{TABLE} "
                "WHERE intake_id = :iid"
            ),
            {"iid": intake_id},
        ).all()
    return {r[0]: r[1] for r in rows}


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )


def _indexdef(engine, name: str) -> str | None:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = :t AND indexname = :n"
            ),
            {"s": SCHEMA, "t": TABLE, "n": name},
        ).first()
    return None if row is None else row[0]


def _alembic_cfg(engine):
    from alembic.config import Config

    cfg = Config(str(_BACKEND / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", engine.url.render_as_string(hide_password=False))
    return cfg


def _current_revision(engine) -> str | None:
    from sqlalchemy import text

    with engine.begin() as conn:
        row = conn.execute(text("SELECT version_num FROM public.alembic_version")).first()
    return None if row is None else row[0]


def _column_names(engine) -> set[str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t"
            ),
            {"s": SCHEMA, "t": TABLE},
        ).all()
    return {r[0] for r in rows}


def _index_names(engine) -> set[str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname FROM pg_indexes WHERE schemaname = :s AND tablename = :t"
            ),
            {"s": SCHEMA, "t": TABLE},
        ).all()
    return {r[0] for r in rows}


# ===========================================================================
# Test 1 — the column
# ===========================================================================

def test_chosen_at_column_is_nullable_timestamptz_without_default(engine):
    """NULLABLE + NO default = a metadata-only ADD COLUMN on a table of paid rows.

    NULL is the meaning "not chosen"; the newest-finished default is display-only and is
    never stored (UI-8), so a server default would be actively WRONG, not just slow.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT is_nullable, data_type, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = :s AND table_name = :t AND column_name = :c"
            ),
            {"s": SCHEMA, "t": TABLE, "c": COLUMN},
        ).first()

    assert row is not None, f"missing column {SCHEMA}.{TABLE}.{COLUMN}"
    is_nullable, data_type, column_default = row
    assert data_type == "timestamp with time zone", data_type
    assert is_nullable == "YES", is_nullable
    assert column_default is None, column_default


# ===========================================================================
# Test 2 — one chosen run per intake, enforced by the DATABASE
# ===========================================================================

def test_one_chosen_run_per_intake_is_db_enforced(engine, set_space):
    """A second non-null ``chosen_at`` on ONE intake raises; two intakes may each have one."""
    from sqlalchemy.exc import IntegrityError

    space = uuid.uuid4()
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()
    _seed_space(engine, space)
    try:
        _seed_intake(engine, set_space, space, intake_a)
        _seed_intake(engine, set_space, space, intake_b)

        _seed_run(engine, set_space, space, intake_a, uuid.uuid4(), attempt=1, chosen=True)
        # A different intake may carry its own chosen run.
        _seed_run(engine, set_space, space, intake_b, uuid.uuid4(), attempt=1, chosen=True)
        # Unchosen rows of the same intake are unconstrained.
        _seed_run(engine, set_space, space, intake_a, uuid.uuid4(), attempt=2, chosen=False)

        with pytest.raises(IntegrityError):
            _seed_run(
                engine, set_space, space, intake_a, uuid.uuid4(), attempt=3, chosen=True
            )

        chosen_a = [v for v in _chosen_map(engine, set_space, space, intake_a).values() if v]
        chosen_b = [v for v in _chosen_map(engine, set_space, space, intake_b).values() if v]
        assert len(chosen_a) == 1
        assert len(chosen_b) == 1
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 3 — the index predicate, pinned against the DEPLOYED definition
# ===========================================================================

def test_chosen_index_predicate_is_pinned(engine):
    """``pg_indexes.indexdef`` — ``alembic check`` does not compare postgresql_where."""
    indexdef = _indexdef(engine, CHOSEN_INDEX)
    assert indexdef is not None, f"index {CHOSEN_INDEX} missing on {SCHEMA}.{TABLE}"
    assert "UNIQUE" in indexdef.upper(), indexdef
    assert "(intake_id)" in indexdef, indexdef
    assert "chosen_at IS NOT NULL" in indexdef, indexdef


# ===========================================================================
# Test 4 — set_chosen moves the mark atomically and is idempotent
# ===========================================================================

def test_set_chosen_moves_the_mark_and_returns_previous(engine, set_space):
    """None -> A; A -> B returns A and clears A; B -> B returns B and changes nothing.

    Runs as a ``user`` identity of the intake's space inside ONE session per call, so the
    repository's ``_scope`` wall is on the path (the superadmin path only drops it).
    """
    from sqlalchemy.orm import Session

    space = uuid.uuid4()
    intake = uuid.uuid4()
    other_intake = uuid.uuid4()
    run_a, run_b, run_other = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    identity = Identity(uid="u-chosen", email="u@acme.test", role="user", space_id=str(space))

    _seed_space(engine, space)
    try:
        _seed_intake(engine, set_space, space, intake)
        _seed_intake(engine, set_space, space, other_intake)
        _seed_run(engine, set_space, space, intake, run_a, attempt=1)
        _seed_run(engine, set_space, space, intake, run_b, attempt=2, status="parked")
        # A chosen run on ANOTHER intake must never be touched by this intake's moves.
        _seed_run(engine, set_space, space, other_intake, run_other, attempt=1, chosen=True)

        def _choose(run_id):
            with Session(engine) as s, s.begin():
                set_space(s, space)
                return ResearchRunRepository(s, identity).set_chosen(intake, run_id)

        # 1. nothing chosen yet -> None, A marked.
        assert _choose(run_a) is None
        state = _chosen_map(engine, set_space, space, intake)
        assert state[run_a] is not None
        assert state[run_b] is None

        # 2. move to B -> returns A, A cleared, B marked.
        assert _choose(run_b) == run_a
        state = _chosen_map(engine, set_space, space, intake)
        assert state[run_a] is None
        b_stamp = state[run_b]
        assert b_stamp is not None

        # 3. B again -> returns B, nothing changes (not even B's timestamp).
        assert _choose(run_b) == run_b
        state = _chosen_map(engine, set_space, space, intake)
        assert state[run_a] is None
        assert state[run_b] == b_stamp

        # The other intake's chosen run is untouched throughout.
        other = _chosen_map(engine, set_space, space, other_intake)
        assert other[run_other] is not None
    finally:
        _cleanup(engine, space)


# ===========================================================================
# Test 5 — 0018 reverses and re-applies, in isolation
# ===========================================================================

def test_0018_reverses_and_re_applies(engine):
    """downgrade 0018 -> 0017 removes exactly ``chosen_at`` + the index; upgrade restores.

    Drives the REAL alembic commands against the container. ``upgrade head`` runs in the
    ``finally`` so a failure cannot leave the session-scoped schema behind.
    """
    from alembic import command

    cfg = _alembic_cfg(engine)
    assert _current_revision(engine) == REVISION, (
        f"the engine fixture should be at head {REVISION}; got {_current_revision(engine)!r}"
    )

    columns_before = _column_names(engine)
    indexes_before = _index_names(engine)
    assert COLUMN in columns_before
    assert CHOSEN_INDEX in indexes_before

    try:
        command.downgrade(cfg, PREVIOUS_REVISION)
        assert _current_revision(engine) == PREVIOUS_REVISION
        assert _column_names(engine) == columns_before - {COLUMN}, (
            "downgrade must drop chosen_at and NOTHING else"
        )
        assert _index_names(engine) == indexes_before - {CHOSEN_INDEX}, (
            "downgrade must drop the chosen index and NOTHING else"
        )

        command.upgrade(cfg, REVISION)
        assert _current_revision(engine) == REVISION
        assert _column_names(engine) == columns_before
        assert _index_names(engine) == indexes_before
    finally:
        command.upgrade(cfg, "head")
