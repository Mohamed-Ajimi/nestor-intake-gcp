"""Operator-verb denial suite (SEC-01 / TENANT-02) — plan 23.1-10.

WHAT THIS FILE PROVES. ``23.1-CONTEXT.md`` § 1 enumerates the intake verbs that took
``Depends(get_current_identity)`` and NO role gate, so a role=``user`` could advance their
own intake to ``reviewed``, mark it ``delivered``, repoint the delivered report, send four
kinds of product-branded mail on Agenic's behalf (stamping ``validation_link_sent_at`` /
``results_link_sent_at`` along the way), and enumerate every member email of their space.
D-23.1-02 pins the fix: ONE shared ``app.auth.gates.superadmin_gate`` (existence-hidden
**404**, never 403) applied to exactly those verbs. This file is the proof that the gate
bites, that it bites WITHOUT side effects, and that it did not also brick the operator.

| Test family                        | Proves                                                   |
|------------------------------------|----------------------------------------------------------|
| ``*_user_role_404``                | a role=``user`` IN THE INTAKE'S OWN SPACE gets EXACTLY    |
|                                    | 404 — not 403, not 401, not 422 — with a WELL-FORMED      |
|                                    | body, so the 404 can only have come from the gate. Each   |
|                                    | carries a NO-SIDE-EFFECT assertion (see below).           |
| ``*_null_space_404``               | a ``user`` whose ``space_id`` is None gets EXACTLY 404    |
|                                    | and **NOT** the null-space 403. The ordering proof.       |
| ``*_superadmin_still_works``       | a superadmin gets the verb's normal success status        |
|                                    | against properly seeded state. Without this arm, "gate    |
|                                    | everything to 404" would pass the whole suite.            |
| ``all_eight_..._shared_gate``      | the structural audit: ``gates.superadmin_gate`` is in     |
|                                    | each of the eight routes' RESOLVED dependency tree.       |
| ``gate_is_declared_before_repo``   | the ordering contract, pinned on the live signatures.     |

THE NO-SIDE-EFFECT ASSERTIONS (a status code alone is the weak form):

* the four mail verbs — ``fake_resend``'s recorded send list is EMPTY, and for
  validation/results the corresponding ``*_sent_at`` column is still NULL;
* ``review_intake`` — the intake status is unchanged AND no ``intake.status_changed``
  audit row exists;
* ``deliver_report`` / ``replace_report`` — status and ``final_report_artifact_id``
  unchanged;
* ``list_members`` — the 404 body contains no ``@`` character.

WHY THE NULL-SPACE ARM EXISTS — it is the ORDERING proof. ``get_tenant_repo`` answers a
null-space user with the D-04 default-deny **403** (``app/db/session.py:86-89``). FastAPI
resolves a handler signature IN ORDER, so if ``Depends(get_tenant_repo)`` were declared
before ``Depends(superadmin_gate)`` the repo's 403 would win — and a 403 where 404 is the
convention tells an unauthorized caller the endpoint EXISTS. That is an existence oracle,
and it is a change no reviewer would read as a security edit. Six of the eight verbs take a
repo; for the two that do not (``deliver_report`` / ``replace_report``, which open their own
``ai_session.tenant_session``) the same arm pins that the gate fires before the handler body
can raise ``PermissionError``.

THE COUNTERWEIGHT. ``tests/test_client_surface_open.py`` (plan 23.1-02) pins the TEN client
routes that must stay reachable by role=``user`` — including ``GET /intakes/{id}/skill-runs``
and ``GET /intakes/{id}/skill-runs/{run_id}``, which ``IntakeForm.tsx:16`` (the CLIENT form)
reads to render the proposal tick shipped 2026-08-31. This file must never make that one red.

HARNESS PROVENANCE. The drive-the-real-route + fabricated-Identity + engine-factory-patch
scaffold is ``test_intake_cross_tenant.py`` / ``test_research_cross_tenant.py``. The seeding
helpers below are COPIED (never imported — no private symbol crosses a test module) from
``test_report_delivery.py`` (``_insert_intake_status``, ``_insert_member``,
``_insert_report_artifact``, ``_link_report``, ``_read_intake``, ``_key``) and
``test_mail_endpoints.py`` (``superadmin_engine``, ``_patch_superadmin_engine``,
``_count_mail_sent_audit`` -> ``_count_audit``). The mail-egress seam is conftest's
``fake_resend`` recorder.

The two ROUTE-WALKING helpers ARE imported from ``test_client_surface_open.py``, on
D-23.1-14's explicit instruction ("do NOT re-derive route walking"): FastAPI 0.141 does not
flatten ``include_router``, so a naive ``[r for r in app.routes if ...]`` finds ZERO
``/intakes`` routes and any audit written that way is VACUOUSLY GREEN, and include-level
dependencies never reach ``route.dependant`` at all.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker/DATABASE_URL);
``importorskip`` guards so the file COLLECTS on a box without the backend deps.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

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
ai_session_mod = pytest.importorskip("app.db.ai_session")
gates = pytest.importorskip("app.auth.gates")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Password granted to the app_superadmin role for the connect-as superadmin engine (test
#: only — the SAME literal test_mail_endpoints / test_research_cross_tenant use, so the
#: role's password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

#: The app base URL every mail CTA is built from. With it UNSET ``_run_intake_send`` REFUSES
#: the send (WR-01) and returns 200 ``{"success": False}`` — which would make a superadmin
#: mail arm pass for the wrong reason, so every scenario pins it.
_APP_BASE_URL = "https://app.example.com"


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the D-04 default-deny case ``get_tenant_repo`` 403s."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch BOTH the ``session.py`` and ``ai_session.py`` engine factories.

    Six of the eight verbs reach the DB through ``get_tenant_repo`` (``app.db.session``);
    ``deliver_report`` / ``replace_report`` open their own ``ai_session.tenant_session``,
    which resolves its engine through ``ai_session``'s OWN import of ``get_engine``. Patching
    one namespace only would leave half the surface pointed at a real engine.
    """
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in both namespaces (the superadmin happy-path arms)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach.
    ``app_superadmin`` is a plain non-superuser LOGIN role (conftest's
    ``_ensure_app_superadmin``), so the arm proves the bypass POLICY + GRANTs, not superuser
    ambient authority. Shape copied from ``test_mail_endpoints.superadmin_engine``.
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
# Seeding helpers (copied from test_report_delivery.py / test_mail_endpoints.py)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake_status(conn, set_space, space_id, intake_id, status: str) -> None:
    """Insert one intake at an EXPLICIT status (GUC set so the 0002 WITH CHECK passes)."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, :status, 'Acme')"
        ),
        {"id": intake_id, "space_id": space_id, "status": status},
    )


def _insert_member(conn, space_id, email: str, status: str = "active"):
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


def _insert_report_artifact(conn, set_space, space_id, intake_id, storage_path: str):
    """Insert a report ``research_artifacts`` row under the OWNING space GUC; return its id."""
    from sqlalchemy import text

    set_space(conn, space_id)
    aid = uuid.uuid4()
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.research_artifacts "
            "(id, space_id, intake_id, source, artifact_type, filename, storage_path, "
            " byte_size, mime_type) "
            "VALUES (:id, :space_id, :intake_id, 'human-report', 'report', 'report.pdf', "
            " :storage_path, 12345, 'application/pdf')"
        ),
        {
            "id": aid,
            "space_id": space_id,
            "intake_id": intake_id,
            "storage_path": storage_path,
        },
    )
    return aid


def _link_report(conn, set_space, space_id, intake_id, artifact_id) -> None:
    """Point ``intakes.final_report_artifact_id`` at ``artifact_id`` (owner GUC set)."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(f"UPDATE {SCHEMA}.intakes SET final_report_artifact_id = :aid WHERE id = :id"),
        {"aid": artifact_id, "id": intake_id},
    )


