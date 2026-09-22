"""Superadmin status-override suite (D-23.5-01) — plan 23.5-01.

WHAT THIS FILE PROVES. Tester remark 1 of phase 23.5 is "allow to change the status to
whatever state". The three pre-existing lifecycle verbs (``/submit`` / ``/review`` /
``/deliver``) each carry a narrow allow-list which is the v1.0 scope-ceiling wall
(INTAKE-05 / T-06-06); those maps are NOT widened. Instead ``POST /intakes/{id}/status``
is a PARALLEL, audited, superadmin-only override that may target any of the SEVEN allowed
statuses — every value of ``nestor.intake_status`` except ``in_research``.

``in_research`` is excluded because entering it SPENDS MONEY: it is written by exactly one
call site, ``research_routes._RESEARCH_TRANSITIONS`` (``{"decomposed": "in_research"}``),
which queues a real Tribunal run. An override able to set it would let an operator
hand-place an intake into a state with no queued run behind it — a status that lies.

| Test family                          | Proves                                            |
|--------------------------------------|---------------------------------------------------|
| ``*_transition_matrix``              | every (from, to) pair over the 7 allowed statuses |
|                                      | is 200 and the ROW reads back ``to`` — backwards  |
|                                      | moves (``delivered`` -> ``reviewed``) included.   |
| ``*_in_research_409``                | the money wall: 409 AND the row is unchanged.     |
| ``*_unknown_status_422``             | a value outside the 8 is 422 AND unchanged.       |
| ``*_user_role_404``                  | role=``user`` IN THE INTAKE'S OWN SPACE gets      |
|                                      | EXACTLY 404 — no status change, no audit row.     |
| ``*_null_space_404``                 | the ORDERING proof: a null-space ``user`` gets    |
|                                      | the gate's 404, NOT ``get_tenant_repo``'s 403.    |
| ``*_cross_tenant_404``               | user-A -> space-B's intake is 404 and B's row is  |
|                                      | untouched.                                        |
| ``*_missing_intake_404``             | a superadmin targeting an id that does not exist  |
|                                      | gets 404 (``repo.get`` -> None), not a 500.       |
| ``*_audit_row``                      | EXACTLY ONE ``intake.status_changed`` row whose   |
|                                      | metadata is ``{"from","to","override": True}``.   |

WHY THERE IS NO "SUPERADMIN CROSS-TENANT 404" ARM. A superadmin's repo is the
``app_superadmin`` engine with the 0003 bypass policy (``session.get_tenant_repo``, D-05),
so reaching another space IS the operator's designed authority — that is what every other
operator verb does. The existence-hidden denial that matters on THIS route is the ROLE
gate (the ``user`` arms above) plus the non-existent-id arm; asserting a superadmin gets
404 for a foreign intake would be asserting the opposite of the platform's contract.

HARNESS PROVENANCE. The drive-the-real-route + fabricated-Identity + engine-factory-patch
scaffold, ``superadmin_engine``, ``_insert_intake_status``, ``_read_status``, ``_count_audit``
and ``_cleanup_spaces`` are COPIED (never imported — no private symbol crosses a test
module, matching the convention in ``test_operator_verb_gate.py``) from
``test_operator_verb_gate.py`` / ``test_intake_routes.py`` / ``test_report_delivery.py``.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker/DATABASE_URL);
``importorskip`` guards so the file COLLECTS on a box without the backend deps.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

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
ai_session_mod = pytest.importorskip("app.db.ai_session")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Password granted to the app_superadmin role for the connect-as superadmin engine (test
#: only — the SAME literal test_operator_verb_gate / test_mail_endpoints use, so the role's
#: password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

#: The SEVEN statuses the override may target — every ``nestor.intake_status`` value except
#: ``in_research``. Written out as a literal rather than imported from the route module ON
#: PURPOSE: if someone widens ``_OVERRIDE_STATUSES`` to include ``in_research``, an imported
#: constant would make this suite agree with the change instead of catching it.
_ALLOWED = (
    "draft",
    "submitted",
    "reviewed",
    "validated_by_client",
    "decomposed",
    "delivered",
    "archived",
)


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the D-04 default-deny case ``get_tenant_repo`` 403s."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="super-override", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the ``session.py`` and ``ai_session.py`` engine factories (both namespaces)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in both namespaces (the superadmin happy-path arms)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach.
    Shape copied from ``test_operator_verb_gate.superadmin_engine``.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD "
                f"'{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


# ---------------------------------------------------------------------------
# Seeding / reading helpers (copied, never imported — see the module docstring)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake_status(conn, set_space, space_id, intake_id, status: str) -> None:
    """Insert one intake at an EXPLICIT status (GUC set so the 0002 WITH CHECK passes)."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, :status, 'Acme')"
        ),
        {"id": intake_id, "space_id": space_id, "status": status},
    )


