"""Offline replay of the persist loop's source decisions (phase 23.5-04).

WHAT THIS FILE IS FOR. `persist_tribunal_claims` decides, per claim, which urls
become `source` + `claim_source` rows and what title and provider grade each one
carries. Those decisions caused the run-7784e71c defect, and they used to be
inline in a loop that cannot run without a database. Task 2 lifted them into
`_plan_claim_sources`, a pure function, so they can be replayed here with NO
database, NO network and NO provider call -- on a bare dev box, in milliseconds.

THE GOLDEN. `fixtures/citations_replay/golden_flags_off.json` was generated from
`extractor.py` at commit bfa3aeb3, BEFORE the refactor, and committed on its own
in an earlier commit than the one that touched `extractor.py`. It is the only
thing standing between "the refactor changed nothing" as a claim and as a fact.
It records the five fields the loop has always decided; `origin` is new
information and is deliberately NOT part of it.

The comparison below is equality on WHOLE LISTS -- not a length, not a
membership check. Order is load-bearing: the first-seen dedupe and the citation
numbering both depend on it.
"""

import json
import pathlib

import pytest

from nestor_pulse_sdk.citations.extractor import (
    _gather_source_urls,
    _plan_claim_sources,
)
from nestor_pulse_sdk.tests.fixtures.citations_replay import (
    CLAIMS,
    RESOLVED_MAP,
    VERDICTS_BY_CLAIM,
)

GOLDEN_PATH = (
    pathlib.Path(__file__).parent / "fixtures" / "citations_replay" / "golden_flags_off.json"
)

#: The five fields the persist loop has always decided, and therefore the only
#: five the golden can speak for.
GOLDEN_FIELDS = ("url", "title", "provider_quality", "resolved_url", "resolution_status")

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

#: FIXTURE COUNT, not a production count. 12 synthetic claims plan 55
#: `claim_source` entries with the master off. The production run planned 4,999
#: for 586 claims; the collapse of the production 2,681 numbered sources is
#: measured on the dev run in plan 07, never here.
FLAGS_OFF_TOTAL_ENTRIES = 55


@pytest.fixture(autouse=True)
def _flags_off(monkeypatch):
    for name in _FLAG_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="module")
def golden():
    with GOLDEN_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def _project(entries):
    """A planned entry seen through the golden's five fields."""
    return [{k: e[k] for k in GOLDEN_FIELDS} for e in entries]


def test_golden_covers_every_fixture_claim(golden):
    """A claim added to the fixture without regenerating the golden fails HERE.

    Otherwise a new shape would be silently unpinned and the per-claim tests
    below would just skip it.
    """
    assert sorted(golden) == sorted(c["fixture_id"] for c in CLAIMS)


@pytest.mark.parametrize("index", range(len(CLAIMS)), ids=[c["fixture_id"] for c in CLAIMS])
def test_flags_off_equals_the_golden(golden, index):
    """With the master off, the refactor decides exactly what HEAD decided."""
    claim = CLAIMS[index]
    planned = _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP)
    assert _project(planned) == golden[claim["fixture_id"]]


@pytest.mark.parametrize("index", range(len(CLAIMS)), ids=[c["fixture_id"] for c in CLAIMS])
def test_url_projection_equals_gather_source_urls(index):
    """The pre-pass and the persist loop cannot drift, because they are one call.

    `_gather_source_urls` is the url projection of `_plan_claim_sources`. If that
    stopped being true, the Stage-7 resolution pre-pass would resolve a set of
    urls that is not the set the loop upserts -- D-V01-11's whole concern.
    """
    claim = CLAIMS[index]
    planned = _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP)
    assert [e["url"] for e in planned] == _gather_source_urls([claim], VERDICTS_BY_CLAIM)


def test_every_entry_carries_exactly_the_six_keys():
    for claim in CLAIMS:
        for entry in _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP):
            assert set(entry) == set(GOLDEN_FIELDS) | {"origin"}, claim["fixture_id"]
            assert entry["origin"] in ("provider", "skeptic")


def test_flags_off_total_is_the_recorded_fixture_count():
    total = sum(len(_plan_claim_sources(c, VERDICTS_BY_CLAIM, RESOLVED_MAP)) for c in CLAIMS)
    assert total == FLAGS_OFF_TOTAL_ENTRIES


def test_gather_source_urls_still_dedupes_across_claims():
    """The run-wide unique set the Stage-7 pre-pass needs (D-V01-11).

    Per-claim dedupe alone is not enough: the same redirect is cited by many
    claims, and resolving it once per claim is what the pre-pass exists to avoid.
    """
    run_wide = _gather_source_urls(CLAIMS, VERDICTS_BY_CLAIM)
    assert len(run_wide) == len(set(run_wide))
    per_claim_total = sum(len(_gather_source_urls([c], VERDICTS_BY_CLAIM)) for c in CLAIMS)
    assert len(run_wide) < per_claim_total


def test_a_claim_that_is_not_a_dict_is_skipped_not_raised():
    """Model-authored input reaches this path; nothing here may raise."""
    assert _gather_source_urls(["not a claim", None, 7], VERDICTS_BY_CLAIM) == []


def test_resolved_map_is_optional():
    """The Stage-7 pre-pass calls the url projection with no map at all."""
    for claim in CLAIMS:
        planned = _plan_claim_sources(claim, VERDICTS_BY_CLAIM, None)
        assert all(e["resolved_url"] is None for e in planned)
        assert all(e["resolution_status"] is None for e in planned)


def test_the_fixture_reproduces_mechanism_one(golden):
    """The three group members each inherit the SAME shared verdict's citations.

    This is the defect, pinned as present. Task 3 turns it off behind a switch;
    if this test ever fails with the flags off, the fixture stopped modelling the
    thing the phase exists to fix.
    """
    members = [
        "c04a_group_member_one",
        "c04b_group_member_two",
        "c04c_group_member_three_no_own_url",
    ]
    shared = [set(e["url"] for e in golden[m]) for m in members]
    common = set.intersection(*shared)
    assert len(common) >= 5
    # The member that supplied NO url of its own still gets a full set of rows.
    assert len(golden["c04c_group_member_three_no_own_url"]) >= 5


def test_the_fixture_reproduces_mechanism_two(golden):
    """One claim's display domain is stamped on two foreign hosts, flags off."""
    entries = golden["c05_foreign_hosts_one_title"]
    assert {e["title"] for e in entries} == {"wikipedia.org"}
    assert any("ebay.de" in e["url"] for e in entries)
    assert any("ah.nl" in e["url"] for e in entries)
    # And the grade half: an ebay listing graded "official" because the CLAIM
    # said so about itself.
    ebay = [e for e in golden["c09_partial_quality_map"] if "ebay.de" in e["url"]]
    assert ebay and ebay[0]["provider_quality"] == "official"
