---
phase: 23-report-legibility-business-friendly-funnel-labels-and-an-hon
verified: 2026-08-13T15:10:00Z
status: passed
score: 15/15 must-haves verified
overrides_applied: 0
---

# Phase 23: Report Legibility — Business-Friendly Funnel Labels and an Honest Work-Phase Banner — Verification Report

**Phase Goal:** A superadmin reads every figure on the verification report without knowing the
engine's internals, and is never told research is running once it has finished.
**Verified:** 2026-08-13T15:10:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

Consolidated from the `must_haves.truths` of all three PLAN frontmatter blocks (23-01, 23-02, 23-03),
cross-checked against the actual codebase at HEAD (`584a3f2`), not against SUMMARY/REVIEW claims.

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Every gate-funnel row reads as a business phrase, never a raw snake_case key | ✓ VERIFIED | All 18 `funnelLabel.*` values in en/nl/fr read as phrases; scripted check confirms zero underscores in any label value (plan 23-01 acceptance script re-run, PASS). `VerificationReport.tsx:634-638` resolves `label` via `t(...funnelLabel.${stage}..., {defaultValue: humanizeFunnelStage(stage)})`, replacing the old raw `{stage}` span. |
| 2 | Each known funnel row carries an explanatory tooltip | ✓ VERIFIED | `InfoTip` (`VerificationReport.tsx:340-348`) renders whenever `tip` is non-empty; `funnelTip.*` (18 keys × 3 langs) all present and non-empty (`funnelLabels.test.ts` WR-01 block, 42/42 green, re-run). |
| 3 | `should_have_been_checked` carries the clearest wording and the longest explanation | ✓ VERIFIED | Measured directly: en tooltip 257 chars, nl 317, fr 338 — the longest of all 18 in each language — and each explicitly states the consequence ("shipped unexamined" / "ongecontroleerd meegeleverd" / "livrées sans examen") and the healthy-run floor ("zero"/"nul"/"zéro"). |
| 4 | An unheard-of funnel key still renders a readable row: never blank, never a crash, never a raw token | ✓ VERIFIED | `humanizeFunnelStage` (`funnelLabels.ts:122-138`): control chars → space, `_`→space, collapse, trim, cap at 80+`…`; empty/whitespace-only → `"Unnamed figure"`. 42-test suite (re-run, green) includes the WR-05 regression cases (`"_new_key"`→`"New key"`, `"__"`→same as empty, no blank label). |
| 5 | No funnel row dropped, added, reordered or renumbered — only label text changed | ✓ VERIFIED | `funnelEntries` construction (`VerificationReport.tsx:403-408`, `Object.entries` + `typeof === "number"` filter) is byte-identical to pre-phase HEAD; `key={stage}` unchanged; row order untouched. |
| 6 | A single pure function maps a research-run status to exactly one of five work-phase presentations, every known status enumerated | ✓ VERIFIED | `deriveWorkPhasePresentation` (`workPhase.ts:64-87`) is an explicit `switch` over all 8 Tribunal statuses with `default: return "unknown"`. 16/16 named tests green (re-run). |
| 7 | Absent/null/unknown status resolves to neutral `unknown`, never `finished` | ✓ VERIFIED | `default` branch returns `"unknown"`; tests assert `null`, `undefined`, `""`, and an unknown literal all resolve to `"unknown"` and never to `"finished"`/`"stopped"`. |
| 8 | The word `run-research` appears in no locale file / nowhere in `frontend/src` | ✓ VERIFIED | `grep -rn "run-research" frontend/src \| wc -l` → **0** (re-run). |
| 9 | No intake status line asserts research is running | ✓ VERIFIED | `intakeDetail.statusBanner.in_research` rewritten in all three `admin.json` files to state-neutral copy ("Deep research phase. The work-phase panel says whether the run is still working." / nl / fr) — read directly, none contains "researching"/"onderzoekt"/"effectue la recherche". |
| 10 | When the run has finished, the banner says finished and not running | ✓ VERIFIED | `NextStepBanner.tsx:332-361`: `case "in_research"` derives `presentation` from `researchRunStatus` via `deriveWorkPhasePresentation` and exhaustively maps `finished` → `t("nextStep.inResearchFinishedBody")` ("Research has finished. Nothing is running — upload the client report and deliver it."). |
| 11 | When still running, the banner still says so, and no longer tells the operator to await `run-research` | ✓ VERIFIED | `running` → `inResearchRunningBody` = "Research is running. You can upload artifacts per research question while it works." — no `run-research` mention. |
| 12 | When no run state is known, the banner claims neither running nor finished | ✓ VERIFIED | `unknown` → `inResearchUnknownBody`, and the `switch`'s own `default` case (an unreachable-by-type `never` guard) also falls to the same neutral body, so no code path can silently claim otherwise. |
| 13 | The "Open run" link is still present and still navigates to the run page | ✓ VERIFIED | `IntakeOpenRunLink` still defined (`ResearchRunProgress.tsx:258-261`), returns `<OpenRunLink runId={runId}/>`, still imported and rendered at `admin.pulse.intakes.$id.tsx:59,1220` under the unchanged `RESEARCH_SURFACE_STATUSES` gate. |
| 14 | The intake detail page holds exactly ONE research SSE connection | ✓ VERIFIED | `grep -c "useActiveResearchRun("` on the route file → **1** (`:326`); `IntakeOpenRunLink` (`ResearchRunProgress.tsx:258-261`) contains zero calls to it — the call moved, not multiplied. |
| 15 | The intake STATUS machine was not split | ✓ VERIFIED | `git diff 5f759a7..HEAD -- frontend/src/lib/intake-phase.ts` is empty; last modification to that file (`dff6178`) predates the phase entirely and is an ancestor of the phase-start commit. |

