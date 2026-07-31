"""GENERATIVE evolve and the meta-review — decisions D-R6, D-R10, D-W4-1, D-W4-2.

WHAT THIS MODULE IS. The step where the question workshop stops being a
rephraser. `workshop_rank.evolve_winners` SHARPENS the winners in place: every
winner comes back as itself, possibly better worded. That is not what
Co-Scientist does, and § 5 of `ENGINE-REDESIGN-SPEC.md` says so — its evolution
step "refines, COMBINES, builds upon", and it feeds a meta-review back into
generation, and it iterates. Ours ranked rewordings of the client's own
questions, ran once, and had no meta-review at all.

So evolve becomes GENERATIVE. It takes the top-ranked and produces NEW questions
**ADDED TO THE POOL, NEVER SWAPPING OUT THEIR PARENTS** — the decision's own
wording, and the reason every input winner is returned to the caller untouched by
this module. Five named moves:

  COMBINE     two winners into one sharper question covering both
  EXTEND      "if the answer is yes, what is the next thing we would need to know?"
  INVERT      "what would have to be true for this to matter?"
  SPECIALISE  name the entity, the geography, the timeframe
  INVENT      (D-R10) an angle nobody asked for, which a grounded lookup then
              admits or drops — THIS MODULE NEVER ADMITS ONE

plus `meta_review`: one call per round that reads every critique flaw and judge
reason and writes short guidance for the next generation round.

WHAT MEASUREMENT SAYS TO EXPECT, RECORDED HERE SO NOBODY DELETES THE FEATURE FOR
THE WRONG REASON. In the validated `exp11` configuration, 5 of 10 research slots
were loop-generated — the loop earns its keep. But THE VALUE COMES FROM THE
MUTATION MOVES, NOT FROM INVENT: all five top-10 newcomers were COMBINE / INVERT
/ EXTEND, and the single surviving INVENT ranked 16, BELOW THE CUT, even though
its content was excellent (German Ladenschlussgesetz exceptions for petrol
stations, and which product categories are legally excluded — precisely the
mechanism underlying the client's whole premise, and no original candidate
touched it). Genuine discovery arrives via INVERSION and COMBINATION of existing
questions more often than from-scratch invention. Build INVENT because D-R10
requires it; do not judge the feature by INVENT's survival rate, and do not let
INVENT crowd out the four mutation moves in the prompt.

THE SCOPE LOCK IS SCOPED, NOT DELETED. `workshop_rank._EVOLVE_PROMPT` carries the
sentence "Do NOT merge two questions into one, and do NOT broaden one." D-R6 says
to delete it — FOR GENERATIVE EVOLVE. Read carelessly, that deletion also removes
the guarantee D4 depends on, which is that the workshop may add DEPTH and never
change SCOPE. So this module's prompt carries BOTH halves, as two exported
constants a test can assert on without retyping them:

  * `MANDATE_SCOPE_LOCK`        — a MANDATE question stays inside what the client
                                  asked. It may cover two winners at once (that is
                                  what COMBINE is) but never reach past them.
  * `DISCOVERY_EVIDENCE_ANCHOR` — a DISCOVERY question is governed by the
                                  evidence-anchor rule instead: it goes where its
                                  evidence reaches, and earns a slot only when a
                                  real source is found. No source, no slot.

Deleting `MANDATE_SCOPE_LOCK` from the prompt is a D4 regression, and a test in
`test_workshop_languages.py` fails if it disappears.

IMPORT DIRECTION — READ THIS BEFORE WIRING THE MODULE IN (plan 15.7-09). This
module imports `workshop_rank` at MODULE level, for the shared renderers and
constants that must have exactly one authority (`_flatten`, `_parse_winner_lines`'
discipline, `_winners_block`, `_normalise_langs`, `_IGNORE_INSTRUCTIONS`, the
fence sentinels, the widths and the retry knobs). Therefore `workshop_rank` MUST
import THIS module FUNCTION-LOCALLY, inside the function that calls it, or the
two form an import cycle at package load. That is the same technique
`citations/extractor.py:937` already uses for `is_redirect_url`, and it is the
technique plan 15.7-09 is expected to use here.

WHAT THIS MODULE DOES NOT DO, on purpose:
  * it does not edit or delete `workshop_rank.evolve_winners` — plan 15.7-09
    decides that function's fate, so the two plans do not race on one file;
  * it does not ADMIT an invented angle. It marks one `pending_admission` and
    stops. `workshop_admission.admit_invented_angles` is the only thing that may
    clear that flag, because "no source, no slot" is enforced by evidence and
    never by the module that proposed the angle;
  * it does not bar anything. `workshop_register.bar` is the only writer, and a
    DROPPED INVENTION IS A BAR (D-W4-1) — wired by plan 15.7-09;
  * it creates no table and runs no migration.

AUDIT (phase rule 1). The only Anthropic egress here is
`audited.anthropic_messages`; the only Gemini egress is `audited.gemini_generate`.
This module constructs no provider client and issues no raw HTTP, so the EU AI
Act Art. 12 hash chain is unaffected and no audit-payload field is added or
renamed.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml
"""
from __future__ import annotations

