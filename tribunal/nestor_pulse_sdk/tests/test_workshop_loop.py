"""Pure-arithmetic tests for `workshop_loop` — Wave 4's loop maths.

WHY THIS FILE EXISTS AND WHY IT IS SHAPED LIKE THIS.

The Wave 4 design was MEASURED before it was built: an 11-experiment local
harness replayed the real V-01 run and drove the whole loop end to end. That
harness proved the DESIGN converges. It proved nothing whatsoever about any
implementation. The only way the implementation inherits the same guarantee is
if every piece of arithmetic is separable, pure and drivable over hundreds of
cases — rather than argued about inside an async LLM loop that costs money to
run and cannot be run on the development machine at all.

So: no `import pytest`, no fixtures, no parametrise, no `pytest.raises`. Plain
`def test_*()` functions and bare asserts, exactly as `test_discovery_bracket.py`
does. That is not stylistic. It is what lets these same functions be driven by a
twenty-line loader on the one stdlib-only interpreter this machine has, so the
tests are run by their author BEFORE the gate ever sees them, and it costs
nothing for the gate to run them too.
"""

from __future__ import annotations

import copy
import json
import random
from typing import Any

from nestor_pulse_sdk.pipeline.tribunal import workshop_loop
from nestor_pulse_sdk.pipeline.tribunal.workshop_loop import (
    catch_up_matches,
    exit_verdict,
    round_metrics,
    select_winners,
    tournament_rounds,
)

_KEEP = "KEEP"
_WEAK = "WEAK"

Q1 = "How do fuel retailers monetise coffee?"
Q2 = "What does a shop-in-shop rollout cost?"
Q3 = "Which regulations bind opening hours?"


