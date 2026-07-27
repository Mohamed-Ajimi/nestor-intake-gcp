"""Poll-driver proofs (ENGINE-07 / RUN-02) — pool-safety, terminal mail, on_error.

The driver kicks a Tribunal run, polls it to a terminal state WITHOUT holding a
pooled DB connection across the ~19-min run, mirrors each tick into
``research_runs``, mails the triggering superadmin on the terminal, and finalizes
the row to EXACTLY ``failed`` on any exception (D-04/D-11). This suite pins those
four contracts.

What this pins:

- ``engine.pool.checkedout() == 0`` across the CALL phase (the poll loop) —
  T-16-06 pool starvation cannot happen (routed through
  ``run_with_session_release``).
- The completion mail's ``to`` is the acting superadmin's email (D-10).
- ``on_error`` leaves the ``research_runs`` row at exactly ``status == "failed"``.
- The loop stops on the RESEARCH terminal set ``{completed, failed, cancelled}``
  (never the skill-run ``succeeded``).

Test design (no DB): the driver's structural functions (``read_fn`` / the
``mirror_tick`` / finalize writers) are exercised by monkeypatching the module's
``run_with_session_release`` to a fake that runs read/call/write against a stub
session and records pool observations. The Tribunal seam is the ``fake_tribunal_client``
fixture; the mail seam is ``fake_resend``. ``app.research.run_task`` is imported
LAZILY (``importorskip``) so this collects on a box without the app installed
(dev machine has no Python; the suite runs in Cloud Build).
"""

from __future__ import annotations

import contextlib
import types
import uuid
from datetime import datetime, timezone

import pytest

run_task = pytest.importorskip("app.research.run_task")
identity_mod = pytest.importorskip("app.auth.identity")

Identity = identity_mod.Identity

# WHAT THIS MARKER MEANS IN *THIS* REPOSITORY, said plainly because the name lies.
#
# The only committed backend gate is the repo-root `cloudbuild.test.yaml`, and it
# runs `pytest tests -m integration`. So in this repo the `integration` marker is
# the "RUNS IN THE COMMITTED MERGE GATE" flag — it is NOT a claim that the file
# touches a database. This file touches none: every seam is monkeypatched and the
# session is a stub. Without the marker it was collected and then DESELECTED
# (measured: `155 deselected`), which means the poll driver's contracts — pool
# safety, terminal mail, park idempotency, on_error — have been running in NO
# committed gate at all (deferred item D19-2).
#
# Plan 15.2-24 adds the marker as a DELIBERATE, NARROW fix for THIS file, because
# this plan adds behaviour to `run_task.py` and shipping an ungated proof of it
# would be the "green because it ran nothing" failure this phase spent six waves
# removing. D19-2's broader question — whether the non-integration unit suite gets
# a committed gate of its own — is still OPEN and is NOT closed by this plan.
pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Collapse the inter-tick sleep so the poll loop runs instantly in tests."""
    monkeypatch.setattr(run_task, "POLL_SECONDS", 0.0)


@pytest.fixture
def warning_sink(monkeypatch):
    """Every WARNING this module logs, captured by REPLACING its logger.

    NOT `caplog`, and NOT a handler either — both were tried and both captured
    NOTHING for records `app.research.run_task` emits under this suite:

      * `caplog.text` came back as the empty string (the pre-existing
        `test_parked_mail_not_resent_for_same_seq` fails on exactly that, and had
        been failing unnoticed for as long as the file was DESELECTED by the only
        committed gate — plan 15.2-24 added `pytestmark` and it surfaced);
      * a `logging.Handler` attached directly to `run_task.log`, with the logger's
        level explicitly lowered to WARNING, captured nothing either.

    Two independent capture routes going silent is consistent with logging being
    globally suppressed somewhere in this suite's dependency set. The cause is
    UNCONFIRMED and is filed as D24-1 in `deferred-items.md` — it matters beyond
    this file, because the next person to reach for `caplog` in `backend/tests`
    will write an assertion that cannot fail.

    Replacing the logger object sidesteps the framework entirely and asserts the
    thing that actually matters: that this module CALLED `log.warning` with the
    right content. A WARNING that is asserted on is a WARNING an operator can rely
    on — this driver runs headless, and silence here has already cost a full UAT
    day (16-05).
    """
    seen: list[str] = []

    class _RecordingLog:
        """Duck-typed stand-in for `logging.Logger`; records the rendered message."""

        def _record(self, bucket: list, msg, args) -> None:
            try:
                bucket.append(str(msg) % args if args else str(msg))
            except Exception:  # noqa: BLE001 - a bad format string is the test's bug
                bucket.append(str(msg))

        def warning(self, msg, *args, **kwargs) -> None:
            self._record(seen, msg, args)

        def error(self, msg, *args, **kwargs) -> None:
            self._record(seen, msg, args)

        def exception(self, msg, *args, **kwargs) -> None:
            self._record(seen, msg, args)

        def info(self, msg, *args, **kwargs) -> None:
            pass

        def debug(self, msg, *args, **kwargs) -> None:
            pass

    monkeypatch.setattr(run_task, "log", _RecordingLog())
    return seen


def _superadmin() -> "Identity":
    """A superadmin identity (space_id is None — cross-tenant, the trigger actor)."""
    return Identity(
        uid="sa-1", email="ops@agenic.be", role="superadmin", space_id=None
    )


class _StubSession:
    """A no-op stand-in for a SQLAlchemy Session (records patch calls)."""

    def __init__(self, sink: list) -> None:
        self._sink = sink

    def execute(self, *args, **kwargs):  # pragma: no cover - unused shape
        return None


class _FakeEngine:
    """Exposes a ``.pool.checkedout()`` the driver's pool assertion can read."""

    class _Pool:
        def checkedout(self) -> int:
            return 0

    pool = _Pool()


