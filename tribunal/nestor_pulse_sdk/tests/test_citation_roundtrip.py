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

PHASE 15.2 PLAN 15 (D-13) ADDS TWO LAYERS
-----------------------------------------
The three tests above all need Docker. The D-13 WRITE CONTRACT must also be
provable WITHOUT it, because "the columns are written, correctly bounded, in the
right order, under a tenant context" is a claim about the code — not about
Postgres — and a claim that can only be checked when Docker happens to be up is
a claim that silently goes unchecked. So:

  * Layer 1 (`TestD13WriteContract`) — PURE. A hand-written duck-typed
    `_RecordingSession` records every `(sql, params)` pair `persist_tribunal_claims`
    issues and the assertions read that transcript. No Docker, no network, no
    mocking library (the house rule: `test_gate_replay.py:19-23`). These tests
    MUST NOT skip.
  * Layer 2 (`test_d13_columns_round_trip`,
    `test_provider_stated_quality_beats_the_domain_heuristic`) — the same contract
    against the REAL schema, in the shape of the three tests above, skipping
    cleanly when Docker is unreachable.

Nothing here touches a provider, so nothing here carries `@pytest.mark.live`.
"""
from __future__ import annotations

import uuid

import pytest  # noqa: F401  (kept for future markers; fixtures use it)


# ===========================================================================
# LAYER 1 (PURE) — the D-13 write contract, provable without Docker.
# ===========================================================================
class _RecordingResult:
    """The minimum `session.execute` return `persist_tribunal_claims` touches.

    `_upsert_source` calls `.first()` on the INSERT ... RETURNING result and
    treats `None` as "conflict — look the existing row up". Returning None here
    therefore drives the upsert down its LOOKUP branch, which also returns None,
    which raises. So `_RecordingSession` answers the lookup with a row instead
    (see its `execute`); this class carries whichever answer it was given.
    """

    def __init__(self, row=None) -> None:
        self._row = row

    def first(self):
        return self._row


class _ExistingSourceRow:
    """A stand-in for the `SELECT id FROM source ...` row. Hand-written."""

    def __init__(self, source_id) -> None:
        self.id = source_id


class _RecordingSession:
    """Duck-typed AsyncSession that RECORDS SQL instead of executing it.

    NO MOCKING LIBRARY — the house rule (`test_gate_replay.py:19-23`): fakes in
    this repo are hand-written and duck-typed, so what a test asserts against is
    readable in the test file rather than assembled by a framework.

    `calls` is the transcript: `(sql_text, params)` in issue order. That order is
    itself a contract — `set_config('app.tenant_id'` MUST be recorded before any
    INSERT, or the RLS `WITH CHECK` policy would reject every write.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, clause, params=None):
        sql = str(clause)
        self.calls.append((sql, params or {}))
        if sql.startswith("SELECT id FROM source"):
            # The upsert's post-conflict lookup. Answering it keeps the source
            # path on a realistic branch instead of raising RuntimeError.
            return _RecordingResult(_ExistingSourceRow(uuid.uuid4()))
        return _RecordingResult(None)

    # --- helpers the assertions read the transcript through ----------------
    def matching(self, needle: str) -> list[tuple[str, dict]]:
        return [(sql, params) for sql, params in self.calls if needle in sql]

    def index_of(self, needle: str) -> int:
        for i, (sql, _params) in enumerate(self.calls):
            if needle in sql:
                return i
        return -1


def _d8_claim(**overrides) -> dict:
    """One claim in the shape the merge stage hands to persistence."""
    claim = {
        "text": "Aral heeft een marktaandeel van 16% in Duitsland",
        "facet": "market",
        "found_by": ["gemini", "openai"],
        "source_urls": ["https://bundeskartellamt.de/a", "https://reuters.com/b"],
        "certainty": "certain",
        "provider_quality": "press",
        "provider_quality_by_url": {"https://bundeskartellamt.de/a": "official"},
        "source_domain": "bundeskartellamt.de",
    }
    claim.update(overrides)
    return claim