def _read_intake(engine, set_space, space_id, intake_id):
    """Return (status, final_report_artifact_id, validation_link_sent_at, results_link_sent_at)."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        row = conn.execute(
            text(
                "SELECT status, final_report_artifact_id, validation_link_sent_at, "
                f"results_link_sent_at FROM {SCHEMA}.intakes WHERE id = :id"
            ),
            {"id": intake_id},
        ).first()
    return tuple(row) if row is not None else (None, None, None, None)


def _count_audit(engine, space_id, event_type: str, target) -> int:
    """Count ``audit_log`` rows of one event type FOR ONE INTAKE (GUC set for the RLS read).

    The ``target`` filter is load-bearing, not decoration. The conftest ``engine`` connects as
    the migration owner, for which the audit read is NOT space-filtered (``test_transition_
    audited`` reads the trail on this engine with no GUC at all), so a count filtered only by
    ``event_type`` sees EVERY space's rows — including those a sibling test in this same file
    wrote before cleanup. Measured: without this filter
    ``test_review_superadmin_still_works`` passes alone and fails in-file, having counted
    ``test_review_user_role_404``'s row. Scoping to the intake id makes each case independent
    of run order.
    """
    from sqlalchemy import func, select, text

    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        return conn.execute(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.event_type == event_type)
            .where(AuditLog.target == str(target))
        ).scalar_one()


def _key(space_id, intake_id, name="report.pdf") -> str:
    """A well-formed staged report key under the intake's own ``reports/`` prefix (D-08)."""
    return f"{space_id}/{intake_id}/reports/{uuid.uuid4()}-{name}"


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + intake_router."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _cleanup_spaces(engine, *space_ids) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


