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
human-crafted report upload and client delivery (Phase 18) → Q&A chat over indexed findings via
Voyage + Haiku (Phase 19) → land the two engine enhancements, plan-critique and draft-tournament, on
the complete proven flow (Phase 15, deferred by operator decision 2026-07-21) → close out deferred
v1.0 chores and the parity UAT ledger (Phase 20). The flow extends from `decomposed` through
`in_research` to `delivered`.

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
- [ ] **Phase 15: Engine Enhancements (Plan-Critique + Draft Tournament)** - DEFERRED (operator decision 2026-07-21): runs after Phase 19, before Phase 20 — plan-critique pass and pairwise draft tournament land on the complete proven A-to-Z flow
- [ ] **Phase 16: Research Trigger + Progress Bridge** - Superadmin triggers a run on a `decomposed` intake; live stage progress + running cost in the admin UI; completion/failure email; cost cap re-enabled
- [ ] **Phase 17: Raw Output + Audit Chain Guard** - Full raw research output as a superadmin-only, space-scoped download; audit chain guarded on the completion path
- [ ] **Phase 18: Human Report Upload + Client Delivery** - Superadmin uploads the final PDF (status → `delivered`); client sees/downloads it + delivery email
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

### Phase 15: Engine Enhancements (Plan-Critique + Draft Tournament) — DEFERRED after Phase 19
**Goal**: The two new frontier engine enhancements are added to the Tribunal pipeline on the complete, proven A-to-Z flow — after the full intake → research → delivery → Q&A spine is live and UAT'd on the engine as it stands today.
**Depends on**: Phase 19 (complete spine live; enhancements land on and are UAT'd against the full flow). Original dep — Phase 13 (re-homed engine proven green) — remains satisfied.
**Requirements**: ENGINE-05, ENGINE-06
**Success Criteria** (what must be TRUE):
  1. A plan-critique pass reviews the research plan before the multi-provider fan-out launches, and its effect is observable in a run's stage trace (frontier idea A2).
  2. Competing report drafts are ranked pairwise in a tournament and the winner becomes the run's final report (frontier idea A1).
  3. A real research run completes green with both enhancements active, and the audit hash-chain still verifies (`verify_chain` green — no frozen payload field renamed).
  4. The Phase 16 progress UI renders the enhanced run's stage trace (including any added pass) without code changes — confirming the dynamic-stage-list contract held.
**Plans**: TBD
**Note on ordering**: DEFERRED by operator decision 2026-07-21 — originally placed before Phase 16 so the trigger + progress bridge would integrate against the final report/stage shape. Deferral is safe because (a) Phase 16 renders the stage list dynamically from the run's stage trace (no hardcoded stage count), (b) the final report is treated as an opaque artifact downstream, and (c) SC3 already forbids renaming frozen payload fields, protecting the audit chain and Phases 17/19 consumers regardless of when the enhancements land.

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
  - [ ] 16-05-PLAN.md — runbook Phase 16 (REBUILD + 0011 migrate + stale-window=90) + operator live run (closes deferred Phase-14 seam UAT)
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
  - [ ] 17-02-PLAN.md — pure bundle builder + completion-path verify_chain gate + materialize zip to GCS (pool-safe)
  - [ ] 17-03-PLAN.md — superadmin-only bundle-url + re-verify routes + denial suite + download/locked/re-verify UI
  - [ ] 17-04-PLAN.md — runbook Phase 17 (ordered dual REBUILD + 0012 migrate) + operator live download / verify_chain proof

### Phase 18: Human Report Upload + Client Delivery
**Goal**: The superadmin uploads the externally crafted final report PDF, moving the intake to `delivered`, and the client sees, downloads, and is emailed about it.
**Depends on**: Phase 16 (runs complete); independent of Phase 19
**Requirements**: REPORT-01, REPORT-02, REPORT-03
**Success Criteria** (what must be TRUE):
  1. Superadmin can upload the final report PDF (crafted externally in Claude Design), which sets status → `delivered` (run `completed` does NOT auto-deliver — the upload does).
  2. Client sees and downloads the final report in their own UI, and nothing research-related is client-visible before delivery.
  3. Client receives an email notification when the report is delivered.
**Plans**: TBD
**UI hint**: yes

### Phase 19: Q&A Chat (Voyage + Haiku RAG)
**Goal**: After delivery, both client and superadmin can ask questions over the indexed research findings and get grounded, Belgian-Dutch answers.
**Depends on**: Phase 16 (completed research output to index); independent of Phase 18
**Requirements**: CHAT-01, CHAT-02, CHAT-03
**Success Criteria** (what must be TRUE):
  1. When a run completes, its findings are chunked and embedded into a dedicated Voyage `voyage-3-large` 1024-dim pgvector table (distinct from the OpenAI 1536-dim column).
  2. Client and superadmin can ask questions post-delivery and get Claude Haiku answers grounded only in the indexed findings (legacy `ask-research` contract: Belgian-Dutch, no markdown, honest when context is insufficient).
  3. Chat is space-scoped (`WHERE space_id` prefilter before the vector op); superadmin additionally sees the source fragments behind each answer while the client does not.
**Plans**: TBD
**UI hint**: yes

### Phase 20: Deferred Chores + v1.0 UAT Closure
**Goal**: Carry-over v1.0 items are closed on the now-extended, stable flow — no new features.
**Depends on**: Phases 16-19 (extended flow live and stable) + Phase 15 (deferred enhancements landed)
**Requirements**: CLOSE-01, CLOSE-02, CLOSE-03
**Success Criteria** (what must be TRUE):
  1. The 21-item deferred v1.0 UAT ledger is re-run against the extended flow and its results recorded.
  2. Chores are done: Resend key rotated, full backend suite rerun in Cloud Build (green), NDA PDF dropped in + image rebuilt, legacy `VITE_SUPABASE_*` env removed.
  3. The 3 open product decisions are decided and implemented: Templates page visibility, Intake-info link-row trimming, and the "Verzonden mails" history block.
**Plans**: TBD

## Progress

**Execution Order:**
13 → 14 → 16 → 17 → 18 → 19 → 15 → 20 (Phase 15 deferred after Phase 19 by operator decision 2026-07-21 — spine ships on the engine as-is, enhancements land on the complete proven flow)

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-12 (all) | v1.0 | 70/70 | Complete (shipped) | 2026-07-20 |
| 13. Tribunal Re-home + Infra Baseline | v1.1 | 4/4 | Complete    | 2026-07-20 |
| 14. Auth Retirement + Integration Seam | v1.1 | 4/4 | Complete    | 2026-07-20 |
| 15. Engine Enhancements | v1.1 | 0/TBD | Deferred — runs after 19 | - |
| 16. Research Trigger + Progress Bridge | v1.1 | 4/5 | In Progress|  |
| 17. Raw Output + Audit Chain Guard | v1.1 | 1/4 | In Progress|  |
| 18. Human Report Upload + Client Delivery | v1.1 | 0/TBD | Not started | - |
| 19. Q&A Chat (Voyage + Haiku RAG) | v1.1 | 0/TBD | Not started | - |
| 20. Deferred Chores + v1.0 UAT Closure | v1.1 | 0/TBD | Not started | - |
