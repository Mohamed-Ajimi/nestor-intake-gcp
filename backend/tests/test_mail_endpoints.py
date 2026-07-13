"""Mail send/read contract suite (NOTIF-01/02 / D-06 / D-16 / T-10-07/13) — Plan 10-03.

Drives the REAL ``intake_router`` mail surface (members read + three send endpoints) AND the
REAL ``admin_router`` invite-mail endpoint over live Postgres through a FastAPI ``TestClient``,
with the mail-egress seam faked (``fake_resend``, conftest). Same drive-the-real-route +
fabricated-Identity + engine-factory-patch scaffold as ``test_intake_cross_tenant.py`` /
``test_admin_routes.py``.

What each case pins:

| Test                              | Proves                                                         |
|-----------------------------------|---------------------------------------------------------------|
| ``members_read_active_only``      | GET /intakes/{id}/members returns the space's ACTIVE {id,email}|
|                                   | rows and EXCLUDES a deactivated member (T-10-13).             |
| ``timestamp_on_success_only``     | a successful validation send stamps validation_link_sent_at;  |
|                                   | a send() that RAISES leaves the column NULL and writes no     |
|                                   | mail.sent audit row (D-16 / Pitfall 1).                       |
| ``reminder_writes_no_timestamp``  | a reminder send does NOT stamp any column (legacy parity).    |
| ``results_stamps_results_sent_at``| a results send stamps results_link_sent_at on success.        |
| ``no_free_address``               | a body carrying an extra ``to``/``email`` field is rejected — |
|                                   | recipients come ONLY from resolved active memberships (D-06). |
| ``deactivated_recipient_rejected``| a deactivated member's id is NOT emailable (422; T-10-13).    |
| ``invite`` / ``action_code``      | invite-mail sends a fresh-link invite + no link in the audit; |
|                                   | generate_set_password_link pins the /auth/action continue URL.|

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker); ``importorskip``
guards so the file COLLECTS on the dev box.
"""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
admin_routes = pytest.importorskip("app.api.admin_routes")
admin_users = pytest.importorskip("app.auth.admin_users")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
admin_router = admin_routes.admin_router
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"

_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only


# ---------------------------------------------------------------------------
# Identity fabrication
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches (mirror the two prior suites)
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE)."""
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


def _insert_intake(
    conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID, client_name: str = "Acme"
) -> None:
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, 'draft', :client_name)"
        ),
        {"id": intake_id, "space_id": space_id, "client_name": client_name},
    )


def _insert_member(
    conn, space_id: uuid.UUID, email: str, status: str = "active"
) -> uuid.UUID:
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


def _build_intake_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _build_admin_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(admin_router)
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


def _read_intake_timestamps(engine, set_space, space_id, intake_id):
    """Return (validation_link_sent_at, results_link_sent_at) read as the owner (GUC set)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                f"SELECT validation_link_sent_at, results_link_sent_at "
                f"FROM {SCHEMA}.intakes WHERE id = :id"
            ),
            {"id": intake_id},
        ).first()
    return (row[0], row[1]) if row is not None else (None, None)


def _count_mail_sent_audit(engine, space_id):
    from sqlalchemy import func, select, text

    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        return conn.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.event_type == "mail.sent")
        ).scalar_one()


# ===========================================================================
# members_read_active_only — active {id,email} rows; deactivated excluded
# ===========================================================================


