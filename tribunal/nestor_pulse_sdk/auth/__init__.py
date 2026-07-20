# nestor_pulse_sdk.auth -- AuthProvider abstraction (D-10) + FastAPI deps.
#
# Per Plan 01-04 + RESEARCH.md lines 692-735 + CONTEXT.md D-10:
#   - `provider.py`     -- AuthProvider ABC + AuthClaims dataclass (the swap point).
#   - `identity_platform.py` -- IdentityPlatformProvider concrete impl.
#   - `deps.py`         -- FastAPI dependencies: get_current_user, get_db_session.
#   - `middleware.py`   -- Request-ID middleware, AuthError -> JSONResponse handler.
#
# Re-exports: callers typically prefer `from nestor_pulse_sdk.auth import X`
# (plan success criterion). The granular submodule imports remain available
# (`from nestor_pulse_sdk.auth.provider import AuthProvider`) so the WorkOS
# swap can stay surgical -- one provider-construction line in main(), no
# fan-out across the import graph.

from nestor_pulse_sdk.auth.provider import (
    AuthClaims,
    AuthError,
    AuthProvider,
    InvalidTokenError,
)
from nestor_pulse_sdk.auth.identity_platform import IdentityPlatformProvider

__all__ = [
    "AuthClaims",
    "AuthError",
    "AuthProvider",
    "InvalidTokenError",
    "IdentityPlatformProvider",
]
