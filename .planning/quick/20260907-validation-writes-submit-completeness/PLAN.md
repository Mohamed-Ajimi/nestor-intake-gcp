---
quick_id: 260907-eyd
slug: validation-writes-submit-completeness
date: 2026-09-07
status: planned
---

# Quick task — DEF-23.2-12 + DEF-23.2-13

Close the two fast follow-ups left open by phase 23.2. Both were recorded by plan 23.2-09 as
deferrals because `frontend/` was an explicit scope fence for that phase.

**Investigation on 2026-09-07 corrected the register on three points. They change the fix, so
they are recorded here before the tasks.**

## Correction 1 — DEF-23.2-12 is TWO gates, not "one line"

`deferred-items.md` says the fix is one line in `saveCurrentSection`. It is not. Two independent
early-returns each block the write, and fixing only the second changes nothing:

* `IntakeForm.tsx:197` — `handleChange` runs `if (!editable) return;` **before**
  `setDirtyFields(...)`. In the validation phase nothing is ever marked dirty.
* `IntakeForm.tsx:210` — `saveCurrentSection` runs `if (!editable) return true;`.

With only the second fixed, `dirtyKeys` is empty and the function still returns early.

## Correction 2 — the headline defect is the wrong one

The register says *"a client ticks 'keep Nestor's proposal' and the tick is discarded."*
Measured: `onConfirm` adds a key to `confirmedDiffKeys`, which only collapses the diff card to a
badge (`ValidationDiff.tsx:114-121`). It never changes an answer. **Nothing is lost by not
persisting it.**

The real loss is `extra_questions_proposed` — the single `proposal_list` field, the ONLY enabled
control in the validation phase (`pulse_intake_v1.json`, section `phase: "validation"`). The
client ticks which AI-proposed extra research questions to include, presses Akkoord, the status
advances to `validated_by_client`, and the selection is discarded. Those questions never reach
the research run.

## Correction 3 — the naive fix creates a WORSE bug

Deleting both early-returns makes every changed field dirty. The revert button
(`ValidationDiffForField` → `onRevert` → `handleChange`) targets `decision_or_goal`,
`audience_description`, `company_intro`, `output_size`, `output_form` — none of them
`proposal_list`. The server refuses those in the validation phase with **409**
(D-23.2-05, `intake_write_policy.py:231-237`). `saveCurrentSection` returns `false`, `doSubmit`
aborts on it, and **the client can never submit at all**. A silent discard becomes a permanent
hard block.

So the fix must reproduce the `disabled=` predicate exactly, not drop it.

## Correction 4 — DEF-23.2-13 must be narrower than written

`POST /intakes/{id}/submit` serves TWO transitions (`_SUBMIT_TRANSITIONS`,
`intake_routes.py:1457-1460`): `draft -> submitted` and `reviewed -> validated_by_client`.

Enforcing completeness on the second is a lockout. In the validation phase every field except
`extra_questions_proposed` is disabled, so a client who fails the check has no control with
which to fix it and no way forward. **Enforce on `draft -> submitted` only** — the transition
the browser already gates with exactly these rules, where server enforcement adds defence in
depth and no new failure mode.

---

## Task 1 — `frontend`: one writable-field rule, used by all three call sites

**New** `frontend/src/lib/intake-writable.ts` — pure, no React, no network:

```
writableFieldKeys(sections, { editable, isValidationPhase }) -> Set<string>
```

A key is writable when `editable` (status `draft`), or when the phase is `validation` and the
field's `type` is `proposal_list`.

**`frontend/src/components/intake/IntakeForm.tsx`:**
1. `writableKeys` as a `useMemo` over the rendered `sections`.
2. `handleChange` — replace `if (!editable) return;` with `if (!writableKeys.has(key)) return;`.
3. `saveCurrentSection` — drop `if (!editable) return true;`; filter `dirtyKeys` by
   `writableKeys`.
4. `FieldRenderer` — `disabled={!writableKeys.has(f.key)}`, replacing the inline expression.

Step 4 is semantically identical to the expression it replaces
(`!editable && !(isValidationPhase && type === "proposal_list")` ≡ `!writable`). The point is
that ONE definition now drives disabling *and* saving. Their having drifted is the whole defect.

**Test** `frontend/src/lib/__tests__/intake-writable.test.ts` — draft opens everything;
validation opens `proposal_list` ONLY; a non-proposal field stays closed in validation (the
409-lockout guard); unknown phase closes everything.

## Task 2 — `backend`: completeness at the submit verb

**`backend/app/intake_write_policy.py`** — add `check_submit_completeness(answers, *, role)`,
pure, raising `AnswerWriteViolation(422, ...)`. Enforces `required`, `min_length` (longtext),
`min_items` (list) — mirroring `validateField` (`IntakeForm.tsx:33-58`). Skips admin-only keys
(a client cannot fill them) and `download` display-only fields. Superadmin exempt, matching
`check_answer_batch`.

The module's existing ⛔ block says these three are NOT enforced. That prohibition is about
`check_answer_batch` and stays true — update it to name the new function so the two read as one
policy, not a contradiction.

**`backend/app/api/intake_routes.py::submit_intake`** — swap to `get_intake_and_answer_repos`,
and when `old_status == "draft"` build `{field_key: value_json ?? value}` from
`list_for_intake` and call the check. Precedence: ownership 404 → lifecycle 409 →
completeness 422, placed before `repo.patch`.

**Test** `backend/tests/test_submit_completeness.py` — missing required 422; short `company_intro`
(min_length 100) 422; empty `questions` (min_items 1) 422; complete draft 200; **`reviewed ->
validated_by_client` with an incomplete answer set still 200** (the lockout guard); superadmin
exempt.

## Out of scope, recorded not fixed

* **The revert button is inert by design.** Reverting a Nestor refinement targets fields the
  server refuses in the validation phase, so the affordance cannot work without reopening
  D-23.2-05. Behaviour is unchanged by this task. Whether the client may reject a refinement is
  a product decision, not a bug fix.
* **`handleChange` writes localStorage before the writable check**, so a revert looks persisted
  until the cache is cleared. Pre-existing; unchanged here.
* **`ValidationDiff.tsx:211` keys on `research_questions`, which is not one of the 29 canonical
  field keys** — the refined-question diff cards therefore never render in the client form.
  Pre-existing, unrelated to these two defects.
