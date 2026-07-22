---
phase: 18-human-report-upload-client-delivery
verified: 2026-07-22T18:30:00Z
status: passed
score: 17/17 must-haves verified
overrides_applied: 0
---

# Phase 18: Human Report Upload + Client Delivery — Verification Report

**Phase Goal:** The superadmin uploads the externally crafted final report PDF, moving the intake to `delivered`, and the client sees, downloads, and is emailed about it.
**Verified:** 2026-07-22
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

All truths are drawn from the merged must-haves across 18-01, 18-02, 18-03, and 18-04 PLAN frontmatter, plus the REQUIREMENTS.md success criteria for REPORT-01/02/03.

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | POST /intakes/{id}/deliver flips in_research -> delivered, creates a report research_artifacts row, sets final_report_artifact_id, and sends the results-family mail | VERIFIED | `_DELIVER_TRANSITIONS = {"in_research": "delivered"}` at line 1234; `deliver_report` at line 1502; `_create_report_artifact` at line 1421; `_send_report_mail` at line 1448; all in `intake_routes.py` |
| 2  | POST /intakes/{id}/deliver on any status other than in_research returns 409 | VERIFIED | `if intake.status not in _DELIVER_TRANSITIONS: raise HTTPException(409, ...)` at line 1533; `test_deliver_wrong_status_returns_409` in `test_report_delivery.py` |
| 3  | Deliver rejects a storage_path not ending in .pdf with 422 (server-side PDF-only, D-10) | VERIFIED | `_assert_report_key` at line 1411: `if not storage_path.lower().endswith(".pdf"): raise HTTPException(422, ...)` |
| 4  | Deliver rejects a storage_path not starting with {space_id}/{intake_id}/reports/ with 404 (forged-key guard, D-08) | VERIFIED | `_assert_report_key` at line 1415: `prefix = f"{intake.space_id}/{intake.id}/reports/"; if not storage_path.startswith(prefix): raise HTTPException(404, ...)` |
| 5  | GET /intakes/{id}/report returns 404 unless the intake status is exactly 'delivered' (REPORT-02 invisibility gate) | VERIFIED | `get_report` at line 1638: `if intake is None or intake.status != "delivered": raise HTTPException(404, ...)` — exact equality, no rank comparison |
| 6  | POST /intakes/{id}/report/replace repoints final_report_artifact_id to a new artifact row, status stays 'delivered' | VERIFIED | `replace_report` at line 1575: `intake.status != "delivered"` -> 409; creates new artifact via `_create_report_artifact`; patches only `final_report_artifact_id`, never `status` |
| 7  | A mail-send failure at Deliver leaves the intake 'delivered' but results_link_sent_at NULL (recoverable) | VERIFIED | Deliver commits flip+link+audit in one `tenant_session` BEFORE calling `_send_report_mail`; `results_link_sent_at` stamped only on `True` return from `_send_report_mail`; `test_deliver_mail_failure` in `test_report_delivery.py` |
| 8  | Cross-tenant: user-A cannot deliver or read the report of user-B's intake (-> 404) | VERIFIED | `test_deliver_cross_tenant_returns_404_intake_unchanged` and `test_report_cross_tenant_returns_404` in `test_intake_cross_tenant.py`; existence-hidden 404 from the scoped repo |
| 9  | During in_research the admin detail shows the FinalReportBlock (staged-upload UI) | VERIFIED | `phaseShowsFinalReport` in `intake-phase.ts` line 119: array includes `"in_research"` |
| 10 | Uploading a PDF stages it locally (status stays in_research, nothing client-visible) | VERIFIED | `FinalReportBlock.tsx` — `onPick` sets `setStagedPath`/`setStagedMeta`, does NOT call onChange or deliver; Deliver affordance is separate |
| 11 | Deliver action opens RecipientPicker and calls deliverReport -> status flips to delivered, mail sent | VERIFIED | `FinalReportBlock.tsx` line 140: `await deliverReport(intakeId, { storagePath: stagedPath, recipients: membershipIds })`; two `<RecipientPicker>` mounts (Deliver + Replace) at lines 420 and 430 |
| 12 | File input accepts only .pdf (D-10) | VERIFIED | `FinalReportBlock.tsx` line 311: `accept=".pdf"` — no .docx/.md/.txt; `maybeAutoDeliver` absent |
| 13 | Admin onChange reloads from the backend view (no client-side status fake) | VERIFIED | `admin.pulse.intakes.$id.tsx` line 1464-1475: `onChange` calls `getIntake(intake.id)` and merges `status`, `final_report_artifact_id`, `results_link_sent_at` from backend response |
| 14 | A client visiting /intake/{id}/report on a delivered intake sees the report metadata + a download button; the route redirects away for any non-delivered status | VERIFIED | `intake.$id.report.tsx` line 75: `if (intakeRes.data.status !== "delivered") { navigate({ to: "/intake" }); return; }` — exact equality; `getReport(id)` at line 80; `signedDownloadUrl` at line 115; no iframe/embed |
| 15 | The route requires an authenticated user (redirect to /auth/login otherwise) | VERIFIED | `intake.$id.report.tsx` line 32-38: `beforeLoad: async () => { const user = await authReady(); if (!user) throw redirect({ to: "/auth/login" }); }` |
| 16 | The intake list shows a 'View report' CTA only when status == 'delivered', navigating to the report page | VERIFIED | `intake.index.tsx` line 73: `if (status === "delivered") return { label: t("list.ctaReport"), target: "report" }`; `openRow` at line 110: navigates to `/intake/$id/report` |
| 17 | infra/DEPLOY-RUNBOOK.md has a § Phase 18 section (nestor-api rebuild + frontend deploy, NO migrate, NO new secret) with live UAT checklist | VERIFIED | `DEPLOY-RUNBOOK.md` line 1532: `## Phase 18 — Human report upload + client delivery (nestor-api REBUILD + frontend deploy, NO migrate, NO new secret)`; Steps 18.a–18.e present; explicit NO migrate note at line 1647 |

