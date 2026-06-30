"""``structure-answers`` port — SIGNATURE STUB (AI-03).

The route surface (07-05) fixes this function's signature so ``ai_routes.py`` imports
cleanly and dispatches the background task today; the real Claude (``claude-sonnet-4-6``)
implementation lands in plan 07-07 (``test_ai_structure_extract.py`` is RED until then).
This stub raises ``NotImplementedError`` so the import is real and the contract is visible,
while the body is deliberately left for 07-07.

Grep-guard: constructs NO engine/session — the real impl writes via
``run_with_session_release`` + ``IntakeAnswerRepository.upsert_extracted`` (extracted_by='llm').
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def run_structure_answers(identity: Identity, intake_id: Any, run_id: Any) -> Any:
    """Map a transcript into ``intake_answers`` rows (``extracted_by='llm'``, scoped) (AI-03).

    Filled in 07-07: read the transcript chunks, call Claude
    (``claude-sonnet-4-6``) returning a JSON array, parse it with ``extract_json_array``,
    and upsert the space-scoped ``intake_answers`` rows respecting the
    ``(intake_id, field_key)`` unique constraint.
    """
    raise NotImplementedError("run_structure_answers is implemented in plan 07-07")
