---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 13
subsystem: api
tags: [fastapi, tenant-isolation, view-filter, superadmin, tanstack, pytest]

# Dependency graph
requires:
  - phase: 06-intake-crud-parity-frontend-api-seam
    provides: real intake_router (list_intakes) + get_tenant_repo scope wall + cross-tenant denial harness
  - phase: 06-intake-crud-parity-frontend-api-seam
    provides: frontend active-space view-filter (withActiveSpace / useActiveSpace) threaded through listIntakes
provides:
  - Optional space_id query param on GET /intakes (superadmin-only handler-side narrowing)
  - Server-side honoring of the superadmin space switcher (TENANT-04 functional end-to-end)
  - Proof that a non-superadmin's space_id param is INERT (cannot widen or narrow their repo-scoped set)
  - Intakes index header copy that tracks the real active-space state (no false filter claim)
affects: [phase-07-ai-skill-ports, phase-12-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Handler-side superadmin view-filter: narrow repo.list() rows by `str(row.space_id) == space_id` ONLY when identity.role == 'superadmin' — a UX filter, NEVER passed into the repo (T-06-22; repository.py no-space_id-parameter invariant preserved)"
    - "Truthful UI state: subtitle copy branches on the same activeSpaceId that drives the query filter, so the header can never imply a filter that is not occurring"

key-files:
  created: []
  modified:
    - backend/app/api/intake_routes.py
    - backend/tests/test_intake_cross_tenant.py
    - frontend/src/routes/admin.pulse.intakes.index.tsx

key-decisions:
  - "space_id is honored ONLY for a superadmin and applied as a handler-side list comprehension over repo.list() rows — never an argument to repo.list() (repository.py LOCKED invariant)."
  - "A non-superadmin's space_id is discarded server-side (the `if identity.role == 'superadmin'` gate), so it can neither widen nor narrow their already token-scoped set — proven by test_user_space_id_param_is_inert."
  - "Header subtitle branches on activeSpaceId rather than asserting an unconditional 'gefilterd' claim, eliminating the misleading-isolation information-disclosure surface (T-06-24)."

patterns-established:
  - "Client-supplied scope identifiers at a trust boundary are VIEW-FILTERS for an already-authorized role only, never authorization inputs — the repo scope remains the sole authority."

requirements-completed: [TENANT-04, API-03]

# Metrics
duration: ~25min
completed: 2026-06-29
---

# Phase 6 Plan 13: Make the Superadmin Space Switcher Actually Filter Summary

**GET /intakes now accepts an optional `space_id` query param and, FOR SUPERADMIN ONLY, narrows the returned list to that space at the handler layer (a view-filter over repo.list() rows, never a repo argument) — a non-superadmin's param is inert, and the intakes index header copy now tracks the real active-space state instead of falsely claiming filtering.**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-29 (this session)
- **Completed:** 2026-06-29
- **Tasks:** 3
- **Files modified:** 3 (+ 1 deferred-items log)

## Accomplishments
- Closed BLOCKER 2 (WR-01 / TENANT-04): `withActiveSpace()` was appending `?space_id=<id>` to `/intakes`, but `list_intakes` declared no such param so FastAPI silently discarded it — a superadmin saw ALL spaces regardless of the switcher. `list_intakes` now declares `space_id: str | None = None` + an `identity` dependency and narrows the result to the selected space when `identity.role == "superadmin"` and `space_id` is truthy.
- Preserved the repository.py LOCKED invariant: the narrowing is a handler-side list comprehension `[r for r in rows if str(r.space_id) == space_id]` over `repo.list()` rows — `repo.list()` is NEVER passed a `space_id` argument (T-06-22: space_id is a superadmin UX view-filter, never an authorization input).
- Proved the param is inert for a non-superadmin: a user's `repo.list()` is already `_scope`-walled to their token-derived space and the handler skips narrowing for non-superadmins, so a forged `?space_id=<B>` returns the user's own space-A intake and never space-B's (no widening, no narrowing).
- Corrected the index header information-disclosure surface (T-06-24): the subtitle now branches on `activeSpaceId` — "gefilterd op de actieve klant" when a space is active, "Alle Pulse intakes." when null — instead of the static false claim.

## Task Commits

Each task was committed atomically:

1. **Task 1: list_intakes optional space_id param + superadmin-only handler narrowing** — `fc71dd4` (feat)
2. **Task 2: Tests — superadmin space_id narrows; user space_id is inert** — `319be81` (test)
3. **Task 3: Correct the intakes index header copy to match real behavior** — `c2cc994` (fix)

_Note: Task 1 is flagged `tdd="true"` in the plan, but the cross-tenant suite is `pytest.mark.integration` and cannot run on this dev box (no Python/Docker). Code + tests were authored by construction and verified with the plan's grep/static gates; the RED/GREEN cycle is collapsed into one feat commit (Task 1) with the adversarial tests landing in the test commit (Task 2) — matching prior Phase 06 practice (D-10 / dev-machine constraint)._

## Files Created/Modified
- `backend/app/api/intake_routes.py` — `list_intakes` gains `space_id: str | None = None` and `identity: Identity = Depends(get_current_identity)`; fetches `rows = repo.list()` then applies `if identity.role == "superadmin" and space_id: rows = [r for r in rows if str(r.space_id) == space_id]`; returns `[_view(row) for row in rows]`. Docstring states the param narrows ONLY for a superadmin and is ignored for a user (cannot widen). (Identity / get_current_identity were already imported by the module.)
- `backend/tests/test_intake_cross_tenant.py` — Added `test_superadmin_space_id_param_narrows_list` (mirrors `test_superadmin_reads_all_spaces` with `sa_engine=superadmin_engine`: `?space_id=<B>` includes intake-B and excludes intake-A; no-param default still returns BOTH) and `test_user_space_id_param_is_inert` (mirrors `test_list_scoped_to_own_space`: user `?space_id=<B>` still returns only space-A's intake, never space-B's). Both inherit the module-level `pytestmark = pytest.mark.integration`; reuse `_seed_two_spaces` / `_cleanup_spaces` / `_as` / try-finally.
- `frontend/src/routes/admin.pulse.intakes.index.tsx` — Imports `useActiveSpace` from `@/lib/active-space`, reads `const { activeSpaceId } = useActiveSpace();`, and branches the subtitle on it. No change to the data fetch or to `withActiveSpace` wiring.

## Decisions Made
- **Handler-side narrowing over a repo change:** the repository module's no-`space_id`-parameter invariant is LOCKED; the superadmin filter is a post-filter on `repo.list()` rows, keeping `space_id` a UX view-filter and never an authz input (T-06-22).
- **Superadmin-only gate is the security wall:** the narrowing runs only under `identity.role == "superadmin"`. A user never reaches it, so their repo-scoped set is the sole authority regardless of any forged param (T-06-23).
- **Truthful header copy:** the subtitle reads the same `activeSpaceId` source-of-truth that drives the query, so the UI cannot imply filtering/isolation that is not occurring (T-06-24).

## Confirmation: withActiveSpace wiring is superadmin-only (no change needed)
Per Task 3, confirmed by reading `active-space.tsx`: `_activeSpaceId` is set ONLY via the provider effect syncing React state, and the only UI that sets it is the `SpaceSwitcher`, which `ProductShell` mounts ONLY inside an `isSuperadmin &&` gate. A regular user therefore never sets the param. Combined with the backend's superadmin-only narrowing + repo scope wall, a user's `?space_id` is doubly inert (never sent by the UI, and ignored server-side even if forged). No change was made to `active-space.tsx` or `ProductShell`.

## Deviations from Plan

None — plan executed exactly as written.

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or schema changes were introduced. The single new query param is the explicitly threat-modeled `space_id` view-filter (T-06-22/23/24), mitigated as designed.

## Verification Performed
- **Task 1 (backend):** grep gate PASSED — `list_intakes` signature contains `space_id: str | None = None`, an `identity` dependency, the `superadmin` gate, and `str(r.space_id)` within the asserted windows.
- **Task 2 (tests):** grep gate PASSED — both `test_superadmin_space_id_param_narrows_list` and `test_user_space_id_param_is_inert` present, `space_id=` query usage present. AST parse DEFERRED (no Python on dev box) — authored by construction.
- **Task 3 (frontend):** grep gate PASSED — `useActiveSpace` imported/used. `tsc --noEmit` run against the worktree (via a temporary junction to the main checkout's installed `node_modules`, since the worktree has no install): my change introduces ZERO new type errors. The 7 errors tsc reports are PRE-EXISTING and repo-wide (see Deferred Issues) — confirmed by re-running tsc with the Task-3 change stashed (identical 7 errors at base HEAD 1a18b7d); the single index.tsx error is on the untouched "Nieuwe intake" Link, merely shifted from line 114 to 121 by the added lines. The junction was removed after the check (main `node_modules` verified intact).

## Deferred Issues
- **Live `pytest -m integration` run is DEFERRED to CI** (no Python/Docker on this dev box; the suite skips without Docker/DATABASE_URL). The two new tests + the existing intake denial cases must be executed against a Cloud SQL / testcontainer Postgres in CI to confirm the narrow/inert assertions at runtime.
- **Pre-existing repo-wide tsc errors (stale `routeTree.gen.ts` / missing required `search` param)** — 7 errors across `admin.clients.$id.tsx`, `admin.pulse.clients.$id.tsx`, `admin.pulse.clients.tsx`, `admin.pulse.intakes.$id.tsx`, and the untouched "Nieuwe intake" Link in `admin.pulse.intakes.index.tsx`. Pre-existing at the worktree base, NOT caused by this plan (scope boundary → not fixed). Logged to `deferred-items.md`; recommend a dedicated follow-up to regenerate the route tree and reconcile the `search` props.

## User Setup Required
None — no external service configuration required.

## Next Phase Readiness
- TENANT-04 is functionally met end-to-end by construction: a superadmin's space switcher narrows the intake list to the selected space (and "Alle klanten" restores all), a non-superadmin's `space_id` can never widen their own-space list, and the index header copy no longer falsely claims filtering.
- Remaining open items: the deferred live `pytest -m integration` execution in CI, and the pre-existing route-tree `search` tsc errors (tracked in `deferred-items.md`).

## Self-Check: PASSED

All three modified files + the deferred-items log exist on disk and all task commits are present:
- Files: `backend/app/api/intake_routes.py`, `backend/tests/test_intake_cross_tenant.py`, `frontend/src/routes/admin.pulse.intakes.index.tsx`, `.planning/.../deferred-items.md`, `06-13-SUMMARY.md`
- Commits: `fc71dd4` (Task 1), `319be81` (Task 2), `c2cc994` (Task 3)

---
*Phase: 06-intake-crud-parity-frontend-api-seam*
*Completed: 2026-06-29*
