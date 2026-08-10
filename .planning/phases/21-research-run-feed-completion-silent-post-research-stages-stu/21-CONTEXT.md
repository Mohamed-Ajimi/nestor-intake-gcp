# Phase 21: Research Run Feed Completion - Context

**Gathered:** 2026-08-10
**Status:** Ready for planning

> **Provenance.** This file was written by the assistant from a working session with the
> operator on 2026-08-10, NOT from a `/gsd:discuss-phase` run. It follows 15.3-CONTEXT.md's
> convention. Decisions marked **[OPERATOR]** are the operator's own, given explicitly in that
> session. Decisions marked **[ASSISTANT — CORRECTABLE]** are the assistant's recommendations,
> stated with their mechanism explained and not contradicted; they are the working assumption
> and may be overridden at plan review without penalty. Everything marked **[MEASURED]** was
> read out of the code in that session and is a fact about the tree at `30443e8`.

<domain>
## Phase Boundary

**Phase 21 finishes a contract Phase 15.3 started and left at four stages out of thirteen.**

The trigger was operator UAT of the dedicated run page (`/admin/pulse/runs/:runId`) on
2026-08-10. Four complaints, in the operator's words: steps that keep spinning after they have
finished and moved on; "show less/show more" buttons that are placeholders and show nothing;
nothing at all after the deep-research phase — no data, no stats, no dispatched agents, no view
of claims verification; and the whole thing too verbose with rubbish information.

**Three of those four are one root cause.** 15.3 shipped the run-event contract and wired it
into four stages. The other nine stages of the pipeline never emit content, so they render as a
phase label with an empty body — and an empty body is also why the collapse toggle above it
reveals nothing when clicked. The stuck spinner is separate and structural: the feed is
append-only, so an "agent started" row is a statement about the past that keeps animating as
though it were about the present.

**Four deliverables plus a density pass:**

1. **Feed events for the eight silent stages** — `distill`, `merge`, `gate`, `verify`,
   `adjudicate`, `coverage`, `conflict`, `synthesize`. Engine work.
2. **Settle finished agent rows** so a spinner means "running now". Frontend.
3. **Gate the collapse toggle** on there actually being hidden rows. Frontend.
4. **Reach `VerificationReport` from the run page**, not only from the intake card. Frontend.
5. **A density pass** over the `deep_research` `thinking` prose. Engine text + frontend.

**Out of scope:**

- **Engine behaviour changes.** Like 15.3, this phase adds and reshapes *observability*. It
  must not alter what the pipeline decides, dispatches, or produces. A change that alters a
  claim, a verdict, a cost or a dispatch is out of scope even if it would improve the feed.
- **Replacing the embedded `ResearchRunProgress` card** on the intake detail route. It stays.
  Only item 4 crosses between the two surfaces, and it crosses by *adding* to the run page.
- **Any client-facing research surface.** D-08 from 15.3 stands unchanged: no client route may
  import any of this. The run page is superadmin-only by placement AND by API authorization.
- **New event kinds.** See D-03 — the vocabulary is closed and stays closed.
- **The `$45` run itself.** Triggering and reading it is the next thing after this phase, not
  part of it.
- **G-7, G-12 through G-17** and the other open engine gaps in `.planning/CONTINUE-HERE.md`.
  Several are *visible* in the feed but none are caused by it. Do not fix them here.

## The measurement this phase is built on

**[MEASURED]** Feed-event emission sites across the engine, excluding tests, at `30443e8`:

| stage | emit sites |
|---|---|
| `deep_research` | 24 |
| `own_research` | 7 |
| `workshop` | 2 |
| `research_division` | 2 |
| `distill` `merge` `gate` `verify` `adjudicate` `coverage` `conflict` `synthesize` | **0** |

`ENGINE_STAGES["tribunal"]` (`runs/stages.py:38-71`) declares **13** stages. Four emit content.

**[MEASURED]** Event kinds actually emitted, by site count: `thinking` 11, `agent_fail` 9,
`agent_done` 9, `dispatch` 4, `summary` 3, `agent_run` 3, `tool` 2, `search` 2, `plan` 2,
`streams` 1, `divider` 1, `agent_retry` 1.