# ---------------------------------------------------------------------------
# The scenario context manager — one seeded space/intake/member per case
# ---------------------------------------------------------------------------


class _Scenario:
    """Everything a case needs to drive one verb: the app, the seeded ids, a client."""

    def __init__(self, app, space_id, intake_id, member_id, artifact_id):
        self.app = app
        self.space_id = space_id
        self.intake_id = intake_id
        self.member_id = member_id
        self.artifact_id = artifact_id

    def client(self):
        from fastapi.testclient import TestClient

        # raise_server_exceptions=False so that an UNGATED null-space call into
        # deliver/replace — which raise PermissionError out of tenant_session rather than an
        # HTTPException — surfaces as a 500 RESPONSE this suite can assert on, instead of
        # blowing the test up with a traceback that hides the status a caller would see.
        return TestClient(self.app, raise_server_exceptions=False)


@contextmanager
def _scenario(
    engine,
    set_space,
    monkeypatch,
    identity,
    status: str,
    *,
    link_report: bool = False,
    sa_engine=None,
):
    """Seed space + intake@status + one active member; wire the overrides; always clean up.

    ``identity`` is either a ready ``Identity`` (the null-space / superadmin arms) or a
    CALLABLE taking the freshly-minted ``space_id`` — which is how the ``user``-role arms get
    an identity scoped to the intake's OWN space. That scoping is the point: a cross-space
    user is already 404'd by ``repo.get``, so only an OWN-SPACE user proves the ROLE gate.
    """
    space_id = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Operator verb gate space")
        with engine.begin() as conn:
            _insert_intake_status(conn, set_space, space_id, intake_id, status)
            member_id = _insert_member(conn, space_id, "member@x.com")

        artifact_id = None
        if link_report:
            with engine.begin() as conn:
                artifact_id = _insert_report_artifact(
                    conn, set_space, space_id, intake_id, _key(space_id, intake_id)
                )
                _link_report(conn, set_space, space_id, intake_id, artifact_id)

        monkeypatch.setenv("APP_BASE_URL", _APP_BASE_URL)  # WR-01
        _patch_engine_factories(monkeypatch, engine)
        if sa_engine is not None:
            _patch_superadmin_engine(monkeypatch, sa_engine)
        resolved = identity(space_id) if callable(identity) else identity
        app.dependency_overrides[get_current_identity] = _as(resolved)

        yield _Scenario(app, space_id, intake_id, member_id, artifact_id)
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


def _mail_body(member_id) -> dict:
    """A WELL-FORMED ``MailRecipients`` body — a 422 would prove nothing about the gate."""
    return {"recipients": [str(member_id)]}


def _deliver_body(space_id, intake_id, member_id, *, recipients: bool = True) -> dict:
    """A WELL-FORMED ``DeliverBody``: a PDF key under the intake's own reports/ prefix."""
    return {
        "storage_path": _key(space_id, intake_id),
        "recipients": [str(member_id)] if recipients else [],
    }


