"""The intake-side research seam router — the trigger verb + the SSE progress stream.

Two surfaces, both space-scoped and bounded by the same existence-hidden 404 / null-space
403 discipline the intake surface uses (D-04 / D-07):

* ``POST /intakes/{intake_id}/research`` (:func:`trigger_research`, SEAM-03) — the discrete
  "start deep research" verb (NOT a generic ``PATCH status``). It flips ``decomposed →
  in_research`` on the allow-listed transition map, enforces the 3-attempt cap (D-04),
  composes a pause-gate-safe brief, inserts the ``research_runs`` row, audits ``{from,to}``
  in the SAME tx, schedules the pool-safe poll driver, and returns ``202`` with the run id.
  The brief is composed marker-free upstream so a seam run can never opt into the
  interactive-report pause gate (SEAM-04 by composition — see :mod:`app.research.brief`).

* ``GET /intakes/{intake_id}/research/stream`` (:func:`stream_research_run`, RUN-01) — the
  ONE deliberate ``async def`` handler, cloned from ``intake_routes.stream_skill_runs`` with
  the RESEARCH terminal set ``{completed, failed, cancelled}`` (NOT the skill-run
  success/failed vocabulary — 16-RESEARCH Pitfall 3). It mirrors the
  ``research_runs`` row to the browser with a dynamic stage trace and closes on a terminal
  status. Every DB touch goes through :func:`run_in_threadpool` (blocking pg8000 must never
  run on the event loop).

Invariants (mirrors ``intake_routes`` — the source of truth):

* D-03 — this module imports NO raw DB symbol (``get_engine`` / ``sessionmaker`` / ...); it
  reaches the DB only through the injected ``Depends(get_tenant_repo)`` repo and the scoped
  reads in :mod:`app.db.stream_session`. The ``ci_no_raw_db_access.sh`` grep-guard stays green.
* TENANT-02 — ``space_id`` is NEVER read from the request; it comes solely from the verified
  ``Identity`` (via the repo) or the intake's OWN resolved space (the superadmin insert path).
* AUTH-01 — mounted UNDER ``protected_router`` in ``app/main.py`` so it inherits
  ``Depends(get_current_identity)`` and is never anonymous.

Sync ``def`` handlers except the ONE SSE ``async def`` (pg8000 is blocking; FastAPI runs
sync handlers in a threadpool — an async handler calling the sync engine would stall the
event loop). Do NOT convert :func:`trigger_research` (or any other handler) to async.
"""

from __future__ import annotations

import json
import logging

import anyio
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db import audit
from app.db.ai_session import tenant_session
from app.db.repository import IntakeRepository, ResearchRunRepository
from app.db.session import get_tenant_repo

# The stream's DB access + the trigger's brief-input read live in app/db/stream_session.py —
# NOT raw DB symbols — so this route module stays clean for ci_no_raw_db_access.sh (D-03).
from app.db.stream_session import (
    check_intake_in_scope,
    read_brief_inputs,
    read_latest_research_run_dict,
)
from app.research import brief as brief_mod
from app.research import tribunal_client
from app.research.bundle import build_bundle_zip
from app.research.run_task import run_poll_driver
from app.storage import gcs
from app.storage.keys import build_object_key

_log = logging.getLogger(__name__)

# The research feature router. Carries NO auth dependency of its own — mounted UNDER
# protected_router in app/main.py (inherits get_current_identity). Same /intakes prefix as
# intake_router so both surfaces share the intake namespace.
research_router = APIRouter(prefix="/intakes", tags=["research"])


# ---------------------------------------------------------------------------
# Trigger verb (discrete named transition, allow-listed to decomposed→in_research)
# ---------------------------------------------------------------------------
#
# The transition map is the data-layer enforcement of the ONLY reachable research target: a
# run may start ONLY from ``decomposed``. A status with no entry raises 409 — so triggering
# research from any other status is STRUCTURALLY impossible, not merely blocked by CI. This
# mirrors intake_routes._SUBMIT_TRANSITIONS / _next_submit_status.
_RESEARCH_TRANSITIONS: dict[str, str] = {"decomposed": "in_research"}

#: Latest-run statuses that permit a RE-trigger while the intake is already
#: ``in_research`` (live finding 2026-07-21): ``failed`` / ``cancelled`` are the
#: mirror's terminal failure states (the 16-04 failure card's retry path — which
#: was previously unreachable because the transition map 409'd everything but
#: ``decomposed``), and ``needs_input`` is the engine's parked clarification
#: state, which the intake side has no surface for — a re-trigger with the
#: repaired brief supersedes the parked run (the old engine run stays parked and
#: consumes nothing). An actively ``queued``/``running`` run still 409s.
_RETRYABLE_RUN_STATUSES = {"failed", "cancelled", "needs_input"}

