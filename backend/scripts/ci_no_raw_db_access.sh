#!/usr/bin/env bash
#
# D-03 CI raw-DB-access guard.
#
# Fails the build if ANY raw DB symbol is used in app/ OUTSIDE the whitelisted
# data-access seam (app/db/). The seam is the single place allowed to construct
# engines / sessions; every feature endpoint must reach the database only through
# the injected tenant repository. If another module can open its own session or
# engine, the per-space tenant filter becomes omittable per-endpoint — which is
# exactly the inherited Supabase isolation hole (a logged-in user reading every
# tenant) this whole phase exists to make unrepeatable. Run this in CI BEFORE
# deploy. This is the structural twin of scripts/ci_no_permissive_rls.sh (QA-02).
#
# Contract: the EXIT CODE is the gate.
#   exit 0  -> no raw DB access found outside app/db/ (clean)
#   exit 1  -> at least one raw DB symbol found outside app/db/ (build must fail)
#   exit 2  -> scan dir does not exist (misconfiguration)
# Do NOT gate on an unfiltered `grep -c ... == 0`; rely on grep's own exit code.
#
# The scan directory defaults to backend/app/ (NOT app/db/) but may be overridden
# with the first positional arg, so the negative test can point the guard at a
# temp dir containing a planted offender.
#
# Usage:
#   scripts/ci_no_raw_db_access.sh [SCAN_DIR]

set -euo pipefail

# Resolve the default scan dir relative to THIS script (scripts/ -> backend/).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_DIR="${SCRIPT_DIR}/../app"   # scan app/, NOT app/db/

SCAN_DIR="${1:-$DEFAULT_DIR}"

if [ ! -d "$SCAN_DIR" ]; then
  echo "ERROR: scan dir does not exist: $SCAN_DIR" >&2
  exit 2
fi

# The forbidden raw-DB symbols. Constructing or fetching an engine/session
# anywhere but the app/db/ seam is what reopens the per-endpoint tenant hole:
#   get_engine(            engine accessor
#   get_superadmin_engine( cross-tenant bypass engine accessor
#   sessionmaker(          session factory construction
#   create_engine(         engine construction
#   [^.]Session(           direct Session construction (the [^.] avoids matching
#                          attribute access like `db.Session(` false-positives).
PATTERN='get_engine\(|get_superadmin_engine\(|sessionmaker\(|create_engine\(|[^.]Session\('

# The app/db/ directory IS the seam -> exclude it. main.py (app lifecycle:
# dispose-on-shutdown + the /readyz SELECT 1 probe) and auth/session.py (the
# Phase-3 login-sync handshake) are the pre-existing sanctioned consumers of the
# seam's PUBLIC accessors (get_engine()/get_sessionmaker()) — calling the seam's
# interface is the allowed path, not a bypass — so they are excluded by name.
# Any OTHER module reaching for these symbols (including a new endpoint) is an
# offender and fails the gate. A bare import of the tenant repo/dependency
# (e.g. `from app.db import get_tenant_repo`) is not a raw DB symbol and never
# matches the pattern.
#
# grep exits 0 when it finds a match (=> offender present => we must fail), and 1
# when it finds none (=> clean => we pass). We invert that into the guard's own
# exit code below.
if grep -rEn --include='*.py' --exclude-dir=db --exclude='main.py' --exclude='session.py' "$PATTERN" "$SCAN_DIR"; then
  echo "ERROR: raw DB access (engine/session construction) found outside app/db/." >&2
  echo "       All DB access must go through the app/db/ seam — see scripts/ci_no_raw_db_access.sh (D-03)." >&2
  exit 1
fi

echo "OK: no raw DB access outside app/db/ ($SCAN_DIR)."
exit 0
