"""
nestor_pulse_sdk.audit.verifier -- hash chain verification endpoint logic.

Design (D-13 + Anti-pattern line 585):
  - verify_chain_endpoint() is the sole entry point for chain verification.
  - Returns {"ok": bool, "broken_at": int | None}.
  - Client NEVER recomputes hashes -- server-side only.
  - Called by GET /api/audit/verify/{run_id} in api.py.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional


async def verify_chain_endpoint(
    run_id: uuid.UUID,
    session: Any,
) -> dict:
    """
    Verify the hash chain for a run, server-side.

    Per D-13: the client receives only {ok, broken_at?}.
    Raw hashes are NEVER included in the response (Anti-pattern line 585).

    Returns:
        {"ok": True, "broken_at": None}  -- chain intact
        {"ok": False, "broken_at": int}  -- first broken row (0-indexed seq)
    """
    from nestor_pulse_sdk.audit.hash_chain import verify_chain

    ok, broken_at = await verify_chain(run_id, session)
    return {"ok": ok, "broken_at": broken_at}
