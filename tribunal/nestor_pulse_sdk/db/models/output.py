"""
Output -- the rendered brief for a Run (D-06).

`format` defaults to 'markdown' (the only Phase 1 format). `gcs_uri`
is the optional rendered-PDF pointer (Phase 1 stretch / Phase 2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nestor_pulse_sdk.db.base import Base


class Output(Base):
    __tablename__ = "output"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(String, default="markdown", nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run = relationship("Run", back_populates="outputs")

    __table_args__ = (
        Index("idx_output_tenant_run", "tenant_id", "run_id"),
    )
