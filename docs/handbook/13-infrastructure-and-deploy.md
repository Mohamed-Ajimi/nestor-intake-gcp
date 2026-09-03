# 13 — Infrastructure, deployment and CI

| | |
|---|---|
| **Audience** | Engineers who deploy or change the platform; the operator who runs a deploy session; anyone reconciling the Terraform against the live project |
| **Type** | Reference + How-to |
| **Source of truth** | `infra/main.tf`, `infra/variables.tf`, `infra/providers.tf`, `infra/outputs.tf`, `infra/README.md`, `infra/DEPLOY-RUNBOOK.md`, `cloudbuild.test.yaml`, `frontend/cloudbuild.yaml`, `frontend/Dockerfile`, `backend/Dockerfile`, `tribunal/cloudbuild.*.yaml`, `tribunal/infrastructure/cloud-run/**`, `backend/scripts/ci_*.sh`, `frontend/scripts/ci_*.sh`, `frontend/scripts/i18n-audit.mjs`, `.planning/CONTINUE-HERE.md` |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

## 13.1 In one paragraph

Everything runs inside one Google Cloud project, `project-cb01b861-cb4a-438d-b9a`, in one EU region, `europe-west1`. Four Cloud Run services (the SSR frontend, the intake API, the Tribunal API and the always-on Tribunal worker) share one Cloud SQL Postgres 16 instance that holds two schemas, plus two GCS buckets (uploads, and a 7-year audit store), Secret Manager for every key, and Identity Platform for login. The Terraform under `infra/` describes this footprint completely, but its state was never adopted: every live resource was created by hand with `gcloud`, and the 6,000-line `infra/DEPLOY-RUNBOOK.md` is both the procedure and the deploy history. Images are built by Cloud Build, deployed by digest, and proven by reading the serving revision's digest back. There is no CI trigger; every gate is a Cloud Build config a person submits before a deploy.

## 13.2 How it works

### 13.2.1 The shape of the deployment

The browser loads the SSR shell from `nestor-frontend`, which is public and holds no secret, no service account and no database connection (`infra/main.tf:677-712`). Every data call goes from the browser straight to `nestor-api` with an Identity Platform ID token. `nestor-api` is the only writer to the `nestor` schema. It reaches Cloud SQL through the Cloud SQL Python Connector using IAM database authentication: there is no password, no IP allowlist and no proxy sidecar (`infra/main.tf:44-71`). Its secrets (Anthropic, OpenAI, Resend) are injected natively from Secret Manager as environment variables (`infra/main.tf:465-503`).

When the operator starts a research run, `nestor-api` mints a Google-signed OIDC token and calls `tribunal-api`. Only the intake runtime service account holds `run.invoker` on that service (`infra/main.tf:1274-1279`), and the app re-verifies the caller inside (`InternalCallerProvider`, see [09 — Tribunal service](09-tribunal-service.md)). `tribunal-api` writes a `queued` row; `tribunal-worker`, an always-on poller, claims it and runs the pipeline for up to an hour per request window, writing every LLM call to the audit bucket with a 7-year object retention. The two Tribunal services use a different database path from the intake API: a stored password DSN over the Cloud SQL unix socket, as the `app_user` (tenant-scoped) and `worker_user` (cross-tenant claim role) built-in users (`infra/main.tf:842-870`, `:1042-1055`).

```mermaid
flowchart TB
  BR["Browser"]
  subgraph GCP["GCP project project-cb01b861-cb4a-438d-b9a · europe-west1"]
    subgraph RUN["Cloud Run"]
      FE["nestor-frontend<br/>SSR · public · 0..4"]
      API["nestor-api<br/>FastAPI · 0..4 · 900s<br/>SA nestor-run"]
      TAPI["tribunal-api<br/>0..3 · 300s<br/>SA tribunal-run"]
      TW["tribunal-worker<br/>1..5 · 3600s · CPU always on<br/>SA tribunal-run"]
      JOBS["Jobs: nestor-migrate<br/>nestor-seed-superadmin<br/>tribunal-migrate"]
    end
    SQL[("Cloud SQL nestor-pg<br/>POSTGRES_16 · db nestor<br/>schemas nestor + tribunal")]
    UP[("uploads bucket<br/>project-nestor-uploads")]
    AUD[("audit bucket<br/>project-nestor-audit<br/>7-year object retention")]
    SM["Secret Manager<br/>10 secrets in Terraform<br/>+ Nestor_SERP by hand"]
    IDP["Identity Platform<br/>manual setup"]
    AR["Artifact Registry repo nestor<br/>backend · frontend<br/>tribunal-api · tribunal-worker"]
  end
  BR --> FE
  BR -->|"ID token"| API
  BR -->|"sign in"| IDP
  API -->|"IAM connector, no password"| SQL
  API -->|"signed URLs"| UP
  API -->|"OIDC · invoker = nestor-run only"| TAPI
  TAPI -->|"unix socket · app_user"| SQL
  TW -->|"unix socket · worker_user"| SQL
  TW -->|"audit blobs"| AUD
  TAPI --> AUD
  JOBS --> SQL
  SM -.-> API
  SM -.-> TAPI
  SM -.-> TW
  AR -.-> RUN
  API --> EXT1["Anthropic · OpenAI · Resend"]
  TW --> EXT2["Anthropic · Google · OpenAI · SerpAPI"]
```

### 13.2.2 Two ways into the same database

The intake API and the Tribunal services deliberately authenticate differently. The intake API has a Cloud SQL IAM user named after its service account (`nestor-run@<project>.iam`), whose privileges are granted by migration 0005 (`infra/main.tf:90-97`). The only stored database credential on the intake side is the `app_superadmin` password, generated by Terraform, kept only in Secret Manager, and referenced from the service by its secret resource name rather than its value (`infra/main.tf:99-139`, `:453-461`). The Tribunal engine was re-homed with its own conventions intact: it reads `DATABASE_URL` from the process environment, so it gets built-in users with passwords embedded in two DSN secrets, and the services mount the `/cloudsql` volume that the unix-socket DSN needs (`infra/main.tf:1042-1055`, `:1166-1179`). The header of the Phase 13 block calls this "DB AUTH TOPOLOGY (RESEARCH Pitfall 5)" (`infra/main.tf:741-746`).

### 13.2.3 Why Terraform is a description, not a controller

Phase 2 was deployed with gcloud from Cloud Shell because the dev box had no Terraform (`infra/README.md:44-60`; the D-10 note at `infra/DEPLOY-RUNBOOK.md:13`). Every later phase kept that mode. The Terraform was extended by construction each time, with an "IaC-DRIFT" comment marking each block as "INTENDED end-state, INERT" (`infra/main.tf:295-300`, `:672-676`, `:751-755`, `:794-795`). The remote-state backend is shipped commented out (`infra/providers.tf:17-32`). The consequence is that the `.tf` files are the most complete single description of the topology, and at the same time nothing guarantees they match the live project. Section 13.4 lists what is known to differ.

### 13.2.4 How a deploy is run

A deploy is a human session that follows a numbered procedure, recorded afterwards in the runbook with the tag, revision names and digests. The order is fixed by three lessons: the surface must be derived from the actual diff by import graph (a skipped service leaves a fix inert while reading as deployed, `infra/DEPLOY-RUNBOOK.md:4738-4767`); migrations must be proven by the literal `Running upgrade` line, not by a zero exit (`:4674`); and the worker deploys last, after the queue is proven empty, because its loop claims before it sleeps (`:2960-2977`). The full procedure is in section 13.6.

```mermaid
flowchart TD
  A["Pin --account=tools@dotto.be and --project on EVERY command"] --> B["Derive the surface: git diff, then non-test importers"]
  B --> C["Local gates: npm ci, i18n-audit, tsc, build, guard scripts"]
  C --> D["Cloud Build gates: test-engine, test-gates, backend integration"]
  D --> E{"Green, read from build STATUS text?"}
  E -- no --> S1["STOP"]
  E -- yes --> F["Build every image in the surface at ONE shared tag"]
  F --> G{"Migration in the diff?"}
  G -- yes --> H["Repin the migrate Job image, execute, read the literal Running upgrade line"]
  G -- no --> I
  H --> I["Deploy non-worker services by digest"]
  I --> J["Prove status.imageDigest on each serving revision"]
  J --> K{"Queue empty? newest audit write + worker_user read"}
  K -- no --> S2["Resolve or cancel the run first"]
  K -- yes --> L["Deploy tribunal-worker LAST, optionally at MIN_INSTANCES=0"]
  L --> M["Read back env and secret NAMES; /readyz 200"]
  M --> N["Audit newest write unchanged: no run was triggered"]
  N --> O["Write the deploy record: tag, revisions, digests"]
```

## 13.3 The GCP topology as coded

### 13.3.1 Provider, state and variables

| Item | Value | Source |
|---|---|---|
| Terraform | `>= 1.6`; provider `hashicorp/google >= 6.0, < 7.0` | `infra/providers.tf:8-13` |
| Provider scope | one `google` provider, `project = var.project`, `region = var.region` | `infra/providers.tf:35-38` |
| Remote state | GCS backend block shipped commented out (WR-06); expected one-time `gsutil mb … -nestor-tfstate` then `terraform init -migrate-state` | `infra/providers.tf:17-32` |
| State adoption | never happened; Phase 2 deployed gcloud-native, every later phase by hand | `infra/DEPLOY-RUNBOOK.md:26-40` |
| Apply model | two-step: apply with `image_tag=bootstrap`, build and push, re-apply with the real tag | `infra/README.md:44-94` |

