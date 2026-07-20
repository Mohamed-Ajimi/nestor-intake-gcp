#!/usr/bin/env bash
# infrastructure/cloud-run/deploy-api.sh
#
# Deploy the nestor-pulse-api Cloud Run service.
#
# Prerequisites:
#   - bash infrastructure/cloud-run/build-and-push.sh (creates .last-build.env)
#   - Cloud SQL nestor-prod-pg must be RUNNABLE:
#       gcloud sql instances patch nestor-prod-pg --activation-policy=ALWAYS
#   - All secrets listed in --set-secrets must exist in Secret Manager
#     (run infrastructure/gcloud/secret-manager-bootstrap.sh if any are missing).
#
# Security (T-10.5-01): no API keys or secrets are baked into the image.
# Secrets are mounted as env vars at deploy time via --set-secrets.
# The DATABASE_URL secret already contains the Cloud SQL Unix socket path:
#   postgresql+asyncpg://app_user:PW@/nestor_db?host=/cloudsql/PROJECT:REGION:INSTANCE
# db/base.py reads DATABASE_URL from os.environ directly.
#
# Plan: 01-10.5 Task 4.
# Re-run safe -- Cloud Run deploys are zero-downtime revisions.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-project-cb01b861-cb4a-438d-b9a}"
REGION="${REGION:-europe-west1}"
SA="nestor-pulse-runtime@${PROJECT}.iam.gserviceaccount.com"
INSTANCE="${PROJECT}:${REGION}:nestor-prod-pg"
SERVICE_NAME="nestor-pulse-api"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

# Source image URLs from the last build
ENV_FILE="${SCRIPT_DIR}/.last-build.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: ${ENV_FILE} not found. Run build-and-push.sh first."
  exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"
if [[ -z "${API_IMAGE_URL:-}" ]]; then
  echo "ERROR: API_IMAGE_URL is empty in ${ENV_FILE}"
  exit 1
fi
echo "==> Deploying ${SERVICE_NAME} with image: ${API_IMAGE_URL}"

# Revision suffix for auditable rollback:
#   gcloud run services update-traffic nestor-pulse-api \
#     --to-revisions=<sha>-00001=100 --region=europe-west1
GIT_SHA="$(git -C "${SCRIPT_DIR}/../.." rev-parse --short=8 HEAD 2>/dev/null || echo "local")"
REVISION_SUFFIX="${GIT_SHA}-$(date +%H%M%S)"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${API_IMAGE_URL}" \
  --service-account="${SA}" \
  --add-cloudsql-instances="${INSTANCE}" \
  --allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --concurrency=80 \
  --min-instances=0 \
  --max-instances=3 \
  --timeout=300 \
  --revision-suffix="${REVISION_SUFFIX}" \
  --set-env-vars="GCP_PROJECT=${PROJECT},NESTOR_ENV=prod,CLOUDSQL_INSTANCE=${INSTANCE},NESTOR_TRIBUNAL_UNCAPPED=1" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL:latest,\
ANTHROPIC_API_KEY=Nestor_Claude:latest,\
GOOGLE_API_KEY=Nestor_Gemini:latest,\
OPENAI_API_KEY=Nestor_OpenAI:latest,\
IDENTITY_PLATFORM_PROJECT_ID=IDENTITY_PLATFORM_PROJECT_ID:latest,\
IDENTITY_PLATFORM_SMOKE_USER_PW=IDENTITY_PLATFORM_SMOKE_USER_PW:latest,\
IDENTITY_PLATFORM_WEB_API_KEY=IDENTITY_PLATFORM_WEB_API_KEY:latest"

# Print the deployed URL
API_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo
echo "=================================================================="
echo "Deployed: ${SERVICE_NAME}"
echo "  URL:     ${API_URL}"
echo "  Revision suffix: ${REVISION_SUFFIX}"
echo "  SA:      ${SA}"
echo "  Cloud SQL: ${INSTANCE}"
echo ""
echo "Smoke:"
echo "  curl -sf ${API_URL}/healthz  -> 200 (no auth)"
echo "  curl -sf ${API_URL}/readyz   -> 200 (no auth; needs Cloud SQL RUNNABLE)"
echo "=================================================================="
