"""
VerificationVerdict -- queryable per-claim verdict read-model (Phase 15 ENGINE-09).

One row per verdict emitted by the group-skeptic's `emit_group_verdict` tool
call. Persists the `_parse_group_verdict` shape so the verification report
(Plan 15-03) and the operator drill-down read REAL verdict data instead of
re-parsing raw audit blobs at request time.

Mirrors migrations 0011 + 0012's `verification_verdict` table EXACTLY (0011
created the table, 0012 added `superseded_note`). FK shape + tenant scoping
copied from claim.py; the RLS ENABLE/FORCE + policy live in the migration
(0011), not the ORM, exactly as claim/source do -- and 0012 deliberately
re-issues none of it, since a row-level policy is table-level and covers a new
column by construction.

Columns:
  - id           UUID PK (default uuid4)
  - tenant_id    UUID FK org.id CASCADE (RLS tenant key)
  - run_id       UUID FK run.id CASCADE
  - claim_id     UUID nullable -- links to claim.id when the group's claim is
                 resolvable (the recorded run predates claim linkage, so NULL
                 is expected for reconstructed fixtures).
  - verdict      TEXT  (support | refute | insufficient | superseded)
  - confidence   TEXT nullable (stringified 0..1 score from the emit payload)
  - evidence_refs JSONB nullable (the evidence URL/quote array)
  - reconciliation JSONB nullable (disputed / relation / note / canonical)
  - superseded_note TEXT nullable (added by 0012 -- the G-07 caveat carried by a
                 `superseded` verdict: what changed and from when. NULL for
                 every non-superseded row and for every row predating 0012.)
  - created_at   timestamptz server_default now()
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class VerificationVerdict(Base):
    __tablename__ = "verification_verdict"

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
    # NULL when the group's claim is not resolvable to a claim.id (recorded run).
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    verdict: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # disputed / relation / note / canonical (group reconciliation).
    reconciliation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # G-07 caveat shipped alongside a `superseded` verdict: what changed and
    # from when. Added by migration 0012; NULL on every non-superseded row.
    superseded_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index(
            "idx_verification_verdict_tenant_run",
            "tenant_id",
            "run_id",
        ),
    )
