# Phase 13: Tribunal Re-home + Infra Baseline - Pattern Map

**Mapped:** 2026-07-20
**Files analyzed:** 14 (8 bulk-copied dirs/files + 6 new/modified)
**Analogs found:** 6 / 6 new-or-modified files (bulk-copied files use the sibling repo as their source, not a this-repo analog)

> **Read this first (phase shape):** Phase 13 is >90% a *file-copy* of the sibling Tribunal engine
> (`C:\Users\ajimimo\Desktop\MOELD\Nestor\nestor_pulse_sdk\`) into a new top-level `tribunal/`
> directory. For those COPIED files the "analog" is literally the source file in the sibling repo —
> copy byte-identical, do NOT re-excerpt or rewrite them (the audit hash-chain and pinned deps are
> integrity-critical). The valuable *this-repo* analogs are the **intake-side infra patterns**
> (runbook, Terraform, migration Job, Cloud Build, alembic env.py) that the ~10% of NEW code must
> replicate/extend. This map focuses its excerpts there.

---

## File Classification

### A. Bulk-copied engine (source = sibling repo; copy verbatim, no this-repo analog)

| New File (in `tribunal/`) | Role | Data Flow | Source (sibling repo) | Match Quality |
|---------------------------|------|-----------|-----------------------|---------------|
| `tribunal/nestor_pulse_sdk/**` (server, runs, pipeline, audit, db, alembic, tools, citations, secrets_bootstrap) | engine (multi) | event-driven / batch | `Nestor/nestor_pulse_sdk/**` | verbatim-copy |
| `tribunal/nestor_pulse/secrets.py` | config/loader | transform | `Nestor/nestor_pulse/secrets.py` | verbatim-copy (sole cross-package dep) |
| `tribunal/requirements.txt` | config | — | `Nestor/requirements.txt` | verbatim-copy (pinned, Py 3.11.9) |
| `tribunal/nestor_pulse_sdk/audit/hash_chain.py` | service (crypto ledger) | transform | `Nestor/…/audit/hash_chain.py` | **verbatim-copy — FROZEN, do NOT alter (ENGINE-04)** |
| `tribunal/infrastructure/{api,worker}/Dockerfile` | config | — | `Nestor/infrastructure/cloud-run/{api,worker}/Dockerfile` | copy + retarget project/repo |
| `tribunal/…/tests/**`, `scripts/run_tribunal_smoke.py` | test | — | `Nestor/nestor_pulse_sdk/{tests,scripts}/**` | verbatim-copy (proof vehicles) |

### B. New or modified files (have a real this-repo infra analog)

| New/Modified File | Role | Data Flow | Closest Analog (this repo) | Match Quality |
|-------------------|------|-----------|----------------------------|---------------|
| `tribunal/nestor_pulse_sdk/alembic/env.py` (MODIFY: add `version_table` + `tribunal` schema/search_path) | config/migration | batch | `backend/app/db/alembic/env.py` | role-match (different driver: asyncpg vs pg8000) |
| `tribunal/nestor_pulse_sdk/runs/execute.py` (NEW: per-run advisory lock — plan 01-19 KEYSTONE) | service | event-driven | `Nestor/…/runs/worker.py` CLAIM_SQL (SKIP-LOCKED claim) — extend, not copy | partial (new primitive) |
| `tribunal/…/tests/test_advisory_lock_exactly_once.py` (NEW) | test | — | `backend/tests/` integration pattern (via `cloudbuild.test.yaml`) | role-match |
| Tribunal migration Job (`tribunal-migrate` — runbook + IaC) | migration/config | batch | `infra/main.tf` `google_cloud_run_v2_job.migrate` | exact |
| Tribunal images Cloud Build config (`tribunal/cloudbuild*.yaml`) | config | — | `frontend/cloudbuild.yaml` + `cloudbuild.test.yaml` | role-match |
| `infra/DEPLOY-RUNBOOK.md` (EXTEND: Tribunal services/secrets/bucket/roles + teardown) | config/runbook | — | `infra/DEPLOY-RUNBOOK.md` (its own existing Phase-7/9/10/12 sections) | exact (self-extend) |
| `infra/main.tf` (EXTEND by-construction: 2 services, secrets, bucket, DB users) | config/IaC | — | `infra/main.tf` (service/job/secret/bucket/user resources) | exact (self-extend) |

---

## Pattern Assignments

### `tribunal/nestor_pulse_sdk/alembic/env.py` (config/migration, batch) — MODIFY

**Analog:** `backend/app/db/alembic/env.py`
**What to copy:** the *shape* of the online-migration `context.configure(...)` call and the
Job-vs-local connector switch. **What to ADD (new, per RESEARCH Pattern 1 / Pitfall 1):**
`version_table="tribunal_alembic_version"`, `version_table_schema="tribunal"`, `include_schemas=True`,
and a `SET search_path TO tribunal` on the connection so unqualified `op.create_table(...)` and
migration-0008's `SCHEMA public` GRANTs land in `tribunal`.

**Analog `configure` pattern** (`backend/app/db/alembic/env.py:126-134`) — note it already sets
`compare_type` + `include_schemas`; Tribunal's version must ADD the two `version_table*` keys:
```python
with connectable.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()
connectable.dispose()
```

**Target shape for Tribunal (ADD the isolation keys — RESEARCH §Pattern 1):**
```python
# tribunal/nestor_pulse_sdk/alembic/env.py — in BOTH offline+online configure() calls
context.configure(
    connection=connection,
    target_metadata=target_metadata,
    version_table="tribunal_alembic_version",   # NEVER collides with intake's alembic_version (Pitfall 1)
    version_table_schema="tribunal",             # schema-option route (CONTEXT wording)
    compare_type=True,
    include_schemas=True,
)
# AND, before run_migrations, so unqualified CREATE TABLE / GRANT / POLICY land in tribunal:
connection.exec_driver_sql("SET search_path TO tribunal")  # asyncpg: await connection.execute(text(...))
```

**Analog's Job-dial switch** (`backend/app/db/alembic/env.py:70-88`) — Tribunal does NOT reuse this
(it uses asyncpg over the unix socket + password `DATABASE_URL`, not the IAM connector). Keep
Tribunal's existing async engine build; the *only* edit is the `configure`/`search_path` block above.
Do NOT force Tribunal onto pg8000/IAM (RESEARCH Pitfall 5).

**Decision to surface (RESEARCH Open Q1):** schema route (above, needs the 0008 `SCHEMA public` →
`tribunal` rewrite) vs separate-database fallback (zero migration edit). Default = schema.

---

### `tribunal/nestor_pulse_sdk/runs/execute.py` (service, event-driven) — NEW

**Analog:** the worker's existing SKIP-LOCKED claim in `Nestor/nestor_pulse_sdk/runs/worker.py`
(`CLAIM_SQL`) — the advisory lock WRAPS this claim; it does not replace it.

**Claim context** (RESEARCH §Code Examples, from `worker.py` CLAIM_SQL) — the run is claimed FOR
UPDATE SKIP LOCKED; the NEW lock is keyed on the returned `run_id`:
```sql
UPDATE run SET status='running', started_at=NOW(), worker_id=:wid
 WHERE id = (SELECT id FROM run
              WHERE status='queued'
                 OR (status='running' AND started_at < NOW() - make_interval(mins => :stale))
              ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
 RETURNING id, tenant_id, project_id, engine, brief;
```

**New primitive to add (plan 01-19 KEYSTONE ONLY — RESEARCH §Pattern 2 / Don't-Hand-Roll):**
```sql
-- 64-bit key (NOT hashtext → int4, ~50% birthday collision at ~65k runs):
SELECT pg_advisory_xact_lock(('x' || md5(:run_id))::bit(64)::bigint);
-- then re-check claimable = status='queued' OR (status='running' AND heartbeat/started stale)
-- explicitly NOT claimable: needs_input, needs_report_spec, cancelled, completed, failed
```

**Anti-pattern guard (RESEARCH §Anti-Patterns):** extract ONLY the lock keystone into
`execute.py`. Do **NOT** port plan 01-19's Pub/Sub + Eventarc + Cloud Run Jobs + reaper + caps
(REQUIREMENTS.md out-of-scope). Set-tenant-context (`app.tenant_id` GUC) immediately after claim,
before the pipeline runs (`db/rls.py` `SET LOCAL`).

**Sizing (D-08, 5+):** simplest mechanism = raise worker `max-instances` above 1; the advisory lock
+ SKIP-LOCKED make multiple pollers safe. Validate under ~5 concurrent from ≥2 spaces, not just the
ENGINE-08 minimum of 2.

---

### `tribunal/…/tests/test_advisory_lock_exactly_once.py` (test) — NEW

**Analog:** the integration-test wiring in `cloudbuild.test.yaml` (real Postgres container + explicit
`DATABASE_URL`, bypassing testcontainers) — Tribunal's suite already uses
`testcontainers[postgresql]`, so the *test* is authored against Tribunal's own conftest, but the
**Cloud Build execution** mirrors this repo's gate.

**Cloud Build gate pattern to replicate** (`cloudbuild.test.yaml:26-86`): start `pgvector/pgvector:pg16`
as a named container on the `cloudbuild` network, `pg_isready`-poll it, then run pytest against it
via a fixed `DATABASE_URL`. A non-zero pytest exit fails the build. For Tribunal use the pinned
`postgres` image its suite expects and run `pytest tribunal/nestor_pulse_sdk/tests/ -q`.

**Assertion intent:** two executors handed the same `run_id` run the engine exactly once; two DISTINCT
runs never serialize on each other; `verify_chain` stays green after concurrent runs.

---

### Tribunal migration Job `tribunal-migrate` (migration/config, batch) — NEW (runbook + IaC)

**Analog:** `infra/main.tf:531-575` `google_cloud_run_v2_job.migrate` (the intake `nestor-migrate` Job).

**Analog IaC pattern** (`infra/main.tf:531-561`) — same image as the service, runtime SA, override
CMD with `alembic upgrade head`, pass non-secret connector env:
```hcl
resource "google_cloud_run_v2_job" "migrate" {
  name     = "nestor-migrate"
  location = var.region
  template {
    template {
      service_account = google_service_account.runtime.email
      containers {
        image = local.image
        args  = ["alembic", "upgrade", "head"]
        env { name = "INSTANCE_CONNECTION_NAME"  value = google_sql_database_instance.main.connection_name }
        env { name = "DB_USER"  value = local.runtime_db_user }
        env { name = "DB_NAME"  value = google_sql_database.app.name }
      }
    }
  }
  depends_on = [ google_sql_database.app, google_sql_user.runtime, … ]
}
```

**Tribunal differences to apply:** name `tribunal-migrate`; image = the Tribunal image (Py 3.11.9);
args `["alembic","upgrade","head"]` but run with `search_path=tribunal` + `DATABASE_URL`
(password/asyncpg, NOT `INSTANCE_CONNECTION_NAME`/IAM); depends on the `tribunal` schema + the
`app_user`/`worker_user` roles existing (RESEARCH §Runtime State Inventory — create roles out-of-band
with `gcloud sql users create` first).

**Runbook execution pattern** (`infra/DEPLOY-RUNBOOK.md:534-538`):
```bash
gcloud run jobs execute nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

---

### Tribunal images Cloud Build config `tribunal/cloudbuild*.yaml` (config) — NEW

**Analog:** `frontend/cloudbuild.yaml` (docker-build + push via config) and `cloudbuild.test.yaml`
(test-suite gate). Use the plain `gcloud builds submit --tag` shape (RESEARCH §Installation) unless a
build-arg is needed; Tribunal's images take no build-time public config, so the simpler tag form works.

**Image build/push pattern** (`frontend/cloudbuild.yaml:24-38`):
```yaml
steps:
  - id: build
    name: "gcr.io/cloud-builders/docker"
    args: [ "build", "-t=${_IMAGE}", "." ]
images:
  - "${_IMAGE}"
options:
  logging: CLOUD_LOGGING_ONLY
timeout: "1200s"
```

**Tribunal build (RESEARCH §Installation)** — two images from the copied `tribunal/` tree, retargeted
to the intake project's `nestor-pulse` Artifact Registry repo:
```bash
gcloud builds submit --tag europe-west1-docker.pkg.dev/$INTAKE_PROJECT/nestor-pulse/tribunal-api:$SHA  …
gcloud builds submit --tag europe-west1-docker.pkg.dev/$INTAKE_PROJECT/nestor-pulse/tribunal-worker:$SHA …
```
Ship a `.gcloudignore` excluding `__pycache__`/`.venv`/`.pytest_cache` (RESEARCH §Runtime State).

---

### `infra/DEPLOY-RUNBOOK.md` (config/runbook) — EXTEND (self-analog)

**Analog:** the runbook's OWN existing phase sections — Phase 7 (secret create + resource-scoped
accessor + out-of-band value seed), Phase 9 (bucket create + IAM), Phase 12 (image rebuild + service
deploy + migration Job execute). Add a new `## Phase 13 — Tribunal re-home` section following the same
idioms. See the Shared Patterns below for the exact idioms to reuse.

**Teardown step (D-02):** append a FINAL, post-proof step that deletes the old
`project-cb01b861` services (`nestor-pulse-api`/`nestor-pulse-worker`) + `nestor-prod-pg` instance —
sequence strictly AFTER the E2E proof run is green.

**IaC-drift note to carry (`infra/DEPLOY-RUNBOOK.md:26-46` idiom):** every new secret/env/IAM
binding/role is enumerated in the runbook because `terraform apply` is blocked on this machine
(RESEARCH Pitfall 6 / MEMORY). By-construction IaC + runbook, gcloud for deploys, Cloud Build for
images.

---

### `infra/main.tf` (config/IaC) — EXTEND by-construction (self-analog)

**Analog:** the existing resource blocks in `infra/main.tf`. Add, mirroring these exact shapes:

- **Cloud Run worker service** (always-on) — mirror `google_cloud_run_v2_service.api`
  (`infra/main.tf:358-403`) but with `min_instance_count = 1` (D-04, vs the intake `= 0`) and
  `cpu_idle = false` (no-CPU-throttling). Scaling block idiom:
  ```hcl
  scaling {
    min_instance_count = 1   # D-04 always-on worker (intake api uses 0)
    max_instance_count = 5   # D-08: size for 5+ concurrent; the advisory lock makes >1 poller safe
  }
  resources { cpu_idle = false }  # no-cpu-throttling (old deploy scripts)
  ```
- **Provider + DB secrets** — mirror the `anthropic_api_key` trio (`infra/main.tf:163-186`): secret
  resource with `replication { auto {} }`, an optional `count = var.x == "" ? 0 : 1` version
  (drift-honest: value seeded out-of-band per runbook), and a resource-scoped
  `secretmanager.secretAccessor` binding to the runtime SA. Apply to `Nestor_Gemini` (reseed, D-06),
  `Nestor_Claude`/`Nestor_OpenAI` (reseed under the names `secrets_bootstrap.py` reads, or refactor
  the mapping — RESEARCH A5), `DATABASE_URL` (app_user), `DATABASE_URL_WORKER` (worker_user),
  `AUDIT_GCS_BUCKET`.
- **Native secret injection** — mirror the `value_source.secret_key_ref { version = "latest" }` env
  blocks (`infra/main.tf:462-493`) for each provider/DB secret on the worker + api services.
- **Audit-evidence GCS bucket** — mirror `google_storage_bucket.uploads` (`infra/main.tf:301-326`)
  + bucket-scoped `storage.objectAdmin` (`:333-337`), but ADD **7-year per-object retention,
  `mode="Unlocked"`, NOT Bucket Lock** (D-09, verified value; `audit/gcs_blob.py`) via a
  `retention_policy`/object-level retention block. `force_destroy = false`.
- **DB users** — mirror `google_sql_user.app_superadmin` (`infra/main.tf:116-121`, `type="BUILT_IN"`
  with generated `random_password`) for `app_user` + `worker_user` (password/asyncpg, NOT IAM —
  RESEARCH Pitfall 5). Grant `worker_user` USAGE/DML on `tribunal` schema ONLY, never `nestor`
  (isolation firewall — RESEARCH §Security Domain).

---

## Shared Patterns

### Secret create + resource-scoped accessor + out-of-band value seed
**Source:** `infra/main.tf:163-186` (Terraform trio) + `infra/DEPLOY-RUNBOOK.md:76-96` (runbook gcloud)
**Apply to:** every new Tribunal secret (`Nestor_Gemini`, `Nestor_Claude`, `Nestor_OpenAI`,
`DATABASE_URL`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET`).
```bash
# create container (empty)  →  scope accessor to runtime SA  →  add VALUE out-of-band (Ctrl-D, never logged)
gcloud secrets create Nestor_Gemini --replication-policy=automatic --project="$GOOGLE_PROJECT"
gcloud secrets add-iam-policy-binding Nestor_Gemini \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"
gcloud secrets versions add Nestor_Gemini --data-file=- --project="$GOOGLE_PROJECT"
```
**Least-privilege rule (T-04-17 / T-7-05):** resource-scoped `secretAccessor`, never project-wide.
Never echo a secret value.

### Native Secret Manager injection into Cloud Run env
**Source:** `infra/main.tf:462-493` (`value_source.secret_key_ref { version = "latest" }`) and
`infra/DEPLOY-RUNBOOK.md:147` / `:437` (`--update-secrets=ENV=secret:latest`)
**Apply to:** all provider + DB-URL + bucket secrets on the `tribunal-api` and `tribunal-worker`
services. gcloud stores the secret REFERENCE, never the value.

### One-shot migration Job + `--wait` execute
**Source:** `infra/main.tf:531-575` (Job) + `infra/DEPLOY-RUNBOOK.md:534-538` (execute)
**Apply to:** `tribunal-migrate` (`alembic upgrade head` into the `tribunal` schema). Job is a
separate Cloud Run Job from the service, same image, CMD overridden via `args`.

### Cloud Build for images/tests (no local Docker)
**Source:** `frontend/cloudbuild.yaml` (build+push) + `cloudbuild.test.yaml` (pg container + pytest gate)
**Apply to:** both Tribunal images + the Tribunal test-suite gate. Dev machine has no Python/Docker;
everything runs via Cloud Build (RESEARCH §Environment Availability).

### Isolated Alembic line via separate `version_table` + schema
**Source:** RESEARCH §Pattern 1 (extends `backend/app/db/alembic/env.py:126-134` shape)
**Apply to:** `tribunal/…/alembic/env.py`. `version_table="tribunal_alembic_version"` +
`version_table_schema="tribunal"` + `search_path=tribunal`. NEVER share `alembic_version` (Pitfall 1:
both repos have colliding revision IDs `0001`–`0010`).

### FROZEN audit hash-chain (do NOT touch)
**Source (verbatim copy):** `Nestor/nestor_pulse_sdk/audit/hash_chain.py` `_payload_for_row`
**Apply to:** the copied `tribunal/…/audit/hash_chain.py`. Keep `tenant_id`, `gcs_uri`, `seq`,
`run_id`, token counts, timestamps byte-identical. Any rename forks every chain (ENGINE-04, legal
gate). The `AUDIT_GCS_BUCKET` must exist with 7y `Unlocked` retention BEFORE the proof run or the
proof run's own chain dangles (RESEARCH Pitfall 3).

---

## No Analog Found

Files whose closest match is the sibling repo (copy verbatim) rather than a this-repo analog — the
planner should treat these as **carry-unchanged**, not author-from-pattern:

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `tribunal/nestor_pulse_sdk/audit/hash_chain.py` | crypto ledger | transform | No this-repo crypto-chain exists; FROZEN copy from sibling (ENGINE-04). |
| `tribunal/nestor_pulse_sdk/runs/worker.py` (SKIP-LOCKED poll worker) | service | event-driven | No always-on background worker exists in the intake backend (it's request-response only). Copy from sibling; extend only via `execute.py` lock. |
| `tribunal/nestor_pulse_sdk/pipeline/**` (9-stage skeptic/synthesis) | service | batch | No deep-research pipeline analog in this repo. Copy verbatim. |
| `tribunal/nestor_pulse/secrets.py` | config/loader | transform | Sole cross-package dep; copy verbatim (imports only stdlib). |
| `tribunal/requirements.txt` | config | — | Pinned Py 3.11.9 set; carry verbatim (do NOT re-resolve or align to backend's 3.12/pg8000). |

---

## Metadata

**Analog search scope:** `infra/` (main.tf, DEPLOY-RUNBOOK.md, README.md, variables/outputs/providers),
`backend/` (Dockerfile, app/db/alembic/env.py), repo-root + `frontend/` Cloud Build configs;
sibling `Nestor/` repo verified for copy-source existence only (not re-excerpted — integrity-frozen).
**Files scanned (this repo):** 8 read in full/part; ~6 more globbed.
**Pattern extraction date:** 2026-07-20
