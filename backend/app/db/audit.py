"""``audit.log`` — the single audit-trail write seam (QA-04 / T-5-04, T-5-05).

Lives INSIDE ``app/db/`` (alongside ``repository.py``) so it stays on the right
side of ``scripts/ci_no_raw_db_access.sh`` (the D-03 grep-guard whitelists
``app/db/``). It imports NO engine / sessionmaker / create_engine — it is a free
function that operates ONLY on the request's already-bound :class:`Session`.

ONE-TX CONTRACT (Pattern: audit-in-the-same-tx): :func:`log` writes via the
PASSED-IN session, so the ``audit_log`` row commits/rolls back together WITH the
action it records. A mutation handler that fails after the work but before the
commit leaves NO orphan audit row; a handler that commits records exactly one
row. Never open a separate transaction here.

EVENT-TYPE CONTRACT (the structured ``metadata`` JSONB payload per event):
  - ``user.invited``      -> {"email", "assigned_space_id", "role"}
  - ``user.deactivated``  -> {"reason"?}
  - ``user.reactivated``  -> {}
  - ``auth.login``        -> {"sync_result"}
  - ``space.created``     -> {"name", "slug"}
  - ``space.updated``     -> {...changed fields...}
  - ``space.deactivated`` -> {"reason"?}
  - ``template.cloned``   -> {"source_template_id"?}
  - ``template.updated``  -> {...changed fields...}

SECURITY (T-5-05, 05-RESEARCH Security Domain): ``metadata`` is STRUCTURED data
only. NEVER log the action link, a token (invite/reset), or a password — PII is
limited to ``email``. Audit fields are server-derived (``actor_uid`` from the
verified IdP token), so client text never becomes a column name.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.db.models.audit import AuditLog


def log(
    session: Session,
    *,
    actor_uid: str,
    actor_membership_id: uuid.UUID | None = None,
    event_type: str,
    target: str | None = None,
    space_id: uuid.UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Record one ``audit_log`` row on the request's bound ``session``.

    The row is added (not committed) here, so it lands in the SAME transaction as
    the action being recorded — the caller's ``session.commit`` (or the
    one-tx-per-request ``maker.begin()`` block) persists action + audit atomically.

    The ``metadata`` kwarg maps onto the ORM attribute ``event_metadata`` (the DB
    column is ``metadata`` — the reserved-name trap is handled in the model). Pass
    ONLY structured fields per the event-type contract above; NEVER a link, token,
    or password.
    """
    session.add(
        AuditLog(
            actor_uid=actor_uid,
            actor_membership_id=actor_membership_id,
            event_type=event_type,
            target=target,
            space_id=space_id,
            event_metadata=metadata or {},
        )
    )
