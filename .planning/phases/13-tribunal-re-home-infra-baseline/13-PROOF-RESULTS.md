# Phase 13 — Tribunal Re-home Proof Results

> Operator-recorded evidence for the Plan-04 live session. The dev machine has no
> Python/Docker and `terraform apply` is blocked, so every value below is captured by the
> operator (project "Nestor Pulse", acct `tools@dotto.be`, region `europe-west1`) from the
> live proof run and pasted here. This file feeds **Phase 16** stale-run + cost calibration
> (ENGINE-02) and closes the ENGINE-04 (chain) + ENGINE-08 (concurrency) gates.

Status: **TASK 1 COMPLETE (deploy green, 2026-07-20)** — Tasks 2–3 in progress.

> **Single-project discovery (live-session correction).** There is NO separate intake
> project: `project-cb01b861-cb4a-438d-b9a` IS "Nestor Pulse" and hosts BOTH the live
> intake platform AND the old standalone Tribunal build. All "old project" teardown steps
> are **resource-level** (services `nestor-pulse-*`, stopped SQL `nestor-prod-pg`, AR repo
> `nestor-pulse`) — NEVER project deletion. Provider secrets (`Nestor_*`) already existed
> in-project; no reseeding was needed (D-06 satisfied trivially).

---

## Deployed revisions (Task 1 — Step 13.a–13.g)

