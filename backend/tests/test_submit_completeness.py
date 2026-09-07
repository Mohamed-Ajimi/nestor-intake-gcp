"""DEF-23.2-13 — ``required`` / ``min_length`` / ``min_items`` enforced at the submit verb.

Until now these three lived ONLY in the browser (``validateField``, ``IntakeForm.tsx:33-40``).
A caller who skipped the form could submit an empty intake, and those answers are the research
inputs: they feed the context pack, the brief, and a ~$45 research run.

Two halves, deliberately different in kind (the shape ``test_answer_write_policy.py`` uses):

* **The pure half** drives ``check_submit_completeness`` directly — no FastAPI, no database.
* **The route half** (``integration``) drives the REAL router over the REAL Postgres and
  proves the two things a pure test cannot: that a refused submit leaves the STATUS UNTOUCHED,
  and that the ``reviewed -> validated_by_client`` transition is exempt.

⭐ THE TEST THAT MATTERS MOST IS THE EXEMPTION, not the enforcement.

``POST /intakes/{id}/submit`` serves BOTH transitions. Applying completeness to the second is
a LOCKOUT with no way out: in the validation phase every field except the ``proposal_list`` is
disabled in the browser AND refused by ``check_answer_batch``, so a client who fails the check
has no control with which to comply. The reviewed answer set is the ADMIN's work by then —
refusing the client's approval over a gap an operator left punishes the wrong party. Enforcing
everywhere is the obvious "improvement" someone will make later; ``test_route_validate_*`` is
here to stop it.

Every fixture value is DERIVED from the canonical schema. A test that spells a field key
proves the code works for that literal, not that the rule reads the schema (D-23.2-02).
"""

from __future__ import annotations

import uuid

import pytest

policy = pytest.importorskip("app.intake_write_policy")
canonical = pytest.importorskip("app.intake_canonical")

AnswerWriteViolation = policy.AnswerWriteViolation
check_submit_completeness = policy.check_submit_completeness

canonical_field = canonical.canonical_field
canonical_field_keys = canonical.canonical_field_keys
admin_only_field_keys = canonical.admin_only_field_keys

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Schema-derived helpers
# ---------------------------------------------------------------------------


def _client_keys() -> list[str]:
    """Canonical keys a client can actually fill (admin-only excluded)."""
    admin = admin_only_field_keys()
    return sorted(k for k in canonical_field_keys() if k not in admin)


def _required_keys() -> list[str]:
    return [k for k in _client_keys() if canonical_field(k).get("required")]


def _one_key_with(predicate, what: str) -> str:
    """The single canonical key matching ``predicate``, or skip if the schema has none."""
    matches = [k for k in _client_keys() if predicate(canonical_field(k))]
    if not matches:
        pytest.skip(f"the canonical schema declares no {what}")
    return matches[0]


def _min_length_of(field: dict):
    value = (field.get("validation") or {}).get("min_length")
    return field.get("min_length") if value is None else value


def _sample_value(field: dict):
    """The smallest value satisfying ``field``'s own stated constraints."""
    field_type = field.get("type")
    if field_type == "longtext":
        return "x" * max(int(_min_length_of(field) or 1), 1)
    if field_type == "radio":
        options = field.get("options") or []
        return next((o.get("value") for o in options if isinstance(o, dict)), "")
    if field_type in ("list", "proposal_list", "files"):
        return [f"entry {i + 1}" for i in range(max(int(field.get("min_items") or 0), 1))]
    if field_type == "email":
        return "client@example.test"
    if field_type == "date":
        return "2030-01-01"
    return "filled"


def _complete() -> dict:
    """A complete client answer map: every REQUIRED field filled to its minimum."""
    return {k: _sample_value(canonical_field(k)) for k in _required_keys()}


def _refused(answers, *, role="user") -> AnswerWriteViolation:
    with pytest.raises(AnswerWriteViolation) as excinfo:
        check_submit_completeness(answers, role=role)
    return excinfo.value


