"""Guarded hard-delete suite (D-23.5-02, narrowed by D-23.5-06) — plans 23.5-02 / 23.5-08.

WHAT THIS FILE PROVES. Tester remark 3 of phase 23.5 is "be able to archive/delete a
project". Archive is remark 1's override verb reaching ``archived`` (plan 23.5-01). THIS
file covers the other half: ``DELETE /intakes/{id}`` — an irreversible destruction — and
its eligibility read ``GET /intakes/{id}/deletable``.

THE WALL THAT DEFINES THE VERB — AND THE DAY IT MOVED. Plan 23.5-02 built it as "ANY
``research_runs`` row blocks forever" (D-23.5-02). The operator tested that on dev on
**2026-09-22** and ruled it too wide: "even ones who had research or intake being done
need to be able to be deleted" (**D-23.5-06**). The wall is now IN-FLIGHT ONLY — the
status set of migration 0016's partial unique index, ``{queued, running,
needs_report_spec}``, exposed as ``app.research.run_status.RESEARCH_IN_FLIGHT``.

Why that is the right wall rather than a weakening of the old one: a TERMINAL run's cost
and audit chain live on the TRIBUNAL side, in the ``tribunal`` schema with no foreign key
into ``nestor`` and with its hash-chained blobs in the audit bucket. Deleting the intake
never touched them, so refusing the delete protected nothing. An IN-FLIGHT run is a
different thing entirely: a worker is actively writing to rows this DELETE would cascade
away, and the reconciler is scanning for exactly those three statuses.

The one real cost of that retention is closed here too: ``research_runs.tribunal_run_id``
is a plain ``String`` with NO foreign key, so once the nestor row is gone nothing points
at the retained tribunal run. The ``intake.deleted`` audit row therefore carries
``research_runs`` (how many were destroyed) and ``tribunal_run_ids`` (their non-null
pointers), written BEFORE the cascade takes them.

The 409 is still checked BEFORE any object key is collected and BEFORE the audit row is
written, so a refused delete has ZERO side effects: nothing in the DB moved and nothing
was handed to GCS.

| Test family                          | Proves                                            |
|--------------------------------------|---------------------------------------------------|
| ``*_cascade``                        | 204, and the intake + answers + skill runs +      |
|                                      | sources + transcripts + artifacts are ALL gone —  |
|                                      | the DB's ``ON DELETE CASCADE`` fans the one       |
|                                      | DELETE out through every child table.             |
| ``*_terminal_run*``                  | a run that has STOPPED never blocks: 204, and     |
|                                      | the ``research_runs`` rows go with the intake.    |
| ``*_in_flight*``                     | 409 and EVERY row above still exists.             |
| ``*_deletable_*``                    | the eligibility read agrees with the wall, and    |
|                                      | never becomes an existence oracle.                |
| ``*_research_in_flight_*`` (no DB)   | the app constant IS migration 0016's index        |
|                                      | predicate, read off ``ResearchRun.__table__``.    |
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
run_status_mod = pytest.importorskip("app.research.run_status")
research_routes_mod = pytest.importorskip("app.api.research_routes")

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

#: The NINE measured Tribunal run statuses. This is the ONE set in this file typed out as
#: literals, and deliberately so: ``mirror_tick`` writes ``metrics.get("status")`` VERBATIM
#: into a plain ``String`` with no CHECK constraint, so no app constant enumerates them.
#: The list is migration 0016's own (``0016_research_runs_single_inflight.py``, "The
#: predicate is DERIVED, not guessed"). Every OTHER status set below is IMPORTED — a test
#: that re-types ``{"queued", "running", "needs_report_spec"}`` pins a copy of the rule
#: instead of the rule.
_MEASURED_RUN_STATUSES = frozenset(
    {
        "queued",
        "running",
        "cancelled",
        "needs_input",
        "failed",
        "completed",
        "needs_report_spec",
        "completed_degraded",
        "parked",
    }
)


#: The three statuses that REFUSE a delete (D-23.5-06). Read off the app module at import
#: time and NOT defaulted: at HEAD this attribute does not exist, so the whole file fails to
#: collect — which is the loudest, least-gameable RED available. A ``getattr(..., default)``
#: would leave the parametrized arms with an EMPTY id list and pass vacuously.
_RESEARCH_IN_FLIGHT = run_status_mod.RESEARCH_IN_FLIGHT

#: Every status a run may hold and STILL allow the delete — computed from the two app sets
#: rather than typed out, so adding a status to either one moves this suite automatically
#: instead of leaving it asserting yesterday's rule.
_DELETABLE_RUN_STATUSES = frozenset(
    run_status_mod.RESEARCH_TERMINAL | research_routes_mod._RETRYABLE_RUN_STATUSES
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


def _insert_research_run(
    conn,
    set_space,
    space_id,
    intake_id,
    status: str = "completed",
    tribunal_run_id: str | None = None,
):
    """Seed ONE research run at an explicit status, optionally carrying its tribunal id.

    ``tribunal_run_id`` is a plain nullable ``String`` with NO foreign key (the tribunal
    rows live in their own schema and are deliberately RETAINED), so a run may or may not
    carry one. Both shapes are seeded by the audit-metadata arm, because the handler must
    list the non-null ones and silently drop the rest.
    """
    from sqlalchemy import text

    run_id = uuid.uuid4()
    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.research_runs "
            "(id, space_id, intake_id, status, attempt, tribunal_run_id) "
            "VALUES (:id, :space_id, :intake_id, :status, 1, :tribunal_run_id)"
        ),
        {
            "id": run_id,
            "space_id": space_id,
            "intake_id": intake_id,
            "status": status,
            "tribunal_run_id": tribunal_run_id,
        },
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

    ``with_research_run`` threads a STATUS rather than only a boolean, because after
    D-23.5-06 the status is the whole rule: ``True`` seeds one ``completed`` run (the
    old default, now on the ALLOWED side of the wall), and any other truthy value is read
    as a sequence of statuses so the both-runs case — one terminal, one in flight — has a
    single seeding path instead of two.
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
                statuses = (
                    ("completed",)
                    if with_research_run is True
                    else tuple(with_research_run)
                )
                for run_status in statuses:
                    _insert_research_run(
                        conn, set_space, space_id, intake_id, run_status
                    )

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

    The literal MOVED with D-23.5-06: the old wording ("has research runs") was a statement
    about HISTORY and is now simply false as a reason, because a finished run no longer
    blocks anything. The new one is a statement about a LIVE run.
    """
    routes = pytest.importorskip("app.api.intake_routes")

    assert routes._DELETE_BLOCKED_DETAIL == (
        "Research is in flight for this intake and it cannot be deleted"
    )


