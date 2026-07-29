# V-01 open questions — the three numbers nobody had explained

Run `7dcf51d5-1153-4374-b444-c25d17eeea01`, 2026-07-28. Answers to the three questions
`.planning/ENGINE-REDESIGN-SPEC.md` § 10 parks as "worth answering during Wave 1", written while the
run's artifacts are still readable.

Companion to [`run-20260728-7dcf51d5-DIAGNOSTICS.md`](run-20260728-7dcf51d5-DIAGNOSTICS.md) (the two
gating diagnostics) and [`run-20260728-7dcf51d5-V01-FINDINGS.md`](run-20260728-7dcf51d5-V01-FINDINGS.md)
(full forensics — superseded by DIAGNOSTICS and the spec where they disagree). Same evidence chain:
the per-call audit blobs in
`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/7dcf51d5-1153-4374-b444-c25d17eeea01/`,
which hold the full request and response of all 415 LLM calls.

**This document changed no engine code.** Every finding below carries an explicit in-scope /
out-of-scope call. Nothing here entered Wave 1.

| | Question | Answer | Scope call |
|---|---|---|---|
| 1 | Is 396 / 426 / 293 reconcilable? | **Yes, exactly. Residual 0.** 426 = 396 + 27 + 3 | Nothing to fix |
| 2 | What is `gate_errors: 153`? | **A response-format rejection, all 153 in gate 1.** 43 explicit DROPs were heard as KEEP | Fix proposed, **out of scope** |
| 3 | Are null-certainty claims acceptable in a client report? | `certainty` **never reaches the report writer** — null is indistinguishable from `certain` | **(b)** out of scope; operator decision |

**Method note.** Everything below marked *measured* was recomputed from the audit blobs with a
stdlib-only Python, by lifting the production parser's own rules. Nothing was taken from the earlier
forensics on trust. Where a number could not be measured it says so.

---

## Question 1 — the claim funnel reconciles exactly

**Answer: 426 distilled − 27 refuted − 3 conflict losers = 396 persisted. The residual is zero.**
`293` is not on that line at all: it is the gate-*kept* count, a different cut of the same 426.

```
                 426  distilled          (input to apply_gates)
                  │
   ┌──────────────┴──────────────┐        GATE STAGE — selects what gets checked
 293 kept                      133 dropped   (112 not_load_bearing + 21 not_falsifiable)
   │  = 293 selected_verify
   │    + 0 skipped_stable
   └──────────────┬──────────────┘
                  │                        Both branches stay in `claims` and are adjudicated.
                 426  adjudicated
                  │
   ┌──────────────┴──────────────┐        ADJUDICATION + CONFLICT — removes what was disproved
 399 survivors                  27 refuted with an independent source
   │
  −3 conflict losers
   │
                 396  persisted as `claim` rows
```

### The three integers, each measured

| Number | How it was measured | Value |
|---|---|---|
| **426 distilled** | The materiality gate batches at `_GATE_BATCH = 40` (`gates.py:78`). The audit bucket holds **11** calls whose prompt starts `You are screening research claims`. Summing each call's answered index range: 10 × 40 + 26 = **426** | ✔ 426 |
| **293 gate-kept** | Gate 2 runs over the survivors only (`gates.py:453`). The bucket holds **8** calls whose prompt starts `Every claim below has already been judged worth checking`: 7 × 40 + 13 = **293** | ✔ 293 |
| **133 dropped** | 426 − 293, and it matches the recorded reasons `not_load_bearing 112 + not_falsifiable 21 = 133` (V01-FINDINGS line 42) | ✔ 133 |
| **27 refuted** | 255 audit blobs carry an `emit_group_verdict` tool call. Extracting every verdict and keying it to the claim text in the same call's prompt yields **302 distinct claims, exactly one verdict each**: `support 182 · insufficient 86 · refute 27 · superseded 7`. Replaying `adjudicate()` (`adjudicate.py:96-127`) over them — majority-refute **and** at least one refuter citing an independent source — drops **exactly 27**; all 27 refuters carried `evidence_refs` | ✔ 27 |
| **3 conflict losers** | Blob `92457a42…_google_gemini-2.5-pro.json` is the whole `conflict_detector` call. Its response is one JSON array of **5** conflicts: **3** with a non-null `loser` (survivor indices 84, 199, 349) and **2** `contested: true` (note only, no drop) — `pipeline.py:3141-3159` | ✔ 3 |
| **396 persisted** | 426 − 27 − 3. `persist_tribunal_claims` writes `claim` rows for `survivors` only; a dropped claim gets no row and only its verdict is persisted (`pipeline.py:1181-1189`) | ✔ 396 |

