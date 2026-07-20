# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — GCP Re-platform

**Shipped:** 2026-07-20
**Phases:** 12 | **Plans:** 70 | **Commits:** 485 (2026-06-18 → 2026-07-20, 33 days)

### What Was Built
- Full pre-research intake flow on GCP: FastAPI/Cloud Run backend as sole DB path, Cloud SQL +
  pgvector via Alembic, Identity Platform auth with server-set claims, GCS signed-URL storage,
  Resend notification-only mail, NL/FR/EN i18n, Cloud Run SSR frontend.
- Tenant isolation as a first-class deliverable: RLS + API-layer scoping, CI-gated cross-tenant
  denial suite (150+ tests) that gated all downstream feature phases.
- All seven pre-research AI function ports with SSE progress and connection-safe LLM calls.

### What Worked
- Isolation-before-features ordering (Phase 4 gate) — the broken-RLS bug class never recurred.
- Author-by-construction + Cloud Build for everything (dev box has no Python/Docker) — the suite
  ran green in Cloud Build without ever running locally.
- Same-day UAT defect loops in Phase 12: 8 defects found across operator rounds, all fixed and
  deployed within hours (quick tasks + fast tasks kept commits atomic and tracked).
- Claude Design canvas round-trips for UI consistency (2 fuse cycles) before parity UAT.

### What Was Inefficient
- Deploy gaps recurred across phases (6, 8, 10, 11 executed but not deployed until later
  catch-ups) — code-complete ≠ live became a standing checklist item.
- Tracking staleness: REQUIREMENTS.md checkboxes and the ROADMAP progress table chronically
  lagged reality; had to be reconciled wholesale at milestone close (trust STATE.md).
- Human-UAT debt accumulated per-phase (HUMAN-UAT files) and was consolidated late (12-UAT);
  earlier consolidation would have shown the true open surface sooner.
- .planning/ gitignore + worktree executors caused two traps (invisible plan files, CWD drift on
  merge) that each cost a halted run.

### Patterns Established
- Human-gate override with preserved ledger: gate closed as "ACCEPTED WITH DEFERRALS" instead of
  falsely green — deferral recorded verbatim, nothing silently dropped.
- Independence-only retirement (D-08): prove zero legacy deps code-side; never touch the legacy
  system itself.
- Bundle guard in the build (D-11): CI fails the frontend image if a Supabase signature ships.

### Key Lessons
1. Make "deployed" an explicit phase exit criterion — every executed-but-not-deployed phase
   produced a confusing gap later.
2. Reconcile tracking tables at phase close, not milestone close; the sed-flip at close worked but
   only because SUMMARY frontmatter held the truth.
3. Operator UAT rounds beat checklist completeness: 3 focused live rounds surfaced 8 real defects
   that no amount of code-side verification caught.

### Cost Observations
- Model mix: opus for planning/execution, sonnet for verification/checking (per GSD profile).
- Sessions: ~15 working sessions across 33 days.
- Notable: subagent-heavy GSD flow kept orchestrator context lean; live-deploy sessions were the
  cheapest and highest-value (operator + assistant tight loop).

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Days | Notable process change |
|-----------|--------|-------|------|------------------------|
| v1.0 | 12 | 70 | 33 | First full GSD cycle; isolation-gated ordering; deferral-ledger close |
