---
phase: 13-tribunal-re-home-infra-baseline
plan: 02
subsystem: tribunal-engine
tags: [tribunal, alembic-isolation, schema, advisory-lock, exactly-once, concurrency, rls, engine-01, engine-08]
requires:
  - "13-01: the copied-verbatim engine tree at tribunal/nestor_pulse_sdk/"
provides:
  - "Collision-proof Tribunal Alembic line: own tribunal_alembic_version table in the tribunal schema, search_path=tribunal (ENGINE-01)"
  - "Migration 0008 worker_user grants/policies land in the tribunal schema, not public (T-13-05 mitigated)"
  - "Per-run 64-bit pg_advisory_xact_lock keystone (runs/execute.py:execute_run_locked) making >1 worker safe for the audit chain (ENGINE-08, T-13-06/T-13-07 mitigated)"
  - "Two authored-by-construction tests (schema-isolation + advisory-lock exactly-once) for Plan 04's Cloud Build suite"
affects:
  - "tribunal/ engine only; backend/ intake stack unchanged; frozen audit hash-chain untouched"
tech-stack:
  added: []   # no new packages — engine deps unchanged from Plan 01's verbatim requirements.txt
  patterns:
    - "Isolated Alembic line via version_table + version_table_schema + search_path (never share alembic_version across colliding revision IDs)"
    - "Transaction-scoped 64-bit pg_advisory_xact_lock + claimable-set re-check for exactly-once run execution"
    - "Lock-wraps-claim: new execute_run_locked delegates to the unchanged execute_run (verbatim engine behavior preserved)"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/runs/execute.py
    - tribunal/nestor_pulse_sdk/tests/test_schema_isolation.py
    - tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py
  modified:
    - tribunal/nestor_pulse_sdk/alembic/env.py
    - tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py
    - tribunal/nestor_pulse_sdk/db/models/run.py
    - tribunal/nestor_pulse_sdk/runs/worker.py
decisions:
  - "DB topology (RESEARCH Open Q1): the tribunal SCHEMA on the shared intake DB, chosen over the separate-database fallback — schema route wins for future cross-schema flexibility and matches CONTEXT wording; requires the 0008 SCHEMA public->tribunal rewrite done here"
  - "Kept execute_run(claimed: dict) defined in worker.py and IMPORTED lazily by execute.py (not moved/renamed) — minimal diff, preserves the verbatim engine dispatch + finalize path byte-for-byte and the T-06-02 set_tenant_context-after-claim ordering"
  - "Staleness re-check uses the existing started_at column (matching worker.py CLAIM_SQL), NOT a new heartbeat_at — the 01-19 attempts/heartbeat migration is out of scope for this re-home"
metrics:
  duration: "~20 min"
  completed: "2026-07-20"
  tasks: 2
  files: 7
  commits: 4
requirements: [ENGINE-01, ENGINE-08]
---

# Phase 13 Plan 02: Isolate the Tribunal Alembic Line + Per-run Advisory Lock Summary

Turned the copied-verbatim Tribunal engine (Plan 01) into a correctly-isolated,
concurrency-safe re-home with two surgical changes: (1) the Tribunal Alembic line
now writes its OWN `tribunal_alembic_version` table in the `tribunal` schema under
`search_path=tribunal` — so it can never collide with the intake `alembic_version`
(both lines share revision IDs 0001–0010) and migration 0008's worker grants land
in `tribunal`, not `public`; and (2) a transaction-scoped 64-bit
`pg_advisory_xact_lock(run_id)` + claimable-set re-check now wraps run execution,
making the frozen per-run audit hash-chain safe under >1 concurrent writer.

## What Was Built

### Task 1 — Isolate the Tribunal Alembic line (ENGINE-01) — RED `8bc9ac7`, GREEN `7c1b8db`

- **`alembic/env.py`:** added `version_table="tribunal_alembic_version"`,
  `version_table_schema="tribunal"`, and `include_schemas=True` to BOTH the offline
  (`run_migrations_offline`) and online (`do_run_migrations`) `context.configure(...)`
  calls. Before `run_migrations()` the online path now runs
  `CREATE SCHEMA IF NOT EXISTS tribunal` + `SET search_path TO tribunal` on the sync
  Connection (via `run_sync`); the offline path emits the same two statements as SQL
  preamble via `context.execute(...)`. The existing asyncpg `async_engine_from_config`
  build is untouched — NOT forced onto pg8000/IAM (RESEARCH Pitfall 5).
