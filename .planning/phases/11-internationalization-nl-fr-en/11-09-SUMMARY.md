---
phase: 11-internationalization-nl-fr-en
plan: 09
subsystem: frontend-i18n
tags: [i18n, react-i18next, ci-guard, phase-gate, common-namespace]

requires:
  - phase: 11-01
    provides: "i18next singleton, common.json catalogs, resolveErrorKey/error-codes map, CI Dutch-string guard"
  - phase: 11-03
    provides: "intake form/schema externalization (sibling — disjoint files)"
  - phase: 11-04
    provides: "admin ClientDetailDrawer/ProductShell/intakes.$id externalization (sibling — disjoint files)"
  - phase: 11-05
    provides: "ResearchResultsPanel display-string externalization + deferred mode-discriminant note"
  - phase: 11-06
    provides: "auth-context/auth routes externalization (sibling — disjoint files)"
  - phase: 11-07
    provides: "admin routes/dialogs externalization (sibling — disjoint files)"
provides:
  - "Long-tail common-namespace keys (workflow.*, accessDenied.*, comingSoon.badge, actions.save, errors.notLoggedIn) in nl/fr/en"
  - "FULL CI Dutch-string guard exits 0 across all in-scope frontend source (I18N-01 phase gate closed)"
  - "ResearchResultsPanel mode discriminant renamed klant → client (stopword removed at source, no guard exemption needed)"
  - "NOT_LOGGED_IN error code wired into the D-11 error-code map"
affects:
  - "11-10+ / phase verification (the whole-tree no-hardcoded-Dutch property is now provably true)"
  - "Any caller of ResearchResultsPanel passing mode= (must use \"client\" not \"klant\" — no external caller does today)"

tech-stack:
  added: []
  patterns:
    - "Module-level label arrays carry labelKey (not label); component resolves via t() at render (IntakeWorkflowStepper.STEPS)"
    - "Cross-namespace key reference from a component bound to another namespace: t(\"common:actions.save\") from useTranslation(\"admin\")"
    - "Client-side (no-backend-code) error surfaced as a stable machine code (NOT_LOGGED_IN) + English raw fallback, translated at the toast via resolveErrorKey"
    - "Path-based guard EXEMPT extension for D-01 out-of-scope surfaces (sales/, salesLabels, generateBattlecardPdf, ComingSoon) — never weaken the stopword PATTERN"
    - "Residual Dutch in code comments rewritten to English (comments are not display; keeps the guard green without exemptions)"

key-files:
  created: []
  modified:
    - frontend/src/locales/nl/common.json
    - frontend/src/locales/fr/common.json
    - frontend/src/locales/en/common.json
    - frontend/src/components/intake/IntakeWorkflowStepper.tsx
    - frontend/src/components/intake/ResearchResultsPanel.tsx
    - frontend/src/lib/api/client.ts
    - frontend/src/lib/i18n/error-codes.ts
    - frontend/src/lib/i18n/error-codes.test.ts
    - frontend/src/lib/auth-context.tsx
    - frontend/src/lib/intake-phase.ts
    - frontend/src/routes/admin.tsx
    - frontend/src/routes/admin.index.tsx
    - frontend/src/routes/admin.pulse.clients.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/routes/admin.spaces.tsx
    - frontend/src/routes/admin.templates.tsx
    - frontend/src/routes/auth.login.tsx
    - frontend/src/routes/__root.tsx
    - frontend/scripts/ci_no_hardcoded_dutch.sh

decisions:
  - "The mode: 'admin' | 'klant' discriminant (11-05 deferred item) is RENAMED to 'admin' | 'client' rather than exempted — the value is confined to ResearchResultsPanel and no external caller passes 'klant', so the rename is fully in-scope and removes the stopword at source (cleaner than a targeted exemption, per flagged-item #1 guidance)"
  - "Sales surfaces (components/sales/*, salesLabels.ts, generateBattlecardPdf.ts) and coming-soon placeholders (ComingSoonPage) are D-01 out-of-scope (stay Dutch); the guard's PATH-based EXEMPT regex was strengthened to cover them (the stopword word list is untouched)"
  - "Residual Dutch inside code comments (not display text) was rewritten to English rather than exempted — keeps the guard genuinely green with no word-list weakening"
  - "client.ts signed-out error emits code NOT_LOGGED_IN + English raw fallback, resolved to common:errors.notLoggedIn at the toast (D-11 error-code contract) — a non-React module cannot call useTranslation"

metrics:
  duration: ~40min
  completed: 2026-07-14

requirements-completed: [I18N-01]
---

# Phase 11 Plan 09: Long-tail common sweep + full CI Dutch-guard gate Summary

**Swept the long-tail small-hit source files into the `common` namespace, renamed the `klant` mode discriminant to `client`, rewrote residual Dutch code comments to English, and drove the FULL CI Dutch-string guard to exit 0 across all in-scope frontend source — closing the I18N-01 whole-tree "no hardcoded Dutch" phase gate.**

## Performance

- **Duration:** ~40 min
- **Completed:** 2026-07-14
- **Tasks:** 1
- **Files modified:** 19 (3 catalogs + 15 source + 1 guard script)

## Accomplishments

