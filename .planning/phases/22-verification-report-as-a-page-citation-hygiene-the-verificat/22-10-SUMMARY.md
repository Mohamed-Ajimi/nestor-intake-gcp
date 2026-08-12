---
phase: 22-verification-report-as-a-page-citation-hygiene-the-verificat
plan: 10
subsystem: deploy
tags: [deploy, cloud-run, cloud-build, runbook, digest-proof, no-run]
requires:
  - "22-01..22-09 merged at ed20031"
  - "operator authorization for the deploy (given)"
provides:
  - "tribunal-api-00020-rjw @sha256:0b67b926… live at 100% traffic"
  - "nestor-frontend-00030-wvh @sha256:1c47f975… live at 100% traffic"
  - "infra/DEPLOY-RUNBOOK.md § Phase 22 — derived surface, ordered deploy, verbatim proofs"
  - "DEF-22-06 — the write-side source-identity fix named with its alembic 0019 money trap"
affects:
  - "infra/DEPLOY-RUNBOOK.md"
  - ".planning/phases/22-…/deferred-items.md"
tech-stack:
  added: []
  patterns:
    - "deploy surface DERIVED by import graph, not inherited from a prior phase's ruling"
    - "gcloud identity pinned per-command; the two identity readers deliberately left unpinned"
    - "build status read via `builds describe`, never through a pipe"
    - "proof = revision `status.imageDigest`, never `containers[0].image`"
key-files:
  created:
    - ".planning/phases/22-…/22-10-SUMMARY.md"
  modified:
    - "infra/DEPLOY-RUNBOOK.md"
    - ".planning/phases/22-…/deferred-items.md"
decisions:
  - "Deployed set = {tribunal-api, nestor-frontend}. tribunal-worker and nestor-api CONFIRM-ONLY — derived, and the derivation agreed with the plan's measured fact 3."
  - "Built tribunal-api from cloudbuild.api.yaml, NOT build-and-push.sh (stale registry path, reports SUCCESS anyway)."
  - "Frontend's four non-_IMAGE substitutions recovered verbatim from build cdafc26e rather than retyped."
  - "No DB credential available, so alembic heads proven by migrate-job execution history instead of the two SQL reads."
metrics:
  duration: "~75 min"
  completed: "2026-08-12"
  tasks: "3/3"
  commits: 3
---

# Phase 22 Plan 10: Deploy — verification report page + citation hygiene, live and digest-proven

Phase 22's read-path and UI changes are live on `tribunal-api` and `nestor-frontend` at the shared tag
`20260812-100556`, both proven by a revision `imageDigest` that differs from the pre-deploy one, with
the engine fast gate green at 45 files and **zero research runs triggered**.

## What was deployed

**SHARED_TAG: `20260812-100556`**

| Service | Disposition | Revision | `status.imageDigest` | Traffic |
|---|---|---|---|---|
| `tribunal-api` | **DEPLOYED** | `tribunal-api-00020-rjw` | `…/nestor/tribunal-api@sha256:0b67b926ef63d2b35b903e7c92ebf7d755ff8f7875f880a9c76b472905705005` | 100% |
| `nestor-frontend` | **DEPLOYED** | `nestor-frontend-00030-wvh` | `…/nestor/frontend@sha256:1c47f975afaf8225f1000f1dbddc00af35b9a8a43cbb4a518738c452b2562a08` | 100% |
| `tribunal-worker` | CONFIRM-ONLY | `tribunal-worker-00007-l8x` | *(untouched)* | 100% |
| `nestor-api` | CONFIRM-ONLY | `nestor-api-00045-hdw` | *(untouched)* | 100% |

**Both digests CHANGED — which is the only thing that proves the deploy landed:**

| Service | PRE-deploy | POST-deploy |
|---|---|---|
| `tribunal-api` | `sha256:3a8f2dbb0798…0b3ade4b` | `sha256:0b67b926ef63…05705005` |
| `nestor-frontend` | `sha256:798a73a29af2…f97bf0a6` | `sha256:1c47f975afaf…b2562a08` |

**Deployed set = the derived surface EXACTLY.** Nothing extra, nothing missing.

