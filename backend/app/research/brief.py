"""Brief assembly (SEAM-04, D-01/D-01b) — compose the Tribunal run brief.

The brief string is what drives Tribunal's two pause gates. This module composes
a brief that NEVER trips either gate:

* **The interactive-report gate (D-01b):** Tribunal opts a run into interactive
  report shaping only when the brief carries the ``[INTERACTIVE_REPORT]`` marker
  (or the caller hits ``/report-spec``). We NEVER append that marker and NEVER
  call ``/report-spec`` — instead the report-length / structure preference is
  expressed as plain PROSE (:func:`derive_report_hint`) folded into the brief. A
  seam run therefore can never reach ``needs_report_spec`` (which would 500 a poll
  per 16-RESEARCH Pitfall 1).
* **The composition pause gate:** a vague brief with no concrete questions risks a
  composition pause. :func:`assemble_brief` always enumerates the validated
  research questions (priority order) under an explicit ``Onderzoeksvragen:``
  header, so the brief is never vague.

This module is PURE string production: no HTTP, no DB, no ORM writes. It reads a
decomposition's ``summary`` + the intake's research questions and returns a
brief the seam client (:func:`app.research.tribunal_client.create_run`) posts
verbatim.

Authoritative references:
- .planning/phases/16-research-trigger-progress-bridge/16-RESEARCH.md
    § Pattern 1 (marker-gate mechanics) + Pattern 2 (report-hint mapping) + Pitfall 1
- .planning/phases/16-research-trigger-progress-bridge/16-02-PLAN.md § interfaces (BRIEF SOURCES / REPORT-SPEC HINT)
"""

from __future__ import annotations

import re
from typing import Any, Iterable

#: The interactive-report pause-gate marker. It is a module constant ONLY so a
#: test can assert its ABSENCE from an assembled brief — it is NEVER concatenated
#: into any returned string (D-01b).
INTERACTIVE_REPORT_MARKER = "[INTERACTIVE_REPORT]"

#: The fixed fallback report-spec hint prose for a thin/missing intake (D-01b).
#: Plain Dutch prose — NEVER a ``/report-spec`` call, NEVER the marker.
_FALLBACK_HINT = "Standaard lengte, kerntabellen, alle onderzoeksvragen behandeld."

#: Question-count threshold above which the report length hint is "uitgebreid".
_MANY_QUESTIONS = 8

#: Intake answer field keys that hint at a sector/market structuring preference.
_SECTOR_FIELD_KEYS = ("sector", "industry", "market", "markt", "branche")

#: Intake answer field keys that carry stated research goals / objectives.
_GOALS_FIELD_KEYS = ("goals", "goal", "doelen", "doel", "objectives", "objective")

#: Answer field keys carrying the validated research questions. The GCP flow
#: stores questions in the intake ANSWERS — NOT in the legacy
#: ``nestor.research_questions`` table, which nothing in the new stack ever
#: writes (live finding 2026-07-21: reading only that table sent the engine an
#: empty brief and parked the run as ``needs_input``). Keys in precedence order:
#: ``research_questions`` is the AI-review-refined list the operator validated
#: (AIReviewPanel writes it back under that key); ``questions`` is the client's
#: original form field (pre-review fallback). ``extra_questions_proposed`` is
#: Nestor's proposal list — only ``approved`` entries count.
_CLIENT_QUESTIONS_KEYS = ("research_questions", "questions")
_PROPOSED_QUESTIONS_KEY = "extra_questions_proposed"

#: Label under which the FULL context pack is folded into the brief. The engine's
#: intake stage is a DELEGATOR now (quick task 260721-twy) — it never re-judges an
#: operator-validated brief as vague — so the brief carries the full context pack
#: verbatim under this header (no truncation, no clarification framing).
_CONTEXT_PACK_HEADER = "[CONTEXT PACK]"

#: Delimiters for the CLIENT'S STATED DECISION (D-H, plan 15.2-21). The engine's
#: ``pipeline/tribunal/brief_input.py::parse_brief`` reads exactly these two lines
#: and lifts what sits between them into the string the Swiss tournament judges
#: materiality against. Before this block existed, the engine had no decision to
#: judge against and fell back to the brief's opening line: on run ``d6bb3aae``
#: every tournament prompt in the run read "The client's decision this research has
#: to serve: Deep research for moetest." — a project TITLE. Ranking by materiality
#: to a title is arbitrary, which is how report-format and NDA metadata out-ranked
#: the client's real research questions. Changing either string is a SEAM CHANGE:
#: the engine-side parser must change in the same commit.
_DECISION_HEADER = "[DECISION]"
_DECISION_FOOTER = "[END DECISION]"