# ===========================================================================
# THE PURE HALF
# ===========================================================================


def test_complete_answer_set_is_accepted():
    """The baseline: a form filled exactly to its minimums passes. Without this the suite
    could go green by refusing everything."""
    check_submit_completeness(_complete(), role="user")


def test_the_schema_actually_declares_required_fields():
    """Guard against a vacuous suite: if the schema declared nothing required, every
    enforcement test below would pass while enforcing nothing."""
    assert len(_required_keys()) > 0, "the canonical form declares no required field"


def test_empty_answer_set_is_refused_422():
    violation = _refused({})
    assert violation.code == 422


@pytest.mark.parametrize("field_key", _required_keys())
def test_each_required_field_is_individually_enforced(field_key):
    """Drop ONE required field from an otherwise complete set — each must be refused.

    Parametrized over the schema rather than asserted once: a rule that happened to check
    only the first key would pass a single-case test.
    """
    answers = _complete()
    del answers[field_key]
    assert _refused(answers).code == 422


@pytest.mark.parametrize("empty", [None, "", []])
def test_required_field_present_but_empty_is_refused(empty):
    """Emptiness matches the BROWSER's definition: null, "", empty list."""
    answers = _complete()
    answers[_required_keys()[0]] = empty
    assert _refused(answers).code == 422


def test_min_length_is_enforced_on_longtext():
    key = _one_key_with(
        lambda f: f.get("type") == "longtext" and _min_length_of(f),
        "longtext field with a min_length",
    )
    minimum = int(_min_length_of(canonical_field(key)))
    answers = _complete()

    answers[key] = "x" * (minimum - 1)
    assert _refused(answers).code == 422

    answers[key] = "x" * minimum
    check_submit_completeness(answers, role="user")


def test_min_items_is_enforced_on_list():
    key = _one_key_with(
        lambda f: f.get("type") == "list" and int(f.get("min_items") or 0) > 0,
        "list field with a min_items",
    )
    minimum = int(canonical_field(key)["min_items"])
    answers = _complete()

    answers[key] = [f"entry {i}" for i in range(minimum - 1)]
    assert _refused(answers).code == 422

    answers[key] = [f"entry {i}" for i in range(minimum)]
    check_submit_completeness(answers, role="user")


def test_optional_field_left_blank_is_accepted():
    """A minimum applies to a value that EXISTS. An optional blank must not trip one."""
    optional = [k for k in _client_keys() if not canonical_field(k).get("required")]
    if not optional:
        pytest.skip("the canonical form declares no optional field")
    answers = _complete()
    for key in optional:
        answers[key] = None
    check_submit_completeness(answers, role="user")


def test_admin_only_fields_are_never_required_of_a_client():
    """A client cannot write an admin-only field (404), so requiring one would make the form
    permanently unsubmittable. Derived, so a future admin-only field is covered."""
    answers = _complete()
    for key in admin_only_field_keys():
        answers.pop(key, None)
    check_submit_completeness(answers, role="user")


def test_superadmin_is_exempt():
    """Same polarity and same reason as ``check_answer_batch``."""
    check_submit_completeness({}, role="superadmin")


def test_an_unknown_role_is_constrained_not_exempted():
    """Deny by default: a role added later must be CONSTRAINED, not waved through."""
    assert _refused({}, role="reviewer").code == 422


# ===========================================================================
# THE ROUTE HALF — the REAL router over the REAL Postgres (integration)
# ===========================================================================

_ROUTE_DEPS_ERROR: str | None = None
try:  # pragma: no cover - import-shape guard, exercised by the skip path
    import firebase_admin  # noqa: F401

    from app.api import auth_routes as _auth_routes
    from app.api import intake_routes as _intake_routes
    from app.auth import dependencies as _dependencies
    from app.auth import identity as _identity_mod
    from app.db import session as _session_mod
