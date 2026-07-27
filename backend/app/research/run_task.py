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
terminal set ``{"completed", "completed_degraded", "failed", "cancelled",
"parked"}`` — NEVER the skill-run success/failed vocabulary. A successful Tribunal
run is ``completed`` or ``completed_degraded``, carried verbatim (D-05 boundary),
and is never remapped to the skill-run success literal. The set and its predicates
live in ONE place, :mod:`app.research.run_status`.

``parked`` joined that set in plan 15.2-19 (DEC-3, a deliberate deviation from
15.2-RESEARCH § R4): this driver is a ``BackgroundTask`` and a parked run waits on
a human click that may be hours away, so a driver that kept polling would leak a
task pinning a Cloud Run instance. ``parked`` is terminal for the STREAM, never for
the RUN — the Resume verb re-queues the SAME engine run and schedules a FRESH
driver. Three states stay distinct here: 1-2 lost streams are
``completed_degraded`` (a real deliverable, completion mail), a D-14 distiller
fallback is normal operation (no status of its own), and ``parked`` is only a hard
wall (:func:`finalize_parked` + the F-03 park mail).

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
from app.mail.render import (
    render_research_complete,
    render_research_failed,
    render_research_parked,
)
from app.research import tribunal_client
from app.research.bundle import build_bundle_zip
from app.research.run_status import (
    RESEARCH_TERMINAL,
    is_research_parked,
    is_research_success,
)
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


def _seam_datetime(value: Any, field: str) -> Any:
    """Parse an ISO-8601 timestamp from the seam, or return ``None``. NEVER raises.

    D-L (plan 15.2-24). ``metrics`` is REMOTE JSON crossing the engine seam into a
    ``BackgroundTask`` — the phase's ASVS V5 rule applies in full: never assume the
    type, never let a malformed value raise here. A raise inside the poll driver
    routes to ``on_error`` and mislabels the run ``failed``, which for a park would
    also destroy the resume affordance. So an int, a garbage string, a dict, a list
    and ``None`` all take the same route: a WARNING naming the field, and ``None``
    back, which the callers treat as "not sent" and therefore "not patched".

    Accepts what the engine actually sends — pydantic serialises
    ``datetime | None`` to an ISO-8601 string, including the ``Z`` suffix that
    ``datetime.fromisoformat`` rejects before Python 3.11 — and passes a
    ``datetime`` straight through so a caller holding a real object is not forced
    to round-trip it through text.
    """
    from datetime import datetime as _dt

    if value is None:
        return None
    if isinstance(value, _dt):
        return value
    if not isinstance(value, str) or not value.strip():
        log.warning(
            "seam timestamp %s is not a string (%s) — ignored, the column is left "
            "untouched rather than guessed",
            field, type(value).__name__,
        )
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return _dt.fromisoformat(text)
    except (TypeError, ValueError):
        log.warning(
            "seam timestamp %s is not ISO-8601 — ignored, the column is left "
            "untouched rather than guessed",
            field,
        )
        return None


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
    # D-L (plan 15.2-24) — THE RUN'S OWN CLOCK, mirrored the moment the engine
    # publishes it. ``ResearchRunProgress.tsx`` already consumes both fields; until
    # now nothing produced them, so ``useElapsed(startedAt)`` fell back to
    # ``Date.now()`` and the counter restarted on every page refresh.
    #
    # Follows this function's existing rule to the letter: patch ONLY when the
    # field is present AND parses. An older engine build sends neither and patches
    # nothing; a malformed value is a WARNING and patches nothing (never a guess,
    # never a raise — see ``_seam_datetime``).
    for _field in ("started_at", "completed_at"):
        if metrics.get(_field) is not None:
            _parsed = _seam_datetime(metrics[_field], _field)
            if _parsed is not None:
                values[_field] = _parsed

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

    # D-L (plan 15.2-24): prefer the ENGINE's own timestamps over this row's
    # ``func.now()``. The engine knows when the run actually finished; the mirror
    # only knows when the driver got round to writing. ``func.now()`` remains the
    # fallback, so an older engine build that sends neither field finalizes exactly
    # as it does today. ``started_at`` is added only when present — a missing field
    # is never patched, and NULLing a column the poll loop already filled would
    # take the elapsed clock back to zero at the very end of the run.
    _stamps: dict[str, Any] = {}
    _started = _seam_datetime(metrics.get("started_at"), "started_at")
    if _started is not None:
        _stamps["started_at"] = _started

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
        completed_at=_seam_datetime(metrics.get("completed_at"), "completed_at")
        or func.now(),
        **_stamps,
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
        # would destroy the resume affordance.
        #
        # The clamp is NOT the park path. Since 15.2-19 the NORMAL route for a
        # parked terminal is :func:`finalize_parked` (which keeps ``completed_at``
        # NULL and stamps the ``[park#n]`` marker); this clamp exists only to stop
        # the ``on_error`` route — which passes ``metrics=None`` and always means
        # "something threw" — from writing a non-terminal literal. If a park ever
        # reaches HERE it is a bug in ``write_fn``'s branch order, not a design.
        if status not in {"failed", "cancelled", "parked"}:
            status = "failed"

    # D-L (plan 15.2-24), same rule as the completed path: the engine's own
    # timestamps win when it sent them, ``func.now()`` when it did not. ``metrics``
    # is None on the ``on_error`` route, which is exactly the case where the engine
    # said nothing and the mirror's clock is the only one there is.
    _stamps: dict[str, Any] = {}
    _started = _seam_datetime((metrics or {}).get("started_at"), "started_at")
    if _started is not None:
        _stamps["started_at"] = _started

    _patch_run(
        session,
        research_run_id,
        status=status,
        error_message=error_message or _default_error(metrics),
        completed_at=_seam_datetime(
            (metrics or {}).get("completed_at"), "completed_at"
        ) or func.now(),
        **_stamps,
    )