#: Intake answer field keys carrying the client's own decision, in the same shape
#: as :data:`_SECTOR_FIELD_KEYS` above. ``decision_or_goal`` and ``decision`` are
#: the English form-field keys; ``beslissing`` / ``beslisvraag`` / ``doel_beslissing``
#: are the Dutch ones the live Pulse template uses. Matched case-insensitively by
#: :func:`_first_nonempty`, which is why no cased variants are listed.
_DECISION_FIELD_KEYS = (
    "decision_or_goal",
    "decision",
    "beslissing",
    "beslisvraag",
    "doel_beslissing",
)

#: Delimiters for the CLIENT-CHOSEN REPORT SHAPE (quick task 260806-lvt). Same seam
#: contract as the decision block above: the engine's
#: ``pipeline/tribunal/brief_input.py::parse_brief`` reads exactly these two lines
#: and lifts the ``KEY: value`` lines between them onto ``ParsedBrief``. Changing
#: either string is a SEAM CHANGE — the engine-side parser changes in the same commit.
#:
#: WHY A BLOCK AND NOT PROSE, because :func:`derive_report_hint` right below already
#: folds report preferences in as prose and a reader will ask. Prose is exactly what
#: was broken: it can only nudge the model's inference. ``mission_brief["language"]``
#: is a STRUCTURED value read by ``synthesis/steps.py::_language_directive`` and by
#: ``research_division._d7_language_sentence`` — neither can read a sentence. Measured
#: on run ``368ff3a0``: all five dispatch assignments carried the fallback
#: "Report all findings in the language of the assignment above." because that value
#: was empty, and the strong "Write EVERYTHING in {lang} and ONLY {lang}" directive
#: has therefore never fired in production.
_REPORT_HEADER = "[REPORT]"
_REPORT_FOOTER = "[END REPORT]"

#: Keys INSIDE the report block. Spelled once here and parsed by name on the engine
#: side, so an unknown key is ignorable rather than positional.
_REPORT_KEY_LANGUAGE = "LANGUAGE"
_REPORT_KEY_LENGTH = "LENGTH"
_REPORT_KEY_PAGES = "PAGES"
_REPORT_KEY_INSTRUCTIONS = "INSTRUCTIONS"

#: Intake answer field keys carrying the client's report language / size choice, in
#: the same shape as :data:`_SECTOR_FIELD_KEYS`. ``report_language`` / ``output_size``
#: are the live Pulse template keys; the rest are tolerated aliases.
_LANGUAGE_FIELD_KEYS = ("report_language", "rapporttaal", "report_lang")
_OUTPUT_SIZE_FIELD_KEYS = ("output_size", "rapportomvang", "report_size")

#: Report-language code -> the ENGLISH language NAME the engine interpolates.
#: The engine reads this value twice and both readers want a NAME, not a code:
#: ``_language_directive`` writes it straight into an English prompt ("Write
#: EVERYTHING in Dutch and ONLY Dutch"), and ``workshop_rank._RUN_LANG_CODES`` maps
#: the name back to an ISO code to derive default SEARCH languages. Every name below
#: is a key of that map (verified 2026-08-06) — an unmapped name would cost the
#: search-language default while still producing a correct output directive.
_RUN_LANGUAGE_NAMES: dict[str, str] = {"nl": "Dutch", "fr": "French", "en": "English"}

#: The same map read backwards, so :func:`derive_report_language_code` can hand a
#: CODE to :func:`_resolve_localized` without a second reader of the answers. Derived
#: from the map above rather than spelled out again — one of the two would rot.
_RUN_LANGUAGE_CODES: dict[str, str] = {name: code for code, name in _RUN_LANGUAGE_NAMES.items()}

#: The variant :func:`_resolve_localized` falls back to. ``nl`` is the guaranteed key
#: on the frontend's own ``LocalizedString`` (``localizeSchema.ts``), so both sides of
#: the app fall back to the same language rather than to two different ones.
_LOCALIZED_FALLBACK_LANG = "nl"

