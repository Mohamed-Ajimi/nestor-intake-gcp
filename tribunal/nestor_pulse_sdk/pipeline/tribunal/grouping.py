"""Tribunal claim grouping — Tribunal quality plan, Phase 3 (2026-06-13).

WHY: the per-claim skeptic loop verifies each claim in ISOLATION, which (a) costs
~3 LLM calls per claim (≈570 for a 170-claim run) and (b) is structurally blind
to contradictions — two claims that disagree on the same fact each find their own
supporting source and both "pass." Grouping fixes both: claims about the same
`entity | attribute` (e.g. `FootballGPT | pricing`) are verified TOGETHER in one
skeptic session that can reconcile the variants.

This module does ONLY the grouping (the cheap flash tagging + the bucketing). The
group verification itself lives in group_skeptic.py.

Design constraints carried from the rest of the pipeline:
  - gemini-2.5-flash with thinking disabled (CLAUDE.md anti-pattern: thinking
    tokens silently truncate output).
  - PLAIN-TEXT line format, never JSON mode (citations ⊗ structured-outputs = 400).
  - Conservative / merge-happy normalization: over-merging just means one skeptic
    sees slightly more context (harmless); UNDER-merging splits a contradiction
    across groups and makes it invisible again (the failure we are fixing).
  - All LLM egress through audited.gemini_generate (audit hash chain, D-07).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_GROUPER_MODEL = "gemini-2.5-flash"
_GROUPER_BATCH = int(os.environ.get("NESTOR_TRIBUNAL_GROUP_BATCH", "40"))
_GROUPER_CONCURRENCY = int(os.environ.get("NESTOR_TRIBUNAL_GROUP_CONCURRENCY", "4"))

# Stakes ordering so a group inherits the HIGHEST stakes of its members (a group
# is only as low-stakes as its most important claim).
_STAKES_ORDER = {"low": 0, "med": 1, "high": 2}


def _make_config():
    """gemini-flash config with thinking disabled (mirrors the distiller)."""
    try:
        from google.genai import types as genai_types  # noqa: PLC0415
        return genai_types.GenerateContentConfig(
            max_output_tokens=4096,
            temperature=0.0,
            thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
        )
    except Exception:  # noqa: BLE001 — SDK may not support ThinkingConfig
        return None


_TAG_PROMPT = """\
You label research claims so that claims about the SAME thing can be grouped and
fact-checked together. For each claim, output its ENTITY (the main subject —
a product, company, method, market, person) and its ATTRIBUTE (the specific
property being asserted — e.g. pricing, capability, market_size, release_date,
accuracy, availability, definition).

Rules:
- ENTITY: short canonical name. Normalize variants to ONE form (e.g. "FootballGPT",
  "Football GPT", "the FootballGPT app" -> "FootballGPT"). Prefer the shortest
  faithful name. Lowercase is fine.
- ATTRIBUTE: a short snake_case property. Use the SAME attribute word for the same
  kind of fact across claims (all price claims -> "pricing", all capability/feature
  claims -> "capability", all market sizing -> "market_size").
- When unsure, prefer a BROADER entity/attribute so related claims merge. Merging
  is safe; splitting hides contradictions.

Output EXACTLY one line per claim, in input order, in this format (no extra text):
INDEX | ENTITY | ATTRIBUTE

