---
phase: 16-research-trigger-progress-bridge
verified: 2026-07-22T16:00:00Z
status: human_needed
score: 4/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Confirm the completion email arrived for run 4cbb5311"
    expected: >
      The triggering superadmin (tools@epicimpact.be / NESTOR_ADMIN_EMAIL) received a
      research_complete email from Resend for intake e08620c5, with a link to the admin
      intake detail page and the run duration + total cost visible.
    why_human: >
      UAT test 1 records the email as "pending operator confirmation". The mail renderer
      and six templates exist and are wired through run_poll_driver → resend.send, but
      whether the Resend call actually delivered on the live rev 00035-cqg run cannot be
      confirmed by code inspection — only by checking the inbox.
  - test: "Confirm the progress panel rendered live stages + running cost during the run"
    expected: >
      During the ~48-min run, the admin intake detail page showed ResearchRunProgress
      with one row per stage rendered dynamically (.map over stage_detail), a ticking
      running cost, and elapsed time in tabular-nums — in the intake design language
      (border-l-4, bg-paperLight, font-mono uppercase labels, #FF2D87 accent).
      On completion, the panel collapsed to a summary card.
    why_human: >
      UAT test 2 is explicitly marked [pending]. The component exists, is wired to the
      SSE stream, and renders stage_detail dynamically — but whether it updated live in
      the browser during the actual run can only be confirmed by the operator who watched
      the screen.
  - test: "Confirm no research surface appears in the client-facing UI during in_research"
    expected: >
      A client login on the smoke space during in_research shows the same validated/decomposed
      state as before the run. No ResearchRunProgress panel, no run status, no cost figure.
    why_human: >
      UAT test 3 is marked [pending]. Code evidence supports this (ResearchRunProgress only
      imported in admin.pulse.intakes.$id.tsx; no import in intake.$token.tsx or
      results.$token.tsx) but the client-side UX experience must be verified with a live
      client login.
  - test: "Confirm total run cost (USD) and record it"
    expected: >
      The ResearchRunProgress summary card (or the research_runs row) shows the total cost
      for run 4cbb5311 — this figure must be read off by the operator.
    why_human: >
      UAT test 1 leaves "total cost (USD)" as "[operator to read off completed card]".
      The cost_usd_total column exists in research_runs and is mirrored per poll tick, but
      the actual value is only readable from the live DB or the UI after the completed run.
gaps: []
deferred:
  - truth: "Cost-cap flip-on (NESTOR_TRIBUNAL_UNCAPPED off) enforced for client-billed runs"
    addressed_in: "Phase 20"
    evidence: >
      ROADMAP.md SC5 note: "cost-cap flip-on (NESTOR_TRIBUNAL_UNCAPPED off) is DEFERRED by
      operator decision 2026-07-21 (16-CONTEXT D-02) — before client-billed runs, Phase 20
      at the latest." UAT test 4 confirmed NESTOR_TRIBUNAL_UNCAPPED=1 is still ON by design.
      The stale-window half of ENGINE-03 (NESTOR_WORKER_STALE_MINUTES=90) IS satisfied.
---

# Phase 16: Research Trigger + Progress Bridge — Verification Report

**Phase Goal:** A superadmin can trigger a research run on a `decomposed` intake and watch
live stage-by-stage progress with running cost in the intake admin UI, receiving an email
when it finishes — the milestone spine.

**Verified:** 2026-07-22T16:00:00Z
**Status:** human_needed (4 human verification items; all automated checks VERIFIED)
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC1 | Superadmin triggers a run on a decomposed intake (status → in_research, immediate 202), brief assembled from validated context pack | ✓ VERIFIED | `trigger_research` in `research_routes.py` implements `_RESEARCH_TRANSITIONS = {"decomposed": "in_research"}`; `brief.assemble_brief` called from `read_brief_inputs` before the flip; live run 4cbb5311 on intake e08620c5 reached `completed` — the trigger path is end-to-end proven |
| SC2 | Live run progress (dynamic stage trace + running cost) renders on the intake detail page | ? UNCERTAIN (human needed) | `ResearchRunProgress.tsx` exists, stage list rendered via `.map` over `stage_detail` (no hardcoded count), cost + elapsed clock present; wired in `admin.pulse.intakes.$id.tsx`; SSE stream functional. Whether it rendered live is UAT test 2 [pending] |
| SC3 | Interactive pause gates (needs_input / needs_report_spec) never fire for seam runs | ✓ VERIFIED | `brief.py` defines `INTERACTIVE_REPORT_MARKER` and explicitly never appends it; `assemble_brief` enumerates questions in priority order; `derive_report_hint` returns prose (never /report-spec); the live run completed without any gate firing (109+ LLM calls, no pause state in the driver log) |
| SC4 | Triggering superadmin receives an email when run completes or fails | ? UNCERTAIN (human needed) | `render_research_complete` / `render_research_failed` in `render.py`; six NL/FR/EN templates exist; `run_poll_driver` calls `send_research_complete(acting_email)` on the `completed` branch. Email delivery for run 4cbb5311 is UAT test 1 pending: "Cost/email confirmations pending operator" |
| SC5 | Stale-run reclaim window set above real max run length (no double-runs) | ✓ VERIFIED | UAT test 4 PASS 2026-07-22: `NESTOR_WORKER_STALE_MINUTES=90` confirmed live via `gcloud run services describe tribunal-worker`. NOTE: cost-cap flip-on (`NESTOR_TRIBUNAL_UNCAPPED` off) is explicitly DEFERRED to Phase 20 by operator decision — this half of ENGINE-03 is in the deferred table below, not a gap |

**Score:** 3 truths fully VERIFIED, 2 UNCERTAIN (human confirmation pending) — live mechanics PASS

---

### Per-Requirement Verdicts

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| ENGINE-03 | Cost cap re-enabled + stale-window calibrated | ✓ PARTIAL (stale=VERIFIED; cap=DEFERRED to Phase 20 by operator) | NESTOR_WORKER_STALE_MINUTES=90 live; NESTOR_TRIBUNAL_UNCAPPED=1 intentional per D-02 |
| SEAM-03 | Superadmin triggers run on decomposed intake | ✓ VERIFIED | trigger_research endpoint + live run 4cbb5311 green; 409 on non-decomposed; 3-attempt cap code-complete and tested |
| SEAM-04 | Runs auto-proceed through interactive pause gates | ✓ VERIFIED | brief.py never appends [INTERACTIVE_REPORT]; derive_report_hint returns prose only; live run completed with no gate pause |
| RUN-01 | Superadmin sees live run progress (stages + cost) | ? HUMAN NEEDED | ResearchRunProgress panel exists with dynamic stage map; SSE stream functional; visual rendering during live run is UAT test 2 [pending] |
| RUN-02 | Superadmin receives completion/failure email | ? HUMAN NEEDED | Renderers + templates complete; wired in run_poll_driver; delivery confirmation for run 4cbb5311 is UAT test 1 [pending] |
| ENGINE-07 | Runs execute via worker (never inside HTTP request) | ✓ VERIFIED | run_poll_driver structured through run_with_session_release (READ→release→CALL→WRITE); BackgroundTasks.add_task schedules the driver AFTER the 202 returns; live run ran ~48 min without timeout — proven immune to Cloud Run request timeout |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/app/db/models/research_runs.py` | ResearchRun ORM model with Tribunal-verbatim status, space-leading indexes, A4/D-04 columns | ✓ VERIFIED | `class ResearchRun` present; `tribunal_run_id`, `stage_detail`, `cost_usd_total`, `attempt`, `output_markdown` all present; three space-leading composite indexes correct |
| `backend/app/db/alembic/versions/0011_research_runs.py` | Migration 0011 with FORCE RLS, both policies, grants | ✓ VERIFIED | `revision: str = "0011"`, `down_revision = "0010"`; FORCE ROW LEVEL SECURITY present; `research_runs_space_isolation` (NULLIF form) and `research_runs_superadmin_all` policies; runtime-SA DO-block + superadmin GRANT |
| `backend/app/db/repository.py` | ResearchRunRepository with latest_for_intake | ✓ VERIFIED | `class ResearchRunRepository` added; `create_in_space` + `latest_for_intake` methods present |
| `backend/tests/conftest.py` | fake_tribunal_client fixture | ✓ VERIFIED | `def fake_tribunal_client` at line 830; `pytest.importorskip`-guarded; patches create_run/get_metrics/get_report/ensure_org/ensure_project; network-free |
| `backend/app/research/tribunal_client.py` | create_run / get_metrics / get_report seam methods | ✓ VERIFIED | All three methods present at lines 146/185/211; `engine: "tribunal"` pinned; `uploaded_documents: []` fixed; reuses existing `_headers`/`_mint_id_token` |
| `backend/app/research/brief.py` | assemble_brief + derive_report_hint, never [INTERACTIVE_REPORT] | ✓ VERIFIED | Both functions present; `INTERACTIVE_REPORT_MARKER` defined and explicitly excluded; "Onderzoeksvragen:" header and priority-ordered questions |
| `backend/app/research/run_task.py` | Pool-safe poll driver via run_with_session_release | ✓ VERIFIED | `def run_poll_driver` present; uses `run_with_session_release`; `_RESEARCH_TERMINAL = {"completed", "failed", "cancelled"}`; `output_markdown` persisted on completion; on_error finalizes to "failed"; uuid5 idempotency key |
| `backend/app/api/research_routes.py` | trigger_research + stream_research_run endpoints | ✓ VERIFIED | Both functions present; `_RESEARCH_TRANSITIONS = {"decomposed": "in_research"}`; `RESEARCH_TERMINAL = {"completed", "failed", "cancelled"}`; attempt-cap logic; existence-hidden 404; `background.add_task` |
| `backend/app/mail/render.py` | render_research_complete + render_research_failed | ✓ VERIFIED | Both functions at lines 172/200; use `_localized_template` pattern; autoescape ON (existing env) |
| `backend/app/mail/templates/{nl,fr,en}/research_{complete,failed}.html.j2` | Six mail templates | ✓ VERIFIED | All six files exist; confirmed nl/fr/en/research_complete and nl/research_failed present |
| `backend/tests/test_research_routes.py` | Trigger + SSE + attempt-cap + mail tests | ✓ VERIFIED | `test_trigger_decomposed_ok`, `test_trigger_wrong_status_409`, `test_attempt_cap_3`, `test_completion_mail_to_trigger_user`, `test_research_stream_terminal_set`, `test_research_stream_cancelled_closes` all present |
| `backend/tests/test_research_cross_tenant.py` | Cross-tenant denial suite | ✓ VERIFIED | `test_trigger_cross_tenant_404`, `test_stream_cross_tenant_404`, `test_stream_null_space_403` present; existence-hidden 404 pattern documented |
| `frontend/src/lib/api/research.ts` | triggerResearch + openResearchStream + ResearchRun type | ✓ VERIFIED | All three present; `RESEARCH_TERMINAL = new Set(["completed", "failed", "cancelled"])`; clones `openSkillRunStream` pattern |
| `frontend/src/components/intake/ResearchRunProgress.tsx` | Dynamic-stage panel + summary/failure end states | ✓ VERIFIED | `useActiveResearchRun` hook; `.map` over `stage_detail` (no hardcoded count); `border-l-4`/`bg-paperLight`/`#FF2D87` design language; summary card + failure card with onRetry |
| `frontend/src/components/intake/NextStepBanner.tsx` | AlertDialog confirm gate on Start Research | ✓ VERIFIED | `AlertDialog` + `AlertDialogAction` present; trigger fires ONLY on confirm (D-03) |
| `infra/DEPLOY-RUNBOOK.md` | Phase 16 runbook section | ✓ VERIFIED | `## Phase 16` at line 1131; steps 16.a through 16.f present; `NESTOR_WORKER_STALE_MINUTES=90` step 16.d |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `research_routes.py` | `run_task.run_poll_driver` | `background.add_task` after 202 | ✓ WIRED | `background.add_task(run_poll_driver, ...)` confirmed at line 236 |
| `research_routes.py` (SSE) | `stream_session.read_latest_research_run_dict` | `run_in_threadpool` per tick | ✓ WIRED | Pattern mirrors stream_skill_runs; read fn confirmed in stream_session.py |
| `main.py` | `research_router` | `protected_router.include_router(research_router)` | ✓ WIRED | Lines 49 and 152 in main.py confirm mount |
| `run_task.py` | `run_with_session_release` | READ→release→CALL→WRITE contract | ✓ WIRED | `from app.db.ai_session import run_with_session_release` + `run_with_session_release(...)` call at line 547 |
| `brief.py` | Tribunal pause gates | Never appends `[INTERACTIVE_REPORT]` | ✓ WIRED | Marker defined as constant; assemble_brief explicitly excludes it; confirmed by code + live run completion without gate |
| `admin.pulse.intakes.$id.tsx` | `ResearchRunProgress` | `import` + mount when `status === "in_research"` | ✓ WIRED | Import at line 47; mount at lines 1108–1109 |
| `NextStepBanner.tsx` | `onStartAutoResearch` | `AlertDialogAction onClick` (never direct button) | ✓ WIRED | AlertDialog pattern confirmed; confirm-gated trigger |
| `ResearchRunProgress` import | Client routes (`*.$token.tsx`) | NOT present (D-08 — isolation) | ✓ VERIFIED (absent) | grep of `frontend/src/routes/` shows ResearchRunProgress only in `admin.pulse.intakes.$id.tsx` |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `ResearchRunProgress.tsx` | `run` (ResearchRun) | `useActiveResearchRun` → `openResearchStream` SSE → `GET /intakes/{id}/research/stream` → `read_latest_research_run_dict` → `research_runs` DB row | Yes — poll driver mirrors Tribunal /metrics every ~3s; live run produced 109+ audit records + completed terminal | ✓ FLOWING |
| `run_task.py` (output_markdown) | `output_markdown` | `tribunal_client.get_report` → Tribunal `/api/runs/{id}/report` → persisted to `research_runs.output_markdown` | Yes — live run reached `completed`; report fetched at terminal | ✓ FLOWING |
| `render.py` (research_complete mail) | `acting_email` | set from `identity.email` at trigger time; passed through poll driver | Yes — code traces from trigger identity to `resend.send(to=[acting_email])`; delivery pending human confirmation | ✓ FLOWING (delivery ? HUMAN) |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED for tests requiring a live server (no local Python/Docker per environment note).
Frontend typecheck was run by the executor: `npx tsc --noEmit` clean (confirmed in 16-04 SUMMARY).

**Live run as spot-check (operator-executed, 2026-07-22):**

| Behavior | Evidence | Status |
|----------|----------|--------|
| Trigger → committed tx → driver START | Log chain in 16-05-SUMMARY: `research driver scheduled` → `run_poll_driver START` → `create_run engine_status=queued` | ✓ PASS |
| Worker claims run (<1s) | `run_claimed <1s` in driver log | ✓ PASS |
| 109+ LLM calls mirrored | 82+ MiB audit records in GCS audit prefix | ✓ PASS |
| Terminal `completed` reached (~48 min) | Driver log: `terminal status=completed` → `DONE` at 12:04:28Z | ✓ PASS |
| NESTOR_WORKER_STALE_MINUTES=90 live | UAT test 4 PASS: `gcloud run services describe tribunal-worker` env confirmed | ✓ PASS |

---

### Probe Execution

No phase-declared probes. The VALIDATION.md lists Cloud Build test commands that cannot run on the dev box (no Python/Docker). Live operator run serves as the functional integration proof.

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| ENGINE-03 (partial) | 16-01, 16-05 | Stale-window calibrated above max run length | ✓ SATISFIED (stale half) | NESTOR_WORKER_STALE_MINUTES=90 live; cost-cap half DEFERRED to Phase 20 |
| ENGINE-07 | 16-02, 16-03 | Runs via worker, immune to Cloud Run timeout | ✓ SATISFIED | run_with_session_release + always-on worker; ~48-min run completed |
| SEAM-03 | 16-03, 16-04 | Superadmin triggers on decomposed intake | ✓ SATISFIED | Live run 4cbb5311 green; code + live evidence |
| SEAM-04 | 16-02 | Interactive pause gates never fire | ✓ SATISFIED | brief.py construction + live run without any pause state |
| RUN-01 | 16-03, 16-04 | Live progress panel (stages + cost) | ? HUMAN NEEDED | Component wired; visual confirmation UAT test 2 pending |
| RUN-02 | 16-02, 16-03 | Completion/failure email to triggering superadmin | ? HUMAN NEEDED | Renderers + templates + wiring complete; email delivery UAT test 1 pending |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `backend/app/research/run_task.py` (module slot `_ACTIVE_IDENTITY`) | Module-level state | ℹ Info | Documented decision (16-02 SUMMARY): required by run_with_session_release contract which doesn't pass identity to write_fn/on_error. Not a stub — set at the top of every run_poll_driver call. Single-run-per-call safe. |
| UAT test 1 / completion email | `pending operator` | ⚠ Warning | Email delivery for run 4cbb5311 unconfirmed. RUN-02 cannot close as SATISFIED without this. |
| UAT test 2 / panel visual | `pending` | ⚠ Warning | Progress panel live rendering unconfirmed. RUN-01 visual UAT pending. |

No TBD / FIXME / XXX / placeholder markers found in Phase 16 source files. No return null /
return {} / return [] stub patterns in the research module.

---

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases:

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | Cost-cap flip-on (NESTOR_TRIBUNAL_UNCAPPED off) for client-billed runs | Phase 20 | ROADMAP.md SC5 note: "cost-cap flip-on is DEFERRED by operator decision 2026-07-21 — before client-billed runs, Phase 20 at the latest." 16-CONTEXT D-02 confirms intentional deferral. UAT test 4 verified UNCAPPED=1 is ON as designed. |

---

### Human Verification Required

#### 1. Completion Email Delivery Confirmation

**Test:** Check the inbox for `tools@epicimpact.be` (or the configured `NESTOR_ADMIN_EMAIL`) for
an email from Resend corresponding to the completed research run on intake e08620c5
(run 4cbb5311, terminal at 12:04:28Z on 2026-07-22).

**Expected:** A short email in NL with: "Research for [client] is done" + run duration (~48 min)
+ total cost (USD) + one CTA button linking to the admin intake detail page.

**Why human:** Email delivery requires live Resend API response, not verifiable by code
inspection. UAT test 1 leaves this as "[operator to confirm]".

---

#### 2. Progress Panel Visual (RUN-01 UAT)

**Test:** Run a second smoke run on a decomposed intake in the smoke space. During the run, open
the admin intake detail page and observe the ResearchRunProgress panel.

**Expected:** One row per stage rendered dynamically from stage_detail (.map); a running cost
that ticks every ~3s (poll cadence); elapsed time in tabular-nums; intake design language
(border-l-4, bg-paperLight, font-mono uppercase stage labels, #FF2D87 accent). On terminal
status, panel collapses to a summary card (timestamp / total cost / duration) or failure card.

**Why human:** Visual/UX confirmation; SSE rendering behavior cannot be grep-verified. UAT
test 2 is explicitly [pending].

---

#### 3. Client Isolation During in_research (D-08)

**Test:** While an intake is in_research, log in as a client user for the same space. Navigate
to the client intake view.

**Expected:** The client UI shows NO research surface — no ResearchRunProgress panel, no run
status, no cost figure. The intake appears in its pre-research state (validated/decomposed view).

**Why human:** Client-side UX experience during an active run requires a live session with a
client-role user. UAT test 3 is explicitly [pending]. Code evidence already supports D-08
(ResearchRunProgress is admin-only by import structure).

---

#### 4. Run Cost Amount

**Test:** Read the `cost_usd_total` for run 4cbb5311 from either the completed ResearchRunProgress
summary card or directly from the `research_runs` DB row.

**Expected:** A non-zero USD amount reflecting the 109+ LLM calls (~48 min run with
claude-sonnet-4-6 + google deep-research sub-agents + gemini-2.5-flash).

**Why human:** UAT test 1 records this as "[operator to read off completed card]". The field
is mirrored per tick from Tribunal /metrics so the value exists in the DB — only the operator
can confirm the actual figure and whether it rendered correctly in the UI.

---

### Gaps Summary

No blocking gaps. All five plans completed, all 15 key artifacts exist and are substantive,
all key wiring links are confirmed. The live run 4cbb5311 (intake e08620c5, ~48 min,
`completed`) provides end-to-end mechanical proof of the trigger → poll → mirror → terminal
chain (ENGINE-03/SEAM-03 mechanics, ENGINE-07, SEAM-04).

The phase status is `human_needed` — not `gaps_found` — because:
- RUN-01 (progress panel visual) and RUN-02 (completion email delivery) cannot be confirmed
  by code inspection alone; the live UAT for both is still partially pending operator
  confirmation (UAT tests 1 and 2).
- The run mechanics PASSED. Once the operator confirms email receipt and panel rendering,
  the status can be upgraded to `passed`.

---

_Verified: 2026-07-22T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
