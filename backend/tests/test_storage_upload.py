"""Storage upload behavior suite (DOC-02 / D-02 / D-03 / D-04 / D-05 / D-07) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED until 09-02 lands
``POST /intakes/{intake_id}/storage/uploads`` (backend/app/api/storage_routes.py).
Do NOT stub the route here — 09-02 turns this file GREEN.

Every test fakes the ``app.storage.gcs`` seam via the ``fake_gcs`` conftest
fixture — no real bucket, no network, no credentials. What this file pins:

| Test                             | Proves                                             |
|----------------------------------|----------------------------------------------------|
| ``test_upload_writes_scoped_key``| the stored key is SERVER-authored and starts with  |
|                                  | ``{space_id}/{intake_id}/attachments/`` (DOC-02,   |
|                                  | D-05 — client path never trusted).                 |
| ``test_upload_413_over_cap``     | a body over 25 MB -> EXACTLY 413, nothing uploaded |
|                                  | (D-02 Whisper cap / D-03 authoritative read).      |
| ``test_upload_415_bad_type``     | an extension outside the D-04 allowlist -> EXACTLY |
|                                  | 415, nothing uploaded.                             |
| ``test_audio_upload_creates_source`` | an audio upload creates a SPACE-SCOPED         |
|                                  | ``intake_sources`` row whose ``storage_path`` is   |
|                                  | the object key, in the same request (D-07).        |

Harness style: engine factories patched only (``session_mod``), identity
overridden with a fabricated ``Identity`` — clones test_ai_transcribe.py /
test_intake_cross_tenant.py.
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

from app.api import storage_routes as storage_routes_mod  # noqa: E402  (RED until 09-02)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}

# D-02: the 25 MB per-file ceiling (Whisper per-file limit; < Cloud Run's 32 MB cap).
MAX_BYTES = 25 * 1024 * 1024

# Local testcontainer credential ONLY for the connect-as app_superadmin engine (mirrors
# test_admin_routes.py) — never a production secret.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no own space, CR-02)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch ONLY the engine factories session.py imported (testcontainer swap)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin engine factory session.py imported (CR-02 superadmin path)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Mirrors test_admin_routes.py: ``current_user = 'app_superadmin'`` makes the 0003
    ``*_superadmin_all`` bypass policy match, so ``create_in_space`` can insert the
    space-scoped ``intake_sources`` row cross-tenant (the CR-02 superadmin upload path).
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

    protected_router.include_router(storage_routes_mod.storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_space_and_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Storage upload space"},
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


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ===========================================================================
# Case: scoped key — the stored key is server-authored under {space}/{intake}/
# ===========================================================================


def test_upload_writes_scoped_key(engine, set_space, fake_gcs, monkeypatch):
    """A valid attachment upload stores under ``{space_id}/{intake_id}/attachments/``.

    DOC-02: the byte stream flows THROUGH the backend to the faked seam;
    D-05: the key is server-authored (uuid-prefixed, sanitized name) — the
    client only supplied a filename, never a path.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    payload = b"%PDF-1.4 fake-but-harmless"

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("verslag.pdf", payload, "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"valid upload should be 201, got {resp.status_code} (body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, (
            f"exactly one seam upload expected, got {len(fake_gcs['uploads'])}."
        )
        recorded = fake_gcs["uploads"][0]
        expected_prefix = f"{space}/{intake_id}/attachments/"
        assert recorded["key"].startswith(expected_prefix), (
            f"key must be server-authored under {expected_prefix!r}, "
            f"got {recorded['key']!r} (D-05 / DOC-02)."
        )
        assert recorded["data"] == payload, "the uploaded bytes must flow through unmodified."

        body = resp.json()
        assert body.get("path") == recorded["key"], (
            "response `path` must echo the stored object key."
        )
        assert body.get("size") == len(payload), "response `size` must be the byte count."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: 413 — over the 25 MB cap (D-02 / D-03 authoritative read)
# ===========================================================================


def test_upload_413_over_cap(engine, set_space, fake_gcs, monkeypatch):
    """A body over 25 MB -> EXACTLY 413; the seam is never called (D-02/D-03)."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    oversize = b"x" * (MAX_BYTES + 1)

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("groot-verslag.pdf", oversize, "application/pdf")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 413, (
            f"an over-cap upload must be EXACTLY 413, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake_gcs["uploads"] == [], (
            "a rejected oversize body must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: 415 — extension outside the D-04 allowlist
# ===========================================================================


def test_upload_415_bad_type(engine, set_space, fake_gcs, monkeypatch):
    """A disallowed extension/MIME -> EXACTLY 415; the seam is never called (D-04)."""
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
            data={"category": "attachments"},
            headers=AUTH,
        )

        assert resp.status_code == 415, (
            f"a disallowed type must be EXACTLY 415, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake_gcs["uploads"] == [], (
            "a type-rejected body must NEVER reach the storage seam."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: audio upload auto-registers a space-scoped intake_sources row (D-07)
# ===========================================================================


def test_audio_upload_creates_source(engine, set_space, fake_gcs, monkeypatch):
    """An audio upload creates an ``intake_sources`` row: storage_path == the key.

    D-07: the row is written in the SAME request (same session/tx as the
    ownership read) and carries the intake's space_id, so the Phase-7
    transcribe flow can find the object without any client bookkeeping.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("gesprek.m4a", b"\x00\x01fake-audio", "audio/mp4")},
            data={"category": "audio"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"audio upload should be 201, got {resp.status_code} (body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, "the audio bytes must reach the seam once."
        key = fake_gcs["uploads"][0]["key"]
        assert key.startswith(f"{space}/{intake_id}/audio/"), (
            f"audio key must live under the audio category, got {key!r}."
        )

        # The intake_sources row exists, is space-scoped, and points at the key.
        with engine.begin() as conn:
            set_space(conn, space)
            row = conn.execute(
                text(
                    f"SELECT storage_path, kind, space_id FROM {SCHEMA}.intake_sources "
                    "WHERE intake_id = :id"
                ),
                {"id": intake_id},
            ).first()
        assert row is not None, (
            "D-07: an audio upload must create an intake_sources row in the same request."
        )
        assert row[0] == key, (
            f"intake_sources.storage_path must equal the object key: {row[0]!r} != {key!r}."
        )
        assert row[1] == "audio", f"intake_sources.kind must be 'audio', got {row[1]!r}."
        assert str(row[2]) == str(space), "the source row must carry the intake's space_id."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: superadmin audio upload targets the intake's OWN space (CR-02)
# ===========================================================================


def test_superadmin_audio_upload_creates_source_in_space(
    engine, set_space, fake_gcs, monkeypatch, superadmin_engine
):
    """A superadmin (null-space identity) audio upload must succeed, not 500 (CR-02).

    The admin intake-detail page is operated by superadmins; a plain ``create()`` on a
    null-space repo raises the RuntimeError guard -> unhandled 500. The handler branches
    to ``create_in_space(intake.space_id, ...)`` so the space-scoped ``intake_sources``
    row is written into the intake's OWN space. The upload runs AFTER the DB write (WR-05),
    so a 201 proves both sides committed with no orphan.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("gesprek.m4a", b"\x00\x01fake-audio", "audio/mp4")},
            data={"category": "audio"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"superadmin audio upload must be 201 (CR-02), got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, "the audio bytes must reach the seam once."
        key = fake_gcs["uploads"][0]["key"]

        with engine.begin() as conn:
            set_space(conn, space)
            row = conn.execute(
                text(
                    f"SELECT storage_path, space_id FROM {SCHEMA}.intake_sources "
                    "WHERE intake_id = :id"
                ),
                {"id": intake_id},
            ).first()
        assert row is not None, (
            "CR-02: a superadmin audio upload must create the intake_sources row "
            "in the intake's own space via create_in_space (no 500)."
        )
        assert row[0] == key, "storage_path must equal the object key."
        assert str(row[1]) == str(space), (
            "create_in_space must target the intake's OWN space, not null."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# D-23.2-17 — the UPLOAD side of F-03, fixed here and NOT deferred
#
# `upload_file` used to take `category` straight from the form and validate it
# only against CATEGORIES, with no role check. A `role=user` could therefore
# upload into `reports/` — writing objects into the operator's deliverable prefix
# on a tenant-billed bucket and, once D-23.2-08 landed, creating objects they
# could no longer delete. Fixing one direction and deferring the other would have
# MANUFACTURED that asymmetry.
#
# This route is the ONLY producer of a `reports/` key: `_assert_report_key` in
# app/api/intake_routes.py accepts any staged path under `{space}/{intake}/reports/`
# and the delivery verb then LINKS it. So this role check is what stands between a
# `role=user` and a path the report-delivery guard would accept.
#
# The code is 422, NOT the delete side's 404, and the difference is deliberate:
# on delete the caller supplies an object KEY whose existence must stay hidden
# (D-07); on upload `category` is a form VALUE from a fixed four-item vocabulary
# that this route's own neighbouring error message already spells out, so there
# is nothing to hide. Do not "harmonise" the two codes.
# ===========================================================================


def _no_seam_calls(fake_gcs) -> bool:
    """True when NOTHING reached the ``app.storage.gcs`` seam.

    Byte-identical to ``test_storage_cross_tenant.py:151-152``.
    """
    return all(fake_gcs[k] == [] for k in ("uploads", "signed_urls", "deletes", "downloads"))


def _source_count(engine, set_space, space_id, intake_id) -> int:
    """Count the ``intake_sources`` rows for one intake, re-read as the owner."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.intake_sources WHERE intake_id = :id"),
            {"id": intake_id},
        ).scalar_one()


