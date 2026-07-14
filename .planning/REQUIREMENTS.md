# Requirements: Nestor Intake (GCP Re-platform)

**Defined:** 2026-06-18
**Core Value:** A logged-in superadmin or client user can run an intake end-to-end on GCP — from form submission through AI skill application to a validated, decomposed context pack — with each client's data fully isolated to its own space, and the legacy Supabase system retired.

## v1 Requirements

Requirements for the cutover milestone. Each maps to roadmap phases. "Done" bar = secure, tenant-isolated, full parity to `decomposed`, validated for superadmin + user, Supabase retired.

### Infrastructure & Platform

- [x] **INFRA-01**: Cloud SQL (PostgreSQL 16 + pgvector) instance is provisioned and reachable from Cloud Run via the Cloud SQL connector (IAM DB auth, no proxy sidecar)
- [x] **INFRA-02**: The full `nestor` schema is created via Alembic migrations on an empty database, including `findings`/`deliverables` tables (left empty as Tribunal handoff contract)
- [ ] **INFRA-03**: A GCS bucket replaces `nestor-uploads`; backend has IAM permission to mint signed URLs via `signBlob`
- [x] **INFRA-04**: The FastAPI backend is deployed and serving on Cloud Run gen2
- [ ] **INFRA-05**: The TanStack Start SSR frontend is deployed on Cloud Run (container), pointed at the new backend

### Backend & API Layer

- [x] **API-01**: A FastAPI backend mediates ALL data access — the browser never talks directly to the database
- [ ] **API-02**: All data access flows through a single repository layer where tenant filtering cannot be omitted per-endpoint
- [ ] **API-03**: The frontend's data access is centralized in a `frontend/src/lib/api/*` client module, replacing all inline Supabase calls
- [ ] **API-04**: Skill-run progress is delivered to the frontend via a Server-Sent Events endpoint that reads `skill_runs` state from the database (no in-memory state)

### Authentication & Identity

- [ ] **AUTH-01**: Every route and API endpoint requires a valid Identity Platform login; there are no anonymous routes (the disabled admin guard is restored as a real guard)
- [ ] **AUTH-02**: The backend verifies the Identity Platform ID token server-side (`verify_id_token`) on every request
- [ ] **AUTH-03**: A user's `role` (superadmin | user) and `space_id` are stored as Identity Platform custom claims, set only server-side via the Admin SDK
- [ ] **AUTH-04**: Admin can deactivate a user, revoking their access (Identity Platform user disabled + refresh tokens revoked); the backend re-checks disabled state
- [ ] **AUTH-05**: All client access via never-expiring bearer links (`client_intake_token`, `client_validation_token`, `client_results_token`) is removed

### Tenancy & Access Control

- [x] **TENANT-01**: Every tenant-owned table has a `space_id NOT NULL` foreign key
- [ ] **TENANT-02**: Every read and write is scoped to the caller's `space_id` derived from the verified token — never from a client-supplied parameter
- [ ] **TENANT-03**: A superadmin can access data across all spaces; a user is hard-pinned to exactly one space (default-deny enforced at the API layer)
- [ ] **TENANT-04**: A user sees only their own space's intakes; a superadmin has a space selector/switcher
- [x] **TENANT-05**: Postgres RLS policies exist as defense-in-depth; no policy uses `USING (true)` / `WITH CHECK (true)`

### User Management

- [ ] **USER-01**: A superadmin can invite a user, assigning them to exactly one space with the `user` role
- [ ] **USER-02**: An invited user provisions their account on first login (JIT), with `role`/`space_id` claims attached server-side
- [ ] **USER-03**: A superadmin can create and manage client spaces (organizations) and their intake templates

### Documents & Storage

- [ ] **DOC-01**: A user can download an artifact only after the backend verifies they own the artifact's space, via a short-TTL (≤15 min) GCS V4 signed URL
- [ ] **DOC-02**: File uploads (intake attachments, audio) are stored in GCS through the backend, never direct browser→storage

### Intake Flow (Authenticated Parity)

- [ ] **INTAKE-01**: A logged-in user can open, fill (save-as-you-go), and submit a multi-section intake form
- [ ] **INTAKE-02**: A logged-in user can view their intake results
- [ ] **INTAKE-03**: The admin intake lifecycle works through the phase machine up to `decomposed` (submitted → reviewed → validated_by_client → decomposed)
- [ ] **INTAKE-04**: Status transitions are driven by the backend (RPC-equivalent endpoints + DB triggers), preserving the documented state machine
- [ ] **INTAKE-05**: A scope guard ensures `run-research` is never invoked from the new frontend/backend; the flow stops at `decomposed`

### AI Flow Parity (Space-Scoped)

- [ ] **AI-01**: `apply-intake-skill` runs on Cloud Run, producing per-field reviewable output, with admin accept/edit/reject UX preserved
- [ ] **AI-02**: `generate-context-pack` runs on Cloud Run and produces the context pack artifact
- [ ] **AI-03**: `structure-answers` and `extract-insights` run on Cloud Run with parity behavior
- [ ] **AI-04**: Embeddings generation runs on Cloud Run; semantic search results are filtered by `space_id` (no cross-tenant embedding leakage)
- [ ] **AI-05**: Audio transcription (Whisper) runs on Cloud Run
- [ ] **AI-06**: AI/LLM calls release the DB connection before the call and reopen to persist (no connection held across a 90–120s call)

