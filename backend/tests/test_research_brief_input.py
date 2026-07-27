"""The producer half of the D-G / D-H fix (plan 15.2-21) — the brief's own structure.

WHAT THIS PINS. ``app.research.brief`` composes the string that crosses the seam
into the Tribunal engine, and the engine's
``pipeline/tribunal/brief_input.py::parse_brief`` reads that string's structure.
This module owns the PRODUCER side of that contract:

  * :func:`derive_decision_statement`'s four-step precedence, and in particular
    that it never returns the deterministic ``"Deep research for …"`` title — that
    exact string, ``Deep research for moetest.``, is defect D-H: on run
    ``d6bb3aae`` every tournament prompt in the run ranked candidate questions by
    their materiality to a project TITLE;
  * the ``[DECISION]`` / ``[END DECISION]`` delimiters themselves, asserted as
    LITERALS, so renaming one side of the seam without the other breaks a test
    rather than a paid run;
  * that an unresolvable decision emits NEITHER marker — an empty block would
    parse, on the engine side, as a decision made of whitespace, which is worse
    than none: none is reported as a named degradation, whitespace is silently
    ranked against;
  * that the ``Onderzoeksvragen:`` header and its DIGIT enumeration survive
    unchanged (the engine's legacy alias reads them, and its item regex is
    digits-only on purpose), and that ``[INTERACTIVE_REPORT]`` is still never
    emitted (the D-01b pause-gate guard).

WHY ``pytestmark = pytest.mark.integration``, ON A PURE STRING TEST. In THIS
repository the only committed backend gate is the repo-root ``cloudbuild.test.yaml``,
which runs ``python -m pytest tests -m integration``. The marker is therefore, in
practice, the "runs in the committed merge gate" flag — it is NOT a claim that this
module needs a database. It needs no DB, no network and no API key, and it will run
happily without one.

Say the corollary out loud rather than inheriting it silently: the pre-existing
``backend/tests/test_research_brief.py`` carries NO marker and so runs in NO
committed gate (deferred item D19-2). That gap is D19-2's to close, not this plan's,
and marking this module does not close it.

RED discipline (the dev box has no Python — this runs in Cloud Build):
``app.research.brief`` is imported LAZILY via ``importorskip`` so the module
collects cleanly on a box without the app installed.

Cloud Build invocation:
  gcloud builds submit --config=cloudbuild.test.yaml .
"""

from __future__ import annotations

import types

import pytest

brief_mod = pytest.importorskip("app.research.brief")

pytestmark = pytest.mark.integration


# The seam delimiters, as LITERALS. The engine-side parser
# (`pipeline/tribunal/brief_input.py`) hard-codes the same two strings; if either
# side is renamed alone, these assertions fail before a run pays for the mismatch.
_DECISION_HEADER = "[DECISION]"
_DECISION_FOOTER = "[END DECISION]"

# The marker that must NEVER appear in an assembled brief (D-01b / SEAM-04).
_INTERACTIVE_MARKER = "[INTERACTIVE_REPORT]"

# The context pack's §3 block, in the exact shape
# `app.ai.prompts.CONTEXT_PACK_SKILL_PROMPT` asks the skill to write.
_PACK_DECISION = "launch Germany 2027, or consolidate NL first"
_CONTEXT_PACK = "\n".join(
    [
        "## 3. De beslissing die eraan hangt",
        f"- **Wat moet beslist worden:** {_PACK_DECISION}",
        "- **Door wie:** MOE (CEO) + senior leadership",
        "- **Tegen wanneer:** juni 2026",
        "",
        "## 10. Taalregister & output-eisen",
        "- **Output-omvang (harde constraint):** Standaard (15-25 p.)",
    ]
)

# The same pack, but with the skill's honest "not filled in yet" placeholder.
_CONTEXT_PACK_PLACEHOLDER = "\n".join(
    [
        "## 3. De beslissing die eraan hangt",
        "- **Wat moet beslist worden:** [concreet]",
        "- **Door wie:** *nog in te vullen*",
    ]
)


def _decomp(summary):
    """A minimal decomposition-like object exposing ``.summary``."""
    return types.SimpleNamespace(summary=summary)


def _question(text, priority=1):
    """A minimal research-question-like object (``.question_text`` / ``.priority``)."""
    return types.SimpleNamespace(question_text=text, priority=priority)


def _intake(**answers):
    """An intake-like object whose ``.answers`` is a flat ``{field_key: value}`` map."""
    return types.SimpleNamespace(answers=dict(answers), project_title="moetest")


_QUESTIONS = [
    _question("Welke retailers passen dynamic pricing toe in Europa vandaag?", 1),
    _question("Hoe evolueerden de koffiestrategieen in de BeNeLux sinds 2023?", 2),
]


# ---------------------------------------------------------------------------
# Test 1 — the context pack's §3 line wins.
# ---------------------------------------------------------------------------


def test_the_context_pack_decision_line_wins():
    """§3 outranks the decomposition summary AND the project title."""
    statement = brief_mod.derive_decision_statement(
        _intake(decision="een heel andere formulering uit het formulier"),
        _decomp("Een samenvatting van de opdracht"),
        _CONTEXT_PACK,
    )

    assert statement == _PACK_DECISION


