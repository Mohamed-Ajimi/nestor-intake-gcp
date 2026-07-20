"""Parse provider research reports into source + claim + claim_source rows.

D-07 three-table model:
  - source       : URL + snapshot_text + content_hash (per-tenant dedupe)
  - claim        : assertion text + facet + position
  - claim_source : many-to-many join (carries tenant_id for RLS)

PHASE 1 MINIMUM
---------------
The legacy ADK pipeline does fine-grained per-sentence claim extraction inside
the synthesis pipeline (RelevanceGate + TopicSynthesis). Plan 09 ships a
defensible coarse-grained extractor that:

  1. Parses URLs from each provider's `report` text (regex).
  2. Upserts a `source` row per (tenant_id, content_hash). content_hash is
     SHA-256 of the snapshot text (so identical-content URLs from different
     providers dedupe automatically).
  3. Writes ONE `claim` row per provider with the full report text as
     `claim.text` and `facet = provider_name`. Phase 2's RelevanceGate port
     will split this into many small claims and re-link claim_source rows.
  4. Links each claim to every source extracted from that provider's report.

This is enough to:
  - Satisfy the test_citation_roundtrip schema round-trip + dedupe tests.
  - Wire the GET /api/sources/{id} contract end-to-end (snapshot_text round-trips).
  - Avoid painting Plan 12's fine-grained extraction into a corner.

What this DOES NOT satisfy: the PHASE1-05 ">=95% citation recall on a >=50-claim
canonical run" gate. That metric requires per-sentence claims (Plan 12 closing
wave). test_citation_recall.py is parked as xfail until Plan 12 wires the
canonical run.
"""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.db.models import Claim, ClaimSource, Source
from nestor_pulse_sdk.db.rls import set_tenant_context

log = logging.getLogger(__name__)

# Lightweight URL pattern -- matches http(s):// up to whitespace, paren, or quote.
_URL_RE = re.compile(r"https?://[^\s)\"'<>\]]+", re.IGNORECASE)

# Cap the snapshot_text length to avoid persisting megabyte-scale provider blobs.
_SNAPSHOT_MAX_CHARS = 50_000


def _content_hash(text_value: str) -> str:
    """SHA-256 of the snapshot text (per-tenant dedupe key)."""
    return hashlib.sha256(text_value.encode("utf-8")).hexdigest()


def _extract_urls(report: str) -> list[str]:
    """Return de-duplicated URLs in the order they appear in `report`."""
    seen: set[str] = set()
    ordered: list[str] = []
    for match in _URL_RE.finditer(report or ""):
        url = match.group(0).rstrip(".,;:")
        if url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


async def _upsert_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    url: str,
    provider: str,
    snapshot_text: str,
) -> uuid.UUID:
    """INSERT a source row, deduping by (tenant_id, content_hash).

    Uses the partial UNIQUE index from migration 0003:
      idx_source_tenant_content_hash UNIQUE (tenant_id, content_hash)
      WHERE content_hash IS NOT NULL

    On conflict, returns the id of the existing row rather than the new uuid.
    """
    snapshot_capped = (snapshot_text or "")[:_SNAPSHOT_MAX_CHARS]
    chash = _content_hash(snapshot_capped) if snapshot_capped else None
    new_id = uuid.uuid4()

    if chash is None:
        # No snapshot to hash -- skip dedupe and insert plainly.
        await session.execute(
            text(
                "INSERT INTO source "
                "(id, tenant_id, url, provider, snapshot_text, content_hash) "
                "VALUES (:id, :tid, :url, :provider, :snapshot, NULL)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "url": url,
                "provider": provider,
                "snapshot": snapshot_capped or None,
            },
        )
        return new_id

    # Try INSERT; on conflict return existing row's id.
    result = await session.execute(
        text(
            "INSERT INTO source "
            "(id, tenant_id, url, provider, snapshot_text, content_hash) "
            "VALUES (:id, :tid, :url, :provider, :snapshot, :chash) "
            "ON CONFLICT (tenant_id, content_hash) "
            "WHERE content_hash IS NOT NULL DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": str(new_id),
            "tid": str(tenant_id),
            "url": url,
            "provider": provider,
            "snapshot": snapshot_capped,
            "chash": chash,
        },
    )
    row = result.first()
    if row is not None:
        return row.id

    # Conflict -- look up the existing id by content_hash.
    existing = await session.execute(
        text(
            "SELECT id FROM source "
            "WHERE tenant_id = :tid AND content_hash = :chash"
        ),
        {"tid": str(tenant_id), "chash": chash},
    )
    existing_row = existing.first()
    if existing_row is None:
        # Should not happen with the partial UNIQUE in place.
        raise RuntimeError(
            f"source upsert returned NULL on conflict and lookup found nothing "
            f"(tenant={tenant_id}, content_hash={chash[:12]})"
        )
    return existing_row.id


