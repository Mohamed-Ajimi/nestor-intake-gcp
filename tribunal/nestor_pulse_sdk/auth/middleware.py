"""
Request-ID middleware + AuthError -> JSONResponse handler + structured
logging hook.

See:
  - .planning/phases/01-production-foundation/01-CONTEXT.md
        D-10 (abstraction), `<code_context>` Auth <-> RLS boundary.
  - .planning/phases/01-production-foundation/01-RESEARCH.md
        § Security Domain V7 (audit logging requires request correlation).
  - .planning/phases/01-production-foundation/01-PATTERNS.md
        § No Analog Found -- `auth/middleware.py` is greenfield (no prior
        analog in the codebase).

Three pieces, intentionally narrow:

  1. `RequestIDMiddleware` -- accepts inbound `X-Request-ID` or generates
     one; attaches to `request.state.request_id`; echoes in response
     header. Audit + logging downstream key off this id.

  2. `auth_exception_handler` -- registered against `AuthError` (and
     subclasses like `InvalidTokenError`). Produces a uniform
     `{"error": "<msg>"}` JSONResponse with the carried status_code.
     FastAPI's default handler for HTTPException already does the right
     thing for HTTPException; this handler exists so callers that raise
     `AuthError` directly (e.g. utility helpers) also get a clean
     response without each helper translating to HTTPException.

  3. `bind_request_log_context` -- structlog binding helper. Pulls
     request_id + tenant_id + app_user_id out of request.state if
     `get_current_user` has run, otherwise just request_id + route.
     Plan 07's audit pipeline reads these keys.
"""

from __future__ import annotations

import uuid
from typing import Awaitable, Callable

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from nestor_pulse_sdk.auth.provider import AuthError


REQUEST_ID_HEADER = "X-Request-ID"


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Attach a stable request id to every request/response.

    Read `X-Request-ID` from the inbound headers when present (lets a
    load balancer / API gateway propagate its own id); otherwise mint a
    fresh uuid4. The id is stashed at `request.state.request_id` and
    echoed back in the response header so the client can correlate
    server logs.

    ASVS V7 (logging + monitoring): correlation requires a stable id
    that travels through every log line for the request. Adding this
    middleware before any auth dep means even auth-failure responses
    carry the id, so 401 spikes can be traced.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id  # type: ignore[attr-defined]
        try:
            response = await call_next(request)
        except Exception:
            # Re-raise -- FastAPI's exception machinery will format a 500.
            # The request_id is already on request.state for any logging
            # hook to grab on the way out.
            raise
        response.headers[REQUEST_ID_HEADER] = request_id
        return response


async def auth_exception_handler(request: Request, exc: AuthError) -> JSONResponse:
    """
    Translate `AuthError` (and subclasses) to a uniform JSON error body.

    Registered via `app.add_exception_handler(AuthError, auth_exception_handler)`
    at app startup. FastAPI handles HTTPException itself; this handler
    catches the cases where domain code raised AuthError directly.
    """
    request_id = getattr(request.state, "request_id", None)  # type: ignore[attr-defined]
    body = {"error": exc.msg}
    if request_id is not None:
        body["request_id"] = request_id
    return JSONResponse(body, status_code=exc.status_code)


def bind_request_log_context(request: Request) -> dict[str, object]:
    """
    Build the structured-logging bind dict for the current request.

    Returns a dict ready to pass to `structlog.contextvars.bind_contextvars`
    or `logger.bind(...)`. Keys are stable across the codebase so log
    queries (Plan 07 audit dashboard, Cloud Logging) can filter
    consistently.

    Pulls from request.state -- safe to call after RequestIDMiddleware
    runs even if `get_current_user` has not run yet (the user fields
    are simply omitted in that case).
    """
    bind: dict[str, object] = {
        "route": str(getattr(request.scope, "get", lambda *_: "")("path", ""))
        if False
        else (request.url.path if request else ""),
    }
    rid = getattr(request.state, "request_id", None)  # type: ignore[attr-defined]
    if rid is not None:
        bind["request_id"] = rid
    user = getattr(request.state, "user", None)  # type: ignore[attr-defined]
    if user is not None:
        # AuthClaims duck-typed -- avoid importing it for a cheap check.
        bind["tenant_id"] = getattr(user, "tenant_id", None)
        bind["app_user_id"] = getattr(user, "app_user_id", None)
    return bind
