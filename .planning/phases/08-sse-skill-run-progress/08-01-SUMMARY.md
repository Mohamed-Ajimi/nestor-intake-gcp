---
phase: 08-sse-skill-run-progress
plan: 01
subsystem: backend-api
tags: [sse, streaming, tenant-isolation, skill-runs, fastapi, async]
requires:
  - "app.db.ai_session.tenant_session (Phase 7 D-05 per-tick GUC discipline)"
  - "app.db.repository.IntakeRepository.get / SkillRunRepository.latest_for_intake+get"
  - "app.db.session.get_skill_run_repo (request-scoped one-tx dependency)"
  - "app.auth.dependencies.get_current_identity (protected_router)"
provides:
  - "GET /intakes/{intake_id}/skill-runs/stream (text/event-stream, API-04)"
  - "GET /intakes/{intake_id}/skill-runs/{run_id} (D-08 full-run projection)"
  - "app.db.stream_session.check_intake_in_scope + read_latest_run_dict"
  - "SkillRunFullView response model"
affects:
  - "backend/app/api/intake_routes.py (2 new routes + 1 model + SSE constants)"
  - "backend/app/db/stream_session.py (NEW module)"
tech-stack:
  added: []
  patterns:
    - "async-generator StreamingResponse with run_in_threadpool per-tick reads (first async handler in the codebase)"
    - "existence-hidden 404 pre-flight BEFORE stream opens (D-04)"
    - "plain-dict per-tick read (never a live ORM row) for statelessness (criterion #2)"
key-files:
  created:
    - "backend/app/db/stream_session.py"
    - "backend/tests/test_sse_stream.py"
    - "backend/tests/test_skill_run_full.py"
  modified:
    - "backend/app/api/intake_routes.py"
decisions:
  - "The nested SSE generator MUST be `async def event_gen()` — an ordinary generator cannot `await run_in_threadpool` / `anyio.sleep`; this makes the module's total `async def` count 2, not 1 (see Deviations)."
  - "Stream helpers patch-seam is `ai_session.get_engine` (they call tenant_session); the full-run read patch-seam is `session.get_engine` (get_skill_run_repo) — the two suites patch different modules accordingly."
metrics:
  duration: "~1 session"
  tasks: 3
  files: 4
  completed: 2026-07-13
requirements: [API-04]
---

# Phase 8 Plan 01: SSE Skill-Run Progress (Backend) Summary

Stateless, DB-backed, tenant-scoped `text/event-stream` skill-run stream (API-04) plus the folded-in full-run read (D-08) that gives the terminal stream event a working review-panel destination — authored RED-first against the final wire contract, implemented behind the existing `tenant_session` discipline so statelessness and cross-tenant denial hold by construction.

## What Was Built

