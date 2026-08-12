# Phase 21 — Operator UAT on RECORDED data

**Status:** ◐ **PARTIALLY WALKED 2026-08-11 — operator gave a roll-up impression plus five change
requests. Per-check verdicts below remain UNFILLED and MUST NOT be inferred from the roll-up.**

> ## Operator walkthrough, 2026-08-11 — recorded VERBATIM
>
> > "ok looks good but verification report should open its own page not a dropdown (too long) also
> > verification report contains very good information , so style it better , like a dashboard and
> > the citation should show when you hover over them , and the list of citation should be hidden by
> > default and user can expand and see. also there are alot of duplicate citations is there a reason
> > for that , why not remove duplicates and have 1 number for it? also activity shouldnt show on the
> > intake page , we already have a open run button that opens it in a different page and it is
> > exactly the same so no need to have it there."
>
> **What this settles:** the report IS reachable and DID render (B1–B4 exercised in substance — the
> operator read its content and judged it "very good information"). **What it does NOT settle:** no
> per-check verdict was stated. SC2 (no spinner on a terminal run) and SC6 (final divider reads
> "Run complete", not `done`) were NOT answered and are both blockers. They stay `(awaiting
> operator)`. **"looks good" is not a PASS on a check nobody named** — recording it as one would be
> the exact false green this document exists to prevent.
>
> **Five change requests ROUTED to Phase 22** (recording rule 2: routed, never absorbed):
> 1. Verification report opens on its own page, not an inline dropdown — it is too long.
> 2. Restyle it as a dashboard; the information itself is good.
> 3. Citations show on hover; the citation LIST is collapsed by default and expandable.
> 4. Duplicate citations collapse to one number per source.
> 5. The activity feed is REMOVED from the intake page — "Open run" already opens the same thing.
>
> ⚠ **Item 5 REVERSES this document's R2**, which deliberately kept the embedded
> `ResearchRunProgress` (21-CONTEXT, out of scope). That is the operator's call, made with the
> reversal in front of them. Recorded here so a later reader does not mistake its removal for a
> Phase 21 regression.
>
> **Answer to the operator's question about duplicate citations** (they asked "is there a reason"):
> yes, and it is a defect rather than a design. `_assign_numbers` (`citations/numbering.py:225`)
> already reuses a number when it sees a source again — the dedupe is correct at the numbering
> layer. The duplication is created one layer up, at source INSERT
> (`citations/extractor.py:289-322`): the conflict key is `(tenant_id, content_hash)`, a hash of the
> **snapshot text**, not the URL. So (a) two providers fetching the same page with even slightly
> different extracted text produce two `source` rows and therefore two numbers, and (b) when there
> is no snapshot at all the code says *"No snapshot to hash — skip dedupe and insert plainly"*, so
> every citation of a snapshot-less source inserts a fresh row every time. Same family as V-01's
> exact-string merge key. The fix is a normalized-URL identity (prefer `resolved_url`, strip `www.`,
> trailing slash, tracking params) — read-time for display first, since that is reversible and needs
> no migration.
**Created:** 2026-08-10 by plan 21-08 (Task 3 artifact, pre-created at the Task 2 checkpoint)
**Spend:** **ZERO.** Every check here runs against an EXISTING recorded run.

> ⛔ **DO NOT TRIGGER A RESEARCH RUN TO COMPLETE THIS DOCUMENT.** There are nine run prefixes in
> the audit bucket already. The ~$45 measuring run is the NEXT action after this phase closes, not
> part of it. If a check cannot be answered without a new run, its verdict is **NOT-OBSERVABLE** —
> that is a legitimate answer and it is the correct one.

## Preconditions

- Phase 21 merged, and `nestor-frontend` + `tribunal-worker` deployed per
  `infra/DEPLOY-RUNBOOK.md` § Phase 21.
- Operator signed in as **superadmin** (the run page is superadmin-only by placement AND by API
  authorization).
- Both Cloud Build gates green, recorded by build id in `21-08-SUMMARY.md`.

