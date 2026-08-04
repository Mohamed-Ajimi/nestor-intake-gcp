"""The workshop loop's per-round yield write, and the drop-cause separation.

WHAT THIS FILE PROVES, AND WHY EACH PIECE IS SHAPED THE WAY IT IS.

`workshop_rank._persist_round_yield` maps a `round_metrics` record onto the nine
`workshop_round_yield` columns this plan fills, and 15.8-15 reads that table as
THE ONE MEASUREMENT of a five-wave redesign. There is no second run to correct
it. So the two failure modes worth testing are not "does it crash" but:

  1. A PLAUSIBLE WRONG BINDING. `winners` and `keep_count` are both integers of
     a similar size, and so are `barred` and `dropped_as_reproposal`. Binding
     either pair the wrong way round produces a number nothing downstream can
     contradict. Every binding test below therefore uses a record whose two
     CONFUSABLE SOURCE KEYS HOLD DIFFERENT VALUES, so a wrong binding cannot
     pass by coincidence.

  2. AN EXCEPTION REACHING THE LOOP. `run_workshop_stage_b`'s outer
     `except Exception` DOES NOT MERELY LOG -- it returns `_fallback_winners`.
     So an instrumentation exception would not crash the run, it would SILENTLY
     REPLACE THE ENTIRE WORKSHOP'S OUTPUT WITH VERBATIM CLIENT QUESTIONS, in a
     ~$45 single-shot run, under a `log.error` nobody would attribute to
     telemetry. "The stage catches it anyway" is the WRONG argument here.

⛔ NO `ast`-LIFT ANYWHERE IN THIS FILE. That harness SUPPLIES MODULE GLOBALS and
therefore MANUFACTURES any name a module forgot to import; it hid a missing
import used at four sites through nine plans, past `py_compile` and past "38
lifted tests green". This file imports the REAL modules. That is the point:
`workshop_rank` gained a module-level `yield_records` import in this plan, and
only a real import can prove it resolves and is not a cycle.

This file opens NO DATABASE, makes NO LLM CALL, needs NO API KEY and uses NO
mocking library -- the writer is replaced through `monkeypatch.setattr` on the
module global, the same TEST SEAM discipline `test_yield_records.py` uses.
`pyproject.toml` sets `asyncio_mode = "auto"`, so `async def test_*` needs no
marker.
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from nestor_pulse_sdk.pipeline.tribunal import workshop_rank as wr
from nestor_pulse_sdk.pipeline.tribunal import workshop_register
from nestor_pulse_sdk.runs import yield_records


# ===========================================================================
# Fixtures. The recorder replaces the ONE public entry point a pipeline module
# is allowed to call, and captures what `build()` produced.
# ===========================================================================


class _Recorder:
    """Captures every round row built, without touching Postgres."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls: list[tuple[Any, Any]] = []

    async def __call__(self, run_id: Any, tenant_id: Any, *, build: Any) -> None:
        self.calls.append((run_id, tenant_id))
        self.rows.append(build())


@pytest.fixture
def recorder(monkeypatch):
    """Rebind `record_round_safe` AS `workshop_rank` RESOLVES IT.

    `workshop_rank` does `from nestor_pulse_sdk.runs import yield_records` and
    then calls `yield_records.record_round_safe(...)`, so the name is looked up
    as an ATTRIBUTE OF THE MODULE at call time. Patching the attribute on the
    module object is therefore what the production call actually reaches.
    """
    rec = _Recorder()
    monkeypatch.setattr(yield_records, "record_round_safe", rec)
    return rec


def _record(**overrides: Any) -> dict[str, Any]:
    """A realistic `round_metrics` record.

    THE CONFUSABLE PAIRS DELIBERATELY DISAGREE: `winners` 17 vs `keep_count` 20,
    `weak_winners` 0 vs `weak_count` 10, `barred` 4 vs `dropped_as_reproposal`
    3. If any of the three bindings were swapped, the assertions below would
    read the neighbour's value and fail -- which is exactly the coincidence a
    same-valued fixture would hide.
    """
    record: dict[str, Any] = {
        "round_no": 3,
        "candidates_in": 34,
        "new_candidates": 7,
        "keep_count": 20,
        "weak_count": 10,
        "kill_count": 4,
        "new_entrants_top_n": 2,
        "winners": 17,
        "weak_winners": 0,
        "barred": 4,
        "dropped_as_reproposal": 3,
        "lookups": 2,
        "calls": 97,
        "cost_usd": "0.24",
    }
    record.update(overrides)
    return record


