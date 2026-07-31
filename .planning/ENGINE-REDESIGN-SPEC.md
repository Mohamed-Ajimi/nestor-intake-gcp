# Engine redesign — specification and phase plan

**Written 2026-07-29.** Everything needed to execute without re-deriving this session's reasoning.
Decisions taken by the operator in session; evidence is from V-01 (`7dcf51d5`, 2026-07-28) and from the
per-call audit blobs.

**Read first, in this order:**
1. `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md` — the two root causes
2. `docs/tribunal-run-reports/run-20260728-7dcf51d5-V01-FINDINGS.md` — the run's full forensics
3. This document

---

## 0. Where this came from

V-01 produced a report whose coffee section told the client the Benelux data *"geeft geen volledig
beeld"*. That statement was false. The engine had **278 well-formed coffee claims** and threw them
away on a string comparison. Diagnosing that is what produced this plan.

Two things were established, and both overturned what the findings document assumed:

- **The missing `FACTS` block is format drift, not truncation.** Gemini's two *longest* reports (88k
  chars) both carry complete blocks. → the Q4 grouping gate is cleared.
- **The distiller worked.** It returned 278 evidence-bearing claims; `_parse_distiller_response`
  dropped every one because the model wrote the literal string `<TAB>` instead of U+0009 — and the
  prompt itself uses `<TAB>` as a placeholder *describing* the separator.

The second finding is what reorders everything below: the top fix is three lines of parser and prompt
hygiene, not the report-writer rewrite the findings doc proposed.

### Measured cost baseline (exact, from the audit log)

| Stage | Calls | Cost | Notes |
|---|---|---|---|
| Orientation (web-grounded) | 3 × sonnet | **$0.45** | runs **once**, not per loop round |
| Candidate generation | 4 × sonnet | $0.068 | |
| Critique + tournament (4 Elo rounds) | 6 × gemini-flash | **~$0.00** | 8.4k in / 400 out **total** |
| Stage summary | 1 × sonnet | $0.017 | |
| **Whole workshop** | 14 calls | **$0.54 / 63 s** | |
| **Research (the money)** | 19 angles | **~$50** | ~60 of the run's 65 minutes |

**Thinking is cents; research is fifty dollars.** That asymmetry justifies every "spend more in the
workshop" decision below. It also reframes the tournament complaint: it is not underpowered because
it is expensive — six flash calls at ~30 output tokens each is what **$0.00** buys.

> **Loop cost — added 2026-07-31.** The table above is V-01's **single-pass** workshop and its per-stage
> figures are audit-log facts, unchanged. What has changed is § 5's *loop* estimate: it projected
> **~$3.00 for 10 rounds**, and that estimate is **SUPERSEDED**. Measured end-to-end, the validated
> Wave 4 configuration runs the entire loop for **$0.24 (exp11)** and exits in round 4 rather than at
> the cap. **Do not carry the ~$3.00 figure forward.** The three-configuration comparison is in § 5
> `### The validated configuration`; it is deliberately not repeated here as a range.

---

## 1. Decisions taken

| id | Decision | Status |
|---|---|---|
| **D-R1** | Distiller parser accepts the literal `<TAB>`; the prompt stops using `<TAB>` as a placeholder | agreed |
| **D-R2** | Retry on an unusable fact list — covering **all three** gemini format deviations | agreed |
| **D-R3** | Stamp sub-question + `corroboration_key` on the claim row | agreed (prerequisite for D-R4) |
| **D-R4** | An LLM groups winners into **≤5 groups**; each group goes to **all providers** | agreed (operator) |
| **D-R5** | Drop `own` from the provider rotation until it is fixed → 3 providers | agreed |
| **D-R6** | The workshop becomes a **creative loop**: generative evolve, judges give reasons, meta-review, **10-round cap** | agreed (operator) |
| **D-R7** | A **discovery bracket** — evidence-anchored questions the client did not ask | agreed (operator) |
| **D-R8** | Record yield per assignment so routing can later be evidence-based | agreed |
| **D-R9** | **Q1 resolved: keep the tournament and make it real.** It earns its cost only because D-R7 gives it genuinely different ideas to rank | agreed · **reaffirmed 2026-07-29** ("we are not killing tournament"); pairwise Elo RETAINED, ties fixed by raising rounds |
| **D-R10** | **The loop DISCOVERS, it does not only sharpen. Evolve may invent an angle; a grounded lookup decides whether it earns a slot** — source found, it becomes a discovery candidate; nothing found, dropped and logged. **Admission test CORRECTED 2026-07-31:** the lookup verifies the **PREMISE is real** (do the named entities, markets, mechanisms and metrics exist, and could desk research settle it) — **not** that a published answer already exists, which rejected all 4 invented angles. Evidence must be a real `groundingChunks` search result, never the model's own output line | agreed (operator) **2026-07-29** |
| **D-R11** | **Elo CARRIES across loop rounds** (stands), and ~~a newly evolved candidate is seeded at the field MEDIAN, never at a fixed 1200~~ **SUPERSEDED 2026-07-31 — the seed is INERT (`wins` is the primary sort key, Elo only the tie-break; median-seed and flat-1200 are byte-identical). Replaced by a CATCH-UP SCHEDULE: a newcomer plays up to the field's median match count on entry** | agreed (operator) **2026-07-29** · seed mechanism superseded by measurement, ruling intent preserved |

### The two premises that changed, and why they hold

**Invention is allowed (D-R7).** The rule is *"D4 — THE WORKSHOP MAY ADD DEPTH, NEVER CHANGE SCOPE"*,
and its only hard enforcement is `enforce_scope_guard`: a Python assertion that the winners' `parents`
UNION is a **superset** of the client-validated labels. That is a **coverage floor, not a ceiling** —
adding questions does not violate it. The "never invent" half lives in two prompt sentences
(`"never change what is being asked"`, `"do NOT broaden"`), and the same file says a prompt sentence
is not a control: *"A model asked nicely to respect scope is not a control."* So today's no-invention
rule is a hope, not a guarantee. This plan makes it explicit and bounded instead.

**The tournament is worth fixing only with D-R7.** Without invention it ranks narrower rewordings of
questions the client already asked, and D4 forces most winners anyway — an expensive coin flip. With a
discovery bracket it does what Co-Scientist's tournament does: choose among genuinely different ideas.

---

## 2. Wave 1 — extraction repair

> **⚠ SEQUENCING OVERRIDDEN BY THE OPERATOR, 2026-07-29.** The "ship this alone" instruction below is
> **no longer in force**. The operator ruled: *"I don't want to measure anything unless we finish all
> changes."* Wave 1 is built and gate-verified but **NOT deployed**; Waves 2-5 are built on top of it
> and the whole redesign ships in ONE deploy with ONE measuring run at the end.
>
> The trade-off was stated and accepted: with several waves landing together, an unexpected result in
> that run cannot be attributed to a single change. Recorded here because the paragraph immediately
> below argues the opposite and would otherwise read as current guidance.

**Ship this alone, first, and let one run measure it.** Everything downstream is judged through the
extraction funnel; shipping the redesign on top of a broken meter would attribute the parser bug to
the redesign.

### 1.1 — The `<TAB>` fix (D-R1)

`tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py`

**(a) Parser** — `_parse_distiller_response`, line ~1281. Today:

```python
if "\t" not in line:
    log.debug("claim_distiller: skipping malformed line (no tab): %r", line[:80])
    continue
parts = line.split("\t", 2)
```

Replace the split with a separator-tolerant one. Accept, in priority order: a real tab, the literal
`<TAB>`, ` | `, and a run of 2+ spaces. **Priority order matters** — a line containing both a real tab
and a literal `<TAB>` must split on the tab.

```python
_SEPARATORS = ("\t", "<TAB>", "|")

def _split_distiller_line(line: str) -> list[str] | None:
    """Split one distiller line into <=3 columns, tolerating the separator the
    model actually used. Returns None when no separator is present at all.

    The model is asked for a TAB. It does not always send one: on run 7dcf51d5
    two of four distiller calls emitted the literal five-character string
    `<TAB>` instead, because the PROMPT uses `<TAB>` as a placeholder describing
    the character. 278 well-formed claims were dropped. Accepting the
    placeholder costs nothing and cannot produce a false positive: a claim whose
    text legitimately contains the literal `<TAB>` does not occur.
    """
    for sep in _SEPARATORS:
        if sep in line:
            return [p.strip() for p in line.split(sep, 2)]
    return None
```

