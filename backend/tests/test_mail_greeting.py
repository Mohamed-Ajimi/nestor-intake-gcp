"""Mail greeting contract (quick 261006-jgn, closes DEF-23.5-03-03).

Every client mail body used to greet ``first_name=client`` — the intake's ``client_name``,
which since D-23.5-03 is the PROJECT name — so a body read "Hi Marktintrede Benelux". The
greeting slot now receives the FIRST NAME of the ``contact_name`` form answer ("Naam
primaire contactpersoon"), or ``""`` so the template's own fallback ("team" / "équipe")
applies. Subjects are UNCHANGED (they still carry ``intake.client_name``).

| Test                                 | Proves                                                  |
|--------------------------------------|---------------------------------------------------------|
| ``greeting_first_name_*`` (pure)     | first whitespace token; localized dict resolved nl-first|
|                                      | (the brief's ``_resolve_localized``); junk -> ""        |
| ``validation_greets_contact``        | html "Hi Sam", not "Hi <client_name>"; subject keeps    |
|                                      | the client_name                                         |
| ``no_contact_falls_back``            | no contact_name answer -> "Hi team" (nl) and            |
|                                      | "Bonjour équipe" (fr recipient)                         |
| ``greeting_is_escaped``              | a hostile contact name arrives HTML-escaped (T-jgn-01)  |
| ``report_mail_greets_contact``       | ``_send_report_mail`` uses the same greeting            |

The pure-helper tests need no DB; the endpoint tests are ``integration`` (testcontainers).
"""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

intake_routes = pytest.importorskip("app.api.intake_routes")
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only
_AUTH = {"Authorization": "Bearer ignored-overridden"}


# ===========================================================================
# Pure helper — no DB
# ===========================================================================


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Sam De Smet", "Sam"),
        ("  Sam  ", "Sam"),
        ("Sam", "Sam"),
        ({"nl": "Jan Peeters", "fr": "Jean", "en": "John"}, "Jan"),
        ({"fr": "Jean Dupont"}, "Jean"),
        (None, ""),
        ("", ""),
        ("   ", ""),
        ({}, ""),
        (42, ""),
        (["Sam"], ""),
    ],
)
def test_greeting_first_name(raw, expected):
    assert intake_routes._greeting_first_name(raw) == expected


# ===========================================================================
# Endpoint / report-mail tests — live Postgres
# ===========================================================================


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity):
    def _override():
        return identity

    return _override


@pytest.fixture
def superadmin_engine(engine):
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


def _seed(engine, set_space, *, client_name: str, contact: object | None, locale: str | None):
    """Create a space + intake (+ optional contact_name answer) + one active member.

    Returns ``(space_id, intake_id, member_id)``. ``contact`` is a plain str (stored in
    ``value``) or a dict (stored in ``value_json``), mirroring the answers API split.
    """
    from sqlalchemy import text

    space_id, intake_id, member_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "Greeting Org"},
        )
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
                "VALUES (:id, :sid, 'draft', :cn)"
            ),
            {"id": intake_id, "sid": space_id, "cn": client_name},
        )
        if contact is not None:
            is_str = isinstance(contact, str)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intake_answers "
                    "(space_id, intake_id, field_key, value, value_json) "
                    "VALUES (:sid, :iid, 'contact_name', :v, CAST(:vj AS jsonb))"
                ),
                {
                    "sid": space_id,
                    "iid": intake_id,
                    "v": contact if is_str else None,
                    "vj": None if is_str else json.dumps(contact),
                },
            )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.organization_memberships "
                "(id, organization_id, provider_user_id, email, role, status, locale) "
                "VALUES (:id, :org, :uid, :email, 'user', 'active', :locale)"
            ),
            {
                "id": member_id,
                "org": space_id,
                "uid": f"pu-{member_id}",
                "email": f"m-{member_id}@x.com",
                "locale": locale,
            },
        )
    return space_id, intake_id, member_id


