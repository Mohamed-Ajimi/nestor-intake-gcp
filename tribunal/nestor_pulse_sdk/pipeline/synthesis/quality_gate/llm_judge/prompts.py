"""
Per-dimension judge prompts.

The judge is instructed to:
  1. Read the brief.
  2. Apply the rubric question for THIS dimension only.
  3. Use chain-of-thought reasoning anchored on the bad/good examples.
  4. Return a JSON object with score (1-5 int), reason (1-sentence string),
     and fixes (list of concrete improvement suggestions).

Separate-call-per-dimension (rather than one batched call grading all dimensions)
buys us:
  - Cleaner per-dim audit trail (each dim's grading = one audit_log row).
  - Lower risk of cross-dim contamination in the judge's reasoning.
  - Ability to disable/enable dimensions without re-architecting the prompt.

The CoT structure forces the judge to lay out its reasoning before scoring,
which empirically reduces score variance and surfaces fix candidates as a
natural by-product of the reasoning trace.
"""

from __future__ import annotations

from .rubric import RubricDimension


_SYSTEM = """You are an expert research-brief evaluator for Nestor, a strategic
business research platform. You grade a single quality dimension of a synthesis
brief against a rubric. You output ONLY a JSON object — no preamble, no
markdown fences, no trailing commentary.""".strip()


def build_user_prompt(
    *,
    dimension: RubricDimension,
    synthesis: str,
    mission_brief: dict | None,
    focus_areas: list[str] | None,
) -> str:
    """
    Build the per-dimension judge prompt.

    The prompt structure:
      1. Dimension question + scoring rubric (1-5).
      2. Bad-example anchor with explanation.
      3. Good-example anchor with explanation.
      4. Mission brief context (focus_areas if provided; topic if available).
      5. The synthesis to grade.
      6. CoT instruction: think step-by-step, then output JSON.

    Returns the user message string for Anthropic Messages API.
    """
    mb_context = ""
    if mission_brief:
        topic = mission_brief.get("topic") or mission_brief.get("research_topic")
        if topic:
            mb_context += f"\n  brief topic: {topic}"
    if focus_areas:
        mb_context += f"\n  focus_areas: {focus_areas}"
    if not mb_context:
        mb_context = "\n  (no mission context provided)"

    return f"""# Evaluation task

## Dimension: {dimension.id}

{dimension.question.strip()}

## Anchor — score {dimension.anchor_bad.score} (low end)

Example:
{dimension.anchor_bad.example}

Why this scores {dimension.anchor_bad.score}: {dimension.anchor_bad.why}

## Anchor — score {dimension.anchor_good.score} (high end)

Example:
{dimension.anchor_good.example}

Why this scores {dimension.anchor_good.score}: {dimension.anchor_good.why}

## Mission context
{mb_context}

## Synthesis to grade

{synthesis}

## Your task

Think step-by-step about this brief against the dimension above.
Cite specific passages from the brief in your reasoning where relevant.
Then output a JSON object — and ONLY a JSON object — with this exact shape:

{{
  "dimension": "{dimension.id}",
  "score": <integer 1-5>,
  "reason": "<one-sentence justification anchored on the rubric criteria>",
  "fixes": ["<concrete suggestion 1>", "<concrete suggestion 2>", ...]
}}

Rules:
- score MUST be an integer 1-5.
- reason MUST be one sentence; cite the brief where possible.
- fixes is a (possibly empty) list of concrete improvement suggestions; each
  string ≤ 200 chars; reference specific brief passages by section name where possible.
- Do NOT include markdown fences, preamble, or trailing text outside the JSON.
"""


def system_prompt() -> str:
    """System prompt for the judge — short, role-defining."""
    return _SYSTEM
