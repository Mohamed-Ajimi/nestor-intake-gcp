#!/usr/bin/env bash
#
# Phase 11 (I18N-01) CI externalization guard — QA-02 style.
#
# Fails the build if a hardcoded Dutch string (stopword heuristic) appears in
# in-scope frontend source. After the Phase 11 externalization sweep, every
# user-visible string must live in src/locales/*/*.json and be rendered via
# t() — a Dutch literal in a .ts/.tsx file means a string escaped the sweep.
#
# Contract: the EXIT CODE is the gate (mirrors backend/scripts/ci_no_permissive_rls.sh).
#   exit 0  -> no hardcoded Dutch found in in-scope source (clean)
#   exit 1  -> at least one offender found (build must fail)
#   exit 2  -> scan dir missing (misconfiguration)
# Do NOT gate on a match-count-equals-zero construct; rely on grep's own exit code.
#
# Exemptions (deliberate Dutch / generated / out-of-scope surfaces):
#   src/locales/**   - the catalogs themselves (nl catalog IS Dutch)
#   *.gen.ts         - generated route tree
#   ui/**            - shadcn primitives (generated, never hand-edited)
#   admin.sales.*    - sales product, out of Phase 11 scope
#   coming-soon*     - placeholder surfaces, out of scope
#   *.test.*         - test fixtures may cite Dutch literals
#
# CI invokes BOTH modes (from the repo root):
#   bash frontend/scripts/ci_no_hardcoded_dutch.sh               # positive scan (the gate)
#   bash frontend/scripts/ci_no_hardcoded_dutch.sh --self-test   # guard-mechanics negative test
#
# NOTE: until the 11-03..11-06 externalization plans complete, the positive scan
# is EXPECTED to fail (the source still contains Dutch). The phase gate runs the
# full scan after Wave 2; the self-test proves the guard mechanics today.
#
# Usage:
#   frontend/scripts/ci_no_hardcoded_dutch.sh [SCAN_DIR]
#   frontend/scripts/ci_no_hardcoded_dutch.sh --self-test

set -euo pipefail

# Dutch stopwords that only appear in prose, not identifiers (word-bounded, case-insensitive).
PATTERN='\b(niet|geen|wordt|klant|ingelogd|opnieuw|versturen|opslaan|verwijderen|annuleren|beschikbaar|vernieuwen|ruimte|gebruiker|verplicht|mislukt)\b'

# Surfaces where Dutch is deliberate, generated, or out of scope (see header).
#
# Path-based exemptions ONLY (never weaken the stopword PATTERN above). Every entry
# here is a surface D-01 declares out of Phase 11 scope (stays Dutch) or a
# generated/never-hand-edited file:
#   /locales/                 - the catalogs themselves (nl catalog IS Dutch)
#   \.gen\.ts                 - generated route tree
#   /ui/                      - shadcn primitives (generated)
#   admin\.sales\.            - sales ROUTE files (out of scope, D-01)
#   /components/sales/        - sales COMPONENT tree (out of scope, D-01 — e.g. BattlecardBlocks, SalesContextFields, BattlecardMarkdown)
#   salesLabels\.            - sales label map (out of scope, D-01)
#   generateBattlecardPdf\.  - sales PDF exporter (out of scope, D-01)
#   [Cc]oming-?[Ss]oon        - coming-soon placeholder surfaces (out of scope, D-01 — ComingSoonPage + kebab coming-soon)
#   \.test\.                  - test fixtures may cite Dutch literals
EXEMPT='(/locales/|\.gen\.ts|/ui/|admin\.sales\.|/components/sales/|salesLabels\.|generateBattlecardPdf\.|[Cc]oming-?[Ss]oon|\.test\.)'

run_scan() {
  local scan_dir="$1"

  if [ ! -d "$scan_dir" ]; then
    echo "ERROR: scan dir does not exist: $scan_dir" >&2
    exit 2
  fi

  # grep exits 0 when a (non-exempt) offender survives the filter => we must fail.
  # The pipeline's exit code is the second grep's: 0 = offender printed, 1 = none.
  if grep -rEni --include='*.ts' --include='*.tsx' "$PATTERN" "$scan_dir" \
       | grep -vE "$EXEMPT"; then
    echo "ERROR: hardcoded Dutch string found in in-scope source (see matches above)." >&2
    echo "       Externalize it to src/locales/*/*.json and render via t() — see I18N-01." >&2
    exit 1
  fi

  echo "OK: no hardcoded Dutch in in-scope source ($scan_dir)."
  exit 0
}

# ---------------------------------------------------------------------------
# Negative self-test (D-13 convention): plant an offender in a temp, NON-exempt
# path, point the guard at it, and assert the guard exits non-zero.
# ---------------------------------------------------------------------------
if [ "${1:-}" = "--self-test" ]; then
  TMP_DIR="$(mktemp -d)"
  trap 'rm -rf "$TMP_DIR"' EXIT

  mkdir -p "$TMP_DIR/src"
  printf 'const x = "niet beschikbaar";\n' > "$TMP_DIR/src/offender.ts"

  # Re-invoke THIS script against the planted offender; capture the exit code.
  # `|| rc=$?` keeps set -e from aborting on the expected non-zero exit.
  rc=0
  bash "${BASH_SOURCE[0]}" "$TMP_DIR" > /dev/null 2>&1 || rc=$?

  if [ "$rc" -eq 0 ]; then
    echo "SELF-TEST FAILED: guard did NOT flag a planted Dutch offender." >&2
    exit 1
  fi

  echo "SELF-TEST OK: planted offender triggered non-zero exit ($rc)."
  exit 0
fi

run_scan "${1:-frontend/src}"
