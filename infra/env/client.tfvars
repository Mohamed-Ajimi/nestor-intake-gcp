# ============================================================================
# CLIENT environment — nestor-pulse-prod
# ============================================================================
# Used as: terraform -chdir=infra plan -var-file=env/client.tfvars
#
# NOTHING IN THIS FILE IS A SECRET (D-23.4-05). Every value here is a project id,
# a service name, a public Firebase identifier, a public run.app URL, or the NAME
# of a Secret Manager container. Secret VALUES are added by the operator, to the
# containers Terraform creates, and are never typed by an agent and never
# committed. If you are about to paste something that looks like a credential
# into this file, stop: it belongs in Secret Manager.
#
# Variables appear in the order they are declared in infra/variables.tf.
#
# Two markers are used:
#   <capture-after-first-deploy>  — the value cannot be known until the resource
#                                   it describes exists. The comment on the line
#                                   names the step that captures it. NEVER apply
#                                   one of these as a literal.
#   (no marker)                   — decided, apply as-is.
# ----------------------------------------------------------------------------

# ---------------------------------------------------------------- core target
project = "nestor-pulse-prod"
region  = "europe-west1"

# D-23.4-04 + operator RULING 2a (shared dev Artifact Registry), 2026-09-11.
# The client's Cloud Run services PULL the SAME image digests the dev build
# produced, out of the dev project's registry. This is what makes "build once,
# promote the same digest" a fact rather than a claim to re-verify.
#
# Two consequences the operator accepted:
#   1. The dev registry is now a hard runtime dependency of the client
#      environment. Deleting an image there removes a client ROLLBACK TARGET.
#      Retention rule, to be carried into infra/BOOTSTRAP.md by plan 23.4-05:
#      never delete an image any client revision still references.
#   2. Three client-project identities need roles/artifactregistry.reader on the
#      dev repo — nestor-run, tribunal-run, and the client project's Cloud Run
#      SERVICE AGENT. That grant lives on the DEV project, so it is an operator
#      command (Task 3 Step 6), NOT a resource in this Terraform root: expressing
#      it here would need a second aliased provider and would give the client
#      state write authority over the dev project's IAM.
#
# Set this to "" to reverse the ruling (per-project registry + a copy step per
# image per release, ruling-2b). The Cloud Run services would then pull from the
# client project's own `nestor` repo, which Terraform creates either way.
image_registry_project = "project-cb01b861-cb4a-438d-b9a"

# ------------------------------------------------------------- image versions
# All three are promoted dev tags, set by plan 23.4-03 Task 1. Until that plan
# runs there is no image in the client's pull path, so the Cloud Run services
# created by the first apply are EXPECTED to fail to become ready.
image_tag          = "f5e2b9ad" # 23.4-03 Task 1 — the promoted backend tag
frontend_image_tag = "client-20260912-135048" # 23.4-03 Task 1 — the promoted frontend tag

# ------------------------------------------------------------ nestor-api tier
# DEF-23.3-14: 1, never 0. At 0 the phase 23.3 orphaned-run reconcile loop never
# ticks and a paid research run can be stranded silently.
api_min_instances = 1
# Cloud Run IAM lets anyone REACH nestor-api; the request is then gated by the app's own
# Firebase ID-token check on every protected route. Dev runs this way (read back 2026-09-12:
# roles/run.invoker -> allUsers); without it the client's browser gets a Cloud Run 403.
allow_unauthenticated = true

# Operator RULING 1a, 2026-09-11: keep the Agenic address, so the operator owns
# the client environment and no client user exists until one is deliberately
# created through the admin surface. D-23.4-06 requires exactly that ordering —
# the proving run happens BEFORE any client user.
superadmin_email = "yanick@agenic.be"

# ------------------------------------------------------------- frontend tier
frontend_min_instances = 0 # SSR does no background work; a cold start is the only cost

# -------------------------------------------- frontend build-time public config
# These are baked into the bundle at IMAGE BUILD time (Cloud Build
# --substitutions), not read at runtime. They are listed here to document the
# build-arg surface; Terraform does not inject them.
# Captured 2026-09-11 from `gcloud run services describe` on nestor-pulse-prod (23.4-03), not chosen.
vite_api_base_url         = "https://nestor-api-zqd5qncdnq-ew.a.run.app"      # the client nestor-api URL, after its first deploy
vite_firebase_api_key     = "AIzaSyCczKyabCcEsvJshzPv_lE9HiaVkKgXxpo"      # PUBLIC web identifier, read from the client project's Firebase web app config
vite_firebase_auth_domain = "nestor-pulse-prod.firebaseapp.com" # D-23.4-03, no custom domain yet
vite_firebase_project_id  = "nestor-pulse-prod"

# ------------------------------------------------------------------ CORS/origins
# The client frontend's run.app origins. BOTH hostnames are needed (the
# <hash>-ew form and the <project-number> form), same as dev. Captured in the
# second-pass wiring after the frontend's first deploy (23.4-03).
cors_allowed_origins = ["<capture-after-first-deploy>"]

# ----------------------------------------------------- secret CONTAINER names
# D-23.4-02: Gemini, OpenAI and Resend carry the SAME VALUES as dev, but in THIS
# project's own containers — a shared key is not a shared container. Anthropic
# gets a DIFFERENT, NEW key value in this project.
#
# D-23.4-05: the intake and tribunal Anthropic ids below are deliberately the
# SAME STRING. local.tribunal_claude_is_shared reads that equality and drops the
# duplicate google_secret_manager_secret resource, so ONE container serves
# nestor-api, tribunal-api and tribunal-worker. The dev project's split (two
# containers for one credential) is drift this environment does not inherit.
anthropic_api_key_secret_id = "nestor-anthropic-api-key"
openai_api_key_secret_id    = "nestor-openai-api-key"
resend_api_key_secret_id    = "nestor-resend-api-key"

# ------------------------------------------------------------- mail / app URLs
nestor_admin_email = "mohamed.ajimi@dotto.be"       # same ops address as dev
app_base_url       = "<capture-after-first-deploy>" # the client frontend URL — 23.4-03 second-pass wiring

# -------------------------------------------------------------- tribunal tier
# 1 x NESTOR_WORKER_RUN_CONCURRENCY=4 = 4 concurrent research runs for the
# client. The live dev project runs 2 x 4 = 8. Never 0: at 0 the poll loop stops
# and queued paid runs sit unclaimed.
tribunal_worker_min_instances = 1
tribunal_api_min_instances    = 0

# D-23.4-07: back to 60. The 90 stopgap's condition (a heartbeat that never
# landed) was removed on 2026-09-09.
tribunal_worker_stale_minutes = "60"

tribunal_image_tag = "f5e2b9ad" # 23.4-03 Task 1 — the promoted tribunal tag

tribunal_gemini_secret_id = "Nestor_Gemini"
tribunal_openai_secret_id = "Nestor_OpenAI"
# The SAME string as anthropic_api_key_secret_id above — see D-23.4-05.
tribunal_claude_secret_id = "nestor-anthropic-api-key"

# Pinned rather than derived, so the name is visible in this file and matches
# what the operator seeds into the AUDIT_GCS_BUCKET container.
tribunal_audit_bucket_name = "nestor-pulse-prod-nestor-audit"

# The client tribunal-api URL, used verbatim as the OIDC audience on BOTH
# services. Captured from `gcloud run services describe tribunal-api` after its
# first deploy — never guessed, never with a path (Phase 14 Pitfall 4).
tribunal_service_url = "https://tribunal-api-zqd5qncdnq-ew.a.run.app" # 23.4-03 second-pass wiring