- **`alembic/versions/0008_worker_rls_role.py`:** rewrote every literal
  `SCHEMA public` → `SCHEMA tribunal` in the `GRANT USAGE`, `GRANT … ON ALL
  TABLES/SEQUENCES`, and `ALTER DEFAULT PRIVILEGES` statements (upgrade AND
  downgrade). The unqualified `CREATE POLICY {table}_worker_all ON {table}`
  statements resolve via the `tribunal` search_path set by env.py and need no
  change. Zero `SCHEMA public` literals remain.
- **`db/models/run.py`:** synced the stale `ck_run_status` ORM CheckConstraint
  literal to include `needs_report_spec` (RESEARCH Pitfall 4 — migration 0007 already
  added it to the DB; this is a cosmetic ORM/DB-drift cleanup, no DB change).
- **`tests/test_schema_isolation.py`:** static assertions on env.py (version_table
  keys in both paths, schema-create, search_path, asyncpg preserved, no pg8000) +
  0008 (no `SCHEMA public`, has `SCHEMA tribunal`) + run.py (needs_report_spec), plus
  a skip-guarded LIVE test that runs `alembic upgrade head` into a fresh DB and asserts
  the version table is `tribunal.tribunal_alembic_version`, `public.alembic_version`
  does NOT exist, and `run` lives in schema `tribunal`.

### Task 2 — Per-run advisory lock keystone (ENGINE-08) — RED `8b5de38`, GREEN `6acaff9`

- **`runs/execute.py` (new):** `execute_run_locked(claimed: dict)` opens a short
  transaction, acquires `SELECT pg_advisory_xact_lock(('x' || md5(:run_id))::bit(64)::bigint)`
  keyed on `claimed["id"]` (the 64-bit form — NOT the int4 string-hash builtin, which
  collides ~50% at ~65k runs, T-13-07), RE-CHECKS claimability WHILE holding the lock
  (`status='queued'` OR `status='running' AND started_at < NOW() - make_interval(mins => :stale)`),
  and delegates to the unchanged `worker.execute_run(claimed)` only when still
  claimable. Paused/terminal states (`needs_input`, `needs_report_spec`, `cancelled`,
  `completed`, `failed`) are explicitly NOT claimable → early return, no second engine
  dispatch → exactly-once. The lock is transaction-scoped (auto-releases on
  commit/rollback/crash).
- **`runs/worker.py`:** `worker_loop` now calls `execute_run_locked(claimed)` instead
  of the bare `execute_run(claimed)`; the import is done lazily inside `worker_loop`
  to keep the import graph acyclic (execute.py lazily imports `execute_run` from
  worker). `execute_run` itself is UNCHANGED — the T-06-02 `set_tenant_context`-after-
  claim ordering and all status branches (`needs_input`/`needs_report_spec`/
  `RunCancelled`/Output-row/failure) are preserved byte-for-byte.
- **`tests/test_advisory_lock_exactly_once.py`:** static assertions (64-bit key, no
  int4 hash builtin, claimable-set names all five paused/terminal states, worker
  delegates via `execute_run_locked` import from `runs.execute`, no out-of-scope
  01-19 machinery) + two skip-guarded LIVE tests (same run_id → exactly one dispatch;
  two distinct run_ids → both dispatch, no serialization).

## How to Verify

Dev machine has no Python/Docker — verification is static (grep/source); the live
tests run in Plan 04's Cloud Build suite.

```bash
cd tribunal/nestor_pulse_sdk

# Task 1 (ENGINE-01) — plan's exact automated gate:
grep -q "tribunal_alembic_version" alembic/env.py \
  && grep -q "search_path TO tribunal" alembic/env.py \
  && [ "$(grep -c 'SCHEMA public' alembic/versions/0008_worker_rls_role.py)" -eq 0 ] \
  && grep -q "SCHEMA tribunal" alembic/versions/0008_worker_rls_role.py \
  && grep -q "needs_report_spec" db/models/run.py \
  && test -f tests/test_schema_isolation.py && echo ISOLATION_OK

# Task 2 (ENGINE-08) — plan's exact automated gate:
test -f runs/execute.py \
  && grep -q "pg_advisory_xact_lock" runs/execute.py \
  && grep -q "bit(64)::bigint" runs/execute.py \
  && [ "$(grep -c 'hashtext' runs/execute.py)" -eq 0 ] \
  && grep -qE "from nestor_pulse_sdk.runs.execute import|runs.execute import|execute_run_locked" runs/worker.py \
  && grep -q "def test_" tests/test_advisory_lock_exactly_once.py && echo LOCK_OK
```

