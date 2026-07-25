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

Cross-batch cluster identity (G-03, Phase 15.1 — block-then-cluster)
-------------------------------------------------------------------
Exact-string bucketing under-merged badly on the 2026-07-22 run: 163 of 177 groups
were singletons and four flat contradictions shipped, because near-miss labels
across languages (`lukoil|verkoop_internationale_operaties` vs
`lukoil benelux|status_rapport`) never met. Real clustering fixes that, but it is
not embarrassingly parallel the way tagging is: the `ENTITY|ATTRIBUTE` key space is
GLOBAL, so any two claims meet regardless of which batch tagged them, whereas
cluster ids invented by a model inside one call mean nothing in another call. And
1,162 claims do not fit in one 4096-token call.

STRATEGY — block, then cluster within the block:
  Stage 1  Tag every claim `ENTITY | ATTRIBUTE` in batches of `_GROUPER_BATCH`
           (unchanged; ceil(1162/40) = 30 calls, matching the recorded run's
           `grouping: 30` tally).
  Stage 2  BLOCK by `_norm(entity)` ALONE — deliberately coarser than the old
           `entity│attribute` key, so `lukoil|verkoop_internationale_operaties`
           and `lukoil benelux|status_rapport` can still meet.
  Stage 3  For each block holding more than one claim, ONE clustering call assigns
           each claim a block-local cluster id. A block of size 1, and any claim
           whose entity tag came back empty, skip stage 3 entirely (no call).

WHY THE ENTITY TAG IS THE BLOCKING KEY: it already exists, it is already tested,
and it is already merge-happy (`_norm` strips case, spaces and punctuation). Using
it as a pre-filter is the smallest change from the previous code and keeps the
clustering call count proportional to distinct entities rather than to claims.
Cluster ids therefore only ever have to be unique WITHIN one call — the hard
cross-batch reconciliation problem is designed out rather than solved.

NAMESPACING: a block larger than `_CLUSTER_MAX_BLOCK` is split into consecutive
chunks of `_CLUSTER_BATCH` (the blob guard — one runaway entity must not produce a
single unreadable mega-group, and must not blow the output token budget). Chunked
or not, every cluster key is `{block_key}#{chunk_index}#{cluster_id}`, so the id
`0` returned by two different chunks can never collide.

ACCEPTED LIMITATION (one, stated plainly): two claims that state the same fact will
NOT merge if their entity tags normalise differently (e.g. `lukoil` vs
`lukoilbenelux`), or if they land in different chunks of an oversized block. This
is a recall limit, not a correctness bug — an unmerged claim is still verified, it
just gets its own session. How often it bites is MEASURED by the hand-run August
calibration (G-05), never asserted by a CI gate: CI proves the plumbing (no claim
lost, chunks never collide, disabled path unchanged); the calibration run measures
merge quality on real claims.

NEVER-DROP: every failure mode here degrades to "this claim is its own singleton
and still gets verified" — an empty entity tag, a failed cluster call and an
unparseable cluster id all take that path. Clustering may never lose a claim.

A/B: `NESTOR_TRIBUNAL_CLUSTER=false` restores the old exact-key
`entity│attribute` bucketing without a code change.
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

# Clustering pass (G-03). Same NESTOR_TRIBUNAL_* + default idiom as above, so a
# tuning change needs no Cloud Run env change to deploy.
#   _CLUSTER_BATCH       chunk size when an oversized block is split.
#   _CLUSTER_MAX_BLOCK   blob guard: above this a block is chunked, never sent whole.
#   _CLUSTER_CONCURRENCY in-flight clustering calls.
#   _CLUSTER_ENABLED     false -> the pre-15.1 exact-key bucketing (A/B baseline).
_CLUSTER_BATCH = int(os.environ.get("NESTOR_TRIBUNAL_CLUSTER_BATCH", "40"))
_CLUSTER_MAX_BLOCK = int(os.environ.get("NESTOR_TRIBUNAL_CLUSTER_MAX_BLOCK", "60"))
_CLUSTER_CONCURRENCY = int(os.environ.get("NESTOR_TRIBUNAL_CLUSTER_CONCURRENCY", "4"))
_CLUSTER_ENABLED = os.environ.get("NESTOR_TRIBUNAL_CLUSTER", "true").lower() == "true"

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


def _exact_keys(claims: list[dict[str, Any]], flat_tags: list[tuple[str, str]]) -> list[str]:
    """The pre-15.1 bucketing key: normalized `entity│attribute`, exact match.

    Kept as the `_CLUSTER_ENABLED=false` fallback so the old behaviour stays
    reachable for A/B without a code change. Untagged (entity == '') -> a unique
    singleton key, so the claim is still verified on its own."""
    keys: list[str] = []
    for i in range(len(claims)):
        entity, attribute = flat_tags[i] if i < len(flat_tags) else ("", "")
        ne, na = _norm(entity), _norm(attribute)
        keys.append(f"{ne}│{na}" if ne else f"__singleton__:{i}")
    return keys


def _assemble_groups(
    claims: list[dict[str, Any]],
    flat_tags: list[tuple[str, str]],
    keys: list[str],
) -> list[dict[str, Any]]:
    """Build the frozen group dicts from a per-claim key assignment.

    Shared by both bucketing paths so the return shape can only ever be built one
    way. Groups appear in first-member order (deterministic); `entity` and
    `attribute` are the first NON-EMPTY values seen in the group; `stakes` is the
    MAX over members (a group is only as low-stakes as its most important claim).
    """
    groups: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for i, claim in enumerate(claims):
        entity, attribute = flat_tags[i] if i < len(flat_tags) else ("", "")
        key = keys[i]
        g = groups.get(key)
        if g is None:
            g = groups[key] = {
                "key": key,
                "entity": "",
                "attribute": "",
                "claims": [],
                "stakes": "low",
            }
            order.append(key)
        if not g["entity"] and entity.strip():
            g["entity"] = entity.strip()
        if not g["attribute"] and attribute.strip():
            g["attribute"] = attribute.strip()
        g["claims"].append(claim)
        # Inherit the highest stakes of any member.
        cs = (claim.get("stakes") or "med")
        if _STAKES_ORDER.get(cs, 1) > _STAKES_ORDER.get(g["stakes"], 0):
            g["stakes"] = cs
    for g in groups.values():
        # Display fallbacks when the tagger gave the whole group nothing.
        if not g["entity"]:
            g["entity"] = (g["claims"][0].get("facet") or "?")
        if not g["attribute"]:
            g["attribute"] = "general"
    return [groups[k] for k in order]


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

    if not _CLUSTER_ENABLED:
        # A/B baseline: the pre-15.1 exact-key `entity│attribute` bucketing.
        result = _assemble_groups(claims, flat_tags, _exact_keys(claims, flat_tags))
    else:
        # Stages 2+3 (block, then cluster within the block) land in the next
        # commit of this plan; until then the enabled path is byte-identical to
        # the fallback, so the module is never in a broken intermediate state.
        result = _assemble_groups(claims, flat_tags, _exact_keys(claims, flat_tags))

    multi = sum(1 for g in result if len(g["claims"]) > 1)
    log.info(
        "group_claims: %d claims -> %d groups (%d multi-claim, %d singletons)",
        len(claims), len(result), multi, len(result) - multi,
    )
    return result
