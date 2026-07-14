---
phase: 11
slug: internationalization-nl-fr-en
status: planned
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-14
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend, authored by construction — dev machine has no Python/Docker; suite runs in Cloud Build). Frontend: vitest for the shared i18n helpers + CI guard script + `npx tsc --noEmit` + UAT. |
| **Config file** | `backend/pyproject.toml` / `backend/tests/conftest.py`; `frontend/package.json` (`vitest`) |
| **Quick run command** | `npx tsc --noEmit` (frontend, in `frontend/`); `npm run test -- src/lib/i18n` (frontend unit); backend tests author-only locally |
| **Full suite command** | Cloud Build suite run (see phase-07 memory: full suite via `gcloud builds submit`) |
| **Estimated runtime** | ~60s (tsc + vitest) / ~10 min (Cloud Build) |

---

## Sampling Rate

- **After every task commit:** Run `npx tsc --noEmit` for frontend tasks; `npm run test -- src/lib/i18n` for the helper tasks; author/extend pytest tests for backend tasks
- **After every plan wave:** Frontend: tsc + i18n vitest + CI guard script locally; backend: tests authored, deferred to Cloud Build
- **Before `/gsd:verify-work`:** Cloud Build full suite must be green; FULL `ci_no_hardcoded_dutch.sh` exits 0
- **Max feedback latency:** 120 seconds (local); Cloud Build deferred

---

## Per-Task Verification Map

*Filled by planner — one row per task with automated verify.*

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 01-T1 | 11-01 | 1 | I18N-01/02 | T-11-SC | Package legitimacy gate before install | checkpoint | human-verify (npmjs.com) | manual | ⬜ pending |
| 01-T2 | 11-01 | 1 | I18N-01 | T-11-01 | Safe interpolation; nl fallback | unit (vitest) | `npm run test -- src/lib/i18n` + `npx tsc --noEmit` | ❌ W0 | ⬜ pending |
| 01-T3 | 11-01 | 1 | I18N-02 | T-11-02 | Additive code; return-no-throw | typecheck | `npx tsc --noEmit` | ❌ W0 | ⬜ pending |
| 01-T4 | 11-01 | 1 | I18N-01 | T-11-01 | CI guard exit-code gate | unit (bash) | `bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test` | ❌ W0 | ⬜ pending |
| 02-T1 | 11-02 | 1 | I18N-02 | T-11-06 | Locale columns; superadmin no-membership | schema (pytest) | Cloud Build (test_schema_shape_locale.py) | ❌ W0 | ⬜ pending |
| 02-T2 | 11-02 | 1 | I18N-02 | T-11-03/04 | Token-derived identity; enum validation | integration (pytest) | Cloud Build (test_me_routes.py) | ❌ W0 | ⬜ pending |
| 02-T3 | 11-02 | 1 | I18N-01 | T-11-05 | Curated code enum; no leak | unit (pytest) | Cloud Build (test_error_codes.py) | ❌ W0 | ⬜ pending |
| 03-T1 | 11-03 | 2 | I18N-01 | T-11-07 | Schema flatten; nl fallback | unit (vitest) | `npm run test -- src/lib/i18n/localizeSchema` + `npx tsc --noEmit` | ❌ W0 | ⬜ pending |
| 03-T2 | 11-03 | 2 | I18N-01/02 | T-11-01 | Form chrome + localized schema | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 03-T3 | 11-03 | 2 | I18N-01 | T-11-01 | Route externalization | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 04-T1 | 11-04 | 2 | I18N-01 | T-11-01/05 | 56-string admin detail | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 04-T2 | 11-04 | 2 | I18N-01/02 | T-11-01 | Chrome switcher + drawer | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 04-T3 | 11-04 | 2 | I18N-02 | T-11-04 | default_locale validated + audited | typecheck + pytest | `npx tsc --noEmit` + Cloud Build (admin-routes test) | ❌ W0 | ⬜ pending |
| 05-T1 | 11-05 | 2 | I18N-01 | T-11-01/05 | Results panel + route | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 05-T2 | 11-05 | 2 | I18N-01 | T-11-01 | AI/artifact + date-locale | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 05-T3 | 11-05 | 2 | I18N-01 | T-11-01 | PDF pre-resolved props | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 06-T1 | 11-06 | 2 | I18N-01/02 | T-11-03 | Pre-login switcher | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 06-T2 | 11-06 | 2 | I18N-01 | T-11-01 | Action page externalize | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 06-T3 | 11-06 | 2 | I18N-02 | T-11-09/10 | SSR-safe boot changeLanguage | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 07-T1 | 11-07 | 2 | I18N-01 | T-11-01/05 | Invite/user management | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 07-T2 | 11-07 | 2 | I18N-01 | T-11-01 | Dialogs + pulse routes | typecheck | `npx tsc --noEmit` | manual/UAT | ⬜ pending |
| 07-T3 | 11-07 | 2 | I18N-01 | T-11-01 | Long-tail + FULL CI guard | unit (bash) | `bash frontend/scripts/ci_no_hardcoded_dutch.sh` + `npx tsc --noEmit` | ❌ W0 | ⬜ pending |
| 08-T1 | 11-08 | 3 | I18N-01/02 | T-11-01 | Locale variants; autoescape ON | pytest | Cloud Build (test_mail_locale.py) | ❌ W0 | ⬜ pending |
| 08-T2 | 11-08 | 3 | I18N-02 | T-11-11/12 | Per-recipient locale; D-16 intact | pytest | Cloud Build (test_mail_locale.py) | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Wave-0 scaffolds are embedded in the Wave-1 foundation plans (11-01 frontend, 11-02 backend) rather
than a separate plan, per the client-render-after-auth model — the shared infra IS the gate.

