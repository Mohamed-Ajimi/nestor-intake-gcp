"""Brief-composition proofs (SEAM-04 / T-16-04) — the pause-gate avoidance guard.

The assembled brief drives Tribunal's two pause gates. A stray
``[INTERACTIVE_REPORT]`` marker opts the run into interactive report shaping
(``needs_report_spec``); a vague brief with no enumerated questions risks the
composition pause gate. This suite pins BOTH failure modes shut at the
composition layer (D-01/D-01b), so the poll driver never has to recover from a
parked run.

What this pins:

- ``assemble_brief`` enumerates every research question (priority order) under an
  "Onderzoeksvragen:" header and starts with the decomposition summary (or a
  deterministic fallback line) — the brief is never vague (T-16-04).
- The assembled brief NEVER contains the substring ``[INTERACTIVE_REPORT]`` — the
  seam run can never opt into the interactive-report pause gate (D-01b).
- ``derive_report_hint`` returns the fixed fallback prose when the intake is thin.

RED discipline (dev box has no Python — runs in Cloud Build): ``app.research.brief``
is imported LAZILY via ``importorskip`` so this module collects cleanly on a box
without the app installed. No network, no DB — pure string production.
"""

from __future__ import annotations

import types

import pytest

brief_mod = pytest.importorskip("app.research.brief")


# The marker that must NEVER appear in an assembled brief (D-01b / SEAM-04).
_INTERACTIVE_MARKER = "[INTERACTIVE_REPORT]"

# The fixed fallback report-spec hint (thin/missing intake fields).
_FALLBACK_HINT = "Standaard lengte, kerntabellen, alle onderzoeksvragen behandeld."


def _decomp(summary):
    """A minimal decomposition-like object exposing ``.summary`` (brief source)."""
    return types.SimpleNamespace(summary=summary)


def _question(text, priority):
    """A minimal research-question-like object (``.question_text`` / ``.priority``)."""
    return types.SimpleNamespace(question_text=text, priority=priority)


def _intake(**answers):
    """A thin intake-like object — ``derive_report_hint`` reads answer fields off it.

    The hint mapping is field-driven; a bare object with no answer attributes
    exercises the thin-intake FALLBACK path.
    """
    return types.SimpleNamespace(**answers)


def test_brief_never_opts_into_gates():
    """The assembled brief has NO [INTERACTIVE_REPORT] and enumerates the questions."""
    decomposition = _decomp("Diepgaand onderzoek naar de EV-laadmarkt in de Benelux.")
    questions = [
        _question("Wat is de marktomvang?", priority=1),
        _question("Wie zijn de belangrijkste spelers?", priority=2),
        _question("Welke regelgeving is relevant?", priority=3),
    ]

    result = brief_mod.assemble_brief(
        _intake(), decomposition, questions
    )

    # Pause-gate avoidance: the interactive-report marker must be absent (D-01b).
    assert _INTERACTIVE_MARKER not in result

    # Non-vague: the enumerated-questions header + every question text present.
    assert "Onderzoeksvragen:" in result
    for q in questions:
        assert q.question_text in result


def test_brief_enumerates_questions_in_priority_order():
    """Questions are enumerated in ascending priority order (lower priority first)."""
    decomposition = _decomp("Samenvatting.")
    # Deliberately supplied OUT of order — assemble_brief must sort by priority.
    questions = [
        _question("Derde vraag.", priority=3),
        _question("Eerste vraag.", priority=1),
        _question("Tweede vraag.", priority=2),
    ]

    result = brief_mod.assemble_brief(_intake(), decomposition, questions)

    pos_first = result.index("Eerste vraag.")
    pos_second = result.index("Tweede vraag.")
    pos_third = result.index("Derde vraag.")
    assert pos_first < pos_second < pos_third


def test_brief_falls_back_when_summary_missing():
    """A null decomposition summary yields a deterministic non-empty opening line."""
    decomposition = _decomp(None)
    questions = [_question("Enige vraag.", priority=1)]

    result = brief_mod.assemble_brief(
        _intake(), decomposition, questions
    )

    # Never blank; still enumerates and never opts into the gate.
    assert result.strip()
    assert "Onderzoeksvragen:" in result
    assert "Enige vraag." in result
    assert _INTERACTIVE_MARKER not in result


