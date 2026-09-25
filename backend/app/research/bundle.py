"""Pure raw-output bundle builder (RUN-03 / D-03) — the immutable snapshot layout.

When a completed Tribunal run's audit chain VERIFIES, the poll driver
(:mod:`app.research.run_task`, Plan 02) materializes a zip snapshot of the run's
raw output to GCS ONCE. This module owns the zip LAYOUT and NOTHING else: given
the report, the scrubbed per-provider ``cleaned_reports`` bundle, and the sources
list, it returns the zip bytes. The caller is responsible for all I/O (fetching
the pieces from the seam, uploading the bytes to GCS, persisting the key).

D-03 layout — four kinds of entry, in this order:

    report.md                        # the synthesized report (standalone → feeds
                                     #   the Phase-18 Claude-Design PDF)
    research/<NN>-<question-slug>-<provider>.md
                                     # one per cleaned_reports pair; NN is shared by
                                     #   the providers of one angle; falls back to
                                     #   research/<NN>-<provider>.md when the entry
                                     #   carries no angle; a -2/-3 suffix dedupes
    research/index.md                # table of every research file (only when at
                                     #   least one research file was written)
    sources.json                     # json.dumps of the sources list

260925-dyt: entries used to be named ``research/<provider>.md``. ``cleaned_reports``
holds one pair per (angle, provider), so the names collided (a 15-entry bundle had 3
distinct names) and extractors dropped up to 12 of 15 reports — measured on all 13
prod bundles on 2026-09-25. Every entry name is now unique.

D-01 (discredited-content scrub): the builder receives ``cleaned_reports`` ONLY —
the Tribunal ``/research-bundle`` endpoint (Plan 01) already excludes
``rejected_claims`` at the boundary. This module does NOT accept, read, or write
any rejected-claims argument, so the ledger is STRUCTURALLY absent from the zip.

Pure module: no I/O, no GCS, no DB, no httpx — same discipline as
:mod:`app.storage.keys` ("safe to import anywhere"). Provider names are
engine-derived, so the entry filenames go through the SHARED
:func:`app.storage.keys.sanitize_filename` (never a hand-rolled sanitizer) — the
same path-traversal kill switch every stored name uses (T-09-02).

Authoritative references:
- .planning/phases/17-raw-output-audit-chain-guard/17-PATTERNS.md § bundle.py
- .planning/phases/17-raw-output-audit-chain-guard/17-RESEARCH.md § Code Examples
- app/storage/keys.py (the pure no-I/O module analog + sanitize_filename)
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

from app.storage.keys import sanitize_filename


def _str_field(meta: dict, key: str) -> str:
    """Return ``meta[key]`` stripped when it is a non-empty string, else ``""``."""
    value = meta.get(key)
    return value.strip() if isinstance(value, str) else ""


def _collapse(text: str) -> str:
    """Collapse every whitespace run (newlines included) to one space."""
    return " ".join(text.split())


def _md_cell(text: str) -> str:
    """Make ``text`` safe for one markdown table cell."""
    return _collapse(text).replace("|", "\\|")


#: A question label arrives from the engine cut at 120 characters (it is the engine's
#: join key, ``workshop._LABEL_MAX_CHARS``, and must stay short there). The full
#: question is still in the bundle: each client question is a ``## `` chapter heading
#: of ``report.md``, and a label is a PREFIX of its question by construction. Only a
#: label this long can have been cut, so a short label like "general" never expands.
_MIN_TRUNCATED_LABEL = 100


def _report_headings(markdown: str) -> list[str]:
    """The collapsed text of every ``## `` heading in the report markdown."""
    out = []
    for line in (markdown or "").splitlines():
        if line.startswith("## "):
            text = _collapse(line[3:])
            if text:
                out.append(text)
    return out


def _full_question(label: str, headings: list[str]) -> str:
    """The untruncated question for a cut-off label, else the label unchanged.

    Display only: file names keep using the short label.
    """
    short = _collapse(label)
    if len(short) < _MIN_TRUNCATED_LABEL:
        return short
    for heading in headings:
        if len(heading) > len(short) and heading.startswith(short):
            return heading
    return short


def _header(nn: str, angle: str, meta: dict, provider: str, question: str = "") -> str:
    """The short markdown header placed before a research report body.

    ``question`` is the display text for ``angle`` (the full question when the label
    was cut); it defaults to the collapsed label.
    """
    lines = [f"# Research report {nn}", ""]
    if angle:
        lines.append(f"**Question:** {question or _collapse(angle)}")
    sub = _str_field(meta, "_sub_question")
    if sub and sub != angle:
        lines.append(f"**Sub-question:** {_collapse(sub)}")
    client_q = _str_field(meta, "_client_question")
    if client_q and client_q != angle and client_q != sub:
        lines.append(f"**Client question:** {_collapse(client_q)}")
    subs = meta.get("sub_questions")
    if isinstance(subs, list) and subs:
        lines.append("**Sub-questions:**")
        for item in subs:
            text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
            lines.append(f"- {_collapse(text)}")
    lines.append(f"**Provider:** {provider}")
    return "\n".join(lines) + "\n\n---\n\n"


