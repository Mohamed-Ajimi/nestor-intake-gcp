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

## Phase 16 — Research trigger + progress bridge (nestor-api REBUILD + 0011 + first live run)

This section is the enumerated source of truth for the Plan-05 operator live session that ships
the research trigger/progress spine to production. Phase 16 added NEW intake-backend modules
(`app/api/research_routes.py`, `app/research/run_task.py`, `app/research/brief.py`,
`app/research/tribunal_client.py` run-lifecycle methods, the `research_runs` ORM model, and six
`research_complete`/`research_failed` mail templates) plus migration **0011** (`nestor.research_runs`
+ FORCE RLS + both policies). None of that is in the running `nestor-api` container until the image
is **rebuilt** — a config-only env flip on the stale image would 500 with `ModuleNotFoundError`
or 404 the new route while CI is green. The live session then triggers ONE real research run on a
decomposed smoke intake, which is ALSO the first real intake-originated seam call and closes the
deferred Phase-14 HTTP UAT.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is FORBIDDEN on this project (it would rotate the BUILT_IN DB
> passwords and take down all services). Every step below is a manual gcloud reconciliation run in
> Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **The recurring deploy-gap (READ FIRST — Steps 8/9/10/12 all hit it).** "Nothing is real until it
> is deployed, and a config-only env flip ships a STALE image." Phase 16 adds new Python modules +
> a migration — a `gcloud run services update --update-env-vars` on the current revision does NOT
> ship them. Step 16.a is a mandatory Cloud Build **image REBUILD**, not an env flip.

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13/14).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

### Step 16.a — REBUILD the `nestor-api` image via Cloud Build (new research modules + 0011 must ship)

