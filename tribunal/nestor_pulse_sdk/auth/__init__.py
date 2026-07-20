# nestor_pulse_sdk.auth -- AuthProvider abstraction (D-10) + FastAPI deps.
#
# Per Plan 01-04 + RESEARCH.md lines 692-735 + CONTEXT.md D-10:
#   - `provider.py`       -- AuthProvider ABC + AuthClaims dataclass (the swap point).
#   - `internal_caller.py` -- InternalCallerProvider (Phase 14 SEAM-01) concrete impl.
#   - `deps.py`           -- FastAPI dependencies: get_current_user, get_db_session.
#   - `middleware.py`     -- Request-ID middleware, AuthError -> JSONResponse handler.
#
# Phase 14 (SEAM-01): the standalone Identity-Platform surface is retired in the
# `tribunal/` copy. `identity_platform.py` (IdentityPlatformProvider / Firebase
# verifier) is deleted; the sole provider is `InternalCallerProvider`, installed
# at the existing `set_auth_provider()` swap point. `firebase-admin` is removed.
#
# Re-exports: callers typically prefer `from nestor_pulse_sdk.auth import X`
# (plan success criterion). The granular submodule imports remain available
# (`from nestor_pulse_sdk.auth.provider import AuthProvider`) so the provider
# swap can stay surgical -- one provider-construction line in server.py, no
# fan-out across the import graph.

from nestor_pulse_sdk.auth.provider import (
    AuthClaims,
    AuthError,
    AuthProvider,
    InvalidTokenError,
)

__all__ = [
    "AuthClaims",
    "AuthError",
    "AuthProvider",
    "InvalidTokenError",
]
