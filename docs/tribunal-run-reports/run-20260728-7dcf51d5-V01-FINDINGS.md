# V-01 findings — run `7dcf51d5`, 2026-07-28

The first live run on the fully deployed 15.2 + 15.3 engine. It completed cleanly. Its most
important result is a **negative** one, and it is not visible anywhere in the output: the engine's
central premise — four research streams corroborating each other — **did not operate at all**, and
could not have.

This document records what the run produced, the evidence chain for that finding, and a proposed
fix. It is the V-01 forensics counterpart to
[`run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md`](run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md).

---

## Run identity

| | |
|---|---|
| Tribunal `run_id` | `7dcf51d5-1153-4374-b444-c25d17eeea01` |
| Status | **`completed_degraded`** |
| Started → completed | 2026-07-28 13:13:45Z → 14:18:52Z (**65.1 min**) |
| `reclaim_count` | 0 · no error · `current_stage = done` |
| Engine images | worker/api/frontend `20260728-094409` · `nestor-api` `20260728-132637` |
| Subject | LUKOIL BeNeLux — dynamic pricing, coffee, convenience (the baseline brief domain) |

The `completed_degraded` label has **one** cause and it is benign: the question workshop collapsed
18 candidate sub-questions to 17 after near-duplicate clustering. `verification_degraded` is
`false`. Degraded here means honest, not broken (D-12).

---

## What the run produced

**Claims: 396.** Distilled 426 → selected for verification 293 → kept 293 (133 dropped).

| Cut | Numbers |
|---|---|
| Certainty | `certain` 60 · `single` 161 · **`null` 175** |
| Found by | gemini 198 · claude 107 · openai 74 · own 17 |
| Sources | 6,385 claim→source links across **4,301 distinct sources** |
| Claims with **no** source | **84** |
| Verification | `checked` 293 · `kept` 293 · `verify_sessions` 255 · **`gate_errors` 153** |
| | `not_load_bearing` 112 · `not_falsifiable` 21 · `unresolved_anchors` 1 |
| Cost | **$53.48** over 415 calls / 2,859,702 tokens / 266 LLM-minutes |

Cost concentration: `claude-sonnet-4-6` accounts for **$51.89 of $53.48 (97%)** across 278 calls,
plus 8.6M cached tokens.

### Tournament

17 candidates ranked, **0 killed**, 10 winners. Coverage per client question: Q1 → 4 winners,
Q2 → 3, Q3 → 3.

Two observations worth keeping:

- **9 of the 10 winners are flagged `WEAK` by the pipeline's own critic** (`assumes its own answer`,
  `two questions in one`). Only rank 1 is `KEEP`. The critic annotates but nothing acts on it —
  `killed: 0`.
- Ranks 8, 9 and 10 are tied at Elo exactly 1200.0 with 2 wins each. The tournament could not
  separate them; they won their places by tie order.

### `brief_conflicts` fired — first time observed

Two conflicts were recorded, both challenging Q1's premise that dynamic pricing is widely deployed
(OPIS: "very few do dynamic pricing where they change their prices more than once a day"; CGI:
"'dynamic' here means a smarter cadence … not frequent visible volatility"). This channel had never
reached an output before. **It still does not reach the client report** — it stops at the checkpoint.

---

## Dispatch — corroboration WAS requested

19 angles. The design deliberately sends the **top 3 ranked sub-questions to all four providers**:

| | gemini | openai | claude | own |
|---|---|---|---|---|
| Rank 1 — MTS-K price transparency (DE) | ✅ | ✅ | ✅ | ✅ |
| Rank 2 — shop concept models (NL) | ✅ | ✅ | ✅ | ✅ |
| Rank 3 — phased dynamic-pricing rollout | ✅ | ✅ | ✅ | ✅ |

Those 12 angles carry `corroboration: true` and shared keys `w01`/`w02`/`w03`. Ranks 4–10 go to one
provider each (`corroboration: false`), round-robin, at `med` then `low` stakes.

Deep-research calls actually issued: **gemini 5 async jobs** (`deep-research-max-preview-04-2026`),
**openai 5 async jobs** (`gpt-5.6-sol`), **claude 5 angles served inline** (no async API),
**own 4 angles → 15 SerpApi searches**. Two of the four `own` angles failed with
`own_researcher_no_fact_list`.

**So the dispatch side works.** Four providers were paid to answer the same three high-stakes
questions.

---

## D-V01-1 — corroboration is arithmetically impossible (blocking)

`verification_summary.both = 0`. Every one of the 396 claims has exactly one entry in `found_by`.

**Root cause.** The cross-stream merge key in `pipeline/synthesis/steps.py` (~line 1355) is the
claim's own text:

