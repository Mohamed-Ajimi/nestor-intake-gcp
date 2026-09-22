"""Guarded hard-delete suite (D-23.5-02) — plan 23.5-02.

WHAT THIS FILE PROVES. Tester remark 3 of phase 23.5 is "be able to archive/delete a
project". Archive is remark 1's override verb reaching ``archived`` (plan 23.5-01). THIS
file covers the other half: ``DELETE /intakes/{id}`` — an irreversible destruction — and
its eligibility read ``GET /intakes/{id}/deletable``.

THE WALL THAT DEFINES THE VERB (D-23.5-02). An intake with ANY ``research_runs`` row can
NEVER be hard-deleted. A Tribunal run costs real money (~$40 at the 2026-09 figures) and
drags a whole audit chain behind it — findings, claims, sources, the audit bundle in GCS.
Archive is the only destructive action available once research exists. The 409 is checked
BEFORE any object key is collected and BEFORE the audit row is written, so a refused
delete has ZERO side effects: nothing in the DB moved and nothing was handed to GCS.

| Test family                          | Proves                                            |
|--------------------------------------|---------------------------------------------------|
| ``*_cascade``                        | 204, and the intake + answers + skill runs +      |
|                                      | sources + transcripts + artifacts are ALL gone —  |
|                                      | the DB's ``ON DELETE CASCADE`` fans the one       |
|                                      | DELETE out through every child table.             |
| ``*_blocked_by_research_run``        | 409 and EVERY row above still exists.             |
| ``*_deletable_*``                    | the eligibility read agrees with the wall, and    |
|                                      | never becomes an existence oracle.                |
| ``*_audit_row_survives``             | an ``intake.deleted`` row exists AFTER the        |
|                                      | cascade — ``audit_log`` has no FK to              |
|                                      | ``nestor.intakes`` so the trail outlives its      |
|                                      | subject. Asserted, not assumed.                   |
| ``*_gcs_prefix``                     | the recorded ``delete_object`` key set EXACTLY    |
|                                      | equals the prefix-valid keys. A seeded            |
|                                      | out-of-prefix ``storage_path`` reaches the seam   |
|                                      | NEVER.                                            |
| ``*_user_role_404``                  | role=``user`` IN THE INTAKE'S OWN SPACE gets      |
|                                      | EXACTLY 404 on BOTH routes, and the intake is     |
|                                      | still there afterwards.                           |
| ``*_null_space_404``                 | the ORDERING proof: a null-space ``user`` gets    |
|                                      | the gate's 404, NOT ``get_tenant_repo``'s 403.    |
| ``*_cross_tenant_404``               | user-A -> space-B's intake is 404 and B's intake  |
|                                      | is still there.                                   |
| ``*_missing_intake_404``             | a superadmin targeting an id that does not exist  |
|                                      | gets 404 (``repo.get`` -> None), not a 500.       |

WHY THERE IS NO "SUPERADMIN CROSS-TENANT 404" ARM — the same reasoning
``test_status_override.py`` records, and it is worth repeating because the plan's
behaviour list asked for one. A superadmin's repo is the ``app_superadmin`` engine with
the 0003 bypass policy (``session.get_tenant_repo``, D-05): cross-tenant reach IS the
operator's designed authority, and every other operator verb behaves that way. Asserting
a superadmin gets 404 for a foreign intake would pin the OPPOSITE of the platform's
contract. The existence-hidden denials that matter here are the ROLE gate (the ``user``
arms) and the non-existent-id arm, and both are covered above.

HARNESS PROVENANCE. The drive-the-real-route + fabricated-Identity + engine-factory-patch
scaffold, ``superadmin_engine``, ``_insert_intake_status``, ``_count_audit`` and
``_cleanup_spaces`` are COPIED (never imported — no private symbol crosses a test module,
matching the convention in ``test_operator_verb_gate.py``) from
``test_status_override.py`` / ``test_operator_verb_gate.py`` / ``test_storage_delete.py``.
The GCS recorder is conftest's ``fake_gcs`` fixture.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker/DATABASE_URL);
``importorskip`` guards so the file COLLECTS on a box without the backend deps.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")
audit_models = pytest.importorskip("app.db.models.audit")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity
AuditLog = audit_models.AuditLog

SCHEMA = "nestor"
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Password granted to the app_superadmin role for the connect-as superadmin engine (test
#: only — the SAME literal test_operator_verb_gate / test_status_override use, so the
#: role's password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

#: The child tables this suite asserts the cascade over. Each declares
#: ``ForeignKey("nestor.intakes.id", ondelete="CASCADE")`` (verified in
#: ``app/db/models/``), so the ONE ``DELETE FROM nestor.intakes`` is expected to take all
#: of them. Listed here by name so the assertion reads as a table, and so adding a new
#: child table to the schema without adding it here is a visible omission rather than a
#: silent gap.
_CASCADE_CHILD_TABLES = (
    "intake_answers",
    "skill_runs",
    "intake_sources",
    "transcripts",
    "research_artifacts",
)


# ---------------------------------------------------------------------------
# Identity fabrication (no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the D-04 default-deny case ``get_tenant_repo`` 403s."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="super-delete", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the ``session.py`` and ``ai_session.py`` engine factories (both namespaces)."""
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in both namespaces (the superadmin happy-path arms)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach.
    Shape copied from ``test_status_override.superadmin_engine``.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD "
                f"'{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


