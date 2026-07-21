# Phase 16: Research Trigger + Progress Bridge - Pattern Map

**Mapped:** 2026-07-21
**Files analyzed:** 14 (12 new/modified backend+frontend + 1 migration + test files)
**Analogs found:** 14 / 14 (every new file has a strong in-repo analog — this phase is integration glue, no greenfield mechanism)

> RESEARCH.md already named every analog with line numbers; this map verified each analog against source and extracts the concrete excerpts the planner copies from. All excerpts are load-bearing — the conventions (sync `def`, verbatim `status`, `space_id`-leading indexes, existence-hidden 404, plain-dict-across-sessions, never-fork-transport) are the correctness contract, not style.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/research/tribunal_client.py` (EXTEND) | service (seam client) | request-response (HTTP → Tribunal) | itself: `ensure_org`/`ensure_project` (same file, lines 88-132) | exact — extend in place |
| `backend/app/research/run_task.py` (NEW) | service (background driver) | event-driven / batch (poll loop) | `backend/app/db/ai_session.py::run_with_session_release` (99-148) | exact (contract) |
| `backend/app/api/research_routes.py` (NEW) | route (trigger + SSE) | request-response + streaming | `intake_routes.py::stream_skill_runs` (1082-1145) + `submit_intake` verb (1184-1259) | exact |
| `backend/app/db/models/research_runs.py` (NEW) | model | CRUD | `backend/app/db/models/skill_run.py` (whole file) | exact |
| `backend/app/db/stream_session.py` (EXTEND) | utility (scoped read) | request-response (per-tick SELECT) | `read_latest_run_dict` (same file, 55-72) | exact — mirror fn |
| `backend/app/db/alembic/versions/0011_research_runs.py` (NEW) | migration | — (DDL + RLS) | `0009_ai_ports.py` (whole file) | exact |
| `backend/app/mail/render.py` (EXTEND) | utility (template render) | transform | `render_admin_validated` / `render_results` (132-149, 108-129) | exact |
| `backend/app/mail/templates/{nl,fr,en}/research_complete.html.j2` + `research_failed.html.j2` (NEW) | config (template) | transform | `templates/admin_validated.html.j2` + `nl/results.html.j2` | exact |
| `backend/app/core/config.py` (VERIFY/wire) | config | — | `Settings.tribunal_service_url` (already present, line ~104) | exact — already typed |
| `frontend/src/lib/api/research.ts` (NEW) | utility (API client + SSE reader) | request-response + streaming | `skillRuns.ts` + `skillRunStream.ts` | exact |
| `frontend/src/components/intake/ResearchRunProgress.tsx` (NEW) | component | streaming (SSE consume) | `SkillRunProgress.tsx` (`useActiveSkillRun` hook + panel, whole file) | role+flow match (scaled up) |
| `frontend/src/lib/intake-phase.ts` (EXTEND) | utility (pure phase machine) | transform | `derivePhase` (same file, 31-76) | exact — additive |
| `frontend/src/components/intake/NextStepBanner.tsx` (EXTEND) | component | request-response (CTA) | `awaiting_research_start` case (258-278) + AlertDialog (`admin.spaces.tsx` 226-247) | exact |
| `backend/tests/test_research_routes.py` + `test_research_run_task.py` + conftest `fake_tribunal_client` (NEW) | test | — | `fake_resend` fixture (conftest 770-801) + cross-tenant denial tests | exact |

## Pattern Assignments

### `backend/app/research/tribunal_client.py` (service, request-response) — EXTEND

**Analog:** itself — the `ensure_org` / `ensure_project` methods already in the file. Add `create_run` / `get_metrics` / `get_run` / `get_report` in the exact same shape.

**Header + OIDC machinery to REUSE verbatim** (lines 47-85 — do NOT re-implement):
```python
_TRANSPORT = ga_requests.Request()
_TIMEOUT_S = 30.0
_HDR_TENANT_ID = "X-Nestor-Tenant-Id"
_HDR_ACTING_USER_ID = "X-Acting-User-Id"
_HDR_ACTING_USER_EMAIL = "X-Acting-User-Email"

def _mint_id_token(service_url: str) -> str:
    # AUDIENCE = service_url WITHOUT /api path (Pitfall 4). The request PATH is added
    # only to the POST/GET URL below, never to the audience.
    return ga_id_token.fetch_id_token(_TRANSPORT, service_url)

