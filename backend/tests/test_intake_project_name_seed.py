"""project_name seed on create (quick 261006-jgn, tester item 2a).

The new-intake screen asks for a project name (``IntakeCreate.client_name``, relabelled by
D-23.5-03) and the form then asked for it AGAIN as the ``project_name`` answer. ``POST
/intakes`` now seeds the ``project_name`` answer from the create BODY value, so the admin
types it once.

| Test                                 | Proves                                                  |
|--------------------------------------|---------------------------------------------------------|
| ``user_create_seeds``                | user create -> project_name answer = body value, in the |
|                                      | intake's own space, ``value`` column, value_json NULL   |
| ``blank_or_missing_does_not_seed``   | no/blank body value -> NO row (never the trigger-       |
|                                      | mirrored organisation name)                             |
| ``superadmin_create_seeds``          | superadmin create (?space_id=) also seeds; the 0008     |
|                                      | client_name answer is untouched                         |
| ``existing_row_is_not_overwritten``  | the helper is ON CONFLICT DO NOTHING                    |
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
intake_routes = pytest.importorskip("app.api.intake_routes")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only
_AUTH = {"Authorization": "Bearer ignored-overridden"}


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity):
    def _override():
        return identity

    return _override


@pytest.fixture
def superadmin_engine(engine):
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


def _create_space(engine, name: str) -> uuid.UUID:
    from sqlalchemy import text

    space_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": name},
        )
    return space_id


def _cleanup(engine, space_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id})


def _answers(engine, space_id, intake_id) -> dict[str, tuple]:
    """Return ``{field_key: (value, value_json, space_id)}`` read in the intake's space."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        rows = conn.execute(
            text(
                f"SELECT field_key, value, value_json, space_id FROM {SCHEMA}.intake_answers "
                "WHERE intake_id = :id"
            ),
            {"id": intake_id},
        ).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}


def _client(monkeypatch, engine, superadmin_engine, identity):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.api.auth_routes import protected_router

    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: engine)
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: superadmin_engine)
    protected_router.include_router(intake_routes.intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    app.dependency_overrides[get_current_identity] = _as(identity)
    return app, TestClient(app)


def test_user_create_seeds_project_name(engine, superadmin_engine, monkeypatch):
    space_id = _create_space(engine, "Seed Org")
    app, client = _client(monkeypatch, engine, superadmin_engine, _user(space_id))
    try:
        resp = client.post("/intakes", json={"client_name": "Marktintrede Benelux"}, headers=_AUTH)
        assert resp.status_code == 201, resp.text
        answers = _answers(engine, space_id, resp.json()["id"])
        assert "project_name" in answers, "create must seed the project_name answer"
        value, value_json, row_space = answers["project_name"]
        assert value == "Marktintrede Benelux"
        assert value_json is None, "a plain string goes in `value` (answers API split)"
        assert str(row_space) == str(space_id), "the seed lands in the intake's own space"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


@pytest.mark.parametrize("body", [{}, {"client_name": ""}, {"client_name": "   "}])
def test_blank_or_missing_does_not_seed(engine, superadmin_engine, monkeypatch, body):
    space_id = _create_space(engine, "No Seed Org")
    app, client = _client(monkeypatch, engine, superadmin_engine, _user(space_id))
    try:
        resp = client.post("/intakes", json=body, headers=_AUTH)
        assert resp.status_code == 201, resp.text
        answers = _answers(engine, space_id, resp.json()["id"])
        assert "project_name" not in answers, (
            "no body value -> no project_name seed (never the trigger-mirrored org name)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


def test_superadmin_create_seeds_and_keeps_client_name(engine, superadmin_engine, monkeypatch):
    space_id = _create_space(engine, "Acme Organisation")
    app, client = _client(monkeypatch, engine, superadmin_engine, _superadmin())
    try:
        resp = client.post(
            f"/intakes?space_id={space_id}", json={"client_name": "Project X"}, headers=_AUTH
        )
        assert resp.status_code == 201, resp.text
        before = _answers(engine, space_id, resp.json()["id"])
        assert before["project_name"][0] == "Project X"
        assert str(before["project_name"][2]) == str(space_id)
        assert before.get("client_name", (None,))[0] == "Acme Organisation", (
            "the 0008 trigger's client_name answer (organisation name) is untouched"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


def test_client_name_answer_untouched_by_seed(engine, superadmin_engine, monkeypatch):
    """The 0008 trigger's ``client_name`` answer is exactly what it was without the seed."""
    space_id = _create_space(engine, "Untouched Org")
    app, client = _client(monkeypatch, engine, superadmin_engine, _user(space_id))
    try:
        with_seed = client.post("/intakes", json={"client_name": "P1"}, headers=_AUTH).json()["id"]
        without = client.post("/intakes", json={}, headers=_AUTH).json()["id"]
        a = _answers(engine, space_id, with_seed)
        b = _answers(engine, space_id, without)
        # Same set of trigger-seeded keys besides project_name; the seed adds exactly one row.
        assert set(a) - set(b) == {"project_name"}
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


def test_existing_row_is_not_overwritten(engine, superadmin_engine, monkeypatch, set_space):
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    space_id = _create_space(engine, "Conflict Org")
    app, client = _client(monkeypatch, engine, superadmin_engine, _user(space_id))
    try:
        intake_id = client.post(
            "/intakes", json={"client_name": "Original"}, headers=_AUTH
        ).json()["id"]
        intake = SimpleNamespace(id=uuid.UUID(intake_id), space_id=space_id)
        with Session(engine) as s:
            set_space(s, space_id)
            intake_routes._seed_project_name_answer(s, intake, "Replacement")
            s.commit()
        assert _answers(engine, space_id, intake_id)["project_name"][0] == "Original"
        # Sanity: the read helper sees the row count unchanged (one project_name row).
        with engine.begin() as conn:
            set_space(conn, space_id)
            n = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :id AND field_key = 'project_name'"
                ),
                {"id": intake_id},
            ).scalar_one()
        assert n == 1
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)
