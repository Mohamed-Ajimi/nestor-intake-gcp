---
phase: 13-tribunal-re-home-infra-baseline
verified: 2026-07-20T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Worker stale-reclaim window is calibrated so that a run exceeding STALE_RUN_MINUTES never gets double-dispatched (WR-01 residual)"
    addressed_in: "Phase 16"
    evidence: "Phase 16 success criteria: 'the stale-run reclaim window is set above the real max run length (no double-runs)'; 13-04-SUMMARY addendum explicitly names WR-01 -> Phase 16 stale-window calibration"
  - truth: "Full Tribunal test suite (all 160+ tests including key-dependent provider tests) passes green in Cloud Build"
    addressed_in: "Phase 16 (as a chore)"
    evidence: "13-04-SUMMARY known deferrals: 'Full Tribunal suite triage (key-dependent tests fail in keyless build env; config mechanism fixed, timeout 3600s)' — carried chore; Phase 16 stale-calibration context expects full-suite re-run"
  - truth: "Tribunal services run under a dedicated, least-privilege tribunal-run service account (not the shared intake runtime SA)"
    addressed_in: "Phase 14"
    evidence: "13-04-SUMMARY addendum: 'WR-03 (SA separation) → Phase 14'; Phase 14 goal: 'only the intake backend can call it (server-to-server internal auth)'"
  - truth: "audit_log UPDATE/DELETE grants are removed from worker_user (write-once chain enforcement)"
    addressed_in: "Phase 15"
    evidence: "13-04-SUMMARY addendum: 'WR-05 (audit_log UPDATE/DELETE grants) → Phase 15'"
  - truth: "D-02 teardown: old nestor-pulse-api, nestor-pulse-worker, nestor-prod-pg SQL instance, and nestor-pulse Artifact Registry repo deleted"
    addressed_in: "Phase 16 (carried chore)"
    evidence: "13-PROOF-RESULTS.md Teardown section: 'DEFERRED (operator decision 2026-07-20) … recorded as carried chore'; not a phase goal gate item"
human_verification:
  - test: "Confirm tribunal-api /health returns 200 with {status: ok} and /readyz returns 200 with {db: ok} on the current live revision (tag 20260720-fix2)"
    expected: "Both endpoints return 200; /readyz shows db:ok — confirming the DB search_path fix and socket attachment are still live"
    why_human: "Requires hitting the live Cloud Run endpoint; cannot verify programmatically without credentials"
  - test: "Confirm the worker queue path actually dispatches a run by enqueuing via POST /api/runs (not via run_tribunal_smoke.py direct-pipeline path) and observing it complete with verify_chain=OK"
    expected: "A run submitted through the real queue path (claim_one → execute_run_locked → execute_run) completes and verify_chain returns green — proving the CR-01 fencing-token fix works end-to-end on the live deployment (tag 20260720-fix2)"
    why_human: "The three original proof runs all used run_tribunal_smoke.py direct-pipeline bypass; no recorded live proof of the queue path on the fixed revision; cannot verify without a live session"
  - test: "Check tribunal.tribunal_alembic_version = 0010 in the live database and confirm tribunal schema has 10+ tables with zero leak into public"
    expected: "SELECT version_num FROM tribunal.tribunal_alembic_version returns 0010; \\dt tribunal.* lists run, audit_log, claim, output, etc.; SELECT * FROM public.alembic_version returns only the intake migration head (not any tribunal migration)"
    why_human: "Requires live Cloud SQL access (psql or Cloud Run job); cannot read the DB from the dev machine"
---

# Phase 13: Tribunal Re-home + Infra Baseline Verification Report

