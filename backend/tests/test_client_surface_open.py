"""Client stay-OPEN suite (SEC-01 / TENANT-02) — the counterweight to the denial suites.

WHY THIS FILE EXISTS. Every other authorization suite in this repo proves what is CLOSED.
Nothing proved what must stay OPEN, and that asymmetry is exactly how an authorization phase
breaks a live product: phase 23.1 applies ``superadmin_gate`` to nine operator verbs plus the
whole ``ai_router`` (23.1-CONTEXT.md § 1 / D-23.1-02), and a gate applied one route too wide
is invisible to every type, lint, locale and i18n-audit gate in this project. This file is
the tripwire. It asserts, per route, that a role=``user`` caller scoped to the intake's OWN
space still receives an EXACT 2xx.

THE SEVENTEEN CLIENT ROUTES THAT MUST STAY OPEN. Rows 1-10 are the 23.1 set
(23.1-CONTEXT.md § 1, "THE TRAP"); rows 11-17 were added in phase 23.2 plan 11 and are
DERIVED, not copied — ``_flatten_routes`` finds 43 ``/intakes`` routes of which 26 carry
``superadmin_gate`` and 17 do not, and rows 11-17 are that 17 minus the 10 already here.
They were open by the same design decision all along and were asserted NOWHERE, so a future
gate could have closed one of them with every gate in this repo still green.

| # | Route                                     | Handler                                | Frontend caller            |
|---|-------------------------------------------|----------------------------------------|----------------------------|
| 1 | ``GET /intakes``                          | ``intake_routes.list_intakes``         | ``intake.index.tsx:12``    |
| 2 | ``GET /intakes/templates``                | ``intake_routes.list_templates``       | ``intake.$id.tsx:10``      |
| 3 | ``GET /intakes/{id}``                     | ``intake_routes.get_intake``           | ``intake.$id.tsx:8``       |
| 4 | ``GET /intakes/{id}/answers``             | ``intake_routes.list_answers``         | ``IntakeForm.tsx:14``      |
| 5 | ``PATCH /intakes/{id}/answers``           | ``intake_routes.upsert_answers``       | ``IntakeForm.tsx:14``      |
| 6 | ``POST /intakes/{id}/submit``             | ``intake_routes.submit_intake``        | ``IntakeForm.tsx:15``      |
| 7 | ``GET /intakes/{id}/skill-runs``          | ``intake_routes.list_skill_runs``      | **``IntakeForm.tsx:16``**  |
| 8 | ``GET /intakes/{id}/skill-runs/{run_id}`` | ``intake_routes.get_skill_run_full``   | **``IntakeForm.tsx:16``**  |
| 9 | ``GET /intakes/{id}/report``              | ``intake_routes.get_report``           | ``intake.$id.report.tsx:10`` |
|10 | ``GET /intakes/{id}/storage/signed-url``  | ``storage_routes.create_signed_url``   | ``intake.$id.report.tsx:11`` |
|11 | ``POST /intakes`` -> **201**              | ``intake_routes.create_intake``        | ``lib/api/intakes.ts``     |
|12 | ``PATCH /intakes/{id}``                   | ``intake_routes.patch_intake``         | ``lib/api/intakes.ts``     |
|13 | ``GET /intakes/{id}/context-pack``        | ``intake_routes.get_context_pack``     | ``intake.$id.tsx``         |
|14 | ``GET /intakes/{id}/skill-runs/stream``   | ``intake_routes.stream_skill_runs``    | ``SkillRunProgress`` (SSE) |
|15 | ``GET /intakes/{id}/sources``             | ``intake_routes.list_sources``         | ``FieldRenderer.tsx``      |
|16 | ``POST /intakes/{id}/storage/uploads`` -> **201** | ``storage_routes.upload_file`` | ``FieldRenderer.tsx:470``  |
|17 | ``DELETE /intakes/{id}/storage/objects``  | ``storage_routes.delete_objects``      | ``FieldRenderer.tsx:488``  |

⛔ ROWS 16 AND 17 NAME THEIR CATEGORY, AND THAT IS LOAD-BEARING. Phase 23.2 plan 02
(D-23.2-17 / D-23.2-08) made ``reports`` and ``artifacts`` CORRECTLY answer 422 on upload and
404 on delete for a non-superadmin. A pin written with a ``reports/`` key would therefore go
red *because plan 02 worked* — a false regression alarm pointing at the plan that did its job.
Both rows are pinned with ``attachments`` / ``audio``, the two categories in
``CLIENT_WRITABLE_CATEGORIES`` (``app/storage/keys.py:47``) that the client form actually
uploads. Do not "generalize" either pin to another category.

⚠ ROW 14 IS SSE. ``TestClient.get`` on a streaming response can block, so it is driven with
``TestClient(app).stream("GET", ...)`` and a TERMINAL skill run (the at-connect snapshot
closes the stream immediately — the shape ``tests/test_sse_stream.py:174`` established).

ROWS 7 AND 8 ARE THE DANGEROUS PAIR. ``IntakeForm.tsx`` is the CLIENT form, and its line 16
imports ``listSkillRuns`` + ``getSkillRunFull``; they render the client's proposal tick
shipped 2026-08-31. Gating them kills a live client feature while every static gate in this
repo stays green. Row 10 lives on ``storage_router``, which phase 23.1 does not touch at all
— it is pinned anyway, because "this phase does not touch it" is a claim that expires the
moment someone gates ``storage_router``.

``GET /intakes/{id}/skill-runs/stream`` was deliberately ABSENT for phase 23.1 — out of scope
in BOTH directions (not pinned, not gated). Phase 23.2 plan 11 pins it as row 14. Do NOT
confuse it with ``GET /intakes/{id}/research/stream``, which lives on ``research_router`` and
IS gated: the string ``"research"`` CONTAINS ``"search"`` and both paths end in ``/stream``,
so any substring reasoning about this pair is unsound. The walk resolves routes, not strings.

THESE ASSERTIONS ARE GREEN AT HEAD BY DESIGN — that is what a regression pin is, and it is
also why a regression pin proves nothing on its own. Plan 23.1-02 Task 2 closed that hole by
MUTATION: an inline ``if identity.role != "superadmin": raise HTTPException(404, ...)`` was
added as the first statement of ``list_skill_runs``, and
``test_skill_runs_list_open_to_user`` went RED with an observed **404** where 200 is
asserted; the mutation was then reverted and the suite went green again. The permanent,
machine-checked residue of that measurement is ``test_mutation_proof_is_recorded``, which
walks the resolved dependency tree of row 7's route RECURSIVELY — including the
``include_router(...)`` context dependencies, which FastAPI 0.141's lazy ``_IncludedRouter``
keeps OUT of ``route.dependant`` — and fails the moment ``superadmin_gate`` appears anywhere
in it, whether attached to the handler, to ``intake_router``, or to an enclosing include.

EXACT STATUS CODES ONLY: never a not-equal-404 comparison, never a less-than-400 range
check, never a tuple-membership test. A tolerant comparison is green for a 500 and for the
very 404 this suite exists to catch.

HARNESS: cloned verbatim from ``test_intake_cross_tenant.py`` (identity fabrication via
``dependency_overrides``, ``_patch_engine_factories`` so the REAL ``get_tenant_repo`` body
runs against the testcontainer, the ``set_space`` GUC-then-INSERT seeding shape). No fake
repos — these routes are exercised end to end over real Postgres, because a fake repo cannot
tell you a live route is reachable.
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

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patch: run the REAL repo dependencies against the testcontainer
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the engine factories ``session.py`` / ``ai_session.py`` imported.

    Every repo provider these ten routes use (``get_tenant_repo``,
    ``get_intake_answer_repo``, ``get_intake_and_answer_repos``, ``get_skill_run_repo``,
    ``get_research_artifact_repo``, ``get_intake_and_source_repos``) lives in
    ``app.db.session`` and resolves its engine through the ``session_mod.get_engine`` name,
    so one patch covers all of them. ``ai_session.get_engine`` is patched too because the
    write paths route through ``tenant_session``. No superadmin engine is needed: every
    caller in this file is role=``user``.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    ai_session = pytest.importorskip("app.db.ai_session")
    monkeypatch.setattr(ai_session, "get_engine", lambda *a, **k: user_engine)


# ---------------------------------------------------------------------------
# App builder — the REAL routers under test (intake + storage)
# ---------------------------------------------------------------------------


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + intake_router + storage_router.

    Mirrors ``app/main.py``'s wiring (both feature routers mounted UNDER the default-deny
    ``protected_router``) without the health probes / lifespan / CORS. Row 10 needs
    ``storage_router``, so this builder includes both — the house builders in
    ``test_intake_cross_tenant.py`` and ``test_storage_signed_url.py`` each include one.
    """
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router
    from app.api.storage_routes import storage_router

    protected_router.include_router(intake_router)
    protected_router.include_router(storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


# ---------------------------------------------------------------------------
# Seeding helpers (GUC-then-INSERT shape, copied from test_intake_cross_tenant.py)
# ---------------------------------------------------------------------------


def _seed_space(engine, space_id) -> None:
    """Insert an organization (a space). ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Client stay-open space"},
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


def _seed_skill_run(engine, set_space, space_id, intake_id, run_id, output_parsed=None) -> None:
    """Insert one ``skill_runs`` row under the owning space GUC (shape from test_skill_run_full)."""
    from sqlalchemy import text

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
                "output_parsed": (
                    json.dumps(output_parsed) if output_parsed is not None else None
                ),
            },
        )


def _seed_report(engine, set_space, space_id, intake_id, storage_path):
    """Insert a report ``research_artifacts`` row and link it from the intake; return its id.

    Shape copied from ``test_report_delivery.py`` — the artifact INSERT and the
    ``final_report_artifact_id`` link both run under the owning space's GUC so the 0002 RLS
    WITH CHECK admits them.
    """
    from sqlalchemy import text

    artifact_id = uuid.uuid4()
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.research_artifacts "
                "(id, space_id, intake_id, source, artifact_type, filename, storage_path, "
                " byte_size, mime_type) "
                "VALUES (:id, :space_id, :intake_id, 'human-report', 'report', :filename, "
                " :storage_path, 4242, 'application/pdf')"
            ),
            {
                "id": artifact_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "filename": "report.pdf",
                "storage_path": storage_path,
            },
        )
        conn.execute(
            text(
                f"UPDATE {SCHEMA}.intakes SET final_report_artifact_id = :aid "
                "WHERE id = :iid"
            ),
            {"aid": artifact_id, "iid": intake_id},
        )
    return artifact_id


def _cleanup(engine, *space_ids) -> None:
    """Delete the seeded organizations (CASCADE removes intakes/answers/runs/artifacts)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for space_id in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": space_id},
            )


