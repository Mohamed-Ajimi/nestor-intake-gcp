"""Tribunal adaptive intake — DELEGATOR (quick task 260721-twy).

Implements `adaptive_intake()`: a single audited Claude call that ALWAYS sharpens
the brief into a structured mission_brief with stakes-tagged focus_areas. There is
no vague/clarification path anymore.

Rationale (operator decision 2026-07-21): the intake backend is the engine's only
caller and every brief it posts has ALREADY been validated by an operator through
the full pre-research flow. The old gatekeeper behaviour (judge the brief as vague
and ask clarifying questions) therefore only ever caused runs to park as
``needs_input`` — the force-proceed machinery bolted on to defeat it was a
rubberband. This module is now a pure delegator: it receives an operator-validated
brief (questions + full context pack) and MUST produce a research plan.

Output shape (always):
    {
        "deep_research_prompt": str,          # sharpened research query
        "language": str,                      # ONE language for the whole run (e.g.
                                              # "English"/"Dutch"); "" => infer downstream
        "focus_areas": [                      # >=1 entries
            {
                "focus_area": str,            # label (backward-compat key)
                "taxonomy":   "A"|"B"|"C"|"D",
                "stakes":     "low"|"med"|"high",
                "research_prompt": str,       # self-contained, multi-line assignment
            },
            ...
        ],
        "needs_clarification": False,         # KEPT for shape compat — ALWAYS False
        "clarifying_questions": [],           # KEPT for shape compat — ALWAYS empty
    }

The ``needs_clarification`` / ``clarifying_questions`` keys are retained ONLY for
downstream shape compatibility (the vestigial ``needs_input`` run status, the
``/answer`` endpoint, and the worker parking logic still exist) — they are never
populated by this module.

LLM call invariants (critical, DO NOT relax):
  - model: claude-sonnet-5 (same literal as the skeptic model — they are kept
    EQUAL deliberately; if one moves, move both. Quick task 260901-j6w moved the
    pair off claude-sonnet-4-6 on 2026-09-01.)
  - routed through audited.anthropic_messages (grep gate — keeps the audit hash
    chain + cost rollup intact; NEVER a direct provider call, NEVER the Anthropic
    agent SDK query entry point which owns its own egress)
  - plain-text line format (NOT JSON mode)
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY, STAKES_TIERS

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_INTAKE_MODEL = "claude-sonnet-5"
_MAX_OUTPUT_TOKENS = 2048

# Fenced markers delimiting the multi-line, self-contained RESEARCH_PROMPT block
# that follows each FOCUS_AREA line. A one-line prefix is no longer used — the
# researcher receives the full inner block verbatim (multi-line safe).
_RESEARCH_PROMPT_START = "RESEARCH_PROMPT_START"
_RESEARCH_PROMPT_END = "RESEARCH_PROMPT_END"

_INTAKE_PROMPT_TEMPLATE = """\
You are a strategic research intake delegator. The client brief below has ALREADY \
been reviewed and validated by an operator — it is NOT a draft and it is NEVER too \
vague. Your job is to structure it into a clear, actionable research plan. You MUST \
produce a plan; you may NOT ask clarifying questions and you may NOT refuse.

=== CLIENT BRIEF ===
{brief}
=== END BRIEF ===

Available taxonomy codes:
  A = Customer   (audience, sentiment, buyer behaviour)
  B = Competitor (competitor landscape, strategies, market share)
  C = Trend      (market trends, macro signals, technology adoption)
  D = Strategy   (strategic positioning, M&A, partnerships, internal moves)

Available stakes tiers: low | med | high
  high = core question; must get right; Tribunal will verify with 3 skeptics
  med  = important but secondary; 2 skeptics
  low  = supporting colour; wave through

--- INSTRUCTIONS ---

Output exactly:
  Line 1:  BRIEF_CLEAR
  Line 2:  LANGUAGE: <ONE language for the whole run — the dominant language of the
           brief, written as an English name, e.g. English, Dutch, French, German>
  Line 3:  DEEP_RESEARCH_PROMPT: <one-line sharpened overall research query>
  Then, for EACH focus area, a FOCUS_AREA line immediately followed by a fenced
  multi-line RESEARCH_PROMPT block, in THIS exact order:
    FOCUS_AREA: <label> | TAXONOMY: <A/B/C/D> | STAKES: <low/med/high>
    RESEARCH_PROMPT_START
    <one or many lines: a complete, self-contained research assignment for THIS
    focus area — named entity, geography, time frame, audience/segment, budget,
    constraints, and every relevant fact drawn from the brief's context>
    RESEARCH_PROMPT_END

