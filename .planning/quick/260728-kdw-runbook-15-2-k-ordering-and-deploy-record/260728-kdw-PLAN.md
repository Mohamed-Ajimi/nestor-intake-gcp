---
id: 260728-kdw
slug: runbook-15-2-k-ordering-and-deploy-record
date: 2026-07-28
status: planned
---

# Quick Task 260728-kdw — Fix DEPLOY-RUNBOOK § 15.2.k ordering + fill the combined deploy record

## Why

The 2026-07-28 deploy followed `infra/DEPLOY-RUNBOOK.md` § 15.2.k as written, and the runbook's
ordering **caused an incident**: it deploys `tribunal-worker` at step 4 and only cancels the stuck
run at step 6. The worker booted during its own deployment health check, claimed run `d6bb3aae`
within seconds, and re-executed ~15 minutes of paid pipeline unattended. The operator deleted the
service to stop it.

The document must not be left in the state that caused this.

## The mechanism, established this session

`--min-instances=0` does **not** prevent a boot. Deploying a revision starts a container to
health-check it, and `tribunal/nestor_pulse_sdk/runs/worker.py`'s main loop (`while True:` at
~line 661) **claims first and sleeps last** — `claim_one()` runs at the top of the very first
iteration, before `asyncio.sleep(POLL_INTERVAL_SECONDS)` is ever reached.

Consequences:
- No env lever makes a boot safe. `NESTOR_WORKER_POLL_INTERVAL` cannot help, because the first
  claim precedes the first sleep.
- `NESTOR_WORKER_STALE_MINUTES` guards only the stale-`running` reclaim arm of `CLAIM_SQL`; it does
  nothing about a fresh `queued` row, which is claimable at any age.
- **An empty queue is the only protection.**

Re-proven live on the clean redeploy at 2026-07-28 12:35Z with `min-instances=0` set:
`Starting new instance. Reason: DEPLOYMENT_ROLLOUT` followed by `worker_started poll_s=2.0`.
It was harmless only because the queue had been proven empty first.

## Tasks

### Task 1 — Correct the § 15.2.k ordering and record the boot mechanism

Files: `infra/DEPLOY-RUNBOOK.md`

The existing step numbers are referenced from three other places (the 15.2.j reconciliation note,
the summary-checklist bullet for 15.2.k, and step 6's own cross-references). Renumbering in place
would silently invalidate those references, so instead:

- Insert an **ORDERING CORRECTION (2026-07-28)** block immediately under the § 15.2.k heading
  giving the authoritative execution order and naming the incident.
- Retitle step 4 so its position is unmissable, and fold in the boot mechanism + the
  claims-before-it-sleeps proof.
- Retitle step 6 to state that it precedes step 4.
- Update the 15.2.j reconciliation note so it no longer implies worker-at-step-4 is correct.
- Update the § 15.2.k summary-checklist bullet to carry the corrected order.

Verify: the corrected order appears above the numbered steps; step 4 and step 6 both state their
true relative position; no cross-reference still asserts the old order.

Done: a reader following the document top-to-bottom cannot reach the worker deploy before the
queue is empty.

### Task 2 — Add the credential-free queue-read recipe

Files: `infra/DEPLOY-RUNBOOK.md` (step 2)

Step 2 currently says "a Cloud SQL `psql` session" without saying how, and the obvious paths are
blocked: `nestor-pg` has an **empty** authorized-networks list, and the Phase-14 lockdown makes
`tribunal-api` reject a plain invoker token (`invalid internal caller token`).

Record the path that works and changes nothing:
`gcloud builds submit --no-source --config=… --service-account=nestor-run@…` running the Cloud SQL
Auth Proxy from inside Google's network. `nestor-run@` already holds `secretAccessor` on
`DATABASE_URL_WORKER`, so no IAM change and no allowlist change is needed.

Two traps to record with it:
- `nestor-run@` lacks `logging.logWriter`, so **build stdout is lost**. The result must be carried
  by **exit status**, with the vacuity and positive-control checks folded into the success
  condition.
- Read as `worker_user`, not `app_user` — `worker_user` matches the `worker_all` RLS policy and
  therefore sees exactly what `CLAIM_SQL` sees. An `app_user` read without a bound `app.tenant_id`
  returns zero rows and looks like an empty queue.

Verify: the recipe names the SA, the `--no-source` flag, the exit-status requirement and the
`worker_user` requirement.

Done: step 2 is executable without opening the database or granting anything.

### Task 3 — Fill the combined deploy record

Files: `infra/DEPLOY-RUNBOOK.md` (step 10)

Fill the table with the real values. **The one-`$SHA` property is broken** — the record's single
`$SHA` row cannot be filled honestly, so the table must be amended to carry two.

- `20260728-094409` — `tribunal-api`, `nestor-frontend`, `tribunal-worker`
- `20260728-132637` — `nestor-api` only (the seam 401/403 retry fix, commit `31a7f71`)

Revisions: `tribunal-api-20260728-094409-102356`, `nestor-frontend-00028-q52`,
`nestor-api-00044-8bz`, `tribunal-worker-00002-ztp`.
Heads: TRIBUNAL **0015**, INTAKE **0013**. Run `d6bb3aae`: `cancelled`.

Mark both change lists. Leave the operator's no-behaviour-change sentence for the operator —
it is theirs to write, and D-03 makes it a gate, not a formality.

Verify: no placeholder rows remain unfilled; the two SHAs are distinct and attributed.

Done: a reader six weeks from now can attribute a surprising V-01 result without archaeology.

## Out of scope

- The five standing debts (burner key rotation, `Nestor_Claude2` restore, the IAM grant decision,
  `ci_no_raw_db_access.sh`, D26-1). They are recorded elsewhere and unchanged by this task.
- The operator's no-engine-behaviour-change sentence (step 10) — operator-written by design.
