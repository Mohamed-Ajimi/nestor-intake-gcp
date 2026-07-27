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

It also carries the ENGINE HALF of the same plan's second defect, D-L: `RunMetrics`
and `get_run_metrics` must publish `started_at` / `completed_at`, because the
frontend has declared and CONSUMED both since Phase 15 and nothing ever produced
them — so the elapsed counter counted from PAGE LOAD and the summary card's
duration rendered an em-dash. The intake half of that seam is pinned in
`backend/tests/test_research_run_task.py`.

NO LLM CALL, NO DATABASE, NO NETWORK. The end-to-end behaviours drive the SAME
stubbed harness `test_engine_e2e_stubbed.py` uses — imported, never re-built, for
the reason that file states about its own coupling guards: a second harness is a
second thing to drift. The metrics behaviours use a hand-written duck-typed
session. No mocking library.

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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import pytest

from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod
from nestor_pulse_sdk.runs.schemas import RunMetrics

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


# ===========================================================================
# 6. CARRY-FORWARD FROM PLAN 15.2-23 — the D-I redaction reaches the operator
#
# 15.2-23 installed the egress PII scrub in `research_division.run_angles`,
# logged the count at WARNING and recorded it additively as
# `angle["pii_removed"]` — but could NOT render it, because the operator's feed
# row is built in `pipeline.py`, a file that plan did not own (its deviation 1).
# The one-line read lives in `_angle_label`, which is in THIS plan's
# `files_modified`, so the proof lives here rather than in 15.2-23's
# `test_dispatch_pii.py` — which this plan does not own and must not edit.
# ===========================================================================
def test_a_redacted_angle_says_so_on_its_feed_row():
    """The operator SEES that a dispatch was redacted — as a count, never a value.

    WHAT BREAKS WITHOUT THIS: personal data reaching the research dispatcher is a
    defect upstream of the scrub, and the operator's only in-product signal that
    it happened is this row. Without the clause the fact lives only in a WARNING
    log line nobody is watching.
    """
    angle = {
        "focus_area": "Benelux fuel-retail market share",
        "provider": "openai",
        "stakes": "high",
        "pii_removed": 2,
    }
    label = _pipeline_mod._angle_label(angle, 0)

    assert "2 personal identifier(s) removed" in label, (
        f"a redacted dispatch must say so on its own feed row: {label!r}"
    )
    # The identifier itself is NEVER rendered — the row is stored in
    # `run.stage_detail` and displayed in a browser (T-15.2-232).
    assert "@" not in label


def test_a_clean_angle_row_is_unchanged():
    """No clause on a clean angle — 15.2-23 sets the key ONLY when it scrubbed.

    A count of zero rendered as "0 personal identifier(s) removed" on every row of
    every run would be the alarm fatigue this phase keeps rejecting, and it would
    read as if a scrub had been necessary when none was.
    """
    base = {
        "focus_area": "Benelux fuel-retail market share",
        "provider": "openai",
        "stakes": "high",
    }
    clean = _pipeline_mod._angle_label(dict(base), 0)
    assert "removed" not in clean, f"a clean angle must gain no clause: {clean!r}"

    # Defensive: a malformed value from a replayed checkpoint is ignored, not
    # stringified into the operator's row.
    for junk in (0, None, "two", True, {"n": 2}):
        row = _pipeline_mod._angle_label({**base, "pii_removed": junk}, 0)
        assert row == clean, f"pii_removed={junk!r} changed the row: {row!r}"



# ===========================================================================
# 7. D-L, THE ENGINE HALF — RunMetrics publishes the two timestamps
# ===========================================================================
def test_run_metrics_carries_the_two_timestamps():
    """`RunMetrics` accepts and serialises `started_at` / `completed_at`.

    WHAT BREAKS WITHOUT THIS: `ResearchRunProgress.tsx` does
    `startedAt ? new Date(startedAt).getTime() : Date.now()`, so a null
    `started_at` makes the elapsed counter restart on every page refresh, and the
    same null makes `fmtDuration(started_at, completed_at)` render an em-dash
    (D-L). The frontend has declared and consumed both fields since Phase 15 —
    nothing ever produced them.
    """
    started = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)
    completed = started + timedelta(minutes=58)

    metrics = RunMetrics(
        run_id=uuid.uuid4(),
        engine="tribunal",
        status="completed",
        started_at=started,
        completed_at=completed,
    )
    assert metrics.started_at == started
    assert metrics.completed_at == completed

    payload = metrics.model_dump(mode="json")
    assert payload["started_at"].startswith("2026-07-27T08:09:00")
    assert payload["completed_at"].startswith("2026-07-27T09:07:00")