```python
norm = re.sub(r"[^a-z0-9 ]", "", (c.get("text") or "").lower())
norm = re.sub(r"\s+", " ", norm).strip()
```

Two claims merge only if they are **character-identical** after lowercasing and punctuation
stripping. Two independent LLMs writing Dutch prose never produce byte-identical sentences.

**Measured on this run: 396 claims → 396 distinct keys → 0 collisions.** `both: 0` is not a research
result; it is the only value this counter can take.

A pair it missed, both answering sub-question `w01`, which was sent to all four providers:

> **openai** — "Sinds 2013 moeten exploitanten of ondernemingen met prijsstellingsbevoegdheid iedere
> wijziging van E5-, E10- en dieselprijzen **binnen vijf minuten** elektronisch aan de MTS-K melden."
>
> **claude** — "Tankstationbeheerders zijn verplicht elke prijswijziging bij E5, E10 en Diesel
> **binnen vijf minuten** door te geven aan de MTS-K."

Same fact. Two claims. No corroboration recorded.

## D-V01-2 — even a fuzzy matcher would find little (blocking, and the harder half)

Fixing the key alone does **not** produce a corroborated report. Token-overlap (Jaccard, stopworded)
across all 78,210 claim pairs:

| Similarity | Cross-provider pairs | Same-provider pairs | Cumulative distinct claims with a cross-provider partner |
|---|---|---|---|
| ≥ 0.5 | 0 | 10 | 0 |
| ≥ 0.4 | 1 | 5 | 2 |
| ≥ 0.35 | 1 | 2 | 4 |
| ≥ 0.3 | 0 | 13 | 4 |
| ≥ 0.25 | 5 | 20 | 14 |
| ≥ 0.2 | 14 | 56 | **37 of 396** |

Even at a very loose 0.2, only 37 of 396 claims have any cross-provider partner. **Each provider
repeats itself more often than it agrees with another** (56 same-provider vs 14 cross-provider
near-duplicates at 0.2).

The providers are answering the same question with *different specifics* — each extracts different
numbers from different sources. This says the engine currently corroborates **at the wrong
granularity**: agreement between independent researchers lives at the level of *the answer to the
sub-question*, not at the level of an individual extracted sentence.

## D-V01-3 — the `own` researcher reports in the wrong language (high)

The `own` stream's claims are in **English** while gemini, claude and openai all report in **Dutch**,
despite the angle prompt instructing "Report all findings in the language of the assignment". Those
17 claims cannot lexically match anything under any matcher. Cheap to fix and it removes one
guaranteed-zero-overlap stream.

## D-V01-4 — a contradiction shipped unflagged (high)

> **gemini** — "De Haan heeft omstreeks **90 locaties** getransformeerd naar het Tony's concept."
>
> **claude** — "De Haan heeft met het Tony's-concept **zeven locaties** per 2021 uitgerold in
> Nederlandse tankstations."

Two providers disagree by more than 13×, on the same subject, from the same corroboration group.
Both entered the output as independent true statements and nothing flagged the conflict. Catching
this is what a tribunal is *for*. Note that this is a **more valuable** output than agreement, and
the current design has no channel for it.

## D-V01-5 — claims cannot be traced to their sub-question (blocking the fix)

`claim` records `facet` (the *parent client question*) but not the sub-question or
`corroboration_key`. So it is currently impossible to tell whether two claims were even answering
the same sub-question. Any clustering built today would compare claims across unrelated
sub-questions and manufacture overlap. **This is a prerequisite for D-V01-1/2**, not an optional
extra.

Observed side effect: a single typo in the focus-area text (`en/of` vs `en/or`) split one client
question into two facets, one of which holds exactly **1** claim. Facet distribution was
286 / 102 / 8 / 1.

## D-V01-6 — stage logging is inert in production (high)

D-F's fix (15.2-24) shipped but emits nothing live. `pipeline.py:199` uses
`log = logging.getLogger(__name__)` (stdlib) while `worker.py:73` uses `structlog`. Stdlib logging
has **no handler configured** in the worker, so Python's `lastResort` handler serves it — and that
fires at **WARNING and above only**. Every `log.info(...)` in the pipeline is discarded, including
every `stage_enter` / `stage_exit` / `run_stages_complete` line.

Confirmed on this run: 2 INFO lines total (`run_claimed`, `dispatch_runner`, both structlog), and
exactly one `tribunal_pipeline` line — a `DEGRADED` **warning**, which is why it got through.

`DEPLOY-RUNBOOK` § 15.2.k currently instructs the operator to diagnose the first live run using
those lines. They cannot appear. **The runbook instruction is unfollowable as written.**

## D-V01-7 — run_event rows dropped (medium)

