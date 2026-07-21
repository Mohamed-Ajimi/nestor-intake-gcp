"""``research_runs`` — the intake-side MIRROR of a Tribunal deep-research run.

Phase 16 foundation (ENGINE-03). Tenant-OWNED (TENANT-01): every row carries
``space_id NOT NULL`` -> ``organizations(id)`` and is FORCE-RLS space-isolated
from day one (Pitfall 5 — a fresh tenant surface is a fresh chance to reintroduce
the broken-RLS bug class). This table is the seam of record between the intake
backend and the internal Tribunal engine:

  * the run-trigger endpoint (Plan 02) INSERTs a ``queued`` row and stamps the
    ``tribunal_run_id`` returned by ``tribunal_client.create_run``;
  * the poll driver (Plan 03) mirrors the Tribunal ``get_metrics`` status /
    ``current_stage`` / ``stage_detail`` / ``cost_usd_total`` into this row and,
    on the terminal ``completed`` status, persists the raw ``output_markdown``
    (via ``get_report``) so Phase 17's raw-output surface is a pure UI add (A4);
  * the SSE stream endpoint (Plan 04) READs this row (never Tribunal directly).

STATUS LITERALS ARE CARRIED VERBATIM (D-05 boundary): the ``status`` column holds
the Tribunal engine's own values ``{queued, running, completed, failed,
cancelled}`` — it is NEVER remapped to the skill-run vocabulary ``{succeeded,
failed}``. A run that finishes successfully is ``completed`` here (NOT
``succeeded``); mixing the two vocabularies is the exact class of contract drift
the SSE terminal-set pitfall warns about (16-RESEARCH Pitfall). ``server_default``
is ``queued`` to mirror the run's birth state.

Index shape mirrors ``SkillRun`` (space-LEADING composite indexes) so the
space_id predicate is index-served for the per-intake poll/read paths. The three
index names MUST match migration 0011 1:1 (``alembic check`` gate).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchRun(Base):
    __tablename__ = "research_runs"

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
    # Tribunal literals carried VERBATIM — {queued, running, completed, failed,
    # cancelled}. NEVER remapped to skill-run {succeeded, failed} (D-05 boundary).
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="queued"
    )
    # ---- Tribunal mirror columns (poll driver / trigger stamp these). All
    #      NULLABLE except ``attempt`` — a freshly-inserted ``queued`` row carries
    #      none of the progress fields until the first poll.
    #: The Tribunal-side run id returned by create_run — the poll key (nullable
    #: until the trigger stamps the create_run response).
    tribunal_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The currently-executing stage key (dynamic; NEVER a hardcoded 9-stage
    #: assumption — the progress UI renders the stage list dynamically).
    current_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Per-stage progress detail, shape ``{stage_key: {items:[{name,status}]}}``.
    stage_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Running cost total in USD (mirrored from the Tribunal budget governor).
    cost_usd_total: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    #: Attempt counter (D-04 attempt tracking) — NOT NULL, starts at 1. A retrigger
    #: after a failed/stale run bumps this so the audit trail keeps every attempt.
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    #: Terminal error message on the ``failed`` path (nullable otherwise).
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The raw research output markdown, persisted on ``completed`` (A4) so the
    #: Phase 17 raw-output surface is a pure UI add — no re-fetch from Tribunal.
    output_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_research_runs_space_id", "space_id"),
        Index("idx_research_runs_space_intake", "space_id", "intake_id"),
        Index("idx_research_runs_space_status", "space_id", "status"),
    )