# ---------------------------------------------------------------------------
# Seeding / reading helpers (copied, never imported — see the module docstring)
# ---------------------------------------------------------------------------


def _create_space(conn, space_id, name: str) -> None:
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id, intake_id, status: str = "decomposed") -> None:
    """Insert one intake at an EXPLICIT status (GUC set so the 0002 WITH CHECK passes)."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status, client_name) "
            "VALUES (:id, :space_id, :status, 'Acme')"
        ),
        {"id": intake_id, "space_id": space_id, "status": status},
    )


def _insert_answer(conn, set_space, space_id, intake_id, field_key: str) -> None:
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intake_answers (space_id, intake_id, field_key, value) "
            "VALUES (:space_id, :intake_id, :field_key, 'x')"
        ),
        {"space_id": space_id, "intake_id": intake_id, "field_key": field_key},
    )


def _insert_skill_run(conn, set_space, space_id, intake_id) -> uuid.UUID:
    from sqlalchemy import text

    run_id = uuid.uuid4()
    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.skill_runs (id, space_id, intake_id, skill, status) "
            "VALUES (:id, :space_id, :intake_id, 'apply-intake-skill', 'succeeded')"
        ),
        {"id": run_id, "space_id": space_id, "intake_id": intake_id},
    )
    return run_id


def _insert_source(conn, set_space, space_id, intake_id, storage_path) -> uuid.UUID:
    from sqlalchemy import text

    source_id = uuid.uuid4()
    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intake_sources "
            "(id, space_id, intake_id, kind, storage_path, file_name) "
            "VALUES (:id, :space_id, :intake_id, 'document', :path, 'f.pdf')"
        ),
        {
            "id": source_id,
            "space_id": space_id,
            "intake_id": intake_id,
            "path": storage_path,
        },
    )
    return source_id


def _insert_transcript(conn, set_space, space_id, intake_id, source_id) -> None:
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.transcripts "
            "(space_id, intake_id, source_id, chunk_index, text) "
            "VALUES (:space_id, :intake_id, :source_id, 0, 'hello')"
        ),
        {"space_id": space_id, "intake_id": intake_id, "source_id": source_id},
    )


def _insert_artifact(conn, set_space, space_id, intake_id, storage_path, source="human-report"):
    from sqlalchemy import text

    artifact_id = uuid.uuid4()
    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.research_artifacts "
            "(id, space_id, intake_id, source, artifact_type, storage_path, filename) "
            "VALUES (:id, :space_id, :intake_id, :source, 'report', :path, 'r.pdf')"
        ),
        {
            "id": artifact_id,
            "space_id": space_id,
            "intake_id": intake_id,
            "source": source,
            "path": storage_path,
        },
    )
    return artifact_id


def _insert_research_run(conn, set_space, space_id, intake_id, status: str = "completed"):
    from sqlalchemy import text

    run_id = uuid.uuid4()
    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.research_runs (id, space_id, intake_id, status, attempt) "
            "VALUES (:id, :space_id, :intake_id, :status, 1)"
        ),
        {"id": run_id, "space_id": space_id, "intake_id": intake_id, "status": status},
    )
    return run_id


def _intake_exists(engine, set_space, space_id, intake_id) -> bool:
    """Re-read the intake AS ITS OWNER (space GUC set) — True when the row is still there."""
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return (
            conn.execute(
                text(f"SELECT 1 FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_id},
            ).scalar_one_or_none()
            is not None
        )


def _child_counts(engine, set_space, space_id, intake_id) -> dict:
    """Count every cascade child of ONE intake, read as its owner. Keys: table names."""
    from sqlalchemy import text

    counts = {}
    with engine.begin() as conn:
        set_space(conn, space_id)
        for table in _CASCADE_CHILD_TABLES:
            counts[table] = conn.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.{table} WHERE intake_id = :id"),
                {"id": intake_id},
            ).scalar_one()
    return counts


def _count_research_runs(engine, set_space, space_id, intake_id) -> int:
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.research_runs WHERE intake_id = :id"),
            {"id": intake_id},
        ).scalar_one()


def _delete_audit_rows(engine, space_id, target):
    """Return the ``event_metadata`` of every ``intake.deleted`` row for ONE intake.

    The ``target`` filter is load-bearing (copied reasoning from
    ``test_status_override._status_audit_rows``): the conftest ``engine`` connects as the
    migration owner, for which the audit read is NOT space-filtered, so a query filtered
    only by ``event_type`` would see every sibling test's rows and make "exactly one"
    depend on collection order.
    """
    from sqlalchemy import select, text

    with engine.connect() as conn:
        conn.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )
        return [
            row[0]
            for row in conn.execute(
                select(AuditLog.event_metadata)
                .where(AuditLog.event_type == "intake.deleted")
                .where(AuditLog.target == str(target))
            ).all()
        ]


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + intake_router."""
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router
    from app.api.intake_routes import intake_router

    protected_router.include_router(intake_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


def _cleanup_spaces(engine, *space_ids) -> None:
    """Delete the seeded organizations AND this suite's audit rows.

    ``audit_log.space_id`` is a plain nullable column with NO ForeignKey, deliberately, so
    the trail outlives its space (``models/audit.py``) — dropping the organization does NOT
    cascade the rows away. Leaving them behind would turn a globally-counting sibling test
    red purely on collection order (measured precedent: ``test_operator_verb_gate``).
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        for sid in space_ids:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.audit_log WHERE space_id = :id"), {"id": sid}
            )
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"), {"id": sid}
            )


# ---------------------------------------------------------------------------
# The scenario context manager — one fully-populated space/intake per case
# ---------------------------------------------------------------------------


class _Scenario:
    def __init__(self, app, space_id, intake_id, keys, foreign_key):
        self.app = app
        self.space_id = space_id
        self.intake_id = intake_id
        #: the PREFIX-VALID object keys seeded on this intake's rows
        self.keys = keys
        #: a storage_path seeded on THIS intake's source row that points OUTSIDE the
        #: intake's own prefix — the forged/legacy shape the prefix wall must drop
        self.foreign_key = foreign_key

    def client(self):
        from fastapi.testclient import TestClient

        # raise_server_exceptions=False so an unexpected handler fault surfaces as a 500
        # RESPONSE this suite can assert on, rather than a traceback that hides the status
        # a real caller would have seen.
        return TestClient(self.app, raise_server_exceptions=False)


@contextmanager
def _scenario(
    engine,
    set_space,
    monkeypatch,
    identity,
    *,
    sa_engine=None,
    with_research_run=False,
    status="decomposed",
):
    """Seed a space + a FULLY POPULATED intake; wire the overrides; always clean up.

    "Fully populated" is the point: one answer, one skill run, two sources (one of them
    with an OUT-OF-PREFIX ``storage_path``), one transcript hanging off a source, and two
    research artifacts (one of which carries a NULL ``storage_path``, the shape a
    text-only artifact has). A cascade assertion over an empty intake proves nothing.

    ``identity`` is either a ready ``Identity`` (null-space / superadmin arms) or a
    CALLABLE taking the freshly-minted ``space_id`` — which is how the ``user``-role arms
    get an identity scoped to the intake's OWN space. That scoping is the point: a
    cross-space user is already 404'd by ``repo.get``, so only an OWN-SPACE user proves
    the ROLE gate.
    """
    space_id = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    prefix = f"{space_id}/{intake_id}/"
    attachment_key = f"{prefix}attachments/{uuid.uuid4()}-brief.pdf"
    audio_key = f"{prefix}audio/{uuid.uuid4()}-call.m4a"
    report_key = f"{prefix}reports/{uuid.uuid4()}-final.pdf"
    # Deliberately OUTSIDE this intake's prefix: another space, another intake. A row like
    # this is what a forged write or a legacy import leaves behind, and it must never be
    # handed to gcs.delete_object no matter what the DB says.
    foreign_key = f"{uuid.uuid4()}/{uuid.uuid4()}/attachments/{uuid.uuid4()}-other.pdf"
    try:
        with engine.begin() as conn:
            _create_space(conn, space_id, "Intake delete space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_id, intake_id, status)
            # The 0008 AFTER-INSERT prefill trigger already writes a client_name answer;
            # a second explicit one makes the count unambiguous.
            _insert_answer(conn, set_space, space_id, intake_id, "explicit_field")
            _insert_skill_run(conn, set_space, space_id, intake_id)
            source_id = _insert_source(
                conn, set_space, space_id, intake_id, attachment_key
            )
            _insert_source(conn, set_space, space_id, intake_id, audio_key)
            _insert_source(conn, set_space, space_id, intake_id, foreign_key)
            _insert_transcript(conn, set_space, space_id, intake_id, source_id)
            _insert_artifact(conn, set_space, space_id, intake_id, report_key)
            # storage_path NULL — a text-only artifact. Must be skipped without raising.
            _insert_artifact(
                conn, set_space, space_id, intake_id, None, source="context-pack-generator"
            )
            if with_research_run:
                _insert_research_run(conn, set_space, space_id, intake_id)

        _patch_engine_factories(monkeypatch, engine)
        if sa_engine is not None:
            _patch_superadmin_engine(monkeypatch, sa_engine)
        resolved = identity(space_id) if callable(identity) else identity
        app.dependency_overrides[get_current_identity] = _as(resolved)

        yield _Scenario(
            app,
            space_id,
            intake_id,
            {attachment_key, audio_key, report_key},
            foreign_key,
        )
    finally:
        app.dependency_overrides.clear()
        _cleanup_spaces(engine, space_id)


def _assert_denied(resp, label: str) -> None:
    """EXACTLY 404 with the gate's byte-exact detail — never 403 / 401 / 422 / 500."""
    assert resp.status_code == 404, (
        f"{label}: an unauthorized caller must get EXACTLY 404 (existence-hidden, "
        f"D-23.1-02), got {resp.status_code} ({resp.text!r}). A 403 is an existence "
        f"oracle; a 422 would mean the body was malformed and the denial proved nothing."
    )
    assert resp.json().get("detail") == "Intake not found", (
        f"{label}: the 404 detail is part of the convention and is asserted byte-exact "
        f"(app/auth/gates.py), got {resp.json()!r}"
    )


# ===========================================================================
# (0) the constants + the schema facts the handler leans on — no DB
# ===========================================================================


def test_delete_blocked_detail_is_a_single_module_constant():
    """``_DELETE_BLOCKED_DETAIL`` exists and is the literal the 409 carries.

    The message is a client-facing contract string (the frontend keys the "cannot delete"
    affordance off the eligibility read, and the 409 is the server-side twin). Pinning it
    here means a reword is a deliberate, visible change rather than a silent break of the
    two consumers.
    """
    routes = pytest.importorskip("app.api.intake_routes")

    assert routes._DELETE_BLOCKED_DETAIL == (
        "Intake has research runs and cannot be deleted"
    )


def test_audit_log_has_no_foreign_key_to_intakes():
    """The audit row outlives the intake BECAUSE there is no FK to cascade it away.

    This is the load-bearing schema fact behind ``test_delete_audit_row_survives...``. If
    someone ever adds ``ForeignKey("nestor.intakes.id", ondelete="CASCADE")`` to
    ``audit_log``, the deletion trail would be destroyed by the very act it records — and
    the behavioural test would go green-then-red in a confusing way. Assert the CAUSE.
    """
    audit_mod = pytest.importorskip("app.db.models.audit")

    targets = {
        fk.target_fullname
        for column in audit_mod.AuditLog.__table__.columns
        for fk in column.foreign_keys
    }
    assert not any(t.startswith("nestor.intakes") for t in targets), (
        f"audit_log must NOT reference nestor.intakes — found {sorted(targets)}. The "
        "deletion audit row has to survive the cascade it records (D-23.5-02)."
    )


def test_every_cascade_child_declares_ondelete_cascade_to_intakes():
    """Each child table this suite counts really does declare ``ondelete='CASCADE'``.

    The handler issues ONE ``DELETE FROM nestor.intakes`` and relies entirely on the DB to
    fan it out. That reliance is an assumption about the schema, so it is asserted rather
    than trusted: a child whose FK was written without ``ondelete`` would make the delete
    fail with a 23503 at runtime, not silently orphan rows — but this pins WHY.
    """
    pytest.importorskip("sqlalchemy")
    from app.db.base import Base

    import app.db.models  # noqa: F401 -- import side effect: register every mapper

    for table_name in _CASCADE_CHILD_TABLES:
        table = Base.metadata.tables[f"{SCHEMA}.{table_name}"]
        intake_fks = [
            fk
            for column in table.columns
            for fk in column.foreign_keys
            if fk.target_fullname == f"{SCHEMA}.intakes.id"
        ]
        assert intake_fks, f"{table_name} has no FK to {SCHEMA}.intakes"
        for fk in intake_fks:
            assert fk.ondelete == "CASCADE", (
                f"{table_name}.{fk.parent.name} -> intakes.id declares "
                f"ondelete={fk.ondelete!r}; the hard delete depends on CASCADE."
            )


# ===========================================================================
# (a) the happy path — 204, the cascade, the audit row, the GCS prefix wall
# ===========================================================================


def test_delete_cascades_every_child_row(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """204, and the intake plus EVERY cascade child is gone afterwards.

    The pre-assertion matters as much as the post: without it, a scenario that silently
    failed to seed would make the "all zero" assertion vacuously true.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        before = _child_counts(engine, set_space, s.space_id, s.intake_id)
        assert all(before[t] > 0 for t in _CASCADE_CHILD_TABLES), (
            f"the scenario did not seed every child table: {before} — the cascade "
            "assertion below would be vacuously true."
        )

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        assert resp.status_code == 204, (
            f"a never-researched intake must delete with 204, got {resp.status_code} "
            f"({resp.text!r})"
        )
        assert not _intake_exists(engine, set_space, s.space_id, s.intake_id), (
            "the response said 204 but the intake row is still there."
        )
        after = _child_counts(engine, set_space, s.space_id, s.intake_id)
        assert after == {t: 0 for t in _CASCADE_CHILD_TABLES}, (
            f"the ON DELETE CASCADE did not take every child: {after}"
        )


def test_delete_writes_an_audit_row_that_survives_the_cascade(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """Exactly one ``intake.deleted`` row exists AFTER the intake is gone.

    Destruction with no trace is the repudiation threat (T-23.5-02-R). The row is written
    on ``repo.session`` BEFORE the delete so it shares the transaction, and it survives
    because ``audit_log`` has no FK to ``nestor.intakes`` (pinned separately above).
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)
        assert resp.status_code == 204, resp.text

        rows = _delete_audit_rows(engine, s.space_id, s.intake_id)
        assert len(rows) == 1, (
            f"expected EXACTLY one intake.deleted audit row, got {len(rows)}: {rows}"
        )
        meta = rows[0]
        assert meta.get("status") == "decomposed", (
            f"the audit metadata must record the status the intake died at, got {meta!r}"
        )
        assert meta.get("objects") == 3, (
            f"the audit metadata must record how many objects were queued for deletion, "
            f"got {meta!r}"
        )
        assert meta.get("objects_skipped") == 1, (
            "the ONE out-of-prefix storage_path must be counted as skipped, so the trail "
            f"shows an object was deliberately left alone; got {meta!r}"
        )


def test_delete_only_passes_prefix_valid_keys_to_the_storage_seam(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """The recorded ``delete_object`` key set EXACTLY equals the prefix-valid keys.

    SET EQUALITY, not a count and not ``len(...) > 0``: a count would pass on a handler
    that deleted three of the WRONG keys, and a non-empty check would pass on almost
    anything. T-delete-cascade is the threat — object keys read out of DB rows crossing
    into a destructive seam call — and the only honest proof is naming every key that was
    and was not passed.

    The out-of-prefix row is seeded on THIS intake deliberately: the DB says it belongs
    here, and the handler must still refuse to act on it. Keys are enumerated from DB rows
    only; ``app.storage.gcs`` has no list function and this plan added none, so a bucket
    listing (a new cross-tenant read surface) is structurally impossible here.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)
        assert resp.status_code == 204, resp.text

        recorded = {call["key"] for call in fake_gcs["deletes"]}
        assert set(recorded) == set(s.keys), (
            f"the storage seam saw {sorted(recorded)}; the intake's own prefix-valid keys "
            f"are {sorted(s.keys)}."
        )
        assert s.foreign_key not in recorded, (
            f"{s.foreign_key!r} sits outside {s.space_id}/{s.intake_id}/ and must NEVER "
            "reach gcs.delete_object — that would be a cross-tenant destruction."
        )


def test_deletable_is_true_for_an_intake_with_no_research_runs(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The eligibility read agrees with the wall on the allowed side."""
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/deletable", headers=_HDR)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deletable": True, "reason": None}


# ===========================================================================
# (b) the money wall — any research run means 409, with zero side effects
# ===========================================================================


def test_delete_is_409_when_a_research_run_exists_and_nothing_is_destroyed(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """409, and the intake, its children, its run row and its objects ALL survive.

    D-23.5-02: paid research and its audit chain must survive. The status code alone is
    the weak form of this test — the assertions that matter are that NOTHING moved. The
    run check is placed before key collection and before the audit write precisely so a
    refused delete is a no-op rather than a partially-executed destruction.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=True,
    ) as s:
        before = _child_counts(engine, set_space, s.space_id, s.intake_id)

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        assert resp.status_code == 409, (
            f"an intake with a research run must be refused with EXACTLY 409, got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["detail"] == (
            "Intake has research runs and cannot be deleted"
        )
        assert _intake_exists(engine, set_space, s.space_id, s.intake_id), (
            "the 409 leaked through — the researched intake was destroyed."
        )
        assert _child_counts(engine, set_space, s.space_id, s.intake_id) == before, (
            "a refused delete must leave every child row exactly as it was."
        )
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 1, (
            "the research_runs row — the paid work and its audit chain — is gone."
        )
        assert fake_gcs["deletes"] == [], (
            f"a refused delete must hand NOTHING to the storage seam, got "
            f"{fake_gcs['deletes']!r}"
        )
        assert _delete_audit_rows(engine, s.space_id, s.intake_id) == [], (
            "a refused delete must not write an intake.deleted audit row."
        )


def test_deletable_is_false_with_reason_when_a_research_run_exists(
    engine, set_space, monkeypatch, superadmin_engine
):
    """The eligibility read agrees with the wall on the refused side, and says WHY.

    The ``reason`` is a stable machine token (``has_research_runs``), not prose: the
    frontend renders its own localized copy off it, so a reworded English sentence must
    never change what the UI can key on.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=True,
    ) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/deletable", headers=_HDR)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deletable": False, "reason": "has_research_runs"}