**[MEASURED]** 13 of the 48 sites live in `audit/audited_llm_client.py` and every one of them
hardcodes `stage="deep_research"`. Eight are `kind="thinking"`. This is the single largest
concentration of feed volume in the engine, it fires per model call, and most of its lines are
exception-path commentary addressed to an engineer rather than to a watcher. One verbatim
example, which renders as one feed row:

> "A recorded Google research job id was refused by the job-id guard — this angle is dispatched
> fresh rather than rejoined, so it is paid for again."

**The noise and the silence are the same misallocation**: the stage that already says the most
says it at the wrong altitude, while the stages carrying the run's actual conclusions —
`verify` above all — say nothing.

> ### ⛔ AMENDED AT PLANNING, 2026-08-10 — the "wrong altitude" half of that sentence is wrong
>
> The planner read all 8 `thinking` sites in `audited_llm_client.py` and measured their CONTENT
> class rather than their form. **All 8 are money or long-silence** — which are precisely D-13's
> two KEEP classes. **5 of them are pinned by `test_own_researcher.py:1290-1400`**, a registered
> CI test whose own comment reads *"the wording is the deliverable — this run was misread as a
> stall once."*
>
> The characterisation above ("exception-path commentary addressed to an engineer") was inferred
> from the *shape* of the prose — long, explanatory, defensive — without checking what each line
> was actually about. The verbatim example quoted below as evidence of noise ends with **"so it is
> paid for again"**: it is a money warning, which D-13 says to KEEP.
>
> **Under D-13 as written, the correct content trim is ZERO CUTS.** The measured volume driver is
> **cardinality, not altitude** — one correct line multiplied across 19 angles. That is a different
> problem with different fixes (dedupe, collapse-by-repetition, per-stage budget) and the operator
> has not ruled on it.
>
> D-12 — the operator's own "diagnose before trimming" — is what caught this. It was the right
> instinct and it was right for exactly this reason. `21-04-PLAN.md` Task 2 is the blocking ruling,
> and **"no change to that file" is a legitimate ruling** that satisfies SC5.

## Where the eight silent stages live

**[MEASURED]** Every `set_stage` call site in `pipeline.py`, mapped to its stage key. This is the
planner's work list — the emission sites go where the stage is already being reported.

| line | stage key | | line | stage key |
|---|---|---|---|---|
| 1681 | `intake` | | 3148 | **`verify`** |
| 2195 | `intake` | | 3301 | **`verify`** |
| 2394 | `research_division` | | 3324 | **`verify`** |
| 2400 | `deep_research` | | 3372 | **`adjudicate`** |
| 2413 | `deep_research` | | 3414 | **`coverage`** (marker only, no detail) |
| 2590 | **`distill`** | | 3483 | **`verify`** |
| 2654 | **`distill`** | | 3536 | **`verify`** |
| 2749 | **`merge`** | | 3589 | **`conflict`** |
| 2898 | **`merge`** | | 3749 | **`synthesize`** |
| 2963 | **`gate`** | | 3955 | **`report_spec`** ⚠ see below |
| 2986 | **`gate`** | | 4179 | **`synthesize`** |
| | | | 4382 | `done` |

Note `3414` advances the marker with **no detail at all**, so `coverage` reports neither rows
nor a meaningful action count. It is the emptiest of the eight.

## ⚠ A fourteenth stage nobody declared — **THIS SECTION WAS WRONG. READ THE AMENDMENT.**

