---
phase: 12-frontend-deploy-cutover-supabase-retirement
plan: 03
subsystem: api
tags: [fastapi, react, tanstack, i18n, tenant-isolation, transcribe, audio]

# Dependency graph
requires:
  - phase: 07-ai-ports
    provides: "transcribe dispatch (POST /intakes/{id}/sources/{source_id}/transcribe), IntakeSourceRepository.list_for_intake, get_intake_and_source_repos"
  - phase: 07-ai-ports (07-09)
    provides: "existence-hidden scoped-read pattern (get_context_pack, ContextPackView projection discipline)"
provides:
  - "GET /intakes/{intake_id}/sources — space-scoped, existence-hidden sources read (projection: id/kind/file_name/language/created_at only)"
  - "get_intake_source_repo single-repo dependency provider (mirrors get_skill_run_repo)"
  - "frontend sources.ts read seam (getIntakeSources over apiFetch)"
  - "transcribe CTA wired to real audio source ids (no longer permanently disabled)"
affects: [12-deploy-cutover, audio-transcription-e2e, 07-UAT, 09-UAT]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single-repo scoped-read provider for a pure read (get_intake_source_repo) — no ownership write-gate needed, the scoped repo IS the wall"
    - "Existence-hidden sources read: cross-tenant/missing intake reads scoped-empty {sources: []}, never a distinguishable 403 (T-12-07)"
    - "Projection discipline: never leak space_id/storage_bucket/storage_path to the browser (T-12-08)"

key-files:
  created:
    - frontend/src/lib/api/sources.ts
  modified:
    - backend/app/api/intake_routes.py
    - backend/app/db/session.py
    - backend/tests/test_intake_routes.py
    - frontend/src/components/intake/AISkillsPanel.tsx
    - frontend/src/locales/en/intake.json
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/fr/intake.json

key-decisions:
  - "Used a single-repo get_intake_source_repo provider (mirroring get_skill_run_repo) rather than the combined get_intake_and_source_repos — the read needs no ownership pre-check write gate, so a single scoped repo is the cleaner Depends."
  - "The endpoint returns a {sources: [...]} wrapper (not a bare list) so the shape is additively extensible and matches the frontend seam contract."
  - "Per audio source, render one enabled transcribe button (labeled by file_name); a single disabled CTA stands in only when no audio source exists."

patterns-established:
  - "Sources read mirrors the 07-09 context-pack existence-hidden read exactly (scoped repo, projection helper, scoped-empty on cross-tenant)."

requirements-completed: [QA-05]

# Metrics
duration: 22min
completed: 2026-07-14
---

# Phase 12 Plan 03: Sources-Read Surface + Transcribe CTA Wiring Summary

**Added the missing space-scoped, existence-hidden `GET /intakes/{id}/sources` read endpoint (projection leaks no tenant/storage identifiers) and wired the frontend transcribe CTA to each returned audio source id — the CTA is no longer permanently disabled.**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-07-14T14:55Z (approx)
- **Completed:** 2026-07-14
- **Tasks:** 2
- **Files modified:** 8 (1 created, 7 modified)

## Accomplishments

- Added `GET /intakes/{intake_id}/sources` — a space-scoped, existence-hidden read that projects only `id/kind/file_name/language/created_at` (no `space_id`/`storage_bucket`/`storage_path`), mirroring the 07-09 context-pack read discipline (T-12-07 / T-12-08).
- Added `get_intake_source_repo` single-repo dependency provider (mirrors `get_skill_run_repo` / `get_research_artifact_repo`).
- Wrote four RED-first tests: in-scope list, empty-scope, cross-tenant scoped-empty (200, not 403), superadmin bypass.
- Created `frontend/src/lib/api/sources.ts` read seam (`getIntakeSources` over `apiFetch`, mirrors `contextPack.ts`).
- Wired `AISkillsPanel` to fetch audio sources on mount and render one enabled transcribe button per source (dispatching `skills.transcribeSource(intakeId, source.id)`); the disabled-only state remains only when no audio source exists. Removed the stale "empty id is unreachable" comment/block.
- Added `transcribeSourceBtn` + `transcribeSourceFallback` i18n keys in en/nl/fr (parallel).

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing tests for the sources read** - `e7871df` (test)
2. **Task 1 (GREEN): sources read endpoint + provider** - `663a4d3` (feat)
3. **Task 2: frontend sources seam + transcribe wiring + i18n** - `c564806` (feat)

