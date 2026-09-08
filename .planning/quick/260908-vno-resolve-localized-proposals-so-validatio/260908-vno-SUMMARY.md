---
quick_id: 260908-vno
status: complete
tasks_completed: 1
commit: 7ffdb46
---

# 260908-vno — Resolve localized proposals so the client's ValidationDiff cards render

**Defect:** DEF-23.2-16b — the second consumer of the root cause fixed in `260908-m7j`.

Resolved the `apply-intake-skill` proposals payload at its **load boundary** in `IntakeForm.tsx`,
so `ValidationDiff`'s (correct) string guards are handed the strings they already expect. The
client now sees the refinement diff cards instead of a silently empty "gereviewd" form.

**Commit:** `7ffdb46` — `fix(260908-vno): resolve localized proposals so ValidationDiff cards render`
(2 files changed, 209 insertions, 1 deletion)

## Base reset

**The reset fired.** The worktree came up based on `ce1dbe72f8c4378fb3af4fe353d431813cb18474`,
an ancestor of the required base — `git merge-base HEAD 229d61eb` returned `ce1dbe72`, i.e. HEAD
was *behind* the target, the known stale-base trap. `git reset --hard 229d61eb…` corrected it and
`git rev-parse HEAD` verified `229d61eb521d0a42c5a42b40589b31ae3555edc3` before any work began.

HEAD was on `worktree-agent-ad3616512ffb514ed` throughout (asserted before the reset and again
before the commit); no protected ref was ever touched.

## Pre-fix observed values (measured, not inferred)

Observed by running the real exports against a raw skill-shaped proposal
(`current`/`suggested`/`rationale` as `{nl, en}` objects) **before** the `IntakeForm.tsx` change:

| Call | Pre-fix observed |
| --- | --- |
| `getSimpleProposal(raw, "decision_or_goal")` | `null` |
| `isFieldChanged("decision_or_goal", "B-nl", raw)` | `false` |
| `sectionHasChange(section, {decision_or_goal:"B-nl"}, raw)` | `false` |

This is the full causal chain of the reported symptom: the guard at `ValidationDiff.tsx:37`
(`typeof p.suggested !== "string"`) rejects the localized object, so `getSimpleProposal` returns
`null` for every proposal, `isFieldChanged` short-circuits to `false`, `sectionHasChange` is
`false`, and no `DiffCard` is ever reached.

The probe file used to print these values was thrown away; the same three observations are pinned
**permanently** in the committed suite (`getSimpleProposal — raw skill output (the defect, pinned)`,
plus the `false` halves of the `isFieldChanged` and `sectionHasChange` blocks). Those cases are the
proof the guard really did reject the object — if they ever flip, the resolve-at-the-boundary
contract established here no longer holds.

## The change

