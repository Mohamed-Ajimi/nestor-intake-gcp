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

WHAT PHASE 15.6 PLAN 04 ADDED (section 3 onwards): the SAME assertion one level
up, over the GROUPS an LLM now proposes.
  * `enforce_group_coverage` counting MANDATE MEMBERS and not mandate groups, so
    neither a `d1` cross-cutting group nor a discovery RIDER sitting inside a
    client question's own group can stand in for that question (D-W3-5);
  * the repair going to the TOP as its own new group, ranked first, because
    stakes and stream treatment derive from `rank`;
  * the ceiling ladder and its precedence — room in the mandate's allowance, else
    drop the cross-cutting group, else exceed the ceiling loudly, because D4 is a
    SCOPE invariant and D-W3-1's five is a SPEND dial;
  * idempotence and the never-raise guarantee, both driven rather than asserted;
  * a rider costing NO group and NO extra call, so with no cross-cutting question
    the mandate keeps all five slots (D-W3-5.3, the 9-12-not-15 saving);
  * GAP A (the mandate keeps its slots) and GAP B (an oversized host sheds riders,
    never winners);
  * the D-12 split held across the new step: a grouping FULL fallback DEGRADES, a
    coverage repair only NOTES.

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

import contextlib
import json
import pathlib
import uuid
from decimal import Decimal
from typing import Any, Optional

from nestor_pulse_sdk.pipeline.tribunal import (
    discovery_bracket,
    question_grouping,
    workshop_loop,
    workshop_rank,
)
from nestor_pulse_sdk.tests.test_workshop_tournament import (
    FeedRecorder,
    JudgeAudited,
    flash_responder,
    make_feed,
)
from nestor_pulse_sdk.tests.workshop_fakes import (
    FakeTextResponse,
    FakeToolUseResponse,
)

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


def rider(
    text: str, parent: str, *, rank: int = 0, source: str = "discovery"
) -> dict[str, Any]:
    """One DISCOVERY question, in `allocate_discovery`'s real output shape.

    `parent` is a client-question label for a RIDER and
    `discovery_bracket.DISCOVERY_PARENT` for a cross-cutting question. `source` is
    what the coverage rule reads, and it is what makes this a discovery MEMBER
    rather than a client one.
    """
    return {
        "text": text,
        "parent": parent,
        "parents": [parent],
        "rank": rank,
        "langs": [],
        "source": source,
        "scope_injected": False,
        "bracket": "discovery",
        "provenance": {
            "question": parent,
            "assumption": "the brief assumes something",
            "world_says": "a source read during orientation disagrees",
            "source_url": "https://example.test/a",
        },
    }


def conflict(
    question: str,
    *,
    url: str = "https://example.test/a",
    assumption: str = "the brief assumes this is settled",
) -> dict[str, Any]:
    """One sourced brief-vs-world conflict, in stage A's real shape."""
    return {
        "question": question,
        "assumption": assumption,
        "world_says": "a source read during orientation says otherwise",
        "source_url": url,
    }


def mandate_group(*label_and_count: tuple[str, int]) -> tuple[list, list]:
    """`(groups, winners)` — one mandate group per (label, member count) pair.

    Built through `question_grouping.build_groups`, never by hand, so the record
    under test is the one production stamps.
    """
    winners: list[dict[str, Any]] = []
    assignment: list[list[int]] = []
    for label, count in label_and_count:
        indices = []
        for _ in range(count):
            indices.append(len(winners))
            winners.append(win(len(winners), label))
        assignment.append(indices)
    return question_grouping.build_groups(assignment, winners), winners


def cross_cutting_group(text: str = "a finding that bears on every question") -> list:
    """The ONE `d1` group, built through production's own builder."""
    return question_grouping.build_groups(
        [[0]],
        [rider(text, discovery_bracket.DISCOVERY_PARENT, rank=99)],
        bracket=question_grouping.GROUP_BRACKET_DISCOVERY,
    )


def group_reply(*member_lists: list[int]) -> FakeToolUseResponse:
    """A well-formed `emit_question_groups` turn. `member_numbers` are 1-BASED.

    Naming ONE winner is enough: `validate_groups` is TOTAL, so every winner the
    model did not name is placed deterministically rather than dropped. That keeps
    this helper independent of however many winners the tournament cut produced.
    """
    return FakeToolUseResponse(
        "emit_question_groups",
        {
            "groups": [
                {"member_numbers": list(numbers), "why_grouped": "shared groundwork"}
                for numbers in (member_lists or ([1],))
            ]
        },
    )


#: The one substring that tells the grouping prompt apart from the evolve prompt.
#: Taken from `question_grouping._build_group_prompt`'s own heading.
GROUP_PROMPT_MARKER = "RESEARCH QUESTIONS TO GROUP"