# ===========================================================================
# (c) the role gate — a user in the intake's OWN space is 404 on both routes
# ===========================================================================


def test_delete_user_role_404_and_the_intake_survives(
    engine, set_space, monkeypatch, fake_gcs
):
    """role=``user``, own space, gets EXACTLY 404 — and nothing was destroyed."""
    with _scenario(engine, set_space, monkeypatch, _user) as s:
        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        _assert_denied(resp, "DELETE /intakes/{id} as role=user")
        assert _intake_exists(engine, set_space, s.space_id, s.intake_id), (
            "the gate returned 404 but the intake was deleted anyway."
        )
        assert fake_gcs["deletes"] == [], "a denied caller must not reach the GCS seam"
        assert _delete_audit_rows(engine, s.space_id, s.intake_id) == []


def test_deletable_user_role_404(engine, set_space, monkeypatch):
    """The eligibility read is gated too — it must not become an existence oracle.

    T-23.5-02-I: a client user who could ask "is this intake deletable?" and get a truthful
    answer would learn the intake exists and how much research it has had. Same 404, same
    detail as every other intake denial.
    """
    with _scenario(engine, set_space, monkeypatch, _user) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/deletable", headers=_HDR)
        _assert_denied(resp, "GET /intakes/{id}/deletable as role=user")


