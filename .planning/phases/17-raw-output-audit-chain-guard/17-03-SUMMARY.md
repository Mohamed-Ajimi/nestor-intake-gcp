---
phase: 17-raw-output-audit-chain-guard
plan: 03
subsystem: api
tags: [fastapi, gcs, signed-url, audit-chain, cross-tenant-denial, react, i18n, existence-hidden-404]

# Dependency graph
requires:
  - phase: 17-raw-output-audit-chain-guard
    plan: 01
    provides: research_runs chain_status/chain_broken_at/bundle_key columns (0012), verify_chain + get_research_bundle seam methods, SSE dict carries the three chain keys, fake_tribunal_client verify_verdict + get_research_bundle fakes
  - phase: 17-raw-output-audit-chain-guard
    plan: 02
    provides: build_bundle_zip pure builder, persisted bundle_key (non-reconstructable — uuid4 segment), chain_status verified|broken on the completed path
  - phase: 09-gcs-storage
    provides: gcs.signed_download_url (keyless V4, TTL clamp ≤900s, forced attachment), gcs._clamp_ttl, gcs.upload_object, build_object_key artifacts category, fake_gcs fixture
provides:
  - "GET /intakes/{id}/research/{run}/bundle-url — superadmin-only, space-scoped signed-URL mint with build-on-download recovery"
  - "POST /intakes/{id}/research/{run}/verify-chain — superadmin-only re-verify that lifts/keeps the D-06 lock, audited in-tx"
  - "_build_and_store_bundle — pool-safe lazy bundle rebuild (no DB conn held across seam/GCS I/O)"
  - "getBundleUrl / reVerifyChain frontend transport + ResearchRun chain fields"
  - "RawOutputControls — download (verified) / locked+re-verify (broken) on the Phase-16 completed card, admin-only"
  - "6 cross-tenant denial tests (3 per route) + download happy/lock/recovery/re-verify suite"
affects: [phase-18-pdf, raw-output-download, audit-chain-guard]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Superadmin role-gate FIRST as existence-hidden 404 (never 403) — a client/user-role caller can never learn the resource exists (Pitfall 5)"
    - "Build-on-download-if-missing: a verified run with NULL bundle_key lazily rebuilds the zip on the download click, patched in a fresh session with no I/O held"
    - "Lock-state-only re-verify: verify_chain re-run outside any DB session; a now-verified verdict lifts the lock but does NOT auto-build (next download does)"
    - "Read the persisted bundle_key — never reconstruct the key (Plan 02's uuid4 segment makes it non-reconstructable)"

key-files:
  created:
    - backend/tests/test_research_bundle_download.py
  modified:
    - backend/app/api/research_routes.py
    - backend/tests/test_research_cross_tenant.py
    - frontend/src/lib/api/research.ts
    - frontend/src/components/intake/ResearchRunProgress.tsx
    - frontend/src/locales/nl/intake.json

key-decisions:
  - "The superadmin role-check fires BEFORE any DB/scope read, so a null-space user hits the role gate → 404 (NOT the null-space default-deny 403 that only the DB-touching stream pre-flight reaches). Both denial suites pin this ordering."
  - "get_bundle_url reads run.bundle_key directly; the NULL branch (driver-death recovery) rebuilds via _build_and_store_bundle — the key is NOT reconstructed (Plan 02 uuid4 segment, upstream constraint honored)."
  - "reverify_chain is lock-state-only (D-08): a now-verified re-verify does NOT auto-build the bundle; the next getBundleUrl click does the build-on-download. Audited as research.chain_reverified in the same patch tx."
  - "Frontend i18n: the research.* progress keys exist ONLY in nl/intake.json today (Phase 16 coverage), so the new download/locked/re-verify keys were added to nl only, mirroring the existing coverage (i18next falls back for fr/en)."

requirements-completed: [RUN-03]

# Metrics
duration: ~35min
completed: 2026-07-22
---