#: ``output_size`` answer -> the report spec the engine's
#: ``synthesis/steps.py::_spec_directives`` consumes.
#:
#: OPERATOR RULING 2026-08-06: keep BOTH the keyword and the page range. Collapsing
#: to ``brief``/``comprehensive`` alone was explicitly rejected — a page target is
#: something the writer can visibly miss, an adjective is not. ``standard`` carries a
#: target with NO keyword on purpose: it is the default shape so there is no
#: adjective to add, but the client was still promised 5-10 pages.
#:
#: THE PAGE RANGES ARE ASSERTED AGAINST THE TEMPLATE'S OWN OPTION LABELS by
#: ``test_research_brief.py``. There are now two places the client sees a number —
#: the label they read on the form and the instruction the writer receives — and
#: that test is what stops them drifting apart silently.
_OUTPUT_SIZE_SPEC: dict[str, dict[str, str]] = {
    "compact": {"length": "brief", "pages": "2-5"},
    "standard": {"pages": "5-10"},
    "extended": {"length": "comprehensive", "pages": "10-20"},
}

#: The context pack's §3 decision line, as written by
#: ``app.ai.prompts.CONTEXT_PACK_SKILL_PROMPT``:
#: ``- **Wat moet beslist worden:** [concreet]``. Tolerant of a leading ``-``/``*``
#: bullet, of ``**`` or ``__`` emphasis, of the colon sitting inside or outside the
#: emphasis, and of the English label — the pack is authored by an AI skill and its
#: punctuation is not a contract.
_DECISION_LINE_RE = re.compile(
    r"^\s*[-*•]?\s*(?:\*\*|__)?\s*"
    r"(?:wat moet beslist worden|what must be decided)"
    r"\s*:?\s*(?:\*\*|__)?\s*:?\s*(?P<value>.*)$",
    re.IGNORECASE,
)

#: Values the context pack writes when the intake is too thin to state a decision.
#: The pack is being HONEST when it emits these, and a placeholder is not a
#: decision — accepting one would put "[concreet]" in front of the tournament as
#: though the client had decided something.
_DECISION_PLACEHOLDERS = frozenset({"concreet", "nog in te vullen", "tbd", ""})

#: The deterministic opening-line shape :func:`assemble_brief` falls back to when a
#: decomposition has no summary. It is a TITLE, and step 3 of
#: :func:`derive_decision_statement` must never return it as a decision — that
#: exact string, ``Deep research for moetest.``, IS defect D-H.
_TITLE_FALLBACK_PREFIX = "deep research for "

#: Characters kept of the resolved decision statement. Matched to the engine's own
#: ``brief_input._DECISION_MAX_CHARS``, so the two sides of the seam clamp at the
#: same place and the engine's ``_GATE_DECISION_CONTEXT_CHARS`` never has to cut a
#: decision mid-sentence.
_DECISION_MAX_CHARS = 400


def _answers_map(intake: Any) -> dict[str, Any]:
    """Best-effort ``{field_key: value}`` map from an intake-like object.

    The report-spec hint is field-driven but the intake's answers may be exposed
    in several shapes depending on the caller (an ORM ``Intake`` with an
    ``.answers`` relationship, a plain DTO carrying an ``answers`` dict, or a bare
    object with neither). This coerces all of them to a flat ``{field_key: value}``
    dict and returns ``{}`` when nothing is available — the thin-intake path.

    Never raises: a shape it does not recognize yields ``{}`` (fallback prose).
    """
    if intake is None:
        return {}

    # Shape A: a plain mapping already, or a DTO carrying an ``answers`` dict.
    raw = getattr(intake, "answers", None)
    if raw is None and isinstance(intake, dict):
        raw = intake.get("answers")

    if isinstance(raw, dict):
        return {str(k): v for k, v in raw.items()}

    # Shape B: an iterable of answer rows exposing ``.field_key`` / ``.value``.
    if isinstance(raw, Iterable) and not isinstance(raw, (str, bytes)):
        out: dict[str, Any] = {}
        for row in raw:
            key = getattr(row, "field_key", None)
            if key is None and isinstance(row, dict):
                key = row.get("field_key")
            if key is None:
                continue
            value = getattr(row, "value", None)
            if value is None and isinstance(row, dict):
                value = row.get("value")
            out[str(key)] = value
        return out

    return {}


