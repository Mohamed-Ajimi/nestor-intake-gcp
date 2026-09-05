"""F-01 field-level confidentiality suite (SEC-03 / D-23.2-03 / D-23.2-04).

WHY THIS FILE EXISTS. ``app/data/pulse_intake_v1.json`` marks the ``strategic_perspective``
section ``"admin_only": true``, and the section's own description reads *"Visible only to
admin, not to the client and not in the handoff PDF."* Until phase 23.2 that flag was honoured
ONLY in the browser (``IntakeForm.tsx:164``, ``intake.$id.results.tsx:163``). The server handed
the content to any authenticated caller through three routes that phase 23.1 correctly kept
OPEN to ``role=user`` — so a client with a devtools tab read the operator's private bias
analysis of their own account.

THE THREE HOPS THIS FILE PINS (23.2-CONTEXT.md § 2):

| # | Hop                                                   | Evidence                    |
|---|-------------------------------------------------------|-----------------------------|
| 1 | ``list_answers`` returned every row, unfiltered        | ``intake_routes.py:559``    |
| 2 | ``output_parsed`` carried ``bias_radar`` + ``blind_spots`` verbatim | ``ai/skills/apply.py:17`` |
| 4a| ``list_templates`` served the admin-only section's labels + help text | ``intake_routes.py:482`` |

Hop 3 (the context-pack generator's LLM INPUT) is plan 23.2-07 and is deliberately NOT here.
Hop 5 (the research brief) needs no work: research reads are gated.

THE POLARITY IS ``!= "superadmin"``, NOT ``== "user"`` — deny by default. Every filtered-side
test below drives a ``role="user"`` identity, and every unfiltered-side test drives the
superadmin literal; a third role value would land on the filtered side, which is the point.

ANTI-VACUITY, IN BOTH DIRECTIONS. "no admin key in the response" is trivially true of an EMPTY
response, and an empty response is exactly what an over-wide filter produces. So every
withholding assertion is paired with a positive one:

* the answers tests assert the three ORDINARY keys ARE present, and that the admin loop
  actually ran ``len(admin_only_field_keys()) == 4`` times;
* ``test_admin_only_answers_really_exist_in_the_database`` reads the four rows straight out of
  Postgres under the owning space's GUC, so the user-side test cannot pass because the seed
  never landed;
* the ``output_parsed`` tests assert an EXACT surviving key SET, which fails on an under-drop
  AND on an over-drop;
* the superadmin half of every pair asserts the content is still fully served — a blanket
  filter (the ``== "user"`` polarity bug's twin) fails there.

HARNESS: cloned from ``test_client_surface_open.py`` (identity fabrication via
``dependency_overrides``, ``_patch_engine_factories`` so the REAL repo dependencies run against
the testcontainer, the GUC-then-INSERT seeding shape) plus ``test_intake_routes.py``'s
``superadmin_engine`` connect-as fixture, which the superadmin read path needs (the 0003
``*_superadmin_all`` bypass policy matches on ``current_user``, not on a GUC).

NO FIELD-KEY LITERAL IS HAND-WRITTEN. Every key set comes from ``app.intake_canonical``
(D-23.2-02), so a fifth admin-only field added to the JSON tightens these tests automatically
instead of silently leaving a hole.
"""

from __future__ import annotations

import json
import uuid

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
canonical = pytest.importorskip("app.intake_canonical")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}

# Three ORDINARY (client-visible) field keys used as the anti-vacuity positive control.
# Derived, never hand-written: take them from the canonical MEMBERSHIP set minus the
# CONFIDENTIALITY set, sorted for determinism. Using canonical_field_keys() as the source
# also proves they are real fields of the form rather than invented strings.
_ORDINARY_KEYS = sorted(canonical.canonical_field_keys() - canonical.admin_only_field_keys())[:3]

# The common prefix of the three ``blind_spots_*`` admin-only field keys. This is NOT itself a
# field key (no such key exists in the schema) — it is the top-level ``output_parsed`` key whose
# object members map onto those three (``AIReviewPanel.tsx:127-129``).
_BLIND_SPOTS_PREFIX = "blind_spots"