Secret bindings, by name only: `ANTHROPIC_API_KEY` + `SERPAPI_API_KEY` still bound on **both**
`tribunal-api` and `tribunal-worker`.

## The derived surface — and what the derivation added over the plan's expectation

`$BASE` = `9afdf2d`, `HEAD` = `ed20031`. **18 source files** (plus 15 under `.planning/`).

| Path group | Files | Ships in | Rule applied |
|---|---|---|---|
| `frontend/src/**` (9 non-test sources incl. the renamed `admin.pulse.runs.$runId.index.tsx`, the new `…verification.tsx`, and `routeTree.gen.ts`) | 9 | `nestor-frontend` — DEPLOY | bundled into the frontend image |
| `frontend/src/locales/{en,fr,nl}/intake.json` | 3 | `nestor-frontend` — DEPLOY | imported by the i18n layer and bundled |
| `frontend/src/lib/research/citationIndex.test.ts` | 1 | *(nothing)* | `.test.ts` is not imported by the app |
| `citations/dedupe.py` (new), `verification/report.py`, `runs/schemas.py` | 3 | `tribunal-api` — DEPLOY | the image that RUNS the changed code |
| `tribunal/nestor_pulse_sdk/tests/test_citation_dedupe.py` | 1 | *(nothing)* | `tests/` ships nothing |
| `tribunal/cloudbuild.test-engine.yaml` | 1 | *(nothing)* | gate config, not an image |
| `backend/**` | **0** | `nestor-api` — CONFIRM-ONLY | not in the diff at all |
| — | 0 | `tribunal-worker` — CONFIRM-ONLY | executes none of the changed code |

**Measured group list: exactly `.planning`, `frontend`, `tribunal` — no `backend`.**
`git diff --stat 9afdf2d..HEAD -- backend/` produced NO OUTPUT; the empty diff is the evidence.
`git diff --name-only 9afdf2d..HEAD -- tribunal/nestor_pulse_sdk/alembic/` produced NO OUTPUT → no
migration.

### The derivation AGREED with the plan's measured fact 3 — and the agreement was re-earned

The plan warned that on 2026-08-06 a standing note said two services, the diff said three, and
skipping `nestor-api` would have left the fix inert. Here the derivation and the expectation matched.
**What the derivation added that the plan did not have is the mechanism**, obtained by grepping
non-test importers rather than by inheriting the conclusion:

- `verification/report.py`'s only non-test caller is `runs/api.py:996`, invoked at `runs/api.py:1002`
  inside the `@router.get("/{run_id}/verification")` handler (`runs/api.py:968`). `runs/api.py` is
  mounted by `nestor_pulse_sdk.server:app` — the **API image's** entrypoint.
- `citations/dedupe.py`'s only non-test importer is `verification/report.py:41`.
- `runs/schemas.py` is imported by `runs/api.py:26`; the change is one additive field
  (`also_claim_ids` on `VerificationCitation`).
- `worker.py`'s imports are `db.base`, `db.rls`, `pipeline.tribunal.reliability` — the graph **never
  reaches** any changed module, and the worker serves no HTTP.

**⚠ The false positive this catches:** `pipeline.py:4570` assigns a local dict literally named
`verification_report`. A substring grep reads that as a worker dependency on
`nestor_pulse_sdk.verification.report`. It is not — `pipeline.py` never imports that module. Had the
surface been derived by substring rather than by import, `tribunal-worker` would have been added to
the surface and redeployed — and the worker is the **money-risk** service, because its loop claims
before it sleeps.

**And unlike Phase 21, there was no "build it anyway" pressure.** Phase 21 deployed `tribunal-api`
alongside the worker because `build-and-push.sh` produced both images in one invocation, so leaving
one behind created drift. This deploy built **only** the API image from `cloudbuild.api.yaml`, so no
worker image existed to leave behind. CONFIRM-ONLY is both correct and strictly safer.

## Gates

### Engine fast gate — build read by id, never through a pipe

