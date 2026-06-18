# External Integrations

**Analysis Date:** 2026-06-18

> **Convention used throughout this document:**
> - **[CURRENT]** — live in the existing Supabase-backed system; code exists in `frontend/` and `docs/supabase-functions/`
> - **[TARGET]** — planned GCP replacement per `README.md` and `docs/PROVENANCE.md`; no code exists yet (`backend/` and `infra/` are placeholders)

---

## APIs & External Services

### Anthropic Claude (LLM)

**[CURRENT]**
- Used by: `apply-intake-skill`, `generate-context-pack`, `extract-insights`, `generate-battlecard` edge functions
- Model: `claude-sonnet-4-5` (hardcoded in `docs/supabase-functions/apply-intake-skill.ts` and `generate-context-pack.ts`)
- Auth env var: `ANTHROPIC_API_KEY`
- Protocol: direct HTTPS POST to `https://api.anthropic.com/v1/messages`
- Max tokens: 8192 per call; cost estimation embedded in `apply-intake-skill.ts`

**[TARGET]**
- Same API, migrated into FastAPI Cloud Run service (`backend/` — to be built)

---

### OpenAI (Embeddings + Speech-to-text)

**[CURRENT]**
- Used by: `generate-embeddings`, `embed-artifact`, `embed-pending-search` (vector embeddings), `transcribe-audio` (Whisper)
- Embedding model: `text-embedding-3-small` (1536 dimensions) — `docs/supabase-functions/generate-embeddings.ts`
- Transcription model: `whisper-1` — `docs/supabase-functions/transcribe-audio.ts`
- Auth env var: `OPENAI_API_KEY`

**[TARGET]**
- Migrate into Cloud Run backend; embedding storage moves to Cloud SQL with pgvector or Vertex AI Vector Search

---

### SerpAPI (Web Search)

**[CURRENT]**
- Used by: `run-research` edge function (`docs/supabase-functions/run-research.ts`)
- Engine: Google; language `nl`, country `be`
- Fetches organic results, news results, answer boxes (up to 10 organic + 5 news per query)
- Auth env var: `SERPAPI_API_KEY`

**[TARGET]**
- Port to Cloud Run backend; same API

---

### SearchAPI (Web Search)

**[CURRENT]**
- Used by: `run-research` as a parallel search source alongside SerpAPI
- Engine: Google; language `nl`, country `be`; up to 10 organic results per query
- Auth env var: `SEARCHAPI_API_KEY`

**[TARGET]**
- Port to Cloud Run backend; same API

---

### Apify (Web Crawling)

**[CURRENT]**
- Used by: `run-research` — two actors:
  1. `apify~rag-web-browser` — semantic web search + markdown extraction (4 results per query, 80s timeout)
  2. `apify~website-content-crawler` — domain-specific full crawl (max 8 pages, Playwright adaptive, 160s timeout)
- Auth env var: `APIFY_API_TOKEN`
- All calls via `https://api.apify.com/v2/acts/...`

**[TARGET]**
- Port to Cloud Run backend; same API

---

### Resend (Transactional Email)

**[CURRENT]**
- Used by: `send-pulse-mail` (`docs/supabase-functions/send-pulse-mail.ts`), `send-sales-mail`, `sales-friday-reminder`
- Sender: `Nestor Pulse <nestor@agenic.be>`; admin default: `yanick@agenic.be`
- Mail types handled by `send-pulse-mail`: `validation_request`, `validation_reminder`, `results_ready`, `admin_validated`
- Auth env var: `RESEND_API_KEY`
- Protocol: POST to `https://api.resend.com/emails`
- HTML emails with inline CSS; logo served from Supabase public storage bucket

**[TARGET]**
- Notification-only email model (no bearer links in email body); same Resend API likely retained
- Auth moves to Identity Platform; email becomes "something is ready, check the app" pattern

---

### Tally (External Form Intake)

**[CURRENT]**
- Webhook ingestion: `tally-webhook` edge function (`docs/supabase-functions/tally-webhook.ts`)
- Auth: `x-webhook-secret` header (env var `TALLY_WEBHOOK_SECRET` or `INTAKE_WEBHOOK_SECRET`)
- Event type: `FORM_RESPONSE` only
- Field mapping: DB-driven via tables `tally_form_mappings`, `tally_field_mappings`, `tally_option_mappings`
- Creates `intake_respondents` row + `intake_answers` rows; idempotent via `responseId` → `invitation_token`

**[TARGET]**
- Port tally-webhook as a Cloud Run endpoint; keep DB-mapping pattern

---

### Jotform (External Form Intake — DEPRECATED)

**[CURRENT]**
- `jotform-webhook` function returns HTTP 410 Gone — retired in favour of Tally
- Source: `docs/supabase-functions/jotform-webhook.ts`

**[TARGET]**
- Not ported; deprecated

---

## Data Storage

### Databases

