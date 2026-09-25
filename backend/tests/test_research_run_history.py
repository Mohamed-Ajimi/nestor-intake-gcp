"""Run history + chosen-run verbs (Phase 23.6, D-23.6-04 / D-23.6-02 revised) — integration.

Drives the REAL ``research_router`` over live Postgres through a FastAPI ``TestClient``
(``pytest.mark.integration``). Mail is faked (``fake_resend``) so the no-client-effect
assertion can prove ZERO mail calls.

THE CONTRACT (frozen — plan 23.6-03 typed the frontend to exactly this shape):

    GET /intakes/{intake_id}/research/runs  -> 200
    {
      "chosen_research_run_id": "<uuid>" | null,   # the run whose chosen_at is non-null
      "runs": [                                     # attempt DESC, then created_at DESC
        {
          "id", "attempt", "status" (engine literal, verbatim), "created_at",
          "started_at" | null, "completed_at" | null,
          "cost_usd_total" (str(Decimal)) | null   # null when unknown, never "0"
          "chain_status" ("verified" | "broken") | null,
          "chosen_at" | null
        }
      ]
    }
    Empty ``runs`` + null chosen id for an in-scope intake with no runs.
    404 "Intake not found" for an out-of-scope / missing intake.

    POST /intakes/{intake_id}/research/runs/{run_id}/choose  (no body) -> 200
    { "chosen_research_run_id": "<run_id>", "previous_research_run_id": "<uuid>" | null }
    - 404 "Run not found": run missing, out of scope, or run.intake_id != intake_id
    - 404 "Intake not found": intake missing / out of scope
    - 409 "Only a finished run can be chosen": run.status not in RESEARCH_SUCCESS
    - 409 "An archived intake is read-only": intake.status == "archived"
    - Re-choosing the already-chosen run: 200 with previous == run_id, no audit row, no write.

The "newest finished run is the default choice" rule is DISPLAY-ONLY (UI-SPEC UI-8) and is
intentionally ABSENT from the backend: ``chosen_research_run_id`` is null until a superadmin
explicitly marks a run. A test below pins that the list never computes a default.

The chosen mark is an INTERNAL label: no mail, no report artifact, no intake column, no
client route. The no-client-effect test pins that.

DB state is asserted by raw SQL reads, never by re-calling the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")
pytest.importorskip("httpx")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")

from app.api import research_routes as research_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"

CONTRACT_KEYS = {
    "id",
    "attempt",
    "status",
    "created_at",
    "started_at",
    "completed_at",
    "cost_usd_total",
    "chain_status",
    "chosen_at",
}

AUTH = {"Authorization": "Bearer overridden"}


# ---------------------------------------------------------------------------
# Identities
# ---------------------------------------------------------------------------


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engines + app
# ---------------------------------------------------------------------------

_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (production's two-engine routing)."""
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


def _patch_engines(monkeypatch, user_engine, sa_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _client(app, identity):
    from fastapi.testclient import TestClient

    app.dependency_overrides[get_current_identity] = _as(identity)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Seeding + raw-SQL reads
# ---------------------------------------------------------------------------


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Run history space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="in_research") -> None:
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


_BASE_TS = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _seed_run(
    engine,
    set_space,
    space_id,
    intake_id,
    run_id,
    status,
    *,
    attempt=1,
    cost=None,
    chain_status=None,
    created_at=None,
    started_at=None,
    completed_at=None,
    chosen_at=None,
) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_runs "
                "(id, space_id, intake_id, status, attempt, cost_usd_total, chain_status, "
                " created_at, started_at, completed_at, chosen_at) "
                "VALUES (:id, :space_id, :intake_id, :status, :attempt, :cost, :chain, "
                " :created_at, :started_at, :completed_at, :chosen_at)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "attempt": attempt,
                "cost": cost,
                "chain": chain_status,
                "created_at": created_at or (_BASE_TS + timedelta(minutes=attempt)),
                "started_at": started_at,
                "completed_at": completed_at,
                "chosen_at": chosen_at,
            },
        )


