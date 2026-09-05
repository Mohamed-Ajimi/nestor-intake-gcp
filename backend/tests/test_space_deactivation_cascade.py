"""SEC-02 — space deactivation actually deactivates (23.1-03 / D-23.1-03, D-23.1-11).

``23.1-CONTEXT.md`` § 2: ``deactivate_space`` used to write
``organizations.status='deactivated'`` and nothing else, and NO auth path reads that
column — so a "deactivated" space kept serving its members. This suite pins the cascade
that makes the flip real, reusing the per-user machinery
(``admin_users.deactivate_user`` = ``update_user(disabled=True)`` +
``revoke_refresh_tokens``) once per member.

What each half proves:

| Half        | Proves                                                              |
|-------------|---------------------------------------------------------------------|
| repo-level  | ``list_memberships_for_space`` is space-scoped and status-blind; the |
|             | third status value ``space_deactivated`` persists and reads as       |
|             | INACTIVE through the existing allow-list reads (D-23.1-11).         |
| route-level | the cascade, the selective inverse (an individually deactivated     |
|             | member is NOT un-fired), both 409 refusal guards, the partial-IdP-  |
|             | failure 502, and the idempotent retry (PLANNING RULING #2).         |

The Admin SDK is patched in EVERY test — no live Identity Platform call is ever made
(zero provider spend). Harness (engine-factory patch, fabricated Identity, fake
``admin_users.*``) mirrors ``tests/test_admin_routes.py``.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

admin_routes = pytest.importorskip("app.api.admin_routes")
admin_repo_mod = pytest.importorskip("app.db.admin_repo")
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
admin_users = pytest.importorskip("app.auth.admin_users")
auth_routes = pytest.importorskip("app.api.auth_routes")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
AdminRepo = admin_repo_mod.AdminRepo
admin_router = admin_routes.admin_router
protected_router = auth_routes.protected_router
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"

# The cascade's third status value, read from the module (not re-typed) so a rename
# breaks these tests loudly instead of leaving them asserting a stale literal.
SPACE_DEACTIVATED = admin_repo_mod._STATUS_SPACE_DEACTIVATED

_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral test only


# ---------------------------------------------------------------------------
# Harness (mirrors tests/test_admin_routes.py)
# ---------------------------------------------------------------------------


def _superadmin(uid: str = "super-cascade") -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no single space)."""
    return Identity(uid=uid, email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """A ``get_current_identity`` override yielding ``identity`` (closure)."""

    def _override():
        return identity

    return _override


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Route the REAL ``get_admin_session`` at the testcontainer's app_superadmin engine."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (the 0003 bypass role)."""
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER ROLE app_superadmin WITH LOGIN PASSWORD "
                f"'{_SUPERADMIN_TEST_PASSWORD}'"
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


@pytest.fixture
def repo(superadmin_engine):
    """An :class:`AdminRepo` on a real app_superadmin session (the repo-level half).

    Same engine, same ``Session`` class and same superadmin ``Identity`` that
    ``get_admin_session`` uses, minus the HTTP layer, so the accessor contract can be
    asserted directly.

    Deliberately NOT ``maker.begin()`` (which production uses for its one-tx-per-request
    rule): these tests must ``commit()`` mid-body so the ``finally`` cleanup's cascading
    DELETE on another connection is not blocked by an open write — and SQLAlchemy forbids
    further commands on a session whose ``begin()`` context manager has been committed out
    from under it. A plain session with autobegin allows commit-then-continue.
    """
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(bind=superadmin_engine, future=True)
    session = maker()
    try:
        yield AdminRepo(session, _superadmin())
    finally:
        session.rollback()
        session.close()


def _fake_admin_sdk(deactivate=None, reactivate=None):
    """Patch every ``admin_users`` call the cascade makes — NO live IdP, ever.

    ``deactivate``/``reactivate`` accept a custom mock (the partial-failure test hands in
    one that raises on the SECOND member only).
    """
    return patch.multiple(
        admin_users,
        create_invited_user=MagicMock(return_value="invited-uid"),
        generate_set_password_link=MagicMock(
            return_value="https://idp/action?oobCode=X"
        ),
        deactivate_user=deactivate or MagicMock(return_value=None),
        reactivate_user=reactivate or MagicMock(return_value=None),
    )


def _create_space(conn, space_id: uuid.UUID, name: str, status: str = "active") -> None:
    """Insert an organization (a space) directly — ``organizations`` is NOT RLS-scoped."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organizations (id, name, slug, status) "
            "VALUES (:id, :name, :slug, :status)"
        ),
        {"id": space_id, "name": name, "slug": f"sp-{space_id}", "status": status},
    )


def _create_membership(
    conn,
    membership_id: uuid.UUID,
    space_id: uuid.UUID,
    *,
    uid: str | None,
    email: str | None = None,
    role: str = "user",
    status: str = "active",
) -> None:
    """Insert one membership row (``provider_user_id`` may be NULL — nullable column)."""
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organization_memberships "
            "(id, organization_id, provider_user_id, email, role, status) "
            "VALUES (:id, :org, :uid, :email, :role, :status)"
        ),
        {
            "id": membership_id,
            "org": space_id,
            "uid": uid,
            "email": email or f"m-{membership_id}@x.com",
            "role": role,
            "status": status,
        },
    )


def _cleanup_space(engine, *space_ids: uuid.UUID) -> None:
    """Delete seeded organizations (CASCADE removes their memberships)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        for space_id in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": space_id},
            )


