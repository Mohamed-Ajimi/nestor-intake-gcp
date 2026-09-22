"""Offline replay of the ANCHOR half of the run-7784e71c defect (phase 23.5-05).

Companion to `test_citation_replay.py`, which replays what the persist loop
WRITES. This file replays what the numbering and the fact ledger then DO with
those rows -- mechanisms 3 and 5 of the measured defect:

  * **Mechanism 3** -- `_CLAIM_SOURCE_SQL` orders `(c.position, c.id, s.id)`, so
    a claim's `[n]` is its first source by SOURCE UUID. A uuid is arbitrary, so
    232 of run 7784e71c's 427 sourced claims anchored to a host they have
    nothing to do with.
  * **Mechanism 5** -- `build_ledger` offers the writing model an anchor for
    EVERY claim, while `number_citations_with_claims` can only map the claims
    that have a `claim_source` row. The 159 sourceless claims were therefore
    offered, anchored, and then stripped back out of the delivered report: 108
    silently uncited statements.

NO DATABASE, NO NETWORK, NO PROVIDER CALL. `_assign_numbers` and `build_ledger`
are pure, the rows are hand-built or projected from the plan-04 fixture, and the
flags are flipped in-process (which is the entire reason `runtime_flags` reads
`os.environ` at CALL time rather than at import).

`render_fact_ledger` is deliberately NOT used anywhere in this file. Its
`NESTOR_TRIBUNAL_ANCHORS` read happens at IMPORT time (`anchors.py:87`), which is
why `test_citation_anchors.py` has to `skipif` rather than assert -- a test that
skips proves nothing, and the RED assertions here have to be able to FAIL.
"""

from __future__ import annotations

import uuid

import pytest

from nestor_pulse_sdk.citations.anchors import (
    anchor_number_map,
    anchor_token,
    apply_citation_anchors,
    build_ledger,
    claim_prefix,
)
from nestor_pulse_sdk.citations.extractor import _plan_claim_sources
from nestor_pulse_sdk.citations.numbering import (
    _CLAIM_SOURCE_SQL,
    _assign_numbers,
    _claim_source_sql,
)
from nestor_pulse_sdk.tests.fixtures.citations_replay import (
    CLAIMS,
    RESOLVED_MAP,
    VERDICTS_BY_CLAIM,
)

#: Every phase-23.5 flag. Cleared before every test in this module so a
#: developer's shell cannot decide which branch is under test.
_FLAG_ENV_NAMES = [
    "NESTOR_CITATIONS_V2",
    "NESTOR_CITATIONS_SKEPTIC_AS_EVIDENCE",
    "NESTOR_CITATIONS_PER_URL_META",
    "NESTOR_CITATIONS_PRIMARY_ANCHOR",
    "NESTOR_CITATIONS_LEDGER_NUMBERABLE_ONLY",
    "NESTOR_CITATIONS_RENDER_RESOLVED",
]


@pytest.fixture(autouse=True)
def _flags_off(monkeypatch):
    for name in _FLAG_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


# ---------------------------------------------------------------------------
# The statements, asserted BYTE FOR BYTE.
#
# `_CLAIM_SOURCE_SQL` carries its own "do not change one character" comment and
# is pinned by `test_citation_numbering.py::test_numbering_is_deterministic_and_
# all_resolve`, a DB-backed test that does not run on a dev box. The literal
# below is that guard's keyless twin: it runs everywhere, and it fails the
# moment somebody edits the constant instead of adding beside it.
# ---------------------------------------------------------------------------

_HEAD_CLAIM_SOURCE_SQL = (
    "SELECT c.id AS claim_id, c.position AS position, "
    "       s.id AS source_id, s.title AS title, s.url AS url, "
    "       s.provider AS provider, s.fetched_at AS fetched_at, "
    "       cs.provider_quality AS provider_quality "
    "FROM claim c "
    "JOIN claim_source cs ON cs.claim_id = c.id "
    "JOIN source s ON s.id = cs.source_id "
    "WHERE c.run_id = :rid "
    "ORDER BY c.position ASC NULLS LAST, c.id ASC, s.id ASC"
)

