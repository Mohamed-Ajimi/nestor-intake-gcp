"""
Pipeline stage schemas + the set_stage progress writer (migration 0006).

WHY: the UI shows which stage each engine is in while a brief runs — a green
check per finished stage, a marker on the current one, plus live sub-progress
inside the heavy stages. That needs (a) a canonical ORDERED stage list per
engine, shipped to the UI so it can render the whole schema up front, and
(b) a cheap way for deep-in-the-pipeline code to report "I'm here now".

The ordered schema lives HERE (not the DB). The run row stores only the current
position (run.current_stage) + per-stage sub-progress (run.stage_detail).

`stage_detail` is a MAP keyed by stage_key: `{"intake": {"items": [...]},
"research_division": {...}, "deep_research": {...}, ...}`. Each set_stage call
MERGES its stage's detail into that map (it does not overwrite the whole column),
so the intake result, the research division, and the per-angle deep-research
status all survive to the end of the run and stay visible on completed runs —
not just while their stage is the current one. The UI looks up
`stage_detail[stage.key]` per stage.

`set_stage` mirrors the worker's DB-write pattern (own session, set_tenant_context
for RLS, fast UPDATE) and is FULLY exception-safe: a progress write must never
crash or slow the pipeline it is reporting on.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Canonical per-engine stage schemas (ordered). `key` is the stable identifier
# written to run.current_stage; `label` is the human text the UI renders.
# The terminal 'done' position is implicit (current_stage == 'done').
# ---------------------------------------------------------------------------
ENGINE_STAGES: dict[str, list[dict[str, str]]] = {
    "tribunal": [
        {"key": "intake",            "label": "Adaptive intake"},
        {"key": "research_division", "label": "Research division"},
        {"key": "deep_research",     "label": "Deep research"},
        {"key": "distill",           "label": "Claim distillation"},
        # WR-03: the pipeline has been writing this key since Phase 15.1
        # (pipeline.py:536-562) while the schema never declared it — so
        # run.current_stage reported a stage RunMetrics.stages omitted, and the
        # UI rendered the raw key with no label. Declared here, between distill
        # and verify, which is where the gates actually run.
        {"key": "gate",              "label": "Verification gates"},
        {"key": "verify",            "label": "Skeptic verification"},
        {"key": "adjudicate",        "label": "Adjudication"},
        {"key": "coverage",          "label": "Coverage gate"},
        {"key": "conflict",          "label": "Conflict detection"},
        {"key": "synthesize",        "label": "Final synthesis"},
    ],
    # ADK is a multi-turn agent pipeline; stages map to its sequential agents.
    # The synthesis sub-steps cannot be instrumented (D-01: nestor_pulse/ is
    # read-only), so 'synthesize' is a single stage observed from session state.
    "adk": [
        {"key": "intake",      "label": "Intake"},
        {"key": "decompose",   "label": "Decompose question"},
        {"key": "classify",    "label": "Classify intent"},
        {"key": "research",    "label": "Parallel deep research"},
        {"key": "synthesize",  "label": "Synthesis pipeline"},
    ],
}

# Both engines share 'adk'/'sdk' naming quirks elsewhere; tribunal arm uses
# engine=='tribunal'. 'sdk' (thin SDK arm) reuses the tribunal schema if ever run.
ENGINE_STAGES["sdk"] = ENGINE_STAGES["tribunal"]


def stages_for(engine: str) -> list[dict[str, str]]:
    """Ordered stage schema for an engine ([] if unknown)."""
    return ENGINE_STAGES.get(engine, [])


async def set_stage(
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    stage_key: str,
    detail: Optional[dict[str, Any]] = None,
) -> None:
    """Record the run's current stage (+ optional sub-progress detail).

    Exception-safe: any failure is logged and swallowed. A progress write must
    never break the pipeline that is reporting it.

    Args:
        stage_key: a key from ENGINE_STAGES[engine], or 'done' when finished.
        detail:    optional {"items": [{"name", "status"}]} sub-progress for THIS
                   stage. Merged into stage_detail under stage_key (earlier stages'
                   detail is preserved). None advances current_stage only, leaving
                   any previously recorded detail intact.
    """
    try:
        from sqlalchemy import text

        from nestor_pulse_sdk.db.base import get_sessionmaker
        from nestor_pulse_sdk.db.rls import set_tenant_context

        entry = _json_or_none({stage_key: detail}) if detail is not None else None

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                if entry is None:
                    # Advance the marker only; keep accumulated per-stage detail.
                    await session.execute(
                        text("UPDATE run SET current_stage = :stage WHERE id = :id"),
                        {"stage": stage_key, "id": str(run_id)},
                    )
                else:
                    # MERGE this stage's detail into the per-stage map (|| replaces
                    # the matching top-level key, so re-reporting a stage updates it).
                    await session.execute(
                        text(
                            "UPDATE run SET current_stage = :stage, "
                            "stage_detail = COALESCE(stage_detail, '{}'::jsonb) "
                            "|| CAST(:entry AS JSONB) WHERE id = :id"
                        ),
                        {"stage": stage_key, "entry": entry, "id": str(run_id)},
                    )
    except Exception as exc:  # noqa: BLE001 — progress writes are best-effort
        log.warning("set_stage failed (run=%s stage=%s): %r", run_id, stage_key, exc)


class RunCancelled(Exception):
    """Raised inside a running pipeline when the user has cancelled the run.

    The worker treats this distinctly from a failure: it leaves the run in the
    'cancelled' state (set by the cancel endpoint) rather than marking it 'failed'.
    """


async def is_cancelled(run_id: uuid.UUID, tenant_id: uuid.UUID) -> bool:
    """Return True if the run's status is 'cancelled'.

    Best-effort and exception-safe (returns False on any error) — a cancellation
    probe must never crash the pipeline it guards. Used by the engines to stop
    early (and stop spending) once the user hits Cancel.
    """
    try:
        from sqlalchemy import text

        from nestor_pulse_sdk.db.base import get_sessionmaker
        from nestor_pulse_sdk.db.rls import set_tenant_context

        sessionmaker = get_sessionmaker()
        async with sessionmaker() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                row = (
                    await session.execute(
                        text("SELECT status FROM run WHERE id = :id"),
                        {"id": str(run_id)},
                    )
                ).first()
        return bool(row) and row[0] == "cancelled"
    except Exception as exc:  # noqa: BLE001 — probe is best-effort
        log.warning("is_cancelled probe failed (run=%s): %r", run_id, exc)
        return False


async def raise_if_cancelled(run_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
    """Raise RunCancelled if the user has cancelled the run; otherwise return."""
    if await is_cancelled(run_id, tenant_id):
        log.info("run cancelled by user — aborting pipeline (run=%s)", run_id)
        raise RunCancelled()


def _json_or_none(detail: Optional[dict[str, Any]]) -> Optional[str]:
    if detail is None:
        return None
    import json

    try:
        return json.dumps(detail)
    except Exception:  # noqa: BLE001
        return None