Variables and their defaults (`infra/variables.tf`):

| Variable | Default | Line |
|---|---|---|
| `project` | required | `:14-17` |
| `region` | `europe-west1` | `:19-23` |
| `tier` | `db-custom-1-3840` | `:25-29` |
| `repo` | `nestor` | `:31-35` |
| `image_tag` | required on the second apply | `:37-40` |
| `db_name` | `nestor` | `:42-46` |
| `instance_name` | `nestor-pg` | `:48-52` |
| `service_name` | `nestor-api` | `:54-58` |
| `runtime_sa_id` | `nestor-run` | `:60-64` |
| `superadmin_email` | `yanick@agenic.be` | `:66-70` |
| `superadmin_db_secret_id` | `nestor-app-superadmin-db-password` | `:72-76` |
| `allow_unauthenticated` | `false` | `:78-82` |
| `frontend_service_name` | `nestor-frontend` | `:91-95` |
| `frontend_image_tag` | required | `:97-100` |
| `vite_api_base_url`, `vite_firebase_api_key`, `vite_firebase_auth_domain`, `vite_firebase_project_id` | `""`, documentation only; real values travel as Cloud Build substitutions | `:112-134` |
| `cors_allowed_origins` | `[]` (empty means no bucket CORS block) | `:143-147` |
| `anthropic_api_key_secret_id` / `openai_api_key_secret_id` | `nestor-anthropic-api-key` / `nestor-openai-api-key` | `:158-168` |
| `anthropic_api_key` / `openai_api_key` / `resend_api_key` | `""`, sensitive; empty means `count = 0` secret version | `:170-182`, `:199-204` |
| `resend_api_key_secret_id` | `nestor-resend-api-key` | `:193-197` |
| `nestor_admin_email`, `app_base_url` | `""`, set live with `--update-env-vars` | `:215-225` |
| `tribunal_worker_service_name` / `tribunal_api_service_name` | `tribunal-worker` / `tribunal-api` | `:250-260` |
| `tribunal_worker_max_instances` | `5` | `:262-266` |
| `tribunal_worker_stale_minutes` | `"60"` | `:268-272` |
| `tribunal_image_tag` | `""` | `:274-278` |
| `tribunal_gemini_secret_id` / `tribunal_claude_secret_id` / `tribunal_openai_secret_id` | `Nestor_Gemini` / `Nestor_Claude2` / `Nestor_OpenAI` | `:289-305` |
| `tribunal_database_url_secret_id` / `tribunal_database_url_worker_secret_id` | `DATABASE_URL` / `DATABASE_URL_WORKER` | `:315-325` |
| `tribunal_audit_bucket_secret_id` | `AUDIT_GCS_BUCKET` | `:328-332` |
| `tribunal_audit_bucket_name` | `""`, derives `${project}-nestor-audit` | `:334-338`, `infra/main.tf:765` |
| `tribunal_runtime_sa_id` | `tribunal-run` | `:351-355` |
| `tribunal_service_url` | `""`, captured from `describe`, never guessed | `:357-361` |

### 13.3.2 Cloud SQL

| Setting | Value | Source |
|---|---|---|
| Instance | `nestor-pg`, `POSTGRES_16`, `deletion_protection = true` | `infra/main.tf:44-50` |
| Tier | `db-custom-1-3840` (1 vCPU, 3.75 GB); default `max_connections = 100` | `infra/main.tf:54` |
| Flag | `cloudsql.iam_authentication = on` | `infra/main.tf:58-61` |
| Network | `ipv4_enabled = true` (public IP) with **no** authorized-networks block, on purpose | `infra/main.tf:63-68` |
| Database | `nestor`, `deletion_protection = true` plus `lifecycle { prevent_destroy = true }` (WR-06) | `infra/main.tf:74-88` |
| Schemas | `nestor` (intake, Alembic head 0013) and `tribunal` (engine, Alembic head 0018, own version table `tribunal.tribunal_alembic_version`) | `backend/app/db/alembic/versions/`, `tribunal/nestor_pulse_sdk/alembic/versions/`, `infra/DEPLOY-RUNBOOK.md:4681` |

Why a public IP with no allowlist: the header of `infra/main.tf:11-15` explains that the Cloud SQL Python Connector tunnels over the Admin API with ephemeral TLS certificates, so access is gated by IAM identity, not by network range. An IP allowlist is named as "the anti-pattern we avoid" (`infra/main.tf:65-67`). The intake API therefore needs no `--add-cloudsql-instances` attachment; the Tribunal services do, because their DSN uses the unix socket (`infra/main.tf:744-746`).

### 13.3.3 Database users

| User | Type | Used by | Notes | Source |
|---|---|---|---|---|
| `nestor-run@<project>.iam` | `CLOUD_IAM_SERVICE_ACCOUNT` | `nestor-api`, `nestor-migrate`, `nestor-seed-superadmin` | login only; privileges come from migration 0005 keyed on `RUNTIME_DB_USER`; RLS still applies | `infra/main.tf:29-33`, `:90-97`, `:566-570` |
| `app_superadmin` | `BUILT_IN` | the cross-tenant superadmin path in `nestor-api` | exact literal required by migration 0003's `current_user = 'app_superadmin'` predicate; 32-char `random_password`; the single stored DB credential | `infra/main.tf:99-139` |
| `app_user` | `BUILT_IN` | `tribunal-api`, `tribunal-migrate` | tenant-scoped; `lifecycle { ignore_changes = [password] }` because the live password was seeded by hand on 2026-07-20 and lives inside `DATABASE_URL` | `infra/main.tf:842-855` |
| `worker_user` | `BUILT_IN` | `tribunal-worker` | cross-tenant claim role; granted on schema `tribunal` only by migration 0008, never on `nestor` (T-13-09) | `infra/main.tf:857-870` |

### 13.3.4 Service accounts and exact roles

**`nestor-run`** (`google_service_account.runtime`, `infra/main.tf:252-255`):

| Grant | Scope | Source |
|---|---|---|
| `roles/cloudsql.client` | project | `infra/main.tf:259-263` |
| `roles/cloudsql.instanceUser` | project (IAM DB login) | `infra/main.tf:265-269` |
| `roles/identitytoolkit.admin` | project (claim writes, IdP user create) | `infra/main.tf:276-280` |
| `roles/secretmanager.secretAccessor` | on `nestor-app-superadmin-db-password` | `infra/main.tf:144-148` |
| `roles/secretmanager.secretAccessor` | on `nestor-anthropic-api-key` | `infra/main.tf:182-186` |
| `roles/secretmanager.secretAccessor` | on `nestor-openai-api-key` | `infra/main.tf:204-208` |
| `roles/secretmanager.secretAccessor` | on `nestor-resend-api-key` | `infra/main.tf:237-241` |
| `roles/storage.objectAdmin` | uploads bucket only | `infra/main.tf:333-337` |
| `roles/iam.serviceAccountTokenCreator` | on itself, for keyless V4 signed URLs via `signBlob` | `infra/main.tf:348-352` |
| `roles/run.invoker` | on `tribunal-api` (the only principal) | `infra/main.tf:1274-1279` |
| `roles/secretmanager.secretAccessor` | on `Nestor_Claude2` (runbook step 15.2.b-bis, not in Terraform) | `infra/DEPLOY-RUNBOOK.md:4684` |

**`tribunal-run`** (`google_service_account.tribunal_run`, `infra/main.tf:796-799`, Phase 14 WR-03 / D-04b):

