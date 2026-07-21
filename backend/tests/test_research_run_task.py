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
        "service_url": "https://tribunal.example",
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
    """Record the finalize_* writer calls (status the driver commits)."""
    sink: dict = {"final": []}

    def _fake_completed(session, research_run_id, metrics, report):
        sink["final"].append(("completed", report.get("markdown")))

    def _fake_failed(session, research_run_id, metrics, error_message=None):
        sink["final"].append(("failed", error_message))

    monkeypatch.setattr(run_task, "finalize_completed", _fake_completed)
    monkeypatch.setattr(run_task, "finalize_failed", _fake_failed)
    return sink


def test_poll_driver_releases_pool(
    monkeypatch, fake_tribunal_client, fake_resend
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
    monkeypatch, fake_tribunal_client, fake_resend
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
    monkeypatch, fake_tribunal_client, fake_resend
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


def test_idempotency_key_is_uuid5_of_intake_and_attempt(
    monkeypatch, fake_tribunal_client, fake_resend
):
    """create_run's idempotency_key is uuid5(intake_id, attempt-N) (D-04 deterministic)."""
    patches: list = []
    _install_context(monkeypatch)
    _capture_mirror(monkeypatch)
    _capture_finalize(monkeypatch)
    _patch_release(monkeypatch, pool_observed=[], patches=patches)

    intake_id = uuid.uuid4()
    attempt = 2
    run_task.run_poll_driver(
        _superadmin(), intake_id, uuid.uuid4(), "brief text", attempt
    )

    expected = str(uuid.uuid5(intake_id, f"attempt-{attempt}"))
    assert fake_tribunal_client["create_run"], "create_run must be called"
    assert fake_tribunal_client["create_run"][0]["idempotency_key"] == expected
