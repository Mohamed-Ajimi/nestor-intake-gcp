"""The run-event EMIT SITES (plan 15.3-03) — the feed's spine, proved where it
is produced rather than where it is stored.

WHAT THIS FILE IS FOR
---------------------
Plan 15.3-01 shipped the emitter and proved it in isolation: `emit` never raises,
`emit_safe` runs `build()` inside its own try, meta keys are whitelisted, text is
scrubbed before it is clamped. None of that says anything about whether the
PIPELINE calls it, calls it once per boundary rather than once per write, or
passes it a label instead of a raw key. This file is about the call sites.

Three behaviours are load-bearing enough to name up front:

  1. THE DIVIDER CARRIES THE HUMAN LABEL. `ENGINE_STAGES["tribunal"]` has had a
     label for all fourteen stages since Phase 15 and no surface has ever shown
     one — `ResearchRunProgress` renders `Current phase: deep_research`. The
     assertions below check for `Deep research` AND check that `deep_research` is
     not what was emitted, because an assertion that only looked for the label
     would pass on a feed that emitted both.

  2. ONE DISPATCH HEADER PER BATCH. The header is what the indented agent
     children hang under. One per angle would emit twenty-four headers with one
     child each, which is not the design with a bug in it — it is a different
     design.

  3. A FAILED ANGLE SAYS WHY. The word "failed" on its own is the exact defect
     phase 15.3 exists to remove.

TESTS (h) AND (i) PROVE DIFFERENT THINGS AND BOTH ARE REQUIRED
--------------------------------------------------------------
(h) installs a recorder that RAISES on every call and shows that neither the
stage shim nor `run_angles` notices. That proves CALLING the emitter is safe.

(i) proves BUILDING what is passed to it is safe, and a raising recorder can
NEVER prove that: by the time any recorder runs, the arguments have already been
constructed successfully. So (i) drives the REAL `run_events` module — no
monkeypatched `emit`, no monkeypatched `emit_safe` — and hands the paid dispatch
loop a provider result with no `facts` key, then a `facts` of `None`. Its shim
half corrupts the timing value the summary line derives `worked` from.

Both halves of (i) carry a NEGATIVE CONTROL: they first assert that the
construction genuinely raises when performed outside the emitter, so a green run
cannot mean "the input was harmless after all".

(j) IS WHY (i) NOW ASSERTS SOMETHING STRONGER — 15.4-05
--------------------------------------------------------
The two degraded shapes (i) drives used to be SWALLOWED: the `agent_done` line
read `result["facts"]` as a subscript, `emit_safe` caught the `KeyError` exactly
as D-06 designs it to, and THE ROW VANISHED. About twenty rows were lost that way
on run 7dcf51d5 (D-V01-7), leaving the feed showing angles that started and never
ended. `emit_safe` was never the defect and is not modified by 15.4-05; the build
lambdas were the intolerant part, and they are what changed.

So (i) no longer asserts "a `KeyError` reached the emitter's log". It asserts the
line SURVIVES, with a count rendered as honestly unknown rather than as `0` — a
feed row must never assert a number the run did not establish (T-15.3-23). Its
negative control now shows what the OLD subscript form would have done.

(j) then drives both degraded shapes and asserts THE COUNT OF RECORDED EVENTS,
which is the load-bearing part: before the fix these record ZERO events, so a
test that only checked "nothing raised" would have passed against the bug. And
because a tolerant helper is a weaker guarantee than a structural one, (j) keeps
a D-06 proof AT THIS SITE by forcing the label helper itself to raise — if
anyone ever hoists `build()` above `emit_safe`'s try, that test fails loudly.

NO LLM CALL, NO DATABASE, NO NETWORK, NO KEY, NO MOCKING LIBRARY. The two
operations in `runs/run_events.py` that touch Postgres are module-level test
seams; the end-to-end behaviours drive the SAME stubbed harness
`test_engine_e2e_stubbed.py` installs, imported rather than rebuilt, because a
second harness is a second thing to drift.

NO PYTEST MARKER, deliberately: the engine gate runs `-m "not live"` and this
file must be SELECTED by it. `asyncio_mode = "auto"` is set in
`tribunal/pyproject.toml`, so the async tests below are plain `async def`.

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.pipeline.tribunal import own_researcher as own
from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod
from nestor_pulse_sdk.pipeline.tribunal import research_division as rd
from nestor_pulse_sdk.pipeline.tribunal import serpapi as _serpapi
from nestor_pulse_sdk.pipeline.tribunal import stage_events
from nestor_pulse_sdk.runs import run_events
from nestor_pulse_sdk.runs.stages import ENGINE_STAGES

# The stubbed end-to-end harness, IMPORTED rather than rebuilt (same reason
# `test_stage_logging.py` states for its own use of it).
from nestor_pulse_sdk.tests.test_engine_e2e_stubbed import (
    _ScriptedProvidersAudited,
    _engine_run,
    _no_db_sessionmaker,
    # 21-03: the `set_stage` detail reader, so the closing feed row can be
    # compared against the sentence the OTHER surface was handed.
    _stage_detail_entries,
    _stage_sequence,
)


# ===========================================================================
# harness
# ===========================================================================


class _Recorder:
    """A stand-in for `run_events.emit` that records every queued row.

    Installed over `emit`, NOT over `emit_safe`: that keeps the real `emit_safe`
    — and therefore the real `build()` call and the real try/except — in the path
    under test. Patching `emit_safe` instead would make every assertion below an
    assertion about the test double.
    """

    def __init__(self, raises: bool = False) -> None:
        self.rows: list[dict[str, Any]] = []
        self._raises = raises

    def __call__(
        self,
        run_id: Any,
        *,
        stage: str,
        kind: str,
        text: str,
        meta: Optional[dict] = None,
    ) -> None:
        self.rows.append(
            {"run_id": run_id, "stage": stage, "kind": kind, "text": text, "meta": meta}
        )
        if self._raises:
            raise RuntimeError("this event recorder is deliberately broken")

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["kind"] == kind]

    def kinds(self) -> list[str]:
        return [row["kind"] for row in self.rows]

    def texts(self, kind: str) -> list[str]:
        return [row["text"] for row in self.of(kind)]


def _install(monkeypatch, *, raises: bool = False) -> _Recorder:
    recorder = _Recorder(raises=raises)
    monkeypatch.setattr(run_events, "emit", recorder)
    return recorder


@pytest.fixture(autouse=True)
def _clean_registries():
    """No run buffer and no stage-log entry survives into the next test.

    Both registries are module-level and bounded, so a leak would not fail
    anything loudly — it would make one test's events show up in another's
    assertions, which is worse.
    """
    run_events._RUNS.clear()
    run_events._UNOPENED_LOGGED.clear()
    _pipeline_mod._STAGE_LOGS.clear()
    yield
    run_events._RUNS.clear()
    run_events._UNOPENED_LOGGED.clear()
    _pipeline_mod._STAGE_LOGS.clear()


def _label_of(key: str) -> str:
    for entry in ENGINE_STAGES["tribunal"]:
        if entry["key"] == key:
            return entry["label"]
    return key


def _runner_ok(calls: dict, name: str, result: Optional[dict] = None):
    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        return dict(
            result
            if result is not None
            else {"status": "success", "report": f"{name} report", "facts": [1, 2]}
        )

    return _run


def _runner_envelope_error(calls: dict, name: str, message: str):
    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        return {"status": "error", "error_message": message}

    return _run


def _runner_raising(calls: dict, name: str, message: str):
    async def _run(*, query, audited, run_id, tenant_id):
        calls.setdefault(name, []).append(query)
        raise RuntimeError(message)

    return _run


def _single_stream(monkeypatch, runners: dict) -> None:
    """Exactly the streams named, so no coverage retry can fire unasked."""
    monkeypatch.setattr(rd, "_PROVIDER_RUNNERS", runners)
    monkeypatch.setattr(
        rd, "_enabled_providers", lambda: [(name, None) for name in runners]
    )


# ===========================================================================
# (a) a transition emits ONE divider, and it carries the LABEL
# ===========================================================================
def test_a_transition_emits_one_divider_carrying_the_human_label(monkeypatch):
    """WHAT BREAKS IF THIS FIRES: the new page renders `deep_research` at its
    operator, which is the string `ResearchRunProgress` has been showing since
    Phase 15 and the reason this phase touches the engine at all.
    """
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(run_id, "intake")
    _pipeline_mod._stage_log_transition(run_id, "deep_research")

    dividers = recorder.texts("divider")
    assert dividers == ["Adaptive intake", "Deep research"], (
        f"the dividers must carry the ENGINE_STAGES labels, in order: {dividers}"
    )
    # THE COUNTERFACTUAL. Asserting only that the label is present would pass on
    # an implementation that emitted the key as well.
    assert "deep_research" not in dividers, (
        "the raw stage key reached the feed — the label lookup is not being used"
    )
    assert "intake" not in dividers
    # And the labels are read from the schema rather than typed here twice.
    assert dividers == [_label_of("intake"), _label_of("deep_research")]


def test_a_stage_with_no_schema_entry_falls_back_to_its_key(monkeypatch):
    """`done` is a real terminal key with no ENGINE_STAGES row. A blank divider
    would be worse than a bare key, so the fallback is asserted rather than
    assumed."""
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(run_id, "synthesize")
    _pipeline_mod._stage_log_transition(run_id, "done")

    assert recorder.texts("divider") == ["Final synthesis", "done"]


# ===========================================================================
# (b) re-reporting the SAME stage key emits NO second divider
# ===========================================================================
def test_re_reporting_the_same_stage_emits_no_second_divider(monkeypatch):
    """`deep_research` is re-written on EVERY angle callback. A divider per write
    would emit dozens per run and destroy the grouping the design exists to
    show — the same rule `_stage_log_transition` already applies to its INFO
    lines."""
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(run_id, "deep_research")
    for _ in range(12):
        _pipeline_mod._stage_log_transition(
            run_id, "deep_research", {"items": [{"name": "angle", "status": "running"}]}
        )

    assert recorder.texts("divider") == ["Deep research"], (
        f"a re-report produced extra dividers: {recorder.texts('divider')}"
    )
    assert recorder.of("summary") == [], (
        "a re-report closed a stage that was never left"
    )


# ===========================================================================
# (c) leaving a stage emits ONE summary, and it comes BEFORE the next divider
# ===========================================================================
def test_leaving_a_stage_emits_one_summary_before_the_next_divider(monkeypatch):
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(
        run_id, "intake", {"items": [{"name": "a"}, {"name": "b"}, {"name": "c"}]}
    )
    _pipeline_mod._stage_log_transition(run_id, "deep_research")

    # divider(intake), summary(intake), divider(deep_research) — in that order.
    assert recorder.kinds() == ["divider", "summary", "divider"], (
        f"the boundary did not read summary-then-divider: {recorder.kinds()}"
    )
    summary = recorder.of("summary")[0]
    assert summary["stage"] == "intake", (
        "the summary must be attributed to the stage being LEFT, not the one "
        f"being entered: {summary}"
    )
    assert summary["meta"]["actions"] == 3, (
        f"the summary must carry the row count the stage reported: {summary}"
    )
    assert isinstance(summary["meta"]["worked"], str) and summary["meta"]["worked"]


def test_a_stage_summary_carries_items_and_cost_when_the_stage_reported_them(
    monkeypatch,
):
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(
        run_id,
        "deep_research",
        {
            "items": [{"name": "angle 1"}],
            "summary": {"duration_s": 12, "actions": 87, "items_read": 95, "cost_usd": 9.08},
        },
    )
    _pipeline_mod._stage_log_transition(run_id, "distill")

    meta = recorder.of("summary")[0]["meta"]
    assert meta["items"] == 95
    assert meta["cost"] == pytest.approx(9.08)


def test_the_last_stage_of_a_run_still_gets_its_summary(monkeypatch):
    """There is no next transition to close the final stage, so `_stage_log_close`
    is the only place its summary can come from. Without this the feed simply
    stops one stage short of the end of every run."""
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(run_id, "synthesize")
    _pipeline_mod._stage_log_close(run_id)

    summaries = recorder.of("summary")
    assert len(summaries) == 1, f"expected one closing summary: {recorder.kinds()}"
    assert summaries[0]["stage"] == "synthesize"
    # No divider is opened for a stage that will never run.
    assert recorder.texts("divider") == ["Final synthesis"]

    # Idempotent, exactly like the stage log it rides.
    _pipeline_mod._stage_log_close(run_id)
    assert len(recorder.of("summary")) == 1


# ===========================================================================
# (d) the run's buffer is opened ONCE and closed on EVERY way out
# ===========================================================================
async def test_a_full_run_opens_its_buffer_once_and_closes_it(monkeypatch):
    """Drives the real pipeline end to end against the stubbed harness.

    Two separate claims: the lifecycle is called correctly, and the dividers the
    run actually emitted name the same stages the run actually reported. The
    second is what stops this passing on a run that emitted two dividers and no
    work."""
    recorder = _install(monkeypatch)
    opened: list[Any] = []
    closed: list[Any] = []
    real_open, real_close = run_events.open_run, run_events.close_run

    async def _open(run_id, tenant_id):
        opened.append(run_id)
        await real_open(run_id, tenant_id)

    async def _close(run_id):
        closed.append(run_id)
        await real_close(run_id)

    async def _max_seq(run_id, tenant_id):
        return 0

    async def _writer(tenant_id, rows):
        return None

    monkeypatch.setattr(run_events, "open_run", _open)
    monkeypatch.setattr(run_events, "close_run", _close)
    monkeypatch.setattr(run_events, "_read_max_seq", _max_seq)
    monkeypatch.setattr(run_events, "_writer", _writer)

    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert len(opened) == 1, (
        f"the run's event buffer was opened {len(opened)} time(s); a second open "
        "orphans the first buffer's undrained events"
    )
    assert closed, "the run finished without ever closing its event buffer"

    reported = set(_stage_sequence(statements))
    assert reported, "the stubbed run reported no stage — every assertion is vacuous"

    divided = set(recorder.texts("divider"))
    assert divided, "the run crossed stage boundaries and emitted no divider at all"
    # Every divider is a LABEL (or the key of a stage the schema does not
    # declare), and at least one of them differs from its key — otherwise this
    # would pass on an implementation that emitted keys throughout.
    labels = {_label_of(key) for key in reported}
    assert divided <= labels, (
        f"a divider was emitted that is neither a label nor a reported key: "
        f"{sorted(divided - labels)}"
    )
    assert divided & {"Deep research", "Adaptive intake", "Final synthesis"}, (
        f"not one divider carried a human label — this would pass on an "
        f"implementation that emitted raw keys throughout: {sorted(divided)}"
    )
    assert "deep_research" not in divided
    assert "research_division" not in divided


async def test_close_run_is_reached_even_when_the_staged_body_raises(monkeypatch):
    """The `finally` in `run()` is the only thing standing between a crashed run
    and a leaked drain task holding undrained events forever."""
    statements: list[Any] = []
    sessionmaker = _no_db_sessionmaker(statements)
    monkeypatch.setattr(
        "nestor_pulse_sdk.db.base.get_sessionmaker", sessionmaker, raising=True
    )
    monkeypatch.setattr(_pipeline_mod, "get_sessionmaker", sessionmaker, raising=True)

    closed: list[Any] = []

    async def _close(run_id):
        closed.append(run_id)

    monkeypatch.setattr(run_events, "close_run", _close)

    async def _boom(self, **kwargs):
        # Deliberately NOT cap/billing wording and NOT a refused-model-id wording,
        # so `classify` returns HARD (not HARD_WALL, not CONFIG_ERROR) and the
        # park arm is not taken — this test is about the `finally`, not the park.
        raise RuntimeError("synthetic staged-body failure for the close_run test")

    monkeypatch.setattr(_pipeline_mod.TribunalPipeline, "_run_staged", _boom)

    pipeline = _pipeline_mod.TribunalPipeline(audited=object())
    run_id = uuid.uuid4()
    with pytest.raises(RuntimeError):
        await pipeline.run(brief="a brief", run_id=run_id, tenant_id=uuid.uuid4())

    assert closed == [run_id], (
        "the staged body raised and the run's event buffer was never closed"
    )


# ===========================================================================
# (e) one dispatch header, then the indented children it introduces
# ===========================================================================
async def test_a_batch_of_three_angles_emits_one_dispatch_then_three_agent_runs(
    monkeypatch,
):
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(monkeypatch, {"openai": _runner_ok(calls, "openai")})

    angles = [
        {"query": "q1", "stakes": "med", "focus_area": "A", "provider": "openai"},
        {"query": "q2", "stakes": "med", "focus_area": "B", "provider": "openai"},
        {"query": "q3", "stakes": "med", "focus_area": "C", "provider": "openai"},
    ]
    results = await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )
    assert len(results) == 3

    dispatches = recorder.of("dispatch")
    assert len(dispatches) == 1, (
        f"expected ONE dispatch header for the batch, got {len(dispatches)}: "
        f"{[d['text'] for d in dispatches]}. One per angle removes the grouping "
        f"the indented children hang under."
    )
    assert "Dispatching 3 agents" in dispatches[0]["text"]
    for number in ("01", "02", "03"):
        assert number in dispatches[0]["text"]

    runs = recorder.of("agent_run")
    assert len(runs) == 3, f"expected one agent_run per angle: {recorder.kinds()}"
    assert recorder.rows.index(dispatches[0]) < min(
        recorder.rows.index(row) for row in runs
    ), "the dispatch header must PRECEDE the children it introduces"
    assert sorted(row["meta"]["angle"] for row in runs) == [1, 2, 3]
    assert all(row["meta"]["is_live"] is True for row in runs)
    assert all(row["meta"]["provider"] == "openai" for row in runs)

    # The routing lines land once each, on the division stage rather than on the
    # money stage.
    assert len(recorder.of("plan")) == 1
    assert len(recorder.of("streams")) == 1
    assert recorder.of("plan")[0]["stage"] == "research_division"
    assert "3 angles" in recorder.of("plan")[0]["text"]


async def test_the_streams_line_names_a_dark_provider_rather_than_hiding_it(
    monkeypatch,
):
    """A run with a stream down is a run with fewer researchers than the operator
    thinks. It has to say so."""
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(monkeypatch, {"openai": _runner_ok(calls, "openai")})

    await rd.run_angles(
        angles=[{"query": "q", "stakes": "med", "focus_area": "A", "provider": "openai"}],
        audited=None,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )

    text = recorder.of("streams")[0]["text"]
    assert "openai" in text
    assert "DARK" in text, f"the disabled streams were not named: {text!r}"
    for dark in ("gemini", "claude"):
        assert dark in text


# ===========================================================================
# (f) a failed angle says WHY
# ===========================================================================
async def test_a_failed_angle_names_its_cause_and_is_never_the_bare_word_failed(
    monkeypatch,
):
    """Both failure shapes: the runner that RAISED and the envelope that said no.

    ONE enabled stream, so the coverage retry cannot fire and add rows this test
    would then have to explain."""
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(
        monkeypatch,
        {"openai": _runner_raising(calls, "openai", "429 RESOURCE_EXHAUSTED")},
    )

    with pytest.raises(rd.InsufficientProvidersError):
        await rd.run_angles(
            angles=[
                {"query": "q", "stakes": "med", "focus_area": "A", "provider": "openai"}
            ],
            audited=None,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )

    fails = recorder.of("agent_fail")
    assert len(fails) == 1, f"the raised failure emitted no agent_fail: {recorder.kinds()}"
    text = fails[0]["text"]
    assert "429 RESOURCE_EXHAUSTED" in text, f"the cause is not in the line: {text!r}"
    assert "RuntimeError" in text
    assert text.strip().lower() != "failed"
    # THE COUNTERFACTUAL: strip the word itself and there must still be a reason
    # left. Without this, "failed" plus an angle number would satisfy the check
    # above while telling the operator exactly nothing new.
    assert len(text.lower().replace("failed", "").strip()) > 20


async def test_an_envelope_error_is_reported_with_the_providers_own_message(
    monkeypatch,
):
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(
        monkeypatch,
        {
            "openai": _runner_envelope_error(
                calls, "openai", "monthly usage cap reached for this account"
            )
        },
    )

    with pytest.raises(rd.InsufficientProvidersError):
        await rd.run_angles(
            angles=[
                {"query": "q", "stakes": "med", "focus_area": "A", "provider": "openai"}
            ],
            audited=None,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )

    fails = recorder.of("agent_fail")
    assert len(fails) == 1
    assert "monthly usage cap reached" in fails[0]["text"]


# ===========================================================================
# (g) a retry names the cause and carries attempt / max / wait_s
# ===========================================================================
async def test_a_coverage_retry_emits_agent_retry_with_attempt_max_and_wait(
    monkeypatch,
):
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(
        monkeypatch,
        {
            "openai": _runner_envelope_error(calls, "openai", "stream outage"),
            "claude": _runner_ok(calls, "claude"),
        },
    )

    results = await rd.run_angles(
        angles=[
            {"query": "q-med", "stakes": "med", "focus_area": "B", "provider": "openai"}
        ],
        audited=None,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )
    assert len(results) == 1, "the coverage retry did not recover the angle"

    retries = recorder.of("agent_retry")
    assert len(retries) == 1, f"the retry emitted no agent_retry: {recorder.kinds()}"
    meta = retries[0]["meta"]
    assert meta["attempt"] == 2
    assert meta["max"] == 2
    assert meta["wait_s"] == 0
    text = retries[0]["text"]
    assert "retrying" in text
    assert "openai" in text and "claude" in text, (
        f"the retry line must name the stream it left and the one it moved to: {text!r}"
    )


async def test_an_angle_skipped_as_a_corroboration_copy_says_so(monkeypatch):
    """A deliberately unresearched angle must be VISIBLE. An angle that is simply
    absent from the feed reads as a bug."""
    recorder = _install(monkeypatch)
    calls: dict = {}
    _single_stream(monkeypatch, {"claude": _runner_ok(calls, "claude")})

    angles = [
        {
            "query": "q-copy",
            "stakes": "high",
            "focus_area": "A",
            "provider": "gemini",
            "corroboration": True,
            "corroboration_key": "k1",
        },
        {
            "query": "q-primary",
            "stakes": "high",
            "focus_area": "A",
            "provider": "claude",
            "corroboration": True,
            "corroboration_key": "k1",
        },
    ]
    await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )

    skipped = [
        row for row in recorder.of("agent_done") if "not researched" in row["text"]
    ]
    assert len(skipped) == 1, (
        f"the skipped corroboration copy left no trace: "
        f"{[r['text'] for r in recorder.of('agent_done')]}"
    )
    assert "gemini" in skipped[0]["text"]
    assert "already cover" in skipped[0]["text"]


# ===========================================================================
# (h) A RECORDER THAT RAISES cannot break the shim or the dispatch loop
# ===========================================================================
async def test_a_recorder_that_raises_on_every_call_breaks_nothing(monkeypatch):
    """This proves CALLING the emitter is safe. It CANNOT prove that BUILDING its
    arguments is safe — by the time this recorder runs, the arguments already
    exist. That is what test (i) below is for, and why both are here."""
    recorder = _install(monkeypatch, raises=True)
    run_id = uuid.uuid4()

    # The shim's choke point.
    _pipeline_mod._stage_log_transition(run_id, "intake")
    _pipeline_mod._stage_log_transition(run_id, "deep_research")
    _pipeline_mod._stage_log_close(run_id)
    assert recorder.rows, "the raising recorder was never reached — nothing was proved"

    # The paid dispatch loop.
    calls: dict = {}
    _single_stream(monkeypatch, {"openai": _runner_ok(calls, "openai")})
    angles = [
        {"query": "q1", "stakes": "med", "focus_area": "A", "provider": "openai"},
        {"query": "q2", "stakes": "med", "focus_area": "B", "provider": "openai"},
    ]
    results = await rd.run_angles(
        angles=angles, audited=None, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )
    assert [provider for provider, _ in results] == ["openai", "openai"]
    assert sorted(res["_angle"] for _, res in results) == ["A", "B"]
    assert len(calls["openai"]) == 2, "an angle was lost to the broken recorder"


# ===========================================================================
# (i) THE ARGUMENT-CONSTRUCTION PROOF — the real run_events, nothing patched
# ===========================================================================
async def _drive_run_angles_with(result: dict, run_id: uuid.UUID) -> list:
    """Two angles through the REAL emitter, with `result` as the provider reply."""
    calls: dict = {}

    async def _runner(*, query, audited, run_id, tenant_id):
        calls.setdefault("openai", []).append(query)
        return dict(result)

    original_runners = rd._PROVIDER_RUNNERS
    original_enabled = rd._enabled_providers
    rd._PROVIDER_RUNNERS = {"openai": _runner}
    rd._enabled_providers = lambda: [("openai", None)]
    try:
        return await rd.run_angles(
            angles=[
                {"query": "q1", "stakes": "med", "focus_area": "A", "provider": "openai"},
                {"query": "q2", "stakes": "med", "focus_area": "B", "provider": "openai"},
            ],
            audited=None,
            run_id=run_id,
            tenant_id=uuid.uuid4(),
        )
    finally:
        rd._PROVIDER_RUNNERS = original_runners
        rd._enabled_providers = original_enabled


async def test_a_result_missing_the_keys_the_done_line_reads_still_records_its_line(
    monkeypatch, caplog
):
    """(i), the half that matters most: NOTHING is monkeypatched on `run_events`
    except the two Postgres seams. `emit` and `emit_safe` are the real ones.

    15.4-05 CHANGED WHAT THIS ASSERTS, and the change is the whole point of the
    plan. The `agent_done` line used to read `result["facts"]` as a SUBSCRIPT, so
    a degrading provider made the TEXT CONSTRUCTION raise inside the semaphore,
    inside the paid dispatch loop; `emit_safe` swallowed it exactly as D-06
    designs it to and the run was unaffected — but THE ROW WAS LOST, about twenty
    of them on run 7dcf51d5 (D-V01-7).

    The reason the subscript was chosen still stands: a `.get(..., 0)` would print
    "0 facts" for an angle whose count is merely UNKNOWN, and a feed row must not
    assert a number the run never established (T-15.3-23). So the rule is kept
    and the intolerance is dropped — `_fact_count_label` renders the unknown in
    words. This test now asserts the LINE SURVIVES all three shapes, and that no
    build failure is reported for any of them.
    """
    persisted: list[dict] = []

    async def _max_seq(run_id, tenant_id):
        return 0

    async def _writer(tenant_id, rows):
        persisted.extend(rows)

    monkeypatch.setattr(run_events, "_read_max_seq", _max_seq)
    monkeypatch.setattr(run_events, "_writer", _writer)

    # THE NEGATIVE CONTROL, first, and it is now a control on the FIX rather than
    # on the defect: the construction the OLD line performed genuinely raises on
    # both degraded shapes, so a green run below cannot mean "these inputs were
    # harmless all along" — it means the tolerant helper is doing the work.
    with pytest.raises(KeyError):
        len({"status": "success", "report": "r"}["facts"])
    with pytest.raises(TypeError):
        len({"status": "success", "report": "r", "facts": None}["facts"])
    # And the helper that replaced it survives both, without inventing a zero.
    assert rd._fact_count_label({"status": "success", "report": "r"}) == rd._UNKNOWN_FACTS
    assert (
        rd._fact_count_label({"status": "success", "report": "r", "facts": None})
        == rd._UNKNOWN_FACTS
    )

    shapes = {
        "well_formed": {
            "status": "success",
            "report": "r",
            "facts": [1, 2],
            "cost_usd": 1.5,
        },
        # No `facts`, no `cost_usd` — the shape a degrading provider returns.
        "missing_keys": {"status": "success", "report": "r"},
        # A None where a number is expected.
        "none_facts": {"status": "success", "report": "r", "facts": None},
    }

    returned: dict[str, list] = {}
    warnings: dict[str, str] = {}
    for name, shape in shapes.items():
        run_id = uuid.uuid4()
        await run_events.open_run(run_id, uuid.uuid4())
        caplog.clear()
        try:
            with caplog.at_level(logging.WARNING):
                results = await _drive_run_angles_with(shape, run_id)
        finally:
            await run_events.close_run(run_id)
        returned[name] = [
            (provider, res["_angle"], res["_stakes"]) for provider, res in results
        ]
        # Only what the EMITTER logged. A record from another logger would make
        # the swallowed-build assertion below pass or fail for the wrong reason.
        warnings[name] = "\n".join(
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("nestor_pulse_sdk.runs.run_events")
        )

    assert returned["missing_keys"] == returned["well_formed"], (
        "a provider result missing the keys the feed line reads CHANGED what "
        f"run_angles returned: {returned['missing_keys']} vs {returned['well_formed']}"
    )
    assert returned["none_facts"] == returned["well_formed"]
    assert len(returned["well_formed"]) == 2

    # NO BUILD FAILURE ON ANY SHAPE. This is the assertion that inverted in
    # 15.4-05: it used to demand a `KeyError` in the emitter's log for the two
    # degraded shapes, because that is what the subscript produced and what the
    # emitter correctly swallowed. A swallowed build is a LOST ROW, so demanding
    # one was demanding the defect.
    for name, text in warnings.items():
        assert "KeyError" not in text and "TypeError" not in text, (
            f"the {name!r} shape still failed to BUILD its feed line, so its row "
            f"was dropped by the emitter rather than emitted: {text!r}"
        )

    # AND ALL THREE RUNS PERSISTED THEIR LINES. Two angles per run, three runs.
    done = [row for row in persisted if row["kind"] == "agent_done"]
    assert len(done) == 6, (
        "every angle of every shape must record a done line; a degrading "
        f"provider must not cost the row: {[row['text'] for row in done]}"
    )
    texts = [row["text"] for row in done]
    assert sum("2 facts" in text for text in texts) == 2, (
        f"the well-formed fact count never made it into a row: {texts}"
    )
    degraded_texts = [text for text in texts if rd._UNKNOWN_FACTS in text]
    assert len(degraded_texts) == 4, (
        f"the two degraded shapes did not record honest-unknown lines: {texts}"
    )
    for text in degraded_texts:
        assert not re.search(r"\d+\s+facts", text), (
            f"a degraded angle rendered a COUNT it never established: {text!r}"
        )
        assert "0 facts" not in text


def test_a_summary_whose_inputs_are_malformed_costs_the_line_not_the_divider(
    monkeypatch,
):
    """(i), the shim half. The summary's `worked` is derived from run-scoped
    timing state; corrupt that state and the CONSTRUCTION raises.

    What must survive: the transition itself, and the divider that follows the
    summary. A construction failure that took the next line with it would leave
    the feed silently one stage behind for the rest of the run."""
    # NEGATIVE CONTROL: performed outside the emitter, this genuinely raises.
    with pytest.raises(ValueError):
        _pipeline_mod._stage_event_summary_meta(
            {"opened_at": "not-a-number", "items": 0}
        )

    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()
    _pipeline_mod._stage_log_transition(run_id, "intake")
    _pipeline_mod._STAGE_LOGS[str(run_id)]["opened_at"] = "not-a-number"

    _pipeline_mod._stage_log_transition(run_id, "deep_research")  # must not raise

    assert recorder.texts("divider") == ["Adaptive intake", "Deep research"], (
        "the divider after a failed summary construction was lost: "
        f"{recorder.texts('divider')}"
    )
    assert recorder.of("summary") == [], (
        "a summary was emitted from inputs that cannot be read — the line should "
        "be DROPPED, never fabricated"
    )


def test_a_stage_that_reported_no_summary_block_still_summarises_cleanly(monkeypatch):
    """The common case: nothing routes a `summary` block through this choke point
    today, so the line has only its own timing to read. It must still be emitted,
    with `items` and `cost` simply absent rather than invented."""
    recorder = _install(monkeypatch)
    run_id = uuid.uuid4()

    _pipeline_mod._stage_log_transition(run_id, "intake", {"items": [{"name": "a"}]})
    _pipeline_mod._stage_log_transition(run_id, "deep_research")

    meta = recorder.of("summary")[0]["meta"]
    assert set(meta) == {"worked", "actions"}, (
        f"absent summary values must be omitted, not defaulted: {meta}"
    )
    assert meta["actions"] == 1


# ===========================================================================
# (j) 15.4-05 — A DEGRADED ANGLE STILL SAYS IT FINISHED
#
# THE COUNT OF RECORDED EVENTS IS THE LOAD-BEARING ASSERTION IN EVERY TEST
# BELOW. Before this fix the degraded shapes recorded ZERO events: the build
# lambda raised, `emit_safe` swallowed it exactly as D-06 designs it to, and the
# row vanished. A test that only checked "no exception escaped" would therefore
# have passed against the bug, which is the failure mode this whole phase exists
# to stop. `len(...) == 1` is what fails without the helpers.
#
# The second rule these tests pin is the honest one: a count that could not be
# established renders as UNKNOWN. `0` would be a number the run is claiming to
# have measured, and a feed row must not assert something the run never
# established (T-15.3-23).
# ===========================================================================


def _own_harness():
    """The own-researcher scripted harness, imported LAZILY and on purpose.

    `test_own_researcher.py` imports `_Recorder` from THIS module at module
    scope, so a module-scope import back would be a genuine cycle — whichever
    file pytest imported first would see a half-built module and fail at
    collection. Inside a function body both modules are fully initialised. This
    is still the ONE harness rather than a second one to drift, which is the
    rule this file's header already states for `test_engine_e2e_stubbed`.
    """
    from nestor_pulse_sdk.tests import test_own_researcher as own_tests

    return own_tests


_ONE_ANGLE = [{"query": "q1", "stakes": "med", "focus_area": "A", "provider": "openai"}]


async def _one_angle_returning(monkeypatch, result: dict) -> list:
    calls: dict = {}
    _single_stream(monkeypatch, {"openai": _runner_ok(calls, "openai", result)})
    return await rd.run_angles(
        angles=list(_ONE_ANGLE),
        audited=None,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )


async def test_j_a_healthy_angle_still_renders_its_fact_count(monkeypatch):
    """The unchanged case, asserted FIRST. Without it the three degraded tests
    below would pass just as happily against a helper that had given up on
    counting altogether and printed "unknown" for every angle ever run."""
    recorder = _install(monkeypatch)

    results = await _one_angle_returning(
        monkeypatch,
        {"status": "success", "report": "r", "facts": [1, 2, 3], "cost_usd": 1.5},
    )
    assert len(results) == 1

    done = recorder.of("agent_done")
    assert len(done) == 1, f"expected one done line for one angle: {recorder.kinds()}"
    assert done[0]["text"] == "Angle 01 done — 3 facts · openai", (
        f"the healthy done line changed shape: {done[0]['text']!r}"
    )
    assert done[0]["text"].endswith("facts · openai")
    assert done[0]["meta"]["angle"] == 1
    assert done[0]["meta"]["provider"] == "openai"
    assert done[0]["meta"]["cost"] == pytest.approx(1.5)


@pytest.mark.parametrize(
    "shape,why",
    [
        ({"status": "success", "report": "r"}, "no facts key at all"),
        ({"status": "success", "report": "r", "facts": None}, "a None under facts"),
        ({"status": "success", "report": "r", "facts": 7}, "an int, which len refuses"),
        ({"status": "success", "report": "r", "facts": "none found"}, "a str"),
    ],
)
async def test_j_a_degraded_result_still_records_exactly_one_done_line(
    monkeypatch, shape, why
):
    """Four shapes a degrading provider really does return. Each must still
    produce ONE `agent_done` row, attributable, with the count admitted as
    unknown rather than fabricated as zero.

    The `str` case is not padding: `len("none found")` is 10, so a helper that
    merely called `len` would print "10 facts" — a number invented out of a
    provider's prose, which is worse than the vanished row it replaced.
    """
    recorder = _install(monkeypatch)

    results = await _one_angle_returning(monkeypatch, shape)
    assert len(results) == 1, f"the angle itself must be unaffected ({why})"

    done = recorder.of("agent_done")
    assert len(done) == 1, (
        f"a result with {why} recorded {len(done)} done line(s), not 1 — before "
        f"15.4-05 this was 0 and the feed showed an angle that never ended: "
        f"{recorder.kinds()}"
    )
    text = done[0]["text"]
    assert rd._UNKNOWN_FACTS in text, (
        f"the count was not admitted as unknown: {text!r}"
    )
    assert "0 facts" not in text, f"a fabricated zero reached the feed: {text!r}"
    assert not re.search(r"\d+\s+facts", text), (
        f"a count the run never established was rendered anyway: {text!r}"
    )
    # STILL ATTRIBUTABLE. A row nobody can tie to an angle or a provider is only
    # marginally better than no row.
    assert done[0]["meta"]["angle"] == 1
    assert done[0]["meta"]["provider"] == "openai"
    assert "openai" in text


async def test_j_the_done_line_is_still_built_inside_the_emitters_try(
    monkeypatch, caplog
):
    """D-06, PROVEN AT THIS SITE, AFTER the site stopped raising on its own.

    `_fact_count_label` promising never to raise is a promise by one helper.
    `build=lambda:` is the STRUCTURAL guarantee that whatever is built here is
    built inside `emit_safe`'s try — the thing that survives a future edit to
    the helper. Forcing the helper to raise is the only way to keep asserting
    it: if anyone ever "tidies" `emit_safe` by hoisting `build()` above its
    `try`, this test fails with the RuntimeError escaping into `run_angles`.
    """

    def _boom(_result):
        raise RuntimeError("synthetic label failure for the D-06 site proof")

    monkeypatch.setattr(rd, "_fact_count_label", _boom)
    recorder = _install(monkeypatch)

    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="nestor_pulse_sdk.runs.run_events"):
        results = await _one_angle_returning(
            monkeypatch, {"status": "success", "report": "r", "facts": [1, 2]}
        )

    assert len(results) == 1, "a raising build cost the paid angle, not just its row"
    emitted = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("nestor_pulse_sdk.runs.run_events")
    )
    assert "RuntimeError" in emitted, (
        "the raising build was never reached, so nothing about D-06 was proved: "
        f"{emitted!r}"
    )
    assert recorder.of("agent_done") == [], (
        "a line whose text could not be built was emitted anyway — DROPPED is "
        "correct here, fabricated is not"
    )


# --- the own_research half -------------------------------------------------


async def test_j_an_own_research_turn_reports_what_it_skipped(monkeypatch):
    """The unchanged own-research case, for the same counterfactual reason as
    the healthy angle above: two of the three emitted entries carry no usable
    source URL, so `2 skipped` is a real difference and not a placeholder."""
    own_tests = _own_harness()
    monkeypatch.setenv("SERPAPI_API_KEY", own_tests._FAKE_KEY)
    _serpapi.reset_breaker()
    recorder = _install(monkeypatch)

    audited = own_tests._ScriptedOwnAudited(
        [
            own_tests._server_fetch_turn("https://fin.belgium.be/duty"),
            own_tests._emit_turn(
                facts=[
                    {
                        "statement": "Diesel duty in Belgium rose in April 2026.",
                        "source_url": "https://fin.belgium.be/duty",
                    },
                    {
                        "statement": "This one cites a scheme we refuse.",
                        "source_url": "ftp://example.com/x",
                    },
                    {"statement": "This one cites nothing at all."},
                ],
                not_found=[],
            ),
        ]
    )
    try:
        await own.run_own_research(
            question="q",
            facet="f",
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            plan=own_tests._PLAN,
        )
    finally:
        _serpapi.reset_breaker()

    done = recorder.of("agent_done")
    assert len(done) == 1, f"expected one own-research done line: {recorder.kinds()}"
    assert done[0]["text"] == "Own query done — 1 facts from 1 pages · 2 skipped"
    assert done[0]["stage"] == "own_research"
    assert done[0]["meta"]["provider"] == own.PROVIDER


async def test_j_an_uncountable_fact_block_still_records_its_done_line(monkeypatch):
    """`_raw_fact_count` RAISES rather than guess, and that contract is correct
    and unchanged — the guard lives at the feed line, in `_skipped_label`.

    Before 15.4-05 this recorded ZERO `agent_done` rows: every own-research turn
    whose emitted block had no countable `facts` entry simply vanished from the
    feed. The facts and pages counts are lengths of lists this module built, so
    they are always real; only the skipped term can be unknown, and it says so.
    """
    own_tests = _own_harness()
    monkeypatch.setenv("SERPAPI_API_KEY", own_tests._FAKE_KEY)
    _serpapi.reset_breaker()

    # NEGATIVE CONTROL: the count genuinely refuses this block. Without it a
    # green run below could mean the input was countable after all.
    uncountable = {"not_found": ["the 2027 tariff schedule"]}
    with pytest.raises((KeyError, TypeError)):
        own._raw_fact_count(
            {"type": "tool_use", "name": "emit_fact_list", "input": uncountable}
        )

    recorder = _install(monkeypatch)
    audited = own_tests._ScriptedOwnAudited(
        [
            own_tests._server_fetch_turn("https://fin.belgium.be/duty"),
            own_tests._emit_turn_with_raw_input(uncountable),
        ]
    )
    try:
        await own.run_own_research(
            question="q",
            facet="f",
            audited=audited,
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            plan=own_tests._PLAN,
        )
    finally:
        _serpapi.reset_breaker()

    done = recorder.of("agent_done")
    assert len(done) == 1, (
        f"an uncountable fact block recorded {len(done)} done line(s), not 1 — "
        f"before 15.4-05 this was 0: {recorder.kinds()}"
    )
    text = done[0]["text"]
    # The two counts that ARE established survive intact — the page count came
    # from a fetch turn, so it is 1 rather than a vacuous 0.
    assert "0 facts from 1 pages" in text, (
        f"the counts the turn DID establish were lost with the skipped term: {text!r}"
    )
    assert own._UNKNOWN_SKIPPED in text, (
        f"the uncomputable skipped count was not admitted as unknown: {text!r}"
    )
    assert not re.search(r"\d+\s+skipped", text), (
        f"a skipped count that cannot be computed was printed anyway: {text!r}"
    )
    assert done[0]["stage"] == "own_research"
    assert done[0]["meta"]["provider"] == own.PROVIDER


# ===========================================================================
# the `worked` formatter, because a summary line is mostly that string
# ===========================================================================
@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0s"), (8, "8s"), (59, "59s"), (60, "1m 00s"), (744, "12m 24s"), (3900, "1h 05m")],
)
def test_worked_reads_in_the_designs_register(seconds, expected):
    assert _pipeline_mod._stage_event_worked(seconds) == expected


def test_worked_never_returns_a_negative_duration():
    """`time.monotonic` cannot step backwards, but the value reaching this
    formatter passes through a dict a defect could corrupt."""
    assert _pipeline_mod._stage_event_worked(-12) == "0s"


# ===========================================================================
# PHASE 21 — THE STAGES 15.3 LEFT SILENT NOW EMIT A BODY (plan 21-03)
#
# WHAT "A BODY" MEANS HERE, AND WHY THAT DEFINITION AND NO OTHER. 15.3 wired the
# run-event contract into four of the pipeline's thirteen stages. The other nine
# emitted nothing, and `_stage_event_boundary` gave each of them a `divider` and
# a `summary` anyway — so every one of them rendered as a phase HEADING WITH
# NOTHING UNDER IT, and the collapse toggle above it expanded to reveal nothing.
#
# `RunFeed.tsx` builds each phase block from
#   `events.filter(e => e.kind !== "divider" && e.kind !== "summary")`
# and calls that `body`. The assertions below filter on exactly that predicate,
# so they measure WHAT THE OPERATOR SEES rather than what the engine intended. An
# assertion that merely counted events on the stage would have passed against the
# defect from the day 15.3 shipped: `verify` has always had two events.
#
# 21-03 is the `verify` half — the stage the operator named twice and the one
# where the run's money and its meaning both live. Plans 21-05 and 21-06 extend
# `stage_events.py` for the remaining seven stages and should extend THIS section
# in the same shape rather than starting a new file: `cloudbuild.test-engine.yaml`
# already names this path in its WANTED list, and EXPECTED_FILES stays 44.
#
# EVERY TEST BELOW IS PURE — no Postgres, no provider key, no network. The two
# `run_events` operations that touch Postgres are module-level TEST SEAMS; they
# are replaced, never reached past. `emit` and `emit_safe` are the REAL ones in
# every test here, because a recorder installed over either would make these
# assertions statements about the double rather than about argument construction.
# ===========================================================================


class _Persisted:
    """A stand-in for `run_events._writer` — the rows that would reach the table.

    Installed at the DEEPEST seam that is still not Postgres, so what these tests
    read is what the `run_event` table would have been sent: past the real
    `emit_safe`, the real `build()` thunk, the real vocabulary check, the real
    PII scrub and the real clamp. `emit` and `emit_safe` stay untouched.
    """

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    async def __call__(self, tenant_id: Any, batch: list) -> None:
        self.rows.extend(batch)

    def on(self, stage: str) -> list[dict[str, Any]]:
        return [row for row in self.rows if row["stage"] == stage]

    def of(self, stage: str, kind: str) -> list[dict[str, Any]]:
        return [row for row in self.on(stage) if row["kind"] == kind]

    def body(self, stage: str) -> list[dict[str, Any]]:
        """`RunFeed.tsx`'s own `body` filter, verbatim."""
        return [
            row
            for row in self.on(stage)
            if row["kind"] != "divider" and row["kind"] != "summary"
        ]

    def texts(self, stage: str, kind: str) -> list[str]:
        return [row["text"] for row in self.of(stage, kind)]


