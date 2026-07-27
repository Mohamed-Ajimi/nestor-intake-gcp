"""D-F — the engine logs its STAGES, not only its failures (plan 15.2-24).

WHY THIS FILE EXISTS
--------------------
All 72 log lines run `d6bb3aae` produced between 08:09 and 08:53 were either the
question workshop's own output or angle-failure warnings. Not one success marker.
Not one stage transition. So when the run went quiet at 08:41 there was nothing to
read, diagnosis fell back to Cloud Run CPU metrics, and that produced a confident,
WRONG conclusion: that the pipeline had stalled. It had not — it was blocked on
long-poll I/O the whole time and resumed on its own at 09:07 with
`OpenAI deep-research: RESUMING the existing response`. The withdrawn D-C section
of `15.2-V01-ABORTED-FINDINGS.md` records the misdiagnosis in full, and its
closing lesson is the requirement this file pins:

    on this engine, neither log silence nor idle CPU is evidence of a stall.

A single INFO line per stage entry and exit makes the difference readable in
seconds: the LAST `stage_enter` line names the stage the run is sitting inside, so
"deep_research entered, 24 angles dispatched" is distinguishable from silence.
This file proves those lines exist, that they are emitted once per TRANSITION
rather than once per write, that they carry no client content, and that a broken
logger cannot cost a paid run.

NO LLM CALL, NO DATABASE, NO NETWORK. The end-to-end behaviours drive the SAME
stubbed harness `test_engine_e2e_stubbed.py` uses — imported, never re-built, for
the reason that file states about its own coupling guards: a second harness is a
second thing to drift. No mocking library.

NO PYTEST MARKER, deliberately, for the same reason `test_engine_e2e_stubbed.py`
carries none: the engine gate runs `-m "not live"` and this file must be SELECTED
by it. `asyncio_mode = "auto"` is set in `tribunal/pyproject.toml`, so the async
tests below are plain `async def`.

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod

# The stubbed end-to-end harness, IMPORTED rather than rebuilt. `_engine_run`
# installs every seam (no DB, no provider, no key) and returns the run result plus
# the SQL statements the run would have executed; `_stage_sequence` decodes the
# stage keys out of those statements, which is what makes "every stage the run
# REPORTED has an entry line" an assertion about the database's view of the run
# rather than about the log agreeing with itself.
from nestor_pulse_sdk.tests.test_engine_e2e_stubbed import (
    _ScriptedProvidersAudited,
    _engine_run,
    _stage_sequence,
)

#: The prefix every stage line in `pipeline.py` shares.
_PREFIX = "tribunal_pipeline "

#: A stage line is ONLY allowed to contain `key=value` pairs whose values are
#: integers, decimal durations or stage keys. This is the T-15.2-240 whitelist:
#: it does not ask "does the line happen to contain a URL", it refuses everything
#: that is not a count, a key or a duration in the first place.
_ALLOWED_LINE = re.compile(
    r"^tribunal_pipeline (?:stage_enter|stage_exit|run_stages_complete): "
    r"(?:[a-z][a-z0-9_]*=[a-z0-9_.]+(?: |$))*$"
)

#: No stage line may be longer than this. A prompt body or a claim text cannot fit.
_MAX_LINE_CHARS = 200


# ---------------------------------------------------------------------------
# readers over the captured log records
# ---------------------------------------------------------------------------
def _stage_records(caplog) -> list[logging.LogRecord]:
    """Every record this plan's stage logging emitted, in order.

    Scoped to the three stage events ON PURPOSE. The pipeline emits many other
    lines (workshop notes, degradation sentences, park reasons) whose content is
    other plans' contract; asserting over all of them would make this file fail
    for changes it does not own.
    """
    return [
        r for r in caplog.records
        if r.getMessage().startswith(_PREFIX + "stage_enter:")
        or r.getMessage().startswith(_PREFIX + "stage_exit:")
        or r.getMessage().startswith(_PREFIX + "run_stages_complete:")
    ]


def _event_lines(caplog, event: str) -> list[str]:
    prefix = f"{_PREFIX}{event}: "
    return [
        r.getMessage()[len(prefix):]
        for r in caplog.records
        if r.getMessage().startswith(prefix)
    ]


def _fields(body: str) -> dict[str, str]:
    """`stage=gate seconds=1.2 items=1` -> a dict. Never raises."""
    out: dict[str, str] = {}
    for token in body.split():
        if "=" in token:
            key, value = token.split("=", 1)
            out[key] = value
    return out


def _stages(caplog, event: str) -> list[str]:
    return [_fields(body).get("stage", "") for body in _event_lines(caplog, event)]


async def _run_with_logs(monkeypatch, caplog) -> tuple[dict, list, Any]:
    """Drive the stubbed pipeline once with INFO capture. Returns (result, statements, caplog)."""
    caplog.set_level(logging.INFO)
    audited = _ScriptedProvidersAudited()
    result, statements = await _engine_run(audited, monkeypatch=monkeypatch)
    return result, statements, caplog


# ===========================================================================
# 1. Every stage the run REPORTS has an entry line naming it
# ===========================================================================
async def test_every_reported_stage_emits_an_entry_line(monkeypatch, caplog):
    """A `stage_enter` INFO line exists for every stage key the run wrote.

    WHAT BREAKS IN PRODUCTION IF THIS FIRES: a stage that writes itself to the
    database but not to the log is a stage that can go quiet without leaving a
    trace — which is the D-C misdiagnosis, exactly, on a different stage.
    """
    _, statements, caplog = await _run_with_logs(monkeypatch, caplog)

    reported = set(_stage_sequence(statements))
    entered = set(_stages(caplog, "stage_enter"))

    assert reported, (
        "the stubbed run reported NO stage at all — the harness broke, and every "
        "assertion below would pass vacuously"
    )
    missing = reported - entered
    assert not missing, (
        f"these stages were written to run.current_stage but never logged: "
        f"{sorted(missing)}. A stage with no entry line cannot be found in the log "
        f"when the run goes quiet inside it (D-F). Logged: {sorted(entered)}"
    )
    # The run id rides every line, so a multi-run log can be filtered.
    for record in _stage_records(caplog):
        assert getattr(record, "run_id", None), (
            "every stage line must carry the run id in `extra` — without it the "
            "lines of two concurrent runs are indistinguishable"
        )


# ===========================================================================
# 2. A stage that is left emits an exit line with a duration AND counts
# ===========================================================================
async def test_stage_exit_carries_a_duration_and_counts(monkeypatch, caplog):
    """Each `stage_exit` names how long the stage was open; the four money
    stages name what they did.

    The duration is the half that makes a LONG POLL readable — a `deep_research`
    stage open for 26 minutes with no exit line yet is a run that is waiting, and
    that reads very differently from a run that has stopped.
    """
    _, _, caplog = await _run_with_logs(monkeypatch, caplog)

    exits = _event_lines(caplog, "stage_exit")
    assert exits, "no stage was ever reported as LEFT — the exit half never fired"

    by_stage: dict[str, dict[str, str]] = {}
    for body in exits:
        fields = _fields(body)
        assert "seconds" in fields, f"a stage_exit line carried no duration: {body!r}"
        # `time.monotonic()` is the clock, never the wall clock, so a clock step
        # cannot produce a negative duration.
        assert float(fields["seconds"]) >= 0.0, f"negative stage duration: {body!r}"
        # AT LEAST ONE COUNT, not specifically `items`. Most stages report the
        # number of sub-progress rows they wrote; the workshop span reports the
        # two numbers that actually matter for it instead, because it is written
        # by `StageFeed` and has no row count of this recorder's own.
        counts = set(fields) - {"stage", "seconds"}
        assert counts, f"a stage_exit line carried no count at all: {body!r}"
        # The LAST exit for a stage wins: `verify` is entered twice (verify ->
        # adjudicate -> coverage -> verify) and its counts land on the second.
        by_stage[fields.get("stage", "")] = fields

    # (e) — the four questions an operator asks of a silent run. Each count is
    # read off a value the pipeline already computed; none is derived here.
    assert "questions_in" in by_stage.get("workshop", {}), (
        f"the workshop must report how many client questions it was given: "
        f"{by_stage.get('workshop')}"
    )
    assert "winners_out" in by_stage.get("workshop", {})
    assert "angles" in by_stage.get("research_division", {}), (
        f"the division must report how many research angles it produced: "
        f"{by_stage.get('research_division')}"
    )
    assert "angles_dispatched" in by_stage.get("deep_research", {}), (
        f"the money stage must report angles dispatched / ok / failed: "
        f"{by_stage.get('deep_research')}"
    )
    assert "angles_ok" in by_stage.get("deep_research", {})
    assert "angles_failed" in by_stage.get("deep_research", {})
    assert "claims_in" in by_stage.get("gate", {}), (
        f"the gates must report claims in and claims selected: {by_stage.get('gate')}"
    )
    assert "selected_for_checking" in by_stage.get("gate", {})
    assert "sessions" in by_stage.get("verify", {}), (
        f"verification must report sessions run and verdicts written: "
        f"{by_stage.get('verify')}"
    )
    assert "verdicts" in by_stage.get("verify", {})

    # The closing summary — the line an operator greps to answer "did this run
    # get anywhere at all".
    closing = _event_lines(caplog, "run_stages_complete")
    assert len(closing) == 1, (
        f"exactly one closing summary line per run, got {len(closing)}: {closing}"
    )
    summary = _fields(closing[0])
    assert int(summary["stages"]) >= 8, (
        f"the closing line must name how many stages were entered, got {summary}"
    )
    assert float(summary["seconds"]) >= 0.0


# ===========================================================================
# 3. Entry is per TRANSITION, not per write
# ===========================================================================
async def test_a_re_reported_stage_does_not_enter_twice(monkeypatch, caplog):
    """`deep_research` is re-written on every angle callback and enters ONCE.

    Without this rule the feed's own re-reporting drowns the signal: a 24-angle
    run would emit 25 `stage_enter: stage=deep_research` lines and the "last entry
    line names where the run is waiting" property would be worthless.
    """
    _, _, caplog = await _run_with_logs(monkeypatch, caplog)

    entered = _stages(caplog, "stage_enter")
    assert entered.count("deep_research") == 1, (
        f"`deep_research` is re-reported once per angle and must still enter "
        f"exactly once; entered {entered.count('deep_research')} times: {entered}"
    )
    # An enter is always eventually matched by an exit for the same stage.
    exited = _stages(caplog, "stage_exit")
    assert exited.count("deep_research") == 1


def test_the_same_key_twice_in_a_row_is_one_entry():
    """The transition rule itself, driven directly and deterministically.

    The pipeline writes `intake` TWICE — once bare, and once with the resolved
    research plan — and that pair is the reason this rule exists. Driving the
    recorder directly rather than inferring it from a run keeps the proof honest
    when the pipeline's own stage order changes.
    """
    run_id = uuid.uuid4()
    try:
        _pipeline_mod._stage_log_transition(run_id, "intake")
        _pipeline_mod._stage_log_transition(run_id, "intake", {"items": [1, 2, 3]})
        state = _pipeline_mod._STAGE_LOGS[str(run_id)]
        assert state["entered"] == 1, (
            f"two consecutive writes of one stage key are ONE entry, got "
            f"{state['entered']}"
        )
        # The re-report still refreshed the row count the exit line will carry.
        assert state["items"] == 3
        # A genuinely different key IS a transition.
        _pipeline_mod._stage_log_transition(run_id, "workshop")
        assert _pipeline_mod._STAGE_LOGS[str(run_id)]["entered"] == 2
    finally:
        _pipeline_mod._stage_log_close(run_id)
        assert str(run_id) not in _pipeline_mod._STAGE_LOGS, (
            "closing a run must POP its registry entry — an entry left behind is a "
            "leak in a worker process that drives many runs"
        )


# ===========================================================================
# 4. T-15.2-240 — no stage line may carry client content
# ===========================================================================
async def test_no_stage_line_carries_content(monkeypatch, caplog):
    """Stage lines contain counts, keys, ids and durations. Nothing else.

    Asserted against the CAPTURED RECORDS, not by eye, and as a WHITELIST rather
    than a blacklist: a line is required to match the `key=value` shape where
    every value is a stage key, an integer or a decimal duration. A prompt body, a
    claim text, a research question or a URL cannot satisfy that pattern, so this
    holds for content nobody thought to blacklist.
    """
    _, _, caplog = await _run_with_logs(monkeypatch, caplog)

    records = _stage_records(caplog)
    assert len(records) >= 10, (
        f"only {len(records)} stage line(s) captured — the assertions below would "
        f"pass vacuously"
    )
    for record in records:
        message = record.getMessage()
        assert _ALLOWED_LINE.match(message), (
            f"a stage line escaped the counts-keys-ids-durations whitelist "
            f"(T-15.2-240): {message!r}"
        )
        # The three named shapes the plan calls out, restated explicitly so a
        # future reader sees them and not only the regex.
        assert "http" not in message, f"a URL reached a stage line: {message!r}"
        assert "\t" not in message, f"a tab (fact-list salad) reached: {message!r}"
        assert "@" not in message, f"an email-shaped token reached: {message!r}"
        assert len(message) <= _MAX_LINE_CHARS, (
            f"a stage line exceeded {_MAX_LINE_CHARS} chars ({len(message)}), which "
            f"means something unbounded was formatted into it: {message[:120]!r}…"
        )


def test_a_non_integer_count_is_dropped_not_stringified(caplog):
    """A value that is not an int never reaches the log, whatever it is.

    This is the structural half of T-15.2-240: the guard is not "reviewers will
    not pass a string", it is that a string CANNOT be rendered. A future edit that
    hands a research question to the counts recorder loses the question, not the
    client's confidentiality.
    """
    caplog.set_level(logging.INFO)
    leaked = "Wat is de marktpositie van Aral in Duitsland?"
    run_id = uuid.uuid4()
    try:
        _pipeline_mod._stage_log_counts(run_id, "gate", claims_in=3, leaked=leaked)
        _pipeline_mod._stage_log_transition(run_id, "gate")
        _pipeline_mod._stage_log_transition(run_id, "verify")
    finally:
        _pipeline_mod._stage_log_close(run_id)

    lines = _event_lines(caplog, "stage_exit")
    gate_lines = [body for body in lines if _fields(body).get("stage") == "gate"]
    assert gate_lines, f"the gate stage never reported an exit: {lines}"
    assert "claims_in=3" in gate_lines[0], (
        f"the integer count must survive: {gate_lines[0]!r}"
    )
    assert "leaked" not in gate_lines[0], (
        f"a non-integer value must be dropped WHOLE — key and value: {gate_lines[0]!r}"
    )
    for record in _stage_records(caplog):
        assert leaked not in record.getMessage()
        assert "Aral" not in record.getMessage()


# ===========================================================================
# 5. T-15.2-241 — a broken logger cannot break a paid run
# ===========================================================================
def test_a_logging_failure_never_propagates(monkeypatch):
    """Every stage-log entry point swallows its own failure.

    `runs/stages.py::set_stage` states the contract this inherits: "a progress
    write must never break the pipeline that is reporting it". A run that has
    already spent real money on deep research must not die because a log handler
    raised. NO `pytest.raises` here on purpose — nothing may escape.
    """

    class _ExplodingLogger:
        def info(self, *args, **kwargs):
            raise RuntimeError("handler exploded: token=sk-should-never-be-logged")

        def debug(self, *args, **kwargs):
            raise RuntimeError("even the fallback exploded")

        def warning(self, *args, **kwargs):
            raise RuntimeError("boom")

        def error(self, *args, **kwargs):
            raise RuntimeError("boom")

    monkeypatch.setattr(_pipeline_mod, "log", _ExplodingLogger())

    run_id = uuid.uuid4()
    # Each of these would raise if the swallow were missing.
    _pipeline_mod._stage_log_line("stage_enter", run_id, "intake")
    _pipeline_mod._stage_log_transition(run_id, "intake")
    _pipeline_mod._stage_log_counts(run_id, "intake", claims_in=1)
    _pipeline_mod._stage_log_transition(run_id, "gate", {"items": [1]})
    _pipeline_mod._stage_log_close(run_id)

    assert str(run_id) not in _pipeline_mod._STAGE_LOGS, (
        "the close must still POP the registry entry even when every log call is "
        "failing — otherwise a broken logger turns into a memory leak"
    )


def test_the_registry_is_bounded():
    """An un-closed run can never grow the registry without limit."""
    ids = [uuid.uuid4() for _ in range(_pipeline_mod._STAGE_LOG_MAX_RUNS + 8)]
    try:
        for rid in ids:
            _pipeline_mod._stage_log_transition(rid, "intake")
        assert len(_pipeline_mod._STAGE_LOGS) <= _pipeline_mod._STAGE_LOG_MAX_RUNS, (
            f"the stage-log registry grew to {len(_pipeline_mod._STAGE_LOGS)} entries; "
            f"the bound is {_pipeline_mod._STAGE_LOG_MAX_RUNS}"
        )
    finally:
        for rid in ids:
            _pipeline_mod._stage_log_close(rid)

