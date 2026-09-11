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
  # an unacceptable risk for a resource set carrying deletion_protection.
  #
  # D-23.4-01: the block below is now LIVE and PARTIAL -- it names the gcs backend but
  # deliberately carries NO bucket. Terraform therefore cannot resolve a state location
  # on its own, and every init MUST name the environment it is initialising:
  #
  #   terraform -chdir=infra init -reconfigure -backend-config=env/client.gcs.tfbackend
  #   terraform -chdir=infra init -reconfigure -backend-config=env/dev.gcs.tfbackend
  #
  # A bare `terraform init` now PROMPTS for the bucket instead of silently writing a
  # local `terraform.tfstate`. That prompt IS THE POINT. A silent local state file is
  # exactly how this project's own state was lost: the dev project has no recorded
  # state anywhere and its resources were created by hand, so nobody can now say what
  # was applied. An interactive prompt is the cheap failure; a second, divergent,
  # unshareable state file is the expensive one.
  #
  # The bucket is created ONCE PER PROJECT, by the operator, BEFORE the first init --
  # `init` against a not-yet-created bucket fails, and that ordering is a runbook step,
  # not a Terraform resource (a backend cannot bootstrap its own storage):
  #
  #   gcloud storage buckets create gs://<project-id>-tfstate --location=europe-west1 \
  #     --uniform-bucket-level-access --project=<project-id> --account=tools@dotto.be
  #   gcloud storage buckets update gs://<project-id>-tfstate --versioning \
  #     --project=<project-id> --account=tools@dotto.be
  #
  # Versioning is not optional: it is the only recovery path from a corrupted apply.
  backend "gcs" {}
}

provider "google" {
  project = var.project
  region  = var.region
}
