---
phase: 08-sse-skill-run-progress
plan: 02
subsystem: ui
tags: [sse, react, fetch, readable-stream, firebase-auth, skill-run, tanstack]

# Dependency graph
requires:
  - phase: 07-ai-function-ports
    provides: "apply-intake-skill background run + status=succeeded terminal contract; output_parsed/cost written but unprojected; the frozen useActiveSkillRun/useSkillRunFull hook contracts prepped in Phase 6/7"
  - phase: 08-sse-skill-run-progress (plan 08-01)
    provides: "backend SSE endpoint GET /intakes/{id}/skill-runs/stream (data: SkillRunView frames, : ping heartbeats, terminal succeeded/failed) + GET /intakes/{id}/skill-runs/{runId} full-run read"
provides:
  - "SSE-first useActiveSkillRun (live push restored, poll retained as silent fallback) behind an unchanged external contract"
  - "Hand-rolled fetch/ReadableStream SSE reader (openSkillRunStream) reusing the exact apiFetch token source — no EventSource, no new dependency"
  - "Un-stubbed useSkillRunFull + getSkillRunFull seam read so the terminal event feeds a working AIReviewPanel"
  - "Terminal-event → detail-page intake + skill-runs refresh so derivePhase flips to review/decomposed without a manual reload"
affects: [phase-08-plan-03-infra-timeout, combined-7+8-UAT, phase-09-gcs, phase-10-notifications]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "fetch + ReadableStream SSE reader (Web APIs only, D-02) — Bearer header via the shared currentIdToken source, never EventSource (D-01), never a token in the URL"
    - "SSE-first with silent poll fallback (D-07a): backoff x3 then hand off to the pre-existing tested 5s poll so the UI never goes blind"
    - "Frozen-contract hook swap: internals change (poll → SSE) while the { data } return + second _forcePoll arg stay byte-for-byte identical so callers need zero edits"
    - "Terminal-status useRef guard: each terminal run drives exactly one intake/runs re-fetch (no render loop)"

key-files:
  created:
    - frontend/src/lib/api/skillRunStream.ts
  modified:
    - frontend/src/lib/api/client.ts
    - frontend/src/lib/api/skillRuns.ts
    - frontend/src/components/intake/SkillRunProgress.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx

key-decisions:
  - "Reused the exact apiFetch token source (currentIdToken) rather than forking the transport; apiFetch itself buffers via resp.text() and cannot stream (RESEARCH anti-pattern)"
  - "Extracted the existing 5s poll block into startPoll() verbatim so it serves as both the _forcePoll path and the SSE onFallback — zero behavior change to the tested fallback"
  - "Threaded intake?.id into useSkillRunFull (3-arg signature) because the space-scoped full-run read needs the intake id; only the one call site changed"
  - "Terminal-refresh wiring lives in the route (D-09), not the hook, keeping the hook contract frozen with no new callback param"

patterns-established:
  - "Pattern: hand-rolled fetch/ReadableStream SSE reader with backoff→poll-fallback, return-no-throw (failures surface via onFallback callback)"
  - "Pattern: frozen external hook contract with swapped internals for transport migration"

requirements-completed: [API-04]

# Metrics
duration: ~40min
completed: 2026-07-13
---

# Phase 8 Plan 02: Frontend SSE Reader + Hook Swap Summary

**SSE-first useActiveSkillRun via a hand-rolled fetch/ReadableStream reader (Bearer header, no EventSource, no new dep) with the tested 5s poll retained as a silent fallback, plus an un-stubbed useSkillRunFull so the terminal stream event drives a working AIReviewPanel and a live phase flip to review/decomposed.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-07-13 (worktree parallel executor)
- **Completed:** 2026-07-13
- **Tasks:** 3
- **Files modified:** 4 (+1 created)

## Accomplishments
- New `openSkillRunStream` SSE reader: `fetch` + `resp.body.getReader()` + `TextDecoder`, frames on `\n\n`, takes `data:` lines, ignores `:` heartbeats, JSON-parses each frame, calls `onEvent`, stops on `succeeded`/`failed`. Reconnect-with-backoff (1s/2s/4s ×3) then silent `onFallback`; 404/401 stop cleanly. `AbortController` cleanup. Surfaces every failure via `onFallback`, never throws.
- `useActiveSkillRun` is now SSE-first behind its **unchanged** external contract (`{ data }` + second `_forcePoll` arg); the pre-existing 5s poll block is retained verbatim as `startPoll()` and used as the `_forcePoll`/`onFallback` path. `toActiveSkillRun` reused unchanged to map events.
- `useSkillRunFull` un-stubbed (D-08): 3-arg `(intakeId, skillRunId, enabled)` fetch of the new `getSkillRunFull` seam read returning `{ id, output_parsed, cost_estimate_usd }`; return-no-throw, `{ data }` shape preserved.
- Detail route threads `intake?.id` into `useSkillRunFull` and adds a terminal-refresh `useEffect` (D-09): on `activeRunStatus` becoming terminal for a not-yet-refreshed run, calls `load()` + `loadSkillRuns()` so `derivePhase` flips without a manual reload; guarded by a `useRef` so each run refreshes exactly once.

## Task Commits

Each task was committed atomically:

1. **Task 1: Seam layer — export currentIdToken, new skillRunStream.ts reader, getSkillRunFull** - `a871cb1` (feat)
2. **Task 2: SkillRunProgress.tsx — SSE-first useActiveSkillRun + un-stubbed useSkillRunFull** - `a754aef` (feat)
3. **Task 3: detail route — terminal-refresh wiring + useSkillRunFull call-site** - `eb7eb6d` (feat)

