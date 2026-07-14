"""Phase 11 (i18n) schema-shape suite — the 0010 locale columns (I18N-01 / I18N-02).

Verifies the two columns the ``GET /me`` / ``PATCH /me/locale`` resolution chain (D-07)
depends on, added by ``0010_locale_columns.py``:

  - ``organizations.default_locale``  — NOT NULL, column default 'nl' (server_default
    backfills every existing org row non-null on apply; the base of the resolution chain).
  - ``organization_memberships.locale`` — NULLABLE (null = "inherit space default"; also the
    superadmin's own locale home when a membership row exists — Open Q1).

Mirrors ``test_schema_shape.py``'s ``information_schema.columns`` is_nullable probe (the same
shape ``test_status_columns_exist_not_null`` uses) plus a ``column_default`` check for the
'nl' server_default. ``pytestmark = pytest.mark.integration`` makes it SKIP without Docker;
the ``engine`` fixture builds the schema via ``alembic upgrade head`` (the Cloud Build suite
is the phase-gate runner — this dev box has no Python/Docker).

Authoritative references:
- backend/tests/test_schema_shape.py (the is_nullable + information_schema.columns probe idiom)
- backend/app/db/alembic/versions/0010_locale_columns.py (the migration under test)
- .planning/phases/11-internationalization-nl-fr-en/11-PATTERNS.md § 0010 migration / models
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

# The Postgres schema all application tables live in.
SCHEMA = "nestor"


# ---------------------------------------------------------------------------
# I18N-02: organizations.default_locale exists, NOT NULL, default 'nl'
# ---------------------------------------------------------------------------


def test_default_locale_not_null_with_nl_default(engine):
    """``organizations.default_locale`` exists, is NOT NULL, and defaults to 'nl'.

    The NOT NULL + server_default 'nl' pair is what backfills EVERY existing org row
    non-null on the 0010 apply — a nullable column (or a missing default) would let an
    existing row carry NULL and break the resolution chain's "space default" leg (D-07).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        col = conn.execute(
            text(
                "SELECT is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'organizations' "
                "AND column_name = 'default_locale'"
            ),
            {"schema": SCHEMA},
        ).first()

    assert col is not None, (
        f"{SCHEMA}.organizations: missing default_locale column (Phase 11 / 0010)"
    )
    assert col[0] == "NO", (
        f"{SCHEMA}.organizations.default_locale must be NOT NULL "
        f"(got is_nullable={col[0]!r}) — a nullable default breaks the D-07 chain"
    )
    # column_default renders the server_default; Postgres stores the string literal
    # 'nl' with a type cast, e.g. "'nl'::character varying". Assert the 'nl' literal is
    # present rather than pinning the exact cast rendering.
    assert col[1] is not None and "'nl'" in col[1], (
        f"{SCHEMA}.organizations.default_locale must default to 'nl' "
        f"(got column_default={col[1]!r}) — the 0010 backfill value (D-07 fallback)"
    )


# ---------------------------------------------------------------------------
# I18N-01: organization_memberships.locale exists AND is NULLABLE
# ---------------------------------------------------------------------------


def test_membership_locale_is_nullable(engine):
    """``organization_memberships.locale`` exists and is NULLABLE.

    Nullable is load-bearing: ``null`` means "no override -> inherit the space default"
    (D-07). A NOT NULL locale would force every membership to carry an override and break
    the inherit-from-space leg of the chain, and would also require a backfill the design
    deliberately avoids (superadmin-no-membership home, Open Q1).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        col = conn.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns "
                "WHERE table_schema = :schema AND table_name = 'organization_memberships' "
                "AND column_name = 'locale'"
            ),
            {"schema": SCHEMA},
        ).first()

    assert col is not None, (
        f"{SCHEMA}.organization_memberships: missing locale column (Phase 11 / 0010)"
    )
    assert col[0] == "YES", (
        f"{SCHEMA}.organization_memberships.locale must be NULLABLE "
        f"(got is_nullable={col[0]!r}) — null = inherit the space default (D-07)"
    )


# ---------------------------------------------------------------------------
# No new index on the scalar locale columns (alembic-check-clean intent)
# ---------------------------------------------------------------------------


def test_no_index_on_locale_columns(engine):
    """No index touches ``default_locale`` or membership ``locale`` (0010 adds none).

    Both are scalar columns read via the existing PK/FK lookup; a stray locale index would
    drift the ORM<->migration index-name 1:1 match the project relies on for a clean
    ``alembic check`` (the same discipline as the audit_log explicit-index names in 0006).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        idx_rows = conn.execute(
            text(
                """
                SELECT t.relname AS table_name, a.attname AS column_name, i.relname AS index_name
                FROM pg_index x
                JOIN pg_class t       ON t.oid = x.indrelid
                JOIN pg_class i       ON i.oid = x.indexrelid
                JOIN pg_namespace n   ON n.oid = t.relnamespace
                JOIN pg_attribute a   ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
                WHERE n.nspname = :schema
                  AND (
                    (t.relname = 'organizations' AND a.attname = 'default_locale')
                    OR (t.relname = 'organization_memberships' AND a.attname = 'locale')
                  )
                """
            ),
            {"schema": SCHEMA},
        ).all()

    assert idx_rows == [], (
        "NO index may exist on the locale columns this phase (0010 adds none); "
        f"found: {[(r[0], r[1], r[2]) for r in idx_rows]}"
    )
