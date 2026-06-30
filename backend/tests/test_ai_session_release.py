"""AI-06 session-release proof (integration, RED scaffold) — T-7-02 / T-7-06.

THE correctness core of Phase 7 (D-05): the long external call must hold NO
pooled DB connection, and the WRITE session must RE-ISSUE the transaction-local
``app.current_space_id`` GUC. Authored against the FINAL contract; RED until
07-04 lands ``run_with_session_release`` / ``tenant_session``. Runs over REAL
Postgres (``pytest.mark.integration`` — auto-skips without Docker/DATABASE_URL).

What this pins:

- ``set_space_context`` (``app.db.rls.set_space_context``, re-exported into the
  ``app.db.ai_session`` namespace) is invoked EXACTLY TWICE for one user AI run —
  once for the READ session and once for the FRESH WRITE session (the marquee
  second-session GUC re-set, T-7-02);
- NO connection is held across the faked external call: ``engine.pool.checkedout()``
  is 0 between the READ-close and the WRITE-open (T-7-06 — pool not starved).

RED discipline: external deps ``importorskip``; impl HARD-imported. The spy wraps
the ``set_space_context`` symbol IN the ``app.db.ai_session`` namespace (the call
site) and delegates to the real ``app.db.rls.set_space_context`` so the GUC is
still actually set.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.integration

pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")

identity_mod = pytest.importorskip("app.auth.identity")
rls_mod = pytest.importorskip("app.db.rls")

from app.db import ai_session as ai_session_mod  # noqa: E402  (RED until 07-04)
from app.db.ai_session import run_with_session_release  # noqa: E402

Identity = identity_mod.Identity
SCHEMA = "nestor"


def _user(space_id) -> "Identity":
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def test_set_space_context_called_twice_and_no_conn_held(
    engine, monkeypatch
):
    """One user AI run -> set_space_context called EXACTLY twice; pool free across call."""
    from sqlalchemy import text

    space = uuid.uuid4()
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: engine)

    # Spy on the GUC setter AT THE CALL SITE (ai_session imported it from rls).
    # The wrapper delegates to the real rls.set_space_context so the GUC is set.
    real_set_space_context = rls_mod.set_space_context
    calls: list[object] = []

    def _spy(conn_or_session, space_id):
        calls.append(space_id)
        return real_set_space_context(conn_or_session, space_id)

    monkeypatch.setattr(ai_session_mod, "set_space_context", _spy, raising=False)
    monkeypatch.setattr(rls_mod, "set_space_context", _spy)

    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :n)"),
                {"id": space, "n": "Session-release space"},
            )

        identity = _user(space)
        pool_observed: list[int] = []

        def read_fn(session):
            # Read phase returns PLAIN data (no live ORM rows survive past close).
            current = session.execute(
                text("SELECT current_setting('app.current_space_id', true)")
            ).scalar_one()
            return {"read_space": current}

        def call_fn(dto):
            # The long external call holds NO DB connection (AI-06 / T-7-06).
            pool_observed.append(engine.pool.checkedout())
            return {"ok": True, "read_space": dto["read_space"]}

        def write_fn(session, dto, result):
            # The WRITE session must have the GUC re-set (2nd set_space_context).
            current = session.execute(
                text("SELECT current_setting('app.current_space_id', true)")
            ).scalar_one()
            return current

        write_space = run_with_session_release(identity, read_fn, call_fn, write_fn)

        # Marquee guarantee: GUC set once per tenant_session -> exactly twice.
        assert len(calls) == 2, (
            f"T-7-02: set_space_context must be called EXACTLY twice (read + write "
            f"session), got {len(calls)} — the 2nd-session GUC re-set is missing."
        )

        # No connection held across the faked external call.
        assert pool_observed == [0], (
            f"T-7-06: no connection may be held across the LLM call; "
            f"engine.pool.checkedout() was {pool_observed} (expected [0])."
        )

        # The write session was scoped to the same space (GUC actually re-issued).
        assert str(write_space) == str(space), (
            f"the WRITE session GUC must equal the caller space {space}, got {write_space!r}."
        )
    finally:
        _cleanup(engine, space)
