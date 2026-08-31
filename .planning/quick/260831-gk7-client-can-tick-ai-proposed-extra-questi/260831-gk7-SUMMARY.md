---
quick_id: 260831-gk7
status: complete
date: 2026-08-31
description: "client can tick AI-proposed extra questions; honour show_to_client"
commits:
  - 41d6810 feat(260831-gk7) honour show_to_client on the client's proposal list
  - 73651b7 fix(260831-gk7) let the client tick proposals in the validation phase
key-files:
  modified:
    - frontend/src/components/intake/FieldRenderer.tsx
    - frontend/src/components/intake/IntakeForm.tsx
---

# Quick task 260831-gk7 — the client can now choose which proposed questions to add

Closes defect 2 of the 2026-08-31 intake test. Two independent bugs that had to ship together.

## What was wrong

**2a — the client could not tick.** `routes/intake.$id.tsx:106` sets `editable: status === "draft"`,
and the validation phase is entered at status `reviewed`. So `editable` was always false there,
`IntakeForm` passed `disabled={!editable}` down, and the proposal checkboxes rendered **inert**.

**2b — the operator's curation was ignored.** `AIReviewPanel.tsx:352` writes `show_to_client`.
Nothing read it — one occurrence in the whole repo, the write itself. The client would have been
offered every proposal, including the ones the operator excluded.

Fixing 2a alone would have been **worse than the bug**: it turns an inert list of all-proposals into
a live one, letting the client commission research the operator had rejected.

## The trap, and how it was avoided

`ProposalListControl`'s toggle maps over the item array and passes the **whole result** to
`onChange`. Filtering the array itself would have written back only the client-visible subset —
**permanently deleting every operator-excluded proposal on the client's first click**, silently.

So the filter is display-only:

```ts
const items = Array.isArray(value) ? value : [];        // FULL array — the write surface
const visible = items
  .map((it, i) => ({ it, i }))                          // i = index in the FULL array
  .filter(({ it }) => (clientSurface ? it.show_to_client === true : true));
// toggle() still maps over `items`, never over `visible`
```

Each rendered row carries its **full-array** index, so `toggle(i)` and `key={i}` both address the
stored array, not the projection.

`show_to_client === true` is strict rather than `!== false`. An entry with no explicit operator
include is not offered. That direction fails safe: an empty list the operator can notice, rather
than the client silently being offered questions the operator rejected.

## Scope discipline

| Surface | Behaviour |
|---|---|
| Client validation page | sees only `show_to_client === true`; can tick |
| Operator AI review panel | sees **all** proposals — `clientSurface` unset, so unfiltered (it must be able to un-exclude) |
| Every other field in validation phase | still read-only |

Only `proposal_list` was re-opened, and only in the validation phase. The rest of the form stays
locked on purpose — those answers were validated at submission, and re-opening them after review
would let the client silently rewrite reviewed content.

**`routes/intake.$id.tsx` has an empty diff.** The status gate was deliberately left alone;
`payload.phase` already carried everything needed. No save wiring either — `saveCurrentSection`,
`saveAnswers` and `sectionHasChange` already run in the validation phase.

**Data model unchanged:** operator sets `show_to_client`, client sets `approved`, and
`backend/app/research/brief.py` counts only `approved` entries. That contract was already correct.

## Verification

| Check | Result |
|---|---|
| `npx tsc --noEmit` | **0 errors** |
| `npx vitest run` | **135 passed / 9 files** (unchanged) |
| `grep -rn "show_to_client" frontend/src` | now a **READ** at `FieldRenderer.tsx:207`, not just the write |
| Files changed | exactly the **2** planned; `routes/intake.$id.tsx` empty diff |
| Backend / deploy | **none** — safe to land while a research run is in flight |

## ⛔ What this does NOT prove

This repo has **no `.tsx` test at all** (`vitest.config.ts` includes only `src/**/*.test.ts`), so the
tick, the filter and the index mapping are verified by typecheck and inspection, **not** by a
rendering test. The 135 passing tests do not touch this code.

The write-back preservation is the thing most worth an operator click-through, because its failure
mode is silent data loss: **tick one proposal on the client page, save, reload, and confirm the
operator-excluded proposals are still present in the stored answer.**

Not deployed — this ships with the next `nestor-frontend` build.

## Self-Check: PASSED
