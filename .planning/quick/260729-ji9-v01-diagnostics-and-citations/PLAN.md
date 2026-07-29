---
id: 260729-ji9
slug: v01-diagnostics-and-citations
date: 2026-07-29
status: in-progress
---

# Preserve V-01 citations + answer the two gating diagnostics

Steps 0 and 1 of the agreed post-V-01 fix sequence (`.planning/CONTINUE-HERE.md`,
memory `engine-fix-sequence-post-v01`). Step 1's two diagnostics **gate** the Q1+Q4
decision and the phase plan, because a truncation cause and a tagging cause need
opposite fixes.

## Task 1 — preserve the citations (TIME-LIMITED)

Gemini's grounding redirects expire ~30 days from the 2026-07-28 run. Resolve-and-store
the publisher URLs or V-01's whole evidence base becomes unverifiable.

- Source: the 225-row resolution captured 2026-07-29 in the prior session's scratchpad.
- Prove the set is COMPLETE against `research.json` (not merely non-empty): every unique
  redirect in the corpus present, none unresolved, none extraneous.
- Spot re-resolve a sample live and require exact equality with the stored value.
- Commit as `docs/tribunal-run-reports/run-20260728-7dcf51d5-CITATIONS.tsv`.

## Task 2 — diagnostic 1a: why gemini omitted the FACTS block

Decide between truncation (→ chunked extraction, and Q4 grouping MUST NOT ship first)
and format drift (→ retry-on-missing-block, Q4 safe now).

## Task 3 — diagnostic 1b: why the distiller returned zero coffee claims

Determine whether it is facet-label mismatch (→ pass `corroboration_key`), a failed call,
or something else.

## Task 4 — record the results

Write a DIAGNOSTICS doc, correct the findings doc where the new evidence overturns it,
and update the memory notes so the next session plans against the true cause.

## Verification

- Citation artifact: row count == unique redirects in the corpus; 0 missing/unresolved/extra;
  live spot-check matches stored values exactly.
- Each diagnostic states a cause, the evidence that establishes it, and the evidence that
  RULES OUT the competing hypothesis.
