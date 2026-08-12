# Phase 21 — deferred items (out of scope, logged not fixed)

Executors append here. Out-of-scope discoveries logged during execution. Per the executor scope
boundary these were NOT fixed: each entry is a pre-existing condition discovered while executing a
plan, outside that plan's scope boundary.

> **Merge note (orchestrator, 2026-08-10):** plans 21-01 and 21-02 each created this file
> independently in their own worktrees, producing an add/add conflict at wave-1 merge. Resolved as a
> **union** — both agents found genuinely different things about the same red lint gate, and neither
> account is complete on its own. 21-02 found the CRLF artifact and the two real drifts in the run
> page; 21-01 found the `scripts/c.ts` root cause that makes the command exit 1 no matter what.

---

## DEF-21-01 — `npm run lint` is already red at the phase base commit (`eac6f2b`)

**Found during:** 21-02 Task 2 and 21-01 Task 3 (both carry a `cd frontend && npm run lint` criterion)
**Status:** ⛔ **LEAVE DEFERRED — OPERATOR RULING, 2026-08-10. This is not an oversight.**

> **Do not re-open this as a missed item.** The operator was shown this finding and ruled
> explicitly that it stays deferred and stays **out of Phase 21**. Their reasoning: it predates
> this work, and fixing it inside a phase whose acceptance criteria measure **single-path diffs**
> would make every remaining plan's diff unreadable.
>
> A later agent that "helpfully" runs `prettier --write` across `frontend/src/` during Phase 21
> is defying a ruling, not closing a gap. Fix it in its own change, after Phase 21.

**Files:** repo-wide. The content complaints are `frontend/scripts/c.ts` (reason 3), plus two lines in
`frontend/src/routes/admin.pulse.runs.$runId.tsx` at the `useRunEvents` destructure and the
`EmptyFeed` return — both PRE-EXISTING lines, unchanged by 21-02.

### Reason 1 — CRLF, and it is a Windows-worktree artifact only

`git config core.autocrlf` is `true` on this machine, so the worktree checkout is CRLF while
`.prettierrc` leaves `endOfLine` at its `"lf"` default. Every file in the tree therefore fails
`prettier/prettier` with ``Delete `␍` ``, including files nobody has touched in months
(`frontend/vitest.config.ts` among them). Measured: **28,046 problems / 28,010 errors** across
the tree.

This is a checkout artifact, not a repo defect: CI checks out on Linux with LF and would not
see it. It is NOT fixable from here without rewriting line endings across the whole tree, which
is exactly the blanket working-tree operation the executor is forbidden to perform.

### Reason 2 — two genuine, EOL-independent formatting drifts, already at HEAD

Filtering the CRLF noise leaves exactly **two** errors in `admin.pulse.runs.$runId.tsx`:

- the `useRunEvents(...)` destructure — prettier wants the multi-line form collapsed;
- `EmptyFeed`'s `return (...)` — prettier wants the parentheses dropped.

**Both are proven pre-existing.** `git show HEAD:frontend/src/routes/admin.pulse.runs.$runId.tsx`
was exported to a scratch path and checked with `prettier --config .prettierrc --end-of-line auto`
— which removes the CRLF variable entirely — and the untouched HEAD version **still fails**. So
the frontend lint gate does not exit 0 at `eac6f2b` either, on Linux or on Windows.

### Reason 3 — `frontend/scripts/c.ts` reddens the whole command regardless (found by 21-01)

`frontend/scripts/c.ts` — an ad-hoc Supabase scratch script, untouched by phase 21 — carries
**3 genuine `@typescript-eslint/no-explicit-any` errors** plus prettier formatting errors. It is
not imported by anything in `src/`. Because `npm run lint` runs `eslint .` over the whole
frontend, that one file makes the whole command exit 1 **regardless of what any plan does**.

**Consequence for every phase-21 frontend plan:** the acceptance criterion
`cd frontend && npm run lint` exits 0 is **not satisfiable at this base commit**, and its failure
says nothing about the plan's own code. This criterion appears in remaining frontend plans and
should be read as unsatisfiable-as-written, not as a defect in the plan being executed.

### How to verify frontend work despite the red gate

