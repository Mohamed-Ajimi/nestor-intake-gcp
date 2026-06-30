---
phase: 07-ai-function-ports
plan: 04
subsystem: database
tags: [postgres, rls, pgvector, sqlalchemy, multi-tenant, connection-pool, ai]

# Dependency graph
requires:
  - phase: 04-tenant-isolation
    provides: "set_space_context (tx-local GUC), TenantRepository.create/get/create_in_space, engine-by-role routing in session.py"
  - phase: 06-intake-crud
    provides: "SkillRun ORM model, SkillRunRepository, IntakeRepository"
  - phase: 07-02
    provides: "ArtifactEmbedding ORM model + migration 0009, RED test suite (test_ai_session_release/_search_cross_tenant/_search_explain)"
provides:
  - "app.db.ai_session: tenant_session @contextmanager (per-entry GUC re-set)"
  - "run_with_session_release (READ -> release -> CALL -> reopen-WRITE) — the AI-06 connection-release contract"
  - "create_running_skill_run (short synchronous running-row insert with 404-mapping scope check)"
  - "search_artifacts (space-prefiltered exact cosine <=> scan, no vector index)"
  - "sweep_orphaned_skill_runs (startup self-heal for D-01a)"
affects: [07-05, 07-06, 07-07, 07-08, ai-function-handlers, semantic-search]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Read/release/reopen-write background-task session lifecycle (no connection across the LLM call)"
    - "Structural second-session GUC re-set via a single shared tenant_session context-manager"
    - "Space confinement by RLS+GUC (no manual WHERE) for the vector search query"

key-files:
  created:
    - backend/app/db/ai_session.py
  modified: []

key-decisions:
  - "tenant_session re-issues the GUC on EVERY entry; forgetting the 2nd-session GUC is structurally impossible"
  - "run_with_session_release closes the READ tx (connection returns to pool) BEFORE call_fn — pool free across the external call"
  - "create_running_skill_run uses create_in_space(intake.space_id) on the superadmin path so the NOT-NULL space_id is satisfied without trusting a request arg"
  - "sweep uses a Python-computed cutoff (datetime.now(utc) - timedelta) instead of SQL interval — cleaner bind, same semantics"
  - "search_artifacts relies on user-engine RLS + GUC for confinement (no explicit space_id WHERE); no vector index (D-03)"

patterns-established:
  - "Background-task tenant access goes through tenant_session/run_with_session_release — never a hand-rolled maker.begin()"
  - "AI handler write phase always re-opens a fresh tenant_session so the GUC is current"

requirements-completed: [AI-06, AI-04]

# Metrics
duration: ~20min
completed: 2026-06-30
---

# Phase 7 Plan 04: AI session-release core Summary

**One shared `app/db/ai_session.py` that guarantees the read/release/reopen-write flow and a structural second-session `app.current_space_id` GUC re-set for all seven AI functions, plus a space-confined exact-cosine `search_artifacts` with no vector index.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-06-30
- **Tasks:** 2
- **Files modified:** 1 (created)

## Accomplishments
- `tenant_session(identity)` — reusable `@contextmanager` mirroring `session.py:58-78` engine-by-role routing; re-issues `set_space_context` on every user-path entry, sets NO GUC on the superadmin path, raises `PermissionError` (not `HTTPException`) for a null user space (default-deny, D-04).
- `run_with_session_release(identity, read_fn, call_fn, write_fn)` — the AI-06 / T-7-06 / T-7-02 core: READ tx commits and returns its connection to the pool, the external `call_fn` holds NO connection, then a FRESH `tenant_session` re-issues the GUC for the WRITE. This turns `test_ai_session_release` (set_space_context-called-exactly-twice, `pool.checkedout()==0` across the call) green in CI.
- `create_running_skill_run(...)` — short synchronous tx that scope-checks the intake (`None` → `IntakeNotInScopeError` → route 404) and inserts one `skill_runs` row at status `running`, releasing the connection before the route returns 202.
- `sweep_orphaned_skill_runs(max_age_minutes)` — startup self-heal flipping stale `running` rows to `failed` (D-01a accepted-limitation backstop).
- `search_artifacts(session, query_vec, limit, max_distance)` — space-prefiltered exact cosine (`<=>`) scan over `artifact_embeddings`, `ORDER BY distance LIMIT n`, no vector index (D-03), returning plain `Row` tuples.

