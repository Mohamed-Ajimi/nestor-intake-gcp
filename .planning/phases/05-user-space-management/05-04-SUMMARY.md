---
phase: 05-user-space-management
plan: 04
subsystem: admin-api
tags: [admin-api, superadmin, get-admin-session, audit, user-01, user-03, auth-04, qa-04]
requires:
  - "app/db/session.py get_tenant_repo (engine/tx wiring — mirrored for the admin seam)"
  - "app/db/base.py get_superadmin_engine (app_superadmin → 0003 bypass policy — reused)"
  - "app/auth/admin_users.py (invite/deactivate/reactivate/reset-link Admin-SDK wrapper — consumed)"
  - "app/db/audit.py audit.log (one-tx audit write helper — called per mutation)"
  - "app/db/models/audit.py + 0006 migration (audit_log root table + status columns — written to)"
provides:
  - "get_admin_session DI seam (superadmin-only 403 gate + superadmin engine, no GUC, yields AdminRepo)"
  - "AdminRepo root/cross-space accessors (users, spaces, templates — no delete)"
  - "admin_router: 12 superadmin endpoints under /admin, mounted on protected_router"
affects:
  - "app/main.py (admin_router mounted under protected_router)"
tech-stack:
  added: []
  patterns:
    - "Dependency-level default-deny: superadmin 403 fires in get_admin_session BEFORE any session/tx opens"
    - "Superadmin engine + NO app.current_space_id GUC: bypass is current_user-based, reaches root + cross-space tables"
    - "One transaction per request via with maker.begin() (D-02): mutation + audit.log share the same tx"
    - "No-DELETE admin surface: deactivate/reactivate status flips instead of row deletion (USER-02/03)"
key-files:
  created:
    - "backend/app/db/admin_repo.py"
    - "backend/app/api/admin_routes.py"
  modified:
    - "backend/app/db/session.py"
    - "backend/app/main.py"
decisions:
  - "get_admin_session yields AdminRepo (not TenantRepository): unfiltered root + cross-space accessors with no _scope/space_id filter and no delete method."
  - "Last-superadmin guard: count_active_superadmins() gates user deactivation/role changes so the system can never be locked out (409)."
  - "All admin mutations are POST/PATCH status flips — zero @admin_router.delete routes (no-DELETE requirement, verified)."
  - "audit.log called once per mutation inside the same request tx (9 call sites: 3 user + 4 space + 2 template)."
metrics:
  duration: "~7 min (executor); SUMMARY reconstructed by orchestrator after socket-error death"
  completed: "2026-06-22"
  tasks: 3
  files: 4
---

# Phase 05 Plan 04: Superadmin Admin API Summary

One-liner: A `get_admin_session` DI seam (superadmin-only 403 default-deny gate, superadmin engine with no tenant GUC, yields an `AdminRepo`), the `AdminRepo` root/cross-space data-access layer (no delete), and a 12-endpoint `admin_router` under `/admin` — invite/list/deactivate/reactivate users, space create/update/deactivate/reactivate, and template list/clone/edit — each mutation writing an `audit_log` row inside the request transaction, all mounted under `protected_router` in `main.py`.

> **Provenance note:** The executor agent for this plan died with an API socket-close error (infrastructure failure) *after* committing all three task commits with a clean working tree, but *before* writing this SUMMARY.md. The orchestrator verified the three commits (`00ada0c`, `a131f68`, `2ce5c66`), the full diff (805 insertions across 4 files, zero deletions), the route surface, the audit instrumentation, and the no-DELETE invariant directly against the merged code, then authored this SUMMARY by construction. No code was changed during reconstruction.

## What Was Built

### Task 1 — `get_admin_session` seam + `AdminRepo` accessors (commit `00ada0c`)
- `backend/app/db/session.py`: `get_admin_session(identity = Depends(get_current_identity))` — the admin API's single DI seam. Three deliberate differences from `get_tenant_repo`: (1) **superadmin-only 403 gate fires in the dependency BEFORE any session/tx opens** (default-deny, EoP wall — a `user` never reaches a handler or a DB connection); (2) opens the tx on `get_superadmin_engine` (`app_superadmin` → 0003 bypass policy) and sets **NO** `app.current_space_id` GUC, so the path reaches root + cross-space tables; (3) yields an `AdminRepo`. One tx per request via `with maker.begin()` (D-02).
- `backend/app/db/admin_repo.py` (new): `AdminRepo` with unfiltered accessors — users (`list_users`, `get_membership`, `find_active_membership`, `create_membership`, `set_membership_status`, `count_active_superadmins`), spaces (`list_spaces`, `get_space`, `create_space`, `update_space`, `set_space_status`), templates (`list_templates`, `get_template`, `clone_template`, `update_template`). **No delete method exists.**

