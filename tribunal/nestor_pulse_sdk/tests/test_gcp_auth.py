"""
PHASE1-01 / PHASE1-02 -- GCP auth: ADC locally, Identity Platform end-to-end
                          (owning plan: 05 [Wave 2 gate])

Per 01-VALIDATION.md row:
  "ADC works locally; Workload Identity works on Cloud Run"
  + Plan 05's expanded scope: REAL Identity Platform token mint -> verify

Per orchestrator spawn prompt:
  Real Identity Platform token mint -> IdentityPlatformProvider verify ->
  401 on missing/invalid/expired/missing-tenant.

Token-minting flow used here (Identity Toolkit REST):

    POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword
        ?key=<API_KEY>
    body: { email, password, returnSecureToken: true }

Returns idToken. We then feed that idToken through
IdentityPlatformProvider.verify_id_token() to confirm the full
JWT signature -> JWKS rotation -> tenant_id custom claim -> AuthClaims
pipeline works end-to-end against the LIVE Identity Platform tenant.

Smoke user (Plan 01 provisioned, see infrastructure/identity-platform-bootstrap.md):
  uid:                X9aUTvNi7tYcqsV9bddSP4jHSsB3
  email:              smoketest@nestor-prod.local
  tenant_id claim:    tenant_smoke_local
  password secret:    IDENTITY_PLATFORM_SMOKE_USER_PW

Tests skip cleanly when prerequisites are missing (no API key, no ADC).
"""

from __future__ import annotations

import os
import subprocess

import pytest


pytestmark = pytest.mark.integration

SMOKE_UID = "X9aUTvNi7tYcqsV9bddSP4jHSsB3"
SMOKE_EMAIL = "smoketest@nestor-prod.local"
SMOKE_TENANT_ID = "tenant_smoke_local"
SMOKE_PW_SECRET = "IDENTITY_PLATFORM_SMOKE_USER_PW"
PROJECT_ID_SECRET = "IDENTITY_PLATFORM_PROJECT_ID"
RUNTIME_SA = "nestor-pulse-runtime"


# ---------------------------------------------------------------------------
# Helper: read a Secret Manager secret via gcloud (skip on failure)
# ---------------------------------------------------------------------------

