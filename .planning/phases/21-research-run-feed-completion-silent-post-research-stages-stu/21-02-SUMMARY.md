---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 02
subsystem: ui
tags: [react, tanstack-router, vitest, i18n, research-run, verification]

# Dependency graph
requires:
  - phase: 15.3-research-run-page
    provides: "the dedicated run page, its card/feed sibling rule, and locateResearchRun id resolution"
  - phase: 16-verification-report
    provides: "VerificationReport component + the superadmin getVerification seam"
provides:
  - "canHaveVerificationReport — the pure, enumerated status rule for whether a run can have a verification report"
  - "The verification report reachable from /admin/pulse/runs/:runId as a sibling of the card and the feed"
  - "10 named vitest assertions pinning all eight run statuses plus unknown/empty"
affects: [21-08, run-page-uat, verification, post-research-evidence]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure availability rules extracted to their own .ts module so they are MEASURED by vitest rather than asserted in a comment"
    - "Enumerated status sets over derived-or-negated ones at evidence gates"

key-files:
  created:
    - frontend/src/lib/research/verificationGate.ts
    - frontend/src/lib/research/verificationGate.test.ts
  modified:
    - frontend/src/routes/admin.pulse.runs.$runId.tsx

key-decisions:
  - "The five-status set is ENUMERATED, never derived from RESEARCH_TERMINAL and never a negation — terminality answers a different question that merely shares today's answer, and a negation defaults unheard-of statuses INTO the affordance"
  - "Gate on whether a report CAN exist (status), not on which RunStatusCard branch renders (D-11) — failed and cancelled are exactly the two states the embedded intake card discards"
  - "Mounted lazily rather than hidden behind CSS: one request, made only when the operator asks, and VerificationReport's own inline error is the honest answer for a run with no report"
  - "Reused verification.viewAction / verification.hideAction — zero new i18n keys, so the hard CHECK B locale gate needed no locale edit in three files"
  - "Reworded the in-code comment so canHaveVerificationReport(status) appears exactly once: the plan's own comment instruction collided with its own exactly-once grep criterion"

patterns-established:
  - "Availability gate as a pure module: status in, boolean out, one named test per status so a regression fails a test whose NAME says what was lost"

requirements-completed: [SC4, D-10, D-11]

# Metrics
duration: 42min
completed: 2026-08-10
---

# Phase 21 Plan 02: Verification Report on the Run Page Summary

**`canHaveVerificationReport` — an enumerated five-status rule pinned by 10 named vitest assertions — now gates a lazily-mounted `VerificationReport` between the status card and the activity feed on `/admin/pulse/runs/:runId`, with zero new i18n keys and zero changes to the reused component.**

## Performance

- **Duration:** ~42 min
- **Started:** 2026-08-10T15:59Z
- **Completed:** 2026-08-10T16:41Z
- **Tasks:** 2 of 3 complete (Task 3 is a blocking operator checkpoint — NOT yet done)
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments

- The claims-verification evidence the operator named twice in UAT is now reachable from the
  page built to hold it, without navigating back to the intake detail card.
- D-11 is **measured, not asserted**: `failed` and `cancelled` are pinned true by tests whose
  names state what a future edit would destroy, and `queued` / `running` / `needs_input` are
  pinned false.
- The report is a **sibling** of the card and the feed, so no future status branch can take it
  away — the structural defect the embedded intake card still has.
- An unknown status returns **false**, so a rolling deploy cannot default a new status into an
  affordance the seam would refuse.

## Task Commits

1. **Task 1: The availability rule, as a pure module with tests** — `71bced7` (feat)
2. **Task 2: Mount the report on the run page as a sibling** — `0c26ff9` (feat)
3. **Task 3: Operator checkpoint** — ⏸ **NOT EXECUTED — awaiting the operator**

## Files Created/Modified

