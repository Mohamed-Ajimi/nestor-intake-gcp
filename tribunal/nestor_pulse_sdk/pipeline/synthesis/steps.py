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
from dataclasses import dataclass, field
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


# ---------------------------------------------------------------------------
# D-08 report sections: "Disputed & changed" and "What we could not establish".
#
# Built in Python for the SAME reason the Sources section was moved here (see the
# block at :265-275): a writing model handed a list to "present" truncates,
# merges, reorders and paraphrases it — the LUKOIL validation report was
# observably truncated mid-URL. D-08 requires that the writing model NEVER SEES
# OR REWRITES these two sections, so they are rendered from pipeline data and
# appended AFTER synthesize_report has already returned. The append site is
# pipeline.py::_write_final_report; nothing here is ever put in a prompt.
#
# That rule is also what makes them provable in CI with ZERO LLM calls, no DB and
# no network — the proof bar D-02 puts on this deliverable, and the only bar that
# can be met at all while the Anthropic account sits at its monthly cap.
#
# Same shape as _extract_sources_section throughout: heading first, "*   "
# bullets, and a NAMED PLACEHOLDER on the empty path rather than "" — a consumer
# never has to branch on whether the section exists.
# ---------------------------------------------------------------------------

#: Item/subgroup bounds — NESTOR_TRIBUNAL_* idiom (gates.py:76-81 register), read
#: at import so August can retune with an env change and no code change.
#:
#: T-15.2-35: a provider (or a hostile page steering one) could emit thousands of
#: "couldn't find" lines or one multi-megabyte note, inflating the report, the
#: output row and the PDF export. Bounding is never SILENT — _truncated_items
#: names the loss in the report itself (phase rule 6).
_SECTION_ITEM_CHARS = int(os.environ.get("NESTOR_TRIBUNAL_SECTION_ITEM_CHARS", "400"))
_SECTION_MAX_ITEMS = int(os.environ.get("NESTOR_TRIBUNAL_SECTION_MAX_ITEMS", "200"))

#: The tag _collect_superseded_notes puts on every caveat line it emits
#: (pipeline.py). Stripped for display: the reader wants the caveat, not our
#: internal marker.
_SUPERSEDED_PREFIX = "[SUPERSEDED] "

#: Fallback wording when a subgroup is capped. English by default and localisable
#: by adding a "truncated" key to a _SECTION_STRINGS entry — the same one-entry
#: map edit that adds a language.
_TRUNCATED_TEMPLATE = "*   … and {k} further item(s) not listed here (list truncated at {cap})."


def _flatten(value: Any) -> str:
    """Collapse ALL whitespace (newlines included) to single spaces, then strip.

    Mirrors `pipeline.py::_one_line`, and deliberately does not import it:
    `steps.py` is imported BY `pipeline.py`, so the dependency only runs one way.

    This is the MARKDOWN CONTAINMENT CONTROL (T-15.2-31), not formatting. Every
    string these builders render is model-authored, several of them derived from
    arbitrary web pages a provider read. Flattened onto one line after a "*   "
    bullet, an item can no longer open a heading, a nested list or a "---" rule of
    its own and forge a section in the operator's report.
    """
    return " ".join(str(value or "").split())


def _sanitize(value: Any) -> str:
    """Flatten, strip citation markers, then truncate. NEVER raises.

    The reuse chain, in order — no stripper and no regex is written here:

    1. `_flatten` (containment, above).
    2. `strip_unresolved_cite_markers` — the PROVIDER's `[cite: N]` mechanism,
       already owned by `audit/audited_llm_client.py`.
    3. the anchor pattern exported by `citations/anchors.py` — OUR mechanism.
    4. truncation to `_SECTION_ITEM_CHARS`, with a single "…" marking the cut.
    """
    flat = _flatten(value)
    if not flat:
        return ""
    try:
        # Function-local imports: the audited client imports this module's peers,
        # so a module-level import would close a cycle. Precedent:
        # pipeline.py's own function-local import of the same symbol.
        from nestor_pulse_sdk.audit.audited_llm_client import (  # noqa: PLC0415
            strip_unresolved_cite_markers,
        )
        # The COUNT is discarded on purpose. These markers sit inside pipeline
        # DATA (reconciliation notes, gap text), not in report prose, so counting
        # them here would pollute D-06's orphan-marker number — which 15.2-05
        # measures on the report body and 15.2-08 surfaces.
        flat, _n_cites = strip_unresolved_cite_markers(flat)
        # Anchor tokens. These sections are appended AFTER 15.2-05's anchor
        # post-pass has already run, so an anchor-shaped token that arrived via a
        # scraped page and rode through a claim into a note is past every existing
        # stripper and would ship as literal garbage (T-15.2-32). Reuse the ONE
        # existing pattern; a second regex here could drift from it.
        from nestor_pulse_sdk.citations.anchors import ANCHOR_RE as _anchor_re  # noqa: PLC0415
        flat = _flatten(_anchor_re.sub("", flat))
    except Exception as exc:  # noqa: BLE001 — a sanitizer must never break a report
        log.warning("report sections: sanitize fell back to flatten-only: %r", exc)
        return _flatten(value)
    if _SECTION_ITEM_CHARS > 0 and len(flat) > _SECTION_ITEM_CHARS:
        flat = flat[:_SECTION_ITEM_CHARS].rstrip() + "…"
    return flat


#: Alias -> canonical language token. `mission_brief["language"]` carries an
#: ENGLISH LANGUAGE NAME emitted by intake.py's `LANGUAGE:` line ("English",
#: "Dutch", "French", "German"), or "" when undetected.
_LANG_ALIASES = {
    "": "english",
    "en": "english",
    "engels": "english",
    "english": "english",
    "nl": "dutch",
    "nederlands": "dutch",
    "dutch": "dutch",
    "de": "german",
    "deutsch": "german",
    "german": "german",
    "fr": "french",
    "français": "french",
    "francais": "french",
    "french": "french",
}


def _norm_lang(language: Any) -> str:
    """Normalise a run language to a `_SECTION_STRINGS` key, English on anything else.

    A one-call flash translation of these headings is REJECTED: it would put an
    LLM back in the loop of a section whose entire point is that no model touches
    it, and it would break byte-stability across two renders of the same data.

    The English fallback is the house precedent — `_verification_appendix` and
    `_extract_sources_section` already emit English headings on every run
    regardless of the run language. Adding a language is a ONE-ENTRY EDIT to
    `_SECTION_STRINGS` (plus its aliases here); no code changes.
    """
    try:
        token = str(language or "").strip().lower()
    except Exception:  # noqa: BLE001 — a hostile __str__ must not break a report
        return "english"
    hit = _LANG_ALIASES.get(token)
    if hit:
        return hit
    log.warning(
        "report sections: no heading translation for language %r — using English headings",
        language,
    )
    return "english"