**(b) Prompt** — `_build_distiller_prompt`, lines ~1237 and ~1256. Stop describing the separator with
a token the model can copy. Two options; **take the second**:

- write a real tab into the example — invisible in source, fragile under reformatting
- **switch the contract to an unambiguous delimiter** and accept a tab for back-compat

```
  - Each line MUST use this format: FACET ||| CLAIM_TEXT ||| EVIDENCE
```

Add `"|||"` to `_SEPARATORS` **ahead of** `"|"`. Note the existing tests
(`tests/test_claim_distiller.py`, `tests/test_distiller_coverage.py`) pin the prompt byte-for-byte —
the docstring at line ~1203 says so explicitly. **They must be updated in the same commit**, and the
update is the point of review, not an incidental fixup.

**(c) Make the drop loud** — `_distill_unit`, after `_parse_distiller_response`:

```python
claims = _parse_distiller_response(text or "", focus_area_labels, provider=name)
if text and not claims:
    log.warning(
        "claim_distiller: chunk from %r returned %d non-empty line(s) but ZERO "
        "parsed as claims — first line: %r",
        name, len([l for l in text.splitlines() if l.strip()]), (text.splitlines() or [""])[0][:200],
    )
```

**This one line is the whole lesson of V-01.** Returned-output-but-kept-nothing is the failure that
produced a false statement in a client report, and it was invisible because the only trace was
`log.debug`. WARNING is the lowest level production actually serves (see D-V01-6).

**(d) The ZERO-claims warning is untrustworthy** — line ~1578. It iterates every focus area in the
mission brief and reports zero for any label absent from *this call's* output, whether or not that
facet was in scope. On V-01 it cried wolf about convenience (never in the call) next to a real coffee
zero. Scope it to the facets present in the call's **inputs**:

```python
in_scope = {str((r or {}).get("_angle") or "") for _, r in provider_reports}
for fa in focus_area_labels:
    if fa in in_scope and facet_counts.get(fa, 0) == 0:
        log.warning("claim_distiller: focus area %r produced ZERO claims — unverified topic", fa)
```

### 1.2 — Retry on an unusable fact list (D-R2)

`tribunal/nestor_pulse_sdk/pipeline/tribunal/facts.py` + `synthesis/steps.py::collect_provider_facts`

Gemini's fact-list failures are **three distinct format deviations**, not one. A retry covering only
"block absent" fixes one of three:

| idx | Deviation | V-01 symptom |
|---|---|---|
| 12, 16 | No `FACTS_START/END` block at all | `gemini returned no FACTS_START/FACTS_END block` |
| 8 | Block present; every line prefixed with a literal `STATEMENT` column, shifting every field one place | `not one line in it parsed as a fact (4 line(s) ignored)` |
| 4 | Block well-formed; `SOURCE_URL` column is the `[cite: N]` marker | ~20 × `rejecting non-http(s) SOURCE_URL '[cite: 25, 26]'` — facts survived, **sources did not** |

Implement **one retry** at the `collect_provider_facts` level, on the `needs_distiller_fallback`
branch (line ~2015), before falling through to `fallback_units`:

