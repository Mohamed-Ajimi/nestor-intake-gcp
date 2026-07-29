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
from datetime import date, datetime
from typing import Optional

import sqlalchemy
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.db.models import Claim, ClaimSource, Source
from nestor_pulse_sdk.db.rls import set_tenant_context

log = logging.getLogger(__name__)

# Lightweight URL pattern -- matches http(s):// up to whitespace, paren, or quote.
_URL_RE = re.compile(r"https?://[^\s)\"'<>\]]+", re.IGNORECASE)

# Cap the snapshot_text length to avoid persisting megabyte-scale provider blobs.
_SNAPSHOT_MAX_CHARS = 50_000

# ---------------------------------------------------------------------------
# D-13 bounds (Phase 15.2 plan 15). EVERY value below originates in model output
# -- a provider's own fact list -- so every one of them is clamped or capped HERE
# as well as at parse time (15.2-04). This function is the last thing between
# untrusted model wording and a persisted, queryable column, and a bound that
# only exists in the parser is a bound one refactor away from being gone.
# ---------------------------------------------------------------------------

#: The only two words `claim.certainty` may hold (15.2-04 `CERTAINTY_VALUES`).
_CERTAINTY_VALUES = ("certain", "single")

#: The only three words `claim_source.provider_quality` may hold (15.2-04
#: `QUALITY_VALUES`). They map to the 1/2/3 tier in citations/numbering.py.
_QUALITY_VALUES = ("official", "press", "other")

#: Bounds on `claim.found_by` (a Postgres text[]). Provider names are CALLER-
#: supplied, never model-supplied (T-15.2-57), so this is not an injection
#: control -- it is the bound that stops a bug writing an unbounded array.
_MAX_FOUND_BY = 16
_FOUND_BY_MAX_CHARS = 64

#: D-R3 (Phase 15.5, migration 0017). Bounds on `claim.sub_question` and
#: `claim.corroboration_key`. Both values are CALLER-supplied, never model-
#: supplied -- `_angle()` stamps them in Python from the dispatch assignment,
#: exactly as `provider` is stamped -- so, like `_MAX_FOUND_BY`, these are NOT an
#: injection control: they are a BUG BOUND. But the column must not be a place a
#: bug can write unbounded data, so the cap exists here, at the last point before
#: the database, and truncation is LOGGED rather than silent.
#:
#: The caps are generous on purpose. A corroboration key is `wNN` today -- three
#: characters -- and a sub-question is one workshop winner's sentence.
_SUB_QUESTION_MAX_CHARS = 500
_CORROBORATION_KEY_MAX_CHARS = 32

#: Bounds on the `research_gap` write (T-15.2-55, denial-of-storage). Truncation
#: is LOGGED with the exact dropped count -- bounded and loud, never silent.
_RESEARCH_GAP_MAX_CHARS = 2_000
_MAX_RESEARCH_GAPS = 200
_GAP_PROVIDER_MAX_CHARS = 64

#: `source.title` is the provider's own markdown link label as resolved by
#: 15.2-04's `display_domain` -- never an invented string.
_SOURCE_TITLE_MAX_CHARS = 200

#: D-V01-11 (Phase 15.4, migration 0016). The only two words
#: `source.resolution_status` may hold. NULL is the third state and means
#: something DIFFERENT -- "never attempted" -- so it is deliberately absent from
#: this tuple: "attempted and failed" must never collapse into "never tried",
#: which is the entire reason `source` carries two columns rather than one.
_RESOLUTION_STATUS_VALUES = ("resolved", "unresolved")

#: `source.resolved_url` holds a `Location` header chosen by a REMOTE HOST, and
#: the value is later rendered as a clickable link. `redirect_resolver` already
#: validates scheme and length; this is the same bound applied AGAIN at the last
#: point before the column, on the D-13 rule that a bound which exists only in
#: the parser is one refactor away from being gone.
_RESOLVED_URL_MAX_CHARS = 2048


