"""``products`` — tenant-owned product catalog (Pulse, etc.).

Tenant-owned: ``space_id NOT NULL`` FK -> organizations(id) ON DELETE CASCADE,
with a ``space_id``-leading composite index (TENANT-01).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    slug: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Explicit index names (NOT index=True) so the ORM and the 0001 migration
    # use identical, schema-prefix-free names and `alembic check` stays clean.
    __table_args__ = (
        Index("ix_products_space_id", "space_id"),
        Index("idx_products_space_name", "space_id", "name"),
    )
