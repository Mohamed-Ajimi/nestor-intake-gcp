---
phase: 21-research-run-feed-completion-silent-post-research-stages-stu
plan: 08
subsystem: deploy
tags: [deploy, runbook, uat, cloud-run, cloud-build, gcp]

# Dependency graph
requires:
  - phase: 21-01..21-07
    provides: "the merged Phase 21 change set — 11 non-.planning files across frontend/ and tribunal/"
provides:
  - "infra/DEPLOY-RUNBOOK.md § Phase 21 — the DERIVED deploy surface, both gates, the ordered deploy, the digest read-backs"
  - "21-UAT.md — the recorded-run walkthrough, carrying DEF-21-02's six deferred steps as a hard obligation"
  - "Both Cloud Build gates GREEN on the merged tree, read by build id"
  - "The BEFORE digest baseline for all four services"
affects: [phase-21-close, the-next-measuring-run]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Deploy surface derived from the diff AND from the import graph, not from a standing note"
    - "A behaviourally-inert-but-byte-carrying service stated as an explicit operator choice"
    - "Build-time frontend config recovered from the LIVE bundle rather than hand-typed"

key-files:
  created:
    - .planning/phases/21-research-run-feed-completion-silent-post-research-stages-stu/21-UAT.md
  modified:
    - infra/DEPLOY-RUNBOOK.md

key-decisions:
  - "The derived surface AGREES with 21-CONTEXT D-02 — stated explicitly, because the agreement was re-earned by measurement and the same exercise DISAGREED with a standing note on 2026-08-06"
  - "tribunal-api deploys at the shared $SHA by operator ruling: built regardless, and skipping diverges two images from one tree"
  - "No migration — DERIVED from the diff by grep, recorded with the command, not assumed"
  - "Identity pinned PER INVOCATION (--account, or CLOUDSDK_CORE_ACCOUNT for the committed scripts, which take no flag) — making the known-wrong persisted config irrelevant instead of trying to keep it correct"
  - "build-and-push.sh is STALE and was NOT used: it targets repo nestor-pulse with names api/worker, while the live services and deploy-*.sh use nestor/tribunal-*. Built via cloudbuild.{api,worker}.yaml instead"
  - "TRIBUNAL_SERVICE_URL pinned explicitly rather than left to self-heal — it is the OIDC audience and --set-env-vars replaces the whole plain env"

requirements-completed: []

# Acceptance is CONDITIONAL — Task 3 (operator UAT) is untouched.
acceptance: conditional
open-checkpoint:
  task: 3
  type: checkpoint:human-verify
  status: "artifact created and committed; every verdict awaiting the operator. The deploy it depends on is now DONE."

# Metrics
duration: ~150min
completed: 2026-08-10 (Tasks 1 and 2 complete; Task 3 awaiting operator)
---

# Phase 21 Plan 08: Ship It and Prove It Shipped — Summary

**Phase 21 is LIVE at `20260810-193000`: both Cloud Build gates green by build id, the queue proven empty at three separate checkpoints, and all three services digest-proven to have MOVED while `nestor-api` is proven unchanged — deployed under an identity pinned per-invocation because the machine's gcloud config reverted to the wrong account twice mid-session.**

## Status: Tasks 1 and 2 COMPLETE · Task 3 awaiting the operator

| Task | Type | Status |
|---|---|---|
| 1 — Derive the surface, write the runbook | `auto` | ✅ **complete** — `508fe08` |
| 2 — Gates and deploy | `checkpoint:human-action` | ✅ **COMPLETE — deployed and digest-proven** |
| 3 — Operator UAT on recorded data | `checkpoint:human-verify` | ⏸ `21-UAT.md` staged; verdicts awaiting the operator |

## ✅ THE DEPLOY RECORD — `20260810-193000`

**Date / who:** 2026-08-10, account `tools@dotto.be`, project `project-cb01b861-cb4a-438d-b9a`,
executed by the GSD executor for plan 21-08 under operator authorisation given in session.

### Digest read-backs — BEFORE vs AFTER, per service

⛔ Every digest below is `status.imageDigest` **read off the revision**. `containers[0].image` is a
mutable tag and is quoted nowhere as proof (G-1). **No revision resolves to `:latest`.**