| Item | Value |
|---|---|
| build id | `18cee1fb-597d-4660-a831-5cc71c66ae7d` |
| status, from `gcloud builds describe … --format='value(status)'` | **SUCCESS** |
| collection line, verbatim | `collecting: 45 of 45 expected files` |
| pytest summary, verbatim | `====================== 1945 passed, 14 skipped in 22.43s =======================` |
| FAILURES | **0** (`grep -c "^FAILED\|=== FAILURES ==="` → 0) |
| errors | **0** |

**The `EXPECTED_FILES` assertion fired and matched at 45.** The config pre-lists paths through
`ls … || true`, so a missing or misnamed file is silently skipped and the build still exits 0 — the
`COLLECTED -ne EXPECTED_FILES` check at `cloudbuild.test-engine.yaml:538` is the only detector, and
the printed line at `:563` is the proof it agreed.

**Pass-count mechanism, stated rather than noted:** Phase 21's engine gate at 44 files measured
1909 passed / 13 skipped / **6 errors** — but that was a *local Windows* run. This is the first Cloud
Build reading of the 45-file list: **1945 passed / 14 skipped / 0 errors** on Linux. The 6 errors are
absent because they are the Windows `PYTEST_CURRENT_TEST` 32767-char ceiling (DEF-22-02), which Linux
does not have. **DEF-22-05's five order-dependent failures did not appear either** — consistent with
them being a local collection-order artifact.

### The four frontend gates

| Gate | Result |
|---|---|
| `npx tsc --noEmit` | **exit 0**, no output |
| `npx vitest run` | **7 files / 77 tests passed, 0 failing** |
| `node scripts/i18n-audit.mjs` | `RESULT: PASS — A/B/C clean (107 CHECK D advisories)`, **exit 0** |
| `npm run build` | **exit 0** (`✓ built in 1m 2s`) |

`npm ci` was used, never `npm install`. **No lint result was recorded as a gate** (DEF-21-01).

**Deviation on the vitest number, with the mechanism.** The plan's measured fact 9 predicted **61/61**.
The actual is **77**. That is not a discrepancy to explain away: fact 9 was measured *at the phase base
commit*, and plan 22-01 added `frontend/src/lib/research/citationIndex.test.ts` with **16 tests**.
61 + 16 = 77, exactly. Had I written the criterion as "expect 61" and driven to it, the correct
outcome would have read as a failure.

**The 107 CHECK D advisories are expected and are not a count to drive to zero.** Per DEF-22-03 the
audit's `RE_SINGLE`/`RE_TWO` match neither `t("key", { … })`, so all 102 interpolated sites in
`frontend/src` are invisible to CHECK A/B/C — green here is necessary, not sufficient.

## NO RESEARCH RUN WAS TRIGGERED

| Reading | Newest write | Prefixes | Objects |
|---|---|---|---|
| BEFORE the deploy | `2026-08-05T19:21:31Z` | 9 | 2050 |
| AFTER the deploy | `2026-08-05T19:21:31Z` | 9 | 2050 |

**All three figures identical. Nothing claimed and nothing ran.**

⚠ **Bucket-identity check, because reading the wrong bucket would have made the comparison
meaningless.** Two audit buckets exist. `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/` has **9**
run prefixes and matches the Phase 21 record — it is the live surface.
`gs://nestor-audit-prod/` has **22** prefixes and a newest write of `2026-06-15T16:01:34Z` — legacy.

**No migration ran either.** Latest `tribunal-migrate` execution `tribunal-migrate-gqmtk` at
`2026-08-05T09:39:54Z`; latest `nestor-migrate` execution `nestor-migrate-gl496` at
`2026-07-28T08:12:43Z`. Neither on 2026-08-12. Heads stay TRIBUNAL **0018** / INTAKE **0013**.

## Identity — the trap fired again

`gcloud config list` reported account **`tools@epicimpact.be`** at session start — the **wrong**
identity, with the **right** project, which is exactly what makes it survivable-looking. Four accounts
are configured on this machine (`moeajimi@gmail.com`, `mohamed.ajimi@agiliz.com`, `tools@dotto.be`,
`tools@epicimpact.be`).

**Every gcloud command in this plan pinned `--account=tools@dotto.be
--project=project-cb01b861-cb4a-438d-b9a` explicitly**, and none relied on the persisted config. The
config was deliberately **not** corrected with `gcloud config set`, since it has reverted mid-session
before and the flags are what actually hold.

