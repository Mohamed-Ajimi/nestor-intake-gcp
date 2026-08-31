---
task: 260831-lpm
title: Correct the stale research-start banner copy
type: quick
scope: copy-only (i18n locale JSON)
base_commit: 651c7de999e79cd5742d45d4ea21600fd6c2f7ce
commit: 6d474e1
branch: master
files_changed: 3
strings_changed: 6
deployed: false
observed: false
completed: 2026-08-31
---

# Quick Task 260831-lpm: Correct the Stale Research-Start Banner Summary

Replaced six locale strings so the pre-run banner names the providers the Tribunal engine
actually uses (Gemini / OpenAI / Claude) instead of three Supabase-era services that no
longer execute on a normal run, and so the confirm dialog states the real duration and the
non-refundable cost.

**Commit:** `6d474e1` — `fix(quick-260831-lpm): research-start banner named three services the engine no longer uses`
**Base:** `651c7de` (asserted before any edit, matched exactly)
**Diff:** 3 files changed, 6 insertions(+), 6 deletions(-) — one insertion + one deletion per string.

---

## The Six Strings — Before / After

### `nextStep.researchStartBody`

**nl — before**
> Dit lanceert `<0>`SerpAPI + SearchAPI + Apify`</0>` (rag-web-browser + website-content-crawler) voor élke onderzoeksvraag. Levert 2–5 artifacts per vraag, klaar binnen 2–5 minuten. Daarna kan je per vraag manueel extra artifacts toevoegen.

**nl — after**
> Dit verdeelt élke onderzoeksvraag over `<0>`Gemini, OpenAI en Claude`</0>` — zwaardere vragen krijgen een tweede provider ter controle. Reken op tientallen minuten: één provider mag tot 35 minuten stil blijven voor hij antwoordt. Je volgt de voortgang op de run-pagina.

**en — before**
> This launches `<0>`SerpAPI + SearchAPI + Apify`</0>` (rag-web-browser + website-content-crawler) for every research question. Delivers 2–5 artifacts per question, ready within 2–5 minutes. Then you can manually add extra artifacts per question.

**en — after**
> This distributes every research question across `<0>`Gemini, OpenAI and Claude`</0>` — heavier questions get a second provider for corroboration. Expect tens of minutes: one provider may stay silent for up to 35 before answering. Follow progress on the run page.

**fr — before**
> Ceci lance `<0>`SerpAPI + SearchAPI + Apify`</0>` (rag-web-browser + website-content-crawler) pour chaque question de recherche. Fournit 2–5 artifacts par question, prêts en 2–5 minutes. Ensuite vous pouvez ajouter manuellement des artifacts par question.

**fr — after**
> Ceci répartit chaque question de recherche entre `<0>`Gemini, OpenAI et Claude`</0>` — les questions à enjeu élevé reçoivent un second fournisseur pour corroboration. Comptez plusieurs dizaines de minutes : un fournisseur peut rester silencieux jusqu'à 35 minutes avant de répondre. Suivez la progression sur la page du run.

### `nextStep.researchConfirmBody`

**nl — before**
> Dit start een uitgebreide research-run voor deze intake. De run duurt enkele minuten en brengt API-kosten met zich mee. Doorgaan?

**nl — after**
> Dit start een betaalde deep-research run over meerdere AI-providers. Reken op tientallen minuten en tientallen dollars aan API-kosten. Annuleer je halverwege, dan worden de reeds gemaakte kosten niet terugbetaald. Doorgaan?

**en — before**
> This starts an extensive research run for this intake. The run takes several minutes and incurs API costs. Continue?

**en — after**
> This starts a paid deep-research run across multiple AI providers. Expect tens of minutes and tens of dollars in API costs. If you cancel midway, costs already incurred are not refunded. Continue?

**fr — before**
> Ceci lance une recherche approfondie pour cet intake. L'exécution dure quelques minutes et engendre des coûts d'API. Continuer ?

**fr — after**
> Ceci lance une recherche approfondie payante via plusieurs fournisseurs d'IA. Comptez plusieurs dizaines de minutes et plusieurs dizaines de dollars de coûts d'API. En cas d'annulation, les coûts déjà engagés ne sont pas remboursés. Continuer ?

All six were applied **verbatim** from the operator-approved text. The final on-disk values were
re-read out of the committed files and diffed against the approved text character-for-character —
they match, including the em dashes, the French narrow-space colon (`minutes : un`), and the
`élke` / `à enjeu élevé` accents.

---

## Render Path of `researchConfirmBody` — What I Found and What I Did

The plan asked me to determine this before deciding whether markup was allowed.

**Finding: it is NOT a `<Trans>`.** It is a plain single-argument `t()` call:

```
NextStepBanner.tsx:443   <AlertDialogDescription>
NextStepBanner.tsx:444     {t("nextStep.researchConfirmBody")}
NextStepBanner.tsx:445   </AlertDialogDescription>
```

Any `**bold**` would have rendered as literal asterisks, and any `<0>` would have rendered as
literal text (or thrown, since no `components` array is bound at this call site).

**What I did: nothing was needed.** The operator-approved replacement text for
`researchConfirmBody` contains no `**bold**` and no tags in any of the three locales — it was
already written as plain prose. I verified this programmatically rather than by eye: a gate
counts `<...>` tags and `**` pairs in `researchConfirmBody` and asserts both are zero. All three
locales returned `tags=0 asterisks=0`. So no emphasis was dropped, because none was present to
drop. The emphasis distinction lives only in `researchStartBody`, which is the `<Trans>` one.

By contrast `researchStartBody` **is** a `<Trans>`, at `NextStepBanner.tsx:296-300`, with
`components={[<strong />]}` on line 299. The `<0>` slot there is load-bearing and was preserved.

