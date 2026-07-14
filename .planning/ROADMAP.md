# Roadmap: Nestor Intake (GCP Re-platform)

## Overview

This is a big-bang re-platform of the Nestor Intake pre-research flow off Supabase and onto GCP
(FastAPI on Cloud Run, Cloud SQL + pgvector, Identity Platform, GCS), driven by the inherited
cross-tenant security flaws. The journey follows the research build order: lay the schema with
`space_id` FKs and real RLS, stand up the FastAPI service against Cloud SQL, add Identity Platform
auth, then **prove tenant isolation with a CI-gated cross-tenant denial suite before any feature
endpoint ships**. From that secure foundation we layer user/space management, intake CRUD parity
behind a single frontend `lib/api/*` seam, the seven AI function ports, SSE skill-run progress, GCS
signed-URL storage, notification-only email, NL/FR/EN i18n, and finally a validated end-to-end
cutover for both superadmin and user roles with Supabase retired. The scope ceiling is hard: the
flow stops at `decomposed` — `run-research`/Tribunal is never reachable from the new credentials.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Schema & Migrations** - Alembic-managed `nestor` schema on empty Cloud SQL with `space_id` FKs, real RLS, and a CI guard banning `USING(true)`
- [ ] **Phase 2: Backend Skeleton & Cloud SQL Wiring** - FastAPI on Cloud Run reachable from the browser, connected to Cloud SQL with safe pooling
- [ ] **Phase 3: Identity Platform Auth** - Login required everywhere; server-side token verification with role/space custom claims; bearer links removed
- [ ] **Phase 4: Tenant Isolation (Proven by Tests)** - Single tenant-scoped repository layer + CI-gated cross-tenant denial suite that gates everything downstream
- [x] **Phase 5: User & Space Management** - Superadmin invites users to spaces, JIT provisioning, deactivation, manages client spaces/templates, with audit trail
- [ ] **Phase 6: Intake CRUD Parity & Frontend API Seam** - Frontend re-pointed off Supabase to `lib/api/*`; authenticated intake fill/submit/view + phase machine to `decomposed`
- [x] **Phase 7: AI Function Ports** - All seven pre-research AI functions on Cloud Run, space-scoped, DB connection released across LLM calls (completed 2026-07-13)
- [ ] **Phase 8: SSE Skill-Run Progress** - DB-backed Server-Sent Events stream replaces Supabase Realtime for skill-run progress
- [x] **Phase 9: GCS Storage** - Signed-URL upload/download via attached-SA `signBlob`, space-scoped, replacing `nestor-uploads` (completed 2026-07-13)
- [x] **Phase 10: Notifications** - Notification-only transactional email (no tokens) for invite/validation-ready/results-ready/reminders (completed 2026-07-13)
- [x] **Phase 11: Internationalization (NL/FR/EN)** - react-i18next with all hardcoded Dutch strings externalized and a working language switcher (completed 2026-07-14)
- [ ] **Phase 12: Frontend Deploy, Cutover & Supabase Retirement** - SSR frontend on Cloud Run, end-to-end validated for both roles, Supabase paused then retired

## Phase Details

### Phase 1: Schema & Migrations
**Goal**: An empty Cloud SQL Postgres 16 database carries the full `nestor` schema via Alembic, with `space_id NOT NULL` FKs and real (non-`true`) RLS policies on every tenant-owned table, and CI refuses any migration that weakens isolation.
**Depends on**: Nothing (first phase)
**Requirements**: INFRA-02, TENANT-01, TENANT-05, QA-02
**Success Criteria** (what must be TRUE):
  1. Running `alembic upgrade head` on an empty database creates all `nestor` tables, including empty `findings`/`deliverables`, with no errors
  2. Every tenant-owned table has a `space_id NOT NULL` foreign key and an enabled RLS policy keyed on a per-session GUC (none use `USING (true)` / `WITH CHECK (true)`)
  3. A CI check fails the build when any migration contains `USING (true)` or `WITH CHECK (true)`
  4. The schema is built with HNSW/`vector_cosine_ops` intent for 1536-dim embeddings, with no IVFFlat index created on the empty table
