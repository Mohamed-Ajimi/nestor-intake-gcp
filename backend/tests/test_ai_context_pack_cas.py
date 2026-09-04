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


# ===========================================================================
# Task 2 — run_context_pack's allow-listed `decomposed` transition (D-23.1-05)
# ===========================================================================
#
# The allow-list has exactly ONE entry. Derived from the UI, not guessed: the
# Generate-context-pack button renders in exactly one phase, `awaiting_context_pack`
# (NextStepBanner.tsx:270), and that phase is derived from
# `status === "validated_by_client" && !intake.context_pack_artifact_id`
# (intake-phase.ts:55-58). `reviewed` maps to awaiting_validation_send /
# awaiting_client_validation and has no such button; `decomposed` maps to
# awaiting_research_start. So every status below except `validated_by_client` is a
# status from which NO caller can legitimately launch this skill.

_REFUSED_STATUSES = ["draft", "decomposed", "in_research", "delivered"]

_PACK_TEXT = "# Context Pack\n\nDe gedecomponeerde briefing."


def _as_identity(identity: "Identity"):
    def _override():
        return identity

    return _override


def _build_app():
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(ai_routes_mod.ai_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _drive_context_pack(
    engine, set_space, monkeypatch, fake_anthropic, space, intake_id, seed_status
):
    """Seed an intake at ``seed_status``, run the context-pack skill against a FAKED
    Claude (zero provider spend), and return the resulting DB rows.

    Returns ``(intake_row, skill_row, artifact_rows)`` where ``intake_row`` is
    ``(status, context_pack_artifact_id)`` and ``skill_row`` is
    ``(status, error_message, completed_at, applied_at, output)``.
    """
    from sqlalchemy import text
    from fastapi.testclient import TestClient

    fake = fake_anthropic(_PACK_TEXT)
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    app = _build_app()
    try:
        with engine.begin() as conn:
            _create_space(conn, space, f"CAS space ({seed_status})")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space, intake_id, seed_status)

        monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)
        app.dependency_overrides[get_current_identity] = _as_identity(_user(space))
        client = TestClient(app)
        resp = client.post(
            f"/intakes/{intake_id}/skills/context-pack",
            headers={"Authorization": "Bearer ignored-overridden"},
        )
        assert resp.status_code in (200, 202), (
            f"the dispatch itself must still succeed, got {resp.status_code} "
            f"(body={resp.text!r})."
        )
        assert fake.calls, "Claude must be called before the transition is evaluated."

        with engine.begin() as conn:
            set_space(conn, space)
            intake_row = conn.execute(
                text(
                    f"SELECT status, context_pack_artifact_id FROM {SCHEMA}.intakes "
                    "WHERE id = :iid"
                ),
                {"iid": intake_id},
            ).first()
            skill_row = conn.execute(
                text(
                    f"SELECT status, error_message, completed_at, applied_at, output "
                    f"FROM {SCHEMA}.skill_runs WHERE intake_id = :iid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"iid": intake_id},
            ).first()
            artifact_rows = conn.execute(
                text(
                    f"SELECT id, text_content FROM {SCHEMA}.research_artifacts "
                    "WHERE intake_id = :iid"
                ),
                {"iid": intake_id},
            ).fetchall()
        return intake_row, skill_row, artifact_rows
    finally:
        app.dependency_overrides.clear()


def test_context_pack_advances_from_validated_by_client(
    engine, set_space, monkeypatch, fake_anthropic
):
    """The ONE allow-listed source status: the artifact is written, the intake becomes
    `decomposed` and points at it, and the run is `succeeded` with applied_at set."""
    space, intake_id = uuid.uuid4(), uuid.uuid4()
    try:
        intake_row, skill_row, artifacts = _drive_context_pack(
            engine,
            set_space,
            monkeypatch,
            fake_anthropic,
            space,
            intake_id,
            "validated_by_client",
        )
        assert intake_row[0] == "decomposed", (
            f"validated_by_client must advance to decomposed, got {intake_row[0]!r}."
        )
        assert len(artifacts) == 1, f"exactly one artifact expected, got {len(artifacts)}."
        assert str(intake_row[1]) == str(artifacts[0][0]), (
            "context_pack_artifact_id must point at the new artifact."
        )
        assert skill_row[0] == "succeeded", (
            f"the allowed path must finalize succeeded, got {skill_row[0]!r}."
        )
        assert skill_row[3] is not None, "applied_at must mark the finalized output."
        assert skill_row[2] is not None, "completed_at must be set."
    finally:
        _drop_spaces(engine, space)


@pytest.mark.parametrize("seed_status", _REFUSED_STATUSES)
def test_context_pack_refuses_disallowed_source_status(
    engine, set_space, monkeypatch, fake_anthropic, seed_status
):
    """From any non-allow-listed status the intake lifecycle is left EXACTLY as it was:
    the status does not move and context_pack_artifact_id is not set.

    `decomposed` is deliberately in this set — a second run on an already-decomposed
    intake is refused, because the launching button only renders for
    validated_by_client (NextStepBanner.tsx:270 / intake-phase.ts:55).
    """
    space, intake_id = uuid.uuid4(), uuid.uuid4()
    try:
        intake_row, _skill_row, _artifacts = _drive_context_pack(
            engine, set_space, monkeypatch, fake_anthropic, space, intake_id, seed_status
        )
        assert intake_row[0] == seed_status, (
            f"LIFECYCLE CORRUPTED: an intake in {seed_status!r} was moved to "
            f"{intake_row[0]!r} by the context-pack skill."
        )
        assert intake_row[1] is None, (
            f"a refused context pack must not link an artifact, got {intake_row[1]!r}."
        )
    finally:
        _drop_spaces(engine, space)


@pytest.mark.parametrize("seed_status", _REFUSED_STATUSES)
def test_refused_context_pack_never_leaves_a_running_skill_run(
    engine, set_space, monkeypatch, fake_anthropic, seed_status
):
    """The refusal is terminal, not a silent early return (D-23.1-05 / T-23.1-14).

    An orphaned `running` row would survive until sweep_orphaned_skill_runs cleared it
    30 minutes later, and once 23.1-12's partial unique index on
    (intake_id, skill) WHERE status='running' lands, it would block every future
    context-pack run for that intake permanently.
    """
    space, intake_id = uuid.uuid4(), uuid.uuid4()
    try:
        _intake_row, skill_row, _artifacts = _drive_context_pack(
            engine, set_space, monkeypatch, fake_anthropic, space, intake_id, seed_status
        )
        assert skill_row is not None, "the skill run row must exist."
        assert skill_row[0] != "running", (
            f"ORPHAN: the refused run from {seed_status!r} was left 'running'."
        )
        assert skill_row[0] == "failed", (
            f"a refused transition must finalize 'failed', got {skill_row[0]!r}."
        )
        assert skill_row[2] is not None, (
            "completed_at must be set on the refused run — a NULL completed_at is what "
            "the orphan sweep looks for."
        )
        assert skill_row[3] is None, (
            "applied_at must NOT be set: nothing was applied to the intake."
        )

        # The index 23.1-12 will add is UNIQUE (intake_id, skill) WHERE status='running',
        # so the invariant that matters is a COUNT over the whole table for this intake,
        # not just "the newest row is terminal".
        from sqlalchemy import text

        with engine.begin() as conn:
            set_space(conn, space)
            running = conn.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.skill_runs "
                    "WHERE intake_id = :iid AND status = 'running'"
                ),
                {"iid": intake_id},
            ).scalar_one()
        assert running == 0, (
            f"ORPHAN: {running} skill_runs row(s) for this intake are still 'running' "
            f"after the refusal from {seed_status!r} — 23.1-12's partial unique index "
            "would then block every future context-pack run for it."
        )
    finally:
        _drop_spaces(engine, space)


