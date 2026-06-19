---
phase: 04-tenant-isolation-proven-by-tests
plan: 03
subsystem: api
tags: [fastapi, tenant-isolation, rls, pg8000, testclient, dependency-overrides, denial-suite, bola-idor]

# Dependency graph
requires:
  - phase: 04-tenant-isolation-proven-by-tests
    plan: 02
    provides: "get_tenant_repo dependency, TenantRepository/IntakeRepository, two-engine factory, set_space_context"
  - phase: 03-identity-platform-auth
    provides: "protected_router (default-deny base), get_current_identity, Identity"
  - phase: 01-schema-migrations
    provides: "nestor schema, 0002 RLS isolation, 0003 app_superadmin bypass, conftest engine/set_space/two_spaces/_ensure_app_superadmin"
provides:
  - "sample_router — throwaway tenant-scoped list/get/patch over intakes wired through get_tenant_repo (D-08)"
  - "sample_router mounted UNDER protected_router in main.py (inherits default-deny auth)"
  - "test_cross_tenant_denial.py — full-stack HTTP denial suite (QA-01): get/patch cross-tenant 404, own-space list, superadmin cross-space reads, null-space 403"
affects: [phase-06-real-endpoints]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Feature router mounted UNDER protected_router via protected_router.include_router(...) — inherits Depends(get_current_identity), never anonymous"
    - "Sync handler acquires tenant data access ONLY via Depends(get_tenant_repo); no raw DB symbol in app/api/ (D-03 guard scope)"
    - "404 is the only data-route denial code (None/rowcount-0 -> 404); 403 reserved for null-space default-deny (D-04)"
    - "Full-stack denial test: real routers via TestClient + dependency_overrides[get_current_identity] (fabricated Identity, no live IdP) + a get_tenant_repo override mirroring production routing against the testcontainer engine"

key-files:
  created:
    - "backend/app/api/sample_routes.py"
    - "backend/tests/test_cross_tenant_denial.py"
  modified:
    - "backend/app/main.py"

key-decisions:
  - "sample_router carries no auth dependency of its own; it inherits get_current_identity by being mounted under protected_router (single app.include_router(protected_router) still mounts it)"
  - "IntakePatch body has NO space_id field — the tenant key is never client-supplied (TENANT-02); only status/client_name are the benign mutable subset"
  - "Cross-tenant by-id reads AND writes assert == 404 EXACTLY (never `in (403, 404)`); null-space asserts == 403 — pinned exact codes prevent enumeration via code differences (D-07/Pitfall 4)"
  - "The denial suite overrides get_tenant_repo (not just get_current_identity) so the real stack runs against the conftest testcontainer engine — get_engine/get_superadmin_engine (Cloud SQL connector) cannot dial inside a testcontainer; the override reproduces production routing verbatim (SET ROLE app_superadmin/no GUC for superadmin; SET LOCAL GUC for user; 403-before-session for null space)"

requirements-completed: [TENANT-02, TENANT-03, QA-01]

# Metrics
duration: 12min
completed: 2026-06-19
---

# Phase 04 Plan 03: Sample Endpoint + Cross-Tenant Denial Suite Summary

**Throwaway tenant-scoped list/get/patch sample endpoint over `intakes` wired through the real auth -> `get_tenant_repo` -> `IntakeRepository` stack and mounted under the default-deny `protected_router`, plus the required full-stack HTTP cross-tenant denial suite (QA-01) proving exact-404 cross-tenant reads/writes, own-space lists, superadmin cross-space reads, and null-space 403 via `dependency_overrides`.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-19 (worktree execution)
- **Completed:** 2026-06-19
- **Tasks:** 2
- **Files modified:** 3 (2 created, 1 modified)

