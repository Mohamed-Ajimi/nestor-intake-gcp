#!/usr/bin/env bash
# infra/promote.sh — promote ONE release, in the one order that is safe.
#
# Build once, promote the same image DIGESTS, never rebuild for the client
# (D-23.4-04). This script is the whole promotion: it is what a Cloud Build
# trigger runs, and it is what the operator runs by hand until the triggers
# exist. `cloudbuild.deploy-dev.yaml` and `cloudbuild.promote-client.yaml` both
# call it, so the path the client depends on is exercised on every dev deploy.
#
# ---------------------------------------------------------------------------
# THE ORDER, AND WHY EACH POSITION IS WHERE IT IS
# ---------------------------------------------------------------------------
#   1  resolve digests        tags are MUTABLE; the digest is the release identity
#   1b verify in target       "same digest" is checked, not assumed
#   2  idle gate              BEFORE anything is applied, so a refusal costs nothing
#   3a nestor-migrate         schema before the code that needs it
#   3b tribunal-migrate
#   4  nestor-api
#   5  frontend               a BUILD, not a promotion (see step 5's comment)
#   6  tribunal-api
#   7  idle gate AGAIN        steps 3-6 take minutes; a run can start in that window
#   8  tribunal-worker        LAST, and only behind a green gate
#   9  smoke                  a broken promotion is visible in the same minute
#   10 write the tags back    Terraform's record and the running images agree
#
# TWO RULES HERE HAVE ALREADY COST REAL MONEY, WHICH IS WHY THEY ARE MECHANICAL:
#
#   * A worker deploy BOOTS the poll loop, and the loop CLAIMS FIRST and SLEEPS
#     LAST. `--min-instances=0` is NOT protection; an empty queue is the only
#     protection (the 2026-07-28 incident). Hence the gate at steps 2 and 7, and
#     hence the worker being last.
#   * `gcloud builds submit | tail` reports the PIPE's status, so a FAILED build
#     exits 0. Nothing here reads a build's exit code through a pipe: builds are
#     confirmed with `gcloud builds describe <FULL UUID>`. Short ids return
#     nothing from describe — always the full UUID.
#
# A THIRD, from 2026-07-22: a Cloud Run JOB does not track its service's image.
# Repin with `jobs update --image` before `jobs execute --wait`, every time, or
# the job runs the image it was created with.
#
# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
# Required, no defaults — a promotion that guesses its target is the defect this
# whole phase exists to prevent:
#   SOURCE_PROJECT   where the images were built (the dev project)
#   TARGET_PROJECT   where they are being promoted to
#   IMAGE_TAG        the tag the three promotable images carry in SOURCE_PROJECT
#   GCLOUD_ACCOUNT   pinned on every gcloud call; the gcloud config on this
#                    machine has reverted mid-session and four accounts are
#                    logged in
# Required unless SKIP_FRONTEND is set (the frontend is REBUILT per environment):
#   API_BASE_URL, FB_API_KEY, FB_AUTH_DOMAIN, FB_PROJECT_ID
# Optional:
#   REGION (europe-west1), REPO (nestor), SKIP_FRONTEND, TFVARS_FILE, DRY_RUN,
#   SMOKE_ID_TOKEN, MIGRATION_EVIDENCE_STRICT, TRIBUNAL_SERVICE_URL,
#   MIGRATE_JOB, TRIBUNAL_MIGRATE_JOB
#
# FB_API_KEY is read from the ENVIRONMENT only. It is never written to a file,
# never echoed, and never placed in a printed command line. (It is a public
# Firebase project identifier rather than a credential, but the agent permission
# classifier blocks the literal and a committed copy would outlive its rotation.)
#
# ---------------------------------------------------------------------------
# DRY_RUN=1 — PRINTS THE WHOLE PLAN AND MAKES NO OUTBOUND CALL AT ALL
# ---------------------------------------------------------------------------
# The second half of that is load-bearing, not a nicety. Step 1 resolves digests
# with a real `gcloud artifacts docker images describe`, which FAILS on a tag that
# does not exist — so a dry run with a placeholder tag would die before reaching
# the ordering the dry run exists to show. Under DRY_RUN every read is skipped
# too: the whole ordering is reviewable offline by anyone, including an agent
# whose permission classifier blocks the real commands.
#
#   DRY_RUN=1 SOURCE_PROJECT=<dev> TARGET_PROJECT=<client> IMAGE_TAG=<sha> \
#   GCLOUD_ACCOUNT=tools@dotto.be SKIP_FRONTEND=1 bash infra/promote.sh

set -euo pipefail

