"""
Recorded tribunal run 4cbb5311 (2026-07-22) fixture package.

Reconstructs the run from its COMMITTED extracts under
`docs/tribunal-run-reports/run-20260722-4cbb5311/` -- no GCS dependency.

Public API:
  - load_recorded_run(session, tenant_id) -> Run   (loader.py)
  - load_selection_experiment()           -> tuple (loader.py)
  - extract_group_verdicts(calls_dir)     -> list  (verdict_extract.py)
  - RECORDED_FUNNEL_COUNTS                 -> dict  (loader.py)
"""

from nestor_pulse_sdk.tests.fixtures.run_4cbb5311.loader import (
    RECORDED_AUDIT_BUCKET,
    RECORDED_FUNNEL_COUNTS,
    RECORDED_GCS_RUN_ID,
    build_stage_detail,
    build_verification_summary,
    load_recorded_run,
    load_selection_experiment,
)
from nestor_pulse_sdk.tests.fixtures.run_4cbb5311.verdict_extract import (
    extract_group_verdicts,
)

__all__ = [
    "load_recorded_run",
    "load_selection_experiment",
    "extract_group_verdicts",
    "build_stage_detail",
    "build_verification_summary",
    "RECORDED_FUNNEL_COUNTS",
    "RECORDED_GCS_RUN_ID",
    "RECORDED_AUDIT_BUCKET",
]
