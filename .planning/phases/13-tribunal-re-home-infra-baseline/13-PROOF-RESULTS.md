# Phase 13 — Tribunal Re-home Proof Results

> Operator-recorded evidence for the Plan-04 live session. The dev machine has no
> Python/Docker and `terraform apply` is blocked, so every value below is captured by the
> operator (project "Nestor Pulse", acct `tools@dotto.be`, region `europe-west1`) from the
> live proof run and pasted here. This file feeds **Phase 16** stale-run + cost calibration
> (ENGINE-02) and closes the ENGINE-04 (chain) + ENGINE-08 (concurrency) gates.

Status: **TASK 1 COMPLETE (deploy green, 2026-07-20)** — Tasks 2–3 in progress.

> **Single-project discovery (live-session correction).** There is NO separate intake
> project: `project-cb01b861-cb4a-438d-b9a` IS "Nestor Pulse" and hosts BOTH the live
> intake platform AND the old standalone Tribunal build. All "old project" teardown steps
> are **resource-level** (services `nestor-pulse-*`, stopped SQL `nestor-prod-pg`, AR repo
> `nestor-pulse`) — NEVER project deletion. Provider secrets (`Nestor_*`) already existed
> in-project; no reseeding was needed (D-06 satisfied trivially).

---

## Deployed revisions (Task 1 — Step 13.a–13.g)

| Resource | Value |
|----------|-------|
| Intake project id (`$GOOGLE_PROJECT`) | `project-cb01b861-cb4a-438d-b9a` (the single "Nestor Pulse" project) |
| Image tag (`$SHA`) | `20260720-161029-fix1` (both images; `-fix1` = env.py commit fix rebuild) |
| `tribunal-api` revision | `tribunal-api-20260720-161029-fix1-164103` |
| `tribunal-worker` revision | `tribunal-worker-20260720-161029-fix1-163954` |
| `tribunal-migrate` Job execution | `tribunal-migrate-sc64g` — succeeded (exit 0; earlier `-5rmmh` failed on alembic cwd, `-mhwdh` rolled back — see deviations) |
| Alembic version table | ✅ `tribunal.tribunal_alembic_version` = `0010`; 10 tables in `tribunal`; 0 leak into `public`; `ck_run_status` includes `needs_report_spec` |
| tribunal-api `/healthz` | `/health` → 200 `{"status":"ok"}` (`/healthz` is intercepted by Cloud Run's platform — documented in `health.py`) |
| tribunal-api `/readyz` | ✅ 200 `{"status":"ready","db":"ok"}` |
| Worker log `worker_started` | ✅ `worker_started poll_s=2.0`, health server up, zero WARNING+ logs (worker_user DSN, no SCHEMA-public grant errors) |
| FIRST-BUILD legitimacy gate (verbatim `requirements.txt`) | ✅ Both images built cleanly on first submit (T-13-SC) |

### Live-session deviations (Task 1)

1. **`db/base.py` runtime search_path fix (commit `fix(13-02)`):** runtime engine was
   schema-blind; added `server_settings search_path=tribunal,public` — proven by `/readyz`
   `db:ok`.
2. **`env.py` transaction-ownership fix (commit `fix(13-02)`):** the pre-configure
   `CREATE SCHEMA`/`SET search_path` autobegan a transaction Alembic didn't own → first
   migration run (`-mhwdh`) logged 0001→0010 then silently ROLLED BACK. Preamble commits
   added; rerun persisted (verified via one-off `tribunal-verify` job).
3. **Migrate job invocation:** jobs use `--set-cloudsql-instances` (not
   `--add-cloudsql-instances`) and alembic must run from `/app/nestor_pulse_sdk`
   (`sh -c "cd /app/nestor_pulse_sdk && alembic upgrade head"`) because
   `alembic.ini script_location` is cwd-relative.
4. **Old services share `DATABASE_URL*:latest`:** the defunct `nestor-pulse-*` services
   (SQL `nestor-prod-pg` STOPPED) reference the same secret ids; they may crash-loop on
   cold start until torn down — harmless (they have no `public.run` to corrupt).

## Cloud Build test suite (Task 2 — Step 13.e `cloudbuild.test.yaml`)

| Item | Value |
|------|-------|
| Build id | _(record)_ |
| Exit status | _(0 = green)_ |
| `test_schema_isolation.py` (Plan 02) | _(pass?)_ |
| `test_advisory_lock_exactly_once.py` (Plan 02) | _(pass?)_ |

## LUKOIL benchmark E2E proof run (Task 2 — ENGINE-02 + ENGINE-04)

> Single real run via `run_tribunal_smoke.py --brief "<LUKOIL COMBINED_BRIEF>"` (or
> `NESTOR_E2E=1 pytest test_tribunal_e2e.py -x`). Guard: `DEMO_MODE` unset,
> `NESTOR_SDK_ORCHESTRATOR=tribunal`. Source brief:
> `C:\Users\ajimimo\Desktop\MOELD\Nestor\lukoil_questions.py` (COMBINED_BRIEF, D-05).

| Metric | Value |
|--------|-------|
| `run_id` | _(record)_ |
| `tenant_id` / `project_id` | _(record)_ |
| Elapsed seconds (wall-clock, max run length) | _(record — feeds Phase 16 stale calibration)_ |
| `cost_usd` (sum) | _(record — RECORDED not enforced; D-07 UNCAPPED=1)_ |
| Total claims | _(> 0?)_ |
| Grounded claims / `claim_source` count | _(≥ 1?)_ |
| Recall % | _(> 0, in [0,1]?)_ |
| **`verify_chain` result** | _( **OK** — `broken_at` is None — ENGINE-04 LEGAL GATE)_ |

## Concurrency proof (Task 3 — ENGINE-08 / D-08)

> ≥2 runs triggered SIMULTANEOUSLY from DIFFERENT `tenant_id`s (two smoke invocations with
> distinct `--tenant-id`, or two `POST /api/runs`). Required gate is ≥2; push toward ~5 to
> validate the D-08 target. Both must complete with `verify_chain` OK and no forked chain /
> double-run (advisory lock + claimable-set guard held).

| Run | tenant_id | run_id | verify_chain | double-ran / forked? |
|-----|-----------|--------|--------------|----------------------|
| A | _(record)_ | _(record)_ | _(OK?)_ | _(no)_ |
| B | _(record)_ | _(record)_ | _(OK?)_ | _(no)_ |
| _(C…E, toward 5)_ | | | | |

Concurrency verdict: _(both/all green, advisory lock held — ENGINE-08 closed?)_

## Teardown (Task 3 tail — Step 13.i, D-02) — STRICTLY AFTER the proofs are green

| Action | Done? |
|--------|-------|
| `nestor-pulse-api` (old `project-cb01b861`) deleted | _(record)_ |
| `nestor-pulse-worker` (old) deleted | _(record)_ |
| `nestor-prod-pg` Cloud SQL instance (old) deleted | _(record — irreversible)_ |
| `nestor-pulse` Artifact Registry repo (old) deleted | _(record)_ |
| Intake `tribunal-api` `/readyz` still 200 post-teardown | _(record — no cross-dependency on old project)_ |
| Legacy Supabase project | UNTOUCHED (independence, never deleted) |