**Phase Goal:** Tribunal runs live in the intake GCP project with correctly isolated schema/migrations, its legally required audit chain verified intact, concurrency-safe locking in place, and one real research run proven end-to-end green — before any feature code depends on it.
**Verified:** 2026-07-20
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | tribunal-api + tribunal-worker run in the intake GCP project; tribunal schema migrated via its own tribunal_alembic_version (no revision-ID collision) | VERIFIED | 13-PROOF-RESULTS.md records both services live on tag 20260720-fix2, tribunal.tribunal_alembic_version=0010, 10 tables in tribunal, zero public leak; code: env.py has `tribunal_alembic_version` + `search_path TO tribunal`; 0008 has zero `SCHEMA public` literals |
| SC-2 | verify_chain returns green against the re-homed audit hash-chain (ENGINE-04 legal gate, before 2026-08-02) | VERIFIED | 13-PROOF-RESULTS.md: LUKOIL run 1315ea6a verify_chain=OK; two concurrent runs (0830d8b5, 5d919ab3) both chain=OK; hash_chain.py present byte-identical with tenant_id payload |
| SC-3 | Two simultaneous runs from different spaces complete without interfering — per-run advisory lock proven by ≥2-concurrent-run test | VERIFIED | 13-PROOF-RESULTS.md concurrency section: runs A + B from distinct tenants (5b0b574f, 260563e6) fully overlapped, both chain=OK, no double-run; execute.py has pg_advisory_xact_lock with bit(64)::bigint, no hashtext; CR-01 fencing-token fix deployed on tag 20260720-fix2; 22/22 critical Cloud Build gate green (including racing-executor live tests) |
| SC-4 | One real research run completes end-to-end green; measured max length recorded for stale-run calibration | VERIFIED | LUKOIL E2E: 115 claims, 97.4% recall, $1.9696, 1020s pipeline, verify_chain=OK; 13-PROOF-RESULTS.md records all values for Phase 16 calibration |

**Score:** 4/4 truths verified

