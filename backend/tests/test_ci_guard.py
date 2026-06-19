"""QA-02 CI isolation guard — positive + negative tests.

Proves ``scripts/ci_no_permissive_rls.sh`` is a working build gate:

  - positive: run the guard against the REAL migrations
    (``app/db/alembic/versions/``) and assert it exits 0 — no permissive policy
    (``USING (true)`` / ``WITH CHECK (true)``) exists in the migrations 0001-0003.
  - negative: plant a temp migration containing ``USING (true)`` in a tmp dir,
    point the guard at that dir, and assert it exits NON-ZERO — i.e. the guard
    actually catches a permissive policy and would fail CI.

The contract under test is the guard's EXIT CODE (not stdout content), matching
how CI consumes it. ``bash`` is required to run the script; when it is not on
PATH (e.g. a bare Windows box) the tests SKIP cleanly rather than error, so the
suite stays collectable everywhere — mirroring the Docker/DB skip philosophy in
conftest.py.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

# scripts/ci_no_permissive_rls.sh lives at backend/scripts/, this file at
# backend/tests/ -> backend root is one level up from tests/.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_GUARD = os.path.join(_BACKEND_ROOT, "scripts", "ci_no_permissive_rls.sh")
_REAL_VERSIONS = os.path.join(_BACKEND_ROOT, "app", "db", "alembic", "versions")


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


def test_guard_passes_on_clean_migrations():
    """The real migrations contain no permissive policy -> guard exits 0."""
    assert os.path.exists(_GUARD), f"guard script missing: {_GUARD}"
    result = _run_guard(_REAL_VERSIONS)
    assert result.returncode == 0, (
        "CI guard FAILED against the real migrations — a permissive RLS policy "
        f"(USING (true) / WITH CHECK (true)) leaked in.\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_guard_fails_on_planted_offender(tmp_path):
    """A planted USING (true) policy -> guard exits non-zero (the gate works)."""
    offender = tmp_path / "0099_permissive_offender.py"
    # A realistic permissive policy — exactly the inherited Supabase bug class.
    offender.write_text(
        'from alembic import op\n\n\n'
        'def upgrade():\n'
        '    op.execute(\n'
        '        """\n'
        '        CREATE POLICY intakes_open ON nestor.intakes\n'
        '            USING (true)\n'
        '            WITH CHECK (true)\n'
        '        """\n'
        '    )\n',
        encoding="utf-8",
    )

    result = _run_guard(str(tmp_path))
    assert result.returncode != 0, (
        "CI guard did NOT fail on a planted USING (true) policy — the QA-02 gate "
        f"is broken.\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
