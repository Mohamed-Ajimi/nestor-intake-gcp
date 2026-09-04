"""AI-01 contract suite — ``apply-intake-skill`` ported to Cloud Run (RED scaffold).

Authored against the FINAL Phase-7 contract; stays RED until the implementation
plans (07-03 clients, 07-04 session helper, 07-05 apply/context-pack routes) land
and turn it GREEN. The external Claude call is FAKED (``fake_anthropic`` fixture)
— no network, no key. What this suite pins (07-VALIDATION § Phase Requirements →
Test Map, AI-01):

| Case                          | Proves                                                       |
|-------------------------------|-------------------------------------------------------------|
| ``apply_success``             | request used model ``claude-sonnet-4-5`` + the pinned        |
|                               | ``max_tokens``; ``skill_runs.output_parsed`` written; status |
|                               | ``running`` -> ``succeeded``; ``llm_model`` persisted.      |
| ``apply_bad_json_fails``      | non-JSON Claude output -> status ``failed`` AND             |
|                               | ``error_message`` set (D-09 failure path).                  |
| ``apply_truncated_fails``     | ``stop_reason == "max_tokens"`` -> status ``failed`` with a |
|                               | budget-naming ``error_message``, never a parse error and    |
|                               | never a half-parsed ``output_parsed`` (D-4, 260831-lm4).    |

RED discipline (07-01 PLAN): external deps are ``importorskip`` (skip-clean when
absent), but the IMPL modules are HARD-imported, so a missing impl is a
COLLECTION ERROR — the intended Wave-0 RED — never a syntax/fixture error. The
DB-write assertions use the ``engine`` fixture (skips clean without Docker; runs
in CI / Cloud Build). Harness shape copied from ``test_intake_cross_tenant.py``
(dependency-override + engine-factory patch).
"""

from __future__ import annotations

import json
import uuid

import pytest

# External deps — skip-clean when not installed on this box (dev box has none).
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

# Existing app modules (present since Phase 3/4).
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")

# Impl-under-test — HARD import so a missing module is a COLLECTION ERROR (RED)
# until 07-03..07-05 land. Do NOT importorskip these: skipping would mask the
# Wave-0 RED state the PLAN requires.
from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-05)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
APPLY_MODEL = "claude-sonnet-4-5"  # D-06 default for apply-intake-skill
# Raised from the legacy 8192 by quick task 260831-lm4 (the skill now emits every
# generated string in nl+fr+en). It is pinned EXACTLY, and deliberately below the
# ~21333 non-streaming SDK ceiling that `apply.py` documents: a future "just raise
# it" would break the non-streaming call outright rather than buy more room.
APPLY_MAX_TOKENS = 20000


