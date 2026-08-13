---
status: awaiting_human_verify
trigger: "one problem that needs fixing when refreshing anypage it starts logging in again and switches to home page, also deep research timer not resetting is good but the others still reset"
created: 2026-08-12
updated: 2026-08-13
---

# Debug: refresh bounces to login+home, and the skill-run clock resets

TWO separate defects reported together. They are independent, but defect A **confounds observation
of** defect B, so A should be fixed first or the operator cannot cleanly see B.

## Symptoms (operator, verbatim where quoted)

- **A —** *"when refreshing anypage it starts logging in again and switches to home page"*
  - Expected: refreshing an admin page keeps you signed in and ON THAT PAGE.
  - Actual: a login flash, then you land on `/admin` (home) instead of the page you were on.
  - Timeline: **"it's been there a while"** — predates Phase 22, seen on earlier phases too.
  - Reproduce: sign in as superadmin, open any `/admin/...` page, press refresh.
- **B —** *"deep research timer not resetting is good but the others still reset"*
  - Operator confirmed which clock: **the AI skill-run clock on the intake detail page.**
  - Expected: like the run page's deep-research clock, it should show real elapsed time and survive
    a refresh.
  - Actual: it restarts from 00:00.
  - The run page's own deep-research elapsed is CORRECT and must not be touched.

## Evidence already gathered (orchestrator, pre-session — all measured, not inferred)

- timestamp: 2026-08-12 — **A's mechanism proven against the LIVE deployment** with curl against
  `https://nestor-frontend-ybkr7metoq-ew.a.run.app`:
  - `GET /admin` → **307 → /auth/login**
  - `GET /admin/pulse/intakes` → **307 → /auth/login**
  - `GET /` → 307 → /admin
  The redirect is issued **by the SERVER**, so it is not a client-side race.
- timestamp: 2026-08-12 — cause of A located at `frontend/src/routes/admin.tsx`. The route's
  `beforeLoad` calls a local `authReady()` (lines ~9-18) and throws
  `redirect({ to: "/auth/login" })` when it resolves null. Under SSR (TanStack Start + Nitro on
  Cloud Run) `beforeLoad` runs **on the server**, where Firebase's session — held in browser
  IndexedDB — is invisible. So `onAuthStateChanged` fires with `null` server-side and the redirect
  always fires on a hard navigation/refresh. The client then rehydrates, `auth.login.tsx` sees a
  live session and navigates to `landingPathForRole(role)` → `/admin`. That is the "switches to home
  page" half. The guard's own comment says it is **"UX gating only — the authoritative control is
  the backend"**, so skipping it server-side removes no real protection.
- timestamp: 2026-08-12 — **B's root cause located** at
  `frontend/src/components/intake/SkillRunProgress.tsx:32`, inside `toActiveSkillRun`:
  `triggered_at: r.applied_at ?? r.completed_at ?? new Date().toISOString()`
  For a RUNNING skill run BOTH `applied_at` and `completed_at` are null, so it falls back to
  wall-clock **now**. Two consequences:
  1. every mount (incl. after a refresh) starts the clock at 00:00;
  2. every SSE event re-maps the snapshot, producing a NEW timestamp, which changes the
     `[triggeredAt]` dependency of the `useEffect` in `RunningClock`
     (`components/intake/NextStepBanner.tsx:118-126`) and **restarts the clock on every event**.
  The comment at lines 22-24 already concedes the cause: *"The view does not project a trigger
  timestamp, so we fall back to the applied/completed markers."*
- timestamp: 2026-08-12 — **a real timestamp DOES exist**, it is simply not projected.
  `backend/app/db/models/skill_run.py` has **`created_at` (line ~57) and `started_at` (line ~60)**,
  but `SkillRunView` (`backend/app/api/intake_routes.py:162-176`) projects only
  `id / skill / status / applied_at / completed_at`. The frontend `SkillRun` type
  (`frontend/src/lib/api/skillRuns.ts:17-23`) mirrors that narrow shape.
  ⭐ This is the SAME seam fix Phase 15.2-24 already did for the deep-research run — it carried
  `started_at` across so `useElapsed` could derive from it, which is exactly why the run page's
  clock is correct. It was never done for skill runs.
