---
phase: 12-frontend-deploy-cutover-supabase-retirement
plan: "01"
subsystem: cutover-validation
tags: [ci-guard, uat, parity-gate, supabase-independence, d-11, d-05]
requires:
  - "backend/scripts/ci_no_permissive_rls.sh (exit-code contract analog)"
  - "frontend/scripts/ci_no_hardcoded_dutch.sh (--self-test harness analog)"
  - "phases 07-11 HUMAN-UAT files (carry-forward inventory source)"
provides:
  - "frontend/scripts/ci_no_supabase_in_bundle.sh (D-11 bundle guard — build-fail gate)"
  - "12-UAT.md (D-05 consolidated parity checklist — the single cutover gate)"
affects:
  - "Plan 02 Dockerfile (wires the guard after `npm run build`)"
  - "The whole-phase parity sign-off (12-UAT is the gate every later plan feeds)"
tech-stack:
  added: []
  patterns:
    - "CI guard-script idiom: exit-code-is-the-gate (0 clean / 1 offender / 2 missing) + planted-offender --self-test"
    - "Doc aggregation: consolidated UAT inherits every open item verbatim (no re-authoring)"
key-files:
  created:
    - "frontend/scripts/ci_no_supabase_in_bundle.sh"
    - ".planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md"
  modified: []
decisions:
  - "Bundle-guard PATTERN = supabase\\.co|VITE_SUPABASE|\"role\":\"anon\"|eyJhbGciOi (URL + build-arg + anon-claim + JWT-prefix), copied verbatim from the plan/RESEARCH spec."
  - "Self-test plants its offender under a `server/` subdir (mirrors Nitro `.output/server/`) to exercise the recursive scan; asserts non-zero re-invocation."
  - "12-UAT carries all 17 inventory rows PLUS 2 E2E roles = 21 checkboxes, guaranteeing line count >= sum of open items (Pitfall 5 guard)."
metrics:
  duration: 11
  completed: 2026-07-14
  tasks: 2
  files: 2
---

# Phase 12 Plan 01: Wave-0 Cutover Validation Artifacts Summary

Created the two Wave-0 gates this phase depends on: the D-11 Supabase bundle guard (a build-fail
CI script that greps the built `.output/` for any Supabase URL/anon-key signature) and the D-05
consolidated `12-UAT.md` parity checklist (aggregating all 17 open HUMAN-UAT items from phases 7–11
plus the two-role `draft → decomposed` E2E).

## What Was Built

### Task 1 — D-11 Supabase bundle guard (`frontend/scripts/ci_no_supabase_in_bundle.sh`)
- Mirrors the two existing guard scripts (`backend/scripts/ci_no_permissive_rls.sh` exit-code
  contract + `frontend/scripts/ci_no_hardcoded_dutch.sh` `--self-test` harness).
- `set -euo pipefail`; `SCAN_DIR="${1:-.output}"` (overridable so the self-test points at a temp dir).
- `PATTERN='supabase\.co|VITE_SUPABASE|"role":"anon"|eyJhbGciOi'` scanned via `grep -rEn`.
- **Exit code IS the gate:** `0` clean (`OK: no Supabase signature`), `1` offender present
  (`ERROR: … INFRA-05/D-11 violation`), `2` scan dir missing. No `grep -c … == 0` construct.
- `--self-test` plants `https://xyz.supabase.co` in a `mktemp -d`, re-invokes the guard, and
  asserts non-zero; prints `SELF-TEST OK`.
- Made executable (`chmod +x`); Plan 02's Dockerfile invokes it via `sh scripts/… .output` right
  after `npm run build`.
- **Verified:** self-test → exit 0; offender dir → exit 1; clean dir → exit 0; missing dir → exit 2.

### Task 2 — Consolidated parity checklist (`12-UAT.md`, D-05)
- Aggregates (does NOT re-author) the 17-row Consolidated Parity Inventory (12-RESEARCH § Pitfall 5)
  as the checklist spine, one section per source phase (`## Phase 7 … Phase 11 (inherited)`), each
  item preserving its source reference (`07-UAT #7`) and prior status (blocked/pending/failed).
- Adds a `## Two-role draft → decomposed E2E (roadmap SC2, D-06)` section: a superadmin run and a
  seeded-user run (invited via the REAL invite flow) through a dedicated test space, ending at
  `decomposed` with `run-research`/Tribunal explicitly unreachable (scope ceiling).
- Header states the D-08 independence framing (Supabase untouched; independence proven code-side via
  the D-11 guard). Closing "Gate status" line: PARITY GREEN only when every box is ticked.
- 21 `- [ ]` checkboxes (17 inherited + 2 E2E roles + 1 gate + 1 combined P11 #1–3 row structure);
  124 lines. All category tokens present (Kopieer, transcribe, RecipientPicker, NL/FR/EN, cross-space).

## Deviations from Plan

None — plan executed exactly as written. Both tasks are `type="auto"` and all acceptance criteria
passed on first verification.

## Verification Results

- `bash frontend/scripts/ci_no_supabase_in_bundle.sh --self-test` → exit 0, `SELF-TEST OK`.
- Offender temp dir → exit 1; clean temp dir → exit 0; non-existent path → exit 2.
- Guard contains `ci_no_supabase_in_bundle` and `VITE_SUPABASE`; the two `grep -c` mentions are
  comments (documenting what NOT to do), not the gate.
- `grep -c "^- \[ \]" 12-UAT.md` → 21 (>= 18 required).
- Phase markers `07-UAT`/`08-UAT`/`09-UAT`/`10-UAT`/`11-UAT` all present; two-role E2E section
  references D-06; scope ceiling (`decomposed`, `run-research` not reachable) asserted.

## Threat Coverage

- **T-12-01 (Information Disclosure — bundle):** mitigated by the D-11 guard; the negative self-test
  proves the guard actually catches a planted offender (not a no-op).
- **T-12-02 (Repudiation — parity coverage):** mitigated by construction — 12-UAT carries all 17
  inventory rows + the E2E, so line count (21) >= sum of open items (Pitfall 5 warning-sign averted).
- **T-12-SC (package installs):** N/A — this plan installs nothing.

## Notes for Downstream Plans

- Plan 02 (Dockerfile) must wire `RUN sh scripts/ci_no_supabase_in_bundle.sh .output` immediately
  after `npm run build` in the build stage.
- 12-UAT.md is the single parity gate; every later plan (backend catch-up, frontend deploy,
  gap-closure) feeds boxes here. Do not mark PARITY GREEN until all 21 boxes are ticked live.
- Live UAT execution requires a fully-deployed backend (D-04 catch-up) and is a HUMAN activity —
  this plan only authors the checklist, it does not run it.

## Self-Check: PASSED

- FOUND: frontend/scripts/ci_no_supabase_in_bundle.sh
- FOUND: .planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md
- FOUND commit 0528529 (Task 1 — bundle guard)
- FOUND commit ead0c02 (Task 2 — 12-UAT checklist)