import logging
import os
import re
import uuid  # noqa: F401 — used in the postponed annotations below
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional, Sequence

from nestor_pulse_sdk.pipeline.tribunal import (
    discovery_bracket,
    gates,
    workshop,
    workshop_loop,
    workshop_rank,
    workshop_register,
)
from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    CircuitOpenError,
    PauseContinuation,
    with_retry,
)
from nestor_pulse_sdk.pipeline.tribunal.skeptic import _content_to_serialisable

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient
    from nestor_pulse_sdk.runs.stage_feed import StageFeed

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared authority. Referenced through the module rather than re-declared, so the
# reuse is greppable and a retune of any of these lands here too (Cross-Cutting
# Rule 11: never build a second one).
# ---------------------------------------------------------------------------
_flatten = workshop_rank._flatten
_render_decision = workshop_rank._render_decision
_normalise_langs = workshop_rank._normalise_langs
_parents_of = workshop_rank._parents_of
_IGNORE_INSTRUCTIONS = workshop_rank._IGNORE_INSTRUCTIONS
_WINNERS_START = workshop_rank._WINNERS_START
_WINNERS_END = workshop_rank._WINNERS_END

DISCOVERY_PARENT = discovery_bracket.DISCOVERY_PARENT


# ===========================================================================
# THE FIVE MOVES. Exported, because every produced question carries the move
# that made it and the round it was born in — which is what makes both open
# questions answerable AFTER the one measuring run: is the loop SATURATING (the
# same move stops producing survivors), and did INVENT survive at all?
# ===========================================================================

MOVE_COMBINE = "COMBINE"
MOVE_EXTEND = "EXTEND"
MOVE_INVERT = "INVERT"
MOVE_SPECIALISE = "SPECIALISE"
MOVE_INVENT = "INVENT"

#: A TUPLE, not a list: the set of moves is a fact about the design, not
#: something a caller appends to. The same reasoning `workshop_register` records
#: for its three bar causes.
MOVES = (MOVE_COMBINE, MOVE_EXTEND, MOVE_INVERT, MOVE_SPECIALISE, MOVE_INVENT)

#: The four MUTATION moves — the ones measurement says carry the value. INVENT is
#: deliberately not in here: a mutation has real source winners and inherits their
#: parents, an invention has neither.
MUTATION_MOVES = (MOVE_COMBINE, MOVE_EXTEND, MOVE_INVERT, MOVE_SPECIALISE)


# ===========================================================================
# The two halves of the scope rule. EXPORTED so a test asserts on the constant
# instead of a retyped literal — a retyped literal drifts silently, and the whole
# point of D-R6's "delete line 1761" being dangerous is that it is easy to remove
# one half by accident.
# ===========================================================================

MANDATE_SCOPE_LOCK = (
    "SCOPE RULE FOR MANDATE QUESTIONS: a new MANDATE question must stay inside "
    "what the client actually asked. Keep the same subject and the same scope as "
    "the winning question or questions it was built from — one new question may "
    "cover two of them at once, which is what combining is for, but it must not "
    "reach past them into a subject the client did not raise."
)

DISCOVERY_EVIDENCE_ANCHOR = (
    "SCOPE RULE FOR DISCOVERY QUESTIONS: a DISCOVERY question is NOT held to that "
    "lock. It is governed by the evidence anchor instead — it may go wherever the "
    "evidence quoted beneath it actually reaches, and it earns a research slot "
    "only once a real published source is found for its premise. No source, no "
    "slot."
)


