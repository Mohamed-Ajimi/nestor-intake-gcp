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

import types
import uuid

import pytest

run_task = pytest.importorskip("app.research.run_task")
identity_mod = pytest.importorskip("app.auth.identity")

Identity = identity_mod.Identity


@pytest.fixture(autouse=True)
def _fast_poll(monkeypatch):
    """Collapse the inter-tick sleep so the poll loop runs instantly in tests."""
    monkeypatch.setattr(run_task, "POLL_SECONDS", 0.0)


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
    monkeypatch, fake_tribunal_client, fake_gcs, fake_resend, caplog
):
    """Re-observing the SAME park event sends ZERO mails but still finalizes (DEC-5)."""
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

    with caplog.at_level("WARNING"):
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
    assert "[park#1]" in caplog.text, (
        "a SKIPPED mail must be logged at WARNING naming the marker — never silent."
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
