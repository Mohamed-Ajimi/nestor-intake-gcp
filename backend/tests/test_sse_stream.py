"""SSE skill-run stream suite (API-04 / criterion #2 & #3) — integration, RED scaffold.

Authored against the FINAL wire contract; RED until 08-01 Tasks 2 & 3 land
(``app.db.stream_session`` + the ``stream_skill_runs`` route). Runs over REAL
Postgres (``pytest.mark.integration`` — auto-skips without Docker/DATABASE_URL,
runs in Cloud Build per MEMORY ``phase-07-deployed-suite-green``).

Four behaviours, each mapping to a locked decision / success criterion:

* ``test_stream_emits_snapshot_then_closes_on_terminal`` (API-04) — a stream
  opened against an intake whose latest run is ALREADY terminal (``succeeded``)
  emits the at-connect snapshot, sees terminal, and closes to EOF. Seeding the
  terminal run BEFORE connecting is the mandatory no-hang lever (RESEARCH
  Pitfall 4): no clock faking, no infinite generator.
* ``test_stream_reads_db_each_tick`` (API-04 / criterion #2 statelessness) —
  with ``TICK_SECONDS`` / ``MAX_STREAM_SECONDS`` monkeypatched tiny, seed a
  ``running`` run, flip it to ``succeeded`` via a SECOND scoped write between
  reads, and assert the stream emits a ``running`` data event followed by a
  ``succeeded`` data event. Proves every tick is a fresh DB re-read (no cached
  in-memory snapshot) — a reconnecting client on any instance sees the same.
* ``test_stream_cross_tenant_is_404`` (criterion #3 / D-04) — a space-A caller
  streaming a space-B intake gets a plain-GET 404 raised in the pre-flight
  BEFORE any stream opens (existence-hidden; never 403/200).
* ``test_stream_null_space_is_403`` (D-04 default-deny) — a null-space user's
  stream pre-flight returns 403.

RED discipline: external deps ``importorskip``; impl HARD-imported.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

# HARD imports of the impl-under-construction — RED until Tasks 2 & 3 land.
from app.api import intake_routes as intake_routes_mod  # noqa: E402
from app.db import ai_session as ai_session_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"

# The ONLY allowed terminal values (D-05 / skill-run-status-succeeded-contract).
TERMINAL_SUCCESS = "succeeded"


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A user Identity with NO space — the null-space default-deny case (D-04)."""
    return Identity(uid="u-nospace", email="u@x", role="user", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _build_app():
    """Mount ``intake_router`` under ``protected_router`` (both new endpoints live there)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(intake_routes_mod.intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "SSE stream space"},
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


def _seed_run(
    engine,
    set_space,
    space_id,
    intake_id,
    run_id,
    status="succeeded",
    output_parsed=None,
    cost_estimate_usd=None,
) -> None:
    """Insert one ``skill_runs`` row under the space GUC (mirrors test_ai_cross_tenant).

    ``output_parsed`` / ``cost_estimate_usd`` are accepted for parity with the
    full-run suite's seeder; the stream only reads status/timestamps.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.skill_runs "
                "(id, space_id, intake_id, skill, status, output_parsed, cost_estimate_usd) "
                "VALUES (:id, :space_id, :intake_id, 'apply-intake-skill', :status, "
                ":output_parsed, :cost)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "status": status,
                "output_parsed": json.dumps(output_parsed) if output_parsed is not None else None,
                "cost": cost_estimate_usd,
            },
        )


def _set_run_status(engine, set_space, space_id, run_id, status) -> None:
    """Flip an existing run's status under the space GUC (per-tick statelessness proof)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(f"UPDATE {SCHEMA}.skill_runs SET status = :status WHERE id = :id"),
            {"status": status, "id": run_id},
        )


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def _data_payloads(resp) -> list:
    """Collect the JSON body of every ``data:`` SSE line (heartbeats ignored)."""
    payloads = []
    for line in resp.iter_lines():
        if line.startswith("data:"):
            payloads.append(json.loads(line[5:].strip()))
    return payloads


def test_stream_emits_snapshot_then_closes_on_terminal(engine, set_space, monkeypatch):
    """API-04: an at-connect snapshot on a terminal run closes the stream (no hang)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id, status=TERMINAL_SUCCESS)  # TERMINAL
    # The stream helpers call tenant_session, which reads ai_session.get_engine.
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        with TestClient(app).stream(
            "GET",
            f"/intakes/{intake_id}/skill-runs/stream",
            headers={"Authorization": "Bearer overridden"},
        ) as resp:
            assert resp.status_code == 200
            assert resp.headers["content-type"].startswith("text/event-stream")
            payloads = _data_payloads(resp)
        # The terminal event is the last data event; then the server closed the stream.
        assert payloads, "expected at least the at-connect snapshot data event"
        assert payloads[-1] is not None
        assert payloads[-1]["status"] == TERMINAL_SUCCESS
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_stream_reads_db_each_tick(engine, set_space, monkeypatch):
    """Criterion #2: each tick is a fresh DB read — a running->succeeded flip is observed.

    Proves statelessness: the ``succeeded`` value is sourced from a SECOND scoped
    write made AFTER the snapshot, so a cached snapshot could never surface it.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(engine, set_space, space, intake_id, run_id, status="running")
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)
    # Tiny tick so the transition is observed without wall-clock waiting; generous cap.
    monkeypatch.setattr(intake_routes_mod, "TICK_SECONDS", 0.05)
    monkeypatch.setattr(intake_routes_mod, "MAX_STREAM_SECONDS", 30)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        # Consume the stream incrementally: flip the run to terminal via a fresh
        # scoped write only AFTER the `running` snapshot frame arrives, so the
        # `succeeded` value can only come from a per-tick DB re-read — a cached
        # in-memory snapshot could never surface it.
        statuses = []
        with TestClient(app).stream(
            "GET",
            f"/intakes/{intake_id}/skill-runs/stream",
            headers={"Authorization": "Bearer overridden"},
        ) as resp:
            assert resp.status_code == 200
            flipped = False
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:].strip())
                if payload is None:
                    continue
                statuses.append(payload["status"])
                if not flipped and payload["status"] == "running":
                    _set_run_status(engine, set_space, space, run_id, TERMINAL_SUCCESS)
                    flipped = True
        # Snapshot `running` then the per-tick-read `succeeded` (terminal, closes stream).
        assert "running" in statuses, f"expected the seeded running snapshot, got {statuses!r}"
        assert statuses[-1] == TERMINAL_SUCCESS, (
            f"expected the per-tick DB re-read to surface {TERMINAL_SUCCESS!r} last, "
            f"got {statuses!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_stream_cross_tenant_is_404(engine, set_space, two_spaces, monkeypatch):
    """Criterion #3 / D-04: a cross-space stream is a plain-GET 404 raised pre-stream."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()
    _seed_intake(engine, set_space, space_b, intake_b)  # intake owned by space-B
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # caller = space-A
    try:
        # Plain GET (NOT a streaming read): the 404 is raised in the pre-flight check
        # BEFORE StreamingResponse is constructed (D-04).
        r = TestClient(app).get(
            f"/intakes/{intake_b}/skill-runs/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant stream must be existence-hidden 404, never 403/200; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_b)


def test_stream_null_space_is_403(engine, set_space, monkeypatch):
    """D-04 default-deny: a null-space user's stream pre-flight returns 403."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_intake(engine, set_space, space, intake_id)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    app = _build_app()
    # A user Identity with no space — tenant_session raises PermissionError -> 403.
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 403, (
            f"null-space user must be default-denied 403 on the pre-flight; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
