"""The research-division feed header's UNIFORM-DISPATCH clause (WR-06).

WHAT BREAKS IN PRODUCTION IF THESE FIRE: the operator's feed — and, far worse, the
run's own permanent record — assert something untrue about the run. The header line
reads "every one of those N group(s) went to all 3 research streams". Before WR-06
that sentence was decided by counting DISTINCT `corroboration_key`s, so a group
dispatched on three streams and trimmed back to one still contributed exactly one
key and the strong wording printed anyway.

Plan 15.8-15 reads that record as THE measurement of the whole five-wave engine
redesign. It is one deploy and one paid run; there is no second run to correct a
sentence that overclaims.

These drive `_dispatch_was_uniform` directly with hand-built angle dicts. The
POSITIVE end-to-end assertion (a stubbed 2-group / 3-stream run whose header still
carries the strong wording) lives in `test_engine_e2e_stubbed.py` and is deliberately
NOT duplicated or edited here: that module is shared, this plan does not own it, and
parallel executors in isolated worktrees cannot see each other's edits to it.
"""
from __future__ import annotations

import pytest

from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod


def _angle(key: str, stream: str, corroboration: bool = True) -> dict:
    """One dispatched angle, in the shape `divide()` emits on the group path."""
    return {
        "query": f"q-{key}-{stream}",
        "provider": stream,
        "stakes": "high",
        "focus_area": "Q1",
        "corroboration": corroboration,
        "corroboration_key": key,
    }


def _group(gid: str) -> dict:
    return {"group_id": gid, "bracket": "mandate", "members": [], "why": "w"}


def _copies(key: str, n: int) -> list[dict]:
    """`n` surviving copies of one group's angle — i.e. it reached `n` streams."""
    return [_angle(key, stream) for stream in ("gemini", "openai", "claude")[:n]]


# ---------------------------------------------------------------------------
# The case the strong wording is FOR — it must survive
# ---------------------------------------------------------------------------

def test_two_groups_on_all_three_streams_is_uniform():
    """The clause is CORRECTED, not deleted.

    This is the shape `test_engine_e2e_stubbed.py` asserts end to end. If WR-06 had
    been fixed by simply dropping the strong wording, the operator would lose the one
    line that says corroboration was actually bought — and D-R4/D-W3-1's headline
    result would become invisible in the run record.
    """
    angles = _copies("g1", 3) + _copies("g2", 3)
    groups = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=3) is True


# ---------------------------------------------------------------------------
# The two trim cases — WR-06 itself
# ---------------------------------------------------------------------------

def test_a_group_trimmed_to_one_stream_is_not_uniform():
    """WR-06's named case: the trim shed 2 of 3 and the feed still said "all 3".

    `_trim_ladder`'s P1 rung goes BELOW `_D6_MIN_CORROBORATION`, taking a group from
    three copies to one. The old key-counting arithmetic saw one key for that group
    either way, so `_corroborated == len(groups)` held and the strong wording printed.
    """
    angles = _copies("g1", 3) + _copies("g2", 1)
    groups = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=3) is False


def test_a_group_trimmed_to_two_streams_is_not_uniform():
    """THE REACHABLE ONE, and the reason proving only the 3-to-1 case is not enough.

    `_trim_ladder`'s P2 rung removes corroboration copies only down to
    `_D6_MIN_CORROBORATION` = 2, so 3 -> 2 is what a real trim produces first. D-W3-2's
    fallback at ten client questions is 30 angles against `_MAX_ANGLES` = 28, so this
    rung fires on ordinary production input rather than on a pathological one.
    """
    angles = _copies("g1", 3) + _copies("g2", 2)
    groups = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=3) is False


# ---------------------------------------------------------------------------
# The degenerate inputs — each must yield the weaker wording, never a raise
# ---------------------------------------------------------------------------