def _cand(
    index: int,
    parent: str,
    critique: str = _KEEP,
    parents: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """One candidate dict in the shape the ranking stage produces."""
    entry: dict[str, Any] = {
        "index": index,
        "text": f"candidate sub-question number {index}",
        "parent": parent,
        "critique": critique,
        "flaw": "",
    }
    if parents is not None:
        entry["parents"] = parents
    entry.update(extra)
    return entry


def _labels_covered(winner: dict[str, Any], label: str) -> bool:
    parents = winner.get("parents") or []
    if parents:
        return label in parents
    return winner.get("parent") == label


# ===========================================================================
# tournament_rounds — D-R9, the DERIVED round count
# ===========================================================================


def test_tournament_rounds_gives_seventeen_candidates_six_rounds() -> None:
    """The measured case. THIS IS THE ASSERTION THAT FAILS AGAINST A HARDCODED 4.

    17 candidates at the shipped `_TOURNAMENT_ROUNDS = 4` gives each candidate
    3.76 matches, and the harness reproduced V-01's exact symptom from it: three
    candidates finishing at Elo exactly 1200.00 with 2 wins each, straddling the
    top-10 cut, one of them losing its research slot to INDEX ORDER.
    """
    assert tournament_rounds(17) == 6


def test_tournament_rounds_yields_to_the_field_when_the_field_is_tiny() -> None:
    """A field of 3 has only 2 distinct opponents.

    The floor of 6 must NOT schedule four rematches to reach itself. `n - 1` is
    a hard bound on useful Swiss rounds and it wins over the floor.
    """
    assert tournament_rounds(3) == 2
    assert tournament_rounds(2) == 1


def test_tournament_rounds_is_zero_when_there_is_nothing_to_rank() -> None:
    assert tournament_rounds(0) == 0
    assert tournament_rounds(1) == 0


def test_tournament_rounds_never_exceeds_the_maximum() -> None:
    assert tournament_rounds(200) <= workshop_loop._TOURNAMENT_ROUNDS_MAX
    assert tournament_rounds(10_000) <= workshop_loop._TOURNAMENT_ROUNDS_MAX


def test_tournament_rounds_is_monotone_non_decreasing_over_the_sweep() -> None:
    """The property sweep. T-15.7-03-02: no unbounded growth as the population grows.

    The population grows EVERY loop round, which is precisely why the count is
    derived rather than hardcoded. Monotone non-decreasing, never above the
    ceiling, and never above `n - 1` for any rankable field.
    """
    previous = 0
    for n in range(0, 201):
        current = tournament_rounds(n)
        assert current >= previous, f"n={n} went DOWN: {previous} -> {current}"
        assert current <= workshop_loop._TOURNAMENT_ROUNDS_MAX, f"n={n} broke the ceiling"
        if n >= 2:
            assert current <= n - 1, f"n={n} scheduled more rounds than it has opponents"
        else:
            assert current == 0
        previous = current


def test_tournament_rounds_lets_an_explicit_operator_override_win() -> None:
    """`workshop_rank` owns the env knob; this module owns the formula.

    The override is how the two stay one authority instead of two. A positive
    override is an operator setting and always wins; a zero, a negative or a
    garbled one falls through to the derivation.
    """
    assert tournament_rounds(17, override=2) == 2
    assert tournament_rounds(17, override=1) == 1
    assert tournament_rounds(17, override=0) == 6
    assert tournament_rounds(17, override=-3) == 6
    assert tournament_rounds(17, override="nonsense") == 6


def test_tournament_rounds_never_raises_on_hostile_input() -> None:
    for hostile in (None, "", "abc", [], {}, 3.7, True, float("nan")):
        assert isinstance(tournament_rounds(hostile), int)


# ===========================================================================
# catch_up_matches — D-W4-3, the newcomer catch-up BUDGET
# ===========================================================================


def test_catch_up_matches_returns_the_low_median() -> None:
    """The measured case: a field at 12/12/11 with two newcomers on 0.

    Sorted that is [0, 0, 11, 12, 12] and the LOW median is 11 — element
    `(5 - 1) // 2 = 2`. Deliberately NOT `statistics.median`, which would return
    11 here but 11.5 on an even-length list, and this value INDEXES A SCHEDULE.
    """
    assert catch_up_matches([12, 12, 11, 0, 0]) == 11


def test_catch_up_matches_takes_the_low_side_of_an_even_field() -> None:
    """An even-length field is where `statistics.median` would hand back a float."""
    assert catch_up_matches([10, 12]) == 10
    assert catch_up_matches([0, 1, 2, 3]) == 1


def test_catch_up_matches_returns_a_real_int_and_never_a_bool() -> None:
    """`isinstance(True, int)` is True, so `int` alone is not enough of an assertion."""
    result = catch_up_matches([12, 12, 11, 0, 0])
    assert isinstance(result, int)
    assert not isinstance(result, bool)
    boolish = catch_up_matches([True, True, True])
    assert isinstance(boolish, int)
    assert not isinstance(boolish, bool)
    assert boolish == 1


def test_catch_up_matches_is_zero_on_an_empty_or_unusable_field() -> None:
    assert catch_up_matches([]) == 0
    assert catch_up_matches(None) == 0
    assert catch_up_matches(["x", "y"]) == 0


def test_catch_up_matches_never_raises_on_hostile_input() -> None:
    """T-15.7-03-01: this function is TOTAL. Model-authored data reaches it."""
    hostile_batteries = (
        None,
        "a string is iterable and every element is a character",
        [-4, "x", None, 7, 9],
        [{}, [], object()],
        [float("nan"), float("inf")],
        {},
        12,
    )
    for battery in hostile_batteries:
        result = catch_up_matches(battery)
        assert isinstance(result, int)
        assert not isinstance(result, bool)
        assert result >= 0


def test_catch_up_matches_drops_negatives_rather_than_ranking_them() -> None:
    """A negative match count is nonsense, not a low score. It leaves the field."""
    assert catch_up_matches([-5, -5, 4, 6, 8]) == 6


# ===========================================================================
# The module-level property that makes everything above drivable
# ===========================================================================


def test_workshop_loop_imports_nothing_from_the_engine_package() -> None:
    """A PROPERTY, never an exact allowlist of module names.

    An exact-set assertion over a file is what turned phase 15.5's merged tree
    red while three verifications read green. So this asserts the one thing that
    actually matters — that no `nestor_pulse_sdk` import exists in the source —
    and says nothing about which standard-library modules are used.

    Two reasons the property is load-bearing. `workshop_rank` will import THIS
    module, so the reverse import would be circular. And being stdlib-only is
    what makes the module drivable on the single interpreter available on the
    development machine.
    """
    import pathlib

    source = pathlib.Path(workshop_loop.__file__).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("import ") or stripped.startswith("from "):
            assert "nestor_pulse_sdk" not in stripped, f"engine import leaked in: {stripped}"


# ===========================================================================
# select_winners — D-W4-5, the floor at the cut and prefer-KEEP
# ===========================================================================


def _pool_36() -> list[dict[str, Any]]:
    """The measured shape: 3 client questions, plus a discovery tail.

    Ranks 0-29 are single-parent, round-robin over the three client questions.
    Ranks 30-35 carry the `__discovery__` sentinel, so they cover NO client
    question label and the per-label counts below are exact rather than
    approximate.
    """
    pool: list[dict[str, Any]] = []
    labels = [Q1, Q2, Q3]
    for i in range(30):
        pool.append(_cand(i, labels[i % 3]))
    for i in range(30, 36):
        pool.append(_cand(i, workshop_loop._DISCOVERY_PARENT))
    return pool


def test_select_winners_returns_seventeen_for_three_client_questions() -> None:
    """THE VALIDATED CONFIGURATION: 5 + 5 + 5 + 2 = 17. exp11 measured exactly this.

    `default_cut` is deliberately passed as 13 — what `winner_count(36)` actually
    returns — so this test also pins that THE FLOOR OVERRIDES THE CUT. If a later
    reader restores the `_WINNERS_MAX` cap of 15, this goes red instead of
    silently deleting two research questions.
    """
    ranked = _pool_36()
    winners, below = select_winners(
        ranked, client_questions=[Q1, Q2, Q3], default_cut=13
    )
    assert len(winners) == 17, f"expected 17 winners, got {len(winners)}"
    for label in (Q1, Q2, Q3):
        covering = [w for w in winners if _labels_covered(w, label)]
        assert len(covering) == 5, f"{label!r} got {len(covering)} winners, expected 5"
    cross = [w for w in winners if w.get("cross_cutting") is True]
    assert len(cross) == 2, f"expected 2 cross-cutting winners, got {len(cross)}"
    assert len(below) == 19


def test_select_winners_honours_the_floor_when_a_question_ranks_badly() -> None:
    """Every client question gets its 5 even when its best candidate ranks 30th.

    This is the whole reason the floor is applied AT THE CUT rather than by
    taking the top N and hoping. A globally-ranked pool can legitimately bury one
    client question, and D4 coverage does not bend to that.
    """
    ranked = [_cand(i, Q1 if i % 2 == 0 else Q2) for i in range(30)]
    ranked += [_cand(i, Q3) for i in range(30, 40)]
    winners, below = select_winners(
        ranked, client_questions=[Q1, Q2, Q3], default_cut=13
    )
    assert len(winners) == 17
    q3 = [w for w in winners if _labels_covered(w, Q3)]
    assert len(q3) == 5
    assert [w["index"] for w in q3] == [30, 31, 32, 33, 34]
    assert len(winners) + len(below) == len(ranked)


def test_select_winners_shortfall_does_not_steal_another_questions_floor() -> None:
    """A client question with only 2 candidates gets 2 — and Q1/Q2 still get 5 each."""
    ranked = [_cand(i, Q1) for i in range(20)]
    ranked += [_cand(i, Q2) for i in range(20, 40)]
    ranked += [_cand(i, Q3) for i in range(40, 42)]
    winners, below = select_winners(
        ranked, client_questions=[Q1, Q2, Q3], default_cut=13
    )
    assert len([w for w in winners if _labels_covered(w, Q3)]) == 2
    assert len([w for w in winners if _labels_covered(w, Q1)]) >= 5
    assert len([w for w in winners if _labels_covered(w, Q2)]) >= 5
    assert len(winners) == 17
    assert len(winners) + len(below) == len(ranked)


def _prefer_keep_pool() -> list[dict[str, Any]]:
    """Ranks 0-3 KEEP, rank 4 WEAK, ranks 5-8 WEAK, rank 9 KEEP.

    The first four slots go to the four KEEPs at the top. The FIFTH slot is the
    contested one: a WEAK at rank 4 against a KEEP at rank 9.
    """
    critiques = [_KEEP, _KEEP, _KEEP, _KEEP, _WEAK, _WEAK, _WEAK, _WEAK, _WEAK, _KEEP]
    return [_cand(i, Q1, critiques[i]) for i in range(10)]


def test_prefer_keep_takes_the_rank_nine_keep_over_the_rank_four_weak() -> None:
    """PREFER-KEEP, column A. The single highest-leverage rule the measurement found.

    Exit criterion 2 CHECKS for WEAK winners and nothing anywhere ever PREVENTED
    one from being selected — a smoke alarm with no fire door. Adding this
    preference took WEAK winners to 0 and made criterion 2 satisfiable BY
    CONSTRUCTION rather than by luck.
    """
    winners, _ = select_winners(
        _prefer_keep_pool(),
        client_questions=[Q1],
        default_cut=10,
        cross_cutting_slots=0,
        prefer_keep=True,
    )
    assert [w["index"] for w in winners] == [0, 1, 2, 3, 9]
    assert all(w["critique"] == _KEEP for w in winners)


def test_prefer_keep_disabled_takes_the_rank_four_weak_instead() -> None:
    """PREFER-KEEP, column B. Without this the rule above is unfalsifiable.

    A test that only ever runs the rule ON cannot tell you the rule is doing
    anything. Turning it OFF and getting a DIFFERENT answer is the proof.
    """
    winners, _ = select_winners(
        _prefer_keep_pool(),
        client_questions=[Q1],
        default_cut=10,
        cross_cutting_slots=0,
        prefer_keep=False,
    )
    assert [w["index"] for w in winners] == [0, 1, 2, 3, 4]
    assert winners[4]["critique"] == _WEAK


def test_select_winners_falls_back_to_default_cut_with_no_client_questions() -> None:
    ranked = [_cand(i, "") for i in range(20)]
    winners, below = select_winners(ranked, client_questions=[], default_cut=10)
    assert [w["index"] for w in winners] == list(range(10))
    assert len(below) == 10


def test_select_winners_recognises_a_two_label_span_as_cross_cutting() -> None:
    """The OTHER branch of the cross-cutting definition: parents spanning 2+ labels.

    Cross-cutting mandate questions are where the best measured output came from,
    and they have two REAL parents rather than the discovery sentinel.
    """
    ranked = [_cand(i, Q1 if i % 2 == 0 else Q2) for i in range(20)]
    ranked += [_cand(i, Q1, parents=[Q1, Q2]) for i in range(20, 24)]
    winners, _ = select_winners(
        ranked, client_questions=[Q1, Q2], default_cut=10, floor_per_question=5
    )
    cross = [w for w in winners if w.get("cross_cutting") is True]
    assert len(cross) == 2
    assert [w["index"] for w in cross] == [20, 21]


def test_select_winners_never_bars_anything_over_two_hundred_seeded_pools() -> None:
    """THE PERMUTATION INVARIANT. Losing the tournament is not a defect.

    `enforce_scope_guard`s documented repair ladder PROMOTES a below-the-cut
    candidate when a client question ends up with no winner. Bar the losers and
    that repair path breaks, which is why `below_cut` is returned at all rather
    than discarded.
    """
    labels = [Q1, Q2, Q3]
    for seed in range(200):
        rng = random.Random(seed)
        size = rng.randint(1, 60)
        ranked = []
        for i in range(size):
            choice = rng.random()
            if choice < 0.12:
                parent = workshop_loop._DISCOVERY_PARENT
                parents = None
            elif choice < 0.22:
                parent = rng.choice(labels)
                parents = [labels[0], labels[1]]
            else:
                parent = rng.choice(labels)
                parents = None
            ranked.append(
                _cand(i, parent, rng.choice([_KEEP, _WEAK]), parents=parents)
            )
        winners, below = select_winners(
            ranked, client_questions=labels, default_cut=13
        )
        won = [w["index"] for w in winners]
        lost = [w["index"] for w in below]
        assert len(won) + len(lost) == size, f"seed {seed}: candidates went missing"
        assert len(set(won)) == len(won), f"seed {seed}: duplicate winner"
        assert len(set(won) & set(lost)) == 0, f"seed {seed}: a candidate is in both"
        assert set(won) | set(lost) == set(range(size)), f"seed {seed}: not a permutation"
        assert won == sorted(won), f"seed {seed}: winners are not in rank order"
        assert lost == sorted(lost), f"seed {seed}: losers lost their relative order"


def test_select_winners_is_deterministic_and_pure() -> None:
    """Same input, same output — and the caller keeps the list it handed in.

    The purity half is a deep-copy comparison rather than a promise in prose: a
    function that quietly stamps `cross_cutting` onto the CALLER's dicts would
    pass every behavioural test above and still be a bug, because the ranked pool
    is reused by the evolve step.
    """
    ranked = _pool_36()
    pristine = copy.deepcopy(ranked)
    first = select_winners(ranked, client_questions=[Q1, Q2, Q3], default_cut=13)
    second = select_winners(ranked, client_questions=[Q1, Q2, Q3], default_cut=13)
    assert first == second
    assert ranked == pristine, "select_winners mutated the caller's candidates"


def test_select_winners_never_raises_on_hostile_input() -> None:
    """T-15.7-03-01 again: this function is TOTAL."""
    batteries: tuple[Any, ...] = (
        None,
        "a string",
        [None, "x", 7],
        [{}, {"index": "not an int"}],
        [],
    )
    for battery in batteries:
        winners, below = select_winners(
            battery, client_questions=[Q1], default_cut=5
        )
        assert isinstance(winners, list)
        assert isinstance(below, list)


# ===========================================================================
# exit_verdict — D-W4-6. 1 = COVERAGE, 2 = QUALITY, 3 = SATURATION.
# ===========================================================================


def _clean_winners() -> list[dict[str, Any]]:
    """One KEEP winner per client question, none new this round. Exits cleanly."""
    return [
        _cand(0, Q1, _KEEP, born_round=1),
        _cand(1, Q2, _KEEP, born_round=1),
        _cand(2, Q3, _KEEP, born_round=2),
    ]


def test_exit_verdict_exits_only_when_all_three_criteria_hold() -> None:
    verdict = exit_verdict(
        winners=_clean_winners(), client_questions=[Q1, Q2, Q3], round_no=4
    )
    assert verdict["coverage_ok"] is True
    assert verdict["quality_ok"] is True
    assert verdict["saturation_ok"] is True
    assert verdict["should_exit"] is True
    assert verdict["cap_reached"] is False
    assert verdict["degradation_reason"] == ""


def test_coverage_is_criterion_one_and_needs_a_keep_per_client_question() -> None:
    """A client question whose only winner is WEAK is NOT covered.

    Criterion 1 asks for a KEEP, not merely for a winner. A question represented
    only by a question the critic could not sharpen is not a question the engine
    has actually covered.
    """
    winners = [
        _cand(0, Q1, _KEEP),
        _cand(1, Q2, _KEEP),
        _cand(2, Q3, _WEAK),
    ]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=3
    )
    assert verdict["coverage_ok"] is False
    assert verdict["should_exit"] is False