| Grant | Scope | Source |
|---|---|---|
| `roles/cloudsql.client` | project; deliberately **not** `instanceUser` (password auth, not IAM login) | `infra/main.tf:802-806` |
| `roles/secretmanager.secretAccessor` | on `Nestor_Gemini`, `Nestor_Claude2`, `Nestor_OpenAI`, `DATABASE_URL`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET` | `infra/main.tf:885-891`, `:900-905`, `:914-919`, `:934-939`, `:948-953`, `:962-967` |
| `roles/secretmanager.secretAccessor` | on `Nestor_SERP` (runbook only) | `infra/DEPLOY-RUNBOOK.md:2517-2560` |
| `roles/storage.objectAdmin` | audit bucket only (upload plus per-object retention patch) | `infra/main.tf:1007-1013` |

Deliberately not granted to `tribunal-run`: `identitytoolkit.admin`, the intake superadmin secret, the intake uploads bucket (`infra/main.tf:791-792`). The Phase 14 header explains why the separation matters: while both sides ran as `nestor-run`, the invoker gate was "theater" because caller and callee were the same identity (`infra/main.tf:769-780`).

### 13.3.5 Artifact Registry and image paths

One Docker repository, id `nestor`, in `europe-west1` (`infra/main.tf:244-249`). Image paths:

| Image | Path | Source |
|---|---|---|
| backend | `europe-west1-docker.pkg.dev/<project>/nestor/backend:<tag>` | `infra/main.tf:35` |
| frontend | `…/nestor/frontend:<tag>` | `infra/main.tf:41` |
| tribunal-api | `…/nestor/tribunal-api:<tag>` | `infra/main.tf:761` |
| tribunal-worker | `…/nestor/tribunal-worker:<tag>` | `infra/main.tf:762` |

The legacy standalone repository `nestor-pulse` still exists in the scripts (`tribunal/infrastructure/cloud-run/artifact-registry-create.sh:16`) and is what the stale `build-and-push.sh` targets (section 13.5.4).

### 13.3.6 Cloud Run services

Terraform declares scaling, timeouts, CPU allocation and invokers, but no memory size and no concurrency. Memory and concurrency come only from the Tribunal deploy scripts; for `nestor-api` and `nestor-frontend` they are whatever was set by hand (the runbook records `min-instances=0` and CPU always-allocated for the API in Phase 7, `infra/DEPLOY-RUNBOOK.md:35-40`).

| Service | Runtime SA | min / max | Timeout | CPU | Port | Invoker | Terraform |
|---|---|---|---|---|---|---|---|
| `nestor-api` | `nestor-run` | 0 / 4 | `900s` (SSE, D-07) | `cpu_idle = false` (always allocated) | 8080 | `allUsers` only when `allow_unauthenticated = true` (count-gated); live service is public per Phase 5 drift | `infra/main.tf:358-535`, `:645-651` |
| `nestor-frontend` | none | 0 / 4 | default 300s | default (throttled) | 8080, env `PORT=8080` | unconditional `allUsers` | `infra/main.tf:677-712`, `:721-726` |
| `tribunal-worker` | `tribunal-run` | 1 / 5 | `3600s` | `cpu_idle = false` | none (no HTTP) | no binding | `infra/main.tf:1023-1142` |
| `tribunal-api` | `tribunal-run` | 0 / 3 | `300s` | default | 8080 | `nestor-run` only, unconditional | `infra/main.tf:1150-1264`, `:1274-1279` |

Script-side sizing, which is what the live Tribunal services actually carry:

| Service | Flags | Source |
|---|---|---|
| `tribunal-api` | `--memory=1Gi --cpu=1 --concurrency=80 --min-instances=0 --max-instances=3 --timeout=300 --no-allow-unauthenticated --add-cloudsql-instances --revision-suffix` | `tribunal/infrastructure/cloud-run/deploy-api.sh:151-166` |
| `tribunal-worker` | `--memory=2Gi --cpu=1 --no-cpu-throttling --min-instances=${MIN_INSTANCES:-1} --max-instances=5 --timeout=3600 --no-allow-unauthenticated --add-cloudsql-instances --revision-suffix` | `tribunal/infrastructure/cloud-run/deploy-worker.sh:61`, `:169-184` |

The `nestor-api` maximum of 4 is connection arithmetic: 4 instances × (pool 2 + overflow 3) = 20, far under the tier's 100 (`infra/main.tf:379-382`). Ingress is not set anywhere in Terraform, so Cloud Run's default applies; `tribunal-api` is protected by the IAM invoker plus the in-app caller check (`infra/main.tf:1266-1273`).

**`nestor-api` environment** (`infra/main.tf:407-503`): `INSTANCE_CONNECTION_NAME`, `DB_USER`, `DB_NAME`, `STORAGE_BUCKET`, `NESTOR_ADMIN_EMAIL`, `APP_BASE_URL`, `TRIBUNAL_SERVICE_URL`, `SUPERADMIN_DB_PASSWORD_SECRET` (the secret resource name with `/versions/latest`, never the value), and native `secret_key_ref` injections for `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `RESEND_API_KEY` at version `latest`. The live service also carries `CORS_ALLOWED_ORIGINS`, set out of band (`infra/DEPLOY-RUNBOOK.md:5989`).

**`tribunal-worker` environment** (`infra/main.tf:1065-1123`): `NESTOR_TRIBUNAL_UNCAPPED=1`, `NESTOR_WORKER_STALE_MINUTES` (default 60), and secrets `AUDIT_GCS_BUCKET`, `DATABASE_URL` sourced from **`DATABASE_URL_WORKER`**, `ANTHROPIC_API_KEY` from `Nestor_Claude2`, `GOOGLE_API_KEY` from `Nestor_Gemini`, `OPENAI_API_KEY` from `Nestor_OpenAI`. The script adds the plain variables `NESTOR_ENV=prod`, `NESTOR_WORKER_POLL_INTERVAL=2.0`, `NESTOR_WORKER_STALE_MINUTES=60`, `NESTOR_TRIBUNAL_UNCAPPED=1`, `NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol` (`deploy-worker.sh:183`) and `SERPAPI_API_KEY` from `Nestor_SERP` when that secret exists (`deploy-worker.sh:131-133`).

**`tribunal-api` environment** (`infra/main.tf:1185-1249`): `NESTOR_TRIBUNAL_UNCAPPED=1`, `TRIBUNAL_SERVICE_URL` (its own `run.app` URL, the OIDC audience), `INTAKE_RUNTIME_SA_EMAIL` (the `nestor-run` email), secrets `AUDIT_GCS_BUCKET`, `DATABASE_URL` from `DATABASE_URL` (the `app_user` DSN), and the three provider keys. The script's plain set is `NESTOR_ENV=prod,NESTOR_TRIBUNAL_UNCAPPED=1,TRIBUNAL_SERVICE_URL=…,INTAKE_RUNTIME_SA_EMAIL=…` (`deploy-api.sh:165`).

### 13.3.7 Cloud Run Jobs

| Job | Image | Command | SA | Notes | Source |
|---|---|---|---|---|---|
| `nestor-migrate` | backend | `args = ["alembic","upgrade","head"]`; env adds `RUNTIME_DB_USER` for the 0005 GRANT | `nestor-run` | migrations never run at service start (D-05) | `infra/main.tf:541-585` |
| `nestor-seed-superadmin` | backend | `python -m scripts.seed_superadmin`, `SUPERADMIN_EMAIL` env; password passed at execute time with `--update-env-vars SUPERADMIN_PASSWORD=…`, never stored | `nestor-run` | one-shot bootstrap | `infra/main.tf:595-639`, `infra/README.md:192-208` |
| `tribunal-migrate` | **tribunal-api** image | `command = ["sh"]`, `args = ["-c", "cd /app/nestor_pulse_sdk && alembic upgrade head"]`; env `DATABASE_URL` from the `DATABASE_URL` secret; mounts `/cloudsql` | `tribunal-run` | `alembic.ini` is cwd-relative, so the `cd` is load-bearing; proven live by execution `tribunal-migrate-sc64g` on 2026-07-20 | `infra/main.tf:1289-1346` |

### 13.3.8 Secret Manager

| Secret | Consumer | In Terraform | Value seeding | Source |
|---|---|---|---|---|
| `nestor-app-superadmin-db-password` | `nestor-api` (runtime fetch by resource name) | yes, and the only Terraform-managed version | `random_password` | `infra/main.tf:128-139` |
| `nestor-anthropic-api-key` | `nestor-api` | secret yes; version `count = 0` by default | `gcloud secrets versions add --data-file=-` | `infra/main.tf:163-186` |
| `nestor-openai-api-key` | `nestor-api` | same | same | `infra/main.tf:188-208` |
| `nestor-resend-api-key` | `nestor-api` | same | same | `infra/main.tf:219-241` |
| `Nestor_Gemini` | both Tribunal services | secret + accessor | by hand; the Gemini key was reused from the old project (13 D-06) | `infra/main.tf:878-891` |
| `Nestor_Claude2` | both Tribunal services | secret + accessor | by hand; repointed from `Nestor_Claude` on 2026-07-27 | `infra/main.tf:893-905`, `infra/variables.tf:289-305` |
| `Nestor_OpenAI` | both Tribunal services | secret + accessor | by hand | `infra/main.tf:907-919` |
| `DATABASE_URL` | `tribunal-api`, `tribunal-migrate` | secret + accessor | by hand (contains the `app_user` password) | `infra/main.tf:927-939` |
| `DATABASE_URL_WORKER` | `tribunal-worker` | secret + accessor | by hand (contains the `worker_user` password) | `infra/main.tf:941-953` |
| `AUDIT_GCS_BUCKET` | both Tribunal services | secret + accessor | by hand; the value is the non-secret bucket name, injected as a secret "purely for uniformity" | `infra/main.tf:955-967`, `:1074-1076` |
| `Nestor_SERP` | both Tribunal services | **no** | existed since 2026-06-03; only IAM was added | `infra/DEPLOY-RUNBOOK.md:4683` |
| `Nestor_Claude_Temp` | Tribunal services on some deploys | **no** | burner key used for V-01 and the 15.8 deploy | `infra/DEPLOY-RUNBOOK.md:4033`, `:4694` |
| `Nestor_Claude` | legacy | **no** | repointed away 2026-07-27 | `tribunal/infrastructure/cloud-run/deploy-api.sh:87-104` |

Every key value is seeded from stdin so nothing enters state (`infra/DEPLOY-RUNBOOK.md:87-106`, `:708-760`).

### 13.3.9 GCS buckets

| Bucket | Name | Settings | Source |
|---|---|---|---|
| Uploads | `${project}-nestor-uploads` | `uniform_bucket_level_access = true`; `public_access_prevention = "enforced"`; no versioning, no lifecycle (D-12); `force_destroy = false`; dynamic GET-only CORS from `cors_allowed_origins` (WR-02) | `infra/main.tf:301-326` |
| Audit | `${project}-nestor-audit` | uniform access; public access prevention enforced; **`enable_object_retention = true`**; deliberately **no** bucket-level `retention_policy` (Bucket Lock is forbidden, 13 D-09); `force_destroy = false` | `infra/main.tf:969-1002` |

The 7-year duration is not in Terraform. It is set per object by the engine: `nestor_pulse_sdk/audit/gcs_blob.py` writes `mode = "Unlocked"` and `retain_until = now + 7y` (`_RETENTION_YEARS = 7`) on every upload, which is why the runtime SA needs `objectAdmin` and not `objectCreator` (`infra/main.tf:975-991`, `:1004-1006`). The live bucket path is `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/<run_id>/` (`docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md:22`). See [09 — Tribunal service](09-tribunal-service.md) for the audit chain and [14 — Security and compliance](14-security-and-compliance.md) for the EU AI Act Article 12 context.