def _assert_denied(resp, verb: str) -> None:
    """EXACTLY 404 with the gate's byte-exact detail — never 403 / 401 / 422 / 500."""
    assert resp.status_code == 404, (
        f"{verb}: an unauthorized caller must get EXACTLY 404 (existence-hidden, "
        f"D-23.1-02), got {resp.status_code} ({resp.text!r}). A 403 is an existence "
        f"oracle; a 422 would mean the body was malformed and the denial proved nothing."
    )
    assert resp.json().get("detail") == "Intake not found", (
        f"{verb}: the 404 detail is part of the convention and is asserted byte-exact "
        f"(app/auth/gates.py), got {resp.json()!r}"
    )


# ===========================================================================
# Verb 1 — GET /intakes/{id}/members   (intake_routes.list_members)
# ===========================================================================


def test_members_user_role_404(engine, set_space, monkeypatch):
    """role=``user`` in the intake's OWN space cannot enumerate member emails (T-23.1-40)."""
    with _scenario(engine, set_space, monkeypatch, _user, "draft") as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/members", headers=_HDR)
        _assert_denied(resp, "GET /members (user role)")
        assert "@" not in resp.text, (
            "NO SIDE EFFECT (T-23.1-40): the denial body must carry no member email — "
            f"found an '@' in {resp.text!r}"
        )


