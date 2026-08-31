---
task: 260831-mgg
title: Remove the dead "Research artifacts" block
date: 2026-08-31
base: ebc0f6d70a58038febae33372f5f6cfec93212cb
commit: cbb8503
scope: frontend-only
deployed: false
---

# 260831-mgg — Remove the dead "Research artifacts" block

Deleted the intake detail page's "Research artifacts" card, which showed
*"No research questions yet — they appear as soon as the intake is decomposed."*
on intakes that **were** decomposed and whose run had finished. It could never render
anything else: `ResearchArtifactsInner`'s loader hardcoded `setQuestions([]); setArtifacts([])`
and the 853-line file contained no fetch of any kind, so `visibleQuestions.length === 0`
was permanently true and the whole "General / upload / manual note" subtree below it was
unreachable by construction. The stub's own comment claimed "the block is gated off" — false;
`phaseShowsResearch` is true for `in_research`, `awaiting_report_upload`,
`awaiting_results_send`, `completed` and `archived`, so it had been rendering all along.

**One atomic commit: `cbb8503`** (deletion + route + three locales together — splitting them
would leave an intermediate commit that does not compile).

## What changed — exact counts

| File | Change |
|------|--------|
| `frontend/src/components/intake/ResearchArtifacts.tsx` | **deleted, 853 lines** |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` | −20 / +10 (3 removals, 1 comment added) |
| `frontend/src/locales/nl/intake.json` | −56 lines (**54 keys**, `artifacts` namespace) |
| `frontend/src/locales/en/intake.json` | −56 lines (**54 keys**) |
| `frontend/src/locales/fr/intake.json` | −56 lines (**54 keys**) |

Diffstat: **5 files changed, 10 insertions(+), 1031 deletions(-)**. The `artifacts` namespace
occupied lines 311–366 in all three locales; removal was done by a boundary-asserting script
(it refused to run unless line 311 was `"artifacts": {`, line 366 was `},` and line 367 opened
`"recipients"`), preserving CRLF endings.

Route removals: the import at `:53`, the `showResearch` const at `:1046`, and the 7-line mount
at `:1383-1389`, replaced by a 10-line tombstone comment recording the operator's 2026-08-31
removal and why it must not be "restored".

## `phaseShowsResearch` — it did become unused

After deleting the `showResearch` const, `phaseShowsResearch` had no remaining use in the route,
so **I removed it from the import list at `:76`**. It remains exported from
`frontend/src/lib/intake-phase.ts` and is still consumed by `phaseShowsSemanticSearch` (`:128`) —
that module was **not touched**. `phaseShowsSemanticSearch` (`:77`), `hasArtifacts` (`:307`) and
`showSemanticSearch` (`:1047`) all stay. Confirmed by `tsc` at 0 errors, which is *not* a strong
signal on its own here: `tsconfig.json` sets `noUnusedLocals: false`, so the compiler would have
stayed silent on a dead local. The unused-ness was established by grep, not by the compiler.

## Verification — real numbers

| # | Check | Baseline (`ebc0f6d`) | After | Result |
|---|-------|----------------------|-------|--------|
| 1 | `git diff --name-only` | — | exactly the 5 expected files | **PASS** |
| 2 | Locale key count, 3-way parity | 634 / 634 / 634 | **580 / 580 / 580**, all 3 re-parse as JSON | **PASS** — even drop of 54; missing-key diff is **0** in all four directions |
| 3 | Live refs to `ResearchArtifacts*` in `frontend/src` | — | **0 outside comments** (sole hit is the new tombstone) | **PASS** |
| 4 | `npx tsc --noEmit` | 0 errors | **0 errors** | **PASS** |
| 5 | `npx vitest run` | 140 passed / 9 files | **140 passed / 9 files** | **PASS — unchanged**, as predicted |
| 6 | `node scripts/i18n-audit.mjs` | PASS, 107 CHECK D advisories | **PASS — A/B/C clean, 104 CHECK D advisories** | **PASS** |
| 7 | Empty-state string gone | — | all three variants absent from `src/locales` | **PASS** |

Notes on 6 and 7:

- The advisory count dropped **107 → 104**, exactly the 3 hits that belonged to the deleted
  `.tsx`. Verified both ways: the deleted file accounted for 3 advisories at baseline, and greps
  0 times in the post-change audit output. No other file's advisories moved.
- Check 7: the exact fr sentence removed was
  `"Aucune question de recherche pour l'instant — elles apparaissent dès que l'intake est décomposé."`
  Two `noQuestions` hits survive at `nl/fr intake.json:111` — these are the **different**
  `results.noQuestions` key the task said to keep (nl: *"Nog geen onderzoeksvragen beschikbaar."*,
  fr: *"Aucune question de recherche disponible pour l'instant."*). Confirmed structurally, not by
  eyeballing the substring: after the change the only key ending in `.noQuestions` in each locale
  is `results.noQuestions`, and `artifacts.*` count is **0**.

All greps were scoped to `frontend/src`. The orphaned stale repo copy under
`.claude/worktrees/agent-af281d695d9b34c35/` was not read, edited or deleted.

## Untouched, as required

`lib/intake-phase.ts` (and `intake-phase.test.ts`, still green within the unchanged 140),
`lib/research-question.ts`, `ResearchResultsPanel.tsx` and its `results.*` keys, `hasArtifacts`,
`results.noQuestions`, and every backend file. `derivePhase`'s `hasResearchArtifacts` parameter
and all phase transitions are unchanged; `hasResearchArtifacts` was not renamed. The prose
mentions in `NextStepBanner.tsx:319`, `workPhase.ts:14` and `intake-phase.ts:68` were left alone.

## One finding worth recording

The deleted block took an `onStartResearch` prop with `handleStatusChange("in_research")` wired
to it, which looks like a lost affordance. It was not: the component did
`// onStartResearch prop is no longer used by this block (banner handles it);` then `void onStartResearch;`
— the prop was inert. The live research trigger is `onStartAutoResearch` → `triggerResearch(id)`,
passed to `NextStepBanner` at `:1243`, and `handleStatusChange` still has two other callers
(`:865`, `:1110`). **No user-facing capability was removed — only the empty card.**

## Deployment status — NOT deployed

This ends at commit `cbb8503` on `master`. No build, no deploy, no `gcloud`, no spend.
It ships with the **next `nestor-frontend` build**, joining three other unbuilt frontend
changes already sitting on `master`: **260831-jx2**, **260831-ksq**, **260831-lpm**.

## Nobody has seen the page without the block

The render is verified by **typecheck and inspection only**. This repo has no `.tsx` test at all —
`vitest.config.ts` includes only `src/**/*.test.ts`, so no test mounts this route and none ever
covered the deleted component. The 140/140 being unchanged is therefore evidence that *nothing
regressed elsewhere*, **not** evidence that the intake detail page renders correctly without the
block. That remains unobserved until someone loads a decomposed intake against a deployed build.

## Self-Check: PASSED

- `frontend/src/components/intake/ResearchArtifacts.tsx` — confirmed **GONE**
- The four surviving touched files — all confirmed present
- Commit `cbb8503` — confirmed present in `git log`
- Post-commit deletion audit: the **only** deletion in the commit is the intended component file
- Working tree clean apart from the pre-existing untracked `.claude/` (not mine, not staged)
