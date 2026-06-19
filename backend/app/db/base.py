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


# Bounded pool args shared by BOTH engine modes (D-04). Small pool_size +
# max_overflow keep total connections well under the Cloud SQL tier limit even
# as Cloud Run scales out (AI-06: never starve the instance against the cap).
# pool_recycle pre-empts Cloud SQL idle-connection drops; pool_pre_ping guards
# against stale pooled connections. Valid for URL-mode QueuePool too.
_POOL_KW = dict(
    pool_size=2,
    max_overflow=3,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
    future=True,
)


@functools.lru_cache(maxsize=1)
def _get_connector():
    """Return the process-singleton Cloud SQL ``Connector`` (lazy refresh).

    The ``Connector`` is imported **lazily inside this function** (not at module
    top) so the testcontainers / DATABASE_URL path never imports it — Phase-1
    suites bind explicit DSNs and must not pull in the connector (Pitfall 7).

    The lazy refresh strategy defers ephemeral-cert refresh to connection time,
    which suits Cloud Run's throttled-CPU-when-idle model (D-03 / Pattern 1).
    ``lru_cache(maxsize=1)`` makes this one Connector per process.
    """
    from google.cloud.sql.connector import Connector

    return Connector(refresh_strategy="lazy")


def _connector_creator():
    """SQLAlchemy ``creator`` that dials Cloud SQL over the connector (pg8000).

    Reads the non-secret connection identity from the environment
    (``INSTANCE_CONNECTION_NAME`` / ``DB_USER`` / ``DB_NAME``). Auth is IAM-only
    (no password — D-09); ip_type is left at the connector default (PUBLIC per
    D-03).
    """
    return _get_connector().connect(
        os.environ["INSTANCE_CONNECTION_NAME"],  # "project:region:instance"
        "pg8000",
        user=os.environ["DB_USER"],  # IAM SA login name (no .gserviceaccount.com)
        db=os.environ["DB_NAME"],
        enable_iam_auth=True,  # IAM ephemeral certs — no DB password exists
    )


@functools.lru_cache(maxsize=1)
def get_engine(database_url: str | None = None):
    """Return the shared sync engine, mode-switched by environment (D-08).

    Two modes, both carrying the shared bounded pool args (``_POOL_KW``, D-04):

    * **Cloud SQL mode** — when ``database_url`` is None AND
      ``INSTANCE_CONNECTION_NAME`` is set, build a connector-backed engine via
      ``creator=_connector_creator`` (password-free IAM auth).
    * **URL mode** — otherwise resolve ``database_url`` (or env ``DATABASE_URL``)
      and build a plain engine. The canonical driver is **pg8000** (Q1 RESOLVED).

    Phase-1 regression guard (Pitfall 6): an **explicit** ``database_url=`` always
    wins — the connector branch is gated on ``database_url is None and icn`` — so
    ``conftest.py::engine`` (which passes an explicit DSN) keeps building a plain
    testcontainer engine even if ``INSTANCE_CONNECTION_NAME`` happens to be set.
    The signature and ``lru_cache(maxsize=1)`` are unchanged from Phase 1.
    """
    icn = os.environ.get("INSTANCE_CONNECTION_NAME")
    if database_url is None and icn:  # Cloud SQL mode (connector + IAM auth)
        return create_engine(
            "postgresql+pg8000://",
            creator=_connector_creator,
            **_POOL_KW,
        )
    url = database_url if database_url is not None else os.environ["DATABASE_URL"]
    return create_engine(url, **_POOL_KW)  # testcontainers / local URL mode


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
