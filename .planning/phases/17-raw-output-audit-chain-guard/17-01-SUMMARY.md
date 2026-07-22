---
phase: 17-raw-output-audit-chain-guard
plan: 01
subsystem: api
tags: [alembic, sqlalchemy, fastapi, httpx, sse, tribunal-seam, rls, audit-chain]

# Dependency graph
requires:
  - phase: 16-research-trigger-progress-bridge
    provides: research_runs mirror table (0011), SSE research-run dict, fake_tribunal_client fixture, tribunal_client seam
provides:
  - "research_runs chain_status / chain_broken_at / bundle_key nullable columns (model + migration 0012)"
  - "Tribunal GET /api/runs/{run_id}/research-bundle endpoint serving scrubbed cleaned_reports only (D-01)"
  - "tribunal_client.get_research_bundle + verify_chain seam methods (persist nothing)"
  - "SSE research-run dict carries chain_status / chain_broken_at / bundle_key lock state"
  - "fake_tribunal_client fixture drives verified + broken verify_chain verdicts + get_research_bundle"
affects: [17-02, 17-03, raw-output-download, audit-chain-guard, complete-but-locked]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Add-column migration inherits the table's existing FORCE-RLS row policy (no re-policy/re-grant)"
    - "Read-only seam endpoint returns a whitelisted key subset (cleaned_reports) to exclude discredited content at the boundary"
    - "Overridable-verdict fixture drives both verified and broken terminals from one fixture"

key-files:
  created:
    - backend/app/db/alembic/versions/0012_research_run_chain_bundle.py
    - tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py
  modified:
    - backend/app/db/models/research_runs.py
    - backend/app/db/stream_session.py
    - backend/app/research/tribunal_client.py
    - tribunal/nestor_pulse_sdk/runs/api.py
    - backend/tests/conftest.py
    - backend/tests/test_research_runs_migration.py

key-decisions:
  - "Migration 0012 is a pure add-column: no new RLS policy, grant, or index — the three columns inherit research_runs' 0011 FORCE-RLS row policy"
  - "All three columns nullable with NO server_default — pre-existing live rows (smoke intake e08620c5) stay NULL; the completion path is the sole writer"
  - "verify_chain seam targets /api/audit/verify/{run_id}; get_research_bundle targets /api/runs/{run_id}/research-bundle — both clone get_report's keyword-only + _headers shape"
  - "/research-bundle returns EXACTLY {cleaned_reports}; rejected_claims/contested_notes/verification excluded at the endpoint (D-01)"

patterns-established:
  - "Whitelist-at-the-boundary: the endpoint returns a fixed key subset rather than filtering downstream, so discredited content cannot leak"
  - "Forward-compatible fixture fakes registered with raising=False so Wave-0 scaffolding binds once real methods land"

requirements-completed: [RUN-03]

# Metrics
duration: 18min
completed: 2026-07-22
---

# Phase 17 Plan 01: Phase-17 Contracts + Test Fakes Summary

**research_runs chain/lock/bundle columns (migration 0012), a read-only Tribunal /research-bundle endpoint serving scrubbed cleaned_reports only, two seam-client methods (get_research_bundle + verify_chain), the SSE lock-state dict fields, and the extended fake_tribunal_client fixture — the interface layer Plans 02–03 build against.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-07-22
- **Completed:** 2026-07-22
- **Tasks:** 3
- **Files modified:** 8 (2 created, 6 modified)

## Accomplishments
- Migration 0012 + ResearchRun model gain `chain_status` / `chain_broken_at` / `bundle_key` (all nullable, no server_default), inheriting 0011's FORCE-RLS row policy — no new policy/grant/index.
- New read-only Tribunal endpoint `GET /api/runs/{run_id}/research-bundle` serves the engine's scrubbed `cleaned_reports` ONLY, gated to completed runs, RLS-scoped, with `rejected_claims` deliberately excluded (D-01) and a test proving it never leaks.
- Two seam-client methods (`get_research_bundle`, `verify_chain`) cloned from `get_report`'s keyword-only + `_headers` shape; persist nothing; `verify_chain`'s empty-chain trap documented.
- SSE research-run dict now carries `chain_status` / `chain_broken_at` / `bundle_key` so the summary card can render the chain-verified / complete-but-locked state.
- `fake_tribunal_client` fixture extended with an overridable `verify_verdict` (default verified, settable to broken) plus both new fakes and call counters.

