"""Research-surface cross-tenant denial suite (T-16-08 / QA-01 / D-04) — the day-one gate.

The Phase-16 research seam adds two new tenant-crossing surfaces — the trigger
(``POST /intakes/{id}/research``) and the SSE progress stream
(``GET /intakes/{id}/research/stream``). Pitfall 5: a fresh tenant surface is a fresh chance
to reintroduce the broken-RLS class of bug, so the denial tests land WITH the surface (never
after). This suite is the HTTP-level proof that both new surfaces deny cross-tenant access:

| Test                                    | Proves                                                   |
|-----------------------------------------|----------------------------------------------------------|
| ``trigger_cross_tenant_404``            | space-B user POST of space-A's intake → EXACTLY 404      |
|                                         | (existence-hidden), space-A intake NOT flipped, no run.  |
| ``stream_cross_tenant_404``            | space-B user GET of space-A's intake stream → EXACTLY 404|
|                                         | (raised pre-stream; never 403/200).                      |
| ``stream_null_space_403``               | a null-space user's stream pre-flight → EXACTLY 403.     |

DESIGN mirrors ``test_intake_cross_tenant.py``: the engine FACTORIES that ``session.py`` /
``ai_session.py`` import are patched to the conftest engines so the REAL ``get_tenant_repo``
+ the stream's ``tenant_session`` reads run verbatim locally; ``get_current_identity`` is
overridden to a fabricated Identity (the IdP is the one boundary that cannot run locally).
The trigger runs as a superadmin (the real actor) via the connect-as ``app_superadmin``
engine; a superadmin scoping a chosen client is space-narrowed by the intake's own space, so
a space-B superadmin path can't reach space-A here because the override yields a SPACE-B
*user* for the denial cases (the existence-hidden 404 is the user-path wall).
"""

from __future__ import annotations

import uuid

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


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engines(monkeypatch, user_engine) -> None:
    """Patch the engine factories session.py + ai_session.py imported (see test_research_routes)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(research_mod.research_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_space(engine, space_id, name) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": name},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="decomposed") -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status))"
            ),
            {"id": intake_id, "space_id": space_id, "status": status},
        )


def _read_intake_status(engine, set_space, space_id, intake_id) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _count_runs(engine, set_space, space_id, intake_id) -> int:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.research_runs WHERE intake_id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _cleanup(engine, *space_ids) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": sid},
            )


# ===========================================================================
# trigger_cross_tenant — space-B user POST space-A intake → EXACTLY 404
# ===========================================================================


def test_trigger_cross_tenant_404(
    engine, set_space, two_spaces, monkeypatch, fake_tribunal_client
):
    """space-B user POST of space-A's research trigger → 404; space-A intake untouched.

    The scoped ``repo.get`` excludes space-A's intake from space-B's scope → ``None`` →
    the handler raises an existence-hidden 404 (never 403/200). No status flip, no run
    inserted, no seam call — the cross-tenant write never begins.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a = uuid.uuid4()
    _seed_space(engine, space_a, "Space A (research denial)")
    _seed_space(engine, space_b, "Space B (research denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="decomposed")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))  # caller = space-B
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_a}/research",
            headers={"Authorization": "Bearer overridden"},
        )
        assert resp.status_code == 404, (
            f"cross-tenant trigger must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/200 would leak existence (BOLA/IDOR)."
        )
        assert str(intake_a) not in resp.text, "404 body leaked the foreign intake id."
        # The foreign intake is untouched (still decomposed) and no run was inserted.
        assert _read_intake_status(engine, set_space, space_a, intake_a) == "decomposed"
        assert _count_runs(engine, set_space, space_a, intake_a) == 0
        assert not fake_tribunal_client["create_run"], "no seam call for a denied trigger."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# stream_cross_tenant — space-B user GET space-A stream → EXACTLY 404
# ===========================================================================


def test_stream_cross_tenant_404(engine, set_space, two_spaces, monkeypatch):
    """space-B user GET of space-A's research stream → plain-GET 404 raised pre-stream."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a = uuid.uuid4()
    _seed_space(engine, space_a, "Space A (stream denial)")
    _seed_space(engine, space_b, "Space B (stream denial)")
    _seed_intake(engine, set_space, space_a, intake_a, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))  # caller = space-B
    try:
        # Plain GET (NOT streaming): the 404 is raised in the pre-flight BEFORE the stream.
        r = TestClient(app).get(
            f"/intakes/{intake_a}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 404, (
            f"cross-tenant stream must be existence-hidden 404, never 403/200; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_a, space_b)


# ===========================================================================
# stream_null_space — a null-space user's stream pre-flight → EXACTLY 403
# ===========================================================================


def test_stream_null_space_403(engine, set_space, monkeypatch):
    """A ``user`` Identity with ``space_id=None`` → EXACTLY 403 on the stream pre-flight (D-04)."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    _seed_space(engine, space, "Space (null-space stream)")
    _seed_intake(engine, set_space, space, intake_id, status="in_research")
    _patch_engines(monkeypatch, engine)

    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_null_space_user())
    try:
        r = TestClient(app).get(
            f"/intakes/{intake_id}/research/stream",
            headers={"Authorization": "Bearer overridden"},
        )
        assert r.status_code == 403, (
            f"null-space user must be default-denied 403 on the pre-flight; got {r.status_code}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
