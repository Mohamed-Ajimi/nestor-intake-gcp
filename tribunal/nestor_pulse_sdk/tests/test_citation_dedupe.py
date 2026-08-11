"""Citation source-identity tests (Phase 22, D-22-4).

Layer 1 only: PURE. No DB, no API key, no network, no mocking library -- so the
whole file runs in the keyless, Postgres-less engine fast gate
(`cloudbuild.test-engine.yaml`).

What is proved here:
  * ONE IDENTITY KEY -- `normalize_source_url` is the single definition of "the
                        same source", shared by the read path (this phase) and by
                        the INSERT conflict key (the follow-up phase). Two layers
                        that normalize differently reintroduce D-22-4 one level
                        down, so the properties below are the contract between
                        them.
  * RESOLVED WINS    -- `resolved_url` is preferred ONLY when
                        `resolution_status == "resolved"`. It is load-bearing, not
                        a refinement: gemini `vertexaisearch` grounding redirects
                        arrive as a different opaque token per citation, and
                        nothing but the resolved target can collapse them.
  * NEVER OVER-MERGE -- path case survives and the bare `ref` parameter survives.
                        Merging two distinct documents into one number is the
                        opposite defect from the one being fixed, and a worse one
                        (T-22-03).
  * NEVER RAISES     -- non-string / blank / malformed input degrades to None.
                        `resolved_url` originates in a remote `Location` header
                        (T-22-01), and read-path code that raises takes down a
                        report the operator has already paid for.

One named test per property, deliberately -- not one table-driven loop. A future
edit that breaks `ref` preservation must fail a test whose NAME says what was lost.
"""

from __future__ import annotations

from nestor_pulse_sdk.citations.dedupe import (
    _TRACKING_PARAMS,
    normalize_source_url,
)


# ---------------------------------------------------------------------------
# 1. Picking the input
# ---------------------------------------------------------------------------


def test_scheme_and_www_and_trailing_slash_all_drop_out_of_the_key():
    """`https://www.example.com/a/` and `http://example.com/a` are ONE source.

    Scheme exclusion is an orchestrator decision recorded in 22-CONTEXT.md that
    widens D-22-4's literal wording: the same document served over both schemes is
    one document.
    """
    assert normalize_source_url("https://www.example.com/a/", None, None) == (
        normalize_source_url("http://example.com/a", None, None)
    )


def test_resolved_url_is_the_key_when_the_status_says_resolved():
    """The redirect token is discarded in favour of the durable publisher URL."""
    token = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/AbCdEf123"

    assert normalize_source_url(
        token, "https://publisher.example/x", "resolved"
    ) == normalize_source_url("https://publisher.example/x", None, None)


def test_raw_url_is_the_key_when_resolution_was_attempted_and_failed():
    """`unresolved` means the HEAD resolution ran and found nothing usable."""
    token = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/Xyz789"

    assert normalize_source_url(token, None, "unresolved") == (
        "vertexaisearch.cloud.google.com/grounding-api-redirect/Xyz789"
    )


def test_resolved_url_is_ignored_when_the_status_is_absent():
    """The status gate is EXPLICIT, so a future partial write cannot leak through.

    A `resolved_url` present with a NULL status means resolution was never
    attempted for this row -- the value is not trustworthy as an identity key.
    """
    raw = "https://redirect.example/token-1"

    assert normalize_source_url(raw, "https://publisher.example/x", None) == (
        "redirect.example/token-1"
    )


# ---------------------------------------------------------------------------
# 2. The query string
# ---------------------------------------------------------------------------


def test_tracking_parameters_are_stripped_and_real_ones_survive():
    """`?utm_source=x&b=2` and `?b=2` are the same document."""
    assert normalize_source_url("https://example.com/a?utm_source=x&b=2") == (
        normalize_source_url("https://example.com/a?b=2")
    )


