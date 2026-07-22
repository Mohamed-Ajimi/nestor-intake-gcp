# Phase 18: Human Report Upload + Client Delivery - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 18-human-report-upload-client-delivery
**Areas discussed:** Delivery moment & email, Post-delivery changes, Client experience, File constraints

---

## Delivery moment & email

**Q1: What happens when the superadmin uploads the final report PDF?**

| Option | Description | Selected |
|--------|-------------|----------|
| Staged, then Deliver (Recommended) | Upload stores the PDF but nothing is client-visible; separate Deliver button flips status + sends mail in one act; review moment before client sees anything | ✓ |
| Upload = delivered + email | One act: upload confirm flips status and emails immediately | |
| Upload = delivered, mail separate | Report client-visible on upload; email is its own send button afterwards | |

**User's choice:** Staged, then Deliver

**Q2: Who receives the delivery email when you hit Deliver?**

| Option | Description | Selected |
|--------|-------------|----------|
| Picker in dialog (Recommended) | Same recipient picker as existing validation/results mails; server resolves emails + per-recipient locale (D-06 machinery) | ✓ |
| All active members, automatic | Every active member of the space emailed on Deliver | |
| You decide | Claude picks based on existing mail-send code | |

**User's choice:** Picker in dialog
**Notes:** Mail reuses Phase-10 `results.html.j2`, short + link style per established convention (noted in continue-check; user moved on without objection).

---

## Post-delivery changes

**Q1: After delivery, can the superadmin replace the report PDF?**

| Option | Description | Selected |
|--------|-------------|----------|
| Replace + optional re-notify (Recommended) | Replace stays available; dialog asks whether to re-send notification email; status stays delivered | ✓ |
| Replace, always silent | Swaps file but never re-emails | |
| Locked after delivery | Report immutable in UI post-delivery | |

**User's choice:** Replace + optional re-notify

**Q2: Can a delivered report be pulled back entirely (un-deliver)?**

| Option | Description | Selected |
|--------|-------------|----------|
| No — delivered is one-way (Recommended) | Staged file swappable before Deliver; after Deliver only Replace; retraction = manual/DB | ✓ |
| Yes, with confirm | Guarded retract action reverting to in_research | |
| You decide | Claude picks based on status-machine simplicity | |

**User's choice:** No — delivered is one-way

---

## Client experience

**Q1: Where does the client see the delivered report?**

| Option | Description | Selected |
|--------|-------------|----------|
| Block on results page (Recommended) | Report block atop existing client results page; no new route | |
| Dedicated report page | New client route that only exists once delivered | ✓ |
| You decide | Claude picks placement | |

**User's choice:** Dedicated report page
**Notes:** Chosen against the recommendation — the page is also the natural future home for the Phase 19 Q&A chat; lay out with that in mind.

**Q2: What does the client report page show?**

| Option | Description | Selected |
|--------|-------------|----------|
| Inline preview + download (Recommended) | Embedded PDF viewer via signed URL + download button | |
| Download-only | Metadata (title, delivered date, size) + download button; no inline rendering | ✓ |
| You decide | Claude picks based on effort vs. experience | |

**User's choice:** Download-only

**Q3: How does the client reach the report page?**

| Option | Description | Selected |
|--------|-------------|----------|
| Email link + list CTA (Recommended) | Delivery email deep-links to the page + "View report" CTA on client intake list once delivered | ✓ |
| Email link + banner on results page too | Adds a banner on the validated-answers results page | |
| Email link only | Reachable only via the email link | |

**User's choice:** Email link + list CTA

---

## File constraints

**Q1: Which file types can be uploaded as the final report?**

| Option | Description | Selected |
|--------|-------------|----------|
| PDF only (Recommended) | Only .pdf; tighten the stub's .pdf/.docx/.md/.txt accept list | ✓ |
| PDF + docx | Allow Word as alternative format | |
| Keep stub's list | Accept .pdf, .docx, .md, .txt | |

**User's choice:** PDF only

**Q2: One report file per intake, or allow extra attachments alongside it?**

| Option | Description | Selected |
|--------|-------------|----------|
| Single file (Recommended) | Exactly one final report PDF; Replace swaps it | ✓ |
| Report + attachments | Main report plus optional annexes | |

**User's choice:** Single file

---

## Claude's Discretion

- File size limit + server-side PDF validation details
- Reuse/repair `FinalReportBlock.tsx` vs rebuild the admin block
- Backend transition-verb shape; column reuse (`results_link_sent_at`) vs new field
- Client report page route naming/layout (reserving Phase-19 chat space)
- Admin post-delivery visuals (summary card, stepper `delivered` state)
- GCS versioning posture on replace (recommend keeping old objects)

## Deferred Ideas

- Phase 19 Q&A chat lives on the client report page built this phase (layout foresight only, no chat UI now)
- Inline PDF preview — rejected this phase, revisit on client demand
- Un-deliver/retract action — rejected (one-way), revisit only after a real incident
- Report attachments/annexes — rejected (single file), future scope if needed
