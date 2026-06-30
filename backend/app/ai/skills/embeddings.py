"""``generate-embeddings`` / ``embed-artifact`` port — SIGNATURE STUB (AI-04 write half).

The route surface (07-05) fixes this function's signature so ``ai_routes.py`` imports
cleanly and dispatches the background task today; the real OpenAI embedding write lands in
plan 07-06 (``test_ai_embeddings.py`` is RED until then). This stub raises
``NotImplementedError`` so the import is real and the contract is visible, while the body
is deliberately left for 07-06.

Grep-guard: constructs NO engine/session — the real impl will go through
``run_with_session_release`` + the ``ArtifactEmbeddingRepository`` wall.
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def run_embeddings(identity: Identity, intake_id: Any, run_id: Any) -> Any:
    """Embed the intake's pending ``research_artifacts`` into ``artifact_embeddings`` (AI-04).

    Filled in 07-06: read the pending artifact text, call OpenAI
    ``text-embedding-3-small`` (``dimensions=1536``, D-02) holding no connection, then in a
    fresh tenant session write space-scoped ``artifact_embeddings`` rows and advance the
    source artifact's ``embed_status`` off ``pending``.
    """
    raise NotImplementedError("run_embeddings is implemented in plan 07-06")