def test_coverage_failing_is_a_normal_reading_and_not_a_bug() -> None:
    """MEASURED: coverage FAILED in rounds 4 and 5 of the harness before recovering.

    Barring WEAK-after-two-passes stripped every KEEP candidate from one client
    question, and the exit AND correctly refused to exit. A `False` here is an
    expected reading of a loop still doing its job, not a defect to be tuned out.
    """
    verdict = exit_verdict(
        winners=[_cand(0, Q1, _KEEP), _cand(1, Q2, _KEEP)],
        client_questions=[Q1, Q2, Q3],
        round_no=4,
    )
    assert verdict["coverage_ok"] is False
    assert verdict["quality_ok"] is True
    assert verdict["should_exit"] is False


def test_quality_is_criterion_two_and_a_weak_winner_fails_it() -> None:
    winners = _clean_winners() + [_cand(3, Q1, _WEAK)]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=3
    )
    assert verdict["coverage_ok"] is True
    assert verdict["quality_ok"] is False
    assert verdict["weak_winners"] == 1
    assert verdict["should_exit"] is False


def test_exemption_a_a_cross_cutting_winner_never_counts_as_weak() -> None:
    """EXEMPTION A. A cross-cutting question is compound BY CONSTRUCTION.

    It joins two topics on purpose, so the flaw clause about two questions in
    one must not count against it. Without the exemption criterion 2
    structurally penalises exactly the highest-value questions the loop exists
    to produce — it would be built to reject its own best output. exp9 marked
    both its best questions WEAK for precisely this reason.
    """
    winners = _clean_winners() + [
        _cand(3, Q1, _WEAK, parents=[Q1, Q2], cross_cutting=True)
    ]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=3
    )
    assert verdict["quality_ok"] is True
    assert verdict["weak_winners"] == 0
    assert verdict["should_exit"] is True


