---
phase: 07-ai-function-ports
plan: 03
subsystem: ai
tags: [anthropic, openai, claude, whisper, embeddings, fastapi, pydantic-settings, prompts]

# Dependency graph
requires:
  - phase: 02-backend-skeleton-cloud-sql-wiring
    provides: core.config.Settings (typed non-secret env config; the model-id fields extend it)
  - phase: 06-intake-crud-parity-frontend-api-seam
    provides: skill_runs model + intake flow the AI handlers will drive
provides:
  - app/ai package (HTTP/parse/config seam; no DB engine/session construction — CI grep-guard clean)
  - anthropic_client() / openai_client() factories reading API keys from os.environ at call time (D-07) — the 07-01 test monkeypatch seam
  - Verbatim legacy system prompts (apply-intake-skill, generate-context-pack, structure-answers, extract-insights) + INSIGHT_KINDS
  - extract_json / extract_json_array / estimate_cost_usd ports of the legacy extractJson + cost math
  - Six config-driven, env-overridable model-id defaults in Settings (D-06)
affects: [07-04-ai-session-helper, 07-05-apply-context-pack, 07-06-embeddings-search, 07-07-structure-extract, 07-08-deploy-secrets]

# Tech tracking
tech-stack:
  added: [anthropic==0.113.0, openai==2.44.0]
  patterns:
    - "External-API client factories read secrets from os.environ at call time (never in Settings, never logged) — D-07"
    - "Legacy prompts carried verbatim as constant-asset module constants (mirrors app/intake_canonical.py)"
    - "Non-secret model IDs are env-overridable typed config; secrets stay out of typed config"

key-files:
  created:
    - backend/app/ai/__init__.py
    - backend/app/ai/clients.py
    - backend/app/ai/prompts.py
    - backend/app/ai/parsing.py
  modified:
    - backend/pyproject.toml
    - backend/app/core/config.py

key-decisions:
  - "Used official anthropic/openai SDKs (not raw httpx) for typed usage + timeouts — Claude's discretion per RESEARCH, consistent with Don't Hand-Roll guidance"
  - "Restored em-dash + Dutch accents that the byte-corrupted docs/supabase-functions/*.ts mangled into mojibake — parity means matching the text production Claude received, not the corrupted export bytes"
  - "Exported INSIGHT_KINDS tuple alongside the extract-insights prompt so the 07-07 handler validates against one canonical list"

patterns-established:
  - "app/ai/* is HTTP/parse/config only; raw DB symbols stay in app/db/ (CI grep-guard enforced)"
  - "API keys read at call time inside the client factory bodies — the single secret-handling discipline for the phase"

requirements-completed: [AI-01, AI-02, AI-03, AI-04, AI-05]

# Metrics
duration: 22min
completed: 2026-06-30
---

# Phase 7 Plan 03: External-API Client Seam Summary

**The fakeable AI seam — anthropic/openai client factories (keys read from os.environ at call time, D-07), the four legacy system prompts carried verbatim, the extractJson/cost-estimate ports, and six config-driven model-id defaults (D-06).**

## Performance

- **Duration:** ~22 min
- **Started:** 2026-06-30T11:09:00Z (approx)
- **Completed:** 2026-06-30T11:31:48Z
- **Tasks:** 3
- **Files modified:** 6 (4 created, 2 modified)

## Accomplishments
- `app/ai/clients.py` — `anthropic_client()` / `openai_client()` factories that read `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` from `os.environ` **inside the function body** (call time, D-07): never module-level, never logged, never in `Settings`. These two names are the monkeypatch seam the 07-01 tests target.
- `app/ai/prompts.py` — the four legacy system prompts carried verbatim as module constants + the 13-value `INSIGHT_KINDS` tuple.
- `app/ai/parsing.py` — `extract_json` (strip fences, slice first `{`..last `}`, raise on miss), `extract_json_array` (fenced-block else first `[`..last `]`), `estimate_cost_usd` (in/1e6·3 + out/1e6·15, round 4) — exact ports of `apply-intake-skill.ts:135-153`.
- `core.config.Settings` — six non-secret, env-overridable model-id fields with the exact legacy defaults (D-06); no API key field added.
- SDK deps `anthropic==0.113.0` + `openai==2.44.0` declared (versions re-verified live on PyPI 2026-06-30).

## Task Commits

Each task was committed atomically:

1. **Task 1: SDK deps + clients.py factories** - `09b0de5` (feat)
2. **Task 2: prompts.py (verbatim) + parsing.py (extractJson + cost ports)** - `105c5c8` (feat)
3. **Task 3: config.py model-id defaults (D-06)** - `995cb6c` (feat)

