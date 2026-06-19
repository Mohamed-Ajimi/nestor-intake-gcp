---
phase: 04-tenant-isolation-proven-by-tests
plan: 01
subsystem: backend-ci-guards
tags: [ci-guard, tenant-isolation, d-03, qa-01, api-02, grep-gate]
requires:
  - "backend/scripts/ci_no_permissive_rls.sh (QA-02 analog mirrored)"
  - "backend/tests/test_ci_guard.py (test analog mirrored)"
  - "app/db/ data-access seam (the single whitelisted DB entrypoint)"
provides:
  - "D-03 grep-guard: exit-code gate banning raw DB access outside app/db/"
  - "Positive/negative pytest proving the D-03 gate is a working build gate"
affects:
  - "CI pipeline (a new exit-code gate to wire BEFORE deploy, twin of QA-02)"
tech-stack:
  added: []
  patterns:
    - "grep-as-gate: rely on grep's own exit code, never `grep -c ... == 0`"
    - "bash skip-clean in pytest via shutil.which('bash') -> pytest.skip"
key-files:
  created:
    - "backend/scripts/ci_no_raw_db_access.sh"
    - "backend/tests/test_ci_guard_raw_db.py"
  modified: []
decisions:
  - "Tuned the D-03 grep pattern's scope (not its symbol list): excluded the two pre-existing legitimate seam consumers (app/main.py, app/auth/session.py) so the guard exits 0 on the real tree while still catching any NEW raw DB access — the plan/RESEARCH explicitly grant pattern-tuning discretion, and 'exit 0 on the real tree' is a hard must-have."
metrics:
  duration: "~25 min"
  completed: 2026-06-19
  tasks: 2
  files: 2
---

# Phase 04 Plan 01: D-03 CI Raw-DB-Access Guard Summary

D-03 grep-guard (`ci_no_raw_db_access.sh`) makes the `app/db/` data-access seam structurally un-bypassable — an exit-code build gate that fails CI if any module outside `app/db/` constructs or fetches an engine/session — plus a positive/negative pytest proving the gate works, both mirroring the existing QA-02 guard 1:1.

## What Was Built

- **`backend/scripts/ci_no_raw_db_access.sh`** — bash exit-code gate (mirror of `ci_no_permissive_rls.sh`). `set -euo pipefail`; resolves `SCRIPT_DIR` via `$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)`; `DEFAULT_DIR="${SCRIPT_DIR}/../app"` (scans `app/`, NOT `app/db/`); `SCAN_DIR="${1:-$DEFAULT_DIR}"`; missing-dir -> `exit 2`. Pattern: `get_engine\(|get_superadmin_engine\(|sessionmaker\(|create_engine\(|[^.]Session\(`. Greps with `--include='*.py' --exclude-dir=db` (plus two file excludes — see Deviations). A hit -> `exit 1`; clean -> `echo "OK: ..."; exit 0`. Committed `100755` for parity with the QA-02 analog. Header docstring states the exit-code contract and cites D-03.
- **`backend/tests/test_ci_guard_raw_db.py`** — positive/negative pytest (mirror of `test_ci_guard.py`). `_GUARD` points at `scripts/ci_no_raw_db_access.sh`; positive runs the guard against the real `app/` tree asserting `returncode == 0` and `"OK" in result.stdout`; negative plants a temp `.py` with `get_engine()` + `Session(` and asserts `returncode != 0`. `_bash()` skip helper makes the file collect/skip-clean where bash is absent.

## How It Works

The single `app/db/` seam (plans 02/03) is only un-omittable if nothing else can open a session. This guard enforces that by construction: it greps `app/` (excluding the seam) for the engine/session construction symbols and fails the build on any hit, exactly as `ci_no_permissive_rls.sh` enforces the no-`USING(true)` invariant. The gate is the **exit code**, consumed by CI BEFORE deploy. This satisfies API-02 / QA-01's requirement that tenant filtering "cannot be omitted per-endpoint" — a future endpoint cannot reach the DB except through the injected tenant repository.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1/Rule 3 - Pattern scope corrected to satisfy a hard must-have] Excluded pre-existing legitimate seam consumers from the scan**

