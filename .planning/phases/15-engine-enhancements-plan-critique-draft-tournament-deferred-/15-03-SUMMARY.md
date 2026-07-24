---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 03
subsystem: tribunal-verification-citation-audit-read-surfaces
tags: [fastapi, rls, pydantic, verification, citations, audit, gcs, tenant-isolation]
requires:
  - tribunal-alembic-0011-cost-verification
  - VerificationVerdict-model
  - run.verification_summary
  - run.cost_pending
  - run_4cbb5311-recorded-fixture
provides:
  - build_verification_report-shaper
  - GET-runs-verification-endpoint
  - VerificationReport-schema
  - enriched-stage_detail-schema
  - number_citations-deterministic
  - download_audit_body-gcs-reader
  - GET-runs-audit-body-endpoint
  - AuditBody-schema
affects:
  - Plan 15-02 (true_cost surfaces run.cost_usd_total + cost_pending set by the cost fix)
  - Plan 15-05 (D15 feed reads enriched run.stage_detail; audit_id item resolves via /audit/{audit_id})
  - Frontend operator surfaces (verification report + citation numbering + audit drill-down)
tech-stack:
  added: []
  patterns:
    - "Pure shaper (shape_verification_report) + thin async DB wrapper (build_verification_report) so shaping is unit-testable with NO Postgres"
    - "RLS-miss == 404 (scalar_one_or_none -> HTTPException(404)) mirrored from get_run_metrics/renderer.get_source for every new read endpoint"
    - "Enriched wire fields are all Optional so legacy flat {name,status} stage rows still validate (additive, D-07)"
    - "Citation [n] generated from claim.position DB ordering (D13) — never model-emitted; every number resolves + de-dups on source first-appearance"
    - "Audit body read back from GCS already-redacted; response model omits hash/prev_hash (mirrors _audit_row_dto)"
key-files:
  created:
    - tribunal/nestor_pulse_sdk/verification/__init__.py
    - tribunal/nestor_pulse_sdk/verification/report.py
    - tribunal/nestor_pulse_sdk/citations/numbering.py
    - tribunal/nestor_pulse_sdk/tests/test_citation_numbering.py
    - tribunal/nestor_pulse_sdk/tests/test_verification_report_endpoint.py
    - tribunal/nestor_pulse_sdk/tests/test_audit_body_endpoint.py
  modified:
    - tribunal/nestor_pulse_sdk/runs/schemas.py
    - tribunal/nestor_pulse_sdk/runs/api.py
    - tribunal/nestor_pulse_sdk/audit/gcs_blob.py
decisions:
  - "The report bucket is taken from the gs:// uri itself in download_audit_body (recorded at upload) rather than re-derived from AUDIT_GCS_BUCKET, so a body written under a different bucket still resolves"
  - "quality_tier + publication_date are DERIVED on read (provider/domain heuristic + source.fetched_at) not stored columns (Open Q A3 — chain-safe)"
  - "unverified is an HONEST count = total claims - DISTINCT claims carrying a verdict; the recorded run predates claim linkage (claim_id NULL) so it reports full claim_count as unverified, never a fabricated 0"
metrics:
  duration: ~40m
  completed: 2026-07-24
---

# Phase 15 Plan 03: Verification / Citation / Audit Read Surfaces Summary

The tribunal-side operator read surfaces over the recorded run: a `build_verification_report()` shaper that plumbs the persisted `verification_verdict` rows + `run.verification_summary` funnel + true cost into the STAKEHOLDER-NOTES report shape (exposed at RLS-scoped `GET /runs/{id}/verification`), deterministic citation `[n]` numbering generated from `claim.position` DB ordering, an enriched `stage_detail` feed-item schema, and an audit-body drill-down endpoint (`GET /runs/{id}/audit/{audit_id}`) with a GCS reader — all tenant-isolated (RLS-miss == 404), all reading persisted rows only, with three test files carrying the RLS denial proofs.

## What Was Built

