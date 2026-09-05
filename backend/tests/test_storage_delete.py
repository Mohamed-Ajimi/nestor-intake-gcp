"""Storage delete behavior suite (D-09 / T-09-09) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED until 09-02 lands
``DELETE /intakes/{intake_id}/storage/objects`` (backend/app/api/storage_routes.py).
Do NOT stub the route here — 09-02 turns this file GREEN.

The ``app.storage.gcs`` seam is faked (``fake_gcs``) — no bucket, no network.
What this file pins:

| Test                        | Proves                                              |
|-----------------------------|-----------------------------------------------------|
| ``test_delete_cleans_ref``  | deleting an audio object removes the GCS object     |
|                             | (seam call) AND the matching ``intake_sources`` row |
|                             | in ONE request — no dangling ref, no dangling       |
|                             | object (D-09 / T-09-09).                            |

Extended in phase 23.2 (F-03 / D-23.2-08) with the CATEGORY authorization suite —
see the banner comment above ``_no_seam_calls`` further down this file. The upload
direction of the same hole (D-23.2-17) is pinned in test_storage_upload.py, and both
routes read ONE constant, ``CLIENT_WRITABLE_CATEGORIES`` in app/storage/keys.py.

Harness style clones test_ai_transcribe.py (engine factories patched only,
fabricated Identity override).
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
from app.storage.keys import CATEGORIES  # noqa: E402  (pure module — no DB, no GCS)

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}

# Local testcontainer credential ONLY for the connect-as app_superadmin engine (mirrors
# test_storage_upload.py) — never a production secret.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(storage_routes_mod.storage_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _seed_intake_with_audio_object(engine, set_space, space_id, intake_id, key) -> uuid.UUID:
    """Seed org + intake + one 'audio' intake_sources row pointing at ``key``."""
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Storage delete space"},
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
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_sources "
                "(id, space_id, intake_id, kind, storage_path, file_name, language) "
                "VALUES (:id, :space_id, :intake_id, 'audio', :storage_path, "
                "'gesprek.m4a', 'nl')"
            ),
            {
                "id": source_id,
                "space_id": space_id,
                "intake_id": intake_id,
                "storage_path": key,
            },
        )
    return source_id


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


# ===========================================================================
# Case: delete removes the object AND cleans the intake_sources ref (D-09)
# ===========================================================================


def test_delete_cleans_ref(engine, set_space, fake_gcs, monkeypatch):
    """Deleting an audio key removes the object AND the matching source row.

    ONE request: the (faked) ``delete_object`` receives the exact key, and the
    ``intake_sources`` row whose ``storage_path`` matches is gone when re-read
    as the owner — no dangling DB ref pointing at a deleted object (T-09-09),
    no orphaned object left behind a deleted ref.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/audio/{uuid.uuid4()}-gesprek.m4a"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, key)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [key]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"own-space delete should be 200, got {resp.status_code} (body={resp.text!r})."
        )
        body = resp.json()
        assert body.get("removed", 0) >= 1, (
            f"the response must report at least one removed object, got {body!r}."
        )

        # The object delete reached the seam with the exact key.
        assert fake_gcs["deletes"] == [{"key": key}], (
            f"delete_object must be called once with the exact key, "
            f"got {fake_gcs['deletes']!r}."
        )

        # The matching intake_sources ref is GONE (re-read as the owner).
        with engine.begin() as conn:
            set_space(conn, space)
            remaining = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.intake_sources "
                    "WHERE storage_path = :key"
                ),
                {"key": key},
            ).scalar_one()
        assert remaining == 0, (
            "D-09: the intake_sources row matching the deleted key must be removed "
            f"in the SAME request ({remaining} row(s) left dangling)."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# D-23.2-08 — deletion is authorized by CATEGORY, not by prefix (F-03)
#
# `delete_objects` used to validate only `key.startswith(f"{space}/{intake}/")`.
# Reports are written to `{space}/{intake}/reports/{uuid}-{name}.pdf`
# (intake_routes.py:1468) — INSIDE that prefix — and `GET /intakes/{id}/report`
# deliberately hands the client that exact `storage_path` for the download flow.
# Possession of a path was therefore authorization to destroy the object behind it.
#
# The rule: a non-superadmin may delete ONLY `attachments` and `audio` (the two a
# client can upload — CLIENT_WRITABLE_CATEGORIES). `artifacts` and `reports` are
# operator-produced and deny with an existence-hidden 404, never 403: a 403 here
# tells the caller "that object exists and is not yours" (the D-07 oracle).
# ===========================================================================


def _no_seam_calls(fake_gcs) -> bool:
    """True when NOTHING reached the ``app.storage.gcs`` seam.

    Byte-identical to ``test_storage_cross_tenant.py:151-152`` — a denied delete
    must leave the bucket untouched, not merely report a failure.
    """
    return all(fake_gcs[k] == [] for k in ("uploads", "signed_urls", "deletes", "downloads"))


def _superadmin() -> "Identity":
    """A cross-tenant ``superadmin`` Identity (space_id None — no own space, CR-02)."""
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS ``app_superadmin`` (clone of test_storage_upload.py).

    ``current_user = 'app_superadmin'`` makes the 0003 ``*_superadmin_all`` bypass
    policy match, so the superadmin delete path reaches the row cross-tenant.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'")
        )

    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Patch the superadmin engine factory session.py imported (CR-02 superadmin path)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


