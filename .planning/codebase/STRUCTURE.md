# Codebase Structure

**Analysis Date:** 2026-06-18

## Directory Layout

```
nestor-intake-gcp/
├── frontend/                    # React 19 SPA — the existing Lovable intake app
│   ├── src/
│   │   ├── assets/              # Static assets (logo, images)
│   │   ├── components/
│   │   │   ├── admin/           # Admin chrome: shell, modals, badges
│   │   │   ├── intake/          # Intake domain: form, fields, AI review, stepper, artifacts
│   │   │   ├── sales/           # Sales product: battlecard blocks, sales context fields
│   │   │   └── ui/              # shadcn/ui primitives (Radix-based, auto-generated)
│   │   ├── hooks/               # Generic React hooks (use-mobile.tsx)
│   │   ├── lib/                 # Data layer: Supabase client, auth context, types, pure logic
│   │   ├── routes/              # TanStack Router file-based routes (dot-notation = path nesting)
│   │   ├── utils/               # Standalone utilities (PDF generation)
│   │   └── styles.css           # Global Tailwind v4 styles + design tokens
│   ├── scripts/                 # Build/maintenance scripts
│   ├── package.json             # Dependencies and scripts
│   ├── vite.config.ts           # Vite + Lovable/TanStack plugin config
│   └── eslint.config.js         # ESLint config
├── backend/                     # (to be built) FastAPI on Cloud Run
│   └── README.md                # Placeholder
├── infra/                       # (to be built) Cloud SQL, Identity Platform, GCS, Cloud Run
│   └── README.md                # Placeholder
└── docs/
    ├── BACKEND-MAP.md           # Full map of original Supabase backend (schema, RPCs, edge fns, state machine)
    ├── PROVENANCE.md            # Source provenance and known security issues
    ├── db_functions.sql         # Postgres RPC/trigger definitions (from live project)
    └── supabase-functions/      # TypeScript source of all 21 Supabase edge functions (reference for porting)
        ├── apply-intake-skill.ts
        ├── generate-context-pack.ts
        ├── run-research.ts
        ├── send-pulse-mail.ts
        └── ... (21 total)
```

## Directory Purposes

**`frontend/src/routes/`:**
- Purpose: TanStack Router file-based routes — one file per route/layout
- Naming convention: dot-separated path segments, `$param` for dynamic segments
  - `admin.pulse.tsx` = layout for `/admin/pulse/*`
  - `admin.pulse.intakes.$id.tsx` = route for `/admin/pulse/intakes/:id`
  - `__root.tsx` = root layout (QueryClient, AuthProvider, Toaster)
- Contains: Route definitions (`createFileRoute`), full page components, local types
- Key files:
  - `frontend/src/routes/__root.tsx` — root layout shell
  - `frontend/src/routes/admin.tsx` — admin guard (currently disabled)
  - `frontend/src/routes/admin.pulse.tsx` — Pulse product layout (ProductShell)
  - `frontend/src/routes/admin.pulse.intakes.$id.tsx` — full intake detail page (1500+ lines, the most complex file)
  - `frontend/src/routes/intake.$token.tsx` — client token intake form
  - `frontend/src/routes/results.$token.tsx` — client token results page
  - `frontend/src/routes/auth.login.tsx` — OTP login
  - `frontend/src/routes/auth.callback.tsx` — OTP callback + org check

**`frontend/src/lib/`:**
- Purpose: Data layer, auth context, domain types, pure business logic
- Key files:
  - `frontend/src/lib/supabase.ts` — Supabase client singleton (`export const supabase`). **This is the primary migration seam** — replacing this with a GCP API client re-points the entire frontend.
  - `frontend/src/lib/auth-context.tsx` — `AuthProvider` + `useAuth()` hook (session + loading state)
  - `frontend/src/lib/intake-types.ts` — `IntakeField`, `IntakeSection`, `IntakeSchema`, `IntakePayload` types
  - `frontend/src/lib/intake-phase.ts` — `derivePhase()` pure function + `Phase` type + visibility helpers
  - `frontend/src/lib/research-question.ts` — display helpers for research question text (anchor prefix stripping)
  - `frontend/src/lib/salesLabels.ts` — Sales product label constants
  - `frontend/src/lib/salesMail.ts` — Sales mail utilities
  - `frontend/src/lib/utils.ts` — `cn()` helper (clsx + tailwind-merge)