# ===========================================================================
# Row 1 — GET /intakes
# ===========================================================================


def test_list_intakes_open_to_user(engine, set_space, monkeypatch):
    """Row 1: a role=user caller lists their OWN space's intakes -> EXACTLY 200.

    Feeds ``intake.index.tsx:12`` (``listIntakes``) — the client's intake inbox. Gating this
    leaves a logged-in client staring at an empty or erroring list.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get("/intakes", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). A 404 here means the superadmin gate "
            f"was applied to a CLIENT route — see 23.1-CONTEXT.md § 1."
        )
        assert str(intake_id) in {row["id"] for row in resp.json()}, (
            "the client's own intake is missing from their own list."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 2 — GET /intakes/templates
# ===========================================================================


def test_list_templates_open_to_user(engine, set_space, monkeypatch):
    """Row 2: a role=user caller reads the canonical intake template -> EXACTLY 200.

    Feeds ``intake.$id.tsx:10`` (``getTemplates``). Without the template the form has no
    schema to render at all — this is the widest blast radius of the ten.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get("/intakes/templates", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/templates must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). Gating it renders the client form "
            f"schema-less."
        )
        body = resp.json()
        assert isinstance(body, list) and len(body) >= 1, (
            f"the canonical template list must be non-empty, got {body!r}."
        )
        # ⚠ ADDED IN PHASE 23.2 (plan 06, D-23.2-04). This route now returns a FILTERED
        # BODY to a role=user: the admin_only section is withheld. The status code above no
        # longer describes the whole contract, and the `len(body) >= 1` assertion below it
        # stayed green straight through that change — a regression pin that survives the
        # change it was supposed to notice is not a pin. So the reachability assertion is
        # left byte-identical (this route must still be EXACTLY 200) and the confidentiality
        # half is asserted here, on the body.
        leaked = [
            section.get("id")
            for template in body
            for section in (template.get("schema") or {}).get("sections", [])
            if section.get("admin_only")
        ]
        assert leaked == [], (
            f"admin_only section(s) {leaked} reached a role=user caller. The canonical form "
            f"marks them 'Visible only to admin, not to the client'; serving their labels "
            f"and help text tells a client which private field keys exist (F-01 hop 4a, "
            f"23.2-CONTEXT.md § 2)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 3 — GET /intakes/{id}
# ===========================================================================


def test_get_intake_open_to_user(engine, set_space, monkeypatch):
    """Row 3: a role=user caller reads their OWN intake by id -> EXACTLY 200.

    Feeds ``intake.$id.tsx:8`` (``getIntake``). Note the collision hazard this route makes
    concrete: a cross-tenant read of this same route is EXACTLY 404 by design
    (``test_intake_cross_tenant.py``), so an over-wide gate would be indistinguishable from
    correct tenant isolation without this positive assertion.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}} must stay OPEN to role=user for their OWN intake "
            f"(EXACTLY 200), got {resp.status_code} (body={resp.text!r})."
        )
        assert resp.json()["id"] == str(intake_id)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 4 — GET /intakes/{id}/answers
# ===========================================================================


def test_list_answers_open_to_user(engine, set_space, monkeypatch):
    """Row 4: a role=user caller reads their OWN intake's answers -> EXACTLY 200.

    Feeds ``IntakeForm.tsx:14`` (``listAnswers``, via ``intake.$id.tsx``). The body is
    asserted to be a list only — ``trg_prefill_intake_answers`` may or may not have seeded
    rows, and the reachability claim does not depend on the row count.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/answers", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/answers must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r})."
        )
        assert isinstance(resp.json(), list)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 5 — PATCH /intakes/{id}/answers
