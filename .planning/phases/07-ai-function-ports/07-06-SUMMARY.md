---
phase: 07-ai-function-ports
plan: 06
subsystem: ai-embeddings-search
tags: [ai, embeddings, semantic-search, pgvector, tenant-isolation, openai]
requires: [07-04, 07-05, 07-03, 07-02]
provides:
  - "run_embeddings (AI-04) — pending research_artifacts -> OpenAI 1536 vectors -> space-scoped artifact_embeddings, embed_status pending->done idempotency"
  - "semantic_search (AI-04) — query embed (1536) + space-prefiltered exact cosine scan via search_artifacts"
affects:
  - backend/app/ai/skills/embeddings.py
  - backend/app/ai/search.py
tech-stack:
  added: []
  patterns:
    - "AI-06 read->release->call->reopen-write contract via run_with_session_release (embed call holds no DB connection)"
    - "Tenant confinement by RLS + GUC inside tenant_session (no manual WHERE space_id in the search path)"
    - "Per-chunk OpenAI embeddings.create(input=chunk) so response.data[0] maps 1:1 to a stored vector"
key-files:
  created: []
  modified:
    - backend/app/ai/skills/embeddings.py
    - backend/app/ai/search.py
decisions:
  - "Embedding rows go through ArtifactEmbeddingRepository: user path .create() injects space_id from Identity (T-7-13); superadmin path .create_in_space(artifact_space) for the audited cross-space write"
  - "Idempotency via embed_status pending->done (read filters pending, write flips to done) — the Postgres-native analogue of the legacy content_hash skip-set"
  - "Per-artifact text chunked into 2000-char windows (one window for typical short artifacts) — bounds token use without changing the legacy one-row-one-vector shape"
  - "semantic_search default max_distance=None keeps every nearest row; legacy 0.7-similarity cutoff (distance 0.3) exposed param/config-driven"
metrics:
  duration: ~25m
  completed: 2026-06-30
---

# Phase 07 Plan 06: Embeddings + Semantic Search Summary

Filled the AI-04 embed/search seam: `run_embeddings` embeds an intake's pending
`research_artifacts` into space-scoped `artifact_embeddings` (OpenAI `text-embedding-3-small`,
1536 dims) with `embed_status` idempotency, and `semantic_search` embeds the query and runs the
space-prefiltered exact cosine scan via the 07-04 `search_artifacts` helper — closing the legacy
intake_id-only cross-tenant leak.

## What Was Built

### Task 1 — `run_embeddings` (backend/app/ai/skills/embeddings.py)
Replaced the 07-05 `NotImplementedError` stub with the real AI-06 release-contract port:
- **READ** selects the intake's `research_artifacts` at `embed_status='pending'` (RLS confines
  the scan to the caller's space) into plain DTOs of `(artifact_id, space_id, chunks)`.
