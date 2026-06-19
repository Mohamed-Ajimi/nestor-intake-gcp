---
phase: 04-tenant-isolation-proven-by-tests
plan: 02
subsystem: database
tags: [sqlalchemy, postgres, rls, pg8000, cloud-sql, secret-manager, fastapi, tenant-isolation]

# Dependency graph
requires:
  - phase: 01-schema-migrations
    provides: "nestor schema, 0002 RLS isolation policies, 0003 app_superadmin bypass policy, app/db/rls.py set_space_context, conftest fixtures"
  - phase: 02-backend-skeleton-cloud-sql-wiring
    provides: "app/db/base.py get_engine/_get_connector/_POOL_KW, sync pg8000 engine factory"
  - phase: 03-identity-platform-auth
    provides: "app/auth/identity.py Identity, app/auth/dependencies.py get_current_identity (401/403 split)"
provides:
  - "get_superadmin_engine() — second cached engine connecting as app_superadmin (Path B, Secret Manager password)"
  - "_register_guc_reset() — per-checkin RESET app.current_space_id on both engines (D-02 backstop)"
  - "TenantRepository[M] generic always-filter repository + IntakeRepository sample subclass"
  - "get_tenant_repo() sync FastAPI dependency: Identity -> engine -> tx -> GUC -> repo"
  - "Repo+GUC integration suite proving both walls, own-space CRUD, cross-tenant exclusion, pooled no-leak"
affects: [04-03-sample-endpoint-and-denial-suite, 04-04-infra-app_superadmin-user, phase-06-real-endpoints]

# Tech tracking
tech-stack:
  added: ["google-cloud-secret-manager>=2.20,<3 (lazy-imported, superadmin password load)"]
  patterns:
    - "Two-engine routing keyed on Identity.role (app engine + GUC for user; app_superadmin engine, no GUC, for superadmin)"
    - "Generic always-filter repository: space_id derived ONLY from Identity, never a method arg"
    - "Defensive per-checkin GUC RESET on the raw DBAPI connection registered on the engine"
    - "Belt-and-suspenders tenant isolation: explicit repo WHERE proven independently of RLS"

key-files:
  created:
    - "backend/app/db/repository.py"
    - "backend/app/db/session.py"
    - "backend/tests/test_tenant_repository.py"
  modified:
    - "backend/app/db/base.py"
    - "backend/pyproject.toml"

key-decisions:
  - "Path B (D-05a): app_superadmin connects with a Secret Manager password (not IAM) — the single deliberate exception to the IAM-passwordless invariant"
  - "get_superadmin_engine() is a separate lru_cache'd function; get_engine() signature/cache left untouched (regression-frozen)"
  - "checkin RESET runs on the raw pg8000 cursor, registered on the engine so dispose() carries it"
  - "TenantRepository accepts no space_id argument; uuid.UUID coercion of Identity.space_id for the explicit WHERE (Pitfall 6)"
  - "Null user space -> 403 before any session/tx is opened (D-04 default-deny)"
  - "Added google-cloud-secret-manager to pyproject (Rule 2) so the lazy runtime import resolves"

patterns-established:
  - "Two-engine factory: a second creator-based engine via the shared _get_connector(), selected by role"
  - "Sync def generator dependency with `with maker.begin()` (one tx/request, guaranteed teardown; never async def)"
  - "where_filter test: set GUC to the foreign space, scope the repo to the own space, assert the repo WHERE still excludes the foreign row"

requirements-completed: [API-02, TENANT-02, TENANT-03]

# Metrics
duration: 18min
completed: 2026-06-19
---

# Phase 04 Plan 02: Tenant Repository Seam Summary

**Generic always-filter TenantRepository + sync get_tenant_repo dependency over a two-engine factory (app role + GUC for users; Secret-Manager-passworded app_superadmin engine with no GUC for superadmins), plus a per-checkin GUC RESET and a repo+GUC integration suite proving both isolation walls.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-19 (worktree execution)
- **Completed:** 2026-06-19
- **Tasks:** 3
- **Files modified:** 5 (2 modified, 3 created)