def _read_status(engine, set_space, space_id, intake_id):
    """Re-read the intake's status AS ITS OWNER (space GUC set), or None if absent."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
            {"id": intake_id},
        ).scalar_one_or_none()


def _status_audit_rows(engine, space_id, target):
    """Return the ``event_metadata`` of every ``intake.status_changed`` row for ONE intake.

    The ``target`` filter is load-bearing (copied reasoning from
    ``test_operator_verb_gate._count_audit``): the conftest ``engine`` connects as the
    migration owner, for which the audit read is NOT space-filtered, so a query filtered
    only by ``event_type`` would see every sibling test's rows and make "exactly one" depend
    on collection order.
    """
    from sqlalchemy import select, text

    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        return [
            row[0]
            for row in conn.execute(
                select(AuditLog.event_metadata)
                .where(AuditLog.event_type == "intake.status_changed")
                .where(AuditLog.target == str(target))
            ).all()
        ]


def _count_status_audit(engine, space_id, target) -> int:
    return len(_status_audit_rows(engine, space_id, target))


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + intake_router."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _cleanup_spaces(engine, *space_ids) -> None:
    """Delete the seeded organizations AND this suite's audit rows.

    ``audit_log.space_id`` is a plain nullable column with NO ForeignKey, deliberately, so
    the trail outlives its space (``models/audit.py``) — dropping the organization does NOT
    cascade the rows away. This suite writes a LOT of ``intake.status_changed`` rows (the
    matrix arm alone writes dozens), and ``test_intake_routes.test_transition_audited``
    counts globally on the owner engine, so leaving them behind would turn a pre-existing
    test red purely on collection order (measured precedent: ``test_operator_verb_gate``).
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": sid}
            )
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


# ---------------------------------------------------------------------------
# The scenario context manager — one seeded space/intake per case
# ---------------------------------------------------------------------------


class _Scenario:
    def __init__(self, app, space_id, intake_id):
        self.app = app
        self.space_id = space_id
        self.intake_id = intake_id

    def client(self):
        from fastapi.testclient import TestClient

        # raise_server_exceptions=False so an unexpected handler fault surfaces as a 500
        # RESPONSE this suite can assert on, rather than a traceback that hides the status
        # a real caller would have seen.
        return TestClient(self.app, raise_server_exceptions=False)


@contextmanager
def _scenario(engine, set_space, monkeypatch, identity, status: str, *, sa_engine=None):
    """Seed space + intake@status; wire the overrides; always clean up.

    ``identity`` is either a ready ``Identity`` (null-space / superadmin arms) or a CALLABLE
    taking the freshly-minted ``space_id`` — which is how the ``user``-role arms get an
    identity scoped to the intake's OWN space. That scoping is the point: a cross-space user
    is already 404'd by ``repo.get``, so only an OWN-SPACE user proves the ROLE gate.
    """
    space_id = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Status override space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_id, intake_id, status)

        _patch_engine_factories(monkeypatch, engine)
        if sa_engine is not None:
            _patch_superadmin_engine(monkeypatch, sa_engine)
        resolved = identity(space_id) if callable(identity) else identity
        app.dependency_overrides[get_current_identity] = _as(resolved)

        yield _Scenario(app, space_id, intake_id)
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


