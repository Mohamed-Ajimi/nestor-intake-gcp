---
phase: 11-internationalization-nl-fr-en
plan: 04
subsystem: ui
tags: [i18n, react-i18next, date-fns, fastapi, admin, locale, CodedError]

# Dependency graph
requires:
  - phase: 11-01
    provides: i18n runtime (i18n instance, getDateLocale, resolveErrorKey/ERROR_CODES), LanguageSwitcher, /me seam
  - phase: 11-02
    provides: organizations.default_locale column (0010), me_routes INVALID_LOCALE contract, CodedError
provides:
  - Admin Pulse intake-detail page fully externalized (NL/FR/EN) + date-locale + error-code-mapped toasts
  - LanguageSwitcher mounted in ProductShell admin chrome (D-08)
  - ClientDetailDrawer externalized + date-locale swapped
  - Space create/edit dialog with a NL/FR/EN default_locale selector (D-09/D-10)
  - admin seam (admin.ts) + backend (admin_routes.py) carry, persist, validate & audit default_locale
affects: [11-09 phase-gate Dutch guard, 11-08 admin_routes invite-send, i18n admin surfaces]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Module-level status maps converted to i18n key lookups (t('intakeDetail.status.<value>')) since t() is a hook not available at module scope"
    - "date-fns call sites swapped from static { nl } import to getDateLocale(i18n.language) (D-04)"
    - "ApiResult failure code -> resolveErrorKey -> t(key) with raw server text fallback (D-11)"
    - "Backend CodedError(422, INVALID_LOCALE) reused from 11-02 for admin space locale validation"

key-files:
  created: []
  modified:
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/components/admin/ProductShell.tsx
    - frontend/src/components/admin/ClientDetailDrawer.tsx
    - frontend/src/routes/admin.spaces.tsx
    - frontend/src/components/admin/SpaceFormModal.tsx
    - frontend/src/lib/api/admin.ts
    - backend/app/api/admin_routes.py
    - backend/app/db/admin_repo.py
    - backend/tests/test_admin_routes.py
    - frontend/src/locales/nl/admin.json
    - frontend/src/locales/fr/admin.json
    - frontend/src/locales/en/admin.json

key-decisions:
  - "Space default_locale UI lives in SpaceFormModal.tsx (the real create/edit dialog) not admin.spaces.tsx (Rule 3 deviation — plan referenced the route host but the dialog is a child component)"
  - "LanguageSwitcher mounted for ALL admin users (not superadmin-gated like SpaceSwitcher) — a `user` also needs to pick their display language"
  - "Backend _validate_locale reuses the 11-02 CodedError(422, INVALID_LOCALE) contract; validation runs before any write on both create and update"

patterns-established:
  - "Status/banner/hint domain values stay stable; only display labels are catalog lookups"
  - "Test app builder registers the CodedError handler so 422+coded bodies render in isolation (mirrors main.py)"

requirements-completed: [I18N-01, I18N-02]

# Metrics
duration: 45min
completed: 2026-07-14
---

# Phase 11 Plan 04: Admin Surfaces Internationalization Summary

**Admin Pulse intake-detail (56 strings), ClientDetailDrawer, and space dialog externalized to NL/FR/EN with getDateLocale date formatting; LanguageSwitcher mounted in the admin chrome; and space default_locale wired end-to-end through the admin seam and admin_routes backend with {nl,fr,en} validation + audit.**

## Performance

- **Duration:** ~45 min
- **Completed:** 2026-07-14
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments
- Externalized the highest-density admin file (`admin.pulse.intakes.$id.tsx`): status labels/banners/hints, CTA labels, all toasts/confirms, section/meta headers, and the link rows — with every ApiResult failure branch mapped through `resolveErrorKey` (raw fallback) and all three date-fns sites swapped to `getDateLocale(i18n.language)`.
- Mounted `<LanguageSwitcher persist />` in `ProductShell` beside the space switcher (D-08), available to every admin user.
- Externalized `ClientDetailDrawer` (data + contact fields, project list, toasts) and swapped its date-fns sites to `getDateLocale`.
- Added a NL/FR/EN `default_locale` selector to the space create/edit dialog (`SpaceFormModal`), defaulting new spaces to `nl` and showing the current value on edit.
- Extended the admin seam (`admin.ts`) and the backend (`admin_routes.py` + `admin_repo.py`) so space create/update accept, persist, return, validate ({nl,fr,en} → `CodedError(422, INVALID_LOCALE)`), and audit `default_locale`.
- Authored 5 by-construction admin-routes tests (create/update persist+return, `nl` fallback on omit, invalid-locale 422+coded on both create and update) and registered the `CodedError` handler in the test app builder.
- Filled the `nl/fr/en` `admin.json` catalogs to exact 140-key parity (nl verbatim, fr/en drafted per D-12).

## Task Commits

1. **Task 1: Externalize admin.pulse.intakes.$id.tsx (56 strings) + date-locale swap** - `272a79e` (feat)
2. **Task 2: ProductShell switcher mount + ClientDetailDrawer externalize + date-locale** - `02da144` (feat)
3. **Task 3: Space dialog default_locale field + admin seam + backend field** - `d0c6d9b` (feat)

