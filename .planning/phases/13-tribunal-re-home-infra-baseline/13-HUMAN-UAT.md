---
status: partial
phase: 13-tribunal-re-home-infra-baseline
source: [13-VERIFICATION.md]
started: 2026-07-20T17:05:00Z
updated: 2026-07-20T17:05:00Z
---

## Current Test

[awaiting human decision on #2]

## Tests

### 1. Live service health on post-review revision (20260720-fix2)
expected: /health 200 {"status":"ok"} and /readyz 200 {"status":"ready","db":"ok"}
result: pass — verified live this session immediately after the fix2 redeploy (operator-delegated agent, curl with identity token; recorded in 13-PROOF-RESULTS.md)

### 2. Queue-path dispatch proof on the fixed revision
expected: a run enqueued through the REAL worker queue path (not the smoke script's direct-pipeline path) is claimed by worker_loop, consumed via the fencing token, dispatched exactly once, completes green with verify_chain OK
result: deferred — operator decision 2026-07-20: accept test-level proof (22/22 Cloud Build gate incl. CR-01 regression on real Postgres) and prove the live queue path as the FIRST step of Phase 16's trigger work

### 3. Database schema validation (live)
expected: tribunal.tribunal_alembic_version = 0010; tribunal tables present; zero tribunal-table leak into public
result: pass — verified live this session via the one-off tribunal-verify Cloud Run job (catalog queries against nestor-pg; output in 13-PROOF-RESULTS.md)

## Summary

total: 3
passed: 2
issues: 0
pending: 1
skipped: 0
blocked: 0

## Gaps
