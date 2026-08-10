"""Feed emitters for the stages Phase 15.3 left SILENT (Phase 21, plans 21-03/05).

`ENGINE_STAGES["tribunal"]` declares thirteen stages and, at the commit this
module was written against, exactly four of them emitted any run event at all:
`deep_research` (24 sites), `own_research` (7), `workshop` (2) and
`research_division` (2). The other eight — `distill`, `merge`, `gate`, `verify`,
`adjudicate`, `coverage`, `conflict`, `synthesize` — emitted ZERO. They still got
a phase label and a summary line (both are automatic; see below), so on the run
page each rendered as a heading with nothing under it, and the collapse toggle
above it expanded to reveal nothing. This module is where their BODIES live.

WHICH OF THE EIGHT ARE DONE — ALL OF THEM, AS OF 21-06. Plan 21-03 gave `verify`
a body; 21-05 gave `distill`, `merge` and `gate` theirs; 21-06 closed the set
with `adjudicate`, `coverage`, `conflict` and `synthesize`. SC1 is met: every
stage the pipeline REPORTS now emits at least one row that is neither a divider
nor a summary, and `test_run_event_emit.py` proves it from the schema rather than
from a list, so a stage added later fails that test until it emits.

ONE DECLARED STAGE STILL HAS NO ROWS, AND IT IS NOT A HOLE IN THIS WORK.
`own_research` is declared in `ENGINE_STAGES["tribunal"]` but the pipeline never
writes the key at all — a separate, older, deliberately-pinned gap with its own
self-retiring test in `test_engine_e2e_stubbed.py`. A stage that is never
REPORTED cannot be given a body from here; wiring the key is that test's job, and
the capstone test's exclusion assertion is written so that the moment somebody
does wire it, this module is required to give it rows.

FOUR RULES THIS MODULE IS BUILT ON. All four are decisions of record; breaking
any of them is a regression, not a refactor.

1. NO NEW EVENT KIND (D-03). `RUN_EVENT_KINDS` in `runs/run_events.py` is a
   CLOSED twelve-kind vocabulary whose own comment states it is "one contract in
   two languages" with the frontend's `LineKind` union: adding a kind on one side
   only renders a blank line, which is worse than an absent one. Everything below
   is expressed in `dispatch`, `agent_run`, `agent_done`, `agent_fail` and
   `thinking`, all of which the run page already renders today.

2. NEVER HAND-EMIT A `divider` OR A `summary` (D-06). `pipeline.py`'s
   `_stage_event_boundary`, driven from `_stage_log_transition`, already emits a
   summary for the outgoing stage and a divider for the incoming one at every
   real transition. A hand-emitted one here would DOUBLE the line. The eight
   silent stages were never missing their label — only their body.

3. TEXT AND META ARE BUILT INSIDE THE THUNK, NEVER ABOVE IT (D-06 again). Every
   function below reaches the emitter through the thunk-taking entry point of
   `runs/run_events.py` (the public one whose name ends in `_safe`), handing it a
   zero-argument callable. A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE
   IS ENTERED, so composing an f-string in the argument list puts the failure at
   the call site — inside the paid verify loop — where nothing inside the emitter
   can catch it. That entry point's own docstring sets this out at length; it
   applies verbatim to every site here. The values these rows are built from are
   model-shaped (`verdicts_by_index`, `entity`, `attribute`, `superseded_note`,
   claim text), which is precisely the class of input most likely to arrive
   malformed, so this is not a hypothetical.

   The count of thunk-taking calls and the count of `build=` thunks in this file
   is therefore ONE TO ONE, and that equality is checkable with a grep — which is
   the whole reason the rule is structural rather than a discipline.

4. PER-ITEM ROWS ARE BOUNDED, AND THE ELISION IS A VISIBLE ROW (D-05). See
   `MAX_ROWS_PER_STAGE` and `RowBudget` below.

WHY THE EMITTER IS IMPORTED IN MODULE FORM. `from nestor_pulse_sdk.runs import
run_events`, matching `pipeline.py`'s import block and for the reason stated
there: the D-06 call-site gate counts qualified calls to the BARE emit entry
point and requires zero of them, and a from-import would bind a bare name that
slips straight past that grep while rebuilding the whole defect.

--------------------------------------------------------------------------
HOW TO ADD THE NEXT STAGE (plans 21-05 and 21-06 — read this before writing)
--------------------------------------------------------------------------
This module is the SHARED SPINE, not a `verify` module. Extend it; do not fork
it and do not re-derive the budget.

  a. Add a `_STAGE_<NAME>` constant holding the stage key EXACTLY as
     `ENGINE_STAGES["tribunal"]` declares it. Never invent a key — an undeclared
     key renders as raw snake_case at the operator (the WR-03 defect class).
  b. Add one `emit_<stage>_*` function per feed ROW, under a banner comment
     naming the stage. `run_id` positional first, everything else keyword-only,
     returning `None` — the shape `workshop.py` already uses.
  c. Any row whose text needs a WALK over model-shaped data gets a separate
     `_<stage>_<row>_event(...)` composer whose docstring carries the marker
     "CALLED ONLY FROM INSIDE A build() THUNK". The walk is exactly the argument
     construction rule 3 keeps inside the emitter's try.
  d. Per-item rows take a `RowBudget` as their second positional argument and
     guard on `budget.take()`. One budget per stage per run, created at the
     stage's opening and `flush(noun)`-ed at its close so the elision row lands
     inside that stage rather than after the next divider.
  e. Only the meta keys in `run_events._META_FIELDS` may be set. Anything else is
     dropped with a warning. Prove the subset with a recorder, not with a grep.
  f. A ROW WHOSE TEXT IS PASSED IN MUST REFUSE A BLANK SENTENCE. Use
     `_sentence_or_none` (added by 21-05, and what `emit_verify_closing` now
     calls) rather than writing the check a second time. `run_events.emit`
     ACCEPTS an empty text and queues it, and an empty row renders as a BLANK
     LINE — which `RUN_EVENT_KINDS`' own comment already calls worse than an
     absent one, and which is squarely the "rubbish information" half of the
     operator's 2026-08-10 UAT. 21-03 shipped this defect in its own first cut
     and its own module docstring had already stated the rule, so stating it is
     evidently not enough: the check now lives in ONE named function.
  g. IF A ROW'S `kind` VARIES WITH THE DATA, THE CHOICE IS MADE OUTSIDE THE
     THUNK — `kind` is an argument to the emitter, not something the thunk
     returns — so that choice MUST NOT be able to raise. Give it its own
     never-raising `_<stage>_<row>_kind(...)` helper with an explicit safe
     default, the way `emit_distill_record` does. Reading a model-shaped
     attribute inline in the argument list would put rule 3's exact defect back
     at the call site while looking like a one-liner.
  h. A ROW THAT NAMES A POPULATION MUST COUNT THE POPULATION IT NAMES, AND THE
     COUNT GOES WHERE THE WALK IS SAFE (21-06). Most counts in this module are
     plain integers the caller already holds, and passing those is right. But
     when the honest number needs a WALK — `emit_coverage_dispatch` reports the
     claims the GATES SELECTED, not every distilled claim — that walk is
     model-shaped and belongs inside the thunk with the rest of rule 3, not in
     the argument list. The tempting shortcut is to pass a number that is merely
     nearby and cheap to compute (`len(claims)`); do not. The coverage row exists
     precisely to show WHICH population the cost trap's intersection kept, so a
     row naming the wrong population is worse than no row — it is a confident
     false statement about the one guard standing between this stage and roughly
     2,100 paid sessions.
"""
from __future__ import annotations

