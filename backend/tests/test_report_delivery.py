"""Human-report delivery contract suite (REPORT-01/02/03 / D-01..D-11) — Plan 18-01.

Drives the REAL ``intake_router`` delivery surface (``POST /intakes/{id}/deliver``,
``POST /intakes/{id}/report/replace``, ``GET /intakes/{id}/report``) over live Postgres
through a FastAPI ``TestClient``, with the mail-egress seam faked (``fake_resend``, conftest).
Same drive-the-real-route + fabricated-Identity + engine-factory-patch scaffold as
``test_intake_cross_tenant.py`` / ``test_mail_endpoints.py``.

What each case pins (``-k`` selectors the RESEARCH Req->Test map names):

| Test (``-k`` selector)         | Proves                                                        |
|--------------------------------|--------------------------------------------------------------|
| ``deliver_transition``         | in_research -> 200 delivered, report artifact linked, mail   |
|                                | reached the seam once (REPORT-01 / D-01).                     |
| ``deliver_wrong_status``       | deliver from any non-in_research status -> 409 (the wall).   |
| ``pdf_only``                   | a non-.pdf storage_path -> 422, status unchanged (D-10).     |
| ``deliver_forged_key``         | a storage_path under another prefix -> 404 (D-08).           |
| ``deliver_mail``               | the send targets the resolved active-member email AND        |
|                                | results_link_sent_at is stamped on the 2xx send (D-03/A3).   |
| ``deliver_mail_failure``       | a send() that RAISES -> still 200 + delivered, but           |
|                                | results_link_sent_at NULL (recoverable, T-18-05).            |
| ``replace``                    | replace on delivered -> new artifact id, status stays        |
|                                | delivered (D-04).                                            |
| ``report_read_delivered``      | GET /report on delivered -> 200 ReportView (filename/size).  |
| ``report_read_pre_delivery``   | GET /report on an own-space in_research intake -> 404        |
|                                | (REPORT-02 invisibility).                                     |

Skip-clean (conftest discipline): ``pytestmark = pytest.mark.integration`` (skips when no
Docker / DATABASE_URL); ``firebase_admin`` and ``app.*`` imports are guarded with
``pytest.importorskip`` so the file COLLECTS on the dev box without erroring.
"""

from __future__ import annotations

import uuid

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

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    """FIXTURE-ONLY (plan 23.1-10) — the operator identity the delivery verbs now require.

    ``POST /deliver`` and ``POST /report/replace`` are superadmin-only via
    ``superadmin_gate`` (23.1-CONTEXT.md § 1 / D-23.1-02): a role=``user`` caller gets an
    existence-hidden 404. The seven cases below drive those verbs, so their CALLER changed
    from a client to an operator. Not one assertion did.
    """
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patch (mirror test_mail_endpoints.py)
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the engine factories ``session.py`` imported AND the ``ai_session`` ones.

    The delivery verbs write through ``app.db.ai_session.tenant_session`` (a committed
    tenant tx for the flip+link+audit), which resolves the engine via its OWN
    ``_engine_and_space`` -> ``get_engine`` import. So BOTH namespaces must be patched:
    ``session_mod.get_engine`` (the ``GET /report`` read dependency routes here) and
    ``ai_session.get_engine`` (the deliver/replace write tx). The user path never touches
    the superadmin engine, so only ``get_engine`` needs swapping for these user-scoped cases.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    ai_session = pytest.importorskip("app.db.ai_session")
    monkeypatch.setattr(ai_session, "get_engine", lambda *a, **k: user_engine)


