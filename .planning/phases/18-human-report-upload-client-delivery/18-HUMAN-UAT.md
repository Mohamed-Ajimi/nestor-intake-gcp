---
status: partial
phase: 18-human-report-upload-client-delivery
source: [18-04-PLAN.md Task 2 checkpoint, DEPLOY-RUNBOOK.md § Phase 18]
started: 2026-07-22T17:00:00Z
updated: 2026-07-22T17:00:00Z
---

## Deploy record (executed 2026-07-22 by Claude session, operator-authorized "DO IT")

| Step | What | Result |
|------|------|--------|
| 18.a | nestor-api image rebuild + repoint | ✅ `backend:20260722-184319` → rev **nestor-api-00038-7jp** (build ae8d3fb4, SUCCESS 1m41s) |
| 18.a smoke | deliver / replace / report verbs live | ✅ all three return 401 auth-wall (not 404 route-miss) |
| 18.b | Full backend suite in Cloud Build | ✅ build b0365150: ALL Phase-18 tests green (`test_report_delivery.py` + cross-tenant deliver/report denial). Only the 4 known pre-existing mail test-harness defects fail (deferred Phase 20 CLOSE-02) |
| 18.c | frontend image rebuild + deploy | ✅ `frontend:20260722-184435` → rev **nestor-frontend-00017-gfr** (build 2e790073, SUCCESS 2m42s; Phase-12 substitutions reused) |
| 18.c smoke | `/intake/$id/report` registered | ✅ SSR 307 → `/auth/login` (auth guard runs ⇒ route in shipped bundle) |
| 18.d | Mail env confirm-only | ✅ `APP_BASE_URL=https://nestor-frontend-1055853212188.europe-west1.run.app`, `NESTOR_ADMIN_EMAIL=mohamed.ajimi@dotto.be`, `RESEND_API_KEY` secret-bound. NOT rotated (Phase-20 chore) |

**No `nestor-migrate` Job run (no migration this phase). Tribunal images untouched.**

## Current Test

[awaiting operator browser/mail session — Step 18.e]

## Tests

### 1. Stage — pre-delivery invisibility (REPORT-02, BLOCKING)
On an `in_research` smoke intake, admin uploads a real PDF in FinalReportBlock.
expected: file stages (open/check/swap possible), status STAYS `in_research`; a CLIENT login sees NO report — `/intake/{id}/report` redirects to /intake, no "View report" CTA on the list.
result: [pending]

### 2. Deliver (REPORT-01)
Admin clicks Deliver → RecipientPicker (results family) → confirm.
expected: status flips to `delivered`; delivery mail arrives in the recipient's locale (NL/FR/EN); CTA deep-links to `/intake/{id}/report`.
result: [pending]

### 3. Client download (REPORT-02)
Log in as a CLIENT member of the space.
expected: intake list shows "View report" → page shows filename/date/size + download button only (no inline viewer); downloaded PDF opens; Phase-19 chat placeholder visible but inert.
result: [pending]

### 4. Replace — silent + re-notify (REPORT-03)
Admin replaces the PDF post-delivery, once silent, once with re-notify.
expected: status STAYS `delivered`; client gets the NEWEST file; re-notify sends a fresh mail.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps

[none recorded yet]

## Failure triage (from runbook § Phase 18)

- deliver 404 / 500 AttributeError → stale api image (should NOT occur: 00038-7jp verified)
- report route browser-404 → stale frontend (should NOT occur: 00017-gfr verified)
- client sees report BEFORE delivery → REPORT-02 breach — STOP, do not accept the phase
- mail never arrives → check nestor-api logs for refuse-send; delivered + NULL `results_link_sent_at` = recoverable via Replace + re-notify