- **Display strings externalized to `common`:**
  - `IntakeWorkflowStepper.tsx` — six step labels (`workflow.steps.*`), the archived notice (`workflow.archivedNotice`) and the draft notice (`workflow.draftNotice`). The module-level `STEPS` array now carries `labelKey` and resolves via `t()` at render (module scope cannot call the hook).
  - `admin.tsx` superadmin access-denied wall — `accessDenied.brand/title/body/logout`.
  - Coming-soon badge in `admin.index.tsx` — `comingSoon.badge`.
  - `DeliveredAtEditor` save button in `admin.pulse.intakes.$id.tsx` — `t("common:actions.save")` (cross-namespace ref from an `admin`-bound `t`).
  - `client.ts` signed-out error — now emits `code: "NOT_LOGGED_IN"` + English raw fallback; added to the D-11 `ERROR_CODES` map → `common:errors.notLoggedIn`, with a matching test.
- **`klant` → `client` discriminant rename** in `ResearchResultsPanel.tsx` (10 literal sites): removes the `\bklant\b` stopword at source. No external caller passes `mode="klant"` (only `AdminResearchResultsPanel` uses the panel, with `mode="admin"`), so the rename is fully contained — no guard exemption required. This closes the 11-05 deferred item cleanly (flagged-item #1).
- **Residual Dutch comments → English** in 8 files (ResearchResultsPanel, auth-context, intake-phase, admin.pulse.clients, admin.pulse.intakes.$id, admin.spaces, admin.templates, auth.login, __root) — comments are not display text; rewriting them keeps the guard green without weakening it.
- **Guard EXEMPT path regex strengthened** for D-01 out-of-scope surfaces: `/components/sales/`, `salesLabels\.`, `generateBattlecardPdf\.`, and `[Cc]oming-?[Ss]oon`. The stopword PATTERN (word list) is unchanged.
- **FR + EN authored** for every new key (D-12); nl/fr/en `common.json` at full key parity (23 keys each).

## Task Commits

1. **Task 1: Long-tail common sweep + FULL CI guard green** — `3225518` (feat)

## Verification

- `bash frontend/scripts/ci_no_hardcoded_dutch.sh` → **exit 0** ("OK: no hardcoded Dutch in in-scope source").
- `bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test` → **exit 0** (planted offender still triggers non-zero; guard mechanics intact — word list not weakened).
- `npx tsc --noEmit` → **exit 0** (clean).
- `npx vitest run src/lib/i18n` → **19/19 pass** (includes the new `NOT_LOGGED_IN` assertion).
- `common.json` key parity: nl 23 == fr 23 == en 23; `nl==fr` and `nl==en` true.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Ran `npm install` in the worktree frontend**
- **Found during:** Setup (before Task 1)
- **Issue:** `frontend/node_modules` was absent in the fresh worktree, so `npx tsc --noEmit` / `vitest` could not run.
- **Fix:** `npm install` in `frontend/` (committed lockfile; no new deps).
- **Files modified:** none (node_modules is gitignored).

**2. [Rule 2 - Missing critical] Guard EXEMPT path regex extended for D-01 out-of-scope surfaces**
- **Found during:** Task 1 (running the authoritative scan)
- **Issue:** The scan flagged sales components/utils (`components/sales/*`, `salesLabels.ts`, `generateBattlecardPdf.ts`) and the `ComingSoonPage` placeholder — all D-01 out-of-scope (stay Dutch) — but the original EXEMPT regex only covered `admin.sales.` route files and kebab `coming-soon`. Without exempting these path surfaces the guard could never reach exit 0 without wrongly translating out-of-scope Dutch.
- **Fix:** Added `/components/sales/`, `salesLabels\.`, `generateBattlecardPdf\.`, `[Cc]oming-?[Ss]oon` to the PATH-based EXEMPT list only. The stopword PATTERN (word list) is untouched, and `--self-test` still passes.
- **Files modified:** `frontend/scripts/ci_no_hardcoded_dutch.sh`
- **Commit:** `3225518`

**3. [Rule 1 - Bug] Leftover display string in a sibling-owned file**
- **Found during:** Task 1
- **Issue:** `admin.pulse.intakes.$id.tsx:1449` ("Opslaan", 11-04's file) and `admin.tsx` access-denied wall (unowned) still contained hardcoded Dutch display text after the sibling waves.
- **Fix:** Externalized both to `common` (`actions.save`, `accessDenied.*`). In-scope as the phase-gate owner.
- **Files modified:** `admin.pulse.intakes.$id.tsx`, `admin.tsx`
- **Commit:** `3225518`

---

**Total deviations:** 3 (1 env bootstrap, 1 guard exemption for out-of-scope surfaces, 1 leftover-string cleanup).
**Impact on plan:** None on scope — Task 1's `<files>` list was explicitly representative; the scan was authoritative and the concrete set differed slightly as the plan anticipated.

## Known Stubs

None introduced. The ResearchResultsPanel `mode="client"` branch is pre-existing phase-gated dead UI (Phase 7+ research surface); this plan only renamed the discriminant literal and touched no runtime behavior.

## Threat Flags

None. Changes are string externalization + a code-literal rename + English comments. No new network endpoint, auth path, or trust-boundary surface. Catalog values render through React auto-escaping (T-11-01); no `dangerouslySetInnerHTML`. The `NOT_LOGGED_IN` code carries no new server detail (T-11-05).

## Self-Check: PASSED

- All 19 modified source files exist on disk (git diff --cached confirmed 19 files at commit time).
- Commit `3225518` present on `worktree-agent-a2a85a641c8a96eaf`.
- Full guard exit 0, self-test exit 0, `tsc --noEmit` exit 0, i18n vitest 19/19, catalog parity 23==23==23.
- No file deletions across the task commit; no untracked files left.

---
*Phase: 11-internationalization-nl-fr-en*
*Completed: 2026-07-14*
