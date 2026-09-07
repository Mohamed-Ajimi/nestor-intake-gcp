"""``app/research/reconcile.py`` — the stateless orphaned-run sweep (DEF-23.2-03 / COST-01).

WHAT THIS IS. A sweep that finds every ``nestor.research_runs`` row still sitting in a
non-terminal status whose poll driver has stopped breathing, asks the engine what actually
happened, mirrors that answer back, and finalizes the row when the engine says it is done.
It is a DIFFERENT DRIVER over the machinery :mod:`app.research.run_task` already owns —
``mirror_tick``, ``build_completion``, ``finalize_completed`` / ``finalize_failed`` /
``finalize_parked`` and the RESEARCH terminal set — never a second implementation of any of
them. Everything this module adds is the part ``run_task`` structurally cannot have: a way
to reach a run WITHOUT the request identity and the in-process ``BackgroundTask`` that
started it.

WHAT THIS IS NOT.

* **It is not a fix for the Tribunal worker.** The worker is already durable: a
  ``FOR UPDATE SKIP LOCKED`` claim, a 30 s per-run heartbeat, stale reclaim,
  ``MAX_RECLAIMS=2`` and a worded reap. That is a genuine at-least-once execution
  guarantee and nothing here touches it (23.3-CONTEXT.md § 4 / § 8).
* **It is not a dispatch rewrite.** Push-based dispatch was measured and REJECTED — a real
  run took 64.2 minutes and a Cloud Run *service* request is capped at 60 (§ 1 / § 2).
* **It is not a replacement for the poll driver.** The driver stays; what changes is that
  it becomes an OPTIMISATION (fast, ~3 s updates) rather than the ONLY path to a terminal
  state. That reframing is the entire point of § 8.

THE HOLE IT CLOSES. ``run_poll_driver`` is a ``while True`` inside a FastAPI
``BackgroundTask`` with no wall-clock cap. When that nestor-api instance recycles — a
deploy, a scale event, Cloud Run's own lifecycle — the driver dies silently: the engine
keeps executing and spending, ``research_runs`` is never mirrored or finalized, the operator
watches a frozen card forever, and NOTHING sweeps it. That is DEF-23.2-03.

TWO CONSTRAINTS ON THE SHAPE, both measured on 2026-09-07:

* **Cloud Scheduler is not enabled on this project** (``PERMISSION_DENIED`` — enabling it is
  an operator/IAM action). So the sweep is a PLAIN CALLABLE that either an in-process timer
  (plan 06) or a future Scheduler HTTP trigger can drive. It takes no FastAPI object, no
  request and no identity argument.
* **nestor-api runs ``maxScale=4``**, so four instances may sweep at once. Two of them
  mirroring the same run concurrently is the defect this phase must NOT introduce, so the
  claim is serialised the same way the worker's already is (§ 10 trap 4: do not invent a
  third mechanism).

THE CONNECTION CONTRACT (T-16-06) is inherited verbatim: no pooled DB connection is held
across a seam call. The claim commits before ``get_metrics`` is issued; the mirror and the
finalize each open their own short ``tenant_session``.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.auth.identity import Identity
from app.db.ai_session import superadmin_session, tenant_session
from app.db.repository import ResearchRunRepository
from app.mail import resend
from app.mail.render import (
    render_research_complete,
    render_research_failed,
    render_research_parked,
)
from app.research import run_task, tribunal_client
from app.research.run_status import (
    RESEARCH_TERMINAL,
    is_research_parked,
    is_research_success,
)

# WARNING level on purpose, for the same reason ``run_task`` says so at its top: uvicorn's
# default logging config drops INFO from app loggers (no root handler — only the WARNING+
# lastResort stderr handler). A sweep that logs at INFO logs nowhere, and a silent
# self-healing mechanism is indistinguishable from one that never ran. That silence has
# already cost this project a full UAT day (16-05).
log = logging.getLogger(__name__)


#: How long a run may go WITHOUT a driver heartbeat before the sweep treats it as orphaned.
#:
#: THIS NUMBER IS NOT TASTE. A live, healthy poll driver is legitimately SILENT — it
#: ``continue``s round its loop without calling ``mirror_tick`` at all — for up to
#: ``run_task._MAX_METRICS_AUTH_OUTAGE_SECONDS`` (200 retries x 3.0 s = 600 s = 10 MINUTES)
#: while it tolerates a 401/403 from a Cloud Run revision rollout. That budget was itself
#: sized from the live 2026-07-28 incident, not chosen.
#:
#: So a cutoff at or below 10 minutes would sweep a driver that is healthy and deliberately
#: waiting, and the sweep's designed response to an orphan is to TAKE THE RUN OVER: a second
#: bundle build, a second completion mail, and a second terminal write on a run that already
#: cost ~$45. 15 minutes clears the driver's own budget by 50%.
#:
#: ⚠ THE TWO CONSTANTS ARE A PAIR. Anyone raising ``_MAX_METRICS_AUTH_RETRIES`` (or
#: ``POLL_SECONDS``) must raise this with it, and anyone lowering this must lower those.
#: ``tests/test_research_reconciler.py`` test 9 asserts on BOTH numbers, from BOTH modules,
#: so they cannot drift apart silently.
#:
#: The same margin is what protects the NON-terminal mirror below, which is deliberately not
#: compare-and-swapped: the only way this codebase can produce a driver that is silent for
#: longer than 10 minutes and then wakes up and writes is to raise that budget past this
#: cutoff. See :func:`reconcile_one`.
ORPHAN_CUTOFF_MINUTES = 15

#: How long a claim holds a row against the other three nestor-api instances.
#:
#: Long enough for one ``get_metrics`` (``tribunal_client._TIMEOUT_S = 30.0``) plus a
#: completion build (report + bundle fetch + chain verify + zip + GCS upload); short enough
#: that a sweep killed mid-flight frees the row again within about one sweep interval.
#:
#: A LEASE, NOT A LOCK, and the distinction is the whole design: a lease EXPIRES BY ITSELF,
#: so a dead sweeper cannot strand a run. Stranding runs behind a dead process is precisely
#: the failure this module exists to end, and reintroducing it one layer up would be absurd.
LEASE_MINUTES = 5

#: How many orphans one sweep may take at a time.
#:
#: Bounded on purpose. An unbounded sweep on a bad day (a deploy that recycled every
#: instance mid-run) is a thundering herd of 30-second seam calls issued from an instance
#: that is also serving operator requests. Ten is a batch a single tick can finish inside
#: the lease; the rest are still there on the next tick, which is what "stateless" buys.
SWEEP_BATCH = 10


def claim_orphans(limit: int = SWEEP_BATCH) -> list[dict[str, Any]]:
    """Claim up to ``limit`` orphaned runs in ONE short, committed transaction.

    Runs on :func:`app.db.ai_session.superadmin_session` — cross-space reach, NO GUC — for
    exactly the reason :func:`app.db.ai_session.sweep_orphaned_skill_runs` reaches for the
    same engine: the sweep does not know which space a lost run belongs to until it has
    read the row, so it cannot set a tenant GUC first. The 0011
    ``research_runs_superadmin_all`` policy (``current_user = 'app_superadmin'``) is what
    admits the statement.

    The session comes from the ``app/db/`` seam rather than from an engine fetched here,
    because ``scripts/ci_no_raw_db_access.sh`` (D-03) fails the build for any module
    outside that directory that constructs its own engine or sessionmaker. That guard is
    what keeps the per-space filter structural, so this module asks the seam for the
    session it needs instead of the guard being widened for it.

    The transaction is deliberately TINY and COMMITS BEFORE ANY SEAM CALL (T-16-06). The
    row lock ``FOR UPDATE SKIP LOCKED`` takes lives only for the duration of this
    statement; from the moment it commits, the ``reconcile_lease_until`` value written here
    is the ONLY thing keeping the other three nestor-api instances off the row.

    Returns PLAIN dicts, never live ORM rows: the connection is released the instant this
    function returns, and a detached row would explode later (the release contract).
    """
    # The statement lives INSIDE the function on purpose: its exact shape is the
    # correctness argument for the whole module, and four details are load-bearing.
    #
    # 1. ``FOR UPDATE SKIP LOCKED`` is what makes two concurrent sweeps DISJOINT at the
    #    instant of claiming: the second sweep's candidate scan steps OVER the row the
    #    first has locked instead of queueing behind it. The LEASE is what keeps them
    #    disjoint AFTERWARDS, once this transaction has committed, the connection has gone
    #    back to the pool and the row lock is gone. Both are needed; neither alone is
    #    enough. This is the same pattern the Tribunal worker's ``claim_one`` already
    #    uses — do not invent a third.
    # 2. ``make_interval(mins => :x)``, NEVER a literal ``INTERVAL ':x minutes'``. The
    #    literal-bind form fails at runtime with bound parameters — the B2 fix already
    #    recorded in ``tribunal/nestor_pulse_sdk/runs/worker.py``'s module docstring. Do
    #    not rediscover it.
    # 3. ``COALESCE(driver_heartbeat_at, created_at)`` so a row written before migration
    #    0017 behaves exactly as it would have: it falls back to AGE, which for a row
    #    already older than the cutoff is the right answer, and which makes the sweep
    #    useful on the existing backlog from its very first tick rather than only on runs
    #    started after the deploy.
    # 4. A POSITIVE ``status IN (...)``, never a negated terminal set. ``mirror_tick``
    #    writes the engine's status VERBATIM into a plain ``String`` with no CHECK
    #    constraint, so the engine can emit a status this repository has never heard of.
    #    Under a negated predicate that unknown status would count as a candidate and the
    #    sweep would seize a perfectly healthy run. Failing OPEN costs a missed sweep;
    #    failing closed would cost a live run. Same three literals, same reasoning, as
    #    ``uq_research_runs_one_inflight_per_intake`` and
    #    ``ix_research_runs_orphan_candidates`` — the partial index this query drives.
    claim_sql = text(
        """
        UPDATE nestor.research_runs
           SET reconcile_lease_until = NOW() + make_interval(mins => :lease)
         WHERE id IN (
           SELECT id
             FROM nestor.research_runs
            WHERE status IN ('queued', 'running', 'needs_report_spec')
              AND (reconcile_lease_until IS NULL OR reconcile_lease_until < NOW())
              AND COALESCE(driver_heartbeat_at, created_at)
                  < NOW() - make_interval(mins => :cutoff)
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT :limit
         )
        RETURNING id, space_id, intake_id, status, tribunal_run_id,
                  acting_user_id, acting_email, bundle_key
        """
    )
    with superadmin_session() as session:
        result = session.execute(
            claim_sql,
            {
                "lease": LEASE_MINUTES,
                "cutoff": ORPHAN_CUTOFF_MINUTES,
                "limit": limit,
            },
        )
        return [dict(m) for m in result.mappings().all()]


def _replay_identity(row: dict[str, Any]) -> Identity:
    """Rebuild the identity this run's OWN driver already ran under.

    A line reading "constructs a superadmin ``Identity`` from a database row" SHOULD stop a
    reviewer, so the answer lives here for when it does:

    * It is a REPLAY, not a widening. ``run_task._patch_run``'s docstring records that the
      research write path already runs under a superadmin identity, because the triggering
      actor is a superadmin who has no own space; the repo ``_scope`` is a no-op for that
      role and the row is reached by id across the intake's space. This function reproduces
      that identity — it does not grant anybody anything they did not already have.
    * The values are NOT request input. ``acting_user_id`` and ``acting_email`` were written
      SERVER-SIDE from a verified token, inside the same INSERT/UPDATE that created or
      resumed the row (plan 23.3-04, ``research_routes.py``). Nothing a caller can send
      reaches this constructor.
    * The alternative — a space-scoped ``user`` identity leaning on the
      ``research_runs_space_isolation`` policy — is tighter and is recorded as a deferral
      rather than taken here, because the ``app_user`` WRITE path on this table has never
      been exercised and a sweep is the wrong place to find out (DEF-23.3-06).
    """
    return Identity(
        uid=row["acting_user_id"],
        email=row["acting_email"],
        role="superadmin",
        space_id=None,
    )


def _clear_lease(identity: Identity, research_run_id: Any) -> None:
    """Release the claim on a run that is still in flight, so the next tick can re-take it.

    Its own short ``tenant_session`` (the release contract). Failing to clear the lease is
    not fatal — it expires by itself in ``LEASE_MINUTES`` — so this never raises out.
    """
    try:
        with tenant_session(identity) as session:
            ResearchRunRepository(session, identity).patch(
                research_run_id, reconcile_lease_until=None
            )
    except Exception:  # noqa: BLE001 - a stuck lease self-heals on expiry; never fail here
        log.warning(
            "reconciler could not clear the lease on research_run_id=%s (it will expire "
            "on its own in %s minutes)",
            research_run_id, LEASE_MINUTES, exc_info=True,
        )


def _park_reason(metrics: dict[str, Any]) -> str:
    """Compose the ``"[park#<seq>] <reason>"`` string ``finalize_parked`` requires.

    ASVS V5, exactly as ``run_poll_driver``'s park branch does it: ``metrics["park"]`` is
    REMOTE JSON whose members originate in provider error text. Read every member
    defensively, never trust its types, never let a malformed descriptor raise.

    The marker is the DEC-5 mail-idempotency record and MUST land in the column verbatim.
    """
    park = metrics.get("park")
    if not isinstance(park, dict):
        park = {}
    try:
        seq = int(park.get("seq"))
    except (TypeError, ValueError):
        seq = 1
    reason = str(park.get("reason") or "").strip() or run_task._DEFAULT_PARK_REASON
    return f"[park#{seq}] {reason}"[: run_task._MAX_PARK_MESSAGE_CHARS]


def reconcile_one(row: dict[str, Any]) -> str:
    """Mirror or finalize ONE claimed row. Returns an outcome word; NEVER raises.

    Outcomes: ``"mirrored"``, ``"finalized"``, ``"skipped_no_actor"``,
    ``"skipped_no_engine_run"``, ``"skipped_lost_cas"``, ``"error"``.

    The no-raise contract is not politeness. This runs on a timer inside the API process
    over a BATCH of rows; an exception escaping here would kill the sweep for every OTHER
    orphan in the batch, which is the failure mode the module exists to end.

    Order of operations, and why each step is where it is:

    1. **actor** — a row with no recorded human is SKIPPED, loudly, and makes ZERO seam
       calls (see below);
    2. **read** — one short session builds the trigger context, then releases;
    3. **CALL** — ``get_metrics`` with NO database connection held (T-16-06);
    4. **non-terminal** → ``mirror_tick`` + clear the lease, and stop. The sweep does NOT
       schedule a replacement driver: a ``BackgroundTask`` needs a request and there is
       none. The run is simply swept again next tick — which is § 8's whole framing, that
       the per-run driver is an optimisation rather than the only path to a terminal state;
    5. **terminal** → build the completion (only if it is not already built), then a
       compare-and-swap terminal write, then the mail POST-COMMIT.

    NO RETRY HERE, deliberately. The driver's 5xx and 401/403 budgets exist because a
    driver gets ONE chance at a run; a sweep runs again in minutes, which is a strictly
    better retry than a loop pinning an API instance that is also serving requests.
    """
    research_run_id = row.get("id")
    try:
        # ---- 1. THE ACTOR ------------------------------------------------------------
        # The Tribunal seam REQUIRES non-empty X-Acting-User-Id and X-Acting-User-Email and
        # answers 400 without them (auth/internal_caller.py:184-223), because D-05
        # attribution is a hard legal constraint on a FROZEN audit chain.
        #
        # ⛔ So a row with no recorded actor is SKIPPED. Do NOT substitute a placeholder
        # address, a service account, or a "system" actor id. A fabricated actor on a
        # legally load-bearing chain is worse than an unswept run — the unswept run is
        # visible and recoverable, the fabricated attribution is neither. The WARNING is
        # what gets a human to look, which is the only correct outcome here.
        #
        # This is also where plan 23.3-04's routed gap lands: ``resume_research`` does not
        # log the missing-email warning that ``trigger_research`` logs, so a resume by an
        # email-less superadmin creates the same NULL silently. This branch is the consumer
        # that meets it, and it is loud.
        if not row.get("acting_user_id") or not row.get("acting_email"):
            log.warning(
                "reconciler SKIPPING research_run_id=%s: no recorded actor "
                "(acting_user_id=%r acting_email=%r). The seam requires both headers and "
                "answers 400 without them; a sweep must replay the original human and must "
                "NEVER invent one. This run needs a human to look at it.",
                research_run_id, row.get("acting_user_id"), row.get("acting_email"),
            )
            return "skipped_no_actor"

        # The run never reached the engine, so there is nothing to ask about. Finalizing it
        # would be a judgement about a run that may never have started, and this plan does
        # not make that judgement (DEF-23.3-07).
        tribunal_run_id = row.get("tribunal_run_id")
        if not tribunal_run_id:
            log.warning(
                "reconciler SKIPPING research_run_id=%s: no tribunal_run_id — the run "
                "never reached the engine, and deciding what a never-started run should "
                "finalize to is out of this plan's scope (DEF-23.3-07)",
                research_run_id,
            )
            return "skipped_no_engine_run"

        identity = _replay_identity(row)

        # ---- 2. READ (its own short session; released before the seam call) ----------
        with tenant_session(identity) as session:
            ctx = run_task.load_trigger_context(session, identity, row["intake_id"])

        seam_kwargs = dict(
            service_url=ctx["service_url"],
            space_id=ctx["space_id"],
            acting_user_id=ctx["acting_user_id"],
            acting_email=ctx["acting_email"],
        )

        # ---- 3. CALL (NO database connection held — T-16-06) -------------------------
        metrics = tribunal_client.get_metrics(run_id=tribunal_run_id, **seam_kwargs)
        if not isinstance(metrics, dict):
            log.warning(
                "reconciler got a non-dict metrics payload for research_run_id=%s (%s) — "
                "nothing is written rather than guessed",
                research_run_id, type(metrics).__name__,
            )
            _clear_lease(identity, research_run_id)
            return "error"
        status = metrics.get("status")

        # ---- 4. STILL RUNNING --------------------------------------------------------
        if status not in RESEARCH_TERMINAL:
            # ``mirror_tick`` REUSED verbatim — the same short-session, GUC-re-issuing,
            # status-VERBATIM write the live driver performs, including the
            # ``driver_heartbeat_at`` stamp. This single call is most of the value of the
            # whole module: an orphaned run stops being frozen at whatever the operator's
            # panel last saw, without anybody having to finalize anything.
            #
            # Deliberately NOT compare-and-swapped, unlike the terminal write below. The
            # window is [claim -> this write], and for a live driver to land a TERMINAL
            # status inside it, that driver would have to be silent for longer than
            # ORPHAN_CUTOFF_MINUTES and then wake up and write. The only silent path this
            # codebase has is the 401/403 budget, capped at 600 s — 10 minutes against a
            # 15-minute cutoff. That margin, not luck, is what closes this window, which is
            # the second reason the two constants are a pair. If the outcome ever did
            # happen it is self-healing and costs nothing: the row goes back to
            # non-terminal, the next sweep reads the same terminal metrics and finalizes it
            # properly. Recorded as DEF-23.3-05.
            run_task.mirror_tick(identity, research_run_id, tribunal_run_id, metrics)
            _clear_lease(identity, research_run_id)
            return "mirrored"

        # ---- 5. TERMINAL -------------------------------------------------------------
        # ``mirror_tick`` is NOT called on this path, and that is deliberate: the finalize
        # IS the mirror (it writes status, stage, cost and the cursor in one statement), and
        # a mirror here would overwrite ``status`` with the terminal literal and thereby
        # destroy the very precondition the compare-and-swap below is built on. See the
        # SUMMARY — this is a correction to the plan's stated ordering, not an omission.
        completion: dict[str, Any] | None = None
        if is_research_success(status) and not row.get("bundle_key"):
            # Connection-free (T-17-07): report fetch + D-01-scrubbed bundle fetch + the
            # D-06 chain gate + zip + GCS upload all happen with NO pooled connection held.
            completion = run_task.build_completion(ctx, research_run_id, tribunal_run_id)
        elif is_research_success(status):
            # A non-NULL ``bundle_key`` at claim time means the bundle was already built and
            # uploaded. Rebuilding it would re-run ``verify_chain``, re-fetch the report and
            # re-upload to GCS for nothing. This cheap READ-TIME guard is what keeps the
            # narrow claim-to-write window from costing anything.
            log.warning(
                "reconciler NOT rebuilding the bundle for research_run_id=%s: "
                "bundle_key is already set (%s)",
                research_run_id, row.get("bundle_key"),
            )

        to = [ctx["acting_email"]] if ctx.get("acting_email") else []
        cta_url = run_task._admin_cta(ctx)
        pending: list[dict[str, Any]] = []
        won = 0

        with tenant_session(identity) as session:
            repo = ResearchRunRepository(session, identity)
            # THE COMPARE-AND-SWAP (D-23.1-05), and it is the FIRST statement in this
            # transaction on purpose: it both proves the precondition and takes the row
            # lock, so everything written after it in this same transaction is protected by
            # that lock. ``expected`` is the status observed AT CLAIM TIME.
            #
            # If the live driver (or another sweep whose lease had expired) finalized in
            # between, the precondition fails in the database, ``rowcount == 0``, and this
            # function returns having written nothing and sent NO mail. A read-then-write
            # here would produce TWO completion mails and two terminal writes on a ~$45 run;
            # ``patch_if`` puts the precondition in the same UPDATE's WHERE, which is the
            # whole guarantee.
            #
            # The winner also releases its own lease in this same statement.
            won = repo.patch_if(
                research_run_id,
                {"status": row["status"]},
                reconcile_lease_until=None,
            )
            if won:
                if is_research_success(status):
                    if completion is None:
                        # The bundle already existed, so carry the completion-derived
                        # columns FORWARD off the row rather than letting the finalize write
                        # NULL over a persisted report, chain verdict and bundle key. Safe
                        # to read here: the CAS above holds the row lock.
                        prior = repo.get(research_run_id)
                        completion = {
                            "report": {
                                "markdown": getattr(prior, "output_markdown", None)
                            },
                            "chain_status": getattr(prior, "chain_status", None),
                            "chain_broken_at": getattr(prior, "chain_broken_at", None),
                            "bundle_key": getattr(prior, "bundle_key", None),
                        }
                    run_task.finalize_completed(
                        session,
                        research_run_id,
                        metrics,
                        completion.get("report") or {},
                        identity=identity,
                        chain_status=completion.get("chain_status"),
                        chain_broken_at=completion.get("chain_broken_at"),
                        bundle_key=completion.get("bundle_key"),
                    )
                    if to:
                        # D-07: the completion mail sends on BOTH the verified and the
                        # broken-chain path — there is no broken-chain variant. Do not gate
                        # it on chain_status.
                        pending.append(
                            {
                                "to": to,
                                "subject": "Je onderzoek is klaar",
                                "html": render_research_complete(
                                    project_title=ctx["project_title"],
                                    duration_min=run_task._duration_min(metrics),
                                    cost_usd=metrics.get("cost_usd_total"),
                                    cta_url=cta_url,
                                    app_base_url=ctx.get("app_base_url"),
                                ),
                            }
                        )
                elif is_research_parked(status):
                    reason = _park_reason(metrics)
                    run_task.finalize_parked(
                        session, research_run_id, metrics, reason, identity=identity
                    )
                    if to:
                        # No DEC-5 "already notified?" check, and that is reasoned rather
                        # than forgotten: the claim's POSITIVE status filter means a claimed
                        # row is never already ``parked``, so the driver's precondition
                        # (prior status parked AND the same marker) can never hold here.
                        # Where the two could differ, the driver's own recorded asymmetry
                        # decides it — "a duplicate mail is a nuisance, a dropped one is the
                        # operator's only signal that a paid run stopped".
                        pending.append(
                            {
                                "to": to,
                                "subject": "Je onderzoek staat op pauze",
                                "html": render_research_parked(
                                    project_title=ctx["project_title"],
                                    park_reason=reason.split("] ", 1)[-1],
                                    cta_url=cta_url,
                                    app_base_url=ctx.get("app_base_url"),
                                ),
                            }
                        )
                else:
                    error_message = (
                        metrics.get("error_message") or run_task._default_error(metrics)
                    )
                    run_task.finalize_failed(
                        session, research_run_id, metrics, error_message,
                        identity=identity,
                    )
                    if to:
                        pending.append(
                            {
                                "to": to,
                                "subject": "Je onderzoek is mislukt",
                                "html": render_research_failed(
                                    project_title=ctx["project_title"],
                                    error_summary=error_message,
                                    cta_url=cta_url,
                                    app_base_url=ctx.get("app_base_url"),
                                ),
                            }
                        )

        # ---- the transaction has COMMITTED by here -----------------------------------
        if not won:
            log.warning(
                "reconciler LOST the compare-and-swap on research_run_id=%s (expected "
                "status=%r): somebody else finalized it first. No write, no mail.",
                research_run_id, row.get("status"),
            )
            return "skipped_lost_cas"

        # MAIL AFTER THE COMMIT, NEVER INSIDE THE WRITE (F-06 / D-23.2-14). A Resend
        # transport error inside the write transaction once rolled back a completion and
        # rewrote a paid, completed run as ``failed`` — the operator saw a failure on a
        # ~$45 run that had produced a report, a verified chain and an uploaded bundle, and
        # reran it. Each send gets its OWN try; a failure is logged and swallowed, because
        # the run is already correctly labelled on disk and nothing may relabel it.
        for mail in pending:
            try:
                resend.send(to=mail["to"], subject=mail["subject"], html=mail["html"])
            except Exception:  # noqa: BLE001 - the run is committed; the send is best-effort
                log.warning(
                    "reconciler terminal mail FAILED (run already finalized, not "
                    "retried): research_run_id=%s subject=%s",
                    research_run_id, mail["subject"], exc_info=True,
                )

        log.warning(
            "reconciler FINALIZED research_run_id=%s status=%s (its driver was gone)",
            research_run_id, status,
        )
        return "finalized"

    except Exception:  # noqa: BLE001 - one bad row must never kill the sweep
        log.warning(
            "reconciler ERROR on research_run_id=%s — the row keeps its lease and is "
            "retried on a later sweep",
            research_run_id, exc_info=True,
        )
        return "error"


def sweep_once(limit: int = SWEEP_BATCH) -> dict[str, int]:
    """Claim a batch of orphans, reconcile each, and return the tally.

    A PLAIN CALLABLE: no FastAPI object, no request, no identity argument, no state carried
    between calls. That is what lets an in-process timer (plan 06) and a future Cloud
    Scheduler HTTP trigger drive the very same unit, and it is what makes the mechanism
    self-healing — ANY nestor-api instance can recover ANY orphaned run, which is exactly
    what the per-run poll driver cannot do.

    Returns ``{"claimed", "mirrored", "finalized", "skipped", "errors"}``.
    """
    counts = {"claimed": 0, "mirrored": 0, "finalized": 0, "skipped": 0, "errors": 0}
    try:
        rows = claim_orphans(limit)
    except Exception:  # noqa: BLE001 - a failed claim must not kill the caller's timer
        log.warning("reconciler claim FAILED — no rows swept this tick", exc_info=True)
        counts["errors"] += 1
        return counts

    counts["claimed"] = len(rows)
    for row in rows:
        outcome = reconcile_one(row)
        if outcome == "mirrored":
            counts["mirrored"] += 1
        elif outcome == "finalized":
            counts["finalized"] += 1
        elif outcome == "error":
            counts["errors"] += 1
        else:
            counts["skipped"] += 1

    if counts["claimed"]:
        # WARNING, not INFO — see the module logger note. A sweep that claimed rows is the
        # ONLY evidence that runs were being lost, and it must survive uvicorn's default
        # logging config.
        log.warning(
            "reconciler sweep: claimed=%s mirrored=%s finalized=%s skipped=%s errors=%s",
            counts["claimed"], counts["mirrored"], counts["finalized"],
            counts["skipped"], counts["errors"],
        )
    return counts
