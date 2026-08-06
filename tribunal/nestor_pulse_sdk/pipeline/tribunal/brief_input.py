"""Brief input parsing (D-G / D-H, plan 15.2-21) — split a seam brief into the
client's research QUESTIONS, the client's DECISION, and everything else as CONTEXT.

WHY THIS MODULE EXISTS, IN ONE PARAGRAPH. On run ``d6bb3aae`` (2026-07-27) the
question workshop was handed **32** "client-validated questions". Only **11** of
them were externally-researchable market questions. The other 21 were the intake's
own administrative fields: ``Decision-maker: MOE, CEO``, ``NDA status: intake says
'dont know'``, ``Primary client contact: MEEMZ (mohamed.ajimi@azentic.be)`` — and,
most plainly of all, **six paid research sub-questions were generated for
"Output size (hard constraint): Standard (15-25 pages)"**. Of the 11 paid deep-
research angles that were actually dispatched, 3 were legitimate external research.
The client's flagship questions — dynamic pricing, competitor coffee strategies,
the supermarket-format threat — were never dispatched at all. That is the incident
this module exists to prevent, and it is the requirement.

HOW IT HAPPENED. ``backend/app/research/brief.py::assemble_brief`` composes ONE
string: an opening line, an ``Onderzoeksvragen:`` header with the client's
questions enumerated ``1.``/``2.``/…, a prose report hint, and the FULL context
pack under a ``[CONTEXT PACK]`` header. The engine then threw that structure away —
``pipeline.py`` called ``run_question_workshop(questions=None, …)``, so
``workshop.normalise_questions`` fell through to
``intake.detect_explicit_questions(brief)``, whose enumeration regex accepts
``^\\s*[-*•]\\s+(.{10,})``: **every ``- **Bold:** value`` bullet in the context-pack
markdown**. The context-pack template is built almost entirely of such bullets
(§3 the decision, §5 scope, §9 stakeholders and NDA, §10 output size and tone).
11 real questions + 21 context-pack bullets = the 32 in the forensics.

WHY DIGITS ONLY. :data:`_ENUM_ITEM_RE` accepts ``1.`` / ``2)`` and NOTHING else.
It deliberately does **not** accept ``-``, ``*`` or ``•`` bullets. A bullet regex is
precisely what swallowed the context pack, and the producer of this brief always
enumerates the client's questions with digits. Widening this regex to bullets
re-opens D-G. If a future brief shape needs another item form, add a NEW explicit
marker (``[RESEARCH QUESTIONS]`` is already recognised) rather than widening this
one.

WHY THE CONTEXT PACK IS CONTEXT. The pack is not dropped and it is not truncated —
it is RECLASSIFIED. The workshop's orientation and candidate steps are *supposed*
to read the client's context; the defect was never that the workshop saw the pack,
it was that the pack was treated as a list of questions to deepen, rank and
dispatch. :attr:`ParsedBrief.context` carries every non-question, non-decision line
verbatim and in original order, which is exactly what the pack is named for.

WHAT THIS MODULE IS. Pure: no I/O, no LLM, no DB, no clock — the same discipline as
``citations/numbering.py`` and the parser half of ``pipeline/tribunal/facts.py``.
It NEVER raises: a parse failure degrades to ``source="error"`` with the whole brief
preserved as context, so the caller takes its legacy whole-brief detector path
rather than losing the brief.

THE FEED'S FIRST LINES (plan 15.3-05), AND WHY THEY DO NOT COST THE GUARANTEE ABOVE.
:func:`parse_brief` now also opens the run page's feed, describing what it understood
the brief to be. Three properties are load-bearing and none of them is optional:

  1. **Still pure in the sense that matters.** The emitter is a SYNCHRONOUS append to
     a bounded in-memory deque (``runs/run_events.py``): no socket, no session, no
     cursor, no ``await``. Nothing here reads a clock — the emitter timestamps its
     own rows on its own drain task, which this module never waits for.
  2. **Still never raises.** ``pipeline.py`` places the ``parse_brief`` call OUTSIDE
     its checkpoint branch *precisely because* this function is pure, free and safe
     (see the D-G comment there). Every emit therefore goes through
     ``run_events.emit_safe``, which takes a ZERO-ARGUMENT ``build()`` thunk so the
     f-strings and attribute reads that compose an event run INSIDE the emitter's
     ``try`` — a caller's arguments are evaluated before the callee is entered, so
     the plain entry point would move the failure back out to this call site and
     silently revoke the guarantee for every brief that states no decision (D-06).
  3. **THE EMIT IS OUTSIDE THIS FUNCTION'S OWN ``try``.** Inside it, a failing event
     would be caught by the parser's ``except`` and turn a perfectly good parse into
     ``source="error"`` — an observability path rewriting the result it observes.

  ``run_id`` is OPTIONAL and keyword-only. Omitted (every test, and any non-pipeline
  caller) the function is byte-for-byte what it was; the pipeline passes the run's id
  and the same parse additionally narrates itself.

D-G AND THE FEED (T-15.3-40). NO CONTEXT LINE IS EVER PUT INTO AN EVENT. The events
name the client's stated DECISION — a delimited, structured field — and COUNTS, and
nothing else. Reaching for "the brief's opening line" as a project label would make
``§9 Stakeholders`` the event text for any brief that leads with its context pack,
and ``- **Primair contact klant:** … (mohamed.ajimi@…)`` is one of the four lines
this module exists to keep away from third parties. ``scrub_pii`` at the emitter is
the SECOND layer here, never the first.

WHAT THIS MODULE IS NOT. It does not decide anything. It does not call the
workshop, it does not rank, and it does not know what a research angle is. The
Stage-1 wiring that consumes it lives in ``pipeline.py``; the producer of the
``[DECISION]`` block lives in ``backend/app/research/brief.py``.

Cloud Build gate (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# MODULE-IMPORT FORM, MANDATORY. Binding the emitter's names directly into this
# namespace would let a bare, unqualified call slip past the machine-checkable
# call-site gate this phase runs over every file that emits, while the gate stayed
# green — so the module is imported and every use stays qualified.
from nestor_pulse_sdk.runs import run_events

log = logging.getLogger(__name__)

#: The feed stage these events belong to. `intake` is a real `ENGINE_STAGES`
#: ["tribunal"] key ("brief received, client-validated questions identified") and it
#: is the stage `pipeline.py` is in when it calls this parser. Not invented here.
_EVENT_STAGE = "intake"

#: Characters of the client's stated decision echoed into the feed. Shorter than
#: `_DECISION_MAX_CHARS` on purpose: the event is a one-line orientation, and the
#: emitter clamps at 400 for the WHOLE row, so an unbounded decision would push the
#: sentence that frames it off the end of its own line.
_EVENT_DECISION_CHARS = 180

#: What the `thinking` line says when the brief carries no `[DECISION]` block. THE
#: ABSENCE IS THE INFORMATION (D-H): on run d6bb3aae there was no stated decision, the
#: judge was handed the project TITLE `Deep research for moetest.` to rank materiality
#: against, and report metadata out-ranked the client's real questions. An empty
#: half-sentence here would render that as though nothing were missing.
_NO_DECISION_TEXT = "no decision stated in the brief"


# ---------------------------------------------------------------------------
# The delimiters. `[DECISION]` / `[RESEARCH QUESTIONS]` are the EXPLICIT shape the
# intake backend emits from plan 15.2-21 onward. `Onderzoeksvragen:` is the LEGACY
# alias and is deliberately still recognised: a run queued BEFORE the backend
# redeploys must parse correctly too, because the entire point of this module is
# that no further run researches the wrong questions.
# ---------------------------------------------------------------------------
_DECISION_HEADER = "[DECISION]"
_DECISION_FOOTER = "[END DECISION]"
_QUESTIONS_HEADER = "[RESEARCH QUESTIONS]"
_QUESTIONS_FOOTER = "[END RESEARCH QUESTIONS]"
_CONTEXT_PACK_HEADER = "[CONTEXT PACK]"

#: The CLIENT-CHOSEN REPORT SHAPE block (quick task 260806-lvt). Producer is
#: ``backend/app/research/brief.py``, which spells the same two strings — changing
#: either is a SEAM CHANGE and both sides move in one commit, exactly as the
#: ``[DECISION]`` pair above.
#:
#: WHAT IT CARRIES AND WHY IT IS PARSED RATHER THAN READ AS PROSE. ``LANGUAGE`` is
#: the run's ONE output language. It is consumed twice downstream — by
#: ``synthesis/steps.py::_language_directive`` and by
#: ``research_division._d7_language_sentence`` — and BOTH interpolate it into a
#: prompt, so neither can recover it from a sentence. Measured on run ``368ff3a0``:
#: it was empty on every one of that run's dispatch assignments, so both consumers
#: silently took their weakened fallback branch and nothing anywhere said so.
_REPORT_HEADER = "[REPORT]"
_REPORT_FOOTER = "[END REPORT]"

#: Keys recognised inside the report block, lowercased at the point of comparison.
#: ``LANGUAGE`` lands on its own ``ParsedBrief`` field; the rest compose the
#: ``report_spec`` dict that ``synthesis/steps.py::_spec_directives`` already knows
#: how to render. Parsed BY NAME, so an unknown key costs that line and nothing else
#: — a producer that gains a key does not break a deployed reader.
_REPORT_SPEC_KEYS = ("length", "pages", "instructions")

#: Characters kept per report-block value. The block is engine-facing and every
#: value is either an enum this file does not trust or short client text; the one
#: that can be long is ``instructions``, which reaches a synthesis prompt verbatim
#: under "ADDITIONAL CLIENT INSTRUCTIONS". Bounding it is the same prompt-injection
#: control ``_QUESTION_MAX_CHARS`` is, applied to the same class of input.
_REPORT_VALUE_MAX_CHARS = 400

#: The legacy header, case-insensitive, trailing colon optional. It must match the
#: WHOLE line: a sentence that merely mentions the word is prose, not a header.
_LEGACY_QUESTIONS_HEADER_RE = re.compile(r"^onderzoeksvragen\s*:?$", re.IGNORECASE)

#: DIGITS ONLY. See the module docstring — this narrowness IS the fix.
_ENUM_ITEM_RE = re.compile(r"^\s*\d{1,2}[.)]\s+(.+)$")

#: Characters kept of the resolved decision statement. Matched to the producer's
#: own bound in `backend/app/research/brief.py::derive_decision_statement`, so the
#: two sides of the seam clamp at the same place and neither has to truncate the
#: other mid-sentence.
_DECISION_MAX_CHARS = 400

#: Characters kept per client question.
#:
#: DELIBERATELY 400 AND NOT `workshop._LABEL_MAX_CHARS` (120). 120 is the bound on a
#: question's LABEL — a dict key and the join key that plan 15.2-11's D4 superset
#: assertion compares on — and `workshop.normalise_questions` already derives that
#: 120-character label from the text it is handed. Bounding the TEXT at 120 here
#: would silently shorten a real client question before it was ever deepened: the
#: intake's own headline question ("Which fuel retailers in Europe apply dynamic
#: pricing today to fuel and/or shop products, how is it operationalised…") is
#: already longer than 120 characters, and cutting it mid-clause would be a quieter
#: version of the very defect this module closes. 400 is `workshop`'s own
#: `_QUESTION_MAX_CHARS` — the ceiling it applies when pasting a question into a
#: prompt — so nothing downstream ever sees more than it already bounded itself to.
#: Not env-tunable, for the same reason `_LABEL_MAX_CHARS` is not.
_QUESTION_MAX_CHARS = 400

#: Characters of a question used as its de-duplication key. Matches
#: `intake.detect_explicit_questions`' existing `seen` rule exactly, so a duplicated
#: question does not become two parents (the forensics counted "31 deepen calls +
#: 1 duplicate").
_DEDUPE_KEY_CHARS = 80


@dataclass(frozen=True)
class ParsedBrief:
    """The structural split of one seam brief. Frozen — a parse result is evidence.

    * ``questions`` — the client's enumerated research questions, in brief order,
      de-duplicated and bounded. These, and ONLY these, may become workshop parents.
    * ``decision`` — the client's stated decision, from an explicit ``[DECISION]``
      block. ``""`` when the brief carries none; the caller must then say so out
      loud rather than substituting a title (D-H).
    * ``context`` — every other line, verbatim and in original order: the opening
      line, the report hint and the entire ``[CONTEXT PACK]`` section. Material to
      read, never a question to dispatch.
    * ``language`` — the run's ONE output language as an English NAME ("Dutch"), from
      the ``[REPORT]`` block. ``""`` when the client was never asked — an intake
      predating the ``report_language`` field. The caller must let that stay empty and
      SAY SO, never substitute a detected language: guessing from the brief's dominant
      language is confidently wrong in exactly the case that matters, a Dutch-speaking
      client who needs an English report for an international board.
    * ``report_spec`` — the client's chosen report shape as
      ``{length?, pages?, instructions?}``, ready for
      ``synthesis/steps.py::_spec_directives``. ``{}`` when no block resolved, which is
      the OLD-INTAKE path and must keep producing today's default report byte for byte.
    * ``source`` — ``"structured"`` when a question block was found,
      ``"unstructured"`` when the brief is free prose (a legitimate shape — the
      caller then takes the deterministic whole-brief detector path deliberately
      rather than by accident), or ``"error"`` when the parse itself failed.
    """

    questions: list[str] = field(default_factory=list)
    decision: str = ""
    context: str = ""
    source: str = "unstructured"
    language: str = ""
    report_spec: dict = field(default_factory=dict)


def _is_section_marker(stripped: str) -> bool:
    """True when this line is one of the recognised structural delimiters."""
    if stripped in (
        _DECISION_HEADER,
        _DECISION_FOOTER,
        _QUESTIONS_HEADER,
        _QUESTIONS_FOOTER,
        _CONTEXT_PACK_HEADER,
        _REPORT_HEADER,
        _REPORT_FOOTER,
    ):
        return True
    return bool(_LEGACY_QUESTIONS_HEADER_RE.match(stripped))


def _blank_ends_unclosed_block(lines: list[str], index: int) -> bool:
    """Does the blank line at ``index`` terminate an unclosed ``[DECISION]`` block?

    The producer always emits ``[END DECISION]``, so this only matters for a
    hand-written or truncated brief. The rule is a paragraph break: a blank line
    followed by a NON-INDENTED line ends the block; a blank followed by an indented
    continuation does not. End-of-input ends it either way.
    """
    for candidate in lines[index + 1:]:
        if not candidate.strip():
            continue
        return not candidate.startswith((" ", "\t"))
    return True


def _emit_parse_events(run_id: Optional[uuid.UUID], parsed: Any) -> None:
    """Narrate one parse into the run feed. Best-effort; NEVER raises.

    ``parsed`` is annotated ``Any`` and read by plain attribute access on purpose.
    In production it is always a :class:`ParsedBrief`, whose fields cannot be absent
    — but a *degraded* result is exactly what these thunks have to survive, and the
    only way to prove that at this call site is to be able to hand it one. Every read
    below therefore happens inside a ``build()`` thunk, so an object with none of
    these attributes costs three feed lines and provably not the parse.

    No context line is ever put into an event: see the D-G / T-15.3-40 paragraph in
    the module docstring.
    """
    if run_id is None:
        # No run context — a test, or any caller that is not the pipeline. Nothing
        # to attribute the events to, and `emit` refuses a tenant-less write anyway.
        return

    run_events.emit_safe(
        run_id,
        stage=_EVENT_STAGE,
        kind="thinking",
        build=lambda: (
            "Analyzing brief — "
            f"{len(parsed.questions)} client question(s), "
            f"{(parsed.decision or '')[:_EVENT_DECISION_CHARS] or _NO_DECISION_TEXT}",
            None,
        ),
    )
    run_events.emit_safe(
        run_id,
        stage=_EVENT_STAGE,
        kind="tool",
        build=lambda: (
            "Loaded parse_brief — split the client's enumerated questions from the "
            f"context pack ({parsed.source} brief, "
            f"{len(parsed.context.splitlines())} context line(s) kept)",
            None,
        ),
    )
    run_events.emit_safe(
        run_id,
        stage=_EVENT_STAGE,
        kind="summary",
        # `text` is empty and the content lives entirely in `meta`, matching the
        # design of record: a summary row is composed from worked / actions / items /
        # cost, so a duplicate human sentence here would simply not be rendered.
        build=lambda: (
            "",
            {
                "actions": len(parsed.questions),
                "items": len(parsed.context.splitlines()),
            },
        ),
    )


def parse_brief(brief: str | None, *, run_id: Optional[uuid.UUID] = None) -> ParsedBrief:
    """Split ``brief`` into its questions / decision / context. NEVER raises.

    Recognised structure, resolved in ONE forward pass:

    * **The decision block** — lines strictly between ``[DECISION]`` and
      ``[END DECISION]``. When the footer is absent the block ends at the next
      recognised section marker or at a paragraph break. Whitespace-collapsed and
      bounded to :data:`_DECISION_MAX_CHARS`.
    * **The question block** — begins at a line that is exactly
      ``[RESEARCH QUESTIONS]`` or that matches the legacy ``Onderzoeksvragen:``
      header. It ends at ``[END RESEARCH QUESTIONS]``, at ``[CONTEXT PACK]``, at
      ``[DECISION]``, or at the first line inside it that is neither blank nor a
      DIGIT-enumerated item. Only :data:`_ENUM_ITEM_RE` items become questions.
    * **The context** — literally everything else, verbatim, in original order.

    A line consumed as a delimiter, as a decision line or as a question item does
    not also appear in ``context``; nothing else is dropped.

    ``run_id`` is OPTIONAL and KEYWORD-ONLY. Omitted, this call is byte-for-byte the
    function it has always been. Supplied, the same parse ALSO writes the run page's
    first three feed lines (see the module docstring) — which cannot change what is
    returned, cannot slow the parse by an I/O wait, and cannot raise.
    """
    raw = str(brief or "")
    try:
        lines = raw.splitlines()
        question_texts: list[str] = []
        decision_parts: list[str] = []
        context_lines: list[str] = []
        saw_question_block = False
        report_language = ""
        report_spec: dict = {}

        state = "none"
        index = 0
        total = len(lines)

        while index < total:
            line = lines[index]
            stripped = line.strip()

            if state == "decision":
                if stripped == _DECISION_FOOTER:
                    state = "none"
                    index += 1
                    continue
                if _is_section_marker(stripped):
                    # An unclosed decision block runs into the next section. Hand
                    # this line back to the top-level state WITHOUT advancing, so
                    # the marker still does its job.
                    state = "none"
                    continue
                if not stripped and _blank_ends_unclosed_block(lines, index):
                    state = "none"
                    context_lines.append(line)
                    index += 1
                    continue
                decision_parts.append(stripped)
                index += 1
                continue

            if state == "questions":
                if stripped == _QUESTIONS_FOOTER:
                    state = "none"
                    index += 1
                    continue
                if _is_section_marker(stripped):
                    state = "none"
                    continue
                if not stripped:
                    index += 1
                    continue
                match = _ENUM_ITEM_RE.match(line)
                if match:
                    question_texts.append(match.group(1).strip())
                    index += 1
                    continue
                # The first non-blank, non-enumerated line closes the block. This
                # is the guard that stops a stray prose line from dragging the rest
                # of the brief in behind it.
                state = "none"
                continue

            if state == "report":
                if stripped == _REPORT_FOOTER:
                    state = "none"
                    index += 1
                    continue
                if _is_section_marker(stripped):
                    # Unclosed block running into the next section: hand the line
                    # back WITHOUT advancing, exactly as the decision arm does.
                    state = "none"
                    continue
                if not stripped:
                    index += 1
                    continue
                # KEY: value, split on the FIRST colon only — an instruction may
                # legitimately contain more (`Target: max. 15 slides`).
                key, sep, value = stripped.partition(":")
                if sep:
                    name = key.strip().lower()
                    text = " ".join(value.split())[:_REPORT_VALUE_MAX_CHARS]
                    if text:
                        if name == "language":
                            report_language = text
                        elif name in _REPORT_SPEC_KEYS:
                            report_spec[name] = text
                # A line that is not KEY: value, or carries an unknown key, is
                # DROPPED rather than kept as context: it sat inside a delimiter pair
                # the producer owns, so treating it as material to read would let a
                # malformed block leak into the workshop's prompt.
                index += 1
                continue

            # state == "none"
            if stripped == _DECISION_HEADER:
                state = "decision"
                index += 1
                continue
            if stripped == _REPORT_HEADER:
                state = "report"
                index += 1
                continue
            if stripped == _QUESTIONS_HEADER or _LEGACY_QUESTIONS_HEADER_RE.match(stripped):
                state = "questions"
                saw_question_block = True
                index += 1
                continue
            context_lines.append(line)
            index += 1

        questions: list[str] = []
        seen: set[str] = set()
        for text in question_texts:
            text = (text or "").strip()
            if not text:
                continue
            text = text[:_QUESTION_MAX_CHARS]
            key = text.casefold()[:_DEDUPE_KEY_CHARS]
            if key in seen:
                log.debug(
                    "brief_input: dropping a duplicate client question %r — a "
                    "question listed twice must not become two workshop parents",
                    text[:80],
                )
                continue
            seen.add(key)
            questions.append(text)

        decision = " ".join(" ".join(decision_parts).split())[:_DECISION_MAX_CHARS]
        context = "\n".join(context_lines)
        source = "structured" if saw_question_block else "unstructured"

        # FAIL LOUD, IN WORDS (phase rule 7): every path says which one it took.
        if source == "structured" and questions:
            log.info(
                "brief_input: parsed %d client question(s) from the brief's question "
                "block; %d character(s) of the brief are CONTEXT (read by the "
                "workshop, never deepened, ranked or dispatched as questions); a "
                "stated client decision was %s",
                len(questions),
                len(context),
                "found" if decision else "NOT found",
            )
        elif source == "structured":
            log.warning(
                "brief_input: the brief has a question header but no digit-enumerated "
                "items under it, so no client question could be read from it — the "
                "caller falls back to its deterministic whole-brief detector"
            )
        else:
            log.info(
                "brief_input: the brief carries no question block (free prose, or a "
                "non-seam caller), so the caller takes its deterministic whole-brief "
                "detector path deliberately rather than by accident"
            )

        # FAIL LOUD ON THE EMPTY CASE (phase rule 7). An absent language is the
        # ONLY reason the run's one-language guarantee silently degrades to
        # "the language of the assignment above" in BOTH the dispatch sentence and
        # every synthesis prompt. On run 368ff3a0 that happened on every call and
        # nothing said so — which is why this line exists rather than a comment.
        if not report_language:
            log.warning(
                "brief_input: the brief states no report LANGUAGE, so the run's "
                "one-language-per-run guarantee falls back to inference — every "
                "synthesis prompt and every provider assignment will say 'the "
                "language of the assignment above' instead of naming a language"
            )

        result = ParsedBrief(
            questions=questions,
            decision=decision,
            context=context,
            source=source,
            language=report_language,
            report_spec=report_spec,
        )
    except Exception as exc:  # noqa: BLE001 — this parser never raises
        log.error(
            "brief_input: the brief could not be parsed (%r) — the whole brief is "
            "kept as context and the caller falls back to its legacy whole-brief "
            "detector, so nothing is lost and nothing is guessed",
            exc,
        )
        result = ParsedBrief(questions=[], decision="", context=raw, source="error")

    # OUTSIDE THE `try` ABOVE, DELIBERATELY. Inside it, a failing event would be
    # caught by this parser's own `except` and would rewrite a perfectly good parse
    # as `source="error"` — an observability path corrupting the result it observes,
    # which is a far worse failure than a missing feed line. Both paths are narrated:
    # a brief that could not be parsed is exactly the one an operator needs to see.
    _emit_parse_events(run_id, result)
    return result
