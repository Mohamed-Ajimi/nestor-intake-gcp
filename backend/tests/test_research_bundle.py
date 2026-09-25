"""Pure-builder proofs for ``app.research.bundle.build_bundle_zip`` (RUN-03 / D-03).

The raw-output bundle is the immutable snapshot the completion path (Plan 02)
materializes to GCS once a run's audit chain verifies. This suite pins the D-03
zip LAYOUT and the D-01 "no discredited content" guarantee at the builder level —
the builder is pure (no I/O, no GCS, no DB), so these assertions run on any box
without the app's runtime seams installed (they run in Cloud Build).

What this pins:

- The zip contains ``report.md`` at root, one uniquely named
  ``research/<NN>-<question-slug>-<provider>.md`` per ``cleaned_reports`` entry,
  ``research/index.md``, and ``sources.json`` at root (D-03 layout). Duplicate
  provider names across angles never collide (260925-dyt).
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
    # 260925-dyt: entries are NN-prefixed so duplicate provider names cannot collide.
    assert "research/01-angle-a.md" in names
    assert "research/index.md" in names

    assert zf.read("report.md").decode("utf-8") == "# The Report Body"
    assert zf.read("research/01-angle-a.md").decode("utf-8").endswith("provider A text")


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

    research_entries = [
        n for n in zf.namelist() if n.startswith("research/") and n != "research/index.md"
    ]
    assert len(research_entries) == 1, research_entries
    entry = research_entries[0]
    # No raw whitespace, no em-dash, no path-traversal separators in the name.
    assert " " not in entry
    assert "—" not in entry
    # sanitize_filename: em-dash -> '-', whitespace runs -> '_' (the surrounding
    # spaces around the dash become '_', so "One — Two" -> "One_-_Two").
    assert entry == "research/01-Angle_One_-_Two_Three.md"
    assert zf.read(entry).decode("utf-8").endswith("X")


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
    assert zf.read("research/01-angle-b.md").decode("utf-8").endswith("raw string report")


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


# ---------------------------------------------------------------------------
# 260925-dyt: one file per angle report, named by question, no duplicate names.
# Before this fix the entries were research/<provider>.md, so a 15-entry bundle
# (5 angles x gemini/openai/claude) had only 3 distinct names and extractors kept
# one file per name — up to 12 of 15 reports lost (13 prod bundles, 2026-09-25).
# ---------------------------------------------------------------------------

SEP = "\n\n---\n\n"


def _research_files(zf: zipfile.ZipFile) -> list[str]:
    """Research report entries in zip order, excluding research/index.md."""
    return [
        i.filename
        for i in zf.infolist()
        if i.filename.startswith("research/") and i.filename != "research/index.md"
    ]


def _split(zf: zipfile.ZipFile, name: str) -> tuple[bytes, bytes]:
    """Return (header, body) bytes split on the first header separator."""
    raw = zf.read(name)
    header, sep, body = raw.partition(SEP.encode("utf-8"))
    assert sep, f"no header separator in {name}"
    return header, body


def _sanitize(text: str, **kw) -> str:
    from app.storage.keys import sanitize_filename

    return sanitize_filename(text, **kw)


def test_duplicate_providers_across_angles_all_survive():
    """3 angles x 3 providers -> 9 distinct, question-named, byte-identical entries."""
    angles = [
        "What is the market size for Belgian SaaS?",
        "Who are the main competitors?",
        "Quelle est la stratégie de prix ?",
    ]
    providers = ["gemini", "openai", "claude"]
    entries = []
    for ai, angle in enumerate(angles):
        for prov in providers:
            entries.append(
                [
                    prov,
                    {
                        "_angle": angle,
                        "_corroboration_key": f"key-{ai}",
                        "report": f"report for angle {ai} by {prov} — é ✓\n",
                    },
                ]
            )
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))

    all_names = [i.filename for i in zf.infolist()]
    assert len(all_names) == len(set(all_names)), all_names
    files = _research_files(zf)
    assert len(files) == 9, files
    assert "research/index.md" in all_names

    for _prov, result in entries:
        text = result["report"].encode("utf-8")
        matching = [f for f in files if zf.read(f).endswith(text)]
        assert len(matching) == 1, (text, matching)
        assert _split(zf, matching[0])[1] == text

    expected = [
        f"research/{ai + 1:02d}-{_sanitize(angle, max_len=60)}-{prov}.md"
        for ai, angle in enumerate(angles)
        for prov in providers
    ]
    assert files == expected


def test_grouping_prefers_corroboration_key():
    """Same corroboration key, angle differing only in case -> one shared NN."""
    entries = [
        ["gemini", {"_angle": "Market Size", "_corroboration_key": "k1", "report": "a"}],
        ["openai", {"_angle": "market size", "_corroboration_key": "k1", "report": "b"}],
    ]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    files = _research_files(zf)
    assert len(files) == 2, files
    assert all(f.startswith("research/01-") for f in files), files


def test_fallback_without_angle_and_plain_string():
    """No angle metadata -> NN-<provider>.md, each entry gets its own NN."""
    entries = [["gemini", {"report": "a"}], ["gemini", "raw b"]]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    files = _research_files(zf)
    assert files == ["research/01-gemini.md", "research/02-gemini.md"]
    assert _split(zf, files[0])[1] == b"a"
    assert _split(zf, files[1])[1] == b"raw b"
    names = [i.filename for i in zf.infolist()]
    assert len(names) == len(set(names))


def test_absolute_uniqueness_suffix():
    """Same angle + same provider (no key) -> the second gets a -2 suffix."""
    entries = [
        ["gemini", {"_angle": "Same question", "report": "one"}],
        ["gemini", {"_angle": "Same question", "report": "two"}],
    ]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    slug = _sanitize("Same question", max_len=60)
    assert _research_files(zf) == [
        f"research/01-{slug}-gemini.md",
        f"research/01-{slug}-gemini-2.md",
    ]


def test_path_traversal_angle_stays_single_entry():
    """A traversal angle/provider stays one flat entry under research/ (T-09-02)."""
    entries = [["../x", {"_angle": "../../etc/passwd", "report": "p"}]]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    files = _research_files(zf)
    assert len(files) == 1, files
    f = files[0]
    assert f.startswith("research/")
    assert ".." not in f
    assert f.count("/") == 1


def test_accented_angle_readable_slug():
    """Accents fold to ASCII and the slug is capped at 60 chars."""
    import unicodedata

    angle = "Quelle est la stratégie de croissance à l'étranger ?"
    entries = [["claude", {"_angle": angle, "report": "x"}]]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    (f,) = _research_files(zf)
    assert "Quelle_est_la_strategie" in f
    assert " " not in f
    assert not any(unicodedata.combining(c) for c in unicodedata.normalize("NFD", f))
    stem = f[len("research/01-") : -len("-claude.md")]
    assert len(stem) <= 60, stem


def test_header_names_questions_and_provider():
    """The header names angle, sub-question, client question, sub_questions, provider."""
    entries = [
        [
            "openai",
            {
                "_angle": "Main angle question",
                "_sub_question": "A narrower sub question",
                "_client_question": "The client's original question",
                "sub_questions": ["q1", "q2"],
                "report": "BODY",
            },
        ],
        [
            "gemini",
            {
                "_angle": "Second angle",
                "_sub_question": "Second angle",
                "report": "BODY2",
            },
        ],
    ]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    files = _research_files(zf)
    header = _split(zf, files[0])[0].decode("utf-8")
    for piece in (
        "Main angle question",
        "A narrower sub question",
        "The client's original question",
        "q1",
        "q2",
        "openai",
    ):
        assert piece in header, piece
    header2 = _split(zf, files[1])[0].decode("utf-8")
    assert header2.count("Second angle") == 1, header2
    assert "Sub-question" not in header2
    assert "gemini" in header2


def test_index_md_lists_files_in_zip_order():
    """research/index.md lists every research file, in zip order, with question + provider."""
    entries = [
        ["gemini", {"_angle": "Alpha question", "_corroboration_key": "a", "report": "1"}],
        ["openai", {"_angle": "Alpha question", "_corroboration_key": "a", "report": "2"}],
        ["claude", {"_angle": "Beta | question", "_corroboration_key": "b", "report": "3"}],
        ["gemini", "plain"],
    ]
    zf = _read_zip(build_bundle_zip({"markdown": "r"}, {"cleaned_reports": entries}, []))
    files = _research_files(zf)
    assert len(files) == 4
    index = zf.read("research/index.md").decode("utf-8")
    positions = []
    rows = {}
    for f in files:
        short = f[len("research/") :]
        assert short in index, short
        positions.append(index.index(short))
        rows[f] = next(line for line in index.splitlines() if short in line)
    assert positions == sorted(positions)
    assert "Alpha question" in rows[files[0]] and "gemini" in rows[files[0]]
    assert "Alpha question" in rows[files[1]] and "openai" in rows[files[1]]
    assert "Beta \\| question" in rows[files[2]] and "claude" in rows[files[2]]
    assert "(not recorded)" in rows[files[3]]
    names = [i.filename for i in zf.infolist()]
    assert names.index("research/index.md") == len(names) - 2
    assert names[-1] == "sources.json"


# --- quick 260925-fqt: the engine hands over a 120-char LABEL; show the full question ---

_FULL_Q = (
    "Welke fuel retailers in Europa passen vandaag dynamic pricing toe op brandstof en/of "
    "shopproducten, hoe wordt dit operationeel en commercieel ingezet, en welk model past?"
)


def _zip_names_and_read(report_md, entries):
    zf = zipfile.ZipFile(io.BytesIO(build_bundle_zip({"markdown": report_md}, {"cleaned_reports": entries}, [])))
    return zf


def test_cut_label_is_expanded_from_report_heading():
    label = _FULL_Q[:120]
    report_md = f"## Managementsamenvatting\n\ntext\n\n## {_FULL_Q}\n\nbody\n"
    zf = _zip_names_and_read(report_md, [["gemini", {"report": "R", "_angle": label}]])
    research = [n for n in zf.namelist() if n.startswith("research/") and n != "research/index.md"]
    assert len(research) == 1
    # file name still uses the SHORT slug (length-capped)
    assert len(research[0]) < 120
    body = zf.read(research[0]).decode("utf-8")
    assert f"**Question:** {_FULL_Q}\n" in body
    assert body.endswith("R")
    assert _FULL_Q in zf.read("research/index.md").decode("utf-8")


def test_short_label_never_expands():
    report_md = "## general market overview and much more text here\n\nbody\n"
    zf = _zip_names_and_read(report_md, [["gemini", {"report": "R", "_angle": "general"}]])
    name = [n for n in zf.namelist() if n.startswith("research/0")][0]
    assert "**Question:** general\n" in zf.read(name).decode("utf-8")


def test_cut_label_without_matching_heading_stays_as_is():
    label = _FULL_Q[:120]
    zf = _zip_names_and_read("## Something else\n", [["gemini", {"report": "R", "_angle": label}]])
    name = [n for n in zf.namelist() if n.startswith("research/0")][0]
    assert f"**Question:** {label}\n" in zf.read(name).decode("utf-8")
