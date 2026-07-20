"""
SQLAlchemy 2.x declarative base + async engine factory for the SDK pipeline.

Authoritative references:
- 01-RESEARCH.md § Standard Stack -- sqlalchemy[asyncio]==2.0.x, asyncpg.
- 01-PATTERNS.md § Shared Patterns: Bootstrap ordering -- the caller
  invokes nestor_pulse.secrets.load_secrets_into_env() BEFORE importing
  this module so DATABASE_URL is in os.environ.
- 01-CONTEXT.md D-05 -- single Postgres schema, RLS-enforced.

`get_engine()` is lru_cached so the SDK shares one engine per process
(per RESEARCH § Anti-patterns: do not let each consumer re-create an
engine).
"""

from __future__ import annotations

import functools
import os

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base shared by every model in nestor_pulse_sdk.db.models."""


@functools.lru_cache(maxsize=1)
def get_engine(database_url: str | None = None):
    """Return the shared async engine. Reads DATABASE_URL from env when None.

    Per 01-RESEARCH.md § Standard Stack the canonical driver is asyncpg, so
    DATABASE_URL must use the `postgresql+asyncpg://` scheme. The Phase 1
    Plan 01 secret bootstrap composes that URL using the Cloud SQL connector
    name (see infrastructure/gcloud/cloudsql-create.sh) and stores it in
    Secret Manager under DATABASE_URL.
    """
    url = database_url if database_url is not None else os.environ["DATABASE_URL"]
    return create_async_engine(url, echo=False, pool_pre_ping=True, future=True)


def get_sessionmaker(engine=None) -> async_sessionmaker[AsyncSession]:
    """Return an async_sessionmaker bound to `engine` (default: shared one).

    `expire_on_commit=False` is the canonical async pattern -- avoids
    auto-refresh round-trips after commit which would otherwise touch
    DB outside the request's transaction.
    """
    return async_sessionmaker(
        engine if engine is not None else get_engine(),
        expire_on_commit=False,
        class_=AsyncSession,
    )
