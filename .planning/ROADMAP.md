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

### Phase 15.3: Research run page — engine run-events + dedicated run route (INSERTED)

**Goal:** A deep-research run has its own page — openable, closeable, bookmarkable and reopenable at `/admin/pulse/runs/:runId` — showing an ordered, durable feed of what the engine actually did at every step, with an elapsed clock that does not restart and every one of the eight run statuses handled honestly. The engine emits the events that page needs (dispatch, tool, search, reasoning, stream config, agent start/finish/retry/fail, per-stage summaries) into a new append-only `run_event` table, best-effort and PII-scrubbed, without changing anything the pipeline decides, dispatches or produces.
**Requirements**: none assigned — this phase carries no REQUIREMENTS.md id. Its source of record is `15.3-CONTEXT.md` (D-01…D-12) and the operator's design of record `docs/design/prototypes/ResearchRunImproved.tsx`.
**Depends on:** Phase 15 (feed contract), Phase 15.2 gap closure (`started_at` across the seam, `scrub_pii`, the stage-log choke point). Ships in the SAME deploy batch as the 15.2 gap fixes (D-03).
**Plans:** 12 plans in 9 waves

Plans:
- [ ] 15.3-01-PLAN.md (W1) — `run_event` table (tribunal alembic `0015`) + `RunEvent` model + the never-raising, PII-scrubbing, batched `runs/run_events.py` emitter; engine gate 27 → 28
- [ ] 15.3-02-PLAN.md (W2) — `GET /api/runs/{run_id}/events` (paginated, seq-ordered, gate-free, 404-on-deny) + additive `RunMetrics.event_seq` cursor; engine gate 28 → 29
- [ ] 15.3-03-PLAN.md (W3) — run lifecycle + labelled stage dividers and per-stage summaries at the `set_stage` choke point, dispatch headers + reasoned agent children in the angle fan-out; engine gate 29 → 30
- [ ] 15.3-04-PLAN.md (W4) — search/tool/thinking events in the own-researcher stream + long-poll progress events (a wait that says it is a wait — the withdrawn-D-C lesson)
- [ ] 15.3-05-PLAN.md (W4) — brief-parse events + orientation, candidate generation and tournament rounds at round granularity
- [ ] 15.3-06-PLAN.md (W3) — intake alembic `0013` (`research_runs.event_seq`) + the cursor mirrored onto the existing SSE frame (D-05: one connection, one terminal authority)
- [ ] 15.3-07-PLAN.md (W3) — `get_run_events` seam verb + the superadmin events proxy + the run→intake `locate` verb, all existence-hidden 404
- [ ] 15.3-08-PLAN.md (W5) — frontend transport (`getRunEvents`/`locateResearchRun`, backfill-then-delta `useRunEvents`), the shared `runClock` (D-09), the flat route `admin.pulse.runs.$runId.tsx` (D-08), and the "Open run" entry point
- [ ] 15.3-09-PLAN.md (W6) — `RunFeed`: the twelve-kind renderer with derived grouping, auto-collapse, the live badge and one shared cursor, memoised for thousand-event runs
- [ ] 15.3-10-PLAN.md (W7) — `RunStatusCard`: all eight statuses (D-11), degraded shares the success branch, parked has its own, and the feed is a sibling so failed/cancelled keep their evidence
- [ ] 15.3-11-PLAN.md (W8) — the four carried-over D-10 affordances: audit drill-down, `chain_status` download lock + re-verify, resume-on-parked, Stop confirmation + operator checkpoint
- [ ] 15.3-12-PLAN.md (W9) — DEPLOY-RUNBOOK § Step 15.2.k extended to the combined deploy (both alembic lines, corrected gate count) + the what-shipped-together attribution record D-03 requires

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

## Progress

**Execution Order:**
13 → 14 → 16 → 17 → 18 → 15 → 15.1 → 15.2 → 19 → 20 (operator decision 2026-07-24, SUPERSEDES the 2026-07-21 deferral: Phase 15 redefined as the Research Engine Redesign, split into 15/15.1/15.2, all before Phase 19 so Q&A chat indexes the NEW engine's output from day one)

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
