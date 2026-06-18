<!-- refreshed: 2026-06-18 -->
# Architecture

**Analysis Date:** 2026-06-18

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────┐
│                         Browser (React 19 SPA)                          │
│                    frontend/src/routes/ + components/                   │
├────────────────┬───────────────────────┬────────────────────────────────┤
│  Token routes  │    Admin routes        │     Sales routes               │
│ /intake/$token │ /admin/pulse/intakes/  │ /sales/intake/$token           │
│ /results/$token│ /admin/pulse/clients/  │ /sales/results/$token          │
│  (no login)    │ /admin/sales/          │ /sales/validate/$token         │
└───────┬────────┴──────────┬────────────┴───────────────────────────────-┘
        │                   │
        ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│               Data Layer — frontend/src/lib/supabase.ts                 │
│   @supabase/supabase-js (PostgREST + GoTrue + Realtime + Edge Fn RPC)   │
│   schema: nestor (main)  |  schema: public (clients, orgs)              │
└─────────────────────────┬───────────────────────────────────────────────┘
                          │  CURRENT (Supabase)
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   Supabase project "Sweep Database Project" (eu-west-1)                 │
│   Postgres (nestor + public schemas) · RLS · 21 Edge Functions          │
│   Storage bucket: nestor-uploads · GoTrue auth                          │
└─────────────────────────────────────────────────────────────────────────┘

                          │  TARGET (GCP re-platform)
                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│   FastAPI on Cloud Run  (backend/ — to be built)                        │
│   Identity Platform (GoTrue replacement)                                │
│   Cloud SQL Postgres (nestor schema)                                    │
│   GCS (replaces nestor-uploads bucket)                                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File(s) |
|-----------|----------------|---------|
| Root layout | QueryClient, AuthProvider, AuthRedirector, Toaster shell | `frontend/src/routes/__root.tsx` |
| Auth context | Supabase session state, OTP code exchange, onAuthStateChange | `frontend/src/lib/auth-context.tsx` |
| Supabase client | Singleton PostgREST + GoTrue client, `nestor` schema default | `frontend/src/lib/supabase.ts` |
| Phase machine | Pure function: intake status + skill run + artifacts → Phase enum | `frontend/src/lib/intake-phase.ts` |
| IntakeForm | Client-facing multi-section form, save-as-you-go via RPC | `frontend/src/components/intake/IntakeForm.tsx` |
| IntakeWorkflowStepper | Visual status stepper (submitted→delivered), 6 steps | `frontend/src/components/intake/IntakeWorkflowStepper.tsx` |
| NextStepBanner | Phase-driven CTA buttons for the admin (one per Phase) | `frontend/src/components/intake/NextStepBanner.tsx` |
| AIReviewPanel | Admin AI review UX: displays skill output, accept/edit/reject per field | `frontend/src/components/intake/AIReviewPanel.tsx` |
| SkillRunProgress | Realtime subscription on skill_runs (Supabase Realtime channel) | `frontend/src/components/intake/SkillRunProgress.tsx` |
| ContextPackBlock | Displays generated context pack artifact | `frontend/src/components/intake/ContextPackBlock.tsx` |
| ResearchArtifacts | Lists research_artifacts for an intake (in_research phase) | `frontend/src/components/intake/ResearchArtifacts.tsx` |
| FinalReportBlock | Upload / display final report artifact, trigger delivered status | `frontend/src/components/intake/FinalReportBlock.tsx` |
| ProductShell | Admin sidebar layout wrapper (logo, nav links, logout) | `frontend/src/components/admin/ProductShell.tsx` |
| IntakeDetail (pulse) | Full intake detail page: phase machine, edit mode, skill run, search | `frontend/src/routes/admin.pulse.intakes.$id.tsx` |
| IntakeTypes | TypeScript types for IntakeSchema, IntakeSection, IntakeField, IntakePayload | `frontend/src/lib/intake-types.ts` |

## Pattern Overview

**Overall:** File-based routing SPA (TanStack Router v1) with colocated data fetching via TanStack Query and direct Supabase SDK calls. No intermediate API layer in the current architecture — the frontend calls Supabase PostgREST and Edge Functions directly.