def stage_a(
    labels: list[str],
    candidate_parents: list[str],
    *,
    fallback: bool = False,
    source: str = "model",
    reasons: Optional[list[str]] = None,
    conflicts: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """A `run_workshop_stage_a` return value, in its real documented shape.

    `conflicts` defaults to the ONE UNSOURCED flag this file has always used, so
    every pre-15.6 test still allocates ZERO discovery questions — no source, no
    slot. Pass real ones to exercise the bracket.
    """
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
        "brief_conflicts": list(
            conflicts
            if conflicts is not None
            else [{"question": labels[0], "assumption": "a", "world_says": "b",
                   "source_url": ""}]
        ),
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


def working_fake(
    evolve_for: int = 12,
    *,
    groups: Optional[list[list[int]]] = None,
    group_response: Any = None,
) -> JudgeAudited:
    """A fake answering the critique, the tournament, the evolve step AND grouping.

    The anthropic script is a DICT keyed on the grouping prompt's own heading, not a
    positional list, so the two anthropic turns cannot be served in the wrong order
    however the stage reorders its calls. `""` is the fall-through key for the
    evolve turn (`ScriptedWorkshopAudited._serve`).

    `group_response` overrides the grouping turn outright — that is how a test
    drives the no-tool_use-block fallback without touching the evolve turn.
    """
    grouping = (
        group_response
        if group_response is not None
        else group_reply(*(groups or [[1]]))
    )
    return JudgeAudited(
        flash_responder(),
        anthropic_script={
            GROUP_PROMPT_MARKER: [grouping],
            "": [evolve_reply(evolve_for)],
        },
    )


async def stage_b(audited: Any, source: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    return await workshop_rank.run_workshop_stage_b(
        stage_a=source,
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        **kwargs,
    )


@contextlib.contextmanager
def grouping_mode(mode: str):
    """Pin `question_grouping._GROUPING_MODE` for one test.

    D-W4-4a (phase 15.7) made ONE GROUP PER CLIENT QUESTION the primary path, and on
    that path the grouping step builds NO PROMPT and makes NO CALL. Every assertion
    about what the grouping model was TOLD, and every assertion about the grouping
    step's own fallback degradation, is therefore about `topic` mode specifically and
    says so by entering this block.

    A test that does NOT enter this block runs on the production default, which is
    what most of this file wants — the scope guard and the discovery allocation are
    the same either way.
    """
    previous = question_grouping._GROUPING_MODE
    question_grouping._GROUPING_MODE = mode
    try:
        yield
    finally:
        question_grouping._GROUPING_MODE = previous


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

    # Phase 15.6 plan 04 added `groups`, `discovery` and
    # `discovery_not_researched`. The exact set is kept exact — this file and
    # `_stage_b_result` are owned together, so pinning the whole contract here is
    # the discriminating assertion rather than a merge hazard.
    assert set(result) == {
        "winners",
        "workshop_fallback",
        "language",
        "deep_research_prompt",
        "client_questions",
        "brief_conflicts",
        "groups",
        "discovery",
        "discovery_not_researched",
        "degradation_reasons",
        "workshop_notes",
        "counts",
        # WAVE 4 added `loop_rounds` — the per-round ledger the loop writes.
        "loop_rounds",
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
        "groups",
        "mandate_groups",
        "discovery_questions",
        "discovery_riders",
        "discovery_cross_cutting",
        "discovery_not_researched",
        "group_coverage_injected",
        # WAVE 4's six. `rounds` and `loop_born_winners` are the loop's own
        # accounting; `barred` and `dropped_as_reproposal` are the admission
        # gate's; `grounded_lookups` and `admitted_angles` are the grounding
        # stage's. All six are plain ints so the rollup stays JSON-safe.
        "rounds",
        "loop_born_winners",
        "barred",
        "dropped_as_reproposal",
        "grounded_lookups",
        "admitted_angles",
    }
    assert all(isinstance(value, int) for value in result["counts"].values())
    # No Decimal, no UUID, no set anywhere in the contract.
    assert json.loads(json.dumps(result))["counts"]["candidates_in"] == 4
    # `loop_rounds` IS THE OTHER JSON HAZARD, and the reason it is asserted here
    # rather than trusted: it is the only part of the contract carrying money.
    # `cost_usd` is a STRING on purpose — a Decimal serialises to a TypeError and
    # a float silently loses cents. Round-tripping the WHOLE result above already
    # covers it, but this names the trap so nobody "tidies" the type.
    assert isinstance(result["loop_rounds"], list)
    for entry in result["loop_rounds"]:
        assert isinstance(entry["round_no"], int)
        assert isinstance(entry["cost_usd"], str), type(entry["cost_usd"])
    # `groups` is what `divide(..., groups=...)` consumes, so it is never empty
    # while there is a winner.
    assert result["groups"]
    # MANDATE ids are dense from g1 IN LIST ORDER; the cross-cutting group keeps
    # `d1`. The previous form asserted density over ALL groups, which contradicts
    # `_restamp_groups` — it would have gone red the first time a fixture produced
    # a cross-cutting conflict, and for entirely the wrong reason.
    mandate_ids = [
        g["group_id"] for g in result["groups"] if not str(g["group_id"]).startswith("d")
    ]
    assert mandate_ids == [f"g{i + 1}" for i in range(len(mandate_ids))]
    discovery_ids = [
        g["group_id"] for g in result["groups"] if str(g["group_id"]).startswith("d")
    ]
    assert discovery_ids in ([], ["d1"]), "there is at most one, and never a d2"


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


# ===========================================================================
# SECTION 3 — enforce_group_coverage, the same assertion over the GROUPS.
# Phase 15.6 plan 04. Pure: no fake, no call, no await.
# ===========================================================================


def test_a_dropped_client_question_is_put_back_at_the_top_ranked_first():
    """THE § 8 WAVE 3 REQUIREMENT, driven directly.

    Fifteen winners covering Q1/Q2/Q3 are grouped, then Q2's members are deleted
    from every group — which is exactly what an LLM that drops a question does.
    Python must put Q2 back, as its own group at the HEAD of the list, with its
    winner ranked FIRST. Placement is load-bearing: stakes and stream treatment
    derive from `rank`, so a repaired client question at the bottom would get the
    weakest treatment.
    """
    labels = ["Q1", "Q2", "Q3"]
    winners = [win(i, labels[i % 3]) for i in range(15)]
    groups = question_grouping.build_groups(
        [[i for i in range(15) if winners[i]["parent"] == label] for label in labels],
        winners,
    )
    assert len(groups) == 3

    stripped = []
    for group in groups:
        keep = [m for m in group["members"] if m["parent"] != "Q2"]
        if keep:
            copy = dict(group)
            copy["members"] = keep
            copy["client_parents"] = [p for p in group["client_parents"] if p != "Q2"]
            copy["parents"] = [p for p in group["parents"] if p != "Q2"]
            stripped.append(copy)
    assert all("Q2" not in g["client_parents"] for g in stripped)

    texts = {label: f"the client's own wording for {label}" for label in labels}
    out_groups, out_winners, notes, injected = workshop_rank.enforce_group_coverage(
        groups=stripped,
        winners=[w for w in winners if w["parent"] != "Q2"],
        client_questions=labels,
        question_texts=texts,
        max_groups=5,
    )

    assert injected == ["Q2"]
    assert out_groups[0]["client_parents"] == ["Q2"], "the repair is at the HEAD"
    assert out_groups[0]["members"][0]["rank"] == 1
    assert out_groups[0]["members"][0]["scope_injected"] is True
    assert out_winners[0]["parent"] == "Q2" and out_winners[0]["rank"] == 1
    assert "Q2" in workshop_rank._covered_by_mandate_members(out_groups)
    assert len(notes) == 1 and "Q2" in notes[0]
    # The list is re-ranked densely, and every group's rank is its min member's.
    assert [w["rank"] for w in out_winners] == list(range(1, len(out_winners) + 1))
    assert all(
        g["rank"] == min(m["rank"] for m in g["members"]) for g in out_groups
    )
    assert [g["group_id"] for g in out_groups] == ["g1", "g2", "g3"]


def test_a_discovery_group_parented_on_q1_does_not_satisfy_q1():
    """The whole `d1` group is skipped: its members are not client questions."""
    discovery = question_grouping.build_groups(
        [[0]],
        [rider("a question the evidence raised about Q1", "Q1", rank=9)],
        bracket=question_grouping.GROUP_BRACKET_DISCOVERY,
    )
    assert discovery[0]["bracket"] == "discovery"
    q2_groups, q2_winners = mandate_group(("Q2", 1))

    _, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=discovery + q2_groups,
        winners=q2_winners,
        client_questions=["Q1", "Q2"],
        max_groups=5,
    )

    assert injected == ["Q1"], "a discovery group cannot stand in for Q1"


def test_a_discovery_rider_inside_q1s_own_group_does_not_satisfy_q1():
    """D-W3-5's REFINEMENT — the reason the rule counts MEMBERS, not GROUPS.

    A rider parented `"Q1"` rides inside Q1's own mandate group (D-W3-5.2). If Q1's
    own winners are then dropped, a GROUP-level rule would still read Q1 as
    covered — the client's question goes unresearched while a question the evidence
    raised about it stands in for it. The negative half is asserted too: the group
    DOES carry "Q1" in `parents`, so the group-level rule really would have said
    covered.
    """
    groups, winners = mandate_group(("Q1", 1))
    groups, shed, _ = question_grouping.attach_discovery_riders(
        groups, [rider("a question the evidence raised about Q1", "Q1", rank=9)],
    )
    assert shed == [] and groups[0]["riders"] == 1

    rider_only = dict(groups[0])
    rider_only["members"] = [
        m for m in groups[0]["members"] if m.get("source") == "discovery"
    ]
    assert len(rider_only["members"]) == 1

    _, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=[rider_only], winners=[], client_questions=["Q1"], max_groups=5
    )

    assert injected == ["Q1"]
    # The negative half, stated explicitly: the group-level rule would have passed.
    assert "Q1" in rider_only["parents"]


