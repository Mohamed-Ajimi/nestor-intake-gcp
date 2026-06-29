---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 01
subsystem: backend-data-access
tags: [tenant-repository, rls, fastapi-dependency, intake, upsert]
requires:
  - "Phase 4 TenantRepository / get_tenant_repo seam (deployed at migration 0006)"
  - "Phase 5 AdminRepo.session audit-in-one-tx idiom"
provides:
  - "TenantRepository.session property (user-path audit target)"
  - "TenantRepository.create() injecting space_id from identity only"
  - "IntakeAnswerRepository (+ list_for_intake, upsert_batch)"
  - "SkillRunRepository (+ list_for_intake, latest_for_intake)"
  - "IntakeTemplateRepository"
  - "get_intake_answer_repo / get_skill_run_repo / get_intake_template_repo dependencies"
affects:
  - "backend/app/api/intake_routes.py (next plan — acquires data access exclusively through these)"
tech-stack:
  added: []
  patterns:
    - "ON CONFLICT DO UPDATE over an existing unique constraint (pg_insert)"
    - "per-entity sync FastAPI dependency mirroring get_tenant_repo"
key-files:
  created: []
  modified:
    - "backend/app/db/repository.py"
    - "backend/app/db/session.py"
decisions:
  - "space_id injected from self._space_id (identity) on create/upsert_batch; never a method kwarg or item-dict field (TENANT-02 / D-03)"
  - "session property placed on the TenantRepository base (not only AdminRepo) so the user path can audit"
  - "upsert_batch targets the existing uq_intake_answers_intake_field constraint — no new migration"
metrics:
  duration: "~12 min"
  completed: "2026-06-29"
  tasks: 3
  files: 2
---

# Phase 6 Plan 01: Per-Entity Tenant Repositories & Dependencies Summary

Extended the deployed Phase 4 tenant data-access seam with three per-entity repository
subclasses (answers, skill-runs, templates) plus two structural base additions — a
`.session` accessor for user-path audit and a `create()` / `upsert_batch()` that inject
`space_id` from the verified Identity only — and three matching sync FastAPI dependencies,
all composition on top of the existing `TenantRepository` with no new tables or migration.

## What Was Built

### Task 1 — `TenantRepository` base extensions (commit 43b7372)
- `session` `@property` returning `self._s`, mirroring `AdminRepo.session` verbatim so a
  user-path status-transition handler can pass the request session to `audit.log` and keep
  the audit row inside the action's ONE transaction (Pitfall 2 / D-02).
- `create(**values)` that sets `values["space_id"] = self._space_id` ONLY inside the
  `self._space_id is not None` (user) branch, then `add` + `flush` + return the row.
  `space_id` is never accepted as a method kwarg (TENANT-02 / T-06-01). Superadmin create
  remains out of scope here and routes through `AdminRepo` (Pitfall 3).
- Imports added: `pg_insert`, `IntakeAnswer`, `IntakeTemplate`, `SkillRun`.

### Task 2 — per-entity subclasses + answers upsert (commit bf0f39e)
- `IntakeAnswerRepository`, `SkillRunRepository`, `IntakeTemplateRepository` — thin
  subclasses setting `model`; all reads remain space-walled by the inherited `_scope`.
- `IntakeAnswerRepository.list_for_intake(intake_id)` and `upsert_batch(intake_id, items)`.
  The upsert issues `pg_insert(...).on_conflict_do_update(constraint="uq_intake_answers_intake_field", ...)`
  over the EXISTING `(intake_id, field_key)` unique constraint, building each row with
  `space_id=self._space_id` and `intake_id` from the path arg; each item contributes only
  `field_key`/`value`/`value_json` — `space_id`/`intake_id` are never read from the item
  dict (D-03 / T-06-03). Empty `items` is a no-op.
- `SkillRunRepository.list_for_intake` (newest-first) and `latest_for_intake`
  (`order_by created_at desc`, `limit 1`, `scalar_one_or_none`), both through `_scope`.

### Task 3 — per-entity dependencies (commit cafbc87)
- `get_intake_answer_repo`, `get_skill_run_repo`, `get_intake_template_repo` in
  `session.py`, each a SYNC `def` generator with a body identical to `get_tenant_repo`:
  engine-by-role, null-user-space `403` default-deny BEFORE any session opens (D-04), ONE
  tx via `with maker.begin()`, `set_space_context` GUC for the user path only (Pitfall 1),
  differing only in the repository class yielded. None is `async def` (Pitfall 5).

## Deviations from Plan

None - plan executed exactly as written.

## Verification

The plan's verification spec is AST/grep-based plus a bash CI guard. This dev machine has
**no Python** (per project memory), so the `python -c "import ast..."` automated checks in
each task could not be executed here; they are recorded below as deferred live-runs. All
acceptance criteria were instead confirmed by construction with the grep gates the plan
itself lists, which ran clean:

- Task 1: `grep "def session"` → property present; `grep "space_id" | grep "def "` → EMPTY
  (no method declares a `space_id` parameter); `create` injects `space_id` only inside the
  `self._space_id is not None` branch.
- Task 2: `grep -c "TenantRepository\["` → `4`; all three new classes present;
  `on_conflict_do_update` targets `uq_intake_answers_intake_field`;
  `grep 'item\["space_id"\]'` → EMPTY; `SkillRunRepository` defines both `list_for_intake`
  and `latest_for_intake`.
- Task 3: three new deps present; no real `async def` (only docstring mentions); five
  `HTTP_403_FORBIDDEN` occurrences (tenant + 3 new + admin gate); each yields its
  respective repository under `with maker.begin()`.
- `bash backend/scripts/ci_no_raw_db_access.sh` → `EXIT=0` (additions stay inside the
  whitelisted `app/db/` seam).
- No new file under `backend/app/db/alembic/versions/` (no migration introduced).

### Deferred live-runs (no Python/Docker on this machine)
- Task 1 AST assertion: `python -c "...assert 'session' in names and 'create' in names..."`
- Task 2 AST assertion: `python -c "...assert all(r in cls for r in ['IntakeAnswerRepository','SkillRunRepository','IntakeTemplateRepository'])..."`
- Task 3 AST assertion: `python -c "...assert all(r in fns for r in [...]); assert not any(AsyncFunctionDef)..."`
- Import-time sanity (`python -c "import app.db.repository, app.db.session"`) to confirm the
  new `from app.db.models.skill_run import SkillRun` import and `pg_insert` resolve.

## Known Stubs

None.

## Self-Check: PASSED
- `backend/app/db/repository.py` — FOUND (modified, committed bf0f39e)
- `backend/app/db/session.py` — FOUND (modified, committed cafbc87)
- `.planning/phases/06-intake-crud-parity-frontend-api-seam/06-01-SUMMARY.md` — FOUND
- Commit 43b7372 — present in git log
- Commit bf0f39e — present in git log
- Commit cafbc87 — present in git log
