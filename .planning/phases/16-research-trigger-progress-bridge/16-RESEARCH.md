# Phase 16: Research Trigger + Progress Bridge - Research

**Researched:** 2026-07-21
**Domain:** Server-to-server run trigger + poll→SSE progress bridge over the Phase-14 HTTP seam (FastAPI/Cloud Run/Cloud SQL; sync pg8000 intake ↔ async asyncpg Tribunal engine)
**Confidence:** HIGH — every claim grounded in source read directly this session (both codebases live in this repo); the v1.1 research trio (`.planning/research/{ARCHITECTURE,PITFALLS,FEATURES}.md`) was cross-checked against the actual Tribunal code and found accurate, with two corrections noted below.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Interactive pauses (SEAM-04) — gates are OBSOLETE for seam runs**
- **D-01 (needs_input never fires):** The intake flow's enrichment/validation/decomposition already did the brief back-and-forth — the validated context pack IS the answered brief. Seam-triggered runs enter the pipeline at the point where the orchestrating agent delegates the validated questions across the deep-research angles (multi-provider fan-out); the brief-clarification gate must never fire. HOW (enter downstream of the clarification stage vs. mark the brief pre-clarified) is builder discretion, under the hard constraint that the frozen audit payload and stage-trace structure are not broken (`verify_chain` stays green).
- **D-01b (needs_report_spec auto-derived from intake):** The report spec (structure of the raw engine report) is built per-run by the backend from the client's intake answers (sector, goals, etc.), with a sane fixed fallback structure when intake fields are thin. The gate never fires. Exact field → spec mapping is builder discretion.

