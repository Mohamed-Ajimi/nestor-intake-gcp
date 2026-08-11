---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 04
subsystem: frontend-intake-detail
tags: [d-22-5, intake-detail, research-run, navigation, dead-code-removal]
requires:
  - "frontend/src/components/intake/ResearchRunProgress.tsx (useActiveResearchRun, OpenRunLink)"
  - "frontend/src/routes/admin.pulse.runs.$runId.tsx (the run page being linked to)"
provides:
  - "IntakeOpenRunLink — the intake page's link-only research surface"
  - "An intake detail page with no embedded research feed, stage list or verification report"
affects:
  - "plan 22-06 (renames the run route file; the import line into it is unchanged either way)"
  - "plan 22-09 UAT (walks the intake → run navigation path)"
tech-stack:
  added: []
  patterns:
    - "Wrapper component keeps a non-exported link definition reusable without exporting it"
key-files:
  created: []
  modified:
    - "frontend/src/components/intake/ResearchRunProgress.tsx (+31, -0)"
    - "frontend/src/routes/admin.pulse.intakes.$id.tsx (+33, -70)"
decisions:
  - "The 'Open run' link was preserved by adding IntakeOpenRunLink rather than by moving OpenRunLink out of the component — one link definition, five render sites"
  - "RESEARCH_SURFACE_STATUSES survives and now gates the link alone; its comment was rewritten to say so"
  - "Two acceptance criteria were unsatisfiable as literally written and were reconciled to their stated purpose (see Deviations)"
metrics:
  duration: ~13 min
  tasks: 2
  files: 2
  completed: 2026-08-11
---

# Phase 22 Plan 04: Remove the Activity Feed from the Intake Page Summary

Took the embedded research feed off the intake detail page per D-22-5 while keeping the "Open run"
link alive through a new `IntakeOpenRunLink` wrapper — the one thing a naive reading of D-22-5 would
have destroyed.

## THE LOAD-BEARING FACT: the "Open run" link was preserved, and here is exactly how

A later reader will want to check this above everything else, because the naive removal deletes the
app's only entry into the run page by accident.

**Mechanism.** `OpenRunLink` (`ResearchRunProgress.tsx:214`) is defined *inside* the component that
was being removed, and before this plan it was rendered *only* from that component's four card
branches. Deleting the `<ResearchRunProgress>` element alone would therefore have left the app with
no navigation into `/admin/pulse/runs/:runId` at all — only a bookmarked URL.

The fix is a new exported wrapper in the same file:

```
IntakeOpenRunLink({ intakeId })
  → useActiveResearchRun(intakeId)     // the only client-side intake → run-id lookup
  → <OpenRunLink runId={run.id} />     // the SAME single definition, not a copy
  → <Link to="/admin/pulse/runs/$runId" params={{ runId }}>
```

**Where the path now lives:** `frontend/src/routes/admin.pulse.intakes.$id.tsx:1189`, mounted under
the unchanged `intake.status && RESEARCH_SURFACE_STATUSES.has(intake.status)` guard — so it is
offered on `in_research`, `delivered` and `archived`, exactly as the removed card was.

**Proven, not asserted.** A repo-wide `grep -rn "/admin/pulse/runs" src --include=*.tsx` (excluding
`routeTree.gen.ts`) returns 5 hits, of which exactly one is a real entry point:

| Hit | Kind | Entry point? |
|---|---|---|
| `ResearchRunProgress.tsx:218` | the `<Link>` inside `OpenRunLink` | **YES — reached from the intake page via `IntakeOpenRunLink`** |
| `RunActions.tsx:192` | post-retrigger `navigate` | No — only fires once already ON the run page |
| `admin.pulse.intakes.$id.tsx:174` | a comment | No |
| `admin.pulse.runs.$runId.tsx:20` | a comment | No |
| `admin.pulse.runs.$runId.tsx:44` | the route's own `createFileRoute` | No |

`OpenRunLink` remains **non-exported** with **one** definition and **five** render sites (the four
pre-existing card branches plus the new wrapper).

## What Was Built

