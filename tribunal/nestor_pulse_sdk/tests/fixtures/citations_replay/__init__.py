"""Offline replay fixture for the run-7784e71c citation defect (phase 23.5-04).

THESE ARE SYNTHETIC SHAPES, NOT COPIED ROWS. Nothing here was read out of any
database, and no value here is production text. Every claim below reproduces a
SHAPE that was measured on run `7784e71c` and recorded in
`gs://nestor-pulse-prod-nestor-audit/diagnostics/7784e71c/diag.txt`, so that the
persist path's decisions can be replayed on a bare dev box with no database, no
network and no provider call.

THE COUNTS IN THIS MODULE ARE FIXTURE COUNTS. They are NOT the 2,681 numbered
sources or the 1,824 mislabelled ones. This fixture has a dozen claims; the
production run had 586. The production totals -- and the collapse of 2,681 to
the count of distinct provider urls -- are measured on the dev run in plan 07,
not here. What this fixture proves is that each measured MECHANISM is present
and that the fix turns it off; it proves nothing about magnitude.

Exports, in exactly the shapes `persist_tribunal_claims` receives them:

  ``CLAIMS``             list[dict] -- the claim dicts, in pipeline order
  ``VERDICTS_BY_CLAIM``  dict keyed by ``id(claim)`` (OBJECT IDENTITY, the same
                         convention `_verdicts_for` reads), value a verdict dict
                         or a list of them
  ``RESOLVED_MAP``       dict[str, str | None] -- the Stage-7 redirect pre-pass
                         result: a target url when resolution succeeded, ``None``
                         when it was attempted and failed

⚠ ``VERDICTS_BY_CLAIM`` IS KEYED BY ``id()``. Copy a claim dict (``dict(claim)``,
``copy.deepcopy(CLAIMS)``) and its verdicts silently vanish, because the copy is
a different object. Pass the objects from ``CLAIMS`` through unchanged.

THE NINE SHAPES, and the measured phenomenon each stands for
------------------------------------------------------------

 1. ``c01`` -- zero source urls, no verdict at all. The 159 sourceless claims.
 2. ``c02`` -- exactly one provider url. The median (sources/claim median = 1).
 3. ``c03`` -- 24 urls, 22 of them from the group verdict's ``citations``. The
    max-58 tail.
 4. ``c04a/c04b/c04c`` -- three claims sharing ONE verdict object whose
    ``citations`` list therefore fans out across all three. Mechanism 1, the
    4,999-claim_source-row driver.
 5. ``c05`` -- ``source_domain`` is one host while the url set reaches two
    FOREIGN hosts. Mechanism 2, the 1,824 wrong labels, modelled on the measured
    wikipedia.org / ebay.de / ah.nl shape.
 6. ``c06`` -- one grounding redirect that RESOLVED to a real publisher and a
    second that was attempted and did NOT. Plus a non-redirect url that is
    present in the map, which must still take the NULL state.
 7. ``c07`` -- a ``distiller_fallback`` claim: ``source_domain`` empty, no usable
    url. Mechanism 5's driver (consumed by plan 05).
 8. ``c08`` -- an ``evidence_refs`` entry that is free text of the form
    ``"https://host/path (quote)"`` rather than a bare url; the minor
    garbage-tier-label finding. Its ``source_urls`` is a bare STRING, the shape
    `_as_list` exists to refuse.
 9. ``c09`` -- ``provider_quality_by_url`` covering SOME of its urls plus a
    scalar ``provider_quality`` for the claim. Mechanism 2's grade half.

``c10`` is not one of the nine: it carries an over-long model-authored
``source_domain`` so the 200-character title truncation is exercised by the
golden rather than assumed.
"""

# ---------------------------------------------------------------------------
# URL constants. Every host here is either a documentation/reserved name or a
# real host used ONLY as a shape -- no path below points at a real document.
# ---------------------------------------------------------------------------

REDIRECT_PREFIX = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"

