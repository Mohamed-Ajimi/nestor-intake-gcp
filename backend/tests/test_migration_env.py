"""Branch-selection unit tests for the Alembic ``env.py`` engine builder.

Authoritative references (this repo):
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-02-PLAN.md
    Task 1 -- additive IAM-connector branch in run_migrations_online, gated on
    INSTANCE_CONNECTION_NAME (D-05, OQ4, RESEARCH Pattern 3).
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-PATTERNS.md
    § env.py -- the connector branch fires ONLY when INSTANCE_CONNECTION_NAME is
    set AND no explicit sqlalchemy.url is pre-set (testcontainers sets the url and
    never sets INSTANCE_CONNECTION_NAME -- the critical guard).

Why this file has NO ``integration`` marker:
    These are pure branch-selection tests. They must run on a box with NO Docker
    and NO live Postgres (the dev machine has none -- D-10). We therefore exercise
    only the importable decision helper ``env._use_connector`` and the connectable
    builder ``env._build_connectable`` with ``create_engine`` / the connector
    creator mocked, so NO socket is ever opened.

Design: ``env.py`` runs its migration logic at import time guarded by
``context.is_offline_mode()``. To import it for unit testing without triggering a
live migration, we import the module by file path with ``alembic.context`` stubbed
so the module-level ``if context.is_offline_mode()`` branch is inert.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest import mock

import pytest

# backend/tests/test_migration_env.py -> backend/ is parents[1]
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ENV_PY = _BACKEND_ROOT / "app" / "db" / "alembic" / "env.py"


def _load_env_module():
    """Import ``app/db/alembic/env.py`` in isolation with alembic stubbed.

    ``env.py`` ends with ``if context.is_offline_mode(): ... else: run_migrations_online()``.
    We stub ``alembic`` + ``alembic.context`` so that import-time guard reports
    *online* mode but ``run_migrations_online`` is monkeypatched to a no-op for the
    duration of the import, so importing the module never opens a connection.

    Returns the loaded module object (with ``_use_connector`` / ``_build_connectable``).
    """
    if str(_BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(_BACKEND_ROOT))

    # Minimal alembic stub: context.is_offline_mode()/config + a no-op so the
    # module-level dispatch at the bottom of env.py does nothing at import.
    fake_context = types.SimpleNamespace()
    fake_context.is_offline_mode = lambda: True  # take the offline (no-DB) branch
    fake_config = types.SimpleNamespace()
    fake_config.config_file_name = None
    fake_config.config_ini_section = "alembic"
    fake_config.get_main_option = lambda key, default=None: default
    fake_config.set_main_option = lambda *a, **k: None
    fake_config.get_section = lambda *a, **k: {}
    fake_context.config = fake_config
    fake_context.configure = lambda *a, **k: None
    fake_context.run_migrations = lambda *a, **k: None

    class _Tx:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    fake_context.begin_transaction = lambda: _Tx()

    fake_alembic = types.ModuleType("alembic")
    fake_alembic.context = fake_context
    fake_alembic_context = types.ModuleType("alembic.context")
    fake_alembic_context.is_offline_mode = fake_context.is_offline_mode

    with mock.patch.dict(
        sys.modules,
        {"alembic": fake_alembic, "alembic.context": fake_alembic_context},
    ):
        spec = importlib.util.spec_from_file_location("_nestor_alembic_env", _ENV_PY)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
    return module


@pytest.fixture()
def env_mod():
    return _load_env_module()


# ---------------------------------------------------------------------------
# _use_connector predicate — the branch decision
# ---------------------------------------------------------------------------

def test_use_connector_true_when_icn_set_and_no_url(env_mod, monkeypatch):
    """ICN set + no pre-set sqlalchemy.url -> connector branch (the Job path)."""
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:region:inst")
    # Config has no explicit url (matches Cloud Run Job: env-only, alembic.ini blank).
    cfg = types.SimpleNamespace(get_main_option=lambda key, default=None: None)
    assert env_mod._use_connector(cfg) is True


def test_use_connector_false_when_url_set(env_mod, monkeypatch):
    """Testcontainers path: sqlalchemy.url IS set -> url branch, even if ICN leaks."""
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:region:inst")
    cfg = types.SimpleNamespace(
        get_main_option=lambda key, default=None: "postgresql+pg8000://x/y"
    )
    assert env_mod._use_connector(cfg) is False


def test_use_connector_false_when_icn_unset(env_mod, monkeypatch):
    """No ICN (DATABASE_URL world) -> url branch."""
    monkeypatch.delenv("INSTANCE_CONNECTION_NAME", raising=False)
    cfg = types.SimpleNamespace(get_main_option=lambda key, default=None: None)
    assert env_mod._use_connector(cfg) is False


# ---------------------------------------------------------------------------
# _build_connectable — dispatches to the right engine builder, no live connect
# ---------------------------------------------------------------------------

def test_build_connectable_connector_path(env_mod, monkeypatch):
    """ICN set + no url -> create_engine(creator=_connector_creator), NullPool, no DB."""
    monkeypatch.setenv("INSTANCE_CONNECTION_NAME", "proj:region:inst")

    sentinel = object()
    with mock.patch.object(env_mod, "create_engine", return_value=sentinel) as ce, \
            mock.patch.object(env_mod, "engine_from_config") as efc:
        out = env_mod._build_connectable()

    assert out is sentinel
    efc.assert_not_called()  # url branch must NOT be taken
    ce.assert_called_once()
    args, kwargs = ce.call_args
    # First positional is the driver-only URL; creator wired to base.py's creator.
    assert args[0] == "postgresql+pg8000://"
    assert kwargs["creator"] is env_mod._connector_creator
    # NullPool for the one-shot Job (no pooling).
    assert kwargs["poolclass"] is env_mod.pool.NullPool


def test_build_connectable_url_path(env_mod, monkeypatch):
    """No ICN -> existing engine_from_config(prefix='sqlalchemy.', NullPool) path."""
    monkeypatch.delenv("INSTANCE_CONNECTION_NAME", raising=False)

    sentinel = object()
    with mock.patch.object(env_mod, "engine_from_config", return_value=sentinel) as efc, \
            mock.patch.object(env_mod, "create_engine") as ce:
        out = env_mod._build_connectable()

    assert out is sentinel
    ce.assert_not_called()  # connector branch must NOT be taken
    efc.assert_called_once()
    _args, kwargs = efc.call_args
    assert kwargs["prefix"] == "sqlalchemy."
    assert kwargs["poolclass"] is env_mod.pool.NullPool
