"""Blind head-to-head critique of two engine reports (2026-06-11).

Objectivity measures (each one matters — do not remove casually):

  1. BLIND INPUT. The judge receives only the client brief and two reports
     labelled "Report A" / "Report B". Engine names are masked, and process
     metadata that would identify the engine or its workflow (the Tribunal's
     "## Verification" appendix, any human-interaction traces) is stripped by
     sanitize_report(). The A/B assignment is randomised per critique.

  2. DOUBLE-PASS, ORDER-SWAPPED. LLM judges have a measurable position bias
     (they favour the report shown first). We judge twice — (A,B) then with
     the documents swapped — map the second pass's labels back, average the
     scores, and declare a winner ONLY when both passes agree; otherwise tie.

  3. DIFFERENT MODEL FAMILY. Both engines' final reports are written by
     Gemini; the judge is Claude. Same-family judges measurably prefer their
     own writing style (self-preference bias).

  4. EVIDENCE-REQUIRED SCORING. Every dimension score must cite verbatim
     quotes from the reports; unsupported scores are a known judge failure
     mode. Length is explicitly excluded as a quality signal.

All LLM calls go through AuditedLLMClient (D-07 audit chain).
"""
from __future__ import annotations

import json
import logging
import re
import secrets as _secrets
import uuid
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_JUDGE_MODEL = "claude-sonnet-4-6"
_JUDGE_MAX_TOKENS = 4096

#: Engine/product words masked from the reports before judging. The judge must
#: not be able to infer which system produced which document.
_IDENTITY_WORDS = ("tribunal", "adk", "nestor", "sdk pipeline")

_DIMENSIONS = ("clarity", "content", "robustness")


def sanitize_report(text: str) -> str:
    """Strip process metadata and engine identity from a report body.

    - Removes the deterministic "## Verification" appendix (it describes the
      engine's workflow — exactly the information the judge must not see).
    - Removes a leading LLM preamble line ("Of course. Here is ...").
    - Masks engine/product names with a neutral token.
    """
    text = text or ""

    # Verification appendix: appended as "\n\n---\n\n## Verification" (en or
    # rendered variants). Cut from the LAST occurrence of a Verification H2.
    m = None
    for match in re.finditer(r"^##\s+Verificati\w*\s*$", text, re.MULTILINE | re.IGNORECASE):
        m = match
    if m:
        cut = text.rfind("---", 0, m.start())
        text = text[: cut if cut != -1 and m.start() - cut < 20 else m.start()]

    # Leading conversational preamble ("Of course. Here is the report ...").
    lines = text.lstrip().splitlines()
    if lines and re.match(
        r"^(of course|certainly|here is|sure|natuurlijk|uiteraard|voici|hier is)\b",
        lines[0].strip(), re.IGNORECASE,
    ) and not lines[0].lstrip().startswith("#"):
        lines = lines[1:]
    text = "\n".join(lines)

    # Mask engine identity words (case-insensitive, word-boundary).
    for word in _IDENTITY_WORDS:
        text = re.sub(rf"(?i)\b{re.escape(word)}\b", "[the research system]", text)

    return text.strip()


def _extract_json_object(raw: str) -> dict:
    """Tolerantly pull one JSON object out of an LLM response (handles fences)."""
    if not raw:
        return {}
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, dict) else {}
    except Exception as exc:
        log.warning("critique: could not parse judge JSON: %s", exc)
        return {}


