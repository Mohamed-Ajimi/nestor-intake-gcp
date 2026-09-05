"""AI-03 contract suite — ``structure-answers`` + ``extract-insights`` (RED scaffold).

Authored against the FINAL contract; RED until 07-07 (+ the 0009 migration that
adds ``transcripts`` / ``extracted_insights`` and the ``intake_answers`` parity
columns) land. The Claude call is FAKED — both functions return a JSON ARRAY in
```json fences (structure-answers.ts:55 / extract-insights.ts), so the port uses
an ``extract_json_array`` parser. What this pins (07-VALIDATION, AI-03):

- ``structure-answers`` (model ``claude-sonnet-4-6``): the parsed array maps a
  transcript into ``intake_answers`` rows carrying ``extracted_by='llm'`` and the
  caller's ``space_id`` (space-scoped write);
- ``extract-insights`` (model ``claude-sonnet-4-6``): the parsed array writes
  ``extracted_insights`` rows carrying the caller's ``space_id``.

RED discipline: external deps ``importorskip``; impl HARD-imported. Seeding the
``transcripts`` / ``intake_sources`` rows only runs once 0009 + impl exist; the
module is a COLLECTION-ERROR RED before that (impl import fails first).
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

from app.api import ai_routes as ai_routes_mod  # noqa: E402  (RED until 07-07)
from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
import app.ai.clients as ai_clients_mod  # noqa: E402  (RED until 07-03)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
STRUCTURE_MODEL = "claude-sonnet-4-6"  # D-06 — structure-answers + extract-insights


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


def _seed_intake_with_transcript(engine, set_space, space_id, intake_id):
    """Seed org + intake + one intake_source + one transcript chunk (all space-scoped)."""
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI structure/extract space"},
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
                f"INSERT INTO {SCHEMA}.intake_sources (id, space_id, intake_id, kind) "
                "VALUES (:id, :space_id, :intake_id, 'audio')"
            ),
            {"id": source_id, "space_id": space_id, "intake_id": intake_id},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.transcripts "
                "(id, space_id, intake_id, source_id, chunk_index, text) "
                "VALUES (gen_random_uuid(), :space_id, :intake_id, :source_id, 0, :txt)"
            ),
            {
                "space_id": space_id,
                "intake_id": intake_id,
                "source_id": source_id,
                "txt": "Onze grootste pijn is dat klanten afhaken bij de prijs.",
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
# structure-answers — JSON array -> intake_answers (extracted_by='llm', scoped)
# ===========================================================================


def test_structure_answers_writes_llm_scoped_answers(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """Faked Claude array -> space-scoped intake_answers with extracted_by='llm'."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    answers = [
        {"field_key": "decision_or_goal", "value": "Prijsperceptie verbeteren", "confidence": 0.82},
    ]
    fake = fake_anthropic("```json\n" + json.dumps(answers) + "\n```")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake_with_transcript(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/structure-answers",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"structure-answers should accept + schedule, got {resp.status_code}."
        )

        assert fake.calls, "Claude was never called for structure-answers."
        assert fake.calls[0]["model"] == STRUCTURE_MODEL, (
            f"structure-answers must call {STRUCTURE_MODEL!r}, "
            f"got {fake.calls[0].get('model')!r}."
        )

        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT space_id, extracted_by FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :iid AND extracted_by = 'llm'"
                ),
                {"iid": intake_id},
            ).all()
        assert rows, "structure-answers must write at least one extracted_by='llm' answer."
        for row_space_id, extracted_by in rows:
            assert str(row_space_id) == str(space), (
                "every LLM-extracted answer must carry the caller's space_id (no cross-tenant)."
            )
            assert extracted_by == "llm", "provenance must be extracted_by='llm'."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_structure_answers_filters_to_canonical_keys(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """D-23.2-16 (F-08) — an invented ``field_key`` is DROPPED; canonical keys are written.

    Drives the skill on an intake whose ``template_id`` IS NULL — the normal creation path
    (``frontend/src/lib/api/intakes.ts`` posts only ``client_name``), and precisely the
    condition under which the pre-fix guard ``if valid_keys and field_key not in valid_keys``
    was disabled: no template row -> empty key list -> an empty set PERMITTED everything.

    Admin-only keys stay IN scope here. This skill runs on the superadmin-gated ``ai_router``
    and structuring an operator interview into ``bias_radar`` is exactly its job, so the
    filter is schema MEMBERSHIP (``canonical_field_keys()``), never the client-visible
    subset. ``bias_radar`` is the assertion that fails if someone swaps in the confidentiality
    set — plan 23.2-07 filters admin-only keys OUT of the context-pack prompt, which is the
    deliberate OPPOSITE of this call site.
    """
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    from app.ai.prompts import STRUCTURE_ANSWERS_SYSTEM_PROMPT
    from app.intake_canonical import admin_only_field_keys, canonical_field_keys

    space = uuid.uuid4()
    intake_id = uuid.uuid4()

    # Anchor the fixture's own claims against the schema rather than hard-coding them: if a
    # future edit moves bias_radar out of the admin-only section, this says so here instead
    # of silently weakening the case below.
    assert "bias_radar" in admin_only_field_keys(), (
        "this case exists to prove an ADMIN-ONLY canonical key is still written."
    )
    assert {"decision_or_goal", "audience_description"} <= canonical_field_keys()
    assert "totally_invented_key" not in canonical_field_keys()

    answers = [
        {"field_key": "decision_or_goal", "value": "Prijsperceptie verbeteren", "confidence": 0.82},
        {"field_key": "audience_description", "value": "MKB-inkopers", "confidence": 0.71},
        # Admin-only, and LEGITIMATE for this operator-run skill (D-23.2-16).
        {"field_key": "bias_radar", "value": "Overschat prijsgevoeligheid", "confidence": 0.55},
        # Pure model invention — no such field exists in the canonical form.
        {"field_key": "totally_invented_key", "value": "Verzonnen waarde", "confidence": 0.40},
    ]
    fake = fake_anthropic("```json\n" + json.dumps(answers) + "\n```")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake_with_transcript(engine, set_space, space, intake_id)
        with engine.begin() as conn:
            set_space(conn, space)
            template_id = conn.execute(
                text(f"SELECT template_id FROM {SCHEMA}.intakes WHERE id = :iid"),
                {"iid": intake_id},
            ).scalar_one()
        assert template_id is None, (
            "the precondition of F-08 is an intake with NO template_id (the normal creation "
            f"path); the seed produced {template_id!r}."
        )

        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/structure-answers",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"structure-answers should accept + schedule, got {resp.status_code}."
        )
        assert fake.calls, "Claude was never called for structure-answers."

        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT field_key, value FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :iid AND extracted_by = 'llm'"
                ),
                {"iid": intake_id},
            ).all()
        written = {field_key: value for field_key, value in rows}

        # The invented key must never reach intake_answers: such a row renders in no form
        # field, survives every later read, and is interpolated into the context-pack prompt.
        assert "totally_invented_key" not in written, (
            "F-08: the model's invented field_key was written to intake_answers "
            f"(row: {written.get('totally_invented_key')!r})."
        )
        # Anti-vacuity: a fix that dropped EVERYTHING would satisfy the line above.
        assert set(written) == {"decision_or_goal", "audience_description", "bias_radar"}, (
            f"expected exactly the three canonical keys to be written, got {sorted(written)}."
        )
        assert len(rows) == 3, f"expected exactly 3 extracted_by='llm' rows, got {len(rows)}."
        # Admin-only key written with its real value (not blanked, not dropped).
        assert written["bias_radar"] == "Overschat prijsgevoeligheid"

        # The prompt must still TELL the model which keys exist, or extraction quality drops
        # and the model invents. Pre-fix this block was the literal "[]".
        prompt = fake.calls[0]["messages"][0]["content"]
        assert "# Template velden" in prompt
        keys_block = prompt.split("# Transcript")[0].split("# Template velden", 1)[1]
        assert json.loads(keys_block.strip()) == sorted(canonical_field_keys()), (
            "the prompt's key list must be the canonical schema, SORTED — a frozenset's "
            "iteration order is not stable across processes and a non-reproducible prompt "
            "makes a paid call's audit record worthless."
        )
        assert "decision_or_goal" in prompt and "bias_radar" in prompt
        found = sum(1 for key in canonical_field_keys() if key in prompt)
        assert found == len(canonical_field_keys()) == 29, (
            f"expected all 29 canonical keys in the prompt, found {found}."
        )

        # The system prompt and model are untouched by this change.
        assert fake.calls[0]["system"] == STRUCTURE_ANSWERS_SYSTEM_PROMPT
        assert fake.calls[0]["model"] == STRUCTURE_MODEL
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# extract-insights — JSON array -> extracted_insights (space-scoped)
# ===========================================================================


