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

# ---------------------------------------------------------------------------
# Secret composition (Phase 15.2 — the D10 own-researcher SERPAPI key)
#
# `--set-secrets` REPLACES the service's ENTIRE secret set on every deploy, exactly as
# `--set-env-vars` does for the plain env (WR-01). Every mapping the service needs must
# therefore appear in the composed list below — anything omitted is DROPPED from the next
# revision. This is the whole reason the list is built in a variable rather than inlined.
#
# LIVE-VS-SCRIPT DRIFT, observed 2026-07-21: both Tribunal services were switched LIVE to
# mount ANTHROPIC_API_KEY from `Nestor_Claude2` (the account that holds credits) while this
# script still hardcoded `Nestor_Claude`. An unguarded re-run therefore silently REPOINTED
# the Anthropic key back at the low-credit secret — walling a real research run mid-flight
# with no error at deploy time. The worker is the run-EXECUTING side, so it is the service
# that would actually die on the wall.
#
# WHAT ACTUALLY HAPPENED NEXT, and why this block was inverted (operator decision 2026-07-27):
# the 2026-07-25 phase-15.1 deploy ran this script, which then ADOPTED the live value. Since
# the live value had already been reverted to `Nestor_Claude`, self-healing simply re-inherited
# the drift it was written to prevent, and all three services were verified on `Nestor_Claude`
# on 2026-07-27. Reading the live value can never correct a clobber — it only ratifies it.
# So the COMMITTED default now wins, and the live value is read solely to REPORT divergence.
# Override for a one-off deploy with `TRIBUNAL_ANTHROPIC_SECRET=... ./deploy-worker.sh`.
# `nestor-api` is ALSO on `Nestor_Claude2` as of 2026-07-27 (it makes Anthropic calls for the
# intake skills); it is deployed by its own script, not this one.
# ---------------------------------------------------------------------------
TRIBUNAL_SERPAPI_SECRET="${TRIBUNAL_SERPAPI_SECRET:-Nestor_SERP}"

# Committed intent wins. A secret NAME is configuration, not a secret — echoing it is safe;
# the VALUE is never read, echoed or logged by this script.
TRIBUNAL_ANTHROPIC_SECRET="${TRIBUNAL_ANTHROPIC_SECRET:-Nestor_Claude2}"

LIVE_ANTHROPIC_SECRET="$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" --project="${PROJECT}" \
  --flatten='spec.template.spec.containers[].env[]' \
  --filter='spec.template.spec.containers.env.name=ANTHROPIC_API_KEY' \
  --format='value(spec.template.spec.containers.env.valueFrom.secretKeyRef.name)' \
  2>/dev/null | head -n1 || true)"
if [ -n "${LIVE_ANTHROPIC_SECRET}" ] && \
   [ "${LIVE_ANTHROPIC_SECRET}" != "${TRIBUNAL_ANTHROPIC_SECRET}" ]; then
  echo "==> NOTE: live revision mounts '${LIVE_ANTHROPIC_SECRET}'; this deploy REPOINTS it to" >&2
  echo "          '${TRIBUNAL_ANTHROPIC_SECRET}' (operator decision 2026-07-27). Intentional."  >&2
fi
echo "==> ANTHROPIC_API_KEY will be mounted from secret: ${TRIBUNAL_ANTHROPIC_SECRET}"

TRIBUNAL_SECRETS="\
DATABASE_URL=DATABASE_URL_WORKER:latest,\
AUDIT_GCS_BUCKET=AUDIT_GCS_BUCKET:latest,\
ANTHROPIC_API_KEY=${TRIBUNAL_ANTHROPIC_SECRET}:latest,\
GOOGLE_API_KEY=Nestor_Gemini:latest,\
OPENAI_API_KEY=Nestor_OpenAI:latest"

# Append the SERPAPI mapping ONLY when the secret actually exists. Binding a non-existent
# secret fails the whole `gcloud run deploy`, and a missing D10 stream must never block
# shipping the rest of the phase.
if gcloud secrets describe "${TRIBUNAL_SERPAPI_SECRET}" --project="${PROJECT}" >/dev/null 2>&1; then
  TRIBUNAL_SECRETS="${TRIBUNAL_SECRETS},SERPAPI_API_KEY=${TRIBUNAL_SERPAPI_SECRET}:latest"
  echo "==> own-researcher key will be mounted from secret: ${TRIBUNAL_SERPAPI_SECRET}"
else
  echo "" >&2
  echo "WARNING: Secret Manager secret '${TRIBUNAL_SERPAPI_SECRET}' does not exist in ${PROJECT}." >&2
  echo "         Deploying WITHOUT the own-researcher key. This is not a deploy failure:"        >&2
  echo "         the SerpApi availability probe reports 'serpapi_key_missing', the breaker"      >&2
  echo "         opens at startup, and runs finish as clean 3-stream 'completed_degraded'"       >&2
  echo "         runs (D-12) instead of crashing."                                               >&2
  echo "         V-02 #6 (own-researcher contributed facts) CANNOT be proven in this state."     >&2
  echo "         To fix: § Phase 15.2 Step 15.2.b of infra/DEPLOY-RUNBOOK.md, then re-run."      >&2
  echo "" >&2
fi

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
  --set-secrets="${TRIBUNAL_SECRETS}"

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
