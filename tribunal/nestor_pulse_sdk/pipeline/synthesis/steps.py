"""SDK synthesis pipeline steps -- Phase 1 minimum port.

This is the SDK-side port of nestor_pulse/synthesis_pipeline/steps.py (the ADK
legacy 10-step pipeline). The ADK file stays untouched (D-01). Each step here
routes its LLM calls through AuditedLLMClient (Plan 07) rather than calling the
provider client directly (the grep gate forbids direct provider construction
outside audit/audited_llm_client.py).

PHASE 1 SCOPE NOTE
------------------
The full 10-step port (Chunker -> ChunkGuard -> ClaimDistiller -> ClaimGuard ->
RelevanceGate -> ConflictDetector -> TopicClustering -> TopicSynthesis ->
FinalSynthesis -> QualityGate) is deferred to Plan 12's closing-wave A/B test
kit. That A/B is the natural forcing function for high-fidelity behaviour
parity with the ADK pipeline (we'll compare both on 5 briefs).

What ships in Plan 09 Task 2:
  - `extract_focus_areas` -- pure Python, ported verbatim from the legacy.
  - `final_synthesis_audited` -- one real audited Gemini call producing the
    synthesis text from the 3 provider reports. The grep gate
    (audited.gemini_generate|anthropic_messages|openai_response in
    nestor_pulse_sdk/pipeline/synthesis/steps.py) is satisfied.
  - Step stubs for the remaining 9 steps raise `NotImplementedError` with a
    pointer to Plan 12. The orchestrator (`run_synthesis`) only calls
    `final_synthesis_audited` for the Plan 09 minimum path.

Anti-pattern to preserve from the legacy:
  `gemini-2.5-pro` does NOT support `thinking_budget=0` ("only works in
  thinking mode"). High `max_output_tokens` instead. This is honoured by
  AuditedLLMClient.gemini_generate when callers pass a generation config.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from typing import Any, Optional, TYPE_CHECKING

from nestor_pulse_sdk.citations.anchors import (
    ANCHOR_RE,
    ANCHOR_RULE_SECTION,
    ANCHOR_RULE_WRAP,
    render_fact_ledger,
)
from nestor_pulse_sdk.citations.numbering import _domain

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)


FINAL_SYNTHESIS_MODEL = "gemini-2.5-pro"

# System instruction for report generation — the report-writing contract.
#
# Design (researched 2026-06-10; see deep_research_compare/final_20260610/):
#   - Pyramid Principle / BLUF: lead every unit of writing with its conclusion,
#     then arguments, then evidence (Minto; standard at consulting firms).
#   - ReportLogic failure modes (arXiv 2602.18446): unsupported claims, internal
#     contradictions, weak claim->evidence chains, structural incoherence — each
#     gets an explicit countermeasure below.
#   - Production deep-research patterns: per-finding confidence, explicit
#     contradiction handling, recommendations restricted to well-supported
#     findings, named research gaps.
#   - Depth-over-breadth: explain mechanism (why/how) and implication (so what),
#     not just the fact; dense analytical prose, not bullet dumps.
#   - ADK A/B learnings: a dedicated decision framework and evidence-strength
#     assessment are what made ADK's reports read "consultant-grade".
# Topic-agnostic on purpose: the engine cannot know the domain in advance.
_SYNTHESIS_SYSTEM = (
    "You are a senior research analyst writing the final report of an independent, "
    "fact-checked research engagement. Your reader is a decision-maker who will act "
    "on this report and may be challenged on it — every sentence must survive that "
    "challenge. The subject matter can be any domain; apply the same discipline "
    "regardless of topic.\n"
    "\n"
    "GROUNDING (non-negotiable):\n"
    "- Use ONLY the research provided. Never add facts, numbers, names, or examples "
    "from your own knowledge — an unsupported claim is worse than a gap.\n"
    "- The research has already been independently fact-checked; discredited "
    "passages were removed. What remains is usable evidence.\n"
    "- Preserve source references EXACTLY as they appear in the research — markdown "
    "links stay markdown links, citation markers like [cite: 12] stay verbatim next "
    "to the claim they support. NEVER invent, renumber, or drop a reference.\n"
    "- If the research does not answer part of the question, say so explicitly in "
    "one sentence and move on. Never pad a gap with generic filler prose.\n"
    "\n"
    "ARGUMENT QUALITY:\n"
    "- Lead with the answer (pyramid principle): state the conclusion first, then "
    "the supporting arguments, then the evidence — at report level, section level, "
    "and paragraph level.\n"
    "- Depth over breadth: for every major finding give the mechanism (why/how it "
    "works) and the implication for the client (so what), not just the fact.\n"
    "- Weigh the evidence in the text: findings corroborated by multiple "
    "independent sources are stated with confidence; single-source or partial "
    "findings are explicitly marked as such (e.g. 'one source reports...'). Base "
    "recommendations only on well-supported findings.\n"
    "- Stay internally consistent: never state a figure or position in one place "
    "and contradict it elsewhere. When a CONTESTED POINT is listed, present both "
    "sides with attribution and do NOT silently resolve it.\n"
    "- Quantify wherever the research quantifies. Prefer the specific number, "
    "named entity, and date over the vague paraphrase.\n"
    "\n"
    "STYLE:\n"
    "- Dense analytical prose in markdown. Use short paragraphs that each make one "
    "argument; use bullet lists only for genuinely enumerable items, never as a "
    "substitute for reasoning.\n"
    "- LANGUAGE: write the ENTIRE report in ONE language — the single run language "
    "stated in the request. Never mix languages, even if the source research or "
    "notes are in another language; translate them into the report language.\n"
    "- No preamble, no meta-commentary about the research process, no 'Of course' "
    "or 'Here is' — start directly with the content.\n"
)


def _make_synthesis_config(max_tokens: int):
    """GenerateContentConfig carrying the system instruction + a real token budget.

    gemini-2.5-pro does NOT support thinking_budget=0 — so we just set a high
    max_output_tokens (a full structured brief needs the headroom; the old call
    passed no config and silently truncated at the model default).
    """
    try:
        from google.genai import types as genai_types  # noqa: PLC0415
        return genai_types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=0.2,
            system_instruction=_SYNTHESIS_SYSTEM,
        )
    except Exception:
        return None


def extract_focus_areas(mission_brief: Optional[dict]) -> list[str]:
    """Pull focus_area strings off mission_brief.focus_areas[*].focus_area.

    Verbatim shape from nestor_pulse/synthesis_pipeline/steps.py. The legacy
    builds the clustering signal from these labels rather than embeddings.
    """
    if not mission_brief:
        return []
    raw = mission_brief.get("focus_areas") or []
    out: list[str] = []
    for fa in raw:
        if isinstance(fa, dict) and fa.get("focus_area"):
            out.append(str(fa["focus_area"]))
        elif isinstance(fa, str):
            out.append(fa)
    return out


def _language_directive(mission_brief: Optional[dict]) -> str:
    """One-language-per-run instruction for every writing step.

    intake (adaptive_intake) detects ONE language for the whole run and stores it
    on mission_brief['language']. Every synthesis/distill prompt injects this so
    the output is single-language end-to-end (no per-section / mixed-language
    behaviour). Falls back to "the brief's language" when none was detected.
    """
    lang = ((mission_brief or {}).get("language") or "").strip()
    if lang:
        return (
            f"Write EVERYTHING in {lang} and ONLY {lang} — one single language for "
            f"the entire output. Translate any source material, notes, or headings "
            f"into {lang}. Never mix languages."
        )
    return (
        "Write the entire output in ONE language — the language the brief is written "
        "in. Never mix languages; translate any source material into that one language."
    )


async def final_synthesis_audited(
    *,
    mission_brief: dict,
    provider_reports: list[tuple[str, dict]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    max_tokens: int = 16384,
    contested_notes: Optional[list[str]] = None,
) -> str:
    """One audited Gemini call producing the final synthesis text.

    Synthesises from the FULL research prose (richness), which the pipeline has
    already SCRUBBED of fact-checked-out claims (trust). The HOW of the report —
    structure, language faithfulness, citation preservation — lives in the
    `_SYNTHESIS_SYSTEM` system instruction. `contested_notes` carries genuine
    cross-source disagreements that survived conflict detection unresolved.
    """
    focus_areas = extract_focus_areas(mission_brief)

    # The brief's own research prompt carries any language / per-question
    # instructions (e.g. "answer Q1-4 in Dutch, Q5 in English") — pass it through
    # so the synthesiser can honour them (the old prompt dropped this entirely).
    brief_prompt = (mission_brief or {}).get("deep_research_prompt") or ""

    if focus_areas:
        focus_list = "\n".join(f"  {i+1}. {fa}" for i, fa in enumerate(focus_areas))
        section_rule = (
            "Write ONE dedicated section per focus area above, in that order, each "
            "fully answering it. Do not merge or drop a focus area."
        )
    else:
        focus_list = "  (none specified — organise by the topics in the brief)"
        section_rule = "Organise the report around the distinct topics in the brief."

    report_blocks: list[str] = []
    for name, result in provider_reports:
        report_text = (result or {}).get("report") or ""
        if not report_text:
            continue
        report_blocks.append(f"### Provider: {name}\n\n{report_text}")
    reports_concatenated = "\n\n---\n\n".join(report_blocks) or "(no provider reports)"

    contested_block = ""
    if contested_notes:
        contested_lines = "\n".join(f"  - {n}" for n in contested_notes)
        contested_block = (
            "\nCONTESTED POINTS (sources genuinely disagree — present BOTH sides "
            "explicitly, attribute each, and do NOT silently resolve):\n"
            f"{contested_lines}\n"
        )

    prompt = (
        f"CLIENT BRIEF / RESEARCH REQUEST:\n{brief_prompt or '(see focus areas)'}\n\n"
        f"Focus areas to cover:\n{focus_list}\n"
        f"{contested_block}\n"
        "Required report structure (markdown):\n"
        "  1. Executive Summary — the key actionable insights.\n"
        f"  2. Body — {section_rule} Include evidence and inline source links.\n"
        "  3. Cross-cutting synthesis — how the themes reinforce each other.\n"
        "  4. Confidence & gaps — what is well-supported vs. uncertain.\n"
        "  5. Sources — a consolidated list of every unique URL used (markdown links).\n\n"
        f"--- Fact-checked research ---\n\n{reports_concatenated}\n\n"
        "--- End research ---\n\n"
        f"{_language_directive(mission_brief)}\n"
        "Write the complete report now."
    )

    config = _make_synthesis_config(max_tokens)
    kwargs: dict = {"config": config} if config is not None else {}
    response = await audited.gemini_generate(
        run_id=run_id,
        tenant_id=tenant_id,
        model=FINAL_SYNTHESIS_MODEL,
        contents=prompt,
        **kwargs,
    )

    # google-genai response shape: .text or .candidates[0].content.parts[0].text
    text = getattr(response, "text", None)
    if not text:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
            if parts:
                text = getattr(parts[0], "text", None) or ""
    return text or ""


# ---------------------------------------------------------------------------
# Per-focus-area synthesis (skeptic-fix session 2026-06-10).
#
# The one-shot final_synthesis_audited pushes ~200K chars of research through a
# single call with a 16K output ceiling — the LUKOIL validation report was
# observably truncated mid-URL in its Sources section. synthesize_report removes
# the bottleneck: one parallel call PER focus area (each writes only its own
# section), one small wrap call (exec summary / cross-cutting / confidence), and
# a DETERMINISTIC Sources section built in Python from the links actually used —
# the part that got truncated is now untruncatable.
# ---------------------------------------------------------------------------

_SECTION_MAX_TOKENS = 8192
_WRAP_MAX_TOKENS = 8192
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _extract_sources_section(*texts: str) -> str:
    """Build the Sources section deterministically from markdown links used."""
    seen: set[str] = set()
    lines: list[str] = []
    for text in texts:
        for label, url in _MD_LINK_RE.findall(text or ""):
            if url not in seen:
                seen.add(url)
                lines.append(f"*   [{label}]({url})")
    if not lines:
        return "## Sources\n\n*(No linked sources found in the report body.)*"
    return "## Sources\n\n" + "\n".join(lines)


#: quality_tier -> the words the operator reads. Anything unrecognised is
#: "other source" -- never a guess dressed up as a grade.
_TIER_LABELS = {1: "official source", 2: "established press"}


def build_graded_sources_section(numbered: Optional[list[dict]], *texts: str) -> str:
    """The graded `## Sources` list (Phase 15.2, D13/D-07).

    WRAPS `_extract_sources_section`, never replaces it. With no numbering data
    (`numbered` falsy) this returns today's output byte-for-byte -- the
    link-scraped list stays the fallback for every path that has no claim rows.

    With numbering, each entry is rendered in `n` order as
    `n. [label](url) — tier · retrieved DATE · single-source`, where:

    * `label` is the stored title, else the display domain (`numbering._domain`
      -- reused, NOT a second URL parser), else the raw URL. Using the DISPLAY
      DOMAIN rather than the link host also keeps Gemini `vertexaisearch`
      redirect URLs from rendering as "vertexaisearch.cloud.google.com".
    * the date word is ALWAYS "retrieved". `publication_date` carries
      `source.fetched_at`, a retrieval-date proxy (numbering.py docstring); the
      operator's C1 bar ("NO ESTIMATES -- facts and correct calculations only")
      forbids presenting a proxy as a publication fact.
    * `single-source` is shown only when true; an entry with no URL renders as
      plain text rather than as a broken link.

    Then an APPEND-ONLY RESCUE: any URL found in the prose that is not in the
    numbered set is still listed, under a line saying in words that it carries no
    verified claim link. A URL that `_extract_sources_section` would have shown
    today is never lost.
    """
    # Anchors are STILL PRESENT in `texts` here: the post-pass runs later, in
    # pipeline.py. `_MD_LINK_RE` needs `](` adjacency, so an anchor the model
    # dropped between a link's label and its URL (`[Aral][[c:9f2a41bd]](http...)`)
    # would hide that URL from the scan entirely. Scan a CLEANED COPY -- the
    # report text itself is not touched by this.
    cleaned = tuple(ANCHOR_RE.sub("", t or "") for t in texts)

    if not numbered:
        return _extract_sources_section(*cleaned)

    lines: list[str] = []
    numbered_urls: set[str] = set()
    for entry in numbered:
        url = str((entry or {}).get("url") or "").strip()
        title = str((entry or {}).get("title") or "").strip()
        label = title or _domain(url) or url or "source"
        tier = _TIER_LABELS.get((entry or {}).get("quality_tier"), "other source")
        published = (entry or {}).get("publication_date")
        date = str(published)[:10] if published else "date unknown"
        segments = [tier, f"retrieved {date}"]
        if (entry or {}).get("single_source"):
            segments.append("single-source")
        meta = " · ".join(segments)
        n = (entry or {}).get("n")
        if url:
            numbered_urls.add(url)
            lines.append(f"{n}. [{label}]({url}) — {meta}")
        else:
            lines.append(f"{n}. {label} — {meta}")

    extra: list[str] = []
    extra_seen: set[str] = set()
    for text_value in cleaned:
        for label, url in _MD_LINK_RE.findall(text_value):
            if url in numbered_urls or url in extra_seen:
                continue
            extra_seen.add(url)
            extra.append(f"*   [{label}]({url})")

    out = "## Sources\n\n" + "\n".join(lines)
    if extra:
        out += (
            "\n\nThese links appear in the report text but carry no verified claim "
            "link, so they are listed without a number:\n\n" + "\n".join(extra)
        )
    return out


def _spec_directives(report_spec: Optional[dict]) -> str:
    """Turn a user report_spec (length / tables / instructions) into a prompt block.

    Empty string when no spec — synthesis behaves exactly as before. Focus-area
    SELECTION is handled by the caller (it filters the section list); this only
    carries the cross-cutting style directives into every section + the wrap.
    """
    if not report_spec:
        return ""
    parts: list[str] = []
    length = report_spec.get("length")
    if length == "brief":
        parts.append(
            "LENGTH: Keep this TIGHT and decision-first. Prefer the shortest "
            "treatment that still fully answers; cut nice-to-have elaboration."
        )
    elif length == "comprehensive":
        parts.append(
            "LENGTH: Be COMPREHENSIVE. Develop every well-supported finding in "
            "depth, include relevant secondary findings and context."
        )
    tables = report_spec.get("tables")
    if tables == "none":
        parts.append("TABLES: Do NOT use markdown tables — write flowing prose.")
    elif tables == "key":
        parts.append(
            "TABLES: Use a markdown table only where it genuinely clarifies a "
            "comparison or dataset (sparingly)."
        )
    elif tables == "heavy":
        parts.append(
            "TABLES: Use markdown tables liberally to present comparisons, "
            "options and data densely wherever it helps the reader."
        )
    instructions = (report_spec.get("instructions") or "").strip()
    if instructions:
        parts.append("ADDITIONAL CLIENT INSTRUCTIONS (follow these):\n" + instructions)
    if not parts:
        return ""
    return "\n\nREPORT SHAPING (client-chosen — honor these):\n" + "\n".join(parts) + "\n"


async def synthesize_report(
    *,
    mission_brief: dict,
    provider_reports: list[tuple[str, dict]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    contested_notes: Optional[list[str]] = None,
    report_spec: Optional[dict] = None,
    anchor_ledger: Optional[list[dict]] = None,
    numbered_citations: Optional[list[dict]] = None,
) -> str:
    """Write the final report with one LLM call per focus-area section.

    Falls back to the single-call final_synthesis_audited when the mission
    brief carries no focus areas (broadcast/control path).

    report_spec (optional, from the interactive report planner): narrows which
    focus areas get a section (included_focus_areas) and carries length / table /
    free-text style directives. None => today's full, default-shaped report.

    anchor_ledger / numbered_citations (optional, Phase 15.2 D-05): the run's
    fact ledger and its `[n]` -> source numbering, both read once from the DB by
    `pipeline.py::_load_citation_context`. When BOTH are None/empty this function
    emits byte-identical prompts and a byte-identical report to the pre-15.2
    behaviour -- pinned by a back-compat test.

    The anchor rule deliberately lands in the prompts this function ACTUALLY
    SENDS: `_one_section` and `wrap_prompt`. It is NOT added to
    `final_synthesis_audited`, which only runs on the zero-focus-area fallback
    below and would therefore be a silent no-op on every real run.
    """
    focus_areas = extract_focus_areas(mission_brief)

    # Apply the client's focus-area selection (interactive shaping). Match
    # case-insensitively; keep canonical order; never end up with zero sections.
    included = (report_spec or {}).get("included_focus_areas")
    if included:
        want = {str(l).strip().lower() for l in included}
        filtered = [fa for fa in focus_areas if fa.strip().lower() in want]
        if filtered:
            focus_areas = filtered

    spec_block = _spec_directives(report_spec)

    if not focus_areas:
        return await final_synthesis_audited(
            mission_brief=mission_brief,
            provider_reports=provider_reports,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
            contested_notes=contested_notes,
        )

    brief_prompt = (mission_brief or {}).get("deep_research_prompt") or ""
    lang_rule = _language_directive(mission_brief)  # ONE language for the whole run

    report_blocks: list[str] = []
    for name, result in provider_reports:
        report_text = (result or {}).get("report") or ""
        if report_text:
            report_blocks.append(f"### Provider: {name}\n\n{report_text}")
    reports_concatenated = "\n\n---\n\n".join(report_blocks) or "(no provider reports)"

    contested_block = ""
    if contested_notes:
        contested_lines = "\n".join(f"  - {n}" for n in contested_notes)
        contested_block = (
            "\nCONTESTED POINTS (sources genuinely disagree — if relevant to this "
            "section, present BOTH sides explicitly and attribute each):\n"
            f"{contested_lines}\n"
        )

    # Is the ledger actually live? render_fact_ledger returns "" both for an empty
    # ledger and when the NESTOR_TRIBUNAL_ANCHORS kill switch is off, so this one
    # check makes the kill switch complete: no ledger in the section prompts AND
    # no anchor rule in the wrap prompt (which would otherwise talk about tokens
    # that were never emitted).
    anchors_on = bool(render_fact_ledger(anchor_ledger))

    async def _one_section(idx: int, fa: str) -> str:
        # Facet-scoped so a 300-600 survivor run does not paste the whole ledger
        # into every section prompt (T-15.2-25 cost control).
        ledger_block = render_fact_ledger(anchor_ledger, facet=fa)
        anchor_rule = ANCHOR_RULE_SECTION if ledger_block else ""
        prompt = (
            f"CLIENT BRIEF / RESEARCH REQUEST:\n{brief_prompt or '(see focus area)'}\n\n"
            f"YOUR ASSIGNMENT: write ONE markdown section of the final report — the "
            f"section that fully answers focus area {idx + 1} of {len(focus_areas)}:\n"
            f"  \"{fa}\"\n"
            f"{contested_block}\n"
            f"Section contract (heading first: ## {fa}):\n"
            "  1. BOTTOM LINE — open with 2-3 sentences that directly answer this "
            "question. A reader who stops here must already know your conclusion.\n"
            "  2. ANALYSIS — dense paragraphs that develop the answer. Every part of "
            "the question gets addressed. For each major finding: the concrete "
            "evidence (numbers, named cases, dates, with its source reference kept "
            "verbatim), the mechanism behind it, and what it means for the client. "
            "State evidence strength: corroborated findings with confidence, "
            "single-source findings marked as such. If the research leaves part of "
            "this question unanswered, say so in one sentence — do not pad.\n"
            "  3. DECISION FRAMEWORK — close with a heading meaning 'What this means' "
            "translated into the run language (e.g. '### What this means'): "
            "2-4 concrete, prioritised actions or conclusions for the client, each "
            "tied to a well-supported finding above, each with its main condition "
            "or risk in the same sentence.\n"
            "\n"
            "Answer ONLY this focus area (other sections are written separately).\n"
            f"{anchor_rule}"
            f"{spec_block}"
            f"{lang_rule}\n\n"
            f"{ledger_block}"
            f"--- Fact-checked research ---\n\n{reports_concatenated}\n\n"
            "--- End research ---\n\nWrite the section now."
        )
        config = _make_synthesis_config(_SECTION_MAX_TOKENS)
        kwargs: dict = {"config": config} if config is not None else {}
        try:
            response = await audited.gemini_generate(
                run_id=run_id,
                tenant_id=tenant_id,
                model=FINAL_SYNTHESIS_MODEL,
                contents=prompt,
                **kwargs,
            )
        except Exception as exc:
            log.error("synthesize_report: section %r failed: %s", fa, exc)
            return f"## {fa}\n\n*(Section generation failed: {exc})*"
        text = getattr(response, "text", None)
        if not text:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
                if parts:
                    text = getattr(parts[0], "text", None) or ""
        text = (text or "").strip()
        if not text:
            log.error("synthesize_report: section %r returned empty text", fa)
            return f"## {fa}\n\n*(Section generation returned no content.)*"
        if not text.lstrip().startswith("#"):
            text = f"## {fa}\n\n{text}"
        return text

    sections = list(
        await asyncio.gather(*(_one_section(i, fa) for i, fa in enumerate(focus_areas)))
    )

    # Wrap call: exec summary + cross-cutting + decision framework + confidence,
    # written FROM the finished sections (small input/output — no bottleneck).
    sections_joined = "\n\n".join(sections)
    wrap_prompt = (
        f"CLIENT BRIEF / RESEARCH REQUEST:\n{brief_prompt or '(see sections)'}\n\n"
        "Below are the finished body sections of a research report. Write the "
        "remaining framing sections — exactly these headings, in this order, "
        "translating the heading text into the run language and keeping the same "
        "order:\n"
        "\n"
        "  ## Executive Summary\n"
        "     Lead with the single most important conclusion of the whole report in "
        "one sentence (bottom line up front). Then 4-6 bullets: the key actionable "
        "insights across all sections, each with its decisive number or fact and "
        "its source reference kept verbatim. A reader of this section alone must "
        "be able to brief their board.\n"
        "  ## Cross-cutting Synthesis\n"
        "     How the themes interact: which findings reinforce each other, which "
        "create tension or trade-offs, and what sequence or dependency that implies. "
        "Add insight beyond the sections — never summarise them again.\n"
        "  ## Decision Framework\n"
        "     The consolidated recommendation set: per question one concrete, "
        "prioritised recommendation (what to do first, what it depends on, what "
        "risk to watch), based ONLY on well-supported findings from the body.\n"
        "  ## Confidence & Gaps\n"
        "     Three short labelled groups: STRONG (corroborated by multiple "
        "independent sources), LIMITED (single-source or partial evidence — name "
        "which findings), and OPEN (what the research could not answer, stated as "
        "concrete follow-up questions).\n"
        "\n"
        "Ground every statement in the body sections — no new facts. Do NOT rewrite "
        "or repeat the body sections.\n\n"
        # NO ledger block here, on purpose: the body sections below already carry
        # the anchor tokens (the post-pass runs later, in pipeline.py), so the
        # wrap REUSES them instead of re-deriving them from a second copy of the
        # ledger. That is the T-15.2-25 cost control.
        f"{ANCHOR_RULE_WRAP if anchors_on else ''}"
        f"{spec_block}"
        f"{lang_rule}\n\n"
        f"--- Report body ---\n\n{sections_joined}\n\n--- End body ---"
    )
    config = _make_synthesis_config(_WRAP_MAX_TOKENS)
    kwargs = {"config": config} if config is not None else {}
    exec_part, tail_part = "", ""
    try:
        response = await audited.gemini_generate(
            run_id=run_id,
            tenant_id=tenant_id,
            model=FINAL_SYNTHESIS_MODEL,
            contents=wrap_prompt,
            **kwargs,
        )
        wrap_text = getattr(response, "text", None)
        if not wrap_text:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
                if parts:
                    wrap_text = getattr(parts[0], "text", None) or ""
        wrap_text = (wrap_text or "").strip()
        # The exec summary opens the report; the other wrap sections close it.
        # Headings may be translated into the report's language, so split on
        # POSITION (the wrap's second '## ' heading), not on heading text.
        heads = list(re.finditer(r"^##\s+", wrap_text, re.MULTILINE))
        if len(heads) >= 2:
            cut = heads[1].start()
            exec_part = wrap_text[:cut].strip()
            tail_part = wrap_text[cut:].strip()
        else:
            exec_part = wrap_text
    except Exception as exc:
        log.error("synthesize_report: wrap call failed: %s", exc)

    sources_section = build_graded_sources_section(
        numbered_citations, *sections, exec_part, tail_part
    )

    parts_out = [p for p in (exec_part, sections_joined, tail_part, sources_section) if p]
    report = "\n\n".join(parts_out)
    log.info(
        "synthesize_report: %d section(s) + wrap -> %d chars",
        len(sections), len(report),
    )
    return report


# ---------------------------------------------------------------------------
# Stubs for the remaining 9 legacy steps -- Plan 12 owns the full port.
# ---------------------------------------------------------------------------


def _phase2_stub(step_name: str):
    def _stub(*_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError(
            f"Synthesis step {step_name!r} is deferred to Plan 12 "
            "(closing-wave ADK-vs-SDK A/B is the forcing function for the "
            "high-fidelity port; until then run_synthesis uses final_synthesis_audited only)."
        )
    return _stub


chunker_prime = _phase2_stub("chunker_prime")
chunk_guard = _phase2_stub("chunk_guard")


# ---------------------------------------------------------------------------
# Step 3: ClaimDistiller — un-stubbed in Plan 01-13 Task 2.
# ---------------------------------------------------------------------------

_DISTILLER_MODEL = "gemini-2.5-flash"
# Output ceiling per distill call — the MODEL MAXIMUM for gemini-2.5-flash
# (fix 2026-06-11). The old 4096 silently truncated extraction at ~29 claims:
# on the LUKOIL final run only the FIRST research report's opening got distilled
# and the other four questions shipped entirely unverified while the report
# claimed "29/29 fact-checked". The cap is now effectively removed; the real
# coverage guarantee is chunking (one call per report / per chunk, parallel).
_DISTILLER_MAX_TOKENS = 65535
#: Reports longer than this are split into chunks on paragraph boundaries so a
#: single distill call never has to read more than it can faithfully cover.
_DISTILLER_CHUNK_CHARS = int(os.environ.get("NESTOR_DISTILLER_CHUNK_CHARS", "60000"))
#: Parallel distill calls (one per report/chunk).
_DISTILLER_CONCURRENCY = int(os.environ.get("NESTOR_DISTILLER_CONCURRENCY", "4"))


def _make_distiller_config():
    """Build a GenerateContentConfig with thinking disabled.

    gemini-2.5-flash supports ThinkingConfig(thinking_budget=0).
    Without this, thinking tokens silently consume max_output_tokens,
    truncating output after 2-3 lines (CLAUDE.md anti-pattern).

    Plain-text line format — NOT JSON mode (citations ⊗ structured-outputs
    = HTTP 400; ADR-006 §GOTCHA).
    """
    try:
        from google.genai import types as genai_types  # noqa: PLC0415
        thinking_cfg = genai_types.ThinkingConfig(thinking_budget=0)
        return genai_types.GenerateContentConfig(
            max_output_tokens=_DISTILLER_MAX_TOKENS,
            temperature=0.0,
            thinking_config=thinking_cfg,
        )
    except Exception:
        # SDK version may not support ThinkingConfig — degrade gracefully
        try:
            from google.genai import types as genai_types  # noqa: PLC0415
            return genai_types.GenerateContentConfig(
                max_output_tokens=_DISTILLER_MAX_TOKENS,
                temperature=0.0,
            )
        except Exception:
            return None


def _chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into <=max_chars chunks on paragraph boundaries (fallback: hard cut)."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= max_chars:
            chunks.append(rest)
            break
        cut = rest.rfind("\n\n", 0, max_chars)
        if cut < max_chars // 2:  # no decent paragraph boundary — try newline, then hard cut
            cut = rest.rfind("\n", 0, max_chars)
        if cut < max_chars // 2:
            cut = max_chars
        chunks.append(rest[:cut])
        rest = rest[cut:].lstrip()
    return chunks


def _build_distiller_prompt(
    provider_reports: list, focus_area_labels: list[str], language: str = ""
) -> str:
    """Build the plain-text distiller prompt.

    Uses a tab-separated "FACET<TAB>CLAIM_TEXT" line format (one claim per line),
    mirroring the RelevanceGate line discipline (CLAUDE.md anti-pattern section).
    NOT JSON mode — citations⊗structured-outputs HTTP 400 trap.
    """
    facet_block = "\n".join(f"  - {f}" for f in focus_area_labels) or "  - general"

    lang = (language or "").strip()
    lang_rule = (
        f"  - Write CLAIM_TEXT in {lang}. If a report is in another language, "
        f"TRANSLATE the claim into {lang} (the whole run is one language).\n"
        if lang else ""
    )

    report_blocks: list[str] = []
    for name, result in provider_reports:
        report_text = (result or {}).get("report") or ""
        if not report_text:
            continue
        report_blocks.append(f"### Provider: {name}\n{report_text}")
    reports_text = "\n\n---\n\n".join(report_blocks) or "(no provider reports)"

    return (
        "You are a claim distiller. Extract atomic factual claims from the research reports below.\n\n"
        "Rules:\n"
        "  - One claim per line. Do NOT use JSON, bullets, or numbered lists.\n"
        "  - Each line MUST use this format: FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE\n"
        "    where FACET is one of the focus area labels listed below.\n"
        "  - CLAIM_TEXT = one self-contained atomic fact (no conjunctions joining two facts).\n"
        "  - EVIDENCE = the shortest VERBATIM sentence or phrase, copied EXACTLY from the\n"
        "    report, that supports this claim. It is used to locate the claim in the source\n"
        "    text and remove it if it is later discredited. Copy it word-for-word "
        "(do NOT translate EVIDENCE — keep it in the report's original language).\n"
        f"{lang_rule}"
        "  - Include statistics, percentages, named entities, dates where present.\n"
        "  - Do NOT interpret, extrapolate, or add context not present in the text.\n"
        "  - Skip vague or unsupported assertions.\n"
        "  - Extract EVERY distinct atomic fact across ALL focus areas. Do NOT limit the\n"
        "    number of claims — thorough coverage matters more than brevity. Each focus\n"
        "    area should be covered in proportion to how much the reports say about it.\n"
        "  - Blank lines and lines without at least one TAB separator are ignored.\n\n"
        f"Focus area labels (use one per claim):\n{facet_block}\n\n"
        f"--- Research reports ---\n\n{reports_text}\n\n"
        "--- End reports ---\n\n"
        "Output claims now (one per line, FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE format):"
    )


def _parse_distiller_response(text: str, focus_area_labels: list[str], *, provider: str = "") -> list[dict]:
    """Parse plain-text tab-separated lines into claim dicts.

    Format: "FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE" (EVIDENCE optional for back-compat).
    Skips blank lines and malformed lines (no tab separator) defensively.

    ``provider`` (G-12) names the researcher whose report this chunk came from. It
    is supplied by the pipeline from ``provider_reports`` and is NEVER parsed out of
    model output, so a model cannot set its own attribution. Every claim carries it
    as ``found_by``; claim-level corroboration is ``len(claim["found_by"])`` once
    duplicates have been merged by ``_dedupe_claims``. ``facet`` is not a usable
    substitute — it falls back to the provider name only when no focus-area label
    matched, so provenance is not reliably recoverable from it.
    """
    valid_facets = set(focus_area_labels) if focus_area_labels else set()
    claims: list[dict] = []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "\t" not in line:
            # Malformed line — skip without raising
            log.debug("claim_distiller: skipping malformed line (no tab): %r", line[:80])
            continue
        # Up to 3 columns: facet, claim_text, evidence. Evidence is optional so a
        # 2-column response (legacy / model omission) still parses.
        parts = line.split("\t", 2)
        facet = parts[0].strip()
        claim_text = parts[1].strip() if len(parts) > 1 else ""
        evidence = parts[2].strip() if len(parts) > 2 else ""
        if not claim_text or len(claim_text) < 10:
            continue
        # Normalise facet: accept any non-empty string; flag if not in known facets
        if not facet:
            facet = "general"
        elif valid_facets and facet not in valid_facets:
            # Use as-is — don't drop claims just because the model used a near-match
            log.debug("claim_distiller: facet %r not in known facets %r", facet, valid_facets)
        claims.append({
            "text": claim_text,
            "facet": facet,
            "evidence": evidence,
            # G-12: the producing researcher, threaded in from the pipeline. A fact
            # found independently by three researchers must be distinguishable from
            # one asserted by a single researcher.
            "found_by": [provider] if provider else [],
        })

    return claims


def _dedupe_claims(claims: list[dict]) -> list[dict]:
    """Drop near-duplicate claims (same fact surfaced by multiple angles/providers).

    Deterministic, no LLM. Normalises claim text (lowercase, strip punctuation +
    whitespace) and keeps the first occurrence. Removing the global 30-claim cap
    means the same fact now arrives many times across 8 angles × 3 providers; this
    is what keeps the skeptic load proportional to DISTINCT facts, not raw volume.

    G-12 contract: a duplicate is MERGED into the first occurrence's ``found_by``
    rather than discarded, so the output length, order and claim texts are identical
    to the pre-15.1 behaviour while the corroboration signal survives.
    """
    seen: dict[str, dict] = {}
    out: list[dict] = []
    for c in claims:
        norm = re.sub(r"[^a-z0-9 ]", "", (c.get("text") or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if not norm:
            continue
        kept = seen.get(norm)
        if kept is not None:
            # MERGE, do not discard (G-12 bug 2). Three researchers independently
            # confirming a fact used to collapse to one indistinguishable claim.
            # Order-stable and duplicate-free: found_by is serialised into
            # synthesis_cache JSON, so no bare set may be stored here.
            incoming = c.get("found_by") or []
            if incoming:
                kept_found_by = kept.get("found_by")
                if not isinstance(kept_found_by, list):
                    kept_found_by = []
                    kept["found_by"] = kept_found_by
                for provider in incoming:
                    if provider not in kept_found_by:
                        kept_found_by.append(provider)
            continue
        seen[norm] = c
        out.append(c)
    return out


async def claim_distiller(
    *,
    provider_reports: list,
    mission_brief: dict,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[dict]:
    """Distil provider reports into atomic claims via an audited gemini-flash call.

    Un-stubbed in Plan 01-13 Task 2 (previously raised NotImplementedError).
    The Tribunal skeptic (Plan 01-14) consumes these claims for per-claim
    stakes triage and verification.

    Args:
        provider_reports: list of (provider_name, result_dict) tuples from
                          run_all_with_degradation. Empty/blank reports produce
                          zero claims, not an exception.
        mission_brief:    mission_brief dict from adaptive_intake (or orchestrator
                          pass-through). Used to seed available facet labels.
        audited:          Injected AuditedLLMClient — the ONLY LLM egress.
        run_id:           UUID for the current run (audit chain).
        tenant_id:        UUID for the current tenant (audit chain).

    Returns:
        list of dicts, each with at least:
            {
                "text":  str,  # atomic claim text
                "facet": str,  # focus_area label (from mission_brief or provider name)
            }
    """
    # Seed facet labels from mission_brief focus_areas
    focus_area_labels = extract_focus_areas(mission_brief)
    # ONE run language (intake-detected); claims are normalised into it.
    language = ((mission_brief or {}).get("language") or "").strip()

    # Build prompt; return early if no reports to distil
    has_any_report = any(
        (result or {}).get("report") for _, result in provider_reports
    )
    if not has_any_report:
        log.info("claim_distiller: no provider reports to distil — returning []")
        return []

    # COVERAGE FIX (2026-06-11): one distill call PER report chunk, in parallel —
    # never one call over the whole concatenated research. A single call reads a
    # 200K+ char input against a finite output budget and silently stops after
    # the first report (the LUKOIL final run distilled only question 5; the
    # other four questions were never fact-checked). Chunking makes every part
    # of every report get its own dedicated extraction pass.
    units: list[tuple[str, str]] = []  # (provider_name, chunk_text)
    for name, result in provider_reports:
        report_text = (result or {}).get("report") or ""
        if not report_text:
            continue
        for chunk in _chunk_text(report_text, _DISTILLER_CHUNK_CHARS):
            units.append((name, chunk))

    config = _make_distiller_config()
    kwargs: dict = {}
    if config is not None:
        kwargs["config"] = config

    sem = asyncio.Semaphore(_DISTILLER_CONCURRENCY)

    async def _distill_unit(name: str, chunk: str) -> list[dict]:
        prompt = _build_distiller_prompt([(name, {"report": chunk})], focus_area_labels, language)
        async with sem:
            try:
                response = await audited.gemini_generate(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    model=_DISTILLER_MODEL,
                    contents=prompt,
                    **kwargs,
                )
            except Exception as exc:
                # One failed chunk must not kill extraction for the rest — but it
                # IS a coverage hole, so log loudly.
                log.error("claim_distiller: chunk from %r failed: %s", name, exc)
                return []
        text = getattr(response, "text", None)
        if not text:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
                if parts:
                    text = getattr(parts[0], "text", None) or ""
        # G-12: `name` is the researcher that produced this chunk. It was previously
        # used only for the prompt header and then thrown away — thread it through so
        # every claim keeps its provenance.
        return _parse_distiller_response(text or "", focus_area_labels, provider=name)

    per_unit = await asyncio.gather(*(_distill_unit(n, c) for n, c in units))
    claims = [c for unit_claims in per_unit for c in unit_claims]

    # Coverage visibility: claims per facet — a facet with zero claims means that
    # focus area's research produced nothing checkable (or extraction failed there).
    facet_counts: dict[str, int] = {}
    for c in claims:
        facet_counts[c.get("facet", "?")] = facet_counts.get(c.get("facet", "?"), 0) + 1
    for fa in focus_area_labels:
        if facet_counts.get(fa, 0) == 0:
            log.warning("claim_distiller: focus area %r produced ZERO claims — unverified topic", fa)
    log.info(
        "claim_distiller: %d units distilled, claims per facet: %s",
        len(units), facet_counts,
    )

    # Dedupe near-identical facts surfaced by multiple angles/providers (the 30-cap
    # is gone, so the raw set is much larger and heavily redundant).
    before = len(claims)
    claims = _dedupe_claims(claims)

    # Off-by-default ops safety valve. The cap is REMOVED by design (default 0 =
    # unlimited); set NESTOR_TRIBUNAL_MAX_CLAIMS>0 only to bound a runaway brief.
    try:
        max_claims = int(os.environ.get("NESTOR_TRIBUNAL_MAX_CLAIMS", "0"))
    except ValueError:
        max_claims = 0
    if max_claims > 0 and len(claims) > max_claims:
        log.warning(
            "claim_distiller: capping %d claims to NESTOR_TRIBUNAL_MAX_CLAIMS=%d "
            "(information will be lost — raise or unset for full coverage)",
            len(claims), max_claims,
        )
        claims = claims[:max_claims]

    # One closing input->output INFO line (grouping.py convention). The old form passed
    # len(claims) twice, so the "atomic claims" and "after dedupe" slots always rendered
    # the same number and the raw->deduped ratio was invisible. The distinct-provider
    # count makes G-12 corroboration coverage observable in run logs.
    distinct_providers = len({p for c in claims for p in (c.get("found_by") or [])})
    log.info(
        "claim_distiller: %d raw claims -> %d after dedupe, from %d providers "
        "(%d distinct providers named in found_by)",
        before, len(claims), len(provider_reports), distinct_providers,
    )
    return claims


claim_guard = _phase2_stub("claim_guard")
relevance_gate = _phase2_stub("relevance_gate")
topic_clustering = _phase2_stub("topic_clustering")
topic_synthesis = _phase2_stub("topic_synthesis")


# ---------------------------------------------------------------------------
# Step 6: ConflictDetector — ported from the ADK legacy, audited + index-based.
# Checks the HORIZONTAL axis: do two claims that each survived the skeptic
# (vertical axis) contradict each other? A grounded claim can still be wrong
# relative to another grounded claim when two sources disagree.
# ---------------------------------------------------------------------------

_CONFLICT_MODEL = "gemini-2.5-pro"


def _extract_json_array(raw: str) -> list:
    """Tolerantly pull a JSON array out of an LLM response (handles code fences)."""
    import json

    if not raw:
        return []
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        parsed = json.loads(raw[start : end + 1])
        return parsed if isinstance(parsed, list) else []
    except Exception as exc:  # malformed JSON — fail soft (no conflicts)
        log.warning("conflict_detector: could not parse JSON array: %s", exc)
        return []


async def conflict_detector(
    *,
    claims: list[dict],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[dict]:
    """Find contradictions among (already-verified) claims.

    Each conflict picks a winner where the evidence is clearly stronger, or flags
    the pair as genuinely contested. Returns a list of conflict dicts:
        {"claims": [i, j, ...],   # indices into the input `claims` list
         "tension": str,           # what conflicts
         "loser": int | None,      # index to drop, or null if contested/unclear
         "contested": bool,        # True => keep both, present both sides
         "note": str}              # short explanation for the synthesiser
    """
    if len(claims) < 2:
        return []

    numbered = "\n".join(
        f"[{i}] (facet:{c.get('facet', '')}) {c.get('text', '')}"
        for i, c in enumerate(claims)
    )

    prompt = (
        "Identify direct contradictions between these already-fact-checked research "
        "claims. Only flag REAL contradictions (claims that cannot both be true), not "
        "claims that merely cover different angles of the same topic.\n\n"
        f"Claims:\n{numbered}\n\n"
        "For each contradiction, decide whether one side is clearly better supported. "
        "Return ONLY a JSON array (use [] if there are no contradictions). Each element:\n"
        '{"claims": [<indices>], "tension": "<what conflicts>", '
        '"loser": <index to drop, or null if neither side is clearly stronger>, '
        '"contested": <true if genuinely unresolved, else false>, '
        '"note": "<one-sentence explanation>"}'
    )

    try:
        response = await audited.gemini_generate(
            run_id=run_id,
            tenant_id=tenant_id,
            model=_CONFLICT_MODEL,
            contents=prompt,
        )
    except Exception as exc:
        log.warning("conflict_detector: LLM call failed: %s", exc)
        return []

    raw = getattr(response, "text", None)
    if not raw:
        candidates = getattr(response, "candidates", None) or []
        if candidates:
            parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
            if parts:
                raw = getattr(parts[0], "text", None) or ""
    conflicts = _extract_json_array(raw or "")

    # Defensive normalisation: keep only well-formed entries with in-range indices.
    n = len(claims)
    clean: list[dict] = []
    for c in conflicts:
        if not isinstance(c, dict):
            continue
        idxs = [i for i in (c.get("claims") or []) if isinstance(i, int) and 0 <= i < n]
        if len(idxs) < 2:
            continue
        loser = c.get("loser")
        if not (isinstance(loser, int) and 0 <= loser < n):
            loser = None
        clean.append({
            "claims": idxs,
            "tension": str(c.get("tension", "")),
            "loser": loser,
            "contested": bool(c.get("contested", loser is None)),
            "note": str(c.get("note", "")),
        })

    log.info("conflict_detector: %d conflict group(s) over %d claims", len(clean), n)
    return clean


# ---------------------------------------------------------------------------
# Research scrubber — the SUBTRACTIVE-verification step.
# Removes passages that state/depend on discredited claims (failed adjudication
# or lost a conflict) from the FULL research prose, then synthesis runs on the
# cleaned research. This is what makes verification "stick": a dropped claim
# cannot ride back into the report through the raw research.
# ---------------------------------------------------------------------------

_SCRUB_MODEL = "gemini-2.5-pro"
#: The span proposal is a small JSON list — never the full research text — so a
#: modest budget suffices and the old whole-text-regeneration truncation bug
#: (research silently cut at the model's default output limit) cannot recur.
_SCRUB_MAX_TOKENS = 8192


def _ws_tolerant_pattern(span: str) -> "re.Pattern[str]":
    """Compile a regex matching `span` with any whitespace runs flexible.

    LLM-quoted spans frequently differ from the source only in line breaks /
    double spaces; exact substring matching alone would miss them.
    """
    parts = [re.escape(tok) for tok in span.split()]
    return re.compile(r"\s+".join(parts))


def _delete_span(text: str, span: str) -> tuple[str, bool]:
    """Delete every occurrence of `span` from `text` (exact, then ws-tolerant)."""
    span = (span or "").strip()
    if len(span) < 10:  # refuse tiny spans — too dangerous (could match everywhere)
        return text, False
    if span in text:
        return text.replace(span, " "), True
    try:
        pat = _ws_tolerant_pattern(span)
    except re.error:
        return text, False
    new_text, n = pat.subn(" ", text)
    return (new_text, True) if n else (text, False)


def _delete_sentence_containing(text: str, needle: str) -> tuple[str, bool]:
    """Delete the sentence(s) containing `needle` (exact or ws-tolerant match)."""
    needle = (needle or "").strip()
    if len(needle) < 10:
        return text, False

    idx = text.find(needle)
    length = len(needle)
    if idx == -1:
        try:
            m = _ws_tolerant_pattern(needle).search(text)
        except re.error:
            return text, False
        if not m:
            return text, False
        idx, length = m.start(), m.end() - m.start()

    # Expand to sentence boundaries: previous ./!/?/newline -> next ./!/?/newline
    start = max(text.rfind(ch, 0, idx) for ch in (".", "!", "?", "\n"))
    start = start + 1 if start != -1 else 0
    ends = [text.find(ch, idx + length) for ch in (".", "!", "?", "\n")]
    ends = [e for e in ends if e != -1]
    end = (min(ends) + 1) if ends else len(text)
    return text[:start] + " " + text[end:], True


async def scrub_research(
    *,
    provider_reports: list[tuple[str, dict]],
    removed_claims: list[dict],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> list[tuple[str, dict]]:
    """Return provider_reports with discredited passages removed — SPAN-BASED.

    `removed_claims` are claims that failed fact-checking or lost a conflict.
    Three layers, strongest guarantee last:

      1. LLM span proposal: one audited Gemini call returns a JSON array of
         verbatim text spans that state or depend on the discredited claims.
         (Small output — replaces the old full-text regeneration, which both
         risked silent truncation and was itself unverifiable.)
      2. Deterministic deletion: Python removes each proposed span (exact or
         whitespace-tolerant match). The LLM proposes; it never rewrites.
      3. Evidence assertion: every removed claim's `evidence` snippet still
         present after step 2 has its containing sentence deleted determinis-
         tically, and any survivor is loudly logged. The "verification sticks"
         property no longer depends on LLM compliance.

    Per-provider report structure is preserved. If there is nothing to remove,
    the input is returned unchanged (no LLM call). If the LLM call fails, layers
    2-3 still run on the claims' own evidence snippets (degraded but real scrub
    — the old implementation returned fully UNSCRUBBED text on failure).
    """
    if not removed_claims:
        return provider_reports

    texts: dict[int, str] = {}
    for i, (name, result) in enumerate(provider_reports):
        texts[i] = (result or {}).get("report") or ""
    if not any(texts.values()):
        return provider_reports

    # ── Layer 1: LLM span proposal ────────────────────────────────────────
    discredited_lines = []
    for c in removed_claims:
        line = f"  - CLAIM: {c.get('text', '')}"
        ev = (c.get("evidence") or "").strip()
        if ev:
            line += f"\n    KNOWN LOCATION: {ev}"
        discredited_lines.append(line)
    discredited_block = "\n".join(discredited_lines)

    report_blocks = [
        f"### Provider: {name}\n\n{texts[i]}"
        for i, (name, _r) in enumerate(provider_reports) if texts[i]
    ]
    reports_concatenated = "\n\n---\n\n".join(report_blocks)

    prompt = (
        "Below are research reports and a list of DISCREDITED claims that failed "
        "independent fact-checking.\n\n"
        "Find every sentence or passage in the reports that STATES, or directly "
        "DEPENDS ON, any discredited claim. Return ONLY a JSON array of strings; "
        "each string must be one such passage COPIED VERBATIM from the reports "
        "(exact characters, so it can be located by string matching). Include the "
        "KNOWN LOCATION snippets' full sentences. Do not return anything else. "
        "Use [] if nothing matches.\n\n"
        f"--- DISCREDITED CLAIMS ---\n{discredited_block}\n\n"
        f"--- REPORTS ---\n\n{reports_concatenated}\n\n--- END REPORTS ---"
    )

    spans: list[str] = []
    try:
        config = None
        try:
            from google.genai import types as genai_types  # noqa: PLC0415
            config = genai_types.GenerateContentConfig(
                max_output_tokens=_SCRUB_MAX_TOKENS, temperature=0.0
            )
        except Exception:
            pass
        kwargs: dict = {"config": config} if config is not None else {}
        response = await audited.gemini_generate(
            run_id=run_id,
            tenant_id=tenant_id,
            model=_SCRUB_MODEL,
            contents=prompt,
            **kwargs,
        )
        raw = getattr(response, "text", None)
        if not raw:
            candidates = getattr(response, "candidates", None) or []
            if candidates:
                parts = getattr(getattr(candidates[0], "content", None), "parts", None) or []
                if parts:
                    raw = getattr(parts[0], "text", None) or ""
        spans = [s for s in _extract_json_array(raw or "") if isinstance(s, str)]
    except Exception as exc:
        log.error(
            "scrub_research: span-proposal call failed (%s) — falling back to "
            "evidence-only deterministic scrub", exc,
        )

    # ── Layer 2: deterministic span deletion ──────────────────────────────
    deleted = 0
    for span in spans:
        for i in texts:
            texts[i], removed = _delete_span(texts[i], span)
            deleted += int(removed)

    # ── Layer 3: evidence assertion + deterministic fallback ─────────────
    leftovers = 0
    for c in removed_claims:
        ev = (c.get("evidence") or "").strip()
        if len(ev) < 10:
            continue
        for i in texts:
            while True:
                texts[i], removed = _delete_sentence_containing(texts[i], ev)
                if not removed:
                    break
                deleted += 1
        # Post-condition: the evidence must now be gone everywhere
        for i in texts:
            if ev in texts[i]:
                leftovers += 1
                log.error(
                    "scrub_research: ASSERTION FAILED — discredited evidence still "
                    "present after scrub: %r", ev[:80],
                )

    total_before = sum(len((r or {}).get("report") or "") for _n, r in provider_reports)
    total_after = sum(len(t) for t in texts.values())
    log.info(
        "scrub_research: %d claim(s) discredited, %d span(s) proposed, %d deletion(s), "
        "%d leftover(s); research %d -> %d chars",
        len(removed_claims), len(spans), deleted, leftovers, total_before, total_after,
    )

    return [
        (name, {**(result or {}), "report": texts[i]})
        for i, (name, result) in enumerate(provider_reports)
    ]
