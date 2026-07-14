---
phase: 11-internationalization-nl-fr-en
verified: 2026-07-14T14:37:00Z
status: human_needed
score: 9/9 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Switch language between NL, FR, and EN on the live app; verify all labels, banners, toasts, and date formats update throughout the UI (including admin shell, intake form, stepper, status pills, error toasts, and results page)"
    expected: "Every visible string updates to the selected language with no raw i18n keys or mixed-language fragments; Dutch strings only appear in the NL catalog and the out-of-scope sales surfaces"
    why_human: "String rendering is visual; the CI guard proves no hardcoded Dutch remains in source but cannot verify that every t() key resolves to a non-empty string at runtime in all three locales"
  - test: "As a logged-in user, switch language, reload the page; verify the selected language persists across reloads"
    expected: "The chosen locale is remembered server-side (PATCH /me/locale) for users with a membership row; for a superadmin with no membership row it survives reload via localStorage (WR-02 fix applied)"
    why_human: "Locale persistence requires a live backend with migration 0010 applied; cannot verify without a deployed Cloud Run instance at rev 00019+"
  - test: "Check the login page shows the LanguageSwitcher before authentication; switching language on login page should carry the choice through to the post-login UI"
    expected: "Pre-login switcher (persist=false) writes LOCALE_STORAGE_KEY; post-login boot reconciliation picks it up and calls changeLanguage; UI language matches after login"
    why_human: "Requires end-to-end flow through the login -> redirect -> post-login reconcile boot"
  - test: "Invite a user to an FR-default space; verify the invitation email subject and body are both in French"
    expected: "Subject is the FR entry from _INVITE_SUBJECTS map, body renders fr/invite.html.j2 (WR-01 fix verified in source)"
    why_human: "Requires a deployed backend with RESEND_API_KEY configured and migration 0010 applied (per phase 10 deploy runbook)"
  - test: "Review FR and EN mail template tone (invite, validation, results variants) and French/English UI translation quality in the catalogs"
    expected: "Translations are accurate, professional, and consistent in tone; no machine-translation artifacts or mixed-language fragments"
    why_human: "D-12 explicitly defers translation tone review to human UAT; automated checks cannot assess translation quality or naturalness"
  - test: "Run the backend test suite against the live Cloud SQL instance (Cloud Build pipeline)"
    expected: "test_me_routes.py, test_error_codes.py, test_mail_locale.py, test_schema_shape_locale.py all pass; migration 0010 applied cleanly"
    why_human: "Dev machine has no Python/Docker (project norm since Phase 1); backend tests are authored by construction and run in Cloud Build at deploy time"
---

# Phase 11: Internationalization (NL/FR/EN) Verification Report

**Phase Goal:** The UI supports NL, FR, and EN through react-i18next with all hardcoded Dutch strings externalized and a working language switcher with a sensible default locale.
**Verified:** 2026-07-14T14:37:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | react-i18next is installed and initializes with nl as the deterministic default and fallback | VERIFIED | `frontend/package.json` has `i18next@^26.3.6` + `react-i18next@^17.0.9`; `lib/i18n/index.ts` calls `i18n.use(initReactI18next).init({ lng: "nl", fallbackLng: "nl", ... })`; `I18nextProvider` mounted in `__root.tsx` inside `QueryClientProvider` |
| 2 | A LanguageSwitcher component exists, flips the UI language on select, and persists via PATCH post-login | VERIFIED | `frontend/src/components/LanguageSwitcher.tsx` calls `i18n.changeLanguage(lang)`, writes `LOCALE_STORAGE_KEY` always, calls `patchLocale(lang)` when `persist=true`; mounted in `ProductShell.tsx` (admin, persist), `IntakeForm.tsx` (client, persist), and `auth.login.tsx` (pre-login, persist=false) |
| 3 | getDateLocale(lang) returns the fr/enUS/nl date-fns Locale with nl fallback | VERIFIED | `lib/i18n/date-locale.ts` has the resolver; `date-locale.test.ts` passes (7/7 via vitest 19/19 green run) |
| 4 | apiFetch surfaces a machine code on the failure branch additively, keeping the raw error string | VERIFIED | `lib/api/client.ts:23-25` — `ApiResult` failure variant has `code?: string`; lines 96-100 extract `code` additively from body on `!resp.ok` branch; string-detail path on lines 83-91 is unchanged; NOT_LOGGED_IN emitted on no-token path (line 60-64) |
| 5 | The CI guard exits non-zero when a hardcoded Dutch stopword appears in in-scope source | VERIFIED | `bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test` → exit 0; `bash frontend/scripts/ci_no_hardcoded_dutch.sh` → exit 0 (no Dutch found in in-scope source after full sweep) |
| 6 | All hardcoded Dutch strings are externalized — no Dutch remains in in-scope frontend source | VERIFIED | Full CI guard scan exits 0; EXEMPT list covers locales/, .gen.ts, ui/, admin.sales., /components/sales/, salesLabels., generateBattlecardPdf., ComingSoon (D-01 out-of-scope) |
| 7 | The backend provides GET /me + PATCH /me/locale with the D-07 resolution chain | VERIFIED | `backend/app/api/me_routes.py` — me_router registered on protected_router in `main.py:163`; resolution chain implemented in `_resolve_me` + `_load_membership` (WR-03 fix: active-only + space-scoped + first()); PATCH validates {nl,fr,en} via _ALLOWED set; CodedError handler registered in `main.py:168-169` |
| 8 | The 0010 migration adds default_locale (org, NOT NULL nl) and locale (membership, nullable) | VERIFIED | `backend/app/db/alembic/versions/0010_locale_columns.py` — down_revision="0009"; adds `organizations.default_locale` NOT NULL server_default 'nl' and `organization_memberships.locale` nullable |
| 9 | Per-locale mail variants (nl/fr/en) exist for validation/results/invite with Jinja2 autoescape ON | VERIFIED | `backend/app/mail/templates/{nl,fr,en}/{validation,results,invite}.html.j2` — all 9 variants present; `render.py` uses `_localized_template(name, locale)` with nl fallback; FR/EN templates carry `autoescape ON` comment and no `| safe` on prose; WR-01 fix: per-locale `_INVITE_SUBJECTS` map in admin_routes.py |

