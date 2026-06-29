"""INTAKE-05 / D-06 CI scope-ceiling guard — positive + negative tests.

Proves ``scripts/ci_no_run_research.sh`` is a working build gate:

  - positive: run the guard with NO args so it scans the REAL trees
    (``backend/app`` + ``frontend/src``) and assert it exits 0 — the
    out-of-scope deep-research stage (run-research / Tribunal) is invoked
    nowhere reachable. The frontend run-research invoke was deleted (plan 06)
    and the post-``decomposed`` components were neutralized (plan 10), so the
    only surviving references are explanatory docstrings/comments + a Dutch
    operator UI string, which the guard deliberately does not match.
  - negative: plant a temp ``*.ts`` containing a genuine
    ``invoke("run-research", ...)`` call in a tmp dir, point the guard at that
    dir, and assert it exits NON-ZERO — i.e. the guard actually catches a
    reintroduced invocation and would fail CI.

The contract under test is the guard's EXIT CODE (not stdout content), matching
how CI consumes it. ``bash`` is required to run the script; when it is not on
PATH (e.g. a bare Windows dev box) the tests SKIP cleanly rather than error, so
the suite stays collectable everywhere — mirroring the Docker/DB skip
philosophy in conftest.py and the sibling guard test (test_ci_guard.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

# scripts/ci_no_run_research.sh lives at backend/scripts/, this file at
# backend/tests/ -> backend root is one level up from tests/.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUARD = os.path.join(_BACKEND_ROOT, "scripts", "ci_no_run_research.sh")


def _bash() -> str:
    """Return a usable bash, or skip cleanly when none is on PATH."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available — CI guard runs in CI / POSIX shells")
    return bash


def _run_guard(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_bash(), _GUARD, *args],
        capture_output=True,
        text=True,
    )


def test_guard_passes():
    """The real trees invoke no run-research/Tribunal stage -> guard exits 0.

    Run with NO args so the guard scans its defaults (backend/app + frontend/src).
    """
    assert os.path.exists(_GUARD), f"guard script missing: {_GUARD}"
    result = _run_guard()
    assert result.returncode == 0, (
        "CI guard FAILED against the real tree — a run-research/Tribunal "
        "invocation leaked into backend/app or frontend/src (INTAKE-05).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_guard_fails_on_planted_offender(tmp_path):
    """A planted run-research invocation -> guard exits non-zero (gate works)."""
    offender = tmp_path / "reintroduced_research.ts"
    # A realistic reintroduction — exactly the scope-ceiling breach this guard
    # exists to make unrepeatable: a frontend edge-function call to run-research.
    offender.write_text(
        'export async function go() {\n'
        '  await supabase.functions.invoke("run-research", { body: {} });\n'
        '}\n',
        encoding="utf-8",
    )

    result = _run_guard(str(tmp_path))
    assert result.returncode != 0, (
        "CI guard did NOT fail on a planted run-research invocation — the "
        f"INTAKE-05 / D-06 scope gate is broken.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