~20 occurrences of `run_events.emit_safe: … event DROPPED, run unaffected` — `KeyError` for
`stage='deep_research' kind='agent_done'`, `TypeError` for `stage='own_research'` kinds `search` and
`agent_done`. The guard behaved correctly (the run was unaffected), but phase 15.3's feed is
missing its agent-completion lines for this run.

## D-V01-8 — `gpt-5.6-sol` is unpriced (medium)

`Unknown LLM model cost: provider='openai' model='gpt-5.6-sol' -- writing NULL cost_usd`. Five calls
carry NULL cost and `run.cost_pending` is still `true`. **$53.48 is a floor, not the final figure.**
The D-A model swap updated the dispatch path but not the cost table.

---

## Proposed fix for D-V01-1 / D-V01-2

### Principle: IDs to the model, IDs back. Claim text and sources never leave the database.

Send only `{id, text}`; return only groupings of those ids:

```json
[{"ids":["c002","c187"],"relation":"same_fact"},
 {"ids":["c044","c301"],"relation":"contradiction"},
 {"ids":["c003"],"relation":"single"}]
```

The model never sees a URL and never emits a claim, so there is nothing for it to lose, rewrite, or
invent a citation into.

### The change is a key function, not a new merge stage

Replace the `norm` expression above with "the cluster id this claim was assigned". **Everything
downstream already handles provenance correctly** and needs no change — verified in
`steps.py` ~1381–1400:

- `source_urls` are **unioned**, explicitly so a corroborating provider's link is not discarded
- `provider_quality_by_url` grades each URL by the provider that supplied it; first writer owns it
- `certainty` takes the **cautious** value (either side `single` → merged `single`)
- `found_by` accumulates providers — `claim.found_by` is already `ARRAY(Text)`, **no migration needed**

### Invariants that must be enforced (the silent-loss guard)

Every input id must appear in **exactly one** output cluster.

| Model behaviour | Required handling |
|---|---|
| id omitted | becomes a **singleton cluster** — fails safe, claim survives unmerged |
| id invented | discard |
| id in two clusters | **reject the whole response**, fall back to today's exact-match key |
| model emits claim text | ignore — surviving text chosen deterministically (first occurrence, as today) |

Log `claims_in / clusters_out / ids_missing / ids_invented` every run. A claim vanishing between the
distiller and the report is the one failure here that the output would never reveal.

### Contradictions must not merge

A `contradiction` cluster keeps its claims **separate** and raises a flag. Merging De Haan's 90 and
7 into one claim with a unioned source list would destroy the most valuable signal in the run while
making the result look better sourced.

### Sizing

All 396 claims total **~15,800 tokens** — the whole run fits in one call. Estimated **$0.15–0.20**
on Sonnet against a $53.48 run.

**Use Sonnet, not Haiku.** The task is not string similarity; it is a three-way judgment
(same fact / contradiction / merely related) in Dutch, over numbers and dates. A small model
mislabelling a contradiction as a duplicate is *worse than the current behaviour*, because it would
merge conflicting claims and hide the disagreement. The price gap at this volume is cents.

**Do not do it pairwise** — 396 claims is 78,210 pairs. Cluster over groups, not pairs.

### Keep the deterministic merge

The existing dedupe is deliberately deterministic ("Deterministic, no LLM" is in its docstring) and
it also bounds skeptic load to distinct facts. Run the LLM pass as an **additional corroboration
annotator**, not a replacement. If claim identity becomes model-decided, two runs over the same data
stop producing the same claim set — costing run-to-run comparability and weakening the audit trail
(which has a legal deadline of 2026-08-02).

### Scale note

`pgvector` **is already installed** (`plpgsql`, `pgcrypto`, `vector`). Not needed at 396 claims, but
the global 30-claim cap was removed — if a run ever yields a few thousand claims, single-call
clustering stops fitting and embeddings should pre-block candidates before the LLM sees them.

---

## Open questions

1. **Should corroboration move to answer level?** D-V01-2 suggests fact-level agreement is rare by
   nature. Comparing each provider's *answer* to sub-question `w01` may be the truer unit — with
   fact-level clustering used for citation merging only.
2. **Is 396 persisted vs 426 distilled vs 293 kept reconcilable?** The three numbers come from
   different places. A `rejected_claims` output (9,189 chars) exists and probably explains it, but
   this was not verified.
3. **`gate_errors: 153`** — a third of the selected set errored in the gates and nothing surfaced
   it. Not investigated.
4. **175 of 396 claims carry `null` certainty** (the D-14 distiller-fallback path). Is a claim with
   no provider-stated certainty acceptable in a client report?
5. **`brief_conflicts` reaches no output.** It fired for the first time here. Where should it land?