# ===========================================================================


def test_upsert_answers_open_to_user(engine, set_space, monkeypatch):
    """Row 5: a role=user caller SAVES a section of answers -> EXACTLY 200, and it LANDED.

    Feeds ``IntakeForm.tsx:14`` (``saveAnswers``) — save-as-you-go. The written value is
    re-read through the route in a second request, because a 200 alone does not prove the
    write reached the database: an over-wide gate is not the only way this route can break.

    The probe key is ``geo_scope`` — a CANONICAL ``text`` field. It used to be
    ``stay_open_probe``, an invented key: since D-23.2-05 the server binds a client write to
    the canonical schema and an undefined key is 422. The intake is seeded ``draft``, which is
    the status the client form actually saves in. Only the SEED changed; the EXACTLY-200 claim
    is untouched.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": "geo_scope", "value": "kept"}]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"PATCH /intakes/{{id}}/answers must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). Gating it silently breaks "
            f"save-as-you-go for every client."
        )

        reread = client.get(f"/intakes/{intake_id}/answers", headers=AUTH)
        assert reread.status_code == 200
        written = {row["field_key"]: row["value"] for row in reread.json()}
        assert written.get("geo_scope") == "kept", (
            f"the upsert returned 200 but the value did not land: {written!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 6 — POST /intakes/{id}/submit
# ===========================================================================


def test_submit_intake_open_to_user(engine, set_space, monkeypatch):
    """Row 6: a role=user caller submits their OWN ``draft`` intake -> EXACTLY 200.

    Feeds ``IntakeForm.tsx:15`` (``submitIntake``). Seeded at ``draft``, the first entry in
    ``_SUBMIT_TRANSITIONS``, so the 409 scope-ceiling wall is not in play — the status is
    asserted to have advanced to ``submitted``, proving the verb executed rather than merely
    answering. ``draft -> submitted`` does NOT reach the ``validated_by_client`` branch, so
    no mail seam is touched.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="draft")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).post(f"/intakes/{intake_id}/submit", headers=AUTH)

        assert resp.status_code == 200, (
            f"POST /intakes/{{id}}/submit must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). This is the client's only way to "
            f"hand their intake over."
        )
        assert resp.json()["status"] == "submitted", (
            f"submit returned 200 but the status did not advance: {resp.json()!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 7 — GET /intakes/{id}/skill-runs   (THE DANGEROUS PAIR, half one)
# ===========================================================================


def test_skill_runs_list_open_to_user(engine, set_space, monkeypatch):
    """Row 7: a role=user caller lists their OWN intake's skill runs -> EXACTLY 200.

    ``IntakeForm.tsx:16`` imports ``listSkillRuns``; this is the CLIENT form, not the admin
    panel, and this call drives the client's proposal tick shipped 2026-08-31. This is the
    single most likely way phase 23.1 does damage (23.1-CONTEXT.md § 1).

    The response is ``SkillRunsView`` — an OBJECT with ``latest`` + ``runs`` — not a bare
    list, so ``runs`` is what carries the list assertion.

    THIS IS THE TEST THAT WENT RED IN THE TASK-2 MUTATION PROOF (observed 404).
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="submitted")
        _seed_skill_run(engine, set_space, space, intake_id, run_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/skill-runs", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/skill-runs must stay OPEN to role=user (EXACTLY 200), got "
            f"{resp.status_code} (body={resp.text!r}). The CLIENT form reads this route "
            f"(IntakeForm.tsx:16) — gating it kills the proposal tick shipped 2026-08-31 "
            f"with every type/lint/locale gate still green."
        )
        body = resp.json()
        assert isinstance(body["runs"], list) and len(body["runs"]) == 1, (
            f"the seeded run is missing from the client's own skill-run list: {body!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 8 — GET /intakes/{id}/skill-runs/{run_id}   (THE DANGEROUS PAIR, half two)
# ===========================================================================


def test_skill_run_full_open_to_user(engine, set_space, monkeypatch):
    """Row 8: a role=user caller reads ONE of their OWN skill runs in full -> EXACTLY 200.

    ``IntakeForm.tsx:16`` imports ``getSkillRunFull``; the client form fetches the run's
    ``output_parsed`` to render the proposal diff it ticks. Row 7 without row 8 is a broken
    feature, so both halves are pinned separately and both name the route.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="submitted")
        _seed_skill_run(
            engine,
            set_space,
            space,
            intake_id,
            run_id,
            output_parsed={"research_questions_refined": ["q1"], "dropped": []},
        )
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(
            f"/intakes/{intake_id}/skill-runs/{run_id}", headers=AUTH
        )

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/skill-runs/{{run_id}} must stay OPEN to role=user "
            f"(EXACTLY 200), got {resp.status_code} (body={resp.text!r}). The CLIENT form "
            f"reads this route (IntakeForm.tsx:16)."
        )
        assert resp.json()["id"] == str(run_id)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 9 — GET /intakes/{id}/report
