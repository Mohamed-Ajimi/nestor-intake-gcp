# Phase 16: Research Trigger + Progress Bridge - Context

**Gathered:** 2026-07-21
**Status:** Ready for planning

<domain>
## Phase Boundary

The milestone spine: a superadmin triggers a Tribunal deep-research run on a `decomposed` intake
(immediate 202, status → `in_research`), with the brief assembled from the intake's validated
context pack. Live run progress (stage trace + running cost) renders on the intake detail page in
the intake design language, fed by a background poll → `research_runs` → SSE bridge. The
triggering superadmin receives an email when the run completes or fails. Runs execute on the
always-on worker (never inside an HTTP request). The stale-run reclaim window is calibrated above
the Phase-13 measured max run length.

Requirements: SEAM-03, SEAM-04, RUN-01, RUN-02, ENGINE-03 (partial — see D-02), ENGINE-07.

**Ordering note:** Phase 15 (plan-critique + draft tournament) is DEFERRED after Phase 19 (operator
decision 2026-07-21). This phase integrates against the engine exactly as it runs today, and the
progress UI MUST render the stage list dynamically from the run's stage trace (9 stages today, no
hardcoded count) so Phase 15's added pass later costs nothing.

**Out of scope:** raw-output download (Phase 17), report upload/delivery (Phase 18), Q&A chat
(Phase 19), engine enhancements (Phase 15, deferred), any client-visible research surface
(REPORT-02 rule), run-cancel/stop mid-flight.

**Absorbed elsewhere:** the Phase-13 queue-path proof was closed by Phase 14's D-07 seam run —
struck from this phase's backlog. The first real intake-originated trigger call through the seam
CLOSES the deferred Phase-14 seam HTTP UAT (`14-HUMAN-UAT.md`) — record it there when it happens.

</domain>

<decisions>
## Implementation Decisions

### Interactive pauses (SEAM-04) — gates are OBSOLETE for seam runs
- **D-01 (needs_input never fires):** The intake flow's enrichment/validation/decomposition already
  did the brief back-and-forth — the validated context pack IS the answered brief. Seam-triggered
  runs enter the pipeline at the point where the orchestrating agent delegates the validated
  questions across the deep-research angles (multi-provider fan-out); the brief-clarification gate
  must never fire. HOW (enter downstream of the clarification stage vs. mark the brief
  pre-clarified) is builder discretion, under the hard constraint that the frozen audit payload and
  stage-trace structure are not broken (`verify_chain` stays green).
- **D-01b (needs_report_spec auto-derived from intake):** The report spec (structure of the raw
  engine report) is built per-run by the backend from the client's intake answers (sector, goals,
  etc.), with a sane fixed fallback structure when intake fields are thin. The gate never fires.
  Exact field → spec mapping is builder discretion.

### Trigger guardrails & cost (ENGINE-03)
- **D-02 (UNCAPPED stays ON — operator deferral):** `NESTOR_TRIBUNAL_UNCAPPED=1` remains for now;
  the $25/run ceiling stays wired but unenforced. The cap flip-on is EXPLICITLY DEFERRED by the
  operator (2026-07-21) — must happen before real client-billed runs, Phase 20 at the latest.
  The OTHER half of ENGINE-03 stays in scope: the stale-run reclaim window IS calibrated in this
  phase (above the Phase-13 measured max run length — no double-runs).