## Recording rules — carried over, and they are load-bearing

1. **Record the operator's answer VERBATIM, never paraphrased.** A paraphrase of a UAT observation
   is how a defect becomes a rumour.
2. **Every deviation must be ROUTED** — either a follow-up task or an explicitly deferred item with
   the operator's agreement. **Never absorbed silently.**
3. **NOT-OBSERVABLE is a real verdict and must be used honestly.** The recorded runs PREDATE this
   phase's emit sites, so a run that finished before the deploy **has no rows** for the eight
   stages and **cannot** show them. Marking that PASS would be the exact false green this project
   keeps catching.

---

## ⛔ KNOWN AND OUT OF SCOPE — do NOT report these as new Phase 21 failures

Three items below are already found, already ruled, and deliberately not fixed in this phase. If
the walkthrough surfaces them, that is the **expected** observation, not a regression.

| Id | What you will see | Why it is not a Phase 21 failure |
|---|---|---|
| **DEF-21-01** | `npm run lint` is red tree-wide. | **Operator ruling 2026-08-10: stays deferred, stays OUT of Phase 21.** `frontend/scripts/c.ts` (an orphan script imported by nothing) makes `eslint .` exit 1 regardless, and `core.autocrlf=true` makes every file fail `prettier/prettier` on a Windows checkout. Phase 21's four changed frontend sources measured **0 non-prettier rule violations**. ⛔ Running `prettier --write` across `frontend/src/` here defies a ruling. |
| **DEF-21-03** | A stage summary line reads nearly empty — `{'worked': '0s', 'actions': 0}` — most visibly on `coverage`. | The summary is built from `state["items"]`, which is written **only** from `set_stage`'s `detail` argument. **Run events never touch it.** The feed BODY and the summary LINE have two different inputs, so the per-item rows this phase added cannot fix the summary. Known separate defect, one-line fix identified, not applied. |
| **DEF-21-04** | The `workshop` block has body rows but **no phase heading above them**. | `workshop` is written by `StageFeed`, not by a `set_stage` transition, and dividers ride only on transitions. That is deliberate (D-F, plan 15.2-24): pushing it through the transition would split the pipeline's two `intake` writes. **A divider-PRESENCE gap, not a label gap** — `workshop` is fully labelled and can never leak raw. Out of scope. |

---

# PART A — The six phase success criteria

One section per ROADMAP § Phase 21 success criterion. Fill in **PASS**, **FAIL** or
**NOT-OBSERVABLE**, plus what was actually seen.

## SC1 — All 13 tribunal stages emit feed content

**Criterion:** the 8 previously silent stages — `distill`, `merge`, `gate`, `verify`,
`adjudicate`, `coverage`, `conflict`, `synthesize` — each emit a dispatch header and per-item rows,
so no phase renders as a label with nothing under it.

> ⛔ **ON A PRE-DEPLOY RECORDED RUN THIS IS `NOT-OBSERVABLE` BY CONSTRUCTION.** Those runs executed
> before the emit sites existed; they have no rows to show. **Any verdict other than
> NOT-OBSERVABLE must name a run that executed AFTER the deploy.**
>
> **SC1's actual end-to-end proof is the capstone test in plan 21-06**, not this walkthrough.
> Measured row counts in the stubbed harness (0 → N): verify 0→16, distill 0→5, merge 0→3,
> gate 0→2 (5 when it drops), adjudicate 0→3, coverage 0→2, conflict 0→2, synthesize 0→3.

**What IS observable now on a recorded run:** the page renders without error; the stage dividers
carry human labels; the eight stages still render a label. The difference appears on the next run.

- **Verdict:** _(awaiting operator)_
- **Run id walked:** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

## SC2 — A finished agent never renders as a spinner

**Criterion:** `agent_run` rows resolve once their work is done, rather than animating forever
because the feed is append-only.