## Task Commits

Each task was committed atomically:

1. **Task 1: research_runs chain/bundle columns + migration 0012 (TDD)** - `7e3383c` (test) → `cea6607` (feat)
2. **Task 2: Tribunal /research-bundle seam endpoint** - `357a363` (feat)
3. **Task 3: seam get_research_bundle + verify_chain; SSE dict + fixture** - `bbbf6c9` (feat)

## Files Created/Modified
- `backend/app/db/alembic/versions/0012_research_run_chain_bundle.py` - Migration 0012 (0012→0011): adds 3 nullable columns, symmetric drop; no RLS/grant/index.
- `backend/app/db/models/research_runs.py` - ResearchRun gains chain_status / chain_broken_at / bundle_key (nullable, no server_default).
- `tribunal/nestor_pulse_sdk/runs/api.py` - New `get_run_research_bundle` handler returning `{cleaned_reports}` only, gated + RLS-scoped.
- `tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py` - Endpoint tests: happy path (rejected_claims excluded), 409/404 gates, cross-tenant 404.
- `backend/app/research/tribunal_client.py` - `get_research_bundle` + `verify_chain` seam methods (persist nothing).
- `backend/app/db/stream_session.py` - `read_latest_research_run_dict` carries the three lock-state keys.
- `backend/tests/conftest.py` - `fake_tribunal_client` gains `verify_verdict` + both fakes + counters.
- `backend/tests/test_research_runs_migration.py` - 0012 source/AST suite + integration nullable-column check.

## Decisions Made
- Migration 0012 kept as a pure add-column so the new columns inherit `research_runs`' existing row-level `space_isolation` + `superadmin_all` policies (a new column on an already-policied/granted table needs no re-policy/re-grant). This keeps the isolation contract unchanged and the migration minimal.
- Columns are nullable with no `server_default` so the ~3 pre-existing live rows on smoke intake `e08620c5` are untouched and the completion path (Plan 02) remains the sole writer of the verdict/key.
- The `/research-bundle` endpoint whitelists `cleaned_reports` at the boundary rather than filtering later, so `rejected_claims` cannot leak even if the cache body shape changes.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Route-shadowing check: confirmed `GET /{run_id}/research-bundle` is not shadowed by the existing `GET /{run_id}` — a single path-parameter segment does not match a two-segment path in Starlette, and the literal-suffix route is registered before `/{run_id}` regardless. Mirrors how the existing `/{run_id}/report` route already coexists.

## Automated Verification (deferred to Cloud Build — no local Python/Docker)
The plan's per-task verification is `MISSING — runs in Cloud Build at wave boundary`. Tests were authored by construction:
- `pytest backend/tests/test_research_runs_migration.py -x` (0012 source/AST + integration nullable-column assertions)
- `pytest tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py -x` (cleaned_reports-only + gates + cross-tenant, xfail-strict without Docker)
- `alembic check` must stay clean (model + 0012 agree).

## Next Phase Readiness
- Plan 02 (completion path) has: the three columns to write, `verify_chain` + `get_research_bundle` seam methods to call at finalize, and the overridable `verify_verdict` fixture to drive verified vs broken terminals.
- Plan 03 (download / re-verify routes) has: the `bundle_key` column, the SSE lock-state fields, and the `/research-bundle` endpoint the finalize step materializes from.
- No blockers introduced. Live proof (like Phase 16) still needs a completed run behind the Anthropic-credits external blocker — same checkpoint pattern as 16-05.

## Threat Surface Scan
- New surface `GET /api/runs/{run_id}/research-bundle` is explicitly in the plan's `<threat_model>` (T-17-01 info-disclosure of rejected_claims → mitigated by returning cleaned_reports only + test; T-17-02 cross-tenant read → RLS-scoped via `Depends(get_db_session)` + cross-tenant test). No new out-of-model surface introduced. No packages installed (T-17-SC N/A).

## Self-Check: PASSED
- All 8 claimed files exist on disk.
- All task commits present: `7e3383c` (test), `cea6607`, `357a363`, `bbbf6c9` (feat).
- SUMMARY.md tracked (force-added; `.planning/` is gitignored).
- Working tree clean.

---
*Phase: 17-raw-output-audit-chain-guard*
*Completed: 2026-07-22*