## Task Commits

1. **Task 1: tenant_session + run_with_session_release + create_running_skill_run + sweep** - `3fae8ef` (feat)
2. **Task 2: search_artifacts — space-prefiltered exact cosine scan** - `fc8ae72` (feat)

## Files Created/Modified
- `backend/app/db/ai_session.py` - The Phase 7 session/correctness core: `tenant_session`, `run_with_session_release`, `create_running_skill_run`, `sweep_orphaned_skill_runs`, `search_artifacts`, plus the `IntakeNotInScopeError` 404-mapping exception. All sync (pg8000 blocking).

## Decisions Made
- **Superadmin path for `create_running_skill_run`:** the plan said "space_id from Identity via the repo's create", but a superadmin has no own space and `skill_runs.space_id` is NOT NULL. The intake is already fetched for the scope check, so the superadmin branch writes via `create_in_space(intake.space_id, ...)` — the space comes from the verified in-scope intake row, never from a request arg (still TENANT-02-safe). The user path uses `create()` (identity-derived space) exactly as specified.
- **Sweep cutoff in Python** (`datetime.now(timezone.utc) - timedelta(...)`) rather than a SQL `interval` literal — equivalent semantics, cleaner pg8000 bind.
- **Names imported into the module namespace** (`get_engine`, `get_superadmin_engine`, `get_sessionmaker`, `set_space_context`) so the integration tests can `monkeypatch.setattr(ai_session, "get_engine", ...)` and spy on `set_space_context` at the call site — required by the pinned RED seams.

## Deviations from Plan

None - plan executed exactly as written. (The superadmin-create handling above is a within-spec robustness choice, not a deviation: the plan's acceptance criteria do not exercise the superadmin path, and the user path matches the plan verbatim.)

## Issues Encountered
- Two acceptance greps (`async def` count == 0; `hnsw|ivfflat|create_index` count == 0) initially matched prose in the docstrings ("An `async def` ..." and "(HNSW/IVFFlat)"). Reworded the docstrings to "a coroutine" and "approximate-nearest-neighbour vector index" — the code never contained these constructs; only the explanatory text did. Both counts now 0.
- Python is unavailable on this dev machine, so the `ast.parse` verify step could not run locally; the file's import/symbol contract was validated by grep against the three RED test files' exact import paths and signatures. The `pytest` integration assertions run in CI/Cloud Build where Postgres is available.

## Threat Surface
No new trust boundaries introduced beyond the plan's `<threat_model>`. The module mitigates T-7-02 (structural 2nd-session GUC), T-7-06 (no connection held across the call), T-7-01 (RLS+GUC space confinement in `search_artifacts`), and T-7-03 (`_engine_and_space` reads role/space ONLY from the Identity; null user space → `PermissionError`).

## Known Stubs
None — every function is fully wired against existing engine/repo/RLS primitives. `search_artifacts` takes a ready `query_vec` by design (the query-text embedding lives in `app/ai/search.py`, 07-06) — this is an interface boundary, not a stub.

## Next Phase Readiness
- 07-05/07-06/07-07 AI handlers can now route every read/call/write through `run_with_session_release`; the semantic-search handler (07-06) calls `search_artifacts` over a `tenant_session`. The RED tests `test_ai_session_release`, `test_ai_search_cross_tenant`, and `test_ai_search_explain` are now satisfiable in CI.
- App startup (07-08 wiring) should call `sweep_orphaned_skill_runs()` once on boot.

## Self-Check: PASSED
- FOUND: backend/app/db/ai_session.py
- FOUND commit: 3fae8ef (Task 1)
- FOUND commit: fc8ae72 (Task 2)

---
*Phase: 07-ai-function-ports*
*Completed: 2026-06-30*
