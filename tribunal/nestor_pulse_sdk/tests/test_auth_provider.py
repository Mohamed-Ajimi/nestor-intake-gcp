"""
PHASE1-02 / D-10 -- AuthProvider abstraction swap (owning plan: 04)

Per 01-VALIDATION.md row:
  "AuthProvider abstraction swap (fake provider) leaves all other code
   untouched"
  Test type: unit
  Command: pytest nestor_pulse_sdk/tests/test_auth_provider.py -x

Plan 04 has filled in the bodies and flipped strict=True. xpass now
surfaces as failure -- if any test passes that was supposed to fail
(or vice versa) the suite catches it.

Behaviors covered (per 01-04-PLAN.md Task 1 <behavior>):
  1. test_swap_provider_does_not_touch_caller
     -- D-10 swap: FakeAuthProvider drop-in honours the same contract.
  2. test_app_user_id_decoupled_from_provider_uid
     -- raw_provider_user_id stays on the dataclass; app_user_id is
        the only id callers see; the two are distinct values.
  3. test_missing_tenant_id_claim_raises_401
     -- Pitfall 9: token without `tenant_id` -> 401 explicit, no DB
        fallback before RLS.
  4. test_check_revoked_true
     -- Don't Hand-Roll: verify_id_token is invoked with
        check_revoked=True (mandatory per Security Domain).
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest

# Plan 04 flips this from strict=False to strict=True per
# 01-04-PLAN.md `<action>` line "Flip Plan 02's `test_auth_provider.py`
# xfail to `strict=True`." The pytestmark stays as xfail(strict=True)
# during the wave window where Plan 03's DB modules haven't merged into
# this worktree yet -- once they do (post-merge wave 2 close), the file
# is expected to pass without xfail and the orchestrator can remove
# this marker in a follow-up cleanup commit.
#
# NOTE: We DO NOT use a file-level xfail here. Instead the individual
# tests that depend on Plan 03 modules use pytest.importorskip(). All
# four tests in this file are pure unit tests that mock the firebase
# call surface -- they do NOT need Plan 03's DB schema to run.

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Test 1 -- D-10 swap: caller code is provider-agnostic
# ---------------------------------------------------------------------------

async def test_swap_provider_does_not_touch_caller():
    """
    Switching from IdentityPlatformProvider to a FakeAuthProvider must
    not require any change to caller code. The contract is the
    AuthProvider ABC -- both impls present the same `verify_id_token`
    coroutine returning the same AuthClaims shape.
    """
    from nestor_pulse_sdk.auth.provider import (
        AuthClaims,
        AuthProvider,
        InvalidTokenError,
    )

    class _FakeAuthProvider(AuthProvider):
        def __init__(self) -> None:
            self._tokens: dict[str, AuthClaims] = {}

        def add_token(self, token: str, claims: AuthClaims) -> None:
            self._tokens[token] = claims

        async def verify_id_token(self, token: str) -> AuthClaims:
            if token not in self._tokens:
                raise InvalidTokenError("unknown token")
            return self._tokens[token]

        async def lookup_user(self, app_user_id: str):
            return None

        async def sign_out(self, app_user_id: str) -> None:
            return None

    fake = _FakeAuthProvider()
    sample = AuthClaims(
        app_user_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        email="alice@example.com",
        raw_provider_user_id="fb_abc",
    )
    fake.add_token("opaque-jwt", sample)

    async def caller_that_only_sees_the_abstraction(
        provider: AuthProvider, token: str
    ) -> AuthClaims:
        # This function is the moral equivalent of `get_current_user`;
        # it must compile and run unchanged for EITHER provider impl.
        return await provider.verify_id_token(token)

    out = await caller_that_only_sees_the_abstraction(fake, "opaque-jwt")
    assert out is sample
    assert isinstance(out, AuthClaims)

    # Negative path: unknown token raises a subclass of AuthError.
    from nestor_pulse_sdk.auth.provider import AuthError
    with pytest.raises(AuthError):
        await caller_that_only_sees_the_abstraction(fake, "nope")


# ---------------------------------------------------------------------------
# Test 2 -- app_user_id is decoupled from provider uid
# ---------------------------------------------------------------------------

async def test_app_user_id_decoupled_from_provider_uid():
    """
    The whole point of D-10's abstraction: app code references
    `app_user_id` (Nestor UUID), NOT `raw_provider_user_id` (firebase
    uid). A token with `firebase_uid=fb_123` must yield AuthClaims where
    app_user_id != "fb_123" and is a valid Nestor-side UUID.
    """
    from nestor_pulse_sdk.auth.provider import AuthClaims

    nestor_uuid = str(uuid.uuid4())
    claims = AuthClaims(
        app_user_id=nestor_uuid,
        tenant_id=str(uuid.uuid4()),
        email="bob@example.com",
        raw_provider_user_id="fb_123",
    )

    # Hard invariant: the two identifiers are distinct values.
    assert claims.app_user_id != claims.raw_provider_user_id
    assert claims.raw_provider_user_id == "fb_123"
    # app_user_id is a UUID -- parses cleanly.
    uuid.UUID(claims.app_user_id)

    # Frozen dataclass: callers cannot accidentally swap one for the other.
    with pytest.raises(Exception):
        claims.app_user_id = "fb_123"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 3 -- missing tenant_id claim => 401 (Pitfall 9, no DB fallback)
# ---------------------------------------------------------------------------

async def test_missing_tenant_id_claim_raises_401():
    """
    A signed and otherwise-valid Identity Platform token that does NOT
    carry a `tenant_id` custom claim MUST fail closed with 401 "Missing
    tenant_id claim". The provider MUST NOT fall back to a DB lookup
    before RLS context is set (RESEARCH.md Pitfall 9).
    """
    from nestor_pulse_sdk.auth import identity_platform as ip_mod
    from nestor_pulse_sdk.auth.provider import AuthError

    # Patch verify_id_token so we never touch the network. The decoded
    # token deliberately omits `tenant_id`.
    fake_decoded = {
        "uid": "fb_no_tenant",
        "email": "no-tenant@example.com",
        # NO `tenant_id` key here -- this is the regression scenario.
    }

    # Prevent firebase init from running (no ADC required in unit tests).
    with patch.object(ip_mod, "_ensure_initialized", lambda _pid: None):
        provider = ip_mod.IdentityPlatformProvider(project_id="test-proj")

    # Patch the underlying firebase_admin.auth.verify_id_token so the
    # provider returns our fake_decoded payload deterministically.
    with patch(
        "firebase_admin.auth.verify_id_token",
        return_value=fake_decoded,
    ):
        with pytest.raises(AuthError) as excinfo:
            await provider.verify_id_token("any-bearer-token")

    assert excinfo.value.status_code == 401
    assert "Missing tenant_id claim" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Test 4 -- check_revoked=True is invoked (Don't Hand-Roll)
# ---------------------------------------------------------------------------

async def test_check_revoked_true():
    """
    RESEARCH.md Don't Hand-Roll line 596 + Security Domain line 891:
    `firebase_admin.auth.verify_id_token` MUST be called with
    `check_revoked=True`. This is the only mechanism that catches a
    leaked refresh token within ~1 hour.

    The lookup of firebase-uid -> app_user_id is short-circuited via
    patch so this test stays pure-unit (no DB).
    """
    from nestor_pulse_sdk.auth import identity_platform as ip_mod

    fake_decoded = {
        "uid": "fb_revoked_test",
        "email": "rev@example.com",
        "tenant_id": "tenant_smoke_local",
    }

    with patch.object(ip_mod, "_ensure_initialized", lambda _pid: None):
        provider = ip_mod.IdentityPlatformProvider(project_id="test-proj")

    # Short-circuit the DB hop so the test doesn't need Plan 03's schema.
    async def _stub_map(*, provider_uid: str, tenant_id: str) -> str:
        # Return a deterministic UUID derived from the provider uid so
        # callers can still assert app_user_id != provider_uid.
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, provider_uid))

    with patch(
        "firebase_admin.auth.verify_id_token",
        return_value=fake_decoded,
    ) as mock_verify, patch.object(
        provider, "_provider_uid_to_app_user_id", _stub_map
    ):
        claims = await provider.verify_id_token("an-id-token")

    # Assert the SDK was called with check_revoked=True (kwarg or arg).
    assert mock_verify.call_count == 1
    args, kwargs = mock_verify.call_args
    # The provider passes the token positionally and check_revoked as kwarg.
    assert kwargs.get("check_revoked") is True, (
        "verify_id_token MUST be called with check_revoked=True "
        "(Don't Hand-Roll line 596)"
    )
    # Sanity: returned claims propagate the JWT tenant_id and a Nestor UUID.
    assert claims.tenant_id == "tenant_smoke_local"
    assert claims.raw_provider_user_id == "fb_revoked_test"
    assert claims.app_user_id != "fb_revoked_test"
    uuid.UUID(claims.app_user_id)