- [x] Frontend CI guard `frontend/scripts/ci_no_hardcoded_dutch.sh` + negative self-test — 11-01 Task 4 (covers I18N-01)
- [x] Frontend `lib/i18n/date-locale.test.ts` + `error-codes.test.ts` (vitest) — 11-01 Task 2 (covers I18N-01)
- [x] Frontend `lib/i18n/localizeSchema.test.ts` (vitest) — 11-03 Task 1 (covers I18N-01 schema shape)
- [x] Backend `test_schema_shape_locale.py` / `test_me_routes.py` / `test_error_codes.py` — 11-02 (covers I18N-02, error contract)
- [x] Backend `test_mail_locale.py` (recipient-locale render) — 11-08 (covers I18N-02 mail)
- [x] i18n init + provider + LanguageSwitcher (shared infra, blocks parallel externalization) — 11-01 Tasks 2-3
- [x] No new framework install beyond i18next/react-i18next (gated by 11-01 Task 1 human-verify)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| UI renders fully in NL/FR/EN | I18N-01 | No frontend E2E runner; visual/linguistic quality | Switch language via switcher; walk intake form, admin lifecycle, auth pages in all 3 locales |
| Translation quality (FR/EN drafts) | I18N-01 | Human linguistic review (D-12) | User reviews AI-drafted catalogs (UI, form content, mail) in UAT |
| Switcher persistence across devices | I18N-02 | Live IdP + DB | Switch language, re-login elsewhere, verify locale restored |
| Pre-login switcher (FR invitee escapes Dutch) | I18N-02 | Live login page | Open login page, switch to FR, verify page + subsequent auth pages render FR |
| Localized mail rendering | I18N-01 | Live Resend send | Send validation/results/invite mails to FR/EN-pref recipient; verify correct variant per recipient |
| No hydration flash on login page | I18N-01 | Visual | Load login page in FR browser; verify no Dutch→FR flash |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (embedded in 11-01/02/03/08)
- [x] No watch-mode flags
- [x] Feedback latency < 120s (local tsc + vitest); backend deferred to Cloud Build per project norm
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** planner-approved 2026-07-14
