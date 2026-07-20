"""
IdentityPlatformProvider -- concrete AuthProvider for Google Identity Platform.

See:
  - .planning/phases/01-production-foundation/01-RESEARCH.md
        § Code Examples lines 718-735 (verbatim target shape)
        § Don't Hand-Roll line 596 (use firebase_admin.auth.verify_id_token)
        § Pitfall 9 (tenant_id custom claim)
        § Security Domain line 891 (check_revoked=True is mandatory)
  - infrastructure/identity-platform-bootstrap.md
        § "The post-signup `tenant_id` custom-claim flow (Plan 04 contract)"
        § "What Plan 04 must NOT do" -- no hand-rolled JWKS; check_revoked=True
  - memory/project_gcp_sa_key_policy.md
        SA JSON keys disabled org-wide -- use ApplicationDefault credentials.

The smoke user this provider verifies tokens for in Plan 05:
    uid:                X9aUTvNi7tYcqsV9bddSP4jHSsB3
    email:              smoketest@nestor-prod.local
    tenant_id claim:    tenant_smoke_local
    password secret:    IDENTITY_PLATFORM_SMOKE_USER_PW
"""

from __future__ import annotations

import os
from typing import Any

from nestor_pulse_sdk.auth.provider import (
    AuthClaims,
    AuthError,
    AuthProvider,
    InvalidTokenError,
)


# Module-level singleton flag: firebase_admin.initialize_app raises if
# called twice for the default app, so we gate behind this idempotently.
_INIT = False


def _ensure_initialized(project_id: str) -> None:
    """Idempotent Firebase Admin SDK init. ADC only -- no SA JSON keys."""
    global _INIT
    if _INIT:
        return
    # Lazy import so module import works in environments where
    # firebase-admin isn't installed (e.g. doc-only smoke checks).
    from firebase_admin import credentials, initialize_app  # type: ignore

    # ApplicationDefault uses ADC (gcloud auth on dev; Workload Identity
    # on Cloud Run). NEVER use credentials.Certificate(json_path) --
    # org policy disables SA JSON keys (memory/project_gcp_sa_key_policy.md).
    initialize_app(credentials.ApplicationDefault(), {"projectId": project_id})
    _INIT = True


