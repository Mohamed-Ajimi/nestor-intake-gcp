---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 06
subsystem: frontend-routing
tags: [d-22-1, routing, verification-report, tanstack-router, route-split]
requires:
  - "frontend/src/components/intake/VerificationReport.tsx (mounted with intakeId + runId)"
  - "frontend/src/lib/api/research.ts (locateResearchRun — the only intake source)"
  - "frontend/src/lib/research/verificationGate.ts (the availability rule, single call site kept)"
  - "frontend/src/locales/{en,fr,nl}/intake.json (verification.backToRun from plan 22-03)"
provides:
  - "/admin/pulse/runs/:runId/verification — the verification report as its own page"
  - "admin.pulse.runs.$runId.index.tsx — the run page as a leaf index sibling"
  - "A regenerated routeTree.gen.ts registering both routes under AdminPulseRoute"
affects:
  - "plan 22-07 (restyles VerificationReport; this plan gives it the page to live on)"
  - "plan 22-09 UAT (the runtime route match is confirmed there, not by a gate)"
tech-stack:
  added: []
  patterns:
    - "Index-sibling route naming (.index.tsx + .verification.tsx, no parent file) to keep both pages leaves and avoid a layout-route Outlet"
key-files:
  created:
    - "frontend/src/routes/admin.pulse.runs.$runId.verification.tsx (196 lines)"
  modified:
    - "frontend/src/routes/admin.pulse.runs.$runId.index.tsx (renamed from .tsx; +27, -38 in task 2)"
    - "frontend/src/routeTree.gen.ts (regenerated, +44/-21)"
decisions:
  - "Took the PRIMARY route option ($runId/verification sibling), not the admin.pulse.verification.$runId fallback"
  - "Neither existing to: call site required an edit — the generator's `to` union keeps the un-slashed form"
  - "The report page deliberately carries no status gate (measured fact 5); DEF-22-02 residual accepted"
  - "Four acceptance criteria were unsatisfiable as literally written and were reconciled to purpose (see Deviations)"
metrics:
  duration: ~45 min
  tasks: 2
  files: 3
  completed: 2026-08-11
---

# Phase 22 Plan 06: Verification Report as a Page Summary

Gave the verification report its own URL (`/admin/pulse/runs/:runId/verification`) by renaming the run
page to an index sibling so both pages stay routing **leaves**, and replaced the run page's inline
toggle with a `Link` — navigation, not a report body (D-22-1).

## Which route option was taken

**The PRIMARY option: `$runId/verification` as an index sibling.** The `admin.pulse.verification.$runId`
fallback in 22-UI-SPEC §1.1 was **not** needed — the rename caused no route-type churn at all, and
`npx tsc --noEmit` stayed at exit 0 throughout.

**No `to:` call site required an edit.** A later reader should not go looking for one. Measured fact 2
predicted this and the regenerated tree confirms it: the generator emits three different unions, and
while `fullPath` and `id` gain a trailing slash for an index route, the **`to` union keeps the
un-slashed form**:

```
interface FileRoutesByTo {
  '/admin/pulse/runs/$runId/verification': typeof AdminPulseRunsRunIdVerificationRoute
  '/admin/pulse/runs/$runId':             typeof AdminPulseRunsRunIdIndexRoute
}
```

So `ResearchRunProgress.tsx:218` and `RunActions.tsx:192` — both `to="/admin/pulse/runs/$runId"` —
stay valid untouched. `git diff --name-only 3a0d74e HEAD` lists neither file.

## THE LOAD-BEARING FACT: no Outlet was needed, and 22-04's entry link still lands on a page

The orchestrator's brief warned that converting the run route into a **parent** with `index` and
`verification` children would require an `<Outlet />` or the page goes blank (the Phase 18 scar). That
warning describes a route shape this plan deliberately **does not create**, and the distinction is the
whole point of the rename.

**There is no parent route.** `admin.pulse.runs.$runId.tsx` was renamed away and does not exist, so the
generator registers both files as **leaves** — verified in the real generated output, not assumed:

```
'/admin/pulse/runs/$runId/':             parentRoute: typeof AdminPulseRoute
'/admin/pulse/runs/$runId/verification': parentRoute: typeof AdminPulseRoute
```