**Plans**: 4 plans (4 waves)
  - [x] 01-01-PLAN.md — Test harness: pytest + pgvector:pg16 testcontainers, failing schema/RLS suites (Wave 0)
  - [x] 01-02-PLAN.md — Baseline schema: 14 tables, space_id NOT NULL FKs, vector(1536) no index (Wave 2)
  - [x] 01-03-PLAN.md — RLS isolation + superadmin bypass + QA-02 CI guard (Wave 3)
  - [x] 01-04-PLAN.md — In-scope triggers + standalone dev seed (Wave 4)

### Phase 2: Backend Skeleton & Cloud SQL Wiring
**Goal**: A deployable FastAPI service runs on Cloud Run gen2, connects to Cloud SQL through the Python connector with IAM auth and bounded pooling, and is the only path to the database.
**Depends on**: Phase 1
**Requirements**: INFRA-01, INFRA-04, API-01
**Success Criteria** (what must be TRUE):
  1. A health-check endpoint on the deployed Cloud Run service returns OK and proves connectivity to Cloud SQL via the connector (IAM DB auth, no proxy sidecar, no password in env/image)
  2. SQLAlchemy pools are bounded (`pool_size` 2–5, `pool_pre_ping`, `pool_recycle`) and Cloud Run `max-instances` is capped so worst-case connections stay under the tier limit
  3. Alembic migrations run as a discrete one-shot job, not on app startup across instances
  4. No data-access path exists that bypasses the backend (the browser cannot reach the database directly)
**Plans**: 3 plans (3 waves)
  - [x] 02-01-PLAN.md — App skeleton + mode-switched connector engine factory + bounded pools + health endpoints (Wave 1)
  - [x] 02-02-PLAN.md — Migration-Job-enabled env.py connector branch + multi-stage uv Dockerfile (Wave 2)
  - [x] 02-03-PLAN.md — Terraform IaC + runtime-SA GRANT migration + Cloud Shell deploy runbook (Wave 3)

### Phase 3: Identity Platform Auth
**Goal**: Every request is authenticated by Identity Platform, verified server-side, with role and space carried as server-set custom claims, and the legacy bearer-link access model is gone.
**Depends on**: Phase 2
**Requirements**: AUTH-01, AUTH-02, AUTH-03, AUTH-05
**Success Criteria** (what must be TRUE):
  1. Every API endpoint and frontend route requires a valid Identity Platform login; there are no anonymous routes and the disabled admin guard is restored as a real guard
  2. The backend verifies the ID token via `verify_id_token` (signature, `iss`, `aud`, expiry) on every request and rejects expired/wrong-audience/revoked tokens
  3. A user's `role` (superadmin | user) and `space_id` exist as Identity Platform custom claims, set only server-side via the Admin SDK — never trusted from the browser
  4. All never-expiring bearer-link routes/columns (`client_intake_token`, `client_validation_token`, `client_results_token`) are removed from the access path
**Plans**: TBD
**UI hint**: yes

### Phase 4: Tenant Isolation (Proven by Tests)
**Goal**: Tenant scoping is structurally impossible to omit — a single repository layer derives `space_id` from the verified token, superadmin sees all and users are hard-pinned to one space — and a CI-gated cross-tenant denial suite proves it before any feature endpoint ships.
**Depends on**: Phase 3
**Requirements**: API-02, TENANT-02, TENANT-03, QA-01
**Success Criteria** (what must be TRUE):
  1. All data access flows through one repository layer where the tenant filter cannot be omitted per-endpoint; `space_id` comes only from the verified token, never from a request body/path/query
  2. A superadmin can read across all spaces while a user is denied access to any space but their own (default-deny enforced at the API layer)
  3. A CI-gated cross-tenant denial test suite proves a user token gets 403/404 (never 200-with-data) on another space's resources, including reads and writes
  4. The Postgres RLS GUC is set/reset per connection checkout so pooled connections never leak tenant context
**Plans**: 4 plans (2 waves)
  - [x] 04-01-PLAN.md — D-03 CI grep-guard banning raw DB access outside app/db/ + positive/negative test (Wave 1)
  - [x] 04-02-PLAN.md — app_superadmin engine (Path B) + checkin GUC reset + TenantRepository + session dependency + repo/GUC integration suite (Wave 1)
  - [x] 04-03-PLAN.md — throwaway sample endpoint over intakes + full-stack cross-tenant denial suite (Wave 2)
  - [x] 04-04-PLAN.md — Terraform app_superadmin user + Secret Manager + secretAccessor + google-cloud-secret-manager dep + Cloud Build integration gate (Wave 2)

