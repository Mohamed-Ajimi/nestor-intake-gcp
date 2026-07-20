# Nestor Intake — Phase 7 AI-seam deploy runbook (Cloud Shell)

This is the **deferred-execution** runbook for the Phase-7 AI function ports
(D-07 / D-01a). It complements `infra/README.md` (the Phase-2 base deploy) and
covers only the **new surface this phase adds**:

1. the two AI provider keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`) as Secret
   Manager secrets injected natively into the Cloud Run service env, and
2. the Cloud Run **CPU-always-allocated + scale-to-zero** configuration that lets
   the long LLM/embedding/Whisper calls finish reliably without a warm pool.

As with the rest of the project, the dev box has **no Python, Docker, Terraform,
or gcloud** (D-10), so every step below is **run by you in GCP Cloud Shell**. The
HCL + this runbook are authored by construction; the live `apply` is deferred.

> **Secret hygiene (T-7-05) — read first.** The API keys must NEVER be echoed,
> logged, pasted into a chat/issue/PR, or committed to IaC/state. Add them only as
> Secret Manager **versions** (Step 2). Do **not** pass them via
> `TF_VAR_anthropic_api_key` / `TF_VAR_openai_api_key` in a shared environment —
> that path writes the value into Terraform state. The drift-honest default
> (`*_version` resource `count = 0`) exists precisely so the value never enters
> state.

---

## ⚠️ IaC-DRIFT reality (carry-over from the Phase 5 blocker)

**Terraform state was never adopted for this project.** Phase 2 deployed
**gcloud-native**, and the live Phase-5 deploy required **manual** grants the
committed `infra/*.tf` never applied (identitytoolkit.admin, allUsers invoker,
`SUPERADMIN_DB_PASSWORD_SECRET` env + secretAccessor, CORS origins — see
`.planning/STATE.md` "Phase 5 follow-up — IaC DRIFT" and `05-UAT.md` Gaps).

**The two new AI-key grants below extend that drift.** Until Terraform state is
adopted (`terraform import`), treat the steps in this runbook as the **manual**
reconciliation that must be performed by hand on the live service — the `*.tf`
edits in this phase are the *intended* end-state, not something that has been
`apply`-ed. Reconcile (import) or keep applying manually **before the Phase 12
cutover**.

Additionally — **the image-only redeploy gap recurs** (memory:
`phase-06-backend-not-deployed`). The `anthropic` / `openai` SDKs are not in the
running container until the image is **rebuilt via Cloud Build** (Terraform/registry
downloads are blocked on the dev box, so the image must be built in Cloud Shell /
Cloud Build, never locally). A `terraform apply` that only flips config will NOT
pull new Python deps into the image — you must rebuild + redeploy the image too.

---

## Step 1 — Create the two secrets (resource only)

The `infra/main.tf` edits declare:

- `google_secret_manager_secret.anthropic_api_key`  (id: `nestor-anthropic-api-key`)
- `google_secret_manager_secret.openai_api_key`     (id: `nestor-openai-api-key`)
- a resource-scoped `roles/secretmanager.secretAccessor` grant to the runtime SA
  (`nestor-run@…`) on **each** secret.

If you are applying via Terraform once state is adopted:

```bash
cd infra
terraform apply \
  -target=google_secret_manager_secret.anthropic_api_key \
  -target=google_secret_manager_secret.openai_api_key \
  -target=google_secret_manager_secret_iam_member.runtime_anthropic_secret_accessor \
  -target=google_secret_manager_secret_iam_member.runtime_openai_secret_accessor
```

**MANUAL equivalent (the current drift reality — state not adopted):**

```bash
export GOOGLE_PROJECT="<your-project-id>"
export RUNTIME_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"

# Create the secret containers (empty — no version yet).
gcloud secrets create nestor-anthropic-api-key --replication-policy=automatic --project="$GOOGLE_PROJECT"
gcloud secrets create nestor-openai-api-key    --replication-policy=automatic --project="$GOOGLE_PROJECT"

# Resource-scoped secretAccessor to the runtime SA (least privilege — NOT project-wide).
gcloud secrets add-iam-policy-binding nestor-anthropic-api-key \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"
gcloud secrets add-iam-policy-binding nestor-openai-api-key \
  --member="serviceAccount:${RUNTIME_SA}" --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"
```

## Step 2 — Add the key VALUES as secret versions (out-of-band, never logged)

Add the actual keys as versions. The recommended path keeps the value off the
shell history and out of Terraform state. Read the key from a file or a prompt —
do **not** type it inline where it lands in history:

```bash
# Reads from stdin; paste the key, then Ctrl-D. Nothing is echoed to history.
gcloud secrets versions add nestor-anthropic-api-key --data-file=- --project="$GOOGLE_PROJECT"
gcloud secrets versions add nestor-openai-api-key    --data-file=- --project="$GOOGLE_PROJECT"
```

The Cloud Run env binds `version = "latest"`, so the service picks up whatever
version exists here — no further config change needed when you rotate a key (add
a new version; `latest` follows it on the next revision).

> Do **not** set `TF_VAR_anthropic_api_key` / `TF_VAR_openai_api_key` in shared
> CI/Cloud-Shell sessions. Those vars exist only for a single-operator, throwaway
> environment; in any shared context they leak the value into state (T-7-05).

## Step 3 — Rebuild the image with the AI SDKs (Cloud Build) and redeploy

The running container does **not** contain `anthropic` / `openai` until rebuilt.
Build in Cloud Build (the dev box cannot build images), push to Artifact Registry,
then point the service at the new tag:

```bash
export REGION="europe-west1"
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (NOT a local docker build — downloads are blocked on dev).
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"

# Re-apply with the real tag (adopted state) …
cd infra && terraform apply -var "image_tag=${IMAGE##*:}"
# … OR the manual equivalent:
gcloud run services update nestor-api --region "$REGION" --image "$IMAGE" --project="$GOOGLE_PROJECT"
```

## Step 4 — Set CPU always-allocated + min-instances=0, and inject the keys

The `infra/main.tf` service template now sets:

- `template.scaling.min_instance_count = 0` — **scale to zero**, warm-pool knob OFF
  (D-01a). `max_instance_count = 4` stays capped so worst-case pooled connections
  stay under the Cloud SQL tier (D-04 / T-7-15).
- `template.containers.resources.cpu_idle = false` — **CPU always-allocated** (the
  v2-API equivalent of the `run.googleapis.com/cpu-throttling = "false"` annotation),
  so request-spawned background work (the 90–120s LLM/Whisper calls, AI-06) runs to
  completion without CPU throttling even with no warm pool.
- two `env { value_source { secret_key_ref { … version = "latest" } } }` blocks
  injecting `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` **natively** from Secret
  Manager (no runtime `access_secret_version` call).

**MANUAL equivalent (drift reality):**

```bash
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --min-instances=0 --max-instances=4 \
  --no-cpu-throttling \
  --update-secrets=ANTHROPIC_API_KEY=nestor-anthropic-api-key:latest,OPENAI_API_KEY=nestor-openai-api-key:latest
```

(`--no-cpu-throttling` is the gcloud surface for `cpu_idle = false` /
`run.googleapis.com/cpu-throttling = "false"`.)

## Step 5 — Verify (without printing secrets)

```bash
# The env vars are PRESENT but their values are Secret Manager references — gcloud
# shows the secret name, never the value. Confirm the wiring, do NOT echo the key.
gcloud run services describe nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.containers[0].env[].name)'

# Confirm CPU + scaling.
gcloud run services describe nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='yaml(spec.template.metadata.annotations, spec.template.spec.containerConcurrency)'
```

Never run a command that prints the secret payload (`gcloud secrets versions
access …`) into a shared log. The scope-guard test
(`backend/tests/test_scope_guard_ai.py`) and `scripts/ci_no_run_research.sh` keep
the flow ceiling at `decomposed` — these keys must never reach `run-research`.

---

## Phase 8 — SSE skill-run-progress: image redeploy + 900s request timeout

Phase 8 adds a live Server-Sent-Events stream for skill-run progress. Two manual
steps make it work on the **live** `nestor-api` service. Both are executed during
the **combined 7+8 UAT (D-10)** — NOT during plan execution.

> **⚠️ IaC-DRIFT (same reality as above).** Editing `infra/main.tf` (which now
> declares `template.timeout = "900s"`) **does NOT change the live service** —
> Terraform state was never adopted, so the `.tf` edit is the intended end-state
> only. The timeout is **not applied** until you run the `gcloud run services
> update … --timeout=900` command below by hand. Do not assume the `.tf` diff
> shipped anything live.

### Step 8.1 — Redeploy the backend image (new stream + full-run endpoints)

The new routes `GET /intakes/{id}/skill-runs/stream` (the SSE `text/event-stream`)
and `GET /intakes/{id}/skill-runs/{run_id}` (terminal full-run fetch) do not exist
in the running container until the image is rebuilt. Reuse the Step-3 Cloud Build
idiom (never a local `docker build` — downloads are blocked on the dev box):

```bash
export REGION="europe-west1"
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build, then repoint the service at the new tag.
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --image "$IMAGE" --project="$GOOGLE_PROJECT"
```

### Step 8.2 — Apply the 900s request timeout live (D-07)

Raise the request timeout so a long-lived `text/event-stream` connection is not
cut at the 300s Cloud Run default (streams reliably die at ~5 min otherwise). This
is the live equivalent of the `template.timeout = "900s"` now in `main.tf`:

```bash
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" --timeout=900
```

The 900s window is paired with the app's 10-min in-handler `MAX_STREAM_SECONDS`
cap (plan 08-01), so a hung run can never hold a connection for the full 900s.

### Step 8.3 — Verify (console + live stream)

```bash
# Confirm the live service now reports a 900s request timeout.
gcloud run services describe nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.timeoutSeconds)'   # expect: 900
```

- In the Cloud Run **console**, confirm the service **Request timeout** reads
  **900s** (not the 300s default).
- Open an intake and start a skill run: streamed progress events must arrive at a
  **~2s cadence** (a steady trickle), **not** as a single terminal burst — and the
  connection must **not drop at ~300s**. A terminal-only burst or a ~5-min drop
  means either the image redeploy (8.1) or the timeout apply (8.2) was skipped.

---

## Phase 9 — GCS storage: bucket + keyless signBlob IAM + image redeploy

Phase 9 replaces the legacy Supabase `nestor-uploads` bucket with a private, hardened
GCS bucket and grants the runtime SA exactly two things: **bucket-scoped**
`storage.objectAdmin` (read/write/delete objects) and a `serviceAccountTokenCreator`
**self-binding** so it can mint V4 signed download URLs via IAM **signBlob** — with
**no SA JSON key anywhere** (criterion 1). All steps run during the **combined 7+8+9
UAT (D-13)** — ONE deploy, ONE session — NOT during plan execution.

> **⚠️ IaC-DRIFT (same reality as the Phase 5/7/8 notes above).** The `infra/main.tf`
> edits from plan 09-04 (`google_storage_bucket.uploads`, the `objectAdmin` bucket
> binding, the `serviceAccountTokenCreator` self-binding, and the `STORAGE_BUCKET`
> env) are the **intended end-state only** — Terraform state was never adopted, so
> **nothing is live until you run the gcloud steps below by hand**. This extends the
> STATE.md IaC-drift list (D-11); reconcile via `terraform import` (or keep manual)
> **before the Phase 12 cutover**.

Preamble — export the env once (mirrors Step 3 / Step 8.1):

```bash
export GOOGLE_PROJECT="<your-project-id>"
export REGION="europe-west1"
export RUNTIME_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export BUCKET="${GOOGLE_PROJECT}-nestor-uploads"
```

### Step 9.1 — Create the private, hardened bucket (D-12/D-07a)

```bash
gcloud storage buckets create "gs://${BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --project="$GOOGLE_PROJECT"
```

`--uniform-bucket-level-access` makes IAM the ONLY access surface (no per-object
ACLs); `--public-access-prevention` guarantees **zero public objects** (a stray
allUsers grant cannot make an object world-readable, D-07a / T-09-14). No versioning,
no lifecycle rules (D-12 — out of scope this phase).

### Step 9.1b — Bucket CORS policy for browser `fetch()` of signed URLs (WR-02)

Two frontend paths (`FinalReportBlock` blob download, `ResearchResultsPanel`
`getArtifactText` for PDF generation) `fetch()` the signed GCS URL **directly** from the
app origin. A cross-origin `fetch` to `storage.googleapis.com` is browser-blocked unless
the bucket echoes the origin, so the bucket needs a CORS policy mirroring the Cloud Run
`CORS_ALLOWED_ORIGINS` allowlist. (The `window.open(url)` navigation download paths are
unaffected — this is only needed for the `fetch()`-then-blob paths.) Set the **same**
origins you set on `CORS_ALLOWED_ORIGINS` for the Cloud Run service.

```bash
# ORIGINS must match the Cloud Run CORS_ALLOWED_ORIGINS allowlist (the app frontend
# origins — Cloudflare Workers prod + any localhost dev origin).
cat > /tmp/uploads-cors.json <<'JSON'
[
  {
    "origin": ["https://REPLACE-WITH-FRONTEND-ORIGIN"],
    "method": ["GET"],
    "responseHeader": ["Content-Disposition", "Content-Type"],
    "maxAgeSeconds": 3600
  }
]
JSON

gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file=/tmp/uploads-cors.json \
  --project="$GOOGLE_PROJECT"
```

Read-only (`method: ["GET"]`) — uploads and deletes go **through the backend**, never
browser→bucket, so no `POST`/`PUT`/`DELETE` is exposed cross-origin on the bucket. Both
consuming paths are post-`decomposed` gated today, so this is latent until those gates
open; apply it before then. (Terraform equivalent: the `dynamic "cors"` block on
`google_storage_bucket.uploads`, driven by `var.cors_allowed_origins`.)

### Step 9.2 — Bucket-scoped `storage.objectAdmin` for the runtime SA (least privilege)

```bash
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin" \
  --project="$GOOGLE_PROJECT"
```

Scoped to **THIS bucket only** — NOT a project-wide `roles/storage.*` grant
(T-09-15). `objectAdmin` (not `objectViewer`/`objectCreator`) because the backend
both writes uploads and deletes objects on cleanup (D-09).

### Step 9.3 — Keyless signBlob grant: `serviceAccountTokenCreator` self-binding (criterion 1)

```bash
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_SA" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project="$GOOGLE_PROJECT"
```

This is the runtime SA impersonating **itself** to sign URLs via the IAM signBlob
API — **no SA JSON key** (T-09-13). It is a **SEPARATE** grant from the object access
in Step 9.2 (**Pitfall 2**): `objectAdmin` lets the SA read/write objects, but
signing a download URL requires the DISTINCT `iam.serviceAccountTokenCreator` role on
the SA principal itself. Skip this and `signed_download_url()` **403s at signBlob**
even though uploads/deletes work. The `scripts/ci_no_sa_json_key.sh` guard (09-01)
enforces that no JSON-key signing path is ever committed.

### Step 9.4 — Rebuild the image with the storage deps + inject `STORAGE_BUCKET` (Pitfall 7)

The running container does **not** contain `google-cloud-storage` /
`python-multipart` until rebuilt (**Pitfall 7** — same image-only-redeploy gap as
Phase 7/8). Reuse the Step-3/8.1 Cloud Build idiom (never a local `docker build` —
downloads are blocked on the dev box), then repoint the service **and** set the
bucket env. **This same rebuild must ship the Phase-8 `skill-runs/stream` route** —
live Cloud Run is still **v12** (no stream route), so 8+9 land in ONE image:

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (pulls the new google-cloud-storage + python-multipart
# deps AND the Phase-8 stream route into the image), then repoint the service.
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE" \
  --update-env-vars="STORAGE_BUCKET=${BUCKET}"
```

`STORAGE_BUCKET` is a plain non-secret env (D-09) — the live equivalent of the
`main.tf` service `env { name = "STORAGE_BUCKET" … }` block, inert until this
command runs.

### Step 9.5 — Combined 7+8+9 live UAT (D-13): ONE deploy, ONE session

Run the whole pre-research flow end-to-end on the deployed service in a single
session. This closes the **deferred Phase-7 UAT** (STATE.md pending todo) and the
**Phase-8 SSE UAT** together with the new storage surface:

1. Log in, open an intake.
2. **Upload** an attachment **and** an audio file (Phase 9 upload path).
3. Confirm **transcribe** runs on the audio (Phase 7 Whisper seam over the uploaded
   object).
4. Run **structure-answers** / **extract-insights** and then **apply-intake-skill**,
   watching the **SSE progress stream** arrive at a ~2s cadence (Phase 8 — the stream
   route must have shipped in the Step-9.4 rebuild).
5. **Download** the produced artifacts via the **signed URLs** — confirm each forces
   an **attachment** download with the **original filename** and the URL **expires
   ≤15 min** (D-10 TTL clamp).
6. Confirm criterion 1: **no SA JSON key** exists anywhere in the environment.

Failure triage: signBlob **403** → the Step-9.3 `serviceAccountTokenCreator`
self-binding is missing (**Pitfall 2**). Upload **422** → the FormData Content-Type
guard (**Pitfall 3**). A storage endpoint **500** with `ModuleNotFoundError` → the
Step-9.4 image rebuild did not include `google-cloud-storage` / `python-multipart`
(**Pitfall 7**).

---

## Phase 10 — Notifications: Resend secret + mail env vars + jinja2 image rebuild

Phase 10 adds the transactional-email (Resend) send path. The mail module (Plan 01) and
the endpoints (Plan 03) are **inert live** until the `RESEND_API_KEY` secret and the two
non-secret mail env vars exist on Cloud Run **and** the image is rebuilt to include
`jinja2`. `RESEND_API_KEY` is the ONLY new secret this phase adds (`agenic.be` sender
domain already verified, D-13).

> **⚠️ IaC-DRIFT (same reality as the Phase 5/7/8/9 notes above).** The `infra/main.tf`
> `google_secret_manager_secret.resend_api_key` trio (secret + version + resource-scoped
> secretAccessor), the `RESEND_API_KEY` `secret_key_ref` env, and the plain
> `NESTOR_ADMIN_EMAIL` / `APP_BASE_URL` envs are the INTENDED end-state only — they are
> INERT until applied out-of-band via the steps below. Reconcile via `terraform import`
> (or keep manual) **before the Phase 12 cutover**.

### Step 10.1 — Create the Resend secret (resource) + add the key VALUE (out-of-band)

```bash
# Create the secret container (empty — no version yet). Mirrors the Phase-7 Step-1 idiom.
gcloud secrets create nestor-resend-api-key \
  --replication-policy=automatic --project="$GOOGLE_PROJECT" 2>/dev/null || true

# Resource-scoped secretAccessor to the runtime SA (least privilege — NOT project-wide).
export RUNTIME_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
gcloud secrets add-iam-policy-binding nestor-resend-api-key \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"

# Add the key VALUE as a secret version. Reads from stdin; paste the key, then Ctrl-D.
# The value is added OUT-OF-BAND and is NEVER committed / echoed / logged (T-10-04).
gcloud secrets versions add nestor-resend-api-key --data-file=- --project="$GOOGLE_PROJECT"
```

### Step 10.2 — Set the two non-secret mail env vars on the live service

```bash
# NESTOR_ADMIN_EMAIL = the ops address that receives the admin_validated notification (D-08).
# APP_BASE_URL       = the deployed frontend origin used to build mail CTA links + logo URL (D-15).
# Plain non-secret envs (the live equivalent of the main.tf env { name = "NESTOR_ADMIN_EMAIL" … }
# / "APP_BASE_URL" blocks — inert until this command runs).
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars="NESTOR_ADMIN_EMAIL=<ops address>,APP_BASE_URL=<deployed frontend origin>"
```

### Step 10.3 — Map the RESEND_API_KEY secret to the service env (if not applied by Terraform)

```bash
# Native Secret Manager injection — gcloud stores the secret REFERENCE, never the value.
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --update-secrets="RESEND_API_KEY=nestor-resend-api-key:latest"
```

### Step 10.4 — REBUILD the backend image with `jinja2` (Cloud Build) — the recurring deploy-gap

The running container does **not** contain `jinja2` until rebuilt (**RESEARCH Pitfall 2** —
the same image-only-redeploy gap as Phase 7/8/9). CI can be green while a live mail send
500s with `ModuleNotFoundError: jinja2` in UAT if this step is skipped. Reuse the
Step-3/8.1/9.4 Cloud Build idiom (never a local `docker build` — downloads are blocked on
the dev box), then repoint the service:

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (pulls the new jinja2 dep into the image), then repoint.
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"
```

### Step 10.5 — Live mail UAT: trigger each mail type against the deployed rev

Trigger each of the five mail types on the deployed service and inspect the inbox for
visual parity + a working (authenticated, tokenless) CTA:

1. **invite** — send an invite; confirm the "Kies je wachtwoord" CTA points to the
   authenticated app route (no token, NOTIF-01).
2. **validation** — send the validation-link mail; confirm `validation_link_sent_at`
   updates **only on successful send** (D-16).
3. **results** — send the results-link mail; confirm `results_link_sent_at` updates only
   on success.
4. **reminder** — send a reminder; confirm the body + CTA render.
5. **admin_validated** — confirm the ops address (`NESTOR_ADMIN_EMAIL`) receives the
   admin notification.

Failure triage: a mail endpoint **500** with `ModuleNotFoundError: jinja2` → the Step-10.4
image rebuild did not ship `jinja2` (**Pitfall 2**). A **broken logo / dead CTA** →
`APP_BASE_URL` is unset or wrong (Step 10.2). An **auth error reaching Resend** →
`RESEND_API_KEY` secret version missing or not mapped (Steps 10.1 / 10.3).

---

## Phase 12 — Frontend deploy, backend catch-up & URL wiring

Phase 12 is the **cutover**: deploy the pending Phase-10/11 backend state (the D-04
catch-up), then containerize + deploy the TanStack Start (Nitro node-server) frontend on
Cloud Run (D-01 — the auto-generated run.app URL is v1's origin; no custom domain), then
wire that frontend URL back into the four live surfaces it must reach (CORS, APP_BASE_URL,
uploads-bucket CORS, Firebase authorized domains). The sequence is **strictly ordered**:
backend catch-up FIRST, then frontend build+deploy, then a **two-pass** URL wiring —
because the run.app URL is not known until the first frontend deploy.

> **⚠️ IaC-DRIFT (same reality as the Phase 5/7/8/9/10 notes above).** The `infra/main.tf`
> `google_cloud_run_v2_service.frontend` block + its `allUsers` invoker, the
> `frontend_service_name` / `frontend_image_tag` / `vite_*` vars, and the
> `frontend_service_url` output are the INTENDED end-state only — Terraform state was never
> adopted, so **nothing is live until you run the gcloud steps below by hand**. The frontend
> image must be built via **Cloud Build** (the dev box has no Docker; downloads are blocked).

> **🚫 D-08 — NO Supabase-side actions anywhere in this phase.** "Retirement" is redefined
> as **independence, not teardown**: do NOT pause, delete, or log into the legacy Supabase
> project, and do NOT touch the old Lovable/Cloudflare deploy (D-10). Independence is proven
> **code-side** — the frontend build never sets `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
> (so the env-guarded `supabase.ts` client stays `null`, D-09), and the `.output/` bundle
> guard (`frontend/scripts/ci_no_supabase_in_bundle.sh`, run in the image build) fails the
> build if any Supabase URL/anon-key signature leaks in (D-11). No Supabase step exists here
> by design.

Preamble — export the env once (mirrors Step 3 / Step 8.1 / Step 9 preamble):

```bash
export GOOGLE_PROJECT="<your-project-id>"
export REGION="europe-west1"
export RUNTIME_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export BUCKET="${GOOGLE_PROJECT}-nestor-uploads"
```

### Step 12.1 — Backend catch-up deploy (D-04) — THIS IS STEP ONE

The frontend deploy and the parity gate must start from a **fully-deployed** backend that
carries the Phase-10/11 code. The live backend (rev 00018) predates the Phase-10/11 Python
deps (`jinja2` / `httpx`) and the alembic `0010` migration, so a **Cloud Build image REBUILD
is mandatory** — a config-only env/secret flip ships a stale image and produces a live
`ModuleNotFoundError` in UAT while CI is green (**Pitfall 3 / the recurring project lesson**;
see Step 10.4). Perform, IN ORDER, reusing the already-documented steps above (do NOT
duplicate their commands — cross-reference):

1. **Resend secret exists** — ensure the `nestor-resend-api-key` secret + its resource-scoped
   `secretAccessor` grant + a key VALUE version exist (**Step 10.1**). Skip creation if already
   done in a prior Phase-10 session; just confirm a version is present.
2. **Mail envs set** — `NESTOR_ADMIN_EMAIL` + `APP_BASE_URL` on the live service (**Step 10.2**).
   > NOTE: `APP_BASE_URL` set here is **provisional** — it is FINALIZED in **Step 12.4** once the
   > real frontend run.app URL is known. If this is a fresh cutover, you may set a placeholder now
   > and overwrite it in Step 12.4; do not treat the Step-12.1 value as final.
3. **RESEND_API_KEY mapped** to the service env (**Step 10.3**).
4. **REBUILD the backend image via Cloud Build** with `jinja2` / `httpx` and repoint the
   service (**Step 10.4** — image rebuild is MANDATORY, Pitfall 3; never a config-only deploy).
5. **Run the alembic `0010` migration Job** against the live DB (the `nestor-migrate` Cloud Run
   Job runs `alembic upgrade head`; execute it after the image rebuild so the container image
   carries the 0010 revision):
   ```bash
   gcloud run jobs execute nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
   ```
   Confirm the DB reaches `0010` (the Job logs the applied head).
6. **Run the full backend suite in Cloud Build** (the 150+-test pytest suite — the mechanism
   documented for this project; run it against the freshly-built image before proceeding to the
   frontend). This closes 11-UAT #6 (full backend suite green at catch-up).

Failure triage: a mail endpoint **500** with `ModuleNotFoundError: jinja2` → the Step-10.4
image rebuild was skipped (Pitfall 3). Alembic below `0010` → the Job in sub-step 5 did not run.

### Step 12.2 — Drop the NDA template asset (D-12 item 5 residual) BEFORE building the frontend

The intake form's template-download field resolves a `templates/`-prefixed static path via
`frontend/public/templates/` (the `DownloadControl` opens the static URL directly, bypassing
the space-scoped signed-URL seam). The scheme is already implemented, but the actual PDF
binary is NOT committed to the repo — it lived in the legacy Supabase bucket and must be
provided **out-of-band** by the operator. Place the file at exactly:

```
frontend/public/templates/NDA/Agenic-Nestor-Overeenkomst.pdf
```

This is a **static asset drop, no code change**. It must be present in the build context
**before** the Step-12.3 image build so it is baked into `.output/public/`. (Analog: the
Phase-10 `frontend/public/agenic-logo.png` static asset.) If the file is absent the build
still succeeds, but the NDA download link 404s in UAT.

### Step 12.3 — Build + deploy the FRONTEND (pass 1): capture the run.app URL

Build the frontend image via **Cloud Build** (the dev box has no Docker) using a
`cloudbuild.yaml` that passes the `VITE_*` public config as Docker `--build-arg`s — a plain
`gcloud builds submit --tag` CANNOT inject build-args, so the bundle would build with empty
config (Firebase init fails, API base URL wrong). The `VITE_*` values are inlined into the
bundle at build time (they are NOT runtime envs). **DELIBERATELY do NOT pass any
`VITE_SUPABASE_*`** — withholding them keeps `supabase.ts` `null` (D-09/D-11); the in-image
bundle guard (`frontend/scripts/ci_no_supabase_in_bundle.sh .output`) fails the build if a
Supabase signature leaks in.

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:$(date +%Y%m%d-%H%M%S)"

# Build via Cloud Build with the frontend cloudbuild.yaml (a docker build step that passes
# --build-arg VITE_* from --substitutions). The frontend image shares the `nestor` repo.
# _API_BASE_URL = the LIVE nestor-api origin the browser calls directly; the VITE_FIREBASE_*
# values are PUBLIC (the web apiKey is a public project identifier, not a secret).
gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<hash>-ew.a.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

# Deploy the built image to the frontend service (public web app — allUsers invoker, A6).
# --port 8080: the Nitro node-server binds $PORT (Cloud Run injects PORT=8080).
gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --project="$GOOGLE_PROJECT"
```

**Capture the printed `Service URL`** from the deploy output as `FRONTEND_URL` — you need it
for pass 2. This is a Cloud Build image REBUILD, never a config-only deploy (the frontend has
no prior live revision to config-flip anyway).

```bash
# Read it back deterministically (do not guess the run.app hash):
export FRONTEND_URL=$(gcloud run services describe nestor-frontend \
  --region "$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')
echo "FRONTEND_URL=$FRONTEND_URL"
```

### Step 12.4 — Wire the FRONTEND_URL (pass 2): CORS + APP_BASE_URL + bucket CORS + Firebase

Now that the real run.app URL is known, wire it into the four surfaces. **NEVER wire a guessed
run.app URL** — the project+region+hash is only assigned at the first deploy (**Pitfall 4**).
Use exactly the captured `FRONTEND_URL` origin (no `*` wildcard, T-12-10):

```bash
# (a) backend CORS allowlist + APP_BASE_URL (mail CTA links) — set both to the captured URL.
#     This FINALIZES the provisional APP_BASE_URL from Step 12.1.
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars="CORS_ALLOWED_ORIGINS=${FRONTEND_URL},APP_BASE_URL=${FRONTEND_URL}"

# (b) ADD the frontend origin to the uploads-bucket CORS (Step 9.1b pattern; was localhost:8081
#     only). Regenerate the cors-file with the run.app origin, then apply. GET-only — uploads /
#     deletes go THROUGH the backend, never browser->bucket (T-12-10).
cat > /tmp/uploads-cors.json <<JSON
[
  {
    "origin": ["${FRONTEND_URL}"],
    "method": ["GET"],
    "responseHeader": ["Content-Disposition", "Content-Type"],
    "maxAgeSeconds": 3600
  }
]
JSON
gcloud storage buckets update "gs://${BUCKET}" \
  --cors-file=/tmp/uploads-cors.json \
  --project="$GOOGLE_PROJECT"
```

**(c) Firebase authorized domains (Console — manual, A5).** There is no clean gcloud/Terraform
surface for Identity Platform authorized domains, so this is a documented manual step:

- Firebase Console → **Authentication → Settings → Authorized domains → Add domain**
- Add the run.app **host only** (the `FRONTEND_URL` without the `https://` scheme, e.g.
  `nestor-frontend-<hash>-ew.a.run.app`). Add ONLY that host — no wildcard domain (T-12-11).
- Without this, Firebase auth redirects/popups are rejected with `auth/unauthorized-domain`.

### Step 12.5 — Verify + consolidated parity gate (QA-05 / D-05)

```bash
# The deployed frontend serves SSR HTML at its root (Nitro node-server serves .output/server
# + .output/public from one process). Confirm a 200 with HTML, not a 404/500.
curl -sS -o /dev/null -w '%{http_code}\n' "$FRONTEND_URL"   # expect: 200
curl -sS "$FRONTEND_URL" | head -c 400                        # expect: <!DOCTYPE html> … SSR markup
```

Then run the **consolidated 12-UAT** — the single parity checklist that folds in EVERY
outstanding HUMAN-UAT item from Phases 7–11 PLUS the two-role `draft → decomposed` E2E (D-05).
See `.planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md`. The whole gate
is green only when every inherited item AND the two-role E2E pass.

> **Scope ceiling (INTAKE-05).** The validated flow stops at `decomposed`. `run-research` /
> Tribunal is **never** invoked from the new frontend/backend credentials — the scope-guard
> tests + `scripts/ci_no_run_research.sh` keep the ceiling. Do not exercise any research path
> in the parity gate.

Failure triage: CORS preflight failures in the browser → the Step-12.4(a) `CORS_ALLOWED_ORIGINS`
or the (b) bucket CORS did not include the exact `FRONTEND_URL`. Firebase
`auth/unauthorized-domain` → the Step-12.4(c) authorized-domains add was skipped. Mail CTA links
pointing at the wrong host → `APP_BASE_URL` still holds the Step-12.1 placeholder (re-run 12.4a).

---

## Phase 13 — Tribunal re-home (deep-research engine into the intake project)

This section is the **single enumerated source of truth** for the Plan-04 operator live
session that stands up the re-homed Tribunal engine in THIS intake "Nestor Pulse" project
and — as the FINAL post-proof step — tears down the old standalone `project-cb01b861`
build (D-02). It closes the recurring "deployed but not wired" IaC-drift gap by listing
every secret / env / IAM binding / DB role / bucket / migrate-Job / deploy step in order.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform
> state was never adopted and `terraform apply` is blocked on the dev box (no
> Python/Docker/Terraform/gcloud). The `infra/main.tf` + `infra/variables.tf` Tribunal
> blocks are the **intended end-state, INERT** — the steps below are the **manual** gcloud
> reconciliation you run in Cloud Shell. Images are built via **Cloud Build** (never
> locally). Reconcile via `terraform import` (or keep manual) later.

> **Secret hygiene (T-13-08) — read first.** Never echo, log, paste, or commit a secret
> VALUE. Add values ONLY as Secret Manager versions via the `--data-file=-` stdin idiom
> (paste, then Ctrl-D). This includes the two `DATABASE_URL*` DSNs (they embed the
> generated BUILT_IN-user passwords) and the reseeded provider keys.

```bash
# Shared exports for this session (set these once in Cloud Shell).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"                                  # the intake Cloud SQL instance
export INSTANCE_CONN="${GOOGLE_PROJECT}:${REGION}:${INSTANCE_NAME}"
export RUNTIME_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export DB_NAME="nestor"
```

### Step 13.a — Artifact Registry (reuse the existing `nestor` repo)

The two Tribunal images land in the SAME `nestor` Artifact Registry repo as the backend +
frontend (no new repo). Paths: `.../nestor/tribunal-api:<tag>` and
`.../nestor/tribunal-worker:<tag>`. Nothing to create — the repo already exists from Phase 2.

### Step 13.b — Create the six secrets (resource + resource-scoped accessor), then seed VALUES out-of-band

Create each secret container EMPTY, scope a `secretAccessor` grant to the runtime SA
(least privilege — NEVER project-wide, T-13-12), then add each VALUE from stdin (never
echoed, T-13-08). The three provider secrets are named the EXACT `Nestor_*` names the
copied `secrets_bootstrap.py` reads (D-06 / Open Q3 — no bootstrap refactor).

```bash
for S in Nestor_Claude Nestor_Gemini Nestor_OpenAI DATABASE_URL DATABASE_URL_WORKER AUDIT_GCS_BUCKET; do
  gcloud secrets create "$S" --replication-policy=automatic --project="$GOOGLE_PROJECT" 2>/dev/null || \
    echo "secret $S already exists — skipping create"
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$GOOGLE_PROJECT"
done
```

Seed the provider keys. **Reseed `Nestor_Gemini` from the OLD project's key** (D-06 — the
third provider arm is enabled day one). Reseed `Nestor_Claude` / `Nestor_OpenAI` from the
same source (they are DISTINCT secret ids from the intake `nestor-anthropic-api-key` /
`nestor-openai-api-key`; the engine reads the `Nestor_*` names verbatim):

```bash
# Paste the key, then Ctrl-D. Nothing is echoed to history (T-13-08).
gcloud secrets versions add Nestor_Claude  --data-file=- --project="$GOOGLE_PROJECT"
gcloud secrets versions add Nestor_Gemini  --data-file=- --project="$GOOGLE_PROJECT"   # reseed from project-cb01b861's GEMINI/GOOGLE_API_KEY (D-06)
gcloud secrets versions add Nestor_OpenAI  --data-file=- --project="$GOOGLE_PROJECT"
```

Compose + seed the two asyncpg unix-socket DSNs (after Step 13.d creates the roles, so you
know the generated passwords). The DSN form is:

```
postgresql+asyncpg://<user>:<password>@/nestor?host=/cloudsql/<GOOGLE_PROJECT>:europe-west1:nestor-pg
```

```bash
# DATABASE_URL       = app_user   (tribunal-api, tenant-scoped)
# DATABASE_URL_WORKER= worker_user (tribunal-worker, cross-tenant claim role)
# Build each string LOCALLY (never echoed), then pipe via stdin (Ctrl-D). URL-encode any
# reserved chars in the generated passwords.
gcloud secrets versions add DATABASE_URL        --data-file=- --project="$GOOGLE_PROJECT"
gcloud secrets versions add DATABASE_URL_WORKER --data-file=- --project="$GOOGLE_PROJECT"
```

Seed `AUDIT_GCS_BUCKET` with the bucket NAME (created in Step 13.c — this value is the
non-secret bucket name; it is a secret only for injection uniformity):

```bash
export AUDIT_BUCKET="${GOOGLE_PROJECT}-nestor-audit"
printf '%s' "$AUDIT_BUCKET" | gcloud secrets versions add AUDIT_GCS_BUCKET --data-file=- --project="$GOOGLE_PROJECT"
```

### Step 13.c — Create the audit-evidence bucket (7-year Unlocked object retention — D-09)

Create the bucket with **Object Retention ENABLED** (`--enable-per-object-retention`) so the
engine's per-object `blob.retention.mode="Unlocked"` + `retain_until_time = now + 7y`
(`nestor_pulse_sdk/audit/gcs_blob.py`) is honored. **Do NOT** set a bucket-level retention
policy / Bucket Lock — that is irreversible and FORBIDDEN (D-09). Harden it like the uploads
bucket (uniform BLA + public-access-prevention). The bucket must exist BEFORE the proof run or
the run's own chain dangles (T-13-10).

```bash
gcloud storage buckets create "gs://${AUDIT_BUCKET}" \
  --location="$REGION" \
  --uniform-bucket-level-access \
  --public-access-prevention \
  --enable-per-object-retention \
  --project="$GOOGLE_PROJECT"

# Bucket-scoped objectAdmin to the runtime SA (least privilege — read/write + patch retention).
gcloud storage buckets add-iam-policy-binding "gs://${AUDIT_BUCKET}" \
  --member="serviceAccount:${RUNTIME_SA}" \
  --role="roles/storage.objectAdmin" \
  --project="$GOOGLE_PROJECT"
```

### Step 13.d — Create the two BUILT_IN Cloud SQL roles (app_user + worker_user)

The Tribunal services authenticate with a stored password over asyncpg (NOT the intake IAM
connector — RESEARCH Pitfall 5), so both roles are BUILT_IN (password) users. Generate a
strong password for each (never echoed / committed), create the users, then feed the
passwords into the DATABASE_URL* DSNs in Step 13.b.

```bash
# Generate locally; capture into vars (do NOT echo).
APP_PW="$(openssl rand -base64 24)"
WORKER_PW="$(openssl rand -base64 24)"

gcloud sql users create app_user    --instance="$INSTANCE_NAME" --password="$APP_PW"    --project="$GOOGLE_PROJECT"
gcloud sql users create worker_user --instance="$INSTANCE_NAME" --password="$WORKER_PW" --project="$GOOGLE_PROJECT"
```

> **Schema + grants (isolation firewall, T-13-09).** The `CREATE SCHEMA tribunal` and the
> `worker_user` GRANTs are NOT run by hand here — they happen inside the `tribunal-migrate`
> Job: `nestor_pulse_sdk/alembic/env.py` (Plan 02) sets `version_table_schema=tribunal` +
> `search_path=tribunal` so migration `0008` grants `worker_user` USAGE/DML on the `tribunal`
> schema **ONLY** — never the intake `nestor` schema. Do not grant `worker_user` anything on
> `nestor`.

### Step 13.e — Build both Tribunal images via Cloud Build (no local Docker)

Build from the `tribunal/` context so `requirements.txt`, `nestor_pulse_sdk/`, AND
`nestor_pulse/` are all in context. **`nestor_pulse/` IS in both images** — the API's
deep-research division imports `nestor_pulse.tools.claude_deep_researcher` at module load
(13-01 SUMMARY deviation #1); omitting it ImportErrors at boot. The Dockerfiles copy it.

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"

gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
```

Optionally run the test gate first (proves the audit chain + advisory-lock exactly-once on
real Postgres; a non-zero pytest exit fails the build):

```bash
gcloud builds submit tribunal --config=tribunal/cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
```

### Step 13.f — Run the `tribunal-migrate` Job (alembic upgrade head into the `tribunal` schema)

Deploy the Job from the api image, then execute it with `--wait`. It runs the Tribunal alembic
line into the `tribunal` schema (creating the schema + the `worker_user` grants via env.py /
migration 0008). Uses the `DATABASE_URL` (app_user) secret — asyncpg, NOT the IAM connector.

```bash
# PROVEN-LIVE FORM (2026-07-20, execution tribunal-migrate-sc64g). Two gotchas the
# original draft got wrong (13-REVIEW CR-03):
#   1. Jobs use --set-cloudsql-instances (NOT --add-cloudsql-instances — that's a
#      services flag; gcloud prints help and deploys nothing).
#   2. `alembic upgrade head` from /app FAILS ("No 'script_location' key found") —
#      alembic.ini lives in /app/nestor_pulse_sdk with a cwd-relative script_location,
#      so the command must cd there first.
gcloud run jobs deploy tribunal-migrate \
  --image="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}" \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --service-account="$RUNTIME_SA" \
  --set-cloudsql-instances="$INSTANCE_CONN" \
  --set-secrets="DATABASE_URL=DATABASE_URL:latest" \
  --command="sh" --args="-c,cd /app/nestor_pulse_sdk && alembic upgrade head"

gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

### Step 13.g — Deploy `tribunal-worker` (always-on, max=5) then `tribunal-api`

Use the retargeted deploy scripts (they read `$GOOGLE_PROJECT` / `$REGION` / `$INSTANCE_NAME`
and default the image tag to `latest` — pass `IMAGE_TAG=$SHA` to pin the just-built image):

```bash
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh
```

The worker deploys always-on (`--min-instances=1 --max-instances=5 --no-cpu-throttling
--timeout=3600 --no-allow-unauthenticated`, `NESTOR_TRIBUNAL_UNCAPPED=1`) with
`DATABASE_URL=DATABASE_URL_WORKER:latest`; the api deploys `--min-instances=0
--max-instances=3 --timeout=300` with `DATABASE_URL=DATABASE_URL:latest`.

### Step 13.h — Proof run (Plan 04) — CHECKPOINT

> **Do NOT proceed to teardown until this gate is green.** The E2E proof run, `verify_chain`
> validation, the ~5-concurrent-from-≥2-spaces concurrency test (ENGINE-08 / D-08), and the
> duration/cost recording are **Plan 04**, executed against the freshly-deployed services.
> The old `project-cb01b861` build is the fallback until this gate passes (T-13-11).

### Step 13.i — FINAL post-proof teardown of the old standalone project (D-02) — ONLY AFTER 13.h IS GREEN

> **DESTRUCTIVE. Strictly sequenced AFTER the Plan-04 proof run is green (T-13-11).** Do NOT
> run any command in this step until Step 13.h passes. This removes the old standalone
> Tribunal build in `project-cb01b861` now that the re-homed engine is proven in the intake
> project.

```bash
export OLD_PROJECT="project-cb01b861"   # the old standalone Tribunal project

# 1. Delete the old Cloud Run services.
gcloud run services delete nestor-pulse-api    --region "$REGION" --project="$OLD_PROJECT" --quiet
gcloud run services delete nestor-pulse-worker --region "$REGION" --project="$OLD_PROJECT" --quiet

# 2. Delete the old Cloud SQL instance (irreversible — confirm the proof run persisted
#    everything you need first).
gcloud sql instances delete nestor-prod-pg --project="$OLD_PROJECT" --quiet

# 3. Delete the old Artifact Registry repo.
gcloud artifacts repositories delete nestor-pulse --location "$REGION" --project="$OLD_PROJECT" --quiet
```

> **Supabase note (independence, not deletion).** This teardown targets ONLY the old
> `project-cb01b861` Tribunal build. The legacy Supabase project is NEVER paused or deleted
> — "retirement" here means zero Supabase dependencies in the new stack, not destroying the
> old data (see the STATE.md independence note).

---

## Phase 14 — Auth retirement + integration seam (dedicated SA + invoker gate + seam env)

This section is the enumerated source of truth for the Plan-04 operator live session that
closes the WR-03 runtime-SA separation and the D-04 defence-in-depth IAM layer, then runs
the **D-07 live proof** (which ABSORBS the Phase-13 deferred queue-path proof — strike it
from Phase 16's backlog once this is green). Phase 14 is a SMALL delta on the already-deployed
Phase-13 Tribunal services: it gives Tribunal its OWN least-privilege runtime SA
(`tribunal-run`), binds the `tribunal-api` invoker to ONLY the intake `nestor-run` SA, wires
the two non-secret seam env vars, removes the retired `IDENTITY_PLATFORM_*` references, and
runs the SEAM-02 CI denial gate (`tribunal/cloudbuild.seam-gate.yaml`, Step 14.g).

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state
> was never adopted and `terraform apply` is FORBIDDEN on this project (CR-02: an apply would
> rotate the `app_user` / `worker_user` BUILT_IN DB passwords and take down all three Tribunal
> services). The `infra/main.tf` + `infra/variables.tf` Phase-14 edits (dedicated `tribunal_run`
> SA, repointed grants, unconditional `run.invoker` = nestor-run, seam env vars) are the
> **intended end-state, INERT** — the gcloud steps below are the manual reconciliation you run
> in Cloud Shell. Images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **Secret hygiene (T-14-15) — read first.** The retired-secret cleanup (Step 14.f) is
> CONSERVATIVE: remove only the Tribunal service's `IDENTITY_PLATFORM_*` env references. Do NOT
> delete the Secret Manager entries themselves unless a no-other-reader grep across BOTH deploy
> surfaces confirms the intake side does not share them — leave any unproven deletion as a
> documented later cleanup.

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export TRIBUNAL_SA="tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

### Step 14.a — Create the dedicated `tribunal-run` SA + its least-privilege grants (WR-03/D-04b)

Create the DEDICATED Tribunal runtime SA, then grant it ONLY the least-privilege set. This is
the fix that makes the invoker gate (Step 14.e) meaningful: caller SA (`nestor-run`) != callee
SA (`tribunal-run`).

```bash
gcloud iam service-accounts create tribunal-run \
  --project="$GOOGLE_PROJECT" \
  --display-name="Tribunal engine runtime (least-priv)"

# cloudsql.client ONLY — NOT cloudsql.instanceUser. The Tribunal services authenticate with
# a stored BUILT_IN-user password over asyncpg (Pitfall 5), NOT IAM DB login, so instanceUser
# is unnecessary.
gcloud projects add-iam-policy-binding "$GOOGLE_PROJECT" \
  --member="serviceAccount:${TRIBUNAL_SA}" \
  --role="roles/cloudsql.client"

# Resource-scoped secretAccessor on the SIX Tribunal secrets ONLY.
for S in Nestor_Claude Nestor_Gemini Nestor_OpenAI DATABASE_URL DATABASE_URL_WORKER AUDIT_GCS_BUCKET; do
  gcloud secrets add-iam-policy-binding "$S" \
    --member="serviceAccount:${TRIBUNAL_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$GOOGLE_PROJECT"
done

# Bucket-scoped objectAdmin on the tribunal audit bucket ONLY.
export AUDIT_BUCKET="${GOOGLE_PROJECT}-nestor-audit"
gcloud storage buckets add-iam-policy-binding "gs://${AUDIT_BUCKET}" \
  --member="serviceAccount:${TRIBUNAL_SA}" \
  --role="roles/storage.objectAdmin" \
  --project="$GOOGLE_PROJECT"
```

> **Grants DELIBERATELY NOT given to `tribunal-run` (least privilege, WR-03 / T-14-14):**
> `roles/identitytoolkit.admin`, the intake `app_superadmin` DB-password secret
> (`nestor-app-superadmin-db-password`), and the intake uploads bucket
> (`${GOOGLE_PROJECT}-nestor-uploads`). Those stay bound to the intake `nestor-run` SA alone —
> a compromised Tribunal worker must NOT reach the intake admin surfaces.
>
> **Cleanup of the OLD Phase-13 grants (optional, after the redeploy is green).** Phase 13 bound
> these same six secret + audit-bucket grants to `nestor-run`. Once Step 14.c has redeployed both
> services as `tribunal-run` and the proof is green, you MAY remove the now-redundant `nestor-run`
> grants on the six Tribunal secrets + the audit bucket (`gcloud secrets remove-iam-policy-binding
> ... --member=serviceAccount:${INTAKE_SA}`). This is NOT required for correctness — leave it as a
> documented tidy-up if you prefer to minimise change during the live session.

### Step 14.b — Rebuild both Tribunal images via Cloud Build (retirement + provider swap in the image)

The Plan-01 retirement (`firebase-admin` removed, the standalone identity surface deleted,
`InternalCallerProvider` installed) must be baked into the image. Rebuild both from the
`tribunal/` context and capture the tag:

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"

gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
```

### Step 14.c — Redeploy `tribunal-worker` then `tribunal-api` as `tribunal-run`; capture the API URL

The retargeted deploy scripts now set `SA="tribunal-run@..."`. Pass `IMAGE_TAG=$SHA` to pin the
just-built image. Deploy the worker first (no public HTTP), then the api, then CAPTURE its URL:

```bash
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh

# Capture the tribunal-api URL WITHOUT a path (the OIDC audience — never guess it, Pitfall 4).
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
echo "tribunal-api URL: $TRIBUNAL_URL"
```

### Step 14.d — Set the seam env vars live on BOTH services (Pitfall 4 — URL without a path)

The captured `$TRIBUNAL_URL` is BOTH tribunal-api's own `aud` and the audience the intake
tribunal_client mints a token for. Set it on both, plus the intake SA email on tribunal-api:

```bash
# tribunal-api: its own aud + the intake SA email its InternalCallerProvider matches.
gcloud run services update tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars="TRIBUNAL_SERVICE_URL=${TRIBUNAL_URL},INTAKE_RUNTIME_SA_EMAIL=${INTAKE_SA}"

# nestor-api (intake): the tribunal-api URL its tribunal_client mints an ID token for.
gcloud run services update nestor-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars="TRIBUNAL_SERVICE_URL=${TRIBUNAL_URL}"
```

> Re-running `deploy-api.sh` with `TRIBUNAL_SERVICE_URL=$TRIBUNAL_URL` exported also sets these
> idempotently (the script defaults `INTAKE_RUNTIME_SA_EMAIL` to `nestor-run@$PROJECT...`), but
> the URL is not known until the first deploy — so the two `--update-env-vars` above are the
> canonical live-set step.

### Step 14.e — Bind the `tribunal-api` invoker to ONLY the intake SA (D-04 outer gate)

Grant `run.invoker` on tribunal-api to the intake `nestor-run` SA ONLY; keep the service
`--no-allow-unauthenticated`. Then REMOVE any lingering `allUsers` invoker binding (a Phase-13
`allow_unauthenticated=true` apply could have left one):

```bash
gcloud run services add-invoker-policy-binding tribunal-api \
  --member="serviceAccount:${INTAKE_SA}" \
  --region="$REGION" --project="$GOOGLE_PROJECT"

# Belt-and-suspenders: strip any allUsers invoker if present (no-op if absent).
gcloud run services remove-invoker-policy-binding tribunal-api \
  --member="allUsers" \
  --region="$REGION" --project="$GOOGLE_PROJECT" 2>/dev/null || \
  echo "no allUsers invoker binding on tribunal-api — good"

# Confirm the service stays internal-only.
gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.metadata.annotations["run.googleapis.com/ingress"])' || true
```

### Step 14.f — Retired-secret cleanup (A6, CONSERVATIVE — T-14-15)

The `IDENTITY_PLATFORM_*` env references are already ABSENT from the retargeted deploy scripts
(Plan 01 removed the standalone identity surface + `firebase-admin`). VERIFY they are also absent
from the live tribunal-api / tribunal-worker service config, and do NOT delete the Secret Manager
entries without a no-other-reader check:

```bash
# Confirm no IDENTITY_PLATFORM_* env on the live services (should print nothing).
gcloud run services describe tribunal-api    --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='yaml(spec.template.spec.containers[].env)' | grep -i IDENTITY_PLATFORM || echo "tribunal-api: clean"
gcloud run services describe tribunal-worker --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='yaml(spec.template.spec.containers[].env)' | grep -i IDENTITY_PLATFORM || echo "tribunal-worker: clean"
```

> **Do NOT `gcloud secrets delete` any `IDENTITY_PLATFORM_*` secret** unless you have grepped BOTH
> deploy surfaces (intake `nestor-api` AND the Tribunal services) and confirmed no reader remains.
> If unproven, leave the entry and record it as a documented later cleanup (T-14-15 disposition=accept).

### Step 14.g — Run the SEAM-02 denial gate (D-08)

**The gate is `tribunal/cloudbuild.seam-gate.yaml` — and ONLY that build.** It exists precisely
so the denial tests EXECUTE (it stands up a real `postgres:15`, creates the NON-superuser
`app_user`/`worker_user` roles, migrates as `app_user`, and runs the seam denial + RLS denial
suites as a non-superuser). Its anti-false-green check fails the build on ANY skip — a
silently-skipped denial test can never fake a green gate. THIS build green == the SEAM-02
denial gate green (proven green as build `25b8f9eb`).

```bash
# From the repo root. The SEAM-02 denial gate: all seam-gate tests
# (nestor_pulse_sdk/tests/test_seam_denial.py + test_seam_rls_denial.py) must
# EXECUTE and pass as non-superuser — skips FAIL the gate.
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.seam-gate.yaml \
  --project="$GOOGLE_PROJECT"
```

Optional context run — the full intake suite (NOT part of the gate):

```bash
# From the repo root — the source MUST be `.` (repo root), never `backend`:
# cloudbuild.test.yaml step 3 does a repo-root-relative `cd backend`, and
# .gcloudignore's header requires the repo root as the upload context.
gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
```

> **Do NOT count the intake build as the seam gate.** `.gcloudignore` excludes `tribunal/` from
> repo-root uploads, so `nestor_pulse_sdk.*` is not importable in that image and the intake-side
> copy (`backend/tests/test_tribunal_seam_denial.py`) SKIPS all its seam denial cases by design
> (D-DEF-1). The FULL `tribunal/cloudbuild.test.yaml` suite is also NOT the gate: it carries
> pre-existing non-Phase-14 failures (D-DEF-3, deferred to Phase 20 / CLOSE-02).
>
> Record the seam-gate build id for the SUMMARY. After it is green, proceed to the Task-3 D-07
> live proof (positive server-to-server run + the three negative proofs).

---

## Summary checklist

- [ ] Step 1 — two secrets created + resource-scoped secretAccessor to the runtime SA (manual, per drift)
- [ ] Step 2 — key VALUES added as secret versions, never echoed/logged/committed
- [ ] Step 3 — image rebuilt via Cloud Build with `anthropic` + `openai`, service repointed
- [ ] Step 4 — `min-instances=0` + CPU always-allocated + native key injection
- [ ] Step 5 — wiring verified without printing any secret value
- [ ] Step 8.1 — backend image rebuilt via Cloud Build with the new `skill-runs/stream` + full-run endpoints, service repointed (D-10 UAT)
- [ ] Step 8.2 — `gcloud run services update nestor-api … --timeout=900` applied live (D-07; the `main.tf` edit alone is inert per drift)
- [ ] Step 8.3 — live verify: console Request timeout reads 900s AND streamed events arrive at ~2s cadence (no ~300s drop)
- [ ] Step 9.1 — private `${GOOGLE_PROJECT}-nestor-uploads` bucket created (uniform BLA + public-access-prevention enforced; no versioning/lifecycle) (D-07a/D-12)
- [ ] Step 9.1b — bucket CORS policy applied (GET-only, origins = Cloud Run `CORS_ALLOWED_ORIGINS`) so the frontend `fetch()` of signed URLs is not browser-blocked (WR-02)
- [ ] Step 9.2 — bucket-scoped `roles/storage.objectAdmin` granted to the runtime SA (least privilege, T-09-15)
- [ ] Step 9.3 — `roles/iam.serviceAccountTokenCreator` self-binding on the runtime SA for keyless signBlob (criterion 1, T-09-13; separate grant per Pitfall 2)
- [ ] Step 9.4 — image rebuilt via Cloud Build with `google-cloud-storage` + `python-multipart` AND the Phase-8 stream route, service repointed + `STORAGE_BUCKET` env set (Pitfall 7; live is still v12)
- [ ] Step 9.5 — combined 7+8+9 UAT: attachment + audio upload → transcribe → SSE-streamed apply-intake-skill → signed-URL download (attachment disposition, ≤15-min TTL); no SA JSON key anywhere (D-13)
- [ ] Step 10.1 — `nestor-resend-api-key` secret created + resource-scoped secretAccessor to the runtime SA + key VALUE added out-of-band (never committed/echoed, T-10-04)
- [ ] Step 10.2 — `NESTOR_ADMIN_EMAIL` + `APP_BASE_URL` plain non-secret envs set live via `--update-env-vars` (D-08/D-15; the `main.tf` edits alone are inert per drift)
- [ ] Step 10.3 — `RESEND_API_KEY=nestor-resend-api-key:latest` mapped to the service env (native secret injection; reference only, never the value)
- [ ] Step 10.4 — backend image rebuilt via Cloud Build with `jinja2`, service repointed (Pitfall 2 — green CI but a 500 `ModuleNotFoundError: jinja2` in UAT if skipped)
- [ ] Step 10.5 — live mail UAT: trigger invite, validation, results, reminder, admin_validated against the deployed rev and inspect the inbox (visual parity + tokenless CTA)
- [ ] Drift logged: reconcile via `terraform import` (or keep manual) BEFORE Phase 12 cutover (now extended with the Phase-9 storage + Phase-10 Resend resources)
- [ ] Step 12.1 — backend catch-up FIRST: Resend secret (10.1) + mail envs (10.2, APP_BASE_URL provisional) + RESEND_API_KEY mapped (10.3) + `jinja2`/`httpx` image REBUILD (10.4, mandatory — Pitfall 3) + alembic `0010` Job run + full backend suite green in Cloud Build (closes 11-UAT #6)
- [ ] Step 12.2 — NDA PDF asset dropped at `frontend/public/templates/NDA/Agenic-Nestor-Overeenkomst.pdf` (out-of-band, no code change) BEFORE the frontend build (D-12 item 5)
- [ ] Step 12.3 — frontend image built via Cloud Build (`frontend/cloudbuild.yaml`, `--build-arg VITE_*` from substitutions; NO `VITE_SUPABASE_*`; in-image bundle guard passes) + deployed (`gcloud run deploy nestor-frontend --allow-unauthenticated --port 8080`) + `FRONTEND_URL` captured from the deploy output (never guessed — Pitfall 4)
- [ ] Step 12.4 — two-pass URL wiring off the CAPTURED `FRONTEND_URL`: (a) backend `CORS_ALLOWED_ORIGINS`+`APP_BASE_URL` = URL, (b) uploads-bucket CORS += URL (GET-only, Step 9.1b pattern), (c) Firebase Console authorized domains += run.app host (manual, A5) — never a `*` wildcard, never a guessed URL (T-12-10/T-12-11)
- [ ] Step 12.5 — verify `curl $FRONTEND_URL` → 200 SSR HTML, then run the consolidated 12-UAT (all inherited 07–11 items + two-role `draft → decomposed` E2E, D-05) fully green; scope ceiling `decomposed` respected (run-research never invoked)
- [ ] D-08 guard confirmed: NO Supabase-side actions taken anywhere in the phase (independence proven code-side — no `VITE_SUPABASE_*` in the build + bundle guard green, D-09/D-11)
- [ ] Step 13.a — Tribunal images target the EXISTING `nestor` Artifact Registry repo (no new repo)
- [ ] Step 13.b — six secrets created + resource-scoped secretAccessor to the runtime SA + VALUES seeded out-of-band via stdin (`Nestor_Claude/Gemini/OpenAI` reseeded — Gemini from the old project, D-06; `DATABASE_URL{,_WORKER}` composed asyncpg DSNs; `AUDIT_GCS_BUCKET` = bucket name); no value echoed/committed (T-13-08/T-13-12)
- [ ] Step 13.c — audit-evidence bucket `${GOOGLE_PROJECT}-nestor-audit` created with `--enable-per-object-retention` (7y Unlocked per-object — D-09; NOT Bucket Lock) + uniform BLA + public-access-prevention + bucket-scoped objectAdmin to the runtime SA (T-13-10)
- [ ] Step 13.d — BUILT_IN `app_user` + `worker_user` Cloud SQL roles created (password/asyncpg, NOT IAM — Pitfall 5); `worker_user` schema GRANTs deferred to migration 0008 → `tribunal` schema ONLY, never `nestor` (T-13-09)
- [ ] Step 13.e — both Tribunal images built via Cloud Build (`cloudbuild.api.yaml` / `.worker.yaml`; `nestor_pulse/` IS in both — boot dep, 13-01 deviation #1); optional test gate (`cloudbuild.test.yaml`) green
- [ ] Step 13.f — `tribunal-migrate` Job deployed + executed `--wait` (alembic upgrade head into the `tribunal` schema; app_user DSN)
- [ ] Step 13.g — `tribunal-worker` deployed (min=1/max=5/no-cpu-throttling/timeout=3600, `DATABASE_URL_WORKER`, `NESTOR_TRIBUNAL_UNCAPPED=1`) then `tribunal-api` (min=0/max=3/timeout=300, `DATABASE_URL`) via the retargeted deploy scripts
- [ ] Step 13.h — CHECKPOINT: Plan-04 proof run (E2E + `verify_chain` + ~5-concurrent-from-≥2-spaces concurrency + duration/cost) GREEN before any teardown (T-13-11)
- [ ] Step 13.i — FINAL post-proof teardown of `project-cb01b861` (Cloud Run `nestor-pulse-api`/`nestor-pulse-worker` + Cloud SQL `nestor-prod-pg` + Artifact Registry `nestor-pulse`) — STRICTLY after 13.h is green (D-02); legacy Supabase project NEVER touched (independence, not deletion)
- [ ] Step 14.a — dedicated `tribunal-run` SA created + least-priv grants ONLY (cloudsql.client + the six Tribunal secrets' secretAccessor + audit-bucket objectAdmin); DELIBERATELY NOT granted identitytoolkit.admin / the intake superadmin secret / the intake uploads bucket (WR-03 / T-14-14)
- [ ] Step 14.b — both Tribunal images rebuilt via Cloud Build with the Plan-01 retirement baked in (`firebase-admin` removed, `InternalCallerProvider` installed); `$SHA` captured
- [ ] Step 14.c — `tribunal-worker` then `tribunal-api` redeployed as `tribunal-run` (retargeted scripts); tribunal-api URL captured from `gcloud run services describe` WITHOUT a path (Pitfall 4)
- [ ] Step 14.d — seam env set live: `TRIBUNAL_SERVICE_URL`+`INTAKE_RUNTIME_SA_EMAIL` on tribunal-api, `TRIBUNAL_SERVICE_URL` on nestor-api (same captured URL — the OIDC audience; the `main.tf` edits alone are inert per drift)
- [ ] Step 14.e — `run.invoker` on tribunal-api bound to ONLY `nestor-run` (D-04 outer gate); any `allUsers` invoker stripped; service stays `--no-allow-unauthenticated` (T-14-12)
- [ ] Step 14.f — retired-secret cleanup CONSERVATIVE: verified no `IDENTITY_PLATFORM_*` env on the live Tribunal services; NO Secret Manager entry deleted without a no-other-reader check (T-14-15)
- [ ] Step 14.g — SEAM-02 denial gate GREEN via `gcloud builds submit tribunal --config=tribunal/cloudbuild.seam-gate.yaml` (all seam denial + RLS denial tests EXECUTE and pass as non-superuser; skips fail the gate) (D-08); build id recorded. The intake `cloudbuild.test.yaml` run is optional context only — its seam denial copy SKIPS by design (D-DEF-1) and must NOT be counted as the gate
- [ ] Step 14 (Task 3) — CHECKPOINT: D-07 live proof — one real server-to-server run completed-green with D-05 acting-user attribution + `verify_chain` green, and the three negative proofs (unauthenticated 401/403, wrong-SA, cross-tenant) all reject; ABSORBS the Phase-13 deferred queue-path proof (strike it from Phase 16's backlog)
