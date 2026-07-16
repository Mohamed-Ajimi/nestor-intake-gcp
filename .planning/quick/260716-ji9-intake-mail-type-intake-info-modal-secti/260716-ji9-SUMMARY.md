---
phase: quick-260716-ji9
plan: 01
subsystem: intake-detail
tags: [mail, i18n, modal, ux]
requires: []
provides:
  - "POST /intakes/{id}/mail/intake (draft-only, 409-gated intake-invite send)"
  - "render_intake() + nl/fr/en intake.html.j2 mail templates"
  - "Draft-phase primary CTA: send intake link by mail (RecipientPicker type 'intake')"
  - "Intake-info header-button modal (dl moved out of page flow)"
affects: [intake-detail-route, mail-layer]
tech-stack:
  added: []
  patterns: ["transition-guard 409 idiom reused for mail gating"]
key-files:
  created:
    - backend/app/mail/templates/nl/intake.html.j2
    - backend/app/mail/templates/fr/intake.html.j2
    - backend/app/mail/templates/en/intake.html.j2
  modified:
    - backend/app/mail/render.py
    - backend/app/api/intake_routes.py
    - frontend/src/lib/api/intakes.ts
    - frontend/src/components/intake/NextStepBanner.tsx
    - frontend/src/components/intake/RecipientPicker.tsx
    - frontend/src/routes/admin.pulse.intakes.$id.tsx
    - frontend/src/locales/{nl,fr,en}/intake.json
    - frontend/src/locales/{nl,fr,en}/admin.json
decisions:
  - "confirmIntake fr = 'Envoyer le lien d'intake' (register mirror of confirmValidation) instead of the plan's shorter 'Envoyer le lien'"
  - "sendIntakeMail en = 'Send intake link via email' (register mirror of sendValidationMail) instead of 'by email'"
  - "admin.json info.title left untouched — already authored-case in all three locales"
metrics:
  duration: "~35 min"
  completed: "2026-07-16"
---

# Quick Task 260716-ji9: Intake Mail Type + Intake-info Modal + Section Casing Summary

**One-liner:** New draft-only "intake" mail type (nl/fr/en templates + render_intake + 409-gated POST /mail/intake) with a primary banner CTA, plus the Intake-info dl re-housed in a header-button house-style modal and schema-section h2s rendering authored-case.

## What Was Done

### Task 1 — Backend intake mail type (commit c0469a1)
- `intake.html.j2` created in `backend/app/mail/templates/{nl,fr,en}/`, each extending `_base.html.j2` and mirroring the validation template shape (greeting, intro, `.btn` CTA on `{{ cta_url }}`, sign-off, `.footer` with `{{ project_title }}`). No `is_reminder` branch, no `| safe` on any interpolation (autoescape stays the XSS guard, T-ji9-02).
- `render_intake()` added to `backend/app/mail/render.py` directly after `render_validation` — exact signature mirror minus `is_reminder`; docstring notes the token-free `{app_base_url}/intake/{intake_id}` CTA (NOTIF-01) and nl fallback (D-07).
- `backend/app/api/intake_routes.py`:
  - `"intake"` subject rows added to all three `_SUBJECTS` locales (nl "Jullie intake staat klaar — {client}", fr "Votre intake est prêt — {client}", en "Your intake is ready — {client}"). `_subject_for` untouched.
  - `_run_intake_send` gains keyword-only `is_intake: bool = False`. When true: draft-only 409 gate right after the 404 gate (`Cannot send the intake mail in status {intake.status!r}` — the transition-guard idiom, T-ji9-03), `mail_type="intake"`, `timestamp_field=None` (no column, no migration), and an `elif is_intake:` render branch calling `mail_render.render_intake` in the per-locale loop.
  - New `POST /{intake_id}/mail/intake` (`send_intake_mail`) beside the other three send verbs, delegating with `is_intake=True`.
  - Existing callers pass no new argument — validation/reminder/results semantics byte-identical (all new code is behind `is_intake`).

