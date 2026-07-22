# Phase 17: Raw Output + Audit Chain Guard - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Once a research run completes, its full raw output is secured as a superadmin-only, space-scoped
download (GCS signed URL), and `verify_chain` runs as a hard gate on the run-completion path so a
broken audit chain surfaces before anything can leave the system. Nothing research-related is ever
client-visible (REPORT-02 rule, absolute).

Requirement: RUN-03.

**Out of scope:** report upload/delivery (Phase 18), Q&A chat / findings indexing (Phase 19),
surfacing the `verification_report` as a client-trust artifact in the UI (FUT-01), engine
enhancements (Phase 15, deferred), any client-facing surface, run cancel/stop.

**Builds directly on Phase 16:** the completion summary card (16 D-09) is the anchor the download
button and the chain-state UI land on; the poll driver's finalize step is the completion-path hook
where materialization and the verify_chain gate run.

**Note:** Phase 16's live UAT is still parked on an external blocker (Anthropic credits). This
phase can be planned and built against the `fake_tribunal_client` fixture; its live proof needs a
completed run, same checkpoint pattern as 16-05.

</domain>

<decisions>
## Implementation Decisions

### Download contents & format (what "full raw output" means)
- **D-01 (bundle = report + scrubbed research + sources; NO rejected claims):** The download
  contains the final report, the scrubbed per-provider deep-research reports (the
  `cleaned_reports` from the engine's synthesis cache — passages supporting dropped claims are
  already physically removed), and the sources. The rejected-claims ledger is EXCLUDED — the
  download never exposes discredited content.
- **D-02 (sources per claim):** Sources are exported as the claim→source evidence trail
  (verified claims with their backing source URLs, structured JSON from the `claim`/
  `claim_source`/`source` tables) — not a flat URL list.
- **D-03 (zip of separate files):** One zip: `report.md` + `research/<angle>.md` per provider
  report + `sources.json`. Each piece usable standalone (e.g. `report.md` feeds Claude Design
  for the Phase-18 client PDF). Exact file naming/layout = builder discretion.

### Storage & materialization
- **D-04 (materialize at completion):** The Phase-16 poll driver's finalize step fetches the
  pieces via the seam and writes the zip to GCS ONCE at run completion. Download clicks only
  mint a signed URL — fast, immutable snapshot, independent of Tribunal availability later.
- **D-05 (intake app bucket):** Bundles live in the existing Phase-9 uploads bucket under
  space-scoped paths — raw output is an app artifact like context packs; reuses existing
  storage plumbing + IAM. NOT the 7-year audit bucket. Signed-URL TTL = builder discretion.

### Audit chain guard (verify_chain on the completion path)
- **D-06 (broken chain → complete-but-locked):** If `verify_chain` fails at completion, the run
  still records as completed but carries a loud "audit chain broken" flag and the raw-output
  download is BLOCKED until resolved. Completed research is never thrown away, and nothing
  leaves the system on a broken chain (EU AI Act Art. 12 posture).
- **D-07 (UI state only):** The broken-chain state is surfaced as a distinct error state on the
  run summary card — NO dedicated email variant. The normal Phase-16 completion mail behavior
  is unchanged.
- **D-08 (re-verify button):** The locked card offers a re-verify action that re-runs
  `verify_chain`; if it now passes (transient issue) the lock lifts, if it still fails the lock
  stays and investigation is manual (logs/DB).

### Failed-run access
- **D-09 (completed-only):** Download exists ONLY for green (chain-verified) completed runs.
  Failed runs keep the Phase-16 failure state + re-trigger; no partial/unverified content is
  ever exported.

### Locked by prior phases (do not re-decide)
- Download button + chain state live on the Phase-16 completion summary card (16 D-09).
- Client can NEVER access anything research-related (REPORT-02 + out-of-scope table).
- Endpoint is superadmin-only, space-scoped, added to the CI-gated cross-tenant denial suite
  from day one (standing v1.1 isolation rule).
- The frozen audit `canonical_json` payload must not gain/rename fields (14 D-05);
  `verify_chain` green is the ENGINE-04 legal gate (deadline 2026-08-02).

### Claude's Discretion
- Where `verify_chain` physically runs (tribunal-side seam endpoint called by the finalize step
  vs. worker-side check) — under the constraint that the intake poll driver is the completion
  hook and the result must land in the intake-side run state.
- How the chain-verified/locked state is stored on the intake side (e.g. column(s) on
  `research_runs`) and its SSE/UI wire shape.
- Bundle assembly mechanics (which seam endpoints serve cleaned_reports + claim/source exports —
  new tribunal endpoints are acceptable; they follow the D-03/D-04 Phase-14 internal-auth rules).
- Signed-URL TTL, zip layout details, file naming, bundle language handling.
- Whether downloads are audit-logged intake-side (recommended: reuse the existing audit/event
  pattern if cheap).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Engine output shape (what the bundle is built from)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — run result shape: `output_text`
  (final report md incl. deterministic Verification appendix), `synthesis_cache` Output row
  (mission_brief + `cleaned_reports` + verification stats), `rejected_claims` (EXCLUDED from
  bundle per D-01), `verification_report` (returned but NOT persisted — FUT-01)
