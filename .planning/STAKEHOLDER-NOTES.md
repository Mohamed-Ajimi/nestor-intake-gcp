# Stakeholder Notes — open decisions

Running list of items to put in front of stakeholders. Each note states the current
behavior (verified in code), why it matters, and the decision being asked for.

---

## 2026-07-21 — Context pack regeneration: versioning edge cases

**Current behavior (verified):** every "Regenerate context pack" creates a NEW version;
old versions are kept forever as history. The research run always uses the newest
finished version automatically (the intake's pointer moves atomically with each
generation). This part is sound and needs no decision.

Three edge cases need a stakeholder call:

### 1. Old pack versions stay in semantic search
Every pack version gets embedded for semantic search, and superseded versions are never
removed — so search can return text from an outdated pack (e.g. quoting facts the
operator deliberately regenerated away).
**Decision asked:** when a pack is regenerated, should the old version's search index
entries be (a) deleted, (b) kept but flagged/deprioritized, or (c) kept as-is (status quo)?

### 2. Regenerating a pack resets the intake status to "decomposed"
Regenerating always sets the intake back to status `decomposed`, even when research is
already running or finished. Data is unaffected and duplicate research triggers are still
blocked, but the workflow display jumps backwards (the intake looks like it regressed).
**Decision asked:** should regeneration after research has started (a) be blocked,
(b) keep the current status instead of resetting it, or (c) stay as-is (accepted quirk)?

### 3. Race: starting research while a regenerate is still running
Pack generation takes ~30 seconds. If an operator clicks Regenerate and then "Start
onderzoek" before the new pack is finished, the research uses the PREVIOUS pack version.
Today the only protection is operator discipline (wait for the new pack to appear).
**Decision asked:** should the Start-research button be disabled while a context-pack
generation is in flight (recommended, small frontend guard), or is operator discipline
acceptable?

## 2026-07-22 — OPERATOR HOLD: no Anthropic usage-limit increase until engine defects fixed

**Decision (operator, 2026-07-22):** the Anthropic monthly usage cap stays where it is.
No further live Tribunal runs until the defects found in the run-4cbb5311 forensic audit
are fixed. Sequencing (operator, same day): engine fixes come LAST — after Phases 17 → 18 → 19.

**📄 The full forensic deep-research report (every step, every LLM call, claims/groups/verdicts):**
- Master report: [`docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md`](../docs/tribunal-run-reports/run-20260722-4cbb5311/REPORT.md)
- Groups & claims inventory (176 groups): `docs/tribunal-run-reports/run-20260722-4cbb5311/GROUPS.md`
- Per-call extracts (all 228 LLM calls, full input+output): `docs/tribunal-run-reports/run-20260722-4cbb5311/calls/`
- Machine-readable index: `docs/tribunal-run-reports/run-20260722-4cbb5311/index.json`
- Raw audit records (146 MB, permanent): `gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/`

**Findings driving the hold (from the first green delegator run, 2026-07-22, ~48 min):**

1. **[P0] Skeptic arm effectively OFF** — `group_skeptic.py:_parse_group_verdict` crashes with
   `'str' object has no attribute 'get'` when the LLM returns `reconciliation` as a JSON string
   (24/176 parsed groups); the rest of the tail died on the usage cap. Net: ZERO usable
   verifications survived, though the LLM produced 76 support / 31 refute / 91 insufficient
   raw verdicts. ~3-line isinstance/json.loads guard.
2. **[P0] Silent failure on usage-limit wall** — 776× Anthropic 400 "reached specified API
   usage limits" (11:58:46–11:59:41) gutted the skeptic tail, and the run still completed
   "green". Must detect and fail/park loudly.
3. **[P1] Honesty appendix overstates verification** — the report claims fact-checking that
   did not happen (cannot distinguish waved-through vs crashed vs 400'd).
4. **[P1] Cost meter massively undercounts** — panel showed ~€5; real Anthropic-side cost
   ≈ $43–45 (8.7M cache-write tokens ≈ $33 uncounted; deep-research calls have NO usage
   metadata recorded at all — the most expensive stage is invisible).
5. **[P1/P3] Audit fidelity** — `seq=0` on all 228 records; gemini-pro request contents
   truncated at 2000 chars; one empty scrub response.
6. **[P2] Intake `max_tokens=2048`** truncated both intake calls → forced coverage retry.
7. **[P2] 28 unresolved `[cite:]` markers stripped** — deep-research emits markers never
   bound to URLs; worsened by dead skeptic citation recall.
8. Pydantic serialization warnings from shallow `_content_to_serialisable` (skeptic.py:204)
   — latent turn-2 breaker.

**Cost reality for planning:** observed run ≈ $43–45 Anthropic-side (panel said €5);
a fully-working run (skeptic fixed + no cap) is estimated $55–90+ per run. Cap raise
decision revisits AFTER fixes land and one calibration run confirms true cost.

**Not blocked by this hold:** Phase 17 deploy + download/chain UAT — it rides on the
already-completed run 4cbb5311 and needs NO new LLM calls (verify_chain + bundle build
are DB/GCS operations).