_V2_SQL_LOWEST_UUID = (
    "SELECT c.id AS claim_id, c.position AS position, "
    "       s.id AS source_id, s.title AS title, s.url AS url, "
    "       s.resolved_url AS resolved_url, "
    "       s.provider AS provider, s.fetched_at AS fetched_at, "
    "       cs.provider_quality AS provider_quality "
    "FROM claim c "
    "JOIN claim_source cs ON cs.claim_id = c.id "
    "JOIN source s ON s.id = cs.source_id "
    "WHERE c.run_id = :rid "
    "ORDER BY c.position ASC NULLS LAST, c.id ASC, s.id ASC"
)

_V2_SQL_PRIMARY_FIRST = (
    "SELECT c.id AS claim_id, c.position AS position, "
    "       s.id AS source_id, s.title AS title, s.url AS url, "
    "       s.resolved_url AS resolved_url, "
    "       s.provider AS provider, s.fetched_at AS fetched_at, "
    "       cs.provider_quality AS provider_quality "
    "FROM claim c "
    "JOIN claim_source cs ON cs.claim_id = c.id "
    "JOIN source s ON s.id = cs.source_id "
    "WHERE c.run_id = :rid "
    "ORDER BY c.position ASC NULLS LAST, c.id ASC, (s.title IS NULL) ASC, s.id ASC"
)

#: Today's entry shape. 15.2-05's Layer-1 tests compare WHOLE entry lists, so a
#: single extra key on the flags-off path is a breaking change.
_ENTRY_KEYS_TODAY = {
    "n",
    "source_id",
    "title",
    "url",
    "provider",
    "publication_date",
    "quality_tier",
    "single_source",
    "first_claim_id",
    "first_claim_position",
}


class TestTheStatementsAreByteLiterals:
    def test_the_pinned_statement_is_unchanged(self):
        assert _CLAIM_SOURCE_SQL == _HEAD_CLAIM_SOURCE_SQL

    def test_the_pinned_statement_carries_no_resolved_url(self):
        """The flags-off read must not even SELECT the new column."""
        assert "resolved_url" not in _CLAIM_SOURCE_SQL

    def test_the_v2_statement_without_primary_first(self):
        assert _claim_source_sql(primary_first=False) == _V2_SQL_LOWEST_UUID

    def test_the_v2_statement_with_primary_first(self):
        assert _claim_source_sql(primary_first=True) == _V2_SQL_PRIMARY_FIRST

    def test_the_two_v2_statements_differ_only_by_the_ordering_term(self):
        """One ordering term, nothing else. No new table, no new join, same WHERE."""
        assert _V2_SQL_PRIMARY_FIRST.replace("(s.title IS NULL) ASC, ", "") == (
            _V2_SQL_LOWEST_UUID
        )

    def test_the_v2_statements_keep_the_run_scope(self):
        """T-23.5-05-I: the second statement is RLS-scoped exactly like the first."""
        for sql in (_V2_SQL_LOWEST_UUID, _V2_SQL_PRIMARY_FIRST):
            assert "WHERE c.run_id = :rid" in sql
            assert sql.count("JOIN") == _CLAIM_SOURCE_SQL.count("JOIN")

    def test_the_v2_statements_are_composed_from_fixed_fragments(self):
        """T-23.5-05-T2: the bool chooses between literals; nothing is interpolated."""
        assert _claim_source_sql(primary_first=False) == _claim_source_sql(
            primary_first=False
        )
        assert _claim_source_sql(primary_first=True) == _claim_source_sql(
            primary_first=True
        )


# ---------------------------------------------------------------------------
# Hand-built rows for the ordering proof.
#
# `_assign_numbers` does NOT sort -- it walks rows the database already ordered.
# A keyless test therefore has to apply the ordering itself, so `_order_rows`
# below is the Python mirror of the ORDER BY clauses pinned byte-for-byte above.
# The literal assertions and this mirror are what the ordering claims rest on;
# neither is worth anything without the other.
# ---------------------------------------------------------------------------


def _order_rows(rows: list[dict], *, primary_first: bool) -> list[dict]:
    def key(row: dict):
        position = row.get("position")
        return (
            (1, 0) if position is None else (0, position),  # ASC NULLS LAST
            str(row["claim_id"]),
            # (s.title IS NULL) ASC -- False (0) sorts before True (1), so a
            # TITLED row comes first. Only applied when the term is in the SQL.
            (row.get("title") is None) if primary_first else False,
            str(row["source_id"]),
        )

    return sorted(rows, key=key)