> ### ⛔ AMENDED AT PLANNING, 2026-08-10 — three of this section's premises are false
>
> The planner measured them and they do not hold. The section is kept verbatim below because the
> reasoning that produced it is instructive, but **do not act on it as written.**
>
> 1. **The recurrence-guard test already exists and already runs.**
>    `tests/test_stage_schema.py::test_every_set_stage_key_in_the_pipeline_is_declared`, registered
>    in `cloudbuild.test-gates.yaml:154`. D-15's "the planner should add one; it is the only thing
>    here that prevents a fourth" was written in ignorance of a test that was already there.
> 2. **`report_spec` was never undetected.** It is a deliberate entry in that test's
>    `_NON_SCHEMA_MARKERS` allowlist (`test_stage_schema.py:38-48`), added by plan 15.1-13 with a
>    written justification: declaring it *"would put a phantom row in the ordered checklist of every
>    NON-interactive run, so it stays out of the schema"*, and *"listed here explicitly so the
>    exception is reviewable, not silently absorbed."* It is the opposite of a silent recurrence.
> 3. **The operator has almost certainly never seen that divider.** `pipeline.py:3955` sits inside
>    `if interactive_report:` — the opt-in `[INTERACTIVE_REPORT]` marker path, which Phase 16's
>    D-01/D-01b says never fires for seam runs. The raw key is therefore **LATENT**, not the thing
>    observed during UAT.
>
> **What survives:** the OUTCOME — no raw stage key should reach a reader — is still worth holding,
> and the allowlist is a real hole in an otherwise sound guard (an allowlisted key is exempt from
> the check but nothing proves it has a label). SC6 was rewritten around that, and the MECHANISM is
> now an open operator decision at `21-07-PLAN.md` Task 1: declare it in the schema, or label it on
> the READ path per this project's own standing generalisation, which has paid off twice.
>
> **The lesson, which is the reusable part:** an undeclared key and a *deliberately* undeclared key
> are indistinguishable from the call site. The check that would have caught this was reading the
> guard before assuming there was none.

### The original section, superseded — do not act on it

**[MEASURED]** `pipeline.py:3955` writes stage key **`report_spec`**, and `report_spec` is **not
in `ENGINE_STAGES["tribunal"]`** (`runs/stages.py:38-71`, which declares 13). `_stage_event_label`
(`pipeline.py:480-493`) falls back to the raw key when it finds no schema entry — so the run page
renders a phase divider reading literally **`report_spec`** instead of a human label.

This is the **same defect class as WR-03**, whose own comment in `stages.py:60-64` records that
`gate` "has been writing this key since Phase 15.1 while the schema never declared it — so
`run.current_stage` reported a stage `RunMetrics.stages` omitted, and the UI rendered the raw key
with no label." It recurred, undetected, on a key added later.

It also sits squarely inside the operator's complaint: a raw snake_case key in the middle of the
feed reads as exactly the "rubbish information" they named.

⚠ The docstring at `pipeline.py:483` claims `ENGINE_STAGES["tribunal"]` "has carried a label for
all fourteen stages since Phase 15." It carries thirteen. **Do not trust that line — count the
list.** Fixing the count in the comment is part of D-15.

## Hard constraints carried forward

- **`RUN_EVENT_KINDS` is a closed 12-kind vocabulary** (`runs/run_events.py:69-82`) and its
  own comment states it is "one contract in two languages" with the frontend's union: adding a
  kind on one side only "renders a blank line, which is worse than an absent one."
- **Emission is best-effort and must never raise into a caller.** `emit_safe` wraps both the
  `build()` thunk and the enqueue. Any new emit site must go through `emit_safe` with its text
  and meta built INSIDE the thunk — never composed above it. `run_events.py:402-465` explains
  why at length; that reasoning applies verbatim to every site this phase adds.
- **`open_run` is called exactly once**, in `pipeline.py:1680`. A second call anywhere would
  orphan the first buffer's undrained events. This phase adds no second call.
- **Dividers and per-stage summaries are already automatic.** `_stage_event_boundary`
  (`pipeline.py:536-565`) emits a `summary` for the outgoing stage and a `divider` for the
  incoming one at every real transition, driven by the `set_stage` shim at `pipeline.py:1655`.
  **The eight silent stages therefore already have a label and a summary line** — what they
  lack is a body. Do not add dividers or summaries by hand; they would double.
- **Tenant binding is mandatory** for the run-scoped tables. `open_run` binds the tenant once
  so the six emitting modules do not carry one. Keep it that way.
- **`frontend/src/components/ui/` is not modified** (CLAUDE.md).
- **`.planning/` is gitignored** — every planning artifact needs `git add -f`.

</domain>

<decisions>
## Implementation Decisions

### Sequencing and deploy

**D-01 [OPERATOR] — Phase 21 ships BEFORE the first measured run.**
Three changes deployed at tag `20260806-175613` have never executed. The ~$45 run that would
validate them is also the only thing that can validate this feed. Running first would spend it
watching a view that reports nothing for 8 of 13 stages. Fixing first means one run validates
both. Recorded in ROADMAP.md's execution order.

