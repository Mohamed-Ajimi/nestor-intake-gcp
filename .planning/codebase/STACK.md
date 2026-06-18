# Technology Stack

**Analysis Date:** 2026-06-18

## Languages

**Primary:**
- TypeScript 5.8 — all frontend source (`frontend/src/**/*.ts`, `frontend/src/**/*.tsx`)
- TypeScript (Deno) — all 21 original Supabase edge functions (`docs/supabase-functions/*.ts`)

**Secondary:**
- SQL (PostgreSQL) — schema, RPCs, and triggers (`docs/db_functions.sql`)

## Runtime

**Frontend Environment:**
- Browser (ES2022 target; `lib: ["ES2022", "DOM", "DOM.Iterable"]` per `frontend/tsconfig.json`)
- SSR via Nitro (Cloudflare Workers runtime, `nodeCompat: true` per `frontend/wrangler.jsonc`)

**Original Backend (Supabase, reference only):**
- Deno — all 21 edge functions run on Supabase EdgeRuntime

**Target Backend (to be built):**
- Python 3.x — FastAPI on Cloud Run (`backend/` — currently a placeholder)

**Package Manager:**
- Bun — `frontend/bunfig.toml` present; lockfile setting: `saveTextLockfile = false`
- No lockfile committed (intentional per bunfig config)

## Frameworks

**Core Frontend:**
- React 19.2 (`react@^19.2.0`) — UI rendering
- TanStack Router 1.168 (`@tanstack/react-router`) — file-based routing; routes auto-generated to `frontend/src/routeTree.gen.ts`
- TanStack Start 1.167 (`@tanstack/react-start`) — SSR/fullstack adapter for TanStack Router
- TanStack Query 5.83 (`@tanstack/react-query`) — server state management

**UI Component Library:**
- shadcn/ui (new-york style, Tailwind CSS variables) — configured via `frontend/components.json`
- Radix UI primitives — full suite (`@radix-ui/react-*`) backing all shadcn components
- Tailwind CSS 4.2 (`tailwindcss@^4.2.1`) via Vite plugin (`@tailwindcss/vite`)
- lucide-react 0.575 — icon set

**Form Handling:**
- react-hook-form 7.71 + `@hookform/resolvers` — form state
- Zod 3.24 — schema validation

**Build / Dev:**
- Vite 7.3 — bundler and dev server
- `@lovable.dev/vite-tanstack-config` 2.3.1 — Lovable-specific Vite/TanStack preset (`frontend/vite.config.ts`)
- `@cloudflare/vite-plugin` — Cloudflare Workers integration
- `@tanstack/router-plugin` — route tree generation
- `vite-tsconfig-paths` — `@/*` path alias resolution

**Linting / Formatting:**
- ESLint 9.32 + typescript-eslint 8.56 — configured in `frontend/eslint.config.js`
- Prettier 3.7 via `eslint-plugin-prettier`
- Rules: react-hooks recommended, react-refresh warnings; `@typescript-eslint/no-unused-vars` disabled

**Document Generation:**
- `@react-pdf/renderer` 4.5 — PDF generation from React components (`frontend/src/components/intake/ContextPackPDF.tsx`, `NestorBriefingPDF.tsx`)
- jsPDF 4.2 — programmatic PDF export (`frontend/src/components/intake/ContextPackBlock.tsx`)

**Markdown / Content:**
- react-markdown 10.1 + remark-gfm + rehype-raw — markdown rendering in admin panels

**Charts:**
- recharts 2.15 — data visualisation

**Date Utilities:**
- date-fns 4.1 (with `nl` locale) — Dutch locale date formatting throughout

**Carousel:**
- embla-carousel-react 8.6

**Toast / Notifications:**
- sonner 2.0 — toast system

**OTP Input:**
- input-otp 1.4

## Key Dependencies

**Critical (currently wired to Supabase, to be replaced):**
- `@supabase/supabase-js` 2.105 — PostgREST client + GoTrue auth + Storage + Edge Function invocation
  - Client initialized in `frontend/src/lib/supabase.ts` using `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY`
  - Targets `nestor` schema via `db: { schema: "nestor" }`
  - Auth session persisted under key `sb-nestor-auth` in localStorage

**Edge Function Runtime (reference, Deno):**
- Original edge functions import from `jsr:@supabase/supabase-js@2` or `https://esm.sh/@supabase/supabase-js@2`
- No npm deps in functions — all via Deno JSR / esm.sh CDN

**Nitro / Deployment:**
- `nitro` 3.0.260429-beta — server output layer
- `wrangler` (dev dep implied by `wrangler.jsonc`) — Cloudflare Workers deploy tooling

## Configuration

**Environment Variables (frontend, required):**
- `VITE_SUPABASE_URL` — Supabase project URL (used in `frontend/src/lib/supabase.ts`, direct `fetch` calls)
- `VITE_SUPABASE_ANON_KEY` — Supabase anon/public key

**Environment Variables (original edge functions, reference):**
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

**TypeScript:**
- Strict mode enabled; `moduleResolution: Bundler`; path alias `@/*` → `frontend/src/*`
- Config: `frontend/tsconfig.json`

**Build:**
- Vite config: `frontend/vite.config.ts` (extends `@lovable.dev/vite-tanstack-config`)
- Wrangler config: `frontend/wrangler.jsonc` (name: `nestor`, compat date 2025-09-24, `nodejs_compat` flag)
- Output: `.output/server/index.mjs` (server), `.output/public/` (static assets)

**shadcn/ui:**
- Config: `frontend/components.json` (style: new-york, baseColor: slate, cssVariables: true, iconLibrary: lucide)
- CSS: `frontend/src/styles.css`

## Platform Requirements

**Development:**
- Bun (package manager / runner)
- Node.js-compatible environment (Cloudflare `nodejs_compat` flag enabled)
- Env vars `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY` for local dev

**Production (Current):**
- Cloudflare Workers — SSR via Nitro + Wrangler deployment of `frontend/`

**Production (Target — to be built):**
- Frontend: remains on Cloudflare Workers (or can be re-targeted)
- Backend API: Cloud Run (FastAPI, `backend/` placeholder)
- Database: Cloud SQL (PostgreSQL), `infra/` placeholder
- Auth: Google Identity Platform
- File Storage: Google Cloud Storage

---

*Stack analysis: 2026-06-18*