import os
from typing import Any, Optional

# MODULE FORM, DELIBERATELY -- see "WHY THE EMITTER IS IMPORTED IN MODULE FORM"
# in the module docstring above.
from nestor_pulse_sdk.runs import run_events
# The shared truncation. `workshop.py` already imports it for exactly this job
# (bounding model-shaped text inside a feed row), so reusing it keeps ONE
# truncation convention -- first N characters plus a single U+2026, so a cut line
# is VISIBLY cut rather than silently shortened -- rather than a second one that
# rounds differently.
from nestor_pulse_sdk.runs.stage_feed import truncate_task_prompt

# ===========================================================================
# THE SPINE. Shared by every stage this module serves.
# ===========================================================================

#: Feed rows one stage may emit for its individual items, before the rest are
#: elided into a single stated row.
#:
#: THE ARITHMETIC (D-05). The emitter's per-run queue ceiling is 5000
#: (`run_events._MAX_QUEUE`) and the page's own backfill caps at the same 5000
#: (`useRunEvents.ts`: PAGE_LIMIT 500 x MAX_PAGES 10), after which the page
#: renders a truncation notice in words. Eight stages at 25 rows each add AT MOST
#: 200 rows and cannot approach either bound. The bound exists because a run
#: distills HUNDREDS of claims: one row per claim across `distill`, `gate`,
#: `verify` and `adjudicate` would be thousands of rows, which would push the
#: early events -- the ones that explain how the run got here -- out of both.
#:
#: Env override uses the `NESTOR_TRIBUNAL_*` idiom the engine already uses for
#: `_SKEPTIC_CONCURRENCY` and `_GROUP_VERIFY`, so a retune needs no code change.
#: RESOLVED AT IMPORT: a `monkeypatch.setenv` after import does nothing, so tests
#: that need a different bound set this attribute or pass `limit=` explicitly.
MAX_ROWS_PER_STAGE = int(os.environ.get("NESTOR_TRIBUNAL_FEED_ROWS_PER_STAGE", "25"))

#: Characters kept of a CLAIM inside a row body. A feed row is a 13px monospace
#: line, and `run_events` clamps the whole row at 400 characters anyway; clipping
#: the claim first means the clamp falls on the row's own trailing detail rather
#: than mid-verdict. Named rather than inlined so the two widths are retunable
#: together.
CLAIM_CHARS = 110

#: Characters kept of an entity, attribute or other short label.
LABEL_CHARS = 60


def clip_claim(text: Any) -> str:
    """One line of claim text, bounded and never raising. Empty string on None."""
    return truncate_task_prompt(text, CLAIM_CHARS) or ""


def clip_label(text: Any) -> str:
    """One short label (entity / attribute), bounded and never raising."""
    return truncate_task_prompt(text, LABEL_CHARS) or ""


def _sentence_or_none(text: Any) -> Optional[str]:
    """The caller's sentence, or `None` when there is no sentence to show.

    THE BLANK-ROW RULE, IN ONE PLACE (21-05). Several helpers here take a
    sentence the CALLER already composed — the closing line of `verify`,
    `distill`, `merge` and `gate` are each bound once and handed to both the feed
    row and `stage_detail`, so the two surfaces cannot drift. Every one of them
    therefore faces the same hazard: `run_events.emit` accepts an empty `text`
    and queues it, and an empty row renders as a BLANK LINE in the feed, which
    the vocabulary comment in `runs/run_events.py` names as worse than an absent
    one.

    21-03 wrote that rule into this module's docstring and then shipped
    `emit_verify_closing` breaking it, which is the argument for a named function
    rather than a restated convention: a rule that lives in prose is re-derived
    by every next author, and 21-06 has four more closing lines to add.

    The work is a string test on a value the caller already holds — the same
    class as `RowBudget.take()` — so it cannot raise, and it is the only work the
    calling helper performs outside the emitter's own try.
    """
    if text is None:
        return None
    sentence = str(text).strip()
    return sentence or None


class RowBudget:
    """One stage's per-item row allowance, for one run. Never raises.

    Created once at the stage's opening and carried through every per-item emit
    site in that stage, so the bound is a property of the STAGE rather than of
    whichever branch happened to run.
    """

    __slots__ = ("run_id", "stage", "limit", "used", "elided")

    def __init__(self, run_id: Any, stage: str, limit: Optional[int] = None) -> None:
        self.run_id = run_id
        self.stage = str(stage)
        try:
            self.limit = int(MAX_ROWS_PER_STAGE if limit is None else limit)
        except (TypeError, ValueError):
            self.limit = int(MAX_ROWS_PER_STAGE)
        #: Rows granted so far.
        self.used = 0
        #: Rows REFUSED since the last flush. Counted, never ignored.
        self.elided = 0

    def take(self) -> bool:
        """Grant one row while the budget lasts; otherwise count a refusal.

        Returns True exactly `limit` times. The only work a guarded emit site
        performs outside the emitter's own try is this integer comparison, which
        is why a per-item site still cannot fail a run.
        """
        if self.used < self.limit:
            self.used += 1
            return True
        self.elided += 1
        return False

    def flush(self, noun: str) -> None:
        """State the elision AS A VISIBLE ROW, then reset the counter.

        D-05's rule, and the house rule `StageFeed._snapshot_locked` already
        applies to its own overflow: dropped rows are announced in the operator's
        own view rather than silently absent. A budget that swallowed rows
        quietly would be the exact failure the `run_event` table exists to end --
        the operator cannot tell "this stage checked 25 clusters" from "this
        stage checked 300 and showed you 25".

        Idempotent: `elided` is zeroed here, so a second call is a no-op and a
        stage that never overflowed emits nothing.
        """
        elided = self.elided
        if elided <= 0:
            return
        self.elided = 0
        limit = self.limit
        stage = self.stage
        run_events.emit_safe(
            self.run_id,
            stage=stage,
            kind="thinking",
            build=lambda: (
                f"{elided} more {noun}(s) not shown — the feed shows the first "
                f"{limit}",
                {"items": elided},
            ),
        )


# ===========================================================================
# `verify` -- Skeptic verification.
#
# THE STAGE THE OPERATOR NAMED TWICE, and the one where the run's money and its
# meaning both live. Until Phase 21 it emitted nothing at all: the run page
# showed "Skeptic verification" as a heading with an empty body while the engine
# was spending most of the run's budget under it.
#
# The verdict vocabulary these rows name is `support` / `refute` /
# `insufficient` / `superseded`, carried per claim index in `verdicts_by_index`
# (`group_skeptic.py::_parse_group_verdict`, enum declared on
# `tools.EMIT_GROUP_VERDICT_TOOL`).
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Skeptic verification"). Not invented here.
_STAGE_VERIFY = "verify"

