"""D-23.1-05 — the context-pack compare-and-swap, at the repo seam and end-to-end.

Two layers, one file:

1. ``TenantRepository.patch_if`` — the conditional-update primitive. It must be a SINGLE
   statement carrying BOTH the tenant scope and the precondition, must return rowcount 0
   (never raise) when the precondition does not hold, and must not weaken the TENANT-02
   wall by adding that second predicate.
2. ``run_context_pack`` — the allow-listed ``decomposed`` transition. The skill may only
   advance an intake from ``validated_by_client``; from every other status it REFUSES,
   leaves the intake lifecycle untouched, keeps the paid Claude output as an (unlinked)
   ``research_artifacts`` row, and finalizes its ``skill_runs`` row ``failed`` — never
   ``running``. An orphaned ``running`` row is the exact failure D-23.1-05 forbids, and
   once 23.1-12 lands its partial unique index that orphan would block every future
   context-pack run for that intake permanently.

ZERO provider spend: every end-to-end case drives the ``fake_anthropic`` fixture.
"""

from __future__ import annotations

import uuid

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("firebase_admin")
pytest.importorskip("fastapi")

repository = pytest.importorskip("app.db.repository")
identity_mod = pytest.importorskip("app.auth.identity")
dependencies = pytest.importorskip("app.auth.dependencies")

from app.api import ai_routes as ai_routes_mod  # noqa: E402
from app.db import ai_session as ai_session_mod  # noqa: E402
import app.ai.clients as ai_clients_mod  # noqa: E402

pytestmark = pytest.mark.integration

IntakeRepository = repository.IntakeRepository
Identity = identity_mod.Identity
get_current_identity = dependencies.get_current_identity

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Shared helpers (two-space seeding shape copied from test_tenant_repository.py)
# ---------------------------------------------------------------------------


def _user(space_id: uuid.UUID) -> "Identity":
    """A fabricated ``user`` Identity scoped to one space (space_id as a str claim)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID, status: str) -> None:
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
            "VALUES (:id, :space_id, CAST(:status AS nestor.intake_status))"
        ),
        {"id": intake_id, "space_id": space_id, "status": status},
    )


def _drop_spaces(engine, *space_ids: uuid.UUID) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        for space_id in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
                {"id": space_id},
            )


def _intake_row(engine, set_space, space_id, intake_id):
    """Return ``(status, context_pack_artifact_id)`` for an intake, read under its GUC."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(
                f"SELECT status, context_pack_artifact_id FROM {SCHEMA}.intakes "
                "WHERE id = :iid"
            ),
            {"iid": intake_id},
        ).first()


# ===========================================================================
# Task 1 — TenantRepository.patch_if
# ===========================================================================


def test_patch_if_applies_when_precondition_holds(engine, set_space, two_spaces):
    """Matching expected value -> rowcount 1 and every written value is persisted."""
    from sqlalchemy.orm import Session

    space_a, _ = two_spaces
    intake_id = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (patch_if hit)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_id, "validated_by_client")

        with engine.begin() as conn:
            set_space(conn, space_a)
            repo = IntakeRepository(Session(bind=conn), _user(space_a))
            rowcount = repo.patch_if(
                intake_id, expected={"status": "validated_by_client"}, status="decomposed"
            )
        assert rowcount == 1, (
            f"patch_if must affect exactly 1 row when the precondition holds, got {rowcount}."
        )

        row = _intake_row(engine, set_space, space_a, intake_id)
        assert row is not None and row[0] == "decomposed", (
            f"the matched patch_if must persist status='decomposed', got {row!r}."
        )
    finally:
        _drop_spaces(engine, space_a)


