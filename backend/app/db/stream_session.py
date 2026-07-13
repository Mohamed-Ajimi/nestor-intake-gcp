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

from typing import Any

from app.auth.identity import Identity
from app.db.ai_session import tenant_session
from app.db.repository import IntakeRepository, SkillRunRepository


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
