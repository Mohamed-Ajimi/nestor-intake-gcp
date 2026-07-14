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

**PARITY GREEN** — set to GREEN only when ALL boxes above are ticked (every inherited 07–11 item
AND both roles of the two-role E2E). Any unchecked box means parity is NOT proven and the cutover
MUST NOT proceed to Supabase-independence sign-off.

- Gate: [ ] PARITY GREEN

## Known gaps (recorded during the 12-05 cutover, 2026-07-14)

1. **Mail deferred (operator decision):** the `nestor-resend-api-key` secret exists with the
   runtime-SA accessor grant but has NO version — the operator chose to skip mail this session.
   `RESEND_API_KEY` is deliberately NOT mapped (a version-less secret ref would break revision
   startup). All mail-dependent items above (10-UAT items, invite-mail locale, invite click-through,
   validation/results sends, and the REAL-invite-flow leg of the user-role E2E) cannot pass until
   the key is added and `--update-secrets=RESEND_API_KEY=nestor-resend-api-key:latest` is applied.
2. **NDA PDF not dropped (operator decision):** `frontend/public/templates/NDA/…` is absent from
   the deployed image — the NDA download 404s. Closing requires the out-of-band PDF drop + a
   frontend image rebuild/redeploy.
3. **Backend suite 218/223:** 5 failures, all in mail tests (`test_mail_render`, `test_mail_locale`,
   `test_mail_endpoints`), diagnosed as TEST defects, not app bugs: absolute audit-row counts
   against the shared Cloud Build DB (cross-test leakage) and a raw-`&` assertion vs Jinja2's
   correct `&amp;` attribute escaping. App send-first/single-audit logic verified correct by
   inspection. Needs a test-harness fix (delta counts / per-test isolation) in a gaps plan.
4. **Latent backend config bug (found live):** comma-separated `CORS_ALLOWED_ORIGINS` crashes
   startup — pydantic-settings JSON-decodes `list[str]` env values BEFORE the comma-splitting
   `field_validator` runs (rev 00021 failed to start; recovered with rev 00022 using the JSON-array
   form). The validator's comma-separated claim in `backend/app/core/config.py` is unreachable;
   fix with `NoDecode`/custom source or correct the docstring.