class TestD13WriteContract:
    """D-13's five persisted values, asserted on the SQL actually issued.

    Every test here is PURE and MUST NOT SKIP: no Docker, no network, no
    provider key. If one of these is reported as skipped, the gate is lying.
    """

    @staticmethod
    async def _persist(session, *, claims=None, research_gaps=None):
        from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

        return await persist_tribunal_claims(
            claims=claims if claims is not None else [_d8_claim()],
            verdicts_by_claim={},
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            session=session,
            research_gaps=research_gaps,
        )

    async def test_tenant_context_is_set_before_any_insert(self):
        """T-15.2-51. The RLS `WITH CHECK` policy is the control, so the GUC
        must be bound first or every write this function makes is rejected."""
        session = _RecordingSession()
        await self._persist(
            session, research_gaps=[{"provider": "gemini", "text": "geen cijfer"}]
        )

        guc = session.index_of("set_config('app.tenant_id'")
        assert guc == 0, "the tenant GUC must be the very first statement"
        first_insert = next(
            i for i, (sql, _p) in enumerate(session.calls) if "INSERT INTO" in sql
        )
        assert guc < first_insert
        assert len(session.matching("set_config('app.tenant_id'")) == 1, \
            "exactly ONE tenant setup — a second one is a second chance to get it wrong"

    async def test_claim_insert_carries_certainty_and_found_by(self):
        session = _RecordingSession()
        await self._persist(session)

        inserts = session.matching("INSERT INTO claim ")
        assert len(inserts) == 1
        sql, params = inserts[0]
        assert "certainty" in sql and "found_by" in sql
        assert params["certainty"] in ("certain", "single")
        assert params["found_by"] == ["gemini", "openai"], \
            "found_by is bound as a LIST (a Postgres text[]), not a joined string"

    async def test_absent_provenance_binds_null_not_an_empty_array(self):
        """`cardinality(found_by)` is 0 on `[]` and NULL on NULL. "No provenance
        recorded" and "found by nobody" are different facts."""
        session = _RecordingSession()
        await self._persist(session, claims=[_d8_claim(found_by=[])])

        _sql, params = session.matching("INSERT INTO claim ")[0]
        assert params["found_by"] is None

    async def test_unrecognised_certainty_and_quality_bind_null(self):
        """ASVS V5 enum clamping at the LAST point before the database."""
        session = _RecordingSession()
        await self._persist(
            session,
            claims=[_d8_claim(
                certainty="maybe",
                provider_quality="whatever",
                provider_quality_by_url={},
            )],
        )

        _sql, claim_params = session.matching("INSERT INTO claim ")[0]
        assert claim_params["certainty"] is None

        for _sql, link_params in session.matching("INSERT INTO claim_source"):
            assert link_params["quality"] is None

    async def test_quality_word_is_case_normalised(self):
        session = _RecordingSession()
        await self._persist(
            session,
            claims=[_d8_claim(provider_quality="PRESS", provider_quality_by_url={})],
        )
        links = session.matching("INSERT INTO claim_source")
        assert links, "the claim cites two urls, so it must produce link rows"
        assert all(p["quality"] == "press" for _s, p in links)

    async def test_claim_source_is_graded_per_url_from_the_map_then_the_scalar(self):
        """The per-url map is what `_dedupe_claims` builds when two streams'
        versions of one fact merge; the scalar is the un-merged case."""
        session = _RecordingSession()
        await self._persist(session)

        link_qualities = [
            p["quality"] for _s, p in session.matching("INSERT INTO claim_source")
        ]
        assert len(link_qualities) == 2
        # URL order is the claim's `source_urls` order, preserved by the
        # `deduped_urls` pass: bundeskartellamt (in the map -> 'official') then
        # reuters (NOT in the map -> falls back to the scalar 'press'). That is
        # the whole point of the map: a url is graded by the provider that
        # supplied it, not by whichever provider's scalar happened to survive.
        assert link_qualities == ["official", "press"], link_qualities

    async def test_source_insert_carries_the_provider_supplied_title(self):
        """`source_domain` is the provider's OWN link label, not an invention —
        and it is what stops every Gemini source being labelled
        `vertexaisearch.cloud.google.com`."""
        session = _RecordingSession()
        await self._persist(session)

        inserts = session.matching("INSERT INTO source ")
        assert inserts
        assert all("title" in sql for sql, _p in inserts)
        assert all(p["title"] == "bundeskartellamt.de" for _s, p in inserts)

    async def test_research_gaps_are_written_one_row_each(self):
        session = _RecordingSession()
        result = await self._persist(
            session,
            research_gaps=[
                {"provider": "gemini", "text": "geen omzetcijfer voor 2025"},
                {"provider": "openai", "text": "geen stationstelling"},
            ],
        )
        gaps = session.matching("INSERT INTO research_gap")
        assert len(gaps) == 2
        assert result["research_gap_count"] == 2
        providers = sorted(p["provider"] for _s, p in gaps)
        assert providers == ["gemini", "openai"]

    async def test_research_gap_caps_are_applied_and_are_loud(self):
        """250 in -> 200 out; a 5,000-char line stored at 2,000; a duplicate
        (provider, text) pair collapsed to one row."""
        from nestor_pulse_sdk.citations.extractor import (
            _MAX_RESEARCH_GAPS, _RESEARCH_GAP_MAX_CHARS,
        )

        session = _RecordingSession()
        gaps = [{"provider": "gemini", "text": f"gap {i}"} for i in range(250)]
        await self._persist(session, research_gaps=gaps)
        assert len(session.matching("INSERT INTO research_gap")) == _MAX_RESEARCH_GAPS

        session = _RecordingSession()
        await self._persist(
            session,
            research_gaps=[{"provider": "gemini", "text": "x" * 5000}],
        )
        _sql, params = session.matching("INSERT INTO research_gap")[0]
        assert len(params["text"]) == _RESEARCH_GAP_MAX_CHARS

        session = _RecordingSession()
        await self._persist(
            session,
            research_gaps=[
                {"provider": "gemini", "text": "same gap"},
                {"provider": "gemini", "text": "same gap"},
            ],
        )
        assert len(session.matching("INSERT INTO research_gap")) == 1

    async def test_blank_or_unattributed_gaps_write_no_row(self):
        session = _RecordingSession()
        result = await self._persist(
            session,
            research_gaps=[
                {"provider": "", "text": "who said this?"},
                {"provider": "gemini", "text": "   "},
                "not a dict",
            ],
        )
        assert session.matching("INSERT INTO research_gap") == []
        assert result["research_gap_count"] == 0

    async def test_no_gaps_writes_no_rows_and_the_old_return_keys_survive(self):
        """A healthy run establishes what it looked for and writes nothing."""
        session = _RecordingSession()
        result = await self._persist(session, research_gaps=None)
        assert session.matching("INSERT INTO research_gap") == []
        assert result["research_gap_count"] == 0
        for key in ("claim_ids", "source_ids", "verdict_ids", "verdict_count"):
            assert key in result, f"pre-existing return key {key} disappeared"

    async def test_a_distiller_claim_writes_nulls_not_defaults(self):
        """D-14: a claim from the fallback distiller states no certainty and no
        quality, and the persistence layer must not invent either."""
        session = _RecordingSession()
        await self._persist(
            session,
            claims=[{
                "text": "Een gedistilleerde bewering",
                "facet": "market",
                "found_by": ["claude"],
                "certainty": None,
                "provider_quality": None,
                "source_domain": None,
                "source_urls": ["https://example.com/x"],
            }],
        )
        _sql, claim_params = session.matching("INSERT INTO claim ")[0]
        assert claim_params["certainty"] is None
        _sql, src_params = session.matching("INSERT INTO source ")[0]
        assert src_params["title"] is None
        _sql, link_params = session.matching("INSERT INTO claim_source")[0]
        assert link_params["quality"] is None