# ---------------------------------------------------------------------------
# Identity fabrication + harness (mirror test_intake_cross_tenant.py)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """FIXTURE-ONLY (plan 23.1-11) — the identity these route-driving cases now need.

    ``ai_router`` carries a router-level ``Depends(superadmin_gate)`` (D-23.1-02), so a
    role=``user`` caller gets an existence-hidden 404 and never reaches the pipeline these
    cases measure. Re-identifying the CALLER changes nothing they assert: the write path
    takes the audited ``create_in_space`` branch against the intake's OWN space
    (``ai_session.create_running_skill_run``), so every row still lands in that space.
    The user-path RLS confinement is proved by ``test_ai_cross_tenant.py``, which drives
    ``tenant_session`` directly and needs no route.
    """
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine, sa_engine=None) -> None:
    """Patch the engine factories ``app.db.ai_session`` imported (PLAN interfaces)."""
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    if sa_engine is not None:
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
            {"id": space_id, "name": "AI apply-skill space"},
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


def _latest_skill_run(engine, set_space, space_id, intake_id):
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT status, output_parsed, error_message, llm_model "
                f"FROM {SCHEMA}.skill_runs WHERE intake_id = :iid "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"iid": intake_id},
        ).first()


# ===========================================================================
# Case: apply_success — valid JSON -> running->succeeded, output_parsed written
# ===========================================================================


def test_apply_skill_success_writes_output_and_succeeds(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """A faked Claude returning valid JSON -> request shape + DB writes + status.

    Asserts (1) the REQUEST used ``claude-sonnet-4-5`` + ``max_tokens=8192``,
    (2) ``skill_runs.output_parsed`` holds the parsed JSON, (3) the terminal
    status is EXACTLY ``succeeded`` (D-09), and (4) ``llm_model`` is persisted.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    parsed = {
        "decision_or_goal": None,
        "research_questions_refined": [],
        "additional_questions": [],
    }
    fake = fake_anthropic(json.dumps(parsed))
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/apply",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        # The endpoint returns immediately (202) with a run id; the bg task runs
        # synchronously under TestClient, so the DB writes are visible below.
        assert resp.status_code in (200, 202), (
            f"apply should accept and schedule the run, got {resp.status_code} "
            f"(body={resp.text!r})."
        )

        # REQUEST shape (legacy parity — apply-intake-skill.ts).
        assert fake.calls, "Claude was never called — the bg task did not run."
        assert fake.calls[0]["model"] == APPLY_MODEL, (
            f"apply must call model {APPLY_MODEL!r}, got {fake.calls[0].get('model')!r}."
        )
        assert fake.calls[0]["max_tokens"] == APPLY_MAX_TOKENS, (
            f"apply must request max_tokens={APPLY_MAX_TOKENS}, "
            f"got {fake.calls[0].get('max_tokens')!r}."
        )

        # DB writes + status lifecycle.
        row = _latest_skill_run(engine, set_space, space, intake_id)
        assert row is not None, "no skill_runs row was written for the intake."
        status_val, output_parsed, error_message, llm_model = row
        assert status_val == "succeeded", (
            f"terminal status must be EXACTLY 'succeeded' (D-09), got {status_val!r}."
        )
        assert output_parsed is not None, "output_parsed must hold the parsed JSON."
        assert error_message is None, "a successful run must not set error_message."
        assert llm_model == APPLY_MODEL, (
            f"llm_model must persist the resolved id {APPLY_MODEL!r}, got {llm_model!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: apply_bad_json_fails — non-JSON Claude -> status failed + error_message
# ===========================================================================


def test_apply_skill_bad_json_marks_failed(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """Non-JSON Claude output -> the run is finalized ``failed`` with an error.

    Drives the D-09 failure path: ``extract_json`` cannot parse the model output,
    so the run terminates ``failed`` and records ``error_message`` (never left
    ``running``, never ``succeeded``).
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_anthropic("Sorry, ik kan hier geen JSON van maken.")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/apply",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"apply should still accept + schedule, got {resp.status_code}."
        )

        row = _latest_skill_run(engine, set_space, space, intake_id)
        assert row is not None, "no skill_runs row was written."
        status_val, _output_parsed, error_message, _llm_model = row
        assert status_val == "failed", (
            f"a JSON-parse failure must terminate 'failed' (D-09), got {status_val!r}."
        )
        assert error_message, "a failed run must record a non-empty error_message."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: apply_truncated_fails — stop_reason "max_tokens" -> failed, loudly
# ===========================================================================


def test_apply_skill_truncated_response_fails_loudly(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """A response cut off at the budget fails with a message that NAMES the budget.

    D-4 (quick task 260831-lm4). Requiring nl+fr+en for every generated string made a
    ``max_tokens`` cut-off realistic for the first time. Without this guard the
    truncated JSON is merely unparseable, so the operator sees a generic parse error
    and concludes the MODEL misbehaved — when the actual cause is the token budget.
    The response text here is deliberately VALID JSON: the test would pass vacuously
    against a parse-error implementation if the payload were garbage.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_anthropic(json.dumps({"decision_or_goal": None}))

    # Mark the response truncated without teaching the shared fixture a new knob.
    inner_create = fake.messages.create

    def _truncated_create(**kwargs):
        message = inner_create(**kwargs)
        message.stop_reason = "max_tokens"
        return message

    fake.messages.create = _truncated_create
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/apply",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"apply should still accept + schedule, got {resp.status_code}."
        )

        row = _latest_skill_run(engine, set_space, space, intake_id)
        assert row is not None, "no skill_runs row was written."
        status_val, output_parsed, error_message, _llm_model = row
        assert status_val == "failed", (
            f"a truncated response must terminate 'failed', got {status_val!r}."
        )
        assert error_message, "a truncated run must record a non-empty error_message."
        assert str(APPLY_MAX_TOKENS) in error_message, (
            "the error must NAME the budget that was hit — that is the whole point of "
            f"the guard; got {error_message!r}."
        )
        assert output_parsed is None, (
            "a truncated response must not persist a half-parsed object, got "
            f"{output_parsed!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
