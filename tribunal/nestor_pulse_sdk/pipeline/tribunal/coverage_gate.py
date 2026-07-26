"""Tribunal coverage gate — Plan 01-15 Task 1; surface corrected by 15.2 plan 07.

Enforces: every claim the GATES selected for checking must end the verify stage
with a verdict, or the gate fails and those claims get one bounded last chance.

Design (ADR-006 §Decision stage 4, as amended by G-02 and 15.2 D-07-B):
  - The coverage surface is claims that are BOTH `stakes == "high"` AND
    gate-selected (`claim["gate"]["strict"] == "VERIFY"`). Stakes alone is no
    longer the selector: G-02 made the two cheap per-claim gates (materiality and
    error-likelihood) the single answer to "what gets checked", and stakes only
    sets how DEEP a surviving session goes (`pipeline._GROUP_DEPTH`).
  - Low + med claims are exempt from the gate (they may have 0 skeptics).
  - Gate returns pass/uncovered for bounded re-entry.
  - MAX_REENTRY caps how many times the pipeline can re-run the uncovered set.

WHY THE INTERSECTION EXISTS — THE WR-01 COST TRAP (D-07-B). Read this before
"simplifying" the `selected_only` guard away.

WR-01 (`15.1-UAT.md` § Deferred to Phase 15.2) recorded that `pipeline.py` built
its `adjudications` mapping with a test that was unconditionally true, so this
gate always passed, `uncovered` was always empty and the re-entry loop was
unreachable dead code. 15.2 plan 07 fixes that. Applied on its own, however, that
fix is a denial-of-wallet bug, because the pre-G-02 coverage surface counts claims
the gates deliberately refused to check:

    recorded run 4cbb5311 population
      706 claims  DROP          (not falsifiable / not load-bearing / both)
    +  32 claims  SKIP_STABLE   (stable, notorious facts)
    = 738 claims that carry NO verdict BY DESIGN

`_propagate_stakes` copies each focus area's stakes onto every one of its claims,
so an unknown but large share of those 738 are `stakes == "high"`. The re-entry
loop fires per uncovered claim, so under the pre-G-02 surface the WR-01 fix would
have dispatched roughly **2,100 extra Anthropic tool-use sessions** against a
verify stage the gates exist to shrink to about 150.

Nothing else in the engine stops that:
  - `MAX_REENTRY = 1` bounds re-entry to ONE pass. The first pass IS the 2,100.
  - D-11's circuit-breaker gate on the re-entry dispatch only fires AFTER the
    breaker has already tripped — it cannot prevent the first fan-out.
  - The budget governor is INERT (`NESTOR_TRIBUNAL_UNCAPPED=1` makes
    `budget.over_budget()` always return False), so no plan may lean on it.

On 2026-07-22 a monthly usage cap hard-400'd 776 sessions in 55 seconds and
nothing in the process noticed. The intersection below is the correction, and it
lives HERE rather than as an inline filter at the call site so the rule has one
auditable home and this docstring can stop lying about the surface.

WHAT THE INTERSECTION BUYS: bucket 3 (`pipeline._book_unchecked`, whose
population is exactly `gate.strict == "VERIFY"`) and the coverage surface now
count the SAME claims by construction. The two numbers can no longer disagree.

check_coverage(claims, adjudications, selected_only=True)
    -> {"pass": bool, "uncovered": [...]}
  claims:        Full adjudicated claim list (from adjudicate_all input).
  adjudications: Mapping of id(claim) -> verdict_or_bool. Any truthy value
                 counts as "adjudicated" for coverage purposes.
  selected_only: True (the default, and the ONLY value production may pass)
                 intersects the surface with `gate.strict == "VERIFY"`.
                 False restores the pre-15.2 surface — stakes alone — and is
                 retained for the legacy / A-B caller and for tests that pin the
                 difference. NEVER for the production path: it is the cost trap.

Sources: WR-01 (`15.1-UAT.md`), D-11, G-02, 15.2 plan 07 (D-07-B).

T-15-02 mitigation: budget governor ensures the per-claim skeptic loop does NOT
silently skip high-stakes claims under budget pressure. The coverage gate is the
enforcement boundary: a selected high-stakes claim that was skipped due to budget
shows up in uncovered[] -> pipeline verdict=fail, preserving auditability.
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
    selected_only: bool = True,
) -> dict[str, Any]:
    """Check that every gate-selected high-stakes claim has been adjudicated.

    Args:
        claims:        Full list of claim dicts (same list passed to adjudicate_all).
        adjudications: Mapping of id(claim) -> any truthy value meaning 'adjudicated'.
                       Absent keys = not adjudicated.
        selected_only: Intersect the coverage surface with the GATE selection —
                       `(claim.get("gate") or {}).get("strict") == "VERIFY"`. This
                       is the D-07-B cost control and defaults to True, because
                       the safe behaviour must be what a caller gets for free.
                       Pass False only to reproduce the pre-15.2 surface (stakes
                       alone) in a test or in the legacy A/B caller — never in
                       production, where it is worth roughly 2,100 unnecessary
                       Anthropic sessions on the recorded population (WR-01).

    Returns:
        {
            "pass":      True if all gate-selected high-stakes claims are covered.
            "uncovered": List of claim dicts NOT present in adjudications.
                         Empty when pass=True.
        }

    Coverage surface: claims that are BOTH `stakes == "high"` AND gate-selected.
    Low + med claims are excluded (they may legitimately have 0 skeptics), and so
    are claims the gates DROPped or marked SKIP_STABLE — those carry no verdict by
    design, they are already counted in bucket 2 with a named reason, and
    re-checking them is the WR-01 cost trap this module's docstring describes.
    """
    uncovered: list[dict[str, Any]] = []

    for claim in claims:
        if selected_only and (claim.get("gate") or {}).get("strict") != "VERIFY":
            # D-07-B: the gates already decided this claim is not worth a billed
            # session. Not a coverage loss — a deliberate, counted exclusion.
            # Same expression as pipeline._book_unchecked's bucket-3 predicate, so
            # the two populations are identical by construction.
            continue
        stakes = claim.get("stakes", "")
        if stakes != "high":
            # Not in the coverage surface — exempt
            continue
        if id(claim) not in adjudications:
            log.warning(
                "coverage_gate: GATE-SELECTED high-stakes claim got no verdict "
                "-> uncovered (text=%r)",
                claim.get("text", "")[:80],
            )
            uncovered.append(claim)

    gate_passed = len(uncovered) == 0
    if gate_passed:
        log.debug(
            "coverage_gate: PASS — every gate-selected high-stakes claim adjudicated "
            "(%d claims total, selected_only=%s)",
            len(claims), selected_only,
        )
    else:
        log.warning(
            "coverage_gate: FAIL — %d gate-selected high-stakes claim(s) unadjudicated "
            "(bounded re-entry allowed, MAX_REENTRY=%d, selected_only=%s)",
            len(uncovered),
            MAX_REENTRY,
            selected_only,
        )

    return {"pass": gate_passed, "uncovered": uncovered}
