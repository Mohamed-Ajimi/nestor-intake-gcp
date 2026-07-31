"""Wave 4's loop arithmetic — every piece of it that can be a PURE function.

WHY THIS MODULE EXISTS AS A SEPARATE FILE, AND WHY IT IMPORTS NOTHING FROM
`nestor_pulse_sdk`. Two reasons, and both of them are load-bearing:

  1. `workshop_rank` will import THIS module. The reverse import would therefore
     be circular. Keeping the dependency one-way is not tidiness, it is the only
     arrangement that works.
  2. Being stdlib-only is what makes this module DRIVABLE. The development
     machine has no pytest, no Docker and no `python3` — only a stdlib-only
     bundled interpreter. A module that reaches nothing outside the standard
     library can be imported and driven over hundreds of cases in seconds on
     that interpreter, which is exactly how phase 15.6 proved its own work and
     how the Wave 4 design was measured in the first place.

THE POINT OF SEPARATING THE ARITHMETIC AT ALL. An 11-experiment local harness
replayed the real V-01 run and measured this loop end to end. That harness
proved the DESIGN converges. It proved nothing about any implementation. The
arithmetic is pulled out here so the implementation can be driven over the same
cases the design was, instead of being argued about inside an async LLM loop
that costs money to run and cannot run on this machine at all.

TWO INVARIANTS EVERY FUNCTION IN THIS FILE HOLDS:

  * NO FUNCTION HERE RAISES. Model-authored candidate text arrives here as data
    — untrusted `text`, `flaw` and `parent` values — and a pure helper that can
    throw on a hostile shape is a denial-of-service channel in a pipeline that
    has already paid for its LLM calls. Every function coerces defensively and
    returns a sane empty answer rather than propagating an exception.
  * NO FUNCTION HERE MAKES A CALL. No network, no model, no clock, no random.
    Same inputs, same outputs, always. That is what makes the tests meaningful.

WHAT THIS MODULE DELIBERATELY DOES NOT OWN. `workshop_rank.winner_count` — the
`min(15, max(10, ceil(0.35 x C)))` cut — IS NOT DUPLICATED HERE. `select_winners`
takes a `default_cut` ARGUMENT and the caller passes `winner_count(...)` into it.
Duplicating that formula would be the single-value-two-authorities defect this
phase exists to stop repeating. Likewise the env knob
`NESTOR_TRIBUNAL_WORKSHOP_ROUNDS` stays in `workshop_rank`; it arrives here as
`tournament_rounds(..., override=...)`. This module owns the FORMULA;
`workshop_rank` owns the OVERRIDE.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Optional, Sequence

# ---------------------------------------------------------------------------
# The critique verdict vocabulary, RE-DECLARED rather than imported.
#
# These three literals are `workshop_rank._KEEP` / `_WEAK` / `_KILL`. They are
# copied here ON PURPOSE and the reason is the module docstring above:
# `workshop_rank` imports THIS module, so importing it back would be circular.
# Three string constants is the cheapest possible price for a one-way
# dependency, and the values are a stable published vocabulary rather than a
# tunable.
# ---------------------------------------------------------------------------
_KEEP = "KEEP"
_WEAK = "WEAK"
_KILL = "KILL"

# ---------------------------------------------------------------------------
# `discovery_bracket.DISCOVERY_PARENT`, re-declared for the identical reason.
# A discovery candidate carries this sentinel instead of a client-question label
# because it did not come from one.
# ---------------------------------------------------------------------------
_DISCOVERY_PARENT = "__discovery__"


def _env_int(name: str, default: int) -> int:
    """Read an int env knob, falling back to `default` on anything unusable.

    A garbled env value must NOT raise at import time. A module that fails to
    import takes the whole worker down at boot, which is a far worse outcome
    than quietly running on the documented default — and the default is the
    measured configuration, not a guess.
    """
    try:
        return int(str(os.environ.get(name, default)).strip())
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Tunables. One comment per number saying what the number is FOR.
#
#   _TOURNAMENT_ROUNDS_MIN  the FLOOR on Swiss rounds inside one loop round. 6,
#                           because D-R9 requires every candidate to play >= 5-6
#                           matches within a round now that Elo persists across
#                           rounds. At the shipped 4 over 17 candidates each
#                           candidate got 3.76 matches and the ties were real.
#   _TOURNAMENT_ROUNDS_MAX  the CEILING. 10. A round is a batch of flash calls;
#                           the whole measured 4-round tournament was 6 calls at
#                           ~$0.00, so this is a runaway guard, not a budget.
#   _LOOP_MAX_ROUNDS        the hard cap on LOOP rounds (D-W4-6 criterion 4). 10.
#                           A CEILING, NOT A TARGET: all three measured global
#                           configurations exited on the criteria at rounds 4, 6
#                           and 9, well inside it.
#   _FLOOR_PER_QUESTION     research questions guaranteed per client question. 5,
#                           by operator ruling 2026-07-30.
#   _CROSS_CUTTING_SLOTS    slots reserved for questions spanning two client
#                           questions. 2. Cross-question synthesis is where the
#                           best measured output came from, and it is exactly
#                           what per-question brackets made impossible.
# ---------------------------------------------------------------------------
_TOURNAMENT_ROUNDS_MIN = _env_int("NESTOR_TRIBUNAL_WORKSHOP_ROUNDS_MIN", 6)
_TOURNAMENT_ROUNDS_MAX = _env_int("NESTOR_TRIBUNAL_WORKSHOP_ROUNDS_MAX", 10)
_LOOP_MAX_ROUNDS = _env_int("NESTOR_TRIBUNAL_WORKSHOP_LOOP_ROUNDS", 10)
_FLOOR_PER_QUESTION = _env_int("NESTOR_TRIBUNAL_WORKSHOP_FLOOR_PER_Q", 5)
_CROSS_CUTTING_SLOTS = _env_int("NESTOR_TRIBUNAL_WORKSHOP_CROSS_SLOTS", 2)


def _safe_int(value: Any, default: int = 0) -> int:
    """Coerce to a plain `int` or hand back `default`. Never raises.

    `bool` is excluded explicitly: `isinstance(True, int)` is True in Python, and
    a `True` leaking into a match count or a round number would read as 1 while
    being the wrong TYPE for a value that indexes a schedule.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _ceil_log2(n: int) -> int:
    """`ceil(log2(n))` in pure integer arithmetic, for `n >= 1`.

    `(n - 1).bit_length()` is exactly this value and involves no floats at all.
    `math.log2` would be correct for the sizes this engine sees, but a round
    count that is derived through a float is a round count that can differ by
    one on some other machine, and determinism is the whole reason the pairing
    and standing code is written the way it is.
    """
    if n <= 1:
        return 0
    return (n - 1).bit_length()


