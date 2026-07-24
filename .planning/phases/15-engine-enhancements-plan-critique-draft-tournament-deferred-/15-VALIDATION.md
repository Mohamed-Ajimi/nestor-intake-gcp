---
phase: 15
slug: research-engine-redesign-operator-surfaces
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-24
revised: 2026-07-24
---

# Phase 15 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Populated from the actual 15-01…15-07 PLAN.md tasks after the revision pass
> (real pytest/tsc gates promoted to each task's primary `<automated>` verify).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework (backend/tribunal)** | pytest, run via Cloud Build (no local Python/Docker — MEMORY: dev machine) |
| **Framework (frontend)** | `tsc --noEmit` typecheck + `node scripts/i18n-audit.mjs` (no vitest runner in repo) |
| **Quick run command** | targeted pytest module via Cloud Build (per task) |
| **Full suite command** | full backend + tribunal suite in Cloud Build (179 green as of 2026-07-23) |
| **Estimated runtime** | ~10–15 min per Cloud Build suite run |
| **Recorded-run fixture** | `docs/tribunal-run-reports/run-20260722-4cbb5311/` extracts + `selection-experiment/*.tsv` — Wave 0 (Plan 15-01) rebuilds the fixture (incl. verdict rows from `emit_group_verdict` extracts) from these committed files; no GCS pull needed |

---

## Sampling Rate

- **After every task commit:** the task's primary `<automated>` Cloud Build pytest target (or `tsc`/`i18n-audit` for frontend), plus the secondary ast/json syntax guard. Author-by-construction where a live run is impossible.
- **After every plan wave:** targeted Cloud Build suite run for the wave's modules.
- **Before `/gsd:verify-work`:** full backend + tribunal suite green; frontend `tsc --noEmit` + `i18n-audit` green.
- **Max feedback latency:** one Cloud Build run (~15 min) < 900s target per module.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 15-01·T1 | 15-01 | 1 | ENGINE-09 | T-15-01, T-15-03 | migration 0011 additive; RLS on verification_verdict; not in nestor line | integration | `pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` | ✅ W0 | ⬜ pending |
| 15-01·T2 | 15-01 | 1 | ENGINE-09 | T-15-01 | new cost/verdict columns non-hashed | integration | `pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` | ✅ W0 | ⬜ pending |
| 15-01·T3 | 15-01 | 1 | ENGINE-09 | T-15-01, T-15-02 | fixture seeds real verdict rows (refute + reconciliation) from committed extracts; verify_chain green post-migration | unit/integration | `pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` | ✅ W0 | ⬜ pending |
| 15-02·T1 | 15-02 | 2 | ENGINE-09 | T-15-04, T-15-05 | cache-write priced; unknown model → NULL (never guessed) | unit | `pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` | ✅ | ⬜ pending |
| 15-02·T2 | 15-02 | 2 | ENGINE-09 | T-15-04, T-15-05 | tool fees counted; DR usageMetadata present→priced / absent→pending (Q3: absent in recorded run); nothing hashed | unit | `pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` | ✅ | ⬜ pending |
| 15-02·T3 | 15-02 | 2 | ENGINE-09 | T-15-05 | facts-only proof: cache-write/tool-fee/DR/NULL-on-unknown | unit | `pytest nestor_pulse_sdk/tests/test_cost_cache_write.py -x` | ✅ | ⬜ pending |
| 15-03·T1 | 15-03 | 2 | ENGINE-09 | T-15-06 | report shaped from persisted verdict rows (no blob re-parse); enriched stage_detail additive | unit | `pytest nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x` | ✅ | ⬜ pending |
| 15-03·T2 | 15-03 | 2 | ENGINE-09 | T-15-06 | GET /verification RLS 404-on-miss, tenant-scoped | integration | `pytest nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x` | ✅ | ⬜ pending |
| 15-03·T3 | 15-03 | 2 | ENGINE-09 | T-15-07, T-15-08 | [n] deterministic from DB ordering, all-resolve; verification RLS denial | unit/integration | `pytest nestor_pulse_sdk/tests/test_citation_numbering.py nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x` | ✅ | ⬜ pending |
| 15-03·T4 | 15-03 | 2 | ENGINE-09 | T-15-08b, T-15-08c | audit-body drill-down: RLS 404-on-miss, redacted body only, no hash exposure | integration | `pytest nestor_pulse_sdk/tests/test_audit_body_endpoint.py -x` | ✅ | ⬜ pending |
| 15-04·T1 | 15-04 | 3 | ENGINE-09 | T-15-11 | seam methods reuse OIDC header discipline (path-less audience) | unit | `pytest tests/test_research_cross_tenant.py -x` | ✅ | ⬜ pending |
| 15-04·T2 | 15-04 | 3 | ENGINE-09 | T-15-09, T-15-10, T-15-11b | superadmin-only, space-scoped, existence-hidden proxies (verification/source/audit-body) | integration | `pytest tests/test_research_cross_tenant.py -x` | ✅ | ⬜ pending |
| 15-04·T3 | 15-04 | 3 | ENGINE-09 | T-15-09, T-15-10, T-15-11b | denial trio ×3 routes (no seam call on denial) + superadmin happy-path funnel (SC1 pre-UAT proof) | integration | `pytest tests/test_research_cross_tenant.py -x` | ✅ W0 | ⬜ pending |
| 15-05·T1 | 15-05 | 4 | ENGINE-09 | — | getVerification + getAuditBody via unforked apiFetch; optional enriched types | typecheck | `npx tsc --noEmit -p tsconfig.json` | ✅ | ⬜ pending |
| 15-05·T2 | 15-05 | 4 | ENGINE-09 | T-15-12, T-15-13b | D15 feed + REAL audit-body drill-down panel (not no-op); superadmin placement | typecheck | `npx tsc --noEmit -p tsconfig.json` | ✅ | ⬜ pending |
| 15-05·T3 | 15-05 | 4 | ENGINE-09 | T-15-12, T-15-13 | VerificationReport facts-only pending cost; en/fr/nl keyed | typecheck + i18n | `node scripts/i18n-audit.mjs && npx tsc --noEmit -p tsconfig.json` | ✅ | ⬜ pending |
| 15-06·T1 | 15-06 | 5 | ENGINE-09 | — | getSource via unforked apiFetch; Citation/CitationSource types | typecheck | `npx tsc --noEmit -p tsconfig.json` | ✅ | ⬜ pending |
| 15-06·T2 | 15-06 | 5 | ENGINE-09 | T-15-14, T-15-15, T-15-16 | [n] panel renders stored snapshot (no live-URL fetch); en/fr/nl keyed | typecheck + i18n | `node scripts/i18n-audit.mjs && npx tsc --noEmit -p tsconfig.json` | ✅ | ⬜ pending |
| 15-07·T1 | 15-07 | 6 | ENGINE-09 | T-15-17, T-15-19 | runbook: dual rebuild + 0011 migrate (tribunal line) + frontend rebuild + verify_chain gate | doc-gate | `grep -c "Phase 15 — Research engine redesign" infra/DEPLOY-RUNBOOK.md` | ✅ | ⬜ pending |
| 15-07·T2 | 15-07 | 6 | ENGINE-09 | T-15-18 | UAT script derived from ROADMAP SC + CONTEXT V-02; recorded-run only; client-blind check | doc-gate | `test -f …/15-UAT.md && grep -c "verify_chain" …/15-UAT.md` | ✅ | ⬜ pending |
| 15-07·T3 | 15-07 | 6 | ENGINE-09 | T-15-17, T-15-18, T-15-19 | operator deploy + recorded-run UAT + V-02 sign-off (blocking checkpoint) | manual (human-verify) | — (see Manual-Only Verifications) | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*
*File Exists: ✅ = target file exists or is created within its own task/plan; W0 = Wave-0 scaffold that later waves depend on.*

---

## Wave 0 Requirements

Wave 0 = Plan 15-01 (wave 1). Every downstream surface test depends on the recorded-run fixture + the interface/schema contracts created here. All satisfied by 15-01:

- [x] Recorded-run fixture loader (`tests/fixtures/run_4cbb5311/loader.py`) rebuilds run/audit_log/claim/source/claim_source/`verification_verdict` from the committed `docs/…/run-20260722-4cbb5311/` extracts — provenance confirmed (Q4: rebuild-from-committed-extracts is the documented source; no GCS at test time).
- [x] Verdict extractor (`tests/fixtures/run_4cbb5311/verdict_extract.py`) parses the `emit_group_verdict` JSON from committed `group_skeptic` call extracts into real verdict rows (verdict/confidence/evidence_refs/reconciliation) — closes the key_links gap for `build_verification_report()` (15-03) which reads these rows.
- [x] Interface/schema contracts for the read model: migration 0011 (`verification_verdict` RLS table + `run.verification_summary` + cost columns) + SQLAlchemy models — every wave-2 read task builds against these.
- [x] Cross-tenant denial extensions: every new table/endpoint gets an RLS/denial test — verification (15-03·T2/T3), audit-body (15-03·T4), seam proxies ×3 (15-04·T3).
- [x] Test targets exist (or are created within their task) for cost recompute (15-02), citation numbering (15-03), audit-body (15-03·T4), feed item shapes (15-05 via tsc). No task ships without an automated gate.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Feed / verification-report / citations / audit-body drill-down visual UAT vs D15 mockup + `replit view.png` | ENGINE-09 (SC1/SC2/SC4) | Visual design bar; recorded-run browser walkthrough | Operator opens admin intake detail for run-4cbb5311 and walks 15-UAT.md steps 1–4 (15-07·T3) |
| Client-role blindness (16-D-08) | ENGINE-09 | Requires a second (client) login session | Operator logs in as a client for the same space and confirms NONE of the research surfaces render (15-UAT.md step + 15-07·T3) |
| `verify_chain` green on deployed audit data | ENGINE-09 (SC5) | Runs against the live audit bucket post-deploy | Run the `verify_chain` job per runbook Step 15.d after deploy (15-07·T1/T3) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (see map above; 15-07·T3 is the one intended manual checkpoint, backed by 15-07·T1/T2 doc-gates)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (each code task carries a Cloud Build pytest or tsc/i18n gate; the only manual task is the terminal operator checkpoint)
- [x] Wave 0 covers all MISSING references (fixture + verdict extractor + schema contracts + denial extensions — all in Plan 15-01, plus the seam happy-path in 15-04)
- [x] No watch-mode flags (all commands are one-shot `-x` / `--noEmit`)
- [x] Feedback latency < 900s (one Cloud Build run per module)
- [x] `nyquist_compliant: true` set in frontmatter
- [x] `wave_0_complete: true` set in frontmatter (Wave 0 = Plan 15-01, fully specified)

**Approval:** approved (revision pass 2026-07-24)