def test_exemption_a_is_structural_and_survives_a_non_english_flaw_clause() -> None:
    """THE REASON EXEMPTION A KEYS OFF A BOOLEAN AND NOT OFF THE FLAW TEXT.

    The critique prompt is English, but a Dutch or French run flaw clause is
    model prose IN THE RUN OWN LANGUAGE. An implementation that matched the
    English phrase would silently NEVER FIRE on those runs, and criterion 2
    would be built to reject exactly the questions the loop exists to produce.

    Both fixtures below are the SAME winner set apart from the language of the
    flaw. A structural implementation passes both. A text-matching one passes
    the English column and fails the Dutch column, which is what makes this
    test the proof rather than the assertion.
    """
    for flaw in (
        "two questions in one",
        "twee vragen in een enkele vraag samengevoegd",
        "deux questions en une seule",
    ):
        winners = _clean_winners() + [
            _cand(3, Q1, _WEAK, parents=[Q1, Q2], cross_cutting=True, flaw=flaw)
        ]
        verdict = exit_verdict(
            winners=winners, client_questions=[Q1, Q2, Q3], round_no=3
        )
        assert verdict["quality_ok"] is True, f"language regression on flaw {flaw!r}"


def test_a_resurrected_winner_fails_criterion_two_and_still_passes_criterion_one() -> None:
    """THE OFF-BY-ONE, CORRECTED 2026-07-31. THIS TEST IS THE CORRECTION.

    Until that date `15.7-OPEN-ITEMS.md`, spec section 5 boxed warning and
    section 8 Wave 4 row ALL said criterion 1. That was wrong in a way that
    INVERTED THE RULE OWN PURPOSE: criterion 1 is COVERAGE and criterion 2 is
    QUALITY, and excluding a resurrected candidate from COVERAGE would break the
    very guarantee resurrection exists to provide.

    Why the direction is FAILS and not IS-IGNORED: the two resurrection guards
    are COVERAGE FALLBACKS, not quality passes. Guard 2 rewrites EVERY candidate
    to KEEP when critique kills everything — so the one case where quality most
    needs to read as FAILED would otherwise read as a perfect pass.
    """
    winners = [
        _cand(0, Q1, _KEEP),
        _cand(1, Q2, _KEEP),
        _cand(2, Q3, _KEEP, resurrected=True),
    ]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=3
    )
    assert verdict["coverage_ok"] is True, "criterion 1 is COVERAGE and must still pass"
    assert verdict["quality_ok"] is False, "criterion 2 is QUALITY and must fail"
    assert verdict["resurrected_winners"] == 1
    assert verdict["should_exit"] is False


