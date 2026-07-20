---
phase: 13-tribunal-re-home-infra-baseline
plan: 01
subsystem: tribunal-engine
tags: [tribunal, re-home, lift-and-shift, audit-chain, cloud-build, import-graph]
requires: []
provides:
  - "tribunal/ engine tree (nestor_pulse_sdk + nestor_pulse/secrets.py) as the base for Plans 02-04"
  - "Frozen audit hash-chain carried byte-identical (ENGINE-04)"
  - "Clean Cloud Build context (.gcloudignore) + proven engine-path import graph"
affects:
  - "backend/ (unchanged; tribunal/ is a separate 3.11 image alongside backend's 3.12)"
tech-stack:
  added: []   # no new packages — requirements.txt carried verbatim (Py 3.11.9)
  patterns:
    - "Lift-and-shift verbatim copy of a live, already-deployed engine"
    - "Bare-namespace __init__.py to sever the un-copied ADK arm from the sole cross-dep"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/**  (engine, 160+ files)
    - tribunal/nestor_pulse/secrets.py
    - tribunal/nestor_pulse/__init__.py
    - tribunal/nestor_pulse/tools/claude_deep_researcher.py
    - tribunal/nestor_pulse/tools/__init__.py
    - tribunal/requirements.txt
    - tribunal/pyproject.toml
    - tribunal/infrastructure/cloud-run/**
    - tribunal/README.md
    - tribunal/.gcloudignore
  modified: []
decisions:
  - "Copied nestor_pulse/tools/claude_deep_researcher.py (1 leaf) to resolve a real engine-path cross-dep RESEARCH A1 missed"
  - "nestor_pulse/__init__.py written as a bare namespace (not verbatim) to avoid importing the un-copied ADK modules"
  - "infrastructure/cloud-run/ subdir preserved (not flattened) to match acceptance-criteria paths"
metrics:
  duration: "~9 min"
  completed: "2026-07-20"
  tasks: 2
  files: 165
  commits: 2
---

# Phase 13 Plan 01: Tribunal Re-home into `tribunal/` Summary

Lift-and-shift of the working Tribunal deep-research engine (`nestor_pulse_sdk` + the
sole cross-package module `nestor_pulse/secrets.py`) verbatim into a new top-level
`tribunal/` directory in this repo (D-01), with the frozen audit hash-chain carried
byte-identical (ENGINE-04), a clean Cloud Build context (`.gcloudignore`), and the
engine-path import graph proven resolvable.

## What Was Built

- **Task 1 — engine copy (`001007d`):** Copied the entire `nestor_pulse_sdk/` engine
  (server, runs, pipeline, audit, db, alembic, tools, citations, scripts, tests,
  `secrets_bootstrap.py`, `health.py`, `uploads/`, `orgs/`, `projects/`, `account/`,
  `auth/`, `critique/`, `demo/`) into `tribunal/`, preserving structure and excluding
  `__pycache__`/`.venv`/`.pytest_cache`/`web/` and the stale `.last-build.env`. Carried
  `nestor_pulse/secrets.py` (sole cross-dep), `requirements.txt` (Py 3.11.9 pins,
  `asyncpg==0.31.0`, `anthropic==0.104.1`) and `pyproject.toml` **byte-identical**. Copied
  `infrastructure/cloud-run/` (Dockerfiles + deploy scripts for Plan 03). Added a
  `README.md` documenting the re-home and the deliberate 3.11-vs-`backend`-3.12 separation.
- **Task 2 — clean context + import-graph proof (`f8a5167`):** Wrote `tribunal/.gcloudignore`
  excluding caches, `.venv`, `.git`, `.planning`, and all `*.env`/secret files (T-13-03). Ran
  the RESEARCH A1 import-graph gate on the *copied* tree and resolved the one real engine-path
  cross-dep it surfaced (see Deviations).

## How to Verify

File-existence / grep based (dev machine has no Python/Docker — verification is static):

```bash
# Frozen chain + sole cross-dep + pins present
test -f tribunal/nestor_pulse_sdk/audit/hash_chain.py && grep -q tenant_id tribunal/nestor_pulse_sdk/audit/hash_chain.py
grep -q "def load_secrets_into_env" tribunal/nestor_pulse/secrets.py
grep -q "asyncpg==0.31.0" tribunal/requirements.txt && grep -q "anthropic==0.104.1" tribunal/requirements.txt

# Clean context, no junk
test -f tribunal/.gcloudignore && grep -q __pycache__ tribunal/.gcloudignore
find tribunal/ -type d \( -name __pycache__ -o -name .venv -o -name .pytest_cache \)   # empty
test ! -d tribunal/nestor_pulse_sdk/web                                                 # excluded

# Import graph: real 'from nestor_pulse.' statements, all accounted for
grep -rnE '^[[:space:]]*from nestor_pulse\.' tribunal/nestor_pulse_sdk/
#  -> secrets_bootstrap.py (sanctioned), tools/claude_adapter.py (now resolvable),
#     scripts/probe_intake.py (lazy, ADK-only dev script, not on boot path)
```

Byte-identity confirmed via `cmp` on `hash_chain.py`, `secrets.py`, `requirements.txt`,
`pyproject.toml`, and `claude_deep_researcher.py` — all IDENTICAL to the sibling source.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Copied one leaf module RESEARCH A1 missed (`claude_deep_researcher.py`)**
- **Found during:** Task 2 (running the authoritative import-graph gate on the copied tree).
- **Issue:** RESEARCH Assumption A1 claims "the ONLY `from nestor_pulse.` import anywhere in
  the SDK is the ADK arm in `runs/adapter.py`." This is **false**. `tribunal/nestor_pulse_sdk/
  tools/claude_adapter.py` (line 12) does a **module-level** `from nestor_pulse.tools.
  claude_deep_researcher import deep_research_async`, and it is on the live engine path:
  `pipeline/tribunal/research_division.py -> pipeline/deep_researchers/degraded_parallel.py ->
  tools/claude_adapter.py`. The `nestor_pulse/tools/` package body was on the plan's
  "do NOT copy" list, so the copied image would **ImportError at boot** when the deep-research
  division loads. (The gemini/openai adapters only *mention* `nestor_pulse/tools` in docstrings
  — they import in-package `nestor_pulse_sdk.audit`, so only the Claude leaf is affected.)
- **Fix:** Copied the single, self-contained leaf `nestor_pulse/tools/claude_deep_researcher.py`
  (imports only stdlib + `httpx`, zero `nestor_pulse.*` deps — verified `grep -c` = 0) plus a
  namespace `nestor_pulse/tools/__init__.py`. No other `nestor_pulse/tools` module is needed
  (the rest is the ADK arm). Byte-identical to source.
- **Files modified:** `tribunal/nestor_pulse/tools/claude_deep_researcher.py`,
  `tribunal/nestor_pulse/tools/__init__.py`
- **Commit:** `f8a5167`

**2. [Rule 3 - Blocking] `nestor_pulse/__init__.py` written fresh, not copied verbatim**
- **Found during:** Task 1.
- **Issue:** The plan says "create the `tribunal/nestor_pulse/` package dir with an
  `__init__.py` if the source has one." The source `nestor_pulse/__init__.py` eagerly imports
  six ADK-arm modules (`agent`, `decomposer_agent`, `intent_classifier_agent`,
  `research_strategy_agent`, `mission_brief_agent`, `research_agent`) — none of which are
  copied. Copying it verbatim would ImportError on `import nestor_pulse.secrets`.
- **Fix:** Wrote a bare-namespace `nestor_pulse/__init__.py` (documenting why) so the sole
  cross-dep `import nestor_pulse.secrets` resolves without dragging in the ADK arm.
- **Files modified:** `tribunal/nestor_pulse/__init__.py`
- **Commit:** `001007d`

**3. [Rule 3 - Cleanup] Removed stale `infrastructure/cloud-run/.last-build.env`**
- **Found during:** Task 1 (post-copy junk scan).
- **Issue:** The copied `.last-build.env` is a build artifact from the OLD standalone
  deployment; it hardcodes old `project-cb01b861` Artifact Registry image URLs. RESEARCH
  §Runtime State Inventory says old build artifacts must not be carried; `build-and-push.sh`
  regenerates it at deploy time (Plan 03).
- **Fix:** Deleted it from the copied tree before committing. `.gcloudignore` also excludes it.
- **Commit:** `001007d`

### Note on the plan's exact Task 2 gate string
The plan's automated-verify string
`grep -rE 'from nestor_pulse[. ]' ... | grep -v adapter.py | grep -v secrets_bootstrap.py | wc -l == 0`
does not literally return 0 on the copied tree — two **benign** hits remain: a `server.py`
**docstring** line ("load_dotenv (find .env from nestor_pulse directory)"), matched only by the
space-variant of the pattern, and a **lazy** `from nestor_pulse.intake_agent import intake_agent`
inside `scripts/probe_intake.py`'s `async def probe_adk()` (an ADK-only dev probe; nothing
imports `probe_intake`, so it is never on the server/worker boot path). Neither causes a
boot-time ImportError on the deployed engine. The RESEARCH-authoritative intent (no unresolved
`nestor_pulse.*` cross-dep on the engine boot path) is satisfied after fix #1.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced (pure file copy +
one leaf module + a build-context ignore file). The threat register's T-13-01 (audit chain
byte-identity) and T-13-03 (secrets excluded from build context) were both satisfied:
`hash_chain.py` is `cmp`-identical and `.gcloudignore` excludes `*.env`/keys.

## Known Stubs

None. This plan is a code copy; no placeholder/mock data was introduced. The two NEW code
changes that ride on this base (Alembic `version_table`/`tribunal` schema in `env.py`, the
per-run advisory lock in `execute.py`) are explicitly Plan 02, not stubs of this plan.

## Self-Check: PASSED

All 12 created files verified present; all 3 commits (`001007d`, `f8a5167`, `2833f34`) verified in the git log; working tree clean (no untracked `tribunal/` files).
