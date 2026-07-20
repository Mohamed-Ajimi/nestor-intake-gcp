---
phase: 13-tribunal-re-home-infra-baseline
plan: 03
subsystem: tribunal-infra
tags: [tribunal, iac, cloud-run, cloud-build, deploy-runbook, audit-retention, secrets, by-construction]
requires:
  - "13-01: tribunal/ engine tree (nestor_pulse_sdk + nestor_pulse leaf) + copied deploy scripts/Dockerfiles"
provides:
  - "By-construction Terraform for the full Tribunal footprint (2 Cloud Run services + tribunal-migrate Job + 7y-Unlocked audit bucket + 6 secrets + 2 BUILT_IN DB roles)"
  - "DEPLOY-RUNBOOK.md § Phase 13 — the enumerated operator source of truth for the Plan-04 live session (deploy + FINAL post-proof teardown of project-cb01b861)"
  - "Retargeted deploy-{api,worker}.sh (intake project, worker max=5) + Cloud Build configs for both images + the test gate"
affects:
  - "tribunal/infrastructure/cloud-run/api/Dockerfile (Rule 1 fix: now COPYs nestor_pulse — boot dep)"
  - "Plan 04 (operator live session) consumes the runbook + IaC + scripts authored here"
tech-stack:
  added: []   # no new packages — test gate installs from the verbatim tribunal/requirements.txt (T-13-SC)
  patterns:
    - "By-construction IaC (drift-honest: terraform apply blocked; runbook is the enumerated source of truth)"
    - "Native Secret Manager injection into Cloud Run (value_source.secret_key_ref, version=latest) — reference never value"
    - "Object Retention (mode=Unlocked, per-object 7y) via enable_object_retention — NOT Bucket Lock (D-09)"
    - "BUILT_IN password DB users + asyncpg DSN secrets (Pitfall 5) — not the intake IAM connector path"
key-files:
  created:
    - tribunal/cloudbuild.api.yaml
    - tribunal/cloudbuild.worker.yaml
    - tribunal/cloudbuild.test.yaml
  modified:
    - infra/main.tf
    - infra/variables.tf
    - infra/DEPLOY-RUNBOOK.md
    - tribunal/infrastructure/cloud-run/deploy-api.sh
    - tribunal/infrastructure/cloud-run/deploy-worker.sh
    - tribunal/infrastructure/cloud-run/api/Dockerfile
decisions:
  - "Audit-bucket retention wired via enable_object_retention=true (per-object Unlocked) + NO bucket-level retention_policy — matches gcs_blob.py's blob.retention API, avoids irreversible Bucket Lock (D-09)"
  - "Tribunal DB auth = BUILT_IN password users (app_user/worker_user) + asyncpg DATABASE_URL* secrets, NOT the intake IAM-connector path (RESEARCH Pitfall 5)"
  - "Provider keys reseeded under the exact Nestor_* secret names secrets_bootstrap.py reads — no bootstrap refactor (D-06 / Open Q3)"
  - "Test gate gives testcontainers the host Docker socket rather than modifying the byte-identical conftest (ENGINE-04 integrity); deps from verbatim requirements.txt (T-13-SC)"
metrics:
  duration: "~20 min"
  completed: "2026-07-20"
  tasks: 2
  files: 9
  commits: 3
---

# Phase 13 Plan 03: Tribunal Infra Baseline (by-construction) Summary

Authored, by construction, the entire infrastructure footprint needed to deploy the re-homed
Tribunal deep-research engine into the intake "Nestor Pulse" GCP project — WITHOUT running
anything live (Plan 04 is the operator session; the dev box has no Python/Docker and
`terraform apply` is blocked). This closes the recurring "deployed but not wired" IaC-drift
gap by making `DEPLOY-RUNBOOK.md § Phase 13` the single enumerated source of truth.

## What Was Built

