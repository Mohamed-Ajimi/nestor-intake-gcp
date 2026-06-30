---
phase: 07-ai-function-ports
plan: 02
subsystem: backend-db-schema
tags: [alembic, rls, orm, tenant-isolation, ai-ports]
requires:
  - "0008 migration head (prefill AFTER INSERT)"
  - "TenantRepository base + _scope wall (Phase 4)"
  - "0002 RLS + 0003 superadmin bypass idioms"
provides:
  - "intake_sources / transcripts / extracted_insights tables (space-scoped, RLS, bypass, grants)"
  - "skill_runs cost/parity columns + intake_answers AI-provenance columns"
  - "IntakeSource/Transcript/ExtractedInsight ORM models in Base.metadata"
  - "IntakeSourceRepository, TranscriptRepository, ExtractedInsightRepository, ArtifactEmbeddingRepository"
  - "IntakeAnswerRepository.upsert_extracted (LLM-answer write path, extracted_by='llm')"
affects:
  - "07-07 structure-answers handler (reuses upsert_extracted)"
  - "07-xx transcribe/extract/embed/search handlers (read/write these tables)"
tech-stack:
  added: []
  patterns: ["space-leading composite index", "NULLIF empty-string-safe RLS predicate", "env-guarded runtime-SA GRANT DO-block"]
key-files:
  created:
    - backend/app/db/models/sources.py
    - backend/app/db/models/transcripts.py
    - backend/app/db/models/insights.py
    - backend/app/db/alembic/versions/0009_ai_ports.py
  modified:
    - backend/app/db/models/__init__.py
    - backend/app/db/models/skill_run.py
    - backend/app/db/models/intake.py
    - backend/app/db/repository.py
decisions:
  - "ORM id columns carry BOTH default=uuid4 (client) AND server_default=gen_random_uuid() so ORM and 0009 agree exactly (compare_server_default is off, but the must_have demands exact agreement)"
  - "intake_id is NOT NULL on all three new tables (clones SkillRun); transcripts.source_id NOT NULL FK->intake_sources"
  - "RLS emitted via a 3-table loop helper (matches 0003's superadmin_all loop idiom) — still QA-02-clean (NULLIF + current_user predicates, never constant-true)"
  - "No intake_status enum widening — audio path records on intake_sources/transcripts, flow ceiling stays at decomposed"
metrics:
  duration: ~25 min
  completed: 2026-06-30
  tasks: 3
  files: 8
---

# Phase 7 Plan 02: AI-Port Schema Foundation Summary

Migration 0009 plus three new ORM models and four repository subclasses lay the complete Phase 7 schema substrate: three space-scoped tenant tables (`intake_sources`, `transcripts`, `extracted_insights`) with full RLS + superadmin bypass + grants, eleven nullable legacy-parity columns on `skill_runs` and `intake_answers`, and an LLM-answer upsert path that respects the existing unique constraint — all authored by construction with the ORM metadata and the migration in exact agreement.

## What Was Built

**Task 1 — three tenant-owned ORM models (commit bcf2882):** `IntakeSource`, `Transcript`, `ExtractedInsight` each clone the `skill_runs` shape — UUID PK, `space_id NOT NULL` FK→`organizations` ON DELETE CASCADE, `intake_id` FK, `created_at`, and `Index("ix_<t>_space_id")` + `Index("idx_<t>_space_intake")`. `Transcript.source_id` FKs `intake_sources` ON DELETE CASCADE. All three are registered in `models/__init__.py` (import + `__all__`) so `Base.metadata` carries them for autogenerate and the schema-shape tests; the registry docstring is updated to 18 tables.

**Task 2 — parity columns + four repositories (commit 2aab58b):**
- `SkillRun` gains 7 nullable columns: `input_tokens`, `output_tokens`, `cost_estimate_usd` (Numeric), `output`, `prompt_system`, `prompt_user`, `skill_version`.
- `IntakeAnswer` gains 4 nullable columns: `respondent_id`, `confidence` (Float), `source_chunk_id`, `extracted_by` — chosen nullable so the save-as-you-go `upsert_batch` is byte-for-byte unaffected.
- Four thin `TenantRepository` subclasses (`IntakeSourceRepository`, `TranscriptRepository`, `ExtractedInsightRepository`, `ArtifactEmbeddingRepository`) inherit the `_scope` wall; `space_id` is never a method parameter.
- `IntakeAnswerRepository.upsert_extracted` mirrors `upsert_batch` but stamps `extracted_by='llm'`, carries `confidence`/`source_chunk_id`, and keeps the conflict target on `uq_intake_answers_intake_field` with the D-01 `WHERE space_id = self._space_id` wall — the constraint is NOT relaxed.