def test_empty_groups_is_never_uniform():
    """A pre-Wave-3 checkpoint restored mid-run dispatches with no groups at all.

    THE THIRD ASSERTION IS THE ONE THAT PINS THE GUARD, and the first two do not.
    With KEYED angles present, the key-count equality already rejects an empty
    `groups` (1 key != 0 groups), so deleting the emptiness guard leaves those two
    green — verified by mutation. Only the 0-keys-AND-0-groups shape reaches the
    vacuous `0 == 0`, where `all()` over an empty mapping is True and the feed would
    print "every one of those 0 group(s) went to all 3 research streams" as a true
    statement about nothing.
    """
    assert _pipeline_mod._dispatch_was_uniform(_copies("g1", 3), [], streams=3) is False
    assert _pipeline_mod._dispatch_was_uniform(_copies("g1", 3), None, streams=3) is False
    keyless = [{"corroboration": True, "corroboration_key": ""}]
    assert _pipeline_mod._dispatch_was_uniform(keyless, [], streams=3) is False


def test_empty_angles_is_never_uniform():
    """Nothing was dispatched, so nothing went to all three streams."""
    assert _pipeline_mod._dispatch_was_uniform([], [_group("g1")], streams=3) is False
    assert _pipeline_mod._dispatch_was_uniform(None, [_group("g1")], streams=3) is False


def test_a_group_that_produced_no_surviving_angle_is_not_uniform():
    """Fewer keys than groups — the boundary WR-06 deliberately did NOT move.

    `len(groups)` is stage B's PRE-dispatch count, so a group `_bound_groups_to_winners`
    dropped whole already makes the counts disagree. That already yielded the weaker
    wording before this fix and must keep doing so after it.
    """
    angles = _copies("g1", 3)
    groups = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=3) is False


@pytest.mark.parametrize(
    "bad_angle",
    [
        {"corroboration": False, "corroboration_key": "g2"},
        {"corroboration": True, "corroboration_key": ""},
        {"corroboration": True, "corroboration_key": None},
        {"corroboration": True},
    ],
    ids=["not-corroborated", "empty-key", "none-key", "missing-key"],
)
def test_an_angle_without_a_usable_corroboration_key_contributes_nothing(bad_angle):
    """A non-corroboration or keyless angle must not manufacture a group.

    If any of these counted, a one-group run carrying a stray depth angle would read
    as two keys over two groups and print the strong wording about a group that does
    not exist.
    """
    angles = _copies("g1", 3) + [bad_angle]
    groups = [_group("g1")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=3) is True

    angles_two = _copies("g1", 3) + [bad_angle]
    groups_two = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles_two, groups_two, streams=3) is False


@pytest.mark.parametrize("hostile", [17, 3.5, object(), True, "abc"])
def test_a_hostile_groups_or_angles_value_yields_false_and_never_raises(hostile):
    """A feed header must never raise into a run that has already paid for itself.

    The header is built AFTER the workshop and the angles are bought. A `TypeError`
    here would destroy a run's results to avoid printing one sentence.
    """
    assert _pipeline_mod._dispatch_was_uniform(_copies("g1", 3), hostile, streams=3) is False
    assert _pipeline_mod._dispatch_was_uniform(hostile, [_group("g1")], streams=3) is False


def test_a_non_dict_angle_is_skipped_rather_than_fatal():
    """Model-adjacent data is never trusted to be a dict."""
    angles = _copies("g1", 3) + [None, 17, "not-an-angle"]
    assert _pipeline_mod._dispatch_was_uniform(angles, [_group("g1")], streams=3) is True


# ---------------------------------------------------------------------------
# The stream count itself
# ---------------------------------------------------------------------------

def test_the_stream_count_defaults_to_the_single_source_of_truth():
    """`streams=None` must read `_D6_STREAMS`, the ONE place the stream count lives.

    Asserted as a PROPERTY (the default equals an explicit `len(_D6_STREAMS)`), never
    as an exact set of provider names — the exact-set trap is what turned phase 15.5's
    merged tree red, and `research_division` documents this import as length-only.
    """
    n = len(_pipeline_mod._D6_STREAMS)
    angles = _copies("g1", n) + _copies("g2", n)
    groups = [_group("g1"), _group("g2")]
    assert _pipeline_mod._dispatch_was_uniform(angles, groups) is True
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=n) is True
    assert _pipeline_mod._dispatch_was_uniform(angles, groups, streams=n + 1) is False
