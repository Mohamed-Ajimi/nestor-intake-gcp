"""nestor_pulse_sdk.pipeline.tribunal — Tribunal adaptive-effort SDK engine.

ADR-006: the Phase-1 SDK engine with adaptive stages:
  1. Intake (this plan, 01-13) — clarify-when-vague + stakes-tagged focus_areas
  2. Research — hybrid division across 3 providers (Plan 01-14)
  3. Verification — per-claim skeptic loops (Plan 01-14)
  4. Gate — coverage + quality (Plan 01-15)

Ships behind NESTOR_SDK_ORCHESTRATOR=tribunal in runs/adapter.py.
"""

from nestor_pulse_sdk.pipeline.tribunal.intake import adaptive_intake
from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY, STAKES_TIERS

__all__ = [
    "adaptive_intake",
    "TAXONOMY",
    "STAKES_TIERS",
]