The running container predates the Phase-16 research modules and migration 0011. A config-only
env flip on the stale image is the **recurring deploy-gap** (Pitfall 2/3; Steps 10.4 / 12.1) — it
produces a live `ModuleNotFoundError: app.research.run_task` or a 404 on `POST
/intakes/{id}/research` while CI is green. Reuse the Step-3/8.1/9.4/10.4 Cloud Build idiom (never a
local `docker build` — downloads are blocked on the dev box), then repoint the service:

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (bakes the new app/research/* + app/api/research_routes.py +
# app/db/models/research_runs.py + the six research_* mail templates into the image), then repoint.
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"
```

> **Run the intake backend suite in Cloud Build against the freshly-built image BEFORE the live
> run.** 16-01/16-02/16-03 authored their pytest suites by-construction and deferred the run to
> Cloud Build (the dev box has no Python). Run the full intake suite so the new research tests
> (`test_research_runs_migration.py`, `test_research_brief.py`, `test_research_run_task.py`,
> `test_research_routes.py`, `test_research_cross_tenant.py`) execute green before you spend on a
> real run:
>
> ```bash
> # From the repo root — source MUST be `.` (repo root), never `backend` (Step 14.g note).
> gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
> ```

### Step 16.b — Run the `nestor-migrate` Job to apply migration 0011 (alembic upgrade head)

The `nestor-migrate` Cloud Run Job runs `alembic upgrade head` (same pattern as the 0009/0010
intake migrations — Step 12.1 sub-step 5). Execute it AFTER the Step-16.a image rebuild so the Job
image carries the 0011 revision:

```bash
gcloud run jobs execute nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

Then confirm `nestor.research_runs` + its two RLS policies exist (the migration logs the applied
head; verify the schema landed):

```bash
# Read-only confirm via the migrate Job's connection or a Cloud SQL psql session:
#   \dt  nestor.research_runs                       -> the table exists
#   SELECT policyname FROM pg_policies
#     WHERE tablename='research_runs';              -> research_runs_space_isolation
#                                                      research_runs_superadmin_all  (both present)
#   SELECT relforcerowsecurity FROM pg_class
#     WHERE relname='research_runs';                -> t  (FORCE RLS on)
```

Alembic still below `0011` after this → the Job in this step did not run (or ran on the pre-rebuild
image); re-run Step 16.a then this step.

### Step 16.c — Confirm `TRIBUNAL_SERVICE_URL` on `nestor-api` (READ-ONLY — already set in Phase 14)

`TRIBUNAL_SERVICE_URL` was set on `nestor-api` in Phase 14 Step 14.d and verified pass in
14-HUMAN-UAT item 2 (`https://tribunal-api-ybkr7metoq-ew.a.run.app`). This is a **confirm-only**
read, NOT a re-set — do not re-run the update (it is the OIDC audience; a wrong value breaks the
seam, Pitfall 4):

```bash
gcloud run services describe nestor-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep TRIBUNAL_SERVICE_URL
# expect: TRIBUNAL_SERVICE_URL=https://tribunal-api-ybkr7metoq-ew.a.run.app
```

If it is absent (should not happen post-Phase-14), re-apply Phase 14 Step 14.d before proceeding.

### Step 16.d — Set `NESTOR_WORKER_STALE_MINUTES=90` on `tribunal-worker` (ENGINE-03 partial — no double-runs)

The worker's stale-run reclaim window defaults to **60** min (`deploy-worker.sh:74`,
`NESTOR_WORKER_STALE_MINUTES=60`). The measured max Tribunal run length is **17–19 min** (A2), but
60 min is uncomfortably close to a long-tail run — set it to **90** to guarantee the reclaim window
sits well above the max so a still-running job is never stale-reclaimed and double-dispatched
(T-16-16). This is a **config-only env update on the UNCHANGED worker image** — no worker rebuild:

```bash
gcloud run services update tribunal-worker \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars="NESTOR_WORKER_STALE_MINUTES=90"

# Verify it landed:
gcloud run services describe tribunal-worker \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep NESTOR_WORKER_STALE_MINUTES
# expect: NESTOR_WORKER_STALE_MINUTES=90
```

> **`NESTOR_TRIBUNAL_UNCAPPED` STAYS ON (D-02).** The operator explicitly deferred the cap flip-on
> during the Phase-16 discussion (2026-07-21) — "uncapped for now". Do NOT flip
> `NESTOR_TRIBUNAL_UNCAPPED` off in this phase; the cap decision + flip is Phase 20 at the latest
> (T-16-17 accepted, mitigated meanwhile by superadmin-only trigger + server-composed brief).

### Step 16.e — Top up Anthropic credits BEFORE the live run

Anthropic credits are LOW (MEMORY: phase-14). A real Tribunal run consumes Claude tokens across
its stages — top up the Anthropic account **before** triggering the run so it does not fail
mid-flight on a credit exhaustion. (The `Nestor_Claude` secret already carries a valid key — this
is an account-balance top-up, not a secret change.)

### Step 16.f — Live trigger / progress / mail UAT (points to 16-HUMAN-UAT.md)

With the image rebuilt, 0011 applied, the stale window at 90, and credits topped up, run the
operator live session per `.planning/phases/16-research-trigger-progress-bridge/16-HUMAN-UAT.md`:

1. On a **DECOMPOSED** smoke intake in a smoke space, open the admin intake detail and click
   **Start research** → confirm the AlertDialog (the 202 fires only on confirm, D-03).
2. Observe: status flips `decomposed → in_research`; the progress panel renders the stage list
   **dynamically** (one row per mirrored `research_runs` stage — no hardcoded count) with a ticking
   cost + elapsed clock, in the intake design language.
3. The run reaches `completed` (~17–19 min) and the completion email arrives at your address.
4. Confirm a **client** login shows NO research surface during `in_research` (D-08 / T-16-18).
5. Record the run id, total cost, duration, and `verify_chain` result.
6. Update `.planning/phases/14-auth-retirement-integration-seam/14-HUMAN-UAT.md` item 1 to PASS
   (this is the first real intake-originated seam call), referencing this Phase-16 run.
7. Record all results in `16-HUMAN-UAT.md`.

Failure triage: `POST /intakes/{id}/research` **404** → Step-16.a rebuild was skipped (stale image,
recurring deploy-gap). A 500 `ModuleNotFoundError: app.research.*` → same (rebuild not shipped). The
trigger 202s but the run never leaves `queued` → the worker is not picking it up (check
`tribunal-worker` logs; a double-dispatch symptom means the stale window in Step 16.d was left at
60). Progress panel blank but the run advances → the SSE `/research/stream` route 404s (stale image,
Step 16.a). Run fails mid-flight with a credit error → Step 16.e top-up was skipped.

---

## Phase 17 — Raw output + audit chain guard (tribunal-api + nestor-api REBUILD, ordered, + 0012 + download proof)

This section is the enumerated source of truth for the Plan-04 operator live session that ships the
raw-output download + audit-chain guard to production. Phase 17 adds surface to BOTH deployables and
they MUST ship in order:

1. **`tribunal-api`** gains a NEW read-only endpoint `GET /api/runs/{run_id}/research-bundle` (serves
   the engine's scrubbed `cleaned_reports` only — `rejected_claims` excluded at the boundary, D-01).
   The `tribunal-worker` image is **UNCHANGED** this phase (no worker rebuild).
2. **`nestor-api`** gains the completion-path audit-chain gate + bundle materialization
   (`app/research/bundle.py`, the extended `app/research/run_task.py`/`app/api/research_routes.py`,
   the `research_runs` chain/lock/bundle columns), the superadmin-only download + re-verify routes,
   plus the frontend download/locked/re-verify UI. Migration **0012** adds three nullable columns to
   `nestor.research_runs` (`chain_status`, `chain_broken_at`, `bundle_key`).

The intake finalize path (in `nestor-api`) calls tribunal-api's new `/research-bundle` endpoint — so
**tribunal-api MUST be rebuilt + deployed FIRST**, or the first real completion 500s on a 404 from a
stale tribunal image while CI is green. The live proof rides on a real `completed` run, which is still
blocked on Anthropic credits (the same Phase-16 blocker) — so this is an operator-runbook checkpoint,
same pattern as § Phase 16 Step 16.f.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is FORBIDDEN on this project (it would rotate the BUILT_IN DB
> passwords and take down all services). Every step below is a manual gcloud reconciliation run in
> Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **The recurring deploy-gap (READ FIRST — Steps 17.a AND 17.b both hit it).** "Nothing is real until
> it is deployed, and a config-only env flip ships a STALE image." Phase 17 adds new code to BOTH
> images plus a migration — a `gcloud run services update --update-env-vars` on the current revisions
> ships NONE of it. Steps 17.a and 17.b are mandatory Cloud Build **image REBUILDs**, not env flips.
> This phase introduces **NO new env var and NO new secret** (Step 17.e is confirm-only): the bundle
> reuses the Phase-9 `STORAGE_BUCKET` (the app uploads bucket — D-05) and the Phase-14/16
> `TRIBUNAL_SERVICE_URL` seam; there is **NO `AUDIT_GCS_BUCKET`** on the nestor-api download path
> (D-05 — the raw-output zip lives in the app bucket, never the 7-year audit-evidence bucket).

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13/14/16).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

### Step 17.a — REBUILD + deploy the `tribunal-api` image via Cloud Build FIRST (new `/research-bundle` endpoint must ship before nestor-api calls it)

The running `tribunal-api` container predates the Phase-17 `GET /api/runs/{run_id}/research-bundle`
endpoint (`tribunal/nestor_pulse_sdk/runs/api.py`). The intake finalize path (in the rebuilt
`nestor-api`, Step 17.b) calls this endpoint at completion, so it MUST be live first — otherwise the
first real completion 500s on a 404 from the stale tribunal image while CI is green (the recurring
deploy-gap). This is an **image REBUILD, not an env flip.** Reuse the § Phase 13.e / 14.b Cloud Build
idiom (never a local `docker build` — downloads are blocked on the dev box). The **`tribunal-worker`
image is UNCHANGED this phase — do NOT rebuild or redeploy the worker.**

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

# Rebuild ONLY tribunal-api (bakes the new /research-bundle endpoint into the image).
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"

# Redeploy tribunal-api at the just-built tag (retargeted deploy script pins IMAGE_TAG=$SHA; it stays
# tribunal-run SA + --no-allow-unauthenticated + invoker=nestor-run ONLY — the Phase-14 lockdown is
# preserved by the script, NOT re-granted here). Do NOT run deploy-worker.sh — the worker is unchanged.
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh
```

> **Optional but recommended: run the Tribunal seam/bundle tests in Cloud Build against the fresh
> image** before nestor-api calls it live. 17-01 authored `test_research_bundle_endpoint.py`
> by-construction and deferred the run (the dev box has no Python):
>
> ```bash
> gcloud builds submit tribunal --config=tribunal/cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
> ```

Confirm the tribunal-api URL is UNCHANGED from Phase 14/16 (a redeploy of an existing service keeps
its URL; capture it read-only for the Step-17.e confirm — do NOT re-set the seam env, Pitfall 4):

```bash
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
echo "tribunal-api URL: $TRIBUNAL_URL"   # expect the same https://tribunal-api-...-ew.a.run.app as Phase 14/16
```

### Step 17.b — REBUILD + deploy the `nestor-api` image via Cloud Build (bundle builder + gate + download routes + 0012 must ship)

The running `nestor-api` container predates the Phase-17 completion-path gate + download surface. A
config-only env flip on the stale image is the **recurring deploy-gap** — it produces a live 404 on
`GET /intakes/{id}/research/{run}/bundle-url` (or a 500 `ModuleNotFoundError: app.research.bundle`)
while CI is green, and the completion path never materializes a zip. Reuse the § Phase 16 Step-16.a
Cloud Build idiom (the same `backend` build context), then repoint the service:

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (bakes app/research/bundle.py, the extended run_task.py /
# research_routes.py, the research_runs chain/lock/bundle columns, and migration 0012 into the image),
# then repoint. No new pip dependency this phase (stdlib zipfile/io/json + in-image gcs/httpx).
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"
```

> **Run the intake backend suite in Cloud Build against the freshly-built image BEFORE the live
> proof.** 17-01/17-02/17-03 authored their pytest suites by-construction and deferred the run to
> Cloud Build (the dev box has no Python). Run the full intake suite so the new Phase-17 tests
> (`test_research_runs_migration.py` 0012 cases, `test_research_bundle.py`,
> `test_research_run_task.py` completion-gate cases, `test_research_bundle_download.py`,
> `test_research_cross_tenant.py` denial cases) execute green:
>
> ```bash
> # From the repo root — source MUST be `.` (repo root), never `backend` (§ Phase 14.g note).
> gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
> ```

### Step 17.c — Run the `nestor-migrate` Job to apply migration 0012 (alembic upgrade head)

The `nestor-migrate` Cloud Run Job runs `alembic upgrade head` (same pattern as the 0009/0010/0011
intake migrations — § Phase 16 Step 16.b). Execute it AFTER the Step-17.b image rebuild so the Job
image carries the 0012 revision:

> ⚠️ **LESSON (hit live 2026-07-22): the Job does NOT track the service image.** Updating
> `nestor-api` with `gcloud run services update --image` leaves the `nestor-migrate` Job pinned to
> its OLD image — executing it then is a **silent no-op** (alembic connects, finds itself "at head"
> on the stale revision set, exits 0, logs no `Running upgrade` line). ALWAYS repin the Job first:

```bash
gcloud run jobs update nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"   # the SAME image tag deployed in Step 17.b
gcloud run jobs execute nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
# CONFIRM the log shows "Running upgrade 0011 -> 0012" — no upgrade line = stale-image no-op.
```

Then confirm the three new nullable columns landed on `nestor.research_runs`. Migration 0012 is a pure
add-column — the columns inherit the table's existing 0011 FORCE-RLS row policies, so there is NO new
policy/grant/index to verify (17-01 D):

```bash
# Read-only confirm via the migrate Job's connection or a Cloud SQL psql session:
#   \d nestor.research_runs                          -> the three columns exist, all nullable:
#     chain_status      text        (nullable)
#     chain_broken_at   timestamptz (nullable)
#     bundle_key        text        (nullable)
#   Pre-existing rows (e.g. smoke intake e08620c5's ~3 rows) stay NULL — the completion path is the
#   SOLE writer of these columns; no server_default backfilled them.
```

Alembic still below `0012` after this → the Job in this step did not run (or ran on the pre-rebuild
image); re-run Step 17.b then this step.

### Step 17.d — Deploy the frontend image (download button + locked/re-verify UI)

The frontend gains `getBundleUrl` / `reVerifyChain` transport (`frontend/src/lib/api/research.ts`)
and the `RawOutputControls` block on the completed summary card
(`frontend/src/components/intake/ResearchRunProgress.tsx`) — a **[Download]** button on a
chain-verified run, a red locked card + **[Re-verify]** button on a broken chain. Rebuild + deploy per
the standard § Phase 12 Step-12.3 frontend flow (Cloud Build image REBUILD; `--build-arg VITE_*` from
substitutions; NO `VITE_SUPABASE_*` — the in-image bundle guard fails the build if a Supabase
signature leaks). No new env/secret and no URL re-wiring is needed (the `_API_BASE_URL` and Firebase
substitutions are unchanged from Phase 12; the run.app URLs already exist):

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:$(date +%Y%m%d-%H%M%S)"

# Reuse the SAME _API_BASE_URL / _FB_* substitutions captured at Phase 12 Step 12.3 (unchanged).
gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<hash>-ew.a.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --project="$GOOGLE_PROJECT"
```

### Step 17.e — Confirm NO new env/secret is needed (READ-ONLY — `STORAGE_BUCKET` + `TRIBUNAL_SERVICE_URL` already set; NO `AUDIT_GCS_BUCKET`)

Phase 17 introduces **no new env var and no new secret** (17-RESEARCH Runtime State Inventory). The
download path reuses two envs already live on `nestor-api`:

- `STORAGE_BUCKET` — the Phase-9 app uploads bucket; the raw-output zip is written under the
  space-scoped `artifacts` category here (D-05). This is the APP bucket.
- `TRIBUNAL_SERVICE_URL` — the Phase-14/16 seam audience; the completion path calls tribunal-api's new
  `/research-bundle` endpoint over it.

Confirm both are present (confirm-only — do NOT re-set either; `TRIBUNAL_SERVICE_URL` is the OIDC
audience and a wrong value breaks the seam, Pitfall 4):

```bash
gcloud run services describe nestor-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep -E 'STORAGE_BUCKET|TRIBUNAL_SERVICE_URL'
# expect: STORAGE_BUCKET=<GOOGLE_PROJECT>-nestor-uploads
#         TRIBUNAL_SERVICE_URL=https://tribunal-api-...-ew.a.run.app  (same as Step 17.a $TRIBUNAL_URL)
```

**Explicitly confirm there is NO `AUDIT_GCS_BUCKET` on the download path.** The `AUDIT_GCS_BUCKET`
secret exists for the Tribunal engine's 7-year audit-evidence chain (§ Phase 13.c) — the raw-output
download does NOT use it (D-05: the app bucket, never the audit bucket). No action is needed here; this
is a confirmation that the bundle bucket is `STORAGE_BUCKET`, not the audit bucket.

### Step 17.f — Top up Anthropic credits + complete the parked Phase-16 run FIRST, then run the live download/verify_chain/isolation UAT (points to 17-HUMAN-UAT.md)

Anthropic credits (the `Nestor_Claude2` key) are the LIVE blocker — the deferred Phase-16 live run is
still parked on empty credits (MEMORY: phase-16). This Phase-17 download proof RIDES ON a real
`completed` run, so:

1. **Top up Anthropic credits** and **complete the parked § Phase 16 Step-16.f live run FIRST** — that
   produces the real `completed` + chain-verified run this download proof needs. (Do this before
   spending any further time; the download UAT cannot run without a completed run.)

With both images rebuilt (tribunal-api first), 0012 applied, the frontend deployed, and a real
completed run in hand, run the operator live session per
`.planning/phases/17-raw-output-audit-chain-guard/17-HUMAN-UAT.md`:

2. On the completed smoke run's admin intake detail page, confirm the summary card shows chain state
   **VERIFIED** and a **Download** button. Click **Download** → confirm the zip downloads → open it and
   verify it contains `report.md`, at least one `research/*.md`, and `sources.json`, and that there is
   **NO rejected-claims file or content** anywhere in the zip (D-01 / D-03 layout).
3. Confirm the chain-verified state was produced by the **completion-path `verify_chain` gate** (the
   run's `chain_status` is `verified`). Optionally, in a **scratch tenant**, tamper the audit chain and
   confirm the summary card shows the **locked** state with a working **Re-verify** button (D-06 →
   complete-but-locked).
4. **ISOLATION (REPORT-02 absolute rule):** log in as a **CLIENT** (user-role) and confirm NO
   raw-output download and NO research surface is visible or reachable anywhere.
5. Record the run id, the zip contents, and the `verify_chain` result in `17-HUMAN-UAT.md`.

Failure triage: `GET /intakes/{id}/research/{run}/bundle-url` **404** for a superadmin → Step-17.b
rebuild was skipped (stale image, recurring deploy-gap). The completion path never materializes a zip
(the summary card shows verified but Download 500s / rebuilds every click) → tribunal-api's
`/research-bundle` is 404ing (Step-17.a rebuild skipped — the finalize seam call failed, `bundle_key`
stayed NULL). A superadmin sees a **403** (not 404) on the download → the role gate ordering regressed
(the denial suite pins existence-hidden 404). A **client** can reach any raw-output surface → STOP,
this is a REPORT-02 breach — do not accept the phase.

---

## Phase 18 — Human report upload + client delivery (nestor-api REBUILD + frontend deploy, NO migrate, NO new secret)

This section is the enumerated source of truth for the Plan-04 operator live session that ships the
human-report delivery surface to production. Phase 18 adds surface to BOTH deployables — but SIMPLER
than Phase 17: there is only ONE backend deployable (`nestor-api`) and the frontend; the Tribunal
images (`tribunal-api`/`tribunal-worker`) are **UNCHANGED** this phase (no Tribunal rebuild), and
**there is NO migration** and **NO new secret/env**.

1. **`nestor-api`** gains three NEW report-delivery verbs (`app/api/intake_routes.py`):
   `POST /intakes/{id}/deliver` (the sole `in_research -> delivered` transition), `POST
   /intakes/{id}/report/replace` (post-delivery repoint, status stays `delivered`), and the
   status-gated `GET /intakes/{id}/report` (client report read, 404 for any status other than
   exactly `delivered` — REPORT-02). These are new Python verbs baked into the image (18-01).
2. **`nestor-frontend`** gains a NEW authenticated client route `/intake/$id/report` (delivered-only,
   download-only) + a delivered-only "View report" list CTA (18-03), and REPAIRS the previously
   gated-off admin `FinalReportBlock` into the real staged-upload → explicit-Deliver → post-delivery-
   Replace flow with `phaseShowsFinalReport` extended to include `in_research` (18-02). Both need the
   image REBUILT (new route + `routeTree.gen.ts` regeneration).

> **NO migration this phase — the schema is untouched (RESEARCH § Runtime State Inventory).** Every
> column and enum the delivery surface reads/writes ALREADY EXISTS from migration 0001:
> `intakes.final_report_artifact_id`, `intakes.results_link_sent_at` (reused as the delivered-mail
> timestamp — no new `delivered_at` column, 18-01 D), the `delivered` intake-status enum value, and
> the `research_artifacts` table (the report row is `source='human-report'`/`type='report'`). The
> `nestor-migrate` Job need **NOT** run this phase — there is no new revision to apply.

> **NO new secret/env this phase (RESEARCH § Runtime State Inventory).** The delivery mail reuses the
> Phase-10 mail stack already live on `nestor-api`: `RESEND_API_KEY` (secret), `APP_BASE_URL` (the
> mail CTA deep-links to `/intake/{id}/report`), and `NESTOR_ADMIN_EMAIL`. The delivery mail obeys the
> SAME refuse-send guard as every other results-family mail — it will NOT send if `APP_BASE_URL` is
> unset (Step 18.d is confirm-only). No new Voyage/chat env lands here (that is Phase 19).

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is FORBIDDEN on this project (it would rotate the BUILT_IN DB
> passwords and take down all services). Every step below is a manual gcloud reconciliation run in
> Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **The recurring deploy-gap (READ FIRST — Steps 18.a AND 18.c both hit it).** "Nothing is real until
> it is deployed, and a config-only env flip ships a STALE image." Phase 18 adds new Python verbs to
> `nestor-api` AND new frontend routes/UI — a `gcloud run services update --update-env-vars` on the
> current revisions ships NEITHER. Steps 18.a and 18.c are mandatory Cloud Build **image REBUILDs**,
> not env flips. Because there is no migration and no new secret this phase, the rebuild+deploy of
> the two images is the ENTIRE deploy surface — do not mistake the "no migration/no secret" simplicity
> for "no rebuild needed": a config-only flip ships stale verbs/routes.

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13/14/16/17).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be / tools@epicimpact.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

### Step 18.a — REBUILD + deploy the `nestor-api` image via Cloud Build (deliver/replace/report verbs must ship)

The running `nestor-api` container predates the Phase-18 report-delivery verbs. A config-only env
flip on the stale image is the **recurring deploy-gap** — it produces a live 404 on `POST
/intakes/{id}/deliver` (or a 500 `AttributeError`/`ModuleNotFoundError` on the new helpers) while CI
is green, and the client `GET /intakes/{id}/report` never resolves. Reuse the § Phase 16 Step-16.a /
§ Phase 17 Step-17.b backend Cloud Build idiom verbatim (the same `backend` build context; never a
local `docker build` — downloads are blocked on the dev box), then repoint the service:

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"

# Build + push via Cloud Build (bakes the deliver/replace/report verbs + DeliverBody/ReportView models
# + the _assert_report_key/_create_report_artifact/_send_report_mail helpers into the image), then
# repoint. No new pip dependency this phase (reuses the in-image storage/mail/transition seams).
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"
```

### Step 18.b — Run the intake backend suite in Cloud Build against the fresh image BEFORE the live proof

18-01 authored its pytest suite by-construction and deferred the run to Cloud Build (the dev box has
no Python). Run the full intake suite so the new Phase-18 tests execute green before you spend on the
live proof — the new `test_report_delivery.py` (deliver transition, wrong-status 409, PDF-only 422,
forged-key 404, deliver-mail stamp, mail-failure recovery, replace, report read delivered/pre-delivery)
plus the extended `test_intake_cross_tenant.py` deliver/report denial cases (deliver_cross_tenant 404,
report_cross_tenant 404, report_read_pre_delivery REPORT-02 404):

```bash
# From the repo root — source MUST be `.` (repo root), never `backend` (§ Phase 14.g / 16.a note).
gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
```

### Step 18.c — Deploy the frontend image (new `/intake/$id/report` route + repaired FinalReportBlock)

The frontend gains the authenticated delivered-only client report route `/intake/$id/report`
(`frontend/src/routes/intake.$id.report.tsx` + the regenerated `routeTree.gen.ts`), the delivered-only
"View report" list CTA (`frontend/src/routes/intake.index.tsx`), and the repaired admin
`FinalReportBlock` (staged-upload → Deliver → Replace, `phaseShowsFinalReport` includes `in_research`)
plus the `deliverReport`/`replaceReport`/`getReport` seam transport and NL/FR/EN copy. Rebuild + deploy
per the standard § Phase 12 Step-12.3 / § Phase 17 Step-17.d frontend flow (Cloud Build image REBUILD;
`--build-arg VITE_*` from substitutions; NO `VITE_SUPABASE_*` — the in-image bundle guard fails the
build if a Supabase signature leaks). Reuse the SAME `_API_BASE_URL` + Firebase substitutions captured
at Phase 12 Step 12.3 (unchanged — no URL re-wiring, no new env/secret):

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:$(date +%Y%m%d-%H%M%S)"

# Reuse the SAME _API_BASE_URL / _FB_* substitutions from Phase 12 Step 12.3 (unchanged).
gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<hash>-ew.a.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --project="$GOOGLE_PROJECT"
```

> **NO `nestor-migrate` Job run this phase.** Unlike § Phase 16 (0011) and § Phase 17 (0012), Phase 18
> lands NO migration — every column/enum/table the delivery surface reads pre-exists from migration
> 0001 (`final_report_artifact_id`, `results_link_sent_at`, the `delivered` enum, `research_artifacts`).
> Do NOT execute `nestor-migrate` here: there is no new revision, so the Job would connect, find itself
> already "at head", and exit a silent no-op. The two image rebuilds above are the entire deploy.

### Step 18.d — Confirm the mail env is present (READ-ONLY — `APP_BASE_URL` / `NESTOR_ADMIN_EMAIL` / `RESEND_API_KEY` already set)

Phase 18 introduces **no new env var and no new secret** — the delivery mail reuses the Phase-10 mail
stack already live on `nestor-api` (§ Phase 10 Steps 10.1–10.3, finalized in § Phase 12 Step 12.4).
The delivery mail obeys the SAME refuse-send guard as every results-family mail: it will NOT send if
`APP_BASE_URL` is unset (the intake is still flipped to `delivered`, but `results_link_sent_at` stays
NULL — recoverable, 18-01 T-18-05). Confirm both plain envs are present + the Resend secret is bound
(confirm-only — do NOT re-set; a wrong `APP_BASE_URL` breaks the mail CTA deep-link, Pitfall 4):

```bash
gcloud run services describe nestor-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep -E 'APP_BASE_URL|NESTOR_ADMIN_EMAIL|RESEND_API_KEY'
# expect: APP_BASE_URL=https://nestor-frontend-<hash>-ew.a.run.app   (the captured FRONTEND_URL, Phase 12)
#         NESTOR_ADMIN_EMAIL=<the ops address>
#         RESEND_API_KEY=nestor-resend-api-key:latest                (native secret reference, never the value)
```

> **CHORE (CLOSE-02, do NOT do here): rotate the Resend key post-UAT.** The Resend key transited an
> assistant chat and is scheduled for rotation to version 2 of `nestor-resend-api-key` (STATE.md
> Deferred Items → Phase 20 CLOSE-02). Do NOT rotate it during this UAT — a mid-UAT rotation would
> break the delivery mail. Rotate AFTER the Phase-18 live proof is green.

### Step 18.e — Live stage/deliver/download/mail UAT (points to 18-HUMAN-UAT.md — see Task 2 checkpoint)

With `nestor-api` rebuilt (deliver/replace/report verbs live), the intake suite green in Cloud Build,
the frontend deployed (report route + repaired admin block), and the mail env confirmed, run the
operator live session per
`.planning/phases/18-human-report-upload-client-delivery/18-HUMAN-UAT.md`:

1. On an **`in_research`** smoke intake (a completed research run from § Phase 16/17, OR an intake set
   to `in_research` directly for this UAT — the report flow does not require a real run), open the
   **admin** intake detail → the `FinalReportBlock` shows the staged-upload UI (it mounts during
   `in_research` via `phaseShowsFinalReport`).
2. **Stage (REPORT-02 pre-delivery invisibility):** upload a real PDF (crafted in Claude Design from
   the § Phase-17 bundle's `report.md`) → it STAGES locally; confirm the intake status STAYS
   `in_research` and a **CLIENT** login shows **NO report** (the `/intake/$id/report` route redirects
   and the list shows no "View report" CTA). This is the T-18-15 blocking check.
3. **Deliver (REPORT-01):** click **Deliver** → the `RecipientPicker` (results copy family) opens →
   confirm → status flips to `delivered`; the delivery email arrives at the recipient inbox — check the
   locale is correct for the recipient (**NL / FR / EN** per the recipient's language); the CTA
   deep-links to `/intake/{id}/report`.
4. **Client download (REPORT-02):** log in as a **CLIENT** member of that space → the intake list now
   shows **"View report"** → open the page → **download and open the PDF** (signed-URL attachment,
   download-only, no inline viewer). The Phase-19 chat placeholder shows but has no chat surface (D-07).
5. **Replace (REPORT-03):** replace the report with a corrected PDF (status STAYS `delivered`); verify
   the client gets the NEWEST file; test both the **silent replace** (no re-notify) and the optional
   **re-notify** (RecipientPicker → new mail) paths.
6. Record the intake id, recipient(s), locales seen (NL/FR/EN), download success, and PASS/FAIL per
   **REPORT-01/02/03** (plus any defects) in `18-HUMAN-UAT.md`.

Failure triage:
- `POST /intakes/{id}/deliver` **404** → Step-18.a rebuild was skipped (stale image, recurring
  deploy-gap). A 500 `AttributeError` / `ModuleNotFound` on deliver → same (the new helpers/verbs did
  not ship).
- The `/intake/{id}/report` route **404s in the browser** → Step-18.c frontend deploy was skipped OR
  `routeTree.gen.ts` was not regenerated (the route is unregistered in the shipped bundle).
- **A client sees the report BEFORE delivery** → the front status gate (`status !== "delivered"`
  redirect) or the backend status-gate (`GET /report` exact-equality 404) regressed → **STOP, this is
  a REPORT-02 breach — do not accept the phase** (T-18-15 blocking).
- **Mail never arrives** → check `APP_BASE_URL` / `RESEND_API_KEY` (Step 18.d) and the `nestor-api`
  logs for the refuse-send warning (a delivered intake with `results_link_sent_at` NULL = the mail
  was refused/failed; the flip is still recoverable, re-send by replacing with re-notify).

---

## Phase 15 — Research engine redesign: operator surfaces (dual tribunal REBUILD + 0011 migrate + frontend REBUILD, NO new secret)

This section is the enumerated source of truth for the Plan 15-07 operator live session that ships the
Phase-15 research-engine-redesign OPERATOR SURFACES to production. Phase 15 adds surface to THREE
deployables — BOTH Tribunal images (`tribunal-worker` AND `tribunal-api`) plus the frontend — and lands
ONE migration (alembic **0011** in the **tribunal** schema, NOT the intake `nestor` line). There is
**NO new secret and NO new env** this phase (SERPAPI is Phase 15.2 / D10, not here). *(SERPAPI has
since LANDED — see § Phase 15.2, Step 15.2.b.)*

**Why BOTH Tribunal images rebuild (unlike Phase 17, which rebuilt only tribunal-api):**

1. **`tribunal-worker`** carries the C1 cost-truth fix — `audit/audited_llm_client.py` +
   `audit/cost_table.py` + `audit/cost_prices.json` + `audit/writer.py` (cache-CREATE tokens priced,
   `web_search`/`web_fetch` server-tool fees counted, Gemini deep-research `usageMetadata` recorded,
   `run.cost_pending` set when the grounding fee is un-itemizable). The worker is the RUN-EMITTING
   side — it writes the per-call `cost_usd` and the `cache_creation_tokens` column the feed reads. If
   the worker image is stale, every future run still under-counts cost (~€5 vs ~$43–45, the P1 defect).
2. **`tribunal-api`** carries the new READ surfaces the operator UI calls: `GET /api/runs/{run_id}/verification`
   (the verification report shaper over `verification_verdict` + `run.verification_summary`), the enriched
   `GET /api/runs/{run_id}/metrics` `stage_detail` (D15 feed items with per-row cost + `audit_id`), the
   citation numbering read, and `GET /api/runs/{run_id}/audit/{audit_id}` (the feed drill-down GCS reader).
   If the api image is stale, the intake seam proxies (already shipped on `nestor-api`) 404 on real calls.

The worker emits cost, the api serves the read surfaces — **so BOTH rebuild at one `$SHA`.** This mirrors
the § Phase 17 Step-17.a dual-rebuild idiom, except Phase 17 left the worker unchanged and Phase 15 does not.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is FORBIDDEN on this project (it would rotate the BUILT_IN DB
> passwords and take down all services). Every step below is a manual gcloud reconciliation run in
> Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **The recurring deploy-gap (READ FIRST — Steps 15.a AND 15.c both hit it).** "Nothing is real until
> it is deployed, and a config-only env flip ships a STALE image." Phase 15 adds new code to BOTH
> Tribunal images AND the frontend, plus the 0011 migration — a `gcloud run services update
> --update-env-vars` on the current revisions ships NONE of it. Steps 15.a and 15.c are mandatory Cloud
> Build **image REBUILDs**, not env flips. This phase introduces **NO new env var and NO new secret**
> (Step 15.d is confirm-only + the verify gates): SERPAPI (the own-researcher key) is **Phase 15.2**
> (D10), not this phase. *(SERPAPI has since LANDED — see § Phase 15.2, Step 15.2.b.)*

> **NO nestor-api rebuild this phase.** The intake-side seam proxies + frontend transport
> (`/intakes/{id}/research/{run}/verification`, `/research/sources/{sourceId}`,
> `/research/{run}/audit/{auditId}`) shipped as PART of the Plan 15-04/15-05/15-06 code that lands in
> the frontend rebuild (Step 15.c) and the ALREADY-DEPLOYED `nestor-api` — Plan 15-04's proxy routes
> were authored into `backend/app/api/research_routes.py`. **Re-confirm** whether the live `nestor-api`
> revision predates the Plan 15-04 proxy routes; if it does, rebuild `nestor-api` per the § Phase 17
> Step-17.b idiom BEFORE the frontend (the frontend calls those proxies). If the live `nestor-api`
> already carries them (e.g. a Phase-17/18 rebuild post-dated 15-04), no nestor-api rebuild is needed —
> the Tribunal read endpoints are the only new server surface. Check the deployed image tag against the
> Plan 15-04 commit (`ac6102d`) date before deciding.

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13/14/16/17/18).
export GOOGLE_PROJECT="<the intake Nestor Pulse project id>"     # acct tools@dotto.be / tools@epicimpact.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export TRIBUNAL_SA="tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

### Step 15.a — REBUILD + deploy BOTH Tribunal images via Cloud Build at ONE `$SHA` (worker cost fix + api read surfaces)

BOTH `tribunal-worker` (cost fix in `audited_llm_client` / `cost_table` — the run-emitting side) AND
`tribunal-api` (new `/verification` + enriched `/metrics` + citation numbering + `/audit/{audit_id}`)
change this phase, so BOTH images rebuild at one `$SHA`. This is an **image REBUILD, not an env flip.**
Reuse the § Phase 13.e / 14.b / 17.a Cloud Build idiom (never a local `docker build` — downloads are
blocked on the dev box). The retargeted deploy scripts pin `IMAGE_TAG=$SHA` and PRESERVE the Phase-14
lockdown (tribunal-run SA + `--no-allow-unauthenticated` + invoker=nestor-run ONLY — NOT re-granted here).

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

# Rebuild tribunal-worker (bakes the C1 cost fix into the run-emitting image).
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"

# Rebuild tribunal-api (bakes the new /verification + enriched /metrics + citation + /audit endpoints).
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"

# Redeploy BOTH at the just-built tag via the retargeted deploy scripts (worker first, then api —
# same order as § Phase 13.g). The scripts keep tribunal-run SA + --no-allow-unauthenticated +
# invoker=nestor-run; the Phase-14 lockdown is PRESERVED by the scripts, NOT re-granted here.
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh
```

Confirm the tribunal-api URL is UNCHANGED from Phase 14/16/17 (a redeploy of an existing service keeps
its URL; capture it read-only for the Step-15.d confirm — do NOT re-set the seam env, Pitfall 4). This
is the `describe` WITHOUT a path (the OIDC audience is the path-less `service_url`):

```bash
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
echo "tribunal-api URL: $TRIBUNAL_URL"   # expect the SAME https://tribunal-api-...-ew.a.run.app as Phase 14/16/17
```

### Step 15.b — Run the `tribunal-migrate` Job with `--wait` to apply alembic 0011 (into the TRIBUNAL schema, using the JUST-BUILT image)

The `tribunal-migrate` Cloud Run Job runs `alembic upgrade head` into the **tribunal** schema (app_user
DSN — the SAME pattern as § Phase 13.f). Migration **0011** (`0011_cost_verification.py`,
`down_revision = "0010"`) adds `audit_log.cache_creation_tokens` (nullable, non-hashed),
`run.cost_pending` (bool default false), `run.verification_summary` (JSONB nullable), and the
`verification_verdict` FORCE-RLS read-model table (tenant policy copied verbatim from 0003). All are
ADDITIVE and land OUTSIDE the frozen hash-chain payload (`_payload_for_row` untouched, T-15-01). This is
the **tribunal** alembic line — it does NOT touch the intake `nestor` migrations (whose head is 0012
after § Phase 17).

> ⚠️ **LESSON (image-pin, hit live 2026-07-22 on `nestor-migrate`): the Job does NOT track the service
> image.** Redeploying `tribunal-api`/`tribunal-worker` at `$SHA` leaves the `tribunal-migrate` Job
> pinned to its OLD image — executing it then is a **silent no-op** (alembic connects, finds itself "at
> head" on the stale revision set, exits 0, logs no `Running upgrade` line). ALWAYS repin the Job to the
> just-built image FIRST:

```bash
gcloud run jobs update tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}"   # the SAME $SHA built in Step 15.a
gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
# CONFIRM the log shows "Running upgrade 0010 -> 0011" — no upgrade line = stale-image no-op.
```

Then confirm the migration landed in the TRIBUNAL schema (read-only, via the migrate Job's connection or
a Cloud SQL psql session):

```bash
#   \d tribunal.audit_log        -> cache_creation_tokens  int  (nullable)
#   \d tribunal.run              -> cost_pending  bool (default false); verification_summary  jsonb (nullable)
#   \d tribunal.verification_verdict  -> table exists; ENABLE + FORCE ROW LEVEL SECURITY;
#        tenant-isolation policy present (copied from 0003); idx_verification_verdict_tenant_run present.
#   alembic head in the TRIBUNAL line == 0011 (NOT the nestor 0012 head — different alembic line).
#   Pre-existing rows keep NULL on the new columns (no server_default backfill except run.cost_pending=false).
```

> ⚠️ **HEAD HAS MOVED SINCE (2026-07-25).** The `== 0011` expectation above was correct **for this
> phase**. The Phase-15.1 gap-closure pass applied `0012_verdict_superseded_note.py`, so the TRIBUNAL
> line's head is now **`0012`** — see § Phase 15.1 Step 15.1.f. Re-running the check above today
> should read `0012`, not `0011`; that is not a regression. (The version table is
> `tribunal.tribunal_alembic_version` — the tribunal line keeps its own, deliberately named apart
> from the intake `nestor` line's `alembic_version`.)

Alembic still below `0011` in the tribunal line after this → the Job in this step did not run (or ran on
the pre-rebuild image); re-run Step 15.a then this step.

### Step 15.c — REBUILD + deploy the frontend image (D15 feed + VerificationReport + CitationPanel + audit drill-down + i18n)

The frontend gains the Plan 15-05/15-06 operator surfaces: the D15 agent-feed renderer + `AuditBodyPanel`
drill-down + superadmin `VerificationReport` (`frontend/src/components/intake/ResearchRunProgress.tsx`,
`VerificationReport.tsx`, `AuditBodyPanel.tsx`), the numbered `CitationPanel` (`CitationPanel.tsx`), the
`getVerification`/`getAuditBody`/`getSource` transport (`frontend/src/lib/api/research.ts`), and en/fr/nl
i18n keys. **NO new route is added** — the components mount on the EXISTING
`admin.pulse.intakes.$id` anchor (via `ResearchRunProgress`), so **`routeTree.gen.ts` does NOT need
regenerating** (unlike § Phase 18, which added a route). Rebuild + deploy per the standard § Phase 12
Step-12.3 / § Phase 17 Step-17.d frontend flow (Cloud Build image REBUILD; `--build-arg VITE_*` from
substitutions; **NO `VITE_SUPABASE_*`** — the in-image bundle guard fails the build if a Supabase
signature leaks). Reuse the SAME `_API_BASE_URL` + Firebase substitutions captured at Phase 12 Step 12.3
(unchanged — no URL re-wiring, no new env/secret):

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:$(date +%Y%m%d-%H%M%S)"

# Reuse the SAME _API_BASE_URL / _FB_* substitutions from Phase 12 Step 12.3 (unchanged).
gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<hash>-ew.a.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --project="$GOOGLE_PROJECT"
```

### Step 15.d — Verify without printing secrets (Cloud Build pytest targets + `verify_chain` re-run on deployed data + endpoint role checks) — NO new secret this phase

Phase 15 introduces **NO new env var and NO new secret** (15-RESEARCH § Runtime State Inventory: SERPAPI
is Phase 15.2 / D10). *(SERPAPI has since LANDED — see § Phase 15.2, Step 15.2.b.)* This step is
confirm-only for env + the automated verify gates. All four sub-checks
run WITHOUT printing any secret value.

1. **Run the Phase-15 pytest targets in Cloud Build against the fresh images** (authored by-construction
   in Plans 15-01…15-06; the dev box has no Python, so they run at deploy). The tribunal suite covers
   the hash-chain-green-post-0011 replay, the cost recompute, the verification-report shaping + RLS
   denials, the citation numbering, and the audit-body denials; the intake suite covers the seam denial
   trios + the superadmin happy path:

   ```bash
   # Tribunal side (cost + verification + citation + chain):
   gcloud builds submit tribunal --config=tribunal/cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
   # Intake side (seam proxies + denial trios + superadmin funnel happy path):
   # From the repo root — source MUST be `.` (repo root), never `backend` (§ Phase 14.g / 16.a note).
   gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
   ```

2. **Re-run `verify_chain` GREEN on the DEPLOYED audit data (SC5 — the phase gate).** The 0011 migration
   is additive and keeps the new columns OUTSIDE the frozen hash-chain payload, so `verify_chain` must
   stay green on the live audit chain after the migration lands. This is the T-15-17 mitigation — the
   deployed-data re-verify BEFORE sign-off. Run the tribunal `verify_chain` proof against the live audit
   chain (the same job used in § Phase 13.h / 14 / 16 to prove chain integrity):

   ```bash
   # verify_chain against the deployed run's audit chain (e.g. the recorded/parked run) — expect GREEN.
   # (Run via the tribunal verify-chain Cloud Build target / job the prior phases used; no secret printed.)
   gcloud builds submit tribunal --config=tribunal/cloudbuild.test-critical.yaml --project="$GOOGLE_PROJECT"
   ```

   A RED chain here is a STOP — do not sign off; investigate whether a non-additive change slipped into
   `_payload_for_row` (T-15-01).

3. **Confirm the recorded run's read endpoints answer correctly per role** (superadmin 200, client 404) —
   the intake-seam proxies over the now-rebuilt tribunal-api. On the recorded run's intake, a superadmin
   GET of `/intakes/{id}/research/{run}/verification` (and enriched `/metrics`) returns **200**; the SAME
   path for a **client** (user-role) member of that space returns **404** (existence-hidden, 16-D-08 /
   T-15-18). These are proven automatically by the intake denial-trio + happy-path tests in sub-check 1;
   the browser confirmation is Step 15.f (the UAT), item 3.

4. **Confirm NO new env/secret is needed (READ-ONLY).** The operator surfaces reuse the EXISTING seam
   (`TRIBUNAL_SERVICE_URL` on `nestor-api` — the Phase-14/16 OIDC audience) and the EXISTING tribunal
   audit bucket (`AUDIT_GCS_BUCKET` on the tribunal services — the audit-body reader source). No new key
   this phase. Confirm the seam env is present (confirm-only — do NOT re-set; a wrong value breaks the
   seam, Pitfall 4):

   ```bash
   gcloud run services describe nestor-api \
     --region="$REGION" --project="$GOOGLE_PROJECT" \
     --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep -E 'TRIBUNAL_SERVICE_URL'
   # expect: TRIBUNAL_SERVICE_URL=https://tribunal-api-...-ew.a.run.app  (same as Step 15.a $TRIBUNAL_URL)
   ```

   **Explicitly: NO SERPAPI_API_KEY this phase** — the own-researcher key lands in Phase 15.2 (D10). Do
   NOT create or seed it here. *(It HAS since landed — created, granted and seeded in § Phase 15.2,
   Step 15.2.b, and bound to BOTH Tribunal services in Step 15.2.e. This Phase-15 step stays
   confirm-only: nothing to do here.)*

### Step 15.e — (conditional) rebuild `nestor-api` ONLY if the live revision predates the Plan 15-04 proxy routes

If the live `nestor-api` revision predates the Plan 15-04 seam proxy routes (`ac6102d` —
`/intakes/{id}/research/{run}/verification`, `/research/sources/{sourceId}`, `/research/{run}/audit/{auditId}`
on `research_routes.py`), rebuild it per the § Phase 17 Step-17.b idiom BEFORE the frontend deploy
(Step 15.c calls those proxies). If the live `nestor-api` already carries them (a Phase-17/18 rebuild
post-dated 15-04 in the same tree), SKIP this step — no nestor-api rebuild is needed. This phase lands
**NO intake `nestor` migration** (the 0011 migration is the TRIBUNAL line only), so the `nestor-migrate`
Job need NOT run this phase.

```bash
# Only if the deployed nestor-api image tag predates commit ac6102d:
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:$(date +%Y%m%d-%H%M%S)"
gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" --image "$IMAGE"
# NO nestor-migrate run — Phase 15 lands no intake-line migration (0011 is the tribunal line, Step 15.b).
```

### Step 15.f — Operator recorded-run UAT (points to 15-UAT.md — see Task 3 checkpoint)

With BOTH Tribunal images rebuilt at one `$SHA` (worker cost fix + api read surfaces), the tribunal 0011
migration applied, the frontend deployed, the Phase-15 pytest targets green in Cloud Build, and
`verify_chain` re-run green on the deployed audit data, run the operator RECORDED-RUN session per
`.planning/phases/15-engine-enhancements-plan-critique-draft-tournament-deferred-/15-UAT.md`.

**NO live LLM run is needed** — the UAT walks the RECORDED run-4cbb5311 on the admin intake detail page
(the Anthropic monthly cap blocks live runs until 2026-08-01; the recorded fixture supplies all surface
data). Walk 15-UAT.md steps 1–5: the D15 feed vs `replit view.png` incl. the audit-body drill-down; the
verification report content; facts-only cost with the pending state; every `[n]` citation resolves; a
CLIENT login sees NONE of it (16-D-08); and `verify_chain` green (SC5). Record PASS/FAIL + the V-02
operator sign-off in 15-UAT.md, read next to the recorded baseline
`docs/tribunal-run-reports/run-20260722-4cbb5311/`.

Failure triage: the verification report / feed **404s for a superadmin** → Step-15.a tribunal-api rebuild
was skipped (stale image, recurring deploy-gap — the seam proxy hits a stale endpoint). Per-row cost shows
the OLD ~€5 undercount → Step-15.a tribunal-WORKER rebuild was skipped (the cost fix did not ship). A
`[n]` citation dangles or the drill-down is empty → the 0011 migrate (Step 15.b) ran on a stale image
(silent no-op — no `Running upgrade 0010 -> 0011` line). A **client** can reach ANY research surface →
STOP, this is a 16-D-08 breach — do not accept the phase.

---

## Phase 15.1 — Verification gates (dual tribunal REBUILD, **NO migration**, **NO env change**, NO new secret)

This section is the enumerated source of truth for shipping the Phase-15.1 VERIFICATION GATES to
production. Phase 15.1 replaces the verification stage's selection logic — materiality +
error-likelihood gates, LLM canonical grouping, corroboration prioritization, honest three-bucket
accounting, a fourth `superseded` verdict and a loud degradation marker. It touches **exactly two
deployables** (`tribunal-worker` AND `tribunal-api`) and **nothing else**:

> 🔁 **TWO OF THE FOUR BULLETS BELOW ARE SUPERSEDED (2026-07-25 gap-closure pass).** They were
> accurate for the ORIGINAL Phase-15.1 pass (plans 15.1-01 … 15.1-10, deployed at `$SHA`
> `20260725-220005`). The gap-closure pass (plans 15.1-11 … 15.1-16) **does** land a tribunal
> migration and **does** require a frontend rebuild. Read Steps **15.1.f** and **15.1.g** before
> acting on the "NO migration" or "NO frontend rebuild" bullets. They are annotated in place rather
> than deleted, because the original pass's record has to stay readable.

- **NO migration** — see Step 15.1.a. **← SUPERSEDED for the gap-closure pass: migration `0012`
  (`0012_verdict_superseded_note.py`) IS applied. See Step 15.1.f.**
- **NO Cloud Run env change and NO new secret** — see Step 15.1.b. *(Still true, including for the
  gap-closure pass — it adds no tunable and no secret.)*
- **NO frontend rebuild** — **← SUPERSEDED for the gap-closure pass by Step 15.1.g:** plan 15.1-16
  edits `VerificationReport.tsx`, `lib/api/research.ts` and the three `intake.json` locale files, so
  the image MUST be rebuilt or the `verdicts.superseded` section and its caveat exist only in the
  JSON payload. The original reasoning, true for the original pass, follows —
  output. `VerificationReport.tsx` renders the funnel via `Object.entries(report.funnel)`, so the
  new funnel keys appear with **no frontend change**. (One honest caveat is recorded as a known
  gap in `15.1-UAT.md` § Known gaps: the backend now emits `verification_degraded_text`, but no
  component renders it yet — the operator sees degradation as raw funnel keys plus the D15 feed's
  closing sentence. Closing that is a frontend change, deliberately out of this phase's scope.)
- **NO `nestor-api` rebuild** — no intake-side surface changed this phase.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is FORBIDDEN on this project (it would rotate the BUILT_IN DB
> passwords and take down all services). Every step below is a manual gcloud reconciliation run in
> Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no Docker).

> **The recurring deploy-gap (READ FIRST).** "Nothing is real until it is deployed." Phases 6, 8,
> 10 and 11 were all *executed but not deployed*. Gate code that only exists in git changes nothing
> about the next real run — the engine will keep sending ~950 claims to the fact-checkers and keep
> reporting a gutted verification as green. Step 15.1.c is a mandatory **image REBUILD**; there is
> no env flip that ships it, because this phase adds no env var to flip.

### Step 15.1.a — CONFIRM there is nothing to migrate (do NOT run the migrate Job)

> 🔁 **SUPERSEDED FOR THE GAP-CLOSURE PASS — read this before following the step below.** This step
> was correct for the ORIGINAL Phase-15.1 pass (plans 15.1-01 … 15.1-10). The **2026-07-25
> gap-closure pass (plans 15.1-11 … 15.1-16) DOES land a tribunal-line migration** —
> `0012_verdict_superseded_note.py`, one nullable `superseded_note TEXT` column on
> `verification_verdict` — and it **was applied live**. **Step 15.1.f supersedes this step's "do NOT
> run the migrate Job" instruction for that pass**, and the tribunal alembic head is now **`0012`**,
> not `0011`. The text below is kept unedited as the record of the original pass.

**Phase 15.1 lands NO migration.** The tribunal alembic head stays at **0011**
(`0011_cost_verification.py`, shipped in § Phase 15 Step 15.b). Both columns this phase writes
already exist:

- `run.verification_summary` — JSONB, nullable. Created by 0011. Phase 15.1 gives it its FIRST
  production writer (`runs/worker.py`, in the same `UPDATE` statement that sets
  `status='completed'`), but the column itself is unchanged.
- `verification_verdict.verdict` — free **`TEXT`, with NO enum and NO CHECK constraint**. The new
  fourth value `superseded` therefore needs no DDL; only the tool schema, the parser, adjudication
  and the report shaper changed, and those all ship inside the image.

```bash
# Confirm — read-only. Expect 0011_cost_verification.py, i.e. NO 0012 in the tribunal line.
ls tribunal/nestor_pulse_sdk/alembic/versions/ | tail -1
```

> ⚠️ **Do NOT run `gcloud run jobs execute tribunal-migrate` for this phase.** There is no
> `0011 -> 0012` upgrade to apply. (The image-pin lesson from § Phase 15 Step 15.b — a Job left
> pinned to a stale image is a silent no-op — still stands for any FUTURE phase that does land a
> migration; it simply does not apply here because no Job should run at all.)

### Step 15.1.b — CONFIRM no Cloud Run env change is required (read-only)

Every tunable this phase introduces is read at import with a **production-safe default**, so the
deployed services need no `--update-env-vars` and no new secret. Set one ONLY to deviate from the
default:

| Env var | Default | Read by | Effect |
|---|---|---|---|
| `NESTOR_TRIBUNAL_GATE_BATCH` | `40` | `pipeline/tribunal/gates.py` | claims per gate-classifier call |
| `NESTOR_TRIBUNAL_GATE_CONCURRENCY` | `4` | `gates.py` | bounded fan-out over gate batches |
| `NESTOR_TRIBUNAL_GATE_RETRIES` | `2` | `gates.py` | extra attempts on a **transient** gate failure (cap/billing 400s are never retried) |
| `NESTOR_TRIBUNAL_GATE_BACKOFF_S` | `2.0` | `gates.py` | exponential-backoff base between gate retries |
| `NESTOR_TRIBUNAL_GATE_CONTEXT_CHARS` | `2000` | `gates.py` | ceiling on the decision context in the gate prompt |
| `NESTOR_TRIBUNAL_GATE_BRIEF_CHARS` | `1200` | `pipeline/tribunal/pipeline.py` | ceiling on the mission brief fed in as that decision context (the tighter of the two) |
| `NESTOR_TRIBUNAL_CLUSTER` | `true` | `pipeline/tribunal/grouping.py` | **ROLLBACK LEVER 1** — see below |
| `NESTOR_TRIBUNAL_CLUSTER_BATCH` | `40` | `grouping.py` | claims per clustering call |
| `NESTOR_TRIBUNAL_CLUSTER_MAX_BLOCK` | `60` | `grouping.py` | max claims in one blocking group before chunking |
| `NESTOR_TRIBUNAL_CLUSTER_CONCURRENCY` | `4` | `grouping.py` | bounded fan-out over cluster blocks |

**The two rollback levers — no redeploy needed, these are config-only `--update-env-vars` on the
already-deployed image:**

1. **`NESTOR_TRIBUNAL_CLUSTER=false`** restores the pre-15.1 exact-key `ENTITY|ATTRIBUTE`
   bucketing in `grouping.py`. Use this if LLM clustering misbehaves; `group_claims`'s signature
   and five-key return shape are frozen across both paths, so nothing downstream notices.
2. **`NESTOR_TRIBUNAL_GROUP_VERIFY=false`** (pre-existing, unchanged) still switches the verify
   stage to the per-claim fallback branch. That branch was **rewired**, not deleted: it now selects
   from `claim["gate"]["strict"]` instead of stakes triage, so the gates remain the selector in
   both modes.

There is deliberately **no lever that turns the gates off entirely.** The gates ARE the selector
now (G-02); disabling them would leave the verify stage with no selection rule at all.

```bash
# Confirm-only read — do NOT re-set anything (a wrong value breaks the Phase-14 seam, Pitfall 4).
# Expect: none of the NESTOR_TRIBUNAL_GATE_* / _CLUSTER* names appear. That is CORRECT — the
# defaults are compiled into the image and no env is needed.
gcloud run services describe tribunal-worker \
  --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format="value(spec.template.spec.containers[0].env)" | tr ',' '\n' | grep -E 'NESTOR_TRIBUNAL' || true
```

### Step 15.1.c — REBUILD + deploy BOTH Tribunal images at ONE `$SHA`

**BOTH images must rebuild.** The gate, cluster, funnel and accounting code all live in the shared
`nestor_pulse_sdk` package, which is baked into both images:

1. **`tribunal-worker`** runs the pipeline. It is the side that executes `apply_gates()`, does the
   clustering, computes the funnel — and it is the **only** writer of `run.verification_summary`
   (`runs/worker.py`, in the same statement as `status='completed'`). A stale worker means the gates
   never run and the honesty marker is never written, no matter what the api image contains.
2. **`tribunal-api`** serves the read surface. `verification/report.py`'s shaper — the three
   accounting buckets, the degradation sentence, the `superseded` verdict class — is what the
   superadmin verification report calls. A stale api serves the OLD two-way `unverified` arithmetic
   over the new funnel, i.e. the P1 defect this phase closes, silently.

The worker computes, the api serves — **so BOTH rebuild at one `$SHA`.** Same idiom as § Phase 13.e
/ 14.b / 15.a; never a local `docker build` (downloads are blocked on the dev box).

> ⚠️ **Image-pin: deploy the SPECIFIC tag just built, NEVER `:latest`.** This is the lesson carried
> from § Phase 15 Step 15.b and § Phase 17 (hit live 2026-07-22 on `nestor-migrate`): an unpinned
> reference resolves to whatever the registry last saw, which silently ships a different image than
> the one you just tested. The retargeted deploy scripts pin `IMAGE_TAG=$SHA` for exactly this
> reason.

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

# Rebuild tribunal-worker (bakes gates.py + the clusterer + _build_funnel + the
# verification_summary write into the run-EXECUTING image).
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"

# Rebuild tribunal-api (bakes the report shaper's accounting buckets + degradation text +
# superseded verdict class + the widened pydantic schemas into the READ-surface image).
gcloud builds submit tribunal \
  --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"

# Redeploy BOTH at the just-built tag via the retargeted deploy scripts (worker first, then api —
# same order as § Phase 13.g / 15.a). The scripts pin IMAGE_TAG=$SHA and PRESERVE the Phase-14
# lockdown (tribunal-run SA + --no-allow-unauthenticated + invoker=nestor-run ONLY — NOT re-granted
# here). Do NOT hand-roll a `gcloud run deploy` for these two services.
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh
```

### Step 15.1.d — Verify the deploy (describe + `/readyz`) — NO live research run

```bash
# Both services must show a NEW revision serving 100% of traffic.
gcloud run services describe tribunal-worker --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(status.latestReadyRevisionName)'
gcloud run services describe tribunal-api --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(status.latestReadyRevisionName)'

# Traffic must be 100% on the new revision (not split with the previous one).
gcloud run services describe tribunal-api --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(status.traffic)'

# Confirm the tribunal-api URL is UNCHANGED from Phase 14/15/16/17 (a redeploy of an existing
# service keeps its URL). Capture read-only — do NOT re-set the seam env (Pitfall 4).
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
echo "tribunal-api URL: $TRIBUNAL_URL"   # expect the SAME https://tribunal-api-...-ew.a.run.app

# /readyz — tribunal-api is --no-allow-unauthenticated (Phase-14 lockdown), so the probe carries an
# identity token. A 200 proves the new revision boots and its DB connection is live.
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$TRIBUNAL_URL/readyz"
```

> **NO live research run is triggered by this step.** The Anthropic monthly cap resets
> **2026-08-01**; a run before then buys a red herring, not a proof. The gate code is proven by the
> deterministic fixture replay recorded in `15.1-UAT.md` § Phase Gate (zero LLM calls). The live
> confirmation — the gate classifier's agreement against the blind answer key, and whether the four
> known contradiction pairs cluster together — is the operator's hand-run August calibration, and it
> is **informational, never a gate** (G-01/G-05).

### Step 15.1.e — Deferred operator UAT (batched, NOT run at deploy time)

Per the operator's standing direction (2026-07-24), the Phase-15\* browser walkthroughs are run
**once, combined**, against a real live Tribunal run after 2026-08-01 — not piecemeal per phase, and
with **no live-DB seeding**. The Phase-15.1 checklist is written and waiting at
`.planning/phases/15.1-research-engine-redesign-verification-gates-inserted-2026-07/15.1-UAT.md`
§ Deferred Browser UAT. Do not run it in isolation.

Failure triage for the deploy itself: the verification report shows the OLD `unverified` count with
no gate funnel keys → the **tribunal-api** rebuild was skipped (stale read surface). A new run
completes but `run.verification_summary` is NULL and no `gate` stage appears in the D15 feed → the
**tribunal-worker** rebuild was skipped (the gates never ran). Either symptom means Step 15.1.c was
not completed — re-run it; there is no env flip that fixes a stale image.

### Step 15.1.f — Gap closure (plans 15.1-11 … 15.1-16): alembic 0012 + dual Tribunal rebuild

**EXECUTED LIVE 2026-07-25** at `$SHA` `20260725-233634`. This step supersedes Step 15.1.a for the
gap-closure pass: that pass persists a new `verification_verdict.superseded_note` column, so it
carries a real tribunal-line migration.

> ⚠️ **ORDER IS LOAD-BEARING: build BOTH images → migrate → THEN deploy.** Two independent reasons,
> and getting either wrong is silent:
>
> 1. **The column must exist before the new writer runs.** Plan 15.1-14's `_insert_verdict` writes
>    `superseded_note` on every verdict. If the code ships ahead of the migration, every verdict
>    `INSERT` fails, **Stage 7's `try/except` swallows it**, and the run completes with **zero
>    verdicts** — the exact hollow surface this pass exists to close, and it would look like success.
> 2. **The migrate Job applies the alembic revisions baked into an IMAGE.** The image carrying `0012`
>    must therefore exist *before* the Job can apply it.

```bash
export GOOGLE_PROJECT=project-cb01b861-cb4a-438d-b9a
export REGION=europe-west1
export SHA="$(date +%Y%m%d-%H%M%S)"

# 1. Build BOTH Tribunal images at ONE $SHA (same idiom as Step 15.1.c).
#    The worker WRITES verdict rows; the api SERVES the report shaper. Both are required.
gcloud builds submit tribunal --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"
```

> ⚠️ **LESSON (image-pin, hit live 2026-07-22 on `nestor-migrate`), quoted verbatim from § Phase 15
> Step 15.b: "the Job does NOT track the service image. Redeploying `tribunal-api`/`tribunal-worker`
> at `$SHA` leaves the `tribunal-migrate` Job pinned to its OLD image — executing it then is a
> silent no-op (alembic connects, finds itself 'at head' on the stale revision set, exits 0, logs no
> `Running upgrade` line). ALWAYS repin the Job to the just-built image FIRST."**
>
> **This was REAL on 2026-07-25, not theoretical.** Before the repin, the Job was pinned to
> `tribunal-api:20260724-214354` — an image two deploys old, whose baked revision set tops out at
> `0011`. Executing it unpinned would have exited 0 and applied nothing.

```bash
# 2. REPIN the migrate Job to the JUST-BUILT api image — BEFORE executing it.
gcloud run jobs update tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}"

# Confirm the repin actually took (cheap, and the whole step depends on it).
gcloud run jobs describe tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.template.spec.containers[0].image)'   # must echo :${SHA}

# 3. Execute the migration.
gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

**4. CONFIRM the upgrade actually ran — an exit code is NOT proof.** Read the execution log and
require the literal line:

```
Running upgrade 0011 -> 0012
```

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="tribunal-migrate"
   AND labels."run.googleapis.com/execution_name"="<EXECUTION_ID>"' \
  --project="$GOOGLE_PROJECT" --limit=50 --format="value(textPayload)"
```

**Absence of that line means the Job ran on a stale image — repin and re-execute.** Do not proceed
to the deploy on a `Container called exit(0)` alone.

**5. Confirm the schema read-only.** Note the tribunal line's version table is
**`tribunal.tribunal_alembic_version`**, NOT `alembic_version` (set via `version_table` /
`version_table_schema` in `alembic/env.py`) — querying `tribunal.alembic_version` raises
`UndefinedTableError` and is a false alarm, not a failed migration. Expect:

```
col superseded_note text nullable=YES
rls enabled=true forced=true
policy verification_verdict_tenant_isolation
index idx_verification_verdict_tenant_run
index verification_verdict_pkey
tribunal_head = 0012
```

The RLS assertions matter: migration `0012` issues **no security DDL at all** (one `op.add_column`
and nothing else), so ENABLE + FORCE ROW LEVEL SECURITY and the
`verification_verdict_tenant_isolation` policy must come through **unchanged**. A PostgreSQL row
policy is a table-level object, so the new column is covered by construction. This is the **TRIBUNAL**
line — NOT the intake `nestor` line, whose own `0011`/`0012` belong to Phases 16/17.

```bash
# 6. Deploy worker first, then api — ONLY after the migration is confirmed.
#    Always the retargeted scripts (never a hand-rolled `gcloud run deploy`): they pin IMAGE_TAG
#    and PRESERVE the Phase-14 lockdown (tribunal-run SA, --no-allow-unauthenticated,
#    invoker=nestor-run ONLY — not re-granted here).
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh

# 7. Post-deploy verification (no live run — Anthropic monthly cap resets 2026-08-01).
gcloud run services describe tribunal-worker --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(status.latestReadyRevisionName,status.traffic)'
gcloud run services describe tribunal-api --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(status.latestReadyRevisionName,status.traffic)'

# Digest-pin proof: each revision must resolve to an @sha256: digest, never :latest.
gcloud run revisions describe <REVISION> --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.containers[0].image)'

# URL captured WITHOUT a path (the OIDC audience is the path-less service_url; Pitfall 4 —
# do NOT re-set the seam env), then /readyz with an identity token.
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$TRIBUNAL_URL/readyz"
```

**Still NOT touched by this pass:** no new secret, **no Cloud Run env change** (the gap-closure code
adds no tunable — Step 15.1.b stands unchanged), and **no `nestor-api` rebuild** (no intake-side
surface changed). **NO live research run is triggered** — the Anthropic monthly cap resets
**2026-08-01**.

### Step 15.1.g — Gap closure: FRONTEND rebuild + deploy

**EXECUTED LIVE 2026-07-25** at the same `$SHA` `20260725-233634`. This step supersedes the
"**NO frontend rebuild**" bullet in the § Phase 15.1 preamble for the gap-closure pass.

**Why it is mandatory this pass.** Plan 15.1-16 edits
`frontend/src/components/intake/VerificationReport.tsx` (a dedicated section for
`report.verdicts.superseded`, plus a `superseded_note` caveat fallback when `reconciliation.note` is
absent), `frontend/src/lib/api/research.ts`, and the three `intake.json` locale files. **Without a
rebuild the newly-populated verdict class exists only in the JSON payload** — the operator still
cannot see a superseded verdict, which would leave SC2's forced-inline-caveat clause unmet on the
operator surface even though every backend fix had landed. Shipping 15.1.f without 15.1.g is a
half-deploy.

Reuse the § Phase 12 Step 12.3 / § Phase 15 Step 15.c flow verbatim — same `_API_BASE_URL` and
`VITE_FIREBASE_*` substitutions already captured (no URL re-wiring, no new env, no new secret):

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:${SHA}"

gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<id>.europe-west1.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" --region "$REGION" \
  --allow-unauthenticated --port 8080 --project="$GOOGLE_PROJECT"
```

Constraints carried from Phase 12 Step 12.3 — all still binding:

- **NEVER pass `VITE_SUPABASE_*`.** An in-image bundle guard FAILS the build if a Supabase signature
  leaks into the bundle.
- **Deploy with `--port 8080`** (the Nitro node-server binds `$PORT`).
- **`routeTree.gen.ts` does NOT need regenerating.** Plan 15.1-16 adds **no route** — it edits an
  existing component that already mounts on the existing `admin.pulse.intakes.$id` anchor via
  `ResearchRunProgress`. (Contrast § Phase 18, which DID add a route and did need the regeneration.)
- **Install is `npm ci`, never `npm install`.** `frontend/package-lock.json` **is** committed and
  `frontend/Dockerfile` runs `npm ci`. The "no lockfile" note in CLAUDE.md is stale — it refers to
  *bun* — and following it costs an `ERESOLVE` dead end.

Record the new frontend revision id and its digest, and the revision it supersedes (the pass
before this one was `nestor-frontend-00025-4w8`, image `20260724-231312`).

---

## Phase 15.2 — Research engine core (SERPAPI secret on BOTH tribunal images + dual REBUILD + 0013 migrate + nestor-api REBUILD + frontend REBUILD, then PARK)

This section is the enumerated source of truth for the Plan 15.2-18 operator live session that ships
the redesigned research **engine core** (plans 15.2-01 … 15.2-17) to production. Phase 15.2 touches
**four deployables** — `tribunal-worker`, `tribunal-api`, `nestor-api` and `nestor-frontend` — plus
the `tribunal-migrate` Job, and lands ONE migration (alembic **0013** in the **tribunal** schema, NOT
the intake `nestor` line).

**This is the FIRST phase since Phase 13 to add a secret.** `SERPAPI_API_KEY` (the D10
own-researcher key) is mounted on **both** Tribunal images from Secret Manager secret
`Nestor_SERP`. Read this before Step 15.2.e: **`--set-secrets` REPLACES the service's ENTIRE
secret set**, so the deploy scripts now compose the full mapping list in a variable rather than
inlining it. Anything omitted from that list is silently dropped from the next revision.

> **IaC-DRIFT reality (carry-over — read first).** As with every prior phase, Terraform state was
> never adopted and `terraform apply` is **FORBIDDEN** on this project — it would rotate the BUILT_IN
> Cloud SQL passwords and take down every service. Every step below is a manual gcloud reconciliation
> run in Cloud Shell; images are built via **Cloud Build** (never locally — the dev box has no
> Docker and no Python). This runbook, not `infra/*.tf`, is the source of truth for what is live.

> **The recurring deploy-gap (READ FIRST).** "Nothing is real until it is deployed, and a config-only
> env flip ships a STALE image." Phase 15.2 is the largest code delta of any phase so far — the whole
> engine core lives inside the two Tribunal images. **A `gcloud run services update --update-env-vars`
> that only adds `SERPAPI_API_KEY` to the CURRENT revisions ships none of it.** Worse, it would
> produce a service that looks freshly configured while running an image whose `_run_staged` raises
> `UnboundLocalError` on its first statement (the defect plan 15.2-17 fixed in commit `e01b7b2` —
> every run since 15.2-16's stage split would report `failed` with no park and no partial work).
> **Steps 15.2.c, 15.2.f and 15.2.g are mandatory image REBUILDs, not env flips.**

> **The park is not a failure.** This phase deploys NOW and then waits at UAT. The Anthropic monthly
> cap is tripped until **2026-08-01**; no step in this section triggers a live LLM run. Step 15.2.i
> is the park, and V-01/V-02/V-03 run in a fresh session after the reset.

```bash
# Shared exports for this session (set once in Cloud Shell — same as § Phase 13/14/15/15.1/16/17/18).
export GOOGLE_PROJECT="project-cb01b861-cb4a-438d-b9a"           # acct tools@dotto.be / tools@epicimpact.be
export REGION="europe-west1"
export INSTANCE_NAME="nestor-pg"
export INTAKE_SA="nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
export TRIBUNAL_SA="tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com"
```

**What changes this phase:**

| Deployable | Action | Carries |
|---|---|---|
| `tribunal-worker` | **REBUILD** + redeploy at `$SHA` | the whole engine core (plans 01-08, 10-17): reliability/retry/breaker, stage feed, workshop, four-stream dispatch, own-researcher + SerpApi client, per-provider fact lists, cross-provider merge, gates, grouped verification, D-08 report sections |
| `tribunal-api` | **REBUILD** + redeploy at the SAME `$SHA` | plan 09's status predicate + the stage feed read surface |
| `tribunal-migrate` (Job) | **REPIN to the `$SHA` api image**, then execute | alembic **0013** (`claim.certainty`, `claim.found_by`, `claim_source.provider_quality`, table `research_gap`, `ck_run_status` += `completed_degraded`/`parked`) |
| `nestor-api` | **REBUILD** + redeploy | plan 09's D-12 status vocabulary (`run_status.py`, `run_task.py`), plan 16's Resume route + parked mail |
| `nestor-frontend` | **REBUILD** + redeploy | plan 09's `RESEARCH_TERMINAL` set, `lib/api/research.ts`, the three `intake.json` locale files |
| Secret Manager | **`Nestor_SERP` already exists and is seeded** — grant the resource-scoped accessor only (it had none) | the D10 own-researcher key |

**NOT touched this phase:** no intake `nestor` migration and **no `nestor-migrate` Job run** (F3 —
`nestor.research_runs.status` carries no CHECK constraint, so the new status literals need no DDL);
no new env or secret on `nestor-api`; no change to the Phase-14 lockdown (`tribunal-run` SA,
`--no-allow-unauthenticated`, invoker `nestor-run` only — preserved by the scripts, not re-granted).

### Step 15.2.a — Preflight, read-only (stale-base guard + the six gates + capture the live wiring)

**1. Stale-base guard.** Cloud Build ships **the tree you submit**. A stale worktree produces a
green-looking deploy of code that is not this phase — the failure mode that has bitten every
executor agent in 15.2. Assert positively, on disk, before building anything:

```bash
git status --porcelain          # must be EMPTY
git log --oneline -1            # record this SHA in the session notes

# One artifact per wave — every one of these must exist in the tree you are about to submit.
ls tribunal/nestor_pulse_sdk/alembic/versions/0013_*.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/reliability.py
ls tribunal/nestor_pulse_sdk/runs/stage_feed.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/facts.py
ls tribunal/nestor_pulse_sdk/citations/anchors.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/own_researcher.py
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/serpapi.py
ls tribunal/nestor_pulse_sdk/tests/test_engine_e2e_stubbed.py
ls tribunal/cloudbuild.test-engine.yaml
grep -q 'completed_degraded' frontend/src/components/intake/ResearchRunProgress.tsx && echo "FE ok"
```

**2. The six gates GREEN on THAT tree.** All six run in Cloud Build (no local Python or Docker):

```bash
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml   --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml    --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-critical.yaml --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test.yaml          --project="$GOOGLE_PROJECT"
# Intake side — source MUST be `.` (repo root), never `backend` (§ Phase 14.g / 15.d note).
gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
bash backend/scripts/ci_no_run_research.sh   # exit 0
```

> ⚠️ **A green gate can prove nothing.** `cloudbuild.test-*.yaml` builds its file list with
> `ls … 2>/dev/null || true`, so a submitted tree that predates a plan collects **fewer files** and
> still exits SUCCESS. **Read the `collecting:` block in the build log and reconcile the file count —
> never accept the exit status alone.** Reference counts from the 15.2-17 sweep on the final tree:
> engine gate **560 passed / 8 skipped** (22 collected paths), gates **179 passed / 2 deselected**,
> critical **34 passed**, full suite **1025 passed / 52 skipped**, repo-root intake gate
> **195 passed / 1 skipped / 155 deselected**.

**3. Capture the live wiring WITHOUT printing any value.** Secret *names* are configuration, not
secrets; secret *values* are never fetched anywhere in this section.

```bash
for SVC in tribunal-worker tribunal-api; do
  echo "--- $SVC ---"
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(spec.template.spec.containers[0].env)' \
    | tr ',' '\n' | grep -E 'ANTHROPIC_API_KEY|SERPAPI_API_KEY|DATABASE_URL|AUDIT_GCS_BUCKET'
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(status.latestReadyRevisionName,status.traffic)'
done

# The tribunal-api URL, captured WITHOUT a path (the OIDC audience is the path-less
# service_url — Pitfall 4). Do NOT re-set the seam env from this; it is a read.
export TRIBUNAL_URL="$(gcloud run services describe tribunal-api \
  --region="$REGION" --project="$GOOGLE_PROJECT" --format='value(status.url)')"
```

Record: the current revision names for all four services, the path-less tribunal-api URL, and **the
Anthropic secret name each service actually mounts**.

**Superseded 2026-07-27 — read this before trusting older wording.** The earlier instruction here
said the scripts "self-heal" the Anthropic secret from the live revision. That mechanism was proven
harmful and has been inverted. Sequence of events:

1. 2026-07-21 — both Tribunal services were switched BY HAND to `Nestor_Claude2` (the credit-bearing
   key) while the scripts still hardcoded `Nestor_Claude`.
2. 2026-07-25 — the phase-15.1 deploy ran those scripts, which adopted the live value. By then the
   live value had already reverted, so self-healing **re-inherited the very drift it was written to
   prevent**.
3. 2026-07-27 — verified live: `tribunal-api`, `tribunal-worker` AND `nestor-api` were all on
   `Nestor_Claude`.

Reading the live value can never correct a clobber — it only ratifies it. The committed default in
both deploy scripts is now `Nestor_Claude2` and it WINS; the live value is read solely to print a
divergence notice. **All three services are on `Nestor_Claude2` as of 2026-07-27** — `nestor-api` no
longer "stays on `Nestor_Claude`", because it makes Anthropic calls for the intake skills and must
draw on the same credit-bearing key. Verify rather than assume.

### Step 15.2.b — Grant the accessor on the EXISTING `Nestor_SERP` secret

**Superseded 2026-07-27 — do NOT create a new secret.** This step originally told you to create
`Nestor_SerpApi` and seed a value. That was written from a search for a secret literally named
`SERPAPI_API_KEY`, which found nothing. In fact **`Nestor_SERP` has existed since 2026-06-03** and
already holds a valid, active key. Creating a second secret would duplicate a live credential —
two things to rotate, two chances to miss one. Both deploy scripts therefore default
`TRIBUNAL_SERPAPI_SECRET=Nestor_SERP`. The env var the code reads is unchanged:
`SERPAPI_API_KEY` (`serpapi.py::api_key()`).

The only thing genuinely missing was the IAM grant — verified 2026-07-27, `Nestor_SERP` had
**no IAM bindings whatsoever** (`get-iam-policy` returned a bare `{"etag":"ACAB"}`), so
`tribunal-run@` could not read it and any revision binding it would have failed to start.

```bash
# 1. Resource-scoped secretAccessor to the TRIBUNAL runtime SA ONLY.
#    NEVER nestor-run, NEVER a project-wide binding (least privilege, Phase-14 lockdown).
gcloud secrets add-iam-policy-binding Nestor_SERP \
  --member="serviceAccount:${TRIBUNAL_SA}" \
  --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"

# 2. Verify with METADATA reads only — never `gcloud secrets versions access`.
gcloud secrets versions list Nestor_SERP --project="$GOOGLE_PROJECT" \
  --format='value(name,state)'                       # expect one ENABLED version
gcloud secrets get-iam-policy Nestor_SERP --project="$GOOGLE_PROJECT" --format=json
# expect EXACTLY one member: serviceAccount:tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com
```

**Step 15.2.b-bis — grant `nestor-run@` on `Nestor_Claude2`.** Required by the 2026-07-27 repoint
(Step 15.2.a): `Nestor_Claude2` was granted to `tribunal-run@` only, but `nestor-api` runs as
`nestor-run@` and is now on Claude2 too.

```bash
gcloud secrets add-iam-policy-binding Nestor_Claude2 \
  --member="serviceAccount:nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor" --project="$GOOGLE_PROJECT"
gcloud secrets get-iam-policy Nestor_Claude2 --project="$GOOGLE_PROJECT" --format=json
# expect BOTH tribunal-run@ and nestor-run@
```

**SerpApi plan/tier in force** — read live from `/account.json` on 2026-07-27, not chosen as a
purchase. The "blocking operator decision" this step used to demand was a fact to look up:

```
SerpApi tier in force: Starter Plan (starter_v4)   ($25/month · 1,000 searches/month · 200 searches/hour)
Confirmed by: probe of GET /account.json           Date: 2026-07-27
Unit price for D-16: $25 / 1000 = $0.025 per search
Observed headroom:   ~42 billable searches/run  =>  ~$1.05 SerpApi spend per run, ~4 runs/hour
```

> **Do not `curl` `/account.json` unfiltered.** The response echoes the API key back. Filter to the
> plan fields only (`plan_name`, `searches_per_month`, `plan_searches_left`, `account_rate_limit_per_hour`).

**No price is hardcoded anywhere in the code.** `serpapi.fetch_plan()` reads `plan_monthly_price` and
`searches_per_month` live from `GET https://serpapi.com/account.json` at run start (free, off-quota)
and records them alongside the run, so D-16's spend figure is an exact `Decimal` computed from the
plan actually in force (D-16 reproducibility). A free-tier run therefore reads a true
`$0.00000/search`, never a blank and never an estimate.

> **If this step is skipped or deferred, the deploy still succeeds.** Both deploy scripts probe for
> the secret's existence before binding it (Step 15.2.e). Absent secret ⇒
> `serpapi.unavailable_reason() == "serpapi_key_missing"` ⇒ breaker open at startup ⇒ a clean
> 3-stream `completed_degraded` run (D-12). It degrades; it never crashes. The cost is that V-02 #6
> cannot be proven on the V-01 run.

### Step 15.2.c — Build BOTH Tribunal images at ONE `$SHA` (BUILD ONLY — the deploy is Step 15.2.e)

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

gcloud builds submit tribunal --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"
```

> ⚠️ **ORDER IS LOAD-BEARING: build BOTH → migrate (15.2.d) → THEN deploy (15.2.e).** Migration 0013
> must land **before** the worker that writes `certainty` / `found_by` / `provider_quality` /
> `research_gap` starts running. If the code ships ahead of the column, every write fails into a
> swallowed `except`, the run completes, and the report renders with silently missing provenance and
> an empty "What we could not establish" — **it looks like success.** This is the same trap § Phase
> 15.1 Step 15.1.f documents for `superseded_note`. Second reason: the migrate Job applies the
> alembic revisions **baked into an image**, so the image carrying `0013` must exist first.

### Step 15.2.d — Repin `tribunal-migrate` to the `$SHA` api image, THEN execute (alembic 0013)

> ⚠️ **LESSON (image-pin, hit live 2026-07-22 on `nestor-migrate` and again 2026-07-25 on
> `tribunal-migrate`): the Job does NOT track the service image.** Deploying `tribunal-api` at `$SHA`
> leaves the Job pinned to its OLD image — executing it then is a **silent no-op** (alembic connects,
> finds itself "at head" on the stale revision set, exits 0, logs no `Running upgrade` line). **ALWAYS
> repin the Job to the just-built image FIRST.**

```bash
# 1. REPIN — before executing.
gcloud run jobs update tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}"

# 2. CONFIRM the repin took (cheap, and the whole step depends on it).
gcloud run jobs describe tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.template.spec.containers[0].image)'   # must echo :${SHA}

# 3. Execute.
gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

**4. CONFIRM the upgrade actually ran.** Read the execution log and require the literal line:

```
Running upgrade 0012 -> 0013
```

```bash
gcloud logging read \
  'resource.type="cloud_run_job" AND resource.labels.job_name="tribunal-migrate"
   AND labels."run.googleapis.com/execution_name"="<EXECUTION_ID>"' \
  --project="$GOOGLE_PROJECT" --limit=50 --format="value(textPayload)"
```

**`Container called exit(0)` is NOT proof.** Absence of the `Running upgrade` line means the Job ran
on a stale image — repin and re-execute. Do not proceed to the deploy without it.

**5. Confirm the schema, read-only.** The tribunal line's version table is
**`tribunal.tribunal_alembic_version`**, NOT `alembic_version` (set via `version_table` /
`version_table_schema` in `alembic/env.py`) — querying `tribunal.alembic_version` raises
`UndefinedTableError` and is a false alarm, not a failed migration. Expect:

```
col claim.certainty                 nullable=YES
col claim.found_by                  type=text[]  nullable=YES
col claim_source.provider_quality   nullable=YES
table tribunal.research_gap         rls enabled=true forced=true
policy research_gap_tenant_isolation
index idx_research_gap_tenant_run
ck_run_status accepts 'completed_degraded' and 'parked'
tribunal_head = 0013
```

The RLS assertions on `research_gap` are load-bearing: it is a **new tenant-scoped table**, so
ENABLE + FORCE ROW LEVEL SECURITY and its tenant-isolation policy must be present in `0013` itself —
unlike `0012`, they are not inherited. A table without them is a cross-tenant leak. This is the
**TRIBUNAL** line — NOT the intake `nestor` line, whose head stays at `0012` (Phase 17).

### Step 15.2.e — Deploy `tribunal-worker`, then `tribunal-api`, at `IMAGE_TAG=$SHA`

Always the retargeted scripts, **never a hand-rolled `gcloud run deploy`**: they pin `IMAGE_TAG` and
PRESERVE the Phase-14 lockdown (`tribunal-run` SA, `--no-allow-unauthenticated`, invoker `nestor-run`
only — not re-granted here). As of Phase 15.2 they also compose the full `--set-secrets` list, probe
`Nestor_SERP` for existence before binding it, and **pin the Anthropic secret name to the committed
default `Nestor_Claude2`** (operator decision 2026-07-27 — see Step 15.2.a). The live value is read
only to print a divergence notice; it is deliberately NOT adopted, because adopting it is what
re-inherited the 2026-07-21 drift on 2026-07-25. Override for a one-off with
`TRIBUNAL_ANTHROPIC_SECRET=<name>` in front of the script.

```bash
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-api.sh
```

Each script echoes the secret **names** it will mount (`==> ANTHROPIC_API_KEY will be mounted from
secret: …`, `==> own-researcher key will be mounted from secret: …`). Confirm the binding landed:

```bash
for SVC in tribunal-worker tribunal-api; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(spec.template.spec.containers[0].env)' \
    | tr ',' '\n' | grep -E 'SERPAPI_API_KEY|ANTHROPIC_API_KEY'
done
# expect the secret REFERENCE on both services, never a value.

# Digest-pin proof: each new revision must resolve to an @sha256: digest, never :latest.
gcloud run revisions describe <REVISION> --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.containers[0].image)'
```

> **If the SERPAPI grep comes back empty the deploy is NOT broken.** The own-researcher will run as a
> clean 3-stream `completed_degraded` run (D-12). But V-01 then cannot prove SC2's D10 clause and
> V-02 #6 records a miss — **fix the binding (Step 15.2.b) before spending the V-01 run.**

> **Anthropic secret sanity check.** Confirm the mounted `ANTHROPIC_API_KEY` secret name matches what
> Step 15.2.a recorded as live. If a script re-run ever repoints it to a low-credit secret, the ~$45
> V-01 run walls mid-flight. Override explicitly with `TRIBUNAL_ANTHROPIC_SECRET=<name>` if needed.

### Step 15.2.f — REBUILD + deploy `nestor-api`

Ordered **after** the Tribunal services, because the Resume route calls the seam.

```bash
export IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:${SHA}"

gcloud builds submit backend --tag "$IMAGE" --project="$GOOGLE_PROJECT"
gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "$IMAGE"
```

What the rebuild carries: the **D-12 status vocabulary** in `app/research/run_status.py` +
`app/research/run_task.py` (the `completed_degraded` / `parked` literals the frontend polls), the
`POST /{intake_id}/research/resume` route in `app/api/research_routes.py`, and
`render_research_parked` in `app/mail/`.

- **NO intake-line migration and NO `nestor-migrate` Job run this phase** — F3:
  `nestor.research_runs.status` has no CHECK constraint, so the new status literals need no DDL. The
  intake `nestor` alembic head stays at **`0012`** (Phase 17).
- **NO new env and NO new secret on `nestor-api`.** The parked mail reuses the Phase-10 stack
  (`RESEND_API_KEY` / `APP_BASE_URL` / `NESTOR_ADMIN_EMAIL`). **`APP_BASE_URL` must be present or the
  mail refuse-sends** — confirm read-only, do not re-set:

```bash
gcloud run services describe nestor-api --region="$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.containers[0].env)' \
  | tr ',' '\n' | grep -E 'APP_BASE_URL|NESTOR_ADMIN_EMAIL|RESEND_API_KEY|TRIBUNAL_SERVICE_URL'
```

- **NEVER bind `SERPAPI_API_KEY` to `nestor-api`.** `backend/scripts/ci_no_run_research.sh` scans
  `backend/app/**` and `frontend/src`, and INTAKE-05 must stay green.

### Step 15.2.g — REBUILD + deploy the frontend

```bash
export FE_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:${SHA}"

gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${FE_IMAGE}",_API_BASE_URL="https://nestor-api-<id>.europe-west1.run.app",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"

gcloud run deploy nestor-frontend \
  --image "$FE_IMAGE" --region "$REGION" \
  --allow-unauthenticated --port 8080 --project="$GOOGLE_PROJECT"
```

Constraints, each still binding:

- **Install is `npm ci`, never `npm install`.** `frontend/package-lock.json` **is** committed and
  `frontend/Dockerfile` runs `npm ci`. The "no lockfile" note in CLAUDE.md is **stale** — it refers
  to *bun* — and following it costs an `ERESOLVE` dead end.
- **NEVER pass `VITE_SUPABASE_*`.** An in-image bundle guard FAILS the build if a Supabase signature
  leaks into the bundle.
- **Deploy with `--port 8080`** (the Nitro node-server binds `$PORT`).
- **NO `routeTree.gen.ts` regeneration.** Plan 15.2-09 adds **no route** — it edits
  `ResearchRunProgress.tsx`, `lib/api/research.ts` and the three `intake.json` locale files on the
  existing `admin.pulse.intakes.$id` anchor. (Contrast § Phase 18, which DID add a route.)

**Why a rebuild is mandatory for what looks like a one-line change:** the terminal-status set
(`RESEARCH_TERMINAL`) is **compiled into the bundle**. Without a rebuild, a `completed_degraded` run
spins forever in the operator's browser while every backend surface is correct — the Phase-18
stale-SPA lesson. Shipping 15.2.f without 15.2.g is a half-deploy.

### Step 15.2.h — Verify without printing secrets

1. **The six gates re-run against the deployed tree** (the Step 15.2.a block, verbatim) — reading the
   `collecting:` block, not the exit status.
2. **`verify_chain` GREEN on the deployed audit data.** Gate 3
   (`tribunal/cloudbuild.test-critical.yaml`). **A RED chain is a STOP** — do not sign off, and
   investigate whether a non-additive change slipped into `_payload_for_row`. Legal gate: EU AI Act
   Art. 12, audit-trail deadline **2026-08-02**.
3. **The secret-binding confirm from Step 15.2.e** — secret *names* only, never values.
4. **`/readyz` 200 on `tribunal-api`**, against the path-less URL with an identity token:

```bash
curl -s -o /dev/null -w '%{http_code}\n' \
  -H "Authorization: Bearer $(gcloud auth print-identity-token)" "$TRIBUNAL_URL/readyz"
```

5. **`bash backend/scripts/ci_no_run_research.sh` exits 0.** The SerpApi client lives inside
   `tribunal/`, which the guard deliberately does not scan. Adding **any** SerpApi reference to
   `backend/app/**` or `frontend/src` breaks INTAKE-05. (The guard was narrowed with an
   import-anchored allowlist and verified non-vacuous in 15.2-17 — it still forbids
   `SERPAPI_API_KEY`, `serpapi.com`, engine-internal imports and run-research invocation.)

### Step 15.2.i — PARK, then V-01 / V-02 / V-03

**The wall: the Anthropic monthly cap resets 2026-08-01.** No live LLM run may be triggered before
then. Deploying is complete at Step 15.2.h; the phase now waits.

The checklist lives at
`.planning/phases/15.2-research-engine-redesign-engine-core-inserted-2026-07-24/15.2-UAT.md`.

Three prerequisites before V-01 can run:

1. **A fresh test intake** reproducing the baseline brief domain (LUKOIL BeNeLux — dynamic pricing,
   coffee, Germany-entry 2027) in a clean space, so the one run that has to prove the phase is not
   entangled with the smoke-tenant cleanup backlog.
2. **The SerpApi tier live** — SATISFIED 2026-07-27: `Nestor_SERP` is seeded and active on Starter
   ($25/mo · 1,000/month · 200/hour). Only the `tribunal-run@` accessor grant was outstanding
   (Step 15.2.b). The fallback — an explicit decision to accept a 3-stream degraded V-01 — is no
   longer needed.
3. **The operator present** for sign-off — V-02 #16 is a human read of the new report beside
   `docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md`.

Then, in order: **V-01** (ONE live run, recorded into `docs/tribunal-run-reports/V-01-COMPARISON.md`
beside the 4cbb5311 baseline — no A/B double-run), **V-02** (the 16-item checklist with named
evidence per item, ending in a dated operator sign-off), and **V-03** (a SEPARATE commit after
sign-off removing only unreferenced old-path code — `claim_distiller` (D-15),
`detect_explicit_questions` and `extract_and_persist_citations` all survive with green tests).

Two items from earlier phases are deliberately batched into the same August operator session
(STATE.md, operator decision 2026-07-24): the deferred **Phase-15 populated-surface browser UAT**
(SC1-SC4) and the **Phase-15.1 gate/verdict surfaces** — neither could be walked on the recorded
fixture, because run 4cbb5311 exists only as a pytest fixture and was never seeded into the live DB.

## Phase 15.2 gap closure — Step 15.2.j: the D-E worker-liveness revert (alembic 0014)

> ⛔ **DO NOT UNPAUSE `tribunal-worker` BEFORE THIS WHOLE STEP IS DONE.** The service is
> deliberately at `--min-instances=0` and carries two TEMPORARY bindings applied by hand on
> 2026-07-27: `NESTOR_WORKER_STALE_MINUTES=525600` (one year) and
> `NESTOR_RUN_ABORTED_MARKER=d6bb3aae-20260727`. Unpausing at `--min-instances=1` before steps
> 1–4 below re-arms exactly the defect this closes: run `d6bb3aae` is **still `running` in the
> DB** and would be re-claimed and re-executed at full cost, unattended.

**What D-E was.** `worker.py`'s `CLAIM_SQL` measured staleness by `started_at`, which is stamped
once at claim time and never moves. A live process holding a ~35-minute deep-research long-poll was
therefore indistinguishable from a process that died 35 minutes ago, and the designed response to a
dead process is to re-run. On 2026-07-27 terminating a stuck worker started a fresh one that was
seconds from re-executing the same run. It was blocked only by setting the stale threshold to one
year — which is worse in the other direction, because with it set a genuinely crashed worker is
**never** recovered. Plan 15.2-20 replaces the clock with a real heartbeat (`run.heartbeat_at`) and
bounds recovery (`run.reclaim_count` + a reap-to-failed), which is what makes `60` safe again.

**The ordering is load-bearing. Run these five in order.**

**1. Migrate first: `tribunal-migrate` REPINNED to the `$SHA` `tribunal-api` image, then executed.**
Same idiom as Step 15.2.d — repin *before* executing or the Job is a silent no-op on a stale image.
Prove it by the literal log line, never by an exit code:

```
Running upgrade 0013 -> 0014
```

`Container called exit(0)` is **NOT** proof. Then confirm the schema read-only — expect:

```
col run.heartbeat_at    nullable=YES
col run.reclaim_count   nullable=NO   default=0
tribunal_head = 0014
```

This is the **TRIBUNAL** line (`tribunal.tribunal_alembic_version`), not the intake `nestor` line.
`0014` issues no policy, no index and no privilege grant: `run` already carries ENABLE + FORCE ROW
LEVEL SECURITY with `run_tenant_isolation` (0002/0010) and `run_worker_all` (0008), and a row-level
policy is a TABLE-level object, so a new column is covered by construction.

**2. Then deploy the new `tribunal-worker` image** (rebuild via `cloudbuild.worker.yaml`, then the
retargeted script — never a hand-rolled `gcloud run deploy`):

```bash
IMAGE_TAG="$SHA" tribunal/infrastructure/cloud-run/deploy-worker.sh
```

*Why this order and not the reverse.* Between (1) and (2) the OLD image runs against the NEW schema,
which is safe: both columns are purely additive and the old `CLAIM_SQL` never reads them. Deploying
the image **before** the migration is **not** safe — the new `CLAIM_SQL` and `REAP_SQL` reference
`heartbeat_at` and `reclaim_count`, so every claim would raise `UndefinedColumnError` and the worker
would poll-crash in a loop, claiming nothing.

**3. Revert the stale threshold to a real value.**

```bash
gcloud run services update tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --update-env-vars NESTOR_WORKER_STALE_MINUTES=60
```

*Why 60 is now safe where it was not before.* The number no longer means "how long a run may take" —
it means "how long the worker may be **silent**". The executing worker writes `run.heartbeat_at`
every `NESTOR_WORKER_HEARTBEAT_S` (default 30s) for as long as it is alive, so 60 minutes of
heartbeat silence is 120 consecutive missed heartbeats: the process is gone, not slow. A 35-minute
long-poll no longer looks stale at any age. Two related tunables exist with production-safe defaults
and need no binding: `NESTOR_WORKER_HEARTBEAT_S` (30) and `NESTOR_WORKER_MAX_RECLAIMS` (2, the number
of crash recoveries a single run gets before it is failed with a worded message rather than started
again).

**4. Remove the abort marker.**

```bash
gcloud run services update tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --remove-env-vars NESTOR_RUN_ABORTED_MARKER
```

`NESTOR_RUN_ABORTED_MARKER` is read by **no code in this repository** — `grep` returns zero hits
outside the findings document. It was a human annotation left on the revision to record why the
threshold had been raised. Removing it therefore changes no behaviour; it only stops the service
carrying a note that is no longer true.

**5. Only then unpause.**

```bash
gcloud run services update tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --min-instances=1
```

Confirm before and after with a read: the env should show `NESTOR_WORKER_STALE_MINUTES=60` and no
`NESTOR_RUN_ABORTED_MARKER`.

```bash
gcloud run services describe tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.containers[0].env)' | tr ',' '\n' | grep -E 'NESTOR_WORKER|ABORTED'
```

> **Flag ordering, non-negotiable (the Phase-12 lesson).** Steps 3–5 use `--update-env-vars` and
> `--remove-env-vars`. Never hand-type the whole-env-replacing `--set-env-vars` form against a live
> service: it DROPS every binding you did not restate, and this service carries
> `NESTOR_ENV`, `NESTOR_WORKER_POLL_INTERVAL` and `NESTOR_TRIBUNAL_UNCAPPED` besides.

**The shortcut, and exactly how far it goes.** `tribunal/infrastructure/cloud-run/deploy-worker.sh`
deploys with a whole-env `--set-env-vars` list whose committed content is
`NESTOR_ENV=prod,NESTOR_WORKER_POLL_INTERVAL=2.0,NESTOR_WORKER_STALE_MINUTES=60,NESTOR_TRIBUNAL_UNCAPPED=1`.
Because that flag **replaces** the entire plain env, a full redeploy through the committed script
performs steps (3) and (4) **by itself**: it restores the threshold to `60` and drops the
out-of-band `NESTOR_RUN_ABORTED_MARKER`, because neither temporary value is in the committed list.
So step 2 via the script usually leaves nothing to do in 3 and 4 — **verify with the describe in
step 5 rather than assuming**, and run 3/4 explicitly if the read disagrees.

This is true **only** for a redeploy through that script. A bare
`gcloud run services update tribunal-worker --image …` leaves both temporary bindings exactly where
they are — which is precisely how they survived. Outside the script, use `--update-env-vars` /
`--remove-env-vars`.

Also still outstanding at this point, and **not** solved by this step: run `d6bb3aae` is stuck in
`running` and blocks retry on its intake. Plan 15.2-25 builds the operator cancel path and 15.2-26
uses it. Do not resolve it by unpausing the worker.

> **RECONCILIATION (plan 15.2-26, 2026-07-27) — read this before executing 15.2.j on its own.**
> Step 15.2.j was written by plan 15.2-20 as the standalone D-E revert, when D-E was the only gap
> plan that had landed. **The gap phase is now SIX plans**, and its whole deploy is § Step 15.2.k
> below, which WRAPS this step. If you are deploying the gap phase, execute **15.2.k** and treat
> 15.2.j as the detail reference it cites:
>
> - 15.2.j steps **1 and 2** (migrate 0014, then the worker image) are 15.2.k steps **3 and 4** —
>   but note that **15.2.k step 4 is executed LATE, after step 6**, per the ORDERING CORRECTION at
>   the head of § 15.2.k. The migrate-before-image dependency still holds; what changed is that the
>   worker image is the LAST deployable, not the first.
> - 15.2.j steps **3 and 4** (the threshold revert and the marker removal) are performed **by the
>   redeploy in 15.2.k step 4**, exactly as the shortcut paragraph below explains — verify, do not
>   assume.
> - 15.2.j step **5 (the unpause) MOVES LATER**: in the gap phase it is 15.2.k step **7**, after the
>   other three deployables AND after run `d6bb3aae` has been cancelled. **Unpausing at 15.2.j step 5
>   during a gap-phase deploy would re-execute `d6bb3aae` at full cost** — see 15.2.k step 6 for why
>   the D-E fix does NOT protect that particular row.
>
> Nothing in 15.2.j is wrong; it is a subset with a different tail. Do not run both tails.

## Phase 15.2 gap closure — Step 15.2.k: the GAP-PHASE deploy (plans 15.2-20 … 15.2-26 **AND 15.3-01 … 15.3-09**)

> ⛔⛔ **ORDERING CORRECTION — 2026-07-28. READ BEFORE EXECUTING ANY STEP BELOW.**
>
> **The numbered order below is WRONG and following it as written CAUSED AN INCIDENT.** It deploys
> `tribunal-worker` at step **4** and only resolves the stuck run at step **6**. On 2026-07-28 the
> worker deployed at 08:22:57Z, claimed run `d6bb3aae` within seconds and re-executed **~15 minutes
> of paid pipeline unattended**; the operator deleted the service to stop it.
>
> **Execute in THIS order.** The step numbers are kept as-is (three other places in this file cite
> them), so the correction is the sequence, not a renumbering:
>
> **0 → 1 → 2 → 3 → 5 → 6 → then 4 → then 7 → 8 → 9 → 10**
>
> That is: **everything except the worker**, then resolve the run, then **the worker LAST**, then
> the unpause. Step 4 is the only move. The reason is in step 4's own warning: a deploy *boots* the
> container, and this worker claims on boot.
>
> **`--min-instances=0` DOES NOT MAKE THIS SAFE.** See step 4. The only protection is an empty
> queue — which is what step 2 is for, and why step 2 must be believed rather than assumed.

This is the **single ordered procedure** for shipping the six gap plans that close the twelve defects
found on run `d6bb3aae`. It supersedes the tail of Step 15.2.j (see the reconciliation note above)
and is the operator session plan 15.2-26 hands over.

> **THIS STEP NOW COVERS TWO PHASES: plans 15.2-20 … 15.2-26 AND plans 15.3-01 … 15.3-09.**
> Phase 15.3 has **no deploy of its own** — it rides this one, by operator decision D-03. That
> decision is the reason no separate numbered step was created for that phase anywhere in this
> file: two procedures for one deploy is two sources of truth, and the one that gets read is
> whichever the reader found first. Everything 15.3 adds is folded into the steps below, in place.
>
> **The accepted risk that comes with D-03, recorded because it lands during V-01:** the next live
> run exercises a changed engine AND a changed frontend at once, so a surprising result is harder
> to attribute to a cause. The mitigation is the **combined deploy record** at the end of this
> step — fill it in, or the attribution is gone.

**What is being shipped, and by which plan:**

| Plan | Closes | Lands in |
|---|---|---|
| 15.2-20 | D-E (the money defect: a stuck run re-billing every 60 min) | migration **0014** + `tribunal-worker` |
| 15.2-21 | D-G / D-H (the workshop deepened the context pack, not the questions) | `tribunal-worker` + `nestor-api` |
| 15.2-22 | D-A / D-B (two dead research streams) | `tribunal-worker` |
| 15.2-23 | D-I (personal identifiers dispatched to third-party providers) + part of D-M | `tribunal-worker` |
| 15.2-24 | D-F (the engine logged only failures) + D-L (the elapsed clock) | `tribunal-worker` + `tribunal-api` + `nestor-api` |
| 15.2-25 | D-D (there was no operator cancel path) | `nestor-api` + `nestor-frontend` |

**And phase 15.3 — observability only. It changes nothing about what the pipeline decides,
dispatches or produces:**

| Plan | Adds | Lands in |
|---|---|---|
| 15.3-01…03 | the append-only `run_event` feed + its emit sites | migration **0015** + `tribunal-worker` |
| 15.3-02 | the bounded, cursor-ordered events read | `tribunal-api` |
| 15.3-06 | the feed cursor mirrored onto the intake run row | migration **0013** (intake line) + `nestor-api` |
| 15.3-07 | the events proxy and the run→intake locate verb | `nestor-api` |
| 15.3-08/09 | the dedicated run page: feed, eight-status card, the four affordances | `nestor-frontend` |

Every step below names its reason. **An ordering constraint without its reason gets reordered by the
next person in a hurry** — that is how the image once shipped ahead of its migration.

---

**0. Preflight — the stale-base guard, positively, on disk.**

Cloud Build ships **the tree you submit**. Assert the six gap plans are actually present before
building anything:

```bash
git status --porcelain          # must be EMPTY
git log --oneline -1            # record this SHA in the session notes

ls tribunal/nestor_pulse_sdk/alembic/versions/0014_run_liveness_and_reclaim.py   # 15.2-20
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/brief_input.py                    # 15.2-21
ls tribunal/nestor_pulse_sdk/tests/test_web_fetch_replay.py                      # 15.2-22
ls tribunal/nestor_pulse_sdk/pipeline/tribunal/pii.py                            # 15.2-23
ls tribunal/nestor_pulse_sdk/tests/test_stage_logging.py                         # 15.2-24
grep -q "def cancel_run" backend/app/research/tribunal_client.py && echo "cancel seam ok"   # 15.2-25
grep -q "research/cancel" frontend/src/lib/api/research.ts && echo "cancel FE ok"           # 15.2-25

# ── And the phase-15.3 artifacts riding the same tree. ──────────────────────────────────
ls tribunal/nestor_pulse_sdk/alembic/versions/0015_run_events.py    # 15.3-01 (engine migration)
ls backend/app/db/alembic/versions/0013_research_run_event_seq.py   # 15.3-06 (intake migration)
ls frontend/src/routes/admin.pulse.runs.\$runId.tsx                 # 15.3-08 (the run page)
ls frontend/src/components/research/RunStatusCard.tsx               # 15.3-09 (the eight statuses)
ls frontend/src/components/research/RunActions.tsx                  # 15.3-09 (the four affordances)
grep -q "runs/\$runId" frontend/src/routeTree.gen.ts && echo "run route registered"  # 15.3-08
```

Then the gates, on THAT tree. The engine gate now **asserts its own file count** (plan 15.2-26): a
name whose file is absent or mistyped fails the build naming the path, instead of collecting one
file fewer and going green.

```bash
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml   --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml    --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-critical.yaml --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.seam-gate.yaml     --project="$GOOGLE_PROJECT"
gcloud builds submit . --config=cloudbuild.test.yaml --project="$GOOGLE_PROJECT"
```

Expect on the engine gate: **`collecting: 30 of 30 expected files`**, then the pass/skip summary.
**The count is not a memory — read it out of `EXPECTED_FILES` in
`tribunal/cloudbuild.test-engine.yaml` and compare.** It moved from 27 to 30 because plans 15.3-01,
15.3-02 and 15.3-03 each registered one test file, and a runbook quoting a stale count teaches the
operator to accept a gate that ran less than it claims. **The DB-bound files skip** (`test_
checkpoint_resume.py`, `test_stale_reclaim.py`) and each prints a message saying in words that a
skip there is not a pass — contract-compliant for a gate that provisions no Postgres, and why
`cloudbuild.test-critical.yaml` is in the list above.

`cloudbuild.test.yaml` (the **backend** gate, `pytest tests -m integration`) is where phase 15.3's
intake-side work is proven: the cursor mirror, the events proxy and the locate verb. Note what it
does **not** print — see the intake migration in step 3b.

**The frontend gates are local, and 15.3 lands real code behind all three.** Run them on the same
tree before the image build in step 1:

```bash
cd frontend && npm ci && node scripts/i18n-audit.mjs && npx tsc --noEmit && npm run build && cd ..
```

`npm ci`, never `npm install`. The i18n audit is a HARD gate on checks A/B/C: every user-visible
string must exist in **en, nl and fr**. Its CHECK D advisories are pre-existing and are not a
failure — read the `RESULT:` line, not the warning count.

---

**1. Build all four images at ONE shared `$SHA`. BUILD ONLY — no deploy until step 4.**

One SHA so a mixed-revision state is impossible to reach by accident, and so the revision list in
step 8 can be read as one fact rather than four.

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

gcloud builds submit tribunal --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"
gcloud builds submit backend --tag "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:${SHA}" \
  --project="$GOOGLE_PROJECT"
gcloud builds submit frontend --config=frontend/cloudbuild.yaml \
  --substitutions=_IMAGE="${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:${SHA}",_API_BASE_URL="<the nestor-api URL — same value as the 2026-07-27 deploy>",_FB_API_KEY="<public firebase web apiKey>",_FB_AUTH_DOMAIN="<project>.firebaseapp.com",_FB_PROJECT_ID="${GOOGLE_PROJECT}" \
  --project="$GOOGLE_PROJECT"
```

*Why all four rebuild and none is an env flip.* The worker carries five plans of engine code; the
api carries 15.2-24's two new `RunMetrics` fields; `nestor-api` carries the cancel route, the
`[DECISION]` block and the `started_at` mirror; the frontend carries the Stop button, which is
**compiled into the bundle** (the Phase-18 stale-SPA lesson — a backend-only deploy leaves the
operator with no button and no error).

*And why each of the four ALSO carries phase 15.3 — so that a reader deciding to skip one image can
see exactly what they would be skipping:*

| Image | What 15.3 puts in it | Skipping it costs |
|---|---|---|
| `tribunal-worker` | the `run_event` emit sites in the pipeline and the research division (15.3-03) | the feed stays empty forever — the page renders, with nothing in it |
| `tribunal-api` | the bounded, cursor-ordered events read endpoint (15.3-02) | the page's backfill 404s and every run reads as having no history |
| `nestor-api` | the events proxy, the run→intake locate verb and the cursor mirror (15.3-06/07) | the page cannot even resolve which intake a run belongs to — it is a dead URL |
| `nestor-frontend` | the run page itself, the eight-status card and the four affordances (15.3-08/09) | the route does not exist in the bundle; the link from the intake card 404s |

`npm ci`, never `npm install` — `frontend/package-lock.json` IS committed. Never pass
`VITE_SUPABASE_*` (the in-image bundle guard fails the build).

> ⚠️ **`routeTree.gen.ts` — READ THIS, IT CHANGED.** The pre-15.3 note here said no route was
> added, because 15.2-25 mounted on the existing `admin.pulse.intakes.$id` anchor. **That is no
> longer true.** Plan 15.3-08 adds a genuinely new flat route, `/admin/pulse/runs/$runId`, and its
> regenerated `frontend/src/routeTree.gen.ts` **is already committed**. Nothing needs regenerating
> at deploy time — but do confirm the guard in step 0 printed `run route registered`. A frontend
> image built from a tree whose generated route table predates 15.3-08 ships a page that cannot be
> navigated to, and the symptom is a 404 that looks like a backend fault.

---

**2. Confirm the queue is EMPTY before touching the worker.**

This is the step that makes **step 4's deploy** and step 7's unpause safe, and it is the cheapest
step in the section. It is not a formality: per step 4, an empty queue is the *only* thing that
makes deploying the worker safe, because the deploy boots it and the loop claims before it sleeps.
Read the run table directly (the Phase-14 lockdown blocks the seam HTTP verb, not a DB read):

```sql
SELECT id, status, started_at, heartbeat_at, reclaim_count
  FROM tribunal.run
 WHERE status IN ('queued', 'running')
 ORDER BY created_at;
```

**Expect EXACTLY ONE row: `d6bb3aae-33e7-49fd-aa35-57dc529e05b3`, status `running`,
`heartbeat_at` NULL** (it predates 0014), `reclaim_count` 0.

- A second `running` row means another process is or was executing — **STOP** and identify it
  before deploying anything.
- Any `queued` row would be claimed the instant step 4 deploys the worker — not step 7. **STOP**:
  decide deliberately whether that run should execute on the new code, and record the decision.

> **HOW to run that query without opening the database — the recipe that works (2026-07-28).**
>
> The two obvious paths are both closed. `nestor-pg`'s authorized-networks list is **empty**, so
> there is no public-IP route without patching production networking; and `tribunal-api` rejects a
> plain Cloud Run invoker token with `{"error":"invalid internal caller token"}` (the Phase-14
> lockdown), so the seam cannot answer it either.
>
> Run it from **inside** Google's network instead, as `nestor-run@` — which already holds
> `secretAccessor` on `DATABASE_URL_WORKER`, so **no IAM change and no allowlist change is needed**:
>
> ```bash
> gcloud builds submit --no-source --config=<queue-check>.yaml \
>   --project="$GOOGLE_PROJECT" \
>   --service-account=projects/$GOOGLE_PROJECT/serviceAccounts/nestor-run@$GOOGLE_PROJECT.iam.gserviceaccount.com
> ```
>
> The build step downloads `cloud-sql-proxy`, points it at
> `$GOOGLE_PROJECT:$REGION:nestor-pg`, and runs `psql` against `127.0.0.1:5432`. `--no-source` is
> required: `nestor-run@` cannot read the Cloud Build source bucket, and a sourced build dies with
> `storage.objects.get denied` before the step ever runs.
>
> **Two traps that will silently give you a wrong answer:**
>
> 1. **`nestor-run@` lacks `logging.logWriter`, so the build's stdout is LOST** — the build goes
>    SUCCESS and `gcloud builds log` returns an empty `REMOTE BUILD OUTPUT`. Do not read a green
>    build as an empty queue. **Carry the result in the EXIT STATUS**, and fold the anti-vacuity
>    checks into the success condition, e.g. `exit 91` if `SELECT count(*) FROM tribunal.run` is 0
>    (RLS hiding everything), `exit 92` if the known-cancelled control row is not visible with its
>    expected status, `exit 93` if anything is claimable. Cloud Build reports the exit code in the
>    failure message, so each cause is distinguishable. **Then prove the gate can fail**: re-run once
>    with the claimable assertion inverted and confirm it exits 93.
> 2. **Connect as `worker_user`, never `app_user`.** `worker_user` matches the `worker_all` RLS
>    policy and therefore sees exactly what `CLAIM_SQL` sees. `app_user` is tenant-scoped: without a
>    bound `app.tenant_id` it returns **zero rows**, which is indistinguishable from an empty queue
>    and is the most expensive false negative in this document. The password is inside
>    `DATABASE_URL_WORKER` — parse it, never echo it.

---

**3. Migrate FIRST — BOTH LINES. Each is its own sequence with its own version table, and each
needs its own proof.**

There are **two independent alembic lines** in this project and they do not know about each other:
the **TRIBUNAL** line in `tribunal.tribunal_alembic_version`, and the **INTAKE (`nestor`)** line in
`public.alembic_version`. This deploy advances BOTH — the first time that has been true — so step 3
has two halves. Neither half proves the other, and a head read on the wrong table proves nothing at
all.

**Both migrations go before their respective service images**, for one reason stated twice: the
engine writes `run_event` from the pipeline, and the intake API reads `research_runs.event_seq`. A
service that ships ahead of its own migration fails on a missing relation or a missing column, in a
loop, on every request.

**3a. TRIBUNAL: repin `tribunal-migrate` to the `$SHA` api image, then execute (alembic 0014 AND
0015).**

Full detail, including the schema read-back, is Step 15.2.j item 1 — do not restate it differently
here.

```bash
gcloud run jobs update tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}"
gcloud run jobs describe tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.template.spec.containers[0].image)'   # must echo :${SHA}
gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

**Prove it by the literal log lines. `Container called exit(0)` is NOT proof** — this is the
recorded phase lesson, and an unpinned Job is a silent no-op that exits 0 having applied nothing.
There are now **TWO** lines to find, because this run advances the tribunal line by two revisions:

```
Running upgrade 0013 -> 0014
Running upgrade 0014 -> 0015
```

Only the first is 15.2's. **`Running upgrade 0014 -> 0015`** is phase 15.3's `run_event` table — the
append-only feed everything else in 15.3 reads from. Seeing the first line and not the second means
the Job ran on an image built before 15.3-01: repin and re-execute.

*Why the migration precedes the worker image.* The new `CLAIM_SQL` and `REAP_SQL` reference
`heartbeat_at` and `reclaim_count`. A worker deployed ahead of 0014 raises `UndefinedColumnError` on
every claim and poll-crashes in a loop, claiming nothing. The same argument now applies twice over:
a worker carrying 15.3's emit sites, deployed ahead of 0015, raises on a missing `run_event`
relation from inside the pipeline. The reverse order is safe: between (3) and (4) the OLD image runs
against the NEW schema, and every one of these changes is purely additive.

Read back: `run.heartbeat_at` nullable=YES · `run.reclaim_count` NOT NULL default 0 ·
`tribunal_head = 0015` in **`tribunal.tribunal_alembic_version`** (the TRIBUNAL line).

**3b. INTAKE (`nestor`): repin `nestor-migrate` to the `$SHA` backend image, then execute
(alembic 0013).**

This half is new to this procedure — previous gap-phase deploys touched only the tribunal line. It
adds `research_runs.event_seq`, the feed cursor `nestor-api` reads to decide whether new events
exist. It must run **before** `nestor-api` is repointed in step 5.

```bash
gcloud run jobs update nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:${SHA}"
gcloud run jobs describe nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.template.spec.containers[0].image)'   # must echo :${SHA}
gcloud run jobs execute nestor-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

**The repin is not optional** (lesson hit live 2026-07-22): the Job does NOT track the service
image, so executing an unrepinned Job is a silent no-op — alembic connects, finds itself at head on
the stale revision set, exits 0, and logs no upgrade line at all.

**Proof — the literal line, and `exit(0)` is never it:**

```
Running upgrade 0012 -> 0013
```

> ⚠️ **DO NOT GO LOOKING FOR THAT LINE IN THE PREFLIGHT GATE — IT IS NOT THERE AND ITS ABSENCE
> MEANS NOTHING.** The backend gate (`cloudbuild.test.yaml`) runs `alembic upgrade head` inside its
> own fixture but **does not surface alembic's `Running upgrade` output**; only the alembic version
> banner and a config deprecation warning appear. This was established directly in plan 15.3-06,
> which is why that plan added live-schema tests rather than letting "the build did not crash"
> stand as evidence. So: the literal line is the proof **of the Job in this step**, and the gate is
> proof of something else entirely.

Because that log line is the only narrative evidence, confirm the schema itself as well — this is
the same pair of reads the backend gate asserts, run here against live Cloud SQL:

```sql
-- (i) the column exists, with the right type and nullability
SELECT column_name, data_type, is_nullable, column_default
  FROM information_schema.columns
 WHERE table_schema = 'nestor'
   AND table_name   = 'research_runs'
   AND column_name  = 'event_seq';
-- expect exactly one row: bigint · YES · NULL default

-- (ii) the INTAKE line's own version table — NOT the tribunal one
SELECT version_num FROM public.alembic_version;
-- expect: 0013
```

`event_seq` must be **NULL** on every pre-existing row, never 0: NULL means "this run has emitted no
events", while 0 would claim a feed positioned at its own start. No backfill runs and none should.

---

**4. ⛔ EXECUTE THIS AFTER STEP 6, NOT HERE. Deploy `tribunal-worker` LAST, via `deploy-worker.sh`.
This is also the D-E env revert.**

> ⛔ **THE WORKER IS THE LAST DEPLOYABLE. Do not run this until step 2 has PROVEN the queue empty
> and step 6 has resolved every `running` row.** Its position in this numbered list is a historical
> artifact; see the ORDERING CORRECTION at the top of § 15.2.k.
>
> **`--min-instances=0` does NOT stop the worker from running.** Deploying a revision starts a
> container to health-check it, and this worker begins its Postgres poll loop the moment it boots.
> "Paused" describes *steady state*, not deployment.
>
> **And no env lever can fix that**, because of how the loop is written: `runs/worker.py`'s
> `while True:` **claims FIRST and sleeps LAST** — `claim_one()` runs at the top of the very first
> iteration, before `asyncio.sleep(POLL_INTERVAL_SECONDS)` is ever reached. So
> `NESTOR_WORKER_POLL_INTERVAL` buys nothing, and `NESTOR_WORKER_STALE_MINUTES` guards only
> `CLAIM_SQL`'s stale-`running` reclaim arm — a `queued` row is claimable **at any age**.
>
> **An empty queue is the ONLY protection.**
>
> *Observed twice, on the same day.* 2026-07-28 08:22:57Z: the deploy claimed `d6bb3aae` and burned
> ~15 minutes of paid pipeline. 2026-07-28 12:35Z, on the clean redeploy with `min-instances=0`
> set, the logs read `Starting new instance. Reason: DEPLOYMENT_ROLLOUT` then
> `worker_started poll_s=2.0` — identical behaviour, harmless only because step 2 had proven the
> queue empty first.

Ship it paused, so the unpause stays a separate, deliberate act (step 7):

```bash
MIN_INSTANCES=0 TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp IMAGE_TAG="$SHA" \
  tribunal/infrastructure/cloud-run/deploy-worker.sh
```

`MIN_INSTANCES` defaults to `1`. Without the override the script's single `gcloud run deploy` sets
`--min-instances=1` **and** `NESTOR_WORKER_STALE_MINUTES=60` in one atomic command — unpausing and
re-arming reclaim at the same instant. The override is necessary but **not sufficient**: it governs
steady state only, and the boot still happens.

What this one command carries: the new `CLAIM_SQL` + the liveness heartbeat + the reclaim ceiling
and reap (15.2-20), the brief parser (15.2-21), the deep-serialised replay and
`NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol` (15.2-22), the PII egress scrub (15.2-23), and the stage
logging (15.2-24).

> ⚠️ **THE `TRIBUNAL_ANTHROPIC_SECRET` OVERRIDE IS NOT OPTIONAL WHILE THE BURNER IS IN FORCE.**
> The committed default in the script is `Nestor_Claude2`, which is **not topped up**. The live
> services run on `Nestor_Claude_Temp` (operator decision 2026-07-27), applied via this override so
> that nothing committed had to change. **A redeploy without the override silently repoints the
> worker at the empty key and the next run walls mid-flight.** Drop the override only once
> `Nestor_Claude2` is funded — and then confirm by name in step 8.

> **The env revert happens HERE, as a side effect, and that is deliberate.** The script deploys with
> a whole-env `--set-env-vars` list whose committed content is
> `NESTOR_ENV=prod,NESTOR_WORKER_POLL_INTERVAL=2.0,NESTOR_WORKER_STALE_MINUTES=60,NESTOR_TRIBUNAL_UNCAPPED=1`.
> Because that flag **replaces** the entire plain env, this deploy restores the threshold to `60` and
> **drops `NESTOR_RUN_ABORTED_MARKER`**, since neither temporary value is in the committed list. So
> Step 15.2.j items 3 and 4 normally have nothing left to do. **Verify with the describe in step 8
> rather than assuming**, and run them explicitly with `--update-env-vars` / `--remove-env-vars` if
> the read disagrees. Never hand-type `--set-env-vars` against a live service outside this script
> (the Phase-12 lesson: it drops every binding you did not restate).

*Why `60` is safe now where it was not before.* The number no longer means "how long a run may
take" — it means "how long the worker may be **silent**". The executing worker writes
`run.heartbeat_at` every `NESTOR_WORKER_HEARTBEAT_S` (default 30s), so 60 minutes of silence is 120
consecutive missed heartbeats: the process is gone, not slow. A 35-minute long-poll no longer looks
stale at any age.

---

**5. Deploy `tribunal-api`, then `nestor-api`, then the frontend. The order is load-bearing.**

```bash
TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp IMAGE_TAG="$SHA" \
  tribunal/infrastructure/cloud-run/deploy-api.sh

gcloud run services update nestor-api --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/backend:${SHA}"

gcloud run deploy nestor-frontend \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/frontend:${SHA}" \
  --region "$REGION" --allow-unauthenticated --port 8080 --project="$GOOGLE_PROJECT"
```

*Why this order.* The Stop button calls `POST /intakes/{id}/research/cancel` on `nestor-api`, which
calls `POST /api/runs/{id}/cancel` on `tribunal-api`. A frontend that ships first shows a button
whose route does not exist yet — a 404 that looks like a defect in the feature you are about to
demo. `nestor-api`'s image update touches **no secret and no env** (`--image` only), so the
Anthropic binding it already carries is unaffected.

**NEVER bind `SERPAPI_API_KEY` to `nestor-api`** — `backend/scripts/ci_no_run_research.sh` scans
`backend/app/**` and `frontend/src`, and INTAKE-05 must stay green.

*What 15.3 adds to this same order.* `nestor-api` here also carries the events proxy, the
run→intake locate verb and the cursor mirror, all of which read `research_runs.event_seq` — so
**step 3b must already have run**, or every one of those reads fails on a missing column. The
frontend here also carries the run page, which calls the locate verb before it can render anything
at all: a frontend shipped ahead of `nestor-api` gives a run page that 404s on open, which looks
exactly like a broken permission and is not.

---

**6. Clear run `d6bb3aae` through the UI — BEFORE the worker deploy (step 4) AND before the unpause
(step 7). This is D-D's acceptance demo.**

> ⛔ **THIS STEP RUNS BEFORE STEP 4.** The original ordering put the worker deploy first and that is
> what caused the 2026-07-28 incident — the deploy's own health-check boot claimed this row. See the
> ORDERING CORRECTION at the top of § 15.2.k. Resolve the run, re-confirm the queue via step 2, and
> only then deploy the worker.

> **THE SAFETY ORDERING IS UNCHANGED BY PHASE 15.3, AND THAT IS WORTH STATING RATHER THAN LEAVING
> TO BE RE-DERIVED.** Run `d6bb3aae` is still cancelled through the UI **before** any unpause, and
> `--min-instances=1` is still the **last** thing that happens. Nothing in 15.3 touches the claim
> query, the reclaim ceiling or the heartbeat — it adds an append-only table, a read endpoint, a
> proxy and a page, and it changes no pipeline decision. So there is nothing here to re-reason
> about under time pressure: the order below is the order, for the same reasons it always had.

> ⛔ **DO NOT SKIP THIS AND DO NOT REORDER IT AFTER STEP 7.** The D-E fix does **not** protect this
> particular row. Staleness is `COALESCE(heartbeat_at, started_at)`, and `d6bb3aae` predates 0014 so
> its `heartbeat_at` is NULL — it is measured by `started_at` (2026-07-27 08:09 UTC), which is
> already hours or days stale. Its `reclaim_count` is 0, under the ceiling of 2. **So the moment
> step 4 restores `NESTOR_WORKER_STALE_MINUTES=60`, that row becomes claimable again**, and step 7
> would hand it straight to a fresh worker at full cost. The heartbeat protects every run started
> from now on; it cannot retro-fit liveness onto a row that never wrote one.

1. Open intake `4a500d44-62b5-4f73-905f-792e31d0d9cc` in the admin UI.
2. The research card shows the run as active. **Check the elapsed clock: it should show a LARGE
   value carried from the real `started_at`, and refreshing the page must NOT reset it to zero.**
   That is D-L verified live (15.2-24 shipped the producer half; the frontend contract already
   expected the field).
3. Click **Stop**, confirm the dialog.
4. Expected: the card resolves to the cancelled state, and the intake becomes retriable — the
   re-trigger affordance reappears. `_RETRYABLE_RUN_STATUSES` contains `cancelled` and excludes
   `running`, which is precisely why the stuck row blocked retry.
5. If the button 404s, the frontend shipped ahead of `nestor-api` — re-check step 5's order before
   reporting a defect.
6. Confirm in SQL that the row really resolved, not just the mirror:
   `SELECT status FROM tribunal.run WHERE id = 'd6bb3aae-33e7-49fd-aa35-57dc529e05b3';` → `cancelled`.

---

**7. ONLY NOW unpause the worker.**

```bash
gcloud run services update tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --min-instances=1
```

Then watch it for one poll cycle and confirm it **claims nothing**. A cancelled run is not in the
claimable set and step 2 proved the queue is otherwise empty, so the correct observation is an idle
worker. **If it claims something, STOP and report — that is D-E unfixed**, and the fix's whole
purpose was to make that impossible.

---

**8. Read back and record — verbatim, in the session notes. Not "looks right".**

```bash
# (a) The worker's plain env: the threshold must be a REAL value and the marker must be GONE.
gcloud run services describe tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.containers[0].env)' | tr ',' '\n' \
  | grep -E 'NESTOR_WORKER|ABORTED|NESTOR_OPENAI_DR_MODEL'
# expect: NESTOR_WORKER_STALE_MINUTES=60   (NOT 525600)
#         NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol
#         NO line matching NESTOR_RUN_ABORTED_MARKER

# (b) Secret bindings by NAME only, never a value.
for SVC in tribunal-worker tribunal-api; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(spec.template.spec.containers[0].env)' | tr ',' '\n' \
    | grep -E 'ANTHROPIC_API_KEY|SERPAPI_API_KEY'
done
# expect Nestor_Claude_Temp (while the burner is in force) + Nestor_SERP on both.

# (c) All four revisions, and 100% traffic on each new one.
for SVC in tribunal-worker tribunal-api nestor-api nestor-frontend; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(status.latestReadyRevisionName,status.traffic)'
done

# (d) The resolved deep-research model ids, from 15.2-22's new startup line
#     (emitted once per process on first client construction).
gcloud logging read \
  'resource.type="cloud_run_revision" AND resource.labels.service_name="tribunal-worker"' \
  --project="$GOOGLE_PROJECT" --limit=50 --format="value(textPayload)" | grep -i "deep.research"
```

```sql
-- (e) BOTH alembic heads, each read from its OWN version table. One does not imply the other.
SELECT version_num FROM tribunal.tribunal_alembic_version;   -- expect: 0015
SELECT version_num FROM public.alembic_version;              -- expect: 0013
```

Record: the worker's `NESTOR_WORKER_STALE_MINUTES`, the **absence** of `NESTOR_RUN_ABORTED_MARKER`,
the resolved deep-research model ids and whether each came from the environment or the default, the
four revision names, `d6bb3aae`'s final status, and **both alembic heads — TRIBUNAL == 0015 and
INTAKE == 0013.** Two heads, two tables, two separate reads; a single "migrations fine" is not a
record of either.

---

**9. Decide the IAM grant. Either answer closes it; leaving it undecided does not.**

`roles/iam.serviceAccountTokenCreator` on `nestor-run@` was granted to `tools@dotto.be` on
2026-07-27 to attempt a manual seam cancel. **It did not achieve one** — the seam also requires
`X-Nestor-Tenant-Id`, which is reachable only by the intake backend — and it is a standing weakening
of the Phase-14 lockdown. With the UI cancel shipped (step 6) it buys nothing.

```bash
gcloud iam service-accounts remove-iam-policy-binding \
  nestor-run@project-cb01b861-cb4a-438d-b9a.iam.gserviceaccount.com \
  --member="user:tools@dotto.be" --role="roles/iam.serviceAccountTokenCreator"
```

**Or** record, in one sentence, that the grant is KEPT as a deliberate operator capability and why.
Write the answer into `15.2-V01-ABORTED-FINDINGS.md` § State left behind either way.

---

**10. THE COMBINED DEPLOY RECORD — fill this in during the deploy, with real values.**

D-03 put two phases in one batch and accepted a named risk for it: **the next live run exercises a
changed engine AND a changed frontend at once, so a surprising result is harder to attribute.** This
table is the whole mitigation. Six weeks from now, when V-01 does something unexpected, the first
question will be *"was that a behaviour change or an observability change?"* — and either this
answers it in ten seconds or it is answered by archaeology.

> ⚠️ **THE ONE-`$SHA` PROPERTY IS BROKEN FOR THIS DEPLOY, DELIBERATELY.** The field below said "the
> single `$SHA`" because a mixed-revision state was supposed to be unreachable by accident. This
> deploy has **two**, and the reason is recorded rather than hidden: the incident forced the batch to
> be split, and the seam 401/403 retry fix (`31a7f71`) was authored *after* the first SHA was built.
> A reader must therefore check **two** rows, not one, before concluding what was live.

| Field | Value |
|---|---|
| Date · who ran it | **2026-07-28** · operator (`tools@epicimpact.be`) with an assisted session |
| SHA **A** — `20260728-094409` | `tribunal-api`, `nestor-frontend`, `tribunal-worker` |
| SHA **B** — `20260728-132637` | `nestor-api` ONLY — the seam 401/403 retry fix, commit `31a7f71` |
| `tribunal-worker` revision | `tribunal-worker-00002-ztp` (image SHA A; service was DELETED mid-incident and RECREATED) |
| `tribunal-api` revision | `tribunal-api-20260728-094409-102356` |
| `nestor-api` revision | `nestor-api-00044-8bz` (SHA B; digest `sha256:171f716f…`) |
| `nestor-frontend` revision | `nestor-frontend-00028-q52` |
| TRIBUNAL head after (expect 0015) | **0015** ✅ |
| ↳ literal line(s) observed | `Running upgrade 0013 -> 0014` · `Running upgrade 0014 -> 0015` — both observed in the 09:4x session |
| INTAKE head after (expect 0013) | **0013** ✅ |
| ↳ literal line observed | `Running upgrade 0012 -> 0013` — observed in the 09:4x session |
| Engine gate count observed | ⚠️ **NOT CARRIED INTO THE RECORD.** The engine gate ran in the 09:4x session but its `collecting:` count was not written down, so it cannot be asserted here. The **backend** gate was re-run against SHA B on the final tree: **299 passed, 1 skipped, 139 deselected**, with all five 401/403 tests green by name. |
| Run `d6bb3aae` | `cancelled` · `completed_at` 09:53:25Z · `reclaim_count` 1 (the intake mirror still reads `failed`) |
| Queue state before the worker deploy | **PROVEN EMPTY** as `worker_user` — zero rows in `('queued','running')`, with a vacuity check and a positive control, and the gate re-run inverted to confirm it fails (exit 93) |

**The two change lists. Keep them SEPARATE — merging them destroys the mechanism.**

| 15.2 gap fixes in this batch (behaviour) | landed? |
|---|---|
| D-A / D-B — two dead research streams (15.2-22) | ✅ SHA A (`tribunal-worker`); `NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol` confirmed by describe |
| D-D — the operator cancel path (15.2-25) | ✅ SHA A (`nestor-frontend`) + SHA B (`nestor-api`) |
| D-E — a stuck run re-billing every 60 min (15.2-20) | ✅ migration 0014 + SHA A worker; `NESTOR_WORKER_STALE_MINUTES=60` confirmed |
| D-F — the engine logged only failures (15.2-24) | ✅ SHA A — **MEASURE on the first live run** |
| D-G / D-H — the workshop deepened the pack, not the questions (15.2-21) | ✅ SHA A |
| D-I — personal identifiers sent to third parties (15.2-23) | ✅ SHA A |
| D-L — the elapsed clock (15.2-24) | ✅ shipped — ⚠️ **NOT yet verified live**: the UI cancel demo was overtaken by the incident |
| D-M — provider fact-list compliance (15.2-23, partial — MEASURED on the next run) | ✅ shipped · measurement OPEN |
| any other that landed: | **seam 401/403 retry (`31a7f71`, quick task `260728-ftv`)** — SHA B, `nestor-api` only. Not a 15.2 defect id: found *during* this deploy, caused by it |

*(D-C was withdrawn as a misdiagnosis; D-J and D-K are deliberately out of scope.)*

| 15.3 changes in this batch (observability only) | landed? |
|---|---|
| engine run-events: the append-only `run_event` table + its emit sites | ✅ migration 0015 + SHA A — **PROVEN IN PRODUCTION**: 80 `run_event` rows across all twelve line kinds |
| the bounded, cursor-ordered events read endpoint | ✅ SHA A (`tribunal-api`) |
| the seam: events proxy, run→intake locate verb, feed cursor mirror | ✅ migration 0013 (intake) + SHA B (`nestor-api`) |
| the dedicated run page: feed, eight-status card, four affordances | ✅ SHA A (`nestor-frontend`) — ⚠️ the four affordances are **NOT yet operator-verified** (plan 15.3-09's two checkpoints remain open) |

> **The one piece of luck in this incident.** The accidental ~15-minute re-execution was phase
> 15.3's first live validation, and it passed: **80 `run_event` rows across all twelve kinds**
> (agent_done 19, search 15, agent_fail 10, thinking 9, summary 7, divider 7, agent_run 6, tool 3,
> dispatch/streams/plan/agent_retry 1 each), with dividers rendering the human stage label rather
> than the raw key. Phase 15.2's heartbeat worked as designed in the same window — it is what proved
> the process was alive rather than stalled. To read `tribunal.run_event` by hand you must bind
> `app.tenant_id` first; migration 0015 deliberately grants no `worker_all` policy there, so an
> unbound query ERRORS rather than returning zero rows.

**The sentence the operator writes at deploy time, in their own words:**

> _"Phase 15.3 changed no engine behaviour — what the pipeline decides, dispatches and produces is
> identical to before this deploy. Therefore an unexpected V-01 outcome is attributable to the 15.2
> gap fixes or to the live environment, not to phase 15.3."_

⛔ **If that sentence cannot honestly be written, the deploy STOPS and the discrepancy is
investigated first.** It is not a formality: it is the only thing standing between "we know what
changed" and a week of bisecting two phases at forty-five dollars a run.

> ⚠️ **STATUS 2026-07-28: NOT YET WRITTEN — still owed before V-01.** The deploy completed, but the
> sentence is the operator's to write and has not been. Nothing observed contradicts it: phase 15.3
> added a table, a read endpoint, a proxy and a page, and the 15-minute accidental re-run behaved as
> the pre-15.3 pipeline did while writing the new feed rows. **But "nothing contradicts it" is not
> the attestation** — the attestation is a person affirming it. Write it here before V-01.
>
> One thing V-01 must account for, since it is exactly the attribution problem D-03 predicted: this
> deploy is **not** one `$SHA`. `nestor-api` carries a behaviour change the other three do not — the
> 401/403 retry arm. If V-01 surprises on run *finalization* specifically (a run ending `failed` or
> not ending when it should), SHA B is the first place to look, not the engine.

---

### What to check in the logs on the FIRST live run after this deploy

The engine used to log **only failures**, which is what made a healthy 35-minute long-poll
indistinguishable from a dead pipeline (defect D-F; it cost an hour and one withdrawn misdiagnosis).
15.2-24 fixed that. On the next run, these lines are the instrument:

1. **`stage_enter` / `stage_exit`** — one INFO line per stage boundary, the exit line carrying that
   stage's wall seconds plus its counts. **When the run goes quiet, the last `stage_enter` line
   names the stage it is sitting inside.** Do not diagnose from CPU or from silence again.
2. **`run_stages_complete: seconds=… stages=…`** — the closing line. A clean run reports
   `stages=14`. A materially lower number on a run that finished is worth chasing.
3. **The two `collect_provider_facts` lines** — this is how D-M gets *measured* rather than assumed:

   ```
   collect_provider_facts: <provider> returned no usable fact list for k of m research report(s)
   ... %d report(s) with a fact list
   ```

   On run `d6bb3aae` gemini honoured the fact-list block on **0 of 8** reports. 15.2-23 shipped a
   placement change and a placeholder-URL rejection; whether gemini now complies is a live-LLM
   question no CI gate can answer. Read `k of m` for gemini and write the number down — that is the
   evidence, and a lower `k` is the result.
4. **`facts: rejecting non-http(s) SOURCE_URL`** — expect these to name a *placeholder* now
   (`N/A`, `-`, `unknown`) and drop the fact, while a merely malformed URL drops the link and keeps
   the fact.
5. **The PII scrub WARNING** — names the angle index, the stream and the **count**, never the value.
   Any occurrence means a personal identifier was about to leave the engine and was removed; the
   operator's feed row says so too.
6. **`run_reclaimed_from_dead_worker`** — should NOT appear on a healthy run. If it does, a claim
   recovered a run the heartbeat had declared dead; note the `reclaim_count` on it.

---

## Phase 15.8 — The WHOLE five-wave engine redesign: dual Tribunal REBUILD + THREE migrations (0016 / 0017 / 0018), then ONE measuring run

<!-- ============================ OWNERSHIP MARKER ============================ -->
<!-- THIS SECTION HAS TWO WRITERS AND THEY MUST NOT COLLIDE.                    -->
<!--                                                                            -->
<!--   * Steps 15.8.a … 15.8.i AND step 15.8.k were authored by plan 15.8-12.   -->
<!--     They are READ-ONLY at deploy time. Execute them; do not edit them.     -->
<!--   * Plan 15.8-14 fills `### Step 15.8.j — THE DEPLOY RECORD` and NOTHING   -->
<!--     ELSE.                                                                  -->
<!--                                                                            -->
<!-- Adding a step outside 15.8.j is a BOUNDARY VIOLATION, not a convenience.   -->
<!-- Two authors editing one procedure is how a deploy acquires two sources of  -->
<!-- truth, and the one that gets read is whichever the reader found first.     -->
<!-- ========================================================================== -->

> ⚠️ **THE SEQUENCING RULING — operator, 2026-07-29. DO NOT RE-ARGUE IT.**
>
> *"I don't want to measure anything unless we finish all changes."*
>
> This **reverses** `ENGINE-REDESIGN-SPEC.md` § 2's "ship Wave 1 alone and measure it" and the parked
> plan `15.4-11` that was written to it. Waves 1–5 (phases 15.4 / 15.5 / 15.6 / 15.7 / 15.8) all ship
> in **this one deploy**, and **ONE** live run measures all of it together. The spec and `15.4-11`
> still read the opposite way on their face; both carry the override in place, deliberately — this
> project marks superseded text rather than deleting it.
>
> **THE TRADE-OFF, STATED AND ACCEPTED — and it belongs here rather than only in a planning file,
> because it is a fact the operator needs at 3am:** with five waves landing in one deploy, **an
> unexpected result in the measuring run CANNOT be attributed to a single change.** That is the price
> of the ruling and it was paid knowingly.
>
> **The only mitigation this deploy has is
> `.planning/phases/15.8-research-engine-redesign-yield-instrumentation-deploy-one-me/15.8-UAT.md`** —
> a comparison table built BEFORE the run, from the recorded V-01 baseline, with every 15.8 cell
> empty. Filling it is **not optional paperwork.** Without it, an odd number six weeks from now is
> answered by archaeology across five phases at forty-five dollars a run.

> ⛔ **ORDERING — THE WORKER IS THE LAST DEPLOYABLE.** This is not a new rule; it is
> **§ Step 15.2.k's ORDERING CORRECTION**, which exists because following the as-written order caused
> an incident. Do not invent a second authority for it — read that block, then execute the steps
> below in their written letter order.
>
> The mechanism, restated at the point of use because **an ordering constraint without its reason
> gets reordered by the next person in a hurry**: a deploy *boots* the container to health-check it,
> and `runs/worker.py`'s `while True:` **CLAIMS FIRST and SLEEPS LAST** — `claim_one()` runs at the
> top of the very first iteration, before `asyncio.sleep(POLL_INTERVAL_SECONDS)` is ever reached.
>
> **`--min-instances=0` describes STEADY STATE ONLY and buys nothing at boot. AN EMPTY QUEUE IS THE
> ONLY PROTECTION.**
>
> *Observed twice on 2026-07-28.* **08:22:57Z** — the worker deploy claimed run `d6bb3aae` within
> seconds and burned **~15 minutes of paid pipeline unattended**; the operator deleted the service to
> stop it. **12:35Z** — the clean redeploy *with* `min-instances=0` set booted identically
> (`Starting new instance. Reason: DEPLOYMENT_ROLLOUT` → `worker_started poll_s=2.0`) and was
> harmless **only because the queue had been proven empty first.**

### What ships, by wave

| Wave | Phase | What it changes | Carried by |
|---|---|---|---|
| **Wave 1** | 15.4 | Extraction repair: separator-tolerant distiller split, the LOUD drop warning, the fact-list retry, cite-marker recovery, grounding-redirect resolution (**alembic 0016**), the `gpt-5.6-sol` cost row | `tribunal-worker` (+ `tribunal-api` at the shared `$SHA`) |
| **Wave 2** | 15.5 | Claim attribution (**alembic 0017**): `claim.sub_question`, `claim.corroboration_key`, `claim.as_of` — all nullable | `tribunal-worker` |
| **Wave 3** | 15.6 | Dispatch by topic: at most `_D6_MAX_GROUPS` = 5 groups × 3 providers (`own` dropped from the rotation, D-R5), plus the discovery bracket (`_DISCOVERY_PER_PARENT_CAP` = 3) | `tribunal-worker` |
| **Wave 4** | 15.7 | The creative workshop loop: `_LOOP_MIN_ROUNDS` = 4 (the floor added 2026-08-04), `_LOOP_MAX_ROUNDS` = 10 (a **ceiling, not a target**), `_FLOOR_PER_QUESTION` = 5, `_CROSS_CUTTING_SLOTS` = 2 | `tribunal-worker` |
| **Wave 5** | 15.8 | Yield instrumentation (**alembic 0018**): `assignment_yield` + `workshop_round_yield`, their emitters, and every carried defect closed before the measurement | `tribunal-worker` + `tribunal-api` |

### What does NOT ship — stated in words, because an unstated omission reads as an oversight

**`backend/` and `frontend/` are UNCHANGED — zero files** since `31a7f71`, the last commit that
reached a live service (SHA B of the 2026-07-28 deploy, the seam 401/403 retry fix). Therefore:

- **NO `nestor-migrate` run.** The **INTAKE** alembic line stays at **0013**. No
  `backend/app/db/alembic` revision landed this phase.
- **NO `nestor-api` rebuild** and **NO `nestor-frontend` rebuild.** Both are **CONFIRM-ONLY**: record
  their existing revision names in the deploy record. **The empty diff IS the evidence.**
- **The reason is RISK, not cost.** The frontend build takes four hand-typed `--substitutions`
  (`_API_BASE_URL`, `_FB_API_KEY`, `_FB_AUTH_DOMAIN`, `_FB_PROJECT_ID`) whose mistyping breaks the
  **live** frontend. That is a real hazard bought for a **zero-byte code delta**.

**Do not trust the paragraph above — RE-DERIVE it at deploy time.** It was measured while later plans
of this phase were still being written:

```bash
git diff --name-only 31a7f71 HEAD | awk -F/ '{print $1}' | sort -u
```

⛔ **If `backend` or `frontend` appears in that output, THIS SECTION IS OUT OF DATE.** The omission
must be re-decided before anything is built, and those images go back into step 15.8.c's build list
**at the same shared `$SHA`**. All four services stay in the deploy record either way.

---

### Step 15.8.a — Preflight: the stale-base ABORT GATE, positively, on disk

Cloud Build ships **the tree you submit**. A stale worktree submits a Cloud Build of the WRONG SOURCE
and returns a confidently green result.

```bash
git status --porcelain          # must be EMPTY
git log --oneline -1            # record this SHA in the session notes
```

**Why `rev-list --count BASE..HEAD == 0` is NOT the check:** it reads **GREEN while stale**, because
on a stale tree the stale ref usually *is* the merge-base. The discriminator is
`git merge-base HEAD <BASE>` **not equal** to `<BASE>`. This repo's worktree stale-base trap is
**15/15** — most recently **2/2 in phase 15.7 at 595–601 commits behind**, and the distances grow as
master advances.

**So do not reason about refs at all here. Assert the ARTIFACTS, positively, one per plan.** Each row
below names something that plan **created** — a NEW file or a NEW symbol, read out of that plan's
merged SUMMARY. **Never a path that pre-existed the phase: a pre-existing path proves nothing.**

| Plan | The NEW thing it introduced | The assertion |
|---|---|---|
| 15.8-01 | new test `test_the_merge_note_is_emitted_once_however_many_merges_the_ceiling_took` | `grep -q "test_the_merge_note_is_emitted_once_however_many_merges_the_ceiling_took" tribunal/nestor_pulse_sdk/tests/test_question_grouping.py` |
| 15.8-02 | NEW file `tests/test_pipeline_dispatch_clause.py` | `ls tribunal/nestor_pulse_sdk/tests/test_pipeline_dispatch_clause.py` |
| 15.8-03 | NEW symbol `_text_key` in `workshop_rank.py` (the CR-01 join key) | `grep -q "def _text_key" tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_rank.py` |
| 15.8-04 | NEW symbol `count_drops` in `workshop_register.py` (D-W5-6's cause-filtered counter) | `grep -q "def count_drops" tribunal/nestor_pulse_sdk/pipeline/tribunal/workshop_register.py` |
| 15.8-05 | NEW files: alembic `0018` + the yield emitter | `ls tribunal/nestor_pulse_sdk/alembic/versions/0018_yield_instrumentation.py tribunal/nestor_pulse_sdk/runs/yield_records.py` |
| 15.8-06 | NEW file: the D-W5-8 / D-W5-9 decision record | `ls .planning/phases/15.8-*/15.8-06-DECISION-RECORD.md` |
| 15.8-07 | NEW `EXPECTED_FILES` assertion in the gates config (that file had none before) | `grep -q "EXPECTED_FILES=" tribunal/cloudbuild.test-gates.yaml` |
| 15.8-08 | NEW symbol `_scrub_urls_in_value` in `audit/gcs_blob.py` (the query-string credential scrubber) | `grep -q "_scrub_urls_in_value" tribunal/nestor_pulse_sdk/audit/gcs_blob.py` |
| 15.8-09 | NEW files: the assignment-yield emit tests | `ls tribunal/nestor_pulse_sdk/tests/test_pipeline_assignment_yield.py tribunal/nestor_pulse_sdk/tests/test_research_division_yield.py` |
| 15.8-10 | NEW file: the round-yield persist tests | `ls tribunal/nestor_pulse_sdk/tests/test_workshop_round_yield.py` |

⛔ **The absence of ANY ONE of those is an ABORT — before the image build, before any spend.** Not a
warning, not a note. `.planning/` is gitignored, so its files are force-added; if a `.planning`
sentinel is missing, check that before concluding the tree is stale.

> ⚠️ **A sentinel that asserts an ABSENCE must be PAIRED with a presence over the same file.** A bare
> `grep -c <thing> == 0` is an **unpaired-zero gate**: it is green on an empty file, a renamed file
> and a deleted file. Assert **both halves** — the new thing present AND the old thing gone.

> ⛔ **NO ARTEFACT MAY SATISFY TWO GATES (WR-05).** The 15.8-08 row above used to be
> `ls .planning/phases/15.8-*/15.8-PRECONDITIONS.md` — **the very file the blocking pre-conditions
> below are recorded in.** Combined with "if a `.planning` sentinel is missing, check that before
> concluding the tree is stale", that gave an operator a signposted path to force-add an **empty**
> `15.8-PRECONDITIONS.md` to clear the staleness row — **silently clearing the credential gate with
> the same keystroke**, and the runbook would then read green over an unredacted live SerpApi key
> under 7-year retention. The staleness row now asserts a **code symbol in a tracked file**, which no
> amount of `.planning` housekeeping can create, and the pre-condition gate below asserts **content**
> rather than existence. Keep them apart. If a future plan's only artefact is a `.planning` file that
> is also a gate, that plan needs a second sentinel, not a shared one.

**Then confirm both blocking pre-conditions are SETTLED. ASSERT THE RULING, NEVER THE FILE** — an
empty or half-written `15.8-PRECONDITIONS.md` must FAIL this, which is why these are `grep` and not
`ls`:

```bash
grep -q "REDACTION: PASS"   .planning/phases/15.8-*/15.8-PRECONDITIONS.md || echo "ABORT: redaction pre-condition NOT settled"
grep -q "GPT-5.6-SOL RATE:" .planning/phases/15.8-*/15.8-PRECONDITIONS.md || echo "ABORT: cost-row pre-condition NOT settled"
```

⚠️ **Those two tokens are a CONTRACT ON 15.8-08's output**, which is paused at an operator gate and
has not run. `15.8-PRECONDITIONS.md` must contain the literal strings `REDACTION: PASS` and
`GPT-5.6-SOL RATE:` (the latter followed by either the published rates or the dated
no-published-rate ruling — **both are a PASS**, per pre-condition 1 below). A record that settles the
question in different words leaves this gate red; fix the record, never the gate.

**What each pre-condition means:**

1. **The `gpt-5.6-sol` cost row** (plan 15.4-07): either published rates, **or** a recorded ruling
   that none exist. ⛔ **Adding the key with nulls is NOT an option** — `_rate()` turns a null into
   `Decimal("0")`, producing a confident **$0.00** and clearing `cost_pending` on a fabricated number.
   "No published rate exists" is a recorded **PASS**, not a gap.
2. **The audit-blob redaction check — BLOCKING, not advisory.** The SerpApi key rides in a URL
   **QUERY PARAMETER**, so an unredacted body freezes a **live credential** into the audit bucket
   under **7-year retention**. This one stops the deploy.

**And one line to close a question nobody should re-open:** the `Nestor_Claude_Temp` burner key
transited a chat in plaintext on 2026-07-27 and is live on both Tribunal services. Its rotation is
**DEFERRED TO GO-LIVE by operator decision (2026-08-03).** It is therefore **NOT a blocker and NOT a
gap — it is a decision.** Do not rotate it early; do not re-raise it.

---

### Step 15.8.b — The gates, read from build TEXT

```bash
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml  --project="$GOOGLE_PROJECT"
```

**Three rules, each with its reason. All three have burned this project.**

1. ⛔ **`gcloud builds submit … | tail` returns the PIPE's exit code, so a FAILED build reports
   exit 0.** Read the build **TEXT** — `gcloud builds describe <BUILD_ID>` or `gcloud builds list` —
   **never a shell status.**
2. ⛔ **An `EXPIRED` Cloud Build is visually identical to `QUEUED`, and it is NOT a result.** One 15.7
   run expired in the queue and was nearly read as pending. Read the STATUS field and say the word
   out loud: `SUCCESS`, `FAILURE`, `TIMEOUT`, `EXPIRED`, `QUEUED`, `WORKING`.
3. ⛔ **The engine gate's printed `collecting: N of N expected files` must equal `EXPECTED_FILES`
   READ OUT OF THE COMMITTED CONFIG AT THAT MOMENT.** Plan 15.8-13 sets that number for this phase.
   **Do not compare against any number quoted in this runbook** — a runbook quoting a stale count
   teaches the operator to accept a gate that ran less than it claims.

**Baselines — these are builds to BEAT, attributed to their build ids, NOT the values to compare
against:**

- Engine gate, build **`7c89be5c`**: **1538 passed / 0 failed / 13 skipped**, at
  `collecting: 36 of 36`.
- Gates gate, build **`2eae97e6`**: **187 passed, 2 deselected** (measured before 15.8-07's new
  `EXPECTED_FILES` assertion went live).

**How to read the gates config's result, in BOTH directions (D-W5-12):**

- A **FLAT 187** there is a genuine **REGRESSION PASS** over the wave-1 and wave-2 edits — most of the
  files that config runs import `pipeline.tribunal.*` or `nestor_pulse_sdk.pipeline`, which this phase
  edits. It is **evidence**, and it should be read as such.
- A **RED** there is a **real signal about the engine edits**. ⛔ **Do not "fix" the gates config to
  make it green** — find what wave 1 or wave 2 broke.
- **A count that did not rise is not automatically a skip — but it must be EXPLAINED, not merely
  noted.**

**No backend gate and no frontend gate run in this deploy, and that omission is deliberate:**
`backend/` and `frontend/` are unchanged (see *What does NOT ship* above, and re-derive it).

---

### Step 15.8.c — BUILD both Tribunal images at ONE `$SHA`. BUILD ONLY

```bash
export SHA="$(date +%Y%m%d-%H%M%S)"

gcloud builds submit tribunal --config=tribunal/cloudbuild.worker.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:${SHA} \
  --project="$GOOGLE_PROJECT"
gcloud builds submit tribunal --config=tribunal/cloudbuild.api.yaml \
  --substitutions=_IMAGE=${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA} \
  --project="$GOOGLE_PROJECT"
```

**No deploy here.** One `$SHA` so a mixed-revision state is unreachable by accident and step 15.8.i
reads as **one fact** rather than two.

> ⚠️ **If more than one `$SHA` ends up in play, the record at 15.8.j must carry BOTH.** The
> 2026-07-28 deploy had two (`20260728-094409` and `20260728-132637`) and recording one would have
> made the attribution wrong. A reader must be able to check every row.

Both images rebuild because **the worker executes the engine** (all five waves' pipeline code plus the
yield emitters) and **the api serves the read surfaces and is the image `tribunal-migrate` is pinned
to** in step 15.8.e.

---

### Step 15.8.d — Queue confirmed EMPTY

This is the cheapest step in the section and the one that makes step 15.8.h safe.

```sql
SELECT id, status, started_at, heartbeat_at, reclaim_count
  FROM tribunal.run
 WHERE status IN ('queued', 'running')
 ORDER BY created_at;
```

**Expect ZERO rows.**

- Any **`queued`** row would be claimed **the instant step 15.8.h deploys the worker** — not at the
  unpause. **STOP.**
- Any **`running`** row means another process is or was executing. **STOP** and identify it.

**HOW to run it without opening the database:** use the recipe already written in **§ Step 15.2.k
step 2** — a Cloud Build `--no-source` job as `nestor-run@` with `cloud-sql-proxy`, carrying the
result in the **EXIT STATUS** (that SA lacks `logging.logWriter`, so the build's stdout is LOST and a
green build is **not** an empty queue). **Cite it; do not restate it differently here** — two
procedures for one read is two sources of truth.

⛔ **Connect as `worker_user`, NEVER `app_user`.** `app_user` is tenant-scoped: without a bound
`app.tenant_id` it returns **zero rows**, which is indistinguishable from an empty queue and is **the
most expensive false negative in this document.**

**If a run must be stopped rather than waited out:** per `cancel_research`'s own docstring, **only
resolving the ROW stops a run.** Pausing is not cancelling — a paused worker's already-claimed run
ran 16 further minutes on 2026-07-27 — and cancellation is **cooperative**, checked at
`_CANCEL_CHECK_INTERVAL = 10.0`s between streamed events.

---

### Step 15.8.e — MIGRATE: three upgrades, three literal lines

```bash
gcloud run jobs update tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --image "${REGION}-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:${SHA}"
gcloud run jobs describe tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.template.spec.containers[0].image)'   # must echo :${SHA}
gcloud run jobs execute tribunal-migrate --region "$REGION" --project="$GOOGLE_PROJECT" --wait
```

**The repin is not optional and the `describe` is not a formality** — an unpinned Job is a **silent
no-op that exits 0 having applied nothing**: alembic connects, finds itself at head on the stale
revision set, and logs no upgrade line at all.

**THE PROOF IS THESE THREE LITERAL LINES, ALL THREE, IN THE JOB LOG:**

```
Running upgrade 0015 -> 0016
Running upgrade 0016 -> 0017
Running upgrade 0017 -> 0018
```

⛔ **`Container called exit(0)` is NOT proof of any of them.** The backend gate has **never** printed
such a line (`cloudbuild.test.yaml` runs alembic inside its own fixture but does not surface the
upgrade output — established in plan 15.3-06), and this repo has been burned by exactly that.
**None of 0016 or 0017 has ever touched a database**, so this is their first application, not a
re-run: seeing only `0015 -> 0016` means the Job ran on an image built before Wave 2.

**Then the schema read-backs — one per revision, because a head number is not a schema:**

```sql
-- 0016 (Wave 1) — grounding-redirect resolution
SELECT column_name, data_type, is_nullable FROM information_schema.columns
 WHERE table_schema='tribunal' AND table_name='source'
   AND column_name IN ('resolved_url','resolution_status');
