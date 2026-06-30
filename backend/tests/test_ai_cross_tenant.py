"""AI new-table cross-tenant denial (integration, RED scaffold) — T-7-01/02.

Proves the 0009 RLS extends to EVERY new AI-written table: a user scoped to
space-A can neither READ nor WRITE space-B rows in ``intake_sources`` /
``transcripts`` / ``extracted_insights``, nor in the AI-written ``skill_runs``.
Authored against the FINAL contract; RED until 07-02 (0009 migration) + 07-04
(``tenant_session``) land. Runs over REAL Postgres (``pytest.mark.integration``
— auto-skips without Docker/DATABASE_URL).

Seeds one space-B row per table (each under space-B's GUC), then opens a
``tenant_session`` AS space-A and asserts: (1) a scoped SELECT returns ZERO
space-B rows for each table (RLS read confinement), and (2) an INSERT carrying
space-B's id from the space-A session is REJECTED by the 0002/0009 WITH CHECK
(no cross-tenant write).

RED discipline: external deps ``importorskip``; impl HARD-imported.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")

identity_mod = pytest.importorskip("app.auth.identity")

from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
from app.db.ai_session import tenant_session  # noqa: E402

Identity = identity_mod.Identity
SCHEMA = "nestor"

# The AI-written tables whose tenant isolation this suite proves.
AI_TABLES = ("intake_sources", "transcripts", "extracted_insights", "skill_runs")


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _seed_space_b_rows(engine, set_space, space_b, intake_b):
    """Seed one row per AI table in space-B (each under space-B's GUC)."""
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        set_space(conn, space_b)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_sources (id, space_id, intake_id, kind) "
                "VALUES (:id, :space_id, :intake_id, 'audio')"
            ),
            {"id": source_id, "space_id": space_b, "intake_id": intake_b},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.transcripts "
                "(id, space_id, intake_id, source_id, chunk_index, text) "
                "VALUES (gen_random_uuid(), :space_id, :intake_id, :source_id, 0, 'B geheim')"
            ),
            {"space_id": space_b, "intake_id": intake_b, "source_id": source_id},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.extracted_insights "
                "(id, space_id, intake_id, kind, label, summary) "
                "VALUES (gen_random_uuid(), :space_id, :intake_id, 'pain', 'B', 'B only')"
            ),
            {"space_id": space_b, "intake_id": intake_b},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.skill_runs (id, space_id, intake_id, skill, status) "
                "VALUES (gen_random_uuid(), :space_id, :intake_id, 'apply-intake-skill', 'succeeded')"
            ),
            {"space_id": space_b, "intake_id": intake_b},
        )


def _seed_spaces(engine, set_space, space_a, space_b, intake_b):
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :n)"),
            {"id": space_a, "n": "AI cross-tenant A"},
        )
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :n)"),
            {"id": space_b, "n": "AI cross-tenant B"},
        )
    with engine.begin() as conn:
        set_space(conn, space_b)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'submitted')"
            ),
            {"id": intake_b, "space_id": space_b},
        )
    _seed_space_b_rows(engine, set_space, space_b, intake_b)


def _cleanup(engine, space_a, space_b) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
            {"a": space_a, "b": space_b},
        )


def test_user_a_cannot_read_space_b_ai_rows(
    engine, set_space, two_spaces, monkeypatch
):
    """A space-A session sees ZERO space-B rows in every AI-written table."""
    from sqlalchemy import text

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    try:
        _seed_spaces(engine, set_space, space_a, space_b, intake_b)

        with tenant_session(_user(space_a)) as session:
            for table in AI_TABLES:
                visible = session.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE space_id = :b"),
                    {"b": space_b},
                ).scalar_one()
                assert visible == 0, (
                    f"T-7-01 LEAK: space-A session can read {visible} space-B rows in "
                    f"nestor.{table} (RLS read confinement missing)."
                )
    finally:
        _cleanup(engine, space_a, space_b)


def test_user_a_cannot_write_space_b_ai_rows(
    engine, set_space, two_spaces, monkeypatch
):
    """A space-A session INSERTing a space-B-scoped row is rejected by WITH CHECK."""
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    try:
        _seed_spaces(engine, set_space, space_a, space_b, intake_b)

        # Attempt a cross-tenant write: space-A session inserts a row tagged space-B.
        with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)):
            with tenant_session(_user(space_a)) as session:
                session.execute(
                    text(
                        f"INSERT INTO {SCHEMA}.extracted_insights "
                        "(id, space_id, intake_id, kind, label, summary) "
                        "VALUES (gen_random_uuid(), :b, :intake_id, 'pain', 'X', 'forged')"
                    ),
                    {"b": space_b, "intake_id": intake_b},
                )

        # The forged row must NOT exist (re-read as space-B owner).
        with engine.begin() as conn:
            set_space(conn, space_b)
            forged = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.extracted_insights "
                    "WHERE label = 'X' AND summary = 'forged'"
                )
            ).scalar_one()
        assert forged == 0, (
            "T-7-02 LEAK: a space-A session wrote a space-B extracted_insights row."
        )
    finally:
        _cleanup(engine, space_a, space_b)
