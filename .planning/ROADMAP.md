# Roadmap: Nestor Intake (GCP Re-platform)

## Milestones

- ✅ **v1.0 GCP Re-platform** — Phases 1-12 (shipped 2026-07-20) — [archive](./milestones/v1.0-ROADMAP.md)
- 🚧 **v1.1 Tribunal Integration** — Phases 13-20 (in progress, scoped 2026-07-20)

## Overview

v1.1 absorbs the existing, working Tribunal deep-research engine (`MOELD/Nestor/nestor_pulse_sdk`)
into the live intake GCP platform — one project, one login, one UI. The journey: re-home Tribunal as
two Cloud Run services with an isolated `tribunal` schema and a verified-intact legal audit chain
(Phase 13) → retire its standalone auth and prove the server-to-server seam (Phase 14) → build the
milestone spine on the engine as-is: research trigger + live progress bridge into the admin UI
(Phase 16) → secure the raw output behind a superadmin-only, audit-guarded download (Phase 17) →
human-crafted report upload and client delivery (Phase 18) → redesign the research engine in three
steps (operator decision 2026-07-24, supersedes the 2026-07-21 deferral): operator surfaces on
recorded run data (Phase 15), verification gates proven on the recorded claim fixture (Phase 15.1),
and the engine core — question workshop, structured fact lists, reliability — live-validated against
the recorded baseline (Phase 15.2) → Q&A chat over the NEW engine's indexed findings via Voyage +
Haiku (Phase 19) → close out deferred v1.0 chores and the parity UAT ledger (Phase 20). The flow
extends from `decomposed` through `in_research` to `delivered`.

## Phases

**Phase Numbering:**

- Integer phases (13, 14, 15…): Planned milestone work. v1.1 continues from v1.0's Phase 12.
- Decimal phases (15.1, 15.2): Urgent insertions (marked with INSERTED)

<details>
<summary>✅ v1.0 GCP Re-platform (Phases 1-12) — SHIPPED 2026-07-20</summary>

Full phase details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)

- [x] Phase 1: Schema & Migrations (4/4 plans)
- [x] Phase 2: Backend Skeleton & Cloud SQL Wiring (3/3 plans)
- [x] Phase 3: Identity Platform Auth (4/4 plans)
- [x] Phase 4: Tenant Isolation, Proven by Tests (4/4 plans)
- [x] Phase 5: User & Space Management (5/5 plans) — completed 2026-06-29
- [x] Phase 6: Intake CRUD Parity & Frontend API Seam (13/13 plans)
- [x] Phase 7: AI Function Ports (11/11 plans) — completed 2026-07-13
- [x] Phase 8: SSE Skill-Run Progress (3/3 plans) — completed 2026-07-13
- [x] Phase 9: GCS Storage (4/4 plans) — completed 2026-07-13
- [x] Phase 10: Notifications (5/5 plans) — completed 2026-07-14
- [x] Phase 11: Internationalization NL/FR/EN (9/9 plans) — completed 2026-07-14
- [x] Phase 12: Frontend Deploy, Cutover & Supabase Independence (5/5 plans) — completed 2026-07-20

**Close-out note:** parity gate closed as **PARITY ACCEPTED WITH DEFERRALS** (operator decision
2026-07-20) — 21 UAT items + 9 human_needed verifications deferred to post-Tribunal; ledger in
`phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md` and STATE.md Deferred Items.
Supabase retirement = independence-only (D-08): zero Supabase deps in the new stack; the legacy
project is deliberately left untouched.

</details>

### 🚧 v1.1 Tribunal Integration (In Progress)

**Milestone Goal:** A logged-in superadmin can run a full deep-research cycle on a `decomposed`
intake — Tribunal research, human-crafted report delivery, and client Q&A over the findings — on the
same GCP platform, with every client's data isolated to its own space and the legally required audit
trail intact.

- [x] **Phase 13: Tribunal Re-home + Infra Baseline** - Tribunal live in the intake project with isolated schema, verified audit chain (legal gate), concurrency lock, and one proven E2E run (completed 2026-07-20)
- [x] **Phase 14: Auth Retirement + Integration Seam** - Tribunal's standalone auth/orgs/UI retired; intake backend drives it server-to-server, space-scoped (completed 2026-07-20)
- [x] **Phase 15: Research Engine Redesign — Operator Surfaces** - REDEFINED 2026-07-24 (replaces "Engine Enhancements"; draft tournament dropped): superadmin-only verification report, live agent-feed foundation (D15), facts-only cost (C1), numbered clickable citations (D13) — built on recorded run-4cbb5311 data, no live LLM runs (completed 2026-07-24)
- [x] **Phase 15.1: Research Engine Redesign — Verification Gates** (INSERTED 2026-07-24) - materiality + error-likelihood gates, canonical grouping, corroboration prioritization, fail-loud, "superseded" verdict — proven by replaying the recorded 1,162-claim fixture. Plans 01-10 executed 2026-07-25; verification returned `gaps_found` on SC2 (no production writer for `verification_verdict`; `superseded_note` dead data) — GAP CLOSURE in progress via plans 11-15 (scoped 2026-07-25) (completed 2026-07-26)
- [ ] **Phase 15.2: Research Engine Redesign — Engine Core** (INSERTED 2026-07-24) - question workshop + pairwise tournament (absorbs ENGINE-05), per-provider fact lists, SerpAPI researcher stream, LLM-based merge, reliability R1–R7 — live-validated vs the recorded baseline after 2026-08-01; old engine path removed on acceptance
- [x] **Phase 16: Research Trigger + Progress Bridge** - Superadmin triggers a run on a `decomposed` intake; live stage progress + running cost in the admin UI; completion/failure email; cost cap re-enabled (completed 2026-07-22)
- [x] **Phase 17: Raw Output + Audit Chain Guard** - Full raw research output as a superadmin-only, space-scoped download; audit chain guarded on the completion path (completed 2026-07-22)
- [x] **Phase 18: Human Report Upload + Client Delivery** - Superadmin uploads the final PDF (status → `delivered`); client sees/downloads it + delivery email (completed 2026-07-22)
- [ ] **Phase 19: Q&A Chat (Voyage + Haiku RAG)** - Findings indexed on completion; client + superadmin ask grounded questions post-delivery, space-scoped
- [ ] **Phase 20: Deferred Chores + v1.0 UAT Closure** - The 21-item deferred UAT ledger re-run, carried-over chores done, 3 open product decisions decided + implemented

## Phase Details

### Phase 13: Tribunal Re-home + Infra Baseline

