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
# Answers-derived questions + force-proceed sections (live finding 2026-07-21):
# the GCP flow stores validated questions in the intake ANSWERS, not in the
# legacy research_questions table — and the engine force-proceeds only when the
# brief carries >= 2 [CLARIFICATION ANSWERS] sections (TribunalPipeline _CLAR_CAP).
# ---------------------------------------------------------------------------


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


def test_force_proceed_sections_present_with_questions():
    """A question-bearing brief carries >= 2 [CLARIFICATION ANSWERS] sections."""
    intake = _intake(answers={"questions": [{"text": "Eén concrete vraag."}]})
    result = brief_mod.assemble_brief(
        intake, None, [], context_pack_text="Bedrijf: Acme NV. Markt: logistiek Benelux."
    )
    assert result.count("[CLARIFICATION ANSWERS]") >= 2
    assert "Acme NV" in result
    assert _INTERACTIVE_MARKER not in result


def test_no_questions_yields_no_force_proceed_sections():
    """An empty brief must NOT carry force-proceed sections (the 422 guard's domain)."""
    result = brief_mod.assemble_brief(_intake(), None, [])
    assert "[CLARIFICATION ANSWERS]" not in result


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
