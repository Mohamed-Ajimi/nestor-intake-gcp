"""Run-event FEED CURSOR proofs (plan 15.3-06, D-05).

The engine writes an ordered ``run_event`` row per meaningful action (15.3-01) and
publishes the run's high-water mark as ``RunMetrics.event_seq`` (15.3-02). This plan
mirrors that number onto ``research_runs.event_seq`` (migration 0013) and re-emits it
on the SSE frame the page already holds, so the run page can tell that new events
exist and fetch ONLY the delta past its own position.

What this suite pins, and why each property is load-bearing:

* **The frame carries a CURSOR, never a payload.** D-05 rejects a second transport
  because two connections can disagree about when a run ended. The SSE stream stays
  the SOLE authority on terminality; the events become a PULL. A frame that carried
  the events themselves would both re-send the whole history on every change and put
  a second copy of the run's story on the authoritative connection.
* **The mirror is ADDITIVE.** A deploy is never atomic. An engine build that does not
  report a cursor must leave the column exactly as it was — NULLing it would truncate
  a live feed because the far side is one revision behind.
* **A malformed cursor never raises.** ``metrics`` is remote JSON crossing the seam
  into a ``BackgroundTask``; a raise there routes to ``on_error`` and mislabels the
  run ``failed`` (T-15.3-50).
* **``parked`` STILL ADVANCES the cursor.** This is the deliberate opposite of
  ``completed_at``, which 15.2-19/15.2-24 keep NULL for a park. A cursor is not a
  completion claim, and a parked run's feed is exactly what the operator reads before
  deciding whether to resume. Test (d) asserts BOTH halves in one test on purpose, so
  a future edit cannot "fix" one and silently break the other.
* **A cursor advance is itself a new frame.** ``stream_research_run`` emits on
  ``view != last_sent`` — a WHOLE-DICT comparison. The entire delta design rests on
  that comparison firing when only the cursor moved.

Test design (no DB): the seam, the session and the repository are all monkeypatched,
and the assertions read the values the REAL functions write rather than trusting that
a stub was called. ``app.research.run_task`` / ``app.db.stream_session`` are imported
LAZILY so this collects on a box without the app installed (the dev machine has no
Python; this suite runs in Cloud Build).
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import datetime, timezone

import pytest

run_task = pytest.importorskip("app.research.run_task")
stream_session = pytest.importorskip("app.db.stream_session")
identity_mod = pytest.importorskip("app.auth.identity")
research_runs_model = pytest.importorskip("app.db.models.research_runs")

Identity = identity_mod.Identity
ResearchRun = research_runs_model.ResearchRun

# The `integration` marker means "RUNS IN THE COMMITTED MERGE GATE" in THIS repo —
# the only committed backend gate is the repo-root `cloudbuild.test.yaml`, which runs
# `pytest tests -m integration`. It is NOT a claim that this file touches a database
# (it touches none). Without the marker the file would be collected and then
# DESELECTED, which is the "green because it ran nothing" failure mode this phase
# exists to avoid. Same reasoning as `test_research_run_task.py`'s marker (15.2-24).
pytestmark = pytest.mark.integration


def _superadmin() -> "Identity":
    """A superadmin identity (space_id is None — the trigger actor)."""
    return Identity(uid="sa-1", email="ops@agenic.be", role="superadmin", space_id=None)


class _StubSession:
    """A no-op stand-in for a SQLAlchemy Session."""

    def execute(self, *args, **kwargs):  # pragma: no cover - unused shape
        return None


def _capture_repo_patch(monkeypatch) -> list:
    """Record the values ``mirror_tick`` PATCHes, without a session or a database.

    Reads the values the REAL ``mirror_tick`` writes rather than trusting a stub was
    called — the discipline ``test_research_run_task.py`` established.
    """
    calls: list = []

    class _Repo:
        def __init__(self, session, identity) -> None:
            pass

        def patch(self, row_id, **values):
            calls.append(dict(values))
            return 1

    @contextlib.contextmanager
    def _fake_tenant_session(identity):
        yield object()

    monkeypatch.setattr(run_task, "ResearchRunRepository", _Repo)
    monkeypatch.setattr(run_task, "tenant_session", _fake_tenant_session)
    return calls


def _capture_patch_run(monkeypatch) -> list:
    """Record every ``_patch_run`` call as ``(research_run_id, values)``.

    Used by the park test INSTEAD of monkeypatching ``finalize_parked``, so the
    assertions read the values the REAL finalizer writes.
    """
    calls: list = []

    def _fake_patch_run(session, research_run_id, *, identity, **values):
        calls.append((str(research_run_id), values))

    monkeypatch.setattr(run_task, "_patch_run", _fake_patch_run)
    return calls


class _FakeRunRow:
    """A minimal stand-in for the mirrored ``research_runs`` ORM row.

    Carries every attribute :func:`read_latest_research_run_dict` reads, so a key
    added to the wire frame without a source column fails here rather than in
    production.
    """

    def __init__(self, **overrides) -> None:
        self.id = uuid.uuid4()
        self.status = "running"
        self.current_stage = "deep_research"
        self.stage_detail = {"deep_research": {"items": []}}
        self.cost_usd_total = None
        self.started_at = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)
        self.completed_at = None
        self.error_message = None
        self.chain_status = None
        self.chain_broken_at = None
        self.bundle_key = None
        self.event_seq = None
        for key, value in overrides.items():
            setattr(self, key, value)


def _install_stream_row(monkeypatch, row) -> None:
    """Make ``read_latest_research_run_dict`` see ``row`` without touching a DB."""

    class _Repo:
        def __init__(self, session, identity) -> None:
            pass

        def latest_for_intake(self, intake_id):
            return row

    @contextlib.contextmanager
    def _fake_tenant_session(identity):
        yield object()

    monkeypatch.setattr(stream_session, "ResearchRunRepository", _Repo)
    monkeypatch.setattr(stream_session, "tenant_session", _fake_tenant_session)


# ---------------------------------------------------------------------------
# (a) the cursor is mirrored
# ---------------------------------------------------------------------------

def test_mirror_tick_patches_the_cursor_when_the_metrics_carry_it(monkeypatch):
    """The engine's ``event_seq`` reaches ``research_runs`` on the tick that reports it.

    WHAT BREAKS WITHOUT THIS: the page holds a connection that never tells it new
    events exist, so the feed the whole phase is built to show stays empty until a
    manual reload.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(),
        uuid.uuid4(),
        "trib-1",
        {"status": "running", "current_stage": "deep_research", "event_seq": 42},
    )

    assert calls, "the mirror write never happened"
    values = calls[-1]
    assert values["event_seq"] == 42, (
        f"the engine's cursor must land on the mirror row, got "
        f"{values.get('event_seq')!r}"
    )


