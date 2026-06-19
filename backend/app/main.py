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
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.db.base import get_engine

# Server-side diagnostic logger. Cloud Run captures stderr, so logging here makes
# a live readiness failure (e.g. "permission denied for schema nestor" from the
# OQ1/A5 GRANT being wrong) diagnosable WITHOUT leaking any DSN/exception text to
# the HTTP client (T-02-01 — the client still gets a generic 503).
logger = logging.getLogger("nestor.health")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: release pooled connections on shutdown.

    Runs NO migrations and sets NO GUC — startup is a no-op; on shutdown the
    shared engine's pool is disposed so Cloud SQL connections are released
    cleanly when the instance is reclaimed.
    """
    yield
    get_engine().dispose()


app = FastAPI(lifespan=lifespan)


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
