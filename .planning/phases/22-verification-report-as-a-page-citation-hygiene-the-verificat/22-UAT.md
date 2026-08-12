# Phase 22 — Operator UAT on RECORDED data

**Status:** ⏳ **AWAITING OPERATOR.** Nothing below has been walked. Every verdict slot is unfilled
and **no slot may be filled from inference** — only from the operator's own observation.

**Created:** 2026-08-11 by plan 22-09
**Spend:** **ZERO.** Every check here runs against an EXISTING recorded run.

> ⛔ **ZERO SPEND — DO NOT TRIGGER A RESEARCH RUN TO COMPLETE THIS DOCUMENT.** There are nine run
> prefixes in the audit bucket already, and the deployed code has not been exercised by a run since
> 2026-08-05. If a check cannot be answered without a new run, its verdict is **NOT-OBSERVABLE** —
> that is a legitimate answer and it is the correct one. The ~$45 measuring run is a separate,
> later action; it is not part of this walkthrough.

## Why this document exists

Phase 21's walkthrough produced five change requests, recorded verbatim in `21-UAT.md` and locked as
D-22-1 … D-22-5 in `22-CONTEXT.md`. Phase 22 built all five. **This document is where the operator
says whether what was built is what they asked for** — and it is also where Phase 21's six deferred
DEF-21-02 checks are finally closed out (PART B).

## Preconditions

- Phase 22 merged, and **the deploy surface DERIVED by plan 22-10 deployed with its digests proven**
  (§ Phase 22 of `infra/DEPLOY-RUNBOOK.md`). ⚠ Do not assume the surface is the same as a prior
  phase's — 2026-08-06 established that a stale surface ruling can leave a fix *inert while reading
  as deployed*. Take the service list from 22-10's derivation table.
- Operator signed in as **superadmin** (both the run page and the report page are superadmin-only by
  placement under `admin.pulse`, and by API).
- At least one intake with a **terminal** research run that reached the verify stage, so a report
  exists to read.

## Recording rules — carried from Phase 21, and they are load-bearing

1. **Record the operator's answer VERBATIM, never paraphrased.** A paraphrase of a UAT observation
   is how a defect becomes a rumour.
2. **Every deviation must be ROUTED** — a follow-up task, or an explicitly deferred item with the
   operator's agreement. **Never absorbed silently.**
3. **NOT-OBSERVABLE is a real verdict and must be used honestly.** Anything that needs a run that
   executed after the deploy cannot be answered here.
4. **"Looks good" is not a PASS on a check nobody named.** A roll-up impression is recorded as a
   roll-up impression; it does not fill in the checks below.

---

## ⛔ KNOWN AND OUT OF SCOPE — do NOT report these as new Phase 22 failures

Each item below is already found, already recorded, and deliberately not fixed in this phase. If the
walkthrough surfaces one, that is the **expected** observation, not a regression.

| Id | What you will see | Why it is not a Phase 22 failure |
|---|---|---|
| **DEF-21-01** | `npm run lint` is red tree-wide. | **Operator ruling 2026-08-10: stays deferred, stays out of scope.** `frontend/scripts/c.ts` (an orphan script imported by nothing) makes `eslint .` exit 1 regardless, and `core.autocrlf=true` makes every file fail `prettier/prettier` on a Windows checkout. Phase 22 measured **0 non-prettier violations** on every file it touched. ⛔ Running `prettier --write` across `frontend/src/` here defies a ruling. |
| **DEF-21-03** | A stage summary line on the RUN page reads nearly empty — `{'worked': '0s', 'actions': 0}`, most visibly on `coverage`. | Phase 21 defect, ruled deferred. The feed BODY and the summary LINE have two different inputs, so per-item rows cannot fix the summary. Not carried into Phase 22. |
| **DEF-21-04** | The `workshop` block on the RUN page has body rows but **no phase heading above them**. | Phase 21 defect, ruled deferred and deliberate (D-F, plan 15.2-24). A divider-PRESENCE gap, not a label gap. |
| **DEF-22-01** | Nothing visible. `ResearchRunProgress`'s ~350-line component body is still compiled but no longer rendered anywhere. | D-22-5 asked that the feed not *show* on the intake page; removing the render site does exactly that. The **file must survive** — the run page imports `useActiveResearchRun` and `IntakeOpenRunLink` out of it. Deleting it would break the run page. A later dedicated cleanup, not this phase. |
| **DEF-22-02** | Nothing visible. Two engine test files cannot be collected locally on Windows. | A local-harness env-var ceiling (32767 chars), Windows-only. The Cloud Build gate runs them on Linux. Not a code defect. |
| **DEF-22-03** | Nothing visible **unless a key is broken** — and that is the point. `i18n-audit.mjs` cannot see any interpolated `t("key", { … })` call, and there are 102 of them. | A gate-coverage defect in a script no Phase 22 plan owns. It means a green i18n audit is **not** proof that every key resolves. If any label on screen renders as a raw key name (e.g. `verification.statClaims`), that IS a real finding — record it. |
| **DEF-22-04** | Nothing visible. Two orphaned locale keys (`intakeDetail.toast.researchResumed`, `…ResumeFailed`) left behind by the intake-page removal. | Dead copy, zero runtime effect. |
| **DEF-22-05** | Nothing visible. Five order-dependent tribunal test failures. | Confirmed byte-identical at the pre-phase commit `9afdf2d`; every one passes in isolation. Harness-isolation, not product. |

