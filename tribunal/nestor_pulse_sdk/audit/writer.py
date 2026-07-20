"""DB-backed audit writer -- persists audit_log rows via SQLAlchemy AsyncSession.

Implements the audit_writer protocol consumed by AuditedLLMClient (Plan 07):
  - get_prev_hash_and_seq(run_id) -> (prev_hash, seq)
  - insert_placeholder(...)       -> writes hash=IN_FLIGHT_PLACEHOLDER row
  - finalize_row(...)              -> UPDATE row from placeholder to real hash
  - write_full_row(...)            -> single INSERT for atomic-call path

Each method opens its own AsyncSession + transaction via the injected
sessionmaker. The tenant_id is SET LOCAL inside that transaction so RLS
applies even when the audit write runs outside the worker's main session
(Autonomous Transaction pattern -- 01-RESEARCH.md Anti-pattern line 584:
the audit row commits even if the LLM-using transaction rolls back).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from nestor_pulse_sdk.audit.hash_chain import GENESIS, IN_FLIGHT_PLACEHOLDER
from nestor_pulse_sdk.db.rls import set_tenant_context


class DBAuditWriter:
    """SQLAlchemy AsyncSession-backed audit_log writer.

    Constructor:
      sessionmaker: async_sessionmaker[AsyncSession] from get_sessionmaker().
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sm = sessionmaker

    async def get_prev_hash_and_seq(
        self, run_id: uuid.UUID, tenant_id: uuid.UUID
    ) -> Tuple[str, int]:
        """Return (prev_hash, next_seq) for the chain tail of `run_id`.

        For a fresh run with no rows: returns (GENESIS, 1).
        Otherwise: returns (latest_row.hash, latest_row.seq + 1).

        audit_log is FORCE-RLS, and this method opens its OWN session (the
        Autonomous Transaction pattern), so the caller's tenant context does
        NOT carry over. We MUST set the tenant context on this session before
        the read -- otherwise current_setting('app.tenant_id')::uuid either
        raises "unrecognized configuration parameter" (fresh connection) or,
        on a pooled connection where a prior txn defined the GUC, casts ''
        and raises "invalid input syntax for type uuid". Found by the Plan
        01-16 live e2e (unit tests use a fake writer with no RLS).
        """
        async with self._sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                result = await session.execute(
                    text(
                        "SELECT hash, seq FROM audit_log "
                        "WHERE run_id = :rid "
                        "ORDER BY seq DESC LIMIT 1"
                    ),
                    {"rid": str(run_id)},
                )
                row = result.first()
                if row is None:
                    return GENESIS, 1
                return row.hash, row.seq + 1

    async def insert_placeholder(
        self,
        *,
        audit_id: uuid.UUID,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        seq: int,
        prev_hash: str,
        provider: str,
        model: str,
        started_at: datetime,
    ) -> None:
        """Insert a row with hash=IN_FLIGHT_PLACEHOLDER for a long-running call.

        The row is finalized by `finalize_row()` when the call returns. If
        the worker crashes before finalize, the placeholder stays in place
        and `verify_chain()` reports a chain break at this row.
        """
        async with self._sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                await session.execute(
                    text(
                        "INSERT INTO audit_log ("
                        "id, tenant_id, run_id, seq, provider, model, "
                        "started_at, duration_ms, prompt_tokens, "
                        "completion_tokens, cached_tokens, cost_usd, "
                        "gcs_uri, prev_hash, hash"
                        ") VALUES ("
                        ":id, :tid, :rid, :seq, :provider, :model, "
                        ":started_at, 0, 0, 0, 0, NULL, "
                        "'pending://in-flight', :prev_hash, :hash"
                        ")"
                    ),
                    {
                        "id": str(audit_id),
                        "tid": str(tenant_id),
                        "rid": str(run_id),
                        "seq": seq,
                        "provider": provider,
                        "model": model,
                        "started_at": started_at,
                        "prev_hash": prev_hash,
                        "hash": IN_FLIGHT_PLACEHOLDER,
                    },
                )

    async def finalize_row(
        self,
        *,
        audit_id: uuid.UUID,
        tenant_id: uuid.UUID,
        hash: str,
        prev_hash: str,
        gcs_uri: str,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int,
        cost_usd: Optional[Decimal],
        started_at: datetime,
    ) -> None:
        """UPDATE a placeholder row to its finalized values.

        Defense in depth: the WHERE clause requires hash=IN_FLIGHT_PLACEHOLDER
        so a double-finalize is a no-op rather than a chain rewrite.

        audit_log is FORCE-RLS and this opens its own session, so set the tenant
        context before the UPDATE (the USING clause reads app.tenant_id). Without
        it the two-phase end_call path raised on every deep-research finalize —
        found by the Plan 01-16 live e2e (sibling of the get_prev_hash_and_seq fix).
        """
        async with self._sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                await session.execute(
                    text(
                        "UPDATE audit_log SET "
                        "hash = :hash, "
                        "gcs_uri = :gcs_uri, "
                        "duration_ms = :duration_ms, "
                        "prompt_tokens = :prompt_tokens, "
                        "completion_tokens = :completion_tokens, "
                        "cached_tokens = :cached_tokens, "
                        "cost_usd = :cost_usd "
                        "WHERE id = :audit_id "
                        "AND hash = :placeholder"
                    ),
                    {
                        "hash": hash,
                        "gcs_uri": gcs_uri,
                        "duration_ms": duration_ms,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cached_tokens": cached_tokens,
                        "cost_usd": cost_usd,
                        "audit_id": str(audit_id),
                        "placeholder": IN_FLIGHT_PLACEHOLDER,
                    },
                )

    async def write_full_row(
        self,
        *,
        audit_id: uuid.UUID,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        seq: int,
        provider: str,
        model: str,
        started_at: datetime,
        duration_ms: int,
        prompt_tokens: int,
        completion_tokens: int,
        cached_tokens: int,
        cost_usd: Optional[Decimal],
        gcs_uri: str,
        prev_hash: str,
        hash: str,
    ) -> None:
        """Atomic single-INSERT path for synthesis-step calls that finish in seconds."""
        async with self._sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                await session.execute(
                    text(
                        "INSERT INTO audit_log ("
                        "id, tenant_id, run_id, seq, provider, model, "
                        "started_at, duration_ms, prompt_tokens, "
                        "completion_tokens, cached_tokens, cost_usd, "
                        "gcs_uri, prev_hash, hash"
                        ") VALUES ("
                        ":id, :tid, :rid, :seq, :provider, :model, "
                        ":started_at, :duration_ms, :prompt_tokens, "
                        ":completion_tokens, :cached_tokens, :cost_usd, "
                        ":gcs_uri, :prev_hash, :hash"
                        ")"
                    ),
                    {
                        "id": str(audit_id),
                        "tid": str(tenant_id),
                        "rid": str(run_id),
                        "seq": seq,
                        "provider": provider,
                        "model": model,
                        "started_at": started_at,
                        "duration_ms": duration_ms,
                        "prompt_tokens": prompt_tokens,
                        "completion_tokens": completion_tokens,
                        "cached_tokens": cached_tokens,
                        "cost_usd": cost_usd,
                        "gcs_uri": gcs_uri,
                        "prev_hash": prev_hash,
                        "hash": hash,
                    },
                )
