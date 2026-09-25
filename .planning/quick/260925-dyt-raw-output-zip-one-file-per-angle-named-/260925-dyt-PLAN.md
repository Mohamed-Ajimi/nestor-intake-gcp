---
phase: quick-260925-dyt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/research/bundle.py
  - backend/tests/test_research_bundle.py
autonomous: true
requirements: [QUICK-260925-dyt]

must_haves:
  truths:
    - "Extracting a raw-output zip built from N cleaned_reports entries yields N research files — none lost to duplicate names"
    - "Each research filename names the question it answers (NN-<question-slug>-<provider>.md) and the providers of one angle share NN"
    - "Each research file opens with a short header naming its question(s) and provider, followed by the provider's report text byte-identical"
    - "research/index.md lists every research file with its question and provider, in zip order"
    - "report.md and sources.json are unchanged; no rejected-claims input exists (D-01)"
  artifacts:
    - path: "backend/app/research/bundle.py"
      provides: "build_bundle_zip with unique, question-named research entries + index.md"
      exports: ["build_bundle_zip"]
      contains: "research/index.md"
    - path: "backend/tests/test_research_bundle.py"
      provides: "Duplicate-provider / fallback / traversal / accent proofs"
      contains: "infolist"
  key_links:
    - from: "backend/app/research/bundle.py"
      to: "app.storage.keys.sanitize_filename"
      via: "every path segment (question slug AND provider) passes through the shared sanitizer"
      pattern: "sanitize_filename\\("
---

<objective>
Fix the raw-output research zip so every angle report survives extraction. Today
`build_bundle_zip` names each entry `research/<sanitize_filename(provider)>.md`. But
`cleaned_reports` holds one entry per (angle, provider), so a 15-entry bundle ends up
with only 3 unique names ("gemini"/"openai"/"claude"). Python `zipfile` writes the
duplicates with nothing more than a UserWarning, and extractors keep one file per name,
so up to 12 of 15 reports are lost. This was measured on all 13 prod bundles on 2026-09-25.

Purpose: the operator/client download must contain every angle report, each one named
after the research question it answers.
Output: a rewritten entry-naming loop in `backend/app/research/bundle.py`, an added
`research/index.md`, and new or updated tests. Backend only.

SCOPE FENCES: no tribunal changes, no frontend, no migration. No change to
`backend/app/api/research_routes.py` or `backend/app/research/run_task.py` (both call
`build_bundle_zip(report, bundle, sources)` and that signature stays the same). Existing
prod bundles are not rebuilt. No deploy.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@backend/app/research/bundle.py
@backend/tests/test_research_bundle.py

<interfaces>
From backend/app/storage/keys.py (the SHARED sanitizer; must be used, never hand-rolled, per T-09-02):
  def sanitize_filename(name: str, *, max_len: int = 200) -> str
  NFD + drop combining marks (é -> e); em/en dash -> '-'; whitespace runs -> '_';
  drops everything outside [A-Za-z0-9._-] (this removes '/', which is the traversal kill switch);
  collapses repeated '_' / '-'; strips leading/trailing '._-'; caps at max_len then
  re-strips the tail; returns "file" when nothing survives.

