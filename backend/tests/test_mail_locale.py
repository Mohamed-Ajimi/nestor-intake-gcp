"""Mail-locale suite (Phase 11 / I18N-01/02 / D-02 / D-07 / D-12 / T-11-01/11/12).

Two layers, authored by construction (the dev box has no Python — the suite runs in
Cloud Build):

- RENDER LEVEL (Task 1): drives ``app.mail.render`` directly (no HTTP, no Resend) and
  pins the per-locale variant selection, the ``nl`` fallback for an unknown locale,
  autoescape-stays-ON in every variant (T-11-01), and that ``render_admin_validated`` has
  NO ``locale`` param and stays Dutch (D-02).
- SEND PATH (Task 2): drives the REAL ``intake_router`` mail surface + the ``admin_router``
  invite-mail endpoint over live Postgres through a FastAPI ``TestClient`` (mail egress
  faked via ``fake_resend``), pinning that each recipient's locale is resolved SERVER-SIDE
  (membership.locale -> org.default_locale -> "nl"), that a mixed-locale recipient list
  sends the correct variant per recipient, that the sending admin's UI never influences the
  variant, that D-16 send-first/stamp-on-2xx discipline is preserved, and that the invite
  mail uses the target space's default_locale.

``app.mail.render`` is imported LAZILY via ``importorskip`` so the render-level cases
collect on a box without jinja2; the send-path cases are ``pytest.mark.integration``
(skipped without Docker) and ``importorskip``-guarded like ``test_mail_endpoints.py``.
"""

from __future__ import annotations

import uuid

import pytest

# ---------------------------------------------------------------------------
# RENDER LEVEL (Task 1) — variant selection, nl fallback, autoescape, admin_validated
# ---------------------------------------------------------------------------

render = pytest.importorskip("app.mail.render")

_BASE = "https://app.example"
_INTAKE_ID = "3f4b1e2a-0000-4000-8000-000000000abc"


def _validation(locale: str) -> str:
    return render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=f"{_BASE}/intake/{_INTAKE_ID}",
        is_reminder=False,
        app_base_url=_BASE,
        locale=locale,
    )


def _results(locale: str) -> str:
    return render.render_results(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=f"{_BASE}/intake/{_INTAKE_ID}/results",
        app_base_url=_BASE,
        locale=locale,
    )


def _invite(locale: str) -> str:
    return render.render_invite(
        cta_url="https://auth.example/action?mode=resetPassword&oobCode=XYZ",
        app_base_url=_BASE,
        locale=locale,
    )


# (r1) fr variant selected -----------------------------------------------------


def test_render_validation_fr_variant_selected():
    """render_validation(locale="fr") selects the FR prose (not the NL canonical)."""
    html = _validation("fr")
    assert "page de validation" in html, "the FR validation variant must be selected"
    assert "validatie-pagina" not in html, "the FR variant must not carry the NL prose"


def test_render_results_fr_variant_selected():
    """render_results(locale="fr") selects the FR prose (not the NL canonical)."""
    html = _results("fr")
    assert "résultats de la recherche" in html, "the FR results variant must be selected"
    assert "onderzoeksresultaten" not in html, "the FR variant must not carry the NL prose"


def test_render_invite_fr_variant_selected():
    """render_invite(locale="fr") selects the FR prose (not the NL canonical)."""
    html = _invite("fr")
    assert "mot de passe" in html, "the FR invite variant must be selected"
    assert "wachtwoord" not in html, "the FR variant must not carry the NL prose"


# (r2) en variant selected -----------------------------------------------------


def test_render_validation_en_variant_selected():
    """render_validation(locale="en") selects the EN prose (not the NL canonical)."""
    html = _validation("en")
    assert "validation page" in html, "the EN validation variant must be selected"
    assert "validatie-pagina" not in html, "the EN variant must not carry the NL prose"


