# Roadmap: Nestor Intake (GCP Re-platform)

## Milestones

- ✅ **v1.0 GCP Re-platform** — Phases 1-12 (shipped 2026-07-20) — [archive](./milestones/v1.0-ROADMAP.md)
- 📋 **v1.1 Tribunal (deep research)** — not yet scoped; start with `/gsd-new-milestone`

## Phases

<details>
<summary>✅ v1.0 GCP Re-platform (Phases 1-12) — SHIPPED 2026-07-20</summary>

Full phase details: [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)

- [x] Phase 1: Schema & Migrations (4/4 plans)
- [x] Phase 2: Backend Skeleton & Cloud SQL Wiring (3/3 plans)
- [x] Phase 3: Identity Platform Auth (4/4 plans)
- [x] Phase 4: Tenant Isolation, Proven by Tests (4/4 plans)
- [x] Phase 5: User & Space Management (5/5 plans) — completed 2026-06-29
- [x] Phase 6: Intake CRUD Parity & Frontend API Seam (13/13 plans)
- [x] Phase 7: AI Function Ports (11/11 plans) — completed 2026-07-13
- [x] Phase 8: SSE Skill-Run Progress (3/3 plans) — completed 2026-07-13
- [x] Phase 9: GCS Storage (4/4 plans) — completed 2026-07-13
- [x] Phase 10: Notifications (5/5 plans) — completed 2026-07-14
- [x] Phase 11: Internationalization NL/FR/EN (9/9 plans) — completed 2026-07-14
- [x] Phase 12: Frontend Deploy, Cutover & Supabase Independence (5/5 plans) — completed 2026-07-20

**Close-out note:** parity gate closed as **PARITY ACCEPTED WITH DEFERRALS** (operator decision
2026-07-20) — 21 UAT items + 9 human_needed verifications deferred to post-Tribunal; ledger in
`phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md` and STATE.md Deferred Items.
Supabase retirement = independence-only (D-08): zero Supabase deps in the new stack; the legacy
project is deliberately left untouched.

</details>

### 📋 v1.1 Tribunal (planned — not yet scoped)

The deep-research track: port `run-research` off Supabase, research artifacts pipeline, and lift
the `decomposed` scope ceiling. Scope via `/gsd-new-milestone`.

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1-12 (all) | v1.0 | 70/70 | Complete (shipped) | 2026-07-20 |