def _patch_release(monkeypatch, *, pool_observed: list, patches: list, error=None):
    """Replace run_with_session_release with a fake that drives read->call->write.

    Mirrors the real contract: read_fn(session) -> dto; call_fn(dto) -> result
    (pool observed here); write_fn(session, dto, result). On any exception routes
    to on_error(session, dto, exc). Uses a stub session so no DB is touched.
    """

    def _fake_release(identity, read_fn, call_fn, write_fn, *, on_error=None):
        session = _StubSession(patches)
        dto = None
        try:
            dto = read_fn(session)
            result = call_fn(dto)
            return write_fn(session, dto, result)
        except Exception as exc:  # noqa: BLE001
            if on_error is None:
                raise
            return on_error(_StubSession(patches), dto, exc)

    monkeypatch.setattr(run_task, "run_with_session_release", _fake_release)


def _install_context(monkeypatch):
    """Make read_fn return a plain trigger context without touching the DB/settings."""
    ctx = {
        "space_id": str(uuid.uuid4()),
        "acting_user_id": "sa-1",
        "acting_email": "ops@agenic.be",
        # intake_id is load-bearing for the Phase-17 completion path — it is one of
        # the two space-scoped segments of the server-authored bundle object key.
        "intake_id": str(uuid.uuid4()),
        "project_title": "dit intake",
        "service_url": "https://tribunal.example",
        "app_base_url": "https://app.example",
        "attempt": 1,
    }
    monkeypatch.setattr(
        run_task, "load_trigger_context", lambda session, identity, intake_id: dict(ctx)
    )
    return ctx


def _capture_mirror(monkeypatch) -> list:
    """Record every mirror_tick call's status without opening a session."""
    ticks: list = []

    def _fake_mirror(identity, research_run_id, tribunal_run_id, metrics):
        ticks.append(metrics.get("status"))

    monkeypatch.setattr(run_task, "mirror_tick", _fake_mirror)
    return ticks


def _capture_finalize(monkeypatch) -> dict:
    """Record the finalize_* writer calls (status + Phase-17 chain/bundle values).

    ``finalize_completed`` grew Phase-17 keyword args (chain_status /
    chain_broken_at / bundle_key) — the fake accepts them and records the last
    completed patch so the verified/broken assertions can read the persisted
    lock-state without a DB.
    """
    sink: dict = {"final": [], "completed_kwargs": None}

    def _fake_completed(
        session,
        research_run_id,
        metrics,
        report,
        *,
        chain_status=None,
        chain_broken_at=None,
        bundle_key=None,
    ):
        sink["final"].append(("completed", report.get("markdown")))
        sink["completed_kwargs"] = {
            "chain_status": chain_status,
            "chain_broken_at": chain_broken_at,
            "bundle_key": bundle_key,
        }

    def _fake_failed(session, research_run_id, metrics, error_message=None):
        sink["final"].append(("failed", error_message))

    monkeypatch.setattr(run_task, "finalize_completed", _fake_completed)
    monkeypatch.setattr(run_task, "finalize_failed", _fake_failed)
    return sink