def _judge_prompt(brief: str, report_a: str, report_b: str) -> str:
    return (
        "You are an independent report evaluator. Two research teams answered the "
        "same client brief; you are given their final reports as Report A and "
        "Report B. You know NOTHING about who or what produced them, and you must "
        "judge ONLY what is on the page, applying identical standards to both.\n"
        "\n"
        "Anti-bias rules:\n"
        "  - Length is NOT quality. Do not reward verbosity or repetition; a "
        "shorter report that answers the brief fully may outscore a longer one.\n"
        "  - Formatting polish is NOT evidence. Judge substance.\n"
        "  - Every score must be justified with at least one VERBATIM quote from "
        "each report. No quote, no score.\n"
        "  - Judge each dimension independently — a report may win one dimension "
        "and lose another.\n"
        "\n"
        "Score both reports 0-10 on each dimension:\n"
        "\n"
        "1. CLARITY — Can a decision-maker extract the answers fast? Conclusions "
        "stated up front; logical structure that follows the brief's questions; "
        "readable prose; no internal repetition or filler.\n"
        "2. CONTENT — Does it actually answer the brief? Every question covered "
        "at the depth asked; specific, decision-relevant facts (named entities, "
        "numbers, dates) rather than generic statements; mechanisms and "
        "implications explained, not just facts listed; concrete, actionable "
        "recommendations.\n"
        "3. ROBUSTNESS — Would it survive challenge? Claims tied to identifiable "
        "evidence or source references; uncertainty and evidence strength "
        "acknowledged where appropriate (hedged where thin, confident where "
        "strong); internally consistent (no self-contradictions); no signs of "
        "overclaiming (suspiciously precise figures with no support).\n"
        "\n"
        "Then hunt for CONFLICTING FACTS: statements where the two reports give "
        "incompatible numbers, dates, or facts about the SAME thing (e.g. the same "
        "company's market share stated differently). Quote both sides verbatim. "
        "Different topics or non-overlapping facts are NOT conflicts.\n"
        "\n"
        "Return ONLY a JSON object, no other text:\n"
        "{\n"
        '  "dimensions": {\n'
        '    "clarity":    {"a": <0-10>, "b": <0-10>, "rationale": "<2-3 sentences>", '
        '"evidence_a": "<verbatim quote>", "evidence_b": "<verbatim quote>"},\n'
        '    "content":    {…same shape…},\n'
        '    "robustness": {…same shape…}\n'
        "  },\n"
        '  "conflicting_facts": [\n'
        '    {"topic": "<what they disagree on>", "report_a_says": "<verbatim>", '
        '"report_b_says": "<verbatim>", "severity": "minor"|"material"}\n'
        "  ],\n"
        '  "overall": {"winner": "A"|"B"|"tie", "rationale": "<3-4 sentences>"}\n'
        "}\n"
        "\n"
        f"=== CLIENT BRIEF ===\n{brief}\n=== END BRIEF ===\n"
        "\n"
        f"=== REPORT A ===\n{report_a}\n=== END REPORT A ===\n"
        "\n"
        f"=== REPORT B ===\n{report_b}\n=== END REPORT B ===\n"
    )