**Goal**: Tribunal runs live in the intake GCP project with correctly isolated schema/migrations, its legally required audit chain verified intact, concurrency-safe locking in place, and one real research run proven end-to-end green — before any feature code depends on it.
**Depends on**: Phase 12 (v1.0 — live intake platform on GCP)
**Requirements**: ENGINE-01, ENGINE-02, ENGINE-04, ENGINE-08
**Success Criteria** (what must be TRUE):

  1. `tribunal-api` and `tribunal-worker` run as Cloud Run services in the intake GCP project, with a `tribunal` schema on the shared Cloud SQL instance migrated via its own separate `alembic_version` table (no revision-ID collision with the intake line).
  2. `verify_chain` returns green against the re-homed audit hash-chain — the tamper-evident chain survives the move (EU AI Act Art. 12 gate, before 2026-08-02).
  3. Two simultaneous runs from different spaces complete without interfering — the per-run audit-chain advisory lock (Tribunal's unexecuted plan 01-19) is in place and proven by a ≥2-concurrent-run test.
  4. One real research run completes end-to-end green on the new deployment (closes Tribunal's unverified-E2E gap), and its measured max length is recorded for later stale-run calibration.

**Plans**: 4 plans

  - [x] 13-01-PLAN.md — Copy Tribunal engine into tribunal/ (verbatim; frozen hash-chain, sole cross-dep, import-graph gate)
  - [x] 13-02-PLAN.md — Isolated Alembic line (tribunal_alembic_version + schema + 0008 rewrite) + per-run advisory lock (ENGINE-08 keystone)
  - [x] 13-03-PLAN.md — By-construction IaC + Phase-13 runbook + Cloud Build configs + retargeted deploy scripts (audit bucket 7y Unlocked, worker max=5)
  - [x] 13-04-PLAN.md — Operator live session: migrate + deploy + LUKOIL E2E proof + verify_chain + ≥2-concurrent proof + record duration/cost + teardown old project (D-02)

### Phase 14: Auth Retirement + Integration Seam

**Goal**: Tribunal's standalone auth, orgs, and UI are retired so the intake backend is the sole caller, with every run space-scoped end-to-end.
**Depends on**: Phase 13
**Requirements**: SEAM-01, SEAM-02
**Success Criteria** (what must be TRUE):

  1. Tribunal's own logins/orgs/UI are gone (`InternalCallerProvider` installed; `orgs/`, `account/`, `Login.jsx`, static `web/` mount removed) and only the intake backend can call the Tribunal API (IAM invoker = intake runtime SA, internal-only).
  2. Every intake space maps 1:1 onto a Tribunal org/project (identity `space_id` → `tenant_id`, lazy project provisioning), so each run is space-scoped from trigger to storage.
  3. The CI-gated cross-tenant denial suite is extended to cover Tribunal tables and passes (GUC-name mismatch cannot leak across the HTTP boundary).

**Plans**: 4 plans

  - [x] 14-01-PLAN.md — Retire Tribunal auth surface + install InternalCallerProvider; salvage ensure_org/ensure_project + /ensure endpoints (SEAM-01/02)
  - [x] 14-02-PLAN.md — Intake seam client: OIDC minting + ensure_org/ensure_project HTTP client (SEAM-02)
  - [x] 14-03-PLAN.md — Two-suite cross-tenant denial gate: seam (pg8000) + tribunal.* RLS (asyncpg) (SEAM-02)
  - [x] 14-04-PLAN.md — Dedicated tribunal-run SA + invoker binding + seam env + runbook + D-07 live proof (SEAM-01/02)

### Phase 15: Research Engine Redesign — Operator Surfaces

**Goal**: The superadmin gets truthful post-run visibility on the engine as it runs today — a superadmin-only verification report, the live agent-feed foundation, facts-only cost itemization, and numbered clickable citations — built and UAT'd against the recorded run-4cbb5311 data with NO live LLM runs.
**Depends on**: Phase 16 (SSE bridge + dynamic-stage contract) + Phase 17 (audit bundle path) — both complete. REDEFINED 2026-07-24 (operator): replaces "Engine Enhancements (Plan-Critique + Draft Tournament)"; requirement source = `.planning/RESEARCH-ENGINE-DECISIONS.md` (D1–D15, R1–R7, C1) + `.planning/STAKEHOLDER-NOTES.md` §2026-07-24 (applies to 15/15.1/15.2).
**Requirements**: ENGINE-09
**Success Criteria** (what must be TRUE):

  1. A superadmin-only post-run verification report renders for a completed run from recorded data (run 4cbb5311): gate funnel numbers, per-claim verdicts, drill-down — no client visibility (16-D-08 stands).
  2. The live agent-feed foundation (D15) renders agent-level activity per the operator-agreed feed mockup — extending (not replacing) the Phase 16 dynamic-stage-list contract; per-row cost visible.
  3. Cost display is facts-only (C1): every countable cost class is counted (cache writes, search fees, deep-research usageMetadata) — pending-then-backfill-exact, never an estimate.
  4. Citations render as numbered, clickable references generated from the existing 3-table citation model (D13); every citation number resolves.
  5. `verify_chain` stays green — new fields only ADD; no frozen audit payload field renamed.

**Plans**: 7 plans

  - [x] 15-01-PLAN.md — Foundation: tribunal alembic 0011 (cost columns + verification_verdict RLS table) + models + recorded-run fixture + hash-chain replay
  - [x] 15-02-PLAN.md — Cost-truth C1 fixes: cache-write charge + web_search/web_fetch fees + Gemini DR usageMetadata + pending flag (facts-only)
  - [x] 15-03-PLAN.md — Verification report shaper + /verification endpoint + deterministic [n] citation numbering + enriched /metrics feed schema (RLS-denial tested)
  - [x] 15-04-PLAN.md — Intake seam: get_verification/get_source methods + superadmin-only proxy routes + denial trio
  - [x] 15-05-PLAN.md — Frontend: D15 agent-feed renderer + superadmin VerificationReport + research.ts getVerification + en/fr/nl i18n
  - [x] 15-06-PLAN.md — Frontend: numbered clickable CitationPanel (stored-snapshot, dead-link safe) + getSource + en/fr/nl i18n
  - [x] 15-07-PLAN.md — DEPLOY-RUNBOOK Phase 15 section (dual rebuild + 0011 migrate + frontend) + 15-UAT.md recorded-run walkthrough + operator UAT checkpoint

### Phase 15.8: Research Engine Redesign — Yield Instrumentation, Deploy + One Measuring Run (Wave 5) (INSERTED)

**Goal:** Record yield per assignment so routing can later be evidence-based — then **deploy the whole
redesign in ONE release and measure it with ONE live run**.
**Depends on:** Phases 15.4, 15.5, 15.6, 15.7 — all of them.
**Scope source:** `.planning/ENGINE-REDESIGN-SPEC.md` § 6 (D-R8) and § 8.
**SEQUENCING — operator decision 2026-07-29:** *"I don't want to measure anything unless we finish all
changes."* This reverses the spec's "ship Wave 1 alone" instruction. Nothing deploys until every wave
is built. The trade-off was stated and accepted: with several waves landing together, an unexpected
result cannot be attributed to a single change.
**Absorbs the parked plan `15.4-11`**, which must be RE-SCOPED from "Wave 1 alone" to the full redesign
before it executes — including V-01 comparison rows for the later waves.
**Blocking pre-conditions:** settle plan 15.4-07's `gpt-5.6-sol` cost row; and prove alembic `0016`
with the literal `Running upgrade 0015 -> 0016` line, never exit 0.
**NO LONGER BLOCKING — `Nestor_Claude_Temp` rotation is DEFERRED TO GO-LIVE (operator, 2026-08-03).**
The key transited a chat in plaintext 2026-07-27 and is live on both Tribunal services; that risk is
**deliberately accepted** for the pre-go-live period. **Do not rotate it early, and do not re-raise it
as a gap or a blocker** — it is a decision, not an oversight. Rotate at go-live.
**Requirements**: none
**Plans:** 16/15 plans complete
⛔ **THE PHASE GATE (15.8-13) HAS RUN AND IS RED** (2026-08-04, commit `5f62a62`).
`EXPECTED_FILES` 36 → **43**, `collecting: 43 of 43`, **1 failed / 1753 passed / 13 skipped** — the
1754 passed floor met exactly. The one failure is a **real production defect** in
`research_division.assignment_identity` (a memory address written into a provenance column), not a
config problem. `cloudbuild.test-gates.yaml` is green at **187 passed / 2 deselected**, a genuine
regression pass over four waves of engine edits (10 of its 13 files import the edited modules).
The batched mutation debt — including `15.4-05`'s P3 and P4, owed since 2026-07-29 — is **PAID**.
**15.8-14 (the ONE deploy) and 15.8-15 (the ONE ~$45 run) MUST NOT START until the engine gate is
green.** Detail: `15.8-13-SUMMARY.md` § FINDING-1 and `.planning/STATE.md` § Gates (15.8).

Plans:

- [x] TBD (run /gsd-plan-phase 15.8 to break down) (completed 2026-08-05)

### Phase 15.7: Research Engine Redesign — Creative Workshop Loop (Wave 4) (INSERTED)

**Goal:** Turn the question workshop into a real creative loop: generative evolve, judges that give
reasons, a meta-review, a **10-round cap** with a three-criteria saturation exit and per-round
spend/population **instrumentation** (not an enforced ceiling). The tournament is kept and made real
(Q1 resolved) — it earns its cost only because Wave 3's discovery bracket gives it genuinely
different ideas to rank, instead of narrower rewordings of questions the client already asked.
**Depends on:** Phase 15.6 (the discovery bracket is what makes the tournament worth running).
**Scope source:** `.planning/ENGINE-REDESIGN-SPEC.md` § 5 (D-R6, D-R9, **D-R10, D-R11**), as
corrected 2026-07-31, plus `15.7-CONTEXT.md`'s locked decisions **D-W4-1 … D-W4-8**.
**⚠ READ FIRST — `15.7-CONTEXT.md` is THE AUTHORITY**, then `15.7-OPEN-ITEMS.md` (whose `## RULED`
section still records D-R11 in its superseded median-seed form). § 5 still reads the OPPOSITE way on
its face for the tournament — a skim is the documented failure mode.
**The design has already been RUN.** An 11-experiment local harness (~$3, scratchpad only, no repo
code changed) replayed the real V-01 run and measured the whole loop end-to-end. Build the validated
configuration (`exp11`): ONE global loop, 12 candidates generated per client question, winners = a
floor of 5 per client question + 2 cross-cutting applied at the CUT, prefer-KEEP-over-WEAK, the
truncation caps raised, a newcomer catch-up schedule, exit criteria unchanged. Measured: 17 questions,
none weak, converges in round 4, $0.24 / 97 calls, population flat at 34–41. Every number is n=1.
**NOT DEPLOYED, and no plan may propose it.** Waves 1–4 land in git only; there is exactly ONE deploy
and ONE measuring run, both at the end of phase 15.8.
**Code review runs PER WAVE, not batched** — Wave 3 shipped 42/42 verification and 1283 green tests
with two criticals living in the SEAMS between plans.
**Requirements**: none (this phase maps to no REQ-ID; plans trace to decision IDs instead)
**Plans:** 9/9 plans complete

Plans:

- [x] 15.7-01-PLAN.md — wave 1 — grouping declamp + the two downstream bounds that would silently clip the D-W4-5 floor (D-W4-4a)
- [x] 15.7-02-PLAN.md — wave 1 — the five truncation/count constants, raised together and pinned in one ladder test (D-W4-8)
- [x] 15.7-03-PLAN.md — wave 1 — `workshop_loop.py`: derived round count, catch-up budget, floor-at-the-cut selection, three-criteria exit, per-round metrics (D-R9/D-W4-3/5/6/7)
- [x] 15.7-05-PLAN.md — wave 1 — `workshop_admission.py`: the corrected premise-real grounded lookup, the real-search-result evidence gate, Python-stamped parents (D-R10)
- [x] 15.7-04-PLAN.md — wave 2 — `workshop_register.py`: the WITHIN-RUN rejected register, three bar causes and no fourth (D-W4-1)
- [x] 15.7-06-PLAN.md — wave 3 — `workshop_evolve.py`: generative evolve (COMBINE/EXTEND/INVERT/SPECIALISE/INVENT), the D-W4-2 anchors, the meta-review (D-R6)
- [x] 15.7-07-PLAN.md — wave 3 — aspect extraction with a Python assertion, the added COVERAGE rule, and the barred semantic drop in `cluster_candidates` (D-W4-4b/D-W4-1)
- [x] 15.7-08-PLAN.md — wave 4 — judges that reason, carried standings with the catch-up schedule, the derived round count, and Guard 2 marking what it rescues (D-R6/D-R9/D-W4-3/D-W4-6)
- [x] 15.7-09-PLAN.md — wave 5 — the loop driver in `run_workshop_stage_b`, instrumentation, and the END-TO-END seam tests for every § 8 Wave 4 item

### Phase 15.6: Research Engine Redesign — Dispatch + Discovery Bracket (Wave 3) (INSERTED)

**Goal:** Replace one-angle-per-question dispatch with an LLM that groups the winning questions into
**at most 5 groups**, each sent to **all providers** — and add a **discovery bracket** that may raise
questions the client did not ask, each carrying the quote and source that provoked it. **No source, no
slot.** `own` is dropped from the rotation (2 of 4 angles failed, English output in a Dutch run, 2
unique URLs). 5 x 3 = 15 calls against V-01's 19.
**Depends on:** Phase 15.5 (claim attribution — HARD prerequisite).
**Scope source:** `.planning/ENGINE-REDESIGN-SPEC.md` § 4 (D-R4, D-R5, D-R7).
**Why invention is allowed:** D4's `enforce_scope_guard` is a **coverage floor** (winners' parents must
be a superset of the client questions), not a ceiling. The "never invent" half was only ever two prompt
sentences — and the same file says a prompt sentence is not a control.
**Requirements**: none
**Plans:** 8/7 plans complete

Plans:

- [x] 15.6-01-PLAN.md — wave 1: the `emit_question_groups` index-only tool, the group record, and the pure validator / clamp / one-group-per-client-question fallback
- [x] 15.6-02-PLAN.md — wave 1: the discovery bracket — no source no slot, global pool with a per-parent cap of 3, the engine-authored question frame and the report provenance annotator
- [x] 15.6-03-PLAN.md — wave 2: group-driven dispatch — `own` leaves `_D6_STREAMS`, `_D6_TOP_K` and the round-robin deal are deleted, every group goes to all three providers, and the `degraded_parallel` gap is commented not closed
- [x] 15.6-04-PLAN.md — wave 2: `enforce_group_coverage` (the same repair ladder, one level up) plus the grouping + discovery wiring into `run_workshop_stage_b`
- [x] 15.6-05-PLAN.md — wave 2: the `researched_as` provenance clause in the brief-vs-world report section, in four languages
- [x] 15.6-06-PLAN.md — wave 3: pipeline wiring — groups into `divide()`, discovery into the report, the over-ceiling warning, and end-to-end coverage
- [x] 15.6-07-PLAN.md — wave 4: register the two new test files (33 -> 35), run BOTH builds, and close the PENDING ledger

### Phase 15.5: Research Engine Redesign — Claim Attribution (Wave 2) (INSERTED)

**Goal:** A claim knows which sub-question it answers. Today a claim's `facet` is the parent client
question, inherited from the angle (`_angle` -> `facet`, stamped in Python, never read from model
output). Once a dispatch group can span two client questions that inheritance breaks — a claim from a
mixed group has no single parent. Stamp the sub-question and a `corroboration_key` on the claim row.
**Depends on:** Phase 15.4 (extraction repair — code complete, NOT deployed).
**HARD PREREQUISITE for Phase 15.6.** Not optional, and not reorderable: Wave 3's grouping cannot be
correct without it.
**Scope source:** `.planning/ENGINE-REDESIGN-SPEC.md` § 3 (D-R3).
**Requirements**: none
**Plans:** 3 plans in 2 waves — COMPLETE, gate-verified (engine 1118/0, gates 187), NOT deployed

Plans:

- [x] 15.5-01-PLAN.md — wave 1: the three nullable `claim` columns, alembic 0017 on 0016, and the pure bounded `extract_as_of`
- [x] 15.5-02-PLAN.md — wave 2: thread `_sub_question` / `_corroboration_key` from dispatch onto every claim dict, attach `as_of`, pin the invariant-2 no-op
- [x] 15.5-03-PLAN.md — wave 2: `_insert_claim` writes the three columns (typed, clamped, absent-means-NULL) and the write path is proven with a fake session
- [x] D-W2-4 follow-up (241d9d5) — month precision keeps its month; `maart 2021` / `2021-03` → 2021-03-01
- [x] Gate fix (9064e76) — the stdlib-purity test asserted an exact 4-module allowlist over a file a
      sibling plan also edited; caught only by executing the merged tree. Tightened, not loosened.

**Gates (merged tree):** engine build `3f57de7a` = 1118 passed / 0 failed / 13 skipped,
`collecting: 33 of 33 expected files`, 1131 collected. Gates build `e9e75413` = 187 passed.
Both counts rose from the Wave 1 baseline (1030 / 182).
**OWED AT 15.8:** `Running upgrade 0016 -> 0017` — alembic 0017 has never touched a database, and
0016's `Running upgrade 0015 -> 0016` is still unpaid too.

### Phase 15.4: Research Engine Redesign — Extraction Repair (Wave 1) (INSERTED 2026-07-29)

**Goal:** The engine stops silently throwing away claims it successfully extracted. A distiller reply
parses whatever separator the model actually used; a unit that returns lines but keeps zero claims is
**loud**; an unusable gemini fact list is retried once, covering all three observed format deviations;
gemini grounding redirects are resolved to publisher URLs at ingest so citations cannot rot. Proven by
replaying V-01's two coffee audit blobs and recovering **278** claims.
**Scope source:** `.planning/ENGINE-REDESIGN-SPEC.md` § 2 "Wave 1 — extraction repair" (D-R1, D-R2,
D-V01-11 + smalls). Waves 2–5 of that spec are explicitly NOT in this phase.
**Depends on:** Phase 15.2 gap closure + Phase 15.3 (deployed engine at SHA 20260727-085533). No
dependency on 15.3 plan 09's operator checkpoints.
**Requirements**: none
**Evidence:** `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md` (the two root causes) and
`run-20260728-7dcf51d5-V01-FINDINGS.md` (full forensics, corrections applied).
**Ships alone:** Wave 1 must be deployed and measured by ONE live run before any later wave starts —
everything downstream is judged through the extraction funnel, so shipping the redesign on top of a
broken meter would attribute the parser bug to the redesign.
**Success Criteria** (what must be TRUE):

  1. A distiller response using a real tab, the literal `<TAB>`, `|||`, or ` | ` all parse to the same
     claims; priority order is respected (a real tab wins over a literal `<TAB>` on the same line).

  2. A unit that returns non-empty lines but zero parsed claims logs at **WARNING** with the offending
     first line — the failure that put a false statement in a client report is no longer invisible.

  3. The ZERO-claims warning fires only for facets present in that call's inputs (no more crying wolf
     about a facet that was never in scope).

  4. All three gemini fact-list deviations are covered — **but not all by the retry** (corrected
     2026-07-29 during planning; the original wording over-stated it). Ownership is split because the
     deviations fail differently: **no block** → the one additive retry per report; **`STATEMENT`-prefixed
     lines** → the normalising pre-parse, with the retry as a safety net; **`[cite: N]` in the
     `SOURCE_URL` column** → the cite index, because those facts *survived* parsing and so never reach
     `needs_distiller_fallback` where a retry could see them. The `STATEMENT` normaliser has a test;
     retry failure still falls through to the distiller exactly as today.

  5. `vertexaisearch` redirects are deduped and resolved to publisher URLs at ingest, degrading to
     keeping the unresolved redirect — never dropping a citation.

  6. The `gpt-5.6-sol` cost gap is **resolved either way, deliberately** — and the dropped
     `deep_research`/`own_research` `run_event` rows are emitted.
     **Amended 2026-07-29** (original wording: "`gpt-5.6-sol` is in the cost table (`run.cost_pending`
     can clear)"). `_rate()` at `cost_table.py:230` turns a null rate into `Decimal("0")`, so adding
     the key with nulls produces a confident **$0.00** and clears `cost_pending` on a fabricated
     number — strictly worse than today's honest NULL, which at least says "unknown". The criterion is
     therefore a **binary owned by the operator**, and BOTH answers satisfy it:
     (a) **published rates found** → the key is added and `cost_pending` can clear; or
     (b) **no published rate exists** → the key stays absent, `cost_pending` legitimately never clears
     for it, and the decision is recorded with its reason.
     What would FAIL this criterion is a guessed price, or leaving the question unanswered.
     Rationale: the original wording made a correct decision look like a gap — this project's recorded
     failure mode of a gate going red on sanctioned work.

  7. **Replay proof:** V-01's two coffee audit blobs yield **278** claims through the new parser, and
     the two blobs that already worked still yield **43** and **143**.

  8. `test_claim_distiller.py` / `test_distiller_coverage.py` are updated deliberately — the prompt
     contract change is reviewed as the substantive edit it is, not an incidental fixup.
