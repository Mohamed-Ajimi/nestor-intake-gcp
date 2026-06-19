#!/usr/bin/env bash
#
# QA-02 CI isolation guard.
#
# Fails the build if ANY Alembic migration introduces a permissive RLS policy —
# a constant-true USING / WITH CHECK predicate. That permissive form is the
# inherited Supabase bug (a logged-in user reading/writing all tenants) this
# whole phase exists to make unrepeatable. Run this in CI BEFORE deploy.
#
# Contract: the EXIT CODE is the gate.
#   exit 0  -> no permissive policy found (clean migrations)
#   exit 1  -> at least one permissive policy found (build must fail)
# Do NOT gate on an unfiltered `grep -c ... == 0`; rely on grep's own exit code.
#
# The scan directory defaults to backend/app/db/alembic/versions/ but may be
# overridden with the first positional arg, so the negative test can point the
# guard at a temp dir containing a planted offender.
#
# Usage:
#   scripts/ci_no_permissive_rls.sh [VERSIONS_DIR]

set -euo pipefail

# Resolve the default versions dir relative to THIS script (scripts/ -> backend/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DIR="${SCRIPT_DIR}/../app/db/alembic/versions"

SCAN_DIR="${1:-$DEFAULT_DIR}"

if [ ! -d "$SCAN_DIR" ]; then
  echo "ERROR: scan dir does not exist: $SCAN_DIR" >&2
  exit 2
fi

# Case/whitespace-tolerant match of the two forbidden permissive predicates:
#   USING (true)        (any spacing between USING and the paren)
#   WITH CHECK (true)   (any spacing between WITH/CHECK and the paren)
PATTERN='USING[[:space:]]*\(true\)|WITH[[:space:]]+CHECK[[:space:]]*\(true\)'

# grep exits 0 when it finds a match (=> offender present => we must fail),
# and 1 when it finds none (=> clean => we pass). We invert that into the
# guard's own exit code below. `|| true` keeps `set -e` from aborting on the
# no-match (exit 1) case so we control the messaging.
if grep -rEn --include='*.py' "$PATTERN" "$SCAN_DIR"; then
  echo "ERROR: forbidden permissive RLS policy (USING(true)/WITH CHECK(true)) found in migrations." >&2
  echo "       Tenant isolation must use a real space_id predicate — see scripts/ci_no_permissive_rls.sh." >&2
  exit 1
fi

echo "OK: no permissive RLS policies in migrations ($SCAN_DIR)."
exit 0
