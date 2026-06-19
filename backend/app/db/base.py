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

Phase 4 additions (04-02-PLAN.md / 04-RESEARCH.md Patterns 3 & 4):

* :func:`get_superadmin_engine` — a SEPARATE ``lru_cache(maxsize=1)`` engine that
  connects as the built-in DB role ``app_superadmin`` (the EXACT literal the 0003
  ``*_superadmin_all`` bypass policy matches via ``current_user = 'app_superadmin'``).
  Path B (D-05a, RESOLVED): the role uses a PASSWORD read once from Secret Manager,
  NOT IAM auth. This stored ``app_superadmin`` password is the single deliberate
  exception to the otherwise IAM-passwordless invariant (D-05a / D-09) — it is
  scoped to the superadmin code path only and kept in Secret Manager (never env).
  The existing :func:`get_engine` is regression-frozen (Phase 1/2 guard): its
  signature and ``lru_cache(maxsize=1)`` are unchanged — the superadmin engine is a
  distinct function, NOT a parameter on ``get_engine``.
* :func:`_register_guc_reset` — a defensive per-``checkin`` pool event (D-02 backstop,
  Pitfall 1) registered on BOTH engines that runs ``RESET app.current_space_id`` on the
  RAW DBAPI (pg8000) connection when it returns to the pool, so no pooled connection
  ever carries a prior request's tenant context. The canonical ``SET LOCAL`` already
  reverts at COMMIT (see ``app/db/rls.py``); this RESET is belt-only and a harmless
  no-op when the GUC was never set. NEVER add a second GUC *setter* and never pass
  ``false`` to ``set_config`` (Pitfall 1).
"""

from __future__ import annotations

import functools
import os

from sqlalchemy import MetaData, create_engine, event
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
    (no password — D-09).

    WR-05: ``ip_type`` is made EXPLICIT (and env-overridable via
    ``CLOUD_SQL_IP_TYPE``) rather than relying on the connector's implicit PUBLIC
    default. The instance is provisioned public-IP (``ipv4_enabled = true``, D-03),
    so the default is ``PUBLIC`` — but encoding it here makes the
    instance-vs-connector IP mode a single greppable contract. If the instance is
    ever switched to private IP, set ``CLOUD_SQL_IP_TYPE=PRIVATE`` in the Cloud Run
    env and the connector follows, instead of silently dialing the wrong endpoint.
    """
    return _get_connector().connect(
        os.environ["INSTANCE_CONNECTION_NAME"],  # "project:region:instance"
        "pg8000",
        user=os.environ["DB_USER"],  # IAM SA login name (no .gserviceaccount.com)
        db=os.environ["DB_NAME"],
        enable_iam_auth=True,  # IAM ephemeral certs — no DB password exists
        ip_type=os.environ.get("CLOUD_SQL_IP_TYPE", "PUBLIC"),  # WR-05: explicit, env-overridable
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
        engine = create_engine(
            "postgresql+pg8000://",
            creator=_connector_creator,
            **_POOL_KW,
        )
    else:
        url = database_url if database_url is not None else os.environ["DATABASE_URL"]
        engine = create_engine(url, **_POOL_KW)  # testcontainers / local URL mode
    # D-02 backstop: scrub app.current_space_id on every checkin (Pitfall 1).
    _register_guc_reset(engine)
    return engine


# ---------------------------------------------------------------------------
# Phase 4: second engine (app_superadmin / Path B) + per-checkin GUC RESET
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def _load_superadmin_password() -> str:
    """Fetch the ``app_superadmin`` DB password ONCE from Secret Manager (Path B).

    The Secret Manager client is imported **lazily inside this function** (mirroring
    :func:`_get_connector`) so the testcontainers / DATABASE_URL path never pulls in
    ``google-cloud-secret-manager`` — only the superadmin Cloud SQL path touches it.

    The secret RESOURCE NAME is read directly from ``os.environ`` (no ``app.core``
    import — base.py must not create an import cycle with config). The value is the
    full resource path, e.g. ``projects/<p>/secrets/<name>/versions/latest``.

    Cached (``lru_cache(maxsize=1)``) so the secret is accessed once per process —
    the password is long-lived and the access call is billable / latency-bearing.
    """
    from google.cloud import secretmanager

    secret_name = os.environ["SUPERADMIN_DB_PASSWORD_SECRET"]
    client = secretmanager.SecretManagerServiceClient()
    response = client.access_secret_version(name=secret_name)
    return response.payload.data.decode("utf-8")


def _superadmin_connector_creator():
    """SQLAlchemy ``creator`` that dials Cloud SQL as the ``app_superadmin`` role.

    Clones :func:`_connector_creator`'s shape but swaps the credential path to
    **Path B** (D-05a): the user is the EXACT literal ``"app_superadmin"`` (so
    ``current_user = 'app_superadmin'`` matches the 0003 ``*_superadmin_all`` bypass
    policy) and authentication is by ``password=`` from Secret Manager rather than
    ``enable_iam_auth=True``. Reuses the single process ``Connector``
    (:func:`_get_connector`) — does NOT build a second one.
    """
    return _get_connector().connect(
        os.environ["INSTANCE_CONNECTION_NAME"],  # "project:region:instance"
        "pg8000",
        user="app_superadmin",  # EXACT literal — 0003's current_user predicate
        password=_load_superadmin_password(),  # Path B: stored secret (D-05a/D-09)
        db=os.environ["DB_NAME"],
        ip_type=os.environ.get("CLOUD_SQL_IP_TYPE", "PUBLIC"),  # WR-05: explicit
    )


@functools.lru_cache(maxsize=1)
def get_superadmin_engine():
    """Return the shared sync engine that connects as ``app_superadmin`` (D-05/D-05a).

    A SEPARATE process-singleton engine alongside :func:`get_engine` (which is
    regression-frozen). Used ONLY by the superadmin code path: because it connects
    as ``current_user = 'app_superadmin'`` the 0003 bypass policy admits cross-tenant
    reads/writes, so the superadmin path sets NO ``app.current_space_id`` GUC
    (Pitfall 2 — the bypass is current_user-based, not GUC-based).

    Carries the same bounded pool args (``_POOL_KW``, D-04) and the same defensive
    per-checkin GUC RESET (D-02) as :func:`get_engine`.
    """
    engine = create_engine(
        "postgresql+pg8000://",
        creator=_superadmin_connector_creator,
        **_POOL_KW,
    )
    _register_guc_reset(engine)
    return engine


def _register_guc_reset(engine) -> None:
    """Register a per-``checkin`` event that resets ``app.current_space_id`` (D-02).

    Pattern 4 (04-RESEARCH.md): the ``checkin`` listener receives the RAW DBAPI
    (pg8000) connection — NOT a SQLAlchemy ``Connection`` — so we open a cursor on it
    directly (``set_space_context`` expects a SA executor and must NOT be used here).
    ``RESET app.current_space_id`` on a connection where the GUC was never set is a
    harmless no-op. Registered on the ENGINE (not the pool) so ``engine.dispose()``
    carries the listener to a freshly-built pool.

    Belt-only: the canonical ``SET LOCAL`` (``app/db/rls.py``) already reverts the GUC
    at COMMIT. This RESET proves — in the pooled-reuse regression — that even a
    session-scoped accidental leak would be scrubbed before the connection is reused.
    """

    @event.listens_for(engine, "checkin")
    def _reset_space_guc(dbapi_connection, connection_record):  # noqa: ANN001
        cur = dbapi_connection.cursor()
        try:
            cur.execute("RESET app.current_space_id")
        finally:
            cur.close()


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
