"""
Deterministic citation `[n]` numbering (Phase 15 ENGINE-09, D13).

D13 (RESEARCH-ENGINE-DECISIONS): citation numbers are GENERATED from the
claim/claim_source ordering in the DB -- NEVER emitted by the writing model.
Last run's writing model produced 28 stripped/unresolvable markers precisely
because it invented its own numbers; here every `[n]` is assigned from
`claim.position` first-appearance ordering and ALWAYS resolves to a real source.

`number_citations(session, run_id)` returns an ordered `[n] -> source` mapping:
  - deterministic on (claim.position, then a stable source ordering) so two calls
    for the same run produce byte-identical numbering;
  - every number resolves to a source row (no dangling `[n]`);
  - each entry flags `single_source` (the claim it first appears on cites exactly
    one source);
  - quality tier (1 official / 2 press / 3 blog-or-other) + a publication-date
    proxy are DERIVED from a provider/domain heuristic (Open Q A3: NOT stored
    columns this phase -- chain-safe; a stored authoritative-tier column is a
    later, still-non-hashed option if the operator wants it).

Reads ONLY the DB (claim / source / claim_source), tenant-scoped via RLS -- no
model text parsing, no GCS. The caller must have set the tenant context
(get_db_session / set_tenant_context) so cross-tenant sources are invisible.
"""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ---------------------------------------------------------------------------
# Quality-tier heuristic (provider/domain) -- derived, NOT a stored column (A3).
# ---------------------------------------------------------------------------

# Tier 1: official / primary sources (government, regulators, standards bodies,
#         company IR / official filings, academic).
_TIER1_SUFFIXES = (".gov", ".gov.uk", ".europa.eu", ".edu", ".ac.uk", ".int")
_TIER1_HOST_HINTS = ("sec.gov", "europa.eu", "oecd.org", "worldbank.org", "imf.org")

# Tier 2: established press / trade-press / recognised data providers.
_TIER2_HOST_HINTS = (
    "reuters.com", "bloomberg.com", "ft.com", "wsj.com", "nytimes.com",
    "economist.com", "forbes.com", "cnbc.com", "theguardian.com", "bbc.co.uk",
    "bbc.com", "statista.com", "spglobal.com", "mckinsey.com",
)


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001 -- a malformed url just has no derivable tier
        return ""
    return host[4:] if host.startswith("www.") else host


def derive_quality_tier(provider: str | None, url: str | None) -> int:
    """Derive a 1/2/3 quality tier from the domain (A3 heuristic).

    1 = official/primary, 2 = established press/data provider, 3 = blog/other.
    NOT a stored column -- recomputed on read, deterministic for a given url.

    The tier comes ONLY from the domain: which search provider fetched a source
    says nothing about the source's quality, so any domain not recognised as
    tier 1/2 is honestly tier 3 (blog/other) regardless of provider (WR-05 --
    the old provider-conditional was dead code returning 3 on both branches;
    the behavior is pinned by test_citation_numbering's tier tests). `provider`
    stays in the signature: callers pass it and a REAL provider-informed
    heuristic remains a later option.
    """
    host = _domain(url)
    if host:
        if host.endswith(_TIER1_SUFFIXES) or any(h in host for h in _TIER1_HOST_HINTS):
            return 1
        if any(h in host for h in _TIER2_HOST_HINTS):
            return 2
    return 3


async def number_citations(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return the run's ordered `[n] -> source` citation mapping (deterministic).

    Ordering key: (claim.position NULLS LAST, claim.id, source first-appearance).
    A source is numbered ONCE at its first appearance across the ordered claims;
    later re-appearances reuse the same `[n]` (stable, all-resolve).

    Each returned entry:
      {
        "n": int,                 # 1-based citation number
        "source_id": str,
        "title": str | None,
        "url": str | None,
        "provider": str | None,
        "publication_date": str | None,  # source.fetched_at ISO (date proxy, A3)
        "quality_tier": int,      # 1/2/3 derived heuristic (A3)
        "single_source": bool,    # the claim it first appears on cites exactly one source
        "first_claim_id": str,    # the claim that introduced this source
        "first_claim_position": int | None,
      }

    Reads claim/source/claim_source only, RLS-scoped. No model text, no GCS.
    """
    # Pull the ordered claim -> source rows in ONE deterministic query. We order
    # by claim.position (first-appearance), then claim.id + source.id as stable
    # tie-breakers so the numbering is byte-identical across calls.
    rows = (
        await session.execute(
            text(
                "SELECT c.id AS claim_id, c.position AS position, "
                "       s.id AS source_id, s.title AS title, s.url AS url, "
                "       s.provider AS provider, s.fetched_at AS fetched_at "
                "FROM claim c "
                "JOIN claim_source cs ON cs.claim_id = c.id "
                "JOIN source s ON s.id = cs.source_id "
                "WHERE c.run_id = :rid "
                "ORDER BY c.position ASC NULLS LAST, c.id ASC, s.id ASC"
            ),
            {"rid": str(run_id)},
        )
    ).all()

    # First pass: count how many DISTINCT sources each claim cites (single_source).
    sources_per_claim: dict[str, set[str]] = {}
    for r in rows:
        cid = str(r._mapping["claim_id"])
        sid = str(r._mapping["source_id"])
        sources_per_claim.setdefault(cid, set()).add(sid)

    # Second pass: assign a 1-based number to each source at first appearance.
    numbered: list[dict[str, Any]] = []
    seen_source_to_n: dict[str, int] = {}
    next_n = 1
    for r in rows:
        m = r._mapping
        sid = str(m["source_id"])
        if sid in seen_source_to_n:
            continue  # already numbered at an earlier first-appearance
        cid = str(m["claim_id"])
        fetched_at = m["fetched_at"]
        numbered.append(
            {
                "n": next_n,
                "source_id": sid,
                "title": m["title"],
                "url": m["url"],
                "provider": m["provider"],
                "publication_date": (
                    fetched_at.isoformat() if fetched_at is not None else None
                ),
                "quality_tier": derive_quality_tier(m["provider"], m["url"]),
                "single_source": len(sources_per_claim.get(cid, ())) == 1,
                "first_claim_id": cid,
                "first_claim_position": m["position"],
            }
        )
        seen_source_to_n[sid] = next_n
        next_n += 1

    return numbered