# ---------------------------------------------------------------------------
# Inputs — checked one at a time, by name, before anything happens.
# ---------------------------------------------------------------------------
DRY_RUN="${DRY_RUN:-}"

need() {
  # need <NAME> <value> <why>
  if [ -z "${2}" ]; then
    echo "ERROR: ${1} is required and has no default." >&2
    echo "       ${3}" >&2
    exit 2
  fi
}

need SOURCE_PROJECT "${SOURCE_PROJECT:-}" "The project whose Artifact Registry holds the built images."
need TARGET_PROJECT "${TARGET_PROJECT:-}" "The project being promoted INTO. Never defaulted: a guess ships a client release into dev, or a dev experiment in front of the client."
need IMAGE_TAG      "${IMAGE_TAG:-}"      "The tag the three promotable images carry in SOURCE_PROJECT. Resolved to digests immediately; nothing is deployed by tag."
need GCLOUD_ACCOUNT "${GCLOUD_ACCOUNT:-}" "Pinned as --account on every gcloud call. The gcloud config on this machine has reverted mid-session and four accounts are logged in."

REGION="${REGION:-europe-west1}"
REPO="${REPO:-nestor}"
SKIP_FRONTEND="${SKIP_FRONTEND:-}"
TFVARS_FILE="${TFVARS_FILE:-}"
SMOKE_ID_TOKEN="${SMOKE_ID_TOKEN:-}"
MIGRATION_EVIDENCE_STRICT="${MIGRATION_EVIDENCE_STRICT:-}"
MIGRATE_JOB="${MIGRATE_JOB:-nestor-migrate}"
TRIBUNAL_MIGRATE_JOB="${TRIBUNAL_MIGRATE_JOB:-tribunal-migrate}"
GATE_CONFIG="${GATE_CONFIG:-infra/queue-check.yaml}"
FRONTEND_CONFIG="${FRONTEND_CONFIG:-frontend/cloudbuild.yaml}"
API_SERVICE="${API_SERVICE:-nestor-api}"
FRONTEND_SERVICE="${FRONTEND_SERVICE:-nestor-frontend}"

if [ -z "${SKIP_FRONTEND}" ]; then
  need API_BASE_URL   "${API_BASE_URL:-}"   "The TARGET environment's nestor-api URL. Vite inlines it at BUILD time, so it cannot be changed after the image exists."
  need FB_API_KEY     "${FB_API_KEY:-}"     "Read from the environment ONLY. Never written to a file and never echoed by this script."
  need FB_AUTH_DOMAIN "${FB_AUTH_DOMAIN:-}" "The TARGET environment's Identity Platform authDomain."
  need FB_PROJECT_ID  "${FB_PROJECT_ID:-}"  "The TARGET environment's Firebase/Identity Platform project id."
fi

ACCOUNT_ARGS=(--account="${GCLOUD_ACCOUNT}")

if [ -z "${DRY_RUN}" ]; then
  command -v gcloud >/dev/null 2>&1 || { echo "ERROR: gcloud is not on PATH." >&2; exit 2; }
fi

say()  { printf '==> %s\n' "$*"; }
show() { printf '    $ %s\n' "$*"; }
die()  { printf '\nPROMOTION ABORTED: %s\n' "$*" >&2; exit 1; }

# run <cmd...> — print it, then execute it unless this is a dry run.
run() {
  show "$*"
  if [ -n "${DRY_RUN}" ]; then return 0; fi
  "$@"
}

SRC_BASE="${REGION}-docker.pkg.dev/${SOURCE_PROJECT}/${REPO}"
TGT_BASE="${REGION}-docker.pkg.dev/${TARGET_PROJECT}/${REPO}"

# A fixed, obviously-fake placeholder so a dry run can carry a digest through the
# rest of the plan without ever resolving a real one.
DRY_DIGEST="0000000000000000000000000000000000000000000000000000000000000000"

say "promote: source=${SOURCE_PROJECT} target=${TARGET_PROJECT} tag=${IMAGE_TAG} region=${REGION} repo=${REPO}"
if [ -n "${DRY_RUN}" ]; then
  say "DRY RUN — every command below is printed, none is executed, and nothing reaches the network."
fi

# ---------------------------------------------------------------------------
# STEP 1 — resolve digests. Do not trust tags.
# ---------------------------------------------------------------------------
say "STEP 1/10  resolve image digests in the source registry (a tag is mutable; the digest is the release identity)"

DIGEST_BACKEND=""
DIGEST_TRIB_API=""
DIGEST_TRIB_WORKER=""

