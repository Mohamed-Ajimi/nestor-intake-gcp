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
from sqlalchemy import engine_from_config, pool

# Make ``backend/`` importable so ``app.*`` resolves regardless of the cwd
# alembic is invoked from. This file is backend/app/db/alembic/env.py, so the
# backend root is parents[3].
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from app.db.base import Base  # noqa: E402
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


def run_migrations_online() -> None:
    """Open a live sync engine (pg8000) and run migrations."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
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