def _resolve_localized(value: Any, lang: str = "") -> str:
    """Resolve an AI-authored string to ONE language. PURE, never raises.

    THIS FUNCTION EXISTS TO STOP A DICT REPR REACHING A PAID RESEARCH QUESTION.
    Since quick task 260831-lm4 the intake skill emits every string it AUTHORS as
    ``{"nl": ..., "fr": ..., "en": ...}``, and ``AIReviewPanel`` writes that object
    straight back into the intake answers the moment the operator accepts it. Any
    ``str()`` of such a value returns the PYTHON REPR —
    ``"{'nl': 'Wat is…', 'fr': 'Quel est…'}"`` — which would then be dispatched to the
    engine as the question to research, in a run costing roughly $45. Silently, because
    every reader in this module is documented "never raises".

    Resolution order, and each step is load-bearing:

    1. a plain ``str`` passes through unchanged — OLD INTAKES ARE NOT MIGRATED, so the
       scalar shape is the compatibility story and must stay first;
    2. ``value[lang]`` — the client's chosen report language (operator ruling);
    3. ``value["nl"]`` — the guaranteed variant, matching the frontend's own fallback
       in ``localizeSchema.ts`` so the two sides never disagree about which language
       "no preference" means;
    4. the first non-empty variant of whatever IS present — a model that dropped a key
       must still yield TEXT rather than a repr;
    5. ``""`` — anything else (numbers, objects, ``None``). Empty is recoverable and
       visible; a repr is neither.
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (lang.strip().lower()[:2], _LOCALIZED_FALLBACK_LANG):
            if not key:
                continue
            variant = value.get(key)
            if isinstance(variant, str) and variant.strip():
                return variant.strip()
        for variant in value.values():
            if isinstance(variant, str) and variant.strip():
                return variant.strip()
    return ""


def _first_nonempty(
    answers: dict[str, Any], keys: tuple[str, ...], lang: str | None = None
) -> str | None:
    """Return the first non-empty answer value whose key matches (case-insensitive).

    ``lang`` is OPT-IN and defaults to ``None``, which keeps the historical
    ``str(value)`` behaviour byte-for-byte for the callers that read the client's own
    scalar answers (sector, goals). Pass a language ONLY for a field that can hold an
    AI-AUTHORED value — today that is ``decision_or_goal``, which ``AIReviewPanel``
    overwrites with the skill's ``suggested`` object on accept. Those values go through
    :func:`_resolve_localized` instead, so the ``[DECISION]`` block the engine ranks
    materiality against can never be a stringified dict.
    """
    lowered = {k.lower(): v for k, v in answers.items()}
    for key in keys:
        value = lowered.get(key)
        if value is None:
            continue
        text = _resolve_localized(value, lang) if lang is not None else str(value).strip()
        if text:
            return text
    return None


def _radio_answer(answers: dict[str, Any], keys: tuple[str, ...]) -> tuple[str, str]:
    """Return ``(choice, free_text)`` for a radio answer. PURE, never raises.

    THIS READER IS NOT OPTIONAL, and the reason is a real storage shape rather than
    defensiveness. ``FieldRenderer`` stores a radio option carrying ``allow_text`` as
    ``{"choice": ..., "text": ...}`` and a plain radio as the bare option value. Both
    shapes live in the same answer map. :func:`_first_nonempty` would ``str()`` the
    dict one into ``"{'choice': 'other', 'text': ...}"`` — a truthy string that
    matches no key of :data:`_OUTPUT_SIZE_SPEC` — so the client's answer would read
    as "unset" instead of as "other", silently and with no error anywhere.

    Returns ``("", "")`` when nothing resolves.
    """
    lowered = {k.lower(): v for k, v in answers.items()}
    for key in keys:
        value = lowered.get(key)
        if value is None:
            continue
        if isinstance(value, dict):
            choice = str(value.get("choice") or "").strip()
            text = str(value.get("text") or "").strip()
            if choice or text:
                return choice, text
            continue
        text = str(value).strip()
        if text:
            return text, ""
    return "", ""


def derive_report_language(intake: Any) -> str:
    """Return the client's chosen report language as an ENGLISH NAME, or ``""``.

    PURE, never raises. ``""`` means the client was never asked (an intake predating
    the ``report_language`` field) — the caller must let that stay empty and say so
    out loud, NOT substitute a guess. Detecting the brief's dominant language would
    be confidently wrong in exactly the case that matters: a Dutch-speaking client
    who needs an English report for an international board.
    """
    choice, _ = _radio_answer(_answers_map(intake), _LANGUAGE_FIELD_KEYS)
    return _RUN_LANGUAGE_NAMES.get(choice.lower(), "")


def derive_report_language_code(intake: Any) -> str:
    """The client's report language as an ISO-ish CODE (``nl``/``fr``/``en``), or ``""``.

    The engine wants an English NAME (:func:`derive_report_language`);
    :func:`_resolve_localized` wants the CODE the skill keyed its output by. This maps
    the one to the other, deliberately derived FROM the function above rather than by
    reading the answers a second time: two independent readers of the same radio could
    disagree about which language the client chose, and only one of them feeds the
    engine. ``""`` means the client was never asked, and the resolver then falls back
    to ``nl`` — this function never guesses.
    """
    return _RUN_LANGUAGE_CODES.get(derive_report_language(intake), "")


def derive_report_spec(intake: Any) -> dict[str, str]:
    """Map the client's ``output_size`` answer to a report spec. PURE, never raises.

    Returns ``{}`` when nothing resolves — which is the OLD-INTAKE path and must keep
    producing today's default report exactly, because ``pipeline.py``'s zero-touch
    branch passes ``report_spec=None`` for it.

    ``other`` carries no page range by construction: the client wrote their own
    constraint ("max. 15 slides for ExCo") and it goes to ``instructions``, which
    ``_spec_directives`` renders under "ADDITIONAL CLIENT INSTRUCTIONS (follow
    these)". Inventing a page range for it would overrule the thing they typed.
    """
    choice, free_text = _radio_answer(_answers_map(intake), _OUTPUT_SIZE_FIELD_KEYS)
    spec: dict[str, str] = dict(_OUTPUT_SIZE_SPEC.get(choice.lower(), {}))
    if free_text:
        spec["instructions"] = free_text
    return spec


def _report_block_lines(intake: Any) -> list[str]:
    """The ``[REPORT]`` block for this intake, or ``[]`` when nothing resolves.

    Emitted ONLY when at least one value resolves — the same never-emit-an-empty-block
    rule the decision block applies, and for the same reason: a block made of
    whitespace parses as a client CHOICE of whitespace, which is worse than no block
    at all because no block is reported as a named degradation.
    """
    language = derive_report_language(intake)
    spec = derive_report_spec(intake)
    if not language and not spec:
        return []

    lines = ["", _REPORT_HEADER]
    if language:
        lines.append(f"{_REPORT_KEY_LANGUAGE}: {language}")
    if spec.get("length"):
        lines.append(f"{_REPORT_KEY_LENGTH}: {spec['length']}")
    if spec.get("pages"):
        lines.append(f"{_REPORT_KEY_PAGES}: {spec['pages']}")
    if spec.get("instructions"):
        # Collapsed to ONE line: the block is line-oriented and a client instruction
        # containing a newline would otherwise forge a block line of its own.
        instructions = " ".join(str(spec["instructions"]).split())
        lines.append(f"{_REPORT_KEY_INSTRUCTIONS}: {instructions}")
    lines.append(_REPORT_FOOTER)
    return lines


def derive_report_hint(intake: Any, question_count: int = 0) -> str:
    """Return PROSE report-spec hints derived from the intake (D-01b — never the marker).

    Maps intake answers to Dutch prose report-structuring hints WITHOUT ever
    calling ``/report-spec`` or appending ``[INTERACTIVE_REPORT]``:

    * a sector / market / industry answer -> "Structureer het rapport per
      marktsegment / sector.";
    * stated goals -> "Behandel expliciet: {goals} als aparte secties.";
    * a length cue keyed off ``question_count`` (``uitgebreid`` when many,
      ``standaard`` otherwise).

    When the intake is thin (none of the above resolve) it returns the fixed
    :data:`_FALLBACK_HINT` verbatim — a deterministic, non-vague default. The
    returned prose NEVER contains :data:`INTERACTIVE_REPORT_MARKER`.
    """
    answers = _answers_map(intake)

    lines: list[str] = []

    sector = _first_nonempty(answers, _SECTOR_FIELD_KEYS)
    if sector:
        lines.append("Structureer het rapport per marktsegment / sector.")

    goals = _first_nonempty(answers, _GOALS_FIELD_KEYS)
    if goals:
        lines.append(f"Behandel expliciet: {goals} als aparte secties.")

    if lines:
        length = "uitgebreid" if question_count > _MANY_QUESTIONS else "standaard"
        lines.append(f"Gewenste lengte: {length}.")
        return " ".join(lines)

    # Thin/missing intake -> the fixed fallback (D-01b, deterministic).
    return _FALLBACK_HINT


def _is_decision_placeholder(value: str) -> bool:
    """True when a §3 value is the pack's own "not filled in yet" text, not a decision."""
    return value.strip().strip("[]*_ ").strip().lower() in _DECISION_PLACEHOLDERS


