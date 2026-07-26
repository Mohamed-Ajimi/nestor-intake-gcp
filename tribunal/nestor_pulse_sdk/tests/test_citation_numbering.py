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
# Layer 1b: the PURE assignment loop (Phase 15.2, D-05) -- NO DB.
#
# `_assign_numbers` is the extracted body of `number_citations`. Proving it with
# hand-built rows is what lets the claim -> [n] map (the thing the anchor
# post-pass resolves against) be verified on a box with no Postgres.
# ---------------------------------------------------------------------------


def _row(claim_id: str, source_id: str, position: int, url: str = "https://x.example/a"):
    """One ordered claim -> source row, in the shape _CLAIM_SOURCE_SQL returns."""
    return {
        "claim_id": claim_id,
        "position": position,
        "source_id": source_id,
        "title": None,
        "url": url,
        "provider": "google",
        "fetched_at": None,
    }


class TestAssignNumbers:
    def test_numbers_sources_at_first_appearance(self):
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        rows = [
            _row("c1", "s1", 0, "https://www.sec.gov/a"),
            _row("c1", "s2", 0, "https://www.reuters.com/b"),
            _row("c2", "s1", 1, "https://www.sec.gov/a"),  # re-use, not re-numbered
            _row("c3", "s3", 2, "https://blog.example/c"),
        ]
        numbered, _ = _assign_numbers(rows)

        assert [e["n"] for e in numbered] == [1, 2, 3]
        assert [e["source_id"] for e in numbered] == ["s1", "s2", "s3"]
        # Documented entry shape.
        assert set(numbered[0]) == {
            "n", "source_id", "title", "url", "provider", "publication_date",
            "quality_tier", "single_source", "first_claim_id",
            "first_claim_position",
        }
        # s1/s2 first appear on c1, which cites TWO sources -> not single_source.
        assert numbered[0]["single_source"] is False
        assert numbered[1]["single_source"] is False
        # s3 first appears on c3, which cites exactly one -> single_source.
        assert numbered[2]["single_source"] is True
        # The tier heuristic rides through unchanged.
        assert [e["quality_tier"] for e in numbered] == [1, 2, 3]

    def test_is_deterministic(self):
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        rows = [_row("c1", "s1", 0), _row("c2", "s2", 1), _row("c3", "s1", 2)]
        first = _assign_numbers(rows)
        for _ in range(10):
            assert _assign_numbers(rows) == first

    def test_claim_map_covers_EVERY_claim_not_just_first_appearances(self):
        """The whole point of the map (D-05).

        c2 and c3 introduce no new source -- a map keyed off `first_claim_id`
        would contain only c1 and leave two thirds of the model's anchors
        unresolvable.
        """
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        rows = [
            _row("c1", "s1", 0),
            _row("c2", "s1", 1),
            _row("c3", "s1", 2),
        ]
        numbered, claim_to_n = _assign_numbers(rows)

        assert len(numbered) == 1, "one distinct source"
        assert set(claim_to_n) == {"c1", "c2", "c3"}
        first_claim_ids = {e["first_claim_id"] for e in numbered}
        assert first_claim_ids == {"c1"}
        assert set(claim_to_n) - first_claim_ids == {"c2", "c3"}

    def test_a_claim_reusing_an_earlier_source_maps_to_that_earlier_n(self):
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        rows = [_row("c1", "s1", 0), _row("c2", "s2", 1), _row("c3", "s1", 2)]
        _, claim_to_n = _assign_numbers(rows)
        assert claim_to_n == {"c1": 1, "c2": 2, "c3": 1}

    def test_a_claim_citing_two_sources_maps_to_the_first_in_row_order(self):
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        rows = [_row("c1", "s1", 0), _row("c1", "s2", 0)]
        _, claim_to_n = _assign_numbers(rows)
        assert claim_to_n == {"c1": 1}

    def test_empty_rows(self):
        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        assert _assign_numbers([]) == ([], {})
        assert _assign_numbers(None) == ([], {})

    def test_fetched_at_is_carried_as_an_iso_retrieval_date(self):
        from datetime import datetime, timezone

        from nestor_pulse_sdk.citations.numbering import _assign_numbers

        row = _row("c1", "s1", 0)
        row["fetched_at"] = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)
        numbered, _ = _assign_numbers([row])
        assert numbered[0]["publication_date"].startswith("2026-07-26")


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


async def test_with_claims_returns_the_identical_numbered_list(live_engine):
    """15.2 D-05: the anchor path must not fork the numbering.

    `number_citations_with_claims` and `number_citations` share
    `_CLAIM_SOURCE_SQL` + `_assign_numbers`, so the `## Sources` list and the
    body's `[n]` markers come from ONE computation. Byte equality is the proof.
    """
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.citations.numbering import (
        number_citations,
        number_citations_with_claims,
    )
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_id = uuid.uuid4()
    run_id = await _seed_run_with_citations(live_engine, tenant_id)
    try:
        Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                plain = await number_citations(session, run_id)
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                numbered, claim_to_n = await number_citations_with_claims(session, run_id)

        assert numbered == plain, "the with-claims variant must not fork the numbering"

        # The seed has 3 claims; EVERY one must be mapped -- including c2, which
        # introduces no new source (it only re-uses s0, already numbered by c0).
        assert len(claim_to_n) == 3

        # c0 is first in position order, so it takes n=1. c1 cites only the blog
        # source; c2 cites only the reuters source. s0/s1 are ordered by source
        # id inside c0, so reuters is 1 or 2 -- the point is that c2 REUSES it
        # rather than being handed a fresh number.
        n_blog = next(e["n"] for e in numbered if e["url"] == "https://some-blog.example/c")
        n_reuters = next(e["n"] for e in numbered if e["url"] == "https://www.reuters.com/a")
        assert n_blog == 3
        assert n_reuters in (1, 2)
        assert sorted(claim_to_n.values()) == sorted([1, n_blog, n_reuters])
    finally:
        await _drop_org(live_engine, tenant_id)


async def test_list_run_claims_is_in_position_order(live_engine):
    """The ledger order and the numbering order are the SAME ordering key."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from nestor_pulse_sdk.citations.numbering import list_run_claims
    from nestor_pulse_sdk.db.rls import set_tenant_context

    tenant_id = uuid.uuid4()
    run_id = await _seed_run_with_citations(live_engine, tenant_id)
    try:
        Session = async_sessionmaker(live_engine, class_=AsyncSession, expire_on_commit=False)
        async with Session() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                claims = await list_run_claims(session, run_id)

        assert [c["position"] for c in claims] == [0, 1, 2]
        assert [c["text"] for c in claims] == ["claim 0", "claim 1", "claim 2"]
        assert set(claims[0]) == {"claim_id", "text", "facet", "position"}
    finally:
        await _drop_org(live_engine, tenant_id)
