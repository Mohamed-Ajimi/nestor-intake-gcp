"""Claim attribution helpers (D-R3, phase 15.5 wave 2).

Today this module exports exactly one function, `extract_as_of`, which reads a
date out of a distilled claim EVIDENCE cell. Plan 15.5-02 adds the facet
resolution helpers to this same module; do not pre-empt them here.

WHY THIS IS THE ONE EXCEPTION IN THE PHASE
------------------------------------------
`extract_as_of` is the ONLY place in phase 15.5 where a persisted value is
DERIVED FROM MODEL OUTPUT. Every other column this phase adds -- `sub_question`
and `corroboration_key` -- is stamped in Python from the dispatch assignment and
is never parsed out of a provider response. That is the identical rule
`_parse_distiller_response` already applies to `provider` and
`enforce_scope_guard` applies to `parent`: a model must not be able to choose
its own attribution, because a model-supplied `corroboration_key` would let
model text pick its own corroboration partner.

`as_of` cannot follow that rule, because the date is a fact about the WORLD that
only the source states -- nothing at dispatch time knows it. D-W2-1 therefore
sanctions parsing it here, and pays for the exception with a BOUND: the grammar
below rejects every ambiguous form instead of guessing. A WRONG DATE IS WORSE
THAN NO DATE. A missing date costs one claim its ordering; a wrong date turns a
real contradiction into a fake time series, which is exactly the failure that
made this column necessary in the first place (V-01 finding D-V01-4 was
WITHDRAWN once it turned out gemini and claude had read different De Haan
articles at different points in one rollout -- 7 sites in 2021 against roughly
90 later -- and both were true).

The residual risk this does NOT cover: a provider stating a well-formed but
untrue date. That is the same trust level as the claim text itself, and it is
accepted for the same reason.

WHY THIS MODULE IS STDLIB-ONLY
------------------------------
It imports `re`, `datetime` and `logging` and nothing else, on purpose. The dev
box that reviews this code has no pytest, no sqlalchemy and no Docker, but does
ship a stdlib-only Python. A stdlib-pure module can be lifted straight out of
the COMMITTED source and DRIVEN there, so the grammar below is provable by
execution rather than by reading. Adding an import from anywhere else in the SDK
would take that away.

THE ACCEPTED GRAMMAR
--------------------
A date is returned for these forms and no others:

  * `YYYY-MM-DD` -- ISO 8601, a real calendar date, year in 1900..2100.
    `2021-03-04` -> 2021-03-04.
  * A TEXTUAL month with an EXPLICIT DAY, in either order and case-insensitive,
    with full and 3-letter month names in ENGLISH and DUTCH (V-01 is a Dutch
    run): `4 maart 2021`, `4 March 2021`, `March 4, 2021`, `4 mrt 2021`,
    `4 Mar 2021`. The accepted vocabulary is the `_MONTHS` table below -- one
    place, greppable.
  * A BARE 4-digit year in 1900..2100 -> `date(YYYY, 1, 1)`.

JANUARY 1 IS A CONVENTION, NOT A STATED DAY
-------------------------------------------
Say it out loud, because a reader of the `claim.as_of` column will otherwise
read `2021-01-01` as a source that said "1 January". It did not. `date(Y, 1, 1)`
is this module's encoding of YEAR PRECISION -- the source stated a year and
nothing finer. PostgreSQL has no year-precision date type and D-W2-1 explicitly
sanctions the bare year rather than dropping it, so the convention is the price.
Anything reasoning about `as_of` at day resolution must treat January 1 as
suspect.

One worked consequence, so it is not a surprise later: `maart 2021` -- a textual
month with NO day -- yields 2021-01-01, because `2021` is a bare year in text
that carries no numeric date token. The month is lost. That is year precision
doing its job, not a bug.

THE REJECTIONS, WHICH ARE AS DELIBERATE AS THE ACCEPTANCES
----------------------------------------------------------
Every one of these returns None:

  * Any all-numeric date that is not ISO order: `03/04/2021`, `3-4-2021`,
    `04.03.2021`, `04-03-2021`. `03/04/2021` IS NOT DECIDABLE between DD/MM and
    MM/DD -- half the world writes each -- and guessing is precisely how a real
    contradiction becomes a fake time series. A `-` separator is accepted ONLY
    in `YYYY-MM-DD` order.
  * Numeric month precision with no day: `2021-03` (and its mirror `03-2021`).
    It would have to FABRICATE a day, and unlike a bare year that fabrication is
    not sanctioned. Note the difference from the `maart 2021` case above: here
    the year is glued into a numeric date-shaped token, so it is not a bare year
    and it never reaches the bare-year rule.
  * Two-digit years (`04-03-21`), years outside 1900..2100, and impossible
    calendar dates (`2021-02-30`).
  * Four digits that are part of a longer digit run -- `20211`, `v20214`, an id
    inside a URL. The scan requires DIGIT boundaries, not word boundaries.
  * MORE THAN ONE CANDIDATE. Full dates and bare years are collected separately,
    then:
        exactly one distinct full date  -> return it (extra bare years are
                                           ignored: the explicitly stated full
                                           date is the more precise statement)
        two or more distinct full dates -> None
        no full date, one distinct year -> January 1 of it
        no full date, two or more years -> None
    This single-candidate rule is what kills `2020-2021`, `tussen 2019 en 2023`,
    and an evidence cell citing two different sources.
  * Empty, None, or non-string input.

INPUT IS BOUNDED BEFORE IT IS SCANNED
-------------------------------------
Only the first `_MAX_EVIDENCE_CHARS` characters are read. Untrusted model output
must be bounded before scanning -- the same register as the caps `_insert_claim`
applies at the database boundary (threat T-15.5-02). The patterns below are flat
alternations of literals with no nested quantifiers, so there is no catastrophic
backtracking to trigger either.

AND IT NEVER RAISES
-------------------
A malformed evidence string costs that claim its date and nothing more. This
function is called on the persistence path of a roughly $50 run; an exception
here would trade a missing date for lost claims (threat T-15.5-01).
"""
from __future__ import annotations