def test_a_discovery_bracket_group_never_counts_toward_coverage_whatever_its_members_are():
    """The GROUP-level skip, pinned INDEPENDENTLY of the member-level one.

    Both controls normally agree, because `allocate_discovery` stamps
    `source="discovery"` on every question it makes — so removing either one alone
    changes nothing observable. This drives the shape that separates them: a
    discovery-bracket group whose member looks like an ordinary winner, which
    `allocate_discovery` cannot produce but a hand-built or RESUMED group list can.
    The bracket alone must be enough to disqualify it.
    """
    plain = win(0, "Q1")
    assert plain["source"] != "discovery"
    forged = question_grouping.build_groups(
        [[0]], [plain], bracket=question_grouping.GROUP_BRACKET_DISCOVERY
    )
    assert forged[0]["bracket"] == "discovery"
    assert "Q1" in forged[0]["client_parents"], "the member reads as a client one"

    assert workshop_rank._covered_by_mandate_members(forged) == []

    _, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=forged, winners=[plain], client_questions=["Q1"], max_groups=5
    )
    assert injected == ["Q1"]


def test_the_cross_cutting_sentinel_is_ignored_not_repaired():
    """`__discovery__` is not a client question, so the guard neither counts nor
    repairs it — and its group survives untouched."""
    groups, winners = mandate_group(("Q1", 1), ("Q2", 1))
    out_groups, _, notes, injected = workshop_rank.enforce_group_coverage(
        groups=groups + cross_cutting_group(),
        winners=winners,
        client_questions=["Q1", "Q2"],
        max_groups=5,
    )

    assert injected == [] and notes == []
    assert discovery_bracket.DISCOVERY_PARENT not in (
        workshop_rank._covered_by_mandate_members(out_groups)
    )
    assert [g["group_id"] for g in out_groups if g["bracket"] == "discovery"] == ["d1"]


def test_the_group_guard_is_idempotent():
    """Running it on its own output changes nothing and reports nothing new.

    Driven THREE times, because an idempotence that only holds once is a
    coincidence — the second call is what a resumed run makes.
    """
    labels = ["Q1", "Q2", "Q3"]
    groups, winners = mandate_group(("Q1", 2), ("Q3", 2))

    first = workshop_rank.enforce_group_coverage(
        groups=groups, winners=winners, client_questions=labels, max_groups=5
    )
    second = workshop_rank.enforce_group_coverage(
        groups=first[0], winners=first[1], client_questions=labels, max_groups=5
    )
    third = workshop_rank.enforce_group_coverage(
        groups=second[0], winners=second[1], client_questions=labels, max_groups=5
    )

    assert first[3] == ["Q2"], "the first call really did repair something"
    assert second[2] == [] and second[3] == []
    assert second[0] == first[0] and second[1] == first[1]
    assert third[0] == first[0] and third[1] == first[1]
    assert third[2] == [] and third[3] == []


def test_the_group_guard_never_raises():
    """Twelve hostile shapes, each returning a 4-tuple rather than an exception.

    The guard runs between an LLM's output and three paid providers, so a shape it
    has never seen must degrade rather than end the run — the same guarantee
    `enforce_scope_guard` carries.
    """
    groups, winners = mandate_group(("Q1", 2))
    hostile: list[dict[str, Any]] = [
        {"groups": None, "winners": winners, "client_questions": ["Q1"]},
        {"groups": "x", "winners": winners, "client_questions": ["Q1"]},
        {"groups": ["a string, not a group"], "winners": winners,
         "client_questions": ["Q1"]},
        {"groups": [{"bracket": "mandate"}], "winners": winners,
         "client_questions": ["Q1"]},
        {"groups": [{"bracket": "mandate", "members": None}], "winners": [],
         "client_questions": ["Q1"]},
        {"groups": [{"bracket": "mandate", "members": ["nope", 3, None]}],
         "winners": [], "client_questions": ["Q1"]},
        {"groups": [{"bracket": "mandate", "members": [{"text": "no parent"}]}],
         "winners": [], "client_questions": ["Q1"]},
        {"groups": groups, "winners": None, "client_questions": ["Q1"]},
        {"groups": groups, "winners": winners, "client_questions": None},
        {"groups": groups, "winners": winners, "client_questions": [""]},
        {"groups": groups, "winners": winners, "client_questions": ["Q1"],
         "all_ranked": ["nope", 7, None, {"parent": "Q9"}]},
        {"groups": groups, "winners": winners, "client_questions": ["Q1"],
         "question_texts": "not a mapping at all"},
        # The 13th, and the one that reaches the OUTER try rather than an inner
        # guard: `_parents_of` is shared with `enforce_scope_guard` and does
        # `list(entry["parents"] or [])`, so a non-iterable `parents` raises inside
        # the guard's body. The outer `try/except` is the control that makes this
        # safe, and this case is what pins it.
        {"groups": [{"bracket": "mandate",
                     "members": [{"parents": 5, "parent": "Q1", "text": "t"}]}],
         "winners": [], "client_questions": ["Q1"]},
    ]
    assert len(hostile) == 13

    for position, kwargs in enumerate(hostile):
        result = workshop_rank.enforce_group_coverage(**kwargs)
        assert isinstance(result, tuple) and len(result) == 4, position
        assert isinstance(result[0], list) and isinstance(result[1], list), position
        assert isinstance(result[2], list) and isinstance(result[3], list), position


