---
phase: 12-frontend-deploy-cutover-supabase-retirement
verified: 2026-07-20T14:00:00Z
status: human_needed
score: 4/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Two-role draft-to-decomposed E2E — superadmin run"
    expected: "Superadmin completes draft → submitted → reviewed → validated_by_client → decomposed on live GCP stack with no Supabase call; run-research is not reachable"
    why_human: "Requires real Firebase auth, live GCP backend, AI skill calls, SSE stream confirmation"
  - test: "Two-role draft-to-decomposed E2E — user run via real invite flow"
    expected: "Invited user (invitation mail → /auth/action → set-password → login) completes full intake flow in own space only; cross-space attempt yields scoped-empty/404"
    why_human: "Requires real email delivery, real Identity Platform invite flow, live tenant isolation proof in browser"
  - test: "07-UAT #3 — structure-answers UI trigger + E2E"
    expected: "structure-answers trigger in AISkillsPanel reaches status=succeeded and structured output renders"
    why_human: "Requires live AI call + real UI interaction"
  - test: "07-UAT #4 — extract-insights E2E"
    expected: "extract-insights trigger succeeds and displays insights on the intake"
    why_human: "Requires live AI call + real UI interaction"
  - test: "07-UAT #6 — embeddings + space-scoped semantic search"
    expected: "Embedded artifacts are searchable; results return only within caller's space"
    why_human: "Requires live embedding generation + semantic search execution + cross-space isolation proof"
  - test: "07-UAT #7 / 09-UAT #4/#8 — transcribe-audio E2E (superadmin audio upload + keyless GCS download)"
    expected: "Upload audio source, trigger transcribe-audio CTA (now wired with real source ids), confirm transcript produced; GCS signed-URL download succeeds"
    why_human: "Requires real GCS upload + Whisper call + browser download"
  - test: "07-UAT Gaps — Kopieer intake-link"
    expected: "Copies ${origin}/intake/${intake.id} (login-gated id path, not legacy client_intake_token)"
    why_human: "Browser clipboard interaction; cannot verify via grep"
  - test: "07-UAT Gaps — context-pack progress UX"
    expected: "Running/progress banner visible during context-pack generation (not only for apply-intake-skill)"
    why_human: "Requires live context-pack trigger + visual inspection"
  - test: "07-UAT Gaps — artifacts-read endpoint / display"
    expected: "ContextPackBlock loads and displays latest artifact via GET /intakes/{id}/context-pack"
    why_human: "Requires real artifact in DB + browser visual inspection"
  - test: "07-UAT Gaps — NDA template-asset serving"
    expected: "NDA PDF downloads via static URL from frontend/public/templates/NDA/…pdf"
    why_human: "PDF binary not in deployed image — requires out-of-band PDF drop + image rebuild"
  - test: "08-UAT #3 — cross-space SSE stream denial in a real browser"
    expected: "SSE stream for intake in space A returns 404 when opened by a user from space B (not 403)"
    why_human: "Requires two real user accounts in different spaces, live SSE stream, browser network inspection"
  - test: "09-UAT #7 — delete file (CORS DELETE preflight) click-through"
    expected: "Uploaded file deleted from UI; CORS DELETE preflight succeeds; object removed from GCS"
    why_human: "Browser CORS preflight + GCS mutation — cannot verify via grep"
  - test: "09-UAT #9 — edit-mode deferred-delete Save vs Cancel"
    expected: "(a) Cancel: marked file remains; (b) Save: file is deleted from GCS"
    why_human: "Requires real GCS + browser interaction for both branches"
  - test: "10-UAT #1 — RecipientPicker visual/functional"
    expected: "RecipientPicker lists correct space-scoped recipients; selection drives notification send"
    why_human: "UI functional test requiring live backend + email validation"
  - test: "10-UAT #2 — live invite click-through via /auth/action"
    expected: "Invite mail received; /auth/action link completes set-password + login successfully"
    why_human: "Requires real email delivery, Identity Platform, browser login"
  - test: "11-UAT #1-3 — live NL/FR/EN switching, persistence, pre→post-login carry"
    expected: "Locale switch takes effect immediately, persists across reload, carries from pre-login into post-login session"
    why_human: "Requires browser interaction for persistence and session carry"
  - test: "11-UAT #4 — invite email locale matches space"
    expected: "Invite email arrives in the space's configured locale (FR or EN)"
    why_human: "Requires real email send + native language review"
  - test: "11-UAT #5 — FR/EN tone review"
    expected: "Native/fluent reviewer approves FR and EN catalog for tone and correctness"
    why_human: "Requires human linguistic judgment"
  - test: "11-UAT #6 — full backend suite green in Cloud Build after ji9 backend change"
    expected: "All backend tests pass in Cloud Build (including mail tests after test-harness fixes)"
    why_human: "Requires Cloud Build run; current known state is 218/223 with 5 mail-test failures (test defects, not app bugs)"
