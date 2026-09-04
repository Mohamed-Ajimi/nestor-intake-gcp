"""D-09 status-contract suite — terminal skill_run status is EXACTLY succeeded/failed.

Authored against the FINAL contract; RED until 07-05 lands. The single most
fragile cross-component contract (frontend ``SkillRunProgress`` polls these exact
strings — skill-run-status-succeeded-contract memory): the terminal status a
finished AI run writes MUST be the literal ``"succeeded"`` on success and the
literal ``"failed"`` on failure — never a synonym (``"success"`` / ``"done"`` /
``"complete"`` / ``"error"`` / ``"failure"``), and the read API must surface that
string verbatim.

This drives the apply endpoint twice (faked Claude): a valid-JSON run -> the row
status is EXACTLY ``"succeeded"``; a non-JSON run -> EXACTLY ``"failed"``. Both
assert the value is NOT in a forbidden-synonym set, so a future refactor that
renames a status fails here loudly.

RED discipline: external deps ``importorskip``; impl HARD-imported.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-05)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"

# The ONLY allowed terminal values (D-09). Anything else is a contract break.
TERMINAL_SUCCESS = "succeeded"
TERMINAL_FAILURE = "failed"
# Synonyms a careless refactor might introduce — all forbidden as terminal values.
FORBIDDEN_TERMINAL = {
    "success",
    "succeed",
    "done",
    "complete",
    "completed",
    "ok",
    "error",
    "errored",
    "failure",
    "fail",
}


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """FIXTURE-ONLY (plan 23.1-11) — the identity these route-driving cases now need.

    ``ai_router`` carries a router-level ``Depends(superadmin_gate)`` (D-23.1-02), so a
    role=``user`` caller gets an existence-hidden 404 and never reaches the pipeline these
    cases measure. Re-identifying the CALLER changes nothing they assert: the write path
    takes the audited ``create_in_space`` branch against the intake's OWN space, so every
    row still lands in that space. The user-path RLS confinement is proved by
    ``test_ai_cross_tenant.py``, which drives ``tenant_session`` directly and needs no route.
    """
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)



def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine, sa_engine=None) -> None:
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    if sa_engine is not None:
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path routes through
        # get_superadmin_engine (D-05), so the gated cases need it patched too.
        monkeypatch.setattr(
            ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
        )


#: Password granted to app_superadmin for the connect-as engine (test only — the SAME
#: literal test_mail_endpoints / test_operator_verb_gate use, so the role's password stays
#: stable no matter which suite touches it first).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


@pytest.fixture
def superadmin_engine(engine):
    """FIXTURE-ONLY (plan 23.1-11) — a second engine connecting AS ``app_superadmin``.

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match. ``app_superadmin`` is a plain
    non-superuser LOGIN role, so this proves the bypass POLICY + GRANTs, not superuser
    ambient authority. Shape copied from ``test_operator_verb_gate.superadmin_engine``.
    """
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


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(ai_routes_mod.ai_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI status-contract space"},
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


def _latest_status(engine, set_space, space_id, intake_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT status FROM {SCHEMA}.skill_runs WHERE intake_id = :iid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"iid": intake_id},
        ).scalar_one()


def test_terminal_success_status_is_exactly_succeeded(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """A successful AI run terminates with the literal status ``"succeeded"``."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_anthropic(json.dumps({"research_questions_refined": []}))
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        client.post(
            f"/intakes/{intake_id}/skills/apply",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        status_val = _latest_status(engine, set_space, space, intake_id)
        assert status_val == TERMINAL_SUCCESS, (
            f"D-09: success must be EXACTLY {TERMINAL_SUCCESS!r}, got {status_val!r}."
        )
        assert status_val not in FORBIDDEN_TERMINAL, (
            f"D-09: {status_val!r} is a forbidden synonym for {TERMINAL_SUCCESS!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_terminal_failure_status_is_exactly_failed(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """A failed AI run terminates with the literal status ``"failed"``."""
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_anthropic("dit is geen geldige json")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        client.post(
            f"/intakes/{intake_id}/skills/apply",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        status_val = _latest_status(engine, set_space, space, intake_id)
        assert status_val == TERMINAL_FAILURE, (
            f"D-09: failure must be EXACTLY {TERMINAL_FAILURE!r}, got {status_val!r}."
        )
        assert status_val not in FORBIDDEN_TERMINAL, (
            f"D-09: {status_val!r} is a forbidden synonym for {TERMINAL_FAILURE!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
