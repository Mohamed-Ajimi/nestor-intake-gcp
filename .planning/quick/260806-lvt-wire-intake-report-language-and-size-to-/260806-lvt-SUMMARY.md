---
quick_id: 260806-lvt
slug: wire-intake-report-language-and-size-to-
date: 2026-08-06
status: complete
commits: [39fec86, 1de2346, 911318c]
deployed: false
---

# Quick 260806-lvt — SUMMARY

**Three atomic commits on `master`. Built, gate-green, NOT deployed.**

| # | Commit | What |
|---|---|---|
| 1 | `39fec86` | Ask for a report language; read the size the client picked; emit `[REPORT]` |
| 2 | `1de2346` | Parse `[REPORT]`; warn out loud when no language is stated |
| 3 | `911318c` | Bind the language, flip the `report_spec` off switch, teach it `pages` |

## What was actually wrong

Both measured from run `368ff3a0`'s GCS audit blobs (`request.query`, untruncated), not inferred.

1. **`mission_brief["language"]` was empty on every call.** All five dispatch assignments read carry
   `"Report all findings in the language of the assignment above."` — a branch that fires only when
   the value is empty. The same value feeds `_language_directive`, so **every writing step also took
   its weak branch**: the strong *"Write EVERYTHING in {lang} and ONLY {lang} … Never mix languages"*
   directive has never fired in production. `adaptive_intake` was its only producer; D-03 unwired it.
2. **`output_size` was read by nothing.** Report length was proxied off `question_count > 8`, and
   `pipeline.py`'s zero-touch path hardcoded `report_spec=None`, so the
   `REPORT SHAPING (client-chosen — honor these)` block the engine already knew how to emit reached
   zero prompts. `368ff3a0` delivered **356,352 chars** against a form whose largest option offers
   *"approx. 10-20 pages"* and whose help text reads *"Dikker ≠ beter."*

## Verification

| Suite | Base | After | Delta |
|---|---|---|---|
| Engine gate, real 44-file `WANTED` list | 1850 passed / 13 skipped | **1869 passed / 0 failed / 13 skipped** | **+19 = 11 + 8, exactly the new tests** |
| Backend (`--continue-on-collection-errors`) | 8 failed / 127 passed / 30 skipped / 44 errors | **8 failed / 137 passed** / 30 skipped / 44 errors | **+10, exactly the new tests** |

- The 6 engine errors are the Windows `PYTEST_CURRENT_TEST` 32767-char limit; the backend
  failures/errors are missing `pgvector` and no local DB. **Both proven pre-existing by re-running
  at the base commit**, not assumed.
- `test_research_brief.py` alone: 21 passed, **0 skipped** — the `importorskip` resolved, so these
  ran rather than silently skipping.

### Three RED proofs, all taken against the pre-change code

1. **Drift guard** — flipping `compact` to `3-6`:
   `AssertionError: compact: the nl label "Compact — ca. 2-5 pagina's" does not contain the mapped
   page range '3-6' — the form and the writer now disagree`
2. **Pages-only (the standard tier)** — `assert 'LENGTH: Target length: approximately 5-10 pages.' in ''`
   — **an empty string is the old behaviour, and that empty string is the finding**: without the
   conditional `LENGTH:` prefix the entire standard tier would have been silently inert.
3. **Comprehensive + pages** — went red in the same run, confirming the target is ADDITIVE to the
   adjective rather than replacing it.

## Deviations from the plan (both caught by reading, not assumed)

1. **⛔ Engine tests moved from `test_synthesize_report.py` to `test_report_sections.py`.** The plan
   named the former. It is **not in `cloudbuild.test-engine.yaml`'s `WANTED` list**, so tests written
   there would never run in the gate — the exact silent skip that config's preamble exists to
   prevent. Found by extracting the real 44-file list rather than trusting the filename.
2. **`_radio_answer` was not in the plan and is not optional.** `FieldRenderer` stores an
   `allow_text` radio as `{"choice", "text"}` and a plain radio as a bare string.
   `_first_nonempty` would `str()` the dict into its repr, match no key of `_OUTPUT_SIZE_SPEC`, and
   report the client's answer as **unset** — silently, with no error anywhere.

## Operator ruling, kept verbatim

`output_size` maps to **BOTH** a keyword and a page range. Collapsing to `brief`/`comprehensive`
alone was explicitly rejected.

| answer | `length` | `pages` |
|---|---|---|
| compact | `brief` | `2-5` |
| standard | *(none)* | `5-10` |
| extended | `comprehensive` | `10-20` |
| other | *(none)* | *(none)* — the client's own text to `instructions` |

## ⚠ Carried forward

- **THIS BREAKS OUTPUT COMPARABILITY WITH RUN `368ff3a0`.** Same class as the parked
  `_GATE_DECISION_CONTEXT_CHARS` ruling. Accepted because the current behaviour is a defect, not a
  baseline — but it is recorded, not assumed harmless.
- **NOT DEPLOYED.** It joins the Opus 5 synthesis change (`74cdf94`/`5e6425c`/`70f9f11`) as
  committed-but-unbuilt. One rebuild covers both, and that rebuild voids the 15.8 digest baseline
  and forces all five pre-flight gates to re-run.
- **The page target is a TARGET, NOT A CAP.** The hard ceiling on length is the per-section token
  budget × one section per client question — that is what produced 356,352 chars. Untouched here.
  If reports still overshoot after this, that is the next lever and a separate change.
- **`derive_report_hint`'s prose tail was deliberately KEPT.** It carries structuring hints the block
  does not model (per-sector structure, goals-as-sections). Retiring it is its own decision.
- **Frontend preselection of the language radio from the active i18n locale was NOT done.** The
  field is `required`, so nothing silently defaults. Follow-up if wanted.
- **`output_form` (Notion / PDF / other) is still read by nothing.** Same four touch points if you
  want it wired; out of scope here.

## Untouched, deliberately

`_LABEL_MAX_CHARS`, `_GATE_DECISION_CONTEXT_CHARS`, `_QUESTION_MAX_CHARS`, `_DECISION_MAX_CHARS`,
`cloudbuild.test-engine.yaml` (`EXPECTED_FILES` stays **44**; no new test file was created).
