# Nestor Intake — GCP deploy runbook (Cloud Shell)

This is the **deferred-execution** runbook for the Phase-2 backend skeleton + IaC
(D-02). The dev box has **no Python, Docker, Terraform, or gcloud** (D-10), so all
steps below are **executed by you in GCP Cloud Shell** — the artifacts are authored
by construction and verified live here.

Run everything from **Cloud Shell** in the target project. Terraform, `gcloud`,
and `docker` are pre-installed there.

## What this provisions

`infra/*.tf` provisions, with **IAM database authentication and no stored DB
credential anywhere** (D-03/D-09):

- a `POSTGRES_16` Cloud SQL instance (`cloudsql.iam_authentication=on`, public IP,
  **no IP allowlist** — the connector tunnels over the Cloud SQL Admin API),
- the `nestor` application database + the runtime SA's IAM DB user (login only),
- an Artifact Registry Docker repo for the backend image,
- the least-privilege runtime service account (exactly `roles/cloudsql.client` +
  `roles/cloudsql.instanceUser`),
- a Cloud Run **service** (`max-instances=4`) and a Cloud Run **migration Job**
  (`alembic upgrade head`) — both off the **same image**.

## Prerequisites (one-time)

```bash
# In Cloud Shell, target the project and enable the APIs.
export GOOGLE_PROJECT="<your-project-id>"
gcloud config set project "$GOOGLE_PROJECT"
gcloud services enable \
  sqladmin.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  cloudbuild.googleapis.com

# Terraform variables (region default is europe-west1 — OQ3).
export TF_VAR_project="$GOOGLE_PROJECT"
export TF_VAR_region="europe-west1"
```

The deploy is intentionally a **two-step apply** (apply infra → build/push image →
re-apply with the real tag). This avoids the chicken-and-egg where the service/Job
reference an image that does not exist yet.

---

## Step 1 — `terraform apply` the infra (with a placeholder tag)

```bash
cd infra
terraform init
# Validate + format before applying (these are also deferred from the dev box).
terraform fmt -check
terraform validate

# First apply: provisions the registry, runtime SA + the two cloudsql IAM
# bindings, the Cloud SQL instance + IAM DB user, and the service/Job pointing
# at a not-yet-pushed image tag. Use a placeholder tag for this pass.
terraform apply -var="image_tag=bootstrap"
```

Note the outputs (`instance_connection_name`, `runtime_sa_email`, `repo_url`,
`service_url`).

## Step 2 — build + push the backend image to Artifact Registry

The backend `Dockerfile` (multi-stage `uv` / `python:3.12-slim`) builds the single
image that serves **both** the Uvicorn service and the migration Job.

```bash
REGION="$TF_VAR_region"
REPO_URL="$(terraform output -raw repo_url)"   # e.g. europe-west1-docker.pkg.dev/<proj>/nestor
TAG="v1"

# Option A — Cloud Build (no local Docker needed):
gcloud builds submit ../backend --tag "${REPO_URL}/backend:${TAG}"

# Option B — local docker (if you prefer):
#   gcloud auth configure-docker "${REGION}-docker.pkg.dev"
#   docker build -t "${REPO_URL}/backend:${TAG}" ../backend
#   docker push "${REPO_URL}/backend:${TAG}"
```

## Step 3 — re-apply with the real image tag, and confirm the IAM DB user

```bash
terraform apply -var="image_tag=v1"
```

This re-points the Cloud Run service and the migration Job at the freshly pushed
`backend:v1` image.

**Confirm the IAM SA DB user exists.** Terraform creates it
(`google_sql_user type=CLOUD_IAM_SERVICE_ACCOUNT`). To verify (or as a manual
fallback if you provisioned out of band):

```bash
SA_EMAIL="$(terraform output -raw runtime_sa_email)"
DB_USER="${SA_EMAIL%.gserviceaccount.com}"        # the IAM DB username
gcloud sql users list --instance="$(terraform output -raw instance_connection_name | cut -d: -f3)"
# Fallback create (idempotent intent):
#   gcloud sql users create "$DB_USER" --instance=<instance> --type=cloud_iam_service_account
```

### ⚠ The single most likely thing to block `/readyz`: the OQ1/A5 GRANT (0005)