# ===========================================================================
# THE MAPPING (D-W5-1's frozen column set, filled by this plan).
# ===========================================================================


async def test_the_nine_mapped_fields_reach_the_emitter(recorder) -> None:
    """One round in, one row out, with all nine columns this plan fills."""
    await wr._persist_round_yield("rid", "tid", _record())

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    assert recorder.calls == [("rid", "tid")]
    assert row == {
        "round_no": 3,
        "candidates_in": 34,
        "new_candidates": 7,
        "keep_count": 20,
        "weak_count": 10,
        "kill_count": 4,
        "new_entrants_top_n": 2,
        "barred_drops": 3,
        "round_cost_usd": "0.24",
    }


async def test_keep_count_is_the_critique_count_and_never_the_winner_count(
    recorder,
) -> None:
    """D-W5-11. `winners` is 17 and `keep_count` is 20 IN THE SAME RECORD.

    They are different denominators: `winners` is the size of the cut,
    `keep_count` is how many of the whole population the critique marked KEEP.
    The fixture holds two DIFFERENT values on purpose, so binding the wrong one
    cannot pass by coincidence -- with equal values this test would be vacuous.
    """
    await wr._persist_round_yield("rid", "tid", _record(winners=17, keep_count=20))
    row = recorder.rows[0]
    assert row["keep_count"] == 20, "keep_count was bound from winners (D-W5-11)"
    assert row["keep_count"] != 17


async def test_weak_count_is_the_critique_count_and_never_the_weak_winner_count(
    recorder,
) -> None:
    """`weak_winners` is WINNER-scoped and cross-cutting-exempt; `weak_count` is not.

    Again the two hold different values (0 vs 10) so a swapped binding fails
    rather than coincidentally agreeing.
    """
    await wr._persist_round_yield(
        "rid", "tid", _record(weak_winners=0, weak_count=10)
    )
    row = recorder.rows[0]
    assert row["weak_count"] == 10, "weak_count was bound from weak_winners"
    assert row["weak_count"] != 0


async def test_barred_drops_takes_dropped_as_reproposal_and_never_barred(
    recorder,
) -> None:
    """`barred` is bars CREATED this round; `barred_drops` is DROPS. Different quantities.

    `round_metrics` emits them as SEPARATE keys (4 vs 3 here) precisely because
    conflating a bar with a barred-duplicate drop is the other half of D-W5-6.
    """
    await wr._persist_round_yield(
        "rid", "tid", _record(barred=4, dropped_as_reproposal=3)
    )
    row = recorder.rows[0]
    assert row["barred_drops"] == 3, "barred_drops was bound from barred, not the drop"
    assert row["barred_drops"] != 4


async def test_new_entrants_top_n_reaches_the_row(recorder) -> None:
    """The counter ENGINE-REDESIGN-SPEC section 6 calls the loop's justification."""
    await wr._persist_round_yield("rid", "tid", _record(new_entrants_top_n=2))
    assert recorder.rows[0]["new_entrants_top_n"] == 2


async def test_an_absent_measurement_becomes_none_and_never_zero(recorder) -> None:
    """A record missing every key STILL PRODUCES A CALL, with None per field.

    `None` means "not recorded" and `0` means "measured zero", and D-W5-10's
    governing principle is that a fabricated measurement is worse than an absent
    one. The mapping therefore uses `.get(...)` and adds NO coercion of its own
    -- coercion belongs to 15.8-05's emitter and to nobody else. In particular
    `workshop_loop._count_of` returns 0 and is the WRONG tool here.
    """
    await wr._persist_round_yield("rid", "tid", {})

    assert len(recorder.rows) == 1
    row = recorder.rows[0]
    for column in (
        "round_no", "candidates_in", "new_candidates", "keep_count", "weak_count",
        "kill_count", "new_entrants_top_n", "barred_drops", "round_cost_usd",
    ):
        assert row[column] is None, f"{column} fabricated a value for an absent key"
        assert row[column] != 0 or row[column] is None


# ===========================================================================
# THE NEVER-RAISES CONTRACT. An escaping exception does not crash the run --
# it silently degrades the workshop to verbatim client questions.
# ===========================================================================