### Phase 5: User & Space Management
**Goal**: A superadmin can fully administer client spaces, templates, and user accounts — inviting users into exactly one space, with JIT provisioning, deactivation, and a security audit trail.
**Depends on**: Phase 4
**Requirements**: USER-01, USER-02, USER-03, AUTH-04, QA-04
**Success Criteria** (what must be TRUE):
  1. A superadmin can invite a user, assigning them exactly one space with the `user` role
  2. An invited user provisions their account on first login (JIT) with `role`/`space_id` claims attached server-side
  3. A superadmin can deactivate a user (Identity Platform disabled + refresh tokens revoked); the backend re-checks disabled state and denies access
  4. A superadmin can create and manage client spaces (organizations) and their intake templates
  5. Security-relevant events (auth, invitations, role/space assignment, status transitions, downloads) are logged with actor + space
**Plans**: 5 plans (3 waves)
  - [x] 05-01-PLAN.md — Wave 0 RED test scaffold: invite/deactivate/audit/AUTH-04/schema-shape suites (Wave 1)
  - [x] 05-02-PLAN.md — 0006 migration (status cols + root audit_log + grants) + AuditLog model + audit.log helper (Wave 1)
  - [x] 05-03-PLAN.md — admin_users Admin-SDK wrapper + AUTH-04 check_revoked boundary + /auth/session tightening (Wave 1)
  - [x] 05-04-PLAN.md — get_admin_session + AdminRepo + admin_routes (invite/deactivate/space/template) with audit + guardrails (Wave 2)
  - [x] 05-05-PLAN.md — thin lib/api slice + four superadmin screens per locked UI-SPEC (Wave 3)
**UI hint**: yes

### Phase 6: Intake CRUD Parity & Frontend API Seam
**Goal**: The intake flow reaches full authenticated parity to `decomposed` with all frontend data access centralized in `frontend/src/lib/api/*`, replacing every inline Supabase call, and the scope guard prevents `run-research` invocation.
**Depends on**: Phase 5
**Requirements**: API-03, INTAKE-01, INTAKE-02, INTAKE-03, INTAKE-04, INTAKE-05, TENANT-04, QA-03
**Success Criteria** (what must be TRUE):
  1. The frontend's data access is centralized in `frontend/src/lib/api/*` modules; no inline `supabase.from(...)` calls remain in routes/components
  2. A logged-in user can open, fill (save-as-you-go, batched), and submit a multi-section intake form, and view their results
  3. The admin lifecycle advances through the phase machine (submitted → reviewed → validated_by_client → decomposed), driven by backend endpoints + DB triggers
  4. A user sees only their own space's intakes while a superadmin has a space selector/switcher
  5. Characterization tests cover the phase machine, and a scope guard makes `run-research` unreachable from the new frontend/backend credentials (flow stops at `decomposed`)
**Plans**: 13 plans (5 waves + 2 gap-closure waves)
  - [x] 06-01-PLAN.md — Backend repo + session foundation: per-entity TenantRepository subclasses + .session/create/upsert_batch + per-entity deps (Wave 1)
  - [x] 06-02-PLAN.md — Frontend vitest runner + QA-03 derivePhase characterization (Wave 1)
  - [x] 06-03-PLAN.md — intake_routes.py CRUD/reads + transitions + audit + mount + test_intake_routes (Wave 2)
  - [x] 06-04-PLAN.md — Re-point cross-tenant denial -> /intakes + delete sample_routes + route-absence test (Wave 3)
  - [x] 06-05-PLAN.md — Frontend lib/api seam (intakes/answers/templates/skillRuns/search) + active-space provider + shared StatusPill (Wave 3)
  - [x] 06-06-PLAN.md — Admin intake detail re-point + IntakeForm section-batch save + delete run-research/send-pulse-mail (Wave 4)
  - [x] 06-07-PLAN.md — Admin list/new/clients/search/index re-point onto the seam (Wave 4)
  - [x] 06-08-PLAN.md — Global space switcher (ProductShell + SpaceSwitcher, superadmin-only) (Wave 4)
  - [x] 06-09-PLAN.md — Authenticated user intake surface: list -> fill -> submit -> results (Wave 4)
  - [x] 06-10-PLAN.md — Neutralize post-decomposed/storage components + storage seam stub + intake-surface sweep (Wave 4)
  - [x] 06-11-PLAN.md — Scope guard: ci_no_run_research.sh + positive/negative guard test (Wave 5)
  - [x] 06-12-PLAN.md — GAP: tenant isolation on the answers write path (upsert ownership 404 + repo scoped WHERE + denial test) (Gap Wave 1)
  - [x] 06-13-PLAN.md — GAP: functional superadmin space filter (list_intakes space_id param + superadmin narrowing + tests + header copy) (Gap Wave 2)
