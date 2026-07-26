"""D-17 terminal states — the park / degrade / complete truth table (Phase 15.2).

D-17, in the operator's words: **park only when no honest deliverable is
possible; otherwise finish degraded.** R2's breaker is per-provider; R4's park is
whole-run. The boundary between them is the whole point:

  - one or two research streams lost  -> `completed_degraded`, and the run says
    in words what it lost (D-12)
  - every provider walled, verification unable to run at all, the synthesis
    model walled, or a hard account wall -> `parked`, because nothing usable can
    come out and this genuinely needs a human

Park must mean "this needs you", not "a stream of emails asking permission to
carry on" — so the two rejected designs (park on ANY hard wall; never park) are
both encoded here as things that must NOT happen.

`terminal_state()` is pure: no I/O, no clock, no LLM, no DB. This file is the
whole truth table and runs in milliseconds. `failed` and `cancelled` are written
elsewhere (`runs/worker.py`) and are deliberately outside its range.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import pytest

from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    ENGINE_TERMINAL_STATES,
    terminal_state,
)


def _healthy(**overrides):
    """A clean 4-stream run; each test overrides exactly the axis it is about."""
    args = {
        "streams_lost": 0,
        "streams_total": 4,
        "verify_ran": True,
        "synthesis_ran": True,
        "hard_wall": False,
        "degradation_reasons": [],
    }
    args.update(overrides)
    return args


# ---------------------------------------------------------------------------
# The truth table.
# ---------------------------------------------------------------------------

_TRUTH_TABLE = [
    # (id, overrides, expected)
    ("clean-run", {}, "completed"),
    (
        "one-stream-lost-with-a-reason",
        {"streams_lost": 1, "degradation_reasons": ["gemini stream lost"]},
        "completed_degraded",
    ),
    (
        "two-streams-lost-with-reasons",
        {
            "streams_lost": 2,
            "degradation_reasons": ["gemini stream lost", "openai stream lost"],
        },
        "completed_degraded",
    ),
    ("every-stream-lost", {"streams_lost": 4}, "parked"),
    (
        "every-stream-lost-even-with-reasons",
        {"streams_lost": 4, "degradation_reasons": ["all providers walled"]},
        "parked",
    ),
    ("hard-wall-with-everything-else-healthy", {"hard_wall": True}, "parked"),
    ("verification-could-not-run", {"verify_ran": False}, "parked"),
    ("synthesis-model-walled", {"synthesis_ran": False}, "parked"),
    ("no-streams-at-all", {"streams_total": 0}, "parked"),
    (
        "bucket-3-only-degradation",
        {"degradation_reasons": ["bucket 3 non-zero: 12 claims unchecked"]},
        "completed_degraded",
    ),
    (
        "workshop-fell-back",
        {"degradation_reasons": ["workshop fell back to client-validated questions"]},
        "completed_degraded",
    ),
    (
        "stream-lost-but-nobody-recorded-why",
        {"streams_lost": 1, "degradation_reasons": []},
        "completed_degraded",
    ),
    ("blank-reasons-are-not-reasons", {"degradation_reasons": ["", "  "]}, "completed"),
    ("none-reason-list", {"degradation_reasons": None}, "completed"),
]


@pytest.mark.parametrize(
    "overrides,expected",
    [(row[1], row[2]) for row in _TRUTH_TABLE],
    ids=[row[0] for row in _TRUTH_TABLE],
)
def test_terminal_state_truth_table(overrides, expected):
    assert terminal_state(**_healthy(**overrides)) == expected


# ---------------------------------------------------------------------------
# The named boundary cases, spelled out so a future reader sees the intent and
# not just a table row.
# ---------------------------------------------------------------------------


def test_a_clean_run_is_plain_completed():
    assert terminal_state(**_healthy()) == "completed"


def test_losing_one_of_four_streams_degrades_but_does_not_park():
    """A report from what remains is an honest deliverable. Finish it."""
    assert (
        terminal_state(
            streams_lost=1,
            streams_total=4,
            verify_ran=True,
            synthesis_ran=True,
            hard_wall=False,
            degradation_reasons=["gemini stream lost"],
        )
        == "completed_degraded"
    )


def test_losing_every_stream_parks():
    """No research at all means no honest deliverable — that needs a human."""
    assert (
        terminal_state(
            streams_lost=4,
            streams_total=4,
            verify_ran=True,
            synthesis_ran=True,
            hard_wall=False,
            degradation_reasons=[],
        )
        == "parked"
    )


def test_a_hard_wall_parks_even_when_everything_else_is_healthy():
    """The settled R4 case: the Anthropic monthly cap, or exhausted credits.

    Parking keeps the checkpoint so the run resumes free after the reset
    (2026-08-01) instead of finishing near-empty.
    """
    assert terminal_state(**_healthy(hard_wall=True)) == "parked"


def test_a_lost_stream_with_no_reason_still_degrades_and_never_reports_clean():
    """Fail loud. A silent `completed` here would be a new silent-green."""
    assert terminal_state(**_healthy(streams_lost=1)) == "completed_degraded"


def test_blank_and_whitespace_reasons_do_not_degrade_a_run():
    """An empty string is not a reason — degrading on it would be alarm fatigue."""
    assert terminal_state(**_healthy(degradation_reasons=["", "   ", "\n"])) == "completed"


# ---------------------------------------------------------------------------
# The range of the function.
# ---------------------------------------------------------------------------


def test_every_returned_value_is_a_declared_engine_terminal_state():
    returned = {
        terminal_state(**_healthy(**row[1])) for row in _TRUTH_TABLE
    }
    assert returned <= set(ENGINE_TERMINAL_STATES)
    assert returned == {"completed", "completed_degraded", "parked"}, (
        "the truth table must exercise all three states"
    )


def test_failed_and_cancelled_are_never_returned():
    """They mean "the run crashed" / "a human stopped it" — not a verdict on output."""
    for row in _TRUTH_TABLE:
        assert terminal_state(**_healthy(**row[1])) not in {"failed", "cancelled"}


def test_engine_terminal_states_is_the_declared_vocabulary():
    assert ENGINE_TERMINAL_STATES == ("completed", "completed_degraded", "parked")


def test_terminal_state_is_pure_and_deterministic():
    """Same inputs, same answer, every time — no clock, no I/O, no LLM."""
    args = _healthy(streams_lost=1, degradation_reasons=["gemini stream lost"])
    assert len({terminal_state(**args) for _ in range(50)}) == 1
