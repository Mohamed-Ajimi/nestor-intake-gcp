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


# ===========================================================================
# Candidate-shape helpers. Total, defensive, and shared by everything below.
# ===========================================================================


def _as_entries(ranked: Any) -> list[dict[str, Any]]:
    """Coerce the caller input into a list of candidate dicts. Never raises.

    A non-dict element is KEPT as an empty dict rather than dropped. That looks
    pedantic and is not: the never-drop rule below is an invariant of this
    module, and an input shape nobody expected is not a licence to start
    deleting positions from a pool that another stage is going to reconcile
    against.
    """
    if ranked is None or isinstance(ranked, (str, bytes, dict)):
        if isinstance(ranked, (str, bytes)):
            return [{} for _ in range(len(ranked))]
        return []
    try:
        raw_items = list(ranked)
    except TypeError:
        return []
    return [item if isinstance(item, dict) else {} for item in raw_items]


def _clean_labels(client_questions: Any) -> list[str]:
    """The ordered, de-duplicated client-question labels. Never raises."""
    out: list[str] = []
    if client_questions is None or isinstance(client_questions, (str, bytes)):
        return out
    try:
        raw_items = list(client_questions)
    except TypeError:
        return out
    for raw in raw_items:
        try:
            label = str(raw or "").strip()
        except Exception:  # noqa: BLE001 - a total function by contract
            continue
        if label and label not in out:
            out.append(label)
    return out


def _parents_of(entry: Any) -> list[str]:
    """The ordered parent labels one candidate covers. Mirrors `workshop_rank._parents_of`.

    UNION OVER `parents`, FALLING BACK TO `parent` — and the direction matters.
    The near-duplicate collapse can legitimately carry two client questions onto
    ONE representative: the representative keeps the lowest-ranked member own
    `parent`, but `parents` is the ordered union of every member. Reading only
    `parent` would report a false coverage miss on a perfectly valid clustering.
    """
    out: list[str] = []
    if not isinstance(entry, dict):
        return out
    try:
        raw_parents = list(entry.get("parents") or [])
    except TypeError:
        raw_parents = []
    for raw in raw_parents:
        try:
            label = str(raw or "").strip()
        except Exception:  # noqa: BLE001 - a total function by contract
            continue
        if label and label not in out:
            out.append(label)
    if not out:
        try:
            own = str(entry.get("parent") or "").strip()
        except Exception:  # noqa: BLE001 - a total function by contract
            own = ""
        if own:
            out.append(own)
    return out


def _critique_of(entry: Any) -> str:
    """The critique verdict, upper-cased. Anything unreadable reads as KEEP.

    THE DEFAULT INVERTS TOWARDS SURVIVAL, exactly as `workshop_rank`
    `_CRITIQUE_DEFAULT` does, and for the same reason: a needless match costs a
    fraction of a cent, whereas a silently deleted sub-question is a scope loss
    nobody can see.
    """
    if not isinstance(entry, dict):
        return _KEEP
    try:
        verdict = str(entry.get("critique") or "").strip().upper()
    except Exception:  # noqa: BLE001 - a total function by contract
        return _KEEP
    return verdict or _KEEP


def _is_cross_cutting(entry: Any, labels: Sequence[str]) -> bool:
    """Does this candidate join two client questions, or come from discovery?

    Two shapes count, and both are real. A candidate whose `parents` span two or
    more CLIENT-QUESTION labels is a cross-cutting mandate question — those have
    two genuine parents and are where the best measured output came from. A
    candidate carrying the `__discovery__` sentinel came from nowhere on the
    mandate at all, which is the other way a question can be cross-cutting.
    """
    parents = _parents_of(entry)
    if _DISCOVERY_PARENT in parents:
        return True
    return len([p for p in parents if p in labels]) >= 2