- Re-ask the **same provider** for **only the fact list**, over its own report text, using the same
  `build_fact_list_prompt_block` contract plus an explicit corrective ("your previous reply did not
  contain a parseable block / used a `STATEMENT` prefix / used `[cite: N]` where a URL was required").
- Parse the retry with the same `parse_fact_list`. On success, treat it exactly as a first-pass block.
- On failure, fall through to the distiller as today — the retry is **additive**, never a new failure mode.
- Cap: **one** retry per report. Log the attempt and the outcome at WARNING.

Add a **normalising pre-parse** in `parse_fact_list` for the idx-8 shape: if every non-empty line in
the block starts with an identical leading column that is not a claim (`STATEMENT`, `FACT`, `CLAIM`),
strip it before field assignment. Cheap, deterministic, and it rescues a whole report.

For idx 4, do **not** reject the fact — reject only the URL (this is already the behaviour) — but
record the `[cite: N]` marker so 1.3 can resolve it.

### 1.3 — Resolve gemini redirects at ingest (D-V01-11)

Every `vertexaisearch` grounding redirect resolves via a plain `302` to a publisher URL; 225/225
resolved on V-01, and they **expire ~30 days after the run**. Resolve at ingest and store the
publisher URL alongside the redirect:

- dedupe first (V-01: 642 instances → 225 unique)
- `HEAD`, follow one hop, read `Location`; no API key, parallelises trivially
- on failure keep the redirect and mark it unresolved — never drop a citation
- this **permanently fixes citation rot**, and is the durable form of the one-off preservation already
  committed as `run-20260728-7dcf51d5-CITATIONS.tsv`

### 1.4 — Smalls in the same wave

- **`gpt-5.6-sol` is absent from the cost table** → 5 NULL-cost calls per run and `run.cost_pending`
  never clears, so **$53.48 is a floor**. Add the model to the cost table.
- **`own` researcher reports in English** while the run is Dutch (D-V01-3) — those 17 claims can never
  match anything. Fix or accept D-R5 (drop it) — see Wave 3.
- **`run_event` rows dropped** (D-V01-7): ~20 `KeyError`/`TypeError` in `emit_safe` for
  `stage='deep_research' kind='agent_done'` and `stage='own_research'`. 15.3's feed is incomplete.

### Wave 1 — done when

- [ ] A distiller response using `<TAB>`, `|||`, a real tab, or ` | ` all parse to the same claims
- [ ] A unit returning lines but zero claims logs at **WARNING** with the offending line
- [ ] The ZERO-claims warning fires only for facets present in the call's inputs
- [ ] All three gemini deviations are covered by the retry; the `STATEMENT` normaliser has a test
- [ ] Redirect resolution runs at ingest, dedupes, and degrades to keeping the redirect
- [ ] `test_claim_distiller.py` / `test_distiller_coverage.py` updated **deliberately**, with the
      prompt change reviewed as the substantive edit it is
- [ ] **Replay proof:** feed V-01's two coffee audit blobs through the new parser and assert **278**
      claims recovered. This is a regression test with a real, known-good fixture — use it.

---

## 3. Wave 2 — claim attribution (D-R3)

**This is a hard prerequisite for Wave 3**, not a nice-to-have. Today a claim's `facet` is the parent
client question, inherited from the angle (`_angle` → `facet`, stamped in Python, never read from
model output — `T-15.2-60`). Once a group can span two client questions, that inheritance breaks: a
claim from a mixed group has no single parent.

### Changes

**Schema** (`tribunal/nestor_pulse_sdk/db/models/claim.py` + a new alembic revision on top of 0015):

| Column | Type | Purpose |
|---|---|---|
| `sub_question` | `Text`, nullable | the winner text this claim answers |
| `corroboration_key` | `Text`, nullable | the shared key (`w01`/`w02`/…) — the real join key for corroboration |
| `as_of` | `Date`, nullable | the claim's own date, where the provider stated one |

**Why `as_of` belongs here.** D-V01-4 was withdrawn because gemini and claude read *different* De Haan
articles at different points in a rollout — 7 sites in 2021 vs ~90 later. **Both were true.** Without a
date the engine cannot tell a contradiction from a time series, and neither could the analysis. This is
missing metadata, not a missing detector.

**Threading**: `corroboration_key` already exists at dispatch (`w01`/`w02`/`w03` on corroboration
angles). Carry it through `_enriched` alongside `_angle`/`_stakes`/`_d8_prompted`
(`research_division.py:1458`) into `collect_provider_facts` and onto the claim row. **Stamp in Python
from the assignment — never parse it out of model output.** That is the identical rule
`_parse_distiller_response` applies to `provider` and `enforce_scope_guard` applies to `parent`.

### Invariants

- Nullable everywhere: legacy rows and the distiller path (which has no source and no certainty by
  design) must keep working.
- A claim whose group spanned two client questions gets its `facet` from **its sub-question's** parent,
  not from the group.
- No behaviour change in Wave 2 beyond recording — corroboration still uses today's key.

---

## 4. Wave 3 — dispatch redesign (D-R4, D-R5)

### What exists today

```python
_STAKES_PROVIDER = {"high": "gemini", "med": "openai", "low": "claude"}   # research_division.py:122
_D6_STREAMS      = ("gemini", "openai", "claude", "own")                  # :130
_D6_TOP_K        = 3     # top-3 winners go to all four streams           # :135
_D6_MAX_WINNERS  = 15                                                     # :145
```

Top-3 → all four providers; **the remainder is dealt round-robin**, one angle each. So coffee did not
land on gemini because gemini is good at Benelux retail — it landed there by **position in the deal**.
And the one place preference applies is inverted: high stakes routes to gemini, the *least*
format-reliable provider on V-01, while claude — the most reliable — is reserved for low stakes.

### What replaces it

**An LLM groups the winners into ≤5 groups by shared research groundwork; each group goes to all
providers.**

```
winners (mandate + discovery)
        │
        ▼  LLM grouping  (≤5 groups, semantic — by shared groundwork)
   ┌────┴────┬─────────┬─────────┬─────────┐
  G1        G2        G3        G4        G5
   │         │         │         │         │
   └─── each group → gemini + openai + claude ───┘
                    = 15 paid calls
```

Grouping is **semantic, not structural**. A group may span two client questions where they overlap, and
one client question may split into two groups if it is really two topics. That is where the saving
comes from — shared groundwork is searched once instead of five times.

**Provider count.** `own` is dropped (**D-R5**): 2 of its 4 angles failed outright
(`own_researcher_no_fact_list`), it reports English in a Dutch run, and it contributed **2 unique URLs**
in the whole run. Keep it as a targeted fact-lookup tool, not a research stream. So **5 × 3 = 15 calls**
against V-01's 19 — cheaper, with every question fully cross-checked.

**No routing logic at all.** Uniform allocation is the correct default *because we have no trustworthy
data to route on* — V-01's yield numbers are contaminated by the `<TAB>` bug. Wave 5 collects the data
that could justify routing later; until then, uniformity is the honest choice and it eliminates the
inverted stakes→provider map outright.

### Why uniform allocation, not corroboration

Do **not** justify this as "more corroboration". V-01 measured **2.9% of URLs cited by ≥2 providers**
and **37 of 396 claims** with any cross-provider partner at a very loose Jaccard 0.2. Four providers on
one question largely read four different corpora. The real payoff is **failure independence and
complementary reach**: coffee got three sub-questions at one provider each, so when two hit the parser
bug the client's entire coffee question survived on 8 claims from a single provider. Under grouping,
one provider failing leaves two standing.

### Four things it needs to be safe

1. **Move the coverage assertion.** `enforce_scope_guard` today asserts the winners' `parents` union
   covers every client question. It must now **also** assert every client question is represented in at
   least one **group**, in Python, after the LLM groups. An LLM deciding grouping is an LLM that can
   drop a question. Keep the existing repair ladder (promote the best below-the-cut candidate, else
   inject the client question verbatim, ranked **first** — the placement is deliberate: stakes and
   stream allocation derive from `rank`, so appending at the bottom would give the client's own
   validated question the weakest treatment).
2. **Cap questions per group.** The known risk with grouping is a provider writing six thin paragraphs
   instead of one deep report. V-01 gives mild reassurance — gemini's r8 covered Shell, Circle K *and*
   LUKOIL in depth in one report — but that is one data point. Cap group size and check run one.
3. **A rule for >5 natural groups.** If a brief has 7 distinct topics, forcing 5 makes one a grab-bag.
   Make 5 a **default dial**, not a hard cap; let it rise for complex briefs.
4. **Attribution** — Wave 2. Non-negotiable.

### Discovery bracket (D-R7)

- **Mandate bracket** — the client's questions and their sub-questions. Coverage guaranteed exactly as
  today. **Nothing here can be displaced by a discovered question, ever.**
- **Discovery bracket** — questions the *evidence* raised, each carrying the quote and source that
  provoked it. **No source, no slot.** Its own cap; it can never borrow from the mandate. If discovery
  finds nothing, its slots **roll back to the mandate** (more depth), not into more discovery.

**Allocation is a global pool with a per-parent cap.** Not per client question: on V-01 *both*
`brief_conflicts` were about Q1, so a per-question quota would have forced the system to **manufacture**
a coffee discovery question to fill it — exactly the free invention we ruled out. A quota forces
invention. The per-parent cap (no more than 2–3 of ~5 slots from one client question) exists because
discovery volume partly tracks research volume — Q1 had 8 reports, coffee 3 — so a pure global pool
quietly rewards the already-well-funded question.

**Cross-cutting discoveries need a home.** A finding like "two chains bought 300 Benelux sites in 2025"
bears on pricing *and* coffee *and* convenience. Every candidate must carry a `parent` (D4's assertion
joins on it; `research_division` derives stakes and allocation from `rank` alongside it), so give
cross-cutting questions an explicit parent value (`__discovery__`) that the coverage assertion knows to
**ignore** — otherwise the guard either rejects them or, worse, silently counts one as covering a client
question it does not answer.

**Timing.** Discovery can only spend slots *this run* if it fires **before** research — i.e. off the
orientation pass, which already produces `brief_conflicts`. Richer discoveries surface from the research
itself (442,904 chars on V-01) but by then the money is spent: those become **"questions for the next
run"**, reported not researched.

**Governance.** `D5 / D-01` states the workshop is **FULLY AUTOMATIC** — *"Nothing in this module pauses
for an operator."* So discovery cannot be gated on an approval click inside the workshop. Instead
discovered questions carry their provenance to the report and land in the section that already exists:
`### Where the brief did not match what the research found`. The client sees plainly which questions they
asked and which the evidence raised. Provenance is also required for the Art. 12 audit trail
(**deadline 2026-08-02**).

### Worked comparison

| | V-01 as it ran | After Wave 3 |
|---|---|---|
| Q1 dynamic pricing | 4 sub-questions, top 3 → 4 providers | grouped |
| Q2 coffee | 3 sub-questions, **1 provider each** | grouped → **3 providers** |
| Q3 convenience | 3 sub-questions, 1 provider each | grouped → **3 providers** |
| Discovery | 0 | ~1 group |
| **Paid calls** | **19** | **15** |

---

## 5. Wave 4 — the creative workshop loop (D-R6, D-R9)

### What was measured on 2026-07-31, and what it overturns

**A local harness ran 11 experiments for ~$3, entirely in a scratchpad. NO REPO CODE WAS CHANGED.** It
replayed the real V-01 run (`7dcf51d5`) out of the GCS audit log, lifted the stages that already exist
verbatim out of `workshop_rank.py`, and then implemented the Wave 4 loop end-to-end — so this design
could be *run* rather than argued about.

**Four of the five headline diagnoses in this section were disproved.** Each is corrected inline below;
no superseded claim is deleted. The original text is kept, struck through and marked
`**SUPERSEDED (measured 2026-07-31)**`, with its measured replacement beside it, so a future reader can
see what was believed and why it was wrong.

| # | The diagnosis as this section wrote it | What measurement showed |
|---|---|---|
| 1 | *"9 of 10 winners flagged `WEAK` by our own critic"* is a quality signal | **DISPROVED** — it is a truncation artefact of `_CANDIDATE_PROMPT_CHARS = 240`; see below |
| 2 | The exit rule can never fire, so the loop hits the 10-round cap every run | **DISPROVED** — every measured configuration exits on all three criteria, well inside the cap |
| 3 | The population balloons (*"a round-9 prompt carrying 60 candidates"*) and 10 rounds costs ~$3.00 | **DISPROVED for one global loop** — population stays between 23 and 41 and the validated configuration costs **$0.24 (exp11)**. Still **TRUE** under per-client-question brackets |
| 4 | A newcomer must seed at the field median (D-R11) or a late angle is structurally last | **DISPROVED** — the seed value is inert; it changes no output at all. Replaced by a catch-up schedule |
| 5 | D-R9 — the Elo-1200.0 ties are real and the round count is the fix | **CONFIRMED** — reproduced exactly, and the fix works |

**The operator rulings in `15.7-OPEN-ITEMS.md` are unchanged.** The tournament stays, the loop must
DISCOVER, and losers are never barred. What follows corrects **diagnoses and numbers, never a ruling**.

**Honest limits of this measurement**

These results are real, but they are not large. All three limits apply to every figure in this section
and none of them is a reason to ignore the figures — they are the reason to read them as *direction*
rather than as *constants*.

- **Every result is n=1.** One client, three client questions, Dutch, 18 candidates. Nothing here is a
  distribution; it is one brief, measured carefully.
- **Sonnet's evolve call runs at temperature 1.0, so a single run varies.** Three runs of **the same
  configuration** exited at **rounds 4, 6 and 6**. Read that as run-to-run variance *within one
  configuration*. It is **NOT** the config-to-config comparison in `### The validated configuration`
  below, where exp7c, exp10 and exp11 are three *different* configurations — those differences are
  causal, this one is noise. Any round number quoted for a configuration is one draw from a spread of
  roughly this width.
- **The stages that do not exist in the codebase yet were implemented by the harness author** —
  generative evolve, meta-review, the grounded lookup, judge reasons, carried Elo, the catch-up
  schedule and the exit checks. Those results test the **DESIGN, not any implementation**: they say the
  design converges, not that Wave 4's code will. The stages lifted verbatim from `workshop_rank.py` —
  the critique and tournament prompts, both parsers, Swiss pairing, Elo, `winner_count` and the
  renderers — **do** transfer directly, and any result resting on those is a statement about the real
  code.

> ### ⚠️ SIX OPEN AMBIGUITIES — items 3 and 4 are now CLOSED BY MEASUREMENT (2026-07-31); settle the rest BEFORE planning 15.7
>
> Recorded 2026-07-29 by an audit of this document for the defect class that nearly shipped in Wave 3:
> **the spec saying two different things in two places, where each reading looks complete on its own.**
> Wave 3's grouping ambiguity survived a full planning pass and was only caught mid-review. These are
> the same shape. **A planner must not resolve any of them silently — route them to the operator.**
>
> 1. **✅ RULED 2026-07-29 — THE TOURNAMENT STAYS. Operator: *"we are not killing tournament".***
>    D-R9 stands unchanged and **pairwise Elo is retained**. The "Fix the arithmetic" paragraph below
>    offers two remedies for the Elo-1200.0 ties — raise the rounds, **or** replace pairwise Elo with a
>    ranked list plus a run-off — and calls the second *"better at our size"* without deciding. **That
>    option is now REJECTED.** The ties are fixed by **raising the rounds** so every candidate plays
>    ≥5–6 matches. Read that paragraph accordingly; on its face it still reads as an open choice.
>    **This is affordable to the point of being free:** the whole 4-round tournament measured 6 ×
>    gemini-flash, 8.4k in / 400 out, **~$0.00**. Six to eight rounds is a handful more flash calls.
>    *Still open (a number, not a direction):* the exact round count. The requirement is ≥5–6 matches
>    per candidate, which at ~17 candidates is roughly 6–8 rounds. **Prefer deriving it from the
>    candidate count over hardcoding**, so it cannot silently under-separate again as the population
>    grows each round — under-separation is exactly what produced ranks 8/9/10 finishing where they
>    started and taking research slots by tie order.
> 2. **✅ RESOLVED BY (1).** The A/B control survives. § 8 nominates
>    `NESTOR_TRIBUNAL_WORKSHOP_TOURNAMENT=false` (ranks by index, zero LLM calls) as the control that
>    proves the loop earned its cost, and keeping pairwise Elo keeps that switch meaningful. There is
>    only ONE measuring run, so this mattered.
> **✅ TWO MORE RULED 2026-07-29 — D-R10 and D-R11, both added to § 1 and written up in full below.**
> Neither was an ambiguity in the document; both were **gaps nobody had noticed**, surfaced by the
> operator asking whether the loop was genuine discovery or a fancy rephrase. **D-R10:** as written the
> loop could not produce a new angle after round 1 (orientation runs once, discovery needs its source,
> the mandate keeps its scope lock) — so evolve may now invent, and a grounded lookup admits or drops it.
> **D-R11:** the tournament now runs inside the loop up to 10 times and nothing said what happened to a
> rating between rounds — Elo carries, and newcomers seed at the field median so a late genuine angle is
> not structurally last.
>
> 3. **✅ CLOSED BY MEASUREMENT 2026-07-31 — the exit rule FIRES, and needs no change at all.** The
>    ambiguity as originally recorded, kept for the record: ~~*"The exit rule and the cost estimate
>    contradict each other. Exit needs all three criteria, one being 'no `WEAK` question remains in the
>    winner set'. V-01 had 9 of 10 winners `WEAK`. If that is typical the loop runs all 10 rounds EVERY
>    run — yet this section says 'the cap is a ceiling, not a target, and you will rarely reach it.'
>    Both cannot hold. Cost of being wrong: ~$3 and +5–7 min on every run rather than occasionally."*~~
>    **Its premise was the cap-240 truncation artefact.** With the truncation fixed, all three measured
>    global configurations exit on all three criteria well inside the cap — **exp7c in round 6, exp10 in
>    round 9, exp11 in round 4**. The *"ceiling, not a target"* sentence is therefore **CONFIRMED**, not
>    contradicted, and **no operator ruling is required.** See `### Exit criteria — all three, or the
>    cap` below.
> 4. **✅ CLOSED BY MEASUREMENT 2026-07-31 — nothing binds at this scale; the ceiling becomes
>    instrumentation.** The ambiguity as originally recorded, kept for the record: ~~*"The spend ceiling
>    has no value. Named as the second backstop and never set — the same omission as the group-size cap,
>    which Wave 3 had to choose for itself. This section itself names the shape it must bound: a round-9
>    prompt carrying 60 candidates, which a round-count cap does not catch."*~~ Under **one global
>    loop** the population stays **between 23 and 41** across all three measured configurations and the
>    largest prompt the loop ever builds is **~9k chars**; the validated configuration (**exp11**) costs
>    **$0.24** in total. Replace the enforced ceiling with **instrumentation** — log population and
>    spend per round. **The 60-candidate explosion IS real, but only under per-client-question
>    brackets**, where the population reached **122**: it is architecture-dependent, not inherent, so
>    the warning is **scoped rather than deleted.** See `### Why 10 rounds is affordable` below.
> 5. **"Barred this run, kept for the next" describes storage that does not exist.** Nothing persists
>    workshop state across runs. Either that is a new table (a **fourth** unpaid migration) or the
>    phrase means something narrower.
> 6. **Enrichment has no source for a discovery question.** Evolve is to be passed *"the orientation
>    findings for the parent question"*. A cross-cutting discovery question's parent is
>    `__discovery__`, which has no findings. Same class of gap D-W3-5 closed for dispatch.

### What is wrong today, precisely

| | Co-Scientist | Ours |
|---|---|---|
| What is ranked | novel hypotheses it invented | **rewordings of client questions** |
| Judge output | simulated debate, with reasoning | literally `3 | A` — **one letter, no reason** |
| Evolution | *"refines, **combines**, builds upon"* | *"Do NOT merge two questions into one, and do NOT broaden one"* |
| Feedback | meta-review → generation | **none** |
| Iterations | many | **one** |

And the measured symptoms: ~~**9 of 10 winners flagged `WEAK` by our own critic, 0 killed**~~
**SUPERSEDED (measured 2026-07-31) — that is a TRUNCATION ARTEFACT, not a quality signal**; ranks 8, 9
and 10 tied at **Elo exactly 1200.0** with 2 wins each — they finished where they started and took their
research slots by tie order (**this second half is CONFIRMED** — reproduced exactly; see
`### Fix the arithmetic`).

**Why the `WEAK` flood is an artefact.** `workshop_rank.py:168` sets `_CANDIDATE_PROMPT_CHARS = 240`.
The real V-01 candidates are **245–373 characters** long, so **17 of 18 reached the critic cut off
mid-word** — 920 characters discarded, with no ellipsis and no question mark surviving — while the
critic was being asked whether each question is *"sharp and answerable AS IT STANDS"*. It answered
honestly about the text it was shown. It was never shown the questions.

Measured on the real critique prompt against the real V-01 candidates:

| candidate cap | critique result | distinct flaw clauses |
|---|---|---|
| `240` (as shipped) | **`KEEP=1/WEAK=17`** | **2** — 16 of them the identical *"two questions in one"* |
| raised | **`KEEP=9/WEAK=9`** | many, and specific |

Two distinct flaw clauses across seventeen rejections is itself the tell: a critic finding real,
varied faults does not repeat one sentence sixteen times. It was describing the cut, not the question.

End-to-end (critique → tournament, rounds held at 4): **"9 of 10 winners `WEAK`" reproduces exactly at
cap 240, and becomes 2 of 10 with the cap raised.** The symptom this entire section was built on is the
cap.

**The truncation is a real security control and must NOT simply be deleted.** It bounds
attacker-influenced text so an injected candidate cannot forge another candidate's output line — the
same channel Wave 3's CR-02 closed on `source_url`. It needs *a* bound; it does not need **240**. Note
also that the same cap truncates **both sides** in `_match_block`, so the tournament was judging
mutilated text too — the critic was not the only stage reading half a question.

### The loop

```
orientation (once, $0.45, web-grounded)  ──►  brief_conflicts ──┐
                                                                │
   ┌────────────────────────────────────────────────────────────┘
   ▼
 generate ──► critique ──► rank (with reasons) ──► EVOLVE (generative)
   ▲                                                     │
   │                                                     ▼
   └────────── meta-review ◄────────── re-critique + re-rank
                                    (max 10 rounds; exits below)
```

**Evolve becomes generative — this is the change.** Take the top-ranked and produce *new* questions,
**added to the pool, not swapping out their parents**:

- **combine** two winners into one sharper question covering both
- **extend** — "if the answer is yes, what is the next thing we would need to know?"
- **invert** — "what would have to be true for this to matter?"
- **specialise** — name the entity, geography, timeframe

Delete the sentence at `_EVOLVE_PROMPT` line ~1718: *"Do NOT merge two questions into one, and do NOT
broaden one."* Keep the scope lock **for the mandate bracket** (a mandate question stays inside what the
client asked); discovery questions are governed by the evidence-anchor rule instead.