def _cleanup(engine, space_id):
    """Drop the space (CASCADE) AND its ``mail.sent`` audit rows.

    ``audit_log`` is NOT RLS-scoped and does not cascade from the organisation, and
    ``test_mail_endpoints`` counts ``mail.sent`` rows globally — so leaving ours behind would
    make that suite order-dependent.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": space_id}
        )
        conn.execute(text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": space_id})


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _send_validation(engine, superadmin_engine, monkeypatch, intake_id, member_id):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: engine)
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: superadmin_engine)
    app = _build_app()
    app.dependency_overrides[get_current_identity] = _as(_superadmin())
    try:
        resp = TestClient(app).post(
            f"/intakes/{intake_id}/mail/validation",
            json={"recipients": [str(member_id)]},
            headers=_AUTH,
        )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    return resp


@pytest.mark.integration
def test_validation_greets_contact_first_name(
    engine, set_space, superadmin_engine, monkeypatch, fake_resend
):
    space_id, intake_id, member_id = _seed(
        engine, set_space, client_name="Marktintrede Benelux", contact="Sam De Smet", locale="nl"
    )
    try:
        _send_validation(engine, superadmin_engine, monkeypatch, intake_id, member_id)
        assert len(fake_resend["calls"]) == 1
        sent = fake_resend["calls"][0]
        assert "Hi Sam" in sent["html"], "the body must greet the contact's first name"
        assert "Hi Marktintrede Benelux" not in sent["html"], (
            "the body must no longer greet the project name (DEF-23.5-03-03)"
        )
        assert "Marktintrede Benelux" in sent["subject"], "the subject is unchanged"
    finally:
        _cleanup(engine, space_id)


@pytest.mark.integration
def test_validation_greets_localized_contact(
    engine, set_space, superadmin_engine, monkeypatch, fake_resend
):
    space_id, intake_id, member_id = _seed(
        engine,
        set_space,
        client_name="Proj",
        contact={"nl": "Jan Peeters", "fr": "Jean", "en": "John"},
        locale="nl",
    )
    try:
        _send_validation(engine, superadmin_engine, monkeypatch, intake_id, member_id)
        assert "Hi Jan" in fake_resend["calls"][0]["html"]
    finally:
        _cleanup(engine, space_id)


@pytest.mark.integration
@pytest.mark.parametrize(("locale", "fallback"), [("nl", "Hi team"), ("fr", "Bonjour équipe")])
def test_no_contact_falls_back_to_template_word(
    engine, set_space, superadmin_engine, monkeypatch, fake_resend, locale, fallback
):
    space_id, intake_id, member_id = _seed(
        engine, set_space, client_name="Marktintrede Benelux", contact=None, locale=locale
    )
    try:
        _send_validation(engine, superadmin_engine, monkeypatch, intake_id, member_id)
        html = fake_resend["calls"][0]["html"]
        assert fallback in html, f"no contact_name -> template fallback {fallback!r}"
        assert "Marktintrede Benelux</h1>" not in html
    finally:
        _cleanup(engine, space_id)


@pytest.mark.integration
def test_greeting_is_escaped(engine, set_space, superadmin_engine, monkeypatch, fake_resend):
    space_id, intake_id, member_id = _seed(
        engine, set_space, client_name="Proj", contact="<b>x</b> Doe", locale="en"
    )
    try:
        _send_validation(engine, superadmin_engine, monkeypatch, intake_id, member_id)
        html = fake_resend["calls"][0]["html"]
        assert "&lt;b&gt;x&lt;/b&gt;" in html, "the greeting must arrive HTML-escaped"
        assert "<b>x</b>" not in html, "T-jgn-01: raw markup must never reach the mail body"
    finally:
        _cleanup(engine, space_id)


@pytest.mark.integration
def test_report_mail_greets_contact(engine, set_space, superadmin_engine, monkeypatch, fake_resend):
    """``_send_report_mail`` (the /deliver mail) greets the same contact first name."""
    from sqlalchemy.orm import Session

    space_id, intake_id, member_id = _seed(
        engine, set_space, client_name="Marktintrede Benelux", contact="Sam De Smet", locale="nl"
    )
    monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
    try:
        intake = SimpleNamespace(id=intake_id, space_id=space_id, client_name="Marktintrede Benelux")
        with Session(superadmin_engine) as s:
            set_space(s, space_id)
            sent = intake_routes._send_report_mail(s, _superadmin(), intake, [str(member_id)])
            s.rollback()
        assert sent is True
        html = fake_resend["calls"][0]["html"]
        assert "Hi Sam" in html
        assert "Hi Marktintrede Benelux" not in html
        assert "/report" in html
    finally:
        _cleanup(engine, space_id)
