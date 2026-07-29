# CONTINUE HERE — session handoff 2026-07-29 (evening)

Supersedes the earlier 2026-07-29 handoff. The deploy is complete; V-01 is analysed; **both gating
diagnostics are answered and the engine redesign is fully specified.** Tree is clean, nothing in flight.

## Start here

**`.planning/ENGINE-REDESIGN-SPEC.md`** — the whole plan: 9 decisions, 5 waves, exact file/function
targets, invariants, tests, cost baseline. It is written to be executed without re-deriving anything.

Background, in order: `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md` (the two root
causes) → `run-20260728-7dcf51d5-V01-FINDINGS.md` (the run's forensics, with corrections applied).

## What changed today, in one paragraph

The two diagnostics that gated everything were answered, and **both overturned the hypothesis they were
testing**. The missing `FACTS` block is **format drift, not truncation** — which clears the Q4 grouping
gate. And the distiller never failed: it returned **278 well-formed coffee claims** that the parser
threw away because gemini wrote the literal string `<TAB>` instead of a tab character, while the prompt
itself uses `<TAB>` as a placeholder describing the separator. That single defect is the true origin of
the client report's false *"geen volledig beeld"* statement. V-01's 225 citations are preserved in the
repo before their ~late-Aug expiry. The session then went on to design the engine fix with the operator.

## Next action — Wave 1, and ship it alone

**`/gsd-plan-phase`** off `.planning/ENGINE-REDESIGN-SPEC.md` § Wave 1 (extraction repair).

Wave 1 is: the `<TAB>` parser + prompt fix · make "returned lines, kept zero claims" a **WARNING** ·
scope the untrustworthy ZERO-claims warning to in-scope facets · retry covering **all three** gemini
format deviations · resolve redirects at ingest · `gpt-5.6-sol` cost-table entry.

**Ship Wave 1 by itself and let one run measure it.** Everything downstream is judged through the
extraction funnel; shipping the redesign on top of a broken meter would attribute the parser bug to the
redesign. Wave 2 (claim attribution) is a **hard prerequisite** for Wave 3 (grouping) — not optional.

**Wave 1 has a real regression fixture:** replay V-01's two coffee audit blobs through the new parser
and assert **278** claims recovered. Exact blob IDs and the `gcloud` command are in the spec § 8.

## Decisions the operator took (do not relitigate)

| | |
|---|---|
| **Dispatch** | An LLM groups winners into **≤5 groups**; each group → **all providers**. `own` is dropped (2 of 4 angles failed, English in a Dutch run, 2 unique URLs). 5 × 3 = **15 calls** vs V-01's 19. |
| **Tournament** | **Keep it and make it real** (Q1 resolved) — generative evolve, judges give reasons, meta-review, **10-round cap** with saturation exit + spend ceiling. |
| **Discovery** | A **discovery bracket** may raise questions the client did not ask, each carrying the quote and source that provoked it. **No source, no slot.** It can never borrow from the mandate. |

**Why invention is allowed:** D4's `enforce_scope_guard` is a **coverage floor** (winners' parents ⊇
client questions), not a ceiling. The "never invent" half was only ever two prompt sentences — and the
same file says a prompt sentence is not a control.

## Standing cautions

- **Judge the engine from the delivered report** (`output` row, `format='markdown'`) — not the claim
  table, not the logs. Four findings had to be withdrawn or corrected because they assumed a missing
  capability that was working.
- **The verification stage works. Do not touch it.**
- **The audit bucket is how you answer what the logs cannot:**
  `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/<run_id>/` — full request **and response** of
  every LLM call. Both diagnostics were settled from it.
- **Claim clustering for corroboration goes LAST**, and expect modest gains: only 37/396 claims have any
  cross-provider partner at Jaccard 0.2; shared-source overlap is 2.9%. Nobody should "fix" corroboration
  by swapping the matcher and declaring victory.

## Also still owed

Operator's no-engine-behaviour-change attestation (the D-03 gate — a person must write it), 15.3 plan
09's two operator checkpoints, the D-L elapsed clock check, and the five standing deploy debts — headed
by **rotating `Nestor_Claude_Temp`**, which transited a chat in plaintext on 2026-07-27 and is still
live on both Tribunal services. Art. 12 audit-trail deadline: **2026-08-02**.