_Task 1's commit includes a Prettier line-wrap of the exported `currentIdToken` signature (see Deviations)._

## Files Created/Modified
- `frontend/src/lib/api/skillRunStream.ts` (created) - Hand-rolled fetch/ReadableStream SSE reader with Bearer auth, backoff, and poll fallback.
- `frontend/src/lib/api/client.ts` - Exported `currentIdToken` so the reader reuses the identical token source (never fork the transport).
- `frontend/src/lib/api/skillRuns.ts` - Added `SkillRunFull` type + `getSkillRunFull` short read over `apiFetch`.
- `frontend/src/components/intake/SkillRunProgress.tsx` - SSE-first `useActiveSkillRun` (poll retained as fallback) + un-stubbed `useSkillRunFull`.
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` - 3-arg `useSkillRunFull` call site + terminal-refresh `useEffect`.

## Decisions Made
- **Never fork the transport:** reused only `currentIdToken` + `apiUrl`, not `apiFetch` (which buffers via `resp.text()` and cannot stream).
- **Poll preserved verbatim:** the tested 5s poll became `startPoll()` with `MAX_POLL_MS` and the `running`/`queued` stop condition intact — it is now the `_forcePoll` and `onFallback` path.
- **Hook contract frozen:** the terminal → detail-refresh wiring lives in the route (D-09), so `useActiveSkillRun` gained no new callback param; callers need zero edits.
- **useSkillRunFull signature:** intentionally changed to 3-arg to thread `intake?.id` (the only breaking change, absorbed by the single call site in the same plan).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Prettier line-wrap of the exported currentIdToken signature**
- **Found during:** Task 1 (export currentIdToken)
- **Issue:** Adding `export ` to the private `currentIdToken` signature pushed the line to 84 chars, which Prettier's function-declaration heuristic wraps across multiple lines. Left unwrapped it would be a new `prettier/prettier` lint error (the original private form was Prettier-clean).
- **Fix:** Applied Prettier's exact wrapping to the exported signature (`export async function currentIdToken(\n  forceRefresh = false,\n): Promise<string | null> {`).
- **Files modified:** frontend/src/lib/api/client.ts
- **Verification:** `prettier --write` on a copy of the current file leaves the `currentIdToken` block untouched; the only remaining Prettier findings in client.ts are pre-existing lines I never touched.
- **Committed in:** a871cb1 (folded into Task 1)

**2. [Rule 3 - Blocking] Worktree line-ending + missing node_modules for verification**
- **Found during:** Task 1 verification (running tsc/eslint)
- **Issue:** The worktree had no `frontend/node_modules` (deps live only in the main repo), and the tracked source is stored LF but checked out CRLF on this Windows machine — so eslint reported the whole file as `Delete ␍` noise, masking real issues.
- **Fix:** Junctioned the main repo's `frontend/node_modules` into the worktree for the tsc/eslint runs (removed afterward), and LF-normalized my touched files in the working tree (git stores them as LF anyway, so the committed blobs are unchanged). This let me confirm zero *new* real Prettier/ESLint errors against the LF baseline.
- **Files modified:** none (tooling/verification only; junction removed post-verification)
- **Verification:** `tsc --noEmit` exits 0; `prettier --check` clean on the new `skillRunStream.ts`; per-file Prettier diffs confirm no new violations in my edits.
- **Committed in:** n/a (no source change)

---

**Total deviations:** 2 auto-fixed (1 formatting bug, 1 blocking-environment).
**Impact on plan:** Both necessary for a clean typecheck/lint. No scope creep — the three planned tasks landed exactly as specified.

## Issues Encountered
- **`.planning/` is gitignored (repo convention, local-only PLAN/RESEARCH files).** The 08-02 PLAN/CONTEXT/RESEARCH/PATTERNS files did not exist in the worktree checkout; they were read from the main-repo working tree for context. This SUMMARY is force-added (`git add -f`) to satisfy the commit requirement, mirroring how the tracked `.planning` docs (PROJECT/ROADMAP/STATE) are force-tracked.

## User Setup Required
None - no external service configuration required (Web APIs only, no dependency added; D-02 — `frontend/package.json` unchanged).

## Next Phase Readiness
- Frontend SSE reader + un-stubbed full-run read are in place; the run → stream → review-panel → accept/reject → context-pack → `decomposed` walk is now wired end-to-end on the client side.
- **Depends on 08-01 (backend SSE + full-run endpoints)** and **08-03 (Cloud Run 900s timeout)** being deployed for the live combined 7+8 UAT (D-10). Until deployed, the poll fallback is the guaranteed floor (the UI degrades silently, never blind).
- Live SSE cadence / `output_parsed` load / phase flip are verified in the combined 7+8 UAT, not in automated tests (author-by-construction; no local Python/Docker/backend).

## Self-Check: PASSED

- Created file `frontend/src/lib/api/skillRunStream.ts` — FOUND
- Task commits `a871cb1`, `a754aef`, `eb7eb6d` — all FOUND in git log
- `tsc --noEmit` — exit 0 (typecheck clean)
- `frontend/package.json` diff vs base — none (D-02: no new dependency)

---
*Phase: 08-sse-skill-run-progress*
*Completed: 2026-07-13*