#: Column bound for the mirrored park reason (marker + reason), clamped before write.
_MAX_PARK_MESSAGE_CHARS = 1000

#: Shown when the engine's park descriptor carries no usable reason. Never blank:
#: an operator staring at an empty reason has no idea what to do next.
_DEFAULT_PARK_REASON = (
    "Het onderzoek is gepauzeerd. Open de run in admin om te zien waar het is "
    "gestopt."
)


def finalize_parked(
    session: Any,
    research_run_id: Any,
    metrics: dict[str, Any],
    park_reason: str,
) -> None:
    """WRITE (parked): mirror the PAUSE — ``completed_at`` stays NULL on purpose.

    A parked run is not finished, it is waiting on one superadmin click, and the
    resume continues the SAME engine run. Stamping ``completed_at`` would make the
    intake card render a duration for a run that has not ended, and would make the
    row indistinguishable from a real terminal in any later reporting.

    ``park_reason`` arrives pre-composed as ``"[park#<seq>] <reason>"`` — the marker
    is the DEC-5 mail-idempotency record and MUST land in the column verbatim (that
    column IS the record of whether the operator was already told). No bundle, no
    report row and no chain verdict are written: a parked run has none of them.

    D-L (plan 15.2-24) DELIBERATELY STOPS AT THIS DOOR: ``completed_at`` stays NULL
    here and NO ``completed_at`` is read from ``metrics``, even though the two
    finalize paths above now prefer the engine's own timestamp. That is 15.2-19's
    rule restated, not an oversight — a parked run has not ended, and stamping a
    completion time would make the intake card render a duration for a run that is
    still waiting on a superadmin click. Do not "fix" the omission. ``started_at``
    is not written here either: the poll loop's ``mirror_tick`` already put it on
    the row, and re-patching it buys nothing.
    """
    _patch_run(
        session,
        research_run_id,
        status="parked",
        error_message=park_reason,
        current_stage=metrics.get("current_stage"),
        cost_usd_total=metrics.get("cost_usd_total"),
        completed_at=None,
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
                # 15.2-19: this guard is ALSO what keeps a ``parked`` terminal
                # bundle-free. is_research_success("parked") is False, so a parked
                # run returns completion=None — no report fetch, no chain verify, no
                # zip, no GCS upload. A paused run has no deliverable to build. No
                # code change is needed here; do not "fix" it by widening the guard.
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
        elif is_research_parked(metrics.get("status")):
            # D-17 / F-03 park. NOT a failure and NOT a degradation: the run hit a
            # wall it cannot pass alone and stopped WITH its paid work checkpointed.
            #
            # ASVS V5 — ``metrics["park"]`` is REMOTE JSON whose members originate in
            # provider error text. Read every member defensively, never re-parse it,
            # never trust its types, and never let a malformed descriptor raise inside
            # the driver (a raise here would route to on_error and mislabel the run
            # ``failed``, destroying the resume affordance).
            park = metrics.get("park")
            if not isinstance(park, dict):
                park = {}
            try:
                seq = int(park.get("seq"))
            except (TypeError, ValueError):
                seq = 1
            marker = f"[park#{seq}]"
            reason = str(park.get("reason") or "").strip() or _DEFAULT_PARK_REASON

            # DEC-5 mail idempotency, in words: 15.2-16's pipeline hashes (stage,
            # redacted reason) into a signature and keeps ``seq`` for a re-park with
            # the SAME signature, incrementing it only for a genuinely different park.
            # So the marker already on the mirror row tells us whether the operator
            # has been told about THIS park event. Two drivers scheduled for the same
            # event therefore send one mail; a new park does mail. Read the prior row
            # BEFORE the finalize overwrites it.
            already_notified = False
            try:
                prior = ResearchRunRepository(
                    session, identity_of(session)
                ).get(research_run_id)
            except Exception as exc:  # noqa: BLE001 - never block the finalize/mail
                prior = None
                # Default to NOT notified: a duplicate mail is a nuisance, a dropped
                # one is the operator's only signal that a paid run stopped (16-05).
                log.warning(
                    "park prior-row read failed (assuming NOT yet notified): "
                    "research_run_id=%s marker=%s err=%s",
                    research_run_id, marker, exc,
                )
            if (
                prior is not None
                and getattr(prior, "status", None) == "parked"
                and str(getattr(prior, "error_message", "") or "").startswith(marker)
            ):
                already_notified = True

            finalize_parked(
                session,
                research_run_id,
                metrics,
                f"{marker} {reason}"[:_MAX_PARK_MESSAGE_CHARS],
            )

            if to and not already_notified:
                # F-03 / 16-D-10: the triggering superadmin and NOBODY else.
                html = render_research_parked(
                    project_title=ctx["project_title"],
                    park_reason=reason,
                    cta_url=cta_url,
                    app_base_url=ctx.get("app_base_url"),
                )
                resend.send(
                    to=to,
                    subject="Je onderzoek staat op pauze",
                    html=html,
                )
            elif already_notified:
                # A skipped mail must be VISIBLE. Silence here would look identical
                # to a mail transport failure in the next incident.
                log.warning(
                    "park mail SKIPPED (already notified for this park event): "
                    "research_run_id=%s marker=%s",
                    research_run_id, marker,
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