#: Attempted and RESOLVED -- the pre-pass got a publisher url back.
REDIRECT_RESOLVED = REDIRECT_PREFIX + "AUZIYQFr3s1Kq9bWresolved0001"
#: Attempted and NOT resolved -- the redirect expires ~30 days after the run and
#: the publisher url is about to be lost. This must NOT read as "never attempted".
REDIRECT_UNRESOLVED = REDIRECT_PREFIX + "AUZIYQFr3s1Kq9bWunresolved02"
#: The publisher behind REDIRECT_RESOLVED.
RESOLVED_TARGET = "https://www.nos.nl/artikel/2500001-fixture-article"

WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Fixture_subject"
EBAY_URL = "https://www.ebay.de/itm/000000000001"
AH_URL = "https://www.ah.nl/producten/product/wi000001"
CBS_URL = "https://www.cbs.nl/nl-nl/cijfers/detail/00000"
RIJKSOVERHEID_URL = "https://www.rijksoverheid.nl/onderwerpen/fixture"
FD_URL = "https://fd.nl/bedrijfsleven/0000001/fixture-piece"

#: The 20 whole-session `web_search` RESULT urls a single skeptic turn produces.
#: Generated, not hand-written, because the ORDER is the thing under test and a
#: generated list cannot be accidentally reordered by an editor.
SKEPTIC_SESSION_URLS = [f"https://example-{i:02d}.test/article" for i in range(1, 21)]


# ---------------------------------------------------------------------------
# The claims. `fixture_id` is OUR key, not a pipeline field -- the persist path
# reads claims with `.get()` and ignores keys it does not know, and the golden
# JSON needs a stable name for each claim that survives serialisation.
# ---------------------------------------------------------------------------

_C01 = {
    # SHAPE 1 -- one of the 159 claims with no source at all. No `source_urls`
    # key, no `evidence_refs` key, no verdict: the keys are ABSENT rather than
    # empty, because that is how a claim that never carried a url arrives.
    "fixture_id": "c01_sourceless_no_verdict",
    "claim_text": "The category grew in the reporting period.",
    "facet": "market",
    "position": 1,
    "found_by": "gemini",
    "source_domain": "",
}

_C02 = {
    # SHAPE 2 -- the median claim: exactly one provider url. Its verdict repeats
    # that same url as a citation DICT, so the first-seen dedupe is exercised
    # across two different field shapes for one url.
    "fixture_id": "c02_single_provider_url",
    "claim_text": "The regulator published the figure in Q2.",
    "facet": "regulation",
    "position": 2,
    "found_by": "claude",
    "source_domain": "rijksoverheid.nl",
    "source_urls": [RIJKSOVERHEID_URL],
    "provider_quality": "official",
}

_C03 = {
    # SHAPE 3 -- the max-58 tail. Two urls the provider actually supplied, and
    # 22 that arrive through the group verdict's `citations`. Today every one of
    # the 24 becomes a `claim_source` row of THIS claim.
    "fixture_id": "c03_long_tail_mostly_skeptic",
    "claim_text": "Retail prices diverged across the three largest chains.",
    "facet": "pricing",
    "position": 3,
    "found_by": "gemini",
    "source_domain": "cbs.nl",
    "source_urls": [CBS_URL],
    "evidence_refs": [FD_URL],
    "provider_quality": "press",
}

_C04A = {
    # SHAPE 4 -- three claims, ONE shared verdict object. This is exactly what
    # `group_skeptic._parse_group_verdict` produces: `citations=list(citations)`
    # on every member of the group, where `citations` is the WHOLE session's
    # search results. 586 claims became 4,999 rows this way.
    "fixture_id": "c04a_group_member_one",
    "claim_text": "Own-brand share rose in the discount segment.",
    "facet": "market",
    "position": 4,
    "found_by": "claude",
    "source_domain": "fd.nl",
    "source_urls": [FD_URL],
    "provider_quality": "press",
}

_C04B = {
    "fixture_id": "c04b_group_member_two",
    "claim_text": "Promotional depth increased year on year.",
    "facet": "market",
    "position": 5,
    "found_by": "claude",
    "source_domain": "ah.nl",
    "source_urls": [AH_URL],
    "provider_quality": "other",
}

_C04C = {
    # The third member supplies NO url of its own, so every source row it gets
    # today comes from the shared verdict. With mechanism 1 fixed it has none --
    # which is the honest reading, and the evidence still sits on its verdict.
    "fixture_id": "c04c_group_member_three_no_own_url",
    "claim_text": "Private label pricing lagged the branded average.",
    "facet": "pricing",
    "position": 6,
    "found_by": "claude",
    "source_domain": "ah.nl",
}

