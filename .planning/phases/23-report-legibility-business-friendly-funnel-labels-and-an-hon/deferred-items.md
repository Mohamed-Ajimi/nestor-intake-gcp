# Phase 23 — deferred items (out of scope, logged not fixed)

Executors append here. Out-of-scope discoveries logged during execution. Per the executor scope
boundary these were NOT fixed: each entry is a pre-existing condition, or a consequence of a ruled
decision, discovered while executing a plan but outside that plan's scope boundary.

> **⚠ THIS FILE IS CREATED ONCE, BY PLAN 23-03, IN WAVE 3.** Phase 21 produced an add/add merge
> conflict because plans 21-01 and 21-02 each created their own copy in their own worktree. The
> wave-1 and wave-2 plans (**23-01, 23-02**) record deferred discoveries in their **own SUMMARY**
> instead, and this plan folds them in below.

**Never renumber an existing id.**

---

## DEF-23-01 — `research.currentStage` prints a raw engine stage key on the RUN page

**Found during:** Phase 23 planning, while auditing every raw-key leak adjacent to UAT-22-F1.
**Status:** deferred — a DIFFERENT vocabulary on a DIFFERENT page, and outside this phase's goal.
**Owner:** unassigned. Belongs to whichever phase next works on the run page.

### The mechanism

`research.currentStage` is `"Current phase: {{stage}}"` and interpolates `run.current_stage`, which
is a pipeline **STAGE** key (`coverage`, `workshop`, `verify`, …) — **not** a verification funnel
**GATE** key. It is a separate enumeration, owned by the pipeline, and none of the eighteen labels
plan 23-01 added applies to it.

It has exactly two call sites:

| Site | Live? |
|------|-------|
| `frontend/src/routes/admin.pulse.runs.$runId.index.tsx:274` | **LIVE** — this is the leak |
| `frontend/src/components/intake/ResearchRunProgress.tsx:938` | **dead** — inside the unrendered component body (DEF-22-01) |

So: one live leak, on the run page. (The second line sat at `:933` when phase 23 was planned; plan
23-03 Task 2 added five lines above it in the same file, which is the whole of the difference.)

### Why it is not fixed here

The Phase 23 goal is scoped to *"every figure on the verification report"*, and UAT-22-F1 names
`VerificationReport.tsx` and the funnel keys specifically. The stage vocabulary needs its own label
set and its own three-locale copy.

### For whoever picks it up

`frontend/src/lib/research/funnelLabels.ts` (this phase, plan 23-01) is the pattern — an enumerated
key set plus a degrade-safe humanizer, with the copy in the three locale files, and an unknown key
falling back to a readable phrase rather than a raw token. The enumeration to work from is the
**pipeline's stage keys**, not `gates.py`'s `_FUNNEL_KEYS`.

---

## DEF-23-02 — `ci_no_run_research.sh`'s comment cites a UI string that no longer exists

**Found during:** plan 23-02 execution, routed here via `23-02-SUMMARY.md`.
**Status:** deferred — backend file, outside the frontend-only scope of every plan in this phase.
**Owner:** unassigned. A comment-only correction.

`backend/scripts/ci_no_run_research.sh:26-30` justifies its own regex precision by citing *"a Dutch
operator UI string in NextStepBanner.tsx contains the words `run-research`"*. Commit `b9cc19e`
(plan 23-02) removed that string; `grep -rn "run-research" frontend/src` now returns **0**.

**The guard itself is unaffected and must not be weakened.** Its regex is anchored to invocation
syntax (`invoke\([^)]*run-research`, `/run-research`, `run_research\(`) and never matched the prose
string in the first place. Only the justifying comment is out of date.

Note for whoever picks it up: `run-research` still appears ~32 times elsewhere in `backend/` — in
`ci_no_run_research.sh` itself and four backend test files. That is all scope-guard machinery
enforcing the project's hard ceiling (`run-research` must never be invoked from the new
frontend/backend credentials) and **must survive**. Only the one stale sentence is in scope.