# ===========================================================================


def test_report_open_to_user(engine, set_space, monkeypatch):
    """Row 9: a role=user caller reads their OWN ``delivered`` intake's report -> EXACTLY 200.

    Feeds ``intake.$id.report.tsx:10`` (``getReport``). The intake is seeded at EXACTLY
    ``delivered`` with a linked ``research_artifacts`` row, because REPORT-02 makes every
    other status a legitimate 404 — pinning this route at any other status would assert the
    invisibility gate, not the client's reachability.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="delivered")
        _seed_report(
            engine, set_space, space, intake_id, f"{space}/{intake_id}/report.pdf"
        )
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/report", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/report must stay OPEN to role=user for their OWN "
            f"delivered intake (EXACTLY 200), got {resp.status_code} "
            f"(body={resp.text!r}). Gating it hides the deliverable the client paid for."
        )
        assert resp.json()["filename"] == "report.pdf"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Row 10 — GET /intakes/{id}/storage/signed-url   (storage_router, untouched by 23.1)
# ===========================================================================


def test_storage_signed_url_open_to_user(engine, set_space, monkeypatch, fake_gcs):
    """Row 10: a role=user caller signs their OWN report key -> EXACTLY 200 with a URL.

    Feeds ``intake.$id.report.tsx:11`` (``lib/api/storage``) — the download half of row 9;
    row 9 without row 10 is a report the client can see and cannot open. This route lives on
    ``storage_router``, which phase 23.1 does not touch — pinned anyway, because that is a
    claim that expires the moment someone gates ``storage_router``. ``fake_gcs`` intercepts
    the seam, so no bucket and no credentials are involved.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/report.pdf"
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id, status="delivered")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(
            f"/intakes/{intake_id}/storage/signed-url",
            params={"path": key},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/storage/signed-url must stay OPEN to role=user for their "
            f"OWN key (EXACTLY 200), got {resp.status_code} (body={resp.text!r})."
        )
        assert resp.json()["url"], "the signed-url body carried no URL."
        assert fake_gcs["signed_urls"][-1]["key"] == key
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# The route-inventory guard — a new /intakes route must be a DECISION, not a default
# ===========================================================================
#
# Generated by RUNNING the enumeration below against app.main.app at 7bb1151, not written by
# hand: a hand-written list is how a route gets silently omitted from the very inventory
# meant to catch omissions. It covers every router mounted under the /intakes prefix
# (intake_router, storage_router AND research_router), which is wider than this plan's ten
# rows and deliberately so.
_PINNED_INTAKE_ROUTES = frozenset(
    {
        ("DELETE", "/intakes/{intake_id}/storage/objects"),
        ("GET", "/intakes"),
        ("GET", "/intakes/research/runs/{run_id}/locate"),
        ("GET", "/intakes/templates"),
        ("GET", "/intakes/{intake_id}"),
        ("GET", "/intakes/{intake_id}/answers"),
        ("GET", "/intakes/{intake_id}/context-pack"),
        ("GET", "/intakes/{intake_id}/members"),
        ("GET", "/intakes/{intake_id}/report"),
        ("GET", "/intakes/{intake_id}/research/sources/{source_id}"),
        ("GET", "/intakes/{intake_id}/research/stream"),
        ("GET", "/intakes/{intake_id}/research/{run_id}/audit/{audit_id}"),
        ("GET", "/intakes/{intake_id}/research/{run_id}/bundle-url"),
        ("GET", "/intakes/{intake_id}/research/{run_id}/events"),
        ("GET", "/intakes/{intake_id}/research/{run_id}/verification"),
        ("GET", "/intakes/{intake_id}/search"),
        ("GET", "/intakes/{intake_id}/skill-runs"),
        ("GET", "/intakes/{intake_id}/skill-runs/stream"),
        ("GET", "/intakes/{intake_id}/skill-runs/{run_id}"),
        ("GET", "/intakes/{intake_id}/sources"),
        ("GET", "/intakes/{intake_id}/storage/signed-url"),
        ("PATCH", "/intakes/{intake_id}"),
        ("PATCH", "/intakes/{intake_id}/answers"),
        ("POST", "/intakes"),
        ("POST", "/intakes/{intake_id}/deliver"),
        ("POST", "/intakes/{intake_id}/embeddings"),
        ("POST", "/intakes/{intake_id}/mail/intake"),
        ("POST", "/intakes/{intake_id}/mail/reminder"),
        ("POST", "/intakes/{intake_id}/mail/results"),
        ("POST", "/intakes/{intake_id}/mail/validation"),
        ("POST", "/intakes/{intake_id}/report/replace"),
        ("POST", "/intakes/{intake_id}/research"),
        ("POST", "/intakes/{intake_id}/research/cancel"),
        ("POST", "/intakes/{intake_id}/research/resume"),
        ("POST", "/intakes/{intake_id}/research/{run_id}/verify-chain"),
        ("POST", "/intakes/{intake_id}/review"),
        ("POST", "/intakes/{intake_id}/skills/apply"),
        ("POST", "/intakes/{intake_id}/skills/context-pack"),
        ("POST", "/intakes/{intake_id}/skills/extract-insights"),
        ("POST", "/intakes/{intake_id}/skills/structure-answers"),
        ("POST", "/intakes/{intake_id}/sources/{source_id}/transcribe"),
        ("POST", "/intakes/{intake_id}/storage/uploads"),
        ("POST", "/intakes/{intake_id}/submit"),
    }
)