def test_members_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` gets the gate's 404, NOT ``get_tenant_repo``'s null-space 403."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "draft") as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/members", headers=_HDR)
        _assert_denied(resp, "GET /members (null space)")


def test_members_superadmin_still_works(engine, set_space, monkeypatch, superadmin_engine):
    """A superadmin still reads the space's ACTIVE members — the gate did not brick the verb."""
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "draft", sa_engine=superadmin_engine
    ) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/members", headers=_HDR)
        assert resp.status_code == 200, (
            f"a superadmin members read should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert "member@x.com" in {r["email"] for r in resp.json()}, (
            "the superadmin read must still return the space's active member"
        )


# ===========================================================================
# Verb 2 — POST /intakes/{id}/mail/validation   (send_validation_mail)
# ===========================================================================


def test_mail_validation_user_role_404(engine, set_space, monkeypatch, fake_resend):
    """role=``user`` cannot send the validation mail; NO send, NO stamp (T-23.1-39)."""
    with _scenario(engine, set_space, monkeypatch, _user, "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/validation",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/validation (user role)")
        assert fake_resend["calls"] == [], (
            "NO SIDE EFFECT (T-23.1-39): a denied mail verb must leave the Resend seam "
            f"untouched, recorded {fake_resend['calls']!r}"
        )
        _status, _art, validation_at, _results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert validation_at is None, (
            "NO SIDE EFFECT: validation_link_sent_at must still be NULL after a denial, "
            f"got {validation_at!r}"
        )


def test_mail_validation_null_space_404(engine, set_space, monkeypatch, fake_resend):
    """A null-space ``user`` gets the gate's 404, NOT the null-space 403 (the ordering proof)."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/validation",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/validation (null space)")
        assert fake_resend["calls"] == [], "a denied send must never reach the Resend seam"


def test_mail_validation_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend
):
    """A superadmin still sends the validation mail AND still stamps ``validation_link_sent_at``."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "submitted",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/validation",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin validation send should be 200, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert resp.json().get("success") is True, (
            f"the send must report success, got {resp.json()!r}"
        )
        assert len(fake_resend["calls"]) == 1, "the mail must reach the seam exactly once"
        _status, _art, validation_at, _results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert validation_at is not None, (
            "the 2xx send must still stamp validation_link_sent_at (D-16)"
        )


# ===========================================================================
# Verb 3 — POST /intakes/{id}/mail/reminder   (send_reminder_mail)
# ===========================================================================


def test_mail_reminder_user_role_404(engine, set_space, monkeypatch, fake_resend):
    """role=``user`` cannot send the reminder mail; the Resend seam stays untouched."""
    with _scenario(engine, set_space, monkeypatch, _user, "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/reminder",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/reminder (user role)")
        assert fake_resend["calls"] == [], (
            "NO SIDE EFFECT (T-23.1-39): a denied mail verb must leave the Resend seam "
            f"untouched, recorded {fake_resend['calls']!r}"
        )


def test_mail_reminder_null_space_404(engine, set_space, monkeypatch, fake_resend):
    """A null-space ``user`` gets the gate's 404, NOT the null-space 403."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/reminder",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/reminder (null space)")
        assert fake_resend["calls"] == [], "a denied send must never reach the Resend seam"


def test_mail_reminder_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend
):
    """A superadmin still sends the reminder — and it still stamps NO column (legacy parity)."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "submitted",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/reminder",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin reminder send should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("success") is True, (
            f"the send must report success, got {resp.json()!r}"
        )
        assert len(fake_resend["calls"]) == 1, "the mail must reach the seam exactly once"
        _status, _art, validation_at, results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert validation_at is None and results_at is None, (
            "the reminder path stamps NO column (legacy parity) — unchanged by the gate"
        )


# ===========================================================================
# Verb 4 — POST /intakes/{id}/mail/results   (send_results_mail)
# ===========================================================================


def test_mail_results_user_role_404(engine, set_space, monkeypatch, fake_resend):
    """role=``user`` cannot send the results mail; NO send, NO ``results_link_sent_at``."""
    with _scenario(engine, set_space, monkeypatch, _user, "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/results",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/results (user role)")
        assert fake_resend["calls"] == [], (
            "NO SIDE EFFECT (T-23.1-39): a denied mail verb must leave the Resend seam "
            f"untouched, recorded {fake_resend['calls']!r}"
        )
        _status, _art, _validation_at, results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert results_at is None, (
            f"NO SIDE EFFECT: results_link_sent_at must still be NULL, got {results_at!r}"
        )


def test_mail_results_null_space_404(engine, set_space, monkeypatch, fake_resend):
    """A null-space ``user`` gets the gate's 404, NOT the null-space 403."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "submitted") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/results",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/results (null space)")
        assert fake_resend["calls"] == [], "a denied send must never reach the Resend seam"


def test_mail_results_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend
):
    """A superadmin still sends the results mail AND still stamps ``results_link_sent_at``."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "submitted",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/results",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin results send should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("success") is True, (
            f"the send must report success, got {resp.json()!r}"
        )
        assert len(fake_resend["calls"]) == 1, "the mail must reach the seam exactly once"
        _status, _art, _validation_at, results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert results_at is not None, (
            "the 2xx send must still stamp results_link_sent_at (D-16)"
        )


# ===========================================================================
# Verb 5 — POST /intakes/{id}/mail/intake   (send_intake_mail — draft only)
# ===========================================================================


def test_mail_intake_user_role_404(engine, set_space, monkeypatch, fake_resend):
    """role=``user`` cannot send the intake-invite mail; the Resend seam stays untouched.

    Seeded at ``draft`` on purpose: this is the ONE status at which the verb would otherwise
    succeed (``_run_intake_send``'s ``is_intake`` 409-guard). A 404 here therefore cannot be
    the status guard wearing the gate's clothes.
    """
    with _scenario(engine, set_space, monkeypatch, _user, "draft") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/intake",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/intake (user role)")
        assert fake_resend["calls"] == [], (
            "NO SIDE EFFECT (T-23.1-39): a denied mail verb must leave the Resend seam "
            f"untouched, recorded {fake_resend['calls']!r}"
        )


def test_mail_intake_null_space_404(engine, set_space, monkeypatch, fake_resend):
    """A null-space ``user`` gets the gate's 404, NOT the null-space 403."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "draft") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/intake",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /mail/intake (null space)")
        assert fake_resend["calls"] == [], "a denied send must never reach the Resend seam"


def test_mail_intake_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend
):
    """A superadmin still sends the intake-invite mail from ``draft``."""
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), "draft", sa_engine=superadmin_engine
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/mail/intake",
            json=_mail_body(s.member_id),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin invite send should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json().get("success") is True, (
            f"the send must report success, got {resp.json()!r}"
        )
        assert len(fake_resend["calls"]) == 1, "the mail must reach the seam exactly once"


# ===========================================================================
# Verb 6 — POST /intakes/{id}/review   (review_intake)
# ===========================================================================


def test_review_user_role_404(engine, set_space, monkeypatch):
    """role=``user`` cannot advance their own intake ``submitted`` -> ``reviewed`` (T-23.1-38).

    NO SIDE EFFECT: the status is unchanged AND no ``intake.status_changed`` audit row
    exists — the audit write is in the SAME tx as the patch, so both must be absent.
    """
    with _scenario(engine, set_space, monkeypatch, _user, "submitted") as s:
        resp = s.client().post(f"/intakes/{s.intake_id}/review", headers=_HDR)
        _assert_denied(resp, "POST /review (user role)")

        status_db, _art, _v, _r = _read_intake(engine, set_space, s.space_id, s.intake_id)
        assert status_db == "submitted", (
            f"NO SIDE EFFECT (T-23.1-38): the intake must still be 'submitted', got "
            f"{status_db!r}"
        )
        assert _count_audit(engine, s.space_id, "intake.status_changed", s.intake_id) == 0, (
            "NO SIDE EFFECT: a denied review must write NO intake.status_changed audit row"
        )


def test_review_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` gets the gate's 404, NOT ``get_tenant_repo``'s null-space 403."""
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "submitted") as s:
        resp = s.client().post(f"/intakes/{s.intake_id}/review", headers=_HDR)
        _assert_denied(resp, "POST /review (null space)")


def test_review_superadmin_still_works(engine, set_space, monkeypatch, superadmin_engine):
    """A superadmin still advances ``submitted`` -> ``reviewed`` and still audits it."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "submitted",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(f"/intakes/{s.intake_id}/review", headers=_HDR)
        assert resp.status_code == 200, (
            f"a superadmin review should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["status"] == "reviewed", (
            f"the review must advance the intake to 'reviewed', got {resp.json()['status']!r}"
        )
        assert _count_audit(engine, s.space_id, "intake.status_changed", s.intake_id) == 1, (
            "the superadmin review must still write exactly one status_changed audit row"
        )


