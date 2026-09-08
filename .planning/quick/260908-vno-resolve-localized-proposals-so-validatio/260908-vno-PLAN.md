---
quick_id: 260908-vno
status: ready
wave: 1
tasks: 1
---

# 260908-vno — Resolve localized proposals so the client's ValidationDiff cards render

**Defect:** DEF-23.2-16b — the second consumer of the same root cause fixed in `260908-m7j`.

Reported live: after the operator refines an intake and sends it back, the client sees their
answers (now rendering correctly after `260908-m7j`) but **no indication of what Nestor changed**.
Every field is locked except `extra_questions_proposed`.

The locking is correct and is NOT in scope — in `reviewed` only `proposal_list` is writable
(D-23.2-05), verified server-side and in the browser. The defect is that the diff cards which are
supposed to *show* the refinements never render.

## Root cause — measured, do not re-derive

`frontend/src/components/intake/ValidationDiff.tsx:37`:

```ts
if (!p || typeof p !== "object" || typeof p.suggested !== "string") return null;
```

The intake skill emits every string it authors as a localized `{nl, fr, en}` object, so
`p.suggested` is an **object**, the guard's `typeof … !== "string"` is true, and
`getSimpleProposal` returns `null` for **every** proposal. `isFieldChanged` then returns `false`,
`sectionHasChange` returns `false`, and no `DiffCard` is ever rendered.

Affected keys are exactly `SIMPLE_DIFF_KEYS` (`ValidationDiff.tsx`):
`decision_or_goal`, `audience_description`, `company_intro`, `output_size`, `output_form`.

This is the identical root cause as `260908-m7j` — the skill moved to localized objects and its
consumers were not updated. That task fixed the three **render** boundaries. This is the **diff**
boundary, which fails silently rather than visibly.

## The fix — one line plus one import

`frontend/src/components/intake/IntakeForm.tsx:155` currently reads:

```ts
if (parsed && typeof parsed === "object") setProposals(parsed as Proposals);
```

Resolve the proposals payload as it is loaded, so `ValidationDiff` receives the strings its type
guards already expect:

```ts
if (parsed && typeof parsed === "object")
  setProposals(resolveAnswerValue(parsed, i18n.language) as Proposals);
```

* Import `resolveAnswerValue` from `@/lib/i18n/resolveAnswerValue` (shipped in `260908-m7j`).
* `i18n` is ALREADY in scope — destructured at `IntakeForm.tsx:92`
  (`const { t, i18n } = useTranslation("intake")`). Do not add another import for it.
* `resolveAnswerValue` only ever rewrites localized-text objects, so `current`, `suggested` and
  `rationale` collapse to strings while every other member keeps its shape. This is why resolving
  the WHOLE proposals object is safe rather than picking members by name.

## Scope fences — hard

* **Do NOT edit `ValidationDiff.tsx`.** Its string guards are correct once it is handed resolved
  data. Loosening them would duplicate locale logic into a third place.
* **Do NOT edit `resolveAnswerValue.ts` or `localizeSchema.ts`.** `pick()` stays untouched.
* **Do NOT touch `AIReviewPanel.tsx`** — the admin side already resolves for display via
  `pick(suggested, i18n.language)` and works. Its write path stays as-is.
* **Do NOT change the write policy or the field locking.** Only `proposal_list` writable in
  `reviewed` is correct behaviour.
* **Do NOT attempt to fix the `research_questions` key mismatch.** `isFieldChanged` and
  `ValidationDiffForField` branch on `fieldKey === "research_questions"`, which is not one of the 29
  canonical field keys (the canonical list field is `questions`). That is a REAL second defect, but
  `research_questions_refined[].original_index` indexes into that array and `AIReviewPanel` also
  writes `research_questions`, so it needs both sides checked. Out of scope — note it in the SUMMARY.
* Frontend only. No backend, no migration, no dependency changes.
* `npm ci`, never `npm install`.

## Task 1 — resolve proposals at the load boundary

**Files:** `frontend/src/components/intake/IntakeForm.tsx`,
`frontend/src/components/intake/ValidationDiff.test.ts` (new)

**Action:** apply the one-line change and its import. Then add a focused test file proving the
behaviour end-to-end through the real `getSimpleProposal` / `isFieldChanged` exports.

**Required test cases** — build a fixture shaped like the real skill output, i.e. a proposal whose
`current` and `suggested` are `{nl, fr, en}` objects:

1. **RED evidence, permanently in the suite:** `getSimpleProposal(rawProposals, "decision_or_goal")`
   returns `null`. This pins the broken shape and is the proof the guard really did reject it.
2. `getSimpleProposal(resolveAnswerValue(rawProposals, "nl"), "decision_or_goal")` returns a
   non-null object whose `suggested` is **the exact Dutch string** from the fixture.
3. Same for `"en"`, returning the exact English string — proving locale selection is honoured, not
   hardcoded.
4. `isFieldChanged("decision_or_goal", <the applied answer>, resolved)` is `true`, and `false`
   against `rawProposals` — the assertion that maps directly to the reported symptom.
5. A non-localized member of the proposals object (e.g. an array, or `rationale` already a string)
   survives resolution unchanged.

**Anti-vacuity, enforced:**

* Do NOT assert `typeof x === "string"` anywhere — that passes on the broken code because
  `String({})` is a string. Assert exact expected text.
* Case 1 and the `false` half of case 4 MUST be observed failing-shape before the fix is applied;
  record the observed values in the SUMMARY.

**Verify:**

* `npx tsc --noEmit` exits 0
* `npx vitest run` — new tests pass and the existing **180** still pass (expect 180 + new count)
* `git diff --exit-code HEAD -- frontend/src/components/intake/ValidationDiff.tsx frontend/src/components/intake/AIReviewPanel.tsx frontend/src/lib/i18n/resolveAnswerValue.ts frontend/src/lib/i18n/localizeSchema.ts` exits 0 (the fences are machine-checked, not trusted)
* The diff in `IntakeForm.tsx` is exactly one changed line plus one added import line

**Done when:** all four verify steps pass and the SUMMARY records the pre-fix observed values, the
post-fix counts, and the out-of-scope `research_questions` defect.

## Known limitation to record, not fix

The proposals effect early-returns on `proposals !== null`, so a mid-session language switch will
not re-resolve the already-loaded proposals — the cards keep the load-time language until reload.
Consistent with the same limitation recorded for the admin route in `260908-m7j`. Note it; do not
change the effect's dependency array.