def test_report_hint_thin_intake_returns_fixed_fallback():
    """A thin intake (no sector/goals fields) returns the fixed fallback hint."""
    hint = brief_mod.derive_report_hint(_intake())
    assert hint == _FALLBACK_HINT
    assert _INTERACTIVE_MARKER not in hint


def test_report_hint_is_appended_to_brief():
    """The derived report-spec hint prose is appended to the assembled brief."""
    decomposition = _decomp("Samenvatting.")
    questions = [_question("Enige vraag.", priority=1)]

    result = brief_mod.assemble_brief(_intake(), decomposition, questions)

    # A thin intake -> the fallback hint prose is present in the brief tail.
    assert _FALLBACK_HINT in result


# ---------------------------------------------------------------------------
# Answers-derived questions + Context section (quick task 260721-twy):
# the GCP flow stores validated questions in the intake ANSWERS, not in the
# legacy research_questions table. The brief now folds the FULL context pack in
# under a [CONTEXT PACK] header (no truncation) and carries NO [CLARIFICATION
# ANSWERS] force-proceed sections — the engine's intake stage is a delegator that
# always produces a research plan, so the clarification-loop machinery is gone.
# ---------------------------------------------------------------------------

# The context-pack section header the brief folds the full context under.
_CONTEXT_PACK_HEADER = "[CONTEXT PACK]"

# The removed force-proceed / clarification marker — must NEVER reappear.
_CLARIFICATION_MARKER = "[CLARIFICATION ANSWERS]"


def test_questions_fall_back_to_intake_answers():
    """No DB question rows -> questions come from the intake ANSWERS (GCP source)."""
    intake = _intake(
        answers={
            "questions": [
                {"text": "Wat is de marktomvang van Acme in de Benelux?", "kind": "decision"}
            ],
            "extra_questions_proposed": [
                {"text": "Welke concurrenten winnen terrein?", "approved": True},
                {"text": "Afgekeurde vraag mag niet meegaan.", "approved": False},
            ],
        }
    )
    result = brief_mod.assemble_brief(intake, None, [])
    assert "Wat is de marktomvang van Acme in de Benelux?" in result
    assert "Welke concurrenten winnen terrein?" in result
    assert "Afgekeurde vraag mag niet meegaan." not in result
    assert _INTERACTIVE_MARKER not in result


def test_full_context_pack_folded_untruncated():
    """The FULL context pack text is folded into the brief under [CONTEXT PACK], untruncated.

    A >4000-char context pack must appear in full — the old 4000-char excerpt cap
    (``_CONTEXT_EXCERPT_CHARS``) is gone. A sentinel near the very END of the long
    context proves nothing was truncated. No clarification markers appear.
    """
    intake = _intake(answers={"questions": [{"text": "Eén concrete vraag."}]})
    # Build a context pack well over 4000 chars with a distinctive end sentinel.
    long_body = "Acme NV opereert in logistiek Benelux. " * 200  # ~7800 chars
    end_sentinel = "ZZZ_EINDE_VAN_DE_CONTEXT_PACK_MARKER"
    context = long_body + end_sentinel

    result = brief_mod.assemble_brief(intake, None, [], context_pack_text=context)

    # The labeled Context section is present and carries the FULL text (end sentinel
    # survives -> nothing truncated at 4000 chars).
    assert _CONTEXT_PACK_HEADER in result
    assert end_sentinel in result
    assert "Acme NV opereert in logistiek Benelux." in result
    # No leftover clarification / force-proceed machinery.
    assert _CLARIFICATION_MARKER not in result
    assert _INTERACTIVE_MARKER not in result


def test_no_clarification_marker_ever_present():
    """[CLARIFICATION ANSWERS] must never appear — with or without questions."""
    # With questions + a context pack.
    with_q = brief_mod.assemble_brief(
        _intake(answers={"questions": [{"text": "Eén concrete vraag."}]}),
        None,
        [],
        context_pack_text="Bedrijf: Acme NV. Markt: logistiek Benelux.",
    )
    assert _CLARIFICATION_MARKER not in with_q

    # Without any questions.
    without_q = brief_mod.assemble_brief(_intake(), None, [])
    assert _CLARIFICATION_MARKER not in without_q