---

# Phase 12: Frontend Deploy, Cutover & Supabase Retirement — Verification Report

**Phase Goal:** Execute the live cutover — deploy the frontend to Cloud Run wired to the GCP backend, prove parity for both roles via the consolidated 12-UAT gate, and establish Supabase independence (no Supabase env vars/calls/keys in the new stack; independence-only, the legacy Supabase project is NOT touched/paused/deleted).
**Verified:** 2026-07-20T14:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | TanStack Start SSR frontend deployed as Cloud Run container against new backend, no Supabase anon key in bundle | VERIFIED (operator-attested + code-side proof) | `frontend/Dockerfile` two-stage node:22-slim, no `VITE_SUPABASE_*` ARG; D-11 guard passes in build (`ci_no_supabase_in_bundle.sh --self-test` exits 0 locally); operator-attested: frontend rev 00010-ndr deployed 2026-07-20, Cloud Build 69381baa SUCCESS, smoke `/auth/login` HTTP 200, no Supabase signature in SSR output |
| SC2 | Parity checklist green: draft→decomposed for both superadmin and user, exercising auth, isolation, AI ports, SSE, storage, i18n | UNCERTAIN — authorized deferral | Operator decision 2026-07-20: PARITY ACCEPTED WITH DEFERRALS; 21 of 21 checklist items remain unchecked; deferred to post-Tribunal. Gate reads `[x] PARITY ACCEPTED WITH DEFERRALS` and `[ ] PARITY GREEN`. Full parity not achieved, but deferral is a recorded operator override, not a silent gap. |
| SC3 | Legacy Supabase project NOT touched; zero Supabase env vars/calls/keys in new stack (D-08/D-11) | VERIFIED (code-side) | Dockerfile omits `VITE_SUPABASE_*` ARGs (confirmed by grep — no matches). D-11 guard (`ci_no_supabase_in_bundle.sh`) uses precise pattern `[a-z0-9]{20}\.supabase\.co|"role":"anon"|eyJhbGciOi|sb_publishable_|sb_secret_` — avoids false-positives on retained supabase-js library strings. `cloudbuild.yaml` has no Supabase substitution variable. `supabase.ts` null-guards the client (`url && key ? createClient(...) : null`); with no `VITE_SUPABASE_*` set at build time, client is null. D-08 confirmed: no Supabase-side action taken per 12-05-SUMMARY. |

**Score: 2/3 roadmap success criteria fully VERIFIED; SC2 is authorized-deferral / human_needed**

---

### PLAN Must-Haves Verification

#### Plan 12-01 Must-Haves

| Truth | Status | Evidence |
|-------|--------|----------|
| Guard fails (non-zero) when Supabase URL/anon-key signature present | VERIFIED | Self-test run locally: `bash frontend/scripts/ci_no_supabase_in_bundle.sh --self-test` → exit 0, `SELF-TEST OK: planted offender triggered non-zero exit (1)` |
| Guard passes (exit 0) when no Supabase signature present | VERIFIED | Self-test negative branch confirmed passing |
| Guard has `--self-test` that plants offender + asserts non-zero | VERIFIED | Script lines 81-102: mktemp -d, plant offender, re-invoke, assert rc != 0 |
| Single consolidated 12-UAT.md carries ALL open items from phases 7-11 + two-role E2E | VERIFIED | 21 `- [ ]` items (confirmed `grep -c "^- \[ \]"` = 21); all category tokens present: Kopieer, transcribe, RecipientPicker, NL/FR/EN, cross-space, decomposed, run-research scope ceiling |