def test_render_results_en_variant_selected():
    """render_results(locale="en") selects the EN prose (not the NL canonical)."""
    html = _results("en")
    assert "research results are ready" in html, "the EN results variant must be selected"
    assert "onderzoeksresultaten" not in html, "the EN variant must not carry the NL prose"


def test_render_invite_en_variant_selected():
    """render_invite(locale="en") selects the EN prose (not the NL canonical)."""
    html = _invite("en")
    assert "Choose your password" in html, "the EN invite variant must be selected"
    assert "wachtwoord" not in html, "the EN variant must not carry the NL prose"


# (r3) unknown/missing locale -> nl fallback -----------------------------------


def test_render_unknown_locale_falls_back_to_nl():
    """An unknown locale resolves to the guaranteed nl variant (D-07 chain base)."""
    val = _validation("de")  # no de/ variant exists
    res = _results("zz")
    inv = _invite("xx")
    assert "validatie-pagina" in val, "unknown-locale validation must fall back to NL"
    assert "onderzoeksresultaten" in res, "unknown-locale results must fall back to NL"
    assert "wachtwoord" in inv, "unknown-locale invite must fall back to NL"


def test_render_default_locale_is_nl():
    """The default (no locale arg) renders the NL canonical (back-compat with existing callers)."""
    html = render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=f"{_BASE}/intake/{_INTAKE_ID}",
        is_reminder=False,
        app_base_url=_BASE,
    )
    assert "validatie-pagina" in html, "the default locale must render the NL variant"


# (r4) autoescape stays ON in every variant ------------------------------------


@pytest.mark.parametrize("locale", ["nl", "fr", "en", "de"])
def test_render_autoescape_on_in_every_variant(locale):
    """A <script> in project_title is HTML-escaped in EVERY locale variant (T-11-01)."""
    html = render.render_validation(
        first_name="Sam",
        project_title="<script>alert('x')</script>",
        cta_url=f"{_BASE}/intake/{_INTAKE_ID}",
        is_reminder=False,
        app_base_url=_BASE,
        locale=locale,
    )
    assert "<script>" not in html, f"autoescape must strip the raw tag in {locale}"
    assert "&lt;script&gt;" in html, f"the escaped form must be present in {locale}"


# (r5) render_admin_validated has no locale param + stays Dutch ----------------


def test_render_admin_validated_has_no_locale_param():
    """render_admin_validated exposes NO locale param and renders the Dutch template (D-02)."""
    import inspect

    sig = inspect.signature(render.render_admin_validated)
    assert "locale" not in sig.parameters, (
        "D-02: render_admin_validated must NOT take a locale param (stays Dutch)"
    )
    html = render.render_admin_validated(
        client_name="Acme BV",
        project_title="Project Phoenix",
        cta_url=f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}",
        app_base_url=_BASE,
    )
    assert "Klant heeft gevalideerd" in html, "admin_validated must render the Dutch prose"


# ---------------------------------------------------------------------------
# SEND PATH (Task 2) — per-recipient locale, mixed list, admin-UI-independence, D-16
# ---------------------------------------------------------------------------

pytestmark_integration = pytest.mark.integration

_send = pytest.importorskip("app.api.intake_routes")
_admin_routes = pytest.importorskip("app.api.admin_routes")
dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
admin_users = pytest.importorskip("app.auth.admin_users")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
admin_router = _admin_routes.admin_router

SCHEMA = "nestor"
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

# FR/EN/NL prose sentinels used to assert WHICH variant reached a given recipient's mail.
_FR_RESULTS = "résultats de la recherche"
_EN_RESULTS = "research results are ready"
_NL_RESULTS = "onderzoeksresultaten"
_FR_INVITE = "mot de passe"
_EN_INVITE = "Choose your password"
_NL_INVITE = "wachtwoord"


def _user(space_id: uuid.UUID) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    def _override():
        return identity

    return _override


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