**The agent's gcloud was NOT read-only.** The plan's Task 2 assumed `builds submit` and `run deploy`
were classifier-blocked and made the task a `checkpoint:human-action`. With the operator's explicit
authorization in hand, both write families executed without interference — three build submits and two
`run deploy` calls all succeeded. Recorded because the read-only assumption is now measurably stale for
these two verbs.

## Deviations from Plan

### 1. [Rule 3 — blocking] Task 2 executed by the agent, not handed to the operator

- **Found during:** Task 2
- **Issue:** Task 2 is `checkpoint:human-action` on the premise that the agent's gcloud cannot write.
- **Resolution:** The team lead relayed the operator's explicit authorization for this deploy, so the
  writes were attempted rather than deferred. They all succeeded — see the build ids and revisions
  above. Nothing outside the derived surface was touched, and no run was triggered.
- **Numbers:** 3 build submits (all SUCCESS), 2 `run deploy` calls (both to services in the derived
  surface), 0 blocked commands, 0 runs triggered.

### 2. [Rule 2 — correctness] Two `gcloud` commands deliberately left unpinned, against the letter of a criterion

- **Found during:** Task 1
- **Issue:** Task 1's criterion says the section "carries `--account=tools@dotto.be` on every `gcloud`
  invocation it lists — a bare `gcloud` in the new section is a defect." Measured with
  `grep -cE '^ *gcloud '` over the section: **19 executable gcloud invocations, of which 17 pin both
  flags and 2 do not** — `gcloud config list` and `gcloud auth list` in § 2(a).
- **Why the criterion is wrong for exactly these two:** their entire job is to *reveal* the unpinned
  identity. Pinning `--account` onto `gcloud config list` prints back the flag you just typed and makes
  the drift undetectable; `gcloud auth list` enumerates all accounts, for which `--account` is
  meaningless. Satisfying the criterion literally would have **deleted the only detector of the trap
  the section exists to defend against** — the "make the grep go green by breaking correct content"
  failure this phase has guarded against repeatedly.
- **Resolution:** kept both bare and added an explicit ⭐ callout in § 2(a) stating why they are the
  only two unpinned commands and instructing future readers not to "fix" them.

### 3. [Rule 2 — correctness] Alembic heads proven by job history, not by the two SQL reads

- **Found during:** Task 3
- **Issue:** Task 3(d) asks for `SELECT version_num FROM …`. No DB credential was available.
- **Resolution:** substituted `gcloud run jobs executions list` on both migrate jobs, which is a
  **stronger** proof of the question actually asked ("did a migration run?") because it reads the
  execution history rather than the resulting state. Recorded in the runbook with the ⚠ note that a
  future reader with a DSN should still run the two SQL reads — job history proves nothing *ran*, not
  what the tables *say*.

### 4. Revision-name shape changed (cosmetic, recorded so it is not misread)

- **Found during:** Task 3
- **Issue:** pre-deploy names were date-shaped (`tribunal-api-20260810-193000-200954`) because Phase 21
  used the deploy scripts, which pass `--revision-suffix`. The hand-typed `gcloud run deploy` in this
  section does not, so Cloud Run auto-numbered: `tribunal-api-00020-rjw`, `nestor-frontend-00030-wvh`.
- **Why it matters:** a reader comparing **names** would think the wrong thing shipped. Digests are the
  proof, which is the point of § 5. Documented in the runbook with the one-flag fix
  (`--revision-suffix=${SHARED_TAG}`) for anyone who prefers date-shaped names.

### 5. `frontend/src/routeTree.gen.ts` CRLF artifact — restored, not committed

- **Found during:** Task 2, after `npm run build`
- **Issue:** the file shows as modified with a **completely empty diff** (`git diff --numstat` returns
  nothing) — a line-ending artifact of `core.autocrlf=true`.
- **Resolution:** `git checkout --` restored it; it was never staged. It still reads as ` M` in
  `git status`, which is expected and is not a pending change.

## Acceptance-criteria measurements

Baselines measured **before** the edit, both numbers stated as the plan required:

