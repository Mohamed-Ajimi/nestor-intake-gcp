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
#
# ---------------------------------------------------------------------------
# THIS SCRIPT TOUCHES PAID INFRASTRUCTURE, AND THERE ARE TWO PROJECTS NOW.
# ---------------------------------------------------------------------------
# A script that GUESSES its target lands a client release in the dev project, or
# a dev experiment in front of the client. So GOOGLE_PROJECT is REQUIRED and has
# NO default: this script used to default to the dev project id, which is the
# exact failure it now refuses to make. Export it explicitly, every time.
#
# Optional but recommended: GCLOUD_ACCOUNT. `gcloud auth login` has silently
# switched BOTH account and project mid-session on this machine, there are four
# accounts on it, and deploy scripts inherit ambient gcloud config without
# complaining. Setting it pins --account on every call below.
# ---------------------------------------------------------------------------

set -euo pipefail

# Canonical name is GOOGLE_PROJECT (deploy-api.sh / deploy-worker.sh already use it);
# GOOGLE_CLOUD_PROJECT is accepted for back-compat. Neither has a literal default.
PROJECT="${GOOGLE_PROJECT:-${GOOGLE_CLOUD_PROJECT:?set GOOGLE_PROJECT to the target project id — there is no default, and there must not be: the default used to be the DEV project}}"
REGION="${REGION:-europe-west1}"
REPO="nestor-pulse"

GCLOUD_ACCOUNT="${GCLOUD_ACCOUNT:-}"
ACCOUNT_ARGS=()
if [ -n "$GCLOUD_ACCOUNT" ]; then
  ACCOUNT_ARGS=(--account="$GCLOUD_ACCOUNT")
else
  echo "WARNING: GCLOUD_ACCOUNT is not set — using whatever account gcloud is currently" >&2
  echo "         configured with. That config has reverted mid-session on this machine," >&2
  echo "         and four accounts are logged in. Export GCLOUD_ACCOUNT to pin it." >&2
fi

command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud not on PATH"; exit 1; }

echo "==> Artifact Registry: checking $REGION-docker.pkg.dev/$PROJECT/$REPO"

if gcloud "${ACCOUNT_ARGS[@]}" artifacts repositories describe "$REPO" \
     --location="$REGION" \
     --project="$PROJECT" \
     --quiet >/dev/null 2>&1; then
  echo "==> Repository $REPO already exists -- no-op"
else
  echo "==> Creating Docker repository $REPO in $REGION"
  gcloud "${ACCOUNT_ARGS[@]}" artifacts repositories create "$REPO" \
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
