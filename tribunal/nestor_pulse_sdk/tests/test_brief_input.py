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

import logging
import uuid
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.pipeline.tribunal import brief_input
from nestor_pulse_sdk.pipeline.tribunal.brief_input import parse_brief
from nestor_pulse_sdk.pipeline.tribunal.intake import detect_explicit_questions
from nestor_pulse_sdk.runs import run_events

#: The emitter's own logger name, so a caplog assertion below names the exact
#: source of a swallowed exception rather than matching anything in the tree.
_EMITTER_LOG = "nestor_pulse_sdk.runs.run_events"


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


# ===========================================================================
# SECTION 6 (plan 15.3-05) — THE FEED'S FIRST LINES.
#
# `parse_brief` now also opens the run page's feed. Two separate things have to be
# proved and only one of them can be proved with a recorder:
#
#   * that CALLING the emitter is safe — a recorder that raises shows the parse
#     does not notice;
#   * that BUILDING the emitter's arguments is safe — which a recorder can NEVER
#     show, because by the time any recorder runs the arguments already exist.
#
# The second is what `emit_safe`'s build() thunk exists for, and the tests marked
# (a2) below are the only ones that touch it. They monkeypatch NOTHING on
# `run_events` and drive genuinely malformed input through the real call site.
# ===========================================================================


class _EventRecorder:
    """Duck-typed to `run_events.emit`. Records the rows; optionally raises.

    A stand-in for the QUEUE APPEND only. Everything between a call site and this
    object — the thunk, `emit_safe`'s try, the 2-tuple check — is production code
    doing its real job.
    """

    def __init__(self, raises: Optional[BaseException] = None) -> None:
        self.events: list[dict[str, Any]] = []
        self._raises = raises

    def __call__(self, run_id, *, stage, kind, text, meta=None):
        self.events.append(
            {"run_id": run_id, "stage": stage, "kind": kind, "text": text, "meta": meta}
        )
        if self._raises is not None:
            raise self._raises

    def of_kind(self, kind: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["kind"] == kind]

    @property
    def texts(self) -> list[str]:
        return [str(event["text"]) for event in self.events]


_DECISION = "Duitsland lanceren in 2027, of eerst NL consolideren"


# ---------------------------------------------------------------------------
# (a) / (b) — what the opening line says, and what it says when there is nothing
#             to say.
# ---------------------------------------------------------------------------


def test_a_stated_decision_reaches_the_feed_as_a_thinking_line(monkeypatch):
    """(a) The feed opens with what the engine understood the brief to be."""
    recorder = _EventRecorder()
    monkeypatch.setattr(run_events, "emit", recorder)

    parse_brief(_live_brief(decision_block=_DECISION), run_id=uuid.uuid4())

    thinking = recorder.of_kind("thinking")
    assert len(thinking) == 1, recorder.events
    assert _DECISION in thinking[0]["text"]
    assert "11 client question(s)" in thinking[0]["text"]
    assert thinking[0]["stage"] == "intake", "the intake block, not an invented stage"

    # The block is a header, a parse step and a stats line — the design's shape.
    assert len(recorder.of_kind("tool")) == 1
    summary = recorder.of_kind("summary")
    assert len(summary) == 1
    assert summary[0]["meta"]["actions"] == 11, "questions found"
    assert summary[0]["meta"]["items"] > 0, "context lines kept"


def test_without_a_run_id_the_parser_emits_nothing_at_all(monkeypatch):
    """The `run_id` default keeps every existing caller byte-for-byte unchanged."""
    recorder = _EventRecorder()
    monkeypatch.setattr(run_events, "emit", recorder)

    parse_brief(_live_brief(decision_block=_DECISION))

    assert recorder.events == []


