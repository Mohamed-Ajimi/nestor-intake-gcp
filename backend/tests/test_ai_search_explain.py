"""AI-04 EXPLAIN prefilter proof (integration, RED scaffold) — Pitfall 5.

Proves the semantic-search plan applies a ``space_id`` PREFILTER (the explicit
WHERE on a superadmin path, or — on the user engine — the 0002 RLS qual
``space_id = NULLIF(current_setting('app.current_space_id', true), '')::uuid``).
Authored against the FINAL contract; RED until 07-06.

Pitfall 5 (07-RESEARCH:257): on a near-empty ``artifact_embeddings`` Postgres may
choose a Seq Scan + ``Filter: (space_id = ...)`` because it is cheaper than an
index scan on a tiny relation. So this test asserts the space_id PREDICATE is
present in the plan — it deliberately does NOT require a strict "Index Scan"
(that assertion would flap as row counts change). The authoritative isolation
guarantee is the zero-foreign-rows test in ``test_ai_search_cross_tenant.py``;
this EXPLAIN test just confirms no cross-space rows are scanned past the filter.

RED discipline: external deps ``importorskip``; impl HARD-imported.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")

identity_mod = pytest.importorskip("app.auth.identity")

from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-06)
from app.db.ai_session import tenant_session  # noqa: E402

Identity = identity_mod.Identity

SCHEMA = "nestor"


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _vec(seed: float) -> list[float]:
    v = [0.01] * 1536
    v[0] = seed
    return v


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def test_search_plan_applies_space_id_prefilter(
    engine, set_space, monkeypatch, seed_artifact_embeddings
):
    """The search EXPLAIN plan must carry a space_id predicate (not a bare scan).

    Asserts the PREFILTER is present (``space_id`` predicate OR the RLS
    ``current_setting('app.current_space_id'...)`` qual) — NOT a strict Index
    Scan (Pitfall 5: near-empty table may legitimately Seq-Scan).
    """
    from sqlalchemy import text

    space = uuid.uuid4()
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :n)"),
                {"id": space, "n": "Explain space"},
            )
        with engine.begin() as conn:
            set_space(conn, space)
            seed_artifact_embeddings(conn, space, [("A-row", _vec(0.9))])

        qvec_literal = "[" + ",".join(str(float(x)) for x in _vec(0.9)) + "]"
        with tenant_session(_user(space)) as session:
            rows = session.execute(
                text(
                    f"EXPLAIN SELECT id FROM {SCHEMA}.artifact_embeddings "
                    "ORDER BY embedding <=> CAST(:q AS vector) LIMIT 25"
                ),
                {"q": qvec_literal},
            ).all()
            plan = "\n".join(str(r[0]) for r in rows).lower()

        # The space_id prefilter shows up either as an explicit space_id predicate
        # or as the RLS qual referencing the GUC — assert EITHER is present.
        has_prefilter = "space_id" in plan or "current_setting" in plan
        assert has_prefilter, (
            "EXPLAIN plan shows no space_id prefilter / RLS qual — a cross-space "
            f"scan would not be confined. Plan was:\n{plan}"
        )
    finally:
        _cleanup(engine, space)
