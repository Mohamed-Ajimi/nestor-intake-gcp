"""The DISCOVERY BRACKET — the engine's right to ask a question the client did not.

WHY THIS MODULE EXISTS. On run V-01 the orientation pass produced `brief_conflicts`
— the places where the brief's assumption disagreed with a page the engine had
actually read — and **not one of them ever reached a report or a research call**.
The producer (`workshop._parse_orientation`) and the consumer
(`synthesis/steps.py`) were both tested, against different hand-made fixtures, and
nobody drove the hand-off. This module is the hand-off: a sourced conflict becomes
a bounded, parented, traceable research question, and an unsourced one becomes
nothing at all.

WHAT IS AND IS NOT IN SCOPE (D-W3-4). Discovery fires off the **orientation** pass,
BEFORE research, which is the only reason it can spend a slot *this* run. Richer
discoveries surface from the research text itself, but by then the money is already
spent — those are "questions for the next run", reported and never researched, and
they are explicitly NOT built here.

THE ALLOCATION IS A GLOBAL POOL WITH A PER-PARENT CAP. **It is not a per-question
quota, and a future reader will reach for a quota — do not.** On V-01 *both*
`brief_conflicts` were about Q1 and none were about the coffee question. A
per-question quota would have obliged the engine to **MANUFACTURE** a coffee
discovery question to fill coffee's slot. **A quota forces invention**, which is
exactly the free invention the operator ruled out. The per-parent cap exists for
the opposite failure: discovery volume partly tracks research volume (Q1 had 8
reports, coffee 3), so a pure global pool quietly rewards the question that was
already best funded.

THE RULES, ALL OF THEM ENFORCED HERE IN PYTHON:

  * **NO SOURCE, NO SLOT.** A conflict without a fetched http(s) URL is dropped,
    counted, and named in a note. Never researched.
  * **At most 5 slots globally, at most 3 per parent**, both env-lowerable, and
    **no floor and no padding** — zero candidates means zero questions.
  * **Unused slots roll back to the MANDATE** (more depth on the client's own
    questions) and **never into more discovery**. Discovery can never borrow from
    the mandate; the mandate can never be displaced.
  * **`parent` is stamped in Python**, from a match against the caller's client
    question labels, never read out of model output. A model that could name its
    own parent could make a discovered question count as covering a client
    question it does not answer.
  * **Cross-cutting discoveries carry the explicit parent `__discovery__`**, which
    the coverage assertion knows to IGNORE. Without an explicit value the guard
    would either reject the question or, worse, silently count it as covering a
    client question.

D-W3-5 — MANDATE STRICT, DISCOVERY RIDES ALONG. A discovery question parented to a
client question label is a **RIDER**: it travels inside that label's mandate group,
where its shared groundwork already is, and costs no extra provider call. Only a
**cross-cutting** question earns a group of its own. `partition_discovery` is that
whole ruling in one function. The accepted consequence is that a rider's claims
file under their **host** question's facet — the facet-resolution seam in
`claim_attribution` resolves a member back to its host, and `__discovery__` is not
a client question, so no client question can read `0` in `claims_per_facet` because
of a discovery rider.

PROVENANCE IS A REQUIREMENT, NOT A COURTESY. D5 / D-01 makes the workshop FULLY
AUTOMATIC — nothing in it pauses for an operator — so a discovered question cannot
be gated on a click. Instead every dispatched question carries the quote and the
URL that provoked it into the report section that already exists,
`"### Where the brief did not match what the research found"`, via the
`researched_as` key `annotate_conflicts` writes. That is also the **Art. 12 audit
trail, deadline 2026-08-02**.

EVERY FUNCTION HERE IS PURE AND NEVER RAISES. No LLM call, no database, no clock,
no network, no file I/O. That is deliberate: it is what makes the whole bracket
drivable in a plain interpreter and replayable byte-for-byte.

NOTE ON THE IMPORT BLOCK. There is intentionally **no**
`from __future__ import annotations` here. The three runtime imports below
(`logging`, `os`, `typing`) are the entire surface, asserted as such by this plan's
verification, and the builtin generics used in the annotations
(`list[dict]`, `dict[str, int]`, `tuple[...]`) need no future import on the gate's
Python 3.11. Please do not add one.
"""

