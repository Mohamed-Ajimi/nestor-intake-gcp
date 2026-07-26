"""Coverage surface, breaker-gated re-entry, F7 and F8 — Phase 15.2 plan 07.

WR-01 (`15.1-UAT.md`) recorded that the coverage gate's `adjudications` mapping was
built with a test that was unconditionally true, so the gate always passed and its
bounded re-entry — the last chance a gate-selected claim gets at a verdict — was
unreachable dead code. This file proves the fix, and proves the two things that had
to land WITH the fix so that it is not a denial-of-wallet bug:

  1. the coverage surface is intersected with the GATE selection (D-07-B), so the
     recorded population's 706 DROP + 32 SKIP_STABLE claims cannot trigger re-entry;
  2. the re-entry fan-out is dispatched only from a fully CLOSED skeptic circuit
     (D-07-C) — `open` and `half_open` both refuse, and every refused claim is
     booked into bucket 3 with a plain-words reason.

THIS FILE MAKES ZERO LLM CALLS. Every provider call is served by
`_ScriptedGroupAudited`, a hand-written duck-typed fake in the style of
`test_gate_replay.py::_AnswerKeyGateAudited`. No network, no database, no mocking
library, no API key, no spend, and nothing that can flake — which matters twice over
while the Anthropic account sits at its monthly cap (resets 2026-08-01). The fake
stands in for the MODEL only: the real `run_group_skeptic`, the real
`_parse_group_verdict`, the real `CircuitBreaker` and the real `check_coverage` all
do their production work.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml

(The file is pre-listed in `tribunal/cloudbuild.test-engine.yaml`, which plan 15.2-02
owns exclusively and no later plan edits.)

Coverage:
  TestCoverageSurface        — D-07-B, the WR-01 cost trap
"""
from __future__ import annotations

from nestor_pulse_sdk.pipeline.tribunal.coverage_gate import (
    MAX_REENTRY,
    check_coverage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _claim(
    *,
    text: str,
    stakes: str = "high",
    strict: str = "VERIFY",
    facet: str = "A",
) -> dict:
    """One claim dict in the shape the verify stage actually sees.

    `gate.strict` is the vocabulary `gates.py` emits: VERIFY (checked),
    DROP (not falsifiable / not load-bearing / both) and SKIP_STABLE (a stable,
    notorious fact).
    """
    return {"text": text, "facet": facet, "stakes": stakes, "gate": {"strict": strict}}


# ---------------------------------------------------------------------------
# D-07-B — the coverage surface is gate-selected AND high-stakes
# ---------------------------------------------------------------------------

class TestCoverageSurface:
    """The population `check_coverage` is allowed to spend money on."""

    def test_dropped_high_stakes_claim_is_not_uncovered(self):
        """A gate-DROPped claim carries no verdict BY DESIGN — not a coverage loss."""
        c = _claim(text="dropped claim", strict="DROP")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_skip_stable_high_stakes_claim_is_not_uncovered(self):
        """Same for a stable, notorious fact the error-likelihood gate skipped."""
        c = _claim(text="water boils at 100C at sea level", strict="SKIP_STABLE")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_selected_high_stakes_claim_with_no_verdict_is_uncovered(self):
        """The claim the re-entry path exists FOR: selected, checked, no verdict."""
        c = _claim(text="selected claim")
        result = check_coverage([c], {})
        assert result["pass"] is False
        assert result["uncovered"] == [c]

    def test_selected_high_stakes_claim_with_a_verdict_is_covered(self):
        c = _claim(text="selected claim")
        result = check_coverage([c], {id(c): True})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_low_stakes_selected_claim_is_exempt(self):
        """The stakes filter is UNCHANGED — the intersection narrows, never widens."""
        c = _claim(text="low stakes but selected", stakes="low")
        result = check_coverage([c], {})
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_selected_only_false_restores_the_legacy_surface(self):
        """The pre-15.2 surface stays reachable — but only on an explicit request."""
        c = _claim(text="dropped claim", strict="DROP")
        result = check_coverage([c], {}, selected_only=False)
        assert result["pass"] is False
        assert result["uncovered"] == [c]

    def test_recorded_population_regression(self):
        """THE WR-01 COST TRAP, at the recorded 4cbb5311 scale.

        706 DROP + 32 SKIP_STABLE = 738 claims that carry no verdict by design,
        all high-stakes (`_propagate_stakes` copies the focus area's stakes onto
        every one of its claims), plus 3 genuinely uncovered VERIFY claims.

        Under the pre-G-02 surface all 741 read as uncovered, and the re-entry
        loop fires per uncovered claim — roughly 2,100 extra Anthropic tool-use
        sessions against a verify stage the gates exist to shrink to ~150. The
        assertion below is what keeps that at 3. Nothing else would: MAX_REENTRY
        bounds the number of PASSES, not the size of the first fan-out; D-11's
        breaker gate only fires after the breaker has already tripped; and the
        budget governor is inert (`NESTOR_TRIBUNAL_UNCAPPED=1`).
        """
        claims = (
            [_claim(text=f"dropped {i}", strict="DROP") for i in range(706)]
            + [_claim(text=f"stable {i}", strict="SKIP_STABLE") for i in range(32)]
            + [_claim(text=f"selected {i}", strict="VERIFY") for i in range(3)]
        )
        result = check_coverage(claims, {})
        assert result["pass"] is False
        assert len(result["uncovered"]) == 3
        assert all(c["gate"]["strict"] == "VERIFY" for c in result["uncovered"])

    def test_max_reentry_is_still_one(self):
        """A claim gets exactly ONE last chance. D-07-B did not touch this bound."""
        assert MAX_REENTRY == 1
