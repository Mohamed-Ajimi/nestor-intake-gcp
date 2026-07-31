"""The WITHIN-RUN rejected register. Operator decision D-W4-1, 2026-07-31.

The list of questions the workshop has ALREADY rejected, carried into every
generate and evolve call so the loop stops re-proposing its own rejects.

THREE FACTS A FUTURE READER NEEDS FIRST.

(a) THE REGISTER LIVES FOR THE DURATION OF ONE WORKSHOP RUN AND DIES WITH IT.
    The redesign spec's phrase *"barred this run, kept for the next"* reads as
    cross-run storage. It does not mean that, and the operator ruled on it on
    2026-07-31: *"the next"* means the next ROUND, not the next RUN. Everything
    here is a plain dict held by the caller for the length of one run. Nothing is
    saved, nothing is loaded, and two runs in one process share nothing.

(b) THEREFORE THERE IS NO TABLE AND NO ALEMBIC MIGRATION. That is the direct
    consequence of (a), and it is deliberate rather than deferred: migrations
    0016 and 0017 have still never touched a database, and this phase must not
    add a third unpaid proof. If a future reader wants the register to survive a
    run, that is a NEW decision to take with the operator — the deferred-ideas
    list already records it — not an omission to quietly fix here.

(c) THIS MODULE IMPORTS NOTHING FROM THE PIPELINE PACKAGE, only the standard
    library. Two reasons, both load-bearing. The workshop's stage-A module and
    its ranking module must BOTH be able to import this one, so this one can
    import neither of them without a cycle. And the development machine has no
    pytest, no Docker and no project interpreter — only a stdlib-only Python —
    so a module with no package imports is a module that can still be driven and
    proven there.

WHAT BARS, AND — the load-bearing half — WHAT NEVER DOES.

    | Outcome                                             | Treatment           |
    |-----------------------------------------------------|---------------------|
    | KILL: unanswerable in principle, pure opinion, or    | BARRED. It is a     |
    | nothing about the client's decision turns on it      | defect, and a       |
    |                                                      | reworded version    |
    |                                                      | has the same defect |
    | KILL: it is a restatement of another candidate       | NOT BARRED. A       |
    |                                                      | duplicate is not a  |
    |                                                      | fault; the          |
    |                                                      | surviving twin      |
    |                                                      | represents it       |
    | WEAK after two evolve passes                         | BARRED. A real      |
    |                                                      | question the        |
    |                                                      | workshop could not  |
    |                                                      | sharpen             |
    | It lost the tournament                               | NEVER BARRED. It    |
    |                                                      | was fine, it just   |
    |                                                      | missed the cut      |
    | An invented angle whose grounded lookup found        | BARRED. A DROPPED   |
    | nothing                                              | INVENTION IS A BAR  |

BAR SOMETHING THAT MERELY CAME LAST AND YOU BREAK `enforce_scope_guard`. Its
documented repair ladder, when a client-validated question ends up with no winner,
is to PROMOTE that question's best-ranked candidate out of the full ranked
population *even though it finished below the winner cut*, and only to inject the
client's raw question text if there is nothing to promote. The coverage guarantee
depends on those below-the-cut candidates staying available. Bar them and the
repair finds nothing, silently: no error, no log, just a client question
researched from its own raw wording or not covered at all.

THE ENFORCEMENT OF THAT RULE IS AN ABSENCE, NOT A CHECK. This module exposes
exactly three causes and can express no fourth, so no caller can bar one of the
two non-barring outcomes even by mistake. Do not "complete" the set later: a
fourth member would move the guarantee from *impossible* to *nobody has done it
yet*. `bar` refuses an unknown cause outright and logs, because the only causes
anyone would plausibly invent are the two the table rules out.

WHY THE FLAW TRAVELS WITH EVERY ENTRY. D-W4-1 requires each barred entry to carry
WHY it was barred, not just its text: *"don't propose these, and here is the
flaw"* beats a bare list. A bare list tells a model what to avoid saying; a list
with flaws tells it what to avoid DOING.

AND WHY THE PROMPT LAYER ALONE WILL NOT HOLD. Enforcement is two layers by
design. This module is the first — the barred list rendered into the generate and
evolve prompts. The second is the semantic drop: clustering each round's new
candidates together with the barred ones and dropping whatever clusters onto a
barred entry, which is what *"don't rephrase it"* actually requires and what
string matching cannot do. That wiring is a separate plan's; this module supplies
the storage and the renderer it needs.
"""
# ---------------------------------------------------------------------------
# On fact (c) above, stated here in a comment rather than in the docstring on
# purpose: this module must not name the `nestor_pulse_sdk` package on any line
# a `grep -v '^ *#'` would keep, because a test asserts exactly that — the
# cheapest possible proof that the import direction is one-way and that the
# module is drivable off its own path with the package absent from `sys.path`.
#
# The same reasoning governs the two re-implementations below. `_flatten` here
# repeats the identically-named renderer in the ranking module, and the verdict
# words are re-declared rather than imported. That is the register
# `question_grouping._block_get` already uses, which repeats
# `skeptic._block_get` for exactly this reason: an import for the sake of one
# small pure helper would buy a cycle and a dependency, and cost more than the
# nine lines it saves.
#
# A NOTE FOR ANYONE GREPPING THIS FILE. The words "tournament" and "duplicate"
# appear here ONLY in the prose that explains what is NOT barred. No identifier
# in this module contains either, and that is checked by a test — see the
# docstring on why the absence of a fourth cause is the enforcement.
# ---------------------------------------------------------------------------
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The three causes, and the two that are missing on purpose.
#
#   BAR_KILL_DEFECT   the critique pass judged it KILL for a DEFECT —
#                     unanswerable in principle, pure opinion, or nothing about
#                     the client's decision turns on it. A reworded version
#                     carries the same defect, so the text is barred.
#
#                     NOT every KILL. The critique prompt's own definition of
#                     KILL includes "a restatement of another candidate", and
#                     that one does NOT bar: a duplicate is not a fault, and the
#                     surviving twin already represents it. The caller decides
#                     which kind of KILL it saw; this module cannot record the
#                     second kind at all.
#
#   BAR_WEAK_TWICE    a real, decision-relevant question the workshop tried and
#                     failed to sharpen across TWO evolve passes. `note_weak_pass`
#                     below holds that count so the caller does not have to.
#
#   BAR_LOOKUP_FAILED an INVENTED angle whose grounded lookup admitted nothing —
#                     its premise did not check out, no admitting source was
#                     found, or the lookup itself failed. All three of the
#                     admission gate's drop reasons map here; the specific one
#                     belongs in the entry's `flaw`, where a model can read it.
#
#                     THIS IS THE MEASURED GAP. In the Wave-4 harness,
#                     failed-lookup angles were never added to the barred
#                     register, so *"minimale netwerkdichtheid"* was re-proposed
#                     in rounds 2 AND 3 and spent a paid grounded lookup each
#                     time. A DROPPED INVENTION IS A BAR.
#
# There is NO cause for a question that merely came last in the tournament, and
# NO cause for one that duplicated another. Both outcomes are listed in the
# module docstring's table as NOT barring, and their absence from this tuple is
# how that is enforced — see the docstring on why not to "complete" it.
# ---------------------------------------------------------------------------
BAR_KILL_DEFECT = "kill_defect"
BAR_WEAK_TWICE = "weak_twice"
BAR_LOOKUP_FAILED = "lookup_failed"

