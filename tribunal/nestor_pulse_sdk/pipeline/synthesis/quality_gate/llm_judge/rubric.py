"""
Rubric YAML loader for the LLM-judge quality gate.

Loads `rubrics/default.yaml` (or a caller-supplied path) into typed dataclasses.

Schema (see rubrics/default.yaml for the canonical example):
  version: int
  judge_model: str (e.g. "claude-sonnet-4-6")
  pass_threshold: float (weighted-average minimum, e.g. 3.8)
  samples: int (1 today; future: 3-5 for self-consistency)
  bias_mitigation:
    randomize_order: bool   (future flag)
    length_normalize: bool  (future flag)
  dimensions:
    - id: str
      enabled: bool
      weight: float (raw weight; we renormalise over enabled-only)
      threshold: float (per-dim minimum, e.g. 4.0)
      question: str (CoT prompt body)
      anchors:
        bad:  {score: int, example: str, why: str}
        good: {score: int, example: str, why: str}

Validation rules enforced at load time:
  - Every dimension must have id, enabled, weight, threshold, question, anchors.
  - At least one dimension must be enabled=true (else there's nothing to grade).
  - Weights sum to ≈ 1.0 in the raw rubric (sanity check; we renormalise enabled
    weights at grading time anyway).
  - pass_threshold must be in [1.0, 5.0].

Renormalisation lives in `Rubric.enabled_weights()` — keeps the raw YAML weights
intact while exposing renormalised weights at grading time. Tests cover the
"disable a 0.20-weight dim and remaining weights renormalise to sum 1.0" case.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Any

import yaml


DEFAULT_RUBRIC_PATH = (
    Path(__file__).resolve().parent.parent / "rubrics" / "default.yaml"
)


@dataclass(frozen=True)
class RubricAnchor:
    score: int
    example: str
    why: str


@dataclass(frozen=True)
class RubricDimension:
    id: str
    enabled: bool
    weight: float
    threshold: float
    question: str
    anchor_bad: RubricAnchor
    anchor_good: RubricAnchor

    @classmethod
    def from_dict(cls, d: dict) -> "RubricDimension":
        return cls(
            id=d["id"],
            enabled=bool(d.get("enabled", False)),
            weight=float(d["weight"]),
            threshold=float(d["threshold"]),
            question=d["question"],
            anchor_bad=RubricAnchor(
                score=int(d["anchors"]["bad"]["score"]),
                example=d["anchors"]["bad"]["example"],
                why=d["anchors"]["bad"]["why"],
            ),
            anchor_good=RubricAnchor(
                score=int(d["anchors"]["good"]["score"]),
                example=d["anchors"]["good"]["example"],
                why=d["anchors"]["good"]["why"],
            ),
        )


@dataclass(frozen=True)
class Rubric:
    version: int
    judge_model: str
    pass_threshold: float
    samples: int
    bias_mitigation: dict[str, bool]
    dimensions: tuple[RubricDimension, ...]

    @classmethod
    def from_dict(cls, d: dict) -> "Rubric":
        dims = tuple(
            RubricDimension.from_dict(item) for item in d["dimensions"]
        )
        rubric = cls(
            version=int(d["version"]),
            judge_model=str(d["judge_model"]),
            pass_threshold=float(d["pass_threshold"]),
            samples=int(d.get("samples", 1)),
            bias_mitigation=dict(d.get("bias_mitigation", {})),
            dimensions=dims,
        )
        rubric._validate()
        return rubric

    def _validate(self) -> None:
        if not (1.0 <= self.pass_threshold <= 5.0):
            raise ValueError(
                f"pass_threshold must be in [1.0, 5.0], got {self.pass_threshold}"
            )
        if not any(d.enabled for d in self.dimensions):
            raise ValueError(
                "At least one rubric dimension must be enabled=true"
            )
        # Sanity-check raw weights sum to ~1.0 (not strict — only warn-by-raise on
        # gross misconfiguration). Use a generous tolerance for human-edited YAML.
        total = sum(d.weight for d in self.dimensions)
        if not (0.95 <= total <= 1.05):
            raise ValueError(
                f"Raw dimension weights must sum to ~1.0 (±0.05); got {total:.3f}"
            )

    def enabled_dimensions(self) -> tuple[RubricDimension, ...]:
        """Return only the dimensions with enabled=true."""
        return tuple(d for d in self.dimensions if d.enabled)

    def enabled_weights(self) -> dict[str, float]:
        """
        Renormalise weights over enabled dimensions only so they sum to 1.0.

        Example: if 6 dims have weights [0.30, 0.25, 0.20, 0.10, 0.10, 0.05]
        and only the first two are enabled (raw sum 0.55), the renormalised
        weights are [0.545, 0.455] — preserving their relative ratio.
        """
        enabled = self.enabled_dimensions()
        raw_sum = sum(d.weight for d in enabled)
        if raw_sum == 0:
            raise ValueError("Enabled dimensions have zero total weight")
        return {d.id: d.weight / raw_sum for d in enabled}


def load_rubric(path: Optional[Path] = None) -> Rubric:
    """Load the rubric from YAML. Defaults to `rubrics/default.yaml`."""
    p = path or DEFAULT_RUBRIC_PATH
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return Rubric.from_dict(raw)
