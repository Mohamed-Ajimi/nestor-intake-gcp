"""resolve_url_citations tests (2026-06-11) — the [cite: N] fix.

The deep-research Interactions API returns text with numeric markers and the
real sources as a separate annotations list; the adapter must inline them as
markdown links so citations survive scrub -> synthesis -> Sources extraction.
"""
from __future__ import annotations

from nestor_pulse_sdk.audit.audited_llm_client import (
    resolve_url_citations,
    strip_unresolved_cite_markers,
)


class _Ann:
    def __init__(self, url=None, title=None, start_index=None, end_index=None):
        self.type = "url_citation"
        self.url = url
        self.title = title
        self.start_index = start_index
        self.end_index = end_index


TEXT = "Margins improved by 10% [cite: 2]. Coffee sales rose 12% [cite: 5, 7]."
#       0123456789...  end of "10%" ~ index 23 ; end of "12%" ~ index 57


class TestResolveUrlCitations:
    def test_injects_links_and_strips_markers(self):
        anns = [
            _Ann(url="https://kalibrate.com/x", title="Kalibrate", start_index=0, end_index=23),
            _Ann(url="https://shell.com/y", title="Shell", start_index=36, end_index=57),
        ]
        out = resolve_url_citations(TEXT, anns)
        assert "[Kalibrate](https://kalibrate.com/x)" in out
        assert "[Shell](https://shell.com/y)" in out
        assert "[cite" not in out, "markers must be stripped once resolved"
        # links land near their claims (Kalibrate before Shell)
        assert out.index("kalibrate.com") < out.index("shell.com")

    def test_no_annotations_leaves_text_untouched(self):
        assert resolve_url_citations(TEXT, []) == TEXT
        assert "[cite: 2]" in resolve_url_citations(TEXT, []), \
            "without a mapping, markers must be preserved (never destroy info)"

    def test_title_falls_back_to_domain(self):
        anns = [_Ann(url="https://www.pwc.com/report", end_index=23)]
        out = resolve_url_citations(TEXT, anns)
        assert "[pwc.com](https://www.pwc.com/report)" in out

    def test_dict_shaped_annotations(self):
        anns = [{"url": "https://a.com/z", "title": "A", "start_index": 0, "end_index": 23}]
        out = resolve_url_citations(TEXT, anns)
        assert "[A](https://a.com/z)" in out

    def test_out_of_range_index_appends_at_end(self):
        anns = [_Ann(url="https://b.com/q", title="B", end_index=99999)]
        out = resolve_url_citations(TEXT, anns)
        assert out.rstrip().endswith("[B](https://b.com/q)")

    def test_duplicate_position_url_pairs_inserted_once(self):
        anns = [
            _Ann(url="https://c.com", title="C", end_index=23),
            _Ann(url="https://c.com", title="C", end_index=23),
        ]
        out = resolve_url_citations(TEXT, anns)
        assert out.count("https://c.com") == 1

    def test_annotations_without_url_are_skipped(self):
        anns = [_Ann(url=None, title="file thing", end_index=23)]
        assert resolve_url_citations(TEXT, anns) == TEXT


class TestStripUnresolvedCiteMarkers:
    """Deliverable-level scrub: any [cite: N] that survived resolution points at
    nothing (resolve_url_citations already inlined every URL-backed marker), so
    it is removed from the final report rather than shown as a dead reference."""

    def test_strips_orphan_markers_and_counts(self):
        out, n = strip_unresolved_cite_markers(TEXT)
        assert "[cite" not in out, "orphan markers must be gone from the deliverable"
        assert n == 2, "both [cite: 2] and [cite: 5, 7] counted"
        assert "Margins improved by 10%." in out
        assert "Coffee sales rose 12%." in out

    def test_leaves_resolved_markdown_links_untouched(self):
        resolved = "Margins improved [Kalibrate](https://kalibrate.com/x) by 10%."
        out, n = strip_unresolved_cite_markers(resolved)
        assert out == resolved, "real markdown links are not citation markers"
        assert n == 0

    def test_clean_text_is_a_noop(self):
        assert strip_unresolved_cite_markers("No markers here.") == ("No markers here.", 0)
        assert strip_unresolved_cite_markers("") == ("", 0)

    def test_underscore_marker_variant_also_stripped(self):
        # _CITE_MARKER_RE matches both [cite:...] and [cite_...] forms.
        out, n = strip_unresolved_cite_markers("Fact [cite_3] here.")
        assert "[cite" not in out and n == 1
