"""D7 language tagging — SEARCH languages widen, the OUTPUT language does not.

WHAT THIS FILE COVERS (plan 15.2-11, D2 step 6 / D7):
  * `LANGS:` parsing out of the evolve step's fenced lines;
  * the 2-letter ISO 639-1 filter, the order-stable de-duplication and the cap;
  * the never-empty guarantee, through the run language's own code and then
    through `_DEFAULT_LANGS`;
  * that `parent` and `rank` are stamped in Python and a model-supplied
    `PARENT:` segment or out-of-range index cannot re-parent or invent a winner;
  * the fenced parser's missing-sentinel and dangling-sentinel tolerances;
  * the F8 `pause_turn` continuation on the evolve call;
  * and the thing that must NOT change: the report's OUTPUT language stays one
    language per run, from `mission_brief["language"]`, and this module neither
    reads nor rewrites it.

THIS FILE MAKES ZERO LLM CALLS, OPENS NO DATABASE, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. Every provider call is served by plan 15.2-10's
`workshop_fakes.ScriptedWorkshopAudited` (and, where the flash judge is needed
too, by the shared subclass in `test_workshop_tournament.py`). No test here
carries `@pytest.mark.live`, nothing can flake on the network, and nothing spends.

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import pathlib
import uuid
from typing import Any, Optional

from nestor_pulse_sdk.pipeline.tribunal import workshop_rank
from nestor_pulse_sdk.tests.test_workshop_tournament import (
    JudgeAudited,
    flash_responder,
)
from nestor_pulse_sdk.tests.workshop_fakes import (
    FakeTextResponse,
    ScriptedWorkshopAudited,
)

RUN_ID = uuid.uuid4()
TENANT_ID = uuid.uuid4()

#: The module under test, resolved from THIS file's location — never a repo
#: root, because Cloud Build ships only `tribunal/` (Pitfall 8).
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
    parent: str = "Q1",
    *,
    text: Optional[str] = None,
    flaw: str = "",
    rank: Optional[int] = None,
) -> dict[str, Any]:
    """One tournament winner, in `run_tournament`'s real output shape."""
    return {
        "index": index,
        "text": text if text is not None
        else f"tournament winner number {index} about the Benelux fuel-card market",
        "parent": parent,
        "parents": [parent],
        "source": "model",
        "rank": rank if rank is not None else index + 1,
        "wins": 0,
        "elo": 1200.0,
        "byes": 0,
        "critique": "KEEP",
        "flaw": flaw,
    }


def fenced(*lines: str) -> str:
    return "\n".join(
        [workshop_rank._WINNERS_START, *lines, workshop_rank._WINNERS_END]
    )


def replying(text: str) -> ScriptedWorkshopAudited:
    return ScriptedWorkshopAudited(anthropic_script=[FakeTextResponse(text)])


async def evolve(
    audited: Any, winners: list[dict[str, Any]], **kwargs: Any
) -> tuple[list[dict[str, Any]], list[str]]:
    return await workshop_rank.evolve_winners(
        winners=winners,
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        **kwargs,
    )


def stage_a(labels: list[str], candidate_parents: list[str]) -> dict[str, Any]:
    """A minimal `run_workshop_stage_a` return value in its documented shape."""
    return {
        "questions": [
            {"label": label, "text": f"client question {label} as the client wrote it",
             "source": "caller"}
            for label in labels
        ],
        "orientation": [],
        "brief_conflicts": [],
        "candidates": [
            {
                "index": i,
                "text": f"candidate {i:02d} — a sharp sub-question deepening {parent}",
                "parent": parent,
                "parents": [parent],
                "source": "model",
                "cluster_key": f"__singleton__:{i}",
                "merged_from": [],
            }
            for i, parent in enumerate(candidate_parents)
        ],
        "degradation_reasons": [],
        "stage_a_fallback": False,
        "counts": {},
    }


# ===========================================================================
# SECTION 1 — parsing and filtering
# ===========================================================================


async def test_langs_parsed_from_the_evolve_lines():
    """1. The happy path: sharpened text plus its ISO 639-1 codes."""
    audited = replying(
        fenced("0 | a sharpened question about German tolling fees | LANGS: de,en")
    )

    winners, reasons = await evolve(audited, [win(0)])

    assert winners[0]["langs"] == ["de", "en"]
    assert winners[0]["text"] == "a sharpened question about German tolling fees"
    assert reasons == []


async def test_langs_are_filtered_capped_and_deduped(monkeypatch):
    """2. Lower-cased, 2-letter only, order-stable, capped at _LANGS_MAX."""
    monkeypatch.setattr(workshop_rank, "_LANGS_MAX", 3)
    audited = replying(
        fenced(
            "0 | a sharpened question about cross-border excise "
            "| LANGS: DE, en, xx1, !!, de, fr, es, it"
        )
    )

    winners, _ = await evolve(audited, [win(0)])

    assert winners[0]["langs"] == ["de", "en", "fr"]


