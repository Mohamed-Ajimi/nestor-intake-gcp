"""Semantic search over ``artifact_embeddings`` — SIGNATURE STUB (AI-04 read half).

The route surface (07-05) fixes :func:`semantic_search`'s signature so ``ai_routes.py``
imports cleanly and the GET search endpoint is mounted today; the real query-embed +
space-prefiltered cosine scan lands in plan 07-06. The scan itself already exists as
``app.db.ai_session.search_artifacts`` (07-04, space-confined exact ``<=>``); 07-06 wires
the OpenAI query-embedding + a ``tenant_session`` around it here.

This stub raises ``NotImplementedError`` so the import is real and the contract is visible
while the body is deferred to 07-06. ``test_ai_search_cross_tenant`` / ``test_ai_search_explain``
exercise ``search_artifacts`` directly (not this seam) and stay RED until 07-06.

Grep-guard: constructs NO engine/session — the real impl opens a ``tenant_session`` and
calls ``search_artifacts`` (both live in the ``app/db`` seam).
"""

from __future__ import annotations

from typing import Any

from app.auth.identity import Identity


def semantic_search(identity: Identity, intake_id: Any, query: str, limit: int = 25) -> Any:
    """Space-confined semantic search over the caller's ``artifact_embeddings`` (AI-04).

    Filled in 07-06: embed ``query`` (OpenAI ``text-embedding-3-small``), open a
    ``tenant_session`` (GUC -> RLS prefilter), and run
    ``app.db.ai_session.search_artifacts`` to return the nearest space-scoped chunks. No
    cross-tenant rows can be returned (RLS + the explicit space prefilter — T-7-01).
    """
    raise NotImplementedError("semantic_search is implemented in plan 07-06")