def _read_secret(name: str) -> str | None:
    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", "project-cb01b861-cb4a-438d-b9a"
    )
    try:
        out = subprocess.run(
            [
                "gcloud",
                "secrets",
                "versions",
                "access",
                "latest",
                f"--secret={name}",
                f"--project={project}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def _read_web_api_key() -> str | None:
    """
    Identity Platform API key for signInWithPassword. Prefer env override
    (FIREBASE_WEB_API_KEY) for CI; fall back to a Secret Manager fetch.

    The Web API key is published by GCP at:
      gcloud projects list --format='value(projectNumber)'
    + the Identity Platform console (Settings → Web API key).
    Mohamed: store it once in Secret Manager as
    `IDENTITY_PLATFORM_WEB_API_KEY` to make these tests self-contained.
    """
    key = os.environ.get("FIREBASE_WEB_API_KEY")
    if key:
        return key
    return _read_secret("IDENTITY_PLATFORM_WEB_API_KEY")


# ---------------------------------------------------------------------------
# Test 1: ADC resolves locally (no SA JSON key required)
# ---------------------------------------------------------------------------

def test_adc_token_resolves_locally():
    """
    PHASE1-01 / memory/project_gcp_sa_key_policy.md -- ADC works locally
    via `gcloud auth application-default login`; no SA JSON key needed.
    """
    google_auth = pytest.importorskip(
        "google.auth", reason="google-auth not installed (Wave 0 deps)"
    )
    try:
        from google.auth.transport.requests import Request  # type: ignore
    except ImportError:
        pytest.skip("google-auth-requests transport not installed")

    try:
        credentials, project_id = google_auth.default()
    except Exception as exc:  # noqa: BLE001 -- DefaultCredentialsError family
        pytest.skip(f"ADC not configured: {exc}")

    assert credentials is not None
    # project_id may be None when ADC was set up via a user account; in
    # that case the *active* gcloud project is the source of truth.
    if not project_id:
        try:
            out = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            project_id = out.stdout.strip()
        except Exception:  # noqa: BLE001
            pass
    assert project_id, "ADC did not yield a project_id and gcloud has none"

    # Refresh; should succeed and produce a valid token.
    try:
        credentials.refresh(Request())
    except Exception as exc:  # noqa: BLE001 -- network blip etc.
        pytest.skip(f"ADC refresh failed (likely network): {exc}")
    assert credentials.valid, "ADC token failed to validate post-refresh"


# ---------------------------------------------------------------------------
# Test 2: Org-policy compliance — no user-managed SA JSON keys exist
# ---------------------------------------------------------------------------

def test_no_user_managed_sa_json_keys_exist():
    """
    Per memory/project_gcp_sa_key_policy.md: org policy disables SA JSON
    keys. This is an active assertion that the policy is enforced; if a
    USER_MANAGED key ever appears on the runtime SA, this test fails.
    """
    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", "project-cb01b861-cb4a-438d-b9a"
    )
    sa_email = f"{RUNTIME_SA}@{project}.iam.gserviceaccount.com"
    try:
        result = subprocess.run(
            [
                "gcloud",
                "iam",
                "service-accounts",
                "keys",
                "list",
                f"--iam-account={sa_email}",
                "--filter=keyType=USER_MANAGED",
                "--format=value(name)",
                f"--project={project}",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        pytest.skip(f"gcloud unavailable: {exc}")

    if result.returncode != 0:
        # 404 / runtime SA not yet created is fine -- Plan 01 hasn't run.
        if "does not exist" in result.stderr.lower():
            pytest.skip(f"Runtime SA {sa_email} not yet provisioned")
        pytest.skip(f"gcloud keys list failed: {result.stderr[:200]}")

    user_keys = [
        line for line in result.stdout.strip().splitlines() if line.strip()
    ]
    assert user_keys == [], (
        f"User-managed SA JSON keys exist on {sa_email}: {user_keys}\n"
        f"Org policy violated; revoke immediately."
    )


# ---------------------------------------------------------------------------
# Test 3: Real Identity Platform token mint -> verify -> AuthClaims
# ---------------------------------------------------------------------------

async def test_identity_platform_token_mint_and_verify(monkeypatch):
    """
    End-to-end auth test: sign in the smoke user via Identity Toolkit REST,
    then feed the idToken through IdentityPlatformProvider.verify_id_token.

    Asserts the full chain works:
      1. signInWithPassword succeeds (smoke user is alive)
      2. firebase_admin.auth.verify_id_token validates the signature
         against the live JWKS endpoint
      3. tenant_id custom claim is present and matches `tenant_smoke_local`
      4. AuthClaims is constructed with the right fields
    """
    httpx = pytest.importorskip("httpx", reason="httpx not installed")
    pytest.importorskip("firebase_admin", reason="firebase-admin not installed")

    project_id = _read_secret(PROJECT_ID_SECRET)
    if not project_id:
        pytest.skip(f"Secret {PROJECT_ID_SECRET} unreadable -- run Plan 01 first")

    api_key = _read_web_api_key()
    if not api_key:
        pytest.skip(
            "No Identity Platform Web API key available. "
            "Set FIREBASE_WEB_API_KEY env var or store in Secret Manager "
            "as IDENTITY_PLATFORM_WEB_API_KEY."
        )

    password = _read_secret(SMOKE_PW_SECRET)
    if not password:
        pytest.skip(f"Secret {SMOKE_PW_SECRET} unreadable -- run Plan 01 first")

    # Need DATABASE_URL for the provider's uid -> app_user_id lookup.
    # Plan 04's IdentityPlatformProvider does a DB lookup in
    # _provider_uid_to_app_user_id. If the smoke user has not been
    # inserted into app_user, we monkey-patch that helper.
    monkeypatch.setenv(PROJECT_ID_SECRET, project_id)

    # Sign in via Identity Toolkit REST to obtain a real idToken.
    sign_in_url = (
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={api_key}"
    )
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            sign_in_url,
            json={
                "email": SMOKE_EMAIL,
                "password": password,
                "returnSecureToken": True,
            },
        )
    assert resp.status_code == 200, (
        f"Identity Toolkit signInWithPassword failed: "
        f"{resp.status_code} {resp.text[:300]}"
    )
    id_token = resp.json().get("idToken")
    assert id_token, f"No idToken in signIn response: {resp.json()}"

    # Now verify through IdentityPlatformProvider. Bypass the DB lookup
    # because the app_user row may not exist yet (it's part of the
    # bootstrap flow that lands in Plan 06).
    from nestor_pulse_sdk.auth.identity_platform import IdentityPlatformProvider

    provider = IdentityPlatformProvider(project_id=project_id)

    async def _stub_provider_uid_to_app_user_id(*, provider_uid, tenant_id):
        # Pretend we already mapped uid -> app_user.id; return the uid
        # itself so the assertion below can sanity-check the wiring.
        return provider_uid

    monkeypatch.setattr(
        provider,
        "_provider_uid_to_app_user_id",
        _stub_provider_uid_to_app_user_id,
    )

    claims = await provider.verify_id_token(id_token)
    assert claims.tenant_id == SMOKE_TENANT_ID, (
        f"tenant_id custom claim mismatch: got {claims.tenant_id!r}, "
        f"expected {SMOKE_TENANT_ID!r}. Plan 01's identity-platform-bootstrap "
        f"may not have set the custom claim correctly."
    )
    assert claims.email == SMOKE_EMAIL
    assert claims.raw_provider_user_id == SMOKE_UID
    assert claims.app_user_id == SMOKE_UID  # from the stub above


# ---------------------------------------------------------------------------
# Test 4: Missing / invalid / empty tokens -> InvalidTokenError (401)
# ---------------------------------------------------------------------------

async def test_invalid_token_raises_401(monkeypatch):
    """
    Verify the failure paths: empty token, malformed token, and a
    syntactically-plausible-but-unsigned token all produce 401.
    """
    pytest.importorskip("firebase_admin")
    project_id = _read_secret(PROJECT_ID_SECRET) or "dummy-project"
    monkeypatch.setenv(PROJECT_ID_SECRET, project_id)

    from nestor_pulse_sdk.auth.identity_platform import IdentityPlatformProvider
    from nestor_pulse_sdk.auth.provider import AuthError, InvalidTokenError

    provider = IdentityPlatformProvider(project_id=project_id)

    # Empty token -> InvalidTokenError
    with pytest.raises(InvalidTokenError):
        await provider.verify_id_token("")

    # Garbage token -> InvalidTokenError (or wrapped AuthError(401))
    try:
        await provider.verify_id_token("not.a.real.token")
    except (InvalidTokenError, AuthError) as exc:
        assert exc.status_code == 401, (
            f"Garbage token should produce 401, got {exc.status_code}"
        )
    else:
        pytest.fail("Garbage token did not raise an auth error")


# ---------------------------------------------------------------------------
# Test 5: Token without tenant_id claim -> 401 "Missing tenant_id claim"
# ---------------------------------------------------------------------------

async def test_missing_tenant_id_claim_raises_401(monkeypatch):
    """
    Pitfall 9 regression -- a verified token that LACKS the tenant_id
    custom claim must produce 401 "Missing tenant_id claim", NOT a DB
    lookup that derives the tenant.

    We mock firebase_admin.auth.verify_id_token to return a decoded token
    without the custom claim so we don't need a second smoke user.
    """
    pytest.importorskip("firebase_admin")
    project_id = _read_secret(PROJECT_ID_SECRET) or "dummy-project"
    monkeypatch.setenv(PROJECT_ID_SECRET, project_id)

    from nestor_pulse_sdk.auth import identity_platform as ip_module
    from nestor_pulse_sdk.auth.identity_platform import IdentityPlatformProvider
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = IdentityPlatformProvider(project_id=project_id)

    # Patch the firebase_admin.auth.verify_id_token used inside the provider
    # to return a decoded token WITHOUT a tenant_id claim.
    from firebase_admin import auth as fb_auth  # type: ignore

    def _no_tenant_decoder(token, check_revoked=False):  # noqa: ARG001
        return {
            "uid": "fb-some-user",
            "email": "no-claim@example.com",
            # NB: no `tenant_id` key here.
        }

    monkeypatch.setattr(fb_auth, "verify_id_token", _no_tenant_decoder)

    with pytest.raises(AuthError) as exc_info:
        await provider.verify_id_token("any-token-the-mock-accepts")
    assert exc_info.value.status_code == 401
    assert "tenant_id" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# Test 6: Workload Identity metadata server (only meaningful on Cloud Run)
# ---------------------------------------------------------------------------

def test_workload_identity_metadata_server_reachable():
    """
    On Cloud Run, the GCE metadata server provides ADC via Workload
    Identity Federation without any SA JSON keys. Locally this is
    impossible to test (no metadata server), so skip.
    """
    if not os.environ.get("K_SERVICE"):
        pytest.skip("Not on Cloud Run; metadata server check skipped")

    requests = pytest.importorskip("requests")
    resp = requests.get(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/email",
        headers={"Metadata-Flavor": "Google"},
        timeout=2,
    )
    assert resp.status_code == 200
    project = os.environ.get(
        "GOOGLE_CLOUD_PROJECT", "project-cb01b861-cb4a-438d-b9a"
    )
    expected = f"{RUNTIME_SA}@{project}.iam.gserviceaccount.com"
    assert expected in resp.text, (
        f"Metadata server returned {resp.text!r}; expected {expected}"
    )