**UI hint**: yes

### Phase 7: AI Function Ports
**Goal**: All seven pre-research AI functions run on Cloud Run with parity behavior and full space-scoping, never holding a DB connection across an LLM/Whisper call, and semantic search never leaks across tenants.
**Depends on**: Phase 6
**Requirements**: AI-01, AI-02, AI-03, AI-04, AI-05, AI-06
**Success Criteria** (what must be TRUE):
  1. `apply-intake-skill` runs on Cloud Run producing per-field reviewable output with the admin accept/edit/reject UX preserved
  2. `generate-context-pack`, `structure-answers`, and `extract-insights` run on Cloud Run with parity behavior
  3. Embeddings generation and semantic search run on Cloud Run with results filtered by `space_id` (an `EXPLAIN` shows index use with a tenant prefilter; a user's search never returns another space's artifacts)
  4. Audio transcription (Whisper) runs on Cloud Run
  5. AI/LLM calls release the DB session before the call and reopen to persist — no connection held across a 90–120s call
**Plans**: 8 plans (4 waves) + 3 gap-closure plans (combined 7+8+9 live-UAT findings, 2 waves)
  - [x] 07-01-PLAN.md — Wave 0 RED test scaffold: 10 AI test modules + conftest fakes (faked external calls) (Wave 1)
  - [x] 07-02-PLAN.md — 0009 migration + 3 new models (intake_sources/transcripts/extracted_insights) + parity columns + repository subclasses (Wave 1)
  - [x] 07-03-PLAN.md — AI client seam: anthropic/openai SDKs + verbatim prompts + extract_json/cost ports + D-06 model-id config (Wave 1)
  - [x] 07-08-PLAN.md — Secret Manager API keys + Cloud Run CPU-always/min-instances=0 + deploy runbook + scope-guard regression (Wave 1)
  - [x] 07-04-PLAN.md — D-05 session-release helper (tenant_session/run_with_session_release) + search_artifacts + orphan sweep (Wave 2)
  - [x] 07-05-PLAN.md — ai_routes surface (7 endpoints) + apply-intake-skill (AI-01) + generate-context-pack (AI-02) + mount + sweep (Wave 3)
  - [x] 07-06-PLAN.md — Embeddings generation + semantic search, space-prefiltered (AI-04) (Wave 4)
  - [x] 07-07-PLAN.md — structure-answers + extract-insights (AI-03) + transcribe-audio (AI-05, faked audio) (Wave 4)
  - [x] 07-09-PLAN.md — [gap] artifacts-read endpoint (GET /context-pack, existence-hidden) + skill discriminator on SkillRunView (Wave 1)
  - [x] 07-11-PLAN.md — [gap] AI trigger UI (structure/extract/embeddings/transcribe) + Kopieer-intake-link fix + template-asset static serving (Wave 1)
  - [x] 07-10-PLAN.md — [gap] ContextPackBlock read wiring + context-pack progress UX + apply-intake-skill run discriminator consumers (Wave 2)

### Phase 8: SSE Skill-Run Progress
**Goal**: Skill-run progress streams to the admin UI via a stateless, DB-backed Server-Sent Events endpoint, replacing the Supabase Realtime subscription.
**Depends on**: Phase 7
**Requirements**: API-04
**Success Criteria** (what must be TRUE):
  1. The admin UI receives live skill-run progress over a `text/event-stream` SSE endpoint and stops streaming on terminal status
  2. The SSE handler reads `skill_runs` state from Cloud SQL each tick (no in-memory state) so any instance can serve a reconnecting client
  3. The SSE stream is tenant-scoped — a user cannot stream another space's skill run