def test_the_mandate_displaces_discovery_before_it_exceeds_the_ceiling():
    """RUNG 2. Four mandate groups plus `d1`, and one client question missing.

    D-W3-4 says nothing in the mandate may be displaced by a discovered question,
    so the displacement runs the other way: `d1` yields its slot, the mandate ends
    at five, and the dropped question comes back through `shed_out` so the caller
    can report it as raised-but-not-researched.
    """
    groups, winners = mandate_group(("P0", 1), ("P1", 1), ("P2", 1), ("P3", 1))
    shed: list[dict[str, Any]] = []

    out_groups, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=groups + cross_cutting_group(),
        winners=winners,
        client_questions=["P0", "P1", "P2", "P3", "MISSING"],
        max_groups=5,
        shed_out=shed,
    )

    assert injected == ["MISSING"]
    assert [g["bracket"] for g in out_groups] == ["mandate"] * 5
    assert not any(g["bracket"] == "discovery" for g in out_groups)
    assert len(shed) == 1
    assert shed[0]["parent"] == discovery_bracket.DISCOVERY_PARENT
    assert [g["group_id"] for g in out_groups] == ["g1", "g2", "g3", "g4", "g5"]


def test_coverage_outranks_the_ceiling_when_there_is_no_discovery_slot_to_take():
    """RUNG 3. Five mandate groups, no `d1`, one client question missing.

    D4 coverage is a SCOPE invariant and D-W3-1's five is a SPEND dial, so coverage
    wins and the run dispatches six. The rung is unreachable while the grouping
    partition is total; it is pinned so a future edit fails LOUDLY here rather than
    quietly shrinking the scope the operator validated.
    """
    groups, winners = mandate_group(*[(f"P{i}", 1) for i in range(5)])

    out_groups, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=groups,
        winners=winners,
        client_questions=[f"P{i}" for i in range(5)] + ["MISSING"],
        max_groups=5,
    )

    assert injected == ["MISSING"]
    assert len(out_groups) == 6, "coverage wins over the spend dial"
    assert all(g["bracket"] == "mandate" for g in out_groups)
    assert "MISSING" in workshop_rank._covered_by_mandate_members(out_groups)


def test_discovery_takes_a_slot_from_inside_the_five():
    """RUNG 1, and D-W3-1's "the discovery group counts INSIDE the 5".

    Three mandate groups plus `d1` leaves room under the allowance of four, so the
    repair is added and discovery is NOT touched.
    """
    groups, winners = mandate_group(("P0", 1), ("P1", 1), ("P2", 1))
    shed: list[dict[str, Any]] = []

    out_groups, _, _, injected = workshop_rank.enforce_group_coverage(
        groups=groups + cross_cutting_group(),
        winners=winners,
        client_questions=["P0", "P1", "P2", "MISSING"],
        max_groups=5,
        shed_out=shed,
    )

    assert injected == ["MISSING"]
    assert len([g for g in out_groups if g["bracket"] == "mandate"]) == 4
    assert len([g for g in out_groups if g["bracket"] == "discovery"]) == 1
    assert shed == [], "discovery kept its slot because the mandate had room"
    assert [g["group_id"] for g in out_groups if g["bracket"] == "discovery"] == ["d1"]


def test_a_promotion_beats_a_verbatim_injection_over_the_groups_too():
    """The repair ladder is `enforce_scope_guard`'s, unchanged in substance: a real
    below-the-cut sub-question beats raw client-question text."""
    groups, winners = mandate_group(("Q1", 1))
    all_ranked = [win(0, "Q1", rank=1), win(5, "Q2", rank=7), win(6, "Q2", rank=9)]

    out_groups, out_winners, notes, injected = workshop_rank.enforce_group_coverage(
        groups=groups,
        winners=winners,
        client_questions=["Q1", "Q2"],
        all_ranked=all_ranked,
        max_groups=5,
    )

    assert injected == ["Q2"]
    assert out_winners[0]["index"] == 5, "the BEST-ranked below-the-cut candidate"
    assert out_winners[0]["source"] == "model" != "verbatim"
    assert out_winners[0]["scope_injected"] is True
    assert out_winners[0]["rank"] == 1
    assert any("promoted" in note for note in notes), notes
    assert out_groups[0]["client_parents"] == ["Q2"]


def test_the_verbatim_winner_shape_is_one_shape_in_one_place():
    """Both D4 guards inject the SAME 12-key shape, through one helper.

    Three hand-maintained copies of one literal is three chances to drift, and a
    winner missing a key another module subscripts is a run-ending failure in the
    most expensive part of the pipeline.
    """
    twelve = {
        "text", "parent", "parents", "source", "scope_injected", "index", "langs",
        "wins", "elo", "byes", "critique", "flaw",
    }
    built = workshop_rank._verbatim_winner("Q1", {"Q1": "the client's own wording"})
    assert set(built) == twelve
    assert built["text"] == "the client's own wording"
    assert workshop_rank._verbatim_winner("Q9", {})["text"] == "Q9"
    assert workshop_rank._verbatim_winner("Q9", "not a mapping")["text"] == "Q9"

    # `enforce_scope_guard`'s own injection is the same shape plus the `rank`
    # `_rerank` stamps on the way out.
    from_guard, _, _ = workshop_rank.enforce_scope_guard(
        winners=[win(0, "Q3")], client_questions=["Q1", "Q3"]
    )
    assert set(from_guard[0]) == twelve | {"rank"}

    # And the group guard's injection matches it key for key.
    groups, winners = mandate_group(("Q3", 1))
    _, from_group_guard, _, _ = workshop_rank.enforce_group_coverage(
        groups=groups, winners=winners, client_questions=["Q1", "Q3"], max_groups=5
    )
    assert set(from_group_guard[0]) == set(from_guard[0])


