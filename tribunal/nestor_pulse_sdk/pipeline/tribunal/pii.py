"""Outbound personal-identifier redaction for research queries (D-I).

WHY THIS MODULE EXISTS
----------------------
On run `d6bb3aae` (2026-07-27) angle #6 was a PAID Google deep-research
assignment, generated from a stakeholder line in the context pack, asking an
external processor to establish the job title of a named individual — and the
query carried that individual's email address. A personal identifier left the
platform to a third party, as a research task, serving no client decision. That
is a data-protection incident, not a quality bug, and this module is the egress
control that answers it.

WHY AT DISPATCH AND NOT AT INPUT
--------------------------------
There are many ways for text to enter this engine — a context pack, an intake
answer, a client-written research question, a model-authored sub-question — and
exactly ONE way for it to leave to a provider: the `runner(query=...)` call
inside `research_division.run_angles`, plus the model-authored search input in
`own_researcher._clamp_search_input`. A control placed at the input has to be
right in every one of those places forever. A control placed at the choke point
has to be right once. So this runs at the choke point, and plan 15.2-21's fix to
the workshop's input selection — which removes the stakeholder lines that
produce name-hunting questions in the first place — is the other half: that one
removes the CAUSE, this one holds when the cause comes back.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
IT DOES NOT DETECT PERSONAL NAMES. This is the honest boundary and it is stated
here on purpose, because a scrubber that silently claims more than it does is
worse than one that says what it covers. A name detector loosed on research text
about companies, brands and executives would either miss most names (and give
false assurance) or delete half of every question — and a half-deleted question
is a wasted paid deep-research call, which is the very cost this whole phase is
trying to control (T-15.2-233). What is machine-detectable without guessing is
DIRECT identifiers: an email address and a dialling-shaped telephone number.
That is what this covers, and nothing more.

It also does not rewrite URLs. An `@` inside a URL path is not an email address,
and a source link corrupted by an over-eager scrub breaks the evidence trail the
whole engine is built on. URL-shaped tokens are skipped, by name, below.

THE FAMILY THIS BELONGS TO — copy its shape, do not invent a fourth style:

    reliability.redact(text) -> str
        credentials, for anything that reaches a log or the operator feed.
    audited_llm_client.strip_unresolved_cite_markers(text) -> tuple[str, int]
        the (text, count) contract that turns a silent removal into a REPORTED
        one.

`scrub_pii` is the third sibling: `reliability.redact`'s never-raise discipline
with `strip_unresolved_cite_markers`' reported count.

THE ONE ASYMMETRY WITH `reliability.redact`. That function fails SAFE toward
`"<unprintable>"`, because its output is a log line and losing a log line costs
nothing. This one fails toward the ORIGINAL TEXT, because its output is a paid
research question and returning `"<unprintable>"` would destroy the angle. The
failure is therefore not silent: it is logged at WARNING, and the caller treats
a scrub failure as a loud event rather than a clean pass.

PURE. No I/O, no network, no database, no LLM call, no import of anything in
`nestor_pulse_sdk`. Module scope is stdlib-only.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger(__name__)

#: The marker left in place of a removed identifier. Deliberately the same
#: spelling `reliability.redact` uses, so an operator reading a dispatched query
#: and an operator reading a log line learn the same word for the same event.
REDACTED = "<redacted>"

# ---------------------------------------------------------------------------
# Email. Conservative and bounded: a local part, an `@`, and a domain that must
# end in a real-looking TLD. Every quantifier has an explicit upper bound so a
# hostile 200 KB input cannot make this backtrack.
#
# The leading look-behind stops a match from starting in the MIDDLE of a longer
# address-like token; the trailing look-ahead stops a TLD from being cut short.
# ---------------------------------------------------------------------------
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9._%+\-])"
    r"[A-Za-z0-9._%+\-]{1,64}"
    r"@"
    r"[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]{0,61}[A-Za-z0-9])?){0,8}"
    r"\.[A-Za-z]{2,24}"
    r"(?![A-Za-z0-9\-])"
)

# ---------------------------------------------------------------------------
# Telephone. THE HARD PART IS NOT FINDING PHONE NUMBERS — IT IS NOT FINDING
# EVERYTHING ELSE. This engine's research questions are dense with year ranges
# ("CAPEX 2026-27"), percentages, money ("EUR 1,2 miljard"), four-digit
# statistics ("8.000 tankstations") and statutory opening hours ("08.00-18.00").
# A pattern that eats any of those turns a data-protection fix into a wasted
# paid angle (T-15.2-233), so the shape is required to be a DIALLING shape:
#
#   1. it must begin with `+` (international) or `0` (national trunk prefix),
#      which alone excludes every year, percentage, price and bare statistic;
#   2. it must carry between `_MIN_DIGITS` and `_MAX_DIGITS` digits. Nine is the
#      shortest national number in this engine's markets (a Belgian landline,
#      `02 123 45 67`); fifteen is the E.164 maximum. Eight-digit shapes are
#      excluded on purpose: `08.00-18.00` is an opening-hours range, and this
#      engine literally researches opening hours;
#   3. it may use AT MOST `_MAX_SEPARATOR_KINDS` DISTINCT separator characters.
#      A phone number is written with one or two ("+32 470 12 34 56",
#      "0470/12.34.56"); a run of clock times glued together by a space
#      ("08.00-18.00 09.00-17.00") needs three, and is refused for that reason.
#
# The candidate pattern is deliberately loose and the three rules above are
# enforced in `_looks_like_a_phone`, because a regex that tried to say all of
# this at once would be unreadable and unauditable.
# ---------------------------------------------------------------------------
_MIN_DIGITS = 9
_MAX_DIGITS = 15
_MAX_SEPARATOR_KINDS = 2

_SEPARATORS = frozenset(" \t/.()-")

_PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\w.])"
    r"(?:\+\d|0\d)"
    r"[\d \t/.()\-]{6,20}"
    r"\d"
    r"(?!\d)"
)

#: A token containing this is a URL, and URLs are not rewritten here.
_URL_MARKERS = ("://", "www.", "mailto:")

#: Hard ceiling on the input this module will scan. Far above any real research
#: query (`_SUBQ_CHARS` is 600 and a whole angle brief is a few KB), and present
#: only so a pathological input cannot turn a prompt decoration into a CPU sink.
_MAX_SCAN_CHARS = 1_000_000


def _token_bounds(text: str, start: int) -> tuple[int, int]:
    """The whitespace-delimited token containing position `start`. Never raises."""
    left = start
    while left > 0 and not text[left - 1].isspace():
        left -= 1
    right = start
    length = len(text)
    while right < length and not text[right].isspace():
        right += 1
    return left, right


def _inside_a_url(text: str, start: int) -> bool:
    """True when the match at `start` sits inside a URL-shaped token.

    `https://x.test/a@b` is a path, not an address, and
    `https://user@host/x` is a userinfo URL — a URL either way. Rewriting the
    middle of one would silently corrupt a source link, and source links are
    the evidence trail this engine's entire verification stage rests on.
    """
    left, right = _token_bounds(text, start)
    token = text[left:right].lower()
    return any(marker in token for marker in _URL_MARKERS)


def _looks_like_a_phone(candidate: str) -> bool:
    """Apply the three dialling-shape rules to one candidate run. Never raises."""
    digits = sum(1 for ch in candidate if ch.isdigit())
    if digits < _MIN_DIGITS or digits > _MAX_DIGITS:
        return False
    kinds = {ch for ch in candidate if ch in _SEPARATORS}
    return len(kinds) <= _MAX_SEPARATOR_KINDS


def scrub_pii(text: "str | None") -> tuple[str, int]:
    """Remove direct personal identifiers from outbound text.

    Returns ``(scrubbed_text, n_removed)``. ``n_removed`` is the number of
    identifiers actually replaced, so the caller can REPORT a redaction instead
    of performing one silently — the contract
    `audited_llm_client.strip_unresolved_cite_markers` established.

    ORDER IS LOAD-BEARING: the email pattern runs FIRST, so an address whose
    local part happens to contain a long digit run cannot be partly eaten by the
    phone pattern and left as a recognisable fragment.

    This function never lowercases, never normalises whitespace and never
    truncates. Bounding the outbound text is the caller's job and stays there:
    `research_division._SUBQ_CHARS` and `own_researcher._QUERY_MAX_CHARS` are
    prompt-injection controls with their own tests, and duplicating them here
    would be a second, competing bound.

    NEVER RAISES. On any internal failure it returns ``(str(text or ""), 0)``
    and logs at WARNING: a failure to scrub must be VISIBLE, and it must not
    kill a paid research angle. See the module docstring for why this direction
    of failure is the opposite of `reliability.redact`'s.
    """
    try:
        if text is None:
            return "", 0
        if not isinstance(text, str):
            # A non-string reached the dispatch point. Degrade to a string the
            # caller can still send rather than raising inside a paid angle.
            return str(text), 0
        if not text:
            return text, 0
        if len(text) > _MAX_SCAN_CHARS:
            log.warning(
                "pii.scrub_pii: input is %d chars, above the %d-char scan ceiling "
                "— it is dispatched UNSCRUBBED. This is a bug in the caller's "
                "bounding, not an acceptable outcome: no research query should "
                "ever be this large.",
                len(text), _MAX_SCAN_CHARS,
            )
            return text, 0

        removed = 0

        def _email_sub(match: "re.Match[str]") -> str:
            nonlocal removed
            if _inside_a_url(match.string, match.start()):
                return match.group(0)
            removed += 1
            return REDACTED

        def _phone_sub(match: "re.Match[str]") -> str:
            nonlocal removed
            candidate = match.group(0)
            if not _looks_like_a_phone(candidate):
                return candidate
            if _inside_a_url(match.string, match.start()):
                return candidate
            removed += 1
            return REDACTED

        out = _EMAIL_RE.sub(_email_sub, text)
        out = _PHONE_CANDIDATE_RE.sub(_phone_sub, out)
        return out, removed
    except Exception as exc:  # noqa: BLE001 — a scrub failure must not kill an angle
        log.warning(
            "pii.scrub_pii: FAILED to scrub an outbound query (%s) — the original "
            "text is returned unchanged and the caller must treat this as a "
            "possible disclosure, not as a clean pass",
            type(exc).__name__,
        )
        try:
            return str(text or ""), 0
        except Exception:  # noqa: BLE001 — a hostile __str__ costs the text, not the run
            return "", 0
