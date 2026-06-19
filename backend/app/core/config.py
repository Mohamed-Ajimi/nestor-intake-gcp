"""Typed environment configuration (pydantic-settings).

Exposes the env names the backend reads at runtime as a validated ``Settings``
object for ``app.main`` and any future typed consumer. All fields are
**non-secret** and optional with sane defaults — there is **no DB password
field by design** (D-09): Cloud SQL access is IAM-only via the connector, which
needs only the non-secret ``INSTANCE_CONNECTION_NAME`` / ``DB_USER`` / ``DB_NAME``.

Planner note (D-06, 02-PATTERNS.md): ``app.db.base`` deliberately keeps reading
``os.environ`` directly for the connector branch so the engine factory has **no
import cycle** with ``app.core``. This module does NOT replace those reads — it
exists for ``main.py`` / typed validation and keeps the env-name contract in one
place. The field env names here MUST match what ``base.py`` reads.

Authoritative references:
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-RESEARCH.md
    § Standard Stack -- pydantic-settings reads INSTANCE_CONNECTION_NAME / DB_USER /
      DB_NAME / DATABASE_URL / PORT
- .planning/phases/02-backend-skeleton-cloud-sql-wiring/02-PATTERNS.md
    § backend/app/core/config.py -- non-secret fields, no import cycle with base.py
- D-06 (minimal skeleton, no speculative trees) / D-09 (no DB password, IAM auth)
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated, env-backed application settings — all fields non-secret.

    Cloud SQL connector identity (set on Cloud Run by Terraform):
    - ``instance_connection_name`` -> INSTANCE_CONNECTION_NAME ("project:region:instance")
    - ``db_user``                  -> DB_USER (IAM SA login name, no password)
    - ``db_name``                  -> DB_NAME (the ``nestor`` application DB)

    Local / test path (never set on Cloud Run):
    - ``database_url`` -> DATABASE_URL (postgresql+pg8000:// DSN for testcontainers)

    Runtime:
    - ``port`` -> PORT (Cloud Run injects this; default 8080)
    """

    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=False,
        extra="ignore",
    )

    instance_connection_name: str | None = None
    db_user: str | None = None
    db_name: str | None = None
    database_url: str | None = None
    port: int = 8080


def get_settings() -> Settings:
    """Return a freshly-read ``Settings`` instance.

    Not cached so tests can vary the environment per case; callers that want a
    process singleton can memoize at their own layer.
    """
    return Settings()
