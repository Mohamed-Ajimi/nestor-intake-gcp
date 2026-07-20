"""
Phase 14 (SEAM-01) Task 2 -- InternalCallerProvider + get_internal_claims.

Owning plan: 14-01 Task 2 (TDD).

The Tribunal API is now a strictly-internal engine. The ONLY authenticated
caller is the intake backend, identified by a Google-signed OIDC ID token
whose audience is this Tribunal service URL and whose caller email is the
intake runtime SA (D-04 inner gate). The acting superadmin (the human) is
forwarded via headers and mapped into the EXISTING AuthClaims fields
(app_user_id / email) -- NO new or renamed field (D-05, frozen audit chain).

Behaviors covered (14-01-PLAN.md Task 2 <behavior>):
  1. accept: valid caller token + three headers -> AuthClaims mapped correctly,
     raw_provider_user_id == "intake-seam".
  2. wrong-SA: decoded email != intake SA -> AuthError(403).
  3. bad token: verify_oauth2_token raises ValueError -> AuthError(401).
  4. missing X-Nestor-Tenant-Id header -> AuthError(400)  [status PINNED: 400].
  4b. present-but-non-UUID X-Nestor-Tenant-Id -> AuthError(400)  [WR-03, same
      pinned malformed-request class, validated BEFORE claims are constructed].
  5. email_verified missing/false -> AuthError(403).

google.oauth2.id_token.verify_oauth2_token is mocked (no network) so the
suite runs in the keyless Cloud Build env.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

# The seam provider imports google.auth transitively (via google-cloud-storage).
# If google.oauth2.id_token is not importable in this env, skip cleanly rather
# than error at collection -- mirrors the sibling suites' importorskip guards.
pytest.importorskip(
    "google.oauth2.id_token",
    reason="google-auth (id_token) not importable in this env",
)

pytestmark = pytest.mark.asyncio


_AUD = "https://tribunal-api-xxxx.run.app"
_INTAKE_SA = "nestor-run@my-project.iam.gserviceaccount.com"
_SPACE_ID = "5b0b574f-0000-0000-0000-000000000001"
_ACTING_ID = "260563e6-0000-0000-0000-000000000002"
_ACTING_EMAIL = "superadmin@agenic.be"

_VERIFY = "nestor_pulse_sdk.auth.internal_caller.ga_id_token.verify_oauth2_token"


def _make_provider():
    from nestor_pulse_sdk.auth.internal_caller import InternalCallerProvider

    return InternalCallerProvider(service_url=_AUD, allowed_caller_email=_INTAKE_SA)


class _FakeRequest:
    """Minimal stand-in for starlette Request -- only .headers is read."""

    def __init__(self, headers: dict[str, str]):
        # starlette Headers are case-insensitive; a plain dict with the exact
        # casing the client sends is enough for the provider's .get() calls.
        self.headers = _CIHeaders(headers)
        self.state = _State()


class _CIHeaders:
    def __init__(self, data: dict[str, str]):
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, key: str, default=None):
        return self._data.get(key.lower(), default)


class _State:
    pass


def _headers(**overrides) -> dict[str, str]:
    base = {
        "Authorization": "Bearer fake-oidc-token",
        "X-Nestor-Tenant-Id": _SPACE_ID,
        "X-Acting-User-Id": _ACTING_ID,
        "X-Acting-User-Email": _ACTING_EMAIL,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# 1. Accept: valid caller + three headers -> correctly mapped AuthClaims
# ---------------------------------------------------------------------------

async def test_accept_maps_headers_into_existing_claim_fields():
    from nestor_pulse_sdk.auth.deps import set_auth_provider
    from nestor_pulse_sdk.auth.internal_caller import get_internal_claims
    from nestor_pulse_sdk.auth.provider import AuthClaims

    provider = _make_provider()
    set_auth_provider(provider)

    decoded = {"email": _INTAKE_SA, "email_verified": True, "aud": _AUD}
    with patch(_VERIFY, return_value=decoded):
        claims = await get_internal_claims(_FakeRequest(_headers()))

    assert isinstance(claims, AuthClaims)
    assert claims.tenant_id == _SPACE_ID          # X-Nestor-Tenant-Id
    assert claims.app_user_id == _ACTING_ID       # X-Acting-User-Id (the human)
    assert claims.email == _ACTING_EMAIL          # X-Acting-User-Email (the human)
    assert claims.raw_provider_user_id == "intake-seam"


# ---------------------------------------------------------------------------
# 2. Wrong-SA: decoded email != intake SA -> 403
# ---------------------------------------------------------------------------

async def test_wrong_caller_email_raises_403():
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = _make_provider()
    decoded = {"email": "attacker@evil.example", "email_verified": True}
    with patch(_VERIFY, return_value=decoded):
        with pytest.raises(AuthError) as ei:
            await provider.verify_id_token("fake-oidc-token")
    assert ei.value.status_code == 403


# ---------------------------------------------------------------------------
# 3. Bad token: verify_oauth2_token raises ValueError -> 401
# ---------------------------------------------------------------------------

async def test_bad_token_raises_401():
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = _make_provider()
    with patch(_VERIFY, side_effect=ValueError("bad aud/sig/expiry")):
        with pytest.raises(AuthError) as ei:
            await provider.verify_id_token("fake-oidc-token")
    assert ei.value.status_code == 401


# ---------------------------------------------------------------------------
# 4. Missing X-Nestor-Tenant-Id header -> 400 (status PINNED for Plan 03)
# ---------------------------------------------------------------------------

async def test_missing_tenant_header_raises_before_any_tenant_trusted():
    from nestor_pulse_sdk.auth.deps import set_auth_provider
    from nestor_pulse_sdk.auth.internal_caller import get_internal_claims
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = _make_provider()
    set_auth_provider(provider)

    hdrs = _headers()
    del hdrs["X-Nestor-Tenant-Id"]

    decoded = {"email": _INTAKE_SA, "email_verified": True}
    with patch(_VERIFY, return_value=decoded):
        with pytest.raises(AuthError) as ei:
            await get_internal_claims(_FakeRequest(hdrs))
    # PINNED: 400 -- a missing required header from an authenticated internal
    # caller is a malformed request, not an auth failure. Plan 03 must match.
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# 4b. Present-but-non-UUID X-Nestor-Tenant-Id -> 400 (WR-03)
# ---------------------------------------------------------------------------

async def test_malformed_tenant_header_raises_400_before_claims():
    from nestor_pulse_sdk.auth.deps import set_auth_provider
    from nestor_pulse_sdk.auth.internal_caller import get_internal_claims
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = _make_provider()
    set_auth_provider(provider)

    hdrs = _headers(**{"X-Nestor-Tenant-Id": "not-a-uuid"})

    decoded = {"email": _INTAKE_SA, "email_verified": True}
    with patch(_VERIFY, return_value=decoded):
        with pytest.raises(AuthError) as ei:
            await get_internal_claims(_FakeRequest(hdrs))
    # WR-03: malformed tenant is the same pinned malformed-request class as the
    # missing-header case — EXACTLY 400, raised BEFORE claims are constructed.
    assert ei.value.status_code == 400


# ---------------------------------------------------------------------------
# 5. email_verified missing/false -> 403
# ---------------------------------------------------------------------------

async def test_email_not_verified_raises_403():
    from nestor_pulse_sdk.auth.provider import AuthError

    provider = _make_provider()
    decoded = {"email": _INTAKE_SA, "email_verified": False}
    with patch(_VERIFY, return_value=decoded):
        with pytest.raises(AuthError) as ei:
            await provider.verify_id_token("fake-oidc-token")
    assert ei.value.status_code == 403

    decoded_missing = {"email": _INTAKE_SA}  # no email_verified key at all
    with patch(_VERIFY, return_value=decoded_missing):
        with pytest.raises(AuthError) as ei2:
            await provider.verify_id_token("fake-oidc-token")
    assert ei2.value.status_code == 403


# ---------------------------------------------------------------------------
# 6. No new/renamed AuthClaims field (D-05 audit-chain guard)
# ---------------------------------------------------------------------------

async def test_authclaims_shape_is_frozen():
    """The seam MUST NOT introduce a new AuthClaims field (frozen canonical_json)."""
    import dataclasses

    from nestor_pulse_sdk.auth.provider import AuthClaims

    field_names = {f.name for f in dataclasses.fields(AuthClaims)}
    assert field_names == {
        "app_user_id",
        "tenant_id",
        "email",
        "raw_provider_user_id",
    }, field_names
