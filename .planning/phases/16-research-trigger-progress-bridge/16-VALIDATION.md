---
phase: 16
slug: research-trigger-progress-bridge
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-21
---

# Phase 16 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (intake backend, sync pg8000 harness); Tribunal keeps its own asyncpg suite (two-suite pattern, 14-CONTEXT D-08) |
| **Config file** | `backend/` pytest config (existing 150-test suite); `tribunal/cloudbuild.test-critical.yaml` (Tribunal critical gate) |
| **Quick run command** | `pytest backend/tests/test_research_routes.py -x` (runs in Cloud Build — dev box has no Python) |
| **Full suite command** | Cloud Build intake full suite (`cloudbuild.test.yaml`) + `tribunal/cloudbuild.test-critical.yaml` |
| **Estimated runtime** | ~10 min (Cloud Build round-trip per suite) |

---

## Sampling Rate

- **After every task commit:** targeted `pytest backend/tests/test_research_routes.py -x` (author-by-construction locally; run in Cloud Build)
- **After every plan wave:** intake full suite + Tribunal critical gate (the two-suite gate)
- **Before `/gsd:verify-work`:** full suite green in Cloud Build; FIRST live seam trigger closes the deferred Phase-14 HTTP UAT (record in `14-HUMAN-UAT.md`)
- **Max feedback latency:** ~600 seconds (Cloud Build)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 16-01-T2 | 16-01 | 1 | ENGINE-03 | T-16-01/02 | Migration 0011 creates `research_runs` + both RLS policies + 3 indexes | migration test | `pytest backend/tests/test_research_runs_migration.py -x` | ✅ 16-01 T2 | ⬜ pending |
| 16-01-T3 | 16-01 | 1 | (infra) | — | `fake_tribunal_client` fixture exists (no test hits the real API) | fixture | `pytest backend/tests/ -k research -x` (collection) | ✅ 16-01 T3 | ⬜ pending |
| 16-02-T1 | 16-02 | 2 | SEAM-04 | T-16-04 | Assembled brief has NO `[INTERACTIVE_REPORT]` + enumerated questions | unit | `pytest backend/tests/test_research_brief.py::test_brief_never_opts_into_gates -x` | ✅ 16-02 T1 | ⬜ pending |
| 16-02-T2 | 16-02 | 2 | ENGINE-07 | T-16-06 | Poll driver holds no DB connection across CALL phase (`checkedout()==0`) | integration | `pytest backend/tests/test_research_run_task.py::test_poll_driver_releases_pool -x` | ✅ 16-02 T2 | ⬜ pending |
| 16-02-T2b | 16-02 | 2 | RUN-02 | — | On terminal, mail sent to acting superadmin; on_error finalizes row `failed` | unit | `pytest backend/tests/test_research_run_task.py -x` | ✅ 16-02 T2 | ⬜ pending |
| 16-02-T3 | 16-02 | 2 | RUN-02 | T-16-05 | Completion/failure templates render short+link; autoescape ON | unit | `pytest backend/tests/ -k research_complete -x` | ✅ 16-02 T3 | ⬜ pending |
| 16-03-T1 | 16-03 | 3 | SEAM-03 | — | Trigger flips `decomposed`→`in_research`, inserts run, schedules driver, 202 | unit+integration | `pytest backend/tests/test_research_routes.py::test_trigger_decomposed_ok -x` | ✅ 16-03 T1 | ⬜ pending |
| 16-03-T1b | 16-03 | 3 | SEAM-03 | — | Trigger on non-`decomposed` → 409 | unit | `pytest backend/tests/test_research_routes.py::test_trigger_wrong_status_409 -x` | ✅ 16-03 T1 | ⬜ pending |
| 16-03-T1c | 16-03 | 3 | SEAM-03/D-04 | — | 4th trigger attempt → needs-investigation (no seam call) | unit | `pytest backend/tests/test_research_routes.py::test_attempt_cap_3 -x` | ✅ 16-03 T3 | ⬜ pending |
| 16-03-T2 | 16-03 | 3 | RUN-01 | T-16-14 | SSE emits frames; closes on `{completed,failed,cancelled}` (dynamic stages) | integration | `pytest backend/tests/test_research_routes.py::test_research_stream_terminal_set -x` | ✅ 16-03 T2 | ⬜ pending |
| 16-03-T3 | 16-03 | 3 | SEAM-03/RUN-01 | T-16-08 | Cross-tenant trigger + SSE → existence-hidden 404; null-space → 403 | denial | `pytest backend/tests/test_research_cross_tenant.py -x` | ✅ 16-03 T3 | ⬜ pending |
| 16-03-T3b | 16-03 | 3 | RUN-02 | — | Completion mail recipient == acting superadmin (fake_resend) | unit | `pytest backend/tests/test_research_routes.py::test_completion_mail_to_trigger_user -x` | ✅ 16-03 T3 | ⬜ pending |
| 16-04-T1 | 16-04 | 3 | RUN-01 | T-16-13 | research.ts trigger + SSE reader typecheck clean (research terminal set) | typecheck | `cd frontend && npx tsc --noEmit` | ✅ 16-04 T1 | ⬜ pending |
| 16-04-T2 | 16-04 | 3 | RUN-01 | T-16-14 | Progress panel renders stage list dynamically (no hardcoded count) | typecheck+UAT | `cd frontend && npx tsc --noEmit` | ✅ 16-04 T2 | ⬜ pending |
| 16-04-T3 | 16-04 | 3 | SEAM-03/D-08 | T-16-12 | Confirm-dialog trigger; additive derivePhase; NO client research surface | typecheck+UAT | `cd frontend && npx tsc --noEmit` | ✅ 16-04 T3 | ⬜ pending |
| 16-05-live | 16-05 | 4 | ENGINE-03/SEAM-03/RUN-01/RUN-02 | T-16-15/16/18 | Live run: trigger→dynamic panel→completed→email; stale window=90; closes 14-UAT | manual UAT | operator live session (16-HUMAN-UAT.md) | ✅ 16-05 T2 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave 0 test infrastructure is folded into the plans (author-by-construction; no separate scaffold plan):

