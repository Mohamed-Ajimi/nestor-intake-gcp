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


def _first_nonempty(answers: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    """Return the first non-empty answer value whose key matches (case-insensitive)."""
    lowered = {k.lower(): v for k, v in answers.items()}
    for key in keys:
        value = lowered.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


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


def assemble_brief(intake: Any, decomposition: Any, questions: Any) -> str:
    """Compose the Tribunal run brief from the validated context pack (SEAM-04).

    Structure (the composition-gate-safe shape):

    1. an opening line — the decomposition ``summary`` when present, else a
       deterministic ``"Deep research for {project_title}."`` fallback (never
       blank);
    2. an ``Onderzoeksvragen:`` header followed by the research questions
       ENUMERATED in ascending ``priority`` order (``1. ...`` / ``2. ...``);
    3. the :func:`derive_report_hint` PROSE tail.

    The returned brief NEVER contains :data:`INTERACTIVE_REPORT_MARKER` — the seam
    run cannot opt into the interactive-report pause gate (D-01b). Enumerating the
    concrete questions keeps the brief non-vague so the composition pause gate does
    not fire either (T-16-04).
    """
    # 1) Opening line — summary or a deterministic project-title fallback.
    summary = getattr(decomposition, "summary", None)
    if summary is None and isinstance(decomposition, dict):
        summary = decomposition.get("summary")
    opening = (summary or "").strip()
    if not opening:
        project_title = _project_title(intake)
        opening = f"Deep research for {project_title}."

    # 2) Enumerated questions in ascending priority order.
    ordered = _ordered_questions(questions)
    question_lines = ["Onderzoeksvragen:"]
    for index, q in enumerate(ordered, start=1):
        text = getattr(q, "question_text", None)
        if text is None and isinstance(q, dict):
            text = q.get("question_text")
        question_lines.append(f"{index}. {(text or '').strip()}")

    # 3) Report-spec hint prose (never the marker).
    hint = derive_report_hint(intake, question_count=len(ordered))

    return "\n".join([opening, "", *question_lines, "", hint])


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
