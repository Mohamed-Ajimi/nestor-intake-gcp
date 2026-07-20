---
phase: 14
slug: auth-retirement-integration-seam
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-20
---

# Phase 14 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend: pg8000 sync harness; tribunal: asyncpg native harness — D-08, no driver mixing) |
| **Config file** | `backend/pyproject.toml` (pytest config) / `tribunal/nestor_pulse_sdk/tests/` conftest |
| **Quick run command** | Per-task `<automated>` structural checks (Python AST parse / grep / file-existence) — dev box has no Python runtime for pytest, checks run via `python -c` AST where available or shell `test`/`grep` |
| **Full suite command** | Cloud Build suite run (both harnesses) — deferred live gate per the no-local-Python constraint; executed at Plan 14-04's operator session (D-07) |
| **Estimated runtime** | ~5 s per structural check; Cloud Build suite ~10 min |

---

## Sampling Rate

- **After every task commit:** Run that task's `<automated>` verify command (structural: AST/grep/existence)
- **After every plan wave:** Re-run all `<automated>` checks for the wave's plans
- **Before `/gsd:verify-work`:** Cloud Build suite green + D-07 live proof checkpoint (Plan 14-04 Task 3)
- **Max feedback latency:** 10 seconds (structural checks); live gates deferred to the 14-04 operator session

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 14-01-01 | 01 | 1 | SEAM-01 | T-14-05 | No silent Firebase fallback; get_auth_provider raises without an installed provider | structural | `cd tribunal && test ! -e ...identity_platform.py && ! grep firebase-admin requirements.txt` (full cmd in 14-01-PLAN Task 1) | ✅ | ⬜ pending |
| 14-01-02 | 01 | 1 | SEAM-01 | T-14-01/02/03/04 | OIDC aud+SA-email verified before any tenant trust; EXISTING AuthClaims fields only (D-05) | structural (AST) | `python -c` AST check on `internal_caller.py` (14-01-PLAN Task 2) | ✅ | ⬜ pending |
| 14-01-03 | 01 | 1 | SEAM-01, SEAM-02 | T-14-03 | ensure_org/ensure_project idempotent, org.id == space_id, set_tenant_context ordering kept | structural (AST) | `python -c` AST check on `orgs/provision.py` + grep on `server.py` (14-01-PLAN Task 3) | ✅ | ⬜ pending |
| 14-02-01 | 02 | 1 | SEAM-02 | T-14-07 | Service URL is non-secret Settings config; no secret in image | structural (AST) | `python -c` AST check on `app/core/config.py` (14-02-PLAN Task 1) | ✅ | ⬜ pending |
| 14-02-02 | 02 | 1 | SEAM-02 | T-14-06/08 | Keyless ADC OIDC mint, audience pinned to Tribunal URL (no path); headers forwarded never fabricated | structural (AST) | `python -c` AST check on `app/research/tribunal_client.py` (14-02-PLAN Task 2) | ✅ | ⬜ pending |
| 14-03-01 | 03 | 2 | SEAM-02 | T-14-09/11 | EXACT 401/403 seam denials; GUC-leak firewall (space-A header never yields space-B rows) | integration (pytest, Cloud Build) | AST/collect check locally; full run in Cloud Build (14-03-PLAN Task 1) | ✅ | ⬜ pending |
| 14-03-02 | 03 | 2 | SEAM-02 | T-14-10 | Cross-tenant RLS denial on tribunal.* project/run tables + no-context denial | integration (pytest asyncpg, Cloud Build) | AST/collect check locally; full run in Cloud Build (14-03-PLAN Task 2) | ✅ | ⬜ pending |
| 14-04-01 | 04 | 3 | SEAM-01, SEAM-02 | T-14-12/13/14 | Dedicated least-priv tribunal-run SA; invoker = nestor-run only; no allUsers | structural (grep) | grep on `infra/main.tf` + deploy scripts (14-04-PLAN Task 1) | ✅ | ⬜ pending |
| 14-04-02 | 04 | 3 | SEAM-01 | T-14-15 | Runbook applies IAM/env live; conservative secret cleanup (no shared-secret deletion without no-other-reader check) | structural (grep) | grep on `infra/DEPLOY-RUNBOOK.md` (14-04-PLAN Task 2) | ✅ | ⬜ pending |
| 14-04-03 | 04 | 3 | SEAM-01, SEAM-02 | T-14-12/13 | D-07 live proof: end-to-end run + unauthenticated & wrong-SA negative proofs | manual (checkpoint:human-verify) | — (operator session, see Manual-Only below) | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Existing infrastructure covers all phase requirements — both pytest harnesses exist (`backend/tests/test_intake_cross_tenant.py` clone source; `tribunal/nestor_pulse_sdk/tests/test_rls_isolation.py` extension target). No framework install needed.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| D-07 live proof: intake backend triggers a real Tribunal run end-to-end, space-scoped | SEAM-01, SEAM-02 | Dev box has no Python/Docker; IAM + Cloud Run behavior only observable live | 14-04-PLAN Task 3 checkpoint: run the § Phase 14 runbook, execute positive proof + unauthenticated (expect 401/403 at IAM edge) + wrong-SA negative proofs |
| Cloud Build full-suite run (both harnesses green incl. new denial tests) | SEAM-02 | No local test runtime | Runbook step in 14-04-PLAN Task 2; suite invocation pattern from Phase 7 memory |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (9/9 auto tasks; 1 human checkpoint exempt)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (none — no MISSING markers)
- [x] No watch-mode flags
- [x] Feedback latency < 10s for structural checks
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-20
