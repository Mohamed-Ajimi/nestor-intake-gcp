#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# infra/release-client.sh — promote a tested dev tag to the TERRAFORM-MANAGED client
# environment (nestor-pulse-prod), in promote.sh's order, through Terraform.
#
# WHY NOT promote.sh FOR THE CLIENT: the client's Cloud Run services are Terraform
# resources whose images live in the DEV registry (var.image_registry_project) and are
# addressed by TAG. promote.sh (a) insists the digests exist in the TARGET registry,
# which is empty by design, and (b) deploys the tribunal services through
# deploy-api.sh / deploy-worker.sh, whose `--set-env-vars` would overwrite the
# Terraform-managed env and create drift. So the client release is `terraform apply`,
# TARGETED per resource so the ordering that has already cost money is kept:
#
#   0  frontend image      BUILT for this environment (client API url + client Firebase)
#   1  migrate jobs        repinned to the release tag and EXECUTED (evidence printed)
#   2  nestor-api          applied; digest read back off the REVISION == the dev digest
#   3  nestor-frontend     applied; read back
#   4  tribunal-api        applied; read back == the dev digest
#   5  idle gate           infra/queue-check.yaml as tribunal-run@ — exit 0 or STOP
#   6  tribunal-worker     applied LAST; read back == the dev digest
#   7  drift plan          a final untargeted plan; only the cosmetic scaling{} diff may remain
#
# The two tribunal kill switches are NOT flipped here. They come from env/client.tfvars
# (both "false" for this release) and are flipped by an explicit, separate apply once the
# dev acceptance run has been read (plan 23.5-07 Task 3 step 5).
#
# INPUTS (env): IMAGE_TAG (backend + tribunal tag in the dev registry, e.g. 261915a)
#               FRONTEND_TAG (e.g. client-261915a)
#               EXPECT_BACKEND, EXPECT_TRIB_API, EXPECT_TRIB_WORKER (dev digests, sha256:…)
#               FB_KEY_BUILD (a prior dev-project build id whose substitutions carry the
#                             CLIENT Firebase web key; the key is read, never printed)
# Optional:     SKIP_FRONTEND_BUILD=1 when the frontend tag already exists.
#
# Run detached (the operator terminal times out at 2 min):
#   nohup bash infra/release-client.sh > "$HOME/release-client-<tag>.log" 2>&1 &
# ---------------------------------------------------------------------------
set -euo pipefail

DEV="${DEV:-project-cb01b861-cb4a-438d-b9a}"
CLIENT="${CLIENT:-nestor-pulse-prod}"
REGION="${REGION:-europe-west1}"
ACCOUNT="${ACCOUNT:-tools@dotto.be}"
REPO="${REPO:-nestor}"
IMAGE_TAG="${IMAGE_TAG:?set IMAGE_TAG}"
FRONTEND_TAG="${FRONTEND_TAG:?set FRONTEND_TAG}"
EXPECT_BACKEND="${EXPECT_BACKEND:?set EXPECT_BACKEND (sha256:...)}"
EXPECT_TRIB_API="${EXPECT_TRIB_API:?set EXPECT_TRIB_API (sha256:...)}"
EXPECT_TRIB_WORKER="${EXPECT_TRIB_WORKER:?set EXPECT_TRIB_WORKER (sha256:...)}"
FB_KEY_BUILD="${FB_KEY_BUILD:-}"
SKIP_FRONTEND_BUILD="${SKIP_FRONTEND_BUILD:-}"

CLIENT_API_URL="${CLIENT_API_URL:-https://nestor-api-zqd5qncdnq-ew.a.run.app}"
CLIENT_FRONTEND_URL="${CLIENT_FRONTEND_URL:-https://nestor-frontend-zqd5qncdnq-ew.a.run.app}"
CLIENT_TRIB_API_URL="${CLIENT_TRIB_API_URL:-https://tribunal-api-zqd5qncdnq-ew.a.run.app}"
FB_AUTH_DOMAIN="${FB_AUTH_DOMAIN:-${CLIENT}.firebaseapp.com}"
FB_PROJECT_ID="${FB_PROJECT_ID:-${CLIENT}}"

