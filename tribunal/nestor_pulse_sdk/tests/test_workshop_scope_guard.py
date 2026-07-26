"""D4's scope guard — the workshop may add depth but NEVER change scope.

WHAT THIS FILE COVERS (plan 15.2-11):
  * the superset invariant itself: the winners' `parents` UNION covers every
    client-validated question label, asserted in PYTHON and not requested in a
    prompt;
  * the union over `parents` (plural) rather than `parent`, which is what stops a
    near-duplicate collapse from producing a FALSE scope violation;
  * promotion of a below-the-cut candidate before verbatim injection;
  * injected and promoted winners ranked FIRST, and the whole list re-ranked
    densely from 1 — the rank plan 15.2-13 derives its D6 stakes from;
  * the loud WARNING per injection, and the deliberate split between
    `workshop_notes` (an injection does NOT degrade a run) and
    `degradation_reasons` (a full fallback does);
  * `run_workshop_stage_b`'s exact JSON-safe contract, its never-raise
    guarantee, its no-operator-pause guarantee, and the fact that it leaves the
    `workshop` stage feed OPEN for plan 15.2-13.

THIS FILE MAKES ZERO LLM CALLS, OPENS NO DATABASE, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. Every provider call is served by the shared hand-written fake
from `test_workshop_tournament.py`, which subclasses plan 15.2-10's
`workshop_fakes.ScriptedWorkshopAudited`. No test here carries
`@pytest.mark.live`, nothing can flake on the network, and nothing spends.

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import json
import pathlib
import uuid
from typing import Any, Optional

from nestor_pulse_sdk.pipeline.tribunal import workshop_rank
from nestor_pulse_sdk.tests.test_workshop_tournament import (
    FeedRecorder,
    JudgeAudited,
    flash_responder,
    make_feed,
)
from nestor_pulse_sdk.tests.workshop_fakes import FakeTextResponse

RUN_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()

#: The module under test, read once. Resolved from THIS file's location, never
#: from a repo root: Cloud Build ships only `tribunal/`, so a repo-root path
#: would not exist in the gate container (Pitfall 8).
_RANK_SRC = (
    pathlib.Path(__file__).resolve().parents[1]
    / "pipeline"
    / "tribunal"
    / "workshop_rank.py"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def win(
    index: int,
    parent: str,
    *,
    parents: Optional[list[str]] = None,
    rank: Optional[int] = None,
    source: str = "model",
    text: Optional[str] = None,
) -> dict[str, Any]:
    """One evolved winner, in `evolve_winners`' real output shape."""
    return {
        "index": index,
        "text": text if text is not None
        else f"winner {index:02d} — a sharp sub-question deepening {parent}",
        "parent": parent,
        "parents": list(parents) if parents is not None else [parent],
        "source": source,
        "rank": rank if rank is not None else index + 1,
        "langs": ["en"],
        "wins": 0,
        "elo": 1200.0,
        "critique": "KEEP",
        "flaw": "",
    }


def parent_union(winners: list[dict[str, Any]]) -> set[str]:
    """The assertion 15.2-10's SUMMARY spells out, verbatim."""
    union: set[str] = set()
    for winner in winners:
        union.update(winner.get("parents") or [winner["parent"]])
    return union


def stage_a(
    labels: list[str],
    candidate_parents: list[str],
    *,
    fallback: bool = False,
    source: str = "model",
    reasons: Optional[list[str]] = None,
) -> dict[str, Any]:
    """A `run_workshop_stage_a` return value, in its real documented shape."""
    return {
        "questions": [
            {
                "label": label,
                "text": f"client question {label} — what the client actually asked",
                "source": "caller",
            }
            for label in labels
        ],
        "orientation": [],
        "brief_conflicts": [{"question": labels[0], "assumption": "a", "world_says": "b",
                             "source_url": ""}],
        "candidates": [
            {
                "index": i,
                "text": f"candidate {i:02d} — a sharp sub-question deepening {parent}",
                "parent": parent,
                "parents": [parent],
                "source": source,
                "cluster_key": f"__singleton__:{i}",
                "merged_from": [],
            }
            for i, parent in enumerate(candidate_parents)
        ],
        "degradation_reasons": list(reasons or []),
        "stage_a_fallback": bool(fallback),
        "counts": {},
    }


