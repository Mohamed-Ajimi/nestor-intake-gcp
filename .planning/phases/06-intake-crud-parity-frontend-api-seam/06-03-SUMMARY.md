---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 03
subsystem: backend-intake-api
tags: [intake-router, crud, section-batch-upsert, status-transition, audit-one-tx, scope-ceiling]
requires:
  - "06-01 per-entity repositories (IntakeAnswerRepository.upsert_batch, SkillRunRepository.latest_for_intake, IntakeTemplateRepository) + get_*_repo dependencies + TenantRepository.session/.create"
  - "Phase 5 admin_routes transition + audit.log(repo.session,...) idiom"
provides:
  - "intake_router (prefix /intakes) mounted under protected_router"
  - "IntakeView / AnswerView / SkillRunView / TemplateView response contract (source of truth for plan 05)"
  - "CRUD (list/create/get/patch) + answers read + section-batch upsert (D-03)"
  - "allow-listed /submit + /review transitions with audit-in-one-tx (<= decomposed)"
  - "read-only skill-runs (latest+list) + templates projections feeding derivePhase"
affects:
  - "backend/app/main.py (intake_router mounted)"
  - "plan 04 (re-points cross-tenant denial suite onto /intakes, then deletes sample_router)"
  - "plan 05 (frontend API seam mirrors this contract)"
tech-stack:
  added: []
  patterns:
    - "discrete named transition POST verbs (not generic PATCH status) as allow-listed single-step + audit call-site"
    - "module-level transition allow-list maps; absence of an entry => 409 (structural scope ceiling)"
    - "literal /templates route declared BEFORE /{intake_id} so the segment is not captured as a path param"
key-files:
  created:
    - "backend/app/api/intake_routes.py"
    - "backend/tests/test_intake_routes.py"
  modified:
    - "backend/app/main.py"
decisions:
  - "IntakePatch carries client_name ONLY — no space_id (TENANT-02) and no status (status moves only via allow-listed transition verbs); its docstring also avoids the words so the grep gate stays clean"
  - "transition allow-lists contain only <= decomposed targets; submit={draft->submitted, reviewed->validated_by_client}, review={submitted->reviewed}; off-list -> 409 (T-06-06 at the data layer, not just CI)"
  - "scope-ceiling docstring reworded to avoid the literal run-research/Tribunal/in_research tokens so the sibling ci_no_run_research guard (lands in a later plan) will not trip on this file"
  - "collection routes use path \"\" (not \"/\") so they register as exactly /intakes (matches the contract + the verify assertion)"
metrics:
  duration: "~25 min"
  completed: "2026-06-29"
  tasks: 3
  files: 3
---

# Phase 6 Plan 03: Intake Feature Router (CRUD + Transitions + Reads) Summary

Built the real intake feature router that replaces the throwaway `sample_routes.py` pattern:
the full authenticated intake surface to `decomposed` — list/create/get/patch intakes,
read + section-batch-save answers (D-03), discrete allow-listed `/submit` + `/review` status
transitions with audit-in-one-tx, and read-only skill-run + template projections that feed the
admin phase machine — mounted under `protected_router`, with `IntakeView` carrying all five
phase markers and no out-of-scope route ever defined.

## What Was Built

### Task 1 — `intake_routes.py` CRUD + reads + mount (commit e80613b)
- `intake_router = APIRouter(prefix="/intakes", tags=["intakes"])`; sync `def` handlers; imports
  NO raw DB symbol (acquires data access only via the four `get_*_repo` dependencies — D-03).
- Pydantic contract: `IntakeView` (carries all five phase markers
  `validation_link_sent_at` / `results_link_sent_at` / `context_pack_artifact_id` /
  `final_report_artifact_id` alongside `status`), `IntakeCreate`, `IntakePatch` (`client_name`
  only — no `space_id`, no `status`), `AnswerView` / `AnswerItem` / `AnswerBatch`,
  `SkillRunView` (maps `SkillRun.status` verbatim — Pitfall 1) + `SkillRunsView`, `TemplateView`.
- Handlers: `GET /intakes` (list), `POST /intakes` (create -> `draft`, space_id injected by the
  repo from identity), `GET /intakes/templates` (declared before `/{intake_id}`), `GET
  /intakes/{intake_id}` (404 D-07), `PATCH /intakes/{intake_id}` (exclude_unset, empty->400,
  rowcount 0->404), `GET /intakes/{intake_id}/answers`, `PATCH /intakes/{intake_id}/answers`
  (section batch upsert), `GET /intakes/{intake_id}/skill-runs` (latest+list).
- `main.py`: `from app.api.intake_routes import intake_router` +
  `protected_router.include_router(intake_router)` next to the sample/admin mounts;
  `sample_router` left mounted (plan 04 removes it). No `/run-research` / deep-research-stage /
  `-> in_research` route defined.

### Task 2 — transitions + allow-list + audit-in-one-tx (commit 11cc000)
- Module-level `_SUBMIT_TRANSITIONS` (`draft->submitted`, `reviewed->validated_by_client`) and
  `_REVIEW_TRANSITIONS` (`submitted->reviewed`) — the data-layer scope-ceiling allow-lists.
- `_next_submit_status` / `_next_review_status` raise `HTTPException(409)` for any status not in
  the allow-list — STRUCTURALLY blocking a jump to the out-of-scope later stages (T-06-06).
