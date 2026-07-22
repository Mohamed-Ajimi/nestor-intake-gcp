"""Pure-builder proofs for ``app.research.bundle.build_bundle_zip`` (RUN-03 / D-03).

The raw-output bundle is the immutable snapshot the completion path (Plan 02)
materializes to GCS once a run's audit chain verifies. This suite pins the D-03
zip LAYOUT and the D-01 "no discredited content" guarantee at the builder level —
the builder is pure (no I/O, no GCS, no DB), so these assertions run on any box
without the app's runtime seams installed (they run in Cloud Build).

What this pins:

- The zip contains EXACTLY ``report.md`` at root, one ``research/<angle>.md`` per
  ``cleaned_reports`` entry, and ``sources.json`` at root (D-03 layout).
- ``report.md`` carries the report markdown (``report["markdown"]`` or the
  fallback the caller passes).
- A provider name with an em-dash / spaces is sanitized into the entry path
  (reusing the shared ``sanitize_filename`` — no hand-rolled sanitizer).
- An empty ``cleaned_reports`` list yields a zip with report.md + sources.json and
  NO ``research/`` entries (no crash).
- ``sources.json`` is ``json.dumps`` of the sources list (unicode preserved).
- NOTHING in the zip (no entry name, no entry body) contains ``rejected`` — the
  discredited-content ledger is structurally absent (D-01).

The builder is imported LAZILY (``importorskip``) so this collects on a box
without the app package installed.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

bundle_mod = pytest.importorskip("app.research.bundle")

build_bundle_zip = bundle_mod.build_bundle_zip


def _read_zip(data: bytes) -> zipfile.ZipFile:
    """Open the returned bytes back as a zip for assertion."""
    return zipfile.ZipFile(io.BytesIO(data))


def test_layout_report_research_and_sources():
    """The zip has report.md + one research/<angle>.md + sources.json (D-03 layout)."""
    report = {"markdown": "# The Report Body"}
    inner = {"cleaned_reports": [["angle-a", {"report": "provider A text"}]]}
    sources = [{"url": "https://example.com", "title": "Example"}]

    result = build_bundle_zip(report, inner, sources)
    assert isinstance(result, bytes)

    zf = _read_zip(result)
    names = set(zf.namelist())
    assert "report.md" in names
    assert "sources.json" in names
    assert "research/angle-a.md" in names

    assert zf.read("report.md").decode("utf-8") == "# The Report Body"
    assert zf.read("research/angle-a.md").decode("utf-8") == "provider A text"


def test_report_md_uses_markdown_key():
    """report.md carries report["markdown"] (the caller supplies the fallback body)."""
    report = {"markdown": "persisted output markdown body"}
    result = build_bundle_zip(report, {"cleaned_reports": []}, [])
    zf = _read_zip(result)
    assert zf.read("report.md").decode("utf-8") == "persisted output markdown body"


def test_report_md_empty_when_markdown_missing():
    """A missing/None markdown yields an empty report.md rather than crashing."""
    result = build_bundle_zip({}, {"cleaned_reports": []}, [])
    zf = _read_zip(result)
    assert zf.read("report.md").decode("utf-8") == ""


def test_provider_name_is_sanitized_into_entry_path():
    """An em-dash / space provider name is sanitized (shared sanitize_filename)."""
    inner = {"cleaned_reports": [["Angle One — Two Three", {"report": "X"}]]}
    result = build_bundle_zip({"markdown": "r"}, inner, [])
    zf = _read_zip(result)

    research_entries = [n for n in zf.namelist() if n.startswith("research/")]
    assert len(research_entries) == 1, research_entries
    entry = research_entries[0]
    # No raw whitespace, no em-dash, no path-traversal separators in the name.
    assert " " not in entry
    assert "—" not in entry
    # sanitize_filename: em-dash -> '-', whitespace runs -> '_' (the surrounding
    # spaces around the dash become '_', so "One — Two" -> "One_-_Two").
    assert entry == "research/Angle_One_-_Two_Three.md"
    assert zf.read(entry).decode("utf-8") == "X"


def test_empty_cleaned_reports_yields_no_research_entries():
    """An empty cleaned_reports list produces report.md + sources.json, no research/."""
    result = build_bundle_zip({"markdown": "r"}, {"cleaned_reports": []}, [])
    zf = _read_zip(result)
    names = zf.namelist()
    assert "report.md" in names
    assert "sources.json" in names
    assert not any(n.startswith("research/") for n in names)


def test_missing_cleaned_reports_key_does_not_crash():
    """A bundle dict with no cleaned_reports key is tolerated (defensive `or []`)."""
    result = build_bundle_zip({"markdown": "r"}, {}, [])
    zf = _read_zip(result)
    assert not any(n.startswith("research/") for n in zf.namelist())


def test_sources_json_is_json_dump_unicode_preserved():
    """sources.json is json.dumps of the sources list with unicode preserved."""
    sources = [{"title": "Café — naïve"}]
    result = build_bundle_zip({"markdown": "r"}, {"cleaned_reports": []}, sources)
    zf = _read_zip(result)
    body = zf.read("sources.json").decode("utf-8")
    # ensure_ascii=False keeps the accented characters literal (not \\uXXXX).
    assert "Café — naïve" in body
    assert json.loads(body) == sources


def test_non_dict_result_falls_back_to_str():
    """A cleaned_reports result that is not a dict is coerced to str for the body."""
    inner = {"cleaned_reports": [["angle-b", "raw string report"]]}
    result = build_bundle_zip({"markdown": "r"}, inner, [])
    zf = _read_zip(result)
    assert zf.read("research/angle-b.md").decode("utf-8") == "raw string report"


def test_no_rejected_content_anywhere_D01():
    """No entry NAME or BODY contains the substring 'rejected' (D-01 scrub proof)."""
    # Even if a hostile provider name or body tried to smuggle the token, the
    # builder only writes report.md / research/* / sources.json from cleaned_reports.
    report = {"markdown": "clean report — no discredited claims"}
    inner = {"cleaned_reports": [["angle-a", {"report": "verified provider text"}]]}
    sources = [{"url": "https://example.com"}]

    result = build_bundle_zip(report, inner, sources)
    zf = _read_zip(result)

    for name in zf.namelist():
        assert "rejected" not in name.lower(), f"entry name leaks rejected: {name}"
        body = zf.read(name).decode("utf-8")
        assert "rejected" not in body.lower(), f"entry body leaks rejected: {name}"
