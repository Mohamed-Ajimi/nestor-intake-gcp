"""USER-01/03 + QA-04 admin-endpoint suite — drives the REAL ``admin_router`` over Postgres.

This is the endpoint-level counterpart to ``test_cross_tenant_denial.py``: it mounts the
REAL ``app.api.admin_routes.admin_router`` under the default-deny ``protected_router``,
overrides ``get_current_identity`` with a fabricated superadmin (no live IdP), patches the
engine FACTORY ``session_mod.get_superadmin_engine`` to the conftest connect-as
``app_superadmin`` engine, and patches the ``app.auth.admin_users.*`` Admin-SDK calls to
fakes — so the PRODUCTION admin path (``get_admin_session`` -> the real handlers ->
``audit.log`` on the request tx) runs verbatim against the testcontainer.

**Wave 0 RED scaffold**: ``app.api.admin_routes`` and the rest land in plan 04, so this
suite is RED until then. ``pytestmark = pytest.mark.integration`` makes it SKIP without
Docker; the ``importorskip`` guards make it COLLECT cleanly on this dev box.

What each case pins (05-VALIDATION ``-k`` selectors / threat register):

| ``-k`` selector            | Proves                                                          |
|----------------------------|----------------------------------------------------------------|
| ``invite``                 | POST /admin/users -> 200 + action LINK only (never a token/pw, |
|                            | T-5-02); a ``status="active"`` membership row + ONE            |
|                            | ``user.invited`` audit row land in PG (USER-01 / QA-04).      |
| ``deactivate``             | POST .../deactivate flips status->"deactivated" + audits;      |
|                            | reactivate flips back to "active" (AUTH-04 DB half).            |
| ``space``                  | POST /admin/spaces creates an org (status="active"); PATCH     |
|                            | edits; .../deactivate soft-deletes; NO DELETE route (USER-03). |
| ``template``               | POST .../templates clones a default; PATCH edits schema JSON.  |
| ``user_role_403`` / 403    | a ``user`` Identity -> 403 on EVERY admin route (T-5-03 EoP).  |
| ``409`` (guardrails)       | self-deactivation, last-active-superadmin, duplicate invite    |
|                            | all map to 409 Conflict (Pattern 5 / Pitfall 5).               |

DESIGN (CR-01 parity with the denial suite): patch ONLY the engine factory the production
``session.py`` imports (``session_mod.get_superadmin_engine``) so the REAL
``get_admin_session`` body — the ``role != "superadmin"`` 403 raise, the
``maker.begin()`` one-tx wiring — runs unchanged. The IdP is the one boundary that cannot
run locally, so ``get_current_identity`` is overridden (legitimate stand-in) and the
``admin_users.*`` SDK calls are faked.

Authoritative references:
- backend/tests/test_intake_cross_tenant.py (the drive-the-REAL-route + fabricated-Identity
    + ``superadmin_engine`` + ``_patch_engine_factories`` + ``_build_app`` template)
- backend/app/api/intake_routes.py (router-under-protected_router, pydantic view/patch, 404 map)
- .planning/phases/05-user-space-management/05-RESEARCH.md § Patterns 1/3/5 / § Code Examples
- .planning/phases/05-user-space-management/05-PATTERNS.md § test_admin_routes.py / § admin_routes.py
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box (Wave 0).
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

# app.* lands in plans 02/03/04 — importorskip so this suite COLLECTS cleanly until then.
admin_routes = pytest.importorskip("app.api.admin_routes")
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
admin_users = pytest.importorskip("app.auth.admin_users")
auth_routes = pytest.importorskip("app.api.auth_routes")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
admin_router = admin_routes.admin_router
protected_router = auth_routes.protected_router
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"

# Local testcontainer credential ONLY for the connect-as app_superadmin engine — never a
# production secret (production reads the password from Secret Manager, Path B / D-05a).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no single space)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _user(space_id: uuid.UUID) -> "Identity":
    """A space-scoped ``user`` Identity — must be denied (403) on every admin route."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    """A ``get_current_identity`` override yielding ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patch: run the REAL get_admin_session against the testcontainer