- **CALL** embeds each chunk via `openai_client().embeddings.create(model=text-embedding-3-small,
  input=chunk, dimensions=1536)` holding NO DB connection (T-7-06). Per-chunk calls so each
  response `data[0].embedding` maps 1:1 to a stored row (also matches the test fake's shape).
- **WRITE** inserts one `artifact_embeddings` row per chunk through `ArtifactEmbeddingRepository`
  (user: `create()` injects `space_id` from Identity — T-7-13; superadmin: `create_in_space()`
  into the artifact's own space), flips each source artifact's `embed_status` to `'done'`
  (idempotency — re-runs find nothing pending and write no duplicate vectors), and finalizes the
  `skill_runs` row `succeeded` (D-09).
- Commit: `c8c4f0c`

### Task 2 — `semantic_search` (backend/app/ai/search.py)
Replaced the 07-05 stub with the query-embed + scan wiring:
- Embeds the query (`text-embedding-3-small`, `dimensions=1536`) holding no DB connection.
- Opens ONE `tenant_session(identity)` and calls `search_artifacts(session, query_vec, limit,
  max_distance)`; on the user engine the 0002 RLS policy + the transaction-local GUC prefilter
  the `<=>` scan to the caller's space. No ANN vector index created (D-03).
- Returns JSON-friendly dicts `(id, artifact_id, chunk_text, distance)` for the inline GET
  `/intakes/{id}/search` endpoint. `max_distance` default `None` keeps every nearest row; the
  legacy 0.7-similarity cutoff (distance 0.3) is exposed param/config-driven.
- Commit: `fbe821c`

## Pinned-Seam Compliance (Wave-1 RED contracts)
- `test_ai_embeddings.py` — request shape asserts `model='text-embedding-3-small'` +
  `dimensions=1536`; write asserts space-scoped rows + non-null embedding + `embed_status` off
  `pending`. Implementation requests exactly those and writes space-scoped rows via the repo wall.
- `test_ai_search_cross_tenant.py` / `test_ai_search_explain.py` — exercise `search_artifacts`
  (07-04) directly; `semantic_search` wires the OpenAI query-embed around that same helper inside
  `tenant_session`, so the zero-foreign-rows + space_id-prefilter guarantees carry through.

## Acceptance Criteria (grep gates — all green)
- `embeddings.py`: `def run_embeddings` + `run_with_session_release` (4 hits); `dimensions`(6) +
  `1536`(6); `embed_status`(7); raw DB symbols `get_engine|sessionmaker` = 0.
- `search.py`: `def semantic_search`(1) + `search_artifacts`(6); `dimensions`(4) + `1536`(6);
  forbidden `hnsw|ivfflat|get_engine|sessionmaker` = 0.

## Threat Model Coverage
- **T-7-13** (embedding row without space_id) — mitigated: rows written via
  `ArtifactEmbeddingRepository` (space_id identity-derived for user, artifact-own-space for
  superadmin), inside `tenant_session`.
- **T-7-01** (search returns another space's chunks) — mitigated: scan runs inside
  `tenant_session` (RLS + GUC + space_id prefilter); no manual cross-space WHERE.
- **T-7-06** (embed loop holds a connection across OpenAI) — mitigated:
  `run_with_session_release` releases the connection across the embed CALL.

## Deviations from Plan
The plan's Task-1 action said "write through `ArtifactEmbeddingRepository` (space_id injected
from Identity)". Implemented exactly that for the user path; for the superadmin path (no own
space) the write uses the audited `create_in_space(artifact_space, ...)` — mirroring the 07-05
`context_pack.py` precedent — so the embed step also works when a superadmin triggers it. The
space_id still originates only from tenant-scoped reads, never a request/LLM value (T-7-13
intact). Not a behavioural change to the user path the tests exercise.

No other deviations. No auth gates. No checkpoints (fully autonomous plan).

## Known Stubs
None — both functions are fully wired (real OpenAI client via the `openai_client()` seam, real
repository/session writes). The OpenAI call is faked only in tests via the `fake_openai` fixture.

## Verification Notes
Python is unavailable on this dev machine (project memory: backend tests run in CI), so the
RED→GREEN transition is authored-by-construction against the pinned Wave-1 contracts and verified
via the plan's grep acceptance gates (all green above). `pytest tests/test_ai_embeddings.py`,
`test_ai_search_cross_tenant.py`, and `test_ai_search_explain.py` run GREEN in CI (faked OpenAI +
testcontainer Postgres for the integration pair).

## Self-Check: PASSED
- Files exist: `backend/app/ai/skills/embeddings.py`, `backend/app/ai/search.py`,
  `.planning/phases/07-ai-function-ports/07-06-SUMMARY.md`.
- Commits exist: `c8c4f0c` (run_embeddings), `fbe821c` (semantic_search), `ace9fe2` (summary).
- Scope: only the two owned files changed (no STATE.md/ROADMAP.md, no sibling-agent files).