LANGUAGE rule (CRITICAL — ONE language per run, never mixed):
- Detect the DOMINANT language of the brief and emit it on the LANGUAGE line.
- The ENTIRE run uses that ONE language: every focus-area label, every
  RESEARCH_PROMPT block, and the DEEP_RESEARCH_PROMPT must be written in it.
- NEVER mix languages — even if the brief itself mixes them or explicitly asks
  for different questions in different languages, pick the single dominant
  language and use it for EVERYTHING. Ignore any per-question language request.

Focus-area (label) rules (CRITICAL):
- If the brief contains EXPLICIT questions or numbered topics, produce EXACTLY
  one focus area per question/topic, in the brief's order. NEVER merge two
  questions into one focus area and NEVER drop a question.
- Only when the brief is a single open question with no enumerated sub-topics
  may you decompose it yourself into 2-4 focus areas.
- Write every focus-area label in the SINGLE run language (the LANGUAGE line).
  Do not mix languages across labels. The label is the coverage/display key —
  keep it short and faithful to the original question.

RESEARCH_PROMPT block rules (CRITICAL — this block is what the researcher ACTUALLY receives):
- Write a complete, SELF-CONTAINED research instruction for THIS focus area
  alone. The researcher sees ONLY this block — not the brief, not the answers,
  not the other focus areas. If a fact is needed to research well, it must be
  INSIDE this block.
- Use multiple lines freely: state the named entity, geography, time frame,
  audience/segment, budget, and constraints, then the specific research task.
- Rewrite the user's question into a clear, unambiguous, well-targeted research
  task. Fix vague wording; make implicit intent explicit.
- Fold in every relevant specific from the brief's context (the [CONTEXT PACK]
  section carries the full validated context). Put those specifics INTO this
  block instead of leaving them in a shared preamble.
- State the shared subject ONCE for grounding, then say: research ONLY this
  question; the other focus areas are handled separately. Do not ask the
  researcher to also cover the sibling questions.
- Write this RESEARCH_PROMPT block in the SINGLE run language (the LANGUAGE line).
  The whole run is one language — do NOT honor any request to answer different
  questions in different languages.

DEEP_RESEARCH_PROMPT rules:
- A single overall one-liner for context/back-compat, written in the SINGLE run
  language (the LANGUAGE line). Do not mix languages.

Do NOT add explanations or extra lines outside this format.
"""

# Appended on the one-shot coverage retry when the first intake pass produced
# fewer focus areas than the brief's detected explicit questions (the Q4-drop
# failure mode from the LUKOIL validation run: a 5-question brief collapsed into
# 4 focus areas, silently deleting the loyalty question before research began).
_COVERAGE_RETRY_NOTE = """\

--- COVERAGE CORRECTION (MANDATORY) ---
Your previous attempt produced {n_produced} focus areas, but the brief contains
{n_detected} explicit questions/topics, listed below. Produce EXACTLY one
FOCUS_AREA line per item, in this order, EACH followed by its own fenced
RESEARCH_PROMPT_START/RESEARCH_PROMPT_END block, plus the LANGUAGE line and the
DEEP_RESEARCH_PROMPT line. Do NOT merge, drop, or reorder items. Write every label
in the SINGLE run language (the LANGUAGE line).

