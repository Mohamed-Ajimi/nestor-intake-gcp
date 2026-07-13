---
phase: 07-ai-function-ports
plan: 10
subsystem: ui
tags: [react, context-pack, skill-runs, ai-review, running-clock, discriminator, uat-gap-closure]

# Dependency graph
requires:
  - phase: 07-ai-function-ports
    provides: "GET /intakes/{id}/context-pack read surface ({latest, history}, existence-hidden) + skill discriminator on SkillRunView (07-09)"
  - phase: 07-ai-function-ports
    provides: "AISkillsPanel mount + copy-link rebuild in admin.pulse.intakes.$id.tsx (07-11, shared route file)"
provides:
  - "contextPack.ts seam (getContextPack) over the 07-09 read surface"
  - "ContextPackBlock loadLatest/loadHistory wired to the real pack markdown + history (stubs removed)"
  - "Context-pack running affordance (RunningClock) in the awaiting_context_pack banner + terminal pack reload"
  - "skill on the frontend SkillRun + ActiveSkillRun types; proposals loader + review-consume effect discriminated to apply-intake-skill"
affects: [live-uat, 12-cutover]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "View→UI shape mapper (toPack): ContextPackView text_content/created_at → Pack output/completed_at, cost/model null-filled"
    - "One-shot terminal reload signal gated on the skill discriminator (contextPackReloadSignal = `${status}:${runId}` only for a terminal context-pack run) — no unconditional poll"

key-files:
  created:
    - frontend/src/lib/api/contextPack.ts
  modified:
    - frontend/src/lib/api/skillRuns.ts
    - frontend/src/components/intake/ContextPackBlock.tsx
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/intake/SkillRunProgress.tsx
    - frontend/src/components/intake/IntakeForm.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx

key-decisions:
  - "Reload strategy = BOTH status-driven AND a one-shot terminal signal. The status-driven reload (ContextPackBlock's load effect already depends on intakeStatus, which flips to `decomposed` via the route's load()) covers the first generation; the explicit reloadSignal covers the re-generate case where the status is already `decomposed` and would not re-trigger the effect."
  - "skill WAS threaded onto ActiveSkillRun (not just gated on phase). The latest run can now be a context-pack run, so the review-consume effect and the context-pack reload gate both need the discriminator directly rather than relying on the phase gate alone."
  - "Dropped the `?? runsRes.data.latest` fallback in the IntakeForm proposals loader — with the discriminator present, a succeeded context-pack/structure-answers run must never be mistaken for the proposals source."

patterns-established:
  - "toPack maps the projection-only view onto the richer UI Pack shape; cost/model are cosmetic and null-tolerant so only the markdown (output) is load-bearing"
  - "Reload signal is gated + one-shot (changes only on a terminal context-pack run) to avoid the T-7-10-03 reload-loop"

requirements-completed: [AI-02]

# Metrics
duration: ~25min
completed: 2026-07-13
---

# Phase 7 Plan 10: Context-Pack Display + Run Progress + Skill Discriminator Summary

**Wired the frontend to the 07-09 read surface so the generated context pack markdown renders (Bekijk laatste / Download PDF / history), gave the context-pack run the same RunningClock progress UX apply-intake-skill has, and discriminated the two run consumers (proposals loader + admin review) on the new `skill` field so a context-pack succeeded run can no longer be mistaken for an apply-intake-skill run.**

## Performance
- **Duration:** ~25 min
- **Completed:** 2026-07-13
- **Tasks:** 3
- **Files:** 1 created, 6 modified

## Accomplishments
- **Task 1 — read surface + skill field.** Added `frontend/src/lib/api/contextPack.ts` (`getContextPack` + `ContextPackView`/`ContextPackRead` types) mirroring the `skillRuns.ts` seam style. Rewired `ContextPackBlock.loadLatest`/`loadHistory` from their stub bodies (`setLatestPack(null)`/`setHistory([])`) to the real `GET /intakes/{id}/context-pack` read, mapping the projection view onto the UI `Pack` shape via a `toPack` helper (`text_content→output`, `created_at→completed_at`, cost/model null-filled). Added `skill: string` to the frontend `SkillRun` type; `latestPhaseInput` untouched (still maps only `{status, applied_at}`), so `derivePhase` is unaffected.
- **Task 2 — running affordance + terminal reload.** `NextStepBanner`'s `awaiting_context_pack` case now renders `<RunningClock triggeredAt={activeRun.triggered_at} />` (+ a "Context Pack wordt gegenereerd…" body) when `activeRun?.status === "running"`, mirroring the `awaiting_skill_run` case; the Genereer button stays for the not-running state. `ContextPackBlock` gained an optional `reloadSignal` prop; its load effect re-reads the pack (and re-fetches history when already opened) when the signal changes.
- **Task 3 — discriminated consumers.** Threaded `skill` onto `ActiveSkillRun` (populated in `toActiveSkillRun` from the new `SkillRun.skill`). The `IntakeForm` proposals loader now requires `r.skill === "apply-intake-skill" && r.status === "succeeded"` (fallback dropped). The admin review-consume effect guards `if (activeRun.skill !== "apply-intake-skill") return;`. The `contextPackReloadSignal` in the admin route is gated to terminal context-pack runs only.

