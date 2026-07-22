---
phase: 18
slug: human-report-upload-client-delivery
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-22
---

# Phase 18 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend, sync pg8000 harness) + Cloud Build suites |
| **Config file** | backend/tests/conftest.py · cloudbuild.test.yaml |
| **Quick run command** | Cloud Build targeted: `gcloud builds submit . --config=cloudbuild.test.yaml` (from repo root) — no local Python |
| **Full suite command** | `gcloud builds submit . --config=cloudbuild.test.yaml` (full backend suite) |
| **Estimated runtime** | ~10-15 min (Cloud Build) |
| **Author-by-construction note** | Dev machine has no Python/Docker — tests are authored with the plan and run in Cloud Build at wave boundaries, not per-commit. Frontend has NO test framework in this repo — client-route gating (delivered-only) is verified via live UAT (18-04). |

---

## Sampling Rate

- **After every task commit:** author-by-construction review (no local runner); frontend tasks run `npx tsc --noEmit`
- **After every plan wave:** Cloud Build backend suite (deliver-verb / report-read / replace / cross-tenant / mail subsets)
- **Before `/gsd:verify-work`:** Full Cloud Build suite green
- **Max feedback latency:** one Cloud Build round (~15 min)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 18-01 T1 | 18-01 | 1 | REPORT-01 | T-18-03/04/06/07 | Deliver in_research→delivered; PDF-only 422; forged-key 404; create_in_space; same-tx audit | integration | `pytest backend/tests/test_report_delivery.py -k "deliver_transition or deliver_wrong_status or pdf_only or deliver_forged_key" -x` | ❌ Wave 0 (T3) | ⬜ pending |
| 18-01 T1 | 18-01 | 1 | REPORT-03 | T-18-05 | Mail sent to resolved recipients w/ /report CTA; stamp on 2xx; mail-failure leaves delivered + NULL ts | integration | `pytest backend/tests/test_report_delivery.py -k "deliver_mail or deliver_mail_failure" -x` | ❌ Wave 0 (T3) | ⬜ pending |
| 18-01 T2 | 18-01 | 1 | REPORT-02 | T-18-01 | GET /report 404 unless status=='delivered' (equality gate) | integration | `pytest backend/tests/test_report_delivery.py -k "report_read_pre_delivery or report_read_delivered" -x` | ❌ Wave 0 (T3) | ⬜ pending |
| 18-01 T2 | 18-01 | 1 | REPORT-01 | T-18-03/04 | Replace repoints artifact, status stays delivered, optional re-notify | integration | `pytest backend/tests/test_report_delivery.py -k "replace" -x` | ❌ Wave 0 (T3) | ⬜ pending |
| 18-01 T3 | 18-01 | 1 | REPORT-02 | T-18-02 | Cross-tenant deliver/report → 404; B unchanged; pre-delivery own-space read → 404 | integration | `pytest backend/tests/test_intake_cross_tenant.py -k "deliver_cross_tenant or report_cross_tenant or report_read_pre_delivery" -x` | ❌ Wave 0 (T3) | ⬜ pending |
| 18-02 T1 | 18-02 | 2 | REPORT-01/03 | T-18-08 | Seam verbs typed; phaseShowsFinalReport includes in_research | type-check | `cd frontend && npx tsc --noEmit -p tsconfig.json` | ✅ (source) | ⬜ pending |
| 18-02 T2 | 18-02 | 2 | REPORT-01 | T-18-09/10 | Staged upload (no auto-deliver); PDF-only accept; explicit Deliver via RecipientPicker | type-check + Manual-Only | `cd frontend && npx tsc --noEmit` (+ live UAT 18-04) | ✅ (source) | ⬜ pending |
| 18-02 T3 | 18-02 | 2 | REPORT-01 | T-18-08 | Admin reloads backend view (no client-side status fake); i18n NL/FR/EN | type-check + i18n presence | `cd frontend && npx tsc --noEmit` | ✅ (source) | ⬜ pending |
| 18-03 T1 | 18-03 | 3 | REPORT-02 | T-18-11/12/13 | Report route gates exactly delivered; signed-URL download; no viewer; chat space reserved | type-check + Manual-Only | `cd frontend && npx tsc --noEmit` (+ live UAT 18-04) | ✅ (source) | ⬜ pending |
| 18-03 T2 | 18-03 | 3 | REPORT-02 | T-18-11 | Delivered-only "View report" CTA; report-page i18n NL/FR/EN | type-check | `cd frontend && npx tsc --noEmit` | ✅ (source) | ⬜ pending |
| 18-04 T1 | 18-04 | 4 | REPORT-01/02/03 | T-18-14 | § Phase 18 runbook: backend+frontend rebuild, no migrate, no new secret | grep gate | `grep -q "Phase 18" infra/DEPLOY-RUNBOOK.md && grep -q "gcloud builds submit backend" infra/DEPLOY-RUNBOOK.md` | ✅ (source) | ⬜ pending |
| 18-04 T2 | 18-04 | 4 | REPORT-01/02/03 | T-18-15/16 | Live deploy + stage/deliver/download/mail UAT (blocking human-action) | Manual-Only | 18-HUMAN-UAT.md sign-off | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/test_report_delivery.py` — NEW (18-01 Task 3): deliver transition + 409 status-gate + PDF-only + forged-key + mail + mail-failure + replace + report-read (pre/post delivery)
- [ ] Extend `backend/tests/test_intake_cross_tenant.py` (18-01 Task 3) — `deliver_cross_tenant` + `report_cross_tenant` + `report_read_pre_delivery`
- [ ] Fake-Resend seam: monkeypatch `mail_resend.send` in the new test file (recording fake + a raising variant for recoverability)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Delivery email renders + arrives (NL/FR/EN), CTA deep-links to `/intake/{id}/report` | REPORT-03 | Live Resend send + real inbox | Deliver a staged report on a test intake; check recipient inbox + CTA target (18-04 Step 18.e) |
| Client downloads the PDF via signed URL in the live UI | REPORT-02 | Signed GCS URL + browser blob flow | Log in as a client member, open the report page, download + open the PDF (18-04 Step 18.e) |
| FinalReportBlock staged-upload / explicit-Deliver / Replace behaviors | REPORT-01 | No FE test framework in repo | Live admin session: stage → confirm client invisible → Deliver → Replace (silent + re-notify) (18-04 Step 18.e) |
| Report page + list CTA invisible for any non-delivered status | REPORT-02 | No FE test framework; end-to-end gate | Attempt to open `/intake/{id}/report` on an in_research intake → redirected to /intake (18-04 Step 18.e) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (or Manual-Only rows for FE runtime behavior)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has tsc/pytest/grep)
- [x] Wave 0 covers all MISSING references (test_report_delivery.py + cross-tenant extensions)
- [x] No watch-mode flags
- [x] Feedback latency < one Cloud Build round (~15 min)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planned (author-by-construction; Cloud Build sampling at wave boundaries per project constraint)