def _source_count(engine, set_space, space_id, intake_id) -> int:
    """Count the ``intake_sources`` rows for one intake, re-read as the owner."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.intake_sources WHERE intake_id = :id"),
            {"id": intake_id},
        ).scalar_one()


# ---------------------------------------------------------------------------
# keys.py surface — category_of() + CLIENT_WRITABLE_CATEGORIES
# ---------------------------------------------------------------------------


def test_category_of_parses_the_third_segment():
    """``category_of`` resolves EVERY known category out of the parsed 3rd segment.

    ANTI-VACUITY: ``checked == 4`` — an implementation that always returns ``None``
    cannot pass, and the count also pins ``CATEGORIES`` at four members.
    """
    from app.storage.keys import category_of

    checked = 0
    for category in sorted(CATEGORIES):
        key = f"{uuid.uuid4()}/{uuid.uuid4()}/{category}/{uuid.uuid4()}-bestand.pdf"
        assert category_of(key) == category, (
            f"category_of must parse {category!r} out of {key!r}, got {category_of(key)!r}."
        )
        checked += 1
    assert checked == 4, f"CATEGORIES must still hold exactly four members, saw {checked}."


def test_category_of_never_substring_matches():
    """THE SUBSTRING TRAP: a client attachment may legally be NAMED ``*reports*``.

    ``sanitize_filename`` keeps ``[A-Za-z0-9._-]``, so
    ``{space}/{intake}/attachments/{uuid}-quarterly_reports.pdf`` is an ordinary
    client attachment. A rule written as ``"reports" in key`` answers ``"reports"``
    here and silently breaks the live file-remove flow (FieldRenderer.tsx:488).
    """
    from app.storage.keys import category_of

    key = f"{uuid.uuid4()}/{uuid.uuid4()}/attachments/{uuid.uuid4()}-quarterly_reports.pdf"
    assert category_of(key) == "attachments", (
        "category_of must PARSE the third path segment, never substring-match the key: "
        f"{key!r} -> {category_of(key)!r}."
    )


@pytest.mark.parametrize(
    "key",
    [
        "s/i/nonsense/uuid-x",  # third segment is not a known category
        "s/i/reports",  # only three segments — no filename
        "",  # empty
        "///",  # four empty segments
        "s/i//x",  # empty third segment
        "reports",  # a bare word, not a key
        None,  # not a str at all — must not raise
    ],
)
def test_category_of_returns_none_and_never_raises(key):
    """A key that cannot have been authored by ``build_object_key`` parses to ``None``."""
    from app.storage.keys import category_of

    assert category_of(key) is None, (
        f"category_of({key!r}) must be None, got {category_of(key)!r}."
    )


def test_client_writable_categories_is_the_one_shared_constant():
    """ONE constant in ``keys.py``, imported by BOTH storage routes (D-23.2-17).

    Asserted as object IDENTITY, so the upload rule and the delete rule cannot
    drift apart into two independent literals. The proper-subset assertion stops a
    constant accidentally equal to ``CATEGORIES`` from making every denial test in
    this file vacuously green.
    """
    from app.storage import keys as keys_mod

    writable = keys_mod.CLIENT_WRITABLE_CATEGORIES
    assert isinstance(writable, frozenset), (
        f"CLIENT_WRITABLE_CATEGORIES must be a frozenset, got {type(writable).__name__}."
    )
    assert writable == {"attachments", "audio"}, (
        f"the client-writable set must be exactly the two a client uploads, got {writable!r}."
    )
    assert writable < CATEGORIES, (
        "CLIENT_WRITABLE_CATEGORIES must be a PROPER subset of CATEGORIES — equal sets "
        "would make every category denial vacuously green."
    )
    assert storage_routes_mod.CLIENT_WRITABLE_CATEGORIES is writable, (
        "storage_routes must import the SAME constant object from app.storage.keys — "
        "a private copy in the route module is exactly the drift D-23.2-17 forbids."
    )


# ---------------------------------------------------------------------------
# Route: the operator-only categories deny with an existence-hidden 404
# ---------------------------------------------------------------------------


def test_delete_operator_categories_denied_for_user(engine, set_space, fake_gcs, monkeypatch):
    """A ``role=user`` deleting a ``reports`` / ``artifacts`` key -> EXACTLY 404.

    Nothing reaches the seam and the intake's ``intake_sources`` rows are untouched.
    ANTI-VACUITY: ``checked == 2`` — the denial set must not be empty.
    """
    from fastapi.testclient import TestClient

    from app.storage.keys import CLIENT_WRITABLE_CATEGORIES

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    audio_key = f"{space}/{intake_id}/audio/{uuid.uuid4()}-gesprek.m4a"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, audio_key)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        checked = 0
        for category in sorted(CATEGORIES - CLIENT_WRITABLE_CATEGORIES):
            key = f"{space}/{intake_id}/{category}/{uuid.uuid4()}-eindrapport.pdf"
            resp = client.request(
                "DELETE",
                f"/intakes/{intake_id}/storage/objects",
                json={"paths": [key]},
                headers=AUTH,
            )
            assert resp.status_code == 404, (
                f"D-23.2-08: a client deleting an operator-produced {category!r} key must be "
                f"EXACTLY 404 (existence hidden), got {resp.status_code} (body={resp.text!r})."
            )
            assert _no_seam_calls(fake_gcs), (
                f"a denied {category!r} delete must NEVER reach the storage seam, "
                f"got {fake_gcs['deletes']!r}."
            )
            checked += 1

        assert checked == 2, f"exactly two operator-only categories must be denied, saw {checked}."
        assert _source_count(engine, set_space, space, intake_id) == 1, (
            "a denied delete must remove NO intake_sources row."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_delete_attachment_named_reports_is_allowed(engine, set_space, fake_gcs, monkeypatch):
    """The substring trap at the ROUTE level: ``{uuid}-quarterly_reports.pdf`` -> 200.

    An ordinary client attachment whose FILENAME contains ``reports`` must stay
    deletable; a substring rule breaks the live file-remove flow with no other test
    going red.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/attachments/{uuid.uuid4()}-quarterly_reports.pdf"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, key)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [key]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            "an attachment whose filename merely CONTAINS 'reports' must still be "
            f"deletable, got {resp.status_code} (body={resp.text!r})."
        )
        assert fake_gcs["deletes"] == [{"key": key}], (
            f"the attachment delete must reach the seam once, got {fake_gcs['deletes']!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_delete_mixed_batch_is_all_or_nothing(engine, set_space, fake_gcs, monkeypatch):
    """``[audio_key, reports_key]`` -> EXACTLY 404 and the AUDIO object survives.

    The category check lives in the EXISTING pre-validation loop. Placed in the
    deletion loop instead, this request would destroy the audio object first and
    only then refuse — the partial destruction the pre-loop exists to prevent.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    audio_key = f"{space}/{intake_id}/audio/{uuid.uuid4()}-gesprek.m4a"
    report_key = f"{space}/{intake_id}/reports/{uuid.uuid4()}-eindrapport.pdf"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, audio_key)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [audio_key, report_key]},
            headers=AUTH,
        )

        assert resp.status_code == 404, (
            f"a batch containing ONE forbidden key must be EXACTLY 404, got "
            f"{resp.status_code} (body={resp.text!r})."
        )
        assert _no_seam_calls(fake_gcs), (
            "ALL-OR-NOTHING: the audio object must NOT have been deleted before the "
            f"refusal, got {fake_gcs['deletes']!r}."
        )
        assert _source_count(engine, set_space, space, intake_id) == 1, (
            "the audio intake_sources row must survive a refused batch."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_delete_unparseable_category_denied_for_both_roles(
    engine, set_space, fake_gcs, monkeypatch, superadmin_engine
):
    """A key whose third segment is not a known category -> 404 for EVERY role.

    Such a key cannot have been authored by ``build_object_key``, so it is either
    forged or from a shape the server no longer produces; the safe answer is
    "not found" — including for a superadmin.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    audio_key = f"{space}/{intake_id}/audio/{uuid.uuid4()}-gesprek.m4a"
    forged = f"{space}/{intake_id}/x/y"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, audio_key)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        client = TestClient(app)

        for label, identity in (("user", _user(space)), ("superadmin", _superadmin())):
            app.dependency_overrides[get_current_identity] = _as(identity)
            resp = client.request(
                "DELETE",
                f"/intakes/{intake_id}/storage/objects",
                json={"paths": [forged]},
                headers=AUTH,
            )
            assert resp.status_code == 404, (
                f"an unparseable category must be EXACTLY 404 for {label}, got "
                f"{resp.status_code} (body={resp.text!r})."
            )
            assert _no_seam_calls(fake_gcs), (
                f"an unparseable key must never reach the seam ({label}), "
                f"got {fake_gcs['deletes']!r}."
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


def test_superadmin_can_delete_report_key(
    engine, set_space, fake_gcs, monkeypatch, superadmin_engine
):
    """A superadmin may still delete every category, including ``reports``.

    This is the operator's own deliverable-management path — D-23.2-08 restricts the
    CLIENT, never the operator.
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    report_key = f"{space}/{intake_id}/reports/{uuid.uuid4()}-eindrapport.pdf"

    app = _build_app()
    try:
        _seed_intake_with_audio_object(engine, set_space, space, intake_id, report_key)
        _patch_engine_factories(monkeypatch, engine)
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)

        resp = client.request(
            "DELETE",
            f"/intakes/{intake_id}/storage/objects",
            json={"paths": [report_key]},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"a superadmin must still be able to delete a report, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake_gcs["deletes"] == [{"key": report_key}], (
            f"the report delete must reach the seam once, got {fake_gcs['deletes']!r}."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)