# ===========================================================================
# Verb 7 — POST /intakes/{id}/deliver   (deliver_report)
# ===========================================================================


def test_deliver_user_role_404(engine, set_space, monkeypatch, fake_resend):
    """role=``user`` cannot mark their own intake ``delivered`` (T-23.1-38).

    NO SIDE EFFECT: status stays ``in_research``, ``final_report_artifact_id`` stays NULL,
    and the delivery mail never reaches the seam.
    """
    with _scenario(engine, set_space, monkeypatch, _user, "in_research") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/deliver",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /deliver (user role)")

        status_db, artifact_id, _v, _r = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert status_db == "in_research", (
            f"NO SIDE EFFECT (T-23.1-38): the intake must still be 'in_research', got "
            f"{status_db!r}"
        )
        assert artifact_id is None, (
            f"NO SIDE EFFECT: no report artifact may be linked, got {artifact_id!r}"
        )
        assert fake_resend["calls"] == [], "a denied delivery must send no client mail"


def test_deliver_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` gets the gate's 404.

    ``deliver_report`` takes NO ``get_tenant_repo``; it opens its own ``tenant_session``,
    which raises ``PermissionError`` (a 500) for a null-space caller. So this arm pins that
    the gate fires BEFORE the handler body runs at all — 404, never 500, never 403.
    """
    with _scenario(engine, set_space, monkeypatch, _null_space_user(), "in_research") as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/deliver",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /deliver (null space)")


def test_deliver_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine, fake_resend
):
    """A superadmin still delivers: status flips, the artifact links, the mail sends."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "in_research",
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/deliver",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin deliver should be 200, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["status"] == "delivered", "the deliver must flip to 'delivered'"
        status_db, artifact_id, _v, results_at = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert status_db == "delivered", "the DB row must be delivered"
        assert artifact_id is not None, "the report artifact must be linked"
        assert len(fake_resend["calls"]) == 1, "the delivery mail must reach the seam once"
        assert results_at is not None, "the 2xx delivery send stamps results_link_sent_at"


# ===========================================================================
# Verb 8 — POST /intakes/{id}/report/replace   (replace_report)
# ===========================================================================


def test_replace_report_user_role_404(engine, set_space, monkeypatch):
    """role=``user`` cannot repoint the delivered report (T-23.1-38).

    NO SIDE EFFECT: status stays ``delivered`` and ``final_report_artifact_id`` still points
    at the ORIGINAL seeded artifact.
    """
    with _scenario(
        engine, set_space, monkeypatch, _user, "delivered", link_report=True
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/report/replace",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id, recipients=False),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /report/replace (user role)")

        status_db, artifact_id, _v, _r = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert status_db == "delivered", (
            f"NO SIDE EFFECT: the intake must still be 'delivered', got {status_db!r}"
        )
        assert artifact_id == s.artifact_id, (
            "NO SIDE EFFECT (T-23.1-38): final_report_artifact_id must still point at the "
            f"ORIGINAL artifact {s.artifact_id}, got {artifact_id}"
        )


def test_replace_report_null_space_404(engine, set_space, monkeypatch):
    """A null-space ``user`` gets the gate's 404 — never the 500 ``tenant_session`` would raise."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _null_space_user(),
        "delivered",
        link_report=True,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/report/replace",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id, recipients=False),
            headers=_HDR,
        )
        _assert_denied(resp, "POST /report/replace (null space)")


def test_replace_report_superadmin_still_works(
    engine, set_space, monkeypatch, superadmin_engine
):
    """A superadmin still repoints the report; the status stays ``delivered`` (D-04/D-05)."""
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        "delivered",
        link_report=True,
        sa_engine=superadmin_engine,
    ) as s:
        resp = s.client().post(
            f"/intakes/{s.intake_id}/report/replace",
            json=_deliver_body(s.space_id, s.intake_id, s.member_id, recipients=False),
            headers=_HDR,
        )
        assert resp.status_code == 200, (
            f"a superadmin replace should be 200, got {resp.status_code} ({resp.text!r})"
        )
        status_db, artifact_id, _v, _r = _read_intake(
            engine, set_space, s.space_id, s.intake_id
        )
        assert status_db == "delivered", "replace must NOT change the status (D-04)"
        assert artifact_id is not None and artifact_id != s.artifact_id, (
            "replace must repoint final_report_artifact_id at a NEW artifact, got "
            f"{artifact_id} (original {s.artifact_id})"
        )


# ===========================================================================
# The structural audit — the gate is on all eight routes, in the RESOLVED tree
# ===========================================================================

#: The EXACT eight (23.1-CONTEXT.md § 1). Path templates are ``path_format`` shaped, i.e.
#: exactly what ``_flatten_routes`` yields. Deliberately NOT included, in either direction:
#: ``GET /intakes/{intake_id}/skill-runs/stream`` (absent from CONTEXT § 1's table AND from
#: the stay-open list — out of scope both ways, so it is left exactly as it was).
_GATED_VERBS = (
    ("GET", "/intakes/{intake_id}/members"),
    ("POST", "/intakes/{intake_id}/mail/validation"),
    ("POST", "/intakes/{intake_id}/mail/reminder"),
    ("POST", "/intakes/{intake_id}/mail/results"),
    ("POST", "/intakes/{intake_id}/mail/intake"),
    ("POST", "/intakes/{intake_id}/review"),
    ("POST", "/intakes/{intake_id}/deliver"),
    ("POST", "/intakes/{intake_id}/report/replace"),
)


def test_all_eight_operator_verbs_depend_on_the_shared_gate():
    """``gates.superadmin_gate`` is in the RESOLVED dependency tree of each of the eight.

    THE WALKERS ARE IMPORTED, NOT RE-DERIVED (D-23.1-14, measured on this tree against
    fastapi 0.141.1): ``app.routes`` holds 8 entries including lazy ``_IncludedRouter``
    placeholders, so the obvious ``[r for r in app.routes if r.path.startswith('/intakes')]``
    returns **ZERO** routes and an audit written that way is VACUOUSLY GREEN. Separately,
    include-level dependencies never reach ``route.dependant``, so a top-level read of the
    dependant would miss a router-level gate entirely.

    Identity is compared with ``is`` (the imported function OBJECT), never a name string: a
    name check passes on a lookalike local and fails on a legitimate re-export —
    ``research_routes`` imports this very object as ``_superadmin_gate``.

    THE POSITIVE SELF-CHECKS, so this cannot go green on an empty tree:
      1. the flattened ``/intakes`` inventory is non-empty and covers all eight targets;
      2. the gate is OBSERVED PRESENT on ``GET /intakes/research/runs/{run_id}/locate``, a
         route already known to carry it (plan 23.1-01 re-pointed the nine research call
         sites at the shared gate) — if the walker could not see a gate that IS there, the
         eight assertions below would be meaningless.
    """
    main = pytest.importorskip("app.main")
    from tests.test_client_surface_open import (  # noqa: E402 -- D-23.1-14: reuse, don't re-derive
        _flatten_routes,
        _resolved_dependency_calls,
    )

    superadmin_gate = gates.superadmin_gate
    flat = _flatten_routes(main.app.routes)

    intake_paths = {p for p, _r, _i in flat if p.startswith("/intakes")}
    assert len(intake_paths) > 0, (
        "the route walker found ZERO /intakes routes — FastAPI does not flatten "
        "include_router (D-23.1-14) and this audit would be vacuously green. Re-verify "
        "_flatten_routes before trusting anything below."
    )

    # SELF-CHECK 2 — the walker CAN see a gate that is genuinely present.
    known_gated = [
        (r, i)
        for p, r, i in flat
        if p == "/intakes/research/runs/{run_id}/locate"
        and "GET" in (getattr(r, "methods", None) or set())
    ]
    assert len(known_gated) == 1, (
        "the known-gated control route GET /intakes/research/runs/{run_id}/locate is not "
        f"mounted (found {len(known_gated)}); the self-check cannot run."
    )
    control_calls = _resolved_dependency_calls(*known_gated[0])
    assert any(call is superadmin_gate for call in control_calls), (
        "SELF-CHECK FAILED: superadmin_gate is NOT visible on a route that carries it "
        "(GET /intakes/research/runs/{run_id}/locate, gated by plan 23.1-01). The walker is "
        "blind, so the eight assertions below would pass by finding nothing. Resolved tree: "
        f"{[getattr(c, '__name__', repr(c)) for c in control_calls]}"
    )

    # The audit proper.
    missing = []
    checked = 0
    for method, path in _GATED_VERBS:
        targets = [
            (r, i)
            for p, r, i in flat
            if p == path and method in (getattr(r, "methods", None) or set())
        ]
        assert len(targets) == 1, (
            f"{method} {path} is mounted {len(targets)} times on the app (expected exactly "
            f"1) — 23.1-CONTEXT.md § 1 names it as an operator verb."
        )
        checked += 1
        calls = _resolved_dependency_calls(*targets[0])
        if not any(call is superadmin_gate for call in calls):
            missing.append(
                f"{method} {path} -> {[getattr(c, '__name__', repr(c)) for c in calls]}"
            )

    assert checked == 8, f"expected to audit exactly 8 operator verbs, audited {checked}"
    assert not missing, (
        "SEC-01 / D-23.1-02 VIOLATION: superadmin_gate is absent from the RESOLVED "
        "dependency tree of these operator verbs, so a role=user caller can still drive "
        f"them:\n  " + "\n  ".join(missing)
    )


def test_gate_is_declared_before_the_repo_on_every_gated_intake_route():
    """The ordering contract, pinned on the LIVE signatures rather than left to a comment.

    Mirrors ``test_superadmin_gate.test_every_gated_research_route_resolves_the_gate_before_
    the_repo`` for ``intake_router``. The gate's null-space 404 only wins because FastAPI
    resolves the signature IN ORDER and ``Depends(superadmin_gate)`` precedes
    ``Depends(get_tenant_repo)``. Reorder any one signature and that route starts answering a
    null-space user with the repo's 403 — an existence oracle, and a change no reviewer would
    read as a security edit.

    Asserted for EVERY intake route that depends on the gate, so a ninth gated verb inherits
    the check for free rather than needing someone to remember it.
    """
    import inspect

    from app.api.intake_routes import intake_router
    from app.db.session import get_tenant_repo

    checked = 0
    for route in intake_router.routes:
        params = list(inspect.signature(route.endpoint).parameters.values())
        gate_pos = next(
            (
                i
                for i, p in enumerate(params)
                if getattr(p.default, "dependency", None) is gates.superadmin_gate
            ),
            None,
        )
        if gate_pos is None:
            continue
        checked += 1
        repo_pos = next(
            (
                i
                for i, p in enumerate(params)
                if getattr(p.default, "dependency", None) is get_tenant_repo
            ),
            None,
        )
        if repo_pos is not None:
            assert gate_pos < repo_pos, (
                f"{route.path}: superadmin_gate must be declared BEFORE get_tenant_repo "
                f"(gate at {gate_pos}, repo at {repo_pos}) or a null-space user gets the "
                f"repo's 403 instead of the existence-hidden 404"
            )

    # Guards the guard: a rename or a refactor that stops the gate resolving here would
    # otherwise leave this test green while checking nothing.
    assert checked == 8, f"expected 8 gated intake routes, found {checked}"