import logging
import os
from typing import Any, Optional

log = logging.getLogger(__name__)

__all__ = [
    "DISCOVERY_PARENT",
    "allocate_discovery",
    "annotate_conflicts",
    "discovery_question_text",
    "partition_discovery",
]

# The GLOBAL ceiling on discovered questions for one run. Five, because D-W3-4
# fixed it there: discovery is a bracket beside the mandate, not a second mandate.
# `max(0, ...)` so an operator can switch discovery off entirely with a 0 — there
# is no code path that needs at least one discovered question to exist.
#
# The bare `int(os.environ.get(...))` follows the house pattern of every `_D6_*` /
# `_D7_*` constant in `research_division.py`. A malformed value therefore raises at
# IMPORT time, loudly, rather than being silently coerced to a default nobody
# chose. The never-raises guarantee below is about the FUNCTIONS.
_DISCOVERY_MAX_SLOTS = max(0, int(os.environ.get("NESTOR_TRIBUNAL_DISCOVERY_SLOTS", "5")))

# The per-parent cap: at most this many of the global slots may come from any one
# parent, INCLUDING the `__discovery__` sentinel. Three, per D-W3-4.
#
# THE ACCEPTED RISK, STATED. At 3 of 5 slots, discovery can be 60% dominated by the
# single best-funded client question. The operator chose the looser cap over 2
# deliberately, because the best-funded question is also where the evidence
# genuinely concentrates. That is why `allocate_discovery` RETURNS the per-parent
# distribution instead of merely enforcing it: the 15.8 measuring run must be able
# to show whether the risk bit, and a number nobody can read is not a control.
#
# `max(1, ...)` because a cap of 0 would silently disable discovery through the
# wrong dial — `NESTOR_TRIBUNAL_DISCOVERY_SLOTS=0` is the way to do that.
_DISCOVERY_PER_PARENT_CAP = max(1, int(os.environ.get("NESTOR_TRIBUNAL_DISCOVERY_PER_PARENT", "3")))

#: The explicit parent a CROSS-CUTTING discovery question carries — a finding like
#: "two chains bought 300 Benelux sites in 2025" bears on pricing *and* coffee
#: *and* convenience, so it belongs to no single client question.
#:
#: The coverage assertion IGNORES this value. That is the whole point of it being
#: explicit: with no parent at all the scope guard would either reject the question
#: outright or, far worse, count it as covering a client question it does not
#: answer, letting the client's own question go unresearched while a question the
#: evidence raised stood in for it.
#:
#: It is also why `research_division._angle`'s existing orphan rule is left alone:
#: an unknown parent already resolves to `labels[0]`, so `__discovery__` can never
#: become a `focus_area`. Do NOT add a second rule for this sentinel.
DISCOVERY_PARENT = "__discovery__"

# The per-field bound inside the question frame. Model-authored text that reaches
# three third-party research providers verbatim is bounded as a PROMPT-INJECTION
# CONTROL, not as formatting (T-15.2-60) — injected prose that cannot grow cannot
# restructure the assignment around it.
#
# 600 deliberately matches `research_division._SUBQ_CHARS`, and is DUPLICATED here
# rather than imported: a sibling plan is editing that module in this same phase,
# and an import would couple two parallel worktrees for the sake of one integer.
# If the two ever need to move together, move them together on purpose.
_DISCOVERY_TEXT_CHARS = 600

# How many individual drop/cap notes `allocate_discovery` will name before it stops
# naming them and emits one aggregate note instead. A note per conflict on a brief
# with fifty unsourced flags is a log flood, and a flood is how the V-01 losses
# stayed invisible. The aggregate line still carries the total, so the count is
# never lost — only the enumeration is.
_DISCOVERY_MAX_NOTES = 10


def _text(value: Any) -> str:
    """`value` as a plain stripped string. NEVER RAISES — a hostile `__str__` is
    not an error, it is untrusted input, and it becomes the empty string."""
    if isinstance(value, str):
        return value.strip()
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:  # noqa: BLE001 — an unprintable value is empty, never a crash
        return ""