def test_the_resurrected_flag_is_read_and_never_inferred() -> None:
    """Guard 2 does not set the flag today; plan 15.7-08 makes it do so.

    This function must be correct either way, which means it READS the flag and
    does not try to deduce resurrection from anything else.
    """
    unmarked = [_cand(i, label, _KEEP) for i, label in enumerate((Q1, Q2, Q3))]
    verdict = exit_verdict(
        winners=unmarked, client_questions=[Q1, Q2, Q3], round_no=3
    )
    assert verdict["resurrected_winners"] == 0
    assert verdict["quality_ok"] is True


def test_saturation_is_criterion_three_and_a_new_entrant_fails_it() -> None:
    winners = _clean_winners() + [_cand(3, Q1, _KEEP, born_round=5)]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=5
    )
    assert verdict["saturation_ok"] is False
    assert verdict["quality_ok"] is True
    assert verdict["should_exit"] is False


def test_the_criteria_gate_each_other_in_turn_rather_than_one_blocking_forever() -> None:
    """MEASURED: round 2 saturation passed but quality failed; round 3 the reverse.

    The AND is doing real work. Both directions are represented here because a
    criterion that is permanently unreachable and a criterion that takes its turn
    look identical from a single round.
    """
    saturation_yes_quality_no = exit_verdict(
        winners=_clean_winners() + [_cand(3, Q1, _WEAK, born_round=1)],
        client_questions=[Q1, Q2, Q3],
        round_no=6,
    )
    assert saturation_yes_quality_no["saturation_ok"] is True
    assert saturation_yes_quality_no["quality_ok"] is False
    assert saturation_yes_quality_no["should_exit"] is False

    quality_yes_saturation_no = exit_verdict(
        winners=_clean_winners() + [_cand(3, Q1, _KEEP, born_round=6)],
        client_questions=[Q1, Q2, Q3],
        round_no=6,
    )
    assert quality_yes_saturation_no["quality_ok"] is True
    assert quality_yes_saturation_no["saturation_ok"] is False
    assert quality_yes_saturation_no["should_exit"] is False


