"""The run-output access model is ONE predicate, and every gate goes through it (D-09).

WHY this file exists
--------------------
Four separate `run.status != "completed"` comparisons in `runs/api.py` were the entire
access model for a ~$45 run's output: two loop filters (blind critique, content compare)
and two 409 guards (`/report`, `/research-bundle`). Four copies of a rule drift, and G-10
deferred the `completed_degraded` marker for exactly that reason. Phase 15.2 promotes the
marker into a real terminal state, so the four copies collapse into `report_readable()` /
`bundle_readable()` in `runs/schemas.py` — and this file is what keeps them collapsed.

It pins five things:
  * the two predicate truth tables, over the full nine-literal `RunStatus`;
  * that `parked` gets INSPECTION (the bundle) but not the REPORT — there is no report yet;
  * that no bare status comparison survives in `runs/api.py` (the source gate);
  * **F1** — `GET /{run_id}/verification` is deliberately gate-free and stays that way,
    because a parked run must be able to show *why* it stopped;
  * **F2** — a degraded run's metrics report `done`, not a permanently spinning stage;
  * **ASVS V4** — widening a *status* gate never widened *tenant* scope: both widened
    handlers still hide a cross-tenant run behind a 404 and never a 403;
  * that the worker writes a `terminal_state()`-computed status and kept its cancel guard;
  * **D-12** — a recovered retry and a pending grounding fee can never degrade a run.

All tests are pure: no DB, no network, no LLM, no mocking library, no API key. Source is
read as TEXT with the path resolved through each module's `__file__`, never a repo-root
relative path, because the build context ships only the `tribunal/` subtree.

Cloud Build invocation:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import get_args

from nestor_pulse_sdk.pipeline.tribunal.reliability import terminal_state
from nestor_pulse_sdk.runs.schemas import RunStatus, bundle_readable, report_readable

_ALL_STATUSES = set(get_args(RunStatus))


def _api_source() -> str:
    """`runs/api.py` as text, resolved through the package (never a relative path)."""
    from nestor_pulse_sdk.runs import api as api_module

    return Path(api_module.__file__).read_text(encoding="utf-8")


def _worker_source() -> str:
    """`runs/worker.py` as text, resolved through the package."""
    from nestor_pulse_sdk.runs import worker as worker_module

    return Path(worker_module.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# The two truth tables
# ---------------------------------------------------------------------------


def test_report_readable_truth_table():
    """The report body is readable for exactly {completed, completed_degraded}."""
    expected = {"completed", "completed_degraded"}
    for status in _ALL_STATUSES:
        assert report_readable(status) is (status in expected), (
            f"report_readable({status!r}) disagrees with the D-09 access model: the "
            f"report body is readable for exactly {sorted(expected)}"
        )


def test_bundle_readable_truth_table():
    """The research bundle is readable for exactly {completed, completed_degraded, parked}."""
    expected = {"completed", "completed_degraded", "parked"}
    for status in _ALL_STATUSES:
        assert bundle_readable(status) is (status in expected), (
            f"bundle_readable({status!r}) disagrees with the D-09 access model: the "
            f"bundle is readable for exactly {sorted(expected)}"
        )


def test_parked_gets_inspection_not_the_report():
    """D-09: a parked run may be INSPECTED, but it has no deliverable to hand over."""
    assert bundle_readable("parked") and not report_readable("parked"), (
        "a parked run has research in hand, so the superadmin must be able to inspect "
        "the bundle before deciding to resume -- but there is no finished, scrubbed "
        "report yet, and serving one would ship unverified prose as a deliverable"
    )


# ---------------------------------------------------------------------------
# The source gates
# ---------------------------------------------------------------------------


def test_all_four_gates_route_through_the_predicate():
    """No bare status comparison survives in `runs/api.py`.

    NOTE for future editors: prose in `runs/api.py` that needs to refer to the old
    comparison must be written WITHOUT quotes -- `status != completed` -- so a comment
    can never satisfy this regex and make the gate dishonest.
    """
    src = _api_source()

    assert re.findall(r'status\s*!=\s*"completed"', src) == [], (
        "a bare `status != \"completed\"` comparison is back in runs/api.py -- that is "
        "the four-copies-drift the D-09 predicate exists to prevent"
    )
    assert src.count("report_readable(") >= 4, (
        "expected at least 4 report_readable call sites: blind critique, content "
        "compare, GET /report, and the F2 metrics display line"
    )
    assert src.count("bundle_readable(") >= 1, (
        "expected the GET /research-bundle gate to call bundle_readable"
    )


def test_verification_endpoint_has_no_status_gate():
    """F1: `GET /{run_id}/verification` is deliberately gate-free and must stay so."""
    from nestor_pulse_sdk.runs.api import get_run_verification

    src = inspect.getsource(get_run_verification)

    for forbidden in ("report_readable", "bundle_readable", "409"):
        assert forbidden not in src, (
            f"{forbidden!r} appeared in get_run_verification. A parked run must be able "
            "to show WHY it stopped; adding a status gate here is the regression (F1)."
        )
    assert "parked" in (get_run_verification.__doc__ or ""), (
        "the docstring must record that this endpoint is deliberately gate-free and "
        "already correct for a parked run, so nobody 'fixes' it later"
    )


def test_metrics_reports_done_for_a_degraded_run():
    """F2: a degraded run's stage list is finished, not permanently spinning."""
    src = _api_source()

    assert '"done" if report_readable(run.status)' in src, (
        "get_run_metrics must decide the terminal stage through report_readable"
    )
    assert '"done" if run.status == "completed"' not in src, (
        "the bare comparison leaves a completed_degraded run showing a spinning stage "
        "forever -- on exactly the runs an operator most needs to read (F2)"
    )