class IdentityPlatformProvider(AuthProvider):
    """
    Verifies Identity Platform ID tokens via firebase-admin and extracts
    `tenant_id` from a custom claim. Maps `firebase uid -> app_user_id`
    via the `app_user` table (Plan 03 schema; W7 -- table renamed from
    reserved keyword `user`).

    Construction is cheap (idempotent init). All token verification is
    delegated to the Firebase Admin SDK which handles JWKS rotation,
    audience checks, expiry, and the revocation lookup
    (`check_revoked=True`).
    """

    def __init__(self, project_id: str | None = None) -> None:
        # Allow constructor injection for tests; default to env var which
        # is loaded by `nestor_pulse/secrets.py::load_secrets_into_env`
        # from Secret Manager at app startup (Plan 01).
        resolved = project_id or os.environ.get("IDENTITY_PLATFORM_PROJECT_ID")
        if not resolved:
            raise AuthError(
                "IDENTITY_PLATFORM_PROJECT_ID not set -- "
                "did Plan 01's secret-manager-bootstrap.sh run?",
                status_code=500,
            )
        # Persist so downstream callers / re-inits see the same project.
        os.environ.setdefault("IDENTITY_PLATFORM_PROJECT_ID", resolved)
        _ensure_initialized(resolved)

    # ------------------------------------------------------------------
    # Public API -- AuthProvider contract
    # ------------------------------------------------------------------

    async def verify_id_token(self, token: str) -> AuthClaims:
        """
        Verify the bearer token and produce provider-agnostic AuthClaims.

        Order of operations (matters for security):
          1. firebase_admin.auth.verify_id_token(token, check_revoked=True)
             -- handles signature, audience, expiry, AND revocation.
          2. Extract `tenant_id` from the signed claim. Missing -> 401
             "Missing tenant_id claim" (Pitfall 9; NO DB fallback).
          3. Map firebase uid -> app_user_id via the `app_user` table,
             querying with RLS set to the JWT-trusted tenant_id.
        """
        if not token:
            raise InvalidTokenError("Empty bearer token")

        # Lazy import; see _ensure_initialized() rationale above.
        from firebase_admin import auth as fb_auth  # type: ignore

        try:
            # check_revoked=True is MANDATORY per RESEARCH Don't Hand-Roll
            # line 596 + Security Domain line 891. Revocation is the ONLY
            # mechanism to kill a leaked refresh token within ~1 hour.
            decoded: dict[str, Any] = fb_auth.verify_id_token(
                token, check_revoked=True
            )
        except AuthError:
            raise
        except Exception as exc:  # noqa: BLE001 -- firebase wraps many types
            # firebase_admin raises a family of exceptions (ExpiredIdTokenError,
            # RevokedIdTokenError, InvalidIdTokenError, CertificateFetchError,
            # UserDisabledError). All map to 401 from the caller's perspective.
            raise InvalidTokenError(f"Invalid token: {exc}") from exc

        # Pitfall 9: tenant_id MUST come from the signed JWT, NOT a DB lookup.
        tenant_id = decoded.get("tenant_id")
        if not tenant_id:
            raise AuthError("Missing tenant_id claim", status_code=401)

        provider_uid = decoded.get("uid")
        if not provider_uid:
            # Defensive: firebase tokens always carry uid, but be explicit.
            raise InvalidTokenError("Token missing uid")

        app_user_id = await self._provider_uid_to_app_user_id(
            provider_uid=provider_uid, tenant_id=str(tenant_id)
        )

        return AuthClaims(
            app_user_id=str(app_user_id),
            tenant_id=str(tenant_id),
            email=str(decoded.get("email", "")),
            raw_provider_user_id=str(provider_uid),
        )

    async def lookup_user(self, app_user_id: str) -> AuthClaims | None:
        """
        Reverse lookup -- not used in the per-request hot path.

        Phase 1 does NOT need this outside an existing request scope; the
        `/api/admin/*` paths that would need it land in Phase 2.
        """
        raise NotImplementedError(
            "Phase 1 does not need lookup-by-app-user-id outside request scope"
        )

    async def sign_out(self, app_user_id: str) -> None:
        """
        Revoke refresh tokens for a user.

        Phase 1 stub -- ID token expiry is short (default ~1h) and the
        revocation list is checked by verify_id_token(check_revoked=True).
        Full admin-driven sign-out lands in Phase 2 alongside the
        org_member admin UI.
        """
        # Intentionally a pass; behaviour is documented in the docstring.
        return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _provider_uid_to_app_user_id(
        self, *, provider_uid: str, tenant_id: str
    ) -> str:
        """
        Map firebase uid -> app_user.id (Nestor-side UUID).

        SECURITY: runs as the runtime app role (NOT a bypass-RLS role).
        Since `app_user` is tenant-scoped, RLS must be set first; the
        tenant_id comes from the signed JWT and is therefore trusted.

        See:
          - RESEARCH.md § Pattern 1 (set_tenant_context + transaction)
          - 01-04-PLAN.md `<must_haves>` W7 plan-check note (User maps to
            table `app_user`; ORM `select(User.id)` renders the right name).
        """
        # Lazy import: Plan 03's DB modules live in a sibling worktree and
        # will be present in this tree after the wave-2 orchestrator merge.
        # Importing lazily lets `from nestor_pulse_sdk.auth import ...`
        # work even before Plan 03 lands (unit tests for the non-DB paths
        # of `verify_id_token` patch `_provider_uid_to_app_user_id`).
        from sqlalchemy import select  # noqa: WPS433 -- intentional local

        from nestor_pulse_sdk.db.base import get_sessionmaker  # type: ignore
        from nestor_pulse_sdk.db.models.user import User  # type: ignore
        from nestor_pulse_sdk.db.rls import set_tenant_context  # type: ignore

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            async with session.begin():
                # SET LOCAL via set_config(..., true) -- transaction scoped
                # so it does NOT leak across PgBouncer-pooled connections
                # (Pitfall 1; regression test in test_auth_middleware.py).
                await set_tenant_context(session, tenant_id)
                stmt = select(User.id).where(
                    User.provider_user_id == provider_uid
                )
                row = (await session.execute(stmt)).scalar_one_or_none()
                if row is None:
                    raise AuthError(
                        "User not found in tenant scope -- "
                        "run org bootstrap first",
                        status_code=403,
                    )
                return str(row)
