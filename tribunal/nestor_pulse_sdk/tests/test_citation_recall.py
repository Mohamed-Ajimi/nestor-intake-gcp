"""
PHASE1-05 -- Citation recall on canonical run (owning plan: 09)

Per 01-VALIDATION.md row:
  "On >=50-claim canonical run, >=95% of claims have >=1 attached source"
  Test type: quality gate
  Command: pytest nestor_pulse_sdk/tests/test_citation_recall.py
           --runs=<canonical>

Wave 0 stub -- bodies land in Plan 09. The `--runs=` CLI arg is parsed
by Plan 09's conftest extension; until then, the test is skipped when
the option is absent.
"""

import pytest

pytestmark = pytest.mark.xfail(
    reason="stub -- implementation lands in Plan 09",
    strict=False,
)


async def test_canonical_run_95_percent_recall(request):
    """>=95% of canonical-run claims must carry >=1 attached source."""
    if not request.config.getoption("--runs", default=None):
        pytest.skip("--runs=<canonical> arg required (Plan 09 wires this)")
    assert False, "pending Plan 09 -- canonical-run citation recall calc"
