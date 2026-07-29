# V-01 diagnostics — the two questions that gated the engine fix

Run `7dcf51d5-1153-4374-b444-c25d17eeea01`, 2026-07-28. Answers to the two diagnostics
that [`engine-fix-sequence-post-v01`] made prerequisites for designing anything.
Companion to [`run-20260728-7dcf51d5-V01-FINDINGS.md`](run-20260728-7dcf51d5-V01-FINDINGS.md).

**Both are answered, and both answers overturn what the findings document assumed.**

| | Prior hypothesis | Established cause |
|---|---|---|
| 1a — gemini omitted the `FACTS` block | truncation (the reports were long) | **format drift.** Truncation is impossible — proven below |
| 1b — the distiller returned zero coffee claims | facet-label mismatch / weak extraction | **a literal `<TAB>` separator.** 278 well-formed claims were parsed away |

Evidence source: the per-call audit blobs in
`gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/7dcf51d5-…/`, which store the full
request **and response** of every LLM call, plus `research.json` (the raw pre-strip research
checkpoint) and the worker's Cloud Logging trail.

---

## Diagnostic 1a — the FACTS block: format drift, NOT truncation

**Answer: gemini simply did not emit the block on 2 of 5 reports. Nothing was cut off.**

### The measurement that settles it

All five gemini reports, raw (as stored before `strip_fact_block`):

| idx | stakes | angle | raw chars | cleaned | `FACTS` block | outcome |
|---|---|---|---|---|---|---|
| 0 | high | dynamic pricing | 46,192 | 27,055 | **yes** | 7 facts parsed |
| 4 | high | convenience | 88,428 | 40,094 | **yes** | 20 facts, every `SOURCE_URL` rejected |
| 8 | high | dynamic pricing | 88,135 | 46,984 | **yes** | 4 lines, **none parsed** → D-14 |
| 12 | med | coffee | 40,488 | 21,386 | **no** | → D-14 |
| 16 | low | coffee | 57,660 | 22,774 | **no** | → D-14 |

**Three independent facts each rule out truncation:**

1. **The two longest reports (88,428 and 88,135 chars) both carry a complete block.** The two
   that lost it are 40,488 and 57,660 — ranks 5 and 3 of 5 by length. On *cleaned* length they
   are the two **shortest**. There is no length ceiling here to hit.
2. **The block is not at the end of the output.** In all three reports that have one, the order
   is prose → `FACTS` block → `NOT_FOUND` block → bibliography, with **9,129 / 15,208 / 13,725
   characters following `FACTS_END`**. A truncated response loses its tail — it cannot lose a
   middle section and keep the bibliography.
3. **The failing reports end cleanly.** Both terminate with a complete, numbered bibliography
   (last entries 28 and 63) and a trailing newline — byte-for-byte the same ending shape as the
   successful ones. Nothing is severed.

Corroborating: the same `finish_reason: "STOP"` appears on every gemini call inspected, and
`_d8_prompted` is `true` for all five — the instruction was sent every time.

### Why it happens

This is a known, already-documented compliance problem with this provider.
`research_division.py:348` records that gemini "honoured [the block] on **0 of 8 reports**"
before plan 15.2-23 added a REQUIRED-OUTPUT lead-in for it, while claude and openai — which
receive a byte-identical block — honoured theirs. On V-01 gemini honoured it **3 of 5**. The
lead-in improved compliance; it did not make it deterministic.

Secondary observation, offered as a lead and not a conclusion: the three that complied were all
`stakes=high` and the two that did not were `med` and `low`. `_with_fact_list_block()` does not
take stakes and the block content is provider-derived only, so this is **not** a prompt-variant
bug. With n=5 it may be coincidence. Worth re-measuring on the next run.

### What this decides

- **The fix is retry-on-missing-block** (re-ask the same provider for the fact list over its own
  report), plus a stricter required-output framing — **not** chunked extraction.