def test_patch_if_is_a_noop_when_precondition_fails(engine, set_space, two_spaces):
    """Mismatched expected value -> rowcount 0 and EVERY written column is unchanged."""
    from sqlalchemy.orm import Session

    space_a, _ = two_spaces
    intake_id = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (patch_if miss)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_id, "delivered")

        from sqlalchemy import text

        # Snapshot BOTH columns the refused call would write. client_name is NOT NULL
        # here: 0004's tg_seed_client_name trigger mirrors the organization name onto
        # it at INSERT, so "unchanged" means "equal to this snapshot", not "NULL".
        with engine.begin() as conn:
            set_space(conn, space_a)
            before = conn.execute(
                text(f"SELECT status, client_name FROM {SCHEMA}.intakes WHERE id = :iid"),
                {"iid": intake_id},
            ).first()

        with engine.begin() as conn:
            set_space(conn, space_a)
            repo = IntakeRepository(Session(bind=conn), _user(space_a))
            rowcount = repo.patch_if(
                intake_id,
                expected={"status": "validated_by_client"},
                status="decomposed",
                client_name="SHOULD-NOT-BE-WRITTEN",
            )
        assert rowcount == 0, (
            f"patch_if must affect 0 rows when the precondition fails, got {rowcount}."
        )

        with engine.begin() as conn:
            set_space(conn, space_a)
            after = conn.execute(
                text(
                    f"SELECT status, client_name FROM {SCHEMA}.intakes WHERE id = :iid"
                ),
                {"iid": intake_id},
            ).first()
        # Assert every column the refused call would have written, not only the compared one.
        assert after[0] == "delivered", (
            f"a refused patch_if must leave status untouched, got {after[0]!r}."
        )
        assert after[1] == before[1], (
            f"a refused patch_if must write NO column, but client_name went "
            f"{before[1]!r} -> {after[1]!r}."
        )
        assert after[1] != "SHOULD-NOT-BE-WRITTEN", (
            "the refused patch_if's SET clause was applied despite rowcount 0."
        )
    finally:
        _drop_spaces(engine, space_a)


def test_patch_if_cross_tenant_row_is_untouched(engine, set_space, two_spaces):
    """The tenant scope still applies: a foreign id is rowcount 0 even with a MATCHING
    precondition — the extra predicate must not weaken the TENANT-02 wall (T-23.1-15)."""
    from sqlalchemy.orm import Session

    space_a, space_b = two_spaces
    intake_b = uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (patch_if cross)")
            _create_space(conn, space_b, "Space B (patch_if cross)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b, "validated_by_client")

        # space_a Identity, GUC set to space_b so RLS would ADMIT the row: only the repo's
        # explicit WHERE can exclude it. The precondition MATCHES, so a rowcount of 1 here
        # would mean the scope was lost.
        with engine.begin() as conn:
            set_space(conn, space_b)
            repo = IntakeRepository(Session(bind=conn), _user(space_a))
            rowcount = repo.patch_if(
                intake_b, expected={"status": "validated_by_client"}, status="decomposed"
            )
        assert rowcount == 0, (
            "TENANT-02 BROKEN: patch_if updated a foreign space's row "
            f"(rowcount={rowcount}) — the scoped WHERE was lost."
        )

        row = _intake_row(engine, set_space, space_b, intake_b)
        assert row[0] == "validated_by_client", (
            f"the foreign row must be untouched, got status {row[0]!r}."
        )
    finally:
        _drop_spaces(engine, space_a, space_b)


def test_patch_if_missing_row_returns_zero_and_never_raises(engine, set_space, two_spaces):
    """An id that does not exist -> rowcount 0, no exception (existence hiding, D-07)."""
    from sqlalchemy.orm import Session

    space_a, _ = two_spaces

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (patch_if missing)")

        with engine.begin() as conn:
            set_space(conn, space_a)
            repo = IntakeRepository(Session(bind=conn), _user(space_a))
            rowcount = repo.patch_if(
                uuid.uuid4(), expected={"status": "validated_by_client"}, status="decomposed"
            )
        assert rowcount == 0, (
            f"patch_if on a nonexistent id must return 0, got {rowcount}."
        )
    finally:
        _drop_spaces(engine, space_a)


def test_patch_if_emits_both_predicates_in_one_statement(engine, set_space, two_spaces):
    """The UPDATE actually sent to Postgres carries the tenant, id AND expected-value
    predicates — asserted on the EMITTED SQL, not on the module source (a source grep
    would match the docstring and go vacuous)."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    space_a, _ = two_spaces
    intake_id = uuid.uuid4()
    statements: list[str] = []

    def _capture(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        statements.append(statement)

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (patch_if sql)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_id, "validated_by_client")

        event.listen(engine, "before_cursor_execute", _capture)
        try:
            with engine.begin() as conn:
                set_space(conn, space_a)
                repo = IntakeRepository(Session(bind=conn), _user(space_a))
                repo.patch_if(
                    intake_id,
                    expected={"status": "validated_by_client"},
                    status="decomposed",
                )
        finally:
            event.remove(engine, "before_cursor_execute", _capture)

        updates = [
            " ".join(s.split()).lower()
            for s in statements
            if s.lstrip().upper().startswith("UPDATE")
        ]
        assert len(updates) == 1, (
            f"patch_if must be ONE statement, not read-then-write; captured {updates!r}."
        )
        sql = updates[0]
        for predicate in ("intakes.id =", "intakes.status =", "intakes.space_id ="):
            assert predicate in sql, (
                f"the emitted UPDATE is missing the {predicate!r} predicate: {sql!r}"
            )
    finally:
        _drop_spaces(engine, space_a)