def _headers(service_url, space_id, acting_user_id, acting_email) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_mint_id_token(service_url)}",
        _HDR_TENANT_ID: space_id,          # space_id IS org.id (identity mapping)
        _HDR_ACTING_USER_ID: acting_user_id,
        _HDR_ACTING_USER_EMAIL: acting_email,
    }
```

**Core method pattern to COPY** (the `ensure_project` shape, lines 111-132 — blocking `httpx`, keyword-only, `raise_for_status`, JSON return):
```python
def ensure_project(*, service_url, space_id, acting_user_id, acting_email) -> str:
    resp = httpx.post(
        f"{service_url}/api/projects/ensure",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        json={},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()["project_id"]
```

**New methods land as** (RESEARCH Code Examples — same signature discipline, keyword-only, `engine` pinned to `"tribunal"`, brief NEVER contains `[INTERACTIVE_REPORT]`):
- `create_run(*, service_url, space_id, acting_user_id, acting_email, project_id, brief, idempotency_key) -> dict` → `POST /api/runs` body `{project_id, brief, engine:"tribunal", idempotency_key, uploaded_documents:[]}`
- `get_metrics(*, ..., run_id) -> dict` → `GET /api/runs/{run_id}/metrics`
- `get_report(*, ..., run_id) -> dict` → `GET /api/runs/{run_id}/report` (only after `completed`)

**Constraint from the file's own SCOPE docstring (lines 29-32):** the file explicitly reserves trigger/poll/report for Phase 16 and persists NOTHING — the `research_runs` write is the route/task's job, never this module's.

---

### `backend/app/research/run_task.py` (service, event-driven) — NEW

**Analog:** `backend/app/db/ai_session.py::run_with_session_release` (99-148) — the exact READ→release→CALL→WRITE contract. Do NOT hand-roll session juggling.

**The contract to drive through** (ai_session.py:99-148 — CALL phase holds NO connection; `on_error` finalizes the row to `failed`):
```python
run_with_session_release(
    identity,
    read_fn,    # returns PLAIN dict (space_id, acting email/uid, service_url) — NEVER ORM rows
    call_fn,    # ensure_org → ensure_project → create_run → poll loop; NO db connection held here
    write_fn,   # on completed: get_report + finalize + send_complete_mail; on failed: finalize + send_failed_mail
    on_error=on_poll_error,  # ANY exception → finalize research_runs to EXACTLY 'failed' (D-04/D-11 failure path)
)
```

**Per-tick mirror write discipline** — each `research_runs` UPDATE is its OWN short scoped tx (mirror `set_stage`'s own-session-per-write; Pitfall 4 pool-safety). The loop lives in `call_fn` and holds no pooled connection across the ~19-min run:
```python
while True:                          # NO db connection held here (T-7-06)
    m = get_metrics(run_id=rid, ...)
    mirror_tick(identity, research_run_id, rid, m)   # opens its own tenant_session, commits, releases
    if m["status"] in {"completed", "failed", "cancelled"}:   # RESEARCH terminal set — NOT skill-run's
        return rid, m
    time.sleep(POLL_SECONDS)         # ~3s
```

**Idempotency key (D-04, deterministic — RESEARCH Alternatives):** `uuid.uuid5(intake_id, f"attempt-{n}")` so a retried trigger returns the existing run (no double-charge) AND the 3-attempt cap is natural.

**5xx-tolerance (Pitfall 1):** treat any 5xx from `/metrics` as transient — bounded retries then finalize `research_runs` as `failed`; never crash the BackgroundTask.

---

### `backend/app/api/research_routes.py` (route, request-response + streaming) — NEW

**Two analogs, both in `intake_routes.py`:**

**(a) Trigger = discrete allow-listed verb** — copy `submit_intake` (1215-1259) + its transition-map guard (1184-1212):
```python
_RESEARCH_TRANSITIONS: dict[str, str] = {"decomposed": "in_research"}  # ONLY reachable target

def _next_research_status(current: str) -> str:
    try:
        return _RESEARCH_TRANSITIONS[current]
    except KeyError:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"Cannot start research on an intake in status {current!r}")

@research_router.post("/{intake_id}/research")
def trigger_research(intake_id, repo=Depends(get_tenant_repo),
                     identity=Depends(get_current_identity)):
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")  # existence-hidden (D-07)
    new_status = _next_research_status(intake.status)   # 409 if not 'decomposed' (D-06 double-trigger guard)
    # enforce attempt < 3 (D-04) BEFORE the flip; assemble brief; flip status; INSERT research_runs(queued);
    # audit.log on repo.session (same tx — Pitfall 2); BackgroundTasks.add_task(run_poll_driver, ...); return 202
