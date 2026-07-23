---
task: quick-260723-kjj
title: Exhaustive i18n hardcoded-string sweep
status: complete
tasks_completed: 3
tasks_total: 3
commits:
  - e02985b  fix: translate AI-skills descriptions, History labels, notification bell
  - b2a22ed  refactor: remove redundant context-pack history accordion
  - cd7e63a  feat: add i18n audit script and close 3-way parity gaps
key_files_created:
  - frontend/scripts/i18n-audit.mjs
key_files_modified:
  - frontend/src/components/intake/AISkillsPanel.tsx
  - frontend/src/components/TopBar.tsx
  - frontend/src/components/intake/SkillRunProgress.tsx
  - frontend/src/components/intake/ContextPackBlock.tsx
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/locales/{nl,fr,en}/intake.json
  - frontend/src/locales/{nl,fr,en}/admin.json
  - frontend/src/locales/{nl,fr,en}/common.json
verification:
  audit: PASS (exit 0, A/B/C clean, 107 CHECK D advisories)
  tsc: PASS (0 errors)
  build: PASS (built in 17.95s)
  grep_gate: PASS (zero genuine two-arg i18n fallbacks)
---

# Quick 260723-kjj: Exhaustive i18n Hardcoded-String Sweep — Summary

Eliminated all user-visible hardcoded/untranslated strings from the Nestor Intake operator
flow so an operator running in English no longer sees Dutch fragments in the AI-skills popover,
the History sheet, or the notification bell. Removed the redundant context-pack history
accordion from the center page (runs already appear in the header History sheet). Added a
reusable `i18n-audit.mjs` script (3-way parity + used-key coverage + fallback scan as hard
gates, hardcoded-string scan as advisory) that now exits 0.

This was the operator's SECOND complaint about untranslated strings, so the sweep was driven by
a full audit rather than a spot-fix of the four known offenders.

## Tasks

### Task 1 — Four known offenders + backfill locale keys (commit e02985b)
- **AISkillsPanel**: added `aiSkills.{structure,extract,embeddings,transcribe}Desc` to nl/fr/en
  `intake.json`; dropped the four inline Dutch two-arg fallbacks — the fallbacks were what
  masked the missing keys and shipped the bug.
- **admin.pulse.intakes.$id.tsx**: added `intakeDetail.history.{empty,done,failed,busy}` +
  `intakeDetail.history.skill.*` (six skill-name keys) to nl/fr/en `admin.json`. Deleted the
  module-level Dutch `SKILL_LABELS` const; skill labels now resolve via
  `t(\`intakeDetail.history.skill.${r.skill_name}\`, r.skill_name)`. Status labels
  (✓ voltooid / ✗ mislukt / bezig…) now resolve through `t()`; unknown statuses keep the bare
  `r.status` fallback.
- **TopBar**: added `useTranslation("common")` + `common.notifications.{comingSoon,ariaLabel}`
  to nl/fr/en; bell `title`/`aria-label` now use `t()`.

### Task 2 — Remove context-pack history accordion (commit b2a22ed)
- Removed `historyOpen`/`history` state, `loadHistory` callback, `toggleHistory` fn, the
  `if (history !== null) loadHistory()` line from the status-change effect, and the entire
  inline history `<section>` JSX from `ContextPackBlock.tsx`.
- Kept `loadLatest` + its effect call, `reloadSignal` handling, the questions block, and the
  `viewingPack` modal intact. Effect deps updated (`loadHistory` removed); stale eslint/comment
  references to `loadHistory` cleaned up.
- Pruned now-orphaned `intake.json` `contextPack` keys (`historyToggle`, `loading`, `noRuns`,
  `view`) from nl/fr/en (each verified zero remaining `t("contextPack.<key>")` references).

### Task 3 — Audit script + close every gap (commit cd7e63a)
- Wrote `frontend/scripts/i18n-audit.mjs` (Node ESM, `node:fs` only). Scans `src/` excluding
  `components/ui/`, `routeTree.gen.ts`, `mock-backend/`, `locales/`. Four checks; A/B/C hard-gate
  (exit 1), D advisory. Now exits 0.