def test_widened_handlers_keep_the_404_non_distinguishability():
    """ASVS V4: widening a STATUS gate did not widen TENANT scope."""
    from nestor_pulse_sdk.runs.api import get_run_report, get_run_research_bundle

    for handler in (get_run_report, get_run_research_bundle):
        src = inspect.getsource(handler)
        assert "scalar_one_or_none()" in src, (
            f"{handler.__name__} must load the run with scalar_one_or_none() so an "
            "RLS-invisible row falls through to the 404 branch"
        )
        assert "HTTPException(404" in src, (
            f"{handler.__name__} must 404 on an unknown or cross-tenant run_id"
        )
        assert "403" not in src, (
            f"{handler.__name__} gained a 403. A cross-tenant run_id is INVISIBLE, not "
            "FORBIDDEN -- a 403 confirms the run exists and leaks its existence."
        )


# ---------------------------------------------------------------------------
# The worker write side
# ---------------------------------------------------------------------------


def test_worker_writes_the_status_terminal_state_computed():
    """T-15.2-23: the terminal status is computed, and the cancel guard survived."""
    src = _worker_source()

    assert "status=:final_status" in src, (
        "the completion UPDATE must bind a computed terminal status"
    )
    assert "terminal_state(" in src, (
        "the status must come from terminal_state() (15.2-02's D-17 truth table), not "
        "a second degradation rule written here"
    )
    assert "UPDATE run SET status='completed'" not in src, (
        "the hardcoded 'completed' write is back: a run that lost a stream would report "
        "clean, leaving no record that the output fell short"
    )
    assert "WHERE id=:id AND status='running'" in src, (
        "the cancel guard must survive the edit -- it is what makes a user cancel win"
    )


def test_recovered_retries_and_cost_pending_never_degrade():
    """D-12: the two designed paths that must NEVER demote a run."""
    assert (
        terminal_state(
            streams_lost=0,
            streams_total=1,
            verify_ran=True,
            synthesis_ran=True,
            hard_wall=False,
            degradation_reasons=[],
        )
        == "completed"
    ), "a clean run with no named reason is completed, full stop"

    src = _worker_source()
    start = src.index("# BEGIN reason-building region")
    end = src.index("# END reason-building region")
    region = src[start:end]

    assert "cost_pending" not in region, (
        "a pending Gemini grounding fee is the DESIGNED path (C1), not a shortfall -- "
        "it must never enter the degradation reason list"
    )
    assert '"retry"' not in region and "'retry'" not in region, (
        "a RECOVERED retry is already shown in the feed as recovery (R5); demoting it "
        "would make nearly every run degraded and drain the status of its meaning"
    )
