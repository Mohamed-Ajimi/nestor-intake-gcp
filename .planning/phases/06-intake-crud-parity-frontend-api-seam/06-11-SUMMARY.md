---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 11
subsystem: ci-scope-guard
tags: [scope-ceiling, ci-guard, grep-guard, run-research, tribunal, INTAKE-05, D-06]
requires:
  - "06-04 structural route-absence test (test_no_run_research_route.py) — this guard is its preventive twin"
  - "06-06 frontend run-research invoke deletion — so the positive test passes on the clean tree"
  - "06-10 post-decomposed component neutralization — so frontend/src carries no reachable run-research invocation"
  - "backend/scripts/ci_no_raw_db_access.sh — the D-03 exit-code contract this guard mirrors"
provides:
  - "backend/scripts/ci_no_run_research.sh — CI grep-guard: build fails if a run-research/Tribunal invocation reappears in backend/app or frontend/src (INTAKE-05/D-06)"
  - "backend/tests/test_scope_guard_run_research.py — positive (clean tree, exit 0) + negative (planted invoke, non-zero) proof; skip-clean without bash"
affects:
  - "CI pipeline (a new guard to wire alongside ci_no_raw_db_access.sh / ci_no_permissive_rls.sh)"
tech-stack:
  added: []
  patterns:
    - "preventive grep-guard gates on grep's OWN exit code (never `grep -c == 0`) — mirrors the proven D-03 contract"
    - "pattern anchored to real invocation/route/call/trigger syntax, NOT bare tokens, so scope-ceiling docstrings + the Dutch UI string never false-positive"
    - "guard scans MULTIPLE default trees (backend/app + frontend/src) yet accepts a single override dir so the negative test can aim it at a temp offender"
key-files:
  created:
    - "backend/scripts/ci_no_run_research.sh"
    - "backend/tests/test_scope_guard_run_research.py"
  modified: []
decisions:
  - "Refined the patterns-doc's naive token list to an invocation-anchored pattern: the literal token alternation would false-positive on 8 legitimate prose references and FAIL the mandatory exit-0 requirement — see Deviations"
  - "Kept the trigger/function identifiers (tg_bump_to_in_research, tg_bump_to_delivered, persist_questions_on_research_start) and run_research (underscore) as literal alternatives — they appear NOWHERE in the current tree, so literal matching is both precise and safe (these strings only ever occur as a real CREATE TRIGGER/FUNCTION or a function call)"
  - "Negative test plants a genuine invoke(\"run-research\") call (not a bare substring) so the test stays consistent with the precise guard while still 'containing run-research'"
metrics:
  duration: "~15 min"
  completed: "2026-06-29"
  tasks: 2
  files: 2
---

# Phase 6 Plan 11: CI Scope-Ceiling Grep-Guard (INTAKE-05 / D-06) Summary

Added the preventive CI grep-guard that makes the scope ceiling permanent: the build now fails if
any genuine invocation of the out-of-scope deep-research stage (run-research / Tribunal) or its
deferred post-`decomposed` DB triggers ever reappears in `backend/app` or `frontend/src`. This is
the final layer over the structural route-absence test (plan 04), the frontend invoke deletion
(plan 06), and the post-decomposed component neutralization (plan 10) — the guard's positive test
passes on the clean tree precisely because those plans already removed run-research.

## What Was Built

### Task 1 — `backend/scripts/ci_no_run_research.sh` (commit 54e5895)
- Mirrors `ci_no_raw_db_access.sh`: `set -euo pipefail`, `SCRIPT_DIR` via `BASH_SOURCE`, exit-code
  contract (0 clean / 1 offender / 2 misconfig), and the **gate-on-grep's-own-exit-code** rule
  (never `grep -c == 0`).
- Scans BOTH `backend/app` and `frontend/src` by default (`--include='*.py' --include='*.ts'
  --include='*.tsx'`); a single positional arg overrides the scan dir so the negative test can aim
  it at a temp dir.
- The pattern is **anchored to real invocation/route/call/trigger syntax** — `invoke(...run-research)`,
  `invoke(...tribunal)`, a `/run-research` route or fetch URL segment, `run_research(` / `.run_research`,
  the literal deferred trigger+function names, and a Python `import`/`from … tribunal` — so it never
  matches the bare enum `in_research`, `Research*` component names, or scope-ceiling prose.
- **Verified: exits 0 against the current real tree** (see Verification).

### Task 2 — `backend/tests/test_scope_guard_run_research.py` (commit b67ad91)
- Mirrors `test_ci_guard.py` verbatim in structure: `_bash()` skip-clean when bash is absent,
  `_run_guard()` subprocess runner, the contract under test being the EXIT CODE.