**This IS observable on recorded data and it is the single clearest check in this list.** On a
**TERMINAL** recorded run (completed / completed_degraded / failed / cancelled / parked), confirm
there is **not one animated spinner anywhere in the feed**.

- **Verdict:** _(awaiting operator)_
- **Run id — MUST be named, and MUST be terminal:** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

## SC3 — The "Show more" toggle appears only where rows are hidden

**Criterion:** never on a phase whose body is empty or shorter than the collapsed preview.

Confirm **no toggle sits above an empty phase**, and that where a toggle **is** shown, clicking it
**reveals rows**.

- **Verdict:** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

## SC4 — `VerificationReport` is reachable from the run page

**Criterion:** funnel, verdicts, superseded, reconciled, unverified and true cost reachable from
the dedicated run page, not only from the intake detail card.

⭐ **The detailed six-step walkthrough for this criterion is PART B below (DEF-21-02).** Part B is
the authority for SC4; this section records the roll-up verdict.

**The one thing that must hold:** the **feed remains rendered while the report is open**. The
report must not replace, hide or unmount the feed.

- **Verdict:** _(awaiting operator)_
- **Feed still rendered beneath the open report? (explicit yes/no):** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

## SC5 — Density of the `deep_research` `thinking` prose

**Criterion (as AMENDED at planning 2026-08-10):** the prose is DIAGNOSED before it is trimmed
(D-12); a per-site keep/cut verdict exists as a reviewable artifact; the operator rules; whatever
is ruled is applied.

> ⚠ **THE RULING WAS `option-c`: NO SOURCE CHANGE to `audited_llm_client.py`, and that SATISFIES
> this criterion.** All 8 `thinking` sites there measured as **money or long-silence** — D-13's two
> KEEP classes — and 5 are pinned by `test_own_researcher.py`, whose own comment reads *"the
> wording is the deliverable — this run was misread as a stall once."* The measured volume driver
> is **CARDINALITY, not altitude**: one correct line multiplied across 19 angles.
>
> **So the improvement expected HERE comes from the collapse toggle and from the other stages
> gaining bodies on the NEXT run — not from cuts to that file.** The artifact is
> `21-DENSITY-AUDIT.md`.
>
> **The density question is SEQUENCED, NOT CLOSED.** The operator re-reads the feed after this
> ships and after one run executes.

- **Verdict:** _(awaiting operator)_
- **Does the deep-research phase read better or worse than it did on 2026-08-10?** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

## SC6 — No raw stage key ever reaches the operator's screen

**Criterion:** and a test enforces it.

Scan **every divider on the page** and confirm none is a `snake_case` string.

> **Note — `done` was NOT latent.** 21-07 measured that **every completed run the operator ever
> opened ended on a divider reading literally `done`**. `NON_SCHEMA_STAGE_LABELS` now maps
> `done → "Run complete"` and `report_spec → "Report shaping"`. **This one IS observable on
> recorded data**, because the label is resolved at READ time on the divider the page renders.

- **Verdict:** _(awaiting operator)_
- **Did the final divider read "Run complete" rather than `done`?** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

---

## Regression checks — this phase must not have broken these

### R1 — The clock does not restart when the page is closed and reopened

15.3 D-01/D-09. Open a run page, note the elapsed clock, close the page, reopen it.

- **Verdict:** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

### R2 — The intake detail card's embedded `ResearchRunProgress` still works

It was **deliberately NOT replaced** (21-CONTEXT, out of scope).

- **Verdict:** _(awaiting operator)_
- **What was actually seen (VERBATIM):** _(awaiting operator)_

---

# PART B — DEF-21-02: plan 21-02's deferred operator UAT