# ---------------------------------------------------------------------------


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin engine factory ``session.py`` imported, so the REAL
    ``get_admin_session`` routes to the testcontainer's connect-as app_superadmin engine.

    ``app/db/session.py`` does ``from app.db.base import ... get_superadmin_engine``, so the
    name to patch lives in ``session_mod`` (not ``base``). Only the engine SOURCE is swapped;
    the production dependency body runs verbatim.
    """
    monkeypatch.setattr(
        session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine
    )


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's routing: ``current_user = 'app_superadmin'`` makes the 0003
    ``*_superadmin_all`` bypass policy match. Because ``app_superadmin`` is a plain
    non-superuser ``LOGIN`` role (created by conftest), it is subject to RLS and to the
    0003/0005/0006 GRANTs — so a missing GRANT on the new ``audit_log`` table (Pitfall 1)
    fails the test loudly here. Mirrors test_cross_tenant_denial.py:156-181.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )

    sa_url = engine.url.set(
        username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD
    )
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


# ---------------------------------------------------------------------------
# Faked Admin SDK (no live IdP) — patch the wrapper module's auth.* calls
# ---------------------------------------------------------------------------


def _fake_admin_sdk():
    """Return a ``patch.multiple``-style context patching every ``admin_users.auth`` call the
    invite/deactivate flow makes, so no live Identity Platform is touched.

    ``create_user`` -> a fake uid; ``generate_password_reset_link`` -> a benign action LINK
    (never a token/password — the invite response must carry only this link, T-5-02).
    """
    return patch.multiple(
        admin_users,
        create_invited_user=MagicMock(return_value="invited-uid"),
        generate_set_password_link=MagicMock(
            return_value="https://idp/action?oobCode=ACTIONCODE"
        ),
        deactivate_user=MagicMock(return_value=None),
        reactivate_user=MagicMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# Two-space-free seeding helpers (admin path operates cross-space, root tables)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    """Insert an organization (a space) directly — ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organizations (id, name, slug) "
            "VALUES (:id, :name, :slug)"
        ),
        {"id": space_id, "name": name, "slug": f"sp-{space_id}"},
    )