def _flatten_routes(routes, prefix="", inherited=()):
    """Yield ``(full_path, route, inherited_depends)`` for every leaf route, recursively.

    FastAPI 0.141 does NOT flatten ``include_router`` at include time: ``app.routes`` holds
    ``_IncludedRouter`` placeholders that keep a live reference to the included router plus
    an ``include_context`` carrying that include's ``prefix`` and ``dependencies``. A
    non-recursive read of ``app.routes`` therefore finds ZERO ``/intakes`` routes, and the
    include-level dependencies (which is how ``protected_router`` attaches
    ``get_current_identity``, and how 23.1-11 will gate ``ai_router``) never appear in a
    leaf's ``route.dependant`` at all. Both facts are why this walker exists and why it
    returns the inherited ``Depends`` alongside each route.
    """
    from fastapi.routing import _IncludedRouter

    out = []
    for route in routes:
        if isinstance(route, _IncludedRouter):
            ctx = route.include_context
            out.extend(
                _flatten_routes(
                    route.original_router.routes,
                    prefix + (ctx.prefix or ""),
                    inherited + tuple(ctx.dependencies or ()),
                )
            )
            continue
        path = getattr(route, "path_format", None) or getattr(route, "path", "")
        out.append((prefix + path, route, inherited))
    return out


def test_client_route_inventory_is_pinned():
    """Every ``/intakes`` route in the REAL app is one this phase has already classified.

    Fails on ADDITION and on REMOVAL, so it is not merely a growth alarm — deleting a client
    route is the same defect from the other direction.
    """
    main = pytest.importorskip("app.main")

    observed = set()
    for path, route, _inherited in _flatten_routes(main.app.routes):
        if not path.startswith("/intakes"):
            continue
        for method in getattr(route, "methods", None) or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            observed.add((method, path))

    added = observed - _PINNED_INTAKE_ROUTES
    removed = _PINNED_INTAKE_ROUTES - observed
    assert observed == _PINNED_INTAKE_ROUTES, (
        f"the /intakes route inventory changed. ADDED={sorted(added)} "
        f"REMOVED={sorted(removed)}. A new /intakes route appeared. Decide whether it is an "
        f"operator verb (gate it, per D-23.1-02) or a client route (pin it here with a "
        f"positive 2xx reachability test), then update this set. A removal is equally a "
        f"defect unless the client caller was removed with it."
    )


# ===========================================================================
# The mutation proof, in permanent machine-checked form
# ===========================================================================


def _resolved_dependency_calls(route, inherited) -> list:
    """Return every callable reachable from ``route``'s resolved dependency tree.

    Walks THREE sources, because a gate can be attached at any of them and checking only one
    is a false pass:

    1. ``route.dependant.dependencies``, RECURSIVELY — covers ``Depends(...)`` in the
       handler signature, ``@router.get(dependencies=[...])``, and
       ``APIRouter(prefix=..., dependencies=[...])`` (verified: a router-level dependency IS
       baked into the leaf's dependant at ``add_api_route`` time).
    2. The ``include_router(..., dependencies=[...])`` context of every enclosing
       ``_IncludedRouter`` — which FastAPI 0.141 keeps OUT of ``route.dependant``. This is
       exactly the shape D-23.1-02 prescribes for ``ai_router``, so omitting it would make
       the whole assertion vacuous against the gating style the phase actually uses.
    3. The sub-dependencies of each of those include-level callables, resolved with
       ``get_dependant`` and walked with the same recursion.
    """
    from fastapi.dependencies.utils import get_dependant

    def _walk(dependant) -> list:
        found = []
        for sub in dependant.dependencies:
            found.append(sub.call)
            found.extend(_walk(sub))
        return found

    calls = _walk(route.dependant)
    for dep in inherited:
        call = getattr(dep, "dependency", None)
        if call is None:
            continue
        calls.append(call)
        calls.extend(_walk(get_dependant(path="/", call=call)))
    return calls