def test_validated_questions_prefers_db_rows_over_answers():
    """Legacy DB rows (when present) win over the answers-derived list."""
    intake = _intake(answers={"questions": [{"text": "Antwoord-vraag."}]})
    rows = [_question("DB-vraag.", 1)]
    final = brief_mod.validated_questions(intake, rows)
    texts = [
        getattr(q, "question_text", None) or (q.get("question_text") if isinstance(q, dict) else None)
        for q in final
    ]
    assert texts == ["DB-vraag."]


def test_refined_research_questions_key_takes_precedence():
    """AI-review-refined 'research_questions' wins over the raw 'questions' field."""
    intake = _intake(
        answers={
            "research_questions": [{"text": "Verfijnde vraag na review."}],
            "questions": [{"text": "Ruwe klantvraag."}],
        }
    )
    result = brief_mod.assemble_brief(intake, None, [])
    assert "Verfijnde vraag na review." in result
    assert "Ruwe klantvraag." not in result


def test_string_entries_in_question_lists_are_supported():
    """research_questions entries may be plain strings (AIReviewPanel patches both shapes)."""
    intake = _intake(answers={"research_questions": ["Vraag als platte string?"]})
    result = brief_mod.assemble_brief(intake, None, [])
    assert "Vraag als platte string?" in result


# ---------------------------------------------------------------------------
# The [REPORT] block — client-chosen report language + size (quick 260806-lvt)
#
# WHY THESE EXIST. Measured on run 368ff3a0: mission_brief["language"] was EMPTY on
# every dispatch call, so the strong "Write EVERYTHING in {lang}" directive has never
# fired in production; and the client's output_size answer was read by nothing at all
# (length was proxied off question_count). These pin the producer half of the fix.
# ---------------------------------------------------------------------------

_REPORT_HEADER = "[REPORT]"
_REPORT_FOOTER = "[END REPORT]"


def test_report_block_absent_when_the_client_was_never_asked():
    """No language and no size answer => NO block at all. This is the OLD-INTAKE path.

    It must stay reachable and must stay EMPTY rather than defaulting: pipeline.py's
    zero-touch branch passes report_spec=None for exactly this shape, and a block made
    of whitespace would parse as a client CHOICE of whitespace.
    """
    result = brief_mod.assemble_brief(_intake(), _decomp("Samenvatting."), [])
    assert _REPORT_HEADER not in result
    assert _REPORT_FOOTER not in result


def test_compact_carries_both_the_keyword_and_the_page_range():
    """OPERATOR RULING: BOTH, never the keyword alone."""
    intake = _intake(answers={"output_size": "compact", "report_language": "nl"})
    result = brief_mod.assemble_brief(intake, _decomp("Samenvatting."), [])

    assert _REPORT_HEADER in result and _REPORT_FOOTER in result
    assert "LANGUAGE: Dutch" in result
    assert "LENGTH: brief" in result
    assert "PAGES: 2-5" in result


def test_standard_carries_a_page_target_with_no_keyword():
    """The default shape has no adjective to add, but the client was promised 5-10."""
    spec = brief_mod.derive_report_spec(_intake(answers={"output_size": "standard"}))
    assert spec == {"pages": "5-10"}

    result = brief_mod.assemble_brief(
        _intake(answers={"output_size": "standard"}), _decomp("S."), []
    )
    assert "PAGES: 5-10" in result
    assert "LENGTH:" not in result


def test_extended_maps_to_comprehensive_plus_pages():
    spec = brief_mod.derive_report_spec(_intake(answers={"output_size": "extended"}))
    assert spec == {"length": "comprehensive", "pages": "10-20"}


