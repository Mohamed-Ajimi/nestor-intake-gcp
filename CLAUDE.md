<!-- GSD:project-start source:PROJECT.md -->
## Project

**Nestor Intake (GCP Re-platform)**

Nestor Intake is the agentic "Pulse" intake application built by Agenic — clients fill in a
structured, multi-section intake form, and operators run AI skills over the answers to produce a
validated set of research questions and a context pack (the flow that runs *before* the deep-research
engine). This project re-platforms the entire pre-research flow off its original third-party
**Supabase** build and onto **Google Cloud Platform** (FastAPI on Cloud Run, Cloud SQL, Identity
Platform, GCS), while introducing real per-tenant isolation ("spaces"), proper authentication, and a
multi-language UI. The deep-research stage (Tribunal) was a separate track, out of scope for
milestone v1.0 — that flow stopped at status `decomposed`. Milestone v1.1 (Tribunal Integration)
has since built, deployed and wired it in; see the Scope ceiling constraint below.

**Core Value:** A logged-in superadmin or client user can run an intake end-to-end on GCP — from form submission
through AI skill application to a validated, decomposed context pack (milestone v1.0's end point;
v1.1 continues from there into Tribunal research and delivery) — with each client's data fully
isolated to its own space, and with the legacy Supabase system fully retired.

### Constraints

- **Tech stack**: GCP-mandated — FastAPI on Cloud Run, Cloud SQL (Postgres + pgvector), Identity Platform, GCS — replaces the entire Supabase stack.
- **Backend language**: Python / FastAPI — per project direction.
- **Frontend**: Existing React 19 + TanStack Router/Query + shadcn app retained; only data + auth layers swapped. `frontend/src/components/ui/` (shadcn) not modified directly.
- **Security**: No cross-tenant access. Tenant isolation enforced server-side at the API layer; the broken-RLS class of bug must not recur. All writes mediated by the backend.
- **Scope ceiling (milestone v1.0 — SUPERSEDED by v1.1)**: the v1.0 re-platform flow
  ended at `decomposed`. Milestone v1.1 (Tribunal Integration) deliberately extends it
  through `in_research` -> `delivered` via the GCP-native Tribunal engine, mounted at
  `backend/app/main.py:152`.
- **Still binding**: the LEGACY Supabase `run-research` edge function must never be
  invoked from the new frontend/backend credentials. This is a different thing from the
  GCP Tribunal path and the prohibition is unchanged.
- **Do not unmount the research router**: `research_router` is mounted at `backend/app/main.py:152` and must not be removed or unmounted (D-23.1-10). The still-binding prohibition above is enforced by `backend/tests/test_no_run_research_route.py` and `backend/tests/test_scope_guard_run_research.py` — keep it when editing the ceiling around it.
- **Cutover model**: Big-bang — Supabase is retired once the GCP path is validated end-to-end (no long-lived dual-run).
- **No test coverage today**: The existing codebase has zero automated tests — a safety net must be built alongside the migration.
- *Corrected 2026-09-04 (phase 23.1, D-23.1-10 — operator ruling 2026-09-03): the `decomposed` ceiling above described milestone v1.0 only. Tribunal is built, deployed and live — `tribunal-api-00023-bc6` / `tribunal-worker-00009-fkm` at tag `20260901-134253`, per `.planning/STATE.md`.*
<!-- GSD:project-end -->

<!-- GSD:stack-start source:codebase/STACK.md -->
## Technology Stack