- **D-03 (confirm dialog before trigger):** "Start research" opens a confirmation dialog ("Start
  deep research for [client]? This runs for a while and costs money") — same pattern as the app's
  other destructive-action dialogs. Only on confirm does the 202 trigger fire.
- **D-04 (re-trigger up to 3 attempts):** On run failure, the failed run stays visible in history
  and the trigger button returns — up to 3 total attempts per intake. After the third failure the
  UI shows a "needs investigation" state instead of the button.
- **D-05 (provider fallback = verify, not build):** Multi-LLM outage fallback already exists in the
  engine (Anthropic + OpenAI + Gemini, ≥2-of-3 degradation — enabled in Phase 13 D-06, demonstrated
  live in Phase 14's D-07 run). This phase VERIFIES it is active on seam runs; no new fallback code.
- **D-06 (one active run per intake — via status machine):** The trigger only renders on
  `decomposed`; triggering flips status to `in_research`, removing the button. No extra locking UI.

### Progress experience (RUN-01)
- **D-07 (full progress panel):** A dedicated block on the admin intake detail page: every stage
  listed with done/running/pending state, plus running cost and elapsed time — the SkillRunProgress
  pattern scaled up to the whole research run. Stage list rendered DYNAMICALLY from the stage trace
  (Phase 15 contract — no hardcoded stage count).
- **D-08 (client sees NO change at all):** During `in_research` the client-facing UI shows exactly
  what it showed before the run started (validated/decomposed state). Research is completely
  invisible to clients until Phase 18 delivery (REPORT-02 rule, chosen strictly).
- **D-09 (summary card end state):** On completion the progress panel collapses into a result
  card: completed timestamp, total cost, duration, stages all green. This card is the anchor
  Phase 17 later adds the raw-output download button to. Failure end state shows what failed +
  re-trigger affordance (per D-04).

### Completion/failure emails (RUN-02)
- **D-10 (email to whoever triggered):** The completion/failure email goes to the superadmin who
  clicked "Start research" (their own address, known from the authenticated trigger call).
- **D-11 (short + link):** Email body is short — "Research for [client] is done" + duration + cost,
  one button linking to the intake detail page. Failure variant: what failed + link. Same style and
  template stack as the existing Phase 10 mails (Resend + Jinja, NL convention).

### Claude's Discretion
- How the pipeline entry-point skip/pre-answer is implemented (D-01) and the intake-fields →
  report-spec mapping (D-01b), including the fallback structure.
- `research_runs` intake-side table design, poll cadence, and the poll → SSE bridge mechanics
  (Phase 8's DB-backed SSE pattern is the reference).
- Brief-assembly details from the validated context pack (which fields, formatting).
- Stale-run window exact value (above Phase-13 measured max; check 13-04/14-04 SUMMARYs for the
  recorded duration).
- Progress panel visual details within the intake design language (round-3 merged workflow panel).
- Attempt-count storage/enforcement for the 3-attempt rule (D-04).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Prior phase context (the seam this phase builds on)
- `.planning/phases/14-auth-retirement-integration-seam/14-CONTEXT.md` — seam decisions carried
  forward: D-04 defense-in-depth OIDC, D-05 acting-user headers (audit attribution), D-06 minimal
  client (this phase adds trigger/poll methods), D-07 absorbed queue-path proof
- `.planning/phases/14-auth-retirement-integration-seam/14-HUMAN-UAT.md` — the deferred live seam
  HTTP UAT this phase's first real trigger call closes
- `.planning/phases/13-tribunal-re-home-infra-baseline/13-CONTEXT.md` — deploy posture, worker
  model (min-instances=1), D-07 uncapped semantics, D-08 5+ concurrency target
- `.planning/ROADMAP.md` § Phase 16 — goal + 5 success criteria + dynamic-stage-list constraint
- `.planning/REQUIREMENTS.md` — SEAM-03, SEAM-04, RUN-01, RUN-02, ENGINE-03, ENGINE-07

### v1.1 research (engine internals this phase integrates against)
- `.planning/research/ARCHITECTURE.md` — Tribunal run lifecycle, stage model, `research_runs`
  bridge design (§ the poll → SSE recommendation), GUC conventions
- `.planning/research/PITFALLS.md` — stale-reclaim double-run trap (the window calibrated here),
  audit hash-chain fragility (D-01 constraint), paused-instance gotchas
- `.planning/research/FEATURES.md` — `needs_input`/`needs_report_spec` semantics + the
  `needs_report_spec` status-CHECK migration gap (`db/models/run.py:103` vs `worker.py:159`) —
  relevant because D-01/D-01b make these states unreachable for seam runs; decide handling

### Tribunal copy (run lifecycle + pause gates)
- `tribunal/nestor_pulse_sdk/runs/worker.py` — worker loop, stage progression, pause-gate logic
  (where needs_input/needs_report_spec are raised — the code D-01/D-01b must neutralize)
- `tribunal/nestor_pulse_sdk/db/models/run.py` — run status model + stage trace shape the bridge
  polls and the progress UI renders
- `tribunal/nestor_pulse_sdk/server.py` — the API surface the seam client calls (runs endpoints)

### Intake side (where the new code lands)
- `backend/app/research/tribunal_client.py` — the Phase 14 seam client (OIDC minting,
  acting-user headers, ensure_org/ensure_project) this phase extends with trigger/poll methods
- `backend/app/api/intake_routes.py` (~line 1056-1150) — `stream_skill_runs`: the codebase's one
  deliberate `async def` SSE handler; the DB-backed, tenant-scoped stream pattern to replicate for
  research-run progress
- `backend/app/db/models/research.py` + `backend/app/db/models/skill_run.py` — existing model
  conventions for the new `research_runs` table
- `backend/app/mail/` (render.py, resend.py, templates/) — the Phase 10 mail stack for D-10/D-11
- `frontend/src/components/intake/SkillRunProgress.tsx` — the progress-block pattern D-07 scales up
- `frontend/src/components/intake/NextStepBanner.tsx` + `frontend/src/lib/intake-phase.ts` — the
  phase machine + CTA banner where the trigger button and `in_research` handling plug in
- `infra/DEPLOY-RUNBOOK.md` — runbook this phase extends (new env, deploy steps, live UAT session)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tribunal_client.py` — OIDC + acting-user header machinery ready; just add methods.
- `stream_skill_runs` SSE handler — proven DB-backed stream shape (headers, keepalive, tenant
  scoping); replicate for research runs rather than invent a new mechanism.
- Phase 10 mail stack (Resend + Jinja base template, NL/FR/EN dirs) — completion/failure mails are
  new templates on existing plumbing.
- `SkillRunProgress.tsx` + `useActiveSkillRun` polling/SSE hooks — frontend progress pattern.
- Phase machine (`intake-phase.ts`) — `in_research` phase already exists from v1.0; the trigger
  extends `derivePhase` inputs rather than adding a parallel mechanism.

### Established Patterns
- Backend handlers are sync `def` on pg8000 (threadpool); the SSE stream is the single deliberate
  `async def` — keep it that way for the research stream.
- Tenant isolation: every new read/write goes through the space-scoped session and gets
  cross-tenant denial tests from day one (STATE.md v1.1 blocker — applies to `research_runs` and
  the trigger/progress endpoints).
- Deploys: by-construction artifacts + operator-run runbook live session (no local Python/Docker;
  Cloud Build for images/tests).
- Two GUCs / two schemas stay separate; the seam is HTTP-only (no shared DB session with Tribunal).

### Integration Points
- Trigger endpoint (intake backend) → seam client → Tribunal `POST /api/runs` (with D-01/D-01b
  neutralized gates) → always-on worker executes.
- Background poll (intake backend) → Tribunal run status → `research_runs` rows → SSE → admin UI.
- Status machine: `decomposed` → (trigger) → `in_research`; completion does NOT auto-advance
  status (delivery flips it in Phase 18 — D-report from PROJECT.md).
- Email send on poll-detected terminal state (completed/failed) via mail stack.

</code_context>

<specifics>
## Specific Ideas

- "The last part of intake already did the back and forth of enriching the questions — Tribunal
  should start at the part where an agent delegates the questions to different deep researches
  according to angles": the founding insight of this phase — the intake flow replaces Tribunal's
  interactive clarification entirely (D-01).
- "Uncapped for now" — operator explicitly repeated the Phase-13 posture for this phase's runs;
  cap flip-on is a recorded deferral, not an oversight (D-02).
- "Re-trigger up to 3 times, also have fallback llms in case of outage" — resilience is
  attempt-count + existing engine degradation, not new failover machinery (D-04/D-05).

</specifics>

<deferred>
## Deferred Ideas

- **Cost-cap flip-on (`NESTOR_TRIBUNAL_UNCAPPED` off) + cap value decision** — deferred by
  operator; before real client-billed runs, Phase 20 at the latest (D-02).
- **Run cancel/stop mid-flight** — not in v1.1 scope; note for backlog if a runaway uncapped run
  ever hurts.
- **Client-visible progress step** — operator chose "no change at all" (D-08); a generic
  "in progress" stepper hint could be revisited post-delivery phases.
- **Detailed digest emails (stage recap/findings in the mail body)** — rejected for v1.1; short +
  link chosen (D-11).

</deferred>

---

*Phase: 16-Research Trigger + Progress Bridge*
*Context gathered: 2026-07-21*
