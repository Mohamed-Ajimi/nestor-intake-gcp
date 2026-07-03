"""Repository + GUC integration suite — proves the Phase 4 tenant data seam (API-02).

Drives :class:`app.db.repository.TenantRepository` / ``IntakeRepository`` directly
(constructed with a fabricated :class:`app.auth.identity.Identity` + a real Session)
against live Postgres, so it exercises the SAME code an HTTP request would, minus
FastAPI. The full-stack HTTP denial suite lives in ``test_cross_tenant_denial.py``
(plan 03's sample endpoint); this file proves the substrate.

What each case proves (04-VALIDATION.md API-02 rows / threat register):

| Test                                   | Proves                                                       |
|----------------------------------------|-------------------------------------------------------------|
| test_where_filter_excludes_foreign_... | repo WHERE excludes a foreign row INDEPENDENTLY of RLS (D-01,|
|   (matches ``-k where_filter``)        | RESEARCH Q3): GUC set to space_b, repo scoped to space_a →   |
|                                        | space_b row still excluded purely by the explicit WHERE.    |
| test_own_space_crud                    | a user-scoped repo can get/list/patch its own space's intake |
|                                        | and list() returns ONLY own-space rows.                     |
| test_cross_tenant_get_and_patch_...    | get(foreign_id) is None; patch(foreign_id) rowcount 0; the   |
|                                        | foreign row is unchanged (T-04-04 BOLA/IDOR, D-07).         |
| test_pool_no_leak_across_reused_...    | on a pinned single physical connection two sequential        |
|   (matches ``-k pool_no_leak``)        | different-space txs do not cross-contaminate through the     |
|                                        | repo/session path (Pitfall 1 regression, T-04-06).         |

Skip-clean: ``pytestmark = pytest.mark.integration`` + reuse of the conftest
``engine`` / ``set_space`` / ``two_spaces`` fixtures (which skip when no Docker /
DATABASE_URL). ``app.db.*`` imports are guarded with ``pytest.importorskip`` so the
file COLLECTS on the dev box (no backend deps installed) without erroring.

Analogs: ``test_rls_isolation.py`` — two-space seeding helpers (lines 88-120) and the
pooled-reuse regression (lines 261-348).
"""

from __future__ import annotations

import uuid

import pytest

from .conftest import _owner_url

pytestmark = pytest.mark.integration

# Guard the app-layer imports so the file collects on a box with no backend deps
# installed (mirrors the conftest skip-clean discipline). importorskip raises Skip
# (collected, not errored) when sqlalchemy / app modules are unavailable.
pytest.importorskip("sqlalchemy")
repository = pytest.importorskip("app.db.repository")
session_mod = pytest.importorskip("app.db.session")  # noqa: F841 — import-smoke only
identity_mod = pytest.importorskip("app.auth.identity")

TenantRepository = repository.TenantRepository  # noqa: F841 — referenced via subclass
IntakeRepository = repository.IntakeRepository
Identity = identity_mod.Identity

SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# Identity + seeding helpers (two-space shape copied from test_rls_isolation.py)
# ---------------------------------------------------------------------------


def _user_identity(space_id: uuid.UUID) -> "Identity":
    """A fabricated ``user`` Identity scoped to one space (space_id as str, as the
    real token claim is a string — exercises the repo's uuid.UUID coercion)."""
    return Identity(uid="u-test", email="u@x", role="user", space_id=str(space_id))


def _create_space(conn, space_id: uuid.UUID, name: str) -> None:
    """Insert an organization (a space). ``organizations`` is the tenant root and is
    NOT RLS-scoped, so no space context is needed to insert it."""
    from sqlalchemy import text

    conn.execute(
        text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
        {"id": space_id, "name": name},
    )


def _insert_intake(conn, set_space, space_id: uuid.UUID, intake_id: uuid.UUID) -> None:
    """Insert one intake into a space, with the GUC set so the 0002 WITH CHECK passes."""
    from sqlalchemy import text

    set_space(conn, space_id)
    conn.execute(
        text(
            f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
            "VALUES (:id, :space_id, 'draft')"
        ),
        {"id": intake_id, "space_id": space_id},
    )


# ---------------------------------------------------------------------------
# where_filter: repo WHERE excludes a foreign row INDEPENDENTLY of RLS (D-01)
# ---------------------------------------------------------------------------


