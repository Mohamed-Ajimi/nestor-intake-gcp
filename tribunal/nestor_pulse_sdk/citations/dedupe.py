"""THE ONE SOURCE-IDENTITY KEY (Phase 22, D-22-4).

WHY THIS MODULE EXISTS
----------------------
Two layers have to agree about what "the same source" means:

  * THE READ PATH, now -- `verification/report.py` collapses the citation list so
    one URL renders as one `[n]` (plan 22-05).
  * THE WRITE PATH, next -- the `source` INSERT conflict key becomes a normalized
    URL so new runs stop creating duplicate rows (its own phase: it needs Alembic
    0019, and the existing `idx_source_tenant_content_hash` UNIQUE index must be
    dropped in the SAME migration or a same-text/different-URL pair raises an
    unhandled IntegrityError inside the persist transaction of a ~$45 run).

THE ONLY WAY TWO LAYERS CAN AGREE IS IF THEY CALL THE SAME FUNCTION. Two layers
that normalize differently reintroduce the exact defect D-22-4 exists to fix, one
level down -- and one level down is harder to see, because the read path would
then be papering over rows the write path had already split. So this module is
deliberately PURE: no DB, no network, no ORM, stdlib only. It is importable from
either side without dragging a session in.

WHAT THE DEFECT ACTUALLY IS
---------------------------
Not "text vs URL". The live Tribunal path already calls
`_upsert_source(snapshot_text=url)` (`citations/extractor.py:1100`), so the
conflict key is already `sha256(url)`. The real defect is RAW URL vs NORMALIZED
URL, and the dominant duplicate generator is gemini
`vertexaisearch.cloud.google.com` grounding redirects, where every citation of one
page arrives as a different opaque token.

That is why `resolved_url` is LOAD-BEARING here, not a refinement: stripping
`www.`, a trailing slash and tracking params collapses NONE of those tokens. Only
the resolved target can, and only where the best-effort HEAD resolution succeeded
-- so there is a real ceiling on how much this collapses, and it is not knowable
before a run. This module makes no claim about yield.
"""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlparse


# ---------------------------------------------------------------------------
# Tracking parameters -- a CLOSED set, deliberately NOT a prefix rule.
# ---------------------------------------------------------------------------
#
# ⚠ THE BARE THREE-LETTER `ref` IS DELIBERATELY ABSENT, and this comment is what
# stops a future editor adding it. That parameter is real and meaningful on git
# hosts, docs sites and APIs -- it frequently selects WHICH DOCUMENT is served.
# Stripping it would merge distinct documents into one `[n]`: the opposite failure
# from the one being fixed, and a worse one, because a wrong citation is worse
# than a duplicated one. `ref_src` / `ref_url` (twitter) are unambiguous tracking
# and ARE stripped. Pinned by
# `test_the_bare_ref_parameter_is_preserved_because_it_is_meaningful`.
#
# A prefix rule over that stem is banned for the same reason.
_TRACKING_PARAMS = frozenset(
    {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "utm_name",
        "utm_reader",
        "gclid",
        "gbraid",
        "wbraid",
        "dclid",
        "msclkid",
        "fbclid",
        "yclid",
        "twclid",
        "ttclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "_hsenc",
        "_hsmi",
        "vero_id",
        "vero_conv",
        "ref_src",
        "ref_url",
        "spm",
        "scm",
    }
)

# ---------------------------------------------------------------------------
# Do NOT do any of these. Each one MERGES GENUINELY DIFFERENT DOCUMENTS, which is
# the opposite defect from the one this module fixes and strictly worse than it:
#
#   * lowercase the path            -- paths are case-sensitive on most origins
#   * strip `index.html` / `default.aspx` -- these are not always equivalent to
#                                     the directory URL, and where they are, the
#                                     origin says so with a redirect
#   * normalize percent-encoding    -- `%2F` and `/` are not interchangeable in a
#                                     path segment
#   * strip ALL query parameters    -- the query is frequently the document
#                                     selector (see the `ref` note above)
#   * resolve relative or `..` segments -- no base URL is available here, so any
#                                     resolution would be a guess
#
# The one deliberate exception is the query: survivors are re-encoded by
# `urlencode` so that parameter ORDER cannot split one document into two keys.
# That re-encoding is scoped to the query alone and never touches the path.
# ---------------------------------------------------------------------------

