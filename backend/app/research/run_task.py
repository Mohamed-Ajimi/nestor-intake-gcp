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
terminal set ``{"completed", "failed", "cancelled"}`` — NEVER the skill-run
``{"succeeded", "failed"}`` vocabulary. A successful Tribunal run is ``completed``,
carried verbatim (D-05 boundary).

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

#: Poll cadence in seconds between ``get_metrics`` ticks (~3s per 16-RESEARCH).
POLL_SECONDS = 3.0

#: The RESEARCH terminal set — Tribunal literals carried VERBATIM (D-05 boundary).
#: NEVER the skill-run ``{"succeeded", "failed"}`` vocabulary (Pitfall 3).
_RESEARCH_TERMINAL = {"completed", "failed", "cancelled"}

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
        ResearchRunRepository(session, identity).patch(research_run_id, **values)


def finalize_completed(
    session: Any,
    research_run_id: Any,
    metrics: dict[str, Any],
    report: dict[str, Any],
) -> None:
    """WRITE (completed): persist the raw report + final mirror fields (A4).

    Runs in the fresh WRITE :func:`tenant_session` opened by the release contract.
    Persists ``output_markdown`` (A4 — Phase 17 raw-output is then a pure UI add),
    the terminal ``status`` VERBATIM, and the final cost/stage. Uses ``func.now()``
    for ``completed_at``.
    """
    from sqlalchemy import func

    _patch_run(
        session,
        research_run_id,
        status=metrics.get("status", "completed"),
        current_stage=metrics.get("current_stage"),
        cost_usd_total=metrics.get("cost_usd_total"),
        output_markdown=report.get("markdown"),
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
        if status not in {"failed", "cancelled"}:
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
    ResearchRunRepository(session, identity).patch(research_run_id, **values)


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
    * **WRITE** (a fresh ``tenant_session``): on ``completed`` fetch ``get_report``,
      persist ``output_markdown`` (A4) + finalize + mail the completion variant to the
      acting superadmin (D-10); else finalize failed + mail the failure variant;
    * **on_error** finalizes the row to EXACTLY ``failed`` on ANY exception (D-04).

    Never returns a value (a BackgroundTask); never raises out of the task (``on_error``
    swallows exceptions into a ``failed`` finalize).
    """
    global _ACTIVE_IDENTITY
    _ACTIVE_IDENTITY = identity

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

        # D-04 deterministic idempotency key: a retried trigger returns the existing
        # run (no double-charge); the 3-attempt cap is natural.
        idem = str(uuid.uuid5(uuid.UUID(str(intake_id)), f"attempt-{attempt}"))
        run = tribunal_client.create_run(
            project_id=project_id,
            brief=brief,
            idempotency_key=idem,
            **seam_kwargs,
        )
        rid = run["id"]

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
                        return rid, {
                            "status": "failed",
                            "error_message": (
                                f"metrics 5xx after {_MAX_METRICS_5XX_RETRIES} "
                                "retries"
                            ),
                        }
                    time.sleep(POLL_SECONDS)
                    continue
                raise  # a 4xx is a real error → on_error finalizes failed.

            mirror_tick(identity, research_run_id, rid, metrics)
            if metrics.get("status") in _RESEARCH_TERMINAL:
                return rid, metrics
            time.sleep(POLL_SECONDS)

    def write_fn(session: Any, ctx: dict[str, Any], result: tuple[str, dict]) -> None:
        rid, metrics = result
        to = [ctx["acting_email"]] if ctx.get("acting_email") else []
        cta_url = _admin_cta(ctx)

        if metrics.get("status") == "completed":
            report = tribunal_client.get_report(
                run_id=rid,
                service_url=ctx["service_url"],
                space_id=ctx["space_id"],
                acting_user_id=ctx["acting_user_id"],
                acting_email=ctx["acting_email"],
            )
            finalize_completed(session, research_run_id, metrics, report)
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

    run_with_session_release(
        identity, read_fn, call_fn, write_fn, on_error=on_error
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