@pytest.mark.parametrize("seed_status", _REFUSED_STATUSES)
def test_refused_context_pack_keeps_the_paid_output_unlinked(
    engine, set_space, monkeypatch, fake_anthropic, seed_status
):
    """The Claude call is already paid for by the time the transition is evaluated, so the
    artifact row is KEPT (append-only history) — just never linked onto the intake."""
    space, intake_id = uuid.uuid4(), uuid.uuid4()
    try:
        intake_row, skill_row, artifacts = _drive_context_pack(
            engine, set_space, monkeypatch, fake_anthropic, space, intake_id, seed_status
        )
        assert len(artifacts) == 1, (
            f"the paid context pack must still be persisted, got {len(artifacts)} rows."
        )
        assert artifacts[0][1] == _PACK_TEXT, "the artifact must carry the generated text."
        assert intake_row[1] is None, "...but the intake must NOT point at it."
        assert str(artifacts[0][0]) in (skill_row[4] or ""), (
            "the failed run's output must name the kept artifact's id so an operator can "
            f"find it; output={skill_row[4]!r}."
        )
    finally:
        _drop_spaces(engine, space)


@pytest.mark.parametrize("seed_status", _REFUSED_STATUSES)
def test_refusal_message_is_a_readable_sentence(
    engine, set_space, monkeypatch, fake_anthropic, seed_status
):
    """error_message names the observed status and the skill in plain language — it is
    what the operator sees in SkillRunProgress, not a stack trace."""
    space, intake_id = uuid.uuid4(), uuid.uuid4()
    try:
        _intake_row, skill_row, _artifacts = _drive_context_pack(
            engine, set_space, monkeypatch, fake_anthropic, space, intake_id, seed_status
        )
        message = skill_row[1] or ""
        assert seed_status in message, (
            f"the message must name the observed status {seed_status!r}: {message!r}"
        )
        assert "context pack" in message.lower(), (
            f"the message must name what was attempted: {message!r}"
        )
        assert "Traceback" not in message, (
            f"the refusal is not an exception and must not carry a traceback: {message!r}"
        )
    finally:
        _drop_spaces(engine, space)
