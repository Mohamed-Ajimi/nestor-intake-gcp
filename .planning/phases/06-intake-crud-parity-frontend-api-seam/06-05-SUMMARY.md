---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 05
subsystem: frontend-api-seam
tags: [lib-api, transport-seam, active-space, status-atoms, column-reconcile, tenant-view-filter]
requires:
  - "Phase 5 transport seam frontend/src/lib/api/client.ts (apiFetch + ApiResult, token-attach, 401-eject) + admin.ts per-endpoint module pattern"
  - "06-03 backend contract: IntakeView/AnswerView/SkillRunView/TemplateView + endpoints GET/POST /intakes, GET/PATCH /intakes/{id}, answers, /submit, /review, /skill-runs, /templates, /search"
  - "intake-phase.ts PhaseSkillRunInput { status, applied_at } | null (derivePhase target shape)"
provides:
  - "frontend/src/lib/api/intakes.ts — listIntakes/getIntake/createIntake/patchIntake/submitIntake/reviewIntake + Intake type (all 5 phase markers)"
  - "frontend/src/lib/api/answers.ts — listAnswers + saveAnswers section-batch PATCH (D-03)"
  - "frontend/src/lib/api/templates.ts — getTemplates"
  - "frontend/src/lib/api/skillRuns.ts — listSkillRuns + latestPhaseInput (SkillRunView -> PhaseSkillRunInput reconcile)"
  - "frontend/src/lib/api/search.ts — search + refreshSearch (Phase 7 backend; seam shape fixed)"
  - "frontend/src/lib/active-space.tsx — withActiveSpace/setActiveSpaceId + ActiveSpaceProvider/useActiveSpace (superadmin view-filter)"
  - "frontend/src/components/intake/_status.tsx — shared StatusPill/STATUS_LABEL/STATUS_VARIANT"
affects:
  - "re-point plans 06/07/09 (replace supabase.from(...) with these modules)"
  - "switcher plan 08 (consumes ActiveSpaceProvider + listSpaces)"
tech-stack:
  added: []
  patterns:
    - "non-hook module accessor (withActiveSpace mirrors client.ts currentIdToken) read by lib/api without a React hook"
    - "one thin typed fn per backend route over apiFetch (mirrors admin.ts); never a forked fetch wrapper"
    - "column reconcile: latestPhaseInput maps backend SkillRunView status verbatim into PhaseSkillRunInput so derivePhase is not fed legacy column vocabulary"
key-files:
  created:
    - "frontend/src/lib/active-space.tsx"
    - "frontend/src/components/intake/_status.tsx"
    - "frontend/src/lib/api/intakes.ts"
    - "frontend/src/lib/api/answers.ts"
    - "frontend/src/lib/api/templates.ts"
    - "frontend/src/lib/api/skillRuns.ts"
    - "frontend/src/lib/api/search.ts"
  modified: []
decisions:
  - "active-space param is UX state only (T-06-13): withActiveSpace appends ?space_id; backend re-derives a user's space from the token so it can never widen access"
  - "StatusPill/STATUS_LABEL/STATUS_VARIANT extracted verbatim from admin.pulse.intakes.index.tsx (labels pinned by UI-SPEC) — source route not edited here (re-point plans rewire imports)"
  - "skillRuns.ts keeps completed_at on the SkillRun TYPE (mirrors backend SkillRunView) but never uses it as an ordering key; latestPhaseInput projects only { status, applied_at } for derivePhase"
  - "search.ts shape fixed now though the AI backend lands in Phase 7 — buttons may surface not-yet-available until then (per plan)"
requirements: [API-03, TENANT-04]
metrics:
  duration: "~15 min"
  completed: "2026-06-29"
  tasks: 3
  files: 7
---

# Phase 6 Plan 05: Frontend Intake API Seam Summary

Generalized the Phase 5 transport seam (`apiFetch`/`client.ts`) into per-entity `lib/api/*`
modules covering the whole intake flow — intakes, answers, templates, skill-runs, search —
plus the `active-space` provider that threads the superadmin view-filter and the shared status
atoms both intake lists reuse. Every module wraps the single token-attaching `apiFetch`
transport (never a forked `fetch`), mirrors the backend plan-03 `*View` contract, and includes
the skill-run column reconcile that feeds `derivePhase` correct data. This is the frontend
contract the re-point plans (06/07/09) and the space switcher (08) consume.

## What Was Built

### Task 1 — active-space provider + shared status atoms (commit d14b54f)
- `frontend/src/lib/active-space.tsx`: module-level `let _activeSpaceId` + `setActiveSpaceId(id)`
  + `withActiveSpace(path)` (the non-hook accessor mirroring `client.ts` `currentIdToken`), plus
  `ActiveSpaceProvider` (React Context mirroring `AuthProvider`) persisting to `localStorage`
  key `nestor.activeSpaceId`, defaulting to null ("Alle klanten"), and `useActiveSpace()`. The
  provider effect calls `setActiveSpaceId` so the non-hook accessor stays in sync with React
  state. Param is UX state only (T-06-13) — documented in the file header.