def _status_of(engine, membership_id: uuid.UUID) -> str:
    """Read one membership's status straight from PG (never through the code under test)."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(
            text(
                f"SELECT status FROM {SCHEMA}.organization_memberships WHERE id = :id"
            ),
            {"id": membership_id},
        ).scalar_one()


def _space_status(engine, space_id: uuid.UUID) -> str:
    """Read one space's status straight from PG."""
    from sqlalchemy import text

    with engine.connect() as conn:
        return conn.execute(
            text(f"SELECT status FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        ).scalar_one()


def _count_audit(engine, *, actor_uid: str, event_type: str) -> int:
    """Count ``audit_log`` rows for an actor/event_type (read as the migration owner)."""
    from sqlalchemy import func, select

    with engine.connect() as conn:
        return conn.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.actor_uid == actor_uid, AuditLog.event_type == event_type)
        ).scalar_one()


def _audit_metadata(engine, *, actor_uid: str, event_type: str) -> dict:
    """Read the single ``audit_log`` row's ``event_metadata`` for an actor/event_type.

    The sibling of :func:`_count_audit`. The cascade's counts (``members_cascaded`` /
    ``members_restored``) live in that JSONB payload, and reading them straight from PG is
    the only way to prove the audit trail does not inherit the over-claim D-23.2-09
    removes from the membership rows. Per-test actor uids keep ``scalar_one`` honest.
    """
    from sqlalchemy import select

    with engine.connect() as conn:
        return conn.execute(
            select(AuditLog.event_metadata).where(
                AuditLog.actor_uid == actor_uid, AuditLog.event_type == event_type
            )
        ).scalar_one()


def _build_app():
    """Mount the REAL ``admin_router`` under the default-deny ``protected_router``."""
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
# Task 1 — repo-level: the space-scoped accessor + the third status value
# ===========================================================================


def test_list_memberships_for_space_returns_every_status(engine, repo):
    """The accessor is status-BLIND: active, deactivated AND space_deactivated come back.

    The deactivate RETRY path depends on this — a member whose IdP call failed is already
    ``space_deactivated`` in the DB, so a status-filtered accessor would hand the retry an
    empty list and pressing the verb twice would be a no-op.
    """
    space_id = uuid.uuid4()
    ids = {
        status: uuid.uuid4()
        for status in ("active", "deactivated", SPACE_DEACTIVATED)
    }
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "All Statuses Space")
            for status, mid in ids.items():
                _create_membership(conn, mid, space_id, uid=f"uid-{mid}", status=status)

        rows = repo.list_memberships_for_space(space_id)
        got = {str(row.id): row.status for row in rows}
        assert set(got) == {str(mid) for mid in ids.values()}, (
            f"accessor must return all three memberships regardless of status, got {got}"
        )
        assert sorted(got.values()) == sorted(ids), (
            "each seeded status must survive the round-trip unchanged"
        )
    finally:
        _cleanup_space(engine, space_id)


def test_list_memberships_for_space_accepts_str_and_uuid(engine, repo):
    """The route hands the path param through as a ``str``; the id coercion (Pitfall 6)
    must make the ``str`` and ``UUID`` forms equivalent."""
    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Coercion Space")
            _create_membership(conn, membership_id, space_id, uid="uid-coerce")

        as_uuid = repo.list_memberships_for_space(space_id)
        as_str = repo.list_memberships_for_space(str(space_id))
        assert len(as_uuid) == 1 and len(as_str) == 1, (
            "both a UUID and a str space id must reach the same row"
        )
        assert as_uuid[0].id == as_str[0].id
    finally:
        _cleanup_space(engine, space_id)


def test_list_memberships_for_space_is_empty_for_a_space_with_no_members(engine, repo):
    """A space with no memberships yields ``[]`` — the cascade must not crash on it."""
    space_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Empty Space")

        assert list(repo.list_memberships_for_space(space_id)) == [], (
            "a space with no memberships must yield an empty list, not None/error"
        )
    finally:
        _cleanup_space(engine, space_id)