async def test_a_writer_that_raises_leaves_the_caller_returning_normally(
    monkeypatch,
) -> None:
    """A dead database may not take the workshop's output with it."""

    async def boom(run_id: Any, tenant_id: Any, *, build: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(yield_records, "record_round_safe", boom)
    assert await wr._persist_round_yield("rid", "tid", _record()) is None


@pytest.mark.parametrize("garbage", [None, "a string", 12345, object()])
async def test_a_garbage_record_leaves_the_caller_returning_normally(
    recorder, garbage
) -> None:
    """`None`, a string, an int and a bare object all leave the loop unharmed."""
    assert await wr._persist_round_yield("rid", "tid", garbage) is None


async def test_a_record_whose_getitem_raises_does_not_break_the_call(
    recorder,
) -> None:
    """THE HOSTILE-RECORD TEST -- this is the one that pins the lambda.

    A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE IS ENTERED. If the
    mapping dict were assigned to a local ABOVE the `record_round_safe` call,
    this record's exploding accessor would raise AT THE CALL SITE, outside every
    protecting `try`, and `run_workshop_stage_b` would return fallback winners.

    Building the dict INSIDE `build=lambda: {...}` moves that evaluation into
    the emitter's own try. "Tidying" the hoist back out reintroduces the entire
    defect while looking correct -- which is why this test exists.
    """

    class Hostile(dict):
        def get(self, *args: Any, **kwargs: Any) -> Any:
            raise RuntimeError("hostile record")

        def __getitem__(self, key: Any) -> Any:
            raise RuntimeError("hostile record")

    assert await wr._persist_round_yield("rid", "tid", Hostile()) is None


# ===========================================================================
# D-W5-6 -- THE DROP-CAUSE SEPARATION, over the REAL register.
# ===========================================================================


def test_count_drops_separates_the_two_causes_from_the_bare_length() -> None:
    """The bare length is the SUM OF TWO OPPOSITE FAILURES. That is the defect.

    `record_drop` appends BOTH causes to ONE list by design. A loop SPINNING
    (re-proposing barred questions) and a dedup STRANGLING DISCOVERY (merging
    near-copies of live candidates) are the two things D-W4-1 built the drop log
    to TELL APART, so reporting their sum under either one's name is worse than
    reporting nothing.

    Two barred-cause drops and three live-cause drops: the bare length is 5 and
    the barred-cause count is 2. That gap of 3 is exactly the inflation the
    three swaps in `workshop_rank.py` prevent from reaching
    `workshop_round_yield.barred_drops`.
    """
    register = workshop_register.new_register()
    for i in range(2):
        workshop_register.record_drop(
            register,
            text=f"barred re-proposal {i}",
            cause=workshop_register.DROP_CLUSTERED_ONTO_BARRED,
            clustered_onto="a barred question",
            round_no=2,
        )
    for i in range(3):
        workshop_register.record_drop(
            register,
            text=f"ordinary near-copy {i}",
            cause=workshop_register.DROP_CLUSTERED_ONTO_LIVE,
            clustered_onto="a live representative",
            round_no=2,
        )

    assert len(register.get("drops") or []) == 5, "the bare length sums both causes"
    assert (
        workshop_register.count_drops(
            register, cause=workshop_register.DROP_CLUSTERED_ONTO_BARRED
        )
        == 2
    )
    assert (
        workshop_register.count_drops(
            register, cause=workshop_register.DROP_CLUSTERED_ONTO_LIVE
        )
        == 3
    )


def _stage_b_source() -> str:
    """`run_workshop_stage_b`'s source plus the `_stage_b_result(` call block.

    Located BY SYMBOL through `ast`, never by line number: 15.8-03 edited this
    same file in the wave before this plan, so every line number in every
    document citing it is an aid and not an address.
    """
    path = Path(wr.__file__)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "run_workshop_stage_b"
    ][0]
    return ast.get_source_segment(src, fn) or ""


def test_all_three_drop_reads_are_cause_filtered_in_the_committed_source() -> None:
    """D-W5-6: ALL THREE OR NONE. A SOURCE-TEXT test, and it says so.

    THIS PROVES THE SOURCE, NOT THE BEHAVIOUR. Driving `run_workshop_stage_b`
    end to end needs the pytest shim and `workshop_fakes`; that behavioural
    proof is OWED to Cloud Build at 15.8-13. What this pins is that no bare
    `len(register.get("drops"))` survived anywhere in the stage, because sites 1
    and 2 are a MATCHED PAIR: fixing one and not the other leaves a delta
    measured between two different denominators, which is worse than leaving
    both wrong.
    """
    body = _stage_b_source()
    assert body, "run_workshop_stage_b was not found by symbol"

    bare = 'len(register.get("drops")'
    assert bare not in body, "A BARE-LENGTH DROP READ SURVIVED -- D-W5-6 says all three or none"
    assert body.count("count_drops(") == 3, (
        f"expected 3 cause-filtered reads, found {body.count('count_drops(')}"
    )
    assert "DROP_CLUSTERED_ONTO_BARRED" in body


