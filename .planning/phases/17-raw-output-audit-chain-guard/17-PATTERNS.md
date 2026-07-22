# Phase 17: Raw Output + Audit Chain Guard - Pattern Map

**Mapped:** 2026-07-22
**Files analyzed:** 11 (7 backend, 2 tribunal, 2 frontend) + 6 test files
**Analogs found:** 11 / 11 (every new/modified file has a same-repo analog; this phase is ~80% wiring existing seams together)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/research/bundle.py` (NEW) | utility (pure) | transform | `backend/app/storage/keys.py` (pure, no-I/O module) | role-match |
| `backend/app/research/tribunal_client.py` (EXTEND: `get_research_bundle`, `verify_chain`) | service (seam client) | request-response | same file's `get_report` / `get_metrics` (lines 185-233) | exact (same file) |
| `backend/app/research/run_task.py` (EXTEND: `finalize_completed` gate+build+persist) | service (driver) | event-driven | same file's `write_fn` (lines 348-389) + `finalize_completed` (149-172) | exact (same file) |
| `backend/app/db/models/research_runs.py` (EXTEND: `chain_status`, `chain_broken_at`, `bundle_key`) | model | CRUD | same file's existing nullable mirror columns (lines 64-95) | exact (same file) |
| `backend/app/db/alembic/versions/0012_research_run_chain_bundle.py` (NEW) | migration | CRUD | `0011_research_runs.py` (whole file) | exact (add-column variant) |
| `backend/app/api/research_routes.py` (EXTEND: `bundle-url` GET + `verify-chain` POST) | route (controller) | request-response | `storage_routes.py::create_signed_url` (230-270) + same file `trigger_research` (108-240) | exact |
| `tribunal/nestor_pulse_sdk/runs/api.py` (EXTEND: `GET /{run_id}/research-bundle`) | route (controller) | request-response | same file's `get_run_report` (852-924) + `_latest("synthesis_cache")` reads (384-397, 469-472) | exact (same file) |
| `frontend/src/lib/api/research.ts` (EXTEND: `getBundleUrl`, `reVerifyChain`, `ResearchRun` type fields) | service (transport) | request-response | same file's `triggerResearch` (75-81) + storage signed-url convention | exact (same file) |
| `frontend/src/components/intake/ResearchRunProgress.tsx` (EXTEND: download button, locked state, re-verify) | component | request-response | same file's completed summary card (183-210) + failed card (213-258) | exact (same file) |
| `backend/tests/test_research_cross_tenant.py` (EXTEND: bundle-url + verify-chain denial) | test | request-response | same file's 3-test structure (147-246) | exact (same file) |
| `backend/tests/test_research_bundle.py` + `test_research_bundle_download.py` (NEW) | test | — | `test_research_cross_tenant.py` scaffolding + `fake_gcs`/`fake_tribunal_client` fixtures | role-match |
| `tribunal/.../tests/test_research_bundle_endpoint.py` (NEW) | test | request-response | Tribunal runs/api pytest suite | role-match |

## Pattern Assignments

### `backend/app/research/tribunal_client.py` — EXTEND with two new seam methods (service, request-response)

**Analog:** the SAME file's `get_report` (lines 211-233) and `get_metrics` (185-208). Copy the shape verbatim — keyword-only args, `_headers(...)` for OIDC+acting-user+tenant, blocking `httpx.get`, `raise_for_status()`, `return resp.json()`. Both new methods REUSE `_headers` / `_mint_id_token` (no new OIDC code; audience stays the path-less `service_url`, Pitfall 4).

**Header/auth pattern to reuse verbatim** (lines 69-85):
```python
def _headers(service_url, space_id, acting_user_id, acting_email) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_mint_id_token(service_url)}",
        _HDR_TENANT_ID: space_id,          # "X-Nestor-Tenant-Id" — space_id IS org.id
        _HDR_ACTING_USER_ID: acting_user_id,
        _HDR_ACTING_USER_EMAIL: acting_email,
    }
