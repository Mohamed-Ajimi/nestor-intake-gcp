# ============================================================================
# DEV environment — project-cb01b861-cb4a-438d-b9a
# ============================================================================
# ⚠ THIS FILE HAS NEVER BEEN APPLIED, AND MUST NOT BE APPLIED AS-IS.
#
# The dev project's resources were all created BY HAND across phases 2-23. There
# is no Terraform state for it anywhere. A plan from an empty state would show
# every resource as a CREATE, and applying that would collide with the live
# footprint. Dev requires a `terraform import` pass first — see the warning at
# the top of env/dev.gcs.tfbackend.
#
# What this file IS: a truthful, measured DESCRIPTION of what is actually running
# in dev, so that the client environment can be compared against it and so the
# eventual import pass has a target to converge on. Every value below was read
# from the live project on 2026-09-11 with read-only gcloud, EXCEPT where a line
# says otherwise.
#
# NO SECRET VALUES. Same rule as client.tfvars (D-23.4-05).
#
# Known drift between infra/*.tf and live dev, recorded here rather than fixed:
#   - nestor-frontend runs maxScale=20; main.tf declares max_instance_count = 4.
#     There is no variable for it, so an import-and-apply would scale it DOWN.
#   - the superadmin DB password secret is named `nestor-app-superadmin-pw` live,
#     not the `nestor-app-superadmin-db-password` default (captured below).
#   - the live worker still runs NESTOR_WORKER_STALE_MINUTES=90; the revert to 60
#     is committed (plan 23.4-02) but NOT yet deployed.
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------- core target
project = "project-cb01b861-cb4a-438d-b9a"
region  = "europe-west1"

# Dev builds AND runs out of its own registry, so no cross-project reference.
# This empty value is what every environment did before the variable existed.
image_registry_project = ""

# ------------------------------------------------------------- image versions
# Read from `gcloud run services list` on 2026-09-11. Note that nestor-frontend
# is deployed BY DIGEST (sha256:0e16471…); the tag below is the tag Artifact
# Registry has attached to that exact digest, not an independent claim.
image_tag          = "20260907-161728" # nestor-api, live
frontend_image_tag = "20260909-101602" # nestor-frontend, live (digest sha256:0e16471…)
tribunal_image_tag = "20260909-091435" # tribunal-api AND tribunal-worker, live

# ---------------------------------------------------------------- scaling, live
# Read from the autoscaling.knative.dev/minScale annotations on 2026-09-11.
api_min_instances             = 1 # set by hand in the 2026-09-07 correction (DEF-23.3-14)
frontend_min_instances        = 0 # annotation absent => 0
tribunal_api_min_instances    = 0 # annotation absent => 0
tribunal_worker_min_instances = 2 # 2 x NESTOR_WORKER_RUN_CONCURRENCY=4 = 8 concurrent runs

# ---------------------------------------------------------------- identity
# NOT MEASURED. This is the infra/variables.tf default; the live Identity
# Platform user list was not read. Verify before relying on it.
superadmin_email = "yanick@agenic.be"

# Live drift: the dev service's SUPERADMIN_DB_PASSWORD_SECRET env points at
# `nestor-app-superadmin-pw`, NOT the variable's default. Recorded so an import
# pass does not try to rename it.
superadmin_db_secret_id = "nestor-app-superadmin-pw"

# -------------------------------------------- frontend build-time public config
vite_api_base_url = "https://nestor-api-ybkr7metoq-ew.a.run.app"

# PUBLIC project identifier, not a credential — but it is never committed in this
# repo by convention (the Cloud Build classifier blocks _FB_API_KEY literals), so
# it is carried as a marker and passed as a --substitution at build time.
vite_firebase_api_key     = "<read-from-the-firebase-web-app-config>"
vite_firebase_auth_domain = "project-cb01b861-cb4a-438d-b9a.firebaseapp.com"
vite_firebase_project_id  = "project-cb01b861-cb4a-438d-b9a"

# ------------------------------------------------------------------ CORS/origins
# Read verbatim from the live nestor-api CORS_ALLOWED_ORIGINS env.
cors_allowed_origins = [
  "https://nestor-frontend-1055853212188.europe-west1.run.app",
  "https://nestor-frontend-ybkr7metoq-ew.a.run.app",
  "http://localhost:8081",
]

# ----------------------------------------------------- secret CONTAINER names
# Dev's historical split: the intake service reads the Anthropic credential from
# one container and the two tribunal services read the SAME credential from
# another. That is the drift D-23.4-05 refuses to carry into a new environment;
# it is recorded here because it is what is live, not because it is right.
anthropic_api_key_secret_id = "nestor-anthropic-api-key"
openai_api_key_secret_id    = "nestor-openai-api-key"
resend_api_key_secret_id    = "nestor-resend-api-key"
tribunal_gemini_secret_id   = "Nestor_Gemini"
tribunal_openai_secret_id   = "Nestor_OpenAI"
tribunal_claude_secret_id   = "Nestor_Claude2"

# ------------------------------------------------------------- mail / app URLs
# Read verbatim from the live nestor-api env.
nestor_admin_email = "mohamed.ajimi@dotto.be"
app_base_url       = "https://nestor-frontend-1055853212188.europe-west1.run.app"

# -------------------------------------------------------------- tribunal tier
# ⚠ The LIVE dev worker still runs 90. This 60 is the D-23.4-07 intent, committed
# in plan 23.4-02 but not yet deployed; dev drifts until the next worker deploy.
tribunal_worker_stale_minutes = "60"

# Empty derives "<project>-nestor-audit", which matches the live bucket name
# `project-cb01b861-cb4a-438d-b9a-nestor-audit` exactly. Note the project also
# holds a legacy `nestor-audit-prod` bucket; which of the two the live worker
# actually writes to is carried in the AUDIT_GCS_BUCKET secret, and secret values
# are never read by the agent, so this line is the DERIVATION, not a read-back.
tribunal_audit_bucket_name = ""

# Read verbatim from the live nestor-api TRIBUNAL_SERVICE_URL env.
tribunal_service_url = "https://tribunal-api-ybkr7metoq-ew.a.run.app"
