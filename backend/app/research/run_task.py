"""``app/research/run_task.py`` — the pool-safe Tribunal poll driver (ENGINE-07 / RUN-02).

The FastAPI trigger endpoint (Plan 03) INSERTs a ``queued`` ``research_runs`` row,
responds 202, and schedules :func:`run_poll_driver` on a ``BackgroundTask``. This
module then drives the run to a terminal state and mirrors it back — the
timeout-immune execution path. It NEVER edits the Tribunal engine; it only chooses
a brief (composed upstream in :mod:`app.research.brief`) and mirrors run state.

Two failure modes this module exists to make impossible (both inherited from the
AI-06 release contract, :func:`app.db.ai_session.run_with_session_release`):

* **T-16-06 (pool starvation):** the ~19-min drive-to-completion holds NO pooled DB
  connection. The driver is structured READ (load a PLAIN trigger-context dict →
  release) → CALL (ensure/create/poll, NO connection held) → WRITE (a fresh
  ``tenant_session`` finalizes + mails). Each per-tick mirror UPDATE
  (:func:`mirror_tick`) opens its OWN short ``tenant_session`` and releases
  immediately — ``engine.pool.checkedout()`` is 0 across the poll loop.
* **T-7-02 (forgotten 2nd-session GUC):** every write (the mirror ticks and the
  finalize) routes through :func:`app.db.ai_session.tenant_session`, which re-issues
  the transaction-local ``app.current_space_id`` GUC structurally.

Terminal-set discipline (16-RESEARCH Pitfall 3): the loop breaks on the RESEARCH
terminal set ``{"completed", "completed_degraded", "failed", "cancelled"}`` —
NEVER the skill-run success/failed vocabulary. A successful Tribunal run is
``completed`` or ``completed_degraded``, carried verbatim (D-05 boundary), and is
never remapped to the skill-run success literal. The set and its predicates live
in ONE place, :mod:`app.research.run_status`; ``parked`` is deliberately not a
member (see that module's docstring).

5xx tolerance (16-RESEARCH Pitfall 1): a 5xx from ``get_metrics`` (e.g. the residual
``needs_report_spec`` response-Literal gap) is retried a bounded number of times,
then the row is finalized ``failed`` — the BackgroundTask never crashes.

Idempotency (D-04, deterministic): the ``create_run`` idempotency key is
``uuid5(intake_id, f"attempt-{attempt}")`` so a retried trigger returns the existing
run (no double-charge) and the 3-attempt cap is natural.

Authoritative references:
- .planning/phases/16-research-trigger-progress-bridge/16-RESEARCH.md
    § Code Examples (run_task) + Pitfall 1 (5xx tolerance) + Pitfall 4 (pool starvation)
- app/db/ai_session.py (run_with_session_release / tenant_session — the release contract)
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

import httpx

from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release, tenant_session
from app.db.base import get_engine
from app.db.repository import IntakeRepository, ResearchRunRepository
from app.mail import resend
from app.mail.render import render_research_complete, render_research_failed
from app.research import tribunal_client
from app.research.bundle import build_bundle_zip
from app.research.run_status import RESEARCH_TERMINAL, is_research_success
from app.storage import gcs
from app.storage.keys import build_object_key

# WARNING level on purpose: uvicorn's default logging config drops INFO from app
# loggers (no root handler — only the WARNING+ lastResort stderr handler), and this
# driver runs headless where silence has already cost a full UAT day (16-05).
log = logging.getLogger(__name__)

#: Poll cadence in seconds between ``get_metrics`` ticks (~3s per 16-RESEARCH).
POLL_SECONDS = 3.0

#: Bounded retries on a 5xx from ``get_metrics`` before finalizing as failed
#: (16-RESEARCH Pitfall 1 — the poll driver must never crash the BackgroundTask).
_MAX_METRICS_5XX_RETRIES = 3


def get_engine_for_pool_check() -> Any:
    """Return the user-path engine — the pool the release contract must not starve.

    Exposed as a thin indirection so the pool-safety test can assert
    ``engine.pool.checkedout() == 0`` across the CALL phase against the SAME pool the
    real writes use.
    """
    return get_engine()


def load_trigger_context(
    session: Any, identity: Identity, intake_id: Any
) -> dict[str, Any]:
    """READ phase: return a PLAIN trigger-context dict (never live ORM rows).

    Resolves the intake's OWN space (a superadmin has no own space, so the
    ``research_runs`` mirror + the seam headers must carry the intake's space_id) and
    the acting-user attribution + the non-secret Tribunal service URL. Returns a plain
    dict so nothing detaches when the READ session closes (the release contract).
    """
    intake = IntakeRepository(session, identity).get(intake_id)
    if intake is None:
        # Existence-hidden: a cross-tenant/missing intake never reaches the seam.
        raise LookupError(f"intake {intake_id} not in scope")

    settings = get_settings()
    return {
        # The intake's OWN space — the tenant id forwarded to the seam + mirrored.
        "space_id": str(intake.space_id),
        "acting_user_id": identity.uid,
        "acting_email": identity.email,
        "project_title": intake.client_name or "dit intake",
        "intake_id": str(intake_id),
        "service_url": settings.tribunal_service_url,
        "app_base_url": settings.app_base_url,
    }


def mirror_tick(
    identity: Identity,
    research_run_id: Any,
    tribunal_run_id: str,
    metrics: dict[str, Any],
) -> None:
    """Mirror one ``get_metrics`` tick into ``research_runs`` in its OWN short tx.

    Opens a fresh :func:`tenant_session` (GUC re-issued), PATCHes the in-scope row's
    mirrored progress fields, and releases the connection immediately — so the poll
    loop holds no pooled connection between ticks (T-16-06). Status is carried
    VERBATIM (D-05). A missing field in ``metrics`` is simply not patched.
    """
    values: dict[str, Any] = {
        "tribunal_run_id": tribunal_run_id,
        "status": metrics.get("status"),
    }
    if metrics.get("current_stage") is not None:
        values["current_stage"] = metrics["current_stage"]
    if metrics.get("stage_detail") is not None:
        values["stage_detail"] = metrics["stage_detail"]
    if metrics.get("cost_usd_total") is not None:
        values["cost_usd_total"] = metrics["cost_usd_total"]

    with tenant_session(identity) as session:
        rowcount = ResearchRunRepository(session, identity).patch(research_run_id, **values)
    if rowcount == 0:
        # The mirror write matched NOTHING — the panel will show a run frozen at
        # "queued" while the driver works invisibly. Loud, every tick, on purpose.
        log.error(
            "mirror_tick matched 0 rows: research_run_id=%s tribunal_run_id=%s status=%s",
            research_run_id, tribunal_run_id, metrics.get("status"),
        )


def finalize_completed(
    session: Any,
    research_run_id: Any,
    metrics: dict[str, Any],
    report: dict[str, Any],
    *,
    chain_status: str | None = None,
    chain_broken_at: int | None = None,
    bundle_key: str | None = None,
) -> None:
    """WRITE (completed): persist the raw report + final mirror + Phase-17 chain state.

    Runs in the fresh WRITE :func:`tenant_session` opened by the release contract.
    Persists ``output_markdown`` (A4 — Phase 17 raw-output is then a pure UI add),
    the terminal ``status`` VERBATIM, and the final cost/stage. Uses ``func.now()``
    for ``completed_at``.

    Phase 17 (RUN-03 / D-06): the audit-chain verdict is a HARD GATE computed in the
    connection-free CALL window (no seam or GCS I/O happens here — this write only
    records the RESULT). ``chain_status`` is ``"verified"`` (bundle materialized,
    ``bundle_key`` set) or ``"broken"`` (complete-but-LOCKED — ``chain_broken_at``
    set, ``bundle_key`` stays NULL, no bundle written). All three are written even
    when None so a re-verify can reset them.
    """
    from sqlalchemy import func

    _patch_run(
        session,
        research_run_id,
        # Carries the Tribunal literal VERBATIM (D-05), so completed_degraded lands
        # on the row unchanged. Deliberately NOT a predicate — do not "fix" it.
        status=metrics.get("status", "completed"),
        current_stage=metrics.get("current_stage"),
        cost_usd_total=metrics.get("cost_usd_total"),
        output_markdown=report.get("markdown"),
        chain_status=chain_status,
        chain_broken_at=chain_broken_at,
        bundle_key=bundle_key,
        completed_at=func.now(),
    )


def finalize_failed(
    session: Any,
    research_run_id: Any,
    metrics: dict[str, Any] | None,
    error_message: str | None = None,
) -> None:
    """WRITE (failed/cancelled): finalize the row to a terminal state VERBATIM.

    Carries the Tribunal terminal ``status`` verbatim when available (``failed`` or
    ``cancelled``); defaults to ``failed`` when ``metrics`` is absent (the
    ``on_error`` path). Stamps ``error_message`` + ``completed_at``.
    """
    from sqlalchemy import func

    status = "failed"
    if metrics is not None:
        status = metrics.get("status", "failed")
        # "parked" is in the clamp because a parked run is NOT a failure — it is a
        # pause a superadmin resumes (D-17/F-01). Mislabelling it ``failed`` here
        # would destroy the resume affordance plan 15.2-16 builds on top of it.
        if status not in {"failed", "cancelled", "parked"}:
            status = "failed"

    _patch_run(
        session,
        research_run_id,
        status=status,
        error_message=error_message or _default_error(metrics),
        completed_at=func.now(),
    )


def _patch_run(session: Any, research_run_id: Any, **values: Any) -> None:
    """PATCH the ``research_runs`` row on the write session via the scoped repo.

    The write path runs under a superadmin identity (the trigger actor has no own
    space), so the repo ``_scope`` leaves the statement unchanged and the row is
    reached by id across the intake's space (the 0011 superadmin bypass policy admits
    the write). ``identity_of`` recovers the driving identity stashed on the session
    binding so the repo constructs correctly.
    """
    identity = identity_of(session)
    rowcount = ResearchRunRepository(session, identity).patch(research_run_id, **values)
    if rowcount == 0:
        log.error(
            "finalize patch matched 0 rows: research_run_id=%s values=%s",
            research_run_id, {k: v for k, v in values.items() if k != "output_markdown"},
        )
    else:
        log.warning(
            "finalize patched research_run_id=%s status=%s",
            research_run_id, values.get("status"),
        )


# The driving identity is threaded to the write helpers via a module-level slot set
# by run_poll_driver — the release contract's write_fn/on_error receive only
# (session, dto, result), not the identity, so we stash it for the finalize writers.
_ACTIVE_IDENTITY: Identity | None = None


def identity_of(session: Any) -> Identity:
    """Return the identity driving the current run (stashed by :func:`run_poll_driver`)."""
    if _ACTIVE_IDENTITY is None:  # pragma: no cover - always set by run_poll_driver
        raise RuntimeError("no active identity — call run_poll_driver")
    return _ACTIVE_IDENTITY


def _default_error(metrics: dict[str, Any] | None) -> str:
    """A terse default error message for the failed path."""
    if metrics is None:
        return "research run failed"
    return f"research run ended with status {metrics.get('status', 'failed')}"


def build_completion(
    ctx: dict[str, Any],
    research_run_id: Any,
    rid: str,
) -> dict[str, Any]:
    """CALL-phase (NO DB conn held) audit-chain gate + bundle materialization (RUN-03).

    Invoked from the tail of :func:`run_poll_driver`'s ``call_fn`` — i.e. while the
    release contract holds NO pooled DB connection (``engine.pool.checkedout() == 0``,
    T-17-07). Runs the D-06 hard gate and, ONLY on a verified chain, builds + uploads
    the immutable zip ONCE. Returns a plain dict of the values the WRITE phase then
    patches onto ``research_runs`` (the WRITE opens the tenant_session; NO I/O there).

    Steps (all connection-free):

    1. ``get_report`` — the synthesized report (already fetched today; the persisted
       ``output_markdown`` is the reliable report.md body when the live seam returns
       ``sections`` not ``markdown`` — Open Q1 / A1).
    2. ``get_research_bundle`` — the D-01-scrubbed per-provider ``cleaned_reports``.
    3. ``verify_chain`` — the D-06 gate verdict ``{ok, broken_at}``.
    4a. VERIFIED → build the zip, upload it ONCE under the server-authored
        space-scoped ``artifacts`` key (D-05 app bucket, NOT the audit bucket), and
        return ``chain_status="verified"`` + ``bundle_key``.
    4b. BROKEN → build NOTHING, upload NOTHING (complete-but-LOCKED, EU AI Act Art.
        12 posture); return ``chain_status="broken"`` + ``chain_broken_at``.

    ``report`` is threaded back so the WRITE persists ``output_markdown`` from the
    SAME fetch (no second seam call in the connected window).
    """
    seam_kwargs = dict(
        service_url=ctx["service_url"],
        space_id=ctx["space_id"],
        acting_user_id=ctx["acting_user_id"],
        acting_email=ctx["acting_email"],
    )

    report = tribunal_client.get_report(run_id=rid, **seam_kwargs)
    bundle = tribunal_client.get_research_bundle(run_id=rid, **seam_kwargs)
    verdict = tribunal_client.verify_chain(run_id=rid, **seam_kwargs)  # D-06 gate.

    completion: dict[str, Any] = {
        "report": report,
        "chain_status": None,
        "chain_broken_at": None,
        "bundle_key": None,
    }

    if verdict.get("ok"):
        # report.md must never be empty: prefer the seam markdown, else the
        # persisted output_markdown (the live report endpoint returns `sections`,
        # not `markdown` — Open Q1 / A1). Pass a report dict the pure builder reads.
        report_for_zip = dict(report)
        if not report_for_zip.get("markdown"):
            report_for_zip["markdown"] = report.get("markdown") or ""
        zip_bytes = build_bundle_zip(
            report_for_zip, bundle, report.get("sources") or []
        )
        # Server-authored, space-scoped key in the "artifacts" app bucket (D-05).
        # The deterministic per-run filename keeps the object 1:1 with the run; the
        # shared key builder adds its uuid4 uniqueness prefix (Pattern 2 idempotency
        # is by the run's single materialization, not by key reuse).
        key = build_object_key(
            ctx["space_id"],
            ctx["intake_id"],
            "artifacts",
            f"raw-output-{research_run_id}.zip",
        )
        gcs.upload_object(key, zip_bytes, content_type="application/zip")
        completion["chain_status"] = "verified"
        completion["bundle_key"] = key
        log.warning(
            "run_poll_driver bundle materialized: research_run_id=%s key=%s",
            research_run_id, key,
        )
    else:
        completion["chain_status"] = "broken"
        completion["chain_broken_at"] = verdict.get("broken_at")
        # Loud on purpose: a broken chain is a legal-posture event (complete-but-locked).
        log.error(
            "run_poll_driver chain BROKEN (complete-but-locked, no bundle): "
            "research_run_id=%s broken_at=%s",
            research_run_id, verdict.get("broken_at"),
        )

    return completion


def run_poll_driver(
    identity: Identity,
    intake_id: Any,
    research_run_id: Any,
    brief: str,
    attempt: int,
) -> None:
    """Drive a Tribunal run to a terminal state pool-safely; mirror + mail the result.

    Structured through :func:`app.db.ai_session.run_with_session_release`:

    * **READ** (:func:`load_trigger_context`) returns a PLAIN dict (space/acting/url)
      then releases the connection;
    * **CALL** holds NO connection: ``ensure_org`` → ``ensure_project`` →
      ``create_run`` (deterministic ``uuid5`` idempotency key, D-04) → poll loop
      (``get_metrics`` → :func:`mirror_tick` per tick → break on the RESEARCH terminal
      set) with bounded 5xx retries on ``get_metrics`` (Pitfall 1);
    * **CALL tail (completed)** — :func:`build_completion` runs the D-06 audit-chain
      gate + the D-01-scrubbed bundle fetch + zip build + GCS upload, ALL in the
      connection-free window (T-17-07); it returns the report + chain verdict +
      ``bundle_key`` as the 3rd result element;
    * **WRITE** (a fresh ``tenant_session``): on ``completed`` persist
      ``output_markdown`` (A4) + the chain/bundle state + finalize + mail the
      completion variant to the acting superadmin (D-10, on BOTH verified and broken
      — no broken-chain variant, D-07); else finalize failed + mail the failure
      variant;
    * **on_error** finalizes the row to EXACTLY ``failed`` on ANY exception (D-04).

    Never returns a value (a BackgroundTask); never raises out of the task (``on_error``
    swallows exceptions into a ``failed`` finalize).
    """
    global _ACTIVE_IDENTITY
    _ACTIVE_IDENTITY = identity

    # WARNING on purpose — see the module logger note. This line is the difference
    # between "the task never ran" and "the task died at X" in the next incident.
    log.warning(
        "run_poll_driver START: intake=%s research_run_id=%s attempt=%s",
        intake_id, research_run_id, attempt,
    )

    def read_fn(session: Any) -> dict[str, Any]:
        return load_trigger_context(session, identity, intake_id)

    def call_fn(ctx: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        seam_kwargs = dict(
            service_url=ctx["service_url"],
            space_id=ctx["space_id"],
            acting_user_id=ctx["acting_user_id"],
            acting_email=ctx["acting_email"],
        )
        tribunal_client.ensure_org(**seam_kwargs)
        project_id = tribunal_client.ensure_project(**seam_kwargs)

        # D-04 deterministic idempotency key, keyed on the MIRROR ROW id (not the
        # attempt number — live finding 2026-07-21): an attempt-number key survives
        # row cleanup, so a replayed attempt number idempotently returns a DEAD
        # engine run from a previous cycle (the burned-key insta-fail loop). The
        # research_run_id is unique per trigger and stable across create_run HTTP
        # retries within this driver — the double-charge protection D-04 wants.
        idem = str(uuid.uuid5(uuid.UUID(str(intake_id)), str(research_run_id)))
        run = tribunal_client.create_run(
            project_id=project_id,
            brief=brief,
            idempotency_key=idem,
            **seam_kwargs,
        )
        rid = run["id"]
        log.warning(
            "run_poll_driver create_run: research_run_id=%s tribunal_run_id=%s "
            "engine_status=%s (an idempotent return of an old run shows here as a "
            "non-queued engine_status)",
            research_run_id, rid, run.get("status"),
        )

        metrics: dict[str, Any] = {"status": run.get("status", "queued")}
        consecutive_5xx = 0
        while True:  # NO db connection held across this loop (T-16-06).
            try:
                metrics = tribunal_client.get_metrics(run_id=rid, **seam_kwargs)
                consecutive_5xx = 0
            except httpx.HTTPStatusError as exc:
                # 5xx tolerance (Pitfall 1): retry bounded, then finalize failed.
                status_code = exc.response.status_code if exc.response else 0
                if status_code >= 500:
                    consecutive_5xx += 1
                    if consecutive_5xx > _MAX_METRICS_5XX_RETRIES:
                        return (
                            rid,
                            {
                                "status": "failed",
                                "error_message": (
                                    f"metrics 5xx after {_MAX_METRICS_5XX_RETRIES} "
                                    "retries"
                                ),
                            },
                            None,  # failed terminal → no completion bundle.
                        )
                    time.sleep(POLL_SECONDS)
                    continue
                raise  # a 4xx is a real error → on_error finalizes failed.

            mirror_tick(identity, research_run_id, rid, metrics)
            if metrics.get("status") in RESEARCH_TERMINAL:
                log.warning(
                    "run_poll_driver terminal: research_run_id=%s tribunal_run_id=%s "
                    "status=%s", research_run_id, rid, metrics.get("status"),
                )
                # Phase 17 (RUN-03): the completion I/O — the D-06 audit-chain gate,
                # the D-01-scrubbed bundle fetch, the zip build, and the GCS upload —
                # runs HERE, in the connection-free CALL window (T-17-07: no pooled DB
                # connection is held across seam/GCS I/O). The WRITE phase only patches
                # the row. Non-success terminals carry completion=None (no bundle).
                # D-09: a completed_degraded run MUST get the bundle too — gating
                # this on the bare "completed" literal would leave a degraded run
                # terminal with no bundle, no report row and no mail.
                completion = None
                if is_research_success(metrics.get("status")):
                    completion = build_completion(ctx, research_run_id, rid)
                return rid, metrics, completion
            time.sleep(POLL_SECONDS)

    def write_fn(
        session: Any, ctx: dict[str, Any], result: tuple[str, dict, dict | None]
    ) -> None:
        # Phase 17: the CALL phase now returns a THIRD element — the completion dict
        # (report + chain verdict + bundle_key) computed in the connection-free
        # window — or None for a non-completed terminal. The report is NO LONGER
        # fetched here (that seam call moved to the pool-safe CALL window, T-17-07).
        rid, metrics, completion = result
        to = [ctx["acting_email"]] if ctx.get("acting_email") else []
        cta_url = _admin_cta(ctx)

        # D-09: completed AND completed_degraded both finalize + mail. There is no
        # degraded mail variant in this plan (park/degrade copy is 15.2-16's
        # render_research_parked work), and gating the mail would silently drop the
        # operator's only notification that a ~$45 run finished.
        if is_research_success(metrics.get("status")):
            # completion is always present for a success terminal (build_completion).
            completion = completion or {}
            report = completion.get("report") or {}
            finalize_completed(
                session,
                research_run_id,
                metrics,
                report,
                chain_status=completion.get("chain_status"),
                chain_broken_at=completion.get("chain_broken_at"),
                bundle_key=completion.get("bundle_key"),
            )
            # D-07: the NORMAL completion mail sends on BOTH the verified and the
            # broken-chain path — there is NO broken-chain email variant. Do NOT gate
            # the mail on chain_status.
            if to:
                html = render_research_complete(
                    project_title=ctx["project_title"],
                    duration_min=_duration_min(metrics),
                    cost_usd=metrics.get("cost_usd_total"),
                    cta_url=cta_url,
                    app_base_url=ctx.get("app_base_url"),
                )
                resend.send(
                    to=to,
                    subject="Je onderzoek is klaar",
                    html=html,
                )
        else:
            error_message = metrics.get("error_message") or _default_error(metrics)
            finalize_failed(session, research_run_id, metrics, error_message)
            if to:
                html = render_research_failed(
                    project_title=ctx["project_title"],
                    error_summary=error_message,
                    cta_url=cta_url,
                    app_base_url=ctx.get("app_base_url"),
                )
                resend.send(
                    to=to,
                    subject="Je onderzoek is mislukt",
                    html=html,
                )

    def on_error(session: Any, ctx: dict[str, Any] | None, exc: Exception) -> None:
        # Finalize the row to EXACTLY failed on ANY exception (D-04). The mail is
        # best-effort — a finalize must never be blocked by a mail failure.
        finalize_failed(session, research_run_id, None, error_message=str(exc))
        if ctx and ctx.get("acting_email"):
            try:
                html = render_research_failed(
                    project_title=ctx.get("project_title", "je onderzoek"),
                    error_summary=str(exc),
                    cta_url=_admin_cta(ctx),
                    app_base_url=ctx.get("app_base_url"),
                )
                resend.send(
                    to=[ctx["acting_email"]],
                    subject="Je onderzoek is mislukt",
                    html=html,
                )
            except Exception:  # noqa: BLE001 - mail is best-effort on the error path
                pass

    try:
        run_with_session_release(
            identity, read_fn, call_fn, write_fn, on_error=on_error
        )
        log.warning("run_poll_driver DONE: research_run_id=%s", research_run_id)
    except BaseException:
        # Belt-and-braces: on_error already finalizes, but if IT fails (or the read
        # phase dies before any context exists) this task must never end silently
        # again — that silence cost the 16-05 UAT a full day.
        log.exception(
            "run_poll_driver CRASHED: research_run_id=%s intake=%s attempt=%s",
            research_run_id, intake_id, attempt,
        )


def _admin_cta(ctx: dict[str, Any]) -> str:
    """Compose the admin intake-route CTA (NO token — NOTIF-01)."""
    base = ctx.get("app_base_url") or ""
    return f"{base}/admin/pulse/intakes/{ctx.get('intake_id', '')}"


def _duration_min(metrics: dict[str, Any]) -> int | None:
    """Return the elapsed run time in whole minutes, if the metrics expose it."""
    elapsed = metrics.get("elapsed_seconds")
    if elapsed is None:
        return None
    try:
        return int(round(float(elapsed) / 60.0))
    except (TypeError, ValueError):
        return None