**D-02 [MEASURED] — the deploy surface is `tribunal-worker` plus `nestor-frontend`.**
Items 1 and 5 change `tribunal/`; items 2, 3, 4 change `frontend/`. **Re-derive the surface from
the actual diff at deploy time and do not trust this line** — that rule is why the 2026-08-06
deploy caught `nestor-api` after a standing note said two services. No migration is expected
(no new columns, no new event kinds), but confirm rather than assume.

### The eight silent stages

**D-03 [ASSISTANT — CORRECTABLE] — express the new stages in the EXISTING 12 kinds. No new
kind, no schema change, no migration.**
The vocabulary is a two-language contract and every addition costs a coordinated frontend
change. The existing kinds already cover what these stages do: `dispatch` for "verifying N
claims", `agent_run`/`agent_done`/`agent_fail` for each unit of work, `plan` for routing
decisions, `thinking` for a conclusion worth a sentence. Nothing in the eight needs a glyph
that does not exist.

**D-04 [ASSISTANT — CORRECTABLE] — every one of the eight emits at minimum a `dispatch` header
naming the work and its count, and then per-item rows.**
The acceptance bar is that no phase renders as a label with nothing under it. A `dispatch`
line alone would clear that bar and still be a disappointment; the point of the page is the
per-item detail. `verify` in particular must show the individual claim verdicts — it is the
stage the operator named, and it is where the run's money and meaning are.

**D-05 [ASSISTANT — CORRECTABLE] — the per-item rows must be bounded.**
A run distills hundreds of claims. Emitting one row per claim across `distill`, `gate`,
`verify` and `adjudicate` would add thousands of rows to a feed whose queue cap is 5000
(`_MAX_QUEUE`) and whose backfill already has a truncation path the page renders in words.
Bound each stage's per-item emission and — following the house rule that already governs
`StageFeed` overflow — **state the elision as a visible row rather than truncating silently.**
The exact bound is the planner's call; it should be a named constant with the
`NESTOR_TRIBUNAL_*` env override idiom the engine already uses.

**D-06 [ASSISTANT — CORRECTABLE] — reuse `_stage_event_boundary`'s existing summary; do not
hand-emit summaries or dividers in the new sites.**
They already fire. A hand-emitted one would double the line.

**D-15 [ASSISTANT — CORRECTABLE] ⛔ SUPERSEDED AT PLANNING 2026-08-10 — see the amendment box in
"A fourteenth stage nobody declared" above, and SC6 in ROADMAP.md. The guard test this decision
asks for ALREADY EXISTS; `report_spec` is a DELIBERATE allowlist entry, not an oversight; and the
raw key is LATENT (interactive-report path only), not the thing seen during UAT. The declare-vs-
label mechanism is now a blocking operator ruling at `21-07-PLAN.md` Task 1. The text below is the
original and is kept only for provenance.**

~~declare `report_spec` in `ENGINE_STAGES["tribunal"]` with a
human label, and correct the stale "fourteen stages" docstring at `pipeline.py:483`.~~
This is a two-line fix for a defect that puts a raw key on the operator's screen. Declare it in
the position the pipeline actually writes it — between `conflict`/`synthesize` per the call-site
map above (3589 `conflict` → 3749 `synthesize` → 3955 `report_spec` → 4179 `synthesize`), so the
declared order matches the executed order. **Verify that ordering against the code rather than
trusting this sentence** — the call sites interleave and the map above is a static read.

⚠ **Guard against the recurrence itself, not just this instance.** Two keys have now been written
without declaration (`gate`, then `report_spec`), each found only by someone reading the feed. A
test that asserts every `set_stage` key in `pipeline.py` appears in `ENGINE_STAGES` would have
caught both and would catch the third. The planner should add one; it is cheap and it is the only
thing here that prevents a fourth.

### The stuck spinner

**D-07 [MEASURED] — there is NO correlation key between `agent_run` and its `agent_done`.**
Verified at `workshop.py:520-577` (`_emit_orientation_run` emits with `meta=None`;
`_orientation_done_event` composes a separate line sharing no identifier) and at
`research_division.py:2389`. The pairing is convention and position, not data. **Any fix that
matches a start row to its finish row must first add a correlation key at ~22 emit sites.**

