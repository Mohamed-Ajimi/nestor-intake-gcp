"""Tribunal taxonomy constants.

A/B/C/D stakes taxonomy (mirrors the ADK focus-area taxonomy referenced in ADR-006):
  A = Customer   — audience, sentiment, buyer behaviour
  B = Competitor — competitor landscape, strategies, share
  C = Trend      — market trends, macro signals, tech adoption
  D = Strategy   — strategic positioning, M&A, partnerships, internal moves

STAKES_TIERS drives per-claim verification depth in the Tribunal skeptic (Plan 01-14):
  low  → wave through (no skeptic allocated)
  med  → 2 skeptics
  high → 3 skeptics
"""

from __future__ import annotations

# ADR-006 §Decision stage 1 — the four taxonomy codes.
TAXONOMY: dict[str, str] = {
    "A": "Customer",
    "B": "Competitor",
    "C": "Trend",
    "D": "Strategy",
}

# Valid stakes tier labels consumed by triage (Plan 01-14) and audit notes.
STAKES_TIERS: tuple[str, ...] = ("low", "med", "high")