#: The two verdicts that earn their own feed row. A `support` verdict is the
#: EXPECTED outcome of a check and is already carried by the group's tally line;
#: a row apiece would bury the two verdicts that change what ships. `refute` is
#: what removes a passage from the delivered report; `superseded` is what carries
#: G-07's caveat. Read off the enum cited in this section's banner.
_VERDICT_REFUTE = "refute"
_VERDICT_SUPERSEDED = "superseded"

#: Verdicts, in the order the group tally names them.
_VERDICT_ORDER = ("support", _VERDICT_REFUTE, "insufficient", _VERDICT_SUPERSEDED)


def emit_verify_dispatch(
    run_id: Any,
    *,
    groups_selected: Any,
    groups_total: Any,
    multi: Any,
    claims_selected: Any,
    claims_total: Any,
) -> None:
    """The verify stage's opening header — the work, and its counts.

    ONE HEADER FOR THE STAGE, not one per cluster. The header is what the
    indented per-cluster children hang under; one per cluster would emit dozens
    of headers with one child each, which is not this design with a bug in it but
    a different design (`test_run_event_emit.py`'s header, behaviour 2).
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="dispatch",
        build=lambda: (
            f"Dispatching skeptic verification — checking {groups_selected} of "
            f"{groups_total} claim cluster(s) ({multi} holding more than one "
            f"stream's version of the same fact) · {claims_selected} of "
            f"{claims_total} claims selected by the gates",
            {"items": groups_selected},
        ),
    )


def emit_verify_batch_dispatch(run_id: Any, *, selected: Any, total: Any) -> None:
    """The per-claim branch's opening header.

    The grouped branch and this one are mutually exclusive at runtime
    (`_GROUP_VERIFY`), so exactly one dispatch header reaches the feed either
    way.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="dispatch",
        build=lambda: (
            f"Dispatching skeptic verification — {selected} of {total} claim(s) "
            f"selected by the gates, checked one at a time",
            {"items": selected},
        ),
    )


def _verify_group_run_event(group: Any) -> tuple[str, dict[str, Any]]:
    """Compose the cluster START line. CALLED ONLY FROM INSIDE A build() THUNK.

    Every field is read off the RAW group dict HERE rather than at the call site.
    A restored or degraded group missing `entity`, `attribute` or `claims` then
    costs this ROW and never the run, which is the whole of D-06 at this site.
    """
    members = group.get("claims") or []
    entity = clip_label(group.get("entity"))
    attribute = clip_label(group.get("attribute"))
    stakes = str(group.get("stakes") or "med")
    return (
        f"Checking {entity or '?'} · {attribute or '?'} — {len(members)} claim "
        f"variant(s), {stakes} stakes",
        {"items": len(members)},
    )


def emit_verify_group_run(run_id: Any, budget: RowBudget, *, group: Any) -> None:
    """One claim cluster has been handed to a skeptic session.

    NO `is_live` META, DELIBERATELY. It is written at exactly one production site
    today, as a literal `True`, so it is a constant rather than a liveness signal;
    the run page now derives liveness from a row's POSITION and the run's state
    (plan 21-01). Setting it here would re-assert a claim about "now" that an
    append-only log cannot make about its own history.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="agent_run",
        build=lambda: _verify_group_run_event(group),
    )


def _verdict_tally(verdicts: Any) -> dict[str, int]:
    """Count verdicts by value. Tolerates a non-mapping and a malformed entry.

    CALLED ONLY FROM INSIDE A build() THUNK (through `_verify_group_done_event`).
    """
    tally: dict[str, int] = {}
    if not isinstance(verdicts, dict):
        return tally
    for entry in verdicts.values():
        value = entry.get("verdict") if isinstance(entry, dict) else None
        key = str(value or "insufficient")
        tally[key] = tally.get(key, 0) + 1
    return tally


def _verify_group_done_event(group: Any, verdicts: Any) -> tuple[str, dict[str, Any]]:
    """Compose the cluster FINISH line and its tally.

    CALLED ONLY FROM INSIDE A build() THUNK. Walking a model-shaped mapping is
    exactly the argument construction that must stay inside the emitter's try:
    handing this function's RESULT to the emitter instead would move the walk
    back to the call site, where a malformed verdict raises in the middle of the
    paid verify loop.
    """
    tally = _verdict_tally(verdicts)
    counted = sum(tally.values())
    entity = clip_label(group.get("entity"))
    attribute = clip_label(group.get("attribute"))
    parts = [f"{tally[name]} {name}" for name in _VERDICT_ORDER if tally.get(name)]
    # An extra verdict value the enum does not declare is REPORTED, not dropped:
    # a tally that silently omits it would under-count the group.
    parts += [
        f"{count} {name}"
        for name, count in sorted(tally.items())
        if name not in _VERDICT_ORDER
    ]
    detail = " · ".join(parts) if parts else "no verdict returned"
    return (
        f"Checked {entity or '?'} · {attribute or '?'} — {detail}",
        {"items": counted},
    )


def emit_verify_group_done(
    run_id: Any, budget: RowBudget, *, group: Any, verdicts: Any
) -> None:
    """One claim cluster came back, and WHAT IT CONCLUDED.

    `verdicts` is the RAW `verdicts_by_index` mapping the group skeptic returned.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="agent_done",
        build=lambda: _verify_group_done_event(group, verdicts),
    )


def _verify_group_failed_event(group: Any, reason: Any) -> tuple[str, dict[str, Any]]:
    """Compose the cluster FAILURE line. CALLED ONLY FROM INSIDE A build() THUNK.

    IT MUST SAY WHY, AND WHICH CLUSTER. "The word failed on its own is the exact
    defect phase 15.3 exists to remove" — and a failure line that does not name
    its cluster leaves the operator unable to tell which part of the report ships
    unexamined.
    """
    members = group.get("claims") or []
    entity = clip_label(group.get("entity"))
    attribute = clip_label(group.get("attribute"))
    return (
        f"Not checked: {entity or '?'} · {attribute or '?'} — {reason}. Its "
        f"{len(members)} claim(s) ship unexamined: only a refutation removes one",
        {"items": len(members)},
    )


def emit_verify_group_failed(
    run_id: Any, budget: RowBudget, *, group: Any, reason: Any
) -> None:
    """A cluster that was NOT checked, and the reason it was not.

    Two distinct reasons reach this site from `pipeline.py`: a skeptic session
    that crashed or timed out, and a cluster skipped because the budget governor
    stopped the spend. An operator must not have to infer from an absence that a
    cluster was skipped rather than checked.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="agent_fail",
        build=lambda: _verify_group_failed_event(group, reason),
    )


def emit_verify_batch_done(
    run_id: Any, budget: RowBudget, *, verified: Any, selected: Any
) -> None:
    """The per-claim branch's flush line."""
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="agent_done",
        build=lambda: (
            f"{verified} of {selected} selected claim(s) checked",
            {"items": verified},
        ),
    )


