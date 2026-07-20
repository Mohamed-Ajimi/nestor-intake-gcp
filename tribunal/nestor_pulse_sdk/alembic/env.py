"""
Alembic env.py -- async-aware, reads DATABASE_URL from os.environ.

Per .planning/phases/01-production-foundation/01-RESEARCH.md
§ ORM and Schema-Push Recommendation: the canonical migration command is
`cd nestor_pulse_sdk && alembic upgrade head`. DATABASE_URL must already
be in the environment (Plan 01 sets this via Secret Manager + ADC).

Async pattern from the Alembic cookbook
(https://alembic.sqlalchemy.org/en/latest/cookbook.html
 "Programmatic API use (Asynchronous)").

Importing `nestor_pulse_sdk.db.models` registers every table in
`Base.metadata` so autogenerate sees the full schema.
"""

from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the repo root importable so `nestor_pulse_sdk.*` resolves regardless
# of where alembic is invoked from.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from nestor_pulse_sdk.db.base import Base  # noqa: E402
import nestor_pulse_sdk.db.models  # noqa: F401, E402  -- register all tables

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve DATABASE_URL at runtime -- never bake it into alembic.ini.
_DATABASE_URL = os.environ.get("DATABASE_URL")
if _DATABASE_URL:
    config.set_main_option("sqlalchemy.url", _DATABASE_URL)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode -- emit SQL to stdout (alembic upgrade --sql)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # FORCE ROW LEVEL SECURITY DDL is in our migrations; render as-is.
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode -- open a live async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        future=True,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
