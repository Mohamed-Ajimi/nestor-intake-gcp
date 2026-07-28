---
id: 260728-kdw
slug: runbook-15-2-k-ordering-and-deploy-record
date: 2026-07-28
status: complete
---

# Quick Task 260728-kdw — SUMMARY

Fixed the `infra/DEPLOY-RUNBOOK.md` § 15.2.k ordering that caused the 2026-07-28 incident, recorded
the mechanism behind it, and filled the combined deploy record.

## What was wrong

The runbook deployed `tribunal-worker` at step 4 and only resolved the stuck run at step 6.
Following it as written re-executed ~15 minutes of paid pipeline unattended.

## The mechanism, now written down

`--min-instances=0` does not prevent a boot — deploying a revision health-checks it. And **no env
lever can compensate**, because `runs/worker.py`'s `while True:` **claims first and sleeps last**:
`claim_one()` runs at the top of the first iteration, before `asyncio.sleep()` is reached. So
`NESTOR_WORKER_POLL_INTERVAL` is useless as a safety lever, and `NESTOR_WORKER_STALE_MINUTES` only
guards `CLAIM_SQL`'s stale-`running` reclaim arm — a `queued` row is claimable at any age.

**An empty queue is the only protection.** Re-proven live at 12:35Z on the clean redeploy:
`Reason: DEPLOYMENT_ROLLOUT` → `worker_started poll_s=2.0`, with `min-instances=0` set.

## Changes

1. **Ordering correction.** The step numbers are cited from three other places, so renumbering would
   silently invalidate them. Instead the corrected sequence `0→1→2→3→5→6→4→7→8→9→10` is stated in a
   blocking callout under the § heading, step 4 is retitled "EXECUTE THIS AFTER STEP 6", step 6
   states it precedes step 4, and both the 15.2.j reconciliation note and the summary-checklist
   bullet were updated. Step 4 now also ships the worker **paused** (`MIN_INSTANCES=0`) so the
   unpause stays a separate act.
2. **Queue-read recipe (step 2).** Step 2 said "a Cloud SQL `psql` session" without saying how, and
   both obvious paths are closed: `nestor-pg`'s authorized-networks list is empty, and the Phase-14
   lockdown rejects a plain invoker token with `invalid internal caller token`. Recorded the path
   that changes nothing: `gcloud builds submit --no-source --service-account=nestor-run@…` running
   the Cloud SQL proxy from inside Google's network, since `nestor-run@` already holds
   `secretAccessor` on `DATABASE_URL_WORKER`. Two traps recorded with it — `nestor-run@` lacks
   `logging.logWriter` so **build stdout is lost** and the result must ride the **exit status**
   (with vacuity + positive-control folded into the success condition, then proven by inverting it);
   and the read must be as **`worker_user`**, since `app_user` without a bound `app.tenant_id`
   returns zero rows and looks exactly like an empty queue.
3. **Deploy record filled**, including an explicit correction that the one-`$SHA` property is broken:
   `20260728-094409` (worker/api/frontend) and `20260728-132637` (`nestor-api`, the 401/403 fix).
   Both change lists marked. Two honest gaps left visible rather than papered over: the engine
   gate's `collecting:` count was never written down in the 09:4x session and so is **not asserted**,
   and D-L's live verification was overtaken by the incident.

## Deliberately not done

- **The operator's no-engine-behaviour-change sentence.** It is a person's attestation, not a
  derivable fact. Marked **NOT YET WRITTEN — still owed before V-01**, with the note that nothing
  observed contradicts it and that "nothing contradicts it" is not the attestation.
- The five standing debts (burner key rotation, `Nestor_Claude2` restore, the IAM grant decision,
  `ci_no_raw_db_access.sh`, D26-1) — unchanged and recorded elsewhere.

## Follow-up worth flagging

The deploy record now notes the attribution consequence of two SHAs: if V-01 surprises on run
*finalization* specifically, `nestor-api` (SHA B) carries a behaviour change the other three
services do not, and is the first place to look — not the engine.