def test_the_pack_placeholder_is_not_a_decision():
    """`[concreet]` is the pack being honest, not the client deciding something."""
    statement = brief_mod.derive_decision_statement(
        _intake(),
        _decomp(None),
        _CONTEXT_PACK_PLACEHOLDER,
    )

    assert statement == ""


# ---------------------------------------------------------------------------
# Test 2 — the intake's own decision answer.
# ---------------------------------------------------------------------------


def test_the_intake_decision_answer_is_used_when_the_pack_has_no_section_three():
    """No §3 line -> the client's own raw answer, before any model framing."""
    answer = "Beslissen of we in 2027 naar Duitsland gaan of eerst NL verdiepen"

    statement = brief_mod.derive_decision_statement(
        _intake(beslissing=answer),
        _decomp("Een samenvatting van de opdracht"),
        "## 5. Scope\n- **In scope:** BeNeLux",
    )

    assert statement == answer


# ---------------------------------------------------------------------------
# Test 3 — the summary, then nothing. And never the title.
# ---------------------------------------------------------------------------


def test_the_decomposition_summary_is_the_last_resort():
    summary = "Onderzoek naar de haalbaarheid van een Duitse uitrol in 2027"

    statement = brief_mod.derive_decision_statement(_intake(), _decomp(summary), None)

    assert statement == summary


def test_nothing_resolves_to_the_empty_string():
    assert brief_mod.derive_decision_statement(None, None, None) == ""
    assert brief_mod.derive_decision_statement(_intake(), _decomp(""), "") == ""


def test_the_title_fallback_is_never_a_decision():
    """`Deep research for moetest.` IS D-H — it must not come back as a decision."""
    statement = brief_mod.derive_decision_statement(
        _intake(), _decomp("Deep research for moetest."), None
    )

    assert statement == ""


def test_the_statement_is_collapsed_and_bounded():
    ragged = "  Duitsland   lanceren\n\tin 2027  " + (" of eerst NL" * 200)

    statement = brief_mod.derive_decision_statement(_intake(decision=ragged), None, None)

    assert statement.startswith("Duitsland lanceren in 2027")
    assert len(statement) <= 400
    assert "\n" not in statement
    assert "  " not in statement


# ---------------------------------------------------------------------------
# Test 4 — the block is emitted only when a decision resolves.
# ---------------------------------------------------------------------------


def test_assemble_brief_emits_the_decision_block_when_one_resolves():
    composed = brief_mod.assemble_brief(
        _intake(),
        _decomp("Een samenvatting van de opdracht"),
        _QUESTIONS,
        context_pack_text=_CONTEXT_PACK,
    )

    assert _DECISION_HEADER in composed
    assert _DECISION_FOOTER in composed

    lines = composed.splitlines()
    start = lines.index(_DECISION_HEADER)
    end = lines.index(_DECISION_FOOTER)
    assert lines[start + 1:end] == [_PACK_DECISION]

    # It sits between the questions and the context pack — part of the ASSIGNMENT.
    assert lines.index("Onderzoeksvragen:") < start
    assert end < lines.index("[CONTEXT PACK]")


def test_assemble_brief_emits_neither_marker_when_no_decision_resolves():
    """An empty block would parse, engine-side, as a decision made of whitespace."""
    composed = brief_mod.assemble_brief(
        _intake(),
        _decomp("Deep research for moetest."),
        _QUESTIONS,
        context_pack_text=_CONTEXT_PACK_PLACEHOLDER,
    )

    assert _DECISION_HEADER not in composed
    assert _DECISION_FOOTER not in composed


# ---------------------------------------------------------------------------
# Test 5 — nothing the engine's parser depends on has moved.
# ---------------------------------------------------------------------------


def test_the_question_block_and_its_digit_enumeration_are_unchanged():
    """The engine reads `Onderzoeksvragen:` as its legacy alias, digits-only items."""
    composed = brief_mod.assemble_brief(
        _intake(),
        _decomp("Een samenvatting"),
        _QUESTIONS,
        context_pack_text=_CONTEXT_PACK,
    )
    lines = composed.splitlines()

    header = lines.index("Onderzoeksvragen:")
    assert lines[header + 1] == f"1. {_QUESTIONS[0].question_text}"
    assert lines[header + 2] == f"2. {_QUESTIONS[1].question_text}"


@pytest.mark.parametrize(
    "context_pack",
    [_CONTEXT_PACK, _CONTEXT_PACK_PLACEHOLDER, None, ""],
)
def test_the_brief_never_opts_into_the_interactive_report_gate(context_pack):
    """D-01b is unchanged by this plan, on every decision path."""
    composed = brief_mod.assemble_brief(
        _intake(sector="brandstofretail"),
        _decomp("Een samenvatting"),
        _QUESTIONS,
        context_pack_text=context_pack,
    )

    assert _INTERACTIVE_MARKER not in composed
    assert "Onderzoeksvragen:" in composed
