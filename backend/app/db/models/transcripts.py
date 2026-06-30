"""``transcripts`` — chunked speech-to-text output for an ``intake_sources`` row.

Tenant-owned (TENANT-01): carries ``space_id NOT NULL`` FK -> organizations(id)
ON DELETE CASCADE + a ``space_id``-leading composite index, cloning the
``skill_runs`` shape. Each row is one transcript chunk (a window of the audio)
produced by the ported ``transcribe-audio`` handler. ``source_id`` FKs the parent
``intake_sources`` row (ON DELETE CASCADE) so deleting the upload removes its
transcript. No ``intake_status`` bump is associated with this table — the audio
path is E2E-deferred and out-of-flow (07-RESEARCH Pitfall 1 / Open Q2).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Transcript(Base):
    __tablename__ = "transcripts"

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
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intake_sources.id", ondelete="CASCADE"),
        nullable=False,
    )
    chunk_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    token_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speaker: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_transcripts_space_id", "space_id"),
        Index("idx_transcripts_space_intake", "space_id", "intake_id"),
    )
