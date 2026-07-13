"""Signed-URL behavior suite (DOC-01 / D-10 / T-09-03 / T-09-04) — Wave-0 RED scaffold.

Authored in 09-01 against the FINAL 09-02 contract; RED until 09-02 lands
``GET /intakes/{intake_id}/storage/signed-url`` (backend/app/api/storage_routes.py).
Do NOT stub the route here — 09-02 turns this file GREEN.

The ``app.storage.gcs`` seam is faked (``fake_gcs``) — no bucket, no signBlob.
What this file pins:

| Test                                 | Proves                                          |
|--------------------------------------|-------------------------------------------------|
| ``test_ttl_clamped_and_disposition`` | ``expires_in=99999`` -> the advertised lifetime |
|                                      | is clamped to <= 900s (D-10) and the signer is  |
|                                      | invoked with the exact key + a filename whose   |
|                                      | disposition is ``attachment`` (T-09-04 — never  |
|                                      | inline render).                                 |
| ``test_seam_clamps_ttl_to_900``      | the REAL seam's clamp arithmetic: any request   |
|                                      | lands in [1, 900] (pure unit test of            |
|                                      | ``app.storage.gcs._clamp_ttl``, T-09-03).       |

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

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
AUTH = {"Authorization": "Bearer ignored-overridden"}

# D-10: the server-side signed-URL lifetime ceiling.
MAX_TTL_S = 900


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


def _seed_space_and_intake(engine, set_space, space_id, intake_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Storage signed-url space"},
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
# Case: TTL clamp + attachment disposition (DOC-01 / D-10 / T-09-04)
# ===========================================================================


def test_ttl_clamped_and_disposition(engine, set_space, fake_gcs, monkeypatch):
    """``expires_in=99999`` -> advertised lifetime <= 900; disposition=attachment.

    The route resolves ownership (404 gate), asserts the key prefix, then calls
    the (faked) signer. The response's ``expires_in`` is the EFFECTIVE lifetime
    the client may rely on — it must never exceed the D-10 ceiling regardless
    of what was requested. The recorded signer call carries the exact key and
    a filename whose Content-Disposition is ``attachment`` (T-09-04).
    """
    from fastapi.testclient import TestClient

    space, intake_id = uuid.uuid4(), uuid.uuid4()
    key = f"{space}/{intake_id}/attachments/{uuid.uuid4()}-verslag.pdf"

    app = _build_app()
    try:
        _seed_space_and_intake(engine, set_space, space, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space))
        client = TestClient(app)

        resp = client.get(
            f"/intakes/{intake_id}/storage/signed-url",
            params={"path": key, "expires_in": 99999},
            headers=AUTH,
        )

        assert resp.status_code == 200, (
            f"own-space signed-url should be 200, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        body = resp.json()
        assert body.get("url") == f"https://signed.example/{key}", (
            f"the faked signer's URL must be returned verbatim, got {body.get('url')!r}."
        )
        assert int(body.get("expires_in", 10**9)) <= MAX_TTL_S, (
            f"D-10: advertised expires_in must be clamped to <= {MAX_TTL_S}, "
            f"got {body.get('expires_in')!r} for a 99999s request."
        )

        assert len(fake_gcs["signed_urls"]) == 1, "the signer seam must be called exactly once."
        recorded = fake_gcs["signed_urls"][0]
        assert recorded["key"] == key, (
            f"the signer must receive the exact requested key: {recorded['key']!r}."
        )
        assert recorded["filename"], "a download filename must be passed to the signer."
        # WR-07: the forced-download (attachment) invariant is NOT asserted here — the
        # fake no longer fabricates a `disposition`, so a route-level test cannot claim to
        # verify what the seam emits. That invariant is pinned against the REAL seam in
        # test_seam_forces_attachment_disposition below.
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space)


# ===========================================================================
# Case: the REAL seam clamp (pure arithmetic — no bucket, no signBlob)
# ===========================================================================


def test_seam_clamps_ttl_to_900():
    """``app.storage.gcs._clamp_ttl`` lands every request in [1, 900] (T-09-03).

    Unit-level proof of the D-10 ceiling INSIDE the real seam (independent of
    where the route layer clamps): a huge, zero, or negative request can never
    widen the exposure window.
    """
    gcs_mod = pytest.importorskip("app.storage.gcs")

    assert gcs_mod._MAX_TTL_S == MAX_TTL_S, "the seam ceiling must be 900s (D-10)."
    assert gcs_mod._clamp_ttl(99999) == MAX_TTL_S, "an over-ask clamps to the ceiling."
    assert gcs_mod._clamp_ttl(MAX_TTL_S) == MAX_TTL_S, "the ceiling itself is allowed."
    assert gcs_mod._clamp_ttl(300) == 300, "an in-range request passes through."
    assert gcs_mod._clamp_ttl(0) == 1, "zero clamps up to the 1s floor."
    assert gcs_mod._clamp_ttl(-5) == 1, "a negative request clamps up to the 1s floor."


# ===========================================================================
# Case: the REAL seam forces attachment disposition (WR-07 — no fabricated fake value)
# ===========================================================================


def test_seam_forces_attachment_disposition(monkeypatch):
    """``gcs.signed_download_url`` passes ``response_disposition='attachment; ...'`` (T-09-04).

    WR-07: patch ONLY the auth + storage.Client SDK boundary (not the seam function) and
    capture the kwargs the seam hands to ``Blob.generate_signed_url``. This pins the
    forced-download invariant against the REAL seam — if someone flips the disposition to
    ``inline`` the assertion fails, unlike the old fixture-fabricated check. It also proves
    the WR-01 filename sanitization reaches the header (a hostile tail cannot inject).
    """
    gcs_mod = pytest.importorskip("app.storage.gcs")
    # get_settings() reads the environment fresh per call (not cached), so the seam picks
    # up this bucket name at call time via _bucket().
    monkeypatch.setenv("STORAGE_BUCKET", "unit-test-bucket")

    recorded: dict = {}

    class _FakeBlob:
        def generate_signed_url(self, **kwargs):
            recorded.update(kwargs)
            return "https://signed.example/unit"

    class _FakeBucket:
        def blob(self, key):
            recorded["key"] = key
            return _FakeBlob()

    class _FakeStorageClient:
        def bucket(self, name):
            recorded["bucket"] = name
            return _FakeBucket()

    class _FakeCreds:
        service_account_email = "sa@example.iam.gserviceaccount.com"
        token = "fake-access-token"

        def refresh(self, _request):
            recorded["refreshed"] = True

    monkeypatch.setattr(gcs_mod.storage, "Client", lambda *a, **k: _FakeStorageClient())
    monkeypatch.setattr(gcs_mod.google.auth, "default", lambda *a, **k: (_FakeCreds(), "proj"))
    monkeypatch.setattr(
        gcs_mod.google.auth.transport.requests, "Request", lambda *a, **k: object()
    )

    url = gcs_mod.signed_download_url(
        "space/intake/audio/uuid-clean.m4a",
        ttl_seconds=300,
        # A hostile tail: quotes + semicolon would break out of the header if unsanitized.
        filename='evil".m4a; x=y',
        content_type=None,
    )

    assert url == "https://signed.example/unit"
    disposition = recorded.get("response_disposition", "")
    assert disposition.startswith("attachment; filename="), (
        f"T-09-04: the real seam must force download (attachment), got {disposition!r}."
    )
    # WR-01: the sanitizer strips the quote/semicolon so no header injection survives.
    assert '"' not in disposition[len("attachment; filename=") :].strip('"'), (
        f"the disposition filename must be sanitized (no raw quotes), got {disposition!r}."
    )
    assert ";" not in disposition.split("filename=", 1)[1], (
        f"a hostile ';' tail must not survive into the header, got {disposition!r}."
    )
    assert recorded.get("method") == "GET", "signed URL must be a GET (download only)."
