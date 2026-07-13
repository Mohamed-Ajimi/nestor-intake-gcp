"""Storage upload behavior suite (DOC-02 / D-02 / D-03 / D-04 / D-05 / D-07) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED until 09-02 lands
``POST /intakes/{intake_id}/storage/uploads`` (backend/app/api/storage_routes.py).
Do NOT stub the route here — 09-02 turns this file GREEN.

Every test fakes the ``app.storage.gcs`` seam via the ``fake_gcs`` conftest
fixture — no real bucket, no network, no credentials. What this file pins:

| Test                             | Proves                                             |
|----------------------------------|----------------------------------------------------|
| ``test_upload_writes_scoped_key``| the stored key is SERVER-authored and starts with  |
|                                  | ``{space_id}/{intake_id}/attachments/`` (DOC-02,   |
|                                  | D-05 — client path never trusted).                 |
| ``test_upload_413_over_cap``     | a body over 25 MB -> EXACTLY 413, nothing uploaded |
|                                  | (D-02 Whisper cap / D-03 authoritative read).      |
| ``test_upload_415_bad_type``     | an extension outside the D-04 allowlist -> EXACTLY |
|                                  | 415, nothing uploaded.                             |
| ``test_audio_upload_creates_source`` | an audio upload creates a SPACE-SCOPED         |
|                                  | ``intake_sources`` row whose ``storage_path`` is   |
|                                  | the object key, in the same request (D-07).        |

Harness style: engine factories patched only (``session_mod``), identity
overridden with a fabricated ``Identity`` — clones test_ai_transcribe.py /
test_intake_cross_tenant.py.
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

# D-02: the 25 MB per-file ceiling (Whisper per-file limit; < Cloud Run's 32 MB cap).
MAX_BYTES = 25 * 1024 * 1024


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch ONLY the engine factories session.py imported (testcontainer swap)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(storage_routes_mod.storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_space_and_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Storage upload space"},
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
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ===========================================================================
# Case: scoped key — the stored key is server-authored under {space}/{intake}/
# ===========================================================================


def test_upload_writes_scoped_key(engine, set_space, fake_gcs, monkeypatch):
    """A valid attachment upload stores under ``{space_id}/{intake_id}/attachments/``.

    DOC-02: the byte stream flows THROUGH the backend to the faked seam;
    D-05: the key is server-authored (uuid-prefixed, sanitized name) — the
    client only supplied a filename, never a path.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    payload = b"%PDF-1.4 fake-but-harmless"

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("verslag.pdf", payload, "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"valid upload should be 201, got {resp.status_code} (body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, (
            f"exactly one seam upload expected, got {len(fake_gcs['uploads'])}."
        )
        recorded = fake_gcs["uploads"][0]
        expected_prefix = f"{space}/{intake_id}/attachments/"
        assert recorded["key"].startswith(expected_prefix), (
            f"key must be server-authored under {expected_prefix!r}, "
            f"got {recorded['key']!r} (D-05 / DOC-02)."
        )
        assert recorded["data"] == payload, "the uploaded bytes must flow through unmodified."

        body = resp.json()
        assert body.get("path") == recorded["key"], (
            "response `path` must echo the stored object key."
        )
        assert body.get("size") == len(payload), "response `size` must be the byte count."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: 413 — over the 25 MB cap (D-02 / D-03 authoritative read)
# ===========================================================================


def test_upload_413_over_cap(engine, set_space, fake_gcs, monkeypatch):
    """A body over 25 MB -> EXACTLY 413; the seam is never called (D-02/D-03)."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    oversize = b"x" * (MAX_BYTES + 1)

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("groot-verslag.pdf", oversize, "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 413, (
            f"an over-cap upload must be EXACTLY 413, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake_gcs["uploads"] == [], (
            "a rejected oversize body must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: 415 — extension outside the D-04 allowlist
# ===========================================================================


def test_upload_415_bad_type(engine, set_space, fake_gcs, monkeypatch):
    """A disallowed extension/MIME -> EXACTLY 415; the seam is never called (D-04)."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 415, (
            f"a disallowed type must be EXACTLY 415, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake_gcs["uploads"] == [], (
            "a type-rejected body must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: audio upload auto-registers a space-scoped intake_sources row (D-07)
# ===========================================================================


def test_audio_upload_creates_source(engine, set_space, fake_gcs, monkeypatch):
    """An audio upload creates an ``intake_sources`` row: storage_path == the key.

    D-07: the row is written in the SAME request (same session/tx as the
    ownership read) and carries the intake's space_id, so the Phase-7
    transcribe flow can find the object without any client bookkeeping.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("gesprek.m4a", b"\x00\x01fake-audio", "audio/mp4")},
            data={"category": "audio"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"audio upload should be 201, got {resp.status_code} (body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, "the audio bytes must reach the seam once."
        key = fake_gcs["uploads"][0]["key"]
        assert key.startswith(f"{space}/{intake_id}/audio/"), (
            f"audio key must live under the audio category, got {key!r}."
        )

        # The intake_sources row exists, is space-scoped, and points at the key.
        with engine.begin() as conn:
            set_space(conn, space)
            row = conn.execute(
                text(
                    f"SELECT storage_path, kind, space_id FROM {SCHEMA}.intake_sources "
                    "WHERE intake_id = :id"
                ),
                {"id": intake_id},
            ).first()
        assert row is not None, (
            "D-07: an audio upload must create an intake_sources row in the same request."
        )
        assert row[0] == key, (
            f"intake_sources.storage_path must equal the object key: {row[0]!r} != {key!r}."
        )
        assert row[1] == "audio", f"intake_sources.kind must be 'audio', got {row[1]!r}."
        assert str(row[2]) == str(space), "the source row must carry the intake's space_id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
