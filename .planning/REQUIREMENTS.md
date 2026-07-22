# Requirements: Nestor Intake — v1.1 Tribunal Integration

**Defined:** 2026-07-20
**Core Value:** A logged-in superadmin can run a full deep-research cycle on a decomposed intake — Tribunal research, human-crafted report delivery, and client Q&A over the findings — on the same GCP platform, with every client's data isolated to its own space and the legally required audit trail intact.

## v1.1 Requirements

Requirements for this milestone. Each maps to roadmap phases.

### Engine Re-home (ENGINE)

- [x] **ENGINE-01**: Tribunal API + worker run as Cloud Run services in the intake GCP project, with a `tribunal` schema on the shared Cloud SQL instance and Tribunal's own Alembic migration line intact
- [x] **ENGINE-02**: One real research run completes end-to-end green on the new deployment before dependent features build on it
- [ ] **ENGINE-03**: The per-run cost cap is re-enabled for client runs (dev `NESTOR_TRIBUNAL_UNCAPPED` flag off) and the stale-run reclaim window is calibrated above the real max run length (no double-runs)
- [x] **ENGINE-04**: The tamper-evident audit hash-chain verifies green (`verify_chain`) after the move — **blocking gate, before 2026-08-02 (EU AI Act Art. 12 enforcement)**
- [ ] **ENGINE-05**: A plan-critique pass reviews the research plan before the multi-provider fan-out launches (frontier idea A2)
- [ ] **ENGINE-06**: Competing report drafts are ranked pairwise (tournament) and the winner becomes the run's report (frontier idea A1)
- [ ] **ENGINE-07**: Research runs execute via the queue + always-on worker model (never inside an HTTP request), so runs of any length are immune to Cloud Run request timeouts
- [x] **ENGINE-08**: Multiple research runs from different clients run concurrently without interference — per-run audit-chain advisory lock added (completing Tribunal's unexecuted concurrency plan 01-19), proven by a test of ≥2 simultaneous runs from different spaces

### Integration Seam (SEAM)

- [x] **SEAM-01**: Tribunal's standalone logins/orgs/UI are retired; only the intake backend can call it (server-to-server internal auth)
- [x] **SEAM-02**: Intake spaces map 1:1 onto Tribunal orgs; every run is space-scoped end-to-end (cross-tenant denial suite extended to Tribunal data)
- [ ] **SEAM-03**: Superadmin can trigger a research run on a `decomposed` intake (status → `in_research`), with the brief assembled from the intake's validated context pack
- [ ] **SEAM-04**: Runs auto-proceed through Tribunal's interactive pauses (`needs_input` / `needs_report_spec`) with sensible defaults (zero-touch)

### Run Experience (RUN)

- [ ] **RUN-01**: Superadmin sees live run progress (stages + running cost) on the intake detail page, in the intake design language
- [ ] **RUN-02**: Superadmin receives an email when the run completes or fails
- [ ] **RUN-03**: Superadmin can download the full raw research output as a file; clients can never access it

### Report Delivery (REPORT)

- [x] **REPORT-01**: Superadmin can upload the final report PDF (crafted externally in Claude Design) → status `delivered`
- [x] **REPORT-02**: Client sees and downloads the final report in their UI; nothing research-related is client-visible before delivery
- [x] **REPORT-03**: Client receives an email notification when the report is delivered

### Q&A Chat (CHAT)

- [ ] **CHAT-01**: Research findings are chunked and embedded (Voyage `voyage-3-large`, dedicated 1024-dim pgvector table) when a run completes
- [ ] **CHAT-02**: Client + superadmin can ask questions post-delivery and get Claude Haiku answers grounded only in the indexed findings (legacy `ask-research` contract: Belgian-Dutch, no markdown, honest when context is insufficient)
- [ ] **CHAT-03**: Chat is space-scoped; superadmin additionally sees the source fragments behind each answer

### Milestone Closing (CLOSE)

- [ ] **CLOSE-01**: The 21-item deferred v1.0 UAT ledger is re-run on the extended flow
- [ ] **CLOSE-02**: Chores done: Resend key rotation, Cloud Build suite rerun, NDA PDF drop + image rebuild, legacy `VITE_SUPABASE_*` env cleanup
- [ ] **CLOSE-03**: The 3 open product decisions decided + implemented (Templates page visibility, Intake-info link-row trimming, "Verzonden mails" history block)

## Future Requirements

Deferred to a later milestone. Tracked but not in current roadmap.

### Frontier / Engine

- **FUT-01**: A4 provenance bundle — surface the per-run `verification_report` (currently audit-only) in the UI as a client-trust artifact
- **FUT-02**: Surface Tribunal's mid-run pauses (`needs_input` / `needs_report_spec`) interactively in the admin UI instead of auto-proceed

### Roles

- **FUT-03**: client-admin role (deferred since v1.0)

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Porting legacy `run-research.ts` (SerpAPI/SearchAPI/Apify) | Research verdict: fully superseded by Tribunal; only trivial edge-case losses (hardcoded Maps-reviews/competitor crawls) |
| Tribunal as a standalone product (own logins/orgs/UI) | Decision: absorbed into the intake platform; standalone app retired |
| Migrating data from Tribunal's dev Cloud SQL (`nestor-prod-pg`) | Dev-round data; start empty in the intake project (mirrors v1.0 empty-start decision) |
| Cloud Run Jobs re-architecture for runs | Existing queue + always-on worker already solves timeouts; Jobs would be a rewrite for no gain |
| Hypothesis-evolution loops, diversity clustering, test-time compute self-play | Frontier comparison verdict: solve open-ended discovery problems Tribunal doesn't have; self-play conflicts with the hard USD cap |
| Merging Tribunal's schema/tables into the intake `nestor` schema | Alembic revision-ID collision + GUC mismatch make it high-risk; separate `tribunal` schema chosen |
| Client access to raw research output or run progress | Product decision: client sees nothing until the final PDF is delivered |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| ENGINE-01 | Phase 13 | Complete |
| ENGINE-02 | Phase 13 | Complete |
| ENGINE-04 | Phase 13 | Complete |
| ENGINE-08 | Phase 13 | Complete |
| SEAM-01 | Phase 14 | Complete |
| SEAM-02 | Phase 14 | Complete |
| ENGINE-05 | Phase 15 | Pending |
| ENGINE-06 | Phase 15 | Pending |
| SEAM-03 | Phase 16 | Pending |
| SEAM-04 | Phase 16 | Pending |
| RUN-01 | Phase 16 | Pending |
| RUN-02 | Phase 16 | Pending |
| ENGINE-03 | Phase 16 | Pending |
| ENGINE-07 | Phase 16 | Pending |
| RUN-03 | Phase 17 | Pending |
| REPORT-01 | Phase 18 | Complete |
| REPORT-02 | Phase 18 | Complete |
| REPORT-03 | Phase 18 | Complete |
| CHAT-01 | Phase 19 | Pending |
| CHAT-02 | Phase 19 | Pending |
| CHAT-03 | Phase 19 | Pending |
| CLOSE-01 | Phase 20 | Pending |
| CLOSE-02 | Phase 20 | Pending |
| CLOSE-03 | Phase 20 | Pending |

**Coverage:**
- v1.1 requirements: 24 total
- Mapped to phases: 24
- Unmapped: 0 ✓

**Per-phase requirement counts:**
- Phase 13 (Tribunal Re-home + Infra Baseline): 4 — ENGINE-01, ENGINE-02, ENGINE-04, ENGINE-08
- Phase 14 (Auth Retirement + Integration Seam): 2 — SEAM-01, SEAM-02
- Phase 15 (Engine Enhancements): 2 — ENGINE-05, ENGINE-06
- Phase 16 (Research Trigger + Progress Bridge): 6 — SEAM-03, SEAM-04, RUN-01, RUN-02, ENGINE-03, ENGINE-07
- Phase 17 (Raw Output + Audit Chain Guard): 1 — RUN-03
- Phase 18 (Human Report Upload + Client Delivery): 3 — REPORT-01, REPORT-02, REPORT-03
- Phase 19 (Q&A Chat): 3 — CHAT-01, CHAT-02, CHAT-03
- Phase 20 (Deferred Chores + v1.0 UAT Closure): 3 — CLOSE-01, CLOSE-02, CLOSE-03

---
*Requirements defined: 2026-07-20*
*Last updated: 2026-07-20 after roadmap creation (traceability populated, 24/24 mapped across Phases 13-20)*
