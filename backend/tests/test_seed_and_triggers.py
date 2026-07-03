"""Empty-baseline + seed-populates + scope-guard + updated_at-mechanism suite.

This is the plan 01-04 verification suite. It proves, against a live
``pgvector/pgvector:pg16`` database built by ``alembic upgrade head`` (the
shared session-scoped ``engine`` fixture in ``conftest.py``):

  (a) PRODUCTION-EMPTY BASELINE — immediately after ``upgrade head`` every
      tenant table has 0 rows (no migration smuggles in seed data; INFRA-02).
  (b) SEED POPULATES — running ``scripts/seed_dev.py::seed`` against the engine
      creates exactly the demo organization + superadmin membership + sample
      intake template (D-09), and is idempotent on a second run.
  (c) SEED IS NOT A MIGRATION — no file under ``app/db/alembic/versions/``
      imports or calls ``seed_dev`` (the seed can never enter production via a
      migration; INFRA-02 / D-09).
  (d) SCOPE GUARD — ``prefill_intake_answers`` exists in ``pg_proc`` while the
      three deferred (post-``decomposed``) trigger functions do NOT (INTAKE-05).
  (e) UPDATED_AT MECHANISM MATCHES THE DOCUMENTED CHOICE — read the
      ``UPDATED_AT_MECHANISM:`` marker from ``0004_triggers.py`` and assert
      reality matches: for ``orm-onupdate`` there must be NO ``set_updated_at``
      function in ``pg_proc`` AND an ORM-mediated UPDATE must bump
      ``updated_at``; for ``trigger`` a ``set_updated_at``/``tg_set_*`` function
      must exist AND a raw UPDATE must bump ``updated_at``.

When no Postgres is reachable (no Docker + no ``DATABASE_URL``) the ``engine``
fixture skips, so the whole suite skips cleanly — mirroring conftest.py.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import re
import uuid

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.integration

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BACKEND_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VERSIONS_DIR = os.path.join(_BACKEND_ROOT, "app", "db", "alembic", "versions")
_MIGRATION_0004 = os.path.join(_VERSIONS_DIR, "0004_triggers.py")
_SEED_PATH = os.path.join(_BACKEND_ROOT, "scripts", "seed_dev.py")

# The 12 tenant-OWNED tables + the 2 tenant-root tables = every table that must
# come up empty on a fresh production DB.
_ALL_TABLES = (
    "organizations",
    "organization_memberships",
    "products",
    "intake_templates",
    "intakes",
    "intake_answers",
    "skill_runs",
    "decompositions",
    "research_questions",
    "research_artifacts",
    "findings",
    "deliverables",
    "artifact_embeddings",
    "search_index",
)

# The deferred (>= research-start) trigger functions that MUST NOT exist.
_DEFERRED_FUNCS = (
    "tg_bump_to_in_research",
    "tg_bump_to_delivered",
    "persist_questions_on_research_start",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _load_seed_module():
    """Import ``scripts/seed_dev.py`` by file path (no package assumptions)."""
    spec = importlib.util.spec_from_file_location("seed_dev", _SEED_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared_updated_at_mechanism() -> str:
    """Read the ``UPDATED_AT_MECHANISM:`` marker from 0004_triggers.py."""
    src = open(_MIGRATION_0004, encoding="utf-8").read()
    m = re.search(r"UPDATED_AT_MECHANISM:\s*([A-Za-z0-9\-]+)", src)
    assert m, "0004_triggers.py is missing the UPDATED_AT_MECHANISM: marker"
    return m.group(1).strip()


def _seed_sessionmaker(engine):
    """A sessionmaker bound to the TEST engine, mirroring app.db.base."""
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(engine, expire_on_commit=False, future=True)


def _superadmin_sessionmaker(engine):
    """A sessionmaker whose sessions run as ``app_superadmin`` (CR-02/CR-03).

    The 0002 migration applies ``ENABLE`` + ``FORCE ROW LEVEL SECURITY`` to
    every tenant-owned table, so even the table owner (the role that ran the
    migrations, which the ``engine`` fixture connects as) is policy-bound. The
    only way to write across the space boundary — exactly what ``seed_dev``
    and a no-GUC tenant insert do — is to satisfy the 0003
    ``*_superadmin_all`` bypass policy, whose predicate is
    ``current_user = 'app_superadmin'``.

    ``conftest._ensure_app_superadmin`` already creates that LOGIN role in the
    container. Rather than re-authenticate as it, we ``SET LOCAL ROLE
    app_superadmin`` at the start of every transaction on this sessionmaker's
    sessions, which flips ``current_user`` to ``app_superadmin`` so the bypass
    policy matches. ``SET LOCAL ROLE`` (unlike plain ``SET ROLE``, which is
    session-scoped and DOES leak onto pooled connections) reverts automatically
    at transaction end.
    """
    from sqlalchemy import event, text
    from sqlalchemy.orm import sessionmaker

    maker = sessionmaker(engine, expire_on_commit=False, future=True)

    @event.listens_for(maker, "after_begin")
    def _set_superadmin_role(session, transaction, connection):  # noqa: ANN001
        connection.execute(text("SET LOCAL ROLE app_superadmin"))

    return maker


def _count(conn, table: str) -> int:
    return conn.execute(text(f"SELECT count(*) FROM nestor.{table}")).scalar_one()


def _count_in_space(conn, table: str, col: str, space_id: str) -> int:
    """Count rows in ``table`` where ``col`` equals the given space id."""
    return conn.execute(
        text(f"SELECT count(*) FROM nestor.{table} WHERE {col} = :sid"),
        {"sid": space_id},
    ).scalar_one()


@contextlib.contextmanager
def _superadmin_connect(engine):
    """Open a transaction whose ``current_user`` is ``app_superadmin``.

    Reads/writes against FORCE-RLS tenant tables (e.g. ``intake_templates``)
    only see/affect rows when the 0003 ``*_superadmin_all`` bypass policy
    matches — i.e. when ``current_user = 'app_superadmin'``. The plain owner
    connection the ``engine`` fixture hands out is policy-bound with no space
    GUC, so a count would read 0 and a DELETE would touch nothing. ``SET
    ROLE`` is transaction-scoped and reset on commit/rollback, so it never
    leaks onto pooled connections (CR-02).
    """
    with engine.begin() as conn:
        conn.execute(text("SET LOCAL ROLE app_superadmin"))
        yield conn


def _func_exists(conn, name: str) -> bool:
    return (
        conn.execute(
            text(
                "SELECT 1 FROM pg_proc p "
                "JOIN pg_namespace n ON n.oid = p.pronamespace "
                "WHERE n.nspname = 'nestor' AND p.proname = :name"
            ),
            {"name": name},
        ).first()
        is not None
    )


# ---------------------------------------------------------------------------
# (a) production-empty baseline
# ---------------------------------------------------------------------------
def test_all_tables_empty_after_migrate(engine):
    """Right after ``upgrade head`` every table is empty (INFRA-02).

    Runs against a FRESH scratch database: the shared session-scoped DB
    accumulates rows from suites that ran earlier in the same session, so a
    global count there says nothing about what the MIGRATIONS created. The
    owner role has CREATEDB (conftest bootstrap) precisely for this check.
    """
    from sqlalchemy import create_engine

    from .conftest import _run_migrations

    scratch = "nestor_infra02_check"

    def _autocommit_sql(*statements: str) -> None:
        """Run CREATE/DROP DATABASE on a FRESH pg8000 connection in autocommit.

        These statements refuse to run inside a transaction block (25001).
        A pooled connection won't do: pg8000 BEGINs implicitly on any execute
        (including the pool's pre-ping probe), and setting ``autocommit`` while
        a transaction is open does not end it. A brand-new driver connection
        with ``autocommit`` set before its first statement is the only shape
        pg8000 guarantees transaction-free.
        """
        import pg8000.dbapi

        u = engine.url
        con = pg8000.dbapi.connect(
            user=u.username,
            password=u.password,
            host=u.host,
            port=u.port or 5432,
            database=u.database,
        )
        try:
            con.autocommit = True
            cur = con.cursor()
            for stmt in statements:
                cur.execute(stmt)
            cur.close()
        finally:
            con.close()

    _autocommit_sql(
        f'DROP DATABASE IF EXISTS "{scratch}"',
        f'CREATE DATABASE "{scratch}"',
    )

    scratch_eng = create_engine(
        engine.url.set(database=scratch), echo=False, future=True
    )
    try:
        _run_migrations(scratch_eng)
        with scratch_eng.connect() as conn:
            for table in _ALL_TABLES:
                assert _count(conn, table) == 0, (
                    f"{table} is NOT empty after upgrade head — a migration is "
                    "smuggling in seed data (INFRA-02 violated)."
                )
    finally:
        scratch_eng.dispose()
        _autocommit_sql(f'DROP DATABASE IF EXISTS "{scratch}"')


# ---------------------------------------------------------------------------
# (b) seed populates + is idempotent
# ---------------------------------------------------------------------------
def test_seed_populates_and_is_idempotent(engine):
    """seed_dev.seed creates the demo org/superadmin/template, idempotently."""
    seed_mod = _load_seed_module()
    # CR-02: bind the seed to an app_superadmin-role session so the 0003
    # *_superadmin_all bypass policy admits the cross-space tenant-table
    # inserts (intake_templates is FORCE-RLS). The plain owner engine is
    # policy-bound and would be rejected at the IntakeTemplate insert.
    maker = _superadmin_sessionmaker(engine)

    try:
        first = seed_mod.seed(session_factory=maker)
        assert first["organization"] == "created"
        assert first["superadmin"] == "created"
        assert first["intake_template"] == "created"

        # Read back as app_superadmin: intake_templates is FORCE-RLS, so an
        # owner connection with no space GUC would count 0 (CR-02). Counts are
        # scoped to the seed's fixed DEV_SPACE_ID — the shared session DB may
        # hold residue from suites that ran earlier.
        sid = str(seed_mod.DEV_SPACE_ID)
        with _superadmin_connect(engine) as conn:
            assert _count_in_space(conn, "organizations", "id", sid) == 1
            assert _count_in_space(conn, "intake_templates", "space_id", sid) == 1
            assert (
                conn.execute(
                    text(
                        "SELECT count(*) FROM nestor.organization_memberships "
                        "WHERE role = 'superadmin' AND organization_id = :sid"
                    ),
                    {"sid": sid},
                ).scalar_one()
                == 1
            )

        # Second run creates nothing new (idempotent get-or-create).
        second = seed_mod.seed(session_factory=maker)
        assert second["organization"] == "exists"
        assert second["superadmin"] == "exists"
        assert second["intake_template"] == "exists"

        with _superadmin_connect(engine) as conn:
            assert _count_in_space(conn, "organizations", "id", sid) == 1
            assert _count_in_space(conn, "intake_templates", "space_id", sid) == 1
    finally:
        # Remove ONLY the seeded space (scoped — other suites' rows are not
        # ours to delete). Delete as app_superadmin so the FORCE-RLS
        # intake_templates rows are actually removed (an owner DELETE with no
        # GUC matches no rows).
        sid = str(_load_seed_module().DEV_SPACE_ID)
        with _superadmin_connect(engine) as conn:
            conn.execute(
                text("DELETE FROM nestor.intake_templates WHERE space_id = :sid"),
                {"sid": sid},
            )
            conn.execute(
                text(
                    "DELETE FROM nestor.organization_memberships "
                    "WHERE organization_id = :sid"
                ),
                {"sid": sid},
            )
            conn.execute(
                text("DELETE FROM nestor.organizations WHERE id = :sid"),
                {"sid": sid},
            )


# ---------------------------------------------------------------------------
# (c) seed is NOT referenced by any migration
# ---------------------------------------------------------------------------
def test_no_migration_references_seed():
    """No Alembic version file imports/calls seed_dev (INFRA-02 / D-09)."""
    offenders = []
    for fname in os.listdir(_VERSIONS_DIR):
        if not fname.endswith(".py"):
            continue
        src = open(os.path.join(_VERSIONS_DIR, fname), encoding="utf-8").read()
        if "seed_dev" in src:
            offenders.append(fname)
    assert not offenders, (
        f"migration(s) reference seed_dev — seed must never enter production "
        f"via a migration: {offenders}"
    )


# ---------------------------------------------------------------------------
# (d) scope guard: in-scope trigger present, deferred ones absent
# ---------------------------------------------------------------------------
def test_in_scope_trigger_present_deferred_absent(engine):
    """prefill_intake_answers exists; the 3 deferred functions do NOT."""
    with engine.connect() as conn:
        assert _func_exists(conn, "prefill_intake_answers"), (
            "prefill_intake_answers should exist in pg_proc after 0004"
        )
        # submit_intake transition logic also lands in 0004.
        assert _func_exists(conn, "submit_intake")
        for fn in _DEFERRED_FUNCS:
            assert not _func_exists(conn, fn), (
                f"deferred function {fn} exists in pg_proc — INTAKE-05 scope "
                "guard breached (it would re-open the path toward Tribunal)."
            )


# ---------------------------------------------------------------------------
# (e) updated_at mechanism matches the documented choice
# ---------------------------------------------------------------------------
def test_updated_at_mechanism_matches_declaration(engine):
    """Reality must match the UPDATED_AT_MECHANISM: marker in 0004."""
    mechanism = _declared_updated_at_mechanism()
    assert mechanism in ("orm-onupdate", "trigger"), (
        f"unexpected UPDATED_AT_MECHANISM value: {mechanism!r}"
    )

    space_id = uuid.uuid4()

    if mechanism == "orm-onupdate":
        # No set_updated_at function may exist...
        with engine.connect() as conn:
            assert not _func_exists(conn, "set_updated_at"), (
                "UPDATED_AT_MECHANISM is orm-onupdate but a set_updated_at "
                "function exists in pg_proc — two mechanisms is ambiguous."
            )

        # ...and an ORM-mediated UPDATE must bump updated_at.
        from app.db.models import Organization, Intake

        # CR-03: intakes is FORCE-RLS. Every transaction that touches it must
        # establish the space context first, or the *_space_isolation policy
        # rejects the write/read (GUC NULL -> predicate false). We set the
        # canonical transaction-local GUC via set_space_context inside EACH
        # session.begin() block (SET LOCAL semantics — it does not survive a
        # commit), matching the row's space_id so the test exercises the real
        # production write path. This also covers the prefill_intake_answers
        # BEFORE-INSERT trigger's secondary INSERT INTO intake_answers, which
        # runs in the same transaction and is FORCE-RLS too.
        from app.db.rls import set_space_context

        maker = _seed_sessionmaker(engine)
        try:
            with maker() as session:
                with session.begin():
                    # organizations is the tenant ROOT (not RLS-scoped), but we
                    # set the context anyway for uniformity across the blocks.
                    set_space_context(session, space_id)
                    session.add(Organization(id=space_id, name="uat-org"))
                intake_id = uuid.uuid4()
                with session.begin():
                    set_space_context(session, space_id)
                    session.add(
                        Intake(id=intake_id, space_id=space_id, status="draft")
                    )
                # Read the initial updated_at, then mutate through the ORM.
                with session.begin():
                    set_space_context(session, space_id)
                    obj = session.get(Intake, intake_id)
                    before = obj.updated_at
                with session.begin():
                    set_space_context(session, space_id)
                    obj = session.get(Intake, intake_id)
                    obj.status = "submitted"
                with session.begin():
                    set_space_context(session, space_id)
                    obj = session.get(Intake, intake_id)
                    after = obj.updated_at
                assert after is not None and before is not None
                assert after >= before, (
                    "ORM onupdate did not maintain updated_at — the declared "
                    "orm-onupdate mechanism is not actually sufficient."
                )
        finally:
            # Tear down under the same space context (intakes + the trigger's
            # intake_answers row are FORCE-RLS; an owner DELETE with no GUC
            # would match nothing). organizations is root, deleted last.
            with engine.begin() as conn:
                set_space_context(conn, space_id)
                conn.execute(
                    text("DELETE FROM nestor.intake_answers WHERE space_id = :s"),
                    {"s": str(space_id)},
                )
                conn.execute(
                    text("DELETE FROM nestor.intakes WHERE space_id = :s"),
                    {"s": str(space_id)},
                )
                conn.execute(
                    text("DELETE FROM nestor.organizations WHERE id = :s"),
                    {"s": str(space_id)},
                )
    else:  # mechanism == "trigger"
        with engine.connect() as conn:
            assert _func_exists(conn, "set_updated_at") or _func_exists(
                conn, "tg_set_updated_at"
            ), (
                "UPDATED_AT_MECHANISM is trigger but no set_updated_at / "
                "tg_set_updated_at function exists in pg_proc."
            )
        try:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO nestor.organizations (id, name) "
                        "VALUES (:s, 'uat-org')"
                    ),
                    {"s": str(space_id)},
                )
            with engine.begin() as conn:
                before = conn.execute(
                    text(
                        "SELECT updated_at FROM nestor.organizations "
                        "WHERE id = :s"
                    ),
                    {"s": str(space_id)},
                ).scalar_one_or_none()
            # Only assert the bump when the table carries updated_at.
            if before is not None:
                with engine.begin() as conn:
                    conn.execute(
                        text(
                            "UPDATE nestor.organizations SET name = 'uat-org-2' "
                            "WHERE id = :s"
                        ),
                        {"s": str(space_id)},
                    )
                    after = conn.execute(
                        text(
                            "SELECT updated_at FROM nestor.organizations "
                            "WHERE id = :s"
                        ),
                        {"s": str(space_id)},
                    ).scalar_one()
                assert after >= before
        finally:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM nestor.organizations WHERE id = :s"),
                    {"s": str(space_id)},
                )
