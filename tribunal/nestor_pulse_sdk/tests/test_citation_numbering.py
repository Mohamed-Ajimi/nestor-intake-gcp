"""
Citation [n] numbering tests (Phase 15 ENGINE-09, D13).

Proves number_citations(session, run_id):
  * DETERMINISM   -- two calls for the same run produce byte-identical numbering.
  * ALL-RESOLVE   -- every [n] resolves to a real source row (no dangling number).
  * SINGLE-SOURCE -- the single_source flag is correct per first-appearance claim.
  * D13           -- numbers come from claim.position DB ordering, NOT the model.

Two layers:
  1. Pure heuristic unit tests (derive_quality_tier) -- run with NO DB on any box.
  2. DB-backed numbering tests -- integration, seed claim/source/claim_source rows
     for one run under a tenant context, then assert. Skip-clean when DATABASE_URL
     is unset (dev box has no Postgres); EXECUTE in Cloud Build against live Cloud
     SQL. Mirrors test_rls_isolation.py's live-engine + tenant-context pattern.

Cloud Build gate:
  pytest nestor_pulse_sdk/tests/test_citation_numbering.py \
         nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x
"""

from __future__ import annotations

import os
import uuid

import pytest

from nestor_pulse_sdk.citations.numbering import derive_quality_tier


# ---------------------------------------------------------------------------
# Layer 1: pure heuristic -- NO DB (runs everywhere).
# ---------------------------------------------------------------------------

class TestDeriveQualityTier:
    def test_official_domains_are_tier_1(self):
        assert derive_quality_tier("google", "https://www.sec.gov/edgar/x") == 1
        assert derive_quality_tier(None, "https://ec.europa.eu/eurostat") == 1
        assert derive_quality_tier(None, "https://data.gov.uk/dataset") == 1
        assert derive_quality_tier(None, "https://mit.edu/report") == 1

    def test_established_press_is_tier_2(self):
        assert derive_quality_tier(None, "https://www.reuters.com/markets") == 2
        assert derive_quality_tier(None, "https://www.ft.com/content/x") == 2
        assert derive_quality_tier(None, "https://www.statista.com/x") == 2

    def test_blog_or_unknown_is_tier_3(self):
        assert derive_quality_tier("tribunal_skeptic", "https://some-blog.example/p") == 3
        assert derive_quality_tier(None, "https://randomsite.xyz/post") == 3
        assert derive_quality_tier(None, None) == 3

    def test_malformed_url_never_raises(self):
        # A garbage url must degrade to tier 3, never raise.
        assert derive_quality_tier(None, "not a url ::://") == 3

    def test_deterministic_for_same_input(self):
        for _ in range(50):
            assert derive_quality_tier("google", "https://www.reuters.com/x") == 2


# ---------------------------------------------------------------------------
# Layer 2: DB-backed numbering -- integration, skip-clean without DATABASE_URL.
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.integration


def _require_database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.skip(
            "DATABASE_URL not set -- run in Cloud Build against live Cloud SQL "
            "(dev box has no Postgres). See test_rls_isolation.py."
        )
    return url


@pytest.fixture
async def live_engine():
    url = _require_database_url()
    sa = pytest.importorskip("sqlalchemy.ext.asyncio")
    engine = sa.create_async_engine(url, echo=False, future=True)
    try:
        yield engine
    finally:
        await engine.dispose()