# ===========================================================================
# LAYER 2 (DB-backed) — the same contract against the real schema.
# ===========================================================================
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


async def _seed_run(session, set_tenant, tenant_id):
    """A project + run under `tenant_id`, returning the run id."""
    from nestor_pulse_sdk.db.models import Project, Run

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
    return run.id


async def test_d13_columns_round_trip(async_engine, set_tenant):
    """certainty / found_by / provider_quality / title / research_gap, for real.

    D-13's promise is that "why was this fact prioritised" is answerable AFTER
    the run, from the database, in August. That is only true if these five values
    survive the real schema — the array type, the RLS `WITH CHECK` policy and the
    NOT NULL columns included — so this test drives the PRODUCTION writer against
    the real tables rather than asserting on SQL strings.
    """
    from sqlalchemy import text
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    tenant_id = uuid.uuid4()
    Session = await _bootstrap_schema(async_engine, tenant_id)

    async with Session() as session:
        async with session.begin():
            run_id = await _seed_run(session, set_tenant, tenant_id)

        async with session.begin():
            await set_tenant(session, tenant_id)
            result = await persist_tribunal_claims(
                claims=[_d8_claim()],
                verdicts_by_claim={},
                run_id=run_id,
                tenant_id=tenant_id,
                session=session,
                research_gaps=[{"provider": "gemini", "text": "geen omzetcijfer 2025"}],
            )
        assert result["research_gap_count"] == 1

        async with session.begin():
            await set_tenant(session, tenant_id)
            claim_row = (await session.execute(
                text("SELECT certainty, found_by FROM claim WHERE run_id = :r"),
                {"r": str(run_id)},
            )).first()
            quality_rows = (await session.execute(
                text(
                    "SELECT s.title AS title, cs.provider_quality AS q "
                    "FROM claim c "
                    "JOIN claim_source cs ON cs.claim_id = c.id "
                    "JOIN source s ON s.id = cs.source_id "
                    "WHERE c.run_id = :r ORDER BY cs.provider_quality ASC"
                ),
                {"r": str(run_id)},
            )).all()
            gap_row = (await session.execute(
                text(
                    "SELECT provider, text, run_id FROM research_gap "
                    "WHERE run_id = :r"
                ),
                {"r": str(run_id)},
            )).first()

    assert claim_row is not None
    assert claim_row.certainty == "certain"
    assert list(claim_row.found_by) == ["gemini", "openai"], \
        "found_by must come back as a Python list, not a string"

    assert len(quality_rows) == 2
    assert sorted(r.q for r in quality_rows) == ["official", "press"]
    assert all(r.title == "bundeskartellamt.de" for r in quality_rows), \
        "the provider's own display label reached source.title"

    assert gap_row is not None
    assert gap_row.provider == "gemini"
    assert gap_row.text == "geen omzetcijfer 2025"
    assert str(gap_row.run_id) == str(run_id), \
        "15.2-06 reads these rows back by run_id — a wrong run_id is an invisible row"


