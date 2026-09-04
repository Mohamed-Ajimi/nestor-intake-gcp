# Cloud Run Deploy Runbook

Manual runbook for deploying or redeploying the Nestor Pulse SDK services
to Cloud Run in `europe-west1`. **This is the primary deployment method
until WIF (Workload Identity Federation) lands** — see
`.continue-here.md § deferred_human_actions item 2`.

Plan: 01-10.5 Task 5.

> **Dev feedback window:** To open the multi-user dev round (SQL ALWAYS,
> schema push, deploy, clarify smoke, tester onboarding, window close), see
> `infrastructure/ops/dev-feedback-window.md`.

---

## Services

| Service | URL | Purpose |
|---------|-----|---------|
| `nestor-pulse-api` | `https://nestor-pulse-api-ybkr7metoq-ew.a.run.app` | SDK API (JWT-gated; health probes exempt) |
| `nestor-pulse-worker` | `https://nestor-pulse-worker-ybkr7metoq-ew.a.run.app` | Async poll worker (always-on, SKIP LOCKED) |

---

## Prerequisites

### 1. gcloud authentication + project

```bash
gcloud auth login
gcloud config set project project-cb01b861-cb4a-438d-b9a
gcloud auth application-default login
```

Verify:
```bash
gcloud config get-value project        # -> project-cb01b861-cb4a-438d-b9a
gcloud auth list --filter=status:ACTIVE --format='value(account)'  # -> tools@dotto.be
```

### 2. Cloud SQL must be RUNNABLE

The `nestor-prod-pg` Cloud SQL instance is paused between sessions to save
cost (see `memory/feedback_sql_pause_pattern.md`). Resume it before deploying
or running smoke tests that hit `/readyz`:

```bash
gcloud sql instances patch nestor-prod-pg \
  --activation-policy=ALWAYS \
  --project=project-cb01b861-cb4a-438d-b9a
# Wait ~30s for the instance to become RUNNABLE
gcloud sql instances describe nestor-prod-pg \
  --project=project-cb01b861-cb4a-438d-b9a \
  --format='value(state)'
# Expected: RUNNABLE
```

---

## Steps 1–7: Full deploy

### Step 1: Artifact Registry (idempotent)

```bash
bash infrastructure/cloud-run/artifact-registry-create.sh
```

Creates `europe-west1-docker.pkg.dev/project-cb01b861-cb4a-438d-b9a/nestor-pulse`
if it doesn't exist. No-op if already present.

### Step 2: Build + push images

```bash
bash infrastructure/cloud-run/build-and-push.sh
```

- Builds `api` and `worker` images via Cloud Build (server-side; no local
  Docker daemon required).
- Tags each with `GIT_SHA:latest` and writes `.last-build.env` for Steps 3+4.
- Takes ~3–5 minutes per image (first run; cached on subsequent runs).

### Step 3: Deploy the API service

```bash
bash infrastructure/cloud-run/deploy-api.sh
```

- Deploys `nestor-pulse-api` with `--no-allow-unauthenticated` at the Cloud Run
  level (`deploy-api.sh:157`) — Cloud Run itself rejects anonymous invocations, and
  FastAPI adds its own JWT gate on top. Cloud Run's built-in startup/liveness
  probes are internal to the service and unaffected by that IAM check; `/healthz`
  and `/readyz` are exempt from the FastAPI JWT gate but still sit behind Cloud
  Run's IAM check.
- Cloud SQL socket: `/cloudsql/project-cb01b861-cb4a-438d-b9a:europe-west1:nestor-prod-pg`
- Secrets mounted: `DATABASE_URL`, `ANTHROPIC_API_KEY` (from `Nestor_Claude`),
  `GOOGLE_API_KEY` (from `Nestor_Gemini`), `OPENAI_API_KEY` (from `Nestor_OpenAI`),
  `IDENTITY_PLATFORM_PROJECT_ID`, `IDENTITY_PLATFORM_SMOKE_USER_PW`,
  `IDENTITY_PLATFORM_WEB_API_KEY` (Plan 01-17; served via GET /api/auth/config to
  the Login page — never hardcoded in source control).
  The `Nestor_*` secrets are canonical for provider keys — rotate keys by adding
  a new version there (see `nestor_pulse_sdk/secrets_bootstrap.py`); the
  legacy-named provider-key secrets are frozen.

**Deploy-time env flags (Plan 01-17):**

| Variable | Purpose | Default |
|---|---|---|
| `IDENTITY_PLATFORM_WEB_API_KEY` | Public browser key for Identity Platform signInWithPassword; served by `/api/auth/config` to Login.html | (empty — set via Secret Manager) |
| `NESTOR_TRIBUNAL_UNCAPPED` | D-15 dev-round posture: set to `"1"` to make the per-run cost governor never block (over_budget always returns False). Audit cost_usd still recorded. Unset to re-enable the ceiling. **No aggregate/daily ceiling; no global kill-switch.** | (unset = capped at DEFAULT_MAX_BUDGET_USD) |

### Step 4: Deploy the worker service

```bash
bash infrastructure/cloud-run/deploy-worker.sh
```

- Deploys `nestor-pulse-worker` with `min-instances=1 max-instances=1`
  (D-09 always-on single worker for SKIP LOCKED claim latency).
