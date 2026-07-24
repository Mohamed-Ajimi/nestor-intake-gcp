---
phase: 15-engine-enhancements-plan-critique-draft-tournament-deferred-
plan: 04
subsystem: intake-side-tribunal-read-proxies
tags: [fastapi, seam, oidc, tenant-isolation, existence-hidden, superadmin, verification, audit, citations]
requires:
  - GET-runs-verification-endpoint          # Plan 15-03 (tribunal side)
  - GET-runs-audit-body-endpoint            # Plan 15-03
  - GET-sources-source-id-endpoint          # Plan 15-03
  - tribunal_client._headers-mint_id_token  # Plan 14 OIDC seam
  - _superadmin_gate                        # Plan 17 research_routes
  - fake_tribunal_client-fixture            # conftest
provides:
  - tribunal_client.get_verification
  - tribunal_client.get_source
  - tribunal_client.get_audit_body
  - GET-intakes-research-verification-proxy
  - GET-intakes-research-sources-proxy
  - GET-intakes-research-audit-body-proxy
  - verification-source-audit-denial-trios
  - verification-superadmin-happy-path
affects:
  - Frontend operator surfaces (verification report + citation source snapshot + feed audit drill-down go through these superadmin-only proxies — the frontend never calls Tribunal directly)
  - Plan 15-05 (D15 feed drill-down: audit_id item resolves via the /audit/{audit_id} proxy)
tech-stack:
  added: []
  patterns:
    - "Seam method clones get_metrics verbatim (keyword-only, blocking httpx, reuse _headers/_mint_id_token, path-less audience Pitfall 4) — no new OIDC code"
    - "Proxy route clones get_bundle_url body: _superadmin_gate dependency + defense-in-depth in-body 404 + intake/run existence-hidden 404 + seam call OUTSIDE the held DB session"
    - "Denial trio (cross-tenant / user-role / null-space) asserts EXACTLY 404, no foreign id in body, and the fake_tribunal_client call counter == 0 (no seam call on denial)"
    - "Superadmin happy path reads through the connect-as app_superadmin engine (0003 bypass) so a seeded intake+run resolve and the seam call fires exactly once"
key-files:
  created: []
  modified:
    - backend/app/research/tribunal_client.py
    - backend/app/api/research_routes.py
    - backend/tests/test_research_cross_tenant.py
    - backend/tests/conftest.py
decisions:
  - "The research-CITATION source proxy (/research/sources/{source_id}) is a DISTINCT concern from the intake-upload sources surface — do NOT overload frontend/src/lib/api/sources.ts (per plan Task 2 note)"
  - "The source proxy has NO run in its path (source_id is tenant-scoped by the header at the tribunal RLS layer), so its trio pins role + intake-existence + null-space walls, not run-scope"
  - "Added a local superadmin_engine fixture (connect-as app_superadmin) to this test module rather than reaching cross-module — mirrors test_intake_cross_tenant.superadmin_engine so the happy-path proof runs the production get_tenant_repo verbatim"
metrics:
  duration: ~25m
  completed: 2026-07-24
---

# Phase 15 Plan 04: Intake-Side Tribunal Read Proxies Summary

The intake-side seam that lets the superadmin operator surface reach the new Plan 15-03 tribunal read endpoints WITHOUT the frontend ever calling Tribunal directly (SEAM-01): three `tribunal_client` methods cloning `get_metrics` verbatim (OIDC header discipline reused, no new token code), three superadmin-only + space-scoped + existence-hidden proxy routes cloning `get_bundle_url` (seam call outside the held DB session), and a CI-gated denial trio for each route plus a happy-path funnel proof — enforcing 16-D-08 (the client sees nothing) day one so the broken-RLS class of bug cannot recur.

## What Was Built

**Task 1 — seam methods `get_verification` / `get_source` / `get_audit_body`** (`0f37ad1`):
- `backend/app/research/tribunal_client.py`: three keyword-only blocking-httpx GET functions, each mirroring `get_metrics` exactly (`resp.raise_for_status()` + `return resp.json()`), reusing `_headers`/`_mint_id_token` verbatim (no new OIDC code, audience stays the path-less `service_url` per Pitfall 4). URLs: `/api/runs/{run_id}/verification`, `/api/sources/{source_id}`, `/api/runs/{run_id}/audit/{audit_id}`. None persist anything.

**Task 2 — superadmin-only proxy routes** (`ac6102d`):
- `backend/app/api/research_routes.py`: three sync `def` routes on `research_router`, each cloning `get_bundle_url`'s body — `Depends(_superadmin_gate)` + a defense-in-depth in-body `if identity.role != "superadmin": 404`, an intake-existence 404, and (for the run-scoped routes) a `run is None or str(run.intake_id) != str(intake_id)` → 404. The seam call runs OUTSIDE the held DB session (mirrors `get_bundle_url`'s connection-free window). Routes:
  - `GET /{intake_id}/research/{run_id}/verification` → `tribunal_client.get_verification(...)`
  - `GET /{intake_id}/research/sources/{source_id}` → `tribunal_client.get_source(...)` (intake-existence check only; source is tenant-scoped at the tribunal RLS layer — a distinct concern from intake-upload sources)
  - `GET /{intake_id}/research/{run_id}/audit/{audit_id}` → `tribunal_client.get_audit_body(...)` (the D15 feed drill-down target)
