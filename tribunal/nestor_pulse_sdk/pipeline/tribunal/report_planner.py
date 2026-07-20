"""Tribunal report planner — the pre-synthesis shaping step (2026-06-14).

After verification + scrubbing, but BEFORE the final report is written, this
LLM reads the (scrubbed) research and proposes HOW to shape the report so the
user can steer it:

  - per focus area: include or drop, and how deep the research actually supports
    going (thin vs rich), with a one-line rationale grounded in the research;
  - a recommended overall length (brief / standard / comprehensive);
  - a recommended table density (none / key / heavy).

The user accepts or edits this into a `report_spec`, which drives
synthesize_report. Pure proposal — no report is written here.

LLM invariants mirror intake.py: gemini-2.5-flash, thinking disabled, plain-text
line format (NOT JSON — avoids the gemini structured-output truncation noted in
CLAUDE.md), routed through audited.gemini_generate.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, TYPE_CHECKING

from google.genai import types as genai_types  # noqa: TC002

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

_PLANNER_MODEL = "gemini-2.5-flash"
_MAX_OUTPUT_TOKENS = 1536
_RESEARCH_CHAR_BUDGET = 60_000  # cap the prose fed to the planner (cost guard)

LENGTH_OPTIONS = ["brief", "standard", "comprehensive"]
TABLE_OPTIONS = ["none", "key", "heavy"]

_PROMPT_TEMPLATE = """\
You are a report-shaping planner. Verified, fact-checked research has been
gathered to answer a client's questions. Your job is NOT to write the report —
it is to PROPOSE how the report should be shaped, so the client can steer it.

Each focus area below is one of the client's questions. Using ONLY what the
research actually contains, decide for EACH:
  - INCLUDE: should this focus area get its own section? (yes unless the research
    is essentially empty on it)
  - DEPTH: does the research support a RICH section (lots of specific, verified
    detail) or only a THIN one (sparse / mostly gaps)?
  - RATIONALE: one short, concrete line citing what the research does/doesn't
    have for this focus area.

Then recommend an overall LENGTH and TABLE density for the whole report:
  - LENGTH: brief (tight, decision-first) | standard | comprehensive (maximal detail)
  - TABLES: none | key (a few comparison/data tables where they add clarity) |
    heavy (data-dense, many tables)
Base these on how much verified, structured detail the research actually holds.

