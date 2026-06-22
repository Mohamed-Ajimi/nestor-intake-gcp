"""``audit_log`` — tamper-evident operator action trail (QA-04 / D-07).

A tenant ROOT table, exactly like ``organization_memberships`` /
``organizations``: it carries NO ``space_id NOT NULL`` and is NEVER RLS-scoped
(it is absent from the 0002 ``*_space_isolation`` / 0003 ``_RLS_TABLES`` loops).
``space_id`` is recorded here as a *plain nullable* column with NO ForeignKey so
the audit row survives a soft-deactivated (or later hard-removed) space — the
trail must outlive its subject (D-07).

Every operator/system action that changes user/space/template state writes one
row here via :func:`app.db.audit.log` on the SAME request session, so the audit
row commits/rolls back WITH the action it records (no orphan rows).

RESERVED-NAME TRAP: SQLAlchemy reserves the attribute ``metadata`` on the
declarative ``Base`` (``Base.metadata``). The JSONB column is therefore mapped to
the Python attribute ``event_metadata`` while keeping the DB column name
``metadata`` — NEVER a bare ``metadata: Mapped[dict]``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Server-derived actor (the verified IdP subject), never client text.
    actor_uid: Mapped[str] = mapped_column(String, nullable=False)
    # Membership the action was taken under. SET NULL so the trail outlives a
    # removed membership row.
    actor_membership_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "nestor.organization_memberships.id", ondelete="SET NULL"
        ),
        nullable=True,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[str | None] = mapped_column(String, nullable=True)
    # D-07 root: plain nullable UUID, NO ForeignKey — survives a soft-deactivated
    # space so the trail is not cascade-deleted with its subject.
    space_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # RESERVED-NAME TRAP: ORM attribute is event_metadata, DB column is "metadata"
    # (a bare `metadata` would collide with Base.metadata). Structured JSONB only —
    # NEVER the action link, a token, or a password (see app/db/audit.py contract).
    event_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, server_default=text("'{}'")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        # Explicit names (declared here, never via the column-level shortcut) so
        # they match the 0006 migration and carry no schema prefix — keeps
        # `alembic check` clean (the membership.py convention).
        Index("ix_audit_log_space_id", "space_id"),
        Index("ix_audit_log_created_at", "created_at"),
        Index("idx_audit_log_event_created", "event_type", "created_at"),
    )
