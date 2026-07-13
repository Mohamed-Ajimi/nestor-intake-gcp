"""Full skill-run read suite (D-08 / D-04) — integration, RED scaffold.

Authored against the FINAL contract; RED until 08-01 Task 3 lands the
``GET /intakes/{intake_id}/skill-runs/{run_id}`` handler + ``SkillRunFullView``.
Runs over REAL Postgres (``pytest.mark.integration`` — auto-skips without
Docker/DATABASE_URL, runs in Cloud Build).

Phase 7 writes ``output_parsed`` + ``cost_estimate_usd`` on a finished run but
NOTHING projects them today, so the AIReviewPanel review flow is a dead end
(D-08). This suite pins the folded-in full-run read:

* ``test_full_run_projection`` (D-08) — a scoped GET of a seeded run projects
  ``output_parsed`` (dict) + ``cost_estimate_usd`` (float) in body.
* ``test_full_run_cross_tenant_is_404`` (D-08 / D-04) — a space-A caller reading
  a space-B run is an existence-hidden 404; and a run whose ``intake_id`` does
  NOT match the path ``intake_id`` is also a 404 (mismatched-intake guard).

The full-run read uses the request-scoped ``get_skill_run_repo`` dependency
(``app.db.session``), so the engine seam patched here is ``session.get_engine``
(NOT ``ai_session.get_engine``, which the STREAM helpers use).

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

# HARD imports of the impl-under-construction — RED until Task 3 lands.
from app.api import intake_routes as intake_routes_mod  # noqa: E402
from app.db import session as session_mod  # noqa: E402

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _build_app():
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
            {"id": space_id, "name": "full-run space"},
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


def _cleanup(engine, *space_ids) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for space_id in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": space_id},
            )


def test_full_run_projection(engine, set_space, monkeypatch):
    """D-08: the scoped full-run read projects output_parsed (dict) + cost (float)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    run_id = uuid.uuid4()
    parsed = {"research_questions_refined": ["q1", "q2"], "dropped": []}
    _seed_intake(engine, set_space, space, intake_id)
    _seed_run(
        engine,
        set_space,
        space,
        intake_id,
        run_id,
        status="succeeded",
        output_parsed=parsed,
        cost_estimate_usd=0.012,
    )
    # The full-run read runs through get_skill_run_repo, which reads session.get_engine.
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space))
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs/{run_id}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == str(run_id)
        assert isinstance(body["output_parsed"], dict), body
        assert body["output_parsed"] == parsed
        assert isinstance(body["cost_estimate_usd"], float), body
        assert body["cost_estimate_usd"] == pytest.approx(0.012)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_full_run_cross_tenant_is_404(engine, set_space, two_spaces, monkeypatch):
    """D-08 / D-04: a cross-space run AND a mismatched-intake run are both 404."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a = uuid.uuid4()
    intake_b = uuid.uuid4()
    run_a = uuid.uuid4()
    run_b = uuid.uuid4()
    _seed_intake(engine, set_space, space_a, intake_a)
    _seed_intake(engine, set_space, space_b, intake_b)
    # A run owned by space-B, and an in-scope run of space-A (for the mismatch case).
    _seed_run(engine, set_space, space_b, intake_b, run_b, status="succeeded")
    _seed_run(engine, set_space, space_a, intake_a, run_a, status="succeeded")
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_a))  # caller = space-A
    try:
        client = TestClient(app)
        # (1) Cross-tenant: space-A caller reading space-B's run -> existence-hidden 404.
        r_cross = client.get(
            f"/intakes/{intake_b}/skill-runs/{run_b}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r_cross.status_code == 404, (
            f"cross-tenant full-run must be 404, never 403/200; got {r_cross.status_code}"
        )
        # (2) Mismatched-intake: run_a is in-scope but its intake_id != the path intake_id.
        r_mismatch = client.get(
            f"/intakes/{intake_b}/skill-runs/{run_a}",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r_mismatch.status_code == 404, (
            "a run whose intake_id != the path intake_id must be 404 (BOLA guard); "
            f"got {r_mismatch.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)