def _noteworthy_verdicts(group: Any, verdicts: Any) -> list[tuple[int, dict]]:
    """The verdict entries that earn their own row, in claim-index order.

    CALLED ONLY FROM INSIDE A build() THUNK (through `_verify_verdict_event`),
    and re-read per row rather than cached, so a mapping that turns out not to be
    a mapping costs rows and not the run.
    """
    if not isinstance(verdicts, dict):
        return []
    out: list[tuple[int, dict]] = []
    for index, entry in verdicts.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("verdict") not in (_VERDICT_REFUTE, _VERDICT_SUPERSEDED):
            continue
        try:
            out.append((int(index), entry))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda pair: pair[0])
    return out


def _verify_verdict_event(group: Any, verdicts: Any, index: int) -> tuple[str, dict]:
    """Compose ONE claim-verdict row. CALLED ONLY FROM INSIDE A build() THUNK.

    Both the verdict mapping and the claim list are re-read here, by index, for
    the reason the module docstring's rule 3 gives.
    """
    entry = verdicts[index] if isinstance(verdicts, dict) else {}
    verdict = str((entry or {}).get("verdict") or "")
    members = group.get("claims") or []
    claim = clip_claim(members[index].get("text") if index < len(members) else "")
    note = str((entry or {}).get("superseded_note") or "").strip()
    text = f"{verdict.upper()} — {claim or '(claim text unavailable)'}"
    if verdict == _VERDICT_SUPERSEDED and note:
        text = f"{text} — {clip_claim(note)}"
    return text, {"sub": verdict}


def emit_verify_verdicts(
    run_id: Any, budget: RowBudget, *, group: Any, verdicts: Any
) -> None:
    """The individual claim verdicts — THE ROW THE OPERATOR ASKED FOR TWICE.

    D-04 names `verify` as the stage that must show the individual claim
    verdicts; if scope is ever cut in this plan, this is the last thing cut.

    Only `refute` and `superseded` earn a row. `support` is the expected outcome
    of a check and is already carried by the count on the cluster's finish line,
    so a row apiece would bury the two verdicts that actually change what ships:
    a refutation is what `scrub_research` deletes a passage on, and a supersession
    is what carries G-07's caveat into the report.

    Bounded like every per-item site. The selection walk itself happens inside a
    thunk-protected composer, so a `verdicts` that is not a mapping produces no
    rows rather than an exception.
    """
    try:
        noteworthy = _noteworthy_verdicts(group, verdicts)
    except Exception:  # noqa: BLE001 -- a feed row never costs the run
        return
    for index, _entry in noteworthy:
        if not budget.take():
            return
        run_events.emit_safe(
            run_id,
            stage=_STAGE_VERIFY,
            kind="thinking",
            build=lambda index=index: _verify_verdict_event(group, verdicts, index),
        )


def emit_verify_closing(run_id: Any, *, text: Any) -> None:
    """The verify stage's closing line — degradation stated in WORDS (G-10).

    THE STRING IS PASSED IN, NOT REBUILT. `pipeline.py::_verify_closing_item` is
    the ONE place the degradation sentence is composed, and G-10 requires that
    sentence to be in words rather than a subtle icon because the run still ends
    `completed`. A second composer here would drift from it, and the run page and
    the intake card would then report different degradation for the same run.
    The caller binds that item once and hands both surfaces the same object.

    A BLANK SENTENCE EMITS NOTHING. `run_events.emit` accepts an empty `text` and
    would queue it, and an empty row renders as a BLANK LINE in the feed — which
    the vocabulary comment in `runs/run_events.py` already names as worse than an
    absent one. So a caller whose funnel produced no sentence loses the row rather
    than printing a gap. 21-05 lifted that check into `_sentence_or_none` so the
    three closing lines it added, and the four 21-06 will add, cannot each
    re-derive it — the substance and the behaviour here are unchanged.
    """
    sentence = _sentence_or_none(text)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_VERIFY,
        kind="thinking",
        build=lambda: (sentence, None),
    )


# ===========================================================================
# `distill` -- Claim distillation.
#
# WHAT THE OPERATOR CANNOT SEE WITHOUT THESE ROWS. This stage is where each
# research stream's own fact list is read, and where a stream that stated no
# usable list is sent through the fallback distiller instead (D-14). Both are
# per-STREAM outcomes, and the stage's closing sentence only ever reported their
# TOTALS -- so a run in which one provider silently contributed nothing looked
# identical, on the page, to one in which all four contributed evenly.
#
# The shape read here is `ProviderFactsRecord`
# (`pipeline/synthesis/steps.py`): `provider`, `facts_from_list`,
# `claims_from_fallback`, `reports_fell_back` and `reason`. `reason` carries
# 15.2-04's own plain-English fallback sentence VERBATIM -- its module writes it
# to be read by a human -- which is why the row quotes it instead of paraphrasing.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Claim distillation"). Not invented here.
_STAGE_DISTILL = "distill"


def emit_distill_dispatch(run_id: Any, *, streams: Any, reports: Any) -> None:
    """The distill stage's opening header — how much research is being read.

    ONE HEADER FOR THE STAGE. Same rule, and the same reason, as
    `emit_verify_dispatch`: the per-stream rows are the children that hang under
    it.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_DISTILL,
        kind="dispatch",
        build=lambda: (
            f"Reading the fact lists of {streams} research stream(s) across "
            f"{reports} report(s)",
            {"items": streams},
        ),
    )


def _distill_record_kind(record: Any) -> str:
    """`agent_retry` for a stream that fell back, `agent_done` otherwise.

    NEVER RAISES, and that is the point (recipe step g). `kind` is an argument to
    the emitter rather than something the thunk returns, so this choice is made
    OUTSIDE the protected region — reading `record.reports_fell_back` inline in
    the argument list would put rule 3's exact defect back at the call site.
    A record too degraded to answer the question is reported as a plain finish
    row: the row itself still says what the stream yielded, and claiming a
    fallback that may not have happened would be a worse lie than omitting the
    distinction.

    WHY `agent_retry` AND NOT `agent_fail`. A fallback is NOT a failure. Per D-14
    — restated at `pipeline.py`'s own `_fallen_back_records` comment — it degrades
    ONE STREAM's metadata and not the run, because the provider's research still
    reached the merge in full. `agent_fail` renders as an ✗ and would tell the
    operator a stream was lost when nothing was.
    """
    try:
        return "agent_retry" if int(record.reports_fell_back) > 0 else "agent_done"
    except Exception:  # noqa: BLE001 -- a kind choice may never cost the run
        return "agent_done"


def _distill_record_event(record: Any) -> tuple[str, dict[str, Any]]:
    """Compose ONE research stream's row. CALLED ONLY FROM INSIDE A build() THUNK.

    Every field is read off the RAW record HERE rather than at the call site, so
    a record that is not the dataclass this expects costs this ROW and never the
    run. `reason` is quoted rather than summarised: 15.2-04 writes that sentence
    for a human to read, and "why did this stream fall back" is precisely the
    question that otherwise has to be answered out of Cloud Logging.
    """
    provider = clip_label(record.provider)
    stated = int(record.facts_from_list)
    distilled = int(record.claims_from_fallback)
    if int(record.reports_fell_back) > 0:
        reason = clip_claim(record.reason)
        return (
            f"{provider or '?'} stated no fact list of its own"
            + (f" — {reason}" if reason else "")
            + f" · {distilled} claim(s) distilled from its prose instead",
            {"items": distilled, "provider": provider},
        )
    return (
        f"{provider or '?'} stated {stated} fact(s) of its own",
        {"items": stated, "provider": provider},
    )


def emit_distill_record(run_id: Any, budget: RowBudget, *, record: Any) -> None:
    """One research stream, and what reading it actually yielded.

    BOUNDED LIKE EVERY PER-ITEM SITE even though there are at most four streams.
    A stage that opts out of the bound because "it can never overflow today" is a
    stage that grows one later without anyone noticing, and the cost of the guard
    is one integer comparison.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_DISTILL,
        kind=_distill_record_kind(record),
        build=lambda: _distill_record_event(record),
    )