**Plans:** 11 plans in 5 waves

Plans:

- [ ] 15.4-01-PLAN.md (W1) — Commit V-01's four distiller audit blobs as a redaction-checked regression fixture with a 141/137/43/143 manifest (operator sign-off on the credential scan)
- [ ] 15.4-02-PLAN.md (W1) — Tribunal alembic `0016`: two nullable `source` columns (`resolved_url`, `resolution_status`) + ORM lock-step; engine gate 30 → 31
- [ ] 15.4-03-PLAN.md (W2) — D-R1(a)+(b): the separator-tolerant `_split_distiller_line`, the `FACET ||| CLAIM_TEXT ||| EVIDENCE` prompt contract, a first-class prompt-contract guard (the coverage that was believed to exist and did not), both historically-named test files updated, and the 278/43/143 replay proof; engine gate 31 -> 32
- [ ] 15.4-04-PLAN.md (W1) — D-R2 parser half: the uniform `STATEMENT`-prefix normaliser (idx 8) and a report-derived `[cite: N]` → URL index that recovers idx 4's lost sources
- [ ] 15.4-05-PLAN.md (W1) — The dropped `run_event` rows: tolerant `agent_done` build lambdas in `research_division.py` and `own_researcher.py` — unknown renders as unknown, never as 0, and `emit_safe` is not touched
- [ ] 15.4-06-PLAN.md (W2) — Investigate and record the three parked questions (396/426/293, `gate_errors: 153`, 175 null-certainty claims), judged from the delivered report; docs only
- [ ] 15.4-07-PLAN.md (W1) — `openai/gpt-5.6-sol` cost row: published rates or a recorded absence — never a null-rate entry, which `_rate()` renders as a fabricated $0.00
- [ ] 15.4-08-PLAN.md (W3) — D-R1(c)+(d): "returned lines, kept zero claims" at WARNING with the offending line, and the ZERO-claims warning scoped to the call's own in-scope facets
- [ ] 15.4-09-PLAN.md (W2) — Grounding-redirect resolution BEFORE the persistence transaction opens: deduped, one hop, http(s)-validated, deadline-bounded, degrading to keeping the unresolved redirect
- [ ] 15.4-10-PLAN.md (W4) — D-R2 retry half: ONE additive corrective re-ask of the same provider on the `needs_distiller_fallback` branch, falling through to the distiller byte-identically on failure
- [ ] 15.4-11-PLAN.md (W5) — DEPLOY: runbook § Phase 15.4 (dual Tribunal rebuild + `0016` proven by its literal upgrade line), the deploy, and ONE live run compared against V-01