@pytest.mark.parametrize(
    "method,suffix",
    [("delete", ""), ("get", "/deletable")],
)
def test_null_space_user_gets_the_gates_404_not_the_repos_403(
    engine, set_space, monkeypatch, method, suffix
):
    """The ORDERING proof, on BOTH new routes.

    ``get_tenant_repo`` answers a null-space user with the D-04 default-deny **403**.
    FastAPI resolves a handler signature IN ORDER, so if ``Depends(get_tenant_repo)`` were
    declared before ``Depends(superadmin_gate)`` the repo's 403 would win — and a 403 where
    404 is the convention tells an unauthorized caller the endpoint EXISTS.
    """
    with _scenario(engine, set_space, monkeypatch, _null_space_user()) as s:
        resp = getattr(s.client(), method)(
            f"/intakes/{s.intake_id}{suffix}", headers=_HDR
        )
        assert resp.status_code != 403, (
            f"{method.upper()} /intakes/{{id}}{suffix}: a null-space user got the repo's "
            "403 — the gate is declared AFTER get_tenant_repo, which turns the denial into "
            "an existence oracle."
        )
        _assert_denied(resp, f"{method.upper()} /intakes/{{id}}{suffix} as null-space user")


def test_delete_cross_tenant_404_and_the_foreign_intake_survives(
    engine, set_space, monkeypatch, fake_gcs
):
    """A ``user`` in space A aimed at space B's intake: 404, and B's intake is untouched.

    Two walls stand between the caller and the row and BOTH are exercised: the role gate
    (they are not a superadmin) and, had they been one, the repo's tenant scope. The
    re-read is done AS SPACE B'S OWNER, so a row hidden from the caller but still present
    is correctly reported as surviving.
    """
    other_space = uuid.uuid4()
    other_intake = uuid.uuid4()
    try:
        with engine.begin() as conn:
            _create_space(conn, other_space, "Foreign space")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, other_space, other_intake, "reviewed")

        with _scenario(engine, set_space, monkeypatch, _user) as s:
            resp = s.client().delete(f"/intakes/{other_intake}", headers=_HDR)
            _assert_denied(resp, "DELETE another space's intake as role=user")
            assert s.space_id != other_space

        assert _intake_exists(engine, set_space, other_space, other_intake), (
            "space B's intake was destroyed by a space-A caller — the cross-tenant wall "
            "failed (TENANT-02)."
        )
    finally:
        _cleanup_spaces(engine, other_space)


def test_delete_missing_intake_is_404_not_500(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """A superadmin aimed at an id that does not exist exercises the ``repo.get -> None``
    branch on the AUTHORIZED path — the only way to reach it without the gate answering
    first. 404, and the storage seam is never touched.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        absent = uuid.uuid4()
        resp = s.client().delete(f"/intakes/{absent}", headers=_HDR)
        _assert_denied(resp, "DELETE a non-existent intake as superadmin")
        assert fake_gcs["deletes"] == []
        # The real intake in this scenario is untouched by the miss.
        assert _intake_exists(engine, set_space, s.space_id, s.intake_id)


def test_deletable_missing_intake_is_404_not_500(
    engine, set_space, monkeypatch, superadmin_engine
):
    """Same branch on the eligibility read — a miss is 404, never a fabricated ``true``."""
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        absent = uuid.uuid4()
        resp = s.client().get(f"/intakes/{absent}/deletable", headers=_HDR)
        _assert_denied(resp, "GET /deletable for a non-existent intake as superadmin")