async def _insert_claim(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    claim_text: str,
    facet: Optional[str],
    position: Optional[int] = None,
) -> uuid.UUID:
    claim_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO claim (id, tenant_id, run_id, text, facet, position) "
            "VALUES (:id, :tid, :rid, :text, :facet, :position)"
        ),
        {
            "id": str(claim_id),
            "tid": str(tenant_id),
            "rid": str(run_id),
            "text": claim_text,
            "facet": facet,
            "position": position,
        },
    )
    return claim_id


async def _link_claim_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    claim_id: uuid.UUID,
    source_id: uuid.UUID,
    snippet: Optional[str] = None,
) -> None:
    await session.execute(
        text(
            "INSERT INTO claim_source (claim_id, source_id, tenant_id, snippet) "
            "VALUES (:cid, :sid, :tid, :snippet) "
            "ON CONFLICT (claim_id, source_id) DO NOTHING"
        ),
        {
            "cid": str(claim_id),
            "sid": str(source_id),
            "tid": str(tenant_id),
            "snippet": snippet,
        },
    )


async def extract_and_persist_citations(
    *,
    provider_results: list[tuple[str, dict]],
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    session: AsyncSession,
) -> dict:
    """Persist claim + source + claim_source rows for one run.

    Caller MUST have opened a transaction on `session` before invoking;
    we SET LOCAL the tenant_id here so RLS-protected inserts succeed.

    Returns {"claim_ids": [...], "source_ids": [...]} for downstream wiring
    (the worker can attach these to its run-progress event stream).
    """
    await set_tenant_context(session, tenant_id)

    PROVIDER_TO_AUDIT_NAME = {
        "gemini": "google",
        "claude": "anthropic",
        "openai": "openai",
    }

    claim_ids: list[uuid.UUID] = []
    source_ids: list[uuid.UUID] = []

    for provider_name, result in provider_results:
        if not result or result.get("status") != "success":
            continue
        report = result.get("report") or ""
        if not report:
            continue

        audit_provider = PROVIDER_TO_AUDIT_NAME.get(provider_name, provider_name)

        # 1. Extract URLs + create source rows (one per URL).
        urls = _extract_urls(report)
        per_provider_source_ids: list[uuid.UUID] = []
        for url in urls:
            sid = await _upsert_source(
                session,
                tenant_id=tenant_id,
                url=url,
                provider=audit_provider,
                snapshot_text=report,
            )
            per_provider_source_ids.append(sid)
            source_ids.append(sid)

        # 2. Create one coarse-grained claim per provider.
        claim_id = await _insert_claim(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            claim_text=report[:_SNAPSHOT_MAX_CHARS],
            facet=provider_name,
        )
        claim_ids.append(claim_id)

        # 3. Link the provider's claim to every source extracted from its report.
        for sid in per_provider_source_ids:
            await _link_claim_source(
                session,
                tenant_id=tenant_id,
                claim_id=claim_id,
                source_id=sid,
            )

    log.info(
        "extract_and_persist_citations done",
        extra={
            "run_id": str(run_id),
            "claim_count": len(claim_ids),
            "source_count": len(source_ids),
        },
    )
    return {"claim_ids": claim_ids, "source_ids": source_ids}