def _norm(value: Any) -> str:
    """`value` collapsed to single spaces and truncated to `_DISCOVERY_TEXT_CHARS`.

    Collapsing is what stops a newline in model output from restructuring the
    question frame; truncation is the T-15.2-60 bound. NEVER RAISES.
    """
    return " ".join(_text(value).split())[:_DISCOVERY_TEXT_CHARS]


def _conflict_key(item: Any) -> tuple[str, str, str]:
    """The identity of a conflict: `(question, assumption, world_says)`.

    The SAME helper is used on both sides of `annotate_conflicts` — over the
    incoming `brief_conflicts` entry and over the dispatched question's
    `provenance` — so a match is exact BY CONSTRUCTION rather than by two
    normalisations that happen to agree today. `source_url` is deliberately not
    part of the key: it mirrors `workshop._collect_conflicts`, whose de-duplication
    key is these same three fields, so two conflicts this module considers
    identical are exactly the two that module already collapsed to one.
    """
    if not isinstance(item, dict):
        return ("", "", "")
    return (_text(item.get("question")), _norm(item.get("assumption")), _norm(item.get("world_says")))


def discovery_question_text(conflict: Any) -> str:
    """Compose ONE research question from one brief-vs-world conflict. PURE.

    Returns `""` for anything that is not a usable conflict — a missing half is not
    a conflict, and an empty string is dropped by `_normalise_winners` downstream,
    so an unusable conflict cannot become a paid call by accident.

    THREE THINGS A FUTURE READER WILL WANT TO CHANGE, AND WHY THEY ARE THIS WAY:

    1. **The frame is ENGLISH inside a Dutch run, deliberately.**
       `research_division._angle_query`'s own framing sentences already are, and
       `_d7_language_sentence` is the one thing that sets the report language,
       always emitted LAST. A second language mechanism in here would be a second
       source of truth for the one property the client actually sees.

    2. **NO LLM PHRASES THIS QUESTION.** A model asked to phrase a discovered
       question is a model that can *invent* one. The fixed frame is what makes
       "no invention" mechanical instead of a sentence in a prompt — and a prompt
       sentence is not a control, which the module that owns the scope rule already
       says in as many words.

    3. **The URL is included in the question text** because the client will see it
       in the report anyway, and because it has already been allowlisted to
       http(s) upstream in `workshop._parse_orientation` before it can get here.

    The two model-authored fields are collapsed to single spaces and truncated to
    `_DISCOVERY_TEXT_CHARS` **each, separately** — separately, so a 5,000-character
    `assumption` cannot consume the budget that would otherwise have carried the
    `world_says` half that contradicts it. The frame's own closing instruction is
    emitted AFTER both of them, and `_angle_query` still appends its
    ignore-instructions line and the language paragraph after that.
    """
    try:
        assumption = _norm(conflict.get("assumption") if isinstance(conflict, dict) else None)
        world_says = _norm(conflict.get("world_says") if isinstance(conflict, dict) else None)
        if not assumption or not world_says:
            return ""
        url = _text(conflict.get("source_url")) if isinstance(conflict, dict) else ""
        cited = f" ({url})" if url.lower().startswith(("http://", "https://")) else ""
        return (
            f"The brief assumes: {assumption}. "
            f"A source read during orientation says instead: {world_says}{cited}. "
            "Establish which of the two holds, how far it holds, and what follows "
            "from it for this client."
        )
    except Exception as exc:  # noqa: BLE001 — the frame never raises
        log.warning("discovery_bracket: could not frame a discovery question: %r", exc)
        return ""


def _client_labels(client_questions: Any) -> list[str]:
    """The client question labels, in order, tolerantly. NEVER RAISES.

    Accepts a sequence of label strings or of question dicts carrying `label` —
    both shapes are live in this pipeline. An entry that yields no label is
    skipped rather than becoming an empty-string label, because `""` would then
    match every conflict whose origin label failed to read.
    """
    out: list[str] = []
    try:
        entries = list(client_questions or [])
    except Exception:  # noqa: BLE001 — a non-iterable is simply no labels
        return out
    for entry in entries:
        label = _text(entry.get("label")) if isinstance(entry, dict) else _text(entry)
        if label and label not in out:
            out.append(label)
    return out