async def test_langs_never_empty_falls_back_to_the_run_language_code():
    """3. No LANGS segment: the run language supplies the tag, name or code."""
    line = "0 | a sharpened question about Dutch excise duty in 2026"

    by_name, _ = await evolve(replying(fenced(line)), [win(0)], run_language="Nederlands")
    assert by_name[0]["langs"] == ["nl"]

    by_code, _ = await evolve(replying(fenced(line)), [win(0)], run_language="nl")
    assert by_code[0]["langs"] == ["nl"]


async def test_langs_falls_back_to_the_default_when_the_run_language_is_unknown():
    """4. An unmapped run language still leaves every winner tagged."""
    audited = replying(fenced("0 | a sharpened question about tolling in transit"))

    winners, _ = await evolve(audited, [win(0)], run_language="Klingon")

    assert winners[0]["langs"] == workshop_rank._filter_lang_codes(
        workshop_rank._DEFAULT_LANGS
    )
    assert winners[0]["langs"] == ["en"]
    assert all(w["langs"] for w in winners)


async def test_every_winner_has_at_least_one_lang_under_every_failure_mode(monkeypatch):
    """5. Garbage, a raising call, the off-switch, and a scope-guard injection."""
    # a) the model returns something unparseable.
    garbage, _ = await evolve(
        replying("total nonsense, no fence, no rows"), [win(0), win(1)]
    )
    assert all(w["langs"] for w in garbage)

    # b) the call raises.
    boom = ScriptedWorkshopAudited(raise_on_call=RuntimeError("the provider refused"))
    failed, reasons = await evolve(boom, [win(0), win(1)], run_language="Nederlands")
    assert all(w["langs"] == ["nl"] for w in failed)
    assert any("failed outright" in r for r in reasons), reasons

    # c) the evolve step is switched off.
    monkeypatch.setattr(workshop_rank, "_EVOLVE_ENABLED", False)
    silent = ScriptedWorkshopAudited()
    off, _ = await evolve(silent, [win(0)], run_language="Nederlands")
    assert len(silent.anthropic_calls) == 0
    assert off[0]["langs"] == ["nl"]
    monkeypatch.setattr(workshop_rank, "_EVOLVE_ENABLED", True)

    # d) the scope guard injected a verbatim client question.
    audited = JudgeAudited(
        flash_responder(),
        anthropic_script=[
            FakeTextResponse(
                fenced(
                    "0 | a sharpened question about pricing across the Benelux "
                    "| LANGS: nl",
                    "1 | a sharpened question about tolling across the Benelux "
                    "| LANGS: nl",
                )
            )
        ],
    )
    result = await workshop_rank.run_workshop_stage_b(
        stage_a=stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2"]),
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        run_language="Nederlands",
    )
    injected = [w for w in result["winners"] if w.get("scope_injected")]
    assert injected, result["winners"]
    assert all(w["langs"] for w in result["winners"])
    assert injected[0]["langs"] == ["nl"]


async def test_model_supplied_parent_and_index_cannot_re_parent_a_winner():
    """6. Attribution is stamped by the pipeline, exactly as `provider` is."""
    audited = replying(
        fenced(
            "0 | a sharpened question about tolling fees "
            "| PARENT: A DIFFERENT QUESTION | LANGS: de",
            "99 | a question addressed to an index that does not exist | LANGS: fr",
        )
    )

    winners, _ = await evolve(audited, [win(0, "Q1", rank=1)])

    assert len(winners) == 1, "an out-of-range index must not create a winner"
    assert winners[0]["parent"] == "Q1"
    assert winners[0]["parents"] == ["Q1"]
    assert winners[0]["rank"] == 1
    assert winners[0]["langs"] == ["de"]
    assert winners[0]["text"] == "a sharpened question about tolling fees"


async def test_evolve_line_parser_tolerates_a_missing_or_dangling_fence():
    """7. The two tolerances inherited from `intake.py`'s fenced parser."""
    bare, _ = await evolve(
        replying("0 | a sharpened question about tolling fees | LANGS: de"), [win(0)]
    )
    assert bare[0]["text"] == "a sharpened question about tolling fees"
    assert bare[0]["langs"] == ["de"]

    dangling_text = (
        f"{workshop_rank._WINNERS_START}\n"
        "0 | another sharpened question about excise | LANGS: fr"
    )
    dangling, _ = await evolve(replying(dangling_text), [win(0)])
    assert dangling[0]["text"] == "another sharpened question about excise"
    assert dangling[0]["langs"] == ["fr"]


