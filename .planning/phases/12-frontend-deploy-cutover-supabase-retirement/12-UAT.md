# Phase 12 — Consolidated Parity UAT (D-05)

**The single cutover parity gate.** This checklist aggregates EVERY open HUMAN-UAT item
carried forward from phases 7–11 (the Consolidated Parity Inventory, 17 rows) PLUS the new
two-role `draft → decomposed` E2E run (roadmap SC2, D-06). It does NOT re-author acceptance
criteria — it inherits each source-phase item verbatim so nothing slips (Pitfall 5).

> **Gate rule:** PARITY is GREEN only when EVERY box below is ticked — every inherited item
> AND both roles of the two-role E2E. A single unchecked box = not green = do NOT retire the
> Supabase path. Blocked ≠ done: a "blocked" prior status still requires a live pass here.

> **Scope ceiling:** The flow ends at status `decomposed`. `run-research` / the Tribunal
> deep-research engine is OUT OF SCOPE and MUST NOT be reachable from the new frontend/backend
> credentials. Any UAT run that can reach `run-research` is a FAILURE, not a pass.

> **Independence, not teardown (D-08):** Supabase is untouched in this phase. Parity is proven
> code-side — no `VITE_SUPABASE_*` env vars, no Supabase signature in the shipped bundle
> (D-11 guard: `frontend/scripts/ci_no_supabase_in_bundle.sh`) — NOT by pausing/deleting the
> legacy project.

## Live environment (cutover executed 2026-07-14 — run this UAT against it)

- **Frontend (test here):** https://nestor-frontend-1055853212188.europe-west1.run.app
  (`nestor-frontend` rev **00006-b9p**, image `frontend:20260716-132659`, D-11 guard green in build;
  supersedes rev 00001..00005 — rollback chain intact. Rev 00004 carried quick task
  260716-e59: first-round UAT defect fixes — user-page LanguageSwitcher, i18n'd sidebar nav,
  `decomposed` status filter, active-space-switch list refetch. Rev 00005 added `1d7732a`:
  active-space filter one-step-behind fix (module accessor synced synchronously; NOT an
  isolation issue — backend space_id filtering verified). Rev 00006 carries quick task
  260716-i0j: round-3 canvas redesign of the intake detail page — merged workflow panel
  (stepper+status+banner+search in one card), sticky sidebar, header pill dropped, boxed
  sections, PLUS new behaviors: house archive dialog (replaces native confirm), deferred-delete
  Herstel undo, inline context-pack preview, inline recipient emails, persistent scope-note.
  Rev **00007-8f2** (image `frontend:20260716-142224`, quick 260716-ji9) adds: draft-phase
  primary CTA "Verstuur intake-link via mail" (copy demoted to secondary), Intake-info moved
  from first page section to a header-button modal, section headings render authored-case.
  Rev **00008-x4h** (`frontend:20260716-151546`, fix `d2f335b`) fixed a phase-machine
  bug found live: a succeeded enrichment run (structure-answers etc.) faked "analysis ready"
  and hid the Run-intake-skill CTA — derivePhase now only consumes apply-intake-skill runs.
  Rev **00009-4r4** (`frontend:20260716-160718`, commits `4eb1c6e`+`acf1ba4`): safety poll
  re-arms on new dispatch (stuck 7-min timer — after a terminal run the SSE stream closes
  itself and the poll had stopped, leaving new runs invisible), unusable review output now
  toasts instead of silently dead-ending, and NEW "Heranalyseer" secondary button in the
  awaiting_review banner re-dispatches apply-intake-skill on the same intake (manual redo
  without a new intake). Rev **00010-ndr** (`frontend:20260720-102153`, commit `c83fdaf`) is the
  current live build — first deploy carrying `a710e8e` client validation-diff fix; supersedes
  00009-4r4. Judge intake-detail UAT items against THIS chrome.)
- **Backend:** https://nestor-api-1055853212188.europe-west1.run.app (`nestor-api` rev **00024-67b**,
  image `backend:20260716-142214`, alembic 0010, CORS + `APP_BASE_URL` wired, `RESEND_API_KEY` live,
  `/readyz` 200. Rev 00024 adds quick 260716-ji9: draft-only intake-invite mail type
  `POST /intakes/{id}/mail/intake` + intake.html.j2 nl/fr/en — NEW UAT item: send the intake-invite
  mail from a draft intake and click through the received mail to the form)
