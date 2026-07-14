---
phase: 11-internationalization-nl-fr-en
plan: 03
subsystem: intake-i18n-client
tags: [i18n, intake-schema, localizeSchema, react-i18next, date-fns, language-switcher]
dependency_graph:
  requires:
    - "11-01 (i18n runtime, getDateLocale, LanguageSwitcher, /me seam)"
    - "11-02 (backend serves canonical template unchanged via GET /intakes/templates)"
  provides:
    - "Multi-locale canonical intake schema (label/title/description/help/placeholder as {nl,fr,en}) at backend/app/data/pulse_intake_v1.json"
    - "localizeSchema(schema, lang) load-time flatten to scalar IntakeSchema with nl fallback (frontend/src/lib/i18n/localizeSchema.ts)"
    - "Localized* source types + resolved scalar types in intake-types.ts"
    - "Externalized intake form chrome (IntakeForm/FieldRenderer/FieldDisplay) + both client intake routes"
    - "LanguageSwitcher mounted in the client form header (D-08); intake namespace catalogs filled (85 keys x nl/fr/en)"
  affects:
    - "11-04..11-06 (admin/auth externalization reuse the same t() + getDateLocale pattern)"
    - "11-07/11-08 (phase-gate full Dutch-guard scan; FR/EN tone UAT review, D-12)"
tech_stack:
  added: []
  patterns:
    - "load-time schema flatten (localizeSchema) keeps every schema consumer reading scalar strings — Pitfall 4 blast-radius containment"
    - "pure helpers (validateField, rowCta, formatDate) thread TFunction / read i18n.language singleton since they cannot call hooks"
    - "useMemo(localizeSchema, [schema, i18n.language]) re-resolves the form on language change"
key_files:
  created:
    - frontend/src/lib/i18n/localizeSchema.ts
    - frontend/src/lib/i18n/localizeSchema.test.ts
  modified:
    - backend/app/data/pulse_intake_v1.json
    - frontend/src/lib/intake-types.ts
    - frontend/src/components/intake/IntakeForm.tsx
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/components/intake/FieldDisplay.tsx
    - frontend/src/routes/intake.$id.tsx
    - frontend/src/routes/intake.index.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json
    - frontend/src/locales/en/intake.json
decisions:
  - "intake-types.ts carries BOTH a Localized* SOURCE family and the un-prefixed RESOLVED scalar family; localizeSchema flattens source -> resolved so FieldRenderer/FieldDisplay keep reading field.label as a string (Pitfall 4)"
  - "FieldType gained `boolean` and the resolved shape gained text_placeholder/display_filename/min_length — the canonical JSON already used these attributes; typing them makes tsc honest without behavior change (Rule 3)"
  - "TFunction is imported from `i18next` (not react-i18next, which does not re-export it)"
  - "formatDate in FieldDisplay reads the i18n.language singleton (module-level pure helper cannot call useTranslation); the component-level date call sites use the hook"
metrics:
  duration: "~35 min"
  completed: "2026-07-14T11:58:00Z"
  tasks: 3
  files: 12
---

# Phase 11 Plan 03: Client Intake i18n Summary

The client-facing intake slice is now multi-locale: the canonical schema carries `{nl,fr,en}`
for every display string, `localizeSchema` flattens it to the current locale at load (nl fallback),
the intake form chrome + both client routes render translated copy, the client form header hosts a
persisting LanguageSwitcher, and date formatting follows the active language via `getDateLocale`.

## Tasks Completed

| # | Task | Commit(s) | Result |
|---|------|-----------|--------|
| 1 | Multi-locale canonical JSON + intake-types + localizeSchema (TDD) | 9945c83 (RED), bd837cc (GREEN) | 14-section JSON converted in-place (nl verbatim, fr/en drafted D-12); localizeSchema flattens to scalar with nl fallback; 5/5 tests green; keys/types/option values byte-unchanged |
| 2 | Externalize form chrome + wire localizeSchema + mount switcher | 20177e6 | IntakeForm/FieldRenderer/FieldDisplay externalized; schema localized at load via useMemo(i18n.language); `<LanguageSwitcher persist />` in the form header (D-08); FieldDisplay date-locale swapped |
| 3 | Externalize both client intake routes + intake.index date-locale | af19447 | intake.$id.tsx + intake.index.tsx externalized; intake.index date-fns nl -> getDateLocale (D-04); rowCta threads t |

