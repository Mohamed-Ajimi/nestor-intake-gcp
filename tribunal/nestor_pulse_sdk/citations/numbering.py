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
  - quality tier is 1 official / 2 press / 3 blog-or-other. THERE ARE NOW TWO
    SOURCES OF TRUTH FOR IT AND PROVIDER-STATED WINS (D-13, Phase 15.2 plan 15):
    when the research provider that cited a source said what KIND of source it
    was, `claim_source.provider_quality` is mapped straight to a tier; only when
    it said nothing does `derive_quality_tier`'s domain heuristic decide. The
    provider read the page and the heuristic only reads the hostname, so the
    heuristic is the FALLBACK, not the authority. `derive_quality_tier` itself is
    unchanged, still recomputed on read, and still pinned by its own tier tests.
    A source is graded by the `claim_source` row of the claim that FIRST
    introduced it in the deterministic ordering below -- one source, one grade,
    chosen the same way every run.
  - the publication-date proxy stays DERIVED from `source.fetched_at` (A3).

`publication_date` IS A RETRIEVAL-DATE PROXY, NOT A PUBLICATION DATE. It carries
`source.fetched_at` -- the moment WE fetched the page, which says nothing about
when the page was published. Downstream renderers MUST label it "retrieved",
never "published": presenting a proxy as a fact is exactly what the operator's
"NO ESTIMATES -- facts and correct calculations only" bar (C1) forbids.

Phase 15.2 (D-05) additions, all ADDITIVE -- `number_citations`' signature,
docstring contract and return value are unchanged and still pinned by its
original determinism test:
  - `_assign_numbers(rows)` -- the pure two-pass assignment, extracted so it can
    be proved with hand-built rows in the keyless, DB-less engine gate.
  - `number_citations_with_claims()` -- the same numbering PLUS a complete
    claim-id -> `[n]` map, which `citations/anchors.py` reduces to the prefix map
    its post-pass resolves against.
  - `list_run_claims()` -- the ordered claim rows the fact ledger is built from.

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


# ---------------------------------------------------------------------------
# D-13 (Phase 15.2 plan 15): the provider-stated grade, which BEATS the heuristic
# above. `claim_source.provider_quality` holds one of these three words, already
# clamped twice -- at parse (15.2-04) and again at write (citations/extractor.py)
# -- so anything unrecognised is already NULL by the time it is read here and
# falls through to `derive_quality_tier`. A model can therefore never invent a
# tier; the worst it can do is decline to state one.
# ---------------------------------------------------------------------------
_PROVIDER_QUALITY_TIER = {"official": 1, "press": 2, "other": 3}


def _quality_tier_for(row: Any, provider: str | None, url: str | None) -> int:
    """Provider-stated tier when there is one, else the domain heuristic.

    The read is DEFENSIVE by design: `_assign_numbers` is pure and is proved with
    hand-built row dicts in the keyless engine gate, and 15.2-05's Layer-1
    fixtures have no `provider_quality` key at all. `_row_get` already returns
    None for a missing key on both a SQLAlchemy Row and a plain dict, so those
    fixtures keep passing untouched and fall through to the heuristic -- which is
    exactly the behaviour they were written to pin.
    """
    stated = _row_get(row, "provider_quality")
    if isinstance(stated, str):
        tier = _PROVIDER_QUALITY_TIER.get(stated.strip().lower())
        if tier is not None:
            return tier
    return derive_quality_tier(provider, url)


# ---------------------------------------------------------------------------
# The ordered claim -> source query. ONE deterministic statement, hoisted so the
# numbering and the with-claims variant can never drift apart.
#
# The ORDER BY is the DETERMINISM CONTRACT pinned by
# test_citation_numbering.py::test_numbering_is_deterministic_and_all_resolve.
# Do not change one character of it.
# ---------------------------------------------------------------------------
_CLAIM_SOURCE_SQL = (
    "SELECT c.id AS claim_id, c.position AS position, "
    "       s.id AS source_id, s.title AS title, s.url AS url, "
    "       s.provider AS provider, s.fetched_at AS fetched_at, "
    # D-13 (15.2-15): the provider's OWN statement about the source it cited.
    # One added column and nothing else -- the ORDER BY below is untouched.
    "       cs.provider_quality AS provider_quality "
    "FROM claim c "
    "JOIN claim_source cs ON cs.claim_id = c.id "
    "JOIN source s ON s.id = cs.source_id "
    "WHERE c.run_id = :rid "
    "ORDER BY c.position ASC NULLS LAST, c.id ASC, s.id ASC"
)

#: The ordered claim rows the fact ledger is built from. SAME ordering key as
#: _CLAIM_SOURCE_SQL, so the ledger the model sees and the numbers Python assigns
#: are ordered identically.
_RUN_CLAIMS_SQL = (
    "SELECT id, text, facet, position "
    "FROM claim "
    "WHERE run_id = :rid "
    "ORDER BY position ASC NULLS LAST, id ASC"
)


def _row_get(row: Any, key: str) -> Any:
    """Read `key` off a SQLAlchemy Row or a plain dict, without raising.

    `_assign_numbers` is pure and must be provable with hand-built dicts in the
    keyless engine gate, but production feeds it SQLAlchemy rows.
    """
    mapping = getattr(row, "_mapping", None)
    if mapping is not None:
        try:
            return mapping[key]
        except (KeyError, IndexError, TypeError):
            return None
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return None