def _capture_patch_run(monkeypatch) -> list:
    """Record every ``_patch_run`` call as ``(research_run_id, values)``.

    Used by the park tests INSTEAD of monkeypatching ``finalize_parked``, so the
    assertions read the values the REAL finalizer writes (status / error_message /
    completed_at) rather than trusting that a stub was called. Stage 7 swallows
    persistence errors by design, so "no exception" proves nothing — this proves the
    write actually happened with the right values.
    """
    calls: list = []

    def _fake_patch_run(session, research_run_id, **values):
        calls.append((str(research_run_id), values))

    monkeypatch.setattr(run_task, "_patch_run", _fake_patch_run)
    return calls


class _PriorRow:
    """A minimal stand-in for the mirrored ``research_runs`` row read before mailing."""

    def __init__(self, status=None, error_message=None) -> None:
        self.status = status
        self.error_message = error_message


def _patch_run_repo(monkeypatch, prior) -> None:
    """Make the park branch's prior-row read return ``prior`` without a DB."""

    class _FakeRepo:
        def __init__(self, session, identity) -> None:
            pass

        def get(self, research_run_id):
            return prior

    monkeypatch.setattr(run_task, "ResearchRunRepository", _FakeRepo)


def _park_script(seq=1, reason="Anthropic monthly cap reached", stage="deep_research"):
    """A two-tick metrics script whose terminal is a park carrying a descriptor."""
    park = {}
    if seq is not None:
        park["seq"] = seq
    if reason is not None:
        park["reason"] = reason
    park["stage"] = stage
    park["signature"] = "abc"
    return [
        {"status": "running", "current_stage": "delegation"},
        {"status": "parked", "current_stage": stage, "park": park},
    ]


