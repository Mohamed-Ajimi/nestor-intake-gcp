"""
Nestor Pulse SDK server entrypoint -- FastAPI app mounting the SDK pipeline routes.

Bootstrap ordering (01-PATTERNS.md § Shared Patterns lines 763-779):
  1. load_dotenv (find .env from nestor_pulse directory)
  2. load_secrets_into_env (Secret Manager pull -- must come BEFORE any SDK import)
  3. FastAPI app construction
  4. Router mounting

Run with:
    uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port 8081

Note: The ADK pipeline server (server.py at repo root) runs on port 8080.
Both coexist per D-01 (parallel pipeline period through Phase 1 A/B).
"""
from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# Bootstrap ordering: Secret Manager BEFORE any nestor_pulse_sdk.* import
load_dotenv(Path(__file__).parent.parent / "nestor_pulse" / ".env")

# LOCAL_DEV_AUTH: do NOT pull cloud secrets. load_secrets_into_env() overrides
# DATABASE_URL with the Cloud SQL unix-socket URL ("Secret Manager values always
# win"), which is unusable on Windows and is not the local clean-room DB. The
# API keys engines need are loaded from nestor_pulse/.env by load_dotenv above.
if os.environ.get("LOCAL_DEV_AUTH") != "1":
    try:
        from nestor_pulse_sdk.secrets_bootstrap import load_sdk_secrets_into_env
        load_sdk_secrets_into_env()
    except Exception:
        # Allow server to start even if secrets module is not available in test envs
        pass

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

DEMO_MODE = os.environ.get("DEMO_MODE") == "1"
# LOCAL_DEV_AUTH: run the FULL real stack (DB, RLS, engines) but short-circuit
# token verification to a fixed dev identity, so the browser can drive real mode
# without Identity Platform / Firebase login. Gate is this env check alone --
# never set in a deployed environment. Ignored under DEMO_MODE (which has no DB).
LOCAL_DEV_AUTH = os.environ.get("LOCAL_DEV_AUTH") == "1"

app = FastAPI(
    title="Nestor Pulse SDK" + (" (demo)" if DEMO_MODE else ""),
    version="0.2.0",
    description="SDK pipeline API -- async runs, engine toggle, tenant-scoped RLS.",
)

# CORS first (applies in both modes)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

if DEMO_MODE:
    # Demo: skip auth + DB entirely. Mount in-memory fixture router only.
    # Never enabled in production -- this env check is the gate.
    from nestor_pulse_sdk.demo.api import router as demo_router
    app.include_router(demo_router)
else:
    from nestor_pulse_sdk.health import router as health_router  # Plan 10.5 Task 3
    from nestor_pulse_sdk.account import router as account_router
    from nestor_pulse_sdk.projects import router as projects_router
    from nestor_pulse_sdk.runs.api import router as runs_router
    from nestor_pulse_sdk.audit.api import router as audit_router
    from nestor_pulse_sdk.citations import router as sources_router
    from nestor_pulse_sdk.uploads.api import router as uploads_router  # Plan 10 Task 2
    from nestor_pulse_sdk.orgs import router as orgs_router  # Plan 01-17 Task 3 (D-16)
    from nestor_pulse_sdk.auth.middleware import RequestIDMiddleware, auth_exception_handler
    from nestor_pulse_sdk.auth.provider import AuthError
    from nestor_pulse_sdk.auth.deps import set_auth_provider  # noqa: F401
    from fastapi import Request as _Request
    from fastapi.responses import JSONResponse as _JSONResponse

    app.add_middleware(RequestIDMiddleware)
    app.add_exception_handler(AuthError, auth_exception_handler)

    # Plan 10.5: health endpoints FIRST, before any JWT-gated routers.
    # /healthz and /readyz are exempt from auth (Cloud Run prober calls without token).
    app.include_router(health_router)

    # Plan 01-17 Task 3 (D-14): GET /api/auth/config — exempt from JWT (like /healthz).
    # Returns the Identity Platform Web API key for the Login page so it is never
    # hardcoded in source control. The key is a public browser-embeddable identifier
    # (T-17-03 accept); abuse is bounded by admin-created-accounts-only (D-14).
    @app.get("/api/auth/config", include_in_schema=False)
    async def _auth_config(_req: _Request) -> _JSONResponse:
        return _JSONResponse({
            "web_api_key": os.environ.get("IDENTITY_PLATFORM_WEB_API_KEY", ""),
        })

    # GET /api/me -- current user + workspace for the app chrome (real-mode parity
    # with the demo router; previously real mode had no /api/me so corners 401'd).
    app.include_router(account_router)
    # D-06: projects must be creatable/listable before any run can be started
    # (runs/api.py 404s on an unknown project_id).
    app.include_router(projects_router)
    app.include_router(runs_router)
    # Plan 07: audit verifier + 4 guided-query endpoints (D-13)
    app.include_router(audit_router)
    # Plan 09: GET /api/sources/{id} citation renderer (D-07)
    app.include_router(sources_router)
    # Plan 10: GCS presigned-URL + Cloud Function extract proxy (replaces AWS Lambda path)
    app.include_router(uploads_router)
    # Plan 01-17: POST /api/orgs/bootstrap (unscoped; provisions new tester's org+user+project)
    app.include_router(orgs_router)

    if LOCAL_DEV_AUTH:
        # Local clean-room: replace token verification with a fixed dev identity.
        # The override propagates into get_db_session (sets app.tenant_id to the
        # dev tenant) and every route depending on the current user. Real DB,
        # real RLS context, real engines -- just no Firebase login required.
        from nestor_pulse_sdk.auth.deps import get_current_user
        from nestor_pulse_sdk.auth.local_dev import dev_claims

        app.dependency_overrides[get_current_user] = dev_claims
        import warnings
        warnings.warn(
            "LOCAL_DEV_AUTH=1: auth is bypassed with a fixed dev identity. "
            "NEVER enable this in a deployed environment.",
            stacklevel=2,
        )

# Plan 11: static UI from Claude Design handoff bundle ("Agenic" design system).
# Bundle is plain HTML/CSS/JSX + React/Babel via CDN — no build step.
# Mock data currently lives in Home.jsx; real API wiring is a follow-up task.
_WEB_DIR = Path(__file__).parent / "web"
if _WEB_DIR.exists():
    @app.middleware("http")
    async def _no_store_static(request, call_next):
        """Dev UI is plain JSX transpiled in-browser (no build hash), so the
        browser must NEVER cache it -- a stale Home.jsx is why edits 'don't show
        up'. Force revalidation on every /app asset."""
        response = await call_next(request)
        if request.url.path.startswith("/app"):
            response.headers["Cache-Control"] = "no-store, max-age=0, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    app.mount("/app", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")

    @app.get("/", include_in_schema=False)
    async def _root_redirect():
        return RedirectResponse(url="/app/Home.html")

# Run with: uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port 8081