REG="${REGION}-docker.pkg.dev/${DEV}/${REPO}"
TF="${TF:-$HOME/AppData/Local/terraform/terraform.exe}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TFDIR="${ROOT}/infra"
VARS="env/client.tfvars"

G=(gcloud "--account=${ACCOUNT}")
say() { printf '\n==> %s\n' "$*"; }
die() { printf '\nRELEASE ABORTED: %s\n' "$*" >&2; exit 1; }

# Terraform authenticates with an OAuth token from the SAME pinned account (ADC on this
# machine is a different identity and gets 403 on the state bucket).
tf() { GOOGLE_OAUTH_ACCESS_TOKEN="$(gcloud auth print-access-token --account="${ACCOUNT}")" \
         "${TF}" -chdir="${TFDIR}" "$@"; }

digest_of_tag() {  # $1 image name, $2 tag -> sha256:...
  "${G[@]}" artifacts docker images describe "${REG}/$1:$2" --project="${DEV}" \
    --format='value(image_summary.digest)' 2>/dev/null
}
revision_digest() {  # $1 service -> "revision sha256:..."
  local rev
  rev="$("${G[@]}" run services describe "$1" --region="${REGION}" --project="${CLIENT}" \
          --format='value(status.latestReadyRevisionName)')"
  local ref
  ref="$("${G[@]}" run revisions describe "${rev}" --region="${REGION}" --project="${CLIENT}" \
          --format='value(status.imageDigest)')"
  printf '%s %s\n' "${rev}" "sha256:${ref#*sha256:}"
}
apply_target() {  # $1 label, $2.. -target=... args
  local label="$1"; shift
  say "terraform plan  [${label}]"
  tf plan -var-file="${VARS}" -input=false -no-color "$@" -out="/tmp/release-${label}.tfplan" \
    | grep -E '^Plan:|^No changes|~ image|Error' || true
  say "terraform apply [${label}]"
  tf apply -input=false -no-color "/tmp/release-${label}.tfplan" | grep -E 'Apply complete|Error' \
    || die "apply failed for ${label}"
}
expect_digest() {  # $1 service, $2 expected sha256
  local rd rev got
  rd="$(revision_digest "$1")"; rev="${rd%% *}"; got="${rd##* }"
  [ "${got}" = "$2" ] || die "$1 revision ${rev} runs ${got}, expected $2"
  say "$1 revision ${rev} confirmed at ${got}"
}
http_code() { curl -s -o /dev/null --max-time 20 -w '%{http_code}' "$1" || echo "000"; }
build_wait() {  # $1 build id -> status
  local s
  for _ in $(seq 1 60); do
    s="$("${G[@]}" builds describe "$1" --project="${DEV}" --format='value(status)' 2>/dev/null)"
    case "${s}" in SUCCESS|FAILURE|CANCELLED|TIMEOUT|EXPIRED|INTERNAL_ERROR) echo "${s}"; return 0;; esac
    sleep 20
  done
  echo "TIMEOUT-WAITING"
}

say "release-client: dev=${DEV} client=${CLIENT} tag=${IMAGE_TAG} frontend=${FRONTEND_TAG}"
say "step 0a — the dev digests behind the tag"
DB="$(digest_of_tag backend "${IMAGE_TAG}")";         echo "  backend        ${DB}"
DA="$(digest_of_tag tribunal-api "${IMAGE_TAG}")";    echo "  tribunal-api   ${DA}"
DW="$(digest_of_tag tribunal-worker "${IMAGE_TAG}")"; echo "  tribunal-worker ${DW}"
[ "${DB}" = "${EXPECT_BACKEND}" ]     || die "backend tag ${IMAGE_TAG} is ${DB}, not the tested ${EXPECT_BACKEND}"
[ "${DA}" = "${EXPECT_TRIB_API}" ]    || die "tribunal-api tag ${IMAGE_TAG} is ${DA}, not the tested ${EXPECT_TRIB_API}"
[ "${DW}" = "${EXPECT_TRIB_WORKER}" ] || die "tribunal-worker tag ${IMAGE_TAG} is ${DW}, not the tested ${EXPECT_TRIB_WORKER}"