def _create_space(conn, space_id: uuid.UUID, name: str, default_locale: str = "nl") -> None:
    from sqlalchemy import text

    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organizations (id, name, default_locale) "
            "VALUES (:id, :name, :locale)"
        ),
        {"id": space_id, "name": name, "locale": default_locale},
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
    conn,
    space_id: uuid.UUID,
    email: str,
    status: str = "active",
    locale: str | None = None,
) -> uuid.UUID:
    from sqlalchemy import text

    mid = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.organization_memberships "
            "(id, organization_id, provider_user_id, email, role, status, locale) "
            "VALUES (:id, :org, :uid, :email, 'user', :status, :locale)"
        ),
        {
            "id": mid,
            "org": space_id,
            "uid": f"pu-{mid}",
            "email": email,
            "status": status,
            "locale": locale,
        },
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


def _html_for(fake_resend, email: str) -> str:
    """Return the rendered HTML of the send call that targeted ``email`` (one recipient)."""
    for call in fake_resend["calls"]:
        if email in call["to"]:
            return call["html"]
    raise AssertionError(f"no send call targeted {email!r}")


def _read_intake_timestamps(engine, set_space, space_id, intake_id):
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
    from sqlalchemy import text

    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        return conn.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.audit_log WHERE event_type = 'mail.sent'"
            )
        ).scalar_one()


# (a) membership.locale="fr" -> fr variant --------------------------------------


@pytestmark_integration
def test_recipient_membership_locale_fr_gets_fr_variant(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A recipient with membership.locale='fr' receives the FR results variant (D-07 override)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "FR Override Space", default_locale="nl")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "fr@x.com", locale="fr")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        html = _html_for(fake_resend, "fr@x.com")
        assert _FR_RESULTS in html, "membership.locale='fr' must render the FR variant"
        assert _NL_RESULTS not in html
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (b) no override, space default_locale="en" -> en variant ----------------------


@pytestmark_integration
def test_recipient_inherits_space_default_en(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A recipient with no override inherits the space default_locale='en' (D-07 chain)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "EN Default Space", default_locale="en")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "en@x.com", locale=None)

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        html = _html_for(fake_resend, "en@x.com")
        assert _EN_RESULTS in html, "no override + space default 'en' must render the EN variant"
        assert _NL_RESULTS not in html
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (c) neither override nor non-nl space default -> nl ---------------------------


@pytestmark_integration
def test_recipient_falls_back_to_nl(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A recipient with no override in an nl-default space gets the NL variant (chain base)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "NL Default Space", default_locale="nl")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "nl@x.com", locale=None)

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        html = _html_for(fake_resend, "nl@x.com")
        assert _NL_RESULTS in html, "no override + nl space default must render the NL variant"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (d) mixed-locale recipient list -> correct variant per recipient --------------


