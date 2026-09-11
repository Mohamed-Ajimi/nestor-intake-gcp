# Outputs the user needs for the deploy runbook (infra/README.md):
#   - instance_connection_name -> the INSTANCE_CONNECTION_NAME the connector uses
#   - runtime_sa_email         -> the runtime SA (also the basis for DB_USER)
#   - service_url              -> the deployed Cloud Run URL (curl /readyz here)
#   - repo_url                 -> the Artifact Registry path to push the image to

output "instance_connection_name" {
  description = "Cloud SQL connection name (project:region:instance) for the connector."
  value       = google_sql_database_instance.main.connection_name
}

output "runtime_sa_email" {
  description = "Cloud Run runtime service account email (DB_USER = this minus .gserviceaccount.com)."
  value       = google_service_account.runtime.email
}

output "service_url" {
  description = "Deployed Cloud Run service URL (verify SC1 by curling its /readyz)."
  value       = google_cloud_run_v2_service.api.uri
}

# Phase 12 (INFRA-05): the deployed frontend run.app URL. This is the URL captured on the
# FIRST frontend deploy (pass 1) and fed into the second-pass wiring (§ Phase 12, Step 12.4):
# backend CORS_ALLOWED_ORIGINS, backend APP_BASE_URL, the uploads-bucket CORS policy, and the
# Firebase authorized-domains allowlist. NEVER wire a guessed run.app URL — read the captured
# Service URL (12-RESEARCH Pitfall 4).
output "frontend_service_url" {
  description = "Deployed frontend Cloud Run service URL (run.app). Feeds the second-pass wiring: backend CORS_ALLOWED_ORIGINS + APP_BASE_URL, uploads-bucket CORS, and Firebase authorized domains (§ Phase 12). Capture the real deploy output — never a guessed URL."
  value       = google_cloud_run_v2_service.frontend.uri
}

output "repo_url" {
  description = "Artifact Registry Docker repo path in THIS project -- the repo images are PUSHED to. Note (D-23.4-04): when var.image_registry_project is set, the Cloud Run services PULL from THAT project's repo instead, and this repo goes unused; `pull_repo_url` below is the path that is actually referenced by the deployed services."
  value       = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.backend.repository_id}"
}

# ------------------------------------------------------------------ Phase 23.4 additions

# D-23.4-04: the repo the deployed services actually pull from. Equal to repo_url unless
# var.image_registry_project points at another project (the client environment promoting
# the dev build's digests). Read this, never repo_url, when checking what is deployed.
output "pull_repo_url" {
  description = "Artifact Registry Docker repo path the Cloud Run services PULL from (var.image_registry_project, else this project). Equal to repo_url in a single-project environment."
  value       = "${var.region}-docker.pkg.dev/${local.registry_project}/${var.repo}"
}

# The tribunal-api run.app URL. Captured on the FIRST tribunal-api deploy and fed back in
# as var.tribunal_service_url (the OIDC audience, set on BOTH services) -- never guessed,
# never with a path (Phase 14 Pitfall 4).
output "tribunal_service_url" {
  description = "Deployed tribunal-api Cloud Run service URL. Feed this back as var.tribunal_service_url (the OIDC audience on both nestor-api and tribunal-api). Capture it -- never guess a run.app URL, and never include a path."
  value       = google_cloud_run_v2_service.tribunal_api.uri
}

# D-23.4-05: the exact secret NAME the operator must add the Anthropic key version to.
# In an environment where anthropic_api_key_secret_id == tribunal_claude_secret_id this is
# the SINGLE container serving nestor-api AND both tribunal services, so one
# `gcloud secrets versions add <this> --data-file=-` covers all three. The agent never sees
# the value; this output is the NAME only.
output "anthropic_secret_name" {
  description = "The exact Secret Manager secret NAME the operator must add the ANTHROPIC_API_KEY version to. Where the intake and tribunal ids are the same string (D-23.4-05) this is the one container serving nestor-api, tribunal-api and tribunal-worker. NAME only -- no value is ever emitted by Terraform."
  value       = local.tribunal_claude_secret_name
}