-- expect two rows, both text, both nullable YES

-- 0017 (Wave 2) — claim attribution
SELECT column_name, is_nullable FROM information_schema.columns
 WHERE table_schema='tribunal' AND table_name='claim'
   AND column_name IN ('sub_question','corroboration_key','as_of');
-- expect three rows, all nullable YES

-- 0018 (Wave 5) — the yield tables, WITH their tenant isolation
SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class
 WHERE relname IN ('assignment_yield','workshop_round_yield');
-- expect both present, RLS ENABLED and FORCED
SELECT tablename, policyname FROM pg_policies
 WHERE tablename IN ('assignment_yield','workshop_round_yield');
-- expect a tenant policy on each

-- The TRIBUNAL head, from its OWN version table
SELECT version_num FROM tribunal.tribunal_alembic_version;   -- expect: 0018

-- The INTAKE head, from its OWN version table — NOT advanced this phase
SELECT version_num FROM public.alembic_version;              -- expect: 0013 (unchanged)
```

⛔ **A new table without ENABLE+FORCE RLS and its tenant policy is a cross-tenant leak.** 0018 creates
two; neither inherits anything.

**Read the INTAKE head to CONFIRM it did not move** — do not skip it because no `nestor-migrate` ran.
Two lines, two tables, two separate reads; **a single "migrations fine" is a record of neither.**

*Why the migration precedes the service images.* A worker carrying 15.8-09/10's yield writers deployed
**ahead of 0018** fails every yield write on a missing relation — and the whole phase exists to
collect that data. The reverse order is safe: between 15.8.e and 15.8.h the OLD image runs against the
NEW schema, and all three migrations are purely additive.

---

### Step 15.8.f — The audit chain across the migration

Re-run `verify_chain` on the **DEPLOYED** audit data after 0018 and require it **GREEN**.

0018 creates new tables and **alters no hashed column** — `audit/hash_chain.py::_payload_for_row`'s
eleven frozen fields are untouched — so a break here would be a surprise. That is exactly why it is
checked: the **EU AI Act Art. 12** obligation makes an **unproven** chain a hard **STOP**, not a note.
A RED chain is a stop with no sign-off.

---

### Step 15.8.g — Deploy `tribunal-api`

```bash
TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp IMAGE_TAG="$SHA" \
  tribunal/infrastructure/cloud-run/deploy-api.sh