def test_the_persist_call_sits_after_the_round_record_and_before_the_hold_log() -> None:
    """The row is written PER ROUND, before the exit check can break the loop.

    A run that dies in round 7 keeps rounds 1-6 -- the durability half of the
    same argument that made 15.8-05 write `assignment_yield` at research-resolve
    rather than at the end. And the record written is the one JUST APPENDED, so
    the table and `loop_rounds` can never disagree.
    """
    body = _stage_b_source()
    append_at = body.index("round_records.append(")
    persist_at = body.index("await _persist_round_yield(")
    hold_at = body.index('verdict.get("hold_reason")')
    assert append_at < persist_at < hold_at


def test_the_mapping_is_built_inside_the_build_lambda() -> None:
    """No hoist. The dict literal must be INSIDE `build=lambda:`.

    Pinned structurally rather than by grep: the `build` keyword argument of the
    `record_round_safe` call must be a `Lambda` whose body is a `Dict`.
    """
    path = Path(wr.__file__)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_persist_round_yield"
    ][0]

    lambdas = [
        kw.value
        for call in ast.walk(fn)
        if isinstance(call, ast.Call)
        for kw in call.keywords
        if kw.arg == "build"
    ]
    assert len(lambdas) == 1, "expected exactly one build= keyword argument"
    assert isinstance(lambdas[0], ast.Lambda), "build= must be a lambda, not a local"
    assert isinstance(lambdas[0].body, ast.Dict), (
        "the mapping dict must be built INSIDE the lambda -- a hoist to a local "
        "above the call reintroduces the whole defect while looking correct"
    )


def test_the_winner_scoped_keys_are_never_read_inside_the_helper() -> None:
    """`winners`, `weak_winners` and `barred` must appear NOWHERE in the helper.

    They are the three confusable neighbours of the three columns this helper
    binds. Their absence from its source is the structural half of the guarantee
    the value assertions above make behaviourally.
    """
    path = Path(wr.__file__)
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_persist_round_yield"
    ][0]
    # Only the EXECUTABLE body -- the docstring names all three on purpose.
    body = ast.get_source_segment(src, fn) or ""
    doc = ast.get_docstring(fn) or ""
    executable = body.replace(doc, "")

    for forbidden in ('"winners"', '"weak_winners"', '"barred"'):
        assert forbidden not in executable, (
            f"{forbidden} is read inside _persist_round_yield -- that is the "
            "D-W5-11 / D-W5-6 mis-binding"
        )


# ===========================================================================
# 15.8-06's RULING, item 2 -- `2-remove`. Resolved BY OPTION ID.
# ===========================================================================


def test_the_actions_sum_no_longer_counts_the_redirect_resolver() -> None:
    """Ruling `2-remove`, read from `15.8-06-DECISION-RECORD.md`'s RULING section.

    `admission_resolver_calls` counts a batched HTTP REDIRECT RESOLUTION, not a
    model call, so `actions` -- which the feed renders as work done -- counted an
    operation that issues no model request at all. D-W5-14 sharpens it: the
    counter is assigned BEFORE the await and regardless of the kill switch, so
    it may count an operation issuing zero HTTP requests.

    THE CORRECTION THAT DECIDED IT: `actions` was NEVER the run's spend signal.
    `cost_usd` travels as a SEPARATE argument on the same
    `_stage_b_feed_finish` call and the resolver records no cost, so the DOLLAR
    FIGURE WAS NEVER CONTAMINATED -- only the count was.

    CR-07's concern survives: the other nine terms are all still read.
    """
    body = _stage_b_source()
    block = body[body.index("calls = ("): body.index("cost = Decimal")]
    executable = "\n".join(
        line for line in block.splitlines() if not line.strip().startswith("#")
    )

    assert "admission_resolver_calls" not in executable, (
        "ruling 2-remove drops this term from the actions sum"
    )
    # CR-07's other terms must NOT have been removed along with it.
    for survivor in (
        "critique_stats", "tourney_stats", "evolve_stats", "generative_stats",
        "meta_stats", "group_stats", "admission_calls", "classify_calls",
        "cluster_stats",
    ):
        assert survivor in executable, f"CR-07 term {survivor} was removed beyond the ruling"
