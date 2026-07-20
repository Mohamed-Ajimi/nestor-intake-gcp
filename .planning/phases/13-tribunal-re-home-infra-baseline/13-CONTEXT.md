# Phase 13: Tribunal Re-home + Infra Baseline - Context

**Gathered:** 2026-07-20
**Status:** Ready for planning

<domain>
## Phase Boundary

The Tribunal deep-research engine (currently in the sibling repo
`C:\Users\ajimimo\Desktop\MOELD\Nestor\nestor_pulse_sdk\`) runs live in the intake GCP project
("Nestor Pulse") as two Cloud Run services (`tribunal-api` + always-on `tribunal-worker`), with an
isolated `tribunal` schema on the shared Cloud SQL instance migrated by Tribunal's own Alembic line
(separate `alembic_version` — no revision-ID collision with the intake `nestor` line). Before any
feature code depends on it:

1. The tamper-evident audit hash-chain verifies green (`verify_chain`) on the re-homed deployment —
   EU AI Act Art. 12 gate (ENGINE-04).
2. The per-run audit-chain advisory lock is in place (completing Tribunal's unexecuted concurrency
   plan 01-19) and ≥2 simultaneous runs from different spaces complete without interference
   (ENGINE-08) — production target is 5+ concurrent runs.
3. One real research run (known benchmark brief) completes end-to-end green, and its measured
   duration is recorded for later stale-run-reclaim calibration (ENGINE-02).

Requirements: ENGINE-01, ENGINE-02, ENGINE-04, ENGINE-08.

**Out of scope for this phase:** intake→Tribunal triggering (Phase 16), auth retirement /
InternalCallerProvider (Phase 14), engine enhancements (Phase 15), any client-facing surface,
cost-cap enforcement (Phase 16 / ENGINE-03 — runs stay uncapped in this phase).

</domain>

<decisions>
## Implementation Decisions

### Code home & repo strategy
- **D-01 (code moves into this repo):** `nestor_pulse_sdk` (plus the modules it imports, e.g. the
  `nestor_pulse.tools.*` deep-researcher imports pulled in by `degraded_parallel.py`) is COPIED into
  this repo — suggested location: a top-level `tribunal/` directory next to `backend/`. From
  Phase 13 onward, all Tribunal changes, plans, and commits happen in this repo. The old Nestor repo
  becomes a frozen reference (no further development there).
- **D-02 (old deployment torn down after proof):** Once the Phase 13 E2E proof run is green in the
  intake project, the old standalone deployment on `project-cb01b861` (Cloud Run `nestor-pulse-api`
  + `nestor-pulse-worker`, Cloud SQL `nestor-prod-pg`) is DELETED to stop all cost. Its data is
  dev-round only (migration already ruled out of scope). NOTE: this deliberately departs from the
  v1.0 "leave legacy untouched" pattern (D-08) — the user chose teardown explicitly. Teardown steps
  belong in the deploy runbook as a final, post-proof step.

### Deploy posture & costs
- **D-03 (v1.0-style deploys):** Build-by-construction on this machine (no local Python/Docker),
  then an operator-run live session: Cloud Build for images, gcloud for deploys, migrations via the
  established job pattern, every step in a runbook. GCP project "Nestor Pulse", account
  tools@dotto.be — same as v1.0 phases 5–12.
- **D-04 (always-on worker accepted):** `tribunal-worker` runs with `min-instances=1`
  (+ no-cpu-throttling per the old deploy scripts); ~$5–10/mo idle cost accepted. Runs start within
  seconds of being queued.

### Proof run & provider keys
- **D-05 (benchmark proof brief):** The E2E proof run uses a known benchmark brief from the old
  deployment's runs (LUKOIL benchmark family — see `deep_research_compare/` in the Nestor repo) so
  output quality is comparable against known results, isolating deployment issues from
  research-quality issues. The intake→brief assembly path is NOT built here (Phase 16).
- **D-06 (all three providers, existing Gemini key):** Anthropic + OpenAI + Gemini all enabled from
  day one (full ≥2-of-3 degradation headroom). The intake project already holds Anthropic/OpenAI
  secrets; the GEMINI/GOOGLE_API_KEY is REUSED from the old Tribunal project — reseed it as a
  secret in the intake project during the live session.
- **D-07 (uncapped in Phase 13):** `NESTOR_TRIBUNAL_UNCAPPED=1` stays ON for Phase 13 proof runs
  (user: "uncap for now"). Budget-cap enforcement + stale-reclaim calibration are Phase 16
  (ENGINE-03). Phase 13 only RECORDS the measured run duration and cost.

### Concurrency & audit gate
- **D-08 (5+ concurrent target):** Production sizing target is 5+ simultaneous runs from different
  spaces. The phase's proof test is ≥2 concurrent runs (per ENGINE-08), but locking design and
  worker sizing must not cap out below ~5 (may mean multiple worker instances or per-instance run
  concurrency — planner/researcher decide the mechanism; validate the advisory lock under the
  target, not just the minimum).
- **D-09 (audit retention mirrors old):** The new audit-evidence GCS bucket in the intake project
  mirrors the OLD deployment's retention configuration (it was designed against the EU AI Act
  requirement — no new legal analysis). Document the mirrored value in the runbook.
- **D-10 (deadline best-effort):** Completing Phase 13 before EU AI Act Art. 12 enforcement
  (2026-08-02) is best-effort, not a hard commitment — practical exposure is low because no
  client-facing research runs exist until later phases. The `verify_chain` green gate itself
  remains MANDATORY for phase completion regardless of date.

### Claude's Discretion
- Cloud SQL database/schema naming and sizing details (user delegated: "database naming/sizing
  details = builder discretion").
- Exact repo layout for the copied code (`tribunal/` top-level suggested, not mandated), what
  subset of the Nestor repo must come along (follow the import graph), and whether git history is
  preserved (plain copy is acceptable).
- Worker concurrency mechanism for the 5+ target (multiple instances vs per-instance concurrency),
  service naming, region (match backend: europe-west1), CPU/memory sizing.
- How the benchmark brief is injected for the proof run (direct `POST /api/runs` with a hand-built
  brief is expected — no intake integration exists yet).
- KEEP `tenant_id` naming and the frozen audit payload byte-identical (research: renaming breaks
  the legal hash-chain) — structural constraint, not a user question.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### v1.1 research (fresh, 2026-07-20 — grounds this whole phase)
- `.planning/research/SUMMARY.md` — consolidated findings + 7-phase spine; Phase 13 flags
- `.planning/research/STACK.md` — Tribunal deps (pinned, Py 3.11.9), new GCP resources, secrets
  inventory, DB topology recommendation (separate DB/schema on shared instance)
- `.planning/research/ARCHITECTURE.md` — Tribunal API/run lifecycle/tables, `worker_user` role +
  RLS re-scoping, GUC conventions (`app.tenant_id` vs `app.current_space_id`), deploy shape
- `.planning/research/PITFALLS.md` — Alembic revision-ID collision, GUC/schema mismatch, audit
  hash-chain fragility (frozen `canonical_json` payload, single-worker-safe, GCS retention in
  hashed payload), stale-reclaim double-run trap, paused-instance gotchas
- `.planning/research/FEATURES.md` — Tribunal capability inventory + dev-state gaps (unconfirmed
  E2E, `needs_report_spec` status-CHECK migration gap in `db/models/run.py:103` vs `worker.py:159`)

### Tribunal source (sibling repo — the code being copied in)
- `C:\Users\ajimimo\Desktop\MOELD\Nestor\nestor_pulse_sdk\` — the engine (server.py, runs/worker.py,
  pipeline/tribunal/*, audit/, db/, alembic/)
- `C:\Users\ajimimo\Desktop\MOELD\Nestor\infrastructure\cloud-run\DEPLOY.md` + `deploy-api.sh` /
  `deploy-worker.sh` / `worker/Dockerfile` — the old deploy shape to replicate (incl.
  min-instances/no-cpu-throttling flags) and the teardown target (D-02)
- `C:\Users\ajimimo\Desktop\MOELD\Nestor\.planning\STATE.md` — Tribunal dev-state: unexecuted
  concurrency plan 01-19, pending verify steps, `NESTOR_TRIBUNAL_UNCAPPED` semantics (D-15)
- `C:\Users\ajimimo\Desktop\MOELD\Nestor\Engine_Decision_Business_Brief.md` — why the audit chain
  is legally load-bearing (EU AI Act Art. 12, 2026-08-02)
- `C:\Users\ajimimo\Desktop\MOELD\Nestor\deep_research_compare\` — LUKOIL benchmark family briefs +
  known outputs for the D-05 proof run

### Intake-side infra patterns (this repo)
- `infra/DEPLOY-RUNBOOK.md` — the operational runbook this phase extends (Tribunal services,
  secrets, migration job, teardown steps)
- `infra/*.tf` — IaC updated by construction (v1.0 D-07 pattern) to describe the new services
- `backend/Dockerfile` — multi-stage uv image pattern reference (note: Tribunal pins Python 3.11.9
  + asyncpg — keep its own image, do NOT force-align with backend 3.12/pg8000)
- `.planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-CONTEXT.md` — v1.0 deploy
  decisions carried forward (run.app URLs, manual runbook deploys, by-construction IaC)

### Requirements & roadmap
- `.planning/ROADMAP.md` § Phase 13 — goal + 4 success criteria
- `.planning/REQUIREMENTS.md` — ENGINE-01, ENGINE-02, ENGINE-04, ENGINE-08

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Old Tribunal deploy scripts (`infrastructure/cloud-run/` in the Nestor repo) — service flags,
  Dockerfiles, and runbook steps to replicate in the intake project.
- Intake deploy machinery — Cloud Build image builds, gcloud deploy conventions, migration-job
  pattern, `infra/DEPLOY-RUNBOOK.md` structure (v1.0 phases 2/12).
- Tribunal's own test suite (`nestor_pulse_sdk/tests/`) — runs against the engine; candidates for
  the re-home verification (note dev machine can't run Python — Cloud Build pattern from v1.0).

### Established Patterns
- Two runtimes stay separate: Tribunal image (Python 3.11.9, asyncpg, pinned requirements.txt)
  and intake image (Python 3.12, pg8000). Do not merge or re-pin.
- Tribunal RLS keys on `app.tenant_id` GUC + `worker_user` elevated role with per-run re-scoping;
  intake RLS keys on `app.current_space_id`. They coexist in separate schemas and never mix in one
  transaction — GUC unification is explicitly NOT this phase.
- Cloud SQL access via IAM connector; secrets via Secret Manager; `europe-west1` region.
- Live validation is operator-run UAT (dev machine has no Python/Docker; gcloud available;
  Terraform apply blocked — by-construction IaC + runbook).

### Integration Points
- Shared Cloud SQL instance gains a `tribunal` database/schema + `worker_user`-style role +
  Tribunal's own `alembic_version` table.
- New GCP resources: 2 Cloud Run services, audit-evidence GCS bucket (retention mirrored, D-09),
  provider secrets (reseeded Gemini + reuse Anthropic/OpenAI), service account(s) per least
  privilege.
- No intake-backend code changes in this phase — the proof run is driven by direct API calls, not
  the intake app.

</code_context>

<specifics>
## Specific Ideas

- "Uncap for now" — the user explicitly wants Phase 13 proof runs unconstrained by the budget cap;
  enforcement is a Phase 16 concern.
- Teardown of the old project is a cost decision — the user picked it over the v1.0
  leave-it-untouched philosophy; sequence it strictly AFTER the proof run is green.
- 5+ concurrency is an ambition statement about real multi-client operation, not just a test
  criterion — don't build a lock that only works for 2.

</specifics>

<deferred>
## Deferred Ideas

- **Budget-cap value ($5 vs higher) + stale-reclaim calibration** — Phase 16 (ENGINE-03), using
  the duration/cost measured by this phase's proof run.
- **GUC/isolation unification across `nestor` + `tribunal` schemas** — not planned; revisit only
  if a future phase needs cross-schema queries.
- **Old Nestor repo archival/cleanup** (beyond freezing) — post-milestone housekeeping.

</deferred>

---

*Phase: 13-Tribunal Re-home + Infra Baseline*
*Context gathered: 2026-07-20*