| Service | Revision (after) | BEFORE digest | AFTER digest | Moved? |
|---|---|---|---|---|
| **`nestor-frontend`** | `nestor-frontend-20260810-193000` | `frontend@sha256:541b2b52…943dea` | `frontend@sha256:798a73a2…7bf0a6` | ✅ **MOVED** |
| **`tribunal-api`** | `tribunal-api-20260810-193000-200954` | `tribunal-api@sha256:55978d5e…03f3bc` | `tribunal-api@sha256:3a8f2dbb…3ade4b` | ✅ **MOVED** |
| **`tribunal-worker`** | `tribunal-worker-00007-l8x` | `tribunal-worker@sha256:ae5722bc…b66b60` | `tribunal-worker@sha256:3067761a…d2edf3` | ✅ **MOVED** |
| **`nestor-api`** (CONFIRM-ONLY) | `nestor-api-00045-hdw` | `backend@sha256:a525c6e2…d4f06a` | `backend@sha256:a525c6e2…d4f06a` | ✅ **UNCHANGED — correct** |

All four at **100% traffic**. **The deployed set EQUALS the derived surface table** — three deployed,
`nestor-api` untouched: no extra, none missing.

⭐ **`nestor-frontend` was the load-bearing one** and it is proven three independent ways, because
it had been stale since **2026-07-28** (a week behind the fleet) and "looks the same" was the
expected wrong conclusion:
1. **digest moved** `541b2b52…` → `798a73a2…`;
2. **the served bundle changed** — `/assets/index-C6zuGW-Q.js` → `/assets/index-nc9cG-bB.js`;
3. **content differs byte-for-byte** — md5 `7f456335…` → `e99d9db3…` (the two happen to be the same
   *length*, which is exactly why size was not accepted as evidence).

**And the rebuild did not corrupt config:** the new bundle still carries the correct `_API_BASE_URL`,
`_FB_AUTH_DOMAIN`, `_FB_PROJECT_ID` and the public Firebase key (1 match each), with **zero Supabase
signatures** (D-08/D-09).

### Builds — all statuses read by build id, never from a tailed exit code

| Build | ID | Status |
|---|---|---|
| engine gate | `4dbf4097-a9dd-43f2-a4b4-037f398303a9` | **SUCCESS** |
| gates config | `8d68ee2f-7339-47da-afed-becb764887e9` | **SUCCESS** |
| frontend image | `cdafc26e-09ac-41b7-9087-57a55b465e00` | **SUCCESS** |
| `tribunal-api` image | `48d46bfa-bd28-4a01-b56c-a315e51fa1f0` | **SUCCESS** |
| `tribunal-worker` image | `c362d3b7-d36f-47db-80e4-0be716364cbd` | **SUCCESS** |

**Engine gate, read VERBATIM from the build log:**

```
collecting: 44 of 44 expected files
1911 passed, 14 skipped in 20.12s
```

**0 failures, 0 errors on Linux.** The count **rose** against the local prediction (1909 → 1911
passed, 13 → 14 skipped, **6 → 0 errors**), and the mechanism is stated rather than shrugged at:
the 6 local errors are the Windows-only `PYTEST_CURRENT_TEST` env-limit teardown failures, which
Linux does not hit; the ±1 collection delta is environment-gated tests (`DATABASE_URL not set`,
`backend/ not present in this checkout` — the gate submits only `tribunal/`).

### The ordered deploy, as executed

1. **`nestor-frontend`** — built with the four `--substitutions`, then deployed.
2. **`tribunal-api`** — `deploy-api.sh` at `IMAGE_TAG=20260810-193000`.
3. **`tribunal-worker` LAST** — `deploy-worker.sh` at `MIN_INSTANCES=0` (**shipped PAUSED**), then a
   **separate deliberate** `--min-instances=1`, per the runbook's ordering correction.
4. **`nestor-api`** — not touched.

### The queue canary — run THREE times, empty every time

| Checkpoint | Time (UTC) | Prefixes | Objects | Newest write |
|---|---|---|---|---|
| pre-deploy | 17:36 | 9 | 2050 | `2026-08-05T19:21:31Z` |
| **immediately pre-worker** | 18:11 | 9 | 2050 | `2026-08-05T19:21:31Z` |
| post-worker-deploy (boot) | 18:13 | 9 | 2050 | `2026-08-05T19:21:31Z` |
| post-unpause (polling) | 18:16 | 9 | 2050 | `2026-08-05T19:21:31Z` |

