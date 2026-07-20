---
phase: 13-tribunal-re-home-infra-baseline
reviewed: 2026-07-20T16:17:42Z
depth: standard
files_reviewed: 20
files_reviewed_list:
  - tribunal/nestor_pulse_sdk/runs/execute.py
  - tribunal/nestor_pulse_sdk/runs/worker.py
  - tribunal/nestor_pulse_sdk/alembic/env.py
  - tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py
  - tribunal/nestor_pulse_sdk/db/models/run.py
  - tribunal/nestor_pulse_sdk/db/base.py
  - tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py
  - tribunal/nestor_pulse_sdk/tests/test_schema_isolation.py
  - tribunal/nestor_pulse/__init__.py
  - tribunal/nestor_pulse/tools/__init__.py
  - tribunal/cloudbuild.api.yaml
  - tribunal/cloudbuild.worker.yaml
  - tribunal/cloudbuild.test.yaml
  - tribunal/infrastructure/cloud-run/deploy-api.sh
  - tribunal/infrastructure/cloud-run/deploy-worker.sh
  - tribunal/infrastructure/cloud-run/api/Dockerfile
  - tribunal/infrastructure/cloud-run/worker/Dockerfile
  - tribunal/.gcloudignore
  - infra/main.tf
  - infra/variables.tf
findings:
  critical: 3
  warning: 6
  info: 6
  total: 15
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-07-20T16:17:42Z
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

Reviewed the 20 phase-authored/phase-modified files of the Tribunal re-home: the per-run
advisory-lock keystone (`execute.py` + `worker.py` wiring), the isolated Alembic line
(`env.py`, `0008` rewrite, `run.py` CHECK sync, `base.py` search_path), the two new tests,
the namespace `__init__` files, and the deploy/IaC artifacts. No structural pre-pass was
provided; all findings below are narrative (AI reviewer).

The headline finding invalidates the phase's central claim. The advisory-lock wiring has a
claim-ordering defect that makes the production worker path **never dispatch any claimed
run** (CR-01). The live proofs do not contradict this: I traced the proof artifacts —
both the E2E run and the two concurrent runs in 13-PROOF-RESULTS.md were executed via
`run_tribunal_smoke.py`, which "calls dispatch_runner('sdk').run(...) directly in-process"
(its own header, `scripts/run_tribunal_smoke.py:24`), bypassing `worker_loop` →
`claim_one` → `execute_run_locked` entirely. The Cloud Build "exactly-once" test also
bypasses the claim step *and* patches a nonexistent module attribute (WR-02), so no
executed proof anywhere covers the real queue path. Separately, the by-construction
Terraform for the Tribunal footprint cannot produce a working deployment (CR-03) and
plants a destructive password-rotation landmine for the day it is applied/imported
(CR-02). The DB-schema isolation work itself (env.py version-table isolation, 0008 schema
retarget, ORM CHECK sync) is sound and matches the live evidence.

## Critical Issues

### CR-01: Production worker never dispatches claimed runs — claimable re-check excludes the claimer's own fresh claim

**File:** `tribunal/nestor_pulse_sdk/runs/execute.py:71-122` (with `tribunal/nestor_pulse_sdk/runs/worker.py:66-78, 276-298`)
**Issue:** `worker_loop` first claims a run via `CLAIM_SQL`, which sets
`status='running', started_at=NOW()` and **commits** (worker.py:278-280). It then calls
`execute_run_locked(claimed)`, whose `_CLAIMABLE_SQL` re-check accepts only
`status='queued'` OR `status='running' AND started_at < NOW() - 60min`. The worker's own
just-claimed run is `'running'` with a milliseconds-old `started_at`, so the re-check
returns no row, `still_claimable` is False, and the function logs
`run_not_claimable_after_lock` and returns **without ever calling `execute_run`**. The run
then sits `'running'` until the 60-minute stale window elapses, gets re-claimed (which
resets `started_at=NOW()` again), and is skipped again — an infinite claim/skip loop.
Every run enqueued through the real API→queue→worker path starves forever and never
reaches a terminal state.

