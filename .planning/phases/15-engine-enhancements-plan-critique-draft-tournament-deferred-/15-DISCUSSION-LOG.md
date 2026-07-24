# Phase 15: Research Engine Redesign - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-24
**Phase:** 15-Research Engine Redesign (was: Engine Enhancements)
**Areas discussed:** Phase scope & old enhancements, Build order & first deliverable, Proving the new engine, Failure & resume policy

Preceded the same day by an area-by-area operator brainstorm producing
`.planning/RESEARCH-ENGINE-DECISIONS.md` (D1–D15, R1–R7, C1) and the STAKEHOLDER-NOTES
verification package — this discussion built on those, not from scratch.

---

## Phase scope & old enhancements

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — 15 = the redesign | Phase becomes "Research Engine Redesign"; roadmap/requirements rewritten from decision files | ✓ |
| No — keep 15 small | Old plan-critique + draft-tournament scope; redesign to a new milestone | |
| 15 = redesign core only | Engine changes in 15, surfaces split into 15.1 | |

**User's choice:** Yes — Phase 15 = the full redesign.

| Option | Description | Selected |
|--------|-------------|----------|
| Drop it | Draft tournament (ENGINE-06) removed; tournament lives at question level | ✓ |
| Keep it in Phase 15 | 2–3 competing drafts, pairwise judge | |
| Backlog | Re-evaluate after redesign ships | |

**User's choice:** Drop ENGINE-06.
**Notes:** Recorded as "first candidate to revisit if report quality disappoints."

---

## Build order & first deliverable

| Option | Description | Selected |
|--------|-------------|----------|
| Surfaces first | Verification report + feed + cost-truth on today's engine, from recorded data | ✓ |
| Verification gates first | Fix the 953→~150 waste first | |
| Engine core first | Workshop/researchers/merge first | |

**User's choice:** Surfaces first.

| Option | Description | Selected |
|--------|-------------|----------|
| Split into 3 phases | 15 surfaces / 15.1 gates / 15.2 engine core, each own verification+UAT | ✓ |
| One phase, ordered waves | Everything in Phase 15 | |

**User's choice:** Split into 3 phases.

| Option | Description | Selected |
|--------|-------------|----------|
| Surfaces now, core after 19 | 15 now, 19, then 15.1/15.2, then 20 | |
| Keep strict order: 19 first | Literal reading of the 07-22 hold | |
| Also pull 20's chores earlier | Max parallelism | |
| (free text) | "15 first all of it, the 19 last" | ✓ |

**User's choice (free text):** ALL of Phase 15 first, Phase 19 last. Confirmed explicitly:
**15 → 15.1 → 15.2 → 19 → 20**, superseding the 2026-07-22 "engine work after 19" decision.
**Notes:** Rationale accepted: Q&A chat (19) then indexes the NEW engine's output from day one.

| Option | Description | Selected |
|--------|-------------|----------|
| Pull embeddings forward | 15.2 sets up pgvector/Voyage wiring itself | |
| LLM-based clustering | LLM groups fact lists directly; no new machinery | ✓ |
| Builder decides | Leave to planning | |

**User's choice:** LLM-based clustering (chosen after asking what Phase 19 has to do with
claims — clarified that only the embedding *machinery* linked them).

---

## Proving the new engine

| Option | Description | Selected |
|--------|-------------|----------|
| A/B on the same intake | Old + new engine side by side via comparison harness | |
| New engine vs recorded baseline | Live new-engine run compared against recorded 4cbb5311 | ✓ |
| Tests only, then straight to live | Fixture replay as sole proof | |

**User's choice:** New engine vs recorded baseline (cheaper; harness stays available).

| Option | Description | Selected |
|--------|-------------|----------|
| Checklist + your sign-off | Hard checklist from decision files AND operator reads/accepts | ✓ |
| Your judgment only | Human gate only | |
| Checklist only | No human gate | |

**User's choice:** Checklist + operator sign-off.

| Option | Description | Selected |
|--------|-------------|----------|
| Flag for a few runs, then remove | Old path selectable as emergency fallback for 2–3 runs | |
| Remove immediately on acceptance | Old path deleted in the same phase | ✓ |
| Keep both indefinitely | Permanent dual maintenance | |

**User's choice:** Remove immediately on acceptance (consistent with big-bang cutover philosophy).

---

## Failure & resume policy

| Option | Description | Selected |
|--------|-------------|----------|
| Superadmin click | Park → email + Resume button; spend never restarts unattended | ✓ |
| Fully automatic | Auto-continue when wall lifts | |
| Auto with a time window | Hybrid | |

**User's choice:** Superadmin click (resolves the R4 open sub-decision).

| Option | Description | Selected |
|--------|-------------|----------|
| 3 full restarts; resumes free | Checkpoint-resumes don't count toward the limit | ✓ |
| Every retry counts | Any resume increments | |
| Drop the limit | Remove the cap entirely | |

**User's choice:** 3 full restarts; checkpoint-resumes free (amends Phase 16 D-04).

| Option | Description | Selected |
|--------|-------------|----------|
| Same as today | Park/fail emails to triggering superadmin, short body + link | ✓ |
| Triggerer + admin address | Copy NESTOR_ADMIN_EMAIL | |
| Feed only, no email | No mail | |

**User's choice:** Same as today (16-D-10/D-11 extended to the parked state).

---

## Claude's Discretion

- Feed/trace data model under the frozen-audit-payload + dynamic-stage-list constraints
- Which recorded data powers which Phase-15 surface; drill-down rendering
- V-02 checklist derivation; workshop internals (counts, pairing, evolve step)
- Test intake selection for the 15.2 validation run
- Retry/backoff/breaker/checkpoint parameters (R1–R3) per cited best practices

## Deferred Ideas

- Draft tournament (ENGINE-06) — revisit if report quality disappoints post-redesign
- Cross-provider corroboration filter — after Phase 19 embeddings
- Embedding-based clustering upgrade for the merge step
- Auto-resume (time-windowed) for parked runs
- Live A/B old-vs-new comparison runs
