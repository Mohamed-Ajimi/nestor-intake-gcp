"""``generate-embeddings`` / ``embed-artifact`` ported to a space-scoped task (AI-04 write half).

Ports ``docs/supabase-functions/generate-embeddings.ts`` onto the AI-06 release contract:
READ the intake's ``research_artifacts`` rows that still sit at ``embed_status='pending'``
into plain DTOs, CALL OpenAI ``text-embedding-3-small`` (``dimensions=1536``, D-02) holding
NO connection, then in a FRESH tenant session (GUC re-issued — T-7-02) write the
space-scoped ``artifact_embeddings`` rows and advance each source artifact's
``embed_status`` to ``'done'``.

Two locked invariants this realises:

* **AI-04 / T-7-13** — every ``artifact_embeddings`` row carries the CALLER's ``space_id``
  (taken from the artifact's own tenant-scoped row, never a request/LLM value). The write
  goes through :class:`ArtifactEmbeddingRepository` (user path: ``space_id`` injected from
  the verified ``Identity``; superadmin path: the audited ``create_in_space`` against the
  artifact's OWN space).
* **Idempotency (D-09 hint)** — the READ filters on ``embed_status='pending'`` and the WRITE
  flips it to ``'done'``, so re-running the embed step finds nothing pending and produces NO
  duplicate vectors (the legacy used a ``content_hash`` skip-set — generate-embeddings.ts:6).

Grep-guard: constructs NO engine/session — the injected ``session`` (from
``run_with_session_release``) plus the repository wall do every tenant-scoped read/write;
the embed call holds no DB connection (T-7-06).

Source: generate-embeddings.ts (OpenAI ``model``/``input``/``dimensions`` body :38, 1536
dims :21, idempotent content_hash skip :6/:80-94).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.ai import clients
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import run_with_session_release
from app.db.models.research import ResearchArtifact
from app.db.repository import ArtifactEmbeddingRepository, SkillRunRepository

# text-embedding-3-small dimensions (D-02 / generate-embeddings.ts:21). Kept as a literal
# named constant so the request-shape assertion (dimensions == 1536) is unmissable.
_EMBED_DIMENSIONS = 1536

# Per-chunk character window. The legacy embedded each owner row's full text as ONE unit
# (no character chunking); we bound a single artifact's text to a safe token window so a
# very large context-pack markdown never overflows the embedding input, while a typical
# (short) artifact stays a single chunk — matching the legacy one-row-one-vector shape.
_CHUNK_CHARS = 2000


def _now() -> datetime:
    """A timezone-aware UTC ``now`` for the skill-run finalize columns."""
    return datetime.now(timezone.utc)


def _chunk_text(text: str, size: int = _CHUNK_CHARS) -> list[str]:
    """Split ``text`` into non-empty ``size``-char windows (one window for short text)."""
    stripped = (text or "").strip()
    if not stripped:
        return []
    return [stripped[i : i + size] for i in range(0, len(stripped), size)]


def run_embeddings(identity: Identity, intake_id: Any, run_id: Any) -> dict[str, Any]:
    """Embed the intake's pending ``research_artifacts`` into ``artifact_embeddings`` (AI-04).

    READ: load the intake's ``research_artifacts`` rows at ``embed_status='pending'`` into
    plain DTOs (id, space_id, text_content) — RLS confines the scan to the caller's space.
    CALL: chunk each artifact's text and embed every chunk via OpenAI
    ``text-embedding-3-small`` (``dimensions=1536``) holding NO DB connection (T-7-06).
    WRITE: in a fresh tenant session (GUC re-issued — T-7-02) insert one space-scoped
    ``artifact_embeddings`` row per chunk through :class:`ArtifactEmbeddingRepository`, flip
    each source artifact's ``embed_status`` to ``'done'`` (idempotency — re-runs find nothing
    pending), and finalize the ``skill_runs`` row ``succeeded`` (D-09).
    """
    model = get_settings().model_embeddings

    def read_fn(session: Any) -> list[dict[str, Any]]:
        # Pending-only scan (idempotency): already-'done' artifacts are skipped, so a re-run
        # produces no duplicate vectors. RLS + the GUC confine the rows to the caller's space.
        rows = session.execute(
            select(
                ResearchArtifact.id,
                ResearchArtifact.space_id,
                ResearchArtifact.text_content,
            )
            .where(ResearchArtifact.intake_id == uuid.UUID(str(intake_id)))
            .where(ResearchArtifact.embed_status == "pending")
        ).all()
        return [
            {
                "artifact_id": str(artifact_id),
                "space_id": str(space_id),
                "chunks": _chunk_text(text_content or ""),
            }
            for (artifact_id, space_id, text_content) in rows
        ]

    def call_fn(dto: list[dict[str, Any]]) -> list[dict[str, Any]]:
        # No DB connection is held across the OpenAI calls (AI-06 / T-7-06).
        client = clients.openai_client()
        embedded: list[dict[str, Any]] = []
        for artifact in dto:
            vectors: list[dict[str, Any]] = []
            for chunk in artifact["chunks"]:
                resp = client.embeddings.create(
                    model=model,
                    input=chunk,
                    dimensions=_EMBED_DIMENSIONS,  # D-02 — request 1536-dim vectors
                )
                vectors.append({"chunk_text": chunk, "embedding": resp.data[0].embedding})
            embedded.append(
                {
                    "artifact_id": artifact["artifact_id"],
                    "space_id": artifact["space_id"],
                    "vectors": vectors,
                }
            )
        return embedded

    def write_fn(
        session: Any, dto: list[dict[str, Any]], result: list[dict[str, Any]]
    ) -> dict[str, Any]:
        embed_repo = ArtifactEmbeddingRepository(session, identity)
        written = 0
        for artifact in result:
            artifact_uuid = uuid.UUID(artifact["artifact_id"])
            space_uuid = uuid.UUID(artifact["space_id"])
            for vec in artifact["vectors"]:
                values = dict(
                    artifact_id=artifact_uuid,
                    chunk_text=vec["chunk_text"],
                    embedding=vec["embedding"],
                )
                if identity.role == "superadmin":
                    # No own space — write into the artifact's OWN space (audited path).
                    embed_repo.create_in_space(space_uuid, **values)
                else:
                    # space_id injected from the verified Identity (T-7-13) — never a param.
                    embed_repo.create(**values)
                written += 1

            # Idempotency: advance the source artifact off 'pending' so re-runs skip it.
            source = session.get(ResearchArtifact, artifact_uuid)
            if source is not None:
                source.embed_status = "done"

        # Finalize the skill_runs row (D-09 terminal status — the frontend polls 'succeeded').
        SkillRunRepository(session, identity).patch(
            run_id,
            status="succeeded",
            output=f"embedded {written} chunk(s) across {len(result)} artifact(s)",
            llm_model=model,
            applied_at=_now(),
            completed_at=_now(),
        )
        return {"status": "succeeded", "embeddings_written": written}

    return run_with_session_release(identity, read_fn, call_fn, write_fn)