def test_the_bare_ref_parameter_is_preserved_because_it_is_meaningful():
    """DO NOT "fix" this by adding the bare name to the tracking set.

    On git hosts, docs sites and APIs that parameter selects WHICH DOCUMENT is
    served. Stripping it merges distinct documents -- the opposite failure from
    the one D-22-4 exists to fix, and a worse one.
    """
    assert normalize_source_url("https://example.com/a?ref=abc") != (
        normalize_source_url("https://example.com/a")
    )


def test_the_twitter_ref_parameters_are_stripped_unlike_the_bare_name():
    """`ref_src` / `ref_url` are unambiguous tracking, so they DO go."""
    assert normalize_source_url("https://example.com/a?ref_src=twsrc&ref_url=z") == (
        normalize_source_url("https://example.com/a")
    )


def test_query_parameter_order_does_not_change_the_key():
    """`?a=1&b=2` and `?b=2&a=1` address one document, so survivors are sorted."""
    assert normalize_source_url("https://example.com/a?a=1&b=2") == (
        normalize_source_url("https://example.com/a?b=2&a=1")
    )


def test_a_blank_valued_parameter_is_not_silently_lost():
    """`keep_blank_values=True` -- `?q=` is not the same request as no query."""
    assert normalize_source_url("https://example.com/a?q=") != (
        normalize_source_url("https://example.com/a")
    )


def test_the_tracking_set_is_a_closed_list_without_the_bare_ref_name():
    """The membership rule is a CLOSED set, never a prefix rule.

    A prefix rule over that three-letter stem would swallow the meaningful
    parameter guarded by
    `test_the_bare_ref_parameter_is_preserved_because_it_is_meaningful`.
    """
    assert "ref_src" in _TRACKING_PARAMS
    assert "ref_url" in _TRACKING_PARAMS
    assert "utm_source" in _TRACKING_PARAMS
    assert not any(name == "r" + "ef" for name in _TRACKING_PARAMS)


# ---------------------------------------------------------------------------
# 3. Host, port, fragment, path
# ---------------------------------------------------------------------------


def test_the_fragment_is_dropped():
    """A fragment addresses a position WITHIN one document."""
    assert normalize_source_url("https://example.com/a#section") == (
        normalize_source_url("https://example.com/a")
    )


def test_host_case_and_a_default_port_are_dropped():
    """DNS is case-insensitive and `:443` on https is the default."""
    assert normalize_source_url("https://EXAMPLE.com:443/a") == (
        normalize_source_url("https://example.com/a")
    )


def test_a_non_default_port_is_kept():
    """`:8443` is a different origin, not a formatting difference."""
    assert normalize_source_url("https://example.com:8443/a") != (
        normalize_source_url("https://example.com/a")
    )


def test_path_case_is_preserved():
    """Paths are case-sensitive on most origins.

    Lowercasing here would merge two genuinely different documents into one `[n]`
    (T-22-03).
    """
    assert normalize_source_url("https://example.com/A") != (
        normalize_source_url("https://example.com/a")
    )


def test_a_bare_root_path_normalizes_to_the_host_alone():
    """`https://example.com/` and `https://example.com` are one source."""
    assert normalize_source_url("https://example.com/") == "example.com"
    assert normalize_source_url("https://example.com") == "example.com"


# ---------------------------------------------------------------------------
# 4. Totality (T-22-01)
# ---------------------------------------------------------------------------


def test_none_and_blank_input_returns_none():
    assert normalize_source_url(None) is None
    assert normalize_source_url("") is None
    assert normalize_source_url("   ") is None


def test_a_non_string_returns_none_and_never_raises():
    """`resolved_url` comes from a remote `Location` header (T-22-01).

    It reaches this function as an attacker-influenceable value, so every input
    shape has to degrade rather than propagate.
    """
    assert normalize_source_url(123) is None
    assert normalize_source_url(object()) is None
    assert normalize_source_url([1, 2, 3]) is None
    assert normalize_source_url(123, object(), "resolved") is None


def test_a_malformed_url_degrades_but_never_raises():
    """Whatever these produce, the one forbidden outcome is an exception."""
    for hostile in ("http://", "https://", ":::", "http://[", "%%%%", "///"):
        normalize_source_url(hostile)