def allocate_discovery(
    brief_conflicts: Any,
    client_questions: Any,
    *,
    slots: Optional[int] = None,
    per_parent_cap: Optional[int] = None,
) -> tuple[list[dict[str, Any]], dict[str, int], list[str]]:
    """Turn sourced brief-vs-world conflicts into research questions. PURE, NEVER RAISES.

    Returns `(questions, per_parent_counts, notes)`.

    THE RULES, IN THE ORDER THEY ARE APPLIED:

    1. `slots` and `per_parent_cap` default to `_DISCOVERY_MAX_SLOTS` /
       `_DISCOVERY_PER_PARENT_CAP`. `slots <= 0` returns `([], {}, [])` — discovery
       switched off is not a degradation and produces no note.
    2. **NO SOURCE, NO SLOT.** A conflict is a candidate only when its `assumption`
       and `world_says` are both non-empty AND its `source_url` starts with
       `http://` or `https://`. Anything else is DROPPED, COUNTED, and NAMED in a
       note. Dropping it silently would hide the one thing this rule exists to
       enforce — and silence around dropped material is precisely how V-01 lost 278
       claims without anyone noticing.
    3. **PARENT IS STAMPED HERE.** `conflict["question"]` when that exact string is
       one of `client_questions`, else `DISCOVERY_PARENT`. It is never read from
       anywhere else, and never from model output: `workshop._parse_orientation`
       already stamps `question` from the CALLER's label for the same reason.
    4. **ORDER IS INPUT ORDER** — orientation order, which is client-question
       order, preserved by `workshop._collect_conflicts`. Deterministic and
       replayable. Do NOT sort and do NOT rank by anything: any ranking here would
       be a second, unvalidated judgement about what matters, competing with the
       tournament that already made one.
    5. Deduped on `(parent, assumption, world_says)` in case the caller did not.
    6. **THE PER-PARENT CAP APPLIES TO EVERY PARENT VALUE, INCLUDING
       `DISCOVERY_PARENT`.** One rule, no exemption. A flood of cross-cutting
       conflicts would otherwise take all five slots and leave the parented ones —
       the ones with a client question to attach to — with none.
    7. **STOP AT `slots`. THERE IS NO FLOOR AND NO PADDING.** Zero candidates
       returns zero questions. **Unused slots roll back to the MANDATE**, which the
       caller effects simply by keeping its full group ceiling — they NEVER roll
       into more discovery, and nothing in here may invent a question to reach a
       number.

    WHY `rank` IS `0` AND THE CALLER MUST STAMP IT. `rank` drives stakes through
    `research_division._stakes_for_rank`, and a discovered question must rank BELOW
    every client winner: the mandate can never be displaced by a question the
    client did not ask. `0` is deliberately an INVALID rank, so it is a loud
    placeholder rather than a plausible one. Note the downstream consequence:
    `research_division._normalise_winners` coerces any rank below 1 to the entry's
    1-based LIST POSITION, so leaving `0` in place is safe only if the caller
    appends discovery AFTER every mandate winner. Stamping it explicitly is the
    supported path; relying on list position is not.

    `per_parent_counts` is a plain `dict[str, int]` in allocation order, returned so
    the caller can log the distribution D-W3-4 requires be visible.
    """
    questions: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    notes: list[str] = []

    try:
        limit = _DISCOVERY_MAX_SLOTS if slots is None else int(slots)
    except Exception:  # noqa: BLE001 — a garbled dial falls back to the default
        limit = _DISCOVERY_MAX_SLOTS
    try:
        cap = _DISCOVERY_PER_PARENT_CAP if per_parent_cap is None else int(per_parent_cap)
    except Exception:  # noqa: BLE001 — same
        cap = _DISCOVERY_PER_PARENT_CAP
    if cap < 1:
        # Mirrors `max(1, ...)` on the constant: switching discovery off goes
        # through `slots`, not through a zero cap on every parent.
        cap = 1
    if limit <= 0:
        return ([], {}, [])

    labels = _client_labels(client_questions)

    def _note(text: str) -> None:
        if len(notes) < _DISCOVERY_MAX_NOTES:
            notes.append(text)

    try:
        entries = list(brief_conflicts or [])
    except Exception:  # noqa: BLE001 — a non-iterable is simply no conflicts
        entries = []

    seen: set[tuple[str, str, str]] = set()
    unsourced = 0
    capped = 0

    for entry in entries:
        if len(questions) >= limit:
            # Rule 7. Everything after the ceiling is untouched, not examined.
            break
        if not isinstance(entry, dict):
            unsourced += 1
            _note(
                "discovery: a brief-vs-world entry was not an object and could not "
                "become a research question."
            )
            continue

        origin = _text(entry.get("question"))
        assumption = _norm(entry.get("assumption"))
        world_says = _norm(entry.get("world_says"))
        url = _text(entry.get("source_url"))

        # Rule 2 — NO SOURCE, NO SLOT. Re-checked here even though
        # `workshop._parse_orientation` already allowlists the scheme: this is THIS
        # module's rule, and a rule that depends on a caller keeping its promise is
        # not a rule (T-15.6-06).
        if not assumption or not world_says or not url.lower().startswith(("http://", "https://")):
            unsourced += 1
            _note(
                "discovery: dropped a brief-vs-world flag on "
                f"'{(origin or 'an unnamed question')[:80]}' because it carries no "
                "fetched http(s) source — no source, no slot."
            )
            continue

        # Rule 3 — the parent is stamped, never read.
        parent = origin if origin in labels else DISCOVERY_PARENT

        # Rule 5.
        key = (parent, assumption, world_says)
        if key in seen:
            continue
        seen.add(key)

        # Rule 6 — the cap binds the sentinel exactly as it binds a client label.
        if counts.get(parent, 0) >= cap:
            capped += 1
            _note(
                f"discovery: '{parent[:80]}' already holds its maximum of {cap} "
                "discovered question(s); a further candidate from it was not "
                "researched."
            )
            continue

        text = discovery_question_text(entry)
        if not text:
            # Unreachable given the guards above; kept because an empty text would
            # be dropped silently by `_normalise_winners` further downstream, and a
            # silent drop there is indistinguishable from "no conflict was found".
            unsourced += 1
            _note("discovery: a sourced flag could not be framed as a question and was dropped.")
            continue

        counts[parent] = counts.get(parent, 0) + 1
        questions.append(
            {
                "text": text,
                "parent": parent,
                "parents": [parent],
                # Deliberately invalid — the CALLER stamps this after the mandate
                # winners. See the docstring.
                "rank": 0,
                "langs": [],
                "source": "discovery",
                "scope_injected": False,
                "bracket": "discovery",
                # T-15.6-10, and the Art. 12 audit trail: the origin label, the
                # quote on both sides, and the URL, so a dispatched question can be
                # traced back to what provoked it. Bounded on the two model-authored
                # fields; `question` is verbatim because it is engine-stamped from
                # the caller's label, not model output.
                "provenance": {
                    "question": origin,
                    "assumption": assumption,
                    "world_says": world_says,
                    "source_url": url,
                },
            }
        )

    if unsourced:
        notes.append(
            f"discovery: {unsourced} brief-vs-world flag(s) carried no fetched "
            "http(s) source and were reported without being researched."
        )
    if capped:
        notes.append(
            f"discovery: {capped} further candidate(s) exceeded the per-parent cap "
            f"of {cap} and were not researched."
        )
    if questions:
        log.info(
            "discovery_bracket: %d discovered question(s) of at most %d slot(s); "
            "per-parent distribution %r (cap %d) — unused slots roll back to the mandate",
            len(questions), limit, counts, cap,
        )
    return (questions, counts, notes)