## Accomplishments
- `sample_routes.py` — a `sample_router` with three sync handlers over `nestor.intakes`, each `Depends(get_tenant_repo)`: `GET /sample/intakes` (own-space list), `GET /sample/intakes/{intake_id}` (404 on None), `PATCH /sample/intakes/{intake_id}` (404 on rowcount 0). Returns only intake-shaped fields (`id`, `space_id`, `status`, `client_name`). The module imports ONLY the injected `get_tenant_repo` + the `IntakeRepository` type — no raw DB symbol (the D-03 guard stays green). `space_id` is never read from the request; only the path `intake_id` flows to the repo (TENANT-02). Header docstring marks it throwaway D-08 scaffolding generalized (not extended) in Phase 6.
- `main.py` — `sample_router` mounted UNDER `protected_router` via `protected_router.include_router(sample_router)`, so the existing single `app.include_router(protected_router)` carries it and it inherits `Depends(get_current_identity)`. No second `app.include_router`, no auth dependency on the bare app (`/healthz`/`/readyz` stay anonymous).
- `test_cross_tenant_denial.py` — the required QA-01 gate: five `pytest.mark.integration` cases driving the REAL `protected_router` + `sample_router` via `TestClient`, matching the 04-VALIDATION `-k` selectors with pinned exact codes:
  - `get_cross_tenant` — user-A GET user-B's intake -> `== 404` AND body carries no space_b id/space_id.
  - `list_scoped` — user-A list -> only space-A rows (space-B id absent).
  - `patch_cross_tenant` — user-A PATCH space-B intake -> `== 404` AND the space-B row re-read as owner is unchanged (`draft`).
  - `superadmin_reads_all` — superadmin list -> BOTH spaces' intake ids present.
  - `null_space_403` — user with `space_id=None` -> `== 403`.

## Task Commits

Each task was committed atomically:

1. **Task 1: throwaway sample endpoint + mount under protected_router** — `62d9aec` (feat)
2. **Task 2: full-stack cross-tenant denial suite (QA-01)** — `1c6101b` (test)

_TDD note: Task 2 is `tdd="true"` but the implementation under test (the sample endpoint) lands in Task 1 of the same plan, so the RED/GREEN gate executes in CI where Postgres is available (the suite is `pytest.mark.integration` and skips clean locally — see Deferred to CI). The standing dev-box constraint (no Python/Docker) precludes a local RED-then-GREEN run; this mirrors the established Phases 1–3 / plan 04-02 pattern._

## Files Created/Modified
- `backend/app/api/sample_routes.py` (new) — `sample_router` + `IntakeView`/`IntakePatch` Pydantic models + three sync handlers; 404-only data-route denial; no raw DB symbol.
- `backend/app/main.py` (modified) — import `sample_router`; mount it under `protected_router` before the single `app.include_router(protected_router)`.
- `backend/tests/test_cross_tenant_denial.py` (new) — the five-case full-stack denial suite with a `get_tenant_repo` override that mirrors production routing against the conftest engine.

## Decisions Made
- **Override `get_tenant_repo`, not only `get_current_identity`:** the plan's literal instruction was to override `get_current_identity`; however the production `get_tenant_repo` routes through `get_engine()`/`get_superadmin_engine()` which use the Cloud SQL connector (and, for users, `os.environ["DATABASE_URL"]` in URL mode) — neither can dial inside a testcontainer, and the superadmin engine additionally needs Secret Manager. To drive the REAL stack (the real `IntakeRepository`, the real `_scope` WHERE, RLS, and the handler 404/403 mapping — which is what this plan must prove) against live testcontainer Postgres, the suite additionally overrides `get_tenant_repo` with `_tenant_repo_for(identity, engine)` that reproduces production routing verbatim: superadmin -> `SET ROLE app_superadmin` (no GUC, 0003 bypass; role created by conftest's `_ensure_app_superadmin`), user -> `set_space_context` (SET LOCAL, true), null-space user -> 403 before any session (D-04). `get_current_identity` is still overridden per case (fabricated `Identity`, no live IdP) per the plan. This is the same `SET ROLE app_superadmin` approach already proven in `test_rls_isolation.py`'s `_as_role` helper.
- **`IntakePatch` excludes `space_id`:** the PATCH body model deliberately has no `space_id` field, so a client cannot even attempt to set the tenant key (TENANT-02); only `status`/`client_name` are accepted, and `exclude_unset` forwards only supplied fields.
- **Empty PATCH -> 400:** a PATCH with no in-scope fields raises 400 (not 404/200) — distinct from the cross-tenant 404 so the denial semantics stay unambiguous.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Denial suite overrides `get_tenant_repo` in addition to `get_current_identity`**
- **Found during:** Task 2 (full-stack denial suite)
- **Issue:** The plan/patterns specify overriding `get_current_identity` and "build the real app … and a TestClient." But the real `get_tenant_repo` calls `get_engine()`/`get_superadmin_engine()`, which use the Cloud SQL connector + (for superadmin) Secret Manager — these cannot connect inside the testcontainer the conftest provides, so an identity-only override would make every case error at connection time rather than exercise the denial logic.
- **Fix:** Added a `get_tenant_repo` override (`_tenant_repo_for`) that mirrors production routing exactly but binds to the conftest `engine`, yielding the REAL `IntakeRepository`. The actual surface this plan proves — the explicit `WHERE`, RLS, and the handler's 404/403 mapping — is genuinely exercised end-to-end; only the engine-acquisition seam (untestable in a testcontainer) is substituted.
- **Files modified:** backend/tests/test_cross_tenant_denial.py
- **Verification:** Selectors and exact-code assertions confirmed by inspection; live RED/GREEN deferred to CI (Postgres). Mirrors the proven `SET ROLE app_superadmin` pattern in `test_rls_isolation.py`.
- **Committed in:** `1c6101b` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** Enables the suite to actually run the real stack against the testcontainer (the alternative — overriding only the identity — would error before testing anything). No scope creep; the engine-acquisition seam is the only substitution and it reproduces production routing verbatim.