| Criterion | Before | After | Verdict |
|---|---|---|---|
| `grep -c "^## Phase 22" infra/DEPLOY-RUNBOOK.md` == 1 | 0 | **1** | PASS |
| `grep -c "git diff --name-only"` increased by ≥2 | 7 | **12** (+5) | PASS |
| `grep -c "status.imageDigest"` increased by ≥1 | 2 | **8** (+6) | PASS |
| `grep -c "cloudbuild.api.yaml"` ≥1 | 13 | **16** (3 in-section) | PASS |
| `grep -c "sha256:"` | 9 | **16** (13 are `@sha256:`) | PASS |
| section warns against `build-and-push.sh` | — | 2 in-section mentions, one a ⛔ ban | PASS |
| engine gate stated as **0 FAILURES**, not exit 0 | — | `ZERO FAILURES` ×1 + `IS NOT EXIT 0` ×1 | PASS |
| no `npm run lint` gate, no "zero advisories" | — | `grep -ci "zero advisories"` → **0**; lint present only as a ⛔ NOT-A-GATE ban | PASS |
| surface table names every service with deploy/CONFIRM-ONLY + rule | — | 4 services, each with a disposition and a rule | PASS |
| `grep -c "^## DEF-22-06 " deferred-items.md` == 1 (anchored, trailing space) | 0 | **1** | PASS |
| `grep -c "0019" deferred-items.md` ≥1 | 0 | **1** | PASS |
| `git diff --cached --name-only` lists both files | — | both listed | PASS |

⚠ **Anchor note:** the DEF id was checked as `^## DEF-22-06 ` **with the trailing space**, not
`^## DEF-22-1`-style prefix, because a prefix pattern like `^## DEF-22-0` matches five existing
entries and would read green while proving nothing. Pre-check confirmed DEF-22-06 was unclaimed
(ledger held 01–05, count 5); it now holds 01–06, count 6, no collision.

## What was NOT claimed, deliberately

- **No duplicate-collapse count, and no yield or reduction figure anywhere.** Banned by operator
  ruling. The dedupe is **DISPLAY-ONLY**: duplicate `source` rows are still created at INSERT and
  still count toward cost and corroboration. The runbook and DEF-22-06 both state this in those words.
- **No claim that the live alembic tables were read.** They were not; job history was.
- **No claim that DEF-22-05's five failures are fixed.** They simply did not appear in a Cloud Build
  run, which is consistent with their being a local collection-order artifact.

## Next action

**The operator UAT is
`.planning/phases/22-verification-report-as-a-page-citation-hygiene-the-verificat/22-UAT.md`. It runs
on RECORDED data and costs NOTHING** — no research run, no provider call, no ~$45.

Four known, ruled, out-of-scope items will be visible and must not be reported as Phase 22
regressions: **DEF-21-01** (lint red tree-wide), **DEF-21-03** (empty `coverage` stage summary),
**DEF-21-04** (`workshop` has no divider), **DEF-22-01** (`ResearchRunProgress`'s body unrendered but
compiled).

## Self-Check

**Files:**
- `infra/DEPLOY-RUNBOOK.md` — FOUND, `## Phase 22` present ×1
- `.planning/phases/22-…/deferred-items.md` — FOUND, `## DEF-22-06 ` present ×1
- `.planning/phases/22-…/22-10-SUMMARY.md` — this file

**Live services** (read with pinned identity, digest off the REVISION):
- `tribunal-api-00020-rjw` @ `sha256:0b67b926…` — FOUND, differs from pre-deploy `sha256:3a8f2dbb…`
- `nestor-frontend-00030-wvh` @ `sha256:1c47f975…` — FOUND, differs from pre-deploy `sha256:798a73a2…`
- `tribunal-worker-00007-l8x`, `nestor-api-00045-hdw` — FOUND, unchanged

**Builds** (status from `builds describe`, not a pipe): `18cee1fb…` SUCCESS, `0e8bb881…` SUCCESS,
`7327905f…` SUCCESS

**No run:** audit newest write `2026-08-05T19:21:31Z` before and after, 9 prefixes / 2050 objects both

## Self-Check: PASSED
