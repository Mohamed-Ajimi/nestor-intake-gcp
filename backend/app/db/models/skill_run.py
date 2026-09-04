"""``skill_runs`` — runs of the intake skill (apply-intake-skill).

Tenant-owned (TENANT-01). Stores the Claude call's status + parsed JSON output
(refined questions, additional questions, dropped, gaps). The admin reviews
this output; it does NOT directly write research_questions (BACKEND-MAP.md §3).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
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
    # ---- Legacy parity + cost-observability columns (07-RESEARCH Pitfall 2 /
    #      Open Q1). All NULLABLE — the existing run lifecycle is unaffected; AI
    #      handlers stamp these post-call (tokens/cost from the LLM response,
    #      prompts + raw output for auditability, skill_version for replay).
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate_usd: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    output: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    skill_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # NOTE there is deliberately no ``started_at`` here. It existed from 0001 and was
    # never written by anything; migration 0015 (plan 23.1-13) dropped it. ``created_at``
    # above IS the run's start timestamp — Postgres now() at INSERT, NOT NULL — and is
    # what the intake page's elapsed clock reads. Only ``research_runs.started_at`` is a
    # real, written column; it is a different column on a different table.
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    applied_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_skill_runs_space_id", "space_id"),
        Index("idx_skill_runs_space_intake", "space_id", "intake_id"),
        Index("idx_skill_runs_space_status", "space_id", "status"),
        # COST-01 / D-23.1-04 — at most ONE running run per (intake, skill). The
        # arbiter is the DATABASE, not an app-level "is one already running?" check,
        # which races: two concurrent dispatches both read "no" and both insert, and
        # the operator pays for two Claude generations. PARTIAL on status='running'
        # so terminal rows stay unconstrained and a re-run after completion is legal.
        # The name is byte-identical to migration 0014's — a mismatch here is
        # invisible until a downgrade or a later autogenerate, and `alembic check`
        # is what pins it.
        Index(
            "uq_skill_runs_one_running_per_intake_skill",
            "intake_id",
            "skill",
            unique=True,
            postgresql_where=text("status = 'running'"),
        ),
    )
