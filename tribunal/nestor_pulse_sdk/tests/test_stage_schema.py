"""The stage schema is COMPLETE: no key the pipeline reports is missing from it (WR-03).

WHY this file exists
--------------------
`set_stage(run_id, tenant_id, "gate", ...)` writes `run.current_stage = 'gate'`
(`pipeline.py:536-562`, added by Phase 15.1), but `ENGINE_STAGES["tribunal"]` never
declared a `gate` entry. `RunMetrics.stages` is built from `stages_for(run.engine)`
(`runs/api.py:846`), so the API shipped a nine-stage ordered schema that OMITTED the
stage the run was reporting it was in, and the UI rendered the bare key with no label.
`set_stage`'s own docstring (`stages.py`) already says `stage_key` must be "a key from
ENGINE_STAGES[engine], or 'done'" — the rule existed, nothing enforced it.

So this file does two things: it pins the `gate` declaration in its correct ORDER, and
it adds the generalised gate — a test that reads the pipeline's SOURCE and fails if any
`set_stage` key is undeclared. That makes this whole class of defect impossible to
reintroduce silently, instead of fixing one instance of it.

All tests are pure: no DB, no network, no LLM, no mocking library. The pipeline is read
as TEXT (path resolved through the package's `__file__`, never a repo-root relative
path, because the build context ships only the `tribunal/` subtree).

Cloud Build invocation:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-gates.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import re
from pathlib import Path

from nestor_pulse_sdk.runs.stages import ENGINE_STAGES, stages_for

#: The first quoted lowercase token after `set_stage(` is the stage key. `[^)]` keeps
#: the match inside one call; DOTALL so a call wrapped over several lines still matches.
_SET_STAGE_RE = re.compile(r'set_stage\([^)]*?"([a-z_]+)"', re.DOTALL)

#: Keys `set_stage` may write that are deliberately NOT ordered schema entries.
#:
#: 21-07 (OPERATOR RULING, 2026-08-10 — `option-read-path`): membership here now
#: exempts a key from ONE requirement, not two. It is still exempt from being a
#: declared CHECKLIST STEP, for the phantom-row reason recorded below. It is NOT
#: exempt from having a human LABEL — `test_the_non_schema_allowlist_cannot_grow_
#: into_a_raw_key_leak` iterates this very set and requires each member to resolve
#: through `_stage_event_label` to something other than itself.
#:
#: That is the hole this allowlist used to be. An allowlisted key skipped the
#: declaration check, nothing checked its label, and `_stage_event_label`'s
#: raw-key fallback then printed the bare key on the run page. Measured on
#: 2026-08-10: every completed run ended on a divider reading literally `done`.
#: Adding a key here without a label in `stages.NON_SCHEMA_STAGE_LABELS` now
#: turns the build red in the same edit.
_NON_SCHEMA_MARKERS = {
    # The terminal position, documented as implicit in stages.py: the UI infers it
    # from `current_stage == 'done'` rather than rendering it as a checklist row.
    # 21-07: labelled "Run complete" on the read path. It is written at the end of
    # EVERY run, so its raw key was never a latent defect — it shipped on all of them.
    "done",
    # An interactive PAUSE, not a pipeline stage (pipeline.py:1172): the run parks as
    # 'needs_report_spec' until the user supplies a report shape. Declaring it would
    # put a phantom row in the ordered checklist of every NON-interactive run, so it
    # stays out of the schema. PRE-EXISTING and outside plan 15.1-13's scope — listed
    # here explicitly so the exception is reviewable, not silently absorbed.
    # 21-07: that reasoning was REVIEWED and UPHELD by the operator rather than
    # reversed; it is labelled "Report shaping" on the read path instead. The
    # exception is now reviewable in BOTH dimensions — declaration and label.
    "report_spec",
}


def _keys(engine: str) -> list[str]:
    return [stage["key"] for stage in stages_for(engine)]


def _pipeline_source() -> str:
    """The tribunal pipeline module as text, resolved through the package."""
    from nestor_pulse_sdk.pipeline.tribunal import pipeline as pipeline_module

    return Path(pipeline_module.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 1. WR-03 — the gate stage is declared, and in the right place
# ---------------------------------------------------------------------------
def test_gate_stage_is_declared_between_distill_and_verify():
    """The gate stage is declared exactly once, labelled, and in its running order.

    WHY THE ADJACENCY MOVED (Phase 15.2 plan 03). This test originally pinned
    `gate == distill + 1`, because in 15.1 the gates ran immediately after claim
    distillation. 15.2's D9/D11 insert a CROSS-PROVIDER MERGE between the two: the
    per-provider claim sets (plus the D-14 fallback distillation's output) are merged
    before anything is gated. So the chain is now
    `distill → merge → gate → verify`.

    The WR-03 property this test exists to protect is UNCHANGED: every stage the
    pipeline reports is declared, in the order it runs. Only the recorded order is
    different, because the pipeline's order is different. The generalised guard in
    section 4 below is untouched.
    """
    keys = _keys("tribunal")

    assert keys.count("gate") == 1, "the gate stage must be declared exactly once"

    # ORDER is the point: the schema is what the UI renders as an ordered checklist.
    # Claim distillation → cross-provider merge → the gates → skeptic verification.
    assert (
        keys.index("distill") < keys.index("merge") < keys.index("gate") < keys.index("verify")
    ), f"the distill → merge → gate → verify chain is out of order: {keys}"
    assert keys.index("merge") == keys.index("distill") + 1
    assert keys.index("gate") == keys.index("merge") + 1
    assert keys.index("gate") == keys.index("verify") - 1

    label = next(s["label"] for s in stages_for("tribunal") if s["key"] == "gate")
    assert label == "Verification gates"

    # The adk schema is a different pipeline and must NOT have gained the entry.
    assert "gate" not in _keys("adk")


# ---------------------------------------------------------------------------
# 1b. WR-03 for the three stages Phase 15.2 adds
# ---------------------------------------------------------------------------
def test_15_2_stage_keys_are_declared_with_labels():
    """`workshop`, `own_research` and `merge` are declared BEFORE any plan writes them.

    WR-03 is a *declare-first* rule, not a clean-up-after rule: `RunMetrics.stages`
    is built from `stages_for(run.engine)` (`runs/api.py:846`), so a stage the
    pipeline reports but the schema omits ships as a bare key with no label and is
    missing from the ordered checklist entirely. Plans 15.2-10/11/12/13/15 write
    these three keys; this assertion is what makes their writes renderable.
    """
    keys = _keys("tribunal")
    labels = {s["key"]: s["label"] for s in stages_for("tribunal")}

    # The exact ordered schema the 15.2 engine reports against.
    assert keys == [
        "intake",
        "workshop",
        "research_division",
        "deep_research",
        "own_research",
        "distill",
        "merge",
        "gate",
        "verify",
        "adjudicate",
        "coverage",
        "conflict",
        "synthesize",
    ], f"the tribunal stage order changed: {keys}"

    assert labels["workshop"] == "Question workshop"
    assert labels["own_research"] == "Own research"
    assert labels["merge"] == "Cross-provider merge"

    # Placement, stated as the relationships that make each one meaningful:
    #   workshop's winning sub-questions feed research_division.divide() (D2-D7)
    assert keys.index("workshop") == keys.index("intake") + 1
    assert keys.index("workshop") == keys.index("research_division") - 1
    #   own_research is the FOURTH peer research stream, alongside the three
    #   third-party providers (D10) — not a step inside deep_research
    assert keys.index("own_research") == keys.index("deep_research") + 1

    # The adk schema is a different pipeline and must NOT have gained the entries.
    assert "workshop" not in _keys("adk")
    assert "own_research" not in _keys("adk")
    assert "merge" not in _keys("adk")


# ---------------------------------------------------------------------------
# 2. Schema shape
# ---------------------------------------------------------------------------
def test_every_stage_has_a_key_and_a_label():
    for engine, schema in ENGINE_STAGES.items():
        keys = []
        for stage in schema:
            assert isinstance(stage, dict), f"{engine}: every stage entry is a dict"
            assert stage.get("key"), f"{engine}: a stage entry has no key"
            assert stage.get("label"), f"{engine}: stage {stage.get('key')!r} has no label"
            keys.append(stage["key"])
        assert len(keys) == len(set(keys)), f"{engine}: duplicate stage keys {keys}"


# ---------------------------------------------------------------------------
# 3. The sdk arm reuses the tribunal schema (same list object)
# ---------------------------------------------------------------------------
def test_sdk_alias_shares_the_tribunal_schema():
    assert stages_for("sdk") == stages_for("tribunal")
    assert "gate" in _keys("sdk"), "the alias must inherit the new entry automatically"


# ---------------------------------------------------------------------------
# 4. THE GENERALISED GATE — no undeclared stage key can ship again
# ---------------------------------------------------------------------------
def test_every_set_stage_key_in_the_pipeline_is_declared():
    """Read the pipeline source and require every stage key it writes to be declared.

    This is the assertion whose absence let WR-03 ship: the `gate` writes and the
    schema were edited in different files by different plans, and nothing compared
    them. Comparing them here means the next stage added to the pipeline fails the
    build until `runs/stages.py` learns about it.
    """
    found = set(_SET_STAGE_RE.findall(_pipeline_source()))

    # Vacuity guard: an empty or near-empty match set means the regex stopped
    # matching (a refactor of the call style), and MUST fail rather than pass.
    assert len(found) >= 8, (
        f"only {len(found)} stage key(s) extracted from pipeline.py ({sorted(found)}) — "
        "the extraction broke; this test would otherwise pass vacuously"
    )

    declared = set(_keys("tribunal"))
    for key in sorted(found):
        assert key in declared or key in _NON_SCHEMA_MARKERS, (
            f"pipeline.py writes run.current_stage = {key!r} but ENGINE_STAGES['tribunal'] "
            f"does not declare it — add {{'key': {key!r}, 'label': ...}} to "
            f"nestor_pulse_sdk/runs/stages.py (this is exactly the WR-03 defect: the API "
            f"would ship a schema omitting the stage the run reports being in)"
        )

    # Positive control: the keys this test is really about are in the extracted set,
    # so the loop above is proving coverage rather than iterating over nothing.
    assert {"gate", "verify", "synthesize"} <= found


# ---------------------------------------------------------------------------
# 4b. THE STRENGTHENED GATE (21-07) — no stage key can reach the OPERATOR raw
# ---------------------------------------------------------------------------
# DECLARATION and LABEL RESOLUTION are two different properties, and section 4
# only checks the first. `_NON_SCHEMA_MARKERS` exempts a key from declaration,
# nothing checked that it had a label, and `_stage_event_label`'s raw-key
# fallback turned that gap into a snake_case string on the run page. Section 4
# was right and it was not enough.
# ---------------------------------------------------------------------------
def _stage_event_label(key: str) -> str:
    """The pipeline's own read-path resolver, imported the same lazy way the
    source reader above imports the module (the build context ships only
    `tribunal/`, and this file must not pay a module-level pipeline import)."""
    from nestor_pulse_sdk.pipeline.tribunal.pipeline import (
        _stage_event_label as resolver,
    )

    return resolver(key)


def _every_key_that_can_reach_the_divider() -> set[str]:
    """The UNION of every source that can put a key on the divider.

    WHY A UNION AND NOT THE SOURCE SCAN ALONE. Section 4 extracts `set_stage`
    keys from `pipeline.py`, which is the right reach for *its* question but not
    for this one: `workshop` is written by `StageFeed` (`runs/stage_feed.py`),
    NOT by a `set_stage` call in `pipeline.py`, and `pipeline.py:1752-1763`
    records that as deliberate (D-F, 15.2-24). A scan of one file therefore
    cannot see it — the same blind spot that let `gate` and `report_spec`
    through. Taking the union with the declared schema and the marker allowlist
    closes it: a key is covered if ANY source knows about it.
    """
    return (
        set(_SET_STAGE_RE.findall(_pipeline_source()))
        | set(_keys("tribunal"))
        | set(_NON_SCHEMA_MARKERS)
    )


def test_every_pipeline_stage_key_resolves_to_a_human_label():
    """No key any source knows about may render as itself on the operator's screen.

    WHAT BREAKS IF THIS FIRES: the run page's phase divider shows a raw
    snake_case identifier where a human label belongs — `RunFeed.tsx` renders
    `event.text` verbatim and looks up no stage vocabulary of its own. That is
    the WR-03 defect class in its display form, and it is SC6 of Phase 21.

    THIS IS NOT REDUNDANT WITH SECTION 4. That test asks "is the key DECLARED";
    this one asks "does the key RESOLVE TO A LABEL". `_NON_SCHEMA_MARKERS`
    exempts a key from the first while saying nothing about the second, so
    before 21-07 an allowlisted key sailed through section 4 and still printed
    raw. Measured 2026-08-10: every completed run ended on a divider whose text
    was literally `done`.
    """
    extracted = set(_SET_STAGE_RE.findall(_pipeline_source()))

    # Vacuity guard, same reasoning as section 4: if the extraction breaks, this
    # must FAIL rather than iterate over an empty set and report success.
    assert len(extracted) >= 8, (
        f"only {len(extracted)} stage key(s) extracted from pipeline.py "
        f"({sorted(extracted)}) — the extraction broke; this test would "
        "otherwise pass vacuously"
    )

    covered = _every_key_that_can_reach_the_divider()
    raw = sorted(key for key in covered if _stage_event_label(key) == key)
    assert not raw, (
        f"these stage keys resolve to THEMSELVES, so the run page's phase "
        f"divider renders the raw snake_case key to the operator: {raw}. Give "
        f"each one a label — an ordered checklist step goes in "
        f"ENGINE_STAGES['tribunal'], a written-but-not-a-step marker goes in "
        f"stages.NON_SCHEMA_STAGE_LABELS. This is the WR-03 defect class: the "
        f"UI shows a bare key with no label."
    )

    # Positive controls: the two keys this test is really about are in the set
    # under assertion, so the loop above proves coverage rather than iterating
    # over nothing. `report_spec` is the allowlisted key the plan was written
    # around; `done` is the one that actually shipped on every run.
    assert "report_spec" in covered
    assert "done" in covered
    # And `workshop` is the StageFeed-written key the union exists to reach.
    assert "workshop" in covered


def test_the_non_schema_allowlist_cannot_grow_into_a_raw_key_leak():
    """Every exemption from declaration must still carry a label.

    This is what makes ADDING to `_NON_SCHEMA_MARKERS` safe. A future engineer
    exempting a new key from the ordered schema is forced to give it a label in
    the SAME edit, so the allowlist can never again become the route by which a
    raw key reaches a reader.

    The set is ITERATED, not copied: a hardcoded duplicate of its contents would
    go stale the moment somebody appended to it, which is precisely the failure
    mode this test exists to prevent.
    """
    assert _NON_SCHEMA_MARKERS, (
        "the marker allowlist is empty — this test would pass vacuously"
    )

    for key in sorted(_NON_SCHEMA_MARKERS):
        label = _stage_event_label(key)
        assert label != key, (
            f"{key!r} is exempt from being declared in ENGINE_STAGES, which is "
            f"deliberate — but it is still WRITTEN to run.current_stage and the "
            f"divider renders whatever the resolver returns, so it also needs a "
            f"label. Add {key!r} to stages.NON_SCHEMA_STAGE_LABELS."
        )
        assert label.strip(), f"{key!r} resolved to blank — worse than a raw key"


def test_the_raw_key_fallback_still_exists_for_an_unknown_key():
    """NEGATIVE CONTROL: prove the two tests above assert something breakable.

    If `_stage_event_label` returned a label for everything — say by title-casing
    its input — both tests above would pass by construction and prove nothing.
    They are only meaningful because a key neither source knows still comes back
    AS ITSELF.

    The fallback is also deliberately correct behaviour, not a leftover: a
    rolling deploy means a newer engine build can write a key this process has
    never heard of, and a bare key beats a blank divider. `_stage_event_label`'s
    docstring says so; this pins it.
    """
    invented = "a_stage_from_a_newer_build"
    assert invented not in _keys("tribunal")
    assert invented not in _NON_SCHEMA_MARKERS

    assert _stage_event_label(invented) == invented, (
        "the raw-key fallback is gone — an unknown key must still render "
        "something, and the two label tests above become vacuous without it"
    )


# ---------------------------------------------------------------------------
# 5. Documented fallback for an unknown engine
# ---------------------------------------------------------------------------
def test_unknown_engine_returns_empty_list():
    assert stages_for("nope") == []
    assert stages_for("") == []