```

**GET-method pattern to clone** (get_report, lines 227-233):
```python
resp = httpx.get(
    f"{service_url}/api/runs/{run_id}/report",
    headers=_headers(service_url, space_id, acting_user_id, acting_email),
    timeout=_TIMEOUT_S,
)
resp.raise_for_status()
return resp.json()
```

New methods (per RESEARCH Code Examples): `get_research_bundle(...)` → `GET {service_url}/api/runs/{run_id}/research-bundle` returning `{cleaned_reports: [[name, {report:...}], ...]}`; `verify_chain(...)` → `GET {service_url}/api/audit/verify/{run_id}` returning `{ok: bool, broken_at: int|None}`. Keep the SEAM SCOPE docstring discipline (this module persists NOTHING).

---

### `tribunal/nestor_pulse_sdk/runs/api.py` — NEW `GET /{run_id}/research-bundle` (route, request-response)

**Analog:** the SAME file's `get_run_report` (lines 852-924) for the run-lookup + 404/409 gate + `Depends(get_db_session)` tenant scope, and the `_latest("synthesis_cache")` read pattern used at lines 384-397 and 469-472.

**Run-lookup + status-gate pattern** (from get_run_report, 865-869):
```python
run = (await session.execute(select(Run).where(Run.id == run_id))).scalar_one_or_none()
if run is None:
    raise HTTPException(404, "run not found")
if run.status != "completed":
    raise HTTPException(409, "bundle not available yet")
```

**synthesis_cache read pattern** (cloned from lines 469-472 / 384-389):
```python
body = (await session.execute(
    select(Output.body)
    .where(Output.run_id == run_id, Output.format == "synthesis_cache")
    .order_by(Output.created_at.desc()).limit(1)
)).scalar_one_or_none()
if not body:
    raise HTTPException(409, "no cached research for this run")
bundle = _json.loads(body)
return {"cleaned_reports": bundle.get("cleaned_reports") or []}   # D-01: cleaned_reports ONLY
```

**Cleaned_reports shape (verified against pipeline.py:707-728):** the `synthesis_cache` Output row is `json.dumps({mission_brief, cleaned_reports, contested_notes, rejected_claims, verification})`. `cleaned_reports` is a list of `[provider_name, {report: ...}]` pairs (tuples serialized to JSON arrays). **D-01: return ONLY `cleaned_reports`** — `rejected_claims` (also in the bundle) is DELIBERATELY excluded.

**Tenant scope:** `Depends(get_db_session)` (auth/deps.py:149) does `SET LOCAL app.tenant_id` from the JWT-trusted tenant — RLS-scopes the Output read. Same dependency every other runs/api endpoint uses.

---

### `backend/app/research/run_task.py` — EXTEND the `completed` branch (service, event-driven)

**Analog:** the SAME file's `write_fn` (lines 348-389, the completed branch) and `finalize_completed` (149-172). The load-bearing structure is `run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=...)` (ai_session.py:99-149): **READ (plain dto) → release → CALL (no DB conn) → WRITE (fresh tenant_session)**.

**CRITICAL — Pattern 1 (pool-safety, Pitfall 4):** the seam fetches + zip build + GCS upload must run with **NO pooled DB connection held**. In `run_with_session_release`, Phase 2 (CALL / `call_fn`) is the connection-free window (`engine.pool.checkedout() == 0`). Do the gate + fetch + build + upload in the CALL tail (or before opening the WRITE session), and open the WRITE `tenant_session` ONLY to patch the row.

**Existing completed-branch pattern to extend** (write_fn, lines 353-361):
```python
if metrics.get("status") == "completed":
    report = tribunal_client.get_report(run_id=rid, service_url=ctx["service_url"],
        space_id=ctx["space_id"], acting_user_id=ctx["acting_user_id"],
        acting_email=ctx["acting_email"])
    finalize_completed(session, research_run_id, metrics, report)
