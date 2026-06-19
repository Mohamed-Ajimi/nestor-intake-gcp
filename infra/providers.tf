# Terraform + provider configuration for the Nestor Intake GCP footprint (D-01).
#
# Single google provider, pinned to a 6.x version that ships the
# google_cloud_run_v2_service / google_cloud_run_v2_job resources used in main.tf
# (RESEARCH Pattern 4 + the verified Cloud Run v2 Job HCL). State backend is left
# as the default local backend for the skeleton; the user may add a GCS backend
# in Cloud Shell per infra/README.md (Claude's discretion, CONTEXT region/state).

terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 7.0"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}