def test_gap_b_an_over_supplied_host_sheds_riders_never_winners():
    """GAP B. When prompt space runs out, DISCOVERY yields — never a winner.

    REWRITTEN FOR CR-09; THE REQUIREMENT IS UNCHANGED. § 4 requirement 2 still
    caps questions per group because the risk is a provider writing six thin
    paragraphs instead of one deep report, and D-W3-4 still says discovery never
    borrows from the mandate. What changed is WHICH NUMBER ENFORCES IT.

    This test used to drive shedding with `max_size=4` — a TOTAL-SIZE cap that
    counted winners. That cap was retired because winners alone exhaust it: at the
    validated configuration a per-question group holds the 5-winner floor plus
    both cross-cutting winners, so the cap shed every rider and deleted the
    discovery bracket outright. CR-09 made `max_size` inert, and D-W4-10
    (2026-08-04) removed it from the signature altogether — so the old call no
    longer sheds anything and can no longer even be written.

    Shedding is now the RIDER BUDGET, counted over riders only — which is what
    makes "never a winner" true by construction instead of by a guard.
    """
    groups, winners = mandate_group(("Q1", 4))
    riders = [rider(f"a discovered question {i}", "Q1", rank=10 + i) for i in range(4)]

    out, shed, notes = question_grouping.attach_discovery_riders(
        groups, riders, max_riders=2
    )

    kept = out[0]["members"]
    assert [m["text"] for m in kept if m.get("source") != "discovery"] == [
        w["text"] for w in winners
    ], "all four winners survive"
    assert len(shed) == 2
    assert all(m.get("source") == "discovery" for m in shed), "a winner was shed"
    # THE WEAKEST RIDERS GO, and the strongest riders stay — ranks 13 and 12 are
    # shed, 10 and 11 are kept. Asserted because "sheds two" alone would pass on a
    # rule that picked arbitrarily.
    assert sorted(m["rank"] for m in shed) == [12, 13]
    assert sorted(m["rank"] for m in kept if m.get("source") == "discovery") == [10, 11]
    assert out[0]["riders"] == 2
    assert notes, "a shed rider is never silent"
    # The client's own question is still fully covered by MEMBERS.
    assert workshop_rank._covered_by_mandate_members(out) == ["Q1"]


def test_gap_b_the_winner_count_alone_never_sheds_a_rider():
    """GAP B's companion — and the CR-09 defect stated directly.

    The rewritten test above CANNOT catch a return to the total-size rule: with
    four winners and four riders a `len(members)` cap of 7 sheds exactly one rider
    too, so both rules agree on the observable outcome. Verified by mutation.

    This one separates them. The group is built at the shape that actually broke:
    seven winners — the 5-winner floor plus the two cross-cutting winners, which
    ARE parented to a real client label and so land inside a per-question group.
    Under the retired rule that group was full before a rider arrived. Every rider
    within budget must now survive regardless of how many winners sit beside it.
    """
    groups, winners = mandate_group(("Q1", 7))
    riders = [rider(f"a discovered question {i}", "Q1", rank=20 + i) for i in range(3)]

    out, shed, _ = question_grouping.attach_discovery_riders(
        groups, riders, max_riders=3
    )

    assert shed == [], "a winner count must not be able to shed a rider"
    assert out[0]["riders"] == 3
    assert len(out[0]["members"]) == len(winners) + 3


def test_discovery_ranks_below_every_winner_after_the_repair_grew_the_list():
    """The mandate can never be displaced, and the repair is why this is re-stamped.

    A rank stamped from the PRE-repair winner count collides with a winner's rank
    once the coverage guard prepends one, and a discovered question would then be
    handed a client question's stakes.
    """
    groups, winners = mandate_group(("Q1", 3))
    groups, _, _ = question_grouping.attach_discovery_riders(
        groups, [rider("a discovered question about Q1", "Q1", rank=4)]
    )
    dispatched = [rider("a discovered question about Q1", "Q1", rank=4)]

    groups, final, _, injected = workshop_rank.enforce_group_coverage(
        groups=groups, winners=winners, client_questions=["Q1", "Q2"], max_groups=5
    )
    assert injected == ["Q2"], "the repair really did grow the winners list"

    workshop_rank._stamp_discovery_ranks(groups, dispatched, base=len(final))

    highest_winner = max(w["rank"] for w in final)
    assert all(q["rank"] > highest_winner for q in dispatched)
    members = [
        m for g in groups for m in g["members"] if m.get("source") == "discovery"
    ]
    assert members and all(m["rank"] > highest_winner for m in members)


# ===========================================================================
# SECTION 4 — grouping and discovery inside run_workshop_stage_b.
# ===========================================================================


async def test_a_rider_costs_no_group_and_no_extra_call():
    """THE V-01 SHAPE, and the whole reason D-W3-5 was chosen.

    Both of run 7dcf51d5's `brief_conflicts` were about Q1. Under D-W3-5.2 both
    become RIDERS inside Q1's own mandate group, so NO discovery group exists,
    discovery consumes NO slot, and the mandate is offered all five — which is why
    V-01's three questions land at 9-12 calls rather than 15.

    RUN IN `topic` MODE (15.7-01). The last assertion — that the mandate was OFFERED
    the whole ceiling — is a claim about what the grouping model was TOLD, and the
    prompt is the only place that offer exists. On D-W4-4a's primary path there is no
    prompt to read it out of, so the assertion would have to be deleted rather than
    moved, and a deleted assertion is how D-W3-5.3's slot-rollback stops being
    checked. The rider arithmetic above holds in both modes; the OFFER only exists in
    this one.
    """
    labels = ["Q1", "Q2", "Q3"]
    source = stage_a(
        labels,
        labels * 2,
        conflicts=[conflict("Q1"), conflict("Q1", assumption="a second assumption")],
    )
    audited = working_fake(6, groups=[[1, 2, 3, 4, 5, 6]])

    with grouping_mode(question_grouping._GROUPING_MODE_TOPIC):
        result = await stage_b(audited, source)

    assert len(result["discovery"]) == 2
    assert not any(g["bracket"] == "discovery" for g in result["groups"])
    assert all(g["group_id"].startswith("g") for g in result["groups"])
    assert result["counts"]["discovery_cross_cutting"] == 0
    assert result["counts"]["discovery_riders"] == 2
    # Both riders sit inside Q1's own mandate group.
    q1_groups = [g for g in result["groups"] if "Q1" in g["client_parents"]]
    assert sum(g["riders"] for g in q1_groups) == 2
    # The saving is that NO slot was spent, not a fixed number of calls.
    angles = len(result["groups"]) * 3
    assert 9 <= angles <= 15, angles
    # The mandate was offered the whole ceiling.
    grouping_prompt = next(
        p for p in audited.anthropic_prompts() if GROUP_PROMPT_MARKER in p
    )
    assert f"AT MOST {question_grouping._D6_MAX_GROUPS} groups" in grouping_prompt
    # And no discovered question ever became a winner.
    assert not (
        {w["text"] for w in result["winners"]} & {q["text"] for q in result["discovery"]}
    )
    highest = max(w["rank"] for w in result["winners"])
    assert all(q["rank"] > highest for q in result["discovery"])