Detected questions/topics:
{detected_block}
"""


def detect_explicit_questions(brief: str) -> list[str]:
    """Deterministically detect explicit questions/topics in a brief.

    Counts two patterns:
      - enumerated lines:  "1. ...", "2) ...", "Q1 ...", "V3: ...", "- ...", "* ..."
        (only when the line has enough words to be a real topic, not a header)
      - interrogative lines: any line ending in "?"

    Used as the ground truth for the intake coverage check: if intake produces
    fewer focus areas than detected questions, it silently dropped one, and we
    force a single retry. Returns [] for free-prose briefs (no constraint).
    """
    import re

    detected: list[str] = []
    seen: set[str] = set()
    enum_re = re.compile(r"^\s*(?:\d{1,2}[.):]|[QqVv]\d{1,2}[.):]?|[-*•])\s+(.{10,})")

    for raw_line in brief.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        candidate = ""
        m = enum_re.match(line)
        if m and len(m.group(1).split()) >= 3:
            candidate = m.group(1).strip()
        elif line.endswith("?") and len(line.split()) >= 4:
            candidate = line
        if candidate:
            key = candidate.lower()[:80]
            if key not in seen:
                seen.add(key)
                detected.append(candidate)

    return detected


def _parse_clear_brief(lines: list[str]) -> dict:
    """Parse a BRIEF_CLEAR LLM response into the mission_brief dict.

    LANGUAGE / DEEP_RESEARCH_PROMPT / FOCUS_AREA lines are handled line-by-line.
    The per-focus-area RESEARCH_PROMPT is a FENCED multi-line block: when a line
    equals ``RESEARCH_PROMPT_START`` we accumulate subsequent lines verbatim until
    ``RESEARCH_PROMPT_END``, then attach the joined+stripped block (newlines
    preserved) to the most-recently-parsed focus area.
    """
    deep_research_prompt = ""
    language = ""
    focus_areas: list[dict] = []

    valid_taxonomy = set(TAXONOMY.keys())
    valid_stakes = set(STAKES_TIERS)

    # Fenced RESEARCH_PROMPT accumulator state.
    in_prompt_block = False
    prompt_buffer: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()

        # --- Fenced RESEARCH_PROMPT block handling (multi-line, verbatim) ---
        if in_prompt_block:
            if stripped == _RESEARCH_PROMPT_END:
                block = "\n".join(prompt_buffer).strip()
                if focus_areas and block:
                    focus_areas[-1]["research_prompt"] = block
                elif block:
                    log.warning(
                        "intake: RESEARCH_PROMPT block with no preceding FOCUS_AREA — dropping"
                    )
                in_prompt_block = False
                prompt_buffer = []
            else:
                # Collect the inner line VERBATIM (preserve original text, not stripped).
                prompt_buffer.append(raw_line.rstrip("\n"))
            continue

        if stripped == _RESEARCH_PROMPT_START:
            in_prompt_block = True
            prompt_buffer = []
            continue

        # --- Ordinary key: value lines ---
        if not stripped:
            continue
        line = stripped
        if line.startswith("LANGUAGE:"):
            # The single language for the WHOLE run (one language, never mixed).
            language = line[len("LANGUAGE:"):].strip()
        elif line.startswith("DEEP_RESEARCH_PROMPT:"):
            deep_research_prompt = line[len("DEEP_RESEARCH_PROMPT:"):].strip()
        elif line.startswith("FOCUS_AREA:"):
            # Format: "FOCUS_AREA: <label> | TAXONOMY: <code> | STAKES: <tier>"
            parts = line.split("|")
            if len(parts) < 3:
                log.warning("intake: malformed FOCUS_AREA line (too few parts): %r", line)
                continue

            fa_raw = parts[0].replace("FOCUS_AREA:", "").strip()
            tax_raw = ""
            stakes_raw = ""

            for part in parts[1:]:
                part = part.strip()
                if part.startswith("TAXONOMY:"):
                    tax_raw = part[len("TAXONOMY:"):].strip()
                elif part.startswith("STAKES:"):
                    stakes_raw = part[len("STAKES:"):].strip()

            if not fa_raw:
                log.warning("intake: empty focus_area label in line: %r", line)
                continue
            if tax_raw not in valid_taxonomy:
                log.warning("intake: invalid taxonomy %r in line: %r — defaulting to D", tax_raw, line)
                tax_raw = "D"
            if stakes_raw not in valid_stakes:
                log.warning("intake: invalid stakes %r in line: %r — defaulting to med", stakes_raw, line)
                stakes_raw = "med"

            focus_areas.append({
                "focus_area": fa_raw,
                "taxonomy": tax_raw,
                "stakes": stakes_raw,
                # Filled by the fenced RESEARCH_PROMPT block that follows (if any).
                # Empty string → divide() falls back to "label: deep_research_prompt".
                "research_prompt": "",
            })

    # A dangling RESEARCH_PROMPT_START with no closing END: flush what we have.
    if in_prompt_block:
        block = "\n".join(prompt_buffer).strip()
        if focus_areas and block:
            focus_areas[-1]["research_prompt"] = block

    return {
        "deep_research_prompt": deep_research_prompt,
        "focus_areas": focus_areas,
        "language": language,   # ONE language for the whole run ("" => infer downstream)
        "needs_clarification": False,   # DELEGATOR — always False (shape compat)
        "clarifying_questions": [],     # DELEGATOR — always empty (shape compat)
    }


async def adaptive_intake(
    *,
    brief: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Adaptive intake DELEGATOR: always sharpen the brief into a research plan.

    Args:
        brief:     Operator-validated client brief text (questions + context pack).
        audited:   Injected AuditedLLMClient — the ONLY LLM egress.
        run_id:    UUID for the current run (audit chain).
        tenant_id: UUID for the current tenant (audit chain).

    Returns:
        mission_brief dict — see module docstring (needs_clarification always False).
    """
    base_prompt = _INTAKE_PROMPT_TEMPLATE.format(brief=brief)

    result = await _intake_once(
        prompt=base_prompt, audited=audited, run_id=run_id, tenant_id=tenant_id
    )

    # ── Coverage check (deterministic) ────────────────────────────────────
    # If the brief enumerates explicit questions and intake produced fewer
    # focus areas, it silently dropped at least one. One forced retry with
    # the detected list spelled out; keep whichever attempt covers more.
    detected = detect_explicit_questions(brief)
    n_produced = len(result.get("focus_areas") or [])
    if detected and n_produced < len(detected):
        log.warning(
            "adaptive_intake: coverage check FAILED — %d focus areas for %d "
            "detected questions; forcing one retry",
            n_produced, len(detected),
        )
        detected_block = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(detected))
        retry_prompt = base_prompt + _COVERAGE_RETRY_NOTE.format(
            n_produced=n_produced,
            n_detected=len(detected),
            detected_block=detected_block,
        )
        retry = await _intake_once(
            prompt=retry_prompt, audited=audited, run_id=run_id, tenant_id=tenant_id
        )
        if len(retry.get("focus_areas") or []) > n_produced:
            # The retry may omit the LANGUAGE line; carry the first pass's
            # detected language forward so the one-language guarantee holds.
            if not (retry.get("language") or "").strip() and (result.get("language") or "").strip():
                retry["language"] = result["language"]
            result = retry
        log.info(
            "adaptive_intake: coverage retry -> %d focus areas (detected %d)",
            len(result.get("focus_areas") or []), len(detected),
        )

    log.info(
        "adaptive_intake: focus_areas=%d",
        len(result["focus_areas"]),
    )
    return result


