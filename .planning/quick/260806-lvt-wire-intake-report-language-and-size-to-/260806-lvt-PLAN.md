---
quick_id: 260806-lvt
slug: wire-intake-report-language-and-size-to-
date: 2026-08-06
status: planned
mode: quick
tasks: 3
---

# Quick 260806-lvt — Wire the intake's report LANGUAGE and SIZE through to Tribunal synthesis

## Why

Both facts below were **measured this session** from run `368ff3a0`'s GCS audit blobs
(`request.query`, untruncated), not inferred.

1. **`mission_brief["language"]` is empty on every call.** All five dispatch assignments read
   carry the fallback `"Report all findings in the language of the assignment above."` — that
   branch in `_d7_language_sentence` fires only when `run_language` is empty. The same empty value
   feeds `synthesis/steps.py::_language_directive` (`steps.py:318`), so **every writing step also
   took its weak branch.** The strong instruction — *"Write EVERYTHING in {lang} and ONLY {lang} …
   Translate any source material … Never mix languages"* — has never fired in production.
   Root cause: both docstrings name `adaptive_intake` as the producer
   (`workshop_rank.py:2368`, `steps.py:313`) and that module is unwired (D-03).
   `brief_input.py`, which builds the brief today, has no language handling at all.

2. **The client's report-size answer is read by nothing.** `backend/app/research/brief.py` reads
   only `_SECTOR_FIELD_KEYS` / `_GOALS_FIELD_KEYS` / questions / decision. The `output_format`
   section's `output_size` is never read; `derive_report_hint` proxies length off
   `question_count > _MANY_QUESTIONS`. And `pipeline.py:3844-3846` — the zero-touch path — hardcodes
   `report_spec=None`, so `synthesis/steps.py::_spec_directives` (`steps.py:1068`) returns `""` on
   every seam run. **That function already emits `REPORT SHAPING (client-chosen — honor these):`
   with LENGTH / TABLES / ADDITIONAL CLIENT INSTRUCTIONS.** The feature is built and switched off.

Evidence it matters: `368ff3a0`'s delivered report is **356,352 chars** (100+ pages) while the
largest option the form offers is *"Extended — approx. 10-20 pages"*, and the form's own help text
tells the client *"Thicker ≠ better."*

## Operator design rulings (locked — do not revisit)

- **`output_size` maps to BOTH a keyword AND a page range.** Explicitly rejected: collapsing to
  `brief`/`comprehensive` alone. A number is a target the writer can visibly miss; an adjective is
  not.
  | answer | `length` | `pages` |
  |---|---|---|
  | `compact` | `brief` | `2-5` |
  | `standard` | *(none)* | `5-10` |
  | `extended` | `comprehensive` | `10-20` |
  | `other` | *(none)* | *(none)* — free text goes to `instructions` |
- **`standard` carries a page target with no keyword.** It is the default shape, so there is no
  adjective to add, but the client was still promised 5-10 pages.
- Language and size ride **one** brief block. Doing them separately means touching the same four
  files twice.
- **Never send either as prose.** `derive_report_hint`'s prose tail only nudges inference — which is
  what already happens implicitly. Both must arrive as parsed values.

## Scope guards

- **BUILD ONLY. No `gcloud`, no Cloud Build, no deploy.** The Opus 5 synthesis change
  (`74cdf94`/`5e6425c`/`70f9f11`) is already committed-but-unbuilt; any rebuild voids the 15.8
  digest baseline and forces all five pre-flight gates to re-run.
- **No new engine test files.** Engine tests go in EXISTING files (`test_brief_input.py`,
  `test_synthesize_report.py`) so `tribunal/cloudbuild.test-engine.yaml` `EXPECTED_FILES` stays
  **44** and that single-quoted `bash -c` block (no apostrophes, ever) is not touched at all.
- **`_spec_directives` with no `pages` key must stay byte-identical** — there is a back-compat test
  pinning byte-identical prompts when `report_spec` is None.
- `_LABEL_MAX_CHARS`, `_GATE_DECISION_CONTEXT_CHARS`, `_QUESTION_MAX_CHARS`, `_DECISION_MAX_CHARS`
  are **not touched**.
- Frontend preselection of the language radio from the active i18n locale is **deliberately out of
  scope** — the field is `required`, so nothing silently defaults. Noted as a follow-up.

## ⚠ Consequence the operator must carry forward

This changes what synthesis is told, so **it breaks output comparability with run `368ff3a0`.**
That is the same class as the parked `_GATE_DECISION_CONTEXT_CHARS` ruling. It is accepted here
because the current behaviour is a defect, not a baseline — but it must be recorded, not assumed
harmless.

---

## Task 1 — Backend: ask for the language, read the size, emit one block

**Files:** `backend/app/data/pulse_intake_v1.json`, `backend/app/research/brief.py`,
`backend/tests/test_research_brief.py`

**Action:**
1. Add a `report_language` radio to the `output_format` section — `nl` / `fr` / `en`,
   `required: true`, trilingual labels matching the template's existing shape.