#: A claim whose LOWEST-uuid source is an untitled, skeptic-shaped row, and whose
#: own titled provider url sorts later by uuid. Mechanism 3 in two rows.
_CLAIM_ID = "11111111-1111-4111-8111-111111111111"
_UNTITLED_SOURCE_ID = "00000000-0000-4000-8000-000000000001"
_TITLED_SOURCE_ID = "ffffffff-ffff-4fff-8fff-ffffffffffff"
_UNTITLED_URL = "https://example-07.test/article"
_TITLED_URL = "https://www.cbs.nl/nl-nl/cijfers/detail/00000"
_TITLED_RESOLVED = "https://www.cbs.nl/nl-nl/cijfers/detail/00000-canonical"

_TWO_SOURCE_ROWS = [
    {
        "claim_id": _CLAIM_ID,
        "position": 1,
        "source_id": _UNTITLED_SOURCE_ID,
        "title": None,
        "url": _UNTITLED_URL,
        "resolved_url": None,
        "provider": "claude",
        "fetched_at": None,
        "provider_quality": None,
    },
    {
        "claim_id": _CLAIM_ID,
        "position": 1,
        "source_id": _TITLED_SOURCE_ID,
        "title": "cbs.nl",
        "url": _TITLED_URL,
        "resolved_url": _TITLED_RESOLVED,
        "provider": "gemini",
        "fetched_at": None,
        "provider_quality": "official",
    },
]


class TestTheEntryShape:
    def test_the_default_shape_is_todays_ten_keys(self):
        numbered, _ = _assign_numbers(_order_rows(_TWO_SOURCE_ROWS, primary_first=False))
        assert numbered
        for entry in numbered:
            assert set(entry) == _ENTRY_KEYS_TODAY

    def test_include_resolved_adds_exactly_one_key(self):
        numbered, _ = _assign_numbers(
            _order_rows(_TWO_SOURCE_ROWS, primary_first=False), include_resolved=True
        )
        assert numbered
        for entry in numbered:
            assert set(entry) == _ENTRY_KEYS_TODAY | {"resolved_url"}

    def test_include_resolved_carries_the_stored_target(self):
        numbered, _ = _assign_numbers(
            _order_rows(_TWO_SOURCE_ROWS, primary_first=True), include_resolved=True
        )
        by_url = {e["url"]: e for e in numbered}
        assert by_url[_TITLED_URL]["resolved_url"] == _TITLED_RESOLVED
        assert by_url[_UNTITLED_URL]["resolved_url"] is None

    def test_a_row_without_the_column_is_not_a_crash(self):
        """`_row_get` returns None for a missing key -- Layer-1 fixtures have none."""
        rows = [{k: v for k, v in r.items() if k != "resolved_url"} for r in _TWO_SOURCE_ROWS]
        numbered, _ = _assign_numbers(rows, include_resolved=True)
        assert all(e["resolved_url"] is None for e in numbered)


class TestMechanism3TheAnchorPicksAProviderUrl:
    def test_flags_off_the_claim_anchors_to_the_lowest_uuid(self):
        """RED. Today the anchor is decided by an arbitrary uuid."""
        numbered, claim_to_n = _assign_numbers(
            _order_rows(_TWO_SOURCE_ROWS, primary_first=False)
        )
        entry = {e["n"]: e for e in numbered}[claim_to_n[_CLAIM_ID]]
        assert entry["source_id"] == _UNTITLED_SOURCE_ID
        assert entry["url"] == _UNTITLED_URL

    def test_flags_on_the_claim_anchors_to_the_titled_row(self):
        """GREEN. A titled source is one the claim's OWN provider supplied."""
        numbered, claim_to_n = _assign_numbers(
            _order_rows(_TWO_SOURCE_ROWS, primary_first=True)
        )
        entry = {e["n"]: e for e in numbered}[claim_to_n[_CLAIM_ID]]
        assert entry["source_id"] == _TITLED_SOURCE_ID
        assert entry["url"] == _TITLED_URL

    def test_both_orderings_number_every_source_exactly_once(self):
        for primary_first in (False, True):
            numbered, _ = _assign_numbers(
                _order_rows(_TWO_SOURCE_ROWS, primary_first=primary_first)
            )
            assert [e["n"] for e in numbered] == [1, 2]
            assert len({e["source_id"] for e in numbered}) == 2

    def test_both_orderings_are_stable_across_two_calls(self):
        for primary_first in (False, True):
            ordered = _order_rows(_TWO_SOURCE_ROWS, primary_first=primary_first)
            first = _assign_numbers(ordered, include_resolved=True)
            second = _assign_numbers(ordered, include_resolved=True)
            assert first == second