def _install_writer(monkeypatch) -> _Persisted:
    persisted = _Persisted()

    async def _max_seq(run_id, tenant_id):
        return 0

    monkeypatch.setattr(run_events, "_read_max_seq", _max_seq)
    monkeypatch.setattr(run_events, "_writer", persisted)
    return persisted


def _names_a_cause(text: str) -> bool:
    """The predicate test (d) applies to a failure line — AND to its control.

    Written once, as a named function, precisely so the negative control can be
    run through the SAME predicate. A control that applied a slightly different
    rule would prove nothing about the assertion it is controlling.
    """
    lowered = text.strip().lower()
    if len(lowered) <= 30:
        return False
    return any(
        cause in lowered
        for cause in ("timed out", "timeout", "crash", "budget cap")
    )


# --- (a) the stage is no longer a label with nothing under it ---------------
async def test_verify_stage_is_no_longer_a_label_with_nothing_under_it(monkeypatch):
    """SC1, at the one stage D-04 singles out.

    WHAT BREAKS IF THIS FIRES: the run page shows "Skeptic verification" as a
    heading with an empty block under it, while the engine spends most of the
    run's budget beneath that heading — which is complaint 3 of the operator's
    2026-08-10 UAT, verbatim.
    """
    persisted = _install_writer(monkeypatch)
    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    # THE VACUITY GUARD, FIRST. A harness that stopped before verify would make
    # every filter below empty, and an empty filter compared with `>= 0` reads as
    # a pass. This asserts the run actually REPORTED the stage before anything
    # measures what it emitted there.
    assert "verify" in _stage_sequence(statements), (
        "the stubbed run never reported the verify stage — every assertion below "
        f"would be vacuous: {_stage_sequence(statements)}"
    )
    assert persisted.on("verify"), (
        "the verify stage produced no run event at all, not even a divider"
    )

    body = persisted.body("verify")
    assert len(body) >= 2, (
        "the verify stage is still a label with nothing under it: its only rows "
        f"are {[row['kind'] for row in persisted.on('verify')]}. Before 21-03 this "
        f"was 0."
    )


