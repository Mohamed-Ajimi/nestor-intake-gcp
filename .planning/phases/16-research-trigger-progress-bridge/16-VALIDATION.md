---
phase: 16
slug: research-trigger-progress-bridge
status: draft
nyquist_compliant: false
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
| TBD | TBD | TBD | SEAM-03 | — | Trigger flips `decomposed`→`in_research`, assembles brief, calls seam | unit+integration | `pytest backend/tests/test_research_routes.py::test_trigger_decomposed_ok -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEAM-03 | — | Trigger on non-`decomposed` → 409 | unit | `...::test_trigger_wrong_status_409 -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEAM-03 | cross-tenant ID | Cross-tenant trigger → existence-hidden 404 | denial | `...::test_trigger_cross_tenant_404 -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | SEAM-04 | stray marker | Assembled brief contains NO `[INTERACTIVE_REPORT]` + enumerated questions | unit | `...::test_brief_never_opts_into_gates -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RUN-01 | — | SSE emits research-run frames; closes on `{completed,failed,cancelled}` | integration | `...::test_research_stream_terminal_set -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RUN-01 | cross-tenant ID | Cross-tenant SSE pre-flight → 404; null-space → 403 | denial | `...::test_research_stream_denial -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | RUN-02 | — | Terminal state mails the acting superadmin (fake_resend asserts recipient) | unit | `...::test_completion_mail_to_trigger_user -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | D-04 | — | 4th trigger attempt → "needs investigation" (no seam call) | unit | `...::test_attempt_cap_3 -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENGINE-07/RUN-01 | pool exhaustion | Poll driver holds no DB connection across CALL phase | integration | `...::test_poll_driver_releases_pool -x` | ❌ W0 | ⬜ pending |
| TBD | TBD | TBD | ENGINE-03 | — | Migration creates `research_runs` + RLS policy | migration test | existing migration-apply harness | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*(Planner fills Task ID / Plan / Wave columns when PLAN.md files are created.)*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_research_routes.py` — trigger + SSE + denial + attempt-cap tests (fake seam client + fake_resend)
- [ ] `backend/tests/test_research_run_task.py` — poll driver pool-safety + terminal mail + on_error finalize-as-failed
- [ ] `backend/tests/conftest.py` (extend) — `fake_tribunal_client` fixture (mirror `fake_anthropic`/`fake_gcs`/`fake_resend`)
- [ ] Migration-apply test for the `research_runs` migration (+ RLS policy) in the existing migration harness
- [ ] Cross-tenant denial suite (intake pg8000 side) extended with `research_runs` cases

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| First live intake-originated seam trigger (closes Phase-14 deferred HTTP UAT) | SEAM-03 | Real Cloud Run + real Tribunal run costs money; operator live session | Runbook: trigger on a decomposed smoke intake, watch progress panel, verify run completes + email arrives; record in `14-HUMAN-UAT.md` |
| Progress panel visual (intake design language, dynamic stage list) | RUN-01 | Visual/UAT judgment | Open intake detail during a live run; stages render from trace, cost ticks |
| Stale-window setting live (`NESTOR_WORKER_STALE_MINUTES=90`) | ENGINE-03 | Deploy-env change, verified by inspection | Runbook step; `gcloud run services describe tribunal-worker` shows the env |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 600s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