@pytestmark_integration
def test_mixed_locale_list_sends_correct_variant_per_recipient(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A mixed-locale recipient list renders+sends the correct variant to each recipient."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        # Space default 'nl'; one fr-override, one en-override, one inheriting nl.
        with engine.begin() as conn:
            _create_space(conn, space_a, "Mixed Locale Space", default_locale="nl")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            m_fr = _insert_member(conn, space_a, "fr@x.com", locale="fr")
            m_en = _insert_member(conn, space_a, "en@x.com", locale="en")
            m_nl = _insert_member(conn, space_a, "nl@x.com", locale=None)

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(m_fr), str(m_en), str(m_nl)]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["recipient_count"] == 3, "recipient_count is the total across groups"

        # One send per distinct locale group (3 distinct locales -> 3 sends).
        assert len(fake_resend["calls"]) == 3, (
            "a mixed-locale list must render+send once per distinct locale group"
        )
        assert _FR_RESULTS in _html_for(fake_resend, "fr@x.com")
        assert _EN_RESULTS in _html_for(fake_resend, "en@x.com")
        assert _NL_RESULTS in _html_for(fake_resend, "nl@x.com")

        # The stamp happens exactly once (not per group) and one audit row is written.
        _, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_a)
        assert res_ts is not None, "a successful results send stamps results_link_sent_at once"
        assert _count_mail_sent_audit(engine, space_a) == 1, (
            "a successful multi-locale send writes exactly ONE mail.sent audit row"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (e) sending admin's UI language does NOT affect the variant --------------------


@pytestmark_integration
def test_admin_ui_language_does_not_affect_variant(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """The sending admin's own membership.locale never leaks into the recipient's variant."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Admin UI Space", default_locale="nl")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            # The sending admin is EN; the recipient is FR. The mail must be FR, not EN.
            _insert_member(conn, space_a, "admin@x.com", locale="en")
            recipient = _insert_member(conn, space_a, "client@x.com", locale="fr")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)
        # The Identity carries NO locale — locale is resolved from the recipient's row only.
        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(recipient)]},
            headers={
                "Authorization": "Bearer x",
                "Accept-Language": "en-US,en;q=0.9",  # admin UI hint — must be ignored
            },
        )
        assert resp.status_code == 200, resp.text
        html = _html_for(fake_resend, "client@x.com")
        assert _FR_RESULTS in html, "the recipient's FR locale must win over the admin's EN UI"
        assert _EN_RESULTS not in html, "the admin's UI language must NOT select the variant"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (f) D-16 preserved — send failure -> {"success": False}, no stamp/audit -------


@pytestmark_integration
def test_locale_send_failure_preserves_d16(
    engine, set_space, two_spaces, monkeypatch, fake_resend
):
    """A send failure in the per-locale loop returns success=False with NO stamp / NO audit (D-16)."""
    from fastapi.testclient import TestClient

    space_a, _b = two_spaces
    intake_a = uuid.uuid4()

    app = _build_intake_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "D16 Locale Space", default_locale="fr")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
            member = _insert_member(conn, space_a, "fail@x.com", locale="fr")

        monkeypatch.setenv("APP_BASE_URL", "https://app.example.com")
        _patch_engine_factories(monkeypatch, engine)

        import app.mail.resend as resend_mod

        def _raise(*, to, subject, html):  # noqa: ANN001
            raise RuntimeError("resend 500 in locale loop")

        monkeypatch.setattr(resend_mod, "send", _raise)

        app.dependency_overrides[get_current_identity] = _as(_user(space_a))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_a}/mail/results",
            json={"recipients": [str(member)]},
            headers={"Authorization": "Bearer x"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is False, "a failed locale send must report success=False"
        _, res_ts = _read_intake_timestamps(engine, set_space, space_a, intake_a)
        assert res_ts is None, "D-16: a failed send must NOT stamp results_link_sent_at"
        assert _count_mail_sent_audit(engine, space_a) == 0, (
            "D-16: a failed send must NOT write a mail.sent audit row"
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_a)


# (g) invite mail uses the space default_locale ---------------------------------


@pytestmark_integration
def test_invite_mail_uses_space_default_locale(
    engine, monkeypatch, superadmin_engine, fake_resend
):
    """The invite mail renders in the target space's default_locale (invitee has no override yet)."""
    from unittest.mock import MagicMock, patch

    from fastapi.testclient import TestClient
    from sqlalchemy import text

    space_id = uuid.uuid4()
    membership_id = uuid.uuid4()
    action_link = "https://idp/action?oobCode=FRINVITE"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "FR Invite Space", default_locale="fr")
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
                headers={"Authorization": "Bearer x"},
            )

        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True
        html = _html_for(fake_resend, "invitee@x.com")
        assert _FR_INVITE in html, "the invite must render in the space default_locale (fr)"
        assert _NL_INVITE not in html, "the invite must not fall back to NL for an fr space"
        assert action_link in html, "the invite (D-09) must still carry the action link"
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)
