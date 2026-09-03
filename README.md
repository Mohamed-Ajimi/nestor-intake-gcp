# nestor-intake-gcp

Re-platform of the **Nestor intake flow** (the agenic "Pulse" intake app, originally built on
Supabase by a third party) onto **Google Cloud Platform**, with a proper **user / client-admin /
superadmin** model and **per-tenant ("spaces") isolation**.

This project is deliberately **isolated** from the Tribunal/ADK research-engine work
(`MOELD/Nestor`). It covers **everything BEFORE the research stage** — Tribunal is explicitly
out of scope here (the flow stops at status `decomposed`: validated questions + context pack ready).

## Documentation

**[The Nestor Pulse Handbook](docs/handbook/00-README.md)** is the complete, verified account of the
system: architecture, every module, both data models, the decision log, the models used and why,
operations, and the known gaps. Start there. Twenty-one chapters, verified against commit `c8b8583`.

## Scope

**In:**
- Intake frontend (the Lovable React/TanStack app) — kept, but its data layer re-pointed off Supabase.
- DB → **Cloud SQL** (Postgres): intakes, intake_answers, research_questions, skill_runs,
  decompositions, intake_templates, clients/orgs.
- Auth: Supabase GoTrue → **Identity Platform** (already enabled on the GCP project).
- Upstream edge functions → **Cloud Run / FastAPI**: apply-intake-skill, generate-context-pack,
  structure-answers, extract-insights, tally/jotform webhooks.
- Storage → **GCS**.
- **NEW:** user / client-admin / superadmin roles + tenant "spaces" with real org-scoped RLS.
  Email becomes notification-only ("something is ready, check the app"), replacing bearer links.

**Out (later, separate track):**
- run-research, Tribunal, findings, the deep-research / verification engine.

## Layout

```
frontend/              the Lovable intake app (React 19 + TanStack + shadcn). Re-platform target.
docs/
  BACKEND-MAP.md       full map of the original Supabase backend (schema, 21 edge fns, 27 RPCs,
                       status state machine, the run-research seam).
  db_functions.sql     key Postgres RPC/trigger definitions (pulled from the live project).
  supabase-functions/  clean TypeScript source of all 21 edge functions (reference for porting).
backend/               (to be built) FastAPI on Cloud Run — the new data/API layer.
infra/                 (to be built) Cloud SQL, Identity Platform, GCS, Cloud Run config.
```

See `docs/PROVENANCE.md` for where the original code came from and the known security issues to fix.
