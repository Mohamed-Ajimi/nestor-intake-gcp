# Nestor Intake GCP footprint (D-01, RESEARCH Pattern 4).
#
# Provisions, with IAM database authentication and NO stored DB credential
# anywhere (D-03/D-09/V10):
#   - a POSTGRES_16 Cloud SQL instance (IAM auth on, public IP, NO IP allowlist)
#   - the application database + the runtime SA's IAM DB user (login only)
#   - an Artifact Registry Docker repo for the backend image
#   - the least-privilege Cloud Run runtime service account (V14)
#   - the Cloud Run gen2 service (max-instances=4, D-04) + the alembic migration Job
#
# The Cloud SQL Python Connector tunnels via the Cloud SQL Admin API over TLS
# with ephemeral certs (D-03) -- so there is NO IP allowlist and the Cloud Run
# resources need NO Cloud-SQL-instance attachment flag / annotation (the
# RESEARCH anti-pattern). The only credentialed path to the DB is the runtime
# SA's IAM identity (API-01/D-09).

locals {
  # The IAM DB username = the runtime SA email WITHOUT the ".gserviceaccount.com"
  # suffix (Cloud SQL IAM-login convention). Used for the google_sql_user name,
  # the service DB_USER env, and the Job's DB_USER / RUNTIME_DB_USER env.
  runtime_db_user = trimsuffix(google_service_account.runtime.email, ".gserviceaccount.com")

  image = "${var.region}-docker.pkg.dev/${var.project}/${var.repo}/backend:${var.image_tag}"
}

# --------------------------------------------------------------- Cloud SQL (D-01/D-03)
# POSTGRES_16, IAM auth ON, public IP, NO authorized-networks allowlist (the
# connector tunnels via the Admin API, not an IP list -- T-02-14). deletion
# protection ON so a stray destroy cannot drop the tenant DB.
resource "google_sql_database_instance" "main" {
  name             = var.instance_name
  region           = var.region
  database_version = "POSTGRES_16"

  deletion_protection = true

  settings {
    tier = var.tier # db-custom-1-3840 -> default max_connections=100 (A4/D-04)

    # IAM database authentication -- the ONLY auth path; there is no built-in
    # DB credential to store or leak (D-03/D-09).
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    ip_configuration {
      ipv4_enabled = true # public IP; the connector secures the channel (D-03).
      # Intentionally NO IP allowlist block here -- access is gated by IAM, not
      # by network range (T-02-14). Adding one is the anti-pattern we avoid.
    }
  }
}

# The application database (D-01).
resource "google_sql_database" "app" {
  name     = var.db_name
  instance = google_sql_database_instance.main.name
}

# The runtime SA's IAM DB user. type=CLOUD_IAM_SERVICE_ACCOUNT grants LOGIN ONLY
# -- zero Postgres privileges by default (Pitfall 3). The 0005 migration GRANTs
# it the space-scoped privilege set; RLS still applies (it is NOT the superadmin).
resource "google_sql_user" "runtime" {
  name     = local.runtime_db_user
  instance = google_sql_database_instance.main.name
  type     = "CLOUD_IAM_SERVICE_ACCOUNT"
}

# --------------------------------------------------------- Artifact Registry (D-01)
resource "google_artifact_registry_repository" "backend" {
  location      = var.region
  repository_id = var.repo
  format        = "DOCKER"
  description   = "Nestor Intake backend container images."
}

# ------------------------------------------------------- Runtime service account
resource "google_service_account" "runtime" {
  account_id   = var.runtime_sa_id
  display_name = "Nestor Intake Cloud Run runtime SA"
}

# Least-privilege GCP IAM (V14, T-02-10): EXACTLY the two cloudsql roles the
# connector + IAM login need -- nothing else. No owner/editor/cloudsql.admin.
resource "google_project_iam_member" "runtime_cloudsql_client" {
  project = var.project
  role    = "roles/cloudsql.client" # connect through the connector
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_cloudsql_instance_user" {
  project = var.project
  role    = "roles/cloudsql.instanceUser" # IAM DB login
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# -------------------------------------------------- Cloud Run SERVICE (D-04/INFRA-04)
# gen2 (the v2 resource default), runtime SA, max-instances=4 (D-04 connection
# math). Env carries ONLY non-secret connector config -- no stored credential,
# no DSN (D-09). The container listens on the Cloud-Run-injected $PORT.
resource "google_cloud_run_v2_service" "api" {
  name     = var.service_name
  location = var.region

  template {
    service_account = google_service_account.runtime.email

    scaling {
      max_instance_count = 4 # D-04: 4 * (pool 2 + overflow 3) = 20 conns << 100
    }

    containers {
      image = local.image

      # Cloud Run injects PORT (default 8080); the Dockerfile binds $PORT.
      ports {
        container_port = 8080
      }

      # Non-secret connector config only (D-09). The mode-switched engine factory
      # selects the connector branch because INSTANCE_CONNECTION_NAME is set.
      env {
        name  = "INSTANCE_CONNECTION_NAME"
        value = google_sql_database_instance.main.connection_name
      }
      env {
        name  = "DB_USER"
        value = local.runtime_db_user
      }
      env {
        name  = "DB_NAME"
        value = google_sql_database.app.name
      }
      # Deliberately NO DSN env and NO stored credential here (D-09/V10).
    }
  }

  depends_on = [
    google_project_iam_member.runtime_cloudsql_client,
    google_project_iam_member.runtime_cloudsql_instance_user,
  ]
}

# ----------------------------------------------------- Cloud Run migration JOB (D-05)
# Same image + same runtime SA as the service; overrides the Uvicorn CMD with
# `alembic upgrade head` (RESEARCH Pattern 3 / verified HCL). It also sets
# RUNTIME_DB_USER so the 0005 migration grants the correct IAM DB role.
resource "google_cloud_run_v2_job" "migrate" {
  name     = "nestor-migrate"
  location = var.region

  template {
    template {
      service_account = google_service_account.runtime.email

      containers {
        image = local.image
        args  = ["alembic", "upgrade", "head"]

        env {
          name  = "INSTANCE_CONNECTION_NAME"
          value = google_sql_database_instance.main.connection_name
        }
        env {
          name  = "DB_USER"
          value = local.runtime_db_user
        }
        env {
          name  = "DB_NAME"
          value = google_sql_database.app.name
        }
        # The 0005 GRANT reads this to grant the space-scoped privileges to the
        # runtime SA IAM DB user (OQ1/A5). Same value as DB_USER.
        env {
          name  = "RUNTIME_DB_USER"
          value = local.runtime_db_user
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.runtime_cloudsql_client,
    google_project_iam_member.runtime_cloudsql_instance_user,
    google_sql_user.runtime,
  ]
}

# ------------------------------------------------------------- Invoker policy (OQ2)
# Authenticated-only by default (allow_unauthenticated=false): the deployed
# /readyz is reached via `gcloud run services proxy` (T-02-13). Public health-only
# is an explicit opt-in -- this binding is created ONLY when the var is true.
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  name     = google_cloud_run_v2_service.api.name
  location = google_cloud_run_v2_service.api.location
  role     = "roles/run.invoker"
  member   = "allUsers"
}
