#!/usr/bin/env bash
#
# Phase 12 (INFRA-05 / D-11) CI bundle guard — QA-02 / ci_no_permissive_rls style.
#
# Fails the build if ANY Supabase signature (project URL, VITE_SUPABASE build-arg,
# anon-role marker, or a JWT prefix) reaches the built frontend `.output/`. The
# built bundle is what ships to the browser — anything leaked here is public. The
# big-bang cutover is only provably independent of Supabase when NO Supabase key
# or URL survives into the deployed artifact (success criterion 1 / T-12-01).
#
# Wire point: run RIGHT AFTER `npm run build`, inside the Dockerfile build stage,
# mirroring the backend Dockerfile's build-time `python -c "import ..."` smoke
# check — "fail the build now, not at runtime."
#
# Contract: the EXIT CODE is the gate (mirrors backend/scripts/ci_no_permissive_rls.sh
# and frontend/scripts/ci_no_hardcoded_dutch.sh).
#   exit 0  -> no Supabase signature found in the scan dir (clean — build proceeds)
#   exit 1  -> at least one Supabase signature found (build MUST fail)
#   exit 2  -> scan dir missing (misconfiguration)
# Do NOT gate on a match-count-equals-zero construct (`grep -c ... == 0`); rely on
# grep's OWN exit code (0 = match = offender present = fail).
#
# The scan directory defaults to `.output` (Nitro build output) but may be
# overridden with the first positional arg, so the negative self-test can point
# the guard at a temp dir containing a planted offender.
#
# CI / Dockerfile invokes BOTH modes:
#   sh scripts/ci_no_supabase_in_bundle.sh .output          # positive scan (the gate)
#   bash scripts/ci_no_supabase_in_bundle.sh --self-test    # guard-mechanics negative test
#
# Usage:
#   scripts/ci_no_supabase_in_bundle.sh [SCAN_DIR]
#   scripts/ci_no_supabase_in_bundle.sh --self-test

set -euo pipefail

# Supabase signatures that must never survive into the shipped bundle:
#   supabase\.co   -> a Supabase project URL (e.g. https://xyz.supabase.co)
#   VITE_SUPABASE  -> a leaked VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY build-arg name
#   "role":"anon"  -> the anon-key JWT claim payload marker
#   eyJhbGciOi     -> a JWT header prefix (base64 of {"alg":...) — anon/service key
PATTERN='supabase\.co|VITE_SUPABASE|"role":"anon"|eyJhbGciOi'

run_scan() {
  local scan_dir="$1"

  if [ ! -d "$scan_dir" ]; then
    echo "ERROR: scan dir does not exist: $scan_dir" >&2
    exit 2
  fi

  # grep exits 0 when it finds a match (=> Supabase signature present => we FAIL),
  # and 1 when it finds none (=> clean => we pass). The exit code IS the gate;
  # do NOT gate on `grep -c ... == 0`.
  if grep -rEn "$PATTERN" "$scan_dir"; then
    echo "ERROR: Supabase signature found in built bundle ($scan_dir) — INFRA-05/D-11 violation." >&2
    echo "       No Supabase URL/anon-key may reach the shipped .output/. Remove the VITE_SUPABASE_*" >&2
    echo "       build-args and any residual client import — see scripts/ci_no_supabase_in_bundle.sh." >&2
    exit 1
  fi

  echo "OK: no Supabase signature in $scan_dir."
  exit 0
}

# ---------------------------------------------------------------------------
# Negative self-test (D-13 convention): plant an offender in a temp, non-scan
# path, point the guard at it, and assert the guard exits non-zero.
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT

  mkdir -p "$TMP_DIR/server"
  printf 'const x = "https://xyz.supabase.co";\n' > "$TMP_DIR/server/offender.js"

  # Re-invoke THIS script against the planted offender; capture the exit code.
  # `|| rc=$?` keeps set -e from aborting on the expected non-zero exit.
  rc=0
  bash "${BASH_SOURCE[0]}" "$TMP_DIR" > /dev/null 2>&1 || rc=$?

  if [ "$rc" -eq 0 ]; then
    echo "SELF-TEST FAILED: guard did NOT flag a planted Supabase offender." >&2
    exit 1
  fi

  echo "SELF-TEST OK: planted offender triggered non-zero exit ($rc)."
  exit 0
fi

run_scan "${1:-.output}"
