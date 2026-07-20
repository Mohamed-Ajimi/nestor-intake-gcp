"""
ENGINE-01 -- Tribunal Alembic-line isolation (owning plan: 13-02).

The Tribunal engine shares a Cloud SQL instance with the intake backend, and
BOTH Alembic lines ship colliding revision IDs 0001-0010 (authored from the
same GSD template). If Tribunal wrote the default `public.alembic_version`
table it would either collide with intake's line or silently skip its own
`0001` (already-applied), leaving Tribunal tables missing -> first run 500s
(13-RESEARCH.md Pitfall 1; threat T-13-04).

The fix (Plan 13-02 Task 1) makes the Tribunal line self-isolating:
  * `env.py` writes `tribunal_alembic_version` in schema `tribunal`
    (NOT `public.alembic_version`), and `SET search_path TO tribunal` before
    running migrations so unqualified `op.create_table(...)` and migration
    0008's GRANT/POLICY statements land in `tribunal`.
  * migration `0008_worker_rls_role.py` targets `SCHEMA tribunal`, not
    `SCHEMA public` (13-RESEARCH.md Pitfall 2; threat T-13-05) -- otherwise the
    worker gets privileges on the wrong schema and claims ZERO rows.
  * the ORM `Run.ck_run_status` CHECK literal is synced to include
    `needs_report_spec` (13-RESEARCH.md Pitfall 4 -- cosmetic ORM/DB drift).

Tests:
  1. test_env_configures_isolated_version_table: env.py source declares
     `tribunal_alembic_version` + `version_table_schema="tribunal"` +
     `search_path TO tribunal` in BOTH configure paths (static assertion; no
     live DB needed -- mirrors the suite's Docker-optional shape).
  2. test_migration_0008_targets_tribunal_schema: 0008 has ZERO literal
     `SCHEMA public` and at least one `SCHEMA tribunal` (upgrade + downgrade).
  3. test_run_model_check_includes_needs_report_spec: the ORM CHECK literal
     lists `needs_report_spec`.
  4. test_upgrade_head_writes_tribunal_version_table (LIVE, skip-guarded): after
     `alembic upgrade head` into a fresh DB the version table is
     `tribunal.tribunal_alembic_version` and the `run` table lives in schema
     `tribunal`, NOT `public`. Runs only when a live DB is reachable
     (testcontainers Docker or DATABASE_URL) -- authored-by-construction and
     executed later in Plan 04's Cloud Build suite.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

_SDK_ROOT = Path(__file__).resolve().parents[1]
_ENV_PY = _SDK_ROOT / "alembic" / "env.py"
_MIG_0008 = _SDK_ROOT / "alembic" / "versions" / "0008_worker_rls_role.py"


# ---------------------------------------------------------------------------
# Static assertions (no live DB) -- these encode the ENGINE-01 contract.
# ---------------------------------------------------------------------------

def test_env_configures_isolated_version_table() -> None:
    """env.py must write `tribunal_alembic_version` in schema `tribunal` and
    set search_path in BOTH the offline and online configure paths."""
    src = _ENV_PY.read_text(encoding="utf-8")
    assert 'version_table="tribunal_alembic_version"' in src, (
        "env.py must set version_table=tribunal_alembic_version so the Tribunal "
        "line never shares intake's alembic_version (Pitfall 1 / T-13-04)"
    )
    assert 'version_table_schema="tribunal"' in src, (
        "env.py must set version_table_schema=tribunal"
    )
    # Both configure() calls carry the isolation keys -> two occurrences each.
    assert src.count('version_table="tribunal_alembic_version"') >= 2, (
        "both offline and online configure() paths must set version_table"
    )
    assert src.count('version_table_schema="tribunal"') >= 2, (
        "both offline and online configure() paths must set version_table_schema"
    )
    assert "CREATE SCHEMA IF NOT EXISTS tribunal" in src, (
        "env.py must ensure the tribunal schema exists before migrating"
    )
    assert "search_path TO tribunal" in src, (
        "env.py must SET search_path TO tribunal so unqualified DDL/GRANTs land "
        "in the tribunal schema (Pitfall 2 / T-13-05)"
    )
    # The async engine build stays asyncpg -- NOT forced onto pg8000/IAM (Pitfall 5).
    assert "async_engine_from_config" in src, (
        "env.py must keep its existing asyncpg async engine build (Pitfall 5)"
    )
    assert "pg8000" not in src, "env.py must NOT add a pg8000/IAM connector (Pitfall 5)"


def test_migration_0008_targets_tribunal_schema() -> None:
    """0008 must reference `SCHEMA tribunal`, never `SCHEMA public`."""
    src = _MIG_0008.read_text(encoding="utf-8")
    assert "SCHEMA public" not in src, (
        "migration 0008 must not grant worker_user on SCHEMA public -- it would "
        "claim ZERO rows in the tribunal schema (Pitfall 2 / T-13-05)"
    )
    assert "SCHEMA tribunal" in src, (
        "migration 0008 must grant worker_user on SCHEMA tribunal"
    )


def test_run_model_check_includes_needs_report_spec() -> None:
    """The ORM ck_run_status literal must include `needs_report_spec` (Pitfall 4)."""
    run_py = (_SDK_ROOT / "db" / "models" / "run.py").read_text(encoding="utf-8")
    assert "needs_report_spec" in run_py, (
        "Run.ck_run_status must list needs_report_spec to match migration 0007 "
        "(Pitfall 4 -- cosmetic ORM/DB drift)"
    )


# ---------------------------------------------------------------------------
# Live assertion (skip-guarded) -- runs in Plan 04's Cloud Build suite.
# ---------------------------------------------------------------------------

def _live_database_url() -> str | None:
    """Return an asyncpg DATABASE_URL if a live DB is explicitly provided.

    Mirrors the suite's Docker-optional shape: when neither DATABASE_URL nor a
    reachable testcontainers Docker is present, the live test skips cleanly
    (dev machine has no Python/Docker -- author-by-construction, run in CI).
    """
    url = os.environ.get("DATABASE_URL")
    if url and url.startswith("postgresql+asyncpg://"):
        return url
    return None


@pytest.mark.asyncio
async def test_upgrade_head_writes_tribunal_version_table() -> None:
    """After `alembic upgrade head`, the version table is
    `tribunal.tribunal_alembic_version` and `run` lives in schema `tribunal`.

    Skip-guarded: needs a live DB (testcontainers Docker OR an explicit
    asyncpg DATABASE_URL). Authored-by-construction; executed in Plan 04.
    """
    sa = pytest.importorskip("sqlalchemy")
    sa_asyncio = pytest.importorskip("sqlalchemy.ext.asyncio")
    text = sa.text

    # Prefer testcontainers; fall back to an explicit asyncpg DATABASE_URL.
    url = _live_database_url()
    container = None
    if url is None:
        try:
            from testcontainers.postgres import PostgresContainer  # type: ignore
        except ImportError:
            pytest.skip("no live DB: DATABASE_URL unset and testcontainers absent")
        try:
            container = PostgresContainer("postgres:15")
            container.start()
        except Exception as exc:  # noqa: BLE001 -- DockerException family
            pytest.skip(f"no live DB: Docker unavailable ({exc})")
        url = container.get_connection_url().replace(
            "postgresql+psycopg2://", "postgresql+asyncpg://"
        )

    try:
        # Run the real Alembic line against the fresh DB via its own env.py.
        from alembic import command  # type: ignore
        from alembic.config import Config  # type: ignore

        os.environ["DATABASE_URL"] = url
        alembic_ini = _SDK_ROOT / "alembic.ini"
        cfg = Config(str(alembic_ini)) if alembic_ini.exists() else Config()
        cfg.set_main_option("script_location", str(_SDK_ROOT / "alembic"))
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")

        engine = sa_asyncio.create_async_engine(url, future=True)
        try:
            async with engine.connect() as conn:
                version_schema = await conn.scalar(
                    text(
                        "SELECT table_schema FROM information_schema.tables "
                        "WHERE table_name = 'tribunal_alembic_version'"
                    )
                )
                assert version_schema == "tribunal", (
                    "version table must live in schema tribunal, got "
                    f"{version_schema!r}"
                )
                # The default public.alembic_version must NOT exist for this line.
                public_ver = await conn.scalar(
                    text(
                        "SELECT COUNT(*) FROM information_schema.tables "
                        "WHERE table_schema='public' AND table_name='alembic_version'"
                    )
                )
                assert public_ver == 0, (
                    "Tribunal must NOT write public.alembic_version (Pitfall 1)"
                )
                run_schema = await conn.scalar(
                    text(
                        "SELECT table_schema FROM information_schema.tables "
                        "WHERE table_name='run' ORDER BY table_schema LIMIT 1"
                    )
                )
                assert run_schema == "tribunal", (
                    f"run table must live in schema tribunal, got {run_schema!r}"
                )
        finally:
            await engine.dispose()
    finally:
        if container is not None:
            try:
                container.stop()
            except Exception:  # noqa: BLE001
                pass
