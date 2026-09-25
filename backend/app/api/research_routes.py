"""The intake-side research seam router — the trigger verb + the SSE progress stream.

Two surfaces, both space-scoped and bounded by the same existence-hidden 404 / null-space
403 discipline the intake surface uses (D-04 / D-07):

* ``POST /intakes/{intake_id}/research`` (:func:`trigger_research`, SEAM-03) — the discrete
  "start deep research" verb (NOT a generic ``PATCH status``), and the ONE verb here that
  SPENDS. Superadmin-only since 23.1-17 (D-23.1-16); it was the router's last ungated
  write and cost ~$45 a call. It flips ``decomposed →
  in_research`` on the allow-listed transition map, or — since 23.6 (D-23.6-03) — starts a
  RERUN from ``in_research`` / ``delivered`` with no status change while no run of the
  intake is in flight. The 3-attempt cap (D-04) applies to non-superadmin identities only
  (D-23.6-01), which the gate makes unreachable today. It composes a pause-gate-safe brief, inserts the ``research_runs`` row, audits ``{from,to}``
  in the SAME tx, schedules the pool-safe poll driver, and returns ``202`` with the run id.
  The brief is composed marker-free upstream so a seam run can never opt into the
  interactive-report pause gate (SEAM-04 by composition — see :mod:`app.research.brief`).

* ``POST /intakes/{intake_id}/research/resume`` (:func:`resume_research`, F-01/ENGINE-11) —
  the click-only Resume of a PARKED run. Superadmin-only and space-scoped
  (existence-hidden 404), 409 unless the latest run is exactly ``parked``, and
  deliberately attempt-FREE: a checkpoint resume costs nothing and never consults
  ``_MAX_ATTEMPTS`` (F-02). It re-queues the SAME engine run through the seam, so the
  R3 checkpoints are reused instead of re-charged.

* ``GET /intakes/{intake_id}/research/runs`` (:func:`list_research_runs`, D-23.6-04) — the
  operator's run HISTORY for one intake: every run (attempt DESC) with status, times, cost,
  chain status and ``chosen_at``, plus the explicitly chosen run id (``None`` when none is
  marked — the newest-finished default is display-only, UI-SPEC UI-8). Superadmin-only,
  space-scoped, existence-hidden 404. A history read, never a second live-status source.

* ``POST /intakes/{intake_id}/research/runs/{run_id}/choose`` (:func:`choose_research_run`,
  D-23.6-02 revised) — marks one ``completed`` / ``completed_degraded`` run as the intake's
  chosen run, moving the previous mark in the same transaction and auditing
  ``research.run_chosen``. An INTERNAL label: no mail, no artifact, no intake column, no
  client consumer. 409 for an unfinished run or an archived intake; 404 for a run of
  another intake.

* ``POST /intakes/{intake_id}/research/cancel`` (:func:`cancel_research`, D-D/ENGINE-11) —
  the operator's ONLY stop path. Superadmin-only and space-scoped (existence-hidden 404),
  with NO 409 arm and NO attempt cap: the engine treats cancelling a terminal run as an
  idempotent no-op, and stopping a run is not an attempt. It resolves the mirror row to the
  status the engine reports and audits ``{from,to}`` in the SAME tx. Because ``cancelled``
  IS in ``_RETRYABLE_RUN_STATUSES`` (and ``running`` is not), resolving the row is exactly
  what makes a stuck intake re-triggerable again.

* ``GET /intakes/{intake_id}/research/stream`` (:func:`stream_research_run`, RUN-01) — the
  operator's live run feed, and the router's ELEVENTH route. Superadmin-only since 23.1-18
  (D-23.1-16 addendum), which completed the boundary: all ELEVEN routes on this router then
  resolved ``superadmin_gate`` — THIRTEEN since 23.6-02 added the two run-history verbs
  above, both gated from birth. It was excluded from 23.1-17 on the false premise that SSE
  forces ``EventSource`` (the frontend opens it with ``fetch()`` + a Bearer header, and
  ``EventSource`` appears nowhere in ``frontend/src``). The
  ONE deliberate ``async def`` handler, cloned from ``intake_routes.stream_skill_runs`` with
  the RESEARCH terminal set ``{completed, completed_degraded, failed, cancelled, parked}``
  (NOT the skill-run success/failed vocabulary — 16-RESEARCH Pitfall 3). ``parked`` joined
  that set in 15.2-19 (DEC-3): a parked run waits on a human click that may be hours away,
  so holding the stream open would burn the handler to its 10-minute ``MAX_STREAM_SECONDS``
  cap and drop the browser into its reconnect loop. ``parked`` is terminal for the STREAM,
  never for the RUN. It mirrors the
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
import httpx
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

# NOT a raw DB symbol: `func` is a SQL-expression helper, not an engine/session factory,
# so ci_no_raw_db_access.sh (D-03) stays green. It is used ONLY for the server-side
# `completed_at=func.now()` stamp on the cancel path — the same shape run_task.py's
# finalize writers use, so the resolved-run timestamp comes from the DB clock, never
# from a Python clock that may be skewed against it.
from sqlalchemy import func

# Also not a raw DB symbol: an exception CLASS, not an engine/session factory, so
# ci_no_raw_db_access.sh (D-03) stays green. Imported for exactly one purpose — turning
# the 0016 partial-unique-index refusal into a readable 409 in trigger_research
# (D-23.2-12). Mirrors ai_session.create_running_skill_run's 23.1-12 precedent.
from sqlalchemy.exc import IntegrityError

# NOTE: this module no longer imports ``get_current_identity``. Every one of its THIRTEEN
# routes resolves ``superadmin_gate`` instead (23.1-18 closed the last one,
# ``stream_research_run``), and the gate itself depends on ``get_current_identity`` — so
# the identity is still verified on every call, one level down. AUTH-01 is unaffected: the
# router is mounted under ``protected_router`` and is never anonymous.
#
# D-23.1-01: the superadmin gate is now the ONE shared object in app/auth/gates.py.
# Aliased to its former private name so not one Depends(_superadmin_gate) site below
# has to change — the promotion is behaviour-identical by construction.
from app.auth.gates import superadmin_gate as _superadmin_gate
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
from app.research.run_status import (
    RESEARCH_IN_FLIGHT,
    RESEARCH_TERMINAL,
    is_research_success,
)
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
#
# ``parked`` is deliberately NOT a member (15.2-19): a parked run has its OWN
# explicit Resume verb (:func:`resume_research`), and letting a re-trigger
# supersede it would throw away every R3 checkpoint the engine already paid for.
#
# Since phase 23.6 this set NO LONGER GATES THE TRIGGER: a rerun is refused only while a
# run is in ``RESEARCH_IN_FLIGHT`` (over ALL of the intake's runs, see trigger_research).
# It is KEPT because ``tests/test_intake_delete.py`` imports it and because
# ``app/research/run_status.py`` derives ``RESEARCH_IN_FLIGHT`` from it (the complement of
# this set union RESEARCH_TERMINAL over the measured statuses).
_RETRYABLE_RUN_STATUSES = {"failed", "cancelled", "needs_input"}

#: D-23.6-03 — the intake statuses from which a NEW run may start with NO status change.
#
# ``delivered`` MUST stay ``delivered``: ``GET /intakes/{id}/report`` is an equality check
# on ``delivered`` (``intake_routes.get_report``), so stepping the status back to start a
# rerun would take the delivered report away from the client. ``archived`` is deliberately
# ABSENT: unarchive with the status override first.
_RERUN_STATUSES = frozenset({"in_research", "delivered"})

#: The 3-attempt cap (D-04): a 4th trigger for an intake returns needs_investigation and
#: makes NO seam call / schedules NO driver (a runaway retrigger must not re-charge Tribunal).
#: It counts the NON-exempt prior runs — see ``_CAP_EXEMPT_RUN_STATUSES``.
_MAX_ATTEMPTS = 3

#: Prior-run statuses that do NOT count toward ``_MAX_ATTEMPTS`` (D-23.4-07).
#
# A ``cancelled`` run is a DELIBERATE stop. It spent nothing that a completed run would not
# have spent more of, and it is ALREADY a legal retry trigger via ``_RETRYABLE_RUN_STATUSES``
# — so counting it toward a cap whose stated purpose (D-04) is "a runaway retrigger must not
# re-charge Tribunal" punishes the single operator action that PREVENTS spend. An intake with
# two genuine failures and one cancellation had two attempts, not three.
#
# DELIBERATELY NOT folded into ``_RETRYABLE_RUN_STATUSES``. The two sets answer different
# questions — "may this run be superseded by a re-trigger?" versus "did this run consume one
# of the three paid attempts?" — and a status will eventually belong to one and not the other
# (``needs_input`` is retryable but DID spend, so it still counts). One set for both would
# drift on the first such change, silently.
_CAP_EXEMPT_RUN_STATUSES = {"cancelled"}


def _attempt_cap_reached(identity: Identity, prior) -> tuple[bool, int]:
    """Return ``(capped, counted)`` for a trigger by ``identity`` over ``prior`` runs.

    PURE — no DB, no side effect; unit-tested directly.

    * ``identity.role == "superadmin"`` → ``(False, counted)``. D-23.6-01: a superadmin is
      never capped. Every run still costs ~$40 and the UI confirm says so.
    * otherwise the D-04 rule: ``counted`` = prior runs NOT in ``_CAP_EXEMPT_RUN_STATUSES``
      (D-23.4-07), capped when ``counted >= _MAX_ATTEMPTS``.

    The trigger's gate admits only superadmins, so the capped arm is unreachable in
    production today; it is kept as defence-in-depth, like the ``create()`` arm.
    """
    counted = [r for r in prior if r.status not in _CAP_EXEMPT_RUN_STATUSES]
    if identity.role == "superadmin":
        return False, len(counted)
    return len(counted) >= _MAX_ATTEMPTS, len(counted)


def _next_research_status(current: str) -> str:
    """Return the research-transition target for ``current``, or 409 if not allow-listed."""
    try:
        return _RESEARCH_TRANSITIONS[current]
    except KeyError:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Cannot start research for an intake in status {current!r}",
        )


# The superadmin gate was DEFINED here until D-23.1-01; it now lives in
# app/auth/gates.py and is imported at module top under this same private name.
# One gate, one convention, one test surface — the intake operator verbs and
# ai_router depend on that SAME object, and a per-route role comparison is how
# verb number ten gets missed.
#
# Its ordering rule is UNCHANGED and still binds every signature below:
# Depends(_superadmin_gate) is declared BEFORE Depends(get_tenant_repo) so the gate
# resolves first and a non-superadmin — including a null-space user — hits its
# existence-hidden 404 before get_tenant_repo can raise its null-space default-deny
# 403, which would leak that the endpoint exists. The denial suite pins EXACTLY 404.


# ---------------------------------------------------------------------------
# Run -> intake resolution for the standalone run page (D-01, plan 15.3-07)
# ---------------------------------------------------------------------------
#
# DECLARED FIRST, DELIBERATELY. FastAPI matches routes in DECLARATION order, and
# this path's SECOND segment is the literal ``research`` while every other route in
# this module has the parameterised ``{intake_id}`` there. Declaring it after them
# is the class of bug that is invisible in review and indistinguishable from a
# working denial in production: a perfectly authorized caller would get a 404 that
# looks exactly like the existence-hidden one. (Until D-23.1-01 it also had to sit
# beneath the gate's own ``def``, because a ``Depends`` default is evaluated at def
# time and an earlier position would have been a NameError at import. The module-top
# import satisfies that trivially now; only the ROUTE order above still binds.)
#
# (The route segments differ at the literal, so today's declaration order is not
# what makes this correct — but the ordering is asserted by a test rather than left
# to a future reader's inspection, because "it happens not to shadow" is not a
# property anyone should have to re-derive.)


@research_router.get("/research/runs/{run_id}/locate")
def locate_research_run(
    run_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Resolve a research run to its intake — the cold-open half of D-01.

    ``/admin/pulse/runs/{runId}`` is a genuinely standalone, bookmarkable URL, which
    means it carries NO intake id. Every other research verb is
    ``/intakes/{intake_id}/research/...``, so something has to answer "which intake
    is this run?" before the page can fetch anything at all. This is that something,
    and NOTHING else.

    It invents NO isolation logic — it COMPOSES the walls this module already proves,
    in the same order as :func:`get_research_audit_body`:

    * ``_superadmin_gate`` declared BEFORE ``get_tenant_repo`` (so a null-space user
      is 404 here rather than the null-space default-deny FORBIDDEN there) plus the
      defense-in-depth in-body role re-check → 404;
    * the space-scoped ``ResearchRunRepository.get`` → 404 when the run is not
      visible;
    * a SECOND, space-scoped resolve of the run's OWN intake → 404 when THAT misses.

    The second resolve is the tenant wall rather than a formality: ``_scope`` is a
    no-op for a superadmin (who has no own space and reaches across spaces by
    design — D-05), so the intake resolve is what every other handler here already
    relies on to prove scope, and this verb must not be the one place that skips it.

    Returns ``{"intake_id", "research_run_id"}`` and NOTHING else. It is deliberately
    NOT a second run-state read: a status or stage returned here would be a second
    source of truth for "is it over" that can disagree with the SSE frame the page is
    already subscribed to (D-05), and two disagreeing answers are worse than one.
    """
    # Defense-in-depth role re-check (the same double gate get_bundle_url uses): the
    # _superadmin_gate dependency is declared BEFORE get_tenant_repo so it resolves
    # first and a null-space user is 404 here rather than reaching get_tenant_repo's
    # null-space default-deny. (The denied status is named in WORDS throughout this
    # handler on purpose: a source gate in tests/test_research_events_proxy.py asserts
    # that number appears NOWHERE in it, and prose quoting it defeats its own gate —
    # the 15.3-02 convention, and the first thing that build caught here.)
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # The tenant wall: re-resolve the run's OWN intake through the SPACE-SCOPED
    # intake repo. A run whose intake is not visible to this caller is a run this
    # caller may not learn the existence of — same 404, same body.
    intake = repo.get(run.intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    return {"intake_id": str(run.intake_id), "research_run_id": str(run.id)}


@research_router.post("/{intake_id}/research", status_code=status.HTTP_202_ACCEPTED)
def trigger_research(
    intake_id: str,
    background: BackgroundTasks,
    # ORDER IS LOAD-BEARING AND THIS IS THE ROUTER'S HARDEST SIGNATURE. ``repo`` used to
    # be declared first; the gate MUST stay above it. FastAPI resolves the signature in
    # order, so with the gate below, a null-space caller gets get_tenant_repo's 403
    # ("No space — not authorized") instead of the existence-hidden 404 — an existence
    # oracle for the one verb whose existence is worth the most to learn.
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Start deep research for a ``decomposed`` intake (SEAM-03) — SUPERADMIN ONLY.

    Flips ``decomposed → in_research``, composes a pause-gate-safe brief, inserts the
    ``research_runs`` row (``status=queued``, ``attempt=n``), audits ``{from,to}`` in the
    SAME tx, schedules the pool-safe poll driver, and returns ``202 {research_run_id}``.

    SUPERADMIN ONLY (D-23.1-16). This is the ONE verb on this router that SPENDS: it
    schedules ``run_poll_driver``, a Tribunal run costing roughly $45 that runs with
    ``NESTOR_TRIBUNAL_UNCAPPED=1``. Until 23.1-17 it took ``get_current_identity`` and no
    role gate while every FREE verb around it was gated — an oversight, not a decision:
    the phase's scope survey read ``intake_routes.py`` and never gave this file the same
    treatment (23.1-CONTEXT.md § 15). Measured before the fix: a role=``user`` in the
    intake's own space got 202, the flip, a queued ``research_runs`` row and a dispatched
    driver. Its only frontend caller is the admin route ``admin.pulse.intakes.$id.tsx``,
    so the gate breaks no client surface. Denial is proved WITHOUT side effect in
    ``tests/test_research_trigger_gate.py`` — no run row, no status flip, no task.

    * 404 for a non-superadmin caller, including a null-space one (``_superadmin_gate``,
      declared FIRST — see the signature comment).
    * 404 if the (in-scope) intake does not exist (D-07 — existence hidden; never 403/200).
    * 409 if the status is not in decomposed/in_research/delivered, or any run of the
      intake is in ``RESEARCH_IN_FLIGHT`` (checked over ALL prior runs, not the newest
      only), or the intake is in_research/delivered with NO prior run (a rerun requires an
      existing run). From ``in_research`` / ``delivered`` a rerun leaves the status exactly
      as it was (D-23.6-03): a delivered intake stays delivered.
    * The attempt cap applies to NON-superadmin identities only (D-23.6-01, via
      :func:`_attempt_cap_reached`). The gate makes that arm unreachable in production
      today; it is kept as defence-in-depth like the ``create()`` arm. When it applies and
      ``_MAX_ATTEMPTS`` COUNTED prior runs exist, the trigger returns
      ``needs_investigation`` and makes NO seam call / schedules NO driver (D-04). Runs in
      ``_CAP_EXEMPT_RUN_STATUSES`` (``cancelled``) are NOT counted (D-23.4-07). The
      ``attempts`` figure in the response is that same counted number, not the row count.

    The ``audit_log`` row is written on ``repo.session`` so it commits/rolls back together
    with the status change (one-tx, Pitfall 2). ``metadata`` is structured ``{"from","to"}``
    only — never a link or token (T-16-11). The driver is scheduled AFTER the 202 via
    ``BackgroundTasks`` so the long (~19-min) Tribunal drive holds no request connection.

    IDEMPOTENCY IS THREE PARTS, AND NONE OF THEM IS REDUNDANT (D-23.2-12 / F-05)
    ---------------------------------------------------------------------------
    This handler reads the intake's status and its prior runs on ``repo.session`` and then
    writes in a SEPARATE ``tenant_session``. That read-then-write window is real: two
    concurrent authorized requests used to both read the same ``prior``, both compute
    ``attempt = 1``, and both insert and dispatch — roughly $45 spent twice, with nothing
    in the UI to say so. Three mechanisms close it, each covering what the others cannot:

    1. **The ``patch_if`` compare-and-swap** on the flip covers the ``decomposed ->
       in_research`` path: the second caller's precondition no longer holds, ``rowcount``
       is 0, and it gets a 409 having written nothing.
    2. **The 0016 partial unique index** covers the RETRY / RERUN path, which the CAS
       CANNOT. When ``old_status`` is ``in_research`` or (since 23.6) ``delivered`` this
       handler sets ``new_status = old_status``, so a CAS of
       ``expected={"status": old_status}`` setting ``status=old_status`` MATCHES for both
       concurrent callers — ``rowcount == 1`` twice. There the database is
       the only arbiter, and the ``except IntegrityError`` below is purely a translator.
       **This is the paragraph to read before deleting that index as "redundant".**
    3. **``attempt`` computed inside the write transaction** so two triggers cannot both
       stamp the same number. It is not a dedup mechanism on its own — it makes the audit
       trail true once the other two have decided who wins.

    The ``_MAX_ATTEMPTS`` cap deliberately stays on the pre-block read: it must
    short-circuit before the brief is assembled, and moving it into the write tx would
    change the ``needs_investigation`` response shape. What it counts on that read is the
    NON-cancelled prior runs (``counted``), not every row — ``prior`` itself is left
    unfiltered because the rerun check below must see EVERY run of the intake.
    """
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # Attempt cap FIRST (D-04): count prior research runs on the same in-scope session.
    run_repo = ResearchRunRepository(repo.session, identity)
    prior = run_repo.list_for_intake(intake_id)
    # ``prior`` stays the TRUE list (every run, newest first): the rerun check below must
    # see ALL of them, including cancelled ones. The cap computes its own filtered view.
    # D-23.6-01: a superadmin is never capped (see _attempt_cap_reached).
    capped, counted = _attempt_cap_reached(identity, prior)
    if capped:
        # No status flip, no seam call, no driver — the run is handed to a human.
        # The exempt count is logged too, so the ``attempts`` figure the operator was shown
        # can be reconciled against the row count in the database from the logs alone.
        _log.warning(
            "research attempt cap reached for intake %s (%d counted prior runs, "
            "%d exempt) — returning needs_investigation, no driver scheduled",
            intake_id,
            counted,
            len(prior) - counted,
        )
        return {
            "research_run_id": None,
            "status": "needs_investigation",
            # SAME number the cap compared — never a number the cap did not use.
            "attempts": counted,
        }

    old_status = intake.status
    if old_status in _RERUN_STATUSES:
        # Rerun path (D-23.6-03): a NEW run on the same approved inputs, with NO status
        # change — a delivered intake stays delivered, so the client keeps their report.
        #
        # A rerun requires an EXISTING run: a legacy in_research/delivered intake with no
        # run row stays refused, exactly as before 23.6.
        if not prior:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "No earlier research run to rerun for this intake",
            )
        # ALL runs, not prior[0]: an OLDER run that is still in flight must block a rerun
        # even when a newer run has finished. This is the pre-check; the 0016 partial
        # unique index + the IntegrityError arm below remain the race arbiter.
        if any(r.status in RESEARCH_IN_FLIGHT for r in prior):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Research is already running for this intake",
            )
        new_status = old_status
    else:
        new_status = _next_research_status(old_status)  # 409 otherwise

    # NOTE: ``attempt`` is deliberately NOT computed here. It is recomputed inside the
    # write transaction below, so there is exactly ONE place that computes it and it
    # counts the runs that exist at WRITE time (D-23.2-12, part 3). ``prior`` above is
    # still read here because the ``_MAX_ATTEMPTS`` cap must short-circuit BEFORE the
    # brief is assembled — see the cap's own comment.

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
    #
    # Since 23.1-17 the gate above admits ONLY superadmins, so the ``create()`` arm is
    # unreachable in production. It is KEPT, deliberately, as the same "Open Q2
    # defense-in-depth" second wall the other nine verbs on this router keep their
    # in-body role re-checks for: deleting it would make relaxing the gate silently
    # write a run row into the CALLER's space instead of the intake's.
    intake_space_id = intake.space_id
    with tenant_session(identity) as txs:
        # (1) COMPARE-AND-SWAP, not a plain patch (D-23.2-12, part 2). The precondition
        # rides in the same UPDATE's WHERE, so there is no window between the read above
        # and this write for a concurrent trigger to slip through. rowcount == 0 is
        # INDISTINGUISHABLE between "the status changed under us", "the row is gone" and
        # "the row belongs to another space" — all three are 0 by design (patch_if's own
        # docstring). Do NOT re-read to tell them apart; all three mean "do not start a
        # ~$45 run", which is the only decision this line makes.
        #
        # Raised BEFORE the audit call and BEFORE the run insert so a refusal writes
        # NOTHING. The HTTPException also aborts the `with` block, and tenant_session
        # wraps maker.begin(), so the transaction rolls back on the way out — belt and
        # braces, asserted by test_cas_refuses_a_stale_flip_and_writes_nothing.
        if IntakeRepository(txs, identity).patch_if(
            intake_id, {"status": old_status}, status=new_status
        ) == 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "The intake changed while this request was being prepared — "
                "research was not started",
            )
        # (2) attempt counted INSIDE the write tx (D-23.2-12, part 3), so two concurrent
        # triggers cannot both stamp the same number. The read above is used ONLY for the
        # _MAX_ATTEMPTS cap, which stays where it is.
        tx_runs = ResearchRunRepository(txs, identity)
        attempt = len(tx_runs.list_for_intake(intake_id)) + 1
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="intake.status_changed",
            target=str(intake_id),
            space_id=intake_space_id,
            metadata={"from": old_status, "to": new_status},
        )
        # Plan 23.3-04 (DEF-23.2-03) — the ACTING HUMAN, stamped in the SAME INSERT
        # that creates the row. Never a follow-up patch: a second statement is a
        # window in which the poll driver can start against a row that carries no
        # actor, and the whole reason the column exists is that a stateless
        # reconciler has no request identity of its own and must REPLAY this one
        # across a seam that requires a non-empty X-Acting-User-Id / -Email and
        # answers 400 without them (D-05 attribution on a frozen audit chain).
        #
        # ``identity.email`` is ``str | None``. A superadmin token without one stores
        # NULL here on purpose — see the WARNING below.
        values = dict(
            intake_id=intake_id,
            status="queued",
            attempt=attempt,
            acting_user_id=identity.uid,
            acting_email=identity.email,
        )
        # (3) The DB's own refusal, translated (D-23.2-12, part 1). create/create_in_space
        # FLUSH to populate the server-side id, so the IntegrityError surfaces HERE, inside
        # the block. Caught around the create ONLY — a genuine FK violation elsewhere in
        # this handler must still surface rather than be relabelled "already running".
        # The session is not reused afterwards: the raise exits the block and rolls back.
        try:
            if identity.role == "superadmin":
                run = tx_runs.create_in_space(intake_space_id, **values)
            else:
                run = tx_runs.create(**values)
        except IntegrityError:
            # A readable sentence, never the constraint name / driver class / SQLSTATE:
            # a leaked "duplicate key value violates unique constraint
            # uq_research_runs_one_inflight_per_intake" is information disclosure and
            # reads to the operator like a crash rather than like "that one is going".
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Research is already running for this intake",
            )
        # Captured INSIDE the tx: expire_on_commit detaches `run` at block exit.
        research_run_id = str(run.id)

    # Plan 23.3-04 — the gap, made VISIBLE before it matters. A NULL acting_email is
    # stored deliberately (never "", never a placeholder address: a fabricated actor on
    # a legally load-bearing attribution chain is worse than a skipped sweep), but it
    # means the reconciler will have to SKIP this row rather than call a seam that would
    # answer 400, and the D-10 completion mail has nobody to go to. WARNING level and
    # naming the run, so the gap is findable now rather than during an incident.
    if not identity.email:
        _log.warning(
            "research run %s has NO acting_email (identity.uid=%s): a reconciler sweep "
            "will SKIP this run rather than invent an actor, and no completion mail can "
            "be sent for it",
            research_run_id, identity.uid,
        )

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


def _run_history_item(run) -> dict:
    """Project one ``research_runs`` row onto the frozen run-history contract (9 keys).

    Plan 23.6-03 typed the frontend to exactly these keys — do not rename or add one here
    without changing that consumer in the same change. ``status`` is the engine literal
    VERBATIM (never remapped, D-05). ``cost_usd_total`` is ``str(Decimal)`` or ``None`` —
    an unknown cost is NEVER rendered as ``"0"``.
    """

    def _iso(value):
        return value.isoformat() if value is not None else None

    return {
        "id": str(run.id),
        "attempt": run.attempt,
        "status": run.status,
        "created_at": _iso(run.created_at),
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "cost_usd_total": (
            str(run.cost_usd_total) if run.cost_usd_total is not None else None
        ),
        "chain_status": run.chain_status,
        "chosen_at": _iso(run.chosen_at),
    }


@research_router.get("/{intake_id}/research/runs")
def list_research_runs(
    intake_id: str,
    # ORDER IS LOAD-BEARING: the gate before the repo, so a null-space user gets the
    # existence-hidden 404 rather than get_tenant_repo's null-space default-deny.
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Every research run of one intake, plus the explicitly chosen run id (D-23.6-04).

    Superadmin-only (``superadmin_gate`` + the in-body role re-check) and space-scoped:
    an intake that is missing or not visible to the caller is the existence-hidden 404
    "Intake not found".

    Returns ``{"chosen_research_run_id", "runs"}``; ``runs`` is ordered attempt DESC,
    then ``created_at`` DESC, each item projected by :func:`_run_history_item`.
    ``chosen_research_run_id`` is the run whose ``chosen_at`` is set, else ``None``.

    The "newest finished run is the default choice" rule is DISPLAY-ONLY (UI-SPEC
    UI-8): it is deliberately NOT computed or stored here, so ``None`` means "nobody has
    marked one", never "there is nothing to choose".

    This is a HISTORY read, not a second source of live status: the intake page's one SSE
    stream stays the live authority for the in-flight run (the same D-05 reasoning as
    :func:`locate_research_run`). A status shown from this list may lag that stream.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    runs = ResearchRunRepository(repo.session, identity).list_for_intake(intake_id)
    ordered = sorted(runs, key=lambda r: (r.attempt, r.created_at), reverse=True)
    items = [_run_history_item(r) for r in ordered]
    chosen = next((item["id"] for item in items if item["chosen_at"] is not None), None)
    return {"chosen_research_run_id": chosen, "runs": items}


@research_router.post("/{intake_id}/research/runs/{run_id}/choose")
def choose_research_run(
    intake_id: str,
    run_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Mark one finished run as the intake's chosen run (D-23.6-02 revised).

    INTERNAL LABEL ONLY. This verb sends no mail, writes no report artifact, touches no
    intake column and has no client-facing consumer; the chosen mark is read by the
    operator's run history and nothing else. Wiring ANY client effect onto this verb
    needs a new operator ruling first — it is not a small follow-up.

    Refusals, in order, all writing nothing:

    * not a superadmin → existence-hidden 404 (gate + in-body re-check);
    * intake missing / out of scope → 404 "Intake not found";
    * run missing, out of scope, or belonging to ANOTHER intake → 404 "Run not found";
    * archived intake → 409 "An archived intake is read-only";
    * run not in ``RESEARCH_SUCCESS`` (``completed`` / ``completed_degraded``) → 409
      "Only a finished run can be chosen".

    The move itself is :meth:`ResearchRunRepository.set_chosen` (FOR UPDATE on the
    intake's runs, clear-then-set) inside a SAVEPOINT, audited as
    ``research.run_chosen`` in the SAME request transaction. Re-choosing the run that is
    already chosen is a no-op: 200, ``previous_research_run_id == run_id``, no audit row.
    The partial unique index is the last wall: an IntegrityError from it is a 409.
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    runs_repo = ResearchRunRepository(repo.session, identity)
    run = runs_repo.get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    if intake.status == "archived":
        raise HTTPException(status.HTTP_409_CONFLICT, "An archived intake is read-only")

    if not is_research_success(run.status):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a finished run can be chosen")

    # Captured BEFORE set_chosen: its synchronize_session="fetch" UPDATEs touch the
    # identity map, and these are all the handler needs from the row afterwards.
    chosen_id = str(run.id)
    attempt = run.attempt

    try:
        # A SAVEPOINT, so a unique-index refusal also undoes the clear step and nothing
        # half-written can commit with the request transaction.
        with repo.session.begin_nested():
            previous = runs_repo.set_chosen(intake_id, run_id)
    except IntegrityError:
        # A readable sentence, never the constraint name / driver text (the same rule
        # trigger_research follows for its 0016 index).
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The chosen run changed while this request was being prepared",
        )

    previous_id = str(previous) if previous is not None else None
    if previous_id == chosen_id:
        # Idempotent re-choose: nothing moved, so there is nothing to audit.
        return {"chosen_research_run_id": chosen_id, "previous_research_run_id": previous_id}

    audit.log(
        repo.session,
        actor_uid=identity.uid,
        event_type="research.run_chosen",
        target=str(intake_id),
        space_id=intake.space_id,
        metadata={
            "research_run_id": chosen_id,
            "previous_research_run_id": previous_id,
            "attempt": attempt,
        },
    )
    return {"chosen_research_run_id": chosen_id, "previous_research_run_id": previous_id}


@research_router.post(
    "/{intake_id}/research/resume", status_code=status.HTTP_202_ACCEPTED
)
def resume_research(
    intake_id: str,
    background: BackgroundTasks,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Resume a PARKED research run — free, unlimited, superadmin-only (F-01/F-02).

    A parked run is not failed and not degraded: it hit a wall it cannot pass alone
    (every stream lost, or a hard billing / monthly-cap wall) and stopped WITH its
    paid work checkpointed. This verb re-queues the SAME engine run so that work is
    reused, then schedules a FRESH poll driver (the previous one exited when
    ``parked`` became terminal — DEC-3).

    Status map, each arm pinned by a test:

    * ``202`` — re-queued; body ``{research_run_id, status: "queued"}``.
    * ``404`` — non-superadmin caller (including a null-space user), cross-tenant or
      missing intake, no run, or a run carrying no ``tribunal_run_id`` (WR-03: a run
      with no engine id can never resolve at the seam, so it is existence-hidden
      rather than a seam 500). Existence is ALWAYS hidden — never 403, never 200.
    * ``409`` — the latest run's status is not exactly ``parked``.
    * ``502`` — any other seam or transport failure. Never an unhandled 500.

    F-02: ``run.attempt`` is passed through UNCHANGED and ``_MAX_ATTEMPTS`` is
    deliberately NOT consulted. The 3-attempt cap (16-D-04) counts full RESTARTS,
    which re-charge Tribunal from zero; a checkpoint resume re-charges nothing, so
    capping it would punish the operator for the engine hitting a wall.
    """
    # Defense-in-depth role re-check (the same double gate get_bundle_url uses):
    # the _superadmin_gate dependency is declared BEFORE get_tenant_repo so it
    # resolves first and a null-space user is 404 here rather than 403 there.
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).latest_for_intake(intake_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    if run.status != "parked":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Research is not paused for this intake"
        )
    if not run.tribunal_run_id:
        # WR-03: no engine id -> the seam could never resolve it. Existence-hidden
        # 404 rather than letting the seam 404/500 leak out unshaped.
        _log.warning(
            "resume refused: research_run_id=%s is parked but carries no "
            "tribunal_run_id (existence-hidden 404)", run.id,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    # The brief is recomposed ONLY because run_poll_driver requires the argument.
    # It starts nothing: the driver's create_run call carries the UNCHANGED
    # idempotency key uuid5(intake_id, research_run_id), so the engine returns the
    # EXISTING run that 15.2-16's resume verb just flipped back to ``queued``.
    # There is no status flip on this path, so the trigger's empty-brief 422 guard
    # is deliberately not repeated here.
    inputs = read_brief_inputs(identity, intake_id)
    if inputs is None:  # pragma: no cover - intake was in-scope above (race)
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    brief = brief_mod.assemble_brief(
        inputs["intake"],
        inputs["decomposition"],
        brief_mod.validated_questions(inputs["intake"], inputs["questions"]),
        context_pack_text=inputs.get("context_pack_text"),
    )

    settings = get_settings()
    # The seam call happens OUTSIDE any held DB session and BEFORE the mirror patch:
    # a seam failure must schedule no driver and leave no half-transitioned row.
    try:
        tribunal_client.resume_run(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            run_id=str(run.tribunal_run_id),
        )
    except httpx.HTTPStatusError as exc:
        seam_status = exc.response.status_code if exc.response is not None else 0
        _log.warning(
            "resume seam error: research_run_id=%s seam_status=%s", run.id, seam_status
        )
        if seam_status == 404:
            # Missing OR cross-tenant at the engine — indistinguishable by design.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        if seam_status == 409:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Research is not paused for this intake"
            )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Research engine unavailable")
    except httpx.HTTPError as exc:
        # Transport failure (timeout / connect error) — never an unhandled 500.
        _log.warning("resume seam transport failure: research_run_id=%s err=%s", run.id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Research engine unavailable")

    # COMMITTED-BEFORE-SCHEDULE (root cause of the 16-05 silent driver, live finding
    # 2026-07-21): the BackgroundTask driver runs BEFORE the request dependency's
    # transaction commits, so a driver scheduled against the REQUEST session's
    # uncommitted writes (a) finds no research_runs row — every mirror/finalize
    # patch matched 0 rows and the panel froze at "queued"; (b) leaves the row lock
    # held for the driver's whole lifetime; and (c) loses the whole action on
    # instance death (rollback). The mirror patch + audit therefore run in their OWN
    # short tenant_session that COMMITS on block exit — strictly before add_task.
    # For the resume case specifically, that commit is also what lets the fresh
    # driver read the row back as ``queued`` instead of the stale ``parked``.
    #
    # The intake row's own status is NOT touched — it is already ``in_research``.
    run_id = run.id
    with tenant_session(identity) as txs:
        # Plan 23.3-04 — the RESUMING human replaces the triggering one. A resume is a
        # NEW human action on the same row: if the row kept whoever triggered it hours
        # earlier, a later sweep would replay the WRONG person's attribution across the
        # audit seam, and the D-10 completion mail would go to someone who did not ask
        # for this. Same short tenant_session, so it commits strictly before add_task.
        ResearchRunRepository(txs, identity).patch(
            run_id,
            status="queued",
            error_message=None,
            completed_at=None,
            acting_user_id=identity.uid,
            acting_email=identity.email,
        )
        audit.log(
            txs,
            actor_uid=identity.uid,
            event_type="research.resumed",
            target=str(run_id),
            space_id=intake.space_id,
            # Structured {from,to} only — never a link or token (T-16-11).
            metadata={"from": "parked", "to": "queued"},
        )

    # F-02: run.attempt is passed through UNCHANGED. A checkpoint resume is free and
    # unlimited; _MAX_ATTEMPTS counts full restarts only and is NOT consulted here.
    background.add_task(
        run_poll_driver, identity, intake_id, str(run_id), brief, run.attempt
    )
    # WARNING level: pairs with run_poll_driver's START line so "scheduled but no
    # START" isolates a BackgroundTask that never executed (the 16-05 failure mode).
    _log.warning(
        "research resume driver scheduled: research_run_id=%s attempt=%s (unchanged)",
        run_id, run.attempt,
    )
    return {"research_run_id": str(run_id), "status": "queued"}


@research_router.post(
    "/{intake_id}/research/cancel", status_code=status.HTTP_202_ACCEPTED
)
def cancel_research(
    intake_id: str,
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Stop a live research run — the operator's ONLY stop path (D-D, plan 15.2-25).

    Before this verb existed, the only way to stop a run the operator was paying for was
    to pause the whole ``tribunal-worker`` Cloud Run service. That does not work: pausing
    is not cancelling. On 2026-07-27 the in-flight process kept going for 16 more minutes,
    terminating it required deploying a new revision, and the fresh worker that came up was
    seconds from RE-CLAIMING the run at full cost (D-E). Only resolving the ROW stops a run.

    Status map, each arm pinned by a test:

    * ``202`` — body ``{research_run_id, status: <the status the engine reported>}``.
      For a live run that is ``"cancelled"``; for an ALREADY-TERMINAL run it is that run's
      unchanged status (an idempotent no-op that reports itself — see below).
    * ``404`` — non-superadmin caller (including a null-space user), cross-tenant or
      missing intake, no run, or a run carrying no ``tribunal_run_id`` (WR-03: a run with
      no engine id can never resolve at the seam, so it is existence-hidden rather than a
      seam 500). Existence is ALWAYS hidden — never 403, never 200.
    * ``502`` — any seam or transport failure other than the engine's 404. Never an
      unhandled 500.

    **There is no 409 arm and no attempt cap.** The engine treats cancelling a terminal run
    as an idempotent no-op rather than a conflict, so this route does not invent one; and
    ``_MAX_ATTEMPTS`` is deliberately NOT consulted, because stopping a run is not an
    attempt at anything.

    **Why the intake row is not touched.** The intake stays ``in_research``.
    ``_RETRYABLE_RUN_STATUSES`` already contains ``cancelled`` (``running`` does NOT — which
    is exactly why a run stuck at ``running`` blocks its intake), so resolving the run row to
    ``cancelled`` is by itself what makes the existing retry path in :func:`trigger_research`
    reachable again. A future reader will otherwise wonder why cancel does not flip a status:
    it does not need to.
    """
    # Defense-in-depth role re-check (the same double gate get_bundle_url uses): the
    # _superadmin_gate dependency is declared BEFORE get_tenant_repo so it resolves
    # first and a null-space user is 404 here rather than 403 there.
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).latest_for_intake(intake_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    if not run.tribunal_run_id:
        # WR-03: no engine id -> the seam could never resolve it (the URL would be
        # /api/runs/None/cancel). Existence-hidden 404 rather than letting the seam
        # 404/500 leak out unshaped.
        _log.warning(
            "cancel refused: research_run_id=%s carries no tribunal_run_id "
            "(existence-hidden 404)", run.id,
        )
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    prior_status = run.status
    run_id = run.id

    settings = get_settings()
    # The seam call happens OUTSIDE any held DB session and BEFORE the mirror patch: a
    # seam failure must leave no half-transitioned row (we must never report a run as
    # stopped when the engine never heard the request).
    try:
        engine_run = tribunal_client.cancel_run(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            run_id=str(run.tribunal_run_id),
        )
    except httpx.HTTPStatusError as exc:
        seam_status = exc.response.status_code if exc.response is not None else 0
        _log.warning(
            "cancel seam error: research_run_id=%s seam_status=%s", run_id, seam_status
        )
        if seam_status == 404:
            # Missing OR cross-tenant at the engine — indistinguishable by design.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Research engine unavailable")
    except httpx.HTTPError as exc:
        # Transport failure (timeout / connect error) — never an unhandled 500.
        _log.warning("cancel seam transport failure: research_run_id=%s err=%s", run_id, exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Research engine unavailable")

    # ECHO the engine, never assume "cancelled": an already-terminal run comes back AS-IS,
    # and reporting that honestly is what makes this verb a no-op-that-reports-itself
    # rather than a lie. `status` is the only field consulted (the engine's own
    # completed_at stamp is engine-side state, mirrored by the poll driver).
    new_status = (engine_run or {}).get("status") or prior_status

    if new_status != prior_status:
        # WRITE: the mirror patch + the audit row in ONE short tenant_session that COMMITS
        # on block exit, so the record cannot exist without the state change or vice versa
        # (T-15.2-254 repudiation). `completed_at` is stamped here — this run is resolved,
        # and the poll driver that would normally finalize it may itself be long dead (the
        # exact condition that makes an operator reach for this button).
        with tenant_session(identity) as txs:
            ResearchRunRepository(txs, identity).patch(
                run_id, status=new_status, completed_at=func.now()
            )
            audit.log(
                txs,
                actor_uid=identity.uid,
                event_type="research.cancelled",
                target=str(run_id),
                space_id=intake.space_id,
                # Structured {from,to} only — never a link or token (T-16-11).
                metadata={"from": prior_status, "to": new_status},
            )
        _log.warning(
            "research run cancelled by %s: research_run_id=%s %s -> %s",
            identity.email, run_id, prior_status, new_status,
        )
    else:
        # Idempotent no-op: the engine returned the run unchanged (already terminal).
        # NO patch and NO audit — there was no state change to record, and stamping
        # completed_at here would clobber the real completion time of a finished run.
        _log.warning(
            "cancel was a no-op: research_run_id=%s already %s", run_id, prior_status
        )

    # There is NO driver to schedule and no BackgroundTasks parameter: `cancelled` is
    # already a member of RESEARCH_TERMINAL, so any poll driver still running exits by
    # itself on its next tick, and the SSE stream closes on the same terminal frame.
    return {"research_run_id": str(run_id), "status": new_status}


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
    * not :func:`~app.research.run_status.is_research_success` or
      ``chain_status != "verified"`` → 409 (the D-06/D-09 complete-but-locked
      availability gate). A ``completed_degraded`` run IS downloadable (D-09) — only
      the *status* half is widened; the chain conjunct is untouched, so a
      broken-chain degraded run is still locked.
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

    # Availability gate (D-06/D-09): only a SUCCESS-terminal + verified run may be
    # downloaded. STATUS half only is widened — the chain conjunct, the superadmin-first
    # 404 above and the existence-hidden 404s are an AUTHORIZATION contract, unchanged.
    if not is_research_success(run.status) or run.chain_status != "verified":
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
# FOUR sync-``def`` proxies over the tribunal read endpoints: verification report /
# citation source / audit-body drill-down (Plan 15-03), plus the run-event feed
# (:func:`get_research_events`, plan 15.3-02's endpoint, added by 15.3-07). Same
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
    # WR-03: a run without a tribunal id can never resolve at the seam (the URL
    # would be /api/runs/None/...) -- existence-hidden 404, not a seam 500.
    if not run.tribunal_run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Seam call OUTSIDE the held DB session (mirrors get_bundle_url's connection-free
    # window). WR-03: the seam getter raise_for_status()es -- a tribunal-side 404
    # (RLS miss / unknown id) maps to the pinned existence-hidden 404, any other
    # seam failure to 502 -- never an unhandled 500.
    settings = get_settings()
    try:
        return tribunal_client.get_verification(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            run_id=run.tribunal_run_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Research engine unavailable"
        ) from exc


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
    # tribunal RLS 404s a cross-tenant/unknown source_id). WR-03: source_id is a free
    # path input never validated intake-side, so a tribunal 404 is the EXPECTED miss
    # shape -- map it to the pinned existence-hidden 404, any other seam failure to
    # 502 -- never an unhandled 500.
    settings = get_settings()
    try:
        return tribunal_client.get_source(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            source_id=source_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Source not found") from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Research engine unavailable"
        ) from exc


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
    # WR-03: a run without a tribunal id can never resolve at the seam (the URL
    # would be /api/runs/None/...) -- existence-hidden 404, not a seam 500.
    if not run.tribunal_run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Seam call OUTSIDE the held DB session; tribunal RLS 404s a cross-tenant/unknown
    # audit. WR-03: map the seam 404 to the pinned existence-hidden 404, any other
    # seam failure to 502 -- never an unhandled 500.
    settings = get_settings()
    try:
        return tribunal_client.get_audit_body(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            run_id=run.tribunal_run_id,
            audit_id=audit_id,
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Research engine unavailable"
        ) from exc


@research_router.get("/{intake_id}/research/{run_id}/events")
def get_research_events(
    intake_id: str,
    run_id: str,
    after_seq: int = Query(
        0, description="Return events with seq STRICTLY GREATER than this. 0 = from the start."
    ),
    limit: int = Query(500, description="Max events in this page; the engine clamps to 1..1000."),
    identity: Identity = Depends(_superadmin_gate),
    repo: IntakeRepository = Depends(get_tenant_repo),
) -> dict:
    """Proxy a run's persisted activity feed to the superadmin surface (D-01/D-05).

    THE BACKFILL READ behind the standalone run page. The SSE stream only carries
    what happens while somebody is watching; this is what makes closing the page and
    reopening it show TRUE history. It exists as an intake-side proxy rather than a
    direct engine call because the intake backend is the SOLE caller of Tribunal —
    the frontend never calls it directly (D-08).

    Authorization is :func:`get_research_audit_body`'s, arm for arm, because this is
    a brand-new READ surface and a new surface is a fresh chance to reintroduce the
    broken-RLS class of bug:

    * ``identity.role != "superadmin"`` → 404 (the gate dependency, plus this
      defense-in-depth in-body re-check). A client is user-role and D-08 says it can
      NEVER reach this — existence-hidden, never the forbidden status;
    * a cross-tenant / missing intake → 404;
    * a run that is not visible, or whose ``intake_id`` is not the path's → 404, so a
      caller cannot borrow one intake's authorization to read another's run;
    * WR-03 — a run with no ``tribunal_run_id`` could never resolve at the seam
      (the URL would be ``/api/runs/None/events``) → 404, not a seam 500.

    Every one of those is the SAME status with the SAME body: distinguishing them
    would confirm which of the two ids the caller got right, which is the whole
    property (T-15.3-60/T-15.3-61).

    The role and null-space arms live HERE and nowhere else. Plan 15.3-02 built the
    engine endpoint and could not prove them: the tribunal engine has no
    ``Identity`` — no role, no ``space_id`` — so its only isolation dimension is the
    JWT tenant plus the FORCE-RLS GUC. It recorded the handover rather than dropping
    it; ``tests/test_research_events_proxy.py`` is where the handover is discharged.

    ``after_seq`` / ``limit`` are forwarded as typed query parameters (a non-integer
    is a 422 before this body runs) and the engine's page JSON is returned VERBATIM —
    this proxy reshapes NOTHING, so a future field the engine adds reaches the page
    without a change here. The seam call runs OUTSIDE any held DB session (mirrors
    :func:`get_bundle_url`'s connection-free window, T-15.3-65).
    """
    if identity.role != "superadmin":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")

    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    # WR-03: a run without a tribunal id can never resolve at the seam (the URL
    # would be /api/runs/None/events) -- existence-hidden 404, not a seam 500.
    if not run.tribunal_run_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")

    # Seam call OUTSIDE the held DB session; tribunal RLS 404s a cross-tenant/unknown
    # run. Map the seam 404 to the pinned existence-hidden 404, any other seam or
    # transport failure to 502 -- never an unhandled 500.
    settings = get_settings()
    try:
        return tribunal_client.get_run_events(
            service_url=settings.tribunal_service_url,
            space_id=str(intake.space_id),
            acting_user_id=identity.uid,
            acting_email=identity.email,
            run_id=run.tribunal_run_id,
            after_seq=after_seq,
            limit=limit,
        )
    except httpx.HTTPStatusError as exc:
        seam_status = exc.response.status_code if exc.response is not None else 0
        if seam_status == 404:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found") from exc
        _log.warning(
            "events seam error: research_run_id=%s seam_status=%s", run_id, seam_status
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Research engine unavailable"
        ) from exc
    except httpx.HTTPError as exc:
        # Transport failure (timeout / connect error) — never an unhandled 500.
        _log.warning("events seam transport failure: research_run_id=%s err=%s", run_id, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Research engine unavailable"
        ) from exc


# ---------------------------------------------------------------------------
# SSE research stream (the ONE async def — cloned from stream_skill_runs)
# ---------------------------------------------------------------------------
#
# Injectable knobs (module-level so tests can monkeypatch them tiny — mirrors intake_routes).
TICK_SECONDS = 2.0  # one indexed SELECT every 2s
HEARTBEAT_SECONDS = 15.0  # ``: ping`` keeps proxies/Cloud Run from reaping idle streams
MAX_STREAM_SECONDS = 10 * 60  # in-handler cap; a run this long is treated as hung
# The RESEARCH terminal set — Tribunal literals carried VERBATIM (D-05 boundary). NEVER the
# skill-run success/failed vocabulary (16-RESEARCH Pitfall 3 / AP-6). Defined ONCE in
# app.research.run_status and re-exported here so the SSE handler and the poll driver
# cannot drift apart again; ``parked`` is deliberately not a member (see that module).
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
    # SUPERADMIN ONLY since 23.1-18 (D-23.1-16 addendum). This signature has NO
    # ``get_tenant_repo``, so the "gate above the repo" ordering rule has nothing to order
    # against here — but the gate being a DEPENDENCY is still what makes the denial
    # existence-hidden: dependencies resolve before the handler body, so the gate's 404
    # pre-empts the in-body pre-flight's null-space 403 (measured RED below).
    identity: Identity = Depends(_superadmin_gate),
) -> StreamingResponse:
    """Stream the intake's latest research-run state as ``text/event-stream`` (RUN-01).

    SUPERADMIN ONLY (D-23.1-16 addendum, 23.1-18). This is a READ, not a spend — but the
    frame it serves is the OPERATOR's diagnostic view: the run id, the engine's
    ``current_stage`` / ``stage_detail`` trace, ``cost_usd_total``, the chain-guard state
    (``chain_status`` / ``chain_broken_at`` / ``bundle_key``) and the run-event cursor
    ``event_seq``. It was the ELEVENTH and LAST route on this router still taking a bare
    ``get_current_identity``. D-23.1-16 originally excluded it on the grounds that "an
    ``EventSource`` cannot set an Authorization header" — **that premise was false for this
    codebase**: ``openResearchStream`` (``frontend/src/lib/api/research.ts:551``) opens it
    with ``fetch()`` carrying ``Authorization: Bearer ${token}`` from the same
    ``currentIdToken()`` source ``apiFetch`` uses, and ``EventSource`` appears NOWHERE in
    ``frontend/src``. Its only mount points are ``admin.pulse.intakes.$id.tsx`` and
    ``admin.pulse.runs.$runId.index.tsx`` (both via ``ResearchRunProgress``), so no
    legitimate non-superadmin caller exists. Measured before the gate: a role=``user`` in
    the intake's own space got 200 ``text/event-stream`` and the full operator frame; a
    null-space user got the pre-flight's 403 existence oracle. Denial + the
    still-streams counterweight live in ``tests/test_research_stream_gate.py``.

    The ONLY ``async def`` added by this plan (cloned from
    ``intake_routes.stream_skill_runs``): every DB touch goes through
    :func:`run_in_threadpool` so the blocking pg8000 read never runs on the event loop, and
    ``anyio.sleep`` between ticks releases the thread. Do NOT convert any other handler.

    PRE-FLIGHT (D-04, runs BEFORE the stream opens so the denial test is a plain GET):
    ``check_intake_in_scope`` in the threadpool — a ``PermissionError`` (null-space user)
    → 403, a falsy result (cross-tenant / missing) → existence-hidden 404. Both arms are
    now DEFENCE IN DEPTH behind the gate rather than the outer wall: a null-space caller
    can no longer reach the 403, because only a superadmin gets this far and the superadmin
    path sets no GUC. Kept, not deleted — it is what still 404s a superadmin asking about
    an intake that does not exist.

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
