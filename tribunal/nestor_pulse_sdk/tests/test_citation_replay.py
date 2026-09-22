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


# ===========================================================================
# FLAGS ON -- mechanisms 1 and 2 (phase 23.5-04 Task 3)
# ===========================================================================
# Everything above this line is the flags-OFF contract and is not touched by
# this block. Everything below runs with NESTOR_CITATIONS_V2=true.
#
# The three behavioural assertions are ZERO-COUNTS over the WHOLE fixture, not
# spot checks: each builds a list of violations and asserts the list is empty,
# printing the offending entries on failure. A spot check passes for the one
# claim it names and says nothing about the eleven it does not.

#: FIXTURE COUNT, not a production count. The 12 synthetic claims plan 14
#: entries with the master on, down from 55. The production collapse -- 2,681
#: numbered sources down to the count of distinct provider urls -- is measured
#: on the dev run in plan 07 and is NOT this ratio.
FLAGS_ON_TOTAL_ENTRIES = 14


@pytest.fixture
def flags_on(monkeypatch):
    """Master on, every sub-switch left at its own default (true)."""
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")


def _plan_all():
    return {
        claim["fixture_id"]: _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP)
        for claim in CLAIMS
    }


def test_flags_on_no_entry_comes_from_a_skeptic(flags_on):
    """Mechanism 1, as a zero-count.

    A skeptic's `web_search` result list is the evidence for the GROUP's verdict.
    Copying it onto every member claim is what turned 586 claims into 4,999
    `claim_source` rows.
    """
    violations = [
        (fid, e["url"])
        for fid, entries in _plan_all().items()
        for e in entries
        if e["origin"] == "skeptic"
    ]
    assert violations == [], violations


def test_flags_on_the_three_group_members_keep_only_their_own_urls(flags_on):
    """The shape that drove the row count, named explicitly.

    The member that supplied no url of its own now plans NO source rows -- which
    is the honest reading. Its evidence is not lost: it is on its verdict row,
    which `_insert_verdict` still writes unchanged.
    """
    planned = _plan_all()
    assert [e["url"] for e in planned["c04a_group_member_one"]] == [
        "https://fd.nl/bedrijfsleven/0000001/fixture-piece"
    ]
    assert [e["url"] for e in planned["c04b_group_member_two"]] == [
        "https://www.ah.nl/producten/product/wi000001"
    ]
    assert planned["c04c_group_member_three_no_own_url"] == []


def test_flags_on_no_title_is_stamped_on_a_foreign_host(flags_on):
    """Mechanism 2, title half, as a zero-count.

    Every surviving title either belongs to a grounding redirect -- where the
    provider's display label is the ONLY honest thing to show -- or names the
    url's own host. Everything else is dropped to None and
    `build_graded_sources_section` falls back to the url's own display domain.
    """
    from nestor_pulse_sdk.citations.numbering import _domain
    from nestor_pulse_sdk.citations.redirect_resolver import is_redirect_url

    violations = [
        (fid, e["url"], e["title"])
        for fid, entries in _plan_all().items()
        for e in entries
        if e["title"] is not None
        and not is_redirect_url(e["url"])
        and _domain(e["url"]) != e["title"]
    ]
    assert violations == [], violations


def test_flags_on_no_grade_is_stamped_on_a_url_the_claim_did_not_supply(flags_on):
    """Mechanism 2, grade half, as a zero-count.

    "Established press" on an ebay listing, because some OTHER url of the same
    claim was graded that way, is the defect. A url the claim did not supply
    carries no grade and falls through to `derive_quality_tier`'s domain
    heuristic at render time.
    """
    by_id = {c["fixture_id"]: c for c in CLAIMS}
    violations = []
    for fid, entries in _plan_all().items():
        claim = by_id[fid]
        graded = claim.get("provider_quality_by_url")
        graded = graded if isinstance(graded, dict) else {}
        own = claim.get("source_urls")
        own = {u.strip() for u in own if isinstance(u, str)} if isinstance(own, list) else set()
        for e in entries:
            if e["provider_quality"] is None:
                continue
            if e["url"] in graded or e["url"] in own:
                continue
            violations.append((fid, e["url"], e["provider_quality"]))
    assert violations == [], violations


