"""AI-05 contract suite — ``transcribe-audio`` ported (RED scaffold).

Authored against the FINAL contract; RED until 07-07 (+ 0009 ``transcripts`` /
``intake_sources`` tables) land. The Whisper call AND the audio download are
FAKED — real audio fetch couples to GCS (Phase 9 / D-08), so Phase 7 builds +
unit-tests the logic with a faked transcription (no bytes off the wire). What
this pins (07-VALIDATION, AI-05):

- the request uses ``model='whisper-1'`` + ``response_format='verbose_json'``
  (so ``.segments`` come back) + the source ``language``;
- the faked verbose_json segments are written as chunked ``transcripts`` rows,
  each carrying the caller's ``space_id`` (space-scoped, no cross-tenant write).

RED discipline: external deps ``importorskip``; impl HARD-imported. The audio
download seam is monkeypatched with ``raising=False`` (its exact name is fixed in
07-07); the openai client seam (``app.ai.clients.openai_client``) is required.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-07)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)
import app.ai.skills as ai_skills_mod  # noqa: E402  (RED until 07-07)
from app.ai.skills import transcribe as transcribe_mod  # noqa: E402  (Phase 9 seam swap)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
WHISPER_MODEL = "whisper-1"  # D-06


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(ai_routes_mod.ai_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_intake_with_audio_source(engine, set_space, space_id, intake_id):
    """Seed org + intake + one 'audio' intake_source (storage refs, no real file)."""
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI transcribe space"},
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
                "(id, space_id, intake_id, kind, file_name, language) "
                "VALUES (:id, :space_id, :intake_id, 'audio', 'gesprek.mp3', 'nl')"
            ),
            {"id": source_id, "space_id": space_id, "intake_id": intake_id},
        )
    return source_id


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def test_download_delegates_to_gcs(monkeypatch):
    """The REAL ``download_audio_bytes`` delegates to ``app.storage.gcs.download_bytes``.

    Phase 9 seam swap: the body no longer raises NotImplementedError — it reads the
    object the ``intake_sources`` row points at, keyed off ``storage_path``, through the
    ``app.storage.gcs.download_bytes`` seam (no DB session, no inline SDK client). This
    test patches THAT seam with a capture-fake and asserts (1) it was called with the
    EXACT storage_path from the source DTO and (2) its bytes are returned verbatim.
    """
    gcs_mod = pytest.importorskip("app.storage.gcs")

    captured: dict[str, object] = {}
    sentinel = b"\x00\x01real-gcs-audio-bytes"

    def _capture(key: str) -> bytes:
        captured["key"] = key
        return sentinel

    # Patch the seam the transcribe module imported (`from app.storage import gcs`).
    monkeypatch.setattr(gcs_mod, "download_bytes", _capture)

    key = "space-uuid/intake-uuid/audio/uuid-gesprek.m4a"
    result = transcribe_mod.download_audio_bytes({"storage_path": key})

    assert captured.get("key") == key, (
        f"download_audio_bytes must delegate with the source's storage_path, "
        f"got {captured.get('key')!r} != {key!r}."
    )
    assert result == sentinel, "the seam's bytes must be returned verbatim."


def test_transcribe_faked_whisper_writes_scoped_transcripts(
    engine, set_space, monkeypatch, fake_openai
):
    """Faked Whisper -> verbose_json request + space-scoped transcripts rows (no audio)."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_openai(
        transcript_text="Dit is het gesprek.",
        transcript_language="nl",
        transcript_segments=[
            (0.0, 3.0, "Dit is het eerste deel."),
            (3.0, 6.5, "En dit is het tweede deel."),
        ],
    )
    monkeypatch.setattr(ai_clients_mod, "openai_client", lambda *a, **k: fake)
    # Audio download is Phase 9 (GCS) — fake the byte fetch so no network/storage.
    # Seam name is finalized in 07-07; raising=False keeps Wave-0 lenient.
    monkeypatch.setattr(
        ai_skills_mod, "download_audio_bytes", lambda *a, **k: b"\x00\x01fake-audio",
        raising=False,
    )

    app = _build_app()
    try:
        source_id = _seed_intake_with_audio_source(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/sources/{source_id}/transcribe",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"transcribe should accept + schedule, got {resp.status_code} (body={resp.text!r})."
        )

        # REQUEST shape — whisper-1 + verbose_json + language (transcribe-audio.ts:84).
        assert fake.transcription_calls, "Whisper transcriptions.create was never called."
        first = fake.transcription_calls[0]
        assert first.get("model") == WHISPER_MODEL, (
            f"transcribe must call {WHISPER_MODEL!r}, got {first.get('model')!r}."
        )
        assert first.get("response_format") == "verbose_json", (
            "transcribe must request response_format='verbose_json' (gives .segments)."
        )
        assert first.get("language") == "nl", (
            f"transcribe must pass the source language 'nl', got {first.get('language')!r}."
        )

        # WRITE shape — chunked transcripts rows, all space-scoped.
        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT space_id FROM {SCHEMA}.transcripts "
                    "WHERE intake_id = :iid AND source_id = :sid"
                ),
                {"iid": intake_id, "sid": source_id},
            ).all()
        assert rows, "transcribe must write at least one transcripts chunk row."
        for (row_space_id,) in rows:
            assert str(row_space_id) == str(space), (
                "every transcript chunk must carry the caller's space_id (no cross-tenant)."
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
