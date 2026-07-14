---
status: partial
phase: 11-internationalization-nl-fr-en
source: [11-VERIFICATION.md]
started: 2026-07-14T14:30:00Z
updated: 2026-07-14T14:30:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live language switching — full UI coverage
expected: With the frontend running against the deployed backend, flip the LanguageSwitcher (admin shell, intake form header, login page) between NL/FR/EN — every label, banner, toast, status pill, date format, and the 14-section intake form content renders in the selected language with no raw i18n keys and no leftover Dutch on FR/EN.
result: [pending]

### 2. Locale persistence across reloads
expected: After deploy + migration 0010: switch language while logged in (member user) → reload / re-login on another browser → language restored from the server (`GET /me`). Superadmin without membership: choice survives reloads via localStorage.
result: [pending]

### 3. Pre-login → post-login locale carry-through
expected: On the login page, switch to FR before authenticating → after login the app stays FR and the choice is persisted to the user's profile (member users).
result: [pending]

### 4. Invite email locale matches target space
expected: Invite a user into a space with default_locale=fr → invite mail (subject AND body) arrives in French; validation/results mails render per-recipient (membership locale → space default → nl). Requires deployed backend + RESEND_API_KEY.
result: [pending]

### 5. FR and EN translation tone review (D-12)
expected: Review the AI-drafted FR/EN catalogs (UI namespaces, intake form content in pulse_intake_v1.json, mail templates) for tone/terminology; correct anything off-brand.
result: [pending]

### 6. Backend test suite in Cloud Build
expected: Full backend suite (incl. new test_me_routes.py, test_error_codes.py, test_schema_shape_locale.py, test_mail_locale.py, duplicate-membership regression test) green in Cloud Build before/at deploy.
result: [pending]

## Summary

total: 6
passed: 0
issues: 0
pending: 6
skipped: 0
blocked: 0

## Gaps