def test_the_cap_ships_with_a_degradation_sentence_a_human_can_read() -> None:
    """D-12: degraded means honest, not broken. V-01 would have carried this.

    The sentence must be a sentence — over 40 characters, naming its count as a
    literal digit and stating the CONSEQUENCE rather than just the event.
    """
    winners = _clean_winners() + [
        _cand(3, Q1, _WEAK),
        _cand(4, Q2, _WEAK),
        _cand(5, Q3, _WEAK),
    ]
    verdict = exit_verdict(
        winners=winners, client_questions=[Q1, Q2, Q3], round_no=10, max_rounds=10
    )
    assert verdict["cap_reached"] is True
    assert verdict["quality_ok"] is False
    assert verdict["weak_winners"] == 3
    reason = verdict["degradation_reason"]
    assert len(reason) > 40, f"degradation reason is not a sentence: {reason!r}"
    assert "3" in reason, "the degradation reason must name its count as a digit"
    assert _WEAK in reason


def test_no_degradation_sentence_when_the_cap_is_reached_cleanly() -> None:
    verdict = exit_verdict(
        winners=_clean_winners(), client_questions=[Q1, Q2, Q3], round_no=10, max_rounds=10
    )
    assert verdict["cap_reached"] is True
    assert verdict["degradation_reason"] == ""
    assert verdict["should_exit"] is True


