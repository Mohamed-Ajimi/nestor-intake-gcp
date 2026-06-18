# Nestor Intake (GCP Re-platform)

## What This Is

Nestor Intake is the agentic "Pulse" intake application built by Agenic — clients fill in a
structured, multi-section intake form, and operators run AI skills over the answers to produce a
validated set of research questions and a context pack (the flow that runs *before* the deep-research
engine). This project re-platforms the entire pre-research flow off its original third-party
**Supabase** build and onto **Google Cloud Platform** (FastAPI on Cloud Run, Cloud SQL, Identity
Platform, GCS), while introducing real per-tenant isolation ("spaces"), proper authentication, and a
multi-language UI. The deep-research stage (Tribunal) is explicitly a separate track and out of scope
here — this flow stops at status `decomposed`.

## Core Value

A logged-in superadmin or client user can run an intake end-to-end on GCP — from form submission
through AI skill application to a validated, decomposed context pack — with each client's data fully
isolated to its own space, and with the legacy Supabase system fully retired.

## Requirements

### Validated

<!-- Capabilities the existing frontend already delivers (currently on Supabase). These define
feature parity the re-platform must preserve. -->

- ✓ Multi-section intake form with save-as-you-go and submit (token flow today) — existing
- ✓ Admin intake lifecycle management driven by a phase machine (`draft → submitted → reviewed → validated_by_client → decomposed`) — existing
- ✓ AI skill application over intake answers (`apply-intake-skill`) with per-field reviewable output — existing
- ✓ Admin AI review UX: accept / edit / reject each AI-suggested field — existing
- ✓ Context pack generation (`generate-context-pack`) — existing
- ✓ Answer structuring (`structure-answers`) and insight extraction (`extract-insights`) — existing
- ✓ Semantic search over embedded artifacts (embeddings + pgvector) — existing
- ✓ Audio transcription of intake inputs (Whisper) — existing
- ✓ Transactional email notifications (Resend) — existing
- ✓ Admin authentication (magic-link OTP) — existing
- ✓ Client organizations, products, and intake templates management — existing

### Active

<!-- The v1 GCP re-platform milestone. Building toward full cutover. -->

- [ ] FastAPI backend on Cloud Run that mediates ALL data access (no direct browser→DB)
- [ ] Cloud SQL (Postgres + pgvector) schema via migrations — includes `findings` / `deliverables` (kept empty, Tribunal handoff target)
- [ ] Identity Platform auth replacing Supabase GoTrue; **login required for everyone**
- [ ] Per-client **spaces** with real org-scoped isolation enforced at the API layer
- [ ] **superadmin** (Agenic, cross-tenant) and **user** (own space only) roles
- [ ] Bearer-link client access removed; email becomes notification-only ("something is ready, log in")
- [ ] Frontend data layer re-pointed off Supabase to the new GCP API client
- [ ] All pre-research AI functions ported to Cloud Run (apply-intake-skill, generate-context-pack, structure-answers, extract-insights, embeddings + semantic search, transcribe-audio)
- [ ] GCS storage replacing the `nestor-uploads` bucket
- [ ] Multi-language UI: **NL / FR / EN** (i18n)
- [ ] Frontend hosted on GCP (Cloud Run or Firebase Hosting)
- [ ] End-to-end flow validated on GCP for superadmin + user; Supabase project retired

### Out of Scope

- Tribunal / `run-research` / deep-research & verification engine — separate track; this flow ends at `decomposed`
- **client-admin** role — deferred to a later milestone (only superadmin + user in v1)
- Tally external-form intake ingestion — dropped for v1 (incompatible with login-only model)
- Jotform webhook — already deprecated (returns 410)
- Migration of existing Supabase production data — **starting fresh** on an empty Cloud SQL database
- Populating `findings` / `deliverables` with data — tables exist for the future Tribunal track

## Context

- **Origin:** The frontend (`frontend/`) is the existing Lovable-built React 19 + TanStack + shadcn app.
  It is kept; only its data/auth layer is re-platformed. Full original-backend mapping lives in
  `docs/BACKEND-MAP.md`, with edge-function source in `docs/supabase-functions/` and provenance +
  known security issues in `docs/PROVENANCE.md`.
- **Driving problem:** The original Supabase build has critical security flaws — broken RLS
  (`USING (true)` lets any logged-in user read/write all tenants' data), broad anon-key write grants,
  never-expiring bearer links, and a client-side-only admin auth guard. These are the primary reason
  for the re-platform.
- **Migration seam:** The Supabase client (`frontend/src/lib/supabase.ts`) is imported across ~34
  files with no data-access abstraction. Introducing an API-client module is the key refactor.
- **Reference patterns:** A sibling repo (`MOELD/Nestor`) provides the tenant/`worker_user` isolation
  pattern and Alembic migration conventions to follow.
- **GCP project:** Identity Platform is already enabled.
- **External AI dependencies (retained, keys move server-side):** Anthropic Claude
  (`claude-sonnet-4-5` today), OpenAI (`text-embedding-3-small`, `whisper-1`). SerpAPI / SearchAPI /
  Apify belong to `run-research` and stay out of scope.
- **Backend is greenfield:** `backend/` and `infra/` are empty placeholders today — 0% built.

## Constraints

- **Tech stack**: GCP-mandated — FastAPI on Cloud Run, Cloud SQL (Postgres + pgvector), Identity Platform, GCS — replaces the entire Supabase stack.
- **Backend language**: Python / FastAPI — per project direction.
- **Frontend**: Existing React 19 + TanStack Router/Query + shadcn app retained; only data + auth layers swapped. `frontend/src/components/ui/` (shadcn) not modified directly.
- **Security**: No cross-tenant access. Tenant isolation enforced server-side at the API layer; the broken-RLS class of bug must not recur. All writes mediated by the backend.
- **Scope ceiling**: Flow ends at `decomposed`. `run-research` must never be invoked from the new frontend/backend credentials.
- **Cutover model**: Big-bang — Supabase is retired once the GCP path is validated end-to-end (no long-lived dual-run).
- **No test coverage today**: The existing codebase has zero automated tests — a safety net must be built alongside the migration.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Full big-bang cutover (retire Supabase) | Clean break; avoids maintaining two systems and the leaky anon-key path | — Pending |
| Start with an empty Cloud SQL database (no data migration) | No production data worth migrating; clean slate avoids porting legacy/broken rows | — Pending |
| Roles limited to superadmin + user for v1 | Keeps the auth/permission model simple; client-admin can come later | — Pending |
| Login required for all; remove bearer links | Eliminates the never-expiring-link security flaw; email becomes notification-only | — Pending |
| Per-client spaces, isolation enforced at API layer | Fixes the #1 security issue (cross-tenant exposure) without relying on DB RLS alone | — Pending |
| Full AI feature parity in v1 | End-to-end cutover requires every pre-research function the old app used | — Pending |
| Move frontend to GCP | Consolidate the whole system on one platform | — Pending |
| Multi-language UI (NL/FR/EN) | Broader client reach; done now rather than retrofitted later | — Pending |
| Include `findings`/`deliverables` tables (empty) | Preserve the Tribunal handoff contract in the schema without populating them | — Pending |
| Drop Tally/Jotform external-form intake | Anonymous external forms conflict with the login-only model | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-18 after initialization*