**Trigger guardrails & cost (ENGINE-03)**
- **D-02 (UNCAPPED stays ON — operator deferral):** `NESTOR_TRIBUNAL_UNCAPPED=1` remains for now; the $25/run ceiling stays wired but unenforced. Cap flip-on EXPLICITLY DEFERRED by the operator (2026-07-21) — must happen before real client-billed runs, Phase 20 at the latest. The OTHER half of ENGINE-03 stays in scope: the stale-run reclaim window IS calibrated in this phase (above the Phase-13 measured max run length — no double-runs).
- **D-03 (confirm dialog before trigger):** "Start research" opens a confirmation dialog ("Start deep research for [client]? This runs for a while and costs money") — same pattern as the app's other destructive-action dialogs. Only on confirm does the 202 trigger fire.
- **D-04 (re-trigger up to 3 attempts):** On run failure, the failed run stays visible in history and the trigger button returns — up to 3 total attempts per intake. After the third failure the UI shows a "needs investigation" state instead of the button.
- **D-05 (provider fallback = verify, not build):** Multi-LLM outage fallback already exists in the engine (Anthropic + OpenAI + Gemini, ≥2-of-3 degradation — enabled in Phase 13 D-06, demonstrated live in Phase 14's D-07 run). This phase VERIFIES it is active on seam runs; no new fallback code.
- **D-06 (one active run per intake — via status machine):** The trigger only renders on `decomposed`; triggering flips status to `in_research`, removing the button. No extra locking UI.

**Progress experience (RUN-01)**
- **D-07 (full progress panel):** A dedicated block on the admin intake detail page: every stage listed with done/running/pending state, plus running cost and elapsed time — the SkillRunProgress pattern scaled up to the whole research run. Stage list rendered DYNAMICALLY from the stage trace (Phase 15 contract — no hardcoded stage count).
- **D-08 (client sees NO change at all):** During `in_research` the client-facing UI shows exactly what it showed before the run started (validated/decomposed state). Research is completely invisible to clients until Phase 18 delivery (REPORT-02 rule, chosen strictly).
- **D-09 (summary card end state):** On completion the progress panel collapses into a result card: completed timestamp, total cost, duration, stages all green. This card is the anchor Phase 17 later adds the raw-output download button to. Failure end state shows what failed + re-trigger affordance (per D-04).

**Completion/failure emails (RUN-02)**
- **D-10 (email to whoever triggered):** The completion/failure email goes to the superadmin who clicked "Start research" (their own address, known from the authenticated trigger call).
- **D-11 (short + link):** Email body is short — "Research for [client] is done" + duration + cost, one button linking to the intake detail page. Failure variant: what failed + link. Same style and template stack as the existing Phase 10 mails (Resend + Jinja, NL convention).

### Claude's Discretion
- How the pipeline entry-point skip/pre-answer is implemented (D-01) and the intake-fields → report-spec mapping (D-01b), including the fallback structure.
- `research_runs` intake-side table design, poll cadence, and the poll → SSE bridge mechanics (Phase 8's DB-backed SSE pattern is the reference).
- Brief-assembly details from the validated context pack (which fields, formatting).
- Stale-run window exact value (above Phase-13 measured max; check 13-04/14-04 SUMMARYs for the recorded duration).
- Progress panel visual details within the intake design language (round-3 merged workflow panel).
- Attempt-count storage/enforcement for the 3-attempt rule (D-04).

### Deferred Ideas (OUT OF SCOPE)
- **Cost-cap flip-on** (`NESTOR_TRIBUNAL_UNCAPPED` off) + cap value decision — deferred by operator; before real client-billed runs, Phase 20 at the latest (D-02).
- **Run cancel/stop mid-flight** — not in v1.1 scope; note for backlog if a runaway uncapped run ever hurts.
- **Client-visible progress step** — operator chose "no change at all" (D-08).
- **Detailed digest emails** (stage recap/findings in the mail body) — rejected for v1.1; short + link chosen (D-11).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEAM-03 | Superadmin can trigger a research run on a `decomposed` intake (status → `in_research`), with the brief assembled from the intake's validated context pack | Brief assembly § (context pack lives in `nestor.decompositions` + `research_questions`; flatten to one prose `brief`). Trigger endpoint + `tribunal_client.create_run()` extension § |
| SEAM-04 | Runs auto-proceed through Tribunal's interactive pauses (`needs_input`/`needs_report_spec`) with sensible defaults (zero-touch) | Pause-gate neutralization § — both gates are controlled purely by the brief string the seam composes; neither fires unless the seam opts in. No pipeline edit needed |
| RUN-01 | Superadmin sees live run progress (stages + running cost) on the intake detail page, in the intake design language | Poll→SSE bridge § — `research_runs` mirror + SSE endpoint cloning `stream_skill_runs`; stage schema from `GET /api/runs/{id}/metrics` (`stages` + `current_stage` + `stage_detail`) rendered dynamically |
| RUN-02 | Superadmin receives an email when the run completes or fails | Email on terminal state § — Phase 10 mail stack (`render.py` + `resend.py`), new NL templates; recipient = acting superadmin `identity.email` |
| ENGINE-03 (partial) | Stale-run reclaim window calibrated above real max run length (cost cap DEFERRED per D-02) | Stale-run window § — measured max 17–19 min (Phase 13/14); `NESTOR_WORKER_STALE_MINUTES` env, currently 60 |
| ENGINE-07 | Runs execute via queue + always-on worker (never in an HTTP request) — immune to Cloud Run request timeouts | Trigger is a queue insert via `POST /api/runs` (status=`queued`); the always-on worker (`worker.py` SKIP-LOCKED, min-instances=1) executes. Already proven live in Phase 14 D-07 |
</phase_requirements>

## Summary

This phase is almost entirely **integration glue on top of proven components**. The two codebases are already re-homed (Phase 13), the HTTP seam is live and OIDC-authed (Phase 14 `tribunal_client.py`, D-07 ran one real research run to `completed` with `verify_chain=OK` at $1.60), and every transport this phase needs already exists on both sides: Tribunal exposes a **DB-queue + poll-REST** run lifecycle (no WebSocket, no callbacks), and intake has a **DB-backed poll-inside-SSE** stream (`stream_skill_runs`) plus a **READ→release→CALL→WRITE** background-task contract (`run_with_session_release`). The work is to extend `tribunal_client.py` with `create_run`/`get_metrics`/`get_report`, add an intake-side `research_runs` mirror table + a background poll task that drives Tribunal to completion and writes each tick into that row, clone the SSE handler to stream that row, and wire a trigger endpoint + a progress panel + a completion mail.

**The single most important finding** is that the two "pause gates" this phase must neutralize (SEAM-04, D-01/D-01b) require **no pipeline modification and no risk to the audit chain**. Both gates are opt-in behaviors controlled entirely by the `brief` string the seam composes: `needs_report_spec` only fires when the brief contains the literal `[INTERACTIVE_REPORT]` marker (`pipeline.py:158,781`) — seam runs simply never add it (zero-touch synthesis is the default at `pipeline.py:795`). `needs_input` only fires when the `intake` stage judges the brief *vague* and `allow_clarification` is on; a well-assembled brief from a validated context pack is not vague, and the pipeline also force-proceeds after 2 `[CLARIFICATION ANSWERS]` rounds (`pipeline.py:189-215`). Because the seam controls the brief and never opts into either gate, neither ever fires — the frozen `canonical_json` audit payload and stage-trace structure are untouched. **Recommendation: neutralize by brief composition, not by editing the engine.**

**Primary recommendation:** Extend the existing seam client + clone the two existing DB-backed transports (background-task + SSE); add ONE new intake table (`research_runs`), ONE Alembic migration (0011), ONE trigger route, ONE SSE route, ONE background poll task, and two NL mail templates. Do NOT edit the Tribunal pipeline, worker, or audit code. Keep `NESTOR_WORKER_STALE_MINUTES` ≥ 60 (measured max run is 17–19 min; 60 is already comfortably above, but see the ENGINE-03 note for the double-dispatch nuance).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| "Start research" CTA + confirm dialog (D-03) | Frontend (React admin) | Intake API | UI affordance gated on `decomposed`; server enforces the transition |
| Trigger → status flip `decomposed`→`in_research` (SEAM-03) | Intake API (sync `def`) | Cloud SQL (`nestor`) | Space-scoped write; must be a discrete allow-listed verb like existing `/submit`,`/review` |
| Brief assembly from context pack (SEAM-03) | Intake API | Cloud SQL (`nestor`) | The intake owns the decomposed questions; flattens to prose before the seam call |
| Run creation + queueing (ENGINE-07) | Tribunal API (`POST /api/runs`) | Tribunal worker | Engine's queue table is the timeout-immune execution boundary — never inline |
| Pipeline execution (9 stages) | Tribunal worker (always-on, min=1) | Providers (Anthropic/OpenAI/Gemini) | Unchanged engine; the seam only triggers + polls |
| Pause-gate neutralization (SEAM-04, D-01/D-01b) | Intake API (brief composition) | — | Controlled by the brief string the seam sends; NO engine tier touches this |
| Progress poll → mirror write (RUN-01) | Intake API (background task) | Tribunal API (`/metrics` poll) | Poll runs in the intake backend's BackgroundTask; writes the `research_runs` mirror |
| Live progress push to browser (RUN-01) | Intake API (async SSE handler) | Cloud SQL (`nestor`) | The ONE deliberate `async def`; reads the mirror row per tick, pushes SSE |
| Progress panel render (RUN-01, D-07/D-09) | Frontend (React admin) | — | Renders stage list DYNAMICALLY from the run's `stages` array (no hardcoded 9) |
| Completion/failure email (RUN-02, D-10/D-11) | Intake API (background task on terminal) | Resend | Phase-10 mail stack; recipient = acting superadmin's own email |
| Stale-run reclaim window (ENGINE-03 partial) | Tribunal worker (env `NESTOR_WORKER_STALE_MINUTES`) | — | Config-only; calibrate above measured max run length |
| Client-facing UI during `in_research` (D-08) | Frontend (client route) | — | MUST be unchanged — no research surface until Phase 18 |

## Standard Stack

This phase adds **no new third-party packages**. Every capability is served by dependencies already vendored and proven in prior phases.

### Core (already present — reuse verbatim)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | present (used by `tribunal_client.py`, `mail/resend.py`) | Blocking server-to-server POST/GET to the Tribunal internal API | Already the seam + mail transport; sync `httpx.post`/`.get` matches the sync-`def` handler contract |
| `google-auth` | pinned `>=2.47` (Phase 14 WR-08 floor) | Keyless OIDC ID-token minting for the Tribunal audience (`fetch_id_token`) | Already wired in `tribunal_client._mint_id_token`; extend for the new POST/GET methods, same audience rule |
| `FastAPI` `BackgroundTasks` | present | Kick the poll driver after the 202 trigger returns | The AI-06 pattern (`run_with_session_release`) is already the "long job, poll, write back" primitive |
| `jinja2` | present (`mail/render.py`) | Render the NL completion/failure mail bodies | Phase 10 stack; autoescape ON (T-10-01) |
| `SQLAlchemy` + `pg8000` | present | `research_runs` model + scoped reads/writes | Intake's sync driver; the whole backend is built on it |
| `anyio` | present | SSE tick sleep + disconnect check in the async stream handler | Already used by `stream_skill_runs` |

### Supporting (Tribunal side — already deployed, do NOT modify)
| Component | Purpose | When to Use |
|-----------|---------|-------------|
| `POST /api/runs` (`runs/api.py:112`) | Create/queue a run; idempotent on `(tenant_id, idempotency_key)` | The trigger's downstream call. Body: `{project_id, brief, engine:"tribunal", idempotency_key, uploaded_documents:[]}` |
| `GET /api/runs/{id}/metrics` (`runs/api.py:786`) | Live poll: `status`, `cost_usd_total`, `elapsed_seconds`, `stages[]`, `current_stage`, `stage_detail` | The poll driver's per-tick read — richest progress surface |
| `GET /api/runs/{id}` (`runs/api.py:927`) | Lighter status-only poll (`RunResponse`) | Alternative if `/metrics` is heavier than needed |
| `GET /api/runs/{id}/report` (`runs/api.py:852`) | Rendered report + sources (only after `completed`) | Fetch on terminal to persist raw output (Phase 17 surfaces the download; this phase may store it) |
| `POST /api/orgs/ensure`, `POST /api/projects/ensure` (`orgs/api.py`) | Idempotent space→org + one-project-per-space provisioning | Already wrapped by `tribunal_client.ensure_org/ensure_project`; call before `create_run` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| In-process `BackgroundTask` poll driver | Cloud Scheduler / Cloud Tasks ping loop | New infra + IAM + drift risk (Pitfall 12). The BackgroundTask on a `min-instances≥1` service already survives the ~19-min run; SSE fallback poll covers instance loss. **Rejected** unless a run outlives an instance's max lifetime (not observed) |
| Poll `/metrics` each tick | Direct read of Tribunal's `run` row from intake | Would open a `tribunal.*` transaction from the intake process — couples two GUCs/schemas (Pitfall 2, AP-2). **Rejected** — HTTP seam only |
| `create_run` idempotency via `uuid4` per trigger | Deterministic `uuid5(intake_id, attempt_n)` | Deterministic keys make a retried trigger safe (no double-charge) AND enforce the 3-attempt cap naturally. **Recommended** — see D-04 mapping |

**Installation:** None. No `pip install`. (Verified: `backend/app/research/tribunal_client.py` already imports `httpx`, `google.auth.transport.requests`, `google.oauth2.id_token`; `backend/app/mail/` already has `jinja2` + `httpx`.)

**Version verification:** Not applicable — zero new packages. Existing pins confirmed live: `google-auth>=2.47` (Phase 14 WR-08, MEMORY `phase-14-executed-live-fix-cycle`); `google-adk` floor forced this pin.

## Package Legitimacy Audit

> Not applicable — this phase installs **no external packages**. Every dependency (`httpx`, `google-auth`, `jinja2`, `SQLAlchemy`, `pg8000`, `anyio`, FastAPI) is already vendored, deployed, and exercised live in Phases 7–14. No registry lookup, no slopcheck, no new secret. If the plan later decides to persist raw output to GCS, that reuses the existing `storage/gcs.py` client (also already present). **Disposition: N/A — no install step.**

## Architecture Patterns

### System Architecture Diagram

```
  Superadmin (admin intake detail page, status == decomposed)
      │  clicks "Start research" → confirm dialog (D-03)
      │  POST /intakes/{id}/research         (Bearer, superadmin-only)
      ▼
┌─ INTAKE BACKEND (sync def, pg8000) ──────────────────────────────────────┐
│ research_routes.trigger:                                                  │
│   • verify intake in scope + status == decomposed (else 409)             │
│   • enforce attempt-count < 3 (D-04)                                     │
│   • assemble brief  ◄── SELECT decompositions/research_questions (nestor)│
│   • flip status decomposed → in_research  (discrete allow-listed verb)   │
│   • INSERT research_runs (status='queued', attempt=n, space_id, intake) │
│   • BackgroundTasks.add_task(run_poll_driver, identity, ...)            │
│   • return 202 {research_run_id}                                         │
│                                                                          │
│ run_poll_driver  (READ→release→CALL→WRITE, run_with_session_release):    │
│   READ  : load space_id + acting email (plain dict)                      │
│   CALL  :  tribunal_client.ensure_org(space_id)                          │
│           tribunal_client.ensure_project(space_id) → project_id          │
│           tribunal_client.create_run(project_id, brief, idem_key) ──HTTP─┼──►┌ TRIBUNAL API (internal, OIDC) ┐
│           loop every ~3s:                                                │   │ POST /api/runs → run row      │
│              m = get_metrics(tribunal_run_id) ──────────────────────HTTP─┼──►│   status='queued'             │
│              UPDATE research_runs SET status,current_stage,stage_detail, │   └───────────────┬───────────────┘
│                     cost_usd_total, tribunal_run_id  (each tick)  ◄──────┼──── (fresh scoped tx per write)  │
│              if m.status in {completed,failed,cancelled}: break          │           ▼
│   WRITE : (on completed) get_report → persist output; send mail (D-10)   │   TRIBUNAL WORKER (always-on min=1)
│           (on failed)    error_message → research_runs; send fail mail   │   claim_one() SKIP LOCKED
│           status stays in_research (Phase 18 flips to delivered)         │   TribunalPipeline.run(): 9 stages
└───────────────┬──────────────────────────────────────────────────────────┘   set_stage() → run.current_stage
                │                                                                / stage_detail (JSONB merge)
   Meanwhile the browser:                                                       cost → audit_log → cost_usd_total
   GET /intakes/{id}/research/stream  (async SSE, the ONE async def)
      └─ per tick: run_in_threadpool(read_latest_research_run_dict)
         → reads research_runs → SSE frame {status,current_stage,stage_detail,cost}
         → frontend renders stages[] DYNAMICALLY (no hardcoded 9); : ping every 15s
         → terminal event → collapse to summary card (D-09)

  Client-facing UI: UNCHANGED during in_research (D-08 — no research surface)
```

### Recommended Project Structure
```
backend/app/
├── research/
│   ├── tribunal_client.py     # EXTEND: add create_run(), get_run(), get_metrics(), get_report()
│   └── run_task.py            # NEW: run_poll_driver (BackgroundTask; poll → mirror → mail)
├── api/
│   └── research_routes.py     # NEW: POST /intakes/{id}/research (trigger) + GET .../research/stream (SSE)
├── db/
│   ├── models/
│   │   └── research_runs.py   # NEW: the intake-side mirror table
│   ├── stream_session.py      # EXTEND: read_latest_research_run_dict() (mirror of read_latest_run_dict)
│   └── alembic/versions/
│       └── 0011_research_runs.py  # NEW: create research_runs + RLS policy + space-leading indexes
├── mail/
│   ├── render.py              # EXTEND: render_research_complete(), render_research_failed()
│   └── templates/nl|fr|en/
│       ├── research_complete.html.j2   # NEW
│       └── research_failed.html.j2      # NEW
frontend/src/
├── lib/
│   ├── api/research.ts        # NEW: triggerResearch(), openResearchStream() (clone skillRunStream.ts)
│   └── intake-phase.ts        # EXTEND: derivePhase feeds in_research off research_runs, not artifacts
└── components/intake/
    └── ResearchRunProgress.tsx  # NEW: dynamic stage list + cost + elapsed; summary card end state
```

### Pattern 1: Pause-gate neutralization by brief composition (SEAM-04, D-01/D-01b)
**What:** Both interactive pauses are opt-in behaviors keyed off the `brief` string; the seam never opts in, so neither fires. No engine edit.
**When to use:** The trigger's brief-assembly step.
**Mechanism (verified in source):**
- `needs_report_spec` fires ONLY when the brief contains `[INTERACTIVE_REPORT]` (`pipeline.py:158` strips it; `pipeline.py:781` gates on the resulting flag; `:795` is the zero-touch default that writes the report directly). **Seam runs omit the marker → gate unreachable.**
- `needs_input` fires ONLY when the `intake` stage's LLM judges the brief *vague* AND `allow_clarification` is on (`pipeline.py:191-197`, `intake.py:329-355`). A brief assembled from a validated, decomposed context pack (explicit enumerated questions) is not vague. Belt-and-suspenders: the pipeline force-proceeds after 2 `[CLARIFICATION ANSWERS]` rounds (`pipeline.py:189` `_CLAR_CAP=2`, `:199-215`), so even a borderline brief cannot park indefinitely.
```python
# Brief assembly — no marker, well-formed questions => neither gate fires.
def assemble_brief(intake, decomposition, questions) -> str:
    # Prose brief the engine's adaptive_intake will (non-vaguely) re-decompose.
    lines = [decomposition.summary or f"Deep research for {intake.project_title}."]
    lines.append("\nOnderzoeksvragen:")            # explicit enumerated questions => not vague
    for i, q in enumerate(sorted(questions, key=lambda x: x.priority), 1):
        lines.append(f"{i}. {q.question_text}")
    # D-01b: derive a light report-spec HINT as prose (NOT the [INTERACTIVE_REPORT] gate).
    # Fallback structure when intake fields are thin — see Pattern 2.
    return "\n".join(lines)      # NB: never append "[INTERACTIVE_REPORT]"
```
**Hard constraint honored:** the `canonical_json` audit payload (`audit/hash_chain.py`, frozen `_payload_for_row` incl. `tenant_id`/`run_id`) and the stage-trace structure are untouched — the seam only chooses a `brief` value; `verify_chain` stays green. This was already proven in the Phase-14 D-07 live run (chain=OK) using exactly this HTTP path.

### Pattern 2: Report-spec derivation (D-01b) — prose hint + fixed fallback
**What Tribunal's report spec controls (verified `runs/schemas.py:108-118`, `report_planner.py`):** `included_focus_areas` (subset of the brief's focus areas), `length` (`brief|standard|comprehensive`), `tables` (`none|key|heavy`), `instructions` (free-text shaping). It only takes effect through the `[INTERACTIVE_REPORT]` pause OR the `/report-spec` resume — **neither of which the seam uses**. So for a zero-touch seam run the "report spec" is not a Tribunal API object; it is realized as **prose shaping notes inside the brief** (the engine's synthesis honors brief instructions). Map intake answers → prose hint:
| Intake signal | Report-spec prose hint |
|---------------|------------------------|
| sector / industry field | "Structureer het rapport per marktsegment / sector." |
| stated goals / objectives | "Behandel expliciet: {goals} als aparte secties." |
| number of decomposed questions | length: many questions → "uitgebreid"; few → "standaard" |
| thin / missing fields (fallback) | fixed default: "Standaard lengte, kerntabellen, alle onderzoeksvragen behandeld." |
**Recommendation:** keep this a pure brief-composition helper (`derive_report_hint(intake) -> str`) with the fixed fallback string. Do NOT call `/report-spec` (that endpoint is for the interactive resume the seam bypasses).

### Pattern 3: Poll → mirror → SSE bridge (RUN-01) — clone the two existing transports
**What:** The intake backend is the poll→SSE adapter. Tribunal keeps its poll model; intake keeps its SSE. Neither transport changes.
**Mechanism:** The background poll driver `UPDATE`s a `research_runs` row every ~3s from `get_metrics`; the SSE handler (clone of `stream_skill_runs`) reads that row per tick and pushes frames — exactly the `read_latest_run_dict` shape but for research.
```python
# stream_session.py — mirror of read_latest_run_dict (verbatim discipline: plain dict, verbatim status)
def read_latest_research_run_dict(identity, intake_id) -> dict | None:
    with tenant_session(identity) as session:          # re-issues app.current_space_id every entry
        run = ResearchRunRepository(session, identity).latest_for_intake(intake_id)
        if run is None:
            return None
        return {
            "id": str(run.id),
            "status": run.status,                       # verbatim — Tribunal terminal set (see AP-6)
            "current_stage": run.current_stage,
            "stage_detail": run.stage_detail,           # JSONB {stage_key: {items:[{name,status}]}}
            "cost_usd_total": str(run.cost_usd_total) if run.cost_usd_total is not None else None,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
        }
```
**SSE terminal set differs from skill-runs (AP-6, verified):** `stream_skill_runs` uses `TERMINAL = {"succeeded","failed"}` (`intake_routes.py:1068`). The research stream's terminal set is Tribunal's: `{"completed","failed","cancelled"}`. Define a NEW `RESEARCH_TERMINAL` constant in the cloned handler; do NOT reuse the skill-run one. The frontend reader (`research.ts`, cloned from `skillRunStream.ts`) must likewise define its own terminal check — the skill-run `TERMINAL` in `skillRunStream.ts:28` is `{succeeded,failed}`.

### Pattern 4: Trigger as a discrete allow-listed verb (SEAM-03, D-06)
**What:** Follow the established `/submit` `/review` pattern (`intake_routes.py:1184-1199`) — a discrete verb with a transition map, NOT a generic `PATCH status`. This keeps the scope-ceiling enforcement structural and gives a natural audit call-site.
```python
_RESEARCH_TRANSITIONS = {"decomposed": "in_research"}   # ONLY reachable target
# 409 if current status not in the map => cannot trigger twice (D-06) or on a wrong status.
```

### Anti-Patterns to Avoid
- **Editing the Tribunal pipeline/worker to "skip" the gates.** Unnecessary and audit-risky (Pitfall 7). The gates are brief-controlled; compose the brief instead. (AP-5 in ARCHITECTURE.md is superseded by D-01/D-01b: the answer is "never opt in," not "auto-answer.")
- **Letting the browser call Tribunal poll endpoints directly** (AP-1). Bridge through the intake SSE; Tribunal API is internal-only (`--no-allow-unauthenticated`, invoker = `nestor-run` SA).
- **Writing Tribunal's `run` table from the intake backend** (AP-2). HTTP `POST /api/runs` only — two GUCs/schemas must never share a transaction.
- **Reusing the skill-run SSE terminal set** (`{succeeded,failed}`) for research (AP-6). Research terminal set is `{completed,failed,cancelled}`.
- **Auto-advancing intake status to `delivered` on run `completed`.** Status stays `in_research`; the Phase-18 PDF upload flips it (Pitfall 10, STATE decision D-report). Run-completed ≠ delivered.
- **Hardcoding the 9-stage list in the frontend.** Render from `metrics.stages[]` (Phase 15 contract — a 10th pass must cost nothing).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Long-job "kick, poll, write-back" with pool safety | A bespoke async task + manual session juggling | `run_with_session_release(read_fn, call_fn, write_fn, on_error=...)` (`ai_session.py:99`) | Already enforces READ→release→CALL→WRITE, re-issues the GUC on the 2nd session (T-7-02), and finalizes the row to `failed` on any exception (the `on_error` hook — exactly the D-04/D-11 failure path) |
| DB-backed live progress push | A WebSocket bridge or a new stream protocol | Clone `stream_skill_runs` (`intake_routes.py:1082`) + `read_latest_run_dict` (`stream_session.py:55`) | Stateless per-tick scoped SELECT, 15s `: ping` heartbeat (keeps Cloud Run from reaping an idle hour-long stream), disconnect check, 403/404 pre-flight — all solved |
| OIDC minting + acting-user headers to Tribunal | New token/header code | Extend `tribunal_client.py` (`_mint_id_token`, `_headers`) | Keyless ADC minting, correct audience rule (no path suffix — Pitfall 4), and the exact `X-Nestor-Tenant-Id`/`X-Acting-User-*` constants the Tribunal `InternalCallerProvider` reads (`auth/internal_caller.py:78`) |
| Space→org→project provisioning | A mapping table or manual org creation | `ensure_org()` + `ensure_project()` (already in `tribunal_client.py`) | Identity mapping (`space_id` IS `org.id`); idempotent get-or-create; returns `project_id` |
| Idempotent run creation / no double-charge | A "is a run already running?" lock table | `POST /api/runs` `(tenant_id, idempotency_key)` UNIQUE (`run.py:113`) + status-machine gate (D-06) | A retried POST returns the existing run; the intake status flip already prevents a 2nd trigger |
| NL/FR/EN mail with autoescape | Manual string templating | `mail/render.py` `_localized_template` + `resend.send` | Autoescape ON (XSS guard T-10-01), nl fallback chain, the single monkeypatchable `send()` seam for tests |
| Cost rollup | Summing `audit_log` in intake | Tribunal's `run.cost_usd_total` (worker rolls it up on terminal, `worker.py:196`) exposed via `/metrics` | Cost is computed engine-side; the mirror just copies the number |

**Key insight:** This phase has essentially zero net-new mechanism. Every hard problem (timeout-immune execution, pool-safe long jobs, live progress, tenant-scoped streaming, keyless auth, idempotency) was already solved and proven live. The risk is in the *seams between* the pieces — status-enum mismatch (AP-6), the report-spec schema gap (Open Question 1), and the isolation of the new `research_runs` surface (Pitfall 9) — not in any single new component.

## Runtime State Inventory

> This is a feature-add phase (new table + new endpoints), not a rename/refactor. The rename-specific categories mostly do not apply, but the **new-surface isolation** and **new-secret/env** dimensions matter and are enumerated below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New intake table `research_runs` (mirror of Tribunal run state); optionally raw output persisted (GCS blob or `research_runs.output_markdown`) | Migration 0011 (create + RLS + space-leading indexes); no data migration (empty start) |
| Live service config | `TRIBUNAL_SERVICE_URL` non-secret env already modeled in `Settings.tribunal_service_url` (config.py:104) but must be SET on the intake Cloud Run service; `NESTOR_WORKER_STALE_MINUTES` is a Tribunal-worker env (default 60, `worker.py:47`) | Runbook step: set `TRIBUNAL_SERVICE_URL` on `nestor-api`; confirm/adjust worker `NESTOR_WORKER_STALE_MINUTES` |
| OS-registered state | None — no Task Scheduler / pm2 / systemd registrations | None |
| Secrets/env vars | NO new secret. OIDC is keyless (ADC). Mail uses existing `RESEND_API_KEY`. The only new plain env is `TRIBUNAL_SERVICE_URL` (non-secret, already typed in Settings) | Set `TRIBUNAL_SERVICE_URL` on the live service (runbook); mail needs existing `RESEND_API_KEY` + `APP_BASE_URL`/`NESTOR_ADMIN_EMAIL` already seeded in Phase 10/12 |
| Build artifacts / installed packages | None — no new package; the intake image rebuild is needed because new backend modules (`research_routes`, `run_task`, `research_runs` model, mail templates) must ship in the image (config-only env flip on a stale image = the recurring deploy-gap, DEPLOY-RUNBOOK:519) | Rebuild the `nestor-api` image via Cloud Build; run migration Job for 0011 |

**Nothing found in category:** OS-registered state — None (verified: no scheduler/daemon registrations in this project; the Tribunal worker is a Cloud Run service, already deployed and unchanged by this phase).

## Common Pitfalls

### Pitfall 1: The `needs_report_spec` Pydantic-Literal gap can 500 a poll (defense-in-depth)
**What goes wrong:** `RunResponse.status` (`schemas.py:63`) and `RunMetrics.status` (`schemas.py:137`) are `Literal["queued","running","completed","failed","cancelled","needs_input"]` — **they do NOT include `needs_report_spec`**. The DB CHECK constraint and the worker DO allow/write `needs_report_spec` (`run.py:107-111`, `worker.py:170`). If a run ever reached `needs_report_spec`, `GET /api/runs/{id}` and `/metrics` would raise a response-validation 500 — the poll driver would see a 5xx instead of a status.
**Why it happens:** migration 0007 added `needs_report_spec` to the CHECK but the response schemas' Literals were never widened (FEATURES.md flagged the CHECK gap; the real live gap is in the *response* Literal). Note: FEATURES.md said the CHECK might be a "latent bug" — **that is resolved**; `run.py:107-111` confirms the CHECK carries `needs_report_spec`. The residual gap is the response schema.
**How to avoid:** D-01b guarantees seam runs never reach `needs_report_spec` (no `[INTERACTIVE_REPORT]` marker). So this cannot fire for seam runs. But the poll driver should treat any 5xx from `/metrics` as a transient/failed condition (retry a bounded number of times, then finalize `research_runs` as `failed` with a clear message) rather than crashing the BackgroundTask.
**Warning signs:** a 500 from `/metrics` with `needs_report_spec` in logs → a run opted into interactive shaping (it shouldn't have; audit the brief assembly for a stray marker).

### Pitfall 2: Stale-run double-dispatch on an ultra-long run (WR-01 residual, ENGINE-03)
**What goes wrong:** the worker's SKIP-LOCKED claim reclaims a row that is `status='running' AND started_at < NOW() - make_interval(mins => STALE)` (`worker.py:76`). If a legitimate run exceeds `STALE_RUN_MINUTES`, a second worker poll reclaims and **re-runs it from scratch** → double spend + duplicate audit rows. There is no partial-progress resumption.
**Measured reality:** Phase 13 recorded max **17 min** (1020s pipeline, ~$1.5–2.1); Phase 14 D-07 ran **~19 min** at $1.60. Current `STALE_RUN_MINUTES = 60` (`worker.py:47`) is already ~3× the observed max.
**How to avoid (ENGINE-03 half in scope):** keep `NESTOR_WORKER_STALE_MINUTES = 60` (comfortably above measured max) OR bump to 90–120 for extra headroom against a slow provider day; the operator's guidance is "above the real max — no double-runs." Since the audit chain is single-worker-*seq*-safe via the per-run advisory lock added in Phase 13 (ENGINE-08, `runs/execute.py` `execute_run_locked`), a re-dispatch would also contend on that lock — but the clean fix is the stale window, not relying on the lock. **Recommendation: set `NESTOR_WORKER_STALE_MINUTES=90` (measured max 19 min → generous headroom, still catches genuinely-crashed runs promptly).** Record the chosen value in the runbook.
**Warning signs:** two `worker_id`s on one run; `uq_audit_tenant_run_seq` collisions; a run's cost roughly doubling.

### Pitfall 3: Reusing the skill-run SSE terminal set for research (AP-6)
**What goes wrong:** the skill-run stream closes on `{"succeeded","failed"}`; a Tribunal run never emits `succeeded` (it emits `completed`). Reusing that set → the research stream never closes on success → the browser hangs until the 10-min cap and the summary card (D-09) never renders.
**How to avoid:** define `RESEARCH_TERMINAL = {"completed","failed","cancelled"}` in both the backend handler and the frontend reader. Carry `status` verbatim (the `stream_session` "Pitfall 1 verbatim" discipline).
**Warning signs:** progress panel spins past a `completed` run; SSE closes only at the 10-min cap.

### Pitfall 4: Holding a DB connection across the ~19-min run (pool starvation, Pitfall 4 in PITFALLS.md)
**What goes wrong:** if the poll driver reads the intake, then holds that session while polling Tribunal for 19 min, it starves the bounded pool (`size=2, overflow=3`). Two concurrent runs → `QueuePool limit … timed out`.
**How to avoid:** route the driver through `run_with_session_release` — the CALL phase (drive-to-completion) holds NO connection; each `research_runs` UPDATE is its own short scoped tx. `set_stage` on the Tribunal side already does exactly this (own session per write, `stages.py:99`).
**Warning signs:** `checkedout()` > 0 during the poll; pool-timeout errors under 2 concurrent triggers.

### Pitfall 5: The new `research_runs` surface leaks cross-tenant (Pitfall 9 in PITFALLS.md)
**What goes wrong:** every new read/write is a fresh chance to reintroduce the broken-RLS bug. The trigger, the SSE stream, and the mirror write must all be space-scoped; the SSE pre-flight must be an existence-hidden 404 for a cross-tenant intake.
**How to avoid:** `research_runs` gets `space_id` FK + RLS policy in 0011 (mirror `skill_runs`/`findings`); all reads/writes go through `tenant_session`; the SSE handler clones the `check_intake_in_scope` pre-flight (403 for null-space, 404 for cross-tenant). Add cross-tenant denial tests for the trigger + the stream from day one (two-suite pattern; STATE v1.1 blocker).
**Warning signs:** a denial test where space B's superadmin sees space A's research run; a `research_runs` row whose `space_id` ≠ its intake's `space_id`.

### Pitfall 6: `derivePhase` currently keys `in_research` off `hasResearchArtifacts`, not the run
**What goes wrong:** the existing phase machine (`intake-phase.ts:61-69`) derives `in_research` / `awaiting_report_upload` from `hasResearchArtifacts` (a legacy Supabase concept). Phase 16 has no `research_artifacts` writer (Tribunal writes to its own schema over HTTP). If the trigger flips status to `in_research` but `hasResearchArtifacts` stays false, `derivePhase` returns `in_research` (correct) — but the progress panel needs the `research_runs` row, not artifacts.
**How to avoid:** extend `derivePhase`'s inputs to include the latest `research_runs` state (or gate the progress panel on the run directly and leave `derivePhase` to drive status-level visibility). Keep the change additive — the intake enum already has `in_research`; wire the panel to `research_runs`, and do NOT let a completed run auto-advance to `awaiting_report_upload` (that's Phase 18's PDF upload).
**Warning signs:** progress panel shows nothing while status is `in_research`; or the report-upload block appears before Phase 18 exists.

## Code Examples

### Extending the seam client (trigger + poll + report) — `tribunal_client.py`
```python
# Source: existing tribunal_client.py shape (ensure_org/ensure_project); httpx blocking, sync-def compatible.
import uuid, httpx

def create_run(*, service_url, space_id, acting_user_id, acting_email,
               project_id: str, brief: str, idempotency_key: str) -> dict:
    """POST /api/runs → queue a Tribunal run. engine is ALWAYS 'tribunal' (Pitfall 15: pin the engine)."""
    resp = httpx.post(
        f"{service_url}/api/runs",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        json={"project_id": project_id, "brief": brief, "engine": "tribunal",
              "idempotency_key": idempotency_key, "uploaded_documents": []},  # never [INTERACTIVE_REPORT]
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()          # RunResponse: {id, status, ...}

def get_metrics(*, service_url, space_id, acting_user_id, acting_email, run_id: str) -> dict:
    """GET /api/runs/{id}/metrics → {status, cost_usd_total, elapsed_seconds, stages[], current_stage, stage_detail}."""
    resp = httpx.get(
        f"{service_url}/api/runs/{run_id}/metrics",
        headers=_headers(service_url, space_id, acting_user_id, acting_email),
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()
    return resp.json()
```
> NOTE the audience rule (Pitfall 4, already in `_mint_id_token`): the OIDC audience is `service_url` WITHOUT the `/api/...` path; the path is added only to the request URL.

### The poll driver via the release contract — `run_task.py`
```python
# Source: run_with_session_release contract (ai_session.py:99) + set_stage per-write discipline.
def run_poll_driver(identity, intake_id, research_run_id, brief):
    def read_fn(session):
        # plain dict — space_id, acting email/uid, tribunal service url
        return load_trigger_context(session, identity, intake_id)   # NEVER return ORM rows
    def call_fn(ctx):
        ensure_org(service_url=ctx["url"], space_id=ctx["space_id"], ...)
        project_id = ensure_project(service_url=ctx["url"], space_id=ctx["space_id"], ...)
        idem = str(uuid.uuid5(uuid.UUID(str(intake_id)), f"attempt-{ctx['attempt']}"))  # D-04 deterministic
        run = create_run(project_id=project_id, brief=brief, idempotency_key=idem, ...)
        rid = run["id"]
        while True:                                   # NO db connection held here (T-7-06)
            m = get_metrics(run_id=rid, ...)
            mirror_tick(identity, research_run_id, rid, m)   # own short scoped tx per tick
            if m["status"] in {"completed", "failed", "cancelled"}:
                return rid, m
            time.sleep(POLL_SECONDS)                  # ~3s
    def write_fn(session, ctx, result):
        rid, m = result
        if m["status"] == "completed":
            report = get_report(run_id=rid, ...)      # persist raw output (Phase 17 surfaces download)
            finalize_completed(session, research_run_id, m, report)
            send_research_complete_mail(to=[ctx["acting_email"]], ...)   # D-10/D-11
        else:
            finalize_failed(session, research_run_id, m)
            send_research_failed_mail(to=[ctx["acting_email"]], ...)
    run_with_session_release(identity, read_fn, call_fn, write_fn, on_error=on_poll_error)
```

### Completion mail render — `mail/render.py` (extend)
```python
# Source: existing render_* + _localized_template pattern (render.py). NL fallback, autoescape ON.
def render_research_complete(*, project_title, duration_min, cost_usd, cta_url,
                             app_base_url=None, locale="nl") -> str:
    return _localized_template("research_complete", locale).render(
        project_title=project_title, duration_min=duration_min,
        cost_usd=cost_usd, cta_url=cta_url, app_base_url=app_base_url,
    )
# cta_url = f"{app_base_url}/admin/pulse/intakes/{intake_id}"  (admin route, no token — NOTIF-01)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| ARCHITECTURE.md AP-5: "auto-answer or surface" the pauses | D-01/D-01b: never opt into either gate (brief-controlled) | 16-CONTEXT 2026-07-21 | No auto-answer code, no pipeline edit — simpler + audit-safe |
| FEATURES.md: `needs_report_spec` CHECK may be a "latent bug" | RESOLVED — `run.py:107-111` CHECK carries `needs_report_spec` (migration 0007 drop+recreate) | Verified this session | The residual gap is the *response Literal*, not the CHECK (Pitfall 1) |
| Hardcoded 9-stage progress list | Dynamic render from `metrics.stages[]` | Phase 15 dynamic-stage contract | A future 10th pass (Phase 15) costs the UI nothing |
| Legacy `run-research` (SerpAPI/SearchAPI/Apify) | Tribunal only (`engine="tribunal"`) | v1.1 scope | Never invoke legacy research from new creds (INTAKE-05) |

**Deprecated/outdated:**
- Tribunal's `adk`/`sdk` A/B engine arms and the `/compare` critique endpoints: dev/eval concerns — the seam pins `engine="tribunal"` (Pitfall 15). Do not route seam runs to `adk` (uncited, non-audited).
- Tribunal's standalone `Run.jsx`/`Report.jsx` UI: retired; the intake progress panel replaces it in the intake design language.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | A brief assembled from a validated/decomposed context pack is reliably judged "not vague" by the `intake` stage, so `needs_input` never fires | Pattern 1 (SEAM-04) | LOW — even if the LLM asked, the 2-round force-proceed cap (`pipeline.py:189`) makes the gate self-clearing; worst case is one wasted intake call, not a parked run. Verify in the first live seam run |
| A2 | `NESTOR_WORKER_STALE_MINUTES=90` is safe headroom above the real max run | Pitfall 2 (ENGINE-03) | LOW — measured max is 17–19 min; 90 is generous. If a future run legitimately exceeds 90 min (e.g. a much broader brief), re-tune. Operator should confirm the value |
| A3 | Deterministic `uuid5(intake_id, attempt-n)` is the right idempotency-key strategy for the 3-attempt cap | Stack alternatives / run_task | LOW — builder discretion per D-04; the alternative (uuid4 + a DB attempt counter) also works. Either satisfies "no double-charge on retry" |
| A4 | Persisting raw output in this phase (vs deferring entirely to Phase 17) is acceptable | run_task write_fn | LOW — ARCHITECTURE.md recommends storing `output_markdown` + optional GCS now; Phase 17 only adds the *download surface*. Plan may defer the persist if it prefers; get_report is idempotent |
| A5 | Setting `TRIBUNAL_SERVICE_URL` on `nestor-api` is the only new live-config step | Runtime State Inventory | LOW — verified `Settings.tribunal_service_url` exists (config.py:104) but is `None` by default; the seam client is parameterized on it. Operator sets it in the runbook |

**If this table is empty:** it is not — but every assumption is LOW risk and self-correcting on the first live run (which also closes the deferred Phase-14 seam HTTP UAT).

## Open Questions (RESOLVED)

1. **Does the report-spec ever need the real Tribunal `/report-spec` endpoint, or is prose-in-brief sufficient?**
   - What we know: `/report-spec` only applies via the `[INTERACTIVE_REPORT]` resume path the seam bypasses; zero-touch synthesis honors brief instructions (`pipeline.py:795`).
   - What's unclear: whether operators will later want structured reshaping (length/tables) without re-running research — that's Tribunal's `/rewrite` capability, which is a Phase-17+ nicety.
   - Recommendation: for Phase 16, prose-in-brief only (Pattern 2). Do not wire `/report-spec` or `/rewrite`.

2. **Store raw output in `research_runs.output_markdown` vs a GCS blob vs defer to Phase 17?**
   - What we know: ARCHITECTURE.md D.1 suggests `research_runs.output_markdown` + optional GCS; Phase 17 owns the *download surface* (RUN-03).
   - What's unclear: size of a typical report (markdown) — likely fine in a TEXT column, but a large report might argue for GCS.
   - Recommendation: persist `output_markdown` in `research_runs` on completion (cheap, keeps Phase 17 a pure UI add); use the existing `storage/gcs.py` only if reports prove large. Builder discretion (A4).

3. **`derivePhase` refactor scope — feed it `research_runs` or gate the panel independently?**
   - What we know: `derivePhase` currently uses `hasResearchArtifacts` for `in_research`/`awaiting_report_upload` (`intake-phase.ts:61-69`), which has no writer in this flow.
   - Recommendation: minimal change — keep status-level visibility in `derivePhase`, gate the progress panel + summary card on the `research_runs` row directly; do NOT let a completed run flip to `awaiting_report_upload` (Phase 18 owns that). See Pitfall 6.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Tribunal API (`tribunal-api`) internal Cloud Run | Trigger + poll | ✓ live | tag `20260720-233938` (Phase 14) | — |
| Tribunal worker (always-on min=1) | ENGINE-07 execution | ✓ live | rev `-185906` (Phase 13 fix2) | — |
| OIDC keyless minting (ADC on `nestor-run` SA) | Seam auth | ✓ live | proven Phase 14 D-07 | — |
| `RESEND_API_KEY` + `APP_BASE_URL` + `NESTOR_ADMIN_EMAIL` | RUN-02 mail | ✓ seeded Phase 10/12 | — | rotate key post-UAT (STATE chore) |
| `TRIBUNAL_SERVICE_URL` env on `nestor-api` | Seam call-site | ✗ not yet set | — | Runbook step (non-secret env update) |
| Anthropic/OpenAI/Gemini provider keys (`Nestor_*`) | Engine run + D-05 fallback | ✓ live | Phase 13/14 | ≥2-of-3 degradation |
| Local Python/Docker | Running the two-suite tests / building images | ✗ (dev box) | — | Cloud Build (tests + images); author-by-construction; operator runbook for live |
| Anthropic credits | The live seam run | ⚠ LOW (MEMORY: top up before live runs) | — | Top up before the UAT run |

**Missing dependencies with no fallback:** none that block *authoring*. `TRIBUNAL_SERVICE_URL` must be set before the live run (runbook step, not a code blocker).

**Missing dependencies with fallback:** local Python/Docker → Cloud Build + operator runbook (established pattern, all prior phases). Anthropic credits → top up (operator).

## Validation Architecture

> nyquist_validation is enabled (`config.json workflow.nyquist_validation: true`). This section is included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (intake backend suite, sync pg8000 harness); Tribunal has its own asyncpg suite (two-suite pattern, 14-CONTEXT D-08) |
| Config file | `backend/` pytest config (existing 150-test suite); `tribunal/cloudbuild.test-critical.yaml` for the Tribunal-side critical gate |
| Quick run command | Targeted: `pytest backend/tests/test_research_routes.py -x` (runs in Cloud Build; dev box has no Python) |
| Full suite command | Cloud Build: intake full suite (see MEMORY `phase-07-deployed-suite-green` for the Cloud Build suite runbook) + `tribunal/cloudbuild.test-critical.yaml` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SEAM-03 | Trigger flips `decomposed`→`in_research`, assembles brief, calls seam | unit + integration (fake seam) | `pytest backend/tests/test_research_routes.py::test_trigger_decomposed_ok -x` | ❌ Wave 0 |
| SEAM-03 | Trigger on non-`decomposed` status → 409 | unit | `...::test_trigger_wrong_status_409 -x` | ❌ Wave 0 |
| SEAM-03 (isolation) | Cross-tenant intake trigger → existence-hidden 404 | denial | `...::test_trigger_cross_tenant_404 -x` | ❌ Wave 0 |
| SEAM-04 | Assembled brief contains NO `[INTERACTIVE_REPORT]` marker + enumerated questions | unit | `...::test_brief_never_opts_into_gates -x` | ❌ Wave 0 |
| RUN-01 | SSE stream emits research-run frames; closes on `{completed,failed,cancelled}` | integration | `...::test_research_stream_terminal_set -x` | ❌ Wave 0 |
| RUN-01 (isolation) | Cross-tenant SSE pre-flight → 404; null-space → 403 | denial | `...::test_research_stream_denial -x` | ❌ Wave 0 |
| RUN-02 | On terminal, mail sent to acting superadmin (fake_resend asserts recipient) | unit | `...::test_completion_mail_to_trigger_user -x` | ❌ Wave 0 |
| D-04 | 4th trigger attempt → "needs investigation" (no seam call) | unit | `...::test_attempt_cap_3 -x` | ❌ Wave 0 |
| ENGINE-07/RUN-01 | Poll driver holds no DB connection across the CALL phase (pool safety) | integration | `...::test_poll_driver_releases_pool -x` | ❌ Wave 0 |
| ENGINE-03 | `research_runs` migration 0011 creates table + RLS policy | migration test | existing migration-apply harness | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** targeted `pytest backend/tests/test_research_routes.py -x` (Cloud Build; author-by-construction locally).
- **Per wave merge:** intake full suite + `tribunal/cloudbuild.test-critical.yaml` (the two-suite gate).
- **Phase gate:** full suite green in Cloud Build before `/gsd:verify-work`; the FIRST live seam trigger closes the deferred Phase-14 HTTP UAT (record in `14-HUMAN-UAT.md`).

### Wave 0 Gaps
- [ ] `backend/tests/test_research_routes.py` — trigger + SSE + denial + attempt-cap tests (fake seam client + fake_resend)
- [ ] `backend/tests/test_research_run_task.py` — poll driver pool-safety + terminal mail + on_error finalize-as-failed
- [ ] `backend/tests/conftest.py` (extend) — a `fake_tribunal_client` fixture (mirror `fake_anthropic`/`fake_gcs`/`fake_resend`) so no test hits the real internal API
- [ ] Migration-apply test for 0011 (`research_runs` + RLS policy) in the existing migration harness
- [ ] Two-suite: extend the cross-tenant denial suite (intake pg8000 side) with `research_runs` cases

## Security Domain

> `security_enforcement` is not explicitly `false` in config → enabled. Section included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Superadmin Bearer (Identity Platform) on the trigger + SSE routes; server-to-server OIDC (keyless ADC) to Tribunal — already proven Phase 14 |
| V3 Session Management | yes | SSE Bearer attached by the frontend reader (clone `skillRunStream.ts` token handling); no server session state (stateless per-tick reads) |
| V4 Access Control | yes | Superadmin-only trigger; space-scoped RLS on `research_runs`; existence-hidden 404 for cross-tenant intake (D-04 pattern). Client sees NO research surface (D-08 / REPORT-02) |
| V5 Input Validation | yes | Brief assembled server-side from stored decomposed questions (not user free-text at trigger time); `intake_id` path validated in scope; Pydantic on any body |
| V6 Cryptography | no (no new crypto) | OIDC token minting is delegated to `google-auth` (never hand-rolled); audit hash-chain is engine-side and untouched |

### Known Threat Patterns for {intake FastAPI ↔ internal Tribunal seam}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Cross-tenant research-run read (SSE or trigger) | Information Disclosure | `space_id` RLS + `tenant_session` + existence-hidden 404 pre-flight; day-one denial tests (Pitfall 5) |
| Client reaching research progress before delivery | Information Disclosure | D-08: no client-facing research surface; enforced by not adding any client route (REPORT-02) |
| Runaway/malicious uncapped run cost | Denial of Service (cost) | ACCEPTED for now (D-02 uncapped deferral); mitigated by the trigger being superadmin-only + brief assembled from stored questions (no arbitrary brief injection) + stale-window preventing double-dispatch. Cap flip-on is Phase 20 |
| Browser calling the internal Tribunal API directly | Elevation / bypass | Tribunal is `--no-allow-unauthenticated`, invoker = `nestor-run` SA only (Phase 14 D-04); browser never gets the audience token (AP-1) |
| Stray `[INTERACTIVE_REPORT]`/vague brief parking a run | Tampering / DoS | Brief-composition guard (Pattern 1) + unit test that the assembled brief never contains the marker (SEAM-04 test) |
| Tenant spoof via forged `X-Nestor-Tenant-Id` | Spoofing | Tribunal reads `tenant_id` ONLY from the verified internal caller's header behind OIDC verification (`internal_caller.py`, T-14-03); the intake backend is the trusted setter (space_id from the verified Identity, never from request input) |

## Sources

### Primary (HIGH confidence — read directly this session)
- Tribunal run lifecycle: `tribunal/nestor_pulse_sdk/runs/{worker.py, api.py, stages.py, schemas.py}` — claim/queue, poll endpoints, stage schema, pause-gate writes, the response-Literal gap
- Tribunal pipeline pause gates: `tribunal/nestor_pulse_sdk/pipeline/tribunal/{pipeline.py, intake.py}` — `[INTERACTIVE_REPORT]` marker gate (`:158,781,795`), clarification force-proceed (`:189-215`), `allow_clarification` (`intake.py:329-355`)
- Tribunal run model + CHECK: `tribunal/nestor_pulse_sdk/db/models/run.py` (`:107-111` — `needs_report_spec` IS in the CHECK; FEATURES.md's "latent bug" is resolved)
- Tribunal seam auth: `tribunal/nestor_pulse_sdk/auth/internal_caller.py` (`X-Nestor-Tenant-Id`/`X-Acting-User-*` constants), `orgs/api.py` (ensure endpoints)
- Intake seam client: `backend/app/research/tribunal_client.py` (OIDC minting, headers, ensure_org/ensure_project; SCOPE note says trigger/poll are Phase 16)
- Intake SSE + release contract: `backend/app/api/intake_routes.py:1052-1145` (`stream_skill_runs`, heartbeat, terminal set, pre-flight), `backend/app/db/stream_session.py` (`read_latest_run_dict`), `backend/app/db/ai_session.py:80-148` (`tenant_session`, `run_with_session_release`)
- Intake models: `backend/app/db/models/{research.py, skill_run.py, intake.py}` (decompositions/research_questions, status enum incl. `in_research`, context_pack/final_report fields)
- Mail stack: `backend/app/mail/{render.py, resend.py}` + `templates/{nl,fr,en}/`
- Frontend: `frontend/src/lib/intake-phase.ts` (phase machine, `in_research`), `frontend/src/components/intake/SkillRunProgress.tsx` (progress + SSE-first hook pattern)
- Config: `backend/app/core/config.py:104` (`tribunal_service_url`), `.planning/config.json`
- Calibration: `.planning/phases/13-04-SUMMARY.md` (max 17 min / 1020s / $1.5–2.1; WR-01 residual → Phase 16 stale window), `.planning/phases/14-04-SUMMARY.md` (D-07 ~19 min, $1.60, chain=OK)
- Deploy: `infra/DEPLOY-RUNBOOK.md` (Phase 13/14 Tribunal sections, env/secret conventions, the "rebuild image not just env" gap `:519`)

### Secondary (HIGH — v1.1 research trio, cross-verified against source this session)
- `.planning/research/ARCHITECTURE.md` (Parts A/B/D — run lifecycle, seam, poll→SSE bridge, component inventory)
- `.planning/research/PITFALLS.md` (Pitfalls 4/5/6/9/10 — long runs, stale window, transport mismatch, new-surface isolation, dual state machines)
- `.planning/research/FEATURES.md` (brief-is-one-prose-string, 9-stage table, `needs_report_spec` CHECK gap — corrected here)

### Tertiary (context)
- MEMORY: `phase-14-executed-live-fix-cycle`, `phase-13-tribunal-rehomed-live`, `dev-machine-no-python-docker`, `skill-run-status-succeeded-contract`, `backend-test-harness-lessons`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; every dependency read live in the codebase.
- Architecture / pause-gate neutralization: HIGH — the brief-marker gate and force-proceed cap read directly from `pipeline.py`/`intake.py`; the "no engine edit" conclusion is source-proven.
- Pitfalls: HIGH — the schema-Literal gap, stale-window numbers, and terminal-set mismatch are all confirmed against source (not inferred).
- Calibration (stale window): HIGH — measured durations from two live runs (17 + 19 min) in the phase SUMMARYs.

**Research date:** 2026-07-21
**Valid until:** ~2026-08-20 (stable — internal codebase, no external fast-moving deps). Re-verify only if the Tribunal pipeline or `runs/schemas.py` change before execution (Phase 15 is deferred *after* Phase 19, so the engine shape is frozen for this phase).