- **⛔ THE Q4 GATE IS CLEARED.** Grouping per client question makes reports longer, and length was
  the suspected cause. It is not. An 88k-char gemini report emitted a complete, parseable block.
  **Q4 is safe to ship on this evidence.**

### A related defect worth fixing in the same pass

Two of the three D-14 fallbacks were **not** caused by a missing block at all:

- **idx 8** emitted a block whose every line began with a literal `STATEMENT` column
  (`STATEMENT<TAB>Tamoil Nederland uses PriceCast Fuel…`), shifting every field one place. The
  claim text landed in the `SOURCE_URL` slot, failed the http(s) check, and all 4 lines were
  ignored. Its claims were also written in **English** while its report is Dutch.
- **idx 4** emitted a well-formed 20-line block whose `SOURCE_URL` column was the `[cite: N]`
  marker rather than a URL — the ~20 `rejecting non-http(s) SOURCE_URL '[cite: 25, 26]'` warnings
  in the trail. The facts survived; **their sources did not**.

So gemini's fact-list failures are three distinct format deviations, not one. A retry that only
covers "block absent" would still have missed idx 8 and would still have dropped idx 4's sources.

> **Correction to the findings document.** D-V01-9 attributes the "block present but not one line
> parsed (4 line(s) ignored)" case to **r2 / idx 4**. The 4-line block is **idx 8**; idx 4 is the
> 20-line `[cite: N]` case. The claim attribution below confirms the swap: 172 of the 175
> distiller claims trace textually to idx 8, which the document lists as "usable".

---

## Diagnostic 1b — the coffee claims were extracted, then thrown away by a separator mismatch

**Answer: the distiller worked. It returned 278 well-formed, evidence-bearing coffee claims.
The parser discarded every one of them because the model wrote the literal five-character
string `<TAB>` where a tab character was required — and the only log line for that is
`log.debug`, which production discards entirely.**

### The evidence

`collect_provider_facts` sends one `claim_distiller` call over all fallback reports
(`steps.py:2039`); `claim_distiller` splits each report into ≤60k-char chunks and issues one
gemini-2.5-flash call per chunk. On this run that is exactly **4 calls**, all four recoverable
from the audit bucket:

| audit id | at | report | `finish_reason` | output tokens | lines returned | lines with a real TAB | claims kept |
|---|---|---|---|---|---|---|---|
| `af1995b6` | 13:46:57 | idx 8 (chunk 2) | STOP | 5,868 | 43 | **43** | 43 |
| `e9a168b5` | 13:47:34 | **idx 12 — coffee** | STOP | 16,343 | **141** | **0** | **0** |
| `fe418029` | 13:47:38 | **idx 16 — coffee** | STOP | 16,048 | **137** | **0** | **0** |
| `7dcf4a14` | 13:48:29 | idx 8 (chunk 1) | STOP | 31,418 | 143 | **143** | 143 |

Every call succeeded. Every call returned a large, on-topic body. The two coffee calls returned
**278 lines that are correctly structured in every respect except the separator**:

```
Hoe evolueren de koffiestrategieën van de belangrijkste petroliers in de Benelux…<TAB>Shell's
koffiestrategie is een hybride van private label en barista-concepten. <TAB>Shell (Strategie:
Hybride Private Label…
```

`_parse_distiller_response` (`steps.py:1281`) drops any line without `"\t"`:

```python
if "\t" not in line:
    log.debug("claim_distiller: skipping malformed line (no tab): %r", line[:80])
    continue
```

278 lines, 278 silent drops. Per D-V01-6 stdlib logging in the pipeline is served by Python's
`lastResort` handler at **WARNING and above**, so not one of those `debug` lines existed in
production. The run's only visible symptom was the downstream
`focus area … produced ZERO claims` warning.

### Why the model did it

The prompt describes the format using the literal token, twice (`steps.py:1237`, `1256`):

```
  - Each line MUST use this format: FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE
…
Output claims now (one per line, FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE format):
```