_No metadata commit by this agent — STATE.md/ROADMAP.md are owned by the wave orchestrator (worktree mode)._

## Files Created/Modified
- `backend/app/ai/__init__.py` - Package marker + scope docstring (HTTP/parse/config only)
- `backend/app/ai/clients.py` - anthropic/openai client factories; keys at call time (D-07)
- `backend/app/ai/prompts.py` - Four verbatim legacy system prompts + INSIGHT_KINDS
- `backend/app/ai/parsing.py` - extract_json / extract_json_array / estimate_cost_usd
- `backend/pyproject.toml` - Added anthropic==0.113.0 + openai==2.44.0 deps
- `backend/app/core/config.py` - Six model-id Settings fields (D-06); no secret added

## Decisions Made
- **Official SDKs over raw httpx** — typed `usage` (input/output tokens), explicit `timeout=`, retries; prompts/models drive parity, not the transport (RESEARCH Don't Hand-Roll). Anthropic timeout 180s; OpenAI 180s.
- **Restore the mojibake to clean UTF-8** — see Deviations below.
- **Export `INSIGHT_KINDS`** so the 07-07 extract-insights handler validates the LLM `kind` field against the same canonical list embedded in the prompt.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Restored byte-corrupted characters in the legacy prompts**
- **Found during:** Task 2 (prompts.py)
- **Issue:** The `docs/supabase-functions/*.ts` exports are byte-corrupted — every em-dash `—` appears as the double-mojibake sequence `Ã¢ÂÂ` (UTF-8 `E2 80 94` round-tripped through Latin-1 twice; confirmed via the byte sequence `C3 83 C2 A2 C3 82 C2 80 C3 82 C2 94`), and a few Dutch accents are likewise mangled (`prozaïsche`, `commerciële`). A literal byte-for-byte copy would send garbage to Claude and **defeat** the parity the plan demands.
- **Fix:** Carried the prompts with the corruption **restored** to the characters production Claude actually received (clean em-dashes + accents). The rest of this repo uses real em-dashes (e.g. `app/intake_canonical.py:28` "Nestor Pulse — Intake v1"), confirming the deployed functions sent clean UTF-8. The genuine source typo `dataclatste` (context-pack §6) is **not** an encoding artifact and was preserved as-is.
- **Files modified:** backend/app/ai/prompts.py
- **Verification:** `grep -o '—' prompts.py` = 28 em-dashes; zero mojibake `Ã` in any prompt body (the one residual `Ã` is in the docstring explaining the corruption); `prozaïsche`/`commerciële` present; inline `INSIGHT_KINDS` list matches the exported tuple order.
- **Committed in:** 105c5c8 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — encoding corruption in the source-of-record).
**Impact on plan:** The fix is required for parity (the whole point of "verbatim"). No scope creep — prompt content is otherwise identical to the legacy source.

## Issues Encountered
- **No local Python/Docker** (memory: `dev-machine-no-python-docker`). The plan's `python -c "import ast; ast.parse(...)"` verify commands could not run locally. Mitigated by author-by-construction + grep-based structural verification: triple-quote delimiters balanced (prompts 10, parsing 8, clients 6 — all even), all acceptance greps pass, and `scripts/ci_no_raw_db_access.sh` runs clean over the whole `app/` tree. Live `import` runs in Cloud Build / CI.
- **Worktree path correction** — initial edits targeted the shared checkout; re-issued against the worktree copy. No content impact.

## User Setup Required
None by this plan. The API-key **secrets** (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY`) must be wired as Cloud Run env from Secret Manager in **07-08** (D-07) before live LLM calls — out of scope here.

## Next Phase Readiness
- The seam is ready for 07-04 (`app/db/ai_session.py` tenant-session helper) and the handler plans 07-05/06/07, which import `anthropic_client`/`openai_client`, the prompt constants, the parsing helpers, and the model-id Settings fields.
- **Scope note:** This plan delivers the *shared seam* for AI-01..AI-05 — the per-function handlers that fully satisfy those requirements land in 07-05/06/07. The requirement IDs are carried in frontmatter per the plan; the orchestrator owns REQUIREMENTS.md marking.
- No blockers.

## Self-Check: PASSED

All created/modified files exist on disk; all three task commits (`09b0de5`, `105c5c8`, `995cb6c`) present in git history. `scripts/ci_no_raw_db_access.sh` clean over `app/`; all acceptance greps satisfied. Python `ast.parse` verify deferred to CI (no local Python — `dev-machine-no-python-docker`); triple-quote delimiters confirmed balanced as a local proxy.

---
*Phase: 07-ai-function-ports*
*Completed: 2026-06-30*