# Sets RESOLVED_DIGEST rather than echoing it. A command substitution would swallow
# the dry run's own output — the "would resolve" lines must reach stdout, because
# offline reviewability of the plan is the whole point of DRY_RUN.
RESOLVED_DIGEST=""
resolve_digest() {
  local name="$1"
  local ref="${SRC_BASE}/${name}"
  RESOLVED_DIGEST=""
  if [ -n "${DRY_RUN}" ]; then
    printf 'would resolve digest for %s:%s\n' "${ref}" "${IMAGE_TAG}"
    RESOLVED_DIGEST="${DRY_DIGEST}"
    return 0
  fi
  local d
  d="$(gcloud "${ACCOUNT_ARGS[@]}" artifacts docker images describe \
        "${ref}:${IMAGE_TAG}" --project="${SOURCE_PROJECT}" \
        --format='value(image_summary.digest)' 2>/dev/null || true)"
  d="${d//[[:space:]]/}"
  RESOLVED_DIGEST="${d#sha256:}"
}

resolve_digest backend;         DIGEST_BACKEND="${RESOLVED_DIGEST}"
resolve_digest tribunal-api;    DIGEST_TRIB_API="${RESOLVED_DIGEST}"
resolve_digest tribunal-worker; DIGEST_TRIB_WORKER="${RESOLVED_DIGEST}"

[ -n "${DIGEST_BACKEND}" ]     || die "could not resolve a digest for the backend image at tag ${IMAGE_TAG} in ${SOURCE_PROJECT}."
[ -n "${DIGEST_TRIB_API}" ]    || die "could not resolve a digest for the tribunal api image at tag ${IMAGE_TAG} in ${SOURCE_PROJECT}."
[ -n "${DIGEST_TRIB_WORKER}" ] || die "could not resolve a digest for the tribunal worker image at tag ${IMAGE_TAG} in ${SOURCE_PROJECT}."

# These three lines ARE the release's identity. They go in the deploy record.
printf '    backend        sha256:%s\n' "${DIGEST_BACKEND}"
printf '    trib-api       sha256:%s\n' "${DIGEST_TRIB_API}"
printf '    trib-worker    sha256:%s\n' "${DIGEST_TRIB_WORKER}"

# ---------------------------------------------------------------------------
# STEP 1b — the same digest must EXIST in the target registry.
#
# Promoting "the same digest" is a claim, so it is checked rather than asserted.
# When SOURCE and TARGET are the same project (the dev self-promotion path) this
# is trivially true and costs one describe. When they differ, a missing digest
# means the image was never copied across, and the promotion stops HERE — before
# a migration has run — with the copy command printed.
# ---------------------------------------------------------------------------
say "STEP 1b/10 confirm each resolved digest is present in the target registry"

verify_in_target() {
  local name="$1" digest="$2"
  if [ -n "${DRY_RUN}" ]; then return 0; fi
  if ! gcloud "${ACCOUNT_ARGS[@]}" artifacts docker images describe \
        "${TGT_BASE}/${name}@sha256:${digest}" --project="${TARGET_PROJECT}" \
        --format='value(image_summary.digest)' >/dev/null 2>&1; then
    echo "" >&2
    echo "The ${name} digest is NOT in ${TARGET_PROJECT}'s registry. Copy it, then re-run:" >&2
    echo "  gcloud artifacts docker images copy \\" >&2
    echo "    ${SRC_BASE}/${name}@sha256:${digest} \\" >&2
    echo "    ${TGT_BASE}/${name}:${IMAGE_TAG} \\" >&2
    echo "    --project=${SOURCE_PROJECT} --account=${GCLOUD_ACCOUNT}" >&2
    die "${name}: the promoted digest does not exist in the target registry."
  fi
}
if [ -n "${DRY_RUN}" ]; then
  show "(skipped: would confirm 3 digests in ${TGT_BASE})"
else
  verify_in_target backend        "${DIGEST_BACKEND}"
  verify_in_target tribunal-api   "${DIGEST_TRIB_API}"
  verify_in_target tribunal-worker "${DIGEST_TRIB_WORKER}"
fi