This shipped green because nothing ever exercised the real sequence: the live concurrency
proof used `run_tribunal_smoke.py` Cloud Run Job executions (`tribunal-smoke-drbbj`/
`-sws55`), which dispatch the pipeline in-process and never touch `worker_loop`; and
`test_same_run_executes_exactly_once` seeds a `'queued'` run and calls
`execute_run_locked` directly, without the preceding claim (see WR-02).
**Fix:** Make the re-check recognize the claimer's own claim. Pass the claimer's identity
into `execute_run_locked` and extend the claimable set:
```sql
SELECT status FROM run
 WHERE id = :run_id
   AND (
         status = 'queued'
      OR (status = 'running' AND worker_id = :wid)                                   -- our own claim
      OR (status = 'running' AND started_at < NOW() - make_interval(mins => :stale)) -- crash recovery
       )
```
with `worker_loop` passing `WORKER_ID`. NOTE: this requires `WORKER_ID` to be unique per
poller — `f"{socket.gethostname()}-{os.getpid()}"` (worker.py:41) is likely **identical
across Cloud Run instances** (container hostname is commonly the same and the entrypoint
PID is 1 in every instance); append a per-process `uuid4().hex[:8]` (see IN-01). Then add
a regression test that claims via `claim_one` first and asserts the dispatch still happens
(the exact sequence production runs).

### CR-02: `terraform apply`/import would rotate app_user/worker_user passwords and take down the live Tribunal deployment