```

**Order to add (RESEARCH Pattern 1, no DB conn held for steps 1-4):**
```python
# In the CALL phase tail (or top of write, BEFORE the tenant_session):
# 1. report  = tribunal_client.get_report(...)          # seam, no DB conn (already done)
# 2. bundle  = tribunal_client.get_research_bundle(...)  # NEW seam
# 3. verdict = tribunal_client.verify_chain(...)         # NEW seam (the D-06 gate)
# 4. if verdict["ok"]:
#        zip_bytes = build_bundle_zip(report, bundle, report["sources"])
#        key = build_object_key(space_id, intake_id, "artifacts", f"raw-output-{run_id}.zip")
#        gcs.upload_object(key, zip_bytes, content_type="application/zip")
# 5. THEN tenant_session → patch: chain_status(verified|broken), chain_broken_at,
#         bundle_key, output_markdown, status, completed_at
```

**Persist-patch pattern to reuse** (finalize_completed / `_patch_run`, 164-172, 204-224): the WRITE runs under a superadmin identity (trigger actor has no own space); `ResearchRunRepository(session, identity).patch(research_run_id, **values)` reaches the row by id via the 0011 superadmin bypass. Keep the `rowcount == 0` ERROR + success WARNING diagnostics (615b6bc) — do NOT regress.

**MUST-NOT-REGRESS (Pitfall 6):** keep the committed `tenant_session` finalize (11e3043 commit-before-schedule), the `uuid5(intake_id, research_run_id)` idempotency key (721086d), and every WARNING/ERROR log (615b6bc). ADD to the completed branch; do NOT restructure the driver's session discipline.

---

### `backend/app/research/bundle.py` — NEW pure builder (utility, transform)

**Analog:** `backend/app/storage/keys.py` — a pure module (no I/O, no GCS, no DB, "safe to import anywhere"). Same discipline: unit-testable, no side effects. REUSE `sanitize_filename` from `keys.py` for the `research/<angle>.md` entry names (provider names are engine-derived — sanitize, Pitfall/Don't-Hand-Roll).

**Builder pattern (RESEARCH Code Examples, D-03 layout):**
```python
import io, json, zipfile
from app.storage.keys import sanitize_filename

def build_bundle_zip(report: dict, bundle: dict, sources: list) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("report.md", report.get("markdown") or "")   # standalone → Phase-18 PDF
        for name, result in (bundle.get("cleaned_reports") or []):  # [name, {report:...}]
            safe = sanitize_filename(str(name))
            text = result.get("report") if isinstance(result, dict) else str(result)
            zf.writestr(f"research/{safe}.md", text or "")
        zf.writestr("sources.json", json.dumps(sources, ensure_ascii=False, indent=2))
    return buf.getvalue()
```
> **report.md source of truth (Open Q1 / A1):** prefer `research_runs.output_markdown` (already persisted on completion by finalize_completed, line 170) OR the seam `report["markdown"]` — the fixture returns `{"markdown": ...}` but the live Tribunal report endpoint returns `sections` (runs/api.py:922). `output_markdown` is the reliable fallback.

---

### `backend/app/api/research_routes.py` — NEW `bundle-url` GET + `verify-chain` POST (route, request-response)

**Analog A (signed-URL response convention):** `storage_routes.py::create_signed_url` (lines 230-270) — the `{url, expires_in}` shape, `_normalize_intake_id` (malformed → 404), existence-hidden 404 on `intake_repo.get() is None`, and `gcs.signed_download_url(...)` + `gcs._clamp_ttl(...)` for the advertised effective TTL.

**Signed-URL mint + response pattern** (storage_routes.py:261-270):
```python
url = gcs.signed_download_url(path, ttl_seconds=expires_in,
        filename=_filename_from_key(path), content_type=None)   # attachment disposition forced in seam
effective_ttl = gcs._clamp_ttl(expires_in)
return SignedUrlView(url=url, expires_in=effective_ttl)          # ≤900s (D-10)
```

**Analog B (this same router's discipline):** `research_routes.py` header docstring + `trigger_research` (108-240). Mount under `protected_router` (inherits `Depends(get_current_identity)`), sync `def` (NOT async — pg8000 blocking), `space_id` NEVER from request. Use `Depends(get_tenant_repo)` (session.py:52) — superadmin → bypass engine, user → space-scoped engine.

**Space-scoped run lookup + gate** (RESEARCH Code Examples):
```python
intake = repo.get(intake_id)
if intake is None:
    raise HTTPException(404, "Intake not found")               # existence-hidden (D-07)
run = ResearchRunRepository(repo.session, identity).get(run_id)
if run is None or str(run.intake_id) != str(intake_id):
    raise HTTPException(404, "Run not found")
if run.status != "completed" or run.chain_status != "verified":
    raise HTTPException(409, "Raw output is not available")     # D-06/D-09 lock
