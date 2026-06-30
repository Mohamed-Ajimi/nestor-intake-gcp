"""Semantic search over ``artifact_embeddings`` (AI-04 read half).

Ports ``docs/supabase-functions/semantic-search.ts`` onto the Phase-7 tenant seam: embed
the query with OpenAI ``text-embedding-3-small`` (``dimensions=1536``, D-02) and run the
space-confined exact cosine (``<=>``) scan via the 07-04 helper
:func:`app.db.ai_session.search_artifacts`.

The marquee fix this closes (T-7-01): the legacy ``match_intake_content`` filtered by
``intake_id`` ONLY — no space predicate — so a vector close to another tenant's chunk could
surface it. Here the scan runs inside :func:`tenant_session`, so on the user engine the 0002
RLS policy + the transaction-local GUC prefilter the scan to the caller's space. A user's
search can therefore NEVER return another space's artifacts (``test_ai_search_cross_tenant``
proves zero foreign rows; ``test_ai_search_explain`` proves the space_id prefilter is in the
plan). There is deliberately NO approximate-nearest-neighbour vector index this phase (D-03 /
criterion 4): exact ``<=>`` over the small per-tenant set is correct and cheap.

This is a SYNC read (NOT a background task) — the search endpoint returns results inline.

Grep-guard: constructs NO engine/session — it opens a ``tenant_session`` and calls
``search_artifacts`` (both live in the ``app/db`` seam); the query embed holds no DB
connection. No approximate-nearest-neighbour vector index is created (D-03 / criterion 4).

Source: semantic-search.ts (1536 query embed; legacy intake_id-only filter — the leak this
closes). Legacy 0.7-cosine-similarity cutoff maps to distance ``0.3`` (``distance = 1 −
similarity``), exposed param/config-driven below (default keeps every nearest row).
"""

from __future__ import annotations

from typing import Any

from app.ai import clients
from app.auth.identity import Identity
from app.core.config import get_settings
from app.db.ai_session import search_artifacts, tenant_session

# text-embedding-3-small dimensions (D-02) — the query vector MUST match the stored vectors'
# 1536 width or the ``<=>`` operator errors on a dimension mismatch.
_EMBED_DIMENSIONS = 1536


def semantic_search(
    identity: Identity,
    intake_id: Any,
    query: str,
    limit: int = 25,
    max_distance: float | None = None,
) -> list[dict[str, Any]]:
    """Space-confined semantic search over the caller's ``artifact_embeddings`` (AI-04).

    Embeds ``query`` (OpenAI ``text-embedding-3-small``, ``dimensions=1536``) holding no DB
    connection, opens ONE :func:`tenant_session` (the GUC drives the RLS prefilter), and runs
    :func:`app.db.ai_session.search_artifacts` to return the nearest space-scoped chunks. No
    cross-tenant rows can be returned (RLS + the space_id prefilter — T-7-01).

    ``max_distance`` is the legacy 0.7-cosine-similarity cutoff expressed as a cosine
    *distance* (``0.3``); ``None`` (the default) keeps every nearest row — param/config-driven
    so callers may tighten it without code changes.
    """
    model = get_settings().model_embeddings

    # CALL — embed the query holding no DB connection (the scan opens its own session below).
    resp = clients.openai_client().embeddings.create(
        model=model,
        input=query,
        dimensions=_EMBED_DIMENSIONS,  # D-02 — query vector width must match stored 1536
    )
    query_vec = resp.data[0].embedding

    # READ — one tenant-scoped session; search_artifacts applies the space-confined <=> scan.
    with tenant_session(identity) as session:
        rows = search_artifacts(session, query_vec, limit=limit, max_distance=max_distance)
        # Map the plain Row tuples to JSON-friendly dicts for the inline endpoint response.
        return [
            {
                "id": str(row.id),
                "artifact_id": str(row.artifact_id) if row.artifact_id is not None else None,
                "chunk_text": row.chunk_text,
                "distance": float(row.distance) if row.distance is not None else None,
            }
            for row in rows
        ]
