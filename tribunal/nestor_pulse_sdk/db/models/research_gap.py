"""
ResearchGap -- the per-provider "couldn't find" list (Phase 15.2 ENGINE-11, D-13).

One row per (run, provider, unfound-item): the plain-prose things a research
provider explicitly reported it could NOT establish. D-08's report reads these
into its "What we could not establish" section, so an absent fact is stated
honestly instead of silently omitted.

Mirrors migration `0013_fact_metadata_research_gap.py` EXACTLY (that revision
creates the table, its index and its RLS). `tenant_id` is DENORMALIZED onto this
table for RLS -- every tenant-scoped table needs the column locally because
cross-table RLS via JOINs is forbidden (the rule recorded in claim_source.py:1-8,
Pitfall 2). The `idx_research_gap_tenant_run` index leads with `tenant_id` for
the same reason.

ENABLE + FORCE ROW LEVEL SECURITY and the `research_gap_tenant_isolation` policy
live in migration 0013, NOT in this ORM file -- exactly as `claim` and
`verification_verdict` do. The policy uses 0010's
`NULLIF(current_setting('app.tenant_id', true), '')::uuid` form, and there is
deliberately NO `research_gap_worker_all` policy: the write path
(`persist_tribunal_claims`, plan 15.2-15) must run inside
`db/rls.py::set_tenant_context` or its INSERT is rejected by WITH CHECK.

Columns:
  - id         UUID PK (default uuid4)
  - tenant_id  UUID FK org.id CASCADE (the RLS tenant key)
  - run_id     UUID FK run.id CASCADE
  - provider   TEXT  which provider reported the gap ('gemini' | 'openai' | 'own')
  - text       TEXT  the item that could not be established
  - created_at timestamptz server_default now()
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from nestor_pulse_sdk.db.base import Base


class ResearchGap(Base):
    __tablename__ = "research_gap"

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
    provider: Mapped[str] = mapped_column(String, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # The index name MUST match migration 0013 exactly or autogenerate reports
    # drift (and would propose dropping + recreating it).
    __table_args__ = (
        Index("idx_research_gap_tenant_run", "tenant_id", "run_id"),
    )
