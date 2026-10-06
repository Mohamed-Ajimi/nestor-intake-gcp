---
phase: quick-261006-jgn
plan: 01
subsystem: intake admin UX + client mail
tags: [tester-feedback, mail, admin-ui, layout, nav]
requires: []
provides:
  - project_name answer seeded on intake create
  - client mails greet the contact_name first name
  - lib/intake-display.ts (objectListTextKey, deriveIntakeHeaderTitle)
  - PULSE_NAV shared nav const
affects:
  - backend/app/api/intake_routes.py (create_intake, _run_intake_send, _send_report_mail)
  - frontend admin intake detail page, manage pages, FieldDisplay
tech-stack:
  added: []
  patterns: [pg_insert ON CONFLICT DO NOTHING seed on request session, ResizeObserver-measured sticky offset]
key-files:
  created:
    - backend/tests/test_mail_greeting.py
    - backend/tests/test_intake_project_name_seed.py
    - frontend/src/lib/intake-display.ts
    - frontend/src/lib/intake-display.test.ts
  modified:
    - backend/app/api/intake_routes.py
    - frontend/src/components/intake/FieldDisplay.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/admin/adminNav.ts
    - frontend/src/components/admin/ProductShell.tsx
    - frontend/src/routes/admin.pulse.tsx
    - frontend/src/routes/admin.users.tsx
    - frontend/src/routes/admin.spaces.tsx
    - .planning/phases/23.5-.../deferred-items.md (DEF-23.5-03-03 -> FIXED; left uncommitted for the orchestrator)
decisions:
  - "project_name seed reads the create BODY value only, never intake.client_name (the 0008 BEFORE-INSERT trigger can mirror the org name into it)"
  - "Mail greeting = first whitespace token of the contact_name answer (localized dicts resolved nl-first via brief._resolve_localized); empty -> \"\" so the template's own team/équipe fallback applies; subjects and project_title unchanged"
  - "Object-list rows take the question path ONLY when a sub-field is keyed `text`; stakeholder rows render every sub-field"
  - "Manage pages pass PULSE_NAV as items; ProductShell's Manage block supplies users/spaces; the items !== ADMIN_NAV guard is kept"
  - "Optional active-link scrollIntoView in the sections nav was SKIPPED: block:nearest would also scroll ProductShell's <main> when the nav sits partly below the fold at page top (page jump on load)"
metrics:
  duration: ~55 min
  completed: 2026-10-06
  tasks: 3
  files: 15
---

# Quick 261006-jgn: Tester feedback — admin UX and mail greeting Summary

Seeded the `project_name` answer from the create screen, made every client mail greet the first name of the `contact_name` answer (or "team"/"équipe" when it is empty), made stakeholder rows show name, role and expectation, set the admin header to "organisation — project", put the full Pulse nav on the manage pages, moved the next-step panel into a full-width block under the step tracker, and made the sections nav stay in view while scrolling.

## Commits

| Task | Commit | Message |
|------|--------|---------|
| 1 | 9b3c290 | fix(261006-jgn): seed project_name answer on create; greet contact first name in client mails |
| 2 | 4f98e9a | fix(261006-jgn): admin stakeholder rows show all fields; header shows organisation — project |
| 3 | 059c58b | feat(261006-jgn): full nav on manage pages; next-step panel above content; sticky sections nav |

## Gate results (exact)