#: Every fixed string of both D-08 sections, per language. Deterministic by
#: construction: same input, same bytes, no model, no clock.
_SECTION_STRINGS: dict[str, dict[str, str]] = {
    "english": {
        "disputed_h": "## Disputed & changed",
        "sub_contradictions": "### Contradictions settled during fact-checking",
        "sub_superseded": "### Findings overtaken by newer information",
        "sub_brief": "### Where the brief did not match what the research found",
        "disputed_empty": (
            "*(No contradiction was settled and no finding was overtaken during "
            "fact-checking.)*"
        ),
        "gaps_h": "## What we could not establish",
        "gaps_empty": "*(No provider reported a research gap.)*",
        "gaps_none_for_provider": "reported no research gaps.",
        "gaps_unreadable": (
            "*(The research-gap list could not be read from the database while this "
            "report was written — see the run log. This is a reporting failure, NOT a "
            "statement that no gaps exist.)*"
        ),
    },
    "dutch": {
        "disputed_h": "## Betwist & gewijzigd",
        "sub_contradictions": "### Tegenstrijdigheden opgelost tijdens de feitencontrole",
        "sub_superseded": "### Bevindingen achterhaald door nieuwere informatie",
        "sub_brief": "### Waar de briefing niet overeenkwam met wat het onderzoek vond",
        "disputed_empty": (
            "*(Er zijn geen tegenstrijdigheden opgelost en geen bevindingen achterhaald "
            "tijdens de feitencontrole.)*"
        ),
        "gaps_h": "## Wat we niet hebben kunnen vaststellen",
        "gaps_empty": "*(Geen enkele provider heeft een onderzoekslacune gemeld.)*",
        "gaps_none_for_provider": "heeft geen onderzoekslacunes gemeld.",
        "gaps_unreadable": (
            "*(De lijst met onderzoekslacunes kon bij het schrijven van dit rapport niet "
            "uit de database worden gelezen — zie het runlogboek. Dit is een "
            "rapportagefout, GEEN bevestiging dat er geen lacunes zijn.)*"
        ),
    },
    "german": {
        "disputed_h": "## Strittig & geändert",
        "sub_contradictions": "### Während der Faktenprüfung geklärte Widersprüche",
        "sub_superseded": "### Durch neuere Informationen überholte Erkenntnisse",
        "sub_brief": "### Wo das Briefing nicht mit den Rechercheergebnissen übereinstimmte",
        "disputed_empty": (
            "*(Bei der Faktenprüfung wurden keine Widersprüche geklärt und keine "
            "Erkenntnis wurde überholt.)*"
        ),
        "gaps_h": "## Was wir nicht belegen konnten",
        "gaps_empty": "*(Kein Anbieter hat eine Recherchelücke gemeldet.)*",
        "gaps_none_for_provider": "hat keine Recherchelücken gemeldet.",
        "gaps_unreadable": (
            "*(Die Liste der Recherchelücken konnte beim Schreiben dieses Berichts nicht "
            "aus der Datenbank gelesen werden — siehe das Run-Protokoll. Dies ist ein "
            "Berichtsfehler und KEINE Aussage darüber, dass es keine Lücken gibt.)*"
        ),
    },
    "french": {
        "disputed_h": "## Contesté & modifié",
        "sub_contradictions": "### Contradictions tranchées lors de la vérification des faits",
        "sub_superseded": "### Conclusions dépassées par des informations plus récentes",
        "sub_brief": (
            "### Là où le briefing ne correspondait pas aux résultats de la recherche"
        ),
        "disputed_empty": (
            "*(Aucune contradiction n'a été tranchée et aucune conclusion n'a été "
            "dépassée lors de la vérification des faits.)*"
        ),
        "gaps_h": "## Ce que nous n'avons pas pu établir",
        "gaps_empty": "*(Aucun fournisseur n'a signalé de lacune de recherche.)*",
        "gaps_none_for_provider": "n'a signalé aucune lacune de recherche.",
        "gaps_unreadable": (
            "*(La liste des lacunes de recherche n'a pas pu être lue depuis la base de "
            "données lors de la rédaction de ce rapport — voir le journal du run. Il "
            "s'agit d'une erreur de rapport, et NON de l'affirmation qu'il n'existe "
            "aucune lacune.)*"
        ),
    },
}


def _truncated_items(items: list[str], strings: dict) -> list[str]:
    """Apply `_SECTION_MAX_ITEMS` and, when it bites, NAME the loss in words.

    Never a silent drop (phase rule 6): the reader is told how many items were
    left out and what the cap was.
    """
    if _SECTION_MAX_ITEMS <= 0 or len(items) <= _SECTION_MAX_ITEMS:
        return list(items)
    kept = list(items[:_SECTION_MAX_ITEMS])
    template = (strings or {}).get("truncated") or _TRUNCATED_TEMPLATE
    kept.append(
        template.format(k=len(items) - _SECTION_MAX_ITEMS, cap=_SECTION_MAX_ITEMS)
    )
    return kept


def build_disputed_and_changed(
    *,
    group_reconciliations: Optional[list] = None,
    superseded_notes: Optional[list] = None,
    brief_conflicts: Optional[list] = None,
    language: str = "",
) -> str:
    """Render the "Disputed & changed" section (D-08).

    PURE: no LLM, no DB, no clock, no I/O. Byte-identical across calls for
    identical input — no set iteration, no dict-insertion luck, no id() leak. The
    caller appends the result AFTER synthesis, so the writing model never sees it
    and cannot omit, merge, truncate or rewrite an item.

    Three subgroups, always in this order, each rendered only when non-empty:
    the contradictions the group skeptics settled, the findings a `superseded`
    verdict overtook, and the workshop's brief-vs-world flags. When all three are
    empty the section STILL renders — heading plus a named placeholder sentence.

    Never raises: a non-dict entry, a non-string note or a hostile __str__ costs
    that one item, never the section.
    """
    strings = _SECTION_STRINGS[_norm_lang(language)]
    try:
        body: list[str] = []

        # 1. Contradictions the group skeptics settled. Entries reach
        #    `group_reconciliations` only when `disputed` or relation == "scoped"
        #    (the narrow filter in pipeline.py), so this does NOT re-filter on
        #    that — only on "does this entry have anything to say".
        contradictions: list[str] = []
        for entry in group_reconciliations or []:
            if not isinstance(entry, dict):
                continue  # ASVS V5: skip the bad item, keep the rest
            note = _sanitize(entry.get("note"))
            canonical = _sanitize(entry.get("canonical"))
            if not note and not canonical:
                continue
            entity = _sanitize(entry.get("entity")) or "?"
            attribute = _sanitize(entry.get("attribute")) or "?"
            # The SAME two words pipeline.py already uses for these two
            # conditions. No third vocabulary.
            tag = "DISPUTED" if entry.get("disputed") else "scope-dependent"
            parts = [f"*   **{entity} — {attribute}** — {tag}:"]
            if note:
                parts.append(note)
            if canonical:
                parts.append(f"Settled reading: {canonical}")
            contradictions.append(" ".join(parts))
        if contradictions:
            body.append(
                strings["sub_contradictions"]
                + "\n\n"
                + "\n".join(_truncated_items(contradictions, strings))
            )

        # 2. Superseded caveats — consumed verbatim from _collect_superseded_notes
        #    and never re-derived from verdicts. The internal tag is stripped for
        #    display. This list arrives UNCAPPED: _SUPERSEDED_NOTE_CAP bounds the
        #    synthesis PROMPT, and this is not a prompt.
        superseded: list[str] = []
        for raw in list(dict.fromkeys(superseded_notes or [])):
            if not isinstance(raw, str):
                continue
            rest = raw[len(_SUPERSEDED_PREFIX):] if raw.startswith(_SUPERSEDED_PREFIX) else raw
            text_value = _sanitize(rest)
            if text_value:
                superseded.append(f"*   {text_value}")
        superseded = list(dict.fromkeys(superseded))
        if superseded:
            body.append(
                strings["sub_superseded"]
                + "\n\n"
                + "\n".join(_truncated_items(superseded, strings))
            )

        # 3. The workshop's brief-vs-world flags (D4). Tolerant input on purpose:
        #    plan 15.2-13 wires the producer, and this section must not care
        #    whether it hands over strings or dicts.
        #
        #    THE `assumption` / `world_says` BRANCH IS THE ONE THE ENGINE ACTUALLY
        #    USES, and it is the reason this loop is not just the three keys above.
        #    `workshop._parse_orientation` emits
        #    `{question, assumption, world_says, source_url}` — it has never
        #    emitted `note`, `text` or `finding`. So every real brief-vs-world flag
        #    fell through the three-key lookup, rendered as the empty string, was
        #    dropped by the `if text_value` guard, and the whole
        #    "Where the brief did not match what the research found" subgroup
        #    silently never appeared in ANY report. Nothing caught it because the
        #    producer and the consumer are tested in different files, against
        #    different hand-made fixtures, and neither one drove the hand-off.
        #    The stubbed end-to-end run (`tests/test_engine_e2e_stubbed.py`) is
        #    what surfaced it. The three legacy keys are kept and still take
        #    priority, so this is purely additive.
        flags: list[str] = []
        for item in brief_conflicts or []:
            if item is None:
                continue
            if isinstance(item, str):
                raw_flag: Any = item
            elif isinstance(item, dict):
                raw_flag = ""
                for key in ("note", "text", "finding"):
                    candidate = item.get(key)
                    if candidate:
                        raw_flag = candidate
                        break
                if not raw_flag:
                    # The producer's own shape, composed into one sentence. Both
                    # halves are required: an assumption with nothing to contrast
                    # it against, or a world reading with no assumption named, is
                    # not a conflict and must not be printed as one.
                    assumption = _sanitize(item.get("assumption"))
                    world_says = _sanitize(item.get("world_says"))
                    if assumption and world_says:
                        raw_flag = (
                            f"The brief assumes: {assumption} "
                            f"The research found: {world_says}"
                        )
                        source_url = _sanitize(item.get("source_url"))
                        if source_url.startswith(("http://", "https://")):
                            raw_flag += f" ({source_url})"
            else:
                raw_flag = str(item)
            text_value = _sanitize(raw_flag)
            if text_value:
                flags.append(f"*   {text_value}")
        if flags:
            body.append(
                strings["sub_brief"] + "\n\n" + "\n".join(_truncated_items(flags, strings))
            )

        if not body:
            body = [strings["disputed_empty"]]
        return "\n\n".join([strings["disputed_h"]] + body)
    except Exception as exc:  # noqa: BLE001 — a report section must never break a run
        log.warning("report sections: build_disputed_and_changed failed: %r", exc)
        return f"{strings['disputed_h']}\n\n{strings['disputed_empty']}"