- [x] Plan 16-01 T3 — `backend/tests/conftest.py` `fake_tribunal_client` fixture (mirror `fake_resend`)
- [x] Plan 16-01 T2 — migration-apply test for `research_runs` (+ RLS policy)
- [x] Plan 16-02 T1/T2 — `backend/tests/test_research_brief.py` + `test_research_run_task.py` (pool-safety, terminal mail, on_error finalize-as-failed)
- [x] Plan 16-03 T1-T3 — `backend/tests/test_research_routes.py` (trigger + SSE + attempt-cap + mail) + `test_research_cross_tenant.py` (denial suite extension)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| First live intake-originated seam trigger (closes Phase-14 deferred HTTP UAT) | SEAM-03 | Real Cloud Run + real Tribunal run costs money; operator live session | Runbook § Phase 16: trigger on a decomposed smoke intake, watch progress panel, verify run completes + email arrives; record in `14-HUMAN-UAT.md` + `16-HUMAN-UAT.md` |
| Progress panel visual (intake design language, dynamic stage list) | RUN-01 | Visual/UAT judgment | Open intake detail during a live run; stages render from trace, cost ticks |
| Stale-window setting live (`NESTOR_WORKER_STALE_MINUTES=90`) | ENGINE-03 | Deploy-env change, verified by inspection | Runbook step 16.d; `gcloud run services describe tribunal-worker` shows the env |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (backend tasks are TDD/author-by-construction; live UAT is operator-gated)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (folded into 16-01/16-02/16-03)
- [x] No watch-mode flags
- [x] Feedback latency < 600s (Cloud Build)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned 2026-07-21
