---
phase: 04-tenant-isolation-proven-by-tests
plan: 04
subsystem: infra
tags: [terraform, secret-manager, cloud-sql, cloud-build, ci-gate, superadmin, path-b]
requires:
  - "04-02: base.py get_superadmin_engine + _load_superadmin_password (reads SUPERADMIN_DB_PASSWORD_SECRET)"
  - "backend/tests/conftest.py: _ensure_app_superadmin + PGVECTOR_IMAGE (CI gate mirrors this)"
  - "0003_superadmin_bypass.py: current_user='app_superadmin' bypass predicate (user name must match verbatim)"
provides:
  - "Terraform: app_superadmin BUILT_IN Cloud SQL user + generated password in Secret Manager"
  - "Terraform: resource-scoped secretAccessor grant for the runtime SA"
  - "Terraform: SUPERADMIN_DB_PASSWORD_SECRET Cloud Run env (secret resource name, not the value)"
  - "cloudbuild.test.yaml: QA-01 required cross-tenant denial CI gate"
affects:
  - "infra/main.tf, infra/variables.tf, infra/README.md"
  - "cloudbuild.test.yaml (new, repo root)"
tech-stack:
  added:
    - "Secret Manager (google_secret_manager_secret/_version/_iam_member) — first Secret Manager use in this repo"
    - "random_password (hashicorp/random) — generated app_superadmin password"
    - "Cloud Build YAML config (cloudbuild.test.yaml)"
  patterns:
    - "Path B (D-05a): one stored DB credential (app_superadmin), in Secret Manager only; env carries the secret NAME"
    - "resource-scoped IAM (least privilege) over project-wide grants"
    - "DATABASE_URL bypass in CI so conftest skips testcontainers and uses the sidecar Postgres"
key-files:
  created:
    - "cloudbuild.test.yaml"
  modified:
    - "infra/main.tf"
    - "infra/variables.tf"
    - "infra/README.md"
decisions:
  - "Cloud Run env SUPERADMIN_DB_PASSWORD_SECRET = '<secret .name>/versions/latest' — the exact resource path base.py passes to client.access_secret_version()"
  - "google-cloud-secret-manager NOT re-added — it was already declared by plan 04-02 (idempotency note honored)"
  - "CI gate exposes pgvector via DATABASE_URL (no docker-in-docker) so conftest bypasses testcontainers and the test superuser provisions app_superadmin out-of-band"
metrics:
  duration: "~5 min"
  completed: 2026-06-19
  tasks: 2
  files: 4
---

# Phase 4 Plan 4: Path B credential plumbing + required CI gate Summary

Provisioned the Path B (D-05a) credential chain — a BUILT_IN Cloud SQL user named the exact literal `app_superadmin` with a `random_password`-generated password stored only in Secret Manager, a resource-scoped `secretAccessor` grant for the runtime SA, and a `SUPERADMIN_DB_PASSWORD_SECRET` Cloud Run env carrying the secret resource name — and authored `cloudbuild.test.yaml`, the QA-01 required cross-tenant denial gate that runs `pytest -m integration` against `pgvector/pgvector:pg16`.

## What was built