- Route ordering is safe: `sources/{source_id}` cannot be shadowed by `{run_id}/bundle-url` (or the `{run_id}/verification` / `{run_id}/audit/...` routes) because the second segment differs (`sources` literal vs a `{run_id}` param followed by a distinct literal suffix).

**Task 3 — denial trio ×3 + happy-path + fixture stubs** (`5c1c933`):
- `backend/tests/test_research_cross_tenant.py`: 9 denial tests (verification / research-source / audit-body × cross-tenant-404 / user-role-404 / null-space-404), each asserting `resp.status_code == 404`, `str(foreign_id) not in resp.text`, and the matching `fake_tribunal_client[...calls] == 0` (no seam call on denial). Plus `test_verification_superadmin_happy_path`: a superadmin same-space GET asserting status 200, a non-empty `funnel` with `distilled > 0`, and exactly one seam call — the pre-UAT proof the full intake → seam → (fake tribunal) path returns real funnel data.
- `backend/tests/conftest.py`: the `fake_tribunal_client` fixture gains `get_verification` / `get_source` / `get_audit_body` stubs with call counters (`get_verification_calls` / `get_source_calls` / `get_audit_body_calls`) and an overridable `verification_report` default carrying `funnel.distilled == 3` for the happy path.
- A local `superadmin_engine` fixture (connect-as `app_superadmin`, mirrors `test_intake_cross_tenant.superadmin_engine`) + an extended `_patch_engines(..., sa_engine=...)` so the happy-path superadmin request flows through the production `get_tenant_repo` verbatim against the testcontainer's 0003-bypass engine.

## Verification Strategy (author-by-construction — no local Python)

The dev box has no Python/Docker (project memory), so no test ran locally.

**Cloud Build gate command (primary gate for all three tasks, per plan acceptance):**
```
cd backend && pytest tests/test_research_cross_tenant.py -x
```
This exercises the 9 new denial tests (existence-hidden 404 + no-seam-call on denial — the T-15-09 / T-15-10 / T-15-11b security proofs) and the verification happy-path funnel assertion (backend → seam path returns real data). The denial tests are DB-backed integration tests (`pytestmark = pytest.mark.integration`) that run against live Cloud SQL when `DATABASE_URL` is set and skip-clean otherwise, mirroring the existing bundle-url / verify-chain trios in the same module.

**Static + structural validation performed locally instead (all pass):**
- `grep -c 'def get_verification'` / `get_source` / `get_audit_body` in `tribunal_client.py` == 1 each; all three call `_headers(...)` + `resp.raise_for_status()`; no new OIDC/token code (grep-verified); URLs match the plan.
- `research_routes.py`: the three new route decorators present, all `def` (sync, not `async def`), all `Depends(_superadmin_gate)` (5 total incl. bundle-url/verify-chain) + in-body role checks (6 total); each 404s on missing intake/run and calls the seam AFTER the DB lookups.
- `test_research_cross_tenant.py`: 19 test functions total (9 pre-existing + 10 new); the 9 denial tests assert `str(foreign_id) not in resp.text` + the matching `...calls == 0`; the happy-path uses the `superadmin_engine` fixture.
- `conftest.py`: the three new stubs + counters registered in the `fake_tribunal_client` patch loop.
- No local `ast.parse` guard ran (no Python on the box) — deferred to the Cloud Build `pytest` invocation, which parses + executes.

## Deviations from Plan

None material — plan executed as written across all three tasks. No Rule 1-4 deviations, no auth gates, no architectural changes, no new packages (T-15-SC holds).

One additive test-infra decision the plan left implicit: the happy-path assertion requires a superadmin to actually READ a seeded intake+run, which the existing `test_research_cross_tenant._patch_engines` did NOT wire (it only patched the plain `get_engine`, because every pre-existing test uses a user-role denial). I added a local `superadmin_engine` fixture + extended `_patch_engines` with an optional `sa_engine` to route the superadmin path through the connect-as `app_superadmin` engine (0003 bypass) — the same pattern `test_intake_cross_tenant` already uses. This is test-only infrastructure (no production-code change) needed to make the plan's mandated happy-path proof real rather than a false green.

## Known Stubs

None in production code. The three proxy routes return REAL tribunal JSON verbatim (verification report / source snapshot / redacted audit body from Plan 15-03). The `fake_tribunal_client` stubs are TEST doubles (by design — no test reaches the real internal Tribunal API / mints no OIDC token), not shipped stubs.

## Threat Flags

None beyond the plan's registered surface. The three new read proxies are all covered by the threat register:
- T-15-09 (client role reading verification/source → user-role-404 denial test, no seam call).
- T-15-10 (cross-space run_id/source_id via proxy → cross-tenant-404 denial test asserts no seam call + no id leak; intake+run scope check + tribunal RLS).
- T-15-11 (forged OIDC audience → reuse `_headers`/`_mint_id_token` verbatim, path-less audience).
- T-15-11b (audit-body drill-down via proxy → audit-body denial trio asserts no seam call on denial).
No new network surface beyond the three documented proxies, no new schema at a trust boundary, no new packages (T-15-SC).

## Self-Check: PASSED

- Files modified — `backend/app/research/tribunal_client.py`, `backend/app/api/research_routes.py`, `backend/tests/test_research_cross_tenant.py`, `backend/tests/conftest.py` — all present in the tree.
- Commits `0f37ad1`, `ac6102d`, `5c1c933` — all present in `git log`.
- Acceptance greps for all three tasks pass (three seam methods ×1, three sync-def routes with the superadmin gate, 10 new tests + three fixture stubs).
