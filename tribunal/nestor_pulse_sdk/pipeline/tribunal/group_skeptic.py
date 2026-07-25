"""Tribunal GROUP skeptic — Tribunal quality plan, Phase 3 (2026-06-13).

Verifies a GROUP of claim variants (all about the same entity|attribute) in ONE
tool-use session, then emits a per-claim verdict for each plus a reconciliation
across them. This replaces the per-claim skeptic for grouped runs.

Why a group skeptic at all (vs N per-claim skeptics):
  - Cost: one session per group instead of ~3 calls per claim.
  - Correctness: the per-claim skeptic never sees the OTHER variants, so two
    claims that contradict each other each find a supporting source and BOTH
    pass (the two-TacticalPad-prices bug). A group skeptic sees all variants at
    once and is forced to reconcile them (agree / scoped / disputed).

Returns a dict:
    {
      "verdicts_by_index": {i: {verdict, confidence, citations, evidence_refs}},
      "reconciliation":    {disputed, relation, note, canonical},
      "citations":         [url, ...],   # all evidence URLs the skeptic fetched
    }

Same hard constraints as run_skeptic: hand-written async loop over
audited.anthropic_messages (NOT the agent SDK), server-tool protocol (never
append a synthetic tool_result for web_search/web_fetch), final turn forces the
client tool.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from nestor_pulse_sdk.pipeline.tribunal.tools import (
    EMIT_GROUP_VERDICT_TOOL,
    build_web_fetch,
    build_web_search,
    force_emit_group_verdict,
)
from nestor_pulse_sdk.pipeline.tribunal.skeptic import (
    _collect_citation_urls,
    _content_to_serialisable,
    _block_get,
    _coerce_json,
)

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_MAX_TURNS_DEFAULT = 4
_GROUP_MAX_TOKENS = 8192

_GROUP_SYSTEM = """\
You are a rigorous fact-checking skeptic verifying a GROUP of related claims that
all concern the same subject and property. Your job:

1. Use web_search to find independent sources, then web_fetch to read them.
2. Decide a verdict for EACH claim (by its index): support / refute / insufficient / superseded.
   - support: independent evidence corroborates it.
   - refute: an independent fetched source contradicts it (MUST cite; never refute
     on absence of evidence alone).
   - insufficient: ambiguous or not enough evidence.
   - superseded: the claim was TRUE when written but has been overtaken by a later
     change. You MUST state what changed and from when in `superseded_note` — quote
     the fetched source; never phrase it from memory. Do not use `refute` for an
     overtaken-but-once-true fact.
3. RECONCILE the variants against each other and report how they relate:
   - agree: they state the same fact.
   - scoped: they look different but are actually different tiers / dates / regions
     / segments — say which in the note.
   - disputed: they genuinely contradict and cannot be reconciled — set disputed=true.
   - single: only one claim in the group.
   Give the best current canonical value when one exists.