# The five ORDINARY top-level keys of the AI's ``output_parsed`` (app/ai/skills/apply.py:17-21,
# app/ai/prompts.py:120-148). This is the MODEL OUTPUT shape, which is not the schema's shape and
# is not derivable from it — but not one ADMIN key appears here: the two withheld keys are
# derived from admin_only_field_keys() in _full_output_parsed() below.

_ORDINARY_OUTPUT_KEYS = {
    "decision_or_goal",
    "research_questions_refined",
    "additional_questions",
    "dropped_questions",
    "gaps_flagged",
}


def _full_output_parsed() -> dict:
    """The SEVEN-key ``output_parsed`` the apply skill writes (apply.py:17-21).

    The two admin-only members are keyed from ``admin_only_field_keys()`` rather than typed
    out: ``bias_radar`` IS an admin field key, and ``blind_spots`` is the common prefix of the
    three ``blind_spots_*`` admin field keys, whose object members map onto them one-for-one
    (``AIReviewPanel.tsx:127-129`` does exactly that mapping).
    """
    admin = canonical.admin_only_field_keys()
    bias_key = next(k for k in sorted(admin) if not k.startswith(_BLIND_SPOTS_PREFIX))
    nested_members = sorted(
        k.removeprefix(_BLIND_SPOTS_PREFIX + "_")
        for k in admin
        if k.startswith(_BLIND_SPOTS_PREFIX + "_")
    )
    out = {
        "decision_or_goal": {"nl": "doel", "fr": "but", "en": "goal"},
        "research_questions_refined": [{"text": "q1"}],
        "additional_questions": [{"text": "q2"}],
        "dropped_questions": [],
        "gaps_flagged": {"nl": "gaten", "fr": "trous", "en": "gaps"},
        bias_key: {"nl": "PRIVATE bias", "fr": "PRIVE", "en": "PRIVATE bias"},
        _BLIND_SPOTS_PREFIX: {m: {"nl": f"PRIVATE {m}"} for m in nested_members},
    }
    return out


def _expected_admin_output_keys() -> set[str]:
    """The top-level ``output_parsed`` keys a non-superadmin must NOT receive.

    Derived exactly as the production helper derives them, so this test does not encode a
    second, independently-drifting copy of the rule.
    """
    admin = canonical.admin_only_field_keys()
    return {k for k in _full_output_parsed() if k in admin or any(a.startswith(k + "_") for a in admin)}


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no own space)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches: run the REAL repo dependencies against the testcontainer
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the user-path engine factory ``session.py`` / ``ai_session.py`` imported."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    ai_session = pytest.importorskip("app.db.ai_session")
    monkeypatch.setattr(ai_session, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin engine factory (the cross-tenant read path)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


# Local testcontainer credential ONLY for the connect-as app_superadmin engine (mirrors
# test_intake_routes.py / test_admin_routes.py) — never a production secret.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (connect-as, not SET ROLE).

    ``current_user = 'app_superadmin'`` makes the 0003 ``*_superadmin_all`` bypass policy
    match, which is how the superadmin read path reaches another space's rows with NO GUC set.
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


# ---------------------------------------------------------------------------
# App builder — the REAL intake_router under the default-deny protected_router
# ---------------------------------------------------------------------------


def _build_app():
    """Mirror ``app/main.py``'s wiring for the intake surface (no health probes / lifespan)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


# ---------------------------------------------------------------------------
# Seeding helpers (GUC-then-INSERT shape, from test_client_surface_open.py)
# ---------------------------------------------------------------------------


def _seed_space(engine, space_id) -> None:
    """Insert an organization (a space). ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Field confidentiality space"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="draft") -> None:
    """Insert one intake at an explicit status, GUC set so the 0002 WITH CHECK passes."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, :status)"
            ),
            {"id": intake_id, "space_id": space_id, "status": status},
        )


def _seed_answers(engine, set_space, space_id, intake_id, keys) -> None:
    """Upsert one answer row per key under the owning space's GUC.

    ``ON CONFLICT ... DO UPDATE`` rather than a plain INSERT because migration 0008's
    ``prefill_intake_answers`` AFTER-INSERT trigger has already written a ``client_name``
    row for this intake; a plain INSERT of the same key would hit
    ``uq_intake_answers_intake_field``.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        for key in keys:
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intake_answers "
                    "(intake_id, space_id, field_key, value) "
                    "VALUES (:intake_id, :space_id, :field_key, :value) "
                    "ON CONFLICT (intake_id, field_key) DO UPDATE SET value = EXCLUDED.value"
                ),
                {
                    "intake_id": intake_id,
                    "space_id": space_id,
                    "field_key": key,
                    "value": f"seeded-{key}",
                },
            )