say "step 0b — tfvars must carry exactly these tags"
grep -Eq "^image_tag\s*=\s*\"${IMAGE_TAG}\""              "${TFDIR}/${VARS}" || die "image_tag in ${VARS} is not ${IMAGE_TAG}"
grep -Eq "^tribunal_image_tag\s*=\s*\"${IMAGE_TAG}\""     "${TFDIR}/${VARS}" || die "tribunal_image_tag in ${VARS} is not ${IMAGE_TAG}"
grep -Eq "^frontend_image_tag\s*=\s*\"${FRONTEND_TAG}\""  "${TFDIR}/${VARS}" || die "frontend_image_tag in ${VARS} is not ${FRONTEND_TAG}"
grep -Eq '^nestor_citations_v2\s*=\s*"false"'             "${TFDIR}/${VARS}" || die "nestor_citations_v2 is not \"false\" — this script never flips the flags"
grep -Eq '^nestor_synthesis_continue_truncated\s*=\s*"false"' "${TFDIR}/${VARS}" || die "nestor_synthesis_continue_truncated is not \"false\""

say "step 0c — frontend image ${FRONTEND_TAG} (built for the CLIENT: its API url + its Firebase)"
if [ -n "${SKIP_FRONTEND_BUILD}" ] && [ -n "$(digest_of_tag frontend "${FRONTEND_TAG}")" ]; then
  echo "  exists, build skipped"
else
  [ -n "${FB_KEY_BUILD}" ] || die "FB_KEY_BUILD is required to build the frontend"
  FB_KEY="$("${G[@]}" builds describe "${FB_KEY_BUILD}" --project="${DEV}" \
             --format='value(substitutions._FB_API_KEY)' 2>/dev/null)"
  [ -n "${FB_KEY}" ] || die "no _FB_API_KEY on build ${FB_KEY_BUILD}"
  FB_PROJ_ON_BUILD="$("${G[@]}" builds describe "${FB_KEY_BUILD}" --project="${DEV}" \
             --format='value(substitutions._FB_PROJECT_ID)' 2>/dev/null)"
  [ "${FB_PROJ_ON_BUILD}" = "${FB_PROJECT_ID}" ] || die "build ${FB_KEY_BUILD} carries the key of ${FB_PROJ_ON_BUILD}, not ${FB_PROJECT_ID}"
  BID="$("${G[@]}" builds submit "${ROOT}/frontend" --config="${ROOT}/frontend/cloudbuild.yaml" \
          --substitutions="_IMAGE=${REG}/frontend:${FRONTEND_TAG},_API_BASE_URL=${CLIENT_API_URL},_FB_API_KEY=${FB_KEY},_FB_AUTH_DOMAIN=${FB_AUTH_DOMAIN},_FB_PROJECT_ID=${FB_PROJECT_ID}" \
          --project="${DEV}" --async --format='value(id)' 2>/dev/null | tail -1)"
  [ -n "${BID}" ] || die "frontend build was not created"
  echo "  frontend build ${BID} submitted; waiting"
  ST="$(build_wait "${BID}")"
  [ "${ST}" = "SUCCESS" ] || die "frontend build ${BID} ended ${ST}"
  echo "  frontend build ${BID}: SUCCESS"
fi
DF="$(digest_of_tag frontend "${FRONTEND_TAG}")"; [ -n "${DF}" ] || die "frontend tag ${FRONTEND_TAG} has no digest"
echo "  frontend       ${DF}"