def _chosen_at(engine, set_space, space_id, run_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT chosen_at FROM {SCHEMA}.research_runs WHERE id = :id"),
            {"id": str(run_id)},
        ).scalar_one()


def _chosen_ids(engine, set_space, space_id, intake_id) -> list[str]:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        rows = conn.execute(
            text(
                f"SELECT id FROM {SCHEMA}.research_runs "
                "WHERE intake_id = :i AND chosen_at IS NOT NULL"
            ),
            {"i": str(intake_id)},
        ).all()
    return [str(r[0]) for r in rows]


def _audit_rows(engine, intake_id) -> list:
    from sqlalchemy import text

    with engine.begin() as conn:
        return conn.execute(
            text(
                f"SELECT actor_uid, space_id, metadata FROM {SCHEMA}.audit_log "
                "WHERE target = :t AND event_type = 'research.run_chosen' "
                "ORDER BY created_at"
            ),
            {"t": str(intake_id)},
        ).all()


def _intake_client_columns(engine, set_space, space_id, intake_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return tuple(
            conn.execute(
                text(
                    f"SELECT status, final_report_artifact_id, results_link_sent_at "
                    f"FROM {SCHEMA}.intakes WHERE id = :id"
                ),
                {"id": str(intake_id)},
            ).one()
        )


def _cleanup(engine, *space_ids) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": sid}
            )
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


@pytest.fixture
def world(engine, set_space, monkeypatch, superadmin_engine):
    """One space + one in_research intake; engines patched; app built. Cleans up after."""
    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space)
    _seed_intake(engine, set_space, space, intake_id)
    _patch_engines(monkeypatch, engine, superadmin_engine)
    app = _build_app()
    extra_spaces: list = []
    try:
        yield {"space": space, "intake": intake_id, "app": app, "extra_spaces": extra_spaces}
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space, *extra_spaces)


def _list(world, identity=None):
    return _client(world["app"], identity or _superadmin()).get(
        f"/intakes/{world['intake']}/research/runs", headers=AUTH
    )


def _choose(world, run_id, identity=None, intake_id=None):
    return _client(world["app"], identity or _superadmin()).post(
        f"/intakes/{intake_id or world['intake']}/research/runs/{run_id}/choose", headers=AUTH
    )


# ===========================================================================
# GET /intakes/{id}/research/runs
# ===========================================================================


def test_list_orders_by_attempt_desc_with_exact_contract_keys(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    r1, r2, r3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_run(engine, set_space, space, intake, r1, "failed", attempt=1)
    _seed_run(
        engine, set_space, space, intake, r2, "completed", attempt=2,
        cost=Decimal("41.87"), chain_status="verified",
        started_at=_BASE_TS + timedelta(minutes=3),
        completed_at=_BASE_TS + timedelta(minutes=90),
    )
    _seed_run(engine, set_space, space, intake, r3, "running", attempt=3)

    resp = _list(world)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"chosen_research_run_id", "runs"}
    assert [item["id"] for item in body["runs"]] == [str(r3), str(r2), str(r1)]
    assert [item["attempt"] for item in body["runs"]] == [3, 2, 1]
    for item in body["runs"]:
        assert set(item.keys()) == CONTRACT_KEYS, item

    completed = body["runs"][1]
    assert completed["status"] == "completed"
    assert completed["cost_usd_total"] == "41.87"
    assert completed["chain_status"] == "verified"
    assert completed["started_at"] is not None
    assert completed["completed_at"] is not None
    assert datetime.fromisoformat(completed["completed_at"]) == _BASE_TS + timedelta(minutes=90)

    running = body["runs"][0]
    assert running["status"] == "running"  # verbatim engine literal
    assert running["cost_usd_total"] is None  # unknown cost stays null, never "0"
    assert running["chain_status"] is None
    assert running["completed_at"] is None