**Plans**: 3 plans (1 wave)
  - [x] 08-01-PLAN.md — Backend SSE stream + full-run read (D-08): stream_session helpers, async StreamingResponse endpoint, RED suites (Wave 1)
  - [x] 08-02-PLAN.md — Frontend SSE reader + SSE-first useActiveSkillRun (poll fallback) + un-stubbed useSkillRunFull + terminal refresh (Wave 1)
  - [x] 08-03-PLAN.md — Cloud Run 900s request timeout (main.tf) + deploy-runbook live-apply note (Wave 1)
**UI hint**: yes

### Phase 9: GCS Storage
**Goal**: File upload and download go through the backend using short-TTL GCS V4 signed URLs minted with the attached service account's `signBlob`, space-scoped, replacing the `nestor-uploads` bucket.
**Depends on**: Phase 6
**Requirements**: INFRA-03, DOC-01, DOC-02
**Success Criteria** (what must be TRUE):
  1. A GCS bucket replaces `nestor-uploads` and the backend mints signed URLs via IAM `signBlob` with no service-account JSON key present anywhere
  2. A user can download an artifact only after the backend verifies they own the artifact's space, via a V4 signed URL with TTL ≤ 15 minutes
  3. Intake attachments and audio uploads are stored in GCS through the backend, never direct browser→storage, with objects namespaced by space
**Plans**: 4 plans (2 waves)
  - [x] 09-01-PLAN.md — Storage foundation: app/storage seam (keys + gcs), config, no-SA-key grep-guard, Wave-0 RED tests + fake_gcs (Wave 1)
  - [x] 09-02-PLAN.md — Backend storage endpoints (upload/signed-url/delete) + combined-repos DI + transcribe seam swap (Wave 2)
  - [x] 09-03-PLAN.md — Frontend seam finalization (drop bucket, add category, FormData guard) + 5 call sites (Wave 2)
  - [x] 09-04-PLAN.md — Bucket + keyless-signBlob IAM (Terraform + gcloud runbook) + combined 7+8+9 live UAT (Wave 2)

### Phase 10: Notifications
**Goal**: Transactional email becomes notification-only — it carries no access token and links route to authenticated pages — covering the full set of lifecycle events.
**Depends on**: Phase 5
**Requirements**: NOTIF-01, NOTIF-02
**Success Criteria** (what must be TRUE):
  1. Every transactional email carries no access token; links point to authenticated app routes ("log in to view")
  2. Email is sent for invitation, validation-ready, results-ready, and reminder events
**Plans**: 5 plans (3 waves)
  - [x] 10-01-PLAN.md — Backend mail module: Resend transport + Jinja2 templates + config + fake_resend + NOTIF-01 render tests (Wave 1)
  - [x] 10-02-PLAN.md — Infra: RESEND_API_KEY secret + NESTOR_ADMIN_EMAIL/APP_BASE_URL env + deploy runbook (Wave 1)
  - [x] 10-03-PLAN.md — Backend send endpoints + recipient resolution + admin_validated + invite-mail + ActionCodeSettings + denial/D-16 tests (Wave 2)
  - [x] 10-04-PLAN.md — Frontend: RecipientPicker + un-stub 3 CTAs + invite-mail buttons + seam + logo asset (Wave 3)
  - [x] 10-05-PLAN.md — Frontend /auth/action oobCode handler route (invite set-password + forgot-password) (Wave 3)

### Phase 11: Internationalization (NL/FR/EN)
**Goal**: The UI supports NL, FR, and EN through react-i18next with all hardcoded Dutch strings externalized and a working language switcher with a sensible default locale.
**Depends on**: Phase 6
**Requirements**: I18N-01, I18N-02
**Success Criteria** (what must be TRUE):
  1. The UI renders fully in NL, FR, and EN — all labels, banners, toasts, error messages, and date locale are externalized to i18n keys (no hardcoded Dutch strings remain)
  2. A user can switch language and a default locale applies per user/space
