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

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.admin_routes import admin_router
from app.api.ai_routes import ai_router
from app.api.auth_routes import auth_router, protected_router
from app.api.errors import CodedError
from app.api.intake_routes import intake_router
from app.api.me_routes import me_router
from app.api.research_routes import research_router
from app.api.storage_routes import storage_router
from app.core.config import get_settings
from app.core.firebase import init_firebase
from app.db import base
from app.db.ai_session import sweep_orphaned_skill_runs
from app.db.base import get_engine
from app.research.reconcile import sweep_once

# Server-side diagnostic logger. Cloud Run captures stderr, so logging here makes
# a live readiness failure (e.g. "permission denied for schema nestor" from the
# OQ1/A5 GRANT being wrong) diagnosable WITHOUT leaking any DSN/exception text to
# the HTTP client (T-02-01 — the client still gets a generic 503).
logger = logging.getLogger("nestor.health")


#: How often the in-process orphaned-run reconcile sweep runs, in SECONDS.
#: ``0`` or negative DISABLES the timer entirely (see ``_reconcile_loop`` / ``lifespan``).
#:
#: 300 s (5 minutes) is DERIVED, not taste. The sweep's whole job is to recover a run whose
#: poll driver died, and such a run has already been silent for longer than
#: ``reconcile.ORPHAN_CUTOFF_MINUTES`` (15) before it is even eligible — so shaving the
#: detection delay from 5 minutes to seconds buys nothing a human is waiting on, while every
#: tick costs a DB claim query and (when it claims) a 30 s-timeout engine seam call. The loss
#: window an operator actually notices is minutes.
#:
#: The ``0`` kill switch is NOT decoration. This phase adds a background loop to a service
#: that previously had none, and ``NESTOR_RECONCILE_INTERVAL_S=0`` is the ONLY way an operator
#: can stop it without shipping code.
RECONCILE_INTERVAL_SECONDS = float(os.environ.get("NESTOR_RECONCILE_INTERVAL_S", "300"))


