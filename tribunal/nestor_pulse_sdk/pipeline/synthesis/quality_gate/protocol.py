"""
QualityGate Protocol — the contract Plan 09's synthesis pipeline calls.

Verdict is the rich return type that supports both the existing pass/iterate/fail
verdict shape (for backwards compatibility) and the new per-dimension scoring +
fix suggestions returned by the LLM judge.

Design notes:
  - Verdict.pass_ is the binary "good enough" signal Plan 09's synthesis loop
    uses to decide whether to iterate. (`pass_` not `pass` — `pass` is a Python
    keyword.)
  - Verdict.per_dim_scores is dict[dimension_id, 1.0–5.0 score] for ENABLED
    dimensions only. Disabled dimensions are NOT included (don't appear in the
    dict at all). This lets the verdict serializer drop them cleanly.
  - Verdict.weighted_avg is computed over enabled dimensions, with weights
    renormalized so they sum to 1.0 (so disabling dimensions doesn't drop the
    achievable max).
  - Verdict.fixes is freeform per-dimension feedback for Phase 1. Plan 09 owns
    the structured retry-loop wiring; for now this is a list of human-readable
    strings the synthesizer can include in the next iteration's prompt.
  - Verdict.legacy_verdict + Verdict.legacy_feedback preserve the existing
    "pass"|"iterate"|"fail" shape so the ADK pipeline can keep using its own
    QualityGate (D-01) and the SDK pipeline can fall back to the heuristic gate
    without code changes upstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable, Optional, Any


@dataclass
class Verdict:
    """Result of running a QualityGate against a synthesis brief."""

    pass_: bool
    """Binary 'good enough' signal. True = passes; False = needs iteration or fails."""

    per_dim_scores: dict[str, float] = field(default_factory=dict)
    """Per-dimension scores 1.0..5.0 for ENABLED dimensions only."""

    fixes: list[str] = field(default_factory=list)
    """Freeform per-dimension feedback strings; empty if no improvements suggested."""

    weighted_avg: float = 0.0
    """Weighted average of per-dim scores, weights renormalised over enabled dims."""

    legacy_verdict: str = "pass"
    """Legacy 'pass'|'iterate'|'fail' verdict for ADK pipeline compatibility."""

    legacy_feedback: str = ""
    """Legacy single-string feedback for ADK pipeline compatibility."""

    raw: dict[str, Any] = field(default_factory=dict)
    """Raw judge response payload for debugging / auditability."""

    def as_dict(self) -> dict[str, Any]:
        """Serialise to a dict — convenient for logging or persistence."""
        return {
            "pass": self.pass_,
            "per_dim_scores": self.per_dim_scores,
            "fixes": self.fixes,
            "weighted_avg": self.weighted_avg,
            "legacy_verdict": self.legacy_verdict,
            "legacy_feedback": self.legacy_feedback,
        }


@runtime_checkable
class QualityGate(Protocol):
    """Protocol for synthesis quality grading.

    Both `ExistingHeuristicGate` and `LLMJudgeGate` implement this.
    Plan 09 selects between them via `build_quality_gate()` factory.
    """

    async def grade(
        self,
        *,
        synthesis: str,
        mission_brief: Optional[dict] = None,
        focus_areas: Optional[list[str]] = None,
        audited: Optional[Any] = None,
        run_id: Optional[Any] = None,
        tenant_id: Optional[Any] = None,
    ) -> Verdict:
        """
        Grade a synthesis brief.

        Args:
          synthesis:     The synthesized brief text (markdown).
          mission_brief: Optional dict; LLMJudgeGate may use focus_areas + topic.
          focus_areas:   Optional list of focus area strings.
          audited:       Optional AuditedLLMClient (Plan 07) for grading calls.
                         REQUIRED for LLMJudgeGate; ignored by ExistingHeuristicGate.
          run_id:        UUID for audit row linkage. REQUIRED for LLMJudgeGate.
          tenant_id:     UUID for audit row tenant column. REQUIRED for LLMJudgeGate.

        Returns:
          Verdict with pass_, per_dim_scores, weighted_avg, fixes, legacy_*.
        """
        ...
