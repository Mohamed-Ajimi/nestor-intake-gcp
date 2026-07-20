---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 12 context gathered
last_updated: "2026-07-14T15:00:31.128Z"
last_activity: 2026-07-14 -- Phase 12 execution started
progress:
  total_phases: 12
  completed_phases: 11
  total_plans: 70
  completed_plans: 65
  percent: 92
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-18)

**Core value:** A logged-in superadmin or client user can run an intake end-to-end on GCP — from form submission through AI skill application to a validated, decomposed context pack — with each client's data fully isolated to its own space, and the legacy Supabase system retired.
**Current focus:** Phase 12 — frontend-deploy-cutover-supabase-retirement

## Current Position

Phase: 12 (frontend-deploy-cutover-supabase-retirement) — EXECUTING
Plan: 1 of 5
Next: Phase 06 (intake-crud-parity-and-frontend-api-seam)
Status: Executing Phase 12
Last activity: 2026-07-20 -- Deployed frontend rev 00010-ndr (a710e8e validation-diff fix live); operator deferred remaining 12-UAT items to post-Tribunal (quick task 260720-eh4)

Progress: 5 / 12 phases complete

## Performance Metrics

**Velocity:**

- Total plans completed: 63
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 4 | - | - |
| 02 | 3 | - | - |
| 03 | 4 | - | - |
| 04 | 4 | - | - |
| 06 | 13 | - | - |
| 08 | 3 | - | - |
| 09 | 4 | - | - |
| 07 | 11 | - | - |
| 10 | 5 | - | - |
| 11 | 9 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 18 | 3 tasks | 5 files |
| Phase 01 P02 | 22 | 2 tasks | 16 files |
| Phase 01 P03 | 15 | 3 tasks | 6 files |
| Phase 01 P04 | 12 | 2 tasks | 3 files |
| Phase 02 P01 | 18 | 3 tasks | 7 files |
| Phase 02 P02 | 5 | 2 tasks | 3 files |
| Phase 02 P03 | 22min | 3 tasks | 7 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Build order is schema → backend/Cloud SQL → auth → isolation-proven-by-tests → CRUD+frontend seam → AI ports → SSE → storage → i18n → cutover (research-recommended).
- Roadmap: Phase 4 (tenant isolation + CI-gated cross-tenant denial suite) gates all downstream feature endpoints — isolation must be proven before features ship.
- Roadmap: Tests are phase-zero work, not cleanup (QA-01 denial suite, QA-02 `USING(true)` CI guard, QA-03 phase-machine/AI contract tests).
- Project: Big-bang cutover — Supabase paused (recoverable), retired only after parity is green for both roles.
- [Phase ?]: Plan 01-01: RLS test harness uses sync pg8000 (Q1 RESOLVED) so the test engine and Alembic env.py share one driver.
- [Phase ?]: Plan 01-01: Wave 0 RED scaffold — schema-shape + RLS-isolation suites authored against the final contract, RED until plans 01-02/01-03 land.
- [Phase ?]: Plan 01-02: all nestor tables live in the Postgres 'nestor' schema (Base.metadata schema='nestor'); shape tests query table_schema='nestor'.
- [Phase ?]: Plan 01-02: no public.clients (Q2 RESOLVED) — org = space; space_id (= org id) is the sole isolation key; client identity is organizations.name.
- [Phase ?]: Plan 01-02: explicit Index() names (no index=True) so ORM and 0001 migration index names match 1:1 and alembic check stays clean.
- [Phase ?]: Plan 01-03: adopt NULLIF(current_setting('app.current_space_id', true),'')::uuid in the FIRST RLS migration (0002) so unset AND empty-string GUC reversion fail safe — no 0009->0010 replay.
- [Phase ?]: Plan 01-03: superadmin bypass via app_superadmin login role + current_user='app_superadmin' policy (Cloud SQL has no BYPASSRLS); OR'd with isolation so the app role stays space-scoped.
- [Phase ?]: Plan 01-03: QA-02 CI guard (scripts/ci_no_permissive_rls.sh) bans USING(true)/WITH CHECK(true) via grep exit code; negative test plants an offender and asserts non-zero exit.
- [Phase ?]: Plan 01-04: updated_at handled by ORM onupdate (not a DB trigger); choice pinned as UPDATED_AT_MECHANISM: orm-onupdate marker in 0004 and asserted by the test.
- [Phase ?]: Plan 01-04: 0004 ports ONLY in-scope (<= decomposed) triggers (prefill_intake_answers retargeted to organizations.name + submit_intake transition logic); the 3 post-decomposed Tribunal triggers are absent as objects AND as literal names (INTAKE-05).
- [Phase ?]: Plan 01-04: dev seed (scripts/seed_dev.py) is standalone + idempotent; test asserts no migration references it so production comes up empty (INFRA-02 / D-09).
- [Phase ?]: [Phase 02]: Plan 02-01: base.py keeps reading os.environ directly (no import cycle with app.core); config.py is for main.py/typed validation only (D-06).
- [Phase ?]: [Phase 02]: Plan 02-01: get_engine() mode-switch gated on (database_url is None and INSTANCE_CONNECTION_NAME) so explicit DSN always wins (Phase-1 regression safe, Pitfall 6); Connector imported lazily inside _get_connector.
- [Phase ?]: [Phase 02]: Plan 02-01: shared _POOL_KW (size=2, overflow=3, pre_ping, recycle=1800) on both engine modes (D-04); split /healthz (no DB) + /readyz (SELECT 1, generic 503 no leak), sync handlers (pg8000 blocking).
- [Phase ?]: [Phase 02]: Plan 02-02: alembic env.py gets an additive IAM-connector branch via importable _use_connector(cfg) + _build_connectable(); fires only when INSTANCE_CONNECTION_NAME set AND no pre-set sqlalchemy.url, reusing base.py._connector_creator (enable_iam_auth stays in base.py, no duplication).
- [Phase ?]: [Phase 02]: Plan 02-02: one multi-stage uv Dockerfile serves both the Cloud Run service (single Uvicorn CMD on PORT) and the migration Job (CMD overridden with args=[alembic,upgrade,head]); alembic.ini + app/db/alembic bundled; no Gunicorn/workers, no baked secrets (D-02/D-05/D-09).
- [Phase ?]: Runtime SA IAM DB user GRANTed DIRECT space-scoped privileges (no named app role in Phase 1); RLS still applies (OQ1/A5, migration 0005)
- [Phase ?]: Cloud Run invoker authenticated-only by default (allow_unauthenticated=false); /readyz verified via gcloud run services proxy (OQ2)
- [Phase ?]: GCP live execution deferred to user per D-10; all artifacts authored by construction