#: A TUPLE, never a list: the set of allowed causes is a fact about the design,
#: not a collection anything is meant to append to.
_BAR_CAUSES: tuple[str, ...] = (BAR_KILL_DEFECT, BAR_WEAK_TWICE, BAR_LOOKUP_FAILED)


# ---------------------------------------------------------------------------
# The widths. BARE LITERALS, NOT ENVIRONMENT KNOBS, and deliberately so: these
# bound how much attacker-influenced text reaches a model, and a prompt-injection
# bound that an environment variable can widen is not a bound. That is the same
# reasoning the admission gate records for its own quote width, and the opposite
# trap to the one the redesign phase spent a wave unpicking — a knob that looks
# like the control and is not.
#
#   _BARRED_TEXT_CHARS   how much of a barred question reaches a prompt. Narrower
#                        than the 600 a live candidate gets, because a barred
#                        entry only has to be RECOGNISABLE — the model is being
#                        told what not to propose, not asked to judge it.
#   _BARRED_FLAW_CHARS   the flaw clause. 160, matching the width the critique
#                        pass already keeps a flaw at, so the same sentence does
#                        not get two different truncations in two prompts.
#   _BARRED_MAX_ENTRIES  how many entries reach any one prompt. Over ten rounds
#                        an unbounded barred list would inflate every generate
#                        and evolve call for the rest of the run; the overflow is
#                        STATED rather than hidden (see `barred_block`).
#   _KEY_CHARS           the width used for IDENTITY only. Wide, because two
#                        questions that differ only after character 200 are two
#                        questions and must not collapse onto one bar.
# ---------------------------------------------------------------------------
_BARRED_TEXT_CHARS = 200
_BARRED_FLAW_CHARS = 160
_BARRED_MAX_ENTRIES = 24
_KEY_CHARS = 600