def partition_discovery(questions: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split allocated discovery questions into `(riders, cross_cutting)`. PURE, NEVER RAISES.

    **This is D-W3-5's whole shape in one function.** A **RIDER** is a question
    whose `parent` is a client question label: it travels INSIDE that label's
    mandate group, where the shared groundwork it needs has already been searched,
    and it therefore costs **no extra provider call at all**. A **CROSS-CUTTING**
    question is one carrying `DISCOVERY_PARENT`, and only those earn a group.

    THE ARITHMETIC THAT MADE THIS THE CHEAPEST OPTION. Groups are capped at 5 and
    each group goes to all three providers, so the happy-path ceiling is 15 paid
    calls. If there is **no** cross-cutting question then **there is no discovery
    group and discovery consumes no group slot whatsoever** — which is why V-01's
    three client questions land at **9–12 calls, not 15**: both of its conflicts
    were parented to Q1, so both are riders, so discovery is free. Against V-01's
    actual 19 calls that is the saving, and it is the reason this ruling exists.

    Order is preserved inside each half, so `allocate_discovery`'s allocation order
    still governs which question the caller drops first if it has to drop one.

    A question with a BLANK or missing parent is treated as CROSS-CUTTING, not as a
    rider. A rider with no named host would be attached to whichever mandate group
    the caller happened to reach for, and its claims would then file under that
    client question's facet — an arbitrary client question absorbing a finding that
    is not about it. Earning its own group is the safe failure. `allocate_discovery`
    cannot produce this shape; a hand-built or resumed list can.
    """
    riders: list[dict[str, Any]] = []
    cross_cutting: list[dict[str, Any]] = []
    try:
        entries = list(questions or [])
    except Exception:  # noqa: BLE001 — a non-iterable partitions to two empties
        return (riders, cross_cutting)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        parent = _text(entry.get("parent"))
        if not parent or parent == DISCOVERY_PARENT:
            cross_cutting.append(entry)
        else:
            riders.append(entry)
    return (riders, cross_cutting)


def annotate_conflicts(brief_conflicts: Any, questions: Any) -> list[Any]:
    """Carry `researched_as` back onto the conflicts that were actually researched.

    PURE, NEVER RAISES. Returns a **NEW list of the SAME LENGTH AND ORDER** as
    `brief_conflicts`, in which every entry whose `(question, assumption,
    world_says)` matches a dispatched discovery question gains a `"researched_as"`
    key holding that question's text. Entries are COPIED; the input dicts are never
    mutated in place, because `brief_conflicts` is also the payload the report
    section renders and a caller that re-renders it must see what it passed in.

    **`questions` IS THE SET THAT WAS ACTUALLY DISPATCHED — not everything
    `allocate_discovery` returned.** A rider shed when its host mandate group could
    not take it, or a cross-cutting question that never got a group, must NOT be
    annotated. It still reaches the client: with no `researched_as` key it renders
    as a plain brief-vs-world conflict, which is the honest statement — the evidence
    raised it and this run did not research it. Annotating it anyway would tell the
    client a question was researched when no provider was ever asked.

    **ANNOTATE, NEVER APPEND.** Appending a second row for a researched conflict
    would print the same conflict twice in
    `"### Where the brief did not match what the research found"` — once with the
    clause and once without — and a client reading it twice cannot tell which
    reading is the true one.

    Non-dict entries pass through unchanged, by identity, so the length-and-order
    guarantee holds for the string form of a conflict that `steps.py` also accepts.
    """
    dispatched: dict[tuple[str, str, str], str] = {}
    try:
        allocated = list(questions or [])
    except Exception:  # noqa: BLE001 — a non-iterable dispatched nothing
        allocated = []
    for entry in allocated:
        if not isinstance(entry, dict):
            continue
        provenance = entry.get("provenance")
        if not isinstance(provenance, dict):
            continue
        text = _text(entry.get("text"))
        if not text:
            continue
        key = _conflict_key(provenance)
        if key == ("", "", "") or key in dispatched:
            # FIRST WINS, matching `_dedupe_claims`' rule: two questions framed from
            # one conflict is a caller defect, and silently taking the second would
            # make the report's clause depend on list order.
            continue
        dispatched[key] = text

    out: list[Any] = []
    try:
        entries = list(brief_conflicts or [])
    except Exception:  # noqa: BLE001 — a non-iterable annotates to an empty list
        return out
    annotated = 0
    for entry in entries:
        if not isinstance(entry, dict):
            out.append(entry)
            continue
        copy = dict(entry)
        researched = dispatched.get(_conflict_key(entry))
        if researched:
            copy["researched_as"] = researched
            annotated += 1
        out.append(copy)
    if entries:
        log.info(
            "discovery_bracket: %d of %d brief-vs-world flag(s) were dispatched as "
            "discovery questions and carry their provenance into the report",
            annotated, len(entries),
        )
    return out
