# Phase 18: Human Report Upload + Client Delivery - Research

**Researched:** 2026-07-22
**Domain:** FastAPI transition verbs + GCS report artifact linking + Jinja mail delivery + new authenticated client React route (TanStack Router)
**Confidence:** HIGH — this phase is almost entirely composition of existing, deployed seams. Every building block (storage upload, signed URL, recipient picker, `results.html.j2`, transition-verb idiom, cross-tenant suite, phase machine) already exists in the codebase and was read directly this session. The only genuinely new artifacts are one backend router group (stage/deliver/replace verbs), one report-artifact linking write, and one client route + list CTA.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Delivery moment & email (REPORT-01, REPORT-03)**
- **D-01 (staged upload, explicit Deliver):** Uploading the PDF only STAGES it — superadmin can open/check/swap it, nothing is client-visible, status stays `in_research`. A separate **Deliver** action flips status to `delivered` AND sends the client email in one act. Reserved phase-machine states: `awaiting_report_upload` = no staged file, `awaiting_results_send` = staged but not delivered, `completed` = delivered + mail sent.
- **D-02 (recipient picker in the Deliver dialog):** Reuse the same picker as validation/results mails — superadmin ticks active members of the intake's space; the server resolves emails + per-recipient locale via `_resolve_active_member_emails` / `_resolve_recipient_locales`.
- **D-03 (mail = existing results template, short + link):** Reuse the Phase-10 `results.html.j2` template stack (NL/FR/EN), short body + one CTA button deep-linking to the client report page — same convention as the Phase-16 completion mails (16 D-11).

**Post-delivery changes**
- **D-04 (replace allowed after delivery):** Replace stays available after Deliver. Status stays `delivered`; the client simply gets the newest file.
- **D-05 (optional re-notify on replace):** The replace dialog asks whether to ALSO re-send the notification email (recipient picker again). Silent replace is the default-available path.
- **D-06 (delivered is one-way):** No un-deliver/retract in the UI. Before Deliver the staged file can be swapped/removed freely; after Deliver the only correction path is Replace. A true retraction is a manual/DB intervention.

**Client experience (REPORT-02)**
- **D-07 (dedicated client report page):** A NEW dedicated route (not a block on the existing results page). The page only exists/renders once the intake is `delivered`. Lay it out with Phase 19 (Q&A chat) in mind.
- **D-08 (download-only, no inline preview):** Show report metadata (filename, delivered date, size) + a download button (signed URL). No embedded PDF viewer.
- **D-09 (two entry points):** The delivery email's CTA deep-links to the report page, and the client's intake list/landing shows a "View report" CTA once `delivered`. No banner on the existing results page.

**File constraints**
- **D-10 (PDF only):** Only `.pdf` accepted — tighten the stub's `.pdf,.docx,.md,.txt` accept list. Server-side enforcement too.
- **D-11 (single file per intake):** Exactly one final report per intake; Replace swaps it. No attachments/annexes.

