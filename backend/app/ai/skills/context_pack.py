"""``generate-context-pack`` ported to a space-scoped background task (AI-02).

SIGNATURE SCAFFOLD (07-05 Task 1): this module's function signature is fixed here so the
route surface (``ai_routes.py``) imports cleanly and dispatches the background task; the
full implementation lands in Task 3 of this same plan (turns ``test_ai_context_pack.py``
GREEN).

Grep-guard: this module will construct NO database engines or sessions — the real impl runs
through ``app.db.ai_session.run_with_session_release`` + the repository wall.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def run_context_pack(identity: Identity, intake_id: Any, run_id: Any) -> Any:
    """Generate the context pack and finalize the artifact + intake + run (AI-02).

    Implemented in Task 3: CALL Claude (``claude-sonnet-4-5``) for the briefing markdown,
    then WRITE a ``research_artifacts`` row (``text_content`` + ``embed_status='pending'``),
    bump the intake to ``decomposed`` + ``context_pack_artifact_id``, and finalize the run
    (``succeeded`` + ``applied_at``). No object-store call (Phase 9 deferral).
    """
    raise NotImplementedError("run_context_pack is implemented in 07-05 Task 3")