# --- (b) ONE dispatch header for the stage, not one per cluster -------------
async def test_verify_emits_exactly_one_dispatch_header(monkeypatch):
    """The header is what the indented per-cluster children hang under. One per
    cluster would emit a dozen headers with one child each — not this design with
    a bug in it, but a different design (this file's header, behaviour 2).

    Asserted with `== 1`, never `>= 1`: the failure this guards against is a
    header per item, which `>= 1` would happily accept.
    """
    persisted = _install_writer(monkeypatch)
    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert "verify" in _stage_sequence(statements), "vacuity guard"
    dispatches = persisted.of("verify", "dispatch")
    assert len(dispatches) == 1, (
        f"expected ONE dispatch header for the verify stage, got "
        f"{len(dispatches)}: {[row['text'] for row in dispatches]}"
    )
    # And it names the work rather than merely announcing it.
    assert "cluster" in dispatches[0]["text"]
    assert "claims selected" in dispatches[0]["text"]


# --- (c) every cluster that starts also finishes ----------------------------
async def test_a_verify_cluster_row_pairs_with_a_finish_row(monkeypatch):
    """The ENGINE-side half of the positional pairing the frontend relies on.

    `feedRows.ts::settledSeqs` settles an `agent_run` by counting the finish rows
    that follow it on the same stage — there is no correlation key (D-07). So an
    engine that emitted a start with no finish would leave a row spinning forever,
    which is complaint 1 of the same UAT. If that ever regresses, this test names
    it at the site rather than leaving it to be found on screen.
    """
    persisted = _install_writer(monkeypatch)
    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert "verify" in _stage_sequence(statements), "vacuity guard"
    starts = persisted.of("verify", "agent_run")
    assert starts, "no cluster start row was emitted — the pairing is vacuous"
    finishes = persisted.of("verify", "agent_done") + persisted.of(
        "verify", "agent_fail"
    )
    assert len(finishes) >= len(starts), (
        f"{len(starts)} cluster(s) started and only {len(finishes)} finished — "
        f"the unfinished ones spin forever on the run page"
    )


