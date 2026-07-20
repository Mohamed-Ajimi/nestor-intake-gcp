"""
Health endpoints for Cloud Run probes.

Routes:
  GET /health   -- primary liveness probe (no DB touch). Cloud Run forwards
                   this path to the container (unlike /healthz which is
                   intercepted by the Cloud Run infrastructure layer -- see
                   Plan 10.5 SUMMARY § Deviation).
  GET /healthz  -- alias for /health; kept for plan spec compliance and local
                   testing. On Cloud Run this path is intercepted before the
                   container, but internal ASGI tests (pytest httpx) work fine.
  GET /readyz   -- readiness probe: SELECT 1 against Cloud SQL.

Both liveness routes are EXEMPT from the JWT auth dependency (see server.py
include_router call). Cloud Run's prober calls them without an Authorization
header; requiring one would make the service appear permanently unhealthy.

Threat model (T-10.5-02): unauthenticated but no tenant data is leaked.
/health + /healthz: static {"status":"ok"} with no user-specific content.
/readyz: {"status":"ready","db":"ok"} or {"status":"unavailable","db":"unreachable"}.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Response
from sqlalchemy import text

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health", include_in_schema=False)
@router.get("/healthz", include_in_schema=False)
async def liveness() -> dict:
    """Cloud Run liveness probe.

    /health is the primary path (Cloud Run forwards this to the container).
    /healthz is an alias; on Cloud Run the platform intercepts it before
    the container, but it works correctly in local/test environments.
    MUST NOT touch the DB -- if the DB is down the pod is still alive.
    Returns 200 as long as the process is up and the event loop is running.
    """
    return {"status": "ok"}


@router.get("/readyz", include_in_schema=False)
async def readiness(response: Response) -> dict:
    """Cloud Run readiness probe.

    Performs a SELECT 1 against Cloud SQL via the shared async session pool.
    Returns 200 + {"status":"ready","db":"ok"} when the DB is reachable.
    Returns 503 + {"status":"unavailable","db":"unreachable"} when it is not
    (e.g., Cloud SQL instance is paused or the socket path is missing).

    NOT 401/403 regardless of DB reachability -- this route is exempt from
    the JWT dependency.
    """
    try:
        from nestor_pulse_sdk.db.base import get_sessionmaker  # lazy import
        sm = get_sessionmaker()
        async with sm() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "db": "ok"}
    except Exception as exc:
        # Log the error but don't leak internal details to the caller.
        logger.warning("readyz DB probe failed: %s", exc)
        response.status_code = 503
        return {"status": "unavailable", "db": "unreachable"}