# ---------------------------------------------------------------------------
# The idle gate. Used at step 2 and again at step 7.
#
# `gcloud builds submit` exits 1 on a failed build — it does NOT hand back the
# step's exit code — so the code is read out of the build's statusDetail via
# `builds describe <FULL UUID>`. A gate whose answer cannot be read is a REFUSAL,
# never a pass.
# ---------------------------------------------------------------------------
gate() {
  local when="$1"
  local sa="projects/${TARGET_PROJECT}/serviceAccounts/nestor-run@${TARGET_PROJECT}.iam.gserviceaccount.com"
  local cmd=(gcloud "${ACCOUNT_ARGS[@]}" builds submit --no-source
             --config="${GATE_CONFIG}"
             --substitutions="_PROJECT=${TARGET_PROJECT},_REGION=${REGION}"
             --service-account="${sa}"
             --project="${TARGET_PROJECT}")
  show "${cmd[*]}"
  if [ -n "${DRY_RUN}" ]; then return 0; fi

  local out rc bid detail code
  set +e
  out="$("${cmd[@]}" 2>&1)"
  rc=$?
  set -e
  printf '%s\n' "${out}"

  if [ "${rc}" -eq 0 ]; then
    say "gate (${when}): queue is idle."
    return 0
  fi

  bid="$(printf '%s' "${out}" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -n1 || true)"
  if [ -z "${bid}" ]; then
    die "the idle gate failed and no build UUID could be recovered from its output. The queue state is UNKNOWN, and UNKNOWN is NOT SAFE."
  fi
  detail="$(gcloud "${ACCOUNT_ARGS[@]}" builds describe "${bid}" --project="${TARGET_PROJECT}" \
            --format='value(status,statusDetail)' 2>/dev/null || true)"
  echo "    build ${bid}: ${detail}"
  code="$(printf '%s' "${detail}" | grep -oE 'status [0-9]+' | grep -oE '[0-9]+' | head -n1 || true)"

  case "${code}" in
    90) die "idle gate exit 90 — the proxy or psql could not answer. UNKNOWN is NOT SAFE. Build ${bid}." ;;
    91) die "idle gate exit 91 — connected as the wrong role, so the queue would read FALSELY EMPTY (trap 2). Build ${bid}." ;;
    92) die "idle gate exit 92 — tribunal.run is not present; the answer would be meaningless. Build ${bid}." ;;
    93) die "idle gate exit 93 — one or more runs are queued or running. A worker deploy would kill them. Build ${bid}." ;;
    *)  die "idle gate failed with an unreadable code (build ${bid}, detail: ${detail}). Fail closed: DO NOT DEPLOY." ;;
  esac
}

# ---------------------------------------------------------------------------
# STEP 2 — the gate, at the TOP, before any migration.
# A release that half-applies and then stops at the worker is worse than one that
# never started. This is the FIRST of the two infra/queue-check.yaml invocations.
# ---------------------------------------------------------------------------
say "STEP 2/10  idle gate (${GATE_CONFIG}) — run before anything is applied"
gate "pre-flight"

# ---------------------------------------------------------------------------
# Migration helper. The exit status is NOT the proof; the log line is.
# ---------------------------------------------------------------------------
migrate_job() {
  local job="$1" image="$2"
  run gcloud "${ACCOUNT_ARGS[@]}" run jobs update "${job}" \
      --image="${image}" --region="${REGION}" --project="${TARGET_PROJECT}"
  run gcloud "${ACCOUNT_ARGS[@]}" run jobs execute "${job}" --wait \
      --region="${REGION}" --project="${TARGET_PROJECT}"
  if [ -n "${DRY_RUN}" ]; then
    show "(skipped: would read the execution's logs and require migration evidence)"
    return 0
  fi

  local exec_name logs
  exec_name="$(gcloud "${ACCOUNT_ARGS[@]}" run jobs executions list --job="${job}" \
                --region="${REGION}" --project="${TARGET_PROJECT}" \
                --limit=1 --format='value(name)' 2>/dev/null || true)"
  [ -n "${exec_name}" ] || die "${job}: no execution could be listed, so the migration cannot be proven."

  logs="$(gcloud "${ACCOUNT_ARGS[@]}" logging read \
          "resource.type=cloud_run_job AND labels.\"run.googleapis.com/execution_name\"=\"${exec_name}\"" \
          --project="${TARGET_PROJECT}" --limit=300 --order=asc \
          --format='value(textPayload)' 2>/dev/null || true)"
  if [ -z "${logs}" ]; then
    die "${job}: the log read for execution ${exec_name} returned NOTHING. The exit status alone is not proof that the schema moved."
  fi

  if printf '%s\n' "${logs}" | grep -q 'Running upgrade'; then
    say "${job}: migration evidence (execution ${exec_name}):"
    printf '%s\n' "${logs}" | grep 'Running upgrade' | sed 's/^/    /'
  else
    echo "    NOTE: no 'Running upgrade' line in execution ${exec_name} — the database was"
    echo "          already at head, or the job did not run alembic. Last lines:"
    printf '%s\n' "${logs}" | tail -n 5 | sed 's/^/    /'
    if [ -n "${MIGRATION_EVIDENCE_STRICT}" ]; then
      die "${job}: MIGRATION_EVIDENCE_STRICT is set and no 'Running upgrade' line was found."
    fi
  fi
}

