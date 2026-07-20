"""Tribunal adaptive intake — Plan 01-13 Task 1.

Implements `adaptive_intake()`: a single audited Gemini-flash call that either
(a) sharpens the brief into a structured mission_brief with stakes-tagged
    focus_areas (clear-brief path), or
(b) asks 2-3 clarifying questions when the brief is genuinely underspecified
    (vague-brief path — prevents wasting research budget on garbage briefs).

Replaces orchestrator.py:113 `_extract_mission_brief` pass-through.

Output shape (clear path):
    {
        "deep_research_prompt": str,          # sharpened research query
        "language": str,                      # ONE language for the whole run (e.g.
                                              # "English"/"Dutch"); "" => infer downstream
        "focus_areas": [                      # >=1 entries
            {
                "focus_area": str,            # label (backward-compat key)
                "taxonomy":   "A"|"B"|"C"|"D",
                "stakes":     "low"|"med"|"high",
            },
            ...
        ],
        "needs_clarification": False,
        "clarifying_questions": [],
    }

Output shape (vague path):
    {
        "deep_research_prompt": "",
        "focus_areas": [],
        "needs_clarification": True,
        "clarifying_questions": ["...", "...", "..."],  # 2-3
    }

LLM call invariants (critical, DO NOT relax):
  - model: gemini-2.5-flash
  - disable_thinking: True  (ThinkingConfig(thinking_budget=0) — prevents thinking
    tokens from consuming max_output_tokens budget; see CLAUDE.md anti-pattern note)
  - plain-text line format (NOT JSON mode — citations⊗structured-outputs HTTP 400)
  - routed through audited.gemini_generate (grep gate)
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from google.genai import types as genai_types  # noqa: TC002

from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY, STAKES_TIERS

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_INTAKE_MODEL = "gemini-2.5-flash"
_MAX_OUTPUT_TOKENS = 2048

_INTAKE_PROMPT_TEMPLATE = """\
You are a strategic research intake agent. Your job is to analyse a client brief \
and either (A) structure it into a clear research plan, or (B) ask clarifying questions \
when the brief is genuinely too vague to research.

A brief is CLEAR if it names a company, market, domain or question specific enough \
to direct deep research. A brief is VAGUE if it is missing a named entity, geography, \
time frame, or purpose that would make research meaningful.

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

If the brief is CLEAR:
  Output exactly:
    Line 1:  BRIEF_CLEAR
    Line 2:  LANGUAGE: <ONE language for the whole run — the dominant language of the
             brief, written as an English name, e.g. English, Dutch, French, German>
    Line 3:  DEEP_RESEARCH_PROMPT: <one-line sharpened overall research query>
    Then, for EACH focus area, a PAIR of lines in THIS exact order:
      FOCUS_AREA: <label> | TAXONOMY: <A/B/C/D> | STAKES: <low/med/high>
      RESEARCH_PROMPT: <self-contained research brief for THIS focus area — one line>

  LANGUAGE rule (CRITICAL — ONE language per run, never mixed):
  - Detect the DOMINANT language of the brief and emit it on the LANGUAGE line.
  - The ENTIRE run uses that ONE language: every focus-area label, every
    RESEARCH_PROMPT, and the DEEP_RESEARCH_PROMPT must be written in it.
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

  RESEARCH_PROMPT rules (CRITICAL — this line is what the researcher ACTUALLY receives):
  - Write a complete, SELF-CONTAINED research instruction for THIS focus area
    alone. The researcher sees ONLY this line — not the brief, not the answers,
    not the other focus areas. If a fact is needed to research well, it must be
    IN this line.
  - Rewrite the user's question into a clear, unambiguous, well-targeted research
    task. Fix vague wording; make implicit intent explicit.
  - Fold in every relevant specific from the brief — INCLUDING the user's replies
    in any [CLARIFICATION ANSWERS] section: named entity, geography, time frame,
    audience/segment, budget, constraints. Put those specifics INTO this prompt
    instead of leaving them in a shared preamble.
  - State the shared subject ONCE for grounding, then say: research ONLY this
    question; the other focus areas are handled separately. Do not ask the
    researcher to also cover the sibling questions.
  - Write this RESEARCH_PROMPT in the SINGLE run language (the LANGUAGE line).
    The whole run is one language — do NOT honor any request to answer different
    questions in different languages.

  DEEP_RESEARCH_PROMPT rules:
  - A single overall one-liner for context/back-compat, written in the SINGLE run
    language (the LANGUAGE line). Do not mix languages.

  Do NOT add explanations or extra lines.

