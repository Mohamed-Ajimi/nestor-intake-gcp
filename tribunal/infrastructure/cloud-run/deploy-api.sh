#!/usr/bin/env bash
# infrastructure/cloud-run/deploy-api.sh  (RETARGETED — Phase 13 re-home)
#
# Deploy the tribunal-api Cloud Run service into the INTAKE "Nestor Pulse" project
# (was the old standalone Tribunal build). Retargeted per Phase 13:
#   - PROJECT   -> $GOOGLE_PROJECT (the intake project; operator exports it)
#   - INSTANCE  -> the intake Cloud SQL instance ($GOOGLE_PROJECT:$REGION:$INSTANCE_NAME)
#   - SA        -> tribunal-run@${GOOGLE_PROJECT}.iam.gserviceaccount.com (Phase 14: the
#      DEDICATED least-privilege Tribunal runtime SA, WR-03/D-04b — was nestor-run in Phase 13)
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
# Phase 14 (WR-03/D-04b): the DEDICATED least-privilege Tribunal runtime SA — NOT the
# intake nestor-run SA. Making caller SA (nestor-run) != callee SA (tribunal-run) is what
# makes the tribunal-api invoker gate meaningful (D-04) and the wrong-SA proof constructible.
SA="tribunal-run@${PROJECT}.iam.gserviceaccount.com"
INSTANCE="${PROJECT}:${REGION}:${INSTANCE_NAME}"
SERVICE_NAME="tribunal-api"
REPO="${REPO:-nestor}"

IMAGE_TAG="${IMAGE_TAG:-latest}"
API_IMAGE_URL="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/tribunal-api:${IMAGE_TAG}"

# Phase 14 seam env vars (both PLAIN non-secret; read by the InternalCallerProvider):
#   TRIBUNAL_SERVICE_URL   = tribunal-api's OWN run.app URL WITHOUT a path (the OIDC audience
#                            it verifies its caller token's aud against — Pitfall 4).
#   INTAKE_RUNTIME_SA_EMAIL = the intake nestor-run SA the OIDC caller email must match.
# TRIBUNAL_SERVICE_URL cannot be known until the service is first deployed + described, so the
# runbook (§ Phase 14, Step 14.d) captures it and sets both via `--update-env-vars` post-deploy.
#
# WR-01 (14-REVIEW): `--set-env-vars` below REPLACES the service's ENTIRE plain-env set, so a
# re-run where the operator forgets to export TRIBUNAL_SERVICE_URL would deploy a revision with
# TRIBUNAL_SERVICE_URL="" — server.py then leaves the seam provider uninstalled and every seam
# request fails (a silent fail-closed seam outage). Guard: self-heal from the live service's
# own URL first, then FAIL FAST if still empty. The only legitimate empty case is the very
# FIRST deploy (Step 14.c, before the URL exists) — allow it explicitly via ALLOW_EMPTY_SEAM_ENV=1.
INTAKE_RUNTIME_SA_EMAIL="${INTAKE_RUNTIME_SA_EMAIL:-nestor-run@${PROJECT}.iam.gserviceaccount.com}"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

if [ -z "${TRIBUNAL_SERVICE_URL:-}" ]; then
  # Self-heal: the seam audience IS this service's own run.app URL (no path — Pitfall 4).
  TRIBUNAL_SERVICE_URL="$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT}" \
    --format='value(status.url)' 2>/dev/null || true)"
  [ -n "${TRIBUNAL_SERVICE_URL}" ] && \
    echo "==> TRIBUNAL_SERVICE_URL not exported; self-healed from the live service: ${TRIBUNAL_SERVICE_URL}"
fi

if [ -z "${TRIBUNAL_SERVICE_URL}" ] && [ "${ALLOW_EMPTY_SEAM_ENV:-0}" != "1" ]; then
  echo "ERROR: TRIBUNAL_SERVICE_URL is empty — not exported AND the service is not yet describable." >&2
  echo "       Deploying now would wipe the live seam env and fail the seam closed (WR-01)."       >&2
  echo "       Either export TRIBUNAL_SERVICE_URL=<captured run.app URL, NO path> (Step 14.d),"    >&2
  echo "       or set ALLOW_EMPTY_SEAM_ENV=1 for the FIRST deploy only (Step 14.c) and then"      >&2
  echo "       run Step 14.d to set the seam env live."                                            >&2
  exit 1
fi

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
# with no error at deploy time. Self-heal from the live revision first (the same shape as
# the TRIBUNAL_SERVICE_URL guard above); the literal fallback below is a FIRST-DEPLOY
# default only, never an assertion about what is live. `nestor-api` deliberately stays on
# `Nestor_Claude` and is not touched by this script.
# ---------------------------------------------------------------------------
TRIBUNAL_SERPAPI_SECRET="${TRIBUNAL_SERPAPI_SECRET:-Nestor_SerpApi}"

if [ -z "${TRIBUNAL_ANTHROPIC_SECRET:-}" ]; then
  TRIBUNAL_ANTHROPIC_SECRET="$(gcloud run services describe "${SERVICE_NAME}" \
    --region="${REGION}" --project="${PROJECT}" \
    --flatten='spec.template.spec.containers[].env[]' \
    --filter='spec.template.spec.containers.env.name=ANTHROPIC_API_KEY' \
    --format='value(spec.template.spec.containers.env.valueFrom.secretKeyRef.name)' \
    2>/dev/null | head -n1 || true)"
  if [ -n "${TRIBUNAL_ANTHROPIC_SECRET}" ]; then
    echo "==> ANTHROPIC secret self-healed from the live revision: ${TRIBUNAL_ANTHROPIC_SECRET}"
  fi
fi
# Not describable (first deploy) or ANTHROPIC_API_KEY not currently mapped: fall back to the
# credit-bearing secret, NOT the Phase-13 original. A secret NAME is configuration, not a
# secret — echoing it is safe; the VALUE is never read, echoed or logged by this script.
TRIBUNAL_ANTHROPIC_SECRET="${TRIBUNAL_ANTHROPIC_SECRET:-Nestor_Claude2}"
echo "==> ANTHROPIC_API_KEY will be mounted from secret: ${TRIBUNAL_ANTHROPIC_SECRET}"

TRIBUNAL_SECRETS="\
DATABASE_URL=DATABASE_URL:latest,\
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
  --set-env-vars="NESTOR_ENV=prod,NESTOR_TRIBUNAL_UNCAPPED=1,TRIBUNAL_SERVICE_URL=${TRIBUNAL_SERVICE_URL},INTAKE_RUNTIME_SA_EMAIL=${INTAKE_RUNTIME_SA_EMAIL}" \
  --set-secrets="${TRIBUNAL_SECRETS}"

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