```

> ⚠️ **THE `TRIBUNAL_ANTHROPIC_SECRET` OVERRIDE IS NOT OPTIONAL WHILE THE BURNER IS IN FORCE.** The
> committed default in the script is `Nestor_Claude2`, which is **not topped up**. **A redeploy
> without the override silently repoints at an empty key and the run walls mid-flight.** Drop the
> override only once `Nestor_Claude2` is funded — and then confirm by NAME in step 15.8.i.

> ⛔ **`--set-secrets` INSIDE THE DEPLOY SCRIPTS IS CORRECT AND MUST NOT BE "FIXED". READ BOTH RULES
> BEFORE TOUCHING EITHER.**
>
> | Artifact | Rule | Why |
> |---|---|---|
> | **Hand-typed `gcloud run services update` against a LIVE service** | use **`--update-secrets`**, never `--set-secrets` | `--set-secrets` **replaces** the whole set, so it silently drops every binding you did not restate. This is the Phase-12 lesson (`15.2-UAT.md`). |
> | **`deploy-api.sh` / `deploy-worker.sh`** | **`--set-secrets="${TRIBUNAL_SECRETS}"` — KEEP IT** | The scripts compose the **FULL** set in a variable **on purpose**, and their own comments say so, **precisely so an omission is a DEPLOY-TIME bug rather than a silent live regression.** |
>
> **Applying the hand-typed rule to the scripts would DROP BINDINGS.** The two rules govern two
> different artifacts and neither generalises to the other.

---

### Step 15.8.h — Deploy `tribunal-worker` LAST, then unpause

⛔ **Do not reach this step until 15.8.d proved the queue empty and 15.8.g deployed the api.**

Ship it paused, so the unpause stays a separate, deliberate act:

```bash
MIN_INSTANCES=0 TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp IMAGE_TAG="$SHA" \
  tribunal/infrastructure/cloud-run/deploy-worker.sh
