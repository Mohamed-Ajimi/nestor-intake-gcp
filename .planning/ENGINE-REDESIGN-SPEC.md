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
| **D-R9** | **Q1 resolved: keep the tournament and make it real.** It earns its cost only because D-R7 gives it genuinely different ideas to rank | agreed |

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

### What is wrong today, precisely

| | Co-Scientist | Ours |
|---|---|---|
| What is ranked | novel hypotheses it invented | **rewordings of client questions** |
| Judge output | simulated debate, with reasoning | literally `3 | A` — **one letter, no reason** |
| Evolution | *"refines, **combines**, builds upon"* | *"Do NOT merge two questions into one, and do NOT broaden one"* |
| Feedback | meta-review → generation | **none** |
| Iterations | many | **one** |

And the measured symptoms: **9 of 10 winners flagged `WEAK` by our own critic, 0 killed**; ranks 8, 9
and 10 tied at **Elo exactly 1200.0** with 2 wins each — they finished where they started and took their
research slots by tie order.

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

**Fix the arithmetic.** `_TOURNAMENT_ROUNDS = 4` over 17 candidates cannot separate them — hence the
1200.0 ties. Either raise rounds so every candidate plays ≥5–6 matches, **or** — better at our size —
replace pairwise Elo with a **ranked list with reasons in one call**, then a run-off among the top group.
Cheaper, more consistent, no ties.

**Meta-review.** One call that reads every critique flaw and judge reason for the round and writes short
guidance, fed into the next generation round.

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

1. **Coverage** — every client question has ≥1 winner rated `KEEP`
2. **Quality** — no `WEAK` question remains in the winner set (sharpened to `KEEP`, or below the cut).
   *V-01 would have failed this: 9 of 10 winners were `WEAK` and it shipped anyway.*
3. **Saturation** — the last round's newly-evolved questions produced **no new entrant into the top N**.
   This is the real "are we still learning?" test and it is what makes a 10-round cap safe.
4. **Hard cap: 10 rounds** (operator decision), plus a **spend ceiling**.

> ### ⚠️ The trap the code already contains
> Two guards keep a candidate alive when critique tries to kill everything: `_reason_critique_resurrected`
> (never leave a client question with zero sub-questions) and `_reason_critique_population` (never empty
> the population). Both are **coverage fallbacks, not quality passes.** If a resurrected candidate counts
> as a `KEEP`, the loop exits believing it met the quality bar when critique actually rejected everything.
> **Mark resurrected candidates and exclude them from criterion 1.** Otherwise the exit condition silently
> lies — the same class of bug as the `ls||true` silent skip in `gate-integrity-traps`.

**On hitting the cap with `WEAK` winners still present:** ship, but record a degradation reason. That
matches the engine's existing posture (D-12: degraded means honest, not broken). V-01 would have carried
*"3 of 10 winners could not be sharpened past WEAK"* — exactly what an operator wants to see.

**If the loop kills too much:** the existing guard injects the client's own question verbatim, ranked
first. Untouched.

### Why 10 rounds is affordable

The loop portion — generate → critique → rank → evolve — is **~$0.07/round** measured. The redesign makes
each round richer (reasons, generative evolve, meta-review, a growing population), so call it **3–5×**:
**~$0.25–0.35/round**.

| Cap | Est. cost | % of a $53.48 run | Latency |
|---|---|---|---|
| 3 rounds | ~$0.90 | 1.7% | +~2 min |
| **10 rounds** | **~$3.00** | **~5%** | **+5–7 min** on a 65-min run |

**Two guards make 10 safe rather than reckless.** The saturation exit does the real work — the cap is a
ceiling, not a target, and you will rarely reach it. The **spend ceiling** is the second backstop,
because the population grows each round: a round-9 carrying 60 candidates in every critique prompt is the
one shape that could surprise you, and a round-count cap alone does not bound it.

**If runs routinely hit 10, that is evidence the cap should go higher — not that money is being wasted.**

### Freeze and hand-off

Winner set frozen → LLM groups into ≤5 → **Python asserts** every client question is represented → dispatch.

---

## 6. Wave 5 — yield instrumentation (D-R8)

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
| 2 | a claim from a mixed group carries the sub-question's parent as `facet`; nullable columns leave legacy rows untouched |
| 3 | coverage assertion catches a deliberately dropped client question; group-size cap holds; 5×3 = 15 calls issued |
| 4 | loop exits on saturation before the cap; a resurrected candidate does **not** satisfy coverage; barred questions do not reappear; losers remain promotable |
| 5 | one run produces a complete yield record per assignment and per round |

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
loop max rounds (**10**), loop spend ceiling, provider list (default **gemini, openai, claude** — `own`
excluded per D-R5).

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
