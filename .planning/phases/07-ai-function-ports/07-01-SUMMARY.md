---
phase: 07-ai-function-ports
plan: 01
subsystem: testing
tags: [pytest, testcontainers, pgvector, anthropic, openai, whisper, rls, tenant-isolation]

# Dependency graph
requires:
  - phase: 01-schema-migrations
    provides: conftest harness (pg_container/engine/set_space/two_spaces/superadmin_engine), RLS GUC contract
  - phase: 06-intake-crud
    provides: test_intake_cross_tenant.py harness (dependency-override + engine-factory patch + _build_app)
provides:
  - Ten RED AI test modules authored against the final Phase-7 contract
  - conftest fakes: fake_anthropic / fake_openai / seed_artifact_embeddings
  - Executable proof spine for AI-01..AI-06 + D-09 (turns GREEN as 07-04..07-07 land)
affects: [07-02, 07-03, 07-04, 07-05, 07-06, 07-07, 07-08]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "RED-on-pending-impl: importorskip external deps, HARD-import impl modules so a missing module is a COLLECTION ERROR (the intended Wave-0 RED), never a silent skip"
    - "Stub SDK clients (fake_anthropic/fake_openai) record request kwargs for shape assertions + return canned typed responses"
    - "AI tests patch engine factories in app.db.ai_session namespace; AI-06 spy wraps set_space_context at the call site"

key-files:
  created:
    - backend/tests/test_ai_apply_skill.py
    - backend/tests/test_ai_context_pack.py
    - backend/tests/test_ai_structure_extract.py
    - backend/tests/test_ai_embeddings.py
    - backend/tests/test_ai_transcribe.py
    - backend/tests/test_ai_status_contract.py
    - backend/tests/test_ai_search_cross_tenant.py
    - backend/tests/test_ai_search_explain.py
    - backend/tests/test_ai_session_release.py
    - backend/tests/test_ai_cross_tenant.py
  modified:
    - backend/tests/conftest.py

key-decisions:
  - "Impl modules (app.api.ai_routes / app.ai.skills / app.ai.clients / app.db.ai_session) are HARD-imported so each suite is a collection-error RED until its impl plan lands; external deps stay importorskip for skip-clean collection"
  - "conftest fakes import NOTHING from app.ai / app.db.ai_session so conftest stays importable while impl is pending (PLAN must_have)"
  - "AI-06 spy patches set_space_context in the app.db.ai_session call-site namespace (and rls) and delegates to the real setter, so the GUC is still actually set while the count is observed"
  - "seed_artifact_embeddings uses raw SQL + explicit CAST(:embedding AS vector) (pg8000 has no native vector type) and no ORM-model import"

patterns-established:
  - "Pattern: per-function AI contract test = fake the SDK, assert (1) request shape (model id / max_tokens / dimensions / response_format), (2) DB writes carry space_id, (3) skill_run status lifecycle"
  - "Pattern: EXPLAIN test asserts the space_id prefilter / RLS qual is present, NOT a strict Index Scan (Pitfall 5 — near-empty table may legitimately Seq-Scan)"

requirements-completed: [AI-01, AI-02, AI-03, AI-04, AI-05, AI-06]

# Metrics
duration: ~40min
completed: 2026-06-30
---

# Phase 7 Plan 01: Wave-0 AI RED Test Scaffold Summary

**Ten RED pytest modules + three conftest fakes (fake_anthropic / fake_openai / seed_artifact_embeddings) authored against the final Phase-7 AI contract — per-function contract suites, cross-tenant + EXPLAIN + connection-release integration suites, and the D-09 status contract — all valid Python, RED only on the pending impl import.**

## Performance

- **Duration:** ~40 min
- **Started:** 2026-06-30
- **Completed:** 2026-06-30
- **Tasks:** 3
- **Files modified:** 11 (10 created, 1 extended)

## Accomplishments
- Extended `conftest.py` with `fake_anthropic` (records model/max_tokens, returns `.content[0].text` + typed `.usage`), `fake_openai` (`.embeddings.create` → 1536-float `.data[0].embedding`; `.audio.transcriptions.create` → `.text`/`.language`/`.segments`), and `seed_artifact_embeddings` (raw-SQL two-space vector seeding) — none import the pending `app.ai` / `app.db.ai_session`.
- Six contract suites pin the final request/DB/status contract: `claude-sonnet-4-5` + `max_tokens=8192` (apply), `decomposed` + `embed_status='pending'` + `applied_at` (context-pack), `claude-sonnet-4-6` arrays → `extracted_by='llm'` / `extracted_insights` (structure/extract), `text-embedding-3-small` + `dimensions=1536` (embeddings), `whisper-1` + `verbose_json` faked audio (transcribe), and EXACT `succeeded`/`failed` with a forbidden-synonym guard (D-09).
- Four integration suites (`pytest.mark.integration`, auto-skip without Docker) prove the marquee guarantees: zero space-B rows from a space-A search (T-7-01), EXPLAIN space_id prefilter (Pitfall 5), `set_space_context` called EXACTLY twice + `pool.checkedout()==0` across the faked call (T-7-02/T-7-06), and per-new-table cross-tenant read/write denial.
- Verified all 11 files via `ast.parse` (Python 3.12 located on the box despite the usual no-Python gap) and every PLAN acceptance grep.