def _cleanup_space(engine, space_id: uuid.UUID) -> None:
    """Delete a seeded organization (CASCADE removes its memberships)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def _count_audit(engine, *, actor_uid: str, event_type: str) -> int:
    """Count ``audit_log`` rows for an actor/event_type (read as the migration owner)."""
    from sqlalchemy import func, select

    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_uid == actor_uid, AuditLog.event_type == event_type)
        ).scalar_one()


# ---------------------------------------------------------------------------
# App builder (the REAL routers under test)
# ---------------------------------------------------------------------------


def _build_app():
    """Mount the REAL ``admin_router`` under the default-deny ``protected_router`` (mirrors
    app/main.py wiring + test_cross_tenant_denial.py:218-233).

    Also registers the production ``CodedError`` handler (mirrors app/main.py) so a
    ``CodedError(422, INVALID_LOCALE, ...)`` raised by the space create/update handlers
    renders as a 422 ``{"detail","code"}`` body here — not an unhandled 500 (Phase 11)."""
    from fastapi import FastAPI
    from fastapi.responses import JSONResponse

    from app.api.errors import CodedError

    protected_router.include_router(admin_router)
    app = FastAPI()
    app.include_router(protected_router)

    @app.exception_handler(CodedError)
    def _coded_error_handler(_request, exc: CodedError) -> JSONResponse:
        return JSONResponse(
            {"detail": exc.detail, "code": exc.code}, status_code=exc.status_code
        )

    return app


# ===========================================================================
# (a) invite — 200 + action LINK only; membership row + ONE audit row land in PG
# ===========================================================================


def test_invite_returns_action_link_and_lands_membership_and_audit(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/users {email, space_id} -> 200 with the action LINK in the body; an
    ``organization_memberships`` row (role="user", status="active", org=target) and EXACTLY
    one ``user.invited`` audit row land in PG. The body NEVER contains a token/password
    beyond the link (T-5-02 / USER-01 / QA-04)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Invite Target Space")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                "/admin/users",
                json={"email": "invitee@x.com", "space_id": str(space_id)},
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, f"invite should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.text
        # The action link is surfaced; no token/password leaks (T-5-02).
        assert "https://idp/action?oobCode=ACTIONCODE" in body, (
            "invite response must carry the action link (D-03)"
        )
        assert "password" not in body.lower(), "invite response must never carry a password"
        assert "id_token" not in body and "refresh_token" not in body, (
            "invite response must never carry a token"
        )

        # The membership row landed: role="user", status="active", scoped to the target org.
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT role, status FROM {SCHEMA}.organization_memberships "
                    "WHERE organization_id = :org"
                ),
                {"org": space_id},
            ).first()
        assert row is not None, "invite must write an organization_memberships row"
        assert row[0] == "user", "invited member role must be 'user' (D-01a)"
        assert row[1] == "active", "invited member status must be 'active'"

        # Exactly one user.invited audit row for this superadmin actor.
        assert _count_audit(engine, actor_uid="super", event_type="user.invited") == 1, (
            "invite must write exactly one user.invited audit row (QA-04)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (b) deactivate / reactivate — membership status flips + audit rows
# ===========================================================================


def test_deactivate_then_reactivate_flips_membership_status_and_audits(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/users/{id}/deactivate flips membership status -> "deactivated" and writes
    a ``user.deactivated`` audit row; /reactivate flips it back to "active" (AUTH-04 DB half)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    target_uid = f"member-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivate Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, :uid, :email, 'user', 'active')"
                ),
                {
                    "id": membership_id,
                    "org": space_id,
                    "uid": target_uid,
                    "email": "member@x.com",
                },
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            deact = client.post(
                f"/admin/users/{membership_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert deact.status_code == 200, (
                f"deactivate should be 200, got {deact.status_code} ({deact.text!r})"
            )

            with engine.connect() as conn:
                status = conn.execute(
                    text(
                        f"SELECT status FROM {SCHEMA}.organization_memberships WHERE id = :id"
                    ),
                    {"id": membership_id},
                ).scalar_one()
            assert status == "deactivated", "deactivate must set membership status='deactivated'"
            assert (
                _count_audit(engine, actor_uid="super", event_type="user.deactivated") == 1
            ), "deactivate must write a user.deactivated audit row (QA-04)"

            react = client.post(
                f"/admin/users/{membership_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert react.status_code == 200, (
                f"reactivate should be 200, got {react.status_code} ({react.text!r})"
            )
            with engine.connect() as conn:
                status = conn.execute(
                    text(
                        f"SELECT status FROM {SCHEMA}.organization_memberships WHERE id = :id"
                    ),
                    {"id": membership_id},
                ).scalar_one()
            assert status == "active", "reactivate must set membership status back to 'active'"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (c) space CRUD — create / edit / soft-deactivate; NO hard-delete route (USER-03)
# ===========================================================================


def test_space_create_edit_deactivate_and_no_delete_route(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/spaces creates an org (status="active"); PATCH edits name/slug;
    POST /admin/spaces/{id}/deactivate soft-deletes (status="deactivated"); a DELETE on
    /admin/spaces/{id} returns 404/405 — there is NO hard-delete affordance (USER-03 / D-10)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    created_id = None
    try:
        with _fake_admin_sdk():
            client = TestClient(app)
            create = client.post(
                "/admin/spaces",
                json={"name": "New Space", "slug": f"new-space-{uuid.uuid4()}"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert create.status_code in (200, 201), (
                f"space create should be 200/201, got {create.status_code} ({create.text!r})"
            )
            created_id = create.json()["id"]

            with engine.connect() as conn:
                status = conn.execute(
                    text(f"SELECT status FROM {SCHEMA}.organizations WHERE id = :id"),
                    {"id": created_id},
                ).scalar_one()
            assert status == "active", "newly created space status must be 'active'"

            edit = client.patch(
                f"/admin/spaces/{created_id}",
                json={"name": "Renamed Space"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert edit.status_code == 200, (
                f"space edit should be 200, got {edit.status_code} ({edit.text!r})"
            )
            with engine.connect() as conn:
                name = conn.execute(
                    text(f"SELECT name FROM {SCHEMA}.organizations WHERE id = :id"),
                    {"id": created_id},
                ).scalar_one()
            assert name == "Renamed Space", "PATCH must persist the new name"

            deact = client.post(
                f"/admin/spaces/{created_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert deact.status_code == 200, (
                f"space deactivate should be 200, got {deact.status_code} ({deact.text!r})"
            )
            with engine.connect() as conn:
                status = conn.execute(
                    text(f"SELECT status FROM {SCHEMA}.organizations WHERE id = :id"),
                    {"id": created_id},
                ).scalar_one()
            assert status == "deactivated", "deactivate must soft-delete (status='deactivated')"

            # NO hard-delete affordance: a DELETE on the space resource must NOT route to a
            # handler (USER-03 / D-10 — no hard delete anywhere).
            delete = client.delete(
                f"/admin/spaces/{created_id}",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert delete.status_code in (404, 405), (
                f"there must be NO space DELETE route; got {delete.status_code} "
                f"({delete.text!r}) — a hard-delete affordance violates D-10"
            )
    finally:
        app.dependency_overrides.clear()
        if created_id is not None:
            _cleanup_space(engine, uuid.UUID(created_id))


# ===========================================================================
# (d) template clone / edit — clone a default into a space, PATCH the schema JSON
# ===========================================================================


def test_template_clone_and_edit_schema(engine, monkeypatch, superadmin_engine):
    """POST /admin/spaces/{id}/templates clones a default template into the space; PATCH edits
    the template's schema JSON (USER-03)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Template Space")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            clone = client.post(
                f"/admin/spaces/{space_id}/templates",
                json={"name": "Cloned Intake", "schema": {"sections": []}},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert clone.status_code in (200, 201), (
                f"template clone should be 200/201, got {clone.status_code} ({clone.text!r})"
            )
            template_id = clone.json()["id"]

            edit = client.patch(
                f"/admin/spaces/{space_id}/templates/{template_id}",
                json={"schema": {"sections": [{"id": "s1", "fields": []}]}},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert edit.status_code == 200, (
                f"template schema edit should be 200, got {edit.status_code} ({edit.text!r})"
            )
            # The clone is scoped to the target space (TENANT — clone lands in the right org).
            # intake_templates is FORCE-RLS and the owner engine is policy-bound: the
            # verification read needs the space GUC set in the same transaction.
            with engine.begin() as conn:
                conn.execute(
                    text("SELECT set_config('app.current_space_id', :sid, true)"),
                    {"sid": str(space_id)},
                )
                owner = conn.execute(
                    text(
                        f"SELECT space_id FROM {SCHEMA}.intake_templates WHERE id = :id"
                    ),
                    {"id": template_id},
                ).scalar_one()
            assert str(owner) == str(space_id), "cloned template must belong to the target space"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (e) authorization — a `user` Identity gets 403 on EVERY admin route (T-5-03 EoP)
# ===========================================================================


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/admin/users", None),
        ("post", "/admin/users", {"email": "x@x.com", "space_id": str(uuid.uuid4())}),
        ("post", f"/admin/users/{uuid.uuid4()}/deactivate", None),
        ("post", f"/admin/users/{uuid.uuid4()}/reactivate", None),
        ("post", "/admin/spaces", {"name": "n", "slug": "s"}),
        ("patch", f"/admin/spaces/{uuid.uuid4()}", {"name": "n"}),
        ("post", f"/admin/spaces/{uuid.uuid4()}/deactivate", None),
        ("post", f"/admin/spaces/{uuid.uuid4()}/templates", {"name": "t", "schema": {}}),
    ],
)
def test_user_role_403_on_every_admin_route(
    engine, monkeypatch, superadmin_engine, method, path, body
):
    """A ``user`` Identity (role="user", space_id set) is denied EXACTLY 403 on every admin
    route — the superadmin-only gate enforced in ``get_admin_session`` BEFORE any session is
    opened (T-5-03 EoP). The 403 must fire regardless of whether the target resource exists."""
    from fastapi.testclient import TestClient

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_user(uuid.uuid4()))
    try:
        with _fake_admin_sdk():
            client = TestClient(app)
            kwargs = {"headers": {"Authorization": "Bearer ignored-overridden"}}
            if body is not None:
                kwargs["json"] = body
            resp = getattr(client, method)(path, **kwargs)

        assert resp.status_code == 403, (
            f"a user Identity must get EXACTLY 403 on {method.upper()} {path}, "
            f"got {resp.status_code} ({resp.text!r}) — superadmin-only gate (T-5-03)"
        )
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# (f) guardrails — self-deactivation / last-superadmin / duplicate invite -> 409
# ===========================================================================