### Notifications

- [x] **NOTIF-01**: Transactional email is notification-only — it carries no access token; links point to authenticated routes
- [x] **NOTIF-02**: Email is sent for invitation, validation-ready, results-ready, and reminders

### Internationalization

- [x] **I18N-01**: The UI supports NL, FR, and EN via an i18n framework; all hardcoded Dutch strings (labels, banners, toasts, date locale) are externalized
- [x] **I18N-02**: A user can switch language; a default locale applies per user/space

### Quality, Security & Cutover

- [ ] **QA-01**: A CI-gated cross-tenant denial test suite proves a user cannot read or write another space's data
- [x] **QA-02**: A CI check fails the build on any `USING (true)` / `WITH CHECK (true)` in a migration
- [ ] **QA-03**: Characterization tests cover the phase machine; contract tests cover the ported AI endpoints
- [ ] **QA-04**: A basic audit trail logs security-relevant events (auth, invitations, role/space assignment, downloads, status transitions) with actor + space
- [ ] **QA-05**: The end-to-end flow is validated on GCP for both superadmin and user roles, and the legacy Supabase project is retired (paused/recoverable until parity is green, then decommissioned)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhancements

- **I18N-03**: Content/email i18n beyond UI chrome (per-locale email templates, CTA copy)
- **QA-06**: Richer audit-log UI / export
- **I18N-04**: Persisted per-user locale preference

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| `client-admin` role / delegated tenant admin | Deferred; v1 is superadmin + user only (claim designed to extend later) |
| Bearer / never-expiring share links | The #1 security flaw being eliminated |
| Tally / external anonymous form ingestion | Incompatible with login-only model |
| Jotform webhook | Already deprecated (returns 410) |
| `run-research` / Tribunal deep-research engine | Separate track; flow stops at `decomposed` |
| Migrating legacy Supabase production data | Starting fresh on an empty Cloud SQL DB |
| DB RLS as the sole isolation mechanism | The original `USING (true)` RLS was the failure; API layer is primary guard |
| Native Identity Platform per-tenant user pools | Over-engineered for a 2-role model; using `space_id` custom claims |
| Heavy realtime / websocket layer | Only skill-run progress needs push (SSE) |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 2 | Complete |
| INFRA-02 | Phase 1 | Complete |
| INFRA-03 | Phase 9 | Pending |
| INFRA-04 | Phase 2 | Complete |
| INFRA-05 | Phase 12 | Pending |
| API-01 | Phase 2 | Complete |
| API-02 | Phase 4 | Pending |
| API-03 | Phase 6 | Pending |
| API-04 | Phase 8 | Pending |
| AUTH-01 | Phase 3 | Pending |
| AUTH-02 | Phase 3 | Pending |
| AUTH-03 | Phase 3 | Pending |
| AUTH-04 | Phase 5 | Pending |
| AUTH-05 | Phase 3 | Pending |
| TENANT-01 | Phase 1 | Complete |
| TENANT-02 | Phase 4 | Pending |
| TENANT-03 | Phase 4 | Pending |
| TENANT-04 | Phase 6 | Pending |
| TENANT-05 | Phase 1 | Complete |
| USER-01 | Phase 5 | Pending |
| USER-02 | Phase 5 | Pending |
| USER-03 | Phase 5 | Pending |
| DOC-01 | Phase 9 | Pending |
| DOC-02 | Phase 9 | Pending |
| INTAKE-01 | Phase 6 | Pending |
| INTAKE-02 | Phase 6 | Pending |
| INTAKE-03 | Phase 6 | Pending |
| INTAKE-04 | Phase 6 | Pending |
| INTAKE-05 | Phase 6 | Pending |
| AI-01 | Phase 7 | Pending |
| AI-02 | Phase 7 | Pending |
| AI-03 | Phase 7 | Pending |
| AI-04 | Phase 7 | Pending |
| AI-05 | Phase 7 | Pending |
| AI-06 | Phase 7 | Pending |
| NOTIF-01 | Phase 10 | Complete |
| NOTIF-02 | Phase 10 | Complete |
| I18N-01 | Phase 11 | Complete |
| I18N-02 | Phase 11 | Complete |
| QA-01 | Phase 4 | Pending |
| QA-02 | Phase 1 | Complete |
| QA-03 | Phase 6 | Pending |
| QA-04 | Phase 5 | Pending |
| QA-05 | Phase 12 | Pending |

**Coverage:**
- v1 requirements: 44 total
- Mapped to phases: 44 ✓
- Unmapped: 0 ✓

*Note: an earlier metadata line stated 38 v1 requirements; the actual count of defined v1 requirement IDs is 44. Corrected here during roadmap creation.*

---
*Requirements defined: 2026-06-18*
*Last updated: 2026-06-18 after roadmap creation (traceability populated)*