def test_exit_verdict_never_raises_on_hostile_input() -> None:
    """The 5-shape hostile battery. T-15.7-03-01."""
    batteries: tuple[Any, ...] = (
        None,
        "a string where a list of winners was expected",
        [1, 2, 3],
        [{"parents": [[], {}], "critique": {"unhashable": ["value"]}}],
        [],
    )
    for battery in batteries:
        for questions in (None, [], [Q1], "not a list"):
            verdict = exit_verdict(
                winners=battery, client_questions=questions, round_no=None
            )
            assert isinstance(verdict, dict)
            assert isinstance(verdict["should_exit"], bool)
            assert isinstance(verdict["degradation_reason"], str)


# ===========================================================================
# round_metrics — D-W4-7. RECORDED, never ENFORCED.
# ===========================================================================


def _metrics(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "round_no": 3,
        "candidates_in": 34,
        "new_candidates": 7,
        "winners": 17,
        "weak_winners": 0,
        "barred": 4,
        "dropped_as_reproposal": 3,
        "lookups": 2,
        "calls": 97,
        "cost_usd": 0.24,
    }
    kwargs.update(overrides)
    return round_metrics(**kwargs)


def test_round_metrics_is_json_safe_and_carries_no_float() -> None:
    """`cost_usd` becomes a STRING, exactly as `workshop_rank` stats do.

    A float in an audit record is a float that renders differently depending on
    who serialises it. The house idiom is `str(cost)` and this follows it.
    """
    metrics = _metrics()
    encoded = json.dumps(metrics)
    assert isinstance(encoded, str)
    for key, value in metrics.items():
        assert not isinstance(value, float), f"{key} came back as a float"
        assert isinstance(value, (int, str)), f"{key} is neither an int nor a string"