# --- (d) a cluster that was not checked says WHY ----------------------------
async def test_a_failed_verify_cluster_says_why(monkeypatch):
    """Every group session crashes. The stage must say so, per cluster, in words.

    The crash path is `pipeline.py`'s `res is None` branch, reached here by making
    the group skeptic raise — `_one_group_pass` catches it and returns None,
    exactly as a real timeout does.
    """
    # THE NEGATIVE CONTROL, FIRST AND THROUGH THE SAME PREDICATE. Without it a
    # green run below could mean the predicate accepts anything.
    assert not _names_a_cause("failed"), (
        "the predicate this test applies accepts the bare word 'failed', so it "
        "proves nothing about content"
    )
    assert not _names_a_cause("Not checked: lukoil"), (
        "the predicate accepts a line that names a cluster but no cause"
    )

    persisted = _install_writer(monkeypatch)

    async def _boom(**kwargs):
        raise TimeoutError("synthetic group-skeptic timeout for the 21-03 fail row")

    monkeypatch.setattr(_pipeline_mod, "run_group_skeptic", _boom)

    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert "verify" in _stage_sequence(statements), "vacuity guard"
    fails = persisted.of("verify", "agent_fail")
    assert fails, (
        "every group session crashed and the feed said nothing about any of "
        f"them: {[row['kind'] for row in persisted.on('verify')]}"
    )
    for row in fails:
        assert _names_a_cause(row["text"]), (
            f"a failure row does not name a cause: {row['text']!r}"
        )
        # AND it names WHICH cluster. A cause with no subject leaves the operator
        # unable to tell which part of the report ships unexamined.
        assert "Not checked:" in row["text"]
        assert row["text"].strip().lower() != "failed"