- **Task 1 — by-construction IaC (`821e6c4`):** Extended `infra/main.tf` + `infra/variables.tf`
  with the full Tribunal footprint, mirroring the existing intake resource shapes:
  - `tribunal-worker` Cloud Run service — `min_instance_count=1` (D-04 always-on),
    `max_instance_count=5` (D-08 concurrency), `cpu_idle=false` (no-cpu-throttling),
    `timeout=3600s`, `NESTOR_TRIBUNAL_UNCAPPED=1` (D-07), `DATABASE_URL` sourced from the
    `DATABASE_URL_WORKER` secret (worker_user, the cross-tenant claim role).
  - `tribunal-api` Cloud Run service — `min=0/max=3/timeout=300`, `DATABASE_URL` from the
    app_user secret; authenticated-only invoker gated on `var.allow_unauthenticated`.
  - `tribunal-migrate` Cloud Run Job — `args=["alembic","upgrade","head"]`, app_user asyncpg
    DSN (NOT the IAM connector — Pitfall 5), depends on app_user + its secret grant.
  - Audit-evidence GCS bucket — `enable_object_retention=true` so the engine's per-object
    `blob.retention.mode="Unlocked"` + 7y `retain_until_time` is honored (D-09), with a
    DELIBERATE absence of any bucket-level `retention_policy` (Bucket Lock is forbidden);
    hardened like the uploads bucket + bucket-scoped `storage.objectAdmin`.
  - Six Secret Manager secrets — `Nestor_Gemini`/`Nestor_Claude`/`Nestor_OpenAI` (the exact
    names `secrets_bootstrap.py` reads, D-06) + `DATABASE_URL`/`DATABASE_URL_WORKER`/
    `AUDIT_GCS_BUCKET`, each with a resource-scoped `secretAccessor` to the runtime SA
    (drift-honest: no `*_version` resource, values seeded out-of-band per the runbook).
  - Two BUILT_IN `google_sql_user` roles — `app_user` + `worker_user` (password/asyncpg,
    `random_password`), with an IaC comment restricting `worker_user` to the `tribunal`
    schema ONLY (the actual GRANT is migration 0008, Plan 02).
- **Task 2 — runbook + deploy scripts + Cloud Build (`e15ab29`):**
  - `DEPLOY-RUNBOOK.md § Phase 13` — ordered operator steps 13.a–13.i: reuse the `nestor`
    Artifact Registry repo; create the six secrets + seed VALUES via the `--data-file=-`
    stdin idiom; create the audit bucket with `--enable-per-object-retention`; create the
    two BUILT_IN roles; build both images via Cloud Build; deploy + execute `tribunal-migrate`;
    deploy `tribunal-worker` then `tribunal-api`; a **CHECKPOINT** noting the E2E proof /
    verify_chain / concurrency / cost are Plan 04; and a FINAL, clearly-marked **post-proof
    teardown** of `project-cb01b861` (services + Cloud SQL + Artifact Registry), strictly
    sequenced after the proof gate. Carried the IaC-drift preamble + a Supabase-independence
    (never delete) note. Added 10 Phase-13 items to the Summary checklist.
  - `deploy-{api,worker}.sh` retargeted — `$GOOGLE_PROJECT` / `nestor` repo / `nestor-run` SA;
    worker `--max-instances=5` (D-08) while keeping `--min-instances=1 --no-cpu-throttling
    --timeout=3600 NESTOR_TRIBUNAL_UNCAPPED=1`; ZERO `project-cb01b861` literals; dropped the
    stale `.last-build.env` sourcing (image tag now via `IMAGE_TAG`).
  - `tribunal/cloudbuild.{api,worker}.yaml` — build+push each image from the `tribunal/`
    context via the respective Dockerfile (`-f`), `CLOUD_LOGGING_ONLY`, `1200s`.
  - `tribunal/cloudbuild.test.yaml` — `pytest nestor_pulse_sdk/tests/` against a real Postgres
    (testcontainers via the mounted host Docker socket), deps from the verbatim
    `requirements.txt` (T-13-SC — no new package selected); non-zero exit fails the build.

## How to Verify

Static (grep/file-existence — dev box has no Python/Docker/terraform):

```bash
# Task 1 IaC
grep -q "tribunal-worker" infra/main.tf && grep -q "tribunal-api" infra/main.tf \
 && grep -q "tribunal-migrate" infra/main.tf && grep -qi "Unlocked" infra/main.tf \
 && grep -q "DATABASE_URL_WORKER" infra/main.tf && grep -q "worker_user" infra/main.tf \
 && grep -q "min_instance_count = 1" infra/main.tf && grep -q "cpu_idle" infra/main.tf && echo IAC_OK
grep -q "enable_object_retention = true" infra/main.tf          # per-object retention ON
grep -c "retention_policy" infra/main.tf                        # only comment lines — NO Bucket Lock block

# Task 2 runbook + scripts + Cloud Build
grep -q "Phase 13" infra/DEPLOY-RUNBOOK.md && grep -qi "teardown" infra/DEPLOY-RUNBOOK.md \
 && grep -q "project-cb01b861" infra/DEPLOY-RUNBOOK.md && grep -q "tribunal-migrate" infra/DEPLOY-RUNBOOK.md \
 && test -f tribunal/cloudbuild.api.yaml && test -f tribunal/cloudbuild.worker.yaml \
 && test -f tribunal/cloudbuild.test.yaml && grep -q "tribunal-worker" tribunal/cloudbuild.worker.yaml \
 && [ "$(grep -c 'project-cb01b861' tribunal/infrastructure/cloud-run/deploy-worker.sh)" -eq 0 ] \
 && grep -q "max-instances=5" tribunal/infrastructure/cloud-run/deploy-worker.sh && echo RUNBOOK_OK

# Secret hygiene: only the stdin idiom, no committed values
grep -rniE 'sk-[a-z0-9]{20}|AIza[0-9A-Za-z_-]{20}' tribunal/infrastructure/cloud-run/*.sh \
  infra/DEPLOY-RUNBOOK.md tribunal/cloudbuild.*.yaml || echo "no hardcoded secret values"
```