#: The 3-attempt cap (D-04): a 4th trigger for an intake returns needs_investigation and
#: makes NO seam call / schedules NO driver (a runaway retrigger must not re-charge Tribunal).
_MAX_ATTEMPTS = 3


def _next_research_status(current: str) -> str:
    """Return the research-transition target for ``current``, or 409 if not allow-listed."""
    try:
        return _RESEARCH_TRANSITIONS[current]
    except KeyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot start research for an intake in status {current!r}",
        )


@research_router.post("/{intake_id}/research", status_code=status.HTTP_202_ACCEPTED)
def trigger_research(
    intake_id: str,
    background: BackgroundTasks,
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> dict:
    """Start deep research for a ``decomposed`` intake (SEAM-03).

    Flips ``decomposed → in_research``, composes a pause-gate-safe brief, inserts the
    ``research_runs`` row (``status=queued``, ``attempt=n``), audits ``{from,to}`` in the
    SAME tx, schedules the pool-safe poll driver, and returns ``202 {research_run_id}``.

    * 404 if the (in-scope) intake does not exist (D-07 — existence hidden; never 403/200).
    * 409 if the current status is not ``decomposed`` (the scope-ceiling wall).
    * When ``_MAX_ATTEMPTS`` prior research runs already exist for the intake, the next
      trigger returns a ``needs_investigation`` response and makes NO seam call / schedules
      NO driver (D-04 — a runaway retrigger must not re-charge Tribunal).

    The ``audit_log`` row is written on ``repo.session`` so it commits/rolls back together
    with the status change (one-tx, Pitfall 2). ``metadata`` is structured ``{"from","to"}``
    only — never a link or token (T-16-11). The driver is scheduled AFTER the 202 via
    ``BackgroundTasks`` so the long (~19-min) Tribunal drive holds no request connection.
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Attempt cap FIRST (D-04): count prior research runs on the same in-scope session.
    run_repo = ResearchRunRepository(repo.session, identity)
    prior = run_repo.list_for_intake(intake_id)
    if len(prior) >= _MAX_ATTEMPTS:
        # No status flip, no seam call, no driver — the run is handed to a human.
        _log.warning(
            "research attempt cap reached for intake %s (%d prior runs) — "
            "returning needs_investigation, no driver scheduled",
            intake_id,
            len(prior),
        )
        return {
            "research_run_id": None,
            "status": "needs_investigation",
            "attempts": len(prior),
        }

    old_status = intake.status
    if old_status == "in_research":
        # Retry path: allowed ONLY when the latest run is dead (failed/cancelled)
        # or parked (needs_input). list_for_intake orders newest-first.
        latest = prior[0] if prior else None
        if latest is None or latest.status not in _RETRYABLE_RUN_STATUSES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Research is already running for this intake",
            )
        new_status = "in_research"
    else:
        new_status = _next_research_status(old_status)  # 409 otherwise
    attempt = len(prior) + 1

    # Compose the brief BEFORE the flip so a brief-input read failure never leaves a
    # half-transitioned intake. Read the decomposition + questions in scope (plain dicts).
    inputs = read_brief_inputs(identity, intake_id)
    if inputs is None:  # pragma: no cover - intake was in-scope above (race)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Empty-brief guard (live finding 2026-07-21): a brief with zero validated
    # questions makes the engine park the run as ``needs_input`` — a state the
    # intake side has no surface for. Refuse BEFORE any status flip or seam call.
    final_questions = brief_mod.validated_questions(
        inputs["intake"], inputs["questions"]
    )
    if not final_questions:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "Intake has no validated research questions — cannot start research "
            "on an empty brief",
        )

    brief = brief_mod.assemble_brief(
        inputs["intake"],
        inputs["decomposition"],
        final_questions,
        context_pack_text=inputs.get("context_pack_text"),
    )

    # COMMITTED-BEFORE-SCHEDULE (root cause of the 16-05 silent driver, live finding
    # 2026-07-21): the BackgroundTask driver runs BEFORE the request dependency's
    # transaction commits, so a driver scheduled against the REQUEST session's
    # uncommitted writes (a) finds no research_runs row — every mirror/finalize
    # patch matched 0 rows and the panel froze at "queued"; (b) leaves the intake
    # row lock held for the driver's whole lifetime — the observed 900s concurrent-
    # trigger hang; and (c) loses the entire trigger on instance death (rollback —
    # the 18:08 vanished rows). The flip + audit + run-row insert therefore run in
    # their OWN short tenant_session that COMMITS on block exit — strictly before
    # add_task — mirroring create_running_skill_run (AI-06), which is why the AI
    # skill routes never exhibited this failure mode.
    #
    # The superadmin path (no own space) writes into the intake's OWN space via
    # create_in_space; the user path uses create() (space_id injected from the
    # Identity). space_id is NEVER a request input (TENANT-02).
    intake_space_id = intake.space_id
    values = dict(intake_id=intake_id, status="queued", attempt=attempt)
    with tenant_session(identity) as txs:
        IntakeRepository(txs, identity).patch(intake_id, status=new_status)
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="intake.status_changed",
            target=str(intake_id),
            space_id=intake_space_id,
            metadata={"from": old_status, "to": new_status},
        )
        tx_runs = ResearchRunRepository(txs, identity)
        if identity.role == "superadmin":
            run = tx_runs.create_in_space(intake_space_id, **values)
        else:
            run = tx_runs.create(**values)
        # Captured INSIDE the tx: expire_on_commit detaches `run` at block exit.
        research_run_id = str(run.id)

    # Schedule the pool-safe poll driver AFTER the 202 (the ~19-min drive holds no
    # request connection). It mirrors each tick into research_runs and mails on terminal.
    background.add_task(
        run_poll_driver, identity, intake_id, research_run_id, brief, attempt
    )
    # WARNING level: pairs with run_poll_driver's START line — "scheduled but no
    # START" isolates a BackgroundTask that never executed (the 16-05 silent-driver
    # failure mode) without needing DB forensics.
    _log.warning(
        "research driver scheduled: research_run_id=%s attempt=%s", research_run_id, attempt
    )
    return {"research_run_id": research_run_id, "status": "queued"}


# ---------------------------------------------------------------------------
# Raw-output download + audit-chain re-verify (superadmin-only, space-scoped)
# ---------------------------------------------------------------------------
#
# Two sync-``def`` handlers realizing RUN-03 SC1 (superadmin download) + SC2
# (client / cross-space denial). Both inherit ``get_current_identity`` from
# protected_router (no own auth dep) and reach the DB ONLY through the injected
# ``get_tenant_repo`` + ``tenant_session`` — D-03's ci_no_raw_db_access grep-guard
# stays green (NO ``get_engine`` / ``sessionmaker`` import).
#
# DENIAL DISCIPLINE (Pitfall 5 / T-17-10 / T-17-11): a non-superadmin caller and a
# cross-tenant / missing run are BOTH existence-hidden 404 — never 403, never
# 200-with-data — because RUN-03 says a client can NEVER reach the raw output and a
# 403 would leak that the resource exists. The superadmin role-check fires FIRST,
# so a null-space user hits the role gate → 404 (not the null-space 403).


def _build_and_store_bundle(
    identity: Identity,
    intake,
    run,
) -> str:
    """Driver-death recovery: rebuild the raw-output zip + persist ``bundle_key`` (Pattern 2).

    The normal completion path (Plan 02 :func:`app.research.run_task.build_completion`)
    materializes the bundle ONCE on the verified terminal. When that never ran (the
    BackgroundTask driver died after finalize but before the build — or on a pre-Phase-17
    row) a verified run carries ``bundle_key IS NULL``. This helper lazily rebuilds it.

    POOL SAFETY (T-17-14, mirrors Plan 02): all seam + GCS I/O runs with NO DB connection
    held — the injected request repo's session is NOT used here. A fresh ``tenant_session``
    is opened ONLY to patch ``research_runs.bundle_key`` after the upload. Returns the new key.
    """
    settings = get_settings()
    space_id = str(intake.space_id)
    seam_kwargs = dict(
        service_url=settings.tribunal_service_url,
        space_id=space_id,
        acting_user_id=identity.uid,
        acting_email=identity.email,
    )
    rid = run.tribunal_run_id

    # Seam + build + upload — connection-free window (no session held).
    report = tribunal_client.get_report(run_id=rid, **seam_kwargs)
    bundle = tribunal_client.get_research_bundle(run_id=rid, **seam_kwargs)
    report_for_zip = dict(report)
    if not report_for_zip.get("markdown"):
        # Prefer the persisted output_markdown (the live report endpoint returns
        # ``sections`` not ``markdown`` — Open Q1 / A1), else empty.
        report_for_zip["markdown"] = report.get("markdown") or run.output_markdown or ""
    zip_bytes = build_bundle_zip(report_for_zip, bundle, report.get("sources") or [])
    key = build_object_key(
        space_id,
        str(intake.id),
        "artifacts",
        f"raw-output-{run.id}.zip",
    )
    gcs.upload_object(key, zip_bytes, content_type="application/zip")

    # WRITE: open a fresh scoped session ONLY to patch the key (no I/O here).
    with tenant_session(identity) as txs:
        ResearchRunRepository(txs, identity).patch(run.id, bundle_key=key)

    _log.warning(
        "bundle lazily rebuilt on download: research_run_id=%s key=%s", run.id, key
    )
    return key


def _superadmin_gate(identity: Identity = Depends(get_current_identity)) -> Identity:
    """Superadmin role gate as a DEPENDENCY (existence-hidden 404, Pitfall 5).

    Declared BEFORE ``get_tenant_repo`` in the download/re-verify signatures so it
    resolves first: a non-superadmin caller — including a null-space user — hits this
    404 before ``get_tenant_repo`` can raise its null-space default-deny 403 (which
    would leak that the endpoint exists; the denial suite pins EXACTLY 404).
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    return identity


@research_router.get("/{intake_id}/research/{run_id}/bundle-url")
def get_bundle_url(
    intake_id: str,
    run_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Mint a signed download URL for a verified completed run's raw-output bundle (RUN-03 SC1).

    Superadmin-only + space-scoped, existence-hidden throughout:

    * ``identity.role != "superadmin"`` → 404 (Open Q2 defense-in-depth; a client is
      user-role and RUN-03 says it can NEVER reach the download — Pitfall 5, NOT 403).
    * a cross-tenant / missing intake or run → 404 (existence hidden, D-07).
    * ``status != "completed"`` or ``chain_status != "verified"`` → 409 (the D-06/D-09
      complete-but-locked availability gate).
    * ``bundle_key IS NULL`` on a verified run → driver-death recovery: build + upload the
      bundle lazily (:func:`_build_and_store_bundle`), then mint against the new key.

    Returns ``{"url", "expires_in"}`` — TTL 300s clamped ≤900s, forced attachment
    disposition (T-17-12 / T-17-13, emitted inside the GCS seam).
    """
    # Superadmin gate FIRST (existence-hidden — a client / user-role caller sees 404).
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Availability gate (D-06/D-09): only a completed + verified run may be downloaded.
    if run.status != "completed" or run.chain_status != "verified":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Raw output is not available"
        )

    key = run.bundle_key
    if key is None:
        # Driver-death recovery (Pattern 2): build + upload + persist the key lazily.
        key = _build_and_store_bundle(identity, intake, run)

    url = gcs.signed_download_url(
        key,
        ttl_seconds=300,
        filename=f"raw-output-{run_id}.zip",
        content_type="application/zip",
    )
    # Advertise the SAME clamped ceiling the seam actually signed (D-10).
    return {"url": url, "expires_in": gcs._clamp_ttl(300)}


@research_router.post("/{intake_id}/research/{run_id}/verify-chain")
def reverify_chain(
    intake_id: str,
    run_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Re-run ``verify_chain`` and lift the lock on a now-passing audit chain (RUN-03 / D-08).

    Same superadmin-only + space-scoped existence-hidden discipline as
    :func:`get_bundle_url`. Runs the ENGINE-04 legal gate again OUTSIDE any DB session (seam
    I/O holds no connection, T-17-14), then patches the lock state in a fresh
    ``tenant_session``:

    * verdict ``ok`` → ``chain_status="verified"``, ``chain_broken_at=None`` (lock lifts);
    * else → ``chain_status="broken"``, ``chain_broken_at=<broken_at>`` (lock stays).

    LOCK-STATE ONLY (D-08): a now-verified re-verify does NOT auto-build the bundle here — the
    next download click does the build-on-download-if-missing. The re-verify action is audited
    in the SAME tx as the patch. Returns ``{"chain_status": <new status>}``.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Re-run the D-06 gate OUTSIDE any DB session (seam I/O holds no connection, T-17-14).
    settings = get_settings()
    intake_space_id = intake.space_id
    verdict = tribunal_client.verify_chain(
        run_id=run.tribunal_run_id,
        service_url=settings.tribunal_service_url,
        space_id=str(intake_space_id),
        acting_user_id=identity.uid,
        acting_email=identity.email,
    )

    if verdict.get("ok"):
        new_status = "verified"
        new_broken_at = None
    else:
        new_status = "broken"
        new_broken_at = verdict.get("broken_at")

    # WRITE: patch the lock state + audit the re-verify in ONE short tx.
    with tenant_session(identity) as txs:
        ResearchRunRepository(txs, identity).patch(
            run_id, chain_status=new_status, chain_broken_at=new_broken_at
        )
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="research.chain_reverified",
            target=str(run_id),
            space_id=intake_space_id,
            metadata={"chain_status": new_status},
        )

    return {"chain_status": new_status}


# ---------------------------------------------------------------------------
# Phase 15 operator read proxies (SEAM-01, superadmin-only, space-scoped)
# ---------------------------------------------------------------------------
#
# Three sync-``def`` proxies over the Plan 15-03 tribunal read endpoints
# (verification report / citation source / audit-body drill-down). Same
# superadmin-only + space-scoped + existence-hidden discipline as
# :func:`get_bundle_url`: the ``_superadmin_gate`` dependency + a defense-in-depth
# in-body 404 (Pitfall 5 — a client / cross-tenant caller can NEVER distinguish
# existence, never 403/200), an intake-existence 404, and a run-scope 404
# (``run.intake_id != intake_id``). The seam call happens OUTSIDE any held DB
# session (mirrors get_bundle_url) so the ~seam round-trip holds no connection.
# These enforce 16-D-08 (the client sees nothing) and keep the intake backend the
# SOLE caller of Tribunal (the frontend never calls it directly). Persists NOTHING.


@research_router.get("/{intake_id}/research/{run_id}/verification")
def get_research_verification(
    intake_id: str,
    run_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Proxy a run's verification report to the superadmin operator surface (SEAM-01).

    Superadmin-only + space-scoped, existence-hidden throughout (mirrors
    :func:`get_bundle_url`):

    * ``identity.role != "superadmin"`` → 404 (defense-in-depth; a client is user-role
      and 16-D-08 says it can NEVER reach this — Pitfall 5, NOT 403).
    * a cross-tenant / missing intake or run → 404 (existence hidden, D-07).

    The seam call (:func:`tribunal_client.get_verification`) runs OUTSIDE any held DB
    session; its JSON (the STAKEHOLDER-NOTES verification shape) is returned verbatim.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Seam call OUTSIDE the held DB session (mirrors get_bundle_url's connection-free window).
    settings = get_settings()
    return tribunal_client.get_verification(
        service_url=settings.tribunal_service_url,
        space_id=str(intake.space_id),
        acting_user_id=identity.uid,
        acting_email=identity.email,
        run_id=run.tribunal_run_id,
    )


@research_router.get("/{intake_id}/research/sources/{source_id}")
def get_research_source(
    intake_id: str,
    source_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Proxy a research-citation source snapshot to the superadmin surface (SEAM-01).

    Same superadmin-only + space-scoped existence-hidden discipline as
    :func:`get_research_verification`: role gate (404), intake-existence (404). This is
    the RESEARCH-CITATION source behind a ``[n]`` — a DISTINCT concern from the
    intake-upload ``sources`` surface (do NOT overload that). The seam call runs OUTSIDE
    any held DB session; its JSON is returned verbatim.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Seam call OUTSIDE the held DB session (the source is scoped by the tenant header;
    # tribunal RLS 404s a cross-tenant/unknown source_id).
    settings = get_settings()
    return tribunal_client.get_source(
        service_url=settings.tribunal_service_url,
        space_id=str(intake.space_id),
        acting_user_id=identity.uid,
        acting_email=identity.email,
        source_id=source_id,
    )


@research_router.get("/{intake_id}/research/{run_id}/audit/{audit_id}")
def get_research_audit_body(
    intake_id: str,
    run_id: str,
    audit_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Proxy a run's redacted audit-body drill-down to the superadmin surface (SEAM-01).

    Same superadmin-only + space-scoped existence-hidden discipline as
    :func:`get_research_verification`: role gate (404), intake-existence (404), run-scope
    (404 if ``run is None or run.intake_id != intake_id``). This is the D15 feed
    drill-down target — the ALREADY-REDACTED audit body. The seam call
    (:func:`tribunal_client.get_audit_body`) runs OUTSIDE any held DB session; its JSON
    (provider/model/request/response, NO hash) is returned verbatim.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Seam call OUTSIDE the held DB session; tribunal RLS 404s a cross-tenant/unknown audit.
    settings = get_settings()
    return tribunal_client.get_audit_body(
        service_url=settings.tribunal_service_url,
        space_id=str(intake.space_id),
        acting_user_id=identity.uid,
        acting_email=identity.email,
        run_id=run.tribunal_run_id,
        audit_id=audit_id,
    )


# ---------------------------------------------------------------------------
# SSE research stream (the ONE async def — cloned from stream_skill_runs)
# ---------------------------------------------------------------------------
#
# Injectable knobs (module-level so tests can monkeypatch them tiny — mirrors intake_routes).
TICK_SECONDS = 2.0  # one indexed SELECT every 2s
HEARTBEAT_SECONDS = 15.0  # ``: ping`` keeps proxies/Cloud Run from reaping idle streams
MAX_STREAM_SECONDS = 10 * 60  # in-handler cap; a run this long is treated as hung
# The RESEARCH terminal set — Tribunal literals carried VERBATIM (D-05 boundary). NEVER the
# skill-run success/failed vocabulary (16-RESEARCH Pitfall 3 / AP-6).
RESEARCH_TERMINAL = {"completed", "failed", "cancelled"}
# Defeat proxy buffering so events arrive live per-tick, not in a burst at close.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _sse_data(view: dict | None) -> str:
    """Frame one SSE data event. ``view`` may be ``None`` → emits ``data: null``."""
    return f"data: {json.dumps(view)}\n\n"


@research_router.get("/{intake_id}/research/stream")
async def stream_research_run(
    intake_id: str,
    request: Request,
    identity: Identity = Depends(get_current_identity),
) -> StreamingResponse:
    """Stream the intake's latest research-run state as ``text/event-stream`` (RUN-01).

    The ONLY ``async def`` added by this plan (cloned from
    ``intake_routes.stream_skill_runs``): every DB touch goes through
    :func:`run_in_threadpool` so the blocking pg8000 read never runs on the event loop, and
    ``anyio.sleep`` between ticks releases the thread. Do NOT convert any other handler.

    PRE-FLIGHT (D-04, runs BEFORE the stream opens so the denial test is a plain GET):
    ``check_intake_in_scope`` in the threadpool — a ``PermissionError`` (null-space user)
    → 403, a falsy result (cross-tenant / missing) → existence-hidden 404.

    STREAM: a snapshot event at connect, then data events only when the DB state differs
    from the last sent (emit-on-change), a ``: ping`` heartbeat every ~15s, and a hard
    10-min cap. Closes on a terminal status in :data:`RESEARCH_TERMINAL` or on client
    disconnect. The frame carries ``current_stage`` + ``stage_detail`` so the frontend
    renders the stage list DYNAMICALLY (no hardcoded stage count).
    """
    # Pre-flight in-scope 404/403 (D-04) — the sync/pg8000 read runs in the threadpool.
    try:
        in_scope = await run_in_threadpool(check_intake_in_scope, identity, intake_id)
    except PermissionError:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No space — not authorized")
    if not in_scope:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    async def event_gen():
        started = anyio.current_time()
        last_beat = started
        # Snapshot at connect. view may be None → ``data: null``.
        view = await run_in_threadpool(
            read_latest_research_run_dict, identity, intake_id
        )
        yield _sse_data(view)
        last_sent = view
        if view is not None and view["status"] in RESEARCH_TERMINAL:
            return
        while True:
            if await request.is_disconnected():  # free abandoned streams promptly
                return
            if anyio.current_time() - started > MAX_STREAM_SECONDS:  # 10-min cap
                return
            await anyio.sleep(TICK_SECONDS)  # thread released here
            if await request.is_disconnected():  # re-check post-sleep — skip wasted read
                return
            view = await run_in_threadpool(
                read_latest_research_run_dict, identity, intake_id
            )
            if view != last_sent:  # emit-on-change
                yield _sse_data(view)
                last_sent = view
                # Reset the heartbeat clock on ANY frame — the invariant is "some byte
                # every ~15s", so a data emit defers the next ping just like a ping does.
                last_beat = anyio.current_time()
                if view is not None and view["status"] in RESEARCH_TERMINAL:
                    return
            elif anyio.current_time() - last_beat >= HEARTBEAT_SECONDS:
                yield ": ping\n\n"  # comment heartbeat
                last_beat = anyio.current_time()

    return StreamingResponse(
        event_gen(), media_type="text/event-stream", headers=SSE_HEADERS
    )