## Task Commits
1. **Task 1: contextPack.ts seam + wire loadLatest/loadHistory + skill on SkillRun** — `62b3990` (feat)
2. **Task 2: context-pack RunningClock affordance + terminal pack reload** — `35fdc70` (feat)
3. **Task 3: discriminate apply-intake-skill in proposals + review consumers** — `59ad201` (feat)

## Files Created/Modified
- `frontend/src/lib/api/contextPack.ts` (created) — `getContextPack` seam + `ContextPackView`/`ContextPackRead` types over `apiFetch`.
- `frontend/src/lib/api/skillRuns.ts` — added `skill: string` to the `SkillRun` type.
- `frontend/src/components/intake/ContextPackBlock.tsx` — `toPack` mapper; real `loadLatest`/`loadHistory`; optional `reloadSignal` prop; load effect re-reads on the signal.
- `frontend/src/components/intake/NextStepBanner.tsx` — `awaiting_context_pack` renders `RunningClock` while running.
- `frontend/src/components/intake/SkillRunProgress.tsx` — `skill` on `ActiveSkillRun`; populated in `toActiveSkillRun`.
- `frontend/src/components/intake/IntakeForm.tsx` — proposals loader discriminated to apply-intake-skill succeeded.
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — review-consume skill guard; `contextPackReloadSignal` gated to terminal context-pack runs and passed to `ContextPackBlock`; synthetic `bannerActiveRun` given a `skill` field.

## Decisions Made
- **Reload strategy — status-driven + one-shot terminal signal (both).** First generation: the route's `load()` flips `intake.status → decomposed`, re-rendering `ContextPackBlock` with a new `intakeStatus`; its existing load effect re-runs `loadLatest`. Re-generate on an already-`decomposed` intake: status does not change, so an explicit `reloadSignal` (`${status}:${runId}`, gated to terminal context-pack runs) re-triggers the effect. This satisfies the plan's preference for the status-driven path while closing the re-generate hole, and stays one-shot (no reload loop, T-7-10-03).
- **`skill` threaded onto `ActiveSkillRun`.** The latest run can now be a context-pack run, so the plan's safer option (explicit skill guard) was taken over the phase gate alone — both the review-consume effect and the reload-signal gate discriminate directly on `skill`.

## Deviations from Plan
None — all three tasks executed as written against the documented 07-09/07-11 interfaces. The `skill` ORM projection, the `{latest, history}` shape, and the `text_content`/`created_at` field names all matched the 07-09 contract exactly. The one non-obvious sequencing detail (moving `loadHistory`'s `useCallback` above the load effect to satisfy TDZ, since the effect now references it) was a mechanical fix, not a scope change.

## Verification Status
- **Automated source assertions (run locally):** all three tasks' `<verify><automated>` greps PASS.
  - Task 1: `getContextPack` appears 3× in `ContextPackBlock.tsx` (≥2 required); `skill: string` appears exactly 1× in `skillRuns.ts`.
  - Task 2: `RunningClock` appears 3× in `NextStepBanner.tsx` (≥2 required).
  - Task 3: `skill === "apply-intake-skill"` present and `r.status === "succeeded"` present in `IntakeForm.tsx`.
- **Typecheck:** `tsc --noEmit` (via the main checkout's TypeScript, junctioned into the worktree since the worktree has no node_modules) exits **0** at HEAD across all three commits — no type errors introduced.
- **Runtime behavior NOT verified live:** live render of the pack markdown requires the **07-09 backend change to be DEPLOYED** (Cloud Build image rebuild + Cloud Run redeploy) — the endpoint is not on the live revision yet. The frontend is authored against the contract and testable on local vite (npm, localhost:8081) once the image ships. No frontend test harness exists (project constraint).

## Known Stubs
None — the two `loadLatest`/`loadHistory` stubs that existed at plan start were the target of this plan and are now wired to the real read.

## Threat Flags
None — no new security surface. `getContextPack` sends only `intakeId` in the path and renders whatever the server-scoped endpoint returns (existence-hidden empty read for a stranger, per 07-09 `_scope`); the discriminator fixes a correctness/trust ambiguity, not a privilege boundary; the reload is a gated one-shot, not a poll. Matches the plan's threat register (T-7-10-01/02/03/SC all `mitigate`, no new packages).

## Self-Check: PASSED
- Created file verified on disk: `frontend/src/lib/api/contextPack.ts` — FOUND.
- Task commits verified in branch history: `62b3990`, `35fdc70`, `59ad201` — all FOUND.
- Working tree clean; `tsc --noEmit` exit 0; no file deletions vs base.

---
*Phase: 07-ai-function-ports*
*Completed: 2026-07-13*