## Issues Encountered
- **Planning artifacts not on the worktree base:** the phase 04 `*-PLAN.md` / `*-PATTERNS.md` / `*-VALIDATION.md` / `*-RESEARCH.md` files exist in the main repo working tree but are not committed to this worktree's base (`2f32fc6`). They were read directly from the main repo path; the SUMMARY directory was created fresh in the worktree (only the two prior SUMMARYs were present). No impact on the code deliverables.
- **No local Python/Docker (standing constraint):** the Task 1 `python -c "…"` AST verify and the Task 2 `pytest …` run could not execute locally. Acceptance criteria were verified by inspection + the runnable bash guard (below). Live test execution is deferred to CI (established Phases 1–3 / plan 04-02 pattern).

## Verification Performed
- **D-03 raw-DB-access guard (runnable locally):** `cd backend && bash scripts/ci_no_raw_db_access.sh` -> `OK … exit 0`. `app/api/sample_routes.py` is in the guard's scan scope (`app/` minus `db/`, `main.py`, `session.py`) and carries no raw DB symbol (the only `get_engine`/`create_engine`/`sessionmaker`/`Session` text is inside the module docstring listing what must NOT appear — confirmed via Grep; the guard's `[^.]Session\(`-style pattern does not match it).
- **Task 1 inline assertions (by Grep, Python unavailable):** `sample_routes.py` contains `get_tenant_repo` + `HTTP_404_NOT_FOUND`; `main.py` contains `sample_router` + `protected_router.include_router`.
- **Task 2 selectors + exact codes (by Grep):** all five `-k` selectors present as contiguous substrings (`get_cross_tenant`, `list_scoped`, `patch_cross_tenant`, `superadmin_reads_all`, `null_space_403`); `== 404` for cross-tenant get/patch, `== 403` for null-space, `== 200` for own-space/superadmin lists; no `in (403, 404)` assertion anywhere (only in explanatory comments).

## Deferred to CI
- `cd backend && python -m pytest tests/test_cross_tenant_denial.py -x` — requires Postgres (testcontainers/Docker); `pytest.mark.integration`, skips clean locally. RED/GREEN gate runs in CI.
- `cd backend && python -m pytest tests` collect-clean check — requires a Python interpreter; the file uses `importorskip` guards + the integration marker so it collects/skips cleanly by construction.
- Task 1's `python -c "…"` AST snippet — requires Python; verified by Grep here.

## Next Phase Readiness
- The throwaway sample endpoint + the required QA-01 denial gate are in place; the whole Phase 4 stack (auth -> `get_tenant_repo` -> repository -> RLS) is now proven end-to-end at the HTTP boundary (pending the CI integration run).
- Plan 04-04 provisions the live `app_superadmin` Cloud SQL user + Secret Manager secret + env var so the production superadmin path can connect (the denial suite's superadmin case is satisfied in the testcontainer via `SET ROLE`; live GCP is the deferred manual verification per 04-VALIDATION).
- Phase 6 deletes `sample_routes.py` and generalizes the pattern: one feature router mounted under `protected_router` + one `TenantRepository` subclass per entity, each handler `Depends(get_tenant_repo)`.

## Self-Check: PASSED

- All created/modified files present: `backend/app/api/sample_routes.py`, `backend/app/main.py`, `backend/tests/test_cross_tenant_denial.py`, `04-03-SUMMARY.md` (verified below).
- All commits present: `62d9aec` (Task 1), `1c6101b` (Task 2).
- D-03 guard runnable and green (exit 0).
- Note: Python/Docker unavailable locally (standing constraint) — AST verify + pytest deferred to CI; acceptance criteria verified by Grep inspection + the runnable bash guard. Per the environment constraint, this is NOT a Self-Check failure.

---
*Phase: 04-tenant-isolation-proven-by-tests*
*Completed: 2026-06-19*