def test_list_memberships_for_space_never_returns_another_spaces_row(engine, repo):
    """Two seeded spaces: every ``AdminRepo`` method runs on the app_superadmin engine
    (0003 bypass — NO automatic ``space_id`` filter), so the explicit WHERE clause is the
    ONLY thing keeping the cascade from disabling a bystander tenant's members."""
    space_a, space_b = uuid.uuid4(), uuid.uuid4()
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A")
            _create_space(conn, space_b, "Space B")
            _create_membership(conn, mid_a, space_a, uid="uid-a")
            _create_membership(conn, mid_b, space_b, uid="uid-b")

        rows_a = repo.list_memberships_for_space(space_a)
        assert [row.id for row in rows_a] == [mid_a], (
            "the accessor leaked a membership from another space — the cascade would "
            "disable a bystander tenant's members"
        )
    finally:
        _cleanup_space(engine, space_a, space_b)


def test_space_deactivated_superadmin_is_not_counted_as_active(engine, repo):
    """``count_active_superadmins`` is an allow-list (``== "active"``), so the third status
    value reads as INACTIVE there by construction (D-23.1-11).

    Measured as a DELTA against the live count, not an absolute: the count is global (root
    table, cross-space) and other suites seed superadmin memberships.
    """
    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        before = repo.count_active_superadmins()
        with engine.begin() as conn:
            _create_space(conn, space_id, "Superadmin Count Space")
            _create_membership(
                conn, membership_id, space_id, uid="uid-super", role="superadmin"
            )

        assert repo.count_active_superadmins() == before + 1, (
            "sanity: an active superadmin membership must move the count"
        )

        rowcount = repo.set_membership_status(membership_id, SPACE_DEACTIVATED)
        # Commit the repo session's write NOW. The ``repo`` fixture holds one open
        # transaction for the whole test, and the ``finally`` cleanup DELETEs the space on
        # ANOTHER connection — its FK cascade onto this membership row would block forever
        # on the uncommitted UPDATE, hanging the suite rather than failing it.
        repo.session.commit()
        assert rowcount == 1, "set_membership_status must report one patched row"
        assert _status_of(engine, membership_id) == SPACE_DEACTIVATED, (
            "the exact string 'space_deactivated' must persist (plain String column — no "
            "PG enum, no CHECK: models/membership.py:43, migration 0006)"
        )
        assert repo.count_active_superadmins() == before, (
            "a space_deactivated superadmin must NOT count as active — if this fails, a "
            "deny-list read has replaced an allow-list read somewhere"
        )
    finally:
        _cleanup_space(engine, space_id)


def test_find_active_membership_ignores_a_space_deactivated_row(engine, repo):
    """The same allow-list proof from the other direction: the invite duplicate-guard's
    lookup must not see a cascaded member as active."""
    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    email = f"cascaded-{uuid.uuid4()}@x.com"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Find Active Space")
            _create_membership(
                conn, membership_id, space_id, uid="uid-find", email=email
            )

        assert repo.find_active_membership(space_id, email) is not None, (
            "sanity: an active membership is found"
        )
        repo.set_membership_status(membership_id, SPACE_DEACTIVATED)
        # Commit before the cleanup DELETE can collide with the open write (see the
        # sibling test — an uncommitted UPDATE blocks the FK cascade indefinitely).
        repo.session.commit()
        assert repo.find_active_membership(space_id, email) is None, (
            "a space_deactivated membership must not read as active"
        )
    finally:
        _cleanup_space(engine, space_id)


# ===========================================================================
# Task 2 — route-level: the cascade, the selective inverse, both guards, 502
# ===========================================================================


