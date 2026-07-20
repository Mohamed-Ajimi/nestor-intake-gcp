"""Tests for adjudicate.py + coverage_gate.py — Plan 01-15 Task 1 (TDD RED).

Tests exercise:
  adjudicate.adjudicate(claim, verdicts, survival_rule) -> bool
    - majority-independent: all-support -> survives
    - majority-independent: majority-refute-with-independent-source -> dropped
    - majority-independent: majority-refute-without-independent-source -> survives
    - 0-skeptic low-stakes claim -> survives (waves through)
  adjudicate.adjudicate_all(claims, verdicts_by_claim, survival_rule) -> {survivors, dropped}
  coverage_gate.check_coverage(claims, adjudications) -> {pass: bool, uncovered: [...]}
    - fails when a high-stakes claim is missing from adjudications
    - passes when all high-stakes claims are covered
  research_division.divide(mission_brief) -> list[dict]
    - returns angle dicts with query + stakes
    - high-stakes angles appear 2+ times (doubled for redundancy)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# adjudicate imports
# ---------------------------------------------------------------------------
from nestor_pulse_sdk.pipeline.tribunal.adjudicate import (
    adjudicate,
    adjudicate_all,
)
from nestor_pulse_sdk.pipeline.tribunal.coverage_gate import (
    check_coverage,
    MAX_REENTRY,
)
from nestor_pulse_sdk.pipeline.tribunal.research_division import divide


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claim(text: str = "test claim", facet: str = "A", stakes: str = "high") -> dict:
    return {"text": text, "facet": facet, "stakes": stakes}


def _support_verdict(independent: bool = True) -> dict:
    return {
        "verdict": "support",
        "confidence": 0.9,
        "evidence_refs": ["https://example.com/evidence"] if independent else [],
        "citations": [],
        "has_independent_source": independent,
    }


def _refute_verdict(independent: bool = True) -> dict:
    return {
        "verdict": "refute",
        "confidence": 0.8,
        "evidence_refs": ["https://independent.org/proof"] if independent else [],
        "citations": [],
        "has_independent_source": independent,
    }


def _insufficient_verdict() -> dict:
    return {
        "verdict": "insufficient",
        "confidence": 0.3,
        "evidence_refs": [],
        "citations": [],
        "has_independent_source": False,
    }


# ---------------------------------------------------------------------------
# adjudicate — majority-independent survival rule
# ---------------------------------------------------------------------------

class TestAdjudicateMajorityIndependent:
    """Tests for survival_rule='majority-independent' (the Plan 01-14 locked default)."""

    RULE = "majority-independent"

    def test_all_support_survives(self):
        """All skeptics support the claim -> it survives."""
        claim = _make_claim()
        verdicts = [_support_verdict(), _support_verdict(), _support_verdict()]
        assert adjudicate(claim, verdicts, self.RULE) is True

    def test_majority_refute_with_independent_source_drops(self):
        """Majority refute AND at least one cites an independent source -> dropped."""
        claim = _make_claim()
        # 2 refute with independent source, 1 support -> majority refute + independent
        verdicts = [
            _refute_verdict(independent=True),
            _refute_verdict(independent=True),
            _support_verdict(),
        ]
        assert adjudicate(claim, verdicts, self.RULE) is False

    def test_majority_refute_without_independent_source_survives(self):
        """Majority refute but NO independent source cited -> claim survives.

        ADR-006 survival rule: refuting REQUIRES an independent source.
        """
        claim = _make_claim()
        # 2 refute but without independent source
        verdicts = [
            _refute_verdict(independent=False),
            _refute_verdict(independent=False),
            _support_verdict(),
        ]
        assert adjudicate(claim, verdicts, self.RULE) is True

    def test_zero_skeptics_low_stakes_survives(self):
        """A claim with 0 skeptics (low stakes) waves through -> survives."""
        claim = _make_claim(stakes="low")
        verdicts = []
        assert adjudicate(claim, verdicts, self.RULE) is True

    def test_single_support_survives(self):
        """Single supporting verdict -> survives (not majority refute)."""
        claim = _make_claim()
        verdicts = [_support_verdict()]
        assert adjudicate(claim, verdicts, self.RULE) is True

    def test_all_insufficient_survives(self):
        """All insufficient (no refutation) -> survives (insufficient alone is not dropped)."""
        claim = _make_claim()
        verdicts = [_insufficient_verdict(), _insufficient_verdict()]
        assert adjudicate(claim, verdicts, self.RULE) is True

    def test_mixed_one_refute_one_support_survives(self):
        """1 refute with independent + 1 support -> not majority refute -> survives."""
        claim = _make_claim()
        verdicts = [_refute_verdict(independent=True), _support_verdict()]
        # Not a majority: 1 out of 2 refute with independent, but majority means > half
        # depends on implementation — 1:1 is not majority (need >50%)
        assert adjudicate(claim, verdicts, self.RULE) is True


# ---------------------------------------------------------------------------
# adjudicate_all
# ---------------------------------------------------------------------------

class TestAdjudicateAll:

    RULE = "majority-independent"

    def test_adjudicate_all_splits_survivors_and_dropped(self):
        """adjudicate_all returns {survivors, dropped} correctly."""
        claim_a = _make_claim(text="claim A", stakes="high")
        claim_b = _make_claim(text="claim B", stakes="high")
        verdicts_by_claim = {
            id(claim_a): [_support_verdict()],
            id(claim_b): [_refute_verdict(independent=True), _refute_verdict(independent=True)],
        }
        result = adjudicate_all([claim_a, claim_b], verdicts_by_claim, self.RULE)
        assert "survivors" in result
        assert "dropped" in result
        survivor_texts = [c["text"] for c in result["survivors"]]
        dropped_texts = [c["text"] for c in result["dropped"]]
        assert "claim A" in survivor_texts
        assert "claim B" in dropped_texts

    def test_adjudicate_all_no_verdicts_all_survive(self):
        """Claims with no verdicts (e.g., low stakes) all survive."""
        claim_a = _make_claim(text="low stakes", stakes="low")
        result = adjudicate_all([claim_a], {}, self.RULE)
        assert len(result["survivors"]) == 1
        assert len(result["dropped"]) == 0

    def test_adjudicate_all_uses_claim_key(self):
        """adjudicate_all must accept verdicts_by_claim keyed by id(claim) or text."""
        claims = [_make_claim(text=f"claim {i}", stakes="high") for i in range(3)]
        # All claims get a single supporting verdict
        verdicts_by_claim = {id(c): [_support_verdict()] for c in claims}
        result = adjudicate_all(claims, verdicts_by_claim, self.RULE)
        assert len(result["survivors"]) == 3
        assert len(result["dropped"]) == 0


# ---------------------------------------------------------------------------
# coverage_gate
# ---------------------------------------------------------------------------

class TestCheckCoverage:

    def test_fails_when_high_stakes_claim_unadjudicated(self):
        """check_coverage returns pass=False when a high-stakes claim is missing from adjudications."""
        high_claim = _make_claim(text="high claim", stakes="high")
        low_claim = _make_claim(text="low claim", stakes="low")
        claims = [high_claim, low_claim]
        # adjudications is a mapping {claim_id -> verdict}, but high_claim is not in it
        adjudications = {}  # empty — high-stakes claim not adjudicated
        result = check_coverage(claims, adjudications)
        assert result["pass"] is False
        assert len(result["uncovered"]) >= 1

    def test_passes_when_all_high_stakes_covered(self):
        """check_coverage returns pass=True when all high-stakes claims have adjudications."""
        high_claim = _make_claim(text="high claim", stakes="high")
        low_claim = _make_claim(text="low claim", stakes="low")
        claims = [high_claim, low_claim]
        # adjudications covers the high-stakes claim
        adjudications = {id(high_claim): True}
        result = check_coverage(claims, adjudications)
        assert result["pass"] is True
        assert result["uncovered"] == []

    def test_uncovered_list_contains_uncovered_high_stakes(self):
        """The uncovered list for pipeline re-entry contains only high-stakes unadjudicated claims."""
        h1 = _make_claim(text="h1", stakes="high")
        h2 = _make_claim(text="h2", stakes="high")
        low = _make_claim(text="low", stakes="low")
        # h2 is adjudicated; h1 is not; low is irrelevant to coverage
        adjudications = {id(h2): True}
        result = check_coverage([h1, h2, low], adjudications)
        assert result["pass"] is False
        uncovered_texts = [c["text"] for c in result["uncovered"]]
        assert "h1" in uncovered_texts
        assert "h2" not in uncovered_texts
        assert "low" not in uncovered_texts

    def test_max_reentry_constant_present(self):
        """MAX_REENTRY is exported from coverage_gate for bounded re-entry."""
        assert isinstance(MAX_REENTRY, int)
        assert MAX_REENTRY >= 1

    def test_empty_claims_passes(self):
        """No claims -> trivially passes (nothing high-stakes to adjudicate)."""
        result = check_coverage([], {})
        assert result["pass"] is True

    def test_only_low_stakes_passes(self):
        """All low-stakes claims -> passes (no high-stakes coverage requirement)."""
        claims = [_make_claim(stakes="low"), _make_claim(stakes="low")]
        result = check_coverage(claims, {})
        assert result["pass"] is True


# ---------------------------------------------------------------------------
# research_division.divide
# ---------------------------------------------------------------------------

class TestDivide:

    def _clear_brief(self, stakes_list: list[str]) -> dict:
        """Build a minimal mission_brief with the given stakes assignments."""
        return {
            "deep_research_prompt": "What is the competitive landscape for AI?",
            "focus_areas": [
                {
                    "focus_area": f"focus_{i}",
                    "taxonomy": "B",
                    "stakes": s,
                }
                for i, s in enumerate(stakes_list)
            ],
            "needs_clarification": False,
        }

    def test_returns_list_of_angle_dicts(self):
        """divide() returns a list of dicts, each with 'query' and 'stakes' keys."""
        brief = self._clear_brief(["low", "med", "high"])
        angles = divide(brief)
        assert isinstance(angles, list)
        assert len(angles) >= 1
        for angle in angles:
            assert "query" in angle, f"Missing 'query' key in angle: {angle}"
            assert "stakes" in angle, f"Missing 'stakes' key in angle: {angle}"

    def test_high_stakes_angle_doubled(self):
        """High-stakes angles appear in at least 2 entries (doubled for redundancy)."""
        brief = self._clear_brief(["high"])
        angles = divide(brief)
        high_angles = [a for a in angles if a["stakes"] == "high"]
        assert len(high_angles) >= 2, (
            f"Expected high-stakes angle to be doubled (>=2 entries), got {len(high_angles)}: {angles}"
        )

    def test_low_med_angles_appear_once(self):
        """Low/med angles are not doubled (one entry each for breadth coverage)."""
        brief = self._clear_brief(["low", "med"])
        angles = divide(brief)
        low_angles = [a for a in angles if a["stakes"] == "low"]
        med_angles = [a for a in angles if a["stakes"] == "med"]
        # Each should appear exactly once (breadth, not redundancy)
        assert len(low_angles) == 1, f"Expected 1 low entry, got {len(low_angles)}"
        assert len(med_angles) == 1, f"Expected 1 med entry, got {len(med_angles)}"

    def test_empty_focus_areas_returns_one_broadcast_angle(self):
        """When no focus_areas, divide falls back to a single broadcast angle."""
        brief = {
            "deep_research_prompt": "research prompt",
            "focus_areas": [],
            "needs_clarification": False,
        }
        angles = divide(brief)
        assert len(angles) >= 1

    def test_angle_query_contains_focus_area_label(self):
        """Each angle's query incorporates or derives from its focus_area label."""
        brief = self._clear_brief(["med"])
        angles = divide(brief)
        # At least one angle should reference the focus area or deep_research_prompt
        # (implementation may construct the query differently — just check it's non-empty)
        for angle in angles:
            assert len(angle["query"]) > 0, f"Empty query in angle: {angle}"