```

⛔ **Repeated here, at the point of use: `--min-instances=0` does NOT stop the worker booting.** The
override governs **steady state**; the container still starts for the health check and the loop
**claims before it sleeps**. The override is necessary but **not sufficient** — step 15.8.d is what
makes this safe.

Then, and only then:

```bash
gcloud run services update tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --min-instances=1
```

Watch **one poll cycle** and confirm it **claims NOTHING**. The correct observation is an idle worker.
**If it claims something, STOP and report.**

*Note on the plain env.* `deploy-worker.sh` uses a whole-env `--set-env-vars`, which **replaces** the
plain environment with its committed list. That list carries **no `NESTOR_TRIBUNAL_*` tunable except
`UNCAPPED`** — so the Wave-4 validated configuration (which **is** the code defaults) survives this
deploy for free. **Never hand-type `--set-env-vars` against a live service outside this script.**

---

### Step 15.8.i — Read-backs, recorded VERBATIM

Not "looks right". Record the actual strings.

```bash
# (a) Both revision names at 100% traffic, digest-pinned — `@sha256:`, NEVER `:latest`.
for SVC in tribunal-worker tribunal-api; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(status.latestReadyRevisionName,status.traffic)'
done

# (b) CONFIRM-ONLY — the two services this deploy does NOT touch. Record the existing names.
for SVC in nestor-api nestor-frontend; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(status.latestReadyRevisionName)'
done