import logging
import re
from datetime import date

log = logging.getLogger(__name__)

__all__ = ["extract_as_of"]


# Untrusted model output is bounded before it is scanned. See the docstring.
_MAX_EVIDENCE_CHARS = 2000

# A claim older than this is not a claim about a live business, and a claim
# dated beyond it is a typo or a hallucination. Both ends are rejected rather
# than clamped: a clamped date would look like a stated one.
_MIN_YEAR = 1900
_MAX_YEAR = 2100

# THE ACCEPTED MONTH VOCABULARY, in ONE place so it is greppable.
# Full and 3-letter abbreviated names, English and Dutch. V-01 is a Dutch run,
# so the Dutch names are not optional decoration -- `maart` and `mrt` are what
# the sources actually say.
_MONTHS: dict[str, int] = {
    # January
    "january": 1, "januari": 1, "jan": 1,
    # February
    "february": 2, "februari": 2, "feb": 2,
    # March -- `march`/`mar` English, `maart`/`mrt` Dutch
    "march": 3, "maart": 3, "mar": 3, "mrt": 3,
    # April
    "april": 4, "apr": 4,
    # May -- `mei` is both the full Dutch name and three letters
    "may": 5, "mei": 5,
    # June
    "june": 6, "juni": 6, "jun": 6,
    # July
    "july": 7, "juli": 7, "jul": 7,
    # August
    "august": 8, "augustus": 8, "aug": 8,
    # September -- same spelling in both languages
    "september": 9, "sep": 9,
    # October
    "october": 10, "oktober": 10, "oct": 10, "okt": 10,
    # November
    "november": 11, "nov": 11,
    # December
    "december": 12, "dec": 12,
}

# Longest-first so `maart` is preferred over `mar` and `augustus` over `aug`.
# A shortest-first alternation would match the prefix and leave the rest of the
# word dangling, so the surrounding pattern would fail on a name it accepts.
_MONTH_ALTERNATION = "|".join(sorted(_MONTHS, key=len, reverse=True))

# (1) ISO 8601, the only accepted all-numeric form. Digit boundaries on both
#     ends so an id inside a longer digit run cannot masquerade as a date.
_ISO_RE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")

# (2a) day month year: `4 maart 2021`, `4 Mar 2021`, `4th March 2021`.
_TEXTUAL_DMY_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\.?\s+\b(" + _MONTH_ALTERNATION + r")\b\.?,?\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)

