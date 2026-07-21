---
phase: quick-260721-twy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/research/brief.py
  - backend/tests/test_research_brief.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py
  - tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py
  - tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "The assembled brief contains the full context-pack text under a labeled Context section (no 4000-char truncation)"
    - "The assembled brief contains no [CLARIFICATION ANSWERS] force-proceed sections"
    - "adaptive_intake never returns needs_clarification=True; it is always False with empty clarifying_questions"
    - "The intake stage runs on claude-sonnet-4-6 via audited.anthropic_messages (audited, cost-rolled-up)"
    - "RESEARCH_PROMPT is a parseable multi-line self-contained block (fenced), not a one-line prefix"
    - "The coverage-retry mechanism and _COVERAGE_RETRY_NOTE remain intact"
    - "pipeline.py has no _CLAR_CAP counting and no needs_clarification early-return branch around intake"
    - "divide()/run_angles() forward the full multi-line research prompt unmodified (no first-line split / truncation)"
  artifacts:
    - path: "backend/app/research/brief.py"
      provides: "Brief composer with full context pack, no clarification blocks"
      contains: "def assemble_brief"
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py"
      provides: "Delegator intake on claude-sonnet-4-6 with multi-line RESEARCH_PROMPT fences"
      contains: "anthropic_messages"
    - path: "tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py"
      provides: "Pipeline with clarification loop removed"
      contains: "adaptive_intake"
  key_links:
    - from: "tribunal/.../intake.py (_parse_clear_brief)"
      to: "tribunal/.../research_division.py (divide)"
      via: "focus_areas[*].research_prompt (multi-line, verbatim)"
      pattern: "research_prompt"
---

<objective>
Convert the Tribunal intake stage from a gatekeeper (that could reject a brief as
vague and ask clarifying questions) into a DELEGATOR that always produces a
research plan, and delete the "rubberband" force-proceed machinery that was bolted
on to defeat the gatekeeper.

Three coordinated code changes:
1. `backend/app/research/brief.py` — drop the two `[CLARIFICATION ANSWERS]` sections
   and the 4000-char context truncation; fold the FULL context pack into the brief
   under a labeled Context section.
2. `tribunal/.../intake.py` — rewrite as a delegator: no vague/clarification branch,
   switch model gemini-2.5-flash → claude-sonnet-4-6 (audited path), multi-line
   fenced RESEARCH_PROMPT per focus area, delete `_FORCE_PROCEED_NOTE`, keep coverage
   retry.
3. `tribunal/.../pipeline.py` — remove `_CLAR_CAP` counting and the needs_clarification
   early-return around intake.

Purpose: The intake backend is the engine's only caller and every brief is
operator-validated, so the vague-brief gate is dead weight that only ever caused
runs to park (`needs_input`) — the force-proceed sections and clar-cap were rubberband
patches to stop that. Removing both simplifies the flow and lets the delegator write
full, self-contained research assignments.

Output: three modified source files + two modified test files.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md

CONSTRAINTS (read before executing):
- Dev machine has NO Python/Docker. Do NOT run pytest, py_compile, or any build/deploy.
  Verification is by careful reading + structural self-check ONLY. Tests run later in Cloud Build.
- This is CODE-ONLY. No deploys, no image builds, no gcloud.
- KEEP the vestigial API surface: the `needs_input` run status, the `/answer` endpoint,
  and the worker parking logic all STAY. Do NOT touch API routes or worker code.
- Keep the `needs_clarification` dict KEY for shape compatibility — always False / empty list.
</execution_context>

<context>
@backend/app/research/brief.py
@backend/tests/test_research_brief.py
@tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py
@tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py
@tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py
@tribunal/nestor_pulse_sdk/pipeline/tribunal/research_division.py

<interfaces>
<!-- Contracts the executor needs. Extracted from the codebase — no exploration required. -->

Audited Anthropic egress (mirror skeptic.py — this is how the delegator must call the model):
  await audited.anthropic_messages(
      run_id=run_id,
      tenant_id=tenant_id,
      model="claude-sonnet-4-6",
      messages=[{"role": "user", "content": [{"type": "text", "text": <prompt>}]}],
      max_tokens=<int>,
  )
  # Returns a raw Anthropic response. Text extraction: resp.content is a list of
  # blocks; join block.text for blocks whose .type == "text" (or getattr(b,"text","")).
  # audited.anthropic_messages writes the audit row itself → cost rollup keeps working.

