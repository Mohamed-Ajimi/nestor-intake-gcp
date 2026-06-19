"""Alembic env — sync pg8000, reads DATABASE_URL from os.environ.

Driver (Q1 RESOLVED): sync **pg8000** so this env and the test harness
(``tests/conftest.py``) share one driver. The sibling repo's env is async
asyncpg; this is the sync variant per 01-RESEARCH.md § Code Examples.

URL resolution precedence:
  1. ``sqlalchemy.url`` already set on the Config (the test harness sets this
     via ``cfg.set_main_option("sqlalchemy.url", str(engine.url))``) — honored
     as-is so the suite's container DSN drives the migration.
  2. else ``DATABASE_URL`` from the environment (CI / local / Cloud Run job).
Never bake the URL into ``alembic.ini``.

Importing ``app.db.models`` registers every table in ``Base.metadata`` so
autogenerate (and ``alembic check``) see the full ``nestor`` schema.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import create_engine, engine_from_config, pool

# Make ``backend/`` importable so ``app.*`` resolves regardless of the cwd
# alembic is invoked from. This file is backend/app/db/alembic/env.py, so the
# backend root is parents[3].
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.db.base import Base, _connector_creator  # noqa: E402
import app.db.models  # noqa: F401, E402  -- registers all 14 tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Honor an explicitly-set sqlalchemy.url (test harness / --x). Only fall back
# to DATABASE_URL when the Config has no url, so we never clobber the harness's
# container DSN with a stale/empty env var.
_existing_url = config.get_main_option("sqlalchemy.url")
if not _existing_url:
    _database_url = os.environ.get("DATABASE_URL")
    if _database_url:
        config.set_main_option("sqlalchemy.url", _database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL to stdout (``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_schemas=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def _use_connector(cfg) -> bool:
    """Decide whether to dial Cloud SQL via the IAM connector (D-05 / OQ4).

    The connector (one-shot migration Job) branch fires ONLY when BOTH hold:

    * ``INSTANCE_CONNECTION_NAME`` is present in the environment (Cloud Run Job
      sets it; nothing else does), AND
    * no explicit ``sqlalchemy.url`` has been pre-set on the Alembic Config.

    This mirrors ``app.db.base.get_engine``'s gate exactly: the testcontainers
    harness sets ``sqlalchemy.url`` (via ``cfg.set_main_option(... str(engine.url))``)
    and NEVER sets ``INSTANCE_CONNECTION_NAME``, so the suite keeps using the
    unchanged url branch byte-for-byte (02-PATTERNS.md § env.py critical guard).
    Factored out as a pure, importable predicate so the branch decision is
    unit-testable with no live DB.
    """
    if cfg.get_main_option("sqlalchemy.url"):
        return False  # explicit url (testcontainers / DATABASE_URL) always wins
    return bool(os.environ.get("INSTANCE_CONNECTION_NAME"))


def _build_connectable():
    """Build the migration engine, mode-switched by ``_use_connector`` (RESEARCH Pattern 3).

    * **Connector mode** — reuse ``app.db.base._connector_creator`` (IAM auth,
      password-free; the connector details live ONLY in base.py — no duplication
      here) behind ``create_engine("postgresql+pg8000://", creator=..., NullPool)``.
    * **URL mode** — the existing config-driven builder (``prefix="sqlalchemy."``,
      ``poolclass=NullPool``) path, UNCHANGED from Phase 1.

    ``NullPool`` in both modes: the migration Job is a one-shot process, so
    pooling buys nothing and a lingering pool would keep the Job alive.
    """
    if _use_connector(config):
        return create_engine(
            "postgresql+pg8000://",
            creator=_connector_creator,  # IAM connector — defined in app.db.base
            poolclass=pool.NullPool,
            future=True,
        )
    return engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )


def run_migrations_online() -> None:
    """Open a live sync engine (pg8000) and run migrations.

    The engine is built by ``_build_connectable``: the IAM connector when the
    Cloud Run migration Job sets ``INSTANCE_CONNECTION_NAME`` (D-05), else the
    unchanged ``sqlalchemy.url``/``DATABASE_URL`` path used by the test harness.
    """
    connectable = _build_connectable()
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_schemas=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