### Phase 15.3: Research run page — engine run-events + dedicated run route (INSERTED)

**Goal:** A deep-research run has its own page — openable, closeable, bookmarkable and reopenable at `/admin/pulse/runs/:runId` — showing an ordered, durable feed of what the engine actually did at every step, with an elapsed clock that does not restart and every one of the eight run statuses handled honestly. The engine emits the events that page needs (dispatch, tool, search, reasoning, stream config, agent start/finish/retry/fail, per-stage summaries) into a new append-only `run_event` table, best-effort and PII-scrubbed, without changing anything the pipeline decides, dispatches or produces.
**Requirements**: none assigned — this phase carries no REQUIREMENTS.md id. Its source of record is `15.3-CONTEXT.md` (D-01…D-12) and the operator's design of record `docs/design/prototypes/ResearchRunImproved.tsx`.
**Depends on:** Phase 15 (feed contract), Phase 15.2 gap closure (`started_at` across the seam, `scrub_pii`, the stage-log choke point). Ships in the SAME deploy batch as the 15.2 gap fixes (D-03).
**Plans:** 8/9 plans executed

Plans:

- [x] 15.3-01-PLAN.md (W1) — `run_event` table (tribunal alembic `0015`) + `RunEvent` model + the never-raising, PII-scrubbing, batched `runs/run_events.py` emitter; engine gate 27 → 28
- [x] 15.3-02-PLAN.md (W2) — `GET /api/runs/{run_id}/events` (paginated, seq-ordered, gate-free, 404-on-deny) + additive `RunMetrics.event_seq` cursor; engine gate 28 → 29
- [x] 15.3-03-PLAN.md (W3) — run lifecycle + labelled stage dividers and per-stage summaries at the `set_stage` choke point, dispatch headers + reasoned agent children in the angle fan-out; engine gate 29 → 30
- [x] 15.3-04-PLAN.md (W4) — search/tool/thinking events in the own-researcher stream + long-poll progress events (a wait that says it is a wait — the withdrawn-D-C lesson)
- [x] 15.3-05-PLAN.md (W4) — brief-parse events + orientation, candidate generation and tournament rounds at round granularity
- [x] 15.3-06-PLAN.md (W3) — intake alembic `0013` (`research_runs.event_seq`) + the cursor mirrored onto the existing SSE frame (D-05: one connection, one terminal authority)
- [x] 15.3-07-PLAN.md (W3) — `get_run_events` seam verb + the superadmin events proxy + the run→intake `locate` verb, all existence-hidden 404
- [x] 15.3-08-PLAN.md (W5) — THE PAGE: frontend transport (`getRunEvents`/`locateResearchRun`, backfill-then-delta `useRunEvents`), the shared `runClock` (D-09), the flat route `admin.pulse.runs.$runId.tsx` (D-08), the "Open run" entry point, and `RunFeed` — the twelve-kind renderer with derived grouping, auto-collapse, the live badge and one shared cursor, memoised for thousand-event runs
- [ ] 15.3-09-PLAN.md (W6) — THE STATES, THE AFFORDANCES AND THE DEPLOY: all eight statuses (D-11, degraded shares the success branch, parked has its own, the feed is a sibling so failed/cancelled keep their evidence); the four carried-over D-10 affordances (audit drill-down, `chain_status` download lock + re-verify, resume-on-parked, Stop confirmation); DEPLOY-RUNBOOK § Step 15.2.k extended to the combined deploy (both alembic lines, corrected gate count) + the what-shipped-together attribution record D-03 requires; two blocking operator checkpoints