---

## DEF-23-03 — `paused` fuses two states that license different, differently-priced actions

**Found during:** phase 23 code review (WR-02), after all three plans had executed.
**Status:** partially closed — the misleading COPY was fixed in `2edb752`; the presentation SPLIT
is deferred.
**Owner:** unassigned.

`workPhase.ts` maps both `parked` and `needs_input` to the single `paused` presentation. The run
page does not treat them alike: `components/research/RunActions.tsx:105-109` sets
`showResume = status === "parked"` and
`showFreshAttempt = failed || cancelled || needs_input`. So a `parked` run can be **resumed**, while
a `needs_input` run's only affordance is a **fresh attempt** — a full ~$45 re-run that discards
paid checkpoints.

**What was fixed:** the paused body said *"Open the run to continue it"*, which is false for
`needs_input` and steers the operator toward an unnamed spend. It now reads *"Open the run to see
what it needs"* in all three languages — true of both states, promising nothing about cost.

**What is deferred:** splitting `paused` into two presentations (resumable vs awaiting-input) so the
banner can name the actual next action, with a sixth body per language and a sixth banner branch.
That is a change to plan 23-02's presentation union and to `NextStepBanner`'s exhaustive mapping,
which is why it was not folded into a review fix.

For whoever picks it up: the union in `workPhase.ts` is exhaustive by design — adding a sixth member
is a TYPE ERROR at the banner until the branch is written, which is the intended forcing function.
Add the binding test alongside it; `funnelLabels.test.ts`'s WR-01 block is the pattern.

---

## DEF-23-04 — the unrendered `ResearchRunProgress` subtree still opens a stream if anyone imports it

**Found during:** phase 23 code review (WR-03).
**Status:** deferred — a deletion, not a fix, and larger than this phase.
**Owner:** unassigned.

After D-22-5 removed its render site and plan 23-03 lifted the hook out of `IntakeOpenRunLink`, the
`ResearchRunProgress` **component** (and roughly 450 lines of subtree exclusive to it, including
`AuditBodyPanel`) has **no importer anywhere**. It still calls `useActiveResearchRun` at
`ResearchRunProgress.tsx:638`.

The module must survive — the intake route and the run page both import `useActiveResearchRun` and
`IntakeOpenRunLink` out of it (DEF-22-01 records this). But the page's one-stream invariant, which
plan 23-03 was written to establish, currently rests on *nobody importing the dead component*. A
future author who re-adds it to the intake page re-creates the double-stream defect silently.

For whoever picks it up: either delete the dead subtree, or add a cheap CI grep guard asserting
`ResearchRunProgress` has no importer outside its own module — the latter is minutes of work and
converts a convention into a gate.

---

## DEF-23-05 — the funnel ⓘ is mouse-only and its label is announced unreliably

**Found during:** phase 23 code review (WR-04).
**Status:** deferred — a pre-existing pattern in this file, not introduced by phase 23.
**Owner:** unassigned.

`InfoTip` (`VerificationReport.tsx:340-346`) is a non-focusable `<span>` with no `role`, carrying
its text in `title` + `aria-label`. It is therefore keyboard-unreachable, and `aria-label` on a
generic element with no role is not reliably exposed by screen readers. The funnel row `<div>`
carries an `aria-label` under the same limitation.

Phase 23 made this matter more than it did before — the tooltip is now the second half of the F1
fix rather than decoration — but the pattern predates the phase, and correcting it properly means a
focusable element with an appropriate role (or a real popover primitive), which is a UI-layer
decision rather than a review fix. `frontend/src/components/ui/` is shadcn and not to be modified
directly, so this likely wants a small local component.

---

## CORRECTION to 22-UAT.md § UAT-22-F1 — the funnel has 18 numeric keys, not 6

