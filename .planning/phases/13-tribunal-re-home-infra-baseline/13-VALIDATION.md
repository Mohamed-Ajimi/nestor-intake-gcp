---
phase: 13
slug: tribunal-re-home-infra-baseline
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-20
---

# Phase 13 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (Tribunal's own suite in `tribunal/nestor_pulse_sdk/tests/` after copy; Python 3.11.9 image) |
| **Config file** | carried with copied code (`tribunal/pyproject.toml`) — dev machine has no Python; runs via Cloud Build |
| **Quick run command** | Author-by-construction greps (see per-task automated commands) — no local Python needed |
| **Full suite command** | `gcloud builds submit tribunal --config tribunal/cloudbuild.test.yaml` (v1.0 Cloud Build pattern), incl. the two new tests + `test_tribunal_e2e.py` |
| **Estimated runtime** | ~minutes per Cloud Build run; E2E proof run is operator-timed (duration recorded per ENGINE-02) |

---

## Sampling Rate

- **After every task commit:** Author-by-construction checks (import-graph greps, file-manifest asserts, isolation/lock source greps) — no local Python
- **After every plan wave:** Cloud Build suite run where a live session is available; otherwise deferred to the operator-run live session (Plan 04)
- **Before `/gsd:verify-work`:** `verify_chain` green + LUKOIL E2E proof run green + ≥2-concurrent-run test green
- **Max feedback latency:** minutes (Cloud Build) / operator-session for live gates

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-T1 | 13-01 | 1 | ENGINE-01, ENGINE-04 | T-13-01 | Engine copied byte-identical; frozen hash-chain carries `tenant_id` | source assert | `test -f tribunal/nestor_pulse_sdk/audit/hash_chain.py && grep -q "tenant_id" tribunal/nestor_pulse_sdk/audit/hash_chain.py && grep -q "asyncpg==0.31.0" tribunal/requirements.txt` | ✅ (source) | ⬜ pending |
| 01-T2 | 13-01 | 1 | ENGINE-01 | T-13-02, T-13-03 | Import graph has exactly one nestor_pulse cross-dep; clean build context | grep gate | `[ "$(grep -rE 'from nestor_pulse[. ]' tribunal/nestor_pulse_sdk/ \| grep -v adapter.py \| grep -v secrets_bootstrap.py \| wc -l)" -eq 0 ]` | ✅ (source) | ⬜ pending |
| 02-T1 | 13-02 | 2 | ENGINE-01 | T-13-04, T-13-05 | Isolated Alembic line (`tribunal_alembic_version` + tribunal schema); 0008 grants target tribunal | migration/integration | `grep -q "tribunal_alembic_version" tribunal/nestor_pulse_sdk/alembic/env.py && [ "$(grep -c 'SCHEMA public' tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py)" -eq 0 ]` + `pytest tribunal/nestor_pulse_sdk/tests/test_schema_isolation.py` (Cloud Build) | ❌ Wave 0 (env.py edit + test) | ⬜ pending |
| 02-T2 | 13-02 | 2 | ENGINE-08 | T-13-06, T-13-07 | Per-run 64-bit advisory lock + claimable re-check; no hashtext; no out-of-scope 01-19 machinery | concurrency | `grep -q "bit(64)::bigint" tribunal/nestor_pulse_sdk/runs/execute.py && [ "$(grep -c hashtext tribunal/nestor_pulse_sdk/runs/execute.py)" -eq 0 ]` + `pytest tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py` (Cloud Build) | ❌ Wave 0 (execute.py + test) | ⬜ pending |
| 03-T1 | 13-03 | 2 | ENGINE-01, ENGINE-04, ENGINE-08 | T-13-09, T-13-10, T-13-12 | IaC describes services/migrate-Job/audit-bucket(7y Unlocked)/roles by construction; worker_user tribunal-only | source assert | `grep -q "tribunal-worker" infra/main.tf && grep -qi "Unlocked" infra/main.tf && grep -q "worker_user" infra/main.tf && grep -q "min_instance_count = 1" infra/main.tf` | ✅ (source) | ⬜ pending |
| 03-T2 | 13-03 | 2 | ENGINE-01 | T-13-08, T-13-11 | Runbook enumerates deploy + FINAL post-proof teardown; deploy scripts retargeted; Cloud Build configs exist | source assert | `grep -q "Phase 13" infra/DEPLOY-RUNBOOK.md && test -f tribunal/cloudbuild.worker.yaml && [ "$(grep -c project-cb01b861 tribunal/infrastructure/cloud-run/deploy-worker.sh)" -eq 0 ]` | ✅ (source) | ⬜ pending |
| 04-T1 | 13-04 | 3 | ENGINE-01 | T-13-17, T-13-SC | Live deploy: secrets seeded, images built, tribunal schema migrated, both services healthy | live (operator) | Human-verify: `/healthz`+`/readyz` 200; `\dt tribunal.*`; `tribunal.tribunal_alembic_version` exists; worker polling | ✅ (live) | ⬜ pending |
| 04-T2 | 13-04 | 3 | ENGINE-02, ENGINE-04 | T-13-13, T-13-15 | Suite green (incl. 2 new tests); LUKOIL E2E proof green; verify_chain OK; duration+cost recorded | e2e (live) | `gcloud builds submit tribunal --config tribunal/cloudbuild.test.yaml` + `run_tribunal_smoke.py --brief "<LUKOIL>"` (chain=OK, cost/elapsed recorded) | ✅ (live) | ⬜ pending |
| 04-T3 | 13-04 | 3 | ENGINE-08 | T-13-14, T-13-16 | ≥2 concurrent runs from different spaces green, no forked chain; old project torn down post-proof | concurrency (live) | Human-verify: 2 smoke runs, distinct `--tenant-id`, both chain=OK; then D-02 teardown | ✅ (live) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tribunal/nestor_pulse_sdk/alembic/env.py` — add `version_table="tribunal_alembic_version"` + `version_table_schema="tribunal"` + `search_path=tribunal` (Plan 02 Task 1) — covers ENGINE-01
- [ ] `tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py` — rewrite `SCHEMA public` → `tribunal` (Plan 02 Task 1) — covers ENGINE-01 / Pitfall 2
- [ ] `tribunal/nestor_pulse_sdk/runs/execute.py` + `tests/test_advisory_lock_exactly_once.py` — the per-run advisory lock + exactly-once test (Plan 02 Task 2) — covers ENGINE-08 (KEYSTONE ONLY from plan 01-19)
- [ ] `tribunal/nestor_pulse_sdk/tests/test_schema_isolation.py` — asserts tables landed in `tribunal`, version table is `tribunal_alembic_version` (Plan 02 Task 1)
- [ ] `nestor_pulse/secrets.py` copied (Plan 01 Task 1) + import-graph grep gate (Plan 01 Task 2) — else import failure at boot
- [ ] `tribunal/cloudbuild.test.yaml` — Cloud Build test-suite config for `tribunal/` (Plan 03 Task 2; dev machine has no Python)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live deploy of tribunal-api/worker + migration job | ENGINE-01 | Dev machine has no Python/Docker; Terraform apply blocked — operator-run runbook | Plan 04 Task 1: follow `infra/DEPLOY-RUNBOOK.md` § Phase 13 |
| E2E proof run (LUKOIL benchmark brief) green + duration/cost recorded | ENGINE-02 | Real research run against live providers, operator-triggered | Plan 04 Task 2: `run_tribunal_smoke.py --brief "<LUKOIL>"`; record duration + cost |
| `verify_chain` green on re-homed deployment | ENGINE-04 | Requires live DB + GCS audit bucket | Plan 04 Task 2: smoke inline chain check / `GET /api/audit/verify/{run_id}` |
| ≥2 concurrent runs from different spaces (advisory lock) | ENGINE-08 | Requires live DB + deployed worker | Plan 04 Task 3: two smoke runs with distinct `--tenant-id`, both chain=OK |
| Old-project teardown (`project-cb01b861`) | D-02 | Destructive; strictly after proof green | Plan 04 Task 3: runbook FINAL step, operator-confirmed |

---

## Validation Sign-Off

- [x] All tasks have `<automated>`/`<human-check>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (source-grep gates on every authored task; live tasks are human-verify by necessity)
- [x] Wave 0 covers all MISSING references (env.py edit, execute.py, both new tests, cloudbuild.test.yaml)
- [x] No watch-mode flags
- [x] Feedback latency < Cloud Build cycle (~minutes)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-complete (operator sign-off at Plan 04 live session)
