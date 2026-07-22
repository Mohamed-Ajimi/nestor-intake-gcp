# Phase 17: Raw Output + Audit Chain Guard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-22
**Phase:** 17-raw-output-audit-chain-guard
**Areas discussed:** Download contents & format, Storage & materialization, Broken-chain behavior, Failed-run output access

---

## Download contents & format

Before answering, the operator asked "what does the tribunal engine actually produce in a run?" —
answered from code inspection (`pipeline.py`, `worker.py`): final report md (with Verification
appendix), rejected_claims ledger, synthesis_cache (mission brief + scrubbed provider reports +
per-claim verdicts), claim/claim_source/source rows, audit hash-chain + stage trace + cost
metrics; `verification_report` returned but not persisted.

| Option | Description | Selected |
|--------|-------------|----------|
| Full bundle (zip) | report.md + rejected_claims.json + raw per-provider research reports | |
| Report only (.md) | Just the final markdown report | |
| Report + rejected claims | Report plus the dropped-claims ledger | |
| Other (free text) | "Full bundle without the rejected claims, but the output of the research filtered from dropped claims + sources" | ✓ |

**User's choice:** Full bundle EXCLUDING rejected claims: report + scrubbed research
(cleaned_reports — dropped-claim passages already removed) + sources.
**Notes:** The download must never expose discredited content.

| Option | Description | Selected |
|--------|-------------|----------|
| Sources per claim | claim→source evidence trail as structured JSON | ✓ |
| Flat source list | Deduplicated URL list, loses linkage | |
| You decide | Builder discretion | |

**User's choice:** Sources per claim.

| Option | Description | Selected |
|--------|-------------|----------|
| Zip of separate files | report.md + research/<angle>.md + sources.json | ✓ |
| One big markdown | Everything concatenated | |
| You decide | Builder discretion | |

**User's choice:** Zip of separate files.

---

## Storage & materialization

| Option | Description | Selected |
|--------|-------------|----------|
| At run completion | Poll-driver finalize builds + stores the zip once; clicks mint signed URLs | ✓ |
| On-demand at click | Assemble from Tribunal at download time | |
| You decide | Builder discretion | |

**User's choice:** At run completion.

| Option | Description | Selected |
|--------|-------------|----------|
| Intake app bucket | Phase-9 uploads bucket, space-scoped paths | ✓ |
| Tribunal audit bucket | 7-year-retention compliance store | |
| You decide | Builder discretion | |

**User's choice:** Intake app bucket.

---

## Broken-chain behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Complete but locked | Completed + loud broken-chain flag; download BLOCKED until investigated | ✓ |
| Mark run failed | Treat as run failure; re-trigger available | |
| Complete with warning | Flag loudly but allow download | |

**User's choice:** Complete but locked.

| Option | Description | Selected |
|--------|-------------|----------|
| Email + UI state | Dedicated mail variant + distinct card state | |
| UI state only | Card state only, no email | ✓ |
| You decide | Builder discretion | |

**User's choice:** UI state only.

| Option | Description | Selected |
|--------|-------------|----------|
| Re-verify button | Card action re-runs verify_chain; lock lifts on pass | ✓ |
| Manual only | Developer/DB task, lock effectively terminal | |
| You decide | Builder discretion | |

**User's choice:** Re-verify button.

---

## Failed-run output access

| Option | Description | Selected |
|--------|-------------|----------|
| Completed-only | Download only for green, chain-verified completed runs | ✓ |
| Partial download if available | Offer synthesis_cache content marked partial/unverified | |
| You decide | Builder discretion | |

**User's choice:** Completed-only.

---

## Claude's Discretion

- Where verify_chain physically runs (seam endpoint vs worker-side) — finalize step is the hook.
- Intake-side storage of chain/lock state + SSE wire shape.
- Bundle assembly mechanics / new tribunal endpoints (Phase-14 internal-auth rules apply).
- Signed-URL TTL, zip layout, file naming, bundle language.
- Intake-side download audit-logging.

## Deferred Ideas

- Surface `verification_report` as client-trust artifact (FUT-01, already tracked).
- Broken-chain email variant (UI-only chosen; revisit after a real incident).
- Partial output download for failed runs (rejected for v1.1).