def build_could_not_establish(
    *,
    not_found_by_provider: Optional[dict] = None,
    language: str = "",
) -> str:
    """Render the "What we could not establish" section (D-08).

    PURE: no LLM, no DB, no clock, no I/O. Byte-identical across calls for
    identical input; providers are emitted in `sorted()` order so a DB read's
    row order can never change the bytes. The caller appends the result AFTER
    synthesis, so the writing model never sees it.

    THREE DISTINCT STATES, and the difference between the first two is the whole
    point (T-15.2-33):

    * `None`  -> the gap list COULD NOT BE READ. Rendered as a named failure
      sentence. Rendering "no gaps" over a database error would put a false
      factual statement into a client-bound document.
    * `{}`    -> read fine, nothing to report.
    * populated -> one block per provider; a provider with an empty list is
      NAMED as having reported no gaps rather than omitted.

    Never raises.
    """
    strings = _SECTION_STRINGS[_norm_lang(language)]
    heading = strings["gaps_h"]
    if not_found_by_provider is None:
        return f"{heading}\n\n{strings['gaps_unreadable']}"
    try:
        if not isinstance(not_found_by_provider, dict) or not not_found_by_provider:
            return f"{heading}\n\n{strings['gaps_empty']}"

        blocks: list[str] = []
        # sorted() by the string form: determinism, never dict-insertion order
        # coming out of a DB read, and never a TypeError on mixed key types.
        for provider in sorted(not_found_by_provider.keys(), key=str):
            # Provider names come from the parser, not a hardcoded enum, so they
            # are untrusted text too.
            name = _sanitize(provider)[:60] or "?"
            raw_items = not_found_by_provider.get(provider)
            if isinstance(raw_items, (list, tuple)):
                candidates = list(raw_items)
            elif raw_items is None or raw_items == "":
                candidates = []
            else:
                candidates = [raw_items]
            bullets: list[str] = []
            for item in candidates:
                text_value = _sanitize(item)
                if text_value:
                    bullets.append(f"*   {text_value}")
            bullets = list(dict.fromkeys(bullets))
            if bullets:
                blocks.append(
                    f"**{name}**\n\n" + "\n".join(_truncated_items(bullets, strings))
                )
            else:
                blocks.append(f"**{name}** — {strings['gaps_none_for_provider']}")
        return "\n\n".join([heading] + blocks)
    except Exception as exc:  # noqa: BLE001 — a report section must never break a run
        log.warning("report sections: build_could_not_establish failed: %r", exc)
        return f"{heading}\n\n{strings['gaps_empty']}"


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

#: Literal column separators accepted by `_split_distiller_line`, IN PRIORITY
#: ORDER. The order is the contract, not a style choice -- see that function.
_DISTILLER_SEPARATORS: tuple[str, ...] = ("\t", "<TAB>", "|||", "|")
#: Last-resort separator: a run of two or more spaces. Tried only when no
#: literal separator above is present anywhere in the line.
_DISTILLER_SPACE_RUN = re.compile(r" {2,}")


