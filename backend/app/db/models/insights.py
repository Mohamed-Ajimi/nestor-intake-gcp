"""``extracted_insights`` — structured facts/insights the AI lifts from an intake.

Tenant-owned (TENANT-01): carries ``space_id NOT NULL`` FK -> organizations(id)
ON DELETE CASCADE + a ``space_id``-leading composite index, cloning the
``skill_runs`` shape. Each row is one insight the ported ``extract-insights``
handler distilled from a transcript chunk or an intake answer. ``source_chunk_id``
points (loosely, no FK) at the originating ``transcripts`` row and
``source_answer_id`` at the originating ``intake_answers`` row, for provenance —
both nullable since an insight may come from either path.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ExtractedInsight(Base):
    __tablename__ = "extracted_insights"

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
    # 'fact' | 'insight' | ... — the kind of thing extracted (free-text, not the
    # finding_kind enum, since this is pre-research staging).
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    label: Mapped[str | None] = mapped_column(String, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    supporting_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Provenance pointers (plain UUIDs, no FK — an insight may reference either a
    # transcript chunk or an intake answer, and must survive their deletion).
    source_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    source_answer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_extracted_insights_space_id", "space_id"),
        Index("idx_extracted_insights_space_intake", "space_id", "intake_id"),
    )