def tournament_rounds(n_candidates: Any, *, override: Any = 0) -> int:
    """How many Swiss rounds to run for a field of `n_candidates`. D-R9.

    DERIVED FROM THE FIELD, NOT HARDCODED, and that is the entire point. The
    shipped `workshop_rank._TOURNAMENT_ROUNDS = 4` is a fixed number, and over 17
    candidates it gives each candidate only **3.76 matches**. The measurement
    harness reproduced V-01's exact symptom from that: **three candidates
    finishing at Elo exactly 1200.00 with 2 wins each**, straddling the top-10
    cut, so one of them lost its research slot to **INDEX ORDER**. Carried Elo
    plus 5 Swiss rounds plus the catch-up schedule below eliminated the ties
    entirely — zero candidates at exactly 1200 in any round, and rank 10 vs 11
    became a decision by Elo (1214 vs 1200) instead of by index.

    WHY DERIVED RATHER THAN JUST A BIGGER CONSTANT: the population GROWS every
    loop round. A fixed number, however well chosen today, silently
    under-separates again the moment it does — which is precisely how the
    shipped 4 became wrong without anyone changing it.

    READ THIS TOGETHER WITH `catch_up_matches`, NOT SEPARATELY. D-R9 makes
    D-R11's problem WORSE: more rounds give incumbents more matches and therefore
    more WINS, and wins is the PRIMARY sort key in the standing
    (`workshop_rank` sorts by `(-wins, -elo, index)`). Measured on the same
    newcomer under the same rule: at 4 rounds entering round 3 it lands rank 6
    and passes; at 8 rounds entering round 6, rank 11; entering round 7, rank 16
    and fails. `catch_up_matches` is what makes raising the rounds safe.

    The arithmetic:
      * fewer than 2 candidates -> 0. There is nothing to rank.
      * a positive `override` wins outright. `workshop_rank` owns the env knob
        `NESTOR_TRIBUNAL_WORKSHOP_ROUNDS` and passes it in, so an explicit
        operator setting is honoured without the formula being duplicated there.
      * otherwise `min(MAX, max(MIN, ceil(log2 n)), n - 1)`.

    `n - 1` is a hard bound and it BEATS the floor: a field of 3 has only 2
    distinct opponents, and scheduling four rematches to reach a floor of 6
    would buy nothing but flash calls.
    """
    total = _safe_int(n_candidates, 0)
    if total < 2:
        return 0
    explicit = _safe_int(override, 0)
    if explicit > 0:
        return explicit
    floor = max(_TOURNAMENT_ROUNDS_MIN, _ceil_log2(total))
    return max(0, min(_TOURNAMENT_ROUNDS_MAX, floor, total - 1))