- timestamp: 2026-08-12 — **exhaustive timer sweep**: only 4 `setInterval` calls exist in
  `frontend/src`, and **no mount-counter timer remains anywhere**:
  `lib/research/runClock.ts:52` (`useElapsed`, derives from `run.started_at` — CORRECT, the good
  one), `components/intake/NextStepBanner.tsx:123` (`RunningClock`, fed the poisoned
  `triggered_at`), `components/intake/SkillRunProgress.tsx:239` (same pattern, but this component
  **is not rendered anywhere** — dead), `components/research/RunFeed.tsx:135` (blinking cursor, not
  a clock). Stage "Worked for X" durations come from server-supplied `meta.worked`, not a client
  timer.

## Evidence — this session (second-cause sweep)

- timestamp: 2026-08-13 — ⭐ **A HAS A SECOND LOCUS. There are FIVE guard sites, not one.**
  Byte-identical `authReady()` + `throw redirect({ to: "/auth/login" })` at:
  `routes/admin.tsx:24-30`, `routes/intake.index.tsx:48-54`, `routes/intake.$id.tsx:31-37`,
  `routes/intake.$id.results.tsx:35-41`, `routes/intake.$id.report.tsx:33-39`.
  Fixing only `admin.tsx` (all the debug file located) would leave EVERY `/intake/*` route — the
  regular-user surface — still bouncing on refresh; `/intake/$id/report` trips TWO guards
  (parent + child). This is the answer to the second-cause question for A: same mechanism,
  four additional loci.
- timestamp: 2026-08-13 — **stale cached SPA bundle ELIMINATED as a contributor to A.**
  Zero `Cache-Control` / `routeRules` / `maxAge` / `immutable` config anywhere in `frontend/`
  (only an unrelated sidebar cookie `max-age`); zero CDN / `backend_bucket` / `url_map` /
  load-balancer in `infra/`. `frontend/Dockerfile` runs Nitro `node-server` on Cloud Run, so the
  HTML shell is rendered per request and assets are Vite content-hashed. **Decisive: the 307 was
  measured with curl, which has no cache at all** — a cold, cacheless client still gets the
  redirect, so cache cannot be a cause.
- timestamp: 2026-08-13 — **no server middleware exists.** Zero `createMiddleware` /
  `createServerFn` / `registerGlobalMiddleware` / `defineEventHandler` in `frontend/src`
  (the only `createStart` hit is a type import in the generated `routeTree.gen.ts`).
  `routes/__root.tsx` has NO `beforeLoad`/`loader`. So the five route guards are the complete
  server-side redirect surface, plus the by-design `/` → `/admin` at `routes/index.tsx:4-6`.
- timestamp: 2026-08-13 — the "switches to home page" half has **TWO** redirectors, both
  client-side, neither preserving the original path: `routes/__root.tsx:92-107` (`AuthRedirector`)
  and `routes/auth.login.tsx:51-53`. Both call `landingPathForRole(role)`. They are NOT an
  independent cause (only reachable once a guard has already dumped you on `/auth/login`), but
  they are why the landing is `/admin` and not the page you refreshed.
- timestamp: 2026-08-13 — ⛔ **`skill_runs.started_at` IS NEVER WRITTEN.**
  `db/ai_session.py:178-190` (`create_running_skill_run`) inserts only
  `intake_id / skill / status / llm_model / prompt_system / prompt_user`. No finalize path writes
  it either: every `started_at` write in `backend/app` targets **`research_runs`**
  (`research/run_task.py:373-375` and `:434-436`), and `db/stream_session.py:128` reads it off
  `ResearchRunRepository` — a DIFFERENT table. Projecting `started_at` would therefore return
  **null for every skill run** and the clock would have nothing to count from.
