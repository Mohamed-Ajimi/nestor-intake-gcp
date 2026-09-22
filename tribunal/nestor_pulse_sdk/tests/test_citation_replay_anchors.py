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

import pytest

from nestor_pulse_sdk.citations.numbering import (
    _CLAIM_SOURCE_SQL,
    _assign_numbers,
    _claim_source_sql,
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