pipeline.py intake call site (currently lines ~184-238) passes:
  await adaptive_intake(brief=..., audited=..., run_id=..., tenant_id=..., allow_clarification=not force_proceed)
  # After this plan: drop allow_clarification (delegator never clarifies).

research_division.divide() ALREADY forwards the per-focus-area research_prompt verbatim
as the angle query (research_division.py lines ~134-141):
  research_prompt = (fa.get("research_prompt") or "").strip()
  if research_prompt: query = research_prompt      # verbatim, multi-line safe — no split
  # High-stakes doubling appends a "broader" suffix to the same string (still verbatim base).
  # => divide() already passes multi-line prompts through unmodified. Task 3 only VERIFIES this.

Skeptic model constant (pipeline.py line 84): _SKEPTIC_MODEL = "claude-sonnet-4-6"
  # Use the SAME literal for the intake delegator model.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite backend brief composer — full context pack, no clarification blocks</name>
  <files>backend/app/research/brief.py, backend/tests/test_research_brief.py</files>
  <behavior>
    After this task, assemble_brief() returns a brief whose sections are:
      opening line → blank → "Onderzoeksvragen:" + enumerated questions → blank → report hint
      → blank → a labeled Context section (e.g. "[CONTEXT PACK]") carrying the FULL
      context_pack_text (untruncated) when context_pack_text is non-empty.
    - Test: brief contains "[CONTEXT PACK]" (or chosen label) followed by the full context text
      when context_pack_text is passed, with NO length cap (a >4000-char context appears in full).
    - Test: brief contains NO "[CLARIFICATION ANSWERS]" substring in any case.
    - Test: the two prior force-proceed tests (test_force_proceed_sections_present_with_questions,
      test_no_questions_yields_no_force_proceed_sections) are REPLACED by tests asserting the
      new Context-section shape / absence of clarification blocks.
    - Test (unchanged, must still pass): [INTERACTIVE_REPORT] never present; "Onderzoeksvragen:"
      header present; questions enumerated in priority order; thin-intake fallback hint present;
      answers-derived questions + research_questions precedence + string entries all still work.
  </behavior>
  <action>
    In backend/app/research/brief.py:
    (1) DELETE the `_CONTEXT_EXCERPT_CHARS = 4000` constant.
    (2) In assemble_brief(), REPLACE the entire `if ordered:` block that appends the two
        "[CLARIFICATION ANSWERS]" sections (currently lines ~265-290) with a labeled Context
        section: when `context_pack_text` (stripped) is non-empty, append `["", "[CONTEXT PACK]",
        <full context_pack_text, NOT truncated>]` to `sections`. Keep the existing entity-bits
        fallback (project_title / sector / goals join) ONLY as the context body when
        context_pack_text is empty — but still label it under the same "[CONTEXT PACK]" header,
        NOT under a clarification header. Do NOT gate the context section on `if ordered:` being
        truthy in a way that reintroduces clarification semantics — a context section may be
        emitted whenever context text (or fallback bits) exist. The empty-questions behavior for
        the 422 guard lives in the trigger route (validated_questions) and is untouched.
    (3) Update the assemble_brief docstring: remove the "Force-proceed contract" / _CLAR_CAP
        paragraph; describe the Context section instead. Update the "[CLARIFICATION ANSWERS]"
        references in the answers-key docstring block if any remain misleading (the questions-source
        precedence comment at lines ~52-61 stays — it is about answer keys, not clarification).
    In backend/tests/test_research_brief.py:
    (4) REPLACE test_force_proceed_sections_present_with_questions and
        test_no_questions_yields_no_force_proceed_sections with:
          - a test that passes a long (>4000 char) context_pack_text and asserts the FULL text is
            present in the brief (pick a sentinel near the end of the context) AND that
            "[CLARIFICATION ANSWERS]" is absent AND "[CONTEXT PACK]" is present;
          - a test that asserts "[CLARIFICATION ANSWERS]" never appears (with and without questions).
        Update the section header comment block (lines ~133-138) to describe the new context-section
        contract instead of the force-proceed contract. Leave all other tests unchanged.
    Do NOT write fenced code into any file section other than the actual .py edits.
  </action>
  <verify>
    <automated>MISSING — dev box has no Python; Cloud Build runs pytest later. Structural self-check: grep brief.py for "CLARIFICATION ANSWERS" and "_CONTEXT_EXCERPT_CHARS" — both MUST return zero matches; grep for "[CONTEXT PACK]" MUST match.</automated>
  </verify>
  <done>brief.py: no "[CLARIFICATION ANSWERS]" and no "_CONTEXT_EXCERPT_CHARS"; a "[CONTEXT PACK]" labeled section carrying the full untruncated context_pack_text. Tests rewritten to assert the new shape; all other brief tests preserved.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Rewrite intake.py as a delegator (claude-sonnet-4-6, multi-line RESEARCH_PROMPT, no vague branch)</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py, tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py</files>
  <behavior>
    - adaptive_intake() always returns needs_clarification=False, clarifying_questions=[] (keys kept for shape).
    - _INTAKE_MODEL == "claude-sonnet-4-6"; the LLM call goes through audited.anthropic_messages
      (NOT gemini_generate), so the stage is audited and cost-rolled-up.
    - The prompt no longer offers a BRIEF_VAGUE branch; it always emits BRIEF_CLEAR-shaped output.
    - Each focus area's RESEARCH_PROMPT is a MULTI-LINE fenced block:
        RESEARCH_PROMPT_START
        <one or many lines: entity, geography, time frame, audience, constraints, relevant context facts>
        RESEARCH_PROMPT_END
      The parser attaches the full inner block (joined, stripped) to the last-parsed focus area.
    - DEEP_RESEARCH_PROMPT stays a single line.
    - _COVERAGE_RETRY_NOTE and the coverage-retry mechanism remain and still work.
    - _FORCE_PROCEED_NOTE is deleted; allow_clarification param removed.
    - Test: a canned claude-shaped response with two focus areas, each with a multi-line
      RESEARCH_PROMPT_START/END block, parses into research_prompt strings that contain the inner
      newlines (multi-line preserved) and are attached to the correct focus area.
    - Test: coverage-retry tests still pass (the retry note is still appended; one retry recovers a
      dropped question). Update canned responses to the new fenced format.
    - Test: a response with no RESEARCH_PROMPT block leaves research_prompt == "".
    - Test: the audited call asserts model == "claude-sonnet-4-6" and that anthropic_messages
      (not gemini_generate) was invoked; the FakeAudited must expose anthropic_messages.
    - The BRIEF_VAGUE canned responses and vague-path tests (TestVagueBrief, test_vague_brief_skips_
      coverage_check) are DELETED (there is no vague path anymore).
  </behavior>
  <action>
    In tribunal/nestor_pulse_sdk/pipeline/tribunal/intake.py:
    (1) Model + client: change `_INTAKE_MODEL = "claude-sonnet-4-6"`. Rewrite `_intake_once()` to
        call `audited.anthropic_messages(run_id=..., tenant_id=..., model=_INTAKE_MODEL,
        messages=[{"role":"user","content":[{"type":"text","text": prompt}]}], max_tokens=_MAX_OUTPUT_TOKENS)`
        — mirror skeptic.py's call shape. Replace the gemini text-extraction with Anthropic
        extraction: iterate `resp.content` blocks and join the `.text` of text blocks (guard with
        getattr). Delete the google.genai import, `_make_thinking_config()`, `genai_types`, and
        `_MAX_OUTPUT_TOKENS` gemini-specific docstring lines; keep a plain `_MAX_OUTPUT_TOKENS` int
        for max_tokens.
    (2) Delete the vague branch: remove `_FORCE_PROCEED_NOTE`, remove `_parse_vague_brief()`, remove
        the `allow_clarification` parameter from adaptive_intake(), and remove the `if not
        allow_clarification: base_prompt += _FORCE_PROCEED_NOTE` line. In `_intake_once`, drop the
        BRIEF_VAGUE dispatch — always parse as clear (the fallback-to-clear path already exists).
    (3) Rewrite `_INTAKE_PROMPT_TEMPLATE` as a DELEGATOR prompt: remove the "(B) ask clarifying
        questions" framing and the entire "If the brief is VAGUE" section. Instruct the model that
        the brief is operator-validated and it MUST produce a research plan. Keep the LANGUAGE line,
        the A-D taxonomy block, the low/med/high stakes block, and the FOCUS_AREA line format
        (`FOCUS_AREA: <label> | TAXONOMY: <A/B/C/D> | STAKES: <low/med/high>`) EXACTLY — divide()
        and downstream depend on this contract. Change the RESEARCH_PROMPT instruction from a
        one-line format to a fenced multi-line block: after each FOCUS_AREA line, emit
        `RESEARCH_PROMPT_START`, then a full multi-line self-contained assignment (entity, geography,
        time frame, audience, constraints, relevant context-pack facts), then `RESEARCH_PROMPT_END`.
        Keep DEEP_RESEARCH_PROMPT a one-liner. Keep the one-language-per-run rules and the
        "one focus area per explicit question, no merge/drop" rules.
    (4) Rewrite the RESEARCH_PROMPT parsing in `_parse_clear_brief()` (currently line-prefix based
        at ~lines 234-297): keep LANGUAGE / DEEP_RESEARCH_PROMPT / FOCUS_AREA line handling as-is,
        but replace the single-line `RESEARCH_PROMPT:` handling with a fenced-block accumulator —
        when a line equals `RESEARCH_PROMPT_START`, collect subsequent lines verbatim until
        `RESEARCH_PROMPT_END`, then attach the joined+stripped multi-line block to focus_areas[-1]
        ["research_prompt"] (warn + drop if no preceding FOCUS_AREA). Preserve the empty-default:
        focus areas with no block keep research_prompt == "". KEEP `detect_explicit_questions()`,
        `_COVERAGE_RETRY_NOTE`, and the entire coverage-retry logic in adaptive_intake() unchanged
        (except removing the needs_clarification guard now that it is always False).
    (5) Update the module docstring: describe the delegator (single audited claude-sonnet-4-6 call
        that always sharpens; never asks clarifying questions), drop the vague-path shape block,
        update the "LLM call invariants" to the Anthropic path (remove gemini/thinking notes).
    In tribunal/nestor_pulse_sdk/tests/test_tribunal_intake.py:
    (6) Change FakeAudited (and FakeAuditedSequence) to expose `anthropic_messages(self, *, run_id,
        tenant_id, model, messages, **kwargs)` returning a fake Anthropic response whose `.content`
        is a list with one text block (an object exposing `.type=="text"` and `.text=<canned_text>`).
        Update _FakeResponse accordingly (or add a _FakeAnthropicResponse). Update
        test_audited_gemini_generate_called_once → assert anthropic_messages called once with
        model == "claude-sonnet-4-6". Delete test_thinking_disabled_in_kwargs (no gemini config).
    (7) DELETE TestVagueBrief, the VAGUE_BRIEF_RESPONSE canned string, and
        test_vague_brief_skips_coverage_check. Where other tests reused VAGUE_BRIEF_RESPONSE, drop
        those assertions.
    (8) Rewrite the RESEARCH_PROMPT canned responses (CLEAR_BRIEF_WITH_RESEARCH_PROMPTS,
        CLEAR_BRIEF_NL_RESPONSE) to the fenced RESEARCH_PROMPT_START/END multi-line format, and
        update TestResearchPromptParsing to assert the multi-line block is captured (include a
        newline inside a block and assert it survives). Keep TestDivideUsesResearchPrompt as-is —
        divide() is unchanged; those tests build mission_brief dicts directly.
    Do NOT run pytest; author by construction.
  </action>
  <verify>
    <automated>MISSING — dev box has no Python; Cloud Build runs pytest later. Structural self-check: grep intake.py — "BRIEF_VAGUE", "_FORCE_PROCEED_NOTE", "gemini_generate", "genai_types", "allow_clarification" MUST all return zero matches; "anthropic_messages", "claude-sonnet-4-6", "RESEARCH_PROMPT_START", "_COVERAGE_RETRY_NOTE" MUST match.</automated>
  </verify>
  <done>intake.py is a delegator: claude-sonnet-4-6 via audited.anthropic_messages, no vague/clarification path, multi-line fenced RESEARCH_PROMPT parsed correctly, coverage retry intact, _FORCE_PROCEED_NOTE gone. Tests updated: FakeAudited exposes anthropic_messages, vague tests deleted, research-prompt tests assert multi-line capture.</done>