## Files Created/Modified
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` - Full i18n externalization + getDateLocale + error-code toast mapping
- `frontend/src/components/admin/ProductShell.tsx` - Mounts LanguageSwitcher in admin chrome
- `frontend/src/components/admin/ClientDetailDrawer.tsx` - Externalized + date-locale swapped
- `frontend/src/routes/admin.spaces.tsx` - Externalized space list/table/dialog chrome
- `frontend/src/components/admin/SpaceFormModal.tsx` - Added default_locale selector + externalized
- `frontend/src/lib/api/admin.ts` - Space type + create/update payloads carry default_locale (SpaceLocale)
- `backend/app/api/admin_routes.py` - SpaceView/bodies + create/update accept, persist, validate, audit default_locale
- `backend/app/db/admin_repo.py` - create_space accepts optional default_locale
- `backend/tests/test_admin_routes.py` - 5 default_locale tests + CodedError handler in test app builder
- `frontend/src/locales/{nl,fr,en}/admin.json` - intakeDetail + clientDrawer + spaces + spaceForm catalogs (140 keys each)

## Decisions Made
- The `default_locale` selector lives in `SpaceFormModal.tsx`, the actual create/edit dialog child of `admin.spaces.tsx`. The plan named `admin.spaces.tsx` as the host, but the dialog form is a separate component; editing it was required to fulfill the plan (Rule 3). SpaceFormModal is an admin file not claimed by parallel siblings 11-03/11-06, so touching it is safe.
- LanguageSwitcher is not superadmin-gated (unlike SpaceSwitcher) — every admin user needs a display-language control.
- Module-level status option/banner/hint constants were converted from label-carrying objects to stable value sets, with display strings resolved via `t()` at render (t is a hook, unavailable at module scope).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] default_locale selector implemented in SpaceFormModal.tsx**
- **Found during:** Task 3 (Space dialog default_locale field)
- **Issue:** The plan's `files_modified` and `contains: default_locale` targeted `admin.spaces.tsx`, but that route only renders `<SpaceFormModal>` — the actual name/slug create/edit form (and thus the correct home for a locale field) lives in `frontend/src/components/admin/SpaceFormModal.tsx`, which was not in the declared file list.
- **Fix:** Added the shadcn `Select`-based NL/FR/EN `default_locale` field to `SpaceFormModal.tsx` (default `nl`, shows current on edit) and externalized its strings; `admin.spaces.tsx` was still externalized as planned. The `Space` type + seam flow through `admin.spaces.tsx` as the plan's key_link intended.
- **Files modified:** frontend/src/components/admin/SpaceFormModal.tsx
- **Verification:** `npx tsc --noEmit` passes; the selector renders in the dialog and sends the chosen value through the extended seam.
- **Committed in:** d0c6d9b (Task 3 commit)

**2. [Rule 3 - Blocking] Registered CodedError handler in the admin-routes test app builder**
- **Found during:** Task 3 (backend tests)
- **Issue:** The test's `_build_app` mounts routers on a bare `FastAPI()` with no exception handlers, so a `CodedError` raised by the space handlers would surface as an unhandled 500, not the 422 the invalid-locale tests assert.
- **Fix:** Registered the same `CodedError` -> `{"detail","code"}` JSONResponse handler (mirrors `app/main.py`) inside `_build_app`.
- **Files modified:** backend/tests/test_admin_routes.py
- **Verification:** Authored by construction (no local Python); the handler mirrors the production `main.py` registration verbatim.
- **Committed in:** d0c6d9b (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking)
**Impact on plan:** Both are necessary to deliver the plan's stated behavior (a working locale selector + a testable 422). No scope creep — SpaceFormModal is the plan's intended dialog, just a different filename than listed.

## Issues Encountered
- Backend cannot be executed locally (no Python/Docker on the dev machine, per project memory). All backend edits and the 5 new tests are authored by construction following the existing `test_admin_routes.py` conventions; they run in Cloud Build at the phase gate.

## Verification
- `npx tsc --noEmit` clean (run after each task and at the end).
- All 12 modified files: no residual Dutch UI stopwords in the four externalized TS/TSX files (grep-verified outside comments/code).
- All three `admin.json` catalogs valid JSON at exact 140-key parity (no missing/extra keys across nl/fr/en).
- All 120 static `t()` keys + 5 dynamic-prefix keys used in source resolve against the nl catalog.
- Backend admin-routes default_locale tests authored (Cloud Build at phase gate).

## Known Stubs
None — all wired: the default_locale field persists through the seam to the backend column; catalogs are fully populated.

## Next Phase Readiness
- The admin seam extension (`default_locale` on space create/update + `_space_view`) lands before 11-08's later admin_routes invite-send change (Wave 3), as the plan anticipated.
- Phase-gate CI Dutch guard (11-09) will do the full-scan; this plan's admin-namespace files are clean.

## Self-Check: PASSED

- All three task commits present: `272a79e`, `02da144`, `d0c6d9b`.
- SUMMARY.md created at `.planning/phases/11-internationalization-nl-fr-en/11-04-SUMMARY.md`.
- No modifications to shared orchestrator artifacts (STATE.md / ROADMAP.md).

---
*Phase: 11-internationalization-nl-fr-en*
*Completed: 2026-07-14*
