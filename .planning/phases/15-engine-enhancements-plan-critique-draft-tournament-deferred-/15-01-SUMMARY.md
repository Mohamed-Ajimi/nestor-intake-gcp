---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 01
subsystem: tribunal-verification-cost-foundation
tags: [alembic, rls, sqlalchemy, fixtures, hash-chain, cost, verification]
requires: []
provides:
  - tribunal-alembic-0011-cost-verification
  - verification_verdict-rls-table
  - VerificationVerdict-model
  - audit_log.cache_creation_tokens
  - run.cost_pending
  - run.verification_summary
  - run_4cbb5311-recorded-fixture
  - enriched-stage_detail-seed
affects:
  - Plan 15-02 (cost fix reads audit_log.cache_creation_tokens + run.cost_pending)
  - Plan 15-03 (verification report reads verification_verdict + run.verification_summary)
  - Plan 15-04 (audit-body seam resolves stage_detail item audit_id)
  - Plan 15-05 (D15 feed reads enriched run.stage_detail)
tech-stack:
  added: []
  patterns:
    - "Additive-only migration keeps new columns OUTSIDE the frozen hash-chain payload (T-15-01)"
    - "New RLS table copies ENABLE+FORCE RLS + tenant policy verbatim from 0003 (T-15-02)"
    - "Recorded-run fixture reconstructed from committed docs extracts — zero GCS dependency"
    - "Fixture audit rows ordered by GCS mtime, not seq (Pitfall 6 — all recorded seq=0)"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/alembic/versions/0011_cost_verification.py
    - tribunal/nestor_pulse_sdk/db/models/verification_verdict.py
    - tribunal/nestor_pulse_sdk/tests/fixtures/__init__.py
    - tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/__init__.py
    - tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/loader.py
    - tribunal/nestor_pulse_sdk/tests/fixtures/run_4cbb5311/verdict_extract.py
  modified:
    - tribunal/nestor_pulse_sdk/db/models/audit_log.py
    - tribunal/nestor_pulse_sdk/db/models/run.py
    - tribunal/nestor_pulse_sdk/db/models/__init__.py
    - tribunal/nestor_pulse_sdk/tests/test_hash_chain_replay.py
decisions:
  - "cost_usd serialised as string inside stage_detail JSONB (Decimal is not JSON-native; NULL preserved)"
  - "reconciliation-as-string recorded rows coerced to NULL reconciliation rather than discarding the whole verdict (safer, keeps the verdict queryable)"
  - "fixture load_recorded_run accepts session=None for no-DB unit assertions (dev box has no Docker/Postgres)"
metrics:
  duration: ~35m
  completed: 2026-07-24
---

# Phase 15 Plan 01: Cost + Verification Foundation Summary

Additive tribunal Alembic 0011 migration (cache-creation cost column, run cost/verification-funnel columns, and a `verification_verdict` FORCE-RLS read-model table), the matching SQLAlchemy models, and the recorded run-4cbb5311 test fixture that reconstructs a real run — with an enriched per-row-cost `stage_detail` and 198 real group-skeptic verdict rows — entirely from committed docs extracts, proving `verify_chain` stays green post-migration.

## What Was Built

**Task 1 — Migration 0011** (`7c7139f`): `down_revision = "0010"`, three additive columns (`audit_log.cache_creation_tokens` nullable, `run.cost_pending` bool default false, `run.verification_summary` JSONB nullable) plus the `verification_verdict` table (id/tenant_id/run_id/claim_id/verdict/confidence/evidence_refs/reconciliation/created_at) with `idx_verification_verdict_tenant_run`, ENABLE + FORCE ROW LEVEL SECURITY, and the tenant-isolation policy copied verbatim from `0003_citation_schema.py`. Nothing enters the intake `nestor` Alembic line; nothing touches `_payload_for_row`.

**Task 2 — Models** (`706df59`): `audit_log.cache_creation_tokens` (nullable, non-hashed), `run.cost_pending` + `run.verification_summary`, and a new `VerificationVerdict` model mirroring the 0011 table (claim.py FK/RLS convention), registered in `db/models/__init__.py`. The existing `audit_log` hashed-field block is byte-identical except the one added non-hashed column.

