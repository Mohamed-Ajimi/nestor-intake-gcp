#!/usr/bin/env bash
# infrastructure/cloud-run/deploy-api.sh  (RETARGETED — Phase 13 re-home)
#
# Deploy the tribunal-api Cloud Run service into the INTAKE "Nestor Pulse" project
# (was the old standalone Tribunal build). Retargeted per Phase 13:
#   - PROJECT   -> $GOOGLE_PROJECT (the intake project; operator exports it)
#   - INSTANCE  -> the intake Cloud SQL instance ($GOOGLE_PROJECT:$REGION:$INSTANCE_NAME)
#   - SA        -> nestor-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com (the intake runtime SA)
#   - image     -> europe-west1-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-api:<tag>
#     (the existing `nestor` Artifact Registry repo — no new repo; built via Cloud Build,
#      NOT locally. See tribunal/cloudbuild.api.yaml.)
#
# Prerequisites:
#   - Image built via Cloud Build (tribunal/cloudbuild.api.yaml) — the dev box has no Docker.
#   - The intake Cloud SQL instance must be RUNNABLE.
#   - All secrets in --set-secrets must exist in Secret Manager (see § Phase 13 of
#     infra/DEPLOY-RUNBOOK.md — create + out-of-band value seed).
#
# Security: no API keys or secrets are baked into the image. Secrets are mounted as env
# vars at deploy time via --set-secrets (reference only, never the value). The DATABASE_URL
# secret carries the Cloud SQL Unix socket asyncpg DSN:
#   postgresql+asyncpg://app_user:PW@/<db>?host=/cloudsql/PROJECT:REGION:INSTANCE
# db/base.py reads DATABASE_URL from os.environ directly.
#
# Re-run safe (zero-downtime revisions).

set -euo pipefail

PROJECT="${GOOGLE_PROJECT:?export GOOGLE_PROJECT to the intake project id}"
REGION="${REGION:-europe-west1}"
INSTANCE_NAME="${INSTANCE_NAME:-nestor-pg}"
SA="nestor-run@${PROJECT}.iam.gserviceaccount.com"
INSTANCE="${PROJECT}:${REGION}:${INSTANCE_NAME}"
SERVICE_NAME="tribunal-api"
REPO="${REPO:-nestor}"

IMAGE_TAG="${IMAGE_TAG:-latest}"
API_IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/tribunal-api:${IMAGE_TAG}"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

echo "==> Deploying ${SERVICE_NAME} with image: ${API_IMAGE_URL}"

REVISION_SUFFIX="${IMAGE_TAG//[^A-Za-z0-9-]/-}-$(date +%H%M%S)"

gcloud run deploy "${SERVICE_NAME}" \
  --project="${PROJECT}" \
  --region="${REGION}" \
  --image="${API_IMAGE_URL}" \
  --service-account="${SA}" \
  --add-cloudsql-instances="${INSTANCE}" \
  --no-allow-unauthenticated \
  --memory=1Gi \
  --cpu=1 \
  --concurrency=80 \
  --min-instances=0 \
  --max-instances=3 \
  --timeout=300 \
  --revision-suffix="${REVISION_SUFFIX}" \
  --set-env-vars="NESTOR_ENV=prod,NESTOR_TRIBUNAL_UNCAPPED=1" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL:latest,\
AUDIT_GCS_BUCKET=AUDIT_GCS_BUCKET:latest,\
ANTHROPIC_API_KEY=Nestor_Claude:latest,\
GOOGLE_API_KEY=Nestor_Gemini:latest,\
OPENAI_API_KEY=Nestor_OpenAI:latest"

# Print the deployed URL
API_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --format='value(status.url)' 2>/dev/null || echo "")

echo
echo "=================================================================="
echo "Deployed: ${SERVICE_NAME}"
echo "  Project:   ${PROJECT}"
echo "  URL:       ${API_URL}"
echo "  Revision suffix: ${REVISION_SUFFIX}"
echo "  SA:        ${SA}"
echo "  Cloud SQL: ${INSTANCE}"
echo "=================================================================="