async def test_provider_stated_quality_beats_the_domain_heuristic(
    async_engine, set_tenant
):
    """D-13: two sources of truth for the tier, provider-stated wins.

    `derive_quality_tier` grades a bare `.com` host tier 3 because a hostname is
    all it has. The provider that cited the page read it and said `official`. The
    same source, with the provider silent, must fall straight back to the
    heuristic's 3 — the heuristic is not removed, it is DEMOTED.
    """
    from sqlalchemy import text
    from nestor_pulse_sdk.citations.numbering import number_citations, derive_quality_tier
    from nestor_pulse_sdk.db.models import Claim, ClaimSource, Source

    url = "https://acme-industries.com/investors/annual-report"
    assert derive_quality_tier("gemini", url) == 3, \
        "fixture guard: this url must be tier 3 by the heuristic or the test proves nothing"

    tenant_id = uuid.uuid4()
    Session = await _bootstrap_schema(async_engine, tenant_id)

    async with Session() as session:
        async with session.begin():
            run_id = await _seed_run(session, set_tenant, tenant_id)
            source = Source(
                tenant_id=tenant_id,
                url=url,
                provider="gemini",
                snapshot_text="annual report",
                content_hash="h-official",
            )
            session.add(source)
            await session.flush()
            claim = Claim(
                tenant_id=tenant_id, run_id=run_id, text="Acme's revenue was X",
                facet="market", position=0,
            )
            session.add(claim)
            await session.flush()
            session.add(ClaimSource(
                tenant_id=tenant_id, claim_id=claim.id, source_id=source.id,
                provider_quality="official",
            ))
            claim_id = claim.id

        async with session.begin():
            await set_tenant(session, tenant_id)
            stated = await number_citations(session, run_id)

        # Now silence the provider on the SAME row and re-number.
        async with session.begin():
            await set_tenant(session, tenant_id)
            await session.execute(
                text(
                    "UPDATE claim_source SET provider_quality = NULL "
                    "WHERE claim_id = :cid"
                ),
                {"cid": str(claim_id)},
            )

        async with session.begin():
            await set_tenant(session, tenant_id)
            silent = await number_citations(session, run_id)

    assert len(stated) == 1 and len(silent) == 1
    assert stated[0]["quality_tier"] == 1, \
        "the provider said 'official' — provider-stated wins over the domain heuristic"
    assert silent[0]["quality_tier"] == 3, \
        "with the provider silent the heuristic decides, unchanged"
    # The rest of the entry is untouched: only the VALUE of quality_tier moved.
    assert stated[0]["n"] == silent[0]["n"] == 1
    assert stated[0]["url"] == silent[0]["url"] == url
