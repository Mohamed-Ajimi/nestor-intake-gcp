# Phase 21 — deferred items

Out-of-scope discoveries logged during execution. Per the executor scope boundary these were
NOT fixed: they are pre-existing and not caused by the task's own changes.

---

## DEF-21-01 — `npm run lint` is already red at HEAD, for two unrelated reasons

**Found during:** 21-02 Task 2 (`cd frontend && npm run lint` acceptance criterion)
**Status:** ⛔ **LEAVE DEFERRED — OPERATOR RULING, 2026-08-10. This is not an oversight.**

> **Do not re-open this as a missed item.** The operator was shown this finding and ruled
> explicitly that it stays deferred and stays **out of Phase 21**. Their reasoning: it predates
> this work, and fixing it inside a phase whose acceptance criteria measure **single-path diffs**
> would make every remaining plan's diff unreadable.
>
> A later agent that "helpfully" runs `prettier --write` across `frontend/src/` during Phase 21
> is defying a ruling, not closing a gap. Fix it in its own change, after Phase 21.
**Files:** repo-wide; the two content complaints are in
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

### What 21-02 itself contributed

**Zero.** `npx eslint` on the three files 21-02 touches, with `Delete ␍` filtered out, reports
only the two pre-existing lines above. Every line 21-02 added is prettier-clean.

### Why it was not fixed here

Reformatting those two hunks would put unrelated churn into a diff whose acceptance criteria
explicitly measure that it touches exactly one path and nothing else. It is a one-line-each fix
for whoever owns the lint gate, and it should land as its own change together with a ruling on
whether `.prettierrc` should pin `endOfLine: "auto"` so Windows worktrees stop drowning the
signal in 28,000 carriage-return errors.

**Recommended follow-up (not done here, and NOT during Phase 21 per the ruling above):** pin
`endOfLine` in `.prettierrc`, then run `prettier --write` once across `frontend/src/` as a single
dedicated commit.

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