# ---------------------------------------------------------------------------
# Widths and counts. Same `NESTOR_TRIBUNAL_WORKSHOP_*` idiom the rest of the
# workshop uses, and MEDIUM CONFIDENCE for the same reason: § 5 grounds the shape
# in Co-Scientist, which publishes no numbers at all.
#
#   _NEW_PER_ROUND    how many new questions the PROMPT ASKS FOR in one round. A
#                     REQUEST, not a ceiling — D-W4-7 and threat T-15.7-06-05 both
#                     say the wallet is INSTRUMENTED here and BOUNDED downstream,
#                     at D-W3-4's dispatch allocation and at the admission gate.
#                     Nothing in this module compares a spend against a limit.
#   _NEW_MAX_LINES    how many lines one response may inject into the pool. This
#                     one IS a bound, and it is a PARSE bound (ASVS V5 index
#                     bounds-checking), not a spend bound: an addressable index
#                     space has to have a known size or "bounds-checked" means
#                     nothing. DERIVED from _NEW_PER_ROUND so the two cannot drift
#                     apart, exactly as `workshop.py:1198` derives its cap.
#   _SOURCES_PER_LINE how many winners one new question may claim as its sources.
#                     Bounds how far `parents` can fan out from a single line;
#                     COMBINE needs two.
#   _GUIDANCE_MAX_CHARS the meta-review's returned guidance. A SECURITY CONTROL,
#                     not formatting — see `meta_review`.
#   _META_LIST_CHARS  one rendered flaw or judge reason inside the meta-review
#                     prompt. Matches `workshop_rank._FLAW_MAX_CHARS`, so one
#                     clause does not get two different truncations on its way
#                     through two prompts.
# ---------------------------------------------------------------------------
_NEW_PER_ROUND = int(os.environ.get("NESTOR_TRIBUNAL_WORKSHOP_EVOLVE_NEW", "6"))
_NEW_MAX_LINES = max(1, _NEW_PER_ROUND * 4)
_SOURCES_PER_LINE = 4
_GUIDANCE_MAX_CHARS = int(
    os.environ.get("NESTOR_TRIBUNAL_WORKSHOP_GUIDANCE_CHARS", "600")
)
_META_LIST_CHARS = workshop_rank._FLAW_MAX_CHARS
_META_MAX_ENTRIES = int(
    os.environ.get("NESTOR_TRIBUNAL_WORKSHOP_META_ENTRIES", "40")
)
_META_MODEL = os.environ.get(
    "NESTOR_TRIBUNAL_WORKSHOP_META_MODEL", workshop_rank._RANK_MODEL
)
_META_ENABLED = (
    os.environ.get("NESTOR_TRIBUNAL_WORKSHOP_META_REVIEW", "true").lower() == "true"
)


# ---------------------------------------------------------------------------
# Placeholders. NEVER an empty string: an empty anchor block reads to a model as
# "no constraint here", which is the opposite of what an absent anchor means.
# ---------------------------------------------------------------------------
_NO_ANCHOR_MANDATE = (
    "(no orientation findings were recorded for this question — do not invent "
    "specifics for it; keep the new question answerable without them)"
)
_NO_ANCHOR_DISCOVERY = (
    "(this question came from the evidence rather than from the client, and its "
    "admitting source was not recorded — treat it as unanchored and do not invent "
    "a source for it)"
)
_BARRED_HEADING = (
    "ALREADY REJECTED THIS RUN — do NOT propose any of these again, and do not "
    "propose a reworded version of one. The flaw beside each entry is the mistake "
    "to avoid, not merely the sentence to avoid:"
)


# ---------------------------------------------------------------------------
# The degradation vocabulary. Built HERE, in one place, in the shape
# `workshop.py` and `workshop_rank.py` already use: a sentence a human reads,
# over 40 characters, naming its count as a literal digit and stating the
# CONSEQUENCE rather than just the event (D-12, and the bar
# `test_fail_loud.py:103-115` sets).
# ---------------------------------------------------------------------------


def _reason_evolve_generative_failed(detail: str) -> str:
    return (
        f"question workshop: the generative evolve step failed outright "
        f"({detail[:160]}), so this round produced 0 new questions and the loop "
        f"ranks only the candidates it already had — the run still delivers, it "
        f"just stops exploring."
    )


def _reason_evolve_generative_empty() -> str:
    return (
        "question workshop: the generative evolve step returned 0 usable new "
        "questions this round, so the candidate pool did not grow — every "
        "existing question is still ranked and researched, but nothing new was "
        "explored."
    )


