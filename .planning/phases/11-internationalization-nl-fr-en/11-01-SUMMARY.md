---
phase: 11-internationalization-nl-fr-en
plan: 01
subsystem: frontend-i18n
tags: [i18n, react-i18next, date-fns, api-seam, ci-guard]
dependency_graph:
  requires: []
  provides:
    - "i18next singleton (nl default+fallback, 12 bundled catalogs) at frontend/src/lib/i18n/index.ts"
    - "I18nextProvider mounted in __root.tsx inside QueryClientProvider"
    - "getDateLocale(lang) date-fns resolver (D-04)"
    - "detectLocale() SSR-safe browser detection (D-09)"
    - "ERROR_CODES + resolveErrorKey (D-11 raw fallback)"
    - "getMe/patchLocale /me seam (return-no-throw)"
    - "LanguageSwitcher component (persist prop, LOCALE_STORAGE_KEY export)"
    - "apiFetch failure variant additive code?: string"
    - "frontend/scripts/ci_no_hardcoded_dutch.sh guard (--self-test)"
  affects:
    - "11-02 (backend /me + CodedError contract this seam consumes)"
    - "11-03..11-06 (externalization plans: useTranslation, catalogs, switcher mounts)"
    - "11-07/11-08 (error-code enum growth, phase gate full scan)"
tech_stack:
  added: ["i18next@^26.3.6", "react-i18next@^17.0.9"]
  patterns:
    - "single synchronous i18next instance, bundled catalogs, no http-backend/no detector plugin"
    - "additive ApiResult failure metadata (code) without forking apiFetch"
    - "exit-code-is-the-gate CI guard with embedded --self-test"
key_files:
  created:
    - frontend/src/lib/i18n/index.ts
    - frontend/src/lib/i18n/detect.ts
    - frontend/src/lib/i18n/date-locale.ts
    - frontend/src/lib/i18n/date-locale.test.ts
    - frontend/src/lib/i18n/error-codes.ts
    - frontend/src/lib/i18n/error-codes.test.ts
    - frontend/src/lib/api/me.ts
    - frontend/src/components/LanguageSwitcher.tsx
    - frontend/src/locales/{nl,fr,en}/{common,intake,admin,auth}.json (12 files)
    - frontend/scripts/ci_no_hardcoded_dutch.sh
  modified:
    - frontend/package.json (+ package-lock.json)
    - frontend/tsconfig.json (resolveJsonModule)
    - frontend/src/lib/api/client.ts
    - frontend/src/routes/__root.tsx
decisions:
  - "Language names in the switcher are translated per active locale (plan-literal: 'Frans' in nl UI), not endonyms — user reviews tone in UAT (D-12)"
  - "LOCALE_STORAGE_KEY = 'nestor.preferredLocale' exported from LanguageSwitcher for the 11-06 post-login reconcile"
  - "resolveJsonModule enabled in tsconfig (Rule 3) — required for the 12 bundled catalog imports"
  - "REQUIREMENTS.md untouched: I18N-01/I18N-02 span plans 11-02..11-08; marking complete after the foundation plan alone would be premature (orchestrator/phase gate owns it)"
metrics:
  duration: "~25 min (incl. checkpoint round-trip + worktree recovery)"
  completed: "2026-07-14T09:25:07Z"
  tasks: 4
  files: 22
---

# Phase 11 Plan 01: Frontend i18n Foundation Summary

react-i18next runtime with deterministic nl default/fallback, bundled 12-catalog skeleton, LanguageSwitcher with best-effort PATCH persist, getDateLocale/detectLocale/error-code helpers, additive `code` on apiFetch failures, /me seam, and a self-tested Dutch-stopword CI guard.

## Tasks Completed