def _split_distiller_line(line: str) -> list[str] | None:
    """Split one distiller output line into up to 3 columns, separator-tolerant.

    Returns the column list (1-3 entries, each stripped) or ``None`` when the
    line carries no recognisable separator at all -- in which case the caller
    drops it exactly as the old tab-only code did.

    WHY THIS EXISTS -- THE V-01 DEFECT (run 7dcf51d5, 2026-07-28)
    ------------------------------------------------------------
    The distiller prompt described its separator with the placeholder token
    ``<TAB>``. Two of four gemini-2.5-flash calls IN THE SAME BATCH, at
    temperature 0.0, copied that placeholder back as five literal characters
    instead of emitting U+0009. `_parse_distiller_response` tested
    ``if "\\t" not in line`` and threw away **278 well-formed, three-column,
    evidence-bearing coffee claims** -- every one of which would have passed
    every downstream filter. The only trace was a ``log.debug``, which
    production does not serve, so the delivered client report went out saying
    the Benelux coffee data "geeft geen volledig beeld". That statement was
    false, and this three-line function is why it can no longer happen.

    THE ORDER IS THE CONTRACT. Every step of it is load-bearing:

    * ``"\\t"`` FIRST -- the real tab is what a compliant model emits and what
      the existing tab-separated canned fixtures use. A line that contains BOTH
      a real tab and a literal ``<TAB>`` MUST split on the tab, because the tab
      is the deliberate separator and the ``<TAB>`` is then data.
    * ``"<TAB>"`` SECOND -- so a placeholder-copying model is read correctly.
      This is the line that recovers V-01's 278.
    * ``"|||"`` BEFORE ``"|"`` -- every ``|||`` line also contains ``|``, so
      testing ``|`` first would split ``A ||| B`` into ``["A", "", "| B"]``.
      ``|||`` is also the CURRENT prompt contract (D-R1(b)).
    * the 2+-space run LAST, and only when no literal separator is present at
      all -- it is the only separator here that can occur inside ordinary
      prose, so it must never pre-empt a real one. The downstream
      ``len(claim_text) < 10`` drop is what keeps an accidental prose split
      from becoming a forged claim (T-15.4-08).
    """
    for sep in _DISTILLER_SEPARATORS:
        if sep in line:
            return [p.strip() for p in line.split(sep, 2)]
    parts = _DISTILLER_SPACE_RUN.split(line, maxsplit=2)
    if len(parts) > 1:
        return [p.strip() for p in parts]
    return None


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
    provider_reports: list,
    focus_area_labels: list[str],
    language: str = "",
    *,
    full_extraction: bool = False,
) -> str:
    """Build the plain-text distiller prompt.

    THE CONTRACT IS ``FACET ||| CLAIM_TEXT ||| EVIDENCE`` (one claim per line),
    mirroring the RelevanceGate line discipline (CLAUDE.md anti-pattern section).
    NOT JSON mode — citations⊗structured-outputs HTTP 400 trap.

    A REAL TAB IS STILL ACCEPTED BY THE PARSER, AND IS DELIBERATELY NOT NAMED
    HERE. `_split_distiller_line` takes a tab first in its priority order, so
    every compliant model and every existing tab-separated fixture keeps
    working. What changed is that this prompt no longer DESCRIBES its separator
    with a token the model can render as characters.

    WHY (V-01, run 7dcf51d5, 2026-07-28)
    ------------------------------------
    This prompt used to say ``FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE``. Two of four
    gemini-2.5-flash calls in one batch, at temperature 0.0, copied the
    placeholder back as five literal characters. The parser tested for U+0009,
    found none, and discarded **278 well-formed, evidence-bearing coffee
    claims** — after which the delivered client report stated that the Benelux
    coffee data "geeft geen volledig beeld". That was false, and it was caused
    by a placeholder describing a control character. Do not reintroduce
    ``<TAB>``, or any other angle-bracket placeholder standing for a character
    the model cannot see, anywhere in the returned string.

    WHAT ACTUALLY GUARDS THIS CONTRACT — READ THIS BEFORE EDITING
    -------------------------------------------------------------
    The previous version of this docstring claimed the default prompt stayed
    "BYTE-IDENTICAL to the one `test_claim_distiller.py` and
    `test_distiller_coverage.py` pin". **NEITHER OF THOSE TWO FILES PINS THIS
    PROMPT, AND NEITHER EVER DID** — verified by reading both on 2026-07-29:

      * ``test_distiller_coverage.py`` asserts NOTHING about the prompt. It
        regexes ``### Provider: (\\w+)`` and splits on ``--- Research reports ---``
        inside its fake client (lines 35 and 37) purely to route a canned
        response back.
      * ``test_claim_distiller.py`` does the same at line 339. Its only tab
        reference is its canned *response* fixture, which is test INPUT, not an
        assertion about this function's output.

    So the ``|||`` switch turned neither of them red, and no green gate proved
    anything about this contract. A docstring that claims coverage which does
    not exist is worse than no docstring: it is precisely what made this edit
    look safe. The coverage now genuinely exists — it is
    ``tests/test_distiller_separators.py::TestDistillerPromptContract``, whose
    assertions are that the built prompt CONTAINS
    ``FACET ||| CLAIM_TEXT ||| EVIDENCE`` and contains NO ``<TAB>``, under the
    default, ``full_extraction=True`` and non-empty-``language`` variants.
    **That class is what holds this contract. Change this string and it goes
    red; that is the intended way to find out.**

    ``full_extraction`` (D-14, plan 15.2-14) switches on the PER-PROVIDER FALLBACK
    voice: this report carried no usable machine-readable fact list, so this
    extraction is the only record of what that researcher found. It is built as an
    extra rule fragment that is the EMPTY STRING in the default case, exactly the
    way ``lang_rule`` is — so the D-14 and language fragments cannot smuggle a
    separator placeholder into the default prompt. That mechanism is unchanged
    by this edit; only the claim about who tests it was wrong.
    """
    facet_block = "\n".join(f"  - {f}" for f in focus_area_labels) or "  - general"

    lang = (language or "").strip()
    lang_rule = (
        f"  - Write CLAIM_TEXT in {lang}. If a report is in another language, "
        f"TRANSLATE the claim into {lang} (the whole run is one language).\n"
        if lang else ""
    )

    # D-14: empty by default, so the default prompt is byte-identical to today's.
    full_rule = (
        "  - This report did NOT include a machine-readable fact list, so THIS\n"
        "    extraction is the ONLY record of what this researcher found. Extract\n"
        "    every distinct atomic fact from the WHOLE report, beginning to end. Do\n"
        "    NOT summarise, do NOT prioritise, and do NOT stop early.\n"
        if full_extraction else ""
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
        "  - Each line MUST use this format: FACET ||| CLAIM_TEXT ||| EVIDENCE\n"
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
        f"{full_rule}"
        "  - Blank lines and lines without at least one ||| separator are ignored.\n\n"
        f"Focus area labels (use one per claim):\n{facet_block}\n\n"
        f"--- Research reports ---\n\n{reports_text}\n\n"
        "--- End reports ---\n\n"
        "Output claims now (one per line, FACET ||| CLAIM_TEXT ||| EVIDENCE format):"
    )


