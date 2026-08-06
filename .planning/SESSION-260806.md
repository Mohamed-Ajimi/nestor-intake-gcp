# Session record — 2026-08-06

**Master `7307a77`, tree clean. Seven commits. Three services DEPLOYED at tag `20260806-175613`.**

Two quick tasks executed (`260806-lvt`, `260806-o96`), one open gap answered (**G-5**), five new
defects found, two of them fixed and shipped the same day.

---

## 1. The method that made the day possible

**The GCS audit bucket is a read surface, and the agent can read it.**

The standing position (D-W5-18) was that the yield tables have no read surface, that the only
credential-free path is a Cloud Build `--no-source` run, and that answers therefore ride in an exit
status. That is true **of the tables**. It is false of the audit bucket.

```
gcloud storage ls   gs://…-nestor-audit/runs/<run_id>/
gcloud storage cat  gs://…-nestor-audit/runs/<run_id>/<audit_id>_<provider>_<model>.json
```

Blob shape: `{run_id, audit_id, seq, provider, model, request{query}, response{status, report}}`.
**`request.query` is the FULL, untruncated assignment** — 4,882–5,000 chars on this run. It carries
the client's question, the decision, every dispatched sub-question, the search-language sentence and
the output-language directive. Read-only, no Cloud Build, no spend, ~30 seconds.

Every finding below came from it.

> ⚠ The 2,000-char audit truncation recorded in the `d6bb3aae` forensics applies to
> **`gemini-2.5-flash`** calls, NOT to the deep-research dispatch payloads.
> ⚠ `for f in $(gcloud storage ls …); do gcloud storage cat "$f" > out; done` **silently produced
> 0-byte files for 3 of 4** in one loop. Always `ls -la` after downloading — a 0-byte blob reads
> exactly like an empty audit record.

Full extraction: **`docs/tribunal-run-reports/run-20260805-368ff3a0-DISPATCH.md`**.

---

## 2. What run `368ff3a0` actually dispatched

**4 groups × 3 providers = 12 angles.** Three groups parented by a client question, one (`d1`)
parented `__discovery__` — its parent assignment is the client's decision alone, exactly as designed.

| Group | Parent | Members | Claims |
|---|---|---|---|
| Q1 — dynamic pricing | client question | **7** (at the cap) | 68 |
| Q2 — coffee | client question | **6** | 68 |
| Q3 — supermarket format | client question | **5** | 72 |
| `d1` — cross-cutting | the decision only | **1** | 33 |

**Two things this settles, by reading rather than inference:**

1. **The client's question reaches the providers in full and untruncated.** All three parents are
   complete sentences ending in a question mark. The 120-char cut was never a dispatch defect.
2. **The client's question is never itself the research task.** Every assignment reads
   *"Sub-questions to answer within this assignment"*, and the single-member group says explicitly
   *"research ONLY this sub-question."* The question is the frame; the machine-written sub-questions
   are the work. It is researched **through its parts, not directly.**

---

## 3. Five defects found. Two fixed and deployed, three open.

| # | Finding | State |
|---|---|---|
| 1 | **The run language was NEVER set.** All five dispatch assignments read carry the fallback *"Report all findings in the language of the assignment above."* — a branch that fires only when the value is empty. The same value feeds `_language_directive`, so **every writing step also took its weak branch** and the strong *"Write EVERYTHING in {lang} … Never mix languages"* directive **has never fired in production.** `adaptive_intake` was its only producer; D-03 unwired it. | ✅ **FIXED + DEPLOYED** (`260806-lvt`) |
| 2 | **The claim gate judged against half-sentences** — see G-5 below. | ✅ **FIXED + DEPLOYED** (`260806-o96`) |
| 3 | **19 members dispatched vs 15 winners recorded.** 7+6+5+1. Nothing reconciles them. | 🔴 **OPEN — G-12** |
| 4 | **A `brief_conflicts` entry was dispatched as a paid research sub-question** (coffee group, member 6) and **cut mid-URL at exactly 600 chars** (`_SUBQ_CHARS`). This IS the feature celebrated as *"fired for the first time ever"*; what it produced was a truncated statement occupying a research slot. | 🔴 **OPEN — G-13** |
| 5 | **Group 1 sits at the 7-member cap with two near-duplicates** (items 4 and 7 both ask about the same 2025 German law and the same three retailers). One of seven paid slots went to a restatement. | 🔴 **OPEN — G-15** |