## Verification

- `npx tsc --noEmit` — clean (exit 0) after each task and at plan end
- `npm run test` full suite — 35/35 green (localizeSchema 5, date-locale 7, error-codes 6, intake-phase 17)
- Canonical JSON parses; `research_questions`/`output_format` option `value`s and every field `key`/`type` byte-unchanged
- No CI Dutch stopword remains in IntakeForm/FieldRenderer/FieldDisplay/intake.$id/intake.index (grep of the guard's stopword set → no matches outside comments)
- intake.json catalog key parity: 85 keys identical across nl/fr/en (no missing variant)
- FieldDisplay + intake.index no longer import `{ nl }` from date-fns/locale; both use `getDateLocale`

## Threat Model Coverage

- **T-11-07 (schema shape change):** mitigated — `localizeSchema` flattens the `{nl,fr,en}` source to the scalar shape at load; the "no raw locale-object survives" test asserts no `nl`/`fr`/`en` keys remain in the resolved schema; nl is the guaranteed fallback.
- **T-11-01 (XSS via string interpolation):** mitigated — all catalog/schema strings pass through React auto-escaping (`escapeValue:false` is safe per the i18n init note); no `dangerouslySetInnerHTML` of any catalog or schema value was added.
- **T-11-08 (template read-only):** accept — only display strings gained variants; no new writable surface.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Typed extra canonical-JSON attributes in intake-types.ts**
- **Found during:** Task 1
- **Issue:** The canonical JSON uses `boolean` field type (`approved` in the validation proposals), `text_placeholder` (radio "other" option), `display_filename` (NDA download) and a top-level `min_length` on a field — none typed in the old `IntakeField`. `localizeSchema`'s option/field spread would not typecheck against a shape missing these.
- **Fix:** Added `boolean` to `FieldType`; added `text_placeholder`/`display_filename`/`min_length` to the resolved `IntakeField`/`FieldOption`. Additive only, no behavior change.
- **Files modified:** frontend/src/lib/intake-types.ts
- **Commit:** bd837cc

**2. [Rule 3 - Blocking] TFunction import source**
- **Found during:** Task 2
- **Issue:** `import { type TFunction } from "react-i18next"` failed tsc — react-i18next does not re-export `TFunction`.
- **Fix:** `import type { TFunction } from "i18next"` in IntakeForm.tsx and intake.index.tsx.
- **Commit:** 20177e6 / af19447

## Known Stubs

None. Every new `t("...")` key exists in all three intake.json catalogs; fr/en are drafted (D-12 — user reviews tone in UAT, not a stub).

## TDD Gate Compliance

- RED: `test(11-03)` 9945c83 — localizeSchema test authored; module absent → suite fails to load (RED confirmed)
- GREEN: `feat(11-03)` bd837cc — localizeSchema.ts + multi-locale JSON; 5/5 pass
- REFACTOR: not needed (no cleanup commit)

## Notes for Orchestrator

- **STATE.md / ROADMAP.md NOT modified** (worktree executor; orchestrator owns those after merge).
- **REQUIREMENTS.md NOT modified**: I18N-01/I18N-02 span plans 11-02..11-08 — mark at phase gate, not per-plan (consistent with 11-01's note).
- Merge note: this plan touches `frontend/src/locales/{nl,fr,en}/intake.json` and `frontend/src/lib/intake-types.ts`. If a sibling Wave-2 plan also fills the intake namespace or edits intake-types, reconcile catalog key sets and the Localized*/resolved type split on merge.
- The FR/EN schema + catalog translations are Claude drafts (D-12) — flag for tone review in the phase UAT.

## Self-Check: PASSED

- Created files exist: frontend/src/lib/i18n/localizeSchema.ts, frontend/src/lib/i18n/localizeSchema.test.ts
- Commits present on worktree-agent-ad8fbf453d761976d: 9945c83, bd837cc, 20177e6, af19447
- Working tree clean before SUMMARY commit; no unexpected file deletions across plan commits