def _decision_from_context_pack(context_pack_text: str | None) -> str:
    """The context pack's §3 "Wat moet beslist worden" value, or ``""``. Never raises."""
    for raw_line in str(context_pack_text or "").splitlines():
        match = _DECISION_LINE_RE.match(raw_line)
        if not match:
            continue
        value = (match.group("value") or "").strip()
        # Trailing emphasis the label group did not consume (`**value**`).
        value = value.strip("*_ ").strip()
        if not value or _is_decision_placeholder(value):
            continue
        return value
    return ""


def derive_decision_statement(
    intake: Any,
    decomposition: Any = None,
    context_pack_text: str | None = None,
) -> str:
    """The CLIENT'S OWN DECISION, in one bounded line (D-H). Pure; never raises.

    The Tribunal's Swiss tournament ranks candidate sub-questions by how much they
    matter *to a decision*. Its entire output is arbitrary if it has no decision to
    judge against — which is exactly what happened on run ``d6bb3aae``, where the
    engine had none and fell back to the brief's opening line, so every tournament
    prompt in the run judged materiality against ``Deep research for moetest.``

    Resolution, most specific source first. Each step says why it ranks where it
    does, because the ORDER is the whole design:

    1. **The context pack's §3 line** — ``- **Wat moet beslist worden:** …``. This
       is the sharpest statement of the decision that exists anywhere in the flow:
       it is written by the context-pack skill FROM the validated intake, reviewed
       by the operator, and it is the one place the decision is expressed as a
       decision rather than as a goal or a topic. A value that is the pack's own
       placeholder (``[concreet]``, ``nog in te vullen``) is rejected — the pack
       writes those honestly when the intake is thin, and a placeholder is not a
       decision.
    2. **The intake's own decision answer** (:data:`_DECISION_FIELD_KEYS`) — the
       client's raw words. Below the pack because it is unreviewed and often
       phrased as an aim rather than a choice, but it is still the client's.
    3. **The decomposition summary** — a model's one-line framing of the whole
       assignment. Usable as a last resort, but ONLY when it is not the
       deterministic ``"Deep research for …"`` fallback :func:`assemble_brief`
       produces when there is no summary at all. That string is a TITLE. Returning
       it here would re-create D-H one layer earlier, and quietly.
    4. ``""`` — no decision could be resolved. The engine then says so as a named
       degradation reason. Silence is what this function exists to end, so it
       returns nothing rather than something plausible.

    The result is whitespace-collapsed and bounded to
    :data:`_DECISION_MAX_CHARS`, matching the engine-side clamp so neither side has
    to truncate the other mid-sentence.
    """
    try:
        # 1. The context pack's §3 decision line.
        statement = _decision_from_context_pack(context_pack_text)

        # 2. The intake's own decision answer. Resolved through _resolve_localized
        # (the `lang` argument), NOT str(): `decision_or_goal` stops being the client's
        # raw words the moment the operator accepts the skill's suggestion —
        # AIReviewPanel overwrites the answer with the skill's `suggested` value, which
        # since 260831-lm4 is a {"nl","fr","en"} object. Without this the [DECISION]
        # block would carry a Python dict repr, and the engine's Swiss tournament would
        # rank every candidate sub-question's materiality against that repr.
        if not statement:
            statement = (
                _first_nonempty(
                    _answers_map(intake),
                    _DECISION_FIELD_KEYS,
                    derive_report_language_code(intake),
                )
                or ""
            )

        # 3. The decomposition summary — but never the deterministic title fallback.
        if not statement:
            summary = getattr(decomposition, "summary", None)
            if summary is None and isinstance(decomposition, dict):
                summary = decomposition.get("summary")
            summary = str(summary or "").strip()
            if summary and not summary.lower().startswith(_TITLE_FALLBACK_PREFIX):
                statement = summary

        # 4. Nothing.
        return " ".join(str(statement or "").split())[:_DECISION_MAX_CHARS]
    except Exception:  # noqa: BLE001 — a brief must never fail to compose
        return ""