- timestamp: 2026-08-13 — **`created_at` is the only viable field**, and is correct on the merits:
  `models/skill_run.py:57-59` — `server_default=func.now()`, `nullable=False`, stamped by
  Postgres at INSERT, i.e. exactly at dispatch. Corroborated by existing code that already
  treats it as the run's start: `db/ai_session.py:211`, `sweep_orphaned_skill_runs`, ages a
  stuck `running` row with `SkillRun.created_at < cutoff`.
- timestamp: 2026-08-13 — ❌ **A CLAIM IN THIS FILE IS WRONG.** The line "This is the SAME seam fix
  Phase 15.2-24 already did for the deep-research run — it carried `started_at` across" is a
  **false precedent**. That fix was on `research_runs`, where `started_at` genuinely is written.
  For `skill_runs` it is a dead column. The seam-fix *shape* transfers; the *field name* does not.
- timestamp: 2026-08-13 — **`ActiveSkillRun.triggered_at` has FOUR consumer groups, not one:**
  1. `NextStepBanner.tsx:185,200,252` → `RunningClock` (the reported defect);
  2. `admin.pulse.intakes.$id.tsx:271` — the OPTIMISTIC run object;
  3. `admin.pulse.intakes.$id.tsx:279` + `:293` — the optimistic-**release guard**
     `if (optimisticRunStartedAt && activeRunTriggeredAt < optimisticRunStartedAt) return;`
  4. `admin.pulse.intakes.$id.tsx:590/613/621/1671` — a SEPARATE **local** `SkillRun` type
     (declared `:119-130`, unrelated to `ActiveSkillRun`) driving the history list's sort key and
     displayed timestamp.
- timestamp: 2026-08-13 — ⛔ **REGRESSION RISK that forbids the obvious one-line fix.** Repurposing
  `triggered_at` to carry `created_at` would make the guard at `:293` compare a **Postgres clock**
  (`created_at`) against a **browser clock** (`optimisticRunStartedAt`, set via `new Date()` at
  `:651` and `:775`). If the browser clock runs AHEAD of Cloud SQL by any amount, the newly
  dispatched run's `created_at` is `< optimisticRunStartedAt`, the guard never releases,
  `setSkillLoading(false)` never fires → `skillLoading` stuck true → `_forcePoll` pins the 5s poll
  for the full 10-min `MAX_POLL_MS` cap and the dispatch CTAs stay disabled. Direction of skew is
  ~50/50 by chance. **Therefore `triggered_at` must NOT be repurposed** — the real start timestamp
  goes in a NEW, distinct `created_at` field and `triggered_at` keeps its exact current value, so
  the release guard's behaviour is bit-for-bit unchanged.
- timestamp: 2026-08-13 — history-list side defect (same root cause, `:590`):
  `triggered_at: r.applied_at ?? r.completed_at ?? ""` yields `""` for a RUNNING run. `""` sorts
  first in the ascending `localeCompare` at `:621`, and the Sheet renders `[...runs].reverse()`,
  so the in-flight run is displayed LAST in a newest-first list, timestamped `—`
  (`fmt("")` → `!d` → `"—"`, `:198-205`).
- timestamp: 2026-08-13 — pre-existing, OUT OF SCOPE, noted only: the skill-run SSE frame
  (`db/stream_session.py:75-80`) omits `skill`, though `lib/api/skillRuns.ts:17-23` declares it.
  So `activeRun.skill` is `undefined` on SSE-sourced snapshots. Not touched.
- timestamp: 2026-08-13 — **gate baselines measured at HEAD before any edit**: `npx tsc --noEmit`
  0 errors (exit 0); `npx vitest run` 77 passed / 7 files; `node scripts/i18n-audit.mjs` PASS,
  A/B/C clean, 107 CHECK D advisories. Matches the stated true baseline exactly.

## Eliminated

- hypothesis: "a stale cached SPA bundle contributes to defect A" — ELIMINATED. No cache headers,
  no CDN, no LB; per-request SSR; and the 307 was reproduced with curl, which has no cache.
- hypothesis: "some OTHER route or middleware also redirects server-side" — **NOT eliminated —
  CONFIRMED.** Four additional `/intake/*` guards do exactly this. No middleware, however.