⭐ **The worker booted, and then ran unpaused at `minScale=1` for several minutes, and CLAIMED
NOTHING.** The correct observation is an idle worker, and that is what was observed.
**NO RESEARCH RUN WAS TRIGGERED** — the newest audit write after the deploy is **identical** to the
one recorded before it.

*Bucket note:* the live audit bucket is **`project-cb01b861-cb4a-438d-b9a-nestor-audit`** (9
prefixes, incl. `368ff3a0` / `7dcf51d5` / `d6bb3aae`). **`nestor-audit-prod` is a different, older
bucket with 22 prefixes** — using it would have produced a plausible reading that meant nothing.

### Worker env + secrets — READ BACK after the unpause, not asserted

```
NESTOR_ENV=prod
NESTOR_WORKER_POLL_INTERVAL=2.0
NESTOR_WORKER_STALE_MINUTES=60        ✅ 60, not 525600
NESTOR_TRIBUNAL_UNCAPPED=1            ✅ the only tunable
NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol
minScale=1                            ✅ always-on restored
```

- ✅ **`NESTOR_RUN_ABORTED_MARKER` ABSENT.**
- ⭐ **NO `NESTOR_TRIBUNAL_WORKSHOP_*` of any kind — recorded as a POSITIVE finding.** The Wave-4
  validated configuration **IS** the code defaults, so the coming measuring run will measure the
  configuration that was actually validated.
- **Secrets by NAME only, no value read:** `ANTHROPIC_API_KEY ← Nestor_Claude2`,
  `SERPAPI_API_KEY ← Nestor_SERP`, plus `Nestor_Gemini`, `Nestor_OpenAI`, `DATABASE_URL_WORKER`,
  `AUDIT_GCS_BUCKET`.
- ⚠️ **CONFIRMED as flagged: the ANTHROPIC binding is `Nestor_Claude2`, and the 15.8
  `Nestor_Claude_Temp` burner is NO LONGER IN FORCE.** Both deploy scripts print
  "REPOINTS it" when live and committed differ; **neither printed it**, so live already matched the
  committed default and this deploy repointed nothing. **Confirm `Nestor_Claude2` is topped up
  before spending on the run.**

### Migration: NONE — as derived

TRIBUNAL head stays **0018**, INTAKE head stays **0013**. No alembic path in the diff; no migrate
job was run.

## Task Commits

1. **Task 1 — derive the surface, write the runbook, stage the UAT** — `508fe08` (docs)
2. **Summary at the identity checkpoint** — `6fc90f9` (docs)
3. **Gates green, queue empty, BEFORE digests** — `41991c4` (docs)
4. **The deploy record** — this commit (docs)

## ⛔ Why the deploy did not run — the identity drifted a SECOND time, mid-session

The operator fixed the account between checkpoints. **I re-verified it myself and it was correct**,
then it **reverted on its own, roughly ten minutes later, without this agent touching it.**

| Time (UTC) | Command | Identity in force |
|---|---|---|
| 17:31 | `gcloud config get-value account` | ✅ `tools@dotto.be` |
| 17:33 | BEFORE digests, all 4 services | ✅ worked |
| 17:36 | queue canary, 2050 objects listed | ✅ worked |
| 17:37–17:39 | **both Cloud Build gates submitted and SUCCEEDED** | ✅ worked |
| ~17:40 | `gcloud builds describe` ×2 | ✅ worked |
| ~17:45 | `gcloud builds log` | ❌ **`PERMISSION_DENIED` … authenticated as `tools@epicimpact.be`** |

Diagnosis, so this is a finding and not a shrug:

- **It is not an env override.** `env | grep -i cloudsdk` shows only `CLOUDSDK_PYTHON`. No
  `CLOUDSDK_CORE_ACCOUNT`.
- **The persisted config itself was rewritten.** `gcloud config configurations list` now reports
  `default … tools@epicimpact.be`. Something on this machine ran an equivalent of
  `gcloud config set account` / `gcloud auth login` **while this plan was mid-flight**.

**This is the documented trap reproducing itself** — *"`auth login` silently picked the wrong
identity + project and overwrote a fix seconds later"* — except it overwrote the operator's OWN fix,
during a deploy window.

### Why this stops the deploy rather than being worked around