# Phase 17 Plan 03: Raw-Output Download + Audit-Chain Re-verify Summary

**The superadmin-only, space-scoped raw-output download (a signed-URL mint with build-on-download-if-missing recovery) plus the re-verify endpoint that lifts the D-06 lock on a now-passing chain — both existence-hidden 404 for every client / cross-space / user-role caller from day one in the CI-gated denial suite — wired to a completed-card Download button (verified) or a locked+Re-verify state (broken), admin-only and return-no-throw.**

## Performance

- **Duration:** ~35 min
- **Tasks:** 3 (all `type="auto"`)
- **Files:** 6 (1 created, 5 modified)

## Accomplishments

- **`research_routes.py` — two sync-`def` routes + a helper:**
  - `get_bundle_url` (GET `/{intake_id}/research/{run_id}/bundle-url`): superadmin role gate → existence-hidden 404; scoped intake + run lookup (`run.intake_id == intake_id`) → 404; availability gate (`status == "completed"` AND `chain_status == "verified"`) → 409; `bundle_key IS NULL` → lazy rebuild; mints `gcs.signed_download_url(ttl_seconds=300, filename, content_type="application/zip")` and returns `{"url", "expires_in": gcs._clamp_ttl(300)}`.
  - `reverify_chain` (POST `/{intake_id}/research/{run_id}/verify-chain`): same gate + lookup; re-runs `tribunal_client.verify_chain` OUTSIDE any DB session; patches `chain_status`/`chain_broken_at` in a fresh `tenant_session` and audits `research.chain_reverified` in the same tx; returns `{"chain_status"}`.
  - `_build_and_store_bundle`: driver-death recovery — `get_report` + `get_research_bundle` + `build_bundle_zip` + `gcs.upload_object` under the server-authored `artifacts` key, all connection-free, then a fresh `tenant_session` patches `bundle_key` (mirrors Plan 02's pool-safety contract, T-17-14).
- **Denial suite (`test_research_cross_tenant.py`):** 6 new tests (3 per route) — space-B user → 404, user-role-in-space → 404, null-space user → 404 — each asserting the EXACT status and `str(foreign_id) not in resp.text`, and (verify-chain) `verify_chain_calls == 0`. A `_seed_run` helper seeds a completed + verified run so a denial is the scope/role wall, never the availability gate.
- **Download suite (`test_research_bundle_download.py`):** happy path (200, signs the persisted key, TTL ≤900, no lazy upload), not-verified 409 (D-06 lock, no mint), build-on-download-if-missing (200, exactly one upload under `{space}/{intake}/artifacts/`, row's `bundle_key` now set), re-verify lifts lock (broken → `verify_verdict` ok → 200 `chain_status="verified"`, row persisted). Uses the connect-as `app_superadmin` engine fixture (0003 bypass).
- **Frontend transport (`research.ts`):** `ResearchRun` gains `chain_status`/`chain_broken_at`/`bundle_key`; `getBundleUrl` + `reVerifyChain` both reuse `apiFetch` (never fork the transport), return `ApiResult` (return-no-throw).
- **Frontend UI (`ResearchRunProgress.tsx`):** `RawOutputControls` on the completed card — a `[Download]` button when `chain_status === "verified"` (navigates the browser to the signed URL; seam forces attachment disposition), a red locked card + `[Re-verify]` button when `chain_status === "broken"`; both toast on error, never throw. Admin-only by placement (only `admin.pulse.intakes.$id.tsx` imports the component). NL i18n keys added.

## Task Commits

1. **Task 1: bundle-url + verify-chain routes** — `f9d951c` (feat)
2. **Task 2: denial suite + download/recovery/re-verify tests** — `7212341` (test)
3. **Task 3: frontend download + locked + re-verify** — `3ed9adc` (feat)

## Decisions Made

- **Role-gate-first ordering → null-space is 404, not 403.** The superadmin role-check runs before any DB/scope read, so a null-space user is denied by the role gate (404) rather than the null-space default-deny 403 that only the DB-touching stream pre-flight reaches. Both `*_null_space_404` tests pin this exact ordering per the plan's Task-2 note.
- **Read `bundle_key`, never reconstruct.** Honoring the upstream constraint (17-02 Next-Phase-Readiness): `build_object_key` prepends a random `uuid4-` segment, so the key is non-reconstructable. `get_bundle_url` reads `run.bundle_key`; the recovery path builds a NEW key and persists it — no key is ever rebuilt from parts.
- **Re-verify is lock-state-only (D-08).** A now-verified re-verify lifts the lock (`chain_status="verified"`, `chain_broken_at=None`) but does NOT auto-build the bundle — the next `getBundleUrl` click does the build-on-download-if-missing. Keeps the re-verify route free of GCS I/O.
- **i18n coverage mirrors existing.** The `research.*` progress keys live only in `nl/intake.json` today (Phase-16 coverage); the new download/locked/re-verify keys were added to nl only, matching that coverage. i18next falls back for fr/en.

## Deviations from Plan

None — plan executed exactly as written. The plan's Task-2 note left the null-space status to be pinned "per the Task-1 gate ordering"; the implemented gate yields 404 (role-check first), which both null-space denial tests assert and document.

## Automated Verification (deferred to Cloud Build — no local Python/Docker; no frontend node_modules in worktree)

Tests authored by construction (the dev machine has no Python/Docker and the worktree has no frontend `node_modules`):

- `pytest backend/tests/test_research_bundle_download.py backend/tests/test_research_cross_tenant.py -x` — the two new routes' happy paths + the 6 denial cases (runs at the wave boundary in Cloud Build).
- Frontend: `cd frontend && npm run lint` / `tsc --noEmit` runs in the frontend build. The new transport reuses `apiFetch` verbatim and the component narrows `ApiResult` on `.success` before touching `.data`.

Expected caveat: the download/re-verify human-check (a real completed run behind the Anthropic-credits blocker) is deferred to the Plan-04 operator runbook — same external blocker as 16-05.

## Threat Surface Scan

No NEW out-of-model surface. The changes implement mitigations already in the plan's `<threat_model>`:
- **T-17-10 / T-17-11** (cross-tenant + client download): space-scoped run lookup (`run.intake_id == intake_id`) + explicit superadmin role gate, both existence-hidden 404; the denial suite proves space-B, user-role, and null-space → 404 for both routes.
- **T-17-12 / T-17-13** (signed-URL over-lifetime / stored-XSS): TTL 300s clamped ≤900s + forced `attachment` disposition, emitted inside the Phase-9 GCS seam (keyless V4).
- **T-17-14** (pool starvation on lazy build): `_build_and_store_bundle` runs all seam+GCS I/O with no session held; a fresh `tenant_session` opens only to patch `bundle_key`.
- **T-17-15** (UI on a client route): `ResearchRunProgress` is imported only by the admin detail route (grep confirms) — the download/re-verify affordances inherit that placement.
- **T-17-SC** (package installs): none — no new packages this phase.

## Known Stubs

None. The download mints against the persisted (or lazily-built) real key; the broken-chain path deliberately serves the locked card (complete-but-locked is the intended terminal, not a stub). The `chain_status === null` UI branch renders no affordance for pre-Phase-17 / not-yet-finalized rows (correct, not a stub).

## Self-Check: PASSED

- All claimed files exist on disk (1 created, 5 modified, + this SUMMARY).
- All task commits present: `f9d951c` (feat), `7212341` (test), `3ed9adc` (feat).
- `research_routes.py` imports NO `get_engine`/`sessionmaker` — the ci_no_raw_db_access grep-guard stays green (reaches the DB only via the injected repo + `tenant_session`).
- The component is imported only by `admin.pulse.intakes.$id.tsx` (T-17-15).
- SUMMARY.md force-added (`.planning/` is gitignored).
