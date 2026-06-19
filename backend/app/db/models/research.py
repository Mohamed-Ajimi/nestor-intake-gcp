"""``decompositions`` + ``research_questions`` + ``research_artifacts``.

Tenant-owned (TENANT-01). The decomposed brief: a decomposition groups the
prioritized research questions materialized from the intake. research_artifacts
hold research outputs (evidence) — schema present for fidelity though the flow
stops at ``decomposed`` (Tribunal is the writer, out of scope).

``question_type`` enum (BACKEND-MAP.md): ``descriptive`` is the default the
research-start trigger uses; the broader set is modeled for fidelity. The 0001
migration owns enum creation (``create_type=False`` here).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

question_type_enum = ENUM(
    "descriptive",
    "comparative",
    "causal",
    "predictive",
    name="question_type",
    schema="nestor",
    create_type=False,
)


class Decomposition(Base):
    __tablename__ = "decompositions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    questions = relationship(
        "ResearchQuestion",
        back_populates="decomposition",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_decompositions_space_id", "space_id"),
        Index("idx_decompositions_space_intake", "space_id", "intake_id"),
    )


class ResearchQuestion(Base):
    __tablename__ = "research_questions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    decomposition_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.decompositions.id", ondelete="CASCADE"),
        nullable=True,
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(
        question_type_enum, nullable=False, server_default="descriptive"
    )
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="open"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    decomposition = relationship("Decomposition", back_populates="questions")

    __table_args__ = (
        Index("ix_research_questions_space_id", "space_id"),
        Index(
            "idx_research_questions_space_intake", "space_id", "intake_id"
        ),
        Index(
            "idx_research_questions_space_status", "space_id", "status"
        ),
    )


class ResearchArtifact(Base):
    __tablename__ = "research_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
    research_question_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.research_questions.id", ondelete="SET NULL"),
        nullable=True,
    )
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    artifact_type: Mapped[str | None] = mapped_column(String, nullable=True)
    filename: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_bucket: Mapped[str | None] = mapped_column(String, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String, nullable=True)
    text_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    embed_status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="pending"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_research_artifacts_space_id", "space_id"),
        Index(
            "idx_research_artifacts_space_intake", "space_id", "intake_id"
        ),
        Index(
            "idx_research_artifacts_space_embed", "space_id", "embed_status"
        ),
    )
