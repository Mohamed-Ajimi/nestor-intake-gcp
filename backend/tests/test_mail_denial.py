"""Cross-space mail denial suite (NOTIF-01/02 / T-10-06 / T-10-13) — the required gate.

Drives the REAL ``intake_router`` mail surface (Plan 10-03) over live Postgres through a
FastAPI ``TestClient``, exactly as ``test_intake_cross_tenant.py`` does for the intake CRUD
routes: ``protected_router`` (default-deny) -> the real ``intake_router`` -> the PRODUCTION
``get_tenant_repo`` -> the real :class:`IntakeRepository` (explicit ``WHERE`` + RLS) -> the
handler's 404 mapping. It proves that a user-A caller can neither list space-B's members nor
send a mail against a space-B intake — BOTH are existence-hidden 404s (D-07), and NO mail
ever leaves the building (``fake_resend`` records ZERO calls).

What each case proves:

| Test                                   | Proves                                                       |
|----------------------------------------|-------------------------------------------------------------|
| ``send_cross_tenant``                  | user-A POST /intakes/{B}/mail/validation -> EXACTLY 404 AND |
|                                        | ``fake_resend`` has ZERO calls (T-10-06 — no cross-space    |
|                                        | mail; the 404 fires BEFORE recipient resolution / send).    |
| ``members_read_cross_tenant``          | user-A GET /intakes/{B}/members -> EXACTLY 404 (T-10-13 —   |
|                                        | the members read cannot leak another space's member list).  |

DESIGN — identical engine-factory patching to ``test_intake_cross_tenant.py``: only the
engine FACTORIES ``session.py`` imported (``session_mod.get_engine`` /
``get_superadmin_engine``) are swapped for the conftest testcontainer engines, so the REAL
``get_tenant_repo`` body runs verbatim. ``get_current_identity`` is overridden with a
fabricated user-A Identity (no live IdP). ``fake_resend`` (conftest, Plan 01) fakes the
mail-egress seam so the "zero sends" assertion is exact and no network is touched.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker / DATABASE_URL);
``firebase_admin`` + ``app.*`` imports are ``importorskip``-guarded so the file COLLECTS on
the dev box without erroring.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

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
# Engine-factory patch (mirrors test_intake_cross_tenant._patch_engine_factories)
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the engine factory ``session.py`` imported so the REAL get_tenant_repo runs.

    Only the engine SOURCE is swapped for the testcontainer; the production dependency
    body (default-deny 403, ONE tx, GUC set) runs verbatim.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


# ---------------------------------------------------------------------------
# Two-space seeding helpers (shape copied from test_intake_cross_tenant.py)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID) -> None:
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
            "VALUES (:id, :space_id, 'draft')"
        ),
        {"id": intake_id, "space_id": space_id},
    )


def _insert_member(conn, space_id: uuid.UUID, email: str) -> uuid.UUID:
    """Insert one ACTIVE membership into a space (root table, not RLS-scoped). Return its id."""
    from sqlalchemy import text

    mid = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organization_memberships "
            "(id, organization_id, provider_user_id, email, role, status) "
            "VALUES (:id, :org, :uid, :email, 'user', 'active')"
        ),
        {"id": mid, "org": space_id, "uid": f"pu-{mid}", "email": email},
    )
    return mid


def _build_app():
    """FastAPI app carrying the REAL protected_router + intake_router (mirrors main.py)."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _cleanup_spaces(engine, *space_ids):
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


# ===========================================================================
# send_cross_tenant — user-A POST space-B mail -> 404 AND zero sends
# ===========================================================================


def test_send_cross_tenant_returns_404_and_zero_sends(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """user-A POST /intakes/{B}/mail/validation -> EXACTLY 404 and NO mail is sent.

    The intake resolves via ``get_tenant_repo``; space-B's intake is outside user-A's scope,
    so ``repo.get`` returns ``None`` and the handler raises 404 (existence-hidden, D-07)
    BEFORE any recipient resolution or ``resend.send`` — so ``fake_resend`` records ZERO calls
    (T-10-06: no cross-space mail ever leaves the building).
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (mail denial)")
            _create_space(conn, space_b, "Space B (mail denial)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)
            member_b = _insert_member(conn, space_b, "member-b@x.com")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_b}/mail/validation",
            json={"recipients": [str(member_b)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 404, (
            f"cross-space mail send must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/200 would leak existence or send cross-space."
        )
        assert fake_resend["calls"] == [], (
            "T-10-06 LEAK: a cross-space send reached the mail seam "
            f"(recorded {fake_resend['calls']!r})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# members_read_cross_tenant — user-A GET space-B members -> 404
# ===========================================================================


def test_members_read_cross_tenant_returns_404(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """user-A GET /intakes/{B}/members -> EXACTLY 404 (T-10-13 — no cross-space member leak).

    The members read is ``get_tenant_repo``-gated on the intake: space-B's intake is out of
    user-A's scope, so ``repo.get`` returns ``None`` -> 404 BEFORE any membership query. The
    read can therefore never leak another space's member emails.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (members denial)")
            _create_space(conn, space_b, "Space B (members denial)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)
            _insert_member(conn, space_b, "secret-member-b@x.com")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_b}/members",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 404, (
            f"cross-space members read must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert "secret-member-b@x.com" not in resp.text, (
            "T-10-13 LEAK: cross-space members read exposed a foreign member email."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)