=== FOCUS AREAS (the client's questions) ===
{focus_block}
=== END FOCUS AREAS ===

=== VERIFIED RESEARCH (already fact-checked; may be truncated) ===
{research}
=== END RESEARCH ===

Output EXACTLY these lines, nothing else:
LENGTH_RECOMMENDED: <brief|standard|comprehensive>
TABLES_RECOMMENDED: <none|key|heavy>
Then ONE line per focus area, in the same order, EXACTLY:
FOCUS: <label> | INCLUDE: <yes|no> | DEPTH: <rich|thin> | RATIONALE: <one line>
"""


def _make_config() -> object:
    try:
        thinking = genai_types.ThinkingConfig(thinking_budget=0)
    except Exception:
        thinking = None
    kwargs: dict = {"max_output_tokens": _MAX_OUTPUT_TOKENS, "temperature": 0.0}
    if thinking is not None:
        kwargs["thinking_config"] = thinking
    return genai_types.GenerateContentConfig(**kwargs)


def _focus_labels(mission_brief: dict) -> list[str]:
    out: list[str] = []
    for fa in (mission_brief.get("focus_areas") or []):
        label = (fa.get("focus_area") or "").strip()
        if label:
            out.append(label)
    return out


def default_proposal(mission_brief: dict) -> dict:
    """Conservative fallback: keep every focus area, standard length, key tables."""
    return {
        "focus_areas": [
            {"label": lbl, "recommended_include": True, "depth": "rich", "rationale": ""}
            for lbl in _focus_labels(mission_brief)
        ],
        "length": {"recommended": "standard", "options": LENGTH_OPTIONS},
        "tables": {"recommended": "key", "options": TABLE_OPTIONS},
    }


def _parse(text: str, labels: list[str]) -> dict:
    length = "standard"
    tables = "key"
    fa_by_label: dict[str, dict] = {}

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.upper().startswith("LENGTH_RECOMMENDED:"):
            v = line.split(":", 1)[1].strip().lower()
            if v in LENGTH_OPTIONS:
                length = v
        elif line.upper().startswith("TABLES_RECOMMENDED:"):
            v = line.split(":", 1)[1].strip().lower()
            if v in TABLE_OPTIONS:
                tables = v
        elif line.upper().startswith("FOCUS:"):
            parts = [p.strip() for p in line.split("|")]
            label = parts[0].split(":", 1)[1].strip() if ":" in parts[0] else ""
            include = True
            depth = "rich"
            rationale = ""
            for p in parts[1:]:
                up = p.upper()
                if up.startswith("INCLUDE:"):
                    include = p.split(":", 1)[1].strip().lower().startswith("y")
                elif up.startswith("DEPTH:"):
                    depth = "thin" if "thin" in p.lower() else "rich"
                elif up.startswith("RATIONALE:"):
                    rationale = p.split(":", 1)[1].strip()
            if label:
                fa_by_label[label.lower()] = {
                    "label": label, "recommended_include": include,
                    "depth": depth, "rationale": rationale,
                }

    # Reconcile against the canonical label list (never drop/add a focus area:
    # the planner only *annotates* the real focus areas; unknown lines ignored).
    focus_areas: list[dict] = []
    for lbl in labels:
        match = fa_by_label.get(lbl.lower())
        focus_areas.append(match or {
            "label": lbl, "recommended_include": True, "depth": "rich", "rationale": "",
        })

    return {
        "focus_areas": focus_areas,
        "length": {"recommended": length, "options": LENGTH_OPTIONS},
        "tables": {"recommended": tables, "options": TABLE_OPTIONS},
    }


async def build_report_proposal(
    *,
    mission_brief: dict,
    cleaned_reports: list[tuple[str, dict]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Propose report shape (focus areas / length / tables) from scrubbed research.

    Returns the proposal dict (see default_proposal for shape). Falls back to a
    conservative default on any LLM/parse failure — shaping must never block the
    report from being writable.
    """
    labels = _focus_labels(mission_brief)
    if not labels:
        return default_proposal(mission_brief)

    blocks: list[str] = []
    for name, result in cleaned_reports:
        rep = (result or {}).get("report") or ""
        if rep:
            blocks.append(f"### {name}\n{rep}")
    research = "\n\n---\n\n".join(blocks)
    if len(research) > _RESEARCH_CHAR_BUDGET:
        research = research[:_RESEARCH_CHAR_BUDGET] + "\n…(truncated)…"
    focus_block = "\n".join(f"  {i+1}. {lbl}" for i, lbl in enumerate(labels))

    prompt = _PROMPT_TEMPLATE.format(focus_block=focus_block, research=research or "(no research)")

    try:
        response = await audited.gemini_generate(
            run_id=run_id, tenant_id=tenant_id, model=_PLANNER_MODEL,
            contents=prompt, config=_make_config(),
        )
        text = getattr(response, "text", None)
        if not text:
            cands = getattr(response, "candidates", None) or []
            if cands:
                parts = getattr(getattr(cands[0], "content", None), "parts", None) or []
                if parts:
                    text = getattr(parts[0], "text", None) or ""
        text = text or ""
    except Exception as exc:  # noqa: BLE001 — shaping is best-effort
        log.warning("report_planner: proposal call failed (%s) — using default", exc)
        return default_proposal(mission_brief)

    proposal = _parse(text, labels)
    log.info(
        "report_planner: proposed length=%s tables=%s, %d focus areas (%d to include)",
        proposal["length"]["recommended"], proposal["tables"]["recommended"],
        len(proposal["focus_areas"]),
        sum(1 for f in proposal["focus_areas"] if f["recommended_include"]),
    )
    return proposal


def normalize_spec(spec: dict | None, mission_brief: dict) -> dict:
    """Coerce a user-submitted report_spec into a safe, complete shape.

    Guarantees: at least one included focus area (falls back to all), a valid
    length and table choice, and a clean free-text instructions string.
    """
    spec = spec or {}
    labels = _focus_labels(mission_brief)
    label_set = {l.lower() for l in labels}

    included = [
        l for l in (spec.get("included_focus_areas") or [])
        if isinstance(l, str) and l.lower() in label_set
    ]
    if not included:
        included = labels  # never produce an empty report

    length = spec.get("length")
    if length not in LENGTH_OPTIONS:
        length = "standard"
    tables = spec.get("tables")
    if tables not in TABLE_OPTIONS:
        tables = "key"
    instructions = (spec.get("instructions") or "").strip()[:2000]

    return {
        "included_focus_areas": included,
        "length": length,
        "tables": tables,
        "instructions": instructions,
    }
