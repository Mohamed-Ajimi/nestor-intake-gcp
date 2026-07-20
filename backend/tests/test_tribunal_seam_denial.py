"""Seam-level cross-tenant DENIAL suite (SEAM-02 / D-08) — the intake-side CI gate.

Proves the intake -> Tribunal HTTP seam rejects every unauthorized / malformed caller
BEFORE any unset-GUC RLS query can run, and that the GUC-name-mismatch firewall
(``app.current_space_id`` intake-side vs ``app.tenant_id`` tribunal-side) cannot leak a
space across the boundary. The seam is HTTP-only with NO shared DB session, so the tenant
comes solely from the verified ``X-Nestor-Tenant-Id`` header (Pitfall 1/2 firewall).

This file drives the REAL Tribunal seam provider under test — it mounts the actual
``get_internal_claims`` dependency (which drives the installed ``InternalCallerProvider``)
plus the two real ``/api/orgs/ensure`` + ``/api/projects/ensure`` endpoints, over a FastAPI
``TestClient``. It does NOT substitute a stand-in router: the denial paths exercise the
production provider logic verbatim. Only two boundaries are faked:

  * ``google.oauth2.id_token.verify_oauth2_token`` is mocked to fabricate the decoded caller
    claims per case (the OIDC verify is the one boundary that cannot run locally — mirrors
    how ``test_intake_cross_tenant.py`` overrides ``get_current_identity`` for the IdP).
  * ``get_db_session`` is overridden with a recording fake so the auth/claims boundary can
    be proven WITHOUT a live Postgres (the denial cases all fire in ``get_internal_claims``
    before ``get_db_session`` runs; the guc_leak case asserts the tenant handed to the DB
    context is EXACTLY the verified header value and nothing else).

What each case proves (EXACT status codes — each asserts one pinned code, never a
membership check across multiple codes):

| Test (``-k`` selector)     | Proves                                                       |
|----------------------------|-------------------------------------------------------------|
| ``missing_tenant``         | valid caller token, NO ``X-Nestor-Tenant-Id`` -> EXACTLY    |
|                            | 400 (the PINNED code, 14-01-SUMMARY) BEFORE any tenant is   |
|                            | trusted; no space-B data returned, no foreign id in body.   |
| ``wrong_sa``               | ``verify_oauth2_token`` email != intake SA -> EXACTLY 403.  |
| ``unauth``                 | no ``Authorization`` bearer header -> EXACTLY 401.          |
| ``guc_leak``               | a request carrying space-A's tenant header can NEVER cause  |
|                            | a space-B tenant context — the DB context is set to EXACTLY |
|                            | the verified header value (the GUC-leak firewall, T-14-09). |

Skip-clean (dev-box discipline): ``pytestmark = pytest.mark.integration``; every heavy
import is guarded with ``pytest.importorskip`` (``fastapi``, ``httpx``, ``google.oauth2``,
and the Tribunal ``internal_caller`` / ``deps`` / ``orgs.api`` modules) so the file COLLECTS
on a box without Docker or the Tribunal deps. It runs under ``pytest backend/tests -m
integration`` in ``cloudbuild.test.yaml``.

Analog: ``backend/tests/test_intake_cross_tenant.py`` (TestClient + dependency_overrides,
EXACT-status discipline, ``_cleanup`` teardown) and the Tribunal-side unit suite
``tribunal/nestor_pulse_sdk/tests/test_internal_caller.py`` (verify_oauth2_token mocking).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Skip-clean guards — the file must COLLECT on the dev box without erroring.
# The Tribunal SDK (nestor_pulse_sdk.*) lives under tribunal/ and is on the
# path only in the Cloud Build test image; google.auth is transitive there.
# ---------------------------------------------------------------------------
pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient transport
pytest.importorskip("google.oauth2.id_token")

# The intake-side client whose header contract the seam consumes (Plan 02). Guarded so a
# box missing its deps skips rather than errors (mirrors the sibling intake suites).
pytest.importorskip("app.research.tribunal_client")

# The REAL Tribunal seam provider + dependency + endpoints under test (Plan 01).
internal_caller = pytest.importorskip("nestor_pulse_sdk.auth.internal_caller")
auth_deps = pytest.importorskip("nestor_pulse_sdk.auth.deps")
orgs_api = pytest.importorskip("nestor_pulse_sdk.orgs.api")
auth_middleware = pytest.importorskip("nestor_pulse_sdk.auth.middleware")
auth_provider = pytest.importorskip("nestor_pulse_sdk.auth.provider")

from unittest.mock import patch  # noqa: E402 -- after importorskip guards

InternalCallerProvider = internal_caller.InternalCallerProvider
get_internal_claims = internal_caller.get_internal_claims
HEADER_TENANT_ID = internal_caller.HEADER_TENANT_ID
HEADER_ACTING_USER_ID = internal_caller.HEADER_ACTING_USER_ID
HEADER_ACTING_USER_EMAIL = internal_caller.HEADER_ACTING_USER_EMAIL

set_auth_provider = auth_deps.set_auth_provider
get_current_user = auth_deps.get_current_user
get_db_session = auth_deps.get_db_session

AuthError = auth_provider.AuthError
auth_exception_handler = auth_middleware.auth_exception_handler


# The dotted path to the verify function the provider imports (patched per case).
_VERIFY = "nestor_pulse_sdk.auth.internal_caller.ga_id_token.verify_oauth2_token"

# The seam audience + the ONE trusted caller (the intake runtime SA). A decoded caller
# email != this value is the wrong-SA case; a forged/browser token fails verify entirely.
_AUD = "https://tribunal-api-xxxx.run.app"
_INTAKE_SA = "nestor-run@my-project.iam.gserviceaccount.com"
_WRONG_SA = "attacker@evil.example"

# Two distinct spaces — the firewall must never let space-A's header surface space-B.
_SPACE_A = str(uuid.uuid4())
_SPACE_B = str(uuid.uuid4())

_ACTING_ID = str(uuid.uuid4())
_ACTING_EMAIL = "superadmin@agenic.be"


# ---------------------------------------------------------------------------
# Recording fake session — proves the DB tenant context equals the verified
# header value and nothing else (the guc_leak firewall), with no live Postgres.
# ---------------------------------------------------------------------------


class _RecordingSession:
    """Minimal AsyncSession stand-in that records the tenant handed to it.

    ``ensure_org`` calls ``session.get(Org, uuid)`` then ``session.flush()`` +
    ``set_tenant_context(session, tenant)``; ``set_tenant_context`` issues
    ``SELECT set_config('app.tenant_id', :tid, true)`` via ``session.execute``. We capture
    the ``:tid`` bind so the test can assert the DB context == the verified header tenant
    (never a foreign space). Every method is async to match the real session surface.
    """

    def __init__(self) -> None:
        self.tenant_contexts: list[str] = []

    async def get(self, _model, _pk):
        # Pretend the Org already exists (no INSERT path); ensure_org then just
        # flushes + sets the tenant context, which is the security-relevant step.
        return object()

    async def flush(self) -> None:
        return None

    async def execute(self, statement, params=None):
        # set_tenant_context binds {"tid": "<tenant>"}. Record it.
        if params and "tid" in params:
            self.tenant_contexts.append(params["tid"])
        return _EmptyResult()


class _EmptyResult:
    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return None


# ---------------------------------------------------------------------------
# App builder — the REAL seam wiring (mirrors server.py's deployed branch)
# ---------------------------------------------------------------------------


def _build_app(recorder: "_RecordingSession | None" = None):
    """Build a FastAPI app carrying the REAL seam: provider + get_internal_claims + endpoints.

    Mirrors ``server.py``'s deployed-mode wiring (``set_auth_provider(InternalCallerProvider)``
    + ``dependency_overrides[get_current_user] = get_internal_claims`` + the orgs /ensure
    router + the AuthError -> JSON handler) WITHOUT booting the whole app. The surface under
    test is the seam, not the app lifecycle.

    ``get_db_session`` is overridden with a recording fake so the endpoints reach the handler
    WITHOUT a live Postgres — the denial cases never get that far, and the guc_leak case reads
    the recorder to prove the tenant context is exactly the verified header value.
    """
    from fastapi import FastAPI

    provider = InternalCallerProvider(
        service_url=_AUD, allowed_caller_email=_INTAKE_SA
    )
    set_auth_provider(provider)

    app = FastAPI()
    app.add_exception_handler(AuthError, auth_exception_handler)
    app.include_router(orgs_api.router)

    # The deployed override: every route (incl. get_db_session) reads verified claims.
    app.dependency_overrides[get_current_user] = get_internal_claims

    async def _fake_db_session():
        # Yield the recorder (or a throwaway) so ensure_org/ensure_project run without a DB.
        yield recorder if recorder is not None else _RecordingSession()

    app.dependency_overrides[get_db_session] = _fake_db_session
    return app


def _headers(**overrides) -> dict[str, str]:
    """Full valid seam header set; override/remove per case."""
    base = {
        "Authorization": "Bearer fake-oidc-token",
        HEADER_TENANT_ID: _SPACE_A,
        HEADER_ACTING_USER_ID: _ACTING_ID,
        HEADER_ACTING_USER_EMAIL: _ACTING_EMAIL,
    }
    base.update(overrides)
    return base


def _cleanup(app) -> None:
    """Teardown discipline (mirrors test_intake_cross_tenant._cleanup_spaces)."""
    app.dependency_overrides.clear()


# ===========================================================================
# Case: missing_tenant — valid caller, NO X-Nestor-Tenant-Id -> EXACTLY 400
# ===========================================================================


def test_missing_tenant_header_returns_exactly_400_no_foreign_body():
    """Valid caller token but NO ``X-Nestor-Tenant-Id`` -> EXACTLY 400 (PINNED).

    The rejection fires in ``get_internal_claims`` BEFORE any tenant is trusted and before
    ``get_db_session`` can run an RLS query on an unset context (T-14-03). 400 (not 401/403)
    because a missing required header from an already-authenticated internal caller is a
    malformed request, not an auth failure — the code PINNED in 14-01-SUMMARY. No space-B
    data is returned and the body leaks no foreign id.
    """
    from fastapi.testclient import TestClient

    app = _build_app()
    try:
        hdrs = _headers()
        del hdrs[HEADER_TENANT_ID]

        decoded = {"email": _INTAKE_SA, "email_verified": True, "aud": _AUD}
        with patch(_VERIFY, return_value=decoded):
            client = TestClient(app)
            resp = client.post("/api/orgs/ensure", headers=hdrs)

        # EXACT 400 — the PINNED missing-tenant code; a single-code assertion only.
        assert resp.status_code == 400, (
            f"missing X-Nestor-Tenant-Id must be EXACTLY 400 (PINNED, 14-01-SUMMARY), "
            f"got {resp.status_code} (body={resp.text!r})."
        )
        # No foreign space id leaks into the error body.
        body = resp.text
        assert _SPACE_B not in body, "400 body leaked a foreign space id."
    finally:
        _cleanup(app)


# ===========================================================================
# Case: wrong_sa — decoded caller email != intake SA -> EXACTLY 403
# ===========================================================================


def test_wrong_sa_caller_returns_exactly_403():
    """A verified OIDC token whose caller email != the intake SA -> EXACTLY 403.

    ``verify_oauth2_token`` succeeds (good aud/sig) but the decoded ``email`` is not the
    trusted intake runtime SA, so ``InternalCallerProvider.verify_id_token`` raises
    AuthError(403). This is the spoofing/elevation gate (T-14-11) — a non-intake caller that
    somehow reaches the service is rejected. EXACTLY 403 — a single pinned code.
    """
    from fastapi.testclient import TestClient

    app = _build_app()
    try:
        decoded = {"email": _WRONG_SA, "email_verified": True, "aud": _AUD}
        with patch(_VERIFY, return_value=decoded):
            client = TestClient(app)
            resp = client.post("/api/orgs/ensure", headers=_headers())

        assert resp.status_code == 403, (
            f"wrong-SA caller must be EXACTLY 403, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert _SPACE_B not in resp.text, "403 body leaked a foreign space id."
    finally:
        _cleanup(app)


# ===========================================================================
# Case: unauthenticated — no Authorization bearer -> EXACTLY 401
# ===========================================================================


def test_unauthenticated_no_bearer_returns_exactly_401():
    """No ``Authorization`` bearer header -> EXACTLY 401 (before any tenant is read).

    ``get_internal_claims`` -> ``_parse_bearer`` raises AuthError(401) when the Authorization
    header is missing/malformed, BEFORE the tenant header is even inspected. EXACTLY 401 —
    the unauthenticated code is distinct from the malformed-request 400 and the wrong-caller
    403 so no status collision blurs the denial reason.
    """
    from fastapi.testclient import TestClient

    app = _build_app()
    try:
        hdrs = _headers()
        del hdrs["Authorization"]  # no bearer at all

        # verify_oauth2_token must NEVER be reached; patch it to blow up if it is.
        with patch(_VERIFY, side_effect=AssertionError("verify must not run without a bearer")):
            client = TestClient(app)
            resp = client.post("/api/orgs/ensure", headers=hdrs)

        assert resp.status_code == 401, (
            f"unauthenticated (no bearer) must be EXACTLY 401, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert _SPACE_B not in resp.text, "401 body leaked a foreign space id."
    finally:
        _cleanup(app)


# ===========================================================================
# Case: guc_leak — space-A header never causes a space-B tenant context
# ===========================================================================


def test_guc_leak_firewall_tenant_context_is_exactly_the_header_value():
    """A request carrying space-A's tenant header can NEVER surface space-B (T-14-09).

    The seam is HTTP-only with NO shared DB session between intake and Tribunal, so the tenant
    is derived SOLELY from the verified ``X-Nestor-Tenant-Id`` header — the GUC-name mismatch
    (intake ``app.current_space_id`` vs tribunal ``app.tenant_id``) cannot bridge the boundary.
    This asserts the firewall at the claims/DB-context layer: after a successful space-A seam
    call, the tenant handed to the DB context (``set_config('app.tenant_id', :tid, true)``) is
    EXACTLY ``_SPACE_A`` and space-B NEVER appears — proving a space-A header can only ever
    scope to space-A rows, never space-B's.
    """
    from fastapi.testclient import TestClient

    recorder = _RecordingSession()
    app = _build_app(recorder=recorder)
    try:
        decoded = {"email": _INTAKE_SA, "email_verified": True, "aud": _AUD}
        with patch(_VERIFY, return_value=decoded):
            client = TestClient(app)
            resp = client.post(
                "/api/orgs/ensure", headers=_headers(**{HEADER_TENANT_ID: _SPACE_A})
            )

        assert resp.status_code == 200, (
            f"a valid space-A seam call should succeed (200), got {resp.status_code} "
            f"(body={resp.text!r})."
        )

        # The response echoes the verified tenant — it MUST be space-A, never space-B.
        assert resp.json().get("tenant_id") == _SPACE_A, (
            f"seam returned tenant_id != the verified space-A header "
            f"(got {resp.json().get('tenant_id')!r})."
        )
        assert _SPACE_B not in resp.text, "GUC-LEAK: space-B id surfaced in a space-A call."

        # FIREWALL: the DB tenant context set for this request is EXACTLY space-A.
        assert recorder.tenant_contexts, (
            "ensure_org never set a DB tenant context — the firewall assertion is vacuous."
        )
        assert all(tid == _SPACE_A for tid in recorder.tenant_contexts), (
            f"GUC-LEAK: DB tenant context was set to something other than the verified "
            f"space-A header (contexts={recorder.tenant_contexts!r})."
        )
        assert _SPACE_B not in recorder.tenant_contexts, (
            "GUC-LEAK: space-B tenant context set from a space-A seam call."
        )
    finally:
        _cleanup(app)