async def test_a_cross_cutting_question_earns_exactly_one_group_called_d1():
    """Only a `__discovery__` question earns a group, and there is never a `d2`."""
    labels = ["Q1", "Q2", "Q3"]
    source = stage_a(
        labels, labels * 4, conflicts=[conflict("not one of the client's labels")]
    )

    result = await stage_b(working_fake(groups=[[1]]), source)

    discovery_groups = [g for g in result["groups"] if g["bracket"] == "discovery"]
    assert len(discovery_groups) == 1
    assert discovery_groups[0]["group_id"] == "d1"
    assert len([g for g in result["groups"] if g["bracket"] == "mandate"]) <= 4
    assert result["counts"]["discovery_cross_cutting"] == 1
    assert len(result["discovery"]) == 1


async def test_no_discovery_and_the_mandate_gets_all_five():
    """An unsourced flag takes no slot, so the unused slot rolls back — effected by
    the ceiling subtraction NOT happening (D-W3-5.3).

    RUN IN `topic` MODE (15.7-01), for the same reason as the rider test above: the
    "gets all five" half is observable ONLY in the prompt's offer. `no source, no
    slot` itself is mode-independent and is asserted after the block.
    """
    labels = ["Q1", "Q2", "Q3"]
    source = stage_a(
        labels,
        labels * 4,
        conflicts=[conflict("Q1", url=""), conflict("Q2", url="ftp://not-fetched")],
    )
    audited = working_fake(groups=[[1]])

    with grouping_mode(question_grouping._GROUPING_MODE_TOPIC):
        result = await stage_b(audited, source)

    assert result["discovery"] == []
    assert result["discovery_not_researched"] == []
    assert not any(g["bracket"] == "discovery" for g in result["groups"])
    grouping_prompt = next(
        p for p in audited.anthropic_prompts() if GROUP_PROMPT_MARKER in p
    )
    assert f"AT MOST {question_grouping._D6_MAX_GROUPS} groups" in grouping_prompt
    assert any("no source, no slot" in note for note in result["workshop_notes"]), (
        result["workshop_notes"]
    )


async def test_gap_a_the_mandate_keeps_its_slots_and_the_cross_cutting_group_is_dropped():
    """GAP A — the case D-W3-5 does not cover, and the default recorded for it.

    Five client questions already need five single-parent mandate groups, so a `d1`
    would leave four. THE MANDATE WINS: no `d1` is created, the cross-cutting
    question comes back under `discovery_not_researched`, and it is a NOTE rather
    than a degradation because every client question is researched in full.

    MOVED ONTO THE PRIMARY PATH BY 15.7-01, rather than pinned to `topic` like the
    two tests above. The reason is that GAP A's claim is *"the mandate keeps its five
    slots"*, and on D-W4-4a's primary path that is observable DIRECTLY — five client
    questions produce five mandate groups, asserted below — instead of indirectly via
    what the grouping model was offered in a prompt. Asserting it on the path that
    actually runs in production is strictly stronger than asserting it on the option.
    The `AT MOST … groups` assertion is therefore not deleted but REPLACED by its
    primary-path counterpart: no grouping prompt is built at all, which is what makes
    "the mandate got all five" a fact about Python's own arithmetic rather than about
    a sentence a model may ignore.
    """
    labels = ["Q1", "Q2", "Q3", "Q4", "Q5"]
    source = stage_a(
        labels, labels * 3, conflicts=[conflict("not a client label at all")]
    )
    audited = working_fake(15, groups=[[1]])

    result = await stage_b(audited, source)

    assert not any(g["bracket"] == "discovery" for g in result["groups"])
    assert len([g for g in result["groups"] if g["bracket"] == "mandate"]) == 5
    assert len(result["discovery_not_researched"]) == 1
    assert result["discovery"] == []
    assert result["counts"]["discovery_not_researched"] == 1
    assert any(
        "were not researched this run" in note for note in result["workshop_notes"]
    ), result["workshop_notes"]
    assert not any(
        "were not researched this run" in reason
        for reason in result["degradation_reasons"]
    ), "holding the mandate line is not a degradation"
    # THE PRIMARY-PATH COUNTERPART of the old `AT MOST {N} groups` prompt assertion.
    # The mandate did not have to be OFFERED five slots by a sentence in a prompt —
    # it took five because there are five client questions, and no grouping prompt
    # was built at all. `len(mandate groups) == 5` above is the same claim, proven
    # against the run's own output rather than against its input.
    assert not any(GROUP_PROMPT_MARKER in p for p in audited.anthropic_prompts()), (
        "the primary path must build no grouping prompt and make no grouping call"
    )
    assert not any(
        "produced nothing usable" in reason
        for reason in result["degradation_reasons"]
    ), "the configured primary path is not a degradation (D-12)"


async def test_a_grouping_failure_degrades_and_a_coverage_repair_only_notes():
    """D-12's alarm-fatigue rule, held across the new step.

    Both halves in one test, because the DISTINCTION is the thing being asserted: a
    grouping FULL fallback is a real degradation (shared groundwork gets searched
    once per question instead of once per topic), while a coverage repair is only a
    note (the question IS researched).

    PART (a) RUNS IN `topic` MODE (15.7-01). A grouping step can only FALL BACK if it
    ran, and only the `topic` path runs one. This is not the plan's three named
    prompt assertions but the same seam: without the pin, part (a)'s premise silently
    evaporates and the test would pass while asserting nothing. Part (b) is a scope
    repair and is mode-independent, so it deliberately stays on the default path —
    which also keeps the D-12 distinction asserted across BOTH grouping modes rather
    than only inside one.
    """
    labels = ["Q1", "Q2", "Q3"]
    # (a) the grouping turn returns no tool_use block at all.
    broken = working_fake(group_response=FakeTextResponse("I would rather not."))
    with grouping_mode(question_grouping._GROUPING_MODE_TOPIC):
        degraded = await stage_b(broken, stage_a(labels, labels * 4))

    assert any(
        "groups research questions" in reason
        for reason in degraded["degradation_reasons"]
    ), degraded["degradation_reasons"]
    assert all(len(reason) > 40 for reason in degraded["degradation_reasons"])
    assert not any(
        "groups research questions" in note for note in degraded["workshop_notes"]
    )
    assert degraded["groups"], "the deterministic fallback still returns groups"

    # (b) a scope repair NOTES and does not degrade.
    repaired = await stage_b(
        working_fake(groups=[[1]]), stage_a(labels, ["Q1", "Q2"])
    )
    assert any("Q3" in note for note in repaired["workshop_notes"])
    assert not any(
        "injected" in reason or "promoted" in reason
        for reason in repaired["degradation_reasons"]
    ), repaired["degradation_reasons"]