def test_round_metrics_enforces_nothing_at_all() -> None:
    """D-W4-7: no ceiling, no truncation, no exception.

    Neither the spend ceiling nor a population cap nor a per-round grounded
    lookup cap is binding at the measured scale — population stayed between 23
    and 41 across all three global configurations and the whole validated run
    cost $0.24 against an original ~$3.00 estimate. An enforced ceiling nobody
    has measured a need for is a knob that will one day truncate a run for no
    reason; a logged number is what tells you whether a ceiling is warranted.
    """
    absurd = _metrics(candidates_in=1_000_000, lookups=9_999, cost_usd=999.99, calls=50_000)
    assert absurd["candidates_in"] == 1_000_000
    assert absurd["lookups"] == 9_999
    assert absurd["calls"] == 50_000
    assert "999.99" in absurd["cost_usd"]


def test_round_metrics_records_the_measured_round_faithfully() -> None:
    metrics = _metrics()
    assert metrics["round_no"] == 3
    assert metrics["candidates_in"] == 34
    assert metrics["new_candidates"] == 7
    assert metrics["winners"] == 17
    assert metrics["weak_winners"] == 0
    assert metrics["barred"] == 4
    assert metrics["dropped_as_reproposal"] == 3


def test_round_metrics_counts_a_collection_rather_than_refusing_it() -> None:
    """A caller that passes the winner LIST gets its length, not a silent zero."""
    metrics = _metrics(winners=[{}, {}, {}], barred=("a", "b"))
    assert metrics["winners"] == 3
    assert metrics["barred"] == 2


def test_round_metrics_never_raises_on_hostile_input() -> None:
    batteries: tuple[Any, ...] = (None, "x", object(), {"a": ["unhashable"]}, [])
    for battery in batteries:
        metrics = round_metrics(
            round_no=battery,
            candidates_in=battery,
            new_candidates=battery,
            winners=battery,
            weak_winners=battery,
            barred=battery,
            dropped_as_reproposal=battery,
            lookups=battery,
            calls=battery,
            cost_usd=battery,
        )
        assert isinstance(metrics, dict)
        json.dumps(metrics)
        for value in metrics.values():
            assert not isinstance(value, float)
