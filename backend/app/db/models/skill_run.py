"""``skill_runs`` — runs of the intake skill (apply-intake-skill).

Tenant-owned (TENANT-01). Stores the Claude call's status + parsed JSON output
(refined questions, additional questions, dropped, gaps). The admin reviews
this output; it does NOT directly write research_questions (BACKEND-MAP.md §3).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SkillRun(Base):
    __tablename__ = "skill_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    intake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    skill: Mapped[str] = mapped_column(
        String, nullable=False, server_default="apply-intake-skill"
    )
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="queued"
    )
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    output_parsed: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("idx_skill_runs_space_intake", "space_id", "intake_id"),
        Index("idx_skill_runs_space_status", "space_id", "status"),
    )