def evolve_reply(total: int) -> FakeTextResponse:
    """A well-formed fenced evolve response for `total` winners."""
    lines = [workshop_rank._WINNERS_START]
    lines += [
        f"{i} | sharpened winning question number {i} for this client | LANGS: en"
        for i in range(total)
    ]
    lines.append(workshop_rank._WINNERS_END)
    return FakeTextResponse("\n".join(lines))


def working_fake(evolve_for: int = 12) -> JudgeAudited:
    """A fake that answers the critique, the tournament AND the evolve step."""
    return JudgeAudited(
        flash_responder(), anthropic_script=[evolve_reply(evolve_for)]
    )


async def stage_b(audited: Any, source: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return await workshop_rank.run_workshop_stage_b(
        stage_a=source,
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        **kwargs,
    )


# ===========================================================================
# SECTION 1 — the guard itself (pure, no fake, no call)
# ===========================================================================


def test_superset_holds_on_the_happy_path():
    """1. Full cover: nothing injected, nothing noted, ranks stay dense."""
    labels = ["Q1", "Q2", "Q3", "Q4"]
    winners = [win(i, labels[i]) for i in range(4)]

    final, notes, injected = workshop_rank.enforce_scope_guard(
        winners=winners, client_questions=labels
    )

    assert injected == []
    assert notes == []
    assert set(labels) <= parent_union(final)
    assert [w["rank"] for w in final] == [1, 2, 3, 4]


def test_missing_client_question_is_injected_verbatim_and_ranked_first():
    """2. The injection goes to the TOP, in client-question order."""
    labels = ["Q1", "Q2", "Q3", "Q4"]
    texts = {label: f"the client's own wording for {label}, verbatim" for label in labels}
    winners = [win(0, "Q3"), win(1, "Q4")]

    final, notes, injected = workshop_rank.enforce_scope_guard(
        winners=winners, client_questions=labels, question_texts=texts
    )

    assert injected == ["Q1", "Q2"]
    assert len(notes) == 2
    assert [w["parent"] for w in final] == ["Q1", "Q2", "Q3", "Q4"]
    assert [w["rank"] for w in final] == [1, 2, 3, 4]
    for position, label in enumerate(("Q1", "Q2")):
        assert final[position]["source"] == "verbatim"
        assert final[position]["scope_injected"] is True
        assert final[position]["text"] == texts[label]
    assert set(labels) <= parent_union(final)


def test_a_below_the_cut_candidate_is_promoted_before_verbatim_injection():
    """3. A real sub-question beats raw question text."""
    labels = ["Q1", "Q2"]
    winners = [win(0, "Q1", rank=1)]
    all_ranked = [
        win(0, "Q1", rank=1),
        win(5, "Q2", rank=7),
        win(6, "Q2", rank=9),
    ]

    final, notes, injected = workshop_rank.enforce_scope_guard(
        winners=winners, client_questions=labels, all_ranked=all_ranked
    )

    assert injected == ["Q2"]
    assert final[0]["index"] == 5, "the BEST-ranked below-the-cut candidate"
    assert final[0]["source"] == "model"
    assert final[0]["source"] != "verbatim"
    assert final[0]["scope_injected"] is True
    assert final[0]["rank"] == 1
    assert any("promoted" in note for note in notes), notes
    assert set(labels) <= parent_union(final)


def test_parents_union_prevents_a_false_uncovered():
    """4. THE REGRESSION TEST for 15.2-10's parent-union rule."""
    labels = ["Q1", "Q2"]
    merged = win(0, "Q1", parents=["Q1", "Q2"])

    final, notes, injected = workshop_rank.enforce_scope_guard(
        winners=[merged], client_questions=labels
    )

    assert injected == [], "Q2 is genuinely covered by the merged representative"
    assert notes == []
    assert len(final) == 1

    # The negative half, stated explicitly: a guard reading only `parent` would
    # have seen a strict subset of the labels and injected Q2 needlessly.
    parent_only = {w["parent"] for w in [merged]}
    assert parent_only < set(labels)
    assert parent_union([merged]) == set(labels)


def test_injection_is_logged_loudly(caplog):
    """5. Every injection produces exactly one WARNING naming the question."""
    labels = ["Q1", "Q2", "Q3"]
    winners = [win(0, "Q1")]

    with caplog.at_level("WARNING", logger="nestor_pulse_sdk.pipeline.tribunal.workshop_rank"):
        _, _, injected = workshop_rank.enforce_scope_guard(
            winners=winners, client_questions=labels
        )

    assert injected == ["Q2", "Q3"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 2, [r.getMessage() for r in warnings]
    joined = " ".join(r.getMessage() for r in warnings)
    assert "Q2" in joined and "Q3" in joined


def test_scope_guard_is_idempotent():
    """7. Running the guard on its own output changes nothing."""
    labels = ["Q1", "Q2", "Q3"]
    winners = [win(0, "Q1")]

    once, notes_one, injected_one = workshop_rank.enforce_scope_guard(
        winners=winners, client_questions=labels
    )
    twice, notes_two, injected_two = workshop_rank.enforce_scope_guard(
        winners=once, client_questions=labels
    )

    assert injected_one == ["Q2", "Q3"]
    assert injected_two == []
    assert notes_two == []
    assert [w["rank"] for w in twice] == [w["rank"] for w in once]
    assert [w["parent"] for w in twice] == [w["parent"] for w in once]
    assert [w["text"] for w in twice] == [w["text"] for w in once]


# ===========================================================================
# SECTION 2 — the guard inside run_workshop_stage_b
# ===========================================================================


async def test_scope_injection_is_a_note_not_a_degradation():
    """6. D-12's alarm-fatigue rule: an injection is a NOTE, not a degradation."""
    source = stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2"])

    result = await stage_b(working_fake(), source)

    assert result["workshop_fallback"] is False
    assert any("Q3" in note for note in result["workshop_notes"]), result["workshop_notes"]
    assert not any(
        "injected" in reason or "promoted" in reason
        for reason in result["degradation_reasons"]
    ), result["degradation_reasons"]
    assert result["counts"]["scope_injected"] == 1
    assert set(result["client_questions"]) <= parent_union(result["winners"])


async def test_full_fallback_sets_workshop_fallback_and_degrades():
    """8. Every call raises: the run degrades, it does not fail."""
    labels = ["Q1", "Q2", "Q3", "Q4"]
    source = stage_a(labels, labels, fallback=True, source="verbatim")
    boom = JudgeAudited(None, raise_on_call=RuntimeError("the provider refused"))

    result = await stage_b(boom, source)

    assert result["workshop_fallback"] is True
    assert len(result["winners"]) == len(result["client_questions"])
    assert [w["rank"] for w in result["winners"]] == [1, 2, 3, 4]
    assert result["degradation_reasons"]
    for reason in result["degradation_reasons"]:
        assert len(reason) > 40, reason
    assert set(labels) <= parent_union(result["winners"])


async def test_stage_a_fallback_propagates_to_workshop_fallback():
    """9. Propagate the upstream flag; never recompute it from the winners."""
    source = stage_a(
        ["Q1", "Q2"], ["Q1", "Q2"], fallback=True, reasons=["x" * 50]
    )

    result = await stage_b(working_fake(), source)

    assert result["workshop_fallback"] is True
    assert "x" * 50 in result["degradation_reasons"], result["degradation_reasons"]


async def test_every_winner_carries_a_dense_rank():
    """10. What plan 15.2-13's `_stakes_for_rank` derivation depends on."""
    cases = [
        # happy path — every client question covered
        (stage_a(["Q1", "Q2"], ["Q1", "Q2", "Q1"]), working_fake()),
        # partial cover — the guard injects
        (stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2"]), working_fake()),
        # full fallback — every call raises
        (
            stage_a(["Q1", "Q2"], ["Q1", "Q2"], fallback=True, source="verbatim"),
            JudgeAudited(None, raise_on_call=RuntimeError("the provider refused")),
        ),
    ]
    for source, audited in cases:
        result = await stage_b(audited, source)
        winners = result["winners"]
        assert winners
        assert [w["rank"] for w in winners] == list(range(1, len(winners) + 1))
        assert all(isinstance(w["rank"], int) for w in winners)
        assert set(result["client_questions"]) <= parent_union(winners)


async def test_result_matches_the_15_2_13_contract():
    """11. Exact keys, exact winner types, and the whole thing JSON-safe."""
    source = stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2", "Q3", "Q1"])

    result = await stage_b(
        working_fake(),
        source,
        run_language="Nederlands",
        deep_research_prompt="the whole brief, as one prompt",
    )

    assert set(result) == {
        "winners",
        "workshop_fallback",
        "language",
        "deep_research_prompt",
        "client_questions",
        "brief_conflicts",
        "degradation_reasons",
        "workshop_notes",
        "counts",
    }
    assert result["language"] == "Nederlands"
    assert result["deep_research_prompt"] == "the whole brief, as one prompt"
    assert result["client_questions"] == ["Q1", "Q2", "Q3"]
    assert result["brief_conflicts"] == source["brief_conflicts"]
    assert isinstance(result["workshop_fallback"], bool)
    for winner in result["winners"]:
        assert isinstance(winner["text"], str) and winner["text"]
        assert isinstance(winner["langs"], list) and winner["langs"]
        assert isinstance(winner["parent"], str) and winner["parent"]
        assert isinstance(winner["rank"], int)
    assert set(result["counts"]) == {
        "candidates_in",
        "killed",
        "ranked",
        "winners",
        "scope_injected",
        "matches_unjudged",
    }
    # No Decimal, no UUID, no set anywhere in the contract.
    assert json.loads(json.dumps(result))["counts"]["candidates_in"] == 4


async def test_stage_b_never_pauses_and_makes_no_live_call():
    """12. D5 / D-01, plus the fake accounting for every call that was made."""
    assert "needs_input" not in _RANK_SRC
    assert "clarifying_questions" not in _RANK_SRC
    assert "input(" not in _RANK_SRC

    audited = working_fake()
    result = await stage_b(audited, stage_a(["Q1", "Q2"], ["Q1", "Q2", "Q1"]))

    assert audited.call_count == len(audited.anthropic_calls) + len(audited.gemini_calls)
    assert audited.call_count > 0
    assert audited.unscripted == [], audited.unscripted
    assert result["winners"]


async def test_stage_b_does_not_close_the_feed():
    """13. Plan 15.2-13 owns the stage's lifetime — stage B only flushes."""
    recorder = FeedRecorder()
    feed = make_feed(recorder)

    await stage_b(working_fake(), stage_a(["Q1", "Q2"], ["Q1", "Q2"]), feed=feed)

    handle = await feed.add("division", status="running")
    await feed.flush()

    assert handle >= 0, "the feed went inert — plan 15.2-13's rows would be no-ops"
    assert "division" in [i["name"] for i in recorder.last_items]
    assert recorder.calls[-1]["stage_key"] == "workshop"


async def test_winners_appear_in_the_feed_as_rows():
    """14. D5's visibility promise / D15's "12 winning questions chosen" line."""
    recorder = FeedRecorder()
    feed = make_feed(recorder)

    result = await stage_b(
        working_fake(), stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2", "Q3"]), feed=feed
    )
    await feed.flush()

    names = [i["name"] for i in recorder.last_items]
    by_name = {i["name"]: i for i in recorder.last_items}
    for winner in result["winners"]:
        expected = winner["text"][:60]
        assert expected in names, (expected, names)
        prompt = by_name[expected].get("task_prompt")
        assert prompt is None or len(prompt) <= 401
    assert recorder.calls[-1]["detail"]["summary"]["items_read"] == result["counts"]["ranked"]