# ---------------------------------------------------------------------------
# (b) the ADDITIVE property
# ---------------------------------------------------------------------------

def test_mirror_tick_leaves_the_cursor_untouched_when_the_metrics_omit_it(monkeypatch):
    """An OLDER engine build sends no cursor and must patch NOTHING.

    Asserted as "the column is not mentioned in the patch" — NOT as "it became
    None". Those are different claims, and only the first one is the additive
    contract: a patch that set the column to NULL would rewind a live page to the
    start of the run every time a rolling deploy put one older revision behind the
    load balancer.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(),
        uuid.uuid4(),
        "trib-1",
        {"status": "running", "current_stage": "deep_research"},
    )

    values = calls[-1]
    assert "event_seq" not in values, (
        f"an absent cursor must leave the column UNCHANGED, not NULLed: {values}"
    )
    # The fields the tick already mirrored are untouched by this plan.
    assert values["status"] == "running"
    assert values["current_stage"] == "deep_research"


# ---------------------------------------------------------------------------
# (c) a malformed cursor is skipped and never raises
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad",
    ["not-a-number", {"seq": 7}, ["7"], True, False, -5, None],
    ids=["string", "dict", "list", "true", "false", "negative", "null"],
)
def test_a_malformed_cursor_is_ignored_and_never_raises(monkeypatch, bad):
    """Remote JSON is UNTRUSTED INPUT (ASVS V5 / T-15.3-50) — a bad value patches nothing.

    No ``pytest.raises`` here on purpose: nothing may escape. A raise inside the poll
    driver routes to ``on_error`` and finalizes the row ``failed`` — losing a paid run
    over an observability field would be an absurd trade.

    ``True``/``False`` are in the list because ``int(True)`` is ``1``: a bool that
    slipped through would rewind a live feed to its second row. ``-5`` is in the list
    because there is no negative position.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(), uuid.uuid4(), "trib-1",
        {"status": "running", "event_seq": bad},
    )

    values = calls[-1]
    assert "event_seq" not in values, (
        f"a malformed cursor must leave the column untouched rather than guessed: "
        f"{values}"
    )
    assert values["status"] == "running", "the rest of the tick must still mirror"


