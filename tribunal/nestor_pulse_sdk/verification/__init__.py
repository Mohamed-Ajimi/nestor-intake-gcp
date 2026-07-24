"""
nestor_pulse_sdk.verification -- operator-facing verification read surfaces (Phase 15 ENGINE-09).

Shapes the persisted per-claim verdicts (`verification_verdict`) + the run-level
funnel (`run.verification_summary`) + true cost (`run.cost_usd_total` /
`run.cost_pending`) into the STAKEHOLDER-NOTES §2026-07-24 verification-report
content. Reads ONLY persisted rows -- it NEVER re-parses GCS audit blobs.

Public API:
  - shape_verification_report(...)  : pure shaper over already-fetched rows (no DB).
  - build_verification_report(...)  : async DB-facing wrapper (fetches rows, then shapes).
"""

from nestor_pulse_sdk.verification.report import (
    build_verification_report,
    shape_verification_report,
)

__all__ = [
    "build_verification_report",
    "shape_verification_report",
]
