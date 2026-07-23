---
phase: quick-260723-kjj
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - frontend/src/components/intake/AISkillsPanel.tsx
  - frontend/src/components/TopBar.tsx
  - frontend/src/components/intake/ContextPackBlock.tsx
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/locales/nl/intake.json
  - frontend/src/locales/fr/intake.json
  - frontend/src/locales/en/intake.json
  - frontend/src/locales/nl/admin.json
  - frontend/src/locales/fr/admin.json
  - frontend/src/locales/en/admin.json
  - frontend/src/locales/nl/common.json
  - frontend/src/locales/fr/common.json
  - frontend/src/locales/en/common.json
  - frontend/scripts/i18n-audit.mjs
autonomous: true
requirements: [I18N-SWEEP]

must_haves:
  truths:
    - "An operator with UI language set to English sees zero Dutch fragments in the AI-skills popover, the History sheet, the notification bell tooltip, or anywhere else in the intake flow"
    - "The four aiSkills.*Desc keys resolve to real translations in nl, fr and en (no inline Dutch fallback renders)"
    - "The History sheet status labels (succeeded/failed/running) and skill names render in the active locale, not hardcoded Dutch"
    - "The notification bell tooltip and aria-label render in the active locale"
    - "The context-pack inline history accordion is gone from the center page; context-pack runs are only visible in the header History sheet"
    - "All three locale catalogs (nl, fr, en) are key-consistent per namespace — no key present in one locale and missing in another"
    - "No genuine two-argument t('key','Dutch fallback') translation calls remain in frontend/src"
    - "Every t('literal.key') used in src resolves to a key present in all three locales (dynamic-key false positives excepted and listed)"
  artifacts:
    - path: "frontend/src/locales/en/intake.json"
      provides: "aiSkills.structureDesc / extractDesc / embeddingsDesc / transcribeDesc translations; orphaned accordion keys removed"
      contains: "structureDesc"
    - path: "frontend/src/locales/en/admin.json"
      provides: "intakeDetail.history.empty + status labels (done/failed/busy) + skill-name map keys"
      contains: "intakeDetail"
    - path: "frontend/src/locales/en/common.json"
      provides: "notifications tooltip + aria-label keys for the TopBar bell"
      contains: "notifications"
    - path: "frontend/src/components/intake/AISkillsPanel.tsx"
      provides: "aiSkills descriptions via single-arg t() (fallbacks dropped)"
    - path: "frontend/src/components/intake/ContextPackBlock.tsx"
      provides: "context-pack block with the inline history accordion removed, latest-pack refresh intact"
    - path: "frontend/scripts/i18n-audit.mjs"
      provides: "reusable audit: 3-way key parity + used-key coverage + hardcoded-string scan"
  key_links:
    - from: "frontend/src/components/intake/AISkillsPanel.tsx"
      to: "frontend/src/locales/{nl,fr,en}/intake.json"
      via: "t('aiSkills.structureDesc') single-arg lookup"
      pattern: "aiSkills\\.(structure|extract|embeddings|transcribe)Desc"
    - from: "frontend/src/routes/admin.pulse.intakes.$id.tsx"
      to: "frontend/src/locales/{nl,fr,en}/admin.json"
      via: "SKILL_LABELS + status labels resolved through t()"
      pattern: "intakeDetail\\.history\\."
    - from: "frontend/src/components/TopBar.tsx"
      to: "frontend/src/locales/{nl,fr,en}/common.json"
      via: "useTranslation('common') for bell title/aria-label"
      pattern: "notifications"
---

<objective>
Eliminate ALL user-visible hardcoded/untranslated strings from the frontend intake flow so an operator running in English never sees Dutch fragments, and remove the now-redundant context-pack history accordion from the center page (context-pack runs already appear in the header History sheet).

This is the operator's SECOND complaint about untranslated strings — the plan is deliberately exhaustive (a full grep + key-parity audit driven by a reusable script), not a spot-fix of the four known offenders.

Purpose: Restore the operator's trust that the language switch actually switches ALL copy, and de-duplicate the context-pack history UI.
Output: Fixed components + three-way key-consistent locale catalogs + a reusable audit script + an audit report (in the SUMMARY) proving zero remaining offenders.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md

<interfaces>
i18n namespaces (per language dir frontend/src/locales/{nl,fr,en}/): admin.json, auth.json, common.json, intake.json

react-i18next usage: const { t } = useTranslation("<namespace>"); then t("dotted.key") or t("key", { var }). Interpolation uses {{name}} in JSON values.