say "step 1 — migrations FIRST: repin both jobs, execute, print the evidence"
apply_target jobs -target=google_cloud_run_v2_job.migrate -target=google_cloud_run_v2_job.tribunal_migrate
for J in nestor-migrate tribunal-migrate; do
  say "execute ${J}"
  "${G[@]}" run jobs execute "${J}" --wait --region="${REGION}" --project="${CLIENT}" 2>&1 | grep -E 'Execution|completed|failed' || true
  EX="$("${G[@]}" run jobs executions list --job="${J}" --region="${REGION}" --project="${CLIENT}" --limit=1 --format='value(name)')"
  "${G[@]}" logging read "resource.type=cloud_run_job AND labels.\"run.googleapis.com/execution_name\"=\"${EX}\"" \
     --project="${CLIENT}" --limit=40 --format='value(textPayload)' 2>/dev/null \
     | grep -E 'Running upgrade|Context impl|exit\(' | tail -4 | sed 's/^/    /' || true
  echo "    (no 'Running upgrade' line = already at head; this release ships no migration)"
done

say "step 2 — nestor-api"
apply_target api -target=google_cloud_run_v2_service.api
expect_digest nestor-api "${DB}"
echo "  /readyz -> $(http_code "${CLIENT_API_URL}/readyz")"

say "step 3 — nestor-frontend"
apply_target frontend -target=google_cloud_run_v2_service.frontend
expect_digest nestor-frontend "${DF}"
echo "  /auth/login -> $(http_code "${CLIENT_FRONTEND_URL}/auth/login")"

say "step 4 — tribunal-api"
apply_target tribunal_api -target=google_cloud_run_v2_service.tribunal_api
expect_digest tribunal-api "${DA}"
echo "  /readyz -> $(http_code "${CLIENT_TRIB_API_URL}/readyz")"

say "step 5 — idle gate as tribunal-run@ (exit 0 is the ONLY pass)"
GID="$("${G[@]}" builds submit --no-source --config="${TFDIR}/queue-check.yaml" \
        --substitutions="_PROJECT=${CLIENT},_REGION=${REGION}" \
        --service-account="projects/${CLIENT}/serviceAccounts/tribunal-run@${CLIENT}.iam.gserviceaccount.com" \
        --project="${CLIENT}" --async --format='value(id)' 2>/dev/null | tail -1)"
[ -n "${GID}" ] || die "gate build was not created"
GS="$(for _ in $(seq 1 30); do s="$("${G[@]}" builds describe "${GID}" --project="${CLIENT}" --format='value(status)' 2>/dev/null)"; case "$s" in SUCCESS|FAILURE|CANCELLED|TIMEOUT|INTERNAL_ERROR) echo "$s"; break;; esac; sleep 10; done)"
GC="$("${G[@]}" builds describe "${GID}" --project="${CLIENT}" --format='value(steps[0].exitCode)' 2>/dev/null)"
echo "  gate build ${GID}: ${GS} exit=${GC:-0}"
[ "${GS}" = "SUCCESS" ] || die "idle gate refused (${GS}, exit ${GC:-?}) — a run may be in flight; the worker was NOT touched"

say "step 6 — tribunal-worker LAST"
apply_target tribunal_worker -target=google_cloud_run_v2_service.tribunal_worker
expect_digest tribunal-worker "${DW}"

say "step 7 — final untargeted plan (only the cosmetic scaling{} read-back may remain)"
tf plan -var-file="${VARS}" -input=false -no-color -lock=false 2>&1 | grep -E '^Plan:|^No changes|will be|~ image|\+ name|Error' | head -20 || true

say "DEPLOY RECORD — ${CLIENT} @ ${IMAGE_TAG} / ${FRONTEND_TAG} ($(date -u +%Y-%m-%dT%H:%MZ))"
for S in nestor-api nestor-frontend tribunal-api tribunal-worker; do printf '  %-16s %s\n' "${S}" "$(revision_digest "${S}")"; done
echo "  flags: NESTOR_CITATIONS_V2 / NESTOR_SYNTHESIS_CONTINUE_TRUNCATED = false (from ${VARS}); flip is a separate apply"
echo "RELEASE COMPLETE"
