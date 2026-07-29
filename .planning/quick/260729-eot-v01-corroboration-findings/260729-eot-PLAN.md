---
id: 260729-eot
slug: v01-corroboration-findings
date: 2026-07-29
status: planned
---

# Quick Task 260729-eot — Write up the V-01 run findings, centred on the corroboration failure

## Why

V-01 ran on 2026-07-28 (`7dcf51d5`) and completed cleanly at $53.48. Its most important result is
invisible in its own output: **cross-stream corroboration did not operate, and structurally could
not have.** `verification_summary.both = 0`, and all 396 claims carry exactly one provider in
`found_by`.

Investigation established this is not a research outcome but an implementation consequence, plus a
second, harder problem underneath it. Both, and five smaller defects found alongside, currently
exist only in a chat transcript. They need to survive into planning.

## Tasks

### Task 1 — Write the V-01 forensics document

Files: `docs/tribunal-run-reports/run-20260728-7dcf51d5-V01-FINDINGS.md`

Follow the existing `run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md` precedent for naming and shape.

Record, with the measured numbers rather than prose summaries:
- run identity, outputs, claims/verification/cost cuts
- the tournament result, including that 9 of 10 winners are critic-flagged `WEAK` with `killed: 0`
- the dispatch table proving corroboration **was** requested (top 3 sub-questions × 4 providers)
- deep-research calls actually issued per provider
- eight defects, D-V01-1 … D-V01-8, each with its evidence

Evidence that must appear verbatim, because it is the proof and not the conclusion:
- the `norm =` merge-key expression from `synthesis/steps.py`
- 396 claims → 396 distinct keys → 0 collisions
- the MTS-K "binnen vijf minuten" pair (openai vs claude) the exact match missed
- the full Jaccard threshold table (0.5 → 0.2), showing only 37 of 396 claims have any
  cross-provider partner even at 0.2
- the De Haan 90-vs-7 contradiction that shipped unflagged

Verify: every number in the document traces to a query or log line actually run, not to memory.

Done: a reader who was not in the session can reach the same conclusions from the evidence.

### Task 2 — Record the proposed fix

Files: same document, "Proposed fix" section.

The design decisions that must be captured, because they are the non-obvious part:
- **IDs to the model, IDs back** — claim text and sources never leave the database
- the change is a **key function**, not a new merge stage: swap the `norm` expression, and the
  existing source-union / per-URL grading / cautious-certainty machinery keeps working unchanged
- the **partition invariant** and its four failure handlings (omitted → singleton, invented →
  discard, duplicated → reject response, emitted text → ignore) — this is the silent-loss guard
- contradictions **must not merge**
- Sonnet not Haiku, with the reason (mislabelling a contradiction is worse than today's behaviour)
- not pairwise (78,210 pairs)
- keep the deterministic merge; add the LLM pass alongside it — audit trail has a 2026-08-02 deadline
- sizing: ~15,800 tokens, ~$0.15–0.20

Verify: a reader can implement it without re-deriving the guards.

Done: the fix is specified to the level of its invariants, not just its intent.

### Task 3 — Make it discoverable from the V-01 record

Files: `docs/tribunal-run-reports/V-01-COMPARISON.md`

That file still says **PARKED — awaiting the Anthropic monthly cap reset on 2026-08-01**, which is
now false: the run went out on the burner key. Correct the status, fill the run-identity rows that
are known, and point to the findings document.

Do **not** fill the comparison table itself — that needs the frozen baseline read side by side, and
inventing it from one side would defeat the document's purpose.

Verify: the stale PARKED claim is gone and the findings doc is linked.

Done: someone opening V-01-COMPARISON is sent to the findings before drawing conclusions.

## Out of scope

- **Fixing** any of the eight defects. This task records them.
- Filling the V-01 comparison table (needs the baseline read).
- The five standing deploy debts — unchanged, recorded elsewhere.
