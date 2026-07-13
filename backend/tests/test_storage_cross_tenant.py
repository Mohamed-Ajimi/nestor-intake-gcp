"""Storage cross-tenant denial suite (D-08 / T-09-05) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED/skipped until 09-02
lands the storage router (backend/app/api/storage_routes.py). Do NOT stub the
routes here — 09-02 turns this file GREEN.

Clones test_intake_cross_tenant.py exactly: ``pytestmark = integration``,
imports guarded with ``pytest.importorskip``, ONLY the engine factories
patched, ``get_current_identity`` overridden with a fabricated ``Identity``,
and EXACTLY 404 asserted for every cross-tenant case (never ``in (403, 404)``
— a 403 would leak existence, BOLA/IDOR). The ``app.storage.gcs`` seam is
faked so a broken handler can never touch a real bucket.

What each case proves (D-08 / T-09-05):

| Test                                    | Proves                                     |
|-----------------------------------------|--------------------------------------------|
| ``upload_cross_tenant``                 | user-A upload to user-B's intake -> 404,   |
|                                         | nothing reaches the seam.                  |
| ``signed_url_cross_tenant``             | user-A signed-url on user-B's intake ->    |
|                                         | 404, the signer is never called.           |
| ``delete_cross_tenant``                 | user-A delete on user-B's intake -> 404,   |
|                                         | object + source row untouched.             |
| ``forged_key_prefix``                   | user-A on their OWN intake but a key whose |
|                                         | prefix is NOT {space}/{intake}/ -> 404     |
|                                         | (key-prefix assert), no seam call.         |
| ``null_space_403``                      | a user Identity with space_id=None ->      |
|                                         | EXACTLY 403 (the only data-route 403).     |
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
storage_routes_mod = pytest.importorskip("app.api.storage_routes")  # RED until 09-02

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A broken/forbidden ``user`` Identity with NO space (D-04 default-deny -> 403)."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch ONLY the engine factories session.py imported (testcontainer swap)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(storage_routes_mod.storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


# ---------------------------------------------------------------------------
# Two-space seeding (shape copied from test_intake_cross_tenant.py)
# ---------------------------------------------------------------------------


def _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_a, "name": "Storage space A (denial suite)"},
        )
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_b, "name": "Storage space B (denial suite)"},
        )
    for space_id, intake_id in ((space_a, intake_a), (space_b, intake_b)):
        with engine.begin() as conn:
            set_space(conn, space_id)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :space_id, 'submitted')"
                ),
                {"id": intake_id, "space_id": space_id},
            )


def _seed_source(engine, set_space, space_id, intake_id, key) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_sources "
                "(id, space_id, intake_id, kind, storage_path, file_name) "
                "VALUES (:id, :space_id, :intake_id, 'audio', :storage_path, 'b.m4a')"
            ),
            {
                "id": uuid.uuid4(),
                "space_id": space_id,
                "intake_id": intake_id,
                "storage_path": key,
            },
        )


def _cleanup_spaces(engine, space_a, space_b) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
            {"a": space_a, "b": space_b},
        )


def _no_seam_calls(fake_gcs) -> bool:
    return all(fake_gcs[k] == [] for k in ("uploads", "signed_urls", "deletes", "downloads"))


# ===========================================================================
# Case: upload_cross_tenant — user-A upload to user-B's intake -> EXACTLY 404
# ===========================================================================


def test_upload_cross_tenant_returns_404(engine, set_space, two_spaces, fake_gcs, monkeypatch):
    """user-A POST upload against user-B's intake -> 404 (exact), no seam call."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_b}/storage/uploads",
            files={"file": ("verslag.pdf", b"%PDF-1.4 x", "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        # EXACT 404 — never `in (403, 404)` (D-08 existence-hiding).
        assert resp.status_code == 404, (
            f"cross-tenant upload must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r}). 403/2xx would leak existence (BOLA/IDOR)."
        )
        assert str(space_b) not in resp.text, "404 body leaked the foreign space_id."
        assert _no_seam_calls(fake_gcs), (
            "a denied cross-tenant upload must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: signed_url_cross_tenant — user-A signed-url on user-B's intake -> 404
# ===========================================================================


def test_signed_url_cross_tenant_returns_404(
    engine, set_space, two_spaces, fake_gcs, monkeypatch
):
    """user-A GET signed-url for user-B's intake -> 404 (exact), signer never called."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()
    # A perfectly-formed space-B key: ownership (not key shape) must deny this.
    key_b = f"{space_b}/{intake_b}/attachments/{uuid.uuid4()}-verslag.pdf"

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)

        resp = client.get(
            f"/intakes/{intake_b}/storage/signed-url",
            params={"path": key_b, "expires_in": 300},
            headers=AUTH,
        )

        assert resp.status_code == 404, (
            f"cross-tenant signed-url must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert _no_seam_calls(fake_gcs), (
            "a denied cross-tenant signed-url must NEVER invoke the signer."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: delete_cross_tenant — user-A delete on user-B's intake -> 404
# ===========================================================================


def test_delete_cross_tenant_returns_404(
    engine, set_space, two_spaces, fake_gcs, monkeypatch
):
    """user-A DELETE against user-B's intake -> 404 (exact); B's source row survives."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()
    key_b = f"{space_b}/{intake_b}/audio/{uuid.uuid4()}-gesprek.m4a"

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        _seed_source(engine, set_space, space_b, intake_b, key_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_b}/storage/objects",
            json={"paths": [key_b]},
            headers=AUTH,
        )

        assert resp.status_code == 404, (
            f"cross-tenant delete must be EXACTLY 404, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert _no_seam_calls(fake_gcs), (
            "a denied cross-tenant delete must NEVER reach the storage seam."
        )
        # Space-B's source row is UNTOUCHED (re-read as its owner).
        with engine.begin() as conn:
            set_space(conn, space_b)
            remaining = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.intake_sources "
                    "WHERE storage_path = :key"
                ),
                {"key": key_b},
            ).scalar_one()
        assert remaining == 1, (
            "cross-tenant delete leaked through: space-B's intake_sources row is gone."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: forged_key_prefix — own intake, foreign key prefix -> 404 (D-08)
# ===========================================================================


def test_forged_key_prefix_returns_404(
    engine, set_space, two_spaces, fake_gcs, monkeypatch
):
    """user-A on their OWN intake with a key outside {space_a}/{intake_a}/ -> 404.

    The ownership gate passes (it IS user-A's intake) — the key-PREFIX assert
    is what must deny the forged path (D-08): a key aimed at space-B's tree
    can never be signed or deleted through space-A's intake.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()
    forged = f"{space_b}/{intake_b}/attachments/{uuid.uuid4()}-loot.pdf"

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)

        signed = client.get(
            f"/intakes/{intake_a}/storage/signed-url",
            params={"path": forged, "expires_in": 300},
            headers=AUTH,
        )
        assert signed.status_code == 404, (
            f"a forged key prefix on signed-url must be EXACTLY 404, "
            f"got {signed.status_code} (body={signed.text!r})."
        )

        deleted = client.request(
            "DELETE",
            f"/intakes/{intake_a}/storage/objects",
            json={"paths": [forged]},
            headers=AUTH,
        )
        assert deleted.status_code == 404, (
            f"a forged key prefix on delete must be EXACTLY 404, "
            f"got {deleted.status_code} (body={deleted.text!r})."
        )

        assert _no_seam_calls(fake_gcs), (
            "a forged-prefix key must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# Case: null_space_403 — user with space_id=None -> EXACTLY 403
# ===========================================================================


def test_null_space_403_user_denied(engine, set_space, two_spaces, fake_gcs, monkeypatch):
    """A ``user`` Identity with ``space_id=None`` -> EXACTLY 403 on a storage route.

    D-04: the ONLY data-route 403 — distinct from the 404 cross-tenant codes
    (no enumeration confusion). No session is opened, no seam call is made.
    """
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_two_spaces(engine, set_space, space_a, space_b, intake_a, intake_b)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_null_space_user())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_a}/storage/uploads",
            files={"file": ("verslag.pdf", b"%PDF-1.4 x", "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        # EXACT 403 — the null-space default-deny (D-04), NOT the 404 data code.
        assert resp.status_code == 403, (
            f"null-space user must be EXACTLY 403, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert _no_seam_calls(fake_gcs), (
            "a 403-denied request must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)