except Exception as exc:  # pragma: no cover
    _ROUTE_DEPS_ERROR = f"route-level deps unavailable: {exc}"

route_test = pytest.mark.skipif(
    _ROUTE_DEPS_ERROR is not None, reason=_ROUTE_DEPS_ERROR or ""
)

AUTH = {"Authorization": "Bearer ignored-overridden"}


def _user(space_id):
    return _identity_mod.Identity(
        uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id)
    )


def _as(identity):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(_session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    _auth_routes.protected_router.include_router(_intake_routes.intake_router)
    app = FastAPI()
    app.include_router(_auth_routes.protected_router)
    return app


def _seed_space(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": f"Submit Completeness {space_id}"},
        )


def _seed_intake(engine, set_space, space_id, intake_id, status="draft") -> None:
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


def _read_status(engine, set_space, space_id, intake_id) -> str:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"), {"id": intake_id}
        ).first()
    return row[0]


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id}
        )


@route_test
@pytest.mark.integration
def test_route_incomplete_draft_submit_is_422_and_status_unchanged(
    engine, set_space, monkeypatch
):
    """An incomplete draft is refused 422 AND stays ``draft``.

    The status assertion is the point: a refusal that still advanced the row would leave the
    intake submitted-but-empty, which is worse than not enforcing at all.
    """
    from fastapi.testclient import TestClient

    space_id, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space_id)
        _seed_intake(engine, set_space, space_id, intake_id, status="draft")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space_id))

        resp = TestClient(app).post(f"/intakes/{intake_id}/submit", headers=AUTH)

        assert resp.status_code == 422, (
            f"an incomplete draft submit must be 422, got {resp.status_code} ({resp.text!r})"
        )
        assert _read_status(engine, set_space, space_id, intake_id) == "draft", (
            "a refused submit must leave the status untouched"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


@route_test
@pytest.mark.integration
def test_route_complete_draft_submit_is_200(
    engine, set_space, monkeypatch, complete_answer_batch
):
    """The client route stays OPEN and EXACTLY 200 once the form is filled (pinned row 6)."""
    from fastapi.testclient import TestClient

    space_id, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space_id)
        _seed_intake(engine, set_space, space_id, intake_id, status="draft")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space_id))
        client = TestClient(app)

        saved = client.patch(
            f"/intakes/{intake_id}/answers",
            json={"answers": complete_answer_batch()},
            headers=AUTH,
        )
        assert saved.status_code == 200, f"seeding answers failed: {saved.text!r}"

        resp = client.post(f"/intakes/{intake_id}/submit", headers=AUTH)

        assert resp.status_code == 200, (
            f"a complete draft submit must be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["status"] == "submitted"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


@route_test
@pytest.mark.integration
@pytest.mark.parametrize("status", ["reviewed"])
def test_route_validate_transition_is_exempt_from_completeness(
    engine, set_space, monkeypatch, status
):
    """⭐ ``reviewed -> validated_by_client`` must stay 200 on an INCOMPLETE answer set.

    This is the lockout guard. In the validation phase the client has exactly one writable
    field, so a client refused here can never comply and never proceed. Enforcing at both
    transitions is the plausible-looking change this test exists to make go red.
    """
    from fastapi.testclient import TestClient

    space_id, intake_id = uuid.uuid4(), uuid.uuid4()
    app = _build_app()
    try:
        _seed_space(engine, space_id)
        # Deliberately NO answers at all — the strongest form of incomplete.
        _seed_intake(engine, set_space, space_id, intake_id, status=status)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[_dependencies.get_current_identity] = _as(_user(space_id))

        resp = TestClient(app).post(f"/intakes/{intake_id}/submit", headers=AUTH)

        assert resp.status_code == 200, (
            f"{status} -> validated_by_client must NOT be gated on completeness, got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["status"] == "validated_by_client"
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)