**`frontend/src/components/intake/`:**
- Purpose: All intake-workflow domain components
- Key files:
  - `IntakeForm.tsx` — client-facing multi-section form (save-as-you-go, validation, submit)
  - `FieldRenderer.tsx` — edit-mode field input (all field types)
  - `FieldDisplay.tsx` — read-mode field display + `isFieldDisplayEmpty()` helper
  - `IntakeWorkflowStepper.tsx` — visual 6-step progress stepper
  - `NextStepBanner.tsx` — phase-driven CTA banner (one action per Phase)
  - `AIReviewPanel.tsx` — AI skill run review UI (accept/edit/reject per field, `ReviewProvider` context)
  - `SkillRunProgress.tsx` — `useActiveSkillRun()` hook (Supabase Realtime subscription on `nestor.skill_runs`)
  - `ContextPackBlock.tsx` — displays context pack research artifact
  - `ResearchArtifacts.tsx` — lists research artifacts for admin view
  - `FinalReportBlock.tsx` — upload + display final report, triggers `delivered` status
  - `ValidationDiff.tsx` — shows admin-vs-client diff during validation phase

**`frontend/src/components/admin/`:**
- Purpose: Admin-specific chrome and utility components
- Key files:
  - `ProductShell.tsx` — sidebar layout with nav links and logout; wraps all admin product pages
  - `ClientFormModal.tsx` — modal for creating/editing clients
  - `ClientDetailDrawer.tsx` — slide-over drawer for client details

**`frontend/src/components/ui/`:**
- Purpose: shadcn/ui generated component library (accordion, button, dialog, input, table, etc.)
- Do NOT hand-edit these files. Add new primitives via `npx shadcn@latest add <component>` or targeted edits only.

**`frontend/src/hooks/`:**
- Purpose: Generic React hooks not specific to a domain
- Key files: `use-mobile.tsx` (breakpoint detection)

**`frontend/src/utils/`:**
- Purpose: Standalone utility functions
- Key files: `generateBattlecardPdf.ts` (jsPDF battlecard generation for Sales product)

**`docs/`:**
- Purpose: Reference documentation for the original Supabase backend (read-only, pulled 2026-06-18)
- `BACKEND-MAP.md` — authoritative map: 14 tables, 21 edge functions, 27 RPCs, full status state machine. **Read this before porting any edge function or RPC.**
- `supabase-functions/` — clean TS source of all 21 edge functions. Use as spec for FastAPI port.
- `db_functions.sql` — Postgres function/trigger definitions. Use as spec for Cloud SQL.

**`backend/`:**
- Purpose: FastAPI service on Cloud Run — to be built
- Will contain Python FastAPI app, Dockerfile, Cloud Run config

**`infra/`:**
- Purpose: Infrastructure-as-code — to be built
- Will contain Cloud SQL schema, Identity Platform config, GCS bucket config, Cloud Run service manifests

## Key File Locations

**Entry Points:**
- `frontend/src/routes/__root.tsx` — root React tree (providers + outlet)
- `frontend/src/routes/index.tsx` — `/` → redirects to `/admin`
- `frontend/src/routes/auth.login.tsx` — admin login
- `frontend/src/routes/auth.callback.tsx` — OTP callback
- `frontend/src/routes/intake.$token.tsx` — client intake form entry
- `frontend/src/routes/results.$token.tsx` — client results entry

**Configuration:**
- `frontend/vite.config.ts` — Vite config (uses `@lovable.dev/vite-tanstack-config`, Cloudflare Nitro target)
- `frontend/package.json` — all dependencies and npm scripts
- `frontend/eslint.config.js` — ESLint rules
- `frontend/src/styles.css` — Tailwind v4 global styles and CSS design tokens