**Key Characteristics:**
- Route files in `frontend/src/routes/` use dot-notation for path nesting (e.g., `admin.pulse.intakes.$id.tsx` = `/admin/pulse/intakes/:id`)
- State management is local React state per route component; no global store (no Zustand/Redux)
- TanStack Query used selectively (token-based intake load, skill run polling); most admin data fetches use raw `useEffect` + Supabase
- Auth context (`AuthProvider`) wraps the whole tree via `__root.tsx`; session propagated via `useAuth()`
- Phase machine (`derivePhase`) is a pure function — no side effects — that maps DB state to a `Phase` enum, driving which UI blocks and CTA buttons are visible

## Layers

**Routing Layer:**
- Purpose: URL → component mapping, layout nesting, auth redirect
- Location: `frontend/src/routes/`
- Contains: Route files, layout wrappers (`admin.tsx`, `admin.pulse.tsx`, `admin.sales.tsx`), auth callback
- Depends on: lib layer (auth-context, supabase), components layer
- Used by: Browser navigation

**Library / Data Layer:**
- Purpose: Supabase client singleton, auth context, domain types, pure business logic
- Location: `frontend/src/lib/`
- Contains: `supabase.ts` (client), `auth-context.tsx` (React context), `intake-types.ts` (TS types), `intake-phase.ts` (phase machine), `research-question.ts` (display helpers), `salesLabels.ts`, `salesMail.ts`, `utils.ts` (cn helper)
- Depends on: `@supabase/supabase-js`, React
- Used by: Route files, components

**Components Layer:**
- Purpose: Reusable UI blocks and domain-specific panels
- Location: `frontend/src/components/`
- Sub-namespaces: `admin/` (shell, modals, product chrome), `intake/` (form, field renderer/display, AI review, artifacts, stepper, banners), `sales/` (battlecard, sales context fields), `ui/` (shadcn primitives — do not modify)
- Depends on: lib layer, shadcn/radix primitives
- Used by: Route files

**UI Primitives:**
- Purpose: shadcn/ui component library (generated, Radix UI based)
- Location: `frontend/src/components/ui/`
- Do NOT modify these directly; update via shadcn CLI or targeted edits

## Data Flow

### Current: Client Token Intake Flow (no login)

1. Admin creates intake → Supabase inserts `nestor.intakes` row with `client_intake_token` UUID
2. Admin copies link → `{origin}/intake/{token}`
3. `frontend/src/routes/intake.$token.tsx` loads → calls Supabase RPC `get_intake_by_token(p_token)` → returns `IntakePayload` (intake + template schema + existing answers)
4. `IntakeForm` renders sections from `template.schema.sections`; each field change calls RPC `save_intake_answer`
5. Client submits → RPC `submit_intake(token)` → status: `draft` → `submitted`
6. Results viewed via `/results/{token}` → RPC `get_results_by_token` (no login required)

### Current: Admin Intake Detail Flow (authenticated)

1. Admin navigates to `/admin/pulse/intakes/{id}` (`frontend/src/routes/admin.pulse.intakes.$id.tsx`)
2. Page `load()` fetches: `nestor.intakes`, `public.clients`, `nestor.intake_answers` via PostgREST `.schema("nestor").from("intakes").select(...)` 
3. `derivePhase(intake, latestSkillRun, hasArtifacts)` → `Phase` (see phase machine below)
4. `NextStepBanner` renders phase-appropriate CTA; admin actions call Supabase Edge Functions via `supabase.functions.invoke(...)`:
   - `apply-intake-skill` → skill_runs row → polled via Supabase Realtime (`SkillRunProgress`)
   - `generate-context-pack` → research_artifacts row
   - `send-pulse-mail` → email (validation_request / validation_reminder / results_ready)
   - `semantic-search` → RAG query over embedded artifacts
   - `run-research` → triggers deep research (out of scope for this re-platform)
5. Admin edits answers inline → upsert to `nestor.intake_answers` per changed field key

### Target: GCP Re-platform Flow