**Task 1 — `IntakeOpenRunLink` (commit `39cc0fa`).** Purely additive: 31 insertions, 0 deletions.
Renders `null` until a run id is known, so an intake with no run shows no dead link. The
`ResearchRunProgress` component body, `useActiveResearchRun`, the four `OpenRunLink` render sites and
the pre-existing dead `export { triggerResearch }` (DEF-22-01) were all left untouched as instructed.

**Task 2 — the removal (commit `21a17d4`).** 33 insertions, 70 deletions on the intake route:
- `<ResearchRunProgress …>` → `<IntakeOpenRunLink intakeId={intake.id} />`, guard unchanged.
- Deleted the three handlers whose only caller was that element: `onRetryResearch`,
  `onResumeResearch`, `onCancelResearch`. Their equivalents are on the run page via `RunActions`.
- Import line: `IntakeOpenRunLink` replaces `ResearchRunProgress`; `cancelResearch` and
  `resumeResearch` dropped; **`triggerResearch` kept** — `onStartAutoResearch` still calls it.
- `RESEARCH_SURFACE_STATUSES` **kept**, comment rewritten to describe the link it now gates.
- The block comment records D-22-5 verbatim and flags the deliberate reversal of Phase 21's R2.

Confirmed gone from the intake page (all `grep -c` → 0): `VerificationReport`, `RunFeed`,
`RunStatusCard`, `AuditBodyPanel`, `openResearchStream`, `stage_detail`. And
`ResearchRunProgress.tsx` still exists on disk and still exports `useActiveResearchRun`, so
`admin.pulse.runs.$runId.tsx:11` still resolves.

## Verification Results

| Gate | Result | vs. recorded baseline |
|---|---|---|
| `npx tsc --noEmit` | exit **0** | matches |
| `npx vitest run` | **61 passed, 0 failed** (6 files) | matches (≥61 required) |
| `node scripts/i18n-audit.mjs` | **`RESULT: PASS`**, exit 0, 107 CHECK D advisories | matches exactly (107) |
| eslint on the 2 files | **0 non-`prettier/prettier` errors**; 4 warnings, all pre-existing | DEF-21-01 respected |
| `git diff --name-only` vs base | exactly the 2 files in `files_modified` | `routeTree.gen.ts` untouched |

The 4 eslint warnings were each confirmed to sit on lines this plan never touched:
`ResearchRunProgress.tsx:158` (`export function useActiveResearchRun`) and `:969`
(`export { triggerResearch }` — the pre-existing DEF-22-01 dead export), plus
`admin.pulse.intakes.$id.tsx:458` (a pre-existing `useCallback` dep) and `:624` (a pre-existing
unused `eslint-disable`). **Zero introduced by this plan.**

`npm run build` was deliberately NOT run (plan 22-06 owns `routeTree.gen.ts`).

## Deviations from Plan

### Two acceptance criteria were unsatisfiable as literally written — reconciled to purpose, not weakened

**1. `grep -c "ResearchRunProgress" …$id.tsx` returns `0` — IMPOSSIBLE.**
The plan's own Task 2(c) mandates importing `IntakeOpenRunLink` "from the same module", and that
module is *named* `ResearchRunProgress.tsx`. The import path therefore contains the string
unavoidably. The literal minimum is **1**, not 0.

- **Measured:** 1 — and that single hit is the module path on line 57.
- **Purpose** ("neither the import nor the element remains") **is met**, verified in the stronger
  form: `grep -c '<ResearchRunProgress'` → **0**, and
  `grep -cE 'import \{[^}]*\bResearchRunProgress\b'` → **0**. No symbol import, no element.