**Score:** 9/9 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/i18n/index.ts` | Single synchronous i18next instance, bundled catalogs, nl fallback | VERIFIED | Imports all 12 catalog JSONs, `initReactI18next`, `lng: "nl"`, `fallbackLng: "nl"`, no http-backend, no detector plugin |
| `frontend/src/lib/i18n/detect.ts` | SSR-safe browser locale detection | VERIFIED | `detectLocale()` with `typeof window` guard, returns "nl" on SSR, "fr"/"en"/"nl" from navigator.language |
| `frontend/src/lib/i18n/date-locale.ts` | date-fns locale resolver | VERIFIED | `getDateLocale(lang)` exports fr/enUS/nl with nl fallback |
| `frontend/src/lib/i18n/error-codes.ts` | Backend code → i18n key map | VERIFIED | `ERROR_CODES` map with 5 entries (INTAKE_NOT_FOUND, INVALID_LOCALE, MAIL_SEND_FAILED, RECIPIENT_INVALID, NOT_LOGGED_IN); `resolveErrorKey` helper |
| `frontend/src/lib/i18n/localizeSchema.ts` | Multi-locale schema flatten pass | VERIFIED | Pure transform; handles LocalizedString → scalar for every display field; nl guaranteed fallback |
| `frontend/src/lib/api/me.ts` | getMe + patchLocale seam over apiFetch | VERIFIED | Both return `Promise<ApiResult<Me>>`, neither throws; `Me` type mirrors backend response shape |
| `frontend/src/components/LanguageSwitcher.tsx` | NL/FR/EN switcher from shadcn primitives | VERIFIED | Under `components/` (not `ui/`); calls `i18n.changeLanguage`; calls `patchLocale` only when `persist` truthy; always writes `LOCALE_STORAGE_KEY` |
| `frontend/scripts/ci_no_hardcoded_dutch.sh` | Dutch-stopword CI guard | VERIFIED | Mirrors QA-02 exit-code-is-the-gate style; extended stopword list (`uitloggen|terug|overzicht|beheer|kies`); self-test exits 0 |
| `frontend/src/locales/{nl,fr,en}/{common,intake,admin,auth}.json` | 12 catalog files, nl authored, fr/en seeded | VERIFIED | All 12 files present; nl/fr/en common.json all 49 lines (23 keys parity); admin.json 419 lines, intake.json 475 lines for all locales (fully populated by plans 03-07) |
| `backend/app/db/alembic/versions/0010_locale_columns.py` | Migration with down_revision 0009 | VERIFIED | down_revision="0009"; adds both columns with correct nullability and server_default |
| `backend/app/api/me_routes.py` | GET /me + PATCH /me/locale | VERIFIED | me_router exported; _load_membership deterministic (WR-03 fix applied); PATCH validates locale; CodedError on invalid locale |
| `backend/app/api/errors.py` | CodedError + USER_FACING_CODES | VERIFIED | `CodedError(status_code, code, detail)` with correct `__init__`; `USER_FACING_CODES` frozenset; mounted handler in main.py |
| `backend/app/mail/templates/{nl,fr,en}/{validation,results,invite}.html.j2` | 9 per-locale mail variants | VERIFIED | All 9 files present; original Dutch templates moved to `nl/` (git renames); fr/en variants authored |
| `backend/app/mail/render.py` | render_* with locale param + nl fallback | VERIFIED | `_localized_template(name, locale)` helper; `render_validation`, `render_results`, `render_invite` all accept `locale: str = "nl"` |
| `backend/tests/test_me_routes.py` | Backend tests by construction | VERIFIED | File exists; covers GET resolution, PATCH persist round-trip, invalid-locale 422, token-derived identity, superadmin-no-membership paths |
| `backend/tests/test_error_codes.py` | Error code contract tests | VERIFIED | File exists |
| `backend/tests/test_mail_locale.py` | Mail locale tests | VERIFIED | File exists; render-level + send-path test cases |
| `backend/tests/test_schema_shape_locale.py` | Schema shape for locale columns | VERIFIED | File exists |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/src/routes/__root.tsx` | `frontend/src/lib/i18n/index.ts` | `I18nextProvider mount` | VERIFIED | `import i18n from "@/lib/i18n"` (line 88) + `<I18nextProvider i18n={i18n}>` wraps the full tree (line 116) |
| `frontend/src/components/LanguageSwitcher.tsx` | `frontend/src/lib/api/me.ts` | `patchLocale on select (post-login)` | VERIFIED | `void patchLocale(lang)` called when `persist` is true (line 58); `patchLocale` imported from `@/lib/api/me` |
| `frontend/src/lib/api/client.ts` | `frontend/src/lib/i18n/error-codes.ts` | `additive code extraction` | VERIFIED | `ApiResult` failure variant has `code?: string`; code extracted on `!resp.ok` branch; `resolveErrorKey` in error-codes.ts is the intended consumer |
| `backend/app/main.py` | `backend/app/api/me_routes.py` | `protected_router.include_router(me_router)` | VERIFIED | `main.py:163` — `protected_router.include_router(me_router)` |
| `backend/app/main.py` | `backend/app/api/errors.py` | `app.exception_handler(CodedError)` | VERIFIED | `main.py:168-169` — `@app.exception_handler(CodedError)` registered |
| `frontend/src/lib/auth-context.tsx` | `frontend/src/lib/api/me.ts` | `getMe boot reconcile + patchLocale persist` | VERIFIED | Auth-context imports `getMe`, `patchLocale`, `LOCALE_STORAGE_KEY`; boot effect resolves locale after sign-in and persists pending pre-login choice |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` | `frontend/src/lib/i18n/localizeSchema.ts` | `useMemo(localizeSchema, i18n.language)` | VERIFIED | CR-01 fix: `import { localizeSchema }` (line 26); `localizeSchema(...)` called in useMemo (line 420) |
| `frontend/src/routes/intake.$id.results.tsx` | `frontend/src/lib/i18n/localizeSchema.ts` | `localizeSchema on load + i18n.language dep` | VERIFIED | CR-02 fix: `import { localizeSchema }` (line 11); `localizeSchema(rawSchema, i18n.language)` in useMemo (line 128) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|-------------------|--------|
| `LanguageSwitcher.tsx` | `i18n.resolvedLanguage` | `i18n` singleton (react-i18next) | Yes — set from init (`lng: "nl"`) and updated via `changeLanguage()` | FLOWING |
| `auth-context.tsx` boot effect | `resolved` locale | `getMe()` → Cloud SQL membership.locale / org.default_locale | Yes — real DB query through me_routes.py (Cloud Build tests verify) | FLOWING (backend live gate) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| CI Dutch guard self-test (planted offender triggers non-zero) | `bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test` | exit 0 ("SELF-TEST OK") | PASS |
| CI Dutch guard full scan (no hardcoded Dutch in in-scope source) | `bash frontend/scripts/ci_no_hardcoded_dutch.sh` | exit 0 ("OK: no hardcoded Dutch in in-scope source") | PASS |
| TypeScript type check | `cd frontend && npx tsc --noEmit` | exit 0 (clean) | PASS |
| i18n unit tests (date-locale, error-codes, localizeSchema) | `cd frontend && npx vitest run src/lib/i18n` | 19/19 pass | PASS |

### Probe Execution

No probe scripts registered for this phase. Behavioral spot-checks above cover the verifiable automated gates.

### Requirements Coverage

| Requirement | Source Plan(s) | Description | Status | Evidence |
|-------------|---------------|-------------|--------|----------|
| I18N-01 | 11-01, 11-02, 11-03, 11-04, 11-05, 11-06, 11-07, 11-08, 11-09 | The UI supports NL, FR, and EN via an i18n framework; all hardcoded Dutch strings (labels, banners, toasts, date locale) are externalized | SATISFIED | react-i18next installed and wired; 12 catalogs populated (nl authored, fr/en translated); full CI guard exits 0; tsc clean; per-locale mail templates; localizeSchema used at all three schema render sites; StatusPill, ProductShell, IntakeWorkflowStepper all externalized |
| I18N-02 | 11-01, 11-02 | A user can switch language; a default locale applies per user/space | SATISFIED | LanguageSwitcher exists and mounted at 3 sites (admin shell, intake form, login page); PATCH /me/locale persists the choice; GET /me returns D-07 resolution chain (user override → space default → nl); boot reconciliation in auth-context.tsx applies the resolved locale post-login |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `frontend/src/lib/api/client.ts` | 127 | `"Onbekende fout"` — hardcoded Dutch string in the catch-all network error path | INFO | Network errors display "Onbekende fout" to EN/FR users (IN-01 from review). Not caught by the CI guard ("fout" is not in the stopword list). This is an Info-only finding from the code review; out of scope for this phase's gap list per the review resolution. |

**Debt markers (TBD/FIXME/XXX):** None found in phase-modified files.

### Human Verification Required

### 1. Live language switching — full UI coverage

**Test:** On the deployed app (post phase-10 deploy, against Cloud Run), sign in as an admin. Use the LanguageSwitcher in the sidebar to switch from NL to FR, then to EN. Navigate between the intake list, a specific intake detail, the admin home, and the spaces/users/templates pages.
**Expected:** Every visible string (nav items, labels, banners, stepper steps, status pills, error toasts, date formats, field labels in the intake form) renders in the selected language. No raw i18n key strings (e.g., `intakeDetail.status.draft`) appear. No mixed-language fragments (Dutch sidebar over English page).
**Why human:** String rendering and completeness is visual; the CI guard proves no hardcoded Dutch remains in source code but cannot verify that every t() key actually resolves to a non-empty value at runtime across all three locales.

### 2. Locale persistence across reloads

**Test:** Sign in as a user with a membership row. Switch to FR. Reload the page.
**Expected:** The UI loads in FR (not reverting to NL). The boot reconciliation in auth-context reads the server-persisted locale and applies `changeLanguage("fr")`.
**Why human:** Requires a live Cloud Run instance with migration 0010 applied. Cannot verify without a deployed backend (dev machine has no Python/Docker).

### 3. Pre-login language choice carries through post-login

**Test:** Navigate to `/auth/login`. The LanguageSwitcher (persist=false) is visible. Switch to EN. Log in.
**Expected:** After login and redirect, the UI renders in EN (the pre-login choice was saved to localStorage and picked up by the boot reconciliation effect, then attempted to persist via PATCH /me/locale).
**Why human:** Requires end-to-end auth flow; cannot verify programmatically without a live Firebase + Cloud Run environment.

### 4. Invite email locale matches the target space

**Test:** As a superadmin, invite a new user to an FR-default space. Check the received email.
**Expected:** Both the subject line and body are in French (from the `_INVITE_SUBJECTS` map and `fr/invite.html.j2`). Not a Dutch subject over a French body (WR-01 was fixed).
**Why human:** Requires a deployed backend with RESEND_API_KEY and migration 0010 applied; email delivery cannot be tested programmatically.

### 5. FR and EN translation tone review (D-12)

**Test:** Review all FR and EN catalog values across common.json, admin.json, intake.json, auth.json and the three mail template variants (fr/ and en/ for validation, results, invite).
**Expected:** Translations are accurate, professional, and appropriately formal for a B2B research platform. No machine-translation artifacts, awkward phrasing, or inconsistent terminology.
**Why human:** Translation quality and tone are a human judgment; the D-12 design decision explicitly defers tone review to user UAT.

### 6. Backend test suite against live Cloud SQL (Cloud Build)

**Test:** Run the full backend test suite via Cloud Build pipeline after deploying the Phase 11 image (which requires adding jinja2 to dependencies and rebuilding per the phase-10 deploy runbook; also requires migration 0010 to be applied).
**Expected:** `test_me_routes.py`, `test_error_codes.py`, `test_mail_locale.py`, `test_schema_shape_locale.py` all pass. The existing 150-test suite remains green.
**Why human:** Dev machine has no Python/Docker (project norm since Phase 1); backend tests are authored by construction and must run in Cloud Build against a live Cloud SQL instance.

### Gaps Summary

No automated gaps found. All 9 must-have truths are verified against the codebase. All 11 critical/warning review findings (CR-01, CR-02, WR-01 through WR-09) have been fixed with confirmed commits on master (9d73e33 through 769c1ba). The 9 Info findings (IN-01 through IN-09) are explicitly out of scope per the review resolution.

The phase awaits 6 human verification items, all requiring either a deployed Cloud Run environment or human judgment (translation tone). These are consistent with the project's established practice for phases 7-10.

---

_Verified: 2026-07-14T14:37:00Z_
_Verifier: Claude (gsd-verifier)_