def test_a_brief_with_no_stated_decision_says_so_in_words(monkeypatch):
    """(b) The ABSENCE of a decision is information, not an empty half-sentence.

    On run d6bb3aae the brief stated no decision, the tournament judge was handed
    the project TITLE to rank materiality against, and report metadata out-ranked
    the client's real questions (D-H). A blank after the comma would render that
    as though nothing were missing.
    """
    recorder = _EventRecorder()
    monkeypatch.setattr(run_events, "emit", recorder)

    parse_brief(_live_brief(), run_id=uuid.uuid4())

    thinking = recorder.of_kind("thinking")[0]["text"]
    assert brief_input._NO_DECISION_TEXT in thinking
    assert not thinking.rstrip().endswith((",", "—", "-", ":")), (
        f"the line trails off into an empty fragment: {thinking!r}"
    )

    # NON-VACUOUS: the same brief WITH a decision must not claim there is none.
    other = _EventRecorder()
    monkeypatch.setattr(run_events, "emit", other)
    parse_brief(_live_brief(decision_block=_DECISION), run_id=uuid.uuid4())
    assert brief_input._NO_DECISION_TEXT not in other.of_kind("thinking")[0]["text"]


# ---------------------------------------------------------------------------
# (c) — D-G through a NEW channel. T-15.3-40.
# ---------------------------------------------------------------------------


def test_no_stakeholder_line_reaches_an_event(monkeypatch):
    """(c) The four offenders stay out of the feed, by construction.

    `- **Primair contact klant:** MEEMZ (mohamed.ajimi@azentic.be)` is a §9 line of
    the same context pack whose bullets became 21 workshop parents on d6bb3aae, and
    it carried a real personal address to two paid third-party providers. A feed row
    is a NEW egress for it, so D-G has to hold here too. `scrub_pii` at the emitter
    is the second layer; not putting the line in the text is the first.
    """
    recorder = _EventRecorder()
    monkeypatch.setattr(run_events, "emit", recorder)

    parse_brief(_live_brief(decision_block=_DECISION), run_id=uuid.uuid4())

    joined = " || ".join(recorder.texts)
    for forbidden in (
        "mohamed.ajimi",
        "@",
        "MEEMZ",
        "Primair contact",
        "Decision-maker",
        "NDA-status",
        "Output-omvang",
    ):
        assert forbidden not in joined, (
            f"{forbidden!r} reached a persisted, operator-visible event row"
        )

    # NON-VACUOUS: an implementation that emitted NOTHING would pass every
    # assertion above. The decision is what these rows are FOR.
    assert _DECISION in joined
    assert len(recorder.events) == 3


# ---------------------------------------------------------------------------
# (a2) — THE ARGUMENT-CONSTRUCTION PROOF. Nothing on `run_events` is patched.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "brief",
    [
        "",
        None,
        "   \n\n\t  \n",
        "Onderzoeksvragen:",
        "[DECISION]",
        "[DECISION]\n[END DECISION]",
        "\x00\x01 binary-ish ﻿ bytes \n Onderzoeksvragen:\n1. Een vraag over de markt",
        "Onderzoeksvragen:\r\n1. Een vraag met CRLF regeleinden over de markt\r\n",
    ],
)
def test_events_never_change_what_parse_brief_returns(brief):
    """(a2) The REAL emitter, on the shapes most likely to break a line's text.

    `ParsedBrief` is frozen, so this is a field-by-field equality: the parse with a
    run id must be indistinguishable from the parse without one.
    """
    assert parse_brief(brief, run_id=uuid.uuid4()) == parse_brief(brief)


def test_the_events_really_are_emitted_so_the_equality_above_is_not_vacuous(caplog):
    """A parse that never reached the emitter would pass every (a2) assertion.

    The run is never opened here, so `emit` DROPS its rows and says so once — which
    is exactly the proof that the call was made rather than skipped.
    """
    with caplog.at_level(logging.WARNING, logger=_EMITTER_LOG):
        parse_brief(_live_brief(), run_id=uuid.uuid4())

    assert "was never opened" in caplog.text