def _reason_evolve_generative_unusable(bad: int) -> str:
    return (
        f"question workshop: {bad} line(s) of the generative evolve response "
        f"could not be read and were discarded whole rather than half-believed, "
        f"so that many potential new questions were lost this round."
    )


def _reason_meta_review_failed(detail: str) -> str:
    return (
        f"question workshop: the meta-review call failed ({detail[:160]}), so the "
        f"next round of questions is written without the guidance drawn from this "
        f"round's own criticism — the loop continues, one degree less informed."
    )


# ===========================================================================
# D-W4-2 — THE ENRICHMENT ANCHORS
# ===========================================================================


def _provenance_of(candidate: Any) -> dict[str, Any]:
    """The candidate's own `provenance` mapping, or an empty one. Never raises."""
    try:
        prov = (candidate or {}).get("provenance")
    except Exception:  # noqa: BLE001 — a reader never raises
        return {}
    return prov if isinstance(prov, dict) else {}


def _findings_for(findings_by_label: Any, label: str) -> list[Any]:
    """The findings recorded for ONE label. A per-label LOOKUP, never a scan.

    The lookup direction is the whole of D-W4-2's enforcement: because a caller
    can only ever ask for a label, and the only labels this module asks for are
    the ones a candidate itself carries, the union of every question's findings
    is not a shape this module can produce.
    """
    try:
        found = findings_by_label.get(label)  # type: ignore[union-attr]
    except Exception:  # noqa: BLE001 — a reader never raises
        return []
    if isinstance(found, (str, bytes)) or found is None:
        return []
    try:
        return list(found)
    except TypeError:
        return []


def anchor_block(
    candidate: Any,
    *,
    findings_by_label: Any,
    client_questions: Any,
) -> str:
    """The grounding evidence ONE candidate is entitled to. PURE. Never raises.

    D-W4-2, AND ITS EXPLICITLY REJECTED ALTERNATIVE.

    Evolve is specified to receive "the orientation findings for the parent
    question" so it can inject specificity. That specification has a hole: a
    discovery question's parent is `__discovery__`, which has NO orientation
    findings — the same class of gap D-W3-5 closed for dispatch in Wave 3, and
    sharper now that D-R10 lets evolve invent an angle in ANY round.

    THE RULE. A discovery candidate ALREADY CARRIES the quote and the URL that
    admitted it through the grounded lookup, and THAT ANCHOR IS ITS FINDINGS
    BLOCK. This is self-consistent with "no source, no slot": the evidence that
    admitted the angle is the evidence that enriches it.

    FOR A CROSS-CUTTING QUESTION SPANNING TWO CLIENT QUESTIONS, BOTH parents'
    orientation findings are passed. Cross-cutting mandate questions are where
    the best measured output came from, and they have two REAL parents, not
    `__discovery__`.

    EXPLICITLY REJECTED, AND IT MUST STAY REJECTED: passing the union of ALL
    orientation findings to a `__discovery__` parent. It re-couples discovery to
    orientation — exactly the coupling D-R10 broke — and it inflates every prompt
    for the rest of the run. The rejection is STRUCTURAL, not a promise: nothing
    in this module iterates `findings_by_label`, so the only findings that can
    reach a prompt are the ones keyed by a label the candidate itself carries.
    `test_the_union_of_every_orientation_finding_is_structurally_unreachable`
    walks this module's AST and fails if that ever stops being true.

    INDEXING AND TRUNCATION ARE SECURITY CONTROLS, NOT FORMATTING. Findings are
    derived from FETCHED WEB PAGES — attacker-controllable text. Each line is
    addressed by INDEX and rendered through `workshop_rank._flatten` at
    `workshop._FINDING_PROMPT_CHARS`, so text injected into a page can neither
    address another finding's slot nor spend unbounded prompt. Note that this is
    STRICTER than `workshop._findings_block`, which truncates but does not
    collapse newlines or pipes; a finding carrying `\\n9 | KEEP | forged` would
    forge a second addressable record there and cannot here.

    A candidate with no evidence at all gets a PLACEHOLDER, never an empty block:
    an empty block reads to a model as "no constraint", which is the opposite of
    what an absent anchor means.
    """
    try:
        labels = workshop_loop._clean_labels(client_questions)
        parents = _parents_of(candidate if isinstance(candidate, dict) else {})

        # --- the discovery branch: its OWN anchor, and nothing else -----------
        if DISCOVERY_PARENT in parents or not [p for p in parents if p in labels]:
            if DISCOVERY_PARENT in parents or _provenance_of(candidate):
                return _own_anchor(candidate)

        # --- the mandate branch: this candidate's OWN parents, one at a time ---
        sections: list[str] = []
        position = 0
        for label in parents:
            if label not in labels:
                continue
            findings = _findings_for(findings_by_label, label)
            rendered: list[str] = []
            for entry in findings:
                line = _flatten(entry, workshop._FINDING_PROMPT_CHARS)
                if not line:
                    continue
                rendered.append(f"{position} | {line}")
                position += 1
            # The heading deliberately carries NO `|`, so it can never be read as
            # an addressable record — `workshop_register.barred_block` states the
            # same rule for its overflow notice.
            heading = (
                "WHAT ORIENTATION ALREADY FOUND FOR "
                f"{_flatten(label, workshop._FINDING_PROMPT_CHARS)}"
            )
            sections.append(
                "\n".join([heading, *rendered]) if rendered
                else "\n".join([heading, _NO_ANCHOR_MANDATE])
            )

        if not sections:
            return _NO_ANCHOR_MANDATE
        return "\n".join(sections)
    except Exception as exc:  # noqa: BLE001 — a renderer never raises
        log.warning("workshop_evolve: anchor block render failed: %r", exc)
        return _NO_ANCHOR_MANDATE


