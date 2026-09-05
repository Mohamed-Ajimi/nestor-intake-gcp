"""AI-02 contract suite — ``generate-context-pack`` ported (RED scaffold).

Authored against the FINAL contract; RED until 07-05 lands. The Claude call is
FAKED. What this pins (07-VALIDATION, AI-02 / Pitfall 7 — storage upload defers
to Phase 9, so ``text_content`` is written now, no GCS):

- a ``research_artifacts`` row is written with ``text_content`` populated and
  ``embed_status='pending'`` (so the 07-06 embed step can pick it up);
- ``intakes.status`` advances to ``decomposed`` (the in-scope flow ceiling);
- ``intakes.context_pack_artifact_id`` points at the new artifact;
- ``skill_runs.applied_at`` is set (D-09 — marks finalized output) and status is
  ``succeeded``.

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

from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-05)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
CONTEXT_PACK_MODEL = "claude-sonnet-4-5"  # D-06


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
            {"id": space_id, "name": "AI context-pack space"},
        )
    with engine.begin() as conn:
        set_space(conn, space_id)
        # Seeded at 'validated_by_client' — the ONLY status the context-pack skill may
        # advance from (D-23.1-05 / _CONTEXT_PACK_TRANSITIONS), and the only phase in
        # which the UI renders its launch button (NextStepBanner.tsx:270 via
        # intake-phase.ts:55). This seed was 'reviewed' until 23.1-04, back when the
        # `decomposed` bump was unconditional; that value made this suite assert the
        # defect — that a context pack could jump an intake straight past client
        # validation. Every assertion below is unchanged.
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'validated_by_client')"
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


def test_context_pack_writes_artifact_and_decomposes(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """Faked Claude -> research_artifacts row + status=decomposed + applied_at."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    fake = fake_anthropic("# Context Pack\n\nDe gedecomponeerde briefing.")
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
            f"/intakes/{intake_id}/skills/context-pack",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"context-pack should accept + schedule, got {resp.status_code} "
            f"(body={resp.text!r})."
        )

        assert fake.calls, "Claude was never called for the context pack."
        assert fake.calls[0]["model"] == CONTEXT_PACK_MODEL, (
            f"context-pack must call {CONTEXT_PACK_MODEL!r}, "
            f"got {fake.calls[0].get('model')!r}."
        )

        with engine.begin() as conn:
            set_space(conn, space)
            artifact = conn.execute(
                text(
                    f"SELECT id, text_content, embed_status "
                    f"FROM {SCHEMA}.research_artifacts WHERE intake_id = :iid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"iid": intake_id},
            ).first()
            intake_row = conn.execute(
                text(
                    f"SELECT status, context_pack_artifact_id "
                    f"FROM {SCHEMA}.intakes WHERE id = :iid"
                ),
                {"iid": intake_id},
            ).first()
            skill_row = conn.execute(
                text(
                    f"SELECT status, applied_at FROM {SCHEMA}.skill_runs "
                    "WHERE intake_id = :iid ORDER BY created_at DESC LIMIT 1"
                ),
                {"iid": intake_id},
            ).first()

        assert artifact is not None, "a research_artifacts row must be written."
        artifact_id, text_content, embed_status = artifact
        assert text_content, "the artifact must persist text_content (Phase-9 GCS deferred)."
        assert embed_status == "pending", (
            f"embed_status must be 'pending' for the 07-06 embed step, got {embed_status!r}."
        )

        assert intake_row is not None
        intake_status, context_pack_artifact_id = intake_row
        assert intake_status == "decomposed", (
            f"context-pack must advance the intake to 'decomposed', got {intake_status!r}."
        )
        assert str(context_pack_artifact_id) == str(artifact_id), (
            "intakes.context_pack_artifact_id must point at the new artifact."
        )

        assert skill_row is not None
        skill_status, applied_at = skill_row
        assert skill_status == "succeeded", (
            f"terminal status must be 'succeeded' (D-09), got {skill_status!r}."
        )
        assert applied_at is not None, "skill_runs.applied_at must mark the finalized output."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ---------------------------------------------------------------------------
# D-23.2-01 — hop 3 of F-01: admin-only answers must never enter the LLM prompt.
# ---------------------------------------------------------------------------

#: Two ORDINARY (non-admin-only) canonical field keys used as the anti-vacuity
#: control. They must SURVIVE the filter, otherwise "no admin sentinel in the
#: prompt" is satisfied by an empty prompt just as well as by a correct filter.
_ORDINARY_SEED = {
    "decision_or_goal": "ORDINARYSENTINEL-decision-or-goal",
    "audience_description": "ORDINARYSENTINEL-audience-description",
}


def _admin_seed() -> dict:
    """One DISTINCT, NON-EMPTY sentinel per admin-only key — derived, never hand-listed.

    Derived from ``admin_only_field_keys()`` (D-23.2-02) so a fifth admin-only field
    added to ``pulse_intake_v1.json`` later is seeded and asserted automatically.

    NON-EMPTY is mandatory: ``_format_intake_markdown`` skips ``value in (None, "")``,
    so an empty admin answer is absent from the prompt even with NO filter in place, and
    the test would be green before the fix — decoration, not a gate.
    """
    from app.intake_canonical import admin_only_field_keys

    return {key: f"ADMINSENTINEL-{key}-VALUE" for key in sorted(admin_only_field_keys())}


def _seed_answers(engine, set_space, space_id, intake_id, answers: dict) -> None:
    """Insert ``intake_answers`` rows under the space GUC (the 0002 WITH CHECK)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        for field_key, value in answers.items():
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intake_answers "
                    "(space_id, intake_id, field_key, value) "
                    "VALUES (:space_id, :intake_id, :field_key, :value)"
                ),
                {
                    "space_id": space_id,
                    "intake_id": intake_id,
                    "field_key": field_key,
                    "value": value,
                },
            )


def test_context_pack_prompt_excludes_admin_only_answers(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """D-23.2-01 / F-01 hop 3 — admin-only answers never reach the context-pack prompt.

    The generated pack lands as ``research_artifacts.text_content``, which
    ``GET /intakes/{id}/context-pack`` (``intake_routes.py:629``) serves to ``role=user``
    by design. So anything in the PROMPT can come back out as prose the client reads.
    This case therefore asserts on the CAPTURED PROMPT, not on the response body — the
    filter must be on the INPUT, because no output filter removes a paraphrase.

    The filter is UNCONDITIONAL, and this case is driven as a SUPERADMIN on purpose:
    ``ai_router`` is superadmin-gated (D-23.1-02), so a superadmin is the ONLY reachable
    caller. A filter keyed on ``identity.role`` would never fire, and would fail here.
    """
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    from app.ai.prompts import CONTEXT_PACK_SKILL_PROMPT
    from app.intake_canonical import admin_only_field_keys

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    admin_seed = _admin_seed()
    fake = fake_anthropic("# Context Pack\n\nDe gedecomponeerde briefing.")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake(engine, set_space, space, intake_id)
        _seed_answers(engine, set_space, space, intake_id, admin_seed)
        _seed_answers(engine, set_space, space, intake_id, _ORDINARY_SEED)
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/context-pack",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"context-pack should accept + schedule, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake.calls, "Claude was never called for the context pack."

        prompt = fake.calls[0]["messages"][0]["content"]

        # --- THE SEED LANDED. "The filter worked" and "the seed never landed" produce the
        #     same absence; this separates them.
        with engine.begin() as conn:
            set_space(conn, space)
            seeded_admin = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :iid AND field_key = ANY(:keys)"
                ),
                {"iid": intake_id, "keys": sorted(admin_only_field_keys())},
            ).scalar_one()
        assert seeded_admin == len(admin_seed) == 4, (
            f"the admin-only answers must EXIST in the database — seeded "
            f"{len(admin_seed)}, found {seeded_admin}. Without this, the absence "
            f"assertions below would pass on a seed that never landed."
        )

        # --- NEITHER the admin VALUE nor the admin KEY may appear. The key matters on its
        #     own: `_format_intake_markdown` emits `**{field_key}**: {value}`, so the key
        #     is disclosed even when the value is short.
        checked = 0
        for field_key, sentinel in admin_seed.items():
            assert sentinel not in prompt, (
                f"admin-only answer value for {field_key!r} reached the LLM prompt: "
                f"{sentinel!r} is present. The pack generated from this prompt is served "
                f"to role=user by GET /intakes/{{id}}/context-pack (D-23.2-01)."
            )
            assert field_key not in prompt, (
                f"admin-only field KEY {field_key!r} reached the LLM prompt "
                f"(_format_intake_markdown emits '**{{field_key}}**: ...')."
            )
            checked += 1
        assert checked == len(admin_only_field_keys()) == 4, (
            f"anti-vacuity: the absence loop must run once per admin-only key — checked "
            f"{checked}, admin_only_field_keys() has {len(admin_only_field_keys())}."
        )

        # --- ANTI-VACUITY: an empty prompt, a vanished intake, or an over-wide filter
        #     that dropped everything would satisfy the four assertions above.
        for field_key, sentinel in _ORDINARY_SEED.items():
            assert sentinel in prompt, (
                f"ordinary answer {field_key!r} is MISSING from the prompt — the filter "
                f"is over-wide and the operator is paying for a pack built from nothing."
            )

        # --- NO PROMPT-INSTRUCTION WORKAROUND. Telling the model to omit the strategic
        #     analysis is not a control: the content would still be in the prompt, and the
        #     model's compliance is not a boundary.
        assert fake.calls[0]["system"] == CONTEXT_PACK_SKILL_PROMPT, (
            "the context-pack system prompt must be byte-identical to "
            "CONTEXT_PACK_SKILL_PROMPT — a 'please omit ...' instruction is not a "
            "confidentiality control (D-23.2-01)."
        )

        # --- THE PACK STILL LANDS. A filter that emptied `answers` would break the flow.
        with engine.begin() as conn:
            set_space(conn, space)
            artifact = conn.execute(
                text(
                    f"SELECT id, text_content FROM {SCHEMA}.research_artifacts "
                    "WHERE intake_id = :iid ORDER BY created_at DESC LIMIT 1"
                ),
                {"iid": intake_id},
            ).first()
            intake_row = conn.execute(
                text(
                    f"SELECT status, context_pack_artifact_id "
                    f"FROM {SCHEMA}.intakes WHERE id = :iid"
                ),
                {"iid": intake_id},
            ).first()

        assert artifact is not None, "a research_artifacts row must still be written."
        artifact_id, text_content = artifact
        assert text_content, "the artifact must still persist text_content."
        assert intake_row is not None
        assert intake_row[0] == "decomposed", (
            f"the intake must still advance to 'decomposed', got {intake_row[0]!r}."
        )
        assert str(intake_row[1]) == str(artifact_id), (
            "intakes.context_pack_artifact_id must still point at the new artifact."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
