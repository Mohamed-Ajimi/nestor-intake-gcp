"""Tribunal stakes triage — Plan 01-14 Task 2.

Per-claim stakes triage allocates skeptics by tier:
  low  -> 0 skeptics (wave through)
  med  -> 2 skeptics
  high -> 3 skeptics

ADR-006 §Decision stage 3: adaptive effort — concentrate verification compute
only where a claim's stakes justify the cost tax.

Unknown tiers (not in low/med/high) default to med behaviour (2 skeptics) with
a warning log — never crash on unexpected LLM output.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Stakes tier -> skeptic count mapping (ADR-006 defaults, Task-1 confirmed)
_STAKES_TO_SKEPTICS: dict[str, int] = {
    "low": 0,
    "med": 2,
    "high": 3,
}

# Default when tier is not recognised — med behaviour (Task-1: majority-independent rule)
_DEFAULT_SKEPTICS = 2


def skeptics_for(stakes: str) -> int:
    """Return the number of skeptics to allocate for a given stakes tier.

    Args:
        stakes: Tier string — one of "low", "med", "high".
                Unknown values default to "med" behaviour (2) with a warning.

    Returns:
        Number of skeptics (0, 2, or 3).
    """
    if stakes in _STAKES_TO_SKEPTICS:
        return _STAKES_TO_SKEPTICS[stakes]
    log.warning(
        "triage: unknown stakes tier %r — defaulting to med behaviour (%d skeptics)",
        stakes,
        _DEFAULT_SKEPTICS,
    )
    return _DEFAULT_SKEPTICS


def triage_claims(
    claims: list[dict[str, Any]],
) -> list[tuple[dict[str, Any], int]]:
    """Allocate skeptic counts for each claim based on its stakes tier.

    Reads each claim's 'stakes' key. Falls back to unknown-tier default (2)
    if the key is absent or its value is not a valid tier — never raises.

    Args:
        claims: List of claim dicts, each expected to have a 'stakes' key.

    Returns:
        List of (claim_dict, n_skeptics) tuples in the same order as input.
    """
    result: list[tuple[dict[str, Any], int]] = []
    for claim in claims:
        stakes = claim.get("stakes", "")
        n = skeptics_for(stakes) if stakes else skeptics_for("__missing__")
        result.append((claim, n))
    return result