**Plans**: 9 plans (4 waves)
  - [x] 11-01-PLAN.md — Frontend i18n foundation: i18next init + provider + LanguageSwitcher + detect/date-locale/error-codes helpers + /me seam + catalog skeleton + CI guard (Wave 1)
  - [x] 11-02-PLAN.md — Backend foundation: 0010 locale columns + /me GET/PATCH resolution chain + CodedError contract (Wave 1)
  - [x] 11-03-PLAN.md — Intake schema multi-locale + localizeSchema + form chrome externalize + client switcher mount (Wave 2)
  - [x] 11-04-PLAN.md — Admin detail (56 strings) + ProductShell switcher + space default_locale field + admin date-locale (Wave 2)
  - [x] 11-05-PLAN.md — Intake results/AI/artifact components + PDF pre-resolved labels + date-locale sites (Wave 3)
  - [x] 11-06-PLAN.md — Auth pages externalize + pre-login switcher + SSR-safe boot-locale reconciliation (Wave 2)
  - [x] 11-07-PLAN.md — Remaining admin dialogs + pulse routes externalize (Wave 3)
  - [x] 11-08-PLAN.md — Mail locale variants (nl/fr/en) + recipient-locale resolution in send path (Wave 3)
  - [x] 11-09-PLAN.md — Long-tail common sweep + FULL CI Dutch-string guard gate (Wave 4)
**UI hint**: yes

### Phase 12: Frontend Deploy, Cutover & Supabase Retirement
**Goal**: The TanStack Start SSR frontend is deployed on Cloud Run against the new backend, the full flow is validated end-to-end for both superadmin and user roles, and the GCP stack is completely independent of Supabase (no env vars/calls/keys in the deployed system).
**Depends on**: Phase 7, Phase 8, Phase 9, Phase 10, Phase 11
**Requirements**: INFRA-05, QA-05
**Success Criteria** (what must be TRUE):
  1. The TanStack Start SSR frontend is deployed as a Cloud Run container pointed at the new backend, with no Supabase anon key remaining in the bundle
  2. A parity checklist is green: a full `draft → … → decomposed` run completes on GCP for both a superadmin and a user, exercising auth, isolation, AI ports, SSE, storage, and i18n
  3. AMENDED (D-08): The legacy Supabase project is NOT touched (no pause, delete, or dashboard action). "Retirement" = independence: zero Supabase env vars, calls, or keys in the deployed system, proven by the D-11 bundle guard.
**Plans**: 5 plans (3 waves)
  - [ ] 12-01-PLAN.md -- Bundle guard (D-11) + consolidated 12-UAT parity checklist (Wave 1)
  - [ ] 12-02-PLAN.md -- Frontend containerization: node-server preset + Dockerfile + cloudbuild + hide sales nav (Wave 2)
  - [ ] 12-03-PLAN.md -- D-12 residual closure: sources-read endpoint + transcribe CTA wiring (Wave 1)
  - [ ] 12-04-PLAN.md -- IaC frontend service by construction + Phase-12 DEPLOY-RUNBOOK (Wave 1)
  - [ ] 12-05-PLAN.md -- Live deploy + two-role parity gate execution (checkpoint) (Wave 3)
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Schema & Migrations | 0/4 | Not started | - |
| 2. Backend Skeleton & Cloud SQL Wiring | 0/3 | Not started | - |
| 3. Identity Platform Auth | 0/TBD | Not started | - |
| 4. Tenant Isolation (Proven by Tests) | 0/4 | Not started | - |
| 5. User & Space Management | 5/5 | Complete (live UAT) | 2026-06-29 |
| 6. Intake CRUD Parity & Frontend API Seam | 11/13 | Gaps found (2 blockers) — gap plans 06-12/06-13 | 2026-06-29 |
| 7. AI Function Ports | 11/11 | Complete   | 2026-07-13 |
| 8. SSE Skill-Run Progress | 0/3 | Planned (3 plans, 1 wave) | - |
| 9. GCS Storage | 4/4 | Complete   | 2026-07-13 |
| 10. Notifications | 5/5 | Complete    | 2026-07-13 |
| 11. Internationalization (NL/FR/EN) | 9/9 | Complete    | 2026-07-14 |
| 12. Frontend Deploy, Cutover & Supabase Retirement | 0/TBD | Not started | - |
