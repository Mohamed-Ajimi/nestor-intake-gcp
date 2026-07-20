# Milestones

## v1.0 GCP Re-platform (Shipped: 2026-07-20)

**Delivered:** The entire Nestor Pulse pre-research intake flow re-platformed off Supabase onto
GCP — a logged-in superadmin or client user runs an intake end-to-end (form → AI skills → review →
client validation → context pack → `decomposed`) with real per-tenant isolation, on a stack with
zero Supabase dependencies.

**Phases completed:** 12 phases, 70 plans, 134 tasks
**Timeline:** 2026-06-18 → 2026-07-20 (33 days, 485 commits)
**Live stack at close:** frontend `nestor-frontend` rev 00010-ndr + backend `nestor-api` rev
00024-67b on Cloud Run, Cloud SQL Postgres 16 + pgvector at alembic 0010, Identity Platform auth,
GCS signed-URL storage, Resend mail.

**Key accomplishments:**

- Full `nestor` schema (14 tables, `space_id NOT NULL` FKs) as Alembic migrations with real RLS
  policies, a CI guard banning `USING(true)`, and a testcontainers suite (150+ tests) proving
  cross-tenant denial before any feature shipped.
- FastAPI backend on Cloud Run as the sole path to the database — IAM-auth Cloud SQL connector,
  bounded pools, least-privilege runtime SA, Terraform IaC + one-image service/migration-Job.
- Identity Platform auth everywhere: server-side token verification, server-set role/space custom
  claims, real invite flow, legacy never-expiring bearer links removed.
- All seven pre-research AI functions ported (apply-intake-skill, generate-context-pack,
  structure-answers, extract-insights, embeddings + semantic search, transcribe-audio) —
  space-scoped, DB connections released across LLM calls, SSE skill-run progress.
- Frontend re-pointed to a single `lib/api/*` seam, deployed as a Cloud Run SSR container with a
  build-time guard proving no Supabase signature ships; NL/FR/EN i18n; notification-only mail.
- Live cutover executed and hardened through 4 operator UAT rounds (8 defects found and fixed
  same-day); Supabase independence proven code-side (D-08 — legacy project untouched by design).

**Known deferred items at close:** 29 (see STATE.md Deferred Items) — headline: parity gate closed
as **PARITY ACCEPTED WITH DEFERRALS** (operator decision 2026-07-20); 21 UAT items + 9 human_needed
verifications deferred to post-Tribunal; chores: Resend key rotation, Cloud Build suite rerun, NDA
PDF drop, legacy env cleanup.

---