def test_flags_on_the_specific_measured_shapes_are_fixed(flags_on):
    """The wikipedia / ebay / ah and the ebay-graded-official cases, by name."""
    planned = _plan_all()

    # c05: the two foreign hosts arrived through the verdict, so they are gone
    # entirely; the claim's own wikipedia url survives, and its title drops to
    # None because en.wikipedia.org is not the claimed display domain.
    c05 = planned["c05_foreign_hosts_one_title"]
    assert [e["url"] for e in c05] == ["https://en.wikipedia.org/wiki/Fixture_subject"]
    assert c05[0]["title"] is None

    # c09: the ebay url is gone, and the rijksoverheid url the claim DID supply
    # keeps the claim's own scalar grade.
    c09 = {e["url"]: e for e in planned["c09_partial_quality_map"]}
    assert not any("ebay.de" in u for u in c09)
    assert c09["https://www.cbs.nl/nl-nl/cijfers/detail/00000"]["provider_quality"] == "official"

    # c10: the 200-char garbage label is no longer stamped on fd.nl.
    assert planned["c10_overlong_source_domain"][0]["title"] is None

    # c06: a grounding redirect KEEPS the provider's display label -- it is the
    # only honest thing to print for an opaque url -- and both resolution states
    # survive untouched.
    c06 = {e["url"]: e for e in planned["c06_redirects_resolved_and_not"]}
    redirects = [e for u, e in c06.items() if "grounding-api-redirect" in u]
    assert len(redirects) == 2
    assert {e["title"] for e in redirects} == {"nos.nl"}
    assert {e["resolution_status"] for e in redirects} == {"resolved", "unresolved"}


def test_flags_on_plans_strictly_fewer_entries(flags_on):
    on_total = sum(len(v) for v in _plan_all().values())
    assert on_total == FLAGS_ON_TOTAL_ENTRIES
    assert on_total < FLAGS_OFF_TOTAL_ENTRIES


def test_the_verdicts_are_never_mutated(flags_on):
    """The skeptic's evidence still reaches the verdict row.

    `group_skeptic.py` is deliberately NOT touched by this phase: the fan-out is
    corrected at the persist boundary, so the verdict keeps its citations and
    `_insert_verdict` writes exactly what it wrote before.
    """
    before = repr(VERDICTS_BY_CLAIM)
    _plan_all()
    assert repr(VERDICTS_BY_CLAIM) == before
    assert VERDICTS_BY_CLAIM[id(CLAIMS[3])]["citations"], "the group verdict kept its evidence"


def test_turning_the_master_back_off_restores_the_golden(monkeypatch, golden):
    """The revert is one environment variable, and it is proven, not asserted.

    This is the same comparison the flags-off block makes, run in a process that
    has ALREADY seen the flags on -- which is the case a module-level,
    import-time flag read could not have covered at all.
    """
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    assert sum(len(v) for v in _plan_all().values()) == FLAGS_ON_TOTAL_ENTRIES
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "false")
    for claim in CLAIMS:
        planned = _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP)
        assert _project(planned) == golden[claim["fixture_id"]], claim["fixture_id"]


def test_a_sub_switch_isolates_one_mechanism(monkeypatch, golden):
    """Bisecting: mechanism 1 on, mechanism 2 off, in one run.

    With `per_url_meta` off, every surviving entry carries the SAME title and
    grade the golden recorded for that url -- so a bad dev run can be narrowed
    to one mechanism without a rebuild.
    """
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    monkeypatch.setenv("NESTOR_CITATIONS_PER_URL_META", "false")
    golden_by_url = {
        fid: {e["url"]: e for e in entries} for fid, entries in golden.items()
    }
    violations = []
    for claim in CLAIMS:
        fid = claim["fixture_id"]
        for e in _plan_claim_sources(claim, VERDICTS_BY_CLAIM, RESOLVED_MAP):
            was = golden_by_url[fid][e["url"]]
            if (e["title"], e["provider_quality"]) != (was["title"], was["provider_quality"]):
                violations.append((fid, e["url"], e["title"], was["title"]))
            if e["origin"] == "skeptic":
                violations.append((fid, e["url"], "skeptic entry survived"))
    assert violations == [], violations