---

## Verification Results — Real Numbers

| # | Gate | Command / method | Result |
|---|------|------------------|--------|
| 1 | JSON validity | `JSON.parse` on all three files | **PASS** — nl, en, fr all parse |
| 2 | Absence of the 5 stale terms | scoped to the two keys only | **PASS** — 0 hits for `SerpAPI`, `SearchAPI`, `Apify`, `rag-web-browser`, `website-content-crawler` |
| 3 | `<0>` slot present + balanced | tag count in `researchStartBody` | **PASS** — nl 1/1, en 1/1, fr 1/1 (open/close) |
| 3b | `researchConfirmBody` markup-free | tag + `**` count | **PASS** — all three: `tags=0 asterisks=0` |
| 4 | Key parity nl/en/fr | flattened key-set diff | **PASS** — **634 keys** in each; 0 missing, 0 extra vs nl in both en and fr |
| 5 | `npx tsc --noEmit` | in `frontend/` | **PASS** — exit 0, **0 errors**, no output |
| 6 | `npx vitest run` | in `frontend/` | **PASS** — **140 passed / 140**, 0 failed, 9 test files, 13.33s |
| 7 | i18n audit | `node scripts/i18n-audit.mjs` from `frontend/` | **PASS** — exit 0, `RESULT: PASS — A/B/C clean (107 CHECK D advisories)` |
| 8 | Diff scope | `git diff --name-only` | **PASS** — exactly the three locale files, nothing else |

**Gate 6 detail** — the count is **140**, the upper of the two the plan allowed (135 or 140).
Per-file: `intake-phase` 17, `localizeSchema` 10, `verificationGate` 10, `error-codes` 7,
`feedRows` 15, `workPhase` 16, `citationIndex` 16, `funnelLabels` 42, `date-locale` 7.

**Gate 7 detail** — the script **did run**; I am not claiming a pass I did not observe. It exists
at `frontend/scripts/i18n-audit.mjs` and is genuinely not wired to any `package.json` script, so I
invoked it directly. Checks A (3-way key parity), B (used-key coverage), and C (two-arg fallbacks)
are all clean; CHECK B explicitly reported `✓ every literal t() key resolves in all locales`.
The **107 CHECK D advisories are pre-existing and unrelated** — CHECK D scans `.tsx` source for
hardcoded user-visible strings, and I changed no `.tsx`. I checked whether any advisory touches a
locale file: the only line in the entire audit output containing the word `locales` is the CHECK B
**pass** line quoted above, not an advisory. So zero of the 107 arise from this change.

**Gate 2 scoping** — as the plan required, absence was asserted against the two key *values*, not
against the repo. `ResearchArtifacts.tsx` still carries `serp_api` / `serpapi` source labels for
historical artifacts and was deliberately left alone. A repo-root `grep -rn` was avoided entirely,
so the orphaned `.claude/worktrees/agent-af281d695d9b34c35/` tree was never read, edited, or deleted.

**Post-commit deletion check** — `git diff --diff-filter=D --name-only HEAD~1 HEAD` returned empty.
No files were deleted.

---

## Scope Discipline

Changed: exactly two keys × three locales = six string values.

Explicitly **not** changed, though adjacent in the same JSON block:
`researchStartTitle`, `researchRunning`, `startAutoResearch`, `researchConfirmTitle`,
`researchConfirmCancel`, `researchConfirmConfirm`. The `6 insertions(+), 6 deletions(-)` line
count is itself the proof — one line per string, no more.

No `.tsx` file was modified. `NextStepBanner.tsx` was opened read-only, twice, to establish the
two render paths.

---

## Deviations from Plan

None. The plan was executed exactly as written. No deviation rule fired.

---

## Known Stubs

None introduced.

---

## ⛔ Not Deployed, Not Observed

Two limits on what this task establishes:

1. **This is NOT deployed.** The task ended at a commit, as instructed — no build, no `gcloud`,
   no deploy. The new copy ships with the next `nestor-frontend` build. Until that build and
   deploy happen, the live service continues to render the stale
   "SerpAPI + SearchAPI + Apify" text to operators.

2. **Nobody has seen the new copy rendered.** There is no `.tsx` test in this repo at all —
   `vitest.config.ts` includes only `src/**/*.test.ts`, and all 9 test files that ran are pure
   `.ts` logic tests. Nothing renders `NextStepBanner`. The `<Trans>` interpolation of the `<0>`
   slot is therefore verified **by inspection of the source at `NextStepBanner.tsx:296-300`
   plus a structural tag-balance assertion on the string**, not by rendering. `tsc` and the
   i18n audit both prove the key exists and resolves in all three locales; neither proves the
   `<strong>` renders where intended, and neither can — this is the same class of gap recorded
   for Phase 23, where locale-parity gates proved keys existed while a label asserted the
   opposite of its own figure.

   The first real observation will be an operator opening an intake at
   `awaiting_research_start` after the next frontend deploy, in each of nl / en / fr, and
   confirming that "Gemini, OpenAI and Claude" appears **bold** in the banner and that the
   confirm dialog shows clean prose with no stray asterisks or angle brackets.

---

## Self-Check: PASSED

- `frontend/src/locales/nl/intake.json` — FOUND, modified, parses
- `frontend/src/locales/en/intake.json` — FOUND, modified, parses
- `frontend/src/locales/fr/intake.json` — FOUND, modified, parses
- Commit `6d474e1` — FOUND in `git log`, 3 files / 6+ 6-
- Base `651c7de` — matched before any edit was made
- Working tree after commit — clean except the pre-existing untracked `.claude/`
