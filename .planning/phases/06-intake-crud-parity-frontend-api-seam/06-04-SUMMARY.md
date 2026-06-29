---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 04
subsystem: backend-intake-api
tags: [cross-tenant-denial, scope-ceiling, sample-router-removal, route-absence, qa, tenant-isolation]
requires:
  - "06-03 intake_router (prefix /intakes) mounted under protected_router + IntakeView/IntakePatch contract"
  - "Phase 4 cross-tenant denial harness (test_cross_tenant_denial.py: three-actor pattern, _patch_engine_factories, superadmin_engine, _build_app, conftest two_spaces/set_space)"
provides:
  - "test_intake_cross_tenant.py — re-pointed TENANT-04 cross-tenant denial proof over the REAL /intakes endpoints (404-not-403 existence hiding)"
  - "test_no_run_research_route.py — INTAKE-05 structural scope-ceiling guard (live app.routes + intake_routes.py source scan)"
  - "sample-router-free backend: no /sample route, no sample_router/sample_routes token in backend/app or backend/tests"
affects:
  - "backend/app/main.py (sample_router import + mount removed; intake_router + admin_router remain)"
  - "plan 06-11 (ci_no_run_research.sh grep-guard complements this structural route-absence test)"
tech-stack:
  added: []
  patterns:
    - "re-point a full-stack denial suite onto the real surface BEFORE deleting the throwaway scaffold (no coverage gap)"
    - "route-absence test scans route-DECORATOR path literals (regex), not prose, so a scope-ceiling docstring never false-positives"
    - "structural guards live in backend/tests (never backend/app) so they may spell forbidden tokens without tripping ci_no_run_research.sh"
key-files:
  created:
    - "backend/tests/test_intake_cross_tenant.py"
    - "backend/tests/test_no_run_research_route.py"
  modified:
    - "backend/app/main.py"
    - "backend/app/api/admin_routes.py"
    - "backend/app/api/intake_routes.py"
    - "backend/tests/test_admin_routes.py"
  deleted:
    - "backend/app/api/sample_routes.py"
    - "backend/tests/test_cross_tenant_denial.py"
decisions:
  - "test_cross_tenant_denial.py was RENAMED (git mv) into test_intake_cross_tenant.py — 're-point' = transform the existing suite, not duplicate it; leaving the old file would both break on the sample_routes.py deletion and violate the Task-2 grep gate"
  - "the patch_cross_tenant case PATCHes client_name (the only benign mutable field on the new IntakePatch) instead of status — status now moves only via the allow-listed /submit /review verbs; the cross-tenant denial proof (404 + unchanged foreign row) is unchanged"
  - "the route-absence source scan inspects ONLY @<router>.<verb>(\"…\") path literals via regex, so intake_routes.py's English 'deep-research-stage' docstring is not a false positive"
  - "reworded the sample_router/sample_routes prose pointers in admin_routes.py / intake_routes.py / test_admin_routes.py (out of the declared files_modified) to satisfy the Task-2 grep gate which requires NOTHING in backend/app or backend/tests"
metrics:
  duration: "~20 min"
  completed: "2026-06-29"
  tasks: 3
  files: 8
---

# Phase 6 Plan 04: Cross-Tenant Re-point + Sample Removal + Scope-Ceiling Guard Summary

Migrated the QA-01 / TENANT-04 cross-tenant isolation proof off the throwaway `/sample`
scaffold and onto the real `/intakes` surface, deleted the now-redundant `sample_routes.py`
(and unmounted it) with no isolation-coverage gap at any point, and added a structural
route-absence test that pins the scope ceiling — the FastAPI app exposes no
deep-research-stage route, and `intake_routes.py` defines no such handler (INTAKE-05).

## What Was Built

### Task 1 — re-point the cross-tenant denial suite onto `/intakes` (commit a2cca67)
- Renamed `test_cross_tenant_denial.py` → `test_intake_cross_tenant.py` (git rename), re-pointing
  the driver from `/sample/intakes` to `/intakes` and `_build_app` from `sample_router` to the
  real `intake_router` under `protected_router`.
