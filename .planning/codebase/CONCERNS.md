# Codebase Concerns

**Analysis Date:** 2026-06-18

---

## Security Issues (Inherited — Must Fix Before Production)

### #1 — No Real Tenant Isolation (Critical)

- **Issue:** The original Supabase RLS policies on `nestor.intakes`, `nestor.intake_answers`, `nestor.research_artifacts`, and `nestor.findings` are `USING (true) WITH CHECK (true)` for the `authenticated` role. Any logged-in user can read and write every client's data across all organizations.
- **Files:** `docs/PROVENANCE.md` (issue #1), `docs/BACKEND-MAP.md` (tables list)
- **Impact:** Complete cross-tenant data exposure. Admin user A can read and mutate Admin user B's client data. This is the #1 driver for the re-platform.
- **Fix approach:** Replace Supabase RLS with Cloud SQL per-tenant row filtering enforced at the FastAPI API layer (`backend/` — not yet built). All queries must be scoped to `org_id` via the authenticated user's membership. Reference the `MOELD/Nestor` worker_user/tenant_id pattern per `docs/PROVENANCE.md`.

### #2 — Anon Key Has Broad Write Grants (Critical)

- **Issue:** In the original Supabase project, the `anon` role (public browser key, no login required) has `INSERT`, `UPDATE`, `DELETE`, and `TRUNCATE` grants on 11 tables. This means unauthenticated actors can write to the database using the publicly visible anon key.
- **Files:** `docs/PROVENANCE.md` (issue #2)
- **Impact:** Any actor with the browser-visible `VITE_SUPABASE_ANON_KEY` (extractable from the built JS bundle) can directly manipulate production data.
- **Fix approach:** The new GCP API layer (`backend/`) must mediate ALL data access. No direct PostgREST/Supabase access from the browser for write operations. Remove anon grants entirely from Cloud SQL.

### #3 — Bearer-Link Client Access Model (High)

- **Issue:** Client access to intake forms, validation, and results currently relies on 32-character never-expiring, non-revocable bearer tokens (`client_intake_token`, `client_validation_token`, `client_results_token` columns on `nestor.intakes`). These are emailed to clients and grant full access indefinitely if the link is leaked or forwarded.
- **Files:** `docs/PROVENANCE.md` (issue #3), `frontend/src/routes/intake.$token.tsx`, `frontend/src/routes/results.$token.tsx`, `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 1408–1428 — token regeneration logic)
- **Impact:** No session expiry, no revocation, no audit trail. A leaked results link gives permanent access to the research deliverable.
- **Fix approach:** Replace with authenticated "spaces" model using Identity Platform sessions. Email becomes notification-only ("your results are ready — log in to view"). Per `docs/PROVENANCE.md`, a narrow tokenized path MAY be preserved only for bulk/anonymous respondents where login is impractical — this is a deliberate product decision, not an oversight.
- **Current token regeneration residue:** `ResultsLinkRow` in `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 1383–1459) allows admins to regenerate results tokens client-side via direct Supabase update — this must be removed or ported to the backend API.

### #4 — Admin UI Auth Guard Is Client-Side Only (High)

- **Issue:** All `/admin/*` routes are protected only by client-side session checks via `useAuth()` from `frontend/src/lib/auth-context.tsx`. There are no `beforeLoad` guards that verify session before rendering. The `AuthRedirector` component in `frontend/src/routes/__root.tsx` (lines 86–97) only redirects from login page when a session exists — it does NOT redirect unauthenticated users away from admin pages.
- **Files:** `frontend/src/routes/__root.tsx`, `frontend/src/lib/auth-context.tsx`, `frontend/src/routes/admin.pulse.intakes.index.tsx`, `frontend/src/routes/admin.pulse.clients.tsx`, `frontend/src/routes/admin.pulse.intakes.new.tsx`
- **Impact:** Unauthenticated browser access to `/admin/pulse/intakes` will attempt Supabase queries with no session. In the original setup this queries PostgREST with the anon key and receives data (due to concern #2 above). In the new setup this must be blocked server-side or via proper `beforeLoad` route guards.
- **Fix approach:** Add `beforeLoad` auth guards to the `/admin` route tree that redirect to `/auth/login` when no session is present. Move auth enforcement to the FastAPI backend for all API calls.

### #5 — Hardcoded Email Allowlist in Login Page (Medium)

- **Issue:** `frontend/src/routes/auth.login.tsx` contains a hardcoded allowlist of permitted email addresses (`ALLOWED_EXPLICIT`) alongside the `ALLOWED_DOMAINS` array. A specific personal Gmail address is currently in `ALLOWED_EXPLICIT`.
- **Files:** `frontend/src/routes/auth.login.tsx` (lines 10–13)
- **Impact:** This is a client-side guard only — it can be bypassed by calling Supabase auth APIs directly. It also requires a code change to add or remove users, which is not scalable and risks leaking personal email addresses in git history.
- **Fix approach:** Remove `ALLOWED_EXPLICIT` from client-side code. Enforce access control at the Supabase `auth.callback` level (already partially done via `user_organization_ids` RPC check in `frontend/src/routes/auth.callback.tsx`) and fully at the Identity Platform / FastAPI layer in the new stack.

### #6 — Supabase Anon Key Exposed in JS Bundle (Medium)

- **Issue:** `VITE_SUPABASE_ANON_KEY` and `VITE_SUPABASE_URL` are baked into the client-side bundle at build time (Vite `import.meta.env`). The anon key is visible to any browser that loads the app. This is by design in Supabase's architecture but is a risk when combined with concern #2 (anon write grants).
- **Files:** `frontend/src/lib/supabase.ts`, `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 140–141 — SUPABASE_ANON_KEY also extracted explicitly for edge function fetch calls), `frontend/.env` (file present, not tracked by git per root `.gitignore`)
- **Impact:** As long as anon write grants exist on the Supabase project, the key is a direct attack vector. After migration the new GCP API uses Identity Platform tokens — no Supabase key will be in the bundle.
- **Fix approach:** The new frontend will call the FastAPI backend with Firebase ID tokens. Remove the Supabase client entirely once migration is complete.

### #7 — Edge Function Invocation Uses Anon Key as Fallback Bearer (Medium)

- **Issue:** In `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 483–491), `apply-intake-skill` is invoked via raw `fetch` with `Authorization: Bearer ${session?.access_token ?? SUPABASE_ANON_KEY}`. If the session is missing, the anon key is sent as the bearer token — meaning the edge function can be invoked without a valid user session.
- **Files:** `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 477–514)
- **Impact:** An unauthenticated actor who knows the function URL can trigger LLM-powered edge functions, incurring cost. The Supabase edge function itself may or may not validate the token.
- **Fix approach:** In the new backend, all function invocations must require a valid Identity Platform ID token validated server-side. Remove the anon fallback.

---

## Migration Risk Surface — Supabase Coupling

### #8 — Supabase Client Pervasive Across Frontend (High Migration Risk)

- **Issue:** The Supabase client (`frontend/src/lib/supabase.ts`) is imported in 34 files across the frontend. Every data access pattern — RPC calls, PostgREST table queries, storage operations, edge function invocations — goes through this client.
- **Files:** `frontend/src/lib/supabase.ts` (the client), plus all 34 importing files including:
  - `frontend/src/components/intake/AIReviewPanel.tsx`
  - `frontend/src/components/intake/IntakeForm.tsx`
  - `frontend/src/components/intake/ContextPackBlock.tsx`
  - `frontend/src/components/intake/FinalReportBlock.tsx`
  - `frontend/src/components/intake/ResearchArtifacts.tsx`
  - `frontend/src/components/intake/SkillRunProgress.tsx`
  - `frontend/src/components/admin/ClientDetailDrawer.tsx`
  - `frontend/src/components/admin/ClientFormModal.tsx`
  - `frontend/src/components/admin/ProductShell.tsx`
  - `frontend/src/routes/admin.pulse.intakes.$id.tsx`
  - `frontend/src/routes/admin.pulse.intakes.index.tsx`
  - `frontend/src/routes/admin.pulse.intakes.new.tsx`
  - `frontend/src/routes/admin.pulse.clients.tsx`
  - `frontend/src/routes/admin.pulse.clients.$id.tsx`
  - `frontend/src/routes/admin.pulse.search.tsx`
  - `frontend/src/routes/intake.$token.tsx`
  - `frontend/src/routes/results.$token.tsx`
  - `frontend/src/routes/auth.login.tsx`
  - `frontend/src/routes/auth.callback.tsx`
  - and 15+ more
- **Impact:** Migration to the new FastAPI backend requires replacing every Supabase call with fetch/API client calls. There is no data access abstraction layer — all queries are inline in route components and component files.
- **Fix approach:** Introduce a thin API client module (`frontend/src/lib/api.ts` or equivalent) that wraps fetch calls to the new FastAPI backend. Migrate call sites file by file. The `supabase.ts` null-safety guard (`url && key ? createClient(...) : null`) already provides a migration seam — the null path can be expanded as routes are ported.

### #9 — `supabasePublic` Alias Is a No-Op Wrapper (Low)

- **Issue:** `frontend/src/lib/supabase.ts` exports `supabasePublic` as an alias of `supabase`. The comment acknowledges it was meant for `public` schema queries but uses `.schema("public" as never)` call-site workarounds instead.
- **Files:** `frontend/src/lib/supabase.ts` (lines 22–23), `frontend/src/routes/admin.pulse.intakes.index.tsx` (imports `supabasePublic`)
- **Impact:** Confusing naming; the alias carries the same schema default (`nestor`) and forces `as never` type casts at call sites.
- **Fix approach:** Remove `supabasePublic` export once migration is underway. Schema disambiguation is a non-issue in the new backend.

### #10 — Auth Context Tied to Supabase GoTrue Session Type (Medium)

- **Issue:** `frontend/src/lib/auth-context.tsx` imports `Session` directly from `@supabase/supabase-js`. The `useAuth()` hook returns a Supabase-specific session object used across admin components.
- **Files:** `frontend/src/lib/auth-context.tsx`, `frontend/src/routes/admin.pulse.intakes.$id.tsx` (line 186 — reads `session.access_token`), `frontend/src/components/admin/ProductShell.tsx`, `frontend/src/routes/admin.index.tsx`
- **Impact:** Swapping to Identity Platform auth requires refactoring the auth context interface and every call site that uses `session?.user.email` or `session?.access_token`.
- **Fix approach:** Define a local `AuthSession` interface that abstracts the provider. Implement a Firebase ID token adapter behind the same `useAuth()` hook. Migration can be done in one pass on `auth-context.tsx` with minimal call-site changes.

---

## Tech Debt (Frontend)

### #11 — No Backend or Infra Built Yet (Critical Blocker)

- **Issue:** `backend/` and `infra/` directories exist but contain only `README.md` placeholder files. The FastAPI backend, Cloud SQL schema, Identity Platform config, and Cloud Run setup are entirely unbuilt.
- **Files:** `backend/README.md`, `infra/README.md`
- **Impact:** The frontend currently runs exclusively against the old Supabase project. The re-platform is at 0% on the backend side.
- **Fix approach:** Prioritize building in this order: Cloud SQL schema (porting `docs/db_functions.sql` + table definitions), FastAPI skeleton on Cloud Run, Identity Platform auth, then port edge functions one by one.

### #12 — Dutch-Only UI and Code Comments (Low-Medium)

- **Issue:** All user-facing strings, error messages, toast notifications, status labels, and many inline comments are in Dutch (`nl`). The codebase mixes Dutch UI strings with English code identifiers. `date-fns` locale is hardcoded to `nl`.
- **Files:** `frontend/src/routes/admin.pulse.intakes.$id.tsx` (pervasive — `STATUS_LABEL`, `STATUS_BANNER`, `STATUS_HINT` all Dutch), `frontend/src/routes/intake.$token.tsx` (error text Dutch), `frontend/src/routes/results.$token.tsx` (all Dutch), `frontend/src/routes/auth.login.tsx` (error messages Dutch), `frontend/src/lib/salesLabels.ts`, `frontend/src/lib/salesMail.ts`
- **Impact:** Only operators fluent in Dutch can maintain or debug UI errors. Makes internationalisation harder later. Per `docs/PROVENANCE.md` issue #5, language handling is a known open decision.
- **Fix approach:** If multi-language is required, extract strings to i18n keys. If Dutch-only is the deliberate product choice, document it explicitly and ensure error monitoring tooling handles Dutch strings.

### #13 — `findings` and `deliverables` Tables Unused (Low)

- **Issue:** Per `docs/PROVENANCE.md` issue #4, `nestor.findings` and `nestor.deliverables` tables contain 0 rows in the live project. The current final-report model uses `research_artifacts` referenced by `intakes.final_report_artifact_id`, not `deliverables`. The `findings` table schema is well-shaped for Tribunal's output (has `confidence`, `sources jsonb`, `reviewed_by`) but is never written to.
- **Files:** `docs/PROVENANCE.md` (issue #4), `docs/BACKEND-MAP.md` (findings/deliverables table descriptions and Tribunal contract section)
- **Impact:** The target Cloud SQL schema must make a deliberate decision on whether to include `findings` and `deliverables` or define a different model. Copying them blindly adds dead schema.
- **Fix approach:** Document the target data model for research outputs before building Cloud SQL migrations. The `findings` table design is worth keeping as the Tribunal output target (per `docs/BACKEND-MAP.md` Tribunal contract).

### #14 — Inline `confirm()` for Destructive Actions (Low)

- **Issue:** Several destructive flows in the admin UI use `confirm()` browser dialogs instead of proper confirmation modals: archive action (line 662), start-auto-research action (line 603), and results-token regeneration (line 1409) in `frontend/src/routes/admin.pulse.intakes.$id.tsx`.
- **Files:** `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 603, 662, 1409)
- **Impact:** `confirm()` is non-styleable, blocks the main thread, and does not render in SSR/test environments. Inconsistent with the shadcn/ui `AlertDialog` component already present in the codebase.
- **Fix approach:** Replace with `AlertDialog` from `frontend/src/components/ui/alert-dialog.tsx`.

### #15 — `nitro` Pinned to Beta Build (Low)

- **Issue:** `frontend/package.json` pins `nitro` to `3.0.260429-beta` — a date-stamped beta version. This is not a stable semver release.
- **Files:** `frontend/package.json` (line 62)
- **Impact:** Beta builds may have breaking changes between patch updates and are not suitable for production deployments.
- **Fix approach:** Upgrade to the next stable `nitro` release when available, or pin to a specific stable version.

---

## Out-of-Scope Boundary (Do Not Pull In)

### #16 — Tribunal / run-research Seam (Scope Guard)

- **Issue:** `docs/BACKEND-MAP.md` documents `run-research` and the full Tribunal integration contract in detail. The source file `docs/supabase-functions/run-research.ts` is present (22,644 bytes). The admin UI in `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 601–627) already invokes `run-research` via `supabase.functions.invoke`.
- **Files:** `docs/supabase-functions/run-research.ts`, `docs/BACKEND-MAP.md` (Tribunal contract section), `frontend/src/routes/admin.pulse.intakes.$id.tsx` (`onStartAutoResearch`)
- **Impact:** If `run-research` is ported to Cloud Run prematurely, it drags in SerpAPI, SearchAPI, Apify, and the full research engine — which is explicitly out of scope per `README.md`. The flow stops at `decomposed` status; research execution belongs to a separate track.
- **Fix approach:** The `onStartAutoResearch` handler in the admin UI should invoke the new backend's `POST /intakes/{id}/start-research` endpoint (to be built), which initially can just set status to `in_research` and delegate actual research to the future Tribunal track. Never invoke `run-research` directly from the frontend using the new backend's credentials.

---

## Performance Concerns

### #17 — Per-Field Sequential Upserts on Save (Low-Medium)

- **Issue:** The admin intake edit save path in `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 716–754) iterates `changedKeys` with `for...of` and issues a sequential Supabase upsert per changed field. There is no batching.
- **Files:** `frontend/src/routes/admin.pulse.intakes.$id.tsx` (lines 716–754)
- **Impact:** Saving an intake with many changed fields issues N sequential round-trips. On a slow connection this is visibly slow. On the new backend this should be a single `PATCH /intakes/{id}/answers` call with a JSON body of all changed key-value pairs.
- **Fix approach:** Design the new backend endpoint to accept a batch of answer upserts in one request.

### #18 — Skill Run Polling with No Back-off (Low)

- **Issue:** `useActiveSkillRun` in `frontend/src/components/intake/SkillRunProgress.tsx` polls for the active skill run status. The polling interval and back-off strategy are not visible from the current exploration but the component is used in the detail page to drive UI state for a 90–120 second operation.
- **Files:** `frontend/src/components/intake/SkillRunProgress.tsx`
- **Impact:** If polling is fixed-interval with no back-off, it creates unnecessary load during long operations and after completion.
- **Fix approach:** Use TanStack Query's `refetchInterval` with a conditional that stops polling once `status !== 'running'` — verify this is already the case; if not, add it.

---

## Missing Critical Features (Migration Gaps)

### #19 — No Cloud SQL Schema or Migrations

- **Issue:** There are no Alembic migration files, no `schema.sql`, and no Cloud SQL table definitions in this repository. The reference schema exists only as introspection output in `docs/BACKEND-MAP.md` and partial RPC definitions in `docs/db_functions.sql`.
- **Files:** `docs/db_functions.sql` (partial — only trigger functions), `docs/BACKEND-MAP.md` (table list, no CREATE TABLE statements)
- **Impact:** Cloud SQL cannot be provisioned without writing migrations from scratch based on the documented schema.
- **Fix approach:** Write Alembic migrations covering all 14 `nestor` tables plus any GCP-specific additions (e.g., `org_id` RLS column, user/role tables). Use `docs/BACKEND-MAP.md` as the authoritative schema reference.

### #20 — No Identity Platform Integration Built

- **Issue:** The new auth system (Identity Platform replacing Supabase GoTrue) is listed as in-scope but does not exist. The frontend still uses `supabase.auth.signInWithOtp` for magic-link login (`frontend/src/routes/auth.login.tsx`) and `supabase.auth.onAuthStateChange` in `frontend/src/lib/auth-context.tsx`.
- **Files:** `frontend/src/routes/auth.login.tsx`, `frontend/src/lib/auth-context.tsx`, `frontend/src/routes/auth.callback.tsx`
- **Impact:** Admin login is entirely dependent on the live Supabase project. No GCP auth path exists.
- **Fix approach:** Implement Firebase Auth (Identity Platform) email magic-link or email/password flow. Replace `supabase.auth.*` calls in `auth-context.tsx` with Firebase SDK equivalents. The `auth.callback.tsx` org-membership check must be ported to query the FastAPI backend.

### #21 — No Test Coverage Anywhere

- **Issue:** No test files (`*.test.*`, `*.spec.*`) exist in the frontend. No test runner configuration (`jest.config.*`, `vitest.config.*`) exists. The backend and infra directories are empty stubs.
- **Files:** (none — absence is the concern)
- **Impact:** All migration work proceeds without a safety net. RLS logic, auth flows, and data transformation have zero automated test coverage.
- **Fix approach:** At minimum, add Vitest unit tests for pure utilities (`frontend/src/lib/intake-phase.ts`, `frontend/src/lib/intake-types.ts`) and integration tests for the FastAPI backend endpoints as they are built.

---

*Concerns audit: 2026-06-18*