# --- (e) the row budget states its elision as a visible row -----------------
async def test_the_verify_row_budget_states_its_elision_as_a_row(monkeypatch):
    """D-05. A bounded feed that truncates SILENTLY is the failure the run_event
    table exists to end: the operator cannot tell "this stage checked 3 clusters"
    from "this stage checked 10 and showed you 3".

    Driven through the real emitter with an explicit small `limit`, rather than
    through `monkeypatch.setenv`: `MAX_ROWS_PER_STAGE` is resolved at IMPORT, so
    setting the environment variable after import would silently do nothing —
    the exact false-green this project keeps catching.
    """
    persisted = _install_writer(monkeypatch)
    group = {
        "entity": "lukoil",
        "attribute": "benelux_retail",
        "stakes": "high",
        "claims": [{"text": "a claim"}],
    }

    run_id = uuid.uuid4()
    await run_events.open_run(run_id, uuid.uuid4())
    budget = stage_events.RowBudget(run_id, "verify", limit=3)
    try:
        for _ in range(10):
            stage_events.emit_verify_group_run(run_id, budget, group=group)
        assert budget.used == 3 and budget.elided == 7, (budget.used, budget.elided)
        budget.flush("cluster")
        # IDEMPOTENT: a second flush must not add a second elision row.
        budget.flush("cluster")
    finally:
        await run_events.close_run(run_id)

    assert len(persisted.of("verify", "agent_run")) == 3, (
        "the budget did not bound the per-item rows: "
        f"{len(persisted.of('verify', 'agent_run'))}"
    )
    elisions = persisted.of("verify", "thinking")
    assert len(elisions) == 1, (
        f"expected exactly one elision row, got {len(elisions)}: "
        f"{[row['text'] for row in elisions]}"
    )
    text = elisions[0]["text"]
    # THE REAL COUNT, not a fixed string. A row reading "some rows not shown"
    # would satisfy a presence check and tell the operator nothing.
    assert "7 more cluster(s)" in text, (
        f"the elision row does not carry the real number of refused rows: {text!r}"
    )
    assert "first 3" in text, f"the elision row does not state the bound: {text!r}"
    assert elisions[0]["meta"]["items"] == 7