- hypothesis: "`started_at` is a viable field to project for skill runs (per the Phase 15.2-24
  precedent)" — ELIMINATED. It is never written for `skill_runs`; it would project null.
- hypothesis: "a mount-counter timer (`useState(0)` + increment) still exists somewhere" —
  ELIMINATED. Swept all of `frontend/src`; zero mount-counter timers. Every clock derives from a
  timestamp; the defect is the *value* of that timestamp, not the counting method.
- hypothesis: "defect A is a client-side race between the guard and Firebase rehydration" —
  ELIMINATED. The 307 is emitted by the server before any client JS runs.
- hypothesis: "Firebase auth persistence is misconfigured" — ELIMINATED as the cause of A.
  `lib/firebase.ts` uses default `getAuth()`, i.e. `browserLocalPersistence`, and the session DOES
  survive (the client restores it and redirects to `/admin`, which is only possible with a live
  session). The server simply cannot see it.

## Current Focus

hypothesis: >
  A: `admin.tsx`'s `beforeLoad` auth guard runs during SSR where the Firebase session is
  structurally invisible, so it always redirects; the client then rehydrates and lands on `/admin`.
  B: `toActiveSkillRun` synthesises `triggered_at` from `new Date()` because the backend
  `SkillRunView` never projects the `created_at`/`started_at` that already exist on the model.
test: >
  A: make the guard client-only and confirm `GET /admin/pulse/intakes` no longer 307s server-side,
  and that a browser refresh stays on the page. Confirm an unauthenticated visitor still reaches
  login and a non-superadmin still gets the denial wall (both must not regress).
  B: project a start timestamp through `SkillRunView` → `SkillRun` → `toActiveSkillRun`, then
  confirm the intake skill clock shows true elapsed, survives a refresh, and does NOT restart on
  each SSE event.
expecting: >
  A: no server-side redirect for admin routes; refresh preserves location.
  B: clock counts from the run's real start; stable across refresh and across SSE events.
next_action: >
  Second-cause question ANSWERED (see "Evidence — this session"). A: one mechanism, FIVE loci —
  fix all five. B: no second cause for the reset, but the naive fix would regress the optimistic
  release guard, so add a distinct field. Now apply both fixes, then re-run the three gates.

