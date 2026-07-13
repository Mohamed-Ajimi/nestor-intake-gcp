---
status: partial
phase: 10-notifications
source: [10-VERIFICATION.md]
started: 2026-07-14T08:20:00Z
updated: 2026-07-14T08:20:00Z
---

## Current Test

[awaiting human testing — requires the Phase-10 deploy: image rebuild (jinja2/httpx), RESEND_API_KEY secret version, APP_BASE_URL + NESTOR_ADMIN_EMAIL env vars per infra/DEPLOY-RUNBOOK.md Steps 10.1-10.5]

## Tests

### 1. RecipientPicker visual/functional verification (Plan 10-04 checkpoint)
expected: Run the frontend locally (npm, localhost:8081) against the deployed backend. On an awaiting-validation intake, "Verstuur validatie-link" opens the RecipientPicker with the space's active members preselected; a zero-member space shows a disabled send CTA with an "invite someone first" hint; a send shows a success toast on delivery and a Dutch failure toast that keeps the picker open on a failed send (CR-01 fix); both the InviteUserDialog success state and the member-list rows offer a working "send/resend invitation mail" action beside the copy-link fallback.
result: [pending]

### 2. Live invite click-through via /auth/action (Plan 10-05 checkpoint)
expected: Invite a test user and send the invitation mail against the deployed rev (live Identity Platform + RESEND_API_KEY + APP_BASE_URL set). The mailed Firebase action link lands on the branded /auth/action route (Dutch "Kies je wachtwoord", NOT Firebase's hosted page); setting a password redirects to /auth/login and the new password logs in; an expired/reused link shows the friendly "verlopen of ongeldig — vraag een nieuwe link aan" message.
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
