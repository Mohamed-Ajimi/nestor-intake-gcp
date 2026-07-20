"""
Quality gate package — ADR-005 ACCEPT WITH FLAG implementation.

Public surface:
  - QualityGate (Protocol): the contract Plan 09 calls.
  - Verdict: rich return type with pass_, per_dim_scores, fixes, weighted_avg.
  - ExistingHeuristicGate: deterministic structural script (port of steps.py).
  - LLMJudgeGate: homegrown reverse-engineered Outcomes (per-dim CoT rubric).
  - build_quality_gate(): env-flag-keyed factory.

Selection:
  NESTOR_QUALITY_GATE=existing  (default) -> ExistingHeuristicGate (free, instant)
  NESTOR_QUALITY_GATE=outcomes            -> LLMJudgeGate (~$0.01 + ~12s/brief)

Plan 09 contract:
    from nestor_pulse_sdk.pipeline.synthesis.quality_gate import build_quality_gate
    gate = build_quality_gate()
    verdict = await gate.grade(
        synthesis=...,
        mission_brief=...,
        focus_areas=...,
        audited=audited_llm_client,  # REQUIRED for LLMJudgeGate
        run_id=...,
        tenant_id=...,
    )

ADK pipeline (D-01): does NOT consume this package; it keeps its own
`nestor_pulse/synthesis_pipeline/steps.py::quality_gate` function untouched.
"""

from __future__ import annotations

import os
import logging

from .protocol import QualityGate, Verdict
from .existing_heuristic import ExistingHeuristicGate
from .llm_judge import LLMJudgeGate, Rubric, RubricDimension, load_rubric, DEFAULT_RUBRIC_PATH

log = logging.getLogger(__name__)


_VALID_FLAGS = {"existing", "outcomes"}


def build_quality_gate(flag: str | None = None) -> QualityGate:
    """
    Factory: select the QualityGate implementation per env flag.

    Args:
      flag: optional override of the NESTOR_QUALITY_GATE env var. Used in tests.

    Returns:
      A QualityGate implementation (ExistingHeuristicGate or LLMJudgeGate).

    Behavior:
      - Default: "existing"
      - Unknown flag value -> log warning, fall back to "existing"
    """
    resolved = flag if flag is not None else os.environ.get("NESTOR_QUALITY_GATE", "existing")
    resolved_lower = resolved.lower().strip()

    if resolved_lower not in _VALID_FLAGS:
        log.warning(
            "[build_quality_gate] unknown NESTOR_QUALITY_GATE=%r; falling back to 'existing'",
            resolved,
        )
        resolved_lower = "existing"

    if resolved_lower == "outcomes":
        log.info("[build_quality_gate] LLMJudgeGate selected (NESTOR_QUALITY_GATE=outcomes)")
        return LLMJudgeGate()

    log.info("[build_quality_gate] ExistingHeuristicGate selected (default / NESTOR_QUALITY_GATE=existing)")
    return ExistingHeuristicGate()


__all__ = [
    "QualityGate",
    "Verdict",
    "ExistingHeuristicGate",
    "LLMJudgeGate",
    "Rubric",
    "RubricDimension",
    "load_rubric",
    "DEFAULT_RUBRIC_PATH",
    "build_quality_gate",
]
