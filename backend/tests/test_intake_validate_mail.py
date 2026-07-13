"""admin_validated auto-fire suite (NOTIF-02 / D-03 / Pitfall 4) — Plan 10-03.

Drives the REAL ``submit_intake`` handler across the ``reviewed → validated_by_client`` edge
(the ONLY in-repo path to ``validated_by_client``) over live Postgres through a FastAPI
``TestClient``, and asserts:

1. an ``admin_validated`` mail fires to the configured ops address (``NESTOR_ADMIN_EMAIL`` /
   ``Settings.nestor_admin_email``, D-08) on that edge; and
2. the client's validate is NEVER blocked by a mail failure — with ``resend.send``
   monkeypatched to RAISE, the submit STILL returns 200 with status
   ``validated_by_client`` (client-not-blocked, Pitfall 4 / T-10-10).

Same drive-the-real-route + fabricated-Identity + engine-factory-patch scaffold as
``test_intake_cross_tenant.py``.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker); ``importorskip``
guards so the file COLLECTS on the dev box.
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

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
_ADMIN_EMAIL = "ops@agenic.be"


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_reviewed_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID) -> None:
    """Insert an intake already at status='reviewed' (the pre-edge state for the validate)."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, 'reviewed', 'Acme BV')"
        ),
        {"id": intake_id, "space_id": space_id},
    )


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _cleanup_spaces(engine, *space_ids):
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


# ===========================================================================
# admin_validated auto-fires on reviewed -> validated_by_client
# ===========================================================================


def test_admin_validated_fires_on_validate(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """submit_intake on the reviewed→validated_by_client edge fires ONE admin_validated mail.

    The mail goes to the configured ops address (``NESTOR_ADMIN_EMAIL``, D-08); the submit
    returns 200 with status ``validated_by_client``.
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    # Pin the ops address via env so get_settings().nestor_admin_email resolves (not cached).
    monkeypatch.setenv("NESTOR_ADMIN_EMAIL", _ADMIN_EMAIL)

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Validate Mail Space")
        with engine.begin() as conn:
            _insert_reviewed_intake(conn, set_space, space_a, intake_a)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/submit",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, (
            f"validate submit should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["status"] == "validated_by_client", (
            "the submit must advance the intake to validated_by_client"
        )
        assert len(fake_resend["calls"]) == 1, (
            "exactly one admin_validated mail must fire on the validate edge"
        )
        assert fake_resend["calls"][0]["to"] == [_ADMIN_EMAIL], (
            "admin_validated must target the configured NESTOR_ADMIN_EMAIL (D-08)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# a mail failure NEVER fails the client's validate (Pitfall 4 / T-10-10)
# ===========================================================================


def test_validate_not_blocked_by_mail_failure(
    engine, set_space, two_spaces, monkeypatch
):
    """A raised admin_validated send must NOT fail the client's validate (client-not-blocked).

    ``resend.send`` is monkeypatched to RAISE; the submit STILL returns 200 with status
    ``validated_by_client`` (the operator-mail error is silent-logged in a try/except and never
    surfaces to the client — Pitfall 4 / T-10-10).
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    monkeypatch.setenv("NESTOR_ADMIN_EMAIL", _ADMIN_EMAIL)

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Validate No-Block Space")
        with engine.begin() as conn:
            _insert_reviewed_intake(conn, set_space, space_a, intake_a)

        _patch_engine_factories(monkeypatch, engine)

        # Force the admin_validated send to raise.
        import app.mail.resend as resend_mod

        def _raise(*, to, subject, html):  # noqa: ANN001
            raise RuntimeError("resend 500 during admin_validated")

        monkeypatch.setattr(resend_mod, "send", _raise)

        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/submit",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, (
            f"a mail failure must NOT fail the client validate — expected 200, got "
            f"{resp.status_code} ({resp.text!r}) (Pitfall 4 / T-10-10)."
        )
        assert resp.json()["status"] == "validated_by_client", (
            "the intake must STILL be validated_by_client despite the mail failure"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)
