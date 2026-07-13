"""INTAKE-01/02/03/04 + QA-04 intake-router suite — drives the REAL ``intake_router`` over PG.

This is the endpoint-level proof for the real intake feature surface (the generalization of
``test_cross_tenant_denial.py``'s sample-router drive). It mounts the REAL
``app.api.intake_routes.intake_router`` under the default-deny ``protected_router``, overrides
``get_current_identity`` with a fabricated ``user`` Identity (no live IdP), and patches ONLY
the engine FACTORIES that ``session.py`` imports (``session_mod.get_engine`` /
``session_mod.get_superadmin_engine``) to the conftest testcontainer engines — so the
PRODUCTION path (``get_tenant_repo`` / ``get_intake_answer_repo`` -> the real repositories +
explicit ``WHERE`` + RLS -> the handler's 404/409 mapping -> ``audit.log`` on the request tx)
runs verbatim.

What each case pins (06-VALIDATION INTAKE-01/04 rows / threat register):

| Test                         | Proves                                                          |
|------------------------------|----------------------------------------------------------------|
| ``create_and_list``          | a user POST /intakes -> 201 status="draft"; GET /intakes lists |
|                              | it within the caller's space (INTAKE-01 / TENANT-02).          |
| ``answers_batch_upsert``     | PATCH .../answers twice on the same (intake_id, field_key)     |
|                              | UPDATES (no duplicate row, no unique violation — D-03/Pitfall6)|
| ``transitions``              | draft->submitted->reviewed->validated_by_client all 200; a     |
|                              | forbidden submit (from validated_by_client) -> 409 (T-06-06).  |
| ``transition_audited``       | one transition writes EXACTLY one intake.status_changed audit  |
|                              | row, metadata={"from","to"} only — no token/link (T-06-08/09). |

Skip-clean (conftest discipline): ``pytestmark = pytest.mark.integration`` (skips when no
Docker / DATABASE_URL); ``firebase_admin`` and ``app.*`` imports are guarded with
``pytest.importorskip`` so the file COLLECTS on the dev box without erroring (this box has no
Python/Docker — the real gate runs in CI; see MEMORY dev-machine-no-python-docker).

Authoritative references:
- backend/tests/test_cross_tenant_denial.py (drive-the-REAL-route + fabricated-Identity +
    ``_patch_engine_factories`` + ``_build_app`` template)
- backend/tests/test_admin_routes.py (audit-row count assertion idiom)
- backend/tests/conftest.py (pg_container / engine / set_space / two_spaces; skip-clean)
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box (Wave 0 / dev box).
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
intake_routes = pytest.importorskip("app.api.intake_routes")
auth_routes = pytest.importorskip("app.api.auth_routes")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
intake_router = intake_routes.intake_router
protected_router = auth_routes.protected_router

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patch: run the REAL get_*_repo dependencies against the testcontainer
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the engine factory ``session.py`` imported, so the REAL tenant dependencies run.

    ``app/db/session.py`` does ``from app.db.base import get_engine, ...``; ALL the per-entity
    dependencies (``get_tenant_repo`` / ``get_intake_answer_repo`` / ``get_skill_run_repo`` /
    ``get_intake_template_repo``) reference that one module-level name, so patching
    ``session_mod.get_engine`` routes every user-path request to the testcontainer engine. The
    production dependency bodies (role->engine, null-space 403, ``maker.begin()`` one-tx,
    ``set_space_context`` GUC) run verbatim. ``get_sessionmaker`` is left real.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


# ---------------------------------------------------------------------------
# Seeding helpers (a single space; the user creates its own intakes via the API)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    """Insert an organization (a space). ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _cleanup_space(engine, space_id: uuid.UUID) -> None:
    """Delete the seeded organization as the owner (CASCADE removes its intakes/answers)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ---------------------------------------------------------------------------
# App builder (the REAL routers under test)
# ---------------------------------------------------------------------------


def _build_app():
    """Mount the REAL ``intake_router`` under the default-deny ``protected_router`` (mirrors
    app/main.py wiring + test_cross_tenant_denial.py:218-233)."""
    from fastapi import FastAPI

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


# ===========================================================================
# (a) create + list — user creates an intake in own space -> draft; list returns it
# ===========================================================================


def test_create_and_list_intake_in_own_space(engine, monkeypatch):
    """A user POST /intakes -> 201 with status="draft"; GET /intakes returns it (INTAKE-01)."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Create/List Space")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_id))
        client = TestClient(app)

        create = client.post(
            "/intakes",
            json={"client_name": "Acme"},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert create.status_code == 201, (
            f"create should be 201, got {create.status_code} ({create.text!r})"
        )
        created = create.json()
        assert created["status"] == "draft", "a newly created intake must be 'draft'"
        assert created["space_id"] == str(space_id), "create must inject the caller's space_id"
        intake_id = created["id"]

        listed = client.get(
            "/intakes", headers={"Authorization": "Bearer ignored-overridden"}
        )
        assert listed.status_code == 200, f"list should be 200, got {listed.status_code}"
        ids = {row["id"] for row in listed.json()}
        assert intake_id in ids, "own-space list() must include the just-created intake"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (b) answers section batch upsert — second save UPDATES, no duplicate row
# ===========================================================================


def test_answers_batch_upsert(engine, monkeypatch):
    """PATCH .../answers twice on the same field_key UPDATES the single row (D-03 / Pitfall 6).

    The second call must NOT raise a unique violation and must NOT create a duplicate — it
    upserts on the EXISTING ``(intake_id, field_key)`` constraint.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Answers Upsert Space")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_id))
        client = TestClient(app)

        intake_id = client.post(
            "/intakes",
            json={"client_name": "Answers Co"},
            headers={"Authorization": "Bearer ignored-overridden"},
        ).json()["id"]

        first = client.patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": "q1", "value": "first"}]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert first.status_code == 200, (
            f"first section save should be 200, got {first.status_code} ({first.text!r})"
        )

        second = client.patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": [{"field_key": "q1", "value": "second"}]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert second.status_code == 200, (
            f"re-saving the same section must be 200 (upsert, not unique violation), "
            f"got {second.status_code} ({second.text!r})"
        )

        # Exactly ONE row for (intake_id, field_key) and the value was UPDATED, not appended.
        # The owner engine is policy-bound under FORCE RLS — the verification read
        # needs the space GUC set in the same transaction to see the rows at all.
        with engine.begin() as conn:
            conn.execute(
                text("SELECT set_config('app.current_space_id', :sid, true)"),
                {"sid": str(space_id)},
            )
            rows = conn.execute(
                text(
                    f"SELECT value FROM {SCHEMA}.intake_answers "
                    "WHERE intake_id = :id AND field_key = 'q1'"
                ),
                {"id": intake_id},
            ).all()
        assert len(rows) == 1, (
            f"section re-save must UPDATE in place — found {len(rows)} rows for q1 "
            "(duplicate => the upsert conflict target is wrong, Pitfall 6)"
        )
        assert rows[0][0] == "second", "the second save must overwrite the first value"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_answers_value_json_accepts_any_json_value(engine, monkeypatch):
    """value_json accepts arrays/booleans/numbers, not only objects (live-UAT regression).

    The frontend routes EVERY non-string form value into ``value_json`` (arrays from
    list/files fields, booleans, numbers) and the column is JSONB. A ``dict``-only
    Pydantic annotation 422'd real section saves ('Opslaan mislukt', 2026-07-13 UAT).
    The GET projection must round-trip the same shapes (AnswerView mirrors AnswerItem).
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Answers JSON Shapes Space")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_id))
        client = TestClient(app)

        intake_id = client.post(
            "/intakes",
            json={"client_name": "JSON Shapes Co"},
            headers={"Authorization": "Bearer ignored-overridden"},
        ).json()["id"]

        payload = {
            "answers": [
                {"field_key": "list_field", "value_json": ["alpha", "beta"]},
                {"field_key": "files_field", "value_json": [{"path": "k", "name": "f.pdf"}]},
                {"field_key": "flag_field", "value_json": True},
                {"field_key": "num_field", "value_json": 42},
                {"field_key": "obj_field", "value_json": {"nested": "ok"}},
            ]
        }
        saved = client.patch(
            f"/intakes/{intake_id}/answers",
            json=payload,
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert saved.status_code == 200, (
            f"non-dict value_json shapes must be accepted (JSONB column), "
            f"got {saved.status_code} ({saved.text!r})"
        )

        read = client.get(
            f"/intakes/{intake_id}/answers",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert read.status_code == 200, f"answers read should be 200, got {read.status_code}"
        by_key = {a["field_key"]: a.get("value_json") for a in read.json()}
        assert by_key.get("list_field") == ["alpha", "beta"]
        assert by_key.get("files_field") == [{"path": "k", "name": "f.pdf"}]
        assert by_key.get("flag_field") is True
        assert by_key.get("num_field") == 42
        assert by_key.get("obj_field") == {"nested": "ok"}
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (c) transitions — the allow-listed path succeeds; a forbidden jump -> 409
# ===========================================================================


def test_transitions_advance_and_reject_out_of_scope(engine, monkeypatch):
    """draft->submitted->reviewed->validated_by_client all 200; a forbidden submit -> 409.

    The forbidden case (submit from ``validated_by_client``) has NO allow-list entry, so it
    409s — STRUCTURALLY blocking any progression past the in-scope ceiling (T-06-06).
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Transitions Space")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_id))
        client = TestClient(app)
        hdr = {"Authorization": "Bearer ignored-overridden"}

        intake_id = client.post(
            "/intakes", json={"client_name": "Flow Co"}, headers=hdr
        ).json()["id"]

        submit = client.post(f"/intakes/{intake_id}/submit", headers=hdr)
        assert submit.status_code == 200, f"draft->submitted should be 200, got {submit.status_code}"
        assert submit.json()["status"] == "submitted"

        review = client.post(f"/intakes/{intake_id}/review", headers=hdr)
        assert review.status_code == 200, f"submitted->reviewed should be 200, got {review.status_code}"
        assert review.json()["status"] == "reviewed"

        validate = client.post(f"/intakes/{intake_id}/submit", headers=hdr)
        assert validate.status_code == 200, (
            f"reviewed->validated_by_client should be 200, got {validate.status_code}"
        )
        assert validate.json()["status"] == "validated_by_client"

        # A further submit from validated_by_client is NOT allow-listed -> 409 (scope ceiling).
        forbidden = client.post(f"/intakes/{intake_id}/submit", headers=hdr)
        assert forbidden.status_code == 409, (
            f"a transition past the in-scope ceiling must be 409, got "
            f"{forbidden.status_code} ({forbidden.text!r})"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (d) transition audited — exactly one intake.status_changed row, {from,to} only
# ===========================================================================


def test_transition_audited(engine, monkeypatch):
    """One transition writes EXACTLY one ``intake.status_changed`` audit row in the same tx,
    with ``metadata={"from","to"}`` and no token/link/password key (T-06-08 / T-06-09)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    actor_uid = f"u-{space_id}"
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Audit Space")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_id))
        client = TestClient(app)
        hdr = {"Authorization": "Bearer ignored-overridden"}

        intake_id = client.post(
            "/intakes", json={"client_name": "Audited Co"}, headers=hdr
        ).json()["id"]

        submit = client.post(f"/intakes/{intake_id}/submit", headers=hdr)
        assert submit.status_code == 200, f"submit should be 200, got {submit.status_code}"

        # Read the audit trail as the migration owner (base engine bypasses RLS).
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT metadata FROM {SCHEMA}.audit_log "
                    "WHERE actor_uid = :uid AND event_type = 'intake.status_changed'"
                ),
                {"uid": actor_uid},
            ).all()

        assert len(rows) == 1, (
            f"a transition must write EXACTLY one intake.status_changed audit row, found "
            f"{len(rows)} (one-tx audit, QA-04 / T-06-08)"
        )
        metadata = rows[0][0] or {}
        assert metadata.get("from") == "draft" and metadata.get("to") == "submitted", (
            f"audit metadata must be the structured transition {{from,to}}, got {metadata!r}"
        )
        # No secret/link leaks into the audit metadata (T-06-09).
        for forbidden_key in ("link", "token", "password"):
            assert forbidden_key not in metadata, (
                f"audit metadata must never carry a {forbidden_key!r} key (T-06-09)"
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (x) canonical template — GET /intakes/templates serves the ONE in-repo form (D-CANON)
# ===========================================================================


def test_templates_returns_canonical_form():
    """GET /intakes/templates returns the single canonical Pulse template (D-CANON).

    The form is shared product config served from ``app.intake_canonical`` — NOT per-space
    ``intake_templates`` rows — so the endpoint touches NO database (no engine patch, no
    seeded space) and returns the same 14-section template to any authenticated caller.
    """
    from fastapi.testclient import TestClient

    from app.intake_canonical import (
        CANONICAL_TEMPLATE_ID,
        CANONICAL_TEMPLATE_NAME,
        CANONICAL_TEMPLATE_SCHEMA,
    )

    app = _build_app()
    try:
        # Auth override only — the handler is pure (no repo / no space scope).
        app.dependency_overrides[get_current_identity] = _as(_user(uuid.uuid4()))
        client = TestClient(app)

        resp = client.get(
            "/intakes/templates",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 200, (
            f"templates should be 200, got {resp.status_code} ({resp.text!r})"
        )
        body = resp.json()
        assert isinstance(body, list) and len(body) == 1, (
            "exactly ONE canonical template must be served (no per-space rows)"
        )
        tpl = body[0]
        assert tpl["id"] == str(CANONICAL_TEMPLATE_ID), "the canonical template id is served"
        assert tpl["name"] == CANONICAL_TEMPLATE_NAME
        sections = tpl["schema"]["sections"]
        assert len(sections) == len(CANONICAL_TEMPLATE_SCHEMA["sections"]) == 14, (
            "the full recovered Pulse form (14 sections) must be served verbatim"
        )
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# (y) superadmin create — create_in_space is the ONLY cross-space write path
# ===========================================================================


def test_create_in_space_is_superadmin_only():
    """``create_in_space`` rejects a USER-scoped repo (TENANT-02).

    A superadmin has no own space and creates into a CHOSEN target space via
    ``create_in_space``; a user must NEVER target a space, so the method refuses a
    user-scoped repo (``self._space_id is not None``). DB-free — the guard fires before any
    session use, so a ``None`` session is sufficient.
    """
    import pytest

    from app.db.repository import IntakeRepository

    # _user(...) sets a concrete space_id => user path => the guard must reject.
    user_repo = IntakeRepository(None, _user(uuid.uuid4()))
    with pytest.raises(RuntimeError, match="superadmin-only"):
        user_repo.create_in_space(uuid.uuid4(), client_name="X")