1. Same frontend, same routes — only the data layer changes
2. `frontend/src/lib/supabase.ts` → replace with a GCP API client (`frontend/src/lib/api.ts` TBD)
3. Auth: Supabase GoTrue (`supabase.auth`) → GCP Identity Platform (OIDC/Firebase Auth SDK or custom JWT)
4. PostgREST calls → FastAPI (`backend/`) endpoints on Cloud Run
5. Edge Function invocations (`supabase.functions.invoke(...)`) → Cloud Run service HTTP calls
6. Realtime subscription (skill_runs) → Cloud Run SSE or Pub/Sub push to frontend
7. Storage signed URLs → GCS signed URLs

**State Management:**
- No global state store. Each route component owns its local state with `useState`/`useEffect`
- TanStack Query cache key: `["intake", token]` for token routes; `["active-skill-run", intakeId]` for skill run polling
- Auth session: React context (`AuthProvider` in `__root.tsx`), propagated via `useAuth()`
- Draft edits (admin edit mode): local `draft` state map diffed against `initial` on save

## Key Abstractions

**Phase Machine:**
- Purpose: Maps the intake's DB state to a single `Phase` string that drives all admin UI
- File: `frontend/src/lib/intake-phase.ts`
- Input: `{ status, validation_link_sent_at, results_link_sent_at, context_pack_artifact_id, final_report_artifact_id }` + latest skill run + `hasResearchArtifacts` boolean
- Output: one of 12 `Phase` values (e.g., `awaiting_skill_run`, `awaiting_review`, `awaiting_context_pack`, `in_research`, `completed`)
- Visibility helpers: `phaseShowsAIReview()`, `phaseShowsContextPack()`, `phaseShowsResearch()`, `phaseShowsFinalReport()`, `phaseShowsSemanticSearch()`

**IntakeSchema / IntakePayload:**
- Purpose: JSON schema describing intake form structure (sections → fields with type/validation/options)
- File: `frontend/src/lib/intake-types.ts`
- Key types: `IntakeField` (15+ field types incl. `proposal_list` for AI-suggested questions), `IntakeSection`, `IntakeSchema`, `IntakePayload`
- Stored as JSON in `nestor.intake_templates.schema`

**FieldRenderer / FieldDisplay:**
- Purpose: Dual-mode field rendering — `FieldRenderer` for edit mode, `FieldDisplay` for read mode
- Files: `frontend/src/components/intake/FieldRenderer.tsx`, `frontend/src/components/intake/FieldDisplay.tsx`
- Handles all field types including file uploads to Supabase Storage

**Intake Status State Machine (DB-side):**
```
draft → submitted → reviewed → validated_by_client → decomposed → in_research → delivered → (archived)
```
- Transitions triggered by: RPCs (`submit_intake`), admin direct status updates (PostgREST PATCH), Postgres triggers (`tg_bump_to_in_research`, `tg_bump_to_delivered`)
- Documented fully in `docs/BACKEND-MAP.md`
- The re-platform scope ends at `decomposed`; `in_research` onward involves run-research (Tribunal, out of scope)

## Entry Points

**Public intake form (no auth):**
- Location: `frontend/src/routes/intake.$token.tsx`
- Triggers: Client opens emailed link `/intake/{client_intake_token}`
- Responsibilities: Load intake via RPC, render `IntakeForm`, handle save-as-you-go and submit

**Client results view (no auth):**
- Location: `frontend/src/routes/results.$token.tsx`
- Triggers: Client opens emailed link `/results/{client_results_token}`
- Responsibilities: Load results via RPC `get_results_by_token`, show `ResearchResultsPanel` + final report download

**Admin login:**
- Location: `frontend/src/routes/auth.login.tsx`
- Triggers: Unauthenticated admin navigates to `/auth/login`
- Responsibilities: OTP magic link via `supabase.auth.signInWithOtp`, domain allowlist enforcement (`@agenic.be`)

**Auth callback:**
- Location: `frontend/src/routes/auth.callback.tsx`
- Triggers: Supabase redirects after OTP click
- Responsibilities: Exchange code, verify user has `operator`-type org membership via RPC `user_organization_ids`, redirect to `/admin` or back to login with error