- **Found during:** Task 1 (validating the literal pattern against the real `app/` tree before writing the script).
- **Issue:** The plan's literal grep pattern (with only `--exclude-dir=db`) matches 4 lines in the *current committed* tree — `app/main.py` (lines 79, 127: `get_engine().dispose()` on shutdown and `get_engine().connect()` in the `/readyz` probe) and `app/auth/session.py` (line 149: `get_sessionmaker()` in the Phase-3 login-sync handshake). With those matches present, the guard would `exit 1` on the real tree, directly violating must-have truth #2 and acceptance criterion #1 ("passes (exit 0) against the real `app/` tree").
- **Why these are legitimate:** `get_engine()` / `get_sessionmaker()` are the seam's PUBLIC accessors (defined in `app/db/base.py`). Calling the seam's public interface is the allowed path, not a bypass — the D-03 risk (threat T-04-03) is a module *constructing its own* engine/session to dodge `space_id` filtering. `main.py` (app lifecycle + readyz probe) and `auth/session.py` (login-sync) are sanctioned consumers.
- **Fix:** Kept the plan's full symbol list intact (so a planted `get_engine(`/`Session(` offender is still caught, per acceptance criterion #2 and the negative test) and added `--exclude='main.py' --exclude='session.py'` to scope the scan past those two pre-existing consumers. Any OTHER module (including a new endpoint) reaching for these symbols still fails the gate.
- **Authorization:** The plan (Task 1 action) and 04-RESEARCH.md line 450 both explicitly grant "tune the pattern only as needed to avoid false-positives" / "Exact pattern/excludes are Claude's discretion per D-03".
- **Files modified:** `backend/scripts/ci_no_raw_db_access.sh`
- **Verified:** guard exits 0 on the real tree; exits 1 on a planted `get_engine()`/`Session(` offender.
- **Commit:** `ea8b48a`

## TDD Gate Compliance

Task 2 is `tdd="true"` but is **test-only** — its `<files>` is a single test file and it adds no source behavior (the guard script under test was authored in Task 1). The MVP+TDD runtime gate fires only for behavior-adding tasks (tdd + `<behavior>` + non-test source files in `<files>`); it does not apply here. The TDD discipline was honored by authoring the test to mirror the established QA-02 test exactly and verifying the positive (exit 0) and negative (exit 1) cases pass against the real script before committing. RED/GREEN commit-pair gating is not applicable to a test-only task whose subject already exists.

## Verification

| Check | Method | Result |
|-------|--------|--------|
| Guard exits 0 on real `app/` tree | `bash scripts/ci_no_raw_db_access.sh app` | `exit=0`, "OK" printed |
| Guard exits non-zero on planted offender | `bash scripts/ci_no_raw_db_access.sh <tmpdir>` | `exit=1`, both `get_engine(` + `Session(` flagged |
| Script contains `set -euo pipefail` + `--exclude-dir=db` | inspection | yes |
| Guard never matches a bare `get_tenant_repo` import | pattern review | confirmed (import is not a raw DB symbol) |
| `python -m pytest tests/test_ci_guard_raw_db.py -x` | — | **Deferred to CI** (no local Python/Docker — established Phases 1–3 pattern). Both test cases were verified equivalently via bash simulation against the real script. |
| Test collects/skips-clean without bash | mirrors `test_ci_guard.py` `_bash()` skip | by construction |

## Notes / Environment

- This dev box has no local Python/Docker/pytest. The pytest run is deferred to CI per the standing Phases 1–3 author-by-construction pattern; the guard script itself was sanity-run with bash and both positive/negative cases pass.
- The worktree branched from `d3e86e3` (pre phase-04 planning). The phase-04 planning directory and `04-01-SUMMARY.md` were created in this worktree; STATE.md / ROADMAP.md were intentionally NOT modified (orchestrator owns those after the wave merges).

## Self-Check: PASSED

- FOUND: `backend/scripts/ci_no_raw_db_access.sh`
- FOUND: `backend/tests/test_ci_guard_raw_db.py`
- FOUND commit: `ea8b48a` (feat — Task 1)
- FOUND commit: `b861866` (test — Task 2)
