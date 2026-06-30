"""AI-04 cross-tenant search proof (integration, RED scaffold) — T-7-01.

The marquee tenant-isolation guarantee of Phase 7: a semantic search run AS
space-A must return ZERO rows owned by space-B. Authored against the FINAL
contract; RED until 07-06 lands the search helper. Runs over REAL Postgres
(``pytest.mark.integration`` — auto-skips without Docker/DATABASE_URL).

Seeds two spaces' ``artifact_embeddings`` via the ``seed_artifact_embeddings``
fixture (each insert under its OWNING-space GUC so the 0002 RLS WITH CHECK
admits it), then opens a tenant session AS space-A and runs the search. Proven
two ways: (1) no returned chunk_text carries space-B's marker, and (2) a direct
read of space-B's seeded ids from the space-A session returns exactly zero rows
(RLS on the user engine confines the scan to the GUC space).

RED discipline: external deps ``importorskip``; impl HARD-imported. Search seam:
``app.db.ai_session.search_artifacts(session, query_vec, limit)`` (07-RESEARCH §3).
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

identity_mod = pytest.importorskip("app.auth.identity")

from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-06)
from app.db.ai_session import tenant_session, search_artifacts  # noqa: E402

Identity = identity_mod.Identity

SCHEMA = "nestor"


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _vec(seed: float) -> list[float]:
    """A deterministic 1536-float vector keyed by ``seed`` (first element)."""
    v = [0.01] * 1536
    v[0] = seed
    return v


def _create_space(conn, space_id, name) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _cleanup(engine, space_a, space_b) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
            {"a": space_a, "b": space_b},
        )


def test_search_as_space_a_returns_zero_space_b_rows(
    engine, set_space, two_spaces, monkeypatch, seed_artifact_embeddings
):
    """Search AS space-A must return zero space-B artifact rows (T-7-01)."""
    from sqlalchemy import text

    space_a, space_b = two_spaces

    # tenant_session(get_engine()) must dial the testcontainer, not Cloud SQL.
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    b_ids: list[str] = []
    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Search space A")
            _create_space(conn, space_b, "Search space B")
        # Seed each space's vectors under its OWNING-space GUC (RLS WITH CHECK).
        with engine.begin() as conn:
            set_space(conn, space_a)
            seed_artifact_embeddings(
                conn, space_a, [("A-alpha", _vec(0.9)), ("A-beta", _vec(0.8))]
            )
        with engine.begin() as conn:
            set_space(conn, space_b)
            b_ids = seed_artifact_embeddings(
                conn, space_b, [("B-secret", _vec(0.9)), ("B-private", _vec(0.85))]
            )

        # Run the search AS space-A. The query vector is close to BOTH spaces'
        # rows by construction — only RLS/prefilter keeps space-B out.
        with tenant_session(_user(space_a)) as session:
            results = search_artifacts(session, _vec(0.9), limit=50)
            chunk_texts = [getattr(r, "chunk_text", None) for r in results]

            # (1) No returned chunk carries space-B's marker.
            leaked = [c for c in chunk_texts if c and c.startswith("B-")]
            assert leaked == [], (
                f"T-7-01 LEAK: space-A search returned space-B chunks: {leaked!r}."
            )

            # (2) Direct read of space-B's ids from the space-A session -> 0 rows.
            foreign_visible = session.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.artifact_embeddings "
                    "WHERE id = ANY(:ids)"
                ),
                {"ids": b_ids},
            ).scalar_one()
            assert foreign_visible == 0, (
                f"T-7-01 LEAK: space-A session can see {foreign_visible} space-B "
                "embedding rows (RLS/prefilter not applied)."
            )
    finally:
        _cleanup(engine, space_a, space_b)
