"""Tribunal adjudication — Plan 01-15 Task 1.

Applies the Plan 01-14 locked survival rule to each claim's skeptic verdicts.

Locked survival rule (ADR-006 Task-1, Plan 01-14):
  NESTOR_TRIBUNAL_SURVIVAL_RULE = majority-independent

  majority-independent:
    A claim DROPS if AND ONLY IF:
      (a) a MAJORITY of skeptic verdicts are "refute" (> 50%), AND
      (b) AT LEAST ONE refuting verdict cites an independent source
          (evidence_refs or has_independent_source flag).

    Otherwise the claim SURVIVES.

    Special cases:
      - 0 skeptics (low stakes or budget-skipped): claim waves through (survives).
      - All insufficient: no refutation -> claim survives.
      - Single refute with independent source: 1 of N (N>=2) — NOT a majority
        unless N==1, in which case 1 of 1 IS a majority.

The module also exports adjudicate_all() which processes a full claims list
and returns {survivors, dropped} dicts for the pipeline.

Import path: nestor_pulse_sdk.pipeline.tribunal.adjudicate
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Survival rule constant (locked; overridable via env for A/B experiments)
# ---------------------------------------------------------------------------
SURVIVAL_RULE: str = os.environ.get(
    "NESTOR_TRIBUNAL_SURVIVAL_RULE", "majority-independent"
)


# ---------------------------------------------------------------------------
# Core adjudication logic
# ---------------------------------------------------------------------------


def _has_independent_source(verdict: dict[str, Any]) -> bool:
    """Return True if the verdict cites at least one independent source.

    Checks:
      - verdict["has_independent_source"] (explicit flag)
      - verdict["evidence_refs"] non-empty list
      - verdict["citations"] non-empty list
    """
    if verdict.get("has_independent_source"):
        return True
    if verdict.get("evidence_refs"):
        return True
    if verdict.get("citations"):
        return True
    return False


def adjudicate(
    claim: dict[str, Any],
    verdicts: list[dict[str, Any]],
    survival_rule: str = SURVIVAL_RULE,
) -> bool:
    """Determine whether a claim survives the Tribunal adjudication.

    Args:
        claim:         Claim dict with at least {"text", "stakes"} keys.
        verdicts:      List of verdict dicts from run_skeptic() calls.
                       Each: {"verdict": "support"|"refute"|"insufficient",
                              "evidence_refs": [...], "has_independent_source": bool, ...}
        survival_rule: Adjudication rule name. Only "majority-independent" is
                       supported in Phase 1. Unknown rules default to this.

    Returns:
        True  -> claim survives (include in synthesis)
        False -> claim is dropped (exclude from synthesis)
    """
    # 0-skeptic path: low-stakes or budget-skipped — always wave through
    if not verdicts:
        log.debug("adjudicate: 0 skeptics -> claim waves through (text=%r)", claim.get("text", "")[:60])
        return True

    if survival_rule != "majority-independent":
        log.warning(
            "adjudicate: unknown survival_rule %r — defaulting to majority-independent",
            survival_rule,
        )

    # Count refuting verdicts and check if any cite an independent source
    n_total = len(verdicts)
    refuters = [v for v in verdicts if v.get("verdict") == "refute"]
    n_refute = len(refuters)

    # Majority = strictly more than half
    is_majority_refute = n_refute > n_total / 2

    if not is_majority_refute:
        log.debug(
            "adjudicate: %d/%d refute — not majority -> claim survives (text=%r)",
            n_refute, n_total, claim.get("text", "")[:60],
        )
        return True

    # Majority refute — check for at least one independent source citation
    has_independent = any(_has_independent_source(v) for v in refuters)

    if has_independent:
        log.info(
            "adjudicate: majority refute (%d/%d) + independent source -> claim DROPPED (text=%r)",
            n_refute, n_total, claim.get("text", "")[:60],
        )
        return False

    # Majority refute but NO independent source -> per the locked rule, the claim
    # survives. ADR-006: "refuting REQUIRES an independent source."
    log.info(
        "adjudicate: majority refute (%d/%d) but NO independent source -> claim SURVIVES (text=%r)",
        n_refute, n_total, claim.get("text", "")[:60],
    )
    return True


def adjudicate_all(
    claims: list[dict[str, Any]],
    verdicts_by_claim: dict[int, list[dict[str, Any]]],
    survival_rule: str = SURVIVAL_RULE,
) -> dict[str, list[dict[str, Any]]]:
    """Adjudicate all claims and partition into survivors + dropped.

    Args:
        claims:           Full list of claim dicts (from claim_distiller output).
        verdicts_by_claim: Mapping of id(claim) -> list of verdict dicts.
                           Claims absent from the mapping (e.g., low-stakes with
                           0 skeptics) are treated as having 0 verdicts.
        survival_rule:    Adjudication rule name.

    Returns:
        {"survivors": [...], "dropped": [...]}
        Both lists carry the original claim dicts.
    """
    survivors: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []

    for claim in claims:
        claim_id = id(claim)
        verdicts = verdicts_by_claim.get(claim_id, [])
        survived = adjudicate(claim, verdicts, survival_rule)
        if survived:
            survivors.append(claim)
        else:
            dropped.append(claim)

    log.info(
        "adjudicate_all: %d claims -> %d survivors / %d dropped",
        len(claims), len(survivors), len(dropped),
    )
    return {"survivors": survivors, "dropped": dropped}