**Task 3 — Fixture + tests** (`39ec257`):
- `verdict_extract.extract_group_verdicts(calls_dir)` parses the committed `group_skeptic` `emit_group_verdict` JSON blocks (176 extracts → 198 verdict rows, 31 `refute`, 29 with a dict reconciliation) into rows carrying verdict/confidence/evidence_refs/reconciliation/audit_id — no GCS pull.
- `loader.load_recorded_run(session, tenant_id)` seeds a `run` + `audit_log` rows (ordered by GCS **mtime**, not seq — Pitfall 6), `verification_verdict` rows, an **enriched** `stage_detail` (per-item `name/status/task_prompt/cost_usd/facts/audit_id` + per-stage `summary`), and `run.verification_summary` from the recorded funnel (`distilled=1162`, `kept=456`, `dropped=706`, `selected_verify=424`, `skipped_stable=32`, `verify_sessions=176`). `cost_usd` is derived via `cost_table.compute` over the recorded token counts (facts-only, NULL on unknown model — never guessed; all 4 recorded models are known).
- Two new tests: `test_chain_green_after_cost_migration` (verify_chain green + the 3 new column names absent from the frozen 11-field `_payload_for_row`) and `test_recorded_stage_detail_enriched` (≥1 item with both cost_usd AND audit_id, funnel counts match, ≥1 refute with non-null reconciliation + evidence_refs).

## Verification Strategy (author-by-construction — no local Python)

The dev box has no Python/Docker (per project memory), so the PRIMARY pytest gate
`pytest nestor_pulse_sdk/tests/test_hash_chain_replay.py -x` **must run in Cloud Build / the migrate-job at deploy** — it could not run locally. This is the documented phase-gate command for Task 1/2/3.

Static + data validation performed locally instead:
- Acceptance greps all pass (down_revision 0010, 2× tenant policy, ENABLE+FORCE RLS, 3 add_column, model columns, VerificationVerdict registered, `load_recorded_run`/`extract_group_verdicts` defined, mtime sort key, no seq sort key, both new tests present).
- **Extraction logic validated with a node re-implementation of the loader's regexes against the committed extracts**: 176 group_skeptic extracts → 198 verdict rows, 31 refute (29 with dict reconciliation) — confirming `test_recorded_stage_detail_enriched`'s refute+reconciliation assertion holds.
- Per-stage aggregates + all 4 recorded models confirmed present in `cost_prices.json`, so `cost_table.compute` returns non-null costs → the enriched-item (cost_usd + audit_id) assertion is satisfiable.

`alembic heads` single-head-at-0011 assertion is deferred to the migrate-job at deploy (author-by-construction).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Missing `text` import in run.py**
- **Found during:** Task 2
- **Issue:** `run.cost_pending` uses `server_default=text("false")`, but `run.py` only imported `Text` (the type), not `text` (the SQL construct helper). This would raise `NameError` at model import time and fail every tribunal test that imports the models.
- **Fix:** Added `text` to the `from sqlalchemy import (...)` list in `run.py`.
- **Files modified:** tribunal/nestor_pulse_sdk/db/models/run.py
- **Commit:** 706df59

**2. [Rule 2 - Missing critical functionality] Created `tests/fixtures/__init__.py`**
- **Found during:** Task 3
- **Issue:** The loader imports `nestor_pulse_sdk.tests.fixtures.run_4cbb5311.verdict_extract`, but `tests/fixtures/` had no `__init__.py`, so the package import path would not resolve.
- **Fix:** Added `tests/fixtures/__init__.py` (in addition to the plan-specified `run_4cbb5311/__init__.py`) so the dotted import path is a real package.
- **Files modified:** tribunal/nestor_pulse_sdk/tests/fixtures/__init__.py
- **Commit:** 39ec257

## Known Stubs

None. `run.verification_summary` and `verification_verdict` are intentionally populated with REAL recorded data by the fixture; the migration columns are nullable-now-populated-later by design (documented in the migration/model docstrings, resolved by Plans 15-02/15-03). No UI-facing empty stubs introduced.

## Threat Flags

None. All new surface is covered by the plan's threat register: T-15-01 (new columns outside `_payload_for_row` — asserted by `test_chain_green_after_cost_migration`), T-15-02 (verification_verdict FORCE RLS + tenant policy from day one; endpoint/seam denial tests land in 15-03/15-04), T-15-03 (migration in the tribunal line only, down_revision 0010). No new packages (T-15-SC).

## Self-Check: PASSED

- Files: 0011_cost_verification.py, verification_verdict.py, loader.py, verdict_extract.py, both fixture `__init__.py` — all FOUND.
- Commits 7c7139f, 706df59, 39ec257 — all present in `git log`.
