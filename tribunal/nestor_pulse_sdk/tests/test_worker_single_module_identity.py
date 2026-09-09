"""
Structural guard for DEF-23.3-01: the worker must run under ONE module identity.

Measured 2026-09-09 on live revision `tribunal-worker-20260908-233038-013724`,
run 9b79e10f: the container entrypoint was

    CMD ["python", "-m", "nestor_pulse_sdk.runs.worker"]

`-m` executes worker.py as `__main__`, which evaluates
`WORKER_ID = f"{hostname}-{pid}-{uuid4().hex[:8]}"`. That copy runs `worker_loop`
and `claim_one`, so CLAIM_SQL stamps `run.worker_id` with ITS id. Dispatch then
reaches `runs/execute.py`'s lazy `from nestor_pulse_sdk.runs.worker import
execute_run`, and Python -- which does not know `__main__` IS that module --
imports worker.py a SECOND time under its canonical name: a second module
object, a second `uuid4()`, a second WORKER_ID. `execute_run` and
`_heartbeat_loop` live in that second copy, so EVERY D-23.1-06 ownership-fenced
write (`WHERE worker_id = :wid`) matched ZERO rows -- heartbeat, both parks, the
success finalize and the failure write. A run could finish perfectly and the
report body was silently discarded.

These tests pin the fix structurally, not by grep:

1. the OLD `-m ...runs.worker` invocation can no longer produce two WORKER_IDs
   (the `__main__` block self-aliases into `sys.modules`);
2. the NEW launcher `...runs.worker_main` loads worker.py exactly once;
3. the Dockerfile CMD names that launcher (allowed as a string assertion only
   because tests 1-2 prove the module it names behaves).

No database is required by any test in this file.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import runpy
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

WORKER_MODULE = "nestor_pulse_sdk.runs.worker"
LAUNCHER_MODULE = "nestor_pulse_sdk.runs.worker_main"

# tribunal/nestor_pulse_sdk/tests/ -> tribunal/
_TRIBUNAL_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _TRIBUNAL_ROOT / "infrastructure" / "cloud-run" / "worker" / "Dockerfile"
_WORKER_PY = _TRIBUNAL_ROOT / "nestor_pulse_sdk" / "runs" / "worker.py"


@contextmanager
def _isolated_import_state():
    """Snapshot/restore sys.modules and sys.argv.

    `runpy.run_module(..., alter_sys=True)` mutates BOTH, and the rest of the
    suite imports the canonical worker module -- leaking a `__main__`-flavoured
    copy would poison it.
    """
    saved_modules = dict(sys.modules)
    saved_argv = list(sys.argv)
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(saved_modules)
        sys.argv[:] = saved_argv


def _purge_worker_modules() -> None:
    for name in list(sys.modules):
        if name == WORKER_MODULE or name.startswith(WORKER_MODULE + "."):
            del sys.modules[name]
        elif name == LAUNCHER_MODULE:
            del sys.modules[name]


@contextmanager
def _neutralised_main(monkeypatch: pytest.MonkeyPatch):
    """Stop `main()` from actually starting the poll loop.

    `main()` does `load_dotenv(...)` then `asyncio.run(_run())`. Patching
    `nestor_pulse_sdk.runs.worker.main` does NOT reach the `__main__` copy --
    that is a different module object, which is the whole point of this file --
    so neutralise one level down, at `asyncio.run`, which both copies resolve
    through the shared `asyncio` module.
    """

    def _no_run(coro, *args, **kwargs):
        # Close the coroutine so no "never awaited" RuntimeWarning is emitted.
        close = getattr(coro, "close", None)
        if close is not None:
            close()
        return None

    monkeypatch.setattr(asyncio, "run", _no_run)
    # Skip the Secret Manager bootstrap inside main() (no network in tests).
    monkeypatch.setenv("LOCAL_DEV_AUTH", "1")
    yield


def _worker_module_objects() -> list:
    """Distinct module objects in sys.modules whose file IS runs/worker.py."""
    target = os.path.realpath(str(_WORKER_PY))
    seen: dict[int, object] = {}
    for mod in list(sys.modules.values()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        try:
            if os.path.realpath(f) == target:
                seen[id(mod)] = mod
        except (OSError, ValueError):  # pragma: no cover - defensive
            continue
    return list(seen.values())


def test_dash_m_worker_does_not_double_import(monkeypatch: pytest.MonkeyPatch):
    """RED before the fix: `-m ...runs.worker` yielded TWO WORKER_IDs.

    This reproduces the live defect exactly: run worker.py as `__main__`, then
    do what execute.py does -- import it under its canonical name -- and compare
    the two WORKER_ID values.
    """
    with _isolated_import_state():
        _purge_worker_modules()
        with _neutralised_main(monkeypatch):
            main_globals = runpy.run_module(
                WORKER_MODULE, run_name="__main__", alter_sys=True
            )

        main_worker_id = main_globals["WORKER_ID"]
        # This is the exact import execute.py performs at dispatch time.
        canonical = importlib.import_module(WORKER_MODULE)
        canonical_worker_id = canonical.WORKER_ID

        assert main_worker_id == canonical_worker_id, (
            "worker.py evaluated WORKER_ID TWICE in one process -- the "
            "`__main__` copy claims the run, the canonical copy owns every "
            "fenced write, and `WHERE worker_id = :wid` matches zero rows "
            f"(DEF-23.3-01).\n  __main__  copy WORKER_ID = {main_worker_id!r}\n"
            f"  canonical copy WORKER_ID = {canonical_worker_id!r}"
        )
        assert main_worker_id is canonical_worker_id


def test_launcher_loads_worker_exactly_once(monkeypatch: pytest.MonkeyPatch):
    """The container path: `-m ...runs.worker_main` loads worker.py once."""
    with _isolated_import_state():
        _purge_worker_modules()
        with _neutralised_main(monkeypatch):
            runpy.run_module(LAUNCHER_MODULE, run_name="__main__", alter_sys=True)

        loaded = _worker_module_objects()
        assert len(loaded) == 1, (
            "runs/worker.py was loaded as more than one module object via the "
            f"launcher: {[getattr(m, '__name__', '?') for m in loaded]}"
        )
        assert WORKER_MODULE in sys.modules
        assert sys.modules[WORKER_MODULE] is loaded[0]
        # And the identity that actually matters downstream:
        assert sys.modules[WORKER_MODULE].WORKER_ID == loaded[0].WORKER_ID


def test_worker_dockerfile_cmd_points_at_the_launcher():
    """A CMD drift back to `runs.worker` must fail here."""
    assert _DOCKERFILE.is_file(), f"worker Dockerfile not found at {_DOCKERFILE}"
    text = _DOCKERFILE.read_text(encoding="utf-8")

    cmds = re.findall(r"^\s*CMD\s+(\[.*\])\s*$", text, flags=re.MULTILINE)
    assert len(cmds) == 1, f"expected exactly one exec-form CMD, found {cmds!r}"

    assert json.loads(cmds[0]) == ["python", "-m", LAUNCHER_MODULE]