**Score:** 15/15 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/src/lib/research/funnelLabels.ts` | Pure enumerated vocabulary + degrade-safe humanizer, exports `KNOWN_FUNNEL_STAGES`/`isKnownFunnelStage`/`humanizeFunnelStage` | ✓ VERIFIED | Present, exports match, no React/i18n import, WR-05 order fix landed (`_` replace before collapse/trim). |
| `frontend/src/lib/research/funnelLabels.test.ts` | Named vitest coverage of every key + fallback paths | ✓ VERIFIED | 42 tests, all green on re-run (includes 12 originally + WR-01's locale-binding block + WR-05 regressions). |
| `frontend/src/lib/research/workPhase.ts` | `deriveWorkPhasePresentation` / `WorkPhasePresentation` | ✓ VERIFIED | Present, exhaustive switch, exports match. |
| `frontend/src/lib/research/workPhase.test.ts` | One named test per status + null/undefined/unknown safety | ✓ VERIFIED | 16 tests, all green on re-run. |
| `frontend/src/locales/{en,nl,fr}/intake.json` | 37 funnel key paths (23-01) + 5 nextStep bodies (23-02), at parity | ✓ VERIFIED | 634 leaf keys in all three, zero-diff key sets (measured directly). |
| `frontend/src/locales/{en,nl,fr}/admin.json` | State-neutral `intakeDetail.statusBanner.in_research` | ✓ VERIFIED | 365 leaf keys in all three, zero-diff; value rewritten as shown above. |
| `frontend/src/components/intake/VerificationReport.tsx` | Business label + tooltip render site | ✓ VERIFIED | `{stage}` raw span removed; CR-02 clipping fix (flex wrapper, inner `truncate` span with native `title`) present. |
| `frontend/src/components/intake/NextStepBanner.tsx` | `in_research` branch split 5 ways | ✓ VERIFIED | `researchRunStatus` prop, exhaustive `switch` with `never` exhaustiveness guard, no `actions` added. |
| `frontend/src/components/intake/ResearchRunProgress.tsx` | `IntakeOpenRunLink` takes `runId`, no longer owns a stream | ✓ VERIFIED | Signature changed, docstring rewritten, `useActiveResearchRun` body/`OpenRunLink` untouched. |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` | Single `useActiveResearchRun` call feeding both link and banner | ✓ VERIFIED | One call (`:326`), gated by unchanged `RESEARCH_SURFACE_STATUSES`, feeds `IntakeOpenRunLink runId=` and `NextStepBanner researchRunStatus=`. |
| `.../deferred-items.md` | DEF-23-01..05 + two 22-UAT.md corrections | ✓ VERIFIED | Present, committed (`479f7e1`, then amended in review-fix commit `584a3f2`), all five DEF entries plus both corrections present with evidence. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `VerificationReport.tsx` | `lib/research/funnelLabels.ts` | `import { isKnownFunnelStage, humanizeFunnelStage }` | ✓ WIRED | Import present, both functions called in the row-render callback. |
| `VerificationReport.tsx` | `verification.funnelLabel.<stage>` / `funnelTip.<stage>` | `t(template-literal, {defaultValue})` | ✓ WIRED | Present at `:635-641`; `defaultValue` fallback confirmed load-bearing (DEF-22-03 blind spot mitigated). |
| `NextStepBanner.tsx` | `lib/research/workPhase.ts` | `import { deriveWorkPhasePresentation }` | ✓ WIRED | Present, called at `:334`. |
| `admin.pulse.intakes.$id.tsx` | `NextStepBanner.tsx` | `researchRunStatus={...}` prop | ✓ WIRED | `researchRunStatus={researchRun?.status ?? null}` at `:1236`. |
| `admin.pulse.intakes.$id.tsx` | `ResearchRunProgress.tsx` | `IntakeOpenRunLink runId={...}` | ✓ WIRED | `<IntakeOpenRunLink runId={researchRun?.id ?? null} />` at `:1220`. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Funnel unit suite | `npx vitest run src/lib/research/funnelLabels.test.ts` | 42 passed | ✓ PASS |
| Work-phase unit suite | `npx vitest run src/lib/research/workPhase.test.ts` | 16 passed | ✓ PASS |
| Full frontend suite | `npx vitest run` | 135 passed / 9 files | ✓ PASS |
| Typecheck | `npx tsc --noEmit -p tsconfig.json` | 0 errors | ✓ PASS |
| i18n audit (parity only; DEF-22-03 blind to interpolated keys) | `node scripts/i18n-audit.mjs` | PASS, exit 0 (107 unrelated CHECK-D advisories) | ✓ PASS |
| ESLint react-hooks on touched files | `npx eslint <3 files>` | 0 `rules-of-hooks`, 1 pre-existing `exhaustive-deps` warning (unrelated line) | ✓ PASS |
| `run-research` gone from frontend | `grep -rn "run-research" frontend/src \| wc -l` | 0 | ✓ PASS |
| Locale key-count parity | direct JSON leaf-count | intake: 634/634/634; admin: 365/365/365 | ✓ PASS |
| No backend/infra/tribunal touched | `git diff --stat 5f759a7..HEAD -- backend infra tribunal` | empty | ✓ PASS |
| `intake-phase.ts` untouched | `git diff 5f759a7..HEAD -- lib/intake-phase.ts` | empty; last change is ancestor of phase start | ✓ PASS |