def _assign_numbers(rows: Any) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Assign `[n]` at first source appearance. PURE -- no DB, no I/O.

    `rows` must already be ordered by `_CLAIM_SOURCE_SQL`'s ORDER BY; this
    function does not sort, it only walks.

    Returns `(numbered, claim_to_n)`:

    * `numbered` -- BYTE-IDENTICAL to what `number_citations` has always
      returned. Its entry shape is documented on `number_citations`.
    * `claim_to_n` -- full claim-id string -> the `[n]` of that claim's FIRST
      source in row order. EVERY claim present in `rows` appears here, not just
      the claims that introduced a new source: one claim can introduce several
      sources, and most claims cite a source some earlier claim already numbered.
      A map built only from `first_claim_id` would leave the majority of the
      model's anchors unresolvable -- which is precisely the D-06 count we are
      trying to drive to zero.
    """
    rows = list(rows or ())

    # First pass: count how many DISTINCT sources each claim cites (single_source).
    sources_per_claim: dict[str, set[str]] = {}
    for r in rows:
        cid = str(_row_get(r, "claim_id"))
        sid = str(_row_get(r, "source_id"))
        sources_per_claim.setdefault(cid, set()).add(sid)

    # Second pass: assign a 1-based number to each source at first appearance.
    numbered: list[dict[str, Any]] = []
    claim_to_n: dict[str, int] = {}
    seen_source_to_n: dict[str, int] = {}
    next_n = 1
    for r in rows:
        sid = str(_row_get(r, "source_id"))
        cid = str(_row_get(r, "claim_id"))
        if sid in seen_source_to_n:
            # Already numbered at an earlier first-appearance. The CLAIM still
            # gets mapped -- this is the majority case.
            claim_to_n.setdefault(cid, seen_source_to_n[sid])
            continue
        claim_to_n.setdefault(cid, next_n)
        fetched_at = _row_get(r, "fetched_at")
        if fetched_at is None:
            publication_date = None
        elif hasattr(fetched_at, "isoformat"):
            publication_date = fetched_at.isoformat()
        else:
            publication_date = str(fetched_at)
        url = _row_get(r, "url")
        provider = _row_get(r, "provider")
        numbered.append(
            {
                "n": next_n,
                "source_id": sid,
                "title": _row_get(r, "title"),
                "url": url,
                "provider": provider,
                "publication_date": publication_date,
                # D-13: provider-stated wins, `derive_quality_tier` is the
                # fallback. The entry SHAPE is deliberately unchanged -- no new
                # key -- because 15.2-05's Layer-1 tests compare whole entry
                # lists for byte-identical determinism. Only the VALUE moves.
                "quality_tier": _quality_tier_for(r, provider, url),
                "single_source": len(sources_per_claim.get(cid, ())) == 1,
                "first_claim_id": cid,
                "first_claim_position": _row_get(r, "position"),
            }
        )
        seen_source_to_n[sid] = next_n
        next_n += 1

    return numbered, claim_to_n


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
        "quality_tier": int,      # 1/2/3 — claim_source.provider_quality when the
                                  # provider stated one (D-13), else the A3 heuristic
        "single_source": bool,    # the claim it first appears on cites exactly one source
        "first_claim_id": str,    # the claim that introduced this source
        "first_claim_position": int | None,
      }

    Reads claim/source/claim_source only, RLS-scoped. No model text, no GCS.
    """
    # Pull the ordered claim -> source rows in ONE deterministic query. We order
    # by claim.position (first-appearance), then claim.id + source.id as stable
    # tie-breakers so the numbering is byte-identical across calls.
    rows = (await session.execute(text(_CLAIM_SOURCE_SQL), {"rid": str(run_id)})).all()
    return _assign_numbers(rows)[0]


async def number_citations_with_claims(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """`number_citations`' list PLUS the complete claim-id -> `[n]` map.

    One query, both halves. The list is BYTE-IDENTICAL to what
    `number_citations(session, run_id)` returns for the same run -- they share
    `_CLAIM_SOURCE_SQL` and `_assign_numbers`, so the `## Sources` list and the
    body's `[n]` markers can never disagree.

    The map is what `citations/anchors.py::anchor_number_map` reduces to the
    prefix map its post-pass resolves against (D-05).
    """
    rows = (await session.execute(text(_CLAIM_SOURCE_SQL), {"rid": str(run_id)})).all()
    return _assign_numbers(rows)


async def list_run_claims(
    session: AsyncSession,
    run_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """Return the run's claims in ledger order.

    Entries: `{"claim_id": str, "text": str, "facet": str|None,
    "position": int|None}`.

    Ordered by the SAME key as the numbering query
    (`position ASC NULLS LAST, id ASC`), so the fact ledger the model reads and
    the numbers Python assigns are ordered identically -- there is exactly one
    ordering in this module and both consumers use it.

    RLS-scoped: the caller must already have set the tenant context.
    """
    rows = (await session.execute(text(_RUN_CLAIMS_SQL), {"rid": str(run_id)})).all()
    return [
        {
            "claim_id": str(_row_get(r, "id")),
            "text": _row_get(r, "text"),
            "facet": _row_get(r, "facet"),
            "position": _row_get(r, "position"),
        }
        for r in rows
    ]