**File:** `infra/main.tf:771-797`
**Issue:** `google_sql_user.tribunal_app_user` / `tribunal_worker_user` set
`password = random_password.*.result`, but the live users were created out-of-band with
`gcloud sql users create` (their real passwords are embedded in the manually seeded
`DATABASE_URL` / `DATABASE_URL_WORKER` secret DSNs, per the runbook and the block's own
comment). The documented reconciliation path ("Reconcile via `terraform import` … BEFORE
…", main.tf:745) is destructive here: after import, the first `apply` will detect the
password attribute diff and **reset both DB users' passwords to Terraform's random
values**, silently invalidating both seeded DSN secrets → every Tribunal service (api,
worker, migrate) loses DB connectivity at its next connection/cold start. Unlike the
other "drift-inert" additive resources in this file, this one actively breaks the live
system when reconciled. (Also note: `random_password.result` and the `google_sql_user`
password *do* land in Terraform state once applied — the "nothing lands in committed
state" comment at main.tf:763-764 holds only while state doesn't exist.)
**Fix:** Do not manage the password attribute for users whose credentials are seeded
out-of-band. Either drop the two `random_password` resources and the `password` argument
and add `lifecycle { ignore_changes = [password] }` on both `google_sql_user` resources,
or make Terraform the single source of truth end-to-end (wire the generated passwords
into the DSN secret versions so apply is self-consistent). Half-managed passwords are the
worst of both.

### CR-03: Tribunal Cloud Run IaC cannot work as declared — no Cloud SQL socket attachment, and the migrate Job repeats a proven-failed invocation

**File:** `infra/main.tf:941-1042 (worker), 1049-1134 (api), 1154-1188 (migrate job)`
**Issue:** Two independent defects make the declared end-state non-functional:
1. All three Tribunal Cloud Run resources use asyncpg DSNs of the unix-socket form
   `...?host=/cloudsql/PROJECT:REGION:INSTANCE` (per the block header, main.tf:736-739 and
   variables.tf:309-310), which requires the Cloud SQL instance to be **attached** to the
   service/job (`gcloud --add/--set-cloudsql-instances`; in the v2 Terraform resources, a
   `volumes { cloud_sql_instance { instances = [...] } }` + `volume_mounts` pair). None of
   the three resources declares it — the `/cloudsql/...` socket will not exist in the
   container and every DB connection fails. (The intake `api`/`migrate` resources in the
   same file legitimately omit it because they use the IAM Python connector over TCP; the
   Tribunal block copied that shape without the attachment the socket DSN needs.)
2. `google_cloud_run_v2_job.tribunal_migrate` declares `args = ["alembic", "upgrade",
   "head"]` with the image's WORKDIR `/app`, but `alembic.ini` lives at
   `/app/nestor_pulse_sdk/alembic.ini`. This exact failure was **observed live**: the
   phase's own deviation log (13-PROOF-RESULTS.md, deviations #3) records execution
   `-5rmmh` failing on alembic cwd and the working form as
   `sh -c "cd /app/nestor_pulse_sdk && alembic upgrade head"` (plus
   `--set-cloudsql-instances` for jobs). The IaC still codifies the broken form — and so
   does the runbook (infra/DEPLOY-RUNBOOK.md Step 13.f, lines 844-852:
   `--add-cloudsql-instances` + `--command="alembic" --args="upgrade,head"`), despite the
   runbook being designated the operational source of truth. Out-of-scope file, but it
   must be corrected together with this.
**Fix:** Add to all three Tribunal resources:
```hcl
volumes {
  name = "cloudsql"
  cloud_sql_instance { instances = [google_sql_database_instance.main.connection_name] }
}
# inside containers { ... }
volume_mounts {
  name       = "cloudsql"
  mount_path = "/cloudsql"
}
```
and change the migrate job to the proven invocation:
`args = ["sh", "-c", "cd /app/nestor_pulse_sdk && alembic upgrade head"]` (or set a
container `working_dir`). Mirror both fixes into DEPLOY-RUNBOOK.md Step 13.f.

## Warnings

### WR-01: Advisory lock is released before dispatch — a stale reclaim of a still-running executor forks the audit chain anyway

**File:** `tribunal/nestor_pulse_sdk/runs/execute.py:92-99, 106-127` (with `worker.py:66-78`)
**Issue:** The lock is transaction-scoped and is released the instant the re-check
transaction commits (execute.py:107-115); `execute_run` then runs the ~15-35-minute
pipeline **without holding any lock**. If a healthy run exceeds `STALE_RUN_MINUTES` (60),
another poller's `CLAIM_SQL` reclaims it (SKIP LOCKED does not conflict — the original
executor holds no row lock either), passes its own re-check (the advisory lock is free),
and dispatches a second engine — exactly the audit-chain fork / double provider spend the
lock exists to prevent (T-13-06). There is no heartbeat refreshing `started_at`
mid-execution, so the only guard is the 60-minute constant vs. actual run length: the
proof's longest run was 1020s (~17 min), but the worker is provisioned for runs up to
3600s (deploy-worker.sh `--timeout=3600`), which is **equal to** the stale threshold. The
module docstring's claim that holding the lock only for the re-check "is sufficient for
exactly-once" is only true for the queued path, not the crash-recovery path.
**Fix:** Either hold the advisory lock for the duration of the dispatch (session-scoped
`pg_advisory_lock` on a dedicated connection, released in a `finally`), or add a
heartbeat (`UPDATE run SET started_at/last_heartbeat = NOW()` on an interval task) so a
live executor can never look stale. At minimum, enforce `STALE_RUN_MINUTES` strictly
greater than the maximum possible run duration and document the invariant where both
constants are set (Phase 16 calibration).

### WR-02: The "exactly-once" live tests patch a nonexistent attribute and cannot intercept the real dispatch — the ENGINE-08 proof proves nothing about the wired path

**File:** `tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py:200, 230`
**Issue:** `patch.object(execute_mod, "execute_run", new=AsyncMock(...))` targets
`nestor_pulse_sdk.runs.execute.execute_run` — but `execute.py` has **no module-level
`execute_run` attribute** (it is imported lazily *inside* `execute_run_locked`,
execute.py:104). `patch.object` with the default `create=False` raises `AttributeError`
for missing attributes, so when these skip-guarded tests actually execute they error
before asserting anything; and even with `create=True` the patch would be ineffective,
because the lazy `from nestor_pulse_sdk.runs.worker import execute_run` resolves from the
*worker* module at call time — the real engine would be dispatched. The reported
Cloud Build green is therefore consistent only with these live tests having been skipped
(or collected-but-not-run), not with them passing as described. Compounding this, both
live tests seed `status='queued'` and call `execute_run_locked` directly, never modeling
the production claim-then-lock sequence — which is precisely why CR-01 survived a "green"
suite.
**Fix:** Patch the true target: `with patch("nestor_pulse_sdk.runs.worker.execute_run",
new=AsyncMock(side_effect=_fake_execute_run)):`. Add a third live test that goes through
`claim_one()` first and asserts the claimed run still dispatches exactly once (this test
must fail on the current code, proving it covers CR-01).

### WR-03: Tribunal services run as the intake runtime SA — the carried engine inherits intake-admin capabilities, undercutting the T-13-09 isolation firewall

**File:** `tribunal/infrastructure/cloud-run/deploy-api.sh:32`, `deploy-worker.sh:40`, `infra/main.tf:946, 1054, 1160`
**Issue:** Both Tribunal services and the migrate job run as
`nestor-run@...` — the same SA as the intake backend. That SA holds resource-scoped
`secretAccessor` on the intake superadmin DB password secret (main.tf:144-148),
`roles/identitytoolkit.admin` (create IdP users / set custom claims, main.tf:276-280),
`storage.objectAdmin` on the tenant uploads bucket, and accessor grants on every intake
provider key. The Tribunal worker executes a large verbatim-carried engine that drives
LLM calls over untrusted research content (prompt-injection → SSRF/metadata-token risk is
the classic chain); a compromise of that process can read the `app_superadmin` password
and connect to the intake `nestor` schema cross-tenant — making the carefully built
DB-level firewall ("worker_user granted on `tribunal` ONLY, never `nestor`") moot at the
IAM layer.
**Fix:** Provision a dedicated `tribunal-run` SA with only: `cloudsql.client`,
accessor on the six Tribunal secrets, and `objectAdmin` on the audit bucket. Point both
deploy scripts and the three Terraform resources at it. No intake secret grants.

### WR-04: `include_schemas=True` on a shared database with no `include_object` filter — autogenerate/`alembic check` will diff intake's schemas and emit cross-schema drops

**File:** `tribunal/nestor_pulse_sdk/alembic/env.py:78, 113`
**Issue:** Both `context.configure()` calls set `include_schemas=True` with no
`include_object`/`include_name` filter. The Tribunal line now runs against the **shared
intake database** (`nestor`, `public` schemas alongside `tribunal`). Any
`alembic revision --autogenerate` or `alembic check` (which run.py:106 explicitly
anticipates for ORM/DB drift checks) will reflect every schema and, since the intake
tables are absent from `Base.metadata`, propose `drop_table` operations for the entire
intake schema. One inattentive autogenerate-and-apply away from generating a migration
that attempts to destroy intake tables.
**Fix:** Add a filter to both `configure()` calls:
```python
def _include_object(obj, name, type_, reflected, compare_to):
    if type_ == "table":
        return obj.schema in (None, "tribunal")
    return True
# context.configure(..., include_object=_include_object)
```
(or drop `include_schemas=True` entirely — all Tribunal tables are schema-less in the
metadata and resolved via search_path, so single-schema comparison suffices).

### WR-05: `worker_user` gets UPDATE/DELETE on `audit_log` — a cross-tenant tamper surface on the legally load-bearing hash chain

**File:** `tribunal/nestor_pulse_sdk/alembic/versions/0008_worker_rls_role.py:70-85`
**Issue:** The migration grants `SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA
tribunal` to `worker_user`, and the `*_worker_all` policies open all rows of all tenants
to it. The audit hash chain (EU AI Act Art. 12, per the phase's own framing) is only as
trustworthy as the roles that can rewrite it: the worker needs INSERT (append entries) and
SELECT (cost SUM), never UPDATE/DELETE on `audit_log` — yet a compromised or buggy worker
can currently rewrite or delete any tenant's chain rows. (The grant also covers
`tribunal_alembic_version`, which the worker has no business touching.)
**Fix:** Replace the blanket grant with per-table grants: full DML where the worker
writes state (`run`, `output`, `source`, `claim`, `claim_source`, …), but
`SELECT, INSERT` only on `audit_log`. Mirror the reduction in the `WITH CHECK`/policy
surface if per-command policies are introduced.

### WR-06: Test-suite global state — `os.environ["DATABASE_URL"]` mutation + `lru_cache`d engine makes the live tests order-dependent

**File:** `tribunal/nestor_pulse_sdk/tests/test_advisory_lock_exactly_once.py:156`, `test_schema_isolation.py:159` (with `db/base.py:33-43`)
**Issue:** Both live tests overwrite `os.environ["DATABASE_URL"]` process-wide and never
restore it. Worse, `execute_run_locked` internally uses `get_sessionmaker()` →
`get_engine()`, which is `@lru_cache`d on first call: if any earlier test in the suite
already built the engine (against its own, since-stopped testcontainer), the advisory-lock
test silently runs its lock/re-check against a dead or wrong database regardless of the
env var it just set, while its seed helper (which builds its own engine from the fresh
URL) targets the new container — the two halves of the test can talk to different
databases depending on collection order.
**Fix:** In `_make_live_sessionmaker`, call `get_engine.cache_clear()` after setting the
env var (and restore the previous `DATABASE_URL` in `_cleanup`), or refactor the live
tests to inject the sessionmaker instead of relying on the process-global engine.

## Info

### IN-01: WORKER_ID is likely not unique across Cloud Run instances

**File:** `tribunal/nestor_pulse_sdk/runs/worker.py:41`
**Issue:** `f"{socket.gethostname()}-{os.getpid()}"` — in Cloud Run every instance runs
the entrypoint as PID 1 and the container hostname is frequently identical across
instances, so all 5 workers can report the same `worker_id`. Harmless today (diagnostic
column), but it blocks the worker-id-based ownership re-check proposed for CR-01.
**Fix:** Append a per-process token: `f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"`.

### IN-02: Deploy scripts default to the mutable `latest` image tag

**File:** `tribunal/infrastructure/cloud-run/deploy-api.sh:37`, `deploy-worker.sh:47`
**Issue:** `IMAGE_TAG="${IMAGE_TAG:-latest}"` deploys whatever `latest` currently points
at — non-reproducible rollouts if the operator forgets `IMAGE_TAG=$SHA` (the runbook does
pass it, but the default invites drift).
**Fix:** Make IMAGE_TAG required: `IMAGE_TAG="${IMAGE_TAG:?pass the immutable tag from the Cloud Build step}"`.

### IN-03: Project-global generic secret names (`DATABASE_URL`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET`)

**File:** `infra/variables.tf:315-332`
**Issue:** These Tribunal secrets live in the shared intake project's flat Secret Manager
namespace under maximally generic names, alongside the intake's prefixed convention
(`nestor-*`). Any future service reaching for "the DATABASE_URL secret" gets the Tribunal
app_user DSN. The constraint is the verbatim-carried `secrets_bootstrap.py` names, but
that constraint applies to the `Nestor_*` provider keys — the DSN/bucket secrets are
mounted explicitly by name in the deploy scripts and could be prefixed (`tribunal-*`).
**Fix:** Rename the three non-bootstrap secrets to `tribunal-database-url`,
`tribunal-database-url-worker`, `tribunal-audit-gcs-bucket` and update the mount flags.

### IN-04: Containers run as root and ship tests + operational scripts

**File:** `tribunal/infrastructure/cloud-run/api/Dockerfile:28-43`, `worker/Dockerfile:24-36`
**Issue:** Neither runtime stage declares a non-root `USER`, and `COPY nestor_pulse_sdk`
brings `tests/` and `scripts/` (including `run_tribunal_smoke.py`, which self-provisions
orgs) into the production images. Baseline-hardening and image-surface nits, mitigated by
Cloud Run's sandbox.
**Fix:** Add `RUN useradd -r app && USER app` and a `.dockerignore` (or explicit COPY
list) excluding `tests/`.

### IN-05: `search_path=tribunal,public` fallback can mask a missing-migration state in production

**File:** `tribunal/nestor_pulse_sdk/db/base.py:51-57`
**Issue:** The `public` fallback exists for the testcontainers suite, but on the shared
production DB it means an un-migrated (or dropped) `tribunal` schema degrades into
confusing `relation does not exist` errors resolved against `public` — or, if a
same-named table ever appears in `public`, into silently querying the wrong schema.
**Fix:** Gate the fallback on a test/env flag, or set `search_path` to `tribunal` alone
in production and let the suite override via env.

### IN-06: `tribunal_image_tag` defaults to `""` — composes invalid image refs; env drift between scripts and TF

**File:** `infra/variables.tf:274-278` (with `infra/main.tf:751-752`), `deploy-*.sh --set-env-vars`
**Issue:** Unlike `image_tag`/`frontend_image_tag` (no default — apply forces a value),
`tribunal_image_tag = ""` lets an apply silently plan `.../tribunal-api:` (invalid
reference). Also, the deploy scripts set `NESTOR_ENV=prod` (and the worker
`NESTOR_WORKER_POLL_INTERVAL`) which the Terraform resources omit — the "intended
end-state" and the operational scripts disagree on the env surface.
**Fix:** Remove the `""` default (or add a `validation` block rejecting empty), and add
the missing `NESTOR_ENV` env to the two Terraform service resources.

---

_Reviewed: 2026-07-20T16:17:42Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