def emit_distill_done(run_id: Any, *, text: Any, claims: Any) -> None:
    """The distill stage's closing line — THE SAME SENTENCE `stage_detail` gets.

    THE STRING IS PASSED IN, NOT REBUILT, for the reason `emit_verify_closing`
    gives at length: the caller binds it once and hands both surfaces the same
    object, so the run page and the intake card cannot report different totals
    for the same run. A blank sentence emits nothing (`_sentence_or_none`).
    """
    sentence = _sentence_or_none(text)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_DISTILL,
        kind="thinking",
        build=lambda: (sentence, {"items": claims}),
    )


# ===========================================================================
# `merge` -- Cross-provider merge.
#
# THE STAGE D11 EXISTS FOR. Until 15.2 the clusterer ran AFTER the gates, so two
# providers contradicting each other were two unrelated claims checked in two
# unrelated skeptic sessions, each of which found its own supporting source and
# passed -- which is how run 4cbb5311 published Aral's German fuel market share
# at both 16% and 21%. Clustering first is what puts a contradiction in ONE
# session that can reconcile it.
#
# So the row that matters here is the MULTI-MEMBER CLUSTER. A singleton is the
# ordinary case and earns nothing; a cluster holding two or more streams'
# version of the same fact is the whole point of the reordering, and it is the
# row that lets an operator see a reconciliation about to happen.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Cross-provider merge"). Not invented here.
_STAGE_MERGE = "merge"

#: Members below which a cluster is the ordinary case and earns no row.
_MERGE_MIN_MEMBERS = 2


def emit_merge_dispatch(run_id: Any, *, claims: Any, streams: Any) -> None:
    """The merge stage's opening header."""
    run_events.emit_safe(
        run_id,
        stage=_STAGE_MERGE,
        kind="dispatch",
        build=lambda: (
            f"Merging {claims} fact(s) from {streams} research stream(s) into "
            f"one clustered list",
            {"items": claims},
        ),
    )


def _merge_cluster_members(group: Any) -> int:
    """How many claims this cluster holds, or 0 for a shape that cannot say.

    NEVER RAISES: this answers the SELECTIVITY question — whether the cluster
    earns a row at all — which, like the kind choice, is decided outside the
    thunk. A group too degraded to count is treated as a singleton and skipped;
    it cannot be described honestly anyway.
    """
    try:
        return len(group.get("claims") or [])
    except Exception:  # noqa: BLE001 -- a selectivity test may never cost the run
        return 0


def _merge_cluster_event(group: Any) -> tuple[str, dict[str, Any]]:
    """Compose ONE multi-member cluster's row. CALLED ONLY FROM INSIDE A build()
    THUNK.

    The entity and attribute are model-shaped strings, read and clipped here.
    """
    members = group.get("claims") or []
    entity = clip_label(group.get("entity"))
    attribute = clip_label(group.get("attribute"))
    return (
        f"{entity or '?'} · {attribute or '?'} — {len(members)} stream(s) stated "
        f"a version of the same fact; they share one skeptic session",
        {"items": len(members)},
    )


def emit_merge_cluster(run_id: Any, budget: RowBudget, *, group: Any) -> None:
    """A cluster holding MORE THAN ONE stream's version of the same fact.

    A SINGLETON EARNS NO ROW, and the rule lives HERE rather than in a condition
    at the call site. `pipeline.py` loops the groups unconditionally; putting the
    filter there too would be a second place the rule lives, and the two would
    eventually disagree about what "multi" means. This is the same reasoning
    `emit_verify_verdicts` applies to `support`.
    """
    if _merge_cluster_members(group) < _MERGE_MIN_MEMBERS:
        return
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_MERGE,
        kind="thinking",
        build=lambda: _merge_cluster_event(group),
    )


def emit_merge_done(run_id: Any, *, text: Any, clusters: Any) -> None:
    """The merge stage's closing line — THE SAME SENTENCE `stage_detail` gets.

    `pipeline.py` ALREADY BINDS THIS STRING to a local (`_merge_row`) before it
    writes the stage detail, so it is passed here rather than rebuilt. That local
    carries two things a second composer would lose: the fail-loud
    `NESTOR_TRIBUNAL_GROUP_VERIFY=false` sentence — which is the difference
    between a contradiction being reconciled and a contradiction shipping — and
    the per-stream fallback attribution. It is also what the `log.info` line on
    the next line of `pipeline.py` prints, so the feed, the stage detail and the
    log are one sentence with one author.
    """
    sentence = _sentence_or_none(text)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_MERGE,
        kind="thinking",
        build=lambda: (sentence, {"items": clusters}),
    )


# ===========================================================================
# `gate` -- Verification gates.
#
# WHERE THE RUN DECIDES WHAT IT WILL NOT CHECK. Two cheap per-claim gates
# (materiality and error-likelihood) decide which claims are worth fact-checking;
# a DROP means the claim is never seen by a skeptic. Run 4cbb5311 dropped 738
# claims here, and the page said nothing about a single one of them.
#
# A drop is a ROUTING decision, so these rows are `plan` -- the kind whose own
# comment in `RUN_EVENT_KINDS` reads "branch -- routing / planning".
#
# THE REASON IS NAMED IN THE GATE'S OWN VOCABULARY, not translated into prose.
# `apply_gates` writes `claim["gate"] = {"decision", "reason", "strict",
# "gate_error"}` (`gates.py`), where `reason` is one of KEEP, NOT_FALSIFIABLE,
# NOT_LOAD_BEARING or BOTH. The operator's question is WHICH GATE refused the
# claim, and those four literals are the answer -- a paraphrase would make the
# feed row and the funnel's own printed reason breakdown look like two different
# accountings of the same drop.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Verification gates"). Not invented here.
_STAGE_GATE = "gate"

#: `gates.py::_DROP`. Read off that module's own literal, not invented.
_GATE_DROP = "DROP"


def emit_gate_dispatch(run_id: Any, *, claims: Any) -> None:
    """The gate stage's opening header."""
    run_events.emit_safe(
        run_id,
        stage=_STAGE_GATE,
        kind="dispatch",
        build=lambda: (
            f"Gating {claims} claim(s) — deciding which are worth fact-checking",
            {"items": claims},
        ),
    )