---

## ⚠ WHAT PHASE 22 DID **NOT** PROVE — read this before recording any verdict

Three honest limits, stated up front so nothing below is over-read:

**1. Five interaction behaviours are proven by NOTHING automated. They are proven only by you.**
There is no React Testing Library in this repo, and `IntersectionObserver` never executes under
vitest or SSR. So the following have **zero** machine coverage and each carries its own verdict slot
below — a green build says nothing about any of them:

| # | Unproven behaviour | Where it is checked |
|---|---|---|
| U1 | Hover intent — does the preview appear and dismiss at a comfortable delay, or does it flicker / lag / stick? | A3 |
| U2 | Collapse/expand feel on the citation list — does opening and closing it feel right? | A3 |
| U3 | Esc closes the citation sheet, focus is trapped inside it while open, and focus returns to the `[n]` marker you clicked | A3 |
| U4 | The document behind the sheet **does not scroll** — you come back to the sentence you were reading | A3 |
| U5 | The nav rail's active-section marking (driven by `IntersectionObserver`) follows your scrolling | A2 |

**2. Read-time citation dedupe changes DISPLAY only.** One entry per normalized source URL is what
the citation list and the "Sources cited" tile now show. **Cost and corroboration still count the
duplicate `source` rows** until the write-side identity fix lands in its own phase (D-22-4). Nothing
on screen claims otherwise, and nothing in this document should be read as claiming it.

**3. No research run was triggered by this phase, and no engine write path was changed.** Phase 21's
verification is still `human_needed` and its ~$45 measuring run is still untriggered. Therefore every
Phase 21 check whose answer depends on observing a **post-deploy live run** — SC1 above all — stays
**OPEN in `21-UAT.md`** and is *not* closed by Phase 22. Only PART B's six DEF-21-02 navigation
checks are reconciled here, because those are the only ones a code change could reach.

---

# PART A — The five decisions

One section per locked decision. Fill in **PASS**, **FAIL** or **NOT-OBSERVABLE**, plus what was
actually seen, verbatim.

## A1 — D-22-1: the report has its own page, not a dropdown

> **Operator, verbatim:** *"verification report should open its own page not a dropdown (too long)"*

**Walk it:** from `/admin/pulse/intakes`, open an intake that has a research run, click **"Open run"**,
then click **"View verification report"**.

Confirm each of these:

- The run page shows a **`View verification report`** link **where the toggle used to be** (see 22-B2
  for the exact position check).
- Clicking it **changes the URL** to `/admin/pulse/runs/<runId>/verification`.
- The report renders **on that page**.
- The run page itself **no longer renders the report body** anywhere.
- **`Back to run`** (top of the report page, with a left arrow) returns to the run page.
- **Reloading the verification URL in the browser still works** — it is a real route, not a modal.
  A bookmarked or shared link must open the report directly.

> ⚠ **One thing that is deliberate and must NOT be recorded as a defect.** The report **page** does
> not re-derive the run's status, on purpose: `locateResearchRun` returns two ids and no run state, and
> gating on the intake's *latest* run would gate run X's report on run Y's state. So a deep link to a
> run with no verdicts is answered by the report's own data — `verification.emptyReport` ("This run
> recorded no verification verdicts.") or, if the fetch fails, the load error plus a **Try again**
> button. There is intentionally **no** separate "report not available" screen on this page. The
> availability rule lives on the run page, where it decides whether the LINK is offered (that is
> 22-B6).

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **URL after clicking the link:** _(awaiting operator)_
- **Did `Back to run` work?** _(awaiting operator)_
- **Did a browser reload of the verification URL work?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

