"""Storage delete behavior suite (D-09 / T-09-09) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED until 09-02 lands
``DELETE /intakes/{intake_id}/storage/objects`` (backend/app/api/storage_routes.py).
Do NOT stub the route here — 09-02 turns this file GREEN.

The ``app.storage.gcs`` seam is faked (``fake_gcs``) — no bucket, no network.
What this file pins:

| Test                        | Proves                                              |
|-----------------------------|-----------------------------------------------------|
| ``test_delete_cleans_ref``  | deleting an audio object removes the GCS object     |
|                             | (seam call) AND the matching ``intake_sources`` row |
|                             | in ONE request — no dangling ref, no dangling       |
|                             | object (D-09 / T-09-09).                            |

Harness style clones test_ai_transcribe.py (engine factories patched only,
fabricated Identity override).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")

from app.api import storage_routes as storage_routes_mod  # noqa: E402  (RED until 09-02)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(storage_routes_mod.storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_intake_with_audio_object(engine, set_space, space_id, intake_id, key) -> uuid.UUID:
    """Seed org + intake + one 'audio' intake_sources row pointing at ``key``."""
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Storage delete space"},
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
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_sources "
                "(id, space_id, intake_id, kind, storage_path, file_name, language) "
                "VALUES (:id, :space_id, :intake_id, 'audio', :storage_path, "
                "'gesprek.m4a', 'nl')"
            ),
            {
                "id": source_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "storage_path": key,
            },
        )
    return source_id


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ===========================================================================
# Case: delete removes the object AND cleans the intake_sources ref (D-09)
# ===========================================================================


def test_delete_cleans_ref(engine, set_space, fake_gcs, monkeypatch):
    """Deleting an audio key removes the object AND the matching source row.

    ONE request: the (faked) ``delete_object`` receives the exact key, and the
    ``intake_sources`` row whose ``storage_path`` matches is gone when re-read
    as the owner — no dangling DB ref pointing at a deleted object (T-09-09),
    no orphaned object left behind a deleted ref.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/audio/{uuid.uuid4()}-gesprek.m4a"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, key)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [key]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"own-space delete should be 200, got {resp.status_code} (body={resp.text!r})."
        )
        body = resp.json()
        assert body.get("removed", 0) >= 1, (
            f"the response must report at least one removed object, got {body!r}."
        )

        # The object delete reached the seam with the exact key.
        assert fake_gcs["deletes"] == [{"key": key}], (
            f"delete_object must be called once with the exact key, "
            f"got {fake_gcs['deletes']!r}."
        )

        # The matching intake_sources ref is GONE (re-read as the owner).
        with engine.begin() as conn:
            set_space(conn, space)
            remaining = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.intake_sources "
                    "WHERE storage_path = :key"
                ),
                {"key": key},
            ).scalar_one()
        assert remaining == 0, (
            "D-09: the intake_sources row matching the deleted key must be removed "
            f"in the SAME request ({remaining} row(s) left dangling)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
