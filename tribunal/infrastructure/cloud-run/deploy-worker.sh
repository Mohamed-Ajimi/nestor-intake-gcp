#!/usr/bin/env bash
# infrastructure/cloud-run/deploy-worker.sh
#
# Deploy the nestor-pulse-worker Cloud Run service.
#
# DB role (migration 0008): the worker connects as worker_user (sourced from
#   the DATABASE_URL_WORKER secret, NOT app_user's DATABASE_URL) so it can claim
#   queued runs across ALL tenants. Cloud SQL forbids BYPASSRLS, so worker_user
#   instead matches a permissive per-table "worker_all" RLS policy; the API stays
#   tenant-scoped as app_user. See nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py.
#
# Worker design (D-09):
#   - min-instances=1, max-instances=1 (always-on single worker; SKIP LOCKED)
#   - --no-cpu-throttling: CPU allocated even when no HTTP requests arrive
#     (worker polls Postgres on its own schedule)
#   - No public HTTP traffic; --no-allow-unauthenticated for defence-in-depth
#   - timeout=3600: long timeout to cover a full deep-research run (~35 min)
#
# Cost implication: always-on 1 vCPU 2Gi instance ~ $5-10/month idle.
# To pause the worker after a session: see DEPLOY.md § Tear down.
#
# Plan: 01-10.5 Task 4.
# Re-run safe.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-project-cb01b861-cb4a-438d-b9a}"
REGION="${REGION:-europe-west1}"
SA="nestor-pulse-runtime@${PROJECT}.iam.gserviceaccount.com"
INSTANCE="${PROJECT}:${REGION}:nestor-prod-pg"
SERVICE_NAME="nestor-pulse-worker"
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
if [[ -z "${WORKER_IMAGE_URL:-}" ]]; then
  echo "ERROR: WORKER_IMAGE_URL is empty in ${ENV_FILE}"
  exit 1
fi
echo "==> Deploying ${SERVICE_NAME} with image: ${WORKER_IMAGE_URL}"

GIT_SHA="$(git -C "${SCRIPT_DIR}/../.." rev-parse --short=8 HEAD 2>/dev/null || echo "local")"
REVISION_SUFFIX="${GIT_SHA}-$(date +%H%M%S)"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${WORKER_IMAGE_URL}" \
  --service-account="${SA}" \
  --add-cloudsql-instances="${INSTANCE}" \
  --no-allow-unauthenticated \
  --memory=2Gi \
  --cpu=1 \
  --no-cpu-throttling \
  --min-instances=1 \
  --max-instances=1 \
  --timeout=3600 \
  --revision-suffix="${REVISION_SUFFIX}" \
  --set-env-vars="GCP_PROJECT=${PROJECT},NESTOR_ENV=prod,CLOUDSQL_INSTANCE=${INSTANCE},NESTOR_WORKER_POLL_INTERVAL=2.0,NESTOR_WORKER_STALE_MINUTES=60,NESTOR_TRIBUNAL_UNCAPPED=1" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL_WORKER:latest,\
ANTHROPIC_API_KEY=Nestor_Claude:latest,\
GOOGLE_API_KEY=Nestor_Gemini:latest,\
OPENAI_API_KEY=Nestor_OpenAI:latest"

echo
echo "=================================================================="
echo "Deployed: ${SERVICE_NAME}"
echo "  SA:      ${SA}"
echo "  Cloud SQL: ${INSTANCE}"
echo "  min-instances=1 (always-on poll loop)"
echo "  max-instances=1 (D-09 single-worker invariant)"
echo "  Revision suffix: ${REVISION_SUFFIX}"
echo ""
echo "To pause (cost discipline): "
echo "  gcloud run services update ${SERVICE_NAME} --min-instances=0 --region=${REGION}"
echo "=================================================================="