def _gate_is_drop(claim: Any) -> bool:
    """Did the gates DROP this claim? NEVER RAISES.

    The SELECTIVITY question, decided outside the thunk for the same reason the
    merge stage's member count is. A KEEP is the expected case and is already
    counted by the funnel, so only a DROP earns a row — and a claim whose gate
    block is missing or malformed is not an accountable drop and must not be
    reported as one.
    """
    try:
        return str(claim["gate"]["decision"]).upper() == _GATE_DROP
    except Exception:  # noqa: BLE001 -- a selectivity test may never cost the run
        return False


def _gate_drop_event(claim: Any) -> tuple[str, dict[str, Any]]:
    """Compose ONE dropped claim's row. CALLED ONLY FROM INSIDE A build() THUNK.

    Both the reason and the claim text are read off the raw claim HERE. The claim
    text is provider- and model-influenced, which is the class of input rule 3
    exists for.
    """
    reason = str(claim["gate"]["reason"])
    text = clip_claim(claim.get("text"))
    return (
        f"Not checked — {reason}: {text or '(claim text unavailable)'}",
        {"sub": reason},
    )


def emit_gate_drop(run_id: Any, budget: RowBudget, *, claim: Any) -> None:
    """One claim the gates refused to check, and WHICH GATE refused it."""
    if not _gate_is_drop(claim):
        return
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_GATE,
        kind="plan",
        build=lambda: _gate_drop_event(claim),
    )


def _gate_done_event(sentence: str, funnel: Any) -> tuple[str, dict[str, Any]]:
    """Compose the gate stage's closing row. CALLED ONLY FROM INSIDE A build()
    THUNK.

    THE SENTENCE SURVIVES A MALFORMED FUNNEL. 15.4-05's lesson is that a build
    which raises is a LOST ROW, and this row is the stage's whole conclusion —
    losing it because a count could not be read would trade the operator's
    sentence for a meta field nothing renders on its own.
    """
    try:
        return sentence, {"items": int(funnel["selected_verify"])}
    except Exception:  # noqa: BLE001 -- the meta is worth less than the sentence
        return sentence, None


def emit_gate_done(run_id: Any, *, text: Any, funnel: Any) -> None:
    """The gate stage's closing line — THE SAME SENTENCE `stage_detail` gets.

    Passed in, not rebuilt, for the reason `emit_verify_closing` gives. A blank
    sentence emits nothing (`_sentence_or_none`).
    """
    sentence = _sentence_or_none(text)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_GATE,
        kind="thinking",
        build=lambda: _gate_done_event(sentence, funnel),
    )


# ===========================================================================
# `adjudicate` -- Adjudication.
#
# WHERE THE VERDICTS BECOME A DECISION. The skeptic stage produces verdicts;
# THIS stage turns them into two lists -- `survivors` and `dropped` -- under
# `SURVIVAL_RULE`. A dropped claim is removed from the report and, one stage
# later, every passage that depends on it is physically scrubbed out of the
# research. That is the most consequential thing the engine does to its own
# output, and until 21-06 the page said only how many.
#
# "HOW MANY" IS NOT THE OPERATOR'S QUESTION. `pipeline.py`'s existing closing
# line already reads "N survived - M dropped of K claims"; what it cannot say is
# WHICH. The per-claim rows below are the same answer the `rejected_claims`
# ledger gives the Deep Content Compare -- one stage earlier, and on the page.
#
# THE REASON LITERAL IS THE LEDGER'S OWN. `pipeline.py` stamps every rejected
# claim `failed_factcheck` or `lost_conflict`, and it distinguishes them with the
# `_factcheck_dropped_ids` snapshot taken BEFORE conflict resolution runs. Every
# claim dropped at THIS point is a fact-check drop by construction -- conflict
# losers join `dropped` later -- so these rows carry `failed_factcheck` and the
# conflict stage's rows carry the other. Naming them in the ledger's vocabulary
# rather than in fresh prose is what keeps the feed and the ledger one accounting.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Adjudication"). Not invented here.
_STAGE_ADJUDICATE = "adjudicate"

#: `pipeline.py::rejected_claims`' own literal for a claim the skeptics removed,
#: as opposed to `lost_conflict`. Read off that ledger, not coined here.
_REASON_FACTCHECK = "failed_factcheck"


def emit_adjudicate_dispatch(run_id: Any, *, claims: Any, rule: Any) -> None:
    """The adjudicate stage's opening header — the work, and the RULE it applies.

    THE RULE IS NAMED BECAUSE IT IS TUNABLE. `SURVIVAL_RULE` is read from
    `NESTOR_TRIBUNAL_SURVIVAL_RULE` at import, so two runs of the same intake can
    adjudicate the same verdicts differently and nothing on the page would say
    so. An operator comparing two runs needs to see which rule each one used
    before the survivor counts mean anything.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_ADJUDICATE,
        kind="dispatch",
        build=lambda: (
            f"Adjudicating {claims} fact-checked claim(s) under the "
            f"{clip_label(rule) or '?'} survival rule",
            {"items": claims},
        ),
    )


def _adjudicate_drop_event(claim: Any) -> tuple[str, dict[str, Any]]:
    """Compose ONE dropped claim's row. CALLED ONLY FROM INSIDE A build() THUNK.

    The claim text is provider- and model-influenced -- rule 3's exact input
    class -- so it is read and clipped HERE rather than at the call site, which
    sits in the loop immediately after adjudication.
    """
    text = clip_claim(claim.get("text") or claim.get("claim_text"))
    return (
        f"Dropped — failed fact-check: {text or '(claim text unavailable)'}",
        {"sub": _REASON_FACTCHECK},
    )


def emit_adjudicate_drop(run_id: Any, budget: RowBudget, *, claim: Any) -> None:
    """One claim the fact-checking removed, NAMED.

    Bounded like every per-item site: a run can drop hundreds of claims here, and
    D-05's arithmetic is written against exactly this stage.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_ADJUDICATE,
        kind="thinking",
        build=lambda: _adjudicate_drop_event(claim),
    )


def emit_adjudicate_done(run_id: Any, *, text: Any, survivors: Any) -> None:
    """The adjudicate stage's closing line — THE SAME SENTENCE `stage_detail` gets.

    THE STRING IS PASSED IN, NOT REBUILT, for the reason `emit_verify_closing`
    gives at length: `pipeline.py` binds it once and hands both surfaces the same
    object, so the run page and the intake card cannot report different survivor
    counts for one run. A blank sentence emits nothing (`_sentence_or_none`).
    """
    sentence = _sentence_or_none(text)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_ADJUDICATE,
        kind="thinking",
        build=lambda: (sentence, {"items": survivors}),
    )


