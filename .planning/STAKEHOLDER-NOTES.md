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

## 2026-07-24 — Verification redesign: selection-experiment numbers + REQUIREMENT: post-run verification report (superadmin-only)

**Context:** operator-driven re-analysis of run 4cbb5311, prompted by a Replit deep-research
comparison. Complements the 2026-07-22 forensic report. One correction to that section's
summary: "ZERO usable verifications survived" overstates — per REPORT.md §3.5, **152 of 176
group-skeptic sessions parsed fine and their verdicts DID reach adjudication**; the losses
were 24 F-01 parse crashes + the cap-killed tail.

**Selection experiment (blind, independent agents; artifacts in
`docs/tribunal-run-reports/run-20260722-4cbb5311/selection-experiment/`):**

- Population: **1,162 unique claims** distilled (from 2,976 distiller lines, 8 calls).
- Gate 1+2 (falsifiable-specific AND load-bearing): **KEEP 456 (39%) / DROP 706 (61%)**
  — 358 not falsifiable (recommendations, phase plans, scope statements), 320 not
  load-bearing (incl. ~149 "LUKOIL 100% stake in [Russian field]" boilerplate), 28 both.
- Gate 3 (error-likelihood; stable-notorious facts skipped, volatile domains kept): 456 → **424**;
  32 SKIP_STABLE (BE/LU max-price regime, MTS-K, NL free pricing, Austria 2011 act).
- Validation against actual verdicts (197 matched): dropped claims contained **no material
  refutes** (13/31 dropped refutes are definitions/scope/trivia — incl. the BDI case);
  SKIP_STABLE bucket: 8 support / 3 insufficient / **0 refute**. Refute *rate* is flat
  (~15-17%) across keep/drop — the gates concentrate *materiality*, not hit-rate.
- Grouping: **92% of ran groups are singletons** (163/177); same-fact variants split across
  keys and never reconciled despite the conflict stage — live contradictions shipped:
  Aral 16% vs 21% share, LUKOIL NL 46 vs ~70/75 stations, Zeeland "sold to Carlyle" vs
  "bought by TotalEnergies", Gunvor vs Carlyle sale.
- KPAnG case (claims 72-79): 6 "support" verdicts on **true-but-superseded** intraday
  pattern claims; the reconciliation note correctly said "pattern superseded since
  1 April 2026" but the verdict vocabulary cannot carry it — nuance rides a free-text
  field that synthesis may drop.

**REQUIREMENT (operator, 2026-07-24):** after every run, the app must auto-generate a
**verification report visible to the superadmin only** (never the client user — extends
D-08). Content: verification funnel stats (distilled / selected / sessions / verdicts /
skipped+why / failed loudly), refuted claims with skeptic evidence and effect on the
report, superseded/scoped findings with temporal caveats, reconciled contradictions with
chosen canonical values, the honest list of claims that shipped UNVERIFIED, and true cost
(fix the P1 undercount — include cache-write + deep-research usage). All source data
already exists (audit blobs, claim/claim_source, stage_detail); the hand-built
run-20260722-4cbb5311 report is the template to productize.

**Proposed Phase-15 redesign package (for discussion, evidence-backed):**
materiality gate (gates 1+2) → error-likelihood gate (gate 3) → canonical grouping
(entity aliasing / semantic clustering; contradictory variants MUST share a session) →
skeptics as-is on the ~424 → "superseded" verdict outcome carried into synthesis as a
mandatory caveat → fail-loud verification (0-verdict run must not report green) →
superadmin verification report (requirement above). Deeper cut available later via
cross-provider corroboration once Phase-19 embeddings land.
