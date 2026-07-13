#!/usr/bin/env bash
#
# Phase-9 criterion-1 CI guard: NO service-account JSON key may ever be
# referenced under backend/app/ (T-09-01, D-09).
#
# GCS access is keyless by design: the Cloud Run attached SA signs V4 URLs via
# the IAM signBlob API using Application Default Credentials
# (google.auth.default() in app/storage/gcs.py). A JSON key file would be an
# exfiltratable, non-expiring credential — the exact class of standing secret
# this re-platform removes. Run this in CI BEFORE deploy. This guard joins the
# family of scripts/ci_no_permissive_rls.sh (QA-02) and
# scripts/ci_no_raw_db_access.sh (D-03).
#
# Banned references (any one fails the build):
#   from_service_account_file            SDK file-key constructor
#   service_account.json                 conventional key filename
#   GOOGLE_APPLICATION_CREDENTIALS=.*json  env pointing ADC at a key file
#
# Comment lines (leading optional whitespace + '#') are STRIPPED before
# matching, so a Python/shell comment explaining the ban does not self-trip
# the guard. Docstrings are NOT stripped — keep the banned literals out of
# app/ docstrings entirely.
#
# Contract: the EXIT CODE is the gate.
#   exit 0  -> no SA JSON key reference found under app/ (clean)
#   exit 1  -> at least one reference found (build must fail)
#   exit 2  -> scan dir does not exist (misconfiguration)
#
# The scan directory defaults to backend/app/ but may be overridden with the
# first positional arg, so a negative test can point the guard at a temp dir
# containing a planted offender.
#
# Usage:
#   scripts/ci_no_sa_json_key.sh [SCAN_DIR]

set -euo pipefail

# Resolve the default scan dir relative to THIS script (scripts/ -> backend/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DIR="${SCRIPT_DIR}/../app"

SCAN_DIR="${1:-$DEFAULT_DIR}"

if [ ! -d "$SCAN_DIR" ]; then
  echo "ERROR: scan dir does not exist: $SCAN_DIR" >&2
  exit 2
fi

PATTERN='from_service_account_file|service_account\.json|GOOGLE_APPLICATION_CREDENTIALS=.*json'

FOUND=0
while IFS= read -r -d '' file; do
  # Strip comment lines first so a header explaining the ban never self-trips.
  if grep -v '^[[:space:]]*#' "$file" | grep -E "$PATTERN" > /dev/null 2>&1; then
    echo "OFFENDER: $file" >&2
    grep -v '^[[:space:]]*#' "$file" | grep -En "$PATTERN" >&2 || true
    FOUND=1
  fi
done < <(find "$SCAN_DIR" -type f -print0)

if [ "$FOUND" -ne 0 ]; then
  echo "ERROR: SA JSON key reference found under app/ — GCS must stay keyless (ADC only)." >&2
  echo "       See scripts/ci_no_sa_json_key.sh (T-09-01 / D-09)." >&2
  exit 1
fi

echo "OK: no SA JSON key reference under app/ ($SCAN_DIR)."
exit 0