def test_poll_driver_releases_pool(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """engine.pool.checkedout() == 0 during the CALL phase (T-16-06 pool safety)."""
    pool_observed: list = []
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    monkeypatch.setattr(run_task, "get_engine_for_pool_check", lambda: _FakeEngine())

    # The real driver observes the pool inside call_fn; capture via a spy on the
    # engine accessor the driver uses. Our fake release runs read->call->write.
    def _fake_release(identity, read_fn, call_fn, write_fn, *, on_error=None):
        session = _StubSession(patches)
        dto = read_fn(session)
        # Observe pool at the boundary the real call_fn runs in.
        pool_observed.append(run_task.get_engine_for_pool_check().pool.checkedout())
        result = call_fn(dto)
        return write_fn(session, dto, result)

    monkeypatch.setattr(run_task, "run_with_session_release", _fake_release)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert pool_observed == [0], (
        f"T-16-06: no connection may be held across the poll loop; "
        f"checkedout() was {pool_observed} (expected [0])."
    )


def test_completion_mail_to_trigger_user(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """On a completed run the completion mail recipient is the acting superadmin (D-10)."""
    patches: list = []
    ctx = _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    # Default fake metrics script ends in "completed".
    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert fake_resend["calls"], "a terminal mail must be sent"
    last = fake_resend["calls"][-1]
    assert last["to"] == [ctx["acting_email"]]


def test_loop_stops_on_completed_terminal(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """The poll loop breaks on the completed terminal and finalizes completed."""
    patches: list = []
    _install_context(monkeypatch)
    ticks = _capture_mirror(monkeypatch)
    sink = _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    # The default script is [running, completed]; the loop mirrors both then stops.
    assert ticks[-1] == "completed"
    assert sink["final"] == [("completed", "fake report")]


def test_failed_terminal_sends_failure_mail(
    monkeypatch, fake_tribunal_client, fake_resend
):
    """A failed terminal finalizes failed and sends the failure-variant mail."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    sink = _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    # Drive the failure terminal.
    fake_tribunal_client["metrics_script"] = [
        {"status": "running"},
        {"status": "failed"},
    ]

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert sink["final"][-1][0] == "failed"
    assert fake_resend["calls"], "a failure mail must be sent"


def test_on_error_finalizes_row_failed(monkeypatch, fake_tribunal_client, fake_resend):
    """Any exception routes through on_error -> the row is finalized to exactly failed."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    sink = _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    # Make create_run raise so the CALL phase throws -> on_error path.
    def _boom(*args, **kwargs):
        raise RuntimeError("tribunal exploded")

    monkeypatch.setattr(
        run_task.tribunal_client, "create_run", _boom, raising=False
    )

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    # on_error must have finalized the row to failed.
    assert sink["final"], "on_error must finalize the row"
    assert sink["final"][-1][0] == "failed"


def test_idempotency_key_is_uuid5_of_intake_and_research_run_id(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """create_run's idempotency_key is uuid5(intake_id, research_run_id) (D-04 / 721086d).

    The key is keyed on the MIRROR ROW id, NOT the attempt number (live finding
    2026-07-21, commit 721086d): an attempt-number key survives row cleanup, so a
    replayed attempt idempotently returns a DEAD engine run from a previous cycle
    (the burned-key insta-fail loop). This is a MUST-NOT-REGRESS invariant.
    """
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    intake_id = uuid.uuid4()
    research_run_id = uuid.uuid4()
    run_task.run_poll_driver(
        _superadmin(), intake_id, research_run_id, "brief text", 2
    )

    expected = str(uuid.uuid5(intake_id, str(research_run_id)))
    assert fake_tribunal_client["create_run"], "create_run must be called"
    assert fake_tribunal_client["create_run"][0]["idempotency_key"] == expected


# ===========================================================================
# Phase 17 (RUN-03) — completion-path audit-chain gate + bundle materialization.
# ===========================================================================


def test_verified_path_builds_and_uploads_bundle_once(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A completed + verified run builds the zip and uploads it to GCS exactly once."""
    patches: list = []
    ctx = _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    sink = _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    # Default verify_verdict is {ok: True} (verified).
    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    # The D-06 gate + the D-01-scrubbed bundle fetch both ran.
    assert fake_tribunal_client["verify_chain_calls"] == 1
    assert fake_tribunal_client["get_research_bundle_calls"] == 1

    # Exactly one upload, under the space-scoped "artifacts" key, ending .zip.
    uploads = fake_gcs["uploads"]
    assert len(uploads) == 1, uploads
    key = uploads[0]["key"]
    assert key.startswith(f"{ctx['space_id']}/{ctx['intake_id']}/artifacts/")
    assert key.endswith(".zip")
    assert uploads[0]["content_type"] == "application/zip"
    assert isinstance(uploads[0]["data"], (bytes, bytearray))

    # The row was patched verified with the bundle_key set.
    kw = sink["completed_kwargs"]
    assert kw["chain_status"] == "verified"
    assert kw["chain_broken_at"] is None
    assert kw["bundle_key"] == key


def test_broken_chain_records_locked_no_upload(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A completed + broken-chain run records complete-but-locked with NO bundle (D-06)."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    sink = _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    # Drive the broken verdict BEFORE the poll reaches the completed terminal.
    fake_tribunal_client["verify_verdict"] = {"ok": False, "broken_at": 3}

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    # The gate ran, but NOTHING was built or uploaded (complete-but-locked).
    assert fake_tribunal_client["verify_chain_calls"] == 1
    assert fake_gcs["uploads"] == [], "a broken chain must NOT write a bundle"

    # Status is still the completed terminal; chain is recorded broken + broken_at.
    assert sink["final"][-1][0] == "completed"
    kw = sink["completed_kwargs"]
    assert kw["chain_status"] == "broken"
    assert kw["chain_broken_at"] == 3
    assert kw["bundle_key"] is None


def test_pool_released_across_build_and_upload(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """engine.pool.checkedout() == 0 across the verify + fetch + build + upload (T-17-07)."""
    pool_observed: list = []
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    monkeypatch.setattr(run_task, "get_engine_for_pool_check", lambda: _FakeEngine())

    # Observe the pool INSIDE the seam/build/upload window: spy on gcs.upload_object
    # (the last I/O step of the connection-free window) and record checkedout() at
    # the moment it fires — it must be 0 (no tenant_session open yet).
    def _spy_upload(key, data, content_type=None):
        pool_observed.append(run_task.get_engine_for_pool_check().pool.checkedout())
        fake_gcs["uploads"].append(
            {"key": key, "data": data, "content_type": content_type}
        )

    monkeypatch.setattr(run_task.gcs, "upload_object", _spy_upload, raising=False)

    # A fake release that also samples the pool at the call boundary.
    def _fake_release(identity, read_fn, call_fn, write_fn, *, on_error=None):
        session = _StubSession(patches)
        dto = read_fn(session)
        result = call_fn(dto)
        return write_fn(session, dto, result)

    monkeypatch.setattr(run_task, "run_with_session_release", _fake_release)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert pool_observed == [0], (
        f"T-17-07: no pooled DB connection may be held across the bundle "
        f"build+upload; checkedout() was {pool_observed} (expected [0])."
    )


def test_completion_mail_sends_on_both_verified_and_broken(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """The normal completion mail sends on BOTH the verified and broken paths (D-07)."""
    # Verified path.
    patches_v: list = []
    ctx_v = _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches_v)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )
    assert fake_resend["calls"], "verified completion must send the completion mail"
    assert fake_resend["calls"][-1]["to"] == [ctx_v["acting_email"]]
    verified_subject = fake_resend["calls"][-1]["subject"]

    # Broken path — same completion mail (no broken-chain variant, D-07).
    fake_tribunal_client["verify_verdict"] = {"ok": False, "broken_at": 2}
    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )
    assert len(fake_resend["calls"]) >= 2, "broken completion must ALSO send a mail"
    # The subject is the SAME completion subject on both paths (unchanged D-07).
    assert fake_resend["calls"][-1]["subject"] == verified_subject


# ===========================================================================
# Plan 15.2-19 (D-17 / F-03) — the PARKED terminal.
#
# Vocabulary discipline, the point of this whole block: a park is NOT a failure,
# NOT a degradation and NOT a distiller fallback.
#   * losing 1-2 of 4 streams   -> completed_degraded (the completion mail)
#   * a D-14 distiller fallback -> normal operation (no special mail at all)
#   * every stream lost, or a hard wall (monthly cap / exhausted credits / 402)
#                               -> parked (THIS block: finalize_parked + park mail)
# A parked run keeps completed_at NULL, builds no bundle, writes no report row, and
# mails the triggering superadmin exactly ONCE per park event (DEC-5's [park#n]).
# ===========================================================================


def test_parked_terminal_finalizes_parked_and_mails(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A parked terminal finalizes parked (completed_at NULL) and mails exactly once."""
    patches: list = []
    ctx = _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    written = _capture_patch_run(monkeypatch)
    _patch_run_repo(monkeypatch, None)  # no prior park marker on the row.
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    fake_tribunal_client["metrics_script"] = _park_script(seq=1)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert written, "the parked terminal must patch the mirror row"
    _, values = written[-1]
    assert values["status"] == "parked", (
        f"a parked run must be mirrored 'parked', never 'failed' — got {values['status']!r}."
    )
    assert values["completed_at"] is None, (
        "completed_at must stay NULL — the run is PAUSED, not finished."
    )
    import re

    assert re.match(r"^\[park#1\] ", values["error_message"]), values["error_message"]
    assert "Anthropic monthly cap reached" in values["error_message"]

    assert len(fake_resend["calls"]) == 1, (
        f"EXACTLY one park mail must be sent, got {len(fake_resend['calls'])}."
    )
    mail = fake_resend["calls"][-1]
    assert mail["to"] == [ctx["acting_email"]], "the park mail goes to the triggering superadmin only."
    assert "Anthropic monthly cap reached" in mail["html"]


def test_parked_mail_not_resent_for_same_seq(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend, warning_sink
):
    """Re-observing the SAME park event sends ZERO mails but still finalizes (DEC-5).

    CAPTURE MECHANISM CHANGED BY PLAN 15.2-24, ASSERTION UNCHANGED. This test used
    `caplog`, and `caplog.text` is EMPTY for this module's records in this suite —
    so the last assertion below could never have passed. It went unnoticed because
    the whole file was DESELECTED by the only committed gate (`pytest tests -m
    integration`, measured: 155 deselected). Adding `pytestmark` put the file in
    the gate and the failure surfaced immediately. The property being asserted is
    exactly the same; only the way the WARNING is captured changed — see the
    `warning_sink` fixture, and D24-1 in `deferred-items.md` for what is still
    unexplained. It is not this plan's to chase.
    """
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    written = _capture_patch_run(monkeypatch)
    # The row already carries this exact park event's marker.
    _patch_run_repo(
        monkeypatch,
        _PriorRow(status="parked", error_message="[park#1] Anthropic monthly cap reached"),
    )
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    fake_tribunal_client["metrics_script"] = _park_script(seq=1)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert len(fake_resend["calls"]) == 0, (
        "a re-observed park event must send ZERO mails (the [park#n] marker is the "
        f"idempotency record); got {len(fake_resend['calls'])}."
    )
    assert written and written[-1][1]["status"] == "parked", (
        "the finalize must still run even when the mail is skipped."
    )
    assert any("[park#1]" in line for line in warning_sink), (
        "a SKIPPED mail must be logged at WARNING naming the marker — never "
        f"silent. WARNINGs seen: {warning_sink}"
    )


def test_parked_seq_two_does_mail(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A genuinely NEW park (seq=2 against a prior [park#1]) mails exactly once."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_patch_run(monkeypatch)
    _patch_run_repo(
        monkeypatch,
        _PriorRow(status="parked", error_message="[park#1] an earlier wall"),
    )
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    fake_tribunal_client["metrics_script"] = _park_script(seq=2, reason="all four streams lost")

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert len(fake_resend["calls"]) == 1, (
        f"a NEW park event must mail exactly once, got {len(fake_resend['calls'])}."
    )
    assert "all four streams lost" in fake_resend["calls"][-1]["html"]


def test_parked_terminal_builds_no_bundle(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A parked terminal never calls build_completion — no bundle, no report row."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_patch_run(monkeypatch)
    _patch_run_repo(monkeypatch, None)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    called: list = []
    monkeypatch.setattr(
        run_task,
        "build_completion",
        lambda *a, **k: called.append(1) or {},
    )

    fake_tribunal_client["metrics_script"] = _park_script(seq=1)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert called == [], "a parked run has no deliverable — build_completion must NOT run."
    assert fake_gcs["uploads"] == [], "a parked run must upload no bundle."


def test_parked_is_in_research_terminal(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """The poll loop EXITS on parked (DEC-3 — terminal for the STREAM, not the RUN)."""
    patches: list = []
    _install_context(monkeypatch)
    ticks = _capture_mirror(monkeypatch)
    _capture_patch_run(monkeypatch)
    _patch_run_repo(monkeypatch, None)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    fake_tribunal_client["metrics_script"] = _park_script(seq=1)

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert ticks[-1] == "parked"
    assert fake_tribunal_client["get_metrics_calls"] == 2, (
        "the driver must stop polling a parked run — a BackgroundTask that keeps "
        "polling an indefinitely-parked run leaks a Cloud Run instance (DEC-3); "
        f"get_metrics was called {fake_tribunal_client['get_metrics_calls']} times."
    )
    assert run_task.is_research_parked("parked")


def test_parked_malformed_descriptor_still_finalizes(
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend
):
    """A malformed park descriptor still finalizes with a readable reason (ASVS V5).

    ``RunMetrics.park`` is REMOTE JSON whose members originate in provider error
    text. A non-int ``seq`` and an absent ``reason`` must not raise inside the
    driver — no ``pytest.raises`` here on purpose: nothing may escape.
    """
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    written = _capture_patch_run(monkeypatch)
    _patch_run_repo(monkeypatch, None)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    fake_tribunal_client["metrics_script"] = [
        {"status": "running"},
        {"status": "parked", "park": {"seq": "not-an-int"}},
    ]

    run_task.run_poll_driver(
        _superadmin(), uuid.uuid4(), uuid.uuid4(), "brief text", 1
    )

    assert written, "a malformed descriptor must still finalize the row"
    _, values = written[-1]
    assert values["status"] == "parked"
    assert values["completed_at"] is None
    assert values["error_message"].startswith("[park#1] "), (
        f"a non-int seq must fall back to 1, got {values['error_message']!r}."
    )
    # The reason falls back to a readable sentence, never an empty tail or "None".
    tail = values["error_message"][len("[park#1] "):].strip()
    assert tail and tail != "None", f"the fallback reason must be readable, got {tail!r}."


# ===========================================================================
# D-L (plan 15.2-24) — the run's own clock reaches the mirror row
#
# `ResearchRunProgress.tsx` does
# `const start = startedAt ? new Date(startedAt).getTime() : Date.now();`
# and `research.ts` has declared `started_at: string | null` since Phase 15 — but
# the backend never sent it. So the field was always null, the elapsed counter
# counted from PAGE LOAD (restarting on every refresh), and the same null made the
# summary card's `fmtDuration(started_at, completed_at)` render an em-dash.
#
# This is a PRODUCER-SIDE fix with three hops, of which only the first two were
# missing: engine run row -> RunMetrics -> research_runs -> (already emitted by
# read_latest_research_run_dict) -> the component. No frontend file changes, and
# no migration: both columns already exist on `research_runs`.
# ===========================================================================

#: A representative pair, as the engine serialises them (pydantic ISO-8601 + Z).
_STARTED_ISO = "2026-07-27T08:09:00Z"
_COMPLETED_ISO = "2026-07-27T09:07:00Z"
_STARTED_DT = datetime(2026, 7, 27, 8, 9, 0, tzinfo=timezone.utc)
_COMPLETED_DT = datetime(2026, 7, 27, 9, 7, 0, tzinfo=timezone.utc)


def _capture_repo_patch(monkeypatch) -> list:
    """Record the values ``mirror_tick`` PATCHes, without a session or a database.

    Reads the values the REAL ``mirror_tick`` writes rather than trusting that a
    stub was called — the same discipline ``_capture_patch_run`` applies to the
    finalize writers.
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


def test_mirror_tick_patches_the_timestamps_when_the_metrics_carry_them(monkeypatch):
    """D-L: ``started_at`` reaches ``research_runs`` on the very first tick.

    WHAT BREAKS WITHOUT THIS: the panel's elapsed counter restarts from zero every
    time the operator refreshes the page during a ~50-minute run, which is exactly
    how long the run they most need to watch takes.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(),
        uuid.uuid4(),
        "trib-1",
        {
            "status": "running",
            "current_stage": "deep_research",
            "started_at": _STARTED_ISO,
        },
    )

    assert calls, "the mirror write never happened"
    values = calls[-1]
    assert values["started_at"] == _STARTED_DT, (
        f"the engine's start time must land on the mirror row parsed, got "
        f"{values.get('started_at')!r}"
    )
    # A running run has not completed — the field is absent, never a guess.
    assert "completed_at" not in values


def test_mirror_tick_patches_nothing_when_the_metrics_omit_them(monkeypatch):
    """An OLDER engine build sends neither field and must patch neither.

    A deploy is never atomic. The existing rule of this function — "a missing field
    is simply not patched" — is what makes the new fields safe to add, and NULLing
    a column because the far side is a version behind would be worse than the
    defect being fixed.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(), uuid.uuid4(), "trib-1",
        {"status": "running", "current_stage": "deep_research"},
    )

    values = calls[-1]
    assert "started_at" not in values, f"an absent field must not be patched: {values}"
    assert "completed_at" not in values
    # The fields the tick ALREADY mirrored are untouched by this plan.
    assert values["status"] == "running"
    assert values["current_stage"] == "deep_research"


def test_finalize_completed_writes_the_engines_completed_at(monkeypatch):
    """The ENGINE's completion time wins over the mirror's own ``func.now()``.

    The engine knows when the run finished; the driver only knows when it got
    round to writing. Both timestamps on the row then come from one clock, so the
    duration the card renders is the duration the run actually took.
    """
    written = _capture_patch_run(monkeypatch)

    run_task.finalize_completed(
        _StubSession([]),
        uuid.uuid4(),
        {
            "status": "completed",
            "current_stage": "done",
            "started_at": _STARTED_ISO,
            "completed_at": _COMPLETED_ISO,
        },
        {"markdown": "# report"},
    )

    _, values = written[-1]
    assert values["completed_at"] == _COMPLETED_DT, (
        f"the engine's completion time must be preferred, got "
        f"{values.get('completed_at')!r}"
    )
    assert values["started_at"] == _STARTED_DT
    assert values["status"] == "completed"


def test_finalize_parked_still_writes_no_completion_time(monkeypatch):
    """A parked run is PAUSED, not finished — ``completed_at`` stays NULL.

    15.2-19's explicit rule, and the one place this plan deliberately does NOT
    prefer the engine's timestamp. Stamping a completion time here would make the
    intake card render a duration for a run that is still waiting on a superadmin
    click, and would make the row indistinguishable from a real terminal in any
    later reporting.
    """
    written = _capture_patch_run(monkeypatch)

    run_task.finalize_parked(
        _StubSession([]),
        uuid.uuid4(),
        {
            "status": "parked",
            "current_stage": "deep_research",
            # Present in the payload ON PURPOSE: the proof is that the finalizer
            # ignores it, not that the engine happened not to send one.
            "completed_at": _COMPLETED_ISO,
            "started_at": _STARTED_ISO,
        },
        "[park#1] Anthropic monthly cap reached",
    )

    _, values = written[-1]
    assert values["completed_at"] is None, (
        f"a parked run must keep completed_at NULL even when the engine sent one, "
        f"got {values.get('completed_at')!r}"
    )
    assert values["status"] == "parked"


@pytest.mark.parametrize(
    "bad",
    [1785159456, "not-a-timestamp", {"iso": "2026-07-27"}, ["2026-07-27"], "", True],
    ids=["int", "garbage-string", "dict", "list", "empty-string", "bool"],
)
def test_a_malformed_timestamp_is_ignored_and_never_raises(monkeypatch, warning_sink, bad):
    """Remote JSON is UNTRUSTED INPUT (ASVS V5) — a bad value patches nothing.

    ``metrics`` crosses the engine seam into a ``BackgroundTask``. A raise here
    routes to ``on_error`` and finalizes the row ``failed``; on a park that would
    also destroy the resume affordance and lose paid, checkpointed work. No
    ``pytest.raises`` here on purpose: nothing may escape.
    """
    calls = _capture_repo_patch(monkeypatch)

    run_task.mirror_tick(
        _superadmin(), uuid.uuid4(), "trib-1",
        {"status": "running", "started_at": bad, "completed_at": bad},
    )

    values = calls[-1]
    assert "started_at" not in values, (
        f"a malformed timestamp must leave the column untouched rather than "
        f"guessed: {values}"
    )
    assert "completed_at" not in values
    assert values["status"] == "running", "the rest of the tick must still mirror"
    assert any("started_at" in line for line in warning_sink), (
        "an ignored value must be VISIBLE at WARNING and must name the field — a "
        f"silent drop looks identical to a field the engine never sent. Seen: "
        f"{warning_sink}"
    )
    # The rejected VALUE is deliberately not in the line: it is remote content of
    # unknown shape and this driver's log is not the place to reproduce it.
    assert not any(str(bad) in line for line in warning_sink if str(bad)), (
        f"the rejected value must not be echoed into the log: {warning_sink}"
    )


def test_a_malformed_completed_at_falls_back_to_the_mirror_clock(monkeypatch):
    """A finalize must still stamp SOMETHING — a terminal row with a NULL
    ``completed_at`` would read as parked."""
    written = _capture_patch_run(monkeypatch)

    run_task.finalize_completed(
        _StubSession([]),
        uuid.uuid4(),
        {"status": "completed", "completed_at": "garbage", "started_at": None},
        {"markdown": "# report"},
    )

    _, values = written[-1]
    assert values["completed_at"] is not None
    assert not isinstance(values["completed_at"], datetime), (
        "a malformed value must fall back to the database clock (func.now()), not "
        f"be coerced into a datetime: {values['completed_at']!r}"
    )
    assert "started_at" not in values, "a None started_at must not NULL the column"