def _parse_distiller_response(text: str, focus_area_labels: list[str], *, provider: str = "") -> list[dict]:
    """Parse plain-text column-separated lines into claim dicts.

    Contract: ``FACET ||| CLAIM_TEXT ||| EVIDENCE`` (EVIDENCE optional for
    back-compat). The COLUMN SPLIT is separator-tolerant -- see
    `_split_distiller_line` for the accepted separators and why their priority
    order is load-bearing. Blank lines, and lines carrying no separator of any
    accepted kind, are skipped defensively.

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
        # Up to 3 columns: facet, claim_text, evidence. Evidence is optional so a
        # 2-column response (legacy / model omission) still parses. The split is
        # separator-TOLERANT (D-R1(a)): this used to be a bare
        # `if "\t" not in line: continue` plus `line.split("\t", 2)`, and that
        # string comparison silently discarded 278 well-formed claims on V-01.
        parts = _split_distiller_line(line)
        if parts is None:
            # Malformed line — no separator of any accepted kind. Skip without
            # raising, exactly as before. `_distill_unit` is what says so out
            # loud when a whole response parses to nothing (D-R1(c)).
            log.debug("claim_distiller: skipping malformed line (no separator): %r", line[:80])
            continue
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

    THE CROSS-STREAM MERGE POINT (15.2-15, D9/D-13)
    ----------------------------------------------
    Since 15.2-14 this function is called ONCE over every stream's claims at
    once, so "a duplicate" now usually means "two different research streams
    stated the same fact". That makes it the place where four streams' views of
    one fact become one claim, and three more things have to survive the collapse
    besides ``found_by``:

    * **``source_urls`` are UNIONED.** Without this the corroborating provider's
      source link is silently discarded and never becomes a ``claim_source`` row
      — the citation for the second, independent confirmation of a fact would be
      the one thing the merge threw away.
    * **``provider_quality_by_url``** is maintained as a plain ``dict[str, str]``
      so a URL is always graded by the provider that SUPPLIED it. Each side seeds
      the map lazily from its own scalar ``provider_quality`` applied to its own
      ``source_urls``; an existing entry is never overwritten, so the first
      provider to introduce a URL owns its grading. (A plain dict, not a set or a
      tuple key: this rides into ``synthesis_cache`` JSON.)
    * **``certainty`` takes the CAUTIOUS value.** If either side says ``single``,
      the merged claim is ``single``. G-11, fail toward more checking: a fact one
      provider only found once does not become ``certain`` because another
      provider was confident about its own copy.

    Every one of those branches is guarded on the key being present, because
    ``claim_distiller`` claims carry no ``source_urls``, no ``provider_quality``
    and no ``certainty`` — their behaviour here is byte-identical to before.
    """
    seen: dict[str, dict] = {}
    out: list[dict] = []
    n_merged = 0
    for c in claims:
        norm = re.sub(r"[^a-z0-9 ]", "", (c.get("text") or "").lower())
        norm = re.sub(r"\s+", " ", norm).strip()
        if not norm:
            continue
        kept = seen.get(norm)
        if kept is not None:
            n_merged += 1
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

            # --- D-13: per-URL provider-stated quality, seeded from both sides.
            # Seeded BEFORE the URL union so each side's map is built from its own
            # urls with its own scalar grade; after the union the sides are no
            # longer distinguishable.
            _seed_provider_quality_by_url(kept)
            incoming_urls = c.get("source_urls")
            if isinstance(incoming_urls, list) and incoming_urls:
                _seed_provider_quality_by_url(c)
                incoming_map = c.get("provider_quality_by_url")
                if isinstance(incoming_map, dict) and incoming_map:
                    kept_map = kept.get("provider_quality_by_url")
                    if not isinstance(kept_map, dict):
                        kept_map = {}
                        kept["provider_quality_by_url"] = kept_map
                    for url, quality in incoming_map.items():
                        # NEVER overwrite: the provider that introduced a URL is
                        # the one whose grading of it is meaningful.
                        kept_map.setdefault(url, quality)

                # --- Union the source urls, order-stable and duplicate-free.
                kept_urls = kept.get("source_urls")
                if not isinstance(kept_urls, list):
                    kept_urls = []
                    kept["source_urls"] = kept_urls
                for url in incoming_urls:
                    if url and url not in kept_urls:
                        kept_urls.append(url)

            # --- G-11: the cautious certainty wins. The `== "single"` test IS
            # the guard — a claim pair that never stated a certainty (the
            # distiller's shape) can never satisfy it, so no key is invented.
            if c.get("certainty") == "single" or kept.get("certainty") == "single":
                kept["certainty"] = "single"
            continue
        seen[norm] = c
        out.append(c)
    if n_merged:
        # The collapse is a LOSS of one statement into another and is named as
        # such in the run log, not only in the stage feed (fail loud, in words).
        log.info(
            "_dedupe_claims: %d duplicate statement(s) merged into %d distinct "
            "claim(s) — found_by, source_urls and per-url provider quality were "
            "carried over; the cautious certainty won",
            n_merged, len(out),
        )
    return out


def _seed_provider_quality_by_url(claim: dict) -> None:
    """Lazily give one claim a ``{url: provider_quality}`` map of its OWN urls.

    A no-op for a claim that already has a (non-empty) map, that has no urls, or
    that has no provider-stated quality — a distiller-produced claim has none of
    the three and comes out of here untouched.

    WHY A MAP AT ALL: ``provider_quality`` is a SCALAR on the claim ("this
    provider says its source is official"), but after the cross-stream merge one
    claim carries several providers' urls, and grading them all by the surviving
    scalar would attribute one provider's judgement to another provider's source.
    """
    if not isinstance(claim, dict):
        return
    existing = claim.get("provider_quality_by_url")
    if isinstance(existing, dict) and existing:
        return
    quality = claim.get("provider_quality")
    if not quality or not isinstance(quality, str):
        return
    urls = claim.get("source_urls")
    if not isinstance(urls, list) or not urls:
        return
    claim["provider_quality_by_url"] = {
        str(url): quality for url in urls if url and isinstance(url, str)
    }


