"""The in-process reconcile timer in ``app.main.lifespan`` (23.3-06 / COST-01 / DEF-23.2-03).

WHAT IS UNDER TEST. Plan 23.3-05 built :func:`app.research.reconcile.sweep_once` as a plain
synchronous callable precisely so its TRIGGER could be chosen separately. Cloud Scheduler is
not enabled on this project (enabling it is an operator/IAM action — 23.3-CONTEXT.md § 8), so
the trigger is an in-process periodic task started by ``lifespan``. These six tests pin the
four properties that make that trigger trustworthy, each of which has a failure mode that is
SILENT in production:

- **test 1 — it ticks with ZERO HTTP requests.** This is the whole reason a background task
  exists rather than a request-driven hook: an orphaned run has, by definition, nobody polling
  it. If the timer only advanced while traffic flowed, the mechanism would be inert exactly
  when it is needed.
- **test 2 — it does not block the event loop.** ``sweep_once`` is blocking pg8000 + blocking
  httpx (``_TIMEOUT_S = 30.0``). ``await sweep_once()`` would stall EVERY request on this
  instance for up to 30 s per swept run. This test is the one that catches that mistake: it
  passes against a direct-await implementation's test 1 and fails here. It is deliberately
  written to be non-vacuous — it asserts both that ``/healthz`` answered fast AND that the
  stub was still inside its blocking sleep when the answer arrived.
- **test 3 — a raising sweep does not end the loop.** A dead timer is invisible: nothing polls
  it and nothing alerts on it, which makes it strictly worse than a noisy failure.
- **test 4 — a broken reconciler does not break startup.** Liveness must never depend on the
  self-healing extra (T-02-04, the same posture as the existing ``sweep_orphaned_skill_runs``
  guard right above it).
- **test 5 — the kill switch works AND says so.** ``NESTOR_RECONCILE_INTERVAL_S=0`` is the
  only way an operator can stop the sweep without a code deploy. A silent no-op is how an
  operator ends up believing a sweep is running when it is not, so the WARNING is asserted
  too, not just the absence of calls.
- **test 6 — clean shutdown.** The task is cancelled and awaited BEFORE the engine pool is
  disposed, so no "Task was destroyed but it is pending" and no write against a disposed pool.

TEST-HARNESS NOTES.

- Lifespan is entered with ``TestClient(app)`` AS A CONTEXT MANAGER — Starlette runs startup
  on ``__enter__`` and shutdown on ``__exit__``. No new ASGI test library is introduced
  (``asgi_lifespan`` / ``httpx.ASGITransport`` are NOT dependencies of this repo).
- ``app.main.sweep_once`` is the patch target, NOT
  ``app.research.reconcile.sweep_once``: ``main`` binds the name at import, so patching the
  source module would not take.
- Log assertions use a private handler attached to the logger and removed in a ``finally``,
  NOT ``caplog``. ``caplog``'s process-wide propagate/level mutation is a registered
  cross-file pollution source in this suite (DEF-23.2-14 / DEF-23.3-02) and this file must not
  add to it.
- ``init_firebase`` and ``sweep_orphaned_skill_runs`` are neutralised for every test here:
  without that, entering lifespan attempts real ADC + a real Cloud SQL connect (which fails
  with ``KeyError: 'INSTANCE_CONNECTION_NAME'`` on a dev box, is caught by the existing guard,
  and prints a full traceback that buries this file's own signal).
"""

from __future__ import annotations

import contextlib
import gc
import logging
import threading
import time
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app.main import app

# Collapsed interval used by the ticking tests. Small enough that a test finishes in under a
# second, large enough that the first tick is not racing lifespan startup itself.
FAST_INTERVAL = 0.05

# The blocking duration of test 2's stub. The /healthz answer must land well inside it.
BLOCK_SECONDS = 0.5

# Wall-clock ceiling for a /healthz answer while the sweep is blocking a WORKER THREAD.
# Comfortably below BLOCK_SECONDS so a slow CI box cannot make this flaky, yet far enough
# below it that a loop-blocking implementation (which would take ~BLOCK_SECONDS) cannot pass.
HEALTHZ_BUDGET = 0.25