**Task 1 — `build_verification_report()` + enriched stage_detail schema** (`cb9253b`):
- `verification/report.py`: `shape_verification_report(...)` is a PURE function over already-materialised verdict rows — it splits verdicts into support/refute/insufficient, surfaces refuted-with-evidence (refute rows carrying non-null `evidence_refs`), superseded/scoped findings (reconciliation with a scoped relation or a temporal note + canonical), reconciled contradictions (`reconciliation.disputed` + canonical), an HONEST unverified count, and true cost (`cost_usd_total` as string + `cost_pending`). `build_verification_report(session, run)` is the thin async DB-facing wrapper: it fetches the run's `verification_verdict` rows (RLS-scoped ORM) + the run's `claim` count, then delegates to the pure shaper. **No GCS/storage/blob import anywhere in report.py** (grep-verified clean).
- `runs/schemas.py`: added `StageRetry`, `StageDetailItem`, `StageSummary`, `StageDetail` — the enriched D15 feed item schema (cost_usd/task_prompt/facts/retry/audit_id + per-stage summary), all fields Optional so today's recorded rows and legacy flat `{name,status}` rows still validate. `RunMetrics.stage_detail` documented as the enriched map and returned VERBATIM by `get_run_metrics` (D-07 — no field stripping; enriched fields ride the JSONB for free).

**Task 2 — `GET /runs/{id}/verification` + `VerificationReport` model** (`14addf8`):
- `runs/api.py`: `get_run_verification` (async) loads the run with `scalar_one_or_none()` → `HTTPException(404, "run not found")` on None (RLS-miss == absent, T-15-06, mirroring `get_run_metrics`/`renderer.get_source`); calls `build_verification_report(session, run)`. Registered BEFORE the `/{run_id}` catch-all so the sub-path is not shadowed.
- `runs/schemas.py`: `VerificationReport` response model (+ `VerificationVerdictItem`/`Groups`/`Unverified`/`TrueCost`), `extra="allow"` so the shaper's `counts` rollup rides through.

**Task 3 — citation `[n]` numbering + numbering/verification tests** (`7e1966f`):
- `citations/numbering.py`: `number_citations(session, run_id)` orders `claim`→`claim_source`→`source` by `claim.position ASC NULLS LAST, claim.id, source.id`, assigns a 1-based `[n]` at each source's first appearance (de-dups re-used sources), and returns each number's source metadata: title/url/provider, `publication_date` (source.fetched_at ISO proxy), `quality_tier` (1/2/3 via `derive_quality_tier` provider/domain heuristic — A3, not a stored column), `single_source` flag, and the introducing claim. Reads the DB only (no model text, no GCS), RLS-scoped.
- `test_citation_numbering.py`: pure `derive_quality_tier` unit tests (run everywhere, no DB) + DB-backed determinism / all-resolve / single-source tests (integration, seed their own claim/source/claim_source rows under a tenant context; skip-clean without `DATABASE_URL`, mirroring `test_rls_isolation.py`).
- `test_verification_report_endpoint.py`: (a) funnel/verdict shaping over the REAL `run_4cbb5311` fixture rows (pure, no DB via `load_recorded_run(session=None)`) covering all six STAKEHOLDER-NOTES areas incl. the recorded funnel constants and a refuted-with-evidence assertion; (b) the RLS cross-tenant **404 denial** test asserting `str(foreign_run_id) not in resp.text`, via a FastAPI `TestClient` + a fake session whose run SELECT returns None (exactly what RLS produces for a foreign id).