def test_run_metrics_still_validates_without_the_timestamps():
    """The fields are ADDITIVE: omitting them must not 500 a newer intake.

    A deploy is never atomic. An older engine build answering a newer intake's
    poll sends no timestamps at all, and the mirror's rule is "a missing field is
    simply not patched" — which only holds if the schema tolerates the absence.
    """
    metrics = RunMetrics(
        run_id=uuid.uuid4(), engine="tribunal", status="running"
    )
    assert metrics.started_at is None
    assert metrics.completed_at is None
    # And `elapsed_seconds` is NOT superseded — the A/B compare screen reads it.
    assert "elapsed_seconds" in RunMetrics.model_fields


# --- the metrics handler, driven without a database -------------------------
class _FakeResult:
    """Duck-typed stand-in for a SQLAlchemy Result."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class _FakeRun:
    """The subset of `Run` that `get_run_metrics` actually reads."""

    def __init__(
        self,
        *,
        started_at: Optional[datetime],
        completed_at: Optional[datetime],
        status: str = "completed",
    ) -> None:
        self.id = uuid.uuid4()
        self.engine = "tribunal"
        self.status = status
        self.cost_usd_total = None
        self.started_at = started_at
        self.completed_at = completed_at
        self.current_stage = "done"
        self.stage_detail = None
        self.verification_summary = None


class _FakeMetricsSession:
    """The run SELECT first, then the three count queries. No database."""

    def __init__(self, run: Any) -> None:
        self._run = run
        self._calls = 0

    async def execute(self, statement, params=None):  # noqa: ANN001 - duck type
        self._calls += 1
        if self._calls == 1:
            return _FakeResult(self._run)
        return _FakeResult(0)


async def test_get_run_metrics_projects_both_timestamps():
    """The handler passes the run row's two columns straight into `RunMetrics`.

    It already READ both columns to compute `elapsed_seconds`, so this adds no
    query and no branch — which is why it can be an additive projection rather
    than new work on a hot polling endpoint.
    """
    from nestor_pulse_sdk.runs.api import get_run_metrics

    started = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)
    completed = started + timedelta(minutes=58)
    run = _FakeRun(started_at=started, completed_at=completed)

    metrics = await get_run_metrics(run.id, session=_FakeMetricsSession(run))

    assert metrics.started_at == started
    assert metrics.completed_at == completed
    # The pre-existing elapsed computation is untouched and still agrees.
    assert metrics.elapsed_seconds == 58 * 60


async def test_get_run_metrics_tolerates_a_null_started_at():
    """A queued run has no `started_at` — that is None, never an error.

    The poll driver hits this endpoint every ~3 seconds from the moment the run is
    created, so the not-yet-started shape is the FIRST shape it ever sees.
    """
    from nestor_pulse_sdk.runs.api import get_run_metrics

    run = _FakeRun(started_at=None, completed_at=None, status="queued")

    metrics = await get_run_metrics(run.id, session=_FakeMetricsSession(run))

    assert metrics.started_at is None
    assert metrics.completed_at is None
    assert metrics.elapsed_seconds is None


@pytest.mark.parametrize("status", ["running", "completed", "parked"])
async def test_get_run_metrics_timestamps_do_not_depend_on_status(status):
    """The projection is unconditional — no status gate was added to the handler.

    `get_run_metrics` carries deliberate status rules (F2's `report_readable`
    -driven `current_stage`), and this plan touches none of them. A parked run in
    particular must still report when it started: it is paused, not un-started.
    """
    from nestor_pulse_sdk.runs.api import get_run_metrics

    started = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)
    run = _FakeRun(started_at=started, completed_at=None, status=status)

    metrics = await get_run_metrics(run.id, session=_FakeMetricsSession(run))

    assert metrics.started_at == started
    assert metrics.completed_at is None
