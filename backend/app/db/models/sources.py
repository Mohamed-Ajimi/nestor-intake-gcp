"""``intake_sources`` — uploaded source material for an intake (audio, documents).

Tenant-owned (TENANT-01): carries ``space_id NOT NULL`` FK -> organizations(id)
ON DELETE CASCADE + a ``space_id``-leading composite index, cloning the
``skill_runs`` shape. A source is one uploaded artifact (a GCS object) that an AI
handler later transcribes / extracts insights from. Phase 7 ports the
``transcribe-audio`` + ``extract-insights`` edge functions onto this table; the
audio→transcript path records progress HERE and on ``transcripts`` — it never
bumps ``intake_status`` (the flow ceiling stays at ``decomposed``, 07-RESEARCH
Pitfall 1 / Open Q2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IntakeSource(Base):
    __tablename__ = "intake_sources"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    intake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 'audio' | 'document' | ... — which kind of source material this row points at.
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    # GCS object location (bucket + path) the handler downloads to transcribe/extract.
    storage_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_intake_sources_space_id", "space_id"),
        Index("idx_intake_sources_space_intake", "space_id", "intake_id"),
    )