def _clamp_enum(value: object, allowed: tuple[str, ...], *, field: str) -> Optional[str]:
    """Return `value` lowercased if it is one of `allowed`, else None + a warning.

    ASVS V5 enum clamping. An unrecognised word is NOT an error worth failing a
    paid run over and is NOT something to store: it becomes NULL, and the run log
    says which field rejected what, so a provider that starts emitting a fourth
    vocabulary word is visible rather than silently absent.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        log.warning(
            "persist: %s was %s, not a string — stored as NULL",
            field, type(value).__name__,
        )
        return None
    normalised = value.strip().lower()
    if normalised in allowed:
        return normalised
    if normalised:
        log.warning(
            "persist: %s value %r is not one of %s — stored as NULL",
            field, value[:40], allowed,
        )
    return None


def _clamp_attribution(value: object, max_chars: int, *, field: str) -> Optional[str]:
    """Bound one D-R3 attribution string; ABSENT becomes None, never ''.

    D-W2-2, and the same rule `_insert_claim`'s docstring already states for
    `found_by` ("an ABSENT provenance is bound as None, never as []"): "no key
    recorded" and "recorded as the empty key" are DIFFERENT FACTS, and the
    corroboration queries must be able to tell them apart. Roughly 12 of 15
    winners have no corroboration key today, because `research_division.py`
    deals the remainder round-robin with the EMPTY STRING -- so the empty string
    arrives here routinely and must land in the column as NULL.

    A non-string, an empty string and a whitespace-only string all become None.
    An over-long string is TRUNCATED and the truncation is LOGGED with both
    lengths: a silent truncation is the class of loss this phase family exists
    to end.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        log.warning(
            "persist: %s was %s, not a string — stored as NULL",
            field, type(value).__name__,
        )
        return None
    stripped = value.strip()
    if not stripped:
        # NOT '' -- see the docstring. This is the common path, not an edge case.
        return None
    if len(stripped) > max_chars:
        log.warning(
            "persist: %s was %d characters — truncated to %d",
            field, len(stripped), max_chars,
        )
        return stripped[:max_chars]
    return stripped