def test_mutation_proof_is_recorded():
    """``GET /intakes/{id}/skill-runs`` carries NO superadmin gate, anywhere in its tree.

    THE PERMANENT FORM OF THE TASK-2 MEASUREMENT. The mutation itself (an inline
    ``if identity.role != "superadmin": raise HTTPException(404, ...)`` at the top of
    ``list_skill_runs``) turned ``test_skill_runs_list_open_to_user`` RED with an observed
    404 and was then reverted — that proved the reachability suite is not vacuous, but it
    left nothing behind in CI. This test is what remains: it is FALSE the moment anyone
    attaches ``superadmin_gate`` to row 7, whether on the handler, on ``intake_router``, or
    on an enclosing ``include_router(...)``.

    IT WAS ITSELF PROVED FALSIFIABLE, by a SECOND temporary mutation — ``intake_router``
    reconstructed as ``APIRouter(prefix="/intakes", tags=["intakes"],
    dependencies=[Depends(superadmin_gate)])``, which is exactly the ROUTER-LEVEL shape
    D-23.1-02 prescribes for ``ai_router``. This test went RED with the resolved tree
    ``['superadmin_gate', 'get_current_identity', HTTPBearer, 'get_skill_run_repo', ...]``,
    and went green again on revert. A top-level-only check would have missed the nested
    ``get_current_identity`` under the gate; a name-string check would have matched a
    lookalike.

    Identity is compared with ``is``: a name-string comparison would pass on a lookalike
    (any local named ``superadmin_gate``) and fail on a legitimate re-export.
    """
    gates = pytest.importorskip("app.auth.gates")
    main = pytest.importorskip("app.main")
    superadmin_gate = gates.superadmin_gate

    target = [
        (route, inherited)
        for path, route, inherited in _flatten_routes(main.app.routes)
        if path == "/intakes/{intake_id}/skill-runs"
        and "GET" in (getattr(route, "methods", None) or set())
    ]
    assert len(target) >= 1, (
        "GET /intakes/{intake_id}/skill-runs is not mounted on the app at all — the CLIENT "
        "form (IntakeForm.tsx:16) calls it."
    )

    for route, inherited in target:
        calls = _resolved_dependency_calls(route, inherited)
        assert not any(call is superadmin_gate for call in calls), (
            "SEC-01 / 23.1-CONTEXT.md § 1 VIOLATION: superadmin_gate is in the resolved "
            "dependency tree of GET /intakes/{intake_id}/skill-runs. That route is read by "
            "the CLIENT intake form (IntakeForm.tsx:16) and renders the proposal tick "
            "shipped 2026-08-31. Gating it breaks a live client feature. Resolved tree: "
            f"{[getattr(c, '__name__', repr(c)) for c in calls]}"
        )
        # SELF-CHECK ON THE WALKER, so the assertion above cannot go green by finding
        # nothing. ``protected_router`` attaches ``get_current_identity`` through its own
        # ``APIRouter(dependencies=[...])``, which FastAPI 0.141 propagates via the INCLUDE
        # CONTEXT and NOT via ``route.dependant`` — so this pair proves both arms of
        # ``_resolved_dependency_calls`` are live: the inherited arm resolves the identity
        # dependency, and the recursive arm resolves the handler's own repo dependency.
        assert any(
            getattr(dep, "dependency", None) is dependencies.get_current_identity
            for dep in inherited
        ), (
            "the INCLUDE-CONTEXT arm of the walker found nothing. Either the route lost its "
            "auth dependency, or FastAPI changed where include_router(...) dependencies "
            "live — in which case _resolved_dependency_calls must be re-verified before the "
            "gate assertion above can be trusted (23.1-11 gates ai_router at ROUTER level, "
            "so a walker blind to that arm is a false pass)."
        )
        assert any(call is session_mod.get_skill_run_repo for call in calls), (
            "the RECURSIVE arm of the walker found nothing — the handler's own "
            "get_skill_run_repo dependency is missing from the resolved tree."
        )


# ===========================================================================
# Rows 11-17 — the seven that were OPEN but asserted NOWHERE (phase 23.2 plan 11)
# ===========================================================================
#
# DERIVED, NOT COPIED. ``_flatten_routes`` resolves 43 ``/intakes`` routes; 26 carry
# ``superadmin_gate`` in their resolved+inherited dependency tree and 17 do not. Rows 11-17
# are that 17 minus the 10 above. Every one is open by the same design decision phase 23.1
# made for rows 1-10 — they were simply never asserted, so a gate applied one router too
# wide would have closed one of them with every gate in this repo still green.
#
# EXACT STATUS CODES, same discipline as rows 1-10: never ``!= 404``, never ``< 400``,
# never tuple membership. Rows 11 and 16 are 201 (``intake_routes.py:525`` and
# ``storage_routes.py:141-142`` both declare ``status_code=HTTP_201_CREATED``); the other
# five are 200.


