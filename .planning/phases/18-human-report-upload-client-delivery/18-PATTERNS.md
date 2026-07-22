# Phase 18: Human Report Upload + Client Delivery - Pattern Map

**Mapped:** 2026-07-22
**Files analyzed:** 9 (2 new, 7 modified)
**Analogs found:** 9 / 9 (every file has a strong in-repo analog — this is a composition phase)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/api/intake_routes.py` (+ `/deliver`, `/report/replace`, `GET /report`) | route/controller | request-response + transition | `submit_intake` / `review_intake` / `_run_intake_send` (same file) | exact |
| `backend/tests/test_report_delivery.py` (NEW) | test | request-response | `backend/tests/test_intake_cross_tenant.py` + `test_mail_endpoints.py` | role-match |
| `backend/tests/test_intake_cross_tenant.py` (extend) | test | request-response | itself (add 3 `-k` cases) | exact |
| `frontend/src/components/intake/FinalReportBlock.tsx` (repair) | component | file-I/O + transition | itself (stub) + `RecipientPicker.tsx` for the dialog | exact |
| `frontend/src/routes/intake.$id.report.tsx` (NEW) | route | request-response (read + download) | `frontend/src/routes/intake.$id.results.tsx` | exact |
| `frontend/src/routes/intake.index.tsx` (+ "View report" CTA) | route | request-response | itself (`rowCta` helper) | exact |
| `frontend/src/lib/api/intakes.ts` (+ `deliverReport`/`replaceReport`/`getReport`) | utility/api-seam | request-response | itself (`submitIntake` / `sendIntakeMail`) | exact |
| `frontend/src/components/intake/IntakeWorkflowStepper.tsx` (render `delivered`) | component | transform | itself (already models `delivered`) | exact |
| `frontend/src/lib/intake-phase.ts` (wire inputs) | utility | transform | itself (reserved `delivered` branch, lines 74-81) | exact |

**Load-bearing backend facts (do not re-derive):**
- `final_report_artifact_id` is a **FK to a `research_artifacts` row**, not a raw GCS key. The row carries `storage_path`, `filename`, `byte_size`, `mime_type`, `artifact_type` (`backend/app/db/models/research.py:125-160`). The Deliver verb must CREATE that row, then set `intake.final_report_artifact_id = artifact.id`.
- A superadmin has a null-space repo → a plain `.create(...)` hits a `RuntimeError` guard (`repository.py:167-169`). Use `create_in_space(intake.space_id, ...)` (see storage-route analog below). `ResearchArtifactRepository` is a thin `TenantRepository` subclass so it inherits `create` / `create_in_space` (`repository.py:513-525`, `133-171`).
- `IntakePatch` carries **no status field** — status moves ONLY via discrete verbs, never `PATCH` (`intake_routes.py:20-22`, `127-130`).

---

## Pattern Assignments

### `backend/app/api/intake_routes.py` — the `/deliver` verb (route, transition)

**Analog:** `submit_intake` (`intake_routes.py:1215-1260`) for the transition skeleton; `_run_intake_send` (`intake_routes.py:926-1049`) for the mail body.

**Transition allow-list + verb skeleton** (copy shape from `intake_routes.py:1184-1240`):
```python
_DELIVER_TRANSITIONS: dict[str, str] = {"in_research": "delivered"}

@intake_router.post("/{intake_id}/deliver")
def deliver_report(intake_id, body, repo=Depends(get_tenant_repo), identity=Depends(get_current_identity)):
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")   # existence-hidden (D-07)
    if intake.status not in _DELIVER_TRANSITIONS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot deliver in status {intake.status!r}")
    # ... link artifact, flip status, audit in SAME tx, then mail LAST
    old_status = intake.status
    repo.patch(intake_id, status="delivered", final_report_artifact_id=artifact.id)
    audit.log(repo.session, actor_uid=identity.uid, event_type="intake.status_changed",
              target=str(intake_id), space_id=intake.space_id,
              metadata={"from": old_status, "to": "delivered"})   # SAME tx — commits/rolls back together
```

**Forged-key prefix-assert** (copy from `storage_routes.py:256-259`), applied to the staged `body.storage_path`:
```python
prefix = f"{intake.space_id}/{intake_id}/reports/"
if not body.storage_path.startswith(prefix):
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Object not found")   # D-08 forged/cross-tenant guard
```

**Artifact-row create — superadmin-safe** (copy the branch from `storage_routes.py:209-215`):
```python
artifact_repo.create_in_space(
    intake.space_id, intake_id=intake_id, artifact_type="report",
    storage_path=body.storage_path, filename=..., byte_size=..., mime_type="application/pdf",
)
# NEVER a plain .create() — a superadmin's null-space repo would 500 (repository.py:167-169)
```

**PDF-only server enforcement** (D-10 — new logic, no analog; place at Deliver, per RESEARCH Pitfall 6): reject `storage_path` not ending `.pdf` and/or non-`application/pdf` mime with 404/422.

**Mail body — reuse verbatim** from `_run_intake_send` (`intake_routes.py:960-1032`), changing ONLY the CTA path:
```python
recipients = _resolve_recipient_locales(repo.session, intake.space_id, body.recipients)  # D-06 (:742-799)
emails_by_locale: dict[str, list[str]] = {}
for email, locale in recipients:
    emails_by_locale.setdefault(locale, []).append(email)
