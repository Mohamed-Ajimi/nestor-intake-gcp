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
loop a provider result with no `facts` key, then a `facts` of `None`, and asserts
`run_angles` returns exactly what it returns for a well-formed result. Its shim
half corrupts the timing value the summary line derives `worked` from.

Both halves of (i) carry a NEGATIVE CONTROL: they first assert that the
construction genuinely raises when performed outside the emitter, so a green run
cannot mean "the input was harmless after all".

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

import logging
import uuid
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod
from nestor_pulse_sdk.pipeline.tribunal import research_division as rd
from nestor_pulse_sdk.runs import run_events
from nestor_pulse_sdk.runs.stages import ENGINE_STAGES

# The stubbed end-to-end harness, IMPORTED rather than rebuilt (same reason
# `test_stage_logging.py` states for its own use of it).
from nestor_pulse_sdk.tests.test_engine_e2e_stubbed import (
    _ScriptedProvidersAudited,
    _engine_run,
    _no_db_sessionmaker,
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


async def test_a_result_missing_the_keys_the_done_line_reads_changes_nothing(
    monkeypatch, caplog
):
    """(i), the half that matters most: NOTHING is monkeypatched on `run_events`
    except the two Postgres seams. `emit` and `emit_safe` are the real ones.

    The `agent_done` line reads `result["facts"]` as a SUBSCRIPT, deliberately —
    a `.get` defaulting to 0 would print "0 facts" for an angle whose fact count
    is merely unknown. So a degrading provider makes the TEXT CONSTRUCTION raise,
    inside the semaphore, inside the paid dispatch loop. This asserts that costs
    the line and nothing else."""
    persisted: list[dict] = []

    async def _max_seq(run_id, tenant_id):
        return 0

    async def _writer(tenant_id, rows):
        persisted.extend(rows)

    monkeypatch.setattr(run_events, "_read_max_seq", _max_seq)
    monkeypatch.setattr(run_events, "_writer", _writer)

    # THE NEGATIVE CONTROL, first: the construction the emitter is asked to
    # perform genuinely raises. Without this, a green test below could mean the
    # degraded input was harmless all along.
    with pytest.raises(KeyError):
        len({"status": "success", "report": "r"}["facts"])
    with pytest.raises(TypeError):
        len({"status": "success", "report": "r", "facts": None}["facts"])

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
        warnings[name] = "\n".join(r.getMessage() for r in caplog.records)

    assert returned["missing_keys"] == returned["well_formed"], (
        "a provider result missing the keys the feed line reads CHANGED what "
        f"run_angles returned: {returned['missing_keys']} vs {returned['well_formed']}"
    )
    assert returned["none_facts"] == returned["well_formed"]
    assert len(returned["well_formed"]) == 2

    # AND THE PATH WAS ACTUALLY TAKEN. Without this the test would pass just as
    # happily against an implementation whose thunk never touched `facts`.
    assert "KeyError" in warnings["missing_keys"], (
        "no build failure was reported for the key-missing result, so the "
        f"fragile construction was never reached: {warnings['missing_keys']!r}"
    )
    assert "TypeError" in warnings["none_facts"]
    assert "KeyError" not in warnings["well_formed"], (
        "the well-formed result also failed to build — the line is broken for "
        f"every run, not just degraded ones: {warnings['well_formed']!r}"
    )

    # The well-formed run really did persist a usable line.
    done = [row for row in persisted if row["kind"] == "agent_done"]
    assert done, "not one agent_done row reached the writer on any of the three runs"
    assert any("2 facts" in row["text"] for row in done), (
        f"the well-formed fact count never made it into a row: "
        f"{[row['text'] for row in done]}"
    )


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
