"""The intake side's ONE copy of the Tribunal run-status vocabulary (D-09/D-12).

Four things a reader needs to know before touching this file:

1. **These literals are the Tribunal run-status contract, carried VERBATIM across
   the seam (the D-05 boundary).** They are NEVER the skill-run
   ``{"succeeded", "failed"}`` vocabulary (16-RESEARCH Pitfall 3). A successful
   Tribunal run is ``completed`` and must never be remapped to a skill-run literal.

2. **``completed_degraded`` gets everything ``completed`` gets** — the completion
   bundle, the report row, the raw-output download and the completion mail
   (D-09/G-10). A run whose output fell short is still a ~$45 deliverable the
   operator paid for; the degradation is NAMED in the verification report, never
   enforced as a denial. That is why :func:`is_research_success` exists rather
   than a bare ``== "completed"`` comparison at each site.

3. **``parked`` is deliberately absent from BOTH sets.** The poll driver must keep
   polling a resumable run, and the Resume button, the ``render_research_parked``
   mail and F-02's free-resume rule are **plan 15.2-16's** work. Adding ``parked``
   to a terminal set before that lands would ship a dead-end state: a run that
   stops polling with no way for the operator to move it forward.

4. **The tribunal-side source of truth is** ``nestor_pulse_sdk/runs/schemas.py`` --
   its ``RunStatus`` Literal and its ``report_readable`` / ``bundle_readable``
   predicates. Keep the two in sync; this module is the mirror, not the origin.

This module is intentionally dependency-free: no SQLAlchemy, no FastAPI, no
settings. It is imported by both ``app/research/run_task.py`` (the poll driver)
and ``app/api/research_routes.py`` (the SSE handler + the download gate), which
each used to carry their own literal set.
"""

from __future__ import annotations

#: Terminal states in which the run produced a report the operator may have.
#: ``completed_degraded`` is here BY DESIGN (D-09) — see point 2 above.
RESEARCH_SUCCESS = frozenset({"completed", "completed_degraded"})

#: Every terminal state the intake side stops polling / closes a stream on.
#: ``parked`` is deliberately NOT a member — see point 3 above.
RESEARCH_TERMINAL = RESEARCH_SUCCESS | frozenset({"failed", "cancelled"})


def is_research_success(status: str | None) -> bool:
    """Did this run finish with a deliverable in hand?

    Tolerates ``None`` (``metrics.get("status")`` can be absent) and returns
    ``False`` for it — an unknown status is never treated as a success.
    """
    return status in RESEARCH_SUCCESS


def is_research_terminal(status: str | None) -> bool:
    """Has this run stopped moving? Tolerates ``None`` and returns ``False``."""
    return status in RESEARCH_TERMINAL