The Outlet that renders them is the **pre-existing** one in `admin.pulse.tsx:19`, which I verified
rather than assumed — `<Outlet />` sits unconditionally inside `<ProductShell>`, and
`ProductShell.tsx:132` renders `{children}` in its `<main>`. Neither of my two files contains `Outlet`
or `useMatches` (`grep -cE` → **0** for both), so the `intake.$id.tsx:41-50` workaround was not
reproduced.

**The full entry-link chain, each hop verified:**

| Hop | Evidence |
|---|---|
| `IntakeOpenRunLink` → `to="/admin/pulse/runs/$runId"` | `ResearchRunProgress.tsx:218`, unedited |
| that `to` value is legal and maps to the index leaf | `FileRoutesByTo` block above; `tsc --noEmit` exit 0 |
| index leaf renders the run page | `admin.pulse.runs.$runId.index.tsx:44-46` → `component: ResearchRunPage` |
| the leaf is actually painted | `admin.pulse.tsx:19` `<Outlet/>` → `ProductShell.tsx:132` `{children}` |

The run page also still renders its card and feed: `<RunStatusCard>` ×1, `<RunFeed>` ×1,
`<RunActions>` ×1, fixed-height shell ×1 — all untouched.

⛔ The **runtime** match (does `/admin/pulse/runs/abc` paint the run page in a browser?) is not
provable by a gate and is confirmed once in operator UAT, plan 22-09 — exactly where the plan puts it.

## What Was Built

**Task 1 — the route split (commit `7e7b99c`).** `git mv` to `.index.tsx` with zero content edits, plus
a new 196-line `admin.pulse.runs.$runId.verification.tsx`:

- Cold open copied verbatim from the run page: `locateResearchRun(runId)` → `intakeId`, with
  `locating` / `locateFailed` state and a cancelled-cleanup flag, plus the cosmetic `getIntake` for
  `clientName`.
- `locating` → the run page's exact `Skeleton` triplet (`h-4 w-48`, `mt-3 h-8 w-96`, `mt-8 h-64 w-full`).
- `locateFailed || !intakeId` → `research.runPage.notFound` + back link, existence-hidden.
- Header per 22-UI-SPEC §1.5: breadcrumb `Pulse · Intakes · {clientName} · Run · Verification` (the
  `Run` crumb links back, `Verification` is an unlinked `<span>`), serif `h1`, mono meta row, a
  **Back to run** `Link` with `ArrowLeft`, and `border-l-4` in `#FF2D87` on the header block.
- Body: `<VerificationReport intakeId={intakeId} runId={runId} />` — exactly the two props.
- Shell: `mx-auto max-w-4xl` in the document flow. No fixed-height column, no nested scroll region, no
  ticker, no stream, no feed, no announcing region (`grep -cE 'calc\(100vh|overflow-y-auto|aria-live'`
  → **0**).
- A module header recording all five decisions the plan asked for, including why recreating
  `admin.pulse.runs.$runId.tsx` would silently break this page.

The generator then rewrote the index file's own id to `createFileRoute("/admin/pulse/runs/$runId/")`
— measured fact 3, confirmed — which is the file's only 1-line change in that commit.

**Task 2 — toggle becomes a link (commit `0a065df`).** +27/-38 on the run page:
- The `<button>` and the conditionally mounted `<VerificationReport>` → one
  `<Link to="/admin/pulse/runs/$runId/verification" params={{ runId }}>` with `ArrowRight` and the
  identical bordered mono classes.
- Removed `const [showVerification, setShowVerification]` (and its now-stale hook-ordering comment)
  and the `VerificationReport` import; added `ArrowRight` to the existing lucide import.
- The `canHaveVerificationReport(status)` guard is **byte-identical** to the base, with decisions 1
  and 2 of its comment preserved and decision 3 rewritten for D-22-1.

## Verification Results

| Gate | Baseline at `3a0d74e` | After both tasks |
|---|---|---|
| `npx tsc --noEmit` | exit **0** | exit **0** |
| `npx vitest run` | **77 passed / 7 files** | **77 passed / 7 files**, 0 failing |
| `node scripts/i18n-audit.mjs` | **PASS**, 107 advisories | **PASS**, 107 advisories |
| `npm run build` | exit 0 | exit 0 |
| eslint, 2 route files | — | **0 non-prettier**; the new file has **0 problems at all** |
| `git diff --name-only 3a0d74e HEAD` | — | exactly the **3** files in `files_modified` |

`verificationGate.test.ts` — the 10 tests the plan required be untouched — passes; that file was never
edited.