If the brief is VAGUE:
  Output exactly:
    Line 1:  BRIEF_VAGUE
    Lines 2+: One clarifying question per line in this exact format:
              CLARIFYING_QUESTION: <question text>
  Ask exactly 2 or 3 questions. Do NOT add explanations or extra lines.
"""

# Appended on the one-shot coverage retry when the first intake pass produced
# fewer focus areas than the brief's detected explicit questions (the Q4-drop
# failure mode from the LUKOIL validation run: a 5-question brief collapsed into
# 4 focus areas, silently deleting the loyalty question before research began).
_COVERAGE_RETRY_NOTE = """\

--- COVERAGE CORRECTION (MANDATORY) ---
Your previous attempt produced {n_produced} focus areas, but the brief contains
{n_detected} explicit questions/topics, listed below. Produce EXACTLY one
FOCUS_AREA line per item, in this order, EACH followed by its own RESEARCH_PROMPT
line, plus the LANGUAGE line and the DEEP_RESEARCH_PROMPT line. Do NOT merge, drop,
or reorder items. Write every label in the SINGLE run language (the LANGUAGE line).

Detected questions/topics:
{detected_block}
"""

# Appended when the brief already carries the user's answers to a prior round of
# clarifying questions. Forward-progress guarantee: never re-ask after the user
# has answered, or the clarification loop never terminates.
_FORCE_PROCEED_NOTE = """\

