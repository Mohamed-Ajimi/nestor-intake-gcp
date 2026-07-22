# Phase 17: Raw Output + Audit Chain Guard - Research

**Researched:** 2026-07-22
**Domain:** Cross-codebase feature — intake `backend/` (sync pg8000/FastAPI) ⇄ Tribunal `tribunal/nestor_pulse_sdk/` (async asyncpg/FastAPI), integrated HTTP-only through the Phase-14 seam. Bundle materialization (GCS zip), audit-chain verification gate, superadmin-only space-scoped download.
**Confidence:** HIGH — every claim below is grounded in a file read this session; the two `[ASSUMED]` items are flagged in the Assumptions Log.

## Summary

Phase 17 secures a completed run's full raw output as a superadmin-only, space-scoped GCS download and hard-gates the run-completion path on `verify_chain`. Almost all the source data already exists and is already served by existing Tribunal endpoints — the work is **assembly + storage + a guard**, not new engine logic. Specifically: the final report markdown is already served by `GET /api/runs/{run_id}/report` (which ALSO returns the claim→source trail, D-02) and is already mirrored onto `research_runs.output_markdown` by the Phase-16 poll driver; the scrubbed per-provider research (`cleaned_reports`, D-01) already lives in the per-run `synthesis_cache` Output row; and `verify_chain` is already an HTTP endpoint at `GET /api/audit/verify/{run_id}` that the seam can call with its existing header machinery. The two genuinely NEW Tribunal seam surfaces are (a) an endpoint that returns the `synthesis_cache` `cleaned_reports` (no existing endpoint exposes them for the seam), and (b) a thin seam-client wrapper over the existing verify endpoint.

The materialization (D-04) slots into the Phase-16 poll driver's `finalize_completed` WRITE step (`backend/app/research/run_task.py`), which already runs in a fresh committed `tenant_session` and already fetches `get_report`. The bundle build (fetch cleaned_reports → build in-memory zip via stdlib `zipfile` → `gcs.upload_object`) and the `verify_chain` call must happen there — but **crucially outside the DB session** (the pool-starvation contract: no pooled connection held across GCS/seam I/O), and must be **idempotent/recoverable** because the in-process driver dies on Cloud Run deploys/restarts (a known, still-open Phase-16 deferral). The recommended recovery mechanism is **build-on-download-if-missing**: the download endpoint materializes the bundle lazily if the completion-path build never ran or was interrupted.