def test_a_float_cursor_truncates_toward_the_safe_direction(monkeypatch):
    """A float is accepted and truncated DOWN — the direction that cannot lose events.

    An under-stated cursor makes the page re-fetch rows it already holds (a wasted
    request). An over-stated one would make it skip rows it never saw (a silent hole
    in the audit-facing feed). Only one of those is acceptable.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(), uuid.uuid4(), "trib-1",
        {"status": "running", "event_seq": 42.9},
    )

    assert calls[-1]["event_seq"] == 42


# ---------------------------------------------------------------------------
# (d) parked advances the cursor AND keeps completed_at NULL
# ---------------------------------------------------------------------------

def test_finalize_parked_carries_the_cursor_but_still_no_completion_time(monkeypatch):
    """A park advances the FEED and does not end the RUN — both halves, one test.

    These two assertions live together deliberately. ``completed_at`` stays NULL
    (15.2-19 / 15.2-24: a parked run is paused, not finished, and stamping a
    completion time would make the card render a duration for a run still waiting on
    a superadmin click). ``event_seq`` DOES advance (15.3-06: a cursor is not a
    completion claim, and the feed a parked run produced is exactly what the operator
    reads before deciding whether to resume).

    Splitting them into two tests would let a future edit "harmonise" the cursor with
    ``completed_at`` — freezing the feed one tick early and hiding the rows that
    explain the park — while the other test stayed green.
    """
    written = _capture_patch_run(monkeypatch)

    run_task.finalize_parked(
        _StubSession(),
        uuid.uuid4(),
        {
            "status": "parked",
            "current_stage": "deep_research",
            "event_seq": 137,
            # Present in the payload ON PURPOSE: the proof is that the finalizer
            # ignores the timestamp while honouring the cursor — not that the engine
            # happened to send only one of them.
            "completed_at": "2026-07-27T09:07:00Z",
        },
        "[park#1] Anthropic monthly cap reached",
        identity=_superadmin(),
    )

    _, values = written[-1]
    assert values["event_seq"] == 137, (
        "a parked run MUST keep advancing its feed cursor — the operator reads that "
        f"feed to decide whether to resume. Got {values.get('event_seq')!r}"
    )
    assert values["completed_at"] is None, (
        "a parked run must keep completed_at NULL even when the engine sent one, "
        f"got {values.get('completed_at')!r}"
    )
    assert values["status"] == "parked"


def test_the_other_two_finalizers_carry_the_cursor_too(monkeypatch):
    """``completed`` and ``failed`` also land the final cursor.

    A failed run's feed is the EVIDENCE of what went wrong, and today's failure card
    drops the feed entirely — the state that most needs the events is the one that
    discards them. The terminal frame must therefore carry a cursor that reaches the
    end of the feed.
    """
    written = _capture_patch_run(monkeypatch)

    run_task.finalize_completed(
        _StubSession(),
        uuid.uuid4(),
        {"status": "completed", "event_seq": 900},
        {"markdown": "# report"},
        identity=_superadmin(),
    )
    assert written[-1][1]["event_seq"] == 900

    run_task.finalize_failed(
        _StubSession(),
        uuid.uuid4(),
        {"status": "failed", "event_seq": 901},
        "boom",
        identity=_superadmin(),
    )
    assert written[-1][1]["event_seq"] == 901

    # The ``on_error`` route passes metrics=None and must not mention the column.
    run_task.finalize_failed(
        _StubSession(), uuid.uuid4(), None, "crashed", identity=_superadmin()
    )
    assert "event_seq" not in written[-1][1], (
        "the on_error route has no metrics at all and must patch no cursor"
    )


# ---------------------------------------------------------------------------
# (e) the cursor rides the existing SSE frame
# ---------------------------------------------------------------------------

def test_the_sse_frame_carries_the_cursor_and_it_round_trips(monkeypatch):
    """``read_latest_research_run_dict`` emits ``event_seq`` with the row's value."""
    _install_stream_row(monkeypatch, _FakeRunRow(event_seq=57))

    view = stream_session.read_latest_research_run_dict(_superadmin(), uuid.uuid4())

    assert view is not None
    assert "event_seq" in view, f"the frame must carry the cursor: {sorted(view)}"
    assert view["event_seq"] == 57


