"""
AuditLog -- the per-call audit row backing the compliance hash chain (D-11/12).

Per 01-RESEARCH.md AuditRow dataclass (lines 408-422). Plan 07 fills the
writer + verifier; Plan 03 just provides the schema.

`seq` is the per-run monotonic call counter. `prev_hash`/`hash` form
the chain (SHA-256 over canonical JSON; see RESEARCH lines 742-771).
`gcs_uri` points to the full-body blob in `gs://nestor-audit-prod/`
which lives under per-object retention (Plan 01).

Composite indexes:
- (tenant_id, run_id, seq) UNIQUE -- catches duplicate writes + powers
  the chain-verifier "for run X in order".
- (tenant_id, run_id, created_at) -- dashboard guided query "all LLM
  calls for run X" (Plan 07 perf target <1s on 2000-row run).
- (tenant_id, model) -- "show all costs for org Z this month" rollup.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("org.id", ondelete="CASCADE"),
        nullable=False,
    )
    # run_id is nullable so a pre-run setup audit row can exist (e.g. auth
    # event). The (tenant_id, run_id, seq) UNIQUE still applies when both
    # are non-null; Postgres treats NULLs as distinct by default.
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("run.id", ondelete="CASCADE"),
        nullable=True,
    )
    seq: Mapped[int] = mapped_column(nullable=False)
    provider: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_ms: Mapped[int] = mapped_column(nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(nullable=False)
    completion_tokens: Mapped[int] = mapped_column(nullable=False)
    # Anthropic prompt-cache hits (Pitfall 6); 0 for providers without caching.
    cached_tokens: Mapped[int] = mapped_column(default=0, nullable=False)
    # Anthropic prompt-cache CREATION tokens (1.25x), priced by Plan 15-02's C1
    # cost fix. nullable=True: legacy rows never captured it (migration 0011
    # adds the column). OUTSIDE the frozen hash-chain payload (_payload_for_row)
    # -- additive, no chain break (T-15-01).
    cache_creation_tokens: Mapped[int | None] = mapped_column(
        default=None, nullable=True
    )
    # NULL if unknown model (Pitfall 5) -- caller MUST decide whether to
    # short-circuit the chain in that case.
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    gcs_uri: Mapped[str] = mapped_column(String, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String, nullable=False)
    hash: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "run_id", "seq", name="uq_audit_tenant_run_seq"
        ),
        Index("idx_audit_tenant_run_created", "tenant_id", "run_id", "created_at"),
        Index("idx_audit_tenant_model", "tenant_id", "model"),
    )