> ## ⚠ WHY THIS SECTION EXISTS
>
> **Plan 21-02's Task 3 was a `checkpoint:human-verify` with `gate="blocking"`. It was DEFERRED to
> plan 21-08 by operator ruling on 2026-08-10 — sequenced, NOT skipped and NOT verified.**
>
> **Operator's reasoning, recorded as theirs:** the code was on an unmerged worktree branch and
> could not be clicked through yet; 21-08 already exists to run a single operator UAT after
> everything is merged and deployed; nothing in Waves 2–4 depends on 21-02. Folding these six
> checks into that one pass means one click-through instead of two.
>
> **Plan 21-02's acceptance is CONDITIONAL on this section.** Its Tasks 1 and 2 are machine-verified
> (tsc clean, vitest 10/10 then 46/46, i18n-audit PASS, build exit 0) — but **the operator-facing
> behaviour is verified by NOTHING until these six steps run.** A phase verifier **must not** count
> **SC4 / D-10 / D-11** as operator-confirmed until then.
>
> ⛔ **21-08's plan file was written BEFORE this ruling existed and does not reference DEF-21-02 on
> its own.** The obligation was injected at execution. **If this phase ships without Part B filled
> in, the deferral has quietly become a skip.**

> ## ⚠ 2026-08-11 — RECONCILED BY PHASE 22, NOT ABANDONED
>
> **Phase 22's D-22-1 moved the verification report onto its own route by operator ruling** — *"verification
> report should open its own page not a dropdown (too long)"*. That ruling landed after this section was
> written, and it changes what three of these six steps can even mean.
>
> **B2, B3 and B4 asked about a TOGGLE sitting beside the activity feed, and about the FEED SURVIVING
> BENEATH an open report. Neither situation exists any more.** There is no toggle, and the report is no
> longer on the same page as the feed. Those three are **UNANSWERABLE AS WRITTEN** and are therefore
> marked **SUPERSEDED**, each with a named Phase 22 successor.
>
> **B1, B5 and B6 test properties that survive the redesign** — the run page loads from "Open run"; the
> affordance is offered on failed and cancelled runs; no affordance appears on a queued or running run.
> They are **CARRIED FORWARD** to Phase 22 successors that ask the same question against the new
> navigation.
>
> **⛔ THIS IS A RECONCILIATION, NOT A SKIP, AND A SUPERSESSION IS NOT A PASS.** The successors live in
> `.planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/22-UAT.md` PART B as
> **22-B1 … 22-B6**, they carry the same blocker status, and they all ship **UNFILLED**. A verifier
> reading this file must **follow the pointer** rather than treat these six as forgotten — and must not
> read any of them as confirmed until an operator fills in the successor.
>
> ⚠ **Scope of this reconciliation: PART B only.** Phase 22 changed no engine write path and triggered
> no research run. Every check in PART A above whose answer needs a **post-deploy live run** — SC1 above
> all — is **untouched by this and stays OPEN**. No verdict anywhere in this file is filled in by the
> Phase 22 work.

**Verifiable on RECORDED data with NO spend — do NOT trigger a run.**

**Preconditions:** 21-02 merged and `nestor-frontend` deployed; operator signed in as superadmin.

### The six steps, verbatim

| # | Step | Expected result | Blocker if failed? |
|---|------|-----------------|--------------------|
| 1 | Open `/admin/pulse/intakes`, open any intake that has a research run, and click through to the run page via the card's **"Open run"** link. | The dedicated run page at `/admin/pulse/runs/:runId` loads. | Yes |
| 2 | Look at the vertical order of the page. | The **"View verification report"** toggle appears **BETWEEN the status card and the activity feed** — below the card, above the feed. | Yes |
| 3 | Click the toggle. | The report opens: **funnel**, **verdict sections** and **cost block** all render. **AND the ACTIVITY FEED IS STILL ON THE PAGE BELOW IT** — the report must not replace, hide or unmount the feed. | Yes — the single most important check in the list |
| 4 | Click the toggle again. | The report collapses, the label returns to "View verification report", and **the feed is untouched**. | Yes |
| 5 | If a **failed** or **cancelled** run exists in the list, open it and confirm the toggle is offered there too. | The toggle IS offered on failed and on cancelled runs (D-11 — these are the two states the embedded intake card throws away). | **No — NOT a blocker if no such run exists.** Record "none available" and move on. |
| 6 | Open a **queued** or **running** run. | **NO toggle appears.** Its **ABSENCE is the CORRECT result**, not a defect — the pipeline has not reached the verify stage, so there is nothing to fetch. | Yes — but note a *present* toggle here is the failure, not an absent one |

