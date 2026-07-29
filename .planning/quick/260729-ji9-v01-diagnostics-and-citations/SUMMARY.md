---
id: 260729-ji9
slug: v01-diagnostics-and-citations
date: 2026-07-29
status: complete
---

# Summary

Steps 0 and 1 of the post-V-01 fix sequence, plus the engine redesign spec that came out of them.

## Task 1 — citations preserved ✅

`docs/tribunal-run-reports/run-20260728-7dcf51d5-CITATIONS.tsv` (commit `7c81e29`).

225 unique gemini grounding redirects → publisher URLs, with occurrence counts. **Verified complete
against `research.json`, not merely non-empty**: 642 instances / 225 unique across the 16 reports,
**0 missing, 0 unresolved, 0 extraneous**, 129 publisher domains. 7 rows re-resolved live and matched
the stored value **exactly**. The redirects expire ~late Aug 2026; this closes the time-limited risk.

## Task 2 — diagnostic 1a: FORMAT DRIFT, not truncation ✅

Truncation is **impossible**, on three independent grounds:

1. Gemini's two **longest** reports (88,428 / 88,135 chars) both carry complete `FACTS` blocks; the two
   failures are 40,488 and 57,660 — ranks 5 and 3 of 5. On *cleaned* length they are the two shortest.
2. The block sits ~75% into the output with **9,129 / 15,208 / 13,725 chars of bibliography after it**.
   A truncation loses the tail, not a middle section.
3. Both failing reports end with a **complete numbered bibliography** (last entries 28 and 63) — the
   same ending shape as the successes.

`research_division.py:348` already records gemini honouring the block on **0 of 8** reports before
15.2-23's lead-in; V-01 got 3 of 5. The lead-in improved compliance; it did not make it deterministic.

**⇒ Fix is retry-on-missing-block. ⇒ THE Q4 GROUPING GATE IS CLEARED.**

Bonus: gemini's fact-list failures are **three** distinct format deviations, not one — block absent
(idx 12/16), a literal `STATEMENT` column shifting every field (idx 8, all 4 lines rejected), and
`[cite: N]` in the `SOURCE_URL` column (idx 4, facts kept, **sources lost**).

## Task 3 — diagnostic 1b: a literal `<TAB>` destroyed 278 claims ✅

All four distiller calls recovered from the audit bucket. Every one succeeded (`finish_reason: STOP`,
16k–31k output tokens). The two coffee calls returned **278 well-formed, three-column,
evidence-bearing claim lines** — and `_parse_distiller_response` (`steps.py:1281`) dropped every one,
because gemini wrote the literal five-character string `<TAB>` instead of U+0009.

**The prompt itself uses `<TAB>` as a placeholder describing the separator** (`steps.py:1237,1256`).
Two of four calls in the same batch at temperature 0.0 emitted real tabs; two copied the placeholder.
A coin-flip in the extraction contract. The only log line for the drop is `log.debug` — discarded in
production (D-V01-6).

What was lost: Circle K 44, LUKOIL 27, Barista 24, Costa 18, Shell Café 10, Illy 10, Lattiz 7,
Douwe Egberts 6, deli2go 3, Perszè 2. **This is the true origin of the report's false
*"geen volledig beeld"* statement** — not an extraction limit.

Also: the `produced ZERO claims` warning is **untrustworthy** — it fired for convenience too, a false
alarm, because `steps.py:1578` iterates every focus area in the brief regardless of whether it was in
the call's inputs.

## Task 4 — recorded ✅

- `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md` — full evidence chain (`513ff59`)
- `run-20260728-7dcf51d5-V01-FINDINGS.md` — D-V01-9 root cause corrected, 89% funnel figure restated,
  swapped idx 4 / idx 8 attribution fixed
- Memory: `engine-fix-sequence-post-v01`, `v01-corroboration-never-operated`,
  `engine-design-open-questions` all updated

## Beyond the plan — the redesign spec

The diagnostics changed the design, so the session continued into design work with the operator.
**`.planning/ENGINE-REDESIGN-SPEC.md`** carries the whole thing: 9 decisions (D-R1…D-R9), five waves
with exact file/function targets, invariants, tests, and a measured cost baseline.

Operator decisions taken: LLM grouping into ≤5 groups × all providers; drop `own`; a creative
tournament loop with a **10-round cap**; a **discovery bracket** for evidence-anchored questions the
client did not ask; keep the tournament (**Q1 resolved**) *because* discovery finally gives it
something real to rank.

## Verification

| Claim | How checked |
|---|---|
| Citation set complete | recomputed unique redirects from `research.json`; 0 missing / 0 unresolved / 0 extra |
| Citations genuine | 7 live `HEAD` re-resolutions, exact string match against stored value |
| Truncation ruled out | raw char lengths + `FACTS_END` offsets + tail inspection, all 5 gemini reports |
| 278 claims recoverable | re-split both coffee responses on `<TAB>`; 278/278 pass the ≥10-char filter, all with EVIDENCE |
| No call failed | `finish_reason` + output-token counts on all four distiller calls; no `chunk … failed` line in Cloud Logging |
| Cost baseline | summed `usage` across all 14 workshop audit blobs; priced sonnet at $3/$15 per MTok |

## Lessons

- **The audit bucket answers what the logs cannot.**
  `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/<run_id>/` stores the **full request and
  response** of every LLM call. Both diagnostics were settled from it in minutes.
- **"Returned output but kept nothing" must be a WARNING.** It is the failure mode that put a false
  statement in a client report, and it was invisible.
- **Do not describe a control character with a token the model can copy.**