def _assert_denied(resp, label: str) -> None:
    """EXACTLY 404 with the gate's byte-exact detail — never 403 / 401 / 422 / 500."""
    assert resp.status_code == 404, (
        f"{label}: an unauthorized caller must get EXACTLY 404 (existence-hidden, "
        f"D-23.1-02), got {resp.status_code} ({resp.text!r}). A 403 is an existence "
        f"oracle; a 422 would mean the body was malformed and the denial proved nothing."
    )
    assert resp.json().get("detail") == "Intake not found", (
        f"{label}: the 404 detail is part of the convention and is asserted byte-exact "
        f"(app/auth/gates.py), got {resp.json()!r}"
    )


# ===========================================================================
# (0) the constants themselves — no DB, so these run on any box
# ===========================================================================


def test_override_allow_list_is_the_eight_statuses_minus_in_research():
    """``_OVERRIDE_STATUSES`` is exactly the ``nestor.intake_status`` enum minus the money one.

    Derived from the ORM enum rather than retyped, so ADDING a ninth status to the enum
    turns this red and forces a decision about whether an operator may hand-set it — the
    silent-default failure mode ("new status is override-able because nobody looked") is
    exactly what a literal list here would allow.
    """
    routes = pytest.importorskip("app.api.intake_routes")
    intake_model = pytest.importorskip("app.db.models.intake")

    all_statuses = set(intake_model.intake_status_enum.enums)
    assert all_statuses == set(_ALLOWED) | {"in_research"}, (
        f"the intake_status enum changed: {sorted(all_statuses)}. Decide whether the new "
        "value may be hand-set by an operator, then update _OVERRIDE_STATUSES and _ALLOWED."
    )
    assert routes._OVERRIDE_STATUSES == frozenset(_ALLOWED)
    assert "in_research" not in routes._OVERRIDE_STATUSES, (
        "in_research must never be override-able — entering it queues a paid research run "
        "(research_routes._RESEARCH_TRANSITIONS is its sole lawful writer)."
    )


def test_override_forbidden_set_has_exactly_one_member():
    """``_OVERRIDE_FORBIDDEN == {"in_research"}`` — the 409 detail string depends on it.

    ``override_status`` raises the LITERAL detail ``"Cannot override status to
    'in_research'"`` rather than interpolating the rejected value (it is a contract string
    the frontend keys a toast off). That is only truthful while the set has one member, so
    the invariant is pinned here instead of left to a comment.
    """
    routes = pytest.importorskip("app.api.intake_routes")

    assert routes._OVERRIDE_FORBIDDEN == frozenset({"in_research"})
    assert not (routes._OVERRIDE_FORBIDDEN & routes._OVERRIDE_STATUSES), (
        "a status cannot be both allow-listed and forbidden"
    )


def test_intake_patch_still_carries_no_status_field():
    """``IntakePatch`` gained NO status field — the override is a separate, gated verb.

    ``patch_intake``'s refusal to carry a status is the TENANT-02 / INTAKE-05 shape the
    module is written around. The whole reason ``StatusOverride`` is its own body model is
    so that refusal never has to be relaxed; this asserts nobody took the shortcut.
    """
    routes = pytest.importorskip("app.api.intake_routes")

    assert set(routes.IntakePatch.model_fields) == {"client_name"}, (
        f"IntakePatch must declare exactly one field (client_name), got "
        f"{sorted(routes.IntakePatch.model_fields)} — a status field here would bypass the "
        "superadmin gate and the override audit marker entirely."
    )
    assert set(routes.StatusOverride.model_fields) == {"status"}


# ===========================================================================
# (a) the transition matrix — every allowed (from, to), backwards included
# ===========================================================================