if not settings.app_base_url:            # existing guard (:975) — refuse-send, never stamp a broken mail
    return {"success": False}
base = settings.app_base_url.rstrip("/")
for locale in sorted(emails_by_locale):
    subject = _subject_for(locale, "results", client)                     # reuse "results" subject (:653-679)
    html = mail_render.render_results(first_name=client, project_title=client,
        cta_url=f"{base}/intake/{intake.id}/report",                      # NEW: /report (was /results)
        app_base_url=settings.app_base_url, locale=locale)
    mail_resend.send(to=emails_by_locale[locale], subject=subject, html=html)
```

**Ordering (design decision — RESEARCH A3 / Pitfall 3):** flip status + link artifact + audit committed FIRST; then send mail wrapped in `try/except`; stamp `results_link_sent_at` (`datetime.now(timezone.utc)`) only on a 2xx send (mirrors `_run_intake_send:1039-1040`). A mail failure leaves the intake `delivered` but `results_link_sent_at` NULL → phase machine shows `awaiting_results_send` (a recoverable re-send state — see `intake-phase.ts:79-81`).

**`/report/replace` (D-04/D-05):** same body, but no status transition (stays `delivered`); create a new artifact row + repoint `final_report_artifact_id`; optional re-notify reuses the identical mail block.

**`GET /report` client read (status-gated, REPORT-02):** clone the `repo.get` 404-gate but ALSO gate on exactly `delivered`:
```python
intake = repo.get(intake_id)                                 # scoped — own space only, else None → 404
if intake is None or intake.status != "delivered":           # exact equality, NOT >= (Pitfall 2)
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
# return { filename, delivered_at (=results_link_sent_at), byte_size, mime_type, storage_path } from the artifact row
```

**Request model** (mirror `MailRecipients` + add `storage_path`): `{ storage_path: str, recipients: list[str] }`. `space_id` is NEVER in the body (TENANT-02, `intake_routes.py:18-22`).

---

### `frontend/src/components/intake/FinalReportBlock.tsx` (component, file-I/O + transition) — REPAIR IN PLACE

**Analog:** itself (upload path is correct at lines 68-94) + `RecipientPicker.tsx` for the Deliver dialog.

**Keep as-is:** `sanitizeFilenameForStorage` (:23-33), `bytesLabel` (:16-21), the drag-drop zone (:196-266), `onDownload` signed-URL flow (:112-138), `storage.uploadFile({ category: "reports" })` (:74-80).

**Repair (the stubbed work):**
- `useEffect` at :54-59 — replace the `void finalReportArtifactId; setArtifact(null)` stub with a real fetch of the report metadata (new `getReport(intakeId)`).
- Remove `maybeAutoDeliver` (:61-66) entirely — it contradicts D-01 (staged upload, explicit Deliver).
- `onPick` (:68-94) — after upload, STAGE (hold the returned `path`/meta in local state); do NOT call `onChange`/deliver. Delivery is a separate explicit act.
- Tighten `accept=".pdf,.docx,.md,.txt"` (:211) → `accept=".pdf"` (D-10).
- Update the STALE comments at :55-56, :82-84, :100-101, :147-149 (they say "Phase 7+, not wired this milestone" / "scope ceiling stops at decomposed" — Phase 18 IS that milestone).

**Deliver dialog — reuse `RecipientPicker` with `type="results"`** (analog `RecipientPicker.tsx:27-41`, `85` preselect-all):
```tsx
<RecipientPicker
  open={deliverOpen} onOpenChange={setDeliverOpen} intakeId={intakeId}
  type="results" busy={delivering}
  onConfirm={async (membershipIds) => {
    const res = await deliverReport(intakeId, { storagePath: stagedKey, recipients: membershipIds });
    if (!res.success) { toast.error(...); return; }
    toast.success(t("finalReport.delivered"));
    await onChange(res.data.final_report_artifact_id);   // status now `delivered` → phase machine advances
  }}
