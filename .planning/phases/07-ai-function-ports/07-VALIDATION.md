---
phase: 7
slug: ai-function-ports
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-30
---

# Phase 7 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `07-RESEARCH.md` § Validation Architecture. The Per-Task map is filled by the planner.
> **Note (author-by-construction):** the dev machine has no local Python/Docker — the suite runs in
> CI (real Postgres) and live LLM/Whisper calls stay faked. Tests are authored to be green in CI;
> local execution is deferred (Phases 1–6 precedent).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` / `backend/tests/conftest.py` |
| **Quick run command** | `cd backend && pytest -q tests/test_ai_*.py` |
| **Full suite command** | `cd backend && pytest -q` |
| **Estimated runtime** | ~60–120 seconds (CI, with pg container) |

---

## Sampling Rate

- **After every task commit:** Run the quick command for the touched AI function's test module.
- **After every plan wave:** Run the full suite.
- **Before `/gsd-verify-work`:** Full suite green in CI; all external AI calls faked (no network).
- **Max feedback latency:** ~120 seconds.

---

## Per-Task Verification Map

> Per-plan summary; the authoritative per-task `<verify><automated>` commands live in each PLAN.md.

| Plan | Wave | Requirement | Threat Ref | Secure Behavior | Automated Command | Status |
|------|------|-------------|------------|-----------------|-------------------|--------|
| 07-01 | 1 | AI-01..06 | T-7-01/02 | RED suites: contract + cross-tenant + release + EXPLAIN | `pytest -q tests/test_ai_*.py` | ⬜ pending |
| 07-02 | 1 | AI-03/05 | T-7-04 | 0009 new tables RLS + space indexes; `alembic check` clean | `alembic check` + `pytest -q tests/test_schema_shape.py` | ⬜ pending |
| 07-03 | 1 | AI-01/02/03/04/05 | T-7-05 | AI clients; keys out of Settings, never logged | `pytest -q tests/test_ai_clients.py` | ⬜ pending |
| 07-08 | 1 | AI-01/02/03/04/05 | T-7-05/07 | Secret→env, CPU-always/min-inst=0, run-research guard | `pytest -q tests/test_scope_guard_ai.py` | ⬜ pending |
| 07-04 | 2 | AI-06/04 | T-7-02/06 | `set_space_context` ×2; `pool.checkedout()==0` across call | `pytest -q tests/test_ai_session_release.py` | ⬜ pending |
| 07-05 | 3 | AI-01/02 | T-7-03 | bg task; `succeeded`/`failed`; Identity-only routes | `pytest -q tests/test_ai_apply_skill.py tests/test_ai_context_pack.py` | ⬜ pending |
| 07-06 | 4 | AI-04 | T-7-01 | space-prefiltered search; zero foreign rows | `pytest -q tests/test_ai_search_cross_tenant.py` | ⬜ pending |
| 07-07 | 4 | AI-03/05 | T-7-02 | structure/extract/transcribe; faked audio; space-scoped writes | `pytest -q tests/test_ai_structure_extract.py tests/test_ai_transcribe.py` | ⬜ pending |

### Gap-closure plans (07-09/10/11) — source-assertion verification

> Gap plans close UAT findings; the dev machine has no Python/Docker and the frontend has no test
> harness, so their per-task `<verify><automated>` blocks are **source-assertion greps** (cross-platform
> Git Bash, no Python/Node). Backend behavior lands green in the next Cloud Build image rebuild; frontend
> behavior is verified on local vite. Test type: **source-assertion**.

| Plan | Wave | Task | Requirement | Secure Behavior | Automated Command (source-assertion) | Status |
|------|------|------|-------------|-----------------|--------------------------------------|--------|
| 07-09 | 1 | T1 | AI-02/04 | `skill` on SkillRunView + scoped ResearchArtifactRepository w/ context-pack filter | `grep -q "skill=run.skill" backend/app/api/intake_routes.py && grep -q "class ResearchArtifactRepository" backend/app/db/repository.py && [ "$(grep -c 'context-pack-generator' backend/app/db/repository.py)" -ge 1 ]` | ⬜ pending |
| 07-09 | 1 | T2 | AI-02/04 | DI injector + existence-hidden GET /context-pack; no raw DB symbol in route | `grep -q "def get_research_artifact_repo" backend/app/db/session.py && grep -q "/{intake_id}/context-pack" backend/app/api/intake_routes.py && [ "$(grep -vE '^\s*#\|^\s*\*' backend/app/api/intake_routes.py \| grep -cE 'get_engine\(\|get_superadmin_engine\(\|sessionmaker\(\|create_engine\(')" -eq 0 ]` | ⬜ pending |
| 07-09 | 1 | T3 | AI-02/04 | Tests authored: projection/discriminator/source-filter/cross-tenant empty read | `[ "$(grep -c 'context-pack' backend/tests/test_intake_routes.py)" -ge 1 ] && grep -q "skill" backend/tests/test_intake_routes.py` | ⬜ pending |
| 07-10 | 2 | T1 | AI-02 | getContextPack seam wired into ContextPackBlock; `skill` on frontend SkillRun | `[ "$(grep -c 'getContextPack' frontend/src/components/intake/ContextPackBlock.tsx)" -ge 2 ] && [ "$(grep -c 'skill: string' frontend/src/lib/api/skillRuns.ts)" -eq 1 ]` | ⬜ pending |
| 07-10 | 2 | T2 | AI-02 | RunningClock for the context-pack run in the awaiting_context_pack banner | `[ "$(grep -c 'RunningClock' frontend/src/components/intake/NextStepBanner.tsx)" -ge 2 ]` | ⬜ pending |
| 07-10 | 2 | T3 | AI-02 | proposals loader + review effect discriminated to apply-intake-skill | `[ "$(grep -c 'skill === "apply-intake-skill"' frontend/src/components/intake/IntakeForm.tsx)" -ge 1 ] && [ "$(grep -c 'r.status === "succeeded"' frontend/src/components/intake/IntakeForm.tsx)" -ge 1 ]` | ⬜ pending |
| 07-11 | 1 | T1 | AI-03/04/05 | AISkillsPanel wires structure/extract/embeddings/transcribe triggers | `[ "$(grep -cE 'skills\.(structureAnswers\|extractInsights\|generateEmbeddings\|transcribeSource)' frontend/src/components/intake/AISkillsPanel.tsx)" -eq 4 ]` | ⬜ pending |
| 07-11 | 1 | T2 | AI-03/04/05 | copy-link handlers use intake.id (no dead token); AISkillsPanel mounted | `[ "$(grep -cE '/intake/\$\{intake\.id\}' 'frontend/src/routes/admin.pulse.intakes.$id.tsx')" -ge 2 ] && [ "$(grep -c 'Geen intake-token' 'frontend/src/routes/admin.pulse.intakes.$id.tsx')" -eq 0 ] && [ "$(grep -c 'AISkillsPanel' 'frontend/src/routes/admin.pulse.intakes.$id.tsx')" -ge 2 ]` | ⬜ pending |
| 07-11 | 1 | T3 | AI-03/04/05 | DownloadControl resolves shared templates/ paths as static assets | `[ "$(grep -c 'templates/' frontend/src/components/intake/FieldRenderer.tsx)" -ge 1 ] && ls frontend/public/templates/.gitkeep` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

### Required test families (from RESEARCH § Validation Architecture)
1. **Per-function contract tests** (AI-01..AI-05): fake the external Anthropic/OpenAI/Whisper call;
   assert request shape (model id, max_tokens, payload) + DB writes + `skill_runs` status lifecycle
   terminal `succeeded`/`failed`.
2. **Cross-tenant scoping** (AI-04 + all writes): seed two spaces; semantic search as space A returns
   **zero** space-B artifacts; every AI write carries `space_id`.
3. **AI-06 connection-release assertion**: spy that `set_space_context` is invoked **twice** (read
   session + fresh write session) and no connection is held across the faked long call.
4. **0009 migration**: `alembic check` clean; new tables (`intake_sources`, `transcripts`,
   `extracted_insights`) have RLS + space-leading indexes; cross-tenant denial on each new table.
5. **Scope guard regression**: `run-research` remains unreachable (extends the Phase 6 D-06 guard).

---

## Wave 0 Requirements

- [ ] `backend/tests/test_ai_<fn>.py` — RED stubs per AI function (faked external call).
- [ ] `backend/tests/conftest.py` — extend with AI-call fakes + two-space embedding fixtures.
- [ ] `backend/tests/test_ai_session_release.py` — the `set_space_context`-called-twice assertion.
- [ ] `backend/tests/test_ai_cross_tenant.py` — semantic-search + new-table cross-tenant denial.

*Existing pytest infrastructure (conftest, dependency-override, pg container) covers the harness;
Wave 0 adds the AI-specific stubs and fakes.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live LLM/embedding/Whisper parity vs legacy output | AI-01..AI-05 | External API + non-deterministic; keys deferred to live deploy | Run each function against a seeded intake on the deployed Cloud Run service with real keys; compare to legacy output shape |
| `transcribe-audio` end-to-end (audio download) | AI-05 | Needs GCS storage (Phase 9) | Deferred to Phase 9 GCS; logic tested with a faked storage fetch now |
| `EXPLAIN` shows space_id prefilter on populated data | AI-04 | Plan-near-empty table may Seq-Scan; needs real data volume | On a space with many artifacts, `EXPLAIN (ANALYZE)` the search query; confirm index/prefilter behavior |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 120s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