A `CLOUD_IAM_SERVICE_ACCOUNT` DB user has **login only, zero Postgres
privileges**. Until the runtime SA is GRANTed `USAGE` on schema `nestor` + table
DML, any real query fails with `permission denied for schema nestor`.

That GRANT is migration **`0005_grant_runtime_sa.py`**. It runs in **Step 4** as
part of `alembic upgrade head`, keyed on the `RUNTIME_DB_USER` env var that the
migration Job sets to the IAM DB username. **You do not run a separate GRANT
command** — the Job does it. If Step 5 returns `permission denied`, this mapping
is the thing to correct (it is the flagged LOW-confidence item, A5).

## Step 4 — run the migration Job (`alembic upgrade head`)

```bash
gcloud run jobs execute nestor-migrate --region "$TF_VAR_region" --wait
```

Confirm migrations reached head (the chain is `0001 → 0005`, and `0005` grants the
runtime SA into the `nestor` schema):

```bash
# Inspect the Job execution logs; you should see 0001..0005 applied with no error.
gcloud run jobs executions list --job nestor-migrate --region "$TF_VAR_region"
# alembic current == head can also be confirmed by a one-off Job run of
#   args=["alembic","current"] (or check the migration logs above).
```

> **WR-04 — the 0005 GRANT now fails loud, not silent.** When the Job runs with
> `RUNTIME_DB_USER` set but the IAM DB user does not yet exist, `0005` raises an
> exception and the Job exits non-zero (instead of the old `RAISE NOTICE` that
> silently skipped the GRANT and left the runtime SA with zero privileges). If the
> Job fails on 0005 with `RUNTIME_DB_USER role ... does not exist`, confirm the IAM
> DB user from Step 3 first, then re-run the Job. As a belt-and-suspenders check,
> after a green Job you can assert the GRANT actually applied:
>
> ```bash
> # Expect 't' (true) for the runtime SA's USAGE on schema nestor.
> #   SELECT has_schema_privilege('<RUNTIME_DB_USER>', 'nestor', 'USAGE');
> ```

## Step 4b — Phase 3 auth: apply the IdP IAM grant + bootstrap the first superadmin (D-05)

Phase 3 adds the auth path (Identity Platform). Two things must be in place before a
human can actually log in: the runtime SA needs **`roles/identitytoolkit.admin`** (to
write custom claims / create-lookup IdP users — token *verification* needs no role),
and the **first superadmin** must be seeded (there is no public self-registration —
D-02). Both are deferred-to-live here.

### 4b.1 — apply the new IAM binding + seed Job

`terraform apply` (re-run from Step 3) now also creates
`google_project_iam_member.runtime_identitytoolkit_admin` and the
`nestor-seed-superadmin` Cloud Run Job (same image, alt entrypoint
`python -m scripts.seed_superadmin`, no stored credential).

```bash
cd infra
# Re-apply (idempotent) so the identitytoolkit.admin grant + seed Job exist.
terraform apply -var="image_tag=v1" -var="superadmin_email=yanick@agenic.be"
```

> **Pitfall 6 — claim writes fail without `identitytoolkit.admin`.** If you skip this
> grant, `verify_id_token` still works but `set_custom_user_claims` (login-sync + the
> seed) fails with a permission error, and every authenticated user is stuck at a 403
> "No role claim" loop. Apply the binding **before** the service serves login traffic.

### 4b.2 — ⚠ same-project guard (Pitfall 5)

The frontend mints tokens against the project named by **`VITE_FIREBASE_PROJECT_ID`**;
the backend verifies + writes claims against the project ADC resolves from
**`GOOGLE_CLOUD_PROJECT`** (injected by Cloud Run). These MUST be the **same**
Identity-Platform-enabled project, or tokens minted by the frontend fail
`verify_id_token` on the backend (audience mismatch).

```bash
# Backend project (what the runtime SA / ADC sees):
gcloud run services describe nestor-api --region "$TF_VAR_region" \
  --format='value(spec.template.spec.containers[0].env)'   # GOOGLE_CLOUD_PROJECT == $GOOGLE_PROJECT
# Confirm Identity Platform is enabled on that SAME project:
gcloud services list --enabled --filter='identitytoolkit.googleapis.com'
# And confirm the frontend build's VITE_FIREBASE_PROJECT_ID == $GOOGLE_PROJECT.
```