**Enrichment (the operator's "enrichment is lacking").** Evolve today may only *"name the entity, the
geography and the time frame **where the question already implies them**"* — it cannot inject what
orientation just learned. Pass the orientation findings for the parent question into the evolve call and
allow specificity injection. Concretely: orientation surfaced OPIS saying *"very few change their prices
more than once a day"*; *"do retailers use dynamic pricing?"* should come out as *"at what cadence do
Benelux retailers actually reprice, and where is that visible to customers?"* Same scope, far more
answerable.

**Judges must reason.** Change `_TOURNAMENT_PROMPT` (line ~969) output from `MATCH_INDEX | A` to
`MATCH_INDEX | A | <one clause why>`, and pass every judging call the parent client question in full plus
the orientation findings for it. Today the judge sees two question texts, a short decision blurb, and a
160-char flaw clause (`_FLAW_MAX_CHARS`) — it is judging blind. Three effects: better judgements (the
model reasons before answering), an audit trail of *why* 7 beat 9, and material for the meta-review.

**Fix the arithmetic — D-R9 CONFIRMED by measurement (2026-07-31).** `_TOURNAMENT_ROUNDS = 4` over 17
candidates cannot separate them — hence the 1200.0 ties. **The harness reproduced V-01's exact
symptom:** three candidates finishing at **Elo exactly 1200.00 with 2 wins each**, straddling the
top-10 cut, so one of them lost its research slot to index order. The arithmetic is simply short —
**4 rounds over 17 candidates gives each candidate only 3.76 matches.**

Raise the rounds so every candidate plays ≥5–6 matches. Measured: **carried Elo + 5 Swiss rounds + the
catch-up schedule eliminated the ties entirely — zero candidates sitting at exactly 1200 in any
round.**

~~**or** — better at our size — replace pairwise Elo with a **ranked list with reasons in one call**,
then a run-off among the top group. Cheaper, more consistent, no ties.~~ **REJECTED — operator,
2026-07-29: *"we are not killing tournament".*** Pairwise Elo is retained (D-R9); the ties are fixed by
the round count, which measurement now confirms actually works.

> **An interaction nobody had noticed: D-R9 makes D-R11's problem WORSE.** More rounds give incumbents
> more matches, and therefore more **wins** — and wins are the *primary* sort key
> (`workshop_rank.py:1524`), with Elo only the tie-break. So every round added to cure the ties deepens
> the incumbency advantage a late-arriving candidate has to overcome. The two decisions have to be read
> together, and this is precisely why the catch-up schedule below matters: fixing D-R9 alone would
> quietly worsen the newcomer problem D-R11 exists to solve.

**Meta-review.** One call that reads every critique flaw and judge reason for the round and writes short
guidance, fed into the next generation round.

### D-R10 — the loop must DISCOVER, not only sharpen (operator, 2026-07-29)

**The defect this fixes, which nothing above had noticed.** As written, the loop *cannot produce a new
angle after round one.* Three facts combine: **orientation runs ONCE** (see the cost table — *"runs
once, not per loop round"*); a discovery question needs a real source (**"no source, no slot"**) and its
only source is orientation's `brief_conflicts`; and the mandate bracket **keeps its scope lock** (*"a
mandate question stays inside what the client asked"*). So the pool of genuinely new angles is **frozen
after round 1** — on V-01 that was **two conflicts, both about Q1** — and ten rounds buy sharper wording
of those two plus enriched rephrasings of the client's own questions. The operator's requirement is that
the loop be *"genuine discovery of angles, not a fancy rephrase of a question."* As specified, it was
the rephrase.

**The mechanism.** Evolve **may invent** an angle in any round. Before it can take a slot it passes a
**cheap grounded lookup**:

- a real source is found → it becomes a **discovery candidate**, carrying that quote and URL exactly as
  an orientation-seeded one does;
- nothing is found → **dropped, and logged as dropped.**

**"No source, no slot" is not weakened — it is enforced one step later.** The rule stops being "only
orientation may originate an angle" and becomes "only evidence may admit one", which is what the rule was
always for. New angles become reachable at **every** round instead of only the first.

Unchanged: D-W3-4's allocation still bounds what is *dispatched* — **≤5 discovery slots, per-parent cap
3, never borrows from the mandate**. D-R10 widens where candidates may *come from*, not how many run.

> ### ⚠️ MEASURED 2026-07-31 — the admission test as specified INVERTS its own purpose and must change
>
> Read as *"is there a published answer to this?"*, **"no source, no slot"** rejected **all 4 invented
> angles** in the harness run. **Zero survived.** Among the rejected was *"what minimum network density
> is required for algorithmic pricing to pay off"* — exactly the question a mid-sized player weighing
> expansion needs answered, and exactly the kind of angle D-R10 exists to admit.
>
> The rule as written admits angles that are **already documented** (already known, therefore low
> research value) and rejects **novel** ones (nobody has published it, therefore high research value).
> It is a novelty filter pointed backwards: it screens out precisely what the loop is for.
>
> **The corrected test: verify the PREMISE is real, not that an answer already exists.** Ask whether
> the named entities, markets, mechanisms and metrics **exist**, and whether desk research could
> plausibly settle the question — not whether someone has already settled it. A well-posed question
> about a real market that nobody has yet answered is the **best** possible research target, not a
> failure to admit.
>
> **The operator ruling is UNCHANGED.** The loop must DISCOVER; only the admission test changes — from
> *"only evidence may admit one, evidenced by an existing answer"* to *"only evidence may admit one,
> evidenced by a real premise"*. Nothing here loosens the requirement that evidence, not the model's
> say-so, does the admitting. The next paragraph tightens that considerably.
>
> **CRITICAL implementation note, measured.** The admission evidence must come from a **real search
> result — `groundingChunks`** — and **never** from the model's own output line. A looser check that
> accepted the model's self-reported evidence admitted **2 of 3** angles carrying a literal `-` as the
> URL: the model "evidenced" its own angle by tautologically restating that its own entities exist.
> Read the `groundingChunks` of the grounded lookup, require an http(s) URL, and treat an absent or
> non-URL source as **not found**. Without this the grounded lookup is theatre and *"no source, no
> slot"* is enforced by nothing at all.

**Open (a number, not a direction):** a ceiling on grounded lookups per round, so an evolve call that
invents twenty angles cannot spend twenty lookups. Same family as the unset spend ceiling below; decide
both together. **Measured 2026-07-31: no ceiling binds at this scale — see `### Why 10 rounds is
affordable`; instrument it rather than enforcing a guessed value.**

**This also raises the stakes on the rejected register:** with invention allowed every round, the barred
list and the `cluster_candidates` semantic drop are what stop the loop re-proposing its own rejects.

### D-R11 — Elo carries; newcomers get a CATCH-UP SCHEDULE, not a median seed

> **The "Elo carries" half STANDS unchanged.** The reasoning below for why a reset is wrong is
> untouched, and so is the ruling's intent: a late genuine angle must not be structurally last.
>
> **SUPERSEDED (measured 2026-07-31) — the MEDIAN SEED is INERT.** It is not wrong, it is a **no-op**,
> which is worse: it reads as a solved problem. The operator's intent is preserved and, for the first
> time, actually delivered — by a catch-up schedule instead of a seed value. The original rule is kept
> struck through below.
>
> **Note on the ledger.** `15.7-OPEN-ITEMS.md`'s `## RULED` section still records D-R11 in its
> median-seed form, and was deliberately left verbatim: a factual-correction pass does not edit
> operator rulings. Read **this** section as the current engineering form, and route the substitution
> to the operator when 15.7 is planned.

**Why the seed value cannot matter.** `workshop_rank.py:1524` sorts candidates by `(-wins, -elo,
index)` — **wins first, rating only as a tie-break** — and `_apply_elo`'s own docstring at
`workshop_rank.py:878` says so in as many words: **"ELO IS THE TIE-BREAK, NOT THE PRIMARY KEY"**. A
newcomer's disadvantage is that it has played fewer **matches** and therefore has fewer **wins**; its
*rating* is not what holds it down. Measured directly: median-seed and flat-1200 produce
**byte-identical** results. The rule as ruled changes no output whatsoever.

**How bad the newcomer problem actually is.** Measured with a perfect judge, 8 rounds, a newcomer
entering in round 6: a **best-in-field** newcomer reaches the top N only **1.5%** of the time. The
obvious repair — rank by raw win-*rate* instead of win-count — over-corrects hard: it admits a
**mediocre** newcomer **93.8%** of the time against a **strong** one **95.5%**, which is to say it
stops discriminating at all. Both failure modes are silent.

**The replacement rule: a new candidate plays up to the field's MEDIAN MATCH COUNT on entry.** Give the
newcomer the matches it missed, then let the existing ranking do its job unmodified. Measured, **with
the ranking code completely unchanged**:

| newcomer | reaches top N |
|---|---|
| strong | **99.8%** |
| median | **29.5%** |
| weak | **1.8%** |

That is the shape the ruling wanted: a strong late angle almost always gets in, a weak one almost never
does. Cost: about **5 extra flash judgements** — at the measured tournament price of ~$0.00 for six
flash calls, effectively free.

This is also **Co-Scientist's own approach**: *"newer and top-ranking hypotheses are prioritized for
participation in tournament matches."* The catch-up schedule is that prioritisation made explicit.

**Required test — KEPT EXACTLY AS RULED:** a strong newcomer introduced in a late round **can still
reach the top N**. **The catch-up schedule is what makes that test passable** — under median-seeding it
fails 98.5% of the time, which is the whole point of keeping the test.

#### The original D-R11 write-up (operator, 2026-07-29)

**Also previously unstated.** Today the tournament runs **once**. In this loop `rank` sits **inside** the
cycle, so it runs up to **ten times** over a population that grows every round — and nothing said what
happens to a rating between rounds. Both readings were defensible and both are wrong in a different way:
**reset** discards eight rounds of accumulated judgement every round; **carry with a fixed 1200 seed**
makes every newly evolved candidate enter *below* an incumbent field that has had rounds to climb — so
the genuinely novel angle is systematically the lowest-rated at exactly the moment slots are allocated,
which would defeat D-R10.

**The rule:** ratings **carry** across loop rounds, and ~~a new candidate enters at the **current field
median**, not at 1200. Neither punished for being new nor handed an advantage.~~
**SUPERSEDED (measured 2026-07-31) — the seed is inert; replaced by the catch-up schedule above. The
"ratings carry" half stands.**

**Required test:** a strong newcomer introduced in a late round **can still reach the top N**. Without
that assertion this is unfalsifiable, and the failure it guards against is silent — the same shape as
ranks 8/9/10 finishing at exactly 1200.0 and taking their research slots by tie order.

**Note for the round-count decision:** "every candidate plays ≥5–6 matches" must now be read as *within
one loop round*, since ratings persist across them.

### The rejected register — bar on defect, not on defeat

The operator's requirement: do not re-propose a rephrasing of something already rejected.

| Outcome | Treatment |
|---|---|
| `KILL` — *unanswerable in principle / pure opinion / nothing turns on it* | **barred this run** — it is a defect, and a reworded version has the same defect |
| `KILL` — *restatement of another candidate* | **not barred** — that is a duplicate, not a fault; the surviving twin represents it |
| `WEAK` after two evolve passes | **barred this run, kept for the next** — a real question the workshop could not sharpen |
| **Lost the tournament** | **never barred** — it was fine, it just missed the cut |

**The last row is load-bearing.** The coverage guard promotes below-the-cut candidates when a client
question ends up with no winner. **Bar losers and you break that repair path.**

Enforcement is two layers, because the prompt layer will not hold:

- **In the prompt** — the barred list travels with every generate and evolve call, each entry carrying
  *why*. "Don't propose these, and here is the flaw" beats a bare list.
- **In code** — reuse `cluster_candidates` (workshop.py:1482). Cluster each round's new candidates
  *together with* the barred ones; anything that clusters onto a barred entry is a rewording and is
  dropped. Semantic, not string matching — which is exactly what "don't rephrase it" requires.
- **Log every drop.** *"Round 2 proposed 3 questions already rejected in round 1"* is the signal that the
  loop is spinning rather than exploring.

### Exit criteria — all three, or the cap

> **MEASURED 2026-07-31: THE EXIT RULE FIRES. KEEP ALL THREE CRITERIA EXACTLY AS WRITTEN.** Boxed item
> 3 above and open item 1 of `15.7-OPEN-ITEMS.md` both assumed the loop would hit the 10-round cap on
> every run, because criterion 2 could never be satisfied. That rested entirely on *"V-01 had 9 of 10
> winners `WEAK`"* — the cap-240 truncation artefact. With the truncation fixed, **all three global
> configurations exit on all three criteria well inside the cap: exp7c in round 6, exp10 in round 9,
> exp11 in round 4.** `WEAK` winners fell **3 → 3 → 0 → 0** across the rounds, and the three criteria
> were observed to gate each other in turn rather than one of them being permanently unreachable.
> **No criterion is removed, weakened or reordered.**

1. **Coverage** — every client question has ≥1 winner rated `KEEP`
2. **Quality** — no `WEAK` question remains in the winner set (sharpened to `KEEP`, or below the cut).
   ~~*V-01 would have failed this: 9 of 10 winners were `WEAK` and it shipped anyway.*~~
   **SUPERSEDED (measured 2026-07-31)** — V-01's 9-of-10 was the truncation artefact: it reproduces
   exactly at cap 240 and becomes 2 of 10 with the cap raised. The criterion itself stands.
   **Exemption — a cross-cutting question is compound by construction.** It joins two topics *on
   purpose*, so the flaw clause *"two questions in one"* must **NOT** count against it in this check.
   Without the exemption, criterion 2 structurally penalises exactly the highest-value questions the
   discovery bracket exists to produce — the loop would be built to reject its own best output.
3. **Saturation** — the last round's newly-evolved questions produced **no new entrant into the top N**.
   This is the real "are we still learning?" test and it is what makes a 10-round cap safe.
4. **Hard cap: 10 rounds** (operator decision), plus ~~a **spend ceiling**~~ **SUPERSEDED (measured
   2026-07-31) — per-round population and spend INSTRUMENTATION instead of an enforced ceiling. Nothing
   binds at the measured scale; see `### Why 10 rounds is affordable`.**

#### The fourth action — PREFER KEEP OVER WEAK WHEN FILLING A SLOT

**The single highest-leverage rule the measurement found, and it is one line of selection logic.** Exit
criterion 2 *checks* for `WEAK` winners. Nothing anywhere in this design ever *prevented* one from being
selected in the first place — the criterion was a smoke alarm with no fire door. Adding the preference
took `WEAK` winners to **0** and made criterion 2 satisfiable **by construction** rather than by luck.

**Its dependency, which exp10-vs-exp11 exposed: prefer-KEEP only works if there are KEEP candidates
left to prefer.** That is a property of the **selection ratio** — how many candidates are generated per
slot — not of the rule itself. In exp10, five slots over six generated candidates left nothing to
prefer and the rule was inert. See `### The validated configuration` below.

> ### ⚠️ The trap the code already contains
> Two guards keep a candidate alive when critique tries to kill everything: `_reason_critique_resurrected`
> (never leave a client question with zero sub-questions) and `_reason_critique_population` (never empty
> the population). Both are **coverage fallbacks, not quality passes.** If a resurrected candidate counts
> as a `KEEP`, the loop exits believing it met the quality bar when critique actually rejected everything.
> **Mark resurrected candidates and exclude them from criterion 2.** Otherwise the exit condition silently
> lies — the same class of bug as the `ls||true` silent skip in `gate-integrity-traps`.
>
> **CORRECTED 2026-07-31 — off-by-one.** Until this commit that instruction named criterion **1**
> instead. It was wrong in a way that inverted its own purpose: criterion 1 is **coverage** and
> criterion 2 is **quality**, and excluding a resurrected candidate from *coverage* would break the very
> guarantee resurrection exists to provide — it exists precisely so a client question is never left with
> zero sub-questions. The identical error existed in `15.7-OPEN-ITEMS.md` — **the first file the 15.7
> planner is instructed to read** — and is corrected in this same commit.
>
> **Half of this guard is already built and half is missing — a Wave 4 implementation requirement.**
> `workshop_rank.py:688` sets `entry["resurrected"] = True` for Guard 1
> (`_reason_critique_resurrected`). **Guard 2 does not.** At `workshop_rank.py:708`, when critique kills
> everything, `_reason_critique_population` rewrites every candidate to `KEEP` **unmarked** — so the one
> case where quality most needs to read as *failed* reads as a perfect pass. Mark it there too, or the
> exit check still lies in the worst case it was written for.

**On hitting the cap with `WEAK` winners still present:** ship, but record a degradation reason. That
matches the engine's existing posture (D-12: degraded means honest, not broken). V-01 would have carried
*"3 of 10 winners could not be sharpened past WEAK"* — exactly what an operator wants to see.

**If the loop kills too much:** the existing guard injects the client's own question verbatim, ranked
first. Untouched.

### Why 10 rounds is affordable

> **SUPERSEDED (measured 2026-07-31) — the estimate below is far too high, and the population does not
> balloon.** The loop never reached the cap in any global configuration, and the validated
> configuration runs end-to-end for **$0.24 (exp11)**. The original estimate is kept for the record:

The loop portion — generate → critique → rank → evolve — is **~$0.07/round** measured. The redesign makes
each round richer (reasons, generative evolve, meta-review, a growing population), so call it **3–5×**:
**~$0.25–0.35/round**.

| Cap | Est. cost | % of a $53.48 run | Latency |
|---|---|---|---|
| 3 rounds | ~$0.90 | 1.7% | +~2 min |
| ~~**10 rounds**~~ | ~~**~$3.00**~~ | ~~**~5%**~~ | ~~**+5–7 min** on a 65-min run~~ |

**What was actually measured.** No global configuration reached ten rounds, and none cost anything near
$3.00. The validated configuration exits in **round 4** for **$0.24 (exp11)**; the full three-config
comparison is in `### The validated configuration` below and is not restated here as a range, because a
range across runs would hide the reason the numbers differ.

**The population does not balloon under one global loop.** Across **all three** global configurations
the population stays **between 23 and 41**, and the largest prompt the loop ever built is **~9k chars**
— measured against this section's feared *"round-9 carrying 60 candidates in every critique prompt"*.

**That fear is not wrong, though — it is misplaced. Scope it, do not delete it.** Under
**per-client-question brackets** the population **did** reach **122**. The explosion is
**architecture-dependent, not inherent**: it is a property of brackets, which the validated
configuration rejects for four other reasons anyway. If anyone ever revisits brackets, this warning
becomes live again exactly as written.

**Consequence: neither the spend ceiling nor a population cap is binding at this scale, so neither
should be enforced.** Replace both with **instrumentation** — log population and spend per round, which
Wave 5 already collects (`candidates_in, new_candidates, … round cost`). An enforced ceiling that
nobody has measured a need for is a knob that will one day truncate a run for no reason; a logged
number is what tells you whether a ceiling is ever warranted.

**The one guard that does the real work is saturation.** The cap is a ceiling, not a target, and you
will rarely reach it — **this is now CONFIRMED by measurement rather than assumed**: exp7c exited in
round 6, exp10 in round 9 and exp11 in round 4, every one of them on the criteria rather than the cap.

**If runs routinely hit 10, that is evidence the cap should go higher — not that money is being wasted.**

### The validated configuration (measured 2026-07-31)

**The three configurations measured, each figure attributed to the run that produced it.** No figure in
this document blends two runs, and none should: the span between them is not uncertainty, it is the
finding.

| run | config | generated per client question | slots | exits | cost | population |
|---|---|---|---|---|---|---|
| exp7c | global, no floor | 6 | 10 | round 6 | **$0.18** | peak **23** |
| exp10 — **`SUPERSEDED — generation defect`** | global + floor 5/question + 2 cross | 6 (**defective**) | 17 | round 9 | **$0.48** | peak **32** |
| **exp11 — ✅ THE VALIDATED CONFIGURATION** | **global + floor 5/question + 2 cross** | **12** | **17** | **round 4** | **$0.24** | **34–41, flat** |

**exp10 is a superseded run with a named defect, not an alternative result.** Its round count and its
cost are **not** the round count and cost of this design and must never be quoted as such.

**The defect, named precisely.** exp10 ran the same architecture as exp11. But the real generation
prompt states the candidate count **twice** — `Output EXACTLY 6 lines` and `<your 6 lines go here>` —
and **only the first was patched.** The prompt therefore still asked for six, and the model still
produced **6 per client question**. Against a floor of five slots per client question that is a
**5-of-6 choice: no selection at all.** The loop then needed **9 rounds and $0.48** to grind out a
clean winner set that exp11 had from round 1.

> **Wave 4 implementation requirement.** When the generation count is raised in the real prompt, **BOTH
> statements must be changed.** This is the same defect class as **CR-01 in Wave 3**, where one value
> was normalised in one place and compared in another — a single value with two authorities, only one
> of which got updated. § 8's Wave 4 verification row asserts it.

**THE FINDING: the lever is the SELECTION RATIO, not the slot count.** exp10 and exp11 differ in
exactly one thing — six generated per client question versus twelve — and they are the before/after
evidence for it:

| | exp10 — 6 generated | exp11 — 12 generated |
|---|---|---|
| the choice at a 5-slot floor | 5-of-6 — no selection | 5-of-12 — a real choice |
| prefer-KEEP | inert; no spare KEEP candidates | always has KEEP candidates available |
| winner set | ground clean over 9 rounds | clean from **round 1** |
| exits | round 9 | **round 4** |
| cost | $0.48 | **$0.24** |

**Raising the generation count halved the cost AND more than halved the rounds.** The slot count was
identical in both. Read as a range the two runs say nothing at all; read as before/after they identify
the lever — which is why house rule 6 of the correcting pass forbade the range.

**The configuration Wave 4 builds:**

- **ONE global loop, NOT per-client-question brackets.** Brackets were measured and fail on four
  counts: they never converge, they hit the 10-round cap, they cost **3–4×** more, and their population
  reaches **122**. The structural reason underneath all four: inside a single bracket, evolve cannot
  **COMBINE across client questions** — and combining across client questions is where the best output
  came from.
- **12 candidates generated per client question** — the selection ratio, the lever above.
- Winners = a **floor of 5 per client question** + **2 cross-cutting**, applied at the **CUT** rather
  than by splitting the pool into per-question quotas.
- **Prefer KEEP over WEAK when filling a slot** — see the exit criteria above.
- **Measured result: 17 questions, none weak, converges in round 4, $0.24** (exp11).

### Freeze and hand-off

Winner set frozen → LLM groups into ≤5 → **Python asserts** every client question is represented → dispatch.

---

## 6. Wave 5 — yield instrumentation (D-R8)

> ### ⚠️ TWO GAPS — under-specified rather than ambiguous (audit 2026-07-29)
>
> 1. **No home is named for the yield data.** This section says *what* to record and never *where*.
>    That is a schema decision, and it means **a THIRD unpaid alembic migration** joining
>    `0015 -> 0016` and `0016 -> 0017`, neither of which has ever touched a database. Decide the table
>    before planning, and budget the proof line.
> 2. **The per-assignment tuple assumes one client question.** `(provider, group_id, client_question,
>    stakes)` is correct for a mandate group under D-W3-5 — but a cross-cutting `d1` group has **no**
>    client question, and a discovery rider's assignment carries one that is not really its own.
>    Decide what those rows record before the run, not after.

Nothing today ties an assignment decision to its outcome. `audit_log` has cost and tokens but no row
says *this provider, on this question, at this stakes, in this group, yielded N parseable facts, M
surviving verification, K resolvable sources, for $X.*

Record per assignment: `(provider, group_id, client_question, stakes)` →
`(fact_list_parsed?, retry_used?, claims_kept, claims_surviving_verification, resolvable_sources, cost_usd, duration_s)`.

Record per workshop round: `candidates_in, new_candidates, KEEP/WEAK/KILL counts, new entrants into the
top N, barred-duplicate drops, round cost`.

**That last counter is the loop's entire justification.** If round 7+ never produces a new entrant across
several runs, drop the cap and keep the money. If it does, raise it. Without this, tuning is guesswork
and "smart routing" stays a hand-written map.

---

## 7. What we are deliberately NOT doing

| Not doing | Why |
|---|---|
| **Touching the verification stage** | It works: 34 settled contradictions with live re-fetching, a staleness channel, brief-conflict surfacing that reaches the report. Three of the findings doc's claims were wrong because they judged it from intermediate artifacts. **Read the delivered report (`output` row, `format='markdown'`), not the claim table or the logs.** |
| **Claim clustering for corroboration first** | Expect modest gains: only 37/396 claims have any cross-provider partner at Jaccard 0.2, and shared-source overlap is 2.9%. A single-provider topic cannot be corroborated by any matcher. Do it **last**, and never let anyone "fix" corroboration by swapping the matcher and declaring victory. |
| **Rewriting the report writer to read all research** | Still worth doing as a safety net, but it was sized against a hole the `<TAB>` fix largely closes. Reassess after one clean run. |
| **Two-wave research** (hold discovery slots, allocate after mandate research returns) | This is what Co-Scientist's supervisor does and it would produce better discovery questions — but it roughly doubles wall-clock (~2 h). Defer until orientation-seeded discovery has proven itself. |
| **Deleting rejected claims from the research text** | Only 19 of 30 are verbatim-locatable (distiller claims are **6%** verbatim vs 100% for FACTS claims). A string delete silently leaves 11 debunked claims in the corpus. **Annotate, never delete** — send a "do not assert" list instead. |
| **Provider routing by measured competence** | We have no trustworthy data — V-01's yield is contaminated by the `<TAB>` bug. Wave 5 collects it. Routing on today's numbers would encode a parser bug as a permanent judgement about gemini, whose *research* was the best in the run. |

---

## 8. Verification

**Wave 1 has a real fixture.** The two coffee audit blobs are the regression test:

```bash
gcloud storage ls "gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/7dcf51d5-1153-4374-b444-c25d17eeea01/" \
  --project=project-cb01b861-cb4a-438d-b9a | grep gemini-2.5-flash
# the four distiller calls are those written 13:46:33Z–13:48:30Z
#   e9a168b5… , fe418029…  = the two coffee calls  → must yield 278 claims
#   af1995b6… , 7dcf4a14…  = the two that worked   → must still yield 43 + 143
```

Per wave:

| Wave | Verified by |
|---|---|
| 1 | replay proof (278 recovered); all four separator forms parse identically; WARNING fires on lines-but-no-claims; all three gemini deviations retried |
| 2 | ~~a claim from a mixed group carries the sub-question's parent as `facet`~~ **SUPERSEDED — see below**; nullable columns leave legacy rows untouched ✅ |
| 3 | coverage assertion catches a deliberately dropped client question ✅; group-size cap holds ✅; ~~5×3 = 15 calls issued~~ **now a band of 9–15, see below** |
| 4 | loop exits on saturation before the cap *(measured: exp11 exits in round 4)*; **a resurrected candidate does not satisfy QUALITY — criterion 2. CORRECTED 2026-07-31: this row previously said "coverage", the same off-by-one § 5's boxed warning carried. Guard 2 at `workshop_rank.py:708` must MARK resurrected candidates, which today it does not**; barred questions do not reappear; losers remain promotable; **a strong newcomer entering in a late round still reaches the top N under the catch-up schedule**; **zero `WEAK` winners — prefer-KEEP is applied when filling a slot**; **the raised generation count appears in BOTH places the prompt states it (`Output EXACTLY 6 lines` and the `<your N lines go here>` placeholder), asserted in the same test** |
| 5 | one run produces a complete yield record per assignment and per round |

> ### ⚠️ TWO ROWS ABOVE ARE STALE — read before ticking anything at 15.8
>
> Recorded 2026-07-29 after an audit of this document for grouping-class ambiguities. **Do not tick
> either strikethrough item; they describe a world operator decision D-W3-5 removed.**
>
> **Wave 2's mixed-group test cannot be run, and that is correct.** D-W3-5 (`15.6-CONTEXT.md`) ruled
> **mandate-strict**: a mandate group holds exactly one client question unless there are more than 5 of
> them. So mixed groups are the rare forced case, not the norm, and `claim_attribution.resolved_facet`
> is deliberately left with **no production caller** — under mandate-strict the group's parent already
> IS every mandate claim's correct facet, and on a cross-cutting `d1` group the resolver would return
> `__discovery__`, which is not a valid facet for `_propagate_stakes` or any report section. Wave 2
> shipped correctly and is gate-verified; only this checklist row is wrong.
>
> **Wave 3 issues 9–15 calls, not 15.** D-W3-1 made 5 groups a **hard ceiling, not a target** (fewer is
> expected on a simple brief), and D-W3-5 lets a discovery question ride in its parent's mandate group
> so discovery usually consumes **no slot at all**. V-01's three client questions land at **9–12**.
> The plans assert the band deliberately — a fixed number would pin the wrong thing.

**Then one clean run.** Compare against V-01 on: claims kept, coffee claims > 0, `WEAK` winners in the
final set, calls issued, total cost, wall-clock. Use `NESTOR_TRIBUNAL_WORKSHOP_TOURNAMENT=false` (ranks
by index, zero LLM calls) as the A/B control for the loop's value.

---

## 9. Environment knobs

Existing: `NESTOR_TRIBUNAL_WORKSHOP_ROUNDS` (4), `NESTOR_TRIBUNAL_WORKSHOP_RANK_MODEL`
(gemini-2.5-flash), `NESTOR_TRIBUNAL_WORKSHOP_EVOLVE_MODEL` (claude-sonnet-4-6),
`NESTOR_TRIBUNAL_WORKSHOP_WINNERS_MIN/MAX` (10/15), `NESTOR_TRIBUNAL_D6_TOP_K` (3),
`NESTOR_TRIBUNAL_D6_MAX_WINNERS` (15), `NESTOR_TRIBUNAL_MAX_ANGLES` (28),
`NESTOR_DISTILLER_CHUNK_CHARS` (60000), `NESTOR_DISTILLER_CONCURRENCY` (4),
`NESTOR_TRIBUNAL_WORKSHOP_TOURNAMENT`, `NESTOR_TRIBUNAL_UNCAPPED`.

New: max groups (default **5**), max questions per group, discovery slot cap, discovery per-parent cap,
loop max rounds (**10**), ~~loop spend ceiling~~ **loop spend + population INSTRUMENTATION — measured
2026-07-31: nothing binds at this scale, so log per-round population and spend instead of enforcing a
guessed ceiling (§ 5 `### Why 10 rounds is affordable`)**, **candidates generated per client question
(default 12 — the selection ratio, the lever § 5 identifies; raising it requires changing BOTH places
the generation prompt states the count)**, **newcomer catch-up match budget (default: up to the
field's median match count, ≈5 extra flash judgements)**, **candidate prompt-truncation cap (today
`_CANDIDATE_PROMPT_CHARS = 240`, which truncated 17 of 18 real candidates mid-word — it is a real
injection bound and must keep *a* value, just not 240)**, provider list (default **gemini, openai,
claude** — `own` excluded per D-R5).

**Note (Q3):** the question caps are the **wallet**, not a quality setting — the code says so: *"the
budget governor is inert by decision (`NESTOR_TRIBUNAL_UNCAPPED=1`), so the angle count is the only real
spend control this engine has left."* Re-enabling the governor (deferred in 16-CONTEXT D-02, due by
Phase 20) would free the caps to be set for quality.

---

## 10. Open items not in this plan

Still owed, unrelated to the engine:

- The operator's **no-engine-behaviour-change attestation** (the D-03 gate — a person must write it)
- Phase 15.3 plan 09's two operator checkpoints (now testable against run `7dcf51d5`)
- The D-L elapsed-clock check
- **Rotate `Nestor_Claude_Temp`** — it transited a chat in plaintext on 2026-07-27 and is still live on
  both Tribunal services
- Decide the `serviceAccountTokenCreator` grant on `nestor-run@` (revoke or record)
- Art. 12 audit trail deadline: **2026-08-02**

Unresolved from the findings doc, worth answering during Wave 1:

- Is **396 persisted vs 426 distilled vs 293 kept** reconcilable? A `rejected_claims` output (9,189
  chars) probably explains it; never verified.
- **`gate_errors: 153`** — a third of the selected set errored in the gates and nothing surfaced it.
  Not investigated.
- **175 of 396 claims carry `null` certainty** (the distiller path). Is a claim with no provider-stated
  certainty acceptable in a client report?