**Admin pulse intake detail:**
- Location: `frontend/src/routes/admin.pulse.intakes.$id.tsx`
- Triggers: Admin opens an intake from the list
- Responsibilities: Full intake lifecycle management — phase machine, edit mode, skill run, AI review, context pack, research, final report, semantic search

**Root (redirects to /admin):**
- Location: `frontend/src/routes/index.tsx`
- Triggers: Any visit to `/`

## Architectural Constraints

- **No backend yet:** `backend/` and `infra/` are scaffolded stubs. All logic is in Supabase today.
- **Direct Supabase calls from routes:** Route components call `supabase.schema("nestor").from(...)` directly — no service/repository abstraction layer between routes and data. This is the primary seam to abstract during the GCP re-platform.
- **Edge Function invocations hardcoded:** `supabase.functions.invoke("apply-intake-skill", ...)` calls are scattered across the intake detail route — not centralized. Each one becomes a Cloud Run HTTP endpoint.
- **Auth guard disabled:** `frontend/src/routes/admin.tsx` has auth guard commented out with `// TEMP: auth disabled for testing`. Re-enabling is required before production.
- **Global state:** None. State is colocated in route components. The `queryClient` singleton is the only shared cache (created once in `__root.tsx`).
- **Realtime subscription:** `SkillRunProgress` uses Supabase Realtime websocket for skill run status. The GCP replacement must provide equivalent push mechanism (SSE or Pub/Sub).
- **Schema routing:** `supabase.schema("nestor")` vs `supabase.schema("public" as never)` — clients live in `public`, intake data in `nestor`. Both schemas queried from the same client instance.
- **Threading:** Single-threaded browser JS event loop. Async operations via `async/await` with `useEffect` cancel flags (`let cancelled = false`).
- **Circular imports:** None detected.

## Anti-Patterns

### Direct Supabase calls in route files

**What happens:** Route components like `admin.pulse.intakes.$id.tsx` call `supabase.schema("nestor").from("intakes").select(...)` and `supabase.functions.invoke("send-pulse-mail", ...)` inline within component event handlers.

**Why it's wrong:** Scatters the data access contract across ~15+ route files. Every Supabase→FastAPI migration requires finding and replacing calls in routes, not a single adapter file.

**Do this instead:** Introduce an API client module (e.g., `frontend/src/lib/api/intakes.ts`) that wraps all intake data operations. Routes call `api.intakes.get(id)` — the module hides whether the underlying transport is Supabase or FastAPI.

### Auth guard disabled in production-bound code

**What happens:** `frontend/src/routes/admin.tsx` returns `<Outlet />` unconditionally with a TODO comment.

**Why it's wrong:** All `/admin/*` routes are publicly accessible without authentication.

**Do this instead:** Restore the guard: check `session` from `useAuth()`, redirect to `/auth/login` when null, show loading state while `loading === true`.

## Error Handling

**Strategy:** Optimistic local state with `toast.error()` rollback messaging. No centralized error boundary beyond TanStack Router's built-in not-found component.

**Patterns:**
- Async data loads: `try/catch` in `useEffect`, local `error` state → inline error UI
- Supabase mutations: check `error` from destructured response, call `toast.error(error.message)`
- Token routes: if RPC returns error → full-page "Link niet beschikbaar" message
- Cancel pattern for unmounted async: `let cancelled = false` flag in `useEffect` cleanup

## Cross-Cutting Concerns

**Logging:** `console.warn` / `console.error` in hooks only (e.g., `SkillRunProgress`). No structured logging.

**Validation:** Client-side field validation in `IntakeForm.tsx` (`validateField` function). Server-side validation in Supabase RLS and Postgres constraints.

**Authentication:** OTP magic link via Supabase GoTrue. Session persisted in `localStorage` (`storageKey: "sb-nestor-auth"`). Domain allowlist enforced client-side in `auth.login.tsx` and server-side via `user_organization_ids` RPC in `auth.callback.tsx`.

**Internationalisation:** UI is Dutch (`nl` locale from `date-fns`). Status labels and messages are hardcoded Dutch strings.

---

*Architecture analysis: 2026-06-18*