### The `rejected_claims` output does explain it — and its byte count agrees

`rejected_claims` is built at `pipeline.py:3166-3175` from the same `dropped` list, one entry per
claim as `{text, facet, reason}` with `reason ∈ {failed_factcheck, lost_conflict}`. So its length is
**27 + 3 = 30 entries**, which is precisely the 426 → 396 delta.

The row itself was **not read** — it lives in `output` and this investigation used no database
credentials. Its recorded size of 9,189 chars over 30 entries is 306 chars/entry, which is the right
order for a JSON object holding a ~150-char Dutch claim, a ~100-char facet label and a reason word.
That is corroboration, not proof. **What would close it:** one `SELECT length(body), body FROM output
WHERE run_id = '7dcf51d5-…' AND format = 'rejected_claims'` read as `worker_user`.

### The one residual, stated

**302 claims carry a skeptic verdict; the funnel records `checked: 293`.** The 9-claim difference is
consistent with `checked_incidentally` — the counter that exists precisely because a gate-dropped or
stable member of a *selected group* still gets a verdict, and it counts (`pipeline.py:996-1002`,
WR-10 / D-10). **It was not verified.** The gate calls' `request.contents` are truncated to 2,000
chars in the audit blob, so a claim cannot be mapped back to its gate decision from the bucket. To
close it: `SELECT checked_incidentally FROM` the run's verification funnel.

### Candidate mechanisms tested and *ruled out*

Named in the plan, checked against the data, **none of them fired between 426 and 396**:

- `_dedupe_claims` (`steps.py:1416`) — runs **before** the gates, so it is upstream of the 426. It
  does not sit on this stretch of the funnel at all.
- `_normalise_fact_claim` returning `None` → `unusable_claims` (`steps.py:1895-1920`) — also upstream
  of the 426, counted separately in the `collect_provider_facts` INFO line (`steps.py:2268-2278`).
- `_NOT_FOUND_TOTAL_MAX` (`steps.py:1735`) — caps the "could not establish" list, never claims.
- `_MAX_FACTS = 400` per provider (`facts.py:112`) — not reached; the largest single provider
  contribution was 198.
- **Gate drops** — the 133 are **not** removed from the funnel. They stay in `claims`, are adjudicated
  with everything else, and are persisted. This is the misreading the question encodes.

### Scope call — question 1

**Nothing to fix. Nothing enters this phase.** The arithmetic was always sound; what was missing was
a document saying which cut each number describes. One presentational note for a later wave (**not
Wave 1**): the V01-FINDINGS line *"Distilled 426 → selected for verification 293 → kept 293 (133
dropped)"* uses `kept` for two different things in one sentence — the gate funnel's `kept` (426 − 133)
and the verification stage's `kept`. That wording is what made the question look unanswerable.

---

## Question 2 — `gate_errors: 153` is a response-format rejection, and no operator was warned

**Answer: all 153 are in gate 1 (materiality); gate 2 produced zero. Not one is an API failure — all
11 gate calls returned `finish_reason: STOP` with a full-length answer. The model answered in a
one-column shorthand the parser requires two columns for, and every such line was rejected whole.**

### The increment site

`gates.py:492` — `funnel["gate_errors"] += 1`, once per claim whose `gate["gate_error"]` flag is set.
The flag has four possible origins:

