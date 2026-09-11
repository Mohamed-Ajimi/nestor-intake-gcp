#!/usr/bin/env bash
# infrastructure/cloud-run/build-and-push.sh
#
# Build both Cloud Run images via Cloud Build (server-side, no local Docker
# daemon required). Tags each image with the current git SHA + :latest.
# Writes API_IMAGE_URL and WORKER_IMAGE_URL to .last-build.env so the
# deploy scripts can source them.
#
# Build path decision (Task 1 -- 01-10.5): gcloud builds submit (cloud-build).
# Rationale: no Docker daemon required on the dev machine; build env is
# consistent; logs persist in GCP Cloud Build history; identical code path
# to the future GHA workflow.
#
# Plan: 01-10.5 Task 2.
# Re-run safe -- each invocation produces a new SHA-tagged image.
#
# ---------------------------------------------------------------------------
# THIS SCRIPT BUILDS AND PUSHES PAID INFRASTRUCTURE, AND THERE ARE TWO PROJECTS NOW.
# ---------------------------------------------------------------------------
# A script that GUESSES its target lands a client release in the dev project, or
# a dev experiment in front of the client. So GOOGLE_PROJECT is REQUIRED and has
# NO default: this script used to default to the dev project id, which is the
# exact failure it now refuses to make. It also calls artifact-registry-create.sh,
# so the two MUST agree on the variable name — they now share this one.
#
# Optional but recommended: GCLOUD_ACCOUNT. `gcloud auth login` has silently
# switched BOTH account and project mid-session on this machine, there are four
# accounts on it, and deploy scripts inherit ambient gcloud config without
# complaining. Setting it pins --account on every call below, and it is exported
# so the artifact-registry-create.sh child inherits the same pin.
# ---------------------------------------------------------------------------

set -euo pipefail

# Canonical name is GOOGLE_PROJECT (deploy-api.sh / deploy-worker.sh already use it);
# GOOGLE_CLOUD_PROJECT is accepted for back-compat. Neither has a literal default.
PROJECT="${GOOGLE_PROJECT:-${GOOGLE_CLOUD_PROJECT:?set GOOGLE_PROJECT to the target project id — there is no default, and there must not be: the default used to be the DEV project}}"
REGION="${REGION:-europe-west1}"
REPO="nestor-pulse"
REGISTRY="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}"
# NOTE: the `nestor-pulse-runtime@` local part belongs to the RETIRED standalone-project
# layout — it is a THIRD service-account name, matching neither `nestor-run` nor
# `tribunal-run`, which are the ones Terraform actually manages today. Left as-is
# deliberately (it derives from ${PROJECT}, so it follows the required project), but do
# not read it as current: override with RUNTIME_SA_EMAIL if a caller needs it to be right.
RUNTIME_SA="${RUNTIME_SA_EMAIL:-nestor-pulse-runtime@${PROJECT}.iam.gserviceaccount.com}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"

GCLOUD_ACCOUNT="${GCLOUD_ACCOUNT:-}"
ACCOUNT_ARGS=()
if [ -n "$GCLOUD_ACCOUNT" ]; then
  ACCOUNT_ARGS=(--account="$GCLOUD_ACCOUNT")
  export GCLOUD_ACCOUNT
else
  echo "WARNING: GCLOUD_ACCOUNT is not set — using whatever account gcloud is currently" >&2
  echo "         configured with. That config has reverted mid-session on this machine," >&2
  echo "         and four accounts are logged in. Export GCLOUD_ACCOUNT to pin it." >&2
fi
# The child script reads the SAME project variable; export so it cannot diverge.
export GOOGLE_PROJECT="$PROJECT"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

# Git SHA for tagging (short SHA, 8 chars)
GIT_SHA="$(git -C "$REPO_ROOT" rev-parse --short=8 HEAD 2>/dev/null || echo "local")"
echo "==> Build SHA: ${GIT_SHA}"

API_IMAGE="${REGISTRY}/api:${GIT_SHA}"
WORKER_IMAGE="${REGISTRY}/worker:${GIT_SHA}"
API_LATEST="${REGISTRY}/api:latest"
WORKER_LATEST="${REGISTRY}/worker:latest"

# ---- Ensure Artifact Registry repo exists ----
bash "${SCRIPT_DIR}/artifact-registry-create.sh"

# ---- Build API image ----
echo
echo "==> Building API image: ${API_IMAGE}"
# gcloud builds submit with a custom Dockerfile path uses --config pointing
# at a cloudbuild.yaml, OR we use the inline build config approach with
# a temporary yaml. The simplest approach: write a temp cloudbuild.yaml.
API_BUILD_YAML=$(mktemp /tmp/cloudbuild-api-XXXXXX.yaml)
cat > "$API_BUILD_YAML" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - build
      - '-f'
      - 'infrastructure/cloud-run/api/Dockerfile'
      - '-t'
      - '${API_IMAGE}'
      - '-t'
      - '${API_LATEST}'
      - '.'
images:
  - '${API_IMAGE}'
  - '${API_LATEST}'
EOF

gcloud "${ACCOUNT_ARGS[@]}" builds submit \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --service-account="projects/${PROJECT}/serviceAccounts/${RUNTIME_SA}" \
  --default-buckets-behavior=REGIONAL_USER_OWNED_BUCKET \
  --config="${API_BUILD_YAML}" \
  "${REPO_ROOT}"
rm -f "$API_BUILD_YAML"
echo "==> API image built: ${API_IMAGE}"

# ---- Build worker image ----
echo
echo "==> Building worker image: ${WORKER_IMAGE}"
WORKER_BUILD_YAML=$(mktemp /tmp/cloudbuild-worker-XXXXXX.yaml)
cat > "$WORKER_BUILD_YAML" <<EOF
steps:
  - name: 'gcr.io/cloud-builders/docker'
    args:
      - build
      - '-f'
      - 'infrastructure/cloud-run/worker/Dockerfile'
      - '-t'
      - '${WORKER_IMAGE}'
      - '-t'
      - '${WORKER_LATEST}'
      - '.'
images:
  - '${WORKER_IMAGE}'
  - '${WORKER_LATEST}'
EOF

gcloud "${ACCOUNT_ARGS[@]}" builds submit \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --service-account="projects/${PROJECT}/serviceAccounts/${RUNTIME_SA}" \
  --default-buckets-behavior=REGIONAL_USER_OWNED_BUCKET \
  --config="${WORKER_BUILD_YAML}" \
  "${REPO_ROOT}"
rm -f "$WORKER_BUILD_YAML"
echo "==> Worker image built: ${WORKER_IMAGE}"

# ---- Persist image URLs for deploy scripts ----
ENV_FILE="${SCRIPT_DIR}/.last-build.env"
cat > "${ENV_FILE}" <<EOF
# Auto-generated by build-and-push.sh on $(date -u +"%Y-%m-%dT%H:%M:%SZ")
# GIT_SHA: ${GIT_SHA}
API_IMAGE_URL=${API_IMAGE}
WORKER_IMAGE_URL=${WORKER_IMAGE}
EOF

echo
echo "=================================================================="
echo "Build complete"
echo "  API    image: ${API_IMAGE}"
echo "  Worker image: ${WORKER_IMAGE}"
echo "  Env file:     ${ENV_FILE}"
echo "=================================================================="
