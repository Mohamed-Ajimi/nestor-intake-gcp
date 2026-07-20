"""
ExistingHeuristicGate — port of nestor_pulse/synthesis_pipeline/steps.py::quality_gate.

This is the structural script that the ADK pipeline currently uses (and continues
to use unchanged per D-01). The SDK pipeline calls this version when
NESTOR_QUALITY_GATE != "outcomes".

No LLM. No external dependencies. Zero cost, sub-millisecond latency.

Three checks (verbatim from steps.py lines 697-736):
  1. Minimum length: 300 words or FAIL immediately.
  2. Section structure: at least 3 markdown headers OR feedback issue.
  3. Bullet ratio: ≤75% bullet lines OR feedback issue.

Verdict rules:
  - 0 issues + ≥300 words           → pass
  - 1 issue  + ≥400 words           → iterate
  - 1 issue  + 300-399 words        → fail
  - 2+ issues                       → fail
  - <300 words                      → fail (immediate)
"""

from __future__ import annotations

import re
from typing import Optional, Any

from .protocol import Verdict


class ExistingHeuristicGate:
    """Deterministic structural quality check. No LLM. Free + instant."""

    name = "existing"

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
        """Run the three structural checks. `audited`/`run_id`/`tenant_id` are ignored."""
        legacy_verdict, legacy_feedback = self._check(synthesis)

        pass_ = legacy_verdict == "pass"
        # The heuristic gate doesn't produce per-dimension scores; we expose a single
        # synthetic "structural" score for callers that want a numeric signal.
        structural_score = 5.0 if pass_ else (3.0 if legacy_verdict == "iterate" else 1.0)
        per_dim = {"structural": structural_score}

        fixes: list[str] = []
        if legacy_feedback:
            fixes.append(legacy_feedback)

        return Verdict(
            pass_=pass_,
            per_dim_scores=per_dim,
            fixes=fixes,
            weighted_avg=structural_score,
            legacy_verdict=legacy_verdict,
            legacy_feedback=legacy_feedback,
            raw={"gate": "existing_heuristic", "checks_run": 3},
        )

    # -----------------------------------------------------------------------
    # Pure structural check (no async needed; broken out for testability)
    # -----------------------------------------------------------------------

    @staticmethod
    def _check(synthesis: str) -> tuple[str, str]:
        """Return (verdict, feedback) matching steps.py:quality_gate exactly."""
        issues: list[str] = []

        # Check 1: minimum length
        word_count = len(synthesis.split())
        if word_count < 300:
            return "fail", f"Too short: {word_count} words (minimum 300)"

        # Check 2: has section structure (at least 3 markdown headers)
        headers = re.findall(r'^#{1,6}\s+.+', synthesis, re.MULTILINE)
        if len(headers) < 3:
            issues.append(
                f"Insufficient structure: only {len(headers)} section headers (need at least 3)"
            )

        # Check 3: not purely bullet points (needs narrative prose)
        non_empty_lines = [l.strip() for l in synthesis.split('\n') if l.strip()]
        bullet_lines = sum(1 for l in non_empty_lines if l.startswith(('-', '*', '•')))
        if non_empty_lines and (bullet_lines / len(non_empty_lines)) > 0.75:
            issues.append("Too many bullet points — needs more narrative prose")

        if not issues:
            return "pass", ""

        feedback = " | ".join(issues)
        verdict = "iterate" if (word_count >= 400 and len(issues) == 1) else "fail"
        return verdict, feedback