def _item_text(item: Any, lang: str = "") -> str:
    """Best-effort question text from a list/proposal_list entry (never raises).

    ``text`` is resolved through :func:`_resolve_localized`, NOT through ``str()``.
    This is the single highest-consequence line in the module: the value it returns is
    enumerated under ``Onderzoeksvragen:`` and dispatched to the engine as a question
    to research. Before quick task 260831-lm4 a localized ``text`` object would have
    been stringified into its Python repr and researched AS a repr, for roughly $45,
    with nothing raising.

    ``lang`` defaults to ``""`` so the old one-argument call still resolves (to ``nl``);
    callers with an intake in hand pass the client's :func:`derive_report_language_code`.
    """
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return _resolve_localized(item.get("text"), lang)
    return _resolve_localized(getattr(item, "text", None), lang)


def questions_from_answers(intake: Any) -> list[dict]:
    """Derive the validated question list from the intake's ANSWERS (the real source).

    * ``questions`` — the client's own list-field entries (``{text, kind}``),
      validated by submission → priority 1;
    * ``extra_questions_proposed`` — Nestor's AI-proposed extras reviewed by the
      operator (``{text, rationale, approved}``) → only ``approved`` entries
      count → priority 2.

    Returns ``[{question_text, priority}]`` dicts compatible with
    :func:`assemble_brief`. Unrecognized shapes contribute nothing (never raises).

    Both lists can carry AI-AUTHORED text: ``research_questions`` is patched by
    ``AIReviewPanel`` with the skill's accepted ``suggested`` value, and
    ``extra_questions_proposed`` is the skill's own proposal list. Since 260831-lm4
    those values may be ``{"nl", "fr", "en"}`` objects, so every one of them is
    resolved to the client's CHOSEN REPORT LANGUAGE here (operator ruling) before it
    can become a question.
    """
    answers = _answers_map(intake)
    lang = derive_report_language_code(intake)
    out: list[dict] = []

    # First non-empty client-question source wins (refined list over raw form list).
    for key in _CLIENT_QUESTIONS_KEYS:
        raw = answers.get(key)
        if isinstance(raw, (list, tuple)):
            found = False
            for item in raw:
                text = _item_text(item, lang)
                if text:
                    out.append({"question_text": text, "priority": 1})
                    found = True
            if found:
                break

    raw = answers.get(_PROPOSED_QUESTIONS_KEY)
    if isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, dict) and not item.get("approved"):
                continue
            text = _item_text(item, lang)
            if text:
                out.append({"question_text": text, "priority": 2})

    return out


