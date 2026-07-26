#!/usr/bin/env bash
#
# INTAKE-05 / D-06 CI scope-ceiling guard.
#
# Fails the build if ANY genuine invocation of the out-of-scope deep-research
# stage (run-research / Tribunal) or its deferred post-`decomposed` DB triggers
# ever (re)appears in backend/app or frontend/src. The whole re-platform stops
# at status `decomposed`; the Tribunal / run-research stage is a separate track
# and must never be reachable from the new frontend/backend credentials. This is
# the preventive twin of the structural route-absence test
# (backend/tests/test_no_run_research_route.py, plan 04): that test proves the
# route is absent today, this guard keeps it absent forever. Run in CI BEFORE
# deploy. It is a member of the D-03 guard family (cf. ci_no_raw_db_access.sh).
#
# Contract: the EXIT CODE is the gate (mirrors ci_no_raw_db_access.sh).
#   exit 0  -> no run-research/Tribunal invocation found (clean)
#   exit 1  -> at least one guarded token found (build must fail)
#   exit 2  -> a scan dir does not exist (misconfiguration)
# Do NOT gate on an unfiltered `grep -c ... == 0`; rely on grep's own exit code.
#
# The scan dirs default to BOTH backend/app/ and frontend/src/, but the first
# positional arg overrides them with a single dir, so the negative test can
# point the guard at a temp dir containing a planted offender.
#
# IMPORTANT — precision over a bare token match:
# The codebase legitimately *documents* the scope ceiling — docstrings/comments
# in the alembic migrations and db models name "Tribunal", and a Dutch operator
# UI string in NextStepBanner.tsx contains the words "run-research". Those are
# explanatory prose, NOT reachable code, and must NOT trip the guard. So the
# pattern is anchored to real invocation / route / call / trigger syntax:
#   - invoke("run-research") / invoke("tribunal")  (Supabase edge-function call)
#   - a "/run-research" route or fetch URL segment
#   - run_research(  /  .run_research              (function / method call)
#   - the deferred post-decomposed trigger + function names (literal — these are
#     unique identifiers that only ever appear as a real CREATE TRIGGER/FUNCTION)
#   - a Python import of a `tribunal` module
# It deliberately never matches the bare enum value `in_research`, component
# names like `ResearchArtifacts`, or the prose word "Tribunal".
#
# The same precision rule governs the SerpAPI tokens added in v1.1: the guard
# matches SERPAPI_API_KEY / serpapi.com / a serpapi package import /
# google-search-results — real egress syntax — and deliberately NOT the bare
# word "SerpAPI", which appears legitimately as a display label for legacy
# artifact source types in frontend/src/components/intake/ResearchArtifacts.tsx.
#
# MILESTONE NOTE (v1.1 "Tribunal Integration", 2026-07-26 — phase 15.2):
# INTAKE-05 was a v1.0 scope ceiling: the deep-research stage had to be
# unreachable from the intake tier, full stop. v1.1 deliberately supersedes that
# — invoking Tribunal from the backend IS the milestone. Since phase 16-02 this
# guard therefore failed on `from app.research import tribunal_client`, a
# sanctioned import, and stayed red (a false positive, not a violation).
# Rather than retire the guard, it is NARROWED to the risk that still matters:
# the intake tier must not perform deep-research egress ITSELF — no direct
# SerpAPI call, no run-research invocation, no reach into engine internals. All
# engine traffic goes through the single audited HTTP seam. See $ALLOW below.
#
# Usage:
#   scripts/ci_no_run_research.sh [SCAN_DIR]

set -euo pipefail

# Resolve dirs relative to THIS script (backend/scripts/ -> backend/ -> repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$#" -ge 1 ]; then
  SCAN_DIRS=("$1")
else
  SCAN_DIRS=("${SCRIPT_DIR}/../app" "${SCRIPT_DIR}/../../frontend/src")
fi

# Forbidden deep-research-stage invocations (see header for the precision note).
PATTERN='invoke\([^)]*run-research|invoke\([^)]*run_research|invoke\([^)]*tribunal|/run-research|run_research[[:space:]]*\(|\.run_research|tg_bump_to_in_research|tg_bump_to_delivered|persist_questions_on_research_start|from[[:space:]]+[A-Za-z0-9_.]*tribunal|import[[:space:]]+[A-Za-z0-9_.]*tribunal|SERPAPI_API_KEY|serpapi\.com|from[[:space:]]+serpapi|import[[:space:]]+serpapi|google-search-results'

# SANCTIONED SEAM ALLOWLIST (v1.1 — see header "Milestone note").
# The ONLY permitted way the intake tier may reach the engine is the HTTP seam
# client `app.research.tribunal_client`, which speaks to the Tribunal API over
# authenticated HTTP and imports no engine code (it pulls httpx + google.auth
# only). Importing THAT module is allowed; importing engine internals is not.
# Anchored to import syntax so it can never whitelist a call site.
ALLOW='from[[:space:]]+app\.research[[:space:]]+import[[:space:]]+tribunal_client|from[[:space:]]+app\.research\.tribunal_client[[:space:]]+import|import[[:space:]]+app\.research\.tribunal_client|from[[:space:]]+\.tribunal_client[[:space:]]+import|from[[:space:]]+\.[[:space:]]+import[[:space:]]+tribunal_client'

for dir in "${SCAN_DIRS[@]}"; do
  if [ ! -d "$dir" ]; then
    echo "ERROR: scan dir does not exist: $dir" >&2
    exit 2
  fi
done

# grep exits 0 when it finds a match (=> offender => we must fail), 1 when it
# finds none (=> clean). We invert that into the guard's own exit code: if ANY
# scan dir yields a match, the guard fails. Scanning backend/app AND frontend/src.
FOUND=1
for dir in "${SCAN_DIRS[@]}"; do
  # Match the forbidden pattern, then drop the sanctioned seam imports. grep -v
  # exits 1 when every line was filtered out, so `if` still means "offender found".
  if grep -rEn --include='*.py' --include='*.ts' --include='*.tsx' "$PATTERN" "$dir" \
     | grep -Ev "$ALLOW"; then
    FOUND=0
  fi
done

if [ "$FOUND" -eq 0 ]; then
  echo "ERROR: run-research/Tribunal invocation found (INTAKE-05 scope guard)." >&2
  echo "       The re-platform scope ends at 'decomposed'; the deep-research" >&2
  echo "       (Tribunal / run-research) stage must never be reachable from the" >&2
  echo "       new frontend/backend — see scripts/ci_no_run_research.sh (D-06)." >&2
  exit 1
fi

echo "OK: no run-research/Tribunal invocation in ${SCAN_DIRS[*]}."
exit 0
