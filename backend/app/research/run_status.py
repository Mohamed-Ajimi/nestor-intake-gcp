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

3. **``parked`` is TERMINAL here, and only for the STREAM — never for the RUN.**
   15.2-09 deliberately left ``parked`` out of every terminal set because shipping
   it before a Resume affordance existed would have been a dead end. 15.2-16 built
   the engine half (checkpoints, the park sequence, ``POST /api/runs/{id}/resume``)
   and plan **15.2-19** ships the operator half (the park mail + the Resume verb +
   the Resume card), so the deferral is now closed and ``parked`` is a member of
   :data:`RESEARCH_TERMINAL`.

   Why terminal, against 15.2-RESEARCH § R4's "not terminal for the poll driver"
   (DEC-3, recorded as a deliberate deviation): ``run_poll_driver`` is a FastAPI
   ``BackgroundTask`` and a parked run waits on a HUMAN click that may be hours
   away. A driver that keeps polling is a leaked task pinning a Cloud Run instance,
   and the SSE handler would burn to its 10-minute ``MAX_STREAM_SECONDS`` cap and
   drop the browser into its reconnect loop. So the stream and the driver stop; the
   RUN does not end. A superadmin resume re-queues the SAME engine run and schedules
   a FRESH driver.

   ``parked`` is NOT in :data:`RESEARCH_SUCCESS` and :func:`is_research_success`
   must never return True for it — a parked run has no bundle, no report and no
   chain verdict. Keep the three states distinct: losing 1-2 of 4 streams is
   ``completed_degraded`` (a real deliverable); a D-14 distiller fallback is normal
   operation and changes no status at all; ``parked`` is only a hard wall.

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
#: ``parked`` IS a member (15.2-19 / DEC-3) — terminal for the STREAM, not the RUN.
#: Built from RESEARCH_SUCCESS so that set stays untouched: a parked run is not a
#: success and never gets the bundle / report / download.
RESEARCH_TERMINAL = RESEARCH_SUCCESS | frozenset({"failed", "cancelled", "parked"})


def is_research_success(status: str | None) -> bool:
    """Did this run finish with a deliverable in hand?

    Tolerates ``None`` (``metrics.get("status")`` can be absent) and returns
    ``False`` for it — an unknown status is never treated as a success. ``parked``
    is deliberately False here: a paused run has nothing to hand over yet.
    """
    return status in RESEARCH_SUCCESS


def is_research_parked(status: str | None) -> bool:
    """Is this run PAUSED awaiting a superadmin resume? Tolerates ``None`` -> ``False``.

    Distinct from both failure and degradation: a parked run hit a wall it cannot
    pass on its own (every stream lost, or a hard billing / monthly-cap wall) and
    stopped with its paid work checkpointed. It is resumed for free by
    ``POST /intakes/{intake_id}/research/resume`` (F-01/F-02), never retried as a
    fresh attempt.
    """
    return status == "parked"


def is_research_terminal(status: str | None) -> bool:
    """Has this run stopped moving? Tolerates ``None`` and returns ``False``."""
    return status in RESEARCH_TERMINAL
