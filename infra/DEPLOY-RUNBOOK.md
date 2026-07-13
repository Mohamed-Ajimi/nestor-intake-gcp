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

## Summary checklist

- [ ] Step 1 — two secrets created + resource-scoped secretAccessor to the runtime SA (manual, per drift)
- [ ] Step 2 — key VALUES added as secret versions, never echoed/logged/committed
- [ ] Step 3 — image rebuilt via Cloud Build with `anthropic` + `openai`, service repointed
- [ ] Step 4 — `min-instances=0` + CPU always-allocated + native key injection
- [ ] Step 5 — wiring verified without printing any secret value
- [ ] Step 8.1 — backend image rebuilt via Cloud Build with the new `skill-runs/stream` + full-run endpoints, service repointed (D-10 UAT)
- [ ] Step 8.2 — `gcloud run services update nestor-api … --timeout=900` applied live (D-07; the `main.tf` edit alone is inert per drift)
- [ ] Step 8.3 — live verify: console Request timeout reads 900s AND streamed events arrive at ~2s cadence (no ~300s drop)
- [ ] Drift logged: reconcile via `terraform import` (or keep manual) BEFORE Phase 12 cutover
