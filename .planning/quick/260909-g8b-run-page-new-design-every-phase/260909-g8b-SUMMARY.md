---
quick_id: 260909-g8b
status: complete
base_commit: aad9691
head_commit: fb23083
tasks: 4
commits: 5
---

# 260909-g8b — SUMMARY

The new grouped trace design is now the whole run page, for every phase, from the first event.

## Base commit

Worked from **`aad9691`** ("plan(260909-g8b): make the new trace design the whole run page,
every phase"), which was HEAD of the worktree branch `worktree-agent-a5206169def1e90c6` at
spawn. Verified before any edit:

```
$ git rev-parse HEAD
aad96911c9519b15fd8b9933b66235fb8f551f90
$ git merge-base --is-ancestor aad9691 HEAD && echo "BASE_OK"
BASE_OK: aad9691 is ancestor
```

No stale base. The worktree's `frontend/` tree was also byte-identical (modulo CRLF) to the
shared checkout at spawn, so nothing was read from a divergent copy.

`frontend/node_modules` was absent in the worktree, so `npm ci` was run once. **The lockfile
was not modified** and no dependency was added:

```
$ git status --short frontend/package-lock.json frontend/package.json
(empty)
```

## Commits

| Commit    | Task | What                                                                      |
| --------- | ---- | ------------------------------------------------------------------------- |
| `299981b` | 4.1  | **RED** — the shell contract test, failing against the old code            |
| `af5f569` | 1    | split `TraceSection` (shell) from `ResearchTraceBody` (deep-research body) |
| `eb7373c` | 2    | `FeedGroup` always renders the shell; `EmptyFeed` moved into one           |
| `203c052` | 3    | `RunStatusCard` container tokens matched to the shells                     |
| `fb23083` | 4    | mixed-run / empty-run / D-09 tests + offline harness fixture               |

## RED evidence — recorded before `RunFeed.tsx` was touched

The test was written first and run against the unmodified code. Two assertions carry the RED,
and both are **structural**, because a text assertion cannot tell the two designs apart —
"the phase title appears" is satisfied by the OLD divider row too.

### RED 1 — no section shells exist at all

```
 RUN  v3.2.6 .../agent-a5206169def1e90c6/frontend

 ❯ src/components/research/RunFeedSections.test.ts (1 test | 1 failed) 44ms
   × run feed sections — every phase renders in the new shell > gives a non-research run one
     section per phase, the title once, the summary in the header 41ms
     → expected +0 to be 2 // Object.is equality

⎯⎯⎯⎯⎯⎯⎯ Failed Tests 1 ⎯⎯⎯⎯⎯⎯⎯

 FAIL  src/components/research/RunFeedSections.test.ts > run feed sections — every phase
 renders in the new shell > gives a non-research run one section per phase, the title once,
 the summary in the header
AssertionError: expected +0 to be 2 // Object.is equality

- Expected
+ Received

- 2
+ 0

 ❯ src/components/research/RunFeedSections.test.ts:71:53
     69|
     70|     // One shell per phase — under the old design this count was zero …
     71|     expect(occurrences(html, "data-trace-section")).toBe(2);
       |                                                     ^
     72|
     73|     // The phase label is the section TITLE and is not also emitted as…

⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[1/1]⎯

 Test Files  1 failed (1)
      Tests  1 failed (1)
   Duration  17.61s
```

### RED 2 — the summary rendered BELOW its phase's rows, not in a header

Captured by temporarily commenting out the assertion above (restored immediately afterwards,
so the committed file contains both assertions):

```
 ❯ src/components/research/RunFeedSections.test.ts (1 test | 1 failed) 71ms
   × run feed sections — every phase renders in the new shell > gives a non-research run one
     section per phase, the title once, the summary in the header 68ms
     → expected 1351 to be less than 1084

AssertionError: expected 1351 to be less than 1084
 ❯ src/components/research/RunFeedSections.test.ts:81:44
     79|     expect(html).toContain("3 actions");
     80|     expect(html).toContain("Worked for 34s");
     81|     expect(html.indexOf("Worked for 12s")).toBeLessThan(html.indexOf("…
       |                                            ^
     82|     expect(html.indexOf("Worked for 34s")).toBeLessThan(html.indexOf("…

 Test Files  1 failed (1)
      Tests  1 failed (1)
```

Both went green after Task 2, with no assertion weakened.

## What changed

**Task 1 — `ResearchTrace.tsx` split.** `TraceSection` is now a phase-agnostic shell: the
`<section class="my-4 min-w-0 border border-ink/20 bg-paper text-ink [color-scheme:only_light]">`
with the serif `<h3>` header, an optional subline, a body slot, the collapsible "original
events" `<details>` footer and the `unmatched` notice. It knows nothing about executions,
tasks or providers. `ResearchTraceBody` holds the execution bands, question groups, task
badges and progress bar, logic unchanged. `ResearchTrace` remains as the thin composition of
the two, so `ResearchTrace.test.ts` keeps driving the same component — all 16 of its tests
pass unmodified.

Two deliberate choices inside the shell: the section carries `data-trace-section` as the
suite's structural hook (an attribute, so no styling can depend on it), and the `active` prop
renders the live badge in the header from the same value the rows' spinners use. The scope
caveat ("Researcher activity only — this does not indicate claim verification or report
readiness") moved **into the body** rather than staying in the subline, because it is a
statement about those bands and the run page needs the subline for the phase summary. It is
therefore still present on the deep-research section — the assertion for it in
`ResearchTrace.test.ts` and in the new mixed-run test both cover this.

**Task 2 — `RunFeed.tsx`.** The `grouped ? <ResearchTrace> : shown.map(renderEvent)` switch is
gone. Every `FeedGroup` renders a `TraceSection`:

- `title` = the divider row's text (the engine's own phase label). No stage vocabulary was
  added. Two fallbacks exist for feeds carrying no divider: a grouped body uses the trace
  title, anything else uses a new `research.runPage.feed.stageFallback` string — so a raw
  stage identifier such as `deep_research` never reaches a serif heading.
- `subline` = the summary row's content, parsed by `summaryLine()`, which is the summary
  branch's code lifted out of `FeedRow` verbatim — same `t()` keys, same order, same
  defensive meta reads, same "render nothing if it carries nothing" rule.
- Neither the divider nor the summary is rendered as a `FeedRow` any more. `FeedRow`'s two
  branches for them were **deleted**: `body` has always excluded both kinds, so after this
  change the branches were unreachable and could only ever reintroduce the duplicate.
- Body: grouped phases get `ResearchTraceBody` with the raw rows passed as `raw`; every other
  phase gets its rows via `renderEvent` directly, with the D-09 rule preserved verbatim as
  `isComplete && hasHiddenRows(body.length)`.
- Only the grouped body offers "original events". A plain-row phase already *is* its rows, so
  giving it a footer would print every line of it twice — asserted.
- `isRowLive`, `settledSeqs`, `cursorSeq`, `canDrill`/`onDrill`/`renderAfterRow` and the
  `activeExecutionId` logic work in both bodies, unchanged.

`EmptyFeed` moved out of the route into `frontend/src/components/research/EmptyFeed.tsx` and
renders inside a `TraceSection` titled with the run's status label. The title is **passed in**
rather than re-derived, so `statusLabel` keeps its single home in the route. The move was
necessary to make "an empty run is already the new design" testable at all — the route file
cannot be imported under the node-env suite without dragging the router in with it.

**Task 3 — `RunStatusCard`.** Container tokens only: `border-ink/30` on `bg-paperLight`
becomes `border-ink/20` on `bg-paper`, matching the shells below it. The accent left border,
`border-l-4`, the padding rhythm, the live region, `RunActions` and every word of the content
are untouched.

**Task 4 — tests and harness.** Four tests in `RunFeedSections.test.ts` (RED-first test plus
the mixed run, the empty run and the D-09 toggle) and an offline harness fixture with a whole
run that never reaches deep research, plus a "no events yet" mode.
`src/lib/research/groupedTrace.test.ts` is untouched.

## A freshly opened run: before and after

**Before**, opening a run gave you the status card on a light-grey panel and then a bare
terminal-style transcript: an uppercase phase label with a hairline rule beside it, a handful
of monospace rows under it, and a small grey "Worked for 18s · 3 actions" line trailing
*below* each finished phase. A run with no events yet was a single centred grey sentence and
nothing else. The bordered, serif-headed panel — the design that was actually asked for —
appeared only once the run had reached deep research *and* the worker had emitted trace
metadata, and then only around that one phase, so the page visibly changed design halfway
through a run.

**Now**, every phase is that bordered panel from its first event: a serif heading carrying the
engine's own phase label, a pink "live" badge on the phase the engine is currently in, and
that phase's "Worked for 18s · 3 actions · $0.42" line as a subline in the header instead of a
row trailing below it — so the phase name and the summary each appear exactly once. A queued
or just-started run already shows one of these panels, titled with its status. Deep research
still gets its question cards, provider badges, results bar and "original events" disclosure,
but now *inside* its own phase's panel as an enhancement, not as the thing that switches the
design on. The status card above shares the same border and paper background, so the page
reads as one design rather than two.

## Rollback — the "partial revert" property is gone

Before this change the design was conditional on data the **worker** produced: the shell only
rendered where `projectResearchTrace` found executions, and that projection only ever fires on
`deep_research` events carrying `trace_*` metadata. Rolling the tribunal worker back to a
build that does not emit that metadata therefore also rolled the run page back to the old
feed — an accidental second revert lever.

That lever no longer exists. The shell is rendered unconditionally by the frontend for every
phase, so a worker rollback now only removes the *grouping inside* the deep-research section;
the whole-page design stays. **The rollback for this change is the Cloud Run revision
`nestor-frontend-00040-tgk` (tag `state-after-trace-visuals-260909`)**, and nothing else.
No feature flag and no localStorage switch was added, per the plan's fence.

## Gates — actual output

**`npx tsc --noEmit`**

```
$ npx tsc --noEmit
TSC EXIT=0
```

(no output; exit 0)

**`npx vitest run`** — baseline was 262 in 15 files; now **266 in 16 files**, all green (+4
from the new `RunFeedSections.test.ts`; no existing test was modified or deleted).

```
 ✓ src/lib/research/funnelLabels.test.ts (42 tests) 10ms
 ✓ src/lib/i18n/statusCatalog.test.ts (14 tests) 11ms
 ✓ src/lib/research/groupedTrace.test.ts (48 tests) 34ms
 ✓ src/components/intake/ValidationDiff.test.ts (13 tests) 8ms
 ✓ src/components/research/RunFeedSections.test.ts (4 tests) 47ms
 ✓ src/components/research/ResearchTrace.test.ts (16 tests) 125ms

 Test Files  16 passed (16)
      Tests  266 passed (266)
   Start at  12:07:41
   Duration  17.84s
```

**`node scripts/i18n-audit.mjs`**

```
  → 106 advisory hit(s) — review + fix or justify in SUMMARY

═══════════════════════════════════════════════════════════════
 RESULT: PASS — A/B/C clean (106 CHECK D advisories)
═══════════════════════════════════════════════════════════════
I18N EXIT=0
```

The 106 CHECK D advisories are pre-existing and unchanged by this work — they are hardcoded
Dutch strings and JSX text in the sales routes, `auth.*`, `index.tsx` and `__root.tsx`, none
of which this change touches. Every string added here goes through `t()` and the one new key
(`research.runPage.feed.stageFallback`) exists in all three locales: `"Run activity"` /
`"Activiteit van de run"` / `"Activité de l'exécution"`.

**`npm run build`** — the production Nitro/Cloudflare build compiles.

```
.output/server/_ssr/admin.pulse.runs._runId.index-DoAzuglp.mjs   70.69 kB
...
✓ built in 20.87s
ℹ Generated .output/nitro.json
[nitro] ✔ You can preview this build using npx vite preview
BUILD EXIT=0
```

**Offline harness build** — the config *does* support a build target:

```
$ npx vite build --config tools/research-trace/vite.config.ts --outDir <scratch>/rt-build --emptyOutDir
.../rt-build/assets/index-CyTmpagD.css   109.94 kB │ gzip:  18.59 kB
.../rt-build/assets/index-oYzJ7HDu.js    404.31 kB │ gzip: 130.20 kB
✓ built in 20.88s
```

**`git diff --stat aad9691 HEAD`** — frontend only, no `backend/`, no `tribunal/`, no `infra/`:

```
 frontend/src/components/research/EmptyFeed.tsx     |  50 +++++
 frontend/src/components/research/ResearchTrace.tsx | 182 +++++++++++++++---
 frontend/src/components/research/RunFeed.tsx       | 213 +++++++++++----------
 .../components/research/RunFeedSections.test.ts    | 204 ++++++++++++++++++++
 frontend/src/components/research/RunStatusCard.tsx |   6 +-
 frontend/src/locales/en/intake.json                |   1 +
 frontend/src/locales/fr/intake.json                |   1 +
 frontend/src/locales/nl/intake.json                |   1 +
 .../src/routes/admin.pulse.runs.$runId.index.tsx   |  29 +--
 frontend/tools/research-trace/main.tsx             |  56 +++++-
 10 files changed, 581 insertions(+), 162 deletions(-)
```

Lint was not run: this worktree checks out CRLF and `eslint` reports tens of thousands of
`Delete ␍` complaints that say nothing about the change. Per the operator's instruction it is
not a gate here.

## Fences honoured

`groupedTrace.ts` projection semantics, `useRunEvents.ts`, `lib/api/research.ts`,
`RESEARCH_TERMINAL`, `isTerminal`, the footer ticker and `components/ui/` are all unmodified —
confirmed by the diff stat above. No feature flag, no localStorage switch, no dependency
change, no `gcloud`, no deploy.

## Found but not touched

1. **`npm run build` rewrites `frontend/src/routeTree.gen.ts` with LF endings.** On this
   CRLF working tree that produces a whole-file diff with zero content change. It was restored
   with `git checkout -- frontend/src/routeTree.gen.ts` and is **not** part of any commit. Any
   future session that runs the production build in a worktree will hit the same phantom diff
   — worth a `.gitattributes` entry (`*.gen.ts text eol=lf`) but that is out of scope here.
2. **`groupedTrace.ts:98` still skips every stage but `deep_research`.** Correct and left
   alone per the plan — it is a TASK projection, not the design switch — but it is now the
   *only* reason a phase gets the grouped body rather than plain rows. If the engine ever
   emits `trace_*` metadata for another stage, that stage will start grouping with no
   frontend change, which is the intended shape but has never been exercised.
3. **Three unused locale keys under `research.runPage.trace`**: `activity`, `provider`,
   `status`. Nothing reads them; `audit` is also unused now that the drill-down affordance
   uses `research.feed.viewAudit`. They were left in all three locales because CHECK A tests
   key *parity*, not usage — deleting them from one file only would go red. Same reasoning
   the route file already records for `verification.hideAction`.
4. **A phase carrying more than one `divider` or `summary` event** shows only the first of
   each. That is pre-existing behaviour, not a regression: `body` has always filtered out
   *all* dividers and summaries while `events.find(...)` picked the first, so the extras were
   already invisible. The engine's `_stage_event_boundary` emits exactly one of each.
5. **A phase with a divider and a summary but no detail rows** now renders a header-only
   panel with no body. That is the truthful rendering (it is what D-09 exists to protect) but
   it does mean the eight quiet stages are visually thinner than the busy ones. No action
   taken — the alternative is inventing filler.
6. **No browser or E2E coverage exists for any of this.** Everything asserted here is
   server-rendered markup under vitest. The visual result — spacing, the live badge's pulse,
   how a dozen stacked panels read on a real screen — has not been seen by anyone. That is
   the walkthrough the orchestrator still owes after deploying.