### 13.3.10 Identity Platform

Not provisioned by Terraform. The only IaC trace is the `identitytoolkit.admin` grant (`infra/main.tf:276-280`). Enabling Identity Platform, the same-project guard (`VITE_FIREBASE_PROJECT_ID` must equal `GOOGLE_CLOUD_PROJECT`), and the Firebase Console "Authorized domains" list are manual steps (`infra/README.md:149-190`, `infra/DEPLOY-RUNBOOK.md:638-645`). The Firebase web API key is public configuration baked into the frontend image at build time (`frontend/cloudbuild.yaml:9-13`).

### 13.3.11 Outputs

`instance_connection_name`, `runtime_sa_email`, `service_url`, `frontend_service_url` (captured on the first frontend deploy and fed into CORS, `APP_BASE_URL`, bucket CORS and Firebase domains) and `repo_url` (`infra/outputs.tf:7-35`).

## 13.4 IaC drift: what is wired by hand

Terraform state was never adopted, so this list is what the runbook says was done with gcloud and what the `.tf` files would not reproduce or would get wrong.

| Item | Applied how | Source |
|---|---|---|
| `identitytoolkit.admin` grant, `allUsers` invoker on `nestor-api`, `SUPERADMIN_DB_PASSWORD_SECRET` env plus accessor, `CORS_ALLOWED_ORIGINS` (Phase 5) | gcloud | `infra/DEPLOY-RUNBOOK.md:28-34`; `.planning/STATE.md:520` |
| AI-key secrets, `min-instances=0`, CPU always allocated (Phase 7) | gcloud | `infra/DEPLOY-RUNBOOK.md:35-40` |
| `--timeout=900` on `nestor-api` (Phase 8) | `gcloud run services update` | `infra/DEPLOY-RUNBOOK.md:202-213` |
| Uploads bucket, both IAM bindings, `STORAGE_BUCKET` env (Phase 9) | gcloud | `infra/main.tf:295-300` |
| Resend secret and the two mail envs (Phase 10) | gcloud | `infra/main.tf:429-434` |
| `nestor-frontend` service and its invoker (Phase 12) | gcloud | `infra/main.tf:672-676` |
| The whole Tribunal footprint: two services, Job, six secrets, audit bucket, two DB users, `tribunal-run` SA (Phases 13, 14) | gcloud + the deploy scripts | `infra/main.tf:751-755`, `:794-795` |
| Every provider key value, both DSN values, `Nestor_SERP` | `gcloud secrets versions add` | `infra/DEPLOY-RUNBOOK.md:87-106`, `:4683` |
| Firebase authorized domains | Console only | `infra/DEPLOY-RUNBOOK.md:638-641` |
| `app_user` / `worker_user` passwords | hand-generated 2026-07-20; Terraform has `ignore_changes` so an import must not rotate them | `infra/main.tf:848-854` |
| Anthropic secret on the Tribunal services | Terraform and the script default say `Nestor_Claude2`; deploys since 15.2.k used the `Nestor_Claude_Temp` burner via `TRIBUNAL_ANTHROPIC_SECRET`; the 2026-08-12 read-back shows `ANTHROPIC_API_KEY` and `SERPAPI_API_KEY` bound on both | `infra/DEPLOY-RUNBOOK.md:4033`, `:5502` |
| `nestor-api`'s Anthropic secret | session notes record `nestor-api` on `Nestor_Claude` while the Tribunal services are on `Nestor_Claude2`; the script comment says `nestor-api` moved to `Nestor_Claude2` on 2026-07-27. Not determined from the code; verify by `describe` before relying on it | `deploy-api.sh:100-102` versus session memory |
| `NESTOR_WORKER_STALE_MINUTES` | 90 in Phase 16, back to 60 in 15.2.j/k | `infra/DEPLOY-RUNBOOK.md:1234-1251`, `:3461` |
| Legacy standalone teardown (Step 13.i: `nestor-pulse-api`, `nestor-pulse-worker`, Cloud SQL `nestor-prod-pg`, repo `nestor-pulse`) | deferred; `project-cb01b861` turned out to be the intake project itself, so "teardown" means resources only | git `cddf1f5` (2026-07-20); [17 · D-02 (Phase 13)](17-decision-log.md) |

The consequence for a reader: use `gcloud run services describe` and `gcloud secrets list` as the truth for live settings, and use `infra/main.tf` for intent and rationale.

## 13.5 The Tribunal images and deploy scripts

### 13.5.1 Two images, one build context

Both Tribunal images are built from the `tribunal/` directory with `tribunal/cloudbuild.api.yaml` and `tribunal/cloudbuild.worker.yaml`, each a single `docker build` with no build arguments (`tribunal/cloudbuild.api.yaml:20-35`, `tribunal/cloudbuild.worker.yaml:19-34`). Both Dockerfiles are two-stage `python:3.11-slim`, install `requirements.txt`, and copy **both** `nestor_pulse_sdk` and the `nestor_pulse` leaf: the API needs it because the Claude deep-research adapter imports it at module level on the boot path (`tribunal/infrastructure/cloud-run/api/Dockerfile:10-19`, `:37-38`); the worker needs it because it runs the deep-research adapters (`worker/Dockerfile:13-16`, `:32-33`). Entrypoints: `uvicorn nestor_pulse_sdk.server:app` (`api/Dockerfile:43`) and `python -m nestor_pulse_sdk.runs.worker` (`worker/Dockerfile:36`). Because both images copy the whole package, a change to any engine module is baked into both, which is why the surface question (section 13.6, step 2) is about who imports the change, not about which image contains the bytes (`infra/DEPLOY-RUNBOOK.md:4763-4767`).

### 13.5.2 `deploy-worker.sh`

- Deploys `tribunal-worker` as `tribunal-run@…` with the flags in section 13.3.6, `--add-cloudsql-instances` for the unix socket, and `--no-cpu-throttling` so the poll loop runs with no inbound HTTP (`deploy-worker.sh:169-184`).
- `MIN_INSTANCES` defaults to 1; the override exists because a single `gcloud run deploy` both unpauses the worker and sets `NESTOR_WORKER_STALE_MINUTES=60` in one atomic command, and on 2026-07-28 that combination re-claimed a stuck run (`deploy-worker.sh:41-61`).
- The secret set is composed in a variable because `--set-secrets` **replaces** the entire secret set on every deploy; anything omitted is dropped from the next revision (`deploy-worker.sh:77-83`). The Anthropic secret defaults to `Nestor_Claude2` by committed intent; the live value is read only to report divergence, because on 2026-07-25 a self-healing version re-inherited the very drift it existed to prevent (`deploy-worker.sh:84-118`).
- `SERPAPI_API_KEY` from `Nestor_SERP` is appended only if the secret exists, so a missing SerpAPI key degrades the run to three streams instead of failing the deploy (`deploy-worker.sh:129-146`).
- `NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol` is pinned on the env line because the previous unpinned default, `o4-mini-deep-research`, was retired by OpenAI on 2026-07-23 and silently killed all seven OpenAI angles on run `d6bb3aae` (`deploy-worker.sh:150-167`).
- Cost of the always-on posture, per the script itself: "always-on 1 vCPU 2Gi instance ~ $5-10/month idle" (`deploy-worker.sh:31`). This is the accepted cost of [17 · D-04 (Phase 13)](17-decision-log.md). Pause with `--min-instances=0` (`deploy-worker.sh:32`, `:201-202`), remembering that pausing does not stop a boot (section 13.6, step 9).

### 13.5.3 `deploy-api.sh`

- Deploys `tribunal-api` as `tribunal-run@…` with the flags in section 13.3.6 (`deploy-api.sh:151-166`).
- `--set-env-vars` replaces the whole plain env, so a forgotten `TRIBUNAL_SERVICE_URL` would ship an empty audience and fail the seam closed. The script self-heals from the live service's own URL and then fails fast if still empty; `ALLOW_EMPTY_SEAM_ENV=1` permits the first-ever deploy only (`deploy-api.sh:45-79`).
- Same secret composition rules and the same `Nestor_SERP` conditional as the worker (`deploy-api.sh:81-149`).

### 13.5.4 `--set-secrets` in scripts versus `--update-secrets` by hand

The scripts use `--set-secrets` and `--set-env-vars`, which replace the full sets. A hand-typed `gcloud run deploy --image=…` with none of the `--set-*` flags carries every existing binding forward, which is why the Phase 22 record deploys "by `--image` ONLY (no `--set-secrets` / `--set-env-vars` / `--service-account`)" (`infra/DEPLOY-RUNBOOK.md:5396-5400`, `:5682-5685`). Use the scripts when the env or secret set must change; use `--image` alone when only the code changes; never mix a partial `--set-*` list into a hand-typed deploy.

`tribunal/infrastructure/cloud-run/build-and-push.sh` is **stale**: it builds to the legacy `nestor-pulse/api` and `nestor-pulse/worker` paths and runs under a `nestor-pulse-runtime` service account, and it reports success (`build-and-push.sh:20-24`; `infra/DEPLOY-RUNBOOK.md:5363-5367`). `tribunal/infrastructure/cloud-run/DEPLOY.md` likewise documents the retired standalone services. Neither is used.

## 13.6 Deploy discipline: the ordered procedure

This is the procedure the runbook converged on across Phases 15.8, 21, 22 and the 2026-08-13 fix deploy. Each rule cites the place where it was learned.