#: FIXTURE-ONLY (plan 23.1-10). Password granted to app_superadmin for the connect-as engine
#: (test only — the same literal test_mail_endpoints.py uses, so the role's password is stable
#: no matter which suite touches it first).
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """FIXTURE-ONLY (plan 23.1-10) — swap ``get_superadmin_engine`` in BOTH namespaces.

    ``deliver_report`` / ``replace_report`` write through ``ai_session.tenant_session``, which
    resolves the engine via ``ai_session``'s OWN import, while ``get_tenant_repo`` resolves it
    via ``session``'s. A superadmin caller reaches both, so patching one would leave half the
    surface pointed at a real engine.
    """
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    ai_session = pytest.importorskip("app.db.ai_session")
    monkeypatch.setattr(ai_session, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """FIXTURE-ONLY (plan 23.1-10) — an engine connecting AS ``app_superadmin``.

    Copied verbatim from ``test_mail_endpoints.superadmin_engine``. Faithful to production's
    two-engine routing (D-05): ``current_user = 'app_superadmin'`` makes the 0003
    ``*_superadmin_all`` bypass policy match. ``app_superadmin`` is a plain non-superuser
    LOGIN role (conftest's ``_ensure_app_superadmin``), so this proves the bypass POLICY and
    the GRANTs, not superuser ambient authority.
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


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake_status(
    conn,
    set_space,
    space_id: uuid.UUID,
    intake_id: uuid.UUID,
    status: str,
    client_name: str = "Acme",
) -> None:
    """Insert one intake at an EXPLICIT status (GUC set so the 0002 WITH CHECK passes).

    Mirrors ``test_mail_endpoints._insert_intake`` but takes a ``status`` arg so a case can
    seed a ``in_research`` (deliverable) or ``delivered`` (replaceable / readable) intake.
    """
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, :status, :client_name)"
        ),
        {
            "id": intake_id,
            "space_id": space_id,
            "status": status,
            "client_name": client_name,
        },
    )


def _insert_member(conn, space_id: uuid.UUID, email: str, status: str = "active") -> uuid.UUID:
    from sqlalchemy import text

    mid = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organization_memberships "
            "(id, organization_id, provider_user_id, email, role, status) "
            "VALUES (:id, :org, :uid, :email, 'user', :status)"
        ),
        {"id": mid, "org": space_id, "uid": f"pu-{mid}", "email": email, "status": status},
    )
    return mid


def _insert_report_artifact(
    conn,
    set_space,
    space_id: uuid.UUID,
    intake_id: uuid.UUID,
    storage_path: str,
    filename: str = "report.pdf",
    byte_size: int = 12345,
) -> uuid.UUID:
    """Insert a report ``research_artifacts`` row under the OWNING space GUC; return its id.

    Mirrors ``test_intake_cross_tenant._insert_answer``'s GUC-then-INSERT shape so the 0002
    RLS WITH CHECK on ``research_artifacts`` admits the row. Used to pre-seed a delivered
    intake's linked report for the report-read and replace cases.
    """
    from sqlalchemy import text

    set_space(conn, space_id)
    aid = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.research_artifacts "
            "(id, space_id, intake_id, source, artifact_type, filename, storage_path, "
            " byte_size, mime_type) "
            "VALUES (:id, :space_id, :intake_id, 'human-report', 'report', :filename, "
            " :storage_path, :byte_size, 'application/pdf')"
        ),
        {
            "id": aid,
            "space_id": space_id,
            "intake_id": intake_id,
            "filename": filename,
            "storage_path": storage_path,
            "byte_size": byte_size,
        },
    )
    return aid


def _link_report(conn, set_space, space_id, intake_id, artifact_id, results_sent: bool) -> None:
    """Point ``intakes.final_report_artifact_id`` at ``artifact_id`` (owner GUC set).

    When ``results_sent`` is True also stamp ``results_link_sent_at`` (the delivered mail
    timestamp the phase machine reads as ``completed``) so ``ReportView.delivered_at`` is
    populated for the report-read case.
    """
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"UPDATE {SCHEMA}.intakes SET final_report_artifact_id = :aid"
            + (", results_link_sent_at = now()" if results_sent else "")
            + " WHERE id = :id"
        ),
        {"aid": artifact_id, "id": intake_id},
    )


def _read_intake(engine, set_space, space_id, intake_id):
    """Return (status, final_report_artifact_id, results_link_sent_at) read as the owner."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                f"SELECT status, final_report_artifact_id, results_link_sent_at "
                f"FROM {SCHEMA}.intakes WHERE id = :id"
            ),
            {"id": intake_id},
        ).first()
    return (row[0], row[1], row[2]) if row is not None else (None, None, None)


def _build_app():
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


def _key(space_id, intake_id, name="report.pdf") -> str:
    """A well-formed staged report key under the intake's own reports/ prefix."""
    return f"{space_id}/{intake_id}/reports/{uuid.uuid4()}-{name}"


# ===========================================================================
# deliver_transition — in_research -> 200 delivered + artifact linked + mail sent
# ===========================================================================


