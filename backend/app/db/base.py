"""SQLAlchemy 2.0 declarative Base + sync engine/sessionmaker factory.

Driver decision (Q1 RESOLVED, 01-RESEARCH.md / 01-PATTERNS.md): Phase 1
standardizes on the **sync pg8000** driver so the test harness
(``tests/conftest.py``) and the Alembic ``env.py`` share one driver. The
sibling repo ``MOELD/Nestor/nestor_pulse_sdk/db/base.py`` uses async asyncpg;
this is the sync variant — structure unchanged.

Schema (D-01/D-03): every application table lives in the Postgres ``nestor``
schema. ``Base.metadata.schema`` is set to ``nestor`` so all models, the
``alembic upgrade head`` build, and the ``information_schema.tables`` shape
tests agree on one schema namespace.

``get_engine()`` is ``lru_cache``-d so the process shares one engine
(anti-pattern to let every consumer re-create an engine).
"""

from __future__ import annotations

import functools
import os

from sqlalchemy import MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# All application tables live in this Postgres schema (D-01/D-03). The
# schema-shape and RLS suites query ``WHERE table_schema = 'nestor'``.
NESTOR_SCHEMA = "nestor"


class Base(DeclarativeBase):
    """Declarative base shared by every model in ``app.db.models``.

    ``metadata.schema = "nestor"`` makes every table schema-qualified by
    default, so ``Base.metadata.create_all`` / Alembic emit ``nestor.<table>``
    and FKs resolve within the schema.
    """

    metadata = MetaData(schema=NESTOR_SCHEMA)


@functools.lru_cache(maxsize=1)
def get_engine(database_url: str | None = None):
    """Return the shared sync engine. Reads ``DATABASE_URL`` from env when None.

    The canonical driver is **pg8000** (Q1 RESOLVED), so ``DATABASE_URL`` must
    use the ``postgresql+pg8000://`` scheme. ``pool_pre_ping=True`` guards
    against stale pooled connections against Cloud SQL.
    """
    url = database_url if database_url is not None else os.environ["DATABASE_URL"]
    return create_engine(url, echo=False, pool_pre_ping=True, future=True)


def get_sessionmaker(engine=None):
    """Return a ``sessionmaker`` bound to ``engine`` (default: the shared one).

    ``expire_on_commit=False`` avoids auto-refresh round-trips after commit,
    which would otherwise issue queries outside the request's transaction (and,
    under RLS, outside the per-request ``app.current_space_id`` context).
    """
    return sessionmaker(
        engine if engine is not None else get_engine(),
        expire_on_commit=False,
        future=True,
    )
