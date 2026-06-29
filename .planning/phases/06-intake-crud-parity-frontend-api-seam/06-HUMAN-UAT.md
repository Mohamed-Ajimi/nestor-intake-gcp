---
status: partial
phase: 06-intake-crud-parity-frontend-api-seam
source: [06-VERIFICATION.md]
started: 2026-06-29T00:00:00Z
updated: 2026-06-29T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Space switcher behavior — superadmin sees KLANT switcher, user sees nothing
expected: >
  As SUPERADMIN: KLANT switcher appears below logo, above nav. Selecting a client
  re-filters the intake list in place (no navigation); label shows org name. Reload
  preserves selection. Selecting 'Alle klanten' restores all spaces (subtitle reads
  'Alle Pulse intakes.'). As USER: switcher is ABSENT from the DOM entirely (inspect
  element — not just hidden). Subtitle reads 'Alle Pulse intakes.' (no activeSpaceId set).
  Backend now honors the ?space_id param for superadmin so the re-filter has a real effect.
result: [pending]

### 2. Authenticated user intake journey — 06-09 Task 4
expected: >
  USER logs in at /intake and sees only their own space's intakes (no Klant column,
  no switcher). Opens a draft, fills a section, clicks Volgende — one save fires and
  progress is preserved. Submit transitions to submitted. For a validated_by_client or
  decomposed intake, 'Bekijk resultaat' renders the read-only FieldDisplay with no
  ResearchResultsPanel/ContextPackBlock. For a draft, /intake/$id/results redirects
  back to the fill route. Note: routeTree.gen.ts regen recommended before this test
  (see deferred-items.md).
result: [pending]

## Summary

total: 2
passed: 0
issues: 0
pending: 2
skipped: 0
blocked: 0

## Gaps
