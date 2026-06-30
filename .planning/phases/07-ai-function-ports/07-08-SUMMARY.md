---
phase: 07-ai-function-ports
plan: 08
subsystem: infra + backend-tests
tags: [secret-manager, cloud-run, scope-guard, iac, deferred-deploy]
requires:
  - "infra/main.tf (Phase 2 base footprint: Cloud Run service, runtime SA, superadmin secret pattern)"
  - "backend/scripts/ci_no_run_research.sh (Phase 6 D-06 scope guard)"
provides:
  - "ANTHROPIC_API_KEY / OPENAI_API_KEY Secret Manager secrets + scoped secretAccessor + native Cloud Run env injection (D-07)"
  - "Cloud Run CPU always-allocated + min-instances=0 (D-01a)"
  - "infra/DEPLOY-RUNBOOK.md (manual/IaC-drift reconciliation for the AI-key surface)"
  - "backend/tests/test_scope_guard_ai.py (run-research unreachable from the AI seam — T-7-07)"
affects:
  - "infra/main.tf"
  - "infra/variables.tf"
  - "the live Cloud Run service config (once applied/reconciled)"
tech-stack:
  added: []
  patterns:
    - "Native Secret Manager env injection via value_source.secret_key_ref (vs runtime access_secret_version)"
    - "Drift-honest optional secret version (count = var == \"\" ? 0 : 1) so key values never enter committed state"
    - "Source-scan scope guard that strips docstrings/comments before matching (precision over bare token grep)"
key-files:
  created:
    - "infra/DEPLOY-RUNBOOK.md"
    - "backend/tests/test_scope_guard_ai.py"
  modified:
    - "infra/main.tf"
    - "infra/variables.tf"
decisions:
  - "AI keys injected NATIVELY (secret_key_ref) not runtime-fetched — no import-cycle reason to hand-roll, unlike the superadmin password (RESEARCH 'Don't Hand-Roll')"
  - "Secret VERSION value is seeded out-of-band by default (count-0 version resource); TF_VAR_*_api_key exists only for throwaway single-operator use — keeps keys out of committed state (T-7-05)"
  - "CPU always-allocated expressed as resources.cpu_idle=false (v2-API equivalent of the run.googleapis.com/cpu-throttling annotation); min_instance_count=0 keeps scale-to-zero"
  - "Scope guard strips docstrings/comments before scanning so a module's scope-ceiling prose never false-positives (mirrors ci_no_run_research.sh precision)"
metrics:
  duration: ~25 min
  tasks: 2
  files: 4
  completed: 2026-06-30
---

# Phase 7 Plan 08: AI-seam deferred-deploy infra + scope-guard regression Summary

Wired the deferred-deploy infrastructure for the Phase-7 AI ports — `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` as Secret-Manager-backed Cloud Run env vars (native `secret_key_ref` injection + resource-scoped `secretAccessor`), CPU always-allocated with scale-to-zero, a deploy runbook documenting the IaC-drift reality — and added a regression test proving `run-research`/Tribunal stays unreachable from the new AI seam.

## What was built

### Task 1 — `infra/main.tf` + `variables.tf` + `DEPLOY-RUNBOOK.md` (D-07 / D-01a)
- Two `google_secret_manager_secret` resources (`nestor-anthropic-api-key`, `nestor-openai-api-key`) mirroring the `app_superadmin_db_password` block, each with a resource-scoped `google_secret_manager_secret_iam_member` granting `roles/secretmanager.secretAccessor` to the runtime SA.
- Optional `google_secret_manager_secret_version` per key (`count = var.*_api_key == "" ? 0 : 1`) — by default **no** Terraform-managed version, so the key value is seeded out-of-band per the runbook and never enters committed state (T-7-05).
- Native env injection into the Cloud Run container via `env { value_source { secret_key_ref { secret = …, version = "latest" } } }` for both keys — no runtime `access_secret_version` call. Service `depends_on` extended with the two new secretAccessor grants.
- Cloud Run service: `template.scaling.min_instance_count = 0` (scale-to-zero, warm-pool OFF) with `max_instance_count = 4` retained (T-7-15 / D-04 connection math), and `template.containers.resources.cpu_idle = false` (CPU always-allocated — the v2 equivalent of `run.googleapis.com/cpu-throttling = "false"`, so the 90–120s LLM/Whisper background work finishes reliably).
- `variables.tf`: `anthropic_api_key_secret_id` / `openai_api_key_secret_id` (defaulted) + sensitive optional `anthropic_api_key` / `openai_api_key` (default `""`).
- `infra/DEPLOY-RUNBOOK.md`: documents (a) creating the secrets + secretAccessor as a **manual** step per the Phase-5 IaC-drift blocker (state never adopted), (b) rebuilding the image with the AI SDKs via Cloud Build (the image-only redeploy gap recurs), (c) setting CPU always-allocated + min-instances=0, (d) never logging/echoing the keys.

