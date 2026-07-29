# V-01 — the phase-15.2 live run, against the recorded 4cbb5311 baseline

**Status: THE V-01 RUN HAS BEEN EXECUTED — 2026-07-28, run `7dcf51d5-1153-4374-b444-c25d17eeea01`.**
(The park is lifted: the run went out on the `Nestor_Claude_Temp` burner key, so the 2026-08-01
monthly-cap reset was not a blocker.)

> **The comparison table below is still UNFILLED.** The run's measured numbers, and the defects it
> surfaced, are written up in
> [`run-20260728-7dcf51d5-V01-FINDINGS.md`](run-20260728-7dcf51d5-V01-FINDINGS.md) — **read that
> first.** It carries the headline result, which is not visible in the run's own output:
> **cross-stream corroboration did not operate at all, and could not have.** `verification_summary.both`
> is `0` because the merge key is exact-string equality, so 396 claims produced 396 distinct keys and
> zero merges. Four providers were paid to answer the same three questions and no agreement between
> them was recorded.
>
> Filling the table below is still owed. Do it from the findings document, not from memory.

This is the comparison document for **V-01**: ONE live run of the redesigned engine, read side by
side with the recorded baseline at
[`docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md`](run-20260722-4cbb5311/REPORT.md).

The baseline column is **pre-filled and frozen** — it is a recorded run, not a re-run. The old
engine is never executed again; `run-20260722-4cbb5311/{REPORT.md,GROUPS.md,index.json}` is the
whole of the comparison's left-hand side.

**There is no A/B double-run.** The `comparison_id` harness stays available and unused. V-01 spends
exactly one capped run.

The checklist this document feeds is
`.planning/phases/15.2-research-engine-redesign-engine-core-inserted-2026-07-24/15.2-UAT.md`.

---

## Run identity

| | Baseline | New run (V-01) |
|---|---|---|
| `research_run_id` | `4cbb5311-9f5f-4504-84bb-b0dda2aedf48` | TBD — not captured |
| Tribunal `run_id` | `9c84e5a9-…` | **`7dcf51d5-1153-4374-b444-c25d17eeea01`** |
| Intake id | `e08620c5` | TBD — not captured |
| Date | 2026-07-22 | **2026-07-28** |
| Subject | LUKOIL BeNeLux — dynamic pricing, coffee, Germany-entry 2027 | **LUKOIL BeNeLux — same brief domain** |
| Engine | pre-15.2 (old path) | **15.2 + 15.3, worker image `20260728-094409`** |

## The comparison

| Metric | Baseline (`run-20260722-4cbb5311`) | New run (V-01) | Reading |
|---|---|---|---|
| Terminal status / outcome | `completed` (green) | TBD (V-01) | `completed_degraded` is **not** a regression if every reason is named — D-12 honesty beats a flattering green |
| Duration | ~48 min | TBD (V-01) | The workshop adds stages; a longer run is acceptable, an unexplained one is not |
| Audited calls | 228 | TBD (V-01) | |
| Deep-research calls | 6 | TBD (V-01) | |
| Distiller calls | 8 | TBD (V-01) | D-15: `claim_distiller` survives V-03 |
| Unique claims reaching the gates | 1,162 | TBD (V-01) | The recorded 1,162 are what 15.2-17's D-04 replay drives through the gates |
| Grouping calls | 30 | TBD (V-01) | |
| Groups formed | 176 (92% singletons) | TBD (V-01) | 92% singletons is the number the merge-before-gate reordering exists to improve |
| Group-skeptic sessions | 176 | TBD (V-01) | |
| **Skeptic parse crashes** (`'str' object has no attribute 'get'`) | **24** | TBD (V-01) | **SC5 pass condition is ZERO.** The F-01 fix shipped 2026-07-23 and has never run live |
| **Hard-400 cap errors** | **776 in 55 s** | TBD (V-01) | R1/R2: a cap-400 must trip the breaker on first occurrence and never be retried |
| **Unresolved `[cite:]` markers stripped** | **28** | TBD (V-01) | D-05 emission-rate metric — **record the number**, and state it in words in the report |
| Real Anthropic-side cost | **≈ $43-45** | TBD (V-01) | |
| Displayed cost | ~€5 | TBD (V-01) | The P1 cost-truth defect. C1 requires the displayed figure to be the real one, itemised |
| SerpApi searches × unit price | n/a (no fourth stream) | TBD (V-01) | Unit price read live from `/account.json`; a free tier reads `$0.00000`, never blank |
| Gate funnel reconciles | n/a (predates the gates) | TBD (V-01) | One claim → exactly one bucket, `checked_incidentally` subtracted from bucket 2 |
| `verify_chain` | green | TBD (V-01) | A RED chain is a STOP — no sign-off (EU AI Act Art. 12) |

## The four shipped contradictions

The baseline shipped these four contradictory pairs **unreconciled** (`GROUPS.md`). V-02 #8 asks
only that **at least one** pair collided in a **single** skeptic session — that is the observable
effect of the merge-before-gate reordering. Reconciliation quality is a judgement call for the
operator's read, not a mechanical pass condition.

| Contradiction | Baseline outcome | New run (V-01) |
|---|---|---|
| Aral market share 16% vs 21% | shipped unreconciled | TBD (V-01) |
| LUKOIL NL 46 vs ~70/75 stations | shipped unreconciled | TBD (V-01) |
| Zeeland — Carlyle vs TotalEnergies | shipped unreconciled | TBD (V-01) |
| Gunvor vs Carlyle | shipped unreconciled | TBD (V-01) |

## Operator's read

To be written at sign-off, after reading the new report beside the baseline. Not a metric — the
question is whether the report is **better research**, which no number in the table above answers.

TBD (V-01)