say "STEP 3a/10 migrations first — ${MIGRATE_JOB}, REPINNED to the promoted backend digest"
say "           (a Cloud Run job does not track its service's image; repinning is not optional)"
migrate_job "${MIGRATE_JOB}" "${TGT_BASE}/backend@sha256:${DIGEST_BACKEND}"

say "STEP 3b/10 migrations — ${TRIBUNAL_MIGRATE_JOB}, repinned to the promoted tribunal api digest"
migrate_job "${TRIBUNAL_MIGRATE_JOB}" "${TGT_BASE}/tribunal-api@sha256:${DIGEST_TRIB_API}"

# ---------------------------------------------------------------------------
# STEP 4 — the API, by digest, then read the digest BACK off the revision.
# ---------------------------------------------------------------------------
say "STEP 4/10  ${API_SERVICE} at the promoted backend digest"
run gcloud "${ACCOUNT_ARGS[@]}" run services update "${API_SERVICE}" \
    --image="${TGT_BASE}/backend@sha256:${DIGEST_BACKEND}" \
    --region="${REGION}" --project="${TARGET_PROJECT}"

API_REVISION=""
if [ -z "${DRY_RUN}" ]; then
  readback="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${API_SERVICE}" \
              --region="${REGION}" --project="${TARGET_PROJECT}" \
              --format='value(status.latestReadyRevisionName,status.imageDigest)' 2>/dev/null || true)"
  API_REVISION="$(printf '%s' "${readback}" | awk '{print $1}')"
  live_digest="$(printf '%s' "${readback}" | awk '{print $2}')"
  live_digest="${live_digest#*sha256:}"
  if [ "${live_digest}" != "${DIGEST_BACKEND}" ]; then
    die "${API_SERVICE} read back digest '${live_digest}' but the release is 'sha256:${DIGEST_BACKEND}'. The running image is not the promoted image."
  fi
  say "${API_SERVICE} revision ${API_REVISION} confirmed at the promoted digest"
else
  show "(skipped: would read status.imageDigest back and abort on a mismatch)"
fi

# ---------------------------------------------------------------------------
# STEP 5 — THE FRONTEND IS BUILT, NOT PROMOTED. This one is different on purpose.
#
# Vite inlines every VITE_* value into the client bundle at BUILD time. A promoted
# dev frontend image would therefore carry the DEV api base url and the DEV
# Firebase config inside its JavaScript, and would point the client's browser at
# the dev API no matter what the Cloud Run env says. So the client frontend is
# rebuilt per environment with the target's substitutions. This is the one image
# in the release whose digest differs between environments, by necessity.
#
# The build is confirmed with `builds describe <FULL UUID>` — never an exit code,
# and never through a pipe.
# ---------------------------------------------------------------------------
FRONTEND_DIGEST=""
FRONTEND_REVISION=""
if [ -n "${SKIP_FRONTEND}" ]; then
  say "STEP 5/10  frontend rebuild SKIPPED (SKIP_FRONTEND is set)"