def test_list_same_attempt_breaks_tie_by_created_at_desc(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    older, newer = uuid.uuid4(), uuid.uuid4()
    _seed_run(engine, set_space, space, intake, older, "failed", attempt=1,
              created_at=_BASE_TS)
    _seed_run(engine, set_space, space, intake, newer, "cancelled", attempt=1,
              created_at=_BASE_TS + timedelta(hours=1))
    body = _list(world).json()
    assert [item["id"] for item in body["runs"]] == [str(newer), str(older)]


def test_list_empty_intake(world):
    resp = _list(world)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"chosen_research_run_id": None, "runs": []}


def test_list_does_not_compute_a_default_chosen_run(engine, set_space, world):
    """Newest-finished default is display-only (UI-SPEC UI-8): absent server-side."""
    space, intake = world["space"], world["intake"]
    _seed_run(engine, set_space, space, intake, uuid.uuid4(), "completed", attempt=1)
    _seed_run(engine, set_space, space, intake, uuid.uuid4(), "completed", attempt=2)
    body = _list(world).json()
    assert body["chosen_research_run_id"] is None
    assert all(item["chosen_at"] is None for item in body["runs"])


def test_list_names_the_explicitly_chosen_run(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    r1, r2, r3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    _seed_run(engine, set_space, space, intake, r1, "failed", attempt=1)
    _seed_run(engine, set_space, space, intake, r2, "completed", attempt=2,
              chosen_at=_BASE_TS + timedelta(hours=2))
    _seed_run(engine, set_space, space, intake, r3, "completed", attempt=3)
    body = _list(world).json()
    assert body["chosen_research_run_id"] == str(r2)
    by_id = {item["id"]: item for item in body["runs"]}
    assert by_id[str(r2)]["chosen_at"] is not None
    assert by_id[str(r1)]["chosen_at"] is None
    assert by_id[str(r3)]["chosen_at"] is None


def test_list_user_role_in_own_space_404(engine, set_space, world):
    _seed_run(engine, set_space, world["space"], world["intake"], uuid.uuid4(), "completed")
    resp = _list(world, _user(world["space"]))
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"
    assert "runs" not in resp.text


def test_list_null_space_user_404(world):
    resp = _list(world, _null_space_user())
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"


def test_list_cross_space_user_404(engine, world):
    other = uuid.uuid4()
    _seed_space(engine, other)
    world["extra_spaces"].append(other)
    resp = _list(world, _user(other))
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"


def test_list_missing_intake_404(world):
    resp = _client(world["app"], _superadmin()).get(
        f"/intakes/{uuid.uuid4()}/research/runs", headers=AUTH
    )
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Intake not found"


# ===========================================================================
# POST /intakes/{id}/research/runs/{run_id}/choose
# ===========================================================================


def test_choose_completed_run_sets_chosen_and_audits(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    run_a = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_a, "completed", attempt=2)

    resp = _choose(world, run_a)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "chosen_research_run_id": str(run_a),
        "previous_research_run_id": None,
    }
    assert _chosen_at(engine, set_space, space, run_a) is not None
    rows = _audit_rows(engine, intake)
    assert len(rows) == 1, rows
    actor_uid, audit_space, metadata = rows[0]
    assert actor_uid == "super"
    assert str(audit_space) == str(space)
    assert metadata == {
        "research_run_id": str(run_a),
        "previous_research_run_id": None,
        "attempt": 2,
    }


def test_choose_moves_the_mark_then_rechoose_is_a_noop(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    run_a, run_b = uuid.uuid4(), uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_a, "completed", attempt=1)
    _seed_run(engine, set_space, space, intake, run_b, "completed_degraded", attempt=2)

    assert _choose(world, run_a).status_code == 200

    resp = _choose(world, run_b)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "chosen_research_run_id": str(run_b),
        "previous_research_run_id": str(run_a),
    }
    assert _chosen_at(engine, set_space, space, run_a) is None
    assert _chosen_ids(engine, set_space, space, intake) == [str(run_b)]
    rows = _audit_rows(engine, intake)
    assert len(rows) == 2
    assert rows[1][2] == {
        "research_run_id": str(run_b),
        "previous_research_run_id": str(run_a),
        "attempt": 2,
    }

    stamp_before = _chosen_at(engine, set_space, space, run_b)
    again = _choose(world, run_b)
    assert again.status_code == 200, again.text
    assert again.json() == {
        "chosen_research_run_id": str(run_b),
        "previous_research_run_id": str(run_b),
    }
    assert len(_audit_rows(engine, intake)) == 2, "re-choose must not write an audit row"
    assert _chosen_at(engine, set_space, space, run_b) == stamp_before