Per the standing rule (and this plan's own `T-21-08-01`) a wrong identity is a **STOP-and-report**
condition, so no `gcloud config set account` and no `gcloud auth login` was run.

**But the stronger reason is the shape of this particular deploy.** It is a **four-step ordered
sequence** — frontend, then `tribunal-api`, then `tribunal-worker` **last**. An identity that can
flip *between* steps does not fail cleanly: it deploys the frontend on new code, then denies the
worker. That is **T-21-08-03 (an inert deploy that reads as successful)** with the added damage of a
**divergent fleet**, and the worker — the one component whose staleness silently changes what the
$45 run measures — is exactly the one left behind. **The safe moment to stop is before step 1, and
that is where execution stopped.**

**Nothing is in a half-applied state.** No image was built, no service was deployed, no migration
exists to be half-run, and no research run was triggered.

## ✅ What DID complete — all of the pre-flight

### Both Cloud Build gates: GREEN, read by build id

| Gate | Build ID | Status | Duration |
|---|---|---|---|
| engine (`cloudbuild.test-engine.yaml`) | **`4dbf4097-a9dd-43f2-a4b4-037f398303a9`** | **SUCCESS** | 17:37:54 → 17:39:28Z |
| gates (`cloudbuild.test-gates.yaml`) | **`8d68ee2f-7339-47da-afed-becb764887e9`** | **SUCCESS** | 17:38:05 → 17:39:25Z |

**Read via `gcloud builds describe <id>`, never from a tailed pipeline's exit code.** Both submit
wrappers printed `exit 0` — which is exactly the value they would have printed on a FAILED build, so
it was ignored by construction.

> ⚠️ **`collecting: 44 of 44 expected files` was NOT read verbatim** — the identity flipped before
> `gcloud builds log` could run, and it returned `PERMISSION_DENIED`. Recorded as **NOT OBTAINED
> with its reason**, per the § 15.2.k precedent, rather than given a plausible line nobody read.
>
> ⭐ **However, SUCCESS ENTAILS IT, and this is a mechanism not a hope.** In
> `cloudbuild.test-engine.yaml:534-562`, the collection assertion runs **before** pytest and
> `exit 1`s on any mismatch; the `collecting:` line is printed **only after** it passes, and pytest
> runs **after that**. A build cannot reach SUCCESS with a collection count other than 44, nor with
> a failing test. **The green build is therefore proof the assertion held** — the literal string is
> what is missing, not the guarantee.

**Local pre-measurement of the same files at `2d16fdd`, for the record:** engine **1909 passed · 13
skipped · 6 errors · 0 FAILURES**; gates **190 passed · 2 skipped · 0 FAILURES**. The 6 errors are
the pre-existing **Windows-only** `PYTEST_CURRENT_TEST` env-limit failures in
`test_dispatch_pii.py` and `test_fact_list_parser.py`; **Linux CI does not hit them, and the green
Cloud Build confirms it.**

### The free queue canary: PASS — nothing running, nothing claimable

Bucket **`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit`** (identified as the live one by having
the 9 known prefixes incl. `368ff3a0`, `7dcf51d5`, `d6bb3aae`; the 22-prefix `nestor-audit-prod` is
a different, older bucket).

| Measure | Value |
|---|---|
| run prefixes | **9** — unchanged from the recorded baseline |
| objects listed | 2050 |
| **newest write anywhere** | **`2026-08-05T19:21:31Z`** — **exactly** the recorded baseline |

**Nothing has claimed anything.** The always-on worker polls every 2s at `minScale=1`, so a
claimable row would already be writing blobs. This also re-confirms, independently, that **the code
deployed at `20260806-175613` has still never executed.**

### BEFORE digests — the baseline for the read-back

All four digest-pinned; **none resolves to `:latest`**.

| Service | Revision (before) | Digest (before) |
|---|---|---|
| `nestor-frontend` | `nestor-frontend-00028-q52` | `frontend@sha256:541b2b52…943dea` |
| `tribunal-api` | `tribunal-api-20260806-175613-180706` | `tribunal-api@sha256:55978d5e…03f3bc` |
| `tribunal-worker` | `tribunal-worker-20260806-175613-180925` | `tribunal-worker@sha256:ae5722bc…b66b60` |
| `nestor-api` **(CONFIRM-ONLY)** | `nestor-api-00045-hdw` | `backend@sha256:a525c6e2…d4f06a` |

⭐ **The orchestrator's staleness observation is CONFIRMED and it matters:** `nestor-frontend` was
last deployed **2026-07-28**, the rest on **2026-08-06**. Its live image tag is
`frontend:20260728-094409`. **If the post-deploy frontend digest does not move off
`sha256:541b2b52…`, the deploy silently no-op'd** — with a fleet this stale, "it looks the same" is
the expected wrong conclusion, so the before/after digest is the only honest test.

### The worker's plain env — READ BACK, not asserted

```
NESTOR_ENV=prod
NESTOR_WORKER_POLL_INTERVAL=2.0
NESTOR_WORKER_STALE_MINUTES=60          ✅ 60, not 525600
NESTOR_TRIBUNAL_UNCAPPED=1              ✅ the only tunable in the committed list
NESTOR_OPENAI_DR_MODEL=gpt-5.6-sol
```

- ✅ **NO `NESTOR_RUN_ABORTED_MARKER`** — absent, as expected.
- ⭐ **NO `NESTOR_TRIBUNAL_WORKSHOP_*` of any kind — recorded as a POSITIVE finding.** The Wave-4
  validated configuration **IS** the code defaults, so the next measuring run will measure the
  configuration that was actually validated.
- Secrets **by name only**: `ANTHROPIC_API_KEY → Nestor_Claude2`, `SERPAPI_API_KEY → Nestor_SERP`,
  plus `Nestor_Gemini`, `Nestor_OpenAI`, `DATABASE_URL_WORKER`, `AUDIT_GCS_BUCKET`. **No value was
  read.** Note the ANTHROPIC binding is `Nestor_Claude2`, i.e. the 15.8 `Nestor_Claude_Temp` burner
  is **no longer in force** — confirm that is intended before spending on the run.
- The worker's `containers[0].image` is `tribunal-worker:20260806-175613` — **a mutable tag, quoted
  here only to show it is NOT what the digest table above relies on (G-1).**

### Frontend build config — recovered from the LIVE bundle, not hand-typed

The runbook deliberately records these as placeholders, and mistyping one **breaks the live
frontend**. Rather than retype them, all four were extracted from the currently-deployed bundle
(`/assets/index-C6zuGW-Q.js`, 808 KB), which guarantees the rebuild reproduces live config exactly:

| Substitution | Source |
|---|---|
| `_API_BASE_URL` | `https://nestor-api-1055853212188.europe-west1.run.app` — inlined in the live bundle |
| `_FB_AUTH_DOMAIN` | `project-cb01b861-cb4a-438d-b9a.firebaseapp.com` |
| `_FB_PROJECT_ID` | `project-cb01b861-cb4a-438d-b9a` |
| `_FB_API_KEY` | the public Firebase web key, recovered verbatim from the live bundle — **not written into this file**, following the runbook's own `<public firebase web apiKey>` convention |

## Task Commits

1. **Task 1 — derive the surface, write the runbook, stage the UAT** — `508fe08` (docs)
2. **Summary + continuation evidence** — this commit (docs)

## Deviations from Plan

### 1. [Rule 3 — Blocking, auto-fixed] The stale-base trap fired — 28th consecutive time

Worktree forked at **`a3a0c96`**, **844 commits behind** `2d16fdd`. `git rev-list --count` would
have read **green**; only `git merge-base` caught it. Corrected with the sanctioned
`git reset --hard`, then **all six positive-presence sentinels re-run and passed** — once before any
edit, and **again before the gates were submitted**. For a plan that submits Cloud Builds a stale
tree does not fail: it **builds the wrong source and returns a confidently green result.**

### 2. [Rule 3 — Blocking, ESCALATED twice, then structurally solved] Wrong gcloud identity

First occurrence blocked the original checkpoint; the operator fixed it. **It then reverted
mid-session** (timeline above) and blocked a second time. Never self-corrected, per the standing
rule.

**The resolution was not "set it correctly again" — it was to make the config irrelevant.** By
operator ruling the identity is now **pinned per invocation**:

- `--account=tools@dotto.be` on every direct `gcloud` call — **visible in the transcript**, so each
  command carries its own proof of identity rather than depending on ambient state;
- `CLOUDSDK_CORE_ACCOUNT=tools@dotto.be` for the **committed deploy scripts**, which take no
  `--account` flag. ⚠️ **This mattered:** `build-and-push.sh`, `deploy-api.sh` and
  `deploy-worker.sh` all call bare `gcloud`, so without the env var they would have inherited the
  known-wrong config **mid-deploy** — exactly the half-deployed-fleet failure the earlier stop was
  protecting against.

**Verified live:** the persisted config still read `tools@epicimpact.be` throughout, while every
pinned command ran as `tools@dotto.be`. The failure mode is now structurally impossible rather than
merely unlikely.

### 2b. ⭐ [Rule 1 — Bug caught before it shipped] `build-and-push.sh` is STALE and builds to the WRONG registry repo

- **Found during:** Task 2, immediately after running it — by reading the image URLs it printed
  instead of accepting the `SUCCESS`.
- **Issue:** the script builds
  `…/nestor-pulse/api:<sha>` and `…/nestor-pulse/worker:<sha>`, but **the live services and both
  `deploy-*.sh` scripts use `…/nestor/tribunal-api` and `…/nestor/tribunal-worker`** (`REPO=nestor`,
  image name `tribunal-*`). It is the pre-Phase-13-re-home build path; the deploy scripts were
  retargeted and it was not. It also tags with the git SHA (`41991c42`), not the shared deploy tag.
- **Consequence had it been trusted:** `deploy-worker.sh` would have looked for
  `nestor/tribunal-worker:41991c42`, which **does not exist** — a failed deploy at best, and at
  worst a silent resolve to a stale image. This is the "inert deploy that reads as successful"
  class (T-21-08-03).
- **Fix:** built via the **correct** committed configs instead —
  `tribunal/cloudbuild.api.yaml` and `tribunal/cloudbuild.worker.yaml` with
  `_IMAGE=…/nestor/tribunal-{api,worker}:20260810-193000`, which is the invocation those files
  document in their own headers.
- **Housekeeping:** the stale `tribunal/infrastructure/cloud-run/.last-build.env` it generated
  (pointing at the wrong repo) was removed with a **file-scoped `rm`** — never `git clean` — because
  leaving it is a trap for the next reader. Tree confirmed clean afterwards.
- **NOT fixed here:** `build-and-push.sh` itself is left untouched — repairing it is out of this
  plan's scope boundary. **Logged for follow-up.**

### 2c. [Rule 2 — Missing safeguard added] `TRIBUNAL_SERVICE_URL` pinned instead of self-healed

`deploy-api.sh` self-heals this value from `status.url`, and `--set-env-vars` **replaces the entire
plain env** (WR-01). The variable is the **OIDC audience** the seam verifies its caller token
against, so a silent change fails the seam **closed**. The live value is the *legacy*
`https://tribunal-api-ybkr7metoq-ew.a.run.app` while the service also answers on a newer
`-1055853212188.europe-west1.run.app` URL. **Measured first:** `status.url` returns the legacy form,
so self-heal would have been safe — but it was **exported explicitly anyway**, converting a
dependency on a lucky match into a stated value.

### 3. [Rule 1 — Unsatisfiable acceptance criterion] "`npm install` does not appear"

Task 1's criteria require `npm install` to be **absent** from the section, while Task 1's own action
text requires writing **"`npm ci`, NEVER `npm install`"** and the measured facts require recording
that it caused a production break. **Both cannot hold literally** — the fifth such collision in this
phase, and the same class as 21-02's Deviation 3. **Resolved toward the criterion's evident
purpose** ("the section must never INSTRUCT `npm install`"): both occurrences are **prohibitions**,
verified by reading every match. Reported rather than silently resolved.

### 4. [Obligation injected at execution — absent from the plan file] DEF-21-02's six UAT steps

21-08's plan predates the ruling that deferred 21-02's Task 3 here. **Discharged:** all six steps
are in `21-UAT.md` as B1…B6, with **step 5's not-a-blocker caveat** and **step 6's
absence-is-correct semantics** preserved verbatim and machine-verified. DEF-21-01/03/04 are named
there as known and out of scope so the walkthrough cannot misreport them.

### 5. [Out of scope — logged, NOT fixed] `npm run lint` red tree-wide

**DEF-21-01, operator ruling.** Verified per-file instead: **0 non-prettier violations** across the
four changed sources (1155 prettier messages, all CRLF checkout noise). **No `prettier --write` was
run.**

**Total deviations:** 5 — 1 blocking auto-fixed, 1 blocking correctly escalated (twice), 1
criteria-collision resolved toward purpose, 1 injected obligation discharged, 1 out-of-scope item
honoured.

## Issues Encountered

- ⭐ **A locally-green gate that ran ZERO tests while reporting exit 0.** The first `WANTED`
  extraction kept the literal `WANTED="` prefix; pytest printed *"no tests ran in 0.00s"* and the
  wrapper still printed **exit 0**. Caught by reading the output **text**, not the exit code — the
  same discipline later applied to `gcloud builds submit`, whose wrapper also printed `exit 0`. This
  is the phase's own lesson reproducing inside the tooling built to check it.
- **`gcloud builds log` returned `PERMISSION_DENIED`** — the identity flip, and the reason the
  `collecting:` line is recorded as NOT OBTAINED.
- **Two audit buckets exist** and only one is live. `nestor-audit-prod` has 22 prefixes;
  `project-cb01b861-…-nestor-audit` has the **9** that match the record. Using the wrong one would
  have produced a canary reading that looked plausible and meant nothing.
- **`.planning/` is gitignored** — both `21-UAT.md` and this SUMMARY were invisible to
  `git status` and needed `git add -f`.

## Threat Flags

None. No route, verb, parameter, dependency or secret added. The only install was `npm ci` from the
**committed** lockfile (868 packages, all pre-pinned), with `git status` showing no manifest change.
T-21-08-SC satisfied by construction. The public Firebase web key read from the live bundle is a
public project identifier, not a secret, and is deliberately not recorded here.

## Known Stubs

**`21-UAT.md` is deliberately unfilled** — every verdict reads *"(awaiting operator)"*. That is its
intended pre-UAT state: **no verdict may be filled from inference.**

## Self-Check: PASSED

- `infra/DEPLOY-RUNBOOK.md` — FOUND, `grep -c "^## Phase 21"` = **1** (line 4708)
- `21-UAT.md` — FOUND, tracked, committed in `508fe08`
- Commits `508fe08`, `6fc90f9`, `41991c4` — all FOUND in `git log`
- All five build ids — **SUCCESS**, each read by `gcloud builds describe <id>`
- All four services — revision + `status.imageDigest` read back; three MOVED, `nestor-api` unchanged
- Working tree **clean**; no deletions of tracked files in any commit
- `STATE.md` / `ROADMAP.md` — **NOT modified**

## Deferred / follow-up

- ⛔ **`build-and-push.sh` is stale and will mislead the next person** — it builds to
  `nestor-pulse/{api,worker}` while everything live uses `nestor/tribunal-{api,worker}`. Not fixed
  here (out of scope). **Either retarget it to match `deploy-*.sh`, or delete it in favour of
  `cloudbuild.{api,worker}.yaml`.**
- ⛔ **The machine's gcloud config keeps reverting to `tools@epicimpact.be`.** Pinning per
  invocation neutralised it for this plan, but the underlying writer is still unidentified and will
  bite an unpinned command later.
- **DEF-21-01** (`npm run lint` red tree-wide) — unchanged, still deferred by operator ruling.
- **DEF-21-03** / **DEF-21-04** — unchanged, out of scope, named in `21-UAT.md` so the walkthrough
  cannot misreport them.

## What happens next

1. **Task 3 — the operator walks the run page and fills `21-UAT.md`.** It is staged with one section
   per success criterion, the two regression checks, and **DEF-21-02's six deferred steps as
   B1–B6** (step 5 not-a-blocker; step 6 absence-is-correct). **Free, read-only, on recorded data.**
   ⚠️ **SC1 is `NOT-OBSERVABLE` on a pre-deploy recorded run by construction** — those runs have no
   rows for the eight stages. Its real proof is 21-06's capstone test.
2. **Then the ~$45 measuring run — the operator's to start, and NOT part of this plan.**
   ⛔ **It is a NEW BASELINE, not a comparison against `368ff3a0`:** `260806-lvt` changed the
   report's shape and `260806-o96` changed which claims reach paid verification. One run now
   validates this feed **and** the three changes deployed at `20260806-175613` that had never
   executed — which is exactly what D-01 sequenced this phase to achieve.
3. **Before spending: confirm `Nestor_Claude2` is topped up** (the 15.8 burner is not in force).

---
*Phase: 21-research-run-feed-completion-silent-post-research-stages-stu*
*Plan 08 — Tasks 1 and 2 COMPLETE; Phase 21 is LIVE at `20260810-193000`, digest-proven*
*Task 3 awaits the operator. NO research run was triggered.*