def test_self_deactivation_returns_409(engine, monkeypatch, superadmin_engine):
    """A superadmin cannot deactivate their OWN account (target uid == identity.uid) -> 409
    Conflict (Pattern 5 guardrail)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Self Deactivation Space")
            # The membership row for the acting superadmin themself (provider_user_id="super").
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'super', 'super@x.com', 'superadmin', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 409, (
            f"self-deactivation must be 409 Conflict, got {resp.status_code} ({resp.text!r})"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# (g) space default_locale — create/update persist + return; invalid-locale -> 422 (Phase 11)
# ===========================================================================


def test_space_create_persists_and_returns_default_locale(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/spaces {name, default_locale:"fr"} -> 200 with default_locale="fr" in the
    body; the organizations row persists default_locale="fr" and the space.created audit
    metadata records it (D-07 / D-10 / QA-04)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    created_id = None
    try:
        with _fake_admin_sdk():
            client = TestClient(app)
            create = client.post(
                "/admin/spaces",
                json={
                    "name": "FR Space",
                    "slug": f"fr-space-{uuid.uuid4()}",
                    "default_locale": "fr",
                },
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert create.status_code in (200, 201), (
                f"space create should be 200/201, got {create.status_code} ({create.text!r})"
            )
            body = create.json()
            created_id = body["id"]
            assert body["default_locale"] == "fr", (
                "the SpaceView must return the persisted default_locale (D-07)"
            )

            with engine.connect() as conn:
                loc = conn.execute(
                    text(
                        f"SELECT default_locale FROM {SCHEMA}.organizations WHERE id = :id"
                    ),
                    {"id": created_id},
                ).scalar_one()
            assert loc == "fr", "create must persist organizations.default_locale='fr'"
    finally:
        app.dependency_overrides.clear()
        if created_id is not None:
            _cleanup_space(engine, uuid.UUID(created_id))


def test_space_create_omitted_default_locale_falls_back_to_nl(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/spaces with NO default_locale -> the column server_default ("nl") applies,
    and the SpaceView returns default_locale="nl" (D-07 non-null base)."""
    from fastapi.testclient import TestClient

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    created_id = None
    try:
        with _fake_admin_sdk():
            client = TestClient(app)
            create = client.post(
                "/admin/spaces",
                json={"name": "Default Locale Space", "slug": f"dl-{uuid.uuid4()}"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert create.status_code in (200, 201), (
                f"space create should be 200/201, got {create.status_code} ({create.text!r})"
            )
            body = create.json()
            created_id = body["id"]
            assert body["default_locale"] == "nl", (
                "omitting default_locale must fall back to the 'nl' column server_default"
            )
    finally:
        app.dependency_overrides.clear()
        if created_id is not None:
            _cleanup_space(engine, uuid.UUID(created_id))


def test_space_update_persists_default_locale(engine, monkeypatch, superadmin_engine):
    """PATCH /admin/spaces/{id} {default_locale:"en"} -> 200 with default_locale="en"; the
    organizations row is updated and the SpaceView reflects it (D-07)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Update Locale Space")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            patch_resp = client.patch(
                f"/admin/spaces/{space_id}",
                json={"default_locale": "en"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            assert patch_resp.status_code == 200, (
                f"space locale patch should be 200, got {patch_resp.status_code} "
                f"({patch_resp.text!r})"
            )
            assert patch_resp.json()["default_locale"] == "en", (
                "PATCH must return the updated default_locale in the SpaceView"
            )

            with engine.connect() as conn:
                loc = conn.execute(
                    text(
                        f"SELECT default_locale FROM {SCHEMA}.organizations WHERE id = :id"
                    ),
                    {"id": space_id},
                ).scalar_one()
            assert loc == "en", "PATCH must persist organizations.default_locale='en'"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_space_create_invalid_locale_returns_422_coded(
    engine, monkeypatch, superadmin_engine
):
    """POST /admin/spaces {default_locale:"de"} -> 422 with code=INVALID_LOCALE; NO row is
    written (the validation runs BEFORE the create — T-11-04 Input Validation)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    slug = f"invalid-locale-{uuid.uuid4()}"
    try:
        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                "/admin/spaces",
                json={"name": "Bad Locale Space", "slug": slug, "default_locale": "de"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 422, (
            f"an invalid default_locale must be 422, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("code") == "INVALID_LOCALE", (
            "the 422 body must carry the machine code INVALID_LOCALE (D-11)"
        )

        # No organizations row was written (validation ran before the create).
        with engine.connect() as conn:
            count = conn.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.organizations WHERE slug = :slug"),
                {"slug": slug},
            ).scalar_one()
        assert count == 0, "a rejected invalid-locale create must NOT write a row"
    finally:
        app.dependency_overrides.clear()


def test_space_update_invalid_locale_returns_422_coded(
    engine, monkeypatch, superadmin_engine
):
    """PATCH /admin/spaces/{id} {default_locale:"xx"} -> 422 code=INVALID_LOCALE; the existing
    row's default_locale is UNCHANGED (validation runs before the write — T-11-04)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Update Bad Locale Space")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.patch(
                f"/admin/spaces/{space_id}",
                json={"default_locale": "xx"},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 422, (
            f"an invalid default_locale patch must be 422, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert resp.json().get("code") == "INVALID_LOCALE", (
            "the 422 body must carry the machine code INVALID_LOCALE (D-11)"
        )

        with engine.connect() as conn:
            loc = conn.execute(
                text(
                    f"SELECT default_locale FROM {SCHEMA}.organizations WHERE id = :id"
                ),
                {"id": space_id},
            ).scalar_one()
        assert loc == "nl", "a rejected patch must leave default_locale unchanged (still 'nl')"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_last_active_superadmin_deactivation_returns_409(
    engine, monkeypatch, superadmin_engine
):
    """Deactivating the FINAL active superadmin -> 409 Conflict (count active superadmin
    memberships before disabling; refuse if it would hit zero — Pattern 5 guardrail)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        # Use a DISTINCT acting superadmin so this is NOT self-deactivation — the only reason
        # for the 409 here is "last active superadmin", isolating that guardrail.
        with engine.begin() as conn:
            # Clear any other active superadmins so the target is provably the last one.
            conn.execute(
                text(
                    f"UPDATE {SCHEMA}.organization_memberships "
                    "SET status='deactivated' WHERE role='superadmin'"
                )
            )
            _create_space(conn, space_id, "Last Superadmin Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'last-super', 'last@x.com', 'superadmin', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        # Acting superadmin is a DIFFERENT uid ("super") so this is not self-deactivation.
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 409, (
            f"deactivating the last active superadmin must be 409, got {resp.status_code} "
            f"({resp.text!r})"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_duplicate_invite_returns_409(engine, monkeypatch, superadmin_engine):
    """A duplicate invite (an active membership already exists for that email in the target
    space) -> 409 Conflict (Pitfall 5 — intentional duplicate maps to 409, not a 500)."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Duplicate Invite Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'existing-uid', 'dup@x.com', 'user', 'active')"
                ),
                {"id": uuid.uuid4(), "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                "/admin/users",
                json={"email": "dup@x.com", "space_id": str(space_id)},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 409, (
            f"duplicate invite must be 409 Conflict, got {resp.status_code} ({resp.text!r})"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


# ===========================================================================
# D-23.2-10 — a deactivated space accepts no NEW access (23.2-CONTEXT § 5)
#
# The space cascade only ever visits the members that existed when it ran. Anything that
# mints or restores access afterwards therefore opens a hole no cascade will ever close:
# the space reads "deactivated" on the operator's console while a live member sits in it.
# 409 (not 404) is deliberate — the caller is a superadmin who legitimately lists this
# space, so hiding it would be a lie about a resource they can already see.
# ===========================================================================


def _deactivate_space_row(engine, space_id: uuid.UUID) -> None:
    """Flip a seeded organization to ``status='deactivated'`` directly.

    ``_create_space`` takes no status (the admin suite's spaces are all active), and going
    through ``POST /admin/spaces/{id}/deactivate`` would drag the whole cascade — and its
    Admin-SDK doubles — into tests that are about a LATER call. A direct UPDATE seeds the
    one precondition under test and nothing else.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE {SCHEMA}.organizations SET status = 'deactivated' WHERE id = :id"),
            {"id": space_id},
        )


def test_invite_into_a_deactivated_space_returns_409_and_mints_no_idp_account(
    engine, monkeypatch, superadmin_engine
):
    """D-23.2-10: inviting into a deactivated space is refused BEFORE any side effect.

    Four negatives, because a 409 that had already minted the IdP account is the failure
    that actually matters — it leaves an enabled Identity Platform user with no membership
    row to ever find it by, and no cascade can reach it.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    email = f"newcomer-{uuid.uuid4()}@x.com"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivated Invite Space")
        _deactivate_space_row(engine, space_id)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        # Audit rows for actor "super" outlive individual tests, so assert on the DELTA
        # rather than an absolute count.
        before = _count_audit(engine, actor_uid="super", event_type="user.invited")

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                "/admin/users",
                json={"email": email, "space_id": str(space_id)},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            # Inside the patch context the module attribute IS the MagicMock.
            minted = list(admin_users.create_invited_user.call_args_list)

        assert resp.status_code == 409, (
            "inviting into a deactivated space must be 409 — the space grants no access, "
            f"so a new ACTIVE member in it is a hole no cascade closes. Got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert minted == [], (
            f"the refusal came AFTER the IdP account was minted: {minted}"
        )
        assert "action_link" not in resp.text, (
            f"a refused invite must not return an action link: {resp.text!r}"
        )

        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.organization_memberships "
                    "WHERE organization_id = :org"
                ),
                {"org": space_id},
            ).scalar_one()
        assert rows == 0, f"a refused invite landed {rows} membership row(s)"

        after = _count_audit(engine, actor_uid="super", event_type="user.invited")
        assert after == before, (
            f"a refused invite wrote {after - before} user.invited audit row(s)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_invite_into_a_deactivated_space_refuses_before_the_duplicate_check(
    engine, monkeypatch, superadmin_engine
):
    """The space guard fires BEFORE the duplicate-membership 409, and says so.

    Both refusals are 409, so ordering is only observable through the message. An operator
    told "User already invited to this space" would go looking for a member to remove; the
    real problem is the space itself. The two must stay distinguishable.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    email = f"dup-{uuid.uuid4()}@x.com"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivated Duplicate Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'existing-uid', :email, 'user', 'active')"
                ),
                {"id": uuid.uuid4(), "org": space_id, "email": email},
            )
        _deactivate_space_row(engine, space_id)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                "/admin/users",
                json={"email": email, "space_id": str(space_id)},
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            minted = list(admin_users.create_invited_user.call_args_list)

        assert resp.status_code == 409, (
            f"expected 409, got {resp.status_code} ({resp.text!r})"
        )
        assert "already invited" not in resp.text, (
            "the DUPLICATE message won the race — the space guard must be evaluated "
            f"first, or the operator is sent after the wrong problem: {resp.text!r}"
        )
        assert "deactivated" in resp.text, (
            f"the 409 must name the deactivated space as the reason: {resp.text!r}"
        )
        assert minted == [], f"a refused invite touched the IdP: {minted}"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_reactivate_user_in_a_deactivated_space_returns_409_and_changes_nothing(
    engine, monkeypatch, superadmin_engine
):
    """D-23.2-10: the INDIVIDUAL reactivate must not hand access back inside a dead space.

    Without this guard, ``POST /admin/users/{id}/reactivate`` restores a member the space
    cascade just took down — an undocumented way to re-enter a deactivated space one
    member at a time, with the space still reading "deactivated" to the operator.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivated Reactivate Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'cascaded-uid', 'cascaded@x.com', 'user', "
                    "'space_deactivated')"
                ),
                {"id": membership_id, "org": space_id},
            )
        _deactivate_space_row(engine, space_id)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        before = _count_audit(engine, actor_uid="super", event_type="user.reactivated")

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            enabled = list(admin_users.reactivate_user.call_args_list)

        assert resp.status_code == 409, (
            "reactivating a member of a deactivated space must be 409, got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert enabled == [], (
            f"the refusal came AFTER the IdP account was re-enabled: {enabled}"
        )

        with engine.connect() as conn:
            status = conn.execute(
                text(
                    f"SELECT status FROM {SCHEMA}.organization_memberships WHERE id = :id"
                ),
                {"id": membership_id},
            ).scalar_one()
        assert status == "space_deactivated", (
            f"a refused reactivate flipped the membership row anyway: {status!r}"
        )

        after = _count_audit(engine, actor_uid="super", event_type="user.reactivated")
        assert after == before, (
            f"a refused reactivate wrote {after - before} user.reactivated audit row(s)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_deactivate_user_in_a_deactivated_space_still_succeeds(
    engine, monkeypatch, superadmin_engine
):
    """The individual DEACTIVATE deliberately carries NO space guard — do not symmetrise.

    D-23.2-10 guards the two verbs that GRANT access. Deactivating a member of an already
    deactivated space is a safe, idempotent narrowing: it can only remove access, and it is
    how an operator fires someone whose space is down. A future reader tempted to
    "harmonise" the three verbs breaks this test, which is the point of it existing.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivated Narrowing Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'still-live-uid', 'live@x.com', 'user', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )
        _deactivate_space_row(engine, space_id)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with _fake_admin_sdk():
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
            disabled = list(admin_users.deactivate_user.call_args_list)

        assert resp.status_code == 200, (
            "deactivating a member of a deactivated space must still succeed — it only "
            f"ever narrows access. Got {resp.status_code} ({resp.text!r})"
        )
        assert [c.args[0] for c in disabled] == ["still-live-uid"], (
            f"the IdP disable must still happen: {disabled}"
        )
        with engine.connect() as conn:
            status = conn.execute(
                text(
                    f"SELECT status FROM {SCHEMA}.organization_memberships WHERE id = :id"
                ),
                {"id": membership_id},
            ).scalar_one()
        assert status == "deactivated", f"expected 'deactivated', got {status!r}"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)
