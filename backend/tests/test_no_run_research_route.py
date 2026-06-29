"""INTAKE-05 scope-ceiling guard — a STRUCTURAL assertion that the FastAPI app exposes
NO deep-research-stage route, and that ``intake_routes.py`` defines no such handler.

The re-platform scope STOPS at status ``decomposed``: the later deep-research stage (the
separate out-of-scope track) must never be reachable from the new backend. This guard
pins that ceiling two ways:

1. **Live route table** — import the production ``app`` and assert NO ``app.routes`` path
   contains a forbidden token. A future handler that wired such a route would flip this
   RED immediately (a structural layer beneath the ``ci_no_run_research.sh`` grep-guard,
   which lands in a later plan).
2. **Source scan** — parse ``backend/app/api/intake_routes.py`` for route-decorator path
   literals (``@<router>.get("…")`` etc.) and assert none carries a forbidden token. The
   scan targets only the decorator PATH strings — never prose — so the module's own
   scope-ceiling docstring (which legitimately discusses the deep-research stage in
   English) does not produce a false positive.

Analog: ``test_no_bearer_routes.py`` — same structural file/route-absence style; the path
root is derived from ``__file__`` (never a hardcoded absolute path); the source scan
skips cleanly when its artifact is absent (mirrors the conftest skip-clean philosophy).

This test file lives in ``backend/tests/`` (NOT ``backend/app/``), so the forbidden tokens
it must spell out in its own assertions do not trip the ``ci_no_run_research.sh`` guard,
which scans ``backend/app/**.py`` only.
"""

from __future__ import annotations

import os
import re

import pytest

# This file lives at backend/tests/test_no_run_research_route.py. The backend root is two
# levels up: tests -> backend. Derived from __file__ so the test is portable (no hardcoded
# absolute path), exactly like test_no_bearer_routes.py's _REPO_ROOT.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INTAKE_ROUTES = os.path.join(_REPO_ROOT, "app", "api", "intake_routes.py")

# Forbidden tokens that must never appear in a reachable route PATH. The flow ends at
# ``decomposed``; the deep-research stage is a separate, out-of-scope track. The token set
# matches the sibling ``ci_no_run_research.sh`` regex (run-research / run_research /
# tribunal) plus a defensive bare ``research`` (no in-scope route path contains it).
_FORBIDDEN_PATH_TOKENS = ("run-research", "run_research", "tribunal", "research")

# Captures a FastAPI route-decorator PATH literal so the source scan inspects only route
# definitions, never docstrings/prose, e.g.:
#   @intake_router.post("/intakes/{intake_id}/submit")  -> "/intakes/{intake_id}/submit"
_ROUTE_DECORATOR = re.compile(
    r"""@\w+_router\.(?:get|post|put|patch|delete|head|options)\(\s*["']([^"']*)["']""",
    re.IGNORECASE,
)


def _forbidden_in(path: str) -> list[str]:
    """Return the forbidden tokens present (lowercased match) in ``path`` (possibly empty)."""
    low = path.lower()
    return [tok for tok in _FORBIDDEN_PATH_TOKENS if tok in low]


def test_app_exposes_no_deep_research_route():
    """The live FastAPI app must expose NO route whose path carries a forbidden token.

    Skips cleanly on a box without the backend deps / Admin SDK installed (importing the
    app pulls firebase_admin + the DB layer); the real gate runs in CI where those exist.
    """
    pytest.importorskip("firebase_admin")
    pytest.importorskip("fastapi")
    main = pytest.importorskip("app.main")

    offending = {
        path: hits
        for r in main.app.routes
        for path in [getattr(r, "path", "")]
        if (hits := _forbidden_in(path))
    }
    assert not offending, (
        "INTAKE-05 scope-ceiling breach: the app exposes deep-research-stage route(s) "
        f"{offending}. The flow must stop at 'decomposed' — no such route may be mounted."
    )


def test_intake_routes_defines_no_deep_research_handler():
    """``intake_routes.py`` must declare no route-decorator path carrying a forbidden token.

    Pure source scan (no import) — skips cleanly if the module file is absent. Only route
    DECORATOR path literals are inspected, so the module's English scope-ceiling docstring
    (which discusses the out-of-scope stage) never yields a false positive.
    """
    if not os.path.exists(_INTAKE_ROUTES):
        pytest.skip("intake_routes.py not present (feature router lands in plan 03)")

    source = open(_INTAKE_ROUTES, encoding="utf-8").read()
    route_paths = _ROUTE_DECORATOR.findall(source)
    offending = {path: hits for path in route_paths if (hits := _forbidden_in(path))}
    assert not offending, (
        "INTAKE-05 scope-ceiling breach: intake_routes.py defines a route whose path "
        f"carries a forbidden token {offending}. The intake surface stops at 'decomposed'."
    )