async def test_the_crash_path_still_carries_groups_and_discovery(monkeypatch):
    """A contract key that vanishes when degraded teaches the caller to use `.get()`.

    `divide()` cannot dispatch without `groups`, so the crash path builds D-W3-2's
    deterministic shape — one group per client question — and carries empty
    discovery lists rather than omitting the keys. The trigger is an unexpected
    internal failure, not a provider refusal: every provider call in this stage
    degrades internally and never reaches the `except`.
    """
    labels = ["Q1", "Q2", "Q3"]

    def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("an unexpected internal failure inside stage B")

    monkeypatch.setattr(workshop_rank, "_stamp_discovery_ranks", explode)

    result = await stage_b(working_fake(groups=[[1]]), stage_a(labels, labels * 4))

    assert result["workshop_fallback"] is True
    assert len(result["groups"]) == len(labels)
    assert all(g["bracket"] == "mandate" for g in result["groups"])
    assert result["discovery"] == []
    assert result["discovery_not_researched"] == []
    assert result["counts"]["groups"] == len(labels)
    assert json.loads(json.dumps(result))["counts"]["groups"] == len(labels)
    assert any(
        "ranking stage failed outright" in reason
        for reason in result["degradation_reasons"]
    ), result["degradation_reasons"]


async def test_stage_b_repairs_a_grouping_step_that_dropped_a_client_question(
    monkeypatch,
):
    """THE REASON THE GUARD IS ON THE CRITICAL PATH, driven through stage B.

    Today `validate_groups` returns a total partition, so nothing can be missing by
    the time the guard runs — which is exactly why the guard is otherwise invisible
    end to end. This drives the case it exists for: a grouping step that returns
    groups omitting a client question, i.e. the regression a future edit to
    `question_grouping` could introduce. Python must put the question back, and the
    run must say so in a NOTE rather than a degradation.
    """
    labels = ["Q1", "Q2", "Q3"]
    real = question_grouping.group_winners

    async def drops_q2(**kwargs: Any):
        groups, notes, reasons = await real(**kwargs)
        kept = []
        for group in groups:
            members = [m for m in group["members"] if m["parent"] != "Q2"]
            if not members:
                continue
            copy = dict(group)
            copy["members"] = members
            copy["client_parents"] = [
                p for p in group["client_parents"] if p != "Q2"
            ]
            copy["parents"] = [p for p in group["parents"] if p != "Q2"]
            kept.append(copy)
        return kept, notes, reasons

    monkeypatch.setattr(question_grouping, "group_winners", drops_q2)

    result = await stage_b(working_fake(groups=[[1]]), stage_a(labels, labels * 4))

    assert result["counts"]["group_coverage_injected"] >= 1, result["counts"]
    assert "Q2" in workshop_rank._covered_by_mandate_members(result["groups"])
    assert any("Q2" in note for note in result["workshop_notes"]), (
        result["workshop_notes"]
    )
    assert not any(
        "injected" in reason or "promoted" in reason
        for reason in result["degradation_reasons"]
    ), "a repair is a NOTE, never a degradation"
    # The repair is at the head of the group list and ranked first.
    assert result["groups"][0]["client_parents"] == ["Q2"]
    assert result["groups"][0]["members"][0]["rank"] == 1
    assert [w["rank"] for w in result["winners"]] == list(
        range(1, len(result["winners"]) + 1)
    )


async def test_the_grouping_call_is_counted_in_the_stage_actions_and_cost():
    """The grouping call is a PAID call and must show up in both meters.

    `group_winners` accumulates its spend under `cost` as a `Decimal`, not under
    `cost_usd` as a string like the other three steps — so reading the wrong key
    reports every grouping call as free. The budget governor is inert by decision,
    which makes this number the only spend signal the run has.

    RUN IN `topic` MODE (15.7-01), because the thing under test is that a PAID
    grouping call is metered, and D-W4-4a's primary path deliberately makes none.
    Pinned rather than rewritten: the accounting bug this guards against is still
    live on the `topic` path, and there is exactly one measuring run in which the two
    modes may be compared. The primary path's own "no call means no cost" claim is
    asserted in `test_question_grouping.py` against a client that cannot be called.
    """
    recorder = FeedRecorder()
    feed = make_feed(recorder)
    audited = working_fake(groups=[[1]])

    with grouping_mode(question_grouping._GROUPING_MODE_TOPIC):
        await stage_b(audited, stage_a(["Q1", "Q2"], ["Q1", "Q2", "Q1"]), feed=feed)
    await feed.flush()

    summary = recorder.calls[-1]["detail"]["summary"]
    assert any(GROUP_PROMPT_MARKER in p for p in audited.anthropic_prompts())
    assert audited.call_count > 0
    assert summary["actions"] == audited.call_count, (
        summary["actions"], audited.call_count
    )
    assert Decimal(summary["cost_usd"]) == (
        Decimal(audited.COST_USD) * audited.call_count
    ), summary["cost_usd"]