def test_delete_blocked_reason_is_one_token_shared_by_both_routes():
    """``_DELETE_BLOCKED_REASON`` is the ONE machine token, and it is ``research_in_flight``.

    Two consumers key off it: ``DeletableView.reason`` (which the frontend renders its own
    nl/fr/en copy from) and the 409 path. A second literal spelled out at either site is
    exactly how the two drift apart, so the constant is pinned rather than the strings.
    ``has_research_runs`` is the OLD token and must be gone — a UI still keyed on it would
    silently stop matching and fall through to a generic error.
    """
    routes = pytest.importorskip("app.api.intake_routes")

    assert routes._DELETE_BLOCKED_REASON == "research_in_flight"
    assert routes._DELETE_BLOCKED_REASON != "has_research_runs"


def test_research_in_flight_is_the_three_literals_and_tolerates_none():
    """``RESEARCH_IN_FLIGHT`` is exactly migration 0016's ``_INFLIGHT`` tuple.

    ``needs_report_spec`` is the member that is easy to miss and the one that matters: a
    run sitting there is ALIVE, awaiting an operator's report spec, and ``POST
    /report-spec`` re-queues that SAME run. Dropping it would let a DELETE cascade away
    rows a worker still owns.
    """
    assert _RESEARCH_IN_FLIGHT == frozenset({"queued", "running", "needs_report_spec"})
    assert run_status_mod.is_research_in_flight("running") is True
    assert run_status_mod.is_research_in_flight("needs_report_spec") is True
    # ``needs_input`` is RETRYABLE — the app already treats it as a finished run that may
    # be re-triggered — so it is NOT in flight and must NOT block a delete.
    assert run_status_mod.is_research_in_flight("needs_input") is False
    assert run_status_mod.is_research_in_flight(None) is False
    # POSITIVE by design: an unknown future engine status counts as NOT in flight, which
    # fails toward ALLOWING the delete. That is the correct direction here for the same
    # reason 0016 gives — the alternative makes an intake undeletable forever with no
    # operator remedy, and the operator's whole ruling is that they must be able to delete.
    assert run_status_mod.is_research_in_flight("some_status_from_2027") is False


