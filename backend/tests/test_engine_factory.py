"""Engine-factory unit suite — covers the mode-switched ``get_engine()`` (D-08),
the bounded pool args (D-04), and the explicit-override Phase-1 regression guard
(Pitfall 6).

These are pure **unit** tests (the Cloud SQL Connector is mocked), so none carry
the ``integration`` marker — they run on the dev box with no Docker and no live
Postgres. They are RED until plan 02-01 Task 2 extends ``app.db.base.get_engine``
into the mode switch and adds ``_get_connector`` / ``_connector_creator``.

Authoritative references:
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-RESEARCH.md
    § Validation Architecture (test map) -- test_factory_* rows (INFRA-04 / D-08 / D-04)
    § Pattern 1 (lines 176-213) + Code Examples (lines 383-397) -- connector creator shape
    § Common Pitfalls / Pitfall 6 -- explicit database_url= must always win (Phase-1 regression)
    § Common Pitfalls / Pitfall 7 -- enable_iam_auth / refresh_strategy="lazy"
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-PATTERNS.md
    § backend/tests/test_engine_factory.py -- fixture reuse + cache_clear contract

Critical: ``get_engine`` and ``_get_connector`` are ``lru_cache(maxsize=1)``-d, so
every test clears both caches in setup AND teardown — otherwise a stale engine from
a prior case leaks across tests (02-PATTERNS.md § lru_cache singleton).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db import base


@pytest.fixture(autouse=True)
def _clear_engine_caches():
    """Clear the lru_cache singletons before and after every test.

    ``get_engine``/``_get_connector`` cache exactly one result each; without a
    clear, the second test would receive the first test's engine and the
    mode-switch assertions would be meaningless.
    """
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()
    yield
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()


def test_factory_url_mode(monkeypatch):
    """No INSTANCE_CONNECTION_NAME + DATABASE_URL set -> plain URL-mode engine.

    The engine must NOT carry a ``creator`` (that is the connector branch); it is
    built straight from the DATABASE_URL DSN.
    """
    monkeypatch.delenv("INSTANCE_CONNECTION_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://u:p@localhost:5432/db")

    engine = base.get_engine()

    # URL mode resolves the DSN directly; the connector creator is not used.
    assert engine.url.get_backend_name() == "postgresql"
    assert engine.url.get_driver_name() == "pg8000"
    assert engine.url.database == "db"


def test_factory_connector_mode(monkeypatch):
    """INSTANCE_CONNECTION_NAME + DB_USER/DB_NAME set + mocked Connector ->
    the connector creator branch is taken (Connector.connect invoked)."""
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:europe-west1:inst")
    monkeypatch.setenv("DB_USER", "runtime-sa@proj.iam")
    monkeypatch.setenv("DB_NAME", "nestor")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    fake_connector = MagicMock()
    # Patch the lazy import target inside _get_connector (imported there, not at module top).
    with patch("google.cloud.sql.connector.Connector", return_value=fake_connector) as ctor:
        engine = base.get_engine()
        # The connector branch builds a creator-backed engine on a host-less DSN.
        assert engine.url.host is None
        # Invoke the creator directly: a full engine.connect() would run real
        # dialect initialization (SELECT version() etc.) against the MagicMock
        # DBAPI connection and blow up — the creator IS the seam under test.
        base._connector_creator()

    # The process-singleton Connector was constructed with the lazy refresh strategy.
    ctor.assert_called_once()
    assert ctor.call_args.kwargs.get("refresh_strategy") == "lazy"

    # The creator dialed Cloud SQL with IAM auth, pg8000, no password.
    fake_connector.connect.assert_called_once()
    call = fake_connector.connect.call_args
    assert call.args[0] == "proj:europe-west1:inst"
    assert call.args[1] == "pg8000"
    assert call.kwargs.get("user") == "runtime-sa@proj.iam"
    assert call.kwargs.get("db") == "nestor"
    assert call.kwargs.get("enable_iam_auth") is True
    assert "password" not in call.kwargs


def test_explicit_url_overrides(monkeypatch):
    """An explicit get_engine(database_url=...) wins even when
    INSTANCE_CONNECTION_NAME is set (Phase-1 regression / Pitfall 6).

    This is exactly how conftest.py::engine builds its test engine, so the
    connector branch must never hijack an explicit DSN.
    """
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:europe-west1:inst")
    monkeypatch.setenv("DB_USER", "runtime-sa@proj.iam")
    monkeypatch.setenv("DB_NAME", "nestor")

    # If the connector branch were (wrongly) taken, constructing a Connector here
    # would be attempted; patch it to a strict mock that fails if used.
    with patch("google.cloud.sql.connector.Connector") as ctor:
        engine = base.get_engine(database_url="postgresql+pg8000://x:y@localhost:5432/explicit")

    assert engine.url.database == "explicit"
    assert engine.url.get_driver_name() == "pg8000"
    # Explicit DSN path must not have touched the connector at all.
    ctor.assert_not_called()


def test_pool_args(monkeypatch):
    """Both modes carry the bounded pool args: size 2, max_overflow 3 (D-04)."""
    # --- URL mode ---
    monkeypatch.delenv("INSTANCE_CONNECTION_NAME", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+pg8000://u:p@localhost:5432/db")
    url_engine = base.get_engine()
    assert url_engine.pool.size() == 2
    assert url_engine.pool._max_overflow == 3

    # Reset caches between the two engines (autouse only wraps the whole test).
    base.get_engine.cache_clear()
    base._get_connector.cache_clear()

    # --- Connector mode ---
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:europe-west1:inst")
    monkeypatch.setenv("DB_USER", "runtime-sa@proj.iam")
    monkeypatch.setenv("DB_NAME", "nestor")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with patch("google.cloud.sql.connector.Connector", return_value=MagicMock()):
        conn_engine = base.get_engine()
    assert conn_engine.pool.size() == 2
    assert conn_engine.pool._max_overflow == 3