- `test_guard_passes`: runs the guard with no args (scans the real `backend/app` + `frontend/src`),
  asserts exit 0 and `"OK"` in stdout.
- `test_guard_fails_on_planted_offender`: writes a temp `*.ts` containing
  `supabase.functions.invoke("run-research", …)`, points the guard at that tmp dir, asserts non-zero.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Refined the naive token pattern to an invocation-anchored pattern (mandatory to satisfy the exit-0 acceptance criterion)**
- **Found during:** Task 1
- **Issue:** The patterns-doc/interface literal alternation
  `run-research|run_research|Tribunal|tribunal|tg_bump_to_in_research|tg_bump_to_delivered|persist_questions_on_research_start`
  matches 8 PRE-EXISTING legitimate references — scope-ceiling docstrings/comments in
  `0001_baseline_schema.py` (lines 18, 452), `0004_triggers.py` (lines 5, 7), `db/models/findings.py`
  (1, 3), `db/models/intake.py` (9), `db/models/research.py` (6), and the Dutch operator UI string in
  `frontend/src/components/intake/NextStepBanner.tsx:247` ("…laat run-research lopen."). With the naive
  pattern the guard exits **1** against the clean tree, directly violating the plan's primary
  acceptance criterion ("exits 0 against the real tree") and making the guard useless (always red).
- **Fix:** Anchored the pattern to genuine reachable syntax instead of bare tokens: `invoke(…run-research)`,
  `invoke(…run_research)`, `invoke(…tribunal)`, `/run-research` (route/URL), `run_research(`,
  `.run_research`, the literal deferred trigger/function identifiers (which appear nowhere today), and
  Python `from`/`import … tribunal`. The 8 prose references contain none of these forms, so the guard is
  precise AND green.
- **Files modified:** backend/scripts/ci_no_run_research.sh
- **Commit:** 54e5895

## Verification

`bash` is available on this dev box (Git Bash), so the SHELL guard was RUN directly; Python/pytest
are NOT installed (per project memory), so the pytest invocation is recorded as a deferred live-run.

**Guard run against the real tree (RAN, exit 0):**
```
$ cd backend && bash scripts/ci_no_run_research.sh
OK: no run-research/Tribunal invocation in …/backend/scripts/../app …/backend/scripts/../../frontend/src.
guard exit: 0
```

**Per-form behavior confirmed by construction (RAN):**
- planted `invoke("run-research")` *.ts → exit **1** (offender)
- `@router.post("/run-research")` *.py → exit **1** (offender)
- `tg_bump_to_in_research` in a migration *.py → exit **1** (offender)
- missing scan dir → exit **2** (misconfig)
- benign tokens (`ResearchArtifacts`, `in_research`, prose "laat run research lopen") → exit **0** (clean)

**Test-contract simulation (RAN via bash — the exact two subprocess calls the test makes):**
- `bash scripts/ci_no_run_research.sh` (no args) → `rc=0` (matches `test_guard_passes`)
- guard pointed at a tmp dir holding `invoke("run-research")` → `rc=1` (matches `test_guard_fails_on_planted_offender`)

### Deferred live-runs (no Python/pytest on this machine)
- `cd backend && pytest tests/test_scope_guard_run_research.py -x -q` — green in CI (or skip-clean
  where bash is absent). Both assertions were proven by running the underlying bash guard directly
  (rc 0 / rc 1 above), so this is a formality in CI.

## Known Stubs

None.

## Threat Flags

None — the change stays within the plan's `<threat_model>`. T-06-29 (reintroducing run-research) is
mitigated by the grep-guard + its negative test; T-06-30 (guard false-negative via `grep -c`) is
mitigated by gating on grep's own exit code (the proven `ci_no_raw_db_access.sh` contract).

## Notes / Deferred (out of scope)

- Wiring the guard into the CI workflow (alongside `ci_no_raw_db_access.sh` / `ci_no_permissive_rls.sh`)
  is a CI-config concern outside this plan's `files_modified`; the guard is authored and proven, ready
  to add as a CI step.

## Self-Check: PASSED
- backend/scripts/ci_no_run_research.sh — FOUND (created, 54e5895)
- backend/tests/test_scope_guard_run_research.py — FOUND (created, b67ad91)
- Commit 54e5895 — present in git log
- Commit b67ad91 — present in git log
- Guard RAN against real tree → exit 0 (no false positives on the 8 documented legitimate references)
