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
- ✓ FastAPI backend on Cloud Run mediating ALL data access (no direct browser→DB) — v1.0
- ✓ Cloud SQL (Postgres + pgvector) schema via Alembic migrations, incl. empty `findings`/`deliverables` Tribunal handoff tables — v1.0
- ✓ Identity Platform auth replacing Supabase GoTrue; login required for everyone — v1.0
- ✓ Per-client spaces with org-scoped isolation enforced at the API layer + RLS, proven by CI-gated cross-tenant denial suite — v1.0
- ✓ superadmin (cross-tenant) and user (own space) roles via server-set custom claims — v1.0
- ✓ Bearer-link client access removed; email is notification-only — v1.0
- ✓ Frontend data layer re-pointed to `lib/api/*` (zero Supabase calls) — v1.0
- ✓ All seven pre-research AI functions ported to Cloud Run — v1.0
- ✓ GCS signed-URL storage replacing `nestor-uploads` — v1.0
- ✓ Multi-language UI NL/FR/EN — v1.0
- ✓ Frontend hosted on GCP (Cloud Run SSR container, D-11 no-Supabase-bundle guard) — v1.0
- ✓ E2E flow on GCP + Supabase independence — v1.0 (PARITY ACCEPTED WITH DEFERRALS 2026-07-20: 21 UAT items → post-Tribunal, ledger in phase-12 12-UAT.md; independence-only per D-08, legacy project untouched)

### Active

<!-- v1.1 Tribunal Integration — scoped 2026-07-20 via /gsd-new-milestone. -->

- [ ] Tribunal engine (`nestor_pulse_sdk`) redeployed into the intake GCP project (API + async worker on Cloud Run), driven server-to-server by the intake backend
- [ ] Tribunal standalone app retired: own logins/orgs/screens removed from the flow; intake auth + spaces govern research runs
- [ ] Superadmin triggers research on a `decomposed` intake (status → `in_research`), sees run step details in the admin UI (Tribunal screens adapted to intake design), gets email on completion
- [ ] Full research output stored as a superadmin-only downloadable file
- [ ] Superadmin uploads final report PDF (crafted externally in Claude Design) → client sees it in their UI (status → `delivered`) + client email notification
- [ ] Q&A chat over indexed research findings (port of legacy `ask-research`: Voyage embeddings + Claude Haiku), for client + superadmin after delivery
- [ ] Deferred v1.0 UAT ledger re-run (21 items — see STATE.md Deferred Items)
- [ ] Chores: Resend key rotation, Cloud Build suite rerun, NDA PDF drop + image rebuild, legacy VITE_SUPABASE_* env cleanup
- [ ] Open product decisions: Templates page visibility, Intake-info link-row trimming, "Verzonden mails" history block

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
| v1.1: Redeploy Tribunal into the intake GCP project | One project to operate; avoids cross-project IAM/DB sprawl | — Pending |
| v1.1: Retire Tribunal standalone app (logins/orgs/UI) | One login + one UI; intake auth/spaces govern research runs; Tribunal screens re-skinned in intake design | — Pending |
| v1.1: Human-in-the-loop report (Claude Design, external) | Raw engine output is superadmin-only; client gets a hand-polished PDF, not raw findings | — Pending |
| v1.1: Voyage embeddings (`voyage-3-large`) for Q&A chat | Fidelity to legacy `ask-research` behavior; accepted cost: new vendor + API key alongside OpenAI | — Pending |

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
## Current State (v1.0 shipped 2026-07-20)

Live on GCP project "Nestor Pulse": frontend `nestor-frontend` rev 00010-ndr + backend `nestor-api`
rev 00024-67b (Cloud Run, europe-west1), Cloud SQL Postgres 16 + pgvector at alembic 0010, Identity
Platform auth, GCS storage, Resend mail. 12 phases / 70 plans / 485 commits in 33 days. Deferred at
close: 21 UAT items + chores (STATE.md Deferred Items). Legacy Supabase project intact but unused
(independence-only retirement, D-08).

## Current Milestone: v1.1 Tribunal Integration

**Goal:** Absorb the existing Tribunal deep-research engine (`MOELD/Nestor/nestor_pulse_sdk`) into
the GCP intake platform — one project, one login, one UI — extending the flow from `decomposed`
through research, human-crafted report delivery, and a client Q&A chat over the indexed findings.

**Target features:**
- Tribunal API + worker redeployed as Cloud Run services in the intake GCP project; standalone app (own logins/orgs/screens, own GCP project `project-cb01b861`) retired from the flow
- Superadmin research trigger on `decomposed` intakes; run progress/step details adapted into the intake admin UI design; completion email to superadmin
- Raw research output as a superadmin-only downloadable file (nothing client-visible until delivery)
- Human report step: superadmin crafts report in Claude Design externally, uploads final PDF → client UI + email notification (status → `delivered`)
- Q&A chat over indexed findings (legacy `ask-research` port: `voyage-3-large` embeddings + Claude Haiku RAG), client + superadmin, post-delivery
- Deferred v1.0 UAT ledger re-run (21 items) + carried-over chores

**Key context (established during scoping):**
- The Tribunal engine is already coded and was mid-dev-round on its own GCP project (skeptic
  verification pipeline, budget governor, citations, audit trail; Cloud Run `nestor-pulse-api` +
  `nestor-pulse-worker`, own Cloud SQL `nestor-prod-pg`, own Alembic line). This milestone is
  re-homing + integration, not engine building.
- Open architecture decision: merge Tribunal's DB into the intake Cloud SQL instance vs. separate
  database in the same project.
- Open comparison: legacy `run-research.ts` (SerpAPI/SearchAPI/Apify) vs. Tribunal — user unsure
  whether anything is lost; research must settle it.
- Research must establish what actually works in Tribunal today (dev state had pending verify steps
  as of 2026-06-15).

---
*Last updated: 2026-07-22 (Phase 18 complete — human report delivery live: staged upload +
explicit Deliver verb (`in_research → delivered`), client report page + download, delivery mail;
api rev 00038-7jp / frontend rev 00018-m6x; verification passed 17/17; replace click-through
operator-accepted, re-verify at next delivery)