`frontend/src/components/intake/IntakeForm.tsx` — exactly one added import and one changed
statement (the statement wraps to two physical lines under Prettier's 100-char `printWidth`):

```diff
 import { localizeSchema } from "@/lib/i18n/localizeSchema";
+import { resolveAnswerValue } from "@/lib/i18n/resolveAnswerValue";
```

```diff
-      if (parsed && typeof parsed === "object") setProposals(parsed as Proposals);
+      if (parsed && typeof parsed === "object")
+        setProposals(resolveAnswerValue(parsed, i18n.language) as Proposals);
```

`i18n` was already in scope (destructured at `IntakeForm.tsx:92`); no second import was added for it.

## The test file

`frontend/src/components/intake/ValidationDiff.test.ts` (new, 13 tests) exercises the real
`getSimpleProposal` / `isFieldChanged` / `sectionHasChange` exports on both shapes.

The fixture mirrors the actual contract in `backend/app/ai/prompts.py` ("=== JSON CONTRACT ==="),
which specifies `suggested` and `rationale` as `{nl, fr, en}` objects and `current` as a verbatim
plain-string quote. Both variants of `current` are covered — localized (as seen on the real data
this was reported against) and plain string (as the contract specifies) — because the model does
not always comply.

**Anti-vacuity, honoured:** no assertion anywhere is of the form `typeof x === "string"`. That
form passes on the broken code too, since `String({})` is itself a string. Every case pins exact
expected text, and `nl` / `en` are asserted separately against distinct literals so locale
selection cannot be satisfied by a hardcoded language. A `nl-BE` case pins the two-char slicing
behaviour delegated to `pick()`.

Case 5 (non-localized members survive) is covered three ways: an already-scalar `rationale` stays
byte-for-byte, `research_questions_refined[0].original_index` stays the **number** `0` (it indexes
into the answers array), and `dropped_questions[0].original` stays its verbatim quote — while the
localized member nested inside the same array element does resolve.

## Verification

| Gate | Result |
| --- | --- |
| `npx tsc --noEmit` | exit **0** |
| `npx vitest run` | **193 passed** / 13 files — 180 baseline + 13 new, zero regressions |
| Fence gate `git diff --exit-code HEAD -- ValidationDiff.tsx AIReviewPanel.tsx resolveAnswerValue.ts localizeSchema.ts` | exit **0** |
| `IntakeForm.tsx` diff shape | one added import + one changed statement |
| Post-commit deletion check | no deletions |
| Untracked files after commit | none |

The 180-test baseline was measured on the corrected base before any edit, so the 193 figure is a
true delta and not an absolute number carried in from the plan.

Dependencies installed with `npm ci` (857 packages), never `npm install`.

## Scope fences — all held, and machine-checked

`ValidationDiff.tsx`, `AIReviewPanel.tsx`, `resolveAnswerValue.ts` and `localizeSchema.ts` are
byte-identical to HEAD (fence gate exit 0). The `typeof p.suggested !== "string"` guard was
deliberately **not** loosened: it is correct once handed resolved data, and loosening it would put
locale logic in a third place. The write policy, the field locking (only `proposal_list` writable
in `reviewed`, D-23.2-05) and `pick()` were not touched. Frontend only — no backend, no migration,
no dependency changes.

## Deviations from plan

**1. [Rule 1 — formatting defect in my own new file] Prettier violations in `ValidationDiff.test.ts`**

Two `prettier/prettier` errors in the newly authored test file (an over-long `rationale` object
literal and an over-long `dropped_questions` entry). Fixed by hand — deliberately *not* via
`eslint --fix`, which `frontend/cloudbuild.yaml:49` explicitly warns against. The file now lints
clean at **0 problems**. No behaviour change; the 13 tests were re-run green afterwards, as were
tsc and the fence gate.

No other deviations. Rules 2, 3 and 4 did not fire.

## Known limitations and consequences — recorded, not fixed

**1. Mid-session language switch does not re-resolve loaded proposals.** The proposals effect
early-returns on `proposals !== null`, so the diff cards keep their load-time language until
reload. This is the same limitation already recorded for the admin route in `260908-m7j`. The
plan directed that the effect's dependency array not be changed, and it was not.

**2. One new `react-hooks/exhaustive-deps` warning** at `IntakeForm.tsx:162` — a direct and
unavoidable consequence of limitation 1: the effect now reads `i18n.language` while the dependency
array is intentionally unchanged. It is **severity 1 (warning), not an error**, and it flags
exactly the behaviour the plan says to preserve. Left unsuppressed to keep the diff at the
plan-mandated one changed line plus one import; the repo does have an established
`// eslint-disable-next-line react-hooks/exhaustive-deps` convention (5 existing uses, including
in sibling `AIReviewPanel.tsx:287`) if a future task wants to document the intent in-line.

Lint is **not** a CI gate on this repo — `frontend/cloudbuild.yaml:18-49` documents at length that
`eslint .` is red at HEAD and that only `npx tsc --noEmit` and `npx vitest run` gate the build.
Per-file lint measured against the pre-fix baseline rather than an absolute number, as instructed:

| File | Pre-fix | Post-fix | Delta |
| --- | --- | --- | --- |
| `IntakeForm.tsx` | 582 (572 prettier/CRLF, 6 no-explicit-any, 4 no-empty) | 585 (574 prettier/CRLF, 6, 4, **1 exhaustive-deps**) | +2 CRLF `Delete ␍` on the two physical lines of the changed statement, +1 exhaustive-deps |
| `ValidationDiff.test.ts` | n/a (new) | **0** | — |

## Out-of-scope defect found — NOT fixed, needs its own task

**The `research_questions` key mismatch is real and confirmed against the canonical template.**

`ValidationDiff.tsx:64` (`isFieldChanged`) and `ValidationDiff.tsx:211` (`ValidationDiffForField`)
both branch on `fieldKey === "research_questions"`. In the canonical backend template
`backend/app/data/pulse_intake_v1.json`, `research_questions` is a **section `id`** (line 216) —
it is **not** a field key. The list field inside that section has `"key": "questions"` (line 224).
The only two question-bearing field keys in the whole template are `questions` and
`extra_questions_proposed`.

Consequence: those two branches can never fire for any real field, so the **refined-questions**
diff cards do not render either — a second, independent instance of the same user-visible symptom
this task fixed for the five `SIMPLE_DIFF_KEYS`. Resolving the proposals payload (this task) does
**not** address it; the branch is unreachable regardless of locale.

It needs both sides checked together, which is why it was correctly fenced out here:

* `AIReviewPanel.tsx:252` exports `RESEARCH_QUESTIONS_FIELD_KEY = "research_questions"` and
  `AIReviewPanel.tsx:383` **writes** `{ field_key: "research_questions", value: patched }` — i.e.
  the admin side persists an answer under a key absent from the canonical template.
* `admin.pulse.intakes.$id.tsx:390` reads `initial["research_questions"]`.
* `research_questions_refined[].original_index` indexes into that array, so any key correction must
  keep the index base aligned with whichever array actually holds the questions.

Changing only the read side would break the admin write path, and changing only the write side
would orphan existing stored answers. Recommend a dedicated quick task that decides the canonical
key, checks both sides, and covers whether already-stored `research_questions` answers need
migrating or dual-reading.

## Self-Check: PASSED

* `frontend/src/components/intake/ValidationDiff.test.ts` — FOUND
* `frontend/src/components/intake/IntakeForm.tsx` — FOUND (modified)
* Commit `7ffdb46` — FOUND in `git log`
* Fence files — verified byte-identical to HEAD
