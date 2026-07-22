# Phase 18: Human Report Upload + Client Delivery - Context

**Gathered:** 2026-07-22
**Status:** Ready for planning

<domain>
## Phase Boundary

The superadmin uploads the externally crafted final report PDF (made in Claude Design from the
Phase-17 bundle's `report.md`), reviews it, and explicitly delivers it — flipping the intake from
`in_research` to `delivered`, making the report visible/downloadable to the client on a dedicated
client report page, and emailing the client. Nothing research-related is client-visible before
that Deliver act (REPORT-02, absolute).

Requirements: REPORT-01, REPORT-02, REPORT-03.

**Out of scope:** Q&A chat / findings indexing (Phase 19 — though the new client report page is
its future home), raw-output download changes (Phase 17, done), engine work (Phase 15, deferred),
run `completed` auto-advancing status (explicitly forbidden — the Deliver act owns the
transition), un-deliver/retraction UI (rejected, see D-06), inline PDF preview (rejected, see
D-08), client-admin role.

**Builds directly on:** Phase 16's status machine (`in_research` is where this phase picks up),
Phase 9 GCS storage (upload plumbing exists), Phase 10 mail stack (recipient picker + Jinja
templates incl. an existing `results.html.j2`), and the dormant v1.0 scaffolding: the frontend
phase machine already has `awaiting_report_upload → awaiting_results_send → completed` states
reserved for this flow, and `FinalReportBlock.tsx` is a gated-off upload stub.

</domain>

<decisions>
## Implementation Decisions

### Delivery moment & email (REPORT-01, REPORT-03)
- **D-01 (staged upload, explicit Deliver):** Uploading the PDF only STAGES it — superadmin can
  open/check/swap it, nothing is client-visible, status stays `in_research`. A separate
  **Deliver** action flips status to `delivered` AND sends the client email in one act. This
  matches the reserved phase-machine states (`awaiting_report_upload` = no staged file,
  `awaiting_results_send` = staged but not delivered, `completed` = delivered + mail sent) and
  the app's explicit-send mail pattern.
- **D-02 (recipient picker in the Deliver dialog):** The Deliver dialog embeds the same
  recipient picker as the existing validation/results mails — superadmin ticks active members of
  the intake's space; the server resolves emails + per-recipient locale via the existing D-06
  no-free-address machinery (`_resolve_active_member_emails` / `_resolve_recipient_locales`).
- **D-03 (mail = existing results template, short + link):** Reuse the Phase-10
  `results.html.j2` template stack (NL/FR/EN), short body + one CTA button deep-linking to the
  client report page — same convention as the Phase-16 completion mails (16 D-11).

### Post-delivery changes
- **D-04 (replace allowed after delivery):** Replace stays available after Deliver — corrected
  versions are expected. Status stays `delivered`; the client simply gets the newest file.
- **D-05 (optional re-notify on replace):** The replace dialog asks whether to ALSO re-send the
  notification email (recipient picker again). Silent replace is the default-available path.
- **D-06 (delivered is one-way):** No un-deliver/retract in the UI. Before Deliver the staged
  file can be swapped/removed freely; after Deliver the only correction path is Replace. A true
  retraction is a manual/DB intervention.

### Client experience (REPORT-02)
- **D-07 (dedicated client report page):** The client sees the report on a NEW dedicated route
  (not a block on the existing validated-answers results page). The page only exists/renders
  once the intake is `delivered`. Lay it out with Phase 19 in mind — the Q&A chat will live on
  this page later.
- **D-08 (download-only, no inline preview):** The page shows report metadata (filename,
  delivered date, size) + a download button (signed URL). No embedded PDF viewer.
- **D-09 (two entry points):** The delivery email's CTA deep-links to the report page, and the
  client's intake list/landing shows a "View report" CTA once `delivered`. No banner on the
  existing results page.

### File constraints
- **D-10 (PDF only):** Only `.pdf` is accepted — tighten the stub's `.pdf,.docx,.md,.txt`
  accept list. Server-side enforcement too, not just the file input.
- **D-11 (single file per intake):** Exactly one final report per intake; Replace swaps it. No
  attachments/annexes.

### Locked by prior phases (do not re-decide)
- Run `completed` does NOT auto-deliver — the Deliver act owns `in_research → delivered`
  (PROJECT.md v1.1 decision; reiterated in the intake-phase.ts Phase-16 comment).
- Nothing research-related is ever client-visible before delivery (REPORT-02; 16 D-08 strict).
- The final report is an opaque artifact from outside the system (Claude Design output built
  from the Phase-17 bundle's standalone `report.md` — 17 D-03).
- Every new read/write is space-scoped and joins the CI-gated cross-tenant denial suite from
  day one; the client report endpoints are role-checked (user sees own space only, and only
  when `delivered`).
- Server authors storage keys (Phase 9 D-05); uploads go through the existing storage seam.

### Claude's Discretion
- File size limit and server-side PDF validation details (D-10).
- Whether to reuse/repair `FinalReportBlock.tsx` or rebuild the admin block fresh — the stub's
  upload + category `"reports"` plumbing works; linking + transitions are missing.
- Exact backend shape: transition verb(s) for stage/deliver/replace, where
  `final_report_artifact_id` gets written, whether `results_link_sent_at` is reused as the
  delivered-mail timestamp or a new column is added.
- Client report page route naming and layout details (within the intake design language),
  including how it reserves space for the Phase-19 chat.
- What the admin intake detail shows post-delivery (summary card + delivered state visuals),
  and stepper (`IntakeWorkflowStepper`) handling of `delivered`.
- Whether replace keeps old file versions in GCS or overwrites (audit posture — recommend
  keeping old objects, cheap and reversible).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prior phase context (decisions carried forward)
- `.planning/phases/17-raw-output-audit-chain-guard/17-CONTEXT.md` — D-03: `report.md` in the
  bundle exists to feed Claude Design for THIS phase's PDF; summary-card anchor decisions
- `.planning/phases/16-research-trigger-progress-bridge/16-CONTEXT.md` — D-08 client sees
  nothing during research; D-09 completion summary card; D-11 mail style
- `.planning/ROADMAP.md` § Phase 18 — goal + 3 success criteria
- `.planning/REQUIREMENTS.md` — REPORT-01/02/03

### Frontend (dormant v1.0 scaffolding this phase awakens)
- `frontend/src/lib/intake-phase.ts` — phase machine with RESERVED states
  `awaiting_report_upload` / `awaiting_results_send` / `completed`; the Phase-16 comment block
  (lines ~65-77) explicitly assigns the `final_report_artifact_id` branches to this phase
- `frontend/src/components/intake/FinalReportBlock.tsx` — gated-off v1.0 stub: working
  drag-drop + storage upload (category `"reports"`), stubbed linking/transition/fetch
- `frontend/src/components/intake/ResearchRunProgress.tsx` — Phase 16/17 summary card the admin
  delivery block sits alongside
- `frontend/src/routes/intake.$id.results.tsx` — client results route (validated answers);
  pattern for the NEW dedicated client report route (auth guard, status gating, i18n)
- `frontend/src/routes/intake.index.tsx` — client intake list where the "View report" CTA lands
- `frontend/src/components/intake/IntakeWorkflowStepper.tsx` — stepper that must render
  `delivered` correctly
- `frontend/src/lib/api/storage.ts` + `frontend/src/lib/api/intakes.ts` — API layers to extend

### Backend (where the new code lands)
- `backend/app/api/intake_routes.py` — transition-verb patterns; mail send endpoints
  (~lines 637-960): `_resolve_active_member_emails` / `_resolve_recipient_locales` (D-06
  no-free-address) + per-locale subjects (D-12) the delivery mail reuses;
  `final_report_artifact_id` currently surfaced read-only (~lines 102-114, 306-308)
- `backend/app/api/storage_routes.py` — Phase 9 upload/signed-URL endpoints (server-authored
  keys) the staged upload goes through
- `backend/app/storage/gcs.py` + `backend/app/storage/keys.py` — GCS plumbing + space-scoped
  key conventions
- `backend/app/mail/` (render.py, resend.py, templates/ incl. `results.html.j2` NL/FR/EN) —
  the delivery mail stack (D-03)
- `backend/app/db/models/intake.py` — `final_report_artifact_id`, `results_link_sent_at`
  columns; where delivered-state fields live
- `backend/tests/test_intake_cross_tenant.py` — denial-suite pattern ALL new endpoints join
  (staging, deliver, client report read/download)

### Deploy
- `infra/DEPLOY-RUNBOOK.md` — runbook to extend (frontend + backend deploy, live UAT session)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- Phase machine states for this exact flow already exist and are additive-safe — wiring inputs
  (`final_report_artifact_id`, `results_link_sent_at`-equivalent) is the work, not new states.
- `FinalReportBlock.tsx` stub — working upload UI + storage call; needs artifact linking,
  staged/delivered states, Deliver dialog.
- Mail machinery end-to-end: recipient picker UI (validation/results sends), server-side D-06
  resolution, per-locale subjects, `results.html.j2` template — delivery mail is mostly reuse.
- Phase 9 storage seam: server-authored keys, signed download URLs (Phase 17 just used the same
  for bundles).
- Client route patterns: `intake.$id.results.tsx` shows auth-guarding, status-gating, and i18n
  conventions for the new report page.

### Established Patterns
- Backend handlers sync `def` on pg8000; status transitions via explicit verbs, never client-set
  status fields.
- Every new endpoint: space-scoped session + cross-tenant denial tests from day one; client
  endpoints additionally role/status-gated (only own space, only when `delivered`).
- Confirm dialogs before consequential actions (16 D-03 trigger dialog is the visual pattern for
  the Deliver dialog).
- Deploys by-construction + operator runbook; Cloud Build for images (no local Python/Docker).

### Integration Points
- Admin intake detail (`admin.pulse.intakes.$id.tsx`): upload/deliver block appears for
  `in_research` (post-run-completion) alongside the Phase-16/17 summary card; NextStepBanner CTA
  follows the phase machine.
- Status machine: `in_research` --Deliver--> `delivered`; `completed` phase = delivered + mail
  sent. Run completion does NOT touch status.
- Client: new report route + list CTA keyed off intake status `delivered`.
- Email: Deliver (and optional re-notify on replace) → mail stack → CTA deep-link to client
  report page.

</code_context>

<specifics>
## Specific Ideas

- The operator's workflow: download Phase-17 bundle → craft report in Claude Design externally →
  upload PDF here → check it → Deliver. The staging step exists precisely because the file
  comes from outside the system and a wrong-file mistake must not reach the client.
- Dedicated client report page chosen over a results-page block explicitly — and it should be
  laid out as the future home of the Phase-19 Q&A chat (report + chat = the client's
  post-delivery hub).

</specifics>

<deferred>
## Deferred Ideas

- **Phase 19 chat on the client report page** — the page built this phase is its future home;
  reserve layout space but build NO chat UI now.
- **Inline PDF preview on the client page** — rejected for this phase (D-08); revisit if
  clients ask for it.
- **Un-deliver/retract action** — rejected (D-06, one-way); revisit only if a real incident
  demands it.
- **Report attachments/annexes** — rejected (D-11, single file); a future need would be its own
  scope.

</deferred>

---

*Phase: 18-Human Report Upload + Client Delivery*
*Context gathered: 2026-07-22*