def _own_anchor(candidate: Any) -> str:
    """A discovery candidate's OWN admitting evidence, rendered as its anchor.

    TWO REAL PROVENANCE SHAPES REACH HERE and both must anchor, because both are
    produced today:

      * `workshop_admission.admit_invented_angles` stamps
        `{quote, why, source_url, resolved_url, resolution_status}`;
      * `discovery_bracket.allocate_discovery` stamps
        `{question, assumption, world_says, source_url}`.

    The publisher URL (`resolved_url`) is preferred over the redirect
    (`source_url`) when one is known — it is the one a reader can act on — and
    the redirect is the fallback, never a second line, because two URLs for one
    source is two records for one fact.
    """
    prov = _provenance_of(candidate)
    cap = workshop._FINDING_PROMPT_CHARS

    quote = _flatten(prov.get("quote"), cap) or _flatten(prov.get("world_says"), cap)
    why = _flatten(prov.get("why"), cap) or _flatten(prov.get("assumption"), cap)
    url = _flatten(prov.get("resolved_url"), cap) or _flatten(prov.get("source_url"), cap)
    if not str(url).lower().startswith(("http://", "https://")):
        # A non-http source is not a source. The same rule `discovery_bracket`
        # applies at :422 and `workshop_admission` applies to `groundingChunks`:
        # a truthy `"-"` admitted 2 of 3 angles in the harness, and that is the
        # bug the whole "no source, no slot" rule exists to prevent.
        url = ""

    lines: list[str] = []
    if quote:
        lines.append(f"{len(lines)} | QUOTE: {quote}")
    if why:
        lines.append(f"{len(lines)} | WHY IT MATTERS: {why}")
    if url:
        lines.append(f"{len(lines)} | SOURCE: {url}")

    if not lines:
        return _NO_ANCHOR_DISCOVERY

    heading = (
        "THE EVIDENCE THAT ADMITTED THIS QUESTION — it is this question's only "
        "grounding, and it is what any sharper version of it must stay true to:"
    )
    return "\n".join([heading, *lines])


def barred_section(register: Any) -> str:
    """The barred list under a heading. DELEGATES — it does not re-render.

    D-W4-1 requires the barred list, EACH ENTRY CARRYING ITS FLAW, to travel with
    every generate and evolve call. `workshop_register.barred_block` is the ONE
    renderer; this wrapper only adds the heading, so the generation prompt (plan
    15.7-07) and the evolve prompt present an identical block and cannot drift
    apart. The call goes through the MODULE attribute deliberately: that is what
    makes the delegation testable, and
    `test_barred_section_delegates_to_the_register_rather_than_copying_it` fails
    if anyone ever inlines a copy here.

    Never raises: an unreadable register still yields a heading a prompt can
    carry.
    """
    try:
        block = workshop_register.barred_block(register)
    except Exception as exc:  # noqa: BLE001 — a renderer never raises
        log.warning("workshop_evolve: barred block render failed: %r", exc)
        block = "(the rejected register could not be read this round)"
    return f"{_BARRED_HEADING}\n{block}"