def _seed_skill_run(
    engine, set_space, space_id, intake_id, run_id, output_parsed=None, raw_json=None
) -> None:
    """Insert one ``skill_runs`` row under the owning space GUC.

    ``raw_json`` writes a pre-serialised JSON document straight into the JSONB column, which
    is how a NON-OBJECT (legacy/odd) ``output_parsed`` is seeded.
    """
    from sqlalchemy import text

    if raw_json is None and output_parsed is not None:
        raw_json = json.dumps(output_parsed)

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.skill_runs "
                "(id, space_id, intake_id, skill, status, output_parsed, cost_estimate_usd) "
                "VALUES (:id, :space_id, :intake_id, 'apply-intake-skill', 'succeeded', "
                ":output_parsed, 0.01)"
            ),
            {
                "id": run_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "output_parsed": raw_json,
            },
        )


def _cleanup(engine, *space_ids) -> None:
    """Delete the seeded organizations (CASCADE removes intakes/answers/runs)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for space_id in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": space_id},
            )


# ===========================================================================
# Hop 1 — GET /intakes/{id}/answers
# ===========================================================================


def test_admin_only_answers_really_exist_in_the_database(engine, set_space, monkeypatch):
    """The seed lands: all four admin-only answer rows are in Postgres for this intake.

    Without this, ``test_answers_hide_admin_only_fields_from_a_user`` cannot distinguish
    "the projection withheld them" from "the seed never wrote them" — the classic vacuous
    pass. Read under the OWNING space's GUC, i.e. exactly the rows a user-path repo can see.
    """
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    admin_keys = sorted(canonical.admin_only_field_keys())
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_answers(engine, set_space, space, intake_id, admin_keys + _ORDINARY_KEYS)

        with engine.begin() as conn:
            set_space(conn, space)
            rows = conn.execute(
                text(
                    f"SELECT field_key FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :iid AND field_key = ANY(:keys)"
                ),
                {"iid": intake_id, "keys": admin_keys},
            ).scalars().all()

        assert sorted(rows) == admin_keys, (
            f"the admin-only answer seed did not land: expected {admin_keys}, got "
            f"{sorted(rows)}. Every withholding assertion in this file is vacuous until "
            f"this passes."
        )
        assert len(admin_keys) == 4, (
            f"the canonical schema is expected to define EXACTLY 4 admin-only field keys "
            f"today; got {len(admin_keys)} ({admin_keys}). If a fifth was added, the "
            f"derived filters close automatically — update this number deliberately."
        )
    finally:
        _cleanup(engine, space)


def test_answers_hide_admin_only_fields_from_a_user(engine, set_space, monkeypatch):
    """Hop 1: a role=user reading their OWN intake's answers gets EXACTLY 200 and NO admin key.

    EXACTLY 200 — this route is row 4 of the ten pinned client routes. This plan changes the
    BODY, never the reachability.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    admin_keys = sorted(canonical.admin_only_field_keys())
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_answers(engine, set_space, space, intake_id, admin_keys + _ORDINARY_KEYS)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/answers", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/answers must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). D-23.2-03 is a PROJECTION, not a gate."
        )
        returned = {row["field_key"] for row in resp.json()}

        # Anti-vacuity: the route returned real data, so "no admin key" means something.
        for key in _ORDINARY_KEYS:
            assert key in returned, (
                f"ordinary field {key!r} is missing from a client's own answers "
                f"(got {sorted(returned)}). The filter is OVER-WIDE — it is withholding "
                f"client-visible content, which breaks the live intake form."
            )

        checked = 0
        for key in admin_keys:
            assert key not in returned, (
                f"admin-only field {key!r} reached a role=user caller (F-01 hop 1, "
                f"23.2-CONTEXT.md § 2). The section carries admin_only=true and its own "
                f"description says it is not visible to the client."
            )
            checked += 1
        assert checked == len(canonical.admin_only_field_keys()) == 4, (
            f"the admin loop must actually run 4 times; it ran {checked}. A zero-iteration "
            f"loop asserts nothing."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_answers_expose_admin_only_fields_to_a_superadmin(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin still receives ALL answers, admin-only included (D-23.2-03 polarity).

    This is the assertion a blanket filter fails. The AIReviewPanel's accept/edit/reject UX
    reads exactly this content, so a filter applied to every role silently kills it.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    admin_keys = sorted(canonical.admin_only_field_keys())
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_answers(engine, set_space, space, intake_id, admin_keys + _ORDINARY_KEYS)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        resp = TestClient(app).get(f"/intakes/{intake_id}/answers", headers=AUTH)

        assert resp.status_code == 200, (
            f"a superadmin read of the answers must be EXACTLY 200, got {resp.status_code} "
            f"({resp.text!r})."
        )
        returned = {row["field_key"] for row in resp.json()}

        checked = 0
        for key in admin_keys:
            assert key in returned, (
                f"admin-only field {key!r} was withheld from a SUPERADMIN (got "
                f"{sorted(returned)}). The projection polarity is inverted or the filter is "
                f"unconditional — the AI review panel depends on this content."
            )
            checked += 1
        assert checked == len(canonical.admin_only_field_keys()) == 4
        for key in _ORDINARY_KEYS:
            assert key in returned, f"ordinary field {key!r} withheld from a superadmin."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Hop 2 — GET /intakes/{id}/skill-runs/{run_id} (output_parsed)
# ===========================================================================


def test_skill_run_output_parsed_filtered_for_a_user(engine, set_space, monkeypatch):
    """Hop 2: a role=user gets EXACTLY 200 and an EXACT five-key ``output_parsed``.

    Set EQUALITY, not ``"bias_radar" not in ...``: an equality fails on an under-drop (the
    disclosure this exists to stop) AND on an over-drop (which would break the client's
    proposal tick, ``IntakeForm.tsx:16``). Row 8 of the ten pinned client routes.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_skill_run(
            engine, set_space, space, intake_id, run_id, output_parsed=_full_output_parsed()
        )
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs/{run_id}", headers=AUTH
        )

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/skill-runs/{{run_id}} must stay OPEN to role=user "
            f"(EXACTLY 200), got {resp.status_code} ({resp.text!r})."
        )
        assert set(resp.json()["output_parsed"]) == _ORDINARY_OUTPUT_KEYS, (
            f"output_parsed key set for a role=user must be EXACTLY "
            f"{sorted(_ORDINARY_OUTPUT_KEYS)}, got "
            f"{sorted(resp.json()['output_parsed'])}. Under-drop = F-01 hop 2 disclosure; "
            f"over-drop = a broken client proposal tick."
        )
        # The derived drop rule must remove exactly two of the seven keys today.
        assert len(_expected_admin_output_keys()) == 2, (
            f"the derived rule (K in admin OR any admin key startswith K + '_') must drop "
            f"EXACTLY 2 of the 7 output keys today; it selects "
            f"{sorted(_expected_admin_output_keys())}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_skill_run_output_parsed_complete_for_a_superadmin(
    engine, superadmin_engine, set_space, monkeypatch
):
    """A superadmin receives all SEVEN ``output_parsed`` keys — the AIReviewPanel's contract.

    ``AIReviewPanel.tsx:114-129`` reads ``parsed.bias_radar`` and
    ``parsed.blind_spots.{upstream,downstream,perspectief}``. Dropping them for the operator
    empties two panels with no error anywhere.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    full = _full_output_parsed()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_skill_run(engine, set_space, space, intake_id, run_id, output_parsed=full)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        resp = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs/{run_id}", headers=AUTH
        )

        assert resp.status_code == 200, (
            f"a superadmin full skill-run read must be EXACTLY 200, got {resp.status_code} "
            f"({resp.text!r})."
        )
        assert set(resp.json()["output_parsed"]) == set(full), (
            f"a superadmin must receive the UNFILTERED output_parsed (all {len(full)} keys); "
            f"got {sorted(resp.json()['output_parsed'])}."
        )
        assert len(full) == 7, "the apply skill writes 7 top-level output keys (apply.py:17-21)."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_skill_run_null_output_parsed_stays_none_for_both_roles(
    engine, superadmin_engine, set_space, monkeypatch
):
    """``output_parsed IS NULL`` -> 200 with ``None`` for a user AND for a superadmin.

    A projection that assumes a dict turns a running/failed run into a 500 on the client's
    polling path.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_skill_run(engine, set_space, space, intake_id, run_id, output_parsed=None)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        for label, identity in (("user", _user(space)), ("superadmin", _superadmin())):
            app.dependency_overrides[get_current_identity] = _as(identity)
            resp = TestClient(app).get(
                f"/intakes/{intake_id}/skill-runs/{run_id}", headers=AUTH
            )
            assert resp.status_code == 200, (
                f"a NULL output_parsed must still be EXACTLY 200 for {label}, got "
                f"{resp.status_code} ({resp.text!r})."
            )
            assert resp.json()["output_parsed"] is None, (
                f"a NULL output_parsed must project as None for {label}, got "
                f"{resp.json()['output_parsed']!r}."
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_visible_output_parsed_helper_is_total_on_non_dict_values():
    """The projection helper NEVER raises on odd data — it returns a non-dict unchanged.

    ⚠ MEASURED DEVIATION FROM PLAN 23.2-06 (recorded in the SUMMARY). The plan asked for an
    END-TO-END assertion that a JSON *list* in ``output_parsed`` returns 200 with the value
    unchanged. That is NOT satisfiable and never was: ``SkillRunFullView.output_parsed`` is
    declared ``dict | None`` (``intake_routes.py:209``), so constructing the response model
    with a list raises ``pydantic.ValidationError`` -> 500 INSIDE THE HANDLER, at HEAD,
    entirely independent of any projection. Making the route answer 200 there would mean
    WIDENING a pinned client route's response contract, which neither D-23.2-03 nor
    D-23.2-04 authorises and which this phase's own scope fences forbid.

    So the true, in-scope half of that criterion is pinned HERE, where it IS true: the helper
    is total. It must not be the thing that raises.
    """
    from app.api.intake_routes import _visible_output_parsed

    for odd in ([1, 2], "a string", 42, True):
        assert _visible_output_parsed(odd, role="user") is odd, (
            f"the projection must return a non-dict value ({odd!r}) UNCHANGED and must "
            f"never raise; a filter is not a validator."
        )
        assert _visible_output_parsed(odd, role="superadmin") is odd
    assert _visible_output_parsed(None, role="user") is None
    assert _visible_output_parsed(None, role="superadmin") is None


# ===========================================================================
# Hop 4a — GET /intakes/templates
# ===========================================================================


def test_templates_hide_the_admin_only_section_from_a_user(engine, set_space, monkeypatch):
    """Hop 4a: a role=user gets EXACTLY 200 and 13 of 14 sections, none ``admin_only``.

    Schema disclosure, not answer disclosure: the section's labels and help text tell a
    client exactly which field keys to ask for. Row 2 of the ten pinned client routes — this
    is the widest blast radius of the ten, so the 200 is asserted exactly.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    total = len(canonical.CANONICAL_TEMPLATE_SCHEMA["sections"])
    app = _build_app()
    try:
        _seed_space(engine, space)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get("/intakes/templates", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/templates must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} ({resp.text!r}). Gating it renders the client form "
            f"schema-less."
        )
        sections = resp.json()[0]["schema"]["sections"]
        assert len(sections) == 13, (
            f"a role=user must receive 13 of the {total} canonical sections; got "
            f"{len(sections)} (F-01 hop 4a)."
        )
        assert total - len(sections) == 1, (
            f"exactly ONE section must be withheld ({total} - 13); "
            f"{total - len(sections)} were."
        )
        offenders = [s.get("id") for s in sections if s.get("admin_only")]
        assert offenders == [], (
            f"admin_only sections reached a role=user: {offenders}. The section's own "
            f"description reads 'Visible only to admin, not to the client'."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_templates_expose_the_admin_only_section_to_a_superadmin():
    """A superadmin still receives all 14 sections, exactly one of them ``admin_only``.

    The handler is DB-free (D-CANON: shared product config, no per-space rows), so no engine
    patch and no seeded space are needed for either role.
    """
    from fastapi.testclient import TestClient

    total = len(canonical.CANONICAL_TEMPLATE_SCHEMA["sections"])
    app = _build_app()
    try:
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        resp = TestClient(app).get("/intakes/templates", headers=AUTH)

        assert resp.status_code == 200, (
            f"a superadmin template read must be EXACTLY 200, got {resp.status_code} "
            f"({resp.text!r})."
        )
        sections = resp.json()[0]["schema"]["sections"]
        assert len(sections) == total == 14, (
            f"a superadmin must receive the FULL {total}-section form; got {len(sections)}."
        )
        admin_sections = [s.get("id") for s in sections if s.get("admin_only")]
        assert len(admin_sections) == 1, (
            f"exactly one canonical section is admin_only today; the superadmin response "
            f"carries {admin_sections}."
        )
    finally:
        app.dependency_overrides.clear()


def test_templates_never_mutate_the_shared_canonical_constant():
    """The filtered response must not be produced by MUTATING module-level state.

    T-23.2-06-05: a ``.pop()``-style implementation would corrupt ``CANONICAL_TEMPLATE_SCHEMA``
    (and ``client_visible_schema()``'s ONE shared object) for the entire process lifetime —
    every later request, every role. Two independent pins:

    1. after a user request, the shared constant still has all 14 sections;
    2. TWO sequential user requests both return 13. A mutating handler passes the first and
       fails the second, which is precisely the bug a single-request test cannot see.
    """
    from fastapi.testclient import TestClient

    total_before = len(canonical.CANONICAL_TEMPLATE_SCHEMA["sections"])
    app = _build_app()
    try:
        app.dependency_overrides[get_current_identity] = _as(_user(uuid.uuid4()))
        client = TestClient(app)

        first = client.get("/intakes/templates", headers=AUTH)
        second = client.get("/intakes/templates", headers=AUTH)

        assert first.status_code == second.status_code == 200
        assert len(first.json()[0]["schema"]["sections"]) == 13, (
            "the FIRST user request must already be filtered to 13 sections."
        )
        assert len(second.json()[0]["schema"]["sections"]) == 13, (
            "the SECOND sequential user request returned a different section count — the "
            "handler is MUTATING shared module state (T-23.2-06-05)."
        )
        assert len(canonical.CANONICAL_TEMPLATE_SCHEMA["sections"]) == total_before == 14, (
            f"GET /intakes/templates mutated the shared CANONICAL_TEMPLATE_SCHEMA: it had "
            f"{total_before} sections and now has "
            f"{len(canonical.CANONICAL_TEMPLATE_SCHEMA['sections'])}. Every later request "
            f"in this process — including a superadmin's — is now wrong."
        )
        assert len(canonical.client_visible_schema()["sections"]) == 13, (
            "the shared client-visible schema was mutated by serving it."
        )
    finally:
        app.dependency_overrides.clear()