**Task 3 — migration 0009 (commit d89469a):** `revision="0009"`, `down_revision="0008"`. Creates the three tables (FK-ordered: sources → transcripts → insights), adds the 11 parity columns via `op.add_column(..., schema="nestor")`, and for each new table emits `ENABLE`+`FORCE` RLS, `<t>_space_isolation` (mandatory `NULLIF(current_setting('app.current_space_id', true), '')::uuid` form), and `<t>_superadmin_all` bypass (`current_user = 'app_superadmin'`). Grants: explicit per-table to `app_superadmin` plus the env-guarded runtime-SA DO-block. Symmetric `downgrade()` reverses everything. No `intake_status` enum widening.

## Verification

All grep-based acceptance gates pass (per-task, captured below). Live `alembic check` / `alembic upgrade` are DEFERRED (D-10 author-by-construction; no Python/Docker on the dev machine) — the standing bar is index-name parity between the ORM models and the migration, which holds 1:1, plus column-type agreement under `compare_type=True`.

- Task 1: 3 model classes present, `__init__` registration count = 6 (≥6).
- Task 2: skill_runs parity ≥4 (5), intake_answers parity ≥4 (6), repo subclasses = 4, unique constraint preserved = 1, no `nullable=False` on the new answer columns.
- Task 3: `down_revision "0008"` = 1, `_space_isolation` = 3, `_superadmin_all` = 3, `NULLIF(current_setting` = 3, `op.add_column` = 11, `ALTER TYPE ... intake_status` = 0.

## Deviations from Plan

**1. [Rule 3 — reconciliation] ORM `id` columns carry `server_default=gen_random_uuid()`**
- Plan Task 1 said "clone `SkillRun`'s shape" (which has no `server_default`), while Task 3 said the migration `id` must have `server_default gen_random_uuid()`. To honor the must_have "ORM metadata and the 0009 migration agree exactly," the new models declare BOTH `default=uuid.uuid4` (client) and `server_default=text("gen_random_uuid()")` — the established `IntakeAnswer` (post-0007) pattern. `compare_server_default` is off in `env.py`, so this is not strictly required for `alembic check`, but it makes ORM/migration agreement unconditional.
- Files: `sources.py`, `transcripts.py`, `insights.py`, `0009_ai_ports.py`. Commits: bcf2882, d89469a.

**2. [style] RLS emitted via a 3-table loop helper rather than fully inline**
- 0002 wrote space-isolation policies inline per table; 0009 factors `ENABLE/FORCE/space_isolation/superadmin_all` into `_enable_rls(table)` called over `_NEW_TABLES`. This matches 0003's `superadmin_all` loop idiom and stays QA-02-clean (predicates are NULLIF/`current_user`, never the banned constant-true). Functionally identical; the grep gates still pass.

No bugs found; no architectural decisions required; no authentication gates.

## Threat Surface

All three STRIDE register mitigations (T-7-08 missing-RLS, T-7-09 superadmin lockout/overreach, T-7-10 caller-supplied space_id) are implemented: ENABLE+FORCE+space_isolation on every new table, `<t>_superadmin_all` bypass + grants to `app_superadmin`/runtime-SA only, and `space_id NOT NULL` FK with repository `create()` injecting `space_id` from Identity (never a method param). The cross-tenant denial proof itself lands in 07-01's `test_ai_cross_tenant.py` (separate plan). No new trust-boundary surface beyond the plan's threat model.

## Known Stubs

None. All schema objects are concrete; the per-handler logic that writes them is intentionally scoped to later Phase 7 plans (07-xx), which this plan exists to unblock.

## Self-Check: PASSED

- Files: all 8 created/modified files present on disk (verified).
- Commits: bcf2882, 2aab58b, d89469a all present in `git log`.