def catch_up_matches(match_counts: Any) -> int:
    """A newcomer plays up to the field's MEDIAN match count on entry. D-W4-3.

    THIS REPLACES D-R11'S MEDIAN SEED, WHICH IS INERT. The seed is not wrong, it
    is a NO-OP, which is worse because it reads as a solved problem. The standing
    sorts by `(-wins, -elo, index)` — **wins is primary and Elo is only the
    tie-break**, as `workshop_rank._apply_elo`'s own docstring says in capitals —
    so a newcomer's disadvantage is FEWER MATCHES AND THEREFORE FEWER WINS, not a
    lower rating. Median-seed and flat-1200 produce byte-identical output.

    So the fix is the SCHEDULE, not the sort. A new candidate simply plays the
    matches it missed, and **the ranking code is not modified at all** — a far
    smaller blast radius than rewriting the standing rule. Measured with a
    perfect judge, 8 rounds, newcomer entering round 6, chance of reaching the
    top N:

        median seed (D-R11 as ruled)      STRONG 1.5%   MEDIAN 1.5%   WEAK 0.0%
        flat 1200 seed                    byte-identical to the median seed
        rank by raw win-RATE              STRONG 95.5%  MEDIAN 93.8%  WEAK 5.8%
        catch-up schedule, sort UNCHANGED STRONG 99.8%  MEDIAN 29.5%  WEAK 1.8%

    The win-rate row is the obvious repair and it OVER-corrects: at 93.8% for a
    median candidate it has stopped discriminating altogether. The last row is
    the shape the ruling wanted. Cost: about 5 extra flash judgements, against a
    whole 4-round tournament that measured 6 flash calls at ~$0.00.

    This is also Co-Scientist's own approach — newer and top-ranking hypotheses
    are prioritised for participation in tournament matches.

    THE LOW MEDIAN, AS AN `int`, DELIBERATELY NOT `statistics.median`. That
    function returns a FLOAT on an even-length list, and this value INDEXES A
    SCHEDULE. `values[(len(values) - 1) // 2]` over a sorted, cleaned list is the
    low median and is an int by construction.

    Entries that are not usable non-negative counts are DROPPED rather than
    coerced: a negative match count is nonsense, not a low score. An empty or
    wholly unusable input returns 0 — a newcomer with no field to catch up to
    has nothing to catch up.
    """
    values: list[int] = []
    if isinstance(match_counts, (str, bytes)) or match_counts is None:
        return 0
    try:
        iterator = iter(match_counts)
    except TypeError:
        return 0
    for raw in iterator:
        if isinstance(raw, bool):
            values.append(int(raw))
            continue
        if not isinstance(raw, (int, float)):
            continue
        if isinstance(raw, float) and (raw != raw or raw in (float("inf"), float("-inf"))):
            continue
        count = _safe_int(raw, -1)
        if count >= 0:
            values.append(count)
    if not values:
        return 0
    values.sort()
    return int(values[(len(values) - 1) // 2])