**Task 4 — audit-body drill-down endpoint + GCS reader** (`f72203f`):
- `audit/gcs_blob.py`: `download_audit_body(gcs_uri)` reads the ALREADY-REDACTED body back from GCS (bucket parsed from the `gs://` uri) with a `file://` local-dev fallback mirroring `upload_audit_body`; returns `None` on an `error://` uri, a missing object, or any GCS/parse error (logged at warning) — the caller's cue to 404. **No live-URL fetch, no key re-exposure** (T-15-08c).
- `runs/api.py`: `get_run_audit_body` (async) filters `audit_log` by BOTH `id == audit_id` AND `run_id == run_id` under RLS → `scalar_one_or_none()` 404 on None (T-15-08b); reads the body via `download_audit_body`; a None body is also a 404. Returns `AuditBody` body-only — `hash`/`prev_hash` NEVER included (mirrors `audit.api._audit_row_dto`).
- `runs/schemas.py`: `AuditBody` response model `{audit_id, provider, model, request, response}`.
- `test_audit_body_endpoint.py`: happy-path (redacted body, request+response present, NO hash key), missing-GCS-body 404, and the cross-tenant RLS **404** denial (`download_audit_body` mocked to raise if reached — proving the denial fires at the RLS layer, `assert_not_awaited`, and `str(foreign_audit_id) not in resp.text`). DB-free + GCS-mocked by design.

## Verification Strategy (author-by-construction — no local Python)

The dev box has no Python/Docker (per project memory), so no test ran locally.

**Cloud Build / migrate-job gate command (documented per Task 3/Task 4 acceptance):**
```
cd tribunal && pytest nestor_pulse_sdk/tests/test_citation_numbering.py \
  nestor_pulse_sdk/tests/test_verification_report_endpoint.py \
  nestor_pulse_sdk/tests/test_audit_body_endpoint.py -x
```
- The pure/no-DB layers (verification-report shaping over the fixture, `derive_quality_tier`, both endpoint RLS-404 denials, the audit happy-path) EXECUTE in that run with no Postgres — the endpoint tests fake the DB session and mock GCS; the shaping tests drive the committed `run_4cbb5311` fixture. These are the security-critical proofs (T-15-06 / T-15-08b denials + T-15-08c no-hash).
- The DB-backed numbering determinism/single-source tests are `pytest.mark.integration` and skip-clean without `DATABASE_URL`; they EXECUTE against live Cloud SQL when the proxy env is set (mirrors `test_rls_isolation.py`).

**Static + structural validation performed locally instead (all pass):**
- `report.py` has ZERO gcs/storage/blob imports (grep clean) — the shaper never re-parses blobs.
- `schemas.py` gains cost_usd/task_prompt/facts/retry/audit_id/summary as Optional; `VerificationReport`, `AuditBody` models present.
- `runs/api.py`: `/{run_id}/verification` (1) + `/{run_id}/audit/{audit_id}` (1) routes present, both async, both `scalar_one_or_none` + `HTTPException(404`; `build_verification_report` referenced.
- `numbering.py` orders by `claim.position`; `download_audit_body` defined in gcs_blob.py.
- Both endpoint test files assert `str(foreign_id) not in resp.text`.

## Deviations from Plan

None — plan executed as written across all four tasks. No Rule 1-4 deviations, no auth gates, no architectural changes. No new packages (T-15-SC holds).

## Known Stubs

None. Every read surface returns REAL data: the verification report shapes the recorded verdict rows + funnel from Plan 15-01; citation numbering reads live claim/source rows; the audit body reads the actual stored GCS blob. The `true_cost.cost_pending` flag is wired to `run.cost_pending` (populated by Plan 15-02) — not a stub, an honest reconciliation signal. `publication_date`/`quality_tier` are derived-on-read by design (A3), not placeholders.

## Threat Flags

None beyond the plan's registered surface. The two new read endpoints and the citation/audit readers are all covered by the threat register: T-15-06 (verification cross-tenant → 404 denial test), T-15-07 (numbering under RLS/tenant context), T-15-08 (D13 generated [n], determinism + all-resolve), T-15-08b (audit-body cross-tenant → 404 denial test), T-15-08c (already-redacted body, no hash/prev_hash in the response model). No new network surface, no new schema at a trust boundary, no new packages.

## Self-Check: PASSED

- Files: verification/__init__.py, verification/report.py, citations/numbering.py, test_citation_numbering.py, test_verification_report_endpoint.py, test_audit_body_endpoint.py — all FOUND.
- Commits cb9253b, 14addf8, 7e1966f, f72203f — all present in `git log`.