@pytest.mark.parametrize("from_status", _ALLOWED)
@pytest.mark.parametrize("to_status", _ALLOWED)
def test_override_transition_matrix(
    engine, set_space, monkeypatch, superadmin_engine, from_status, to_status
):
    """Every (from, to) pair over the 7 allowed statuses is 200 and the ROW reads back ``to``.

    This is the whole point of remark 1: the three lifecycle verbs move an intake along ONE
    named edge each, so ``delivered`` -> ``reviewed`` (the operator's own example) and
    anything -> ``archived`` were reachable from NOWHERE. The assertion is on the re-read
    ROW, not on the response body alone — a handler that returned a fabricated view without
    patching would pass a body-only check.

    ``from == to`` is included deliberately: a same-status override is accepted and audited
    like any other move. One behaviour, no special case.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), from_status,
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status", json={"status": to_status}, headers=_HDR
        )
        assert resp.status_code == 200, (
            f"{from_status} -> {to_status} must be 200, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert resp.json()["status"] == to_status
        assert _read_status(engine, set_space, s.space_id, s.intake_id) == to_status, (
            f"{from_status} -> {to_status}: the response said {to_status!r} but the ROW "
            "did not change — the view was fabricated, not patched."
        )


# ===========================================================================
# (b) the money wall — in_research is 409 and the row is unchanged
# ===========================================================================


def test_override_to_in_research_is_409_and_status_unchanged(
    engine, set_space, monkeypatch, superadmin_engine
):
    """``in_research`` is refused with 409 and the intake is left exactly where it was.

    ``research_routes._RESEARCH_TRANSITIONS`` (``{"decomposed": "in_research"}``) stays the
    SOLE writer of this status, because entering it queues a paid Tribunal run. The
    unchanged-row assertion is the half that matters: a 409 returned AFTER a patch would
    still have hand-placed the intake into a state with no run behind it.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "decomposed",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status",
            json={"status": "in_research"},
            headers=_HDR,
        )
        assert resp.status_code == 409, (
            f"an override to in_research must be EXACTLY 409, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert _read_status(engine, set_space, s.space_id, s.intake_id) == "decomposed", (
            "the 409 leaked through — the intake was moved into in_research with no "
            "queued run behind it."
        )
        assert _count_status_audit(engine, s.space_id, s.intake_id) == 0, (
            "a refused override must write no intake.status_changed row"
        )


# ===========================================================================
# (c) an unknown status is 422 and the row is unchanged
# ===========================================================================


