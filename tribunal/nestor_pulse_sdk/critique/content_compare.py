"""Deep content comparison of two engine reports (2026-06-14).

Heavier companion to the blind score critique (critique/judge.py). Where the
judge produces 0-10 dimension SCORES, this produces an exhaustive, objective
CONTENT map plus a rejected-claims cross-check:

  1. CONTENT OVERLAP (blind, one LLM pass). Buckets the two reports' substantive
     points into shared / only-A / only-B, flags each unique point as
     decision-relevant or filler, characterises each report's internal
     redundancy, and explains whether a size difference is more information or
     more repetition. Engine identity is masked exactly as in the score critique
     (sanitize_report + randomised A/B), revealed only via label_map.

  2. REJECTED-CLAIMS CROSS-CHECK (not blind — inherently asymmetric). For the
     engine that fact-checks and DROPS claims (Tribunal), each rejected claim is
     checked against the OTHER engine's final report: does that report still
     assert the same thing? A "yes" is a verified-vs-unverified signal — one
     engine threw the claim out after web verification; the other kept it.

Both LLM calls go through AuditedLLMClient (D-07 audit chain) and reuse the
score critique's masking + JSON-extraction helpers so the two stay consistent.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, TYPE_CHECKING

from nestor_pulse_sdk.critique.judge import (
    sanitize_report,
    _extract_json_object,
)

import secrets as _secrets

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 6144
_CROSSCHECK_MAX_CLAIMS = 40  # cap the cross-check prompt size (loudly truncated)


# ---------------------------------------------------------------------------
# 1. Content overlap (blind)
# ---------------------------------------------------------------------------
def _content_prompt(brief: str, report_a: str, report_b: str) -> str:
    return (
        "You are an impartial analyst comparing two research reports that answer "
        "the SAME client brief. You know NOTHING about who produced them. Produce "
        "an EXHAUSTIVE, OBJECTIVE content comparison — what each report actually "
        "contains — NOT a quality score.\n"
        "\n"
        "Rules:\n"
        "  - Length is NOT quality. A longer report is not automatically richer.\n"
        "  - Compare SUBSTANCE: named entities, numbers, mechanisms, concrete "
        "recommendations — not tone or formatting.\n"
        "  - A point is 'shared' only if BOTH reports make substantially the same "
        "claim. Otherwise it is unique to one side.\n"
        "  - For every unique point, judge honestly whether it is decision-relevant "
        "(a fact a client would act on) or filler/generic.\n"
        "  - Be specific and quote figures where they exist.\n"
        "\n"
        "Return ONLY a JSON object, no other text:\n"
        "{\n"
        '  "shared": ["<concise substantive point present in BOTH>", ...],\n'
        '  "only_a": [{"point": "<in A, absent from B>", "decision_relevant": true|false, "note": "<why it matters or why it is filler>"}],\n'
        '  "only_b": [{"point": "<in B, absent from A>", "decision_relevant": true|false, "note": "<...>"}],\n'
        '  "redundancy": {"a": "<1-2 sentences: how repetitive is A; repeated scaffolding/restated conclusions>", "b": "<same for B>"},\n'
        '  "size_characterization": "<2-3 sentences: if one report is materially longer, is that extra length mostly NEW information, or mostly redundancy/padding? Be quantitative where you can.>",\n'
        '  "coverage_gaps": ["<any brief question or sub-topic that ONE report covers and the other misses or under-answers>", ...]\n'
        "}\n"
        "\n"
        f"=== CLIENT BRIEF ===\n{brief}\n=== END BRIEF ===\n"
        "\n"
        f"=== REPORT A ===\n{report_a}\n=== END REPORT A ===\n"
        "\n"
        f"=== REPORT B ===\n{report_b}\n=== END REPORT B ===\n"
    )


async def _compare_content(
    *,
    brief: str,
    report_a: str,
    report_b: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    resp = await audited.anthropic_messages(
        run_id=run_id,
        tenant_id=tenant_id,
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
        messages=[{"role": "user", "content": _content_prompt(brief, report_a, report_b)}],
    )
    text = ""
    for block in getattr(resp, "content", None) or []:
        t = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if t:
            text += t
    return _extract_json_object(text)


# ---------------------------------------------------------------------------
# 2. Rejected-claims cross-check (asymmetric — not blind)
# ---------------------------------------------------------------------------
def _crosscheck_prompt(rejected: list[dict], other_report: str) -> str:
    lines = []
    for i, rc in enumerate(rejected):
        reason = rc.get("reason", "")
        lines.append(f"{i+1}. [{reason}] {rc.get('text','').strip()}")
    claims_block = "\n".join(lines)
    return (
        "One research team EXTRACTED the claims below but then REJECTED each one "
        "during fact-checking — either it failed verification against the live web "
        "(failed_factcheck) or it lost a head-to-head conflict with a better-sourced "
        "claim (lost_conflict).\n"
        "\n"
        "Your job: for EACH rejected claim, decide whether the OTHER team's final "
        "report (below) still ASSERTS substantially the same thing. This surfaces "
        "claims one team discarded as unreliable but the other team kept.\n"
        "\n"
        "Rules:\n"
        "  - 'present: true' ONLY if the other report makes the same factual "
        "assertion (same entity + same claim). A loosely related mention is NOT a "
        "match — be strict.\n"
        "  - If present, quote the supporting sentence VERBATIM as evidence.\n"
        "  - If absent, evidence must be an empty string.\n"
        "\n"
        "Return ONLY a JSON object:\n"
        "{\n"
        '  "results": [\n'
        '    {"index": <1-based claim number>, "present": true|false, "evidence": "<verbatim quote from the OTHER report, or \\"\\">"}\n'
        "  ]\n"
        "}\n"
        "\n"
        f"=== REJECTED CLAIMS ===\n{claims_block}\n=== END REJECTED CLAIMS ===\n"
        "\n"
        f"=== OTHER TEAM'S REPORT ===\n{other_report}\n=== END OTHER TEAM'S REPORT ===\n"
    )


async def _crosscheck_rejected(
    *,
    rejected: list[dict],
    other_report: str,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[dict]:
    """Annotate each rejected claim with present-in-other + evidence."""
    capped = rejected[:_CROSSCHECK_MAX_CLAIMS]
    if len(rejected) > _CROSSCHECK_MAX_CLAIMS:
        log.warning(
            "content_compare: cross-check truncated %d -> %d rejected claims",
            len(rejected), _CROSSCHECK_MAX_CLAIMS,
        )
    resp = await audited.anthropic_messages(
        run_id=run_id,
        tenant_id=tenant_id,
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        temperature=0.0,
        messages=[{"role": "user", "content": _crosscheck_prompt(capped, other_report)}],
    )
    text = ""
    for block in getattr(resp, "content", None) or []:
        t = getattr(block, "text", None) or (block.get("text") if isinstance(block, dict) else None)
        if t:
            text += t
    parsed = _extract_json_object(text)
    by_index = {}
    for r in (parsed.get("results") or []):
        if isinstance(r, dict) and isinstance(r.get("index"), (int, float)):
            by_index[int(r["index"])] = r

    out: list[dict] = []
    for i, rc in enumerate(capped):
        r = by_index.get(i + 1, {})
        out.append({
            "text": rc.get("text", ""),
            "facet": rc.get("facet", ""),
            "reason": rc.get("reason", ""),
            "present_in_other": bool(r.get("present")),
            "evidence": (r.get("evidence") or "").strip(),
        })
    return out


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------
async def run_content_comparison(
    *,
    brief: str,
    reports_by_engine: dict[str, str],
    rejected_by_engine: dict[str, list[dict]] | None,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Deep content comparison + rejected-claims cross-check for two engines.

    Args:
        brief:              Client brief (clarification blocks stripped here).
        reports_by_engine:  Exactly two {engine: report_markdown}.
        rejected_by_engine: {engine: [{text, facet, reason}, ...]} — the claims
                            each engine fact-checked and dropped (empty/absent for
                            engines that don't verify, e.g. ADK).
        audited:            AuditedLLMClient (only LLM egress).
        run_id, tenant_id:  Audit-chain anchors.

    Returns:
        {
          "label_map": {"A": engine, "B": engine},
          "content": {shared, only_a, only_b, redundancy, size_characterization, coverage_gaps},
          "rejected_crosscheck": {"verifier": engine, "other": engine, "claims": [...]} | None,
          "method": {...}
        }
    """
    if len(reports_by_engine) != 2:
        raise ValueError(f"content comparison needs exactly 2 reports, got {len(reports_by_engine)}")

    engines = list(reports_by_engine.keys())
    if _secrets.randbelow(2):
        engines.reverse()
    label_map = {"A": engines[0], "B": engines[1]}

    report_a = sanitize_report(reports_by_engine[engines[0]])
    report_b = sanitize_report(reports_by_engine[engines[1]])
    brief_clean = (brief or "").split("[CLARIFICATION ANSWERS]")[0].strip()

    content = await _compare_content(
        brief=brief_clean, report_a=report_a, report_b=report_b,
        audited=audited, run_id=run_id, tenant_id=tenant_id,
    )

    # Rejected-claims cross-check: only for an engine that actually dropped claims.
    # Cross-check its rejects against the OTHER engine's (unsanitized — we want the
    # real assertions) report. Pick the engine with the most rejected claims.
    rejected_crosscheck = None
    rejected_by_engine = rejected_by_engine or {}
    verifier = max(
        (e for e in reports_by_engine if rejected_by_engine.get(e)),
        key=lambda e: len(rejected_by_engine.get(e) or []),
        default=None,
    )
    if verifier:
        other = next(e for e in reports_by_engine if e != verifier)
        claims = await _crosscheck_rejected(
            rejected=rejected_by_engine[verifier],
            other_report=reports_by_engine[other],
            audited=audited, run_id=run_id, tenant_id=tenant_id,
        )
        rejected_crosscheck = {
            "verifier": verifier,
            "other": other,
            "total_rejected": len(rejected_by_engine[verifier]),
            "claims": claims,
            "kept_by_other_count": sum(1 for c in claims if c["present_in_other"]),
        }

    log.info(
        "content_comparison: A=%s B=%s shared=%d only_a=%d only_b=%d crosscheck=%s",
        label_map["A"], label_map["B"],
        len(content.get("shared") or []), len(content.get("only_a") or []),
        len(content.get("only_b") or []),
        (rejected_crosscheck or {}).get("kept_by_other_count") if rejected_crosscheck else "none",
    )

    return {
        "label_map": label_map,
        "content": content,
        "rejected_crosscheck": rejected_crosscheck,
        "method": {
            "model": _MODEL,
            "content_blind": True,
            "identity_masking": True,
            "rejected_crosscheck_note": "asymmetric: verifier's dropped claims checked against the other report",
        },
    }
