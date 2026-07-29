"""
Claim -- a single assertion extracted from research, joined to sources.

Per 01-RESEARCH.md § Pattern 4 (lines 547-560). `facet` carries the
question_facet label from the existing ADK synthesis pipeline (see
nestor_pulse/synthesis_pipeline/steps.py RelevanceGate output). Phase
1 leaves `position` advisory (Plan 09 fills it during synthesis).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, func
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
    # D-R3 (migration 0017): the winner text this claim answers. Today `facet`
    # carries the PARENT CLIENT QUESTION, inherited from the angle the claim was
    # dispatched under -- `_angle()` stamps `focus_area` in Python and the claim
    # takes it. That inheritance is correct only while one angle maps to exactly
    # one client question. Phase 15.6 groups winners into <=5 groups sent to all
    # providers, and the moment a group spans two client questions a claim from
    # it has NO SINGLE PARENT and `facet` becomes a lie. So the sub-question is
    # recorded on the row itself rather than reconstructed from the angle.
    sub_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    # D-R3 (migration 0017): the shared dispatch key ('w01' / 'w02' / ...) -- the
    # real join key for corroboration.
    #
    # D-W2-2: only the TOP-3 winners get a key. `research_division.py:867-874`
    # deals the top-k to every stream with `key = f"w{rank:02d}"` and deals the
    # REMAINDER round-robin with the EMPTY STRING, so this column is NULL for
    # roughly 12 of 15 winners today. That is CORRECT, not a bug -- it fills up
    # in phase 15.6, when every group goes to every provider.
    #
    # An absent key is written as NULL, never as ''. Same rule as `found_by`
    # ("an ABSENT provenance is bound as None, never as []"): "no key recorded"
    # and "recorded as the empty key" are DIFFERENT FACTS, and the corroboration
    # queries must be able to tell them apart.
    corroboration_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # D-R3 (migration 0017): the claim's own date, where the provider stated one.
    # `Date` and not `DateTime`: a claim is dated to a day at best.
    #
    # This exists because D-V01-4 was WITHDRAWN. Gemini and claude read different
    # De Haan articles at different points in one rollout -- 7 sites in 2021 vs
    # ~90 later -- and BOTH WERE TRUE. Without a date the engine cannot tell a
    # contradiction from a time series. NULL is the common case and is accepted;
    # the value is parsed from the EVIDENCE cell by
    # `pipeline/synthesis/claim_attribution.py::extract_as_of`, which rejects
    # every ambiguous form rather than guessing (a wrong date is worse than no
    # date: it manufactures a fake time series out of a real contradiction).
    as_of: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("idx_claim_tenant_run", "tenant_id", "run_id"),
    )