common.json already has a comingSoon.badge section — put the bell strings in a NEW notifications object in common.json (all 3 locales).

intake.json aiSkills namespace is MISSING these four keys in ALL three locales:
  aiSkills.structureDesc   (nl fallback text: "Zet antwoorden om in gestructureerde data.")
  aiSkills.extractDesc     (nl fallback text: "Extraheer sleutelinzichten uit de antwoorden.")
  aiSkills.embeddingsDesc  (nl fallback text: "Genereer embeddings voor semantisch zoeken.")
  aiSkills.transcribeDesc  (nl fallback text: "Transcribeer audio naar tekst.")

admin.json intakeDetail.history currently: { title, loading, error, running }. Needs added:
  empty ("Geen activiteit gevonden."), status labels done / failed / busy, and a skill sub-map.

admin.pulse.intakes.$id.tsx SKILL_LABELS (~line 210) hardcoded Dutch to move into admin.json intakeDetail.history.skill:
  apply-intake-skill -> "Intake analyse", structure-answers -> "Structureer antwoorden",
  extract-insights -> "Inzichten extractie", generate-embeddings -> "Embeddings",
  transcribe-source -> "Transcriptie", context-pack -> "Context Pack" (product term — keep untranslated in all locales).
  Hardcoded status labels (~line 1655): "✓ voltooid" / "✗ mislukt" / "bezig…". Empty fallback (line 1633): "Geen activiteit gevonden.".

TopBar.tsx (~line 30-31): hardcoded title="Notificaties — binnenkort beschikbaar" and aria-label="Notificaties".

ContextPackBlock.tsx accordion internals to REMOVE (KEEP everything else):
  state historyOpen / history (+ setters); loadHistory useCallback; toggleHistory fn;
  the `if (history !== null) loadHistory();` line inside the status-change effect (~line 322);
  the `{latestPack && (<section>…history accordion…</section>)}` JSX block (~lines 542-612).
  KEEP: loadLatest and its effect call, reloadSignal, questions block, viewingPack modal.
  Orphaned intake.json contextPack key historyToggle is accordion-only (remove from all 3 locales).
  For contextPack.noRuns / contextPack.loading and any other history-list label: grep src first,
  remove a key ONLY if it has zero remaining t("contextPack.<key>") references after the edit.