**Positive findings, recorded in the same breath:**
- **No PII and no credentials** in any dispatch blob — the `d6bb3aae` incident (a personal email
  address sent to third-party providers as a research task) did **not** recur.
- All dispatch calls returned `status: success` with 39K–88K-char reports.
- The sub-questions are specific and well-formed — named competitors, named pilot sites, explicit
  date ranges, explicit *"which published data"* demands. **The decomposition is doing real work.**
- Only **1 of 2** cross-cutting slots filled — but feed event 81 shows an INVENT candidate reached
  the evidence gate and was **dropped**, so this is very likely the gate working, not a bug. It is
  unmeasurable either way because the `cross_cutting` flag is never persisted (**G-14**).

---

## 4. G-5 ANSWERED — and the answer inverted the question

**576 chars against a 1200 cap. The cap never bound** (624 spare, 52% unused), identical on all 7
gate calls. **What bound was `workshop._LABEL_MAX_CHARS = 120`**, and the gate's TEST 2 — *"does the
client's decision actually turn on this claim?"* — was answered against three questions cut mid-word.

> **The cap everyone suspected was innocent. The cap nobody suspected was the whole defect** — and it
> is the same constant behind G-10, and the same one a parked note wrongly cleared as *"safe to
> remove"*.

**Generalise: when a cap is suspected, measure what actually reaches the consumer, not the cap.**

Fixed by resolving the label to the full question on the READ path — the second time this exact
pattern has paid off (G-10 was the first) — with `_LABEL_MAX_CHARS` untouched and pinned by a test.

### ⚠ The in-series cap trap, now pinned

`pipeline._GATE_DECISION_CONTEXT_CHARS` truncates, then `gates._CONTEXT_MAX_CHARS` truncates **the
same string again**. Raising the first past the second **changes the number, produces no observable
effect, and reads as "the cap was not the problem."** Both moved to 4000 together, and a test now
pins the **relationship** rather than the values.

⚠ **THREE similarly-named caps exist**; only two moved. `pipeline._GATE_DECISION_CONTEXT_CHARS`
(4000) · `gates._CONTEXT_MAX_CHARS` (4000) · `workshop._CONTEXT_MAX_CHARS` (2000, unrelated,
untouched). **Grep by module, never by name.**

### A justification corrected rather than carried

The 1200's own comment claimed it protected *"the 4096-token gate budget"*. **That 4096 is
`max_output_tokens`** — the cap on what the model writes back. Input cannot consume an output budget.
The bound was right; the mechanism was not, and anyone sizing that constant against 4096 sized it
against the wrong number.

---

## 5. What shipped

| Commit | |
|---|---|
| `39fec86` | `lvt-01` — ask the client for a report language; read the size they picked; emit `[REPORT]` |
| `1de2346` | `lvt-02` — parse `[REPORT]`; warn out loud when no language is stated |
| `911318c` | `lvt-03` — bind the language; flip the `report_spec` off switch; teach it `pages` |
| `85c3aa9` | `o96` — feed the gate the whole question; move both caps together |
| `ee4f505` `5714498` `7307a77` | docs |

**The second off switch, found while wiring the first:** `pipeline.py`'s zero-touch path hardcoded
`report_spec=None`, so `_spec_directives` returned `""` on every seam run and the
`REPORT SHAPING (client-chosen — honor these)` block the engine **already knew how to emit** reached
zero prompts. The intake had asked *"Gewenste omvang van het rapport"* all along; the answer died on
that line. Run `368ff3a0` delivered **356,352 characters** against a form whose largest option offers
*"approx. 10-20 pages"* and whose help text reads *"Dikker ≠ beter."*

