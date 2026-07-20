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
from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ENGINE-01 / 13-RESEARCH.md Pattern 1 + Pitfall 1/2 (Plan 13-02):
# The Tribunal engine shares a Cloud SQL instance with the intake backend, and
# BOTH Alembic lines ship colliding revision IDs 0001-0010. To keep the two
# lines from ever sharing an `alembic_version` table (which would silently skip
# Tribunal's 0001 -> tables never created -> first run 500s), the Tribunal line
# writes its OWN version table in its OWN schema and runs every migration with
# `search_path=tribunal` so unqualified `op.create_table(...)` and migration
# 0008's GRANT/POLICY statements land in `tribunal`, not `public`.
#
# DB-topology decision (13-RESEARCH.md Open Q1): the **`tribunal` SCHEMA on the
# shared intake database** is chosen over the separate-database fallback --
# schema route wins for future cross-schema flexibility and matches the CONTEXT
# wording. It requires 0008's `SCHEMA public` -> `SCHEMA tribunal` rewrite (done
# in this plan) plus the schema-create + `SET search_path TO tribunal` in both
# the offline and online migration paths below.

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
        include_schemas=True,
        # ENGINE-01: isolate the Tribunal line -- never share intake's alembic_version.
        version_table="tribunal_alembic_version",
        version_table_schema="tribunal",
    )
    with context.begin_transaction():
        # Emit the schema-create + search_path preamble so the generated SQL
        # script targets `tribunal` for every unqualified CREATE TABLE / GRANT /
        # POLICY (mirrors the online path's connection-level SET search_path).
        context.execute("CREATE SCHEMA IF NOT EXISTS tribunal")
        context.execute("SET search_path TO tribunal")
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # ENGINE-01: ensure the tribunal schema exists and target it via search_path
    # BEFORE configuring/running migrations, so the version table lands in
    # `tribunal` and every unqualified CREATE TABLE / GRANT / POLICY (incl.
    # migration 0008) resolves to `tribunal`, never `public`. This runs on the
    # sync Connection that async run_sync() hands us -- keep Tribunal's existing
    # asyncpg engine unchanged (Pitfall 5: do NOT swap it for an IAM connector).
    connection.execute(text("CREATE SCHEMA IF NOT EXISTS tribunal"))
    # COMMIT the autobegun preamble transaction before context.configure().
    # Without this, SQLAlchemy 2.0 autobegin means Alembic's begin_transaction()
    # finds a transaction it does not own, so nothing ever commits and the whole
    # migration silently ROLLS BACK when the connection closes (observed live:
    # all 10 migrations logged, zero tables persisted). SET search_path is
    # session-scoped, so it survives the commit for the migration run below.
    connection.commit()
    connection.execute(text("SET search_path TO tribunal"))
    connection.commit()
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        include_schemas=True,
        # ENGINE-01: isolate the Tribunal line -- never share intake's alembic_version.
        version_table="tribunal_alembic_version",
        version_table_schema="tribunal",
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
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Normal path (migrate Job, CLI): no loop is running.
        asyncio.run(run_migrations_online())
    else:
        # Programmatic invocation from inside an async test: asyncio.run() would
        # raise "cannot be called from a running event loop", so run the
        # migration on its own loop in a worker thread.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as _ex:
            _ex.submit(asyncio.run, run_migrations_online()).result()