# (c) Secret bindings BY NAME only, never a value.
for SVC in tribunal-worker tribunal-api; do
  gcloud run services describe "$SVC" --region="$REGION" --project="$GOOGLE_PROJECT" \
    --format='value(spec.template.spec.containers[0].env)' | tr ',' '\n' \
    | grep -E 'ANTHROPIC_API_KEY|SERPAPI_API_KEY'
done
# expect Nestor_Claude_Temp (while the burner is in force) + Nestor_SERP on both.

# (d) The worker's plain env — READ the values back, do not assert them.
gcloud run services describe tribunal-worker --region "$REGION" --project="$GOOGLE_PROJECT" \
  --format='value(spec.template.spec.containers[0].env)' | tr ',' '\n' \
  | grep -E 'NESTOR_WORKER|ABORTED|NESTOR_TRIBUNAL'
```

**What (d) must show, and why each is a finding rather than a formality:**

- **`NESTOR_WORKER_STALE_MINUTES=60`** — **not** `525600`. § Step 15.2.j item 3 reverted it and the
  2026-07-28 deploy record confirms `60` live. At 60, a killed process's row is re-claimed after 60
  minutes of **heartbeat silence** (120 missed 30s heartbeats — the process is gone, not slow), up to
  `NESTOR_WORKER_MAX_RECLAIMS=2`. **Read the live value; do not assert it from this document.**
- **NO line matching `NESTOR_RUN_ABORTED_MARKER`** — it is read by no code and the whole-env replace
  drops it.
- ⭐ **The ABSENCE of every `NESTOR_TRIBUNAL_WORKSHOP_*` is a POSITIVE READ-BACK FINDING, and it must
  be written into the record as one.** The Wave-4 validated configuration **is the code defaults**
  (`_FLOOR_PER_QUESTION` = 5, `_CROSS_CUTTING_SLOTS` = 2, `_LOOP_MAX_ROUNDS` = 10,
  `_LOOP_MIN_ROUNDS` = 4). **If any one of them is set on the live worker, the measuring run is
  measuring a configuration nobody validated.** `NESTOR_TRIBUNAL_UNCAPPED=1` is expected and is the
  only tunable in the committed list.

```sql
-- (e) BOTH alembic heads, each from its OWN table. One does not imply the other.
SELECT version_num FROM tribunal.tribunal_alembic_version;   -- expect: 0018
SELECT version_num FROM public.alembic_version;              -- expect: 0013 (unchanged)
```

> ⛔ **BEFORE the run, settle the READ SURFACE (D-W5-18).** `assignment_yield` and
> `workshop_round_yield` have **no endpoint, no seam verb and no UI**, and the only credential-free DB
> path — the `--no-source` Cloud Build as `nestor-run@` — **lacks `roles/logging.logWriter`, so it can
> carry a boolean in its exit status and NOT a table of numbers.** Wave 5's own § 8 criterion would
> therefore be **UNREADABLE after the money is spent**. Plan 15.8-15 carries this as a **blocking
> pre-flight gate (Q-PRE-4)**: grant `roles/logging.logWriter` to `nestor-run@` and prove it with a
> `SELECT 1` build **whose output is actually visible**, *before* the trigger. This is the fourth time
> in two days that data was produced and unreadable — do not let it be the fifth.

---

### Step 15.8.j — THE DEPLOY RECORD

<!-- ⛔ PLAN 15.8-14 FILLS THIS STEP AND ONLY THIS STEP. Everything above and below is 15.8-12's -->
<!-- and is read-only at deploy time. Leave the skeleton in place; replace the blanks with real  -->
<!-- values during the deploy, not from memory afterwards.                                       -->

**EMPTY UNTIL THE DEPLOY. Fill every row with a real value — a blank row is an unanswered question.**

| Field | Value |
|---|---|
| Date · who ran it | |
| `$SHA` (or **both**, with what each carries) | |
| `tribunal-worker` revision (digest-pinned) | |
| `tribunal-api` revision (digest-pinned) | |
| `nestor-api` revision (**CONFIRM-ONLY** — not rebuilt) | |
| `nestor-frontend` revision (**CONFIRM-ONLY** — not rebuilt) | |
| TRIBUNAL head after (expect **0018**) | |
| ↳ literal line 1 observed | `Running upgrade 0015 -> 0016` — |
| ↳ literal line 2 observed | `Running upgrade 0016 -> 0017` — |
| ↳ literal line 3 observed | `Running upgrade 0017 -> 0018` — |
| INTAKE head (expect **0013**, unchanged) | |
| Engine gate: `collecting:` line · pass/fail counts · build id | |
| Gates gate: pass/deselect counts · build id | |
| Queue state before the worker deploy · HOW it was proven | |
| `verify_chain` result | |
| ANTHROPIC secret bound, BY NAME, per service | |

---

#### 15.8.j.1 — PREFLIGHT BLOCK (plan 15.8-14 Task 1) · 2026-08-05

**Nothing was built and nothing was deployed to produce this block.** Every line below came from a
command run in the main working tree or from `gcloud builds describe` build TEXT.

**(a) The tree.**

| Check | Command | Result |
|---|---|---|
| Branch | `git rev-parse --abbrev-ref HEAD` | `master` |
| HEAD | `git log --oneline -1` | `382b5b9 docs(phase-15.8): 15.8-08 complete — both deploy pre-conditions settled` |
| Clean | `git status --porcelain` | **empty** (whole tree — not even the previously-noted `?? .claude/`) |
| Clean, build surface | `git status --porcelain tribunal/ infra/ backend/ frontend/` | **empty** |
| Worktrees | `git worktree list` | one entry only: the main tree at `382b5b9 [master]`. **No stale worktree on disk.** |

**Staleness — asserted by MERGE-BASE, never by `rev-list --count`.** The count reads GREEN while
stale, because on a stale tree the stale ref usually *is* the merge-base.

| Base | `git merge-base HEAD <BASE>` | Equals `<BASE>`? | (`rev-list --count`, recorded but NOT the proof) |
|---|---|---|---|
| `8a6c59f` (phase code base, per 15.8-13) | `8a6c59fce0aa2a5c0db6af20fa4a40d53a0d79fd` | **YES** | 108 |
| `31a7f71` (last commit that reached a live service) | `31a7f71dd423a25ce0bb859c01e0f93388e57399` | **YES** | 384 |

**(b) POSITIVE-PRESENCE SENTINELS — 26 assertions, one or more per build plan. ZERO MISSES.**

| Plan | Assertion | Result |
|---|---|---|
| 15.8-01 | `_resolve_ceiling` in `pipeline/tribunal/question_grouping.py` | 2 matches |
| 15.8-01 | `test_the_merge_note_is_emitted_once_however_many_merges_the_ceiling_took` in `tests/test_question_grouping.py` | 1 match |
| 15.8-02 | `_dispatch_was_uniform` in `pipeline/tribunal/pipeline.py` | 3 matches |
| 15.8-02 | file `tests/test_pipeline_dispatch_clause.py` | present |
| 15.8-03 | `def _text_key` in `pipeline/tribunal/workshop_rank.py` | 1 match |
| 15.8-03 | `_sweep_langs` in `pipeline/tribunal/workshop_rank.py` | 3 matches |
| 15.8-04 | `def count_drops` in `pipeline/tribunal/workshop_register.py` | 1 match |
| 15.8-04 | `DROP_CLUSTERED_ONTO_LIVE` in `pipeline/tribunal/workshop.py` | 1 match |
| 15.8-05 | files `alembic/versions/0018_yield_instrumentation.py`, `runs/yield_records.py`, `db/models/assignment_yield.py`, `db/models/workshop_round_yield.py` | all 4 present |
| 15.8-05 | `down_revision` = `"0017"` in `0018_yield_instrumentation.py` | 1 match |
| 15.8-06 | file `15.8-06-DECISION-RECORD.md` | present |
| 15.8-07 | `EXPECTED_FILES` in `tribunal/cloudbuild.test-gates.yaml` | 9 matches |
| 15.8-08 | `_scrub_urls_in_value` in `audit/gcs_blob.py` | 8 matches |
| 15.8-08 | `gpt-5.6-sol` in `audit/cost_prices.json` | 3 matches |
| 15.8-09 | files `tests/test_pipeline_assignment_yield.py`, `tests/test_research_division_yield.py` | both present |
| 15.8-09 | `yield_records` referenced under `pipeline/tribunal/` | 4 files: `pipeline.py`, `research_division.py`, `workshop_loop.py`, `workshop_rank.py` |
| 15.8-09 | `parent_kind` referenced under `pipeline/tribunal/` | `pipeline.py` 1, `research_division.py` 13 |
| 15.8-10 | `new_entrants_top_n` in `pipeline/tribunal/workshop_loop.py` | 5 matches |
| 15.8-10 | file `tests/test_workshop_round_yield.py` | present |
| 15.8-10 | `yield_records` imported in `workshop_rank.py` | line 122, `record_round_safe` called at 1974 |
| 15.8-11 | file `tests/test_suite_hygiene.py` | present |
| 15.8-13 | `EXPECTED_FILES=43` in `tribunal/cloudbuild.test-engine.yaml` | 1 match |
| CR-01 restore | `ANGLE_YIELD_RESOLVABLE_SOURCES` in `pipeline/synthesis/steps.py` | 4 matches |
| CR-01 restore | `ANGLE_YIELD_RESOLVABLE_SOURCES` in `pipeline/tribunal/pipeline.py` | 3 matches |
| Wave 4 (15.7), carried | `_LOOP_MIN_ROUNDS` in `pipeline/tribunal/workshop_loop.py` | 4 matches |

**The two PAIRED assertions — both halves recorded, because a bare `== 0` is green on an empty file:**

| Paired assertion | Absence half | Presence half |
|---|---|---|
| D-W5-6 cause-filtered drop counter (15.8-10) | `grep -c 'len(register.get("drops")' workshop_rank.py` = **0** | `grep -c "count_drops" workshop_rank.py` = **5** |
| Wave 3 (15.6) discovery-rider cap | `max_size` in `attach_discovery_riders`' signature = **0** | `max_riders` **present** in that same signature: `def attach_discovery_riders(groups: Any, riders: Any, *, max_riders: Any = None)` |

**(c) THE TWO BLOCKING PRE-CONDITIONS — read from `15.8-PRECONDITIONS.md`, asserted as CONTENT.**

| Pre-condition | Gate grep | Occurrences | The settled line, verbatim | State |
|---|---|---|---|---|
| 1 — `gpt-5.6-sol` cost row | `grep -q "GPT-5.6-SOL RATE:"` | 1 (line 44) | `**GPT-5.6-SOL RATE: PUBLISHED-RATES ENTERED 2026-08-04**` | ✅ **SETTLED 2026-08-04** — legal state **`published-rates`** (the other legal state being a dated `no-published-rate` ruling). **Not nulls.** Operator ruling, in session. |
| 2 — audit-blob credential scan | `grep -q "REDACTION: PASS"` | 1 (line 155) | `**REDACTION: PASS**` | ✅ **SETTLED 2026-08-05 by the OPERATOR's own run** — 415 blobs, SCAN 1 query-param class `files: 0 / hits: 0`, positive control `urls-with-querystring: 1724` |

**The SerpApi rotation trigger did NOT fire.** SCAN 1 was a true zero against a corpus proven to
contain 1,724 query-string URLs, and all 58 SCAN-2 header-class hits decomposed to false positives
(`sk-` 0, real auth header names 0, the 4 `AIza` hits are base64 attachment substrings of length
84/54/214/58 where a real key is fixed-length). **`Nestor_SERP` was NOT rotated and did not need to
be. No rotation is scheduled before the build step.**

⚠ **What that scan does and does not retire (PRECONDITIONS FINDING 2):** V-01 is clean because the
exposure path **was never triggered in that run** — 0 of 415 blobs carry a non-empty
`error`/`exception`/`traceback` field, so `write_failure`'s path never fired. The scan retires the
**historical** question only; `_scrub_urls_in_value` (commit `5c04421`, shipping in this image) is
what protects future runs.

**`Nestor_Claude_Temp`: CLOSED-BY-DECISION (operator, 2026-08-03) — rotation DEFERRED TO GO-LIVE.**
It is a decision, not a gap, and it is recorded here once and nowhere else in this record as an open
item. It still receives its `TRIBUNAL_ANTHROPIC_SECRET` override on every deploy command below.

**(d) THE GATE — ⚠ A DEVIATION FROM THIS PLAN'S OWN TASK 1(d), AND THE REASON IS A REAL FINDING.**

Plan 15.8-14 Task 1(d) instructs: *"the gate is already paid — read 15.8-13's record, do not re-run
it."* **That criterion is stale, and following it would have shipped an ungated tree.** Two facts,
both re-derived here rather than recalled:

1. **15.8-13's own recorded gate was RED**, not green — build `b1397467` = **FAILURE**, `1 failed /
   1753 passed / 13 skipped` (FINDING-1, `assignment_identity` stringifying a hostile
   `corroboration_key` into a provenance column). Its summary states plainly *"the PHASE GATE is NOT
   GREEN"*. Read literally, Task 1(d) says **ABORT**.
2. That defect was closed afterwards by the review-fix cycle and the CR-01 restore — but **the last
   green engine gate, build `409ecddc` (SUCCESS, created `2026-08-04T13:40:32Z`), predates three
   `tribunal/` commits that are in HEAD**:

   ```
   3597e87 2026-08-04T22:51:52+02:00 feat(15.8-08): record published gpt-5.6-sol rates with full provenance
   5c04421 2026-08-04T22:52:09+02:00 fix(15.8-08): redact credentials in URL query params on BOTH audit blob halves
   ```

   `git diff --name-only 54a1544..HEAD -- tribunal/` returns exactly three files:
   `audit/cost_prices.json`, `audit/gcs_blob.py`, `tests/test_cost_serpapi.py`. **One is a production
   module, one is the cost table the audit record depends on, and one is a test file already
   registered in the engine gate's 43-path list.** 15.8-08's own summary says so in its own words:
   *"STILL OWED TO CLOUD BUILD (15.8-13): the full 43-file gate."* — a debt handed to a plan that had
   already run and could not have paid it.

**So the gates were re-run on HEAD before any spend**, which is also what **§ Step 15.8.b of this
same runbook instructs at deploy time**. This does not re-litigate 15.8-13; it executes 15.8-12's
procedure on the tree actually being built.

| Gate | Build id | Status (from `gcloud builds describe`, never a shell status or a pipe) | Tree |
|---|---|---|---|
| `cloudbuild.test-engine.yaml` | `3a7a580a-2e36-4a9c-9a35-956e165ea361` | **SUCCESS** | HEAD `382b5b9` |
| `cloudbuild.test-gates.yaml` | `f1322c33-1f10-4aef-b530-e396b24787d3` | **SUCCESS** | HEAD `382b5b9` |

Both reached a **terminal** status under polling, so neither `EXPIRED` nor `QUEUED` could have been
misread as a result. **Historical baselines, as builds to beat and not as values to compare
against:** engine `7c89be5c` = 1538 passed / 0 failed / 13 skipped at `collecting: 36 of 36`; gates
`2eae97e6` = 187 passed / 2 deselected; last pre-HEAD green engine `409ecddc` = 1777 passed / 0
failed / 13 skipped at `collecting: 43 of 43`.

**(e) THE DEPLOY SURFACE — computed, not inherited.**

```
$ git diff --name-only 31a7f71 HEAD | awk -F/ '{print $1}' | sort -u
.gitattributes
.gitignore
.planning
docs
infra
tribunal