def _flatten(text: Any, cap: int) -> str:
    """Collapse newlines and pipes to spaces, squeeze whitespace, truncate.

    SECURITY CONTROL, not formatting. Every prompt block in this engine renders
    one record per LINE and separates its fields with `|`, so text containing
    either character could otherwise forge an extra record and address a slot
    that is not its own. Truncation bounds how much attacker-influenced text
    reaches the model at all.

    A re-implementation of the ranking module's identically-named helper, on
    purpose — see the comment above the imports for why repeating it is cheaper
    than importing it.

    Never raises, including on an object whose `__str__` does.
    """
    try:
        raw = "" if text is None else str(text)
    except Exception:  # noqa: BLE001 — a renderer never raises
        return ""
    raw = raw.replace("|", " ").replace("\r", " ").replace("\n", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    limit = max(0, int(cap))
    return raw[:limit] if limit else ""


def _key(text: Any) -> str:
    """The identity of a question for barring purposes. Never raises.

    Case-folded and whitespace-collapsed, so a model that re-proposes the same
    question with different capitalisation or spacing does not get a second
    entry. Deliberately NOT semantic: string identity is all this module claims,
    and rephrasings are the semantic drop's job, not this one's.
    """
    return _flatten(text, _KEY_CHARS).casefold()


def new_register() -> dict[str, Any]:
    """A fresh, empty register. One per workshop run.

    Returns a PLAIN DICT, built here every call and never a module-level default.
    A shared default would be cross-run persistence by accident — the very thing
    D-W4-1 ruled out — and it would stay invisible until two runs shared one
    process, which is exactly how the worker runs.

    The shape is JSON-safe by construction: lists, dicts, strings and ints only,
    with no set, no float and nothing that holds a handle. It is meant to be
    cheap to drop into a log line or a stage-feed row on its way past.

      `barred`       ordered list of barred entries, oldest first
      `drops`        ordered list of drop records, oldest first
      `weak_passes`  normalised text -> how many evolve passes it survived WEAK
    """
    return {"barred": [], "drops": [], "weak_passes": {}}


def _slots(register: Any) -> dict[str, Any] | None:
    """The register's three containers, repaired in place, or None if unusable.

    Total over hostile input: a caller that passes None, a list or an int gets a
    logged refusal rather than an exception in the middle of a paid run.
    """
    if not isinstance(register, dict):
        log.warning(
            "workshop_register: refusing to operate on a register of type %s — "
            "expected the plain dict `new_register` returns",
            type(register).__name__,
        )
        return None
    if not isinstance(register.get("barred"), list):
        register["barred"] = []
    if not isinstance(register.get("drops"), list):
        register["drops"] = []
    if not isinstance(register.get("weak_passes"), dict):
        register["weak_passes"] = {}
    return register


def bar(
    register: Any,
    *,
    text: Any,
    flaw: Any,
    cause: Any,
    round_no: Any = 0,
) -> bool:
    """Bar one question for the rest of THIS RUN. Returns True if it is new.

    `cause` must be one of `BAR_KILL_DEFECT`, `BAR_WEAK_TWICE` or
    `BAR_LOOKUP_FAILED`. ANYTHING ELSE IS REFUSED AND LOGGED, and nothing is
    stored. That refusal is the module's whole safety property: the two outcomes
    D-W4-1 rules out — a question that merely came last, and one that restated
    another candidate — have no cause here, so a caller cannot bar one even by
    accident, and `enforce_scope_guard`'s promotion of below-the-cut candidates
    keeps working.

    FIRST FLAW WINS. Barring a text that is already barred adds no entry and does
    not overwrite the flaw already recorded, the same first-wins rule
    `_dedupe_claims` follows. The first diagnosis is the one made while the
    evidence was in front of the critic; a later pass restating it more vaguely
    must not replace it.

    Identity is case-folded and whitespace-collapsed string identity, nothing
    cleverer. An empty text after that collapse is refused — a bar on the empty
    string would match everything downstream.

    Never raises.
    """
    slots = _slots(register)
    if slots is None:
        return False

    if cause not in _BAR_CAUSES:
        log.warning(
            "workshop_register: REFUSING to bar %r under unknown cause %r. The "
            "allowed causes are %s. A question that merely came last in the "
            "tournament and one that restated another candidate are NEVER barred "
            "(D-W4-1), and barring them would break the coverage repair that "
            "promotes below-the-cut candidates",
            _flatten(text, 80),
            _flatten(cause, 40),
            ", ".join(_BAR_CAUSES),
        )
        return False

    key = _key(text)
    if not key:
        log.warning(
            "workshop_register: refusing to bar an empty question — a bar on the "
            "empty string would match every later candidate"
        )
        return False

    for entry in slots["barred"]:
        if isinstance(entry, dict) and entry.get("key") == key:
            return False

    try:
        stamped = int(round_no)
    except (TypeError, ValueError):
        stamped = 0

    slots["barred"].append(
        {
            "key": key,
            "text": _flatten(text, _BARRED_TEXT_CHARS),
            "flaw": _flatten(flaw, _BARRED_FLAW_CHARS),
            "cause": str(cause),
            "round": stamped,
        }
    )
    log.info(
        "workshop_register: barred %r for the rest of this run (cause=%s, "
        "round=%d); %d question(s) are now barred",
        _flatten(text, 80),
        cause,
        stamped,
        len(slots["barred"]),
    )
    return True


def note_weak_pass(register: Any, text: Any) -> int:
    """Count the evolve passes one question has survived as WEAK. Never raises.

    D-W4-1 bars a WEAK question only after TWO evolve passes: one WEAK verdict is
    a question the workshop has not finished with, two is one it cannot sharpen.
    Somebody has to hold that count across rounds, and holding it HERE means the
    loop does not carry a second parallel piece of state whose lifetime could
    drift from the register's.

    Returns the running count for this text, so the caller's rule reads
    `if note_weak_pass(reg, t) >= 2: bar(..., cause=BAR_WEAK_TWICE)`.
    Returns 0 when the register is unusable or the text collapses to nothing.
    """
    slots = _slots(register)
    if slots is None:
        return 0

    key = _key(text)
    if not key:
        return 0

    counts = slots["weak_passes"]
    try:
        current = int(counts.get(key, 0))
    except (TypeError, ValueError):
        current = 0
    current += 1
    counts[key] = current
    return current


# ===========================================================================
# THE PROMPT LAYER — the barred list on its way into a generate or evolve call.
# ===========================================================================

#: What an empty register renders. NEVER the empty string: a prompt heading with
#: nothing under it invites the model to fill the gap itself, and a block that
#: silently vanishes is a block nobody notices has stopped working.
_NOTHING_BARRED = (
    "(nothing has been barred yet in this run — propose freely)"
)


def barred_block(
    register: Any,
    *,
    cap_entries: Any = None,
    cap_chars: Any = None,
) -> str:
    """Render the barred list for a prompt: `INDEX | text | FLAW: flaw`.

    TWO PROPERTIES OF THIS BLOCK ARE SECURITY CONTROLS, NOT FORMATTING, in the
    same register the engine's other prompt blocks already state for themselves.
    Every entry is addressed by INDEX, and both the text and the flaw are
    TRUNCATED. Barred text is model output on its way back into another model's
    prompt — exactly the same untrusted class as a live candidate, and bounded
    exactly the same way. Without the collapse, a barred question containing
    `\\n7 | KEEP | worthless` would forge a second addressable record and speak
    about a slot that is not its own. `_flatten` above does that collapse, and is
    re-implemented locally on purpose (see the comment above the imports).

    THE FLAW IS THE POINT, NOT DECORATION. D-W4-1 requires each entry to carry
    WHY it was barred: *"don't propose these, and here is the flaw"* beats a bare
    list. A bare list tells a model which sentences to avoid; a list with flaws
    tells it which MISTAKE to avoid, which is the only version that survives
    rephrasing.

    AND THE PROMPT LAYER ALONE WILL NOT HOLD. A model asked nicely is not a
    control. The layer that actually enforces the bar is the semantic drop —
    clustering each round's new candidates together with the barred ones and
    dropping whatever clusters onto a barred entry — because that is what *"don't
    rephrase it"* requires and what no prompt can guarantee. This block is the
    cheap first layer; it is not the guarantee.

    BOUNDED OVERALL, AND THE OVERFLOW IS STATED. At most `cap_entries` entries
    reach any one prompt, OLDEST FIRST, because an unbounded barred list would
    inflate every generate and evolve call for the rest of a ten-round run. The
    surplus is announced in a trailing notice rather than silently dropped — a
    prompt that quietly forgets two-thirds of what is barred is a prompt nobody
    can debug. That notice deliberately carries NO `|`, so it can never be read
    as an addressable record.

    Never raises; returns the placeholder for any register it cannot read.
    """
    slots = _slots(register)
    if slots is None:
        return _NOTHING_BARRED

    entries = [e for e in slots["barred"] if isinstance(e, dict)]
    if not entries:
        return _NOTHING_BARRED

    try:
        limit = _BARRED_MAX_ENTRIES if cap_entries is None else int(cap_entries)
    except (TypeError, ValueError):
        limit = _BARRED_MAX_ENTRIES
    limit = max(0, limit)

    try:
        width = _BARRED_TEXT_CHARS if cap_chars is None else int(cap_chars)
    except (TypeError, ValueError):
        width = _BARRED_TEXT_CHARS
    width = max(0, width)
    flaw_width = min(width, _BARRED_FLAW_CHARS)

    shown = entries[:limit]
    lines = [
        f"{i} | {_flatten(e.get('text'), width)} | "
        f"FLAW: {_flatten(e.get('flaw'), flaw_width) or 'not recorded'}"
        for i, e in enumerate(shown)
    ]

    hidden = len(entries) - len(shown)
    if hidden > 0:
        lines.append(
            f"(and {hidden} further barred question(s) not shown here, to keep "
            f"this prompt bounded; do not propose a reworded version of anything "
            f"barred, shown or not)"
        )
        log.info(
            "workshop_register: the barred list reached a prompt with %d of %d "
            "entries shown; the remaining %d were announced but not rendered",
            len(shown),
            len(entries),
            hidden,
        )

    return "\n".join(lines)


# ===========================================================================
# THE DROP LOG — the one signal that separates two OPPOSITE measured failures.
# ===========================================================================

#: A proposal dropped because it clustered onto something ALREADY BARRED. This is
#: the loop re-proposing its own rejects.
DROP_CLUSTERED_ONTO_BARRED = "clustered_onto_barred"

#: A proposal dropped because it clustered onto a LIVE candidate already on the
#: table. Ordinary near-copy collapse — but the count is worth watching, because
#: this is the channel through which an over-eager filter strangles discovery.
DROP_CLUSTERED_ONTO_LIVE = "clustered_onto_live"

_DROP_CAUSES: tuple[str, ...] = (DROP_CLUSTERED_ONTO_BARRED, DROP_CLUSTERED_ONTO_LIVE)


def record_drop(
    register: Any,
    *,
    text: Any,
    clustered_onto: Any,
    cause: Any,
    round_no: Any,
) -> bool:
    """Log one dropped proposal: WHAT was dropped, and ONTO WHAT.

    `clustered_onto` HAS NO DEFAULT, AND THAT IS THE POINT. D-W4-1 records two
    failures the Wave-4 harness measured, and they point in opposite directions:

      * THE LOOP SPINNING. Failed-lookup angles were never barred, so *"minimale
        netwerkdichtheid"* was re-proposed in rounds 2 AND 3, spending a paid
        grounded lookup each time. *"Round 2 proposed 3 questions already
        rejected in round 1"* is the sentence that makes that visible: the loop
        is repeating itself rather than exploring.

      * THE FILTER BEING OVER-EAGER. The same harness's semantic dedup dropped 6
        proposals as rewordings — mostly fairly, but it also killed SPECIALISE
        and COMBINE attempts, and it killed round 1's only INVENT BEFORE THE
        GROUNDED LOOKUP EVER RAN. An over-eager filter suppresses discovery
        INVISIBLY: nothing errors, the round simply produces less than it could.

    "3 drops" is the same number in both worlds. Only what each one clustered
    ONTO separates them, so a caller that cannot say is a caller producing a
    number nobody can act on — and it is refused rather than defaulted to a
    blank.

    Returns True when a record was stored. Never raises.
    """
    slots = _slots(register)
    if slots is None:
        return False

    dropped = _flatten(text, _BARRED_TEXT_CHARS)
    if not dropped:
        log.warning(
            "workshop_register: refusing to log a drop with no dropped text"
        )
        return False

    onto = _flatten(clustered_onto, _BARRED_TEXT_CHARS)
    if not onto:
        log.warning(
            "workshop_register: REFUSING to log the drop of %r without naming "
            "what it clustered onto. A bare count cannot distinguish the loop "
            "re-proposing its own rejects from an over-eager filter strangling "
            "discovery, and both were measured",
            dropped[:80],
        )
        return False

    if cause not in _DROP_CAUSES:
        log.warning(
            "workshop_register: unknown drop cause %r for %r; the allowed causes "
            "are %s",
            _flatten(cause, 40),
            dropped[:80],
            ", ".join(_DROP_CAUSES),
        )
        return False

    try:
        stamped = int(round_no)
    except (TypeError, ValueError):
        stamped = 0

    slots["drops"].append(
        {
            "text": dropped,
            "clustered_onto": onto,
            "cause": str(cause),
            "round": stamped,
        }
    )
    return True


def drop_summary(register: Any, round_no: Any) -> str:
    """One plain-words sentence about a round's drops. Never raises.

    Built HERE, in one place, to the bar every degradation and note sentence in
    this engine already meets: over 40 characters, naming its count as a literal
    digit, and stating the CONSEQUENCE rather than just the event.

    Three sentences, because there are three situations worth telling apart and a
    single templated count would collapse them into one:

      * nothing was dropped — every proposal that round was new;
      * some drops landed on ALREADY BARRED questions — the loop is SPINNING
        rather than exploring, and the next round needs a new angle rather than a
        new phrasing;
      * the drops all landed on live candidates — ordinary near-copy collapse,
        but worth a second look, because this is the channel through which an
        over-eager filter quietly kills SPECIALISE, COMBINE and INVENT attempts.
    """
    slots = _slots(register)
    try:
        wanted = int(round_no)
    except (TypeError, ValueError):
        wanted = 0

    records: list[dict[str, Any]] = []
    if slots is not None:
        records = [
            r
            for r in slots["drops"]
            if isinstance(r, dict) and r.get("round") == wanted
        ]

    total = len(records)
    spun = len(
        [r for r in records if r.get("cause") == DROP_CLUSTERED_ONTO_BARRED]
    )

    if total == 0:
        return (
            f"question workshop: round {wanted} dropped 0 proposed "
            f"sub-question(s) as near-copies, so every question it proposed was "
            f"new to this run."
        )

    if spun:
        return (
            f"question workshop: round {wanted} dropped {total} proposed "
            f"sub-question(s) as near-copies, and {spun} of them repeated a "
            f"question this run had already rejected — the loop is SPINNING "
            f"rather than exploring, so the next round needs a new angle rather "
            f"than a new phrasing."
        )

    return (
        f"question workshop: round {wanted} dropped {total} proposed "
        f"sub-question(s) as near-copies of questions already on the table, and "
        f"0 of them repeated an already-rejected question — the near-copy filter "
        f"is doing the work, so check it is not also discarding genuinely new "
        f"angles."
    )
