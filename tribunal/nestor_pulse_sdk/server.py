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
import warnings
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

# WR-06 (T-14-05 — never a silent auth downgrade): LOCAL_DEV_AUTH replaces the
# ENTIRE seam (OIDC verify + SA pinning + tenant validation) with a fixed dev
# identity, so an env flag alone is too weak a gate for a deployed service that
# fronts cross-tenant research data. Cloud Run always injects K_SERVICE and the
# operator flow cannot unset it — if both are present this is a deployed
# environment carrying the bypass (a mistaken --update-env-vars, or a stale
# value replayed by --set-env-vars replacement semantics): refuse LOUDLY at
# import so the revision fails to boot instead of silently serving unauthenticated.
if LOCAL_DEV_AUTH and os.environ.get("K_SERVICE"):
    raise RuntimeError(
        "LOCAL_DEV_AUTH=1 is forbidden in a deployed environment (K_SERVICE is "
        "set): it would replace the internal-caller seam with a fixed dev "
        "identity. Remove LOCAL_DEV_AUTH from the Cloud Run service env."
    )

app = FastAPI(
    title="Nestor Pulse SDK",
    version="0.2.0",
    description="Internal research engine API -- async runs, tenant-scoped RLS.",
)

# CORS — WR-05 (14-REVIEW): the Tribunal API is a strictly-internal
# server-to-server engine; no browser origin ever calls it, so deployed mode
# installs NO CORS middleware at all (a wildcard would advertise cross-origin
# readability of anything a future IAM/ingress misconfiguration exposes, and
# contradicts the intake project's no-permissive-CORS doctrine). The permissive
# local wildcard survives ONLY under LOCAL_DEV_AUTH (a local browser tool
# driving real mode); combined with the WR-06 rule that LOCAL_DEV_AUTH is
# refused on Cloud Run, this middleware can never reach production.
if LOCAL_DEV_AUTH:
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

# Phase 14 (SEAM-02): the internal-seam provisioning endpoints
# (POST /api/orgs/ensure + POST /api/projects/ensure) replace the retired
# user-facing /api/orgs/bootstrap. Driven ONLY by the intake backend.
from nestor_pulse_sdk.orgs import router as orgs_router
app.include_router(orgs_router)

# Phase 14 (SEAM-01): install the auth provider. get_current_user is overridden
# so every route (incl. get_db_session's RLS SET LOCAL) reads verified claims.
from nestor_pulse_sdk.auth.deps import get_current_user

if LOCAL_DEV_AUTH:
    # Local clean-room: replace token verification with a fixed dev identity.
    # The override propagates into get_db_session (sets app.tenant_id to the
    # dev tenant) and every route depending on the current user. Real DB,
    # real RLS context, real engines -- just no service-to-service seam required.
    from nestor_pulse_sdk.auth.local_dev import dev_claims

    app.dependency_overrides[get_current_user] = dev_claims
    warnings.warn(
        "LOCAL_DEV_AUTH=1: auth is bypassed with a fixed dev identity. "
        "NEVER enable this in a deployed environment.",
        stacklevel=2,
    )
else:
    # Deployed mode: the intake backend is the sole authenticated caller.
    # InternalCallerProvider re-verifies the Google-signed OIDC token (aud ==
    # this Tribunal service URL, caller email == intake runtime SA -- D-04 inner
    # gate), and get_internal_claims threads the tenant + acting-user headers
    # into the frozen AuthClaims shape (D-05). Both env vars are NON-secret
    # (a service URL + an SA email) -- Plan 04 sets them on the tribunal-api
    # service: TRIBUNAL_SERVICE_URL, INTAKE_RUNTIME_SA_EMAIL.
    from nestor_pulse_sdk.auth.internal_caller import (
        InternalCallerProvider,
        get_internal_claims,
    )

    # Read the two NON-secret seam env vars WITHOUT crashing at import when they
    # are absent (e.g. the CI test image, which imports `server` to exercise the
    # health/RLS suites and never sets production env). Fail-CLOSED at request
    # time rather than at collection: if either is unset we do NOT install the
    # provider, so get_auth_provider() raises the deps.py RuntimeError on any real
    # request (T-14-05) instead of masking a mis-provisioned deploy with a 200.
    _seam_service_url = os.environ.get("TRIBUNAL_SERVICE_URL")
    _seam_caller_email = os.environ.get("INTAKE_RUNTIME_SA_EMAIL")
    if _seam_service_url and _seam_caller_email:
        set_auth_provider(InternalCallerProvider(
            service_url=_seam_service_url,
            allowed_caller_email=_seam_caller_email,
        ))
        app.dependency_overrides[get_current_user] = get_internal_claims
    else:
        # No seam env → provider intentionally left uninstalled. Any authenticated
        # route will 500 via get_auth_provider()'s RuntimeError (fail-closed). The
        # unauthenticated health routes (/healthz, /readyz) still import + serve.
        warnings.warn(
            "TRIBUNAL_SERVICE_URL / INTAKE_RUNTIME_SA_EMAIL unset in deployed mode: "
            "the InternalCaller seam provider is NOT installed. Authenticated routes "
            "will fail closed. Set both env vars on the tribunal-api service.",
            stacklevel=2,
        )

# Run with: uvicorn nestor_pulse_sdk.server:app --host 0.0.0.0 --port 8081
