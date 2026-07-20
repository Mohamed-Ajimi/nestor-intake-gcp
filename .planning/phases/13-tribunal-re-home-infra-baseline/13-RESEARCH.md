# Phase 13: Tribunal Re-home + Infra Baseline - Research

**Researched:** 2026-07-20
**Domain:** Re-homing a self-contained async deep-research engine (Tribunal / `nestor_pulse_sdk`) into the live intake GCP project — Cloud Run services + isolated `tribunal` schema/Alembic line, audit hash-chain preservation, per-run concurrency lock, one live proof run
**Confidence:** HIGH (grounded directly in the sibling Tribunal source, its deploy scripts, migrations, audit code, unexecuted concurrency plan 01-19, and the intake-side infra)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (code moves into this repo):** `nestor_pulse_sdk` (plus the modules it imports) is COPIED into this repo — suggested location `tribunal/` next to `backend/`. From Phase 13 onward, all Tribunal changes/plans/commits happen in this repo. The old Nestor repo becomes a frozen reference.
  - ⚠️ **RESEARCH CORRECTION — see Assumption A1 / Standard Stack:** CONTEXT says "plus the modules it imports, e.g. the `nestor_pulse.tools.*` deep-researcher imports pulled in by `degraded_parallel.py`." This is **factually wrong for the `tribunal` engine path.** `degraded_parallel.py` imports `nestor_pulse_sdk.tools.{gemini,claude,openai}_adapter` — NOT `nestor_pulse.tools.*`. The ONLY `from nestor_pulse.` import anywhere in the SDK is the ADK arm in `runs/adapter.py` (`ADKRunnerShim`, lazy, `engine="adk"`, out of scope) — enforced by a CI grep gate. See the Copy Manifest below for the ONE real `nestor_pulse` dependency (`nestor_pulse.secrets`).
- **D-02 (old deployment torn down after proof):** Once the E2E proof run is green in the intake project, DELETE the old standalone deployment on `project-cb01b861` (Cloud Run `nestor-pulse-api` + `nestor-pulse-worker`, Cloud SQL `nestor-prod-pg`) to stop cost. Teardown belongs in the runbook as a final, post-proof step. Deliberately departs from the v1.0 "leave legacy untouched" pattern.
- **D-03 (v1.0-style deploys):** Build-by-construction on this machine (no local Python/Docker), operator-run live session: Cloud Build for images, gcloud for deploys, migrations via the established job pattern, every step in a runbook. GCP project "Nestor Pulse", account tools@dotto.be.
- **D-04 (always-on worker accepted):** `tribunal-worker` runs `min-instances=1` + `--no-cpu-throttling`; ~$5–10/mo idle accepted. Runs start within seconds of being queued.
- **D-05 (benchmark proof brief):** The E2E proof run uses a known LUKOIL benchmark brief (see `deep_research_compare/` in the Nestor repo) so output quality is comparable. The intake→brief assembly path is NOT built here (Phase 16).
- **D-06 (all three providers, existing Gemini key):** Anthropic + OpenAI + Gemini all enabled day one. Intake project already holds Anthropic/OpenAI secrets; the GEMINI/GOOGLE_API_KEY is REUSED from the old Tribunal project — reseed it as a secret in the intake project during the live session.
- **D-07 (uncapped in Phase 13):** `NESTOR_TRIBUNAL_UNCAPPED=1` stays ON for Phase 13 proof runs. Budget-cap enforcement + stale-reclaim calibration are Phase 16. Phase 13 only RECORDS measured run duration and cost.
- **D-08 (5+ concurrent target):** Production sizing target is 5+ simultaneous runs from different spaces. The phase's proof test is ≥2 concurrent runs (per ENGINE-08), but the locking design and worker sizing must not cap out below ~5 (may mean multiple worker instances or per-instance run concurrency — builder decides the mechanism; validate the advisory lock under the target, not just the minimum).
- **D-09 (audit retention mirrors old):** The new audit-evidence GCS bucket mirrors the OLD deployment's retention configuration (designed against the EU AI Act requirement — no new legal analysis). Document the mirrored value in the runbook. **Verified value: 7-year per-object retention, `mode="Unlocked"`, NOT Bucket Lock** (`audit/gcs_blob.py`).
- **D-10 (deadline best-effort):** Completing before EU AI Act Art. 12 enforcement (2026-08-02) is best-effort, not a hard commitment. The `verify_chain` green gate itself remains MANDATORY for phase completion regardless of date.

### Claude's Discretion
- Cloud SQL database/schema naming and sizing details ("database naming/sizing details = builder discretion").
- Exact repo layout for the copied code (`tribunal/` top-level suggested, not mandated), what subset of the Nestor repo comes along (follow the import graph), whether git history is preserved (plain copy acceptable).
- Worker concurrency mechanism for the 5+ target (multiple instances vs per-instance concurrency), service naming, region (match backend: `europe-west1`), CPU/memory sizing.
- How the benchmark brief is injected for the proof run (direct `POST /api/runs` with a hand-built brief expected — no intake integration exists yet).
- KEEP `tenant_id` naming and the frozen audit payload byte-identical (renaming breaks the legal hash-chain) — structural constraint, not a user question.