async def test_a_verify_stage_inside_its_budget_emits_no_elision_row(monkeypatch):
    """The counterfactual for (e). Without it, a `flush` that emitted its row
    unconditionally would pass the test above and add a false "0 more" line to
    every healthy run."""
    persisted = _install_writer(monkeypatch)
    group = {"entity": "e", "attribute": "a", "stakes": "med", "claims": []}

    run_id = uuid.uuid4()
    await run_events.open_run(run_id, uuid.uuid4())
    budget = stage_events.RowBudget(run_id, "verify", limit=5)
    try:
        for _ in range(2):
            stage_events.emit_verify_group_run(run_id, budget, group=group)
        budget.flush("cluster")
    finally:
        await run_events.close_run(run_id)

    assert len(persisted.of("verify", "agent_run")) == 2
    assert persisted.of("verify", "thinking") == [], (
        "a stage that never overflowed still announced an elision"
    )


# --- (f) no verify emit can fail the run ------------------------------------
async def test_no_verify_emit_can_fail_the_run(monkeypatch):
    """D-06 at these sites: a degraded group costs the ROW at worst, never the run.

    The two shapes are the ones a restored or degrading run really produces: a
    group dict with no `claims` key, and a `verdicts_by_index` that is not a
    mapping at all.
    """
    # THE NEGATIVE CONTROL, FIRST. Performed the obvious way — the way a call site
    # composing its own f-string would perform it — both shapes genuinely raise.
    # Without this, a green run below could mean "the inputs were harmless after
    # all" rather than "the construction is inside the emitter's try".
    degraded_group: dict[str, Any] = {
        "entity": "lukoil",
        "attribute": "benelux_retail",
        "stakes": "high",
    }
    not_a_mapping: Any = ["support", "refute"]
    with pytest.raises(KeyError):
        len(degraded_group["claims"])
    with pytest.raises(AttributeError):
        not_a_mapping.values()

    persisted = _install_writer(monkeypatch)
    run_id = uuid.uuid4()
    await run_events.open_run(run_id, uuid.uuid4())
    budget = stage_events.RowBudget(run_id, "verify", limit=25)
    try:
        # (i) NOTHING RAISES. Every helper, against both degraded shapes.
        stage_events.emit_verify_dispatch(
            run_id, groups_selected=1, groups_total=1, multi=0,
            claims_selected=1, claims_total=1,
        )
        stage_events.emit_verify_group_run(run_id, budget, group=degraded_group)
        stage_events.emit_verify_group_done(
            run_id, budget, group=degraded_group, verdicts=not_a_mapping
        )
        stage_events.emit_verify_verdicts(
            run_id, budget, group=degraded_group, verdicts=not_a_mapping
        )
        stage_events.emit_verify_group_failed(
            run_id, budget, group=degraded_group, reason="the session timed out"
        )
        stage_events.emit_verify_closing(run_id, text=None)
        budget.flush("cluster")
    finally:
        await run_events.close_run(run_id)

    # AND THE ROWS SURVIVE. 15.4-05's lesson: a swallowed build is a LOST ROW, so
    # "nothing raised" alone would have passed against a version that dropped
    # every line. The counts are the load-bearing part.
    assert len(persisted.of("verify", "dispatch")) == 1
    assert len(persisted.of("verify", "agent_run")) == 1
    assert len(persisted.of("verify", "agent_done")) == 1
    assert len(persisted.of("verify", "agent_fail")) == 1
    # The cluster's finish line admits it has no verdicts rather than inventing a
    # tally the run never established (T-15.3-23).
    assert "no verdict returned" in persisted.texts("verify", "agent_done")[0]
    # A non-mapping produces no verdict rows, and no elision either — nothing was
    # refused, so nothing may be announced as refused. AND a closing sentence that
    # came out blank emitted NOTHING rather than a blank row: `emit` accepts an
    # empty text and would queue it, and an empty row renders as a blank LINE,
    # which `RUN_EVENT_KINDS`' own comment calls worse than an absent one.
    assert persisted.of("verify", "thinking") == [], (
        "a degraded verify stage emitted a thinking row it had no content for: "
        f"{persisted.texts('verify', 'thinking')!r}"
    )