def test_extract_insights_writes_scoped_insights(
    engine, set_space, monkeypatch, fake_anthropic, superadmin_engine
):
    """Faked Claude array -> space-scoped extracted_insights rows."""
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    intake_id = uuid.uuid4()
    insights = [
        {
            "kind": "pain",
            "label": "Prijsweerstand",
            "summary": "Klanten haken af bij de prijs.",
            "confidence": 0.74,
        },
    ]
    fake = fake_anthropic("```json\n" + json.dumps(insights) + "\n```")
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        _seed_intake_with_transcript(engine, set_space, space, intake_id)
        # FIXTURE-ONLY (plan 23.1-11): the superadmin write path needs its own engine.
        _patch_engine_factories(monkeypatch, engine, superadmin_engine)
        # FIXTURE-ONLY (plan 23.1-11): ai_router is superadmin-gated (D-23.1-02).
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/skills/extract-insights",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"extract-insights should accept + schedule, got {resp.status_code}."
        )

        assert fake.calls, "Claude was never called for extract-insights."
        assert fake.calls[0]["model"] == STRUCTURE_MODEL, (
            f"extract-insights must call {STRUCTURE_MODEL!r}, "
            f"got {fake.calls[0].get('model')!r}."
        )

        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT space_id FROM {SCHEMA}.extracted_insights "
                    "WHERE intake_id = :iid"
                ),
                {"iid": intake_id},
            ).all()
        assert rows, "extract-insights must write at least one extracted_insights row."
        for (row_space_id,) in rows:
            assert str(row_space_id) == str(space), (
                "every insight must carry the caller's space_id (no cross-tenant write)."
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