## Task Commits

Each task was committed atomically:

1. **Task 1: conftest fakes** - `1f38d4d` (test)
2. **Task 2: six contract RED suites (AI-01..05 + D-09)** - `8c6e4ab` (test)
3. **Task 3: four integration RED suites (AI-04/AI-06 + new-table denial)** - `8c4188e` (test)

_No production code; this is the phase-zero RED scaffold (Phase 1/5 Wave-0 precedent)._

## Files Created/Modified
- `backend/tests/conftest.py` - Added `fake_anthropic`, `fake_openai`, `seed_artifact_embeddings` fixtures (+ stdlib stub classes), no app.ai import.
- `backend/tests/test_ai_apply_skill.py` - AI-01: request shape + `output_parsed` + running→succeeded / bad-JSON→failed.
- `backend/tests/test_ai_context_pack.py` - AI-02: research_artifacts(text_content, embed_status=pending) + intakes.status=decomposed + context_pack_artifact_id + applied_at.
- `backend/tests/test_ai_structure_extract.py` - AI-03: claude-sonnet-4-6 arrays → space-scoped intake_answers(extracted_by=llm) / extracted_insights.
- `backend/tests/test_ai_embeddings.py` - AI-04 write half: dimensions=1536 + space-scoped artifact_embeddings + embed_status advance.
- `backend/tests/test_ai_transcribe.py` - AI-05: whisper-1 verbose_json (faked audio) → space-scoped transcripts.
- `backend/tests/test_ai_status_contract.py` - D-09: terminal status EXACTLY succeeded/failed, no synonyms.
- `backend/tests/test_ai_search_cross_tenant.py` - AI-04: search AS space-A → zero space-B rows (T-7-01).
- `backend/tests/test_ai_search_explain.py` - AI-04: EXPLAIN space_id prefilter/RLS qual, not strict Index Scan.
- `backend/tests/test_ai_session_release.py` - AI-06: set_space_context ×2 + pool.checkedout()==0 (T-7-02/T-7-06).
- `backend/tests/test_ai_cross_tenant.py` - new-table cross-tenant read+write denial across intake_sources/transcripts/extracted_insights/skill_runs.

## Decisions Made
- **Hard-import the impl, importorskip the deps.** The PLAN requires RED on pending impl. External deps (firebase_admin/sqlalchemy/fastapi) are `importorskip` (skip-clean), but the not-yet-existing impl modules are plain imports so a missing module is a COLLECTION ERROR — the intended Wave-0 RED — attributable solely to the missing impl, never a syntax/fixture error.
- **Pinned the impl test seams** future plans must conform to (they "turn GREEN incrementally, none deleted/weakened"): `app.api.ai_routes.ai_router`; `app.ai.clients.anthropic_client` / `openai_client`; `app.db.ai_session.{get_engine, get_superadmin_engine, set_space_context, tenant_session, run_with_session_release, search_artifacts}`; endpoints `/intakes/{id}/skills/{apply|context-pack|structure-answers|extract-insights}`, `/intakes/{id}/embeddings`, `/intakes/{id}/sources/{sid}/transcribe`; transcribe audio-fetch seam `app.ai.skills.download_audio_bytes` (spied `raising=False`).

## Deviations from Plan

None - plan executed exactly as written. (One opportunistic improvement over the author-by-construction assumption: a Python 3.12 interpreter was found on the box, so the canonical `ast.parse` verify was actually executed rather than deferred to CI — strengthening, not changing, the verification.)

## Issues Encountered
- Initial Edit/Write targeted the shared-checkout path; redirected all file operations to the worktree root (`.claude/worktrees/agent-a250458c8fceaded0`). No content impact.

## Threat Flags

None — this plan adds only test modules; it introduces no new network endpoints, auth paths, or schema. It is the executable proof of the existing T-7-01/T-7-02/T-7-06 register entries.

## User Setup Required
None - no external service configuration required (all AI calls faked; live keys deferred to the deploy plans 07-03/07-08).

## Self-Check: PASSED

- All 11 files exist and parse (`ast.parse` OK on Python 3.12).
- Acceptance greps pass: conftest fixtures ==3; `claude-sonnet-4-5` in apply (3); `dimensions` in embeddings (8); `"succeeded"/"failed"` in status contract (7); `pytest.mark.integration` in all 4 integration suites; `set_space_context` (12) + `len(calls) == 2` in session-release; zero-foreign-row asserts in search_cross_tenant; no bare `assert "Index Scan"` in search_explain (0).
- Commits verified present: `1f38d4d`, `8c6e4ab`, `8c4188e`.

## Next Phase Readiness
- The RED spine is in place; 07-02 (0009 migration) + 07-03 (AI clients) + 07-04 (session helper) + 07-05/06/07 (function ports) turn these suites GREEN one function at a time.
- **CI dependency:** `anthropic` / `openai` must be added (07-03) and the contract/integration suites must run against real Postgres in CI/Cloud Build — they skip-clean locally (no Docker/deps on the dev box) and collection-error RED until impl lands, which is the intended state.

---
*Phase: 07-ai-function-ports*
*Completed: 2026-06-30*