### Deferred Ideas (OUT OF SCOPE)
- Budget-cap value ($5 vs higher) + stale-reclaim calibration — Phase 16 (ENGINE-03), using the duration/cost measured by this phase.
- GUC/isolation unification across `nestor` + `tribunal` schemas — not planned.
- Old Nestor repo archival/cleanup (beyond freezing) — post-milestone housekeeping.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ENGINE-01 | Tribunal API + worker run as Cloud Run services in the intake GCP project, with a `tribunal` schema on the shared Cloud SQL instance and Tribunal's own Alembic line intact | Standard Stack (copy manifest, pinned deps), Architecture Patterns (Alembic `version_table` + schema isolation), Deploy shape (retargeted deploy-api/worker scripts). Alembic env.py currently sets NO `version_table`/schema → tables land in `public` today; the re-home MUST set `version_table="tribunal_alembic_version"` + a `tribunal` schema/search_path. |
| ENGINE-02 | One real research run completes end-to-end green on the new deployment before dependent features build on it | `run_tribunal_smoke.py` + `test_tribunal_e2e.py` are ready-made proof vehicles (in-process TribunalPipeline run against live Cloud SQL; assert output + claims + claim_source + chain-verify + recall). D-05 LUKOIL brief. Record duration+cost for Phase 16 stale calibration. |
| ENGINE-04 | Tamper-evident audit hash-chain verifies green (`verify_chain`) after the move — blocking gate before 2026-08-02 | `audit/hash_chain.py` `_payload_for_row` frozen field set (incl. `tenant_id`, `gcs_uri`); `verify_chain_endpoint`; `GET /api/audit/verify/{run_id}`. Preserve payload byte-identical; carry/re-seed GCS bucket with 7y `Unlocked` retention. |
| ENGINE-08 | Multiple runs from different spaces run concurrently without interference — per-run audit-chain advisory lock (completing Tribunal's unexecuted plan 01-19), proven by ≥2 simultaneous runs from different spaces | Concurrency section: plan 01-19 is a MUCH larger design than ENGINE-08 needs. Extract ONLY the keystone (per-run `pg_advisory_xact_lock` 64-bit + claimable-set guard). The full Pub/Sub+Eventarc+Jobs+reaper re-architecture is explicitly OUT OF SCOPE per REQUIREMENTS.md. |
</phase_requirements>

## Summary

Phase 13 is a **lift-and-shift of a working async engine**, not engine-building. The Tribunal engine (`nestor_pulse_sdk`) already runs a complete 9-stage skeptic/synthesis pipeline with a tamper-evident audit hash-chain, an always-on SKIP-LOCKED poll worker, and a REST API. It is currently deployed standalone on `project-cb01b861` against its own `nestor-prod-pg` Cloud SQL instance. This phase re-homes it into the intake "Nestor Pulse" GCP project as two Cloud Run services (`tribunal-api` + `tribunal-worker`), puts its tables in an isolated `tribunal` schema on the shared intake Cloud SQL instance via its own separate Alembic `version_table`, verifies the audit chain survives the move, adds the one missing concurrency primitive (a per-run advisory lock), and proves one real research run green end-to-end.

The four hardest structural facts, all verified in source: (1) the two repos have **identical Alembic revision IDs `0001`–`0010`** in both lines — the tribunal line MUST use a separate `alembic_version` table and land in a `tribunal` schema, never merge; (2) Tribunal's migration 0008 and its worker role hardcode **`SCHEMA public`** in every GRANT/POLICY — moving to a `tribunal` schema needs a `search_path`/schema-qualification strategy; (3) the audit hash-chain's `_payload_for_row` hashes `tenant_id` and `gcs_uri` **verbatim** — renaming the tenant column or repointing the GCS bucket without carrying objects breaks the legal chain; (4) the unexecuted concurrency plan 01-19 is a full Pub/Sub+Eventarc+Cloud-Run-Jobs re-architecture that is **explicitly out of scope** (REQUIREMENTS.md) — ENGINE-08 needs only its *keystone*, the per-run `pg_advisory_xact_lock`.

**Primary recommendation:** Copy `nestor_pulse_sdk/` + `nestor_pulse/secrets.py` (the only real cross-package dependency on the tribunal path) into `tribunal/`, keep Tribunal's Python 3.11.9 / asyncpg / password-based-DATABASE_URL image completely separate from the intake 3.12 / pg8000 / IAM-auth image, migrate into an isolated `tribunal` schema with `version_table="tribunal_alembic_version"`, extract ONLY the 64-bit per-run advisory lock from plan 01-19 into `execute_run`, and drive the D-05 LUKOIL proof run with the ready-made `run_tribunal_smoke.py`. Do NOT port the Pub/Sub/Jobs re-architecture.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Research run execution | Tribunal Worker (Cloud Run, always-on) | — | Runs are minutes→~1h; must never run in an HTTP request (Cloud Run timeout). SKIP-LOCKED queue over `tribunal.run`. |
| Run creation / status / report | Tribunal API (Cloud Run) | — | FastAPI `POST /api/runs`, `GET /api/runs/{id}/metrics`, `GET /api/runs/{id}/report`. Internal-only in later phases; for Phase 13 proof, reachable by operator with a JWT OR driven in-process by the smoke script. |
| Audit hash-chain write + verify | Tribunal (audit/ module, inside worker) | Cloud SQL `tribunal.audit_log` + GCS audit bucket | Chain integrity is single-writer-safe; `verify_chain` recompute is server-side only. |
| Per-run exactly-once locking | Tribunal Worker (Postgres advisory lock) | Cloud SQL | `pg_advisory_xact_lock` over run_id → the DB is the coordination point, not app memory. |
| Schema migration | Cloud Run Migration Job (Tribunal image) | Cloud SQL `tribunal` schema + `tribunal_alembic_version` | Mirrors intake's one-shot migration-Job pattern; keeps Tribunal's Alembic line untouched. |
| Provider LLM calls (Anthropic/OpenAI/Gemini) | Tribunal Worker | Secret Manager (`Nestor_*` secrets) | All egress through `AuditedLLMClient` so the audit chain captures every call. |
| Audit-evidence blob storage | GCS (intake project, new bucket) | — | 7y `Unlocked` per-object retention; `gcs_uri` is inside the hashed payload. |

## Standard Stack

### Core (Tribunal engine — carry over UNCHANGED, its own image)

Grounded in `Nestor/requirements.txt` (all `==`-pinned, resolved on Python 3.11.9). **Do NOT bump to match the intake backend's 3.12 pins — two images, two Python minors, two DB drivers is correct and intentional.**

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python | 3.11-slim | Tribunal runtime | Both Dockerfiles `FROM python:3.11-slim`; requirements resolved on 3.11.9. Intake is 3.12 — keep separate. `[ASSUMED]` (from requirements.txt header, not re-resolved this session) |
| fastapi | 0.136.3 | Tribunal API service | `requirements.txt`; entrypoint `uvicorn nestor_pulse_sdk.server:app`. `[VERIFIED: requirements.txt]` |
| uvicorn | 0.48.0 | ASGI server | `requirements.txt`. `[VERIFIED: requirements.txt]` |
| sqlalchemy[asyncio] | 2.0.50 | Async ORM | `requirements.txt`; `db/base.py` `create_async_engine`. `[VERIFIED: requirements.txt]` |
| asyncpg | 0.31.0 | Postgres async driver | `requirements.txt`. **Divergence:** intake uses pg8000 (sync) + cloud-sql-python-connector. Tribunal connects over the Cloud SQL unix socket (`--add-cloudsql-instances`). `[VERIFIED: requirements.txt]` |
| alembic | 1.18.4 | Tribunal migrations (own line 0001→0010) | `requirements.txt`. Same version as intake — but a SEPARATE migration line. `[VERIFIED: requirements.txt]` |
| anthropic | 0.104.1 | Skeptic loop, Claude deep-research arm, synthesis | `requirements.txt`. Older than intake's 0.113.0; keep the pin in Tribunal's image (server-side web tools `web_search_20250305`/`web_fetch_20250910` are version-sensitive). `[VERIFIED: requirements.txt]` |
| openai | 2.38.0 | OpenAI deep-research arm | `requirements.txt`. `[VERIFIED: requirements.txt]` |
| google-genai | 1.75.0 | Gemini 2.5-flash intake/triage + Gemini deep-research arm | `requirements.txt`; `pipeline/tribunal/intake.py` `_INTAKE_MODEL="gemini-2.5-flash"`. `[VERIFIED: requirements.txt]` |
| google-cloud-secret-manager | 2.28.0 | Pull `Nestor_*` provider secrets at boot | `requirements.txt`; `secrets_bootstrap.py`. `[VERIFIED: requirements.txt]` |
| google-cloud-storage | 2.19.0 | Audit-body upload + `output.gcs_uri` | `requirements.txt`; `audit/gcs_blob.py`. `[VERIFIED: requirements.txt]` |
| jcs | 0.2.1 | JSON canonicalisation (available; chain currently uses stdlib `json.dumps` pinned spec) | `requirements.txt`; `audit/hash_chain.py`. `[VERIFIED: requirements.txt]` |
| structlog | 24.4.0 | Worker/pipeline structured logging | `requirements.txt`. `[VERIFIED: requirements.txt]` |
| tenacity | 9.1.4 | Retry wrapper on provider calls | `requirements.txt`. `[VERIFIED: requirements.txt]` |
| firebase-admin | 6.9.0 | Identity Platform JWT verify (Tribunal's own auth) | `requirements.txt`. **Redundant post-integration** but present in the image; auth retirement is Phase 14, not here — keep for Phase 13 so the JWT-gated proof path works. `[VERIFIED: requirements.txt]` |

### Supporting (heavy deps present but NOT on the tribunal path)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| google-adk | 1.34.1 | ADK engine (`engine="adk"` arm) | ONLY the ADK/`sdk`-A/B arm. The tribunal path never imports it. Kept in `requirements.txt` because it is a transitive/pinned dep; the *worker image* copies `nestor_pulse/` for it, but the tribunal engine does not import `nestor_pulse`. See Copy Manifest. `[VERIFIED: adapter.py CI grep gate]` |
| claude-agent-sdk | 0.2.87 | Present but explicitly REJECTED in the skeptic loop | `skeptic.py` rejects it ("owns its own LLM egress, would bypass the audit hash chain"). Keep pinned; do not remove blindly. `[VERIFIED: requirements.txt + skeptic.py note]` |
| litellm | 1.86.1 | LLM routing shim (transitive to ADK) | Not on the tribunal path. `[VERIFIED: requirements.txt]` |

### The Copy Manifest (D-01 concrete file/dir list)

The engine to copy into `tribunal/`. **Correction to CONTEXT:** the tribunal path is self-contained within `nestor_pulse_sdk` EXCEPT for one module.

| Copy | Source | Why | Confidence |
|------|--------|-----|-----------|
| **Entire `nestor_pulse_sdk/`** | `Nestor/nestor_pulse_sdk/` | The engine. Includes `server.py`, `runs/`, `pipeline/`, `audit/`, `db/`, `alembic/`, `citations/`, `tools/` (the SDK's own `{gemini,claude,openai}_adapter.py`), `secrets_bootstrap.py`, `health.py`. | HIGH `[VERIFIED]` |
| **`nestor_pulse/secrets.py` ONLY** | `Nestor/nestor_pulse/secrets.py` | `secrets_bootstrap.py` (imported by `server.py`, `worker.py`, the smoke script, the E2E test) does `from nestor_pulse.secrets import load_secrets_into_env`. This loader owns `DATABASE_URL`, `AUDIT_GCS_BUCKET`, `UPLOADS_GCS_BUCKET`. **Either copy this one module (+ its own imports — it imports only stdlib `logging`/`os`/`typing`, so it is standalone) OR refactor `secrets_bootstrap.py` to inline the loader.** | HIGH `[VERIFIED]` |
| `requirements.txt` | `Nestor/requirements.txt` | Pinned dep set for the Tribunal image. `google-adk`/`nestor_pulse` deps can be pruned LATER (hardening), not in the lift-and-shift. | HIGH `[VERIFIED]` |
| `infrastructure/cloud-run/{api,worker}/Dockerfile`, `deploy-api.sh`, `deploy-worker.sh`, `build-and-push.sh`, `artifact-registry-create.sh`, `DEPLOY.md` | `Nestor/infrastructure/cloud-run/` | Deploy shape to retarget. **api/Dockerfile does NOT copy `nestor_pulse/`** (comment: "ADK preservation — nestor_pulse/ is NOT copied"). The worker/Dockerfile DOES copy it (for the ADK arm) — but if the ADK arm is not deployed, the worker image only needs `nestor_pulse/secrets.py`. | HIGH `[VERIFIED]` |
| Tests: `tests/test_tribunal_e2e.py`, `test_hash_chain_replay.py`, `test_rls_isolation.py`, `test_async_worker.py` + `pipeline/tribunal` tests | `Nestor/nestor_pulse_sdk/tests/` | Re-home verification assets (see Validation Architecture). | HIGH `[VERIFIED]` |
| `scripts/run_tribunal_smoke.py` | `Nestor/nestor_pulse_sdk/scripts/` | The D-05 proof-run vehicle. | HIGH `[VERIFIED]` |

**Do NOT copy** (out of scope for the tribunal path): `nestor_pulse/` package body beyond `secrets.py` (the ADK arm), `web/` static UI, `orgs/`/`account/`/`projects/` if you also retire auth — but **auth retirement is Phase 14**, so for Phase 13 keep `server.py`'s routers intact so the JWT-gated proof path is reachable. `AWS/`, `deep_research_compare/` (copy only the LUKOIL brief text you need for the proof, or reference it read-only in the sibling repo).

### DB Topology (Claude's discretion — recommendation)

Milestone research (ARCHITECTURE.md Part C) recommends **ONE Cloud SQL instance, `tribunal` schema, Tribunal's own Alembic line**. Phase 13 CONTEXT confirms this ("a `tribunal` schema on the shared Cloud SQL instance"). Two viable sub-options:

| Option | What it requires | Trade-off | Verdict |
|--------|------------------|-----------|---------|
| **Separate SCHEMA (`tribunal`) in the intake `nestor` database** | Set `version_table="tribunal_alembic_version"` + `version_table_schema="tribunal"` in `env.py`; set `search_path=tribunal` for the connection so Tribunal's unqualified `op.create_table("run", …)` and `SCHEMA public` GRANTs/policies land in `tribunal`. | Matches CONTEXT wording exactly. Requires handling migration 0008's hardcoded `SCHEMA public` (see Pitfall 2). | **RECOMMENDED** — matches CONTEXT + one instance to operate |
| Separate DATABASE (`tribunal`) on the same instance | `CREATE DATABASE tribunal`; run Tribunal's Alembic into it unchanged (its unqualified tables land in `public` of the new DB — zero rewrite). | STACK.md's original "Option A." Lowest migration surgery, but does NOT match CONTEXT's "schema" wording and blocks any future cross-schema query. | Acceptable fallback if the `search_path`/0008 schema rewrite proves fragile — flag for planner decision |

**Builder decision point (surface in plan):** "schema" (CONTEXT wording, needs the 0008 `SCHEMA public` fix) vs "separate database" (zero migration rewrite). Both satisfy ENGINE-01. The schema route is preferred for future flexibility; the database route is the lower-risk fallback.

**Installation / build (no local Docker — Cloud Build):**
```bash
# From the copied tribunal/ tree, mirroring the old build-and-push.sh:
gcloud builds submit --tag europe-west1-docker.pkg.dev/$INTAKE_PROJECT/nestor-pulse/tribunal-api:$SHA  --config=... 
gcloud builds submit --tag europe-west1-docker.pkg.dev/$INTAKE_PROJECT/nestor-pulse/tribunal-worker:$SHA --config=...
```

**Version verification:** All versions above are read verbatim from the committed `Nestor/requirements.txt` (pinned `==`, resolved 2026-05-27 on Python 3.11.9). They are `[VERIFIED: requirements.txt]` as the working set of the *currently-live* standalone deployment — NOT re-resolved against PyPI this session (the lift-and-shift explicitly carries the working set unchanged; re-resolving would defeat the purpose and risk a version drift). No new packages are being *selected* in this phase.

## Package Legitimacy Audit

> **Not applicable in the usual sense.** Phase 13 installs **no newly-chosen packages** — it carries an existing, already-deployed, pinned `requirements.txt` verbatim (a lift-and-shift of a working image). Every package below is already running in production on the standalone deployment. slopcheck was not run because (a) no package is being newly selected, and (b) these are the exact pins of a live, working, audited system. If the planner adds a `checkpoint:human-verify` before the first Cloud Build, that is sufficient.

| Package | Registry | Disposition |
|---------|----------|-------------|
| All of `Nestor/requirements.txt` | PyPI | Carried verbatim from the live standalone deployment — no new selection. Pinned `==`. Approved as-is. |
| VOYAGE_API_KEY / voyageai | — | NOT this phase (Q&A chat = Phase 19). |

**Packages removed due to slopcheck [SLOP] verdict:** none (no selection performed).
**Packages flagged as suspicious [SUS]:** none.

## Architecture Patterns

### System Architecture Diagram

```
                         INTAKE GCP PROJECT ("Nestor Pulse", europe-west1)
                         ================================================

  Operator (Phase 13 proof)                     Shared Cloud SQL instance (POSTGRES_16 + pgvector)
        │                                        ┌────────────────────────────────────────────┐
        │  (A) JWT → POST /api/runs              │  schema: nestor   (intake, RLS app.current_space_id,
        │      OR                                │                    pg8000/IAM, alembic_version)
        │  (B) in-process run_tribunal_smoke.py  │  schema: tribunal (Tribunal, RLS app.tenant_id,
        ▼                                        │                    asyncpg/password,
   ┌─────────────┐   internal HTTP (later)       │                    tribunal_alembic_version)
   │ tribunal-api│───────────────┐               │    tables: run, output, audit_log, source,      │
   │ (Cloud Run) │               │               │            claim, claim_source, org, project,    │
   └─────────────┘               │               │            app_user                              │
        │ INSERT run(status=queued)              └────────────────────────────────────────────┘
        ▼                        │                         ▲            ▲
  ┌──────────────────────────────┴────────┐                │            │
  │ tribunal-worker (Cloud Run, always-on)│  claim_one()   │            │ verify_chain
  │  min=1, no-cpu-throttling, t=3600     │  SKIP LOCKED ──┘            │ (audit/hash_chain.py)
  │  worker_loop → execute_run:           │                            │
  │    ┌───────────────────────────────┐  │                            │
  │    │ pg_advisory_xact_lock(run_id) │  │  (NEW — plan 01-19 keystone)│
  │    │ set_tenant_context(tenant_id) │  │                            │
  │    │ TribunalPipeline.run():        │  │  every LLM call →          │
  │    │  intake→research_division→     │──┼──AuditedLLMClient──────────┤
  │    │  deep_research(3 providers)→   │  │   (writes audit_log row +  │
  │    │  distill→verify→adjudicate→    │  │    body to GCS, hash-chain) │
  │    │  coverage→conflict→synthesize  │  │                            ▼
  │    └───────────────────────────────┘  │                   ┌──────────────────────┐
  └───────────────────────────────────────┘                   │ GCS audit bucket     │
        │ providers: Anthropic web_search/web_fetch,           │ 7y Unlocked retention│
        │ OpenAI deep-research, Gemini 2.5-flash               │ (gcs_uri IS hashed)  │
        ▼                                                       └──────────────────────┘
   Secret Manager: Nestor_Claude, Nestor_OpenAI, Nestor_Gemini,
                   DATABASE_URL (app_user), DATABASE_URL_WORKER (worker_user),
                   AUDIT_GCS_BUCKET
```

### Recommended Project Structure (in this repo)
```
tribunal/                       # D-01 copied engine (parallel to backend/)
├── nestor_pulse_sdk/           # the engine (server, runs, pipeline, audit, db, alembic, tools, citations)
│   ├── alembic/                # Tribunal's OWN line (0001..0010) — separate version_table
│   ├── audit/                  # hash_chain.py (FROZEN _payload_for_row), gcs_blob.py, verifier.py
│   ├── db/                     # base.py (async engine), rls.py (app.tenant_id), models/
│   ├── runs/                   # api.py, worker.py, execute.py (NEW — advisory lock), adapter.py, stages.py
│   └── secrets_bootstrap.py    # imports nestor_pulse.secrets (copied below)
├── nestor_pulse/
│   └── secrets.py              # ONLY this module (DATABASE_URL/bucket loader) — the sole cross-dep
├── requirements.txt            # pinned, Python 3.11.9
├── infrastructure/             # retargeted deploy-api.sh / deploy-worker.sh / Dockerfiles / DEPLOY.md
└── ...

infra/                          # intake IaC (extend by construction — new services/secrets/bucket)
infra/DEPLOY-RUNBOOK.md         # extend with the Tribunal re-home + teardown steps
```

### Pattern 1: Isolated Alembic line via separate `version_table` + schema
**What:** Tribunal's `alembic/env.py` currently sets NO `version_table` and NO schema — so `alembic upgrade head` writes `public.alembic_version` and creates unqualified tables in `public`. Both repos share revision IDs `0001`–`0010`, so pointing one process at both lines fails (multiple heads) and running the tribunal line against the intake `alembic_version` silently skips `0001` (same ID).
**When to use:** The re-home migration step (ENGINE-01).
**Example:**
```python
# tribunal/nestor_pulse_sdk/alembic/env.py — add to BOTH configure() calls
# Source: pattern for Alembic multi-tenant version tables (alembic.sqlalchemy.org)
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    version_table="tribunal_alembic_version",   # ← never collides with intake's alembic_version
    version_table_schema="tribunal",             # ← if using the schema option
    compare_type=True,
    include_schemas=True,
)
# AND set the connection search_path so unqualified CREATE TABLE / GRANT land in `tribunal`:
#   await connection.execute(text("SET search_path TO tribunal"))
```

### Pattern 2: Per-run advisory lock (plan 01-19 KEYSTONE ONLY)
**What:** Extract ONLY the exactly-once primitive from the unexecuted plan 01-19 — a transaction-scoped 64-bit Postgres advisory lock keyed on `run_id`, plus an explicit claimable-set re-check. This is the ENGINE-08 deliverable. Do NOT port the rest of 01-19 (see Anti-Patterns).
**When to use:** Wrap the worker's run-execution path so two executors handed the same `run_id` run the engine exactly once, and two DISTINCT runs never serialize on each other.
**Example:**
```sql
-- Source: Nestor plan 01-19 design_decisions (KEYSTONE), verified verbatim
-- 64-bit key (NOT hashtext → that's int4, ~50% birthday collision at ~65k runs):
SELECT pg_advisory_xact_lock(('x' || md5(:run_id))::bit(64)::bigint);
-- then re-check claimable = status='queued' OR (status='running' AND heartbeat/started stale)
-- explicitly NOT claimable: needs_input, needs_report_spec, cancelled, completed, failed
```
**Sizing for D-08 (5+):** Two mechanisms satisfy "5+ concurrent from different spaces":
- **(a) Multiple worker instances** — raise the worker `max-instances` above 1 (currently `min=1/max=1`). The advisory lock + SKIP-LOCKED claim make multiple pollers safe. This is the smallest change from today's single-worker deploy.
- **(b) Per-instance run concurrency** — one worker running N concurrent `execute_run` coroutines.
Either way, the advisory lock is what makes >1 executor safe for the audit chain (it was the reason the old deploy was capped at `max-instances=1`, per plan 01-19 objective and Pitfall 7). Validate under ~5, not just 2 (D-08).

### Pattern 3: One-shot migration Job (mirror intake's pattern)
**What:** The intake side runs migrations via a Cloud Run Job that dials Cloud SQL through the IAM connector when `INSTANCE_CONNECTION_NAME` is set (`backend/app/db/alembic/env.py` `_use_connector`). Tribunal uses asyncpg over the unix socket instead. Build a `tribunal-migrate` Job from the Tribunal image that runs `alembic upgrade head` against the `tribunal` schema.
**When to use:** ENGINE-01 schema creation, before deploying the services.

### Anti-Patterns to Avoid
- **Porting the full plan 01-19 (Pub/Sub + Eventarc + Cloud Run Jobs + reaper + concurrency caps + flag-gated cutover).** REQUIREMENTS.md Out-of-Scope explicitly rejects "Cloud Run Jobs re-architecture for runs — Existing queue + always-on worker already solves timeouts; Jobs would be a rewrite for no gain." ENGINE-08 needs ONLY the advisory-lock keystone. Extract it into `execute.py`; leave the trigger/reaper/caps machinery unbuilt.
- **Renaming `tenant_id` or the audit payload fields.** `_payload_for_row` hashes `tenant_id`, `gcs_uri`, `seq`, `run_id`, token counts, timestamps verbatim. Any rename forks every chain. Keep byte-identical (CONTEXT structural constraint).
- **Repointing the GCS audit bucket without carrying objects / retention.** `audit_log.gcs_uri` (`gs://old-bucket/...`) is inside the hashed payload. Old `gcs_uri`s embed the old bucket name. For a *fresh-start* intake project (empty Tribunal data, per REQUIREMENTS.md "start empty"), there are no old chains to carry — but the NEW bucket must exist with 7y `Unlocked` retention BEFORE the proof run, or the proof run's own chain dangles.
- **Merging the two Alembic lines or the two `alembic_version` tables.** Separate `version_table` always.
- **Forcing Tribunal onto pg8000/IAM auth or Python 3.12.** Keep its asyncpg/password/3.11 image. The two runtimes stay separate (CONTEXT).
- **Setting `app.tenant_id` GUC in an intake (`app.current_space_id`) session, or vice-versa.** They never mix in one transaction — the schema boundary + HTTP seam keeps them apart. (Relevant to later phases; in Phase 13 the engine talks only to `tribunal.*`.)

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exactly-once run execution under concurrency | A custom in-app mutex / status flag | `pg_advisory_xact_lock` (64-bit, txn-scoped) from plan 01-19 | In-process locks don't coordinate across instances; the DB lock does, and auto-releases on commit/rollback/crash. Plan 01-19 already specifies the exact SQL and the hashtext pitfall. |
| Tamper-evident audit chain | Any change to the hashing | The frozen `audit/hash_chain.py` as-is | The chain is legally load-bearing (EU AI Act Art. 12). It works. Copy it byte-identical. |
| Deep-research (search + verify) | Re-adding SerpAPI/SearchAPI/Apify | Tribunal's Anthropic server-side `web_search`/`web_fetch` skeptic loop | Grep-confirmed zero third-party search vendors in Tribunal; it supersedes the legacy stack. |
| Cloud Run worker health/probe | A new HTTP server | `worker.py`'s stdlib `_health_server` on `$PORT` | Already binds a probe endpoint for the no-HTTP background worker. |
| The proof run harness | A new script | `scripts/run_tribunal_smoke.py` (prints recall, cost, chain-verify, IDs) | Purpose-built for exactly this (D-05). Self-provisions org/project/run, cleans up. |
| Schema-scoped migration engine dial | A new connector | Mirror intake's `_use_connector` Job pattern (Tribunal: asyncpg unix socket) | The intake env.py already solves "Job dials Cloud SQL"; replicate the shape for Tribunal. |

**Key insight:** Phase 13 is >90% *carrying working code unchanged* and <10% new code (the advisory lock + env.py version_table + a retargeted runbook). The temptation is to "improve" the engine during the move — resist it. The audit chain and the concurrency lock are the only two integrity-critical seams, and both have a proven design already written (chain live; lock fully specified in 01-19).

## Runtime State Inventory

> This IS a re-home/migration phase. Explicit inventory of runtime state that a file-copy does NOT move.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | Old Tribunal Cloud SQL `nestor-prod-pg` holds dev-round `run`/`audit_log`/`claim`/`org` rows. **REQUIREMENTS.md Out-of-Scope: "Migrating data from Tribunal's dev Cloud SQL — Dev-round data; start empty."** | **None — start empty.** No data migration. The new `tribunal` schema is created fresh by `alembic upgrade head`. Confirmed by CONTEXT D-02 ("data is dev-round only; migration already ruled out of scope"). |
| **Live service config** | Old standalone Cloud Run services `nestor-pulse-api` + `nestor-pulse-worker` on `project-cb01b861`; old Artifact Registry `nestor-pulse` repo; old `nestor-prod-pg` instance (PAUSED between sessions, `activation-policy=NEVER`). | New services deployed fresh in the intake project. **Teardown of the old project's services + instance is a POST-PROOF step (D-02)** — sequence strictly after the E2E proof is green. Belongs in the runbook as the final step. |
| **OS-registered state** | None (no Task Scheduler / cron / launchd — all GCP-managed Cloud Run + Cloud Scheduler; and the Cloud Scheduler reaper from plan 01-19 was never deployed). | None — verified by absence of any scheduler in the old deploy scripts (only `deploy-api.sh`/`deploy-worker.sh` exist; no `deploy-reaper.sh` in the live infra). |
| **Secrets / env vars** | Old project secrets: `Nestor_Claude`, `Nestor_OpenAI`, `Nestor_Gemini`, `DATABASE_URL`, `DATABASE_URL_WORKER`, `IDENTITY_PLATFORM_*`, `AUDIT_GCS_BUCKET`. Intake project already has Anthropic/OpenAI keys **under DIFFERENT secret names** (`nestor-anthropic-api-key`, `nestor-openai-api-key`) than Tribunal expects (`Nestor_Claude`, `Nestor_OpenAI`). | **Reseed provider secrets under the `Nestor_*` names Tribunal's `secrets_bootstrap.py` reads** (OR refactor the bootstrap mapping). Reseed `Nestor_Gemini` (reuse old value, D-06). Create NEW `DATABASE_URL` (app_user) + `DATABASE_URL_WORKER` (worker_user) secrets pointing at the intake instance + `tribunal` schema. Create NEW `AUDIT_GCS_BUCKET` secret/env. |
| **Build artifacts / installed packages** | Old Artifact Registry images; `nestor_pulse_sdk/__pycache__`, `.venv` in the sibling repo (do not copy). | Fresh Cloud Build in the intake project's Artifact Registry. Do NOT copy `__pycache__`/`.venv`/`.pytest_cache` (use `.gcloudignore`). |
| **DB roles** | `worker_user` + `app_user` login roles + `worker_user`'s permissive `*_worker_all` RLS policies (migration 0008). Cloud SQL has **no BYPASSRLS** — 0008 uses the `current_user='worker_user'` policy trick, hardcoded to `SCHEMA public`. | **Create `worker_user` + `app_user` roles on the intake instance out-of-band** (`gcloud sql users create ...`), then run 0008. **Fix 0008's hardcoded `SCHEMA public`** to the `tribunal` schema (or set search_path) — see Pitfall 2. Grant `worker_user` USAGE on `tribunal` only, never `nestor` (isolation firewall). |

**Canonical question answered:** After every file is copied into `tribunal/`, what runtime systems still hold old state? → **Only the old GCP project's services/instance/secrets/bucket (all in `project-cb01b861`), which are intentionally left running until the proof is green, then torn down (D-02). No data migrates (start-empty). The one non-obvious code dependency a copy misses is `nestor_pulse/secrets.py` — copy it or inline it.**

## Common Pitfalls

### Pitfall 1: Alembic revision-ID collision (`0001`–`0010` in BOTH lines)
**What goes wrong:** Both repos ship `0001_baseline_schema.py` … `0010` with identical `revision="0001"` strings. Pointing one env at both → `Multiple head revisions`. Running the tribunal line against the intake `alembic_version` → `0001` is "already applied" and silently skipped → Tribunal tables never created → first run 500s.
**Why it happens:** Both authored from the same GSD template starting at `0001`.
**How to avoid:** `version_table="tribunal_alembic_version"` (+ `version_table_schema="tribunal"`) in `env.py`; never share the `alembic_version` table; keep the two lines physically separate (they already are — separate `alembic/versions/` dirs).
**Warning signs:** `alembic history` shows two `down_revision=None` roots; `alembic upgrade head` errors multiple-heads; or Tribunal tables missing after a "successful" migrate.

### Pitfall 2: Migration 0008 + worker role hardcode `SCHEMA public`
**What goes wrong:** `0008_worker_rls_role.py` does `GRANT ... ON ALL TABLES IN SCHEMA public TO worker_user`, `GRANT USAGE ON SCHEMA public`, `ALTER DEFAULT PRIVILEGES ... IN SCHEMA public`, and `CREATE POLICY {table}_worker_all ON {table}` (unqualified table names → resolve via search_path). If migrations run with `search_path=tribunal` but the GRANT statements say `public`, the worker gets privileges on the WRONG schema and the cross-tenant claim silently matches ZERO rows (documented failure mode in `worker.py`'s `main()`).
**Why it happens:** Tribunal was authored assuming everything lives in `public`.
**How to avoid (choose one, surface in plan):** (a) Set `search_path=tribunal` for the migration connection AND rewrite 0008's literal `public` → `tribunal` (small, mechanical edit in the copied migration); OR (b) use the **separate-database** topology so unqualified `public` is correct in the new DB (zero 0008 edit). This is the strongest argument for the separate-database fallback.
**Warning signs:** Worker deploys, polls, but `claim_one()` never claims (queue drains to zero claims); `run` rows stuck `queued`.

### Pitfall 3: Audit hash-chain breaks on the move (BLOCKING — ENGINE-04)
**What goes wrong:** `_payload_for_row` hashes `provider, model, started_at, duration_ms, prompt/completion/cached_tokens, gcs_uri, seq, tenant_id, run_id` verbatim via a pinned `canonical_json` spec. Four break vectors: (1) renaming `tenant_id`; (2) reshaping any hashed field; (3) the `gcs_uri` pointing at a bucket that doesn't exist / has no retention; (4) `IN_FLIGHT_PLACEHOLDER` rows from a worker killed mid-run (Cloud Run revision swap) → permanent chain break.
**Why it happens:** The chain trades flexibility for tamper-evidence by design — any structural change is a detectable break.
**How to avoid:** Copy `hash_chain.py` byte-identical; do NOT rename `tenant_id`; create the `AUDIT_GCS_BUCKET` with 7y `Unlocked` per-object retention BEFORE the proof run; keep the single-writer invariant OR add the advisory lock before allowing >1 writer (the lock is the ENGINE-08 deliverable, so this aligns); run `verify_chain` (`GET /api/audit/verify/{run_id}` or the smoke script's built-in check) as the hard phase gate.
**Warning signs:** `verify_chain` returns `(False, i)`; `IN_FLIGHT_PLACEHOLDER` ("iiii...") rows after a deploy; `uq_audit_tenant_run_seq` violations.

### Pitfall 4: `needs_report_spec` CHECK constraint — model/DB divergence
**What goes wrong:** The ORM `Run.__table_args__` `ck_run_status` lists only through `needs_input` (stale). But migration **0007 DOES `drop_constraint` + `create_check_constraint` adding `needs_report_spec`** to the live DB. On a FRESH `alembic upgrade head` into the `tribunal` schema, the DB CHECK will be correct (0007 runs). The ORM model is cosmetically stale but harmless (the DB is the enforcer). **No migration gap exists** — the FEATURES.md flag was a false alarm resolvable by inspection: 0007 already fixes the DB.
**Why it happens:** The ORM `CheckConstraint` literal was never updated after 0007 (a known housekeeping item — plan 01-19 Task 1 even calls it out: "reconcile the SQLAlchemy run.py CheckConstraint … no DB change needed; 0007 already did it").
**How to avoid:** Optionally sync the ORM literal to match 0007 for cleanliness (a 1-line edit), but it is NOT a blocker. Verify with `\d run` on the migrated `tribunal` schema that the CHECK includes `needs_report_spec`.
**Warning signs:** None functional — the DB accepts `needs_report_spec` regardless. Only `alembic check` (autogenerate) would flag the ORM/DB drift.

### Pitfall 5: Two Python runtimes / DB drivers / auth models collide if unified
**What goes wrong:** Intake uses pg8000 (sync) + Cloud SQL IAM auth (the runtime SA IS the DB user, no password). Tribunal uses asyncpg + password-based `DATABASE_URL`/`DATABASE_URL_WORKER` secrets over the unix socket. Trying to make Tribunal use IAM auth or pg8000 breaks its engine (`db/base.py` `create_async_engine` needs `postgresql+asyncpg://`).
**Why it happens:** The two systems were built independently with different DB access patterns.
**How to avoid:** Keep Tribunal's password-based asyncpg path. Create `app_user`/`worker_user` as **built-in Cloud SQL users with passwords** (not IAM users), compose `DATABASE_URL` with the unix-socket host (`postgresql+asyncpg://app_user:PW@/DBNAME?host=/cloudsql/PROJECT:REGION:INSTANCE`), store in Secret Manager. This is exactly the old deploy shape — just retargeted to the intake instance.
**Warning signs:** asyncpg connection errors; the worker binding `app_user` instead of `worker_user` (the `secrets_bootstrap` "Secret Manager values always win" stomp — `worker.py`'s `main()` guards against this; preserve that guard).

### Pitfall 6: IaC drift — new services/secrets/bucket wired manually, not in Terraform
**What goes wrong:** The intake project already carries a documented IaC-drift blocker (STATE.md Phase-5 follow-up): live deploys needed manual steps the committed `infra/*.tf` doesn't apply. Adding two Cloud Run services + 5+ secrets + a bucket + 2 DB roles via drifted IaC will miss wiring → the recurring "deployed but not wired" gap. Terraform apply is blocked on the dev machine anyway (MEMORY).
**How to avoid:** Write the Tribunal re-home as an explicit **runbook** section in `infra/DEPLOY-RUNBOOK.md` (by-construction IaC per v1.0 D-07), enumerating every new secret/env/IAM binding/role. Assume Cloud Build for images, gcloud for deploys. Do NOT rely on `terraform apply`.
**Warning signs:** Worker never claims (missing `DATABASE_URL_WORKER`); audit writes fail (missing bucket / SA GCS role); provider calls 401 (missing `Nestor_*` secrets).

### Pitfall 7: Cloud SQL / worker paused-instance gotchas
**What goes wrong:** The old `nestor-prod-pg` is `activation-policy=NEVER` between sessions. The intake instance is live (v1.0). But the always-on worker (D-04, `min=1`) means the intake instance now carries a permanent poller — confirm the intake instance stays RUNNABLE (it does, v1.0 is live) and that adding a second always-on Cloud Run service doesn't trip connection-pool limits on the shared instance.
**How to avoid:** Confirm the intake Cloud SQL tier's max_connections headroom for the extra worker (Tribunal opens fresh sessions per status write). Document the always-on cost line item (D-04).

## Code Examples

### Verifying the audit chain (the ENGINE-04 gate)
```python
# Source: nestor_pulse_sdk/audit/verifier.py + hash_chain.py (copy byte-identical)
from nestor_pulse_sdk.audit.verifier import verify_chain_endpoint
result = await verify_chain_endpoint(run_id, session)   # {"ok": True, "broken_at": None}
# Exposed as GET /api/audit/verify/{run_id}; the smoke script calls it inline.
```

### The proof-run vehicle (ENGINE-02, D-05)
```bash
# Source: nestor_pulse_sdk/scripts/run_tribunal_smoke.py (self-provisions org/project/run)
# In-process TribunalPipeline run against live Cloud SQL — no HTTP/JWT needed.
# Prints: run_id/tenant_id/project_id, total+grounded claims, recall %, sum(cost_usd), chain ok/broken_at
NESTOR_SDK_ORCHESTRATOR=tribunal python nestor_pulse_sdk/scripts/run_tribunal_smoke.py
# Feed the LUKOIL COMBINED_BRIEF (Nestor/lukoil_questions.py) as the brief for a comparable-quality proof.
# RECORD the wall-clock duration + cost_usd for Phase 16 stale-reclaim calibration (D-07).
```

### The claim query the worker runs (context for the advisory lock)
```sql
-- Source: nestor_pulse_sdk/runs/worker.py CLAIM_SQL (SKIP LOCKED)
UPDATE run SET status='running', started_at=NOW(), worker_id=:wid
 WHERE id = (SELECT id FROM run
              WHERE status='queued'
                 OR (status='running' AND started_at < NOW() - make_interval(mins => :stale))
              ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
 RETURNING id, tenant_id, project_id, engine, brief;
-- The advisory lock wraps execute_run AFTER this claim, keyed on the claimed run_id.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Tribunal standalone on `project-cb01b861` + `nestor-prod-pg` | Re-homed into intake project, `tribunal` schema on shared instance | Phase 13 | One project to operate; teardown old (D-02) |
| Single worker `max-instances=1` (T-14-02 gap forced it) | Advisory-lock `execute_run` allows >1 executor safely | Phase 13 (ENGINE-08) | 5+ concurrent runs (D-08) without chain corruption |
| Legacy `run-research.ts` (SerpAPI/SearchAPI/Apify) | Tribunal (Anthropic server-side web_search/web_fetch + skeptic loop) | v1.1 | Richer, audited, cited pipeline; legacy retired |

**Deprecated/outdated:**
- The full plan 01-19 Pub/Sub+Eventarc+Jobs+reaper design: **superseded/descoped** by REQUIREMENTS.md ("always-on worker already solves timeouts"). Only its advisory-lock keystone survives into Phase 13.
- `NESTOR_TRIBUNAL_UNCAPPED=1`: stays ON for Phase 13 (D-07); flipped OFF in Phase 16 (ENGINE-03).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | CONTEXT D-01's claim that `nestor_pulse.tools.*` is pulled in by `degraded_parallel.py` is FALSE for the tribunal path; the only real `nestor_pulse` dependency is `nestor_pulse.secrets`. | Copy Manifest | If a dynamic/lazy `nestor_pulse` import on the tribunal path was missed, the copied image would `ImportError` at runtime. **Mitigation:** the CI grep gate in `adapter.py` (`grep -rE "from nestor_pulse[. ]" nestor_pulse_sdk/ \| grep -v adapter.py == 0`) is authoritative — but run it against the copied tree before first deploy. MEDIUM. |
| A2 | Python 3.11.9 pins in `requirements.txt` are still the working set (not re-resolved against PyPI this session). | Standard Stack | Low — these are the exact pins of the currently-live standalone deployment. Re-resolving is explicitly avoided (lift-and-shift). LOW. |
| A3 | The intake Cloud SQL instance has connection/tier headroom for a second always-on worker + its per-write asyncpg sessions. | Pitfall 7 | If the shared instance saturates connections under ~5 concurrent runs, the worker errors. **Mitigation:** confirm `max_connections` / tier during the live session; measure under the D-08 concurrency test. MEDIUM. |
| A4 | For a start-empty intake project, there are no pre-existing audit chains/`gcs_uri`s to carry — only the NEW bucket must exist before the proof run. | Anti-Patterns / Pitfall 3 | If any old data were expected to migrate (it is not — REQUIREMENTS.md out-of-scope), old `gcs_uri`s would dangle. Confirmed no migration. LOW. |
| A5 | Reseeding provider secrets under `Nestor_*` names (vs refactoring `secrets_bootstrap.py` to read intake's `nestor-anthropic-api-key`) is the lower-effort path. | Runtime State Inventory | Either works; if the planner prefers not to duplicate secret values, refactor the bootstrap mapping instead. LOW (both valid). |

## Open Questions (RESOLVED)

1. **Schema vs separate-database topology for `tribunal`** — RESOLVED: `tribunal` SCHEMA on the shared intake database (13-02-PLAN.md objective; 0008 `SCHEMA public` → `tribunal` rewrite included; separate-database documented as fallback only).
   - What we know: CONTEXT says "schema"; the schema route needs the 0008 `SCHEMA public` rewrite + search_path; the separate-database route needs zero migration edits.
   - What's unclear: whether the planner/builder prefers CONTEXT-literal "schema" (more future flexibility, small 0008 edit) or the lower-risk separate-database fallback.
   - Recommendation: default to **schema** (matches CONTEXT), with the separate-database route documented as the fallback if the 0008 schema rewrite proves fragile. Surface as a plan decision.

2. **D-08 5+ concurrency mechanism: multiple worker instances vs per-instance concurrency** — RESOLVED: raise worker `max-instances` to 5 (multiple SKIP-LOCKED pollers made safe by the advisory lock; 13-03-PLAN.md objective).
   - What we know: the advisory lock makes either safe; today's deploy is `min=1/max=1`.
   - What's unclear: which the builder prefers (multiple instances is the smaller deploy change; per-instance concurrency is more resource-efficient).
   - Recommendation: raise `max-instances` (multiple pollers) as the simplest change; validate the advisory lock under ~5 concurrent runs from ≥2 spaces (the ENGINE-08 proof test needs only ≥2, but D-08 says design for 5+).

3. **Provider secret naming: reseed `Nestor_*` vs refactor bootstrap** (see A5) — RESOLVED: reseed under the `Nestor_*` names the copied `secrets_bootstrap.py` already reads (no bootstrap refactor; 13-03-PLAN.md objective).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| gcloud CLI | All deploys, secrets, SQL, Cloud Build | ✓ | (MEMORY: available) | — |
| Cloud Build | Building both Tribunal images (no local Docker) | ✓ | (v1.0 pattern) | — |
| Local Python 3.11 / Docker | Running Tribunal tests locally | ✗ | — | Author-by-construction; run tests via Cloud Build (v1.0 pattern), or as an operator live session |
| Terraform apply | IaC | ✗ (blocked, MEMORY) | — | By-construction IaC + runbook (Pitfall 6) |
| Intake Cloud SQL instance | `tribunal` schema host | ✓ (v1.0 live) | POSTGRES_16 | — |
| Intake Artifact Registry | Tribunal images | ✓ / create `nestor-pulse` repo | — | `artifact-registry-create.sh` (idempotent) |
| Old `project-cb01b861` (Gemini key, old bucket ref) | D-06 Gemini reuse; D-02 teardown target | ✓ (until teardown) | — | — |

**Missing dependencies with no fallback:** none block Phase 13 (all live steps are operator-run per D-03).
**Missing dependencies with fallback:** local Python/Docker → Cloud Build + operator session; Terraform → runbook.

## Validation Architecture

> `nyquist_validation: true` in config.json — this section is required.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 + pytest-asyncio 0.26.0 + testcontainers[postgresql] 4.14.2 (Tribunal's own suite; carried in the copy) |
| Config file | `Nestor/pyproject.toml` (pytest config) — carry into `tribunal/` |
| Quick run command | `pytest tribunal/nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` (no live DB needed) |
| Full suite command | Cloud Build job running `pytest tribunal/nestor_pulse_sdk/tests/ -q` (dev machine has no Python — mirror the v1.0 Cloud Build suite pattern) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ENGINE-01 | `tribunal` schema migrated via own `version_table`; tables exist | migration/integration | `alembic upgrade head` (Job) then `\d tribunal.run`; `test_rls_isolation.py` | ✅ (test_rls_isolation.py copied) / ❌ Wave 0 (env.py version_table edit + a schema-isolation assertion) |
| ENGINE-02 | One real run completes green; duration+cost recorded | e2e (live) | `NESTOR_E2E=1 NESTOR_SDK_ORCHESTRATOR=tribunal pytest tribunal/.../test_tribunal_e2e.py -x` OR `run_tribunal_smoke.py` | ✅ (both exist) |
| ENGINE-04 | `verify_chain` green after move | unit + live | `pytest tribunal/.../test_hash_chain_replay.py -x` (offline) + `GET /api/audit/verify/{run_id}` (live) | ✅ (test_hash_chain_replay.py) |
| ENGINE-08 | 2 concurrent runs from different spaces don't interfere; advisory lock exactly-once | concurrency (needs live DB) | `pytest tribunal/.../test_advisory_lock_exactly_once.py -x` | ❌ Wave 0 (the lock + this test are the NEW code — plan 01-19 Task 1 specifies both) |

### Sampling Rate
- **Per task commit:** `pytest tribunal/nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` (fast, offline)
- **Per wave merge:** full Tribunal suite via Cloud Build
- **Phase gate:** live E2E proof run green (`verify_chain` ok) + ≥2-concurrent-run test green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tribunal/nestor_pulse_sdk/alembic/env.py` — add `version_table="tribunal_alembic_version"` (+ schema/search_path) — covers ENGINE-01
- [ ] `tribunal/nestor_pulse_sdk/runs/execute.py` + `tests/test_advisory_lock_exactly_once.py` — the per-run advisory lock + exactly-once test — covers ENGINE-08 (extract KEYSTONE ONLY from plan 01-19 Task 1; do NOT port Tasks 2–6)
- [ ] `nestor_pulse/secrets.py` copied (or `secrets_bootstrap.py` refactored) — else import failure at boot
- [ ] Cloud Build test-suite config for `tribunal/` (dev machine has no Python) — mirror v1.0 pattern
- [ ] A schema-isolation assertion that Tribunal tables landed in `tribunal`, not `public`, and use `tribunal_alembic_version`

## Security Domain

> `security_enforcement` absent in config → enabled. Included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes (partial) | Tribunal API is JWT-gated in Phase 13 (Identity Platform); full internal-only + `InternalCallerProvider` is Phase 14. For Phase 13, either keep JWT gate for the proof OR drive in-process via the smoke script. |
| V3 Session Management | no | No user sessions added this phase. |
| V4 Access Control | yes | RLS: Tribunal `tribunal.*` keyed on `app.tenant_id`; `worker_user` cross-tenant policy scoped to `tribunal` ONLY, never `nestor` (isolation firewall). `set_tenant_context` immediately after claim. |
| V5 Input Validation | yes | Pydantic request schemas (`runs/schemas.py`); brief is free-text prose (no injection surface into SQL — parameterized). |
| V6 Cryptography | yes | Audit hash-chain SHA-256 over pinned canonical JSON — DO NOT hand-roll or alter (`audit/hash_chain.py`). GCS 7y `Unlocked` retention. |
| V7 Error Handling / Logging | yes | structlog; audit_log is the tamper-evident ledger; `verify_chain` is the integrity check. |
| V10 Malicious Code | yes | Secrets never baked into images (Dockerfile T-10.5-01 note); `--set-secrets` at deploy; `LOCAL_DEV_AUTH` dev fallback MUST be OFF in prod (Pitfall 14 in milestone research). |

### Known Threat Patterns for {Tribunal re-home}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant read via `worker_user` granted on `nestor` | Information Disclosure / Elevation | Grant `worker_user` USAGE + DML on `tribunal` schema ONLY; never `nestor`. Verify with a cross-tenant denial test. |
| Audit chain forged/broken by rename or bucket repoint | Tampering / Repudiation | Freeze `_payload_for_row`; keep `tenant_id`/`gcs_uri` byte-identical; `verify_chain` hard gate; single-writer OR advisory lock. |
| Two executors double-run one run → forked chain + double spend | Tampering / DoS(cost) | `pg_advisory_xact_lock(run_id)` 64-bit + claimable-set guard (ENGINE-08 keystone). |
| Uncapped run burns unbounded provider spend | DoS (cost) | Accepted for Phase 13 (D-07 `UNCAPPED=1`); enforcement is Phase 16. RECORD cost. Practical exposure low (no client-facing runs yet, D-10). |
| Secrets baked into image / logged | Information Disclosure | `--set-secrets` at deploy; never echo; `.gcloudignore` excludes `.env`/`__pycache__`. |
| `LOCAL_DEV_AUTH=1` / GCS file-fallback leaks into prod | Tampering (audit) | Ensure `LOCAL_DEV_AUTH != 1` and real `AUDIT_GCS_BUCKET` in prod config (else audit bodies write to local disk → breaks the legal chain). |

## Sources

### Primary (HIGH confidence — read directly this session)
- `Nestor/nestor_pulse_sdk/` — `alembic/env.py` + `alembic.ini` (no version_table/schema set today); `alembic/versions/0001,0007,0008` (revision-ID collision, `needs_report_spec` CHECK add, `SCHEMA public` hardcode); `audit/hash_chain.py` (frozen `_payload_for_row`, `canonical_json`, IN_FLIGHT_PLACEHOLDER), `audit/verifier.py`, `audit/gcs_blob.py` (7y Unlocked retention, `nestor-audit-prod` default); `db/base.py` (async engine, "single schema" note), `db/rls.py` (`app.tenant_id`, SET LOCAL true); `runs/worker.py` (CLAIM_SQL SKIP LOCKED, execute_run body, worker_user URL guard, health server), `runs/adapter.py` (dispatch_runner, ADK-only nestor_pulse import + CI grep gate), `runs/api.py`, `db/models/run.py` (stale ORM CHECK vs 0007), `secrets_bootstrap.py` (Nestor_* mapping, imports `nestor_pulse.secrets`), `pipeline/deep_researchers/degraded_parallel.py` (imports `nestor_pulse_sdk.tools.*_adapter`, NOT `nestor_pulse`), `tests/test_tribunal_e2e.py`, `scripts/run_tribunal_smoke.py`
- `Nestor/nestor_pulse/secrets.py` — owns DATABASE_URL/AUDIT_GCS_BUCKET/UPLOADS_GCS_BUCKET (the sole cross-package dep)
- `Nestor/infrastructure/cloud-run/DEPLOY.md` + `deploy-api.sh` + `deploy-worker.sh` + `api/Dockerfile` + `worker/Dockerfile` — deploy shape, flags (min=1/max=1, no-cpu-throttling, timeout=3600), secrets, teardown/pause pattern
- `Nestor/.planning/phases/01-production-foundation/01-19-PLAN.md` — the unexecuted concurrency plan; advisory-lock KEYSTONE (64-bit `pg_advisory_xact_lock`, hashtext pitfall, claimable set) + the full Pub/Sub/Jobs re-architecture (out of scope)
- `Nestor/requirements.txt` — pinned Python 3.11.9 dep set
- `Nestor/lukoil_questions.py` + `deep_research_compare/` — D-05 proof brief family
- Intake: `backend/app/db/alembic/env.py` (`_use_connector` Job pattern, `include_schemas`), `infra/main.tf` (POSTGRES_16, IAM DB auth, runtime SA IAM user, secret-scoped accessor), `infra/DEPLOY-RUNBOOK.md` (Cloud Build + secret hygiene + IaC-drift note)
- `.planning/research/{SUMMARY,STACK,ARCHITECTURE,PITFALLS}.md` — v1.1 milestone research (grounds this phase)
- `.planning/STATE.md`, `.planning/REQUIREMENTS.md`, CONTEXT.md, MEMORY.md

### Secondary (MEDIUM confidence)
- Alembic `version_table`/`version_table_schema` multi-line pattern (alembic.sqlalchemy.org cookbook) — standard mechanism, `[CITED]`
- EU AI Act Art. 12 enforcement date 2026-08-02 (`Engine_Decision_Business_Brief.md`, referenced not re-read this session)

## Metadata

**Confidence breakdown:**
- Standard stack / copy manifest: HIGH — read `requirements.txt`, Dockerfiles, and the actual import graph incl. the CI grep gate (corrects the CONTEXT `nestor_pulse.tools` assumption)
- Architecture (Alembic isolation, advisory lock, deploy shape): HIGH — read env.py, migrations 0001/0007/0008, worker.py, plan 01-19, both deploy scripts
- Audit chain preservation: HIGH — read hash_chain.py/verifier.py/gcs_blob.py directly (frozen payload + 7y Unlocked retention confirmed)
- Concurrency scope: HIGH — plan 01-19 read in full; REQUIREMENTS.md confirms Jobs re-architecture is out of scope, only the keystone applies
- DB topology (schema vs database): MEDIUM — both viable; CONTEXT wording favors schema, 0008 `SCHEMA public` hardcode is the deciding wrinkle (surfaced as Open Question 1)

**Research date:** 2026-07-20
**Valid until:** ~2026-08-20 (stable — lift-and-shift of pinned, already-live code; the only time-sensitive item is the 2026-08-02 Art. 12 date, which is best-effort per D-10)
