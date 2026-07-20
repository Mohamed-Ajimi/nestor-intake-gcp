# Phase 13 — Tribunal Re-home Proof Results

> Operator-recorded evidence for the Plan-04 live session. The dev machine has no
> Python/Docker and `terraform apply` is blocked, so every value below is captured by the
> operator (project "Nestor Pulse", acct `tools@dotto.be`, region `europe-west1`) from the
> live proof run and pasted here. This file feeds **Phase 16** stale-run + cost calibration
> (ENGINE-02) and closes the ENGINE-04 (chain) + ENGINE-08 (concurrency) gates.

Status: **AWAITING OPERATOR LIVE SESSION** — values are placeholders until the proof runs land.

---

## Deployed revisions (Task 1 — Step 13.a–13.g)

| Resource | Value |
|----------|-------|
| Intake project id (`$GOOGLE_PROJECT`) | _(record)_ |
| Image tag (`$SHA`) | _(record)_ |
| `tribunal-api` revision | _(record — e.g. tribunal-api-00001-abc)_ |
| `tribunal-worker` revision | _(record)_ |
| `tribunal-migrate` Job execution | _(record — execution id, exit 0)_ |
| Alembic version table | `tribunal.tribunal_alembic_version` (confirm — NOT `public.alembic_version`) |
| tribunal-api `/healthz` | _(200?)_ |
| tribunal-api `/readyz` | _(200? — needs Cloud SQL RUNNABLE)_ |
| Worker log `worker_started` | _(seen? binds worker_user, no SCHEMA-public grant errors)_ |
| FIRST-BUILD legitimacy gate (verbatim `requirements.txt`) | _(built cleanly? — Plan-01 T-13-SC gate)_ |

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