_C05 = {
    # SHAPE 5 -- mechanism 2, the 1,824 wrong labels. `source_domain` says
    # wikipedia.org; the url set reaches ebay.de and ah.nl, two hosts this claim
    # has nothing to do with. Today all three rows are titled "wikipedia.org".
    "fixture_id": "c05_foreign_hosts_one_title",
    "claim_text": "The product family has been sold under that name since 1998.",
    "facet": "history",
    "position": 7,
    "found_by": "gemini",
    "source_domain": "wikipedia.org",
    "source_urls": [WIKIPEDIA_URL],
    "provider_quality": "press",
}

_C06 = {
    # SHAPE 6 -- the three-state resolution rule, all three states in one claim:
    #   REDIRECT_RESOLVED    -> 'resolved'   (a redirect, target came back)
    #   REDIRECT_UNRESOLVED  -> 'unresolved' (a redirect, attempted, no target)
    #   CBS_URL              -> NULL         (in the map, but NOT a redirect)
    #   WIKIPEDIA_URL        -> NULL         (not in the map at all)
    # `source_domain` is the provider's own markdown link label -- the ONLY
    # honest title for an opaque redirect, which is why the per-url rule keeps it
    # there and nowhere else.
    "fixture_id": "c06_redirects_resolved_and_not",
    "claim_text": "Imports shifted toward regional suppliers.",
    "facet": "supply",
    "position": 8,
    "found_by": "gemini",
    "source_domain": "nos.nl",
    "source_urls": [REDIRECT_RESOLVED, REDIRECT_UNRESOLVED, CBS_URL, WIKIPEDIA_URL],
    "provider_quality": "press",
}

_C07 = {
    # SHAPE 7 -- mechanism 5's driver. The distiller fallback zeroes
    # `source_domain` and carries no usable url, so the claim can never be
    # numbered, so every writer anchor pointing at it is stripped: 108 of them on
    # run 7784e71c, and 0 on the three runs before it. Plan 05 consumes this.
    "fixture_id": "c07_distiller_fallback_unnumberable",
    "claim_text": "Consumer sentiment recovered more slowly than spending.",
    "facet": "demand",
    "position": 9,
    "found_by": "distiller_fallback",
    "source_domain": "",
    "source_urls": [],
    "evidence_refs": [],
}

_C08 = {
    # SHAPE 8 -- the minor finding. A skeptic wrote its evidence ref as prose
    # with the url embedded, and it is stored VERBATIM as `source.url`, which is
    # what produces the garbage tier labels in the rendered list.
    #
    # `source_urls` here is a bare STRING, which is the shape `_as_list` exists
    # to refuse: iterating it would yield its CHARACTERS and each one would pass
    # the `isinstance(url, str)` test and become a one-character source row.
    "fixture_id": "c08_free_text_evidence_ref",
    "claim_text": "A retailer confirmed the assortment change publicly.",
    "facet": "supply",
    "position": 10,
    "found_by": "claude",
    "source_domain": "ah.nl",
    "source_urls": "unknown",
    "evidence_refs": [
        AH_URL + ' ("we hebben het assortiment aangepast")',
        None,  # a model-authored list may hold a non-string; it is skipped
    ],
    "provider_quality": "other",
}

_C09 = {
    # SHAPE 9 -- mechanism 2's grade half. `provider_quality_by_url` grades TWO
    # of this claim's urls; the scalar `provider_quality` is the claim's own
    # single-provider grade. Today `quality_by_url.get(url) or claim_quality`
    # stamps "official" on the ebay listing that arrives via the verdict.
    #
    # The leading/trailing whitespace on the second url is deliberate: the
    # persist path strips at dedupe time, so " X " and "X" are ONE url.
    "fixture_id": "c09_partial_quality_map",
    "claim_text": "The official statistics office and a retailer disagree on the level.",
    "facet": "pricing",
    "position": 11,
    "found_by": "gemini",
    "source_domain": "cbs.nl",
    "source_urls": [CBS_URL, "  " + RIJKSOVERHEID_URL + "  "],
    "provider_quality": "official",
    "provider_quality_by_url": {
        CBS_URL: "official",
        FD_URL: "press",  # a url this claim does not itself supply
    },
}