- Closed a pre-existing 3-way parity gap the audit surfaced: the entire `intake.research.*`
  namespace (37 keys, used by `ResearchRunProgress.tsx`) and `nextStep.researchConfirm{Title,
  Body,Cancel,Confirm}` (used by `NextStepBanner.tsx`) existed only in nl — backfilled fr + en
  with natural translations.
- Fixed one more genuinely user-visible intake-flow offender the audit found:
  `SkillRunProgress.tsx` "Nestor analyseert" banner (title + body) → new
  `intake.skillRunProgress.{title,body}` keys in nl/fr/en, wired via `useTranslation("intake")`.

## Locale keys added (per namespace)

**intake.json (nl / fr / en):**
- `aiSkills.structureDesc`, `aiSkills.extractDesc`, `aiSkills.embeddingsDesc`, `aiSkills.transcribeDesc`
- `skillRunProgress.title`, `skillRunProgress.body`
- `nextStep.researchConfirmTitle`, `nextStep.researchConfirmBody`, `nextStep.researchConfirmCancel`, `nextStep.researchConfirmConfirm` (fr/en only — already in nl)
- `research.*` full namespace, 37 keys (fr/en only — already in nl): panelTitle, panelBody,
  startingBody, elapsed, cost, currentStage, stageDone, stageRunning, stagePending, stagesTitle,
  completedTitle, completedBody, completedAt, totalCost, duration, failedTitle, failedBody,
  cancelledTitle, cancelledBody, errorLabel, retry, costFallback, dateFallback, download,
  downloadError, lockedTitle, lockedBody, reverify, reverifyError, reverifyStillBroken,
  unverifiedTitle, unverifiedBody, verifyChain
- **Removed** (orphaned, all 3 locales): `contextPack.historyToggle`, `contextPack.loading`,
  `contextPack.noRuns`, `contextPack.view`

**admin.json (nl / fr / en):**
- `intakeDetail.history.empty`, `intakeDetail.history.done`, `intakeDetail.history.failed`, `intakeDetail.history.busy`
- `intakeDetail.history.skill.{apply-intake-skill, structure-answers, extract-insights, generate-embeddings, transcribe-source, context-pack}`

**common.json (nl / fr / en):**
- `notifications.comingSoon`, `notifications.ariaLabel`

## CHECK D advisory findings — resolution

The advisory scan surfaced 107 hits. Resolution:

1. **Fixed (intake operator flow):** `SkillRunProgress.tsx` "Nestor analyseert" banner —
   translated (Task 3, above). This was the only genuinely user-visible hardcoded UI string in
   the intake/admin operator flow that the operator's complaint targeted.
2. **False positives (regex noise):** `"Promise"` (×8) are `Promise<...>` type annotations in
   async code matched by the JSX-text heuristic, not rendered text. `intake.$id.tsx:18` and
   `:114` ("Antwoorden bekijken", "Akkoord — verstuur") are inside `//` code comments, not JSX.
3. **Everything else** is enumerated under Judged Exceptions below.

## Judged Exceptions (intentionally untranslated)

| String(s) | Location | Reason |
|-----------|----------|--------|
| `alt="Agenic"`, `"Agenic"`, `"Agenic × Nestor"`, `"nestor — verified intelligence that compounds"`, `"nestor — verified"`, `"intelligence"`, `"that compounds"` | ProductShell.tsx:49, admin.index.tsx:82-83, index.tsx:91-95, auth.action.tsx:150, auth.login.tsx:117 | Brand names / brand tagline — rendered identically in every locale by design. |
| `"Context Pack"` (all locales) | admin.json `intakeDetail.history.skill.context-pack`, contextPack.label | Product term — kept untranslated in every locale per plan interfaces. |
| `"Something went wrong"`, `"An unexpected error occurred. Please try again."`, `"Try again"`, `"Go home"` | router.tsx:26-48 (DefaultErrorComponent) | Dev-only error boundary; message shown only in `import.meta.env.DEV`. |
| `"Page not found"`, `"The page you're looking for…"`, `"Go home"` | __root.tsx:10-18 (NotFoundComponent) | 404 boundary, English-only fallback chrome; not part of the localized intake flow. |
| `"Promise"` (×8) | AISkillsPanel.tsx:52, ResearchArtifacts.tsx, ResearchResultsPanel.tsx, ValidationDiff.tsx, auth-context.tsx:59 | False positive — TypeScript `Promise<T>` type annotations, not rendered text. |
| `intake.$id.tsx:18, :114` Dutch fragments | intake.$id.tsx | False positive — text inside `//` source comments. |
| `ResearchResultsPanel.tsx:426` `"Type: … · Onderzoek: ${clientName} · …"` with hardcoded `nl-BE` | ResearchResultsPanel.tsx:426 | Inside a jsPDF `doc.text()` per-question answer-PDF export (no `t` in scope). PDF i18n is a separate react-pdf-pattern change out of this sweep's UI scope. **Follow-up candidate.** |
| All `admin.sales.*`, `SalesContextFields.tsx`, `BattlecardBlocks.tsx` Dutch strings (~80 hits) | `src/routes/admin.sales.projects.*`, `src/components/sales/*` | **Separate product area (Nestor Sales), not the Nestor Intake flow the operator complained about.** Per the plan SCOPE NOTE, the audit flags them but they are out of scope for this intake-flow sweep. Translating the entire sales product is its own task. |