else
  say "STEP 5/10  frontend — REBUILT for this environment, not promoted"
  FRONTEND_IMAGE="${TGT_BASE}/frontend:${IMAGE_TAG}"
  # FB_API_KEY is expanded by the shell into the argument list and never printed:
  # the command echoed below carries a placeholder in its place.
  show "gcloud ${ACCOUNT_ARGS[*]} builds submit frontend --config=${FRONTEND_CONFIG} --substitutions=_IMAGE=${FRONTEND_IMAGE},_API_BASE_URL=${API_BASE_URL},_FB_API_KEY=<from-env>,_FB_AUTH_DOMAIN=${FB_AUTH_DOMAIN},_FB_PROJECT_ID=${FB_PROJECT_ID} --project=${TARGET_PROJECT}"
  if [ -z "${DRY_RUN}" ]; then
    set +e
    fe_out="$(gcloud "${ACCOUNT_ARGS[@]}" builds submit frontend \
              --config="${FRONTEND_CONFIG}" \
              --substitutions="_IMAGE=${FRONTEND_IMAGE},_API_BASE_URL=${API_BASE_URL},_FB_API_KEY=${FB_API_KEY},_FB_AUTH_DOMAIN=${FB_AUTH_DOMAIN},_FB_PROJECT_ID=${FB_PROJECT_ID}" \
              --project="${TARGET_PROJECT}" 2>&1)"
    fe_rc=$?
    set -e
    printf '%s\n' "${fe_out}"
    fe_bid="$(printf '%s' "${fe_out}" | grep -oE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}' | head -n1 || true)"
    [ -n "${fe_bid}" ] || die "the frontend build produced no readable build UUID (submit rc=${fe_rc})."
    fe_status="$(gcloud "${ACCOUNT_ARGS[@]}" builds describe "${fe_bid}" --project="${TARGET_PROJECT}" \
                 --format='value(status)' 2>/dev/null || true)"
    [ "${fe_status}" = "SUCCESS" ] || die "frontend build ${fe_bid} is '${fe_status}', not SUCCESS. Never trust the submit exit code."
    say "frontend build ${fe_bid}: SUCCESS"

    FRONTEND_DIGEST="$(gcloud "${ACCOUNT_ARGS[@]}" artifacts docker images describe "${FRONTEND_IMAGE}" \
                       --project="${TARGET_PROJECT}" --format='value(image_summary.digest)' 2>/dev/null || true)"
    FRONTEND_DIGEST="${FRONTEND_DIGEST//[[:space:]]/}"
    FRONTEND_DIGEST="${FRONTEND_DIGEST#sha256:}"
    [ -n "${FRONTEND_DIGEST}" ] || die "the frontend image built but its digest could not be read."
  fi
  run gcloud "${ACCOUNT_ARGS[@]}" run services update "${FRONTEND_SERVICE}" \
      --image="${TGT_BASE}/frontend@sha256:${FRONTEND_DIGEST:-${DRY_DIGEST}}" \
      --region="${REGION}" --project="${TARGET_PROJECT}"
  if [ -z "${DRY_RUN}" ]; then
    FRONTEND_REVISION="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${FRONTEND_SERVICE}" \
                         --region="${REGION}" --project="${TARGET_PROJECT}" \
                         --format='value(status.latestReadyRevisionName)' 2>/dev/null || true)"
  fi
fi

# ---------------------------------------------------------------------------
# STEP 6 — tribunal-api, through its own hardened deploy script.
#
# deploy-api.sh composes --set-secrets and --set-env-vars as ONE atomic line each
# (a second flag REPLACES the first), so it is the only correct way to move this
# service. It addresses the image by TAG, which is why step 1b pinned the tag to a
# verified digest first and why the digest is read back immediately after.
# ---------------------------------------------------------------------------
say "STEP 6/10  tribunal-api via tribunal/infrastructure/cloud-run/deploy-api.sh"
TRIB_API_SERVICE="tribunal-api"
if [ -n "${DRY_RUN}" ]; then
  show "GOOGLE_PROJECT=${TARGET_PROJECT} IMAGE_TAG=${IMAGE_TAG} GCLOUD_ACCOUNT=${GCLOUD_ACCOUNT} TRIBUNAL_SERVICE_URL=<target tribunal url> REGION=${REGION} REPO=${REPO} bash tribunal/infrastructure/cloud-run/deploy-api.sh"
else
  GOOGLE_PROJECT="${TARGET_PROJECT}" \
  IMAGE_TAG="${IMAGE_TAG}" \
  GCLOUD_ACCOUNT="${GCLOUD_ACCOUNT}" \
  REGION="${REGION}" REPO="${REPO}" \
  TRIBUNAL_SERVICE_URL="${TRIBUNAL_SERVICE_URL:-}" \
    bash tribunal/infrastructure/cloud-run/deploy-api.sh \
    || die "deploy-api.sh failed."

  ta_readback="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${TRIB_API_SERVICE}" \
                 --region="${REGION}" --project="${TARGET_PROJECT}" \
                 --format='value(status.latestReadyRevisionName,status.imageDigest)' 2>/dev/null || true)"
  TRIB_API_REVISION="$(printf '%s' "${ta_readback}" | awk '{print $1}')"
  ta_digest="$(printf '%s' "${ta_readback}" | awk '{print $2}')"
  ta_digest="${ta_digest#*sha256:}"
  [ "${ta_digest}" = "${DIGEST_TRIB_API}" ] \
    || die "${TRIB_API_SERVICE} is running digest '${ta_digest}', not the promoted 'sha256:${DIGEST_TRIB_API}'. The tag moved under the release."
  say "${TRIB_API_SERVICE} revision ${TRIB_API_REVISION} confirmed at the promoted digest"
fi

# ---------------------------------------------------------------------------
# STEP 7 — THE GATE AGAIN, immediately before the worker. This is the SECOND of
# the two infra/queue-check.yaml invocations, and the one that actually protects
# the money: steps 3-6 take minutes and a run can be started in that window.
# Re-running a cheap check is the difference between a rule and a ritual.
# ---------------------------------------------------------------------------
say "STEP 7/10  idle gate again (${GATE_CONFIG}) — immediately before the worker"
gate "pre-worker"