1. **Pin the identity on every command.** Add `--account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a` to every `gcloud` invocation, not once per session. Four accounts are authenticated on the dev machine. On 2026-08-05 a `gcloud auth login` mid-deploy switched both the account and the project, a correction succeeded, and the browser login then finalised asynchronously and overwrote it (`infra/DEPLOY-RUNBOOK.md:4364-4383`; `.planning/STATE.md:97-100`). The config drifted again to `tools@epicimpact.be` on 2026-08-13 and stayed wrong through a successful deploy because every acting command was pinned (`infra/DEPLOY-RUNBOOK.md:6036-6041`). Read the two unpinned config values first so the drift is detected, then pin everything else.
2. **Derive the surface from the diff by import graph.** Run `git diff --name-only <last-deployed>..HEAD`, then find the non-test importers of each changed module. Do not copy a surface from a plan, and do not grep by substring: on 2026-08-12 a local dict named `verification_report` in `pipeline.py` would have pulled the money-risk worker into the surface (`infra/DEPLOY-RUNBOOK.md:4738-4767`, `:5149`, `:5850`). The runbook calls the surface "a MEASUREMENT WITH AN EXPIRY DATE, not a fact". On 2026-08-06 the standing note said two services and the diff said three.
3. **Run the local gates for the frontend** before any frontend build: `npm ci && node scripts/i18n-audit.mjs && npx tsc --noEmit && npm run build` (`infra/DEPLOY-RUNBOOK.md:3086-3092`). `npm ci`, never `npm install`; the lockfile is committed (`frontend/Dockerfile:42-45`). Run the guard scripts of section 13.9 for their exit codes.
4. **Submit the Cloud Build gates** for the touched half and read the result from `gcloud builds describe <id> --format=value(status)`. `builds submit | tail` returns the pipe's exit status, so it reports 0 on a failed build; `EXPIRED` is not a result (`infra/DEPLOY-RUNBOOK.md:4689`). The engine gate prints a `collecting: N of N expected files` line that must be read (section 13.8).
5. **Build every image in the surface at one shared tag** (`YYYYmmdd-HHMMSS`). The backend builds with a plain `gcloud builds submit backend --tag …/nestor/backend:<tag>` and no config (`infra/README.md:73-85`); the frontend needs `--config=frontend/cloudbuild.yaml` and five substitutions that are recovered verbatim from the previous frontend build with `gcloud builds describe <prior> --format="yaml(substitutions)"`, never retyped, and asserted non-empty because `--format='value(...)'` renders a permission error as an empty string and an empty substitution ships a broken live frontend silently (`infra/DEPLOY-RUNBOOK.md:5378-5390`, `:5677-5680`, `:4826-4830`). The Tribunal images build with their two configs and an explicit `_IMAGE`.
6. **Migrations, only when the diff contains one.** Repin the Job image first (`gcloud run jobs update --image`), then execute, then find the literal `Running upgrade NNNN -> NNNN` line in the execution log. A zero exit against a stale image is a no-op that reads as success (`infra/DEPLOY-RUNBOOK.md:1423`, `:4674`, `:4681`). The two lines are separate: intake via `nestor-migrate` (head 0013), engine via `tribunal-migrate` (head 0018). On 2026-08-05 three engine migrations were paid in one execution and all three lines were recorded (`.planning/STATE.md:52-58`).
7. **Deploy the non-worker services by digest** (`--image=…@sha256:…`), or with the deploy scripts when the env or secret set changes (section 13.5.4).
8. **Prove each revision.** Read `status.imageDigest` off the new revision and compare with the built digest. `containers[0].image` is a mutable tag and proves nothing; an unchanged digest is a failed deploy; revision names are not comparable across script deploys (which pass `--revision-suffix`) and hand deploys (auto-numbered) (`infra/DEPLOY-RUNBOOK.md:4972-4974`, `:5514-5527`, `:6014-6023`).
9. **Prove the queue empty, then deploy `tribunal-worker` last.** A deploy boots the container to health-check it, and `runs/worker.py`'s loop claims at the top of its first iteration and sleeps at the bottom (`tribunal/nestor_pulse_sdk/runs/worker.py:661-665`, `:700`). `--min-instances=0` does not prevent that boot; it governs steady state only. On 2026-07-28 the worker deployed at 08:22:57Z, claimed run `d6bb3aae` within seconds and re-executed about 15 minutes of paid pipeline unattended; the operator deleted the service to stop it (`infra/DEPLOY-RUNBOOK.md:2960-2977`; quick `260728-kdw`, `.planning/STATE.md:549`). Two free checks: the newest write in the audit bucket (a claimable row would already be writing blobs, `infra/DEPLOY-RUNBOOK.md:4841-4860`), and a queue read as `worker_user`, since `app_user` without a bound tenant sees zero rows and looks exactly like an empty queue (quick `260728-kdw` summary). Ship the worker with `MIN_INSTANCES=0` when a run needs resolving first, then unpause as a separate act.
10. **Read back, smoke, and prove nothing ran.** Read env and secret **names** (never values) off both Tribunal services; hit `/readyz` on `tribunal-api` with an identity token against the path-less URL (`infra/DEPLOY-RUNBOOK.md:4690`). For `nestor-api`, smoke on `/readyz` (`backend/app/main.py:200`), not `/healthz`: since at least 2026-08-31 `/healthz` returns a Google-branded 404 from upstream while `/readyz` and `/docs` answer 200, and `main.py` was unchanged, so the cause sits outside the app (session record 2026-08-31). Compare the audit bucket's newest write before and after; equality proves no run was triggered (`infra/DEPLOY-RUNBOOK.md:5506-5507`, `:5996-5997`).
11. **Write the deploy record** in the runbook: tag, build ids, revision names, pre and post digests, migration lines, env read-backs, and the audit-bucket before/after.

**Classifier-blocked commands.** The agent's `gcloud` is read-only in practice: `describe` and `list` work; `add-iam-policy-binding` and `logging read` are blocked; `gcloud builds submit` was blocked on 2026-08-13 and not on 2026-09-01 (session records; `.planning/CONTINUE-HERE.md`, traps section). The working division is: the operator runs `gcloud builds submit` by typing it with the `!` prefix in the prompt, the agent recovers the substitutions into shell variables so no key literal is typed, then polls by build id and does the deploy and the proofs. The operator's terminal times out at two minutes while the build continues server-side, so the build id from the `Created […]/builds/<id>` line is polled; the build is never resubmitted.

## 13.7 The deploy tags ledger

Tags are `YYYYmmdd-HHMMSS` build timestamps shared across the images of one deploy. Entries marked *(session)* come from session records rather than the repository.

| Tag | Date | Phase / task | Services and revisions | What shipped |
|---|---|---|---|---|
| (v1.0 archive) | 2026-07-20 | v1.0 close | `nestor-frontend-00010-ndr`, `nestor-api-00024-67b` | the cutover state, parity accepted with deferrals |
| `20260721-220957` | 2026-07-21 | Phase 16 | `tribunal-worker` for run `4cbb5311` | first green live run (`docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md:17`) |
| (Phase 18) | 2026-07-22 | Phase 18 | `nestor-api-00038-7jp`, `nestor-frontend-00017-gfr` | deliver / replace / report |
| `20260725-233634` | 2026-07-25 | Phase 15.1 | both Tribunal images | verification gates, tribunal 0012 |
| `20260727-085533` | 2026-07-27 | Phase 15.2 | all four services | question workshop, own researcher, SerpAPI, 0013; parked at V-01 |
| `20260728-094409` + `20260728-132637` | 2026-07-28 | 15.2.k + 15.3 | worker / api / frontend at the first tag; `nestor-api-00044-8bz` at the second (the 401/403 seam-retry fix); worker recreated as `tribunal-worker-00002-ztp` after the incident | gap plans 20–26, run page, tribunal 0014→0015, intake 0012→0013 |
| `20260805-111647` | 2026-08-05 | Phase 15.8 (waves 15.4–15.8) | `tribunal-api-20260805-111647-115349`, `tribunal-worker-00004-gnv`; `nestor-api-00044-8bz` and `nestor-frontend-00028-q52` confirm-only | tribunal 0016/0017/0018, three literal upgrade lines; measuring run `368ff3a0` (`.planning/STATE.md:52-58`) |
| `20260806-175613` | 2026-08-06 | quick `260806-dn8/lvt/o96` | three services (worker, api, `nestor-api`) | synthesis to Opus 5, run language wiring, gate context widened |
| `20260810-193000` | 2026-08-10 | Phase 21 | `tribunal-worker` + `nestor-frontend` rebuilt (`tribunal-api-20260810-193000-200954`, `nestor-frontend-20260810-193000`), `tribunal-api` at the shared tag | eight silent feed stages get bodies; no migration, no run |
| `20260812-100556` then `20260812-121358` | 2026-08-12 | Phase 22 | `tribunal-api-00020-rjw` / `nestor-frontend-00030-wvh`, then `tribunal-api-00021-t7k` / `nestor-frontend-00031-pkh` after the CR-01 + WR-01 fixes; worker `00007-l8x` and `nestor-api-00045-hdw` unchanged | verification report page, citation hygiene; the first tag is SUPERSEDED (it rendered a populated `degradation_reasons` list as `0`) |
| `20260813-101148` | 2026-08-13 | fix branch `fix/refresh-ssr-guard-and-skill-clock` | `nestor-api-00046-72r`, `nestor-frontend-00032-k74` | SSR auth guard + skill clock; live proof `/admin` 307 → 200 (`infra/DEPLOY-RUNBOOK.md:6010-6023`) |
| `20260813-155426` *(session)* | 2026-08-13 | Phase 23 | `nestor-frontend-00033-97g` only | funnel labels + honest work-phase banner; no deploy record commit exists in the repo |
| `20260831-124920` *(session)* | 2026-08-31 | quick `260831-*` | `nestor-api-00047-ghp`, `nestor-frontend-00034-2wx` | three-language skill output, client proposal tick, feed line fixes |
| `20260831-160956` | 2026-08-31 | quick `260831-*` (frontend follow-up) | `nestor-frontend-00035-zz2` | banner and dead-block cleanup (`.planning/CONTINUE-HERE.md:24`) |
| `20260901-134253` | 2026-09-01 | quick `260901-j6w`, `260901-lf2` | `tribunal-api-00023-bc6`, `tribunal-worker-00009-fkm` | engine stages to `claude-sonnet-5`, five Flash stages to `gemini-3.7-flash` (`.planning/CONTINUE-HERE.md:20-29`) |