Current builder (backend/app/research/bundle.py):
  def build_bundle_zip(report: dict, bundle: dict, sources: list) -> bytes
  Entry order: report.md, research/*, sources.json. The research loop is
  `for name, result in (bundle.get("cleaned_reports") or [])`, where name = provider string and
  result = dict with "report" (or a non-dict, which is coerced with str()).

Shape of result (tribunal `_enriched` dict spread through scrub_research, JSON round-tripped).
Every key below is OPTIONAL, because old caches may lack all of them:
  "_angle": str             # focus_area = lead client question label; may be "general" or a long run-level prompt
  "_sub_question": str
  "_client_question": str
  "_corroboration_key": str # stable per-angle group key
  "sub_questions": list     # items may be str or dict
  "report": str             # the body, which must be written byte-identical

Callers (unchanged): backend/app/api/research_routes.py:893 and backend/app/research/run_task.py:704.
Only backend/tests/test_research_bundle.py asserts research/<x>.md entry names; grep confirmed
test_research_bundle_download.py asserts none.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Unique, question-named research entries + header + index.md in build_bundle_zip</name>
  <files>backend/app/research/bundle.py, backend/tests/test_research_bundle.py</files>
  <behavior>
    New tests in backend/tests/test_research_bundle.py. Write them first and watch them fail against the current builder:
    - test_duplicate_providers_across_angles_all_survive: 3 angles x ["gemini","openai","claude"] (9 entries, each result a dict with distinct "_angle", "_corroboration_key" and a unique "report" text). Assert (a) `[i.filename for i in zf.infolist()]` has no duplicates; (b) the count of names starting with "research/", excluding "research/index.md", is 9, and "research/index.md" is present; (c) for each input, exactly one research entry's bytes endswith the original report text encoded UTF-8, and the body after the header separator equals it byte-identical; (d) the names are "research/01-<slug1>-gemini.md", "research/01-<slug1>-openai.md", "research/01-<slug1>-claude.md", "research/02-<slug2>-gemini.md" and so on, with the slug = sanitize_filename(angle, max_len=60).
    - test_grouping_prefers_corroboration_key: two entries with the same "_corroboration_key" but "_angle" text differing only in case share one NN.
    - test_fallback_without_angle_and_plain_string: [["gemini", {"report": "a"}], ["gemini", "raw b"]] gives "research/01-gemini.md" and "research/02-gemini.md". Both bodies end with their text, and there are no duplicates.
    - test_absolute_uniqueness_suffix: two entries with the same "_angle" + same provider (no corroboration key) give "research/01-<slug>-gemini.md" and "research/01-<slug>-gemini-2.md".
    - test_path_traversal_angle_stays_single_entry: "_angle" "../../etc/passwd" and provider "../x" give exactly one research file. Its name starts with "research/", contains no "..", and has exactly one "/" in total.
    - test_accented_angle_readable_slug: "_angle" "Quelle est la stratégie de croissance à l'étranger ?" gives a name containing "Quelle_est_la_strategie" (no combining marks, no spaces), and the slug part is at most 60 chars.
    - test_header_names_questions_and_provider: an entry with "_angle", a different "_sub_question", "_client_question" and "sub_questions" ["q1","q2"] gives a header that contains each text plus the provider name, ahead of the "---" separator. A "_sub_question" equal to "_angle" is NOT repeated.
    - test_index_md_lists_files_in_zip_order: the index.md body names every research filename in the same order as infolist(), each with its question text and provider.
    Existing tests to update (the naming legitimately changed; record each one in the SUMMARY):
    test_layout_report_research_and_sources ("research/angle-a.md" becomes "research/01-angle-a.md", body equality becomes endswith "provider A text"),
    test_provider_name_is_sanitized_into_entry_path (becomes "research/01-Angle_One_-_Two_Three.md", body endswith "X"; count only non-index research entries),
    test_non_dict_result_falls_back_to_str ("research/angle-b.md" becomes "research/01-angle-b.md", body endswith "raw string report").
    Keep unchanged: test_empty_cleaned_reports_yields_no_research_entries (empty input still writes NO research/ entries, index.md included), test_missing_cleaned_reports_key_does_not_crash, test_report_md_*, test_sources_json_*, test_no_rejected_content_anywhere_D01 (header labels must never contain "rejected").
  </behavior>
  <action>
    Rewrite only the research loop of build_bundle_zip. Keep the signature exactly `(report: dict, bundle: dict, sources: list) -> bytes`. Per D-01, add no rejected-claims parameter. Leave the report.md and sources.json writes byte-for-byte unchanged, and keep entry order report.md, research files, research/index.md, sources.json. The module stays pure: no I/O, and its only imports are io/json/zipfile/typing plus sanitize_filename.

    Use small private helpers in the same module (for example `_str_field(result, key)`, `_header(...)`, `_md_cell(text)`) and walk the entries in input order.
    (1) `result` is a dict: body = result.get("report") or "", coerced with str() if it is not a str. `result` is not a dict: body = str(result) and it carries no metadata.
    (2) angle = the stripped str of "_angle" when it is a non-empty string. Group key = the non-empty "_corroboration_key" if present, else angle.
    (3) NN comes from ONE shared counter. A group key seen for the first time gets the next index, and a key seen before reuses its index. An entry with no group key (no angle and no corroboration key, or a plain-string result) always takes the next index. Format NN as `f"{idx:02d}"`.
    (4) provider_seg = sanitize_filename(str(name)) with the default max_len, which keeps the existing em-dash test semantics. When angle is present, slug = sanitize_filename(angle, max_len=60) and base = f"{NN}-{slug}-{provider_seg}"; when it is absent, base = f"{NN}-{provider_seg}". Every path segment passes through the shared sanitizer (T-09-02); never hand-roll a sanitizer.
    (5) Absolute uniqueness: keep a `used` set of bases. If base is already used, try f"{base}-2", f"{base}-3", and so on until one is free. The entry is f"research/{base}.md".
    (6) Header, with English labels and question text taken verbatim except that internal whitespace, newlines included, is collapsed to single spaces via `" ".join(s.split())` in the header lines only. The run-level discovery prompt can be multi-line, and collapsing it keeps the markdown intact. Header lines, in order: a title line `# Research report {NN}`; `**Question:** {angle}` when angle is present; `**Sub-question:** ...` when "_sub_question" is a non-empty string different from angle; `**Client question:** ...` when "_client_question" is non-empty and different from both angle and the sub-question; `**Sub-questions:**` followed by `- item` lines when "sub_questions" is a non-empty list, where str items are used as-is and other items are rendered with json.dumps(item, ensure_ascii=False); `**Provider:** {str(name)}` always. After the header come a blank line, `---`, a blank line, and then the body appended UNCHANGED. Build the content as header_str + body and encode it as UTF-8 through writestr on a str, so the body bytes are identical to the body's UTF-8 encoding. Never strip or normalise the body.
    (7) Collect (entry_filename_without_prefix, question_or_empty, provider_raw) rows. After the loop, and ONLY if at least one research entry was written, write "research/index.md". Its content is a `# Research index` heading and one intro sentence, then a markdown table `| # | File | Question | Provider |` with one row per research file in write order. The `#` column is the row's NN. Question cells use the collapsed angle, or "(not recorded)" when the entry has none. In every cell, escape "|" as "\|" and collapse newlines.
    (8) Update the module docstring's D-03 layout block: replace `research/<sanitized-angle>.md    # one per cleaned_reports pair` with the new `research/<NN>-<question-slug>-<provider>.md` line (with the `<NN>-<provider>.md` fallback and the -2/-3 dedupe), add `research/index.md`, and add one sentence recording the defect this fixes (the provider-only names collided, so extractors dropped up to 12 of 15 reports; measured on 13 prod bundles, 2026-09-25). Update the build_bundle_zip docstring's `bundle` paragraph to match. Remove the "exactly three kinds of entry" wording, which is now four.

    Then update the three existing tests listed in <behavior> and add the new ones. Keep the `importorskip` pattern, and import sanitize_filename from app.storage.keys inside the tests to compute the expected slugs.
  </action>
  <verify>
    <automated>cd /c/Users/ajimimo/Desktop/MOELD/nestor-intake-gcp/backend && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests/test_research_bundle.py -q -W error::UserWarning</automated>
  </verify>
  <done>All tests in test_research_bundle.py pass with UserWarning promoted to an error, which proves no duplicate zip names are written. A 9-entry, 3-provider input yields 9 distinct research files plus index.md. grep shows `sanitize_filename(` applied to both the angle and the provider, and no new regex or replace-based sanitizing in bundle.py.</done>
</task>

<task type="auto">
  <name>Task 2: Full backend suite + commit</name>
  <files>backend/app/research/bundle.py, backend/tests/test_research_bundle.py</files>
  <action>
    Docker Desktop is up (testcontainers). Run the FULL backend suite from backend/ with Python 3.12, `~/AppData/Local/Programs/Python/Python312/python.exe -m pytest -q`, and record the exact pass/skip/fail counts. For reference, the last recorded count before this change is 908 passed (commit bb2a2f5); expect 908 plus the new tests. If anything outside test_research_bundle.py fails, first check whether it asserts research zip entry names or bodies. If it does, update it the same way and record it. If it does not, confirm it fails the same way on `git stash` (pre-existing) and report it without fixing. Run a scope check with `git diff --stat`: it must show ONLY backend/app/research/bundle.py and backend/tests/test_research_bundle.py (no tribunal/, frontend/, alembic, research_routes.py or run_task.py). Commit with message `fix(260925-dyt): raw-output zip — one file per angle report, named by question (no duplicate entry names)` plus the attribution trailer lines. `.planning/` is gitignored, so the SUMMARY must be committed with `git add -f`. Do not deploy, and do not rebuild prod bundles.
  </action>
  <verify>
    <automated>cd /c/Users/ajimimo/Desktop/MOELD/nestor-intake-gcp/backend && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest -q</automated>
  </verify>
  <done>The full backend suite passes, with its count recorded in the SUMMARY. The diff touches only the two planned files. The commit exists. The SUMMARY lists the three existing tests whose assertions changed and why.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| engine output -> zip entry path | `_angle` (partly client-authored question text) and provider names become zip path segments |
| engine output -> zip entry body | report text and question text land in markdown the client downloads |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-dyt-01 | Tampering | bundle.py entry naming (zip-slip) | mitigate | Both the slug and the provider go through the shared `sanitize_filename`, which drops "/" and strips leading dots; test_path_traversal_angle_stays_single_entry pins that there is no "..", only one "/", and a research/ prefix (T-09-02) |
| T-dyt-02 | Information disclosure | bundle.py (D-01 rejected claims) | mitigate | The signature is unchanged with no rejected-claims input; the header draws only on `_angle`/`_sub_question`/`_client_question`/`sub_questions`/provider; test_no_rejected_content_anywhere_D01 stays green |
| T-dyt-03 | Denial of service | very long `_angle` in filename | mitigate | The slug is capped at max_len=60; the full text appears only in the header/index |
| T-dyt-04 | Tampering | markdown injection via question text in index.md table | accept | The file is static markdown the operator downloads; "|" is escaped and newlines collapsed so the table stays intact; nothing renders it as HTML server-side |
</threat_model>

<verification>
- test_research_bundle.py passes with `-W error::UserWarning` (no duplicate-name warning possible)
- Full backend suite green; count reported
- `git diff --stat` limited to the two planned files
</verification>

<success_criteria>
- N cleaned_reports entries give N uniquely named research files plus research/index.md
- Names are `NN-<question-slug>-<provider>.md` (fallback `NN-<provider>.md`, `-2` dedupe), and the providers of one angle share NN
- Every body is byte-identical after the header; report.md and sources.json are unchanged
- The shared sanitizer is used for every path segment; the module stays pure
</success_criteria>

<output>
Create `.planning/quick/260925-dyt-raw-output-zip-one-file-per-angle-named-/260925-dyt-SUMMARY.md` (commit with `git add -f`). Include: the full-suite pass count, the three existing tests whose assertions changed and why, and a note that existing prod bundles were NOT rebuilt (only new completions get the new layout).
</output>