### Phase 15.1: Research Engine Redesign — Verification Gates (INSERTED 2026-07-24)

**Goal**: The verification stage applies the redesigned gate package — materiality gate, error-likelihood gate, canonical grouping, corroboration prioritization, fail-loud behavior, and the "superseded" verdict — proven by replaying the recorded 1,162-claim fixture through the gates in tests.
**Depends on**: Phase 15 (surfaces render the gate outputs). No live LLM runs needed.
**Requirements**: ENGINE-10
**Success Criteria** (what must be TRUE):

  1. The gate pipeline replays the recorded 1,162-claim fixture (`docs/tribunal-run-reports/run-20260722-4cbb5311/selection-experiment/`) in tests and reproduces the recorded keep/drop numbers.
  2. Materiality + error-likelihood gates, canonical grouping, and corroboration prioritization run in the verification stage (STAKEHOLDER-NOTES package + D9/D11), with fail-loud on gate errors and a "superseded" verdict available.
  3. `verify_chain` stays green — frozen payload fields unchanged.

**Plans**: 16 plans (9 waves — plans 11-16 are the 2026-07-25 gap-closure set, waves 7-9)

  - [x] 15.1-01-PLAN.md — Fixture reader `load_selection_experiment()` + 13-key `RECORDED_FUNNEL_COUNTS` (G-13) + no-Postgres `cloudbuild.test-gates.yaml`
  - [x] 15.1-02-PLAN.md — G-12 corroboration: `found_by` provenance in the distiller + merging `_dedupe_claims` (1,162 stays 1,162)
  - [x] 15.1-03-PLAN.md — G-06/G-07 `superseded` producer side: tool enum, skeptic prompt, normalising parse boundary, adjudicate regression
  - [x] 15.1-04-PLAN.md — G-03/G-04 canonical clustering: block-then-cluster replaces exact-key bucketing, signature frozen
  - [x] 15.1-05-PLAN.md — `gates.py`: materiality + error-likelihood gates, G-11 fail-toward-more-checking, never retry a usage-cap 400
  - [x] 15.1-06-PLAN.md — G-08/G-09/G-10/G-14 report shaper: three buckets, `verification_degraded` in words, pydantic fields, client-appendix negative test
  - [x] 15.1-07-PLAN.md — G-02 pipeline wiring: gate stage insertion, gate-driven selector, corroboration ordering, low-stakes depth tier, bucket-3 counters
  - [x] 15.1-08-PLAN.md — Funnel persistence: `run.verification_summary` written in the worker's completion transaction (SC1 propagation)
  - [x] 15.1-09-PLAN.md — G-01 pair: deterministic answer-key replay CI gate + the `@pytest.mark.live` August calibration (no threshold)
  - [x] 15.1-10-PLAN.md — Phase gate (full suite, `verify_chain` green), dual Tribunal image rebuild + deploy, DEPLOY-RUNBOOK section, deferred Phase-15* UAT checklist
  - [x] 15.1-11-PLAN.md — GAP CLOSURE (wave 7): `superseded_note` storage — tribunal alembic `0012` + ORM mirror + three new test files pre-registered in the no-Postgres gate
  - [x] 15.1-12-PLAN.md — GAP CLOSURE (wave 7): publishing surface — `_verdict_dto` emits `superseded_note`, `verdicts_total == 0` funnel fallback so `unverified` can never contradict the funnel (CR-02), gate-error unit fixed (WR-02)
  - [x] 15.1-13-PLAN.md — GAP CLOSURE (wave 7): caveat reaches synthesis via `contested_notes` (CR-01a), `gate` stage declared in `ENGINE_STAGES` (WR-03), false "low-stakes supporting detail" appendix line replaced (WR-11)
  - [x] 15.1-14-PLAN.md — GAP CLOSURE (wave 8): the production `verification_verdict` writer — `_insert_verdict` in `persist_tribunal_claims`, survivors linked by `claim_id`, dropped claims persisted with NULL (CR-02)
  - [x] 15.1-15-PLAN.md — GAP CLOSURE (wave 9): three Cloud Build gates + SC3 re-proof, alembic `0012` applied live + dual Tribunal redeploy + frontend rebuild, runbook Steps 15.1.f/15.1.g, UAT Known-Gaps closure + WR-01/WR-10 deferred to 15.2
  - [x] 15.1-16-PLAN.md — GAP CLOSURE (wave 7): operator surface — render the `verdicts.superseded` class in its own section (new nl/en/fr key) + fall the amber caveat back to `superseded_note`; forces a frontend rebuild in 15.1-15

### Phase 15.2: Research Engine Redesign — Engine Core (INSERTED 2026-07-24)

**Goal**: The pipeline core is restructured — question workshop with pairwise tournament (absorbs ENGINE-05), structured per-provider fact lists + safety-net distiller, SerpAPI-fueled researcher stream, LLM-based cross-provider merge, language tagging, reliability R1–R7, and report changes — validated by a live run compared against the recorded baseline plus operator sign-off, after which the old engine path is removed immediately.
**Depends on**: Phase 15.1 (gates in place). Live validation run lands after 2026-08-01 (Anthropic monthly cap reset).
**Requirements**: ENGINE-05, ENGINE-11
**Success Criteria** (what must be TRUE):

  1. The question workshop (orientation + critique + pairwise tournament, D2–D7) selects the run's research questions — visible in the feed — without altering client-validated questions (D4). This IS the evolved plan-critique pass (ENGINE-05 absorbed per S-02).
  2. Providers return structured fact lists with a per-provider safety-net distiller (D8); the SerpAPI-fueled own researcher stream contributes (D10); the cross-provider merge clusters same-fact claims via LLM-based grouping (D9/B-04 — no embedding machinery).
  3. Reliability R1–R7 hold: retry/backoff, breaker, checkpointing, park + superadmin-click-only resume (F-01), checkpoint-resumes free/unlimited with the 3-attempt rule counting full restarts only (F-02), park/failure mail to the triggering superadmin (F-03).
  4. V-01/V-02 acceptance passes: live run on a test intake compared against the recorded 4cbb5311 baseline; hard checklist green (workshop questions visible in feed, per-provider fact lists present, gate funnel recorded, citations resolve, `verify_chain` green, cost fully itemized per C1, feed complete with per-row cost) PLUS operator sign-off next to the recorded baseline.
  5. On acceptance the old engine path (adaptive_intake one-call → distiller-as-shredder → exact-key grouping) is removed immediately (V-03 — no fallback flag), and the first live run validates the deployed F-01 skeptic fix by construction.

