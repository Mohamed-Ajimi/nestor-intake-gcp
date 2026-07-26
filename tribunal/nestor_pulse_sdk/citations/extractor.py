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
import json
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
    title: str | None = None,
) -> uuid.UUID:
    """INSERT a source row, deduping by (tenant_id, content_hash).

    Uses the partial UNIQUE index from migration 0003:
      idx_source_tenant_content_hash UNIQUE (tenant_id, content_hash)
      WHERE content_hash IS NOT NULL

    On conflict, returns the id of the existing row rather than the new uuid.

    `title` (Phase 15.2 F10) is ADDITIVE and defaults to None, so every existing
    call site stays valid unchanged. Three rules govern it:

    * It is NOT part of `content_hash` -- the dedupe key is computed from
      `snapshot_capped` alone and is unchanged by this parameter. An existing row
      therefore still wins on conflict (`DO NOTHING`) and KEEPS whatever title it
      already had; a later, better title never silently rewrites history.
    * The one production call site (the skeptic-evidence upsert below) passes
      NOTHING in 15.2-05. A title invented from the URL would be a fabrication;
      the graded `## Sources` renderer falls back to the display domain at render
      time instead, which is honest.
    * 15.2-15 threads the real D8 provider-supplied titles through this
      parameter.
    """
    snapshot_capped = (snapshot_text or "")[:_SNAPSHOT_MAX_CHARS]
    chash = _content_hash(snapshot_capped) if snapshot_capped else None
    new_id = uuid.uuid4()
    title_value = (title or "").strip() or None

    if chash is None:
        # No snapshot to hash -- skip dedupe and insert plainly.
        await session.execute(
            text(
                "INSERT INTO source "
                "(id, tenant_id, url, provider, title, snapshot_text, content_hash) "
                "VALUES (:id, :tid, :url, :provider, :title, :snapshot, NULL)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "url": url,
                "provider": provider,
                "title": title_value,
                "snapshot": snapshot_capped or None,
            },
        )
        return new_id

    # Try INSERT; on conflict return existing row's id.
    result = await session.execute(
        text(
            "INSERT INTO source "
            "(id, tenant_id, url, provider, title, snapshot_text, content_hash) "
            "VALUES (:id, :tid, :url, :provider, :title, :snapshot, :chash) "
            "ON CONFLICT (tenant_id, content_hash) "
            "WHERE content_hash IS NOT NULL DO NOTHING "
            "RETURNING id"
        ),
        {
            "id": str(new_id),
            "tid": str(tenant_id),
            "url": url,
            "provider": provider,
            "title": title_value,
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


async def _insert_verdict(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    claim_id: Optional[uuid.UUID],
    verdict: dict,
) -> uuid.UUID:
    """Write ONE `verification_verdict` row for one per-claim verdict dict.

    ENGINE-10 / CR-02. Before this helper existed nothing in production wrote to
    `verification_verdict` — the only writer in the repo was the recorded-fixture
    loader — so `build_verification_report` queried zero rows on every real run
    and published `verdicts.{support,refute,insufficient,superseded} == []` with
    `counts.verdicts_total == 0` beside an honest gate-derived `checked` count.

    TENANT CONTEXT — THIS HELPER PERFORMS NO TENANT SETUP OF ITS OWN.
    It is called ONLY from inside `persist_tribunal_claims`, AFTER that
    function's `set_tenant_context`, and inside the transaction the CALLER
    opened. `set_tenant_context` issues `set_config('app.tenant_id', :tid, true)`
    — transaction-local — so every statement executed after it in that same
    transaction is governed by migration 0011's FORCE-RLS policy
    `verification_verdict_tenant_isolation`. `tenant_id` is bound explicitly so
    the policy's `WITH CHECK` clause governs the INSERT rather than the write
    slipping around it. Calling this from anywhere without an established tenant
    context would be a bug.

    SOURCE ORDER IS NOT THE ORDERING THAT MATTERS. This `def` sits ABOVE
    `persist_tribunal_claims` because it is grouped with the other write helpers
    (`_upsert_source`, `_insert_claim`, `_link_claim_source`); it is only ever
    CALLED below it. The runtime ordering proof is
    `tests/test_verdict_write_path.py::test_tenant_context_is_set_before_any_verdict_insert`,
    which asserts the recorded CALL order on the session.

    Args:
        claim_id: the `claim` row this verdict belongs to, or None. A refuted /
                  conflict-lost claim has NO claim row (the claim table is the
                  survivor recall mechanism for the PHASE1-05 gate), so its
                  verdict is written with a NULL claim_id — the same shape the
                  recorded fixture uses, and one `report.py` already handles by
                  counting DISTINCT non-null claim_ids.
        verdict:  a per-claim verdict dict from `verdicts_by_claim`
                  (`group_skeptic._parse_group_verdict` shape, plus the
                  `reconciliation` key the pipeline attaches in `_flush_groups`).

    Every value is a BOUND PARAMETER on a `text()` statement — no model-authored
    string is ever interpolated into SQL — and the two JSONB columns go through
    `json.dumps` + `CAST(:p AS JSONB)`, the codebase's raw-SQL JSONB idiom.
    """
    verdict_id = uuid.uuid4()

    # A malformed / unparseable verdict dict must not bind NULL into a NOT NULL
    # column: default to the same "insufficient" the group skeptic uses.
    raw_verdict = verdict.get("verdict")
    verdict_value = (raw_verdict.strip() if isinstance(raw_verdict, str) else "") or "insufficient"

    # The parser produces a float; the column is TEXT.
    raw_confidence = verdict.get("confidence")
    confidence = None if raw_confidence is None else str(raw_confidence)

    raw_refs = verdict.get("evidence_refs")
    evidence = json.dumps(raw_refs) if isinstance(raw_refs, list) and raw_refs else None

    raw_recon = verdict.get("reconciliation")
    recon = json.dumps(raw_recon) if isinstance(raw_recon, dict) and raw_recon else None

    # Never write "" — the column is nullable precisely so "no caveat" is
    # representable as NULL rather than as an empty string.
    raw_note = verdict.get("superseded_note")
    note = (raw_note.strip() if isinstance(raw_note, str) else "") or None

    await session.execute(
        text(
            "INSERT INTO verification_verdict "
            "(id, tenant_id, run_id, claim_id, verdict, confidence, "
            "evidence_refs, reconciliation, superseded_note) "
            "VALUES (:id, :tid, :rid, :cid, :verdict, :confidence, "
            "CAST(:evidence AS JSONB), "
            "CAST(:recon AS JSONB), "
            ":note)"
        ),
        {
            "id": str(verdict_id),
            "tid": str(tenant_id),
            "rid": str(run_id),
            "cid": str(claim_id) if claim_id is not None else None,
            "verdict": verdict_value,
            "confidence": confidence,
            "evidence": evidence,
            "recon": recon,
            "note": note,
        },
    )
    return verdict_id


def _verdicts_for(claim: dict, verdicts_by_claim: dict) -> list[dict]:
    """Return one claim's verdicts as a list, whatever shape the map holds.

    `verdicts_by_claim` is keyed by `id(claim)` — object identity, so the SAME
    dict objects the `claims` / `survivors` / `dropped` lists hold — and a value
    may be a single verdict dict or a list of them. ONE normalisation, used by
    both the source-gathering block and the verdict writes, so the two cannot
    drift apart.
    """
    raw = verdicts_by_claim.get(id(claim))
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [raw]
    return [v for v in raw if isinstance(v, dict)]


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
    dropped_claims: Optional[list[dict]] = None,
) -> dict:
    """Persist fine-grained claim + claim_source + verification_verdict rows.

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
      4. Writes ONE verification_verdict row per verdict — survivors linked to the
         claim row inserted for them in this same transaction, dropped claims with
         claim_id = NULL (ENGINE-10 / CR-02).

    Args:
        claims:           Adjudicated survivors from claim_distiller output.
                          Each dict: {text|claim_text, facet, source_urls|evidence_refs, ...}
        verdicts_by_claim: Mapping of id(claim) -> verdict dict (or list of verdicts).
                           Used to extract skeptic evidence_refs / citations for claim_source,
                           and to write the verification_verdict rows.
        run_id:           UUID of the current run.
        tenant_id:        UUID of the current tenant.
        session:          Active AsyncSession (caller opens transaction).
        dropped_claims:   Claims refuted by adjudication or lost as the weaker side of
                          a conflict. They get NO `claim` row — the claim table is the
                          survivor recall mechanism for the PHASE1-05 gate and must keep
                          that meaning — but their verdicts ARE persisted, with
                          `claim_id = NULL`, so report["verdicts"]["refute"] and
                          report["refuted"] are not permanently empty. Keyword-optional
                          and defaulted to None so every pre-existing call shape stays
                          valid.

    Returns:
        {"claim_ids": [uuid, ...], "source_ids": [uuid, ...],
         "verdict_ids": [uuid, ...], "verdict_count": int}
    """
    await set_tenant_context(session, tenant_id)

    claim_ids: list[uuid.UUID] = []
    source_ids: list[uuid.UUID] = []
    verdict_ids: list[uuid.UUID] = []

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

        claim_verdicts = _verdicts_for(claim, verdicts_by_claim)

        # ENGINE-10 / CR-02: the verdict row is written HERE, carrying the
        # claim_id of the row inserted a moment ago in this same transaction.
        # That linkage is the point — it is what makes
        # unverified.claims_with_verdict a real number instead of the
        # claim_id-IS-NULL workaround report.py documents. The write runs after
        # this function's set_tenant_context above, so migration 0011's
        # FORCE-RLS WITH CHECK policy governs it.
        for claim_verdict in claim_verdicts:
            verdict_ids.append(
                await _insert_verdict(
                    session,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    claim_id=claim_id,
                    verdict=claim_verdict,
                )
            )

        # Gather source URLs from the claim itself + from skeptic verdicts
        source_urls: list[str] = []

        # From the claim dict (e.g., source_urls or evidence_refs added by intake/distiller)
        for url_field in ("source_urls", "evidence_refs"):
            for url in (claim.get(url_field) or []):
                if url and isinstance(url, str):
                    source_urls.append(url)

        # From skeptic verdict(s) for this claim — SAME normalisation the verdict
        # writes above use, so the two views of verdicts_by_claim cannot diverge.
        for claim_verdict in claim_verdicts:
            for ref in (claim_verdict.get("evidence_refs") or []):
                if ref and isinstance(ref, str):
                    source_urls.append(ref)
            for citation in (claim_verdict.get("citations") or []):
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

    # Dropped claims: refuted by adjudication or the weaker side of a conflict.
    # No `claim` row is written for them (see the dropped_claims Arg note), but
    # their verdicts ARE persisted with claim_id = NULL. Without this loop
    # report["verdicts"]["refute"] and report["refuted"] would stay permanently
    # empty, because Stage 7 passes only survivors as `claims` — the exact
    # hollow surface CR-02 describes. Claims with no verdicts are skipped:
    # conflict losers were never fact-checked.
    for dropped_claim in (dropped_claims or []):
        for claim_verdict in _verdicts_for(dropped_claim, verdicts_by_claim):
            verdict_ids.append(
                await _insert_verdict(
                    session,
                    tenant_id=tenant_id,
                    run_id=run_id,
                    claim_id=None,
                    verdict=claim_verdict,
                )
            )

    log.info(
        "persist_tribunal_claims done: %d claims / %d sources / %d verdicts (run_id=%s)",
        len(claim_ids),
        len(source_ids),
        len(verdict_ids),
        str(run_id),
    )
    return {
        "claim_ids": claim_ids,
        "source_ids": source_ids,
        "verdict_ids": verdict_ids,
        "verdict_count": len(verdict_ids),
    }
