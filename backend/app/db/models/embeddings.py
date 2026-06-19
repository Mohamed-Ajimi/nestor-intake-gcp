"""``artifact_embeddings`` + ``search_index`` — RAG / semantic search.

Tenant-owned (TENANT-01): both carry ``space_id`` so Phase 7 search can
prefilter by space (no cross-tenant vector-leak path baked in — threat T-01-06).

``artifact_embeddings.embedding`` is ``Vector(1536)`` (D-08, matches
``text-embedding-3-small``) with **NO index this phase** (criterion 4):
- IVFFlat is FORBIDDEN — it needs training rows the empty table lacks.
- HNSW is DEFERRED — buildable on an empty table, but deferred by policy until
  data exists. Intent recorded below for the future index migration.

DEFERRED (do NOT create on the empty table):
    CREATE INDEX ix_artifact_embeddings_hnsw
        ON nestor.artifact_embeddings
        USING hnsw (embedding vector_cosine_ops);
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ArtifactEmbedding(Base):
    __tablename__ = "artifact_embeddings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.research_artifacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    # vector(1536). NO HNSW/IVFFlat index this phase (criterion 4).
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536), nullable=True
    )
    chunk_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_artifact_embeddings_space_id", "space_id"),
        # space_id-leading composite for tenant prefilter (NOT a vector index).
        Index("idx_artifact_embeddings_space_artifact", "space_id", "artifact_id"),
    )


class SearchIndex(Base):
    __tablename__ = "search_index"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    intake_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intakes.id", ondelete="CASCADE"),
        nullable=True,
    )
    artifact_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.research_artifacts.id", ondelete="CASCADE"),
        nullable=True,
    )
    kind: Mapped[str | None] = mapped_column(String, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_search_index_space_id", "space_id"),
        Index("idx_search_index_space_intake", "space_id", "intake_id"),
    )