Finish by calling emit_group_verdict exactly once.
"""


def _extract_group_verdict_block(content: list[Any]) -> Any | None:
    for block in content:
        btype = _block_get(block, "type")
        bname = _block_get(block, "name")
        if btype == "tool_use" and bname == "emit_group_verdict":
            return block
    return None


def _parse_group_verdict(block: Any, n_claims: int, citations: list[str]) -> dict[str, Any]:
    """Map an emit_group_verdict tool_use block to per-claim verdicts + reconciliation.

    Robust to a model that omits a claim, returns a bad index, or skips fields:
    any claim without an explicit verdict defaults to 'insufficient' (survives
    adjudication — we never silently drop a claim on a parsing miss)."""
    inp = block.get("input") if isinstance(block, dict) else getattr(block, "input", {})
    # F-01 hardening (run 4cbb5311): the model may return `input` itself, or its
    # reconciliation / verdicts / evidence_refs fields, as JSON-encoded STRINGS
    # instead of objects — coerce each before any .get access, falling back to
    # the existing defaults (so claims still default to 'insufficient').
    inp = _coerce_json(inp, dict) or {}
    recon = _coerce_json(inp.get("reconciliation"), dict) or {}
    raw_verdicts = _coerce_json(inp.get("verdicts"), list) or []
    evidence = list(_coerce_json(inp.get("evidence_refs"), list) or [])

    by_index: dict[int, dict[str, Any]] = {}
    for v in raw_verdicts:
        if not isinstance(v, dict):
            continue
        try:
            idx = int(v.get("claim_index"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < n_claims:
            by_index[idx] = {
                "verdict": v.get("verdict", "insufficient"),
                "confidence": float(v.get("confidence", 0.0) or 0.0),
                "evidence_refs": evidence,
                "citations": list(citations),
            }
    # Fill any missing claim with insufficient (so it survives, not silently dropped).
    for i in range(n_claims):
        by_index.setdefault(i, {
            "verdict": "insufficient", "confidence": 0.0,
            "evidence_refs": evidence, "citations": list(citations),
        })

    return {
        "verdicts_by_index": by_index,
        "reconciliation": {
            "disputed": bool(recon.get("disputed", False)),
            "relation": recon.get("relation", "single" if n_claims == 1 else "agree"),
            "note": recon.get("note", ""),
            "canonical": recon.get("canonical", ""),
        },
        "citations": list(citations),
    }


def _insufficient_group(n_claims: int, citations: list[str]) -> dict[str, Any]:
    return {
        "verdicts_by_index": {
            i: {"verdict": "insufficient", "confidence": 0.0,
                "evidence_refs": [], "citations": list(citations)}
            for i in range(n_claims)
        },
        "reconciliation": {"disputed": False, "relation": "single" if n_claims == 1 else "agree",
                           "note": "", "canonical": ""},
        "citations": list(citations),
    }


async def run_group_skeptic(
    *,
    group: dict[str, Any],
    sources: list[dict[str, Any]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    model: str,
    max_turns: int = _MAX_TURNS_DEFAULT,
    max_search_uses: int = 5,
    max_fetch_uses: int = 3,
) -> dict[str, Any]:
    """Verify one claim group and return per-claim verdicts + a reconciliation.

    ONE thorough session per group (not N independent skeptics). Stakes controls
    DEPTH via (max_turns, max_search_uses, max_fetch_uses) — higher-stakes groups
    get more searches/fetches in their single session — rather than more sessions.

    Args:
        group:   {entity, attribute, claims: [claim_dict, ...], stakes}.
        sources: prior research sources for context (URL + snippet).
        model:   Anthropic model string.
        max_turns/max_search_uses/max_fetch_uses: per-session depth budget.
    """
    claims = group.get("claims") or []
    n = len(claims)
    if n == 0:
        return _insufficient_group(0, [])

    entity = group.get("entity", "?")
    attribute = group.get("attribute", "?")
    claims_block = "\n".join(
        f"[{i}] {(c.get('text') or '')}" for i, c in enumerate(claims)
    )
    sources_text = "\n".join(
        f"- {s.get('url','unknown')} — {s.get('snippet','')}" for s in sources
    ) or "(no prior sources)"

    shared_block = {
        "type": "text",
        "text": (
            f"SUBJECT: {entity}  |  PROPERTY: {attribute}\n\n"
            f"CLAIMS TO EVALUATE (verify each by its [index], then reconcile them):\n"
            f"{claims_block}\n\n"
            f"PRIOR SOURCES (for context):\n{sources_text}"
        ),
        "cache_control": {"type": "ephemeral"},
    }
    msgs: list[dict[str, Any]] = [{"role": "user", "content": [shared_block]}]
    tools = [
        build_web_search(max_uses=max_search_uses),
        build_web_fetch(max_uses=max_fetch_uses, max_content_tokens=4000),
        EMIT_GROUP_VERDICT_TOOL,
    ]
    collected: list[str] = []

    for turn in range(1, max_turns + 1):
        call_kwargs: dict[str, Any] = {"system": _GROUP_SYSTEM}
        if turn == max_turns:
            call_kwargs["tool_choice"] = force_emit_group_verdict()

        resp = await audited.anthropic_messages(
            run_id=run_id, tenant_id=tenant_id, model=model,
            messages=msgs, tools=tools, max_tokens=_GROUP_MAX_TOKENS, **call_kwargs,
        )
        content = resp.content if isinstance(resp.content, list) else []
        for u in _collect_citation_urls(content):
            if u not in collected:
                collected.append(u)

        if resp.stop_reason == "tool_use":
            vblock = _extract_group_verdict_block(content)
            if vblock is not None:
                return _parse_group_verdict(vblock, n, collected)
            # server tools used — append assistant turn, no synthetic tool_result
            msgs.append({"role": "assistant", "content": _content_to_serialisable(content)})
        else:
            log.warning(
                "group_skeptic: unexpected stop_reason %r on turn %d (%s|%s, %d claims) — insufficient",
                resp.stop_reason, turn, entity, attribute, n,
            )
            return _insufficient_group(n, collected)

    log.error("group_skeptic: loop exhausted without emit_group_verdict — insufficient")
    return _insufficient_group(n, collected)
