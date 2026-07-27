"""D8 structured fact lists — the provider's own fact list as the primary claim source.

WHAT D8 IS
----------
Until now every claim reaching the Tribunal was produced by *prose distillation*: a
second model (`claim_distiller`) re-read a 53 KB research essay and guessed which
sentences were facts. D8 inverts that. The researcher that actually did the work is
asked to append a machine-readable fact list to its own report, and THAT list is the
primary claim source. The distiller becomes the fallback for a provider that ignores
the instruction (D-14), not the default path.

WHY THIS IS A PROMPT INSTRUCTION AND NOT STRUCTURED OUTPUT
---------------------------------------------------------
Structured-output mode is unavailable for these providers:
"citations ⊗ structured-outputs = HTTP 400" — recorded twice in the working tree,
at `pipeline/synthesis/steps.py:576-577` and again at `:626`. A deep-research call that
asks for grounded citations may not also ask for a JSON schema. So the format is a
prompt instruction the model may get wrong, and the parser is tolerant BY DESIGN.

UNTRUSTED-OUTPUT DISCIPLINE (ASVS V5)
-------------------------------------
Provider report text is not merely "a model we called": it embeds web pages the
provider chose to ingest, so it is an indirect-prompt-injection carrier. This module
follows, in substance, the discipline stated at `pipeline/tribunal/grouping.py:209-219`:

  * the output is PRE-FILLED and only overwritten by a line that validated;
  * every length and count is BOUNDS-CHECKED against an explicit cap;
  * garbled lines are IGNORED (counted, logged) rather than allowed to abort a batch;
  * raw model text is NEVER parsed as JSON (plain-text lines only — and the `json`
    module is deliberately not imported, so it cannot be);
  * NOTHING here raises: a malformed report degrades a run, it must not fail it;
  * every enum CLAMPS to a default that fails toward *more* checking (G-11), never
    toward less.

Attribution is structurally unforgeable: `provider` and `facet` are caller-supplied
arguments and are never read out of model text, the same rule
`_parse_distiller_response` states at `steps.py:679-681`.

WHAT THIS MODULE DOES NOT DO
----------------------------
  * No I/O of any kind — no network, no filesystem, no database, no LLM call. It is a
    pure transform, which is why every `nestor_pulse_sdk.*` import below is
    function-local and module scope is stdlib-only.
  * No deduplication. `_dedupe_claims` (`steps.py:723`) is the single normaliser and
    is applied ONCE by the caller, across all provider streams at once — deduping
    per-provider here would destroy the `found_by` corroboration signal it exists to
    merge.
  * No quality-tier table of its own — `citations/numbering.py::derive_quality_tier`
    is reused.
  * No second `[cite: N]` stripper — `audit/audited_llm_client.py::
    strip_unresolved_cite_markers` is reused.
  * No persistence. Writing `certainty` / `provider_quality` to the D-13 columns is
    plan 15.2-15; appending the prompt block to the provider prompts is 15.2-14.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:  # pragma: no cover — typing only, never imported at runtime
    from collections.abc import Mapping

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The D8 format contract — sentinels and vocabularies.
# ---------------------------------------------------------------------------

#: Fenced sentinels delimiting the machine-readable regions the provider appends to
#: its report. Same convention as `intake.py`'s RESEARCH_PROMPT_START/END: a bare
#: token on its own line, so a multi-line region is unambiguous and a dangling START
#: is still recoverable.
FACTS_START = "FACTS_START"
FACTS_END = "FACTS_END"
NOT_FOUND_START = "NOT_FOUND_START"
NOT_FOUND_END = "NOT_FOUND_END"

#: The provider's own assessment of its source. Anything outside this vocabulary
#: clamps to DEFAULT_QUALITY.
QUALITY_VALUES: tuple[str, ...] = ("official", "press", "other")
# G-11 — fail toward MORE checking: an unrecognised quality word must not be able to
# promote a blog to "official", so the default is the weakest value in the set.
DEFAULT_QUALITY = "other"

#: D-13's per-fact certainty marker: "certain" only when the provider says it
#: corroborated the fact across two or more independent sources.
CERTAINTY_VALUES: tuple[str, ...] = ("certain", "single")
# G-11 — fail toward MORE checking: an unrecognised certainty word degrades to
# "single", which sends the claim to the skeptics rather than waving it through.
DEFAULT_CERTAINTY = "single"


# ---------------------------------------------------------------------------
# Bounds. NESTOR_TRIBUNAL_* + default idiom (grouping.py:87-100), so a tuning
# change needs no code change to deploy.
#   _MAX_FACTS            facts accepted from ONE provider before the rest are
#                         dropped and counted.
#   _MAX_STATEMENT_CHARS  per-statement hard truncation (truncate, never drop — a
#                         long fact is still a fact).
#   _MAX_NOT_FOUND        entries accepted from the NOT_FOUND region.
# ---------------------------------------------------------------------------
_MAX_FACTS = int(os.environ.get("NESTOR_TRIBUNAL_FACTS_MAX_PER_PROVIDER", "400"))
_MAX_STATEMENT_CHARS = int(os.environ.get("NESTOR_TRIBUNAL_FACT_MAX_CHARS", "1200"))
_MAX_NOT_FOUND = int(os.environ.get("NESTOR_TRIBUNAL_NOT_FOUND_MAX", "100"))

#: Fixed bounds (not worth an env knob).
_MIN_STATEMENT_CHARS = 10   # mirrors _parse_distiller_response's drop rule
_MAX_URL_CHARS = 2048
_MAX_NOT_FOUND_CHARS = 400

#: Gemini grounded-search results are returned as opaque redirect URLs on this host;
#: the real domain survives only as the markdown link LABEL (Pitfall 10).
VERTEX_REDIRECT_HOST = "vertexaisearch.cloud.google.com"

#: The markdown link form used by BOTH the SOURCE_URL cell of a fact line and the
#: trailing numbered source list of a deep-research report. Quantifiers are bounded
#: so a hostile line cannot make this backtrack. Named distinctly from anything in
#: `citations/` on purpose — that tree is owned by another plan this wave.
_MD_LINK_RE = re.compile(r"\[([^\]\n]{1,200})\]\((https?://[^\s)]{1,2048})\)")

#: A candidate display domain must look like a hostname before it is believed. A
#: model-supplied label is untrusted text like everything else.
_DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{0,252}\.[a-z]{2,24}$", re.IGNORECASE)

#: Upper bound on the url -> label map built from one report (DoS guard).
_MAX_LABEL_INDEX = 2000

#: SOURCE_URL spellings that mean "I have no source", REJECTED BY NAME (D-M).
#:
#: `facts: rejecting non-http(s) SOURCE_URL 'N/A'` was observed live on run
#: `d6bb3aae`, and it was caught only as an ACCIDENT of the http(s) scheme test —
#: `N/A` happens not to parse as a URL. That is the wrong reason to be right: a
#: placeholder is a model stating plainly that it could not source the claim,
#: which is a different event from a malformed URL and deserves both its own
#: words in the log and its own test. Compared after `.strip().lower()`.
#:
#: THE TWO OUTCOMES DIFFER, DELIBERATELY:
#:   * a MALFORMED url -> the link is dropped, THE FACT SURVIVES. The model had a
#:     source and wrote it badly; losing the link must not lose the fact
#:     (`FactListResult.rejected_urls`, and its own test since 15.2-04).
#:   * a PLACEHOLDER url -> THE FACT IS DROPPED. The model said it had no source.
#:     Keeping it would put an admittedly unsourced claim into the tribunal
#:     wearing the same clothes as a sourced one (T-15.2-234).
_PLACEHOLDER_URLS: frozenset[str] = frozenset({
    "n/a", "n.a.", "na", "none", "null", "nil", "nvt", "n.v.t.",
    "-", "--", "---", "_", ".", "?", "??",
    "unknown", "unspecified", "not available", "not applicable", "not found",
    "no source", "no url", "source", "url", "tbd", "todo", "pending",
})


def is_placeholder_url(raw: object) -> bool:
    """True when a SOURCE_URL cell carries no source at all. PURE, never raises.

    An EMPTY or whitespace-only cell answers True as well — it also carries no
    source — but note that `_parse_url_cell` treats the two differently on the
    way through: an ABSENT cell is not a rejection to be counted (a two-column
    fact line simply has no URL column), whereas a cell that was WRITTEN and
    says `N/A` is a stated absence and is counted as one.
    """
    try:
        if not isinstance(raw, str):
            return raw is None
        return raw.strip().lower() in _PLACEHOLDER_URLS or not raw.strip()
    except Exception:  # noqa: BLE001 — a predicate that raises is worse than a coarse one
        return False


# ---------------------------------------------------------------------------
# The prompt side: what a provider is told to emit.
# ---------------------------------------------------------------------------


#: The providers that receive the REQUIRED-OUTPUT lead-in below. Exactly one
#: today, and named rather than defaulted so adding a second is a decision.
_LEAD_IN_PROVIDERS: tuple[str, ...] = ("gemini",)

#: A short restatement of the requirement, placed at the TOP of the block for a
#: long-context deep-research agent. Four lines, on purpose — see
#: `build_fact_list_prompt_block`'s docstring for what it is and is not.
_FACT_LIST_LEAD_IN = (
    "REQUIRED OUTPUT — READ THIS BEFORE YOU START. Your finished report MUST end\n"
    f"with two blocks: a {FACTS_START} block listing the facts you established, and a\n"
    f"{NOT_FOUND_START} block listing what you looked for and could not establish.\n"
    "The exact format of both is defined at the END of this message. Follow it.\n"
)


def build_fact_list_prompt_block(*, language: str = "", provider: str = "") -> str:
    """Build the D8 instruction block appended to a provider's research prompt.

    Mirrors `_build_distiller_prompt` (`steps.py:619`): one concatenated string, a
    conditionally-built language rule, and an explicit "NOT JSON" instruction because
    the JSON path is closed to us (citations ⊗ structured-outputs = HTTP 400).

    `language`, when non-empty, requires STATEMENT in that language while EVIDENCE
    stays in the report's original language — EVIDENCE is a locator, not prose, and a
    translated locator matches nothing.

    `provider` (15.2-23, additive — the default reproduces today's output BYTE FOR
    BYTE) selects PLACEMENT, never content. For a provider in `_LEAD_IN_PROVIDERS`
    the block is prefixed with `_FACT_LIST_LEAD_IN`, a four-line restatement of the
    requirement; the full format rules then follow verbatim, unchanged, in the same
    place they have always been.

    WHY, AND WHAT ITS STATUS IS. On run `d6bb3aae` Gemini honoured this block on
    **0 of 8** reports while Claude and OpenAI honoured theirs. The most likely
    cause for a long-context deep-research agent is mundane: the agent composes its
    report from a summarised prompt, and a 2.1 KB formatting block sitting at the
    very END of that prompt is the easiest part of it to lose. Restating the
    requirement up front is the cheapest intervention available that does not touch
    the format itself, and it costs one paid angle nothing.

    THIS IS A HYPOTHESIS, NOT A FIX. Whether a model COMPLIES with an instruction is
    a live-LLM question and no live run may be spent to answer it, so nothing here
    claims Gemini's compliance is repaired. What makes the next live run a
    MEASUREMENT rather than another guess is that the honour rate is already logged,
    per provider and in aggregate, by `pipeline/synthesis/steps.py`:

        collect_provider_facts: <provider> returned no usable fact list for
        k of m research report(s)
        ... %d report(s) with a fact list

    Read those two lines after the next run. A second counter is deliberately NOT
    added: `synthesis/steps.py` is the D-15 file and a nicer log line is not worth
    entering it.

    AND THE FALLBACK MUST NOT BE WEAKENED BY ANY OF THIS. D-14's full-extraction
    distiller caught all five non-compliant Gemini reports live, first time, and is
    the reason run `d6bb3aae` produced claims at all. It stays exactly as it is.
    """
    lang = (language or "").strip()
    lang_rule = (
        f"  - Write STATEMENT in {lang}. If your report is in another language,\n"
        f"    TRANSLATE the statement into {lang} (the whole run is one language).\n"
        "    Do NOT translate EVIDENCE — it must stay in the report's original\n"
        "    language, word for word.\n"
        if lang else ""
    )

    lead_in = (
        _FACT_LIST_LEAD_IN
        if str(provider or "").strip().lower() in _LEAD_IN_PROVIDERS
        else ""
    )

    return (
        f"{lead_in}"
        "\n--- MACHINE-READABLE FACT LIST (required) ---\n\n"
        "After you have written your report, append a fact list for the facts you\n"
        "established. Emit it ONCE, at the VERY END of your output, AFTER any source\n"
        "list. It is read by a machine, not by a person.\n\n"
        "Format rules:\n"
        f"  - Put the fact lines between a line reading {FACTS_START} and a line\n"
        f"    reading {FACTS_END}, each alone on its own line.\n"
        "  - One fact per line, TAB-separated. Do NOT use JSON, bullets, numbered\n"
        "    lists, or a markdown table.\n"
        "  - Each line MUST use this exact column order:\n"
        "    STATEMENT<TAB>SOURCE_URL<TAB>QUALITY<TAB>CERTAINTY<TAB>EVIDENCE\n"
        "  - STATEMENT = one self-contained factual assertion (no conjunctions\n"
        "    joining two facts). Include statistics, percentages, named entities and\n"
        "    dates where you have them.\n"
        "  - SOURCE_URL = the single URL that supports this fact. A markdown link in\n"
        "    the form [domain](url) is also accepted.\n"
        f"  - QUALITY = one of: {QUALITY_VALUES[0]}, {QUALITY_VALUES[1]}, {QUALITY_VALUES[2]}.\n"
        f"    {QUALITY_VALUES[0]} = government, regulator, standards body, official\n"
        f"    filing or academic source; {QUALITY_VALUES[1]} = established press or a\n"
        f"    recognised data provider; {QUALITY_VALUES[2]} = anything else.\n"
        f"  - CERTAINTY = {CERTAINTY_VALUES[0]} when two or more INDEPENDENT sources\n"
        f"    corroborate the fact; {CERTAINTY_VALUES[1]} when you found it only once\n"
        "    and it still needs double-checking. If in doubt, say\n"
        f"    {CERTAINTY_VALUES[1]}.\n"
        "  - EVIDENCE = the shortest VERBATIM sentence or phrase, copied EXACTLY from\n"
        "    your own report, that states this fact. Copy it word for word, in the\n"
        "    report's original language. It is used to LOCATE the passage in your\n"
        "    report and remove that passage if the fact is later discredited, so a\n"
        "    paraphrase or a translation is useless here.\n"
        f"{lang_rule}"
        "  - Blank lines, and lines without at least one TAB, are ignored.\n"
        "  - Do NOT number the fact lines and do NOT repeat the column headings.\n\n"
        "Then, in a second block, list what you looked for and could NOT establish:\n"
        f"  - Put those lines between a line reading {NOT_FOUND_START} and a line\n"
        f"    reading {NOT_FOUND_END}.\n"
        "  - One short line per thing you could not establish, in plain words.\n"
        "  - Emit this block even if it is empty. Saying nothing is missing is\n"
        "    information; saying nothing at all is not.\n"
    )


# ---------------------------------------------------------------------------
# Removing the machine-readable region from the prose.
# ---------------------------------------------------------------------------


def strip_fact_block(text: str | None) -> str:
    """Remove the FACTS / NOT_FOUND regions so they never reach synthesis or delivery.

    The fact list is an instruction artefact, not report prose. Left in place it would
    be distilled back into claims (double-counting every fact) and would render as
    tab-salad in the deliverable.

    Scans line by line — never a multiline regex over a 53 KB body — and preserves the
    original line terminators byte for byte, so a report with no sentinels comes back
    exactly as it went in. A dangling ``FACTS_START`` with no ``FACTS_END`` drops
    everything to end of text, mirroring the dangling-START flush at `intake.py:296`.
    Never raises; ``None`` and ``""`` both return ``""``.
    """
    if not text:
        return ""
    if FACTS_START not in text and NOT_FOUND_START not in text:
        # Fast path: nothing to strip, so return the input byte-identical.
        return text

    kept: list[str] = []
    dropping = False
    closer = ""
    for line in text.splitlines(keepends=True):
        token = line.strip()
        if dropping:
            # The closing sentinel is itself dropped, then normal copying resumes.
            if token == closer:
                dropping = False
                closer = ""
            continue
        if token == FACTS_START:
            dropping, closer = True, FACTS_END
            continue
        if token == NOT_FOUND_START:
            dropping, closer = True, NOT_FOUND_END
            continue
        kept.append(line)
    return "".join(kept)


# ---------------------------------------------------------------------------
# The parse side: reading a provider's answer back.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactListResult:
    """The outcome of parsing one provider's fact block.

    Every field except ``facts`` and ``not_found`` is a NAMED LOSS. The bar is
    `verification/report.py:184-190`: a degraded stream must be visibly degraded, in
    words and numbers a human reads, never a silent green.

    facts:
        Pipeline-shaped claim dicts, in report order. See `parse_fact_list` for the
        exact key set.
    not_found:
        The provider's own "I looked and could not establish this" lines. Feeds D-08's
        "What we could not establish" section and the `research_gap` rows.
    had_block:
        True when a ``FACTS_START`` sentinel was present at all. Distinguishes "the
        provider ignored the instruction" from "the provider complied but found
        nothing" — two very different failures that must not look alike.
    parse_errors:
        Lines inside the block that were ignored: no TAB, an echoed header row, or a
        statement below the minimum length. Also counts a second, ignored fact block.
    rejected_urls:
        SOURCE_URL cells dropped for a non-http(s) scheme, excess length, or a
        named placeholder. For the first two the statement SURVIVES — losing the
        link must not lose the fact.
    placeholder_urls:
        The subset of ``rejected_urls`` whose cell was a NAMED placeholder
        (`N/A`, `none`, `-`, `unknown`, …). These are counted separately and the
        FACT IS DROPPED, because the model is stating it had no source at all —
        a different event from writing a source down badly (T-15.2-234).
    dropped_over_cap:
        Facts discarded because the provider exceeded ``_MAX_FACTS``.
    needs_distiller_fallback:
        D-14. True when this provider yielded zero usable facts, so 15.2-14 must run
        the full-extraction distiller over its prose instead.
    fallback_reason:
        None when facts exist; otherwise a plain-English sentence naming the provider
        and the cause. Consumed verbatim by 15.2-14 for the feed and the verification
        report — a reader must understand it without reading this module.
    """

    facts: list[dict] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    had_block: bool = False
    parse_errors: int = 0
    rejected_urls: int = 0
    placeholder_urls: int = 0
    dropped_over_cap: int = 0
    needs_distiller_fallback: bool = True
    fallback_reason: str | None = None


def build_label_index(text: str | None) -> dict[str, str]:
    """Map every markdown link URL in ``text`` to its display label.

    This is what turns a deep-research report's trailing numbered source list —
    ``44. [hnsenergygroup.com](https://vertexaisearch.cloud.google.com/...)`` — into a
    redirect-URL -> display-domain map, so a bare redirect URL on a fact line can
    still be attributed to a real domain (Pitfall 10).

    RESOLUTION RULE — first USABLE label wins, not simply first label. A Gemini report
    cites the same redirect URL twice: once inline in the body, where the label is the
    self-referential string ``vertexaisearch.cloud.google.com``, and once in the
    trailing source list, where the label is the real domain. The inline occurrence
    comes FIRST in every recorded call, so a plain first-occurrence-wins map resolves
    to the redirect host for 100% of URLs and Pitfall 10 stays wide open. A label that
    is itself the redirect host is therefore treated as a placeholder and may be
    upgraded by a later, real domain label; any other label is kept as-is and is never
    overwritten. Measured on the committed recorded run: this is the difference
    between 0 and 3-4 tier-1/2 domains per report.

    Bounded at ``_MAX_LABEL_INDEX`` entries. Never raises.
    """
    out: dict[str, str] = {}
    if not text:
        return out
    for match in _MD_LINK_RE.finditer(text):
        label = (match.group(1) or "").strip()
        url = (match.group(2) or "").strip()
        if not url or not label:
            continue
        existing = out.get(url)
        if existing is None:
            if len(out) >= _MAX_LABEL_INDEX:
                break
            out[url] = label
        elif _is_placeholder_label(existing) and not _is_placeholder_label(label):
            # Upgrade a self-referential redirect-host label to the real domain.
            out[url] = label
    return out


def _is_placeholder_label(label: str) -> bool:
    """True when a link label carries no information beyond the redirect host itself."""
    candidate = (label or "").strip().lower()
    if candidate.startswith("www."):
        candidate = candidate[4:]
    return candidate == VERTEX_REDIRECT_HOST


def display_domain(
    url: str | None,
    *,
    label: str | None = None,
    label_index: "Mapping[str, str] | None" = None,
) -> str:
    """Resolve a URL to the domain a human would recognise as its source (Pitfall 10).

    Gemini grounded search does not return source URLs. It returns opaque redirects on
    ``VERTEX_REDIRECT_HOST`` (``vertexaisearch.cloud.google.com``), and the real domain
    survives only as the markdown link LABEL. Feeding the raw redirect to the tier
    heuristic grades every source in the largest research stream as tier 3
    "blog/other" — 52, 56 and 62 sources respectively in the recorded run, uniformly
    mis-graded. Resolution order:

      1. Take the host from ``url``, lowercased with a leading ``www.`` stripped (the
         same normalisation as `numbering._domain`). A malformed URL yields ``""``.
      2. Host is not the redirect host -> return it. Nothing to resolve.
      3. Host IS the redirect host -> try ``label``, then ``label_index[url]``. A
         candidate is accepted only if it looks like a hostname AND is not itself
         ``VERTEX_REDIRECT_HOST`` — recorded call 006 contains inline links whose
         label is exactly that self-referential string.
      4. Nothing usable -> return the redirect host. The tier then honestly stays 3
         and the provider-stated ``provider_quality`` carries the signal instead,
         which is precisely what D-13 added it for.

    Never raises.
    """
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:  # noqa: BLE001 — a malformed url just has no derivable domain
        return ""
    if host.startswith("www."):
        host = host[4:]
    if host != VERTEX_REDIRECT_HOST:
        return host

    candidates = [label]
    if label_index:
        try:
            candidates.append(label_index.get(url))
        except Exception:  # noqa: BLE001 — a hostile mapping must not break parsing
            pass
    for raw in candidates:
        if not raw:
            continue
        candidate = str(raw).strip().lower()
        if candidate.startswith("www."):
            candidate = candidate[4:]
        if candidate and candidate != VERTEX_REDIRECT_HOST and _DOMAIN_RE.match(candidate):
            return candidate
    return host


def _quality_tier_hint(provider: str, domain: str) -> int:
    """Best-effort 1/2/3 quality tier for a display domain.

    REUSES `citations/numbering.py::derive_quality_tier` — the tier tables are NOT
    copied here. The import is function-local so this module stays a pure transform
    with a stdlib-only module scope (`numbering` pulls in SQLAlchemy).

    A tier is a hint, not verification, so any failure degrades to 3 rather than
    propagating: being wrong about a source's prestige must never fail a run.
    """
    if not domain:
        return 3
    try:
        from nestor_pulse_sdk.citations.numbering import derive_quality_tier  # noqa: PLC0415
        return derive_quality_tier(provider, f"https://{domain}/")
    except Exception:  # noqa: BLE001 — a tier is best-effort, never load-bearing
        log.debug("facts: tier hint unavailable for domain %r", domain[:80])
        return 3


def _clamp(raw: object, vocabulary: tuple[str, ...], default: str, kind: str) -> str:
    """Clamp a model-supplied enum to its vocabulary (shape copied from
    `group_skeptic._normalise_verdict`).

    The column these land in is free text with no CHECK constraint, so an unclamped
    typo would reach the database and be miscounted by every downstream bucket. Both
    defaults fail toward MORE checking (G-11).
    """
    if not isinstance(raw, str):
        return default
    value = raw.strip().lower()
    if not value:
        return default
    if value in vocabulary:
        return value
    log.warning("facts: unknown %s %r — normalised to %r", kind, raw[:40], default)
    return default


def _extract_region(
    lines: list[str], start_token: str, end_token: str
) -> tuple[list[str], bool, int]:
    """Slice the lines between the FIRST start/end sentinel pair.

    Returns (region_lines, had_block, extra_blocks). A dangling start sentinel with no
    end reads to end of text (mirrors the flush at `intake.py:296`). A second block is
    ignored and reported so the caller can count it as a parse error rather than
    silently concatenating a duplicate.
    """
    region: list[str] = []
    had_block = False
    extra_blocks = 0
    in_block = False
    closed = False
    for line in lines:
        token = line.strip()
        if not in_block:
            if token == start_token:
                if closed:
                    extra_blocks += 1
                    continue
                in_block = True
                had_block = True
            continue
        if token == end_token:
            in_block = False
            closed = True
            continue
        region.append(line)
    return region, had_block, extra_blocks


def parse_fact_list(
    text: str | None,
    *,
    provider: str,
    facet: str,
    label_index: "Mapping[str, str] | None" = None,
) -> FactListResult:
    """Parse a provider's D8 fact block into pipeline-shaped claim dicts.

    ``provider`` and ``facet`` are CALLER-SUPPLIED and are NEVER read out of model
    text — the rule `_parse_distiller_response` states at `steps.py:679-681`. A model
    must not be able to set its own attribution, so no line format, however
    well-formed, can influence ``found_by`` or ``facet``.

    Each fact is a dict with exactly nine keys. The first five are the shape
    `persist_tribunal_claims` already consumes (``source_urls`` is read at
    `extractor.py:498`), so no persistence-loop change is needed:

        text, facet, evidence, found_by, source_urls,
        certainty, provider_quality, source_domain, quality_tier_hint

    ``certainty`` and ``provider_quality`` are the D-13 columns added by migration
    0013; ``source_domain`` and ``quality_tier_hint`` are the Pitfall-10 pair.

    Tolerates 2, 3, 4 or 5 columns; missing cells take their defaults. Blank lines and
    lines without a TAB are ignored and counted. Nothing raises, for any input.
    """
    facts: list[dict] = []
    not_found: list[str] = []
    parse_errors = 0
    rejected_urls = 0
    placeholder_urls = 0
    dropped_over_cap = 0

    body = text or ""
    lines = body.splitlines()

    if label_index is None:
        # Derive from the report itself so a bare redirect URL on a fact line can
        # still resolve against the report's own trailing source list.
        label_index = build_label_index(body)

    region, had_block, extra_blocks = _extract_region(lines, FACTS_START, FACTS_END)
    parse_errors += extra_blocks

    for raw_line in region:
        line = raw_line.strip()
        if not line:
            continue
        if "\t" not in line:
            parse_errors += 1
            log.debug("facts: skipping malformed line (no tab): %r", line[:80])
            continue
        parts = line.split("\t", 4)
        if parts[0].strip().upper() == "STATEMENT":
            # The model echoed the column headings back at us.
            parse_errors += 1
            continue

        statement = _clean_statement(parts[0])
        if len(statement) < _MIN_STATEMENT_CHARS:
            parse_errors += 1
            continue

        if len(facts) >= _MAX_FACTS:
            dropped_over_cap += 1
            continue

        url_cell = parts[1].strip() if len(parts) > 1 else ""
        url, link_label, rejected, placeholder = _parse_url_cell(url_cell)
        if rejected:
            rejected_urls += 1
        if placeholder:
            # The model said it had no source. Drop the FACT, not just the link,
            # and keep parsing: one unsourced line never voids a report's whole
            # fact list (T-15.2-234).
            placeholder_urls += 1
            continue

        domain = display_domain(url, label=link_label, label_index=label_index) if url else ""

        # EVIDENCE stays BYTE-VERBATIM: only surrounding whitespace is removed. No
        # cite-marker stripping, no truncation, no normalisation — `scrub_research`
        # locates the passage to delete by matching this exact span, and the
        # cite-marker regex also eats the whitespace preceding a marker, so stripping
        # here would silently break every later scrub of a discredited fact.
        evidence = parts[4].strip() if len(parts) > 4 else ""

        facts.append({
            "text": statement,
            "facet": facet,
            "evidence": evidence or statement,
            "found_by": [provider] if provider else [],
            "source_urls": [url] if url else [],
            "certainty": _clamp(
                parts[3] if len(parts) > 3 else "",
                CERTAINTY_VALUES,
                DEFAULT_CERTAINTY,
                "certainty",
            ),
            "provider_quality": _clamp(
                parts[2] if len(parts) > 2 else "",
                QUALITY_VALUES,
                DEFAULT_QUALITY,
                "quality",
            ),
            "source_domain": domain,
            "quality_tier_hint": _quality_tier_hint(provider, domain),
        })

    if placeholder_urls:
        log.warning(
            "facts: %s emitted %d fact line(s) whose SOURCE_URL was a placeholder "
            "rather than a source — those facts were dropped. A stated absence of "
            "a source is not a source (D-M).",
            provider or "provider", placeholder_urls,
        )

    if dropped_over_cap:
        log.warning(
            "facts: %s exceeded the %d-fact cap — %d fact(s) dropped",
            provider or "provider", _MAX_FACTS, dropped_over_cap,
        )

    nf_region, _nf_had, _nf_extra = _extract_region(lines, NOT_FOUND_START, NOT_FOUND_END)
    for raw_line in nf_region:
        entry = raw_line.strip()
        if not entry:
            continue
        if len(not_found) >= _MAX_NOT_FOUND:
            break
        not_found.append(entry[:_MAX_NOT_FOUND_CHARS])

    needs_distiller_fallback = not facts
    fallback_reason = None
    if needs_distiller_fallback:
        who = provider or "this provider"
        if not had_block:
            fallback_reason = (
                f"{who} returned no {FACTS_START}/{FACTS_END} block — its report will "
                f"be run through the full-extraction distiller instead (D-14)."
            )
        elif placeholder_urls and not parse_errors:
            # The lines PARSED; every one of them admitted it had no source. That
            # is a different failure from a garbled block and must not be worded
            # as one, or the operator reads "0 lines ignored" and is misled.
            fallback_reason = (
                f"{who} returned a {FACTS_START}/{FACTS_END} block in which every "
                f"fact named a placeholder instead of a source "
                f"({placeholder_urls} line(s)) — nothing in it was usable, so its "
                f"report will be run through the full-extraction distiller "
                f"instead (D-14)."
            )
        else:
            fallback_reason = (
                f"{who} returned a {FACTS_START}/{FACTS_END} block but not one line in "
                f"it parsed as a fact ({parse_errors} line(s) ignored) — its report "
                f"will be run through the full-extraction distiller instead (D-14)."
            )
        log.warning("facts: %s", fallback_reason)

    return FactListResult(
        facts=facts,
        not_found=not_found,
        had_block=had_block,
        parse_errors=parse_errors,
        rejected_urls=rejected_urls,
        placeholder_urls=placeholder_urls,
        dropped_over_cap=dropped_over_cap,
        needs_distiller_fallback=needs_distiller_fallback,
        fallback_reason=fallback_reason,
    )


def _clean_statement(cell: str) -> str:
    """Strip unresolved citation markers, trim, and hard-truncate a STATEMENT cell.

    REUSES `audit/audited_llm_client.py::strip_unresolved_cite_markers` — there is no
    second stripper in this codebase, and this one is imported function-locally
    exactly as `pipeline.py:1304` does it.

    Truncation, not rejection: an over-long statement is still a fact, and the cap is
    what bounds the injection surface reaching the skeptic and grouping prompts
    downstream (a documented security control, not formatting).
    """
    try:
        from nestor_pulse_sdk.audit.audited_llm_client import (  # noqa: PLC0415
            strip_unresolved_cite_markers,
        )
        cleaned, _n_removed = strip_unresolved_cite_markers(cell or "")
    except Exception:  # noqa: BLE001 — degrade to the raw cell rather than lose the fact
        cleaned = cell or ""
    return cleaned.strip()[:_MAX_STATEMENT_CHARS]


def _parse_url_cell(cell: str) -> tuple[str, str | None, bool, bool]:
    """Parse a SOURCE_URL cell into (url, label, rejected, placeholder).

    Accepts a bare URL or a ``[label](url)`` markdown link. Only ``http`` and
    ``https`` survive: this URL is later rendered as a CLICKABLE LINK in the
    superadmin citation panel, so a ``javascript:`` or ``data:`` URL chosen by an
    untrusted model would be an elevation-of-privilege path into the operator's own
    tool. A rejected URL drops the link and KEEPS the fact.

    A PLACEHOLDER is checked FIRST and answered separately (15.2-23). `N/A`,
    `none`, `-`, `unknown` and their siblings are not malformed URLs — they are the
    model stating that it had no source — so they are named in the log as such and
    the CALLER drops the fact rather than keeping an admittedly unsourced claim
    (T-15.2-234). Checking before the scheme test is what makes the log line
    honest; leaving it to the http(s) test was how the case was caught live, by
    accident, wearing the wrong name.
    """
    if not cell:
        return "", None, False, False
    if is_placeholder_url(cell):
        log.warning(
            "facts: SOURCE_URL %r is a placeholder, not a URL — the provider is "
            "stating it had no source, so this fact is dropped rather than "
            "persisted as an unsourced claim",
            cell.strip()[:40],
        )
        return "", None, True, True
    label: str | None = None
    url = cell
    match = _MD_LINK_RE.fullmatch(cell)
    if match:
        label = (match.group(1) or "").strip() or None
        url = (match.group(2) or "").strip()
    if len(url) > _MAX_URL_CHARS:
        log.warning("facts: rejecting over-long SOURCE_URL (%d chars)", len(url))
        return "", label, True, False
    try:
        scheme = urlparse(url).scheme.lower()
    except Exception:  # noqa: BLE001 — unparseable is rejected, not fatal
        scheme = ""
    if scheme not in ("http", "https"):
        log.warning("facts: rejecting non-http(s) SOURCE_URL %r", url[:80])
        return "", label, True, False
    return url, label, False, False