async def test_the_verify_closing_line_is_emitted_when_there_is_a_sentence(
    monkeypatch,
):
    """The counterfactual for the blank-row rule asserted in (f).

    Without it, an `emit_verify_closing` that had simply stopped emitting would
    satisfy the assertion above and silently remove G-10's degradation sentence —
    the one line standing between an operator scanning a green feed and a run
    whose verification was gutted.
    """
    persisted = _install_writer(monkeypatch)
    sentence = (
        "VERIFICATION DEGRADED — 4 of 17 selected claims were never checked"
    )

    run_id = uuid.uuid4()
    await run_events.open_run(run_id, uuid.uuid4())
    try:
        stage_events.emit_verify_closing(run_id, text=sentence)
    finally:
        await run_events.close_run(run_id)

    assert persisted.texts("verify", "thinking") == [sentence]


async def test_the_verify_closing_row_carries_the_same_sentence_as_the_stage_detail(
    monkeypatch,
):
    """G-10, across BOTH surfaces. `_verify_closing_item` is deliberately the one
    place that sentence is composed; 21-03 binds it once and hands the feed row
    and the stage detail the same object. If a second composer is ever introduced,
    the run page and the intake card start reporting different degradation for the
    same run — and only one of them would be right.
    """
    persisted = _install_writer(monkeypatch)
    audited = _ScriptedProvidersAudited()
    _result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert "verify" in _stage_sequence(statements), "vacuity guard"
    # The `set_stage` writes are captured as raw JSON, so the names are parsed
    # back out rather than substring-matched — a JSON escape of an em dash would
    # otherwise make an identical sentence look different.
    detail_names: list[str] = []
    for entry in _stage_detail_entries(statements, "verify"):
        for item in (json.loads(entry).get("verify") or {}).get("items") or []:
            name = item.get("name")
            if name:
                detail_names.append(str(name))
    assert detail_names, "the verify stage wrote no stage_detail — vacuous compare"

    feed_lines = persisted.texts("verify", "thinking")
    assert feed_lines, "the verify stage emitted no closing line"
    assert feed_lines[-1] in detail_names, (
        "the closing feed row and the stage detail are not the same sentence:\n"
        f"  feed:   {feed_lines[-1]!r}\n  detail: {detail_names!r}"
    )