async def _reconcile_loop() -> None:
    """Drive :func:`app.research.reconcile.sweep_once` on a timer, forever.

    Four properties here are each a way this quietly stops working, so each is pinned by a
    test in ``tests/test_reconciler_lifespan.py``:

    1. **``asyncio.to_thread`` is MANDATORY, not stylistic.** ``sweep_once`` is blocking
       pg8000 plus blocking httpx (``reconcile._TIMEOUT_S = 30.0``). Awaiting it directly on
       the event loop would stall EVERY request on this instance for the duration of a 30 s
       seam call — the same rule ``app/db/ai_session.py``'s module docstring already states
       for the AI path ("pg8000 is blocking, so EVERYTHING here is sync ``def``").
    2. **Sleep FIRST, then sweep.** A sweep on the very first tick would run before the
       instance is serving and would delay readiness behind a seam call — for a run that has
       by definition already been orphaned for 15+ minutes and can wait 5 more.
    3. **``except Exception`` then ``continue``.** One bad sweep must never end the loop. A
       dead timer is INVISIBLE: nothing polls it and nothing alerts on it, which makes it
       worse than a noisy failure. WARNING level on purpose — uvicorn's default logging config
       drops INFO from app loggers (the note already at the top of ``run_task.py`` and
       ``reconcile.py``), so an INFO here would log nowhere.
    4. **``counts.get("claimed")`` gates the log line**, so an idle service does not print a
       line every 5 minutes forever. ``sweep_once`` already logs its own detailed WARNING when
       it claims anything; this line is the caller-side breadcrumb that the TIMER fired.
    """
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
        try:
            counts = await asyncio.to_thread(sweep_once)
        except Exception:  # noqa: BLE001 -- one bad sweep must never end the timer
            logger.warning("research reconcile sweep failed", exc_info=True)
            continue
        if counts.get("claimed"):
            logger.warning("research reconcile sweep: %s", counts)


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
    # Phase 7 (D-01a / 07-RESEARCH Pitfall 6): self-heal orphaned skill runs. A
    # Cloud Run instance can die mid-task (deploy/scale-in/crash), leaving a
    # ``skill_runs`` row stuck at ``running`` forever — the frontend would then poll a
    # never-terminal run. One cheap superadmin-engine UPDATE on startup flips stale
    # ``running`` rows to ``failed`` before serving traffic. GUARDED so a sweep failure
    # (e.g. the DB is briefly unreachable at boot) never crashes startup — liveness must
    # not depend on it (mirrors the dispose guard below / T-02-04).
    try:
        swept = sweep_orphaned_skill_runs()
        if swept:
            logger.info("startup sweep marked %d orphaned skill_runs failed", swept)
    except Exception:  # noqa: BLE001 -- best-effort self-heal; never block startup
        logger.warning("startup sweep_orphaned_skill_runs failed", exc_info=True)
    # Phase 23.3 (COST-01 / DEF-23.2-03): start the in-process orphaned-RESEARCH-run sweep.
    #
    # WHY IN-PROCESS AND NOT CLOUD SCHEDULER: the Scheduler API is not enabled on this
    # project and enabling it is an operator/IAM action (23.3-CONTEXT.md § 8). ``sweep_once``
    # is a plain callable precisely so a Scheduler HTTP trigger can drive the very same unit
    # later without a redesign (DEF-23.3-10) — no route is added here for an API nobody can
    # call yet.
    #
    # WHY THIS IS SELF-HEALING RATHER THAN JUST ANOTHER TIMER: the sweep is stateless, so ANY
    # nestor-api instance can recover ANY orphaned run — which is exactly what the per-run
    # BackgroundTask poll driver structurally cannot do. ``minScale=1`` guarantees an instance
    # exists to run it (the runbook now pins ``--min-instances=1`` for this reason), and
    # ``run.googleapis.com/cpu-throttling: 'false'`` — MEASURED live on 2026-09-07, revision
    # nestor-api-00049-wgk — is what keeps the timer ticking between requests. With throttling
    # ON, Cloud Run cuts an idle instance's CPU and this loop would silently stop; the runbook
    # flags that annotation as load-bearing at its point of use.
    #
    # GUARDED exactly like the sweep above: startup must NEVER fail because the reconciler
    # could not start. Liveness does not depend on this extra (T-02-04 / T-23.3-32).
    app.state.reconcile_task = None
    if RECONCILE_INTERVAL_SECONDS > 0:
        try:
            # Held in a local AND on app.state: a bare create_task() result can be
            # garbage-collected mid-flight, so a strong reference is required (the app.state
            # copy is also what the shutdown assertion in the test suite reads).
            reconcile_task = asyncio.create_task(_reconcile_loop())
            app.state.reconcile_task = reconcile_task
        except Exception:  # noqa: BLE001 -- a broken reconciler must not block startup
            logger.warning("could not start the research reconcile timer", exc_info=True)
    else:
        # Announce the kill switch. A silently disabled sweep is how an operator ends up
        # believing runs are being recovered when nothing is recovering them.
        logger.warning(
            "research reconcile sweep DISABLED (NESTOR_RECONCILE_INTERVAL_S=%s); orphaned "
            "research_runs will NOT be recovered on this instance",
            RECONCILE_INTERVAL_SECONDS,
        )
    yield
    # Stop the sweep BEFORE the pool is disposed below: disposing while a sweep is mid-write
    # would surface as a confusing shutdown error, and a task dropped without being awaited
    # produces asyncio's "Task was destroyed but it is pending".
    task = getattr(app.state, "reconcile_task", None)
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
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
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