## Dynamic-key allowlist (CHECK B — unresolvable, informational)

These use template-literal keys (variable interpolation), so the audit cannot statically resolve
them; they are printed, not failed. All resolve at runtime against keys that ARE present:

- `t(\`spaceForm.locale.${loc}\`)` — SpaceFormModal.tsx:158
- `t(\`status.${status}\`)` — _status.tsx:34
- `t(\`language.${current}\`)`, `t(\`language.${lang}\`)` — LanguageSwitcher.tsx:93,111
- `t(\`home.products.${slug}\`)`, `t(\`home.products.${p.slug}\`)` — admin.index.tsx:22,107
- `t(\`common:status.${k}\`)` — admin.pulse.clients.tsx:41
- `t(\`intakeDetail.status.${status}\`)` — admin.pulse.intakes.$id.tsx:176
- `t(\`intakeDetail.statusHint.${intake.status}\`)` — admin.pulse.intakes.$id.tsx:1004
- `t(\`intakeDetail.status.${value}\`)` — admin.pulse.intakes.$id.tsx:1078
- `t(\`intakeDetail.statusBanner.${intake.status}\`)` — admin.pulse.intakes.$id.tsx:1164
- `t(\`intakeDetail.history.skill.${r.skill_name}\`)` — admin.pulse.intakes.$id.tsx:1628 (NEW this task)
- `t(\`intakesList.filter.${value}\`)` — admin.pulse.intakes.index.tsx:145

## Verification

1. `node scripts/i18n-audit.mjs` — **exit 0**; CHECK A/B/C clean, CHECK D advisory (107, all resolved/justified above).
2. `npx tsc --noEmit` — **0 errors**.
3. `npm run build` — **succeeds** (built in 17.95s).
4. Manual grep gate `grep -rnoE "[^.A-Za-z]t\(\s*\"…\"\s*,\s*\"…\"" src | grep -vi "helvetica\|Content-Type"` — **zero** genuine i18n fallback lines.

## Deviations from Plan

- **[Rule 3 — blocking]** CHECK B initially flagged a false-positive key `intakeDetail.status.<value>`
  extracted from a `t("intakeDetail.status.<value>")` string inside a source **comment**. Fixed
  the audit script's single-arg collector to reject keys containing non-key characters
  (`/^[\w.:$-]+$/`), so doc/comment artifacts no longer trip the hard gate.
- **[Rule 2 — missing critical]** The plan named four known offenders; the audit surfaced a
  larger pre-existing parity gap — the entire `intake.research.*` namespace (37 keys) plus
  `nextStep.researchConfirm*` existed only in nl. These are used by live intake-flow components
  (`ResearchRunProgress`, `NextStepBanner`), so an EN/FR operator saw Dutch there too. Backfilled
  fr/en as part of closing the CHECK A/B hard gates (required for exit 0).

## Self-Check: PASSED
- `frontend/scripts/i18n-audit.mjs` — FOUND
- Commit e02985b — FOUND
- Commit b2a22ed — FOUND
- Commit cd7e63a — FOUND