def test_a_run_with_no_events_reports_a_null_cursor_not_zero(monkeypatch):
    """NULL means "no events yet"; 0 would claim a stream positioned at its start.

    The distinction is what stops the page issuing a delta fetch for a run that has
    no feed at all (migration 0013's stated reason for no ``server_default``).
    """
    _install_stream_row(monkeypatch, _FakeRunRow(event_seq=None))

    view = stream_session.read_latest_research_run_dict(_superadmin(), uuid.uuid4())

    assert view["event_seq"] is None


def test_the_frame_carries_no_event_payload(monkeypatch):
    """The frame is a CURSOR, never a list of events (D-05).

    Two failures this prevents: the frame is re-sent IN FULL on every change, so a
    thousand-row history would ride the wire on every tick; and a second copy of the
    run's story on the authoritative connection is the first step toward two sources
    of truth for "is this run over".
    """
    _install_stream_row(monkeypatch, _FakeRunRow(event_seq=57))

    view = stream_session.read_latest_research_run_dict(_superadmin(), uuid.uuid4())

    list_valued = [k for k, v in view.items() if isinstance(v, list)]
    assert not list_valued, (
        f"the SSE frame must carry no list-of-events key; found {list_valued}"
    )
    assert "events" not in view and "run_events" not in view, (
        f"events are PULLED from the 15.3-07 proxy, never pushed on this frame: "
        f"{sorted(view)}"
    )


# ---------------------------------------------------------------------------
# (f) a cursor advance is BY ITSELF a new frame
# ---------------------------------------------------------------------------

def test_two_frames_differing_only_in_the_cursor_are_different_dicts(monkeypatch):
    """The property the WHOLE delta design rests on.

    ``stream_research_run`` emits on ``view != last_sent`` — a WHOLE-DICT comparison.
    If a moved cursor did not change the dict, the page would never be told that new
    events exist and the feed would only ever update when something ELSE (cost, stage
    detail, status) happened to change at the same time.

    Asserted as DICT inequality, not field inequality: comparing the two numbers
    would prove something about this test, not about the frame the handler compares.
    """
    row = _FakeRunRow(event_seq=10)
    _install_stream_row(monkeypatch, row)
    intake_id = uuid.uuid4()

    first = stream_session.read_latest_research_run_dict(_superadmin(), intake_id)

    # ONLY the cursor moves — same run id, same status, same stage, same cost.
    row.event_seq = 11
    second = stream_session.read_latest_research_run_dict(_superadmin(), intake_id)

    assert first != second, (
        "a cursor advance must produce a DIFFERENT frame — this is exactly the "
        f"comparison the SSE handler makes: {first} vs {second}"
    )
    # And nothing else moved, so the cursor is genuinely the only difference.
    differing = {k for k in first if first[k] != second[k]}
    assert differing == {"event_seq"}, differing


