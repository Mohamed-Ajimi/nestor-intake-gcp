"""``extract-insights`` port — SIGNATURE STUB (AI-03).

The route surface (07-05) fixes this function's signature so ``ai_routes.py`` imports
cleanly and dispatches the background task today; the real Claude (``claude-sonnet-4-6``)
implementation lands in plan 07-07 (``test_ai_structure_extract.py`` is RED until then).
This stub raises ``NotImplementedError`` so the import is real and the contract is visible,
while the body is deliberately left for 07-07.

Grep-guard: constructs NO engine/session — the real impl writes via
``run_with_session_release`` + ``ExtractedInsightRepository``.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def run_extract_insights(identity: Identity, intake_id: Any, run_id: Any) -> Any:
    """Distil ``extracted_insights`` rows from an intake's transcripts/answers (AI-03).

    Filled in 07-07: read the transcript chunks / answers, call Claude
    (``claude-sonnet-4-6``) returning a JSON array of insights, validate each ``kind``
    against ``INSIGHT_KINDS``, and write space-scoped ``extracted_insights`` rows.
    """
    raise NotImplementedError("run_extract_insights is implemented in plan 07-07")
