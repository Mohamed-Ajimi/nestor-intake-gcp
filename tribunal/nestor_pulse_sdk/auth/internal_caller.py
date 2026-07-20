"""
InternalCallerProvider + get_internal_claims -- the Phase 14 (SEAM-01) seam.

The Tribunal API is a strictly-internal engine. The ONLY authenticated caller
is the intake backend, which reaches Tribunal over a server-to-server HTTPS
seam carrying a Google-signed OIDC ID token (D-04 inner gate) plus three
headers that forward the tenant (= intake space_id) and the acting superadmin
(the human, D-05).

Two responsibilities, kept separate:

  1. `InternalCallerProvider.verify_id_token(token)` -- the AuthProvider impl
     installed at `set_auth_provider()` (deps.py:37). It validates the CALLER
     only: `google.oauth2.id_token.verify_oauth2_token` checks the token's
     audience == this Tribunal service URL and signature/expiry, then this
     provider asserts the decoded caller email == the intake runtime SA and
     `email_verified` is truthy. On success it returns a CALLER-VERIFIED
     placeholder AuthClaims (tenant/user come from headers, filled in by
     `get_internal_claims`). On failure it raises AuthError (401 bad token,
     403 wrong/unverified caller).

  2. `get_internal_claims(request)` -- a thin FastAPI dependency installed via
     `app.dependency_overrides[get_current_user]` (mirroring the LOCAL_DEV_AUTH
     override in server.py). It parses the bearer token, drives the installed
     provider's `verify_id_token` to validate the caller, then reads the three
     seam headers and maps them into the EXISTING AuthClaims fields:

         X-Nestor-Tenant-Id   -> tenant_id   (== space_id, identity mapping)
         X-Acting-User-Id     -> app_user_id (the human, D-05)
         X-Acting-User-Email  -> email       (the human, D-05)
         (constant)           -> raw_provider_user_id = "intake-seam"

     NO new or renamed AuthClaims field is introduced -- the audit chain's
     frozen `canonical_json` payload must not change shape (D-05 hard
     constraint; T-14-04).

Security notes:
  - T-14-01/02 (Spoofing/Elevation): a forged or browser-minted token fails
    `verify_oauth2_token` (wrong aud/sig) or the caller-email check; the
    in-app OIDC re-verification is the inner gate that does not trust IAM
    alone (D-04).
  - T-14-03 (Tampering): tenant_id is read ONLY from the verified internal
    caller's header; a request missing `X-Nestor-Tenant-Id` is rejected with
    HTTP 400 BEFORE any tenant is trusted and before `get_db_session` can run
    an RLS query on an unset context.

References:
  - auth/provider.py -- AuthProvider ABC + frozen AuthClaims + AuthError
  - auth/deps.py -- set_auth_provider (line 37), get_current_user (bearer parse)
  - 14-RESEARCH.md Pattern 1, Pitfall 4 (aud without path), Pitfall 6 (header
    threading), Code Examples (verify core)
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from starlette.concurrency import run_in_threadpool

from google.auth.transport import requests as ga_requests
from google.oauth2 import id_token as ga_id_token

from nestor_pulse_sdk.auth.provider import AuthClaims, AuthError, AuthProvider


# ---------------------------------------------------------------------------
# Seam header names -- MUST match the intake client (Plan 02) verbatim.
# ---------------------------------------------------------------------------

HEADER_TENANT_ID = "X-Nestor-Tenant-Id"      # == space_id (identity mapping)
HEADER_ACTING_USER_ID = "X-Acting-User-Id"   # the human (D-05)
HEADER_ACTING_USER_EMAIL = "X-Acting-User-Email"  # the human (D-05)

# Sentinel stamped into raw_provider_user_id for every seam call. Distinguishes
# internal-caller claims from a real IdP subject in any audit review.
SEAM_PROVIDER_MARKER = "intake-seam"


class InternalCallerProvider(AuthProvider):
    """Trusts ONLY the intake backend.

    Verifies the Google-signed OIDC token (audience = this Tribunal service URL,
    caller email = intake runtime SA), then -- in the paired `get_internal_claims`
    dependency -- reads tenant + acting-user from headers into the EXISTING
    AuthClaims fields (D-05: no new/renamed field; the audit canonical_json is
    frozen).
    """

    def __init__(self, service_url: str, allowed_caller_email: str) -> None:
        # audience = the Tribunal service URL WITHOUT a path (Pitfall 4).
        self._aud = service_url
        # the intake runtime SA email, e.g. nestor-run@<project>.iam.gserviceaccount.com
        self._caller = allowed_caller_email
        # Construct the google-auth transport once; reused per verification.
        self._transport = ga_requests.Request()

    async def verify_id_token(self, token: str) -> AuthClaims:
        """Validate the CALLER (the intake backend), not the human.

        Raises:
            AuthError(401): token invalid (bad audience, signature, or expiry).
            AuthError(403): token valid but caller is not the intake SA, or the
                caller email is not verified.

        Returns a caller-verified placeholder AuthClaims. The tenant + acting
        user are threaded from headers by `get_internal_claims`; this method
        never trusts a tenant from the token itself.
        """
        try:
            # WR-02: verify_oauth2_token performs a SYNCHRONOUS HTTPS fetch of
            # Google's public certs on every call (google-auth's requests-based
            # transport, no cross-call cert cache). Run it on the starlette
            # threadpool so a slow cert fetch can never stall the event loop
            # (and with it every in-flight request incl. health probes).
            info: dict[str, Any] = await run_in_threadpool(
                ga_id_token.verify_oauth2_token, token, self._transport, self._aud
            )
        except Exception as exc:  # ValueError on bad aud/sig/expiry
            raise AuthError(
                "invalid internal caller token", status_code=401
            ) from exc

        if info.get("email") != self._caller or not info.get("email_verified"):
            raise AuthError(
                "caller is not the intake backend", status_code=403
            )

        # Caller verified. Identity (tenant + human) comes from headers; return
        # a placeholder that get_internal_claims replaces. Using the frozen
        # field shape guarantees no downstream code sees a novel field.
        return AuthClaims(
            app_user_id="",
            tenant_id="",
            email="",
            raw_provider_user_id=SEAM_PROVIDER_MARKER,
        )

    async def lookup_user(self, app_user_id: str) -> "AuthClaims | None":
        # Unused in the seam -- the intake backend owns users.
        return None

    async def sign_out(self, app_user_id: str) -> None:
        # Unused in the seam -- stateless per-request OIDC, no sessions.
        return None


def _parse_bearer(request: Request) -> str:
    """Extract the bearer token (split-max-1 pattern, mirrors orgs/api.py)."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise AuthError("Missing or malformed Authorization header", status_code=401)
    parts = auth_header.split(None, 1)
    if len(parts) < 2:
        raise AuthError("Missing or malformed Authorization header", status_code=401)
    token = parts[1].strip()
    if not token:
        raise AuthError("Missing or malformed Authorization header", status_code=401)
    return token


