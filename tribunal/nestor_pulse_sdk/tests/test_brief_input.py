"""The D-G regression — a seam brief yields its client questions and NOTHING else.

THIS FILE MAKES ZERO LLM CALLS, opens no socket and touches no database. The module
under test (``pipeline.tribunal.brief_input``) is a pure transform, so every test
here is a real end-to-end test of it: nothing is stubbed and nothing can flake.

THE FIXTURE IS TRANSCRIBED, NOT INVENTED. ``_live_brief()`` below reproduces the
brief shape that run ``d6bb3aae`` (2026-07-27) actually carried:

  * the opening line and the ``Onderzoeksvragen:`` header come from
    ``backend/app/research/brief.py::assemble_brief``;
  * the eleven enumerated questions are the client's real questions as recorded in
    ``docs/tribunal-run-reports/run-20260727-d6bb3aae-WORKSHOP-FORENSICS.md`` §4 and
    §3 (translated back to their Dutch register where the forensics translated them);
  * the context-pack bullets are the §3 / §9 / §10 lines of
    ``backend/app/ai/prompts.py::CONTEXT_PACK_SKILL_PROMPT``, including the four
    offenders the forensics names by hand — ``Output-omvang (harde constraint)``,
    ``NDA-status``, ``Decision-maker`` and ``Primair contact klant`` (which carried a
    real personal email address to two paid third-party research providers).

WHAT IT PROVES. On that exact input the workshop was handed **32** parents and
generated six paid research sub-questions for "Output size (hard constraint):
Standard (15-25 pages)". ``parse_brief`` must yield **11** — the client's questions,
and not one context-pack line. Test 1 additionally runs the OLD detector over the
same string and asserts it still finds the offenders, so the regression is
demonstrated rather than merely asserted: the two functions disagree, and the
disagreement is the fix.

Cloud Build gate (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import pytest

from nestor_pulse_sdk.pipeline.tribunal.brief_input import parse_brief
from nestor_pulse_sdk.pipeline.tribunal.intake import detect_explicit_questions


# The client's eleven real research questions (forensics §3 + §4). None of these
# contains an "@", a report-format constraint or a stakeholder name — which is
# exactly what Test 1 asserts about the parse.
_CLIENT_QUESTIONS = [
    "Welke brandstofretailers in Europa passen vandaag dynamic pricing toe op "
    "brandstof en/of shopproducten, en hoe wordt dat operationeel gemaakt?",
    "Hoe zijn de koffiestrategieen van de belangrijkste BeNeLux-tankstationketens "
    "geevolueerd, en welke impact had dat op koffieverkoop, traffic en merkbeleving "
    "de afgelopen 3 jaar?",
    "Nu het concurrentievoordeel van een supermarktformule aan tankstations "
    "afkalft door ruimere winkelopeningsuren, hoe reageren brandstofretailers "
    "elders strategisch?",
    "Welk migratierisico loopt de bestaande klantenloyaliteit bij een "
    "premiumisering van het shopaanbod?",
    "Welke strategieen voeren Shell, TotalEnergies en BP op shop- en "
    "foodservice-vlak in de BeNeLux?",
    "Welke concrete exit-scenarios zijn realistisch uitvoerbaar als een Duitse "
    "uitrol niet aanslaat?",
    "In welke concrete stappen eroderen brandstofvolume en klantfrequentie bij een "
    "middelgrote brandstofretailer zonder loyalty- of differentiatie-antwoord?",
    "Wat zijn de exacte wettelijke openingsuurregels voor tankstations en "
    "aangehechte gemakswinkels in NL, BE, LU en DE?",
    "Welke regelgeving rond prijstransparantie geldt in de BeNeLux versus "
    "Duitsland?",
    "Hoe groot is de markt voor foodservice op tankstations in de BeNeLux, en hoe "
    "snel groeit die?",
    "Welke rol speelt laadinfrastructuur in de winkelomzet van een tankstation?",
]

# The four offenders the forensics names, verbatim in the producer's own bullet
# shape. Each of these was deepened into paid research sub-questions on d6bb3aae.
_OFFENDER_OUTPUT_SIZE = (
    "- **Output-omvang (harde constraint):** Standaard (15-25 p.)"
)
_OFFENDER_NDA = "- **NDA-status:** intake zegt 'dont know' over gevoeligheden"
_OFFENDER_DECISION_MAKER = (
    "- **Decision-maker:** MOE, CEO + senior leadership. Of MEEMZ beslist of "
    "afstemt is onduidelijk."
)
_OFFENDER_CONTACT = (
    "- **Primair contact klant:** MEEMZ (mohamed.ajimi@azentic.be) — rol nog in "
    "te vullen"
)

_CONTEXT_PACK = "\n".join(
    [
        "# Context Pack — LUKOIL BeNeLux",
        "",
        "## 3. De beslissing die eraan hangt",
        "- **Wat moet beslist worden:** Duitsland lanceren in 2027, of eerst NL "
        "consolideren",
        "- **Door wie:** MOE (CEO) + senior leadership",
        "- **Tegen wanneer:** juni 2026 — zodat de planning voor 2027 kan starten",
        "- **Alternatieven op tafel:** A) Duitsland 2027 / B) NL verdiepen / C) "
        "beide / D) status quo",
        "- **Kost van niets veranderen:** als LUKOIL niet differentieert en "
        "concurrenten wel",
        "",
        "## 5. Scope & segmentatie",
        "- **In scope:** BeNeLux, Duitsland",
        "- **Out of scope:** Frankrijk, Scandinavie",
        "",
        "## 9. Stakeholders & gevoeligheden",
        _OFFENDER_CONTACT,
        _OFFENDER_DECISION_MAKER,
        _OFFENDER_NDA,
        "- **Politieke/commerciele gevoeligheden:** interne dynamiek rond de "
        "franchisenemers",
        "",
        "## 10. Taalregister & output-eisen",
        "- **Hoe praat de klant:** zakelijk, weinig jargon",
        _OFFENDER_OUTPUT_SIZE,
        "- **Output-vorm:** PDF",
        "- **Specifieke eisen klant:** geen aan-de-ene-kant-aan-de-andere-kant taal",
    ]
)

_HINT = "Structureer het rapport per marktsegment / sector. Gewenste lengte: uitgebreid."


def _live_brief(*, decision_block: str | None = None) -> str:
    """The exact live brief shape `assemble_brief` produces (optionally with [DECISION])."""
    parts = ["Deep research for moetest.", "", "Onderzoeksvragen:"]
    parts += [f"{i}. {q}" for i, q in enumerate(_CLIENT_QUESTIONS, start=1)]
    if decision_block is not None:
        parts += ["", "[DECISION]", decision_block, "[END DECISION]"]
    parts += ["", _HINT, "", "[CONTEXT PACK]", _CONTEXT_PACK]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Test 1 — THE D-G REGRESSION.
# ---------------------------------------------------------------------------


def test_the_32_parent_brief_yields_exactly_its_eleven_client_questions():
    """The recorded d6bb3aae brief shape yields 11 questions and zero pack lines."""
    brief = _live_brief()

    parsed = parse_brief(brief)

    assert parsed.source == "structured"
    assert len(parsed.questions) == 11, (
        "the client enumerated 11 research questions; anything else means a "
        "context-pack line was counted as a question again (D-G)"
    )
    assert parsed.questions == _CLIENT_QUESTIONS

    joined = " || ".join(parsed.questions)
    for forbidden in ("Output-omvang", "NDA-status", "Decision-maker", "@"):
        assert forbidden not in joined, (
            f"{forbidden!r} reached the question list — that is the D-G defect, and "
            f"on the live run it bought paid third-party research"
        )


def test_the_old_detector_still_finds_the_offenders_on_the_same_string():
    """The regression is a DISAGREEMENT, not an assertion — pin both sides of it.

    `detect_explicit_questions` is not broken and is not being changed: it is the
    correct fallback for a FREE-PROSE brief and stays in use for exactly that. What
    was wrong was calling it on a brief that already had a question block. This test
    records what it does to that brief, so nobody "fixes" D-G by widening
    `_ENUM_ITEM_RE` and quietly reintroducing it.
    """
    brief = _live_brief()

    detected = detect_explicit_questions(brief)
    detected_joined = " || ".join(detected)

    assert len(detected) > len(parse_brief(brief).questions)
    assert "Output-omvang" in detected_joined
    assert "NDA-status" in detected_joined
    assert "Decision-maker" in detected_joined


# ---------------------------------------------------------------------------
# Test 2 — the pack is RECLASSIFIED, never dropped.
# ---------------------------------------------------------------------------


def test_the_context_pack_survives_verbatim_as_context():
    """The pack still reaches the engine in full — as context, which is its name."""
    parsed = parse_brief(_live_brief())

    assert _CONTEXT_PACK in parsed.context, (
        "the context pack must be reclassified, not dropped — the workshop is "
        "supposed to READ the client's context"
    )
    assert "[CONTEXT PACK]" in parsed.context
    assert _HINT in parsed.context
    assert "Deep research for moetest." in parsed.context
    # And the pack's own bullets are context, never questions.
    assert _OFFENDER_OUTPUT_SIZE in parsed.context
    assert _OFFENDER_CONTACT in parsed.context


# ---------------------------------------------------------------------------
# Test 3 — the [DECISION] block.
# ---------------------------------------------------------------------------


def test_decision_block_is_extracted_stripped_bounded_and_never_a_question():
    """`[DECISION]` … `[END DECISION]` becomes `.decision` and nothing else."""
    statement = "Duitsland lanceren in 2027, of eerst NL consolideren"
    parsed = parse_brief(_live_brief(decision_block=f"   {statement}   "))

    assert parsed.decision == statement
    assert len(parsed.questions) == 11
    assert statement not in " || ".join(parsed.questions)
    assert "[DECISION]" not in parsed.context
    assert "[END DECISION]" not in parsed.context


def test_decision_block_is_bounded_and_whitespace_collapsed():
    """A long, ragged decision is clamped so the gate clamp never cuts mid-sentence."""
    long_statement = "\n   ".join(["Een heel lange beslissing over Duitsland"] * 40)
    parsed = parse_brief(_live_brief(decision_block=long_statement))

    assert parsed.decision
    assert len(parsed.decision) <= 400
    assert "\n" not in parsed.decision
    assert "  " not in parsed.decision


def test_an_unclosed_decision_block_ends_at_the_next_section():
    """A hand-written brief without [END DECISION] does not swallow the rest."""
    brief = "\n".join(
        [
            "Opening line.",
            "",
            "[DECISION]",
            "Duitsland lanceren in 2027, of eerst NL consolideren",
            "",
            "Onderzoeksvragen:",
            "1. Welke retailers passen dynamic pricing toe in Europa vandaag?",
            "2. Hoe evolueerden de koffiestrategieen in de BeNeLux sinds 2023?",
            "",
            "[CONTEXT PACK]",
            _OFFENDER_NDA,
        ]
    )

    parsed = parse_brief(brief)

    assert parsed.decision == "Duitsland lanceren in 2027, of eerst NL consolideren"
    assert len(parsed.questions) == 2
    assert "NDA-status" in parsed.context


# ---------------------------------------------------------------------------
# Test 4 — free prose is a legitimate brief shape, taken deliberately.
# ---------------------------------------------------------------------------


def test_a_brief_with_no_question_header_is_unstructured():
    """No header -> no questions and `source == "unstructured"` (the legacy path)."""
    brief = (
        "We want to understand how European fuel retailers are responding to the "
        "erosion of the supermarket format at filling stations. What is changing, "
        "and how fast?\n"
        "- Some bullet the old detector would have taken as a question\n"
    )

    parsed = parse_brief(brief)

    assert parsed.questions == []
    assert parsed.source == "unstructured"
    assert parsed.context == brief.rstrip("\n")
    assert parsed.decision == ""


def test_the_explicit_research_questions_marker_is_recognised():
    """The forward-looking `[RESEARCH QUESTIONS]` delimiter parses too."""
    brief = "\n".join(
        [
            "Opening line.",
            "[RESEARCH QUESTIONS]",
            "1. Welke retailers passen dynamic pricing toe in Europa vandaag?",
            "2) Hoe evolueerden de koffiestrategieen in de BeNeLux sinds 2023?",
            "[END RESEARCH QUESTIONS]",
            "[CONTEXT PACK]",
            _OFFENDER_OUTPUT_SIZE,
        ]
    )

    parsed = parse_brief(brief)

    assert parsed.source == "structured"
    assert len(parsed.questions) == 2
    assert parsed.questions[0].startswith("Welke retailers")
    assert parsed.questions[1].startswith("Hoe evolueerden")
    assert "Output-omvang" in parsed.context


def test_a_duplicated_question_does_not_become_two_parents():
    """The forensics counted "31 deepen calls + 1 duplicate" — dedupe like the detector."""
    question = "Welke retailers passen dynamic pricing toe op brandstof in Europa?"
    brief = "\n".join(
        [
            "Opening line.",
            "Onderzoeksvragen:",
            f"1. {question}",
            f"2. {question}",
            "3. Hoe evolueerden de koffiestrategieen in de BeNeLux sinds 2023?",
        ]
    )

    parsed = parse_brief(brief)

    assert len(parsed.questions) == 2


# ---------------------------------------------------------------------------
# Test 5 — pathological input never raises and never loses the brief.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "",
        None,
        "   \n\n\t  \n",
        "Onderzoeksvragen:",
        "Onderzoeksvragen:\n\n\n",
        "[RESEARCH QUESTIONS]\n[END RESEARCH QUESTIONS]",
        "[DECISION]",
        "[DECISION]\n[END DECISION]",
        "[END DECISION]\n[CONTEXT PACK]\nstray",
        "Onderzoeksvragen:\n1. Een vraag die tot het einde van het bestand loopt zonder pack",
        "Onderzoeksvragen:\n1.\n2.   \n3. Een echte vraag over de markt in de BeNeLux",
        "Onderzoeksvragen:\n99. Een vraag\n100. Nog een vraag zonder geldige nummering",
        "\x00\x01 binary-ish ﻿ bytes \n Onderzoeksvragen:\n1. Een vraag over de markt",
        "Onderzoeksvragen:\r\n1. Een vraag met CRLF regeleinden over de BeNeLux-markt\r\n",
    ],
)
def test_pathological_input_never_raises(hostile):
    """Every shape below returns a ParsedBrief. None of them raises."""
    parsed = parse_brief(hostile)

    assert isinstance(parsed.questions, list)
    assert isinstance(parsed.decision, str)
    assert isinstance(parsed.context, str)
    assert parsed.source in {"structured", "unstructured", "error"}
    assert all(isinstance(q, str) and q.strip() for q in parsed.questions)


def test_a_very_large_brief_is_parsed_without_loss():
    """200 KB of context does not raise, does not truncate the question list."""
    filler = "\n".join(
        f"- **Veld {i}:** een lange contextregel met veel tekst erin herhaald"
        for i in range(3400)
    )
    brief = "\n".join(
        [
            "Opening line.",
            "Onderzoeksvragen:",
            "1. Welke retailers passen dynamic pricing toe in Europa vandaag?",
            "2. Hoe evolueerden de koffiestrategieen in de BeNeLux sinds 2023?",
            "",
            "[CONTEXT PACK]",
            filler,
        ]
    )
    assert len(brief) > 200_000

    parsed = parse_brief(brief)

    assert parsed.source == "structured"
    assert len(parsed.questions) == 2
    assert filler in parsed.context


def test_a_question_longer_than_the_bound_is_clamped_not_dropped():
    """A runaway question is bounded, never silently discarded."""
    long_question = "Welke retailers " + ("x" * 2000) + "?"
    brief = f"Onderzoeksvragen:\n1. {long_question}"

    parsed = parse_brief(brief)

    assert len(parsed.questions) == 1
    assert len(parsed.questions[0]) == 400
    assert parsed.questions[0].startswith("Welke retailers ")