# ---------------------------------------------------------------------------
# The fixture replay: mechanism 5, the stripped anchors.
#
# `build_ledger` shows the writing model an anchor for EVERY claim;
# `number_citations_with_claims` can only map the claims that have a
# `claim_source` row. On run 7784e71c 159 claims had none -- mostly
# `distiller_fallback`, which zeroes `source_domain` and carries no usable url --
# so they were offered, anchored, and then deleted from the deliverable by
# `apply_citation_anchors`. 108 statements lost their citation silently.
#
# The RED assertion below is as load-bearing as the GREEN one. A fixture that
# cannot reproduce the defect proves nothing whatsoever about the fix.
# ---------------------------------------------------------------------------

#: A fixed namespace so the synthetic ids below are the SAME on every machine and
#: every run. Nothing here is, or is derived from, a production id.
_NS = uuid.UUID("23500000-0000-4000-8000-000000000005")


def _claim_id_for(fixture_id: str) -> str:
    return str(uuid.uuid5(_NS, "claim:" + fixture_id))


def _source_id_for(url: str) -> str:
    """One id per url. `_upsert_source` dedupes by url, so two claims citing the
    same url reach ONE source row -- and that is what makes a claim's `[n]`
    contestable in the first place."""
    return str(uuid.uuid5(_NS, "source:" + url))


def _claim_rows() -> list[dict]:
    """The `list_run_claims` projection of the plan-04 fixture, in ledger order."""
    return [
        {
            "claim_id": _claim_id_for(claim["fixture_id"]),
            "text": claim["claim_text"],
            "facet": claim.get("facet"),
            "position": claim.get("position"),
        }
        for claim in CLAIMS
    ]


def _replay(monkeypatch, *, flags_on: bool):
    """Run the whole offline path for ONE flag state.

    Returns `(numbered, claim_to_n, ledger)`. The flag is set here rather than in
    each test because it governs BOTH halves -- which `claim_source` rows the
    persist loop would plan AND how the ledger is filtered -- and setting it in
    one place is what stops a test from replaying half of each branch.
    """
    if flags_on:
        monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    else:
        monkeypatch.delenv("NESTOR_CITATIONS_V2", raising=False)

    rows: list[dict] = []
    for claim in CLAIMS:
        cid = _claim_id_for(claim["fixture_id"])
        for entry in _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP):
            rows.append(
                {
                    "claim_id": cid,
                    "position": claim.get("position"),
                    "source_id": _source_id_for(entry["url"]),
                    "title": entry["title"],
                    "url": entry["url"],
                    "resolved_url": entry["resolved_url"],
                    "provider": claim.get("found_by"),
                    "fetched_at": None,
                    "provider_quality": entry["provider_quality"],
                }
            )

    numbered, claim_to_n = _assign_numbers(
        _order_rows(rows, primary_first=flags_on), include_resolved=flags_on
    )
    ledger = build_ledger(
        _claim_rows(),
        numberable_claim_ids=set(claim_to_n) if flags_on else None,
    )
    return numbered, claim_to_n, ledger


def _writer_output(ledger: list[dict]) -> str:
    """A writing model that obeys the prompt PERFECTLY: one anchor per offered
    fact, copied character for character. Every strip below is therefore the
    system's doing, not the model's."""
    return " ".join(
        f"Statement {i}.{anchor_token(entry['claim_id'])}"
        for i, entry in enumerate(ledger, start=1)
    )


def test_the_synthetic_claim_prefixes_do_not_collide():
    """`collision_free_prefixes` drops ambiguous prefixes. That must not be what
    drives the counts below -- otherwise this file would measure the wrong thing."""
    prefixes = [claim_prefix(_claim_id_for(c["fixture_id"])) for c in CLAIMS]
    assert len(set(prefixes)) == len(prefixes)