--- OVERRIDE: ALREADY CLARIFIED ---
The brief above ALREADY contains the user's answers to a previous round of
clarifying questions (see the [CLARIFICATION ANSWERS] section). You MUST proceed:
output BRIEF_CLEAR with focus areas. Do NOT output BRIEF_VAGUE and do NOT ask any
further questions, even if the brief still feels broad — work with what is given.
"""


def _make_thinking_config() -> object:
    """Build a GenerateContentConfig with thinking disabled.

    gemini-2.5-flash supports ThinkingConfig(thinking_budget=0).
    Without this, thinking tokens silently consume max_output_tokens,
    truncating output after 2-3 lines (CLAUDE.md anti-pattern).
    """
    try:
        thinking_cfg = genai_types.ThinkingConfig(thinking_budget=0)
    except Exception:
        thinking_cfg = None  # SDK version may not support it — degrade silently

    kwargs: dict = {"max_output_tokens": _MAX_OUTPUT_TOKENS, "temperature": 0.0}
    if thinking_cfg is not None:
        kwargs["thinking_config"] = thinking_cfg

    return genai_types.GenerateContentConfig(**kwargs)


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
    """Parse a BRIEF_CLEAR LLM response into the mission_brief dict."""
    deep_research_prompt = ""
    language = ""
    focus_areas: list[dict] = []

    valid_taxonomy = set(TAXONOMY.keys())
    valid_stakes = set(STAKES_TIERS)

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("LANGUAGE:"):
            # The single language for the WHOLE run (one language, never mixed).
            language = line[len("LANGUAGE:"):].strip()
        elif line.startswith("DEEP_RESEARCH_PROMPT:"):
            deep_research_prompt = line[len("DEEP_RESEARCH_PROMPT:"):].strip()
        elif line.startswith("RESEARCH_PROMPT:"):
            # The self-contained, answer-enriched research brief for the MOST
            # RECENT focus area. This is what divide() actually sends to the
            # researcher. Attach it to the last-parsed focus area; ignore a stray
            # RESEARCH_PROMPT with no preceding FOCUS_AREA.
            rp = line[len("RESEARCH_PROMPT:"):].strip()
            if focus_areas and rp:
                focus_areas[-1]["research_prompt"] = rp
            elif rp:
                log.warning("intake: RESEARCH_PROMPT with no preceding FOCUS_AREA — dropping")
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
                # Filled by the RESEARCH_PROMPT line that follows (if any).
                # Empty string → divide() falls back to "label: deep_research_prompt".
                "research_prompt": "",
            })

    return {
        "deep_research_prompt": deep_research_prompt,
        "focus_areas": focus_areas,
        "language": language,   # ONE language for the whole run ("" => infer downstream)
        "needs_clarification": False,
        "clarifying_questions": [],
    }


def _parse_vague_brief(lines: list[str]) -> dict:
    """Parse a BRIEF_VAGUE LLM response into the mission_brief dict."""
    questions: list[str] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("CLARIFYING_QUESTION:"):
            q = line[len("CLARIFYING_QUESTION:"):].strip()
            if q:
                questions.append(q)

    return {
        "deep_research_prompt": "",
        "focus_areas": [],
        "needs_clarification": True,
        "clarifying_questions": questions[:3],  # cap at 3
    }


async def adaptive_intake(
    *,
    brief: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    allow_clarification: bool = True,
) -> dict:
    """Adaptive intake: sharpen the brief or request clarification.

    Args:
        brief:     Raw client brief text.
        audited:   Injected AuditedLLMClient — the ONLY LLM egress.
        run_id:    UUID for the current run (audit chain).
        tenant_id: UUID for the current tenant (audit chain).

    Returns:
        mission_brief dict — see module docstring for both shapes.
    """
    base_prompt = _INTAKE_PROMPT_TEMPLATE.format(brief=brief)
    # Forward-progress guarantee: after the user has answered, never re-ask.
    if not allow_clarification:
        base_prompt += _FORCE_PROCEED_NOTE

    result = await _intake_once(
        prompt=base_prompt, audited=audited, run_id=run_id, tenant_id=tenant_id
    )

    # ── Coverage check (deterministic) ────────────────────────────────────
    # If the brief enumerates explicit questions and intake produced fewer
    # focus areas, it silently dropped at least one. One forced retry with
    # the detected list spelled out; keep whichever attempt covers more.
    if not result.get("needs_clarification"):
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
            if not retry.get("needs_clarification") and len(
                retry.get("focus_areas") or []
            ) > n_produced:
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
        "adaptive_intake: needs_clarification=%s, focus_areas=%d",
        result["needs_clarification"],
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
    """One intake LLM call + parse. Shared by the first pass and the coverage retry."""
    config = _make_thinking_config()

    response = await audited.gemini_generate(
        run_id=run_id,
        tenant_id=tenant_id,
        model=_INTAKE_MODEL,
        contents=prompt,
        config=config,
    )

    # Extract text — mirror final_synthesis_audited fallback pattern
    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
            if parts:
                text = getattr(parts[0], "text", None) or ""
    text = text or ""

    lines = text.splitlines()

    # Determine path from the first non-empty line
    first = next((ln.strip() for ln in lines if ln.strip()), "")

    if first == "BRIEF_CLEAR":
        return _parse_clear_brief(lines[1:])  # skip the BRIEF_CLEAR sentinel
    if first == "BRIEF_VAGUE":
        return _parse_vague_brief(lines[1:])  # skip the BRIEF_VAGUE sentinel

    # Fallback: treat any response without a sentinel as a clear brief attempt
    log.warning(
        "intake: no BRIEF_CLEAR/BRIEF_VAGUE sentinel in response — "
        "treating as clear brief (first line: %r)", first
    )
    return _parse_clear_brief(lines)
