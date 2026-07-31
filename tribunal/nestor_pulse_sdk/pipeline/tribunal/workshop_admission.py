"""The D-R10 ADMISSION GATE — how an angle the loop INVENTED earns a research slot.

WHY THIS MODULE EXISTS. D-R6 makes evolve generative: it may COMBINE two winners,
EXTEND one, INVERT one, SPECIALISE one — and, under D-R10, it may INVENT an angle
outright in any round. `"no source, no slot"` is not weakened by that; it MOVES,
from *"only orientation may originate an angle"* to *"only evidence may admit
one"*. This module is that evidence gate: a cheap grounded lookup runs once per
invented angle, and the angle either earns a slot on a real source or is dropped
with a reason the loop can turn into a bar.

FOUR THINGS A LATER READER NEEDS, ALL OF THEM MEASURED.

1. **THE TEST IS THE PREMISE, NOT THE ANSWER — and the original specification had
   it backwards.** Read as *"is there a published answer to this?"*, the admission
   rule rejected **all four** invented angles in the measurement harness. **Zero
   survived.** Among the rejected: *"what minimum network density is required for
   algorithmic pricing to pay off"* — exactly the strategic question a mid-sized
   player weighing expansion needs, and exactly what D-R10 exists to admit. The
   rule as written admits angles that are ALREADY DOCUMENTED (already known, so low
   research value) and rejects NOVEL ones (nobody has published it, so high
   research value). **It is a novelty filter pointed backwards.** The corrected
   test, and the one implemented here, verifies that the PREMISE IS REAL: do the
   named entities, markets, mechanisms and metrics EXIST, and could desk research
   plausibly settle this — never, has someone already settled it.

2. **THE `groundingChunks` SUBSTITUTION.** D-R10's implementation note says the
   admission evidence must come from `groundingChunks`. **THIS ENGINE HAS NO
   `groundingChunks`.** That is a Gemini grounded-search concept, and it is what
   the measurement harness happened to run on; the deployed workshop orients
   through ANTHROPIC SERVER-SIDE TOOLS. The equivalent real-search-result channel
   in this codebase is `skeptic._collect_citation_urls(content)` — the very
   function `workshop._one_orientation` already uses to accumulate the URLs an
   orientation session actually fetched. It reads three block types and nothing
   else: `web_search_tool_result` (a list of `web_search_result`, each carrying a
   url), `web_fetch_tool_result` (a `web_fetch_result` carrying a url), and `text`
   (whose `.citations` may carry a url). **That is the channel, and it is used
   here.** The decision's INTENT — the evidence comes from a real search result and
   NEVER from the model's own output line — is honoured exactly; only the vendor
   noun changes. Do not go hunting for a `groundingChunks` reader: one was never
   going to exist here.

3. **THE HARNESS'S OWN BUG IS WHY THE GATE IS SHAPED LIKE THIS.** A guard of the
   form `if not url` admitted **2 of 3** angles carrying a literal `"-"` as the
   URL — **because a dash is truthy** — where the model had "evidenced" its own
   angle by tautologically restating that its own entities exist. So: the URL is
   never read out of the `emit_admission` tool input (that is the model's own
   output line, and `EMIT_ADMISSION_TOOL` therefore has no URL field at all), an
   `http(s)` URL is REQUIRED, and an absent or non-URL source is **NOT FOUND**.
   Without this the grounded lookup is theatre and `"no source, no slot"` is
   enforced by nothing at all.

4. **THIS MODULE DOES NOT DECIDE HOW MANY DISCOVERY QUESTIONS RUN.** D-W3-4's
   allocation is unchanged and still bounds what is DISPATCHED — at most 5
   discovery slots globally, a per-parent cap of 3, never borrowing from the
   mandate, unused slots rolling back to the mandate. `discovery_bracket.
   allocate_discovery` is untouched by this module. **D-R10 widens where candidates
   may COME FROM, not how many run.**

WHAT TO EXPECT, AND IT IS NOT WHAT THE RULING ASSUMED. Measured, the loop earns its
keep — 5 of 10 research slots were loop-generated — but **the value comes from the
MUTATION moves, not from INVENT**: all five top-10 newcomers were COMBINE / INVERT
/ EXTEND, and the single surviving INVENT ranked **16, below the cut**, even though
its content was excellent (German *Ladenschlussgesetz* exceptions for petrol
stations, and which product categories are legally excluded — the mechanism under
the client's whole premise, which no original candidate touched). **Do not judge
this feature by INVENT's survival rate, and do not delete it on that basis.**

EVERY FUNCTION HERE NEVER RAISES. `admission_evidence` is additionally PURE and
touches no network, so the whole evidence rule is drivable in a plain interpreter;
the two impure functions are thin shells over it.
"""

from __future__ import annotations

import logging
import uuid  # noqa: F401 — used in the postponed annotations below
from typing import TYPE_CHECKING, Any, Optional

from nestor_pulse_sdk.citations.redirect_resolver import is_redirect_url
from nestor_pulse_sdk.pipeline.tribunal.discovery_bracket import (
    _DISCOVERY_TEXT_CHARS,
    _norm,
    _norm_url,
)
from nestor_pulse_sdk.pipeline.tribunal.skeptic import _collect_citation_urls