```
The `submit_intake` audit pattern (1237-1240) — `audit.log(repo.session, ..., metadata={"from": old, "to": new})` in the SAME tx — is copied verbatim; `metadata` carries `{from,to}` only (T-06-09, never a link/token).

**(b) SSE stream = clone `stream_skill_runs`** (1082-1145) — the ONE deliberate `async def`. Copy verbatim EXCEPT the terminal set:
```python
# CHANGE from the skill-run handler (AP-6, Pitfall 3):
RESEARCH_TERMINAL = {"completed", "failed", "cancelled"}   # NOT {"succeeded","failed"}
TICK_SECONDS = 2.0; HEARTBEAT_SECONDS = 15.0; MAX_STREAM_SECONDS = 10 * 60   # reuse
SSE_HEADERS = {"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
```
Reuse the pre-flight verbatim (1105-1111): `check_intake_in_scope` in `run_in_threadpool` → `PermissionError` = 403, falsy = existence-hidden 404. Reuse the emit-on-change loop, `: ping` heartbeat, disconnect check, 10-min cap. Every DB touch goes through `run_in_threadpool` (blocking pg8000 must never run on the event loop). Do NOT convert any other handler to async.

---

### `backend/app/db/models/research_runs.py` (model, CRUD) — NEW

**Analog:** `backend/app/db/models/skill_run.py` (whole file) — copy the column + index shape.

**Copy verbatim** (skill_run.py:24-36, 57-74) — `id` UUID PK `default=uuid.uuid4`, `space_id` FK `organizations.id ON DELETE CASCADE` NOT NULL, `intake_id` FK `intakes.id ON DELETE CASCADE`, `status String server_default`, `created_at/started_at/completed_at DateTime(timezone=True)`, and the **space-leading composite indexes**:
```python
__table_args__ = (
    Index("ix_research_runs_space_id", "space_id"),
    Index("idx_research_runs_space_intake", "space_id", "intake_id"),
    Index("idx_research_runs_space_status", "space_id", "status"),
)
```
**New columns for this table (RESEARCH § Architecture):** `tribunal_run_id String nullable`, `current_stage String nullable`, `stage_detail JSONB nullable` (`{stage_key: {items:[{name,status}]}}`), `cost_usd_total Numeric nullable`, `attempt Integer` (D-04), `error_message Text nullable`, and (Open Q2, A4) optionally `output_markdown Text nullable` on completion. Carry `status` VERBATIM from Tribunal (`queued/running/completed/failed/cancelled`) — no remap.

---

### `backend/app/db/stream_session.py` (utility, per-tick read) — EXTEND

**Analog:** `read_latest_run_dict` (same file, 55-72) — mirror it as `read_latest_research_run_dict`.

**Copy the discipline verbatim** (plain dict never ORM row — detaches across ticks; `status` verbatim Pitfall 1; connection released on block exit):
```python
def read_latest_research_run_dict(identity, intake_id) -> dict | None:
    with tenant_session(identity) as session:                      # re-issues the GUC every entry (T-7-02)
        run = ResearchRunRepository(session, identity).latest_for_intake(intake_id)
        if run is None:
            return None
        return {
            "id": str(run.id),
            "status": run.status,                                  # verbatim
            "current_stage": run.current_stage,
            "stage_detail": run.stage_detail,                      # JSONB — dynamic stage list (no hardcoded 9)
            "cost_usd_total": str(run.cost_usd_total) if run.cost_usd_total is not None else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
        }
```
Also add `check_intake_in_scope` reuse — the SSE pre-flight uses the SAME existing `check_intake_in_scope` (42-52), no new function needed.

---

### `backend/app/db/alembic/versions/0011_research_runs.py` (migration) — NEW

**Analog:** `0009_ai_ports.py` (whole file) — the canonical new-tenant-table-with-RLS migration.

**Copy verbatim the RLS + grants helpers** (0009 lines 96-209, 348-359) — this is the anti-broken-RLS contract:
```python
def _space_id_col():   # space_id UUID NOT NULL FK organizations.id ON DELETE CASCADE
    return sa.Column("space_id", _uuid(),
                     sa.ForeignKey(f"{SCHEMA}.organizations.id", ondelete="CASCADE"), nullable=False)

def _enable_rls(table):   # ENABLE + FORCE + space_isolation (NULLIF form) + superadmin_all bypass
    op.execute(f"ALTER TABLE {SCHEMA}.{table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {SCHEMA}.{table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""CREATE POLICY {table}_space_isolation ON {SCHEMA}.{table}
        USING (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)
        WITH CHECK (space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid)""")
    op.execute(f"""CREATE POLICY {table}_superadmin_all ON {SCHEMA}.{table}
        USING (current_user = 'app_superadmin')
        WITH CHECK (current_user = 'app_superadmin')""")
```
**MANDATORY forms (both load-bearing):** the `NULLIF(current_setting('app.current_space_id', true), '')::uuid` empty-string-reversion form AND the `current_user = 'app_superadmin'` bypass (a superadmin carries no GUC → without this they cannot touch the table). Copy the env-guarded runtime-SA GRANT DO-block (0009:131-158) verbatim, the explicit `GRANT ... TO app_superadmin` (0009:355-358), and the `_id_col` `gen_random_uuid()` server_default (0009:82-93). Index names in the migration MUST match the ORM `__table_args__` 1:1 (`alembic check` gate). Set `revision="0011"`, `down_revision="0010"`.

---

### `backend/app/mail/render.py` (utility, transform) — EXTEND

**Analog:** `render_admin_validated` (132-149) + `render_results` (108-129) — the `_localized_template` + `.render(**kwargs)` pattern, autoescape ON.

**Copy the shape** (108-129 — keyword-only, nl fallback via `_localized_template`, `cta_url` is a fully-formed admin route the CALLER builds, never a token):
```python
def render_research_complete(*, project_title, duration_min, cost_usd, cta_url,
                             app_base_url=None, locale="nl") -> str:
    return _localized_template("research_complete", locale).render(
        project_title=project_title, duration_min=duration_min,
        cost_usd=cost_usd, cta_url=cta_url, app_base_url=app_base_url)
# render_research_failed(...): same shape + an error/what-failed field (D-11 failure variant)
# cta_url = f"{app_base_url}/admin/pulse/intakes/{intake_id}"  (admin route, NO token — NOTIF-01)
```
Send seam is the existing `app.mail.resend.send(*, to, subject, html)` (resend.py:39) — `to=[acting_email]` (D-10), key read at call-time. Do NOT touch `resend.py`.

---

### `frontend/src/lib/api/research.ts` (utility, request-response + streaming) — NEW

**Two analogs:** `skillRuns.ts` (trigger fn shape) + `skillRunStream.ts` (SSE reader).

**Trigger fn** — copy `getSkillRunFull` shape (skillRuns.ts:58-65): `apiFetch<T>(...)` over the token-attaching transport, never fork:
```typescript
export function triggerResearch(intakeId: string): Promise<ApiResult<{ research_run_id: string }>> {
  return apiFetch(`/intakes/${intakeId}/research`, { method: "POST" });
}
```
**SSE reader** — clone `openSkillRunStream` (skillRunStream.ts:40-160) verbatim EXCEPT the terminal set (AP-6):
```typescript
const RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"]);  // NOT {"succeeded","failed"}
// Reuse verbatim: currentIdToken() Bearer (never in URL/log), apiUrl() base, raw fetch + ReadableStream
// getReader() frame parsing, `: ping` heartbeat skip, JSON.parse-in-try/catch (T-08-10 malformed skip),
// null-snapshot guard, 404/401 → onFallback (no retry), 3× backoff, close()=abort.
```
URL is `/intakes/${intakeId}/research/stream`.

---

### `frontend/src/components/intake/ResearchRunProgress.tsx` (component, streaming) — NEW

**Analog:** `SkillRunProgress.tsx` (whole file) — the `useActiveSkillRun` SSE-first-with-poll-fallback hook (60-177) + the progress panel (230-269). Scale up: render the FULL stage list.

**Copy the hook mechanics** (SkillRunProgress.tsx:78-168): SSE primary via the new `openResearchStream`, bounded poll fallback, `cancelled` cleanup flag, `restartPollRef` re-arm, terminal→`stream.close()`. The intake design-language panel (245-267) is the styling reference: `border-l-4`, `bg-paperLight`, `font-mono text-[11px] uppercase tracking-wider` labels, `#FF2D87` accent, `tabular-nums` elapsed clock, `role="status" aria-live="polite"`.

**KEY difference (D-07 dynamic stages):** render the stage list from `stage_detail`/`stages[]` DYNAMICALLY — map over the array, one row per stage with done/running/pending state. NO hardcoded 9 (Phase 15 contract). Add running cost + elapsed. **D-09 end state:** on terminal event collapse to a summary card (completed timestamp, total cost, duration, stages green); failure card shows what failed + re-trigger affordance.

---

### `frontend/src/lib/intake-phase.ts` (utility, transform) — EXTEND

**Analog:** `derivePhase` (31-76) — additive change only.

**Current `in_research` derivation keys off `hasResearchArtifacts`** (61-69) which has NO writer in this flow (Pitfall 6). **Minimal change (RESEARCH Open Q3):** keep status-level visibility in `derivePhase` (the enum already has `in_research`, line 12) — the trigger flips status to `in_research` so `derivePhase` returns it correctly. Gate the NEW progress panel + summary card on the `research_runs` row DIRECTLY (not via `derivePhase`). Do NOT let a completed run auto-advance to `awaiting_report_upload` — that is Phase 18's PDF upload (Pitfall 6 / Pitfall 10). If feeding the run into `derivePhase`, extend `PhaseSkillRunInput`-style inputs additively; do not remove the `hasResearchArtifacts` branch.

---

### `frontend/src/components/intake/NextStepBanner.tsx` (component, CTA) — EXTEND

**Analog:** the existing `awaiting_research_start` case (258-278) + the AlertDialog pattern from `admin.spaces.tsx` (226-247).

**The scaffolding already exists** — `onStartAutoResearch`/`onStartManualResearch` props (25-26), `startResearch` BusyKey (40), and the `awaiting_research_start` `PrimaryBtn` (271-277). This phase repurposes the trigger onto the seam and wraps it in a confirm dialog. Copy the button shape (272-276):
```tsx
<PrimaryBtn onClick={props.onStartAutoResearch} busy={busy.startResearch}>
  {busy.startResearch ? t("nextStep.researchRunning") : t("nextStep.startAutoResearch")}
</PrimaryBtn>
```
**D-03 confirm dialog** — copy the shadcn AlertDialog from `admin.spaces.tsx` (226-247): `<AlertDialog open onOpenChange>` → `AlertDialogContent/Header/Title/Description/Footer` with `AlertDialogCancel` + `AlertDialogAction`. The action `onClick` fires the 202 trigger only on confirm ("Start deep research for [client]? This runs for a while and costs money"). Use i18n keys (`t(...)`) like the rest of the banner. **`in_research` case (280-283)** currently shows a static body — extend to mount `ResearchRunProgress` (or leave the panel to the route and keep the banner status-only, per D-07 discretion).

---

### `backend/tests/test_research_routes.py` + `test_research_run_task.py` + conftest fixture (test) — NEW

**Analogs:** `fake_resend` fixture (conftest 770-801) for the new `fake_tribunal_client`; existing cross-tenant denial tests for the isolation cases.

**Copy the `fake_resend` fixture shape** (conftest 770-801) for `fake_tribunal_client` — monkeypatch the seam module's `create_run`/`get_metrics`/`get_report` with capture-only fakes (importorskip so conftest stays importable on a box without httpx), return a capture dict:
```python
@pytest.fixture
def fake_tribunal_client(monkeypatch):
    tc = pytest.importorskip("app.research.tribunal_client")
    calls = {"create_run": [], "get_metrics": []}
    def _create_run(*, brief, idempotency_key, **kw):
        calls["create_run"].append({"brief": brief, "idempotency_key": idempotency_key})
        return {"id": "fake-run-id", "status": "queued"}
    monkeypatch.setattr(tc, "create_run", _create_run)
    # ... get_metrics returns a scripted status sequence ending 'completed'
    return calls
```
**Required tests (RESEARCH § Validation, Wave 0):** trigger `decomposed`→`in_research` ok; wrong-status→409; cross-tenant trigger→existence-hidden 404; brief NEVER contains `[INTERACTIVE_REPORT]` + has enumerated questions (SEAM-04); SSE closes on `{completed,failed,cancelled}` (RESEARCH_TERMINAL); cross-tenant SSE→404, null-space→403; completion mail `to` == acting superadmin (assert via `fake_resend`); 4th attempt→no seam call (D-04); poll driver holds no DB connection across CALL (assert `engine.pool.checkedout()==0`); on_error finalizes row to `failed`. Add `research_runs` cases to the cross-tenant denial suite (STATE v1.1 two-suite blocker).

---

## Shared Patterns

### Authentication / Tenant Isolation (applies to ALL new backend reads/writes)
**Source:** `backend/app/db/ai_session.py::tenant_session` (79-96) + `_engine_and_space` (62-76)
**Apply to:** `research_routes` trigger + SSE, `run_task` mirror writes, `stream_session` read
```python
with tenant_session(identity) as session:      # re-issues SET LOCAL app.current_space_id every entry (T-7-02)
    ...                                          # superadmin → superadmin engine, no GUC; user null-space → PermissionError
```
Every research read/write goes through this. Superadmin path writes into the intake's OWN space via `create_in_space` (ai_session.py:186-188 pattern). Never a manual `WHERE space_id` — RLS + the GUC do the confinement.

### Existence-hidden 404 / 403 split (applies to trigger + SSE pre-flight)
**Source:** `stream_skill_runs` pre-flight (intake_routes.py:1105-1111) + `check_intake_in_scope` (stream_session.py:42-52)
**Apply to:** every route touching an `intake_id`
```python
try:
    in_scope = await run_in_threadpool(check_intake_in_scope, identity, intake_id)
except PermissionError:
    raise HTTPException(status.HTTP_403_FORBIDDEN, "No space — not authorized")   # null-space default-deny
if not in_scope:
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")            # cross-tenant / missing
```

### Verbatim `status` discipline (applies to model, mirror write, stream, frontend)
**Source:** `read_latest_run_dict` "status verbatim (Pitfall 1)" (stream_session.py:69) + `skillRuns.ts` COLUMN RECONCILE note (4-14)
**Apply to:** everywhere `status` crosses a boundary — carry Tribunal's literal (`queued/running/completed/failed/cancelled`) unchanged; the terminal-set check and phase machine see the exact DB literal. Never remap. The terminal set is `{completed,failed,cancelled}` on BOTH sides (backend `RESEARCH_TERMINAL` + frontend `RESEARCH_TERMINAL`), NEVER the skill-run `{succeeded,failed}`.

### Blocking sync transport (applies to seam client + mail + all handlers except SSE)
**Source:** `tribunal_client.py` (blocking `httpx.post`, 25-27 docstring) + `resend.py` (39-68)
**Apply to:** `create_run`/`get_metrics`/`get_report` and the trigger route — sync `def` on the pg8000 threadpool. The ONLY `async def` is the SSE stream handler. A coroutine calling the sync engine stalls the event loop.

### Never-fork-the-transport (frontend)
**Source:** `skillRunStream.ts` header comment (11-14) + `skillRuns.ts` (5)
**Apply to:** `research.ts` — reuse `currentIdToken` (Bearer, never in URL/log) + `apiUrl` for the stream, `apiFetch` for the trigger. Do NOT wrap `apiFetch` for the stream (it buffers via `resp.text()` and cannot stream).

### Runbook / deploy (infra)
**Source:** `infra/DEPLOY-RUNBOOK.md` Phase 13/14 sections; the "rebuild image not just env" gap (:519)
**Apply to:** new backend modules (`research_routes`, `run_task`, `research_runs` model, mail templates) MUST ship in a rebuilt `nestor-api` image (config-only env flip on a stale image is the recurring deploy-gap). Set `TRIBUNAL_SERVICE_URL` on `nestor-api` (non-secret, already typed `Settings.tribunal_service_url`). Confirm/adjust Tribunal worker `NESTOR_WORKER_STALE_MINUTES` (RESEARCH recommends 90 — above the measured 17-19 min max). Run the migration Job for 0011. No new secret (OIDC keyless; mail reuses `RESEND_API_KEY`).

## No Analog Found

None. Every file has a strong in-repo analog. The two closest-to-novel surfaces both have exact templates:
- The poll-driver loop (`run_task.py`) has no identical prior loop, but its session contract (`run_with_session_release`) and per-write discipline (`set_stage`-style own-tx-per-tick) are established — only the poll loop body inside `call_fn` is new composition, not new mechanism.
- The dynamic stage-list render (`ResearchRunProgress.tsx`) has no prior dynamic-stage component, but the SSE-first hook + intake-design-language panel are copied wholesale from `SkillRunProgress.tsx`; only the stage-list `.map` is net-new markup.

## Metadata

**Analog search scope:** `backend/app/{research,api,db,mail,core}/`, `backend/app/db/alembic/versions/`, `backend/tests/conftest.py`, `frontend/src/lib/{api,}/`, `frontend/src/components/intake/`, `frontend/src/routes/` (AlertDialog)
**Files scanned:** 15 read in full/targeted + 4 grep sweeps
**Pattern extraction date:** 2026-07-21
