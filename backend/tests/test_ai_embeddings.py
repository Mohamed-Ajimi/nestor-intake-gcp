"""AI-04 contract suite — embeddings write to ``artifact_embeddings`` (RED scaffold).

Authored against the FINAL contract; RED until 07-06 lands. The OpenAI call is
FAKED (``fake_openai`` fixture, default 1536-float vector). What this pins
(07-VALIDATION, AI-04 — the WRITE half; the cross-tenant SEARCH proof lives in
``test_ai_search_cross_tenant.py``):

- the embed step requests ``model='text-embedding-3-small'`` with
  ``dimensions=1536`` (D-02);
- the written ``artifact_embeddings`` rows carry the caller's ``space_id`` (never
  cross-tenant) and a non-null ``embedding``;
- the source ``research_artifacts`` row's ``embed_status`` advances off
  ``pending`` (idempotency hint for re-runs).

RED discipline: external deps ``importorskip``; impl HARD-imported.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-06)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
EMBED_MODEL = "text-embedding-3-small"  # D-02
EMBED_DIMENSIONS = 1536  # D-02 — text-embedding-3-small dimensions


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


def _seed_intake_with_pending_artifact(engine, set_space, space_id, intake_id):
    """Seed org + intake + a research_artifact (text_content, embed_status='pending')."""
    from sqlalchemy import text

    artifact_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI embeddings space"},
        )
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'decomposed')"
            ),
            {"id": intake_id, "space_id": space_id},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_artifacts "
                "(id, space_id, intake_id, text_content, embed_status) "
                "VALUES (:id, :space_id, :intake_id, :txt, 'pending')"
            ),
            {
                "id": artifact_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "txt": "De gedecomponeerde context pack tekst om te embedden.",
            },
        )
    return artifact_id


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def test_embeddings_request_dimensions_and_space_scoped_rows(
    engine, set_space, monkeypatch, fake_openai
):
    """Faked OpenAI -> dimensions=1536 request + space-scoped artifact_embeddings."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_openai()  # default 1536-float vector
    monkeypatch.setattr(ai_clients_mod, "openai_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        artifact_id = _seed_intake_with_pending_artifact(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/embeddings",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"embeddings should accept + schedule, got {resp.status_code} (body={resp.text!r})."
        )

        # REQUEST shape — model + dimensions (D-02 / generate-embeddings.ts:38).
        assert fake.embedding_calls, "OpenAI embeddings.create was never called."
        first = fake.embedding_calls[0]
        assert first.get("model") == EMBED_MODEL, (
            f"embeddings must request {EMBED_MODEL!r}, got {first.get('model')!r}."
        )
        assert first.get("dimensions") == EMBED_DIMENSIONS, (
            f"embeddings must request dimensions={EMBED_DIMENSIONS}, "
            f"got {first.get('dimensions')!r}."
        )

        # WRITE shape — space-scoped rows with a non-null embedding.
        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT space_id, embedding IS NOT NULL AS has_vec "
                    f"FROM {SCHEMA}.artifact_embeddings WHERE artifact_id = :aid"
                ),
                {"aid": artifact_id},
            ).all()
            embed_status = conn.execute(
                text(
                    f"SELECT embed_status FROM {SCHEMA}.research_artifacts WHERE id = :aid"
                ),
                {"aid": artifact_id},
            ).scalar_one()

        assert rows, "the embed step must write at least one artifact_embeddings row."
        for row_space_id, has_vec in rows:
            assert str(row_space_id) == str(space), (
                "every embedding row must carry the caller's space_id (no cross-tenant)."
            )
            assert has_vec, "the embedding vector must be persisted (non-null)."
        assert embed_status != "pending", (
            f"the source artifact's embed_status must advance off 'pending', got {embed_status!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