key = run.bundle_key or _build_and_store_bundle(...)            # build-on-download-if-missing (Pattern 2)
```

**Superadmin gate (Open Q2, recommended defense-in-depth):** RUN-03 says clients (all `user`-role) can NEVER access it. Add an explicit existence-hidden gate `if identity.role != "superadmin": raise HTTPException(404, ...)` in ADDITION to the space-scoped run lookup. Mirror the `get_admin_session` role gate (session.py:357 — but return 404 not 403 here, existence-hidden per Pitfall 5).

**Re-verify POST (D-08):** superadmin-only → `tribunal_client.verify_chain(...)` → patch `chain_status` in a fresh `tenant_session` → 200. Same audit-in-tx pattern as `trigger_research` (lines 211-220) if audit-logging the action.

---

### `backend/app/db/models/research_runs.py` + migration 0012 (model + migration, CRUD)

**Analog (model):** the SAME file's existing nullable mirror columns (lines 64-95). Add `chain_status: Mapped[str | None]` (or with a sane server_default), `chain_broken_at: Mapped[int | None]`, `bundle_key: Mapped[str | None]` — all NULLABLE so existing rows on the live DB don't break (Runtime State Inventory: smoke intake has pre-existing rows).

**Existing nullable-column pattern to copy** (lines 82-86):
```python
error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
output_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
```

**Analog (migration):** `0011_research_runs.py` (whole file). Migration 0012 is an ADD-COLUMN variant: `revision="0012"`, `down_revision="0011"`. It only `op.add_column(...)` (nullable) — it does NOT touch RLS/policies/grants (those already exist on `research_runs` from 0011; new columns inherit the table's row-level policy). Keep the module docstring + `alembic check` discipline. Extend `test_research_runs_migration.py` to assert the new columns exist (RESEARCH Wave 0).

---

### `frontend/src/lib/api/research.ts` — EXTEND transport + type (service, request-response)

**Analog:** the SAME file's `triggerResearch` (lines 75-81) — a one-shot `apiFetch` over the token-attaching transport, RETURN-NO-THROW (`ApiResult`). NEVER fork the transport.

**Transport pattern to clone** (lines 75-81):
```typescript
export function getBundleUrl(intakeId: string, runId: string): Promise<ApiResult<{ url: string; expires_in: number }>> {
  return apiFetch(`/intakes/${intakeId}/research/${runId}/bundle-url`, { method: "GET" });
}
export function reVerifyChain(intakeId: string, runId: string): Promise<ApiResult<{ chain_status: string }>> {
  return apiFetch(`/intakes/${intakeId}/research/${runId}/verify-chain`, { method: "POST" });
}
```

**Type extension:** add `chain_status: string | null` (+ `chain_broken_at`/`bundle_key` if surfaced) to the `ResearchRun` type (lines 49-58) so the SSE frame carries the lock state. The SSE frame source is `read_latest_research_run_dict` (backend) — extend that dict to include the new column(s).

---

### `frontend/src/components/intake/ResearchRunProgress.tsx` — EXTEND summary card (component, request-response)

**Analog:** the SAME file's completed summary card (lines 183-210) and failed/cancelled card (213-258). The download button + chain-locked state land on the completed card (16 D-09 anchor). The re-verify action mirrors the existing `onRetry` button (lines 248-256).

**Completed-card pattern to extend** (lines 184-210): when `status === "completed"` AND `chain_status === "verified"` → render the `[Download]` button (calls `getBundleUrl` then navigates to the signed URL). When `chain_status === "broken"` → render the distinct locked/error state (D-07 UI-only) with a `[Re-verify]` button (calls `reVerifyChain`), styled like the existing failed card (red left-border `#DC2626`, XCircle/AlertTriangle icon).

**Button pattern to reuse** (lines 248-256):
```tsx
<button type="button" onClick={onRetry}
  className="inline-flex items-center gap-2 bg-ink px-4 py-2 font-mono text-xs uppercase tracking-wider text-paper hover:bg-ink/85">
  {t("research.retry")}
</button>
```
**Security (T-16-12):** this component lives ONLY on the admin detail route — never imported by any client route. The download/re-verify affordances inherit that admin-only placement.

---

### `backend/tests/test_research_cross_tenant.py` — EXTEND denial suite (test, request-response)

**Analog:** the SAME file's 3-test structure (lines 147-246). Add denial tests for BOTH new routes from day one (Pitfall 5, standing v1.1 isolation rule). Mirror the existing pattern verbatim: `_patch_engines(monkeypatch, engine)`, `app.dependency_overrides[get_current_identity] = _as(_user(space_b))`, assert EXACTLY the expected status, assert the foreign id is NOT in the body.