- **Firebase authorized domain:** added by operator (login works). Bucket CORS: wired.
- **Wiring pre-verified:** SSR 200 at `/auth/login`; CORS preflight from the frontend origin OK.
- **Expected failures (recorded in Known gaps below):** NDA download 404s (PDF not in image).
  Mail is LIVE (key seeded same session) — mail items ARE testable.
- **Resume:** plans 12-01..12-04 complete; 12-05 Task 1 (deploy) done. This checklist is 12-05
  Task 2 — the only open work in the phase. After ticking boxes, resume with
  `/gsd-execute-phase 12` (or tell the orchestrating session "parity green" / list failures)
  to write the 12-05 SUMMARY, run phase verification, and close the phase + milestone.
- **✓ DEPLOYED (resolves 2026-07-16 PENDING DEPLOY):** commit `a710e8e` (client validation diff —
  applied question refinements patched into the `research_questions` answer by `original_index` +
  diff cards show applied text) is now LIVE. Frontend rev **00010-ndr** deployed to Cloud Run
  2026-07-20 (~10:25 CEST), serving 100% traffic; image `frontend:20260720-102153`
  (Cloud Build 69381baa, 1m49s, SUCCESS); built from commit `c83fdaf` — the first deployed build
  containing `a710e8e`. Smoke: `/auth/login` HTTP 200, no Supabase signature in the SSR output.
  The validation UAT items are now testable (no longer blocked on deploy). Retest:
  Heranalyseer → redo review (incl. research questions) → send validation → client link shows
  ALL changed cards (intakes validated pre-fix won't).
- **Session log 2026-07-16:** 8 defects found in UAT rounds 1-3, all fixed same-day (revs
  00004→00009 frontend, 00024 backend — details in the rev block above). Suite run in Cloud
  Build still pending after the ji9 backend change (fold into 11-UAT #6). Open decisions:
  Templates page visibility, Intake-info link-row trimming, "Verzonden mails" history block.
- **Post-UAT chore:** rotate the Resend API key (it transited assistant chat) and add the new
  value as version 2 of `nestor-resend-api-key`.

### Pre-UAT UI consistency pass (2026-07-15 — done BEFORE running this checklist)

The operator ran a Claude Design canvas round-trip over all 17 app pages to fix UI
inconsistencies before parity UAT, so screenshots/expectations in this checklist should be
judged against the NEW chrome, not the cutover-day UI:

- **Quick task 260715-fts** (commits `eca918d`/`8a0c373`/`8907172`, 15 files): serif-lowercase
  h1s + mono-uppercase chrome on the intake detail sticky header; duplicate "Beheer" sidebar nav
  removed (ProductShell `items !== ADMIN_NAV` guard); boxed tables + `border-ink text-xs` theads
  on clients/users/spaces; house input/select style (`border-ink bg-paper2` sans) on sales
  new-project, templates select, pulse new-intake; Sales status badges → Pulse
  `badge-ink/outline/dashed` pill system; italic subtitles dropped; asterisks `text-red-600`.
- **Quick task 260715-j7f** (commits `b7fa30b`/`5b5259b`): client intake form redesign — numbered
  stepper sidebar with "Voortgang" header + progress bar (three-state rows driven by the
  existing `done` flag), header hairline, 300px sidebar grid, `resize-y` longtext textareas,
  submit label + " →" (label stays schema-sourced); new i18n key `form.progress` (nl/fr/en).
- **Deploys:** rev 00002-9q2 (`frontend:20260715-115515`, fts only) → rev 00003-dw8
  (`frontend:20260715-135954`, fts+j7f). Smoke after each: `/auth/login` 200, no Supabase
  signature in SSR output.
- **Canvas project (for future UI rounds):** claude.ai/design → "Nestor Pulse — Pages"
  (projectId `7d71cbcf-0b88-4864-bea0-0d79d56bba1a`), 17 page snapshots. Workflow: edit on
  canvas → main session pulls via DesignSync (`get_file`, main-session-only tool) → diff vs
  `pages/` originals → fuse via `/gsd-quick`. Fuse worklists preserved in
  `.planning/quick/260715-fts-*/DIFF-NOTES.md` and `.planning/quick/260715-j7f-*/DIFF-NOTES-2.md`.

---

## Phase 7 (inherited) — AI function ports

- [ ] **07-UAT #3 — structure-answers UI trigger + E2E** (prior status: blocked — no UI trigger)
      How to verify: open an intake with submitted answers, click the structure-answers trigger
      in `AISkillsPanel`, confirm the run reaches `status="succeeded"` and structured output renders.
      Needs the gap-closure UI trigger to exist first.
- [ ] **07-UAT #4 — extract-insights E2E** (prior status: blocked — no UI trigger)
      How to verify: trigger extract-insights from `AISkillsPanel`, confirm the run succeeds and
      extracted insights display on the intake.
- [ ] **07-UAT #6 — embeddings + space-scoped semantic search** (prior status: blocked — no embedded artifacts)
      How to verify: generate embeddings for an intake's artifacts, run a semantic search, confirm
      hits return ONLY within the current space (also proves AI-04: no cross-tenant leak).
- [ ] **07-UAT #7 — transcribe-audio E2E** (prior status: blocked — audio deferred)
      How to verify: upload an audio source, trigger transcribe-audio, confirm the transcript is
      produced and attached. The deferred "audio session" folds in here.
- [ ] **07-UAT Gaps — Kopieer intake-link** (prior status: failed/partial)
      How to verify: click "Kopieer intake-link" on an intake; confirm it copies
      `${origin}/intake/${intake.id}` (the login-gated id path, NOT the legacy `client_intake_token`).
- [ ] **07-UAT Gaps — context-pack progress UX** (prior status: failed/partial)
      How to verify: trigger a context-pack generation; confirm a running/progress banner renders
      for the context-pack run (not only for apply-intake-skill) until it completes.
- [ ] **07-UAT Gaps — artifacts-read endpoint / display** (prior status: failed/partial)
      How to verify: after generating a context pack, confirm `ContextPackBlock` loads and displays
      the latest artifact via `GET /intakes/{id}/context-pack` (existence-hidden scoped read).
- [ ] **07-UAT Gaps — NDA template-asset serving** (prior status: failed/partial)
      How to verify: open a field with a `templates/`-prefixed download; confirm the NDA PDF
      (`frontend/public/templates/NDA/…pdf`) downloads via the static URL. Requires the operator to
      drop the PDF binary (it lived in the legacy Supabase bucket) — see runbook.

## Phase 8 (inherited) — SSE skill-run progress

- [ ] **08-UAT #3 — cross-space SSE stream denial in a real browser (404)** (prior status: blocked — no 2nd space/user)
      How to verify: as the seeded user (space B), attempt to open the SSE stream for an intake in
      space A; confirm a 404 (existence-hidden), never a distinguishable 403/BOLA. The D-06 seeded
      second space enables this.

## Phase 9 (inherited) — GCS storage

- [ ] **09-UAT #4 — transcribe-audio keyless GCS download** (prior status: blocked — audio deferred)
      How to verify: confirm the transcribe path reads the audio from GCS via signed/keyless access
      (no Supabase Storage). Pairs with 07-UAT #7.
- [ ] **09-UAT #7 — delete file (CORS DELETE preflight) click-through** (prior status: blocked)
      How to verify: delete an uploaded file from the UI; confirm the CORS DELETE preflight succeeds
      and the object is removed from GCS.
- [ ] **09-UAT #8 — superadmin audio upload** (prior status: blocked — audio deferred)
      How to verify: as superadmin, upload an audio source to an intake; confirm it registers in
      `intake_sources` and is retrievable.
- [ ] **09-UAT #9 — edit-mode deferred-delete Save vs Cancel** (prior status: blocked)
      How to verify: in edit mode, mark a file for deletion, then (a) Cancel → file remains, and
      (b) Save → file is deleted. Confirm the deferred-delete semantics on both branches.

## Phase 10 (inherited) — Notifications

- [ ] **10-UAT #1 — RecipientPicker visual/functional** (prior status: pending — needs backend catch-up deploy)
      How to verify: open the RecipientPicker; confirm it lists the correct space-scoped recipients
      and selection drives the notification send.
- [ ] **10-UAT #2 — live invite click-through via /auth/action** (prior status: pending)
      How to verify: send an invite; open the invitation mail; follow `/auth/action` through
      set-password and login. THIS IS the D-06 invite-flow test (see Two-role E2E below).

## Phase 11 (inherited) — Internationalization (NL/FR/EN)

- [ ] **11-UAT #1–3 — live NL/FR/EN switching, persistence, pre→post-login carry** (prior status: pending)
      How to verify: switch the UI locale across NL/FR/EN; confirm (1) live switching, (2) the
      choice persists across reloads, and (3) a pre-login locale choice carries into the
      post-login session.
- [ ] **11-UAT #4 — invite email locale matches space** (prior status: pending — needs deployed backend + RESEND)
      How to verify: send an invite for a space configured in FR (or EN); confirm the invitation
      email arrives in the space's locale.
- [ ] **11-UAT #5 — FR/EN tone review** (prior status: pending)
      How to verify: a native/fluent reviewer checks the FR and EN catalogs for tone and correctness
      on the key user-facing surfaces.
- [ ] **11-UAT #6 — full backend suite green in Cloud Build** (prior status: pending)
      How to verify: run the full backend test suite in Cloud Build; confirm it is green. Run as
      part of the D-04 backend catch-up (step one of the phase).

## Two-role draft → decomposed E2E (roadmap SC2, D-06)

The headline parity run. A dedicated **seeded test client space** whose test account is invited
through the **REAL invite flow** (invitation mail → `/auth/action` set-password → login — this is
also 10-UAT #2). Each role runs `draft → submitted → reviewed → validated_by_client → decomposed`,
exercising auth, per-space isolation, the ported AI functions, SSE progress, GCS storage, and i18n.
Both runs MUST stop at `decomposed` — `run-research` / Tribunal must NOT be reachable.

- [ ] **Superadmin run** (cross-tenant): superadmin completes a full `draft → decomposed` intake in
      the seeded test space — form submit, apply-intake-skill, AI review accept/edit/reject, context
      pack generation, and end at `decomposed`. Confirm every stage transitions via the GCP backend
      (no Supabase call) and `run-research` is never invoked.
- [ ] **User run** (own space only, via real invite flow): the seeded test user — invited through
      the real invite flow (invitation mail → set-password → login) — completes a full
      `draft → decomposed` intake, seeing ONLY their own space's data (isolation proven). Confirm the
      scope ceiling holds: the flow ends at `decomposed` and `run-research`/Tribunal is not reachable.

---

## Gate status

**2026-07-20 — PARITY ACCEPTED WITH DEFERRALS (operator decision).** The operator ran a partial
UAT on 2026-07-20 (against live frontend rev **00010-ndr** carrying the `a710e8e` validation-diff
fix), is satisfied with the current state, and ACCEPTED phase-12 parity **WITH DEFERRALS**. This is
explicitly NOT full PARITY GREEN. All remaining unchecked checklist items above are DEFERRED until
after the **Tribunal milestone** — they are to be revisited in/after that milestone. They remain
listed and unchecked so nothing is lost, and they MUST NOT gate phase-12 closure.

- Gate: [x] PARITY ACCEPTED WITH DEFERRALS (operator decision, 2026-07-20)

**PARITY GREEN** — set to GREEN only when ALL boxes above are ticked (every inherited 07–11 item
AND both roles of the two-role E2E). Any unchecked box means parity is NOT proven and the cutover
MUST NOT proceed to Supabase-independence sign-off.

- Gate: [ ] PARITY GREEN

## Known gaps (recorded during the 12-05 cutover, 2026-07-14)

1. **RESOLVED (same session):** mail was initially deferred, but the operator provided the Resend
   key later in the session — version 1 added to `nestor-resend-api-key`, `RESEND_API_KEY` mapped
   (rev 00023, /readyz 200). All mail-dependent items above are now TESTABLE. Operator note: the
   key transited the assistant chat — rotate it in Resend after UAT and add the new value as
   version 2 (no service change needed; the env references `:latest`).
2. **NDA PDF not dropped (operator decision):** `frontend/public/templates/NDA/…` is absent from
   the deployed image — the NDA download 404s. Closing requires the out-of-band PDF drop + a
   frontend image rebuild/redeploy.
3. **RESOLVED 2026-07-22 (stabilization pass, F-03, commit `ce6da62`):** the remaining 4 mail-test
   failures (2× `test_mail_endpoints`, 2× `test_mail_locale`) were absolute `mail.sent` audit-row
   counts leaking across the shared Cloud Build DB — converted to delta counts (before/after the
   action under test), preserving the WR-01/WR-04/D-16 zero-new-rows and exactly-one-new-row
   intents. Test-only change; app code untouched.
4. **RESOLVED 2026-07-22 (stabilization pass, F-02, commit `e3a84ba`):** comma-separated
   `CORS_ALLOWED_ORIGINS` startup crash fixed — `cors_allowed_origins` is now
   `Annotated[list[str], NoDecode]` so the raw env string reaches the validator, which accepts
   BOTH the comma-separated form and the live JSON-array form (backward compatible with the
   deployed rev's env). Unit-tested in `backend/tests/test_config_cors.py`. Takes effect live at
   the next nestor-api image rebuild.
