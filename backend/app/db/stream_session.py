"""``app/db/stream_session.py`` — per-tick stateless scoped-read helpers for the SSE stream.

The SSE skill-run stream (API-04, ``intake_routes.stream_skill_runs``) must read
``skill_runs`` state from Cloud SQL on EVERY tick — no in-memory run state — so any
Cloud Run instance can serve a reconnecting client (criterion #2). This module holds the
two short scoped reads the stream handler drives, kept OUT of ``app/api/`` so the route
carries NO raw DB symbol and the ``ci_no_raw_db_access.sh`` grep-guard stays green
(``intake_routes.py`` docstring :13-17).

Both helpers REUSE :func:`app.db.ai_session.tenant_session` — the AI-06 / D-05 discipline
that opens ONE tenant-scoped transaction and re-issues ``SET LOCAL app.current_space_id``
on EVERY entry (T-7-02). Nothing here builds an engine or a sessionmaker; the connection
returns to the pool the instant each ``with`` block exits, so nothing is held between ticks
(criterion #2 statelessness; the "don't hold ``get_tenant_repo``'s one-tx across the stream"
constraint, Phase 4 D-02 / AI-06).

Two correctness invariants:

* **403 vs 404 split (D-04):** a null-space user makes :func:`tenant_session` raise
  ``PermissionError`` — this is left to PROPAGATE so the route turns it into a 403
  (default-deny). A cross-tenant / missing intake makes the scoped repo ``get`` return
  ``None`` — the route turns that into an existence-hidden 404.
* **Plain-dict rule:** :func:`read_latest_run_dict` returns a PLAIN dict shaped exactly
  like ``SkillRunView`` (``id``/``status``/``applied_at``/``completed_at``), NEVER a live
  ORM row — a row from tick N's session is detached in tick N+1
  (``DetachedInstanceError``, the ``run_with_session_release`` READ-phase rule). The dict
  IS the D-05 wire shape → the frontend's ``toActiveSkillRun`` maps it unchanged.

``status`` is carried VERBATIM (Pitfall 1) — no remap, so the phase machine and the
terminal-set check see the exact DB literal.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select

from app.auth.identity import Identity
from app.db.ai_session import tenant_session
from app.db.models.research import Decomposition, ResearchArtifact, ResearchQuestion
from app.db.repository import (
    IntakeRepository,
    ResearchRunRepository,
    SkillRunRepository,
)


def check_intake_in_scope(identity: Identity, intake_id: Any) -> bool:
    """Existence-hidden pre-flight (D-04): is ``intake_id`` visible to this identity?

    Opens a fresh :func:`tenant_session` and returns whether the scoped
    :meth:`IntakeRepository.get` finds the intake. ``False`` → the route raises an
    existence-hidden 404 BEFORE any stream opens (so the cross-tenant denial test is a
    plain GET). A null-space user makes :func:`tenant_session` raise ``PermissionError``
    — deliberately NOT caught here; the route maps it to a 403 (default-deny).
    """
    with tenant_session(identity) as session:
        return IntakeRepository(session, identity).get(intake_id) is not None


def read_latest_run_dict(identity: Identity, intake_id: Any) -> dict | None:
    """One short scoped tx per tick → the latest run as a PLAIN ``SkillRunView`` dict.

    Returns ``None`` when the intake has no runs yet (the stream then emits ``data: null``,
    Open Question 2). Otherwise returns a plain dict (never a live ORM row — it would
    detach across ticks) whose four keys ARE the D-05 wire shape. The connection returns to
    the pool on block exit — nothing held between ticks (criterion #2).
    """
    with tenant_session(identity) as session:
        run = SkillRunRepository(session, identity).latest_for_intake(intake_id)
        if run is None:
            return None
        return {
            "id": str(run.id),
            "status": run.status,  # verbatim (Pitfall 1)
            "applied_at": run.applied_at.isoformat() if run.applied_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        }


def read_latest_research_run_dict(identity: Identity, intake_id: Any) -> dict | None:
    """One short scoped tx per tick → the latest research run as a PLAIN dict (RUN-01).

    The research-stream twin of :func:`read_latest_run_dict`: the Plan-04 SSE handler
    (``research_routes.stream_research_run``) drives this once per tick so any Cloud Run
    instance serving a reconnecting client re-reads the mirrored ``research_runs`` row
    fresh (statelessness). Returns a PLAIN dict (NEVER a live ORM row — a row from tick N's
    session is detached in tick N+1, ``DetachedInstanceError``) whose keys ARE the wire
    shape the frontend renders the dynamic stage trace from.

    ``status`` is carried VERBATIM (D-05 boundary): the Tribunal literal
    ``{queued, running, completed, failed, cancelled}`` is never remapped to the skill-run
    ``{succeeded, failed}`` vocabulary. ``current_stage`` + ``stage_detail`` carry the
    dynamic stage list (no hardcoded 9-stage assumption); ``cost_usd_total`` is stringified
    (a ``Decimal`` is not JSON-serializable). Returns ``None`` when the intake has no
    research runs yet (the stream then emits ``data: null``). The connection returns to the
    pool on block exit — nothing held between ticks.
    """
    with tenant_session(identity) as session:
        run = ResearchRunRepository(session, identity).latest_for_intake(intake_id)
        if run is None:
            return None
        return {
            "id": str(run.id),
            "status": run.status,  # verbatim (D-05 boundary)
            "current_stage": run.current_stage,
            "stage_detail": run.stage_detail,
            "cost_usd_total": (
                str(run.cost_usd_total) if run.cost_usd_total is not None else None
            ),
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error_message": run.error_message,
        }


def read_brief_inputs(identity: Identity, intake_id: Any) -> dict | None:
    """Read the intake + its decomposition + validated questions as PLAIN dicts (SEAM-04).

    The synchronous scoped read the research trigger performs to compose the Tribunal
    brief (:func:`app.research.brief.assemble_brief`). Returns PLAIN dicts (never live ORM
    rows) so nothing detaches once this short tx closes — the trigger then holds only data,
    not a session. Returns ``None`` when the intake is missing / out of scope (the trigger
    renders that as an existence-hidden 404, D-07).

    The shapes match what ``assemble_brief`` reads: the ``intake`` dict carries
    ``project_title`` / ``client_name`` + an ``answers`` map (so the report hint is
    field-driven); ``decomposition`` carries ``summary``; ``questions`` is a list of
    ``{question_text, priority}`` in DB order (``assemble_brief`` re-sorts by priority).
    The read is space-scoped: a user sees only their own space's rows; a superadmin reaches
    the intake's own space via the 0011 bypass.
    """
    with tenant_session(identity) as session:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            return None

        # The latest decomposition for this intake (scoped). ``_scope`` walls a user to
        # their space and is a no-op for the superadmin (bypass policy reaches the row).
        decomposition = session.execute(
            _scoped(identity, select(Decomposition))
            .where(Decomposition.intake_id == intake_id)
            .order_by(Decomposition.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()

        questions = (
            session.execute(
                _scoped(identity, select(ResearchQuestion))
                .where(ResearchQuestion.intake_id == intake_id)
                .order_by(ResearchQuestion.priority.asc())
            )
            .scalars()
            .all()
        )

        # The validated context pack (the artifact the decompose step wrote and the
        # operator reviewed). The brief folds a bounded excerpt in so the engine
        # receives the company/market context the intake flow already produced —
        # without it the engine's adaptive-intake judges the brief VAGUE and parks
        # the run as needs_input (live finding, 2026-07-21).
        context_pack_text: str | None = None
        artifact_id = getattr(intake, "context_pack_artifact_id", None)
        if artifact_id is not None:
            artifact = session.execute(
                _scoped(identity, select(ResearchArtifact))
                .where(ResearchArtifact.id == artifact_id)
                .limit(1)
            ).scalar_one_or_none()
            if artifact is not None:
                context_pack_text = artifact.text_content

        # An answer's payload lives in ONE of two columns: ``value_json`` (JSONB —
        # list/object fields like the research questions) or ``value`` (Text —
        # scalar fields). Reading only ``value`` made every list field look empty
        # (live finding 2026-07-21: rich intakes produced zero-question briefs).
        answers = {
            a.field_key: (a.value_json if a.value_json is not None else a.value)
            for a in intake.answers
        }
        return {
            "intake": {
                "project_title": intake.client_name,
                "client_name": intake.client_name,
                "answers": answers,
            },
            "decomposition": (
                {"summary": decomposition.summary} if decomposition is not None else None
            ),
            "questions": [
                {"question_text": q.question_text, "priority": q.priority}
                for q in questions
            ],
            "context_pack_text": context_pack_text,
        }


def _scoped(identity: Identity, stmt):
    """Apply the tenant space filter for a user; leave a superadmin statement unchanged.

    Mirrors :meth:`app.db.repository.TenantRepository._scope` for the two ad-hoc brief-input
    reads above (which query ``Decomposition`` / ``ResearchQuestion`` — models with no
    dedicated repository). A ``user`` gets an explicit ``WHERE space_id = <own space>`` (the
    un-omittable D-01 wall); a ``superadmin`` (``space_id is None``) gets the statement
    unchanged (the 0011 bypass policy admits the cross-space read).
    """
    if identity.role == "superadmin" or not identity.space_id:
        return stmt
    model = stmt.column_descriptions[0]["entity"]
    # Coerce str -> uuid.UUID for the explicit WHERE (pg8000; mirrors _space_id in the repo).
    return stmt.where(model.space_id == uuid.UUID(identity.space_id))