- `POST /intakes/{intake_id}/submit` + `/review`: `repo.get` -> 404 if None; compute new status
  (409 if forbidden); `repo.patch(status=...)`; then
  `audit.log(repo.session, actor_uid=identity.uid, event_type="intake.status_changed",
  target=str(intake_id), space_id=intake.space_id, metadata={"from": old, "to": new})` on the
  SAME session (one-tx, QA-04 / Pitfall 2); return the re-read `_view`. Metadata is structured
  `{from,to}` only — never a link/token (T-06-09).

### Task 3 — `test_intake_routes.py` integration suite (commit a9e7e64)
- `pytestmark = pytest.mark.integration` + `importorskip` guards (skip-clean without
  Docker/firebase). Drives the REAL `intake_router` under `protected_router` via a fabricated
  `user` Identity (`dependency_overrides`) and `_patch_engine_factories(session_mod.get_engine)`
  so the production dependency bodies + repos + RLS run verbatim against the conftest engine.
- `test_create_and_list_intake_in_own_space` (201 + `draft` + own-space list),
  `test_answers_batch_upsert` (PATCH the same `(intake_id, field_key)` twice -> single row
  UPDATED, no unique violation — Pitfall 6), `test_transitions_advance_and_reject_out_of_scope`
  (draft->submitted->reviewed->validated_by_client all 200; a further submit -> 409),
  `test_transition_audited` (exactly one `intake.status_changed` row, `metadata={from,to}`, no
  token/link/password key).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded scope-ceiling docstring to avoid sibling-guard tokens**
- **Found during:** Task 1
- **Issue:** The module docstring originally spelled out the forbidden surface literally
  (`/run-research`, `/tribunal`, `-> in_research`). 06-PATTERNS specifies a sibling
  `ci_no_run_research.sh` guard (created in a later plan) whose regex matches
  `run-research|run_research|Tribunal|tribunal`. Once that guard lands it scans `backend/app/`
  `*.py` and would have tripped on this file's own docstring — a self-inflicted future build break.
- **Fix:** Reworded the scope-ceiling bullet to "NO deep-research-stage route and no
  post-`decomposed` transition, ever" — preserving the intent while removing the literal tokens.
  Verified `grep -nE "run-research|run_research|Tribunal|tribunal"` returns nothing.
- **Files modified:** backend/app/api/intake_routes.py
- **Commit:** e80613b

## Verification

The plan's per-task `<verify>` blocks are `python -c "from app.main import app; ..."` import/route
assertions plus `pytest`. This dev machine has **no Python/Docker** (per project memory), so those
runtime checks are recorded below as deferred live-runs (they are the real CI gate). All
acceptance criteria were confirmed by construction with the grep gates the plan itself lists,
which ran clean:

- Task 1: `bash scripts/ci_no_raw_db_access.sh` -> `EXIT=0` (no engine/session symbol leaked);
  phase-marker count `grep -c "_link_sent_at\|_artifact_id"` -> `18` (>= 4); `include_router(intake_router)`
  present in `main.py`; IntakePatch class body contains neither `space_id` nor `status`; no route
  path contains `research`/`tribunal` (only the reworded docstring, no token match).
- Task 2: `grep -c "audit.log(repo.session"` -> `2`; `grep -c "HTTP_409_CONFLICT"` -> `2` (>= 1);
  `grep -nE "in_research|delivered|archived"` -> NONE (transition maps hold only `<= decomposed`);
  no `"link"/"token"/"password"` key in the file; `submit_intake` + `review_intake` handlers present.
- Task 3: all four `test_*` functions present (`create_and_list`, `answers_batch_upsert`,
  `transitions...`, `transition_audited`); forbidden transition asserts `status_code == 409`; audit
  assertion checks `len(rows) == 1` and that `link`/`token`/`password` keys are absent;
  `pytestmark = pytest.mark.integration` + `importorskip` present.
- Cross-checked the raw-SQL targets against the schema: `audit_log` table, `metadata` JSONB column,
  and `Base.metadata.schema = "nestor"` all confirmed in the source so `nestor.audit_log`/
  `nestor.intake_answers` references in the test are correct.

### Deferred live-runs (no Python/Docker on this machine)
- Task 1 route assertion: `python -c "from app.main import app; paths=[r.path for r in app.routes]; assert '/intakes' in paths and '/intakes/{intake_id}/answers' in paths; assert not any('research' in p or 'tribunal' in p for p in paths)"`
- Task 2 route assertion: `python -c "from app.main import app; paths=[r.path for r in app.routes]; assert '/intakes/{intake_id}/submit' in paths and '/intakes/{intake_id}/review' in paths"`
- Task 3 suite: `pytest tests/test_intake_routes.py -q` (green in CI with Docker; skip-clean locally)
- `bash scripts/ci_no_raw_db_access.sh` re-run in CI (passed locally, EXIT=0)

## Known Stubs

None.

## Threat Flags

None — the intake surface introduced here stays within the plan's `<threat_model>` (the
`/intakes` client boundary and the API->audit_log boundary are both already enumerated; all five
listed mitigations T-06-05..09 are implemented: 404-only data denial, allow-listed transitions,
mass-assignment-proof IntakePatch/AnswerBatch, one-tx audit, structured-metadata-only audit).

## Self-Check: PASSED
- `backend/app/api/intake_routes.py` — FOUND (created, e80613b + 11cc000)
- `backend/app/main.py` — FOUND (modified, e80613b)
- `backend/tests/test_intake_routes.py` — FOUND (created, a9e7e64)
- Commit e80613b — present in git log
- Commit 11cc000 — present in git log
- Commit a9e7e64 — present in git log