def _coerce_as_of(value: object, *, field: str) -> Optional[date]:
    """Bound `claim.as_of` to a real `datetime.date`, or None with a warning.

    `datetime` is a SUBCLASS of `date`, so an `isinstance(value, date)` test
    alone would let a timestamp through into a DATE column. It is converted with
    `.date()` rather than stored, so a time can never reach the column and two
    claims from the same day can never acquire a false ordering.

    Anything else -- including the ISO STRING the column would happily accept --
    becomes None. The parsing already happened upstream in
    `claim_attribution.extract_as_of`, which rejects every ambiguous form rather
    than guessing; this boundary only refuses what it cannot vouch for. A wrong
    date is worse than no date: it turns a real contradiction into a fake time
    series, which is the failure that made this column necessary.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    log.warning(
        "persist: %s was %s, not a date — stored as NULL",
        field, type(value).__name__,
    )
    return None


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
    resolved_url: str | None = None,
    resolution_status: str | None = None,
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

    `resolved_url` and `resolution_status` (D-V01-11, migration 0016) are
    ADDITIVE in exactly the same way and live under exactly the same three rules:

    * NEITHER is part of `content_hash` -- the dedupe key is still computed from
      `snapshot_capped` alone -- so supplying them CANNOT change source dedupe.
    * On conflict the existing row wins (`DO NOTHING`) and KEEPS whatever it
      already had. A later, better resolution never rewrites a historic row
      (T-15.4-24).
    * Both default to None, so every existing call site stays valid unchanged and
      reads back as NULL -- which is the "never attempted" state, distinct from
      the `'unresolved'` that means "attempted and failed".

    `url` itself is NEVER rewritten with the resolved target. The redirect the
    provider returned is the citation; the publisher URL is stored beside it.
    """
    snapshot_capped = (snapshot_text or "")[:_SNAPSHOT_MAX_CHARS]
    chash = _content_hash(snapshot_capped) if snapshot_capped else None
    new_id = uuid.uuid4()
    title_value = (title or "").strip() or None

    # Both values originate outside this process -- one in a remote host's
    # `Location` header, one in this module's own caller -- so both are bounded
    # HERE as well as where they were produced.
    resolved_value = (resolved_url or "").strip()[:_RESOLVED_URL_MAX_CHARS] or None
    status_value = _clamp_enum(
        resolution_status, _RESOLUTION_STATUS_VALUES, field="source.resolution_status"
    )

    if chash is None:
        # No snapshot to hash -- skip dedupe and insert plainly.
        await session.execute(
            text(
                "INSERT INTO source "
                "(id, tenant_id, url, provider, title, snapshot_text, content_hash, "
                "resolved_url, resolution_status) "
                "VALUES (:id, :tid, :url, :provider, :title, :snapshot, NULL, "
                ":resolved_url, :resolution_status)"
            ),
            {
                "id": str(new_id),
                "tid": str(tenant_id),
                "url": url,
                "provider": provider,
                "title": title_value,
                "snapshot": snapshot_capped or None,
                "resolved_url": resolved_value,
                "resolution_status": status_value,
            },
        )
        return new_id

    # Try INSERT; on conflict return existing row's id.
    result = await session.execute(
        text(
            "INSERT INTO source "
            "(id, tenant_id, url, provider, title, snapshot_text, content_hash, "
            "resolved_url, resolution_status) "
            "VALUES (:id, :tid, :url, :provider, :title, :snapshot, :chash, "
            ":resolved_url, :resolution_status) "
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
            "resolved_url": resolved_value,
            "resolution_status": status_value,
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
    certainty: Optional[str] = None,
    found_by: Optional[list[str]] = None,
    sub_question: Optional[str] = None,
    corroboration_key: Optional[str] = None,
    as_of: Optional[date] = None,
) -> uuid.UUID:
    """INSERT one claim row. `certainty` / `found_by` are D-13, ADDITIVE.

    `sub_question` / `corroboration_key` / `as_of` are D-R3 (Phase 15.5,
    migration 0017) and are ADDITIVE in exactly the same way.

    All five default to None so every pre-existing call site stays valid
    unchanged -- including the coarse-grained one in
    `extract_and_persist_citations`, which passes only `claim_text` and `facet`.

    THREE BINDING RULES, stated here because each one is a trap:

    * `found_by` is a Postgres `text[]`. It is bound through an EXPLICIT
      `bindparam(..., type_=postgresql.ARRAY(Text))` rather than left for the
      driver to infer an array type from an untyped Python list -- pg8000 and
      asyncpg disagree about that inference, and the failure mode is a runtime
      error inside a paid run rather than a test failure.
    * An ABSENT provenance is bound as `None`, never as `[]`, so the column reads
      NULL. `cardinality(found_by)` on an empty array is 0 and on NULL is NULL;
      "no provenance recorded" and "recorded as found by nobody" are different
      facts and the corroboration queries must be able to tell them apart.
    * `certainty` is clamped to {'certain','single'} HERE as well as at parse
      time. Anything else -- including a non-string -- becomes NULL with a
      warning. This function is the last thing between untrusted model wording
      and the database.

    `found_by` is additionally capped at `_MAX_FOUND_BY` entries of
    `_FOUND_BY_MAX_CHARS` characters. Provider names are caller-supplied and
    never model-supplied (T-15.2-57), so that cap is a bug bound, not an
    injection control -- but the column must not be a place a bug can write
    unbounded data.

    THE THREE D-R3 COLUMNS FOLLOW ALL THREE OF THOSE RULES AGAIN:

    * `as_of` is bound through an EXPLICIT `bindparam("as_of", type_=Date)` for
      the same reason `found_by` is: a driver left to infer a date type inside
      the final persistence transaction of a roughly $50 run fails as a RUNTIME
      ERROR, not as a test failure.
    * An ABSENT `sub_question` or `corroboration_key` is bound as `None`, never
      as `''` (D-W2-2). The empty string is what `research_division.py` deals to
      every non-top-3 winner, so it arrives here on the majority of claims and
      must land in the column as NULL.
    * Both strings are capped -- `_SUB_QUESTION_MAX_CHARS` /
      `_CORROBORATION_KEY_MAX_CHARS` -- and a non-date `as_of` is refused. This
      function is the last thing between untrusted model wording and the
      database.
    """
    claim_id = uuid.uuid4()

    certainty_value = _clamp_enum(certainty, _CERTAINTY_VALUES, field="claim.certainty")

    sub_question_value = _clamp_attribution(
        sub_question, _SUB_QUESTION_MAX_CHARS, field="claim.sub_question"
    )
    corroboration_key_value = _clamp_attribution(
        corroboration_key, _CORROBORATION_KEY_MAX_CHARS, field="claim.corroboration_key"
    )
    as_of_value = _coerce_as_of(as_of, field="claim.as_of")

    found_by_value: Optional[list[str]] = None
    if isinstance(found_by, list) and found_by:
        bounded = [
            str(p).strip()[:_FOUND_BY_MAX_CHARS]
            for p in found_by[:_MAX_FOUND_BY]
            if p
        ]
        bounded = [p for p in bounded if p]
        if len(found_by) > _MAX_FOUND_BY:
            log.warning(
                "persist: claim.found_by had %d entries — capped at %d, %d dropped",
                len(found_by), _MAX_FOUND_BY, len(found_by) - _MAX_FOUND_BY,
            )
        # NULL rather than [] -- see the docstring.
        found_by_value = bounded or None

    statement = text(
        "INSERT INTO claim "
        "(id, tenant_id, run_id, text, facet, position, certainty, found_by, "
        "sub_question, corroboration_key, as_of) "
        "VALUES (:id, :tid, :rid, :text, :facet, :position, :certainty, :found_by, "
        ":sub_question, :corroboration_key, :as_of)"
    ).bindparams(
        sqlalchemy.bindparam(
            "found_by", type_=postgresql.ARRAY(sqlalchemy.Text)
        ),
        sqlalchemy.bindparam("as_of", type_=sqlalchemy.Date),
    )
    await session.execute(
        statement,
        {
            "id": str(claim_id),
            "tid": str(tenant_id),
            "rid": str(run_id),
            "text": claim_text,
            "facet": facet,
            "position": position,
            "certainty": certainty_value,
            "found_by": found_by_value,
            "sub_question": sub_question_value,
            "corroboration_key": corroboration_key_value,
            "as_of": as_of_value,
        },
    )
    return claim_id


async def _insert_research_gap(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    run_id: uuid.UUID,
    provider: str,
    text_value: str,
) -> None:
    """INSERT one `research_gap` row -- a thing a provider said it could NOT find.

    Shaped exactly like `_insert_claim`: one parameterised INSERT, a fresh uuid4,
    and NO `created_at` (the column carries a server default, so the database
    clock is the only clock that times these rows).

    TENANT ISOLATION (T-15.2-51). This runs inside `persist_tribunal_claims`'
    existing `set_tenant_context(session, tenant_id)` and the caller's
    transaction. `tenant_id` is written explicitly on the row and migration
    0013's FORCE RLS + `WITH CHECK` policy is the ENFORCEMENT -- there is
    deliberately no application-level tenant filter here, because a second place
    that decides which tenant a row belongs to is a second place to get it wrong.
    """
    await session.execute(
        text(
            "INSERT INTO research_gap (id, tenant_id, run_id, provider, text) "
            "VALUES (:id, :tid, :rid, :provider, :text)"
        ),
        {
            "id": str(uuid.uuid4()),
            "tid": str(tenant_id),
            "rid": str(run_id),
            "provider": provider,
            "text": text_value,
        },
    )


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


def _as_list(value: object) -> list:
    """`value` if it is a sequence of items, else an empty list.

    A STRING is deliberately NOT a sequence of items here. Every field this
    guards (`source_urls`, `evidence_refs`, `citations`) is model-authored, and
    iterating a bare string yields its CHARACTERS -- which then pass the
    `isinstance(url, str)` test one at a time and become one-character source
    rows. The empty list is the honest reading of a field that is not a list.
    """
    if isinstance(value, (list, tuple)):
        return list(value)
    return []


def _gather_source_urls(claims: list[dict], verdicts_by_claim: dict) -> list[str]:
    """Every source URL `claims` would upsert, de-duplicated, in first-seen order.

    ONE extraction, called from TWO places, which is the whole reason it exists
    as a function (D-V01-11):

      * the RESOLUTION PRE-PASS in `pipeline/tribunal/pipeline.py` Stage 7, over
        the whole run's claims at once, BEFORE any session is opened;
      * the per-claim loop in `persist_tribunal_claims` below, called with a
        single-element list.

    If those two views could drift, the pre-pass would resolve a set of URLs that
    is not the set the loop then upserts, and the difference would show up as
    citations silently missing their publisher URL for no stated reason. Calling
    the same function from both makes drift impossible rather than unlikely.

    NOTE ON DEDUPE. The de-duplication here is PER CALL. Called with one claim it
    reproduces exactly the per-claim dedupe this loop has always done; called
    with every claim it produces the run-wide unique set D-V01-11 asks for --
    V-01's 642 citation instances collapsing to 225 unique URLs. The per-claim
    dedupe alone is NOT sufficient for resolution: the same redirect is cited by
    many different claims, so it would still issue 642 requests.

    Nothing raises: a claim that is not a dict, a verdict that is not a dict, a
    citation of an unexpected shape and a non-string URL are each skipped.
    """
    verdicts_by_claim = verdicts_by_claim or {}
    source_urls: list[str] = []

    for claim in claims or []:
        if not isinstance(claim, dict):
            continue

        # From the claim dict (e.g., source_urls or evidence_refs added by
        # intake/distiller).
        #
        # `_as_list` guard added with the extraction: these keys are
        # model-authored, and a STRING here used to be iterated CHARACTER BY
        # CHARACTER, so `"unknown"` silently became seven one-character source
        # rows. A shape that is not a list is not a list of URLs.
        for url_field in ("source_urls", "evidence_refs"):
            for url in _as_list(claim.get(url_field)):
                if url and isinstance(url, str):
                    source_urls.append(url)

        # From skeptic verdict(s) for this claim -- SAME normalisation the
        # verdict writes use, via `_verdicts_for`, so the two views of
        # verdicts_by_claim cannot diverge either.
        for claim_verdict in _verdicts_for(claim, verdicts_by_claim):
            for ref in _as_list(claim_verdict.get("evidence_refs")):
                if ref and isinstance(ref, str):
                    source_urls.append(ref)
            for citation in _as_list(claim_verdict.get("citations")):
                if isinstance(citation, dict):
                    url = citation.get("url") or citation.get("source_url") or ""
                elif isinstance(citation, str):
                    url = citation
                else:
                    url = ""
                # `isinstance` guard added with the extraction: a citation dict
                # whose `url` is model-authored and not a string used to reach
                # the `.strip()` below and raise inside the persistence step of
                # a paid run.
                if url and isinstance(url, str):
                    source_urls.append(url)

    # De-duplicate while preserving order.
    seen_urls: set[str] = set()
    deduped_urls: list[str] = []
    for url in source_urls:
        url = url.strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            deduped_urls.append(url)
    return deduped_urls


async def _link_claim_source(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    claim_id: uuid.UUID,
    source_id: uuid.UUID,
    snippet: Optional[str] = None,
    provider_quality: Optional[str] = None,
) -> None:
    """Link one claim to one source. `provider_quality` is D-13, ADDITIVE.

    `provider_quality` is what the PROVIDER said about the source it cited
    ('official' / 'press' / 'other'), clamped here as well as at parse time;
    anything else becomes NULL with a warning. `citations/numbering.py` prefers
    it over `derive_quality_tier`'s domain heuristic, so an unrecognised word
    costs the provider's opinion and falls back to the heuristic -- it can never
    invent a tier.

    The `ON CONFLICT (claim_id, source_id) DO NOTHING` clause is UNCHANGED and
    load-bearing for exactly that reason: a repeat link stays a no-op, so a
    second claim citing the same source cannot overwrite the first claim's
    grading of it.
    """
    quality_value = _clamp_enum(
        provider_quality, _QUALITY_VALUES, field="claim_source.provider_quality"
    )
    await session.execute(
        text(
            "INSERT INTO claim_source "
            "(claim_id, source_id, tenant_id, snippet, provider_quality) "
            "VALUES (:cid, :sid, :tid, :snippet, :quality) "
            "ON CONFLICT (claim_id, source_id) DO NOTHING"
        ),
        {
            "cid": str(claim_id),
            "sid": str(source_id),
            "tid": str(tenant_id),
            "snippet": snippet,
            "quality": quality_value,
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
    research_gaps: Optional[list[dict]] = None,
    resolved_urls: Optional[dict[str, Optional[str]]] = None,
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
        research_gaps:    D-13 (Phase 15.2). The things a research provider explicitly
                          reported it could NOT establish, as
                          `[{"provider": str, "text": str}, ...]`. One `research_gap`
                          row is written per surviving entry, inside this function's
                          own `set_tenant_context` and the caller's transaction.
                          15.2-06's "What we could not establish" report section reads
                          these rows straight back out of the table, so an absent fact
                          is stated honestly instead of silently omitted. A run where
                          every stream established everything it looked for writes NO
                          rows, and that is the healthy case, not a missing feature.
                          Keyword-optional and defaulted to None so every pre-existing
                          call shape stays valid.

                          Every value here is model-authored, so it is bounded before
                          it is written: blank provider or text is skipped, text is
                          truncated to `_RESEARCH_GAP_MAX_CHARS`, provider to
                          `_GAP_PROVIDER_MAX_CHARS`, the `(provider, text)` pair is
                          de-duplicated order-preservingly, and the total is capped at
                          `_MAX_RESEARCH_GAPS` with the exact dropped count logged.

        resolved_urls:    D-V01-11 (Phase 15.4). The redirect -> publisher-URL map the
                          CALLER resolved, keyed by source URL. It is produced by the
                          resolver in `citations/redirect_resolver.py`, and it is
                          produced BEFORE the caller opens the session and the
                          transaction this function runs inside -- deliberately, and
                          asserted by an ordering test. Resolving here would put up to
                          30 s of network I/O inside the final persistence transaction
                          of a ~$50 run, holding a pooled connection with RLS tenant
                          context set, for an ENRICHMENT that is by design allowed to
                          fail. So this function only ever READS the finished map; the
                          resolver is not reachable from it at all.

                          Keyword-optional and defaulted to None so every pre-existing
                          call shape stays valid unchanged. None means resolution was
                          NEVER ATTEMPTED, and every source row written then carries
                          `resolved_url` and `resolution_status` NULL -- byte-identical
                          to the behaviour before this parameter existed.

                          A URL that FAILED to resolve is still upserted, marked
                          `'unresolved'`. Turning resolution on or off changes zero
                          citations; it only changes what is known about them.

    Returns:
        {"claim_ids": [uuid, ...], "source_ids": [uuid, ...],
         "verdict_ids": [uuid, ...], "verdict_count": int,
         "research_gap_count": int}

        `research_gap_count` is ADDITIVE — the four pre-existing keys are unchanged.
    """
    # D-V01-11. `is_redirect_url` is imported FUNCTION-LOCALLY and it is the only
    # thing this module ever takes from the resolver package: a pure predicate
    # over a string, with no client, no request and no I/O. The resolver's own
    # entry point is deliberately NOT imported anywhere in this file, and a test
    # asserts that it is not — so no future edit can start resolving inside the
    # caller's transaction by adding one line here. The import is function-local
    # so `httpx` is not pulled into this module's import graph either.
    from nestor_pulse_sdk.citations.redirect_resolver import is_redirect_url

    await set_tenant_context(session, tenant_id)

    # An empty map is the "never attempted" case and is read exactly like None:
    # no URL is a member, so every `resolution_status` below comes out NULL.
    resolved_map = resolved_urls or {}

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

        # Insert ONE fine-grained claim row per survivor.
        #
        # D-13: `certainty` and `found_by` come straight off the claim dict the
        # merge produced. `certainty` is the PROVIDER's own confidence word (or
        # the cautious `single` if any stream that stated this fact only found it
        # once); `found_by` is the corroboration signal — which research streams
        # stated this fact — that `_dedupe_claims` unioned across streams. Both
        # are clamped and bounded inside `_insert_claim`.
        #
        # D-R3 (Phase 15.5): `sub_question`, `corroboration_key` and `as_of`
        # ride on the SAME claim dict, and they are read here with `.get()` and
        # passed straight through. Nothing is re-derived, re-parsed or defaulted
        # at this call site: a SECOND place that decides what a claim's
        # attribution is, is a second place to get it wrong -- the reasoning
        # `_insert_research_gap`'s docstring records for `tenant_id`. Clamping
        # and NULL-coercion belong to `_insert_claim`, which owns them.
        #
        # `sub_question` and `corroboration_key` were stamped in PYTHON from the
        # dispatch assignment in `collect_provider_facts`, never parsed out of
        # model output; `as_of` came through `extract_as_of`'s grammar over the
        # EVIDENCE cell, which rejects every ambiguous form rather than guessing.
        #
        # TWO EXPECTED SOURCES OF NULL, BOTH CORRECT, NEITHER A BUG:
        #   * `corroboration_key` is NULL for roughly 12 of 15 winners. Only the
        #     TOP-3 winners are dealt a key (`w01`/`w02`/...); the remainder is
        #     dealt round-robin with the empty string, which `_insert_claim`
        #     writes as NULL. The column fills up in phase 15.6, when every group
        #     goes to every provider.
        #   * The `claim_distiller` fallback path carries NO dispatch attribution
        #     at all, by construction -- there was no angle to inherit from -- so
        #     claims from it are permanently NULL on the first two.
        #
        # `.get()` and never a subscript: this function is also reached by the
        # recorded-fixture loader and by tests that build claim dicts by hand,
        # and a claim dict that predates phase 15.5 has none of the three keys.
        # It must keep working and write NULLs.
        claim_id = await _insert_claim(
            session,
            tenant_id=tenant_id,
            run_id=run_id,
            claim_text=claim_text,
            facet=facet,
            position=position,
            certainty=claim.get("certainty"),
            found_by=claim.get("found_by"),
            sub_question=claim.get("sub_question"),
            corroboration_key=claim.get("corroboration_key"),
            as_of=claim.get("as_of"),
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

        # Gather source URLs from the claim itself + from skeptic verdicts.
        # THE SAME function the resolution pre-pass called over the whole run's
        # claims before this transaction was opened (D-V01-11) — called here
        # with a single-element list so the two views cannot drift.
        deduped_urls = _gather_source_urls([claim], verdicts_by_claim)

        # D-13 per-URL grading. `provider_quality_by_url` is the map
        # `_dedupe_claims` builds when two streams' versions of one fact merge —
        # it keeps each URL graded by the provider that SUPPLIED it. The scalar
        # `provider_quality` is the un-merged single-provider case. A URL that
        # neither covers (a skeptic's own web_fetch citation, say) is graded
        # NULL and falls through to `derive_quality_tier`'s domain heuristic.
        quality_by_url = claim.get("provider_quality_by_url")
        if not isinstance(quality_by_url, dict):
            quality_by_url = {}
        claim_quality = claim.get("provider_quality")

        # D-13 `source.title`. WHY THIS MATTERS: for the Gemini streams EVERY
        # url is a `https://vertexaisearch.cloud.google.com/grounding-api-
        # redirect/...` redirect, so the graded `## Sources` renderer's domain
        # fallback would label every single Gemini source
        # `vertexaisearch.cloud.google.com` — actively misleading, not merely
        # unhelpful. `source_domain` is the display domain 15.2-04 resolved from
        # the provider's OWN markdown link label, so it is the provider's label
        # and never an invented title. 15.2-05 added the parameter and left it
        # unused by production callers; this is the plan that supplies it.
        # (`title` is NOT part of `content_hash`, so supplying it cannot change
        # source dedupe, and an existing row keeps the title it already had.)
        source_title = str(claim.get("source_domain") or "").strip() or None
        if source_title:
            source_title = source_title[:_SOURCE_TITLE_MAX_CHARS]

        # Upsert source rows + link claim_source rows
        for url in deduped_urls:
            # D-V01-11. THREE STATES, and they are not interchangeable:
            #   NULL         the URL was never a resolution candidate (an
            #                ordinary publisher URL) or no map was supplied at
            #                all -- nothing was ever attempted for it;
            #   'resolved'   a redirect whose publisher URL came back;
            #   'unresolved' a redirect that WAS attempted and did not resolve.
            #
            # The last two must never collapse into the first. `'unresolved'` is
            # a citation whose publisher URL is about to be lost when the
            # redirect expires ~30 days after the run; NULL is a citation that
            # never needed one. Recording both as NULL would erase the
            # difference and make the loss unfindable.
            #
            # AND THE ROW IS WRITTEN EITHER WAY. Resolution failing NEVER skips
            # the upsert: the redirect itself is still the citation. That is
            # D-V01-11's rule verbatim -- keep the redirect and mark it
            # unresolved, never drop a citation.
            resolved_target = resolved_map.get(url)
            if url not in resolved_map or not is_redirect_url(url):
                resolution_status = None
            elif resolved_target:
                resolution_status = "resolved"
            else:
                resolution_status = "unresolved"

            sid = await _upsert_source(
                session,
                tenant_id=tenant_id,
                url=url,
                provider="tribunal_skeptic",
                snapshot_text=url,  # minimal snapshot; Phase 2 can enrich
                title=source_title,
                resolved_url=resolved_target,
                resolution_status=resolution_status,
            )
            source_ids.append(sid)
            await _link_claim_source(
                session,
                tenant_id=tenant_id,
                claim_id=claim_id,
                source_id=sid,
                provider_quality=quality_by_url.get(url) or claim_quality,
            )

    # ------------------------------------------------------------------------
    # D-13: the couldn't-find lists become `research_gap` rows.
    # ------------------------------------------------------------------------
    # These are the things a provider said, in its own words, that it could NOT
    # establish. Without them "What we could not establish" is an empty heading
    # and an unfound fact is indistinguishable from a fact nobody looked for.
    #
    # Every value is model-authored, so every value is BOUNDED before it is
    # written (T-15.2-55), and every truncation says exactly how much it dropped.
    # Every INSERT runs under this function's own `set_tenant_context` above and
    # inside the caller's transaction — 0013's FORCE RLS `WITH CHECK` policy is
    # the control, and no second, weaker tenant setup is added here (T-15.2-51).
    research_gap_count = 0
    if research_gaps:
        seen_gaps: set = set()
        bounded_gaps: list[tuple[str, str]] = []
        for entry in research_gaps:
            if not isinstance(entry, dict):
                continue
            gap_provider = str(entry.get("provider") or "").strip()
            gap_text = str(entry.get("text") or "").strip()
            if not gap_provider or not gap_text:
                # A gap with no attribution cannot be rendered per provider, and
                # a gap with no text says nothing. Neither is worth a row.
                continue
            gap_provider = gap_provider[:_GAP_PROVIDER_MAX_CHARS]
            gap_text = gap_text[:_RESEARCH_GAP_MAX_CHARS]
            pair = (gap_provider, gap_text)
            if pair in seen_gaps:
                continue
            seen_gaps.add(pair)
            bounded_gaps.append(pair)

        if len(bounded_gaps) > _MAX_RESEARCH_GAPS:
            log.warning(
                "persist_tribunal_claims: %d research gaps exceed the %d cap — "
                "%d dropped and NOT written (run_id=%s)",
                len(bounded_gaps), _MAX_RESEARCH_GAPS,
                len(bounded_gaps) - _MAX_RESEARCH_GAPS, str(run_id),
            )
            bounded_gaps = bounded_gaps[:_MAX_RESEARCH_GAPS]

        for gap_provider, gap_text in bounded_gaps:
            await _insert_research_gap(
                session,
                tenant_id=tenant_id,
                run_id=run_id,
                provider=gap_provider,
                text_value=gap_text,
            )
            research_gap_count += 1

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
        "persist_tribunal_claims done: %d claims / %d sources / %d verdicts / "
        "%d research gaps (run_id=%s)",
        len(claim_ids),
        len(source_ids),
        len(verdict_ids),
        research_gap_count,
        str(run_id),
    )
    return {
        "claim_ids": claim_ids,
        "source_ids": source_ids,
        "verdict_ids": verdict_ids,
        "verdict_count": len(verdict_ids),
        "research_gap_count": research_gap_count,
    }