DIAGNOSTIC — the raw grep for two-arg t( has MANY false positives that are NOT i18n:
  jsPDF doc.setFont("helvetica","normal"), headers.set("Content-Type",...), fields.industry_vertical.
  The ONLY genuine i18n two-arg fallbacks are the 4 in AISkillsPanel + the 1 in admin.pulse.intakes.$id.tsx.
  The audit regex MUST anchor on a non-word char before t( (i.e. [^.A-Za-z]t\() to exclude .text(/.set(.

SCOPE NOTE — sales routes (admin.sales.projects.*.tsx, SalesContextFields.tsx) contain hardcoded Dutch
  placeholders (e.g. placeholder="Naam"). They are a separate product area from the intake flow the
  operator complained about. The audit (Task 3) MUST still flag them; the executor either fixes them or
  lists each with a one-line justification in the SUMMARY under "Judged exceptions" — never silently skip.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix the four known offenders and backfill locale keys (3-way consistent)</name>
  <files>frontend/src/components/intake/AISkillsPanel.tsx, frontend/src/components/TopBar.tsx, frontend/src/routes/admin.pulse.intakes.$id.tsx, frontend/src/locales/nl/intake.json, frontend/src/locales/fr/intake.json, frontend/src/locales/en/intake.json, frontend/src/locales/nl/admin.json, frontend/src/locales/fr/admin.json, frontend/src/locales/en/admin.json, frontend/src/locales/nl/common.json, frontend/src/locales/fr/common.json, frontend/src/locales/en/common.json</files>
  <action>
Fix the four orchestrator-verified offenders and add every missing locale key to nl, fr AND en. Dutch is the source; translate naturally, not literally.

(1) AISkillsPanel.tsx — add aiSkills.structureDesc / extractDesc / embeddingsDesc / transcribeDesc to intake.json in all 3 locales (nl values = the current inline Dutch fallbacks quoted in interfaces; en/fr = natural translations). Then change the four call sites to single-arg t() — drop the second-argument Dutch fallback. Fallbacks are what masked the missing keys and shipped this bug, so they must not stay.

(2) admin.pulse.intakes.$id.tsx — (a) add intakeDetail.history.empty plus status labels intakeDetail.history.done / .failed / .busy to admin.json x3 (nl values from interfaces). Change the JSX status expression (~line 1655) to use t(...) for the succeeded/failed/running cases; keep the raw r.status bare-fallback for unknown statuses. (b) Add an intakeDetail.history.skill sub-map to admin.json x3 with the six skill_name keys from interfaces (context-pack stays "Context Pack" in every locale). Replace the module-level SKILL_LABELS lookup with a call using t with key intakeDetail.history.skill.<r.skill_name> and r.skill_name as the fallback, inside the render (t is in scope via useTranslation("admin")); you may delete the SKILL_LABELS const. (c) Change line 1633 from the two-arg fallback to single-arg t("intakeDetail.history.empty").

(3) TopBar.tsx — add const { t } = useTranslation("common"). Add a notifications object to common.json x3 with keys comingSoon and ariaLabel (nl values from interfaces). Replace the hardcoded title= and aria-label= with t("notifications.comingSoon") and t("notifications.ariaLabel"). common.json is correct because TopBar mounts in both admin and intake layouts.

Preserve each JSON file's existing 2-space indentation and trailing newline.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit 2>&1 | tail -5</automated>
  </verify>
  <done>The 4 AISkillsPanel .Desc keys, TopBar notifications keys, and admin history/status/skill keys exist in nl, fr AND en; the genuine two-arg i18n fallbacks in AISkillsPanel and admin route are gone; TopBar uses t() for bell strings; tsc has no new errors.</done>
</task>

<task type="auto">
  <name>Task 2: Remove the redundant context-pack history accordion</name>
  <files>frontend/src/components/intake/ContextPackBlock.tsx, frontend/src/locales/nl/intake.json, frontend/src/locales/fr/intake.json, frontend/src/locales/en/intake.json</files>
  <action>
Remove the inline context-pack history accordion (redundant with the header History sheet, commit 1aafe77) WITHOUT breaking the latest-pack refresh.

Delete: the historyOpen and history state plus their setters; the loadHistory useCallback; the toggleHistory fn; the `if (history !== null) loadHistory();` line inside the status-change effect (~line 322); the entire `{latestPack && (<section>…history accordion…</section>)}` JSX block (~lines 542-612).

KEEP intact: loadLatest and its call in the effect, reloadSignal handling, the questions block, and the viewingPack modal. After removing loadHistory from the effect body, remove it from the effect dependency array and update the eslint-disable comment if it references loadHistory. Confirm the effect still calls loadLatest() on status/reloadSignal change.

Then remove now-orphaned intake.json contextPack keys from all 3 locales — ONLY keys with zero remaining references in src after the edit. contextPack.historyToggle is accordion-only (safe). For contextPack.noRuns, contextPack.loading, and any other history-list label: grep the whole src tree first; remove a key only if grep shows zero remaining t("contextPack.<key>") usages. Remove from nl, fr AND en together to keep parity.
  </action>
  <verify>
    <automated>cd frontend && ! grep -qE "toggleHistory|loadHistory|setHistory|historyOpen" src/components/intake/ContextPackBlock.tsx && ! grep -qr "contextPack.historyToggle" src && npx tsc --noEmit 2>&1 | tail -5</automated>
  </verify>
  <done>The history accordion state/fns/JSX are gone from ContextPackBlock.tsx; loadLatest + reloadSignal refresh still work (tsc clean); orphaned contextPack.historyToggle removed from all 3 locales; other history-only keys removed only if unreferenced.</done>
</task>

<task type="auto">
  <name>Task 3: Exhaustive i18n audit script + close every gap it finds</name>
  <files>frontend/scripts/i18n-audit.mjs, frontend/src/locales/nl/intake.json, frontend/src/locales/fr/intake.json, frontend/src/locales/en/intake.json, frontend/src/locales/nl/admin.json, frontend/src/locales/fr/admin.json, frontend/src/locales/en/admin.json, frontend/src/locales/nl/common.json, frontend/src/locales/fr/common.json, frontend/src/locales/en/common.json, frontend/src/locales/nl/auth.json, frontend/src/locales/fr/auth.json, frontend/src/locales/en/auth.json</files>
  <action>
Write frontend/scripts/i18n-audit.mjs (a Node ESM script, no new deps — use node:fs) that scans frontend/src, EXCLUDING components/ui/, routeTree.gen.ts, mock-backend/, and the locales/ dir themselves. It runs four checks and exits non-zero if any HARD failure remains:

CHECK A — 3-way key parity: for each namespace (admin, auth, common, intake) load nl/fr/en, flatten to dotted keys, and report any key present in one locale but missing in another. HARD failure if any diff.

CHECK B — used-key coverage: regex-extract literal single-arg calls matching a word-boundary t("<ns-optional>.<key>") across src (anchor [^.A-Za-z] before t( to skip .text(/.set(). Merge all locale namespaces into one lookup; report used keys with no locale entry. Dynamic keys (template literals like t(`intakeDetail.history.skill.${...}`) are UNRESOLVABLE — collect and PRINT them as an allowlist, do not fail on them.

CHECK C — two-arg i18n fallbacks: find [^.A-Za-z]t( "..." , "..." ) occurrences, then FILTER OUT known non-i18n callers (setFont/doc.text/headers.set — already excluded by the [^.A-Za-z] anchor plus a helvetica/Content-Type denylist). HARD failure if any genuine i18n two-arg fallback remains.

CHECK D — hardcoded user-visible strings (WARN, printed for human review, does not hard-fail): (i) JSX text nodes >[A-Za-zÀ-ÿ]{2,}< not wrapped in {t(...)}; (ii) literal string props title=/placeholder=/aria-label=/alt="[A-Za-zÀ-ÿ]..."; (iii) Dutch signal words (van|het|naar|wordt|beschikbaar|mislukt|voltooid|bezig|geen|nog|verstuur|bekijk|antwoorden|vragen|onderzoek|klik) case-insensitive inside string literals. Print file:line for each hit.

The script prints a section per check and a final PASS/FAIL. Make CHECK A/B/C hard-gate (exit 1), CHECK D advisory.

Run the script. Then CLOSE every hard-gate gap it reports: add missing keys to the correct namespace in ALL three locales (translate from whichever locale has the string; Dutch is source). Re-run until CHECK A/B/C are clean. For CHECK D warnings: fix every hardcoded string that is genuinely user-visible in the intake/admin operator flow (including the sales-route placeholders — move them to a sales namespace or the appropriate existing namespace across 3 locales). Anything left unfixed (brand names like "Agenic", the product term "Context Pack", console.* strings, dev-only DefaultErrorComponent text) MUST be enumerated in the SUMMARY under "Judged exceptions" with a one-line reason each.
  </action>
  <verify>
    <automated>cd frontend && node scripts/i18n-audit.mjs</automated>
  </verify>
  <done>i18n-audit.mjs exists and exits 0: CHECK A (3-way parity) clean, CHECK B (every literal t() key exists in all 3 locales) clean, CHECK C (zero genuine two-arg i18n fallbacks) clean. CHECK D warnings are either fixed or listed as judged exceptions in the SUMMARY. Dynamic-key allowlist printed.</done>
</task>

</tasks>

<verification>
Run from frontend/ with the EXISTING node_modules (never npm install):

1. `node scripts/i18n-audit.mjs` — exits 0 (CHECK A/B/C clean; CHECK D advisory list printed).
2. `npx tsc --noEmit` — no new type errors.
3. `npm run build` — production build succeeds.
4. Manual grep gate: `grep -rnoE "[^.A-Za-z]t\(\s*\"[^\"]*\"\s*,\s*\"[^\"]*\"" src | grep -vi "helvetica\|Content-Type"` returns zero genuine i18n fallback lines.
5. Spot check: switch UI to EN and confirm the AI-skills popover descriptions, History sheet status/skill labels, and bell tooltip all render English (not Dutch).
</verification>

<success_criteria>
- Operator on English sees zero Dutch fragments across the intake + admin flow (AI-skills popover, History sheet, bell tooltip).
- aiSkills.*Desc, intakeDetail.history.* (empty/done/failed/busy/skill.*), and common.notifications.* keys exist in nl, fr AND en.
- Context-pack inline history accordion removed; latest-pack refresh and viewingPack modal still work; orphaned locale keys pruned in all 3 locales.
- i18n-audit.mjs committed and green (A/B/C hard-gates pass).
- tsc clean and `npm run build` succeeds.
- Every remaining hardcoded string is a documented judged exception in the SUMMARY.
</success_criteria>

<output>
Create `.planning/quick/260723-kjj-exhaustive-i18n-hardcoded-string-sweep-h/260723-kjj-SUMMARY.md` when done. The SUMMARY MUST include: (a) the full list of locale keys added per namespace; (b) the CHECK D advisory findings and how each was resolved; (c) a "Judged exceptions" section listing every intentionally-untranslated string (brand names, product terms, console/dev-only strings) with a one-line reason; (d) the dynamic-key allowlist from CHECK B.
</output>
