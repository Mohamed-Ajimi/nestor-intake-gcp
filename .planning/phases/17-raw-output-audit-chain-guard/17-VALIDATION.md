---
phase: 17
slug: raw-output-audit-chain-guard
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-22
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend, sync pg8000 harness) + Cloud Build suites |
| **Config file** | backend/tests/conftest.py · cloudbuild.test.yaml |
| **Quick run command** | Cloud Build targeted: `gcloud builds submit --config cloudbuild.test.yaml` (subset via test path env) — no local Python |
| **Full suite command** | `gcloud builds submit --config cloudbuild.test.yaml` (full backend suite) |
| **Estimated runtime** | ~10-15 min (Cloud Build) |
| **Author-by-construction note** | Dev machine has no Python/Docker — tests are authored with the plan and run in Cloud Build at wave boundaries, not per-commit |

---

## Sampling Rate

- **After every task commit:** author-by-construction review (no local runner)
- **After every plan wave:** Cloud Build backend suite (research/bundle/denial subsets)
- **Before `/gsd:verify-work`:** Full Cloud Build suite green
- **Max feedback latency:** one Cloud Build round (~15 min)

---

## Per-Task Verification Map

*Populated by the planner — every task must map to a fake_tribunal_client/fake-GCS-backed test or an explicit Manual-Only row.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 17-01-T1 | 01 | 1 | RUN-03 | — | 0012 adds 3 nullable cols; no default; existing rows unbroken | integration | pytest backend/tests/test_research_runs_migration.py -x | extend | ⬜ pending |
| 17-01-T2 | 01 | 1 | RUN-03 | T-17-01,T-17-02 | /research-bundle returns cleaned_reports ONLY (no rejected_claims); RLS-scoped; 409 gates | integration (tribunal) | pytest tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py -x | NEW (Wave 0) | ⬜ pending |
| 17-01-T3 | 01 | 1 | RUN-03 | T-17-06 | seam get_research_bundle + verify_chain reuse _headers; SSE dict + fixture carry lock state | unit/fixture | pytest backend/tests/test_research_run_task.py -x | extend fixture | ⬜ pending |
| 17-02-T1 | 02 | 2 | RUN-03 | T-17-01 | build_bundle_zip yields D-03 layout; rejected_claims structurally absent | unit | pytest backend/tests/test_research_bundle.py -x | NEW (Wave 0) | ⬜ pending |
| 17-02-T2 | 02 | 2 | RUN-03 | T-17-05,T-17-07,T-17-08,T-17-09 | verify_chain hard gate; verified→build+upload once; broken→locked no bundle; checkedout()==0 across build | integration | pytest backend/tests/test_research_run_task.py -x | extend | ⬜ pending |
| 17-03-T1 | 03 | 3 | RUN-03 | T-17-10,T-17-11,T-17-12,T-17-14 | superadmin-only + space-scoped bundle-url/verify-chain; existence-hidden 404; build-on-download recovery | integration | pytest backend/tests/test_research_bundle_download.py -x | NEW (Wave 0) | ⬜ pending |
| 17-03-T2 | 03 | 3 | RUN-03 | T-17-10,T-17-11 | denial suite: space-B→404, user-role→404, null-space→403/404 for BOTH routes | integration (denial) | pytest backend/tests/test_research_cross_tenant.py -x | extend | ⬜ pending |
| 17-03-T3 | 03 | 3 | RUN-03 | T-17-13,T-17-15 | download/locked/re-verify UI admin-only; attachment download; return-no-throw | manual/lint | see Manual-Only (frontend has no test harness) | Manual-Only | ⬜ pending |
| 17-04-T2 | 04 | 4 | RUN-03 | T-17-16,T-17-17,T-17-18,T-17-19 | live download zip + verify_chain green + client isolation | manual (checkpoint) | see Manual-Only | Manual-Only | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Extend `backend/tests/` research fixtures: fake_tribunal_client gains synthesis-cache/verify-chain fakes; fake GCS (or monkeypatched storage module) for bundle writes/signed URLs
- [ ] Denial-suite stubs for the download + re-verify endpoints (cross-space AND client-role denial)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live bundle download from a real completed run (signed URL works in browser) | RUN-03 | Needs a real completed Tribunal run — blocked on Anthropic credits (same blocker as Phase 16 UAT) | Operator runbook session: after Phase-16 retest goes green, click download on the summary card, verify zip contents (report.md, research/*.md, sources.json) |
| verify_chain green on a real run's audit chain | RUN-03 / ENGINE-04 | Real hash-chain only exists after a live run | Same runbook session: confirm chain state shows verified; optionally tamper-test in a scratch tenant |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < one Cloud Build round
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