**Primary recommendation:** Reuse the existing `GET /api/runs/{id}/report` (report + sources) verbatim; add ONE new Tribunal seam endpoint for `cleaned_reports`; call the existing `GET /api/audit/verify/{run_id}` for the guard; extend `research_runs` with `chain_status` + `bundle_key` columns (migration 0012); build the zip with stdlib `zipfile` into GCS under the existing Phase-9 space-scoped key convention; store the bundle build in `finalize_completed` guarded by verify_chain, with a build-on-download-if-missing fallback for driver-death recovery; add a superadmin-only, space-scoped download endpoint + a re-verify endpoint, both landing in the CI-gated cross-tenant denial suite from day one.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Download contents & format:**
- **D-01 (bundle = report + scrubbed research + sources; NO rejected claims):** The download contains the final report, the scrubbed per-provider deep-research reports (the `cleaned_reports` from the engine's synthesis cache — passages supporting dropped claims are already physically removed), and the sources. The rejected-claims ledger is EXCLUDED — the download never exposes discredited content.
- **D-02 (sources per claim):** Sources are exported as the claim→source evidence trail (verified claims with their backing source URLs, structured JSON from the `claim`/`claim_source`/`source` tables) — not a flat URL list.
- **D-03 (zip of separate files):** One zip: `report.md` + `research/<angle>.md` per provider report + `sources.json`. Each piece usable standalone (e.g. `report.md` feeds Claude Design for the Phase-18 client PDF). Exact file naming/layout = builder discretion.

**Storage & materialization:**
- **D-04 (materialize at completion):** The Phase-16 poll driver's finalize step fetches the pieces via the seam and writes the zip to GCS ONCE at run completion. Download clicks only mint a signed URL — fast, immutable snapshot, independent of Tribunal availability later.
- **D-05 (intake app bucket):** Bundles live in the existing Phase-9 uploads bucket under space-scoped paths — raw output is an app artifact like context packs; reuses existing storage plumbing + IAM. NOT the 7-year audit bucket. Signed-URL TTL = builder discretion.

**Audit chain guard:**
- **D-06 (broken chain → complete-but-locked):** If `verify_chain` fails at completion, the run still records as completed but carries a loud "audit chain broken" flag and the raw-output download is BLOCKED until resolved. Completed research is never thrown away, and nothing leaves the system on a broken chain (EU AI Act Art. 12 posture).
- **D-07 (UI state only):** The broken-chain state is surfaced as a distinct error state on the run summary card — NO dedicated email variant. The normal Phase-16 completion mail behavior is unchanged.
- **D-08 (re-verify button):** The locked card offers a re-verify action that re-runs `verify_chain`; if it now passes (transient issue) the lock lifts, if it still fails the lock stays and investigation is manual (logs/DB).

**Failed-run access:**
- **D-09 (completed-only):** Download exists ONLY for green (chain-verified) completed runs. Failed runs keep the Phase-16 failure state + re-trigger; no partial/unverified content is ever exported.

**Locked by prior phases (do not re-decide):**
- Download button + chain state live on the Phase-16 completion summary card (16 D-09).
- Client can NEVER access anything research-related (REPORT-02 + out-of-scope table).
- Endpoint is superadmin-only, space-scoped, added to the CI-gated cross-tenant denial suite from day one (standing v1.1 isolation rule).
- The frozen audit `canonical_json` payload must not gain/rename fields (14 D-05); `verify_chain` green is the ENGINE-04 legal gate (deadline 2026-08-02).

### Claude's Discretion
- Where `verify_chain` physically runs (tribunal-side seam endpoint called by the finalize step vs. worker-side check) — under the constraint that the intake poll driver is the completion hook and the result must land in the intake-side run state.
- How the chain-verified/locked state is stored on the intake side (e.g. column(s) on `research_runs`) and its SSE/UI wire shape.
- Bundle assembly mechanics (which seam endpoints serve cleaned_reports + claim/source exports — new tribunal endpoints are acceptable; they follow the D-03/D-04 Phase-14 internal-auth rules).
- Signed-URL TTL, zip layout details, file naming, bundle language handling.
- Whether downloads are audit-logged intake-side (recommended: reuse the existing audit/event pattern if cheap).

### Deferred Ideas (OUT OF SCOPE)
- **Surface `verification_report` in the UI as a client-trust artifact** — FUT-01. If persisting it is trivial while touching the completion path, note it for FUT-01 but do NOT scope UI work here.
- **Broken-chain email variant** — operator chose UI-only (D-07).
- **Partial output download for failed runs** — rejected for v1.1 (D-09).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RUN-03 | Superadmin can download the full raw research output as a file; clients can never access it | Download endpoint pattern (Standard Stack + Architecture); superadmin-only enforcement via `get_superadmin_engine` role check; space-scoped bundle key (`build_object_key`); denial-suite pattern (`test_research_cross_tenant.py`); the three success criteria map to: (1) download endpoint → signed URL, (2) denial suite entry, (3) `verify_chain` gate in `finalize_completed`. |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Fetch final report markdown | Tribunal API (existing `GET /{run_id}/report`) | Intake poll driver (consumer) | Report is a Tribunal-owned Output row; seam already consumes it |
| Fetch claim→source trail (D-02) | Tribunal API (existing `GET /{run_id}/report` returns `sources`) | Intake poll driver | Already joined + returned by the report endpoint; no new endpoint needed |
| Fetch scrubbed `cleaned_reports` (D-01) | Tribunal API (NEW seam endpoint) | Intake poll driver | Lives in `synthesis_cache` Output row; no existing seam endpoint exposes it |
| Run `verify_chain` (the guard) | Tribunal API (existing `GET /api/audit/verify/{run_id}`) | Intake poll driver (caller) | Audit chain data + RLS are Tribunal-side; server-side recompute only (D-13) |
| Build the zip bundle | Intake backend (poll driver finalize) | — | Assembly of seam-fetched pieces; must NOT hold a DB connection |
| Store the bundle | Intake backend → GCS (Phase-9 `gcs.upload_object`) | — | D-05: intake app bucket, space-scoped key |
| Persist chain/lock/bundle state | Intake backend `research_runs` | — | D-06/D-08: lock state must land intake-side (drives the UI) |
| Mint signed download URL | Intake backend (Phase-9 `gcs.signed_download_url`) | — | Space-scoped, superadmin-only route |
| Download button + lock/re-verify UI | Frontend (React, admin-only) | — | On the Phase-16 completion summary card (16 D-09); admin route only |

## Standard Stack

### Core (all already present — no new packages)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `zipfile` (Python stdlib) | 3.x | Build the D-03 zip in-memory | Zero-dependency, well-understood; bundle is small text (see size estimate) |
| `io.BytesIO` (Python stdlib) | 3.x | In-memory buffer for the zip bytes → `gcs.upload_object` | Avoids temp files on Cloud Run's ephemeral FS |
| `google-cloud-storage` | (pinned, Phase-9) | Upload bundle + mint V4 signed URL | Already the ONLY GCS seam (`app/storage/gcs.py`); ADC keyless signing |
| `httpx` | (pinned, Phase-14/16) | Seam calls (new cleaned_reports GET + verify GET) | `tribunal_client.py` already uses blocking `httpx` + `raise_for_status` |
| `sqlalchemy` | (pinned) | `research_runs` model + migration 0012 | Existing ORM |
| `alembic` | (pinned) | Migration 0012 (chain/bundle columns) | Head is 0011; next is 0012 |

**No new third-party dependencies are required for this phase.** The Package Legitimacy Audit is therefore N/A (see below).

### Supporting (existing helpers to reuse — do NOT re-implement)
| Helper | Location | Purpose |
|--------|----------|---------|
| `gcs.upload_object(key, data, content_type)` | `backend/app/storage/gcs.py:73` | Upload the zip bytes |
| `gcs.signed_download_url(key, ttl_seconds, filename, content_type)` | `backend/app/storage/gcs.py:83` | Mint V4 signed GET (attachment disposition, TTL clamped ≤900s) |
| `build_object_key(space_id, intake_id, category, filename)` | `backend/app/storage/keys.py:90` | Server-authored space-scoped key |
| `tribunal_client._headers(...)` / `_mint_id_token(...)` | `backend/app/research/tribunal_client.py:59,69` | OIDC + acting-user + tenant headers for the new seam calls |
| `tenant_session(identity)` | `backend/app/db/ai_session.py` | Fresh committed write tx with GUC re-issued |
| `ResearchRunRepository` | `backend/app/db/repository.py:463` | Scoped read/patch of `research_runs` |
| `get_superadmin_engine()` role gate | `backend/app/db/session.py:60` | Superadmin cross-tenant reach (0003 bypass) |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| stdlib `zipfile` | A streaming zip lib | Unnecessary: bundle is small (KB–low-MB of text); stdlib in-memory is simpler and dependency-free |
| Build at completion (D-04) | Build on every download | D-04 locked this: build once, immutable snapshot, independent of later Tribunal availability. (Keep a build-on-download-if-missing FALLBACK for driver-death recovery — not the primary path.) |
| New `cleaned_reports` seam endpoint | Fetch the `synthesis_cache` Output row directly from Tribunal's DB | Forbidden by the seam contract (HTTP-only, internal-auth; intake never shares Tribunal's session — Pitfall 2). A new endpoint is the correct, locked-decision-compatible path. |

