---
quick_id: 260907-eyd
slug: validation-writes-submit-completeness
date: 2026-09-07
status: complete
commits:
  - 21acffd  # DEF-23.2-12 — frontend
  - e03b2c9  # DEF-23.2-13 — backend
---

# SUMMARY — DEF-23.2-12 + DEF-23.2-13

Both closed. **Not deployed** at time of writing.

| Gate | Result |
|---|---|
| Backend | **764 passed / 2 skipped / 0 failed** (736 baseline + 28 new — closes exactly) |
| Frontend | tsc **0 errors**, **161 vitest** passed (154 baseline + 7 new), i18n-audit **PASS** |
| Route inventory | **61 gate-bearing routes / 26 gated**, `/intakes` 43 / 26 — IDENTICAL to the pre-phase walk |

Neither change moves a gate. `submit_intake` swapped one dependency for a combined one on the
same session; the walk confirms no route appeared, disappeared or changed gating.

## What the register had wrong

Four corrections, all made before writing code and all recorded in `PLAN.md`. The first three
changed the fix; the fourth changed its scope.

1. **Not one line — two gates.** `handleChange` returned before `setDirtyFields`, so nothing was
   ever marked dirty; fixing `saveCurrentSection` alone would have changed nothing, because
   `dirtyKeys` would still be empty.
2. **The headline defect was the wrong one.** "Keep Nestor's proposal" (`onConfirm`) only
   collapses a diff card to a badge — it never changes an answer, so nothing was lost by not
   persisting it. The real loss was `extra_questions_proposed`, the one enabled control in the
   validation phase: the client's choice of AI-proposed extra research questions was discarded
   while the status advanced, so those questions never reached the research run.
3. **⭐ The naive fix would have been worse than the bug.** Deleting both early-returns makes the
   revert button's fields dirty too — and the server refuses those in the validation phase with
   409 (D-23.2-05). `saveCurrentSection` returns false, `doSubmit` gates on it, and the client
   could never submit. A silent discard would have become a permanent hard block.
4. **DEF-23.2-13 needed a narrower scope than written.** `POST /submit` serves two transitions.
   Enforcing completeness on `reviewed -> validated_by_client` is a lockout: the client has one
   writable field in that phase, so a failing client cannot comply — and the reviewed answer set
   is the admin's work by then. Enforced on `draft -> submitted` only.

## The shape of the fix

**Frontend.** The rule existed in three places and the save paths held a stale copy. One
predicate (`lib/intake-writable.ts`) now drives `handleChange`, `saveCurrentSection` and the
`disabled=` prop. The prop's inline expression was *equivalent* to the new predicate — it was a
second copy, and their drifting apart is the entire defect. Enabled and saved are now the same
question.

**Backend.** `check_submit_completeness` is a separate function from `check_answer_batch`, not a
relaxation of it. The ⛔ block forbidding these three constraints on the per-save path is
unchanged and still correct; the docstring now names the new function so the two read as one
policy rather than a contradiction.

## Three pre-existing tests went red — correctly

`test_transitions_advance_and_reject_out_of_scope`, `test_transition_audited` and
`test_submit_intake_open_to_user` each created a bare intake and submitted it expecting 200.
Predicted before running, then confirmed: 3 failed / 36 passed.

They are **fixture updates, not assertion changes** — each now fills the form first, as a real
client does. Not one assertion was weakened. The client-surface pin (row 6) is the one that
mattered: it asserts EXACTLY 200 to prove the route is open to `role=user`, so a 422 there would
have been a *false authorization signal* — the route is open, the payload was incomplete.

`complete_answer_batch` (in `conftest.py`) is DERIVED from the canonical schema, so a future
required field widens every fixture using it instead of silently making them incomplete again.

## Recorded, not fixed

* **The revert affordance is inert by design.** Reverting a Nestor refinement targets fields the
  server refuses in the validation phase, so the button cannot work without reopening D-23.2-05.
  Behaviour is unchanged by this task. Whether a client may reject a refinement is a product
  decision, not a bug fix — it needs an operator ruling.
* **`handleChange` writes localStorage before the writable check**, so a revert *looks* persisted
  until the cache clears. Pre-existing; unchanged.
* **`ValidationDiff.tsx:211` keys on `research_questions`, which is not one of the 29 canonical
  field keys.** The refined-question diff cards therefore never render in the client form. It is
  a real answer key (`AIReviewPanel.tsx:383` writes it as superadmin, which is exempt from schema
  membership) but no canonical section declares it, so `ValidationDiffForField` is never called
  with it. Pre-existing and unrelated to these two defects — worth its own look.

## Still true after this task

There are still **zero browser/E2E tests**. DEF-23.2-12 is exactly the defect class they catch:
an enabled control whose value is dropped is invisible to every gate this repo has — tsc, 161
vitest assertions, 764 backend tests and the i18n audit were all green while it shipped. The
seven new unit tests pin the predicate, not the user journey.
