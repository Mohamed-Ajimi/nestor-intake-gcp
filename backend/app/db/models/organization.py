"""``organizations`` — the tenant / space root (D-01).

An organization IS a space: ``space_id`` on every tenant-owned table equals
``organizations.id``. The root carries NO ``space_id`` (it is not RLS-scoped —
it defines the boundary). Client identity lives on ``organizations.name``
(Q2 RESOLVED: no ``public.clients`` table is created; ``prefill_intake_answers``
reads ``organizations.name``).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Client identity (Q2 RESOLVED): no public.clients — the org name is the
    # client name surfaced by prefill_intake_answers.
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str | None] = mapped_column(String, nullable=True, unique=True)
    # D-10 soft-deactivate flag; app-level allowed set {"active","deactivated"}
    # (enforced in code, NOT a PG enum). No hard-delete path exists.
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="active"
    )
    # D-07 (i18n / 0010) space default language — the base of the locale resolution
    # chain (user override -> space default -> "nl"). App-level allowed set
    # {"nl","fr","en"} enforced IN CODE (me_routes _ALLOWED), NOT a PG enum — mirrors
    # the status column rationale (avoids alembic enum-alter friction). server_default
    # "nl" backfills existing rows non-null on the 0010 apply.
    default_locale: Mapped[str] = mapped_column(
        String, nullable=False, server_default="nl"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Cascading children — deleting a space wipes its descendants. Only the
    # membership map cascades from the relationship layer; tenant-owned tables
    # cascade via their ``space_id`` FK ``ON DELETE CASCADE``.
    memberships = relationship(
        "OrganizationMembership",
        back_populates="organization",
        cascade="all, delete-orphan",
    )
