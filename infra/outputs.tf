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

output "repo_url" {
  description = "Artifact Registry Docker repo path to push the backend image to."
  value       = "${var.region}-docker.pkg.dev/${var.project}/${google_artifact_registry_repository.backend.repository_id}"
}