# Routers (plan 03+). NO auth dependency is attached to the bare app, so /healthz and
# /readyz below stay ANONYMOUS for the Cloud Run probes (Pitfall 1 / T-02-04).
# - auth_router: anonymous-but-self-verifying /auth/session login-sync handshake.
# - protected_router: the default-deny base (Depends(get_current_identity)) every
#   feature router inherits (AUTH-01 / T-03-17). The single
#   app.include_router(protected_router) below carries every router mounted under it; do
#   NOT add a second app.include_router(...) for those nested routers and do NOT attach
#   any auth dependency to the bare app (keeps /healthz and /readyz anonymous for the
#   Cloud Run probes).
# - admin_router: the Phase-5 superadmin-only admin surface (invite / deactivate /
#   space + template management, USER-01/03 / AUTH-04 / QA-04). Mounted UNDER
#   protected_router so it inherits get_current_identity; its own per-route
#   get_admin_session dependency adds the superadmin-only 403 gate.
protected_router.include_router(admin_router)
# - intake_router: the Phase-6 real intake feature surface (CRUD + answers batch +
#   allow-listed status transitions + skill-run/template reads, bounded at decomposed —
#   INTAKE-01/02/03/04). Mounted UNDER protected_router so it inherits
#   get_current_identity; each handler additionally Depends(get_*_repo) for its
#   tenant-scoped data access. (The Phase-4 throwaway scaffold router was removed in plan
#   04 once this real surface and its cross-tenant denial suite landed.)
protected_router.include_router(intake_router)
# - research_router: the Phase-16 research seam surface — the trigger verb
#   (POST /intakes/{id}/research: decomposed→in_research, insert research_runs, schedule the
#   pool-safe poll driver — SEAM-03) + the SSE progress stream (GET
#   /intakes/{id}/research/stream, RUN-01). Mounted UNDER protected_router so it inherits
#   get_current_identity; the trigger additionally Depends(get_tenant_repo) for its
#   tenant-scoped data access and the SSE pre-flight uses the space-scoped stream_session
#   reads. No second app.include_router for it — it rides the single protected_router include.
protected_router.include_router(research_router)
# - ai_router: the Phase-7 AI feature surface (apply / context-pack / structure-answers /
#   extract-insights / embeddings / transcribe / semantic search — AI-01..05). Mounted
#   UNDER protected_router so it inherits get_current_identity; each handler depends on
#   Identity ONLY (never get_tenant_repo — the long Claude/OpenAI call must not hold the
#   request tx) and dispatches the work via BackgroundTasks (D-05). No second
#   app.include_router for it — it rides the single protected_router include below.
protected_router.include_router(ai_router)
# - storage_router: the Phase-9 GCS storage surface (upload / signed-url / delete —
#   DOC-01/02 / INFRA-03). Mounted UNDER protected_router so it inherits
#   get_current_identity; each handler Depends(get_intake_and_source_repos) for its
#   ownership-gated, tenant-scoped data access and reaches GCS only through the
#   app.storage.gcs seam. No second app.include_router for it — it rides the single
#   protected_router include below.
protected_router.include_router(storage_router)
# - me_router: the Phase-11 i18n locale surface (GET /me + PATCH /me/locale — I18N-01/02).
#   Mounted UNDER protected_router so it inherits get_current_identity; each handler
#   additionally Depends(get_me_session) for its both-roles membership+org read. The
#   resolution + persist derive identity from the verified token only (T-11-03). No second
#   app.include_router for it — it rides the single protected_router include below.
protected_router.include_router(me_router)
app.include_router(auth_router)
app.include_router(protected_router)


@app.exception_handler(CodedError)
def _coded_error_handler(_request, exc: CodedError) -> JSONResponse:
    """Render a :class:`app.api.errors.CodedError` as ``{"detail", "code"}`` (Phase 11 / D-11).

    ADDITIVE: ``detail`` stays a plain string so the frontend transport's existing
    string-``detail`` raw-fallback path is untouched; ``code`` is the new machine-readable
    field the i18n error-codes map (11-01) reads. Existing ``HTTPException`` raises are
    unaffected — they never reach this handler and keep emitting a string ``detail`` with no
    ``code`` (backward-compat). SECURITY (T-11-05): only curated user-facing codes flow here;
    internal errors keep generic HTTPException messages, never a code or a leaked stack.
    """
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code},
        status_code=exc.status_code,
    )


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