# ---------------------------------------------------------------------------
# Structural gates (folded in from the plan's `<automated>` checks — see SUMMARY:
# this machine has no local Python, so the checks live where they RUN.)
# ---------------------------------------------------------------------------

def test_the_orm_knows_about_the_new_column_and_kept_the_old_ones():
    """Task 1's ``<automated>`` check, folded into the gate so it runs every build.

    The additive columns from 0012/0011 and 15.2-24 are asserted alongside the new
    one: a migration that dropped a sibling while adding this would otherwise pass.
    """
    columns = ResearchRun.__table__.c
    assert "event_seq" in columns
    for pre_existing in (
        "chain_status", "chain_broken_at", "bundle_key", "started_at", "completed_at",
    ):
        assert pre_existing in columns, f"0013 must be purely additive; lost {pre_existing}"


def test_the_new_column_is_nullable_with_no_server_default():
    """NULL is the honest value for a run with no events; 0 would be a lie."""
    column = ResearchRun.__table__.c["event_seq"]
    assert column.nullable is True
    assert column.server_default is None


# ---------------------------------------------------------------------------
# Live-schema proof — the migration ACTUALLY APPLIED.
#
# The `engine` fixture runs `alembic upgrade head` as the non-superuser owner. The
# gate's own log does NOT surface alembic's `Running upgrade 0012 -> 0013` line, so
# without these two tests the only evidence 0013 applied would be "the build did not
# crash" — which is precisely the exit(0)-is-never-proof failure this project has
# been bitten by. These assert the column and the head revision from the LIVE
# database instead.
# ---------------------------------------------------------------------------

def test_the_cursor_column_exists_live_and_is_a_nullable_bigint(engine):
    """0013 applied: ``nestor.research_runs.event_seq`` is BIGINT NULL, no default."""
    from sqlalchemy import text

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT data_type, is_nullable, column_default "
                "FROM information_schema.columns "
                "WHERE table_schema = 'nestor' AND table_name = 'research_runs' "
                "AND column_name = 'event_seq'"
            )
        ).first()

    assert row is not None, (
        "nestor.research_runs.event_seq is MISSING from the live schema — migration "
        "0013 did not apply"
    )
    data_type, is_nullable, column_default = row
    assert data_type == "bigint", (
        f"the mirror must match tribunal 0015's run_event.seq (bigint), got {data_type}"
    )
    assert is_nullable == "YES"
    assert column_default is None, (
        f"a default would claim a feed positioned at its start, got {column_default!r}"
    )


def test_the_intake_alembic_head_is_0014(engine):
    """The INTAKE line's version table is at 0014 after ``alembic upgrade head``.

    This is the direct statement the build log does not print. It also pins the line:
    the tribunal line's own head lives in a DIFFERENT version table
    (``tribunal.tribunal_alembic_version``), numbers itself independently, and is
    untouched by the intake line's migrations.

    Was ``0013`` until plan 23.1-12 added 0014 (the single-running-skill-run partial
    unique index). The literal is a DELIBERATE hardcode, not an oversight: it is what
    turns "a migration landed" into a red test, so an unintended or half-applied head
    cannot pass silently. Every revision on this line therefore updates this one literal
    and this function's name — plan 23.1-13 does it again for 0015.
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        heads = {
            r[0]
            for r in conn.execute(
                text("SELECT version_num FROM public.alembic_version")
            ).all()
        }

    assert heads == {"0014"}, (
        f"the intake alembic line must be at exactly 0014, found {heads}"
    )
