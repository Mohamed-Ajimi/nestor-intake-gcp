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

from pydantic import field_validator
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

    Identity Platform (Phase 3):
    - ``firebase_project_id`` -> FIREBASE_PROJECT_ID. **Non-secret** explicit
      override for the Admin SDK's project. Normally ADC supplies the project via
      ``GOOGLE_CLOUD_PROJECT`` on Cloud Run, so this field stays ``None`` there and
      exists only to pin the project locally / in tests (Pitfall 5: the verified
      token's ``aud`` must match the project). NO service-account key / secret field
      is added by design (D-09) — IdP init relies on ADC, not a key in env.
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

    # Identity Platform: non-secret explicit project override (env FIREBASE_PROJECT_ID).
    # None on Cloud Run (ADC supplies the project via GOOGLE_CLOUD_PROJECT). No secret here (D-09).
    firebase_project_id: str | None = None

    # CORS allowlist for the cross-origin browser handshake (WR-03). The frontend
    # (Cloudflare Workers origin) calls this backend (Cloud Run origin) directly with
    # an Authorization header, so the browser preflight (OPTIONS) must be answered with
    # an EXPLICIT origin allowlist. Env CORS_ALLOWED_ORIGINS is a comma-separated list
    # of exact origins (e.g. "https://nestor.example.com,http://localhost:5173").
    #
    # Default is EMPTY -> NO CORSMiddleware is installed and NO permissive "*" is ever
    # used (never broaden access by default). Credentials are allowed only against this
    # pinned allowlist — never "*" + credentials together (forbidden by the browser and
    # by this design).
    cors_allowed_origins: list[str] = []

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: object) -> object:
        """Accept a comma-separated CORS_ALLOWED_ORIGINS string (env-friendly).

        pydantic-settings would otherwise expect JSON for a ``list[str]`` env value;
        this lets ``CORS_ALLOWED_ORIGINS=https://a.example,https://b.example`` work.
        An empty/whitespace string -> empty list (no origins -> middleware not added).
        A list is passed through unchanged (programmatic / test construction).
        """
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v


def get_settings() -> Settings:
    """Return a freshly-read ``Settings`` instance.

    Not cached so tests can vary the environment per case; callers that want a
    process singleton can memoize at their own layer.
    """
    return Settings()