**Locked by prior phases (do not re-decide)**
- Run `completed` does NOT auto-deliver — the Deliver act owns `in_research → delivered` (PROJECT.md v1.1; reiterated in the intake-phase.ts Phase-16 comment).
- Nothing research-related is ever client-visible before delivery (REPORT-02; 16 D-08 strict).
- The final report is an opaque artifact from outside the system (Claude Design output built from the Phase-17 bundle's standalone `report.md` — 17 D-03).
- Every new read/write is space-scoped and joins the CI-gated cross-tenant denial suite from day one; the client report endpoints are role-checked (user sees own space only, and only when `delivered`).
- Server authors storage keys (Phase 9 D-05); uploads go through the existing storage seam.

### Claude's Discretion
- File size limit and server-side PDF validation details (D-10).
- Whether to reuse/repair `FinalReportBlock.tsx` or rebuild the admin block fresh — the stub's upload + category `"reports"` plumbing works; linking + transitions are missing.
- Exact backend shape: transition verb(s) for stage/deliver/replace, where `final_report_artifact_id` gets written, whether `results_link_sent_at` is reused as the delivered-mail timestamp or a new column is added.
- Client report page route naming and layout details (within the intake design language), including how it reserves space for the Phase-19 chat.
- What the admin intake detail shows post-delivery (summary card + delivered state visuals), and stepper (`IntakeWorkflowStepper`) handling of `delivered`.
- Whether replace keeps old file versions in GCS or overwrites (audit posture — recommend keeping old objects, cheap and reversible).

### Deferred Ideas (OUT OF SCOPE)
- **Phase 19 chat on the client report page** — reserve layout space but build NO chat UI now.
- **Inline PDF preview on the client page** — rejected (D-08).
- **Un-deliver/retract action** — rejected (D-06, one-way).
- **Report attachments/annexes** — rejected (D-11, single file).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| REPORT-01 | Superadmin can upload the final report PDF (crafted externally in Claude Design) → status `delivered` | Existing storage seam (`POST /intakes/{id}/storage/uploads`, category `"reports"` already whitelisted) stages the PDF; a NEW `POST /intakes/{id}/deliver` verb creates the report `research_artifacts` row, sets `final_report_artifact_id`, flips `in_research → delivered`, and sends mail — modeled on `submit_intake` / `_run_intake_send`. |
| REPORT-02 | Client sees and downloads the final report in their UI; nothing research-related is client-visible before delivery | New status-gated client read endpoint (`GET /intakes/{id}/report`) returns 404 unless `status == 'delivered'`; new `intake.$id.report.tsx` route reuses the `intake.$id.results.tsx` auth-guard + status-gate pattern; download via existing `GET /intakes/{id}/storage/signed-url` (prefix-scoped, attachment disposition). |
| REPORT-03 | Client receives an email notification when the report is delivered | Deliver verb calls the existing `_resolve_recipient_locales` + `mail_render.render_results` + `mail_resend.send` machinery, CTA deep-linking to the new report page; stamps `results_link_sent_at` (reuse — see Architecture). |
</phase_requirements>

## Summary

Phase 18 is a **composition phase**, not a greenfield one. The scope ceiling in `intake_routes.py` deliberately blocks any transition past `decomposed` (`_SUBMIT_TRANSITIONS` / `_REVIEW_TRANSITIONS` allow only `<= decomposed`). This phase's central backend act is to **extend that transition wall** with a dedicated `in_research → delivered` verb — following the exact `submit_intake` idiom (get → 404-gate → allow-list check → `repo.patch(status=...)` → same-tx `audit.log`) — that additionally links a report artifact and fires the client mail in one call. Every dependency it needs is already live in production: the storage upload/signed-URL seam (Phase 9, category `"reports"` already whitelisted in `keys.py`), the recipient-picker + server-side locale resolution + `results.html.j2` mail stack (Phase 10/11), the `RecipientPicker` React component, and the cross-tenant denial suite.

The one non-obvious architectural fact: **`final_report_artifact_id` is a FK-shaped pointer to a `research_artifacts` row, not a raw GCS key.** The `research_artifacts` table (`backend/app/db/models/research.py`) already carries `storage_path`, `filename`, `byte_size`, `mime_type`, `artifact_type`, `text_content`. So the Deliver flow is: (1) the staged upload writes the object to `{space}/{intake}/reports/{uuid}-{name}.pdf` via the existing storage seam; (2) the Deliver verb creates a `research_artifacts` row (`artifact_type='report'`, `storage_path`=that key) in the intake's space; (3) sets `intake.final_report_artifact_id` = that row's id; (4) flips status; (5) sends mail — all in one transaction (mail sent last, as `_run_intake_send` does, so a mail failure does not roll back the delivery). The frontend `FinalReportBlock.tsx` stub already uploads to category `"reports"` correctly but stubs out every DB-linking step; those stubs are exactly the work.

**No new table and (almost certainly) no migration is required** — `intakes.final_report_artifact_id`, `intakes.results_link_sent_at`, and the full `research_artifacts` table all exist. The intake_status enum already includes `delivered` and `archived` (schema was modeled full-fidelity in migration 0001). Reusing `results_link_sent_at` as the delivered-mail timestamp is the recommended choice (the phase machine's `delivered` branch already reads it: `status === "delivered"` → `results_link_sent_at ? "completed" : "awaiting_results_send"`), which means **zero DDL**. Deploy is therefore an image rebuild of `nestor-api` + a frontend deploy — no `nestor-migrate` Job run, no new secret, no new env var.

**Primary recommendation:** Repair `FinalReportBlock.tsx` in place (its upload path is correct); add three backend verbs (`/deliver`, `/report/replace`, and a client `GET /report` read) modeled 1:1 on `submit_intake` + `_run_intake_send`; reuse `results_link_sent_at` (no migration); build one new client route cloned from `intake.$id.results.tsx`; extend the cross-tenant suite with the three new endpoints from day one.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Stage report PDF (upload, swap, remove pre-delivery) | API / Backend (existing storage seam) | Frontend (admin block) | Server authors key, enforces size/type (D-05/D-10); browser only sends bytes + category |
| Deliver act (status flip + artifact link + mail) | API / Backend (new transition verb) | — | Status transitions are backend-only, never client-set (established pattern); one atomic verb owns all three effects |
| PDF-only + size enforcement | API / Backend (server-side) | Frontend (accept-filter UX) | D-10 mandates server-side enforcement; the `accept=".pdf"` input is UX only |
| Report artifact record | Database (`research_artifacts` row) | API | `final_report_artifact_id` is a FK to a `research_artifacts` row, not a raw key |
| Delivery email (recipient resolve, render, send) | API / Backend (`_resolve_recipient_locales` + mail stack) | Frontend (RecipientPicker) | Emails + locale resolved server-side from membership rows (D-06); browser sends only membership ids |
| Client report page (view + download) | Frontend Server (SSR route) + Browser | API (status-gated read + signed URL) | New authenticated TanStack route; download is a browser `fetch()` of a backend-minted signed URL |
| Cross-tenant / status gating on every new endpoint | API / Backend (scoped repo + 404) | Database (RLS) | Existence-hidden 404 + RLS is the isolation wall; client read additionally status-gated to `delivered` |

## Standard Stack

This phase adds **no new packages** to either the backend or the frontend. Everything is already installed and deployed. The relevant existing stack:

### Core (already present — versions from the deployed image / package manifests)
| Library | Purpose | Why Standard (in THIS codebase) |
|---------|---------|--------------------------------|
| FastAPI + pg8000 (sync handlers) | Backend routes | All intake routes are sync `def` on the blocking pg8000 driver (run in a threadpool). `[CITED: backend/app/api/intake_routes.py docstring lines 33-35]` |
| SQLAlchemy ORM + Alembic | Models + migrations | `research_artifacts`, `intakes.final_report_artifact_id` already modeled `[CITED: backend/app/db/models/research.py, intake.py]` |
| Jinja2 (autoescape ON) | Mail body render | `render_results` already renders `results.html.j2` NL/FR/EN `[CITED: backend/app/mail/render.py:108-129]` |
| Resend (faked seam in tests) | Mail transport | `mail_resend.send(to=..., subject=..., html=...)` `[CITED: backend/app/api/intake_routes.py:1032]` |
| google-cloud-storage (signBlob) | GCS upload + V4 signed URLs | Phase 9 storage seam, deployed `[CITED: backend/app/api/storage_routes.py]` |
| React 19 + TanStack Router/Query | Frontend | `intake.$id.results.tsx` is the clone target `[CITED: frontend/src/routes/intake.$id.results.tsx]` |
| react-i18next | NL/FR/EN client copy | `useTranslation("intake")` throughout; new `finalReport.*` + report-page keys needed |
| sonner (toast) | User notifications | Established pattern (never `alert()` except destructive confirm) |
| shadcn Dialog + Checkbox | Deliver/Replace dialog | `RecipientPicker.tsx` is the reusable element `[CITED: frontend/src/components/intake/RecipientPicker.tsx]` |

**Installation:** None. `npm install` / `pip install` add nothing this phase.

## Package Legitimacy Audit

Not applicable — this phase installs **no external packages** in either ecosystem. All code composes existing, already-deployed dependencies. (slopcheck not run: no install surface.)

## Architecture Patterns

### System Architecture Diagram

```
ADMIN (superadmin) — /admin/pulse/intakes/$id, status = in_research
  │
  │ 1. STAGE  (existing seam, category="reports", server enforces PDF + size)
  ▼
POST /intakes/{id}/storage/uploads ──► GCS  {space}/{intake}/reports/{uuid}-name.pdf
  │                                     (object written; status UNCHANGED = in_research)
  │                                     returns { path, filename, size, mime_type }
  │   (admin may swap/remove the staged object freely — pre-delivery)
  │
  │ 2. DELIVER  (NEW verb — RecipientPicker supplies membership ids + staged key)
  ▼
POST /intakes/{id}/deliver
  ├─ 404-gate (scoped repo.get)                     ── existence-hidden isolation
  ├─ 409 if status != "in_research"                 ── allow-list transition wall
  ├─ prefix-assert staged key startswith {space}/{intake}/   ── D-08 forged-key guard
  ├─ create research_artifacts row (artifact_type='report', storage_path=key) [in space]
  ├─ intake.final_report_artifact_id = artifact.id
  ├─ status: in_research → delivered  (repo.patch)
  ├─ audit.log("intake.status_changed", {from,to})  [SAME tx]
  ├─ resolve (email, locale) per recipient          ── _resolve_recipient_locales (D-06)
  ├─ render_results(cta = {base}/intake/{id}/report) per locale
  ├─ mail_resend.send(...)                           ── LAST; failure does NOT undo delivery
  └─ stamp results_link_sent_at on 2xx
  ▼
STATUS = delivered ──────────────────────────────────────────────┐
                                                                  │
CLIENT (user) — /intake list shows "View report" CTA (status==delivered)
  │                          + email CTA deep-link → /intake/{id}/report
  ▼
GET /intakes/{id}/report   (NEW client read — 404 unless status=='delivered')
  ├─ scoped repo.get (own-space only) → 404 otherwise
  ├─ 404 if status != 'delivered'  ── REPORT-02 absolute pre-delivery invisibility
  └─ returns { filename, delivered_at, size, mime_type, storage_path }
  ▼
Download button → GET /intakes/{id}/storage/signed-url?path=... (existing, attachment)
  ▼
browser fetch(signedUrl) → blob download

REPLACE (post-delivery, D-04/D-05): re-stage new PDF, POST /intakes/{id}/report/replace
  → new research_artifacts row + repoint final_report_artifact_id; status STAYS delivered;
    optional re-notify reuses the RecipientPicker + same mail path.
```

### Recommended Project Structure (files touched/created)

```
backend/app/api/intake_routes.py       # + /deliver, /report/replace verbs; + GET /report client read
                                        # + a _DELIVER_TRANSITIONS allow-list ({in_research: delivered})
backend/app/db/repository.py           # (likely no change — ResearchArtifactRepository.create_in_space exists)
backend/tests/test_intake_cross_tenant.py   # + deliver / report-read / replace denial cases
backend/tests/test_report_delivery.py  # NEW — happy path + status-gate + PDF-only + one-way + re-notify
frontend/src/lib/api/intakes.ts        # + deliverReport(), replaceReport(), getReport()
frontend/src/components/intake/FinalReportBlock.tsx   # repair: wire linking + Deliver dialog + PDF-only
frontend/src/routes/intake.$id.report.tsx             # NEW client report page (clone of results route)
frontend/src/routes/intake.index.tsx   # + "View report" CTA when status==delivered
frontend/src/components/intake/IntakeWorkflowStepper.tsx  # render `delivered` step
infra/DEPLOY-RUNBOOK.md                # + § Phase 18 (nestor-api rebuild + frontend deploy; NO migrate Job)
```

### Pattern 1: The transition-verb idiom (the Deliver verb's skeleton)
**What:** Discrete named POST verb, allow-list map, get→404→check→patch→audit-in-same-tx.
**When to use:** The `/deliver` and `/report/replace` verbs.
**Example:**
```python
# Source: backend/app/api/intake_routes.py:1184-1260 (submit_intake — the exact template)
_DELIVER_TRANSITIONS: dict[str, str] = {"in_research": "delivered"}

@intake_router.post("/{intake_id}/deliver")
def deliver_report(
    intake_id: str,
    body: DeliverBody,                       # { storage_path: str, recipients: list[str] }
    repo: IntakeRepository = Depends(get_tenant_repo),
    identity: Identity = Depends(get_current_identity),
) -> IntakeView:
    intake = repo.get(intake_id)
    if intake is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
    if intake.status not in _DELIVER_TRANSITIONS:          # 409 wall (parity w/ _next_submit_status)
        raise HTTPException(status.HTTP_409_CONFLICT, f"Cannot deliver in status {intake.status!r}")
    # prefix-assert the staged key against the OWN-space tree (D-08, cf. storage_routes.py:256)
    prefix = f"{intake.space_id}/{intake_id}/reports/"
    if not body.storage_path.startswith(prefix):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Object not found")
    # create the report artifact row in the intake's OWN space (superadmin has null space → create_in_space)
    artifact = artifact_repo.create_in_space(
        intake.space_id, intake_id=intake_id, artifact_type="report",
        storage_path=body.storage_path, filename=..., byte_size=..., mime_type="application/pdf",
    )
    old = intake.status
    repo.patch(intake_id, status="delivered", final_report_artifact_id=artifact.id,
               results_link_sent_at=datetime.now(timezone.utc))  # stamp AFTER mail on 2xx (see below)
    audit.log(repo.session, actor_uid=identity.uid, event_type="intake.status_changed",
              target=str(intake_id), space_id=intake.space_id, metadata={"from": old, "to": "delivered"})
    # mail LAST — a send failure must not roll back the delivery (cf. _send_admin_validated wrap)
    ...
```
> Note: the ORDER of "stamp `results_link_sent_at`" vs "send mail" differs between the two established idioms. `_run_intake_send` sends FIRST then stamps (mail is the whole point). `submit_intake`'s admin-validated mail is fire-and-forget AFTER the status flip (status is the whole point). For Deliver, the **status flip is the primary effect and must persist even if mail fails** — so flip+link+audit first, then send, then stamp `results_link_sent_at` only on a 2xx send (matching the phase machine's `delivered + results_link_sent_at == completed`). This is a genuine design decision the planner must make explicit; recommend: flip/link/audit unconditionally, mail wrapped in try/except, stamp on success. `[ASSUMED]` — the exact ordering is Claude's discretion per CONTEXT.

### Pattern 2: Server-side recipient + locale resolution (reuse verbatim)
**What:** Resolve membership ids → `(email, locale)` pairs, group by locale, render+send per group.
**When to use:** The Deliver mail and the optional re-notify.
**Example:**
```python
# Source: backend/app/api/intake_routes.py:960-1035 (_run_intake_send body — reuse this exact shape)
recipients = _resolve_recipient_locales(repo.session, intake.space_id, body.recipients)
emails_by_locale: dict[str, list[str]] = {}
for email, locale in recipients:
    emails_by_locale.setdefault(locale, []).append(email)
for locale in sorted(emails_by_locale):
    subject = _subject_for(locale, "results", client)          # reuse the "results" subject row
    html = mail_render.render_results(first_name=client, project_title=client,
        cta_url=f"{base}/intake/{intake.id}/report",           # NEW: /report, not /results
        app_base_url=settings.app_base_url, locale=locale)
    mail_resend.send(to=emails_by_locale[locale], subject=subject, html=html)
```
> The CTA changes from `/intake/{id}/results` to `/intake/{id}/report`. If `results.html.j2`'s copy is generic enough ("your results are ready") it can be reused verbatim per D-03; otherwise add a small `report.html.j2` variant. Recommend reuse first, only forking the template if the copy reads wrong for a report vs. validated-answers context. `[ASSUMED]` — verify the actual `results.html.j2` copy against the delivery context during planning.

### Pattern 3: Status-gated client read (REPORT-02 invisibility guard)
**What:** Scoped read that returns 404 unless the intake is `delivered`.
**When to use:** `GET /intakes/{id}/report` and the report page's `beforeLoad`/gate.
**Example:**
```python
# Backend: existence-hidden 404 for both cross-tenant AND pre-delivery
intake = repo.get(intake_id)                       # scoped — own space only, else None → 404
if intake is None or intake.status != "delivered":
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
```
```typescript
// Frontend gate — mirror intake.$id.results.tsx:88-92, but require exactly `delivered`
if (intakeRes.data.status !== "delivered") {
  navigate({ to: "/intake" });   // no report to show → back to list
  return;
}
```

### Anti-Patterns to Avoid
- **Generic `PATCH status` to set `delivered`:** The codebase deliberately uses discrete verbs, not a settable status field (`IntakePatch` carries no status field). A `PATCH` path to `delivered` would breach the transition-wall design. `[CITED: intake_routes.py:20-22, 127-130]`
- **Client sets `final_report_artifact_id`:** Never. It is surfaced read-only on `IntakeView`; only the Deliver/Replace verbs write it. `[CITED: intake_routes.py:98-114]`
- **Pointing `final_report_artifact_id` at a raw GCS key:** It is a FK-shaped UUID to a `research_artifacts` row. Skipping the artifact-row create would break the schema contract and the client read's metadata (filename/size come from the artifact row).
- **Auto-delivering on run completion:** Explicitly forbidden (CONTEXT locked; intake-phase.ts:65-77 comment). Run `completed` stays `in_research` until the Deliver act.
- **Making the client report visible pre-`delivered`:** REPORT-02 is absolute. The read must 404 for any non-`delivered` status, and the list CTA must only appear on `delivered`.
- **Forgetting `create_in_space` for superadmin:** A superadmin has a null-space repo; a plain `create()` hits the null-space RuntimeError guard → 500. Use `create_in_space(intake.space_id, ...)` — exactly the fix used for the audio-source create. `[CITED: storage_routes.py:209-215]`

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Report upload to GCS | A new upload endpoint | `POST /intakes/{id}/storage/uploads` category `"reports"` | Already deployed; server authors key, enforces size (25 MB) + type allowlist; `reports` already in `CATEGORIES` |
| Signed download URL | A new signing route | `GET /intakes/{id}/storage/signed-url` | Prefix-scoped, TTL-clamped, attachment disposition — already exists |
| Recipient selection UI | A new picker | `RecipientPicker.tsx` (`type` can be `results`) | Preselect-all, membership-id-only, already wired to `listSpaceMembers` |
| Email recipient/locale resolution | Address handling in the verb | `_resolve_recipient_locales` | D-06 no-free-address + D-07 locale chain, already 422-hardened |
| Delivery email body | New HTML | `render_results` + `results.html.j2` (NL/FR/EN) | D-03 mandates reuse; autoescape XSS guard already on |
| Status transition | A settable status field | A discrete `/deliver` verb + allow-list map | Matches `submit_intake`/`review_intake`; keeps the audit call-site + scope wall |
| Filename sanitization | New logic | `sanitize_filename` (backend) / `sanitizeFilenameForStorage` (frontend) | 1:1 ports already agree; the object key is server-authored anyway |
| Client report route scaffolding | From scratch | Clone `intake.$id.results.tsx` | Auth-guard (`authReady` + `beforeLoad`), status-gate, i18n, chrome all solved |

**Key insight:** This phase's risk is NOT in building new machinery — it is in **wiring existing machinery correctly and preserving the isolation/invisibility invariants**. The temptation to hand-roll is low; the temptation to skip the cross-tenant test on a "trivial" new read is the real hazard (Pitfall 1).

## Runtime State Inventory

> This is not a rename/refactor phase, but it introduces the first-ever live use of the `delivered` status and the `reports/` GCS category, so a light inventory is warranted.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | No existing `delivered` intakes; no existing `research_artifacts` rows of `artifact_type='report'`; no objects under any `{space}/{intake}/reports/` prefix (feature never shipped). Empty-start, consistent with the v1.0 empty-start decision. | None — new writes only |
| Live service config | GCS bucket already exists + hardened (Phase 9); `reports` category already in `keys.py` `CATEGORIES`; `STORAGE_BUCKET` env already set on `nestor-api`. `results_link_sent_at` column already live. | None |
| OS-registered state | No Task Scheduler / cron involvement. | None — verified: this is request-driven only |
| Secrets/env vars | `APP_BASE_URL`, `NESTOR_ADMIN_EMAIL`, `RESEND_API_KEY` all already set + required by the existing mail sends (the Deliver mail reuses the same guard: refuse-send if `APP_BASE_URL` unset). No new secret/env. | None — verified against intake_routes.py:975 guard |
| Build artifacts | The `delivered` enum value already exists in `intake_status` (migration 0001, full-fidelity). No enum ALTER needed. If NO migration is added, the `nestor-migrate` Job need NOT run this phase. | Confirm during planning that no migration lands (recommend none — reuse `results_link_sent_at`) |

**Migration decision (planner must lock):** Recommend **NO new migration**. Columns needed (`final_report_artifact_id`, `results_link_sent_at`) and the `delivered` enum value all pre-exist; `research_artifacts` is fully modeled. Reusing `results_link_sent_at` as the delivered-mail timestamp is the phase-machine-consistent choice (`delivered + results_link_sent_at → completed`). Adding a dedicated `delivered_at` column is possible but adds a migration + a `nestor-migrate` Job run for no functional gain. `[ASSUMED — recommend confirm]`

## Common Pitfalls

### Pitfall 1: Skipping the cross-tenant test on the "read-only" client report endpoint
**What goes wrong:** The `GET /intakes/{id}/report` read looks harmless, so it ships without a denial-suite case — reintroducing the broken-RLS bug class the whole project exists to prevent.
**Why it happens:** New reads feel low-risk; the suite pattern (`test_intake_cross_tenant.py`) is opt-in per endpoint.
**How to avoid:** Add three cases to the cross-tenant suite BEFORE the endpoints are considered done: (1) user-A GET user-B's `/report` → 404; (2) user-A POST user-B's `/deliver` → 404; (3) the report-read of a non-`delivered` own-space intake → 404 (the invisibility gate). CONTEXT makes this explicit: "joins the CI-gated cross-tenant denial suite from day one."
**Warning signs:** A new route lands with no corresponding `-k` case in the denial table.

### Pitfall 2: Client report becomes visible before `delivered`
**What goes wrong:** The report read gates on "own space" but not on status, so a client could read report metadata (or worse, a signed URL) while status is `in_research` — violating REPORT-02 (absolute).
**Why it happens:** The existing `intake.$id.results.tsx` gates at `validated_by_client` (a LOWER bar); copying it verbatim leaks the report early.
**How to avoid:** The report read + route gate on `status == 'delivered'` EXACTLY, not `>= delivered`. Both backend (404) and frontend (redirect). Add a denial-suite case for the pre-delivery read.
**Warning signs:** The gate uses `STATUS_RANK[...] >= STATUS_RANK.delivered` (a range) instead of an equality on `delivered`.

### Pitfall 3: Mail failure rolls back the delivery (or a delivery failure still sends mail)
**What goes wrong:** If the mail send shares the status-flip transaction and raises, the intake never reaches `delivered` — but the operator thinks it did. Conversely, sending mail before the flip persists could email a client about a report that failed to link.
**Why it happens:** The two established idioms order these differently (`_run_intake_send` sends-then-stamps; `submit_intake` flips-then-fire-and-forget-mails).
**How to avoid:** For Deliver, flip status + link artifact + audit in one committed tx FIRST; then send mail wrapped in try/except; stamp `results_link_sent_at` only on a 2xx send. A mail failure leaves the intake `delivered` but `results_link_sent_at` NULL → phase machine shows `awaiting_results_send` (a "re-send" affordance), which is the correct recoverable state.
**Warning signs:** `mail_resend.send(...)` inside the same `try` that would roll back `repo.patch(status=...)`.

### Pitfall 4: Superadmin `create()` on the report artifact 500s
**What goes wrong:** The Deliver verb creates the `research_artifacts` row with `artifact_repo.create(...)`, but a superadmin has a null-space repo → RuntimeError → 500.
**Why it happens:** Superadmins carry no `space_id` GUC; the tenant repo's `create()` guards against null-space writes.
**How to avoid:** Use `create_in_space(intake.space_id, ...)` — the exact pattern the storage route uses for the audio-source row (storage_routes.py:209-215). This works for both a user (own space) and a superadmin (intake's space).
**Warning signs:** A `.create(...)` call in the Deliver path without a superadmin branch.

### Pitfall 5: Deploying a stale image (the recurring project lesson)
**What goes wrong:** Phase 18 adds new Python modules to `nestor-api` + new frontend routes; a config-only redeploy ships the OLD image and the verbs 404 in production.
**Why it happens:** The documented recurring trap ("code is deployed only when its IMAGE is deployed" — MEMORY: phase-06/10/16 lessons).
**How to avoid:** The § Phase 18 runbook MUST rebuild the `nestor-api` image via Cloud Build (dev box has no local Docker) AND deploy the frontend image, mirroring § Phase 16 Step 16.a / § Phase 17 Step 17.b/17.d. No `nestor-migrate` Job needed IF no migration lands.
**Warning signs:** A runbook step that only flips env/tags without a Cloud Build rebuild.

### Pitfall 6: PDF-only enforced only in the file input
**What goes wrong:** The `accept=".pdf"` input filters the picker but a crafted multipart request uploads a `.docx` to the `reports/` key; the Deliver verb links it and the client downloads a non-PDF.
**Why it happens:** The storage seam's `ALLOWED_EXT` includes `.docx/.txt/.md` (16 extensions) — it does NOT restrict `reports` to PDF.
**How to avoid:** Enforce PDF server-side. Two options: (a) the Deliver verb rejects a `storage_path` not ending in `.pdf` and/or a non-`application/pdf` mime; or (b) tighten the upload gate per-category (harder — the seam is category-agnostic today). Recommend (a): validate at Deliver time (the artifact-linking moment), since staging tolerates a mistaken file that Deliver then refuses. `[ASSUMED — recommend]`
**Warning signs:** PDF restriction appears only in the React `accept` attribute.

## Code Examples

### Extending the cross-tenant denial suite (the required gate)
```python
# Source pattern: backend/tests/test_intake_cross_tenant.py (fabricated Identity + dependency_overrides).
# Add a case that a user-A POST /intakes/{B}/deliver returns EXACTLY 404 (never 403, never 200),
# AND the space-B intake is UNCHANGED on re-read as its owner (mirrors patch_cross_tenant).
# Add a case that GET /intakes/{own}/report on a non-'delivered' intake returns 404 (REPORT-02).
```

### Frontend Deliver dialog (reuse RecipientPicker with type="results")
```typescript
// Source: frontend/src/components/intake/RecipientPicker.tsx (open→load members→preselect→confirm ids)
<RecipientPicker
  open={deliverOpen}
  onOpenChange={setDeliverOpen}
  intakeId={intakeId}
  type="results"                          // reuse the results copy/subject family (D-03)
  busy={delivering}
  onConfirm={async (membershipIds) => {
    const res = await deliverReport(intakeId, { storagePath: stagedKey, recipients: membershipIds });
    if (!res.success) { toast.error(...); return; }
    toast.success(t("finalReport.delivered"));
    await reloadIntake();                 // status now `delivered` → phase machine advances
  }}
/>
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `FinalReportBlock` gated OFF (v1.0 scope stopped at `decomposed`) | This phase awakens it: wire linking + Deliver dialog + PDF-only | Phase 18 | The stub's upload path is correct; only the stubbed DB-linking/transition/fetch are the work |
| No transition past `decomposed` (scope wall) | Add `in_research → delivered` verb | Phase 18 | First-ever code that transitions into `delivered` |
| `results_link_sent_at` used for the validated-answers results mail | Also the delivered-mail timestamp (recommended reuse) | Phase 18 | Phase machine already reads it for `delivered → completed`; no migration |

**Deprecated/outdated:**
- The `FinalReportBlock.tsx` comments ("research-backend operations (Phase 7+), not wired this milestone", "scope ceiling stops at decomposed") are now STALE — Phase 18 IS that milestone. Update them when repairing the block.
- The `accept=".pdf,.docx,.md,.txt"` list on the block's file input must tighten to `.pdf` (D-10).
- The `maybeAutoDeliver` stub in the block (auto-deliver on upload) contradicts D-01 (staged upload, explicit Deliver) — remove it; delivery is a separate explicit act.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | No new migration is needed; reuse `results_link_sent_at` + existing `delivered` enum + `research_artifacts` | Runtime State Inventory / Summary | If a `delivered_at` column is preferred, a migration + `nestor-migrate` Job run is added to the phase (moderate — adds a deploy step) |
| A2 | `results.html.j2` copy is generic enough to reuse for the report-delivery mail (CTA → `/report`) | Pattern 2 | If the copy reads wrong for a report, a small `report.html.j2` NL/FR/EN variant is needed (low — additive templates) |
| A3 | Deliver ordering: flip+link+audit committed first, mail last, stamp on 2xx | Pattern 1 / Pitfall 3 | Wrong ordering could roll back a delivery on mail failure or email about a failed link (high if mis-ordered — but CONTEXT marks ordering Claude's discretion) |
| A4 | Server-side PDF enforcement is best placed at the Deliver verb (validate `storage_path`/mime) rather than per-category at upload | Pitfall 6 | If enforced at upload, the category-agnostic storage seam needs per-category logic (moderate — touches Phase 9 code) |
| A5 | `final_report_artifact_id` must FK to a `research_artifacts` row (not a raw key) | Summary / Don't Hand-Roll | Confirmed by model shape; low risk — the column is UUID and IntakeView projects it as an id, and the client read needs the artifact's filename/size |
| A6 | The client report page clones `intake.$id.results.tsx` auth pattern (`authReady` + `beforeLoad` redirect) | Pattern 3 | Low — the pattern is read directly and is the established client-auth idiom |
| A7 | Replace keeps old GCS objects (each Replace = new key + new artifact row, repoint FK) | Architecture | CONTEXT recommends keeping (cheap, reversible, audit-friendly); low risk |

## Open Questions (RESOLVED — all three answered by construction in the 18-0x plans)

1. **Does `results.html.j2` copy suit a report-delivery mail, or does the phase need a `report.html.j2` variant?**
   - What we know: D-03 says reuse the results template stack; `render_results` + NL/FR/EN variants exist and are wired.
   - What's unclear: whether the literal prose ("results ready" vs "your report is ready") reads correctly for a delivered PDF.
   - Recommendation: Read the three `results.html.j2` bodies during planning; reuse if generic, else fork to `report.html.j2` (additive, same render pattern, add a `report` row to `_SUBJECTS`).

2. **Should the delivered-mail timestamp reuse `results_link_sent_at` or add `delivered_at`?**
   - What we know: the phase machine's `delivered` branch already reads `results_link_sent_at` (`→ completed` when set).
   - What's unclear: whether the project wants a distinct audit timestamp for delivery vs. the validated-answers results mail (they'd now share a column).
   - Recommendation: Reuse `results_link_sent_at` (no migration, phase-machine-consistent). If a distinct `delivered_at` is wanted for audit clarity, that is a small additive migration — a planner decision.

3. **Where exactly is PDF enforced server-side (upload gate vs. Deliver verb)?**
   - What we know: the storage seam's `ALLOWED_EXT` permits 16 types incl. `.docx/.md/.txt`; it is category-agnostic.
   - Recommendation: Enforce at the Deliver verb (reject non-`.pdf`/non-`application/pdf` `storage_path`), so staging tolerates a wrong file that Deliver refuses — cleaner than making the shared upload gate category-aware.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| GCS bucket + signBlob IAM | Report upload + signed download | ✓ (Phase 9, deployed) | live | — |
| `reports` storage category | Report object key | ✓ (`keys.py` CATEGORIES) | live | — |
| Resend + `RESEND_API_KEY` | Delivery mail | ✓ (Phase 10, deployed; rotate post-UAT per CLOSE-02) | live | — |
| `APP_BASE_URL` / `NESTOR_ADMIN_EMAIL` | Mail CTA + guard | ✓ (set on nestor-api) | live | Deliver refuses-send if `APP_BASE_URL` unset (existing guard) |
| `results.html.j2` NL/FR/EN | Delivery mail body | ✓ | live | — |
| Cloud Build | Image rebuild (no local Docker) | ✓ (used every deploy) | — | — |
| `delivered` enum value | Status transition | ✓ (migration 0001) | live | — |
| Local Python / Docker | Running the test suite locally | ✗ | — | Tests run in Cloud Build (established); author-by-construction |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** Local test execution → Cloud Build suite run (the standing project constraint).

## Validation Architecture

> Nyquist validation is ENABLED (`workflow.nyquist_validation: true` in `.planning/config.json`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (backend); `pytest.mark.integration` gates DB-touching tests behind Docker/`DATABASE_URL` |
| Config file | `backend/tests/conftest.py` (session-scoped pgvector testcontainer, `alembic upgrade head`, `app_superadmin` role, two-space fixtures); no `pytest.ini` found — markers configured in conftest |
| Quick run command | `pytest backend/tests/test_report_delivery.py -x` (new file; runs in Cloud Build) |
| Full suite command | Cloud Build suite run (the established ~150+-test full run; dev box has no Python/Docker) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| REPORT-01 | Deliver flips `in_research → delivered`, links report artifact | integration | `pytest backend/tests/test_report_delivery.py -k deliver_transition -x` | ❌ Wave 0 |
| REPORT-01 | Deliver from a non-`in_research` status → 409 | integration | `pytest backend/tests/test_report_delivery.py -k deliver_wrong_status -x` | ❌ Wave 0 |
| REPORT-01 | Non-PDF `storage_path` at Deliver → rejected | integration | `pytest backend/tests/test_report_delivery.py -k pdf_only -x` | ❌ Wave 0 |
| REPORT-02 | Client `GET /report` on non-`delivered` intake → 404 (invisibility) | integration | `pytest backend/tests/test_report_delivery.py -k report_read_pre_delivery -x` | ❌ Wave 0 |
| REPORT-02 | user-A `GET /intakes/{B}/report` → 404 (cross-tenant) | integration | `pytest backend/tests/test_intake_cross_tenant.py -k report_cross_tenant -x` | ❌ Wave 0 (extend existing) |
| REPORT-02 | user-A `POST /intakes/{B}/deliver` → 404, B unchanged | integration | `pytest backend/tests/test_intake_cross_tenant.py -k deliver_cross_tenant -x` | ❌ Wave 0 (extend existing) |
| REPORT-03 | Deliver sends `results`-family mail to resolved recipients, stamps `results_link_sent_at` on 2xx | integration | `pytest backend/tests/test_report_delivery.py -k deliver_mail -x` | ❌ Wave 0 |
| REPORT-03 | Mail failure leaves status `delivered` but `results_link_sent_at` NULL (recoverable) | integration | `pytest backend/tests/test_report_delivery.py -k deliver_mail_failure -x` | ❌ Wave 0 |
| REPORT-01/D-04 | Replace post-delivery repoints artifact, status stays `delivered` | integration | `pytest backend/tests/test_report_delivery.py -k replace -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest backend/tests/test_report_delivery.py -x` (the new file)
- **Per wave merge:** the new file + `test_intake_cross_tenant.py` + `test_mail_endpoints.py` (regression on the shared mail path)
- **Phase gate:** Full Cloud Build suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `backend/tests/test_report_delivery.py` — NEW: covers REPORT-01/02/03 happy + status-gate + PDF-only + mail-failure + replace
- [ ] Extend `backend/tests/test_intake_cross_tenant.py` — add `deliver_cross_tenant` + `report_cross_tenant` + `report_read_pre_delivery` cases (the required day-one denial gate)
- [ ] Frontend: no test framework detected in `frontend/` (no jest/vitest config found). Client-route validation is manual/live UAT per the project's standing frontend posture (no automated FE tests exist in this repo). Flag: FE report-page gating (delivered-only) verified via live UAT session in the runbook.
- [ ] Framework install: none — pytest + conftest already present; runs in Cloud Build

## Security Domain

> `security_enforcement` not set to `false` in config → enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Multi-tenant isolation is the project's core invariant; every new endpoint space-scoped + RLS |
| V2 Authentication | yes | All new routes under `protected_router` (inherit `get_current_identity`); client route reuses `authReady` + Firebase session |
| V4 Access Control (BOLA/IDOR) | **yes (critical)** | Existence-hidden 404 on scoped `repo.get`; report read additionally status-gated to `delivered`; storage prefix-assert on any `storage_path` (D-08); the cross-tenant denial suite is the CI gate |
| V5 Input Validation | yes | Pydantic bodies (recipient membership ids, `storage_path`); server-side PDF-only + size (25 MB seam cap); `storage_path` prefix-assert prevents forged/cross-tenant keys |
| V6 Cryptography | yes (delegated) | GCS V4 signed URLs (signBlob, keyless) — never hand-rolled; TTL clamped ≤ 900s |
| V7 Error Handling | yes | 404 (never 403/200) on cross-tenant/pre-delivery; 409 on wrong-status transition; no existence leak |
| V14 Config | yes | No new secret; reuse `RESEND_API_KEY`/`APP_BASE_URL` (guard refuses-send if unset) |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Client reads report before delivery (REPORT-02 breach) | Information Disclosure | Status-gate read to `status == 'delivered'` (backend 404 + frontend redirect) + denial-suite case |
| Cross-tenant report read/deliver (BOLA) | Information Disclosure / Elevation | Scoped repo → existence-hidden 404; cross-tenant suite case from day one |
| Forged `storage_path` aimed at another tenant's tree | Tampering / Information Disclosure | `key.startswith(f"{space}/{intake}/reports/")` prefix-assert before signing/linking (D-08 idiom) |
| Non-PDF masquerading as report | Tampering | Server-side PDF enforcement at Deliver (`.pdf` + `application/pdf`) — not just the input `accept` |
| XSS via hostile filename / client_name in mail | Tampering (stored XSS) | Jinja autoescape ON (already) — every `{{ var }}` escaped |
| Mail-failure inconsistency (delivered but no notify) | Repudiation / availability | Flip+link+audit committed first; mail last; stamp on 2xx → recoverable `awaiting_results_send` |
| Signed-URL TTL over-long | Information Disclosure | Seam clamps TTL ≤ 900s; short expiry (300s default) for the download button |

## Sources

### Primary (HIGH confidence — read directly this session)
- `backend/app/api/intake_routes.py` — transition-verb idiom (`submit_intake`/`review_intake` :1184-1326), mail-send body (`_run_intake_send` :926-1049), `_resolve_active_member_emails`/`_resolve_recipient_locales` :698-799, `_SUBJECTS` :653-679, `IntakeView` :98-114, `_view` :284-311, scope-ceiling docstring :26-29
- `backend/app/api/storage_routes.py` — upload/signed-url/delete seam, prefix-assert :256, `create_in_space` superadmin fix :209-215, size/type gates
- `backend/app/storage/keys.py` — `CATEGORIES` (incl. `reports`) :35, `ALLOWED_EXT` :39-58, `build_object_key` :90-104
- `backend/app/db/models/intake.py` — `final_report_artifact_id`/`results_link_sent_at` columns, `delivered` enum value :41-53, 87-89
- `backend/app/db/models/research.py` — `ResearchArtifact` (`storage_path`/`filename`/`byte_size`/`mime_type`/`artifact_type`/`text_content`) :125-170
- `backend/app/mail/render.py` — `render_results` + localized-template selector :42-129
- `backend/app/db/repository.py` — `TenantRepository.get/patch/create/create_in_space` :96-183; `ResearchArtifactRepository`, `IntakeRepository`
- `backend/app/db/alembic/versions/0011_research_runs.py` — the new-tenant-table RLS/grant idiom (reference if any table were needed — it isn't)
- `backend/tests/test_intake_cross_tenant.py` — denial-suite pattern (fabricated Identity, dependency_overrides, `-k` case table) :1-120
- `backend/tests/conftest.py` — pytest fixtures (pgvector container, `alembic upgrade head`, two-space, app_superadmin)
- `frontend/src/components/intake/FinalReportBlock.tsx` — the stub to repair (correct upload, stubbed linking/transition/fetch, `.pdf,.docx,.md,.txt` accept, `maybeAutoDeliver` stub)
- `frontend/src/lib/intake-phase.ts` — reserved states + `delivered` branch :65-84, visibility helpers :112-119
- `frontend/src/routes/intake.$id.results.tsx` — client-route clone target (auth-guard, status-gate :88-92, i18n)
- `frontend/src/routes/intake.index.tsx` — list + `rowCta` (where the "View report" CTA lands) :67-72
- `frontend/src/components/intake/RecipientPicker.tsx` — reusable Deliver-dialog picker
- `frontend/src/lib/api/intakes.ts` / `storage.ts` — the API seams to extend
- `frontend/src/routes/admin.pulse.intakes.$id.tsx` — FinalReportBlock wiring :1457-1476 (note: the existing `onChange` auto-deliver-on-upload logic contradicts D-01 and must be replaced with the staged/explicit-Deliver flow)
- `infra/DEPLOY-RUNBOOK.md` — § Phase 16 Step 16.a (Cloud Build rebuild idiom), § Phase 17 Step 17.b/17.d (backend+frontend image deploy) — the § Phase 18 template
- `.planning/config.json` — nyquist_validation enabled, code_review standard
- `.planning/REQUIREMENTS.md` — REPORT-01/02/03
- CONTEXT.md — all D-01..D-11 decisions

### Secondary (MEDIUM confidence)
- Project MEMORY entries: recurring "code deployed only when IMAGE deployed" lesson (phase-06/10/16), dev-machine-no-Python/Docker (Cloud Build for tests), `skill-run status "succeeded"` contract (status-vocabulary discipline analog)

### Tertiary (LOW confidence)
- None — this phase required no web/external research; all findings are codebase-verified.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; every dependency read directly and confirmed deployed
- Architecture: HIGH — the Deliver verb, artifact-linking, mail reuse, and client route all map 1:1 onto existing, read code; the one open design point (timestamp reuse vs. new column) is flagged and recommended
- Pitfalls: HIGH — derived from the project's own recurring lessons (stale image, cross-tenant gate, superadmin null-space, status-vocabulary) and the specific REPORT-02 invisibility invariant

**Research date:** 2026-07-22
**Valid until:** ~30 days (stable internal codebase; no fast-moving external deps). Re-verify only if the storage seam, mail stack, or phase machine changes before planning.