**Plans**: 19 plans across 12 waves (planned 2026-07-26). Waves 4-12 are single-plan and mostly serialize file ownership rather than dependency depth — `pipeline/tribunal/pipeline.py` is touched by seven plans and `synthesis/steps.py` by four, and GSD requires zero `files_modified` overlap inside a wave.

**Wave 1** *(no dependencies — 3-way parallel)*

  - 15.2-01 — alembic `0013` (D-13 columns + `research_gap` + `ck_run_status`) + ORM sync + non-superuser RLS denial harness
  - 15.2-02 — `reliability.py` (R1/R2/R4/R6 primitives, `terminal_state()`) **+ creates `cloudbuild.test-engine.yaml`**, the phase's keyless fast gate
  - 15.2-03 — `StageFeed` owner + new `ENGINE_STAGES` keys + `audit_id` plumbing (D15/R5/F4/F9)

**Wave 2** *(blocked on Wave 1 — 4-way parallel)*

  - 15.2-04 — D8 fact-list format + tolerant parser (`facts.py`)
  - 15.2-05 — D-05 anchor placement + D-06 unresolved accounting + D13 graded sources
  - 15.2-09 — D-09 shared status predicate + D-12 four-state vocabulary
  - 15.2-10 — question workshop A: orientation, candidate generation, near-duplicate clustering

**Wave 3** *(3-way parallel)*

  - 15.2-06 — D-08's two deterministic report sections
  - 15.2-11 — question workshop B: critique (**ENGINE-05, absorbed per S-02**), Swiss tournament, evolve, D7 tags
  - 15.2-12 — SerpAPI own-researcher stream (D10) + D-16 cost arithmetic

**Waves 4-8** *(serial)*

  - 15.2-07 (W4) — WR-01 fix + the coverage cost-trap intersection + D-11 breaker-gated re-entry
  - 15.2-08 (W5) — WR-10 / D-10 `checked_incidentally` + D-06/D-12 surfacing
  - 15.2-13 (W6) — D6 distribution + `_MAX_ANGLES` rework + 4th stream + D-03 unwiring of `adaptive_intake`
  - 15.2-14 (W7) — fact lists from the three third-party streams + D-14 fallback (D-15 protected)
  - 15.2-15 (W8) — cross-provider merge before the gates (D9/D11) + D-13 persistence

**Waves 9-12** *(serial)*

  - 15.2-16 (W9) — R3/R4/R7 checkpointing + park, Tribunal engine side + its cross-tenant denial test
  - 15.2-19 (W10) — park/resume intake + frontend side: Resume route, F-03 mail, Resume UI
  - 15.2-17 (W11) — **D-02's single gating proof**: stubbed end-to-end run + D-04's rewired replay + the six-gate sweep
  - 15.2-18 (W12) — deploy + runbook, then **parks at UAT until 2026-08-01** for V-01/V-02, then the separate V-03 cleanup commit

**GAP CLOSURE — 7 plans across 4 waves** *(planned 2026-07-27, after the first live run was aborted)*.
Source: `15.2-V01-ABORTED-FINDINGS.md` (D-A, D-B, D-D, D-E, D-F, D-L, D-M + the operator decisions) and
`docs/tribunal-run-reports/run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md` (D-G, D-H, D-I). D-C is
withdrawn (a misdiagnosis); D-J (audit prompt truncation — EU AI Act record) and D-K (text
corruption) are out of scope and get their own phase. Total plans for phase 15.2: **26**.

  - [x] 15.2-20-PLAN.md (W1) — D-E: heartbeat liveness + reclaim ceiling + reap-to-failed, migration 0014, the `NESTOR_WORKER_STALE_MINUTES=525600` revert, gate seeded
  - [x] 15.2-21-PLAN.md (W2) — D-G/D-H: the workshop takes ONLY the client-validated questions; the context pack is context; the decision statement gets a real source
  - [x] 15.2-22-PLAN.md (W2) — D-A/D-B: the OpenAI DR model id (operator checkpoint) + fail-loud config class; the web_fetch error-block replay fix + a genuine fixture
  - [x] 15.2-23-PLAN.md (W2) — D-I/D-M: PII scrub at the dispatch choke point; Gemini fact-list placement + placeholder-URL rejection
  - [x] 15.2-24-PLAN.md (W3) — D-F/D-L: stage entry/exit logging with counts; `started_at`/`completed_at` across the seam onto the mirror row
  - [x] 15.2-25-PLAN.md (W3) — D-D: `cancel_run` seam method + `POST /intakes/{id}/research/cancel` + the Stop button (operator-confirmed UI placement)
  - [x] 15.2-26-PLAN.md (W4) — gate count assertion, the ordered deploy, clearing run `d6bb3aae`, the IAM revoke decision, findings marked up

**Cross-cutting constraints** *(hold in every plan)*: all LLM egress through `audited.*` · frozen audit payload — fields ADD, never rename (`verify_chain` green is a legal gate, EU AI Act Art. 12, deadline 2026-08-02) · no agent frameworks, hand-written loops (`group_skeptic.py` is the template) · never `json.loads` raw model text · no plan may depend on the budget governor, which is inert (`NESTOR_TRIBUNAL_UNCAPPED=1`) · every new table/endpoint gets FORCE RLS + a cross-tenant denial test in the plan that creates it · no local Python/Docker — Cloud Build only · plans 01-17 + 19 require **zero live Anthropic calls**.
**Carried in from Phase 15.1 gap closure (2026-07-25, operator-approved deferrals):** review finding
WR-01 (the coverage gate is unreachable dead code — `adjudications` is seeded `True` for every claim,
so the re-entry mechanism never fires) and WR-10 (verdicts attributed to gate-DROPped group members
can break the "every claim lands in exactly one bucket" funnel invariant). Both live in
`pipeline/tribunal/pipeline.py`'s verify stage, which this phase restructures. Full context in
`phases/15.1-*/15.1-UAT.md` § Deferred to Phase 15.2.

### Phase 16: Research Trigger + Progress Bridge

**Goal**: A superadmin can trigger a research run on a `decomposed` intake and watch live stage-by-stage progress with running cost in the intake admin UI, receiving an email when it finishes — the milestone spine.
**Depends on**: Phase 14 (proven seam). Phase 15 dependency REMOVED (deferred after Phase 19) — integrates against the engine as it runs today; the progress UI MUST render the stage list dynamically from the run's stage trace (9 stages today, no hardcoded count) so Phase 15's added pass costs nothing later.
**Requirements**: SEAM-03, SEAM-04, RUN-01, RUN-02, ENGINE-03, ENGINE-07
**Success Criteria** (what must be TRUE):

  1. Superadmin triggers a run on a `decomposed` intake (status → `in_research`, immediate 202), with the brief assembled from the intake's validated context pack.
  2. Live run progress (stage trace rendered dynamically — 9 stages today — + running cost) renders on the intake detail page in the intake design language, fed by a background poll → `research_runs` → SSE bridge.
  3. Tribunal's interactive pause gates (`needs_input` / `needs_report_spec`) NEVER fire for seam runs (16-CONTEXT D-01/D-01b: the validated intake IS the brief; report spec auto-derived from intake answers), and runs execute on the always-on worker so no run is bounded by a Cloud Run request timeout.
  4. The triggering superadmin receives an email when the run completes or fails.
  5. The stale-run reclaim window is set above the real max run length (no double-runs). NOTE: cost-cap flip-on (`NESTOR_TRIBUNAL_UNCAPPED` off) is DEFERRED by operator decision 2026-07-21 (16-CONTEXT D-02) — before client-billed runs, Phase 20 at the latest.