⛔ No research run has executed on any deploy after `20260806-175613`. The audit bucket held 10 run prefixes with the newest write at `2026-08-31T08:43:24Z` on 2026-09-01 (`.planning/CONTINUE-HERE.md:29`), and that write predates the model switch. See [11 — Models and providers](11-models-and-providers.md).

## 13.8 Cloud Build configs

Ten configs exist: one at the repo root, one under `frontend/`, eight under `tribunal/`. None is wired to a trigger. The root config's header says the trigger and the required-check wiring are "DEFERRED TO THE USER" because "no CI runner exists in the repo yet" (`cloudbuild.test.yaml:18-20`; `infra/README.md:273-297`). Every gate below is submitted by hand before a deploy.

| Config | What runs | Database | Assertion / marker | When it runs |
|---|---|---|---|---|
| `cloudbuild.test.yaml` (root, 92 lines) | `pip install uv; uv pip install -e '.[dev]'; python -m pytest tests -m integration -v` in `python:3.12-slim` from `backend/` | `pgvector/pgvector:pg16` container `nestor-test-pg` on the `cloudbuild` network; `DATABASE_URL=postgresql+pg8000://test:test@nestor-test-pg:5432/test` bypasses testcontainers | non-zero pytest exit fails the build; **only the `integration` marker runs**, so the rest of the 59-file backend suite is not exercised here; timeout 1200s | the QA-01 cross-tenant denial gate; submit from the repo root, never from `backend/` (`infra/DEPLOY-RUNBOOK.md:1113-1116`) |
| `frontend/cloudbuild.yaml` (43) | `docker build` with `--build-arg` for `VITE_API_BASE_URL`, `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_PROJECT_ID` from `_API_BASE_URL`, `_FB_API_KEY`, `_FB_AUTH_DOMAIN`, `_FB_PROJECT_ID`; pushes `_IMAGE` | none | the D-11 bundle guard runs inside the image build; timeout 1200s | every frontend build; a config exists because `--tag` cannot pass build args (`frontend/cloudbuild.yaml:3-7`) |
| `tribunal/cloudbuild.api.yaml` (35) | `docker build -f infrastructure/cloud-run/api/Dockerfile -t ${_IMAGE} .` from `tribunal/` | none | none; timeout 1200s | every `tribunal-api` image |
| `tribunal/cloudbuild.worker.yaml` (34) | same with the worker Dockerfile | none | none; timeout 1200s | every `tribunal-worker` image |
| `tribunal/cloudbuild.test.yaml` (91) | full `pytest nestor_pulse_sdk/tests/` in `python:3.11-slim` under `--network=host` with the Docker socket mounted, `TESTCONTAINERS_RYUK_DISABLED=true` | testcontainers `postgres:15`, which **does not start** under host networking (port bindings rejected); 42 real skips | exits 0 on skips: treat as NOT PROVEN (`tribunal/cloudbuild.test.yaml:27-58`); E2_HIGHCPU_8; 3600s | historical full suite, superseded by the targeted gates |
| `tribunal/cloudbuild.test-critical.yaml` (36) | `test_schema_isolation.py`, `test_advisory_lock_exactly_once.py`, `test_hash_chain_replay.py`, `test_verification_report_endpoint.py` as the `postgres` superuser | `postgres:15` on host network; roles `worker_user` / `app_user` pre-created; `search_path=tribunal,public` | proven 22/22 on 2026-07-20; RLS file excluded because a superuser bypasses RLS (`:7-9`); 1800s | the DB-bound engine tests |
| `tribunal/cloudbuild.test-rls.yaml` (112) | `alembic upgrade head` **as `app_user`**, then `test_rls_isolation.py -m "not live"` as that non-superuser | `postgres:15`, database `tribunal OWNER app_user` | anti-false-green: the summary line must contain `6 passed` and no `skipped|failed|error` (`:98-104`); 1200s | Phase 15.2 ENGINE-11 RLS gate |
| `tribunal/cloudbuild.seam-gate.yaml` (98) | `test_seam_denial.py` + `test_seam_rls_denial.py` as `app_user` | same pattern | must contain exactly `8 passed`, any skip is red (`:84-89`); 1200s | Phase 14 SEAM-02 denial gate |
| `tribunal/cloudbuild.test-gates.yaml` (196) | 13 pure files (gate replay, selector, failure modes, calibration, superseded verdict, buckets, fail-loud, grouping, distiller, adjudicate, verdict publication, stage schema, verdict write path) with `-m "not live"` | none, keyless | `EXPECTED_FILES=13` (`:161`); baseline 187 passed / 2 deselected; 1800s | Phase 15.1 verification-gate regression gate |
| `tribunal/cloudbuild.test-engine.yaml` (570) | 45 pure engine files with `-m "not live"` | none, keyless | `EXPECTED_FILES=45` (`:535`); last recorded green `1945 passed, 14 skipped` at `collecting: 45 of 45` (`infra/DEPLOY-RUNBOOK.md:5493-5494`); 1800s | the engine fast gate since Phase 15.2 |

**The `EXPECTED_FILES` assertion and the trap it closes.** Both pure gates build their file list with `ls $WANTED 2>/dev/null || true`, which was a wave-ordering accommodation: the config landed before its test files existed, so a missing file had to be a skip rather than a collection error. That made a mistyped path a silent skip, and an empty collection was once rewarded with an early `exit 0` (`tribunal/cloudbuild.test-gates.yaml:36-49`). The count assertion pins how many paths the list names, counts what `ls` collected, and fails the build naming each absent path; the early exit is gone (`test-gates.yaml:161-190`, `test-engine.yaml:535-564`). The two halves are both load-bearing: drop `|| true` and one missing file aborts the script before pytest; drop the assertion and the gate goes green having run less than it claims. The gates config had **no** completeness assertion until plan 15.8-07 on 2026-08-04 (`test-gates.yaml:41-49`); the engine config gained it in plan 15.2-26 on 2026-07-27 (`test-engine.yaml:27-31`). The `-m "not live"` filter is also load-bearing: `pyproject.toml` only registers the `live` marker, so without the filter a live-marked test would fire a real LLM call from CI (`test-engine.yaml:12-18`). Cloud Build caps one step argument at 10,000 characters, which is why the rationale lives in YAML comments and why no apostrophe may appear inside the single-quoted shell string (`test-gates.yaml:17-26`, `:138-146`).

**Test inventory the gates draw from** (counted 2026-09-03): 59 `backend/tests/test_*.py` files (266 collected ids on 2026-08-13, `infra/DEPLOY-RUNBOOK.md:6058`); 94 `tribunal/nestor_pulse_sdk/tests/test_*.py` files, of which 45 are in the engine gate, 13 in the gates gate, 4 in the critical gate, 1 in the RLS gate, 2 in the seam gate; 9 vitest files under `frontend/src/**/*.test.ts`, all pure `lib/` code, no component or route test (`infra/DEPLOY-RUNBOOK.md:6055-6057`). See [15 — Quality and testing](15-quality-and-testing.md).

## 13.9 Guard scripts

Each script's exit code is the gate, each has a negative self-test that plants an offender in a temp directory, and none gates on a `grep -c … == 0` construct.

| Script | Bans | Scope | Source |
|---|---|---|---|
| `backend/scripts/ci_no_permissive_rls.sh` (51 lines) | constant-true `USING` / `WITH CHECK` RLS policies, the inherited Supabase bug (QA-02) | `backend/app/db/alembic/versions/` | header `:1-20` |
| `backend/scripts/ci_no_raw_db_access.sh` (70) | raw engine / session symbols outside `app/db/` (D-03) | `backend/app/` | header `:1-25` |
| `backend/scripts/ci_no_run_research.sh` (111) | any genuine invocation, route or trigger of `run-research` / Tribunal from the intake side (INTAKE-05, the `decomposed` scope ceiling); prose mentions exempt; deliberately does not scan `tribunal/` | `backend/app/` + `frontend/src/` | header `:1-25`; `infra/DEPLOY-RUNBOOK.md:4690` |
| `backend/scripts/ci_no_sa_json_key.sh` (68) | `from_service_account_file`, `service_account.json`, `GOOGLE_APPLICATION_CREDENTIALS=*.json` (T-09-01) | `backend/app/` | header `:1-25` |
| `frontend/scripts/ci_no_hardcoded_dutch.sh` (103) | Dutch stopword literals in `.ts` / `.tsx`; exempts `locales/`, `*.gen.ts`, `ui/`, `admin.sales.*`, `coming-soon*`, tests (I18N-01) | `frontend/src` | header `:1-25` |
| `frontend/scripts/ci_no_supabase_in_bundle.sh` (104) | Supabase URL, `VITE_SUPABASE`, anon marker, JWT prefix in `.output/` (D-11); runs inside the Docker build stage | the built bundle | `frontend/Dockerfile:57`; header `:1-25` |
| `frontend/scripts/i18n-audit.mjs` | CHECK A three-way nl/fr/en key parity, CHECK B every literal `t("key")` resolves, CHECK C zero two-arg fallbacks (hard); CHECK D hardcoded strings (advisory) over namespaces `admin, auth, common, intake` | `frontend/src` minus `ui/`, `mock-backend/`, `locales/` | `:7-13`, `:22-27` |

