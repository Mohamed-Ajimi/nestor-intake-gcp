"""D-03 CI raw-DB-access guard — positive + negative tests.

Proves ``scripts/ci_no_raw_db_access.sh`` is a working build gate:

  - positive: run the guard against the REAL app tree (``app/``) and assert it
    exits 0 — no raw DB access (engine/session construction) leaks out of the
    whitelisted ``app/db/`` seam today.
  - negative: plant a temp ``.py`` containing a raw ``get_engine()`` / ``Session(``
    call in a tmp dir, point the guard at that dir, and assert it exits NON-ZERO —
    i.e. the guard actually catches a module reaching for the DB outside the seam
    and would fail CI.

The contract under test is the guard's EXIT CODE (not stdout content), matching
how CI consumes it — the structural twin of ``test_ci_guard.py`` (QA-02). ``bash``
is required to run the script; when it is not on PATH (e.g. a bare Windows box)
the tests SKIP cleanly rather than error, so the suite stays collectable
everywhere — mirroring the Docker/DB skip philosophy in conftest.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

# scripts/ci_no_raw_db_access.sh lives at backend/scripts/, this file at
# backend/tests/ -> backend root is one level up from tests/.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUARD = os.path.join(_BACKEND_ROOT, "scripts", "ci_no_raw_db_access.sh")
_REAL_APP = os.path.join(_BACKEND_ROOT, "app")


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


def test_guard_passes_on_clean_app_tree():
    """The real app/ tree has no raw DB access outside app/db/ -> guard exits 0."""
    assert os.path.exists(_GUARD), f"guard script missing: {_GUARD}"
    result = _run_guard(_REAL_APP)
    assert result.returncode == 0, (
        "D-03 guard FAILED against the real app/ tree — raw DB access "
        "(engine/session construction) leaked outside the app/db/ seam.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_guard_fails_on_planted_offender(tmp_path):
    """A planted get_engine()/Session( call -> guard exits non-zero (gate works)."""
    offender = tmp_path / "rogue_endpoint.py"
    # A realistic raw-DB bypass — a feature module opening its own engine/session
    # instead of going through the injected tenant repository (exactly the
    # per-endpoint, omittable-tenant-filter hole D-03 exists to prevent).
    offender.write_text(
        "from app.db.base import get_engine\n"
        "from sqlalchemy.orm import Session\n\n\n"
        "def list_all_intakes():\n"
        "    engine = get_engine()\n"
        "    with Session(engine) as session:\n"
        "        return session.execute('SELECT * FROM nestor.intakes').all()\n",
        encoding="utf-8",
    )

    result = _run_guard(str(tmp_path))
    assert result.returncode != 0, (
        "D-03 guard did NOT fail on a planted get_engine()/Session( call — the "
        f"gate is broken.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