### Verdicts

#### B1 — Run page loads via "Open run"
> **CARRIED FORWARD → 22-B1** (see 22-UAT.md). Not answered here.
- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

#### B2 — Toggle sits BETWEEN the status card and the activity feed
> **SUPERSEDED by D-22-1 → 22-B2** (see 22-UAT.md). The toggle no longer exists; the link in the same
> position is checked there.
- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

#### B3 — Report opens (funnel + verdicts + cost) AND THE FEED SURVIVES BELOW IT
⭐ **The single most important check in this document.** The feed surviving is the structural
property 21-02 was built to guarantee — it is what the embedded intake card gets wrong.
> **SUPERSEDED by D-22-1 → 22-B3** (see 22-UAT.md). The report is a separate page, so "the feed survives
> beneath it" cannot arise; the equivalent property is checked at 22-B4.
- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Funnel rendered?** _(awaiting operator)_
- **Verdict sections rendered?** _(awaiting operator)_
- **Cost block rendered?** _(awaiting operator)_
- **FEED STILL PRESENT BELOW THE REPORT?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### B4 — Toggle collapses cleanly, label returns, feed untouched
> **SUPERSEDED by D-22-1 → 22-B4** (see 22-UAT.md). "Back to run leaves the run page whole" replaces
> "the toggle collapses cleanly".
- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

#### B5 — Toggle offered on failed / cancelled runs (D-11)
> ⚠ **NOT A BLOCKER IF NO FAILED OR CANCELLED RUN EXISTS.** Record **"none available"** and move
> on. Do not manufacture one, and above all do not trigger a run to create one.
> **CARRIED FORWARD → 22-B5** (see 22-UAT.md). Still NOT a blocker if no failed/cancelled run exists.
- **Verdict:** _(awaiting operator — or "none available")_ · **Blocker:** **NO**
- **Run id, if one existed:** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### B6 — NO toggle on a queued or running run
> ⚠ **THE EXPECTED RESULT IS THE TOGGLE'S ABSENCE.** An absent toggle here is **CORRECT** — the
> pipeline has not reached the verify stage, so there is nothing to fetch. **A toggle that IS
> present on a queued or running run is the FAILURE.** Do not record "no toggle" as a defect.
> **CARRIED FORWARD → 22-B6** (see 22-UAT.md). The expected result is still the AFFORDANCE'S ABSENCE.
- **Verdict:** _(awaiting operator)_ · **Blocker:** yes (a *present* toggle is the failure)
- **Run id and its status:** _(awaiting operator)_
- **Was a toggle present? (yes = FAIL, no = PASS):** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

---

## Roll-up

| Check | Verdict | Blocker |
|---|---|---|
| SC1 — all 13 stages emit | _(awaiting)_ | expected NOT-OBSERVABLE pre-run |
| SC2 — no finished agent spins | _(awaiting)_ | yes |
| SC3 — toggle only where rows hidden | _(awaiting)_ | yes |
| SC4 — verification report reachable | _(awaiting)_ | yes |
| SC5 — density | _(awaiting)_ | no — ruling was `option-c`, no source change |
| SC6 — no raw stage key on screen | _(awaiting)_ | yes |
| R1 — clock does not restart | _(awaiting)_ | yes |
| R2 — embedded card still works | _(awaiting)_ | yes |
| B1…B6 — DEF-21-02's six steps | _(awaiting)_ | B5 is NOT a blocker; all others are |

**Operator sign-off:** _(awaiting — type "approved" with the verdicts, or describe the failures)_

---

*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Created by plan 21-08 · carries DEF-21-02's six deferred steps as a hard obligation*
*No verdict in this file may be filled from inference — only from the operator's own observation*