The audit's blind spot: CHECK B matches only single-argument literal `t("key")` calls, so interpolated keys are invisible to it, and CHECK D never fails the build (`i18n-audit.mjs:9-13`). See [12 — Frontend](12-frontend.md).

## 13.10 Dockerfiles

| Image | Base | Build stage | Runtime | Source |
|---|---|---|---|---|
| backend | `python:3.12-slim`, two stages | `uv pip install --system .` (`:62`); copies `alembic.ini` and `scripts/` so the same image runs the migrate and seed Jobs (`:55-60`); build-time smoke `python -c "import fastapi, uvicorn, sqlalchemy, alembic, pg8000, google.cloud.sql.connector, pgvector, pydantic_settings, app.main"` (`:68`) | one Uvicorn process, `uvicorn app.main:app --port ${PORT}` (`:93`); no migration at startup (D-05); no secret baked | `backend/Dockerfile` |
| frontend | `node:22-slim`, two stages | four public `ARG` → `ENV` (`:33-40`); `npm ci` (`:45`); `npm run build` (Nitro node-server, `:51`); `bash scripts/ci_no_supabase_in_bundle.sh .output` (`:57`) | copies only `.output`; `node .output/server/index.mjs` (`:77`); no `VITE_SUPABASE_*` ARG exists (`:16-21`) | `frontend/Dockerfile` |
| tribunal-api | `python:3.11-slim`, two stages | `pip install -r requirements.txt` | copies `nestor_pulse_sdk` + `nestor_pulse` (`:37-38`); `uvicorn nestor_pulse_sdk.server:app` (`:43`) | `tribunal/infrastructure/cloud-run/api/Dockerfile` |
| tribunal-worker | same | same | same copies (`:32-33`); `python -m nestor_pulse_sdk.runs.worker` (`:36`); no port, no HTTP | `tribunal/infrastructure/cloud-run/worker/Dockerfile` |

Two Python minors run in production: 3.12 for the intake API (`backend/pyproject.toml:6` requires `>=3.12`) and 3.11 for the engine (`tribunal/pyproject.toml:9` requires `>=3.11`). See [03 — Architecture](03-architecture.md) for why the two codebases stayed separate.

## 13.11 Live revisions at `c8b8583`

All four digest-proven on 2026-09-01 (`.planning/CONTINUE-HERE.md:16-27`).

| Service | Revision | Tag |
|---|---|---|
| `nestor-frontend` | `nestor-frontend-00035-zz2` | `20260831-160956` |
| `nestor-api` | `nestor-api-00047-ghp` | `20260831-124920` |
| `tribunal-api` | `tribunal-api-00023-bc6` | `20260901-134253` |
| `tribunal-worker` | `tribunal-worker-00009-fkm` | `20260901-134253` |

Alembic heads: intake 0013, engine 0018 (unchanged since 2026-08-05). Worker env at the last read-back: `NESTOR_WORKER_STALE_MINUTES=60`, `NESTOR_TRIBUNAL_UNCAPPED=1`, `NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol`, no `NESTOR_TRIBUNAL_WORKSHOP_*` override (`.planning/STATE.md:52-58`).

## 13.12 Local development

### 13.12.1 Mock mode (no GCP)

Two processes: the frontend dev server, `cd frontend && npm run dev -- --port 5000 --host`, and the Express mock backend, `node mock-backend/server.js` on port 3001 (`replit.md:14-21`). `frontend/.env.local` (gitignored) sets `VITE_MOCK_AUTH=1`, `VITE_API_BASE_URL=/api` and fake `VITE_FIREBASE_*` values; Vite proxies `/api` to port 3001 (`CHANGES-FOR-CLAUDE-CODE.md:8-42`). The flag is read at `frontend/src/lib/firebase.ts:13` as `MOCK_AUTH`; `currentIdToken()` then returns a fixed mock token, the auth context delegates to a mock superadmin (`uid mock-user-001`, `admin@example.com`), and five route guards return early (`CHANGES-FOR-CLAUDE-CODE.md:46-132`).

`mock-backend/server.js` (687 lines) fakes one space, users, templates, an organisation, one intake per status, and per-intake skill runs; it serves `/auth/session`, `/me`, the admin users, spaces, templates and organisations routes, the intake CRUD and transition verbs, answers, the skill endpoints (transcribe returns a 202 stub), `skill-runs` with the `{latest, runs}` contract, an SSE stream that answers 404, research endpoints that return empty lists or a single done event, storage with placeholder signed URLs, and an empty search. Unimplemented routes return 501 so a gap fails loudly (`CHANGES-FOR-CLAUDE-CODE.md:149`).

| Works in mock mode | Does not work |
|---|---|
| the full admin UI (product picker, intakes list, users, spaces, templates, organisations); create, patch and transition intakes; invite, deactivate, reactivate users; spaces and templates CRUD; the user intake flow at `/intake` | real Firebase authentication; file uploads (placeholder URLs); skill-run SSE streaming; research and decomposition (empty arrays); the Supabase-backed Sales pages, inert without `VITE_SUPABASE_URL` |

Source: `replit.md:23-38`.

### 13.12.2 Against real GCP from a laptop

Remove `VITE_MOCK_AUTH`, set `VITE_API_BASE_URL` and the three `VITE_FIREBASE_*` values (`replit.md:40-49`). Older runbook notes ran the frontend on port 8081 because 8080 is taken by a local Tomcat on the dev box (session record). The Replit-originated UI work reached `master` through branch `replit-ui-changes`, merged by quick `260723-ior` (14 commits by "Replit Agent").

### 13.12.3 What the dev box can and cannot run

- **Python.** The only interpreter on the box is gcloud's bundled Python 3.11.9. The engine suite runs locally in a venv in about 50 seconds when the explicit file list from `cloudbuild.test-engine.yaml` is used (never the bare `tests/` directory, which gives order-dependent caplog failures). The backend suite needs `>=3.12` (`backend/pyproject.toml:6`), so `pip install -e backend` fails outright; run it through `cloudbuild.test.yaml` and never claim a local run (session record 2026-08-31).
- **Docker.** Absent through most of the project (the D-10 note, `infra/DEPLOY-RUNBOOK.md:13`; `tribunal/cloudbuild.api.yaml:3`); a 2026-08-31 session record reports Docker 29.6.2 present. Docker alone does not close the 3.12 gap for the backend suite. Images are built server-side by Cloud Build either way.
- **Terraform.** Not installed; `releases.hashicorp.com` is firewall-blocked from the box, and the gcloud component cannot install non-interactively. IaC changes are applied by mirroring the `.tf` in gcloud (session record 2026-06-19).
- **gcloud.** Installed and authenticated with four accounts; read-only operations are unrestricted for the agent, and some write commands are classifier-blocked (section 13.6).

## 13.13 Why it is built this way

**One project, one region.** Context: the intake platform and the Tribunal engine started as two projects. Options: keep two projects with cross-project IAM, or re-home the engine. Decision: re-home into the intake project (see [17 · M-01](17-decision-log.md)); the target turned out to be the very project the engine already used, so teardown became a resource list (17 · D-02, Phase 13). Consequence: one Cloud SQL instance carries both schemas, with a separate Alembic line and version table for the engine (17 · M-03).

**IAM database auth for the intake API, no allowlist.** Context: the legacy system's failures were credential-shaped. Options: proxy sidecar with an IP allowlist and a password, or the connector with IAM. Decision: connector plus IAM, one stored credential only for the superadmin bypass role (17 · Phase 2 rows; `infra/main.tf:1-27`). Consequence: no DSN in any env or image on the intake side, `roles/cloudsql.instanceUser` on the runtime SA, and a max-instances cap sized to the tier.

**Password DSNs for the Tribunal services.** Context: the engine reads `DATABASE_URL` and its RLS depends on `worker_user` being a distinct role. Options: refactor the engine to the connector, or carry its convention. Decision: carry it, with built-in users and the unix-socket volume (`infra/main.tf:741-746`, 13-REVIEW CR-03). Consequence: two DB auth topologies coexist, and `tribunal-run` needs `cloudsql.client` but not `instanceUser`.

**A dedicated `tribunal-run` service account.** Context: Phase 13 ran the engine as `nestor-run`, which also held `identitytoolkit.admin` and the intake secrets. Decision: least-privilege split, six secrets and one bucket only (17 · D-04b, Phase 14). Consequence: the invoker binding on `tribunal-api` became a real gate because caller and callee differ, and a compromised worker cannot reach the intake surfaces.

**Defence in depth on the seam.** Decision: Cloud Run IAM restricts invocation to `nestor-run` and the app verifies the OIDC token's audience and caller email before trusting a tenant id (17 · D-04, Phase 14). Consequence: a mis-set IAM binding cannot silently open tenants; the seam gate config proves the denial paths.

**An always-on worker.** Context: runs take about 35 minutes and must start promptly. Options: Cloud Run Jobs per run, or a polling worker. Decision: a worker at `min-instances=1` with CPU never throttled, at the idle cost the script names (17 · D-04, Phase 13; 17 · M-09). Consequence: runs start within seconds, and the worker's boot behaviour makes deploy ordering a money question (section 13.6, step 9).