#### Plan 12-02 Must-Haves

| Truth | Status | Evidence |
|-------|--------|----------|
| Frontend build targets Nitro node-server preset | VERIFIED | `frontend/vite.config.ts`: `nitro: { preset: "node-server" }`, no `cloudflare:` |
| Two-stage Node Dockerfile bakes `VITE_API_BASE_URL` + `VITE_FIREBASE_*` at build time, runs `node .output/server/index.mjs` on `$PORT` | VERIFIED | `frontend/Dockerfile` stage 1: ARG/ENV for all 4 public VITE_ vars; CMD: `["node", ".output/server/index.mjs"]` |
| Dockerfile deliberately omits `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` | VERIFIED | `grep VITE_SUPABASE frontend/Dockerfile` → no matches |
| Dockerfile runs D-11 bundle guard right after `npm run build` | VERIFIED | Line 57: `RUN bash scripts/ci_no_supabase_in_bundle.sh .output` |
| Sales product card hidden (enabled:false) with code retained | VERIFIED | `admin.index.tsx` PRODUCTS array: `slug: "sales"`, `enabled: false`; comment explains D-09 retention intent |

#### Plan 12-03 Must-Haves

| Truth | Status | Evidence |
|-------|--------|----------|
| GET /intakes/{id}/sources returns intake's audio sources, space-scoped (existence-hidden) | VERIFIED | `backend/app/api/intake_routes.py` line 607-629: `@intake_router.get("/{intake_id}/sources")` `def list_intake_sources` with scoped repo `Depends(get_intake_source_repo)`, returns `IntakeSourcesView` |
| Transcribe CTA no longer permanently disabled — wires each audio source id to `skills.transcribeSource` | VERIFIED | `AISkillsPanel.tsx` imports `getIntakeSources`, calls on mount, renders per-source enabled transcribe button at line 149: `skills.transcribeSource(intakeId, source.id)` |
| Cross-tenant/missing intake returns scoped-empty list (never distinguishable 403) | VERIFIED | Docstring + test `test_sources_read_cross_tenant_is_existence_hidden` at line 1002 of `test_intake_routes.py` |

#### Plan 12-04 Must-Haves

| Truth | Status | Evidence |
|-------|--------|----------|
| `infra/main.tf` has `google_cloud_run_v2_service.frontend` (scale-to-zero, PORT=8080, allUsers invoker) | VERIFIED | grep matches line 667; `google_cloud_run_v2_service_iam_member.frontend_invoker` at line 711 |
| `infra/outputs.tf` exposes `frontend_service_url` | VERIFIED | `output "frontend_service_url"` at line 27 |
| DEPLOY-RUNBOOK.md has Phase 12 section (backend catch-up + two-pass frontend deploy + URL wiring) | VERIFIED | `## Phase 12` section exists; `CORS_ALLOWED_ORIGINS`, `cloudbuild.yaml`, `authorized domains` all present |
| Runbook two-pass sequence captures printed Service URL, never a guessed URL | VERIFIED | Runbook Step 12.4 explicitly keys wiring off `${FRONTEND_URL}` captured from deploy output; "never a guessed URL" language present |

#### Plan 12-05 Must-Haves