</task>

<task type="auto">
  <name>Task 3: Strip clarification loop from pipeline.py; verify multi-line prompt pass-through</name>
  <files>tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py</files>
  <action>
    In tribunal/nestor_pulse_sdk/pipeline/tribunal/pipeline.py, Stage 1 (Adaptive intake, lines ~181-245):
    (1) DELETE the clarification-cap block: `_CLAR_CAP = 2`, `clar_rounds = brief.count(
        "[CLARIFICATION ANSWERS]")`, `force_proceed = clar_rounds >= _CLAR_CAP`, and the
        `allow_clarification=not force_proceed` kwarg on the adaptive_intake() call (call it with
        just brief/audited/run_id/tenant_id).
    (2) DELETE the `if mission_brief.get("needs_clarification") and force_proceed:` forced-proceed
        synthetic-mission block (the base-split single-focus fallback, lines ~199-215).
    (3) DELETE the `if mission_brief.get("needs_clarification"):` early-return branch (lines ~217-238)
        that returns the clarifying-questions payload. adaptive_intake now always returns a real plan,
        so the run always proceeds to research division.
    (4) Keep the surviving `await set_stage(... _intake_detail(mission_brief))` result-surfacing call
        (line ~243) and `raise_if_cancelled`. `_intake_detail()` still handles the (now-unreachable)
        needs_clarification branch harmlessly — leave it, or simplify to the focus-area branch only;
        do NOT rip out unrelated code.
    (5) VERIFY (read-only, add NO transform): confirm divide() (research_division.py ~134-141) assigns
        the angle query as the verbatim `fa["research_prompt"]` string with no `.splitlines()[0]`,
        no truncation, no `.split("\n")` — multi-line prompts pass through whole. Confirm run_angles()
        forwards `angle["query"]` to the provider runner unmodified. If (and only if) a first-line
        split or truncation exists on the research_prompt path, remove it; otherwise change nothing in
        research_division.py. Do NOT touch the [INTERACTIVE_REPORT] marker handling, cache-resume,
        or any downstream stage.
  </action>
  <verify>
    <automated>MISSING — dev box has no Python; Cloud Build runs pytest later. Structural self-check: grep pipeline.py — "_CLAR_CAP", "force_proceed", "clar_rounds", "allow_clarification" MUST all return zero matches; "adaptive_intake(" MUST still match with only brief/audited/run_id/tenant_id args. grep research_division.py for ".splitlines()[0]" / "split(\"\\n\")" on the query path MUST return zero matches (confirming multi-line pass-through).</automated>
  </verify>
  <done>pipeline.py has no _CLAR_CAP / force_proceed / clar_rounds / allow_clarification; the intake early-return and forced-proceed synthetic block are gone; adaptive_intake is called with the reduced arg set; divide()/run_angles() confirmed to pass multi-line research prompts through unmodified.</done>