## A2 — D-22-2: the restyle, as an instrumented document

> **Operator, verbatim:** *"verification report contains very good information , so style it better ,
> like a dashboard"*

The ruling was that the **content is good** — so this is a presentation change and **nothing was
dropped, summarised, merged or reordered**. What was added: a six-tile stat strip and a proportional
gate funnel above the fold, real section headings, and a sticky section nav rail.

**A2a — above the fold.** Without scrolling, confirm you can see the six stat tiles (Claims, With
verdict, Refuted, Unverified, Sources cited, Cost) and the gate funnel as **proportional bars**, not
a comma-separated list of numbers.

- **Verdict:** _(awaiting operator)_ · **Blocker:** no (record, do not block)
- **Observed (VERBATIM):** _(awaiting operator)_

**A2b — THE LOAD-BEARING HALF: nothing was dropped.** Scroll the whole document and confirm all of
these are still present, **in this order**:

| # | Section | Present? |
|---|---|---|
| 1 | Gate funnel | _(awaiting operator)_ |
| 2 | Refuted claims | _(awaiting operator)_ |
| 3 | Supported claims | _(awaiting operator)_ |
| 4 | Insufficient evidence | _(awaiting operator)_ |
| 5 | Superseded verdicts | _(awaiting operator)_ |
| 6 | Superseded / scoped | _(awaiting operator)_ |
| 7 | Reconciled contradictions | _(awaiting operator)_ |
| 8 | Unverified accounting | _(awaiting operator)_ |
| 9 | Numbered citations | _(awaiting operator)_ |
| 10 | True itemized cost | _(awaiting operator)_ |

> ⚠ **A section with zero rows is OMITTED, and that is pre-existing correct behaviour** — it was true
> before this phase too. "Missing because empty" is not "dropped". If you are unsure which applies,
> record what you see and say you are unsure rather than guessing.
> ⚠ **Sections 5 and 6 share a word and must NOT be merged.** "Superseded verdicts" is a skeptic
> verdict class; "Superseded / scoped" is reconciliation-derived. Same word, different question.

- **Verdict on "nothing was dropped":** _(awaiting operator)_ · **Blocker:** **yes**
- **Observed (VERBATIM):** _(awaiting operator)_

**A2c — the nav rail.** On a wide window, a rail sits to the left of the document listing the
sections. Confirm every section that has rows is listed with a count, and that clicking an entry
jumps to that section without the heading being clipped.

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Observed (VERBATIM):** _(awaiting operator)_

**A2d — U5, UNPROVEN BY ANY GATE: the active-section marking.** As you scroll, the rail entry for the
section you are reading should take on a pink left rule and darker text, and the mark should move as
you scroll. `IntersectionObserver` does not execute under the test runner or SSR, so **you are the
only check on this.**

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Did the active mark follow your scrolling?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A2e — the open question, asked plainly.** *Does it read better than it did on 2026-08-10?* This is
a judgement, recorded and not blocking. If the answer is no, say what is wrong — a "dashboard" here
means an instrumented document, and a card-grid direction was already rejected by ruling, so a
complaint needs to be specific to be actionable.

- **Does it read better?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

## A3 — D-22-3: hover preview, collapsed list, and where the panel opens

> **Operator, verbatim:** *"the citation should show when you hover over them , and the list of
> citation should be hidden by default and user can expand and see"*

**A3a — the hover card's content is a closed list.** Hover a `[n]` marker inside a verdict row. The
card must show **exactly three things**: the title, a date labelled **Retrieved** (see A3b), and a
quality tier as squares plus a text label. Plus one affordance hint line (A3f). It must show **no
URL, no provider and no snapshot text** — those belong to the click.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Was anything shown that is not on that list?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A3b — the date label never reads "Published".** The date on the hover card, and the date in the
citation panel, both carry when the crawler **retrieved** the page — not when it was published.
Presenting the one as the other is a factual misstatement, and it was on screen until this phase.

- **Did every citation date read `Retrieved`, and never `Published`?** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