**Core Business Logic:**
- `frontend/src/lib/intake-phase.ts` — phase machine (the key intake workflow logic)
- `frontend/src/lib/intake-types.ts` — intake schema types
- `frontend/src/lib/supabase.ts` — current data layer (migration seam)
- `frontend/src/lib/auth-context.tsx` — auth session management

**Intake UI Logic:**
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — the largest file; orchestrates all intake admin actions
- `frontend/src/components/intake/IntakeForm.tsx` — client form experience
- `frontend/src/components/intake/AIReviewPanel.tsx` — admin AI review UX

**Backend Reference (read-only):**
- `docs/BACKEND-MAP.md` — schema, state machine, edge function and RPC inventory
- `docs/supabase-functions/apply-intake-skill.ts` — Claude skill run (port to FastAPI)
- `docs/supabase-functions/generate-context-pack.ts` — context pack generator (port to FastAPI)
- `docs/supabase-functions/send-pulse-mail.ts` — email sender (port to FastAPI)
- `docs/supabase-functions/semantic-search.ts` — RAG search (port to FastAPI)
- `docs/db_functions.sql` — Postgres RPCs and triggers

## Naming Conventions

**Route files:**
- Pattern: `{segment}.{segment}.$param.tsx` where segments are path parts and `$param` is dynamic
- Examples: `admin.pulse.tsx` (layout), `admin.pulse.intakes.$id.tsx` (detail page), `intake.$token.tsx`
- Layout wrappers use just the path prefix: `admin.tsx`, `admin.pulse.tsx`, `admin.sales.tsx`

**Component files:**
- PascalCase: `IntakeForm.tsx`, `NextStepBanner.tsx`, `ProductShell.tsx`
- Domain prefix in directory name, not filename: `components/intake/FieldDisplay.tsx` not `IntakeFieldDisplay.tsx`

**Library files:**
- kebab-case: `auth-context.tsx`, `intake-phase.ts`, `intake-types.ts`, `research-question.ts`

**Exports:**
- Route files export `Route` (the TanStack Router route object) and a named component function
- Components export named functions (no default exports)
- Hooks export named functions prefixed with `use`

## Where to Add New Code

**New admin route/page:**
- Create `frontend/src/routes/admin.{product}.{feature}.tsx`
- If it needs a layout shell, create `admin.{product}.tsx` using `ProductShell`
- Pattern: copy `admin.pulse.tsx` for layout, `admin.pulse.intakes.index.tsx` for list page

**New intake component (admin side):**
- Add to `frontend/src/components/intake/`
- Export named function, import `supabase` from `@/lib/supabase`

**New client-facing route (token-based, no login):**
- Create `frontend/src/routes/{noun}.$token.tsx`
- Use TanStack Query (`useQuery`) with the token as the query key
- Call appropriate Supabase RPC for data loading

**New lib utility / type:**
- Add to `frontend/src/lib/` with a kebab-case filename
- Keep pure functions separate from React context/hooks

**New shadcn/ui primitive:**
- Run `npx shadcn@latest add <component>` from the `frontend/` directory
- File lands in `frontend/src/components/ui/`

**New FastAPI endpoint (GCP backend):**
- Add to `backend/` (structure TBD — not yet scaffolded)
- Reference the corresponding Supabase edge function source in `docs/supabase-functions/`

**New Cloud SQL migration:**
- Add to `infra/` (structure TBD)
- Reference the original schema in `docs/db_functions.sql` and `docs/BACKEND-MAP.md`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning documents (phases, codebase maps)
- Generated: By GSD tooling
- Committed: Yes

**`frontend/src/components/ui/`:**
- Purpose: Auto-generated shadcn/ui components
- Generated: Via shadcn CLI
- Committed: Yes (editable in-place but treat as library code)

**`docs/supabase-functions/`:**
- Purpose: Reference-only source code of the Supabase edge functions being ported
- Generated: Pulled via Supabase Management API
- Committed: Yes, read-only reference

---

*Structure analysis: 2026-06-18*