**D-08 [ASSISTANT — CORRECTABLE] — fix the spinner in the FRONTEND, without adding a
correlation key.**
A spinner is a claim about *now*, and an append-only log can only make claims about now on its
newest rows. So: render `agent_run` with the animated glyph only where "now" is still possible
— the last group — and render it settled everywhere else. This is correct by construction, is a
few lines in `RunFeed.tsx`, and is decoupled from the engine deploy.
*The rejected alternative* is adding `meta.agent_key` at every `agent_run`/`agent_done`/
`agent_fail`/`agent_retry` site and settling by lookup. It is more precise and it is
proportionally more work and more risk across 22 sites, for a difference the operator would
see only in the seconds between one agent finishing and the next starting. If the planner finds
the cheap fix leaves a visible wrong state, escalate to this rather than half-doing it.

### The collapse toggle

**D-09 [ASSISTANT — CORRECTABLE] — render the toggle only when rows are actually hidden.**
`RunFeed.tsx:225` renders it on `isComplete` alone; `RunFeed.tsx:211` previews the last
`COLLAPSED_PREVIEW_ROWS` (2) of `body`, and `body` excludes dividers and summaries — so for all
eight silent stages `body` is empty and the button expands to reveal nothing. Gate it on
`body.length > COLLAPSED_PREVIEW_ROWS`. Once D-04 lands, most phases will have bodies and the
button becomes meaningful; the gate still matters for short ones.

### Verification on the run page

**D-10 [ASSISTANT — CORRECTABLE] — reuse `VerificationReport` as-is; do not rebuild or fork it.**
It exists at `frontend/src/components/intake/VerificationReport.tsx`, already renders funnel,
verdicts, superseded, reconciled, unverified and true cost, and is already wired on the
completed card at `ResearchRunProgress.tsx:692` behind a toggle, scoped by `intakeId` + `runId`.
The run page resolves both ids. This is a wiring job.

**D-11 [ASSISTANT — CORRECTABLE] — reachable for every terminal status that has a report, not
only `completed`.**
The embedded card gates it on the completed/degraded branch. The run page's own structural rule
(`admin.pulse.runs.$runId.tsx:280-284`) is that the card and the feed are siblings so that
evidence survives on failed and cancelled runs. Follow that rule here: gate on whether a
verification report can exist, not on which card branch is rendering.

### Density

**D-12 [OPERATOR] — diagnose before trimming.** The operator declined an immediate aggressive
trim and asked for a specific list of what is noise versus signal first. The diagnosis in
"The measurement this phase is built on" above is that list's foundation; the planner should
produce the per-site verdict as a reviewable artifact, not fold it silently into a commit.

**D-13 [ASSISTANT — CORRECTABLE] — the keep/cut rule for `thinking` rows.**
KEEP: (a) the long-silence notice — "waiting on Google, polling every Ns for up to N minutes, a
long silence here is normal" — because without it a 35-minute gap reads as a hang, and that
exact silence was misread as a hang on 2026-07-27; (b) anything about **money** — rejoined work
already paid for, an angle being paid for twice, a fallback that re-charges. CUT to logs:
guard-refusal commentary, parser-defect explanations, and any line whose subject is the
engine's own defensive machinery rather than the research. REWRITE survivors as short phrases,
not paragraphs — the row is a 13px monospace line in a feed, not a log entry.

**D-14 [ASSISTANT — CORRECTABLE] — cutting a line from the feed means demoting it to
`log.warning`, never deleting it.** Every one of these lines documents a real condition someone
once needed to see. The feed is the wrong reader; the log is the right one.

### Claude's Discretion