- `--no-cpu-throttling` ensures CPU is allocated between polls.
- Cost: ~$5–10/month idle (1 vCPU, 2 GiB RAM, europe-west1).

### Step 5: Run post-deploy smoke

```bash
bash infrastructure/smoke/post-deploy.sh
```

This checks:
- Cloud SQL RUNNABLE
- GCS buckets + Secret Manager secrets present
- SA roles on `nestor-pulse-runtime`
- No SA JSON keys
- Cloud Run services Ready + correct SA + worker min=1
- `GET /health` returns 200

### Step 6: Verify health probes manually

```bash
API_URL=https://nestor-pulse-api-ybkr7metoq-ew.a.run.app

# Liveness (no auth required)
curl -sf "$API_URL/health" | jq .
# Expected: {"status": "ok"}

# Readiness (no auth; requires Cloud SQL RUNNABLE)
curl -sf "$API_URL/readyz" | jq .
# Expected: {"status": "ready", "db": "ok"}

# JWT gate (requires Authorization header)
curl -si "$API_URL/api/runs" | head -2
# Expected: HTTP/2 401
```

### Step 7: Audited SDK run smoke

Get a JWT for the Identity Platform smoke user:

```bash
# Fetch the smoke user password
SMOKE_PW=$(gcloud secrets versions access latest \
  --secret=IDENTITY_PLATFORM_SMOKE_USER_PW \
  --project=project-cb01b861-cb4a-438d-b9a)

# Mint an Identity Platform ID token via the REST signIn endpoint
WEB_API_KEY=$(gcloud secrets versions access latest \
  --secret=IDENTITY_PLATFORM_WEB_API_KEY \
  --project=project-cb01b861-cb4a-438d-b9a 2>/dev/null || \
  echo "${FIREBASE_WEB_API_KEY:-}")

TOKEN=$(curl -s \
  "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${WEB_API_KEY}" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"smoketest@nestor-prod.local\",\"password\":\"${SMOKE_PW}\",\"returnSecureToken\":true}" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['idToken'])")

# Submit a test run (engine=sdk)
RUN_RESPONSE=$(curl -sf \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"brief":"Short smoke test: what is Nestor Pulse?","engine":"sdk"}' \
  "$API_URL/api/runs")
echo "$RUN_RESPONSE" | python3 -c "import sys,json; d=json.load(sys.stdin); print('run_id:', d['id'], 'status:', d['status'])"

# Poll until complete (worker picks it up within seconds)
RUN_ID=$(echo "$RUN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
for i in $(seq 1 60); do
  STATUS=$(curl -sf -H "Authorization: Bearer $TOKEN" "$API_URL/api/runs/$RUN_ID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin)['status'])")
  echo "[$i] status: $STATUS"
  [[ "$STATUS" == "completed" || "$STATUS" == "failed" ]] && break
  sleep 5
done

# Audit chain verification
curl -sf -H "Authorization: Bearer $TOKEN" "$API_URL/api/audit/verify/$RUN_ID" | python3 -c "import sys,json; d=json.load(sys.stdin); print('audit:', d)"
# Expected: {"ok": true, "broken_at": null}
```

---

## Rollback

To roll back the API service to the previous revision:

```bash
# List revisions
gcloud run revisions list \
  --service=nestor-pulse-api \
  --region=europe-west1 \
  --project=project-cb01b861-cb4a-438d-b9a \
  --format='table(metadata.name,status.conditions[0].status)' \
  | head -5

# Route 100% traffic to previous revision
gcloud run services update-traffic nestor-pulse-api \
  --to-revisions=<PREVIOUS_REVISION_NAME>=100 \
  --region=europe-west1 \
  --project=project-cb01b861-cb4a-438d-b9a
```

Same pattern for `nestor-pulse-worker`.

---

## Tear down (cost discipline)

**Pause Cloud SQL** when not actively testing (saves ~$15-30/month idle cost):
```bash
gcloud sql instances patch nestor-prod-pg \
  --activation-policy=NEVER \
  --project=project-cb01b861-cb4a-438d-b9a
```

**Pause the always-on worker** between sessions:
```bash
gcloud run services update nestor-pulse-worker \
  --min-instances=0 \
  --region=europe-west1 \
  --project=project-cb01b861-cb4a-438d-b9a
```

To resume: set `--min-instances=1` and ensure Cloud SQL is RUNNABLE.

---

## GHA workflow (future)

`.github/workflows/deploy-cloud-run.yml.disabled` is the GHA workflow stub.
It will trigger automatically on push to `main` once WIF is provisioned:

```bash
# 1. Set git remote origin
git remote add origin git@github.com:Mohamed-Ajimi-Azentic/Nestor.git

# 2. Provision WIF pool + provider
bash infrastructure/gcloud/workload-identity.sh

# 3. Rename the workflow file
mv .github/workflows/deploy-cloud-run.yml.disabled \
   .github/workflows/deploy-cloud-run.yml

# 4. Commit + push -- triggers the first automated deploy
git add .github/workflows/deploy-cloud-run.yml
git commit -m "chore: enable Cloud Run GHA deploy workflow (WIF unblocked)"
git push origin main
```