def test_a_parse_result_with_none_of_the_keys_the_lines_read_costs_only_the_lines(
    caplog,
):
    """(a2) THE SHARPEST CASE IN THIS FILE.

    `parse_brief` is DOCUMENTED as never raising, and `pipeline.py` relies on that
    in writing: it sits OUTSIDE the checkpoint branch because it is pure, free and
    safe. An event whose text was composed in the argument list would revoke that
    guarantee for every brief that fails to carry what the line reads — and a pure
    function that starts raising outside a checkpoint branch is a run that dies
    before it starts.

    Nothing here is monkeypatched. The object handed in has NONE of the attributes
    the three lines read.
    """
    naked = object()

    # NEGATIVE CONTROL FIRST. Without it this test would pass just as happily
    # against an implementation whose thunks never touched the result at all.
    with pytest.raises(AttributeError):
        len(naked.questions)  # type: ignore[attr-defined]

    with caplog.at_level(logging.WARNING, logger=_EMITTER_LOG):
        assert brief_input._emit_parse_events(uuid.uuid4(), naked) is None

    assert caplog.text.count("AttributeError") >= 3, (
        "all three lines must have REACHED the fragile construction and been "
        f"swallowed by the emitter; got: {caplog.text}"
    )


def test_the_parser_still_works_after_an_event_could_not_be_built():
    """A run whose feed lines fail is DEGRADED. It is not a failed run."""
    run_id = uuid.uuid4()

    brief_input._emit_parse_events(run_id, object())

    parsed = parse_brief(_live_brief(decision_block=_DECISION), run_id=run_id)
    assert parsed.questions == _CLIENT_QUESTIONS
    assert parsed.decision == _DECISION
    assert parsed.source == "structured"


# ---------------------------------------------------------------------------
# The [REPORT] block — consumer half of quick task 260806-lvt.
#
# WHY. On run 368ff3a0 `mission_brief["language"]` was EMPTY on every dispatch
# call, measured by reading `request.query` out of the audit blobs: all five
# assignments carried "Report all findings in the language of the assignment
# above.", the branch that fires only when the value is empty. Nothing was wrong
# with the consumers — nobody was producing the value. These pin the reader.
# ---------------------------------------------------------------------------


def _brief_with_report_block(body: str) -> str:
    """A minimal seam-shaped brief carrying `body` as its [REPORT] block."""
    return (
        "Deep research for lukoil.\n"
        "\n"
        "Onderzoeksvragen:\n"
        "1. Welke fuel retailers passen dynamic pricing toe?\n"
        "\n"
        "[DECISION]\n"
        "Investeert LUKOIL in Duitsland of in margegroei in de Benelux?\n"
        "[END DECISION]\n"
        "\n"
        "[REPORT]\n"
        f"{body}\n"
        "[END REPORT]\n"
        "\n"
        "[CONTEXT PACK]\n"
        "- Sector: fuel retail\n"
    )


def test_report_block_yields_language_and_spec():
    parsed = parse_brief(
        _brief_with_report_block(
            "LANGUAGE: Dutch\nLENGTH: comprehensive\nPAGES: 10-20"
        )
    )

    assert parsed.language == "Dutch"
    assert parsed.report_spec == {"length": "comprehensive", "pages": "10-20"}
    # The block must not damage what already worked.
    assert parsed.questions == ["Welke fuel retailers passen dynamic pricing toe?"]
    assert parsed.decision.startswith("Investeert LUKOIL")
    assert parsed.source == "structured"


def test_report_block_lines_never_leak_into_context():
    """Context is read by the workshop. A delimiter pair the producer owns must not
    become material the workshop reads as if the client had written it — that class
    of leak is exactly what fed 32 parents into the d6bb3aae workshop."""
    parsed = parse_brief(
        _brief_with_report_block("LANGUAGE: French\nPAGES: 5-10")
    )

    assert "[REPORT]" not in parsed.context
    assert "[END REPORT]" not in parsed.context
    assert "LANGUAGE:" not in parsed.context
    assert "PAGES:" not in parsed.context
    # The real context survives intact.
    assert "Sector: fuel retail" in parsed.context


def test_pages_only_block_is_the_standard_case():
    """`standard` carries a page target and NO length keyword, by operator ruling."""
    parsed = parse_brief(_brief_with_report_block("LANGUAGE: Dutch\nPAGES: 5-10"))
    assert parsed.report_spec == {"pages": "5-10"}
    assert "length" not in parsed.report_spec