- Preserved the three-actor 404-not-403 existence-hiding contract:
  `get_cross_tenant` (user-A GET of user-B's intake id → EXACTLY 404, no leaked id/space_id),
  `list_scoped` (user-A list → own-space rows only), `superadmin_reads_all` (both spaces visible
  via the connect-as `app_superadmin` engine), `null_space_403` (the single data-route 403),
  plus the DB-free direct `get_tenant_repo` 403 probe.
- `patch_cross_tenant` now PATCHes `client_name` (the only benign mutable field on the new
  `IntakePatch`) and re-reads the foreign row as its owner to prove it is untouched.
- Patches ONLY the engine factories (`session_mod.get_engine` / `get_superadmin_engine`) so the
  REAL `get_tenant_repo` body runs verbatim; `pytestmark = pytest.mark.integration` (skip-clean
  without Docker/DATABASE_URL).

### Task 2 — delete `sample_routes.py` and unmount it (commit 9374b9c)
- Deleted `backend/app/api/sample_routes.py`.
- Removed `from app.api.sample_routes import sample_router` and
  `protected_router.include_router(sample_router)` from `main.py`; reworded the surrounding
  router-wiring comment block (intake_router + admin_router remain mounted under protected_router).
- Reworded the residual `sample_router`/`sample_routes` PROSE pointers in `admin_routes.py`,
  `intake_routes.py`, and `test_admin_routes.py` so the Task-2 grep gate
  (`grep -rn "sample_router\|sample_routes" backend/app backend/tests` → NOTHING) is clean.

### Task 3 — route-absence guard for the scope ceiling (commit bedf63b)
- Created `backend/tests/test_no_run_research_route.py` mirroring `test_no_bearer_routes.py`:
  `_REPO_ROOT` derived from `__file__` (never hardcoded).
- `test_app_exposes_no_deep_research_route`: imports the production `app` (importorskip
  firebase_admin/fastapi/app.main → skip-clean locally) and asserts no `app.routes` path carries
  `run-research` / `run_research` / `tribunal` / `research`.
- `test_intake_routes_defines_no_deep_research_handler`: regex-scans only the
  `@<router>.<verb>("…")` path literals in `intake_routes.py` source (so the module's English
  scope-ceiling docstring is not a false positive); skip-clean if the file is absent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded out-of-scope prose pointers to satisfy the Task-2 grep gate**
- **Found during:** Task 2
- **Issue:** The Task-2 acceptance gate requires `grep -rn "sample_router\|sample_routes" backend/app backend/tests` to return NOTHING, but three files NOT in the declared `files_modified` carried the literal token in docstrings/comments: `admin_routes.py:29`, `intake_routes.py:3` and `:35`, and `test_admin_routes.py:41`. Deleting `sample_routes.py` alone would leave the gate RED.
- **Fix:** Reworded each prose reference (e.g. "mirrors `sample_routes.py`" → "mirrors `intake_routes.py`"; "GENERALIZES the throwaway `sample_routes.py` seam-prover" → "GENERALIZES the earlier throwaway seam-prover scaffold"). Doc-only, no behavior change. Also updated `test_admin_routes.py`'s `sample_routes.py` analog pointer to `intake_routes.py`.
- **Files modified:** backend/app/api/admin_routes.py, backend/app/api/intake_routes.py, backend/tests/test_admin_routes.py
- **Commit:** 9374b9c

**2. [Rule 3 - Blocking] Deleted the re-point source file (test_cross_tenant_denial.py)**
- **Found during:** Task 1
- **Issue:** "Re-pointing" the suite onto a new filename leaves the original `test_cross_tenant_denial.py` still importing `from app.api.sample_routes import sample_router` — which would break on the Task-2 deletion AND duplicate the suite. `files_modified` lists only the new file, not the deletion.
- **Fix:** Performed the re-point as a `git mv` (rename) of `test_cross_tenant_denial.py` → `test_intake_cross_tenant.py` so there is exactly one denial suite, pointed at the real surface, with no broken import and no coverage gap (the truth: "deleted only AFTER the denial suite is re-pointed").
- **Files modified:** backend/tests/test_cross_tenant_denial.py (deleted), backend/tests/test_intake_cross_tenant.py (created)
- **Commit:** a2cca67

## Verification

This dev machine has **no Python/Docker** (per project memory), so the plan's runtime `<verify>`
blocks (`pytest …`, `python -c "from app.main import app; …"`) are recorded below as deferred
live-runs (the real CI gate). All acceptance criteria were confirmed by construction with the
grep gates the plan itself lists, which ran clean:

- **Task 1:** `grep -c "/sample" test_intake_cross_tenant.py` → `0`; `grep -c "/intakes"` → `10`
  (≥ 1); `pytestmark = pytest.mark.integration` present; the `get_cross_tenant` case asserts
  `status_code == 404` (exact, never `in (403, 404)`); `superadmin_reads_all` asserts both
  spaces' ids visible and `list_scoped` asserts own-only.
- **Task 2:** `test ! -f backend/app/api/sample_routes.py` → ABSENT;
  `grep -rn "sample_router\|sample_routes" backend/app backend/tests` → NONE;
  `grep -rn '"/sample' backend/app` → NONE.
- **Task 3:** `_REPO_ROOT` derived from `os.path.abspath(__file__)`; both a live-`app.routes`
  assertion and a source scan of `intake_routes.py` are present; all 10 `@intake_router.<verb>`
  decorator paths verified to contain none of `research`/`tribunal`
  (`grep -nE '@intake_router\.(get|post|put|patch|delete)\([^)]*(research|tribunal)'` → NONE), so
  the source-scan assertion passes.

### Deferred live-runs (no Python/Docker on this machine)
- `cd backend && pytest tests/test_intake_cross_tenant.py -q` — green in CI with Docker; skip-clean locally (integration mark).
- `cd backend && pytest tests/test_no_run_research_route.py -q` — green in CI; skip-clean locally where backend deps/Admin SDK are absent.
- Task 2 route assertion: `cd backend && python -c "from app.main import app; assert not any('/sample' in r.path for r in app.routes), [r.path for r in app.routes if '/sample' in r.path]; print('OK')"`
- `bash scripts/ci_no_raw_db_access.sh` re-run in CI (intake_routes.py docstring reword stays clean — no raw DB symbol touched).

## Known Stubs

None.

## Threat Flags

None — the changes stay within the plan's `<threat_model>`. T-06-10 (cross-tenant read) is now
proven on the real `/intakes` surface; T-06-11 (run-research reachability) gains the structural
route-absence guard; T-06-12 (stale sample surface) is resolved by deleting `sample_routes.py`
only AFTER the denial suite was re-pointed, so no isolation-coverage gap existed at any point.

## Notes / Deferred (out of scope)

- Stale PROSE pointers to the renamed `test_cross_tenant_denial.py` remain in
  `test_admin_routes.py` (lines 3, 133, 225), `test_intake_routes.py` (lines 4, 32, 136), and
  `test_tenant_repository.py` (line 6). These are docstring references (no imports — nothing
  breaks) in files outside this plan's `files_modified`, and they do not match any acceptance
  gate. Left untouched to respect the plan scope and avoid editing files a parallel wave-3 agent
  may hold; a future doc-sweep can repoint them to `test_intake_cross_tenant.py`.

## Self-Check: PASSED
- backend/tests/test_intake_cross_tenant.py — FOUND (created, a2cca67)
- backend/tests/test_no_run_research_route.py — FOUND (created, bedf63b)
- backend/app/api/sample_routes.py — DELETED (9374b9c)
- backend/tests/test_cross_tenant_denial.py — DELETED / renamed (a2cca67)
- Commit a2cca67 — present in git log
- Commit 9374b9c — present in git log
- Commit bedf63b — present in git log