Per-file, instead of the whole-tree command:

```
npm exec --prefix frontend -- eslint --config frontend/eslint.config.js <the files you touched>
```

21-01 verified its three files this way: **zero non-prettier rule violations.**
21-02 verified its three files this way: **zero** contributed errors — only the two pre-existing
lines above.

To check prettier conformance of the form that will actually be committed, feed the file through a
CR strip so the CRLF noise cannot drown the signal:

```
tr -d '\r' < <file> | npm exec --prefix frontend -- prettier --stdin-filepath <file> --check
```

**Doing this found two REAL pre-existing prettier deviations in `RunFeed.tsx`** that the CRLF noise
had been burying (`stableAfterRow` and the collapse-toggle ternary were both wrapped where prettier
joins them). 21-01 normalised those two because they sat in a file it already owned. There may be
more elsewhere in `frontend/src/`; nobody has looked, because the local signal is drowned.

### Why it was not fixed here

Reformatting those hunks would put unrelated churn into a diff whose acceptance criteria
explicitly measure that it touches exactly one path and nothing else. `scripts/c.ts` and any wider
prettier sweep are unrelated to the run feed and belong to whoever decides whether that scratch
script should exist at all.

`frontend/cloudbuild.yaml` has no lint, tsc or vitest step, so none of this currently blocks a
deploy — which is also why it went unnoticed.

**Recommended follow-up (not done here, and NOT during Phase 21 per the ruling above):** pin
`endOfLine` in `.prettierrc`, rule on whether `scripts/c.ts` should exist at all, then run
`prettier --write` once across `frontend/src/` as a single dedicated commit.

---

## DEF-21-02 — 21-02's operator UAT, folded into the 21-08 UAT gate