def test_members_read_active_only(engine, set_space, two_spaces, monkeypatch, fake_resend):
    """GET /intakes/{id}/members returns ACTIVE {id, email} rows and EXCLUDES a deactivated one."""
    from fastapi.testclient import TestClient

    space_a, _space_b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Members Read Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            active_id = _insert_member(conn, space_a, "active@x.com", status="active")
            _insert_member(conn, space_a, "gone@x.com", status="deactivated")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_a}/members",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"members read should be 200, got {resp.status_code}"
        rows = resp.json()
        emails = {r["email"] for r in rows}
        ids = {r["id"] for r in rows}
        assert "active@x.com" in emails, "the active member must appear in the read"
        assert str(active_id) in ids, "the read must carry the active member's id"
        assert "gone@x.com" not in emails, (
            "T-10-13: a deactivated member must be EXCLUDED from the members read"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# timestamp_on_success_only — stamp on success; none on a raised send (D-16)
# ===========================================================================


def test_timestamp_on_success_only(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A successful validation send stamps validation_link_sent_at; a raised send leaves it NULL.

    Success path: ``fake_resend`` captures the send, the handler stamps
    ``validation_link_sent_at`` and writes ONE ``mail.sent`` audit row. Failure path: a
    ``resend.send`` monkeypatched to RAISE leaves the column NULL and writes NO mail.sent audit
    row (D-16 / Pitfall 1 — send THEN stamp, never before).
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_ok, intake_fail = uuid.uuid4(), uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Timestamp Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_ok)
            _insert_intake(conn, set_space, space_a, intake_fail)
            member_ok = _insert_member(conn, space_a, "ok@x.com")
            member_fail = _insert_member(conn, space_a, "fail@x.com")

        # WR-01: APP_BASE_URL must be set or _run_intake_send refuses (success=False).
        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)

        # --- success path: stamp written, one mail.sent audit ---
        ok = client.post(
            f"/intakes/{intake_ok}/mail/validation",
            json={"recipients": [str(member_ok)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert ok.status_code == 200, f"validation send should be 200, got {ok.status_code}"
        assert ok.json()["success"] is True
        val_ts, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_ok)
        assert val_ts is not None, "successful validation send must stamp validation_link_sent_at"
        assert res_ts is None, "validation send must not touch results_link_sent_at"
        assert len(fake_resend["calls"]) == 1, "the success send must reach the mail seam once"
        assert _count_mail_sent_audit(engine, space_a) == 1, (
            "a successful send must write exactly one mail.sent audit row"
        )

        # --- failure path: send() raises -> NO stamp, NO new audit row ---
        import app.mail.resend as resend_mod

        def _raise(*, to, subject, html):  # noqa: ANN001
            raise RuntimeError("resend 500")

        monkeypatch.setattr(resend_mod, "send", _raise)
        fail = client.post(
            f"/intakes/{intake_fail}/mail/validation",
            json={"recipients": [str(member_fail)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert fail.status_code == 200, "a failed send returns a 200 JSON body (success=False)"
        assert fail.json()["success"] is False, "a raised send must report success=False"
        fail_val_ts, _ = _read_intake_timestamps(engine, set_space, space_a, intake_fail)
        assert fail_val_ts is None, (
            "D-16 VIOLATION: validation_link_sent_at was stamped despite a failed send"
        )
        assert _count_mail_sent_audit(engine, space_a) == 1, (
            "a failed send must NOT write a mail.sent audit row (still only the success one)"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# unset_app_base_url_refuses_send — no APP_BASE_URL -> refuse, no stamp (WR-01)
# ===========================================================================


def test_unset_app_base_url_refuses_send(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """With APP_BASE_URL unset, a client-facing send is REFUSED (200 + success=False) — WR-01.

    A relative `/intake/{id}` CTA is a dead link in every mail client and the logo renders
    `None/agenic-logo.png`. The guard refuses BEFORE the send (like _send_admin_validated
    refuses on an unset NESTOR_ADMIN_EMAIL): no mail reaches the seam, no sent-at is stamped,
    and no mail.sent audit row is written.
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "No Base URL Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "b@x.com")

        # Explicitly ensure APP_BASE_URL is UNSET for this case.
        monkeypatch.delenv("APP_BASE_URL", raising=False)
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/validation",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, "an unset-base-url refusal returns a 200 JSON body"
        assert resp.json()["success"] is False, (
            "WR-01: with APP_BASE_URL unset the send must be refused (success=False)"
        )
        assert fake_resend["calls"] == [], (
            "WR-01: no mail may reach the seam when APP_BASE_URL is unset"
        )
        val_ts, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_a)
        assert val_ts is None and res_ts is None, (
            "WR-01: a refused send must NOT stamp any sent-at column"
        )
        assert _count_mail_sent_audit(engine, space_a) == 0, (
            "WR-01: a refused send must NOT write a mail.sent audit row"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# members_read_excludes_null_email — email-less active member filtered (WR-02)
# ===========================================================================


def test_members_read_excludes_null_email(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """GET /intakes/{id}/members EXCLUDES an ACTIVE member whose email is NULL (WR-02).

    An email-less active membership can never be a recipient (the send resolver would 422 the
    whole batch), and the RecipientPicker preselects every returned row — so an unfilterable
    NULL-email row would make the one-click default send fail with an opaque 422 and render a
    blank checkbox. Filtering it out of the read keeps the picker clean and sendable.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Null Email Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            has_email = _insert_member(conn, space_a, "has@x.com", status="active")
            # An ACTIVE membership with a NULL email (email column is nullable).
            no_email = uuid.uuid4()
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, :uid, NULL, 'user', 'active')"
                ),
                {"id": no_email, "org": space_a, "uid": f"pu-{no_email}"},
            )

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.get(
            f"/intakes/{intake_a}/members",
            headers={"Authorization": "Bearer ignored-overridden"},
        )

        assert resp.status_code == 200, f"members read should be 200, got {resp.status_code}"
        ids = {r["id"] for r in resp.json()}
        assert str(has_email) in ids, "an active member WITH an email must appear"
        assert str(no_email) not in ids, (
            "WR-02: an active member with a NULL email must be EXCLUDED from the read"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# reminder_writes_no_timestamp — reminder send stamps nothing (legacy parity)
# ===========================================================================


def test_reminder_writes_no_timestamp(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A reminder send succeeds but stamps NO column (no reminder-sent column — legacy parity)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Reminder Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "rem@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")  # WR-01
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/reminder",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 200, f"reminder send should be 200, got {resp.status_code}"
        val_ts, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_a)
        assert val_ts is None and res_ts is None, (
            "a reminder send must NOT stamp any sent-at column (legacy parity)"
        )
        assert len(fake_resend["calls"]) == 1, "the reminder must still reach the mail seam"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# results_stamps_results_sent_at — results send stamps results_link_sent_at
# ===========================================================================


def test_results_stamps_results_sent_at(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A results send stamps results_link_sent_at (and not validation_link_sent_at) on success."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Results Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "res@x.com")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")  # WR-01
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 200, f"results send should be 200, got {resp.status_code}"
        val_ts, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_a)
        assert res_ts is not None, "successful results send must stamp results_link_sent_at"
        assert val_ts is None, "results send must not touch validation_link_sent_at"
        # The rendered body carried the resolved active-member email (no free address).
        assert fake_resend["calls"][0]["to"] == ["res@x.com"], (
            "the send must target ONLY the resolved active-member email"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# no_free_address — a body-supplied to/email is not honored (D-06)
# ===========================================================================


def test_no_free_address(engine, set_space, two_spaces, monkeypatch, fake_resend):
    """A body carrying an extra ``to``/``email`` field is REJECTED (422) — no free address (D-06).

    ``MailRecipients`` forbids extra fields, so a smuggled recipient address is a 422 and never
    reaches the send seam. Recipients come ONLY from resolved active memberships.
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "No Free Address Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "legit@x.com")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/validation",
            json={
                "recipients": [str(member)],
                "to": "attacker@evil.com",
                "email": "attacker@evil.com",
            },
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        # extra="forbid" -> 422; the smuggled address never reaches the seam.
        assert resp.status_code == 422, (
            f"a body-supplied to/email must be rejected (422), got {resp.status_code} "
            f"({resp.text!r}) — D-06 no-free-address."
        )
        assert fake_resend["calls"] == [], (
            "D-06 LEAK: a request with a free-text address reached the mail seam"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# deactivated_recipient_rejected — a deactivated member id is not emailable
# ===========================================================================


def test_deactivated_recipient_rejected(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A deactivated member's id is NOT emailable — the send is 422 and NO mail is sent (T-10-13).

    The recipient resolver only matches ACTIVE memberships, so a deactivated id is rejected
    rather than silently dropped-and-sent-to-fewer (an empty resolved set is never sent).
    """
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Deactivated Recipient Space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            gone = _insert_member(conn, space_a, "gone@x.com", status="deactivated")

        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/validation",
            json={"recipients": [str(gone)]},
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 422, (
            f"a deactivated recipient id must be rejected (422), got {resp.status_code} "
            f"({resp.text!r})."
        )
        assert fake_resend["calls"] == [], (
            "T-10-13: a deactivated member must never be emailed"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# ===========================================================================
# invite — invite-mail sends a fresh-link invite; NO link in the audit metadata
# ===========================================================================


def test_invite_mail_sends_and_audits_without_link(
    engine, monkeypatch, superadmin_engine, fake_resend
):
    """POST /admin/users/{id}/invite-mail sends the invite mail and audits mail.sent — no link.

    The membership is looked up; ``generate_set_password_link`` is faked to a benign action
    link; the invite body is rendered and sent via ``fake_resend`` (carrying the link in the
    HTML). A ``mail.sent`` audit row lands with metadata that NEVER contains the action link.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    action_link = "https://idp/action?oobCode=INVITECODE"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Invite Mail Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'invitee-uid', 'invitee@x.com', 'user', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_admin_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with patch.object(
            admin_users, "generate_set_password_link", MagicMock(return_value=action_link)
        ):
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/invite-mail",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"invite-mail should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["success"] is True
        # The response body must NOT carry the action link (it is sent, not returned).
        assert action_link not in resp.text, "invite-mail response must not carry the link"
        # The mail was sent to the member's email and carries the link in the HTML body.
        assert len(fake_resend["calls"]) == 1, "invite-mail must reach the mail seam once"
        assert fake_resend["calls"][0]["to"] == ["invitee@x.com"]
        assert action_link in fake_resend["calls"][0]["html"], (
            "the invite mail body (D-09 — the only link-carrying mail) must contain the link"
        )

        # The mail.sent audit row's metadata must NEVER contain the action link (T-5-16 / T-10-08).
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_space_id', :sid, true)"),
                {"sid": str(space_id)},
            )
            rows = conn.execute(
                text(
                    f"SELECT metadata::text FROM {SCHEMA}.audit_log "
                    "WHERE event_type = 'mail.sent'"
                )
            ).all()
        assert rows, "invite-mail must write a mail.sent audit row"
        for (meta_text,) in rows:
            assert action_link not in meta_text, (
                "T-10-08: the invite-mail audit metadata must NEVER contain the action link"
            )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


def test_invite_mail_no_email_returns_409(
    engine, monkeypatch, superadmin_engine, fake_resend
):
    """A membership with NO email -> 409 (never send to None); no mail is sent."""
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "No Email Invite Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'no-email-uid', NULL, 'user', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)
        app = _build_admin_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        client = TestClient(app)
        resp = client.post(
            f"/admin/users/{membership_id}/invite-mail",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code == 409, (
            f"a member with no email must be 409, got {resp.status_code} ({resp.text!r})"
        )
        assert fake_resend["calls"] == [], "no mail may be sent when the member has no email"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


# ===========================================================================
# invite_mail_send_failure — transport failure -> 200 + success:false, no audit (WR-04)
# ===========================================================================


def test_invite_mail_send_failure_returns_success_false(
    engine, monkeypatch, superadmin_engine, fake_resend
):
    """A raised invite-mail send returns 200 + success=False and writes NO audit row (WR-04).

    Mirrors _run_intake_send's contract: a Resend transport failure (or missing
    RESEND_API_KEY) is caught and surfaced as HTTP 200 + {success: false} — NOT a raw 500 —
    and the mail.sent audit row is written only on success (audit-on-success-only).
    """
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    action_link = "https://idp/action?oobCode=FAILCODE"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Invite Fail Space")
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organization_memberships "
                    "(id, organization_id, provider_user_id, email, role, status) "
                    "VALUES (:id, :org, 'fail-uid', 'fail-invitee@x.com', 'user', 'active')"
                ),
                {"id": membership_id, "org": space_id},
            )

        _patch_superadmin_engine(monkeypatch, superadmin_engine)

        # Force the invite send to raise (simulates Resend non-2xx / missing key).
        import app.mail.resend as resend_mod

        def _raise(*, to, subject, html):  # noqa: ANN001
            raise RuntimeError("resend 500 during invite")

        monkeypatch.setattr(resend_mod, "send", _raise)

        app = _build_admin_app()
        app.dependency_overrides[get_current_identity] = _as(_superadmin())

        with patch.object(
            admin_users, "generate_set_password_link", MagicMock(return_value=action_link)
        ):
            client = TestClient(app)
            resp = client.post(
                f"/admin/users/{membership_id}/invite-mail",
                headers={"Authorization": "Bearer ignored-overridden"},
            )

        assert resp.status_code == 200, (
            f"WR-04: a failed invite send returns a 200 JSON body, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert resp.json()["success"] is False, (
            "WR-04: a raised invite send must report success=False (not a raw 500)"
        )

        # No mail.sent audit row may be written on a failed send (audit-on-success-only).
        with engine.connect() as conn:
            conn.execute(
                text("SELECT set_config('app.current_space_id', :sid, true)"),
                {"sid": str(space_id)},
            )
            count = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.audit_log "
                    "WHERE event_type = 'mail.sent'"
                )
            ).scalar_one()
        assert count == 0, (
            "WR-04: a failed invite send must NOT write a mail.sent audit row"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


# ===========================================================================
# action_code — generate_set_password_link pins the /auth/action continue URL
# ===========================================================================


def test_action_code_continue_url_is_auth_action(monkeypatch):
    """generate_set_password_link builds ActionCodeSettings(url={app_base_url}/auth/action).

    Unit test on the wrapper — no DB, no live IdP. ``app_base_url`` is provided via config
    (env), the ``auth`` seam is faked, and the assertion pins that ``ActionCodeSettings`` is
    constructed with the branded ``/auth/action`` continue URL and passed to
    ``generate_password_reset_link`` (D-11 / A6).
    """
    import app.auth.admin_users as au

    captured = {}

    class _FakeACS:
        def __init__(self, *, url, handle_code_in_app):
            captured["url"] = url
            captured["handle_code_in_app"] = handle_code_in_app

    def _fake_reset_link(email, action_code_settings=None):
        captured["email"] = email
        captured["acs"] = action_code_settings
        return "https://idp/action?oobCode=X"

    # Pin app_base_url via env so get_settings() reads it (Settings is not cached).
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(au.auth, "ActionCodeSettings", _FakeACS)
    monkeypatch.setattr(au.auth, "generate_password_reset_link", _fake_reset_link)

    link = au.generate_set_password_link("user@x.com")

    assert link == "https://idp/action?oobCode=X"
    assert captured["email"] == "user@x.com"
    assert captured["url"] == "https://app.example.com/auth/action", (
        "the continue URL must be {app_base_url}/auth/action (D-11)"
    )
    assert captured["handle_code_in_app"] is True
    assert captured["acs"] is not None, (
        "ActionCodeSettings must be passed to generate_password_reset_link"
    )


def test_action_code_falls_back_to_bare_link_when_no_base_url(monkeypatch):
    """When app_base_url is unset, generate_set_password_link returns the BARE link (no raise)."""
    import app.auth.admin_users as au

    calls = {}

    def _fake_reset_link(email, action_code_settings=None):
        calls["action_code_settings"] = action_code_settings
        return "https://idp/action?oobCode=BARE"

    # Ensure no APP_BASE_URL in the environment for this case.
    monkeypatch.delenv("APP_BASE_URL", raising=False)
    monkeypatch.setattr(au.auth, "generate_password_reset_link", _fake_reset_link)

    link = au.generate_set_password_link("user@x.com")

    assert link == "https://idp/action?oobCode=BARE"
    assert calls["action_code_settings"] is None, (
        "with no app_base_url the bare link is generated (no ActionCodeSettings, no raise)"
    )