- `frontend/src/components/intake/_status.tsx`: `STATUS_LABEL`, `STATUS_VARIANT`, `StatusPill`
  extracted verbatim from `admin.pulse.intakes.index.tsx` (labels Concept/Ingediend/Gereviewd/
  Gevalideerd/Gedecomposeerd unchanged). The source route is NOT edited here — re-point plans
  rewire its imports.

### Task 2 — intakes.ts + answers.ts + templates.ts (commit db0a4ac)
- `intakes.ts`: `Intake` type with `status` + all five phase markers; `listIntakes()` over
  `withActiveSpace("/intakes")`, `getIntake`, `createIntake` (POST; space_id injected
  server-side, TENANT-02), `patchIntake(id, {client_name})` (client_name only), `submitIntake`
  + `reviewIntake` (POST transition verbs, empty body tolerated). `withActiveSpace` appears on
  the read path (count 3 incl. import + usage).
- `answers.ts`: `Answer`/`AnswerInput` types, `listAnswers(intakeId)` GET, `saveAnswers(intakeId,
  answers)` PATCH `/intakes/${id}/answers` with body `{ answers }` (section batch, D-03).
- `templates.ts`: `getTemplates()` GET `/intakes/templates`.

### Task 3 — skillRuns.ts (column reconcile) + search.ts (commit c2ecf6a)
- `skillRuns.ts`: `SkillRun` type matching backend `SkillRunView` `{ id, status, applied_at,
  completed_at }`, `SkillRunsView` `{ latest, runs }`, `listSkillRuns(intakeId)` GET, and
  `latestPhaseInput(intakeId)` mapping the latest run to `PhaseSkillRunInput` `{ status,
  applied_at }` (or null) — status passed through verbatim so `derivePhase` (terminal
  `"succeeded"`, Assumption A1) is fed correct data with no silent drift (T-06-15). The legacy
  column vocabulary (`skill_name`, ordering by `completed_at`) is gone (only referenced in the
  reconcile comment that documents what was replaced).
- `search.ts`: `search(query)` GET `/search` and `refreshSearch()` POST `/search/refresh` over
  `apiFetch`. AI backend lands in Phase 7; the seam shape is fixed now.

## Deviations from Plan

None — plan executed exactly as written.

## Verification

Node v22/npm available in this worktree, so the plan's `<verify>` blocks ran live:

- Task 1: `npx tsc --noEmit -p tsconfig.json | grep -E "active-space|_status"` → "no type errors
  in new files". `grep -c "let _activeSpaceId"` = 1; `grep -c "nestor.activeSpaceId"` = 1; labels
  Concept/Ingediend/Gereviewd/Gevalideerd/Gedecomposeerd all present in `_status.tsx`.
- Task 2: tsc clean for `lib/api/(intakes|answers|templates)`; `grep -L "apiFetch"` over the
  three returns nothing (all import apiFetch); `grep -c "fetch(" intakes.ts` = 0;
  `grep -c "withActiveSpace" intakes.ts` = 3; `Intake` declares all five phase markers;
  `saveAnswers` sends `{ answers }` via PATCH.
- Task 3: tsc clean for `lib/api/(skillRuns|search)`; `grep -c "applied_at" skillRuns.ts` = 5;
  `grep -rc "fetch("` over skillRuns.ts + search.ts both 0; search wraps `/search` + `/search/refresh`.
- Overall: `grep -rc "fetch("` across all five `lib/api` modules = 0 each (single transport,
  T-06-14); full tsc reports NO ERRORS in any new file.

## Known Stubs

`search.ts` (`search`/`refreshSearch`) targets backends that land in Phase 7 — by design per the
plan. The seam shape is fixed now; until Phase 7 these calls surface a not-yet-available error.
This is an intentional, plan-sanctioned seam-ahead-of-backend, not an unwired UI stub: no list/UI
in this plan renders hardcoded empty data, and the re-point plans (06/07/09) consume the modules.

## Threat Flags

None — all surface stays within the plan's `<threat_model>`. The three listed mitigations are
implemented: T-06-13 (withActiveSpace is a superadmin-only UX filter, documented as never authz),
T-06-14 (every module imports `apiFetch` — no forked transport, grep-confirmed 0 raw `fetch(`),
T-06-15 (skillRuns.ts maps backend status verbatim into PhaseSkillRunInput — no phase drift).

## Self-Check: PASSED
- All 7 source files FOUND
- SUMMARY.md FOUND
- Commits d14b54f, db0a4ac, c2ecf6a present in git log