**Installation:** None. All packages are already in the backend image (`google-cloud-storage`, `httpx`, `sqlalchemy`, `alembic` — verified present via existing Phase-9/14/16 code that imports them).

**Version verification:** Not applicable — no new packages. Existing pins are the source of truth; `google-cloud-storage` keyless-signing kwargs are already validated by the live Phase-9 endpoints (`create_signed_url` in `storage_routes.py`).

## Package Legitimacy Audit

**N/A — this phase installs NO external packages.** All functionality is built from Python stdlib (`zipfile`, `io`) plus already-installed, already-in-production dependencies (`google-cloud-storage`, `httpx`, `sqlalchemy`, `alembic`). No slopcheck / registry verification is required because nothing new is added to the dependency graph.

## Architecture Patterns

### System Architecture Diagram

```
                          RUN COMPLETION (Phase-16 poll driver, run_task.py)
                                          │
                     metrics.status == "completed"  (write_fn, terminal branch)
                                          │
        ┌─────────────────────────────────┼─────────────────────────────────┐
        │  STEP A — GATE (no DB conn held) │  STEP B — FETCH (no DB conn held) │
        │  seam: GET /api/audit/verify/    │  seam: GET /{id}/report  ────────►│ report.md
        │        {tribunal_run_id}         │        (already fetched today)     │ + sources (D-02)
        │  → {ok, broken_at}               │  seam: GET /{id}/research-bundle ─►│ cleaned_reports (D-01, NEW)
        └──────────────┬──────────────────┴────────────────┬─────────────────┘
                       │                                    │
              chain_status =                        BUILD ZIP (zipfile, in-memory)
          "verified" | "broken"                     report.md
                       │                             research/<angle>.md × N
                       │                             sources.json
                       ▼                                    │
         ┌──────────── if verified ────────────────────────┤
         │                                                  ▼
         │                                  gcs.upload_object(bundle_key, zip_bytes)
         │                                  bundle_key = build_object_key(space, intake, "artifacts", ...)
         │                                                  │
         └──────────────────────► STEP C — PERSIST (fresh committed tenant_session) ◄─────┘
                                  research_runs.patch(chain_status=..., bundle_key=...)
                                          │
                                          ▼
                    SSE stream (existing) ──► ResearchRunProgress summary card
                       │                          ├─ verified → [Download] button
                       │                          └─ broken   → 🔒 locked + [Re-verify]
                       │
         ┌─────────────┴──────────────────────────────────────────────────┐
         │  DOWNLOAD  GET /intakes/{id}/research/{run_id}/bundle-url        │
         │  superadmin-only → space-scoped run lookup → if bundle_key null  │
         │  AND chain verified: build-on-download-if-missing (recovery) →   │
         │  gcs.signed_download_url(bundle_key) → {url, expires_in}         │
         ├─────────────────────────────────────────────────────────────────┤
         │  RE-VERIFY POST /intakes/{id}/research/{run_id}/verify-chain     │
         │  superadmin-only → seam verify → patch chain_status → 200        │
         └─────────────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| Bundle builder | Assemble zip from report + cleaned_reports + sources | NEW `backend/app/research/bundle.py` (recommended — keeps `run_task.py` slim + unit-testable) |
| `finalize_completed` extension | Call gate + build + upload OUTSIDE the DB session; persist chain_status + bundle_key | `backend/app/research/run_task.py:149` |
| New seam methods | `get_research_bundle` (cleaned_reports), `verify_chain` | `backend/app/research/tribunal_client.py` |
| New Tribunal endpoint | `GET /api/runs/{run_id}/research-bundle` → `{cleaned_reports}` | `tribunal/nestor_pulse_sdk/runs/api.py` |
| `research_runs` extension | `chain_status`, `chain_broken_at`, `bundle_key` columns | `backend/app/db/models/research_runs.py` + migration 0012 |
| Download + re-verify routes | superadmin-only, space-scoped | `backend/app/api/research_routes.py` (extend) |
| Frontend | Download button, locked state, re-verify action, SSE fields | `frontend/src/components/intake/ResearchRunProgress.tsx` + `frontend/src/lib/api/research.ts` |

### Recommended Project Structure (delta only)
```
backend/app/research/
├── run_task.py          # EXTEND finalize_completed (gate + build + persist)
├── tribunal_client.py   # ADD get_research_bundle() + verify_chain()
└── bundle.py            # NEW: build_bundle_zip(report, cleaned_reports, sources) -> bytes (pure, unit-testable)
backend/app/db/models/research_runs.py   # ADD chain_status / chain_broken_at / bundle_key
backend/app/db/alembic/versions/0012_research_run_chain_bundle.py   # NEW migration
backend/app/api/research_routes.py       # ADD bundle-url + verify-chain routes
tribunal/nestor_pulse_sdk/runs/api.py    # ADD GET /{run_id}/research-bundle
frontend/src/lib/api/research.ts         # ADD getBundleUrl() + reVerifyChain() + extend ResearchRun type
frontend/src/components/intake/ResearchRunProgress.tsx  # download / lock / re-verify UI
```

### Pattern 1: Gate + build + upload OUTSIDE the DB session (pool-safety contract)
**What:** `verify_chain` (seam HTTP) and the GCS upload must NOT run while a pooled DB connection is held — same contract as the Phase-16 driver (T-16-06) and the explicit `.continue-here.md` warning: "bundle build should not hold DB connections while doing GCS I/O."
**When to use:** In the poll driver's completion branch.
**How:** The `write_fn` in `run_task.py` currently opens the fresh `tenant_session` and does the report fetch + finalize INSIDE it. Restructure so the **seam fetches + zip build + GCS upload happen BEFORE opening the finalize `tenant_session`** (or in the CALL phase's tail), and the session is opened ONLY to patch the row with the results. The existing `run_with_session_release` structure (READ → CALL-no-conn → WRITE) already models this — the bundle work belongs in the CALL tail (no connection) and only the column patch belongs in WRITE.
```python
# Source: pattern derived from backend/app/research/run_task.py:348 (write_fn) + :318 (conn-free CALL loop)
# In the completed branch, do this ORDER:
#   1. report = tribunal_client.get_report(...)          # seam, no DB conn
#   2. bundle = tribunal_client.get_research_bundle(...)  # NEW seam, no DB conn
#   3. verdict = tribunal_client.verify_chain(...)        # NEW seam, no DB conn
#   4. if verdict["ok"]:
#          zip_bytes = build_bundle_zip(report, bundle, report["sources"])
#          key = build_object_key(space_id, intake_id, "artifacts", f"raw-output-{run_id}.zip")
#          gcs.upload_object(key, zip_bytes, content_type="application/zip")
#   5. THEN open tenant_session and patch: chain_status, chain_broken_at, bundle_key, output_markdown, status, completed_at
```

### Pattern 2: Build-on-download-if-missing (driver-death recovery)
**What:** The in-process poll driver dies on Cloud Run deploys/restarts mid-run (open Phase-16 deferral: "in-process drivers still die with deploys/restarts mid-run"). If the driver dies AFTER completion is detected but BEFORE the bundle is written, the run is `completed` but `bundle_key IS NULL`. The download endpoint must recover.
**When to use:** In the download endpoint, when `bundle_key IS NULL` on a `completed` + chain-`verified` run.
**How:** The download route, on a verified completed run with no `bundle_key`, re-runs the fetch+build+upload path (idempotent: same deterministic key or a fresh key + patch), then mints the URL. This is the safety net; the D-04 completion-path build stays the primary path.
**Why this is safe:** The pieces are immutable post-completion (report Output, synthesis_cache, audit chain never change after `completed`), so a late rebuild yields the identical bundle. Make the key deterministic per run (e.g. `.../artifacts/raw-output-{run_id}.zip`) so a double-build overwrites rather than duplicates.

### Pattern 3: verify_chain "empty chain is trivially valid" trap
**What:** `verify_chain` (`tribunal/nestor_pulse_sdk/audit/hash_chain.py:94`) returns `(True, None)` for a run with ZERO audit rows visible to the current tenant — the `for` loop over an empty list falls through to `return True, None`. The endpoint docstring confirms: "Cross-tenant run_id returns `{ok: true, broken_at: null}` on empty result (no rows visible == empty chain == trivially valid)."
**Implication for the guard:** The seam call MUST send the correct `X-Nestor-Tenant-Id` (= the intake's space_id) so the audit rows are visible. It already does (the poll driver carries `ctx["space_id"]`). But a green `ok:true` on a run that SHOULD have audit rows but shows zero is a FALSE PASS. **Recommendation:** treat `ok:true` as verified only when the run is a real completed run in the correct tenant scope (which the driver guarantees). Optionally, the new bundle/verify handling can assert the run actually produced audit calls (the report's `sources` non-empty, or a call-count check) before trusting a trivially-green verdict — flag as a hardening note, not a blocker.

### Anti-Patterns to Avoid
- **Holding a DB connection across GCS/seam I/O** — reintroduces pool starvation (T-16-06); the `.continue-here.md` explicitly warns the superadmin engine pool is tiny (size 2 + overflow 3).
- **Regressing the Phase-16 fixes** — do NOT move the finalize out of the committed `tenant_session` pattern (commit-before-schedule `11e3043`), do NOT change the row-id idempotency key (`721086d`), do NOT remove the WARNING/ERROR diagnostics (`615b6bc`). Extend the completed branch; don't restructure the driver's session discipline.
- **Adding/renaming a hashed audit field** — the `canonical_json` payload (`_payload_for_row`) is frozen (14 D-05); this phase READS the chain, never writes it. No migration touches Tribunal's `audit_log`.
- **Client-role reachability** — the download/re-verify routes must be superadmin-only; a `user`-role or cross-space request is existence-hidden 404 (never 403/200 that leaks existence — Pitfall 9).
- **Persisting the bundle to the 7-year audit bucket** — D-05 says the intake app bucket (`STORAGE_BUCKET`), NOT `AUDIT_GCS_BUCKET`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Claim→source export (D-02) | A new claim/source join query | The EXISTING `GET /{run_id}/report` which already returns `sources` (joined claim→claim_source→source, RLS-scoped) | `runs/api.py:891` already does this DISTINCT join; the driver already fetches this endpoint (`get_report`) |
| Chain verification | Recomputing hashes intake-side | The EXISTING `GET /api/audit/verify/{run_id}` | Server-side-only recompute is a hard rule (D-13, Anti-pattern line 585); client NEVER recomputes hashes |
| Signed URL minting | Constructing GCS SDK clients / V4 signing inline | `gcs.signed_download_url` | Keyless ADC signBlob, TTL clamp ≤900s, forced attachment disposition, filename sanitize — all baked in |
| Space-scoped object key | String-concatenating a path | `build_object_key(space_id, intake_id, "artifacts", name)` | Server-authored, path-traversal-proof, prefix-assertable (D-08) |
| Zip file naming safety | Trusting provider names in the zip path | `sanitize_filename` from `keys.py` for the `research/<angle>.md` names | Provider names are engine-derived; sanitize to avoid odd zip entry names |
| OIDC token for the new seam calls | New auth code | `tribunal_client._headers(...)` | Keyless OIDC mint + acting-user + tenant headers already correct (Pitfall 4 audience rule handled) |

**Key insight:** ~80% of Phase 17 is wiring existing endpoints together. The only genuinely new server surface is the `cleaned_reports` bundle endpoint on Tribunal and two thin intake routes. Resist re-deriving anything the engine already produced.

## Runtime State Inventory

> This is a feature phase, not a rename/refactor. Included for completeness because it touches live deployed services and stored run state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Existing `research_runs` rows on the live DB (smoke intake e08620c5 has 3 rows; per `.continue-here.md`). New columns (`chain_status`, `bundle_key`) will be NULL for these — migration must add them nullable with a sane default so existing rows don't break. Existing `completed` runs (once credits restored) predate bundle materialization → build-on-download-if-missing handles them. | Migration 0012 nullable columns; download fallback covers pre-existing completed runs |
| Live service config | Tribunal `tribunal-api` (rev 00007-vsf) must be redeployed with the NEW `GET /{run_id}/research-bundle` endpoint before the intake finalize path can call it. Deploy-gap risk (recurring per memory). | Runbook: rebuild + deploy tribunal-api image; intake backend image with new routes |
| OS-registered state | None. | None — verified: no Task Scheduler / cron in this stack |
| Secrets/env vars | No NEW secret. Reuses `STORAGE_BUCKET` (already set, Phase-9) and `tribunal_service_url` (already set, Phase-14/16). No `AUDIT_GCS_BUCKET` needed (D-05: app bucket, not audit bucket). | None |
| Build artifacts | New backend + tribunal-api images required (Cloud Build; dev machine has no local Python/Docker per memory). Migration 0012 runs via the `nestor-migrate` job. | Runbook: Cloud Build both images, run migrate job, deploy both revisions |

## Common Pitfalls

### Pitfall 1: The `cleaned_reports` are NOT on the report endpoint — they need a new seam endpoint
**What goes wrong:** Assuming the existing `GET /{run_id}/report` returns the scrubbed per-provider reports. It does NOT — it returns `sections` (parsed report markdown) + `sources`. The `cleaned_reports` live ONLY in the `synthesis_cache` Output row (`format='synthesis_cache'`, written by the pipeline at `pipeline.py:728`), which the worker's completion path does NOT re-expose and no seam endpoint serves.
**Why it happens:** The worker persists only `'markdown'` + `'rejected_claims'` Output rows (`worker.py:210-240`); the `synthesis_cache` row is written earlier by the pipeline for the rewrite/resume path, not for external consumption.
**How to avoid:** Add `GET /api/runs/{run_id}/research-bundle` on Tribunal that reads the latest `synthesis_cache` Output row (mirror the `_latest("synthesis_cache")` pattern at `runs/api.py:395`) and returns `{cleaned_reports: [[provider_name, {report: ...}], ...]}`. RLS-scoped via `get_db_session` (tenant from the seam's `X-Nestor-Tenant-Id`). 409 if no cache row (a completed Tribunal run always has one).
**Warning signs:** Empty `research/` directory in the zip; a `KeyError` on `cleaned_reports`.

### Pitfall 2: `verify_chain` trivially passes on an empty/wrong-tenant chain
**What goes wrong:** A verify call that returns `ok:true` because zero audit rows were visible (wrong tenant header, or a run that genuinely produced no audited calls) — a FALSE green that would let unverifiable content leave the system, defeating the D-06 legal posture.
**Why it happens:** `verify_chain` returns `(True, None)` on an empty row set by design (`hash_chain.py:120-136`).
**How to avoid:** Always send the intake's space_id as `X-Nestor-Tenant-Id` (the driver already does). Optionally cross-check that the completed run actually has audit activity (non-empty `sources`, or a call-count) before trusting `ok:true`. Document this as a hardening note.
**Warning signs:** `broken_at: null` on a run you know is real but the download is suspiciously instant / the report has no sources.

### Pitfall 3: The in-process driver dies mid-materialization
**What goes wrong:** A Cloud Run deploy/restart between "completion detected" and "bundle written" leaves a `completed` run with `bundle_key IS NULL` and no bundle — the download button is dead with no recovery.
**Why it happens:** The poll driver runs in `BackgroundTasks` on the API process (open Phase-16 deferral). Deploys are frequent in this project.
**How to avoid:** Build-on-download-if-missing (Pattern 2). Also acceptable: a re-finalize sweep, but the download-time lazy build is simplest and needs no scheduler.
**Warning signs:** Download 500s or 404s on a run whose summary card shows "completed".

### Pitfall 4: Pool starvation from GCS/seam I/O inside a held connection
**What goes wrong:** Building the zip and uploading to GCS while a `tenant_session` is open holds a pooled connection across seconds of I/O; the tiny superadmin pool (2+3) starves under a concurrent trigger → 30s QueuePool-timeout 500 (exactly the 21:44 incident in `.continue-here.md`).
**Why it happens:** Natural to put "fetch, build, save row" in one transaction.
**How to avoid:** Pattern 1 — all seam/GCS I/O outside the session; open the session ONLY to patch the row.
**Warning signs:** `QueuePool limit ... timed out`; `engine.pool.checkedout()` > 0 during the build (the existing pool-safety test in `test_research_run_task.py` is the template — add a checkedout==0 assertion across the build).

### Pitfall 5: A new tenant surface reintroduces the cross-tenant leak
**What goes wrong:** The download/re-verify endpoints leak another tenant's raw findings if not superadmin-only AND space-scoped (Pitfall 9 in PITFALLS.md — this exact endpoint is named).
**How to avoid:** Land both routes in `test_research_cross_tenant.py` from day one: (a) space-B user/superadmin → 404 on space-A's run; (b) null-space user → 403; (c) a `user`-role → 404 (existence-hidden). Mirror the existing three-test structure verbatim.
**Warning signs:** A denial test missing for a new route; a route that reads `space_id` from the request instead of the resolved run/intake.

### Pitfall 6: Regressing the load-bearing Phase-16 driver fixes
**What goes wrong:** Restructuring `write_fn` breaks commit-before-schedule, the row-id idempotency key, or removes the diagnostics — reviving the "silent driver" that cost a UAT day.
**How to avoid:** ADD to the `completed` branch; keep the `tenant_session` finalize, the idempotency key (`uuid5(intake_id, research_run_id)`), and the WARNING logs. The pool-safety test + a green run are the guard.
**Warning signs:** Panel frozen at "queued"; 0-row-patch ERROR logs; duplicate triggers.

## Code Examples

### New Tribunal seam endpoint — serve cleaned_reports (D-01)
```python
# Source: pattern cloned from tribunal/nestor_pulse_sdk/runs/api.py:384-397 (_latest synthesis_cache read)
@router.get("/{run_id}/research-bundle")
async def get_run_research_bundle(
    run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),  # tenant-scoped via X-Nestor-Tenant-Id
) -> dict:
    run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "run not found")
    if run.status != "completed":
        raise HTTPException(409, "bundle not available yet")
    body = (await session.execute(
        select(Output.body)
        .where(Output.run_id == run_id, Output.format == "synthesis_cache")
        .order_by(Output.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    if not body:
        raise HTTPException(409, "no cached research for this run")
    bundle = _json.loads(body)
    # D-01: cleaned_reports only. rejected_claims are DELIBERATELY excluded.
    return {"cleaned_reports": bundle.get("cleaned_reports") or []}
```

### New seam-client methods (intake side)
```python
# Source: cloned from backend/app/research/tribunal_client.py:211 (get_report shape) — same keyword surface + _headers
def get_research_bundle(*, service_url, space_id, acting_user_id, acting_email, run_id) -> dict:
    resp = httpx.get(
        f"{service_url}/api/runs/{run_id}/research-bundle",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()  # {cleaned_reports: [[name, {report:...}], ...]}

def verify_chain(*, service_url, space_id, acting_user_id, acting_email, run_id) -> dict:
    resp = httpx.get(
        f"{service_url}/api/audit/verify/{run_id}",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()  # {ok: bool, broken_at: int | None}
```

### Bundle builder (pure, unit-testable)
```python
# Source: Python stdlib zipfile + D-03 layout. Pure function — no I/O, no DB, no GCS.
import io, json, zipfile
from app.storage.keys import sanitize_filename

def build_bundle_zip(report: dict, bundle: dict, sources: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # report.md — standalone (feeds Claude Design for the Phase-18 PDF, D-03/specifics)
        zf.writestr("report.md", report.get("markdown") or _sections_to_md(report))
        # research/<angle>.md per scrubbed provider report (D-01)
        for name, result in (bundle.get("cleaned_reports") or []):
            safe = sanitize_filename(str(name))
            text = result.get("report") if isinstance(result, dict) else str(result)
            zf.writestr(f"research/{safe}.md", text or "")
        # sources.json — claim→source evidence trail (D-02)
        zf.writestr("sources.json", json.dumps(sources, ensure_ascii=False, indent=2))
    return buf.getvalue()
```
> Note: `get_report` returns `sections` (parsed) not raw `markdown` when called via the Tribunal endpoint (`runs/api.py:915`), BUT the poll driver's `get_report` seam contract returns `{markdown, sources}` (see `tribunal_client.py:219` + `fake_tribunal_client` returns `{"markdown": ..., "sources": []}`). The driver already persists `report.get("markdown")` onto `output_markdown` — so `output_markdown` (or the report's `markdown` key) is the report.md source. Confirm the live report endpoint returns a `markdown` key, or reconstruct from `sections`. [ASSUMED: the seam report response carries a `markdown` key — the fixture and the driver both assume it; the live `runs/api.py:915` returns `sections` not `markdown`, so a `_sections_to_md` fallback or a report-endpoint tweak may be needed. Verify against a live completed run.]

### Superadmin-only, space-scoped download route
```python
# Source: role gate from backend/app/db/session.py:60 + signed-url convention from storage_routes.py:230
@research_router.get("/{intake_id}/research/{run_id}/bundle-url")
def get_bundle_url(
    intake_id: str, run_id: str,
    repo: IntakeRepository = Depends(get_tenant_repo),  # superadmin engine or scoped user engine
    identity: Identity = Depends(get_current_identity),
) -> dict:
    # Existence-hidden: a cross-tenant/missing intake -> 404 (repo scope). run must belong to it.
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(404, "Intake not found")
    run = ResearchRunRepository(repo.session, identity).get(run_id)
    if run is None or str(run.intake_id) != str(intake_id):
        raise HTTPException(404, "Run not found")
    if run.status != "completed" or run.chain_status != "verified":
        raise HTTPException(409, "Raw output is not available (run not completed or chain not verified)")
    key = run.bundle_key
    if key is None:
        key = _build_and_store_bundle(...)  # build-on-download-if-missing (Pattern 2), then patch row
    url = gcs.signed_download_url(key, ttl_seconds=300, filename=f"raw-output-{run_id}.zip",
                                  content_type="application/zip")
    return {"url": url, "expires_in": gcs._clamp_ttl(300)}
```
> Note on superadmin-only: the download is a superadmin action against a chosen client's run. `get_tenant_repo` routes a superadmin onto the bypass engine (cross-tenant reach) and a `user` onto the space-scoped engine. A `user` reaching another space's run gets an existence-hidden 404 via `_scope`. If a stricter "superadmin role required, users NEVER" gate is wanted, add an explicit `if identity.role != "superadmin": raise 404` (existence-hidden) — recommended, since RUN-03 says clients can NEVER access it and clients are `user`-role. Confirm the exact gate with the planner.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Report + sources only served for the report viewer | Same endpoint reused for the bundle's report.md + sources.json | Phase 16 (get_report seam) | No new report/source fetch code |
| `cleaned_reports` only used internally (rewrite/resume) | Now also exported via a new read-only seam endpoint | This phase | One small new Tribunal endpoint |
| verify_chain as a compliance smoke | verify_chain as a hard completion-path gate | This phase (ENGINE-04 posture → RUN-03 gate) | Chain result now lands in intake run state + blocks download |

**Deprecated/outdated:** None relevant. Do NOT use `AUDIT_GCS_BUCKET` for the bundle (that's the 7-year audit bucket; D-05 says the app bucket).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The seam `get_report` response carries a top-level `markdown` key (the fixture + driver assume it; the live `runs/api.py:915` returns `sections`, not `markdown`). | Code Examples (bundle builder) | If the live endpoint returns only `sections`, `report.md` would be empty unless reconstructed from `sections` or the report endpoint is adjusted. Verify against a live completed run OR persist from `output_markdown` (which the driver already writes). LOW risk — `output_markdown` is a reliable fallback source. |
| A2 | google-cloud-storage keyless V4 signing kwargs (`service_account_email` + `access_token`) work for the bundle blob exactly as for existing Phase-9 objects. | Standard Stack | LOW — the same `gcs.signed_download_url` is already live for context-pack/report artifacts; the bundle is just another object under the same bucket/key convention. |

**No other assumptions.** All architecture, endpoints, models, and pitfalls were verified by direct file reads this session.

## Open Questions (RESOLVED)

1. **report.md source of truth (A1).**
   - What we know: the driver persists `report.get("markdown")` to `research_runs.output_markdown`; the fixture returns `{"markdown": ...}`; the live report endpoint returns `sections`.
   - What's unclear: whether the live seam `get_report` returns a `markdown` key or only `sections`.
   - Recommendation: use `output_markdown` (already stored) as the report.md body — it's already the persisted raw markdown; no dependency on the report endpoint's exact shape. Confirm during the live UAT run.

2. **Exact superadmin gate strength for the download route.**
   - What we know: RUN-03 says clients (all `user`-role) can NEVER access it; superadmin-only is locked.
   - What's unclear: whether to rely on `get_tenant_repo`'s existence-hidden 404 for `user`-role, or add an explicit `role != "superadmin" → 404`.
   - Recommendation: add the explicit existence-hidden role gate for defense-in-depth (cheap, unambiguous), AND the space-scoped run lookup. Both proven in the denial suite.

3. **Signed-URL TTL for the bundle (builder discretion, D-05).**
   - Recommendation: reuse the Phase-9 default of 300s (clamped ≤900s). No reason to differ.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| GCS (`STORAGE_BUCKET`) | Bundle storage | ✓ (Phase-9 live) | — | — |
| Tribunal seam (`tribunal_service_url`) | verify + cleaned_reports fetch | ✓ (Phase-14/16 live) | tribunal-api 00007-vsf | Needs redeploy for the NEW `/research-bundle` endpoint |
| `verify_chain` endpoint (`/api/audit/verify/{run_id}`) | The guard | ✓ (already mounted, `server.py:112`) | — | — |
| Anthropic credits (Nestor_Claude2) | A live completed run to test against | ✗ (empty, Phase-16 blocker) | — | Test against `fake_tribunal_client`; defer live proof to operator runbook |
| Cloud Build | Build backend + tribunal-api images | ✓ | — | — (no local Python/Docker per memory) |

**Missing dependencies with no fallback:** None that block BUILD/PLAN. The only ✗ (Anthropic credits) blocks the LIVE proof only — the phase is fully buildable and testable against `fake_tribunal_client`.

**Missing dependencies with fallback:** The new `/research-bundle` Tribunal endpoint must be deployed before the intake finalize path can call it live; test-time it's faked.

## Validation Architecture

> nyquist_validation is enabled (no `workflow.nyquist_validation: false` found; treated as enabled).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (backend) + Tribunal's own pytest suite; both run in Cloud Build (dev machine has no Python) |
| Config file | `backend/` pytest (integration marker used); `tribunal/nestor_pulse_sdk/tests/` |
| Quick run command | `pytest backend/tests/test_research_run_task.py backend/tests/test_research_cross_tenant.py -x` (in Cloud Build) |
| Full suite command | Cloud Build backend integration suite (152 passed / 4 pre-existing mail-audit failures) + tribunal subset |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RUN-03 (SC1) | Superadmin downloads raw output as a file (signed URL, space-scoped) | integration | `pytest backend/tests/test_research_bundle_download.py -x` | ❌ Wave 0 |
| RUN-03 (SC2) | Client/cross-space CANNOT access — 404/403 | integration (denial) | `pytest backend/tests/test_research_cross_tenant.py -x` (EXTEND) | ✅ extend |
| RUN-03 (SC3) | `verify_chain` runs as a hard gate; broken → locked | integration | `pytest backend/tests/test_research_run_task.py -x` (EXTEND: completed branch gates + patches chain_status) | ✅ extend |
| RUN-03 | Bundle builder produces correct zip layout (report.md + research/*.md + sources.json, NO rejected_claims) | unit | `pytest backend/tests/test_research_bundle.py -x` | ❌ Wave 0 |
| RUN-03 | Pool-safety: `checkedout()==0` across build+upload | integration | `pytest backend/tests/test_research_run_task.py -x` (EXTEND pool assertion) | ✅ extend |
| RUN-03 | New seam methods call correct URLs / return shapes | unit | extend `fake_tribunal_client` with `get_research_bundle` + `verify_chain` fakes | ✅ extend fixture |
| RUN-03 | New Tribunal `/research-bundle` endpoint returns cleaned_reports, 409 when absent, RLS-scoped | integration (tribunal) | `pytest tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the quick run (`test_research_run_task.py` + `test_research_cross_tenant.py`).
- **Per wave merge:** full backend integration suite + tribunal subset in Cloud Build.
- **Phase gate:** full suite green + the LIVE proof (deferred): one completed run → verify_chain green → download the zip → confirm layout. Blocked on Anthropic credits (Phase-16 blocker); record in a HUMAN-UAT runbook item, same checkpoint pattern as 16-05.

### Wave 0 Gaps
- [ ] `backend/tests/test_research_bundle.py` — unit tests for `build_bundle_zip` (layout, no rejected_claims, sanitized angle names, empty cleaned_reports).
- [ ] `backend/tests/test_research_bundle_download.py` — superadmin download happy path (signed URL minted) + build-on-download-if-missing recovery.
- [ ] Extend `backend/tests/test_research_cross_tenant.py` — download + re-verify denial (space-B → 404, user-role → 404, null-space → 403).
- [ ] Extend `backend/tests/test_research_run_task.py` — completed branch gates on verify_chain, sets chain_status/bundle_key, pool checkedout==0 across build; broken-chain → locked (no bundle, chain_status="broken").
- [ ] Extend `fake_tribunal_client` fixture — add `get_research_bundle` (returns `{cleaned_reports:[["angle-a",{"report":"x"}]]}`) + `verify_chain` (returns `{ok:True,broken_at:None}`; overridable to broken).
- [ ] `tribunal/nestor_pulse_sdk/tests/test_research_bundle_endpoint.py` — the new endpoint returns cleaned_reports / 409 / 404 / RLS-scoped.
- [ ] `backend/tests/test_research_runs_migration.py` — extend to assert the new 0012 columns exist.

## Security Domain

> `security_enforcement` treated as enabled (no `false` in config found).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | HTTP-only seam, internal-auth (Phase-14 D-04/D-05); no shared DB session across codebases |
| V4 Access Control | **yes (core)** | Superadmin-only + space-scoped download/re-verify; existence-hidden 404; CI-gated denial suite (BOLA/IDOR prevention — Pitfall 9) |
| V5 Input Validation | yes | `run_id`/`intake_id` coerced to canonical UUID (404 on malformed, `_normalize_intake_id` pattern); provider names sanitized into zip entries |
| V6 Cryptography | yes (delegated) | Keyless V4 signed URLs via ADC signBlob (`gcs.signed_download_url`); no SA JSON key; audit hash-chain is SHA-256 (verified server-side only, never re-implemented) |
| V8 Data Protection | **yes (core)** | Raw research NEVER client-visible (REPORT-02); download forced `attachment` disposition; TTL clamped ≤900s; broken chain BLOCKS export (D-06, EU AI Act Art. 12) |
| V12 File/Resource | yes | Server-authored space-scoped keys; path-traversal-proof (`build_object_key`); zip built in-memory (no temp-file exposure) |

### Known Threat Patterns for {intake backend + Tribunal seam}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant download of another space's raw output | Information Disclosure | Space-scoped run lookup + superadmin gate + denial suite from day one (Pitfall 9) |
| Client (`user`-role) reaching the download | Elevation of Privilege | Existence-hidden 404 for non-superadmin; route mounted admin-only |
| Exporting content on a tampered/broken audit chain | Repudiation / Tampering | verify_chain hard gate; broken → complete-but-locked, download BLOCKED (D-06) |
| False-green verify on an empty/wrong-tenant chain | Tampering (evasion) | Correct tenant header (already sent) + optional audit-activity cross-check (Pitfall 2) |
| Signed-URL leakage / over-long lifetime | Information Disclosure | ≤900s clamp, attachment disposition, keyless signing (Phase-9 seam) |
| Stored-XSS via report/provider content rendered inline | Tampering | Forced `attachment` disposition — browser downloads, never renders (T-09-04) |

## Sources

### Primary (HIGH confidence — read directly this session)
- `backend/app/research/run_task.py` — poll driver, finalize_completed, pool-safety contract, load-bearing fixes
- `backend/app/research/tribunal_client.py` — seam client (OIDC + acting-user headers), get_report shape
- `backend/app/api/research_routes.py` — trigger + SSE stream, superadmin write path, transition map
- `backend/app/api/storage_routes.py` — signed-URL JSON convention `{url, expires_in}`, prefix-assert, existence-hidden 404
- `backend/app/storage/gcs.py` + `keys.py` — GCS seam, TTL clamp, keyless signing, `build_object_key`
- `backend/app/db/models/research_runs.py` — model to extend; migration head 0011
- `backend/app/db/session.py` — superadmin/user engine routing, default-deny 403
- `backend/app/db/repository.py:463` — ResearchRunRepository
- `backend/tests/test_research_cross_tenant.py`, `test_research_run_task.py`, `conftest.py` (fake_tribunal_client + fake_gcs fixtures)
- `tribunal/nestor_pulse_sdk/runs/api.py` — get_run_report (report + sources), synthesis_cache `_latest` read, report-spec/rewrite patterns
- `tribunal/nestor_pulse_sdk/audit/api.py` + `verifier.py` + `hash_chain.py` — verify endpoint, empty-chain-trivially-valid behavior, frozen payload
- `tribunal/nestor_pulse_sdk/runs/worker.py` — completion path (persists markdown + rejected_claims only)
- `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py` — synthesis_cache write (cleaned_reports shape), _write_output/_read_output
- `tribunal/nestor_pulse_sdk/db/models/{output,claim,source}.py` — model shapes
- `tribunal/nestor_pulse_sdk/auth/deps.py` + `server.py` — get_db_session tenant scoping, audit router mounting
- `frontend/src/components/intake/ResearchRunProgress.tsx` + `frontend/src/lib/api/research.ts` — summary card + SSE wire
- `.planning/research/PITFALLS.md` — Pitfalls 7 (audit chain) + 9 (new-surface leak)
- `.planning/phases/16-research-trigger-progress-bridge/.continue-here.md` — live deploy state, driver-death deferral, pool starvation

### Secondary (MEDIUM confidence)
- CLAUDE.md + REQUIREMENTS.md + 17-CONTEXT.md (locked decisions, constraints)
- MEMORY.md (deploy recipes, no-local-Python, Anthropic-credits blocker)

### Tertiary (LOW confidence)
- None — no unverified web claims used.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all helpers read directly.
- Architecture: HIGH — every integration point traced through both codebases.
- Pitfalls: HIGH — grounded in PITFALLS.md + live incident notes + direct code (empty-chain, pool starvation, driver death).
- Assumptions: 2 LOW-risk items flagged (report `markdown` key; GCS signing kwargs — both have safe fallbacks already in production).

**Research date:** 2026-07-22
**Valid until:** ~2026-08-21 (30 days — stable internal codebase; fast-moving only if the Tribunal report endpoint or GCS pins change).