**Plans**: 5 plans

  - [x] 16-01-PLAN.md — research_runs table (migration 0011 + RLS) + model/repo + fake_tribunal_client fixture (foundation)
  - [x] 16-02-PLAN.md — seam client (create_run/get_metrics/get_report) + brief assembly (no [INTERACTIVE_REPORT]) + pool-safe poll driver + NL/FR/EN completion/failure mail
  - [x] 16-03-PLAN.md — trigger verb (decomposed→in_research, attempt cap) + SSE stream (research terminal set) + cross-tenant denial tests
  - [x] 16-04-PLAN.md — frontend: research.ts + dynamic-stage ResearchRunProgress panel + confirm-dialog trigger + additive derivePhase (client UI untouched)
  - [x] 16-05-PLAN.md — runbook Phase 16 (REBUILD + 0011 migrate + stale-window=90) + operator live run (closes deferred Phase-14 seam UAT)

**UI hint**: yes

### Phase 17: Raw Output + Audit Chain Guard

**Goal**: Once a run completes, its full raw output is secured as a superadmin-only download and the audit chain is guarded on the completion path — nothing research-related is client-visible.
**Depends on**: Phase 16
**Requirements**: RUN-03
**Success Criteria** (what must be TRUE):

  1. Superadmin can download the full raw research output as a file (GCS signed URL, space-scoped).
  2. A client can never access the raw output — the endpoint is superadmin-only and denies cross-space and client access (added to the CI-gated denial suite).
  3. `verify_chain` runs as a hard gate on the run-completion path (audit objects carried, frozen payload preserved), surfacing a broken chain before delivery.

**Plans**: 4 plans

  - [x] 17-01-PLAN.md — research_runs chain/bundle columns (migration 0012) + Tribunal /research-bundle endpoint + seam methods + fixtures (foundation)
  - [x] 17-02-PLAN.md — pure bundle builder + completion-path verify_chain gate + materialize zip to GCS (pool-safe)
  - [x] 17-03-PLAN.md — superadmin-only bundle-url + re-verify routes + denial suite + download/locked/re-verify UI
  - [x] 17-04-PLAN.md — runbook Phase 17 (ordered dual REBUILD + 0012 migrate) + operator live download / verify_chain proof

### Phase 18: Human Report Upload + Client Delivery

**Goal**: The superadmin uploads the externally crafted final report PDF, moving the intake to `delivered`, and the client sees, downloads, and is emailed about it.
**Depends on**: Phase 16 (runs complete); independent of Phase 19
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):

  1. Superadmin can upload the final report PDF (crafted externally in Claude Design), which sets status → `delivered` (run `completed` does NOT auto-deliver — the upload does).
  2. Client sees and downloads the final report in their own UI, and nothing research-related is client-visible before delivery.
  3. Client receives an email notification when the report is delivered.

**Plans**: 4 plans

  - [x] 18-01-PLAN.md — Backend deliver/replace/report verbs (in_research→delivered, PDF-only, forged-key guard, status-gated client read) + report-delivery & cross-tenant denial tests
  - [x] 18-02-PLAN.md — Frontend admin: repair FinalReportBlock (staged upload + explicit Deliver dialog + Replace + PDF-only) + seam verbs + phase-machine wiring + admin reload + NL/FR/EN
  - [x] 18-03-PLAN.md — Frontend client: new delivered-only report route (download-only, chat space reserved) + list "View report" CTA + report-page i18n
  - [x] 18-04-PLAN.md — § Phase 18 runbook (nestor-api + frontend rebuild, no migrate, no new secret) + operator live deploy / stage-deliver-download-mail UAT

**UI hint**: yes

### Phase 19: Q&A Chat (Voyage + Haiku RAG)