def test_the_three_status_sets_partition_the_nine_measured_statuses():
    """in-flight / terminal / retryable together cover the nine, and in-flight overlaps neither.

    This is the derivation D-23.5-06 quotes, asserted rather than trusted. If the engine
    grows a tenth status, this test goes red and FORCES the decision — which is the point:
    a status nobody classified silently becomes "deletable" under the positive predicate,
    and that should be a deliberate choice, not a default nobody noticed.
    """
    retryable = frozenset(research_routes_mod._RETRYABLE_RUN_STATUSES)
    terminal = frozenset(run_status_mod.RESEARCH_TERMINAL)

    assert not (_RESEARCH_IN_FLIGHT & terminal), (
        f"in-flight and terminal overlap on {sorted(_RESEARCH_IN_FLIGHT & terminal)} — a "
        "run cannot be both stopped and running."
    )
    assert not (_RESEARCH_IN_FLIGHT & retryable), (
        f"in-flight and retryable overlap on {sorted(_RESEARCH_IN_FLIGHT & retryable)} — "
        "a re-trigger must never be offered for a live run."
    )
    assert (_RESEARCH_IN_FLIGHT | terminal | retryable) == _MEASURED_RUN_STATUSES, (
        "the three sets no longer cover the nine measured statuses; unclassified: "
        f"{sorted(_MEASURED_RUN_STATUSES - (_RESEARCH_IN_FLIGHT | terminal | retryable))}, "
        f"unexpected: {sorted((_RESEARCH_IN_FLIGHT | terminal | retryable) - _MEASURED_RUN_STATUSES)}"
    )
    assert _DELETABLE_RUN_STATUSES == _MEASURED_RUN_STATUSES - _RESEARCH_IN_FLIGHT


