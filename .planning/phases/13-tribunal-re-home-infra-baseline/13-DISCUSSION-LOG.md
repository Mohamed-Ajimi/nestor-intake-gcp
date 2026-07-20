# Phase 13: Tribunal Re-home + Infra Baseline - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-20
**Phase:** 13-tribunal-re-home-infra-baseline
**Areas discussed:** Code home & repo strategy, Deploy posture & costs, Proof run & provider keys, Concurrency & audit gate

---

## Code home & repo strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Copy into this repo (Recommended) | nestor_pulse_sdk + imported bits into tribunal/ next to backend/; one repo drives everything | ✓ |
| Keep in Nestor repo | Deploy from Nestor repo; cross-repo work outside GSD's reach | |
| New dedicated repo | Clean third repo | |

**User's choice:** Copy into this repo
**Notes:** Old Nestor repo becomes a frozen reference.

| Option | Description | Selected |
|--------|-------------|----------|
| Leave untouched (v1.0 style) | Same philosophy as the Supabase decision | |
| Tear down after proof | Delete old Cloud Run services + Cloud SQL once E2E green; data is dev-round only | ✓ |
| Decide later | Park as deferred idea | |

**User's choice:** Tear down after proof
**Notes:** Deliberate departure from the v1.0 leave-legacy-alone pattern; cost-driven.

---

## Deploy posture & costs

| Option | Description | Selected |
|--------|-------------|----------|
| Same as v1.0 (Recommended) | Build-by-construction + operator-run live session (runbook, tools@dotto.be, Nestor Pulse project) | ✓ |
| Different — let me explain | Something changed about deploys | |

**User's choice:** Same as v1.0

| Option | Description | Selected |
|--------|-------------|----------|
| Accept always-on (Recommended) | min-instances=1, ~$5–10/mo idle, runs start in seconds | ✓ |
| Scale to zero | No idle cost but cold starts + polling rework | |

**User's choice:** Accept always-on
**Notes:** DB naming/sizing delegated to builder discretion.

---

## Proof run & provider keys

| Option | Description | Selected |
|--------|-------------|----------|
| Known benchmark brief (Recommended) | LUKOIL-family brief; compare against known results | ✓ |
| A real client intake brief | More realistic but conflates move issues with brief issues | |
| You decide | Builder picks | |

**User's choice:** Known benchmark brief

| Option | Description | Selected |
|--------|-------------|----------|
| All three, key available | Reuse old project's Gemini key; full 2-of-3 headroom | ✓ |
| All three, need new key | Flag new Gemini key as operator prerequisite | |
| Start with two (no Gemini) | Anthropic + OpenAI only; zero headroom | |

**User's choice:** All three, key available (reseed old Gemini key into intake project)

| Option | Description | Selected |
|--------|-------------|----------|
| $5 per run (Recommended) | Engine's designed default (ADR-006) | |
| Higher (~$10-15) | More headroom | |
| You decide | From old benchmark costs | |

**User's choice:** Other — "uncap for now" (keep NESTOR_TRIBUNAL_UNCAPPED=1 during Phase 13; enforcement is Phase 16 / ENGINE-03)

---

## Concurrency & audit gate

| Option | Description | Selected |
|--------|-------------|----------|
| 2–3 simultaneous (Recommended) | Small operator team reality | |
| 5+ simultaneous | Headroom for many clients; may need multiple workers + stronger locking validation | ✓ |
| You decide | Size from worker design limits | |

**User's choice:** 5+ simultaneous

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror old setting (Recommended) | Copy old deployment's audit retention (designed against EU AI Act) | ✓ |
| Longer — multi-year | 5–10 years for NDA/dispute safety | |
| You decide | Mirror + document | |

**User's choice:** Mirror old setting

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — target before Aug 2 | Phase 13 complete before 2026-08-02 | |
| Best effort | Aim for it, no hard commitment; low practical exposure pre-client-runs | ✓ |

**User's choice:** Best effort (verify_chain green stays mandatory for phase completion regardless of date)

## Claude's Discretion

- Cloud SQL database/schema naming and sizing
- Repo layout for copied code; import-graph subset; git-history preservation
- Worker concurrency mechanism for the 5+ target; service naming/region/sizing
- Proof-run injection mechanics (direct POST /api/runs)
- tenant_id/frozen-payload preservation (structural constraint from research)

## Deferred Ideas

- Budget-cap value + stale-reclaim calibration → Phase 16 (ENGINE-03)
- GUC/isolation unification across schemas → only if cross-schema queries ever needed
- Old Nestor repo archival beyond freezing → post-milestone housekeeping