No server, no deploy, no research run was started to produce any of the above — all are static/tree-level checks, consistent with the phase's zero-spend design.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|--------------|--------|----------|
| UAT-22-F1 | 23-01 | Funnel renders engine snake_case keys; needs business labels + tooltips, all 3 locales | ✓ SATISFIED | All 18 keys labelled and tipped in en/nl/fr; CR-01 (label/tooltip contradiction) and CR-02 (tooltip clipping) fixed in review pass, verified in code. |
| UAT-22-F4 | 23-02, 23-03 | Work-phase banner says "running" after research has finished; instructs waiting on `run-research` | ✓ SATISFIED | Banner now derives presentation from the live run status; `run-research` sentence deleted; operator-facing `statusBanner.in_research` also fixed (correctly re-scoped from the UAT's inaccurate "client-facing" framing, recorded in `deferred-items.md`). |

`UAT-22-F1` and `UAT-22-F4` are not tracked as formal `REQ-*` IDs in `.planning/REQUIREMENTS.md` (that file has no Phase 23 entries) — they are UAT gap IDs from `22-UAT.md`'s `## Gaps` section, which is the correct and only source for this phase per its PLAN frontmatter. No orphaned requirement IDs found: both IDs declared in PLAN frontmatter (`23-01: [UAT-22-F1]`, `23-02`/`23-03: [UAT-22-F4]`) match exactly the two gap entries in `22-UAT.md`.

### Anti-Patterns Found

None blocking. Scanned all files modified across the phase (`git diff --stat 5f759a7..HEAD -- frontend`) for `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` and stub-return patterns — none found in the delivered code. The five items the code review found (CR-01, CR-02, WR-01, WR-02 partial, WR-05) were all fixed post-review and independently re-verified above by direct code and locale-file inspection, not by trusting the SUMMARY's claim.

Three review findings remain deliberately open, correctly logged rather than silently dropped:
- **WR-03 / DEF-23-04** — the dead `ResearchRunProgress` component subtree still calls `useActiveResearchRun` internally; nothing currently imports it, so the one-stream invariant rests on a convention, not a gate. Logged, not fixed — acceptable given phase scope (this phase did not introduce the dead subtree; Phase 22's D-22-5 did).
- **WR-04 / DEF-23-05** — the funnel ⓘ tooltip is mouse-only (non-focusable `<span>`, `aria-label` on a role-less element), pre-existing pattern in this file, not introduced by Phase 23. Logged, not fixed.
- **DEF-23-03** — `paused` still fuses `parked` (resumable) and `needs_input` (fresh-attempt-only); the misleading COPY was fixed ("see what it needs" instead of "continue it"), the presentation SPLIT is deferred. This is an honest partial fix, correctly represented as partial rather than closed.
- **IN-01/IN-02/IN-03** (info-severity) — not fixed, not claimed fixed; correctly left out of the "fixed" list in the post-execution context.

None of these block the phase goal: the goal is legibility and honesty of what's shown, and all of the above are either pre-existing patterns unrelated to Phase 23's introduction, or an honestly-partial fix that already improved the reported defect without over-claiming completeness.

### Human Verification Required

None. Every truth above is resolvable by static code inspection, direct JSON reads, and typecheck/test/lint runs — no visual rendering, no interaction timing, and no live-run behavior is asserted by this phase's must-haves. (The phase's own SUMMARY/REVIEW honestly state that no rendering test exists for the banner or funnel-row component — confirmed here: `vitest.config.ts` only includes `src/**/*.test.ts`, and zero `.test.tsx` files exist in the repo. That gap is a known, disclosed limitation of the test harness, not a phase failure — the observable behavior it would cover is instead pinned by the underlying pure-function tests (`workPhase.test.ts`, `funnelLabels.test.ts`) plus direct source-level wiring checks performed in this verification.)

### Gaps Summary

No gaps found. All 15 must-haves across the three plans verified directly against the codebase at HEAD (`584a3f2`), not inferred from SUMMARY/REVIEW text. The five post-execution-context "fixed" claims (CR-01, CR-02, WR-05, WR-01, WR-02-partial) were independently re-verified by reading the actual source/locale files and re-running the test suites — all landed as claimed. The phase's zero-spend, frontend-only, no-status-split constraints all hold (confirmed by empty diffs on `backend/infra/tribunal` and `lib/intake-phase.ts`).

The phase is honest about what it does NOT prove: nothing here was observed running in a browser, no deploy occurred, and no rendering test exists for the banner or funnel row. This verification treats that as a disclosed, structural limitation of the harness (no React Testing Library, no `.tsx` test convention in this repo) rather than as a phase defect — the wiring itself (prop reaching the branch, single stream, link survival) was checked here by direct source inspection rather than by trusting the SUMMARY's narration.

---

_Verified: 2026-08-13T15:10:00Z_
_Verifier: Claude (gsd-verifier)_