def validated_questions(intake: Any, questions: Any) -> list[Any]:
    """The final list a brief enumerates: DB rows when present, else answer-derived.

    The trigger route uses this for its empty-brief guard (a research run must
    never start on zero questions — the engine would park it as ``needs_input``).
    """
    ordered = _ordered_questions(questions)
    if ordered:
        return ordered
    return _ordered_questions(questions_from_answers(intake))


def assemble_brief(
    intake: Any,
    decomposition: Any,
    questions: Any,
    *,
    context_pack_text: str | None = None,
) -> str:
    """Compose the Tribunal run brief from the validated context pack (SEAM-04).

    Structure (the composition-gate-safe shape):

    1. an opening line — the decomposition ``summary`` when present, else a
       deterministic ``"Deep research for {project_title}."`` fallback (never
       blank);
    2. an ``Onderzoeksvragen:`` header followed by the research questions
       ENUMERATED in ascending ``priority`` order (``1. ...`` / ``2. ...``);
    3. a :data:`_DECISION_HEADER` / :data:`_DECISION_FOOTER` block carrying the
       client's stated decision (:func:`derive_decision_statement`), emitted ONLY
       when a decision actually resolves — an empty block would parse, on the
       engine side, as a decision made of whitespace. It sits between the questions
       and the hint so the decision reads as part of the ASSIGNMENT rather than as
       one more line of context (D-H, plan 15.2-21);
    3b. a :data:`_REPORT_HEADER` / :data:`_REPORT_FOOTER` block carrying the client's
       CHOSEN report language and size (:func:`derive_report_language`,
       :func:`derive_report_spec`), emitted only when one of them resolves. Parsed
       values, not prose — see the constants' own comment for why that distinction is
       the whole point of the block;
    4. the :func:`derive_report_hint` PROSE tail;
    5. a labeled :data:`_CONTEXT_PACK_HEADER` Context section carrying the FULL
       ``context_pack_text`` verbatim (untruncated) — or, when no context pack is
       supplied, a compact entity-bits fallback (title / sector / goals) under the
       same header.

    The returned brief NEVER contains :data:`INTERACTIVE_REPORT_MARKER` — the seam
    run cannot opt into the interactive-report pause gate (D-01b). Enumerating the
    concrete questions keeps the brief non-vague so the composition pause gate does
    not fire either (T-16-04).

    There is no force-proceed / clarification-answers machinery here anymore
    (quick task 260721-twy): the engine's intake stage is a delegator that always
    produces a research plan, so the brief simply carries the full validated
    context instead of clarification-shaped filler. The empty-questions 422 guard
    lives in the trigger route (:func:`validated_questions`) and is untouched.
    """
    # 1) Opening line — summary or a deterministic project-title fallback.
    summary = getattr(decomposition, "summary", None)
    if summary is None and isinstance(decomposition, dict):
        summary = decomposition.get("summary")
    opening = (summary or "").strip()
    if not opening:
        project_title = _project_title(intake)
        opening = f"Deep research for {project_title}."

    # 2) Enumerated questions in ascending priority order. Falls back to the
    # answer-derived list when no DB rows exist (the normal GCP-flow case).
    ordered = validated_questions(intake, questions)
    question_lines = ["Onderzoeksvragen:"]
    for index, q in enumerate(ordered, start=1):
        text = getattr(q, "question_text", None)
        if text is None and isinstance(q, dict):
            text = q.get("question_text")
        question_lines.append(f"{index}. {(text or '').strip()}")

    sections = [opening, "", *question_lines]

    # 3) The client's stated decision (D-H). Emitted ONLY when one resolves: an
    # empty `[DECISION]` / `[END DECISION]` pair would give the engine a decision
    # made of whitespace, which is worse than none — none is reported as a named
    # degradation, whitespace is silently ranked against.
    decision = derive_decision_statement(intake, decomposition, context_pack_text)
    if decision:
        sections += ["", _DECISION_HEADER, decision, _DECISION_FOOTER]

    # 3b) The client-chosen report shape (quick task 260806-lvt). Sits AFTER the
    # decision and BEFORE the prose hint, so the two report-shaping inputs read in
    # increasing vagueness: the parsed block first, the prose that only nudges
    # inference second. Emitted only when something resolves.
    sections += _report_block_lines(intake)

    # 4) Report-spec hint prose (never the marker).
    #
    # DELIBERATELY KEPT alongside the block above rather than replaced by it. It
    # carries structuring hints the block does not model (per-sector structure,
    # goals-as-sections), it is additive, and removing it would change every brief
    # this seam has ever produced. Retiring it is its own decision, not a side
    # effect of this one.
    hint = derive_report_hint(intake, question_count=len(ordered))
    sections += ["", hint]

    # 5) Context section (quick task 260721-twy): fold the FULL context pack into
    # the brief verbatim under a labeled header — no truncation, no clarification
    # framing. The engine's intake stage is a delegator that always produces a
    # research plan, so it consumes this context to write self-contained research
    # assignments rather than re-judging the brief as vague. When no context pack
    # is supplied, fall back to a compact entity-bits line under the SAME header.
    context_section = (context_pack_text or "").strip()
    if not context_section:
        answers = _answers_map(intake)
        entity_bits = [
            _project_title(intake),
            _first_nonempty(answers, _SECTOR_FIELD_KEYS) or "",
            _first_nonempty(answers, _GOALS_FIELD_KEYS) or "",
        ]
        context_section = " — ".join(b for b in entity_bits if b)

    if context_section:
        sections += ["", _CONTEXT_PACK_HEADER, context_section]

    return "\n".join(sections)


def _ordered_questions(questions: Any) -> list[Any]:
    """Return the questions sorted by ascending ``priority`` (default 1 when absent)."""
    items = list(questions or [])

    def _priority(q: Any) -> int:
        value = getattr(q, "priority", None)
        if value is None and isinstance(q, dict):
            value = q.get("priority")
        try:
            return int(value) if value is not None else 1
        except (TypeError, ValueError):
            return 1

    return sorted(items, key=_priority)


def _project_title(intake: Any) -> str:
    """Best-effort display title for the fallback opening line (never blank)."""
    for attr in ("project_title", "client_name"):
        value = getattr(intake, attr, None)
        if value is None and isinstance(intake, dict):
            value = intake.get(attr)
        if value:
            text = str(value).strip()
            if text:
                return text
    return "dit intake"