| Origin | file:line | Logged? |
|---|---|---|
| The model's line for that index was not parseable *whole* | `gates.py:239` (`defaulted = [True] * n`) + `gates.py:258` (cleared only on a fully valid row) | **no** |
| A DROP whose reason word is unattributable → forced to KEEP | `gates.py:437-440` | **no** |
| The whole batch failed after `_GATE_RETRIES` | `gates.py:337-342` | `log.warning` |
| Gate 2's row missing or defaulted | `gates.py:466-467` | **no** |

Three of the four are silent. On this run the loss came entirely from the silent first row.

### What the model actually sent — measured, all 11 calls

| blob | finish | claims | parsed | **defaulted** | response format |
|---|---|---|---|---|---|
| `2963639d` | STOP | 40 | 0 | **40** | 1-column, all 40 lines |
| `40b4b397` | STOP | 40 | 0 | **40** | 1-column, all 40 lines |
| `268f2c49` | STOP | 40 | 11 | **29** | mixed |
| `89242192` | STOP | 40 | 15 | **25** | mixed |
| `5da04694` | STOP | 40 | 32 | **8** | mixed |
| `b66e349d` | STOP | 40 | 34 | **6** | mixed |
| `070947e9` | STOP | 40 | 35 | **5** | 2-column, wrong word in slot 1 |
| `3a698981` | STOP | 26 | 26 | 0 | 2-column |
| `4b8dee93` | STOP | 40 | 40 | 0 | 2-column |
| `e68263e4` | STOP | 40 | 40 | 0 | 2-column |
| `f829b89f` | STOP | 40 | 40 | 0 | 2-column |
| | | **426** | 273 | **153** | |

Every rejected line, by shape:

```
 110   'N | KEEP'                                     the model collapsed decision+reason to one word
  32   'N | NOT_LOAD_BEARING'                         same, on a DROP
   6   'N | NOT_FALSIFIABLE'                          same, on a DROP
   4   'N | NOT_LOAD_BEARING | NOT_LOAD_BEARING'      reason written into the DECISION slot
   1   'N | NOT_FALSIFIABLE | NOT_FALSIFIABLE'        same
 ---
 153
```

