"""
Run -- one brief execution (D-09).

`engine` is constrained to {'adk', 'sdk'} per D-02 (CHECK constraint).
`status` is constrained to {'queued','running','completed','failed','cancelled',
'needs_input'} per D-09 (+ 'needs_input' clarification pause, migration 0005).
`(tenant_id, idempotency_key)` is UNIQUE -- repeat POSTs return existing
run (RESEARCH.md line 513 + Pattern 3 SKIP LOCKED).

Composite indexes lead with tenant_id (Pitfall 2): tenant+status (worker
poll path), tenant+project (project-detail screen), tenant+created_at
(dashboard cost-this-month tile).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from nestor_pulse_sdk.db.base import Base


class Run(Base):
    __tablename__ = "run"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    engine: Mapped[str] = mapped_column(String, nullable=False)
    brief: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)
    idempotency_key: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    worker_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd_total: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4), nullable=True
    )
    # A/B fan-out grouping (Plan 01-12): the N child runs of one comparison
    # share a comparison_id. NULL for ordinary single-engine runs.
    comparison_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Clarification loop (0005): when status='needs_input', the engine asked the
    # user 2-3 questions instead of researching a vague brief. NULL otherwise.
    clarifying_questions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Live stage progress (0006): the key of the stage the engine is currently
    # executing (e.g. 'deep_research'), or 'done' when finished. NULL for queued
    # runs / legacy rows. The ordered per-engine stage SCHEMA lives in
    # nestor_pulse_sdk/runs/stages.py; this only stores the current position.
    current_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional sub-progress for the current stage:
    # {"items": [{"name": str, "status": "done|running|pending"}]}. NULL when the
    # current stage has no sub-progress.
    stage_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    project = relationship("Project", back_populates="runs")
    outputs = relationship(
        "Output", back_populates="run", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # D-02 engine constraint (+ 'tribunal' A/B arm, migration 0004).
        CheckConstraint(
            "engine IN ('adk','sdk','tribunal')", name="ck_run_engine"
        ),
        # D-09 status constraint (+ 'needs_input' clarification pause, migration 0005).
        CheckConstraint(
            "status IN ('queued','running','completed','failed','cancelled','needs_input')",
            name="ck_run_status",
        ),
        # (tenant_id, idempotency_key) UNIQUE -- repeat POST returns existing run.
        UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_run_tenant_idempotency"
        ),
        # Composite indexes leading with tenant_id (Pitfall 2).
        Index("idx_run_tenant_status", "tenant_id", "status"),
        Index("idx_run_tenant_project", "tenant_id", "project_id"),
        Index("idx_run_tenant_created", "tenant_id", "created_at"),
        # A/B fan-out lookup: GET /api/runs/compare/{comparison_id}.
        Index("idx_run_tenant_comparison", "tenant_id", "comparison_id"),
    )