**A3c — the card makes no network request.** It should appear instantly, with no spinner and no page
flicker: every field comes from data already in memory.

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Observed (VERBATIM):** _(awaiting operator)_

**A3d — U1, UNPROVEN BY ANY GATE: hover intent.** There is no interaction test in this repo, so the
*feel* is unmeasured. Hover several markers, move the pointer onto the card and away again. Is the
open delay comfortable, or does the card flicker, lag, stick open, or appear when you did not mean it
to? Can you move the pointer from the marker onto the card without it vanishing?

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Observed (VERBATIM):** _(awaiting operator)_

**A3e — ⭐ THE DEFECT THIS PHASE WAS BUILT TO AVOID: a `[n]` clicked from a verdict row, while the
citation list is still collapsed, must open something VISIBLE.** Before the fix, the citation panel
rendered *inside* the citation list — so with that list collapsed by default, clicking a marker would
have set state and rendered the panel inside a closed container, hundreds of pixels down the page.
The click would have appeared to do nothing. The panel is now a page-level right-hand sheet.

**Walk it exactly:** leave the citation list **closed**, scroll to a verdict row, click a `[n]`.

- **Verdict:** _(awaiting operator)_ · **Blocker:** **yes — this is the single most important check in PART A**
- **Did a panel open, visibly, without you expanding anything?** _(awaiting operator)_
- **Did the citation list stay closed?** (it should — a click must not auto-expand it) _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A3f — U3 and U4, UNPROVEN BY ANY GATE: the sheet's keyboard and scroll behaviour.** Four things,
all supplied by the primitive and none of them exercised by any test in this repo:

- **Esc** closes the sheet.
- While the sheet is open, **Tab stays inside it** (focus is trapped) rather than wandering into the
  document behind.
- On close, **focus returns to the `[n]` marker** you clicked.
- **The document behind the sheet does not scroll** — when the sheet closes you are back at the same
  sentence.

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Esc closed it?** _(awaiting operator)_
- **Focus stayed inside while open?** _(awaiting operator)_
- **Focus returned to the marker on close?** _(awaiting operator)_
- **Did the document stay put?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A3g — the citation list is closed on arrival and shows its count.** Confirm section 9 is **closed**
when the page loads, that its row reads its source count while closed (so you can tell how many exist
without opening it), and that expanding it reveals every source with **no inner scrollbar** and no
height cap.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Was it closed on arrival?** _(awaiting operator)_
- **Was the count visible while closed?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A3h — U2, UNPROVEN BY ANY GATE: the collapse/expand feel.** Open and close the list a few times.
Does the whole row work as the target? Does the chevron read correctly? Does anything jump?

- **Verdict:** _(awaiting operator)_ · **Blocker:** no
- **Observed (VERBATIM):** _(awaiting operator)_

**A3i — ❓ A QUESTION FOR THE OPERATOR TO RULE: strike the fourth hover line?** The hover card carries
one line beyond the three fields you ruled: **"Click to open the stored snapshot"**. It is an
*affordance hint*, not source metadata — with a preview now appearing on hover, there is otherwise no
way for someone to learn that clicking does something different. The design spec flags it explicitly
as the one addition beyond your ruling, and offers it for you to strike. It is one element and one
locale key; **nothing else depends on it.**

- **Ruling — keep it or strike it?** _(awaiting operator)_
- **Reason, if given (VERBATIM):** _(awaiting operator)_

## A4 — D-22-4: one number per source

> **Operator, verbatim:** *"there are alot of duplicate citations is there a reason for that , why not
> remove duplicates and have 1 number for it?"*

> ⛔ **DO NOT COUNT ANYTHING, AND DO NOT COMPARE TO A PREVIOUS READING.** How many duplicates collapse
> in any given run depends on how often a best-effort URL resolution succeeded during *that* run —
> runtime data, unknowable in advance, and no count field is emitted anywhere by design. A number here
> would be a fabricated fact. **The observable property is the one below, and it is the whole check.**

**A4a — the observable property: no two entries in the citation list point at the same source.**
Expand the citation list and read down it. Two entries with different numbers must not be the same
page.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

**A4b — the numbers are sparse, and that is CORRECT.** The list may read `1, 2, 4, 7, …`. Here is
exactly why, in plain words:

- A missing number means that source was the **same page** as an earlier one, so it was folded into
  that earlier entry rather than given its own line.
