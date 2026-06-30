---
status: partial
phase: 06-intake-crud-parity-frontend-api-seam
source: [06-VERIFICATION.md]
started: 2026-06-29T00:00:00Z
updated: 2026-06-30T00:00:00Z
---

## Current Test

Fill → save-as-you-go → submit walkthrough (carried — to be done alongside Phase 7 AI testing).

## Tests

### 1. Space switcher behavior — superadmin sees KLANT switcher, user sees nothing
expected: >
  As SUPERADMIN: KLANT switcher appears below logo, above nav. Selecting a client
  re-filters the intake list in place (no navigation); label shows org name. Reload
  preserves selection. Selecting 'Alle klanten' restores all spaces (subtitle reads
  'Alle Pulse intakes.'). As USER: switcher is ABSENT from the DOM entirely (inspect
  element — not just hidden). Subtitle reads 'Alle Pulse intakes.' (no activeSpaceId set).
  Backend now honors the ?space_id param for superadmin so the re-filter has a real effect.
result: passed — superadmin selected a client and created an intake INTO that space; the
  intake then showed for that client/user and only for them. Space scoping + the
  active-space switcher + per-tenant visibility confirmed live (2026-06-30).

### 2. Authenticated user intake journey — 06-09 Task 4
expected: >
  USER logs in at /intake and sees only their own space's intakes (no Klant column,
  no switcher). Opens a draft, fills a section, clicks Volgende — one save fires and
  progress is preserved. Submit transitions to submitted. For a validated_by_client or
  decomposed intake, 'Bekijk resultaat' renders the read-only FieldDisplay with no
  ResearchResultsPanel/ContextPackBlock. For a draft, /intake/$id/results redirects
  back to the fill route.
result: partial — USER sees only their own space's intake (visibility/isolation confirmed
  live 2026-06-30). Fill → save-as-you-go → Volgende → submit (and results/redirect) NOT
  yet walked through; deferred by the user to the Phase 7 AI-testing pass. Mechanism is
  built and the backend create/answers/templates endpoints are verified live.

## Summary

total: 2
passed: 1
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps

- CARRIED: complete the fill → save-as-you-go → submit (+ results/redirect) live
  walkthrough for the authenticated user during Phase 7 testing. Not AI-gated — the form
  is human-filled; the AI only processes answers after submit.
