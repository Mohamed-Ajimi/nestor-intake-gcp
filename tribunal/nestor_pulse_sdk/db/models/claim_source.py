"""
ClaimSource -- many-to-many join between Claim and Source (D-07).

Per 01-RESEARCH.md § Pattern 4 (lines 562-575). `tenant_id` is
denormalized for RLS (every tenant-scoped table needs the column
locally; cross-table RLS via JOINs is forbidden by Pitfall 2).
`confidence` is NULL in Phase 1 -- Phase 2 PHASE2-05 fills it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Float, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class ClaimSource(Base):
    __tablename__ = "claim_source"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("claim.id", ondelete="CASCADE"),
        primary_key=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    snippet: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    __table_args__ = (
        Index("idx_claim_source_tenant", "tenant_id"),
    )