**Plan metadata:** committed after this summary (docs).

## Files Created/Modified

- `frontend/src/lib/api/sources.ts` (created) - `getIntakeSources` read seam over `apiFetch`; `IntakeSourceView`/`IntakeSourcesRead` types mirroring the backend projection.
- `backend/app/api/intake_routes.py` - `IntakeSourceView`/`IntakeSourcesView` models, `_intake_source_view` helper, `list_intake_sources` existence-hidden GET endpoint; import of `IntakeSourceRepository` + `get_intake_source_repo`.
- `backend/app/db/session.py` - `get_intake_source_repo` single-repo scoped provider.
- `backend/tests/test_intake_routes.py` - `_seed_source` helper + four sources tests (in-scope, empty, cross-tenant existence-hidden, superadmin).
- `frontend/src/components/intake/AISkillsPanel.tsx` - fetch audio sources on mount; per-source enabled transcribe buttons; disabled CTA only when no audio source.
- `frontend/src/locales/{en,nl,fr}/intake.json` - `transcribeSourceBtn` + `transcribeSourceFallback` keys.

## Decisions Made

- Single-repo `get_intake_source_repo` provider over the combined provider (read needs no write ownership gate — the scoped repo is the wall).
- `{sources: [...]}` wrapper response shape (extensible; matches the frontend seam).
- Per-source enabled transcribe buttons labeled by `file_name`; single disabled CTA fallback when no audio.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None during authoring. Test-run and lint-run environment notes below (expected, per project pattern).

## Verification Status

- **Backend (`pytest tests/test_intake_routes.py -k sources`):** authored TDD RED→GREEN by construction; NOT run locally — the dev box has no Python/Docker. The suite runs in Cloud Build per the project pattern (MEMORY: dev-machine-no-python-docker). Four tests target the new endpoint.
- **Frontend i18n-parallel check:** PASSED locally — `['en','nl','fr']` all carry `aiSkills.transcribeSourceBtn` + `transcribeSourceFallback`; all three `intake.json` parse as valid JSON.
- **`bash scripts/ci_no_hardcoded_dutch.sh src`:** PASSED (no hardcoded Dutch in in-scope source).
- **`npm run lint`:** NOT run locally — `frontend/node_modules` is not installed in the worktree; lint runs in CI/Cloud Build. All new strings are routed through `t(...)`; no hardcoded UI strings introduced.

## User Setup Required

None - no external service configuration required. No new packages installed (T-12-SC accept — reuses existing `apiFetch` + repositories). Deployment is out of scope for this code-only plan; it happens in plan 12-05.

## Threat Model Compliance

- **T-12-07 (BOLA/IDOR):** the endpoint derives space scope from the verified Identity via the scoped repo `Depends` only, never a client param; cross-tenant/missing reads scoped-empty (test `test_sources_read_cross_tenant_is_existence_hidden`).
- **T-12-08 (info disclosure):** `IntakeSourceView` exposes only id/kind/file_name/language/created_at; the in-scope test asserts `space_id`/`storage_bucket`/`storage_path` are absent from each item.
- **T-12-09 (EoP):** transcribe reuses the existing space-scoped `POST /sources/{source_id}/transcribe`; the frontend passes only a source id it just read from the scoped list — no new authz surface.

No new security surface beyond the plan's `<threat_model>`.

## Next Phase Readiness

- The sources-read surface + wired transcribe CTA unblock the audio-transcription E2E items (07-UAT #7, 09-UAT #8).
- Backend pytest run + frontend `npm run lint` remain to be executed in Cloud Build / CI (deferred, dev-box constraint).
- Deployment (image rebuild + revision) is plan 12-05, not this plan.

## Self-Check: PASSED

All created/modified files present on disk; all three task commits (`e7871df`, `663a4d3`, `c564806`) present in git history.

---
*Phase: 12-frontend-deploy-cutover-supabase-retirement*
*Completed: 2026-07-14*
