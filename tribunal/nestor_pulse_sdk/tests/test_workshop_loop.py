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

from nestor_pulse_sdk.pipeline.tribunal import workshop_loop
from nestor_pulse_sdk.pipeline.tribunal.workshop_loop import (
    catch_up_matches,
    tournament_rounds,
)


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
