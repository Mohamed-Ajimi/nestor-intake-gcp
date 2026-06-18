# Provenance & known issues

## Where this came from
- **Frontend** (`frontend/`): copied from a third-party Lovable build, original repo
  `github.com/agenic-nestor/Nestor` (Dutch commits). Copied WITHOUT their git history,
  node_modules, or build output. It is the re-platform starting point — we keep the UI, swap the
  backend it talks to.
- **Backend reference** (`docs/`): the original backend lives only in a hosted **Supabase** project
  ("Sweep Database Project", ref `inmsssedwdmgtnhaydmg`, eu-west-1). There were NO migrations or
  function sources in the frontend repo, so the schema + RPCs + edge-function sources were pulled
  **read-only** via the Supabase Management API (2026-06-18) for reference. Nothing was modified.

## Known issues to FIX during the migration (verified against the live project)
1. **No real tenant isolation.** The Supabase `nestor` RLS policies on intakes/intake_answers/
   research_artifacts/findings are `USING (true) WITH CHECK (true)` for `authenticated` — any
   logged-in user can read/write every client's data. The new GCP build MUST enforce org-scoped
   RLS (the "spaces" boundary). This is the #1 reason for the migration.
2. **anon (public browser key) has INSERT/UPDATE/DELETE/TRUNCATE grants on 11 tables.** Don't carry
   that over; the new API mediates all access.
3. **Client access = never-expiring bearer links by email** (client_intake/validation/results
   tokens, 32-char, no expiry, no revocation). Replace with authenticated spaces + notification-only
   email. (A narrow tokenized path MAY be kept only for bulk/anonymous respondent intake.)
4. **findings & deliverables tables are unused (0 rows).** Final report today = a research_artifact
   referenced by intakes.final_report_artifact_id. Decide the target model deliberately.
5. **Dutch-only** prompts/UI/comments. Plan language handling.

## Reuse from the existing GCP stack (MOELD/Nestor, nestor_pulse_sdk)
The auth + tenancy + deploy patterns are already built and hardened there: Identity Platform login
+ first-login org provisioning, Cloud SQL with per-tenant RLS (worker_user/tenant_id model),
FastAPI on Cloud Run, GCS, alembic migrations, deploy scripts. Reuse these as reference patterns
(this project stays its own repo per the isolation decision).
