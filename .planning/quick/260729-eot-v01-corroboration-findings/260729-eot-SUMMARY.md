---
id: 260729-eot
slug: v01-corroboration-findings
date: 2026-07-29
status: complete
---

# Quick Task 260729-eot — SUMMARY

Wrote up the V-01 run (`7dcf51d5`, 2026-07-28) and the corroboration failure it exposed.

## Delivered

- `docs/tribunal-run-reports/run-20260728-7dcf51d5-V01-FINDINGS.md` — the forensics document,
  eight defects D-V01-1 … D-V01-8 with evidence, plus the proposed fix and its invariants.
- `docs/tribunal-run-reports/V-01-COMPARISON.md` — stale **PARKED** status corrected, run identity
  filled, findings document linked.

## The headline

The run completed cleanly at **$53.48 / 65.1 min / 396 claims**, and its central premise did not
operate: `verification_summary.both = 0`, every claim found by exactly one provider.

**Two distinct causes, and the second is the harder one.**

**D-V01-1 — arithmetically impossible.** The merge key is the claim text, lowercased and stripped of
punctuation. Claims merge only if character-identical. Measured: **396 claims → 396 distinct keys →
0 collisions.** `both: 0` is the only value that counter can take. A missed pair is recorded
verbatim: openai and claude both stating the MTS-K five-minute reporting rule, in different words.

**D-V01-2 — thin genuine overlap.** Fixing the key alone does not produce a corroborated report.
Fuzzy token-overlap over all 78,210 pairs finds **0** cross-provider pairs at ≥0.5 and only **37 of
396 claims** with any cross-provider partner even at a very loose 0.2 — while each provider repeats
*itself* more often than it agrees with another (56 vs 14 near-duplicates at 0.2). The engine is
corroborating at the wrong granularity: agreement lives at the level of the answer to a
sub-question, not an individual extracted sentence.

## Also recorded

- **D-V01-3** `own` researcher reports in English while the other three report in Dutch — 17 claims
  that cannot match anything under any matcher.
- **D-V01-4** a contradiction shipped unflagged: gemini "≈90 locaties" vs claude "zeven locaties"
  for the same De Haan/Tony's rollout. 13× apart, both output as independent facts.
- **D-V01-5** `claim` records only `facet` (the parent client question), not the sub-question or
  `corroboration_key` — so it is currently impossible to tell whether two claims answered the same
  sub-question. **Prerequisite for any clustering fix.** A one-character typo (`en/of` vs `en/or`)
  also split one client question into two facets, one holding 1 claim.
- **D-V01-6** stage logging is inert in production. `pipeline.py` uses stdlib `logging`, which has no
  handler in the worker, so Python's `lastResort` handler serves it at WARNING+ only. Every
  `stage_enter`/`stage_exit`/`run_stages_complete` line is discarded. **The DEPLOY-RUNBOOK instructs
  the operator to diagnose the first live run using exactly those lines — that instruction is
  unfollowable as written.**
- **D-V01-7** ~20 `run_event` rows dropped (`KeyError`/`TypeError` in `emit_safe`); 15.3's feed is
  missing agent-completion lines for this run.
- **D-V01-8** `gpt-5.6-sol` is absent from the cost table → 5 NULL-cost calls, `cost_pending` still
  true. **$53.48 is a floor.**

## The fix, as specified

IDs to the model, IDs back — claim text and sources never leave the database. The change is a
**key function swap**, not a new merge stage: the existing merge already unions `source_urls`, grades
each URL by its supplying provider, and takes the cautious `certainty`, so provenance needs no new
code and `found_by` is already `ARRAY(Text)` (no migration). Enforced partition invariant handles
silent loss: omitted id → singleton, invented → discard, duplicated → reject the response, emitted
text → ignore. Contradictions annotate rather than merge. Sonnet not Haiku, grouped not pairwise,
~15,800 tokens, ~$0.15–0.20.

## Deliberately not done

Fixing any defect; filling the V-01 comparison table (needs the frozen baseline read side by side —
filling it from one side would defeat its purpose).

## Five open questions carried in the document

Answer-level vs fact-level corroboration · the 396/426/293 reconciliation · `gate_errors: 153`
unsurfaced · 175 claims with `null` certainty · `brief_conflicts` fired for the first time and still
reaches no output.