def test_deactivate_space_cascades_to_every_member_and_leaves_other_spaces_alone(
    engine, monkeypatch, superadmin_engine
):
    """The whole point of SEC-02: the space flip is accompanied by an IdP disable +
    refresh-token revoke for EVERY member, so an in-flight session stops working on the
    next request (``check_revoked=True``, dependencies.py:78).

    Asserted on the RECORDED call list (not a boolean flag) so "exactly once per member"
    is a real count, and with a SECOND seeded space so a cross-tenant cascade would fail.
    """
    from fastapi.testclient import TestClient

    space_id, bystander_id = uuid.uuid4(), uuid.uuid4()
    mid_a, mid_b, mid_bystander = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Cascade Space")
            _create_space(conn, bystander_id, "Bystander Space")
            _create_membership(conn, mid_a, space_id, uid="uid-a")
            _create_membership(conn, mid_b, space_id, uid="uid-b")
            _create_membership(conn, mid_bystander, bystander_id, uid="uid-bystander")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        # A per-test actor uid: audit_log.space_id carries NO ForeignKey (it survives a
        # soft-deactivated space by design), so rows are NOT cleaned up with the space —
        # counting by a shared actor would accumulate across tests.
        actor = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor))

        deact = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"deactivate should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert _space_status(engine, space_id) == "deactivated"
        assert _status_of(engine, mid_a) == SPACE_DEACTIVATED, (
            "member A must be marked with the CASCADE status, not plain 'deactivated'"
        )
        assert _status_of(engine, mid_b) == SPACE_DEACTIVATED

        called = sorted(call.args[0] for call in deact.call_args_list)
        assert called == ["uid-a", "uid-b"], (
            "deactivate_user must be called exactly once per member of the space — got "
            f"{deact.call_args_list}"
        )

        # The bystander tenant is untouched, in the DB and in the IdP.
        assert _status_of(engine, mid_bystander) == "active", (
            "the cascade crossed a tenant boundary"
        )
        assert _space_status(engine, bystander_id) == "active"

        assert (
            _count_audit(engine, actor_uid=actor, event_type="space.deactivated") == 1
        ), "the cascade must write exactly one space.deactivated audit row (QA-04)"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id, bystander_id)


def test_deactivate_space_unknown_space_returns_404(
    engine, monkeypatch, superadmin_engine
):
    """An id that matches no space -> 404, unchanged from the pre-cascade behaviour."""
    from fastapi.testclient import TestClient

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        deact = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{uuid.uuid4()}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 404, (
            f"unknown space must be 404, got {resp.status_code} ({resp.text!r})"
        )
        assert deact.call_args_list == [], "a 404 must not touch the IdP"
    finally:
        app.dependency_overrides.clear()