def test_research_in_flight_equals_the_single_inflight_index_predicate():
    """The app constant IS the DB invariant — read off the MODEL, never off a source grep.

    ``uq_research_runs_one_inflight_per_intake`` is what actually stops two concurrent
    ~$45 triggers (D-23.2-12). If the delete wall and that index ever disagree about what
    "in flight" means, one of two bad things happens: a DELETE cascades away a run the
    index still considers live, or an intake stays undeletable while the DB would happily
    accept a fresh trigger. Comparing against ``ResearchRun.__table__`` — the declaration
    the ORM and migration 0016 share byte-for-byte — is the only comparison that cannot go
    stale, because a grep of the source file matches a comment just as happily as code.
    """
    import re

    pytest.importorskip("sqlalchemy")
    from app.db.models.research_runs import ResearchRun

    matching = [
        i
        for i in ResearchRun.__table__.indexes
        if i.name == "uq_research_runs_one_inflight_per_intake"
    ]
    assert matching, "the single-in-flight index is gone from the model (D-23.2-12)"
    where = str(matching[0].dialect_options["postgresql"]["where"])
    assert set(re.findall(r"'([a-z_]+)'", where)) == set(_RESEARCH_IN_FLIGHT), (
        f"the index predicate is {where!r} but RESEARCH_IN_FLIGHT is "
        f"{sorted(_RESEARCH_IN_FLIGHT)} — the delete wall and the concurrency invariant "
        "disagree about what 'in flight' means."
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
# (a2) D-23.5-06 — a run that has STOPPED never blocks the delete
# ===========================================================================


@pytest.mark.parametrize("run_status", sorted(_DELETABLE_RUN_STATUSES))
def test_deletable_is_true_for_every_stopped_run_status(
    engine, set_space, monkeypatch, superadmin_engine, run_status
):
    """``completed`` / ``completed_degraded`` / ``failed`` / ``cancelled`` / ``parked`` /
    ``needs_input`` all answer ``{"deletable": true}``.

    This is the ruling, arm by arm. Before D-23.5-06 every one of these six answered
    ``false`` and the operator was left with nothing but archive for an intake whose
    research had long since stopped.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=(run_status,),
    ) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/deletable", headers=_HDR)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deletable": True, "reason": None}, (
            f"a {run_status!r} run has STOPPED; its cost and audit chain live on the "
            "tribunal side and survive the delete, so it must not block one (D-23.5-06)."
        )


def test_delete_succeeds_with_a_terminal_run_and_takes_the_research_rows(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """204 for an intake whose only run is ``completed`` — and the run rows go with it.

    The pre-assertion is load-bearing: without it, a scenario that failed to seed the run
    would make the "zero afterwards" assertion vacuously true and this arm would prove
    nothing about the cascade at all.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=("completed",),
    ) as s:
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 1, (
            "the scenario did not seed the research run — the post-assertion below would "
            "be vacuously true."
        )

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        assert resp.status_code == 204, (
            f"a terminal-run intake must delete with 204 (D-23.5-06), got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert not _intake_exists(engine, set_space, s.space_id, s.intake_id)
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 0, (
            "research_runs declares ondelete='CASCADE' to nestor.intakes, so the run rows "
            "must go with the intake. The TRIBUNAL-side rows are a different schema and "
            "are deliberately retained — that is what the audit row's tribunal_run_ids "
            "are for."
        )


def test_delete_audit_row_records_the_destroyed_runs_and_their_tribunal_ids(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """The ``intake.deleted`` metadata carries ``research_runs`` and ``tribunal_run_ids``.

    ``research_runs.tribunal_run_id`` is a plain ``String`` with NO foreign key, and the
    tribunal rows live in their own schema with their own alembic line — they SURVIVE this
    delete on purpose (the cost record and the hash-chained audit blobs). The consequence
    is that once the nestor row is cascaded away, nothing points at the retained run any
    more. This audit row is the only thing that still can. Retaining a record nobody can
    find is not retention.

    The ``parked`` run is seeded WITHOUT a tribunal id deliberately: the handler must list
    the non-null pointers and drop the rest rather than emitting a ``null`` into the trail.
    """
    with _scenario(
        engine, set_space, monkeypatch, _superadmin(), sa_engine=superadmin_engine
    ) as s:
        with engine.begin() as conn:
            _insert_research_run(
                conn,
                set_space,
                s.space_id,
                s.intake_id,
                "completed",
                tribunal_run_id="trib-completed-1",
            )
            _insert_research_run(
                conn, set_space, s.space_id, s.intake_id, "parked", tribunal_run_id=None
            )

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)
        assert resp.status_code == 204, resp.text

        rows = _delete_audit_rows(engine, s.space_id, s.intake_id)
        assert len(rows) == 1, f"expected exactly one intake.deleted row, got {rows!r}"
        meta = rows[0]
        assert meta.get("research_runs") == 2, (
            f"the trail must say how many research runs the cascade destroyed, got {meta!r}"
        )
        assert meta.get("tribunal_run_ids") == ["trib-completed-1"], (
            "the trail must carry the RETAINED tribunal run ids and nothing else — a "
            f"null pointer is not a pointer; got {meta!r}"
        )
        # The plan-02 metadata is untouched by the addition.
        assert meta.get("objects") == 3 and meta.get("objects_skipped") == 1


# ===========================================================================
# (b) the money wall — a run IN FLIGHT means 409, with zero side effects
# ===========================================================================


@pytest.mark.parametrize("run_status", sorted(_RESEARCH_IN_FLIGHT))
def test_delete_is_409_when_research_is_in_flight_and_nothing_is_destroyed(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs, run_status
):
    """409, and the intake, its children, its run row and its objects ALL survive.

    D-23.5-06: an IN-FLIGHT run means a worker is actively writing to rows this DELETE
    would cascade away, and the reconciler (``app/research/reconcile.py``) is scanning for
    exactly these three statuses. The status code alone is the weak form of this test —
    the assertions that matter are that NOTHING moved. The run check is placed before key
    collection and before the audit write precisely so a refused delete is a no-op rather
    than a partially-executed destruction.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=(run_status,),
    ) as s:
        before = _child_counts(engine, set_space, s.space_id, s.intake_id)

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        assert resp.status_code == 409, (
            f"an intake with a {run_status!r} research run must be refused with EXACTLY "
            f"409, got {resp.status_code} ({resp.text!r})"
        )
        assert resp.json()["detail"] == (
            "Research is in flight for this intake and it cannot be deleted"
        )
        assert _intake_exists(engine, set_space, s.space_id, s.intake_id), (
            "the 409 leaked through — an intake with a live run was destroyed."
        )
        assert _child_counts(engine, set_space, s.space_id, s.intake_id) == before, (
            "a refused delete must leave every child row exactly as it was."
        )
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 1, (
            "the research_runs row — the run a worker is still writing to — is gone."
        )
        assert fake_gcs["deletes"] == [], (
            f"a refused delete must hand NOTHING to the storage seam, got "
            f"{fake_gcs['deletes']!r}"
        )
        assert _delete_audit_rows(engine, s.space_id, s.intake_id) == [], (
            "a refused delete must not write an intake.deleted audit row."
        )


def test_delete_is_409_when_a_terminal_and_an_in_flight_run_coexist(
    engine, set_space, monkeypatch, superadmin_engine, fake_gcs
):
    """The wall is "ANY row in flight", never "the NEWEST row".

    A retriggered intake legitimately holds a ``failed`` run and a ``running`` one at the
    same time. Reading only the latest run — the shape ``latest_for_intake`` invites —
    would answer on whichever happened to be newest, and a ``failed`` row created after a
    resume would open the delete on a live run. Both rows are seeded so ordering cannot
    make this pass by luck.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=("running", "failed"),
    ) as s:
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 2

        resp = s.client().delete(f"/intakes/{s.intake_id}", headers=_HDR)

        assert resp.status_code == 409, (
            f"one in-flight row among terminal ones must still refuse, got "
            f"{resp.status_code} ({resp.text!r})"
        )
        assert _intake_exists(engine, set_space, s.space_id, s.intake_id)
        assert _count_research_runs(engine, set_space, s.space_id, s.intake_id) == 2


@pytest.mark.parametrize("run_status", sorted(_RESEARCH_IN_FLIGHT))
def test_deletable_is_false_with_reason_when_research_is_in_flight(
    engine, set_space, monkeypatch, superadmin_engine, run_status
):
    """The eligibility read agrees with the wall on the refused side, and says WHY.

    The ``reason`` is a stable machine token (``research_in_flight``), not prose: the
    frontend renders its own localized copy off it, so a reworded English sentence must
    never change what the UI can key on. It is asserted as the literal here and pinned to
    ``_DELETE_BLOCKED_REASON`` separately, so the wire format and the constant cannot
    drift apart in opposite directions and still look green.
    """
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        _superadmin(),
        sa_engine=superadmin_engine,
        with_research_run=(run_status,),
    ) as s:
        resp = s.client().get(f"/intakes/{s.intake_id}/deletable", headers=_HDR)
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"deletable": False, "reason": "research_in_flight"}


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
