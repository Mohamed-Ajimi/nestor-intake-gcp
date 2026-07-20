#!/usr/bin/env bash
# infrastructure/cloud-run/artifact-registry-create.sh
#
# Idempotent: creates the nestor-pulse Docker repository in Artifact Registry
# (europe-west1) if it does not already exist. Safe to re-run at any time;
# no-ops if the repo is present.
#
# Mirrors the early-exit guard style from infrastructure/gcloud/bootstrap.sh.
#
# Plan: 01-10.5 Task 2.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-project-cb01b861-cb4a-438d-b9a}"
REGION="${REGION:-europe-west1}"
REPO="nestor-pulse"

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

echo "==> Artifact Registry: checking $REGION-docker.pkg.dev/$PROJECT/$REPO"

if gcloud artifacts repositories describe "$REPO" \
     --location="$REGION" \
     --project="$PROJECT" \
     --quiet >/dev/null 2>&1; then
  echo "==> Repository $REPO already exists -- no-op"
else
  echo "==> Creating Docker repository $REPO in $REGION"
  gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Nestor Pulse Cloud Run images" \
    --project="$PROJECT" \
    --quiet
  echo "==> Created: $REGION-docker.pkg.dev/$PROJECT/$REPO"
fi

echo
echo "=================================================================="
echo "Artifact Registry: $REGION-docker.pkg.dev/$PROJECT/$REPO  READY"
echo "=================================================================="