The contract at `gates.py:166` is `INDEX | KEEP|DROP | KEEP|NOT_FALSIFIABLE|NOT_LOAD_BEARING|BOTH`.
`_parse_gate_lines` requires `len(parts) >= fields + 1` (`gates.py:245`) and rejects a partially valid
row whole (`gates.py:254-256`, documented as deliberate: *"half a decision is not a decision we can
account for"*). Both rules are right. The model simply did not honour a two-column contract on 5 of
11 calls — **the same class of provider format drift as the `<TAB>` defect in
[DIAGNOSTICS](run-20260728-7dcf51d5-DIAGNOSTICS.md) § 1b, in a different stage.**

### What it cost

The default is KEEP + VERIFY (`gates.py:97`, `gates.py:100`) — G-11, fail toward more checking. So the
direction is safe. But it is not free:

- **110 of the 153** were the model saying `KEEP` in shorthand. The default matched its intent; the
  only casualty is the counter.
- **43 of the 153** were the model explicitly saying **DROP**, with a reason. Those 43 claims were
  sent to a paid skeptic session against the gate's own judgement.

Order-of-magnitude cost: 43 of 293 selected claims ≈ 15% of the verification stage. Verification is
claude-sonnet-4-6, which carried **$51.89 of the run's $53.48**. So roughly **$6–8 of this run was
spent checking claims the gate had already judged non-material.** That is an estimate from the
proportion, not a per-call measurement.

### Did anything tell a human? — the load-bearing half

**Almost. The number was displayed, in a green row, next to healthy counts, with no threshold and no
warning anywhere in the log.**

| Surface | file:line | On V-01 |
|---|---|---|
| Gate feed row | `pipeline.py:2517-2528` | **Rendered** — `"293 of 426 claims selected for checking · 133 not checkable · 0 stable facts skipped · 153 gate errors (sent for checking)"`, `status: "done"`. The frontend prints `row.name` verbatim (`ResearchRunProgress.tsx:325`) |
| Verify closing feed row | `pipeline.py:989-1002, 1014-1017` | **Rendered** — same clause appended, `status: "done"` |
| Verification report JSON | `report.py:227` | **Present** as `accounting.gate_errors: 153`. No frontend code references `gate_errors`, so whether a human sees the raw field is unknown |
| The *worded* sentence — `"153 claim(s) were sent for checking on a defaulted gate answer."` | `report.py:277` | **NEVER RENDERED.** `_degradation` returns at `report.py:256-257` when the run is not degraded, and this run's `should_have_been_checked` was 0 with `verification_degraded: false`. The sentence sits behind that early return |
| `gates.py` summary line | `gates.py:514-519` | `log.info` — **inert in production** (D-V01-6: stdlib logging in the pipeline is served by `lastResort` at WARNING and above) |
| Batch-failure warning | `gates.py:337-341` | **Never fired** — no batch failed |
| `THE VERIFICATION GATES COULD NOT RUN` | `pipeline.py:2543-2549` | **Never fired** — `log.error` only when `gate_errors >= distilled`; 153 < 426 |

So: **no log line at WARNING or above, and the one sentence written to say this out loud was
unreachable on a healthy run.** A third of the gate stage failed its contract and the operator's feed
said `done`. That is the same failure class as the `<TAB>` drop — a real loss rendered as normal —
which is why this deserves a decision now rather than a note.

### Fix proposed, and its scope call

**Three changes, all small, none in this phase.** In order of value:

1. **Accept the one-column shorthand.** In `_parse_gate_lines`, when a materiality line yields exactly
   one value: if it is `KEEP`, read `(KEEP, KEEP)`; if it is one of `_DROP_REASONS`, read
   `(DROP, <reason>)`. Also accept a reason word in slot 1 when slots 1 and 2 are equal. This is the
   exact analogue of the separator-tolerant distiller split and would have recovered **153 of 153**.
   ~15 lines plus tests.
2. **Make the drop loud.** A batch whose parsed rows are fewer than its claims must
   `log.warning(provider, n, parsed, first_offending_line[:200])`. This is the `<TAB>` lesson applied
   to the second stage that has it.
3. **Un-gate the sentence.** `report.py:268` should render the `gate_errors` sentence whenever
   `gate_errors > 0`, independently of bucket 3, and the feed row should not read `done` when a
   material fraction of the gate stage defaulted.

**OUT OF SCOPE for Wave 1.** Wave 1 is the extraction funnel — the distiller parser, the fact-list
retry, redirect resolution, and two smalls. The gates are a different stage with their own tests and
their own funnel invariants (`gates.py:494-512`), and changing gate parsing changes which claims get
paid verification — the exact kind of variable Wave 1 exists to hold still, so that the next live run
measures the `<TAB>` fix and nothing else. **Recorded for the wave that owns gate/verification work.**
Note also that spec § 7 puts *touching the verification stage* on the deliberately-not-doing list
("it works — do not touch it"); this finding is about the **gate** stage that feeds it, so it is not
covered by that prohibition, but it is adjacent enough to want the operator's ruling rather than an
executor's judgement.

---

## Question 3 — a null-certainty claim is indistinguishable from a certain one, because the report writer never sees `certainty` at all

**Answer, mechanically: `certainty` — null, `single` or `certain` — cannot influence one word of the
delivered report. It is not passed to the writer in any form.**

### Why the nulls exist (known, not re-derived)

`_normalise_fact_claim` writes `certainty = None` **unconditionally** on the `distiller_fallback`
branch (`steps.py:1941`). Its docstring at `steps.py:1903-1911` states this is a **security control,
not a default** (T-15.2-61): provider prose embeds web pages the provider chose to ingest, so a page
saying `certainty: certain` is an indirect prompt injection aimed straight at a persisted, queryable
column. **A model must not be able to state its own confidence.** That reasoning is sound and nothing
here disputes it.

On V-01 the two working distiller calls returned 43 + 143 = **186** claims (`af1995b6`, `7dcf4a14`,
both idx 8 — measured). The run records **175** null-certainty claims of 396. The 11-claim difference
is consistent with `_dedupe_claims` merges (`steps.py:1455-1522`) and was not individually verified.

### What the report does with them — measured

The writer's inputs are fixed by `synthesize_report`'s signature (`steps.py:863-874`):
`mission_brief`, `provider_reports`, `contested_notes`, `report_spec`, `anchor_ledger`,
`numbered_citations`. Following each one:

- `anchor_ledger` entries are exactly `{anchor, prefix, claim_id, text, facet}` — `anchors.py:222-230`.
- They are built from `list_run_claims`, which selects `{claim_id, text, facet, position}` —
  `numbering.py:334-341`.
- `provider_reports` is scrubbed research prose; `contested_notes` are conflict-detector notes.

**`certainty` appears in none of them.** Grepping the SDK confirms the column has a writer
(`extractor.py:318, 338-354`) and no reader outside dedupe and normalisation: it is currently a
**write-only column**. The design intent recorded at `facts.py:98-100` — an unrecognised certainty
word degrades to `single`, *"which sends the claim to the skeptics rather than waving it through"* —
is **not implemented anywhere**: gate selection is decided purely by the two LLM screens above.

So a null certainty costs nothing *relative to* a stated one, because a stated one also does nothing.

### How it reads to the client

A distiller-path claim (`certainty = NULL` by construction) and the sentence it became in the
delivered dynamic-pricing section:

> **Claim, from the distiller** (`7dcf4a14`, gemini idx 8):
> *"Middelgrote brandstofretailers in de Benelux hebben tussen 2019 en 2024 dynamische prijsstelling
> (dynamic pricing) geïmplementeerd."*
>
> **Report** (writer call `8525bafe`, the section for the dynamic-pricing client question):
> *"Middelgrote brandstofretailers hebben tussen 2019 en 2024 dynamic pricing geïmplementeerd
> `[[c:a1c41b2e]]`."*

Flat assertion, carrying a citation anchor that the post-pass renders as a numbered `[n]` reference —
**identical treatment to any `certain` claim.** No hedge, no qualifier, no distinction.

*Provenance caveat:* this quotes the report **writer's response**, the direct antecedent of the
`output` row with `format='markdown'`, read from the audit bucket. The `output` row itself was not
read (no database credentials were used). The section writer is `gemini-2.5-pro`; the run has four
such calls — three body sections (`4327f500`, `8525bafe`, `ae84cd29`) and the management summary
(`66cc8e6a`) — carrying 17 / 36 / 7 / 46 anchors respectively.

### What the operator IS told, and where

There is a real disclosure, but it is **operator-facing only, per stream, and never client-facing**.
`_fallback_note` (`steps.py:1988-1993`) produces, from integers and the provider name only:

> *"gemini returned no usable fact list for 3 of 5 research report(s) — its prose was run through the
> full-extraction distiller instead (N claims), so those claims carry no provider-stated certainty or
> source quality and the domain heuristic fills the tier (D-14). The research still reached the merge;
> nothing was dropped."*

That sentence reaches the verification report via `factlist_fallbacks` (`pipeline.py:2222-2243`). The
condition is disclosed; the claims are not marked.

### Disposition — **(b): needs a report-writer change, OUT OF SCOPE here**

Marking a claim's evidence strength in client prose is a report-writer change, and *rewriting the
report writer* is on spec § 7's deliberately-not-doing list. **Recorded for the wave that owns report
composition. No code was changed and none is proposed for Wave 1.**

The framing for the decision, since this is a product judgement and not an engineering one:

| Option | What it means | Consequence |
|---|---|---|
| **A — accept as-is** | A claim's provenance does not change how it is written; verification is the quality bar, and the operator-facing note already discloses the condition | Cheapest. But the client cannot distinguish a fact two providers corroborated from one extracted from a single provider's prose |
| **B — mark certainty in the report** | Pass `certainty` through the ledger and hedge on `single`/NULL | Low value for the effort: 44% of this run's claims would be marked NULL, and the marker would mean *"no provider volunteered a confidence word"*, not *"weaker evidence"*. Risks looking like a quality signal while carrying almost none |
| **C — mark the *verdict* instead** | Pass the skeptic verdict through and hedge on `insufficient` | **The recommendation.** The verdict is our own independent check, not a provider's self-report — the thing `certainty` was hard-nulled precisely to avoid trusting |

**Recommended: A now, C later — and A is only defensible because C exists as a follow-up.** Do not
build B.

### The adjacent finding that makes C worth scheduling — recorded, not acted on

While tracing what reaches the writer, the same trace answers a bigger question than the one asked.
Of the 302 verdicts measured on this run:

```
  support       182
  insufficient   86      <-- survives to the report, written exactly like `support`
  refute         27      <-- dropped
  superseded      7
```

`adjudicate()` drops a claim only on majority-refute-with-an-independent-source (`adjudicate.py:96-127`),
so all **86 `insufficient` claims survive**; `scrub_research` removes passages only for *discredited*
claims (`pipeline.py:3212-3218`). And since `list_run_claims` carries no verdict either, an
`insufficient` claim reads to the client exactly like a corroborated one. **Roughly 28% of what the
Tribunal checked came back "we could not establish this" and the report says so nowhere.**

That is a larger and better-grounded version of question 3, and it is **explicitly out of scope for
Wave 1** — recorded here for whichever wave takes report composition.

### One consequence to write down before the next run

The `<TAB>` fix recovers **278 claims that all arrive on the distiller path**, and every one of them
gets `certainty = None` by the same unconditional write. Today's ratio is 175/396 ≈ **44%**. After the
fix, the arithmetic (assuming those 278 survive dedupe, the gates and verification at the same rates)
lands near 453/674 ≈ **67%**. That is a projection, not a measurement. **The point is only this: the
null-certainty share is going UP, so if the answer to question 3 were ever "acceptable because it is
a minority", that reason expires with the next run.** It is not the reason recommended above.

---

## Scope summary — what entered Wave 1 as a result

**Nothing.**

| Finding | Belongs to |
|---|---|
| Funnel reconciles, 0 residual | closed; documentation only |
| `checked: 293` vs 302 verdicts — 9-claim residual | needs one DB read; no code change identified |
| Gate 1 one-column shorthand → 153 defaults, 43 DROPs heard as KEEP | a later wave owning gate/verification work |
| `gate_errors` never logged at WARNING; its sentence unreachable on a healthy run | same wave |
| Null certainty invisible to the writer | report-composition wave (spec § 7) |
| `certainty` is a write-only column; the `facts.py:98-100` intent is unimplemented | same wave |
| 86 `insufficient` claims ship unmarked | same wave — the larger question |

## Reproduction

```bash
gcloud storage ls "gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/7dcf51d5-1153-4374-b444-c25d17eeea01/" \
  --project=project-cb01b861-cb4a-438d-b9a
# gate 1  : the 11 gemini-2.5-flash calls whose request.contents starts "You are screening research claims"
# gate 2  : the  8 whose request.contents starts "Every claim below has already been judged"
# verdicts: the 255 anthropic calls carrying an `emit_group_verdict` tool_use block
# conflict: 92457a42…_google_gemini-2.5-pro.json  — one JSON array, 5 conflicts, 3 with a loser
# report  : 4327f500 / 8525bafe / ae84cd29 (body sections) + 66cc8e6a (management summary)
```

**Reads only.** No `UPDATE`, no `DELETE`, no migration, no redeploy, no database session (T-15.4-16).

**Disclosure scan (T-15.4-15).** Run over this finished document before commit:

```
grep -icE '(api[_-]?key|apikey|serpapi|x-goog-api-key|authorization|secret|AIza)'  -> 1
grep -cE  '[?&](key|token|api[_-]?key)='                                          -> 0
```

**The single hit is this document quoting its own scan pattern** — the `grep -icE '(api[_-]?key|…)'`
line four lines above. It is recorded as `1` rather than reported as `0`, because a scan whose result
was adjusted to look clean is not a scan. Verified by re-running with `-n`: line 380, no other match.

Quoted content is limited to two Dutch sentences about public fuel-retail market structure and the
gate model's own decision tokens.