async def get_internal_claims(request: Request) -> AuthClaims:
    """Header-reading dependency for the internal seam (Pitfall 6).

    Installed via `app.dependency_overrides[get_current_user] = get_internal_claims`
    so every route that depends on the current user (incl. `get_db_session`, which
    sets `app.tenant_id` for RLS) transparently gets the verified internal claims.

    Flow:
      1. Parse the bearer OIDC token.
      2. Validate the CALLER via the installed InternalCallerProvider.
      3. Read the three seam headers; the tenant header is REQUIRED -- a missing
         `X-Nestor-Tenant-Id` raises AuthError(400) before any tenant is trusted
         (T-14-03), i.e. before an RLS query can run on an unset context.
      4. Map into the EXISTING AuthClaims fields (D-05 -- no new field).
    """
    from nestor_pulse_sdk.auth.deps import get_auth_provider  # avoid import cycle

    token = _parse_bearer(request)

    provider = get_auth_provider()
    # Caller validation (aud + caller email + email_verified). Raises 401/403.
    await provider.verify_id_token(token)

    tenant_id = request.headers.get(HEADER_TENANT_ID)
    if not tenant_id:
        # PINNED status 400: a missing required header from an authenticated
        # internal caller is a malformed request, not an auth failure. Plan 03's
        # denial test asserts this exact code.
        raise AuthError(
            f"missing required {HEADER_TENANT_ID} header", status_code=400
        )

    acting_user_id = request.headers.get(HEADER_ACTING_USER_ID, "")
    acting_email = request.headers.get(HEADER_ACTING_USER_EMAIL, "")

    claims = AuthClaims(
        app_user_id=acting_user_id,
        tenant_id=tenant_id,
        email=acting_email,
        raw_provider_user_id=SEAM_PROVIDER_MARKER,
    )
    # Make claims discoverable to downstream middleware (audit binding) on the
    # same request, mirroring get_current_user's request.state stash.
    request.state.user = claims  # type: ignore[attr-defined]
    return claims
