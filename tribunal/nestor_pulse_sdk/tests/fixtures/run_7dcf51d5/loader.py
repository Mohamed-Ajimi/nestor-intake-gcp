"""
run_7dcf51d5 fixture loader -- the four RECORDED distiller responses from V-01
(run 7dcf51d5, 2026-07-28), committed so the `<TAB>` defect has a real
regression fixture (Phase 15.4, plan 15.4-01).

WHY THIS FIXTURE EXISTS
-----------------------
V-01 delivered a client report whose coffee section stated the Benelux data
"geeft geen volledig beeld". That statement was FALSE. The distiller had
returned 278 well-formed coffee claims and `_parse_distiller_response` threw
away every one of them, because the model wrote the literal five-character
string `<TAB>` instead of U+0009 -- and the prompt itself used `<TAB>` as a
placeholder DESCRIBING the separator. The only trace was a `log.debug`, which
production does not serve.

These four responses are the evidence. Two of them are the loss; two are the
control:

    e9a168b5  idx 12  literal `<TAB>` x141, real tabs 0  -> 141 claims LOST
    fe418029  idx 16  literal `<TAB>` x137, real tabs 0  -> 137 claims LOST
    af1995b6  idx  8  literal `<TAB>`   x0, real tabs 43 ->  43 claims kept
    7dcf4a14  idx  8  literal `<TAB>`   x0, real tabs 143 -> 143 claims kept

141 + 137 = 278 = `COFFEE_EXPECTED_CLAIMS`, the number the delivered report was
missing. The split is perfectly disjoint: no response mixes the two separators.

The two already-working responses are as important as the two broken ones. A
separator fix that recovers 278 while quietly changing 43 or 143 is a
regression, not a fix, and only the control pair can show that.

PROVENANCE
----------
Pulled 2026-07-29 from the per-call audit bucket:

    gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/
    7dcf51d5-1153-4374-b444-c25d17eeea01/

The four distiller calls are those written in the 13:46:33Z-13:48:30Z window.
Full forensics: `docs/tribunal-run-reports/run-20260728-7dcf51d5-DIAGNOSTICS.md`.

ONLY THE `response` HALF IS COMMITTED. The `request` half was never downloaded.
That is deliberate: the SerpApi key rides in a QUERY PARAMETER, and key-based
audit redaction (`audit/gcs_blob.py` `_DEFAULT_REDACT_KEYS`) covers header and
body KEYS only -- it cannot catch a credential inside a URL query string. An
unredacted request blob would freeze a live credential into this repo under
7-year retention.

CREDENTIAL SCAN -- run 2026-07-29 over all four texts, recorded verbatim:

    grep -icE '(api[_-]?key|apikey|serpapi|x-goog-api-key|authorization|secret|AIza)'
        7dcf4a14: 0   af1995b6: 0   e9a168b5: 0   fe418029: 0

    grep -cE '[?&](key|token|api[_-]?key)='
        7dcf4a14: 0   af1995b6: 0   e9a168b5: 0   fe418029: 0

Both scanners were additionally run against a planted `?api_key=LIVE123` control
line and returned 1 -- so the zeros above are a real result, not a dead regex.
Operator reviewed the scan output and approved the commit on 2026-07-29.

NO GCS AT TEST TIME. This module never constructs a storage client; the bucket
path above is recorded for lineage only. Same convention as the sibling
`run_4cbb5311` fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Lineage only -- the loader never reads GCS.
RECORDED_RUN_ID = "7dcf51d5-1153-4374-b444-c25d17eeea01"
RECORDED_AUDIT_BUCKET = (
    "gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/"
    f"{RECORDED_RUN_ID}/"
)

_RESPONSES_DIR = Path(__file__).parent / "responses"


@dataclass(frozen=True)
class DistillerCall:
    """One recorded distiller call, with the counts it MUST reproduce."""

    audit_prefix: str
    filename: str
    report_idx: int
    separator: str        # "<TAB>" (the defect) or "\t" (the control)
    non_empty_lines: int
    expected_claims: int


# The manifest. These numbers are RECORDED FACTS reconciled against
# run-20260728-7dcf51d5-DIAGNOSTICS.md at pull time -- they are not targets to
# be adjusted. If a parser change makes any of them unreachable, the parser is
# wrong, not the manifest.
DISTILLER_CALLS: tuple[DistillerCall, ...] = (
    DistillerCall(
        audit_prefix="e9a168b5",
        filename="e9a168b5-idx12-coffee.txt",
        report_idx=12,
        separator="<TAB>",
        non_empty_lines=141,
        expected_claims=141,
    ),
    DistillerCall(
        audit_prefix="fe418029",
        filename="fe418029-idx16-coffee.txt",
        report_idx=16,
        separator="<TAB>",
        non_empty_lines=137,
        expected_claims=137,
    ),
    DistillerCall(
        audit_prefix="af1995b6",
        filename="af1995b6-idx08-chunk2.txt",
        report_idx=8,
        separator="\t",
        non_empty_lines=43,
        expected_claims=43,
    ),
    DistillerCall(
        audit_prefix="7dcf4a14",
        filename="7dcf4a14-idx08-chunk1.txt",
        report_idx=8,
        separator="\t",
        non_empty_lines=143,
        expected_claims=143,
    ),
)

# 141 + 137. The coffee claims the engine extracted, discarded on a string
# comparison, and then told the client it did not have. This is the number the
# delivered V-01 report was missing.
COFFEE_EXPECTED_CLAIMS = 278


def load_distiller_response(audit_prefix: str) -> str:
    """Return one recorded response text by its audit-id prefix.

    Raises `KeyError` for an unknown prefix and `FileNotFoundError` when the
    committed file is missing -- never returns "" for either, because an empty
    string would sail through a downstream parser and prove nothing.
    """
    for call in DISTILLER_CALLS:
        if call.audit_prefix == audit_prefix:
            path = _RESPONSES_DIR / call.filename
            if not path.is_file():
                raise FileNotFoundError(
                    f"run_7dcf51d5 fixture: {call.filename} is missing from "
                    f"{_RESPONSES_DIR}. The fixture is incomplete; do not run "
                    f"the replay proof against a partial corpus."
                )
            return path.read_text(encoding="utf-8")
    raise KeyError(
        f"run_7dcf51d5 fixture: no recorded distiller call with prefix "
        f"{audit_prefix!r}. Known prefixes: "
        f"{[c.audit_prefix for c in DISTILLER_CALLS]}"
    )


def load_all() -> list[tuple[str, str]]:
    """Return (audit_prefix, text) for all four calls, in `DISTILLER_CALLS` order.

    RAISES when the number of response files found on disk is not exactly 4.

    THAT RAISE IS THE POINT, and it is the `ls || true` silent-skip trap in
    fixture clothing. A loader that quietly returns three rows -- or zero --
    makes every downstream assertion VACUOUS: the replay test would iterate an
    empty list, assert nothing, and report green. This repo has already been
    bitten by a gate that passed because its file list was empty. A fixture that
    cannot find its data must fail loudly, exactly like the WARNING this whole
    phase adds to the distiller.
    """
    found = sorted(p.name for p in _RESPONSES_DIR.glob("*.txt"))
    expected = sorted(c.filename for c in DISTILLER_CALLS)
    if found != expected:
        raise RuntimeError(
            f"run_7dcf51d5 fixture is incomplete: expected exactly "
            f"{len(expected)} response files {expected}, found {len(found)} "
            f"{found}. Refusing to return a partial corpus -- a short fixture "
            f"makes the 278-claim replay proof vacuous rather than failing."
        )
    return [
        (call.audit_prefix, load_distiller_response(call.audit_prefix))
        for call in DISTILLER_CALLS
    ]