def test_upload_operator_categories_denied_for_user(engine, set_space, fake_gcs, monkeypatch):
    """A ``role=user`` uploading into ``reports`` / ``artifacts`` -> EXACTLY 422.

    Nothing reaches the storage seam and no ``intake_sources`` row is written.
    ANTI-VACUITY: ``checked == 2`` — the denial set must not be empty.
    """
    from fastapi.testclient import TestClient

    from app.storage.keys import CATEGORIES, CLIENT_WRITABLE_CATEGORIES

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        checked = 0
        for category in sorted(CATEGORIES - CLIENT_WRITABLE_CATEGORIES):
            resp = client.post(
                f"/intakes/{intake_id}/storage/uploads",
                files={"file": ("eindrapport.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"category": category},
                headers=AUTH,
            )
            assert resp.status_code == 422, (
                f"D-23.2-17: a client uploading into the operator-only {category!r} prefix "
                f"must be EXACTLY 422, got {resp.status_code} (body={resp.text!r})."
            )
            assert _no_seam_calls(fake_gcs), (
                f"a denied {category!r} upload must NEVER reach the storage seam, "
                f"got {fake_gcs['uploads']!r}."
            )
            checked += 1

        assert checked == 2, f"exactly two operator-only categories must be denied, saw {checked}."
        assert _source_count(engine, set_space, space, intake_id) == 0, (
            "a denied upload must write NO intake_sources row."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_upload_forbidden_category_refused_before_the_body_read(
    engine, set_space, fake_gcs, monkeypatch
):
    """An OVERSIZED forbidden upload answers 422, NOT 413 — the ordering proof.

    ``read(_MAX_BYTES + 1)`` pulls up to 25 MB off the wire. A role check placed
    after it answers 413 here, which is the observable signature of a server that
    ingested 25 MB from an unauthorized caller before refusing. The check must sit
    in the type-check band, immediately after the existing unknown-category 422 and
    BEFORE any body read.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    oversize = b"x" * (MAX_BYTES + 1)

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("groot-eindrapport.pdf", oversize, "application/pdf")},
            data={"category": "reports"},
            headers=AUTH,
        )

        assert resp.status_code == 422, (
            "an oversized FORBIDDEN upload must be refused on the ROLE (422) before the "
            f"body is ever read — 413 here means the 25 MB was ingested first. Got "
            f"{resp.status_code} (body={resp.text[:200]!r})."
        )
        assert _no_seam_calls(fake_gcs), "the refused body must never reach the storage seam."
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_upload_unknown_category_still_422_for_both_roles(
    engine, set_space, fake_gcs, monkeypatch, superadmin_engine
):
    """The pre-existing unknown-category 422 survives — the new check must not shadow it.

    ``"nonsense"`` is not in CATEGORIES at all, so BOTH roles get 422 and the
    superadmin's answer still carries the ORIGINAL message (a superadmin bypasses
    the role check but not the vocabulary check).
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        client = TestClient(app)

        for label, identity in (("user", _user(space)), ("superadmin", _superadmin())):
            app.dependency_overrides[get_current_identity] = _as(identity)
            resp = client.post(
                f"/intakes/{intake_id}/storage/uploads",
                files={"file": ("verslag.pdf", b"%PDF-1.4 fake", "application/pdf")},
                data={"category": "nonsense"},
                headers=AUTH,
            )
            assert resp.status_code == 422, (
                f"an unknown category must stay EXACTLY 422 for {label}, got "
                f"{resp.status_code} (body={resp.text!r})."
            )
            assert _no_seam_calls(fake_gcs), (
                f"an unknown-category upload must never reach the seam ({label})."
            )

        assert "Unknown storage category" in resp.text, (
            "the superadmin's unknown-category refusal must keep the PRE-EXISTING message — "
            f"the new role check must not shadow it. Got {resp.text!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_superadmin_can_upload_reports(
    engine, set_space, fake_gcs, monkeypatch, superadmin_engine
):
    """A superadmin may still upload every category, including ``reports``.

    This is the live ``FinalReportBlock.tsx:111`` path — D-23.2-17 restricts the
    CLIENT, never the operator.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.post(
            f"/intakes/{intake_id}/storage/uploads",
            files={"file": ("eindrapport.pdf", b"%PDF-1.4 fake", "application/pdf")},
            data={"category": "reports"},
            headers=AUTH,
        )

        assert resp.status_code == 201, (
            f"a superadmin report upload must stay 201, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert len(fake_gcs["uploads"]) == 1, "the report bytes must reach the seam once."
        key = fake_gcs["uploads"][0]["key"]
        assert key.startswith(f"{space}/{intake_id}/reports/"), (
            f"the report must land under the reports prefix, got {key!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
