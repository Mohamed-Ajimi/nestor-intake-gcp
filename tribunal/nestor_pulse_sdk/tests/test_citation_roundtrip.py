"""PHASE1-05 -- Citation round-trip schema (owning plan: 09).

Per 01-VALIDATION.md row:
  "Citation round-trip: claim -> claim_source -> source -> snapshot_text
   reachable in 1 query each"
  Test type: unit (integration via testcontainers Postgres)
  Command: pytest nestor_pulse_sdk/tests/test_citation_roundtrip.py -x

Three tests:
  1. test_claim_to_source_via_claim_source_in_one_query
     - Insert claim + source + claim_source; one JOIN reaches snapshot_text.
  2. test_source_snapshot_text_round_trips
     - Insert snapshot_text='alpha'; read back byte-for-byte equal.
  3. test_source_upsert_by_content_hash_dedupes
     - Two inserts with same (tenant_id, content_hash) -> exactly 1 row.

Plan 09 dropped the Plan 02 xfail marker now that the schema + extractor are
real. The `postgres_container` fixture in conftest.py calls `pytest.skip()`
when Docker / testcontainers is unreachable, so the suite still exits 0 on
dev boxes without Docker (per 01-VALIDATION.md Environment Notes).
"""
from __future__ import annotations

import uuid

import pytest  # noqa: F401  (kept for future markers; fixtures use it)


async def _bootstrap_schema(async_engine, tenant_id):
    """Create all tables + an `org` row matching `tenant_id`."""
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
    from nestor_pulse_sdk.db.base import Base
    from nestor_pulse_sdk.db.models import Org

    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    Session = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        async with session.begin():
            session.add(Org(id=tenant_id, name="Acme", slug="acme"))
    return Session


async def test_claim_to_source_via_claim_source_in_one_query(
    async_engine, set_tenant
):
    """A single JOIN reaches `source.snapshot_text` from a `claim.id`."""
    from sqlalchemy import text
    from nestor_pulse_sdk.db.models import Claim, ClaimSource, Project, Run, Source

    tenant_id = uuid.uuid4()
    Session = await _bootstrap_schema(async_engine, tenant_id)

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            project = Project(tenant_id=tenant_id, name="P")
            session.add(project)
            await session.flush()
            run = Run(
                tenant_id=tenant_id,
                project_id=project.id,
                engine="sdk",
                brief="b",
                idempotency_key=uuid.uuid4(),
            )
            session.add(run)
            await session.flush()
            source = Source(
                tenant_id=tenant_id,
                url="https://example.com/a",
                provider="anthropic",
                snapshot_text="snapshot alpha",
                content_hash="h-alpha",
            )
            session.add(source)
            await session.flush()
            claim = Claim(
                tenant_id=tenant_id, run_id=run.id, text="alpha claim", facet="general"
            )
            session.add(claim)
            await session.flush()
            session.add(
                ClaimSource(
                    tenant_id=tenant_id, claim_id=claim.id, source_id=source.id
                )
            )
            claim_id = claim.id

        async with session.begin():
            await set_tenant(session, tenant_id)
            result = await session.execute(
                text(
                    "SELECT s.snapshot_text "
                    "FROM claim c "
                    "JOIN claim_source cs ON cs.claim_id = c.id "
                    "JOIN source s ON s.id = cs.source_id "
                    "WHERE c.id = :cid"
                ),
                {"cid": str(claim_id)},
            )
            row = result.first()
    assert row is not None
    assert row.snapshot_text == "snapshot alpha"


async def test_source_snapshot_text_round_trips(async_engine, set_tenant):
    """Inserted `snapshot_text` equals selected `snapshot_text` byte-for-byte."""
    from sqlalchemy import select
    from nestor_pulse_sdk.db.models import Source

    tenant_id = uuid.uuid4()
    Session = await _bootstrap_schema(async_engine, tenant_id)

    payload = "alpha\nbeta — gamma\n\thttps://example.com/x?y=1&z=2"

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            src = Source(
                tenant_id=tenant_id,
                url="https://example.com/x",
                provider="openai",
                snapshot_text=payload,
                content_hash="h-x",
            )
            session.add(src)
            await session.flush()
            source_id = src.id

        async with session.begin():
            await set_tenant(session, tenant_id)
            result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            fetched = result.scalar_one()

    assert fetched.snapshot_text == payload


async def test_source_upsert_by_content_hash_dedupes(async_engine, set_tenant):
    """Two inserts with the same (tenant_id, content_hash) -> only 1 row."""
    from sqlalchemy import text

    tenant_id = uuid.uuid4()
    Session = await _bootstrap_schema(async_engine, tenant_id)

    async with Session() as session:
        async with session.begin():
            await set_tenant(session, tenant_id)
            for url in ("https://example.com/dup1", "https://example.com/dup2"):
                await session.execute(
                    text(
                        "INSERT INTO source "
                        "(id, tenant_id, url, provider, snapshot_text, content_hash) "
                        "VALUES (:id, :tid, :url, 'anthropic', 'shared snapshot', :h) "
                        "ON CONFLICT (tenant_id, content_hash) "
                        "WHERE content_hash IS NOT NULL DO NOTHING"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "tid": str(tenant_id),
                        "url": url,
                        "h": "shared-content-hash",
                    },
                )

        async with session.begin():
            await set_tenant(session, tenant_id)
            count_result = await session.execute(
                text(
                    "SELECT COUNT(*) AS n FROM source "
                    "WHERE tenant_id = :tid AND content_hash = :h"
                ),
                {"tid": str(tenant_id), "h": "shared-content-hash"},
            )
            count_row = count_result.first()

    assert count_row.n == 1