- **Backend, targeted set** (greeting + seed + mail_endpoints + mail_locale + mail_render + report_delivery + intake_routes): **118 passed, 0 failed**.
- **Backend, full suite** (Docker Desktop started for testcontainers): **984 passed, 2 skipped, 0 failed** (39 warnings, 2m47s).
- `grep -v '^\s*#' intake_routes.py | grep -c "first_name=client"` = **0**; `grep -c "first_name=greeting"` = **4**.
- `scripts/ci_no_raw_db_access.sh` — **OK** (the module still imports no raw DB symbol).
- **tsc** `--noEmit`: **0 errors**.
- **vitest** (full): **21 files, 605 tests passed, 0 failed** (includes the 9 new `intake-display.test.ts` cases).
- **i18n audit** `node scripts/i18n-audit.mjs`: **PASS — A/B/C clean, exit 0**, 106 CHECK D advisories. The hits in the files touched here are pre-existing interpolated `t()` calls (line numbers moved) and the ProductShell `alt="Agenic"`. This change adds no copy and no i18n keys.
- Task 2 gates: `sf.type === "longtext"` in FieldDisplay = 0; `objectListTextKey` in FieldDisplay = 2; `deriveIntakeHeaderTitle` in the intake page = 2.
- Task 3 gates: `items={ADMIN_NAV}` in users/spaces = 0/0; `items={PULSE_NAV}` in pulse/users/spaces = 1/1/1; `1fr_272px` = 0; `top-28` = 0; `git diff --stat frontend/src/components/ui/` is empty; `package-lock.json` is unchanged (no `npm install`).
- TDD RED was observed before GREEN for both test files in Task 1 (21 failing, for the expected reasons) and for `intake-display.test.ts` in Task 2 (module missing).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Greeting tests leaked `mail.sent` audit rows, which made `test_mail_endpoints` depend on test order**
- **Found during:** Task 1, targeted run.
- **Issue:** `audit_log` is not RLS-scoped and does not cascade when the organisation is deleted. `test_mail_endpoints::test_timestamp_on_success_only` counts `mail.sent` rows across the whole table. Running the new greeting file first gave it 6 instead of 1.
- **Fix:** the cleanup in `test_mail_greeting.py` now deletes `audit_log` rows for its own `space_id` before deleting the organisation. Re-run: 30/30, and the full suite is green.
- **Files:** backend/tests/test_mail_greeting.py (in commit 9b3c290).

**2. [Formatting] Ran prettier on `intake-display.test.ts`, a Task 2 file**
- The fix went into the Task 3 commit (059c58b) together with `admin.pulse.tsx`. It is formatting only, and the tests were re-run (9/9).
- Pre-existing prettier errors in `NextStepBanner.tsx` were left alone (the count did not go up: 7 at baseline, 6 now). They are out of scope.

### Not done (optional item)
- The optional `scrollIntoView` of the active link in the sections nav was skipped on purpose. With `block: "nearest"` it would also scroll the page's `<main>`, because at the top of the page the nav sits partly below the fold. The result would be a page jump when `activeSection` is first set.

## Notes for the verifier / human check (not run in a browser)

- Nothing was checked in a browser. Layout items 1, 6 and 7 are confirmed only by tsc and the grep gates.
- Things to check by hand: `/admin/users` and `/admin/spaces` show new intake / intakes / clients / search plus the Beheer block, each link once. On the intake detail page, the next-step card sits under the tracker with the text on the left and the buttons on the right at md+, and AI tools and search share the row below it. The section nav stays visible under the sticky header and scrolls on its own when it is long.
- In phases where `NextStepBanner` returns null and neither AI tools nor search apply, the full-width card is an empty bordered strip with `mb-8`. The old rail had the same empty-card behaviour.
- `admin:intakeDetail.unknownClient` is now unused in the intake page. The key was kept, as the plan instructed.

## Threat model check

- T-jgn-01: autoescape stays on, no `| safe` or Markup. A test asserts `&lt;b&gt;x&lt;/b&gt;` and that the raw `<b>x</b>` is absent.
- T-jgn-02: `_contact_first_name` filters on `intake_id` AND `space_id == intake.space_id`.
- T-jgn-03: the seed takes `space_id` from the created intake row and runs on the create's own session and GUC with ON CONFLICT DO NOTHING. A test proves an existing row is not overwritten.
- T-jgn-04: header values go through `pick()` before render; the questions path is unchanged.
- No new network endpoints, auth paths or schema changes (no migration).

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: backend/tests/test_mail_greeting.py, backend/tests/test_intake_project_name_seed.py, frontend/src/lib/intake-display.ts, frontend/src/lib/intake-display.test.ts
- FOUND commits: 9b3c290, 4f98e9a, 059c58b