- The numbers are **deliberately not renumbered**. The `[n]` markers inside the **downloadable
  report** were written at synthesis time and can no longer be changed. If the page renumbered, `[7]`
  on screen would be a *different source* from `[7]` in the report you downloaded — the page and the
  report would disagree about what a number means.
- So the sparseness is the cost of the two staying in agreement. It is not a defect to tidy away, and
  tidying it away would break the more important guarantee.

- **Did the numbering look sparse, and is that acceptable now you know why?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

**A4c — ❓ A QUESTION FOR THE OPERATOR TO RULE: explain the sparse numbering on screen?** Nothing on
the page currently explains the gaps. Research recommends shipping **without** an on-screen note,
because any wording drifts towards a claim about how many duplicates there were — which is precisely
the claim that cannot be made honestly. **Your call.**

- **Ruling — add an on-screen explanation, or leave it out?** _(awaiting operator)_
- **Reason, if given (VERBATIM):** _(awaiting operator)_

**A4d — no verdict row lost its marker.** Folding one entry into another could, done carelessly, take
a marker off a verdict row whose only source was the folded one. An alias list carries those claims
onto the surviving entry to prevent it. Confirm verdict rows still carry their `[n]` markers.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Did you see any verdict row that reads as though a citation went missing?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

> ⚠ **Say it once more, because it is easy to over-read this section.** The folding happens at
> **display** time. **Cost and corroboration figures still count the duplicate rows** until the
> write-side identity fix lands in its own phase. The "Sources cited" tile counts distinct sources
> *shown* — it is not a statement about what the run paid for.

## A5 — D-22-5: the intake page

> **Operator, verbatim:** *"activity shouldnt show on the intake page , we already have a open run
> button that opens it in a different page and it is exactly the same so no need to have it there"*

**A5a — the feed is gone.** Open an intake with a research run. Confirm the intake detail page shows
**no activity feed and no stage list** — no per-stage rows, no agent cards, no live ticker.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

**A5b — ⭐ AND THE "Open run" LINK IS STILL THERE AND STILL WORKS.** This gets its own slot because a
naive reading of D-22-5 destroys it by accident: that link was defined *inside* the very component
being removed, and it is the app's **only** navigation into the run page. Everything else that points
at `/admin/pulse/runs/:runId` only fires once you are already on it. Confirm the link is present on
the intake page and that clicking it lands on the run page.

- **Verdict:** _(awaiting operator)_ · **Blocker:** **yes**
- **Was the link present?** _(awaiting operator)_
- **Did it open the run page?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

---

# PART B — DEF-21-02 reconciliation: Phase 21's six deferred checks, closed here

> ## ⚠ WHAT IS HAPPENING IN THIS SECTION, AND WHY IT IS NOT A SKIP
>
> Phase 21 deferred six blocking operator checks (B1–B6) from plan 21-02 into plan 21-08's single UAT
> pass, by operator ruling on 2026-08-10 — **sequenced, not skipped.** They are still unfilled in
> `21-UAT.md`.
>
> **Three of them cannot be answered any more, because the operator changed the design.** B2, B3 and
> B4 all asked about a **toggle sitting beside the activity feed**, and about **the feed surviving
> beneath the open report**. D-22-1 moved the report onto its own route — *"verification report should
> open its own page not a dropdown (too long)"* — so there is no toggle, and there is no feed on the
> same page for the report to sit beside. Those three are **UNANSWERABLE AS WRITTEN** and are marked
> **SUPERSEDED**, each with a named successor below.
>
> **The other three survive the redesign** and are **CARRIED FORWARD** against the new navigation.
>
> ⛔ **A supersession is not a pass.** All six successors below ship **unfilled**. Nothing in Phase 21
> becomes operator-confirmed by this reconciliation — the questions were rewritten to be answerable,
> not answered. And the Phase 21 checks that need a **live post-deploy run** (SC1 above all) are
> untouched by this and stay OPEN in `21-UAT.md`.

**Verifiable on RECORDED data with NO spend — do not trigger a run.**

### Mapping table

