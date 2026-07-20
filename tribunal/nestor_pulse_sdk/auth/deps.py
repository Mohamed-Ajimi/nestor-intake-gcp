"""
FastAPI dependencies for the auth + RLS boundary.

See:
  - .planning/phases/01-production-foundation/01-CONTEXT.md
        D-05 (RLS), D-10 (AuthProvider abstraction)
        `<code_context>` "Auth <-> RLS boundary" -- highest-leverage security
        review target.
  - .planning/phases/01-production-foundation/01-RESEARCH.md
        § Pattern 1 lines 354-371 -- get_db_session canonical pattern.
        § Pitfall 1 -- SET LOCAL via set_config(..., true), transaction-scoped.
        § Pitfall 9 -- tenant_id custom claim.
  - .planning/phases/01-production-foundation/01-PATTERNS.md
        § Tenant context dependency (RLS guard) lines 798-815.

The two exported deps Plan 06 will consume from its API layer:
  - `get_current_user(request)`                       -> AuthClaims
  - `get_db_session(user=Depends(get_current_user))`  -> AsyncSession
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends, HTTPException, Request

from nestor_pulse_sdk.auth.provider import AuthClaims, AuthError, AuthProvider


# ---------------------------------------------------------------------------
# Provider injection (D-10): one global slot, swappable from tests + main()
# ---------------------------------------------------------------------------

_PROVIDER: AuthProvider | None = None


def set_auth_provider(provider: AuthProvider) -> None:
    """
    Install the AuthProvider used by `get_current_user`.

    Called once at app startup -- typically with `IdentityPlatformProvider`
    -- and called repeatedly by tests with a `FakeAuthProvider` to keep
    unit tests off the network. THIS is the single bind point D-10's
    abstraction collapses to. Swapping to WorkOS = `set_auth_provider(
    WorkOSProvider(...))` and nothing else upstream changes.
    """
    global _PROVIDER
    _PROVIDER = provider


def get_auth_provider() -> AuthProvider:
    """
    Resolve the active AuthProvider installed via `set_auth_provider`.

    Phase 14 (SEAM-01): there is NO silent fallback. The standalone
    Identity-Platform surface (`IdentityPlatformProvider` / firebase-admin)
    is retired in the `tribunal/` copy, and the Tribunal API is now a
    strictly-internal engine — the sole provider is `InternalCallerProvider`,
    installed once at app startup in `server.py`.

    If nobody has installed a provider, FAIL LOUD rather than falling back
    to a Firebase path (T-14-05): a missing install is a boot-time
    configuration error, never a silent auth downgrade.
    """
    if _PROVIDER is None:
        raise RuntimeError(
            "no AuthProvider installed -- call set_auth_provider() at app "
            "startup (Phase 14: InternalCallerProvider). The Identity-Platform "
            "fallback was removed with the standalone auth surface (SEAM-01)."
        )
    return _PROVIDER


# ---------------------------------------------------------------------------
# Sessionmaker injection (Plan 03 contract; lazy)
# ---------------------------------------------------------------------------

# Plan 03 provides `nestor_pulse_sdk.db.base.get_sessionmaker`. We import it
# lazily so this module can be imported even before Plan 03's DB code lands
# in the worktree (matters in parallel wave execution).


def _resolve_sessionmaker():
    from nestor_pulse_sdk.db.base import get_sessionmaker  # type: ignore
    return get_sessionmaker()


# ---------------------------------------------------------------------------
# get_current_user -- the auth gate
# ---------------------------------------------------------------------------

async def get_current_user(request: Request) -> AuthClaims:
    """
    Read the `Authorization: Bearer <token>` header, verify the token via
    the active AuthProvider, and return provider-agnostic AuthClaims.

    Raises:
        HTTPException(401, "Missing or malformed Authorization header"):
            no header, wrong scheme, or empty token.
        HTTPException(401, "Invalid token: ..."):
            verification failed (signature, expiry, revocation).
        HTTPException(401, "Missing tenant_id claim"):
            token verified but no `tenant_id` custom claim (Pitfall 9).
        HTTPException(403, ...):
            uid valid but no matching `app_user` row in the tenant scope.

    On success, the resulting AuthClaims is also stashed on
    `request.state.user` so downstream middleware (request-id, audit
    binding) can read it without re-running the verification.
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
        )
    # Split max-1 -- handles "Bearer  token" with extra whitespace. After
    # the prefix check, split is guaranteed to yield >=1 elements; defend
    # against an all-whitespace remainder ("Bearer    ") returning length 1.
    parts = auth_header.split(None, 1)
    if len(parts) < 2:
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
        )
    token = parts[1].strip()
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Missing or malformed Authorization header",
        )

    provider = get_auth_provider()
    try:
        claims = await provider.verify_id_token(token)
    except AuthError as exc:
        # Translate provider exception to HTTP semantics uniformly.
        raise HTTPException(status_code=exc.status_code, detail=exc.msg) from exc

    # Make claims discoverable to other middleware on the same request.
    request.state.user = claims  # type: ignore[attr-defined]
    return claims


# ---------------------------------------------------------------------------
# get_db_session -- the JWT -> RLS boundary
# ---------------------------------------------------------------------------

async def get_db_session(
    user: AuthClaims = Depends(get_current_user),
) -> AsyncIterator["object"]:  # AsyncSession (lazy-typed for import safety)
    """
    Open an AsyncSession, begin a transaction, and SET LOCAL app.tenant_id
    to the JWT-trusted tenant before yielding.

    This is THE critical boundary the entire Phase 1 multi-tenant story
    rests on. Three invariants:

      1. The SET is transaction-scoped (`set_config(..., true)` per
         Pitfall 1). Under PgBouncer transaction-pooling the next request
         on the same physical connection gets a clean slate.
      2. The SET runs INSIDE `session.begin()` -- a SET LOCAL outside an
         open transaction is a silent no-op in Postgres.
      3. The SET runs BEFORE the route handler sees the session, so no
         RLS-protected query can ever run on an unset tenant context.

    Plan 06 routes consume this via `Depends(get_db_session)`.
    """
    # Lazy imports keep this module importable before Plan 03 lands.
    from nestor_pulse_sdk.db.rls import set_tenant_context  # type: ignore

    sessionmaker = _resolve_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            # Pitfall 1: third-arg-true SET LOCAL, transaction-scoped.
            await set_tenant_context(session, user.tenant_id)
            yield session