async def test_every_group_member_is_a_winner_or_a_discovered_question():
    """The partition is TOTAL, and the two brackets are the only two sources.

    Asserted as a PROPERTY rather than against an exact group count, because the
    number of groups is a function of the clamp and of how many client questions
    there are — pinning it here would pin a rule that lives elsewhere.
    """
    labels = ["Q1", "Q2", "Q3"]
    source = stage_a(labels, labels * 4, conflicts=[conflict("Q1")])

    result = await stage_b(working_fake(groups=[[1]]), source)

    winner_texts = sorted(w["text"] for w in result["winners"])
    mandate_members = sorted(
        m["text"]
        for g in result["groups"]
        for m in g["members"]
        if m.get("source") != "discovery"
    )
    assert mandate_members == winner_texts, "every winner is in exactly one group"
    discovered = {q["text"] for q in result["discovery"]}
    rider_texts = {
        m["text"]
        for g in result["groups"]
        for m in g["members"]
        if m.get("source") == "discovery"
    }
    assert rider_texts <= discovered
    assert set(result["client_questions"]) <= set(
        workshop_rank._covered_by_mandate_members(result["groups"])
    )
    assert result["counts"]["group_coverage_injected"] == 0, (
        "the guard finds nothing to repair when the partition is total"
    )


# ===========================================================================
# SECTION (phase 15.7, plan 08) — D-W4-6: GUARD 2 MARKS WHAT IT RESCUES.
#
# Both critique guards are COVERAGE FALLBACKS, NOT QUALITY PASSES. Guard 1
# already marked; Guard 2 — the one that rewrites EVERY candidate to KEEP when
# critique kills the whole population — did not. Without the mark, the one case
# where quality most needs to read as FAILED read as a PERFECT PASS.
#
# The exemption targets CRITERION 2 — QUALITY. Until 2026-07-31 three separate
# documents said criterion 1; that inverted the rule's own purpose, because
# criterion 1 is COVERAGE and excluding a resurrected candidate from coverage
# would break the exact guarantee resurrection exists to provide.
# ===========================================================================


def _verdict_for_every_indexed_line(prompt: str, verdict: str) -> str:
    """Answer every `INDEX | text` line the critique block rendered."""
    lines = []
    for physical in prompt.splitlines():
        stripped = physical.strip()
        head = stripped.split("|")[0].strip()
        if "|" in stripped and head.isdigit():
            lines.append(f"{head} | {verdict} | a clause")
    return "\n".join(lines)


def critique_responder(verdict: str):
    """A judge that gives every candidate the same critique verdict."""

    def _respond(prompt: str) -> str:
        if MATCH_MARKER in prompt:
            return flash_responder()(prompt)
        return _verdict_for_every_indexed_line(prompt, verdict)

    return _respond


#: Present in a TOURNAMENT prompt and in no other flash prompt this module makes.
MATCH_MARKER = " | A: "


def bare_candidates(total: int, *, parented: bool) -> list[dict[str, Any]]:
    """GUARD 2 IS ONLY REACHABLE WHEN NO CANDIDATE CARRIES A PARENT LABEL.

    Guard 1 runs first and rescues the lowest-index candidate of EVERY parent
    label, so a PARENTED population can never reach the empty-survivor state
    Guard 2 exists for. That is Guard 1 doing its job — but it also means a
    Guard 2 test built on parented candidates silently tests Guard 1 instead,
    which is why this helper takes the flag explicitly rather than defaulting.
    """
    out = []
    for i in range(total):
        entry: dict[str, Any] = {
            "index": i,
            "text": f"candidate {i:02d} about topic {i:02d}",
            "source": "model",
        }
        if parented:
            entry["parent"] = "Q0"
            entry["parents"] = ["Q0"]
        out.append(entry)
    return out


async def _critique(verdict: str, candidates: list[dict[str, Any]]):
    return await workshop_rank.critique_candidates(
        candidates=candidates,
        audited=JudgeAudited(critique_responder(verdict)),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
    )


async def test_guard_two_marks_every_candidate_it_rescues():
    """50. A critique that kills EVERYTHING yields survivors that ALL carry the mark."""
    survivors, reasons = await _critique("KILL", bare_candidates(6, parented=False))

    assert len(survivors) == 6, "Guard 2 did not fire"
    assert all(s["critique"] == "KEEP" for s in survivors)
    assert all(s.get("resurrected") is True for s in survivors), (
        "Guard 2 rescued without marking — the blanket rescue reads as a clean pass"
    )
    assert reasons


async def test_an_honest_survivor_is_never_marked():
    """51. The negative arm. A candidate that survived on merit carries no mark."""
    survivors, _ = await _critique("KEEP", bare_candidates(6, parented=True))

    assert survivors
    assert not any(s.get("resurrected") is True for s in survivors), survivors


async def _resurrected_through_the_pipeline():
    survivors, _ = await _critique("KILL", bare_candidates(6, parented=False))
    assert all(s.get("resurrected") is True for s in survivors)

    ranked, _ = await workshop_rank.run_tournament(
        candidates=survivors,
        audited=JudgeAudited(flash_responder()),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
    )
    assert all(w.get("resurrected") is True for w in ranked), "lost at run_tournament"

    evolved, _ = await workshop_rank.evolve_winners(
        winners=ranked,
        audited=JudgeAudited(flash_responder()),
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
    )
    assert all(w.get("resurrected") is True for w in evolved), "lost at evolve_winners"

    guarded, _notes, _injected = workshop_rank.enforce_scope_guard(
        winners=evolved, client_questions=["Q0"], all_ranked=ranked
    )
    assert [w for w in guarded if w.get("resurrected") is True], (
        "lost at enforce_scope_guard"
    )
    return guarded


async def test_the_resurrection_mark_survives_all_four_stages():
    """52. Asserted at EACH stage, not only at the end.

    A mark that is set and then dropped two stages later is WORSE than no mark,
    because a dropped mark reads as a clean pass — the precise failure this
    whole decision exists to prevent.
    """
    await _resurrected_through_the_pipeline()


async def test_the_exit_check_reads_a_blanket_rescue_as_a_quality_failure():
    """53. THE SEAM between this plan and 15.7-03, closed and asserted.

    `workshop_loop.exit_verdict` READS the flag and never infers it, so this is
    the only place the two halves meet. The second half of this test is the
    MUTANT COLUMN: strip the mark and the very same winner set reads as a
    perfect quality pass — the exact lie the mark exists to prevent.
    """
    guarded = await _resurrected_through_the_pipeline()

    verdict = workshop_loop.exit_verdict(
        winners=guarded, client_questions=["Q0"], round_no=1
    )
    assert verdict["resurrected_winners"] > 0, verdict
    assert verdict["quality_ok"] is False, verdict
    assert verdict["should_exit"] is False, verdict

    stripped = [{k: v for k, v in w.items() if k != "resurrected"} for w in guarded]
    lie = workshop_loop.exit_verdict(
        winners=stripped, client_questions=["Q0"], round_no=1
    )
    assert lie["quality_ok"] is True, (
        "removing the mark did not change the verdict, so this test proves nothing"
    )