**Goal**: After delivery, both client and superadmin can ask questions over the indexed research findings and get grounded, Belgian-Dutch answers.
**Depends on**: Phase 16 (completed research output to index) + Phase 15.2 (NEW engine live — Q&A indexes the new engine's output from day one, order set 2026-07-24); independent of Phase 18
**Requirements**: CHAT-01, CHAT-02, CHAT-03
**Success Criteria** (what must be TRUE):

  1. When a run completes, its findings are chunked and embedded into a dedicated Voyage `voyage-3-large` 1024-dim pgvector table (distinct from the OpenAI 1536-dim column).
  2. Client and superadmin can ask questions post-delivery and get Claude Haiku answers grounded only in the indexed findings (legacy `ask-research` contract: Belgian-Dutch, no markdown, honest when context is insufficient).
  3. Chat is space-scoped (`WHERE space_id` prefilter before the vector op); superadmin additionally sees the source fragments behind each answer while the client does not.

**Plans**: TBD
**UI hint**: yes

### Phase 20: Deferred Chores + v1.0 UAT Closure

**Goal**: Carry-over v1.0 items are closed on the now-extended, stable flow — no new features.
**Depends on**: Phases 16-19 (extended flow live and stable) + Phases 15/15.1/15.2 (engine redesign landed)
**Requirements**: CLOSE-01, CLOSE-02, CLOSE-03
**Success Criteria** (what must be TRUE):

  1. The 21-item deferred v1.0 UAT ledger is re-run against the extended flow and its results recorded.
  2. Chores are done: Resend key rotated, full backend suite rerun in Cloud Build (green), NDA PDF dropped in + image rebuilt, legacy `VITE_SUPABASE_*` env removed.
  3. The 3 open product decisions are decided and implemented: Templates page visibility, Intake-info link-row trimming, and the "Verzonden mails" history block.

**Plans**: TBD

### Phase 21: Research Run Feed Completion

**Goal**: The dedicated run page tells the whole story of a run — every stage reports, finished work reads as finished, and the claims-verification evidence is on the page built to hold it.
**Depends on**: Phase 15.3 (run page + run-event contract), Phase 15.2 (engine core stages)
**Success Criteria** (what must be TRUE):

  1. All 13 tribunal stages emit feed content, not just the 4 wired by 15.3 (`workshop`, `research_division`, `deep_research`, `own_research`). The 8 silent stages — `distill`, `merge`, `gate`, `verify`, `adjudicate`, `coverage`, `conflict`, `synthesize` — each emit a dispatch header and per-item rows, so no phase renders as a label with nothing under it.
  2. A finished agent never renders as a spinner. `agent_run` rows resolve once their work is done, rather than animating forever because the feed is append-only.
  3. The "Show more" toggle appears only when rows are actually hidden — never on a phase whose body is empty or shorter than the collapsed preview.
  4. `VerificationReport` (funnel, verdicts, superseded, reconciled, unverified, true cost) is reachable from the dedicated run page, not only from the intake detail card.
  5. The `deep_research` `thinking` prose is DIAGNOSED before it is trimmed (D-12): a per-site keep/cut
     verdict exists as a reviewable artifact, the operator rules on it, and whatever is ruled is applied —
     a line that leaves the feed is demoted to a log, never deleted.
     ⚠ **AMENDED AT PLANNING 2026-08-10** — measurement contradicts this criterion's original premise.
     All 8 `thinking` sites in `audited_llm_client.py` are money or long-silence, which are D-13's two KEEP
     classes, and 5 of them are pinned by `test_own_researcher.py`, whose own comment reads "the wording is
     the deliverable". Under D-13 as written the correct CONTENT trim is **zero cuts**; the measured volume
     driver is CARDINALITY — one correct line multiplied by 19 angles. A ruling of "no change to that file"
     therefore SATISFIES this criterion. Detail: `21-04-PLAN.md` and the `21-DENSITY-AUDIT.md` it produces.

  6. No raw stage key ever reaches the operator's screen, and a test enforces it.
     ⚠ **AMENDED AT PLANNING 2026-08-10** — three measured corrections to this criterion's premises:
     (a) the recurrence-guard test it asks for **already exists and is already registered in CI** —
     `test_stage_schema.py::test_every_set_stage_key_in_the_pipeline_is_declared`, in
     `cloudbuild.test-gates.yaml`;
     (b) `report_spec` was **not undetected** — it is a deliberate entry in that test's
     `_NON_SCHEMA_MARKERS` allowlist, put there by plan 15.1-13 with a written reason: declaring it
     "would put a phantom row in the ordered checklist of every NON-interactive run";
     (c) `pipeline.py:3955` sits inside `if interactive_report:`, a gate Phase 16's D-01/D-01b says never
     fires for seam runs — so this is a LATENT defect, not the raw key the operator saw during UAT.
     The OUTCOME clause stands. The MECHANISM is an open decision put to the operator at `21-07-PLAN.md`
     Task 1: declare it in the schema, or label it on the READ path per this project's own standing
     generalisation ("when a truncated identifier reaches a reader, resolve it on the READ path instead of
     widening the identifier" — CONTINUE-HERE.md, paid off twice already). Either way the guard is made
     strictly stronger: every allowlisted marker must now prove it has a human label, so the allowlist can
     never again be a hole a raw key reaches the screen through.
**Requirements**: none assigned — this phase carries no REQUIREMENTS.md id. Its sources of record are the
six success criteria above and `21-CONTEXT.md` (D-01…D-15); plans trace to those ids, exactly as phases
15.7 and 15.8 do.
**Plans**: 8 plans in 5 waves (planned 2026-08-10)

Plans:
**Wave 1**

- [x] 21-01-PLAN.md (W1) — frontend: the pure settle rule + the hidden-rows predicate, pinned by vitest, and `RunFeed.tsx` wired to both — no spinner on a finished agent, no toggle over an empty phase (SC2/SC3, D-07/D-08/D-09)
- [x] 21-02-PLAN.md (W1) — frontend: `VerificationReport` reachable from the run page as a SIBLING of the card and the feed, gated on whether a report CAN exist rather than on which card branch renders, so failed and cancelled runs keep their verdicts (SC4, D-10/D-11)
- [x] 21-03-PLAN.md (W1) — engine: `stage_events.py` — the shared row budget, the visible elision row and the house emitter shape — plus `verify`, the stage the operator named twice, with per-cluster lifecycle rows and per-verdict rows (SC1, D-03/D-04/D-05/D-06)
- [x] 21-04-PLAN.md (W1) — engine: `21-DENSITY-AUDIT.md` — the per-site verdict as a reviewable artifact, a BLOCKING operator ruling, then exactly what was ruled and nothing more. Carries the measured contradiction of SC5's premise (SC5, D-12/D-13/D-14)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 21-05-PLAN.md (W2) — engine: `distill`, `merge`, `gate` — copying the landed pattern; each closing sentence bound ONCE and shared between `stage_detail` and the feed so the two surfaces cannot drift (SC1)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 21-06-PLAN.md (W3) — engine: `adjudicate`, `coverage` (the emptiest — a bare marker with no detail at all), `conflict`, `synthesize` including the module-level resume path; the capstone test derives its stage list from the SCHEMA, not a hardcoded thirteen (SC1)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 21-07-PLAN.md (W4) — the WR-03 raw-key fix: a BLOCKING ruling on declare-vs-label, the stale "fourteen stages" docstring corrected to the counted number, and the guard strengthened so the non-schema allowlist can never again hide a raw key (SC6, D-15)

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 21-08-PLAN.md (W5) — DEPLOY: the surface RE-DERIVED from the actual diff (D-02), both Cloud Build gates read as build TEXT, the digest-proven ordered deploy, and a recorded-run UAT with one honest verdict per success criterion. Triggers NO research run (D-01/D-02)

**Wave structure:** W1 is four-way parallel across disjoint file sets — two frontend plans, the engine spine
plus `verify`, and the density audit. W2 → W4 serialise on `pipeline.py`, which every engine plan touches
and which GSD forbids two same-wave plans from sharing. W5 is the deploy.
**Ships BEFORE the first measured run** (D-01): the ~$45 run then validates this feed AND the three
still-unexercised changes at tag `20260806-175613` together, instead of being spent watching a view that
reports nothing for 8 of 13 stages.

## Progress

**Execution Order:**
13 → 14 → 16 → 17 → 18 → 15 → 15.1 → 15.2 → 21 → 19 → 20 (operator decision 2026-07-24, SUPERSEDES the 2026-07-21 deferral: Phase 15 redefined as the Research Engine Redesign, split into 15/15.1/15.2, all before Phase 19 so Q&A chat indexes the NEW engine's output from day one)

**Phase 21 is sequenced BEFORE the first measured run** (operator decision 2026-08-10). The three changes deployed at tag `20260806-175613` have never executed, and the ~$45 run that would validate them is the only thing that can also validate the run feed. Running first would spend it watching a view that reports nothing for 8 of 13 stages, so the feed is fixed first and one run validates both.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-12 (all) | v1.0 | 70/70 | Complete (shipped) | 2026-07-20 |
| 13. Tribunal Re-home + Infra Baseline | v1.1 | 4/4 | Complete    | 2026-07-20 |
| 14. Auth Retirement + Integration Seam | v1.1 | 4/4 | Complete    | 2026-07-20 |
| 15. Research Engine Redesign — Operator Surfaces | v1.1 | 7/7 | Complete   | 2026-07-24 |
| 15.1. Research Engine Redesign — Verification Gates | v1.1 | 16/16 | Complete   | 2026-07-26 |
| 15.2. Research Engine Redesign — Engine Core | v1.1 | 25/26 | In Progress|  |
| 16. Research Trigger + Progress Bridge | v1.1 | 5/5 | Complete   | 2026-07-22 |
| 17. Raw Output + Audit Chain Guard | v1.1 | 4/4 | Complete   | 2026-07-22 |
| 18. Human Report Upload + Client Delivery | v1.1 | 4/4 | Complete    | 2026-07-22 |
| 19. Q&A Chat (Voyage + Haiku RAG) | v1.1 | 0/TBD | Not started | - |
| 20. Deferred Chores + v1.0 UAT Closure | v1.1 | 0/TBD | Not started | - |
| 21. Research Run Feed Completion | v1.1 | 8/8 | Complete   | 2026-08-10 |

### Phase 22: Verification Report as a Page + Citation Hygiene - the verification report moves off the run page onto its own dedicated route and is restyled as a dashboard; citations gain hover previews with the full list collapsed by default; duplicate citations collapse to one number per source; the embedded activity feed is removed from the intake detail page since Open run already serves it

**Goal:** The verification report is a page of its own — an instrumented document with the trust figures above the fold and every existing section intact — whose citations preview on hover, collapse to one number per distinct source without ever being renumbered, and no longer label a retrieval date as a publication date; and the intake detail page no longer duplicates the run activity feed while keeping its way into the run.
**Requirements**: D-22-1, D-22-2, D-22-3, D-22-4, D-22-5 — this phase carries NO REQUIREMENTS.md ids; its sources of record are 22-CONTEXT.md, 22-UI-SPEC.md and the operator UAT in 21-UAT.md
**Depends on:** Phase 21
**Plans:** 8/10 plans executed

Plans:
- [x] 22-01-PLAN.md — wave 1 — the shared normalize_source_url + collapse_citations_by_url, with tests, inside the engine fast gate (44 -> 45)
- [x] 22-02-PLAN.md — wave 1 — frontend Citation type fields + the pure buildCitationIndex that honours the dedupe aliases
- [x] 22-03-PLAN.md — wave 1 — every new locale key in three languages, citation.published -> citation.retrieved, and CitationMarker with its hover card
- [x] 22-04-PLAN.md — wave 1 — D-22-5: the activity feed off the intake page, the Open run link kept
- [x] 22-05-PLAN.md — wave 2 — the dedupe seam in build_verification_report + also_claim_ids on the wire model
- [x] 22-06-PLAN.md — wave 2 — the route rename to .index.tsx, the new /verification route, and the run page CTA as a Link
- [x] 22-07-PLAN.md — wave 3 — the instrumented document: stat strip, proportional funnel, anchored section blocks
- [x] 22-08-PLAN.md — wave 4 — the section nav rail, the collapsed citation list, and the page-level Sheet
- [ ] 22-09-PLAN.md — wave 5 — 22-UAT.md and the DEF-21-02 B1-B6 reconciliation
- [ ] 22-10-PLAN.md — wave 6 — derive the deploy surface, deploy, and prove it by imageDigest