- The exact per-stage row bound in D-05 and its constant name.
- Wording of every new event line (subject to D-13's "short phrase" rule).
- Whether the density pass ships as its own plan or rides with the stage-emission plans.
- Test placement — subject to the trap below: `test_synthesize_report.py` is NOT in the CI
  gate's `WANTED` list. **Extract the real 44-file list from
  `tribunal/cloudbuild.test-engine.yaml` and never trust a filename.** If a new test file is
  added, `EXPECTED_FILES` and the test path move in ONE edit, and the count changes from 44.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The event contract (both languages)
- `tribunal/nestor_pulse_sdk/runs/run_events.py` — `RUN_EVENT_KINDS` (69-82), `emit_safe`
  contract and its build-thunk reasoning (402-465), `open_run` (232-292), queue caps (92-99)
- `frontend/src/components/research/RunFeed.tsx` — the consuming component. Grouping (106-114),
  the collapse toggle defect (211, 225), the spinner (407-408), the memo boundaries and the
  standing warning that they are **inspected, not measured** (54-60)

### The stage machinery
- `tribunal/nestor_pulse_sdk/runs/stages.py` — `ENGINE_STAGES` (38-71), `set_stage` (94-142)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — `_stage_event_boundary` (536-565),
  `_stage_log_transition` (568+), the `set_stage` shim and its load-bearing import comment
  (1622-1663), `open_run` call site (1680)
- `tribunal/nestor_pulse_sdk/runs/stage_feed.py` — `StageFeed`, the single-owner pattern, and
  the overflow-as-a-visible-row rule this phase's D-05 follows (449-465)

### Existing emit sites to imitate
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop.py` (511-627) — the cleanest
  dispatch → agent_run → agent_done shape
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py` (2081-2622) — fan-out with
  retry and failure rows
- `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py` (1395-1975) — **the density target**

### The run page
- `frontend/src/routes/admin.pulse.runs.$runId.tsx` — the card/feed sibling rule (280-284), id
  resolution (52-71), the audit drill-down seam (180-193)
- `frontend/src/components/research/RunStatusCard.tsx` — where D-10/D-11 wiring lands
- `frontend/src/components/intake/VerificationReport.tsx` — reuse target
- `frontend/src/components/intake/ResearchRunProgress.tsx` (692) — the existing wiring to copy

### Design of record
- `docs/design/prototypes/ResearchRunImproved.tsx` — the twelve line kinds and the six things
  `RunFeed.tsx`'s header comment names as WHAT TO PRESERVE
- `docs/design/research-run-page-mockup.html`, `docs/design/research-run-ui-current-state.html`

### Prior phase
- `.planning/phases/15.3-*/15.3-CONTEXT.md` and its nine SUMMARY.md files — the contract this
  phase completes
- `.planning/CONTINUE-HERE.md` — live state, standing cautions, the open gap list this phase
  must NOT wander into

</canonical_refs>

<specifics>
## Specific Ideas

- **`verify` is the stage that matters most.** The operator named claims verification twice. If
  a plan has to be cut for scope, `verify` is the last thing cut, not the first.
- **The four wired stages are the template.** `workshop.py:511-627` is a complete, working,
  reviewed example of the shape the eight need. Imitate it rather than inventing.
- **`_stage_event_summary_meta` already carries `worked / actions / items / cost`.** The silent
  stages' summary lines are probably rendering nearly empty because `state["items"]` is 0 for a
  stage that never reported detail rows — worth confirming, because if so, D-04's per-item rows
  fix the summary line for free.
- The `is_live` meta flag already exists on `agent_run` and the frontend already reads it
  (`RunFeed.tsx:348`). D-08 should check whether it can be leaned on before adding new logic.

</specifics>

<deferred>
## Deferred Ideas

- **Adding a correlation key to agent lifecycle events** (the D-08 alternative). Revisit only
  if the cheap fix demonstrably leaves a wrong state on screen.
- **Retiring the embedded `ResearchRunProgress` card** in favour of the run page. Still the
  separate post-use decision 15.3 deferred.
- **A frontend test framework.** ⛔ **AMENDED AT PLANNING 2026-08-10 — the premise was stale.**
  `RunFeed.tsx:54-60` says "this repo has no frontend test framework". Measured: `vitest ^3.2.4`
  in `frontend/package.json`, a committed `frontend/vitest.config.ts` (`environment: node`,
  `include: src/**/*.test.ts`), and four passing `.test.ts` files under `frontend/src/lib/`.
  **Vitest is already standing.** I repeated the file's own stale comment without checking it.
  What remains true: there is **no `jsdom` and no `@testing-library`**, so component render tests —
  including the render-count assertion that would actually measure the memo boundaries — remain out
  of scope and are still deferred. But a PURE RULE extracted to its own `.ts` module is testable
  today with zero new dependencies and zero config change, which is why 21-01 and 21-02 prove their
  rules with real assertions instead of source greps. **That is not a fence violation** — the fence
  was against standing Vitest up, and it is already up. If you disagree, both plans fall back to
  source-scan criteria on request.
- **Whether the run page should render the report itself.** Out of scope; the download and the
  verification report are the two evidence surfaces this phase touches.

</deferred>

---

*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Context gathered: 2026-08-10 — assistant-written from an operator working session*