</task>

</tasks>

<verification>
Whole-change structural checks (no Python execution — dev box has no Python/Docker):
- brief.py: zero matches for "CLARIFICATION ANSWERS" and "_CONTEXT_EXCERPT_CHARS"; "[CONTEXT PACK]" present.
- intake.py: zero matches for "BRIEF_VAGUE", "_FORCE_PROCEED_NOTE", "gemini_generate", "genai_types",
  "allow_clarification"; present: "anthropic_messages", "claude-sonnet-4-6", "RESEARCH_PROMPT_START",
  "RESEARCH_PROMPT_END", "_COVERAGE_RETRY_NOTE".
- pipeline.py: zero matches for "_CLAR_CAP", "force_proceed", "clar_rounds", "allow_clarification".
- The FOCUS_AREA line format (`FOCUS_AREA: <label> | TAXONOMY: <A/B/C/D> | STAKES: <low/med/high>`)
  and the LANGUAGE / DEEP_RESEARCH_PROMPT one-liner contracts are unchanged (divide() compatibility).
- Vestigial API/worker surface (needs_input status, /answer endpoint, worker parking) untouched.
- Tests authored by construction; the full tribunal + backend suites run later in Cloud Build.
</verification>

<success_criteria>
- The intake stage is a delegator: it always returns a research plan (needs_clarification always
  False), runs on claude-sonnet-4-6 through the audited Anthropic path, and emits full multi-line
  self-contained research prompts per focus area.
- The rubberband force-proceed / clarification-loop machinery is fully removed from both the brief
  composer (backend) and the pipeline (tribunal), including the 4000-char context truncation.
- The brief now carries the full context pack under a labeled Context section.
- The coverage-retry mechanism, taxonomy/stakes/LANGUAGE output contract, and multi-line prompt
  pass-through to divide()/run_angles() are all preserved.
- Both affected test files are updated to match the new shapes (author-by-construction; no local runs).
</success_criteria>

<output>
Create `.planning/quick/260721-twy-convert-tribunal-intake-gatekeeper-into-/260721-twy-SUMMARY.md` when done
</output>
