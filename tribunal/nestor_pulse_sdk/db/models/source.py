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

Migration 0016 (D-V01-11, phase 15.4) adds `resolved_url` and
`resolution_status`, both nullable and neither part of `content_hash`,
so the dedupe index above is unaffected. That lock-step rule is why they
are mirrored here in the same commit as the DDL.
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
    # D-V01-11 (migration 0016) -- a gemini grounding redirect and the publisher
    # URL it resolves to, stored SIDE BY SIDE. `url` above stays exactly what the
    # provider returned and is never rewritten; `resolved_url` is the durable
    # target, because `vertexaisearch.cloud.google.com` redirects expire ~30 days
    # after the run and would otherwise take every citation in every past report
    # with them.
    #
    # Both are nullable so no historic row needs a backfill, and NEITHER
    # participates in `content_hash` -- that hash is computed in
    # `citations/extractor.py::_upsert_source` from the snapshot alone, so the
    # partial UNIQUE index below still dedupes byte-identically. Same rule
    # `title` lives under.
    resolved_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NULL = never attempted | 'resolved' = a 302 Location was read and stored
    # | 'unresolved' = attempted, no usable http(s) target. Clamped in Python
    # (the `claim.certainty` idiom), deliberately NOT a CHECK constraint or an
    # enum: a resolver bug must not be able to fail an INSERT inside a paid run.
    resolution_status: Mapped[str | None] = mapped_column(Text, nullable=True)
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
