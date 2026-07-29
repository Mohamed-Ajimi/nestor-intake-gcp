"""Claim attribution helpers (D-R3, phase 15.5 wave 2).

This module exports three functions. `extract_as_of` (plan 15.5-01) reads a date
out of a distilled claim EVIDENCE cell and IS called by the pipeline.
`parent_index` and `resolved_facet` (plan 15.5-02) are the FACET RESOLUTION SEAM
and are deliberately NOT called by the pipeline in this wave — see their
docstrings, and the section below.

WHY TWO OF THE THREE HAVE NO CALLER
-----------------------------------
Invariant 2 of D-R3 says a claim whose corroboration group spanned two client
questions must take its `facet` from its SUB-QUESTION'S PARENT rather than from
the group. In wave 2 that is a NO-OP BY CONSTRUCTION: `research_division._angle`
stamps `focus_area` from `w["parent"]`, and `sub_question` from `w["text"]`, so
a winner's parent label IS the facet already on the claim. `resolved_facet`
therefore resolves to today's value for EVERY claim in this wave.

Wiring it in would change nothing and would add a live call path for zero gain,
which invariant 3 forbids outright — no dispatch decision, no merge outcome and
no report sentence may move in this wave, because that is the one variable the
phase 15.8 measuring run has to hold still. So the seam exists, is pure, and is
proven by test instead of by use. Phase 15.6, which breaks the one-angle-one-
question assumption, is its first real caller and must re-prove the invariant it
is about to invalidate.

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
  * MONTH PRECISION, textual or numeric, with no day -> `date(YYYY, MM, 1)`.
    `maart 2021`, `March 2021`, `2021-03`, `03-2021` all yield 2021-03-01.
  * A BARE 4-digit year in 1900..2100 -> `date(YYYY, 1, 1)`.

THE FIRST OF THE PERIOD IS A CONVENTION, NOT A STATED DAY
---------------------------------------------------------
Say it out loud, because a reader of the `claim.as_of` column will otherwise
read `2021-01-01` as a source that said "1 January". It did not. `date(Y, 1, 1)`
is this module's encoding of YEAR PRECISION -- the source stated a year and
nothing finer -- and `date(Y, M, 1)` is the same encoding one level finer, for a
source that stated a month and nothing finer. PostgreSQL has no year-precision
or month-precision date type and D-W2-1 explicitly sanctions the bare year
rather than dropping it, so the convention is the price. Anything reasoning
about `as_of` at day resolution must treat the 1st of a month as suspect.

WHY MONTH PRECISION IS NOT ROUNDED TO THE YEAR (D-W2-4)
-------------------------------------------------------
This module originally read `maart 2021` as a bare year and returned 2021-01-01,
discarding the month. That was overturned by the operator on 2026-07-29, because
it broke the one case this column exists for.

The old behaviour was also internally inconsistent, and inconsistent in the
wrong direction: numeric `2021-03` was REJECTED for fabricating a day, while
`maart 2021` was ACCEPTED after fabricating a day AND overwriting March with
January. The looser form fabricated more.

The cost was concrete. De Haan reported 7 sites in one article and roughly 90 in
a later one. Had those read `maart 2021` and `december 2021`, both would have
collapsed onto 2021-01-01 -- nine months apart, recorded as the same instant,
which reads as a contradiction rather than a rollout. That is precisely the
D-V01-4 failure `as_of` was added to prevent, reintroduced by the encoding.

So a stated month is kept and encoded as its first day. This WIDENS what is
accepted: `2021-03` and `03-2021` used to return None and now parse. Everything
D-W2-1 actually bounds is untouched -- ambiguous numeric triples, 2-digit years,
digits inside longer runs, and the more-than-one-candidate rule all still hold.

THE REJECTIONS, WHICH ARE AS DELIBERATE AS THE ACCEPTANCES
----------------------------------------------------------
Every one of these returns None:

  * Any all-numeric date that is not ISO order: `03/04/2021`, `3-4-2021`,
    `04.03.2021`, `04-03-2021`. `03/04/2021` IS NOT DECIDABLE between DD/MM and
    MM/DD -- half the world writes each -- and guessing is precisely how a real
    contradiction becomes a fake time series. A `-` separator is accepted ONLY
    in `YYYY-MM-DD` order.
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
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — typing only, never imported at runtime
    from collections.abc import Iterable, Mapping

log = logging.getLogger(__name__)

__all__ = ["extract_as_of", "parent_index", "resolved_facet"]


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

# (2c) MONTH PRECISION, textual, no day: `maart 2021`, `March 2021` (D-W2-4).
#      Deliberately scanned AFTER (2a)/(2b): a day-bearing `4 maart 2021` has
#      already had its span blanked by then, so this can never re-read the tail
#      of a full date as a month-precision hit.
_TEXTUAL_MY_RE = re.compile(
    r"\b(" + _MONTH_ALTERNATION + r")\b\.?,?\s+(\d{4})(?!\d)",
    re.IGNORECASE,
)

# (3) The one REJECTED numeric form. Matched only to CONSUME it, so that the
#     year buried inside can never leak out to the bare-year rule.
#     `03/04/2021` must be None, not 2021.
_AMBIGUOUS_TRIPLE_RE = re.compile(r"(?<!\d)\d{1,4}[/.\-]\d{1,2}[/.\-]\d{1,4}(?!\d)")

# (3b) MONTH PRECISION, numeric, both orders: `2021-03`, `2021/03`, `03-2021`
#      (D-W2-4). Scanned AFTER the ambiguous triple above, so the `03/04` head of
#      `03/04/2021` is already blanked and cannot be mistaken for a month-year.
#      An out-of-range month (`2021-13`) is dropped by `take`, and because its
#      span is consumed anyway the year still cannot fall through.
_PARTIAL_YM_RE = re.compile(r"(?<!\d)(\d{4})[/.\-](\d{1,2})(?!\d)")
_PARTIAL_MY_RE = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{4})(?!\d)")

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

        # (2c) Textual month precision, no day (D-W2-4). Day 1 encodes "the
        #      source stated this month and nothing finer".
        text = _consume(
            text,
            _TEXTUAL_MY_RE,
            lambda m: take(int(m.group(2)), _MONTHS[m.group(1).lower()], 1),
        )

        # (3) Consume the ambiguous numeric triple WITHOUT collecting anything.
        #     This is not tidying: it is what stops the year inside `03/04/2021`
        #     from being read as a bare year in stage 4. It runs FIRST so that
        #     the month-precision scans below cannot chew off one of its halves.
        noop = lambda _match: None  # noqa: E731 - deliberate, keeps _consume uniform
        text = _consume(text, _AMBIGUOUS_TRIPLE_RE, noop)

        # (3b) Numeric month precision, both orders (D-W2-4). Same day-1
        #      convention as (2c) -- see the module docstring for why a stated
        #      month is kept rather than rounded away to January.
        text = _consume(
            text,
            _PARTIAL_YM_RE,
            lambda m: take(int(m.group(1)), int(m.group(2)), 1),
        )
        text = _consume(
            text,
            _PARTIAL_MY_RE,
            lambda m: take(int(m.group(2)), int(m.group(1)), 1),
        )

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


# ---------------------------------------------------------------------------
# THE FACET RESOLUTION SEAM (plan 15.5-02).
#
# NOT CALLED BY THE PIPELINE IN THIS WAVE. Read the module docstring's "why two
# of the three have no caller" section before wiring either of these in.
# ---------------------------------------------------------------------------


def parent_index(winners: "Iterable[object] | None") -> dict[str, str]:
    """Build ``{winner_text: parent_label}`` from a workshop winners list.

    **DELIBERATELY NOT CALLED BY THE PIPELINE.** Its only consumer today is
    `resolved_facet` and the test that proves invariant 2 is a no-op.

    **PHASE 15.6 EXAMINED THIS SEAM AND LEFT IT UNCALLED.** Wave 2 predicted 15.6
    would be its first production caller. It is not, and the reason is now
    STRUCTURAL rather than incidental — read `resolved_facet` below for the full
    finding, including the one code path on which the two values genuinely differ
    and resolving is nevertheless the WORSE answer.

    The winners list is the workshop tournament's own output — the same list
    `research_division.divide(..., winners=...)` consumes — where each entry is a
    dict carrying at least ``text`` (the sub-question) and ``parent`` (the client
    question it deepens).

    TOLERANT, AND NEVER RAISES. A non-dict entry, a missing/blank ``text`` and a
    missing/blank ``parent`` are each SKIPPED. A resolver that blew up on one
    malformed winner would cost a whole run its attribution, and this is a pure
    lookup table — there is nothing here worth failing a $50 run over.

    FIRST WINS on a repeated ``text``, matching D-W2-3's merge rule for the two
    columns this index resolves. Two winners with the same text and different
    parents is a workshop defect, not a case to arbitrate here.

    Args:
        winners: the workshop winners list, or None.

    Returns:
        A plain ``dict[str, str]``. Empty when there is nothing usable — never
        None, so a caller can index it without a guard.
    """
    index: dict[str, str] = {}
    try:
        for winner in winners or ():
            try:
                if not isinstance(winner, dict):
                    continue
                text = winner.get("text")
                parent = winner.get("parent")
                if not isinstance(text, str) or not text:
                    continue
                if not isinstance(parent, str) or not parent:
                    continue
                # FIRST WINS — `setdefault`, not assignment.
                index.setdefault(text, parent)
            except Exception:  # noqa: BLE001 — one bad winner costs that winner only
                log.debug("parent_index: unusable winner entry skipped")
    except Exception:  # pragma: no cover — the never-raises guarantee
        log.debug("parent_index: unexpected failure, returning what was built")
    return index


def resolved_facet(claim: dict, parents: "Mapping[str, str] | None") -> str | None:
    """The client question a claim really answers, resolved via its sub-question.

    **DELIBERATELY NOT CALLED BY THE PIPELINE.** In wave 2 this function returns
    exactly ``claim["facet"]`` for every claim a real run produces, because
    `research_division._angle` stamps `focus_area` from the winner's ``parent`` and
    `sub_question` from the winner's ``text`` — so the parent of a claim's
    sub-question IS the facet already on it. Calling it would change nothing and
    would add a live call path for zero gain, which D-R3 invariant 3 forbids.

    ==================================================================
    PHASE 15.6 EXAMINED THIS SEAM AND LEFT IT UNCALLED. Do not wire it in
    without reading all four cases below; each one has been checked against
    the code rather than reasoned about.
    ==================================================================

    Wave 2 recorded that this function exists so phase 15.6 could fill it "when an
    LLM-formed group can span two client questions and `facet` stops being true".
    **Operator decision D-W3-5 (2026-07-29) removed that condition.** Under
    mandate-strict grouping a mandate group contains members from exactly ONE
    client question, so the group's parent IS the angle's ``focus_area`` AND IS
    every mandate claim's correct facet. The resolver would return the claim's own
    facet for every claim in the run — a no-op for exactly the structural reason it
    was a no-op in wave 2, which is a STRONGER justification than the one wave 2
    recorded, not a weaker one.

    THE FOUR RESIDUAL CASES, recorded rather than papered over:

    1. **A discovery RIDER files under its host client question.** Accepted by
       D-W3-5.2, and this function could not improve it: the rider's own ``parent``
       IS that host label, so resolving returns the same value.
    2. **A cross-cutting ``d1`` claim files under ``labels[0]`` via the existing
       orphan rule.** Resolving would return ``__discovery__``, which is not a
       client question and therefore not a member of
       ``mission_brief["focus_areas"]`` — so `pipeline._propagate_stakes` would
       silently default its stakes to ``med`` and ``claims_per_facet`` would gain a
       key with no report section behind it. **Calling it here is WORSE, not
       better.** Say so explicitly, because it is the obvious "improvement" the
       next reader will attempt.
    3. **The ORPHAN path is the one place the two values genuinely DIFFER, and
       resolving is still worse.** `_angle` reads
       ``w["parent"] if w["parent"] in parent_prompt else labels[0]``, so a winner
       naming a parent that matches no client-validated label gets
       ``focus_area == labels[0]`` while this resolver would return the unmatched
       label itself. `build_mission_brief_from_winners` builds ``focus_areas``
       from the client labels ONLY, so that unmatched label is not one — and
       resolving to it would move the claim out of every report section and out of
       the client question's own count, which is precisely what the orphan rule
       exists to prevent. The rule is deliberate ("attached rather than dropped");
       this function would undo it.
    4. **More than five client questions**, where the ≤5 ceiling makes
       single-parent impossible and one mandate group may legitimately span two.
       This is the only case with anything to gain — and it is still not reachable,
       because a per-claim resolution needs a per-claim sub-question, and under
       group dispatch one angle covers the whole group. Phase 15.5 ruled that
       fabricating a sub-question is worse than a NULL, and that ruling stands.

    THE ONE CONDITION THAT WOULD MAKE THIS A CALLER: a genuine per-claim
    sub-question attribution channel, which requires a ``facet`` column in the D8
    fact-list contract (``facts.py`` — ``STATEMENT<TAB>SOURCE_URL<TAB>QUALITY<TAB>
    CERTAINTY<TAB>EVIDENCE`` has none, which is why `synthesis/steps.py` stamps
    ``facet`` in Python from the angle at three ``fact_source="fact_list"`` call
    sites). Changing that contract is out of scope for phase 15.6 and high-risk for
    the reasons D-W3-5 records.

    THE LOOKUP IS EXACT-STRING, ON PURPOSE. Both sides of it are the SAME
    engine-authored string: `divide()` copies ``w["text"]`` onto the angle as
    ``sub_question``, and this index is built from that same ``w["text"]``. This
    is NOT the V-01 corroboration-key mistake (an exact-string key over
    model-written CLAIM TEXT, which merged nothing) — fuzzy matching here would
    introduce ambiguity where there is none.

    NEVER RAISES, and never invents a parent: an unknown sub-question falls back
    to the claim's own ``facet`` rather than guessing.

    Args:
        claim: a claim dict, normally one produced by `collect_provider_facts`.
        parents: the index from `parent_index`, or None.

    Returns:
        The resolved parent label, else the claim's own ``facet``, else None.
        ``None`` means "no facet could be established" and is deliberately
        distinct from the empty string (D-W2-2: absent is NULL, never ``""``).
    """
    try:
        if not isinstance(claim, dict):
            return None

        own = claim.get("facet")
        own = own if isinstance(own, str) and own else None

        sub_q = claim.get("sub_question")
        if not isinstance(sub_q, str) or not sub_q:
            return own
        if not isinstance(parents, dict) and not hasattr(parents, "get"):
            return own

        parent = parents.get(sub_q) if parents is not None else None
        if isinstance(parent, str) and parent:
            return parent
        return own
    except Exception:  # pragma: no cover — the never-raises guarantee
        log.debug("resolved_facet: unexpected failure, falling back to None")
        return None