def test_other_routes_the_clients_own_words_to_instructions_and_invents_no_pages():
    """The client typed their own constraint; a page range would overrule it.

    Also the SHAPE test: FieldRenderer stores an allow_text radio as
    {"choice": ..., "text": ...}. Reading it with _first_nonempty would str() the dict
    into its repr, match no key, and report the answer as unset.
    """
    intake = _intake(
        answers={"output_size": {"choice": "other", "text": "max. 15 slides voor ExCo"}}
    )
    spec = brief_mod.derive_report_spec(intake)

    assert spec == {"instructions": "max. 15 slides voor ExCo"}
    assert "pages" not in spec
    assert "length" not in spec

    result = brief_mod.assemble_brief(intake, _decomp("S."), [])
    assert "INSTRUCTIONS: max. 15 slides voor ExCo" in result


def test_language_resolves_to_an_english_name_the_engine_can_read_twice():
    """The engine interpolates this into an English prompt AND maps it to an ISO code."""
    assert brief_mod.derive_report_language(_intake(answers={"report_language": "nl"})) == "Dutch"
    assert brief_mod.derive_report_language(_intake(answers={"report_language": "fr"})) == "French"
    assert brief_mod.derive_report_language(_intake(answers={"report_language": "en"})) == "English"
    # Unknown / absent must stay EMPTY, never guessed.
    assert brief_mod.derive_report_language(_intake(answers={"report_language": "xx"})) == ""
    assert brief_mod.derive_report_language(_intake()) == ""


def test_instructions_are_collapsed_to_one_line():
    """The block is line-oriented; a newline in client text would forge a block line."""
    intake = _intake(
        answers={"output_size": {"choice": "other", "text": "max 15 slides\nLENGTH: brief"}}
    )
    result = brief_mod.assemble_brief(intake, _decomp("S."), [])
    block = result.split(_REPORT_HEADER, 1)[1].split(_REPORT_FOOTER, 1)[0]
    assert "LENGTH:" not in block.split("INSTRUCTIONS:", 1)[0]
    assert len([ln for ln in block.strip().splitlines() if ln.strip()]) == 1


def test_report_block_never_reintroduces_the_interactive_marker():
    """The block is NOT the interactive gate — the seam must still never opt in."""
    intake = _intake(answers={"output_size": "extended", "report_language": "en"})
    result = brief_mod.assemble_brief(intake, _decomp("S."), [])
    assert _INTERACTIVE_MARKER not in result


def test_page_ranges_match_the_labels_the_client_actually_reads():
    """THE DRIFT GUARD. Two places now show the client a number: the option label on
    the form and the instruction handed to the writer. If they ever diverge we would
    be promising one thing and instructing another, and nothing would notice.

    Change a label from 2-5 to 3-6 pages and this goes red until the constant follows.
    """
    import json
    import pathlib

    template = json.loads(
        (
            pathlib.Path(brief_mod.__file__).resolve().parents[1]
            / "data"
            / "pulse_intake_v1.json"
        ).read_text(encoding="utf-8")
    )

    section = next(s for s in template["sections"] if s["id"] == "output_format")
    field = next(f for f in section["fields"] if f["key"] == "output_size")
    options = {o["value"]: o for o in field["options"]}

    # Non-vacuity: the mapping must not be silently empty, and every mapped value
    # must still exist as an option the client can actually pick.
    assert brief_mod._OUTPUT_SIZE_SPEC, "the size mapping is empty — nothing is pinned"
    for value, spec in brief_mod._OUTPUT_SIZE_SPEC.items():
        assert value in options, f"{value} is mapped but is not an option on the form"
        pages = spec["pages"]
        for locale in ("nl", "fr", "en"):
            label = options[value]["label"][locale]
            assert pages in label, (
                f"{value}: the {locale} label {label!r} does not contain the mapped "
                f"page range {pages!r} — the form and the writer now disagree"
            )


def test_report_language_is_a_required_field_on_the_live_template():
    """The field must exist and be required — nothing may silently default."""
    import json
    import pathlib

    template = json.loads(
        (
            pathlib.Path(brief_mod.__file__).resolve().parents[1]
            / "data"
            / "pulse_intake_v1.json"
        ).read_text(encoding="utf-8")
    )
    section = next(s for s in template["sections"] if s["id"] == "output_format")
    field = next(f for f in section["fields"] if f["key"] == "report_language")

    assert field["required"] is True
    assert {o["value"] for o in field["options"]} == set(brief_mod._RUN_LANGUAGE_NAMES)