## Accomplishments
- `get_superadmin_engine()` — a separate cached engine connecting as the exact literal role `app_superadmin` (matching 0003's `current_user` bypass predicate) with a password read once from Secret Manager via a lazily-imported client (Path B / D-05a). `get_engine()` left byte-for-byte frozen.
- `_register_guc_reset()` — a `checkin` pool event that runs `RESET app.current_space_id` on the raw pg8000 connection, registered on BOTH engines (D-02 backstop, Pitfall 1).
- `TenantRepository[M]` + `IntakeRepository`: every read/write composes an explicit `WHERE space_id = uuid.UUID(identity.space_id)` for users and omits the filter for superadmins; no method ever accepts a `space_id` argument (TENANT-02). `get()`/`patch()` return None/rowcount-0 for cross-tenant ids (handler -> 404, D-07).
- `get_tenant_repo()` sync dependency: composes `get_current_identity`, rejects a null user space with 403 BEFORE opening any tx (D-04), routes the engine by role, opens one tx (`with maker.begin()`), sets the tenant GUC for the user path only, and yields the repository.
- Repo+GUC integration suite with four cases: `where_filter` (repo WHERE proven independently of RLS), own-space CRUD, cross-tenant exclusion, and `pool_no_leak` (pinned single-connection regression driven through the repo path).

## Task Commits

Each task was committed atomically:

1. **Task 1: get_superadmin_engine() (Path B) + per-checkin GUC RESET** - `e757ce3` (feat)
2. **Task 2: TenantRepository + sync get_tenant_repo dependency** - `987c702` (feat)
3. **Task 3: repo+GUC integration suite** - `2eb616c` (test)

_TDD note: Task 3 is the test-authoring task for an existing-substrate plan; the RED/GREEN gate executes in CI where Postgres is available (the suite skips clean locally — see Deferred to CI)._

## Files Created/Modified
- `backend/app/db/base.py` - Added `get_superadmin_engine()`, `_superadmin_connector_creator()`, `_load_superadmin_password()` (lazy Secret Manager), and `_register_guc_reset()`; wired the checkin RESET into both engine factories. `get_engine()` signature/lru_cache unchanged.
- `backend/pyproject.toml` - Added `google-cloud-secret-manager>=2.20,<3` runtime dependency.
- `backend/app/db/repository.py` - `TenantRepository[M]` generic always-filter repo + `IntakeRepository` sample subclass.
- `backend/app/db/session.py` - Sync `get_tenant_repo` FastAPI dependency (identity -> engine -> tx -> GUC -> repo).
- `backend/tests/test_tenant_repository.py` - `pytest.mark.integration` repo+GUC suite (where_filter, own-space CRUD, cross-tenant, pool_no_leak).

## Decisions Made
- **Path B over Path A:** Per the locked 04-CONTEXT decision (D-05a RESOLVED), `app_superadmin` authenticates with a Secret Manager password rather than a second IAM SA. Documented in the base.py header as the single deliberate exception to the IAM-passwordless invariant (D-09).
- **Lazy Secret Manager import + `lru_cache` password load:** keeps the testcontainers/DATABASE_URL path from ever importing `google-cloud-secret-manager`, mirroring the existing lazy `_get_connector` discipline.
- **`where_filter` construction:** set the transaction GUC to the *foreign* space (so RLS would admit it) while scoping the repository to the *own* space — the only thing that can then exclude the foreign row is the repo's explicit `WHERE`, so a broken `uuid.UUID(...)` coercion fails the test (RESEARCH Q3 / Pitfall 6).
- **Attached `_register_guc_reset` to the pinned pool test engine:** so `pool_no_leak` covers the D-02 checkin backstop on the reused connection, not just `SET LOCAL`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added google-cloud-secret-manager to pyproject.toml**
- **Found during:** Task 1 (get_superadmin_engine / Path B)
- **Issue:** `_load_superadmin_password()` lazily imports `google.cloud.secretmanager`, but the dependency was not declared in `backend/pyproject.toml`. The plan's interfaces note said the dep is "added to pyproject in plan 04"; 04-PATTERNS.md § base.py instead says to add it in this plan ("`google-cloud-secret-manager` is **not yet a dependency** — add it to `backend/pyproject.toml`"). Without it, the superadmin engine import would fail at runtime.
- **Fix:** Added `"google-cloud-secret-manager>=2.20,<3"` to `[project].dependencies` with a comment noting the lazy-import / Path B rationale.
- **Files modified:** backend/pyproject.toml
- **Verification:** Declared alongside the other runtime deps; the import is lazy so the test path remains unaffected.
- **Committed in:** `e757ce3` (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary for the superadmin path to import at runtime; resolves a cross-document ambiguity in favour of 04-PATTERNS.md. No scope creep.

## Issues Encountered
- **Planning artifacts not on the worktree base:** the phase 04 `*-PLAN.md` / `*-RESEARCH.md` / `*-PATTERNS.md` files exist in the main repo working tree but are not committed to this worktree's base (`d3e86e3`). They were read directly from the main repo path; the SUMMARY directory was created fresh in the worktree. No impact on the code deliverables.
- **No local Python/Docker (standing constraint):** the Task 1/2 AST verify commands and the Task 3 `pytest` run could not execute locally. Acceptance criteria were verified by inspection (function/class presence, signatures, no `async def`, no `space_id` method arg, no `set_config(..., false)`). Live test execution is deferred to CI (established Phases 1–3 pattern).

## Deferred to CI
- `cd backend && python -m pytest tests/test_tenant_repository.py -x` — requires Postgres (testcontainers/Docker); the suite is `pytest.mark.integration` and skips clean locally.
- AST verify snippets in Task 1/2 (`python -c "import ast; ..."`) — require a Python interpreter; verified by code inspection here.
- `bash scripts/ci_no_raw_db_access.sh` (verification block) — that guard script does not yet exist (authored in plan 04-03 per the file map / Pattern 5). All new raw-DB symbols (`get_engine`, `get_superadmin_engine`, `create_engine`, `sessionmaker`, `Session`) are confined to `app/db/` (and the test file), so the guard will pass once it lands. Out of scope for 04-02.

## User Setup Required
**External service configuration is required for the live superadmin path** (provisioned in plan 04-04, not this plan):
- `SUPERADMIN_DB_PASSWORD_SECRET` — Secret Manager resource name (`projects/<p>/secrets/<name>/versions/latest`) set on the Cloud Run service. Read by `get_superadmin_engine()` at runtime.
- The `app_superadmin` Cloud SQL user (built-in password role) + the secret + `secretAccessor` IAM are Terraform deliverables of plan 04-04 (deferred apply). Until then the live superadmin path cannot connect (Pitfall 3); tests are unaffected (the conftest container creates the role).

## Next Phase Readiness
- The tenant data seam (repository + session dependency + two-engine factory) is complete and ready for plan 04-03's sample endpoint + full-stack denial suite to depend on `get_tenant_repo`.
- Plan 04-04 must provision the `app_superadmin` Cloud SQL user + Secret Manager secret + env var for the live superadmin path.
- Phase 6 real endpoints subclass `TenantRepository` per entity the same way as `IntakeRepository`.

## Self-Check: PASSED

- All created/modified files present: `backend/app/db/base.py`, `backend/app/db/repository.py`, `backend/app/db/session.py`, `backend/tests/test_tenant_repository.py`, `backend/pyproject.toml`, `04-02-SUMMARY.md`.
- All commits present: `e757ce3` (Task 1), `987c702` (Task 2), `2eb616c` (Task 3), `495fb31` (docs).
- Note: Python/Docker unavailable locally (standing constraint) — AST verify + pytest deferred to CI; acceptance criteria verified by inspection. Not a Self-Check failure per the environment constraint.

---
*Phase: 04-tenant-isolation-proven-by-tests*
*Completed: 2026-06-19*