@pytest.mark.parametrize("bad_status", ["running", "failed", "parked", "cancelled", "queued"])
def test_choose_unfinished_run_409_writes_nothing(engine, set_space, world, bad_status):
    space, intake = world["space"], world["intake"]
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_id, bad_status)
    resp = _choose(world, run_id)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "Only a finished run can be chosen"
    assert _chosen_ids(engine, set_space, space, intake) == []
    assert _audit_rows(engine, intake) == []


def test_choose_on_archived_intake_409_writes_nothing(engine, set_space, world):
    space = world["space"]
    archived = uuid.uuid4()
    _seed_intake(engine, set_space, space, archived, status="archived")
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, archived, run_id, "completed")
    resp = _choose(world, run_id, intake_id=archived)
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"] == "An archived intake is read-only"
    assert _chosen_ids(engine, set_space, space, archived) == []
    assert _audit_rows(engine, archived) == []


def test_choose_run_of_a_sibling_intake_404_writes_nothing(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    sibling = uuid.uuid4()
    _seed_intake(engine, set_space, space, sibling)
    sibling_run = uuid.uuid4()
    _seed_run(engine, set_space, space, sibling, sibling_run, "completed")
    resp = _choose(world, sibling_run)
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Run not found"
    assert _chosen_at(engine, set_space, space, sibling_run) is None
    assert _audit_rows(engine, intake) == []
    assert _audit_rows(engine, sibling) == []


def test_choose_missing_run_404(world):
    resp = _choose(world, uuid.uuid4())
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Run not found"


def test_choose_missing_intake_404(world):
    resp = _choose(world, uuid.uuid4(), intake_id=uuid.uuid4())
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "Intake not found"


def test_choose_user_role_in_own_space_404_writes_nothing(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_id, "completed")
    resp = _choose(world, run_id, identity=_user(space))
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"
    assert str(run_id) not in resp.text
    assert _chosen_at(engine, set_space, space, run_id) is None
    assert _audit_rows(engine, intake) == []


def test_choose_null_space_user_404_writes_nothing(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_id, "completed")
    resp = _choose(world, run_id, identity=_null_space_user())
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"
    assert _chosen_at(engine, set_space, space, run_id) is None
    assert _audit_rows(engine, intake) == []


def test_choose_cross_space_user_404_writes_nothing(engine, set_space, world):
    space, intake = world["space"], world["intake"]
    other = uuid.uuid4()
    _seed_space(engine, other)
    world["extra_spaces"].append(other)
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_id, "completed")
    resp = _choose(world, run_id, identity=_user(other))
    assert resp.status_code == 404, resp.text
    # The gate's own existence-hidden detail, not the router's "Not Found" for a
    # route that does not exist.
    assert resp.json()["detail"] == "Intake not found"
    assert _chosen_at(engine, set_space, space, run_id) is None
    assert _audit_rows(engine, intake) == []


def test_choose_has_no_client_facing_effect(engine, set_space, world, fake_resend):
    """D-23.6-02 revised: internal label only — no mail, no artifact, no intake column."""
    space, intake = world["space"], world["intake"]
    run_id = uuid.uuid4()
    _seed_run(engine, set_space, space, intake, run_id, "completed")
    before = _intake_client_columns(engine, set_space, space, intake)
    resp = _choose(world, run_id)
    assert resp.status_code == 200, resp.text
    assert _intake_client_columns(engine, set_space, space, intake) == before
    assert fake_resend["calls"] == []