### Task 1 — Terraform: app_superadmin BUILT_IN user + Secret Manager password (commit ddead39)
- `infra/main.tf`:
  - `random_password.app_superadmin` (length 32, conservative special set valid for pg8000 + Secret Manager payload) — the password is generated, never a committed literal.
  - `google_sql_user.app_superadmin` — `name = "app_superadmin"` (the EXACT literal 0003's `current_user = 'app_superadmin'` predicate matches), `type = "BUILT_IN"`, password sourced from `random_password.app_superadmin.result`.
  - `google_secret_manager_secret.app_superadmin_db_password` + `..._version` holding the generated password (the first Secret Manager resource in the repo — annotated as the single deliberate D-05a/D-09 exception to the IAM-passwordless invariant).
  - `google_secret_manager_secret_iam_member.runtime_superadmin_secret_accessor` — resource-scoped `roles/secretmanager.secretAccessor` for the runtime SA on that one secret (least privilege, not project-wide — T-04-17).
  - `SUPERADMIN_DB_PASSWORD_SECRET` env on `google_cloud_run_v2_service.api` = `"${...secret.name}/versions/latest"` (the secret RESOURCE NAME `base.py::_load_superadmin_password()` reads; no password value in any env — T-04-16). Added `depends_on` so the secret/version/grant precede the service.
  - Header invariant updated to document the single deliberate Path B exception.
- `infra/variables.tf`: added `superadmin_db_secret_id` (default `nestor-app-superadmin-db-password`), modeled on the `superadmin_email` block.
- `infra/README.md`: new Step 4c (deferred apply runbook for the user + secret + scoped grant + env, with the Pitfall-3 "does not exist on the live instance yet" note and verification commands) and Step 4d (the deferred CI-trigger / required-check wiring); `secretmanager.googleapis.com` added to the API-enable list.

### Task 2 — google-cloud-secret-manager dep + CI integration gate (commit 315552e)
- `backend/pyproject.toml`: verified `google-cloud-secret-manager>=2.20,<3` is already declared (added by plan 04-02 which merged before this fork) — NOT duplicated, per the locked idempotency note. No diff to pyproject.toml.
- `cloudbuild.test.yaml` (new, repo root): three steps —
  1. `start-postgres`: runs `pgvector/pgvector:pg16` as a named sidecar (`nestor-test-pg`) on the shared `cloudbuild` network.
  2. `wait-for-postgres`: polls `pg_isready` up to 60×2s.
  3. `pytest-integration`: installs the backend project + dev group via `uv`, sets `DATABASE_URL=postgresql+pg8000://test:test@nestor-test-pg:5432/test`, runs `python -m pytest tests -m integration -v`. Because conftest honors `DATABASE_URL` it bypasses testcontainers, and the `test` superuser lets `_ensure_app_superadmin` create the `app_superadmin` role out-of-band (mirroring real Cloud SQL). A non-zero pytest exit fails the build — the gate.
  - Header documents the QA-01/D-09/T-04-19 purpose and that creating the Cloud Build trigger + making it a required check is deferred to the user (RESEARCH Q2 — no CI runner exists yet).

## Key link verified
- `infra/main.tf` `SUPERADMIN_DB_PASSWORD_SECRET` -> `backend/app/db/base.py::_load_superadmin_password()`: base.py does `os.environ["SUPERADMIN_DB_PASSWORD_SECRET"]` then `client.access_secret_version(name=...)`. The env value is `projects/<p>/secrets/<id>/versions/latest`, which is exactly the resource-name form `access_secret_version` expects. Name matches verbatim.
- `cloudbuild.test.yaml` -> `backend/tests/test_cross_tenant_denial.py` (and the rest of the integration suite) via `pytest tests -m integration`.

## Threat mitigations applied (from the plan's threat register)
- T-04-16 (password in IaC/state/env): password flows only `random_password` -> `secret_version`; env carries the secret name, never the value. No plaintext literal committed.
- T-04-17 (over-broad secret access): resource-scoped `google_secret_manager_secret_iam_member`, not a project-wide grant.
- T-04-18 (app_superadmin missing on live): Terraform creates the BUILT_IN user; README Step 4c documents the deferred apply + "not on live yet" warning.
- T-04-19 (denial suite not enforced): `cloudbuild.test.yaml` runs the suite as a gating (non-zero-fails) step; README/user_setup require a required-check trigger.
- T-04-20 (name drift): the `google_sql_user` name is the exact literal `app_superadmin`, matching 0003's fixed predicate.

## Deviations from Plan

None — plan executed as written. The only plan-anticipated no-op was the `google-cloud-secret-manager` dependency: the plan said to verify-don't-duplicate (it was added by 04-02), and it was already present, so pyproject.toml was left unchanged.

## Deferred (environment + GCP-deploy-deferred standing pattern)

- `terraform fmt -check` / `terraform validate` — terraform is not installed on the dev box; format/validate is deferred to the live Cloud Shell apply (documented in infra/README.md). NOT a Self-Check failure (author-by-construction).
- Live `terraform apply` (creates the app_superadmin user, the secret + version, the scoped grant, and the new env var) — deferred to the user in GCP Cloud Shell (infra/README.md Step 4c).
- Creating the Cloud Build trigger on `cloudbuild.test.yaml` and marking it a required status check — deferred to the user (infra/README.md Step 4d; RESEARCH Q2).
- The `cloudbuild.test.yaml` step semantics were verified structurally (3 step blocks, valid YAML, no tabs, correct image + `-m integration`); a live build run is deferred (no Docker/Cloud Build on the dev box).

## Known Stubs

None — all artifacts are complete, wired, and consumed (base.py reads the env; conftest provisions the role; the gate runs the real suite).

## Self-Check: PASSED

- Files: infra/main.tf, infra/variables.tf, infra/README.md, cloudbuild.test.yaml, 04-04-SUMMARY.md — all FOUND.
- Commits: ddead39 (Task 1), 315552e (Task 2) — both FOUND.