async def persist_tribunal_claims(
    *,
    claims: list[dict],
    verdicts_by_claim: dict,
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    session: AsyncSession,
) -> dict:
    """Persist fine-grained claim + claim_source rows for Tribunal survivors.

    This is the RECALL MECHANISM for the Tribunal path (PHASE1-05 gate).

    Unlike extract_and_persist_citations (which writes ONE coarse claim PER PROVIDER
    = 3 total from the provider_results blobs), this function writes ONE atomic claim
    row per distilled survivor from claim_distiller output. The result is many
    fine-grained rows (>=50 for a real brief) with skeptic web_fetch citations
    linked as claim_source rows — the shape the >=50-claim/>=95%-recall gate needs.

    Caller (TribunalPipeline) opens the session + transaction and passes the SURVIVORS
    only (claims that passed adjudication). This function:
      1. Calls set_tenant_context to enable RLS.
      2. For each survivor claim, inserts ONE claim row (claim.text = atomic fact,
         claim.facet = focus_area label).
      3. For each source_url / evidence_ref attached by that claim's skeptics, upserts
         a source row and links a claim_source row.

    Args:
        claims:           Adjudicated survivors from claim_distiller output.
                          Each dict: {text|claim_text, facet, source_urls|evidence_refs, ...}
        verdicts_by_claim: Mapping of id(claim) -> verdict dict (or list of verdicts).
                           Used to extract skeptic evidence_refs / citations for claim_source.
        run_id:           UUID of the current run.
        tenant_id:        UUID of the current tenant.
        session:          Active AsyncSession (caller opens transaction).

    Returns:
        {"claim_ids": [uuid, ...], "source_ids": [uuid, ...]}
    """
    await set_tenant_context(session, tenant_id)

    claim_ids: list[uuid.UUID] = []
    source_ids: list[uuid.UUID] = []

    for position, claim in enumerate(claims):
        # Support both 'text' (claim_distiller shape) and 'claim_text' (legacy)
        claim_text = (claim.get("text") or claim.get("claim_text") or "").strip()
        if not claim_text:
            log.warning("persist_tribunal_claims: empty claim text at position %d — skipping", position)
            continue

        facet = claim.get("facet") or claim.get("focus_area") or ""

        # Insert ONE fine-grained claim row per survivor
        claim_id = await _insert_claim(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            claim_text=claim_text,
            facet=facet,
            position=position,
        )
        claim_ids.append(claim_id)

        # Gather source URLs from the claim itself + from skeptic verdicts
        source_urls: list[str] = []

        # From the claim dict (e.g., source_urls or evidence_refs added by intake/distiller)
        for url_field in ("source_urls", "evidence_refs"):
            for url in (claim.get(url_field) or []):
                if url and isinstance(url, str):
                    source_urls.append(url)

        # From skeptic verdict(s) for this claim
        claim_id_key = id(claim)
        raw_verdicts = verdicts_by_claim.get(claim_id_key)
        if raw_verdicts is not None:
            # verdicts_by_claim may contain a single verdict dict or a list
            if isinstance(raw_verdicts, dict):
                raw_verdicts = [raw_verdicts]
            for verdict in raw_verdicts:
                for ref in (verdict.get("evidence_refs") or []):
                    if ref and isinstance(ref, str):
                        source_urls.append(ref)
                for citation in (verdict.get("citations") or []):
                    if isinstance(citation, dict):
                        url = citation.get("url") or citation.get("source_url") or ""
                    elif isinstance(citation, str):
                        url = citation
                    else:
                        url = ""
                    if url:
                        source_urls.append(url)

        # De-duplicate while preserving order
        seen_urls: set[str] = set()
        deduped_urls: list[str] = []
        for url in source_urls:
            url = url.strip()
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped_urls.append(url)

        # Upsert source rows + link claim_source rows
        for url in deduped_urls:
            sid = await _upsert_source(
                session,
                tenant_id=tenant_id,
                url=url,
                provider="tribunal_skeptic",
                snapshot_text=url,  # minimal snapshot; Phase 2 can enrich
            )
            source_ids.append(sid)
            await _link_claim_source(
                session,
                tenant_id=tenant_id,
                claim_id=claim_id,
                source_id=sid,
            )

    log.info(
        "persist_tribunal_claims done: %d claims / %d sources (run_id=%s)",
        len(claim_ids),
        len(source_ids),
        str(run_id),
    )
    return {"claim_ids": claim_ids, "source_ids": source_ids}