async def test_unusable_line_keeps_the_tournament_text():
    """8. Too short, or simply absent — the winner keeps what it had."""
    winners = [win(0), win(1)]
    audited = replying(fenced("0 | short"))

    evolved, reasons = await evolve(audited, winners)

    assert evolved[0]["text"] == winners[0]["text"]
    assert evolved[1]["text"] == winners[1]["text"]
    assert any("2 of 2" in r for r in reasons), reasons
    assert all(w["langs"] for w in evolved)


async def test_evolve_prompt_carries_the_run_language_and_the_injection_rule():
    """9. The run language, the ISO rule, the ignore line, and truncation."""
    long_text = "A" * 240 + "ZQZ"
    audited = replying(fenced("0 | a sharpened question about tolling fees | LANGS: de"))

    await evolve(
        audited, [win(0, text=long_text)], run_language="Nederlands"
    )

    prompt = audited.anthropic_calls[0]["prompt_text"]
    assert "Nederlands" in prompt
    assert "ISO 639-1" in prompt
    assert workshop_rank._IGNORE_INSTRUCTIONS in prompt
    assert "A" * 240 in prompt
    assert "ZQZ" not in prompt, "the 241st character reached the model"
    assert "\n0 | " in prompt, "winners are addressed by INDEX"


async def test_evolve_pause_turn_continues_the_call():
    """10. F8: a paused turn is continued, not thrown away."""
    audited = ScriptedWorkshopAudited(
        anthropic_script=[
            FakeTextResponse("still working on it", stop_reason="pause_turn"),
            FakeTextResponse(
                fenced("0 | a sharpened question about tolling fees | LANGS: de")
            ),
        ]
    )

    winners, reasons = await evolve(audited, [win(0)])

    assert len(audited.anthropic_calls) == 2, "the paused turn must be continued"
    assert winners[0]["text"] == "a sharpened question about tolling fees"
    assert winners[0]["langs"] == ["de"]
    assert reasons == []


async def test_output_language_rule_is_untouched():
    """11. D7 widens the SEARCH surface only.

    DEVIATION NOTE (recorded in the SUMMARY): the plan asks for a grep proving
    `workshop_rank.py` "contains no reference to `_language_directive`,
    `deep_research_prompt` rewriting, or `mission_brief["language"]`
    assignment". Two of those literals legitimately appear here —
    `deep_research_prompt` is a parameter this module ECHOES, and both symbols
    are NAMED in a docstring precisely to tell a reader where the output-language
    rule lives. So the assertions below pin the thing that actually matters: the
    module never CALLS the directive, never imports the synthesis package and
    never assigns a language field — and, behaviourally, echoes the run language
    and the deep-research prompt unchanged.
    """
    assert "_language_directive(" not in _RANK_SRC
    assert "steps._language_directive" not in _RANK_SRC
    assert "nestor_pulse_sdk.pipeline.synthesis" not in _RANK_SRC
    assert 'mission_brief["language"] =' not in _RANK_SRC

    audited = JudgeAudited(
        flash_responder(),
        anthropic_script=[
            FakeTextResponse(
                fenced(
                    "0 | a sharpened question about pricing | LANGS: de,en",
                    "1 | a sharpened question about tolling | LANGS: de,en",
                )
            )
        ],
    )
    result = await workshop_rank.run_workshop_stage_b(
        stage_a=stage_a(["Q1", "Q2"], ["Q1", "Q2"]),
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        run_language="Nederlands",
        deep_research_prompt="the whole brief, unchanged",
    )

    assert result["language"] == "Nederlands"
    assert result["deep_research_prompt"] == "the whole brief, unchanged"
    # The SEARCH languages are wider than the run language — that is the point.
    assert any("de" in w["langs"] for w in result["winners"])


async def test_langs_reach_the_winner_records_15_2_13_reads():
    """12. The shape plan 15.2-13's hand-written display-name allowlist filters."""
    audited = JudgeAudited(
        flash_responder(),
        anthropic_script=[
            FakeTextResponse(
                fenced(
                    "0 | a sharpened question about pricing | LANGS: de,en",
                    "1 | a sharpened question about tolling | LANGS: fr",
                    "2 | a sharpened question about excise | LANGS: nl,en",
                )
            )
        ],
    )

    result = await workshop_rank.run_workshop_stage_b(
        stage_a=stage_a(["Q1", "Q2", "Q3"], ["Q1", "Q2", "Q3"]),
        audited=audited,
        run_id=RUN_ID,
        tenant_id=TENANT_ID,
        run_language="Nederlands",
    )

    for winner in result["winners"]:
        assert isinstance(winner["langs"], list)
        assert winner["langs"], "D7: every winner carries at least one tag"
        assert len(winner["langs"]) <= workshop_rank._LANGS_MAX
        for code in winner["langs"]:
            assert isinstance(code, str)
            assert len(code) == 2 and code.islower()