_C10 = {
    # NOT one of the nine. A model-authored `source_domain` of 250 characters,
    # so the 200-character title truncation is something the golden OBSERVES
    # rather than something this plan assumes.
    "fixture_id": "c10_overlong_source_domain",
    "claim_text": "A secondary source restated the figure.",
    "facet": "market",
    "position": 12,
    "found_by": "gemini",
    "source_domain": "verylongdomainlabel." * 12 + "example.test",
    "source_urls": [FD_URL],
    "provider_quality": "other",
}

CLAIMS = [
    _C01,
    _C02,
    _C03,
    _C04A,
    _C04B,
    _C04C,
    _C05,
    _C06,
    _C07,
    _C08,
    _C09,
    _C10,
]


# ---------------------------------------------------------------------------
# The verdicts. Keyed by `id(claim)` -- the same object-identity convention
# `_verdicts_for` reads. The group of three shares ONE dict OBJECT, which is the
# whole point of shape 4: the fan-out is not three copies of a list, it is one
# list reached from three claims.
# ---------------------------------------------------------------------------

#: The shared group verdict. `citations` is every `web_search` RESULT url and
#: every `web_fetch` url of the WHOLE group session -- `_collect_citation_urls`'s
#: output, copied onto each member by `_parse_group_verdict`. This is the verdict
#: row's evidence, and after the fix it STAYS here: `group_skeptic.py` is not
#: touched, `_insert_verdict` still writes this list, and only the
#: claim_source fan-out is suppressed.
_GROUP_VERDICT = {
    "verdict": "supported",
    "confidence": 0.7,
    "evidence_refs": [WIKIPEDIA_URL],
    "citations": [
        EBAY_URL,
        AH_URL,
        FD_URL,
        CBS_URL,
        {"url": RIJKSOVERHEID_URL},
        {"source_url": WIKIPEDIA_URL},
        {"url": 12345},  # model-authored, not a string -- skipped, never raises
        None,  # ditto
    ],
    "note": "group session over three member claims",
}

_C03_VERDICT = {
    "verdict": "uncertain",
    "confidence": 0.4,
    "evidence_refs": [AH_URL],
    "citations": list(SKEPTIC_SESSION_URLS) + [EBAY_URL],
    "note": "one skeptic session, twenty-two result urls",
}

_C02_VERDICT = {
    "verdict": "supported",
    "confidence": 0.9,
    # The same url the claim already supplied -- exercises the first-seen dedupe
    # across the provider field and the verdict field.
    "citations": [{"url": RIJKSOVERHEID_URL}],
}

_C05_VERDICT = {
    "verdict": "contested",
    "confidence": 0.5,
    # Two FOREIGN hosts. Today both are titled "wikipedia.org" and graded
    # "press" because the claim said so about itself.
    "citations": [EBAY_URL, AH_URL],
}

_C09_VERDICT = {
    "verdict": "contested",
    "confidence": 0.6,
    "citations": [EBAY_URL],
}

VERDICTS_BY_CLAIM = {
    id(_C02): _C02_VERDICT,
    id(_C03): _C03_VERDICT,
    # ONE object, three claims. Mechanism 1 in a single line.
    id(_C04A): _GROUP_VERDICT,
    id(_C04B): _GROUP_VERDICT,
    id(_C04C): _GROUP_VERDICT,
    id(_C05): _C05_VERDICT,
    # A LIST of verdicts, not a bare dict -- `_verdicts_for` normalises both.
    id(_C09): [_C09_VERDICT],
}


# ---------------------------------------------------------------------------
# The Stage-7 redirect pre-pass result.
# ---------------------------------------------------------------------------

RESOLVED_MAP = {
    REDIRECT_RESOLVED: RESOLVED_TARGET,
    # Attempted, no target came back. NOT the same thing as absent.
    REDIRECT_UNRESOLVED: None,
    # Present in the map but NOT a redirect, so the status is NULL: nothing was
    # ever attempted for it. The `url not in resolved_map or not
    # is_redirect_url(url)` branch is what this entry exists to exercise.
    CBS_URL: None,
}