@pytest.mark.parametrize("bogus", ["nonsense", "DRAFT", "", "delivered; DROP TABLE"])
def test_override_unknown_status_is_422_and_status_unchanged(
    engine, set_space, monkeypatch, superadmin_engine, bogus
):
    """A target outside the 8 known statuses is 422 — no free-text value reaches repo.patch.

    The allow-list, not the DB enum, is the wall: relying on the enum would surface a
    500 from psycopg/pg8000 instead of a 422, and the failure mode of a mistyped status
    would be an exception trace rather than a refusal.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "reviewed",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status", json={"status": bogus}, headers=_HDR
        )
        assert resp.status_code == 422, (
            f"an unknown status {bogus!r} must be EXACTLY 422 (never 500 from the DB "
            f"enum), got {resp.status_code} ({resp.text!r})"
        )
        assert _read_status(engine, set_space, s.space_id, s.intake_id) == "reviewed"


# ===========================================================================
# (d) the role gate — a user in the intake's OWN space gets EXACTLY 404
# ===========================================================================


def test_override_user_role_404_no_side_effect(engine, set_space, monkeypatch):
    """role=``user`` IN THE INTAKE'S OWN SPACE cannot override: EXACTLY 404, nothing moved.

    Own-space scoping is the point — a cross-space user is already 404'd by ``repo.get``, so
    only an own-space user proves the ROLE gate rather than the ownership check.
    """
    with _scenario(engine, set_space, monkeypatch, _user, "reviewed") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status", json={"status": "delivered"}, headers=_HDR
        )
        _assert_denied(resp, "POST /status (user role)")
        assert _read_status(engine, set_space, s.space_id, s.intake_id) == "reviewed"
        assert _count_status_audit(engine, s.space_id, s.intake_id) == 0, (
            "a gated-out call must write no intake.status_changed row"
        )


def test_override_null_space_user_404_not_403(engine, set_space, monkeypatch):
    """The ORDERING proof: a null-space ``user`` gets the gate's 404, NOT the repo's 403.

    ``get_tenant_repo`` answers a null-space user with the D-04 default-deny **403**
    (``app/db/session.py``). FastAPI resolves a handler signature IN ORDER, so if
    ``Depends(get_tenant_repo)`` were declared before ``Depends(superadmin_gate)`` the
    repo's 403 would win — and a 403 where 404 is the convention tells an unauthorized
    caller the endpoint EXISTS. That is an existence oracle, and it is a change no reviewer
    would read as a security edit.
    """
    with _scenario(
        engine, set_space, monkeypatch, _null_space_user(), "reviewed"
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status", json={"status": "draft"}, headers=_HDR
        )
        _assert_denied(resp, "POST /status (null-space user)")
        assert _read_status(engine, set_space, s.space_id, s.intake_id) == "reviewed"


# ===========================================================================
# (e) cross-tenant — user-A -> space-B's intake is 404, B's row untouched
# ===========================================================================


def test_override_cross_tenant_404_foreign_row_untouched(
    engine, set_space, two_spaces, monkeypatch
):
    """user-A POST /intakes/{B}/status -> EXACTLY 404 and space-B's intake is unchanged.

    Two walls stand between the caller and the foreign row here and the test does not care
    which one fires first: the role gate (A is a ``user``) and, were A a superadmin, the
    ownership scope. What it asserts is the OUTCOME the D-07 convention promises — a
    byte-identical existence-hidden 404 and a foreign row that did not move.
    """
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Override X-Tenant A")
            _create_space(conn, space_b, "Override X-Tenant B")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_b, intake_b, "decomposed")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))

        from fastapi.testclient import TestClient

        resp = TestClient(app, raise_server_exceptions=False).post(
            f"/intakes/{intake_b}/status", json={"status": "archived"}, headers=_HDR
        )
        _assert_denied(resp, "POST /status (cross-tenant)")

        with engine.begin() as conn:
            set_space(conn, space_b)
            status_b = conn.execute(
                text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_b},
            ).scalar_one()
        assert status_b == "decomposed", (
            f"cross-tenant override leaked through: space_b intake status={status_b!r}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


def test_override_missing_intake_404(
    engine, set_space, monkeypatch, superadmin_engine
):
    """A superadmin targeting an id that does not exist gets 404 — ``repo.get`` -> None.

    The arm exists so the ownership branch is exercised on the AUTHORIZED path too: without
    it, "404" on this route would be proven only by the role gate, and a handler that
    dereferenced a ``None`` intake would 500 in production on the operator's first typo.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "draft",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{uuid.uuid4()}/status", json={"status": "archived"}, headers=_HDR
        )
        assert resp.status_code == 404, (
            f"a non-existent intake must be 404, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("detail") == "Intake not found"


# ===========================================================================
# (f) the audit row — exactly one, metadata {from, to, override: True}
# ===========================================================================


def test_override_writes_one_audit_row_marking_the_override(
    engine, set_space, monkeypatch, superadmin_engine
):
    """EXACTLY one ``intake.status_changed`` row with ``{"from","to","override": True}``.

    The ``override`` marker is what lets the trail tell an operator override apart from a
    lifecycle verb — without it a ``delivered`` -> ``reviewed`` row is indistinguishable
    from a legitimate transition that the allow-lists could never have produced. The
    metadata is also asserted to carry NO link/token/password key (T-06-09).
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "delivered",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/status", json={"status": "reviewed"}, headers=_HDR
        )
        assert resp.status_code == 200, resp.text

        rows = _status_audit_rows(engine, s.space_id, s.intake_id)
        assert len(rows) == 1, (
            f"an override must write EXACTLY one intake.status_changed row, got "
            f"{len(rows)}: {rows!r}"
        )
        assert rows[0] == {"from": "delivered", "to": "reviewed", "override": True}, (
            f"metadata must be exactly {{from, to, override}}, got {rows[0]!r}"
        )
        for banned in ("token", "link", "password", "url"):
            assert not any(banned in k.lower() for k in rows[0]), (
                f"audit metadata must never carry a {banned} (T-06-09): {rows[0]!r}"
            )