class _ListHandler(logging.Handler):
    """Collect records instead of emitting them (see the caplog note in the module docstring)."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - trivial
        self.records.append(record)


@contextlib.contextmanager
def _capture(logger_name: str, level: int = logging.WARNING) -> Iterator[_ListHandler]:
    """Attach a private handler to ``logger_name`` and always remove it again."""
    lg = logging.getLogger(logger_name)
    handler = _ListHandler()
    previous_level = lg.level
    lg.addHandler(handler)
    lg.setLevel(level)
    try:
        yield handler
    finally:
        lg.removeHandler(handler)
        lg.setLevel(previous_level)


@pytest.fixture(autouse=True)
def _hermetic_startup(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Neutralise the two unrelated startup side effects, and never leak a timer.

    ``monkeypatch`` restores ``RECONCILE_INTERVAL_SECONDS`` and both patched callables
    automatically, and every test enters lifespan through a ``with`` block so shutdown always
    runs — together that is what stops a fast timer from this file ticking inside another
    module's tests.
    """
    monkeypatch.setattr(main_module, "init_firebase", lambda: None, raising=True)
    monkeypatch.setattr(
        main_module, "sweep_orphaned_skill_runs", lambda *a, **k: 0, raising=True
    )
    yield
    gc.collect()


def _wait_until(predicate, timeout: float = 5.0, poll: float = 0.01) -> bool:
    """Poll ``predicate`` from the MAIN thread until true or ``timeout`` elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(poll)
    return False


def test_the_timer_ticks_with_zero_http_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 1: the sweep runs repeatedly while NO request is ever issued.

    Zero requests is the point. The runs this mechanism recovers are precisely the ones whose
    driver died, so nothing is polling them; a trigger that needed traffic would be inert.
    """
    calls: list[float] = []

    def _stub(*_a: Any, **_k: Any) -> dict[str, int]:
        calls.append(time.monotonic())
        return {"claimed": 0}

    monkeypatch.setattr(main_module, "sweep_once", _stub, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", FAST_INTERVAL, raising=True)

    with TestClient(app):
        # NOTE: not a single c.get(...) in this block, on purpose.
        ticked = _wait_until(lambda: len(calls) >= 2)

    assert ticked, f"sweep_once ran {len(calls)} time(s) in 5s with no request; expected >= 2"


def test_the_sweep_does_not_block_the_event_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 2: /healthz is answered fast WHILE the sweep is blocking its thread.

    This is the test that exists to fail against ``await sweep_once()``. ``sweep_once`` blocks
    (pg8000, httpx) so it MUST be offloaded with ``asyncio.to_thread``; awaited directly it
    would freeze every request on the instance for the length of the call.

    Both halves of the assertion matter. Only checking the elapsed time would go vacuously
    green if the request happened to land after the sweep had already finished, so the test
    also asserts the stub was still inside its sleep when the answer arrived.
    """
    entered = threading.Event()
    exited = threading.Event()

    def _blocking_stub(*_a: Any, **_k: Any) -> dict[str, int]:
        entered.set()
        time.sleep(BLOCK_SECONDS)  # blocks whichever thread runs it
        exited.set()
        return {"claimed": 0}

    monkeypatch.setattr(main_module, "sweep_once", _blocking_stub, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", FAST_INTERVAL, raising=True)

    with TestClient(app) as client:
        assert entered.wait(timeout=5.0), "the sweep never started"
        started = time.monotonic()
        response = client.get("/healthz")
        elapsed = time.monotonic() - started
        still_blocking = not exited.is_set()

    assert response.status_code == 200
    assert still_blocking, (
        "the sweep had already finished when /healthz answered — the timing assertion below "
        "would have been vacuous"
    )
    assert elapsed < HEALTHZ_BUDGET, (
        f"/healthz took {elapsed:.3f}s while the sweep blocked for {BLOCK_SECONDS}s — the "
        "sweep is running ON the event loop instead of via asyncio.to_thread"
    )


def test_a_failing_sweep_does_not_kill_the_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test 3: the loop continues after the sweep raises.

    A ``try/except`` that ``break``s (or no ``try`` at all) passes a happy-path test and fails
    here. The failure it would cause in production is a timer that silently stopped: nothing
    polls the task, so nobody would learn of it until runs went unrecovered.
    """
    calls: list[int] = []

    def _raise_once(*_a: Any, **_k: Any) -> dict[str, int]:
        calls.append(len(calls))
        if len(calls) == 1:
            raise RuntimeError("boom — first sweep fails")
        return {"claimed": 0}

    monkeypatch.setattr(main_module, "sweep_once", _raise_once, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", FAST_INTERVAL, raising=True)

    with _capture("nestor.health") as logs, TestClient(app):
        survived = _wait_until(lambda: len(calls) >= 3)

    assert survived, (
        f"sweep_once ran only {len(calls)} time(s) after raising on the first tick — the "
        "exception ended the loop instead of being swallowed"
    )
    assert any("reconcile" in r.getMessage().lower() for r in logs.records), (
        "the failing sweep was swallowed SILENTLY; it must log a WARNING naming the reconcile "
        "sweep, or the failure is undiagnosable in Cloud Run"
    )


def test_startup_survives_a_reconciler_that_cannot_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 4: the app still starts, and /healthz still answers 200, when starting the
    reconciler itself raises.

    DEVIATION FROM THE PLAN'S WORDING, recorded deliberately: the plan says "with
    ``sweep_once`` patched to raise at import/creation time". Patching ``sweep_once`` cannot
    exercise this path — it raises inside the loop (that is test 3), not at task creation. The
    property actually worth pinning is that the ``lifespan`` guard around task CREATION holds,
    so ``_reconcile_loop`` itself is made to raise synchronously when called. Same threat
    (T-23.3-32: a broken reconciler must not block startup or readiness), correct mechanism.
    """

    def _explode() -> None:
        raise RuntimeError("cannot build the reconcile coroutine")

    monkeypatch.setattr(main_module, "_reconcile_loop", _explode, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", FAST_INTERVAL, raising=True)

    with _capture("nestor.health") as logs, TestClient(app) as client:
        response = client.get("/healthz")

    assert response.status_code == 200, "startup must not fail because the reconciler could not"
    assert response.json() == {"status": "ok"}
    assert any("reconcile" in r.getMessage().lower() for r in logs.records), (
        "a reconciler that could not start must leave a WARNING behind"
    )
    assert getattr(app.state, "reconcile_task", None) is None


def test_the_kill_switch_disables_the_sweep_and_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 5: at interval 0 the sweep NEVER runs, and startup logs a WARNING saying it is off.

    BOTH halves are asserted. ``NESTOR_RECONCILE_INTERVAL_S=0`` is the only way to stop this
    background loop without a code deploy, and a kill switch that engages silently is how an
    operator comes to believe a sweep is running when it is not.
    """
    calls: list[int] = []

    def _stub(*_a: Any, **_k: Any) -> dict[str, int]:
        calls.append(1)
        return {"claimed": 0}

    monkeypatch.setattr(main_module, "sweep_once", _stub, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", 0.0, raising=True)

    with _capture("nestor.health") as logs, TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        time.sleep(0.3)  # generous: FAST_INTERVAL would have ticked ~6 times by now

    assert calls == [], f"the sweep ran {len(calls)} time(s) with the kill switch engaged"
    assert getattr(app.state, "reconcile_task", None) is None
    messages = [r.getMessage().lower() for r in logs.records]
    assert any("reconcile" in m and "disabl" in m for m in messages), (
        "the disabled sweep must announce itself at WARNING; got: " + repr(messages)
    )


def test_the_task_is_cancelled_and_awaited_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test 6: after lifespan exits the task is finished, with no pending-task warning.

    ``asyncio`` logs "Task was destroyed but it is pending" at ERROR from ``__del__`` when a
    task is dropped without being awaited, so the assertion watches the ``asyncio`` logger as
    well as the task's own state. The cancel must also happen BEFORE the engine dispose, or a
    sweep mid-write would surface as a confusing shutdown error.
    """

    def _stub(*_a: Any, **_k: Any) -> dict[str, int]:
        return {"claimed": 0}

    monkeypatch.setattr(main_module, "sweep_once", _stub, raising=True)
    monkeypatch.setattr(main_module, "RECONCILE_INTERVAL_SECONDS", FAST_INTERVAL, raising=True)

    with _capture("asyncio", logging.DEBUG) as asyncio_logs, TestClient(app) as client:
        assert client.get("/healthz").status_code == 200
        task = app.state.reconcile_task
        assert task is not None, "lifespan did not record the reconcile task"
        assert not task.done(), "the task ended while the app was still up"

    gc.collect()

    assert task.done(), "the reconcile task was still pending after lifespan exited"
    assert task.cancelled(), "the task finished for some reason other than being cancelled"
    destroyed = [
        r.getMessage() for r in asyncio_logs.records if "destroyed but it is pending" in r.getMessage()
    ]
    assert destroyed == [], f"asyncio complained about a dropped task: {destroyed}"