Claims:
{claims_block}
"""


def _norm(s: str) -> str:
    """Normalize a grouping-key token to alphanumerics only (lowercase).

    Merge-happy BY DESIGN: spaces, underscores, hyphens and punctuation are all
    stripped, so "FootballGPT", "Football GPT" and "football-gpt" collapse to the
    same key, and "market_size" == "market size" == "marketsize". Over-merging is
    safe (a group skeptic just sees slightly more context); under-merging would
    split a contradiction across groups and hide it — the failure we are fixing."""
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _parse_tag_lines(text: str, n: int) -> list[tuple[str, str]]:
    """Parse 'INDEX | ENTITY | ATTRIBUTE' lines into [(entity, attribute)] of length n.

    Missing/garbled lines default to ('', '') so the caller can fall back to a
    per-claim singleton group (never drops a claim)."""
    out: list[tuple[str, str]] = [("", "")] * n
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            continue
        idx_raw, entity, attribute = parts[0], parts[1], parts[2]
        m = re.search(r"\d+", idx_raw)
        if not m:
            continue
        idx = int(m.group())
        if 0 <= idx < n:
            out[idx] = (entity, attribute)
    return out


async def _tag_batch(
    claims: list[dict[str, Any]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[tuple[str, str]]:
    """Tag one batch of claims with (entity, attribute). Best-effort: on failure
    every claim in the batch gets ('', '') -> singleton groups."""
    block = "\n".join(
        f"{i} | {(c.get('text') or '')[:240]}" for i, c in enumerate(claims)
    )
    prompt = _TAG_PROMPT.format(claims_block=block)
    config = _make_config()
    kwargs: dict = {"config": config} if config is not None else {}
    try:
        resp = await audited.gemini_generate(
            run_id=run_id, tenant_id=tenant_id, model=_GROUPER_MODEL,
            contents=prompt, **kwargs,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("grouping: tag batch failed (%d claims): %r", len(claims), exc)
        return [("", "")] * len(claims)
    text = getattr(resp, "text", None)
    if not text:
        cands = getattr(resp, "candidates", None) or []
        if cands:
            parts = getattr(getattr(cands[0], "content", None), "parts", None) or []
            if parts:
                text = getattr(parts[0], "text", None) or ""
    return _parse_tag_lines(text or "", len(claims))


async def group_claims(
    *,
    claims: list[dict[str, Any]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Tag claims with entity|attribute and bucket them into groups.

    Returns a list of group dicts:
        {
          "key":       "entity│attribute",   # normalized grouping key
          "entity":    str,                  # display entity (first non-empty seen)
          "attribute": str,
          "claims":    [claim_dict, ...],    # original claim dicts, order preserved
          "stakes":    "low"|"med"|"high",   # MAX stakes across members
        }

    A claim that fails to tag (entity == '') becomes its OWN singleton group keyed
    by its identity — never merged blindly, never dropped.
    """
    if not claims:
        return []

    # Tag in concurrent batches.
    batches = [claims[i:i + _GROUPER_BATCH] for i in range(0, len(claims), _GROUPER_BATCH)]
    sem = asyncio.Semaphore(_GROUPER_CONCURRENCY)

    async def _run(batch):
        async with sem:
            return await _tag_batch(batch, audited, run_id, tenant_id)

    tagged = await asyncio.gather(*(_run(b) for b in batches))
    flat_tags: list[tuple[str, str]] = [t for batch in tagged for t in batch]

    # Bucket by normalized (entity, attribute). Untagged -> unique singleton key.
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for i, claim in enumerate(claims):
        entity, attribute = flat_tags[i] if i < len(flat_tags) else ("", "")
        ne, na = _norm(entity), _norm(attribute)
        if ne:
            key = f"{ne}│{na}"
        else:
            # Untagged: keep it isolated (singleton) so it still gets verified.
            key = f"__singleton__:{i}"
        if key not in groups:
            groups[key] = {
                "key": key,
                "entity": entity.strip() or (claim.get("facet") or "?"),
                "attribute": attribute.strip() or "general",
                "claims": [],
                "stakes": "low",
            }
            order.append(key)
        g = groups[key]
        g["claims"].append(claim)
        # Inherit the highest stakes of any member.
        cs = (claim.get("stakes") or "med")
        if _STAKES_ORDER.get(cs, 1) > _STAKES_ORDER.get(g["stakes"], 0):
            g["stakes"] = cs

    result = [groups[k] for k in order]
    multi = sum(1 for g in result if len(g["claims"]) > 1)
    log.info(
        "group_claims: %d claims -> %d groups (%d multi-claim, %d singletons)",
        len(claims), len(result), multi, len(result) - multi,
    )
    return result