`<TAB>` is a *placeholder describing* a character. Two of four calls emitted U+0009; two copied
the placeholder verbatim. Same prompt, same model, same batch, same temperature 0.0 — the split
is non-deterministic. **The engine has a 50% coin-flip in its extraction contract.**

This is not an artifact of the audit serialisation: the other two responses in the same format,
from the same batch, contain real tab characters.

### What was actually lost

Splitting the discarded lines on `<TAB>` recovers **278 claims, all ≥10 chars, all three columns
populated including verbatim EVIDENCE** — i.e. they would have passed every downstream filter.
Their content is exactly the "missing" Benelux coffee material:

| | Circle K | LUKOIL | Barista | Costa | Shell Café | Illy | Lattiz | Douwe Egberts | deli2go | Perszè |
|---|---|---|---|---|---|---|---|---|---|---|
| claims | 44 | 27 | 24 | 18 | 10 | 10 | 7 | 6 | 3 | 2 |

The run persisted 396 claims. These 278 would have been the largest single contribution to the
run and would have made coffee the best-covered client question rather than the worst.

**This is the true origin of the report's false evidence-gap statement.** The delivered coffee
section tells the client the Benelux data *"geeft geen volledig beeld"* — the engine had 278
claims about exactly that, extracted and structured, and dropped them on a string comparison.

### What this decides

The primary fix is **not** "the writer must read the research". It is three lines of parser and
prompt hygiene:

1. **Accept the literal `<TAB>` (and `\t`, `|`, multi-space) as separators** in
   `_parse_distiller_response` — defensive, costs nothing, recovers 100% of this loss.
2. **Stop putting a literal `<TAB>` placeholder in the prompt.** Use a real tab in the example, or
   switch the contract to an unambiguous delimiter such as ` ||| ` that cannot be "described".
3. **Make the drop loud.** A unit that returns >0 lines and yields 0 claims must log at WARNING
   with the first offending line — the single line that would have caught this on day one. And
   fix D-V01-6's inert stdlib logging, or WARNING is the only level anyone ever sees.

### The ZERO-claims warning is not trustworthy either

The run logged `produced ZERO claims — unverified topic` for **two** focus areas: coffee **and**
convenience. The convenience one is a **false alarm** — that report (idx 4) parsed its fact list
successfully and was never in this distiller call at all. The warning at `steps.py:1578` iterates
every focus area in the mission brief and reports zero for any label absent from *this call's*
output, regardless of whether that focus area was in scope for the call. It should be scoped to
the facets actually present in the call's inputs, or it will keep crying wolf while the real
zero sits next to it.

---

## Consequences for the fix sequence

1. **The "~89% lost at extraction" figure needs restating.** For the two coffee reports the loss
   was not extraction — it was a separator. Extraction produced 278 claims from 98,148 chars of
   research. The funnel's headline number conflates a parser bug with a capability limit.
2. **Reorder the phase.** The `<TAB>` fix and the retry-on-missing-block are small, contained, and
   recover more value than anything else on the list. "Writer reads the research" remains worth
   doing as a safety net, but it is no longer the top item — it was sized against a hole that this
   fix mostly closes.
3. **Q4 is unblocked** (see 1a).
4. **Neither diagnostic supports the `corroboration_key` theory of the coffee loss.** The facet
   labels were correct in all 278 discarded lines. `corroboration_key` is still wanted for
   D-V01-5's own reasons; it was not the cause here.

## Reproduction

```bash
gcloud storage ls "gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/7dcf51d5-1153-4374-b444-c25d17eeea01/" \
  --project=project-cb01b861-cb4a-438d-b9a | grep gemini-2.5-flash
# the four distiller calls are those written 13:46:33Z–13:48:30Z
# response.candidates[0].content.parts[0].text carries the returned lines
```

The 225 resolved citations for this run are preserved in
[`run-20260728-7dcf51d5-CITATIONS.tsv`](run-20260728-7dcf51d5-CITATIONS.tsv) — the redirects
themselves die around late August 2026.