_DEFAULT_PORTS = {"http": "80", "https": "443"}


def _strip_default_port(netloc: str, scheme: str) -> str:
    """Drop `:80` on http and `:443` on https; keep every other port.

    A non-default port is a DIFFERENT ORIGIN, not a formatting difference, so it
    stays in the key.
    """
    if netloc.endswith("]"):
        # A bracketed IPv6 literal with no port -- `[::1]`. Nothing to strip, and
        # rpartition below would otherwise chop inside the address.
        return netloc
    head, sep, tail = netloc.rpartition(":")
    if not sep or not tail.isdigit():
        return netloc
    if _DEFAULT_PORTS.get(scheme) == tail:
        return head
    return netloc


def normalize_source_url(
    url: str | None,
    resolved_url: str | None = None,
    resolution_status: str | None = None,
) -> str | None:
    """Return the canonical identity key for one source, or None.

    A TOTAL function: it NEVER raises, on any input, including non-strings
    (T-22-01). `resolved_url` reaches this function from a remote `Location`
    header (`citations/extractor.py:109-115`), so it is attacker-influenceable,
    and read-path code that raises takes down a report the operator has already
    paid for. The result is used ONLY as a dict key -- never to build a request.

    Steps, in order:
      1. pick `resolved_url` when `resolution_status == "resolved"` and it is a
         non-empty string; otherwise `url`
      2. guard: non-string / blank / unparseable -> None
      3. trim
      4. lowercase the scheme, then DROP it from the key (`http` and `https` of
         one page are one source -- an orchestrator decision recorded in
         22-CONTEXT.md that widens D-22-4's literal wording)
      5. host: lowercase, strip a leading `www.`, drop a default port
      6. fragment: dropped entirely -- it addresses a position WITHIN a document
      7. query: drop `_TRACKING_PARAMS`, sort the survivors, re-encode
      8. path: strip exactly ONE trailing `/`, and case is PRESERVED
      9. assemble `host + path`, plus `?query` when the query is non-empty

    Returns None rather than `""` for an input that yields no key at all, so that
    two unrelated unusable URLs can never collide on a falsy key.
    """
    # 1. Pick the input. The status gate is EXPLICIT: 'unresolved' means resolution
    #    was attempted and failed, and gating on the status (rather than merely on
    #    `resolved_url` being truthy) survives a future partial write that stores a
    #    target without marking it resolved.
    if (
        resolution_status == "resolved"
        and isinstance(resolved_url, str)
        and resolved_url.strip()
    ):
        candidate = resolved_url
    else:
        candidate = url

    # 2. Guard.
    if not isinstance(candidate, str):
        return None
    candidate = candidate.strip()  # 3. Trim.
    if not candidate:
        return None

    # `except Exception` is the same posture as `numbering.py::_domain` -- a
    # malformed url simply has no derivable key.
    try:
        parsed = urlparse(candidate)

        # 4. Scheme: lowercased for the port comparison below, then discarded.
        scheme = (parsed.scheme or "").lower()

        # 5. Host.
        host = (parsed.netloc or "").lower()
        host = _strip_default_port(host, scheme)
        if host.startswith("www."):
            host = host[4:]

        # 6. Fragment: never read.

        # 7. Query. `keep_blank_values=True` so `?q=` is not silently lost -- it is
        #    a different request from no query at all.
        pairs = parse_qsl(parsed.query or "", keep_blank_values=True)
        kept = [(k, v) for k, v in pairs if k.lower() not in _TRACKING_PARAMS]
        kept.sort()
        query = urlencode(kept)

        # 8. Path. NOT lowercased -- see the "Do NOT" block above.
        path = parsed.path or ""
        if path == "/":
            path = ""
        elif path.endswith("/"):
            path = path[:-1]

        # 9. Assemble. Scheme-free by step 4.
        key = f"{host}{path}"
        if query:
            key = f"{key}?{query}"
    except Exception:  # noqa: BLE001 -- a malformed url just has no identity key
        return None

    return key or None


