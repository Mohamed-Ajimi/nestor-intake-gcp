"""
AuthProvider ABC + AuthClaims dataclass -- the D-10 swap point.

See:
  - .planning/phases/01-production-foundation/01-CONTEXT.md
        D-10 (Identity Platform NOW; WorkOS via abstraction later)
        `<specifics>` line 127 (provider-side IDs must NOT leak)
  - .planning/phases/01-production-foundation/01-RESEARCH.md
        § Code Examples lines 692-735 (verbatim target)
        § Pitfall 9 (tenant_id custom claim; never DB lookup before RLS)
        § Don't Hand-Roll (use firebase_admin.auth.verify_id_token)
  - .planning/phases/01-production-foundation/01-PATTERNS.md
        § `nestor_pulse_sdk/auth/provider.py` lines 166-202

The abstraction enables a ~1-2 day swap from Identity Platform to WorkOS.
Any caller that consumes `AuthClaims` is provider-agnostic -- the ONLY
field that ever carries a provider-specific id is `raw_provider_user_id`,
which by convention NEVER leaks past the AuthProvider boundary.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthClaims:
    """
    Provider-agnostic, immutable identity envelope.

    Attributes:
        app_user_id:           Nestor-side UUID -- the ONLY id used internally
                               (URLs, audit rows, DB FKs). NEVER use
                               `raw_provider_user_id` outside this dataclass.
        tenant_id:             == org_id; comes from a JWT custom claim per
                               RESEARCH.md Pitfall 9. MUST NOT be derived from a
                               DB lookup that happens before RLS is set.
        email:                 user email; convenience for audit logging.
        raw_provider_user_id:  firebase uid OR workos user id; provider-side.
                               Boundary marker -- this field name is deliberately
                               verbose so grep can enforce non-leakage outside
                               `nestor_pulse_sdk/auth/`.
    """
    app_user_id: str
    tenant_id: str
    email: str
    raw_provider_user_id: str


class AuthError(Exception):
    """
    Raised when a token is missing, malformed, invalid, revoked, or lacks
    a required claim (notably the `tenant_id` custom claim per Pitfall 9).

    Carries an HTTP status code so `nestor_pulse_sdk.auth.middleware`'s
    exception handler can translate uniformly to FastAPI responses.
    """

    def __init__(self, msg: str, status_code: int = 401) -> None:
        super().__init__(msg)
        self.msg = msg
        self.status_code = status_code


class InvalidTokenError(AuthError):
    """
    Specialisation of AuthError for token-validation failures.

    Kept as a distinct class so callers (and the Plan 02 conftest
    `fake_auth_provider` fixture, which imports it by name) can catch the
    narrow case without catching every AuthError variant.
    """

    def __init__(self, msg: str = "Invalid or unknown token") -> None:
        super().__init__(msg, status_code=401)


class AuthProvider(ABC):
    """
    Abstract identity provider. One impl per backing IdP.

    Phase 1: `IdentityPlatformProvider` (Google Identity Platform).
    Phase 2+ optional: `WorkOSProvider` (D-10 swap, ~1-2 days).
    Tests: `FakeAuthProvider` (see Plan 02 conftest -- in-memory dict).

    Contract notes:
      - `verify_id_token` MUST raise `AuthError` (subclass) on ANY failure
        path -- never return None, never return a sentinel claims object.
      - `verify_id_token` MUST extract `tenant_id` from the signed JWT (a
        custom claim) and NEVER from a DB lookup before RLS is set
        (RESEARCH.md Pitfall 9). The ONLY route allowed to bypass this rule
        is `/api/orgs/bootstrap`, which uses a separate "unscoped" dep.
      - `lookup_user` is reserved for admin/back-channel paths and is NOT
        called inside the per-request hot path.
      - `sign_out` revokes refresh tokens (provider-specific mechanism).
    """

    @abstractmethod
    async def verify_id_token(self, token: str) -> AuthClaims:
        """
        Verify a bearer ID token and return provider-agnostic claims.

        Raises:
            InvalidTokenError: token missing, malformed, invalid signature,
                or revoked.
            AuthError(status_code=401, msg="Missing tenant_id claim"):
                token verified but lacks the `tenant_id` custom claim
                (Pitfall 9). Bootstrap path is the only exception.
        """

    @abstractmethod
    async def lookup_user(self, app_user_id: str) -> "AuthClaims | None":
        """Return AuthClaims for an app_user_id, or None if absent."""

    @abstractmethod
    async def sign_out(self, app_user_id: str) -> None:
        """Revoke the user's refresh tokens at the provider."""