def test_deactivate_space_containing_the_acting_superadmin_returns_409_and_writes_nothing(
    engine, monkeypatch, superadmin_engine
):
    """T-23.1-09: the operator must not be able to lock themselves out by deactivating the
    space their own membership lives in. The guard runs BEFORE any write and before any
    IdP call — asserted on the DB (still active) and on the empty call list."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mid_self, mid_other = uuid.uuid4(), uuid.uuid4()
    acting_uid = f"acting-{uuid.uuid4()}"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Own Space")
            _create_membership(conn, mid_self, space_id, uid=acting_uid)
            _create_membership(conn, mid_other, space_id, uid="uid-other")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin(acting_uid))

        deact = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 409, (
            f"deactivating one's own space must be 409, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert _space_status(engine, space_id) == "active", "the 409 wrote to the space"
        assert _status_of(engine, mid_self) == "active"
        assert _status_of(engine, mid_other) == "active", (
            "the 409 must refuse BEFORE any membership flip"
        )
        assert deact.call_args_list == [], "the 409 must refuse BEFORE any IdP call"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_deactivate_space_holding_the_last_active_superadmins_returns_409(
    engine, monkeypatch, superadmin_engine
):
    """The per-user last-superadmin guardrail (T-5-15) raised to the space: a cascade that
    would drop the count of ACTIVE superadmins to zero is refused, nothing is written.

    Every other active superadmin membership is parked first so the seeded pair is
    provably the last — the count is global (root table, cross-space).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    mid_super_a, mid_super_b = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {SCHEMA}.organization_memberships "
                    "SET status='deactivated' WHERE role='superadmin'"
                )
            )
            _create_space(conn, space_id, "Last Superadmins Space")
            _create_membership(
                conn, mid_super_a, space_id, uid="uid-super-a", role="superadmin"
            )
            _create_membership(
                conn, mid_super_b, space_id, uid="uid-super-b", role="superadmin"
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        # A DIFFERENT acting uid, so the ONLY reason for the 409 is the superadmin count.
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        deact = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 409, (
            f"a cascade emptying the active-superadmin set must be 409, got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert _space_status(engine, space_id) == "active"
        assert _status_of(engine, mid_super_a) == "active"
        assert deact.call_args_list == [], "the 409 must refuse BEFORE any IdP call"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_deactivate_space_survives_a_member_with_no_provider_user_id(
    engine, monkeypatch, superadmin_engine
):
    """``provider_user_id`` is NULLABLE (a membership created before the IdP account
    exists). Such a member has nothing to disable, so the IdP loop skips it — but the DB
    flip still applies, and the handler must not crash."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mid_null, mid_real = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Null Uid Space")
            _create_membership(conn, mid_null, space_id, uid=None)
            _create_membership(conn, mid_real, space_id, uid="uid-real")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        deact = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"a NULL provider_user_id must not fail the cascade, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert _status_of(engine, mid_null) == SPACE_DEACTIVATED, (
            "a member with no IdP account is still flipped in the DB"
        )
        assert [call.args[0] for call in deact.call_args_list] == ["uid-real"], (
            "the IdP loop must skip the NULL uid and disable only the real one"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_partial_idp_failure_returns_502_and_flips_only_the_members_the_idp_disabled(
    engine, monkeypatch, superadmin_engine
):
    """The IdP cannot join the DB transaction, so a partial cascade is a real state.

    The fake raises on the SECOND member specifically, which proves four things at once:
    the loop does NOT stop early (the third member is still attempted), the flips that DID
    happen are COMMITTED despite the error response, the member the IdP REFUSED keeps
    ``active`` (D-23.2-09 — the DB must never claim a revocation the IdP did not perform),
    and the 502 body carries a COUNT with no email and no uid (T-23.1-11 / T-06-09 —
    identifiers belong in the audit row, not the browser).

    INVERTED in phase 23.2 (was
    ``test_partial_idp_failure_returns_502_with_a_count_only_and_keeps_the_db_flip``). Its
    closing loop asserted ``_status_of(mid) == SPACE_DEACTIVATED`` for ALL THREE members,
    which pinned F-04 — the over-claim — as expected behaviour. Everything else about the
    test is unchanged; only the status expectation for the refused member moved, and the
    space-row assertion stays because ``organizations.status`` is bookkeeping that grants
    no access.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mids = [uuid.uuid4() for _ in range(3)]
    uids = ["uid-one", "uid-two", "uid-three"]
    emails = [f"member{i}@x.com" for i in range(3)]
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Partial Failure Space")
            for mid, uid, email in zip(mids, uids, emails, strict=True):
                _create_membership(conn, mid, space_id, uid=uid, email=email)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        def _raise_on_second(uid):
            if uid == "uid-two":
                raise RuntimeError("IdP unavailable")

        deact = MagicMock(side_effect=_raise_on_second)
        with _fake_admin_sdk(deactivate=deact):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 502, (
            f"a partial IdP failure must be 502, got {resp.status_code} ({resp.text!r})"
        )

        attempted = sorted(call.args[0] for call in deact.call_args_list)
        assert attempted == sorted(uids), (
            f"the loop stopped early — only {attempted} were attempted"
        )

        body = resp.text
        assert "@" not in body, f"the 502 body leaked an email: {body!r}"
        for uid in uids:
            assert uid not in body, f"the 502 body leaked a uid ({uid}): {body!r}"
        assert "1" in body, "the 502 detail must state HOW MANY members are still enabled"

        # The DB flip survived the error response (the record of intent is not lost).
        assert _space_status(engine, space_id) == "deactivated", (
            "the 502 rolled back the space flip — the operator would see the space as "
            "active while two of its members are already disabled in the IdP"
        )
        # D-23.2-09: the split. Flipped for the two the IdP disabled; NOT flipped for the
        # one it refused, whose access is still live.
        checked = 0
        for mid, uid in zip(mids, uids, strict=True):
            got = _status_of(engine, mid)
            if uid == "uid-two":
                assert got == "active", (
                    "the member whose IdP disable FAILED was flipped anyway — the DB now "
                    "claims access is revoked while a valid token keeps working, and the "
                    f"operator's console repeats that claim. Status: {got!r}"
                )
            else:
                assert got == SPACE_DEACTIVATED, (
                    f"the 502 rolled back a membership flip that succeeded: {got!r}"
                )
            checked += 1
        assert checked == 3, f"the status split checked {checked} rows, expected 3"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_re_issuing_deactivate_retries_the_member_whose_idp_call_failed(
    engine, monkeypatch, superadmin_engine
):
    """PLANNING RULING #2's whole reason for existing: pressing the verb twice must RETRY.

    First press: the IdP rejects one member -> 502; the member it ACCEPTED is
    ``space_deactivated`` and the rejected one is still ``active`` (D-23.2-09 — the DB does
    not claim a revocation the IdP refused). Second press: the member list is status-BLIND,
    so BOTH are attempted again — and this time the rejected one lands, and the response is
    200.

    INVERTED in phase 23.2 alongside the partial-failure test above. The mid-test line
    ``assert _status_of(engine, mid_flaky) == SPACE_DEACTIVATED`` encoded the same F-04
    over-claim; the retry behaviour this test exists to prove is untouched, and the
    second-press assertion below is unchanged.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mid_ok, mid_flaky = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Retry Space")
            _create_membership(conn, mid_ok, space_id, uid="uid-ok")
            _create_membership(conn, mid_flaky, space_id, uid="uid-flaky")

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        first = MagicMock(
            side_effect=lambda uid: (_ for _ in ()).throw(RuntimeError("IdP down"))
            if uid == "uid-flaky"
            else None
        )
        with _fake_admin_sdk(deactivate=first):
            client = TestClient(app)
            resp1 = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp1.status_code == 502, (
            f"first press should report the partial failure, got {resp1.status_code}"
        )
        assert _status_of(engine, mid_flaky) == "active", (
            "the member the IdP refused must NOT be flipped — this row is the retry's own "
            "record that the disable never happened"
        )
        assert _status_of(engine, mid_ok) == SPACE_DEACTIVATED, (
            "the member the IdP DID disable must be flipped and committed"
        )

        second = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=second):
            client = TestClient(app)
            resp2 = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp2.status_code == 200, (
            f"the retry should succeed, got {resp2.status_code} ({resp2.text!r})"
        )
        retried = sorted(call.args[0] for call in second.call_args_list)
        assert retried == ["uid-flaky", "uid-ok"], (
            "the retry must re-attempt the already-space_deactivated members — a "
            "status-filtered member list makes the second press a silent no-op, and the "
            f"failed member never gets disabled. Attempted: {retried}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_reactivate_space_restores_the_cascaded_members(
    engine, monkeypatch, superadmin_engine
):
    """The inverse's happy path: space -> active, every ``space_deactivated`` membership ->
    active with one ``reactivate_user`` each, plus a ``space.reactivated`` audit row."""
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mid_a, mid_b = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Reactivate Space", status="deactivated")
            _create_membership(
                conn, mid_a, space_id, uid="uid-ra", status=SPACE_DEACTIVATED
            )
            _create_membership(
                conn, mid_b, space_id, uid="uid-rb", status=SPACE_DEACTIVATED
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        # Per-test actor uid — audit rows outlive the space (no FK on space_id).
        actor = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor))

        react = MagicMock(return_value=None)
        with _fake_admin_sdk(reactivate=react):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"reactivate should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert _space_status(engine, space_id) == "active"
        assert _status_of(engine, mid_a) == "active"
        assert _status_of(engine, mid_b) == "active"
        assert sorted(call.args[0] for call in react.call_args_list) == [
            "uid-ra",
            "uid-rb",
        ], "reactivate_user must be called exactly once per restored member"
        assert (
            _count_audit(engine, actor_uid=actor, event_type="space.reactivated") == 1
        ), "reactivate must write exactly one space.reactivated audit row"
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_reactivate_space_does_not_un_fire_an_individually_deactivated_member(
    engine, monkeypatch, superadmin_engine
):
    """THE assertion this plan exists for (T-23.1-08).

    A member fired INDIVIDUALLY (status ``deactivated``) before their space was taken down
    must stay fired when the space comes back. With a two-value status vocabulary the
    inverse cannot tell the two cases apart, and deactivate-then-reactivate a space
    becomes an undocumented way to restore revoked access — a silent grant, not a visible
    one. The member's IdP account must also stay disabled: ``reactivate_user`` is NOT
    called for them.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mid_cascaded, mid_fired = uuid.uuid4(), uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Un-firing Space", status="deactivated")
            _create_membership(
                conn, mid_cascaded, space_id, uid="uid-cascaded", status=SPACE_DEACTIVATED
            )
            _create_membership(
                conn, mid_fired, space_id, uid="uid-fired", status="deactivated"
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        react = MagicMock(return_value=None)
        with _fake_admin_sdk(reactivate=react):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"reactivate should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert _status_of(engine, mid_cascaded) == "active", (
            "the cascaded member must be restored"
        )
        assert _status_of(engine, mid_fired) == "deactivated", (
            "reactivating a space UN-FIRED an individually deactivated member — "
            "deactivate-then-reactivate is now a way to restore revoked access"
        )
        called = [call.args[0] for call in react.call_args_list]
        assert called == ["uid-cascaded"], (
            "reactivate_user must NOT be called for the individually deactivated member "
            f"— their IdP account must stay disabled. Called: {called}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_reactivate_space_unknown_space_returns_404(
    engine, monkeypatch, superadmin_engine
):
    """An id that matches no space -> 404, unchanged from the pre-cascade behaviour."""
    from fastapi.testclient import TestClient

    _patch_superadmin_engine(monkeypatch, superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        react = MagicMock(return_value=None)
        with _fake_admin_sdk(reactivate=react):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{uuid.uuid4()}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp.status_code == 404, (
            f"unknown space must be 404, got {resp.status_code} ({resp.text!r})"
        )
        assert react.call_args_list == [], "a 404 must not touch the IdP"
    finally:
        app.dependency_overrides.clear()


# ===========================================================================
# D-23.2-09 — IdP FIRST, DB second, on BOTH verbs (23.2-CONTEXT § 5, F-04 + F-07)
# ===========================================================================


def test_reactivate_partial_idp_failure_flips_only_the_members_the_idp_enabled(
    engine, monkeypatch, superadmin_engine
):
    """F-07's first half: a re-enable the IdP REFUSED must not read as restored.

    The mirror of the deactivate partial-failure test, on the verb that carried no
    partial-failure coverage at all before D-23.2-09. The fake raises on the SECOND member,
    proving at once that the loop does not stop early, that the two members the IdP DID
    enable are ``active``, and that the member it refused is STILL ``space_deactivated``.

    That last row is the whole fix. ``reactivate_space``'s target filter selects exactly
    ``space_deactivated`` rows, so flipping the refused member anyway (the pre-D-23.2-09
    ordering) makes the verb one-shot: the account stays disabled in the IdP forever while
    the database says it is back.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mids = [uuid.uuid4() for _ in range(3)]
    uids = ["uid-one", "uid-two", "uid-three"]
    emails = [f"member{i}@x.com" for i in range(3)]
    try:
        with engine.begin() as conn:
            _create_space(
                conn, space_id, "Reactivate Partial Failure", status="deactivated"
            )
            for mid, uid, email in zip(mids, uids, emails, strict=True):
                _create_membership(
                    conn, mid, space_id, uid=uid, email=email, status=SPACE_DEACTIVATED
                )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        actor = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor))

        def _raise_on_second(uid):
            if uid == "uid-two":
                raise RuntimeError("IdP unavailable")

        react = MagicMock(side_effect=_raise_on_second)
        with _fake_admin_sdk(reactivate=react):
            client = TestClient(app)
            resp = client.post(
                f"/admin/spaces/{space_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 502, (
            f"a partial IdP failure must be 502, got {resp.status_code} ({resp.text!r})"
        )

        attempted = sorted(call.args[0] for call in react.call_args_list)
        assert attempted == sorted(uids), (
            f"the loop stopped early — only {attempted} were attempted"
        )

        body = resp.text
        assert "@" not in body, f"the 502 body leaked an email: {body!r}"
        for uid in uids:
            assert uid not in body, f"the 502 body leaked a uid ({uid}): {body!r}"
        assert "1" in body, "the 502 detail must state HOW MANY members are still disabled"

        # organizations.status is bookkeeping and grants no access, so the space flip is
        # kept as the operator's record of intent even on the partial-failure path.
        assert _space_status(engine, space_id) == "active", (
            "the 502 rolled back the space flip — the record of intent is lost"
        )

        checked = 0
        for mid, uid in zip(mids, uids, strict=True):
            got = _status_of(engine, mid)
            if uid == "uid-two":
                assert got == SPACE_DEACTIVATED, (
                    "the member whose IdP re-enable FAILED was flipped to active anyway — "
                    "the DB now claims restored access the IdP never granted, and the "
                    f"retry will never select the row again. Status: {got!r}"
                )
            else:
                assert got == "active", (
                    f"a member the IdP DID enable was left at {got!r}"
                )
            checked += 1
        assert checked == 3, f"the status split checked {checked} rows, expected 3"

        meta = _audit_metadata(engine, actor_uid=actor, event_type="space.reactivated")
        assert meta["members_restored"] == 2, (
            "members_restored must count the rows this call ACTUALLY flipped, not "
            f"len(targets) — otherwise the audit trail inherits the over-claim. Got {meta}"
        )
        assert meta["idp_failed_uids"] == ["uid-two"], (
            f"the failed uid belongs in the audit row, not the response body. Got {meta}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_re_issuing_reactivate_retries_the_member_whose_idp_call_failed(
    engine, monkeypatch, superadmin_engine
):
    """F-07 proper: pressing reactivate twice must RETRY the member the IdP refused.

    Deactivate has always been retryable — its target list deliberately includes rows that
    are already ``space_deactivated``. Reactivate could not be given the same treatment
    (widening its filter to ``!= active`` would sweep up the individually deactivated
    members and undo T-23.1-08), so the ORDERING is the entire fix: flip after the IdP
    call, and the refused member keeps the status the retry selects on.

    Before D-23.2-09 the second press returned 200 having attempted NOTHING, because the
    first press had already marked every row active — the failure message's "Re-issue this
    request to retry" was a no-op on this verb.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mids = [uuid.uuid4() for _ in range(3)]
    uids = ["uid-one", "uid-two", "uid-three"]
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Reactivate Retry Space", status="deactivated")
            for mid, uid in zip(mids, uids, strict=True):
                _create_membership(
                    conn, mid, space_id, uid=uid, status=SPACE_DEACTIVATED
                )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        actor_first = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor_first))

        first = MagicMock(
            side_effect=lambda uid: (_ for _ in ()).throw(RuntimeError("IdP down"))
            if uid == "uid-two"
            else None
        )
        with _fake_admin_sdk(reactivate=first):
            client = TestClient(app)
            resp1 = client.post(
                f"/admin/spaces/{space_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp1.status_code == 502, (
            f"first press should report the partial failure, got {resp1.status_code}"
        )

        actor_second = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor_second))
        second = MagicMock(return_value=None)
        with _fake_admin_sdk(reactivate=second):
            client = TestClient(app)
            resp2 = client.post(
                f"/admin/spaces/{space_id}/reactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp2.status_code == 200, (
            f"the retry should succeed, got {resp2.status_code} ({resp2.text!r})"
        )
        retried = [call.args[0] for call in second.call_args_list]
        assert retried == ["uid-two"], (
            "F-07: the retry did not re-attempt exactly the member whose re-enable "
            "failed. With the DB flipped BEFORE the IdP call the first press marks every "
            "row active, so the second press selects nothing and returns 200 having done "
            f"NOTHING while the account stays disabled. Observed call_args_list: {retried}"
        )
        assert _status_of(engine, mids[1]) == "active", (
            "the retry must finally restore the member the first press could not"
        )

        # PER-CALL semantics: an audit row records what ITS OWN event did. A reader
        # reconstructs total state by summing the sequence (2 + 1), so a clean retry
        # legitimately reports ONE even though all three members are now active.
        meta = _audit_metadata(
            engine, actor_uid=actor_second, event_type="space.reactivated"
        )
        assert meta["members_restored"] == 1, (
            "the retry's audit row must count the rows THIS call flipped, not the total "
            f"now active. Got {meta}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)


def test_re_issuing_deactivate_after_partial_failure_audits_only_this_calls_flips(
    engine, monkeypatch, superadmin_engine
):
    """The deactivate retry under the NEW ordering, and the PER-CALL count it audits.

    A mirror of :func:`test_re_issuing_deactivate_retries_the_member_whose_idp_call_failed`
    (which is left untouched) with a third member and an audit assertion. It pins the
    semantics an operator reading the trail depends on: ``members_cascaded`` is the number
    of rows THIS call flipped, never the number of members currently down. The first press
    flips two and the retry flips one — ``1`` on the retry is CORRECT, not a second
    partial failure.
    """
    from fastapi.testclient import TestClient

    space_id = uuid.uuid4()
    mids = [uuid.uuid4() for _ in range(3)]
    uids = ["uid-one", "uid-two", "uid-three"]
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Deactivate Retry Count Space")
            for mid, uid in zip(mids, uids, strict=True):
                _create_membership(conn, mid, space_id, uid=uid)

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_app()
        actor_first = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor_first))

        first = MagicMock(
            side_effect=lambda uid: (_ for _ in ()).throw(RuntimeError("IdP down"))
            if uid == "uid-two"
            else None
        )
        with _fake_admin_sdk(deactivate=first):
            client = TestClient(app)
            resp1 = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )
        assert resp1.status_code == 502, (
            f"first press should report the partial failure, got {resp1.status_code}"
        )
        meta_first = _audit_metadata(
            engine, actor_uid=actor_first, event_type="space.deactivated"
        )
        assert meta_first["members_cascaded"] == 2, (
            f"the first press flipped exactly two rows. Got {meta_first}"
        )

        actor_second = f"super-cascade-{uuid.uuid4()}"
        app.dependency_overrides[get_current_identity] = _as(_superadmin(actor_second))
        second = MagicMock(return_value=None)
        with _fake_admin_sdk(deactivate=second):
            client = TestClient(app)
            resp2 = client.post(
                f"/admin/spaces/{space_id}/deactivate",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp2.status_code == 200, (
            f"the retry should succeed, got {resp2.status_code} ({resp2.text!r})"
        )
        retried = sorted(call.args[0] for call in second.call_args_list)
        assert retried == sorted(uids), (
            "the retry must re-attempt EVERY member — the already-space_deactivated rows "
            f"stay in the target list precisely so this works. Attempted: {retried}"
        )
        for mid in mids:
            assert _status_of(engine, mid) == SPACE_DEACTIVATED

        meta_second = _audit_metadata(
            engine, actor_uid=actor_second, event_type="space.deactivated"
        )
        assert meta_second["members_cascaded"] == 1, (
            "PER-CALL semantics: the retry flipped ONE row (the other two were already "
            "space_deactivated), so it audits 1 even though three members are now down. "
            f"Got {meta_second}"
        )
        assert meta_second["idp_failed_uids"] == [], (
            f"the retry had a healthy IdP. Got {meta_second}"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_space(engine, space_id)
