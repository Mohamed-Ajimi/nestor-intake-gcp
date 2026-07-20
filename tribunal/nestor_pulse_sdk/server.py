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

# LOCAL_DEV_AUTH: run the FULL real stack (DB, RLS, engines) but short-circuit
# token verification to a fixed dev identity, so a developer can drive real mode
# without the internal service-to-service seam. Gate is this env check alone --
# never set in a deployed environment.
#
# Phase 14 (SEAM-01): the standalone identity surface (Firebase/Identity Platform
# login, the current-user + bootstrap + auth-config endpoints, the static UI mount,
# and the demo fixture router) is RETIRED in the tribunal/ copy. The Tribunal API
# is now a strictly-internal engine: the only authenticated caller is the intake
# backend, verified by InternalCallerProvider at the set_auth_provider() swap point.
LOCAL_DEV_AUTH = os.environ.get("LOCAL_DEV_AUTH") == "1"

app = FastAPI(
    title="Nestor Pulse SDK",
    version="0.2.0",
    description="Internal research engine API -- async runs, tenant-scoped RLS.",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

from nestor_pulse_sdk.health import router as health_router  # Plan 10.5 Task 3
from nestor_pulse_sdk.projects import router as projects_router
from nestor_pulse_sdk.runs.api import router as runs_router
from nestor_pulse_sdk.audit.api import router as audit_router
from nestor_pulse_sdk.citations import router as sources_router
from nestor_pulse_sdk.uploads.api import router as uploads_router  # Plan 10 Task 2
from nestor_pulse_sdk.auth.middleware import RequestIDMiddleware, auth_exception_handler
from nestor_pulse_sdk.auth.provider import AuthError
from nestor_pulse_sdk.auth.deps import set_auth_provider  # noqa: F401

app.add_middleware(RequestIDMiddleware)
app.add_exception_handler(AuthError, auth_exception_handler)

# Plan 10.5: health endpoints FIRST, before any JWT-gated routers.
# /healthz and /readyz are exempt from auth (Cloud Run prober calls without token).
app.include_router(health_router)

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

# NOTE (Phase 14 Task 3): the InternalCallerProvider install + the orgs /ensure
# seam router include are wired here in Task 3 of this plan.

if LOCAL_DEV_AUTH:
    # Local clean-room: replace token verification with a fixed dev identity.
    # The override propagates into get_db_session (sets app.tenant_id to the
    # dev tenant) and every route depending on the current user. Real DB,
    # real RLS context, real engines -- just no service-to-service seam required.
    from nestor_pulse_sdk.auth.deps import get_current_user
    from nestor_pulse_sdk.auth.local_dev import dev_claims

    app.dependency_overrides[get_current_user] = dev_claims
    import warnings
    warnings.warn(
        "LOCAL_DEV_AUTH=1: auth is bypassed with a fixed dev identity. "
        "NEVER enable this in a deployed environment.",
        stacklevel=2,
    )

# Run with: uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port 8081