$ git diff --stat 31a7f71..HEAD -- backend/ frontend/
[no output — the diff is empty]

$ git log --oneline 31a7f71..HEAD -- backend/ frontend/
[no output — no commit touched either directory]
```

Neither `backend` nor `frontend` appears. **The rebuild condition did not fire.** Resulting surface,
recorded as a decision with its evidence:

| Deployable | Decision | Evidence |
|---|---|---|
| `tribunal-worker` | **REBUILD + DEPLOY** | carries all five waves of engine code |
| `tribunal-api` | **REBUILD + DEPLOY** | serves the read surfaces over the changed schema; it is the image `tribunal-migrate` is pinned to |
| `tribunal-migrate` (Job) | **REPIN + EXECUTE** | three unpaid migrations (`0016`, `0017`, `0018`) |
| `nestor-api` | **CONFIRM-ONLY** | zero-byte diff under `backend/` since `31a7f71`, quoted above |
| `nestor-frontend` | **CONFIRM-ONLY** | zero-byte diff under `frontend/` since `31a7f71`, quoted above |
| `nestor-migrate` (Job) | **NOT EXECUTED** | newest `backend/app/db/alembic` revision is `0013_research_run_event_seq.py`; no revision added this phase. INTAKE head stays `0013`. |

**The one residual assumption, stated rather than hidden:** the live frontend image was built at
SHA A of the 2026-07-28 deploy (a tree at or before `31a7f71`). The evidence that it carries today's
`frontend/` is that `31a7f71` touched only `backend/`, plus § Step 15.2.k's own record line
confirming the run page shipped at SHA A. That is inference from two records, not a read of the
running bundle.

**(f) A CORRECTION TO THIS PLAN'S `user_setup`, recorded because it misdirects every future reader.**

Plan 15.8-14's `user_setup` states: *"The agent has no gcloud credentials, cannot submit a Cloud
Build, cannot execute a Cloud Run Job and cannot read Cloud SQL."* **That is FALSE.** `gcloud` is
authenticated as `tools@dotto.be` on `project-cb01b861-cb4a-438d-b9a`
(`gcloud config list` → `tools@dotto.be  project-cb01b861-cb4a-438d-b9a`), four Cloud Builds were
submitted by agents during this phase, and the audit bucket was read directly.

⛔ **That correction changes WHO CAN RUN a command. It changes NOTHING about who may CLEAR a gate.**
A `checkpoint:human-verify` guarding a production deploy is satisfied by a human reading the result
and signing off — **being able to run the command is not authority to satisfy the gate.** This
distinction was violated once in this phase (plan 15.8-08, pass token written then withdrawn, commit
`7c76636`) and the reversal is recorded in `15.8-PRECONDITIONS.md`'s PROCESS NOTE. Both halves are
recorded here deliberately.

---

### Step 15.8.k — THE ONE MEASURING RUN: what to read, and where

**ONE live run, on a FRESH intake, in the baseline brief domain. No A/B double-run.**

The comparison itself lives in
`.planning/phases/15.8-research-engine-redesign-yield-instrumentation-deploy-one-me/15.8-UAT.md` —
built before the run, from the recorded V-01 baseline, with every 15.8 cell empty. **Open it.** The
three judging rules are restated here so they survive even if it is not:

1. ⛔ **Judge the engine from the DELIVERED REPORT** — the `output` row with **`format='markdown'`** —
   **not the claim table and not the logs.** Three of V-01's own findings-doc claims were wrong
   because they judged a working stage from an intermediate artifact.
2. ⛔ **The verification stage works. DO NOT TOUCH IT.**
3. ⛔ **Do NOT tick `ENGINE-REDESIGN-SPEC.md` § 8's struck-through Wave 2 and Wave 3 rows.** Wave 2's
   mixed-group test **cannot be run** (D-W3-5 made mandate groups strict), and Wave 3 issues **9–15**
   calls, not 15. **Both waves shipped correctly; only the checklist is wrong.**

**Log lines worth grepping on this first run:**

- The WARNING a unit emits when it **returns non-empty lines and ZERO parsed claims**. **Expect
  ABSENT.** Its presence names a **NEW format deviation** — and that is **this phase working, not
  failing**: V-01 dropped 278 well-formed coffee claims on a literal `<TAB>` and logged nothing at all.
- The **fact-list retry** attempt/outcome warnings — attempted vs recovered.
- The **redirect resolver's** summary line: unique / resolved / unresolved.
- The **dispatch** line naming **how many streams a group went to**. Expect a group count in the
  **9–15** band (≤5 groups × 3 providers; `own` is out of the rotation by design).
- The **catch-up schedule** warning at `_catch_up_pairs`' `median <= 0` guard. **Expect ABSENT** — its
  absence is the evidence the schedule fired.

**The attribution sentence the operator owes** — the same shape § Step 15.2.k asks for, adapted to a
five-wave deploy:

> ⛔ **The honest sentence here is NOT "nothing changed."** It is a **named list of what did**:
> extraction repair, claim attribution, dispatch-by-topic plus the discovery bracket, the creative
> workshop loop, and the yield instrumentation — five waves, in one deploy, deliberately, by the
> 2026-07-29 ruling. **Write that list, and write which of them each surprising number could plausibly
> come from.**
>
> **If that sentence cannot be written honestly, the run is NOT STARTED.** It is not a formality: it
> is the only thing standing between "we know what changed" and bisecting five phases at forty-five
> dollars a run.

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
- [ ] Step 16.a — `nestor-api` image REBUILT via Cloud Build with the new research modules (`app/research/*`, `app/api/research_routes.py`, `app/db/models/research_runs.py`, six `research_*` mail templates) + service repointed (MANDATORY rebuild, not an env flip — the recurring deploy-gap, Pitfall 2/3); intake full suite green in Cloud Build against the fresh image
- [ ] Step 16.b — `nestor-migrate` Job executed `--wait` (alembic → 0011); `nestor.research_runs` + both RLS policies (`research_runs_space_isolation` / `research_runs_superadmin_all`) + FORCE RLS confirmed
- [ ] Step 16.c — `TRIBUNAL_SERVICE_URL` on `nestor-api` CONFIRMED read-only (already set + verified Phase 14; NOT re-set — Pitfall 4)
- [ ] Step 16.d — `NESTOR_WORKER_STALE_MINUTES=90` set on `tribunal-worker` (config-only env update on the unchanged worker image; above the measured 17–19 min max, T-16-16) + verified via describe; `NESTOR_TRIBUNAL_UNCAPPED` LEFT ON (D-02, T-16-17)
- [ ] Step 16.e — Anthropic credits topped up BEFORE the live run (MEMORY: LOW)
- [ ] Step 16.f — CHECKPOINT: live trigger on a DECOMPOSED smoke intake → dynamic progress panel + ticking cost → run `completed` (~17–19 min) → completion email; client login shows NO research surface (D-08/T-16-18); run id / cost / duration / `verify_chain` recorded; 14-HUMAN-UAT item 1 closed to PASS + results in 16-HUMAN-UAT.md
- [ ] Step 17.a — `tribunal-api` image REBUILT via Cloud Build FIRST (new `GET /api/runs/{run_id}/research-bundle` endpoint) + redeployed at `$SHA` (MANDATORY rebuild, not an env flip — the finalize path calls it; the recurring deploy-gap); `tribunal-worker` LEFT UNCHANGED (no worker rebuild); tribunal-api URL confirmed unchanged; optional Tribunal seam/bundle tests green in Cloud Build
- [ ] Step 17.b — `nestor-api` image REBUILT via Cloud Build (`app/research/bundle.py`, extended `run_task.py`/`research_routes.py`, `research_runs` chain/lock/bundle columns, migration 0012) + service repointed (MANDATORY rebuild, not an env flip — the recurring deploy-gap); intake full suite green in Cloud Build against the fresh image
- [ ] Step 17.c — `nestor-migrate` Job executed `--wait` (alembic → 0012); the three new nullable columns (`chain_status` / `chain_broken_at` / `bundle_key`) confirmed on `nestor.research_runs`; pure add-column so NO new policy/grant/index (inherits 0011 FORCE-RLS, 17-01 D)
- [ ] Step 17.d — `nestor-frontend` image REBUILT via Cloud Build (download button + locked/re-verify UI) + deployed; SAME `_API_BASE_URL`/`_FB_*` substitutions as Phase 12 (no URL re-wiring); NO `VITE_SUPABASE_*` (bundle guard green)
- [ ] Step 17.e — CONFIRM-ONLY read: `STORAGE_BUCKET` (the app bucket — bundle target, D-05) + `TRIBUNAL_SERVICE_URL` (the seam audience) present on `nestor-api`; NO new env/secret; explicitly NO `AUDIT_GCS_BUCKET` on the download path (D-05 — app bucket, never the audit bucket)
- [ ] Step 17.f — CHECKPOINT: top up Anthropic credits + complete the parked Phase-16 run FIRST (produces the real `completed` run); then on that run's card confirm chain state VERIFIED + Download → zip contains `report.md` + `research/*.md` + `sources.json` with NO rejected claims (D-01/D-03); `chain_status=verified` from the completion-path gate (optional scratch-tenant tamper → locked + Re-verify, D-06); a CLIENT login sees NO raw-output/research surface (REPORT-02); run id / zip contents / `verify_chain` recorded in 17-HUMAN-UAT.md
- [ ] Step 18.a — `nestor-api` image REBUILT via Cloud Build with the deliver/replace/report verbs (`POST /intakes/{id}/deliver` / `POST /intakes/{id}/report/replace` / `GET /intakes/{id}/report` + DeliverBody/ReportView + the report helpers) + service repointed (MANDATORY rebuild, not an env flip — the recurring deploy-gap); Tribunal images UNCHANGED
- [ ] Step 18.b — intake full suite green in Cloud Build against the fresh image (`test_report_delivery.py` + the extended `test_intake_cross_tenant.py` deliver/report denial cases); `gcloud builds submit . --config=cloudbuild.test.yaml`
- [ ] Step 18.c — `nestor-frontend` image REBUILT via Cloud Build (new `/intake/$id/report` route + regenerated `routeTree.gen.ts` + repaired `FinalReportBlock` + list "View report" CTA) + deployed; SAME `_API_BASE_URL`/`_FB_*` substitutions as Phase 12 (no URL re-wiring); NO `VITE_SUPABASE_*` (bundle guard green); NO `nestor-migrate` Job run (no migration landed)
- [ ] Step 18.d — CONFIRM-ONLY read: `APP_BASE_URL` + `NESTOR_ADMIN_EMAIL` + `RESEND_API_KEY` present on `nestor-api` (Phase-10 mail stack reused; the delivery mail refuse-sends if `APP_BASE_URL` unset); NO new env/secret; Resend-key rotation LEFT for Phase 20 CLOSE-02 (do NOT rotate mid-UAT)
- [ ] Step 18.e — CHECKPOINT: live UAT on an `in_research` smoke intake — stage a PDF (status stays `in_research`, CLIENT sees nothing — REPORT-02 blocking) → Deliver (status → `delivered`, mail arrives in the recipient's NL/FR/EN locale, CTA → `/intake/{id}/report`) → CLIENT sees "View report" + downloads/opens the PDF (REPORT-02) → Replace silent + re-notify (status stays `delivered`, newest file served — REPORT-03); intake id / recipients / locales / download result / PASS-FAIL per REPORT-01/02/03 recorded in 18-HUMAN-UAT.md
- [ ] Step 15.a — BOTH Tribunal images REBUILT via Cloud Build at ONE `$SHA` (`tribunal-worker` — C1 cost fix in `audited_llm_client`/`cost_table`/`cost_prices.json`/`writer.py`; `tribunal-api` — new `/verification` + enriched `/metrics` + citation numbering + `/audit/{audit_id}`) + redeployed worker-then-api at `$SHA` via the retargeted deploy scripts (Phase-14 lockdown preserved, not re-granted); tribunal-api URL confirmed UNCHANGED via `describe` WITHOUT a path (Pitfall 4). BOTH rebuild because the worker EMITS cost and the api SERVES the read surfaces
- [ ] Step 15.b — `tribunal-migrate` Job REPINNED to the `$SHA` image FIRST (image-pin lesson — else silent no-op) then executed `--wait` (alembic → **0011** in the **TRIBUNAL** schema, NOT the intake `nestor` line); log shows `Running upgrade 0010 -> 0011`; `audit_log.cache_creation_tokens` + `run.cost_pending`/`verification_summary` + `verification_verdict` FORCE-RLS table (tenant policy from 0003) + index confirmed; tribunal alembic head == 0011
- [ ] Step 15.c — `nestor-frontend` image REBUILT via Cloud Build (D15 feed + `VerificationReport` + `CitationPanel` + `AuditBodyPanel` + `getVerification`/`getAuditBody`/`getSource` + en/fr/nl i18n) + deployed; SAME `_API_BASE_URL`/`_FB_*` substitutions as Phase 12 (no URL re-wiring); NO `VITE_SUPABASE_*` (bundle guard green); NO `routeTree.gen.ts` regeneration (no new route — components mount on the existing `admin.pulse.intakes.$id` anchor)
- [ ] Step 15.d — VERIFY without printing secrets: Phase-15 pytest targets green in Cloud Build (tribunal `cloudbuild.test.yaml` cost/verification/citation/chain + intake `cloudbuild.test.yaml` seam denial trios + superadmin funnel happy path); **`verify_chain` re-run GREEN on the DEPLOYED audit data (SC5 — T-15-17 gate)**; recorded-run `/verification` + enriched `/metrics` return 200 for a superadmin and 404 for a client (16-D-08 / T-15-18); CONFIRM-ONLY read that `TRIBUNAL_SERVICE_URL` present on `nestor-api`; NO new env/secret — explicitly NO `SERPAPI_API_KEY` (that is Phase 15.2 / D10 — it HAS since landed in § Phase 15.2, Step 15.2.b)
- [ ] Step 15.e — (conditional) `nestor-api` REBUILT via Cloud Build ONLY if the live revision predates the Plan 15-04 proxy routes (commit `ac6102d`) — else SKIP; NO intake `nestor` migration this phase (0011 is the tribunal line), so NO `nestor-migrate` Job run
- [ ] Step 15.f — CHECKPOINT: operator RECORDED-RUN UAT (run-4cbb5311, NO live LLM run — Anthropic cap until 2026-08-01) per 15-UAT.md steps 1–5: D15 feed vs `replit view.png` + audit-body drill-down; verification report content; facts-only cost with pending state; every `[n]` resolves; CLIENT sees nothing (16-D-08); `verify_chain` green (SC5); V-02 operator sign-off recorded next to `docs/tribunal-run-reports/run-20260722-4cbb5311/`
- [ ] Step 15.1.a — CONFIRM-ONLY: **NO migration this phase**; tribunal alembic head stays **0011** (`run.verification_summary` JSONB and `verification_verdict.verdict` free TEXT with NO CHECK both already exist); the `tribunal-migrate` Job is **NOT** executed
- [ ] Step 15.1.b — CONFIRM-ONLY: **NO Cloud Run env change and NO new secret**; all ten `NESTOR_TRIBUNAL_GATE_*` / `_CLUSTER*` tunables read at import with production-safe defaults; the two rollback levers documented (`NESTOR_TRIBUNAL_CLUSTER=false` → exact-key bucketing; `NESTOR_TRIBUNAL_GROUP_VERIFY=false` → the rewired per-claim fallback, which still selects from the gate)
- [ ] Step 15.1.c — BOTH Tribunal images REBUILT via Cloud Build at ONE `$SHA` (`cloudbuild.worker.yaml` — the worker EXECUTES the gates and is the sole writer of `run.verification_summary`; `cloudbuild.api.yaml` — the api SERVES the accounting buckets / degradation text / `superseded` verdict class) + redeployed worker-then-api at that `$SHA` via the retargeted deploy scripts (Phase-14 lockdown preserved, not re-granted); **the specific built tag, never `:latest`**. NO frontend rebuild, NO `nestor-api` rebuild
- [ ] Step 15.1.d — VERIFY: `gcloud run services describe` shows a NEW revision on BOTH services with traffic 100% on it; tribunal-api URL confirmed UNCHANGED via `describe` WITHOUT a path (Pitfall 4); `/readyz` 200 with an identity token; **NO live research run triggered** (Anthropic cap until 2026-08-01)
- [ ] Step 15.1.e — DEFERRED (not a deploy-time gate): the Phase-15.1 browser checklist in `15.1-UAT.md` § Deferred Browser UAT is batched into the ONE combined Phase-15\* operator session after 2026-08-01, against a real live run, with no live-DB seeding — do NOT run it piecemeal
- [ ] Step 15.1.f — GAP CLOSURE (plans 15.1-11 … 15.1-16): BOTH Tribunal images REBUILT at ONE `$SHA` **FIRST**, then `tribunal-migrate` REPINNED to that `tribunal-api:$SHA` (image-pin lesson — the Job was found on a 2-deploy-old image; unpinned = silent no-op) and executed `--wait`; log shows **`Running upgrade 0011 -> 0012`** (an exit code is NOT proof); `superseded_note text` nullable confirmed AND `verification_verdict` still ENABLE+FORCE RLS with the `verification_verdict_tenant_isolation` policy intact (0012 issues no security DDL); TRIBUNAL head == **0012** in `tribunal.tribunal_alembic_version` (NOT the intake `nestor` line); ONLY THEN deploy worker-then-api at `$SHA` via the retargeted scripts (Phase-14 lockdown preserved). **Order build → migrate → deploy is load-bearing**: code ahead of the migration makes every verdict INSERT fail into Stage 7's swallow, producing a zero-verdict run that looks green. NO env change, NO new secret, NO `nestor-api` rebuild, NO live research run
- [ ] Step 15.1.g — GAP CLOSURE: `nestor-frontend` image REBUILT via Cloud Build at the SAME `$SHA` (plan 15.1-16's `verdicts.superseded` section + `superseded_note` caveat fallback in `VerificationReport.tsx`, `lib/api/research.ts`, en/fr/nl `intake.json`) + deployed `--port 8080`; SAME `_API_BASE_URL`/`_FB_*` substitutions as Phase 12 (no URL re-wiring); NO `VITE_SUPABASE_*` (bundle guard green); NO `routeTree.gen.ts` regeneration (no new route); `npm ci` not `npm install` (the lockfile IS committed). **Mandatory this pass** — without it the newly-populated verdict class exists only in the JSON and the operator still cannot see it
- [ ] Step 15.2.a — PREFLIGHT (read-only): `git status --porcelain` EMPTY + HEAD SHA recorded + a positive on-disk assertion for one artifact per wave (0013 migration, `reliability.py`, `stage_feed.py`, `facts.py`, `anchors.py`, `workshop.py`, `workshop_rank.py`, `own_researcher.py`, `serpapi.py`, `test_engine_e2e_stubbed.py`, `cloudbuild.test-engine.yaml`, `completed_degraded` in `ResearchRunProgress.tsx`) — **Cloud Build ships the tree you submit; a stale worktree deploys code that is not this phase**; the SIX gates green on THAT tree with the `collecting:` block READ (an `ls … || true` config goes green having run nothing); live wiring captured WITHOUT printing values (both Tribunal services' mounted ANTHROPIC secret NAME + revision names + the path-less tribunal-api URL, Pitfall 4)
- [ ] Step 15.2.b — `Nestor_SERP` **already existed since 2026-06-03 with a valid seeded value — do NOT create a second secret**; the only missing piece was IAM, so: resource-scoped `secretAccessor` granted to `tribunal-run` ONLY (never `nestor-run`, never project-wide), verified with METADATA reads only (`versions list` + `get-iam-policy` showing exactly one member); tier **read live, not chosen** — Starter Plan (`starter_v4`), $25/mo · 1,000/month · 200/hour ⇒ D-16 unit price $0.025/search; **no price hardcoded anywhere**, `fetch_plan()` reads `/account.json` live at run start (D-16); never `curl` that endpoint unfiltered — it echoes the key back
- [ ] Step 15.2.b-bis — `nestor-run@` granted `secretAccessor` on `Nestor_Claude2` (previously granted to `tribunal-run@` only; required by the 2026-07-27 repoint of `nestor-api`)
- [ ] Step 15.2.c — BOTH Tribunal images BUILT via Cloud Build at ONE `$SHA` (`cloudbuild.worker.yaml` — the whole engine core; `cloudbuild.api.yaml` — the status predicate + feed read surface). **BUILD ONLY — deploy is 15.2.e.** Order build → migrate → deploy is LOAD-BEARING: a worker running ahead of 0013 fails every `certainty`/`found_by`/`provider_quality`/`research_gap` write into a swallowed `except` and the run completes looking clean
- [ ] Step 15.2.d — `tribunal-migrate` Job REPINNED to the `$SHA` `tribunal-api` image FIRST (image-pin lesson — unpinned = silent no-op) + repin CONFIRMED via `describe`, then executed `--wait`; log shows the literal **`Running upgrade 0012 -> 0013`** (**`Container called exit(0)` is NOT proof**); schema confirmed read-only: `claim.certainty` + `claim.found_by text[]` + `claim_source.provider_quality` all nullable, table `tribunal.research_gap` with **ENABLE+FORCE RLS + its tenant-isolation policy + index (new table — NOT inherited, a table without them is a cross-tenant leak)**, `ck_run_status` accepting `completed_degraded`/`parked`, and TRIBUNAL head == **0013** in `tribunal.tribunal_alembic_version` (NOT the intake `nestor` line, which stays at 0012)
- [ ] Step 15.2.e — `tribunal-worker` then `tribunal-api` deployed at `IMAGE_TAG=$SHA` via the retargeted scripts (Phase-14 lockdown preserved, not re-granted); **`SERPAPI_API_KEY` bound on BOTH** from `Nestor_SERP` (existence-probed — a missing secret WARNS and continues as a clean 3-stream `completed_degraded` run rather than failing the deploy); **ANTHROPIC secret PINNED to the committed default `Nestor_Claude2`, NOT self-healed** — self-healing was inverted on 2026-07-27 after it was proven to ratify the very drift it was meant to prevent (2026-07-21 manual switch to Claude2 → 2026-07-25 script deploy adopted the reverted live value → all three services verified back on `Nestor_Claude`); the live value is now read only to print a divergence notice, and `nestor-api` is repointed to Claude2 as well; binding confirmed by secret NAME only, never a value; digest-pin proof (`@sha256:`, never `:latest`)
- [ ] Step 15.2.f — `nestor-api` image REBUILT via Cloud Build (`app/research/run_status.py` + `run_task.py` D-12 status vocabulary, the `POST /{intake_id}/research/resume` route, `render_research_parked`) + service repointed (MANDATORY rebuild, not an env flip — the recurring deploy-gap); ordered AFTER the Tribunal services (the Resume route calls the seam); **NO intake `nestor` migration and NO `nestor-migrate` Job run** (F3 — `research_runs.status` has no CHECK; intake head stays 0012); **NO new env/secret** — Phase-10 mail stack reused, `APP_BASE_URL` confirmed present or the parked mail refuse-sends; **`SERPAPI_API_KEY` NEVER bound here** (INTAKE-05)
- [ ] Step 15.2.g — `nestor-frontend` image REBUILT via Cloud Build at the SAME `$SHA` (plan 15.2-09's `RESEARCH_TERMINAL` set + `lib/api/research.ts` + en/fr/nl `intake.json`) + deployed `--port 8080`; SAME `_API_BASE_URL`/`_FB_*` substitutions as Phase 12 (no URL re-wiring); NO `VITE_SUPABASE_*` (bundle guard green); NO `routeTree.gen.ts` regeneration (no new route); `npm ci` not `npm install` (the lockfile IS committed; the CLAUDE.md note is stale/bun). **Mandatory** — the terminal-status set is COMPILED INTO THE BUNDLE, so without it a `completed_degraded` run spins forever in the browser while every backend surface is correct (the Phase-18 stale-SPA lesson)
- [ ] Step 15.2.h — VERIFY without printing secrets: the six gates re-run against the deployed tree (`collecting:` block read); **`verify_chain` GREEN on the DEPLOYED audit data — a RED chain is a STOP, no sign-off** (EU AI Act Art. 12, deadline 2026-08-02); secret-binding confirm by NAME; `/readyz` 200 on `tribunal-api` with an identity token against the path-less URL (Pitfall 4); `bash backend/scripts/ci_no_run_research.sh` exit 0 (INTAKE-05 — SerpApi lives in `tribunal/`, which the guard deliberately does not scan)
- [ ] Step 15.2.j — GAP CLOSURE (D-E, plan 15.2-20): **`tribunal-worker` stays PAUSED until this whole step is done** — unpausing first re-executes the still-`running` run `d6bb3aae` at full cost. Order is load-bearing: (1) `tribunal-migrate` REPINNED to the `$SHA` api image then executed `--wait`, log shows the literal **`Running upgrade 0013 -> 0014`** (an exit code is NOT proof), `run.heartbeat_at` nullable + `run.reclaim_count` NOT NULL default 0 confirmed, TRIBUNAL head == **0014**; (2) the new `tribunal-worker` image deployed via the retargeted script — never before the migration, because the new `CLAIM_SQL`/`REAP_SQL` reference both columns and would poll-crash; (3) `--update-env-vars NESTOR_WORKER_STALE_MINUTES=60` (safe now that the clock is heartbeat SILENCE, not run duration — 120 missed 30s heartbeats); (4) `--remove-env-vars NESTOR_RUN_ABORTED_MARKER` (read by no code — a human annotation); (5) ONLY THEN `--min-instances=1`. A full redeploy through `deploy-worker.sh` performs (3) and (4) by itself because its whole-env flag replaces the plain env — **verify by `describe`, never assume**; never hand-type that flag against a live service (Phase-12 lesson: it drops every binding not restated). Run `d6bb3aae` is NOT resolved here — that is 15.2-25/26. **SUPERSEDED TAIL:** when deploying the gap phase as a whole, execute § Step 15.2.k instead — 15.2.j items 1-4 are 15.2.k steps 3-4, and the unpause MOVES to 15.2.k step 7, after the cancel
- [ ] Step 15.2.k — GAP-PHASE DEPLOY (plans 15.2-20…26 **AND 15.3-01…09** — 15.3 has no deploy of its own, it RIDES this one per operator decision D-03), ONE ordered procedure — ⛔ **EXECUTE IN THE CORRECTED ORDER `0→1→2→3→5→6→4→7→8→9→10`: the worker (4) is the LAST deployable, after the run is resolved (6). The as-written order below deploys it at (4) and that CAUSED the 2026-07-28 incident — a deploy BOOTS the container and `runs/worker.py` CLAIMS FIRST, SLEEPS LAST, so `--min-instances=0` does not save you; an empty queue is the only protection**: (0) stale-base guard on disk, one artifact per gap plan PLUS the five 15.3 artifacts (both migrations, the run route, the status card, the actions), then the gates — the engine gate ASSERTS its collected count, now **`collecting: 30 of 30 expected files`** (27→30 via plans 15.3-01/02/03; READ THE NUMBER OUT OF `EXPECTED_FILES` in `tribunal/cloudbuild.test-engine.yaml`, never out of memory — the DB-bound skips say in words that a skip is not a pass), plus the backend gate `pytest tests -m integration` and the three FRONTEND gates (`npm ci` → `node scripts/i18n-audit.mjs` → `npx tsc --noEmit` → `npm run build`; the i18n audit is HARD on en/nl/fr and its CHECK D advisories are pre-existing); (1) all FOUR images BUILT at ONE `$SHA` (worker/api/backend/frontend — every one a REBUILD, the Stop button AND the whole run page are COMPILED INTO THE BUNDLE; 15.3-08 DOES add a new route and its regenerated `routeTree.gen.ts` is already committed, superseding the old "no route added" note); (2) **queue confirmed EMPTY** via `SELECT … FROM tribunal.run WHERE status IN ('queued','running')` — expect EXACTLY the one row `d6bb3aae`, and a `queued` row is a STOP because **step 4's deploy** would claim it on boot (not step 7) — read as `worker_user`, never `app_user`, or RLS returns a falsely empty queue; (3) **BOTH migration lines, each with its OWN literal proof and its OWN version table** — (3a) `tribunal-migrate` REPINNED then executed, proven by **`Running upgrade 0013 -> 0014`** AND **`Running upgrade 0014 -> 0015`** (the second is 15.3's `run_event` table; seeing only the first means a pre-15.3 image), and (3b) `nestor-migrate` REPINNED to the `$SHA` backend image then executed, proven by **`Running upgrade 0012 -> 0013`** (`research_runs.event_seq`) — `exit(0)` is NEVER proof for either, and do NOT hunt that line in the preflight backend gate: `cloudbuild.test.yaml` runs alembic but does not surface its upgrade output (established in 15.3-06), so confirm 3b additionally via `information_schema.columns` (bigint · nullable · no default) and `public.alembic_version` = 0013; each migration BEFORE its own service image, or the worker poll-crashes on `UndefinedColumnError`/missing `run_event` and `nestor-api` fails every cursor read; (4) `deploy-worker.sh` at `IMAGE_TAG=$SHA` **WITH `TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp`** (the committed default `Nestor_Claude2` is NOT topped up — a redeploy without the override silently repoints at an empty key), which also performs the D-E env revert by whole-env replacement — VERIFY by describe, never assume; (5) `tribunal-api` → `nestor-api` → frontend (the Stop button calls a nestor-api route that calls a tribunal-api endpoint; a frontend shipped first 404s); (6) **run `d6bb3aae` CANCELLED THROUGH THE UI BEFORE the unpause** — D-D's acceptance demo AND a hard safety step: that row predates 0014 so `heartbeat_at` is NULL, `COALESCE` falls back to a stale `started_at` and `reclaim_count`=0, so restoring `NESTOR_WORKER_STALE_MINUTES=60` makes it claimable again; D-L verified in the same click (the elapsed clock must NOT reset on refresh); (7) ONLY THEN `--min-instances=1`, and the worker must claim NOTHING; (8) read-backs recorded VERBATIM (threshold=60 not 525600, `NESTOR_RUN_ABORTED_MARKER` ABSENT, `NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol`, secret names only, four revision names, `d6bb3aae` status, and **BOTH alembic heads from their own tables — TRIBUNAL 0015, INTAKE 0013**); (9) the `serviceAccountTokenCreator` grant on `nestor-run@` REVOKED or its retention RECORDED as a decision — undecided is not an answer; (10) **the COMBINED DEPLOY RECORD at the end of § Step 15.2.k filled in** — the `$SHA`(s), four revisions, both heads with their literal upgrade lines (**as executed 2026-07-28 this was TWO SHAs, not one: `20260728-094409` for worker/api/frontend and `20260728-132637` for `nestor-api` — record both or the attribution is wrong**), and the TWO separately labelled change lists (15.2 gap fixes by defect id · 15.3 observability changes) plus the operator-affirmed no-engine-behaviour-change sentence. That split is the whole attribution mechanism D-03 asks for, and **if that sentence cannot honestly be written, the deploy STOPS**. Plus the first-live-run log checklist: `stage_enter`/`stage_exit`/`run_stages_complete` (D-F — never diagnose from silence or CPU again) and the two `collect_provider_facts` honour lines (how D-M gets MEASURED). **NO V-01 in this session** — the next live run is a separate, operator-scheduled event on a FRESH intake
- [ ] Step 15.2.i — PARK: **Anthropic monthly cap resets 2026-08-01**; NO live LLM run triggered before then — the park is NOT a failure. Then V-01 (ONE live run on a FRESH intake in the baseline brief domain, recorded in `docs/tribunal-run-reports/V-01-COMPARISON.md` beside run-20260722-4cbb5311 — **no A/B double-run**, the `comparison_id` harness stays unused), V-02 (the 16-item checklist in `15.2-UAT.md`, each item pass/fail with NAMED evidence, ending in a dated operator sign-off), then V-03 as a **SEPARATE commit after sign-off** removing only unreferenced old-path code (`claim_distiller`/D-15, `detect_explicit_questions` and `extract_and_persist_citations` all SURVIVE with green tests). Batched into the same August session: the deferred Phase-15 populated-surface browser UAT (SC1-SC4) and the Phase-15.1 verdict/gate surfaces
- [ ] Step 15.8.a — PREFLIGHT / **STALE-BASE ABORT GATE**: `git status --porcelain` EMPTY + HEAD SHA recorded + **one positive on-disk sentinel per plan 15.8-01 … 15.8-10**, each a NEW file or NEW symbol from that plan's merged SUMMARY (a pre-existing path proves nothing; `rev-list --count BASE..HEAD == 0` reads GREEN while stale — the merge-base is the discriminator; the trap is 15/15 in this repo). **Absence of ANY sentinel ABORTS before the image build**, not after. ⛔ **NO ARTEFACT SATISFIES TWO GATES (WR-05):** 15.8-08's sentinel is the code symbol `_scrub_urls_in_value` in `audit/gcs_blob.py`, deliberately **not** `15.8-PRECONDITIONS.md` — that file is the pre-condition record below, and using it for both let a force-added empty file clear the credential gate as a side effect of clearing a staleness row. Plus a **content** check (`grep`, never `ls`) over `15.8-PRECONDITIONS.md` for the literal tokens `REDACTION: PASS` and `GPT-5.6-SOL RATE:`, confirming BOTH blocking pre-conditions settled — the `gpt-5.6-sol` cost row (nulls are NOT an option: `_rate()` turns null into `Decimal("0")` and clears `cost_pending` on a fabricated $0.00) and the audit-blob redaction check (**BLOCKING** — the SerpApi key rides in a URL QUERY PARAMETER, so an unredacted body freezes a live credential under 7-year retention). `Nestor_Claude_Temp` rotation is **DEFERRED TO GO-LIVE (operator, 2026-08-03)** — a decision, NOT a gap
- [ ] Step 15.8.b — GATES read from build **TEXT**: `cloudbuild.test-engine.yaml` + `cloudbuild.test-gates.yaml` submitted, statuses read via `gcloud builds describe` / `builds list` — **never a shell exit code** (`| tail` returns the PIPE's status, so a FAILED build reports exit 0) — and **`EXPIRED` named as NOT a result** (identical on sight to `QUEUED`). The engine gate's printed `collecting: N of N` must equal `EXPECTED_FILES` **READ OUT OF THE COMMITTED CONFIG at that moment**, never a number quoted in this runbook. Baselines to BEAT with their build ids: engine `7c89be5c` = 1538/0/13 at `collecting: 36 of 36`; gates `2eae97e6` = 187 passed / 2 deselected. **A flat gates count is a REGRESSION PASS over the wave-1/wave-2 edits; a RED is a signal about those edits, NOT a config to tune.** A count that did not rise must be EXPLAINED. **No backend gate and no frontend gate** — `backend/`/`frontend/` unchanged
- [ ] Step 15.8.c — BOTH Tribunal images BUILT at ONE `$SHA` (`cloudbuild.worker.yaml` — the whole five-wave engine + the yield emitters; `cloudbuild.api.yaml` — the read surfaces AND the image `tribunal-migrate` pins to). **BUILD ONLY**; if more than one SHA ends up in play, 15.8.j records BOTH (recording one made the 2026-07-28 attribution wrong)
- [ ] Step 15.8.d — **QUEUE PROVEN EMPTY** — `SELECT … FROM tribunal.run WHERE status IN ('queued','running')`, **expect ZERO rows**, read as `worker_user` and **never `app_user`** (unbound tenant → zero rows, indistinguishable from an empty queue: the most expensive false negative in this document). Recipe CITED from § Step 15.2.k step 2, not restated (`nestor-run@` lacks `logging.logWriter`, so the result rides in the EXIT STATUS). Only resolving the ROW stops a run — pausing is not cancelling, and cancellation is cooperative at `_CANCEL_CHECK_INTERVAL = 10.0`s
- [ ] Step 15.8.e — **MIGRATE: THREE upgrades, THREE literal lines.** `tribunal-migrate` REPINNED to the `$SHA` api image + repin CONFIRMED by `describe` (unpinned = silent no-op that exits 0 having applied nothing), then executed `--wait`. Proof is **`Running upgrade 0015 -> 0016`** AND **`Running upgrade 0016 -> 0017`** AND **`Running upgrade 0017 -> 0018`** — **`Container called exit(0)` is NOT proof of any of them** (the backend gate has never printed such a line; none of 0016 or 0017 has ever touched a database). Read-backs: `source.resolved_url`/`resolution_status` nullable text (0016); `claim.sub_question`/`corroboration_key`/`as_of` nullable (0017); `assignment_yield` + `workshop_round_yield` present with **ENABLE+FORCE RLS + tenant policies** (0018 — a new table without them is a cross-tenant leak); TRIBUNAL head == **0018**; **INTAKE head READ to confirm it stayed 0013**
- [ ] Step 15.8.f — `verify_chain` **GREEN on the DEPLOYED audit data** after 0018 (0018 alters no hashed column, but EU AI Act Art. 12 makes an unproven chain a hard STOP, not a note)
- [ ] Step 15.8.g — `tribunal-api` deployed via `deploy-api.sh` at `IMAGE_TAG=$SHA` **WITH `TRIBUNAL_ANTHROPIC_SECRET=Nestor_Claude_Temp`** (the committed default `Nestor_Claude2` is not topped up — a redeploy without the override silently repoints at an empty key). ⛔ **`--set-secrets` in the SCRIPTS is CORRECT and must NOT be "fixed"**: the `--update-secrets`-not-`--set-secrets` rule governs **hand-typed `gcloud run services update`** against a live service; the scripts compose the FULL set in a variable on purpose so an omission is a deploy-time bug rather than a silent live regression — applying the hand-typed rule to them would DROP bindings
- [ ] Step 15.8.h — `tribunal-worker` deployed **LAST**, after 15.8.d and 15.8.g, at `MIN_INSTANCES=0` + the burner override + `IMAGE_TAG=$SHA`, then a SEPARATE deliberate `--min-instances=1`. **`--min-instances=0` does NOT stop the boot** — the loop CLAIMS FIRST and SLEEPS LAST, so the override governs steady state only and **an empty queue is the only protection** (2026-07-28: 08:22:57Z the deploy claimed `d6bb3aae` and burned ~15 min of paid pipeline). After the unpause, watch one poll cycle and confirm it claims NOTHING
- [ ] Step 15.8.i — READ-BACKS recorded **VERBATIM**: both Tribunal revisions at 100% traffic, digest-pinned (`@sha256:`, never `:latest`); `nestor-api` + `nestor-frontend` **CONFIRM-ONLY** revision names (not rebuilt — the empty diff IS the evidence); secret bindings **BY NAME only**; `NESTOR_WORKER_STALE_MINUTES` **read live** (expect 60, not 525600) with `NESTOR_RUN_ABORTED_MARKER` ABSENT; ⭐ **the ABSENCE of every `NESTOR_TRIBUNAL_WORKSHOP_*` recorded as a POSITIVE finding** (the Wave-4 validated config IS the code defaults — if one is set, the measuring run measures a config nobody validated); BOTH alembic heads from their own tables (TRIBUNAL **0018**, INTAKE **0013**). ⛔ **And settle the READ SURFACE first (D-W5-18): the yield tables have NO endpoint, no seam verb and no UI**, and the credential-free DB path lacks `logging.logWriter` — so Wave 5's own § 8 criterion is UNREADABLE after the spend unless 15.8-15's blocking pre-flight gate Q-PRE-4 is paid
- [ ] Step 15.8.j — **THE DEPLOY RECORD** — owned by plan **15.8-14** and by no one else: date/who, the `$SHA`(s) with what each carries, both Tribunal revisions, both CONFIRM-ONLY revisions, TRIBUNAL head 0018 with **all three literal upgrade lines quoted**, INTAKE head 0013 unchanged, both gate results with their build ids, the queue state and how it was proven, `verify_chain`, and the ANTHROPIC secret each service binds by name
- [ ] Step 15.8.k — **THE ONE MEASURING RUN** — ONE live run on a FRESH intake in the baseline brief domain, **no A/B double-run**, compared in `.planning/phases/15.8-*/15.8-UAT.md`. **Judge from the DELIVERED REPORT** (the `output` row, `format='markdown'`), never the claim table and never the logs; **the verification stage works — do not touch it**; **do NOT tick § 8's struck-through Wave 2 and Wave 3 rows** (Wave 2's mixed-group test cannot be run; Wave 3 issues 9–15 calls, not 15 — both waves shipped correctly, only the checklist is wrong). Grep the ZERO-parsed-claims WARNING (expect ABSENT — its presence names a NEW format deviation and is this phase WORKING), the fact-list retry warnings, the redirect resolver summary, the dispatch stream-count line, and the catch-up `median <= 0` warning (expect ABSENT). ⛔ **The attribution sentence is a NAMED LIST of the five waves, not "nothing changed" — and if it cannot be written honestly, the run is NOT STARTED**