**Route tree criteria:** `verification` present ×9; the un-slashed `'to'` form present ×2; old file
absent; both new files present.

## Deviations from Plan

### ⚠ STALE BASE — 25th recorded occurrence, caught by the merge-base gate

The worktree spawned with `merge-base HEAD 3a0d74e` = **`a3a0c96`** — the same stale commit as all 24
prior occurrences, and Wave 1's three artifacts were absent. `git reset --hard 3a0d74e` corrected it
(784 files updated), after which all three positive-presence sentinels passed. **Had I trusted
`rev-list --count`, I would have built this plan on a tree without Wave 1's locale keys.**

### Measured fact 4 was wrong: `node_modules` is NOT present

The plan states "`node_modules` is already present". In a fresh worktree it is **absent** (gitignored,
not copied on spawn) — the same trap every Wave 1 executor hit. Installed with `npm ci --prefix frontend`
(868 packages, 51 s) from the **committed lockfile**; `npm install` was never used and
`package.json` / `package-lock.json` are byte-unchanged (T-22-SC intact). I also confirmed the real
compiler resolved afterwards (`tsc --version` → 5.9.3), not the decoy stub.

### Vitest baseline is 77, not 61

The plan's recorded baseline (61) predates Wave 1. Plan 22-03 added `citationIndex.test.ts` with 16
tests: 61 + 16 = **77 across 7 files**. The criterion "at least 61 passing" is satisfied with margin;
I record the real number so the next plan does not read 77 as unexplained drift.

### Four acceptance criteria were unsatisfiable as literally written — reconciled to purpose, with numbers

**1. `grep -cE "search|useSearch|intakeId=" verification.tsx` showing no query-parameter read.**
Literal measurement: **11**, and zero of them is a query parameter. Ten are the substring **"search"
inside "re*search*"** — `locateResearchRun`, `@/lib/api/research`, and the `research.runPage.*` locale
keys the plan itself mandates. The eleventh is `intakeId={intakeId}`, the prop the plan's own
`<interfaces>` block requires. A count of 0 is impossible.
- **Purpose (T-22-16: the intake id is resolved, never accepted) verified in the stronger form:**
  `useSearch` → **0**, `validateSearch` → **0**, `searchParams` → **0**, and of the three `setIntakeId`
  occurrences the only value-bearing write is `setIntakeId(res.data.intake_id)` from
  `locateResearchRun`. There is exactly one source of the intake id.

**2. `grep -c "canHaveVerificationReport" index.tsx` returns `2` — "it is 2 before this task".**
The stated baseline is wrong. Measured at `3a0d74e` it was **3**: the import (`:10`), a **comment**
mention in decision 2 (`:309`), and the one call (`:328`). Reaching 2 would require deleting that
comment line — which the plan's own Task 2(c) explicitly orders me to **keep** ("Keep decisions 1 and
2 from the existing comment"). This is the "guard red on correct code invites deleting correct code"
trap.
- **Measured after: 3** — identical composition to the baseline (import + comment + call).
- **Purpose (exactly ONE call site of the rule) verified in the stronger form:**
  `grep -c 'canHaveVerificationReport('` → **1**.

**3. `grep -c "VerificationReport" index.tsx` returns `0` — contradicts criterion 2 directly.**
`canHaveVerificationReport` **contains** the substring `VerificationReport`, so criterion 2 (which
demands that symbol appear) and this one (which demands the substring appear zero times) cannot both
hold. Measured: **3**, and every one is inside `canHaveVerificationReport`.
- **Purpose (the component is neither imported nor mounted here) verified in the stronger form:**
  `grep -c '<VerificationReport'` → **0**; `grep -cE 'import \{[^}]*\bVerificationReport\b'` → **0**;
  occurrences of `VerificationReport` **not** preceded by `canHave` → **0**.

**4. `verification.viewAction` returns `1` and `verification.hideAction` returns `0`.**
Both are unsatisfiable **alongside the plan's own Task 2(c)**, which dictates a comment stating "the
CTA reuses `verification.viewAction`, and `verification.hideAction` is now unused but stays in all
three locales". Writing that mandated comment necessarily puts both key names in the file. Measured:
**2** and **1**, the extras being that comment (`:316`, `:318`).
- **Purpose verified in the stronger form:** `t("verification.viewAction")` calls → **1**;
  `t("verification.hideAction")` calls → **0**. The key is unused in code and survives in all three
  locales (`grep -c '"hideAction"'` → 1 / 1 / 1), so CHECK A parity holds.
