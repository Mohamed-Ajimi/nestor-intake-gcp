"""
Org -- top-level tenant entity (org.id == tenant_id everywhere else).

Per 01-CONTEXT.md D-05 + D-06: Org IS the tenant -- not tenant-scoped
itself. Every other tenant-scoped table FKs to `org.id` via `tenant_id`.

Per 01-CONTEXT.md D-12 + "Claude's Discretion": per-client retention is
admin-settable; default is 6 months. We store it in days for precise
GCS bucket-lifecycle alignment (180 days ~= 6 months).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nestor_pulse_sdk.db.base import Base


class Org(Base):
    __tablename__ = "org"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    retention_days: Mapped[int] = mapped_column(default=180, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Cascading children -- delete-org wipes all descendants (Test 1).
    projects = relationship(
        "Project", back_populates="org", cascade="all, delete-orphan"
    )
    users = relationship(
        "User", back_populates="org", cascade="all, delete-orphan"
    )