2. In `brief.py` add, beside the existing `_*_FIELD_KEYS` constants:
   - `_REPORT_HEADER = "[REPORT]"` / `_REPORT_FOOTER = "[END REPORT]"`
   - `_OUTPUT_SIZE_SPEC` — the mapping table above, spelled once.
   - `_LANGUAGE_FIELD_KEYS` / `_OUTPUT_SIZE_FIELD_KEYS` in the same idiom as the existing key
     tuples.
3. `derive_report_spec(intake) -> dict` — pure, never raises. Returns `{}` when nothing resolves.
   `other` routes the client's free text to `instructions`.
4. `assemble_brief` emits the `[REPORT]` block **only when at least one value resolves**, between
   the decision block and the report hint. Same "never emit an empty block" rule the decision block
   already applies, and for the same reason.
5. `derive_report_hint` is **left alone** — it stays prose, it is additive, and removing it is a
   separate decision.

**Verify:** `test_research_brief.py` gains — a compact/standard/extended/other case each; a
no-answer case asserting **no** `[REPORT]` block; and the **drift guard**: read
`pulse_intake_v1.json` and assert every `output_size` option's `nl`/`fr`/`en` label contains its
mapped page range, so the promise on the form cannot diverge from the instruction to the writer.

**Done:** backend suite green; a brief assembled from a compact intake contains
`[REPORT]`, `LANGUAGE:`, `LENGTH: brief`, `PAGES: 2-5`, `[END REPORT]`.

## Task 2 — Engine read side: parse the block

**Files:** `tribunal/nestor_pulse_sdk/pipeline/tribunal/brief_input.py`,
`tribunal/nestor_pulse_sdk/tests/test_brief_input.py`

**Action:**
1. `_REPORT_HEADER` / `_REPORT_FOOTER` constants; add both to `_is_section_marker` so the block
   terminates a `[DECISION]` block correctly and never leaks into `context`.
2. `ParsedBrief` gains `language: str = ""` and `report_spec: dict = field(default_factory=dict)`.
   Defaults keep every existing construction call valid — the dataclass stays `frozen=True`.
3. Parse `KEY: value` lines inside the block in the same forward pass. Unknown keys ignored;
   a malformed block costs the block, never the parse. `parse_brief` still NEVER raises.
4. Block lines must be consumed as delimiters — they must not appear in `context`, and must not be
   mistaken for enumerated questions.

**Verify:** `test_brief_input.py` gains — a full block; a block with only `LANGUAGE`; a malformed
block (asserting `questions`/`decision` survive intact and `report_spec == {}`); and a
**no-block brief asserting `language == ""` and `report_spec == {}`**, which is the old-intake path.

**Done:** engine suite green; no new test file; `EXPECTED_FILES` still 44.

## Task 3 — Engine use side: bind it, and teach `_spec_directives` a page target

**Files:** `tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py`,
`tribunal/nestor_pulse_sdk/pipeline/synthesis/steps.py`,
`tribunal/nestor_pulse_sdk/tests/test_synthesize_report.py`

**Action:**
1. `pipeline.py` — bind `parsed.language` onto `run_language` where `parsed.decision` is already
   consumed (~`:1865`), so it flows into `mission_brief["language"]` and therefore into BOTH
   `_d7_language_sentence` (dispatch) and `_language_directive` (synthesis). Put `parsed.report_spec`
   on the mission brief in the same place.
2. `pipeline.py:3845` — replace the hardcoded `report_spec=None` with the spec read off
   `synthesis_bundle["mission_brief"]`. `None` stays the value when nothing resolved, so the
   zero-touch default is preserved exactly for old intakes.
3. **Keep the empty-language fallback reachable, and make it loud** — `log.warning` when the
   language resolves empty. Silent failure is the entire reason this survived.
4. `steps.py::_spec_directives` — optional `pages` key appended to the LENGTH line as
   `Target length: approximately {pages} pages.`, AND emit the LENGTH block when **only** `pages` is
   set (today it emits only for `brief`/`comprehensive`, so the `standard` case would silently
   produce nothing).

**Verify:** `test_synthesize_report.py` gains — `brief`+`pages`, `comprehensive`+`pages`,
`pages`-only (the standard case), and **`report_spec=None` asserted byte-identical to today**.
Plus a test that a mission brief carrying a language produces the STRONG `_language_directive`
branch and one with none still produces the weak branch.

**Done:** engine suite green at 44 files; full local run recorded in the summary with before/after
counts.

---

## Acceptance

- `Nestor\.venv\Scripts\python.exe` (3.11.9): engine gate **44 of 44 files**, backend suite green.
  Record before/after pass counts — an unchanged total means the new tests did not run.
- The 6 Windows `PYTEST_CURRENT_TEST` 32767-char errors are pre-existing at the base commit and are
  not this task's.
- Three atomic commits, one per task.
- `.planning/` is gitignored — planning artifacts need `git add -f`.
- Nothing built, nothing deployed, no `gcloud` write.
