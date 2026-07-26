"""
Claim -- a single assertion extracted from research, joined to sources.

Per 01-RESEARCH.md § Pattern 4 (lines 547-560). `facet` carries the
question_facet label from the existing ADK synthesis pipeline (see
nestor_pulse/synthesis_pipeline/steps.py RelevanceGate output). Phase
1 leaves `position` advisory (Plan 09 fills it during synthesis).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class Claim(Base):
    __tablename__ = "claim"

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
    text: Mapped[str] = mapped_column(Text, nullable=False)
    facet: Mapped[str | None] = mapped_column(String, nullable=True)
    position: Mapped[int | None] = mapped_column(nullable=True)
    # D-13 (migration 0013): D8's per-fact certainty marker -- 'certain' when
    # corroborated, 'single' for "found only once -- double-check", NULL when the
    # provider said nothing. Drives the report's hedging language.
    certainty: Mapped[str | None] = mapped_column(String, nullable=True)
    # D-13 (migration 0013): the persisted G-12 provenance -- which providers
    # independently surfaced this fact. ARRAY(Text), not JSONB, so it stays
    # queryable (`'gemini' = ANY(found_by)`) and `cardinality(found_by)` gives the
    # corroboration count directly.
    found_by: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_claim_tenant_run", "tenant_id", "run_id"),
    )
