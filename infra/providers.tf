# Terraform + provider configuration for the Nestor Intake GCP footprint (D-01).
#
# Single google provider, pinned to a 6.x version that ships the
# google_cloud_run_v2_service / google_cloud_run_v2_job resources used in main.tf
# (RESEARCH Pattern 4 + the verified Cloud Run v2 Job HCL).

terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0, < 7.0"
    }
  }

  # WR-06: remote state for the infra that owns the only credentialed path to the
  # tenant DB. Local state has no locking, is easy to lose, and is not shareable --
  # an unacceptable risk for a resource set carrying deletion_protection. Provision
  # a versioned GCS bucket once in Cloud Shell, then UNCOMMENT the backend block
  # below and run `terraform init -migrate-state` to move local state into it:
  #
  #   gsutil mb -l "$TF_VAR_region" -b on "gs://${TF_VAR_project}-nestor-tfstate"
  #   gsutil versioning set on "gs://${TF_VAR_project}-nestor-tfstate"
  #
  # The block is shipped commented (not live) because `terraform init` would fail
  # against a not-yet-created bucket; uncommenting is a one-line step in the runbook.
  #
  # backend "gcs" {
  #   bucket = "<your-project-id>-nestor-tfstate" # the bucket created above
  #   prefix = "nestor-intake/infra"
  # }
}

provider "google" {
  project = var.project
  region  = var.region
}