**Object retention, not Bucket Lock.** Context: EU AI Act Article 12 needs a tamper-evident record kept for years. Options: a locked bucket-level retention policy, or per-object Unlocked retention. Decision: mirror the old deployment's 7-year per-object retention and forbid Bucket Lock, which is irreversible (17 · D-09, Phase 13; `infra/main.tf:975-989`). Consequence: the engine sets retention on every blob and the SA needs `objectAdmin`.

**Uncapped spend.** `NESTOR_TRIBUNAL_UNCAPPED=1` is set on both Tribunal services. The $25 governor has never fired; two of six runs exceeded it; the operator re-confirmed "leave it uncapped" on 2026-09-01 (17 · D-07, Phase 13; 17.18). Consequence: the question caps are the only spend control, and cost is surfaced on the run page instead.

**Frontend as a public SSR container with build-time config.** Decision: Cloud Run instead of Cloudflare Workers, public `allUsers` invoker, all public config inlined by Vite at build time, and a build-time guard proving no Supabase signature ships (17 · P-07, D-08, D-11). Consequence: a frontend build needs the five substitutions, and a wrong one breaks the live frontend silently.

**Terraform by construction, deploy by runbook.** Context: the dev box had no Terraform and the first deploy was done from Cloud Shell with gcloud. Options: adopt state and import, or keep the runbook as the control surface. Decision, repeated each phase: keep the Terraform as the intended end-state and record every manual step in the runbook (17 · D-03, Phase 13; `.planning/STATE.md:520`). Consequence: the drift list in section 13.4, and a runbook that is also the deploy history.

## 13.14 Known gaps and traps

- **IaC drift, carried since Phase 5.** Terraform state never adopted; every resource applied by gcloud; `terraform import` never run. Reconciling would need the `ignore_changes` guards on the two Tribunal user passwords to hold, or the services go down (`infra/main.tf:848-854`; `.planning/STATE.md:520`).
- **No CI trigger.** Every Cloud Build gate is submitted by hand; the "REQUIRED status check" of `cloudbuild.test.yaml` was never created (`cloudbuild.test.yaml:18-20`). A merge that skips the gates is not blocked by anything.
- **The root gate runs only `-m integration`.** The rest of the backend suite is exercised only when someone runs it in Cloud Build or on a 3.12 interpreter; the 2026-08-31 deploy shipped without the orchestrator re-running it (session record).
- **`tribunal/cloudbuild.test.yaml` is a false green.** Its testcontainers fixture never starts; 42 skips exit 0 (`tribunal/cloudbuild.test.yaml:27-58`). Treat it as NOT PROVEN.
- ⚠ **The worker claims first and sleeps last.** `--min-instances=0` does not stop a boot from claiming; the 2026-07-28 incident re-executed about 15 minutes of paid pipeline (`tribunal/nestor_pulse_sdk/runs/worker.py:661-665`, `:700`; `infra/DEPLOY-RUNBOOK.md:2960-2977`).
- ⚠ **`--set-secrets` and `--set-env-vars` replace whole sets.** A hand-typed deploy with a partial list drops bindings; the scripts compose full lists for this reason (`deploy-worker.sh:77-83`). On 2026-07-21 a script default silently repointed the Anthropic key back to a low-credit secret and walled a live run (`deploy-worker.sh:84-96`).
- ⚠ **`build-and-push.sh` is stale and reports success** while building to the retired `nestor-pulse` repository (`build-and-push.sh:20-24`; `infra/DEPLOY-RUNBOOK.md:5363-5367`).
- ⚠ **The gcloud account drifts mid-session.** Four accounts; `gcloud auth login` overwrote a correction asynchronously on 2026-08-05; the config sat on `tools@epicimpact.be` on 2026-08-13 and again on 2026-09-01 (`infra/DEPLOY-RUNBOOK.md:4364-4383`, `:6036-6041`; `.planning/CONTINUE-HERE.md`, traps). `--format='value(...)'` renders a permission error as an empty string, so an empty read must be re-run without `--format` before it is believed (`infra/DEPLOY-RUNBOOK.md:4826-4830`).
- ⚠ **`builds submit | tail` exits 0 on a failed build** (`infra/DEPLOY-RUNBOOK.md:4689`). Read the status off the build resource.
- ⚠ **`/healthz` on `nestor-api` answers a Google 404 from upstream** while `/readyz` answers 200; pre-existing and not caused by the app (session record 2026-08-31). Smoke on `/readyz`.
- ⚠ **Secret bindings on the Tribunal services differ from Terraform.** `Nestor_Claude_Temp` (a burner key that transited a chat in plaintext on 2026-07-27) has been live on both services since 15.2.k; its rotation is deferred to go-live by operator ruling 2026-08-03 (`infra/DEPLOY-RUNBOOK.md:4033`, `:4364-4366`; 17.18). Which Anthropic secret `nestor-api` mounts is not determined from the code; read it with `describe`.
- ⚠ **Revision names are not comparable across deploy methods.** Script deploys pass `--revision-suffix`; hand deploys auto-number. Only digests prove a deploy (`infra/DEPLOY-RUNBOOK.md:5514-5527`).
- ⚠ **A migrate Job with an unpinned image is a silent no-op.** Repin before executing and find the literal upgrade line (`infra/DEPLOY-RUNBOOK.md:1423`, `:4674`).
- ⛔ **Nothing deployed after 2026-08-06 has run.** The engine models switched on 2026-09-01 have never executed a run; every cost figure after that date is arithmetic (`.planning/CONTINUE-HERE.md:8-12`).
- **Deploy records for `20260813-155426` and `20260831-124920` exist only in session notes**, not in the runbook. The runbook's dated records stop at the 2026-08-13 fix deploy (`infra/DEPLOY-RUNBOOK.md:5751-6072`).
- **Legacy standalone resources** (`nestor-pulse-api`, `nestor-pulse-worker`, Cloud SQL `nestor-prod-pg`, repository `nestor-pulse`) were never torn down; Step 13.i is deferred (git `cddf1f5`).
- **Ingress is unset on every service**, so Cloud Run's default applies; `tribunal-api` relies on the invoker binding plus the in-app check rather than an internal-only ingress (`infra/main.tf:1266-1273`).
- **Terraform declares no memory or concurrency**, so the live values for `nestor-api` and `nestor-frontend` are not determined from the code.

## 13.15 Where to look

| Path | Responsibility |
|---|---|
| `infra/main.tf` | every GCP resource with its rationale comments; the IaC-DRIFT markers |
| `infra/variables.tf` | names, defaults and which values are seeded out of band |
| `infra/providers.tf` | provider pins; the commented-out remote-state backend |
| `infra/outputs.tf` | the five outputs the runbook consumes |
| `infra/README.md` | the Phase 2–4 base deploy: APIs, two-step apply, migrate Job, superadmin seed, the deferred CI trigger, the `/readyz` proof |
| `infra/DEPLOY-RUNBOOK.md` | Phase 7 onward, per-phase procedures and the dated deploy records with digests; § 15.2.k carries the worker-last correction; § Phase 21 carries the surface-derivation method; the summary checklist at `:4607-4707` |
| `cloudbuild.test.yaml` | the backend integration gate (real pgvector Postgres) |
| `frontend/cloudbuild.yaml`, `frontend/Dockerfile` | frontend image build with the four public build args and the D-11 bundle guard |
| `backend/Dockerfile` | the one intake image that serves the API and both Jobs |
| `tribunal/cloudbuild.api.yaml`, `tribunal/cloudbuild.worker.yaml` | the two Tribunal image builds |
| `tribunal/cloudbuild.test-engine.yaml`, `tribunal/cloudbuild.test-gates.yaml` | the two keyless pure gates with `EXPECTED_FILES` |
| `tribunal/cloudbuild.test-rls.yaml`, `tribunal/cloudbuild.seam-gate.yaml`, `tribunal/cloudbuild.test-critical.yaml` | the three DB-bound gates |
| `tribunal/cloudbuild.test.yaml` | the historical full suite (not proven) |
| `tribunal/infrastructure/cloud-run/deploy-worker.sh`, `deploy-api.sh` | the retargeted deploy scripts with secret composition and the `MIN_INSTANCES` override |
| `tribunal/infrastructure/cloud-run/build-and-push.sh`, `artifact-registry-create.sh`, `DEPLOY.md` | stale standalone-era tooling; do not use |
| `tribunal/infrastructure/cloud-run/api/Dockerfile`, `worker/Dockerfile` | the two engine images |
| `tribunal/.gcloudignore` | what is excluded from the Cloud Build source archive |
| `backend/scripts/ci_*.sh`, `frontend/scripts/ci_*.sh`, `frontend/scripts/i18n-audit.mjs` | the grep guards and the i18n audit |
| `backend/app/main.py:194-200` | `/healthz` and `/readyz` |
| `tribunal/nestor_pulse_sdk/runs/worker.py:661-700` | the claim-first / sleep-last loop |
| `tribunal/nestor_pulse_sdk/audit/gcs_blob.py` | the 7-year per-object retention writer |
| `replit.md`, `CHANGES-FOR-CLAUDE-CODE.md`, `mock-backend/server.js`, `frontend/src/lib/firebase.ts` | local mock mode |
| `.planning/CONTINUE-HERE.md` | live revisions and the current traps |
| `.planning/STATE.md` | the IaC-drift blocker entry, the 2026-08-05 deploy record, the quick-task ledger |