**Operator ruling, kept verbatim:** `output_size` maps to **BOTH** a keyword and a page range —
compact→`brief`+2-5 · standard→5-10 **with no keyword** · extended→`comprehensive`+10-20 ·
other→the client's own text to `instructions`, no invented range.

### Three traps caught by reading rather than assuming

1. **`test_synthesize_report.py` is NOT in the engine gate's `WANTED` list.** Tests written there
   never run in CI. Always extract the real 44-file list from the config; never trust the filename.
2. **`FieldRenderer` stores an `allow_text` radio as `{choice, text}`**, not a bare string.
   `_first_nonempty` would `str()` the dict into its repr, match no key, and report the client's
   answer as **unset** — silently.
3. **A pages-only spec previously emitted NOTHING**, so the whole `standard` tier would have been
   silently inert. RED-proved as `assert 'LENGTH: Target length: approximately 5-10 pages.' in ''`.

---

## 6. The deploy

**Three services, not two — and the standing note said two.** D-W5-16 books `nestor-api` as
CONFIRM-ONLY on the evidence that `backend/` had no commits since the last deploy. **`39fec86` made
that stale.** Skipping it would have left the engine parsing a `[REPORT]` block the backend never
emits, the form never showing the language question, and the language still empty — **the fix would
have read as deployed while being entirely inert.** Sixth inert-instrumentation near-miss in this
lineage, and the first caught by re-deriving a standing note instead of trusting it.

> **Generalise: which services a change touches is a MEASUREMENT WITH AN EXPIRY DATE, not a fact.
> Re-derive it from the diff every deploy.**

Gates green in Cloud Build **before any image was built** — engine `db8171c3` at `44 of 44`,
**1877 passed / 0 failed**; backend `05e90efa`, **299 passed / 0 failed**.
**Built digest == deployed digest verified on all three**, read off `status.imageDigest` (G-1).
Worker env read-back: `NESTOR_TRIBUNAL_UNCAPPED` is the **only** `NESTOR_TRIBUNAL_*` present, so the
new gate caps (4000/4000) and the validated Wave-4 config are the code defaults that actually run.

### ⭐ The queue check has a much cheaper form than the uncommitted recipe

**The always-on worker is its own canary.** At `minScale=1` polling every 2s, any claimable row
would ALREADY have been claimed and would be writing audit blobs. So listing the audit bucket and
taking the newest write answers *"is anything running or claimable"* **read-only, in ~30s, with no DB
credential and no Cloud Build**. Newest write was 20h stale, checked twice, the second time
immediately before the worker deploy. **Cheaper and stronger than the § 15.2.k recipe, which remains
uncommitted (G-3).**

⚠ `gcloud builds submit` streams nothing when the config logs to Cloud Logging — but
**`gcloud builds log <id>` works and is not classifier-blocked**, which is how the counts above were
read. That is the answer to *"the answers rode in exit status only."*

---

## 7. ⛔ THE NEXT MEASURED RUN IS A NEW BASELINE, NOT A COMPARISON

`260806-lvt` changed the report's **shape**. `260806-o96` changed **which claims reach paid
verification**. Comparability with `368ff3a0` is broken in **two independent dimensions**. Say so
before anyone builds a comparison table against it.

## 8. Open after today

15.8 **Task 3** browser UAT · **G-7** (deep research bills $0.00 — highest priority) ·
**G-12** 19-vs-15 · **G-13** `brief_conflicts` shape · **G-14** cross-cutting flag never persisted ·
**G-15** duplicate in the 7-cap group · **G-16** `output_form` asked and read by nothing ·
**G-3** commit the § 15.2.k recipe · revoke `logging.logWriter` on `nestor-run@` ·
**~800 commits still never pushed**.
