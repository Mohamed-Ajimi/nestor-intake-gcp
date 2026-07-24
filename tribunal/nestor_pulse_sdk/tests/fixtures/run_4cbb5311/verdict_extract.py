"""
verdict_extract -- parse emit_group_verdict JSON out of the committed
group_skeptic call extracts (Phase 15 ENGINE-09, blocker-3 fix).

The committed selection-experiment TSVs carry gate-BUCKET counts, NOT the
per-claim verdict shape. The verdict shape only exists in the group_skeptic
call extracts under
`docs/tribunal-run-reports/run-20260722-4cbb5311/calls/`. Each such extract
(header `# Call NNN - group_skeptic`, roughly 047 onward) contains a fenced
`_TOOL CALL -> emit_group_verdict:_` block whose JSON is the EXACT
`_parse_group_verdict` shape:

    {
      "verdicts": [{"claim_index": int, "verdict": "support|refute|insufficient",
                    "confidence": float, ...}, ...],
      "reconciliation": {"disputed": bool, "relation": str, "note": str,
                         "canonical": str},
      "evidence_refs": ["url — quote", ...]
    }

`extract_group_verdicts(calls_dir)` walks those extracts and returns one flat
dict per emitted verdict, carrying:
  verdict, confidence (stringified), evidence_refs (the group's JSON array),
  reconciliation (the group's JSON object -- disputed/relation/note/canonical),
  audit_id (the call's audit-record id, from the extract header),
  claim_index (the group-local index).

This is the source of truth the loader seeds verification_verdict rows from --
no GCS pull needed. (If a downstream agent ever needs raw blobs instead, they
are permanent at gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/
9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/, but the committed calls/ extracts
already carry the full verdict payload, so this module has NO GCS dependency.)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

# Header markers in the committed extracts.
_GROUP_SKEPTIC_HEADER = re.compile(r"^#\s*Call\s+(\d+)\s*-\s*group_skeptic", re.MULTILINE)
_AUDIT_ID = re.compile(r"^-\s*\*\*audit_id:\*\*\s*([0-9a-fA-F-]{36})", re.MULTILINE)
# The fenced emit_group_verdict tool-call block: capture the ```json ... ``` body.
_EMIT_BLOCK = re.compile(
    r"_TOOL CALL -> emit_group_verdict:_\s*```json\s*(\{.*?\})\s*```",
    re.DOTALL,
)


def _parse_one_extract(text: str) -> list[dict[str, Any]]:
    """Parse a single group_skeptic extract's emit_group_verdict block into rows.

    Returns [] if the extract has no group_skeptic header or no emit block (e.g.
    the ~24 rows the recorded run flagged BUG:recon-as-str, where the payload
    was malformed and the pipeline discarded the verdicts -- we skip those too).
    """
    if not _GROUP_SKEPTIC_HEADER.search(text):
        return []

    audit_match = _AUDIT_ID.search(text)
    audit_id = audit_match.group(1) if audit_match else None

    block_match = _EMIT_BLOCK.search(text)
    if not block_match:
        return []

    try:
        payload = json.loads(block_match.group(1))
    except (json.JSONDecodeError, ValueError):
        # Malformed emit payload (the recorded BUG:recon-as-str rows) -- skip,
        # exactly as the live pipeline discarded them.
        return []

    reconciliation = payload.get("reconciliation")
    # Guard against the recorded reconciliation-as-string bug: only pass a dict
    # through as the JSONB reconciliation object.
    if not isinstance(reconciliation, dict):
        reconciliation = None

    evidence_refs = payload.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        evidence_refs = None

    rows: list[dict[str, Any]] = []
    for v in payload.get("verdicts", []):
        if not isinstance(v, dict) or "verdict" not in v:
            continue
        confidence = v.get("confidence")
        rows.append(
            {
                "verdict": v["verdict"],
                "confidence": None if confidence is None else str(confidence),
                "evidence_refs": evidence_refs,
                "reconciliation": reconciliation,
                "audit_id": audit_id,
                "claim_index": v.get("claim_index"),
            }
        )
    return rows


def extract_group_verdicts(calls_dir: str | Path) -> list[dict[str, Any]]:
    """Parse every committed group_skeptic call extract into verdict rows.

    Arguments:
      calls_dir: path to
        docs/tribunal-run-reports/run-20260722-4cbb5311/calls/

    Returns a flat list of verdict-row dicts (see module docstring), ordered by
    call-file name (which is the recorded execution order -- files are named
    NNN-provider-model.md with a zero-padded monotonic prefix).
    """
    calls_path = Path(calls_dir)
    rows: list[dict[str, Any]] = []
    for md in sorted(calls_path.glob("*.md")):
        rows.extend(_parse_one_extract(md.read_text(encoding="utf-8")))
    return rows