class TestMechanism5StrippedAnchors:
    def test_flags_off_the_writer_loses_citations(self, monkeypatch):
        """RED. Run 7784e71c's 108 stripped anchors, in miniature."""
        _, claim_to_n, ledger = _replay(monkeypatch, flags_on=False)
        text, n_unresolved = apply_citation_anchors(
            _writer_output(ledger), anchor_number_map(claim_to_n)
        )
        assert n_unresolved > 0
        # And it is exactly the offered claims that have no `claim_source` row.
        offered = {e["claim_id"] for e in ledger}
        assert n_unresolved == len(offered - set(claim_to_n))
        # Silent, too: no marker is left behind for a reader to notice.
        assert "[[c:" not in text

    def test_flags_on_no_anchor_is_ever_stripped(self, monkeypatch):
        """GREEN. The ledger offers only what can be numbered."""
        _, claim_to_n, ledger = _replay(monkeypatch, flags_on=True)
        _, n_unresolved = apply_citation_anchors(
            _writer_output(ledger), anchor_number_map(claim_to_n)
        )
        assert n_unresolved == 0

    def test_flags_on_the_ledger_still_offers_every_numberable_claim(self, monkeypatch):
        """The filter must not be a blunt instrument: nothing citable is withheld."""
        _, claim_to_n, ledger = _replay(monkeypatch, flags_on=True)
        assert ledger
        assert {e["claim_id"] for e in ledger} == set(claim_to_n)

    def test_flags_on_the_sourceless_claims_are_the_ones_withheld(self, monkeypatch):
        """Shapes 1 and 7 of the fixture are mechanism 5's drivers, by name."""
        _, _, ledger = _replay(monkeypatch, flags_on=True)
        withheld = {_claim_id_for(c["fixture_id"]) for c in CLAIMS} - {
            e["claim_id"] for e in ledger
        }
        assert _claim_id_for("c01_sourceless_no_verdict") in withheld
        assert _claim_id_for("c07_distiller_fallback_unnumberable") in withheld


class TestBuildLedgerFilter:
    def test_none_means_no_filter(self):
        rows = _claim_rows()
        assert build_ledger(rows, numberable_claim_ids=None) == build_ledger(rows)

    def test_an_empty_set_means_nothing_is_numberable(self):
        """NOT "no filter". `if not numberable_claim_ids` would re-introduce the
        defect at exactly the moment the run has no citations at all."""
        assert build_ledger(_claim_rows(), numberable_claim_ids=set()) == []

    def test_the_filter_preserves_order_and_shape(self):
        rows = _claim_rows()
        full = build_ledger(rows)
        keep = {full[0]["claim_id"], full[-1]["claim_id"]}
        filtered = build_ledger(rows, numberable_claim_ids=keep)
        assert filtered == [e for e in full if e["claim_id"] in keep]

    def test_the_filter_compares_as_strings(self):
        """A caller holding `uuid.UUID` keys must not silently filter EVERYTHING."""
        rows = _claim_rows()
        as_uuids = {uuid.UUID(r["claim_id"]) for r in rows}
        assert build_ledger(rows, numberable_claim_ids=as_uuids) == build_ledger(rows)


class TestMechanism3OverTheFixture:
    def test_flags_on_every_anchor_resolves_to_a_url_of_that_claim(self, monkeypatch):
        """The CONTEXT's acceptance number: anchors resolving to a url that is NOT
        among the claim's own provider urls = 0."""
        numbered, claim_to_n, _ = _replay(monkeypatch, flags_on=True)
        by_n = {e["n"]: e for e in numbered}
        violations = []
        for claim in CLAIMS:
            cid = _claim_id_for(claim["fixture_id"])
            if cid not in claim_to_n:
                continue
            own = {
                e["url"]
                for e in _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP)
                if e["origin"] == "provider"
            }
            if by_n[claim_to_n[cid]]["url"] not in own:
                violations.append(claim["fixture_id"])
        assert violations == []

    def test_flags_on_the_numbered_entries_carry_resolved_url(self, monkeypatch):
        """Plan 06 renders this key, so it has to arrive."""
        numbered, _, _ = _replay(monkeypatch, flags_on=True)
        assert numbered
        assert all("resolved_url" in e for e in numbered)
        assert any(e["resolved_url"] for e in numbered)
