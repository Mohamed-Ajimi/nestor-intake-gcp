"""Per-engine clarification cap contract (decision 2026-06-10).

Tribunal: capped at 2 rounds — it CAN force-proceed past the cap (intake override).
ADK:      uncapped — it CANNOT be forced (D-01 read-only) and asks one question per
          turn plus a competitor-confirmation checkpoint, so any small cap fails
          virtually every competitive brief. Every ADK pause parks the run as
          needs_input awaiting a human, so an uncapped ADK cannot loop unattended.

Grep-gate style (the repo's established pattern for structural invariants).
"""
from __future__ import annotations

from pathlib import Path

_SDK = Path(__file__).parent.parent


def test_adk_adapter_has_no_clarification_cap():
    src = (_SDK / "runs" / "adapter.py").read_text(encoding="utf-8")
    assert "ADK hit the 2-round clarification cap" not in src, (
        "ADK must NOT fail on a clarification cap — it pauses for a human "
        "(needs_input) on every round instead"
    )
    # The pause path itself must still exist
    assert "needs_clarification" in src


def test_tribunal_keeps_two_round_cap_with_force_proceed():
    src = (_SDK / "pipeline" / "tribunal" / "pipeline.py").read_text(encoding="utf-8")
    assert "_CLAR_CAP = 2" in src, "Tribunal must keep its 2-round clarification cap"
    assert "force_proceed" in src, "Tribunal's cap requires the force-proceed path"


# ---------------------------------------------------------------------------
# ADK answer replay: folded brief -> conversation turns
# ---------------------------------------------------------------------------

from nestor_pulse_sdk.runs.adapter import _split_brief_rounds


class TestSplitBriefRounds:
    def test_plain_brief_is_one_turn(self):
        assert _split_brief_rounds("Research X for client Y.") == [
            "Research X for client Y."
        ]

    def test_folded_brief_splits_into_turns(self):
        brief = (
            "Research X for client Y.\n\n"
            "[CLARIFICATION ANSWERS]\nBelgium only, last 2 years.\n\n"
            "[CLARIFICATION ANSWERS]\nAkkoord met de concurrentenlijst."
        )
        turns = _split_brief_rounds(brief)
        assert len(turns) == 3
        assert turns[0] == "Research X for client Y."
        assert turns[1] == "Belgium only, last 2 years."
        assert turns[2] == "Akkoord met de concurrentenlijst."

    def test_empty_blocks_are_dropped(self):
        brief = "Base.\n\n[CLARIFICATION ANSWERS]\n\n[CLARIFICATION ANSWERS]\nReal answer."
        assert _split_brief_rounds(brief) == ["Base.", "Real answer."]

    def test_empty_brief_yields_single_empty_turn(self):
        assert _split_brief_rounds("") == [""]


def test_adk_shim_replays_answers_as_turns():
    """The shim must loop turns (replay) rather than send one folded mega-brief."""
    src = (_SDK / "runs" / "adapter.py").read_text(encoding="utf-8")
    assert "_split_brief_rounds(brief)" in src
    assert "for turn_idx, turn_text in enumerate(turns)" in src
