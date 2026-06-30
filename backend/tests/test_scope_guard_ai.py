"""INTAKE-05 scope-ceiling guard — the AI-seam extension (Phase 7 / T-7-07).

The re-platform flow STOPS at status ``decomposed``. The deep-research stage
(``run-research`` / Tribunal, backed by SerpAPI / SearchAPI / Apify) is a
separate, out-of-scope track that must NEVER be reachable from the new backend —
and in particular must never be reachable from the **new AI seam** (the LLM /
embedding / Whisper ports added in plans 07-05/06/07). This file is the AI-seam
twin of the Phase-6 guards:

  - ``test_no_run_research_route.py`` proves the live FastAPI app exposes no
    deep-research route and that ``intake_routes.py`` declares none.
  - ``scripts/ci_no_run_research.sh`` (run by ``test_scope_guard_run_research.py``)
    is the grep build-gate over ``backend/app`` + ``frontend/src``.

This adds three assertions focused on the AI surface:

1. **Live route table** — import the production ``app`` and assert NO mounted
   route path carries a deep-research token (run-research / run_research /
   tribunal / a bare ``research`` segment, plus the vendor names serpapi /
   searchapi / apify). A future AI route that wired such a path flips this RED.
2. **AI source scan** — scan ``app/ai/**/*.py`` and ``app/api/ai_routes.py`` for a
   *reachable* reference to the deep-research engine: a ``run_research(`` call, a
   ``run-research`` invoke/URL literal, a ``tribunal`` import/attribute, or the
   research-only vendor credentials (``SERPAPI_API_KEY`` / ``SEARCHAPI_API_KEY`` /
   ``APIFY_API_TOKEN``). Docstrings and comments are stripped first, so a module
   that legitimately *documents* the scope ceiling in prose does not false-positive
   (mirrors the precision note in ``ci_no_run_research.sh``). The scan skips clean
   when the AI seam is not yet present (those modules land in sibling plans), and
   still proves "no run-research reference" against whatever AI source exists.
3. **CI guard intact** — invoke ``scripts/ci_no_run_research.sh`` with no args so it
   scans the real trees and assert it still exits 0 (the family gate stays green).

This file lives in ``backend/tests/`` (NOT ``backend/app/``), so the forbidden
tokens it must spell out in its own assertions do not trip the
``ci_no_run_research.sh`` guard, which scans ``backend/app/**`` + ``frontend/src``
only. Paths are derived from ``__file__`` (never hardcoded absolutes), and every
test skips cleanly when its prerequisite (the importable app, the AI modules, or
``bash``) is absent — matching the conftest skip-clean philosophy on a dev box
without Python/Docker.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess

import pytest

# This file lives at backend/tests/test_scope_guard_ai.py -> backend root is two
# levels up (tests -> backend). Derived from __file__ so the test is portable.
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_AI_PKG_DIR = os.path.join(_BACKEND_ROOT, "app", "ai")
_AI_ROUTES = os.path.join(_BACKEND_ROOT, "app", "api", "ai_routes.py")
_GUARD = os.path.join(_BACKEND_ROOT, "scripts", "ci_no_run_research.sh")

# Forbidden tokens that must never appear in a reachable route PATH. Matches the
# sibling ci_no_run_research.sh / test_no_run_research_route.py token family
# (run-research / run_research / tribunal / a defensive bare `research`) plus the
# research-stage vendor names — no in-scope AI route path contains any of these.
_FORBIDDEN_PATH_TOKENS = (
    "run-research",
    "run_research",
    "tribunal",
    "research",
    "serpapi",
    "searchapi",
    "apify",
)

# Reachable-reference patterns for the AI source scan. Anchored to real call /
# import / invoke / env-access syntax (NOT bare prose) so a scope-documenting
# docstring/comment does not false-positive — the same precision discipline as
# ci_no_run_research.sh. Tokens spelled here are inert: this file is under
# backend/tests/, outside the ci guard's scan roots.
_AI_FORBIDDEN_SOURCE = re.compile(
    r"""
      run_research\s*\(                 # a run_research(...) call
    | \.run_research\b                  # a .run_research attribute / method
    | ["'][^"'\n]*run-research          # "run-research" / "/run-research" literal (invoke/URL)
    | /run-research                     # a bare run-research URL segment
    | (?:from|import)\s+[\w.]*tribunal  # a python import of a tribunal module
    | \.tribunal\b                      # a .tribunal attribute / call
    | SERPAPI_API_KEY                   # research-only vendor creds — the AI seam
    | SEARCHAPI_API_KEY                 # must never name or read these (they belong
    | APIFY_API_TOKEN                   # exclusively to the out-of-scope run-research)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A triple-quoted block (docstring or multi-line literal). The backreference keeps
# the closing quote-style matched to the opening one so `"""..."""` and `'''...'''`
# pair correctly. Stripped before the source scan so prose never false-positives.
_TRIPLE_QUOTED = re.compile(r"(?P<q>\"\"\"|''')(?:.|\n)*?(?P=q)")


def _forbidden_path_tokens(path: str) -> list[str]:
    """Forbidden tokens present (case-insensitive) in a route ``path`` (maybe empty)."""
    low = path.lower()
    return [tok for tok in _FORBIDDEN_PATH_TOKENS if tok in low]


def _strip_comments_and_docstrings(source: str) -> str:
    """Return ``source`` with triple-quoted blocks and ``#`` comments removed.

    Lets the source scan inspect only *code* — a module that documents the scope
    ceiling in its docstring (legitimate, per project convention) does not trip the
    guard. The ``#``-strip is line-naive (it does not honour ``#`` inside a string),
    which is acceptable here: it only ever *removes* potential matches, so it can
    never manufacture a false positive, and a genuine reachable call/import/env
    access does not hide behind a ``#`` on the same line.
    """
    without_docstrings = _TRIPLE_QUOTED.sub("", source)
    out_lines = []
    for line in without_docstrings.splitlines():
        hash_pos = line.find("#")
        if hash_pos != -1:
            line = line[:hash_pos]
        out_lines.append(line)
    return "\n".join(out_lines)


def _ai_source_files() -> list[str]:
    """All AI-seam python sources: ``app/ai/**/*.py`` + ``app/api/ai_routes.py``."""
    files = sorted(glob.glob(os.path.join(_AI_PKG_DIR, "**", "*.py"), recursive=True))
    if os.path.exists(_AI_ROUTES):
        files.append(_AI_ROUTES)
    return files


def _bash() -> str:
    """Return a usable bash, or skip cleanly when none is on PATH (CI / POSIX shells)."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash not available — the CI guard runs in CI / POSIX shells")
    return bash


def test_app_exposes_no_deep_research_route():
    """The live FastAPI app must mount NO route whose path carries a research token.

    Skips cleanly on a box without the backend deps / Admin SDK installed (importing
    the app pulls firebase_admin + the DB layer); the real gate runs in CI.
    """
    pytest.importorskip("firebase_admin")
    pytest.importorskip("fastapi")
    main = pytest.importorskip("app.main")

    offending = {
        path: hits
        for r in main.app.routes
        for path in [getattr(r, "path", "")]
        if (hits := _forbidden_path_tokens(path))
    }
    assert not offending, (
        "INTAKE-05 scope-ceiling breach: the app exposes deep-research-stage "
        f"route(s) {offending}. The flow must stop at 'decomposed' — the AI seam "
        "must never mount a run-research / Tribunal route."
    )


def test_ai_modules_reference_no_research_engine():
    """No ``app/ai/*`` module nor ``ai_routes.py`` references the deep-research engine.

    Pure source scan (no import). Skips clean when the AI seam is absent (those
    modules land in plans 07-05/06/07); when present it proves none reach
    run-research / Tribunal / the research-only vendor creds. Docstrings/comments are
    stripped first, so a module's English scope-ceiling note never false-positives.
    """
    sources = _ai_source_files()
    if not sources:
        pytest.skip("AI seam not present yet (app/ai/* + ai_routes.py land in 07-05/06/07)")

    offenders: dict[str, list[str]] = {}
    for path in sources:
        with open(path, encoding="utf-8") as fh:
            code = _strip_comments_and_docstrings(fh.read())
        hits = _AI_FORBIDDEN_SOURCE.findall(code)
        # findall on an alternation returns the full match per hit; normalise to the
        # matched substrings for a readable assertion message.
        matched = [m if isinstance(m, str) else next(filter(None, m), "") for m in hits]
        meaningful = [m.strip() for m in matched if m.strip()]
        if meaningful:
            offenders[os.path.relpath(path, _BACKEND_ROOT)] = meaningful

    assert not offenders, (
        "INTAKE-05 scope-ceiling breach: the AI seam references the out-of-scope "
        f"deep-research engine {offenders}. The new AI ports (LLM / embeddings / "
        "Whisper) must never call run-research / Tribunal nor read the SerpAPI / "
        "SearchAPI / Apify credentials — the flow stops at 'decomposed' (T-7-07)."
    )


def test_ci_no_run_research_guard_still_passes():
    """The Phase-6 ``ci_no_run_research.sh`` build gate still exits 0 on the real trees.

    Run with NO args so it scans its defaults (backend/app + frontend/src). The AI
    ports must not have leaked a run-research / Tribunal invocation into either tree.
    Skips cleanly when ``bash`` is unavailable (bare Windows dev box).
    """
    assert os.path.exists(_GUARD), f"scope guard script missing: {_GUARD}"
    result = subprocess.run([_bash(), _GUARD], capture_output=True, text=True)
    assert result.returncode == 0, (
        "ci_no_run_research.sh FAILED — a run-research/Tribunal invocation leaked "
        "into backend/app or frontend/src after the AI ports (INTAKE-05).\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert "OK" in result.stdout