if TYPE_CHECKING:  # pragma: no cover — typing only
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient
    from nestor_pulse_sdk.runs.stage_feed import StageFeed

log = logging.getLogger(__name__)

__all__ = [
    "admission_evidence",
]


# ---------------------------------------------------------------------------
# The three resolution states, named. D-V01-11's rule is STORE BOTH, side by side:
# keep the redirect AND the resolved publisher URL, and MARK an unresolved one
# rather than discarding it. These three names are the shape the persistence layer
# already distinguishes (`citations/extractor.py`): a URL absent from the resolved
# map was NEVER REQUESTED and stores as NULL, a URL present with a None value was
# ATTEMPTED AND FAILED and stores as `unresolved`, and a URL present with a string
# value stores as that publisher URL.
#
# The two "nothing was stored" cases share one name deliberately. They are the same
# fact — no publisher URL is known — and splitting them here would invent a fourth
# state that nothing downstream reads.
# ---------------------------------------------------------------------------

#: A publisher URL is known.
RESOLUTION_RESOLVED = "resolved"

#: It IS a grounding redirect, resolution was attempted, and it failed. The
#: redirect is KEPT — a redirect that did not resolve is still a real source, and
#: discarding it would let a transient network failure silently reject an angle
#: that had genuine evidence behind it.
RESOLUTION_UNRESOLVED = "unresolved"

#: No resolution was attempted: either the URL is not on the redirect host at all,
#: or no resolution map was supplied to this call.
RESOLUTION_NOT_ATTEMPTED = "not_attempted"


def _first(value: Any) -> str:
    """`value` as a plain stripped string, never raising."""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # noqa: BLE001 — an unprintable value is empty, never a crash
        return ""


def admission_evidence(
    content: Any, *, resolved: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """The evidence that admits ONE invented angle, read from REAL SEARCH RESULTS.

    PURE. NEVER RAISES. NO NETWORK. This is the whole of D-R10's critical
    implementation note, and it is deliberately drivable without a provider.

    `content` is the accumulated content-block list of an admission session. The
    URLs are pulled with `skeptic._collect_citation_urls`, which reads ONLY
    `web_search_tool_result`, `web_fetch_tool_result` and `text` `.citations`
    blocks — the three places a SERVER TOOL puts a URL it actually fetched. **A
    `tool_use` block is not one of them, which is the point**: the URL is never
    read out of the `emit_admission` tool input, because that is the model's own
    output line rather than evidence, and a model restating that its own entities
    exist has evidenced nothing.

    **TREAT AN ABSENT OR NON-URL SOURCE AS NOT FOUND** — the decision's own
    wording. Every surfaced value must survive `discovery_bracket._norm_url`
    (Wave 3's CR-02 fix: collapse whitespace, REFUSE if a space survives, `http(s)`
    scheme gate, 300-character cap), so a literal `"-"`, an empty string, `None`,
    `"n/a"`, `"javascript:alert(1)"` and a URL with an interior space all yield
    `found: False`. A dash is truthy; `if not url` is not a source check.

    `resolved` is the map `citations.redirect_resolver.resolve_redirects` returns,
    supplied by the caller for the WHOLE BATCH at once — deduping there rather than
    per angle is the entire point of D-V01-11. Both values are kept side by side
    and an unresolved redirect is MARKED, never discarded.

    Returns a plain dict:
        found             bool   — explicit, never inferred from a truthy string
        source_url        str    — the first surviving real-search-result URL
        resolved_url      str    — its publisher URL when one is known, else ""
        resolution_status str    — one of the three RESOLUTION_* constants
        source_urls       list   — every surviving URL, order preserved, deduped
    """
    empty: dict[str, Any] = {
        "found": False,
        "source_url": "",
        "resolved_url": "",
        "resolution_status": RESOLUTION_NOT_ATTEMPTED,
        "source_urls": [],
    }

    try:
        blocks = content if isinstance(content, list) else []
        raw_urls = _collect_citation_urls(blocks)
    except Exception as exc:  # noqa: BLE001 — hostile content is input, not an error
        log.debug("admission: could not read the content blocks (%r) — no evidence", exc)
        return empty

    surviving: list[str] = []
    for raw in raw_urls or ():
        url = _norm_url(raw)
        if not url:
            # NOT a failure to log loudly: a search-result block legitimately
            # carries values this bound refuses. The DROP that matters — an angle
            # with no surviving URL at all — is named by the caller.
            continue
        if url not in surviving:
            surviving.append(url)

    if not surviving:
        return empty

    source_url = surviving[0]
    status = RESOLUTION_NOT_ATTEMPTED
    resolved_url = ""

    if isinstance(resolved, dict) and is_redirect_url(source_url):
        if source_url in resolved:
            publisher = _norm_url(resolved.get(source_url))
            if publisher:
                status = RESOLUTION_RESOLVED
                resolved_url = publisher
            else:
                # Attempted and failed. KEEP the redirect and MARK it — D-V01-11
                # stores BOTH columns, and a redirect that did not resolve is
                # still the URL a real search returned.
                status = RESOLUTION_UNRESOLVED

    return {
        "found": True,
        "source_url": source_url,
        "resolved_url": resolved_url,
        "resolution_status": status,
        "source_urls": list(surviving),
    }