async def test_a_raising_verify_composer_costs_the_row_and_not_the_run(monkeypatch):
    """The STRUCTURAL half of (f), and the one that survives a future edit.

    A composer promising never to raise is a promise by one helper.
    `build=lambda:` is the structural guarantee that whatever it builds is built
    inside the emitter's try. Forcing the composer to raise is the only way to
    keep asserting that: if anyone ever "tidies" the emitter by hoisting `build()`
    above its `try`, this run dies instead of losing a row.

    This is also where "(ii) the run completes" is proved — end to end, through
    the real pipeline, with the real emitter.
    """
    persisted = _install_writer(monkeypatch)

    def _boom(_group, _verdicts):
        raise RuntimeError("synthetic verify composer failure for the D-06 proof")

    monkeypatch.setattr(stage_events, "_verify_group_done_event", _boom)

    audited = _ScriptedProvidersAudited()
    result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    # THE RUN COMPLETES.
    assert "done" in _stage_sequence(statements), (
        f"a raising feed composer cost the RUN, not just its row: "
        f"{_stage_sequence(statements)}"
    )
    assert result is not None
    # The row it could not build is DROPPED — correct here; fabricated is not.
    assert persisted.of("verify", "agent_done") == [], (
        "a line whose text could not be built reached the feed anyway"
    )
    # ...and the stage still has a body, so one broken row did not silence the
    # stage. This is what stops the test passing on an implementation that gave up
    # on the whole stage the moment one composer failed.
    assert persisted.of("verify", "agent_run"), (
        "one raising composer silenced every other row on the stage"
    )