def _index(rows: list[tuple[str, str, str, str]]) -> str:
    """``research/index.md`` — one table row per research file, in write order."""
    out = [
        "# Research index",
        "",
        "Every per-provider research report in this bundle, with the question it answers.",
        "",
        "| # | File | Question | Provider |",
        "|---|------|----------|----------|",
    ]
    for nn, filename, question, provider in rows:
        out.append(
            f"| {nn} | {_md_cell(filename)} | {_md_cell(question) or '(not recorded)'} "
            f"| {_md_cell(provider)} |"
        )
    return "\n".join(out) + "\n"


def build_bundle_zip(report: dict, bundle: dict, sources: list) -> bytes:
    """Return the raw-output zip bytes in the D-03 layout (pure — no I/O).

    ``report``  — the report dict; ``report.get("markdown")`` is written verbatim
                  to ``report.md``. The CALLER (Plan 02) is responsible for passing
                  a report dict whose ``markdown`` is the persisted
                  ``output_markdown`` when the live seam response lacks it (the live
                  report endpoint returns ``sections``, not ``markdown`` — Open Q1);
                  this builder just reads ``report.get("markdown")`` and falls back
                  to an empty string.
    ``bundle``  — ``{"cleaned_reports": [[name, {"report": text, "_angle": ...}],
                  ...]}`` (the D-01-scrubbed per-(angle, provider) research). Each
                  pair yields one uniquely named
                  ``research/<NN>-<sanitize_filename(angle, max_len=60)>-<sanitize_filename(name)>.md``
                  (``research/<NN>-<provider>.md`` without an angle; ``-2``/``-3``
                  dedupe). NN groups by ``_corroboration_key`` (else ``_angle``). The
                  body is a short header naming the question(s) and provider, a
                  ``---`` separator, then ``text`` byte-identical. A result that is
                  not a dict is coerced to ``str`` and carries no metadata.
                  ``research/index.md`` lists every research file. A missing/empty
                  ``cleaned_reports`` yields NO ``research/`` entries (no crash).
    ``sources`` — written to ``sources.json`` via ``json.dumps(..., ensure_ascii=
                  False)`` so accented/unicode source titles stay literal.

    D-01: no rejected-claims argument exists — the discredited ledger cannot be
    written here even if a caller had it.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # report.md is standalone (feeds the Phase-18 PDF). Empty-string fallback
        # so the entry always exists even when markdown is missing/None.
        zf.writestr("report.md", report.get("markdown") or "")
        headings = _report_headings(report.get("markdown") or "")

        group_index: dict[str, int] = {}
        used: set[str] = set()
        rows: list[tuple[str, str, str, str]] = []  # (NN, filename, question, provider)
        counter = 0

        for name, result in (bundle.get("cleaned_reports") or []):
            if isinstance(result, dict):
                raw_body: Any = result.get("report") or ""
                body = raw_body if isinstance(raw_body, str) else str(raw_body)
                meta: dict = result
            else:
                body = str(result)
                meta = {}

            angle = _str_field(meta, "_angle")
            group_key = _str_field(meta, "_corroboration_key") or angle
            if group_key and group_key in group_index:
                idx = group_index[group_key]
            else:
                counter += 1
                idx = counter
                if group_key:
                    group_index[group_key] = idx
            nn = f"{idx:02d}"

            provider_raw = str(name)
            provider_seg = sanitize_filename(provider_raw)
            if angle:
                slug = sanitize_filename(angle, max_len=60)
                base = f"{nn}-{slug}-{provider_seg}"
            else:
                base = f"{nn}-{provider_seg}"
            candidate, n = base, 1
            while candidate in used:
                n += 1
                candidate = f"{base}-{n}"
            used.add(candidate)
            filename = f"{candidate}.md"

            question = _full_question(angle, headings) if angle else ""
            zf.writestr(
                f"research/{filename}", _header(nn, angle, meta, provider_raw, question) + body
            )
            rows.append((nn, filename, question, provider_raw))

        if rows:
            zf.writestr("research/index.md", _index(rows))

        zf.writestr(
            "sources.json",
            json.dumps(sources, ensure_ascii=False, indent=2),
        )
    return buf.getvalue()