**Score:** 17/17 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/api/intake_routes.py` | deliver_report / replace_report / get_report verbs + DeliverBody + ReportView + _DELIVER_TRANSITIONS | VERIFIED | All present: `_DELIVER_TRANSITIONS` line 1234, `DeliverBody` line 280, `ReportView` line 299, `deliver_report` line 1502, `replace_report` line 1575, `get_report` line 1637 |
| `backend/tests/test_report_delivery.py` | 9 test cases covering REPORT-01/02/03 happy + status-gate + PDF-only + mail-failure + replace | VERIFIED | File exists; all 9 -k selectors present: deliver_transition, deliver_wrong_status, pdf_only, deliver_forged_key, deliver_mail, deliver_mail_failure, replace, report_read_delivered, report_read_pre_delivery |
| `backend/tests/test_intake_cross_tenant.py` | deliver_cross_tenant + report_cross_tenant + report_read_pre_delivery denial cases | VERIFIED | `_insert_intake_status` helper; `test_deliver_cross_tenant_returns_404_intake_unchanged`; `test_report_cross_tenant_returns_404`; `test_report_read_pre_delivery_returns_404` all present |
| `frontend/src/lib/api/intakes.ts` | deliverReport / replaceReport / getReport + ReportView type | VERIFIED | `ReportView` type line 99; `deliverReport` line 113; `replaceReport` line 132; `getReport` line 149 |
| `frontend/src/lib/intake-phase.ts` | phaseShowsFinalReport includes in_research | VERIFIED | `phaseShowsFinalReport` array at line 119 contains `"in_research"` |
| `frontend/src/components/intake/FinalReportBlock.tsx` | staged-upload + Deliver dialog + Replace + PDF-only, no auto-deliver | VERIFIED | `accept=".pdf"` line 311; `deliverReport` call line 140; `replaceReport` calls lines 164 and 185; two `RecipientPicker` mounts; no `maybeAutoDeliver` |
| `frontend/src/routes/intake.$id.report.tsx` | authenticated, delivered-only client report page (download-only) | VERIFIED | Exists; `createFileRoute("/intake/$id/report")` line 32; auth beforeLoad; exact `status !== "delivered"` gate; `getReport` call; `signedDownloadUrl` call; no iframe/embed; `chatComingSoon` placeholder |
| `frontend/src/routes/intake.index.tsx` | delivered -> View report CTA routed to the report page | VERIFIED | `RowCta` includes `"report"` target; `rowCta` returns `report` for `status === "delivered"`; `openRow` navigates to `/intake/$id/report` |
| `frontend/src/routeTree.gen.ts` | /intake/$id/report registered | VERIFIED | Import at line 32; route registered at lines 255, 290, 329, 369, 442, 607 |
| `frontend/src/routes/intake.$id.tsx` | Parent route renders Outlet for child routes (UAT-cycle fix 285f050) | VERIFIED | `UserIntakeRouteShell` function; `Outlet` import; child routes report and results now render |
| `infra/DEPLOY-RUNBOOK.md` | § Phase 18 section with rebuild commands + failure triage | VERIFIED | Section at line 1532; backend rebuild `gcloud builds submit backend --tag` at line 1600; frontend deploy at line 1635; failure triage block present |
| `frontend/src/locales/{nl,fr,en}/intake.json` | finalReport.deliver/delivering/delivered/deliverFailed/staged/replaceConfirm/reNotify in all 3 locales | VERIFIED | NL: lines 423-430; FR and EN: matching keys confirmed |
| `frontend/src/locales/{nl,fr,en}/intake.json` | reportPage.* block + list.ctaReport in all 3 locales | VERIFIED | NL: `reportPage` at line 178 with all required keys; FR line 178; EN line 178; `ctaReport` at line 107 in all 3 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `deliver_report` | `artifact_repo.create_in_space` | `_create_report_artifact` — role-branch superadmin/user | VERIFIED | `_create_report_artifact` at line 1421: `identity.role == "superadmin"` -> `create_in_space(intake.space_id, ...)` else `create(...)` |
| `deliver_report` | `_resolve_recipient_locales + mail_render.render_results` | `_send_report_mail` helper sends results-family mail with /report CTA | VERIFIED | `_send_report_mail` at line 1448 calls `_resolve_recipient_locales`, `mail_render.render_results`, with `cta_url=f"{base_url}/intake/{intake.id}/report"` |
| `get_report` | `final_report_artifact_id -> research_artifacts row` | `ReportView` projection carries filename/byte_size/mime_type/storage_path | VERIFIED | `get_report` lines 1664-1680: fetches artifact via `repo.get(intake.final_report_artifact_id)`, returns `ReportView(filename=artifact.filename, ...)` |
| `FinalReportBlock Deliver button` | `deliverReport(intakeId, { storagePath, recipients })` | RecipientPicker `onConfirm` -> `onDeliverConfirm` | VERIFIED | `FinalReportBlock.tsx` line 140; `<RecipientPicker ... onConfirm={onDeliverConfirm} />` at line 420 |
| `admin route FinalReportBlock onChange` | backend intake view reload | `getIntake(intake.id)` merges status/final_report_artifact_id/results_link_sent_at | VERIFIED | `admin.pulse.intakes.$id.tsx` lines 1464-1475 |
| `intake.$id.report.tsx` | `getReport(id) + signedDownloadUrl` | delivered-gated metadata load + signed-URL blob download | VERIFIED | Lines 80 and 115 in `intake.$id.report.tsx` |
| `intake.index.tsx rowCta` | `/intake/$id/report` | `status === "delivered"` branch -> `target: "report"` -> `openRow` navigate | VERIFIED | Lines 73 and 110-111 in `intake.index.tsx` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `intake.$id.report.tsx` | `report: ReportView` | `getReport(id)` -> `GET /intakes/{id}/report` -> `artifact_repo.get(final_report_artifact_id)` | Yes — fetches from `research_artifacts` table via scoped repo | FLOWING |
| `FinalReportBlock.tsx` | `artifact` (post-deliver) | `getReport(intakeId)` in useEffect when `finalReportArtifactId` is set | Yes — reads the linked artifact row | FLOWING |
| `intake.index.tsx` | `intakes` list | Existing intake list fetch (Phase 12, unchanged) | Yes — real DB query | FLOWING (unchanged seam) |

---

### Behavioral Spot-Checks

Backend: Not runnable locally (dev box has no Python). Cloud Build suite b0365150 executed 2026-07-22 — ALL Phase-18 tests green (`test_report_delivery.py` 9 cases + 3 cross-tenant denial cases in `test_intake_cross_tenant.py`). Only the 4 known pre-existing mail test-harness defects fail (deferred to Phase 20 CLOSE-02).

Frontend: TypeScript type-check (`tsc --noEmit`) confirmed passing per 18-02 and 18-03 SUMMARY self-checks. No frontend test framework exists in this repo.

Live UAT: Executed 2026-07-22 on intake e08620c5-2ccf-4006-8bce-ae45f47f8c88. API deployed as `nestor-api-00038-7jp` (backend build ae8d3fb4); frontend deployed as `nestor-frontend-00018-m6x` (includes Outlet fix 285f050).

| Behavior | Result | Status |
|----------|--------|--------|
| Stage PDF → status stays in_research, client sees nothing (REPORT-02) | PASS — upload 201 @17:15:11Z, status stayed in_research | PASS |
| Deliver → status flips, mail arrives, CTA deep-links /intake/{id}/report (REPORT-01/03) | PASS — POST /deliver 200 @17:15:19Z; operator received mail | PASS |
| Client "View report" -> report page loads -> PDF downloads (REPORT-02) | PASS (after Outlet fix 285f050) — GET /report 200 + signed-url 200 @17:27Z | PASS |
| Replace silent + re-notify (D-04/D-05) | ACCEPTED (operator decision) — UI worked per operator; no backend log evidence; verb covered by Cloud Build `replace` test | ACCEPTED |

---

### Probe Execution

No conventional `scripts/*/tests/probe-*.sh` probes exist for this phase. The equivalent proof is the Cloud Build suite (build b0365150) and the live UAT documented in `18-HUMAN-UAT.md`.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| REPORT-01 | 18-01, 18-02, 18-04 | Superadmin can upload the final report PDF -> status `delivered` | SATISFIED | `deliver_report` verb + `FinalReportBlock` Deliver dialog; live UAT PASS (test 2) |
| REPORT-02 | 18-01, 18-03, 18-04 | Client sees and downloads the final report; nothing research-related is client-visible before delivery | SATISFIED | `get_report` status gate (equality); client route exact equality gate; list CTA gated on `delivered`; Outlet fix deployed; live UAT PASS (tests 1 and 3) |
| REPORT-03 | 18-01, 18-02, 18-04 | Client receives email when report is delivered | SATISFIED | `_send_report_mail` in `deliver_report`; results-family mail with /report CTA; live UAT PASS (test 2 — operator received mail) |

All 3 requirements from REQUIREMENTS.md Phase 18 mapping are SATISFIED.

---

### Anti-Patterns Found

Scanned all 8 files modified/created by this phase.

| File | Pattern | Severity | Notes |
|------|---------|----------|-------|
| `frontend/src/routes/intake.$id.report.tsx` | `reportPage.chatComingSoon` placeholder section | INFO | Intentional — explicitly scoped as a static layout reservation for Phase-19 Q&A chat (D-07). No data fetch, no chat UI. Not a stub for this phase's goal. |
| `backend/app/api/intake_routes.py` | Pre-existing `run_task.py` raw-engine access noted in deferred-items.md | INFO | Pre-dates Phase 18 (Phase 17 base commit). The Phase-18 additions are clean under the `ci_no_raw_db_access.sh` guard. |

No `TBD`, `FIXME`, or `XXX` markers found in Phase-18-modified files. No unreferenced debt markers. The `chatComingSoon` placeholder is a named, intentionally scoped deferred feature (Phase 19) — not an unresolved marker.

---

### Human Verification Required

None. All UAT items are recorded as closed in `18-HUMAN-UAT.md` (3 PASS + 1 operator-accepted). The operator-accepted replace item (UAT test 4) is a documented residual risk: the live click-through was not server-log-confirmed, but the `replace_report` verb is covered green in Cloud Build (`test_report_delivery.py` `replace` case). The operator explicitly accepted this and closed the phase. No re-verification of human items is warranted per the verification context.

---

### Gaps Summary

No gaps. All 17 must-haves verified in the codebase. The three REPORT requirements are satisfied end-to-end:

- **REPORT-01**: `deliver_report` verb exists, is substantive, and is wired. The Deliver dialog in `FinalReportBlock` calls it via `deliverReport`. Deployed live as `nestor-api-00038-7jp`; live UAT PASS.
- **REPORT-02**: `get_report` uses exact-equality status gate (no rank comparison). The client route also gates exactly on `status !== "delivered"`. The list CTA appears only for `delivered`. The `intake.$id.tsx` parent Outlet fix (commit 285f050) was deployed, unblocking child route rendering. Live UAT PASS.
- **REPORT-03**: `_send_report_mail` is wired into `deliver_report` (and optionally `replace_report`). Results-family mail with `/report` CTA. Live UAT PASS (operator received mail).

---

_Verified: 2026-07-22_
_Verifier: Claude (gsd-verifier)_