# ===========================================================================
# `coverage` -- Coverage gate.
#
# THE EMPTIEST STAGE IN THE ENGINE, AND THE ONE GUARDING THE LARGEST BILL.
# Its `set_stage` carries NO detail argument at all, so it advanced its marker
# and reported nothing -- neither rows nor a meaningful action count. Measured at
# 21-06's base commit in the stubbed run: 0 body rows, and the only stage of the
# thirteen whose automatic summary line reports `actions: 0`.
#
# WHAT THE STAGE ACTUALLY DOES. It asks one question -- did every high-stakes
# claim the gates SELECTED come back with a verdict? -- and, if not, it dispatches
# a bounded last-chance re-check. That re-check SPENDS MONEY, and its refusal by
# the skeptic circuit breaker is a degradation the run still reports as
# `completed`. Both were invisible: the re-entry existed only as a `log.warning`
# and the block only as a line in the degradation accumulator.
#
# THE POPULATION IS THE POINT (recipe step h). `check_coverage` is called with
# `selected_only=True` EXPLICITLY, and `pipeline.py`'s comment above that call
# records why: without the intersection, the recorded 4cbb5311 population's 738
# gate-dropped / SKIP_STABLE claims all read as uncovered and this loop fans out
# roughly 2,100 Anthropic sessions against a stage the gates exist to shrink to
# ~150 -- with the budget governor inert and unable to stop it. The dispatch row
# below reports that intersected population, which is why it counts the selected
# claims rather than every distilled one.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Coverage gate"). Not invented here.
_STAGE_COVERAGE = "coverage"

#: `gates.py`'s marker for a claim the gates SELECTED for fact-checking. The
#: coverage gate's population is exactly these claims, and `pipeline.py` counts
#: bucket 3 with the identical predicate -- so the row and the funnel agree by
#: construction rather than by coincidence.
_STRICT_VERIFY = "VERIFY"


def _coverage_selected(claims: Any) -> int:
    """How many claims the gates SELECTED for verification.

    CALLED ONLY FROM INSIDE A build() THUNK (through `_coverage_dispatch_event`).
    This is a walk over model-shaped claim dicts, and recipe step (h) is the
    reason it is here rather than at the call site: the honest number needs the
    walk, and the walk needs the emitter's try.
    """
    total = 0
    for claim in claims or []:
        if (claim.get("gate") or {}).get("strict") == _STRICT_VERIFY:
            total += 1
    return total


def _coverage_dispatch_event(claims: Any, adjudications: Any) -> tuple[str, dict]:
    """Compose the coverage gate's opening row. CALLED ONLY FROM INSIDE A build()
    THUNK."""
    selected = _coverage_selected(claims)
    checked = len(adjudications or {})
    return (
        f"Checking that every claim the gates selected came back with a verdict "
        f"— {selected} selected, {checked} with a verdict so far",
        {"items": selected},
    )


def emit_coverage_dispatch(run_id: Any, *, claims: Any, adjudications: Any) -> None:
    """The coverage gate's opening header — the question, and over WHICH claims.

    THE POPULATION IN THIS ROW IS THE COST TRAP'S GUARD, RENDERED. The gate runs
    with `selected_only=True` deliberately; the alternative is not a slightly
    different number but roughly 2,100 paid Anthropic sessions, because every
    gate-dropped claim would read as uncovered and enter the re-entry fan-out.
    Reporting the SELECTED population is therefore the row's whole content: an
    operator who sees this number diverge from the gate stage's own
    `selected_verify` count is looking at the intersection having come undone.

    Both arguments are the raw pipeline objects, walked inside the thunk. Passing
    a pre-computed `len(claims)` would have been cheaper and would have named the
    wrong population -- see recipe step (h).
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_COVERAGE,
        kind="dispatch",
        build=lambda: _coverage_dispatch_event(claims, adjudications),
    )


def emit_coverage_reentry(
    run_id: Any, *, attempt: Any, max_attempts: Any, uncovered: Any
) -> None:
    """A last-chance re-check is being DISPATCHED — and it is being paid for.

    `plan`, not `thinking`: a re-entry is a ROUTING decision, which is what that
    kind's own comment in `RUN_EVENT_KINDS` names ("branch -- routing /
    planning"), and it is the same kind the gate stage's drop rows use for the
    same reason.

    THIS ROW IS A MONEY SIGNAL AND IS KEPT ON THOSE GROUNDS (D-13, as amended by
    the operator on 2026-08-10: where a line is both a money signal and
    commentary, money wins). Until now this dispatch existed ONLY as a
    `log.warning` — so a run that quietly re-checked a batch of claims, and paid
    for it, looked on the page exactly like one that did not.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_COVERAGE,
        kind="plan",
        build=lambda: (
            f"Coverage gate FAILED — dispatching re-check {attempt} of "
            f"{max_attempts} for {uncovered} claim(s) that came back without a "
            f"verdict; this re-check is paid for",
            {"items": uncovered, "attempt": attempt, "max": max_attempts},
        ),
    )


def emit_coverage_blocked(run_id: Any, *, reason: Any) -> None:
    """The re-check was REFUSED by the skeptic circuit breaker.

    THE REASON IS CARRIED VERBATIM, NOT PARAPHRASED. `_coverage_reentry_pass`
    composes a sentence written for a human — it names how many claims were not
    re-checked, that the provider's circuit is open, and that their supporting
    passages ship unexamined — and `pipeline.py` hands that same string to the
    run's ONE degradation accumulator. This row puts the identical words on the
    page, so the feed and the degradation notice cannot drift into two accounts
    of one loss.

    `agent_fail` is the honest kind: work that should have happened did not.
    A blank reason emits nothing (`_sentence_or_none`) rather than an empty row.
    """
    sentence = _sentence_or_none(reason)
    if sentence is None:
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_COVERAGE,
        kind="agent_fail",
        build=lambda: (sentence, None),
    )