- `frontend/src/lib/research/verificationGate.ts` — the pure rule. `canHaveVerificationReport(status)`
  returns true for `completed`, `completed_degraded`, `failed`, `cancelled`, `parked`, and false
  for everything else including any status this build has never heard of. The docstring records
  the reason for each of the five, and for each of the three exclusions.
- `frontend/src/lib/research/verificationGate.test.ts` — 10 named assertions: all eight run
  statuses individually, plus an invented string and the empty string. Deliberately eight named
  tests, not one table loop, so a regression names what was lost instead of a row index.
- `frontend/src/routes/admin.pulse.runs.$runId.tsx` — two imports, one `useState` declared with
  the other hooks above the early returns, one guarded JSX block between `RunStatusCard` and the
  truncation notice, and one extended SECURITY paragraph in the module header.

## Verification Evidence

| Gate | Command | Result |
|------|---------|--------|
| Task 1 tests | `npx vitest run src/lib/research/verificationGate.test.ts` | **10 passed / 0 failed** (bar was ≥9) |
| Full suite | `npx vitest run` | **5 files, 46 tests, all passed** |
| Type-check | `npx tsc --noEmit -p tsconfig.json` | **clean, exit 0** |
| i18n audit | `node scripts/i18n-audit.mjs` | **PASS — A/B/C clean, exit 0**, 107 pre-existing CHECK D advisories, **zero of them in this file** |
| Build | `npm run build` | **exit 0** ("built in 1m 43s") |
| Lint | `npm run lint` | ⚠ **red — pre-existing, see Deviation 2 + DEF-21-01** |

**`git diff --name-only` for Task 2 — the exact output, as the plan requires:**

```
frontend/src/routes/admin.pulse.runs.$runId.tsx
```

Exactly one path. No file under `frontend/src/locales/`, none under `frontend/src/components/`,
and `VerificationReport.tsx` is imported and **not modified** — which is D-10 proven rather than
claimed.

**Structural criterion (sibling, not nested), by line number:**

`<RunStatusCard` at **296** → `canHaveVerificationReport(status)` at **325** → `{truncated &&` at
**348**. The block sits between the card and the truncation notice, exactly as specified.

**Grep criteria:**

- `canHaveVerificationReport(status)` — **exactly 1** match (see Deviation 3).
- `VerificationReport` — matches both an import line (13) and a JSX mount (336).
- `intakeId={intakeId}` and `runId={runId}` — both match at the mount (337, 338).
- `RESEARCH_TERMINAL` in `verificationGate.ts` — **no matches**, so the set is enumerated, not derived.
- `canHaveVerificationReport("failed")` / `("cancelled")` in the test file — **2** matches (bar was ≥2).

**Vitest file count note:** the plan's verification step says "all six test files green"; this
worktree has **five** (four pre-existing + the one added here). The sixth belongs to sibling plan
21-01, which is a separate parallel worktree in the same wave. Not a defect — an artifact of the
plan being written against the post-wave tree.

## Decisions Made

- **The set is enumerated by hand.** `RESEARCH_TERMINAL` in `lib/api/research.ts` happens to hold
  the same five strings today, and deriving from it would have been one line. It was rejected on
  purpose: terminality answers "when does the stream stop", which is a different question that
  merely shares an answer right now, and a future edit made for the stream's own reasons would
  silently move this gate. A negation (`!queued && !running`) was rejected for the worse reason:
  it defaults every status nobody has thought of INTO the affordance.
- **The report is mounted lazily, not hidden with CSS.** `VerificationReport` fetches on mount, so
  lazy mounting means a run whose report does not exist costs exactly one request, made only when
  the operator asks for it, and shows one honest inline error.
- **`intakeId` is passed directly, with no second null guard.** The `locateFailed || !intakeId`
  early return has already run at that point; a redundant guard would read as though the
  resolution could still have failed and would invite a future reader to add a fallback path
  that cannot be reached.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `node_modules` absent in a fresh worktree**