# ---------------------------------------------------------------------------
# STEP 8 — the worker, LAST, and only behind a green gate.
# ---------------------------------------------------------------------------
say "STEP 8/10  tribunal-worker via tribunal/infrastructure/cloud-run/deploy-worker.sh — LAST"
TRIB_WORKER_SERVICE="tribunal-worker"
TRIB_WORKER_REVISION=""
if [ -n "${DRY_RUN}" ]; then
  show "GOOGLE_PROJECT=${TARGET_PROJECT} IMAGE_TAG=${IMAGE_TAG} GCLOUD_ACCOUNT=${GCLOUD_ACCOUNT} REGION=${REGION} REPO=${REPO} bash tribunal/infrastructure/cloud-run/deploy-worker.sh"
else
  GOOGLE_PROJECT="${TARGET_PROJECT}" \
  IMAGE_TAG="${IMAGE_TAG}" \
  GCLOUD_ACCOUNT="${GCLOUD_ACCOUNT}" \
  REGION="${REGION}" REPO="${REPO}" \
    bash tribunal/infrastructure/cloud-run/deploy-worker.sh \
    || die "deploy-worker.sh failed."

  tw_readback="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${TRIB_WORKER_SERVICE}" \
                 --region="${REGION}" --project="${TARGET_PROJECT}" \
                 --format='value(status.latestReadyRevisionName,status.imageDigest)' 2>/dev/null || true)"
  TRIB_WORKER_REVISION="$(printf '%s' "${tw_readback}" | awk '{print $1}')"
  tw_digest="$(printf '%s' "${tw_readback}" | awk '{print $2}')"
  tw_digest="${tw_digest#*sha256:}"
  [ "${tw_digest}" = "${DIGEST_TRIB_WORKER}" ] \
    || die "${TRIB_WORKER_SERVICE} is running digest '${tw_digest}', not the promoted 'sha256:${DIGEST_TRIB_WORKER}'."
  say "${TRIB_WORKER_SERVICE} revision ${TRIB_WORKER_REVISION} confirmed at the promoted digest"
fi

# ---------------------------------------------------------------------------
# STEP 9 — smoke, and it must be able to fail.
# ---------------------------------------------------------------------------
say "STEP 9/10  smoke — /readyz, the login page, and one authenticated intake read"
SMOKE_FAILED=""

http_code() {
  curl -sS -o /dev/null -w '%{http_code}' --max-time 30 "$@" 2>/dev/null || echo "000"
}

if [ -n "${DRY_RUN}" ]; then
  show "(skipped: would GET <api>/readyz, GET <frontend>/auth/login, and GET <api>/intakes with an id token)"
else
  API_URL="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${API_SERVICE}" \
             --region="${REGION}" --project="${TARGET_PROJECT}" --format='value(status.url)' 2>/dev/null || true)"
  FE_URL="$(gcloud "${ACCOUNT_ARGS[@]}" run services describe "${FRONTEND_SERVICE}" \
            --region="${REGION}" --project="${TARGET_PROJECT}" --format='value(status.url)' 2>/dev/null || true)"

  # /healthz 404s upstream on this service while /readyz 200s — smoke on /readyz.
  if [ -z "${API_URL}" ]; then
    SMOKE_FAILED="${SMOKE_FAILED} api-url-unreadable"
  else
    code="$(http_code "${API_URL}/readyz")"
    echo "    GET ${API_URL}/readyz -> ${code}"
    [ "${code}" = "200" ] || SMOKE_FAILED="${SMOKE_FAILED} readyz(${code})"
  fi

  if [ -z "${FE_URL}" ]; then
    SMOKE_FAILED="${SMOKE_FAILED} frontend-url-unreadable"
  else
    code="$(http_code "${FE_URL}/auth/login")"
    echo "    GET ${FE_URL}/auth/login -> ${code}"
    [ "${code}" = "200" ] || SMOKE_FAILED="${SMOKE_FAILED} login(${code})"
  fi

  if [ -z "${SMOKE_ID_TOKEN}" ]; then
    echo ""
    echo "    *** THIRD SMOKE CHECK SKIPPED: the authenticated intake read did NOT run. ***"
    echo "    *** No SMOKE_ID_TOKEN was available in this invocation context.           ***"
    echo "    *** The data path is therefore UNVERIFIED by this promotion. Export a     ***"
    echo "    *** Firebase id token as SMOKE_ID_TOKEN, or read one intake by hand now.  ***"
    echo ""
  elif [ -n "${API_URL}" ]; then
    body_file="$(mktemp)"
    code="$(curl -sS -o "${body_file}" -w '%{http_code}' --max-time 30 \
            -H "Authorization: Bearer ${SMOKE_ID_TOKEN}" "${API_URL}/intakes" 2>/dev/null || echo "000")"
    echo "    GET ${API_URL}/intakes (authenticated) -> ${code}"
    if [ "${code}" != "200" ]; then
      SMOKE_FAILED="${SMOKE_FAILED} intakes(${code})"
    elif ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "${body_file}" >/dev/null 2>&1; then
      SMOKE_FAILED="${SMOKE_FAILED} intakes(body-not-json)"
    fi
    rm -f "${body_file}"
  fi

  if [ -n "${SMOKE_FAILED}" ]; then
    die "post-promotion smoke FAILED:${SMOKE_FAILED}. The environment is live on the new images and one or more checks did not pass."
  fi
  say "smoke passed"