def test_instructions_keep_their_own_colons():
    """Split on the FIRST colon only — client text legitimately contains more."""
    parsed = parse_brief(
        _brief_with_report_block("INSTRUCTIONS: Target: max. 15 slides voor ExCo")
    )
    assert parsed.report_spec == {"instructions": "Target: max. 15 slides voor ExCo"}


def test_a_malformed_block_costs_the_block_and_never_the_parse():
    """The load-bearing degradation property: questions and decision survive."""
    parsed = parse_brief(
        _brief_with_report_block("this is not a key value line at all\nWAT: onbekend")
    )

    assert parsed.report_spec == {}
    assert parsed.language == ""
    assert parsed.questions == ["Welke fuel retailers passen dynamic pricing toe?"]
    assert parsed.decision.startswith("Investeert LUKOIL")
    # And the junk did not become context either.
    assert "not a key value line" not in parsed.context


def test_an_unclosed_report_block_ends_at_the_next_section_marker():
    brief = (
        "Opening.\n"
        "\n"
        "[REPORT]\n"
        "LANGUAGE: English\n"
        "[CONTEXT PACK]\n"
        "- Sector: fuel retail\n"
    )
    parsed = parse_brief(brief)

    assert parsed.language == "English"
    assert "Sector: fuel retail" in parsed.context


def test_no_report_block_is_the_old_intake_path_and_stays_empty():
    """THE BACK-COMPAT ARM. An intake predating the field must yield empty, not a
    guess — pipeline.py's zero-touch branch passes report_spec=None for this shape."""
    brief = (
        "Deep research for lukoil.\n"
        "\n"
        "Onderzoeksvragen:\n"
        "1. Welke fuel retailers passen dynamic pricing toe?\n"
    )
    parsed = parse_brief(brief)

    assert parsed.language == ""
    assert parsed.report_spec == {}
    assert parsed.questions == ["Welke fuel retailers passen dynamic pricing toe?"]


def test_absent_language_is_reported_out_loud(caplog):
    """A fallback that fires 100% of the time is the behaviour, not a fallback.
    Silence is the entire reason this survived unnoticed on run 368ff3a0."""
    with caplog.at_level(logging.WARNING, logger=brief_input.log.name):
        parse_brief("Opening line only.\n")

    assert any(
        "no report LANGUAGE" in record.getMessage() for record in caplog.records
    ), "the empty-language path must name itself in the log"


def test_a_stated_language_logs_no_warning(caplog):
    """Non-vacuity for the test above: the warning must be conditional, not constant."""
    with caplog.at_level(logging.WARNING, logger=brief_input.log.name):
        parse_brief(_brief_with_report_block("LANGUAGE: Dutch"))

    assert not any(
        "no report LANGUAGE" in record.getMessage() for record in caplog.records
    )


def test_report_values_are_bounded():
    """`instructions` reaches a synthesis prompt verbatim — same class of input as a
    client question, so it carries the same kind of bound."""
    parsed = parse_brief(
        _brief_with_report_block("INSTRUCTIONS: " + ("x" * 900))
    )
    assert len(parsed.report_spec["instructions"]) == brief_input._REPORT_VALUE_MAX_CHARS


def test_the_seam_strings_match_the_producer():
    """SEAM GUARD. backend/app/research/brief.py spells the same two delimiters; if
    either side drifts the block silently becomes context and the language is lost
    again, with no error anywhere. Asserted against the producer's own source."""
    import pathlib
    import re

    producer = (
        pathlib.Path(__file__).resolve().parents[3]
        / "backend"
        / "app"
        / "research"
        / "brief.py"
    )
    if not producer.exists():  # engine-only checkout
        pytest.skip("backend/ not present in this checkout")

    text = producer.read_text(encoding="utf-8")
    for name, value in (
        ("_REPORT_HEADER", brief_input._REPORT_HEADER),
        ("_REPORT_FOOTER", brief_input._REPORT_FOOTER),
    ):
        assert re.search(rf'^{name} = "{re.escape(value)}"$', text, re.M), (
            f"the producer's {name} no longer equals the parser's {value!r} — "
            "this is a seam change and both sides move in one commit"
        )