---

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Worker stale-reclaim window calibrated so ultra-long runs (> STALE_RUN_MINUTES) cannot be double-dispatched (WR-01 residual) | Phase 16 | Phase 16 SC-5: "stale-run reclaim window is set above the real max run length (no double-runs)"; 13-04-SUMMARY addendum explicitly maps WR-01 → Phase 16 |
| 2 | Full Tribunal test suite (key-dependent tests) passes green in Cloud Build | Phase 16 (chore) | 13-04-SUMMARY known deferrals: key-dependent tests need live provider keys, absent in the keyless build env; config fixed; triage is a carried chore |
| 3 | Tribunal services run under a dedicated tribunal-run SA (not shared intake SA) | Phase 14 | 13-04-SUMMARY addendum: WR-03 (SA separation) → Phase 14 |
| 4 | audit_log UPDATE/DELETE grants removed from worker_user | Phase 15 | 13-04-SUMMARY addendum: WR-05 (audit_log grants) → Phase 15 |
| 5 | D-02 teardown of old nestor-pulse-* resources | Phase 16 (chore) | 13-PROOF-RESULTS.md: "DEFERRED (operator decision 2026-07-20)" — operator chose "Not now" after proofs passed |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tribunal/nestor_pulse_sdk/audit/hash_chain.py` | Frozen tamper-evident audit hash-chain with tenant_id payload | VERIFIED | EXISTS; grep confirms `tenant_id` present |
| `tribunal/nestor_pulse/secrets.py` | Sole cross-package dependency with load_secrets_into_env | VERIFIED | EXISTS; grep confirms `def load_secrets_into_env` |
| `tribunal/requirements.txt` | Pinned Py 3.11.9 deps: asyncpg==0.31.0 + anthropic==0.104.1 | VERIFIED | EXISTS; both pins confirmed |
| `tribunal/.gcloudignore` | Excludes __pycache__/.venv/.pytest_cache from Cloud Build context | VERIFIED | EXISTS; grep confirms `__pycache__` present |
| `tribunal/nestor_pulse_sdk/alembic/env.py` | tribunal_alembic_version + search_path=tribunal in BOTH configure paths | VERIFIED | EXISTS; grep confirms both keys; also has `_include_object` filter (WR-04 fix) |
| `tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py` | Zero SCHEMA public literals; SCHEMA tribunal present | VERIFIED | grep -c SCHEMA public = 0; SCHEMA tribunal present |
| `tribunal/nestor_pulse_sdk/db/models/run.py` | ck_run_status CHECK includes needs_report_spec | VERIFIED | EXISTS; grep confirms needs_report_spec |
| `tribunal/nestor_pulse_sdk/runs/execute.py` | pg_advisory_xact_lock with bit(64)::bigint; no hashtext; CR-01 fencing-token | VERIFIED | EXISTS; all three greps pass; _CONSUME_CLAIM_SQL fencing-token present |
| `tribunal/nestor_pulse_sdk/tests/test_schema_isolation.py` | Schema isolation test | VERIFIED | EXISTS; def test_ present |
| `tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py` | Exactly-once concurrency test | VERIFIED | EXISTS; def test_ present |
| `infra/DEPLOY-RUNBOOK.md` | Phase 13 section with deploy + teardown steps | VERIFIED | EXISTS; Phase 13, teardown, project-cb01b861, tribunal-migrate all present |
| `tribunal/cloudbuild.worker.yaml` | Cloud Build config for tribunal-worker image | VERIFIED | EXISTS; tribunal-worker present |
| `tribunal/cloudbuild.api.yaml` | Cloud Build config for tribunal-api image | VERIFIED | EXISTS |
| `tribunal/cloudbuild.test.yaml` | Test gate: pytest against Postgres container | VERIFIED | EXISTS |
| `tribunal/cloudbuild.test-critical.yaml` | Post-review critical subset gate (22/22) | VERIFIED | EXISTS (created as part of CR-01 fix cycle) |
| `infra/main.tf` | By-construction IaC: tribunal-worker (min=1, max=5, cpu_idle=false), tribunal-api, tribunal-migrate Job, audit bucket (7y Unlocked), 6 secrets, 2 BUILT_IN DB roles | VERIFIED | All key patterns confirmed; CR-02 lifecycle ignore_changes present; CR-03 volumes + correct migrate cmd present |
| `tribunal/infrastructure/cloud-run/deploy-worker.sh` | Retargeted to $GOOGLE_PROJECT; max-instances=5; no project-cb01b861 | VERIFIED | No old project refs; max-instances=5 present |
| `tribunal/infrastructure/cloud-run/api/Dockerfile` | Includes COPY nestor_pulse (Plan 03 deviation fix) | VERIFIED | Both COPY nestor_pulse_sdk and COPY nestor_pulse present |
| `.planning/phases/13-tribunal-re-home-infra-baseline/13-PROOF-RESULTS.md` | Proof-run duration + cost + verify_chain + concurrency result recorded | VERIFIED | EXISTS; 1020s, $1.9696, verify_chain=OK, 2x concurrent runs recorded |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| tribunal/nestor_pulse_sdk/runs/worker.py | tribunal/nestor_pulse_sdk/runs/execute.py | worker_loop calls execute_run_locked (import from runs.execute) | VERIFIED | grep confirms `from nestor_pulse_sdk.runs.execute import execute_run_locked` at line 277; worker_loop calls it at line 297 |
| tribunal/nestor_pulse_sdk/alembic/env.py | tribunal schema | search_path TO tribunal before run_migrations; CREATE SCHEMA IF NOT EXISTS tribunal | VERIFIED | Both literals present; `_include_object` filter also prevents cross-schema autogenerate drops (WR-04 fix) |
| tribunal/nestor_pulse_sdk/secrets_bootstrap.py | tribunal/nestor_pulse/secrets.py | from nestor_pulse.secrets import load_secrets_into_env | VERIFIED (via SUMMARY 01) | Confirmed in 13-01-SUMMARY; the only nestor_pulse.* cross-dep on the engine boot path |
| infra/main.tf tribunal-worker | DATABASE_URL_WORKER secret | secret_key_ref to tribunal_database_url_worker | VERIFIED | grep confirms DATABASE_URL_WORKER present in main.tf |
| infra/main.tf tribunal_worker/api/migrate | Cloud SQL socket | volumes { cloud_sql_instance { ... } } + volume_mounts (CR-03 fix) | VERIFIED | Lines 970-985 in main.tf; migrate job lines 1206-1225; proven-live alembic cmd in migrate args |
| infra/main.tf tribunal DB users | lifecycle { ignore_changes = [password] } | CR-02 fix: prevents password rotation on import/apply | VERIFIED | Lines 793-795, 808-810 in main.tf |

---

### Data-Flow Trace (Level 4)

Not applicable to this phase. Phase 13 produces infrastructure/engine artifacts (Cloud Run services, Terraform IaC, Python engine), not React/frontend components that render dynamic data from a store. The "data flow" proof is the live E2E run recorded in 13-PROOF-RESULTS.md — the engine received a real brief, produced 115 claims with verify_chain=OK, and the results are recorded.

---

### Behavioral Spot-Checks (Step 7b)

The dev machine has no Python/Docker and cannot reach the live GCP project without credentials. Static source checks were used throughout as the established verification mode for this project.

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| advisory lock uses 64-bit key (not int4 hashtext) | `grep -q "bit(64)::bigint" tribunal/nestor_pulse_sdk/runs/execute.py` + `grep -c hashtext ... == 0` | Both pass | PASS |
| 0008 migration grants target tribunal schema only | `grep -c "SCHEMA public" 0008... == 0` | 0 occurrences | PASS |
| env.py writes isolated version table | `grep -q "tribunal_alembic_version" alembic/env.py` | Present in both configure paths | PASS |
| deploy-worker.sh retargeted (no old project refs, max=5) | `grep -c project-cb01b861 deploy-worker.sh == 0` + `grep -q max-instances=5` | Both pass | PASS |
| CR-01 fencing-token fix in execute.py | `grep -q "_CONSUME_CLAIM_SQL\|fencing" execute.py` | Present | PASS |
| Live verify_chain on re-homed deployment | Operator-recorded in 13-PROOF-RESULTS.md | chain=OK on 3 real runs | PASS (operator-recorded) |
| 22/22 critical Cloud Build gate (post-review) | cloudbuild.test-critical.yaml — operator-run | 22/22 green 2026-07-20 | PASS (operator-recorded) |
| Queue path dispatch (CR-01 regression test) | `test -f tribunal/cloudbuild.test-critical.yaml` | EXISTS | PASS (file exists; runtime result operator-recorded) |

---

### Probe Execution (Step 7c)

No conventional `scripts/*/tests/probe-*.sh` probes exist in this phase. The phase used a `run_tribunal_smoke.py` E2E vehicle and `cloudbuild.test-critical.yaml` as the suite gate. Both were operator-run during the live session and results are recorded in 13-PROOF-RESULTS.md. The verifier cannot re-execute them (no Python/Docker on dev machine, no live GCP credentials).

| Probe | Command | Result | Status |
|-------|---------|--------|--------|
| LUKOIL E2E smoke run | `run_tribunal_smoke.py --brief "<LUKOIL>"` (Cloud Run job) | exit 0, chain=OK, 1020s, $1.97 | PASS (operator-recorded 2026-07-20) |
| Critical test gate | `gcloud builds submit --config tribunal/cloudbuild.test-critical.yaml` | 22/22 passed | PASS (operator-recorded 2026-07-20) |
| Concurrent runs proof | 2x smoke with distinct --tenant-id | Both chain=OK, no interference | PASS (operator-recorded 2026-07-20) |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| ENGINE-01 | 13-01, 13-02, 13-03, 13-04 | tribunal-api + worker as Cloud Run services; tribunal schema; own Alembic migration line | SATISFIED | Services live (13-PROOF-RESULTS.md); env.py isolation verified in source; 0008 rewrite confirmed; IaC in main.tf |
| ENGINE-02 | 13-04 | One real run completes end-to-end green; duration recorded | SATISFIED | LUKOIL run 1315ea6a: 115 claims, 97.4% recall, $1.9696, 1020s, verify_chain=OK; values in 13-PROOF-RESULTS.md |
| ENGINE-04 | 13-01, 13-02, 13-04 | verify_chain green after re-home (EU AI Act Art. 12 gate) | SATISFIED | 3 real runs with chain=OK; hash_chain.py byte-identical with tenant_id payload; audit bucket with 7y Unlocked retention |
| ENGINE-08 | 13-02, 13-03, 13-04 | ≥2 concurrent runs from different spaces without interference; advisory lock proven | SATISFIED | 2 fully-overlapped runs, distinct tenants, both chain=OK; 22/22 Cloud Build gate green (including racing-executor live tests + CR-01 regression); execute.py 64-bit lock + fencing token |

All 4 requirements mapped to Phase 13 in REQUIREMENTS.md are covered. No orphaned requirements.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tribunal/nestor_pulse_sdk/db/base.py` | ~51 | `search_path=tribunal,public` — public fallback can mask a missing-migration state in production | Info (WR-05 from review, IN-05) | Low: serves testcontainers; mitigated by mandatory migration gate before deploy |
| `tribunal/infrastructure/cloud-run/deploy-api.sh` | ~37 | `IMAGE_TAG="${IMAGE_TAG:-latest}"` — defaults to mutable latest tag | Info (IN-02) | Low: runbook passes the explicit tag; operators who use scripts directly without $IMAGE_TAG get a non-reproducible deploy |
| `infra/variables.tf` | ~315 | Generic secret names `DATABASE_URL`, `DATABASE_URL_WORKER` in the shared project namespace | Info (IN-03) | Low: no collision today; future services could grab the wrong secret; renaming deferred |
| `tribunal/infrastructure/cloud-run/api/Dockerfile` | ~28 | Containers run as root; tests/ and scripts/ included in production image | Info (IN-04) | Low: Cloud Run sandbox mitigates; image hardening deferred |
| `infra/variables.tf` | ~274 | `tribunal_image_tag` defaults to `""` — composes invalid image refs on a naive apply | Info (IN-06) | Low: IaC is drift-inert (terraform apply blocked); not an execution risk today |

No TBD, FIXME, or XXX debt markers found in phase-authored files. No unreferenced debt markers constitute a blocker.

**WR-01 status (not an anti-pattern, deferred):** The advisory lock is transaction-scoped and released before the ~17-minute pipeline runs. A run exceeding STALE_RUN_MINUTES (60 min) could theoretically be re-claimed. The proof's longest run was 17 min vs. the 60-min stale window (3.5x margin); this is acceptable for Phase 13 and is explicitly tracked for Phase 16 calibration. The stale window observation is a WARNING-class finding, not a BLOCKER for this phase's goals.

---

### Human Verification Required

All four ROADMAP success criteria are verified by code + operator-recorded live evidence. The following items need human spot-checks before Phase 14 begins, to confirm the live deployment is still healthy and the queue path works on the fixed revision.

#### 1. Live service health on fixed revision (tag 20260720-fix2)

**Test:** `curl https://<tribunal-api-url>/health` and `curl https://<tribunal-api-url>/readyz` on the current live revision
**Expected:** Both return 200; /readyz returns `{"status":"ready","db":"ok"}` — confirming DB search_path fix and Cloud SQL socket attachment are live on the post-review revision
**Why human:** Requires live endpoint access with GCP credentials; the verifier cannot reach the Cloud Run service

#### 2. Queue-path dispatch verification on the fixed revision

**Test:** POST a run to `/api/runs` (the real queue path, not run_tribunal_smoke.py), observe the worker claim it via `claim_one`, run `execute_run_locked`, and confirm the run reaches a terminal state with verify_chain=OK
**Expected:** A queued run is dispatched exactly once through the real worker loop on tag 20260720-fix2 (the CR-01 fix), producing chain=OK
**Why human:** All three original proof runs (LUKOIL + 2 concurrent) used run_tribunal_smoke.py which bypasses worker_loop entirely; no recorded live proof exists of the queue path on the fixed revision; the 22/22 Cloud Build gate proves correctness on a test DB, but a live production-path smoke is prudent before Phase 14 depends on this

#### 3. Database schema validation (live)

**Test:** `\dt tribunal.*` via psql/Cloud SQL proxy; `SELECT version_num FROM tribunal.tribunal_alembic_version`; `SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name LIKE '%alembic%'`
**Expected:** tribunal schema has 10+ tables; tribunal_alembic_version = 0010; no tribunal migrations leaked into public.alembic_version
**Why human:** Requires live database access; dev machine cannot connect to Cloud SQL directly

---

### Gaps Summary

No must-have ROADMAP success criteria failed. All four SC-1 through SC-4 are VERIFIED by code artifacts and operator-recorded live evidence. The human verification items are prudent operational checks before Phase 14 begins, not blockers against the phase goal itself.

The post-review fix cycle (CR-01/02/03/WR-04) was fully executed and committed: the CR-01 fencing-token logic is in execute.py and worker.py; CR-02 lifecycle guards are in main.tf; CR-03 Cloud SQL volume blocks and correct migrate command are in main.tf; WR-04 `_include_object` filter is in env.py. The 22/22 Cloud Build critical gate was run after the fixes and is green per operator record.

The five deferred items (WR-01 stale window, WR-03 SA separation, WR-05 audit_log grants, full-suite triage, D-02 teardown) all have explicit later-phase assignments confirmed in the ROADMAP and are not actionable gaps for this phase.

---

_Verified: 2026-07-20_
_Verifier: Claude (gsd-verifier)_
