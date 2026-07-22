"""Pure raw-output bundle builder (RUN-03 / D-03) — the immutable snapshot layout.

When a completed Tribunal run's audit chain VERIFIES, the poll driver
(:mod:`app.research.run_task`, Plan 02) materializes a zip snapshot of the run's
raw output to GCS ONCE. This module owns the zip LAYOUT and NOTHING else: given
the report, the scrubbed per-provider ``cleaned_reports`` bundle, and the sources
list, it returns the zip bytes. The caller is responsible for all I/O (fetching
the pieces from the seam, uploading the bytes to GCS, persisting the key).

D-03 layout — exactly three kinds of entry:

    report.md                        # the synthesized report (standalone → feeds
                                     #   the Phase-18 Claude-Design PDF)
    research/<sanitized-angle>.md    # one per cleaned_reports pair
    sources.json                     # json.dumps of the sources list

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


def build_bundle_zip(report: dict, bundle: dict, sources: list) -> bytes:
    """Return the raw-output zip bytes in the D-03 layout (pure — no I/O).

    ``report``  — the report dict; ``report.get("markdown")`` is written verbatim
                  to ``report.md``. The CALLER (Plan 02) is responsible for passing
                  a report dict whose ``markdown`` is the persisted
                  ``output_markdown`` when the live seam response lacks it (the live
                  report endpoint returns ``sections``, not ``markdown`` — Open Q1);
                  this builder just reads ``report.get("markdown")`` and falls back
                  to an empty string.
    ``bundle``  — ``{"cleaned_reports": [[name, {"report": text}], ...]}`` (the
                  D-01-scrubbed per-provider research). Each pair yields
                  ``research/<sanitize_filename(name)>.md`` with ``text`` as body. A
                  result that is not a dict is coerced to ``str``. A missing/empty
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

        for name, result in (bundle.get("cleaned_reports") or []):
            safe = sanitize_filename(str(name))
            text: Any = result.get("report") if isinstance(result, dict) else str(result)
            zf.writestr(f"research/{safe}.md", text or "")

        zf.writestr(
            "sources.json",
            json.dumps(sources, ensure_ascii=False, indent=2),
        )
    return buf.getvalue()