| Truth | Status | Evidence |
|-------|--------|----------|
| Backend catch-up deploy live (jinja2/httpx, alembic 0010, RESEND_API_KEY, mail envs, suite green) | VERIFIED (operator-attested) | 12-05-SUMMARY: backend rev 00024-67b, alembic 0010, RESEND_API_KEY seeded (rev 00023); 218/223 suite (5 failures are test-harness defects, not app bugs — recorded in Known Gaps section of 12-UAT.md) |
| Frontend deployed as Cloud Run container, returns SSR HTML at run.app URL | VERIFIED (operator-attested) | Frontend rev 00010-ndr (`frontend:20260720-102153`), Cloud Build 69381baa SUCCESS, smoke `/auth/login` HTTP 200 confirmed |
| Captured frontend URL wired into backend CORS + APP_BASE_URL + bucket CORS + Firebase authorized domains | VERIFIED (operator-attested) | 12-05-SUMMARY: "FRONTEND_URL wired into backend CORS_ALLOWED_ORIGINS + APP_BASE_URL, uploads-bucket CORS, and Firebase authorized domains" |
| Consolidated 12-UAT parity gate fully green for BOTH roles | UNCERTAIN — authorized deferral | 21/21 items remain unchecked; gate reads `[ ] PARITY GREEN`. Operator decision recorded: PARITY ACCEPTED WITH DEFERRALS 2026-07-20. This is a human-gate override with a preserved ledger, not a silent gap. See human_verification section. |
| No Supabase key/URL in deployed bundle (D-11 guard green in build) | VERIFIED (code-side + operator-attested) | D-11 guard passes self-test locally; Dockerfile wires guard in build stage; operator-attested: "no Supabase signature in SSR output" |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `frontend/scripts/ci_no_supabase_in_bundle.sh` | D-11 bundle guard (exit-code gate + negative self-test) | VERIFIED | Substantive: 104 lines with proper PATTERN, exit-code gate, self-test harness. Self-test passes locally. |
| `.planning/phases/12-frontend-deploy-cutover-supabase-retirement/12-UAT.md` | D-05 consolidated parity checklist (>= 18 items + two-role E2E) | VERIFIED | 21 unchecked items, all phase markers present, gate decision block recorded |
| `frontend/vite.config.ts` | Nitro node-server preset | VERIFIED | Contains `preset: "node-server"`, no cloudflare: block |
| `frontend/Dockerfile` | Two-stage Node SSR container with D-11 guard | VERIFIED | ci_no_supabase_in_bundle wired after npm run build; no VITE_SUPABASE_ ARGs |
| `frontend/cloudbuild.yaml` | Cloud Build config with VITE_ build-args, no Supabase vars | VERIFIED | 4 --build-arg VITE_* substitutions; no Supabase substitution |
| `frontend/.dockerignore` | Excludes .output, node_modules | VERIFIED | Both excluded; also excludes .env* |
| `frontend/src/routes/admin.index.tsx` | Sales entry enabled:false | VERIFIED | `enabled: false` confirmed |
| `backend/app/api/intake_routes.py` | GET /{intake_id}/sources endpoint | VERIFIED | `def list_intake_sources` at line 608, correct shape |
| `frontend/src/lib/api/sources.ts` | Sources read seam | VERIFIED | `getIntakeSources` calls `apiFetch` GET `/intakes/${intakeId}/sources` |
| `frontend/src/components/intake/AISkillsPanel.tsx` | Per-source transcribe wiring (not hard-disabled) | VERIFIED | imports getIntakeSources, filters kind==="audio", calls skills.transcribeSource(intakeId, source.id) |
| `infra/main.tf` | Frontend Cloud Run service block | VERIFIED | `google_cloud_run_v2_service.frontend` + allUsers invoker + IaC-DRIFT note |
| `infra/variables.tf` | frontend_service_name + frontend_image_tag | VERIFIED | Both present |
| `infra/outputs.tf` | frontend_service_url output | VERIFIED | Present at line 27 |
| `infra/DEPLOY-RUNBOOK.md` | Phase 12 deploy runbook section | VERIFIED | Steps 12.1-12.5 including backend-first ordering, two-pass URL wiring, D-08 no-Supabase guard |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `frontend/Dockerfile` | `frontend/scripts/ci_no_supabase_in_bundle.sh` | `RUN bash scripts/ci_no_supabase_in_bundle.sh .output` | WIRED | Confirmed line 57 of Dockerfile |
| `frontend/cloudbuild.yaml` | `frontend/Dockerfile` | `docker build --build-arg VITE_*` | WIRED | 4 `--build-arg=VITE_*` substitutions, pushes via `images:` |
| `frontend/src/lib/api/sources.ts` | `/intakes/{id}/sources` | `apiFetch GET` | WIRED | Line 31: `apiFetch<IntakeSourcesRead>(\`/intakes/${intakeId}/sources\`, { method: "GET" })` |
| `frontend/src/components/intake/AISkillsPanel.tsx` | `skills.transcribeSource` | per-source transcribe trigger | WIRED | Line 149: `skills.transcribeSource(intakeId, source.id)` |
| `infra/main.tf frontend service` | `infra/variables.tf frontend vars` | `var.frontend_service_name / var.frontend_image_tag` | WIRED | Both vars declared; frontend block references `var.frontend_service_name` |
| `infra/DEPLOY-RUNBOOK.md Phase 12` | `CORS_ALLOWED_ORIGINS + APP_BASE_URL + bucket CORS + Firebase authorized domains` | second-pass URL wiring steps | WIRED | Steps 12.4(a/b/c) all present; wired to captured FRONTEND_URL |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `AISkillsPanel.tsx` | `audioSources` | `getIntakeSources(intakeId)` → `apiFetch GET /intakes/{id}/sources` → `IntakeSourceRepository.list_for_intake(intake_id)` | Yes — DB query via space-scoped repo | FLOWING |
| `backend/app/api/intake_routes.py list_intake_sources` | `IntakeSourcesView` | `repo.list_for_intake(intake_id)` (SQLAlchemy query against `intake_sources` table) | Yes — real DB query | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| D-11 guard self-test exits 0 | `bash frontend/scripts/ci_no_supabase_in_bundle.sh --self-test` | exit 0, "SELF-TEST OK: planted offender triggered non-zero exit (1)." | PASS |
| vite.config.ts targets node-server | `grep "node-server" frontend/vite.config.ts` | Matches: `nitro: { preset: "node-server" }` | PASS |
| Dockerfile has no VITE_SUPABASE_ ARG | `grep VITE_SUPABASE frontend/Dockerfile` | No matches | PASS |
| D-11 guard wired in Dockerfile | `grep ci_no_supabase_in_bundle frontend/Dockerfile` | Matches line 57 | PASS |
| Sales card hidden | `grep -A5 'slug: "sales"' admin.index.tsx \| grep "enabled: false"` | Matches | PASS |
| sources endpoint exists | `grep "def list_intake_sources" backend/app/api/intake_routes.py` | Matches line 608 | PASS |
| sources frontend seam calls apiFetch | Pattern `getIntakeSources.*apiFetch` | `sources.ts` line 31 confirmed | PASS |
| transcribe CTA wired to real source id | `grep "transcribeSource.*source.id" AISkillsPanel.tsx` | Line 149 confirmed | PASS |
| 12-UAT.md has >= 18 unchecked items | `grep -c "^- \[ \]" 12-UAT.md` | 21 | PASS |
| infra/main.tf has frontend service | `grep 'google_cloud_run_v2_service" "frontend"' infra/main.tf` | Matches | PASS |
| DEPLOY-RUNBOOK has Phase 12 | `grep "Phase 12" infra/DEPLOY-RUNBOOK.md` | Matches | PASS |
| No debt markers (TBD/FIXME/XXX) in phase-12 modified files | grep across all 9 modified files | No matches | PASS |

