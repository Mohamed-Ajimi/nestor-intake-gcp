"""FastAPI application skeleton — split liveness/readiness health probes (D-07).

This is the first deployable Cloud Run surface (API-01). It carries **no business
logic, no auth, no per-request DB state** (D-06): the only routes are the two
health probes, and the only DB touch is ``/readyz``'s ``SELECT 1`` through the
shared pooled engine.

Endpoints (D-07):
- ``/healthz`` -- LIVENESS. Sync ``def``, returns 200 ``{"status":"ok"}`` and
  NEVER opens a DB connection, so a transient Cloud SQL blip cannot fail liveness
  and cycle instances (Pitfall 4 / threat T-02-04).
- ``/readyz``  -- READINESS. Sync ``def``, runs ``SELECT 1`` through the pool;
  200 ``{"status":"ready","db":"ok"}`` when reachable, **503**
  ``{"status":"not-ready","db":"error"}`` otherwise — with NO DSN / exception
  text leaked (threat T-02-01).

Critical conventions:
- **Sync ``def`` handlers, not ``async def``** — pg8000 is a blocking driver and
  FastAPI runs sync handlers in a threadpool; an ``async def`` calling the sync
  engine would block the event loop (RESEARCH Pattern 2 / Pitfall).
- **No migrations** in lifespan or anywhere here (Pitfall 5) — the one-shot Cloud
  Run Job is the sole migration runner (threat T-02-05).
- **No GUC / transaction-local session state** — ``rls.py``'s
  per-space context contract is untouched (Pitfall 2 / threat T-02-03).
- The engine is reused via ``app.db.base.get_engine`` — never build a second one.

Authoritative references:
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-RESEARCH.md § Pattern 2
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-PATTERNS.md § main.py
- D-06 (minimal skeleton) / D-07 (split health) / threat_model T-02-01,04,05
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.auth_routes import auth_router, protected_router
from app.api.sample_routes import sample_router
from app.core.config import get_settings
from app.core.firebase import init_firebase
from app.db import base
from app.db.base import get_engine

# Server-side diagnostic logger. Cloud Run captures stderr, so logging here makes
# a live readiness failure (e.g. "permission denied for schema nestor" from the
# OQ1/A5 GRANT being wrong) diagnosable WITHOUT leaking any DSN/exception text to
# the HTTP client (T-02-01 — the client still gets a generic 503).
logger = logging.getLogger("nestor.health")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: init the Firebase Admin SDK on startup; release pooled
    connections on shutdown.

    Runs NO migrations and sets NO GUC. Startup initializes the Admin SDK once via
    ADC (``init_firebase()`` — idempotent, no JSON key) so ``auth.verify_id_token``
    is ready before the first request; on shutdown the shared engine's pool is
    disposed so Cloud SQL connections are released cleanly when the instance is
    reclaimed.
    """
    # Phase 3: init the Admin SDK once via ADC before serving traffic (D-09). This
    # does NOT attach any auth dependency to the bare app — /healthz and /readyz
    # stay anonymous for the Cloud Run probes (per-route protection lands in plan 03).
    init_firebase()
    yield
    # WR-03: only dispose if the lru_cached engine was ACTUALLY built (e.g. a
    # /readyz was served). Building a brand-new engine purely to dispose it is
    # wasteful and, in URL mode, get_engine() reads os.environ["DATABASE_URL"]
    # which would KeyError on Cloud Run (where only INSTANCE_CONNECTION_NAME is
    # set). Guard the dispose so a shutdown error never surfaces as an ugly crash.
    if base.get_engine.cache_info().currsize:
        try:
            get_engine().dispose()
        except Exception:  # noqa: BLE001 -- shutdown best-effort; never crash on dispose
            logger.warning("engine dispose on shutdown failed", exc_info=True)


app = FastAPI(lifespan=lifespan)

# CORS for the cross-origin browser handshake (Phase-3 WR-03). The frontend
# (Cloudflare Workers origin) POSTs to /auth/session on this backend (Cloud Run
# origin) with an Authorization bearer header; the browser preflight (OPTIONS) for
# that header on a cross-origin request must be answered or the handshake is blocked
# from the browser entirely. Middleware is installed ONLY when an explicit allowlist
# is configured (CORS_ALLOWED_ORIGINS) — never a permissive "*" (and never "*" with
# credentials). Empty allowlist (the default) => no middleware, no broadening.
_cors_origins = get_settings().cors_allowed_origins
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

# Routers (plan 03). NO auth dependency is attached to the bare app, so /healthz and
# /readyz below stay ANONYMOUS for the Cloud Run probes (Pitfall 1 / T-02-04).
# - auth_router: anonymous-but-self-verifying /auth/session login-sync handshake.
# - protected_router: the default-deny base (Depends(get_current_identity)) every
#   future feature router inherits (AUTH-01 / T-03-17).
# - sample_router: the throwaway Phase-4 tenant-scoped list/get/patch surface (D-08),
#   mounted UNDER protected_router so it inherits get_current_identity and is NEVER
#   anonymous. The single app.include_router(protected_router) below carries it; do NOT
#   add a second app.include_router(sample_router) and do NOT attach any auth dependency
#   to the bare app (keeps /healthz and /readyz anonymous for the Cloud Run probes).
protected_router.include_router(sample_router)
app.include_router(auth_router)
app.include_router(protected_router)


@app.get("/healthz")
def healthz():
    """Liveness probe — never touches the DB (Pitfall 4 / T-02-04)."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness probe — ``SELECT 1`` through the pool (proves SC1).

    Opens and closes its own connection with no per-space GUC write (Pitfall 2).
    On any failure returns a generic 503 with NO exception / DSN detail leaked
    (T-02-01).
    """
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "db": "ok"}
    except Exception:  # noqa: BLE001 -- generic by design; never leak DSN/exception text
        # Log the full exception SERVER-SIDE (stderr -> Cloud Run logs) so a live
        # failure is diagnosable (WR-02). logger.exception records the traceback;
        # the DSN/credentials are never part of the exception here (IAM auth, no
        # password), and nothing is echoed to the client response below (T-02-01).
        logger.exception("readyz: DB connectivity check failed")
        return JSONResponse(
            {"status": "not-ready", "db": "error"},
            status_code=503,
        )