- `tribunal/nestor_pulse_sdk/runs/worker.py` — worker persists Output rows `'markdown'` +
  `'rejected_claims'` only; completion path this phase's gate must not break
- `tribunal/nestor_pulse_sdk/db/models/output.py` — Output model (`format`, `gcs_uri` fields)
- `tribunal/nestor_pulse_sdk/db/models/claim.py` + `claim_source.py` + `source.py` — the
  claim→source evidence trail D-02 exports
- `tribunal/nestor_pulse_sdk/runs/api.py` — existing `GET /{run_id}/report` (line ~852) the
  seam already consumes; pattern for any new bundle endpoints

### Audit chain (the guard)
- `tribunal/nestor_pulse_sdk/audit/verifier.py` — `verify_chain` implementation (the gate)
- `tribunal/nestor_pulse_sdk/audit/api.py` — existing audit HTTP surface (candidate home for a
  seam verify endpoint)
- `tribunal/nestor_pulse_sdk/audit/hash_chain.py` — frozen canonical payload rules (14 D-05
  constraint)

### Intake side (where the new code lands)
- `backend/app/research/run_task.py` — the Phase-16 poll driver whose finalize step is the
  completion hook (D-04, D-06). CRITICAL: carries the commit-before-schedule fix (11e3043),
  row-id idempotency key (721086d), and load-bearing WARNING/ERROR diagnostics (615b6bc) — do
  not regress these
- `backend/app/research/tribunal_client.py` — the seam client (OIDC + acting-user headers) to
  extend with bundle/verify methods
- `backend/app/db/models/research.py` — `research_runs` model the lock/chain state extends
- `backend/app/storage/gcs.py` + `backend/app/storage/keys.py` — Phase-9 GCS plumbing (D-05
  bucket, signed URLs, space-scoped key conventions)
- `backend/tests/test_intake_cross_tenant.py` — denial-suite pattern the download endpoint
  joins from day one

### Frontend
- `frontend/src/components/intake/ResearchRunProgress.tsx` — the Phase-16 panel + summary card
  (16 D-09) the download button, chain-locked state, and re-verify action extend
- `frontend/src/lib/research.ts` — Phase-16 API layer to extend

### Planning context
- `.planning/phases/16-research-trigger-progress-bridge/16-CONTEXT.md` — D-09 summary card
  anchor, poll-driver architecture, decisions carried forward
- `.planning/phases/16-research-trigger-progress-bridge/.continue-here.md` — live deploy state,
  the three fixed root causes, deferred follow-ups (apiFetch POST retry, pool sizing, driver
  out of BackgroundTasks) that touch the same finalize path
- `.planning/ROADMAP.md` § Phase 17 — goal + 3 success criteria
- `.planning/REQUIREMENTS.md` — RUN-03

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Poll driver finalize step (`run_task.py`) — the exact completion hook for materialize + gate;
  already runs in a committed tenant_session with diagnostics.
- `tribunal_client.py` — OIDC/acting-user machinery ready; add get-bundle-pieces + verify-chain
  methods.
- Phase-9 GCS module (`storage/gcs.py`) — upload + signed-URL generation with space-scoped keys.
- `fake_tribunal_client` fixture (16-01) — test seam without live engine/credits.
- Phase-16 SSE stream + `ResearchRunProgress` panel — chain/lock state rides the existing
  research-run wire format.

### Established Patterns
- Backend handlers sync `def` on pg8000; SSE streams are the deliberate `async def` exceptions.
- Every new read/write goes through the space-scoped session + cross-tenant denial tests.
- Seam is HTTP-only, internal-auth (Phase 14 D-04/D-05); new tribunal endpoints follow it.
- Deploys by-construction + operator runbook; Cloud Build for images/tests (no local
  Python/Docker).

### Integration Points
- Poll driver finalize (completed detected) → verify_chain via seam → fetch report +
  cleaned_reports + claim/source export → zip → GCS write → research_runs row updated
  (chain state + bundle ref) → SSE → summary card.
- Download endpoint: superadmin-only route → space-scoped lookup → signed URL (302/JSON).
- Re-verify endpoint: superadmin-only → seam verify_chain → update chain state.

</code_context>

<specifics>
## Specific Ideas

- "Full bundle without the rejected claims, but the output of the research filtered from dropped
  claims + sources" — the founding decision of this phase: the operator wants everything the
  engine produced that SURVIVED verification; discredited content stays internal (D-01).
- The engine's `cleaned_reports` (subtractive-verification scrub) is precisely "research filtered
  from dropped claims" — reuse it, don't re-derive.
- report.md standalone in the zip because it feeds Claude Design for the Phase-18 client PDF.

</specifics>

<deferred>
## Deferred Ideas

- **Surface `verification_report` in the UI as a client-trust artifact** — FUT-01, already
  tracked; the dict is currently returned but not persisted (worker writes only markdown +
  rejected_claims). If persisting it is trivial while touching the completion path, note it for
  FUT-01 but do NOT scope UI work here.
- **Broken-chain email variant** — operator chose UI-only (D-07); revisit if a real broken-chain
  incident ever occurs.
- **Partial output download for failed runs** — rejected for v1.1 (D-09).

</deferred>

---

*Phase: 17-Raw Output + Audit Chain Guard*
*Context gathered: 2026-07-22*
