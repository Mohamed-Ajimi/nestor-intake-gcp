"""
nestor_pulse_sdk.audit.hash_chain -- SHA-256 hash chain for tamper-evident audit log.

Design:
  - canonical_json: pinned serialization spec (Pitfall 3 -- no drift across deploys).
    sort_keys=True, separators=(",",":"), ensure_ascii=False, allow_nan=False.
    Use the SAME function for WRITE and VERIFY. If switching to RFC 8785 (jcs lib),
    do so atomically and bump the chain version field.
  - link_hash(prev_hash, payload): SHA-256 over (prev_hash bytes || canonical_json(payload) bytes).
  - GENESIS = "0" * 64: the sentinel prev_hash for the first row in every run.
  - IN_FLIGHT_PLACEHOLDER = "i" * 64: the hash written by start_call before end_call
    finalizes. verify_chain reports a chain break at any row with this placeholder
    (worker crash recovery -- T-07-10).
  - verify_chain(run_id, session): server-side recompute per D-13.
    Client NEVER recomputes (Anti-pattern line 585 in RESEARCH).

Pitfall 3 -- canonical JSON drift:
  The payload dict is defined in _payload_for_row(). This set of fields MUST
  stay frozen forever once the first audit row is written to a production run.
  Any schema change to this set breaks all existing chains and requires a
  migration plan + chain version bump.

RESEARCH lines 742-771 verbatim implementation.
"""

from __future__ import annotations

import hashlib
import json


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENESIS: str = "0" * 64
"""The sentinel prev_hash for the first audit row in every run."""

IN_FLIGHT_PLACEHOLDER: str = "i" * 64
"""
Written by start_call before end_call finalizes the row.
verify_chain reports a chain break at any row with this value (T-07-10).
"""


# ---------------------------------------------------------------------------
# Canonical JSON serialization (Pitfall 3 -- pinned spec)
# ---------------------------------------------------------------------------

def canonical_json(obj) -> bytes:
    """
    Deterministic JSON serialization per Pitfall 3. Pinned spec:
      - sort_keys=True            (field order independent)
      - separators=(',', ':')    (no whitespace -- no formatting drift)
      - ensure_ascii=False        (UTF-8 native; no \\uXXXX escapes for Unicode)
      - allow_nan=False           (NaN/Inf rejected -- forbid both per Pitfall 3)

    Use the SAME function for WRITE (AuditedLLMClient) and VERIFY (verify_chain).
    If switching to RFC 8785 (jcs lib), do so atomically + bump chain version.
    """
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Hash chain link computation
# ---------------------------------------------------------------------------

def link_hash(prev_hash: str, payload: dict) -> str:
    """
    Compute the next hash in the chain.

    Algorithm:
      SHA-256(prev_hash.encode("ascii") || canonical_json(payload))

    prev_hash is ASCII hex (64 chars for SHA-256), so encode("ascii") is safe.
    canonical_json ensures deterministic serialization (Pitfall 3).
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(canonical_json(payload))
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Chain verification (server-side ONLY -- D-13 + Anti-pattern line 585)
# ---------------------------------------------------------------------------

async def verify_chain(run_id, session) -> tuple[bool, int | None]:
    """
    Server-side hash chain recompute for run_id.

    Per D-13: client receives only {ok, broken_at?} -- never raw hashes.
    This function is called by the verifier endpoint; clients NEVER call it.

    Algorithm:
      1. Fetch all audit_log rows for run_id ordered by seq ASC.
      2. Walk rows: check prev_hash chain link and recompute each hash.
      3. Return (True, None) if all rows verify; (False, i) at first break.

    Orphaned in_flight rows (crash recovery T-07-10):
      Any row with hash == IN_FLIGHT_PLACEHOLDER is treated as a chain break
      at that row index.
    """
    from nestor_pulse_sdk.db.models.audit_log import AuditLog
    from sqlalchemy import select

    stmt = (
        select(AuditLog)
        .where(AuditLog.run_id == run_id)
        .order_by(AuditLog.seq.asc())
    )
    rows = (await session.execute(stmt)).scalars().all()

    expected_prev = GENESIS
    for i, row in enumerate(rows):
        # Orphaned in_flight row (worker crashed between start_call and end_call) -- chain break
        if row.hash == IN_FLIGHT_PLACEHOLDER:
            return False, i

        if row.prev_hash != expected_prev:
            return False, i

        payload = _payload_for_row(row)
        recomputed = link_hash(row.prev_hash, payload)
        if recomputed != row.hash:
            return False, i

        expected_prev = row.hash

    return True, None


def _payload_for_row(row) -> dict:
    """
    The exact subset of audit_log columns that was canonical_json-hashed at write time.

    MUST stay frozen for the chain to verify across deploys (Pitfall 3).
    Any change to this set requires a chain version migration + re-hash of all
    existing rows (or accept a chain break at the migration boundary).

    Note: run_id may be None for pre-run audit rows (e.g. auth events).
    """
    return {
        "provider": row.provider,
        "model": row.model,
        "started_at": row.started_at.isoformat(),
        "duration_ms": row.duration_ms,
        "prompt_tokens": row.prompt_tokens,
        "completion_tokens": row.completion_tokens,
        "cached_tokens": row.cached_tokens,
        "gcs_uri": row.gcs_uri,
        "seq": row.seq,
        "tenant_id": str(row.tenant_id),
        "run_id": str(row.run_id) if row.run_id else None,
    }
