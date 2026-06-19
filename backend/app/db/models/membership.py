"""``organization_memberships`` — user -> space mapping (D-02).

A tenant ROOT table: it carries NO ``space_id`` and is NOT RLS-scoped. It maps
an Identity Platform user (``user_id`` / ``provider_user_id``) to an
organization (= space) with a role. Roles in v1: ``superadmin`` (cross-tenant,
Agenic) and ``user`` (own space only). The ``organization_id`` FK is the link
to the space; superadmin is additionally a DB role (plan 01-03), not a row
attribute here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class OrganizationMembership(Base):
    __tablename__ = "organization_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Identity Platform subject id (Phase 3 auth). Nullable until auth lands.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    provider_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    role: Mapped[str] = mapped_column(
        String, nullable=False, server_default="user"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    organization = relationship("Organization", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint(
            "organization_id", "user_id", name="uq_membership_org_user"
        ),
    )
