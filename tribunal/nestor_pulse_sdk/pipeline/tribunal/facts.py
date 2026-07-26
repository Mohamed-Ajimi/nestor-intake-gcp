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


# ---------------------------------------------------------------------------
# The prompt side: what a provider is told to emit.
# ---------------------------------------------------------------------------


def build_fact_list_prompt_block(*, language: str = "") -> str:
    """Build the D8 instruction block appended to a provider's research prompt.

    Mirrors `_build_distiller_prompt` (`steps.py:619`): one concatenated string, a
    conditionally-built language rule, and an explicit "NOT JSON" instruction because
    the JSON path is closed to us (citations ⊗ structured-outputs = HTTP 400).

    `language`, when non-empty, requires STATEMENT in that language while EVIDENCE
    stays in the report's original language — EVIDENCE is a locator, not prose, and a
    translated locator matches nothing.
    """
    lang = (language or "").strip()
    lang_rule = (
        f"  - Write STATEMENT in {lang}. If your report is in another language,\n"
        f"    TRANSLATE the statement into {lang} (the whole run is one language).\n"
        "    Do NOT translate EVIDENCE — it must stay in the report's original\n"
        "    language, word for word.\n"
        if lang else ""
    )

    return (
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