| Resource | Value |
|----------|-------|
| Intake project id (`$GOOGLE_PROJECT`) | `project-cb01b861-cb4a-438d-b9a` (the single "Nestor Pulse" project) |
| Image tag (`$SHA`) | `20260720-161029-fix1` (both images; `-fix1` = env.py commit fix rebuild) |
| `tribunal-api` revision | `tribunal-api-20260720-161029-fix1-164103` |
| `tribunal-worker` revision | `tribunal-worker-20260720-161029-fix1-163954` |
| `tribunal-migrate` Job execution | `tribunal-migrate-sc64g` — succeeded (exit 0; earlier `-5rmmh` failed on alembic cwd, `-mhwdh` rolled back — see deviations) |
| Alembic version table | ✅ `tribunal.tribunal_alembic_version` = `0010`; 10 tables in `tribunal`; 0 leak into `public`; `ck_run_status` includes `needs_report_spec` |
| tribunal-api `/healthz` | `/health` → 200 `{"status":"ok"}` (`/healthz` is intercepted by Cloud Run's platform — documented in `health.py`) |
| tribunal-api `/readyz` | ✅ 200 `{"status":"ready","db":"ok"}` |
| Worker log `worker_started` | ✅ `worker_started poll_s=2.0`, health server up, zero WARNING+ logs (worker_user DSN, no SCHEMA-public grant errors) |
| FIRST-BUILD legitimacy gate (verbatim `requirements.txt`) | ✅ Both images built cleanly on first submit (T-13-SC) |

### Live-session deviations (Task 1)

1. **`db/base.py` runtime search_path fix (commit `fix(13-02)`):** runtime engine was
   schema-blind; added `server_settings search_path=tribunal,public` — proven by `/readyz`
   `db:ok`.
2. **`env.py` transaction-ownership fix (commit `fix(13-02)`):** the pre-configure
   `CREATE SCHEMA`/`SET search_path` autobegan a transaction Alembic didn't own → first
   migration run (`-mhwdh`) logged 0001→0010 then silently ROLLED BACK. Preamble commits
   added; rerun persisted (verified via one-off `tribunal-verify` job).
3. **Migrate job invocation:** jobs use `--set-cloudsql-instances` (not
   `--add-cloudsql-instances`) and alembic must run from `/app/nestor_pulse_sdk`
   (`sh -c "cd /app/nestor_pulse_sdk && alembic upgrade head"`) because
   `alembic.ini script_location` is cwd-relative.
4. **Old services share `DATABASE_URL*:latest`:** the defunct `nestor-pulse-*` services
   (SQL `nestor-prod-pg` STOPPED) reference the same secret ids; they may crash-loop on
   cold start until torn down — harmless (they have no `public.run` to corrupt).

## Cloud Build test suite (Task 2 — Step 13.e `cloudbuild.test.yaml`)

| Item | Value |
|------|-------|
| Critical-subset build | ✅ GREEN 2026-07-20 (24 tests: `test_schema_isolation`, `test_advisory_lock_exactly_once`, `test_hash_chain_replay`, `test_rls_isolation` — all pass on real Postgres) |
| `test_schema_isolation.py` (Plan 02) | ✅ pass (incl. live `upgrade head` → `tribunal.tribunal_alembic_version`) |
| `test_advisory_lock_exactly_once.py` (Plan 02) | ✅ pass (exactly-once under two racing executors; distinct runs don't serialize) |
| `test_hash_chain_replay.py` | ✅ pass (10/10 — tamper detection, canonical JSON, two-phase crash) |
| Full-suite status | ⚠ DEFERRED: full suite timed out at 1200s (~62%) and contains tests needing live provider keys (absent in the keyless build env). Config fixed (host-network pattern, 3600s, E2_HIGHCPU_8) — triage of key-dependent failures is a carried chore. |
| Harness fixes landed | Cloud Build reserved-socket + sibling-port networking (`--network=host` docker step); `env.py` loop-aware alembic runner |

### Post-review test cycle (13-REVIEW, same day)

The mandatory code-review gate found **CR-01**: the worker's queue path never
dispatched (post-lock re-check re-tested the pre-claim claimable set and refused its own
fresh claim). Undetected because (a) all three live proof runs used the smoke script's
direct-pipeline path, and (b) the "green" critical build had silently **SKIPPED** the 7
live-DB tests (testcontainers could not start inside the host-network step) — the earlier
"24 green" reading in this file's first draft was wrong and is corrected here.

Fix cycle (all committed):
- Ownership → **fencing-token claim consume** (`_CONSUME_CLAIM_SQL`: bump `started_at`
  iff it equals the claim's token, under the advisory lock) — a claim dispatches at most
  once, ever. Duplicate invocations, stolen claims, and superseded self-reclaims all
  refuse deterministically.
- `WORKER_ID` made globally unique (hostname-pid collides across Cloud Run instances —
  live logs showed `localhost-1`).
- Live tests rewritten to model claim-then-lock with the real patch target; new CR-01
  regression + stolen-claim tests.
- Working harness: dedicated host-network Postgres + `DATABASE_URL` + pre-created
  `worker_user`/`app_user` roles + login-role `search_path` (committed as
  `tribunal/cloudbuild.test-critical.yaml`).

**Final gate: 22/22 PASSED** (schema isolation 5, advisory lock 8 incl. all live races,
hash-chain replay 10) — build green 2026-07-20. `test_rls_isolation.py` excluded from
this gate: the harness connects as a Postgres superuser and RLS never applies to
superusers (v1.0 lesson); faithful re-run needs a non-superuser DSN harness → carried
into the full-suite triage chore.

Services redeployed on tag `20260720-fix2` with the corrected worker (see below).

## LUKOIL benchmark E2E proof run (Task 2 — ENGINE-02 + ENGINE-04)

> Single real run via `run_tribunal_smoke.py --brief "<LUKOIL COMBINED_BRIEF>"` (or
> `NESTOR_E2E=1 pytest test_tribunal_e2e.py -x`). Guard: `DEMO_MODE` unset,
> `NESTOR_SDK_ORCHESTRATOR=tribunal`. Source brief:
> `C:\Users\ajimimo\Desktop\MOELD\Nestor\lukoil_questions.py` (COMBINED_BRIEF, D-05).

| Metric | Value |
|--------|-------|
| `run_id` | `1315ea6a-6ea0-40b0-8434-48b2e8a74133` (job execution `tribunal-smoke-4rgwv`, exit 0) |
| `tenant_id` / `project_id` | ephemeral self-provisioned "Tribunal Smoke" org (IDs in job logs) |
| Elapsed seconds (wall-clock, max run length) | **1020s pipeline / ~1072s job wall-clock** (15:28:27Z → 15:46:19Z incl. start) — feeds Phase 16 stale calibration |
| `cost_usd` (sum) | **$1.9696** (UNCAPPED=1; recorded not enforced, D-07) |
| Total claims | 115 (dropped 4, survivors 115) |
| Grounded claims / `claim_source` count | 112 |
| Recall % | **97.4%** |
| **`verify_chain` result** | ✅ **OK** — chain intact on the re-homed deployment (ENGINE-04 LEGAL GATE GREEN) |
| Quality gates | quality_gate PASS · coverage_gate PASS · reentry_count 0 · budget_marker '' |
| Non-fatal warnings | 3× group-skeptic parse errors (`'str' object has no attribute 'get'`); malformed `FOCUS_AREA` intake lines forced one coverage retry (recovered) — engine-quality items, not re-home defects |

## Concurrency proof (Task 3 — ENGINE-08 / D-08)

> ≥2 runs triggered SIMULTANEOUSLY from DIFFERENT `tenant_id`s (two smoke invocations with
> distinct `--tenant-id`, or two `POST /api/runs`). Required gate is ≥2; push toward ~5 to
> validate the D-08 target. Both must complete with `verify_chain` OK and no forked chain /
> double-run (advisory lock + claimable-set guard held).

| Run | tenant_id | run_id | verify_chain | double-ran / forked? |
|-----|-----------|--------|--------------|----------------------|
| A (`tribunal-smoke-drbbj`) | `5b0b574f-191f-4676-8dd2-1f2b6ab87733` | `0830d8b5-f9a5-457e-9c08-a147b83ca4c2` | ✅ OK | no (913s, $1.48, recall 96.3%) |
| B (`tribunal-smoke-sws55`) | `260563e6-6cc9-4dfe-8095-cdf8bbe0727f` | `5d919ab3-aca3-4815-92dc-283d2d24fef9` | ✅ OK | no (968s, $2.10, recall 96.9%) |

Both executions fully overlapped (15:47:36Z → 16:04:27Z wall-clock window).

Concurrency verdict: ✅ **GREEN — ENGINE-08 closed.** Two simultaneous runs from two
different spaces completed without interference, both audit chains intact. The advisory
lock's exactly-once property is additionally proven by
`test_advisory_lock_exactly_once.py` (two racing executors on real Postgres, Cloud Build
green this session); worker deploys at `max-instances=5` toward the D-08 5+ target.

## Teardown (Task 3 tail — Step 13.i, D-02) — STRICTLY AFTER the proofs are green

> **DEFERRED (operator decision 2026-07-20).** All proof gates were green and the teardown
> was offered; the operator chose "Not now". The old-build resources remain in place as a
> carried chore. Reminder of the exact scope when it is picked up (resource-level ONLY —
> single-project reality means NEVER delete the project):
> `nestor-pulse-api` + `nestor-pulse-worker` services, STOPPED `nestor-prod-pg` SQL
> instance (irreversible), `nestor-pulse` AR repo. Out of the runbook list and untouched
> either way: `nestor-pulse-pdf-extractor` (decide then), `nestor-audit-prod` bucket
> (retention-managed audit evidence — keep).

| Action | Done? |
|--------|-------|
| `nestor-pulse-api` (old) deleted | DEFERRED |
| `nestor-pulse-worker` (old) deleted | DEFERRED |
| `nestor-prod-pg` Cloud SQL instance (old) deleted | DEFERRED (instance remains STOPPED) |
| `nestor-pulse` Artifact Registry repo (old) deleted | DEFERRED |
| Intake `tribunal-api` `/readyz` still 200 post-teardown | n/a until teardown |
| Legacy Supabase project | UNTOUCHED (independence, never deleted) |