### Task 2 — Admin user endpoints + router mount (commit `a131f68`)
- `backend/app/api/admin_routes.py` (new): `admin_router = APIRouter(prefix="/admin", tags=["admin"])`. User surface: `GET /admin/users`, `POST /admin/users` (invite → returns the set-password link only, never the password, D-02), `POST /admin/users/{membership_id}/deactivate`, `POST /admin/users/{membership_id}/reactivate`. Invite composes `admin_users.create_invited_user` + `generate_set_password_link`; deactivate composes `admin_users.deactivate_user`; the last-superadmin guard (`count_active_superadmins`) returns 409 to prevent lockout. Each mutation calls `audit.log(...)` in-tx.
- `backend/app/main.py`: `protected_router.include_router(admin_router)` — mounted exactly like `sample_router` so it inherits `get_current_identity`; the per-route `get_admin_session` adds the superadmin-only 403 gate.

### Task 3 — Space CRUD + template clone/edit (commit `2ce5c66`)
- `backend/app/api/admin_routes.py` (extended): spaces — `GET /admin/spaces`, `POST /admin/spaces`, `PATCH /admin/spaces/{space_id}`, `POST /admin/spaces/{space_id}/deactivate`, `POST /admin/spaces/{space_id}/reactivate`; templates — `GET /admin/spaces/{space_id}/templates`, `POST /admin/spaces/{space_id}/templates` (clone), `PATCH /admin/spaces/{space_id}/templates/{template_id}` (edit). USER-03. Status flips + duplicate/slug/state-conflict 409 guards; `audit.log(...)` per mutation.

## Deviations from Plan

None — all three tasks executed as written. The only anomaly is process-level, not content-level: the executor died (socket error) before the SUMMARY commit; the orchestrator reconstructed this file after verifying the committed work (see provenance note).

## Authentication Gates

None requiring human action during execution. The superadmin-only 403 enforcement (T-5-13) is implemented in `get_admin_session` and is exercised by the parametrized user-role-403 test across all routes in the plan-01 RED suite.

## Verification

Static / by-construction (live pytest DEFERRED — this dev box has no Python/pytest/Docker runtime, a confirmed project constraint; suites run in CI/GCP, and the plan-01 RED suite `tests/test_admin_routes.py` is the contract these endpoints satisfy):

- `backend/scripts/ci_no_raw_db_access.sh` → exit 0 (no raw DB access outside `app/db/`) post-merge.
- 12 route decorators present under `admin_router` (4 user + 5 space + 3 template); `admin_router` carries `prefix="/admin"`.
- **0 `@admin_router.delete` routes** — the no-DELETE invariant holds (USER-02/03; verified by grep).
- **9 `audit.log(` call sites** in `admin_routes.py` — one per mutation (3 user, 4 space, 2 template).
- `get_admin_session` present in `session.py` and uses `get_superadmin_engine` (5 references) with no `app.current_space_id` GUC set.
- `app/main.py` contains `protected_router.include_router(admin_router)` and imports `admin_router`.
- `AdminRepo` exposes `count_active_superadmins` (last-superadmin lockout guard) and no delete accessor.
- DEFERRED (CI/GCP): live `alembic upgrade` + endpoint integration tests, cross-tenant denial, and the audit-row round-trip assertions.

## Known Stubs

None. All handlers are fully composed against the Wave 1 interfaces (`admin_users`, `audit.log`, `AdminRepo`, the 0006 schema). No placeholder returns.

## Self-Check: PASSED

- FOUND: backend/app/db/admin_repo.py
- FOUND: backend/app/api/admin_routes.py
- FOUND: backend/app/db/session.py (modified — get_admin_session)
- FOUND: backend/app/main.py (modified — admin_router mount)
- FOUND commit 00ada0c (Task 1)
- FOUND commit a131f68 (Task 2)
- FOUND commit 2ce5c66 (Task 3)