def test_where_filter_excludes_foreign_row_independent_of_rls(
    engine, set_space, two_spaces
):
    """The repo's explicit ``WHERE space_id=`` excludes a foreign row even when RLS
    would otherwise ADMIT it — proving the belt independently of the suspenders.

    Construction (RESEARCH Q3 / Pitfall 6): we set the GUC to **space_b** (so the
    0002 isolation policy would let space_b's intake through) but build the repository
    with a **space_a** Identity. A correct repo applies ``WHERE space_id = space_a``
    and therefore returns NEITHER space_b's row (excluded by the WHERE despite RLS
    allowing it) NOR space_a's row (RLS hides it under the space_b GUC) — the headline
    assertion is that space_b's row is NOT returned, which can ONLY be the repo WHERE
    doing the work (RLS is actively permitting space_b here). A silently-broken
    ``uuid.UUID(...)`` coercion (e.g. comparing a str to a UUID column and matching
    nothing — or everything) would change this outcome and fail the test.
    """
    from sqlalchemy.orm import Session

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (where_filter)")
            _create_space(conn, space_b, "Space B (where_filter)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # Open ONE tx, set the GUC to space_b (RLS now admits space_b's row), but scope
        # the repo to space_a. The repo WHERE must still exclude space_b's row.
        with engine.begin() as conn:
            set_space(conn, space_b)  # RLS context = space_b (would allow space_b)
            session = Session(bind=conn)
            repo = IntakeRepository(session, _user_identity(space_a))

            ids = {row.id for row in repo.list()}
            assert intake_b not in ids, (
                "WHERE-FILTER BROKEN: repo scoped to space_a returned space_b's row "
                "even though the repo's explicit WHERE should exclude it (RLS was "
                "actively permitting space_b — so only the repo WHERE can exclude it)."
            )
            # get() of the foreign id is also None purely via the repo WHERE.
            assert repo.get(intake_b) is None, (
                "WHERE-FILTER BROKEN: repo.get(space_b id) returned a row under a "
                "space_a Identity (the explicit WHERE must exclude it)."
            )
    finally:
        with engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


# ---------------------------------------------------------------------------
# own-space CRUD: a user repo can get/list/patch its own space; list() is scoped
# ---------------------------------------------------------------------------


def test_own_space_crud(engine, set_space, two_spaces):
    """A user-scoped repo reads/lists/patches its OWN space's intake, and ``list()``
    returns only own-space rows (the positive path under matching GUC + repo scope)."""
    from sqlalchemy.orm import Session

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (own crud)")
            _create_space(conn, space_b, "Space B (own crud)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        # Read/list/patch as space_a with the matching GUC (the real user path).
        with engine.begin() as conn:
            set_space(conn, space_a)
            session = Session(bind=conn)
            repo = IntakeRepository(session, _user_identity(space_a))

            got = repo.get(intake_a)
            assert got is not None and got.id == intake_a, (
                "own-space get() should return the space_a intake."
            )

            ids = {row.id for row in repo.list()}
            assert intake_a in ids, "own-space list() should include space_a's intake."
            assert intake_b not in ids, (
                "own-space list() leaked space_b's intake (repo WHERE + RLS scope)."
            )

            rowcount = repo.patch(intake_a, status="submitted")
            assert rowcount == 1, (
                f"own-space patch() should affect exactly 1 row, got {rowcount}."
            )

        # Confirm the patch landed (read back as owner with the space_a GUC).
        with engine.begin() as conn:
            from sqlalchemy import text

            set_space(conn, space_a)
            status = conn.execute(
                text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_a},
            ).scalar_one()
            assert status == "submitted", (
                f"own-space patch() did not persist (status={status!r})."
            )
    finally:
        with engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


# ---------------------------------------------------------------------------
# cross-tenant exclusion: get() None, patch() rowcount 0, foreign row unchanged
# ---------------------------------------------------------------------------


def test_cross_tenant_get_and_patch_denied(engine, set_space, two_spaces):
    """A user-scoped repo cannot reach another space's row by id (T-04-04 / D-07).

    Under the space_a GUC + a space_a Identity: ``get(space_b id)`` is None,
    ``patch(space_b id, ...)`` returns rowcount 0, and space_b's row is UNCHANGED.
    """
    from sqlalchemy.orm import Session

    space_a, space_b = two_spaces
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        with engine.begin() as conn:
            _create_space(conn, space_a, "Space A (cross-tenant)")
            _create_space(conn, space_b, "Space B (cross-tenant)")
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_a, intake_a)
        with engine.begin() as conn:
            _insert_intake(conn, set_space, space_b, intake_b)

        with engine.begin() as conn:
            set_space(conn, space_a)
            session = Session(bind=conn)
            repo = IntakeRepository(session, _user_identity(space_a))

            assert repo.get(intake_b) is None, (
                "BOLA/IDOR: repo.get(foreign id) returned a row (must be None, D-07)."
            )
            rowcount = repo.patch(intake_b, status="submitted")
            assert rowcount == 0, (
                f"BOLA/IDOR: repo.patch(foreign id) affected {rowcount} rows "
                "(must be 0 — the scoped WHERE matches nothing, D-07)."
            )

        # The foreign row must be untouched (read back as owner under the space_b GUC).
        with engine.begin() as conn:
            from sqlalchemy import text

            set_space(conn, space_b)
            status = conn.execute(
                text(f"SELECT status FROM {SCHEMA}.intakes WHERE id = :id"),
                {"id": intake_b},
            ).scalar_one()
            assert status == "draft", (
                f"cross-tenant patch leaked through: space_b row status={status!r} "
                "(expected unchanged 'draft')."
            )
    finally:
        with engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )


# ---------------------------------------------------------------------------
# pool_no_leak: no space-context leak across a reused pooled connection (Pitfall 1)
# ---------------------------------------------------------------------------


def test_pool_no_leak_across_reused_connection(engine, pg_container):
    """Two sequential txs on the SAME pinned physical connection, scoped to DIFFERENT
    spaces THROUGH the repo/session path, must not cross-contaminate (T-04-06).

    Mirrors ``test_concurrent_different_spaces_stay_isolated`` but drives the
    repository (not raw SQL) so the regression covers the actual Phase 4 seam:
    ``set_space_context`` (SET LOCAL, true) + the per-checkin RESET in base.py. With a
    session-scoped GUC (``set_config(..., false)`` / bare SET) the second tx would
    inherit the first space's context and the second repo would see the first's row.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from app.db.base import _register_guc_reset
    from app.db.rls import set_space_context

    # Owner (non-superuser) DSN: the superuser DSN would bypass RLS entirely.
    url = _owner_url(pg_container)
    # Pin a single shared physical connection so a leak would be observable.
    pooled = create_engine(
        url, echo=False, future=True, pool_size=1, max_overflow=0, pool_pre_ping=True
    )
    # Attach the SAME per-checkin RESET base.py registers on the real engines, so the
    # regression covers the D-02 backstop (not just SET LOCAL) on the reused connection.
    _register_guc_reset(pooled)

    space_a, space_b = uuid.uuid4(), uuid.uuid4()
    intake_a, intake_b = uuid.uuid4(), uuid.uuid4()

    try:
        with pooled.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.organizations (id, name) "
                    "VALUES (:id, :name)"
                ),
                [
                    {"id": space_a, "name": "Space A (pool_no_leak)"},
                    {"id": space_b, "name": "Space B (pool_no_leak)"},
                ],
            )

        # Tx 1: scope to space_a through the repo, insert space_a's intake.
        with pooled.begin() as conn:
            set_space_context(conn, space_a)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_a, "sid": space_a},
            )

        # Tx 2: scope to space_b through the repo, insert space_b's intake.
        with pooled.begin() as conn:
            set_space_context(conn, space_b)
            conn.execute(
                text(
                    f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                    "VALUES (:id, :sid, 'draft')"
                ),
                {"id": intake_b, "sid": space_b},
            )

        # Tx 3 (reuses the SAME physical connection): a space_b repo must NOT see
        # space_a's row — proves the prior space_a context did not leak.
        with pooled.begin() as conn:
            set_space_context(conn, space_b)
            session = Session(bind=conn)
            repo = IntakeRepository(session, _user_identity(space_b))
            ids_b = {row.id for row in repo.list()}
            assert intake_b in ids_b, "space_b repo should see space_b's intake."
            assert intake_a not in ids_b, (
                "POOL LEAK (Pitfall 1): space_b repo saw space_a's row on a reused "
                "pooled connection — SET LOCAL / checkin RESET failed."
            )

        # Tx 4 (reverse): a space_a repo must NOT see space_b's row.
        with pooled.begin() as conn:
            set_space_context(conn, space_a)
            session = Session(bind=conn)
            repo = IntakeRepository(session, _user_identity(space_a))
            ids_a = {row.id for row in repo.list()}
            assert intake_a in ids_a, "space_a repo should see space_a's intake."
            assert intake_b not in ids_a, (
                "POOL LEAK (Pitfall 1): space_a repo saw space_b's row on a reused "
                "pooled connection — SET LOCAL / checkin RESET failed."
            )
    finally:
        with pooled.begin() as conn:
            conn.execute(
                text(f"DELETE FROM {SCHEMA}.organizations WHERE id IN (:a, :b)"),
                {"a": space_a, "b": space_b},
            )
        pooled.dispose()
