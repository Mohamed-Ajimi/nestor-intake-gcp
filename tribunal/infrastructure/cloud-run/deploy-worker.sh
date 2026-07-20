#!/usr/bin/env bash
# infrastructure/cloud-run/deploy-worker.sh  (RETARGETED — Phase 13 re-home)
#
# Deploy the tribunal-worker Cloud Run service into the INTAKE "Nestor Pulse"
# project (was the old standalone Tribunal build). Retargeted per Phase 13:
#   - PROJECT   -> $GOOGLE_PROJECT (the intake project; operator exports it)
#   - INSTANCE  -> the intake Cloud SQL instance ($GOOGLE_PROJECT:$REGION:$INSTANCE_NAME)
#   - SA        -> tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com (Phase 14: the
#      DEDICATED least-privilege Tribunal runtime SA, WR-03/D-04b — was nestor-run in Phase 13)
#   - image     -> europe-west1-docker.pkg.dev/${GOOGLE_PROJECT}/nestor/tribunal-worker:<tag>
#     (the existing `nestor` Artifact Registry repo — no new repo; built via Cloud Build,
#      NOT locally: the dev box has no Docker. See tribunal/cloudbuild.worker.yaml.)
#
# DB role (migration 0008): the worker connects as worker_user (sourced from the
#   DATABASE_URL_WORKER secret, NOT app_user's DATABASE_URL) so it can claim queued
#   runs across ALL tenants. Cloud SQL forbids BYPASSRLS, so worker_user matches a
#   permissive per-table "worker_all" RLS policy on the `tribunal` schema ONLY (never
#   `nestor` — isolation firewall, T-13-09). See
#   nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py.
#
# Worker design (D-04 always-on + D-08 concurrency):
#   - min-instances=1 (always-on poll loop; SKIP LOCKED)
#   - max-instances=5 (D-08 — size for 5+ concurrent runs; the per-run advisory lock
#     added in runs/execute.py makes multiple pollers safe)
#   - --no-cpu-throttling: CPU allocated even with no inbound HTTP (worker polls Postgres
#     on its own schedule and runs ~35-min pipelines off the request path)
#   - No public HTTP; --no-allow-unauthenticated for defence-in-depth
#   - timeout=3600: covers a full deep-research run (~35 min)
#   - NESTOR_TRIBUNAL_UNCAPPED=1 (D-07 — uncapped this phase)
#
# Cost implication: always-on 1 vCPU 2Gi instance ~ $5-10/month idle.
# To pause the worker after a session: `--min-instances=0` (see the footer).
#
# Re-run safe (zero-downtime revisions).

set -euo pipefail

PROJECT="${GOOGLE_PROJECT:?export GOOGLE_PROJECT to the intake project id}"
REGION="${REGION:-europe-west1}"
INSTANCE_NAME="${INSTANCE_NAME:-nestor-pg}"
# Phase 14 (WR-03/D-04b): the DEDICATED least-privilege Tribunal runtime SA — NOT the
# intake nestor-run SA. A compromised worker reaches only the Tribunal secrets + audit
# bucket (no identitytoolkit.admin, no intake superadmin secret, no intake uploads bucket).
SA="tribunal-run@${PROJECT}.iam.gserviceaccount.com"
INSTANCE="${PROJECT}:${REGION}:${INSTANCE_NAME}"
SERVICE_NAME="tribunal-worker"
REPO="${REPO:-nestor}"

# Image tag: pass IMAGE_TAG explicitly, else default to the built-latest convention.
# The image is built by tribunal/cloudbuild.worker.yaml (Cloud Build — no local Docker).
IMAGE_TAG="${IMAGE_TAG:-latest}"
WORKER_IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/tribunal-worker:${IMAGE_TAG}"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

echo "==> Deploying ${SERVICE_NAME} with image: ${WORKER_IMAGE_URL}"

REVISION_SUFFIX="${IMAGE_TAG//[^A-Za-z0-9-]/-}-$(date +%H%M%S)"

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
  --max-instances=5 \
  --timeout=3600 \
  --revision-suffix="${REVISION_SUFFIX}" \
  --set-env-vars="NESTOR_ENV=prod,NESTOR_WORKER_POLL_INTERVAL=2.0,NESTOR_WORKER_STALE_MINUTES=60,NESTOR_TRIBUNAL_UNCAPPED=1" \
  --set-secrets="\
DATABASE_URL=DATABASE_URL_WORKER:latest,\
AUDIT_GCS_BUCKET=AUDIT_GCS_BUCKET:latest,\
ANTHROPIC_API_KEY=Nestor_Claude:latest,\
GOOGLE_API_KEY=Nestor_Gemini:latest,\
OPENAI_API_KEY=Nestor_OpenAI:latest"

echo
echo "=================================================================="
echo "Deployed: ${SERVICE_NAME}"
echo "  Project:   ${PROJECT}"
echo "  SA:        ${SA}"
echo "  Cloud SQL: ${INSTANCE}"
echo "  min-instances=1 (always-on poll loop, D-04)"
echo "  max-instances=5 (D-08 concurrency — advisory lock makes >1 poller safe)"
echo "  Revision suffix: ${REVISION_SUFFIX}"
echo ""
echo "To pause (cost discipline): "
echo "  gcloud run services update ${SERVICE_NAME} --min-instances=0 --region=${REGION} --project=${PROJECT}"
echo "=================================================================="