async def claim_distiller(
    *,
    provider_reports: list,
    mission_brief: dict,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    full_extraction: bool = False,
) -> list[dict]:
    """Distil provider reports into atomic claims via an audited gemini-flash call.

    Un-stubbed in Plan 01-13 Task 2 (previously raised NotImplementedError).
    The Tribunal skeptic (Plan 01-14) consumes these claims for per-claim
    stakes triage and verification.

    READ THIS BEFORE DELETING ANYTHING — D-15
    -----------------------------------------
    V-03 removes the WIRING that made this function the primary claim source (the
    "distiller-as-shredder" path, where every provider's prose was shredded into
    claims whether or not the provider had supplied a structured list). V-03 does
    NOT remove THIS FUNCTION. Since 15.2-14 its ``full_extraction`` mode is D-14's
    per-provider fallback: the path taken by a research stream that ignored the
    fact-list instruction, so that the stream is neither dropped nor re-researched.

    It also keeps its own tests. ``tests/test_claim_distiller.py`` and
    ``tests/test_distiller_coverage.py`` MUST STAY GREEN THROUGH V-03
    (CONTEXT.md D-15, RESEARCH Pitfall 13). Anyone told to "remove the old engine
    path" should stop here: the thing to unwire lives in ``pipeline.py``, not in
    this module.

    Args:
        provider_reports: list of (provider_name, result_dict) tuples from
                          run_all_with_degradation. Empty/blank reports produce
                          zero claims, not an exception.
        mission_brief:    mission_brief dict from adaptive_intake (or orchestrator
                          pass-through). Used to seed available facet labels.
        audited:          Injected AuditedLLMClient — the ONLY LLM egress.
        run_id:           UUID for the current run (audit chain).
        tenant_id:        UUID for the current tenant (audit chain).
        full_extraction:  D-14 fallback mode. Default False keeps the prompt and
                          every observable behaviour byte-identical to today's.

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

    mode = "full-extraction" if full_extraction else "safety-net"

    async def _distill_unit(name: str, chunk: str) -> list[dict]:
        prompt = _build_distiller_prompt(
            [(name, {"report": chunk})],
            focus_area_labels,
            language,
            full_extraction=full_extraction,
        )
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
        "claim_distiller: %d units distilled (mode=%s), claims per facet: %s",
        len(units), mode, facet_counts,
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
        "(%d distinct providers named in found_by, mode=%s)",
        before, len(claims), len(provider_reports), distinct_providers, mode,
    )
    return claims


# ---------------------------------------------------------------------------
# Step 3b: D8-first claim collection with the D-14 per-provider fallback.
# Plan 15.2-14. This function is the drop-in replacement for the bare
# `claim_distiller(...)` call in `pipeline.py`'s distill stage; 15.2-15 does the
# wiring. NOTHING here is a new parser, deduper, stripper or tier table — the D8
# format and its tolerant parser are 15.2-04's `pipeline/tribunal/facts.py`, and
# the prose path is `claim_distiller` above.
# ---------------------------------------------------------------------------

#: Cross-provider cap on the deduped "we looked and could not establish this"
#: list. Per-report count and per-entry length are already bounded by 15.2-04's
#: parser; this bounds the UNION, which is what reaches a JSONB column and the
#: operator's report. NESTOR_TRIBUNAL_* idiom (grouping.py).
_NOT_FOUND_TOTAL_MAX = int(os.environ.get("NESTOR_TRIBUNAL_NOT_FOUND_TOTAL_MAX", "300"))

#: The nine keys 15.2-04 guarantees on every fact dict, in its order.
_FACT_CLAIM_KEYS: tuple[str, ...] = (
    "text", "facet", "evidence", "found_by", "source_urls",
    "certainty", "provider_quality", "source_domain", "quality_tier_hint",
)


@dataclass(frozen=True)
class ProviderFactsRecord:
    """One provider's D8 accounting — every integer is a NAMED loss or yield.

    This is the fail-loud contract (`verification/report.py:184-190`): a stream
    that quietly produced less than it should have must be visibly, numerically
    degraded, never a silent green.

    ``prompted`` is False when the stream was NEVER ASKED for a fact list — either
    the ``NESTOR_TRIBUNAL_D8_FACT_LIST`` kill switch is off, or it is the
    own-researcher stream, which emits its facts through a forced client tool
    instead. That is NOT a provider failure and must never be worded as one: an
    operator told "gemini did not comply" when gemini was never asked has been
    given a false fault report.

    ``reason`` carries 15.2-04's own ``FactListResult.fallback_reason`` sentence
    VERBATIM (its module writes it to be read by a human without reading this
    one); the count-bearing sentence an operator sees lives in
    ``ProviderFactsResult.fallback_notes``.
    """

    provider: str
    reports_seen: int = 0
    reports_with_fact_list: int = 0
    reports_fell_back: int = 0
    facts_from_list: int = 0
    claims_from_fallback: int = 0
    parse_errors: int = 0
    rejected_urls: int = 0
    dropped_over_cap: int = 0
    prompted: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class ProviderFactsResult:
    """What the distill stage now produces. THREE CONSUMER CONTRACTS:

    (a) ``claims`` is the merge's input (15.2-15). Every entry carries the nine
        15.2-04 keys plus ``fact_source``, whichever path produced it.

    (b) ``reports`` is a DROP-IN REPLACEMENT for ``provider_results`` from the
        distill stage onward — same length, same order, same tuple/dict shape,
        every other key preserved — with the machine-readable block already
        removed from the prose. Use it in place of ``provider_results`` so that
        ``scrub_research``, ``synthesize_report`` and ``_extract_sources_for_*``
        all see clean report text. Leaving the block in would double-count every
        fact and render as tab-salad in the deliverable.

    (c) ``fallback_notes`` and ``not_found`` are surfaced in the verification
        report — AND ``fallback_notes`` MUST NOT BE FED INTO ``terminal_state()``,
        nor into ``pipeline.run()``'s ``_note_degradation`` accumulator, which is
        what feeds it. Per D-14 a fallback "degrades one stream, not the run".
        D-12's degrading conditions are: a non-zero bucket 3, a stream lost to a
        tripped breaker, a workshop fallback, or a skipped stage. A D-14 fallback
        is none of those — the provider's research still reached the merge in
        full. Promoting it would drain ``completed_degraded`` of meaning in
        exactly the way D-12 warns about for recovered retries.

    (d) ``not_found_by_provider`` is (c)'s SAME couldn't-find material with the
        attribution kept (15.2-15). ``not_found`` is a flat, text-deduped union
        for prose; the ``research_gap`` TABLE has a NOT NULL ``provider`` column
        and 15.2-06's reader groups its "What we could not establish" section BY
        PROVIDER, so the union alone cannot be persisted without inventing an
        attribution. Entries are ``{"provider": str, "text": str}``, deduped on
        the PAIR (two streams reporting the same gap is two honest rows, not a
        duplicate) and capped by the same ``_NOT_FOUND_TOTAL_MAX``, loudly.
    """

    claims: list[dict] = field(default_factory=list)
    reports: list[tuple[str, dict]] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    records: list[ProviderFactsRecord] = field(default_factory=list)
    fallback_notes: list[str] = field(default_factory=list)
    #: ADDITIVE (15.2-15). Appended last so every positional construction of this
    #: dataclass that predates it stays valid.
    not_found_by_provider: list[dict] = field(default_factory=list)


def _normalise_fact_claim(
    claim: dict, *, provider: str, facet: str, fact_source: str
) -> dict | None:
    """One claim -> the single key set, whichever path produced it. NEVER RAISES.

    Returns ``None`` for a claim with no usable text, so the caller can count the
    loss rather than ship an empty claim.

    On the ``distiller_fallback`` branch the four D-13 / Pitfall-10 fields are
    written as ``None`` UNCONDITIONALLY, in Python, and are never read from model
    output. THIS IS A SECURITY CONTROL, NOT A DEFAULT (T-15.2-61): provider prose
    embeds web pages the provider chose to ingest, so a page saying
    "certainty: certain, provider_quality: official" is an indirect prompt
    injection aimed straight at a persisted, queryable D-13 column. A model must
    not be able to state its own confidence. The distiller was never asked for
    those fields, so there is nothing legitimate to lose by hard-writing them.

    On the ``fact_list`` branch the values come from 15.2-04's parser, which has
    already clamped them to ``CERTAINTY_VALUES`` / ``QUALITY_VALUES``.
    """
    if not isinstance(claim, dict):
        return None
    try:
        text = str(claim.get("text") or "").strip()
        if not text:
            return None

        found_by = claim.get("found_by")
        if not isinstance(found_by, list) or not found_by:
            found_by = [provider] if provider else []
        else:
            found_by = [str(p) for p in found_by if p]

        source_urls = claim.get("source_urls")
        if not isinstance(source_urls, list):
            source_urls = []

        out: dict = {
            "text": text,
            "facet": str(claim.get("facet") or facet or "general"),
            "evidence": str(claim.get("evidence") or ""),
            "found_by": found_by,
            "source_urls": source_urls,
        }
        if fact_source == "distiller_fallback":
            # Written here, in Python. See the docstring — T-15.2-61.
            out["certainty"] = None
            out["provider_quality"] = None
            out["source_domain"] = None
            out["quality_tier_hint"] = None
        else:
            out["certainty"] = claim.get("certainty")
            out["provider_quality"] = claim.get("provider_quality")
            out["source_domain"] = claim.get("source_domain")
            out["quality_tier_hint"] = claim.get("quality_tier_hint")
        # One key set for both paths, guaranteed rather than assumed: 15.2-15's
        # merge and persistence loop read these by name and a missing key there
        # would be a KeyError inside a paid run.
        for key in _FACT_CLAIM_KEYS:
            out.setdefault(key, None)
        out["fact_source"] = fact_source
        return out
    except Exception:  # noqa: BLE001 — one malformed claim costs that claim only
        log.debug("collect_provider_facts: unusable claim discarded")
        return None


def _fallback_note(provider: str, *, prompted: bool, k: int, m: int, c: int) -> str:
    """The plain-words, per-provider fallback sentence an operator reads.

    Built ONLY from the provider name and integers — never from report text or
    model output (T-15.2-66). These sentences render in the superadmin UI, so any
    model-controlled substring here would be an injection surface aimed at a human.

    Two wordings, because "did not comply" and "was never asked" are different
    facts about the run and telling an operator the wrong one is a false fault
    report. Both clear the >40-character plain-words bar for every input.

    NOTE for the verification report: this is a STREAM-level note. It is
    deliberately NOT bucket-3 wording — `verification/report.py` DERIVES the
    bucket-3 sentence at read time (15.2-08), and a second wording of the same
    shortfall would double-report it.
    """
    who = provider or "this provider"
    if prompted:
        opening = (
            f"{who} returned no usable fact list for {k} of {m} research report(s)"
        )
    else:
        opening = (
            f"{who} was not asked for a machine-readable fact list, so {k} of {m} "
            f"research report(s) had none"
        )
    return (
        f"{opening} — its prose was run through the full-extraction distiller "
        f"instead ({c} claims), so those claims carry no provider-stated certainty "
        f"or source quality and the domain heuristic fills the tier (D-14). The "
        f"research still reached the merge; nothing was dropped."
    )


async def collect_provider_facts(
    *,
    provider_reports: list,
    mission_brief: dict,
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    feed: Any = None,
) -> ProviderFactsResult:
    """Provider reports -> claims, D8 first, with the D-14 fallback per report.

    THE RULE, once: a report that carried a usable machine-readable fact list is
    read with 15.2-04's parser and is NEVER passed to the distiller. A report that
    did not is added to ONE full-extraction distillation covering all such reports.
    A stream is never dropped and a research call is NEVER re-issued — a corrective
    deep-research call is among the most expensive calls in the run, and on Gemini
    it is a full re-run (D-14's two rejected alternatives).

    Both rejected alternatives and the no-double-spend property are pinned by
    ``tests/test_factlist_fallback.py``.
    """
    reports_out: list[tuple[str, dict]] = []
    records_by_provider: "dict[str, dict]" = {}
    d8_claims: list[dict] = []
    fallback_units: list[tuple[str, dict]] = []
    not_found_raw: list[str] = []
    #: The SAME couldn't-find lines with the provider kept — see
    #: ``ProviderFactsResult.not_found_by_provider``. Filled from the same
    #: ``parsed.not_found`` in the same place, so the two views cannot drift.
    not_found_pairs_raw: list[tuple[str, str]] = []
    unusable_claims = 0

    entries = list(provider_reports or [])

    def _unpack(entry: Any) -> "tuple[str, dict]":
        """Tolerant (name, result) unpack — hostile input must not raise."""
        try:
            name, result = entry
        except Exception:  # noqa: BLE001 — a malformed entry is not a run-killer
            return "", {}
        return str(name or ""), (result if isinstance(result, dict) else {})

    has_material = False
    for entry in entries:
        _n, result = _unpack(entry)
        if (result.get("report") or ""):
            has_material = True
            break
        facts_val = result.get("facts")
        if isinstance(facts_val, list) and facts_val:
            # A forced-tool stream can deliver facts with no prose at all.
            has_material = True
            break

    if not has_material:
        log.info(
            "collect_provider_facts: no provider material to read (%d entr(y/ies)) "
            "— returning an empty result, no LLM call made",
            len(entries),
        )
        return ProviderFactsResult(reports=[(n, r) for n, r in (_unpack(e) for e in entries)])

    # NOTE: focus-area labels and the run language are NOT resolved here. The only
    # consumer of either is `claim_distiller`, which derives both from
    # `mission_brief` itself — resolving them a second time would be two sources
    # for one value and the first thing to drift.

    # Function-local, mirroring `pipeline.py`'s `strip_unresolved_cite_markers`
    # import: this module gains NO module-scope dependency on pipeline.tribunal.
    from nestor_pulse_sdk.pipeline.tribunal.facts import (  # noqa: PLC0415
        build_label_index,
        parse_fact_list,
        strip_fact_block,
    )

    def _rec(name: str) -> dict:
        return records_by_provider.setdefault(name, {
            "provider": name,
            "reports_seen": 0,
            "reports_with_fact_list": 0,
            "reports_fell_back": 0,
            "facts_from_list": 0,
            "claims_from_fallback": 0,
            "parse_errors": 0,
            "rejected_urls": 0,
            "dropped_over_cap": 0,
            "prompted": False,
            "reason": None,
        })

    for entry in entries:
        name, result = _unpack(entry)
        rec = _rec(name)
        rec["reports_seen"] += 1

        report_text = ""
        stripped = ""
        try:
            # `name` and `facet` are CALLER-SUPPLIED and are never read out of
            # report text — the rule `_parse_distiller_response` states above.
            # A model must not be able to set its own attribution (T-15.2-60).
            facet = str(result.get("_angle") or "") or "general"
            report_text = result.get("report") or ""
            if not isinstance(report_text, str):
                report_text = ""
            if bool(result.get("_d8_prompted")):
                rec["prompted"] = True

            # ALWAYS strip, including on the fallback path: a partial or dangling
            # block must never reach synthesis, scrub_research or the extractors.
            stripped = strip_fact_block(report_text)

            # --- The forced-tool hand-off (15.2-12 / 15.2-15) ------------------
            # The own-researcher emits its facts through a forced `emit_fact_list`
            # client tool, so they arrive ALREADY PARSED on the result dict. Using
            # them verbatim and never distilling this stream is the whole point:
            # re-distilling a stream that already emitted structured facts is a
            # pure double spend for a strictly worse result.
            # TO BE CONFIRMED ON MERGE by 15.2-12 / 15.2-15 — see the SUMMARY.
            pre_parsed = result.get("facts")
            if isinstance(pre_parsed, list) and pre_parsed and all(
                isinstance(f, dict) for f in pre_parsed
            ):
                kept = 0
                for raw in pre_parsed:
                    norm = _normalise_fact_claim(
                        raw, provider=name, facet=facet, fact_source="fact_list"
                    )
                    if norm is None:
                        unusable_claims += 1
                        continue
                    d8_claims.append(norm)
                    kept += 1
                rec["reports_with_fact_list"] += 1
                rec["facts_from_list"] += kept
                # THE COULDN'T-FIND LIST IS HARVESTED ON THIS BRANCH TOO.
                #
                # It was not, and the consequence was silent: the forced-tool
                # stream (the own-researcher, 15.2-12) `continue`d straight past
                # the `parse_fact_list` call below, so its `not_found` lines never
                # reached `not_found_by_provider`, never became `research_gap`
                # rows, and never appeared in D-08's "What we could not establish"
                # section. A stream that said out loud what it could not establish
                # was reported as having said nothing — which reads to the
                # operator as "this stream found everything it looked for".
                #
                # The SAME production parser is used rather than reading
                # `result["not_found"]` off the envelope: `parse_fact_list` owns
                # the bounds (`_MAX_NOT_FOUND`, `_MAX_NOT_FOUND_CHARS`) and the
                # region extraction, and a second reader of the same data is
                # exactly the fork this phase forbids. `render_report` writes the
                # block into `report`, so it round-trips. `parsed.facts` is
                # deliberately DISCARDED here — the pre-parsed facts above are
                # authoritative and re-adding them would double-count every fact.
                if report_text:
                    _nf = parse_fact_list(
                        report_text, provider=name, facet=facet,
                        label_index=build_label_index(report_text),
                    ).not_found
                    not_found_raw.extend(_nf)
                    not_found_pairs_raw.extend((name, item) for item in _nf)
                reports_out.append((name, {**result, "report": stripped}))
                continue

            if not report_text:
                # Nothing to parse and nothing to distil. Not a fallback: there is
                # no prose that could have carried a list.
                reports_out.append((name, {**result, "report": stripped}))
                continue

            label_index = build_label_index(report_text)
            parsed = parse_fact_list(
                report_text, provider=name, facet=facet, label_index=label_index
            )
            rec["parse_errors"] += parsed.parse_errors
            rec["rejected_urls"] += parsed.rejected_urls
            rec["dropped_over_cap"] += parsed.dropped_over_cap
            not_found_raw.extend(parsed.not_found)
            # Attribution kept for the research_gap write path (15.2-15). `name`
            # is caller-supplied, never read out of report text (T-15.2-60).
            not_found_pairs_raw.extend((name, item) for item in parsed.not_found)

            if not parsed.needs_distiller_fallback:
                rec["reports_with_fact_list"] += 1
                kept = 0
                for raw in parsed.facts:
                    norm = _normalise_fact_claim(
                        raw, provider=name, facet=facet, fact_source="fact_list"
                    )
                    if norm is None:
                        unusable_claims += 1
                        continue
                    d8_claims.append(norm)
                    kept += 1
                rec["facts_from_list"] += kept
            else:
                rec["reports_fell_back"] += 1
                if rec["reason"] is None:
                    # 15.2-04's own sentence, carried verbatim.
                    rec["reason"] = parsed.fallback_reason
                # The block is stripped BEFORE distillation too, so the distiller
                # never re-reads a half-parsed fact table as prose.
                fallback_units.append((name, {**result, "report": stripped}))
        except Exception as exc:  # noqa: BLE001 — one bad report degrades itself only
            log.warning(
                "collect_provider_facts: %s report could not be read as a fact "
                "list (%s) — it is passed through as prose",
                name or "a provider", type(exc).__name__,
            )
            stripped = stripped or report_text or ""

        reports_out.append((name, {**result, "report": stripped}))

    # --- The ONE fallback distillation, over ALL fallback reports at once -----
    # Skipping it entirely when there is nothing to distil IS the no-double-spend
    # assertion. One call keeps `claim_distiller`'s existing per-chunk parallelism
    # and its `_chunk_text` coverage guarantee — neither is re-implemented here.
    fallback_claims: list[dict] = []
    if fallback_units:
        raw_fallback = await claim_distiller(
            provider_reports=fallback_units,
            mission_brief=mission_brief,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
            full_extraction=True,
        )
        for raw in raw_fallback:
            # Attribution comes from `found_by`, which `claim_distiller` already
            # sets from the tuple name — never from the model's own output.
            attributed = ""
            fb = raw.get("found_by") if isinstance(raw, dict) else None
            if isinstance(fb, list) and fb:
                attributed = str(fb[0] or "")
            norm = _normalise_fact_claim(
                raw if isinstance(raw, dict) else {},
                provider=attributed,
                facet="general",
                fact_source="distiller_fallback",
            )
            if norm is None:
                unusable_claims += 1
                continue
            fallback_claims.append(norm)
            if attributed:
                _rec(attributed)["claims_from_fallback"] += 1

    # --- ONE dedupe, across ALL streams, D8 claims FIRST ----------------------
    # The order is deliberate. `_dedupe_claims` keeps the FIRST occurrence and
    # MERGES `found_by`, so putting provider-stated facts first means a fact the
    # provider itself asserted wins over a distilled paraphrase of the same fact,
    # while the corroboration signal (two streams naming the same fact) survives
    # in `found_by`. This is the SINGLE normaliser — no second deduper is written
    # here, and `_dedupe_claims` itself is not modified; 15.2-15's merge depends
    # on its current shape. Note also that the D6 corroboration COPIES — the same
    # sub-question deliberately sent to several providers — are exactly what this
    # merge is for; they are the signal, and nothing above removes them per-stream.
    claims = _dedupe_claims(d8_claims + fallback_claims)

    # --- not_found: order-preserving dedupe, then a LOUD cap ------------------
    seen_nf: set = set()
    not_found: list[str] = []
    for item in not_found_raw:
        key = str(item or "").strip()
        if not key or key in seen_nf:
            continue
        seen_nf.add(key)
        not_found.append(key)
    if len(not_found) > _NOT_FOUND_TOTAL_MAX:
        log.warning(
            "collect_provider_facts: %d distinct 'could not establish' entries "
            "exceed the %d cap — %d dropped (raise "
            "NESTOR_TRIBUNAL_NOT_FOUND_TOTAL_MAX to keep them all)",
            len(not_found), _NOT_FOUND_TOTAL_MAX,
            len(not_found) - _NOT_FOUND_TOTAL_MAX,
        )
        not_found = not_found[:_NOT_FOUND_TOTAL_MAX]

    # --- The same lines, attribution kept: (provider, text) pairs -------------
    # Deduped on the PAIR, not on the text: two streams independently reporting
    # that they could not establish the same thing is two honest research_gap
    # rows, and collapsing them would silently erase one provider's report of its
    # own limits. Capped by the same constant, and just as loudly.
    seen_pair: set = set()
    not_found_pairs: list[dict] = []
    for provider_name, item in not_found_pairs_raw:
        gap_text = str(item or "").strip()
        gap_provider = str(provider_name or "").strip()
        if not gap_text or not gap_provider:
            continue
        pair_key = (gap_provider, gap_text)
        if pair_key in seen_pair:
            continue
        seen_pair.add(pair_key)
        not_found_pairs.append({"provider": gap_provider, "text": gap_text})
    if len(not_found_pairs) > _NOT_FOUND_TOTAL_MAX:
        log.warning(
            "collect_provider_facts: %d attributed 'could not establish' entries "
            "exceed the %d cap — %d dropped before they could become research_gap "
            "rows (raise NESTOR_TRIBUNAL_NOT_FOUND_TOTAL_MAX to keep them all)",
            len(not_found_pairs), _NOT_FOUND_TOTAL_MAX,
            len(not_found_pairs) - _NOT_FOUND_TOTAL_MAX,
        )
        not_found_pairs = not_found_pairs[:_NOT_FOUND_TOTAL_MAX]

    # --- Per-provider records, plain-words notes, and one feed row each -------
    records: list[ProviderFactsRecord] = []
    fallback_notes: list[str] = []
    for name, rec in records_by_provider.items():
        records.append(ProviderFactsRecord(**rec))
        if rec["reports_fell_back"] > 0:
            note = _fallback_note(
                name,
                prompted=bool(rec["prompted"]),
                k=rec["reports_fell_back"],
                m=rec["reports_seen"],
                c=rec["claims_from_fallback"],
            )
            fallback_notes.append(note)
            log.warning("collect_provider_facts: %s", note)

    if feed is not None:
        for name, rec in records_by_provider.items():
            # Best-effort: a feed write must never break a paid run.
            try:
                if rec["reports_fell_back"] > 0:
                    row = (
                        f"{name or 'provider'}: no fact list — full distillation "
                        f"fallback ({rec['claims_from_fallback']} claims from "
                        f"{rec['reports_fell_back']} report(s))"
                    )
                    n_facts = rec["claims_from_fallback"]
                else:
                    row = (
                        f"{name or 'provider'}: {rec['facts_from_list']} fact(s) "
                        f"from its own fact list"
                    )
                    n_facts = rec["facts_from_list"]
                await feed.add(name=row, status="done", facts=int(n_facts))
            except Exception as exc:  # noqa: BLE001 — feed rows are best-effort
                log.warning(
                    "collect_provider_facts: feed row for %s failed: %r", name, exc
                )

    log.info(
        "collect_provider_facts: %d provider(s), %d report(s) with a fact list, "
        "%d fell back to full distillation -> %d D8 fact(s) + %d fallback claim(s) "
        "= %d claim(s) after one dedupe (%d unusable discarded, %d 'could not "
        "establish' entries)",
        len(records_by_provider),
        sum(r["reports_with_fact_list"] for r in records_by_provider.values()),
        sum(r["reports_fell_back"] for r in records_by_provider.values()),
        len(d8_claims), len(fallback_claims), len(claims), unusable_claims,
        len(not_found),
    )

    return ProviderFactsResult(
        claims=claims,
        reports=reports_out,
        not_found=not_found,
        records=records,
        fallback_notes=fallback_notes,
        not_found_by_provider=not_found_pairs,
    )


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