**Origin:** 21-02 Task 3, a `checkpoint:human-verify` with `gate="blocking"`
**Status:** **DEFERRED to plan 21-08 by operator ruling, 2026-08-10 — sequenced, NOT skipped and
NOT verified**
**Owner:** plan 21-08 (the phase's single post-merge operator UAT)

### The ruling

**Operator's reasoning, recorded as theirs:** the code is on an unmerged worktree branch and
cannot be clicked through yet; plan 21-08 already exists to run a single operator UAT after
everything is merged and deployed; nothing in Waves 2–4 depends on 21-02. Folding these six
checks into that one pass means one click-through instead of two.

### What this means for 21-02's acceptance

**Plan 21-02's acceptance is CONDITIONAL on this UAT.** Tasks 1 and 2 are machine-verified — tsc
clean, vitest 46/46, i18n-audit PASS exit 0, build exit 0 — but the operator-facing behaviour is
verified by **nothing** yet. A phase verifier must not count SC4 / D-10 / D-11 as
operator-confirmed until these steps run and pass.

### ⚠ Obligation on plan 21-08

**These six steps MUST be carried into `21-UAT.md`.** If 21-08 ships without them, the deferral
has quietly become a skip and 21-02's user-facing behaviour will have been checked by no one.
Note that 21-08's plan file was written **before** this ruling existed and therefore does not
reference DEF-21-02 on its own — the obligation must be injected when 21-08 executes.

### The six steps, in full

Verifiable on **RECORDED data with NO spend — do NOT trigger a run.**

**Preconditions:** 21-02 merged and `nestor-frontend` deployed; operator signed in as superadmin.

| # | Step | Expected result | Blocker if failed? |
|---|------|-----------------|--------------------|
| 1 | Open `/admin/pulse/intakes`, open any intake that has a research run, and click through to the run page via the card's **"Open run"** link. | The dedicated run page at `/admin/pulse/runs/:runId` loads. | Yes |
| 2 | Look at the vertical order of the page. | The **"View verification report"** toggle appears **BETWEEN the status card and the activity feed** — below the card, above the feed. | Yes |
| 3 | Click the toggle. | The report opens: **funnel**, **verdict sections** and **cost block** all render. **AND the ACTIVITY FEED IS STILL ON THE PAGE BELOW IT** — the report must not replace, hide or unmount the feed. | Yes — the single most important check in the list |
| 4 | Click the toggle again. | The report collapses, the label returns to "View verification report", and **the feed is untouched**. | Yes |
| 5 | If a **failed** or **cancelled** run exists in the list, open it and confirm the toggle is offered there too. | The toggle IS offered on failed and on cancelled runs (D-11 — these are the two states the embedded intake card throws away). | **No — NOT a blocker if no such run exists.** Record "none available" and move on. |
| 6 | Open a **queued** or **running** run. | **NO toggle appears.** Its **ABSENCE is the CORRECT result**, not a defect — the pipeline has not reached the verify stage, so there is nothing to fetch. | Yes — but note a *present* toggle here is the failure, not an absent one |

### Recording rules carried over from the original Task 3

- The operator's answer must be recorded **VERBATIM**, not paraphrased — a paraphrase of a UAT
  observation is how a defect becomes a rumour.
- Any deviation must be **routed**: either a follow-up task or an explicitly deferred item.
  Never absorbed silently.

### ✅ CLOSURE — DEF-21-02 is RECONCILED, 2026-08-11, by Phase 22 plan 22-09

**All six steps now have an explicit status and a named successor.** Three carried forward, three
superseded by a deliberate, operator-ruled design change:

| Phase 21 step | Status | Successor in `22-UAT.md` PART B |
|---|---|---|
| B1 — run page loads via "Open run" | **CARRIED FORWARD** | 22-B1 |
| B2 — toggle sits BETWEEN the status card and the feed | **SUPERSEDED by D-22-1** | 22-B2 |
| B3 — report opens AND the feed survives beneath it | **SUPERSEDED by D-22-1** | 22-B3 |
| B4 — toggle collapses cleanly, feed untouched | **SUPERSEDED by D-22-1** | 22-B4 |
| B5 — offered on failed / cancelled runs (D-11) | **CARRIED FORWARD** | 22-B5 |
| B6 — NO affordance on a queued / running run | **CARRIED FORWARD** | 22-B6 |

**Why three of them changed rather than being answered.** Phase 22's D-22-1 moved the verification
report onto its own route by operator ruling — *"verification report should open its own page not a
dropdown (too long)"*. B2, B3 and B4 all asked about a **toggle beside the activity feed** and about
the **feed surviving beneath an open report**. After D-22-1 there is no toggle and the report is not on
the same page as the feed, so those three questions have no referent. They are **unanswerable as
written**, and answering them anyway — in either direction — would be fabricating an observation.

**The obligation this item placed on plan 21-08 is DISCHARGED BY POINTER, not by answering the six
steps in their original form.** That is recorded plainly here so a later reader does not mistake it
for an abandoned deferral: the six checks were **rewritten to be answerable against the shipped
navigation**, and each rewrite states what changed and why.

⛔ **A SUPERSESSION IS NOT A PASS, AND THIS CLOSES NO VERDICT.** All six successors ship **unfilled**
in `22-UAT.md`, carrying the same blocker status (B5 still not a blocker when no failed or cancelled
run exists). **Plan 21-02's operator-facing behaviour therefore remains verified by nobody until an
operator fills in 22-B1 … 22-B6.** A phase verifier must not count SC4 / D-10 / D-11 as
operator-confirmed on the strength of this closure — it moved the questions, it did not answer them.

⚠ **Scope: this closure covers DEF-21-02 only.** Phase 22 changed no engine write path and triggered
no research run, so every Phase 21 check that needs a post-deploy live run (SC1 above all) stays OPEN
in `21-UAT.md`, and `21-UAT.md`'s `awaiting operator` count is unchanged by plan 22-09 (40 before, 40
after).

---

## DEF-21-03 — the `coverage` summary line is still nearly empty, and per-item rows do NOT fix it

**Found during:** 21-06 Task 3(b), by measurement before and after the change
**Status:** deferred — out of 21-06's scope, one-line fix identified, NOT applied

### What was measured

21-CONTEXT's `<specifics>` predicted: *"the silent stages' summary lines are probably rendering
nearly empty because `state["items"]` is 0 for a stage that never reported detail rows — worth
confirming, because if so, D-04's per-item rows fix the summary line for free."*