**Not a deferred item, and deliberately carries no `DEF-` id:** it is a correction to a source
document, recorded where a reader of this phase will find it. **CLOSED** — plan 23-01 labelled all
eighteen, so this is a closed correction, not an open gap.

`22-UAT.md`'s F1 entry lists six funnel keys. Six is what the operator's particular run happened to
display, not what the funnel contains.

### The measured derivation

`VerificationReport.tsx:401-406` renders **every numeric entry** of `report.funnel` through a
generic `Object.entries(...)` map — nothing enumerates a fixed six.

The funnel dict is assembled by `_build_funnel` in
`tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py:973-1085` and carries **20** keys:

- **9 gate-owned**, from `gates.py:120-129` (`_FUNNEL_KEYS`): `distilled`, `kept`, `dropped`,
  `not_falsifiable`, `not_load_bearing`, `both`, `selected_verify`, `skipped_stable`, `gate_errors`.
- **11 stage-owned**, set in `_build_funnel`: `checked`, `should_have_been_checked`,
  `verify_sessions`, `verification_degraded`, the four `_INCIDENTAL_REASON_KEYS`
  (`checked_incidentally_not_falsifiable`, `…_not_load_bearing`, `…_both`, `…_stable`),
  `checked_incidentally`, `unresolved_anchors`, `degradation_reasons`.

Two of those 20 are **not numbers** and are dropped by the strict `typeof count === "number"` filter
at `VerificationReport.tsx:403` — `verification_degraded` is a **bool** and `degradation_reasons` is
a **list**. (That strictness is itself load-bearing: coercion previously turned a populated reasons
list into the number `0`, which asserts there were no reasons.)

**20 − 2 = 18 numeric keys reach the screen**, and plan 23-01's `KNOWN_FUNNEL_STAGES` covers exactly
those eighteen, key for key.

> ⚠ **A note on the arithmetic.** Phase 23's own planning documents reached 18 by "nine from
> `gates.py` plus nine from `pipeline.py`". The total is right and the conclusion is right, but the
> route is not: `pipeline.py` contributes **eleven**, two of which are non-numeric. Anyone extending
> the label set must count what `_build_funnel` returns and then apply the numeric filter — not
> trust "nine plus nine".

**Why it mattered:** labelling only the six the UAT lists would have left twelve raw snake_case keys
on screen — the exact defect F1 was raised to remove.

---

## CORRECTION to 22-UAT.md § UAT-22-F4 — defect 3 is operator-facing, not client-facing

**Not a deferred item, no `DEF-` id.** **CLOSED** — the defect was real and plan 23-02 fixed it as a
locale-only change. What is corrected here is its *framing*.

`22-UAT.md`'s F4 entry states that the conflation is **CLIENT-FACING**, citing
`locales/en/admin.json`'s `intakeDetail.statusBanner.in_research`. Measured, it is not.

| Claim | Measured |
|-------|----------|
| `intakeDetail.statusBanner.in_research` render sites | **exactly one** — `routes/admin.pulse.intakes.$id.tsx:1201`, under `/admin/pulse`, an operator route |
| What the client status pill reads | `frontend/src/components/intake/_status.tsx` → `common.json`'s `status.*` catalogue, whose `in_research` is the neutral `"In research"` (`locales/en/common.json:14`) |
| `admin.pulse.intakes.$id.tsx:190` | reads `intakeDetail.status.*` — also the neutral `"In research"` |
| Any client route rendering a research-running claim | **none** |

The string lives in `admin.json`, has one render site, and that site is an admin route. It was a
real defect and worth fixing — an operator was being told research was running after it had
finished — but it was **operator-facing**.

> ⚠ **The CLIENT-FACING framing must not be re-inherited as fact** by a future reader of the UAT. A
> phase that plans around it will go looking for a client-side leak that does not exist, and may
> widen scope into client routes on the strength of it.

(The render site sat at `:1178` when phase 23 was planned; plan 23-03 Task 2 added 23 lines above it
in the same file.)