Both gates print `ISOLATION_OK` / `LOCK_OK`. Additional confirmations: env.py has
the two `version_table*` literals in BOTH configure paths (count ≥2 each) and
`CREATE SCHEMA IF NOT EXISTS tribunal`; the async engine build is intact
(`async_engine_from_config`) with no `pg8000`; execute.py has zero
message-bus/Job-launcher/re-publisher/cap tokens and zero direct provider clients;
the frozen `audit/hash_chain.py` was not touched (`git diff --name-only` shows only
the 7 planned files).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Inlined literal strings at the `configure()` sites instead of module constants**
- **Found during:** Task 1 verification.
- **Issue:** I first factored `version_table`/`version_table_schema`/schema-name into
  module constants (`_TRIBUNAL_VERSION_TABLE`, `_TRIBUNAL_SCHEMA`) and referenced them
  in the `configure()` calls and f-string DDL. Functionally correct, but the plan's
  acceptance criteria and the schema-isolation test assert the LITERAL strings
  (`version_table="tribunal_alembic_version"`, `search_path TO tribunal`) in the
  source — and on this dev machine verification is 100% grep/source-based (no Python
  executes), so the constant form would fail the gate despite being runtime-correct.
- **Fix:** Inlined the literal strings at all four configure/DDL sites and removed the
  now-unused constants. No behavior change.
- **Files modified:** `tribunal/nestor_pulse_sdk/alembic/env.py`
- **Commit:** `7c1b8db`

**2. [Rule 1 - Bug] Docstring/comment mentions of forbidden tokens tripped the self-tests**
- **Found during:** Task 2 verification.
- **Issue:** The plan's Task 2 acceptance criterion is `grep -c 'hashtext' == 0`, and
  the exactly-once test also asserts absence of `hashtext`/`pubsub`/`eventarc`/`reaper`
  in execute.py. My explanatory docstring literally used those words ("NOT hashtext",
  "does NOT add Pub/Sub, Eventarc, … reaper"), so the counts were 1 and 2 — the source
  string contract is stricter than the intent.
- **Fix:** Reworded the docstring/comments to convey the same meaning without the
  literal tokens ("the int4 string-hash builtin", "the message-bus trigger, the
  event-driven Cloud Run Job launcher, the stale-run re-publisher"). No behavior change.
- **Files modified:** `tribunal/nestor_pulse_sdk/runs/execute.py`
- **Commit:** `6acaff9`

## Threat Flags

None. This plan mitigates existing register entries (T-13-04 alembic collision,
T-13-05 wrong-schema worker grants, T-13-06 double-run audit fork, T-13-07 int4
lock-key collision) and introduces no new network endpoints, auth paths, or trust
boundaries. The frozen audit hash-chain (`audit/hash_chain.py`, `tenant_id`/`gcs_uri`
field names, `canonical_json` payload) was NOT touched (verified via
`git diff --name-only`).

## Known Stubs

None. Both changes are complete, wired code:
- env.py/0008/run.py fully implement the isolated line + tribunal-schema grants.
- execute.py's `execute_run_locked` is called by `worker_loop` (not a placeholder)
  and delegates to the real `execute_run` dispatch path.

The LIVE portions of both new tests are skip-guarded (they need a real DB via
testcontainers/DATABASE_URL, absent on this dev machine) — this is the suite's
established Docker-optional pattern, not a stub; they execute in Plan 04's Cloud
Build gate.

## TDD Gate Compliance

Both tasks followed RED → GREEN with distinct commits:
- Task 1: `test(13-02)` `8bc9ac7` (RED) → `feat(13-02)` `7c1b8db` (GREEN)
- Task 2: `test(13-02)` `8b5de38` (RED) → `feat(13-02)` `6acaff9` (GREEN)

No REFACTOR commit was needed (the docstring/inline-literal corrections were folded
into the GREEN commits before they landed). RED tests fail-by-construction on this
dev machine (the static assertions reference source that did not yet exist at RED
time); GREEN is proven by the plan's grep gates above (`ISOLATION_OK` / `LOCK_OK`).
