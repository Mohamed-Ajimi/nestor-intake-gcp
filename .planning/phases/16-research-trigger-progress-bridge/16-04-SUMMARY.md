---
phase: 16-research-trigger-progress-bridge
plan: 04
subsystem: frontend-admin-research
tags: [react, tanstack, sse, i18n, shadcn, research, admin-ui]

# Dependency graph
requires:
  - phase: 16-02
    provides: backend contract — POST /intakes/{id}/research (202 {research_run_id}), GET /intakes/{id}/research/stream (mirrored research_runs SSE frame with verbatim Tribunal status + stage_detail + cost_usd_total)
  - phase: 08-skill-run-stream
    provides: openSkillRunStream SSE reader + useActiveSkillRun SSE-first/poll-fallback hook (cloned here) and the intake progress design language
  - phase: 14-auth-retirement
    provides: apiFetch/currentIdToken token-attaching transport (Bearer only, never URL/log)
provides:
  - triggerResearch() + openResearchStream() + ResearchRun type (frontend research transport)
  - ResearchRunProgress panel — dynamic-stage progress + summary/failure end states, SSE-first
  - Start-research AlertDialog confirm gate in NextStepBanner (D-03)
  - additive derivePhase in_research semantics (status-driven, no artifact writer)
affects: [16-05 operator UAT session, 17 raw-output surface (reads output_markdown)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "SSE reader cloned verbatim from openSkillRunStream except the terminal set {completed,failed,cancelled} (Tribunal-verbatim, D-05) + the /research/stream URL — never fork the apiFetch transport (it buffers)"
    - "Stage list rendered DYNAMICALLY via .map over the mirrored stage_detail (no hardcoded 9) so a Phase-15 added pass costs the UI nothing (T-16-14)"
    - "Deep-research trigger gated behind a shadcn AlertDialog — the 202 fires only on the confirm action, never on the initial click (D-03)"
    - "in_research phase visibility driven by intake STATUS alone (no research_artifacts writer this milestone); a completed run does not auto-advance (Pitfall 6/10)"

key-files:
  created:
    - frontend/src/lib/api/research.ts
    - frontend/src/components/intake/ResearchRunProgress.tsx
  modified:
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/lib/intake-phase.ts
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/locales/nl/intake.json
    - frontend/src/locales/nl/admin.json

key-decisions:
  - "openResearchStream clones openSkillRunStream verbatim (backoff, malformed-skip, 404/401->onFallback, null-snapshot guard) changing only RESEARCH_TERMINAL + the URL"
  - "No dedicated research poll read exists yet — useActiveResearchRun's onFallback keeps the last snapshot after the reader's own bounded reconnect (the SkillRun 5s poll has no research analog)"
  - "Panel offers the re-trigger affordance unconditionally on failure; the 3-attempt cap (D-04) is enforced server-side and an over-cap retry is surfaced as a toast"
  - "derivePhase change is a comment-only additive clarification — the in_research status branch already returned in_research with hasResearchArtifacts=false; no behavior change, existing branches retained"

requirements-completed: [RUN-01, SEAM-03]

# Metrics
duration: 21min
completed: 2026-07-21
---

# Phase 16 Plan 04: Admin Research Experience Summary

**The operator's window into a Tribunal run: a `Start research` confirm dialog that fires the 202 only on confirm (D-03), a live progress panel that renders the stage list DYNAMICALLY from the mirrored `research_runs` stage trace (no hardcoded 9) with a running cost + elapsed clock and collapses to a summary card on completion or a failure card with a re-trigger affordance (D-09), the cloned SSE reader + return-no-throw trigger that feed it, and an additive `derivePhase` — all while leaving the client-facing UI completely unchanged during `in_research` (D-08).**

## Performance
- **Duration:** ~21 min
- **Completed:** 2026-07-21
- **Tasks:** 3
- **Files:** 7 (2 created, 5 modified)

## Accomplishments
- **`research.ts` (Task 1):** `triggerResearch(intakeId)` — a one-shot `apiFetch` POST returning `ApiResult<{research_run_id}>` (return-no-throw, never forks the transport). `openResearchStream` clones `openSkillRunStream` VERBATIM except `RESEARCH_TERMINAL = {completed,failed,cancelled}` (Tribunal-verbatim, D-05) and the `/intakes/{id}/research/stream` URL — reusing `currentIdToken` (Bearer only, never URL/log), the `apiUrl` builder, raw-fetch `getReader()` frame parsing, `": ping"` skip, malformed-frame skip, null-snapshot guard, 404/401→onFallback, and the 3× backoff. Added a `ResearchRun` type matching the SSE frame.
- **`ResearchRunProgress.tsx` (Task 2):** `useActiveResearchRun` copies the SkillRunProgress SSE-first mechanics (cancelled-cleanup flag, terminal→`stream.close()`). The panel renders one row per stage via `.map` over the flattened `stage_detail` (data-driven — a 10-stage run renders 10 rows; NO hardcoded count) with per-stage done/running/pending icons, plus a running cost + elapsed clock, in the intake design language (`border-l-4`, `bg-paperLight`, `font-mono text-[11px] uppercase tracking-wider`, `#FF2D87` accent, `tabular-nums` clock, `role="status" aria-live="polite"`). On a terminal status it collapses to a summary card (completed timestamp / total cost / duration) or a failure card (`error_message` + a re-trigger button surfaced via `onRetry`).
- **Wiring + additive derivePhase (Task 3):** `NextStepBanner` wraps the `awaiting_research_start` CTA in a shadcn `AlertDialog` — the button opens the dialog, and the trigger fires ONLY on `AlertDialogAction` (confirm), Cancel is a no-op (D-03). `admin.pulse.intakes.$id.tsx` rewires `onStartAutoResearch` to `triggerResearch(id)` (return-no-throw, toast + `load()` refresh), adds `onRetryResearch`, and mounts `<ResearchRunProgress>` when `intake.status === "in_research"`. `intake-phase.ts` gets an additive clarification: `in_research` visibility is status-driven (no artifact writer this milestone) and a completed run does not auto-advance to `awaiting_report_upload` — the `hasResearchArtifacts` branch is retained.

## Task Commits
1. **Task 1: research.ts API client + SSE reader** — `6d9e2fb` (feat)
2. **Task 2: ResearchRunProgress panel** — `cfdff03` (feat)
3. **Task 3: confirm-dialog trigger + panel wiring + additive derivePhase** — `8a2f5fe` (feat)

## Files Created/Modified
- `frontend/src/lib/api/research.ts` — triggerResearch + openResearchStream + ResearchRun type
- `frontend/src/components/intake/ResearchRunProgress.tsx` — dynamic-stage panel + summary/failure end states, SSE-first
- `frontend/src/components/intake/NextStepBanner.tsx` — AlertDialog confirm gate on the Start-research CTA
- `frontend/src/lib/intake-phase.ts` — additive in_research comment (status-driven; no auto-advance)
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — trigger wiring + panel mount + onRetryResearch
- `frontend/src/locales/nl/intake.json` — research.* panel/summary/failure keys + nextStep confirm-dialog keys
- `frontend/src/locales/nl/admin.json` — researchStarted/researchStartFailed toast keys

## Decisions Made
- **Clone, don't re-derive (D-05 boundary):** `openResearchStream` is a verbatim clone of the proven `openSkillRunStream` so the only research-specific facts are the terminal set and the URL. The Tribunal status literals stay verbatim in `ResearchRun.status` — never remapped to the skill-run `{succeeded,failed}` vocabulary.
- **Dynamic stage list (T-16-14):** the panel `.map`s over `stage_detail` — never a hardcoded stage count — so a future Phase-15 added pass renders automatically.
- **Additive derivePhase, comment-only:** the existing `in_research` status branch already returned `in_research` when `hasResearchArtifacts=false` (which it always is this milestone), so the change is a clarifying comment plus the guarantee that a completed run does not flip to `awaiting_report_upload`. No behavior change; the `hasResearchArtifacts`/`final_report_artifact_id` branches are retained for the later report-upload flow.
- **Re-trigger affordance always shown, cap enforced server-side:** the failure card always offers `onRetry`; the D-04 3-attempt cap lives on the backend, and an over-cap retry surfaces as a toast rather than a disabled-button guess client-side.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Corrected the i18n locale file path**
- **Found during:** Task 2
- **Issue:** the plan's `files_modified` + `read_first` referenced `frontend/src/lib/i18n/locales/nl/intake.json`, which does not exist. The i18n instance (`frontend/src/lib/i18n/index.ts`) imports catalogs from `@/locales/{lng}/{ns}.json` — the real path is `frontend/src/locales/nl/intake.json`.
- **Fix:** added all NL keys to the real `frontend/src/locales/nl/intake.json` (and `admin.json`).
- **Files modified:** `frontend/src/locales/nl/intake.json`, `frontend/src/locales/nl/admin.json`
- **Verification:** `node -e JSON.parse(...)` valid; `npx tsc --noEmit` clean (i18next resolves the keys at runtime).
- **Committed in:** `cfdff03` (intake.json) + `8a2f5fe` (admin.json)

**2. [Rule 2 - Missing critical functionality] Added admin.json trigger toasts**
- **Found during:** Task 3
- **Issue:** the plan's `action` says "toast on error" for the trigger but listed no toast keys and no `admin.json` in `files_modified`. The route's toasts read the `admin` namespace (`intakeDetail.toast.*`); firing a bare English string would break the multi-language UI (a CLAUDE.md constraint).
- **Fix:** added `researchStarted` (success) + `researchStartFailed` (error fallback) under `intakeDetail.toast` in `nl/admin.json`; the error path still prefers a `resolveErrorKey(code)` translation when the backend sends a machine code (D-11).
- **Files modified:** `frontend/src/locales/nl/admin.json`
- **Committed in:** `8a2f5fe`

---

**Total deviations:** 2 auto-fixed (1 blocking path correction, 1 missing i18n functionality). No architectural changes; no auth gates.
**Impact on plan:** Both are required for the plan's own acceptance criteria (typecheck-clean + toast-on-error in the multi-language UI). No scope creep — FR/EN catalog parity for the new keys is deferred (nl is the guaranteed fallback per i18n D-04/D-05; see Known Stubs).

## Issues Encountered
- **No live backend to exercise the stream (dev box):** the SSE reader + panel are authored by construction against the read analogs (`skillRunStream.ts`, `SkillRunProgress.tsx`, the 16-02 backend contract). A live run rendering dynamic stages + cost is the Plan-05 operator UAT item. All frontend gates (typecheck, JSON validity, client-route grep) pass locally.

## Known Stubs
None that block the plan's goal. The new NL keys are NOT yet mirrored into `fr/` and `en/` catalogs — `nl` is the guaranteed i18n fallback (index.ts `fallbackLng: "nl"`, D-04/D-05), so the panel renders correctly in every locale with Dutch copy until FR/EN parity is added. This mirrors the existing per-namespace key-parity backlog and is not a functional gap for this milestone (admin operators run in nl).

## Threat Flags
None beyond the plan's threat_model. The three `mitigate` dispositions are satisfied:
- **T-16-12** (client-visible research surface): `ResearchRunProgress` is imported ONLY by the admin detail route — grep of `frontend/src/routes/*.$token.tsx` (the client intake/results routes) shows no match.
- **T-16-13** (id token via SSE URL/log): the cloned reader attaches the Bearer header only; the token never appears in the URL or a log (skillRunStream discipline preserved verbatim).
- **T-16-14** (stale hardcoded stage list): the stage list is rendered via `.map` over the run's `stage_detail` — no hardcoded count / no literal 9.

## Self-Check: PASSED
- **Files:** all 7 present (2 created, 5 modified) — verified via git + filesystem.
- **Commits:** `6d9e2fb`, `cfdff03`, `8a2f5fe` all present in `git log`.
- **Content pins:** `openResearchStream` + `RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"])` + `/research/stream` in research.ts; `.map(` over stage rows + `role="status"` in ResearchRunProgress.tsx; `AlertDialog` + `AlertDialogAction onClick={props.onStartAutoResearch}` in NextStepBanner.tsx; `triggerResearch(id)` + `ResearchRunProgress` mount in the route.
- **Typecheck:** `npx tsc --noEmit -p tsconfig.json` reports no `error TS` lines (full run).
- **Client-route grep:** no `ResearchRunProgress` import in `*.$token.tsx` (T-16-12 asserted).
- **JSON:** `nl/intake.json` + `nl/admin.json` parse clean.

## Next Phase Readiness
- Plan 05 (operator UAT) can drive a live run: click Start research → confirm dialog → 202 → the panel renders dynamic stages + running cost → summary card on completion (or failure card + retry on failure).
- Phase 17 (raw-output surface) reads the `output_markdown` the poll driver persists; the frontend `ResearchRun` type intentionally omits it (the panel does not render the raw report — that is a separate surface).
- Deploy note: the frontend must be rebuilt/redeployed to ship `research.ts` + `ResearchRunProgress` + the new NL keys; the backend intake image must already ship the 16-02/16-03 trigger + stream routes and have `TRIBUNAL_SERVICE_URL` set on `nestor-api`.

---
*Phase: 16-research-trigger-progress-bridge*
*Completed: 2026-07-21*
