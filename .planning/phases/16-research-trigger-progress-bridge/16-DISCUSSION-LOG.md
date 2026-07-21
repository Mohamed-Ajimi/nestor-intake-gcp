# Phase 16: Research Trigger + Progress Bridge - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-21
**Phase:** 16-Research Trigger + Progress Bridge
**Areas discussed:** Interactive pauses policy, Trigger guardrails & cost cap, Progress experience in admin UI, Completion/failure emails

---

## Interactive pauses policy

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-proceed, zero-touch | Backend answers both gates with defaults | |
| Auto-proceed + visible trace | Zero-touch but auto-answers shown in UI | |
| Surface pauses to superadmin | Run pauses; admin UI form to answer | |
| (Free text) | Gates are obsolete for seam runs | ✓ |

**User's choice:** Free text — "this part of tribunal becomes obsolete… the last part of intake
already did the back and forth of enriching the questions and tribunal should start at the part
where an agent delegates the questions to different deep researches according to angles."
**Notes:** The validated intake IS the answered brief; `needs_input` must never fire for seam runs.

### Sub-question: needs_report_spec (how the raw report is structured)

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed standard spec | Same recipe every time | |
| Derived from intake answers | Per-client structure from intake fields | ✓ |
| You decide | Builder discretion | |

**User's choice:** "2" — derived from intake answers (after requesting a plain-language
re-explanation of the question).
**Notes:** Sane fixed fallback when intake fields are thin (builder discretion on mapping).

---

## Trigger guardrails & cost cap

### Per-run cost ceiling

| Option | Description | Selected |
|--------|-------------|----------|
| $25 per run | The wired ceiling, room for thorough runs | |
| $10 per run | Tighter budget | |
| $5 per run | Very tight safety net | |
| (Free text) | "uncapped for now" | ✓ |

**User's choice:** Uncapped for now — `NESTOR_TRIBUNAL_UNCAPPED` stays on; ENGINE-03 cap flip
recorded as explicit operator deferral (before client-billed runs, Phase 20 latest). Stale-run
window calibration stays in this phase.

### Trigger confirmation

| Option | Description | Selected |
|--------|-------------|----------|
| Confirm first | Dialog before starting | ✓ |
| Start immediately | One click, no dialog | |

**User's choice:** Confirm first (recommended).

### Failure handling

| Option | Description | Selected |
|--------|-------------|----------|
| Re-trigger fresh run | Button returns after failure | |
| Resume from where it stopped | Complex resume machinery | |
| Nothing in v1.1 | Failure is final | |
| (Free text) | "re trigger up to 3 times, also have fallback llms in case of outage" | ✓ |

**User's choice:** Re-trigger capped at 3 attempts, then "needs investigation" state. LLM fallback
noted as already existing in the engine (≥2-of-3 provider degradation) — verify, don't build.

---

## Progress experience in admin UI

### Running display

| Option | Description | Selected |
|--------|-------------|----------|
| Full progress panel | Stage list + running cost + elapsed | ✓ |
| Compact status line | One line summary | |
| You decide | Builder picks | |

**User's choice:** Full progress panel (recommended).

### Client-side visibility during in_research

| Option | Description | Selected |
|--------|-------------|----------|
| Generic "in progress" step | Stepper hint, no details | |
| No change at all | Research fully invisible until delivery | ✓ |

**User's choice:** No change at all.

### Completion end state

| Option | Description | Selected |
|--------|-------------|----------|
| Summary card | Timestamp, cost, duration; Phase-17 anchor | ✓ |
| Keep full stage list | Stays expanded | |
| You decide | Builder picks | |

**User's choice:** Summary card (recommended).

---

## Completion/failure emails

### Recipient

| Option | Description | Selected |
|--------|-------------|----------|
| Whoever started the run | Triggering superadmin's address | ✓ |
| Fixed admin address | Standing admin mailbox | |
| Both | Both of the above | |

**User's choice:** Whoever started the run (recommended).

### Content

| Option | Description | Selected |
|--------|-------------|----------|
| Short + link | Result + cost/duration + button to intake page | ✓ |
| Detailed digest | Stage recap + findings in the mail | |

**User's choice:** Short + link (recommended).

---

## Claude's Discretion

- Pipeline entry-point mechanics for skipping the clarification gate (D-01)
- Intake-fields → report-spec mapping + fallback structure (D-01b)
- `research_runs` table design, poll cadence, poll → SSE bridge mechanics
- Brief assembly from the validated context pack
- Stale-run window exact value (above Phase-13 measured max)
- Progress panel visual details; 3-attempt storage/enforcement

## Deferred Ideas

- Cost-cap flip-on + cap value (operator deferral — before client-billed runs / Phase 20)
- Run cancel/stop mid-flight
- Client-visible "in progress" stepper hint (revisit post-delivery)
- Detailed digest emails