- I kept the comment rather than reword it away: it is the one place telling the next editor *why* an
  apparently-dead locale key must not be deleted, which is precisely the mistake it prevents.

### [Rule 1 - Bug] Corrected a module-header comment this task falsified

The security paragraph (`:32-38`) ended "...so **mounting the report** changes this page's
authorization surface not at all: it adds no route, no parameter and no new caller." After Task 2 the
report is not mounted here, and the sibling route *does* add a route — so the sentence actively
misdescribed the code in the same commit that falsified it. Rewritten to say the report now lives on
the sibling route, which inherits the same posture by placement, and that what remains here is a link
that reads nothing. Not in the plan's task steps; left alone it would have shipped as a false comment.

### `routeTree.gen.ts` shows as modified after a no-op build — EOL artifact, not drift

At the base commit, `npm run build` leaves `git status` reporting ` M frontend/src/routeTree.gen.ts`,
which looks like the generator disagreeing with the committed tree. It is not: a byte comparison
against `HEAD`'s blob returns **identical: true**. The repo has `core.autocrlf=true` while the file is
stored and rewritten as pure LF, so git flags a pending normalization with no content change. Measured
fact 4's "CONTENT diff of zero" is therefore correct in substance. The real post-rename diff is
`+44/-21` and is committed.

### Known deviation from 22-UI-SPEC, already ruled by the plan

22-UI-SPEC §1.1 says the report page gates on `canHaveVerificationReport`, and its States table
specifies a `verification.notAvailable` arrival. Measured fact 5 deliberately **narrows** this: the
page does not re-derive run status (`grep -c` → 0), and `verification.notAvailable` is **not** a key in
this phase. I followed the plan. The consequence is the accepted residual **DEF-22-02** — a bookmarked
URL for a still-`queued` run 404s at the intake-backend proxy and renders the generic
`verification.loadError` instead of a "not available yet" state. Unreachable via any UI path (the run
page link is gated), honest, and self-correcting via the retry button. Not "fixed" by adding the key,
per the plan's explicit instruction.

### Expected intermediate duplication

Between this plan and 22-07 the page shows `VerificationReport`'s own bordered container and title
beneath the page header. Measured fact 11 flags this as expected; 22-07 removes it.

## Threat Model Notes

| Threat | Disposition | Verification |
|---|---|---|
| T-22-16 (EoP, tenant hint in URL) | mitigate | **Verified.** No `useSearch` / `validateSearch` / `searchParams`; the only intake-id write comes from `locateResearchRun`. |
| T-22-17 (Info disclosure, guessed `runId`) | mitigate | **Verified.** Existence-hidden block copied verbatim; one message covers "no such run" and "not yours". |
| T-22-18 (DoS, SSE per visit) | mitigate | **Verified.** `useActiveResearchRun` → 0, `useRunEvents` → 0, `openResearchStream`/`EventSource` → 0. The page opens no stream. |
| T-22-19 (Spoofing, client route reaching the report) | accept | Superadmin-only by placement under `admin.pulse`; no new verb, parameter or caller. |
| T-22-SC (Tampering, installs) | mitigate | `npm ci` from the committed lockfile only; `package.json` / `package-lock.json` byte-unchanged. No registry package added. |

No new security-relevant surface beyond the plan's register, so there are **no threat flags**.

## Known Stubs

None. The page is fully wired: `locateResearchRun` resolves the intake, `getIntake` supplies the
client name, and `VerificationReport` fetches and renders real data with its own loading, error and
empty states.

## Self-Check: PASSED

- `frontend/src/routes/admin.pulse.runs.$runId.verification.tsx` — FOUND
- `frontend/src/routes/admin.pulse.runs.$runId.index.tsx` — FOUND
- `frontend/src/routes/admin.pulse.runs.$runId.tsx` — CONFIRMED ABSENT (required: keeps both siblings leaves)
- `frontend/src/routeTree.gen.ts` — FOUND, contains both routes
- Commit `7e7b99c` — FOUND in `git log`
- Commit `0a065df` — FOUND in `git log`
- No file deletions in either commit (`git diff --diff-filter=D` empty for both; the rename is tracked as `R`)
- No modifications to `STATE.md` or `ROADMAP.md` (orchestrator-owned)
- Working tree clean apart from this SUMMARY