async def _seed_run_with_citations(engine, tenant_id: uuid.UUID) -> uuid.UUID:
    """Seed one org + project + run + 3 claims / 3 sources / claim_source links.

    Claim positions 0,1,2 give a deterministic first-appearance order. Claim 0
    cites sources s0+s1 (multi-source); claims 1,2 each cite exactly one source
    (s2, then s0 re-used) so we can assert single_source + de-dup numbering.
    Returns the run_id.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.db.rls import set_tenant_context

    run_id = uuid.uuid4()
    project_id = uuid.uuid4()
    slug = f"num-{tenant_id.hex[:8]}"

    # org is the tenant root (not RLS-scoped) -- insert directly.
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO org (id, name, slug, retention_days) "
                "VALUES (:id, :name, :slug, 180)"
            ),
            {"id": tenant_id, "name": "Numbering test org", "slug": slug},
        )

    s0, s1, s2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    c0, c1, c2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            await session.execute(
                text(
                    "INSERT INTO project (id, tenant_id, name) "
                    "VALUES (:id, :tid, :name)"
                ),
                {"id": project_id, "tid": tenant_id, "name": "Numbering proj"},
            )
            await session.execute(
                text(
                    "INSERT INTO run (id, tenant_id, project_id, engine, brief, "
                    "status, idempotency_key) "
                    "VALUES (:id, :tid, :pid, 'sdk', 'b', 'completed', :ik)"
                ),
                {"id": run_id, "tid": tenant_id, "pid": project_id, "ik": uuid.uuid4()},
            )
            for sid, url, prov in (
                (s0, "https://www.reuters.com/a", "google"),
                (s1, "https://www.sec.gov/b", "google"),
                (s2, "https://some-blog.example/c", "tribunal_skeptic"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO source (id, tenant_id, url, provider, snapshot_text) "
                        "VALUES (:id, :tid, :url, :prov, :snap)"
                    ),
                    {"id": sid, "tid": tenant_id, "url": url, "prov": prov, "snap": url},
                )
            for cid, pos in ((c0, 0), (c1, 1), (c2, 2)):
                await session.execute(
                    text(
                        "INSERT INTO claim (id, tenant_id, run_id, text, facet, position) "
                        "VALUES (:id, :tid, :rid, :txt, 'f', :pos)"
                    ),
                    {"id": cid, "tid": tenant_id, "rid": run_id, "txt": f"claim {pos}", "pos": pos},
                )
            # c0 -> s0 + s1 (multi); c1 -> s2 (single); c2 -> s0 (single, re-used).
            for cid, sid in ((c0, s0), (c0, s1), (c1, s2), (c2, s0)):
                await session.execute(
                    text(
                        "INSERT INTO claim_source (claim_id, source_id, tenant_id) "
                        "VALUES (:cid, :sid, :tid)"
                    ),
                    {"cid": cid, "sid": sid, "tid": tenant_id},
                )
    return run_id


async def _drop_org(engine, tenant_id: uuid.UUID) -> None:
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM org WHERE id = :id"), {"id": tenant_id})


async def test_numbering_is_deterministic_and_all_resolve(live_engine):
    """Two calls produce identical numbering, and every [n] resolves to a source."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.citations.numbering import number_citations
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_id = uuid.uuid4()
    run_id = await _seed_run_with_citations(live_engine, tenant_id)
    try:
        Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                first = await number_citations(session, run_id)
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                second = await number_citations(session, run_id)

        # DETERMINISM: byte-identical across calls.
        assert first == second, "numbering must be deterministic across calls"

        # Numbers are a contiguous 1..N with no gaps (generated, not model-emitted).
        ns = [e["n"] for e in first]
        assert ns == list(range(1, len(first) + 1)), f"[n] must be contiguous 1..N, got {ns}"

        # ALL-RESOLVE: every entry carries a real source_id + url.
        assert first, "expected at least one numbered citation"
        for e in first:
            assert e["source_id"], "every [n] must resolve to a source_id"
            assert e["url"], "every numbered source must carry a url"

        # De-dup: s0 is cited by c0 AND c2 but numbered ONCE (3 distinct sources).
        assert len(first) == 3, f"3 distinct sources expected, got {len(first)}"

    finally:
        await _drop_org(live_engine, tenant_id)


async def test_single_source_flag_is_correct(live_engine):
    """single_source reflects the first-appearance claim's distinct source count."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.citations.numbering import number_citations
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_id = uuid.uuid4()
    run_id = await _seed_run_with_citations(live_engine, tenant_id)
    try:
        Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                numbered = await number_citations(session, run_id)

        by_url = {e["url"]: e for e in numbered}
        # s0 + s1 first appear on c0 (which cites TWO sources) -> not single_source.
        assert by_url["https://www.reuters.com/a"]["single_source"] is False
        assert by_url["https://www.sec.gov/b"]["single_source"] is False
        # s2 first appears on c1 (which cites exactly ONE source) -> single_source.
        assert by_url["https://some-blog.example/c"]["single_source"] is True

        # Tier heuristic rode through the DB path too.
        assert by_url["https://www.sec.gov/b"]["quality_tier"] == 1
        assert by_url["https://www.reuters.com/a"]["quality_tier"] == 2
        assert by_url["https://some-blog.example/c"]["quality_tier"] == 3
    finally:
        await _drop_org(live_engine, tenant_id)