async def _intake_once(
    *,
    prompt: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """One intake LLM call + parse. Shared by the first pass and the coverage retry.

    Routes through ``audited.anthropic_messages`` (mirrors skeptic.py) so the call
    is audited and cost-rolled-up. Text extraction: ``resp.content`` is a list of
    blocks; join the ``.text`` of the text-typed blocks.
    """
    response = await audited.anthropic_messages(
        run_id=run_id,
        tenant_id=tenant_id,
        model=_INTAKE_MODEL,
        messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        max_tokens=_MAX_OUTPUT_TOKENS,
    )

    # Extract text — resp.content is a list of blocks; join the text blocks.
    content = getattr(response, "content", None) or []
    text_parts: list[str] = []
    for block in content:
        btype = getattr(block, "type", None)
        if btype is None and isinstance(block, dict):
            btype = block.get("type")
        if btype == "text":
            btext = getattr(block, "text", None)
            if btext is None and isinstance(block, dict):
                btext = block.get("text")
            if btext:
                text_parts.append(btext)
    text = "".join(text_parts)

    lines = text.splitlines()

    # Determine the sentinel from the first non-empty line. The delegator always
    # emits BRIEF_CLEAR; anything else is treated as a clear-brief attempt too.
    first = next((ln.strip() for ln in lines if ln.strip()), "")

    if first == "BRIEF_CLEAR":
        return _parse_clear_brief(lines[1:])  # skip the BRIEF_CLEAR sentinel

    # Fallback: treat any response without the sentinel as a clear brief attempt.
    log.warning(
        "intake: no BRIEF_CLEAR sentinel in response — "
        "treating as clear brief (first line: %r)", first
    )
    return _parse_clear_brief(lines)