## Languages
- TypeScript 5.8 — all frontend source (`frontend/src/**/*.ts`, `frontend/src/**/*.tsx`)
- TypeScript (Deno) — all 21 original Supabase edge functions (`docs/supabase-functions/*.ts`)
- SQL (PostgreSQL) — schema, RPCs, and triggers (`docs/db_functions.sql`)
## Runtime
- Browser (ES2022 target; `lib: ["ES2022", "DOM", "DOM.Iterable"]` per `frontend/tsconfig.json`)
- SSR via Nitro (Cloudflare Workers runtime, `nodeCompat: true` per `frontend/wrangler.jsonc`)
- Deno — all 21 edge functions run on Supabase EdgeRuntime
- Python 3.x — FastAPI on Cloud Run (`backend/` — currently a placeholder)
- Bun — `frontend/bunfig.toml` present; lockfile setting: `saveTextLockfile = false`
- No lockfile committed (intentional per bunfig config)
## Frameworks
- React 19.2 (`react@^19.2.0`) — UI rendering
- TanStack Router 1.168 (`@tanstack/react-router`) — file-based routing; routes auto-generated to `frontend/src/routeTree.gen.ts`
- TanStack Start 1.167 (`@tanstack/react-start`) — SSR/fullstack adapter for TanStack Router
- TanStack Query 5.83 (`@tanstack/react-query`) — server state management
- shadcn/ui (new-york style, Tailwind CSS variables) — configured via `frontend/components.json`
- Radix UI primitives — full suite (`@radix-ui/react-*`) backing all shadcn components
- Tailwind CSS 4.2 (`tailwindcss@^4.2.1`) via Vite plugin (`@tailwindcss/vite`)
- lucide-react 0.575 — icon set
- react-hook-form 7.71 + `@hookform/resolvers` — form state
- Zod 3.24 — schema validation
- Vite 7.3 — bundler and dev server
- `@lovable.dev/vite-tanstack-config` 2.3.1 — Lovable-specific Vite/TanStack preset (`frontend/vite.config.ts`)
- `@cloudflare/vite-plugin` — Cloudflare Workers integration
- `@tanstack/router-plugin` — route tree generation
- `vite-tsconfig-paths` — `@/*` path alias resolution
- ESLint 9.32 + typescript-eslint 8.56 — configured in `frontend/eslint.config.js`
- Prettier 3.7 via `eslint-plugin-prettier`
- Rules: react-hooks recommended, react-refresh warnings; `@typescript-eslint/no-unused-vars` disabled
- `@react-pdf/renderer` 4.5 — PDF generation from React components (`frontend/src/components/intake/ContextPackPDF.tsx`; `NestorBriefingPDF.tsx` was deleted in phase 23.1)
- jsPDF 4.2 — programmatic PDF export (`frontend/src/components/intake/ContextPackBlock.tsx`)
- react-markdown 10.1 + remark-gfm — markdown rendering in admin panels (`rehype-raw` was REMOVED in phase 23.1: it rendered unsanitised AI/DB-controlled HTML; see DEF-23.1-01 before reinstating anything like it)
- recharts 2.15 — data visualisation
- date-fns 4.1 (with `nl` locale) — Dutch locale date formatting throughout
- embla-carousel-react 8.6
- sonner 2.0 — toast system
- input-otp 1.4
## Key Dependencies
- `@supabase/supabase-js` 2.105 — PostgREST client + GoTrue auth + Storage + Edge Function invocation
- Original edge functions import from `jsr:@supabase/supabase-js@2` or `https://esm.sh/@supabase/supabase-js@2`
- No npm deps in functions — all via Deno JSR / esm.sh CDN
- `nitro` 3.0.260429-beta — server output layer
- `wrangler` (dev dep implied by `wrangler.jsonc`) — Cloudflare Workers deploy tooling
## Configuration
- `VITE_SUPABASE_URL` — Supabase project URL (used in `frontend/src/lib/supabase.ts`, direct `fetch` calls)
- `VITE_SUPABASE_ANON_KEY` — Supabase anon/public key
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` — all 21 functions
- `ANTHROPIC_API_KEY` — `apply-intake-skill`, `generate-context-pack`, `extract-insights`, `generate-battlecard`
- `OPENAI_API_KEY` — `generate-embeddings`, `embed-artifact`, `embed-pending-search`, `transcribe-audio`
- `SERPAPI_API_KEY` — `run-research` (Google search via SerpAPI)
- `SEARCHAPI_API_KEY` — `run-research` (Google search via SearchAPI)
- `APIFY_API_TOKEN` — `run-research` (rag-web-browser + website-content-crawler actors)
- `RESEND_API_KEY` — `send-pulse-mail`, `send-sales-mail`
- `TALLY_WEBHOOK_SECRET` / `INTAKE_WEBHOOK_SECRET` — `tally-webhook`
- `NESTOR_BASE_URL` — `send-pulse-mail` (defaults to `https://start-bloom-flow.lovable.app`)
- `NESTOR_ADMIN_EMAIL` — `send-pulse-mail` (defaults to `yanick@agenic.be`)
- Strict mode enabled; `moduleResolution: Bundler`; path alias `@/*` → `frontend/src/*`
- Config: `frontend/tsconfig.json`
- Vite config: `frontend/vite.config.ts` (extends `@lovable.dev/vite-tanstack-config`)
- Wrangler config: `frontend/wrangler.jsonc` (name: `nestor`, compat date 2025-09-24, `nodejs_compat` flag)
- Output: `.output/server/index.mjs` (server), `.output/public/` (static assets)
- Config: `frontend/components.json` (style: new-york, baseColor: slate, cssVariables: true, iconLibrary: lucide)
- CSS: `frontend/src/styles.css`
## Platform Requirements
- Bun (package manager / runner)
- Node.js-compatible environment (Cloudflare `nodejs_compat` flag enabled)
- Env vars `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for local dev
- Cloudflare Workers — SSR via Nitro + Wrangler deployment of `frontend/`
- Frontend: remains on Cloudflare Workers (or can be re-targeted)
- Backend API: Cloud Run (FastAPI, `backend/` placeholder)
- Database: Cloud SQL (PostgreSQL), `infra/` placeholder
- Auth: Google Identity Platform
- File Storage: Google Cloud Storage
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

## Naming Patterns
- Routes: dot-separated TanStack file-route convention — `admin.pulse.intakes.$id.tsx`, `auth.login.tsx`, `intake.$token.tsx`
- Components: PascalCase — `IntakeForm.tsx`, `NextStepBanner.tsx`, `SkillRunProgress.tsx`
- UI primitives (shadcn): lowercase-kebab — `button.tsx`, `alert-dialog.tsx`, `dropdown-menu.tsx`
- Lib/utilities: camelCase or kebab — `intake-types.ts`, `intake-phase.ts`, `salesLabels.ts`, `salesMail.ts`
- Generated files: suffix `.gen.ts` — `routeTree.gen.ts`
- Admin sub-components: PascalCase — `ClientDetailDrawer.tsx`, `ProductBadge.tsx`
- One file exception: `clientPills.tsx` (lowercase — inconsistent, flag when adding similar files)
- React components: PascalCase — `IntakeDetailPage`, `LoginPage`, `PulseLayout`, `StatusPill`
- Custom hooks: `use` prefix camelCase — `useIsMobile`, `useAuth`, `useActiveSkillRun`, `useSkillRunFull`
- Event handlers: `handle` prefix camelCase — `handleSubmit`, `handleSave`, `handleCancel`, `handleStatusChange`, `handleSemanticSearch`
- Action callbacks passed as props: `on` prefix — `onRunSkill`, `onCopyIntakeLink`, `onSendValidationMail`
- Async helpers: verb + noun — `sendSalesMail`, `loadSkillRuns`, `fetchLatest`
- Pure helpers (non-handler, non-hook): camelCase verb — `derivePhase`, `displayQuestionText`, `stripAnchorPrefix`, `isAnchorQuestion`, `fmt`, `fmtDate`
- camelCase throughout — `intakeData`, `clientMap`, `skillRuns`, `answersMap`
- Boolean states named with `is`/`has` prefix where possible — `isMobile`, `hasArtifacts`, `hasChanges`
- Loading states: `loading`, `saving`, `sending`, `submitting`, `busy`, `updatingStatus`
- Error states: `error` (string | null), `errors` (string[]) for multi-field validation
- Local row types: PascalCase suffix `Row` — `IntakeRow`, `AnswerRow`, `SkillRun`
- Domain types: plain PascalCase — `Intake`, `Client`, `Phase`, `Product`
- Prop types: inline `{ prop: Type }` or named with `Props` suffix — `type Props = { ... }`
- Exported types: named and exported — `ActiveSkillRun`, `BusyKey`, `IntakePayload`, `IntakeSchema`
- Option arrays: `SCREAMING_SNAKE_CASE` — `STATUS_OPTIONS`, `STATUS_LABEL`, `STATUS_VARIANT`, `MEETING_TYPE_OPTIONS`
- Constants: `SCREAMING_SNAKE_CASE` — `MOBILE_BREAKPOINT`, `ANCHOR_PREFIX`, `ALLOWED_DOMAINS`
## Code Style
- `printWidth`: 100
- `semi`: true (semicolons required)
- `singleQuote`: false (double quotes)
- `trailingComma`: "all"
- Config: `frontend/.prettierrc`
- Base: `@eslint/js` recommended + `typescript-eslint` recommended
- Plugins: `eslint-plugin-react-hooks`, `eslint-plugin-react-refresh`, `eslint-plugin-prettier`
- `@typescript-eslint/no-unused-vars`: turned **off** (tolerated in this codebase)
- `react-hooks/rules-of-hooks`: enforced
- `react-hooks/exhaustive-deps`: enforced (with selective `eslint-disable-next-line` suppressions)
- `react-refresh/only-export-components`: warn
- Config: `frontend/eslint.config.js`
- Strict: yes (TypeScript 5.8)
- `any` use: present but discouraged. 53 occurrences of `as any` / `as unknown` spread across ~11 files; route/data layer uses frequent `as unknown as Type` casts because Supabase JS SDK generics are not wired up (no generated DB types)
- `import type` used consistently for type-only imports
- `void` used to intentionally discard promise results — `void fetch(...)`, `void supabase!.removeChannel(...)`
- `!` non-null assertions used sparingly on `supabase!` after null-guards
## Import Organization
- `@/` maps to `frontend/src/` (configured in `vite-tsconfig-paths`)
- Always use `@/` — never relative `../../` for cross-directory imports
## Data Fetching Pattern
## Supabase Client Usage
- Null-checked on every use: `if (!supabase) return;` / `if (!supabase) { setError("Supabase niet geconfigureerd."); ... }`
- Schema qualifier always explicit: `.schema("nestor")` or `.schema("public")`
- The `supabasePublic` export in `frontend/src/lib/supabase.ts` is an alias for `supabase` (same client, back-compat only — do not create a second GoTrueClient)
- Edge function calls via `supabase.functions.invoke("function-name", { body: {...} })`, not raw fetch (except the fire-and-forget `apply-intake-skill` pattern in `admin.pulse.intakes.$id.tsx`)
## Component Design
- Named function (not arrow) — `function IntakeDetailPage() { ... }`
- Route export always `export const Route = createFileRoute(...)({ component: FunctionName })`
- Local helper components (non-exported) defined at file bottom — `Meta`, `LinkRow`, `ResultsLinkRow`, `StatusPill`, `DeliveredAtEditor`
- Named exports — `export function IntakeForm(...)`, `export function NextStepBanner(...)`
- Props typed inline or as `type Props = { ... }` immediately before the function
- `cva` + `cn` pattern for variant-based styling — see `frontend/src/components/ui/button.tsx`
- `React.forwardRef` used on all shadcn primitives
- `displayName` set on forwarded-ref components
- Defined inline in the same file as their parent when only used there — `PrimaryBtn`, `SecondaryBtn`, `Tooltip`, `RunningClock` in `NextStepBanner.tsx`
- Prop type defined inline — `{ onClick: () => void; busy?: boolean; children: React.ReactNode }`
## Tailwind / Styling
- `cn()` from `frontend/src/lib/utils.ts` for conditional class merging (clsx + tailwind-merge)
- Shared class strings extracted to `const` when reused within a file:
- Inline `style` prop used only for dynamic values (colour driven by runtime data):
- Font families: IBM Plex Mono (`font-mono`), IBM Plex Sans (`font-sans`), IBM Plex Serif (`font-serif`) — loaded via Google Fonts and `@fontsource` packages
## Error Handling
- Supabase error: destructure `error` from result, check, then `toast.error(error.message)`
- Pattern: try/catch with `finally` to clear loading state:
- User notifications: **always** via `sonner` toast (`toast.success`, `toast.error`, `toast.message`) — never `alert()` except for destructive confirmation dialogs (`confirm(...)`)
- Network/API errors from `salesMail.ts` pattern: return `{ success: boolean; error?: string }` (no throw)
- Loading: `<Skeleton>` components from `@/components/ui/skeleton` during data fetch
- Error: inline error message (`<p className="text-sm text-red-600">{error}</p>`) or full-page error card
- Router-level: `DefaultErrorComponent` in `frontend/src/router.tsx` — shows error message in dev only (`import.meta.env.DEV`)
- 404: `NotFoundComponent` in `frontend/src/routes/__root.tsx`
## Logging
- `console.error` for fetch/data errors in development — not removed before commit in this codebase
- `console.warn` in hooks for non-fatal degraded states (e.g. `[SkillRunProgress] latest run fetch failed`)
- No structured logging library
## Comments
## Module Design
- Named exports preferred — `export function`, `export type`, `export const`
- Default exports: only used by TanStack Router file-route convention (none explicitly in source)
- Route files always export `const Route = createFileRoute(...)(...)` as the primary export
- `supabase.ts`: client singleton + shared types (`Product`)
- `auth-context.tsx`: `AuthProvider` + `useAuth` hook (React Context pattern)
- `intake-types.ts`: pure TypeScript types for intake domain (no logic)
- `intake-phase.ts`: pure phase-machine logic (no React, no Supabase — explicitly noted in file comment)
- `salesLabels.ts`: label maps + option arrays for sales domain
- `salesMail.ts`: standalone async function, no side effects
- `research-question.ts`: pure string helpers
- `utils.ts`: `cn()` utility only
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

## System Overview
```text
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
- Route files in `frontend/src/routes/` use dot-notation for path nesting (e.g., `admin.pulse.intakes.$id.tsx` = `/admin/pulse/intakes/:id`)
- State management is local React state per route component; no global store (no Zustand/Redux)
- TanStack Query used selectively (token-based intake load, skill run polling); most admin data fetches use raw `useEffect` + Supabase
- Auth context (`AuthProvider`) wraps the whole tree via `__root.tsx`; session propagated via `useAuth()`
- Phase machine (`derivePhase`) is a pure function — no side effects — that maps DB state to a `Phase` enum, driving which UI blocks and CTA buttons are visible
## Layers
- Purpose: URL → component mapping, layout nesting, auth redirect
- Location: `frontend/src/routes/`
- Contains: Route files, layout wrappers (`admin.tsx`, `admin.pulse.tsx`, `admin.sales.tsx`), auth callback
- Depends on: lib layer (auth-context, supabase), components layer
- Used by: Browser navigation
- Purpose: Supabase client singleton, auth context, domain types, pure business logic
- Location: `frontend/src/lib/`
- Contains: `supabase.ts` (client), `auth-context.tsx` (React context), `intake-types.ts` (TS types), `intake-phase.ts` (phase machine), `research-question.ts` (display helpers), `salesLabels.ts`, `salesMail.ts`, `utils.ts` (cn helper)
- Depends on: `@supabase/supabase-js`, React
- Used by: Route files, components
- Purpose: Reusable UI blocks and domain-specific panels
- Location: `frontend/src/components/`
- Sub-namespaces: `admin/` (shell, modals, product chrome), `intake/` (form, field renderer/display, AI review, artifacts, stepper, banners), `sales/` (battlecard, sales context fields), `ui/` (shadcn primitives — do not modify)
- Depends on: lib layer, shadcn/radix primitives
- Used by: Route files
- Purpose: shadcn/ui component library (generated, Radix UI based)
- Location: `frontend/src/components/ui/`
- Do NOT modify these directly; update via shadcn CLI or targeted edits
## Data Flow
### Current: Client Token Intake Flow (no login)
### Current: Admin Intake Detail Flow (authenticated)
### Target: GCP Re-platform Flow
- No global state store. Each route component owns its local state with `useState`/`useEffect`
- TanStack Query cache key: `["intake", token]` for token routes; `["active-skill-run", intakeId]` for skill run polling
- Auth session: React context (`AuthProvider` in `__root.tsx`), propagated via `useAuth()`
- Draft edits (admin edit mode): local `draft` state map diffed against `initial` on save
## Key Abstractions
- Purpose: Maps the intake's DB state to a single `Phase` string that drives all admin UI
- File: `frontend/src/lib/intake-phase.ts`
- Input: `{ status, validation_link_sent_at, results_link_sent_at, context_pack_artifact_id, final_report_artifact_id }` + latest skill run + `hasResearchArtifacts` boolean
- Output: one of 12 `Phase` values (e.g., `awaiting_skill_run`, `awaiting_review`, `awaiting_context_pack`, `in_research`, `completed`)
- Visibility helpers: `phaseShowsAIReview()`, `phaseShowsContextPack()`, `phaseShowsResearch()`, `phaseShowsFinalReport()`, `phaseShowsSemanticSearch()`
- Purpose: JSON schema describing intake form structure (sections → fields with type/validation/options)
- File: `frontend/src/lib/intake-types.ts`
- Key types: `IntakeField` (15+ field types incl. `proposal_list` for AI-suggested questions), `IntakeSection`, `IntakeSchema`, `IntakePayload`
- Stored as JSON in `nestor.intake_templates.schema`
- Purpose: Dual-mode field rendering — `FieldRenderer` for edit mode, `FieldDisplay` for read mode
- Files: `frontend/src/components/intake/FieldRenderer.tsx`, `frontend/src/components/intake/FieldDisplay.tsx`
- Handles all field types including file uploads to Supabase Storage
```
```
- Transitions triggered by: RPCs (`submit_intake`), admin direct status updates (PostgREST PATCH), Postgres triggers (`tg_bump_to_in_research`, `tg_bump_to_delivered`)
- Documented fully in `docs/BACKEND-MAP.md`
- The v1.0 re-platform scope ended at `decomposed`; milestone v1.1 extends the flow through `in_research` -> `delivered`. The research surface is `backend/app/api/research_routes.py`, mounted at `backend/app/main.py:152`, and the engine lives under `tribunal/nestor_pulse_sdk/`. (The legacy Supabase `run-research` edge function is a different thing and remains prohibited — see the Scope ceiling constraint.)
## Entry Points
- Location: `frontend/src/routes/intake.$token.tsx`
- Triggers: Client opens emailed link `/intake/{client_intake_token}`
- Responsibilities: Load intake via RPC, render `IntakeForm`, handle save-as-you-go and submit
- Location: `frontend/src/routes/results.$token.tsx`
- Triggers: Client opens emailed link `/results/{client_results_token}`
- Responsibilities: Load results via RPC `get_results_by_token`, show `ResearchResultsPanel` + final report download
- Location: `frontend/src/routes/auth.login.tsx`
- Triggers: Unauthenticated admin navigates to `/auth/login`
- Responsibilities: OTP magic link via `supabase.auth.signInWithOtp`, domain allowlist enforcement (`@agenic.be`)
- Location: `frontend/src/routes/auth.callback.tsx`
- Triggers: Supabase redirects after OTP click
- Responsibilities: Exchange code, verify user has `operator`-type org membership via RPC `user_organization_ids`, redirect to `/admin` or back to login with error
- Location: `frontend/src/routes/admin.pulse.intakes.$id.tsx`
- Triggers: Admin opens an intake from the list
- Responsibilities: Full intake lifecycle management — phase machine, edit mode, skill run, AI review, context pack, research, final report, semantic search
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
### Auth guard disabled in production-bound code
## Error Handling
- Async data loads: `try/catch` in `useEffect`, local `error` state → inline error UI
- Supabase mutations: check `error` from destructured response, call `toast.error(error.message)`
- Token routes: if RPC returns error → full-page "Link niet beschikbaar" message
- Cancel pattern for unmounted async: `let cancelled = false` flag in `useEffect` cleanup
## Cross-Cutting Concerns
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