def select_winners(
    ranked: Any,
    *,
    client_questions: Any,
    default_cut: Any,
    floor_per_question: Optional[int] = None,
    cross_cutting_slots: Optional[int] = None,
    prefer_keep: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Choose the winners at the cut. D-W4-5, the `exp11` validated configuration.

    Returns `(winners, below_cut)`. `ranked` is in rank order — position 0 is
    rank 1 — and both lists come back in ascending rank order.

    THE SHAPE: a floor of `floor_per_question` winners per client question, plus
    `cross_cutting_slots` for questions that span two of them, applied AT THE CUT
    rather than by splitting the pool into per-question quotas. Measured over 3
    client questions with 12 candidates generated each: 17 winners, 5 + 5 + 5 + 2,
    none WEAK, converging in round 4.

    THREE THINGS A FUTURE READER WILL GET WRONG, STATED PLAINLY:

    1. THIS FUNCTION NEVER BARS ANYTHING. Losing the tournament is not a defect —
       it means the candidate was fine and just missed the cut.
       `enforce_scope_guard` documented repair ladder PROMOTES a below-the-cut
       candidate when a client question ends up with no winner, so barring losers
       silently breaks the coverage guarantee. `below_cut` is returned for
       exactly that reason and it is a complete partition of the input: every
       candidate handed in comes back in one list or the other, always.

    2. THE FLOOR OVERRIDES `_WINNERS_MIN` / `_WINNERS_MAX`. `winner_count` would
       cap the cut at 15 and the validated configuration is 17. D-W4-5 is an
       operator decision and the floor wins. `default_cut` is consulted ONLY when
       there are no client questions at all. Say it here and pin it in a test, or
       a later reader restores the cap and silently deletes two research
       questions.

    3. `discovery_bracket` ANTI-QUOTA DOCSTRING DOES NOT GOVERN THIS FLOOR. That
       docstring argues against quotas by name, and it is right about what it is
       arguing about: a per-question DISCOVERY quota would force the engine to
       MANUFACTURE a discovery question for a client question that has no
       conflict worth exploring. A MANDATE floor manufactures nothing — the
       per-question candidates already exist and were already generated. A future
       reader will cite that docstring to block this floor. It does not apply.

    PREFER-KEEP is applied at EVERY step, and it is ONE rule: within the eligible
    pool for a slot, take the best-ranked candidate whose critique is KEEP if any
    KEEP is eligible, otherwise the best-ranked non-KEEP.

    It is the single highest-leverage rule the measurement found, and it is a few
    lines of selection logic. Exit criterion 2 CHECKS for WEAK winners, and
    nothing anywhere ever PREVENTED one from being selected — a smoke alarm with
    no fire door. Adding the preference took WEAK winners to 0 and made criterion
    2 satisfiable BY CONSTRUCTION rather than by luck.

    ITS DEPENDENCY, WHICH IS NOT A PROPERTY OF THE RULE: prefer-KEEP only works
    when there are spare KEEP candidates to prefer, and that is a property of the
    SELECTION RATIO. At 6 generated per question against a 5-slot floor it is a
    5-of-6 choice and the rule is INERT; at 12 generated it is a 5-of-12 choice
    and the rule always has a KEEP available. That single change halved the cost
    AND more than halved the rounds at an identical slot count.
    """
    entries = _as_entries(ranked)
    labels = _clean_labels(client_questions)
    total = len(entries)

    floor = _FLOOR_PER_QUESTION if floor_per_question is None else _safe_int(
        floor_per_question, _FLOOR_PER_QUESTION
    )
    slots = _CROSS_CUTTING_SLOTS if cross_cutting_slots is None else _safe_int(
        cross_cutting_slots, _CROSS_CUTTING_SLOTS
    )
    floor = max(0, floor)
    slots = max(0, slots)

    if labels:
        target = floor * len(labels) + slots
    else:
        target = _safe_int(default_cut, 0)
    target = max(0, min(target, total))

    taken: set[int] = set()

    def _pick(eligible: list[int]) -> Optional[int]:
        """One slot. Prefer a KEEP if one is eligible, else the best rank."""
        if not eligible:
            return None
        if prefer_keep:
            for position in eligible:
                if _critique_of(entries[position]) == _KEEP:
                    return position
        return eligible[0]

    # --- Step 1: the per-client-question floor, in CLIENT-QUESTION ORDER.
    for label in labels:
        for _ in range(floor):
            if len(taken) >= target:
                break
            eligible = [
                p
                for p in range(total)
                if p not in taken and label in _parents_of(entries[p])
            ]
            chosen = _pick(eligible)
            if chosen is None:
                break
            taken.add(chosen)

    # --- Step 2: the cross-cutting slots.
    for _ in range(slots if labels else 0):
        if len(taken) >= target:
            break
        eligible = [
            p
            for p in range(total)
            if p not in taken and _is_cross_cutting(entries[p], labels)
        ]
        chosen = _pick(eligible)
        if chosen is None:
            break
        taken.add(chosen)

    # --- Step 3: fill whatever is left of the target, by rank.
    while len(taken) < target:
        chosen = _pick([p for p in range(total) if p not in taken])
        if chosen is None:
            break
        taken.add(chosen)

    def _stamped(position: int) -> dict[str, Any]:
        """A COPY, with the cross-cutting boolean stamped on.

        A copy because the caller ranked pool is reused by the evolve step and a
        function that quietly writes into it would pass every behavioural test
        and still be a bug. The boolean is stamped here so `exit_verdict` reads a
        flag instead of re-deriving the property — see Exemption A, which must be
        STRUCTURAL rather than textual.
        """
        copied = dict(entries[position])
        copied["cross_cutting"] = _is_cross_cutting(entries[position], labels)
        return copied

    winners = [_stamped(p) for p in sorted(taken)]
    below_cut = [_stamped(p) for p in range(total) if p not in taken]
    return winners, below_cut


# ===========================================================================
# The degradation vocabulary, built HERE in one place, exactly as
# `workshop_rank.py:218-280` and `workshop.py:218-280` do for their own stages.
# Each sentence is > 40 characters, names its count as a literal digit, and
# states the CONSEQUENCE rather than just the event — the bar `test_fail_loud`
# sets is a sentence a human reads, not a code.
# ===========================================================================


def _reason_cap_with_weak(weak: int, total: int) -> str:
    return (
        f"question workshop: the loop reached its round cap with {weak} of "
        f"{total} winning question(s) that could not be sharpened past {_WEAK}, "
        f"so those questions go to research as they stand — every client "
        f"question is still covered, but that many answers will be "
        f"correspondingly less pointed."
    )


def _reason_cap_with_resurrected(resurrected: int, total: int) -> str:
    return (
        f"question workshop: the loop reached its round cap with {resurrected} "
        f"of {total} winning question(s) that survived only because a coverage "
        f"guard kept them when the critique pass tried to remove everything, so "
        f"those questions were never actually judged worth researching — they "
        f"are there to keep a client question from going unanswered."
    )


def _exempt_cross_cutting(winner: Any) -> bool:
    """EXEMPTION A, AND IT IS STRUCTURAL ON PURPOSE. Read the whole of this.

    A cross-cutting question is compound BY CONSTRUCTION — it joins two topics
    deliberately — so the flaw clause about being two questions in one must not
    count against it in criterion 2. Without the exemption, criterion 2
    structurally penalises exactly the highest-value questions the loop exists to
    produce: it would be built to reject its own best output. `exp9` marked both
    its best questions WEAK for precisely this reason.

    THE OBVIOUS IMPLEMENTATION IS TO MATCH THAT PHRASE IN THE FLAW TEXT. DO NOT.
    The critique prompt is English, but a Dutch or French run flaw clause is
    model prose in the run own language, so a text matcher would silently NEVER
    FIRE on those runs — and a guard that never fires is worse than no guard,
    because it reads as a solved problem. This keys off the boolean
    `select_winners` stamps, which is language-independent and derived from the
    candidate parent structure rather than from prose.
    """
    if not isinstance(winner, dict):
        return False
    return winner.get("cross_cutting") is True


def _is_resurrected(winner: Any) -> bool:
    """EXEMPTION B. READ the flag; never INFER it.

    `workshop_rank` Guard 1 sets `resurrected`; Guard 2 — the one that rewrites
    EVERY candidate to KEEP when critique kills everything — does NOT set it
    today, and plan 15.7-08 makes it do so. This function must be correct
    whether or not that has landed, so it reads the flag and deduces nothing.
    """
    if not isinstance(winner, dict):
        return False
    return winner.get("resurrected") is True


def exit_verdict(
    *,
    winners: Any,
    client_questions: Any,
    round_no: Any,
    max_rounds: Optional[int] = None,
) -> dict[str, Any]:
    """Should the loop stop? D-W4-6, all three criteria, none removed or reordered.

    THE CRITERION NUMBERING IS LOAD-BEARING AND HAS ALREADY BEEN WRONG ONCE IN
    THREE FILES AT THE SAME TIME:

        1 = COVERAGE    every client question has at least one KEEP winner
        2 = QUALITY     no winner is WEAK, subject to the two exemptions
        3 = SATURATION  the last evolve pass produced no new entrant to the top N

    CORRECTED 2026-07-31. Until that date `15.7-OPEN-ITEMS.md`, spec section 5
    boxed warning and section 8 Wave 4 row ALL said the resurrection exemption
    targeted criterion 1. That inverted the rule own purpose: criterion 1 is
    COVERAGE, and excluding a resurrected candidate from COVERAGE would break the
    exact guarantee resurrection exists to provide. THE TARGET IS CRITERION 2.

    MEASURED, SO THE `AND` IS NOT PARANOIA: all three global configurations
    exited on the criteria well inside the cap — rounds 4, 6 and 9 — and the
    criteria were observed to gate each other in turn rather than one blocking
    forever (round 2 saturation passed while quality failed; round 3 the
    reverse). WEAK winners fell 3 -> 3 -> 0 -> 0 across the configurations.

    A `False` HERE IS OFTEN A NORMAL READING. In the harness, COVERAGE FAILED in
    rounds 4 and 5 before recovering, because barring WEAK-after-two-passes
    stripped every KEEP candidate from one client question. The exit AND
    correctly refused to exit. That is the loop working, not a bug to tune out.

    AT THE CAP THE LOOP SHIPS AND RECORDS A REASON, matching D-12: degraded means
    honest, not broken. V-01 would have carried a sentence naming 3 of 10 winners
    that could not be sharpened past WEAK — exactly what an operator wants to see.
    """
    entries = _as_entries(winners)
    labels = _clean_labels(client_questions)
    current = _safe_int(round_no, 0)
    cap = _LOOP_MAX_ROUNDS if max_rounds is None else _safe_int(
        max_rounds, _LOOP_MAX_ROUNDS
    )

    # --- Criterion 1: COVERAGE. A KEEP winner for every client question.
    covered: set[str] = set()
    for winner in entries:
        if _critique_of(winner) == _KEEP:
            covered.update(_parents_of(winner))
    coverage_ok = all(label in covered for label in labels)

    # --- Criterion 2: QUALITY, with Exemption A (structural) and Exemption B.
    weak_winners = 0
    resurrected_winners = 0
    for winner in entries:
        if _is_resurrected(winner):
            resurrected_winners += 1
        if _critique_of(winner) == _WEAK and not _exempt_cross_cutting(winner):
            weak_winners += 1
    quality_ok = weak_winners == 0 and resurrected_winners == 0

    # --- Criterion 3: SATURATION. Nothing in the winner set was born this round.
    _ABSENT = -(10**9)
    new_entrants = 0
    for winner in entries:
        if not isinstance(winner, dict) or winner.get("born_round") is None:
            continue
        if _safe_int(winner.get("born_round"), _ABSENT) == current:
            new_entrants += 1
    saturation_ok = new_entrants == 0

    cap_reached = current >= cap
    should_exit = bool(coverage_ok and quality_ok and saturation_ok)

    sentences: list[str] = []
    if cap_reached and not quality_ok:
        if weak_winners:
            sentences.append(_reason_cap_with_weak(weak_winners, len(entries)))
        if resurrected_winners:
            sentences.append(
                _reason_cap_with_resurrected(resurrected_winners, len(entries))
            )

    return {
        "round_no": current,
        "max_rounds": cap,
        "winner_count": len(entries),
        "coverage_ok": bool(coverage_ok),
        "quality_ok": bool(quality_ok),
        "saturation_ok": bool(saturation_ok),
        "should_exit": should_exit,
        "cap_reached": bool(cap_reached),
        "weak_winners": int(weak_winners),
        "resurrected_winners": int(resurrected_winners),
        "new_entrants": int(new_entrants),
        "degradation_reason": " ".join(sentences),
    }


def _count_of(value: Any) -> int:
    """A count from whatever the caller had to hand. Never raises.

    A caller that passes the winner LIST rather than its length gets the length,
    not a silent zero. Instrumentation that quietly reports 0 is worse than
    instrumentation that is absent, because a zero looks like a measurement.
    """
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, (str, bytes)):
        return _safe_int(value, 0)
    try:
        return len(value)
    except TypeError:
        return _safe_int(value, 0)


def _cost_str(value: Any) -> str:
    """Spend as a STRING, the same idiom `workshop_rank` uses for `stats`.

    A float in an audit record renders differently depending on who serialises
    it, and these records are read by a human comparing rounds.
    """
    try:
        return str(float(value))
    except (TypeError, ValueError):
        return "0.0"


def round_metrics(
    *,
    round_no: Any,
    candidates_in: Any,
    new_candidates: Any,
    winners: Any,
    weak_winners: Any,
    barred: Any,
    dropped_as_reproposal: Any,
    lookups: Any,
    calls: Any,
    cost_usd: Any,
) -> dict[str, Any]:
    """One per-round instrumentation record. D-W4-7. IT ENFORCES NOTHING.

    NO CEILING, NO TRUNCATION, NO EXCEPTION — and that is a decision, not an
    omission. Neither the spend ceiling nor a population cap nor a per-round
    grounded-lookup cap is binding at the measured scale: population stayed
    between 23 and 41 across all three global configurations, the largest prompt
    the loop ever built was ~9k chars, and the validated configuration cost
    $0.24 in total against the spec original ~$3.00 estimate for 10 rounds.

    AN ENFORCED CEILING NOBODY HAS MEASURED A NEED FOR IS A KNOB THAT WILL ONE
    DAY TRUNCATE A RUN FOR NO REASON. A logged number is what tells you whether a
    ceiling is ever warranted. The one guard that does real work is SATURATION,
    and the round cap is a ceiling rather than a target — confirmed by
    measurement rather than assumed. If runs routinely hit 10 rounds, that is
    evidence the cap should go HIGHER, not that money is being wasted.

    The record is plain ints and strings so it survives `json.dumps` unchanged
    and carries no float into an audit trail.
    """
    return {
        "round_no": _count_of(round_no),
        "candidates_in": _count_of(candidates_in),
        "new_candidates": _count_of(new_candidates),
        "winners": _count_of(winners),
        "weak_winners": _count_of(weak_winners),
        "barred": _count_of(barred),
        "dropped_as_reproposal": _count_of(dropped_as_reproposal),
        "lookups": _count_of(lookups),
        "calls": _count_of(calls),
        "cost_usd": _cost_str(cost_usd),
    }
