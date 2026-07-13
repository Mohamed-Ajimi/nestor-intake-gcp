---
phase: 07-ai-function-ports
plan: 09
subsystem: api
tags: [fastapi, sqlalchemy, context-pack, research-artifacts, skill-runs, tenant-isolation, bola]

# Dependency graph
requires:
  - phase: 07-ai-function-ports
    provides: "generate-context-pack write path (research_artifacts row, source=context-pack-generator) + skill_runs.skill column"
  - phase: 04 (tenant repository seam)
    provides: "TenantRepository._scope + get_*_repo DI injector pattern (space-scoped, default-deny, one-tx)"
provides:
  - "GET /intakes/{intake_id}/context-pack read endpoint (latest + history, space-scoped, existence-hidden)"
  - "ContextPackView projection (id/text_content/created_at/notes only)"
  - "ResearchArtifactRepository with latest_context_pack_for_intake + list_context_packs_for_intake"
  - "get_research_artifact_repo DI injector (mirrors get_skill_run_repo)"
  - "skill discriminator projected on SkillRunView"
affects: [07-10 (frontend consumes the context-pack read + skill field)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Existence-hidden empty read: a cross-tenant/missing intake reads {latest: null, history: []}, indistinguishable from an in-scope intake with no pack (never 200-with-foreign-data, never distinguishable 403)"
    - "Source-literal filter (source == 'context-pack-generator') pins a read to exactly the artifact type the write path stamps"

key-files:
  created: []
  modified:
    - backend/app/api/intake_routes.py
    - backend/app/db/repository.py
    - backend/app/db/session.py
    - backend/tests/test_intake_routes.py

key-decisions:
  - "Context-pack read is a scoped-empty 200 (not 404) when no pack exists — absence of a pack is not absence of the intake, and this makes cross-tenant existence-hiding uniform"
  - "The read is source-filtered to context-pack-generator so future post-decomposed research-evidence rows never surface here (T-7-09-05 accepted, scoped out)"
  - "ContextPackView projects only id/text_content/created_at/notes — no space_id/storage identifiers leak (T-7-09-02)"

patterns-established:
  - "ResearchArtifactRepository is a thin TenantRepository subclass; its two reads are space-walled by _scope for free (superadmin-bypass via the 0003 policy)"
  - "get_research_artifact_repo copies get_skill_run_repo verbatim (role→engine, null-space 403 before any session, one maker.begin() tx, GUC user-path only)"

requirements-completed: [AI-02, AI-04]

# Metrics
duration: ~12min
completed: 2026-07-13
---

# Phase 7 Plan 09: Context-Pack Read Surface + Skill Discriminator Summary

**Space-scoped GET /intakes/{id}/context-pack (latest + history, existence-hidden) backed by a new ResearchArtifactRepository, plus a `skill` discriminator on the skill-run projection so 07-10 can tell apply-intake-skill runs apart from context-pack runs.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-07-13T16:51Z (approx)
- **Completed:** 2026-07-13T17:03:38Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments
- Added the READ surface the generated context pack always lacked: `GET /intakes/{intake_id}/context-pack` returns `{latest, history}` for an in-scope intake with a pack, and `{latest: null, history: []}` when there is none or the intake is out of scope (existence-hidden, D-07 / T-7-09-01).
- Added `ResearchArtifactRepository` (space-scoped via `_scope`) with `latest_context_pack_for_intake` + `list_context_packs_for_intake`, both filtered on the exact `source == "context-pack-generator"` literal the write path stamps.
- Added `get_research_artifact_repo` DI injector — byte-for-byte the `get_skill_run_repo` shape (role→engine, null-space 403 before any session, one-tx, GUC user-path only) so a null-space user is default-denied 403 (T-7-09-03).
- Projected `skill` on `SkillRunView` (verbatim from `run.skill`, ORM `server_default` guarantees legacy rows read back `apply-intake-skill`) without disturbing `status`/`applied_at`/`completed_at`.
- Authored 4 integration tests (discriminator, pack-read shape + source filter, empty read, cross-tenant existence-hiding) against the existing harness.

## Task Commits

Each task was committed atomically:

1. **Task 1: skill discriminator + ResearchArtifactRepository** - `a0464d7` (feat)
2. **Task 2: DI injector + GET /{intake_id}/context-pack endpoint** - `a6a0289` (feat)
3. **Task 3: tests (projection, discriminator, source filter, cross-tenant hiding)** - `445a7b8` (test)

## Files Created/Modified
- `backend/app/api/intake_routes.py` - Added `skill` to `SkillRunView` + `_skill_run_view`; added `ContextPackView` + `_context_pack_view`; added `get_context_pack` GET endpoint; imported `get_research_artifact_repo`.
- `backend/app/db/repository.py` - Imported `ResearchArtifact`; added `ResearchArtifactRepository` with the two space-scoped context-pack reads.
- `backend/app/db/session.py` - Imported `ResearchArtifactRepository`; added `get_research_artifact_repo` injector.
- `backend/tests/test_intake_routes.py` - Added 4 tests + seed helpers (`_seed_intake_direct`, `_seed_run_with_skill`, `_seed_context_pack`, `_cleanup_spaces`).

## Decisions Made
- **Empty read is a 200, not a 404:** absence of a pack ≠ absence of the intake, and this keeps the cross-tenant outcome uniform (a stranger cannot distinguish "no pack" from "not your intake").
- **Source-literal filter:** pinning the read to `source == "context-pack-generator"` deliberately excludes future post-`decomposed` research-evidence rows (T-7-09-05, accepted/out-of-scope for this milestone).
- **Projection discipline:** `ContextPackView` carries no `space_id`/`storage_bucket`/`storage_path`, mirroring `SkillRunFullView`.

## Deviations from Plan

None - plan executed exactly as written. All three tasks landed against the interfaces documented in the plan; the `skill` ORM column and the `source="context-pack-generator"` write literal both matched the codebase exactly (confirmed by reading `skill_run.py` and `app/ai/skills/context_pack.py`).

## Issues Encountered
None. The `test_skill_run_full.py` and `test_ai_context_pack.py` suites provided exact templates for the skill-run seed (with `skill` column) and the `research_artifacts` insert shape, so the tests were authored by construction without guesswork.

## Verification Status

- **Automated source assertions (run locally):** all three task `<verify><automated>` greps PASS.
  - Task 1: `skill=run.skill` present; `class ResearchArtifactRepository` present; `context-pack-generator` present.
  - Task 2: `def get_research_artifact_repo` present; `/{intake_id}/context-pack` route present; NO raw DB symbol (`get_engine`/`get_superadmin_engine`/`sessionmaker`/`create_engine`) in `intake_routes.py` (ci_no_raw_db_access.sh stays green).
  - Task 3: `context-pack` + `skill` present in the test file (4 new `test_` functions authored).
- **Runtime behavior (pytest suite) NOT run locally:** this dev machine has NO Python/Docker (per project constraint + MEMORY dev-machine-no-python-docker). The integration tests are authored by construction and run under `pytest.mark.integration` in **Cloud Build** (documented in the project deploy runbook). The change also requires a **Cloud Build image rebuild + Cloud Run redeploy** to go live — nothing here ships to the live Cloud Run revision automatically.

## User Setup Required
None - no external service configuration required. (Deploy is a standard image rebuild + Cloud Run redeploy; see the project runbook.)

## Next Phase Readiness
- **07-10 (frontend) can now:** call `GET /intakes/{id}/context-pack` to render `ContextPackBlock.loadLatest`/`loadHistory` (previously stubbed), and filter skill runs on the new `skill` field so it no longer assumes "newest succeeded run == apply-intake-skill" (context-pack now also lands succeeded runs).
- **Blocker for live UAT:** the change is authored + committed but NOT yet on the live Cloud Run revision — it needs the next image rebuild + redeploy before the endpoint is reachable in a live browser test.

## Self-Check: PASSED

All modified files exist on disk; all four commits (`a0464d7`, `a6a0289`, `445a7b8`, `1b77745`) are present in the branch history. Working tree clean. (SUMMARY.md is force-added — `.planning/` is gitignored in this repo.)

---
*Phase: 07-ai-function-ports*
*Completed: 2026-07-13*