| Phase 21 step | Status | Phase 22 successor |
|---|---|---|
| B1 — run page loads via "Open run" | **CARRIED FORWARD** | 22-B1 |
| B2 — toggle sits BETWEEN the status card and the feed | **SUPERSEDED by D-22-1** | 22-B2 |
| B3 — report opens AND the feed survives beneath it | **SUPERSEDED by D-22-1** | 22-B3 |
| B4 — toggle collapses cleanly, feed untouched | **SUPERSEDED by D-22-1** | 22-B4 |
| B5 — offered on failed / cancelled runs (D-11) | **CARRIED FORWARD** | 22-B5 |
| B6 — NO affordance on a queued / running run | **CARRIED FORWARD** | 22-B6 |

### The six successor checks

#### 22-B1 — the run page loads via "Open run" *(carries Phase 21 B1 forward unchanged in substance)*

From `/admin/pulse/intakes`, open an intake that has a research run and click **"Open run"**. The
dedicated run page at `/admin/pulse/runs/:runId` loads.

**What changed and why:** nothing about the property. The link is now rendered by a small wrapper
rather than by the feed card that used to contain it, and the route file was renamed to an index
sibling so the report could become a sibling page — `/admin/pulse/runs/:runId` still serves the run
page. The check is the same check.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Run id walked:** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### 22-B2 — the report link sits BETWEEN the status card and the activity feed *(SUPERSEDES Phase 21 B2)*

Look at the vertical order of the run page. The **"View verification report"** control appears **below
the status card and above the activity feed**.

**What changed and why:** B2 asked about a **toggle** in that position. **The position is unchanged;
the control is now a LINK**, because the report moved off this page. It is still a sibling of the card
and the feed — deliberately not inside the status card, so no status branch can take it away.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Was it below the card and above the feed?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### 22-B3 — clicking the link NAVIGATES to the report, and funnel + verdicts + cost all render *(SUPERSEDES Phase 21 B3)*

Click the link. You arrive at `/admin/pulse/runs/:runId/verification`, and the **gate funnel**,
**verdict sections** and **cost block** all render there.

**What changed and why:** B3's real subject was *"the report must not replace, hide or unmount the
feed"* — it was Phase 21's most important check because the report used to expand inside the run page.
**That question can no longer arise:** the report is a separate route, so the feed is not on the same
page to be lost. The equivalent property — *is the run page whole when I come back?* — is 22-B4.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Funnel rendered?** _(awaiting operator)_
- **Verdict sections rendered?** _(awaiting operator)_
- **Cost block rendered?** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### 22-B4 — `Back to run` returns to a run page that is WHOLE *(SUPERSEDES Phase 21 B4)*

Click **`Back to run`**. The run page returns with the **status card** and the **full activity feed**
intact, and **the elapsed clock has not restarted**.

**What changed and why:** B4 asked whether collapsing the toggle left the feed untouched. For a
separate page the equivalent question is whether navigating back leaves the run page whole. This is
where B3's structural concern actually lands now.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Status card intact?** _(awaiting operator)_
- **Full activity feed intact?** _(awaiting operator)_
- **Did the elapsed clock restart? (yes = FAIL)** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### 22-B5 — the link IS offered on a failed or cancelled run (D-11) *(carries Phase 21 B5 forward)*

If a **failed** or **cancelled** run exists in the list, open it and confirm the **"View verification
report"** link is offered there too. D-11: those two states are precisely the ones whose evidence
matters most, and the old embedded intake card threw them away.

> ⚠ **NOT A BLOCKER IF NO SUCH RUN EXISTS.** Record **"none available"** and move on. **Do not
> manufacture one, and above all do not trigger a run to create one.**

- **Verdict:** _(awaiting operator — or "none available")_ · **Blocker:** **NO**
- **Run id and status, if one existed:** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

#### 22-B6 — NO link appears on a queued or running run *(carries Phase 21 B6 forward)*

Open a **queued** or **running** run. **No "View verification report" link appears.**

> ⚠ **ITS ABSENCE IS THE CORRECT RESULT.** The pipeline has not reached the verify stage, so there is
> nothing to fetch. **A link that IS present here is the failure.** Do not record "no link" as a
> defect.
>
> ⚠ **Scope: this check is about the LINK on the run page, not the report page.** As A1 explains, the
> report page deliberately carries no status gate — typing the verification URL directly for a
> still-running run is an expected arrival and is answered by the report's own empty state, not by a
> "not available" screen. That is by design, not a gap in this check.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes (in that direction — a *present* link is the failure)
- **Run id and its status:** _(awaiting operator)_
- **Was a link present? (yes = FAIL, no = PASS):** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