def test_create_intake_open_to_user(engine, set_space, monkeypatch):
    """Row 11: a role=user creates an intake in their OWN space -> EXACTLY 201.

    Feeds ``frontend/src/lib/api/intakes.ts`` (the create call posts ``client_name`` only).
    The user path goes through ``repo.create(**values)``, which FORCES the caller's own
    space onto the row (TENANT-02) — the ``?space_id=`` query param is inert for a user and
    the body never carries a space. Gating this route means a client can never start.
    """
    from fastapi.testclient import TestClient

    space = uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).post(
            "/intakes", json={"client_name": "Stay-open probe"}, headers=AUTH
        )

        assert resp.status_code == 201, (
            f"POST /intakes must stay OPEN to role=user (EXACTLY 201 — "
            f"intake_routes.py:525 declares HTTP_201_CREATED), got {resp.status_code} "
            f"(body={resp.text!r}). Gating it means a client can never create an intake."
        )
        # Anti-vacuity: a 201 that wrote into the WRONG space would still be a 201.
        assert resp.json()["space_id"] == str(space), (
            f"the created intake landed outside the caller's own space: {resp.text!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_patch_intake_open_to_user(engine, set_space, monkeypatch):
    """Row 12: a role=user renames their OWN intake -> EXACTLY 200.

    Feeds ``frontend/src/lib/api/intakes.ts``. ``IntakePatch`` admits ``client_name`` and
    nothing else — no status, no space_id — so this route is benign by construction and its
    openness is a deliberate decision rather than an oversight.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).patch(
            f"/intakes/{intake_id}", json={"client_name": "Renamed"}, headers=AUTH
        )

        assert resp.status_code == 200, (
            f"PATCH /intakes/{{id}} must stay OPEN to role=user for their OWN intake "
            f"(EXACTLY 200), got {resp.status_code} (body={resp.text!r})."
        )
        # Anti-vacuity: a 200 whose write did not land is not a working route.
        assert resp.json()["client_name"] == "Renamed", (
            f"the patch returned 200 but the value did not land: {resp.text!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_context_pack_open_to_user(engine, set_space, monkeypatch):
    """Row 13: a role=user reads their OWN intake's context pack -> EXACTLY 200.

    The SCOPED-EMPTY case, deliberately: with no pack generated the handler returns
    ``{"latest": None, "history": []}`` at 200, NEVER a 404 (``intake_routes.py:803``). That
    non-distinguishability IS the security property — a stranger cannot tell "no pack" from
    "not your intake" — and it is exactly the case an over-wide gate breaks just as surely
    as the populated one. It also needs no seed beyond the intake.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/context-pack", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/context-pack must stay OPEN to role=user (EXACTLY 200, "
            f"scoped-empty by design), got {resp.status_code} (body={resp.text!r})."
        )
        assert resp.json() == {"latest": None, "history": []}, (
            f"the scoped-empty shape changed: {resp.text!r}. A 404 here would leak intake "
            f"existence (D-07)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_skill_runs_stream_open_to_user(engine, set_space, monkeypatch):
    """Row 14: a role=user opens the SSE skill-run stream on their OWN intake -> EXACTLY 200.

    Feeds ``SkillRunProgress`` — the live progress bar the CLIENT form renders while a run
    is in flight. Gating it leaves the client staring at a frozen bar.

    ⚠ SSE. ``TestClient.get`` on a streaming response can block, so this uses
    ``TestClient(app).stream("GET", ...)`` — the shape ``tests/test_sse_stream.py:174``
    established — and the seeded run is TERMINAL (``_seed_skill_run`` writes
    ``status='succeeded'``), so the at-connect snapshot closes the stream immediately and
    there is no timeout hazard. The status code is asserted off the response object.
    """
    from fastapi.testclient import TestClient

    space, intake_id, run_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _seed_skill_run(engine, set_space, space, intake_id, run_id)  # TERMINAL: succeeded
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        with TestClient(app).stream(
            "GET", f"/intakes/{intake_id}/skill-runs/stream", headers=AUTH
        ) as resp:
            assert resp.status_code == 200, (
                f"GET /intakes/{{id}}/skill-runs/stream must stay OPEN to role=user "
                f"(EXACTLY 200), got {resp.status_code}. It is the CLIENT form's live "
                f"progress feed."
            )
            assert resp.headers["content-type"].startswith("text/event-stream"), (
                f"the stream stopped being SSE: {resp.headers.get('content-type')!r}"
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_sources_open_to_user(engine, set_space, monkeypatch):
    """Row 15: a role=user lists their OWN intake's uploaded sources -> EXACTLY 200.

    Feeds ``FieldRenderer.tsx`` — the client's own file list. Like row 13 this is a
    SCOPED-EMPTY 200 by design (``intake_routes.py:837``): no sources reads
    ``{"sources": []}``, never a 404, so absence of uploads cannot be told from absence of
    the intake.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).get(f"/intakes/{intake_id}/sources", headers=AUTH)

        assert resp.status_code == 200, (
            f"GET /intakes/{{id}}/sources must stay OPEN to role=user (EXACTLY 200, "
            f"scoped-empty by design), got {resp.status_code} (body={resp.text!r})."
        )
        assert resp.json() == {"sources": []}, (
            f"the scoped-empty shape changed: {resp.text!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_storage_upload_open_to_user(engine, set_space, monkeypatch, fake_gcs):
    """Row 16: a role=user uploads an ``attachments`` file to their OWN intake -> EXACTLY 201.

    Feeds ``FieldRenderer.tsx:470``, which sends ``category`` = ``audio`` or
    ``attachments``.

    ⛔ THE CATEGORY IS NAMED ON PURPOSE. Phase 23.2 plan 02 (D-23.2-17) made a non-superadmin
    uploading ``reports``/``artifacts`` CORRECTLY answer 422 — those are operator-produced
    deliverables. Pinning this row with ``category="reports"`` would go red *because plan 02
    worked*, manufacturing a false regression alarm against the plan that did its job. The
    pin uses ``attachments``, one of the two in ``CLIENT_WRITABLE_CATEGORIES``
    (``app/storage/keys.py:47``). ``fake_gcs`` intercepts the seam — no bucket, no creds.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("brief.pdf", b"%PDF-1.4 probe", "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"POST /intakes/{{id}}/storage/uploads must stay OPEN to role=user for a "
            f"CLIENT-WRITABLE category (EXACTLY 201 — storage_routes.py:141-142 declares "
            f"HTTP_201_CREATED), got {resp.status_code} (body={resp.text!r}). Note the "
            f"category is 'attachments', not 'reports': 422 on 'reports' is CORRECT "
            f"post-D-23.2-17 and is not a regression."
        )
        # Anti-vacuity: a 201 that never reached the seam is not an upload.
        assert fake_gcs["uploads"], "the upload returned 201 but never reached the GCS seam."
        assert fake_gcs["uploads"][-1]["key"].startswith(
            f"{space}/{intake_id}/attachments/"
        ), f"the server-authored key is wrong: {fake_gcs['uploads'][-1]['key']!r}"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_storage_delete_open_to_user(engine, set_space, monkeypatch, fake_gcs):
    """Row 17: a role=user deletes an ``attachments`` object of their OWN intake -> EXACTLY 200.

    Feeds ``FieldRenderer.tsx:488`` (the client's file-remove button).

    ⛔ THE CATEGORY IS NAMED ON PURPOSE — the same trap as row 16, from the delete side.
    Phase 23.2 plan 02 (D-23.2-08 / F-03) made a non-superadmin deleting a ``reports/`` key
    CORRECTLY answer an existence-hidden 404, because ``GET /intakes/{id}/report`` hands the
    client that exact ``storage_path`` and possession of a path was permission to destroy the
    object behind it. A pin written with a ``reports/`` key would therefore go red *because
    plan 02 worked*. This pin uses an ``attachments/`` key — client-writable, and the exact
    shape ``build_object_key`` authors, so ``category_of`` parses the third segment.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/attachments/{uuid.uuid4()}-brief.pdf"
    app = _build_app()
    try:
        _seed_space(engine, space)
        _seed_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))

        resp = TestClient(app).request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [key]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"DELETE /intakes/{{id}}/storage/objects must stay OPEN to role=user for a "
            f"CLIENT-WRITABLE category (EXACTLY 200), got {resp.status_code} "
            f"(body={resp.text!r}). Note the key is an 'attachments/' key, not 'reports/': "
            f"404 on a reports key is CORRECT post-D-23.2-08 and is not a regression."
        )
        assert resp.json()["removed"] == 1, (
            f"the delete returned 200 but removed nothing: {resp.text!r}"
        )
        assert fake_gcs["deletes"][-1]["key"] == key
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Anti-vacuity on the pin itself — the COUNT of reachability tests
# ===========================================================================


def test_every_open_client_route_is_pinned():
    """Exactly SEVENTEEN ``*_open_to_user`` tests exist — one per open ``/intakes`` route.

    ANTI-VACUITY BY INTROSPECTION, not by prose. The header table claims seventeen rows; a
    table is a comment and a comment cannot fail. This derives the count from the module's
    own callables and cross-checks it against the number of ``/intakes`` routes the REAL app
    exposes WITHOUT ``superadmin_gate`` — so deleting a pin, or opening an eighteenth route
    and not pinning it, both go red here.

    The two numbers are computed independently: one from this module's namespace, one from
    ``_flatten_routes`` over ``app.main.app``. They are asserted equal, and then asserted to
    be 17. A single hard-coded number could be satisfied by editing the number.
    """
    import sys

    from fastapi.dependencies.utils import get_dependant

    gates = pytest.importorskip("app.auth.gates")
    main = pytest.importorskip("app.main")
    superadmin_gate = gates.superadmin_gate

    module = sys.modules[__name__]
    pins = sorted(
        name
        for name in dir(module)
        if name.startswith("test_") and name.endswith("_open_to_user")
    )
    checked = len(pins)

    def _walk(dependant):
        found = []
        for sub in dependant.dependencies:
            found.append(sub.call)
            found.extend(_walk(sub))
        return found

    open_routes = set()
    for path, route, inherited in _flatten_routes(main.app.routes):
        if not path.startswith("/intakes") or not hasattr(route, "dependant"):
            continue
        calls = _walk(route.dependant)
        for dep in inherited:
            call = getattr(dep, "dependency", None)
            if call is None:
                continue
            calls.append(call)
            calls.extend(_walk(get_dependant(path="/", call=call)))
        if any(c is superadmin_gate for c in calls):
            continue
        for method in getattr(route, "methods", None) or set():
            if method in ("HEAD", "OPTIONS"):
                continue
            open_routes.add((method, path))

    assert checked == len(open_routes), (
        f"the pin and the app disagree: {checked} *_open_to_user tests but "
        f"{len(open_routes)} ungated /intakes routes. Pins={pins}. "
        f"Open routes={sorted(open_routes)}. Either a client route was added and not "
        f"pinned (pin it), or a pin was deleted (restore it), or a route acquired/lost a "
        f"gate (that is the finding — do not adjust this number to match)."
    )
    assert checked == 17, (
        f"expected 17 pinned client routes, got {checked}: {pins}. This number changing is "
        f"a DECISION about the client surface, never a bookkeeping edit."
    )