fi

# ---------------------------------------------------------------------------
# STEP 10 — write the promoted tags back into the tfvars file.
# The ONLY file this script edits. Without it Terraform's record and the running
# images drift apart silently, and the next `terraform apply` quietly rolls the
# environment back to whatever the file still said.
#
# EXERCISED 2026-09-11 against the real infra/env/client.tfvars: the three keys
# are matched anchored, so `image_tag` does NOT also hit `frontend_image_tag`,
# column alignment survives, and no other variable is touched. Two things it
# DOES do, both intended and neither a correctness problem:
#   * the trailing explanatory comment on a rewritten line is replaced along
#     with the value ("<capture-after-first-deploy>" stops being true the moment
#     a real tag is written, so the note goes with it);
#   * `sed -i` writes LF. On a Windows checkout (core.autocrlf=true) that
#     re-lines the WHOLE file and produces a noisy diff. Inside Cloud Build,
#     which is where this runs, everything is LF already.
# ---------------------------------------------------------------------------
say "STEP 10/10 record the promoted tags in the tfvars file"
set_tfvar() {
  local key="$1" val="$2" file="$3"
  if grep -qE "^[[:space:]]*${key}[[:space:]]*=" "${file}"; then
    sed -i -E "s|^([[:space:]]*${key}[[:space:]]*=[[:space:]]*).*$|\\1\"${val}\"|" "${file}"
  else
    printf '%s = "%s"\n' "${key}" "${val}" >> "${file}"
  fi
}
if [ -z "${TFVARS_FILE}" ]; then
  say "TFVARS_FILE is not set — nothing written. Update the tfvars by hand or the next apply will roll this release back."
elif [ -n "${DRY_RUN}" ]; then
  show "(skipped: would set image_tag / tribunal_image_tag / frontend_image_tag in ${TFVARS_FILE})"
elif [ ! -f "${TFVARS_FILE}" ]; then
  die "TFVARS_FILE=${TFVARS_FILE} does not exist."
else
  set_tfvar image_tag          "${IMAGE_TAG}" "${TFVARS_FILE}"
  set_tfvar tribunal_image_tag "${IMAGE_TAG}" "${TFVARS_FILE}"
  [ -n "${SKIP_FRONTEND}" ] || set_tfvar frontend_image_tag "${IMAGE_TAG}" "${TFVARS_FILE}"
  say "wrote the promoted tags into ${TFVARS_FILE}"
fi

# ---------------------------------------------------------------------------
# The deploy record — paste this into infra/DEPLOY-RUNBOOK.md.
# ---------------------------------------------------------------------------
echo ""
echo "=================================================================="
echo "DEPLOY RECORD — ${TARGET_PROJECT} @ ${IMAGE_TAG}"
echo "  promoted from : ${SOURCE_PROJECT}"
echo "  backend       : sha256:${DIGEST_BACKEND}"
echo "  tribunal api  : sha256:${DIGEST_TRIB_API}"
echo "  tribunal wrkr : sha256:${DIGEST_TRIB_WORKER}"
echo "  frontend      : sha256:${FRONTEND_DIGEST:-<rebuilt per env; skipped>}"
echo "  revisions     : ${API_REVISION:-?} ${FRONTEND_REVISION:-?} ${TRIB_API_REVISION:-?} ${TRIB_WORKER_REVISION:-?}"
if [ -z "${DRY_RUN}" ]; then
  echo "  alembic heads : (read from the step 3a/3b evidence above)"
fi
echo "  smoke         : ${SMOKE_FAILED:-ok}${SMOKE_ID_TOKEN:+ (intake read included)}"
echo "=================================================================="
