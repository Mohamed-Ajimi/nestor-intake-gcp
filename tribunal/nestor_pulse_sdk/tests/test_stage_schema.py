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
_NON_SCHEMA_MARKERS = {
    # The terminal position, documented as implicit in stages.py: the UI infers it
    # from `current_stage == 'done'` rather than rendering it as a checklist row.
    "done",
    # An interactive PAUSE, not a pipeline stage (pipeline.py:1172): the run parks as
    # 'needs_report_spec' until the user supplies a report shape. Declaring it would
    # put a phantom row in the ordered checklist of every NON-interactive run, so it
    # stays out of the schema. PRE-EXISTING and outside plan 15.1-13's scope — listed
    # here explicitly so the exception is reviewable, not silently absorbed.
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
    keys = _keys("tribunal")

    assert keys.count("gate") == 1, "the gate stage must be declared exactly once"

    # ORDER is the point: the schema is what the UI renders as an ordered checklist,
    # and the gates run after claim distillation and before skeptic verification.
    assert keys.index("gate") == keys.index("distill") + 1
    assert keys.index("gate") == keys.index("verify") - 1

    label = next(s["label"] for s in stages_for("tribunal") if s["key"] == "gate")
    assert label == "Verification gates"

    # The adk schema is a different pipeline and must NOT have gained the entry.
    assert "gate" not in _keys("adk")


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
# 5. Documented fallback for an unknown engine
# ---------------------------------------------------------------------------
def test_unknown_engine_returns_empty_list():
    assert stages_for("nope") == []
    assert stages_for("") == []