**Denial-test pattern to clone** (lines 147-183):
```python
def test_trigger_cross_tenant_404(engine, set_space, two_spaces, monkeypatch, fake_tribunal_client):
    ...
    app.dependency_overrides[get_current_identity] = _as(_user(space_b))
    resp = TestClient(app).post(f"/intakes/{intake_a}/research", headers={"Authorization": "Bearer overridden"})
    assert resp.status_code == 404, "cross-tenant must be EXACTLY 404 (403/200 leaks existence)"
    assert str(intake_a) not in resp.text
```

**New denial cases (RESEARCH):** bundle-url + verify-chain each → (a) space-B user → 404 (existence-hidden), (b) `user`-role → 404 (superadmin-only, existence-hidden), (c) null-space user → 403 (default-deny). Reuse the `_seed_space`/`_seed_intake`/`_cleanup` helpers.

## Shared Patterns

### Seam OIDC + acting-user headers
**Source:** `backend/app/research/tribunal_client.py::_headers` (lines 69-85) + `_mint_id_token` (59-66)
**Apply to:** both new seam methods (`get_research_bundle`, `verify_chain`)
Keyless OIDC via ADC; audience is the path-less `service_url` (Pitfall 4); `X-Nestor-Tenant-Id` = space_id; acting-user headers for D-05 attribution. No new auth code — reuse verbatim.

### Pool-safety release contract (no DB conn across I/O)
**Source:** `backend/app/db/ai_session.py::run_with_session_release` (lines 99-149) — READ→release→CALL(no conn)→WRITE
**Apply to:** the `run_task.py` finalize extension (seam fetches + zip build + GCS upload in the CALL window; WRITE session only patches). Pitfall 4 — the tiny superadmin pool (size 2 + overflow 3) starves under a concurrent trigger if a connection is held across GCS/seam I/O. Pool-safety test asserts `checkedout() == 0` across the build.

### Existence-hidden 404 + space-scoped lookup (BOLA/IDOR wall)
**Source:** `storage_routes.py::create_signed_url` (230-270), `research_routes.py::trigger_research` (132-134), `session.py::get_tenant_repo` (52-81)
**Apply to:** both new intake routes. `space_id` NEVER from request; cross-tenant/missing → 404 (never 403/200); null-space user → 403 (default-deny in the dependency). Both routes join the CI-gated denial suite from day one.

### GCS signed-URL + server-authored key
**Source:** `gcs.signed_download_url` (83-122, ≤900s clamp + forced `attachment` disposition + keyless V4) + `keys.build_object_key` (90-104, space-scoped `{space}/{intake}/{category}/{uuid4}-{name}`)
**Apply to:** the bundle-url route + the finalize upload. Category `"artifacts"` (in `CATEGORIES`, keys.py:35 — NOT the audit bucket, D-05). Deterministic per-run filename `raw-output-{run_id}.zip` so a double-build overwrites (Pattern 2 idempotency).

### Scoped repo patch under superadmin identity
**Source:** `run_task.py::_patch_run` (204-224) + `ResearchRunRepository` (repository.py:463-510)
**Apply to:** the finalize chain/bundle persist + the re-verify patch. The write runs under the superadmin identity (0011 bypass reaches the row by id); keep the `rowcount == 0` ERROR diagnostics.

### Capture-only test fakes (no network / no bucket)
**Source:** `fake_gcs` (conftest.py:663-755) + `fake_tribunal_client` (805-895)
**Apply to:** all new/extended tests. Extend `fake_tribunal_client` with `get_research_bundle` (returns `{cleaned_reports:[["angle-a",{"report":"x"}]]}`) + `verify_chain` (returns `{ok:True,broken_at:None}`, overridable to broken). Both patched with `raising=False` (the methods land in this phase). `fake_gcs["uploads"]` / `["signed_urls"]` capture the bundle write + URL mint.

## No Analog Found

None. Every file has a same-repo analog — most extend a file that already exists. The only genuinely NEW server surface is the Tribunal `/research-bundle` endpoint (analog: `get_run_report` + `_latest("synthesis_cache")` in the same file) and the two thin intake routes (analog: `storage_routes.create_signed_url` + `research_routes.trigger_research`).

## Metadata

**Analog search scope:** `backend/app/{research,storage,api,db}`, `backend/tests/`, `tribunal/nestor_pulse_sdk/{runs,audit,pipeline,auth}`, `frontend/src/{lib/api,components/intake}`
**Files scanned:** 18 (11 read in full or in targeted ranges; 7 grep-located)
**Pattern extraction date:** 2026-07-22
