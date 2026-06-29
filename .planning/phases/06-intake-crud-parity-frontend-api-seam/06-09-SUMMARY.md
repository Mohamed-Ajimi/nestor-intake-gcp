---
phase: 06-intake-crud-parity-frontend-api-seam
plan: 09
subsystem: ui
tags: [react, tanstack-router, intake, tenant-isolation, firebase-auth]

# Dependency graph
requires:
  - phase: 06-05
    provides: "lib/api seam (intakes/answers/templates over apiFetch), shared StatusPill/_status atoms, active-space accessor"
  - phase: 06-06
    provides: "IntakeForm data-layer swap to the seam (save-per-section + submit) — hosted, not forked, by the fill route"
provides:
  - "Authenticated, space-scoped user intake list (/intake) via listIntakes seam"
  - "User fill/submit route (/intake/$id) hosting the reused IntakeForm"
  - "Read-only validated-results route (/intake/$id/results) via reused FieldDisplay, with phase-ceiling redirect"
  - "Three intake.* routes registered in the generated route tree (hand-authored, flat under root)"
affects: [phase-07-context-pack, phase-11-i18n, frontend-uat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Top-level authenticated route group with inline authReady() beforeLoad guard (mirrors admin.tsx; NOT under /admin, no ProductShell/SpaceSwitcher)"
    - "Minimal user chrome (Agenic eyebrow + email + Uitloggen) inline per route on bg-paper max-w-4xl"
    - "Status → contextual row CTA mapping (draft→invullen, submitted/reviewed→bekijken, validated/decomposed→resultaat)"
    - "IntakePayload constructed client-side from the seam (getIntake + listAnswers + getTemplates) to host the reused IntakeForm by its existing prop contract"

key-files:
  created:
    - frontend/src/routes/intake.index.tsx
    - frontend/src/routes/intake.$id.tsx
    - frontend/src/routes/intake.$id.results.tsx
  modified:
    - frontend/src/routeTree.gen.ts

key-decisions:
  - "Hosted IntakeForm via the EXISTING base prop contract { payload, token } by constructing an IntakePayload from the seam — host-not-fork; token = intake id"
  - "Registered intake.* as FLAT siblings under the root route (no intake.tsx layout exists); flagged for authoritative regen"
  - "Titel column falls back to client_name (seam Intake type exposes no title); Laatst bewerkt reads updated_at defensively (optional in projection)"

patterns-established:
  - "Authenticated non-admin route group with per-route beforeLoad guard"
  - "Read-only results view enforcing the decomposed scope ceiling (no research/context-pack components)"

requirements-completed: [INTAKE-01, INTAKE-02, TENANT-04, API-03]

# Metrics
duration: ~30min
completed: 2026-06-29
---

# Phase 6 Plan 09: Client-Facing Authenticated Intake Surface Summary

**Re-introduced the client intake as a logged-in, space-scoped journey — list → open → fill (reused IntakeForm) → submit → read-only validated results — as three top-level `intake.*` routes outside `/admin`, with no space switcher and a hard decomposed scope ceiling.**

## Performance

- **Duration:** ~30 min
- **Completed:** 2026-06-29T17:59:39Z
- **Tasks:** 3 implementation tasks complete (Task 4 is human-verify — see Pending Human Verification)
- **Files modified:** 4 (3 created, 1 modified)

## Accomplishments
- `/intake` — authenticated, space-scoped intake list via `listIntakes()` (no inline legacy client, no Klant column, no switcher), with the shared `StatusPill`, contextual row CTAs, loading skeletons, load-error copy, and the `Nog geen intake klaargezet` empty state.
- `/intake/$id` — hosts the REUSED `IntakeForm` (not forked) by constructing an `IntakePayload` from `getIntake` + `listAnswers` + `getTemplates`; editable only for `draft`, read-only otherwise.
- `/intake/$id/results` — read-only validated answer set via the reused `FieldDisplay` grouped by section; redirects to the fill route when status `< validated_by_client`; renders NO `ResearchResultsPanel`/`ContextPackBlock` (scope ceiling).
- Three routes registered in `routeTree.gen.ts` (hand-authored — no `node_modules` to run the router plugin in this worktree).

## Task Commits

1. **Task 1: User intake list route (/intake)** - `be7b283` (feat)
2. **Task 2: User fill route + results route** - `3578aab` (feat)
3. **Task 3: Register intake.* in the route tree** - `8bbfb9b` (chore)

_Task 4 (`checkpoint:human-verify`) cannot be executed by an agent — documented below for the phase-level HUMAN-UAT._

## Files Created/Modified
- `frontend/src/routes/intake.index.tsx` - Authenticated space-scoped user intake list; minimal chrome; contextual CTAs; uses `listIntakes` + shared `StatusPill`.
- `frontend/src/routes/intake.$id.tsx` - Authenticated fill/submit route; loads the seam, builds an `IntakePayload`, hosts the reused `IntakeForm`.
- `frontend/src/routes/intake.$id.results.tsx` - Authenticated read-only results view; phase-ceiling redirect; reused `FieldDisplay` per section + `StatusPill`.
- `frontend/src/routeTree.gen.ts` - Registered `/intake`, `/intake/$id`, `/intake/$id/results` as flat children of the root route (imports, `.update()` consts, FileRoutes maps/unions, FileRoutesByPath, and `rootRouteChildren` assembly).

## Decisions Made
- **Host-not-fork IntakeForm via its existing contract.** On this worktree's base, `IntakeForm` still takes `{ payload, token }`. The fill route constructs an `IntakePayload` from the seam and passes `token = intake.id`. Plan 06-06 (parallel) swaps IntakeForm's internal save/submit to the seam; this route does not touch IntakeForm. See Deviations for the post-merge reconciliation flag.
- **Flat sibling routes under root.** There is no `intake.tsx` layout file, so the three routes were registered as direct children of the root route (matching how `admin.intakes.*` attach flat to their nearest layout). This keeps the fill route a leaf (no `<Outlet/>` needed).
- **Seam-type gaps handled gracefully.** The plan-05 `Intake` type exposes no `title`/`updated_at`; the list reads them defensively (optional extension type) and falls back to `client_name` / `—`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Hand-authored routeTree.gen.ts instead of `npm run build`**
- **Found during:** Task 3 (route tree regeneration)
- **Issue:** `node_modules` is absent in this fresh parallel worktree, so the `@tanstack/router-plugin` generator cannot run; running `npm install` was explicitly prohibited (5 parallel installs would thrash).
- **Fix:** Hand-authored the three new route registrations by faithfully following the existing generated pattern (imports → `.update()` route consts → `FileRoutes*` maps → unions → `FileRoutesByPath` → `RootRouteChildren` interface + `rootRouteChildren` assembly).
- **Files modified:** frontend/src/routeTree.gen.ts
- **Verification:** `grep -c "/intake/" src/routeTree.gen.ts` → 30; runtime assembly (imports, consts, `rootRouteChildren`) confirmed present.
- **Committed in:** `8bbfb9b`

---

**Total deviations:** 1 (1 blocking, environment-driven). No scope creep.
**Impact on plan:** None functionally; the route tree is provisional and must be confirmed by authoritative regen (see Issues / flags below).

## Issues Encountered / Flags for the Orchestrator

1. **Authoritative route-tree regen required (build-environment limitation).** The hand-authored `routeTree.gen.ts` must be regenerated via `npm run build` (or dev) post-merge to confirm. **Watch point:** because `intake.$id.tsx` exists as a real route file, the TanStack generator may NEST `/intake/$id/results` UNDER `/intake/$id` (parent→child) rather than as a flat sibling. If it does, the fill route would need to render an `<Outlet/>` (or the results page would not display). **Recommended resolution:** keep the three routes flat (as hand-authored here, which is runtime-correct for three independent pages); if the generator insists on nesting, split the fill UI into an index child (`intake.$id.index.tsx`) and make `intake.$id.tsx` a pure `<Outlet/>` layout. Either way the orchestrator's authoritative regen + `tsc` post-merge is the source of truth.

2. **IntakeForm prop-contract dependency on plan 06-06 (parallel wave).** The fill route hosts `IntakeForm` using the base contract `{ payload, token }`. If plan 06-06 changes IntakeForm's prop signature (e.g., drops `token` or accepts the intake/answers/template directly), the host call site in `intake.$id.tsx` must be reconciled during the orchestrator's post-merge `tsc`. The route already provides everything the form needs (full `IntakePayload` + intake id).

3. **submitted-status display nuance.** The reused IntakeForm shows its own confirmation screen when `payload.intake.status === "submitted"`; for `reviewed` it shows the read-only fields. Both are reachable via the list CTA `Antwoorden bekijken` → `/intake/$id`. This is inherent IntakeForm behavior (owned by 06-06) and was not forked here.

## Known Stubs
None — all data is wired through the live `lib/api` seam. The `product_slug`/`created_at`/`updated_at` placeholders passed into `IntakePayload.intake` are inert (IntakeForm does not consume them); the form keys all persistence on the intake id.

## User Setup Required
None - no external service configuration required.

## Pending Human Verification

Task 4 is a `checkpoint:human-verify` (gate="blocking") that requires running the app in a browser as a real user — an agent cannot perform it. Collect this into the phase-level HUMAN-UAT.

**What was built:** The full authenticated user journey — list → open → fill (save per section) → submit → view results, space-scoped, behind login, with no switcher.

**How to verify (verbatim from the plan):**
1. Run the frontend locally (`npm run dev`, localhost:8081) against the live backend.
2. Log in as a USER. Visit `/intake` → confirm only that user's space's intake(s) appear, no Klant column, no switcher.
3. Open a draft → fill a section → click `Volgende` → confirm one save happens (`Alle wijzigingen opgeslagen`) and that a forced failure keeps you on the section (does not advance). Submit → confirm the submitted state.
4. For a `validated_by_client`/`decomposed` intake, click `Bekijk resultaat` → confirm the read-only answer set renders (no research report). For a draft, confirm `/intake/$id/results` redirects back to the fill route.

**Resume signal:** Type "approved" or describe issues (cross-space leakage, save-on-advance broken, results showing research output).

**Pre-requisite for UAT:** run `npm install` + `npm run build` (authoritative route-tree regen + `tsc`) in the merged tree first; see Issues flag #1.

## Next Phase Readiness
- The client-facing intake surface is implemented end-to-end at the route layer against the seam.
- Blockers/concerns: authoritative `routeTree.gen.ts` regen (flag #1) and the IntakeForm prop reconciliation (flag #2) must be resolved during the orchestrator's post-merge build before HUMAN-UAT.

## Self-Check: PASSED

- All 3 created files + 1 modified file present on disk.
- All 3 task commits (`be7b283`, `3578aab`, `8bbfb9b`) present in git log.

---
*Phase: 06-intake-crud-parity-frontend-api-seam*
*Completed: 2026-06-29*