# (2b) month day, year: `March 4, 2021`, `maart 4 2021`.
_TEXTUAL_MDY_RE = re.compile(
    r"\b(" + _MONTH_ALTERNATION + r")\b\.?\s+(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s*,?\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)

# (3) REJECTED numeric forms. These are matched only to CONSUME them, so that
#     the year buried inside one can never leak out to the bare-year rule.
#     `03/04/2021` must be None, not 2021.
_AMBIGUOUS_TRIPLE_RE = re.compile(r"(?<!\d)\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}(?!\d)")
# Numeric month precision, both orders: `2021-03`, `2021/03`, `03-2021`.
_PARTIAL_YM_RE = re.compile(r"(?<!\d)\d{4}[/.\-]\d{1,2}(?!\d)")
_PARTIAL_MY_RE = re.compile(r"(?<!\d)\d{1,2}[/.\-]\d{4}(?!\d)")

# (4) A bare 4-digit year -- DIGIT boundaries, not word boundaries, so `20211`
#     and `v20214` are not years.
_BARE_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _in_range(year: int) -> bool:
    return _MIN_YEAR <= year <= _MAX_YEAR


def _consume(text: str, pattern: re.Pattern[str], collect) -> str:
    """Blank out every match of `pattern`, offering each to `collect` first.

    Returning the text with matched spans replaced by SPACES (not deleted) keeps
    every later pattern honest: character offsets do not shift, and a consumed
    numeric date can no longer be re-read as a bare year by the next stage. That
    is the whole mechanism by which `03/04/2021` yields None rather than 2021.
    """
    out: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        collect(match)
        out.append(text[cursor:match.start()])
        out.append(" " * (match.end() - match.start()))
        cursor = match.end()
    out.append(text[cursor:])
    return "".join(out)


def extract_as_of(evidence: str | None) -> date | None:
    """Return the single date stated in `evidence`, or None.

    Pure, importable, and NEVER RAISES. See the module docstring for the full
    accepted grammar, the rejections, and why January 1 means year precision.

    Args:
        evidence: the EVIDENCE cell of a distilled claim -- the verbatim source
            sentence the distiller copied. May be None, empty, or not a string
            at all; all three yield None.

    Returns:
        A `datetime.date` when exactly one date is stated, otherwise None. None
        is the COMMON case and is accepted: most evidence sentences carry no
        date, and D-W2-1 prefers no date to a guessed one.
    """
    try:
        if not isinstance(evidence, str) or not evidence:
            return None

        # Bound the untrusted input BEFORE scanning it (threat T-15.5-02).
        text = evidence[:_MAX_EVIDENCE_CHARS]

        full_dates: set[date] = set()

        def take(year: int, month: int, day: int) -> None:
            """Record a full date, or silently drop an impossible one.

            An out-of-range year or an impossible calendar date (`2021-02-30`)
            is DROPPED rather than raised on -- and because its span has already
            been consumed by the caller, its year cannot fall through to the
            bare-year rule either. `2021-02-30` therefore yields None, not 2021.
            """
            if not _in_range(year):
                return
            try:
                full_dates.add(date(year, month, day))
            except ValueError:
                log.debug("extract_as_of: impossible calendar date %r-%r-%r", year, month, day)

        # (1) ISO 8601 first, so its span is claimed before the ambiguous-numeric
        #     scan below can eat it.
        text = _consume(
            text,
            _ISO_RE,
            lambda m: take(int(m.group(1)), int(m.group(2)), int(m.group(3))),
        )

        # (2) Textual month WITH an explicit day, both orders.
        text = _consume(
            text,
            _TEXTUAL_DMY_RE,
            lambda m: take(int(m.group(3)), _MONTHS[m.group(2).lower()], int(m.group(1))),
        )
        text = _consume(
            text,
            _TEXTUAL_MDY_RE,
            lambda m: take(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2))),
        )

        # (3) Consume the rejected numeric forms WITHOUT collecting anything.
        #     This is not tidying: it is what stops the year inside `03/04/2021`
        #     or `2021-03` from being read as a bare year in stage 4.
        noop = lambda _match: None  # noqa: E731 - deliberate, keeps _consume uniform
        text = _consume(text, _AMBIGUOUS_TRIPLE_RE, noop)
        text = _consume(text, _PARTIAL_YM_RE, noop)
        text = _consume(text, _PARTIAL_MY_RE, noop)

        # (4) Whatever 4-digit runs survive are bare years.
        years = {
            int(match.group(1))
            for match in _BARE_YEAR_RE.finditer(text)
            if _in_range(int(match.group(1)))
        }

        # THE SINGLE-CANDIDATE RULE. Two dates in one evidence cell means the
        # cell cites two things, and picking either one is a coin flip recorded
        # as a fact.
        if len(full_dates) == 1:
            # Extra bare years are ignored on purpose: an explicitly stated full
            # date is the more precise statement, and a trailing archive year is
            # not a competing claim.
            return next(iter(full_dates))
        if len(full_dates) > 1:
            log.debug("extract_as_of: %d distinct full dates, refusing to pick", len(full_dates))
            return None
        if len(years) == 1:
            # JANUARY 1 IS THE YEAR-PRECISION CONVENTION, not a stated day.
            return date(next(iter(years)), 1, 1)
        if len(years) > 1:
            log.debug("extract_as_of: %d distinct bare years, refusing to pick", len(years))
        return None
    except Exception:  # pragma: no cover - the never-raises guarantee, belt and braces
        log.debug("extract_as_of: unexpected failure, returning None", exc_info=True)
        return None