**[CURRENT] — Supabase Postgres (hosted)**
- Project ref: `inmsssedwdmgtnhaydmg`, region `eu-west-1`
- Schema: `nestor` (primary), `sales`, `public` (Supabase system schemas also present)
- Access: PostgREST via `@supabase/supabase-js`; `nestor` schema selected via `Accept-Profile` header
- Frontend client: `frontend/src/lib/supabase.ts` — `createClient(url, key, { db: { schema: "nestor" } })`
- 14 application tables: `organizations`, `organization_memberships`, `products`, `intakes`, `intake_answers`, `intake_templates`, `skill_runs`, `decompositions`, `research_questions`, `research_artifacts`, `findings`, `deliverables`, `artifact_embeddings`, `search_index`
- 27 RPCs (Postgres functions) used by the frontend — see `docs/BACKEND-MAP.md` for full list
- RLS: currently broken (`USING (true)` policies on core tables — see `docs/PROVENANCE.md` issue #1)
- Extensions implied: `pgvector` (for `artifact_embeddings`, 1536-dim embeddings)

**[TARGET] — Cloud SQL (PostgreSQL)**
- Cloud SQL instance in GCP project — `infra/` placeholder
- Same schema ported; proper org-scoped RLS (`tenant_id`/`worker_user` model per `PROVENANCE.md`)
- Alembic migrations (pattern from sibling repo `MOELD/Nestor`)

---

### File Storage

**[CURRENT] — Supabase Storage**
- Bucket: `nestor-uploads`
- Used by: `generate-context-pack` (writes context pack markdown as `research_artifact`), `run-research` (writes raw provider JSON per question per source at path `{intake_id}/research/{question_id}/{label}.json`), `transcribe-audio`, `upload-pending-artifacts`
- Public bucket also used for email logo asset (`email bucket public/Agenic Logo BW 001.png`)
- Client access: via Supabase Storage API (service role key in edge functions)

**[TARGET] — Google Cloud Storage (GCS)**
- Single GCS bucket replaces `nestor-uploads`
- All storage paths preserved where possible
- Access mediated by Cloud Run backend (no direct browser → GCS)

---

### Caching

- **[CURRENT]** None — no Redis or in-memory cache layer
- **[TARGET]** Not specified; likely none initially

---

## Authentication & Identity

### Supabase GoTrue

**[CURRENT]**
- Provider: Supabase GoTrue (hosted auth)
- Frontend client: `frontend/src/lib/auth-context.tsx` — listens to `supabase.auth.onAuthStateChange`; handles PKCE code-exchange (`?code=` param) for OAuth callback
- Session persisted: `localStorage` under key `sb-nestor-auth`
- Admin login route: `frontend/src/routes/admin.login.tsx`
- Auth callback route: `frontend/src/routes/auth.callback.tsx`
- Auth login route: `frontend/src/routes/auth.login.tsx`
- Client access model: **never-expiring bearer tokens** in email links (`client_intake_token`, `client_validation_token`, `client_results_token`) — identified as critical security issue in `docs/PROVENANCE.md`
- anon key has overly broad INSERT/UPDATE/DELETE grants on 11 tables (security issue #2 in `docs/PROVENANCE.md`)

**[TARGET] — Google Identity Platform**
- Already enabled on the GCP project (per `README.md`)
- Replaces GoTrue entirely
- First-login org provisioning pattern available from sibling `MOELD/Nestor`
- Token-based client routes replaced by authenticated "spaces" with notification-only email

---

## Monitoring & Observability

**Error Tracking:**
- **[CURRENT]** None detected — no Sentry, Datadog, or equivalent imports in `frontend/src/`

**Logs:**
- **[CURRENT]** Console logging in edge functions; frontend uses `sonner` toasts for user-facing errors
- **[TARGET]** Cloud Logging (Cloud Run emits stdout/stderr automatically)

---

## CI/CD & Deployment

### Frontend Hosting

**[CURRENT]**
- Platform: Cloudflare Workers
- Deploy via Wrangler — config `frontend/wrangler.jsonc` (name: `nestor`)
- SSR layer: Nitro (`frontend/package.json` `nitro` dep, `wrangler.jsonc` references `.output/server/index.mjs`)
- Dev URL: `https://start-bloom-flow.lovable.app` (Lovable preview, referenced in `send-pulse-mail.ts` as default `NESTOR_BASE_URL`)

**[TARGET]**
- Frontend hosting strategy not yet decided; Cloudflare Workers may be retained or migrated to Cloud Run / Firebase Hosting

### Backend Hosting

**[CURRENT]**
- Supabase EdgeRuntime (Deno) — 21 edge functions

**[TARGET]**
- Google Cloud Run — FastAPI Python service (`backend/` placeholder)

### CI Pipeline

**[CURRENT / TARGET]**
- None detected in repo — no `.github/`, CircleCI, or Cloud Build config present

---

## Webhooks & Callbacks

### Incoming Webhooks

**[CURRENT]**
- `POST /functions/v1/tally-webhook` — receives Tally form submission events (`FORM_RESPONSE`)
  - Auth: `x-webhook-secret` header
  - Source: `docs/supabase-functions/tally-webhook.ts`
- `POST /functions/v1/jotform-webhook` — DEPRECATED, returns 410 Gone

**[TARGET]**
- Equivalent `POST /webhooks/tally` endpoint on Cloud Run; same secret-header auth pattern

### Outgoing Webhooks

**[CURRENT]**
- None — all external calls are request-response (Anthropic, OpenAI, SerpAPI, SearchAPI, Apify, Resend)

---

## Environment Configuration

**Required frontend env vars (Vite `VITE_` prefix, exposed to browser):**
- `VITE_SUPABASE_URL` — Supabase project URL
- `VITE_SUPABASE_ANON_KEY` — Supabase anon key

**Required edge function env vars (Supabase secrets, not in repo):**
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `SERPAPI_API_KEY`, `SEARCHAPI_API_KEY`, `APIFY_API_TOKEN`
- `RESEND_API_KEY`
- `TALLY_WEBHOOK_SECRET` (or `INTAKE_WEBHOOK_SECRET`)
- `NESTOR_BASE_URL`, `NESTOR_ADMIN_EMAIL`

**Secrets location:**
- **[CURRENT]** Supabase project secrets dashboard (never committed)
- `.pat` file (Supabase Management API personal access token) — gitignored, outside repo
- `.gitignore` present at repo root — contents not read

---

*Integration audit: 2026-06-18*