def emit_coverage_done(
    run_id: Any, *, passed: Any, uncovered: Any, reentries: Any
) -> None:
    """The coverage gate's verdict on itself.

    A PASS AND A FAIL READ DIFFERENTLY, and both are stated: a gate that only
    spoke up when it failed would leave an operator unable to tell "this run was
    fully covered" from "this stage is broken again".
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_COVERAGE,
        kind="thinking",
        build=lambda: (
            (
                f"Coverage satisfied — every selected claim came back with a "
                f"verdict after {reentries} re-check(s)"
                if passed
                else f"Coverage NOT satisfied — {uncovered} selected claim(s) "
                f"still have no verdict after {reentries} re-check(s); their "
                f"passages ship unexamined"
            ),
            {"items": uncovered, "actions": reentries},
        ),
    )


# ===========================================================================
# `conflict` -- Conflict detection.
#
# THE HORIZONTAL AXIS. The skeptic checks each claim against the WEB (is it
# true?); this stage checks the survivors against EACH OTHER (do two grounded
# claims contradict?). Where one side is clearly weaker it is dropped and later
# scrubbed out of the research; where neither is, the pair becomes a
# `contested_note` the synthesiser must present as an open disagreement.
#
# THOSE TWO OUTCOMES ARE NOT THE SAME EVENT AND MUST NOT READ AS ONE. A RESOLVED
# conflict means the report lost a claim -- the same consequence as a fact-check
# drop, arrived at differently, and stamped `lost_conflict` rather than
# `failed_factcheck` in the rejected-claims ledger. A CONTESTED conflict means
# the report KEEPS BOTH SIDES and says so. An operator reading "conflict found"
# with no more detail cannot tell which of those happened, and they are opposite
# outcomes for the delivered report.
#
# The shape read here is `synthesis/steps.py::conflict_detector`'s own normalised
# dict: `claims` (indices), `tension`, `loser` (int | None), `contested` (bool),
# `note`.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Conflict detection"). Not invented here.
_STAGE_CONFLICT = "conflict"

#: `pipeline.py::rejected_claims`' literal for the weaker side of a conflict.
_REASON_CONFLICT = "lost_conflict"


def _conflict_finding_event(conflict: Any) -> tuple[str, dict[str, Any]]:
    """Compose ONE detected contradiction's row. CALLED ONLY FROM INSIDE A
    build() THUNK.

    THE CONTESTED TEST IS `pipeline.py`'S OWN, not a second interpretation of the
    same dict: that file classifies with `conflict.get("contested") or
    conflict.get("loser") is None`, and a row that used a different test would
    eventually describe a conflict as resolved while the pipeline treated it as
    contested. Every field is model-authored, which is exactly the input class
    rule 3 keeps inside the emitter's try.
    """
    contested = bool(conflict.get("contested")) or conflict.get("loser") is None
    tension = clip_claim(conflict.get("tension") or conflict.get("note"))
    detail = tension or "(no explanation returned)"
    if contested:
        return (
            f"Contradiction UNRESOLVED — both sides ship, presented as an open "
            f"disagreement: {detail}",
            {"sub": "contested"},
        )
    return (
        f"Contradiction resolved — the weaker side is dropped from the report: "
        f"{detail}",
        {"sub": _REASON_CONFLICT},
    )


def emit_conflict_dispatch(run_id: Any, *, survivors: Any, reconciliations: Any) -> None:
    """The conflict stage's opening header."""
    run_events.emit_safe(
        run_id,
        stage=_STAGE_CONFLICT,
        kind="dispatch",
        build=lambda: (
            f"Checking {survivors} verified claim(s) against each other for "
            f"contradictions — {reconciliations} group reconciliation(s) carried "
            f"in from verification",
            {"items": survivors},
        ),
    )


def emit_conflict_finding(run_id: Any, budget: RowBudget, *, conflict: Any) -> None:
    """One contradiction the detector found, AND WHICH WAY IT WENT.

    Takes the RAW conflict dict; every read happens inside the thunk. Bounded
    like every per-item site.
    """
    if not budget.take():
        return
    run_events.emit_safe(
        run_id,
        stage=_STAGE_CONFLICT,
        kind="thinking",
        build=lambda: _conflict_finding_event(conflict),
    )


def emit_conflict_done(
    run_id: Any, *, losers: Any, contested: Any, survivors: Any
) -> None:
    """The conflict stage's closing line — what it cost the report, in claims.

    `survivors` is the count AFTER any losers were removed, which is the number
    the synthesis stage is about to write from, so the two stages' rows reconcile
    by reading them in order.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_CONFLICT,
        kind="thinking",
        build=lambda: (
            f"{losers} claim(s) dropped as the weaker side of a contradiction · "
            f"{contested} open disagreement(s) carried into the report · "
            f"{survivors} claim(s) go forward to synthesis",
            {"items": survivors, "actions": losers},
        ),
    )


# ===========================================================================
# `synthesize` -- Final synthesis.
#
# TWO CALL SITES IN TWO SCOPES, AND THE SECOND ONE IS WHY A RESUMED RUN IS
# VISIBLE AT ALL. One site is inside `_run_staged`'s closure; the other is inside
# the MODULE-LEVEL `_write_final_report`, which is ALSO the resume path's entry
# point -- `run()` calls it directly from the synthesis cache. On a resumed run
# the closure never executes, so the row emitted from `_write_final_report` is
# the ONLY synthesize row there will be. `pipeline.py`'s comment above that
# function records why it is deliberately not re-plumbed through the closure, and
# the same judgement applies here: it calls this module directly.
#
# SUBTRACTIVE VERIFICATION, MADE VISIBLE. `pipeline.py` explains that synthesis
# runs on the FULL research prose -- so no information is lost to a claim cap --
# but that every passage stating or depending on a discredited claim is
# physically removed from that prose first. That removal is the mechanism which
# makes the whole Tribunal actually stick to the delivered report, and nothing
# has ever shown it happening.
# ===========================================================================

#: The stage key, exactly as `ENGINE_STAGES["tribunal"]` declares it
#: (`runs/stages.py`, label "Final synthesis"). Not invented here.
_STAGE_SYNTHESIZE = "synthesize"


def emit_synthesize_dispatch(run_id: Any, *, survivors: Any) -> None:
    """The synthesis stage's opening header."""
    run_events.emit_safe(
        run_id,
        stage=_STAGE_SYNTHESIZE,
        kind="dispatch",
        build=lambda: (
            f"Writing the report from {survivors} verified claim(s)",
            {"items": survivors},
        ),
    )


def emit_synthesize_scrubbed(run_id: Any, *, removed: Any, reports: Any) -> None:
    """The discredited claims have been CUT OUT of the research prose.

    THE ROW THAT SHOWS SUBTRACTIVE VERIFICATION WORKING. Everything upstream --
    the gates, the skeptics, adjudication, conflict resolution -- only matters to
    the delivered report through this step: a claim that was refuted but whose
    passage survived into the prose would ship anyway. The count is the claims
    the run discredited; the reports count is the streams they were removed from.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_SYNTHESIZE,
        kind="thinking",
        build=lambda: (
            f"Removed every passage depending on {removed} discredited claim(s) "
            f"from {reports} research stream(s) before writing",
            {"items": removed, "actions": reports},
        ),
    )


def emit_synthesize_writing(
    run_id: Any, *, ledger: Any, numbered: Any, resumed: Any
) -> None:
    """The report is being written, and from WHAT.

    WHY THIS SECOND ROW EXISTS, AND WHY IT IS NOT A DUPLICATE. It is emitted from
    the module-level `_write_final_report`, which is the RESUME path's entry
    point. On a resumed run — `run()` loading a cached bundle and writing the
    report from it — the `_run_staged` closure never executes, so
    `emit_synthesize_dispatch` and `emit_synthesize_scrubbed` never fire and THIS
    IS THE ONLY SYNTHESIZE ROW THE FEED WILL EVER GET. An operator watching a
    resumed run would otherwise see "Final synthesis" as a heading with nothing
    under it, on the one path where they are most likely to be watching because
    something already went wrong.

    `resumed` is supplied by the CALLER because the function genuinely cannot
    tell: the same bundle shape arrives from the live pipeline and from the
    synthesis cache. Guessing from the bundle's contents would be a heuristic
    that reads as fact on the page.
    """
    run_events.emit_safe(
        run_id,
        stage=_STAGE_SYNTHESIZE,
        kind="thinking",
        build=lambda: (
            (
                "Resuming from cached research — writing the final report from "
                f"{ledger} verified fact(s) and {numbered} numbered source(s)"
                if resumed
                else f"Writing the final report from {ledger} verified fact(s) "
                f"and {numbered} numbered source(s)"
            ),
            {"items": ledger},
        ),
    )
