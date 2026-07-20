"""Tribunal coverage gate — Plan 01-15 Task 1.

Enforces: every high-stakes claim must be adjudicated, or the gate fails.

Design (ADR-006 §Decision stage 4):
  - High-stakes claims (stakes='high') are the coverage surface.
  - Low + med claims are exempt from the gate (they may have 0 skeptics).
  - Gate returns pass/uncovered for bounded re-entry.
  - MAX_REENTRY caps how many times the pipeline can re-run the uncovered set.

check_coverage(claims, adjudications) -> {"pass": bool, "uncovered": [...]}
  claims:        Full adjudicated claim list (from adjudicate_all input).
  adjudications: Mapping of id(claim) -> verdict_or_bool. Any truthy value
                 counts as "adjudicated" for coverage purposes.

T-15-02 mitigation: budget governor ensures the per-claim skeptic loop does NOT
silently skip high-stakes claims under budget pressure. The coverage gate is the
enforcement boundary: a high-stakes claim that was skipped due to budget shows
up in uncovered[] -> pipeline verdict=fail, preserving auditability.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

#: Bounded re-entry cap — pipeline may re-run uncovered high-stakes claims at most once.
MAX_REENTRY: int = 1


def check_coverage(
    claims: list[dict[str, Any]],
    adjudications: dict[int, Any],
) -> dict[str, Any]:
    """Check that every high-stakes claim has been adjudicated.

    Args:
        claims:        Full list of claim dicts (same list passed to adjudicate_all).
        adjudications: Mapping of id(claim) -> any truthy value meaning 'adjudicated'.
                       Absent keys = not adjudicated.

    Returns:
        {
            "pass":      True if all high-stakes claims are covered, else False.
            "uncovered": List of claim dicts NOT present in adjudications.
                         Empty when pass=True.
        }

    Coverage surface: only "high" stakes claims.
    Low + med claims are excluded (they may legitimately have 0 skeptics).
    """
    uncovered: list[dict[str, Any]] = []

    for claim in claims:
        stakes = claim.get("stakes", "")
        if stakes != "high":
            # Not in the coverage surface — exempt
            continue
        if id(claim) not in adjudications:
            log.warning(
                "coverage_gate: HIGH-STAKES claim not adjudicated -> uncovered (text=%r)",
                claim.get("text", "")[:80],
            )
            uncovered.append(claim)

    gate_passed = len(uncovered) == 0
    if gate_passed:
        log.debug("coverage_gate: PASS — all high-stakes claims adjudicated (%d claims total)", len(claims))
    else:
        log.warning(
            "coverage_gate: FAIL — %d high-stakes claim(s) unadjudicated (bounded re-entry allowed, MAX_REENTRY=%d)",
            len(uncovered),
            MAX_REENTRY,
        )

    return {"pass": gate_passed, "uncovered": uncovered}