### Task 2 — `backend/tests/test_scope_guard_ai.py` (T-7-07 / INTAKE-05)
Three assertions: (1) the live FastAPI app mounts no route whose path carries a research/Tribunal/vendor token; (2) a source scan of `app/ai/**/*.py` + `app/api/ai_routes.py` finds no reachable `run_research(` call, `run-research` invoke/URL literal, `tribunal` import/attribute, nor any `SERPAPI_API_KEY` / `SEARCHAPI_API_KEY` / `APIFY_API_TOKEN` reference — docstrings + comments stripped first so scope-documenting prose never false-positives; skips clean until the AI seam lands; (3) re-runs `scripts/ci_no_run_research.sh` and asserts it still exits 0.

## Verification

| Gate | Result |
|------|--------|
| `grep -c 'ANTHROPIC_API_KEY\|OPENAI_API_KEY' infra/main.tf` | 6 (≥2) |
| `grep -q 'secretAccessor' infra/main.tf` | pass |
| `grep -q 'secret_key_ref' infra/main.tf` | pass |
| `grep -q 'cpu-throttling' infra/main.tf` (+ `cpu_idle=false`) | pass |
| `grep -q 'min_instance' infra/main.tf` | pass |
| `grep -ic 'drift\|manual' infra/DEPLOY-RUNBOOK.md` | 12 (≥1) |
| main.tf brace balance | 74 open / 74 close |
| `grep -q 'run-research\|run_research' tests/test_scope_guard_ai.py` | pass |
| `bash scripts/ci_no_run_research.sh` | exit 0 |

**Deferred (no local toolchain — author-by-construction per MEMORY `dev-machine-no-python-docker`):**
- `terraform fmt -check` / `terraform validate` — terraform not on PATH; HCL authored to convention, brace-balanced, mirrors the existing superadmin block 1:1. Run in CI / Cloud Shell.
- `pytest tests/test_scope_guard_ai.py` and `python -c "import ast; ast.parse(...)"` — no Python on the dev box. Test authored against the established sibling patterns (`test_no_run_research_route.py`, `test_scope_guard_run_research.py`); the bash CI guard it invokes was run live (exit 0).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `infra/variables.tf` (not in the plan's `files_modified`)**
- **Found during:** Task 1
- **Issue:** The superadmin-pw pattern this task mirrors drives the secret id through a Terraform variable (`var.superadmin_db_secret_id`); the optional key-value seed likewise needs sensitive variables. Hardcoding the secret ids / key values in `main.tf` would break the established convention and risk a committed key value.
- **Fix:** Added `anthropic_api_key_secret_id`, `openai_api_key_secret_id` (defaulted) and sensitive optional `anthropic_api_key`, `openai_api_key` (default `""`) to `variables.tf`, consistent with the existing `superadmin_db_secret_id` var.
- **Files modified:** `infra/variables.tf`
- **Commit:** f8feb52

## Threat surface

The threat register dispositions (T-7-05 info-disclosure, T-7-07 EoP, T-7-15 DoS) are all addressed and no NEW security-relevant surface beyond the plan's `<threat_model>` was introduced. No threat flags.

## Known Stubs

None. The optional secret-version `count = 0` default is an intentional drift-honest design (documented in `variables.tf` + the runbook), not a stub — the AI seam reads the keys from env at call time once the version is seeded out-of-band.

## Self-Check: PASSED

All created/modified files exist on disk; per-task commits f8feb52 (Task 1) and 953b1b3 (Task 2) present in git log.