async def _judge_once(
    *,
    brief: str,
    report_a: str,
    report_b: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """One judging pass. Returns the parsed JSON verdict (possibly {})."""
    resp = await audited.anthropic_messages(
        run_id=run_id,
        tenant_id=tenant_id,
        model=_JUDGE_MODEL,
        max_tokens=_JUDGE_MAX_TOKENS,
        temperature=0.0,
        messages=[{
            "role": "user",
            "content": _judge_prompt(brief, report_a, report_b),
        }],
    )
    text = ""
    for block in getattr(resp, "content", None) or []:
        t = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if t:
            text += t
    return _extract_json_object(text)


def _swap_verdict(v: dict) -> dict:
    """Map a verdict produced on swapped documents back to original labels."""
    out: dict = {"dimensions": {}, "conflicting_facts": [], "overall": {}}
    for dim, d in (v.get("dimensions") or {}).items():
        if not isinstance(d, dict):
            continue
        out["dimensions"][dim] = {
            **d,
            "a": d.get("b"),
            "b": d.get("a"),
            "evidence_a": d.get("evidence_b", ""),
            "evidence_b": d.get("evidence_a", ""),
        }
    for c in v.get("conflicting_facts") or []:
        if isinstance(c, dict):
            out["conflicting_facts"].append({
                **c,
                "report_a_says": c.get("report_b_says", ""),
                "report_b_says": c.get("report_a_says", ""),
            })
    overall = v.get("overall") or {}
    winner = overall.get("winner")
    out["overall"] = {
        **overall,
        "winner": {"A": "B", "B": "A"}.get(winner, winner),
    }
    return out


def _num(x: Any) -> float | None:
    try:
        f = float(x)
        return f if 0 <= f <= 10 else None
    except (TypeError, ValueError):
        return None


def _merge_passes(p1: dict, p2: dict) -> dict:
    """Average scores across the two order-swapped passes; consensus winner."""
    merged: dict = {"dimensions": {}, "conflicting_facts": [], "overall": {}}

    for dim in _DIMENSIONS:
        d1 = (p1.get("dimensions") or {}).get(dim) or {}
        d2 = (p2.get("dimensions") or {}).get(dim) or {}
        scores_a = [s for s in (_num(d1.get("a")), _num(d2.get("a"))) if s is not None]
        scores_b = [s for s in (_num(d1.get("b")), _num(d2.get("b"))) if s is not None]
        merged["dimensions"][dim] = {
            "a": round(sum(scores_a) / len(scores_a), 1) if scores_a else None,
            "b": round(sum(scores_b) / len(scores_b), 1) if scores_b else None,
            "rationale": d1.get("rationale") or d2.get("rationale") or "",
            "evidence_a": d1.get("evidence_a") or d2.get("evidence_a") or "",
            "evidence_b": d1.get("evidence_b") or d2.get("evidence_b") or "",
            "pass_agreement": (
                _num(d1.get("a")) is not None and _num(d2.get("a")) is not None
                and abs(_num(d1.get("a")) - _num(d2.get("a"))) <= 2
                and abs(_num(d1.get("b")) - _num(d2.get("b"))) <= 2
            ),
        }

    # Conflicts: union of both passes, deduped by topic (case-folded).
    seen_topics: set[str] = set()
    for c in (p1.get("conflicting_facts") or []) + (p2.get("conflicting_facts") or []):
        if not isinstance(c, dict):
            continue
        key = str(c.get("topic", "")).strip().lower()[:80]
        if key and key not in seen_topics:
            seen_topics.add(key)
            merged["conflicting_facts"].append(c)

    w1 = (p1.get("overall") or {}).get("winner")
    w2 = (p2.get("overall") or {}).get("winner")
    if w1 in ("A", "B") and w1 == w2:
        winner = w1
    else:
        winner = "tie"
    merged["overall"] = {
        "winner": winner,
        "consensus": w1 == w2,
        "rationale": (p1.get("overall") or {}).get("rationale", ""),
        "rationale_swapped_pass": (p2.get("overall") or {}).get("rationale", ""),
    }
    return merged


async def run_blind_critique(
    *,
    brief: str,
    reports_by_engine: dict[str, str],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Judge two engines' reports blind. Returns the de-anonymised result dict.

    Args:
        brief:             The client brief (base text, without clarification blocks).
        reports_by_engine: Exactly two entries {engine_name: report_markdown}.
        audited:           AuditedLLMClient (the only LLM egress).
        run_id:            Run UUID to anchor the audit rows.
        tenant_id:         Tenant UUID.

    Returns:
        {
          "label_map": {"A": engine, "B": engine},   # revealed AFTER judging
          "dimensions": {dim: {"a", "b", "rationale", "evidence_a", "evidence_b",
                               "pass_agreement"}},
          "conflicting_facts": [...],
          "overall": {"winner": "A"|"B"|"tie", "consensus": bool, ...},
          "method": {...}                            # how objectivity was enforced
        }
    """
    if len(reports_by_engine) != 2:
        raise ValueError(f"blind critique needs exactly 2 reports, got {len(reports_by_engine)}")

    engines = list(reports_by_engine.keys())
    # Random blind assignment — the judge never sees engine names at all;
    # the mapping is only used to de-anonymise the result for the UI.
    if _secrets.randbelow(2):
        engines.reverse()
    label_map = {"A": engines[0], "B": engines[1]}

    report_a = sanitize_report(reports_by_engine[engines[0]])
    report_b = sanitize_report(reports_by_engine[engines[1]])
    brief_clean = (brief or "").split("[CLARIFICATION ANSWERS]")[0].strip()

    pass1 = await _judge_once(
        brief=brief_clean, report_a=report_a, report_b=report_b,
        audited=audited, run_id=run_id, tenant_id=tenant_id,
    )
    pass2_raw = await _judge_once(
        brief=brief_clean, report_a=report_b, report_b=report_a,  # swapped
        audited=audited, run_id=run_id, tenant_id=tenant_id,
    )
    pass2 = _swap_verdict(pass2_raw)

    if not pass1 and not pass2:
        raise RuntimeError("blind critique: both judge passes returned unparseable output")

    merged = _merge_passes(pass1 or pass2, pass2 or pass1)
    merged["label_map"] = label_map
    merged["method"] = {
        "judge_model": _JUDGE_MODEL,
        "blind": True,
        "order_swapped_double_pass": True,
        "identity_masking": True,
        "process_metadata_stripped": True,
    }

    log.info(
        "blind_critique: winner=%s consensus=%s conflicts=%d (A=%s, B=%s)",
        merged["overall"]["winner"], merged["overall"]["consensus"],
        len(merged["conflicting_facts"]), label_map["A"], label_map["B"],
    )
    return merged