**2. `grep -c "triggerResearch" …$id.tsx` returns `2` (import + call) — unsatisfiable without
deleting a correct pre-existing comment.**
Base count was **5** across 5 lines. Removing the three handlers kills 2 of them (the call inside
`onRetryResearch` and a `triggerResearch` mention inside `onResumeResearch`'s docstring), leaving
**3**: the import, the *pre-existing and still-accurate* prose mention in `onStartAutoResearch`'s
docstring (line 784), and the call itself. Hitting 2 literally would require deleting a truthful
comment — which is precisely the "guard red on correct code invites deleting correct code" trap.

- **Measured:** 3 (1 import + 1 pre-existing prose + 1 call).
- **Purpose** (`triggerResearch` survives and is still wired) **is met**, verified in the stronger
  form: exactly **1** import line and exactly **1** `await triggerResearch(` call site.

To keep both counts as close to literal as possible I also **reworded my own new comments** to avoid
gratuitously repeating these symbols. That brought `IntakeOpenRunLink` to exactly **2** (import +
mount) and the three-handler grep to exactly **0**, both as the plan specified. `RESEARCH_SURFACE_STATUSES`
is **2** and `useActiveResearchRun` is **0**, both exactly as specified.

### [Rule 1 - Bug] Fixed a comment the removal made false

`onStartAutoResearch`'s docstring said a `load()` re-fetch "swaps the banner for the live
ResearchRunProgress panel below". After this plan there is no panel below, so the comment actively
misdescribed the code. Rewritten to say the banner is swapped for the "Open run" link. Not listed in
the plan's task steps; left as-is it would have been a stale comment shipped in the same commit that
falsified it.

### Minor: a layout wrapper around the link

The plan says replace the element with `<IntakeOpenRunLink intakeId={intake.id} />`. I wrapped it in
`<div className="px-6 pb-6">`. Rendered bare, the link would hug the page's left edge with no gutter —
the removed component supplied its own padding. `px-6` is this page's established gutter (the status
banner directly above uses `px-6 py-3`). No effect on any acceptance criterion. 22-UI-SPEC.md is
silent on this surface (it contains no reference to the intake page, `D-22-5` or "Open run"), so no
design contract was crossed.

### Environment: `npm ci` was required

`frontend/node_modules` is absent in a fresh worktree (gitignored, not copied by the worktree spawn),
so `npx tsc` initially resolved to the decoy "this is not the tsc command you are looking for" stub.
Installed with `npm ci --prefix frontend` (868 packages, 32s) from the **committed lockfile** —
`npm install` was NOT used and neither `package.json` nor `package-lock.json` changed.

## Out-of-Scope Discoveries

⚠ Per the plan's `<output>`, this is a wave-1 plan and must NOT create `deferred-items.md` (plan
22-01 owns it). Recorded here instead for whoever owns that file.

**Two now-unreferenced locale keys.** Deleting `onResumeResearch` orphaned
`intakeDetail.toast.researchResumed` and `intakeDetail.toast.researchResumeFailed`, which still exist
in all three locale files (`src/locales/{en,fr,nl}/admin.json`, en at lines 150-151) with zero source
referrers. Left in place: the plan's scope explicitly excluded locale keys, the i18n audit checks for
*missing* keys (so it stays green), and unused keys are harmless. Candidate for a future cleanup, not
a defect.

Note that the sibling keys `research.cancelError` / `research.cancelOk` are **still live** — used by
`RunActions.tsx:169,172` — so they were correctly not disturbed.

## Threat Model Notes

- **T-22-09 (DoS, accepted):** confirmed accurate. `IntakeOpenRunLink` mounts exactly ONE SSE
  connection — the same one the removed component already opened on this page. Net connections
  **decrease**; the stream still self-closes on a terminal run.
- **T-22-10 (EoP, mitigated):** unchanged posture. `runId` comes from the server's own stream for the
  resolved intake; nothing is taken from user input.
- **T-22-11 (Info disclosure, mitigated):** the link's survival is proven above and by grep.
- **T-22-SC:** no package was added. `package.json` / `package-lock.json` unchanged (`npm ci` installs
  from the existing lockfile only).

No new security-relevant surface was introduced, so there are no threat flags.

## Known Stubs

None. `IntakeOpenRunLink` is fully wired to a real data source (`useActiveResearchRun` → the live SSE
stream) and renders a working router `<Link>`.

## Self-Check: PASSED

- `frontend/src/components/intake/ResearchRunProgress.tsx` — FOUND (exists, exports
  `useActiveResearchRun` ×1 and `IntakeOpenRunLink` ×1)
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — FOUND (modified)
- Commit `39cc0fa` — FOUND in `git log`
- Commit `21a17d4` — FOUND in `git log`
- No files deleted by either commit (`git diff --diff-filter=D` empty for both)
- Working tree clean, no untracked stragglers