---

### Probe Execution

No conventional probe scripts exist for Phase 12 (it is a deploy + UAT phase, not a backend logic phase). Step 7b spot-checks substituted above.

---

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| INFRA-05 | 12-01, 12-02, 12-04, 12-05 | TanStack Start SSR frontend deployed on Cloud Run (container), pointed at the new backend | SATISFIED | Dockerfile + cloudbuild.yaml + vite node-server preset authored; live deploy operator-attested (rev 00010-ndr, Cloud Build 69381baa SUCCESS) |
| QA-05 | 12-01, 12-03, 12-05 | End-to-end flow validated on GCP for both roles; legacy Supabase project retired (independence-only per D-08) | PARTIALLY SATISFIED | Supabase independence proven code-side (D-11 guard, no VITE_SUPABASE_ in build); parity UAT closed by operator deferral (not full PARITY GREEN); 21 UAT items deferred to post-Tribunal. Independence-only framing confirmed (no Supabase-side action taken). |

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `backend/tests/test_intake_routes.py` (mail tests) | Known gap | Absolute audit-row counts against shared Cloud Build DB (cross-test leakage) causing 5 mail test failures | WARNING | Test-harness defect (not app bug); 218/223 suite passes; recorded in 12-UAT.md Known Gaps. Not a blocker for INFRA-05 but deferred QA debt for post-Tribunal (11-UAT #6). |
| `backend/app/core/config.py` | Known gap | CORS_ALLOWED_ORIGINS comma-splitting `field_validator` is unreachable (pydantic-settings JSON-decodes before validator) | WARNING | Config bug discovered live (rev 00021 failed to start; recovered via JSON-array form rev 00022). Workaround in place; underlying validator docstring is incorrect. Recorded in 12-UAT.md Known Gaps. |

No TBD/FIXME/XXX debt markers found in any phase-12 modified file.

---

### Human Verification Required

All 21 items in the 12-UAT.md consolidated gate remain unchecked and are deferred by operator decision to after the Tribunal milestone. These are classified as human_needed tracking debt, not unreported gaps — the deferral decision is recorded explicitly in 12-UAT.md gate block (2026-07-20).

#### Items requiring live GCP verification against rev 00010-ndr / nestor-api rev 00024-67b:

**1. Two-role draft → decomposed E2E (Superadmin run)**
- **Test:** Superadmin completes a full `draft → submitted → reviewed → validated_by_client → decomposed` intake in a seeded test space — form submit, apply-intake-skill, AI review accept/edit/reject, context pack generation, end at `decomposed`
- **Expected:** Every stage transitions via the GCP backend; run-research/Tribunal is never invoked
- **Why human:** Requires real Firebase auth + live AI skill calls + SSE stream + DB state transitions on live GCP

**2. Two-role draft → decomposed E2E (User run via real invite flow)**
- **Test:** Seeded test user invited via real invite flow (invitation mail → `/auth/action` → set-password → login) completes full intake; sees ONLY own space; cross-space attempt yields scoped-empty/404
- **Expected:** Tenant isolation proven in browser; scope ceiling holds (decomposed, no run-research)
- **Why human:** Requires real email delivery, Identity Platform invite flow, second browser session, network inspection

**3-19. Inherited 07-11 HUMAN-UAT items (deferred)**
See 12-UAT.md sections: Phase 7 (#3/#4/#6/#7/Gaps), Phase 8 (#3), Phase 9 (#4/#7/#8/#9), Phase 10 (#1/#2), Phase 11 (#1-3/#4/#5/#6). All require live GCP interaction, visual inspection, or real email/AI calls.

**Post-UAT chore (not a UAT gate item, but tracked):**
- Rotate the Resend API key — it transited assistant chat during the session. Add new value as version 2 of `nestor-resend-api-key` (no service change needed; env references `:latest`).

---

### Gaps Summary

No hard BLOCKED gaps. The phase deliverables are substantively complete code-side:
- The D-11 Supabase bundle guard exists, is wired in the Dockerfile, and passes its self-test.
- The frontend container definition (Dockerfile + cloudbuild.yaml + vite node-server preset) is correct with no Supabase build-args.
- The sources-read endpoint (`GET /intakes/{id}/sources`) and transcribe CTA wiring are implemented, scoped correctly, and tested (TDD).
- The IaC frontend service is described by construction in `infra/main.tf` with the correct shape.
- The DEPLOY-RUNBOOK Phase 12 section is complete and correctly ordered.
- The live cutover is operator-attested: frontend rev 00010-ndr live, no Supabase signature confirmed.

The only outstanding item is the parity UAT gate, which is not a code gap — it is an authorized human-gate override with a preserved deferred-items ledger. Status is `human_needed` rather than `gaps_found` because the operator decision was explicit, documented, and non-silent.

#### Known tracked debt (not blocking, recorded in 12-UAT.md):
1. **NDA PDF not dropped**: `frontend/public/templates/NDA/Agenic-Nestor-Overeenkomst.pdf` absent from deployed image — NDA field download 404s. Requires out-of-band PDF drop + image rebuild.
2. **Backend suite 218/223**: 5 mail test failures are test-harness defects (absolute row counts + raw `&` vs `&amp;` assertion), not app bugs. Needs test-harness fix (delta counts / per-test isolation). Folded into 11-UAT #6 deferred item.
3. **CORS env validator bug**: comma-separated `CORS_ALLOWED_ORIGINS` crashes startup (pydantic-settings decodes before validator). Workaround: use JSON-array form. Docstring correction + `NoDecode` source fix needed.
4. **Resend API key rotation**: key transited assistant chat; rotate and add version 2 in Secret Manager.

---

*Verified: 2026-07-20T14:00:00Z*
*Verifier: Claude (gsd-verifier)*