- **Found during:** Task 1 (running the vitest acceptance command)
- **Issue:** The worktree checkout carries no `node_modules`, so `npx vitest` could not resolve
  `vitest/config` or `vite-tsconfig-paths` and failed at config load. Worse, `npx` began
  auto-downloading `vitest@4.1.10` from the registry — a *different major* from the pinned
  `^3.2.4`, and exactly the unverified-package-fetch pattern the threat model forbids.
- **Fix:** `npm ci` in `frontend/` — restoring the **committed lockfile**, never `npm install`,
  per the standing project rule. This installs no new package and resolves no new name; it
  materializes versions already pinned in `package-lock.json`. The subsequent run used the
  correct pinned **vitest 3.2.6**.
- **Files modified:** none tracked — `git status` after `npm ci` showed only the two new source
  files, confirming `package.json` and `package-lock.json` were untouched, which is itself one of
  Task 1's acceptance criteria and the T-21-02-SC mitigation.
- **Verification:** `git status --short` clean of any manifest change; vitest ran on 3.2.6.
- **Committed in:** n/a (no tracked change)

**2. [Out of scope — logged, NOT fixed] `npm run lint` does not exit 0, and did not at HEAD either**

- **Found during:** Task 2 (the `npm run lint` acceptance criterion)
- **Issue:** Two independent causes, neither caused by this plan.
  (a) `core.autocrlf=true` on this machine checks the worktree out as CRLF while `.prettierrc`
  leaves `endOfLine` at `"lf"`, so **every file in the tree** fails with ``Delete `␍` `` —
  **28,046 problems**, including files this plan never touched such as `frontend/vitest.config.ts`.
  (b) Filtering that noise leaves **two** genuine formatting drifts, both on **pre-existing lines**
  of `admin.pulse.runs.$runId.tsx` (the `useRunEvents` destructure and `EmptyFeed`'s return).
- **Proof it is pre-existing:** `git show HEAD:...$runId.tsx` was exported to a scratch path and
  checked with `prettier --config .prettierrc --end-of-line auto`, which removes the CRLF variable
  entirely. **The untouched HEAD version still fails.** The lint gate was therefore already red at
  `eac6f2b`.
- **This plan's own contribution: zero.** `npx eslint` on all three touched files, with the CRLF
  errors filtered, reports only those two pre-existing lines.
- **Why not fixed:** the scope boundary forbids fixing pre-existing failures in code this task did
  not change, and reformatting those hunks would put unrelated churn into a diff whose acceptance
  criteria explicitly measure that it touches exactly one path.
- **Logged to:** `deferred-items.md` as **DEF-21-01**, with a recommended follow-up (pin
  `endOfLine` in `.prettierrc`, then one dedicated `prettier --write` commit).

**3. [Rule 1 - Contradictory acceptance criteria] The plan's own comment instruction collided with its own grep criterion**

- **Found during:** Task 2 (checking the grep criteria)
- **Issue:** Task 2(e) instructs the comment to record that "the gate is
  `canHaveVerificationReport(status)` and NOT the card's success branch (D-11)". Writing that
  verbatim put the literal string in the file **twice** — once as prose, once as code — while the
  acceptance criterion requires it to match **exactly once**. Both cannot hold as written.
- **Fix:** reworded the comment to say the gate is `canHaveVerificationReport`, **applied to the
  run's own status**, and added that there is exactly one call to it on purpose. The decision the
  plan wanted recorded is fully preserved; the literal call-site form now appears only at the call
  site.
- **Rationale:** the criterion's evident purpose is "there is ONE gate call site, not two". A
  comment that satisfies the grep by *talking about* the gate would defeat that purpose — the
  known "windowed greps match prose about the thing" failure mode. Resolving in favour of the
  purpose, and reporting the collision rather than silently picking one.
- **Files modified:** `frontend/src/routes/admin.pulse.runs.$runId.tsx`
- **Verification:** `grep -c 'canHaveVerificationReport(status)'` returns **1**; tsc, i18n audit
  and build all re-run green after the reword.
- **Committed in:** `0c26ff9`

**4. [Housekeeping] `routeTree.gen.ts` restored after the build touched it**

- **Found during:** Task 2 (pre-commit `git status`)
- **Issue:** `npm run build` regenerated `frontend/src/routeTree.gen.ts`, which showed as modified.
- **Fix:** `git diff --stat` on it was **empty** — the difference was line endings only, no content
  change — so it was restored with a file-scoped `git checkout -- frontend/src/routeTree.gen.ts`.
  No blanket reset, no `git clean`.
- **Verification:** `git diff --name-only` then listed exactly the one intended path, satisfying
  the Task 2 criterion.

---

**Total deviations:** 4 — 1 blocking auto-fix (Rule 3), 1 criteria-collision resolution (Rule 1),
1 housekeeping, 1 out-of-scope item logged and deliberately not fixed.
**Impact on plan:** No scope creep. No new dependency, no locale edit, no change to
`VerificationReport.tsx`, `RunStatusCard.tsx`, `RunFeed.tsx`, `RunActions.tsx`,
`ResearchRunProgress.tsx`, or anything under `frontend/src/components/ui/`.

## Issues Encountered

- **The stale-base trap fired again — 24th consecutive time.** The worktree forked at `a3a0c96`,
  not the expected `eac6f2b`. `git merge-base` caught it, `git reset --hard` corrected it, and the
  positive-presence sentinels (`21-02-PLAN.md`, `21-CONTEXT.md`) confirmed the corrected tree
  before a single edit was spent. Worth noting that a `rev-list --count` check would have read
  green here.
- **`npx` tried to auto-fetch a wrong-major vitest** when `node_modules` was missing. Caught
  because the run failed loudly rather than silently; resolved with `npm ci` from the committed
  lockfile. This is a live instance of the reason the project rule says `npm ci`, never
  `npm install`.

## Threat Flags

None. This plan adds no route, no verb, no parameter and no new caller. `intakeId` continues to
come only from `locateResearchRun(runId)` and never from a query parameter, and the module
header's SECURITY paragraph was extended to record that the verification verb is superadmin-gated,
space-scoped and existence-hiding exactly like every other verb the page calls. T-21-02-SC is
satisfied by construction: nothing was installed and both manifests are provably unchanged.

## Known Stubs

None. The gate is a real enumerated rule with real assertions, and the report is the existing
component wired to live ids — no placeholder data, no empty-array-to-UI path.

## ⏸ CHECKPOINT — Task 3 is NOT complete

Task 3 is `checkpoint:human-verify` with `gate="blocking"`. Execution stopped here as the plan
requires. **No operator response has been recorded, because none has been given.** The plan
requires that response be recorded VERBATIM in this file — a paraphrase of a UAT observation is
how a defect becomes a rumour — so this section stays open until the operator speaks.

**Operator verbatim response:** _(awaiting — do not fill this in from inference)_

The walkthrough put to the operator is reproduced in the checkpoint return. It is verifiable on
RECORDED data with no spend; no run is to be triggered.

## Next Phase Readiness

- SC4, D-10 and D-11 are implemented and machine-verified; they are **not yet operator-verified**.
- Deploy surface for this plan is `nestor-frontend` only. Per D-02, **re-derive the surface from
  the actual diff at deploy time** rather than trusting that line — that rule is what caught
  `nestor-api` on 2026-08-06.
- No migration, no new event kind, no schema change.
- Sibling plan 21-01 adds the sixth test file this plan's verification step expects.
- **Blocker:** the operator checkpoint. Nothing about this plan should be marked done until it
  clears.

---
*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Plan 02 — tasks 1-2 complete, task 3 awaiting operator*
*Completed: 2026-08-10*