def collapse_citations_by_url(
    numbered: list[dict[str, Any]],
    resolution: Mapping[str, tuple[str | None, str | None]] | None = None,
) -> list[dict[str, Any]]:
    """Collapse `number_citations` entries to ONE per normalized URL.

    `numbered` is the list `citations/numbering.py::number_citations` returns (its
    10-key entry shape, documented at `numbering.py:274-287`). `resolution` maps
    `source_id` -> `(resolved_url, resolution_status)`; absent or incomplete is
    fine -- a source with no entry there is normalized from its raw `url`.

    ⛔ THIS FUNCTION ASSIGNS NO NUMBERS. NOT ONE. It never derives a number from a
    loop position, and it never writes to any entry's number field.

    THE REASON, because a future editor WILL want to close the gaps: the
    deliverable report markdown's `[n]` markers were baked at synthesis by
    `apply_citation_anchors` (`pipeline/tribunal/pipeline.py:4533`) and FROZEN
    there -- that document has already been generated, downloaded and paid for,
    and nothing can update it. The verification report PAGE, by contrast, renders
    every marker from `citation.n` at paint time. So renumbering here would make
    `[7]` on the page a DIFFERENT SOURCE from `[7]` in the report the operator is
    holding, silently, on both surfaces at once.

    Therefore every survivor keeps exactly the number `number_citations` gave it,
    and the emitted list goes SPARSE -- 1, 2, 4, 7, ... THAT SPARSENESS IS CORRECT.
    It is the honest, visible cost of collapsing duplicates on the read side, and
    tidying it away would trade a cosmetic gap for a wrong citation.

    Ordering: `numbered` arrives in `_CLAIM_SOURCE_SQL`'s pinned first-appearance
    order, so "the first time a key is seen" IS "the lowest number for that key".
    The survivor is therefore deterministic without any sort.

    Absorbed entries are not discarded silently: each survivor carries
    `also_claim_ids`, the `first_claim_id` of every entry it absorbed. Without that
    alias a verdict row whose only source was absorbed would lose its marker.

    An entry whose URL normalizes to None is passed through UNCHANGED and is never
    merged with another such entry -- "both failed to parse" is not evidence that
    two rows are the same source, and merging on it would collapse unrelated
    citations into one number, which is the worse defect.

    Emits no yield figure. 22-UI-SPEC §1.6 bars an "N duplicates removed" reading
    from the page, and a field that exists is a field somebody will render.

    PURE: no DB, no I/O, never raises. The caller's list and its dicts are not
    mutated -- survivors are copies.
    """
    if not numbered:
        return []

    lookup: Mapping[str, tuple[str | None, str | None]] = resolution or {}

    collapsed: list[dict[str, Any]] = []
    canonical_by_key: dict[str, dict[str, Any]] = {}

    for entry in numbered:
        source_id = entry.get("source_id")
        resolved_url, status = lookup.get(str(source_id), (None, None))
        key = normalize_source_url(entry.get("url"), resolved_url, status)

        if key is None:
            # Unparseable: keep it exactly as it arrived, on its own.
            collapsed.append(entry)
            continue

        canonical = canonical_by_key.get(key)
        if canonical is None:
            # First sighting of this source. COPY rather than mutate: the caller's
            # list must not change under it.
            canonical = dict(entry)
            canonical["also_claim_ids"] = []
            canonical_by_key[key] = canonical
            collapsed.append(canonical)
            continue

        # A repeat: not emitted, but its claim id is carried forward.
        absorbed = entry.get("first_claim_id")
        aliases = canonical["also_claim_ids"]
        if (
            absorbed
            and absorbed != canonical.get("first_claim_id")
            and absorbed not in aliases
        ):
            aliases.append(absorbed)

    return collapsed