Both `IAC_OK` and `RUNBOOK_OK` print; `retention_policy` appears only in comment lines
(no Bucket Lock resource block); no secret value is committed anywhere.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `api/Dockerfile` did not copy `nestor_pulse/` — boot-time ImportError**
- **Found during:** Task 2 (authoring the Cloud Build context; cross-checking the 13-01
  SUMMARY deviation #1 against the copied Dockerfiles).
- **Issue:** The copied `tribunal/infrastructure/cloud-run/api/Dockerfile` carried the old
  standalone comment "nestor_pulse/ is NOT copied" and only `COPY nestor_pulse_sdk`. But
  `nestor_pulse_sdk/tools/claude_adapter.py` does a MODULE-LEVEL
  `from nestor_pulse.tools.claude_deep_researcher import ...`, and that adapter is on the API's
  live boot path (research_division → degraded_parallel → claude_adapter). Building the API
  image per that Dockerfile would ImportError at boot when the deep-research division loads —
  exactly the cross-dep 13-01 copied `claude_deep_researcher.py` to satisfy. (The worker
  Dockerfile already copied `nestor_pulse/`; only the api Dockerfile was wrong.)
- **Fix:** Added `COPY nestor_pulse ./nestor_pulse` to the api Dockerfile and rewrote the
  header note to explain the boot dep (the copied `nestor_pulse/` leaf carries no ADK modules,
  so it drags in nothing extra). Both Cloud Build configs run from the `tribunal/` context so
  `nestor_pulse/` is present. The § Phase 13 runbook (Step 13.e) also documents this.
- **Files modified:** `tribunal/infrastructure/cloud-run/api/Dockerfile`
- **Commit:** `e15ab29`

### Notes on plan-latitude decisions (not deviations)

- **Test gate uses the Docker socket, not a fixed DATABASE_URL.** The plan's PATTERNS §test
  described mirroring this repo's fixed-`DATABASE_URL` gate, but the Tribunal suite is
  testcontainers-based (`conftest.py::postgres_container`) and does NOT honor a plain
  `DATABASE_URL` (only `test_rls_isolation.py` reads one). Modifying the byte-identical conftest
  would break the ENGINE-04 integrity carry, so the gate instead mounts the host Docker socket
  (`TESTCONTAINERS_RYUK_DISABLED=true`) so testcontainers starts its own Postgres — the copied
  suite runs unmodified. Deps install from the verbatim `requirements.txt` (T-13-SC).
- **`AUDIT_GCS_BUCKET` modeled as a Secret Manager secret** (not a plain env) purely for
  injection uniformity with the DB/provider secrets; its value is the non-secret bucket name.

## Threat Flags

None new. The plan's `<threat_model>` dispositions are all satisfied by construction:
T-13-08 (no secret value committed — only `--data-file=-`), T-13-09 (worker_user restricted to
`tribunal` in IaC comment + deferred to 0008), T-13-10 (audit bucket 7y Unlocked created BEFORE
the proof gate, Step 13.c precedes the 13.h checkpoint), T-13-11 (teardown is the FINAL
post-proof step 13.i), T-13-12 (resource-scoped secretAccessor throughout), T-13-SC (no new
package — verbatim requirements.txt).

## Known Stubs

None. This plan is by-construction IaC + a runbook + deploy/build configs. Every resource is
the intended end-state; the "inert until applied" nature is the drift-honest posture the whole
project uses (documented in the runbook + STATE.md), NOT a stub. The live apply is Plan 04.

## Self-Check: PASSED

All 3 created files verified present; all 3 commits (`821e6c4`, `e15ab29`, + this metadata
commit) recorded; `IAC_OK` and `RUNBOOK_OK` both print; no plan-02-owned files touched; no
committed secret values; working tree clean.
