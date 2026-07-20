"""
Source -- first-class citation entity (D-07).

Per 01-RESEARCH.md § Pattern 4 (lines 526-545): URL + title + provider +
fetched_at + snapshot_text + snapshot_gcs_uri + content_hash. Snapshots
are captured at fetch time so dead URLs don't break old reports.

Partial UNIQUE index `(tenant_id, content_hash) WHERE content_hash IS
NOT NULL` provides per-tenant dedupe; Phase 1 leaves it advisory (Plan
09 fills in the writes). The Alembic migration 0003 carries the exact
DDL; the ORM index here is kept in lock-step so autogenerate diffs are
clean.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class Source(Base):
    __tablename__ = "source"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    snapshot_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    snapshot_gcs_uri: Mapped[str | None] = mapped_column(String, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_source_tenant_url", "tenant_id", "url"),
        # Partial UNIQUE -- RESEARCH line 539 verbatim.
        Index(
            "idx_source_tenant_content_hash",
            "tenant_id",
            "content_hash",
            unique=True,
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
    )