reasoning_checkpoint:
  hypothesis: >
    A: a single mechanism at FIVE loci. `beforeLoad` runs during SSR (Nitro `node-server`), where
    the Firebase session lives in browser IndexedDB and is structurally invisible, so `authReady()`
    resolves null and the server emits a 307 to /auth/login on every hard load of /admin/** and
    /intake/**. The client then rehydrates, finds a live session, and AuthRedirector /
    LoginPage send it to landingPathForRole(role) = /admin — losing the original path.
    B: `RunningClock`'s start comes from `ActiveSkillRun.triggered_at`, which
    `toActiveSkillRun` synthesises as `new Date()` for any run that is still running (both
    `applied_at` and `completed_at` are null then). The real start (`skill_runs.created_at`)
    exists on the model but is not projected through `SkillRunView` / `read_latest_run_dict`.
  confirming_evidence:
    - "curl against the live frontend returns 307 → /auth/login for /admin and /admin/pulse/intakes — server-emitted, cacheless client."
    - "Five byte-identical guard bodies read directly: admin.tsx:24-30, intake.index.tsx:48-54, intake.$id.tsx:31-37, intake.$id.results.tsx:35-41, intake.$id.report.tsx:33-39."
    - "vite.config.ts sets nitro preset node-server and Dockerfile CMDs `node .output/server/index.mjs` — SSR is real, so beforeLoad genuinely executes server-side."
    - "SkillRunProgress.tsx:32 is `triggered_at: r.applied_at ?? r.completed_at ?? new Date().toISOString()`; both markers are null while running."
    - "SkillRunView (intake_routes.py:162-176) and read_latest_run_dict (stream_session.py:75-80) both project only id/skill?/status/applied_at/completed_at — no start timestamp."
    - "models/skill_run.py:57-59 gives created_at a NOT NULL server_default=func.now(); ai_session.py:178-190 never writes started_at."
  falsification_test: >
    A would be disproven if a request carrying a valid session cookie/header still 307'd after the
    guards are made client-only, or if a route with NO guard also 307'd (it does not — /auth/login
    and /intake/* pre-fix behaviour match the guard map exactly).
    B would be disproven if the clock still restarted once fed a stable per-run timestamp — i.e. if
    some other dependency of RunningClock's useEffect changed per event. The effect's only
    dependency is the start timestamp, so a stable value cannot restart it.
  fix_rationale: >
    A: the guard's own comment states it is "UX gating only — the authoritative control is the
    backend", so declining to evaluate it on the server removes no real protection. Skipping it
    under SSR removes the false negative at its source; a client-side <RequireAuth> gate restores
    the genuine signed-out redirect AFTER Firebase has settled, where the session is actually
    visible. Root cause, not symptom: nothing downstream (AuthRedirector, login landing) is
    touched, because with the false redirect gone those paths are never entered on refresh.
    B: project the real `created_at` end-to-end and count from it. Root cause is the missing
    projection, so the fix is the projection — not clamping the clock or memoising the timestamp.
    It is added as a NEW field rather than by repurposing `triggered_at`, because `triggered_at`
    is also the input to a browser-clock comparison at :293 that would deadlock on clock skew.
  blind_spots:
    - "Cannot verify in a browser: no session credentials, and DO NOT DEPLOY is in force. The server-side half of A is provable by code+curl; the 'refresh stays on the page' half is only provable by the operator after a redeploy."
    - "Cannot observe a live running skill run without triggering one (~$45 ban applies to research runs; a skill run is cheap but still a real Claude call, so not exercised). B's fix is verified by code path + types + gates, not by watching the clock tick."
    - "No test exists for RunningClock or for the guards — the frontend suite (77 tests) covers only lib/ pure functions, so the gates cannot regression-catch either fix. Backend pytest not run this session; the SkillRunView change is an additive Pydantic field with a default and no test asserts exact key sets."
    - "Whether TanStack Start re-runs beforeLoad on the client after hydration is assumed NOT to happen (hence the component gate). If it does re-run, the result is a redundant but harmless second check."

## Resolution

root_cause: >
  A — ONE mechanism at FIVE loci. `beforeLoad` runs during SSR (Nitro `node-server` on Cloud Run),
  where the Firebase session lives in browser IndexedDB and is structurally invisible, so
  `onAuthStateChanged` resolved null server-side and the guard emitted a 307 to `/auth/login` on
  every hard load of `/admin/**` and `/intake/**`. The client then rehydrated, found a live
  session, and `AuthRedirector` / `LoginPage` navigated to `landingPathForRole(role)` — which is
  both the "logs in again" flash and the "switches to home page" landing. NOT a cache issue, NOT a
  client race, NOT Firebase persistence.
  B — `toActiveSkillRun` synthesised the clock's start as
  `applied_at ?? completed_at ?? new Date().toISOString()`. Both markers are null while a run is
  RUNNING, so it collapsed to wall-clock now: a NEW value on every re-map, which changed
  `RunningClock`'s effect dependency on every SSE event and every 5s poll (≈ reset every 5s) and on
  every mount (so it never survived a refresh). The real start existed on the model
  (`skill_runs.created_at`) but was projected by neither read path.

fix: >
  A — new `frontend/src/lib/auth-guard.tsx` as the ONE guard definition:
  `requireAuthBeforeLoad()` no-ops under SSR (`typeof window === "undefined"`) and still guards
  client-side navigations; `useRequireAuth()` / `<RequireAuth>` re-establish the real signed-out
  redirect post-hydration. All five duplicate route copies deleted and converted. Plus a regression
  guard in `lib/auth-context.tsx`: `loading` now settles only once the role-claim read finishes
  (via `.finally()`), because with the SSR redirect gone a superadmin refreshing `/admin` would
  otherwise arrive at `loading:false, role:null` and flash the in-place denial wall.
  B — project `skill_runs.created_at` through BOTH read paths (`SkillRunView`/`_skill_run_view`
  AND the hand-built SSE dict in `db/stream_session.py`), carry it as a NEW
  `ActiveSkillRun.created_at`, and feed `RunningClock` from it. `triggered_at` deliberately
  UNCHANGED — it is also the input to the optimistic-release guard that compares against a browser
  clock, so repurposing it would deadlock on clock skew. Old chain kept as last fallback for
  independent frontend/backend deploys. History-list mapping fixed for the same missing projection.

verification: >
  Gates measured BEFORE and AFTER, identical — `npx tsc --noEmit` 0 errors (exit 0);
  `npx vitest run` 77 passed / 7 files; `node scripts/i18n-audit.mjs` PASS, A/B/C clean, 107 CHECK D
  advisories. Backend files pass `py_compile`. Sweep confirms zero residual `authReady` /
  `onAuthStateChanged` in `src/routes/` (only the one shared module) and all five routes now read
  `beforeLoad: requireAuthBeforeLoad`. `routeTree.gen.ts` untouched.
  ⛔ NOT verified live — DO NOT DEPLOY was in force and no research run was triggered. Neither "a
  refresh stays on the page" nor "the clock counts true elapsed" has been observed in a browser;
  both need the operator to redeploy and walk it. No test covers `RunningClock` or the guards (the
  77 tests are all `lib/` pure functions), so the gates cannot regression-catch either fix.

files_changed:
  - frontend/src/lib/auth-guard.tsx (NEW — the one guard definition)
  - frontend/src/lib/auth-context.tsx (settle `loading` after the claim read)
  - frontend/src/routes/admin.tsx (locus 1 → shared guard + `checking`)
  - frontend/src/routes/intake.index.tsx (locus 2)
  - frontend/src/routes/intake.$id.tsx (locus 3)
  - frontend/src/routes/intake.$id.results.tsx (locus 4)
  - frontend/src/routes/intake.$id.report.tsx (locus 5)
  - backend/app/api/intake_routes.py (SkillRunView + _skill_run_view project created_at)
  - backend/app/db/stream_session.py (SSE frame projects created_at — the second read path)
  - frontend/src/lib/api/skillRuns.ts (seam type += created_at, optional for deploy skew)
  - frontend/src/components/intake/SkillRunProgress.tsx (ActiveSkillRun += created_at)
  - frontend/src/components/intake/NextStepBanner.tsx (RunningClock counts from startedAt)
  - frontend/src/routes/admin.pulse.intakes.$id.tsx (optimistic created_at + history sort key)

commits:
  - 172aa8d fix: stop the SSR auth guard bouncing every refresh to login then home
  - 3b7ae82 fix: project skill_runs.created_at so the AI skill clock stops resetting
  - branch: fix/refresh-ssr-guard-and-skill-clock (NOT merged to master — operator's call)

redeploy_surface_required_to_observe:
  - nestor-frontend — carries BOTH fixes' frontend halves (guard + clock). Defect A is
    frontend-only, so this alone resolves the refresh bounce.
  - nestor-api — carries B's projection. WITHOUT it the frontend falls back to the old
    applied/completed/`new Date()` chain, so the clock keeps resetting: B needs BOTH services.
    Order is safe either way (the field is optional on the frontend seam).
  - Derive the surface by IMPORT before deploying (infra/DEPLOY-RUNBOOK.md § Phase 22) — do not
    trust substring matching.

## Constraints carried into any fix

- ⛔ Do NOT alter the run page's deep-research clock (`lib/research/runClock.ts::useElapsed`) — the
  operator confirmed it is correct. There must remain exactly ONE clock definition; do not add a
  second.
- ⛔ Do NOT trigger a research run (~$45, unauthorized).
- Any frontend fix needs a redeploy of `nestor-frontend` to be observable; a backend projection
  change also needs `nestor-api`. Derive the deploy surface by IMPORT, never by substring —
  see `infra/DEPLOY-RUNBOOK.md` § Phase 22.
- Phase 22's UAT (`22-UAT.md`) is unrun and waiting; defect A makes walking it painful, so A is the
  higher priority of the two.