/>
```
Note the admin wiring at `admin.pulse.intakes.$id.tsx:1457-1476` — its `onChange` currently fakes the `delivered` bump client-side (`:1468-1471`); replace with the real post-`deliverReport` reload (the backend now owns the transition).

**Error/loading/toast conventions:** already correct in the stub — `try/finally` + `toast.error(t(...))` + `busy` state (:88-93). Keep them.

---

### `frontend/src/routes/intake.$id.report.tsx` (NEW route) — CLONE of `intake.$id.results.tsx`

**Analog:** `frontend/src/routes/intake.$id.results.tsx` (read whole file — auth-guard, status-gate, i18n, cancel-flag).

**Auth guard — copy verbatim** (`intake.$id.results.tsx:24-42`):
```tsx
function authReady(): Promise<User | null> { /* onAuthStateChanged first-tick resolve */ }
export const Route = createFileRoute("/intake/$id/report")({
  beforeLoad: async () => { const user = await authReady(); if (!user) throw redirect({ to: "/auth/login" }); },
  component: UserIntakeReportPage,
});
```

**Status gate — CHANGE the bar to exactly `delivered`** (the results route gates at `validated_by_client` via `isValidatedOrLater`, `:57-92` — a LOWER bar that would leak the report early, RESEARCH Pitfall 2):
```tsx
// Mirror :88-92 BUT require exactly delivered (not >=)
if (intakeRes.data.status !== "delivered") {
  navigate({ to: "/intake" });   // no report to show → back to list
  return;
}
```

**Data-load pattern:** copy the `let cancelled = false` useEffect + `getIntake(id)` + `ApiResult` handling (`intake.$id.results.tsx:76-120`). Replace the answers/template load with `getReport(id)`.

**Download button:** reuse the signed-URL blob flow from `FinalReportBlock.onDownload` (`FinalReportBlock.tsx:112-138`) — `storage.signedDownloadUrl` → `fetch` → `blob` → anchor click.

**Layout (D-07):** metadata card (filename, delivered date, size) + download button only, NO inline PDF viewer (D-08). Reserve visual space below for the Phase-19 Q&A chat (build no chat UI). Use the intake design language (font-mono labels, `border-ink`, `bg-paper` — see the results route + `FinalReportBlock` section styling).

---

### `frontend/src/routes/intake.index.tsx` (+ "View report" CTA) — EXTEND `rowCta`

**Analog:** itself, `rowCta` (`intake.index.tsx:62-72`) + `openRow` (`:105-112`).

**Add a `delivered` branch** to `rowCta` and a `report` target:
```tsx
type RowCta = { label: string; target: "fill" | "results" | "report" };
function rowCta(status, t): RowCta {
  if (status === "draft") return { label: t("list.ctaFill"), target: "fill" };
  if (status === "submitted" || status === "reviewed") return { label: t("list.ctaView"), target: "fill" };
  if (status === "delivered") return { label: t("list.ctaReport"), target: "report" };   // NEW (D-09)
  return { label: t("list.ctaResult"), target: "results" };
}
```
And route it in `openRow` (`:105-112`): `if (cta.target === "report") navigate({ to: "/intake/$id/report", params: { id: row.id } })`. Add the `list.ctaReport` i18n key (NL/FR/EN).

---

### `frontend/src/lib/api/intakes.ts` (+ verbs) — EXTEND the seam

**Analog:** itself — `submitIntake` (`:71-73`), `sendIntakeMail` (`:124-133`), `getIntake` (`:35-37`).
```ts
export function deliverReport(id: string, input: { storagePath: string; recipients: string[] }) {
  return apiFetch<Intake>(`/intakes/${id}/deliver`, {
    method: "POST", body: JSON.stringify({ storage_path: input.storagePath, recipients: input.recipients }),
  });
}
export function replaceReport(id: string, input: { storagePath: string; recipients?: string[] }) { /* POST /intakes/{id}/report/replace */ }
export function getReport(id: string) { return apiFetch<ReportView>(`/intakes/${id}/report`, { method: "GET" }); }
```
Mirror the `ApiResult<T>` union return and the `snake_case` body-field convention (`storage_path`, not `storagePath`, on the wire). Add a `ReportView` type mirroring the backend `GET /report` shape.

---

### `frontend/src/components/intake/IntakeWorkflowStepper.tsx` — verify `delivered` render

**Analog:** itself — already models `delivered` as the 6th and final step (`:12-21`, `isDelivered` at `:41`, past-marking `cur > i || isDelivered` at `:60`). Likely needs only a `submittedAt`/`clientValidatedAt`-style timestamp for the delivered step if a delivered stamp is wanted; otherwise no change beyond confirming it renders when `status === "delivered"`.

---

### `frontend/src/lib/intake-phase.ts` — wire the inputs (no logic change)

**Analog:** itself — the `in_research` branch (`:65-77`) and `delivered` branch (`:79-81`) already encode the flow:
```ts
if (intake.final_report_artifact_id) return "awaiting_results_send";   // staged, pre-mail
// ...
if (status === "delivered") return intake.results_link_sent_at ? "completed" : "awaiting_results_send";
```
The visibility helpers `phaseShowsFinalReport` (`:112-119`) already include the four post-research phases. **The work is feeding real inputs** (`final_report_artifact_id`, `results_link_sent_at`) — currently `FinalReportBlock` passes hard-coded `null`s to `derivePhase` (`FinalReportBlock.tsx:150-160`). No state-machine change; update the STALE Phase-16 comment block (`:65-73`) noting Phase 18 now writes these.

---

## Shared Patterns

### Existence-hidden 404 + transition-wall (ALL new backend endpoints)
**Source:** `intake_routes.py:1230-1236` (get→404), `:1193-1201` (409 allow-list), `storage_routes.py:256-259` (prefix-assert).
**Apply to:** `/deliver`, `/report/replace`, `GET /report`.
```python
intake = repo.get(intake_id)
if intake is None:
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")   # never 403, never 200-with-data
```

### Same-tx audit on status change
**Source:** `intake_routes.py:1237-1240`.
**Apply to:** `/deliver` (the one status transition). `audit.log(repo.session, ...)` on the SAME session so it commits/rolls back with the `repo.patch`. `metadata` is structured `{"from","to"}` only — never a link/token.

### Server-side recipient + locale resolution (D-06 no-free-address)
**Source:** `_resolve_recipient_locales` (`intake_routes.py:742-799`), `_subject_for` (`:675-679`), `_run_intake_send` mail loop (`:1003-1032`).
**Apply to:** the Deliver mail + the optional replace re-notify. Browser sends membership ids only; server resolves `(email, locale)` and 422-rejects any non-active/foreign/email-less id.

### `create_in_space` for superadmin writes
**Source:** `storage_routes.py:209-215`, guard at `repository.py:157-171`.
**Apply to:** the report `research_artifacts` create in `/deliver` and `/report/replace`.

### Cross-tenant denial suite from day one (CI gate — mandatory)
**Source:** `backend/tests/test_intake_cross_tenant.py` — fabricated `Identity` (`:104-125`), engine-factory patch (`:31-54`), `-k` case table (`:13-29`), `pytestmark = pytest.mark.integration` + `importorskip` (`:70-81`).
**Apply to:** add THREE cases (RESEARCH Pitfall 1): `deliver_cross_tenant` (user-A POST /intakes/{B}/deliver → 404, B unchanged on owner re-read — mirror `patch_cross_tenant`), `report_cross_tenant` (user-A GET /intakes/{B}/report → 404), `report_read_pre_delivery` (own-space non-`delivered` GET /report → 404, the REPORT-02 invisibility gate).

### Frontend client-route conventions
**Source:** `intake.$id.results.tsx:24-42` (auth guard), `:76-120` (cancel-flag load), `intake.index.tsx:35-55` (guard mirror).
**Apply to:** `intake.$id.report.tsx`. NEVER weaken the gate below exactly `delivered`.

### Frontend error/notification conventions (project-wide, CLAUDE.md)
**Source:** `FinalReportBlock.tsx:88-93`, `RecipientPicker.tsx:78-83`.
**Apply to:** all new UI. `try/finally` clears `busy`; user-facing errors via `sonner` `toast.error(t(...))`; loading via `Skeleton`; `ApiResult` union checked (`if (!res.success)`), no throw across the seam.

---

## No Analog Found

None. Every file has a strong in-repo analog. The only genuinely NEW logic (no direct analog) is small and local:
- Server-side PDF-only enforcement in `/deliver` (D-10) — a simple suffix/mime check; no pattern needed.
- The `ReportView` response shape (`GET /report`) — a straightforward projection of the `research_artifacts` row fields.

---

## Metadata

**Analog search scope:** `backend/app/api/`, `backend/app/db/`, `backend/app/mail/`, `backend/app/storage/`, `backend/tests/`, `frontend/src/routes/`, `frontend/src/components/intake/`, `frontend/src/lib/api/`, `frontend/src/lib/`
**Files scanned (read + verified):** 14 (intake_routes.py ×3 ranges, storage_routes.py, research.py, repository.py grep, render.py, test_intake_cross_tenant.py, FinalReportBlock.tsx, intake.$id.results.tsx, intake.index.tsx, intake-phase.ts, intakes.ts, storage.ts, RecipientPicker.tsx, IntakeWorkflowStepper.tsx, admin.pulse.intakes.$id.tsx wiring)
**Pattern extraction date:** 2026-07-22
