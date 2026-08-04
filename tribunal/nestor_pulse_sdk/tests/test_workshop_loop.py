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

    THE ROUND NUMBER MOVED FROM 3 TO THE FLOOR (D-W4-9, 2026-08-04) and the
    subject of the test did not. `should_exit` now ANDs the minimum-round floor
    into the three criteria, so a round below `_LOOP_MIN_ROUNDS` would read
    `False` for a reason that has nothing to do with Exemption A — the assertion
    would still fail loudly, but it would stop being a statement about criterion
    2. It reads the constant rather than a hand-typed 4 so it tracks the floor.
    """
    winners = _clean_winners() + [
        _cand(3, Q1, _WEAK, parents=[Q1, Q2], cross_cutting=True)
    ]
    verdict = exit_verdict(
        winners=winners,
        client_questions=[Q1, Q2, Q3],
        round_no=workshop_loop._LOOP_MIN_ROUNDS,
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


# ===========================================================================
# The MINIMUM-ROUND FLOOR — D-W4-9, operator ruling 2026-08-04.
#
# THE DEFECT IT CLOSES. Criterion 3 (SATURATION) is VACUOUSLY TRUE IN ROUND 1:
# `_stamp_loop_candidates` stamps `born_round = round_no + 1`, so round 1's
# winner set structurally cannot hold a loop-born candidate and `new_entrants`
# is necessarily 0. On a KEEP-heavy brief coverage and quality also hold, all
# three criteria are satisfied, and the loop breaks after ONE pass — no COMBINE,
# no cross-question synthesis, no INVENT through the evidence gate, and the two
# cross-cutting slots filled by ordinary candidates by rank.
# ===========================================================================


def _unborn_winners() -> list[dict[str, Any]]:
    """A clean winner set with NO `born_round` at all.

    Distinct from `_clean_winners`, whose members carry `born_round=1`/`2` and
    would therefore fail criterion 3 in round 1 for an unrelated reason. These
    tests are about the FLOOR, so the three criteria must genuinely all hold.
    """
    return [
        _cand(0, Q1, _KEEP),
        _cand(1, Q2, _KEEP),
        _cand(2, Q3, _KEEP),
    ]


def test_all_three_criteria_hold_in_round_one_and_the_floor_still_blocks_exit() -> None:
    """THE BLOCKER ITSELF. Every criterion passes; the loop must not stop."""
    verdict = exit_verdict(
        winners=_unborn_winners(), client_questions=[Q1, Q2, Q3], round_no=1
    )
    assert verdict["coverage_ok"] is True
    assert verdict["quality_ok"] is True
    assert verdict["saturation_ok"] is True, "criterion 3 is vacuous in round 1"
    assert verdict["floor_ok"] is False
    assert verdict["should_exit"] is False
    assert verdict["min_rounds"] == workshop_loop._LOOP_MIN_ROUNDS


def test_the_same_winner_set_exits_once_the_floor_is_reached() -> None:
    verdict = exit_verdict(
        winners=_unborn_winners(),
        client_questions=[Q1, Q2, Q3],
        round_no=workshop_loop._LOOP_MIN_ROUNDS,
    )
    assert verdict["floor_ok"] is True
    assert verdict["should_exit"] is True
    assert verdict["hold_reason"] == ""


def test_a_cap_below_the_floor_wins_so_the_loop_can_never_be_unterminable() -> None:
    """THE TERMINATION GUARANTEE IS UNCHANGED, and this is the proof.

    `effective_floor = min(floor, cap)`. At `round_no == cap` the floor is
    necessarily satisfied, so the driver's `for round_no in range(1, max_rounds
    + 1)` remains the SOLE bound on how long the loop runs. A floor that could
    outrank the cap would be a floor that hangs the engine.
    """
    held = exit_verdict(
        winners=_unborn_winners(),
        client_questions=[Q1, Q2, Q3],
        round_no=1,
        max_rounds=2,
    )
    assert held["should_exit"] is False
    assert held["min_rounds"] == 2, "the floor degrades to the cap, not the reverse"

    at_cap = exit_verdict(
        winners=_unborn_winners(),
        client_questions=[Q1, Q2, Q3],
        round_no=2,
        max_rounds=2,
    )
    assert at_cap["cap_reached"] is True
    assert at_cap["should_exit"] is True

    degenerate = exit_verdict(
        winners=_unborn_winners(),
        client_questions=[Q1, Q2, Q3],
        round_no=1,
        max_rounds=1,
    )
    assert degenerate["should_exit"] is True, "a cap of 1 must still exit in round 1"

    absurd = exit_verdict(
        winners=_unborn_winners(),
        client_questions=[Q1, Q2, Q3],
        round_no=10,
        max_rounds=10,
        min_rounds=10**6,
    )
    assert absurd["should_exit"] is True
    assert absurd["min_rounds"] == 10


def test_a_floor_hold_is_distinguishable_from_criteria_not_met() -> None:
    """A READER OF THE VERDICT MUST BE ABLE TO TELL THE TWO APART.

    Both read `should_exit: False`. Only one of them is the loop being held
    open by a rule; the other is the loop genuinely not being done. If they
    were indistinguishable, the audited record could not explain why round 1
    did not stop.
    """
    held = exit_verdict(
        winners=_unborn_winners(), client_questions=[Q1, Q2, Q3], round_no=1
    )
    reason = held["hold_reason"]
    assert reason, "criteria met but floor not reached must carry a sentence"
    assert len(reason) > 40, f"hold reason is not a sentence: {reason!r}"
    assert "1" in reason and str(workshop_loop._LOOP_MIN_ROUNDS) in reason

    not_met = _unborn_winners()
    not_met[0]["critique"] = _WEAK
    verdict = exit_verdict(
        winners=not_met, client_questions=[Q1, Q2, Q3], round_no=1
    )
    assert verdict["quality_ok"] is False
    assert verdict["should_exit"] is False
    assert verdict["hold_reason"] == "", "criteria NOT met is not a floor hold"


def test_a_floor_hold_is_not_a_degradation() -> None:
    """D-12's alarm-fatigue rule. The driver appends `degradation_reason` to
    `loop_reasons` as a degradation; a loop working exactly as designed must
    not raise one."""
    held = exit_verdict(
        winners=_unborn_winners(), client_questions=[Q1, Q2, Q3], round_no=1
    )
    assert held["hold_reason"] != ""
    assert held["degradation_reason"] == ""

    # `degradation_reason`'s own composition is untouched: cap reached AND
    # quality failing is still the only thing that produces one.
    weak = _unborn_winners() + [_cand(3, Q1, _WEAK)]
    capped = exit_verdict(
        winners=weak, client_questions=[Q1, Q2, Q3], round_no=10, max_rounds=10
    )
    assert capped["degradation_reason"] != ""
    assert capped["hold_reason"] == ""


def test_the_floor_is_read_from_the_module_constant_at_call_time() -> None:
    """Monkeypatching the constant must change behaviour, which is what makes
    `test_engine_e2e_stubbed.py`'s pin to 1 work at all."""
    original = workshop_loop._LOOP_MIN_ROUNDS
    try:
        workshop_loop._LOOP_MIN_ROUNDS = 1
        verdict = exit_verdict(
            winners=_unborn_winners(), client_questions=[Q1, Q2, Q3], round_no=1
        )
        assert verdict["should_exit"] is True
        assert verdict["min_rounds"] == 1
    finally:
        workshop_loop._LOOP_MIN_ROUNDS = original


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
            # `min_rounds` joins the battery: a garbled floor must coerce like
            # every other hostile input rather than raise inside a stage that
            # has already paid for its LLM calls.
            for floor in (None, "junk", -5, 0, [], True):
                verdict = exit_verdict(
                    winners=battery,
                    client_questions=questions,
                    round_no=None,
                    min_rounds=floor,
                )
                assert isinstance(verdict, dict)
                assert isinstance(verdict["should_exit"], bool)
                assert isinstance(verdict["floor_ok"], bool)
                assert isinstance(verdict["hold_reason"], str)
                assert isinstance(verdict["min_rounds"], int)
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


# ===========================================================================
# THE SEAM: the loop driven END TO END through the REAL `run_workshop_stage_b`.
#
# WHY THESE ASSERT ON THE RETURNED CONTRACT AND NEVER ON A COLLABORATOR. Wave 3
# shipped 42/42 verification and 1283 green tests and still carried TWO
# criticals, because every plan's own `must_haves` were individually satisfied
# and the defects lived in the SEAMS BETWEEN PLANS. This plan IS the seam, so a
# barred question that does not reappear "according to the register" proves
# nothing — only its absence from the RETURNED winner set does.
#
# Every model call is SCRIPTED: a canned critique per round, an oracle judge, a
# scripted sharpener, a scripted generative evolve and a scripted meta-review.
# That makes a multi-round run deterministic, free and fast, and it is the only
# way these assertions can be driven at all.
# ===========================================================================

import asyncio
import re
import types
import uuid

from nestor_pulse_sdk.pipeline.tribunal import (
    discovery_bracket,
    workshop_rank,
    workshop_register,
)

_KILL = "KILL"
_START = workshop_rank._WINNERS_START
_END = workshop_rank._WINNERS_END

CQ1 = "Coffee monetisation"
CQ2 = "Rollout cost"
CQ3 = "Opening hours"
SEAM_LABELS = [CQ1, CQ2, CQ3]


def _classify_prompt(prompt: str) -> str:
    """Which workshop call is this? Ordered MOST SPECIFIC FIRST.

    The generative-evolve prompt also carries `LANGS:`, so `SOURCE_INDICES` has
    to be tested before the sharpener — otherwise every generation call would be
    answered with sharpener lines and the loop would never grow its pool.

    `CLUSTER_ID` is FIRST and it is the one that unlocks D-W4-1 layer 2. Until it
    was routed, the near-duplicate clustering call fell through to the `meta`
    branch, `_parse_cluster_lines` found no parseable line, every candidate got
    the `-1` singleton sentinel — and THE SEMANTIC DROP NEVER FIRED IN ANY TEST.
    Every barred-reappearance assertion built on that would have passed because
    nothing was ever clustered, which is the silently-vacuous shape this whole
    file exists to avoid.
    """
    if "CLUSTER_ID" in prompt:
        return "cluster"
    if "MATCH_INDEX" in prompt:
        return "judge"
    if "SOURCE_INDICES" in prompt:
        return "generate"
    if "KILL" in prompt and "KEEP" in prompt and "WEAK" in prompt:
        return "critique"
    if "LANGS:" in prompt:
        return "sharpen"
    return "meta"


def _script(*, weak_first_rounds: int = 2, generate_rounds: int = 3,
            new_per_round: int = 6, seed: int = 0, weak_label: str = CQ3):
    """A scripted responder.

    `weak_label`'s candidates are WEAK for the first `weak_first_rounds` rounds,
    so that question's floor slots have no KEEP to prefer and BOTH criterion 1
    (coverage) and criterion 2 (quality) fail early.

    CORRECTED 2026-08-04 (D-W4-9). This paragraph used to say that an all-KEEP
    script "correctly exits in round 1", and that is no longer true: the
    minimum-round floor inside `exit_verdict` guarantees at least
    `_LOOP_MIN_ROUNDS` passes whatever the criteria say, and
    `test_an_all_keep_script_still_runs_the_full_floor_of_rounds` asserts exactly
    that. The early WEAK is therefore not what keeps the loop alive any more —
    but it remains a DIFFERENT and still-necessary thing to exercise, because it
    is the only arm of this file that drives criteria 1 and 2 through a genuine
    FAIL and back to a recovery, which is the behaviour the harness measured and
    which a floor does not produce on its own.
    """
    state: dict[str, int] = {"round": 0, "generate": 0}
    rng = random.Random(seed)

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            if rows and int(rows[0][0]) == 0:
                state["round"] += 1
            lines = []
            for raw_index, text in rows:
                if state["round"] <= weak_first_rounds and weak_label in text:
                    verdict, flaw = _WEAK, "too broad to answer as it stands"
                else:
                    verdict, flaw = _KEEP, "-"
                lines.append(f"{int(raw_index)} | {verdict} | {flaw}")
            return "\n".join(lines)

        if kind == "judge":
            count = len(re.findall(r"^\s*\d+\s*\|", prompt, re.M))
            return "\n".join(
                f"{i} | {'A' if rng.random() < 0.5 else 'B'} | scripted verdict"
                for i in range(max(count, 1))
            )

        if kind == "sharpen":
            indices = sorted({int(m) for m in re.findall(r"^(\d+) \| ", prompt, re.M)})
            body = "\n".join(
                f"{i} | sharpened research question {i} for this client | LANGS: nl,en"
                for i in indices
            )
            return f"{_START}\n{body}\n{_END}"

        if kind == "generate":
            state["generate"] += 1
            if state["generate"] > generate_rounds:
                return f"{_START}\n{_END}"
            lines = [
                f"{k} | COMBINE | 0,1 | new loop question round "
                f"{state['generate']} number {k} joining two winners | LANGS: nl,en"
                for k in range(new_per_round)
            ]
            return f"{_START}\n" + "\n".join(lines) + f"\n{_END}"

        return "focus the next round on cost evidence"

    return respond


class _ScriptedClient:
    """The audited LLM client, entirely scripted. Records every prompt it saw."""

    def __init__(self, responder: Any) -> None:
        self._responder = responder
        self.prompts: list[str] = []

    async def gemini_generate(self, *, run_id, tenant_id, model, contents,
                              audit_out=None, **kw):
        prompt = contents if isinstance(contents, str) else str(contents)
        self.prompts.append(prompt)
        if isinstance(audit_out, dict):
            audit_out["cost_usd"] = "0.001"
        return types.SimpleNamespace(
            text=self._responder(_classify_prompt(prompt), prompt), candidates=None
        )

    async def anthropic_messages(self, *, run_id, tenant_id, model, messages,
                                 max_tokens=None, audit_out=None, **kw):
        prompt = ""
        for message in messages:
            for block in message.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "text":
                    prompt += block.get("text") or ""
        self.prompts.append(prompt)
        if isinstance(audit_out, dict):
            audit_out["cost_usd"] = "0.001"
        return types.SimpleNamespace(
            content=[types.SimpleNamespace(
                type="text", text=self._responder(_classify_prompt(prompt), prompt)
            )],
            stop_reason="end_turn",
        )


def _stage_a(labels, per_question: int = 12, empty_labels: Any = ()):
    """A stage-A payload. A label in `empty_labels` gets a client question but NO
    candidates, which is what forces a scope-guard repair."""
    questions = [{"label": L, "text": f"Client question: {L}"} for L in labels]
    candidates: list[dict[str, Any]] = []
    cursor = 0
    for label in labels:
        if label in empty_labels:
            continue
        for k in range(per_question):
            candidates.append({
                "index": cursor,
                "text": f"sub-question {cursor} about {label} number {k}",
                "parent": label,
                "parents": [label],
                "source": "model",
                "scope_injected": False,
                "cluster_key": "",
                "merged_from": [],
            })
            cursor += 1
    return {
        "questions": questions,
        "candidates": candidates,
        "brief_conflicts": [],
        "degradation_reasons": [],
    }


def _run_stage_b(client: Any, labels: Any, payload: Any = None) -> dict[str, Any]:
    return asyncio.run(workshop_rank.run_workshop_stage_b(
        stage_a=payload if payload is not None else _stage_a(labels),
        decision_context="Should the client roll out shop-in-shop coffee?",
        run_language="nl",
        deep_research_prompt="",
        audited=client,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        feed=None,
        breaker=None,
    ))


def test_the_loop_exits_on_its_criteria_before_the_cap() -> None:
    """D-W4-6. THE EXIT ROUND IS ASSERTED AS A RANGE AND NEVER AS A CONSTANT.

    The measurement harness exited at rounds 4, 6 and 6 on three runs of the SAME
    configuration, because evolve runs at temperature 1.0. A hard round number is
    a flaky test by construction; what is actually guaranteed is that a healthy
    brief converges strictly INSIDE the cap.
    """
    observed = []
    for seed in range(5):
        result = _run_stage_b(_ScriptedClient(_script(seed=seed)), SEAM_LABELS)
        observed.append(result["counts"]["rounds"])
    assert all(1 <= r < workshop_loop._LOOP_MAX_ROUNDS for r in observed), observed
    # It must actually LOOP. Without this line a run that exited in round 1 would
    # satisfy the assertion above while proving nothing about the loop at all.
    assert all(r >= 2 for r in observed), observed


def test_an_all_keep_script_still_runs_the_full_floor_of_rounds() -> None:
    """D-W4-9 END TO END, and this is the arm the unit tests cannot reach.

    `weak_first_rounds=0` makes every candidate KEEP from round 1, which is the
    exp11-shaped healthy brief: coverage holds, quality holds, and criterion 3
    is VACUOUSLY true because `_stamp_loop_candidates` stamps `born_round =
    round_no + 1` so no round-1 winner can be loop-born. Before the floor this
    run stopped after ONE pass — no COMBINE, no cross-question synthesis, no
    INVENT through the evidence gate — which is Wave 4 degenerating into the
    straight line it was built to replace.

    Asserted as a RANGE, for the same reason `test_the_loop_exits_on_its_
    criteria_before_the_cap` is: evolve runs at temperature 1.0 and the exact
    exit round is not a guarantee. What IS guaranteed is the floor and the cap.
    """
    result = _run_stage_b(
        _ScriptedClient(_script(weak_first_rounds=0)), SEAM_LABELS
    )
    rounds = result["counts"]["rounds"]
    assert rounds >= workshop_loop._LOOP_MIN_ROUNDS, rounds
    assert rounds <= workshop_loop._LOOP_MAX_ROUNDS, rounds
    assert result["winners"]


def test_every_final_winner_carries_a_non_empty_langs_list() -> None:
    """D7 SURVIVES THE LOOP, asserted through the contract stage B returns.

    `langs` is written only by `evolve_winners` via `_normalise_langs`, and plan
    15.2-13 builds its angle-query language sentence ONLY when `langs` is
    non-empty — so a loop that routed around that step would ship D7-less winners
    while every other assertion in this phase read green.
    """
    result = _run_stage_b(_ScriptedClient(_script()), SEAM_LABELS)
    assert result["winners"]
    for winner in result["winners"]:
        assert winner.get("langs"), winner.get("text")


def test_a_scope_guard_injected_winner_also_carries_langs() -> None:
    """THE NON-VACUITY CASE for the test above, and it is not decoration.

    A client question with NO candidates is repaired by `enforce_scope_guard`
    injecting `_verbatim_winner`, which sets `langs: []` — and that winner reaches
    the tail WITHOUT passing through `evolve_winners`. Deleting the
    `_normalise_langs` sweep below the scope guard makes exactly this winner ship
    with an empty `langs`; measured, that mutant takes the empty count from 0 to
    1 while every other assertion in this file stays green.
    """
    empty = "Staffing model"
    labels = SEAM_LABELS + [empty]
    payload = _stage_a(labels, empty_labels=(empty,))
    result = _run_stage_b(_ScriptedClient(_script()), labels, payload=payload)
    injected = [w for w in result["winners"] if w.get("source") == "verbatim"]
    assert injected, "the empty client question should have been repaired"
    for winner in result["winners"]:
        assert winner.get("langs"), winner.get("text")


def test_no_winner_is_a_discovery_question() -> None:
    """T-15.7-09-04. `build_mission_brief_from_winners` derives the report's
    client-facing focus-area sections from this list, so a discovered question in
    it would mint a section the client never asked for — and D4 says depth may
    grow while SCOPE MAY NOT."""
    result = _run_stage_b(_ScriptedClient(_script()), SEAM_LABELS)
    for winner in result["winners"]:
        assert winner.get("source") != "discovery", winner.get("text")


def test_the_crash_path_still_returns_every_contract_key() -> None:
    """NEVER RAISES, and the three list keys are present on the DEGRADED path too.

    A contract key that exists on the happy path and vanishes on the crash path is
    how a caller learns to reach for `.get()` and then stops noticing.
    """
    original = workshop_rank.critique_candidates

    async def _explode(**kw):
        raise RuntimeError("scripted explosion inside the loop")

    workshop_rank.critique_candidates = _explode
    try:
        result = _run_stage_b(_ScriptedClient(_script()), SEAM_LABELS)
    finally:
        workshop_rank.critique_candidates = original

    assert result["workshop_fallback"] is True
    for key in ("groups", "discovery", "discovery_not_researched"):
        assert key in result, key
    for key in ("rounds", "loop_born_winners"):
        assert key in result["counts"], key
    json.dumps(result)


def test_candidate_indices_never_collide_across_rounds() -> None:
    """T-15.7-09-05. `run_tournament` RENUMBERS the whole field the moment it sees
    a duplicate index, and a renumber mid-loop would silently detach every carried
    standing — `wins`, `elo`, `byes` and `matches` are all keyed by index."""
    population = [{"index": i} for i in range(5)]
    start = workshop_rank._next_free_index(population)
    assert start == 5
    stamped = workshop_rank._stamp_loop_candidates(
        [{}, {}, {}], start_index=start, born_round=2
    )
    indices = [entry["index"] for entry in stamped]
    assert indices == [5, 6, 7]
    assert set(indices).isdisjoint({p["index"] for p in population})


def test_born_round_is_the_round_the_candidate_first_competes_in() -> None:
    """Criterion 3 (SATURATION) is tested as `born_round == round_no` over the
    winners SELECTED in that round. Selection happens BEFORE evolve inside a
    round, so stamping the WRITING round would make `new_entrants` permanently
    zero and criterion 3 permanently true — a criterion that always passes is not
    a criterion."""
    stamped = workshop_rank._stamp_loop_candidates([{}], start_index=0, born_round=4)
    assert stamped[0]["born_round"] == 4


def test_the_evolve_prompt_carries_the_scoped_rule_not_the_flat_ban() -> None:
    """D-R6. The flat sentence is GONE and BOTH halves of its replacement are
    present. Asserted against the EXPORTED CONSTANTS rather than retyped
    literals, because a retyped literal drifts silently — which is the whole
    reason deleting the old line was dangerous."""
    from nestor_pulse_sdk.pipeline.tribunal import workshop_evolve

    block = workshop_rank._scope_rules_block()
    assert workshop_evolve.MANDATE_SCOPE_LOCK in block
    assert workshop_evolve.DISCOVERY_EVIDENCE_ANCHOR in block
    assert "Do NOT merge two questions into one" not in workshop_rank._EVOLVE_PROMPT
    assert "{scope_rules}" in workshop_rank._EVOLVE_PROMPT


# ===========================================================================
# TASK 2 — the register, the admission gate and the instrumentation.
# ===========================================================================


def _keyed_stage_a(labels, per_question: int = 12):
    """Stage A where every candidate carries a DISTINCT `cluster_key`.

    The KILL split reads the CLUSTERING SHAPE, not the flaw prose, so without a
    cluster key there is no structural signal and nothing is barred — which is
    the deliberate fail-safe, and would make every bar test below vacuous.
    """
    payload = _stage_a(labels, per_question=per_question)
    for candidate in payload["candidates"]:
        candidate["cluster_key"] = f"k{candidate['index']}"
    return payload


def _kill_script(kill_marker: str, **kw):
    """Like `_script`, but KILLs every candidate whose text carries `kill_marker`
    with a flaw naming a DEFECT rather than a restatement."""
    base = _script(**kw)

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            lines = []
            for raw_index, text in rows:
                if kill_marker in text:
                    lines.append(
                        f"{int(raw_index)} | {_KILL} | it is unanswerable in principle"
                    )
                else:
                    lines.append(f"{int(raw_index)} | {_KEEP} | -")
            return "\n".join(lines)
        return base(kind, prompt)

    return respond


def test_a_tournament_loss_can_never_be_expressed_as_a_bar() -> None:
    """D-W4-1, and the enforcement is STRUCTURAL rather than a rule to remember.

    `workshop_register.bar` accepts exactly three causes and "came last" is not
    one of them, so the loop could not bar a loser even by accident. That is what
    keeps `enforce_scope_guard`'s promotion of a below-the-cut candidate working
    after however many rounds of barring (T-15.7-09-02).
    """
    register = workshop_register.new_register()
    stored = workshop_register.bar(
        register, text="a losing question", flaw="came last",
        cause="tournament_loss", round_no=1,
    )
    assert stored is False
    assert register["barred"] == []


def test_a_weak_bars_on_the_second_pass_and_never_on_the_first() -> None:
    """ONE WEAK verdict is a question the workshop has not finished with; TWO is
    one it cannot sharpen. Asserted as two separate steps, because a rule that
    barred on the first pass would read identically at the call site."""
    register = workshop_register.new_register()
    assert workshop_register.note_weak_pass(register, "some question") == 1
    assert workshop_register.note_weak_pass(register, "some question") == 2


def test_the_kill_split_bars_a_defect_and_spares_a_restatement() -> None:
    """The four shapes of `_kill_is_a_restatement`, which is the KILL split.

    The signal is STRUCTURAL — the clustering shape — and never the flaw prose,
    because the flaw clause is model prose in the run's own language and a text
    matcher would silently never fire on a Dutch or French run.
    """
    population = [{"index": 1, "cluster_key": "other"}]
    defect = {"index": 99, "text": "t", "flaw": "unanswerable",
              "cluster_key": "unique-key", "merged_from": []}

    # A DEFECT: no duplicate family anywhere -> it bars.
    assert workshop_rank._kill_is_a_restatement(defect, population) is False

    # A RESTATEMENT: a live candidate shares its cluster -> it does NOT bar.
    shared = dict(defect, cluster_key="shared")
    assert workshop_rank._kill_is_a_restatement(
        shared, [{"index": 1, "cluster_key": "shared"}]
    ) is True

    # It absorbed near-duplicates -> it is a duplicate family -> does NOT bar.
    assert workshop_rank._kill_is_a_restatement(
        dict(defect, merged_from=[3, 4]), population
    ) is True

    # NO CLUSTERING SIGNAL AT ALL -> FAIL SAFE TOWARDS NOT BARRING. An over-eager
    # bar suppresses discovery invisibly; an under-eager one costs one duplicate
    # the clusterer collapses anyway.
    assert workshop_rank._kill_is_a_restatement(
        dict(defect, cluster_key=""), population
    ) is True


def test_a_kill_naming_a_defect_reaches_the_register_end_to_end() -> None:
    """Driven through the REAL stage B, not through the register alone — a bar
    that the register records but that stage B never actually makes is exactly
    the shape of defect that got through Wave 3."""
    client = _ScriptedClient(_kill_script(CQ3, seed=0))
    result = _run_stage_b(client, SEAM_LABELS, payload=_keyed_stage_a(SEAM_LABELS))
    assert result["counts"]["barred"] > 0


def test_the_loop_records_one_metrics_row_per_round_and_enforces_nothing() -> None:
    """D-W4-7. The numbers are RECORDED; nothing is compared against a ceiling.

    Population, spend and lookups are all present per round, and the absence of
    any enforcement is the assertion: an enforced ceiling nobody has measured a
    need for is a knob that will one day truncate a run for no reason.
    """
    client = _ScriptedClient(_script(seed=0))
    result = _run_stage_b(client, SEAM_LABELS, payload=_keyed_stage_a(SEAM_LABELS))

    assert "loop_rounds" in result
    assert len(result["loop_rounds"]) == result["counts"]["rounds"]
    for record in result["loop_rounds"]:
        for key in ("round_no", "candidates_in", "new_candidates", "winners",
                    "weak_winners", "barred", "dropped_as_reproposal",
                    "lookups", "calls", "cost_usd"):
            assert key in record, key
        for value in record.values():
            assert not isinstance(value, float)
    # The whole result is checkpointed by `pipeline.py`.
    json.dumps(result)


def test_the_counts_gained_the_loop_numbers_and_the_docstring_names_them() -> None:
    """Both halves asserted: a counts key nobody documented is a key the next
    reader will not know exists, and a documented key that is not emitted is
    worse."""
    client = _ScriptedClient(_script(seed=0))
    result = _run_stage_b(client, SEAM_LABELS, payload=_keyed_stage_a(SEAM_LABELS))
    doc = workshop_rank.run_workshop_stage_b.__doc__ or ""
    for key in ("rounds", "loop_born_winners", "barred",
                "dropped_as_reproposal", "grounded_lookups", "admitted_angles"):
        assert key in result["counts"], key
        assert key in doc, key
    assert "loop_rounds" in doc


def test_the_discovery_allocation_bound_still_binds_over_admitted_angles() -> None:
    """D-W3-4 is UNCHANGED: at most 5 discovered questions, per-parent cap 3, and
    discovery never borrows from the mandate. The admitted inventions CONTINUE
    that allocation rather than running a second one, and the ceilings are read
    from `discovery_bracket` rather than retyped."""
    taken, _notes = workshop_rank._fill_remaining_discovery_slots(
        [{"parent": "P"} for _ in range(10)], already=[], per_parent={}
    )
    assert len(taken) == discovery_bracket._DISCOVERY_PER_PARENT_CAP

    mixed = ([{"parent": "A"}] * 3) + ([{"parent": "B"}] * 3) + ([{"parent": "C"}] * 3)
    taken, _notes = workshop_rank._fill_remaining_discovery_slots(
        mixed, already=[], per_parent={}
    )
    assert len(taken) <= discovery_bracket._DISCOVERY_MAX_SLOTS

    # Slots orientation already spent are not spent twice.
    taken, _notes = workshop_rank._fill_remaining_discovery_slots(
        mixed, already=[{}] * discovery_bracket._DISCOVERY_MAX_SLOTS, per_parent={}
    )
    assert taken == []


def test_an_admitted_angle_keeps_its_own_text_and_its_admitting_source() -> None:
    """D-W4-2: a discovery candidate's OWN admitting quote and URL ARE its
    enrichment anchor. The angle must NOT be reframed into the orientation
    conflict sentence, which would both discard the question the INVENT move
    wrote and assert it came from orientation, which is false."""
    angle = {
        "text": "Which product categories are legally excluded after 20:00?",
        "source": "discovery",
        "provenance": {
            "quote": "the Act excludes tobacco after 20:00",
            "why": "the brief assumes no category limits",
            "source_url": "https://example.gov/act",
            "resolved_url": "https://example.gov/act",
            "resolution_status": "resolved",
        },
    }
    entry = workshop_rank._conflict_from_admitted(angle, CQ3)
    assert entry["text"] == angle["text"]
    assert entry["parent"] == CQ3
    assert entry["parents"] == [CQ3]
    assert entry["source"] == "discovery"
    assert entry["provenance"]["source_url"] == "https://example.gov/act"
    assert entry["provenance"]["world_says"] == "the Act excludes tobacco after 20:00"
    # `rank` is DELIBERATELY invalid — the caller re-stamps it below every
    # mandate winner, and 0 is a loud placeholder rather than a plausible rank.
    assert entry["rank"] == 0


def test_a_resurrected_candidate_never_reaches_the_register_as_a_bar() -> None:
    """Both critique guards put a killed candidate BACK into `survivors`, and a
    candidate the pipeline chose to keep must never be barred — barring it would
    delete the very coverage the resurrection exists to provide."""
    killed_out: list[dict[str, Any]] = []

    async def _drive():
        return await workshop_rank.critique_candidates(
            candidates=[
                {"index": 0, "text": "only candidate for this question",
                 "parent": CQ1, "parents": [CQ1]},
            ],
            decision_context="ctx",
            audited=_ScriptedClient(
                lambda kind, prompt: "0 | KILL | nothing turns on it"
            ),
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            killed_out=killed_out,
        )

    survivors, _reasons = asyncio.run(_drive())
    # GUARD 1 rescued it — not Guard 2. The candidate carries a parent label, and
    # Guard 1 (the per-client-question rescue) therefore fires first and leaves
    # `survivors` non-empty, so Guard 2's "the population is empty" branch is
    # never reached. Naming the wrong guard here would be the same error plan 08's
    # first Guard 2 test made: GUARD 2 IS ONLY REACHABLE WHEN NO CANDIDATE CARRIES
    # A PARENT LABEL AT ALL. The assertion below holds for either guard, which is
    # why the test is still sound — but a reader chasing Guard 2 would be looking
    # at the wrong branch.
    assert survivors
    # ...and therefore it must NOT be offered to the register as a bar.
    assert killed_out == []


# ===========================================================================
# TASK 3 — THE SEAM SUITE. Section 8's Wave 4 row, ITEM BY ITEM, each as its
# own named test, and each driving the REAL `run_workshop_stage_b` and
# asserting on THE CONTRACT IT RETURNS.
#
# WHY THE END-TO-END FORM IS NON-NEGOTIABLE HERE. Wave 3 shipped 42/42
# verification and 1283 green tests and still carried TWO CRITICALS — a
# prompt-injection channel and a silent deletion of client questions — because
# every plan's own `must_haves` were individually satisfied and both defects
# lived in the SEAMS BETWEEN PLANS. Plan 09 IS that seam. A barred question that
# does not reappear "according to the register" proves nothing; only its absence
# from the RETURNED winner set does.
#
# ONE ITEM CANNOT TAKE THIS FORM, and it is called out rather than quietly
# reshaped: the generation-count item asserts the STAGE A generation prompt,
# which `run_workshop_stage_b` never builds. See
# `test_section8_the_generation_count_appears_in_both_places_the_prompt_states_it`.
# ===========================================================================


def _oracle_script(*, strong_newcomer: bool = False, newcomer_strength: int = 999,
                   generate_rounds: int = 3, new_per_round: int = 6,
                   weak_first_rounds: int = 0, weak_label: str = CQ3):
    """A scripted responder whose JUDGE IS AN ORACLE rather than a coin flip.

    Every candidate text carries `STRENGTH=<n>`; the judge reads both sides and
    always answers the higher one. That makes the tournament DETERMINISTIC and
    makes "did the better question win?" an assertion rather than a hope — the
    random judge in `_script` can only support statements about shape.

    With `strong_newcomer` the generative evolve writes candidates at
    `newcomer_strength`, which is above every seed candidate, so a candidate born
    in a LATE round is the best in the field and must finish in the top N.
    """
    state: dict[str, int] = {"round": 0, "generate": 0}

    def _strength(text: str) -> int:
        found = re.search(r"STRENGTH=(\d+)", text or "")
        return int(found.group(1)) if found else 0

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            if rows and int(rows[0][0]) == 0:
                state["round"] += 1
            lines = []
            for raw_index, text in rows:
                if state["round"] <= weak_first_rounds and weak_label in text:
                    verdict, flaw = _WEAK, "too broad to answer as it stands"
                else:
                    verdict, flaw = _KEEP, "-"
                lines.append(f"{int(raw_index)} | {verdict} | {flaw}")
            return "\n".join(lines)

        if kind == "judge":
            lines = []
            for match in re.finditer(
                r"^\s*(\d+)\s*\|\s*A:\s*(.*?)\s*\|\s*B:\s*(.*)$", prompt, re.M
            ):
                index, side_a, side_b = match.group(1), match.group(2), match.group(3)
                winner = "A" if _strength(side_a) >= _strength(side_b) else "B"
                lines.append(f"{int(index)} | {winner} | the stronger question")
            return "\n".join(lines) or "0 | A | the stronger question"

        if kind == "sharpen":
            # THE SHARPENER MUST PRESERVE `STRENGTH=`. It rewrites every winner's
            # text, and a rewrite that dropped the marker would make the oracle's
            # verdict unreadable in the RETURNED winners — the assertion would
            # then be about the sharpener, not about the tournament.
            out = []
            for line in re.findall(r"^(\d+) \| (.*?)(?: \| |$)", prompt, re.M):
                index, text = int(line[0]), line[1]
                out.append(
                    f"{index} | sharpened {text} | LANGS: nl,en"
                )
            body = "\n".join(out)
            return f"{_START}\n{body}\n{_END}"

        if kind == "generate":
            state["generate"] += 1
            if state["generate"] > generate_rounds:
                return f"{_START}\n{_END}"
            strength = newcomer_strength if strong_newcomer else 5
            lines = [
                f"{k} | COMBINE | 0,1 | loop-born question {state['generate']}-{k} "
                f"STRENGTH={strength} | LANGS: nl,en"
                for k in range(new_per_round)
            ]
            return f"{_START}\n" + "\n".join(lines) + f"\n{_END}"

        return "focus the next round on cost evidence"

    return respond


def _strength_stage_a(labels, per_question: int = 12):
    """Stage A whose candidate texts carry an explicit, distinct `STRENGTH=`.

    Seed strengths run 10..10+per_question, all BELOW `_oracle_script`'s
    newcomer strength, so a late newcomer reaching the top N cannot be an
    artefact of a tie.
    """
    payload = _keyed_stage_a(labels, per_question=per_question)
    for position, candidate in enumerate(payload["candidates"]):
        candidate["text"] = f"{candidate['text']} STRENGTH={10 + position}"
    return payload


# --------------------------------------------------------------------------
# § 8 Wave 4, item 1 — "loop exits on saturation before the cap"
# --------------------------------------------------------------------------
def test_section8_the_loop_exits_on_saturation_before_the_cap() -> None:
    """A healthy brief converges on its OWN criteria and never reaches the cap.

    THE EXIT ROUND IS ASSERTED AS A RANGE AND NEVER AS A CONSTANT. Evolve runs at
    temperature 1.0: the design harness exited at rounds 4, 6 and 6 on three runs
    of ONE configuration, and this file's scripted stubs measured [3, 3, 3, 3, 3,
    4] over six seeds. A hard round number is a flaky test by construction; what
    is actually guaranteed is convergence strictly INSIDE the cap.

    The lower bound matters as much as the upper one. A run that exited in round
    1 would satisfy "before the cap" while proving nothing about the loop at all,
    so `>= 2` is asserted separately and for that reason.
    """
    cap = workshop_loop._LOOP_MAX_ROUNDS
    observed = []
    for seed in range(6):
        result = _run_stage_b(_ScriptedClient(_script(seed=seed)), SEAM_LABELS)
        observed.append(result["counts"]["rounds"])
        # It exited on the CRITERIA, so it carries no cap degradation sentence.
        cap_sentences = [
            reason for reason in result["degradation_reasons"]
            if "round cap" in reason or "could not be sharpened" in reason
        ]
        assert not cap_sentences, (seed, cap_sentences)

    assert all(2 <= round_no < cap for round_no in observed), observed
    # SATURATION is the criterion that closes the loop: the last round it ran
    # added no NEW candidate to the winner set. Read off the returned
    # instrumentation rather than re-derived, so the assertion is about what the
    # run recorded.
    assert len(result["loop_rounds"]) == result["counts"]["rounds"]


# --------------------------------------------------------------------------
# § 8 Wave 4, item 2 — "a resurrected candidate does not satisfy QUALITY"
# --------------------------------------------------------------------------
def test_section8_a_resurrected_candidate_does_not_satisfy_criterion_two() -> None:
    """CRITERION 2 IS QUALITY, and until 2026-07-31 three documents said 1.

    That inversion mattered: criterion 1 is COVERAGE, and excluding a resurrected
    candidate from coverage would break the exact guarantee resurrection exists to
    provide. Driven END TO END — a critique that kills everything, through the
    never-drop guard that resurrects, through to a loop that REFUSES TO EXIT and
    ships at the cap saying why.

    THIS IS GUARD 1, the per-client-question rescue, and it is named because the
    distinction is a live trap: Guard 2 is only reachable when NO candidate
    carries a parent label, so any "Guard 2" test built on parented candidates is
    vacuous. Every candidate here has a parent, so Guard 1 fires and Guard 2 is
    never entered.
    """
    def _kill_everything(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            return "\n".join(
                f"{int(i)} | {_KILL} | nothing about the decision turns on it"
                for i, _text in rows
            )
        return _script()(kind, prompt)

    result = _run_stage_b(_ScriptedClient(_kill_everything), SEAM_LABELS)

    # It never satisfied criterion 2, so it ran the whole way to the cap...
    assert result["counts"]["rounds"] == workshop_loop._LOOP_MAX_ROUNDS
    # ...and it SHIPPED, saying so in a sentence a human reads (D-12: degraded
    # means honest, not broken).
    assert result["winners"]
    # MATCHED ON THE SENTENCE'S OWN PROVENANCE, not on the word "resurrected" —
    # which is the code's vocabulary and appears nowhere in the operator-facing
    # sentence `_reason_cap_with_resurrected` actually returns.
    reasons = " ".join(result["degradation_reasons"])
    assert "coverage guard" in reasons, result["degradation_reasons"]

    # AND CRITERION 1 STILL HELD. Every client question is still covered — which
    # is the half that the corrected numbering protects.
    covered = set()
    for winner in result["winners"]:
        covered.update(winner.get("parents") or [])
    assert set(SEAM_LABELS) <= covered, covered


# --------------------------------------------------------------------------
# § 8 Wave 4, item 3 — "barred questions do not reappear"
# --------------------------------------------------------------------------
_BARRED_MARKER = "number 3"
_REWORDING = "REWORDEDBARRED"


def _rewording_script(*, merge_the_rewording: bool):
    """KILL one candidate as a DEFECT, then re-propose a REWORDING of it.

    `merge_the_rewording` is the NON-VACUITY CONTROL and the reason this helper
    takes a parameter at all. The semantic drop only fires when the clusterer
    puts the rewording in the same cluster as the barred SHADOW; with the
    clusterer answering "every candidate is its own singleton", the rewording
    survives. Running BOTH ways in one test proves the rewording would have
    become a winner and that THE BAR is what removed it — rather than it having
    been absent for some unrelated reason.

    THE JUDGE IS THE ORACLE, NOT THE COIN FLIP, and that is what makes the
    control decisive. The rewording carries the highest `STRENGTH=` in the field,
    so on the control run it MUST take a slot; with a random judge its absence
    would be explainable as "it simply lost", and the control would prove
    nothing.
    """
    base = _oracle_script(weak_first_rounds=2, generate_rounds=3)
    state: dict[str, int] = {"round": 0}

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            if rows and int(rows[0][0]) == 0:
                state["round"] += 1
            lines = []
            for raw_index, text in rows:
                if _BARRED_MARKER in text and CQ1 in text:
                    # A DEFECT, not a restatement — so the register bars it.
                    lines.append(
                        f"{int(raw_index)} | {_KILL} | it is unanswerable in principle"
                    )
                elif state["round"] <= 2 and CQ3 in text:
                    # THE LOOP HAS TO ACTUALLY LOOP FOR THIS TEST TO MEAN
                    # ANYTHING. Evolve runs AFTER selection, so a run that exits
                    # in round 1 writes the rewording and stops before it can
                    # ever compete — the winner-set assertion would then pass
                    # because the candidate was never a candidate. Keeping one
                    # client question WEAK for two rounds keeps criterion 2
                    # failing and the loop running.
                    lines.append(
                        f"{int(raw_index)} | {_WEAK} | too broad to answer as it stands"
                    )
                else:
                    lines.append(f"{int(raw_index)} | {_KEEP} | -")
            return "\n".join(lines)

        if kind == "cluster":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            lines = []
            for raw_index, text in rows:
                related = _BARRED_MARKER in text or _REWORDING in text
                if merge_the_rewording and related:
                    lines.append(f"{int(raw_index)} | 777")
                else:
                    lines.append(f"{int(raw_index)} | {900 + int(raw_index)}")
            return "\n".join(lines)

        if kind == "generate":
            # A REWORDING, never the same string — that is the whole point. A
            # string comparison cannot enforce "or a rewording of it", which is
            # why D-W4-1 names `cluster_candidates` rather than a comparison.
            return (
                f"{_START}\n"
                f"0 | SPECIALISE | 0 | {_REWORDING} a differently worded take on "
                f"the very same question STRENGTH=999 | LANGS: nl,en\n"
                f"{_END}"
            )

        return base(kind, prompt)

    return respond


def test_section8_a_barred_question_does_not_reappear_as_a_winner() -> None:
    """D-W4-1 END TO END, asserted on the WINNER SET and never on the register.

    A question barred in round 1 is re-proposed as a REWORDING by the scripted
    evolve, and must not be a winner at the end. That exercises the SEMANTIC
    DROP — the barred questions travel through the clusterer as shadow members —
    rather than a string comparison, which could not enforce a rewording ban at
    all.

    A bar that the register records but that stage B never actually acts on is
    precisely the shape of defect that got through Wave 3's 42/42 verification.
    """
    payload = _strength_stage_a(SEAM_LABELS)

    dropped = _run_stage_b(
        _ScriptedClient(_rewording_script(merge_the_rewording=True)),
        SEAM_LABELS,
        payload=copy.deepcopy(payload),
    )
    # The bar was really made...
    assert dropped["counts"]["barred"] > 0
    # ...the semantic drop really fired...
    assert dropped["counts"]["dropped_as_reproposal"] > 0
    # ...and the REWORDING is not a winner.
    assert not [
        w for w in dropped["winners"] if _REWORDING in str(w.get("text") or "")
    ], [w.get("text") for w in dropped["winners"]]

    # THE NON-VACUITY CONTROL. Same script, same bar, but a clusterer that merges
    # nothing: the rewording survives all the way into the winner set. Without
    # this, an assertion that the rewording is absent would pass just as happily
    # if the evolve step had never proposed it.
    kept = _run_stage_b(
        _ScriptedClient(_rewording_script(merge_the_rewording=False)),
        SEAM_LABELS,
        payload=copy.deepcopy(payload),
    )
    assert [
        w for w in kept["winners"] if _REWORDING in str(w.get("text") or "")
    ], "the control run never produced the rewording, so the test above is vacuous"


# --------------------------------------------------------------------------
# § 8 Wave 4, item 4 — "losers remain promotable"
# --------------------------------------------------------------------------
def _drop_one_questions_winners(label: str):
    """A `select_winners` that returns no winner for `label`, keeping the rest.

    WHY A COLLABORATOR IS PINNED HERE AND NOWHERE ELSE IN THIS SUITE. The winner
    selection guarantees a FLOOR of five per client question, so on any honest
    script every client question already has a winner and `enforce_scope_guard`'s
    repair ladder is simply never entered. Pinning selection is the only way to
    reach the repair at all — and it is an INPUT CONDITION, exactly like the
    scripted LLM responses: the assertion below is still made on the contract the
    REAL `run_workshop_stage_b` returns, and every other step (the tournament,
    the ten rounds of barring, the scope guard, the tail) is the real one.
    """
    original = workshop_loop.select_winners

    def _patched(ranked, **kw):
        winners, below = original(ranked, **kw)
        kept = [w for w in winners if label not in (w.get("parents") or [])]
        moved = [w for w in winners if label in (w.get("parents") or [])]
        return kept, list(moved) + list(below)

    return original, _patched


def test_section8_losers_remain_promotable_after_ten_rounds_of_barring() -> None:
    """T-15.7-09-02, END TO END and after the loop has barred all it is going to.

    An over-eager bar deletes a client question's coverage INVISIBLY, and the
    structural protection is that a tournament loss can never be expressed as a
    bar. This asserts the consequence rather than the mechanism: after ten rounds
    of barring, a client question left with no winner is repaired by PROMOTING a
    below-the-cut candidate out of the FULL ranked list — not by injecting the
    client's question text verbatim.

    THE DISTINCTION IS THE WHOLE TEST. A verbatim injection also "covers" the
    question, so a test that only asserted coverage would pass just as well
    against a scope guard whose promotion ladder had stopped working — and a
    verbatim client question is raw brief text where a promotion is a real,
    tournament-ranked sub-question.
    """
    original, patched = _drop_one_questions_winners(CQ3)
    workshop_loop.select_winners = patched
    try:
        result = _run_stage_b(
            _ScriptedClient(_rewording_script(merge_the_rewording=False)),
            SEAM_LABELS,
            payload=_strength_stage_a(SEAM_LABELS),
        )
    finally:
        workshop_loop.select_winners = original

    # Ten rounds, and they really were rounds that barred.
    assert result["counts"]["rounds"] == workshop_loop._LOOP_MAX_ROUNDS
    assert result["counts"]["barred"] > 0

    repaired = [w for w in result["winners"] if CQ3 in (w.get("parents") or [])]
    assert repaired, "the starved client question was not repaired at all"

    # IT IS A PROMOTION. `_verbatim_winner` is a fixed 12-key shape carrying
    # `source: "verbatim"` and the sentinel `index: -1`; a promoted candidate is a
    # copy of a real ranked entry, so it has a real index and a tournament rank.
    promoted = [w for w in repaired if w.get("source") != "verbatim"]
    assert promoted, [
        (w.get("source"), w.get("index"), w.get("text")) for w in repaired
    ]
    winner = promoted[0]
    assert winner.get("index", -1) >= 0, winner
    assert isinstance(winner.get("rank"), int) and winner["rank"] >= 1, winner
    # ...and it carries a real sub-question, not the client's own question text.
    assert str(winner.get("text") or "") != f"Client question: {CQ3}"
    assert winner.get("langs"), winner


# --------------------------------------------------------------------------
# § 8 Wave 4, item 5 — "a strong newcomer entering in a late round still
# reaches the top N under the catch-up schedule"
# --------------------------------------------------------------------------
_LATE_ENTRANT = "LATEENTRANT"


def _lone_late_newcomer_script(*, entry_round: int = 3):
    """EXACTLY ONE strong candidate, born in a LATE round, against a settled field.

    THE COUNT IS THE WHOLE POINT AND THIS TEST WAS REWRITTEN TO GET IT RIGHT.
    An earlier version of this test let the generative evolve write SIX
    999-strength newcomers EVERY round. It passed — and it passed for the wrong
    reason: a field flooded with top-strength entrants puts one of them in the
    top N no matter what the match schedule does. Measured, `catch_up_matches ->
    0` did not move that test at all, which means it was asserting nothing about
    D-W4-3.

    With ONE newcomer entering in round 3 the schedule becomes load-bearing and
    the mutant is caught: the late entrant reaches the winner set on the baseline
    and does NOT reach it with the catch-up removed.
    """
    state: dict[str, int] = {"round": 0, "generate": 0}

    def _strength(text: str) -> int:
        found = re.search(r"STRENGTH=(\d+)", text or "")
        return int(found.group(1)) if found else 0

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            if rows and int(rows[0][0]) == 0:
                state["round"] += 1
            lines = []
            for raw_index, text in rows:
                # One question stays WEAK for most of the run, which is what
                # keeps criterion 2 failing and the loop turning long enough for
                # a round-3 entrant to exist at all.
                if CQ3 in text and state["round"] <= 8:
                    lines.append(
                        f"{int(raw_index)} | {_WEAK} | too broad to answer as it stands"
                    )
                else:
                    lines.append(f"{int(raw_index)} | {_KEEP} | -")
            return "\n".join(lines)

        if kind == "judge":
            lines = []
            for match in re.finditer(
                r"^\s*(\d+)\s*\|\s*A:\s*(.*?)\s*\|\s*B:\s*(.*)$", prompt, re.M
            ):
                side = (
                    "A"
                    if _strength(match.group(2)) >= _strength(match.group(3))
                    else "B"
                )
                lines.append(f"{int(match.group(1))} | {side} | the stronger question")
            return "\n".join(lines) or "0 | A | the stronger question"

        if kind == "sharpen":
            out = []
            for line in re.findall(r"^(\d+) \| (.*?)(?: \| |$)", prompt, re.M):
                out.append(f"{int(line[0])} | sharpened {line[1]} | LANGS: nl,en")
            return f"{_START}\n" + "\n".join(out) + f"\n{_END}"

        if kind == "generate":
            state["generate"] += 1
            if state["generate"] != entry_round:
                return f"{_START}\n{_END}"
            return (
                f"{_START}\n0 | COMBINE | 0,1 | {_LATE_ENTRANT} the one late "
                f"entrant STRENGTH=999 | LANGS: nl,en\n{_END}"
            )

        return "focus the next round on cost evidence"

    return respond


def test_section8_a_strong_late_newcomer_still_reaches_the_top_n() -> None:
    """D-W4-3 AT THE SEAM. Plan 15.7-08 asserts this at the tournament level;
    this asserts it survives a loop that adds candidates round after round.

    The mechanism is the SCHEDULE and not the sort: the standing sorts by
    `(-wins, -elo, index)`, so a newcomer's disadvantage is FEWER MATCHES and
    therefore FEWER WINS — which is exactly why D-R11's median Elo seed is inert
    (median-seed and flat-1200 give byte-identical output) and why
    `catch_up_matches` is what actually works.

    Driven with an ORACLE judge so the entrant's strength is decisive rather than
    probabilistic: it carries the highest `STRENGTH=` in the field, so if it does
    not reach the top N then the make-up matches are what failed.
    """
    result = _run_stage_b(
        _ScriptedClient(_lone_late_newcomer_script()),
        SEAM_LABELS,
        payload=_strength_stage_a(SEAM_LABELS),
    )

    # It really did loop long enough for a round-3 entrant to exist.
    assert result["counts"]["rounds"] >= 3, result["counts"]["rounds"]

    entrant = [
        w for w in result["winners"]
        if _LATE_ENTRANT in str(w.get("text") or "")
    ]
    assert entrant, (
        "the best question in the field entered late and never reached the top N"
    )
    # It is genuinely a LATE arrival, not a seed candidate that happened to match.
    assert (entrant[0].get("born_round") or 0) >= 2, entrant[0]
    assert result["counts"]["loop_born_winners"] >= 1


# --------------------------------------------------------------------------
# § 8 Wave 4, item 6 — "zero WEAK winners — prefer-KEEP is applied"
# --------------------------------------------------------------------------
def _half_weak_script(**kw):
    """Half of every question's candidates are WEAK FOREVER, half are KEEP.

    A SURPLUS OF KEEP IS WHAT MAKES THIS TEST MEAN ANYTHING. With six KEEP
    candidates per question against a floor of five, prefer-KEEP has a real
    choice at every slot; with fewer KEEP than slots the winner set would be
    WEAK-free only because there was nothing else to take, and the assertion
    would hold without the rule existing.
    """
    base = _script(**kw)

    def respond(kind: str, prompt: str) -> str:
        if kind == "critique":
            rows = re.findall(r"^\s*(\d+)\s*\|\s*(.*)$", prompt, re.M)
            lines = []
            for raw_index, text in rows:
                found = re.search(r"number (\d+)", text)
                weak = found is not None and int(found.group(1)) >= 6
                if weak:
                    lines.append(
                        f"{int(raw_index)} | {_WEAK} | too broad to answer as it stands"
                    )
                else:
                    lines.append(f"{int(raw_index)} | {_KEEP} | -")
            return "\n".join(lines)
        return base(kind, prompt)

    return respond


def test_section8_zero_weak_winners_when_keep_and_weak_both_exist_in_surplus() -> None:
    """D-W4-5's prefer-KEEP, asserted on the RETURNED winner set.

    The measured configuration produces 17 winners with NONE weak. Prefer-KEEP is
    what does it: a rank-9 KEEP is taken over a rank-4 WEAK when a slot is being
    filled, because a WEAK winner is a paid research question the workshop itself
    said was not sharp enough.
    """
    result = _run_stage_b(
        _ScriptedClient(_half_weak_script(seed=0)),
        SEAM_LABELS,
        payload=_stage_a(SEAM_LABELS),
    )

    weak = [
        w for w in result["winners"]
        if str(w.get("critique") or "").upper() == _WEAK
        and not w.get("cross_cutting")
    ]
    assert not weak, [(w.get("text"), w.get("critique")) for w in weak]

    # NON-VACUITY: the WEAK candidates really existed and really were available
    # to be chosen. Without this the run could have been all-KEEP by accident.
    assert result["counts"]["ranked"] > len(result["winners"])


# --------------------------------------------------------------------------
# § 8 Wave 4, item 7 — "the raised generation count appears in BOTH places the
# prompt states it"
# --------------------------------------------------------------------------
def test_section8_the_generation_count_appears_in_both_places_the_prompt_states_it() -> None:
    """THE ONE § 8 ITEM THAT CANNOT BE DRIVEN THROUGH `run_workshop_stage_b`.

    This is stated rather than worked around. The generation prompt is built by
    `workshop.generate_candidates`, which belongs to STAGE A: stage B receives an
    already-generated candidate list in its `stage_a` payload and never builds a
    generation prompt at all. Driving it through stage B is therefore impossible,
    and dressing it up as a stage-B test would be a test that asserts nothing.
    So it drives the REAL `generate_candidates` and asserts on the REAL rendered
    prompt.

    The spec names both sites explicitly — the `Output EXACTLY {n} lines`
    sentence and the `<your {n} lines go here>` placeholder — and warns that both
    must change together. In THIS repository they cannot drift: the template
    writes `{n}` twice but there is exactly one `.format(...)` call feeding it
    with one `n=` keyword. That is asserted here as a PROPERTY of the rendered
    text, so the day someone splits it into two constants this fails.
    """
    from nestor_pulse_sdk.pipeline.tribunal import workshop as _workshop

    seen: list[str] = []

    class _PromptCapture:
        async def anthropic_messages(self, *, run_id, tenant_id, model, messages,
                                     max_tokens=None, audit_out=None, **kw):
            for message in messages:
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        seen.append(block.get("text") or "")
            return types.SimpleNamespace(
                content=[types.SimpleNamespace(type="text", text="")],
                stop_reason="end_turn",
            )

        async def gemini_generate(self, *, run_id, tenant_id, model, contents,
                                  audit_out=None, **kw):
            seen.append(contents if isinstance(contents, str) else str(contents))
            return types.SimpleNamespace(text="", candidates=None)

    asyncio.run(_workshop.generate_candidates(
        questions=[{"label": CQ1, "text": f"Client question: {CQ1}"}],
        orientations=[],
        brief_context="Should the client roll out shop-in-shop coffee?",
        audited=_PromptCapture(),
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    ))

    # SELECTED ON THE CANDIDATE OUTPUT LINE, which only this prompt contains.
    # The ASK-SPLIT prompt that runs first shares both "lines go here" AND
    # "between the two sentinels", so either of those would have asserted the
    # generation count against the wrong prompt — and the ask-split prompt states
    # no candidate count at all, so the test would simply have been wrong.
    generation = [p for p in seen if "CANDIDATE: <" in p and "| PARENT:" in p]
    assert generation, "the candidate generation prompt was never rendered"
    prompt = generation[0]

    count = _workshop._CANDIDATES_PER_QUESTION
    assert f"Output EXACTLY {count} lines" in prompt, prompt[:400]
    assert f"<your {count} lines go here>" in prompt, prompt[:400]

    # AND THE PARSE-SIDE BOUND MUST STAY ABOVE THE GENERATION COUNT. "Raise
    # generation to twelve and leave the cap at ten" silently halves the measured
    # selection ratio with nothing in the output saying so — one logical value
    # with two authorities, only one of which got updated.
    assert _workshop._CANDIDATES_PER_QUESTION_MAX > count


# --------------------------------------------------------------------------
# THE WHOLE-PHASE SHAPE — and the last hop, which is the seam plan 15.7-01
# opened and this is where it is proven closed.
# --------------------------------------------------------------------------
def test_the_whole_phase_shape_three_questions_seventeen_winners_reach_a_provider() -> None:
    """3 client questions in, 17 winners out, none WEAK, ALL SEVENTEEN dispatched.

    This is the validated `exp11` configuration end to end: a floor of 5 winners
    per client question plus 2 cross-cutting, prefer-KEEP applied, converging
    inside the cap — and then the hop nothing else in this phase asserts, through
    `research_division.divide` to the angles a paid provider is actually sent.

    THAT LAST HOP IS THE POINT. Three separate downstream clips could each
    truncate the winner set after stage B had already produced a correct 17, and
    every plan in this phase would still read green: a floor that is quietly cut
    to 15 on the way to dispatch delivers nothing. The assertion is therefore
    about the ANGLES, not about the winner list.
    """
    from nestor_pulse_sdk.pipeline.tribunal import research_division

    result = _run_stage_b(_ScriptedClient(_script(seed=0)), SEAM_LABELS)
    winners = result["winners"]

    # -- the shape stage B returns
    assert len(winners) == 17, len(winners)
    assert not [
        w for w in winners
        if str(w.get("critique") or "").upper() == _WEAK and not w.get("cross_cutting")
    ]
    # NOT A COUNT. `_CROSS_CUTTING_SLOTS` reserves 2 SLOTS; it does not bound how
    # many winners carry the flag, because a cross-cutting candidate can also win
    # a per-question floor slot on merit. Measured over 12 seeds of this same
    # script the count runs 0..8 — `== 2` was a hard number on a value that was
    # never pinned, and it only ever read 2 because clustering was inert and five
    # of every six loop-born candidates were being silently deleted (CR-02).
    # The slot arithmetic is pinned where it can be isolated, on hand-built pools:
    # `test_select_winners_returns_seventeen_...` and
    # `test_select_winners_recognises_a_two_label_span_as_cross_cutting`.
    #
    # WHAT THIS TEST CAN PIN AND NOTHING ELSE CAN: that a two-client-question span
    # is EARNED. `cluster_candidates` unions `parents` across merged members, and
    # since CR-02 that union is live for loop-born candidates for the first time.
    # An over-merge would show up here as a winner claiming two client questions
    # with no provenance for the second — inflating cross-cutting AND losing
    # per-question specificity. That is the regression worth a test.
    for w in winners:
        parents = w.get("parents") or []
        assert parents, w.get("text")
        assert set(parents) <= set(SEAM_LABELS) | {workshop_loop._DISCOVERY_PARENT}, parents
        if len([p for p in parents if p in SEAM_LABELS]) >= 2:
            # a near-duplicate collapse, or an evolve join — never nowhere
            assert w.get("merged_from") or w.get("source_indices"), (w.get("index"), parents)
    for w in winners:
        if w.get("cross_cutting"):
            assert workshop_loop._is_cross_cutting(w, SEAM_LABELS), w.get("parents")
    # NON-VACUITY: the traceability rule above is not satisfied by everything
    # simply being cross-cutting.
    assert [w for w in winners
            if len([p for p in (w.get("parents") or []) if p in SEAM_LABELS]) == 1]
    # A floor of five per client question, counted on the parents union so a
    # cross-cutting winner counts for both questions it spans.
    for label in SEAM_LABELS:
        covering = [w for w in winners if label in (w.get("parents") or [])]
        assert len(covering) >= 5, (label, len(covering))
    assert result["counts"]["rounds"] < workshop_loop._LOOP_MAX_ROUNDS

    # -- and the last hop: every one of the 17 reaches a provider
    angles = research_division.divide(
        {
            "deep_research_prompt": "Should the client roll out shop-in-shop coffee?",
            "focus_areas": [],
        },
        winners=winners,
        groups=result["groups"],
    )
    assert angles, "no angle was dispatched at all"
    assert {str(a.get("provider") or "") for a in angles} == set(
        research_division._D6_STREAMS
    )

    dispatched = " ".join(str(a.get("query") or "") for a in angles)
    missing = [
        w.get("text") for w in winners
        if str(w.get("text") or "")[:60] not in dispatched
    ]
    assert not missing, (
        f"{len(missing)} of {len(winners)} winners never reached a provider "
        f"query: {missing}"
    )