def test_deliver_transition_links_artifact_and_flips_status(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """POST /deliver on an in_research intake -> 200 delivered, artifact linked, mail sent once."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Deliver Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")
            member = _insert_member(conn, space_a, "client@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")  # WR-01
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={"storage_path": _key(space_a, intake_a), "recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"deliver should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["status"] == "delivered", "the intake must be delivered after /deliver"
        assert body["final_report_artifact_id"] is not None, (
            "delivery must link a report artifact (final_report_artifact_id set)"
        )
        status_db, art_id, _ = _read_intake(engine, set_space, space_a, intake_a)
        assert status_db == "delivered", "the DB row must be delivered"
        assert art_id is not None, "the DB row must carry the linked report artifact id"
        assert len(fake_resend["calls"]) == 1, "the delivery mail must reach the seam once"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# deliver_wrong_status — deliver from a non-in_research status -> 409
# ===========================================================================


def test_deliver_wrong_status_returns_409(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """POST /deliver on a decomposed intake -> 409 (the in_research-only transition wall)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Deliver Wrong Status Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "decomposed")
            member = _insert_member(conn, space_a, "client@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={"storage_path": _key(space_a, intake_a), "recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 409, (
            f"deliver from a non-in_research status must be 409, got {resp.status_code}"
        )
        status_db, art_id, _ = _read_intake(engine, set_space, space_a, intake_a)
        assert status_db == "decomposed", "a 409 deliver must NOT change the status"
        assert art_id is None, "a 409 deliver must NOT link an artifact"
        assert fake_resend["calls"] == [], "a 409 deliver must NOT send mail"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# pdf_only — a non-.pdf storage_path -> 422 (D-10), status unchanged
# ===========================================================================


def test_pdf_only_rejects_non_pdf(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """POST /deliver with a .docx storage_path -> 422 (server-side PDF-only, D-10)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "PDF Only Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")
            member = _insert_member(conn, space_a, "client@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={
                "storage_path": _key(space_a, intake_a, "report.docx"),
                "recipients": [str(member)],
            },
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 422, (
            f"a non-.pdf report must be 422 (D-10), got {resp.status_code} ({resp.text!r})"
        )
        status_db, art_id, _ = _read_intake(engine, set_space, space_a, intake_a)
        assert status_db == "in_research", "a 422 deliver must NOT change the status"
        assert art_id is None, "a 422 deliver must NOT link an artifact"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# deliver_forged_key — a cross-prefix storage_path -> 404 (D-08)
# ===========================================================================


def test_deliver_forged_key_returns_404(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """POST /deliver with a storage_path under ANOTHER space/intake prefix -> 404 (D-08)."""
    from fastapi.testclient import TestClient

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Forged Key Space A")
            _create_space(conn, space_b, "Forged Key Space B")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")
            member = _insert_member(conn, space_a, "client@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        # A key under space_b/intake_b — not the owned intake's reports/ prefix.
        forged = _key(space_b, intake_b)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={"storage_path": forged, "recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 404, (
            f"a forged / cross-prefix report key must be 404 (D-08), got {resp.status_code}"
        )
        status_db, art_id, _ = _read_intake(engine, set_space, space_a, intake_a)
        assert status_db == "in_research", "a forged-key deliver must NOT change the status"
        assert art_id is None, "a forged-key deliver must NOT link an artifact"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a, space_b)


# ===========================================================================
# deliver_mail — the send targets the resolved email + stamps results_link_sent_at
# ===========================================================================


def test_deliver_mail_targets_resolved_email_and_stamps(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """A successful deliver sends to the resolved active-member email and stamps the sent-at."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Deliver Mail Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")
            member = _insert_member(conn, space_a, "resolved@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={"storage_path": _key(space_a, intake_a), "recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"deliver should be 200, got {resp.status_code}"
        # The send targeted ONLY the resolved active-member email (D-06 no-free-address).
        assert fake_resend["calls"][0]["to"] == ["resolved@x.com"], (
            "the delivery mail must target the resolved active-member email"
        )
        # The CTA deep-links to the client REPORT page, not /results.
        assert "/report" in fake_resend["calls"][0]["html"], (
            "the delivery mail CTA must deep-link to the /report client page (D-07)"
        )
        _, _, res_ts = _read_intake(engine, set_space, space_a, intake_a)
        assert res_ts is not None, (
            "a successful delivery send must stamp results_link_sent_at (A3)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# deliver_mail_failure — a raised send -> still 200 delivered, results_link_sent_at NULL
# ===========================================================================


def test_deliver_mail_failure_leaves_delivered_timestamp_null(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """A send() that RAISES leaves the intake delivered but results_link_sent_at NULL (T-18-05)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Deliver Mail Failure Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")
            member = _insert_member(conn, space_a, "client@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        # Force the delivery mail to raise (simulates a Resend transport failure).
        import app.mail.resend as resend_mod

        def _raise(*, to, subject, html):  # noqa: ANN001
            raise RuntimeError("resend 500 during delivery")

        monkeypatch.setattr(resend_mod, "send", _raise)

        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/deliver",
            json={"storage_path": _key(space_a, intake_a), "recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, (
            f"a failed delivery mail must still return 200 (delivered), got {resp.status_code}"
        )
        assert resp.json()["status"] == "delivered", (
            "T-18-05: a mail failure must still leave the intake delivered (recoverable)"
        )
        status_db, art_id, res_ts = _read_intake(engine, set_space, space_a, intake_a)
        assert status_db == "delivered", "the delivery (flip+link) must be committed"
        assert art_id is not None, "the report artifact must be linked even on a mail failure"
        assert res_ts is None, (
            "T-18-05: a failed send must NOT stamp results_link_sent_at (recoverable state)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# replace — replace on delivered -> new artifact id, status stays delivered
# ===========================================================================


def test_replace_repoints_artifact_keeps_delivered(
    engine, set_space, two_spaces, monkeypatch, fake_resend
, superadmin_engine):
    """POST /report/replace on a delivered intake -> new artifact id, status STILL delivered."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Replace Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "delivered")
            old_art = _insert_report_artifact(
                conn, set_space, space_a, intake_a, _key(space_a, intake_a, "old.pdf")
            )
            _link_report(conn, set_space, space_a, intake_a, old_art, results_sent=True)

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # FIXTURE-ONLY (plan 23.1-10): the verb this test drives is now superadmin-only
        # (D-23.1-02); only the IDENTITY changed, every assertion below is untouched.
        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app.dependency_overrides[get_current_identity] = _as(_superadmin())
        client = TestClient(app)
        # Silent replace (no recipients) — the default path (D-05).
        resp = client.post(
            f"/intakes/{intake_a}/report/replace",
            json={"storage_path": _key(space_a, intake_a, "new.pdf"), "recipients": []},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"replace should be 200, got {resp.status_code} ({resp.text!r})"
        body = resp.json()
        assert body["status"] == "delivered", "replace must NOT change the status"
        assert body["final_report_artifact_id"] != str(old_art), (
            "replace must repoint final_report_artifact_id to a NEW artifact row"
        )
        assert fake_resend["calls"] == [], "a silent replace (no recipients) must NOT send mail"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# report_read_delivered — GET /report on delivered -> 200 ReportView
# ===========================================================================


def test_report_read_delivered_returns_metadata(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """GET /report on a delivered intake -> 200 with the linked artifact's filename/size."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Report Read Space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_a, intake_a, "delivered")
            art = _insert_report_artifact(
                conn,
                set_space,
                space_a,
                intake_a,
                _key(space_a, intake_a, "final.pdf"),
                filename="final.pdf",
                byte_size=98765,
            )
            _link_report(conn, set_space, space_a, intake_a, art, results_sent=True)

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_a}/report",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"report read should be 200, got {resp.status_code}"
        body = resp.json()
        assert body["filename"] == "final.pdf", "the ReportView must carry the artifact filename"
        assert body["byte_size"] == 98765, "the ReportView must carry the artifact byte_size"
        assert body["mime_type"] == "application/pdf", "the ReportView must carry the mime_type"
        assert body["delivered_at"] is not None, (
            "delivered_at must mirror results_link_sent_at (stamped on the seed)"
        )
        assert body["storage_path"], "the ReportView must carry the storage_path for download"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# report_read_pre_delivery — GET /report on an own-space in_research intake -> 404
# ===========================================================================


def test_report_read_pre_delivery_returns_404(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """GET /report on an OWN-space non-delivered intake -> 404 (REPORT-02 invisibility)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Pre Delivery Space")
        with engine.begin() as conn:
            # in_research is a HIGHER lifecycle stage than delivered's predecessors, yet the
            # report is STILL invisible — the gate is exact equality on 'delivered', not >=.
            _insert_intake_status(conn, set_space, space_a, intake_a, "in_research")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_a}/report",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 404, (
            "REPORT-02: GET /report on a non-delivered own-space intake must be EXACTLY 404, "
            f"got {resp.status_code} ({resp.text!r})."
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)
