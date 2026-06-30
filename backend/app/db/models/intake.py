"""``intakes`` + ``intake_answers`` + ``intake_templates`` — the intake forms.

Tenant-owned (TENANT-01): each carries ``space_id NOT NULL`` FK ->
organizations(id) ON DELETE CASCADE + a ``space_id``-leading composite index.

``intake_status`` enum (D-04 fidelity): the FULL 8-value state machine is
modeled even though THIS milestone's flow stops at ``decomposed`` — the later
values (``in_research``, ``delivered``, ``archived``) exist for schema fidelity
with the Tribunal handoff, but no in-scope code transitions into them.

Reconciliation (Q2 RESOLVED): no ``public.clients`` table. ``intakes`` keeps a
nullable ``client_name`` text column for display only; ``space_id`` (= org id)
is the SOLE isolation key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# Full intake_status state machine (BACKEND-MAP.md § FULL FLOW). The flow in
# THIS milestone stops at ``decomposed``; the trailing values are schema-only
# (D-04). ``create_type=False`` — the 0001 migration owns enum creation so the
# ORM does not race it (alembic, not create_all, builds the schema).
intake_status_enum = ENUM(
    "draft",
    "submitted",
    "reviewed",
    "validated_by_client",
    "decomposed",
    "in_research",
    "delivered",
    "archived",
    name="intake_status",
    schema="nestor",
    create_type=False,
)


class Intake(Base):
    __tablename__ = "intakes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intake_templates.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Display-only client name (Q2 RESOLVED: no public.clients).
    client_name: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        intake_status_enum, nullable=False, server_default="draft"
    )
    # Lifecycle markers driving the admin phase machine (BACKEND-MAP.md).
    validation_link_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    results_link_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    context_pack_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    final_report_artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    answers = relationship(
        "IntakeAnswer", back_populates="intake", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_intakes_space_id", "space_id"),
        Index("idx_intakes_space_status", "space_id", "status"),
        Index("idx_intakes_space_created", "space_id", "created_at"),
    )


class IntakeTemplate(Base):
    __tablename__ = "intake_templates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    # JSON schema of sections/fields (intake-types.ts IntakeSchema).
    schema: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_intake_templates_space_id", "space_id"),
        Index("idx_intake_templates_space_name", "space_id", "name"),
    )


class IntakeAnswer(Base):
    __tablename__ = "intake_answers"

    # server_default gen_random_uuid() (migration 0007): the prefill_intake_answers trigger
    # inserts rows via raw SQL that does NOT carry the ORM uuid4 default, so id needs a
    # DB-level default or the trigger insert hits 23502 (null id, NOT NULL violation).
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
    # field_key addresses one form field; prefill_intake_answers + the
    # save-as-you-go RPC both upsert on (intake_id, field_key).
    field_key: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    intake = relationship("Intake", back_populates="answers")

    __table_args__ = (
        UniqueConstraint(
            "intake_id", "field_key", name="uq_intake_answers_intake_field"
        ),
        Index("ix_intake_answers_space_id", "space_id"),
        Index("idx_intake_answers_space_intake", "space_id", "intake_id"),
    )