### Pending Todos

- [2026-07-13] COMBINED 7+8+9 LIVE UAT RUN — core flow PROVEN live (upload → apply-intake-skill (first real Claude call, €0.04) → review → client validation → context pack → decomposed → signed-URL download). Scores: 07-UAT 3 pass/4 blocked; 08-HUMAN-UAT 2 pass/1 blocked; 09-HUMAN-UAT 5 pass/4 blocked. Deployed rev nestor-api-00017-zbt (bucket+IAM+CORS applied; 900s timeout; STORAGE_BUCKET set). 12+ inline fixes committed during the session (superadmin answers upsert, value_json Any, AI trigger wiring, client validation phase, FieldControl crash, submit gating). REMAINING: (a) audio follow-up session — transcribe E2E, superadmin audio upload, delete + WR-04 click-through, cross-space browser denial; (b) gap-closure plans from 07-UAT Gaps (missing UI triggers for structure/extract/transcribe/embeddings, artifacts-read endpoint + ContextPackBlock display, context-pack progress UX, Kopieer-intake-link, NDA template-asset serving). Resume audio: /gsd-verify-work 9.

### Blockers/Concerns

- Scope guard (INTAKE-05): `run-research`/Tribunal must never be reachable from the new frontend/backend credentials; flow stops at `decomposed`. Enforced in Phase 6.
- Connection management (AI-06): never hold a DB connection across a 90–120s LLM/Whisper call; bounded pools vs Cloud SQL tier limit. Addressed in Phase 2 and enforced in Phase 7.
- Requirements metadata previously stated 38 v1 requirements; actual count is 44 (corrected in REQUIREMENTS.md traceability).
- [Phase 5 follow-up — IaC DRIFT, major]: the live deploy required manual steps the committed `infra/*.tf` doesn't apply (identitytoolkit.admin grant to nestor-run, allUsers invoker, SUPERADMIN_DB_PASSWORD_SECRET env + secretAccessor on nestor-app-superadmin-pw, CORS_ALLOWED_ORIGINS). Terraform state was never adopted (Phase 2 deployed gcloud-native). Reconcile (terraform import) or document a deploy runbook BEFORE Phase 12 cutover. See 05-UAT.md Gaps.
- [Phase 5 follow-up — minor]: `backend/app/api/admin_routes.py` space update/deactivate/reactivate `audit.log` calls omit `space_id` (only create_space passes it). Audit row still written; space_id null on those 3 events.
- [Phase 5 live-deploy state]: nestor-api is currently `allUsers`-invocable (public; app enforces Firebase auth). Lock back down (remove allUsers invoker) when local testing is done, OR keep if continuing into Phase 6 frontend work.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260629-ds9 | Add PATCH to backend CORS allow_methods | 2026-06-29 | db32754 | [260629-ds9-cors-patch-method](./quick/260629-ds9-cors-patch-method/) |
| 260629-li2 | Role-gate admin UI (claims guard + Beheer nav hide + 401-disabled redirect) | 2026-06-29 | b49bc8d | [260629-li2-role-gate-admin-ui-on-frontend-claims-ro](./quick/260629-li2-role-gate-admin-ui-on-frontend-claims-ro/) |
| 260715-fts | Apply Claude Design canvas UI consistency fixes to frontend (pre-UAT fuse) | 2026-07-15 | 8907172 | [260715-fts-apply-claude-design-canvas-ui-consistenc](./quick/260715-fts-apply-claude-design-canvas-ui-consistenc/) |
| 260715-j7f | Fuse round-2 canvas redesign of client intake form (stepper sidebar progress) | 2026-07-15 | 5b5259b | [260715-j7f-fuse-round-2-canvas-redesign-of-client-i](./quick/260715-j7f-fuse-round-2-canvas-redesign-of-client-i/) |
| 260716-e59 | Fix 4 UAT-found frontend defects (user lang switcher, nav i18n, decomposed filter, space-switch refetch) | 2026-07-16 | d358685 | [260716-e59-fix-4-uat-found-frontend-defects-user-la](./quick/260716-e59-fix-4-uat-found-frontend-defects-user-la/) |
| fast | Fix one-step-behind active-space filter (sync module accessor in setActiveSpace) | 2026-07-16 | 1d7732a | — |
| 260716-i0j | Fuse round-3 canvas redesign of admin intake detail (merged workflow panel, archive dialog, deferred-delete viz, pack preview, inline emails) | 2026-07-16 | f7297e6 | [260716-i0j-fuse-round-3-canvas-redesign-of-admin-in](./quick/260716-i0j-fuse-round-3-canvas-redesign-of-admin-in/) |
| 260716-ji9 | Intake-invite mail type (backend+frontend) + Intake-info header modal + section-heading casing | 2026-07-16 | 03603f2 | [260716-ji9-intake-mail-type-intake-info-modal-secti](./quick/260716-ji9-intake-mail-type-intake-info-modal-secti/) |
| fast | Fix phase machine consuming enrichment skill runs (fake "analysis ready" after structure-answers) | 2026-07-16 | d2f335b | — |
| fast | Restart skill-run safety poll on new dispatch (stuck 7-min timer) + toast on unusable review output | 2026-07-16 | 4eb1c6e | — |
| fast | Heranalyseer re-run button in awaiting_review banner | 2026-07-16 | acf1ba4 | — |
| fast | Client validation diff: patch applied refinements into research_questions + show applied text | 2026-07-16 | a710e8e | — |
| 260720-eh4 | Record rev 00010-ndr deploy (a710e8e live) + operator UAT-deferral decision in 12-UAT.md | 2026-07-20 | 7731421 | [260720-eh4-record-rev-00010-ndr-deploy-defer-remain](./quick/260720-eh4-record-rev-00010-ndr-deploy-defer-remain/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| *(none)* | | | |

## Session Continuity

Last session: 2026-07-14T13:35:29.239Z
Stopped at: Phase 12 context gathered
Resume file: .planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-CONTEXT.md