### 4b.3 — run the superadmin seed (Cloud Run Job)

Execute the one-shot Job, passing the password **at execute time** (it is never stored
in IaC/state — T-03-15). The Job uses ADC (the runtime SA), no JSON key.

```bash
gcloud run jobs execute nestor-seed-superadmin --region "$TF_VAR_region" --wait \
  --update-env-vars "SUPERADMIN_PASSWORD=<choose-a-strong-password>"
# Idempotent: re-running promotes the existing IdP user / membership row (no duplicates).
# Expect the +/= summary: idp_user, claim, system_org, membership.
```

This creates (or promotes) the IdP user, sets the **cross-tenant** claim
`{"role":"superadmin","space_id":null}`, and writes the FK-anchored
`organization_memberships` row against the system "Agenic" org. **Open Q3 / T-03-16:**
the row's `organization_id` is a bookkeeping FK anchor only — the superadmin claim is
`space_id=null` (all spaces), and Phase-4 authorization reads the *claim*, never the row.

### 4b.4 — optional: local run against the Firebase Auth emulator (D-09)

The dev box has no live IdP. To exercise the auth path locally, point the Admin SDK +
the frontend at the Firebase Auth emulator:

```bash
firebase emulators:start            # exposes Auth on localhost:9099
# Backend (seed / API): export FIREBASE_AUTH_EMULATOR_HOST=localhost:9099 before running.
# Frontend: connectAuthEmulator(auth, "http://localhost:9099") in the auth client.
```

With the emulator running, `python -m scripts.seed_superadmin <email> <password>` and
`POST /auth/session` work end-to-end without touching a real Identity Platform project.

## Step 5 — deferred SC1 verification: deployed `/readyz` returns 200

This is **success criterion 1** — it proves live **Cloud SQL connectivity via the
connector + IAM**, with no proxy sidecar and no stored credential.

The invoker defaults to **authenticated-only** (`allow_unauthenticated=false`,
OQ2), so reach the service through an authenticated proxy:

```bash
# Open an authenticated local proxy to the service (no public exposure).
gcloud run services proxy nestor-api --region "$TF_VAR_region" --port 8080 &
# In the same shell:
curl -i http://localhost:8080/readyz
# EXPECT: HTTP/1.1 200 and a body of {"status":"ready","db":"ok"}
curl -i http://localhost:8080/healthz
# EXPECT: HTTP/1.1 200 {"status":"ok"} (liveness — never touches the DB)
```

**Public health-only opt-in (fallback):** if your org permits unauthenticated
Cloud Run and you want to curl the URL directly, re-apply with
`-var="allow_unauthenticated=true"`, then
`curl -i "$(terraform output -raw service_url)/readyz"`.

## Step 6 — confirm no DB credential anywhere (criterion 4)

IAM-only auth means there is no DB secret to leak. Confirm none exists in the
service/Job env, the image, or Secret Manager:

```bash
gcloud run services describe nestor-api --region "$TF_VAR_region" \
  --format='value(spec.template.spec.containers[0].env)'   # only INSTANCE_CONNECTION_NAME/DB_USER/DB_NAME
gcloud secrets list   # no DB credential / SA JSON key for this service
```

---

## Deferred Manual-Only pass criteria (reproduced from 02-VALIDATION.md, D-10)

These three are verified **here in GCP**, not on the dev box:

1. **Deployed `/readyz` returns 200** proving live Cloud SQL connectivity via the
   connector + IAM (INFRA-01, INFRA-04) — Step 5.
2. **Migration Job runs `alembic upgrade head`** against Cloud SQL via IAM and
   `alembic current` == head (INFRA-04) — Step 4.
3. **The IAM DB user ⇄ `nestor` GRANT (0005) lets the runtime SA actually query**
   (API-01) — connect/run as the runtime SA post-deploy and confirm `SELECT 1`
   (and, in Phase 4, a tenant-scoped read) succeed. A `permission denied for
   schema nestor` here means the 0005 / `RUNTIME_DB_USER` mapping needs adjusting.

**Report after running:** did `/readyz` return **200**, and did the migration Job
reach head? Paste any error (especially a `permission denied`) so the OQ1/A5 GRANT
mapping can be corrected.