- **`stream_skill_runs` (async, the codebase's first and only `async def` handler)** — pre-flight existence-hidden 404 / null-space 403 via `run_in_threadpool(check_intake_in_scope, ...)` BEFORE any stream opens (D-04); then a `StreamingResponse` whose async generator emits an at-connect snapshot, data events only on change (D-06), a `: ping` heartbeat every ~15s, and closes on the terminal status (`succeeded`/`failed`) or a hard 10-min cap. Every DB touch goes through `run_in_threadpool` so the blocking pg8000 read never runs on the event loop, and `anyio.sleep(TICK_SECONDS)` releases the thread between ticks (RESEARCH Pitfall 1). Registered BEFORE `get_skill_run_full` so the literal `/skill-runs/stream` matches ahead of the parameterized `/skill-runs/{run_id}`.
- **`app/db/stream_session.py` (new)** — `check_intake_in_scope` and `read_latest_run_dict`, each opening a fresh `tenant_session` per call (GUC re-set every tick, T-7-02), returning a plain `bool` / plain `SkillRunView`-shaped dict (never a live ORM row → no `DetachedInstanceError` across ticks). Lives under `app/db/` so the route holds no raw DB symbol (grep-guard). `PermissionError` from a null-space user propagates for the route to turn into a 403.
- **`get_skill_run_full` (sync) + `SkillRunFullView` (D-08)** — a sibling of `list_skill_runs`; scoped `repo.get(run_id)` plus a `str(run.intake_id) == intake_id` match → existence-hidden 404 (BOLA guard); projects `output_parsed` (dict) + `cost_estimate_usd` (Numeric → float).
- **Two RED integration suites** — `test_sse_stream.py` (snapshot→close-on-terminal with a seeded terminal run to avoid the infinite-stream hang; a running→succeeded per-tick statelessness proof; cross-tenant plain-GET 404; null-space 403) and `test_skill_run_full.py` (the D-08 projection; cross-tenant + mismatched-intake 404). Both `pytest.mark.integration`, run in Cloud Build.

## Task Commits

| Task | Name | Commit |
| ---- | ---- | ------ |
| 1 | RED SSE stream + full-run integration suites | b54eab9 |
| 2 | stream_session.py per-tick stateless scoped-read helpers | 9de0100 |
| 3 | async SSE stream handler + full-run read on intake_router | 0bab77f |

## Verification

- **Local (no Python runtime on the dev box — author-by-construction):** `ast.parse` was NOT runnable (no Python); structural verification done via the plan's grep acceptance gates, all of which pass:
  - `def test_` count: 4 (sse) / 2 (full); both carry `pytest.mark.integration`.
  - `stream_session.py`: exactly the two functions; `tenant_session` reused (7 refs); zero `create_engine`/`sessionmaker(`; all four `SkillRunView` keys present.
  - `intake_routes.py`: `async def stream_skill_runs` == 1; route paths present; `run_in_threadpool` (5 refs, incl. both helper links); `TERMINAL = {"succeeded", "failed"}` verbatim; `output_parsed`/`cost_estimate_usd` projected; zero raw DB symbols with an open-paren (grep-guard clean).
- **Cloud Build (full gate — deferred to the user):** `pytest tests/test_sse_stream.py tests/test_skill_run_full.py -x` then the full backend suite.
- **Live (deferred, D-10 combined 7+8 UAT):** unbuffered SSE at ~2s cadence over Cloud Run, paired with the plan 08-03 900s timeout.

## Deviations from Plan

### Auto-fixed / reconciled

**1. [Rule 3 — Blocking spec/impl reconciliation] Total `async def` count is 2, not 1**
- **Found during:** Task 3
- **Issue:** The Task 3 acceptance criterion `grep -c 'async def ' == 1` cannot be satisfied together with the mandated async-generator streaming pattern (RESEARCH Pattern 1, `08-RESEARCH.md:212`), because the nested `event_gen()` MUST be `async def` — an ordinary generator cannot `await run_in_threadpool(...)` or `await anyio.sleep(...)`. The criterion's true intent is "exactly one async **handler**".
- **Fix:** Implemented the required `async def event_gen()` generator; the load-bearing criterion `grep -c 'async def stream_skill_runs' == 1` (exactly one async handler) passes. No other handler was converted to async — the sync-`def`-everywhere rule holds for every request handler.
- **Files modified:** backend/app/api/intake_routes.py
- **Commit:** 0bab77f

**2. [Rule 3 — Test seam correctness] Full-run suite patches `session.get_engine`, not `ai_session.get_engine`**
- **Found during:** Task 1
- **Issue:** The plan's test guidance centered on patching `ai_session.get_engine` (correct for the STREAM helpers, which call `tenant_session`). The D-08 full-run read, however, uses the request-scoped `get_skill_run_repo` dependency from `app.db.session`, which reads `session.get_engine`.
- **Fix:** `test_skill_run_full.py` patches `session_mod.get_engine`; `test_sse_stream.py` patches `ai_session_mod.get_engine`. Each suite patches the exact seam its code path resolves the engine from — otherwise the full-run tests would hit the real (unconfigured) engine.
- **Files modified:** backend/tests/test_skill_run_full.py, backend/tests/test_sse_stream.py
- **Commit:** b54eab9

## Notes / Downstream

- **Not in this plan (owned by sibling wave agents / later plans):** the frontend fetch-ReadableStream reader + `useActiveSkillRun` SSE swap + `useSkillRunFull` un-stub (08-02), and `infra/main.tf` 900s timeout + gcloud-native live apply (08-03). This plan is strictly `backend/`.
- **No schema change / no migration** — `skill_runs` already carries `status`/`output_parsed`/`cost_estimate_usd`/timestamps.
- **No `main.py` change** — `intake_router` is already mounted under `protected_router`.

## Self-Check: PASSED

- FOUND: backend/app/db/stream_session.py
- FOUND: backend/tests/test_sse_stream.py
- FOUND: backend/tests/test_skill_run_full.py
- FOUND (modified): backend/app/api/intake_routes.py
- FOUND commit b54eab9 (Task 1)
- FOUND commit 9de0100 (Task 2)
- FOUND commit 0bab77f (Task 3)
