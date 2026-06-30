"""``apply-intake-skill`` ported to a space-scoped background task (AI-01).

SIGNATURE SCAFFOLD (07-05 Task 1): this module's function signature is fixed here so the
route surface (``ai_routes.py``) imports cleanly and dispatches the background task; the
full implementation lands in Task 2 of this same plan (turns ``test_ai_apply_skill.py`` and
``test_ai_status_contract.py`` GREEN).

Grep-guard: this module will construct NO database engines or sessions — the real impl runs
through ``app.db.ai_session.run_with_session_release`` + the repository wall.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def run_apply_intake_skill(identity: Identity, intake_id: Any, run_id: Any) -> Any:
    """Run apply-intake-skill as the WRITE half of the AI-06 release contract (AI-01).

    Implemented in Task 2: READ the intake + answers into a plain DTO, CALL Claude
    (``claude-sonnet-4-5``, ``max_tokens=8192``) holding no connection, then WRITE the
    parsed ``output_parsed`` + terminal ``succeeded`` / ``failed`` status (D-09).
    """
    raise NotImplementedError("run_apply_intake_skill is implemented in 07-05 Task 2")