**Its first half is right; its conclusion is wrong.** Measured in the stubbed run at 21-06's base
commit AND after 21-06 landed, `coverage`'s automatic summary meta is `{'worked': '0s',
'actions': 0}` **both times** — unchanged by the two body rows the stage now emits, and still the
only stage of the thirteen reporting `actions: 0`.

The mechanism, read out of `pipeline.py`: `_stage_event_summary_meta` builds the summary from
`state["items"]`; `state["items"]` is written only by `_stage_log_items(detail)`, i.e. from the
**`detail` argument of `set_stage`**; and `meta["items"]` comes from `detail["summary"]["items_read"]`.
**Run events never touch that state at all.** The feed body and the summary line are driven by two
different inputs, so per-item rows cannot fix the summary "for free" or otherwise.

### The fix, and why it was not applied here

`pipeline.py`'s coverage marker is the only `set_stage` call in the pipeline with no `detail`
argument. Giving it one — e.g. the same sentence `emit_coverage_done` already composes — would
make `actions` non-zero and the summary meaningful.

It was **not** done in 21-06 because that plan's scope is explicitly "add rows around that call and
change NO argument to it", and because 21-06's acceptance rests on proving the diff is
observability-only (`await set_stage(` unchanged at 23, the cost trap byte-identical). Changing a
`set_stage` payload is a change to the stage-detail contract, which is a different surface with its
own consumers (`RunMetrics.stages`, the intake card).

**Whoever picks this up:** the assertion pinning the current behaviour is
`test_the_coverage_stage_summary_is_no_longer_empty` in `test_run_event_emit.py`. It is written to
fail loudly with an instruction if `actions` stops being 0, so the fix cannot land silently — it
forces the test and this item to be closed together.

---

## DEF-21-04 — the `workshop` stage emits body rows but NO divider, so its block has no heading

**Found during:** 21-07 Task 1, by measuring every `divider` row's text in a full stubbed run
**Status:** deferred — **out of 21-07's scope by operator ruling, 2026-08-10**. Routed here rather
than absorbed silently.

### What was measured

Driving the stubbed pipeline and reading every `divider` row at `run_events._writer`, a complete
run emits **13 dividers**, and the declared stages with **no divider at all** are:

```
['own_research', 'workshop']
```

`own_research` is expected and correct — the pipeline never writes that key at all (see 21-06's
pinned `_NEVER_REPORTED` exclusion, and 21-07's own finding that it is nonetheless already
labelled `Own research`, so it can never leak raw).

**`workshop` is the real gap.** It IS reported — it appears twice in the `set_stage` sequence and
21-06 measured **12 body rows** on it, the most of any stage — but it gets no divider, so those 12
rows render on the run page with no phase heading above them.

### Why

`workshop` is written by `StageFeed` (`runs/stage_feed.py:126`), **not** by a `set_stage` call in
`pipeline.py`. Dividers are emitted only by `_stage_event_boundary`, which rides
`_stage_log_transition`. `pipeline.py:1752-1763` records that this is deliberate (D-F, plan
15.2-24): the workshop is an **explicit span** (`_stage_log_line("stage_enter", ...)`) rather than
a synthetic transition, because *"pushing `workshop` through `_stage_log_transition` would split
the pipeline's two `intake` writes into two separate entries and re-introduce the entry-per-write
noise the transition rule exists to prevent."*

So the missing divider is a consequence of a decision that was made for a good reason. Fixing it
means finding a way to open a divider for an explicit span without re-splitting `intake` — which
is a change to the stage-log transition contract, not a label change.

### Why it was not fixed in 21-07

**It is a divider-PRESENCE defect, not a divider-LABEL defect**, and 21-07's scope (SC6) is
labels: no raw stage key may reach the operator's screen. `workshop` is fully labelled
(`Question workshop`) and could never leak raw. Adding a divider would change *which events the
pipeline emits*, which is engine-observability behaviour and belongs with the SC1 family of work
(21-03/05/06), not with the label resolver.

**Note for whoever picks this up:** 21-07's new
`test_every_pipeline_stage_key_resolves_to_a_human_label` already asserts over the union that
includes `workshop`, so the label side is protected today. What is unprotected is that the stage
has no heading — no test asserts a divider exists per reported stage. If this is fixed, that
assertion is the thing to add alongside it.