| # | Task | Commit(s) | Result |
|---|------|-----------|--------|
| 1 | Package legitimacy gate + install | 1f03ec5 | checkpoint:human-verify APPROVED by user; i18next@^26.3.6 + react-i18next@^17.0.9 installed; NO languagedetector plugin; React 19 peer OK (react >= 16.8.0) |
| 2 | i18n runtime (TDD) | 8bd6c44 (RED), a72b7fa (GREEN) | singleton init + provider mount + detect/date-locale/error-codes + 12 catalogs; 13/13 vitest green, tsc clean |
| 3 | Switcher + /me seam + code extraction | 547d98f | ApiResult failure gains `code?: string`; detail path byte-identical; getMe/patchLocale return-no-throw; switcher NOT mounted (by design) |
| 4 | Dutch-string CI guard | a4c95ad | `--self-test` exits 0 (planted offender → non-zero); no count-construct; exemptions per plan |

## Verification

- `npx tsc --noEmit` — clean (exit 0)
- `npm run test -- src/lib/i18n` — 13/13 green; full suite 30/30 (intake-phase characterization unaffected)
- `bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test` — exit 0
- `grep -n 'grep -c' frontend/scripts/ci_no_hardcoded_dutch.sh` — no match
- Plain guard scan exits 1 as EXPECTED (source still Dutch until 11-03..11-06; phase gate runs it after Wave 2)
- All 12 catalog JSONs parse (imported by index.ts under tsc + vitest)

## TDD Gate Compliance

- RED: `test(11-01)` 8bd6c44 (both suites fail — modules absent)
- GREEN: `feat(11-01)` a72b7fa (13/13 pass)
- REFACTOR: not needed (no cleanup commit)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Enabled `resolveJsonModule` in frontend/tsconfig.json**
- **Found during:** Task 2
- **Issue:** tsconfig (moduleResolution Bundler) had no `resolveJsonModule`; the 12 catalog JSON imports in `lib/i18n/index.ts` would fail `tsc --noEmit`
- **Fix:** added `"resolveJsonModule": true` (additive, safe)
- **Files modified:** frontend/tsconfig.json
- **Commit:** a72b7fa

### Execution Environment Recovery (not a plan deviation)

My worktree (`agent-ab2afac3a08b2cdf4`) and branch were removed after the Task 1 checkpoint return; the continuation resumed with cwd on the main repo (`master`). A sibling worktree (`agent-a2b0c46c6a698eb31`, plan 11-02, uncommitted backend changes) was NOT touched. Recovery: recreated the worktree at the original path with the original branch name `worktree-agent-ab2afac3a08b2cdf4` from base `0cb51b4`, then executed all tasks there. Zero commits landed on protected refs.

## Known Stubs (intentional)

| Stub | File | Reason / resolved by |
|------|------|----------------------|
| `{}` empty catalogs | src/locales/{nl,fr,en}/{intake,admin,auth}.json (9 files) | Per plan — externalization plans 11-03..11-06 fill them; nl is guaranteed fallback |
| LanguageSwitcher unmounted | frontend/src/components/LanguageSwitcher.tsx | Per plan — mounts land in 11-03/04/06 |
| `/me`, `/me/locale` endpoints do not exist yet | frontend/src/lib/api/me.ts | Backend lands in 11-02 (same wave); patchLocale failure is ignored by design (D-10) until then |

## Notes for Orchestrator

- **REQUIREMENTS.md deliberately NOT updated**: I18N-01/I18N-02 are phase-spanning (frontmatter lists them on multiple plans incl. 11-02); marking them complete after this foundation plan would be premature and would conflict with the parallel 11-02 branch. Mark at phase gate.
- Merge note: `frontend/tsconfig.json` and `frontend/package.json`/`package-lock.json` changed here — low conflict risk with 11-02 (backend-only).

## Self-Check: PASSED

- All 10 created source files + guard script exist on disk
- Commits 1f03ec5, 8bd6c44, a72b7fa, 547d98f, a4c95ad present on `worktree-agent-ab2afac3a08b2cdf4`
- Working tree clean before SUMMARY commit; no file deletions across plan commits