### Task 2 — Frontend CTA + modal + casing (commit bd3ab7a)
- `IntakeMailType` union extended to `"intake" | "validation" | "reminder" | "results"`; `sendIntakeMail` unchanged (generic).
- `NextStepBanner`: `"sendIntake"` BusyKey + `onSendIntakeMail` prop; `awaiting_client_submission` now renders PrimaryBtn (send intake mail) first, copy-link demoted to SecondaryBtn.
- `RecipientPicker`: `intake` entry added to `TYPE_COPY` (tsc-enforced exhaustiveness).
- Route `admin.pulse.intakes.$id.tsx`: `intake: "sendIntake"` in `MAIL_BUSY_KEY`, `onSendIntakeMail = () => setMailPickerType("intake")`, prop passed to `<NextStepBanner>`; `handleSendMail`/picker mount untouched.
- Intake-info: first `<section>` in `<main>` deleted; the entire `<dl>` moved verbatim into a new `infoModalOpen` overlay next to the archive dialog (same house convention: `fixed inset-0 z-50 ... bg-ink/40` backdrop-click close; panel `max-h-[85vh] max-w-2xl overflow-y-auto border border-ink bg-paper p-6 shadow-lg` with `stopPropagation`), authored-case heading (no `lowercase`), right-aligned close button in archive-cancel styling. Local helpers (`Meta`, `LinkRow`, `ResultsLinkRow`, `StatusPill`, `DeliveredAtEditor`) stayed at file bottom.
- Header: mono-outline "Intake-info" button added before the status select.
- Casing: `lowercase` removed ONLY from the schema-section h2 (`{section.title}`); page h1, archive dialog h2, RecipientPicker DialogTitle unchanged.

### Task 3 — i18n catalogs (commit c7fd19c)
- `intake.json` (nl/fr/en): `nextStep.sendIntakeMail`, `recipients.titleIntake`, `recipients.confirmIntake` — placed adjacent to siblings, mirroring each locale's register (titles lowercase like `titleValidation`, confirms capitalized).
- `admin.json` (nl/fr/en): `intakeDetail.info.openButton` + `intakeDetail.info.close`. `info.title` was already authored-case in all three locales ("Intake-info" / "Infos intake" / "Intake info") — no change needed.

## Verification

- Task 1 grep gates: 3 templates exist; `def render_intake` = 1; `mail/intake` route present; 409 message present; no `| safe` filter in any interpolation (the only grep hits are the comment-header convention shared with the sibling templates).
- `npx tsc --noEmit` — clean (after Task 2 and again at final gate).
- `npm run build:dev` — built in 12.35s, success.
- No changes under `frontend/src/components/ui/`; no DB migration/column added.
- `routeTree.gen.ts` regenerated by the build with no content change — discarded via `git checkout -- frontend/src/routeTree.gen.ts` per plan constraint.

## Deviations from Plan

**1. [Minor — copy register] FR confirmIntake + EN sendIntakeMail wording**
- **Found during:** Task 3
- **Issue:** The plan's literal values ("Envoyer le lien" fr confirm, "Send intake link by email" en CTA) conflicted with its own instruction to mirror the register of the existing sibling entries ("Envoyer le lien de validation", "Send validation link via email").
- **Fix:** Followed the register-mirror instruction: fr confirm "Envoyer le lien d'intake", en CTA "Send intake link via email". Same for the lowercase title register (nl "intake-link versturen", fr "envoyer le lien d'intake", en "send intake link").
- **Files modified:** frontend/src/locales/{nl,fr,en}/intake.json
- **Commit:** c7fd19c

No other deviations — backend and frontend structure executed exactly as planned.

## Known Stubs

None — the CTA is fully wired end-to-end (banner → picker → sendIntakeMail → POST /intakes/{id}/mail/intake → render_intake → Resend).

## Threat Flags

None beyond the plan's own register: the new endpoint reuses `_run_intake_send` unchanged (404 existence-hidden D-07, membership-id-only recipients D-06), templates have no `| safe` (T-ji9-02), and the draft-only 409 gate is in place (T-ji9-03). No new dependencies.

## Post-Task Follow-ups (NOT done here)

- **Backend deploy:** the new endpoint/templates are author-by-construction only — Cloud Run image rebuild + deploy required (runbook: memory `phase-07-deployed-suite-green`).
- **Cloud Build suite run:** full backend test suite should be run in Cloud Build post-deploy; consider adding tests for the draft-only 409 gate and the intake render path.
- **Visual UAT:** draft-phase banner order, RecipientPicker copy, Intake-info modal, section-title casing in all three locales.

## Commits

| Task | Commit | Message |
| ---- | ------- | ------- |
| 1 | c0469a1 | feat(260716-ji9): add draft-only intake-invite mail type to backend |
| 2 | bd3ab7a | feat(260716-ji9): intake mail CTA, Intake-info modal, section-heading casing |
| 3 | c7fd19c | feat(260716-ji9): nl/fr/en catalog keys for intake mail CTA and info modal |

## Self-Check: PASSED

- All 3 created template files exist on disk.
- All 3 commits present on `worktree-agent-a3203fafe62aeced0`.
- Working tree clean except this SUMMARY (uncommitted by design — orchestrator handles docs).