---

## Regression checks — this phase must not have broken these

### R1 — the run page's elapsed clock does not restart on close and reopen

15.3 D-01/D-09. Open a run page, note the elapsed clock, navigate away (to the report page and back,
or out and in), and check the clock did not start over.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

### R2 — the run page's activity feed, "Show more" toggles and audit drill-down still work

**This phase renamed that route file**, so it earns an explicit regression check. Confirm the feed
renders, that a "Show more" toggle reveals rows where one is offered, and that the audit drill-down
still opens.

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Observed (VERBATIM):** _(awaiting operator)_

### R3 — no screen anywhere reads `Published:` for a citation date

Check both surfaces that show a citation date: the **hover card** and the **citation panel**. Neither
may read "Published". (Phase 22 renamed the key in all three languages; if you are browsing in Dutch
or French, the equivalents are *Opgehaald* and *Récupéré*.)

- **Verdict:** _(awaiting operator)_ · **Blocker:** yes
- **Language(s) checked:** _(awaiting operator)_
- **Observed (VERBATIM):** _(awaiting operator)_

---

## Roll-up

| Check | Verdict | Blocker |
|---|---|---|
| A1 — the report has its own page, and reload works | _(awaiting)_ | yes |
| A2a — stat strip + funnel above the fold | _(awaiting)_ | no |
| A2b — **nothing was dropped** | _(awaiting)_ | **yes** |
| A2c — nav rail lists and jumps | _(awaiting)_ | no |
| A2d — U5 active-section marking (no automated coverage) | _(awaiting)_ | no |
| A2e — does it read better? (judgement) | _(awaiting)_ | no |
| A3a — hover shows exactly title + date + tier | _(awaiting)_ | yes |
| A3b — the date reads `Retrieved`, never `Published` | _(awaiting)_ | yes |
| A3c — no network call, no spinner | _(awaiting)_ | no |
| A3d — U1 hover intent (no automated coverage) | _(awaiting)_ | no |
| A3e — **`[n]` from a verdict row opens a VISIBLE panel while the list is collapsed** | _(awaiting)_ | **yes** |
| A3f — U3/U4 Esc, focus trap, focus restore, no background scroll (no automated coverage) | _(awaiting)_ | no |
| A3g — list closed on arrival, count visible, no inner scrollbar | _(awaiting)_ | yes |
| A3h — U2 collapse/expand feel (no automated coverage) | _(awaiting)_ | no |
| A3i — ruling: keep or strike the fourth hover line | _(awaiting)_ | ruling, not a pass/fail |
| A4a — no two list entries point at the same source | _(awaiting)_ | yes |
| A4b — sparse numbering understood and acceptable | _(awaiting)_ | no |
| A4c — ruling: explain the sparse numbering on screen? | _(awaiting)_ | ruling, not a pass/fail |
| A4d — no verdict row lost its marker | _(awaiting)_ | yes |
| A5a — the intake page shows no activity feed | _(awaiting)_ | yes |
| A5b — **the "Open run" link survives and works** | _(awaiting)_ | **yes** |
| 22-B1 — run page loads via "Open run" | _(awaiting)_ | yes |
| 22-B2 — link sits between the card and the feed | _(awaiting)_ | yes |
| 22-B3 — link navigates; funnel + verdicts + cost render | _(awaiting)_ | yes |
| 22-B4 — `Back to run` returns a whole run page | _(awaiting)_ | yes |
| 22-B5 — offered on failed / cancelled | _(awaiting)_ | **NO** — "none available" is a valid answer |
| 22-B6 — NO link on queued / running | _(awaiting)_ | yes (a *present* link is the failure) |
| R1 — clock does not restart | _(awaiting)_ | yes |
| R2 — feed, "Show more", audit drill-down still work | _(awaiting)_ | yes |
| R3 — nothing reads `Published:` | _(awaiting)_ | yes |

**Operator sign-off:** _(awaiting — type "approved" with the verdicts, or describe the failures)_

**After sign-off, the two rulings in A3i and A4c must be ROUTED** — implemented, or recorded as a
deferred item with the operator's agreement. Neither may be absorbed silently.

---

*Phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat*
*Created by plan 22-09 · closes DEF-21-02's six deferred steps by reconciliation, not by skipping*
*No verdict in this file may be filled from inference — only from the operator's own observation*
