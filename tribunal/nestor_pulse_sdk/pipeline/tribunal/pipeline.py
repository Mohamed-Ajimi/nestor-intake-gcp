"""TribunalPipeline — Plan 01-15 Task 2.

Full assembly of the ADR-006 adaptive-effort SDK engine (Plans 01-13/14/15):
  intake -> hybrid research -> distill -> triage -> skeptics -> adjudicate
  -> coverage+quality gate -> persist (fine-grained) -> final synthesis

Runner protocol (matches nestor_pulse_sdk/runs/adapter.py:42):
    async def run(*, brief: str, run_id: uuid.UUID, tenant_id: uuid.UUID) -> dict

Critical constraints (from .continue-here.md):
  1. ALL LLM calls go through AuditedLLMClient — no direct provider client construction.
  2. This is a hand-written async Python loop — NOT the agent SDK query() entry point.
  3. persist_tribunal_claims (NOT extract_and_persist_citations) is the persistence path.
  4. Wired behind NESTOR_SDK_ORCHESTRATOR=tribunal in dispatch_runner('sdk').
  5. No modifications to nestor_pulse/ (D-01 invariant).

Return dict shape:
    {
        "output_text":        str,       # final synthesis over survivors
        "claim_count":        int,       # number of survivor claims persisted
        "verdict":            dict,      # quality gate Verdict.as_dict()
        "verification_report": dict,     # AUDIT-ONLY (no UI change in Phase 1)
        "verification_summary": dict,    # the 15.1 funnel — the WORKER persists this
                                         # onto run.verification_summary in the same
                                         # transaction that sets status='completed'
                                         # (plan 15.1-08 / G-10). Same 13-key shape on
                                         # every path, including the zero-claim one.
    }

Stage 1 is the QUESTION WORKSHOP (plan 15.2-13, D-03): orientation -> candidates
-> cluster -> critique -> Swiss tournament -> evolve. It takes the client-validated
questions and sharpens them into ranked sub-questions, which become the run's
research angles. It may add DEPTH inside a question; it never changes SCOPE (D4) —
the report's per-focus-area sections are still keyed by the client's own labels.

The single-LLM-call intake that used to be Stage 1 is now UNREFERENCED FROM THIS
MODULE AND DELIBERATELY RETAINED (D-03) — see the comment above the import block
for the exact symbol, the rollback recipe and who owns its deletion. There is no
feature flag and no dual-run: the workshop is the only Stage 1.
``intake.detect_explicit_questions`` is NOT part of that retirement — it is pure,
deterministic Python and stays in use as the fallback source of client-validated
question labels.

The ``needs_clarification`` / ``clarifying_questions`` keys survive only as
vestigial shape (the ``/answer`` endpoint + worker parking still exist), never
populated by this pipeline.

T-15-03 mitigation: dispatch_runner fails safe — any NESTOR_SDK_ORCHESTRATOR value
other than exactly 'tribunal' returns the thin SDKPipeline control; this pipeline
is only instantiated when the flag is exactly 'tribunal'.

T-15-04 accept: verification_report is audit-only this phase; no runs/schemas.py or
Report.jsx change — UI surfacing deferred to Phase 2 per ADR-006 open question.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING

# D-03, THE WHOLE OF IT, IN ONE PLACE.
#
# `intake.adaptive_intake` is NO LONGER IMPORTED HERE — the question workshop
# (`workshop_rank.run_question_workshop`) is Stage 1 now. The function is NOT
# deleted: `intake.py` is byte-unchanged and `adaptive_intake` is still defined,
# importable and syntactically live.
#
# ROLLBACK RECIPE, if the August live run says the workshop is worse: restore
# this import, put the `adaptive_intake(...)` call back in place of the
# `run_question_workshop(...)` block in Stage 1, and pass no `winners=` to
# `divide()`. That is the entire change — one wiring edit, no restored code, no
# migration. Deletion of the function itself is plan 15.2-18's separate V-03
# commit, after sign-off.
#
# `detect_explicit_questions` is a DIFFERENT thing and survives in use: it is
# pure, deterministic Python, not the LLM call D-03 retires.
from nestor_pulse_sdk.pipeline.tribunal.intake import detect_explicit_questions
# D-G (plan 15.2-21): the pure, never-raising split of a seam brief into the
# client's QUESTIONS, the client's DECISION and everything else as CONTEXT. It is
# what stops `detect_explicit_questions` from ever being handed a brief that
# already has a question block — see this module's Stage 1 and the parser's own
# docstring for the incident that made it necessary.
from nestor_pulse_sdk.pipeline.tribunal.brief_input import parse_brief
from nestor_pulse_sdk.pipeline.tribunal.workshop_rank import run_question_workshop
from nestor_pulse_sdk.pipeline.tribunal.research_division import (
    run_angles,
    divide,
    build_mission_brief_from_winners,
    # THE SINGLE SOURCE OF STREAM ORDERING, imported for its LENGTH only. The feed
    # header has to be able to say "all three streams" without retyping 3, and
    # `_D6_STREAMS` is documented as the one place that number lives. Only `len()`
    # is read — never the member names — so this stays a PROPERTY assertion and not
    # the exact-set trap that turned phase 15.5's merged tree red.
    _D6_STREAMS,
)
# Imported AS A MODULE at file scope, deliberately. `discovery_bracket` imports only
# `logging`, `os` and `typing`, so there is no cycle to dodge and none of the
# function-local import idiom this file uses for `strip_unresolved_cite_markers` is
# needed. Module form (not `from ... import annotate_conflicts`) keeps the call site
# readable as "the discovery bracket decided this", which is what it is.
from nestor_pulse_sdk.pipeline.tribunal import discovery_bracket
from nestor_pulse_sdk.pipeline.deep_researchers.degraded_parallel import (
    own_stream_unavailable_reason,
    # F6 (plan 15.2-16): the "no angle produced a usable result" signal. It is
    # CAUGHT here and turned into park FACTS; the two raise sites in
    # research_division.py / degraded_parallel.py are deliberately unchanged.
    InsufficientProvidersError,
)
from nestor_pulse_sdk.runs.stage_feed import StageFeed
# 15.3-03: the run-event emitter (plan 15.3-01). IMPORTED AS A MODULE, never as
# `from ... .run_events import emit`. The module form is what makes the D-06
# call-site gate meaningful: that gate counts qualified calls to the BARE emit
# entry point and requires zero, and a bare `emit(...)` bound by a from-import
# would slip straight past it and rebuild the whole defect while the gate stayed
# green. (This comment states the rule WITHOUT writing that qualified call out,
# because the gate is a grep and a comment matches it just as a call does.)
# Every site below calls `emit_safe`, whose `build`
# thunk moves text/meta construction INSIDE the emitter's try — a caller's
# arguments are evaluated BEFORE the callee is entered, so wrapping the
# emitter's body protects nothing about the f-string that fed it.
from nestor_pulse_sdk.runs import run_events
# 21-03: the feed emitters for the eight stages Phase 15.3 left SILENT — they
# had a divider and a summary but no BODY, so each rendered as a heading with
# nothing under it. Imported in MODULE FORM for the same call-site-gate reason
# stated three lines above, and because the call site then reads as "the verify
# stage said this", which is what it is. Every helper it exposes goes through the
# thunk-taking entry point, so none of them can fail a run.
from nestor_pulse_sdk.pipeline.tribunal import stage_events
# D-R8 (15.8): the per-assignment / per-round yield emitter. Every sqlalchemy and
# db import inside it is FUNCTION-LOCAL by its own design, so this costs nothing
# at module load. Only the `_safe` trio may be called from here — see
# `_assignment_yield_rows` and the two seams in `_run_staged`.
from nestor_pulse_sdk.runs import yield_records
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    # D8/D-14 (15.2-14): the per-stream fact-list collector that REPLACED the
    # whole-corpus `claim_distiller` call as this pipeline's primary claim
    # source. `claim_distiller` is deliberately NO LONGER IMPORTED here — that
    # import WAS the distiller-as-primary-source wiring D-03 unwires. The
    # function itself lives on, with its two test files, as the per-provider
    # fallback INSIDE `collect_provider_facts` (D-15; see its docstring).
    collect_provider_facts,
    # D-R8 (15.8, review CR-01 repair): the two keys `collect_provider_facts`
    # stamps on every `reports` entry, carrying that assignment's PRE-MERGE
    # yield. IMPORTED AS SYMBOLS, not matched as string literals, because the
    # producer and the reader are in different modules and a silently-renamed
    # key here is a NULL column in a run that happens exactly once.
    ANGLE_YIELD_FACT_LIST_PARSED,
    ANGLE_YIELD_RESOLVABLE_SOURCES,
    # The G-12 deduper, imported for the merge stage's deterministic half. A
    # private helper crossing a module boundary already has precedent two
    # imports below (`_FUNNEL_KEYS`), and the alternative — a second deduper —
    # is the exact duplication this phase forbids.
    _dedupe_claims,
    synthesize_report,
    # G-10: the DISPLAY-only facet-key resolver. Same rule as the section
    # headings, spelled once in synthesis.steps.
    relabel_facets,
    # …and the map it is built on. `_gate_decision_context` reads it directly so the
    # claim gate judges materiality against the client's FULL question instead of
    # the 120-char join key (quick task 260806-o96). Prompt text, not a key — the
    # DISPLAY-ONLY contract holds.
    focus_area_questions,
    conflict_detector,
    scrub_research,
    # D-08 (Phase 15.2): the two report sections are rendered by PYTHON from
    # pipeline data and appended AFTER synthesize_report returns, so the writing
    # model never sees them and cannot omit, merge, truncate or rewrite an item.
    # Both are pure — no LLM, no DB, no clock. Append site: _write_final_report.
    build_disputed_and_changed,
    build_could_not_establish,
)
from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
from nestor_pulse_sdk.pipeline.tribunal.grouping import group_claims
# The gate stage (G-01/G-02/G-11) and ITS OWN key list. _FUNNEL_KEYS is imported
# rather than re-typed here so the zero-claim early return and the computed path
# cannot drift apart if gates.py ever gains a key (RESEARCH Pitfall 10).
from nestor_pulse_sdk.pipeline.tribunal.gates import apply_gates, _FUNNEL_KEYS as _GATE_FUNNEL_KEYS
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import run_group_skeptic
from nestor_pulse_sdk.pipeline.tribunal.adjudicate import adjudicate_all
from nestor_pulse_sdk.pipeline.tribunal.coverage_gate import check_coverage, MAX_REENTRY
# Plan 15.2-02's shared reliability primitives. IMPORTED, never extended: there is
# exactly one breaker implementation and one retry policy in this engine. The
# BreakerSet is what gates the coverage re-entry fan-out (D-07-C) — `with_retry` is
# deliberately NOT imported here, because this plan adds no retry policy.
from nestor_pulse_sdk.pipeline.tribunal.reliability import (
    BreakerSet,
    # R4/D-17 (plan 15.2-16). `classify`/`HARD_WALL` decide whether a failure is
    # an account-level wall (park) or an ordinary error (fail); `error_signature`
    # is what makes a park reason SAFE TO DISPLAY — it is already digit-stripped,
    # credential-redacted and truncated, and 15.2-19 renders it into an email.
    HARD_WALL,
    classify,
    error_signature,
    # D-F (plan 15.2-24): the ONE credential/secret redactor in this engine. The
    # stage log's own failure path is the only thing here that touches an
    # exception, and phase rule 8 says anything derived from one is redacted
    # before it is written.
    redact,
)
# R3 (plan 15.2-16): the checkpoint store and its guards. `checkpoints.py` holds
# no database code at all — it is bound to the `_read_output` / `_write_output`
# primitives below, which is what keeps it unit-testable without Postgres.
from nestor_pulse_sdk.pipeline.tribunal.checkpoints import (
    CheckpointStore,
    angles_digest,
    next_park_seq,
    park_signature,
    safe_job_id,
)
from nestor_pulse_sdk.pipeline.tribunal.budget import (
    over_budget,
    budget_marker,
    DEFAULT_MAX_BUDGET_USD,
    BUDGET_BEHAVIOUR,
    SURVIVAL_RULE,
)
from nestor_pulse_sdk.pipeline.synthesis.quality_gate import build_quality_gate
from nestor_pulse_sdk.runs.stages import (
    set_stage,
    raise_if_cancelled,
    RunCancelled,
    # 15.3-03: the fourteen `{key, label}` pairs. The feed's divider carries the
    # LABEL ("Deep research"), never the key ("deep_research") — the labels have
    # existed since Phase 15 and no surface has ever rendered one.
    stages_for,
)
from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY
from nestor_pulse_sdk.citations.extractor import (
    persist_tribunal_claims,
    # D-V01-11: the SAME URL extraction the persistence loop performs, so the
    # pre-pass resolves exactly the set that is about to be upserted.
    _gather_source_urls,
)
from nestor_pulse_sdk.pipeline.synthesis.steps import extract_focus_areas
from nestor_pulse_sdk.db.base import get_sessionmaker

if TYPE_CHECKING:
    from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient

log = logging.getLogger(__name__)

#: Anthropic model for skeptic calls
_SKEPTIC_MODEL = "claude-sonnet-4-6"

# Skeptic-stage guards (added after a sequential-skeptic overnight hang on a broad
# brief). NO claim cap — every claim still gets skeptics — but they run CONCURRENTLY
# with a per-skeptic wall-clock timeout so a hung web_fetch/stream can't stall forever.
_SKEPTIC_CONCURRENCY = int(os.environ.get("NESTOR_TRIBUNAL_SKEPTIC_CONCURRENCY", "8"))
_SKEPTIC_TIMEOUT_S = int(os.environ.get("NESTOR_SKEPTIC_TIMEOUT_S", "300"))
#: Phase 3: verify claims in entity|attribute GROUPS (one skeptic session per group,
#: which also reconciles contradictions) instead of one-by-one. Default ON; set to
#: "false" to fall back to the per-claim path (preserved for A/B baseline).
_GROUP_VERIFY = os.environ.get("NESTOR_TRIBUNAL_GROUP_VERIFY", "true").lower() == "true"

#: ONE thorough group-skeptic session per group. Stakes controls the DEPTH of that
#: single session (max_turns, web_search uses, web_fetch uses), NOT the number of
#: sessions. Under G-02 stakes no longer decides WHETHER a group is checked — the
#: gates do — so this map is the only surviving job stakes has.
#: A single group skeptic that refutes WITH an independent citation is authoritative
#: — adjudicate's majority-independent rule already drops a 1/1 refute-with-source,
#: so no adjudication change is needed.
_GROUP_DEPTH: dict[str, tuple[int, int, int]] = {
    # stakes: (max_turns, max_search_uses, max_fetch_uses)
    "high": (6, 8, 5),
    "med": (4, 5, 3),
    # "low" exists BY DECISION, not by accident (RESEARCH Pitfall 9). Low-stakes
    # groups used to be waved through unchecked, so this map never needed the key.
    # Now the gates let a load-bearing low-stakes claim into the queue, and the
    # `.get(stakes, _GROUP_DEPTH["med"])` fallback below would have silently given
    # it MED depth — quietly eroding the "~6× cheaper" bar this phase is measured
    # against. A shallow tier checks it honestly and cheaply instead.
    "low": (2, 3, 2),
}


# ===========================================================================
# D-F (plan 15.2-24) — THE STAGE LOG.
#
# WHY THIS EXISTS, in one paragraph, because the next person to read it will be
# reading it during an incident. All 72 log lines run d6bb3aae produced between
# 08:09 and 08:53 were either the workshop's own output or angle-failure
# warnings. Not one success marker, not one stage transition. So when the run
# went quiet at 08:41 there was nothing to read, diagnosis fell back to Cloud Run
# CPU metrics, and that produced the confident and WRONG conclusion that the
# pipeline had stalled — it was blocked on long-poll I/O the whole time and
# resumed on its own at 09:07. The lesson, recorded in the withdrawn D-C section
# of 15.2-V01-ABORTED-FINDINGS.md, is that on this engine NEITHER LOG SILENCE NOR
# IDLE CPU IS EVIDENCE OF A STALL. These lines are what make the difference
# readable: the last `stage_enter` line names the stage the run is sitting
# inside, so a long poll is distinguishable from a stall in the log itself.
#
# WHAT MAY APPEAR IN THESE LINES (T-15.2-240): stage keys, run ids, integer
# counts and durations. NOTHING ELSE — no prompt body, no claim text, no
# question, no URL, no provider response, no environment value. That is enforced
# structurally in `_stage_log_line` (every value is rendered through `int()` or a
# key sanitiser), not by reviewer discipline. `pipeline/tribunal/pii.py::scrub_pii`
# — this engine's ONE personal-data redactor, shipped by plan 15.2-23 — is
# deliberately NOT called here, and that is not an omission: no client-derived or
# provider-derived STRING ever reaches these lines, so there is nothing to scrub,
# and calling a redactor on a line built from integers would imply free text was
# expected. If a future edit ever formats a caller-supplied string into a stage
# line, `scrub_pii` is the function to use — do not write a second redactor.
#
# WHY THE STATE IS MODULE-LEVEL. `_write_final_report` is a MODULE-LEVEL function
# and it writes the last two stages of EVERY run (`synthesize`, `done`), so a
# closure living inside `_run_staged` cannot see them. Handing it the closure
# would mean a new parameter threaded through a paid path for the sake of a log
# line. A small run-scoped registry keeps that call graph byte-identical. It is
# bounded (`_STAGE_LOG_MAX_RUNS`) and popped by `_stage_log_close`, which BOTH the
# `done` write and `run()`'s own `finally` call — so a parked, failed or cancelled
# run leaves nothing behind either.
#
# EXCEPTION SAFETY (T-15.2-241). Every public entry point below swallows its own
# failures, inheriting the contract `runs/stages.py::set_stage` already states: a
# progress write must never break the pipeline that is reporting it. A broken
# logger cannot cost a paid run.
# ===========================================================================

#: Hard bound on the registry so an un-closed run can never grow it without limit.
_STAGE_LOG_MAX_RUNS = 64

#: run-id (str) -> the bookkeeping for that run's stage log. See the block above.
_STAGE_LOGS: dict[str, dict[str, Any]] = {}


def _stage_log_key(value: Any) -> str:
    """A stage key reduced to `[a-z0-9_]`, bounded. Never raises, never empty."""
    cleaned = "".join(
        ch for ch in str(value or "").lower() if ch.isalnum() or ch == "_"
    )[:40]
    return cleaned or "unknown"


def _stage_log_items(detail: Any) -> Optional[int]:
    """How many sub-progress rows a `set_stage` detail carried, or None.

    The COUNT only — the rows themselves carry client text and provider prompts
    and must never be logged.
    """
    if isinstance(detail, dict):
        items = detail.get("items")
        if isinstance(items, (list, tuple)):
            return len(items)
    return None


def _stage_log_swallow(exc: BaseException) -> None:
    """Absorb a stage-logging failure. Phase rule 8: redact anything from an exception."""
    try:
        log.debug("tribunal_pipeline: stage log failed — %s", redact(str(exc)))
    except Exception:  # noqa: BLE001 — a logger that cannot log is the end of it
        pass


def _stage_log_state(run_id: Any) -> dict[str, Any]:
    """The registry entry for this run, created on first use."""
    key = str(run_id)
    state = _STAGE_LOGS.get(key)
    if state is None:
        if len(_STAGE_LOGS) >= _STAGE_LOG_MAX_RUNS:
            # Insertion-ordered: drop the oldest entry rather than grow forever.
            _STAGE_LOGS.pop(next(iter(_STAGE_LOGS)), None)
        now = time.monotonic()
        state = {
            "current": None,       # the stage key currently open, or None
            "opened_at": now,      # monotonic() when it was entered
            "items": 0,            # rows on the last detail written to it
            "entered": 0,          # how many stage_enter lines this run emitted
            "counts": {},          # stage key -> {name: int} for its exit line
            "started_at": now,     # monotonic() at the run's first stage write
            # 15.3-03: the last `summary` block seen on the CURRENTLY-OPEN stage's
            # detail, so the feed's per-stage summary line can carry its
            # `items_read` / `cost_usd` when the stage reported them. Reset at
            # every transition. Additive: every reader below uses `.get`, so this
            # key changes nothing about the stage log itself.
            "event_summary": None,
        }
        _STAGE_LOGS[key] = state
    return state


def _stage_log_line(
    event: str,
    run_id: Any,
    stage_key: Any = None,
    *,
    seconds: Any = None,
    items: Any = None,
    **counts: Any,
) -> None:
    """Emit ONE stage line, in the ONE shape every stage line in this module uses.

    COUNTS, KEYS, IDS AND DURATIONS ONLY (T-15.2-240). Every count is rendered
    through `int()` and every name through `_stage_log_key`, so a value that is
    not an integer is DROPPED rather than stringified into the log. `time.monotonic`
    is the clock everywhere, never the wall clock, so a clock step cannot produce
    a negative duration.

    Also the ONE place `entered` is incremented, so the closing summary counts
    both the closure-driven transitions and the two explicit spans below.
    """
    try:
        parts: list[str] = []
        if stage_key is not None:
            parts.append(f"stage={_stage_log_key(stage_key)}")
        if seconds is not None:
            parts.append(f"seconds={max(0.0, float(seconds)):.1f}")
        if items is not None:
            parts.append(f"items={int(items)}")
        for name in sorted(counts):
            value = counts[name]
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            parts.append(f"{_stage_log_key(name)}={int(value)}")
        if event == "stage_enter":
            _stage_log_state(run_id)["entered"] += 1
        log.info(
            "tribunal_pipeline %s: %s",
            _stage_log_key(event), " ".join(parts),
            extra={"run_id": str(run_id)},
        )
    except Exception as exc:  # noqa: BLE001 — T-15.2-241
        _stage_log_swallow(exc)


def _stage_log_counts(run_id: Any, stage_key: str, **counts: int) -> None:
    """Record integer counts to be reported on `stage_key`'s exit line.

    Called at the four places the pipeline already HAS the numbers an operator
    asks of a silent run — how many angles went out and came back, how many
    claims the gates selected, how many verification sessions ran. Nothing is
    computed here that the pipeline did not already compute for itself.
    """
    try:
        _stage_log_state(run_id)["counts"].setdefault(stage_key, {}).update(counts)
    except Exception as exc:  # noqa: BLE001 — T-15.2-241
        _stage_log_swallow(exc)


def _stage_log_exit(run_id: Any, state: dict[str, Any]) -> None:
    """Close the currently-open stage: one `stage_exit` line with its counts."""
    stage_key = state.get("current")
    if stage_key is None:
        return
    state["current"] = None
    _stage_log_line(
        "stage_exit",
        run_id,
        stage_key,
        seconds=time.monotonic() - float(state.get("opened_at") or time.monotonic()),
        items=state.get("items") or 0,
        **(state.get("counts") or {}).pop(stage_key, {}),
    )


# ===========================================================================
# 15.3-03 — THE FEED'S SPINE, riding the SAME transition choke point.
#
# `_stage_log_transition` below is the ONE place this engine decides that a run
# has actually LEFT one stage and ENTERED another, and it already owns the two
# things a feed divider and a stage summary need: the outgoing stage key and the
# monotonic clock it was opened at. So the run-event emits ride it rather than
# the `set_stage` shim in `_run_staged`.
#
# WHY THE TRANSITION FUNCTION AND NOT THE SHIM. The shim covers every stage
# boundary the STAGED BODY crosses, but it is not the only caller here:
# `_write_final_report` is a MODULE-LEVEL function and calls this transition
# directly for `synthesize` and `done` (see its two call sites). Emitting from
# the shim alone would leave the last two stages of every run with no divider and
# no summary — the feed would simply stop before the report was written, which is
# precisely the "goes quiet and you cannot tell why" defect this phase exists to
# end. One edit here covers all three call sites; three edits would be three
# chances to miss one.
#
# NOTHING HERE MAY RAISE INTO THE PIPELINE. Both helpers are called from inside
# an existing `try/except Exception` (T-15.2-241), AND every value they derive is
# built inside an `emit_safe(build=...)` thunk, so a malformed state dict or an
# absent summary block costs the LINE and never the run (D-06). The two layers
# are not redundant: the outer try covers the bookkeeping, the thunk covers the
# f-string, and neither one covers the other.
# ===========================================================================


def _stage_event_label(stage_key: Any) -> str:
    """The stage's HUMAN LABEL, falling back to the raw key.

    `ENGINE_STAGES["tribunal"]` has carried a label for all fourteen stages since
    Phase 15 and no surface has ever rendered one — `ResearchRunProgress` shows
    `Current phase: deep_research`. The divider is where that ends. A key with no
    schema entry (`done`, or a stage added ahead of its declaration) falls back to
    the key rather than to an empty line.
    """
    key = str(stage_key)
    for entry in stages_for("tribunal"):
        if entry.get("key") == key:
            return str(entry.get("label") or key)
    return key


def _stage_event_worked(seconds: Any) -> str:
    """`8s` / `12m 24s` / `1h 05m` — the design's `Worked for X` register."""
    total = max(0, int(round(float(seconds))))
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _stage_event_summary_meta(state: dict[str, Any]) -> dict[str, Any]:
    """The `summary` line's meta. CALLED ONLY FROM INSIDE AN `emit_safe` THUNK.

    Every read below is deliberately a direct subscript or a float/int coercion
    over run-scoped bookkeeping that a defect elsewhere could leave malformed.
    That is safe here and ONLY here: this function runs inside the emitter's try,
    so a `KeyError` or a `ValueError` drops the summary line and leaves the run
    untouched. Do NOT hoist a call to it above an `emit_safe`.
    """
    meta: dict[str, Any] = {
        "worked": _stage_event_worked(time.monotonic() - float(state["opened_at"])),
        "actions": int(state["items"] or 0),
    }
    summary = state.get("event_summary")
    if isinstance(summary, dict):
        if summary.get("items_read") is not None:
            meta["items"] = int(summary["items_read"])
        if summary.get("cost_usd") is not None:
            meta["cost"] = float(summary["cost_usd"])
    return meta


def _stage_event_note_summary(state: dict[str, Any], detail: Any) -> None:
    """Remember a `summary` block reported on the currently-open stage."""
    if isinstance(detail, dict) and isinstance(detail.get("summary"), dict):
        state["event_summary"] = dict(detail["summary"])


def _stage_event_boundary(
    run_id: Any, state: dict[str, Any], stage_key: Optional[str]
) -> None:
    """Close the outgoing stage with a `summary`, open the next with a `divider`.

    SUMMARY FIRST, DIVIDER SECOND, so replaying the events reads exactly as the
    design's timeline does: work, then the stage's own summary, then the next
    stage's label. `stage_key=None` is the run's LAST boundary (from
    `_stage_log_close`) — the final stage still gets its summary and no divider
    is opened for a stage that will never run.
    """
    outgoing = state.get("current")
    if outgoing is not None:
        run_events.emit_safe(
            run_id,
            stage=outgoing,
            kind="summary",
            # `text` is empty BY DESIGN: the design of record renders a summary
            # line entirely from `worked / actions / items / cost`
            # (ResearchRunImproved.tsx, every `kind:"summary"` entry).
            build=lambda: ("", _stage_event_summary_meta(state)),
        )
    state["event_summary"] = None
    if stage_key is not None:
        run_events.emit_safe(
            run_id,
            stage=stage_key,
            kind="divider",
            build=lambda: (_stage_event_label(stage_key), None),
        )


def _stage_log_transition(run_id: Any, stage_key: str, detail: Any = None) -> None:
    """Record a stage write; emit exit+entry lines only on a real TRANSITION.

    ENTRY IS PER TRANSITION, NOT PER WRITE. The pipeline re-reports the same
    stage key repeatedly — `intake` is written twice (once bare, once with the
    resolved research plan) and `deep_research` is re-written on every angle
    callback — so an entry line per write would emit dozens of them per run and
    drown exactly the signal this exists to give. A re-report only refreshes the
    row count carried on the eventual exit line.
    """
    try:
        state = _stage_log_state(run_id)
        n_items = _stage_log_items(detail)
        if state.get("current") == stage_key:
            if n_items is not None:
                state["items"] = n_items
            # A RE-REPORT IS NOT A BOUNDARY. `deep_research` is re-written on
            # every angle callback; a divider per write would emit dozens per run
            # and destroy the grouping the design exists to show. Only the
            # summary's own inputs are refreshed here.
            _stage_event_note_summary(state, detail)
            return
        # 15.3-03: BEFORE `_stage_log_exit`, which pops this stage's counts and
        # is where a corrupt `opened_at` would abort the rest of this function.
        # The feed's summary/divider pair is the thing an operator watches, so it
        # goes first and cannot be lost to bookkeeping that fails afterwards.
        _stage_event_boundary(run_id, state, stage_key)
        _stage_log_exit(run_id, state)
        state["current"] = stage_key
        state["opened_at"] = time.monotonic()
        state["items"] = n_items or 0
        _stage_event_note_summary(state, detail)
        _stage_log_line("stage_enter", run_id, stage_key, items=state["items"])
    except Exception as exc:  # noqa: BLE001 — T-15.2-241
        _stage_log_swallow(exc)


def _stage_log_close(run_id: Any) -> None:
    """Close the run's stage log: the last exit line, then ONE summary line.

    `run_stages_complete` is the line an operator greps to answer "did this run
    get anywhere at all" — it names how many stages were entered and how long the
    whole staged body took. Idempotent: the registry entry is POPPED, so the
    `done` write and `run()`'s `finally` can both call this and only the first
    one speaks.
    """
    try:
        state = _STAGE_LOGS.pop(str(run_id), None)
        if state is None:
            return
        # 15.3-03: the LAST stage of the run gets its summary line here and
        # nowhere else — there is no next transition to close it. No divider:
        # nothing follows. Idempotent for the same reason this function is (the
        # registry entry is already popped).
        _stage_event_boundary(run_id, state, None)
        _stage_log_exit(run_id, state)
        _stage_log_line(
            "run_stages_complete",
            run_id,
            seconds=time.monotonic() - float(state.get("started_at") or time.monotonic()),
            stages=int(state.get("entered") or 0),
        )
    except Exception as exc:  # noqa: BLE001 — T-15.2-241
        _stage_log_swallow(exc)


def _group_passes(stakes: str) -> int:
    """Sessions for a group: 1 for med/high, 0 for low (wave through).

    RETAINED AS THE A/B REFERENCE ONLY — as of 15.1/G-02 this is NO LONGER the
    selector. Returning 0 for every low-stakes group is exactly the hidden second
    filter this phase removed: those claims were never checked and nothing in the
    report said so. `_group_selected()` — driven by the gate result — decides what
    gets checked now. Kept so the old rule stays readable beside the new one.
    """
    return 0 if stakes == "low" else 1


def _group_selected(group: dict[str, Any]) -> bool:
    """True when ANY member claim survived the gates as VERIFY (G-04 step 3).

    The cluster is the unit of WORK (one skeptic session reconciles the whole
    entity|attribute cluster at once), but the gate decision is per claim. So a
    cluster is worth a session as soon as one member is worth checking — checking
    a load-bearing claim would otherwise be skipped because it happened to be
    clustered with stable, notorious ones.

    A group with no selected member is skipped, and that skip is NOT a bucket-3
    event: those claims were deliberately gated out with a named reason and are
    already counted in bucket 2 (not_falsifiable / not_load_bearing / both /
    stable_known_fact).
    """
    for claim in group.get("claims") or ():
        if (claim.get("gate") or {}).get("strict") == "VERIFY":
            return True
    return False


def _group_corroboration(group: dict[str, Any]) -> int:
    """How many DISTINCT researchers found this cluster's facts (G-12 `found_by`)."""
    providers: set[str] = set()
    for claim in group.get("claims") or ():
        for provider in claim.get("found_by") or ():
            if provider:
                providers.add(str(provider))
    return len(providers)


def _corroboration_order(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Queue order: LOWEST corroboration FIRST (G-04 step 4, decision D9).

    The direction is counter-intuitive and deliberate. A fact that only ONE
    researcher found is the one most likely to be wrong and the one no other
    source can back up, so it goes to the head of the queue; a fact three
    researchers independently reported is the safest thing to leave until last.
    This matters because the budget governor truncates the queue from the TAIL —
    so what survives an early cap must be the checks that were worth most.

    Ties keep their original index, so the order is deterministic run to run.
    """
    return [g for _, _, g in sorted(
        ((_group_corroboration(g), i, g) for i, g in enumerate(groups)),
        key=lambda t: (t[0], t[1]),
    )]


#: How much of the client's brief is handed to the gates as `decision_context`.
#: "Load-bearing" is only meaningful relative to a decision, so the gate must see
#: one — but the brief is CLIENT-TYPED TEXT going verbatim into a prompt that also
#: carries `gates._GATE_BATCH` (40) claims, so it is bounded here for two reasons,
#: neither of which is the one this comment used to give:
#:
#:   1. DILUTION — an unbounded brief would dominate the prompt and the 40 claims
#:      it is supposed to be judging would become the minority of the input;
#:   2. INJECTION SURFACE — unbounded client text in a prompt is exactly what this
#:      codebase bounds everywhere else (T-15.2-60, `_SUBQ_CHARS`, `_QUESTION_MAX_CHARS`).
#:
#: ⛔ THE OLD JUSTIFICATION WAS WRONG AND IS CORRECTED HERE RATHER THAN CARRIED.
#: It read "a long brief would crowd the claims out of the 4096-token gate budget".
#: That 4096 is `max_output_tokens` (`gates.py:_make_config`) — the cap on what the
#: model WRITES BACK. Input text cannot consume an output budget. The bound is
#: still right; the stated mechanism was not, and a reader sizing this constant
#: against 4096 would size it against the wrong number.
#:
#: ⚠ THIS CAP AND `gates._CONTEXT_MAX_CHARS` SIT IN SERIES: this one truncates
#: first, that one truncates the same string AGAIN. Raising this above that one has
#: NO OBSERVABLE EFFECT — it changes the number, produces no change in behaviour,
#: and reads as "the cap was not the problem". They move together; a test asserts
#: the ordering so the trap cannot silently return.
#:
#: 1200 -> 4000 (quick task 260806-o96). At 1200 this never bound: measured on run
#: 368ff3a0, all 7 gate calls carried an identical 576-char context (216 overhead +
#: 3 x `workshop._LABEL_MAX_CHARS`). It becomes LIVE the moment the labels stop
#: being truncated — three FULL client questions measure 1165, which fits 1200 by
#: only 35 characters, and FOUR measure ~1484, which does not. The intake admits up
#: to five questions.
_GATE_DECISION_CONTEXT_CHARS = int(
    os.environ.get("NESTOR_TRIBUNAL_GATE_BRIEF_CHARS", "4000")
)

#: Skeptic sessions per SELECTED claim in the per-claim A/B fallback branch
#: (NESTOR_TRIBUNAL_GROUP_VERIFY=false). Flat by design: under G-02 the gate
#: decides whether a claim is checked at all, so this is a depth knob and no
#: longer the stakes-derived selector triage.py used to supply.
_PER_CLAIM_SKEPTICS = 2

#: Cost ceiling (USD) the budget governor enforces across the skeptic fan-out.
_MAX_BUDGET_USD = float(
    os.environ.get("NESTOR_TRIBUNAL_MAX_BUDGET_USD", str(DEFAULT_MAX_BUDGET_USD))
)

#: How many `[SUPERSEDED]` caveats may be merged into contested_notes (CR-01).
#: This cap exists to BOUND THE SYNTHESIS PROMPT, not to hide anything: when it
#: truncates, the drop is logged at WARNING with the exact count (fail-loud rule),
#: never silently shortened.
_SUPERSEDED_NOTE_CAP = 40

#: Claim text kept in a `[SUPERSEDED]` line before truncation. Long enough to
#: identify the claim, short enough that 40 caveats cannot dominate the prompt.
_SUPERSEDED_CLAIM_CHARS = 120


def _gate_decision_context(mission_brief: dict[str, Any]) -> str:
    """The client's decision, in words, for the gates' load-bearing test.

    A claim is "load-bearing" only relative to a decision — the blind experiment
    that produced the recorded 456/424 numbers judged materiality against "the
    LUKOIL BeNeLux dynamic-pricing report", not in the abstract. So the gate is
    handed the sharpened research prompt plus the client's questions.

    ⛔ IT USED TO BE HANDED THE 120-CHARACTER JOIN KEYS, AND THAT IS WHAT THIS
    FUNCTION NOW FIXES. `focus_area` is `normalise_questions`' prefix of the
    client's question, built to be a stable dict key — and it was being pasted into
    the prompt as if it were the question. Measured on run 368ff3a0 (all 7 gate
    calls, identical): the gate's TEST 2 — "does the client's decision actually turn
    on this claim?" — was answered against three questions cut MID-WORD, reading
    "...hoe wordt dit operat", "...op koff", "...in de retailmar". Every KEEP/DROP
    decision in that run was made against half-sentences.

    ONE RESOLVER, NOT A SECOND COPY. `synthesis.steps.focus_area_questions` already
    maps label -> full question off `focus_areas[*].research_prompt`, using the CR-08
    prefix rule, and `pipeline.py` already imports from that module for exactly this
    reason (see the `relabel_facets` call site). Writing a second mapper here would
    put a second copy of the 120 in the tree.

    ⚠ THAT RESOLVER IS DOCUMENTED "DISPLAY ONLY — the label stays the join key
    everywhere it is a key", so state plainly why this is not a violation: the gate
    decision context is PROMPT TEXT. Nothing is keyed, joined or stored by it. The
    label remains the key in `claims_per_facet`, in `extract_focus_areas`, and in
    `assignment_identity` — all untouched. This is a read path, which is precisely
    what that resolver exists to serve.

    Bounded by _GATE_DECISION_CONTEXT_CHARS — see that constant for the two real
    reasons, for the corrected 4096 claim, and for the in-series relationship with
    `gates._CONTEXT_MAX_CHARS`.
    """
    parts: list[str] = []
    prompt = (mission_brief.get("deep_research_prompt") or "").strip()
    if prompt:
        parts.append(prompt)
    # `or {}` is the never-raises guard the resolver already promises; spelled here
    # so a future edit to it cannot make this function raise inside the gate stage.
    full_by_label = focus_area_questions(mission_brief) or {}
    questions = []
    for fa in (mission_brief.get("focus_areas") or []):
        label = (fa.get("focus_area") or "").strip()
        if not label:
            continue
        # FALL BACK TO THE LABEL, never to nothing. A brief with no
        # `research_prompt` (an intake.py-built brief, a question-less brief) yields
        # `{}` from the resolver, and a truncated question is still far better than
        # handing the gate no decision context at all — which is the branch
        # `gates._render_decision_context` has to paper over.
        questions.append(full_by_label.get(label, label))
    if questions:
        parts.append("Focus areas: " + " · ".join(questions))
    return "\n".join(parts).strip()[:_GATE_DECISION_CONTEXT_CHARS]


#: WR-10 / D-10 Option 2 — the four reason keys an incidental check is attributed
#: to. Order is the allocation order used by the clamp in `_build_funnel`, so a
#: malformed count is truncated deterministically rather than arbitrarily.
_INCIDENTAL_REASON_KEYS = (
    "checked_incidentally_not_falsifiable",
    "checked_incidentally_not_load_bearing",
    "checked_incidentally_both",
    "checked_incidentally_stable",
)

#: D-12 caps for a single degradation reason and for the list as a whole. Both are
#: load-bearing rather than cosmetic: the funnel is rendered by a GENERIC chip
#: renderer on the superadmin surface (VerificationReport.tsx walks
#: Object.entries(report.funnel)), so an unbounded list becomes one unreadable
#: chip — and an unbounded STRING is how a prompt body or a provider response
#: would smuggle itself into a JSONB column that also feeds the D15 feed.
_DEGRADATION_REASON_CHARS = 200
_MAX_DEGRADATION_REASONS = 8


def _count_incidental(
    claims: list[dict[str, Any]],
    verdicts_by_claim: dict[int, list[dict]],
) -> dict[str, int]:
    """WR-10 / D-10 Option 2: claims the gates did NOT select that got checked anyway.

    A group is sent for checking when ANY member is gate-selected
    (`_group_selected`), and `group_skeptic._parse_group_verdict` fills EVERY
    member index — so a gate-DROPped or SKIP_STABLE member of a selected group
    comes back carrying a real verdict. Those verdicts are not decorative: they
    reach `adjudicate_all`, can refute the claim, and `scrub_research` then deletes
    the refuted passage from the delivered report. Yet the funnel published those
    same claims to the operator inside bucket 2, "not checkable" — the
    one-claim-one-bucket invariant breaking in the *under-claiming* direction.

    D-10 keeps the behaviour and fixes the accounting. Option 1 (skip non-VERIFY
    members) was explicitly REJECTED: it silently stops scrubbing passages that are
    removed today, making the report LESS verified in exchange for cleaner books.

    Computed from CLAIM STATE at the end of the verify stage, not tallied at the
    filing sites — for exactly the reason `_observed_unchecked` below is: a tally
    only knows the causes it was taught to name, while claim state knows what
    actually happened. `verdicts_by_claim` is seeded `{id(c): [] for c in claims}`,
    so TRUTHINESS (not key presence) is the correct test for "received a verdict".

    Attribution is one claim to exactly one reason key, and `both` is the catch-all
    — `BOTH`, a missing reason and an unrecognised string all land there, mirroring
    what `gates.py` already does with its own catch-all. An unattributable
    incidental check is never dropped from the accounting.

    Never raises: every read is a `.get` chain, so a claim carrying no `gate` key
    at all is handled rather than blowing up the funnel build. (Such a claim can
    only arise on a run with no gate stage, where `dropped + skipped_stable` is 0
    and `_build_funnel`'s clamp reduces the whole count to zero anyway.)

    Returns exactly five int keys: the four reason keys plus `checked_incidentally`,
    set HERE to the sum of the four so the total and the breakdown cannot disagree.
    """
    counts: dict[str, int] = {key: 0 for key in _INCIDENTAL_REASON_KEYS}
    for claim in claims:
        gate = claim.get("gate") or {}
        strict = gate.get("strict")
        if strict == "VERIFY":
            continue                                   # selected: bucket 1 or 3, not here
        if not verdicts_by_claim.get(id(claim)):
            continue                                   # not selected AND not checked
        if strict == "SKIP_STABLE":
            counts["checked_incidentally_stable"] += 1
            continue
        reason = gate.get("reason")
        if reason == "NOT_FALSIFIABLE":
            counts["checked_incidentally_not_falsifiable"] += 1
        elif reason == "NOT_LOAD_BEARING":
            counts["checked_incidentally_not_load_bearing"] += 1
        else:
            counts["checked_incidentally_both"] += 1
    counts["checked_incidentally"] = sum(counts[key] for key in _INCIDENTAL_REASON_KEYS)
    return counts


def _normalise_degradation_reasons(reasons: list[str] | None) -> list[str]:
    """D-12's ONE normaliser for the run's degradation-reason list.

    `run()` holds exactly ONE accumulator (declared by plan 15.2-07, together with
    its `_note_degradation` writer) and publishes it on TWO surfaces: the top-level
    result key `runs/worker.py` reads, and the funnel key the superadmin
    verification report reads. Both go through THIS function, so the two surfaces
    cannot disagree about what degraded — which is the CR-02 failure mode of two
    numbers describing one thing.

    Keeps non-empty `str` entries only, strips each, truncates each to
    _DEGRADATION_REASON_CHARS, de-duplicates preserving first-seen order, and caps
    the list at _MAX_DEGRADATION_REASONS. Truncation and capping are LOUD (Rule 6):
    a reason list silently shortened is a degraded run under-reporting itself.

    Never raises — a non-list (a legacy funnel, a cached bundle from before 15.2)
    returns [], because a shaper that throws on old data is a shaper that blanks
    the operator surface.
    """
    if not isinstance(reasons, list):
        return []
    kept: list[str] = []
    seen: set[str] = set()
    n_truncated = 0
    for entry in reasons:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if not text:
            continue
        if len(text) > _DEGRADATION_REASON_CHARS:
            text = text[:_DEGRADATION_REASON_CHARS]
            n_truncated += 1
        if text in seen:
            continue
        seen.add(text)
        kept.append(text)
    if n_truncated:
        log.warning(
            "tribunal_pipeline: %d degradation reason(s) were longer than %d "
            "characters and were truncated to that length for the operator surface",
            n_truncated, _DEGRADATION_REASON_CHARS,
        )
    if len(kept) > _MAX_DEGRADATION_REASONS:
        log.warning(
            "tribunal_pipeline: this run recorded %d distinct degradation reasons "
            "but only the first %d are published; the rest are in the logs above",
            len(kept), _MAX_DEGRADATION_REASONS,
        )
        kept = kept[:_MAX_DEGRADATION_REASONS]
    return kept


def _build_funnel(
    gate_funnel: dict[str, Any] | None,
    *,
    unchecked_selected: int,
    verify_sessions: int,
    incidental: dict[str, int] | None = None,
    unresolved_anchors: int = 0,
    degradation_reasons: list[str] | None = None,
) -> dict[str, Any]:
    """The one funnel dict — the gates' nine keys plus the eleven this stage owns.

    Built in ONE place so the zero-claim early return and the full path cannot
    report different shapes (RESEARCH Pitfall 10): a downstream consumer must
    never have to branch on which path produced the report.

    The eleven pipeline-owned keys (G-08 / G-10 / G-13 / WR-10 / D-06 / D-12):
      checked                  -- selected for checking AND actually checked
      should_have_been_checked -- bucket 3: selected and NOT checked, whatever the
                                  cause (crash, timeout, usage cap, budget cap).
                                  This is the phase's most important number and
                                  must be ZERO on a healthy run.
      verification_degraded    -- the loud marker; true iff bucket 3 is non-empty.
      verify_sessions          -- skeptic sessions actually launched. G-13: a
                                  recorded pass-through measure of throughput, NOT
                                  a gate assertion — never assert on it.
      checked_incidentally     -- WR-10: NOT selected by the gates, yet checked as
                                  a member of a selected group. Subtracted from
                                  bucket 2 by verification/report.py, per reason.
      checked_incidentally_not_falsifiable
      checked_incidentally_not_load_bearing
      checked_incidentally_both
      checked_incidentally_stable
                               -- the same count split by the gate reason the claim
                                  carried, so bucket 2's printed reasons still sum
                                  to bucket 2's printed total after the subtraction.
      unresolved_anchors       -- D-06: [[c:...]] anchors the writing model emitted
                                  that matched no claim and were removed. ZERO on
                                  every path here; the real value only exists after
                                  synthesis and is folded in by _write_final_report.
      degradation_reasons      -- D-12: the run's degradation sentences, normalised
                                  by the ONE normaliser above. NOT the bucket-3
                                  sentence: verification/report.py derives that at
                                  read time, so there is exactly one wording of it.

    Keys are ADDITIVE ONLY. Phase-15 surfaces and test_hash_chain_replay.py assert
    on the existing names; renaming one breaks them silently. And every key added
    here MUST be added to RECORDED_FUNNEL_COUNTS (tests/fixtures/run_4cbb5311/
    loader.py) in the SAME commit — test_gate_selector.py compares the two key sets
    for equality, in both directions.

    Every parameter after `verify_sessions` is keyword-only WITH A DEFAULT, because
    the zero-claim call site's source literal is itself asserted by
    test_gate_selector.py and must stay byte-identical.
    """
    funnel: dict[str, Any] = {key: 0 for key in _GATE_FUNNEL_KEYS}
    for key, value in (gate_funnel or {}).items():
        funnel[key] = value
    selected = int(funnel.get("selected_verify", 0) or 0)
    # Clamped defensively: bucket 3 counts a SUBSET of the selected queue, so a
    # count above it would be an accounting lie in the other direction.
    unchecked = max(0, min(int(unchecked_selected), selected))
    funnel["checked"] = selected - unchecked
    funnel["should_have_been_checked"] = unchecked
    funnel["verify_sessions"] = int(verify_sessions)
    funnel["verification_degraded"] = unchecked > 0

    # WR-10 / D-10 Option 2. Same defensive register as the bucket-3 clamp above:
    # an incidental count above bucket 2's own population would drive a bucket-2
    # reason negative in verification/report.py and break the one-claim-one-bucket
    # invariant in the OTHER direction. Allocate against the remaining capacity in
    # a fixed key order so the truncation is deterministic, and say so out loud.
    _incidental = incidental or {}
    _raw = {
        key: max(0, int(_incidental.get(key, 0) or 0))
        for key in _INCIDENTAL_REASON_KEYS
    }
    _capacity = max(
        0,
        int(funnel.get("dropped", 0) or 0) + int(funnel.get("skipped_stable", 0) or 0),
    )
    _remaining = _capacity
    for key in _INCIDENTAL_REASON_KEYS:
        take = min(_raw[key], _remaining)
        funnel[key] = take
        _remaining -= take
    _incidental_total = sum(funnel[key] for key in _INCIDENTAL_REASON_KEYS)
    if _incidental_total != sum(_raw.values()):
        log.warning(
            "tribunal_pipeline: %d claim(s) were counted as checked incidentally, "
            "but only %d claims were gated out at all (%d dropped + %d stable "
            "skips) — publishing the clamped figure, because a count above bucket "
            "2's population would make the accounting sum to more than the "
            "distilled total",
            sum(_raw.values()), _capacity,
            int(funnel.get("dropped", 0) or 0), int(funnel.get("skipped_stable", 0) or 0),
        )
    # The flat total is the SUM of the four published reason counts, never a second
    # reading of the input: the total and its breakdown cannot disagree.
    funnel["checked_incidentally"] = _incidental_total

    # D-06. Always present, 0 on every path THROUGH THIS BUILDER — the real count
    # does not exist until the writing model has produced prose and the anchors
    # have been resolved, so _write_final_report folds it in afterwards.
    funnel["unresolved_anchors"] = max(0, int(unresolved_anchors or 0))
    # D-12, SURFACE 1 OF 2. `degradation_reasons` is plan 15.2-07's run-scoped
    # accumulator, handed in at the call site and READ here, never re-declared.
    # Deliberately does NOT include the bucket-3 sentence: verification/report.py
    # derives that one from `should_have_been_checked` at read time, so exactly ONE
    # wording of it exists in the codebase. A later plan appending a bucket-3 reason
    # here would print the same shortfall to the operator twice, in two dialects.
    funnel["degradation_reasons"] = _normalise_degradation_reasons(degradation_reasons)
    return funnel


def _verify_closing_item(funnel: dict[str, Any]) -> dict[str, str]:
    """The verify stage's closing D15 feed row — degradation stated in WORDS (G-10).

    G-10 is explicit that a gutted verification is announced "in words … not a
    subtle icon", because the run still ends with status `completed` and an
    operator scanning a green feed has nothing else to warn them. So when bucket 3
    is non-empty the sentence LEADS with the degradation and names the count; the
    counts follow as supporting detail rather than as the headline.

    `status` is deliberately one of the values the feed already renders
    (`ResearchRunProgress.tsx` handles done / running / retry / failed / pending) —
    an invented string would fall through to the neutral styling and produce
    exactly the quiet failure this is here to prevent. "failed" is the honest one:
    part of the verification stage did fail, even though the run completes.
    """
    distilled = int(funnel.get("distilled", 0) or 0)
    selected = int(funnel.get("selected_verify", 0) or 0)
    checked = int(funnel.get("checked", 0) or 0)
    unchecked = int(funnel.get("should_have_been_checked", 0) or 0)
    dropped = int(funnel.get("dropped", 0) or 0)
    stable = int(funnel.get("skipped_stable", 0) or 0)
    gate_errors = int(funnel.get("gate_errors", 0) or 0)
    sessions = int(funnel.get("verify_sessions", 0) or 0)
    incidental = int(funnel.get("checked_incidentally", 0) or 0)

    counts = (
        f"{checked} of {selected} selected claims checked · "
        f"{dropped} not checkable · {stable} stable facts skipped · "
        f"{sessions} skeptic sessions"
    )
    if gate_errors:
        counts += f" · {gate_errors} gate errors (sent for checking)"
    if incidental:
        # WR-10 / D-10 Option 2, in words. Both branches below render `counts`, so
        # one append covers the degraded row and the healthy row.
        counts += (
            f" · {incidental} also checked incidentally (gate-dropped or stable "
            f"members of a selected group — their verdicts count)"
        )

    if unchecked > 0:
        return {
            "name": (
                f"VERIFICATION DEGRADED — {unchecked} of {selected} selected claims "
                f"were never checked (crash, usage cap, budget exhaustion or gate "
                f"error). Their passages ship unexamined: only a refutation removes "
                f"one. Do not read this run's verification as green. — {counts}"
            ),
            "status": "failed",
        }
    return {
        "name": f"verification complete · {counts} · {distilled} claims distilled",
        "status": "done",
    }


#: Which ALREADY-DECLARED stage key a restored checkpoint reports itself under.
#: 15.2-03 owns `runs/stages.py`; this plan declares NO new stage and writes feed
#: rows only into keys that schema already contains. `provider_jobs` and `park`
#: are absent on purpose: an in-flight job id is not a finished stage, and a park
#: marker is not progress.
_CKPT_STAGE_KEYS: dict[str, str] = {
    "workshop": "intake",
    "angles": "intake",
    "research": "deep_research",
    "merge": "distill",
    "gates": "gate",
    "verify": "verify",
}

#: Hard bound on a park reason. It is persisted on `run.verification_summary`,
#: projected onto `RunMetrics.park`, and rendered by 15.2-19 into an HTML mail
#: and the operator panel — so it is a SENTENCE, not a stack trace (T-15.2-126).
_PARK_REASON_CHARS = 400


def _read_terminal_inputs(verification: dict[str, Any] | None) -> dict[str, Any]:
    """D-17 facts off a synthesis bundle, read defensively. Never raises.

    A pre-15.2-16 `synthesis_cache` row replayed after a deploy carries no
    `terminal_inputs` key at all, and it must still produce the pre-15.2-16
    answer rather than an exception or a park: the defaults below are exactly
    what `runs/worker.py` pinned before this plan.
    """
    raw = (verification or {}).get("terminal_inputs")
    raw = raw if isinstance(raw, dict) else {}

    def _int(key: str, default: int) -> int:
        value = raw.get(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    return {
        "streams_lost": max(0, _int("streams_lost", 0)),
        "streams_total": max(1, _int("streams_total", 1)),
        "verify_ran": bool(raw.get("verify_ran", True)),
        "synthesis_ran": bool(raw.get("synthesis_ran", True)),
        "hard_wall": bool(raw.get("hard_wall", False)),
        "degradation_reasons": _normalise_degradation_reasons(
            raw.get("degradation_reasons")
            if isinstance(raw.get("degradation_reasons"), list)
            else (verification or {}).get("degradation_reasons")
        ),
    }


def _park_result(
    *,
    stage: str,
    reason: str,
    prior_park: Any,
    terminal_inputs: dict[str, Any],
    verification_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the pipeline's PARK FACTS. This function never decides a status.

    DEC-6, and the whole reason this returns facts rather than a string: the
    pipeline never returns `"parked"`. It returns `terminal_inputs` constructed
    so that `reliability.terminal_state()` provably yields `"parked"` — F6 sets
    `streams_lost == streams_total`, a hard wall sets `hard_wall=True`, a gate
    stage that could not run sets `verify_ran=False`, a walled synthesis sets
    `synthesis_ran=False`. `runs/worker.py` calls `terminal_state(**terminal_inputs)`
    and writes whatever comes back. There is exactly ONE degradation/park rule in
    this codebase and it is not here.

    The `reason` must already have been built from `error_signature(exc)` plus a
    plain-language lead sentence — NEVER `repr(exc)`. It is clamped here as the
    last line of defence.
    """
    clamped = str(reason or "").strip()[:_PARK_REASON_CHARS]
    signature = park_signature(stage, clamped)
    park = {
        "seq": next_park_seq(prior_park, signature),
        "stage": str(stage or ""),
        "reason": clamped,
        "signature": signature,
    }
    result: dict[str, Any] = {
        "parked": True,
        "park": park,
        "terminal_inputs": dict(terminal_inputs),
    }
    if verification_summary:
        result["verification_summary"] = verification_summary
    return result


async def _resolve_then_persist_claims(
    *,
    survivors: list[dict],
    dropped: list[dict],
    verdicts_by_claim: dict,
    research_gaps: Optional[list[dict]],
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> None:
    """Stage 7. Resolve gemini redirects, THEN open the session and persist.

    THE ORDER OF THE TWO HALVES IS THE POINT OF THIS FUNCTION (D-V01-11).

    `persist_tribunal_claims` documents that the CALLER opens the session and the
    transaction — so anything awaited inside that block holds a pooled connection
    with RLS tenant context set. Redirect resolution is up to
    `NESTOR_REDIRECT_RESOLVE_DEADLINE_S` (30 s by default) of network I/O against
    a third party, and this is the FINAL persistence step of a ~$50 run: a pool
    stall or a hung socket there costs the run its claims. Resolution is an
    ENRICHMENT that is allowed to fail; the claims are not. So the resolver runs
    HERE, before `get_sessionmaker()` is even called, and only the finished map
    crosses into the transaction.

    `tests/test_source_resolution.py` asserts the ORDERING — the resolver's last
    request completes before `session.begin()` is entered — rather than merely
    asserting that the map arrived. A test of the second kind would still pass if
    a future edit moved resolution back inside the transaction, which is exactly
    the edit this arrangement exists to prevent. This body is a module-level
    function, not an inline block, so that ordering can be driven directly.

    Extracted from the inline Stage 7 block; the `except Exception` that
    deliberately does NOT block synthesis on a persistence failure is preserved
    verbatim, including its log line.
    """
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    # ------------------------------------------------------------------
    # 7a. OUTSIDE any session or transaction: resolve the run's redirects.
    # ------------------------------------------------------------------
    # `_gather_source_urls` is the SAME extraction `persist_tribunal_claims`
    # performs per claim, so the set resolved here is exactly the set upserted
    # below — no drift, by construction rather than by care.
    #
    # `dropped` is included as well as `survivors` because both are handed to
    # `persist_tribunal_claims`, and the dedupe means a URL cited by both costs
    # one request, not two.
    #
    # A resolution failure degrades to an EMPTY MAP and persistence proceeds
    # unchanged: a citation without its publisher URL is still a citation.
    resolved_urls: dict = {}
    try:
        resolved_urls = await resolve_redirects(
            _gather_source_urls(list(survivors) + list(dropped), verdicts_by_claim)
        )
    except Exception as exc:  # the resolver promises not to raise; belt and braces
        log.warning(
            "tribunal_pipeline: redirect resolution failed (%s) — persisting "
            "citations without publisher URLs", exc,
        )
        resolved_urls = {}

    # ------------------------------------------------------------------
    # 7b. NOW open the session and the transaction. No network from here on.
    # ------------------------------------------------------------------
    try:
        _sm = get_sessionmaker()
        async with _sm() as session:
            async with session.begin():
                # ENGINE-10 / CR-02 — `dropped_claims` is NOT optional in
                # spirit. A refuted claim lives in `dropped`, never in
                # `survivors`, and gets no `claim` row; without this argument
                # its verdict is never persisted at all, so
                # report["verdicts"]["refute"] and report["refuted"] stay
                # structurally empty on every run no matter how many claims
                # the skeptic refuted. `dropped` here already covers BOTH
                # adjudication losers and conflict losers — it is the same
                # list the rejected_claims ledger was built from.
                #
                # D-13 — `research_gaps` is the merge stage's ATTRIBUTED
                # couldn't-find list. It is written HERE, inside the same
                # tenant context and the same transaction as the claims,
                # because 15.2-06's "What we could not establish" section
                # reads the `research_gap` table DIRECTLY rather than taking
                # a hand-off through the synthesis bundle: the rows simply
                # have to exist before `_write_final_report` runs, and this
                # is the last tenant-scoped transaction before it.
                await persist_tribunal_claims(
                    claims=survivors,
                    dropped_claims=dropped,
                    verdicts_by_claim=verdicts_by_claim,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    session=session,
                    research_gaps=research_gaps,
                    resolved_urls=resolved_urls,
                )
    except Exception as exc:
        # Do NOT block synthesis on persistence failures; log for audit
        log.error("tribunal_pipeline: persist_tribunal_claims failed: %s", exc, exc_info=True)


class TribunalPipeline:
    """Adaptive-effort Tribunal SDK engine (ADR-006).

    Matches the Runner protocol from nestor_pulse_sdk/runs/adapter.py.

    The constructor accepts an optional injected audited client (for testing);
    production instantiation via dispatch_runner() passes no argument, and
    the client is built lazily on first run() call.
    """

    def __init__(self, audited: Optional["AuditedLLMClient"] = None) -> None:
        self._audited = audited

    async def run(
        self,
        *,
        brief: str,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Execute the Tribunal pipeline end-to-end.

        Args:
            brief:     Raw client brief text.
            run_id:    UUID of the current run (audit + DB key).
            tenant_id: UUID of the current tenant (RLS + audit).

        Returns:
            Result dict matching the Runner protocol. See module docstring for shapes.
        """
        log.info("tribunal_pipeline_invoked", extra={"run_id": str(run_id)})

        audited = self._audited
        if audited is None:
            from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client
            audited = build_audited_client()

        # Interactive report shaping (opt-in). The brief carries the marker only
        # when the user enabled "shape report interactively"; strip it so it never
        # reaches research/synthesis.
        interactive_report = _INTERACTIVE_MARKER in (brief or "")
        if interactive_report:
            brief = (brief or "").replace(_INTERACTIVE_MARKER, "").strip()

        # ------------------------------------------------------------------
        # RUN-SCOPED REGISTRIES. Both are declared HERE, at the top of the run and
        # BEFORE the resume-from-cache early return below, so every stage can reach
        # them and both return paths publish the same shape.
        # ------------------------------------------------------------------
        #
        # The run's circuit-breaker registry (plan 15.2-02). ONE instance per run,
        # NEVER at module level — plan 02's BreakerSet docstring says so: a
        # module-level set would carry one run's provider failures into the next
        # run and, in a multi-tenant system, across tenants. It is created here
        # rather than down in the verify stage because plans 15.2-12/13/16 attach
        # the research-provider breakers to this same object. This plan does NOT
        # thread it into run_angles or any other stage — that is 13/16's work.
        breakers = BreakerSet()
        #
        # D-12's degradation-reason list for this run.
        #
        # THIS IS THE ONE AND ONLY DECLARATION OF `degradation_reasons` IN run().
        # Never re-declare or re-assign the name further down — in particular NOT in
        # the verify stage next to `unchecked_ids`. A second binding rebinds the name
        # to a fresh empty list and silently discards everything appended before it
        # (the workshop fallback, a lost research stream, a fact-list fallback), and
        # no plan's own unit tests would catch it because each tests its accumulator
        # in isolation. That is exactly the silent-green class of bug this phase
        # exists to eliminate.
        degradation_reasons: list[str] = []

        def _note_degradation(reason: str) -> None:
            """Append ONE plain-words degradation reason for this run, idempotently.

            The single writer for D-12's reason list. `run()` publishes the list on
            exactly two surfaces (see the synthesis bundle and `_write_final_report`
            below): the TOP-LEVEL key on the dict `run()` returns, which
            `runs/worker.py` reads and feeds to `terminal_state()`, and the same
            list on the synthesis bundle under `verification`, which is what
            survives the interactive-report pause and the synthesis_cache round-trip.
            Both carry the SAME content from THIS list; neither is a second
            accumulator.

            Callers, so no later plan invents a second list:
              - this plan (15.2-07): the blocked coverage re-entry sentence;
              - plan 15.2-08: consumes the list and adds the shared
                `_normalise_degradation_reasons` (200-char / 8-entry caps) plus the
                funnel-side surfacing;
              - plan 15.2-11: the question-workshop fallback;
              - plan 15.2-12: a lost own-researcher stream;
              - plan 15.2-14: the fact-list fallback;
              - plan 15.2-16: the park / skip paths.

            De-duplicated by exact string, because the same provider failure can be
            observed at more than one site and an operator reading the same sentence
            twice learns nothing new. Not normalised or capped HERE — plan 08 owns
            the shared normaliser, and writing a second one would be the fork this
            phase's Rule 11 forbids.

            NEVER a reason (D-12): a RECOVERED retry and a pending Gemini grounding
            fee. Both are designed paths, not shortfalls, and demoting them would
            drain `completed_degraded` of its meaning. Bucket 3 is not written here
            either — `verification/report.py` derives that sentence at read time
            (plan 08), so there is exactly one wording of it in the codebase.
            """
            if not isinstance(reason, str):
                return
            text = reason.strip()
            if not text or text in degradation_reasons:
                return
            degradation_reasons.append(text)
            log.warning("tribunal_pipeline: DEGRADED — %s", text, extra={"run_id": str(run_id)})

        # RESUME-FROM-CACHE: if a report_spec has been submitted for this run (the
        # interactive gate was answered, or this is a "Rewrite report" run that
        # inherited a cached bundle), the expensive research is already done. Skip
        # straight to synthesis from the cache — never re-research.
        cached_spec = await _read_output(run_id, tenant_id, "report_spec")
        if cached_spec is not None:
            bundle = await _read_output(run_id, tenant_id, "synthesis_cache")
            if bundle:
                from nestor_pulse_sdk.pipeline.tribunal.report_planner import normalize_spec
                spec = normalize_spec(cached_spec, bundle.get("mission_brief") or {})
                log.info("tribunal_pipeline: resuming from cached research (report_spec present)")
                return await _write_final_report(
                    bundle=bundle, report_spec=spec,
                    audited=audited, run_id=run_id, tenant_id=tenant_id,
                )
            log.warning(
                "tribunal_pipeline: report_spec present but no synthesis_cache — running fresh"
            )

        # ------------------------------------------------------------------
        # R3 CHECKPOINTS (plan 15.2-16)
        # ------------------------------------------------------------------
        # Constructed AFTER the report_spec / synthesis_cache branch above,
        # which stays FIRST and unchanged: that branch is a full short-circuit
        # to synthesis and must keep priority over anything here.
        #
        # `CheckpointStore` takes BOUND CLOSURES rather than a session — that is
        # precisely what keeps the class database-free and unit-testable with a
        # plain dict and no Postgres. Every payload it writes is an ordinary
        # `Output(format='ckpt_*')` row through the SAME `_write_output`
        # primitive the two branches above already use, so checkpoints inherit
        # the `output` table's existing FORCE-RLS policy: no new table, no
        # migration, no new isolation surface (T-15.2-129).
        ckpt = CheckpointStore(
            read=lambda fmt: _read_output(run_id, tenant_id, fmt),
            write=lambda fmt, payload: _write_output(run_id, tenant_id, fmt, payload),
        )
        await ckpt.load()

        if ckpt.resumed():
            log.warning(
                "tribunal_pipeline: RESUMING from checkpoints — %s. Every stage "
                "listed here was already paid for on a previous attempt and will "
                "not be dispatched again.",
                ", ".join(ckpt.restored_keys),
                extra={"run_id": str(run_id)},
            )
            # The detail dict is built into a local FIRST, on purpose. The stage
            # key here is a VARIABLE, so an inline `detail={...}` would make the
            # dict's own first key the first quoted token in the call — and the
            # WR-03 source gates (test_stage_schema.py and
            # test_research_division_assignment.py) read exactly that position to
            # recover the stage key. Keeping the call free of string literals
            # keeps those gates reading real stage keys only.
            _restored_detail = {"items": [{
                "name": (
                    "restored from a checkpoint — this stage ran on an earlier "
                    "attempt of this run and was NOT charged again"
                ),
                "status": "done",
            }]}
            for _restored_key in ckpt.restored_keys:
                _stage_key = _CKPT_STAGE_KEYS.get(_restored_key)
                if not _stage_key:
                    continue
                await set_stage(run_id, tenant_id, _stage_key, detail=_restored_detail)

        # WHERE the run got to, for the park message. A one-element list because
        # the `set_stage` shim inside `_run_staged` writes to it and `run()` reads
        # it back after the guard below fires.
        stage_tracker = ["intake"]

        # ------------------------------------------------------------------
        # THE ONE PARK GUARD (R4/D-17). One try/except around the whole staged
        # body — never a scatter of them.
        # ------------------------------------------------------------------
        try:
            return await self._run_staged(
                brief=brief,
                run_id=run_id,
                tenant_id=tenant_id,
                audited=audited,
                interactive_report=interactive_report,
                breakers=breakers,
                degradation_reasons=degradation_reasons,
                _note_degradation=_note_degradation,
                ckpt=ckpt,
                stage_tracker=stage_tracker,
            )
        except RunCancelled:
            # A USER CANCEL IS NEVER CONVERTED INTO A PARK. It is listed FIRST
            # and re-raised unconditionally so that the worker's `except
            # RunCancelled` arm — and its `WHERE ... status='running'` guard —
            # keep the cancelled verdict. Parking a cancelled run would show the
            # operator a Resume button for work they deliberately stopped.
            raise
        except Exception as exc:  # noqa: BLE001 — re-raised below unless it parks
            # F6, DEFENCE IN DEPTH — expressed as an isinstance test rather than
            # a second dedicated except clause for it, so this file keeps
            # exactly ONE such clause (the PRIMARY one, at the `run_angles`
            # call site inside `_run_staged`, where the angle count and the
            # per-provider reasons are in hand). Both of F6's raise sites are
            # already inside that try, so this arm is unreachable today; it
            # exists so a future raise site cannot quietly turn "every research
            # stream was lost" into `failed`.
            _is_f6 = isinstance(exc, InsufficientProvidersError)
            if not _is_f6 and classify(exc) != HARD_WALL:
                # Not a park cause: an ordinary failure, and the worker's
                # `failed` path is the honest answer for it. Re-raise.
                raise

            if _is_f6:
                _lost = max(1, len(getattr(exc, "failed", None) or []) or 1)
                _inputs = {
                    "streams_lost": _lost,
                    "streams_total": _lost,
                    "verify_ran": False,
                    "synthesis_ran": False,
                    "hard_wall": False,
                    "degradation_reasons": list(degradation_reasons),
                }
                reason = (
                    "No research provider produced a usable result for this run, "
                    "so there is nothing to verify or report on. Nothing already "
                    "paid for has been lost — the run is parked and can be "
                    f"resumed. Provider signal: {error_signature(exc)}"
                )
            else:
                _inputs = {
                    "streams_lost": 0,
                    "streams_total": 1,
                    "verify_ran": False,
                    "synthesis_ran": False,
                    "hard_wall": True,
                    "degradation_reasons": list(degradation_reasons),
                }
                reason = (
                    "This run stopped because the provider refused the request at "
                    "the account level — a monthly usage cap, exhausted credits or "
                    "a billing block. No retry can fix that, so the run is parked "
                    "with its paid work intact and can be resumed once the account "
                    f"is clear. Provider signal: {error_signature(exc)}"
                )

            parked = _park_result(
                stage=stage_tracker[0],
                reason=reason,
                prior_park=ckpt.get("park"),
                terminal_inputs=_inputs,
            )
            await ckpt.put("park", parked["park"])
            log.error(
                "tribunal_pipeline: PARKED at stage %s — %s",
                stage_tracker[0], parked["park"]["reason"],
                extra={"run_id": str(run_id)},
            )
            return parked
        finally:
            # D-F (15.2-24). EVERY OTHER WAY OUT OF THE STAGED BODY ENDS HERE:
            # a park, a cancel, an ordinary failure, the zero-claim early return
            # and the interactive report_spec pause. The normal path already
            # closed at the `done` write and `_stage_log_close` is idempotent, so
            # this costs that path nothing — what it buys is that a run which
            # stopped early still emits its last `stage_exit` and its
            # `run_stages_complete` line (the operator's answer to "how far did it
            # get"), and that no run leaves an entry behind in the registry.
            _stage_log_close(run_id)
            # 15.3-03. SAME `finally`, SAME REASON, AND THE ORDER IS LOAD-BEARING:
            # the line above emits the run's FINAL stage summary into the event
            # buffer, and this line drains and closes that buffer. Closing first
            # would throw that summary away.
            #
            # `close_run` is idempotent (it pops the registry entry before doing
            # any work), so a later writer on the `done` path may also call it;
            # and it never raises, so a failing drain cannot turn a completed run
            # into a failed one (D-06).
            await run_events.close_run(run_id)

    async def _run_staged(
        self,
        *,
        brief: str,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        audited: "AuditedLLMClient",
        interactive_report: bool,
        breakers: BreakerSet,
        degradation_reasons: list[str],
        _note_degradation: Any,
        ckpt: CheckpointStore,
        stage_tracker: list[str],
    ) -> dict[str, Any]:
        """The staged body of `run()`: workshop -> research -> ... -> report.

        SPLIT OUT OF `run()` BY PLAN 15.2-16, and for exactly one reason: the
        R4/D-17 park needs ONE try/except around the whole staged body, and a
        sibling method is how you get that without re-indenting 1,300 lines of
        working pipeline. Every local this body uses is passed in by name, so
        the body itself is unchanged — `degradation_reasons` is still run()'s
        ONE accumulator (the same list object, not a copy) and
        `_note_degradation` is still its only writer.

        Returns either a normal result dict or, on F6, park FACTS from
        `_park_result` — never the string "parked" (DEC-6).
        """
        # `set_stage` IS DELIBERATELY SHADOWED for this whole method.
        #
        # The park message has to name WHERE the run stopped, and this body
        # calls `set_stage` at every stage boundary already. Wrapping the name
        # once here records the stage for free, instead of editing thirty call
        # sites (each of which would be a chance to miss one). The wrapper adds
        # nothing else: same arguments, same awaited call, same return.
        #
        # LIMIT, stated rather than hidden: `_coverage_reentry_pass` is a
        # module-level function and calls the REAL `set_stage`, so a park raised
        # from inside it is named by the last boundary this body crossed
        # ("coverage"), which is the right answer anyway.
        #
        # THE IMPORT BELOW IS LOAD-BEARING AND MUST NOT BE "TIDIED" BACK INTO
        # `_outer_set_stage = set_stage`.
        #
        # `set_stage` is REBOUND by the `async def` immediately below, which makes
        # the name a LOCAL of this whole method — including on the line above the
        # def. Reading it there therefore raises
        # `UnboundLocalError: cannot access local variable 'set_stage'` on the
        # FIRST statement of the staged body, i.e. on every single run, before any
        # stage executes. The `except Exception` in `run()` re-raises it (it is not
        # a HARD_WALL), so the run reports `failed` with no park and no partial
        # work — the engine is completely dead.
        #
        # It survived review and eleven waves of per-component tests because no
        # test drove `TribunalPipeline.run(...)` end to end; the stubbed e2e
        # (`tests/test_engine_e2e_stubbed.py`) caught it on its first execution.
        # Importing the module attribute under a DIFFERENT name removes the
        # shadowing entirely, and re-reads `runs.stages.set_stage` at call time,
        # so a monkeypatched writer still applies.
        from nestor_pulse_sdk.runs.stages import set_stage as _outer_set_stage

        async def set_stage(_run_id, _tenant_id, stage_key, **kwargs):  # noqa: A001
            stage_tracker[0] = stage_key
            # D-F (plan 15.2-24). THE STAGE LOG RIDES THE SAME CHOKE POINT the
            # park tracker already uses, for the same reason: every in-run stage
            # write passes through here, so one line here is one line at every
            # stage boundary — instead of thirty edits, each of which is a chance
            # to miss one. It cannot raise (see `_stage_log_transition`).
            _stage_log_transition(_run_id, stage_key, kwargs.get("detail"))
            return await _outer_set_stage(_run_id, _tenant_id, stage_key, **kwargs)

        # ------------------------------------------------------------------
        # Stage 1: The QUESTION WORKSHOP (D-03) — client questions in, ranked
        #          sub-questions out. Never raises; degrades in words.
        # ------------------------------------------------------------------
        # The `intake` stage key now means "brief received, client-validated
        # questions identified", and it is still where `_intake_detail` renders
        # the final research plan. The workshop's own fan-out rows go to the
        # `workshop` stage key, declared by 15.2-03 — this plan declares none.
        # 15.3-03: OPEN THE RUN'S EVENT BUFFER, ONCE, HERE. It binds the tenant
        # (the six pipeline modules that emit do not carry one and must not have
        # to) and seeds the sequence from `MAX(seq)`, so a RESUMED run continues
        # its own numbering instead of colliding with the history it already
        # wrote. A second `open_run` anywhere would orphan this buffer's undrained
        # events, so there is exactly one call in this file. It never raises: a
        # failed open costs the feed, not the run.
        await run_events.open_run(run_id, tenant_id)
        await set_stage(run_id, tenant_id, "intake")

        # D-G (plan 15.2-21) — READ THE BRIEF'S STRUCTURE BEFORE ANYTHING SPENDS
        # MONEY ON IT. `parse_brief` is pure, free and never raises, so it sits
        # OUTSIDE the checkpoint branch below: the restored path still skips the
        # whole paid workshop, but `parsed` is defined on both paths because the
        # decision resolution, the degradation sentence and the operator's division
        # header all read it after the workshop returns.
        # 15.3-05: the run id is passed so the same parse ALSO writes the feed's
        # opening lines. It is optional and keyword-only, the parser still never
        # raises and still touches nothing, so this line does not move `parse_brief`
        # out of the safe position the paragraph above puts it in.
        parsed = parse_brief(brief, run_id=run_id)

        # The tournament judge is asked "which of these two matters more for THIS
        # client's decision". Precedence at CALL time is step 1 of the resolution in
        # `(c)` below — the client's own stated decision — because the workshop's
        # restatement of it does not exist yet. When the brief states no decision the
        # judge is handed the project's CONTEXT rather than the brief's opening line:
        # on run d6bb3aae that opening line was `Deep research for moetest.`, a
        # project TITLE, and ranking materiality against a title is how report
        # metadata out-ranked the client's real questions (D-H). Bounded exactly as
        # before, and never empty — an empty decision context silently weakens every
        # judgement in the run.
        _workshop_decision_context = (
            parsed.decision or parsed.context or (brief or "")
        ).strip()[:_GATE_DECISION_CONTEXT_CHARS]

        # R3 (plan 15.2-16): the question workshop is a MULTI-CALL PAID STAGE —
        # orientation, candidates, clustering, critique, a Swiss tournament and
        # an evolve pass. When an earlier attempt of THIS run already completed
        # it, the result is restored and the whole stage is skipped. That is the
        # largest non-research saving a resume makes.
        #
        # The checkpoint holds `workshop_result`, NOT the derived
        # `mission_brief`: everything between the two is pure, deterministic
        # Python (the question fallbacks and `build_mission_brief_from_winners`),
        # so re-deriving it costs nothing and keeps ONE source of truth rather
        # than two that can drift apart across a redeploy.
        _restored_workshop = ckpt.get("workshop")
        workshop_result = (
            _restored_workshop.get("workshop_result")
            if isinstance(_restored_workshop, dict)
            else None
        )
        if workshop_result is not None:
            log.warning(
                "tribunal_pipeline: RESTORED the question workshop from a "
                "checkpoint (%d winning sub-question(s)) — the workshop did NOT "
                "run again and cost nothing on this attempt",
                len(list((workshop_result or {}).get("winners") or [])),
                extra={"run_id": str(run_id)},
            )
        else:
            # THE WORKSHOP FEED IS CLOSED HERE, and only here. 15.2-10 and 15.2-11
            # deliberately left it open (their `_stage_b_feed_finish` flushes but does
            # not close), because closing it inside stage B would make the next
            # writer's rows a no-op and drag `run.current_stage` backwards onto a
            # stage the operator has already watched finish. This pipeline is the
            # last writer of that stage, so `async with` closes it on both the normal
            # and the exception path.
            # D-F (15.2-24), THE ONE STAGE THE CLOSURE CANNOT SEE. The `workshop`
            # stage key is written by `StageFeed`, not by this method's shadowed
            # writer, so no transition reaches the stage log for it — and the
            # workshop is the LONGEST silent stretch of a run (orientation,
            # candidates, clustering, critique, a tournament and an evolve pass).
            # Leaving it unlogged would leave the exact gap this plan closes.
            #
            # It is an EXPLICIT SPAN rather than a synthetic transition, on
            # purpose: pushing `workshop` through `_stage_log_transition` would
            # split the pipeline's two `intake` writes into two separate entries
            # and re-introduce the entry-per-write noise the transition rule
            # exists to prevent.
            _workshop_log_t0 = time.monotonic()
            _stage_log_line("stage_enter", run_id, "workshop")
            async with StageFeed(
                run_id=run_id, tenant_id=tenant_id, stage_key="workshop"
            ) as workshop_feed:
                workshop_result = await run_question_workshop(
                    # `brief=` stays the FULL brief, deliberately. The orientation
                    # and candidate steps are SUPPOSED to read the client's context
                    # pack: the defect was never that the workshop saw the pack, it
                    # was that the pack was treated as a list of questions.
                    brief=brief,
                    # D-G, THE HEADLINE FIX OF THIS PHASE. The workshop's parents are
                    # the client's decomposed, validated questions and nothing else.
                    #
                    # Passing `None` for `questions` used to mean "let
                    # `normalise_questions` work it out from the brief", which in
                    # practice meant `detect_explicit_questions`,
                    # whose enumeration regex accepts `- ` bullets — and the context
                    # pack is built almost entirely of `- **Bold:** value` bullets. On
                    # run d6bb3aae that produced 11 real questions + 21 administrative
                    # bullets = 32 parents, including six paid research sub-questions
                    # generated for "Output size (hard constraint): Standard (15-25
                    # pages)". The client's flagship questions were never dispatched.
                    #
                    # `None` on the UNSTRUCTURED path is deliberate and is NOT the old
                    # defect returning: a free-prose brief has no question block, and
                    # the detector (then the whole-brief case) is the correct, already
                    # proven behaviour for exactly that shape. A structured brief whose
                    # question block yielded nothing takes the same route, so a parse
                    # miss degrades to the old behaviour rather than starting a run
                    # with no questions at all.
                    questions=(
                        [
                            {"label": q, "text": q, "source": "client"}
                            for q in parsed.questions
                        ]
                        if (parsed.source == "structured" and parsed.questions)
                        else None
                    ),
                    decision_context=_workshop_decision_context,
                    audited=audited,
                    run_id=run_id,
                    tenant_id=tenant_id,
                    feed=workshop_feed,
                    # ONE CircuitBreaker, not the whole BreakerSet: `with_retry`
                    # consults `breaker.allow()` directly. Same run-scoped registry
                    # the skeptic stage draws from, so a wedged Anthropic endpoint is
                    # observed once per run rather than once per stage.
                    breaker=breakers.get("anthropic:workshop"),
                )
            # CHECKPOINT AFTER THE EXPENSIVE THING, never before it.
            await ckpt.put("workshop", {"workshop_result": workshop_result})
            # (e) THE TWO NUMBERS AN OPERATOR ASKS OF THE WORKSHOP: how many of
            # the client's own questions went in, and how many sharpened
            # sub-questions came out. Both are read off values that already
            # exist — nothing is computed for the log.
            _stage_log_line(
                "stage_exit", run_id, "workshop",
                seconds=time.monotonic() - _workshop_log_t0,
                questions_in=len(list(parsed.questions or [])),
                winners_out=len(
                    list((workshop_result or {}).get("winners") or [])
                    if isinstance(workshop_result, dict) else []
                ),
                # (f) THE TWO NUMBERS WAVE 3 ADDS, in the same register and read the
                # same way: how many research groups the workshop decided, and how
                # many questions the EVIDENCE raised that this run is going to buy.
                # Nothing is computed for the log — both are the length of a list
                # stage B already returned, read with `.get()` so a pre-Wave-3
                # result shape logs 0 rather than raising on the exit line.
                groups_out=len(
                    list((workshop_result or {}).get("groups") or [])
                    if isinstance(workshop_result, dict) else []
                ),
                discovery_out=len(
                    list((workshop_result or {}).get("discovery") or [])
                    if isinstance(workshop_result, dict) else []
                ),
            )

        # Read the result TOLERANTLY (phase rule 4): every key below is optional
        # as far as this reader is concerned, even though 15.2-11 guarantees them.
        workshop_result = workshop_result if isinstance(workshop_result, dict) else {}
        winners = list(workshop_result.get("winners") or [])
        workshop_fallback = bool(workshop_result.get("workshop_fallback"))
        run_language = str(workshop_result.get("language") or "").strip()
        deep_research_prompt = str(workshop_result.get("deep_research_prompt") or "").strip()
        client_questions = [
            str(q or "").strip()
            for q in (workshop_result.get("client_questions") or [])
            if str(q or "").strip()
        ]
        brief_conflicts = list(workshop_result.get("brief_conflicts") or [])
        # WAVE 3'S TWO NEW KEYS, READ EXACTLY LIKE EVERY LINE ABOVE THEM: `.get()`
        # and `or []`, never a subscript. This is not defensive style for its own
        # sake — T-15.6-25. A run RESTORED from a checkpoint written before Wave 3
        # carries NEITHER key, and a subscript would raise at precisely the moment
        # the resume exists to avoid: after the workshop has been paid for and
        # before the angles have. The tolerant read makes that resume dispatch by
        # the deterministic one-group-per-client-question fallback instead, which
        # `_divide_from_winners` already logs once.
        groups = list(workshop_result.get("groups") or [])
        discovery = list(workshop_result.get("discovery") or [])
        discovery_not_researched = list(
            workshop_result.get("discovery_not_researched") or []
        )
        # THE SET THAT WAS ACTUALLY DISPATCHED — the only set `annotate_conflicts`
        # may be handed. Stage B already returns `discovery` as the dispatched half
        # and `discovery_not_researched` as its complement, so on every path this
        # engine writes the subtraction below removes nothing. It is here because
        # the OTHER shapes are real: a checkpoint restored from a build whose stage
        # B partitioned differently, or a hand-built result in a test, can carry a
        # question in both lists. Annotating such a question would tell the client
        # a question was researched when no provider was ever asked — the one thing
        # `annotate_conflicts`' docstring says must not happen. A question shed as a
        # rider, or whose cross-cutting group was dropped to free a coverage slot,
        # still reaches the report: with no `researched_as` clause it renders as a
        # plain brief-vs-world conflict, which is the honest statement.
        _shed_discovery_texts = {
            str((q or {}).get("text") or "").strip()
            for q in discovery_not_researched
            if isinstance(q, dict)
        } - {""}
        discovery_dispatched = [
            q
            for q in discovery
            if isinstance(q, dict)
            and str(q.get("text") or "").strip() not in _shed_discovery_texts
        ]

        if not client_questions:
            # The workshop normally cannot return an empty list, so reaching this
            # is worth a sentence. `detect_explicit_questions` is the SAME
            # detector the workshop uses internally — reused, never re-written.
            client_questions = [
                q.strip() for q in detect_explicit_questions(brief or "") if q.strip()
            ]
            log.warning(
                "tribunal_pipeline: the workshop returned no client questions — "
                "falling back to the deterministic question detector (%d found)",
                len(client_questions),
            )
        if not client_questions:
            first_line = next(
                (ln.strip() for ln in (brief or "").splitlines() if ln.strip()), ""
            )
            client_questions = [(first_line or "the brief")[:120]]
            log.warning(
                "tribunal_pipeline: the brief carries no enumerated question — "
                "researching it as ONE question titled %r", client_questions[0],
            )
        # D-H — THE DECISION, RESOLVED ONCE, WITH THE ORDER DELIBERATELY CHANGED.
        # Until now the workshop's own `deep_research_prompt` was preferred and the
        # brief's opening line was the floor. The precedence is now:
        #   1. the client's STATED decision, carried across the seam in the brief's
        #      `[DECISION]` block (written by the intake backend from the context
        #      pack's "Wat moet beslist worden" line, then the intake's own decision
        #      answer, then the decomposition summary);
        #   2. the workshop's own research prompt, when it returned one;
        #   3. nothing — which is now a NAMED degradation, never a substitution.
        # The client's own words outrank a model-authored restatement of them because
        # the tournament is ranking sub-questions by materiality TO THE CLIENT'S
        # DECISION, and on this brief the client wrote that decision down. A
        # restatement can only lose fidelity to it.
        #
        # SAY THE UNCOMFORTABLE PART ABOUT STEP 2. `run_question_workshop` does not
        # AUTHOR a research prompt — it ECHOES the `deep_research_prompt` it was
        # handed, and this call site has never handed it one. So step 2 is empty on
        # every run from this pipeline, and the log line "the workshop returned no
        # research prompt" that fired on d6bb3aae was not bad luck: it is the only
        # thing that can happen here. Step 2 is kept because the parameter is part of
        # the workshop's published return shape and another caller may populate it,
        # but nothing in this engine should be read as depending on it.
        if parsed.decision:
            if deep_research_prompt and deep_research_prompt != parsed.decision:
                log.info(
                    "tribunal_pipeline: the brief carries the client's stated "
                    "decision, so materiality is judged against that rather than "
                    "against the workshop's own restatement of it"
                )
            deep_research_prompt = parsed.decision
        _no_stated_decision = False

        # D-LVT — THE RUN LANGUAGE, RESOLVED IN THE SAME REGISTER AS THE DECISION
        # ABOVE, and for the same reason: the client's own choice outranks a
        # model-authored restatement of it.
        #
        #   1. the client's STATED report language, carried across the seam in the
        #      brief's `[REPORT]` block (the `report_language` intake field);
        #   2. the workshop's own `language`, when it returned one;
        #   3. nothing — which stays EMPTY and is now WARNED about, never guessed.
        #
        # WHY STEP 3 IS NOT A DETECTOR. Inferring the dominant language of the brief
        # is confidently wrong in exactly the case that matters — a Dutch-speaking
        # client who needs an English report for an international board — and the
        # cost of being wrong is the whole report.
        #
        # WHAT THIS UNBLOCKS, measured on run 368ff3a0 rather than argued: this value
        # is read by `_d7_language_sentence` (every provider assignment) and by
        # `synthesis/steps.py::_language_directive` (every writing step). It was
        # EMPTY on that entire run, so both took their weakened branch — all five
        # dispatch assignments read say "Report all findings in the language of the
        # assignment above.", and the strong "Write EVERYTHING in {lang} and ONLY
        # {lang} ... Never mix languages" directive has never fired in production.
        # `adaptive_intake` was its only producer and D-03 unwired it; nothing has
        # produced it since.
        if parsed.language:
            if run_language and run_language != parsed.language:
                log.info(
                    "tribunal_pipeline: the brief states the client's chosen report "
                    "language (%s), so it outranks the workshop's own value (%s)",
                    parsed.language, run_language,
                )
            run_language = parsed.language
        if not run_language:
            log.warning(
                "tribunal_pipeline: no report language was stated by the client and "
                "none was returned by the workshop — every provider assignment and "
                "every synthesis prompt falls back to inferring it from the brief, "
                "which is a materially weaker one-language-per-run guarantee"
            )
        if not deep_research_prompt:
            # A value MUST keep flowing: this feeds `_gate_decision_context`, and the
            # gates' load-bearing test is judged AGAINST A DECISION — an empty context
            # silently weakens every gate decision in the run. What changes is WHAT
            # the value is, and that the loss is now reported instead of swallowed.
            # The old floor was the brief's opening line; on run d6bb3aae that line
            # read `Deep research for moetest.`, a project TITLE, and every tournament
            # prompt in the run said "The client's decision this research has to
            # serve: Deep research for moetest." Nothing anywhere said so.
            deep_research_prompt = (
                parsed.context or " ".join((brief or "").split())
            ).strip()[:_GATE_DECISION_CONTEXT_CHARS]
            log.warning(
                "tribunal_pipeline: neither the brief nor the workshop stated the "
                "client's decision — the sub-questions are ranked against the "
                "project's context instead of against a decision, which is a "
                "materially weaker ranking"
            )
            # WHO GETS DEMOTED, AND WHY NOT EVERYONE. The warning above fires on
            # every decisionless run, because that is a fact the operator should be
            # able to find in the logs. The run-DEMOTING sentence below is narrower:
            # it fires only for a STRUCTURED brief — one that came through the intake
            # seam with a question block, and which therefore also carries a
            # `[DECISION]` block whenever a decision could be resolved at all. A
            # structured brief with no decision is a real gap in the client's own
            # material and is worth reporting.
            #
            # An UNSTRUCTURED brief is free prose from a non-seam caller: it has no
            # decision block by construction and never could have, so demoting it
            # would mark every such run degraded forever — the alarm fatigue D-12
            # explicitly rejects, and a marker that is always on is one the operator
            # learns to ignore.
            #
            # THE CHECK THAT MATTERS: run d6bb3aae's brief WAS structured
            # (`Onderzoeksvragen:` + 11 enumerated questions, no decision), so under
            # this narrower rule D-H would still have been reported on the run it was
            # written for. The narrowing does not weaken the fix.
            #
            # The SENTENCE itself is deferred to just below, deliberately: the
            # `workshop_fallback` branch there is guarded on `not
            # degradation_reasons`, so noting this one first would silently suppress
            # 15.2-11's own fallback wording. Order of reasons is not cosmetic here.
            _no_stated_decision = parsed.source == "structured"

        # CR-08 — GIVE THE PROVIDER THE WHOLE QUESTION, NOT THE JOIN KEY.
        #
        # `client_questions` above carries LABELS, and a label is
        # `workshop.normalise_questions`' `text[:120]`. That constant is
        # documented as "a dict key and the join key"; nobody recorded that it
        # was also the entire assignment a paid research provider receives. It
        # was: the assignment reached the provider cut off mid-word, with no
        # brief, while the cross-cutting discovery group got the full brief.
        #
        # The full text still exists here, so hand it over. `parsed.questions`
        # is the structured seam's own list; `detect_explicit_questions` is the
        # SAME detector the workshop falls back to, reused rather than
        # re-written, so both label sources are covered. A label is a PREFIX of
        # its text by construction, which is the whole matching rule — no copy
        # of the 120 lives here, so the constant can move without this drifting.
        _full_texts: list[str] = []
        for _raw in list(parsed.questions or []) + detect_explicit_questions(brief or ""):
            _text = str(_raw or "").strip()
            if _text and _text not in _full_texts:
                _full_texts.append(_text)
        parent_prompts: dict[str, str] = {}
        # EACH FULL TEXT IS CLAIMED AT MOST ONCE. Without this, two client
        # questions that share their first 120 characters — which is exactly
        # when `normalise_questions` has to de-duplicate their labels — both
        # prefix-match the SAME first text, so question 2 would be dispatched
        # question 1's wording. That is strictly worse than the truncation this
        # fix exists to remove: it researches a question the client never asked
        # and silently loses one they did. Consuming the match makes the pairing
        # positional among the colliding group, which is the correct reading.
        _unclaimed = list(_full_texts)
        for _label in client_questions:
            # `normalise_questions` de-duplicates colliding labels by appending
            # " (2)", " (3)", ... so a label that matches nothing is retried
            # once with that suffix removed. If that convention ever changes the
            # retry simply stops matching and the label stands — i.e. today's
            # behaviour.
            _candidates = [_label]
            if _label.endswith(")") and " (" in _label:
                _head, _, _tail = _label.rpartition(" (")
                if _tail[:-1].isdigit() and _head:
                    _candidates.append(_head)
            for _cand in _candidates:
                _hit = next((t for t in _unclaimed if t.startswith(_cand)), "")
                if _hit and _hit != _label:
                    parent_prompts[_label] = _hit
                    _unclaimed.remove(_hit)
                    break
        if parent_prompts:
            log.info(
                "tribunal_pipeline: %d of %d client question(s) dispatched with "
                "their full text rather than the 120-char label",
                len(parent_prompts), len(client_questions),
            )

        mission_brief = build_mission_brief_from_winners(
            winners=winners,
            client_questions=client_questions,
            language=run_language,
            deep_research_prompt=deep_research_prompt,
            parent_prompts=parent_prompts,
        )

        # D-LVT — the client's chosen report SHAPE rides on the mission brief rather
        # than through a new parameter, because the mission brief is the ONE object
        # that survives into the synthesis bundle. `_write_final_report` reads it back
        # off `bundle["mission_brief"]` at the zero-touch call site, so no signature
        # anywhere between here and there has to learn about it.
        #
        # ABSENT STAYS ABSENT: an old intake carries no `[REPORT]` block, `report_spec`
        # is `{}`, and the read at the far end resolves to `None` — byte-identical to
        # the report this engine writes today.
        if parsed.report_spec:
            mission_brief["report_spec"] = dict(parsed.report_spec)
            log.info(
                "tribunal_pipeline: the client chose a report shape (%s) and it will "
                "reach synthesis as a directive rather than as prose",
                ", ".join(f"{k}={v}" for k, v in sorted(parsed.report_spec.items())),
            )

        # D-12, reason 1 of 3: everything the workshop itself named. This goes
        # through `_note_degradation` — run()'s ONE accumulator — and includes
        # 15.2-11's own workshop-fallback sentence, so no second wording of it is
        # written here.
        for reason in (workshop_result.get("degradation_reasons") or []):
            _note_degradation(reason)
        if workshop_fallback and not degradation_reasons:
            _note_degradation(
                "The question workshop produced no usable questions of its own, so "
                "this run researched the client-validated questions verbatim and "
                "the added-depth half of the redesign did not run."
            )
        # D-H, said out loud at last. On run d6bb3aae the decision statement fell
        # back to `Deep research for moetest.` and NOTHING reported it — the report,
        # the operator mail and the verification record all showed a clean run.
        if _no_stated_decision:
            _note_degradation(
                "This run had no stated client decision to rank against: the brief "
                "carried no decision block and the question workshop produced none, "
                "so the sub-questions were ranked by how much they matter to the "
                "project's context rather than to a decision. The ranking is "
                "therefore weaker than usual — the questions themselves are the "
                "client's, but the order in which they were researched is less "
                "trustworthy than normal."
            )
        # EVERY workshop note is PERSISTED (D-W4-11, operator ruling 2026-08-04).
        #
        # THE DEFECT THIS CLOSES is the V-01 inert-logging class: the operator's
        # only record that a discovered question was dropped, shed or repaired
        # lived in a `[:4]` log slice. `workshop_rank` folds `loop_notes +
        # disc_notes + group_notes + rider_notes + cov_notes` into this list IN
        # THAT ORDER, and `loop_notes` alone contributes up to 10 per-round drop
        # summaries — so `rider_notes` and `cov_notes` were STRUCTURALLY
        # unreachable behind the slice. Nothing about that was visible in an
        # artifact.
        #
        # `stage="workshop"` is a real `ENGINE_STAGES["tribunal"]` key (label
        # "Question workshop"), so `_stage_event_label` renders it. It is a LABEL
        # ON THE EVENT, not a stage transition — `emit_safe` does not move the
        # run's open stage.
        #
        # `kind="plan"` because `RUN_EVENT_KINDS` is a CLOSED twelve-value
        # vocabulary and `emit` DROPS a row whose kind is not in it — an invented
        # kind is a silently discarded event, which would reproduce the very
        # defect being fixed while every test read green. `plan` is the
        # vocabulary's decision/routing line, and that is what a workshop note is.
        # RENDER TARGET: the `plan` icon is drawn in
        # `docs/design/prototypes/ResearchRunImproved.tsx`, A DESIGN PROTOTYPE
        # AND NOT A SHIPPED COMPONENT. The shipped
        # `frontend/src/components/intake/ResearchRunProgress.tsx` renders the
        # STAGE FEED (`kind: "item" | "summary"`), a different surface. The
        # run-event stream is fetched by `frontend/src/lib/api/research.ts`
        # through `backend/app/api/research_routes.py` and types `kind` as a
        # plain `string` precisely so an unrendered kind still produces a line.
        # So these events ARE persisted and retrievable; no specific rendering is
        # claimed.
        #
        # `meta=None`: `_META_FIELDS` is an allowlist and there is no honest field
        # for a note. The text IS the record, and `emit` already bounds it at
        # `MAX_TEXT_CHARS` with a visible ellipsis.
        # A `workshop_notes` THAT IS NOT A LIST COSTS THE EVENTS, NEVER THE RUN.
        # `list("abc")` would silently emit three single-character events and
        # `list(7)` would raise TypeError here — outside `emit_safe`'s try, which
        # only ever protects the thunk. The isinstance check is the guard.
        _raw_notes = workshop_result.get("workshop_notes")
        _workshop_notes = list(_raw_notes) if isinstance(_raw_notes, list) else []
        for note in _workshop_notes:
            # `n=note` BINDS THE LOOP VARIABLE AT DEFINITION. A bare closure over
            # `note` would capture the LAST iteration's value for every event.
            # `str()` happens INSIDE the thunk, not at the call site — a caller's
            # arguments are evaluated before the callee is entered, so anything
            # built out here is outside `emit_safe`'s protection.
            run_events.emit_safe(
                run_id,
                stage="workshop",
                kind="plan",
                build=lambda n=note: (f"Question workshop — {str(n)}", None),
            )
        # The log keeps its cap, but a SILENT truncation is the V-01 defect. A
        # truncation that names itself is honest.
        for note in _workshop_notes[:4]:
            log.info("tribunal_pipeline: workshop note — %s", note)
        if len(_workshop_notes) > 4:
            log.info(
                "tribunal_pipeline: %d workshop notes in total; the %d not logged "
                "above were still persisted in full as run events",
                len(_workshop_notes),
                len(_workshop_notes) - 4,
            )

        # D-12, reason 3 of 3: a research stream lost before it was ever called.
        _own_lost = own_stream_unavailable_reason()
        if _own_lost:
            _note_degradation(_own_lost)

        # Surface the RESULT (focus areas + stakes) so the research plan the
        # engine decided on stays visible for the whole run and afterwards.
        await set_stage(
            run_id, tenant_id, "intake", detail=_intake_detail(mission_brief)
        )

        # Bail before spending on deep research if the user already cancelled.
        await raise_if_cancelled(run_id, tenant_id)

        # ------------------------------------------------------------------
        # Stage 2: Hybrid research division
        # ------------------------------------------------------------------
        _trims: list[dict[str, Any]] = []
        # THE WIRE THIS PHASE EXISTS TO CLOSE. `groups=` is what makes the groups the
        # workshop decided the groups research is BOUGHT on: without it `divide()`
        # still ran, still produced angles, and still grouped one-per-client-question
        # — the fallback — so the whole grouping call was paid for and thrown away.
        #
        # `winners=` stays, and stays first, because it alone still chooses between
        # `divide()`'s two paths (D-03, no feature flag): truthy winners take the
        # group-dispatch branch, falsy winners take the ORIGINAL focus-area path,
        # which is the workshop-fallback and is out of scope for this phase. `groups`
        # only refines the first branch; it never selects a branch.
        #
        # NO SECOND FALLBACK IS ADDED HERE. When `winners` is truthy and `groups` is
        # empty — a pre-Wave-3 checkpoint, or a stage B that crashed before grouping
        # — `_divide_from_winners` already falls back to one group per client
        # question and logs it exactly once. A guard here would log it twice and give
        # the operator two different accounts of one decision.
        angles = divide(mission_brief, winners=winners, groups=groups, trim_out=_trims)
        # THE OVER-CEILING ALARM IS NOT RAISED HERE, AND THAT IS DELIBERATE.
        # D-W3-2 accepted the fallback's paid-call overshoot ON CONDITION that it is
        # logged loudly (T-15.6-26), and it already is: `_divide_from_winners` calls
        # `question_grouping.warn_if_over_ceiling(len(resolved), len(_D6_STREAMS))`
        # immediately after dispatch, and that sentence names the group count, the
        # call count, the ceiling, and the T-15.2-61 fact that the budget governor is
        # inert under NESTOR_TRIBUNAL_UNCAPPED=1 so the group count is the only real
        # spend control this engine has left. Every run of this pipeline goes through
        # that call. A second warning here would double-log the one alarm the 15.8
        # measuring run reads as its cost signal, and an alarm that fires twice is an
        # alarm an operator learns to discount.

        # R3: the angle list is CHECKPOINTED but never restored, on purpose.
        # `divide()` is pure, deterministic and free, so re-running it costs
        # nothing and keeps `_trims` — which is where two of D-12's degradation
        # reasons come from. What the row is FOR is the digest: it records which
        # questions this run's research answers, so a resume can tell whether a
        # recorded research result still belongs to the question it was bought
        # for (T-15.2-123).
        _live_digest = angles_digest(angles)
        _stored_angle_digest = ckpt.digest_of("angles")
        if _stored_angle_digest is not None and _stored_angle_digest != _live_digest:
            log.warning(
                "tribunal_pipeline: the research angles CHANGED since the last "
                "attempt of this run (checkpoint digest %s, live digest %s) — every "
                "recorded research result will be discarded and the questions "
                "researched fresh, rather than answering the new questions with the "
                "old answers",
                _stored_angle_digest, _live_digest,
                extra={"run_id": str(run_id)},
            )
        await ckpt.put("angles", {"angles": angles}, digest=_live_digest)

        # D-12, reason 2 of 3: a trim that took a sub-question below two
        # independent streams. Depth-only trims are LOGGED by divide() and are
        # deliberately NOT reasons — the client's question is still researched and
        # the merge still has two views of it, and demoting the run for that would
        # be the alarm fatigue D-12 rejects.
        for _trim in _trims:
            if not _trim.get("degrading"):
                continue
            _note_degradation(
                f"Only one research stream covered the sub-question "
                f"\"{str(_trim.get('sub_question') or '')[:80]}\" (under the client "
                f"question \"{str(_trim.get('parent') or '')[:60]}\"), so its "
                f"findings could not be corroborated against a second, independent "
                f"stream."
            )

        # Show the ACTUAL division: each angle, the provider/model it was routed to,
        # and its stakes — a summary header line first.
        _corroborated = len({
            a.get("corroboration_key") for a in angles if a.get("corroboration")
        } - {None, ""})
        # SAY WHERE THE CLIENT QUESTIONS CAME FROM. On run d6bb3aae this header read
        # "32 client question(s) → …" and nothing on the operator's screen hinted
        # that 21 of those 32 were the intake's own administrative fields. One plain
        # clause, in the same register as the rest of the line, puts the split that
        # actually matters in front of the operator.
        _question_source_clause = (
            ", taken from the client's validated question list"
            if parsed.source == "structured"
            else ", detected from a free-prose brief (no question list was supplied)"
        )
        # --- the three Wave 3 clauses, each computed off the ANGLES ---------------
        #
        # 1. MIXED GROUPS — counted by GROUP, not by angle. Every group produces one
        #    angle per stream, so summing a per-angle flag would report three times
        #    the truth. `mixed_parents` is set by `_divide_from_winners` ONLY when a
        #    group holds two different CLIENT questions, never for a client question
        #    plus a discovery rider: under D-W3-5.2 that ride-along IS the intended
        #    shape, and saying so on the operator's page would be exactly the
        #    crying-wolf warning D-W3-5 forbids. This clause is the one place the run
        #    admits that some claims' per-question attribution is an approximation.
        _mixed_groups = len({
            str(a.get("corroboration_key") or "")
            for a in angles
            if a.get("mixed_parents")
        } - {""})
        # 2. RIDE-ALONGS — the saving D-W3-5 was chosen for, and therefore the number
        #    that shows whether it was collected. Also per GROUP: `discovery_riders`
        #    is the same count on all three of a group's angles, so the maximum per
        #    corroboration key is taken and the keys are then summed. Read as an int
        #    with `bool` excluded, because `isinstance(True, int)` is True and a
        #    truthy non-count must not be added to a total.
        _riders_by_group: dict[str, int] = {}
        for _a in angles:
            _key = str(_a.get("corroboration_key") or "")
            _riders = _a.get("discovery_riders")
            if not _key or isinstance(_riders, bool) or not isinstance(_riders, int):
                continue
            if _riders > 0:
                _riders_by_group[_key] = max(_riders_by_group.get(_key, 0), _riders)
        _rider_questions = sum(_riders_by_group.values())
        # 3. UNIFORM DISPATCH — the headline of D-R4/D-W3-1. UNIFORM means every
        #    group kept every COPY: it went out on all three streams and came back
        #    on all three. The decision is taken in exactly one place,
        #    `_dispatch_was_uniform`, and it counts COPIES per corroboration key.
        #
        #    COUNTING KEYS CANNOT SEE A TRIM AND THAT IS WHY THIS CHANGED (WR-06).
        #    `_corroborated` counts DISTINCT keys, so a group trimmed from three
        #    streams down to one still contributes exactly one key — and this line
        #    used to print "every one of those N group(s) went to all 3 research
        #    streams" about precisely that run. The comment that stood here claimed
        #    a trim "keeps the OLD, weaker wording"; it described the intent, and the
        #    arithmetic below it did the opposite. Counting copies is what makes the
        #    sentence true. It matters more than a wording nit because this sentence
        #    is written into the run's own record and plan 15.8-15 reads that record
        #    as the measurement of the whole redesign — once, with no second run.
        #
        #    THE BOUNDARY THIS DELIBERATELY DOES NOT MOVE: `len(groups)` is stage B's
        #    PRE-dispatch group count, so a group that `_bound_groups_to_winners`
        #    dropped whole already makes the counts disagree and already yields the
        #    weaker wording. That is the conservative direction and it is left alone.
        _uniform_dispatch = _dispatch_was_uniform(angles, groups)
        _corroboration_clause = (
            f", and every one of those {len(groups)} group(s) went to all "
            f"{len(_D6_STREAMS)} research streams"
            if _uniform_dispatch
            else (f", {_corroborated} of them checked by several streams"
                  if _corroborated else "")
        )
        _division_items = [{
            "name": (
                f"{len(client_questions)} client question(s) → "
                f"{len(winners)} workshop question(s) → "
                f"{len(groups)} research group(s) → "
                f"{len(angles)} research angle(s)"
                + _corroboration_clause
                + (f", plus {len(discovery_dispatched)} question(s) the evidence "
                   f"raised that the client did not ask"
                   if discovery_dispatched else "")
                + (f", {_mixed_groups} group(s) covering two different client "
                   f"questions (their per-question attribution is an approximation)"
                   if _mixed_groups else "")
                + (f", {_rider_questions} discovered question(s) rode along inside a "
                   f"client question's own group at no extra research call"
                   if _rider_questions else "")
                + _question_source_clause
            ),
            "status": "done",
        }]
        _division_items += [
            {
                "name": (
                    f"{(a.get('focus_area') or '').strip()[:48]} → "
                    f"{_dr_model_display(a.get('provider'))} · {a.get('stakes', 'med')}"
                    + (
                        " · corroboration copy "
                        f"({_angle_copies(angles, a)} streams on the same sub-question)"
                        if a.get("corroboration") else ""
                    )
                ),
                "status": "done",
                # The REAL, self-contained query this angle sends to the
                # researcher (intake's rewritten research_prompt, answers folded
                # in). Surfaced verbatim so the UI shows what is actually sent —
                # not just the short display label. Frontend renders it expandable.
                "prompt": (a.get("query") or "").strip(),
            }
            for a in angles
        ]
        # D-F (e): the division, in numbers, on the stage's own exit line. Every
        # value is the length of a list this method already built.
        _stage_log_counts(
            run_id, "research_division",
            client_questions=len(client_questions),
            workshop_questions=len(winners),
            angles=len(angles),
            corroborated=int(_corroborated),
        )
        await set_stage(
            run_id, tenant_id, "research_division",
            detail={"items": _division_items},
        )
        # Stage 3 (deep research) reports per-angle sub-progress from inside
        # run_angles via the on_progress callback.
        await set_stage(
            run_id, tenant_id, "deep_research",
            detail={"items": [
                {"name": _angle_label(a, i), "status": "pending",
                 "prompt": (a.get("query") or "").strip()}
                for i, a in enumerate(angles)
            ]},
        )
        _angle_status = ["pending"] * len(angles)

        async def _on_angle_done(idx: int, ok: bool) -> None:
            if 0 <= idx < len(_angle_status):
                _angle_status[idx] = "done" if ok else "failed"
            await set_stage(
                run_id, tenant_id, "deep_research",
                detail={"items": [
                    {"name": _angle_label(a, i), "status": _angle_status[i],
                     "prompt": (a.get("query") or "").strip()}
                    for i, a in enumerate(angles)
                ]},
            )

        # ------------------------------------------------------------------
        # R3/R7 — THE MONEY STAGE. Everything below exists so that a resumed run
        # never buys the same deep-research report twice.
        # ------------------------------------------------------------------
        def _restore_for_these_angles(key: str) -> dict:
            """A recorded payload, but ONLY if it belongs to THESE questions.

            The digest is recomputed from the LIVE angle list on every read, and
            a mismatch DISCARDS the whole payload with both digests named. Index-
            keyed restore is therefore only ever applied to the identical angle
            list — otherwise one stream's answer would be attached to another
            stream's question and the report would be wrong while looking healthy
            (T-15.2-123).
            """
            stored = ckpt.get(key)
            if not isinstance(stored, dict):
                return {}
            stored_digest = ckpt.digest_of(key)
            if stored_digest != _live_digest:
                log.warning(
                    "tribunal_pipeline: DISCARDING the %s checkpoint — it was "
                    "recorded for angle digest %s and this run's angles digest to "
                    "%s, so those results answer different questions",
                    key, stored_digest, _live_digest,
                )
                return {}
            return stored

        _recorded_research = _restore_for_these_angles("research")
        _recorded_jobs = _restore_for_these_angles("provider_jobs")

        # Index keys survive a JSON round-trip as STRINGS; job ids are re-checked
        # on the way OUT of the checkpoint as well as on the way in, so a poisoned
        # `output` row can never reach a provider URL (T-15.2-125).
        _resume_results: dict[int, Any] = {}
        for _k, _v in _recorded_research.items():
            try:
                _resume_results[int(_k)] = _v
            except (TypeError, ValueError):
                continue
        _resume_jobs: dict[int, dict[str, Any]] = {}
        for _k, _v in _recorded_jobs.items():
            if not isinstance(_v, dict):
                continue
            _job = safe_job_id(_v.get("job_id"))
            if _job is None:
                continue
            try:
                _resume_jobs[int(_k)] = {
                    "provider": str(_v.get("provider") or ""), "job_id": _job,
                }
            except (TypeError, ValueError):
                continue

        if _resume_results or _resume_jobs:
            log.warning(
                "tribunal_pipeline: RESUMING deep research — %d angle(s) already "
                "have a recorded result and will not be dispatched, and %d in-flight "
                "job(s) will be reconnected to rather than re-dispatched",
                len(_resume_results), len(_resume_jobs),
                extra={"run_id": str(run_id)},
            )

        # The accumulators seed from what is already recorded, so a second crash
        # keeps the first attempt's angles too.
        _research_done: dict[str, Any] = dict(_recorded_research)
        _jobs_in_flight: dict[str, Any] = dict(_recorded_jobs)

        async def _record_angle(idx: int, provider: str, result: dict) -> None:
            """Checkpoint after EVERY completed angle, not at the end of the stage.

            A crash halfway through deep research must still leave the finished
            angles recorded — that is the difference between losing one angle and
            losing twenty.
            """
            _research_done[str(idx)] = [provider, result]
            await ckpt.put("research", _research_done, digest=_live_digest)

        async def _record_job(idx: int, provider: str, job_id: str) -> None:
            checked = safe_job_id(job_id)
            if checked is None:
                return
            _jobs_in_flight[str(idx)] = {"provider": provider, "job_id": checked}
            await ckpt.put("provider_jobs", _jobs_in_flight, digest=_live_digest)

        try:
            provider_results = await run_angles(
                angles=angles,
                audited=audited,
                run_id=run_id,
                tenant_id=tenant_id,
                on_angle_done=_on_angle_done,
                resume_results=_resume_results,
                resume_jobs=_resume_jobs,
                on_angle_result=_record_angle,
                on_job_started=_record_job,
            )
        except InsufficientProvidersError as exc:
            # F6. Losing EVERY research stream is a PARK, not a failure: there is
            # nothing to verify and nothing to report on, but everything already
            # paid for is on disk and a resume is free. The raise sites in
            # `research_division.py` / `degraded_parallel.py` are untouched — only
            # this catch is new (DEC-6: facts here, the decision in the worker).
            _streams = len(getattr(exc, "failed", None) or []) or len(angles) or 1
            _reasons = list((getattr(exc, "reasons", None) or {}).values())
            reason = (
                "No research provider produced a usable result for this run, so "
                "there is nothing to verify or report on yet. Everything already "
                "paid for has been kept and the run can be resumed. Provider "
                f"signal: {error_signature(exc)}"
            )
            parked = _park_result(
                stage="deep_research",
                reason=reason,
                prior_park=ckpt.get("park"),
                terminal_inputs={
                    # streams_lost == streams_total is what makes terminal_state()
                    # return "parked" (D-17). The pipeline never says "parked".
                    "streams_lost": _streams,
                    "streams_total": _streams,
                    "verify_ran": False,
                    "synthesis_ran": False,
                    "hard_wall": False,
                    "degradation_reasons": list(degradation_reasons) + [
                        str(r) for r in _reasons if str(r or "").strip()
                    ],
                },
            )
            await ckpt.put("park", parked["park"])
            log.error(
                "tribunal_pipeline: PARKED at deep_research — %s",
                parked["park"]["reason"], extra={"run_id": str(run_id)},
            )
            return parked

        # ------------------------------------------------------------------
        # Stage 3: Claim collection — the streams' own fact lists come first
        # ------------------------------------------------------------------
        # D8/D-03/D-14 (15.2-14 + 15.2-15). This stage USED to hand the entire
        # `provider_results` corpus to `claim_distiller`, which shredded every
        # provider's prose into claims whether or not the provider had supplied a
        # structured list of its own facts. That is the distiller-as-primary-
        # source wiring, and it is what D-03 unwires: a provider that states
        # "Aral's German fuel market share is 16%, certainty: single, source:
        # official" knows more about its own finding than a paraphrase of its
        # prose ever will, and that extra — certainty, per-source quality, the
        # display label — is exactly D-13's metadata.
        #
        # `collect_provider_facts` reads each stream D8-first and falls back to
        # `claim_distiller` PER PROVIDER (one-element report list, full-extraction
        # mode) only for a stream that produced no usable list. The distiller is
        # therefore demoted, never deleted (D-15).
        n_ok_angles = sum(1 for _, r in provider_results if r and r.get("status") == "success")
        n_streams = len({str(name or "") for name, _ in provider_results})
        # D-F (e) — THE MONEY STAGE'S THREE NUMBERS, recorded before the next
        # transition closes `deep_research`. These are the counts that would have
        # answered "did anything come back" during run d6bb3aae's silent stretch.
        # They are read from `provider_results` rather than from the `_angle_status`
        # feed list, because a resumed run restores results without ever firing the
        # per-angle callback — the feed list would say "pending" for work that was
        # already paid for and delivered.
        _stage_log_counts(
            run_id, "deep_research",
            angles_dispatched=len(angles),
            angles_ok=int(n_ok_angles),
            angles_failed=max(0, len(provider_results) - int(n_ok_angles)),
            streams=int(n_streams),
        )
        await set_stage(
            run_id, tenant_id, "distill",
            detail={"items": [{
                "name": (
                    f"reading the fact lists of {n_streams} research stream(s) "
                    f"across {n_ok_angles} report(s)…"
                ),
                "status": "running",
            }]},
        )
        facts_result = await collect_provider_facts(
            provider_reports=provider_results,
            mission_brief=mission_brief,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )
        claims = list(facts_result.claims)

        # 15.2-14 contract (b): `reports` is a DROP-IN replacement for
        # `provider_results` — same length, same order, same tuple/dict shape —
        # with the machine-readable fact block already stripped out of the prose.
        # Rebinding the name ONCE here is what makes every downstream consumer
        # (`_extract_sources_for_group`, `_extract_sources_for_claim`,
        # `scrub_research`, synthesis) see clean report text. Leaving the block in
        # would double-count every fact and render as tab-salad in the deliverable.
        provider_results = list(facts_result.reports)

        # The couldn't-find lines, ATTRIBUTED, on their way to `research_gap`
        # (Stage 7 hands them to persist_tribunal_claims; 15.2-06 reads them back
        # into the report's "What we could not establish" section). A run where
        # every stream established everything it looked for writes no rows.
        research_gaps: list[dict] = list(facts_result.not_found_by_provider)

        # Which streams fell back to the distiller, and 15.2-04's own plain-English
        # reason, verbatim. NOT a degradation: per D-14 a fallback degrades one
        # stream, not the run, so this list is deliberately kept OUT of
        # `_note_degradation` / `degradation_reasons` / `terminal_state()`. The
        # provider's research still reached the merge in full.
        _fallen_back_records = [r for r in facts_result.records if r.reports_fell_back > 0]
        # `fallback_notes` is built by the SAME filter over the SAME iteration
        # order, so the two line up one-to-one — but that is a coupling between
        # two loops in another module, so it is CHECKED rather than assumed. A
        # mismatch costs the sentence, never the record.
        _notes = list(facts_result.fallback_notes)
        if len(_notes) != len(_fallen_back_records):
            log.warning(
                "tribunal_pipeline: %d fallback note(s) for %d fallen-back stream(s) "
                "— the per-provider sentences are omitted rather than mis-attributed",
                len(_notes), len(_fallen_back_records),
            )
            _notes = []
        factlist_fallbacks: list[dict] = []
        for _i, _record in enumerate(_fallen_back_records):
            _entry = {"provider": _record.provider, "reason": _record.reason or ""}
            if _i < len(_notes):
                # The count-bearing sentence an operator reads, built by 15.2-14
                # from the provider name and integers only (T-15.2-66).
                _entry["note"] = _notes[_i]
            factlist_fallbacks.append(_entry)

        _n_from_lists = sum(r.facts_from_list for r in facts_result.records)
        _n_from_fallback = sum(r.claims_from_fallback for r in facts_result.records)
        _fell_back = [r.provider for r in _fallen_back_records]
        await set_stage(
            run_id, tenant_id, "distill",
            detail={"items": [{
                "name": (
                    f"{len(claims)} claims collected · {_n_from_lists} stated by the "
                    f"streams themselves · {_n_from_fallback} extracted from prose by "
                    f"the fallback distiller"
                    + (
                        " · no stream had to fall back"
                        if not _fell_back
                        else (
                            " · these streams returned no usable fact list and were "
                            f"distilled instead: {', '.join(_fell_back)}"
                        )
                    )
                    + (
                        f" · {len(research_gaps)} thing(s) a stream said it could not "
                        "establish"
                        if research_gaps else ""
                    )
                ),
                "status": "done",
            }]},
        )

        if not claims:
            log.warning("tribunal_pipeline: no claims distilled — returning empty synthesis")
            # RESEARCH Pitfall 10: this hand-built skeleton used to carry no funnel
            # at all, so the zero-claim path reported a DIFFERENT shape from the
            # full path and every consumer had to branch on which one it got. Same
            # builder, all keys, all zero — and the same top-level carrier key, so
            # the worker's persistence path does not branch on the path either.
            _empty_funnel = _build_funnel(None, unchecked_selected=0, verify_sessions=0)
            return {
                "output_text": "(No claims could be distilled from the research reports.)",
                "claim_count": 0,
                "verdict": {"pass": None, "error": "no_claims"},
                "verification_report": {
                    "verdicts": {},
                    "dropped_count": 0,
                    "budget_marker": "",
                    "coverage": {"pass": True, "uncovered": []},
                    "funnel": _empty_funnel,
                },
                "verification_summary": _empty_funnel,
                # D-12: the same top-level carrier key the full path publishes, for
                # the reason the comment above already gives — the worker's
                # persistence path never branches on which path produced its input.
                # A zero-claim run has nothing to say, so the list is empty, never
                # absent.
                "degradation_reasons": list(degradation_reasons),
            }

        # ------------------------------------------------------------------
        # Stage 4: Stakes triage + verification (GROUPED by default, per-claim fallback)
        # ------------------------------------------------------------------
        # Propagate each focus-area's stakes (from intake) onto its claims so the
        # adaptive triage actually differentiates effort. claim_distiller emits
        # {text, facet, evidence} with NO stakes; without this every claim defaulted
        # to med (2 skeptics) and the ADR-006 high=3/low=0 tiering never fired.
        #
        # THIS RUNS BEFORE THE MERGE, deliberately: a group inherits the MAX stakes
        # of its members, so a group formed before stakes were propagated would
        # inherit `med` for everything and the tiering would be dead again.
        _propagate_stakes(claims, mission_brief)

        # ------------------------------------------------------------------
        # Stage 3.5: CROSS-PROVIDER MERGE (D9 / D11)
        # ------------------------------------------------------------------
        # THE ORDERING DECISION, recorded here because it is the whole point of
        # this stage. Until 15.2 the clusterer ran AFTER the gates, inside the
        # grouped-verify branch. That meant the gates judged claims one research
        # stream at a time, and two providers contradicting each other were two
        # unrelated claims that were checked in two unrelated skeptic sessions,
        # each of which found its own supporting source and passed. That is
        # exactly how run 4cbb5311 published Aral's German fuel market share at
        # both 16% and 21%, and LUKOIL's international operations as sold to both
        # Gunvor and Carlyle. D11 inverts the order: all four streams' claims are
        # merged into ONE clustered list FIRST, so a contradiction lands in one
        # group and therefore in one skeptic session that can reconcile it.
        #
        # WHAT DID NOT CHANGE:
        #  * The gates stay PER CLAIM (G-04). Only their position moved. A cluster
        #    is still worth a session as soon as ANY member survived the gates —
        #    `_group_selected` — and `apply_gates` MUTATES the same claim dicts the
        #    groups hold by identity, so gating after clustering still gives every
        #    group its members' gate decisions.
        #    The regression that proves the semantics did not change is
        #    `test_gate_replay.py::test_cluster_survives_if_any_member_survives`.
        #  * The COST. `group_claims` always ran over the full claim list, never
        #    the gate-selected subset, so moving it earlier changes zero clustering
        #    calls. This is a reorder, not a cost increase.
        #  * The clusterer itself. `group_claims` is called, not modified, not
        #    wrapped and not duplicated (B-04) — there is one clusterer.
        await raise_if_cancelled(run_id, tenant_id)
        await set_stage(
            run_id, tenant_id, "merge",
            detail={"items": [{
                "name": (
                    f"merging {len(claims)} facts from {n_streams} research "
                    f"stream(s) into one clustered list…"
                ),
                "status": "running",
            }]},
        )

        # --- Deterministic half -------------------------------------------------
        # `collect_provider_facts` already ran this exact function once over all
        # streams at collection time, so this call is normally a no-op and is here
        # as the merge's own guarantee rather than as the primary collapse: nothing
        # downstream of this line may see two copies of one statement. The number
        # an operator wants is the WHOLE path's collapse, so it is measured against
        # what the streams produced, not against this call's input.
        _n_stream_claims = sum(
            r.facts_from_list + r.claims_from_fallback for r in facts_result.records
        )
        claims = _dedupe_claims(claims)
        n_dupes_merged = max(0, _n_stream_claims - len(claims))

        # --- D-R8: THE ASSIGNMENT-YIELD INSERT SEAM ----------------------------
        # WHY HERE, and not inside `run_angles`. `record_assignment` needs
        # `fact_list_parsed`, `claims_kept` and `resolvable_sources`, and NONE of
        # the three exists inside `run_angles`: the three live adapters return a
        # `{status, report}` envelope, and the fact list is parsed later, in
        # `collect_provider_facts`. So "research resolved" for this table means THE
        # DISTILL BOUNDARY — the first point at which the research half is complete
        # and THE LAST POINT BEFORE THE PIPELINE SPENDS ANOTHER CENT. Everything
        # upstream that this needs (cost, duration, the retry flag, the assignment
        # identity) travelled here stamped on the enriched result — and since the
        # CR-01 repair so do `fact_list_parsed` and `resolvable_sources`, stamped
        # by `collect_provider_facts` BEFORE its dedupe unioned the answer away.
        # `provider_results` is `facts_result.reports` from the distill stage,
        # which is what carries them; do not re-point this at the pre-distill list.
        #
        # ⚠ AND BEFORE THE `groups` REBIND TWELVE LINES DOWN. That line REBINDS the
        # name `groups` from the workshop's QUESTION groups to CLAIM groups —
        # anything below it reading `groups` is reading claim groups. Neither seam
        # reads `groups` at all, and this one sits above the rebind so that stays
        # obviously true.
        #
        # `claims_kept` and `claims_surviving_verification` deliberately share ONE
        # DENOMINATOR BASIS: both are counted over POST-`_dedupe_claims` claim
        # objects. Counting the kept half pre-dedupe and the survivor half
        # post-dedupe would make the ratio quietly wrong in the one measured run.
        _yield_rows: list[dict[str, Any]] = []
        try:
            _yield_rows = _assignment_yield_rows(provider_results, claims)
            for _row in _yield_rows:
                # The row is bound as a DEFAULT ARGUMENT and NEVER captured: a
                # captured `_row` is looked up when the thunk RUNS, so the
                # late-binding closure bug would put the LAST row in every call.
                await yield_records.record_assignment_safe(
                    run_id, tenant_id, build=lambda _r=_row: _r,
                )
            _distinct_keys = {
                (r.get("provider"), r.get("group_id"), r.get("client_question"))
                for r in _yield_rows
            }
            # A row count ABOVE the distinct-key count is the signal that a RESUME
            # or `divide()`'s doubled high-stakes fallback copy is in play, and this
            # is the only place a reader sees it before querying the table. The
            # duplicates are deliberately NOT collapsed: collapsing would hide the
            # very condition the completer's not-exactly-one warning exists to
            # surface. READER-SIDE RULE: dedupe on the natural key before any SUM.
            log.info(
                "tribunal_pipeline: D-R8 offered %d assignment_yield row(s) across "
                "%d distinct natural key(s)%s",
                len(_yield_rows), len(_distinct_keys),
                (" — MORE ROWS THAN KEYS: a resumed angle or a doubled high-stakes "
                 "copy is present; dedupe on (run_id, provider, group_id, "
                 "client_question) before any SUM"
                 if len(_yield_rows) > len(_distinct_keys) else ""),
            )
        except Exception as exc:  # noqa: BLE001 — telemetry may never end a paid run
            log.warning(
                "tribunal_pipeline: the assignment-yield INSERT seam failed (%s: "
                "%s) — the research half of this run's yield measurement is lost; "
                "the run itself is unaffected",
                type(exc).__name__, exc,
            )

        # --- LLM half, gated exactly as the clusterer was gated before ----------
        groups: list[dict[str, Any]] = []
        multi = 0
        if _GROUP_VERIFY:
            try:
                groups = await group_claims(
                    claims=claims, audited=audited, run_id=run_id, tenant_id=tenant_id,
                )
            except Exception as exc:  # noqa: BLE001
                # NEVER-DROP, at the pipeline level this time: a failed merge must
                # not fail the run and must not lose a claim. One singleton group
                # per claim is the same degradation `grouping.py` applies
                # internally — every claim is still gated, still verifiable, and
                # still gets its own session.
                log.warning(
                    "tribunal_pipeline: cross-provider merge failed (%s) — falling "
                    "back to one singleton group per claim; no claim was lost",
                    exc, exc_info=True,
                )
                groups = [
                    {
                        "key": f"__singleton__:{i}",
                        "entity": "",
                        "attribute": "general",
                        "claims": [claim],
                        "stakes": claim.get("stakes", "med"),
                    }
                    for i, claim in enumerate(claims)
                ]
            multi = sum(1 for g in groups if len(g["claims"]) > 1)
        n_groups = len(groups)

        # D9's priority rule is `_group_corroboration` and `_corroboration_order`,
        # which are already in production above. Nothing new counts corroboration.
        n_corroborated = sum(1 for g in groups if _group_corroboration(g) >= 2)

        _merge_row = (
            f"{len(claims)} facts merged into {n_groups} cluster(s) "
            f"({multi} holding more than one stream's version of the same fact) · "
            f"{n_corroborated} cluster(s) corroborated by two or more streams · "
            f"{n_dupes_merged} duplicate statement(s) collapsed into one"
        )
        if not _GROUP_VERIFY:
            # FAIL LOUD, IN WORDS. Skipping the clusterer is not a neutral
            # configuration detail: it is the difference between a contradiction
            # being reconciled and a contradiction shipping.
            _merge_row = (
                f"{len(claims)} facts deduplicated, but cross-provider clustering "
                f"was SKIPPED because the per-claim A/B baseline is selected "
                f"(NESTOR_TRIBUNAL_GROUP_VERIFY=false) — contradicting facts from "
                f"different research streams will NOT share a skeptic session and "
                f"can both survive into the report · "
                f"{n_dupes_merged} duplicate statement(s) collapsed into one"
            )
        if factlist_fallbacks:
            _merge_row += (
                " · these streams stated no facts of their own and were distilled "
                "from prose instead: "
                + ", ".join(
                    f"{f['provider']} ({f['reason']})" if f.get("reason") else f["provider"]
                    for f in factlist_fallbacks
                )
            )
        await set_stage(
            run_id, tenant_id, "merge",
            detail={"items": [{"name": _merge_row, "status": "done"}]},
        )
        log.info("tribunal_pipeline: merge stage — %s", _merge_row)

        # ------------------------------------------------------------------
        # Stage 3.6: Verification gates (G-01 / G-02 / G-11)
        # ------------------------------------------------------------------
        # Two cheap per-claim gates decide WHICH claims are worth fact-checking:
        # materiality (falsifiable-specific AND load-bearing for THIS client's
        # decision) and error-likelihood (a stable, notorious fact is skipped).
        # From here on the gate result is the SINGLE answer to "what gets
        # checked" — stakes no longer selects, it only sets how deep a surviving
        # session goes (G-02, _GROUP_DEPTH).
        #
        # G-04 ordering note (REVISED by D11, 15.2-15): clustering now happens
        # ABOVE, in the merge stage, so the gates see one merged four-stream claim
        # list instead of one stream's at a time. The gate DECISION is still PER
        # CLAIM and still the only thing consulted for survival, so the per-claim
        # keep/drop numbers reproduce exactly as before; a cluster survives if ANY
        # member survived. `apply_gates` mutates the same claim dicts the groups
        # already hold by identity, which is why gating after clustering still
        # gives `_group_selected` every member's decision.
        #
        # The gate is a cheap flash fan-out, but it is still a fan-out, and every
        # other fan-out in this pipeline cancel-checks first.
        await raise_if_cancelled(run_id, tenant_id)

        # R3: record the merged claim list and the cluster shape BEFORE the gates
        # run. Everything above this line — `collect_provider_facts` (which may
        # fall back to the paid distiller per stream) and `group_claims` (a paid
        # clusterer call) — is what this row would let a future resume skip.
        #
        # GROUPS ARE STORED BY CLAIM INDEX, not by nesting the claim dicts again.
        # `_group_selected` works because `apply_gates` MUTATES the very dicts the
        # groups hold BY IDENTITY, and identity is exactly what a JSON round-trip
        # destroys. Index references are the only shape a restore can rebuild that
        # coupling from.
        #
        # WRITE-ONLY IN THIS PLAN — no restore branch is wired for `merge`,
        # `gates` or `verify`. See the SUMMARY and `deferred-items.md`: the
        # restore needs the index-rebuild above to be exercised end-to-end, and
        # the stubbed full-pipeline harness that could prove it is not in the tree
        # yet. A checkpoint that is written but not yet read costs nothing and
        # loses nothing; a restore branch nothing exercises could corrupt a paid
        # run, which is the trade this plan refuses to make silently.
        _claim_index = {id(_c): _i for _i, _c in enumerate(claims)}
        await ckpt.put("merge", {
            "claims": claims,
            "groups": [
                {
                    "key": _g.get("key"),
                    "entity": _g.get("entity"),
                    "attribute": _g.get("attribute"),
                    "stakes": _g.get("stakes"),
                    "claim_indexes": [
                        _claim_index[id(_m)] for _m in (_g.get("claims") or [])
                        if id(_m) in _claim_index
                    ],
                }
                for _g in groups
            ],
        })

        await set_stage(
            run_id, tenant_id, "gate",
            detail={"items": [{
                "name": f"gating {len(claims)} claims…", "status": "running",
            }]},
        )
        gate_result = await apply_gates(
            claims=claims,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
            decision_context=_gate_decision_context(mission_brief),
        )
        gate_funnel: dict[str, Any] = gate_result["funnel"]
        # D-F (e): claims in, claims selected for checking. Taken straight off the
        # funnel the gates just returned — the same numbers the feed row renders.
        _stage_log_counts(
            run_id, "gate",
            claims_in=int(gate_funnel.get("distilled") or 0),
            selected_for_checking=int(gate_funnel.get("selected_verify") or 0),
            not_checkable=int(gate_funnel.get("dropped") or 0),
            gate_errors=int(gate_funnel.get("gate_errors") or 0),
        )
        await set_stage(
            run_id, tenant_id, "gate",
            detail={"items": [{
                "name": (
                    f"{gate_funnel['selected_verify']} of {gate_funnel['distilled']} claims "
                    f"selected for checking · {gate_funnel['dropped']} not checkable · "
                    f"{gate_funnel['skipped_stable']} stable facts skipped"
                    + (f" · {gate_funnel['gate_errors']} gate errors (sent for checking)"
                       if gate_funnel["gate_errors"] else "")
                ),
                "status": "done",
            }]},
        )

        # R3: the gate decisions now live ON the claim dicts (apply_gates mutates
        # them), so recording the claims records the decisions with them.
        await ckpt.put("gates", {"claims": claims, "funnel": gate_funnel})

        # D-17 input: COULD the verification stage run at all? When every gate
        # call errored there is no selection to verify against, and a run that
        # ships unverifiable claims as `completed` is the 2026-07-22 incident all
        # over again. This does NOT park inline — it is a FACT carried into
        # `terminal_inputs`, and `terminal_state()` makes the call (DEC-6).
        _distilled = int(gate_funnel.get("distilled") or 0)
        _gate_errors = int(gate_funnel.get("gate_errors") or 0)
        verify_ran = not (_distilled > 0 and _gate_errors >= _distilled)
        if not verify_ran:
            log.error(
                "tribunal_pipeline: THE VERIFICATION GATES COULD NOT RUN — %d of "
                "%d claims errored at the gate, so nothing was selected on the "
                "evidence and no honest verification is possible for this run",
                _gate_errors, _distilled, extra={"run_id": str(run_id)},
            )

        # Skeptic verification is the most expensive stage — check for a user cancel
        # before fanning out, and again between batches below.
        await raise_if_cancelled(run_id, tenant_id)

        # verdicts_by_claim: id(claim) -> list[verdict_dict]. Seed EVERY claim so
        # adjudication sees all of them (a claim with no verdicts survives).
        verdicts_by_claim: dict[int, list[dict]] = {id(c): [] for c in claims}
        budget_exceeded = False
        total_skeptics = 0
        group_reconciliations: list[dict] = []  # scoped/disputed notes from group skeptics
        # CR-01 / G-07: `[SUPERSEDED] <claim>: <note>` caveats harvested during group
        # flushing and merged into contested_notes below, so the note reaches synthesis.
        # ONLY the grouped path fills this: `superseded_note` is produced exclusively by
        # group_skeptic._parse_group_verdict — the per-claim EMIT_VERDICT_TOOL keeps the
        # three-word vocabulary — so the per-claim branch is deliberately left alone.
        superseded_notes: list[str] = []
        # `n_groups` / `multi` are NOT re-initialised here: D11 moved the clusterer
        # to the merge stage ABOVE the gates, so both are already final by the time
        # this block runs and a re-init would zero the numbers the verify feed rows
        # and the closing log line report.
        _sm = get_sessionmaker()
        sem = asyncio.Semaphore(_SKEPTIC_CONCURRENCY)

        # The skeptic provider's circuit, named by (provider, stage) as plan 02's
        # CircuitBreaker docstring specifies. It is what D-11's coverage-re-entry
        # gate reads (D-07-C) — and until this stage started RECORDING outcomes on
        # it, that gate was decorative: with no failure ever booked the breaker
        # could never trip, so "a tripped provider means no re-entry" was a
        # statement about a state nothing could reach. On 2026-07-22 the Anthropic
        # monthly cap hard-400'd 776 sessions in 55 seconds and nothing in the
        # process noticed.
        skeptic_breaker = breakers.get("anthropic:skeptic")

        # Breaker bookkeeping is BEST-EFFORT (Shared Pattern 6): a bookkeeping
        # error must never kill a batch of results that already came back. The
        # VERIFICATION LOSS is a different thing entirely — it is counted by
        # `_book_unchecked` below, which is Pattern 5 and is NOT best-effort.
        def _note_skeptic_ok() -> None:
            try:
                skeptic_breaker.record_success()
            except Exception as exc:  # noqa: BLE001
                log.warning("tribunal_pipeline: skeptic breaker success bookkeeping failed: %s", exc)

        def _note_skeptic_failure(exc: BaseException) -> None:
            try:
                skeptic_breaker.record_failure(exc)
            except Exception as bexc:  # noqa: BLE001
                log.warning("tribunal_pipeline: skeptic breaker failure bookkeeping failed: %s", bexc)

        # G-08 BUCKET 3 — claims the gates SELECTED for checking that did not get
        # checked: a crashed or timed-out session, the budget cap, a failed
        # coverage re-entry. Before this existed all three losses were a bare
        # `continue` and the run reported them as if they had been verified.
        #
        # This is the phase's most important number and must be ZERO on a healthy
        # run. It is not a bookkeeping line: only a REFUTATION scrubs a passage out
        # of the research prose, so an unchecked claim's passage ships unexamined —
        # which is how one run published Aral's share at both 16% and 21%.
        #
        # Tracked by identity as well as counted so a claim lost twice (crashed
        # group, then a failed re-entry) is booked once.
        unchecked_ids: set[int] = set()
        unchecked_selected = 0

        def _book_unchecked(lost_claims, cause: str) -> None:
            """Count + LOG selected-but-unchecked claims (V7: never swallowed)."""
            nonlocal unchecked_selected
            newly = [
                c for c in lost_claims
                if (c.get("gate") or {}).get("strict") == "VERIFY"
                and id(c) not in unchecked_ids
            ]
            if not newly:
                return
            unchecked_ids.update(id(c) for c in newly)
            unchecked_selected = len(unchecked_ids)
            log.warning(
                "tribunal_pipeline: %d selected claim(s) NOT checked (%s) — bucket 3 "
                "now %d; their passages ship unexamined",
                len(newly), cause, unchecked_selected,
            )

        # Per-claim skeptic caller — used by the per-claim branch AND by the
        # coverage-gate re-entry (which targets specific uncovered high-stakes
        # claims one at a time, in either verification mode). Defined once here so
        # it is always available regardless of which branch runs below.
        async def _one_skeptic(claim: dict, sources: list) -> dict | None:
            async with sem:
                try:
                    async with asyncio.timeout(_SKEPTIC_TIMEOUT_S):
                        result = await run_skeptic(
                            claim=claim, sources=sources, audited=audited,
                            run_id=run_id, tenant_id=tenant_id, model=_SKEPTIC_MODEL,
                        )
                    _note_skeptic_ok()
                    return result
                except Exception as exc:
                    _note_skeptic_failure(exc)
                    log.warning(
                        "tribunal_pipeline: skeptic failed/timeout for claim %r: %s",
                        claim.get("text", "")[:60], exc,
                    )
                    return None

        # 21-03: ONE row budget for the verify STAGE, spanning BOTH branches
        # below. Bounding per stage rather than per branch means the ceiling is a
        # property of what the operator sees under "Skeptic verification", not of
        # which verification mode happened to run. Flushed once at the stage's
        # close, so any elision row lands before the next stage's divider.
        _verify_budget = stage_events.RowBudget(run_id, "verify")

        if _GROUP_VERIFY:
            # --- Grouped verification (plan Phase 3) ---------------------------
            # Claims about the same entity|attribute are verified TOGETHER in ONE
            # thorough skeptic session that also reconciles contradictions. Stakes
            # controls the DEPTH of that single session (searches/fetches), NOT the
            # number of sessions — so the call count drops from ~3-per-claim to
            # ~1-session-per-GROUP. WHICH groups run is the gates' call (G-02), not
            # stakes': a low-stakes group with a load-bearing claim is now checked
            # (shallowly), and a high-stakes group of unfalsifiable claims is not.
            #
            # THE CLUSTERING NO LONGER HAPPENS HERE (D11, 15.2-15). `groups`,
            # `n_groups` and `multi` were all computed by the merge stage above,
            # BEFORE the gates ran — that reordering is the whole of D11 and the
            # reason a cross-provider contradiction now reaches one session. This
            # branch is a pure consumer of them; the "grouping N claims…" feed row
            # moved with the work it described.
            #
            # G-02: the QUEUE is what the gates selected, not what stakes allowed.
            # `queue` is also the iteration order — single-source clusters first.
            queue = [g for g in _corroboration_order(groups) if _group_selected(g)]
            total_passes = len(queue)
            done_passes = 0

            async def _verify_detail(done: int) -> None:
                await set_stage(
                    run_id, tenant_id, "verify",
                    detail={"items": [{
                        "name": (f"{min(done, total_passes)} / {total_passes} group checks · "
                                 f"{n_groups} groups ({multi} multi-claim) · "
                                 f"{gate_funnel['selected_verify']} of {len(claims)} claims selected"),
                        "status": "running",
                    }]},
                )

            # 21-03: the stage's ONE dispatch header, naming the work and its
            # counts. It carries the same five numbers `_verify_detail` renders,
            # so the run page and the intake card cannot disagree about how much
            # of this run was actually checked.
            stage_events.emit_verify_dispatch(
                run_id,
                groups_selected=total_passes,
                groups_total=n_groups,
                multi=multi,
                claims_selected=gate_funnel["selected_verify"],
                claims_total=len(claims),
            )
            await _verify_detail(0)

            async def _one_group_pass(group: dict, sources: list) -> dict | None:
                turns, su, fu = _GROUP_DEPTH.get(group.get("stakes", "med"), _GROUP_DEPTH["med"])
                async with sem:
                    try:
                        async with asyncio.timeout(_SKEPTIC_TIMEOUT_S):
                            result = await run_group_skeptic(
                                group=group, sources=sources, audited=audited,
                                run_id=run_id, tenant_id=tenant_id, model=_SKEPTIC_MODEL,
                                max_turns=turns, max_search_uses=su, max_fetch_uses=fu,
                            )
                        _note_skeptic_ok()
                        return result
                    except Exception as exc:
                        _note_skeptic_failure(exc)
                        log.warning(
                            "tribunal_pipeline: group skeptic failed for %r|%r: %s",
                            group.get("entity"), group.get("attribute"), exc,
                        )
                        return None

            pending: list = []
            owners: list = []

            async def _flush_groups() -> None:
                nonlocal done_passes
                if not pending:
                    return
                n = len(owners)
                results = await asyncio.gather(*pending)
                for grp, res in zip(owners, results):
                    if res is None:
                        # Bucket-3 site (a): the session crashed or timed out. Its
                        # selected claims got no verdict and never will.
                        _book_unchecked(grp["claims"], "group session crashed or timed out")
                        # 21-03: and SAY SO, naming the cluster and the cause. An
                        # absence in the feed reads as "not reached yet"; this
                        # reads as "never checked", which is what it is.
                        stage_events.emit_verify_group_failed(
                            run_id, _verify_budget, group=grp,
                            reason="the skeptic session crashed or timed out",
                        )
                        continue
                    vbi = res.get("verdicts_by_index", {})
                    # ENGINE-10: harvested BEFORE the member loop (it used to be
                    # read after it) so each verdict can carry it into the
                    # Stage-7 writer. report.py builds the top-level `reconciled`
                    # and `superseded` sections from the verdict ROW's
                    # `reconciliation` column, so a recon that never reaches a
                    # verdict leaves those sections empty however good the writer.
                    recon = res.get("reconciliation") or {}
                    # ...but ONLY when the recon carries meaning — see the
                    # module-level `_recon_is_meaningful`, which the coverage
                    # re-entry path shares rather than forking.
                    recon_meaningful = _recon_is_meaningful(recon)
                    # WR-10 / D-10 Option 2 — DO NOT FILTER THIS LOOP.
                    #
                    # Every member of a selected group is filed, including the ones
                    # the gates DROPped and the ones marked SKIP_STABLE. Those
                    # verdicts are REAL: they reach `adjudicate_all`, they can
                    # refute a claim, and `scrub_research` then deletes the refuted
                    # passage from the delivered report.
                    #
                    # Option 1 — skip non-VERIFY members here — was explicitly
                    # REJECTED by the operator: it silently stops scrubbing passages
                    # that are removed today, making the report LESS verified in
                    # exchange for tidier books. So the behaviour stays and the
                    # ACCOUNTING was fixed instead: `_count_incidental` counts these
                    # claims, the funnel publishes them as `checked_incidentally`,
                    # and verification/report.py subtracts them from bucket 2 per
                    # reason. Adding a `continue`, a `strict != "VERIFY"` test or any
                    # other filter here re-opens the defect that fix was for.
                    for i, c in enumerate(grp["claims"]):
                        v = vbi.get(i)
                        if v is not None:
                            if recon_meaningful:
                                # dict(...) COPIES rather than aliases: a later
                                # mutation of the group result must not reach a
                                # verdict already built.
                                v["reconciliation"] = dict(recon)
                            verdicts_by_claim[id(c)].append(v)
                    # 21-03: the cluster's FINISH row and then its individual
                    # verdicts. BOTH SIT OUTSIDE THE MEMBER LOOP ABOVE, ON
                    # PURPOSE. That loop carries the WR-10 "DO NOT FILTER THIS
                    # LOOP" comment, and a call placed inside it invites a later
                    # reader to add a condition next to it — which is precisely
                    # the defect that comment exists to prevent. One finish row
                    # per cluster, one verdict row per refutation or supersession,
                    # all bounded by the stage's row budget.
                    stage_events.emit_verify_group_done(
                        run_id, _verify_budget, group=grp, verdicts=vbi,
                    )
                    stage_events.emit_verify_verdicts(
                        run_id, _verify_budget, group=grp, verdicts=vbi,
                    )
                    # CR-01: carry this group's superseded caveats out before the
                    # verdict dicts disappear into verdicts_by_claim, where G-07's
                    # note used to die. Merged into contested_notes below.
                    superseded_notes.extend(_collect_superseded_notes(grp["claims"], vbi))
                    # Unchanged consumer — this one feeds contested_notes, and its
                    # narrower condition is deliberate. Do not fold it into the
                    # meaningfulness test above.
                    if recon.get("disputed") or recon.get("relation") == "scoped":
                        group_reconciliations.append({
                            "entity": grp.get("entity"), "attribute": grp.get("attribute"),
                            **recon,
                        })
                pending.clear()
                owners.clear()
                done_passes += n
                await _verify_detail(done_passes)

            # `queue` is gate-selected and corroboration-ascending: single-source
            # clusters are checked first (D9), so if the budget cap truncates the
            # tail, what got dropped is the best-corroborated work.
            for group in queue:
                if budget_exceeded:
                    # Bucket-3 site (b): the budget governor stopped the spend. The
                    # shortfall lands here honestly instead of reading as verified.
                    _book_unchecked(group["claims"], "budget cap reached")
                    # 21-03: a cluster skipped on budget must SAY it was skipped.
                    # Without this row the operator has to infer, from a cluster
                    # that simply never appears, that it was not checked.
                    stage_events.emit_verify_group_failed(
                        run_id, _verify_budget, group=group,
                        reason="the budget cap was reached before it could be checked",
                    )
                    continue
                sources = _extract_sources_for_group(group, provider_results)
                # ONE thorough session per selected group; stakes sets its depth.
                pending.append(_one_group_pass(group, sources))
                owners.append(group)
                # 21-03: the cluster's START row, paired positionally with the
                # finish row `_flush_groups` emits for the same group.
                stage_events.emit_verify_group_run(
                    run_id, _verify_budget, group=group,
                )
                total_skeptics += 1
                if len(pending) >= _SKEPTIC_CONCURRENCY:
                    await _flush_groups()
                    await raise_if_cancelled(run_id, tenant_id)
                    try:
                        if await over_budget(run_id, tenant_id, _MAX_BUDGET_USD, _sm):
                            budget_exceeded = True
                            log.warning(
                                "tribunal_pipeline: budget cap (%.2f USD) hit — "
                                "remaining groups wave through", _MAX_BUDGET_USD,
                            )
                    except Exception as exc:
                        log.warning("tribunal_pipeline: budget check failed: %s", exc)
            await _flush_groups()

            log.info(
                "tribunal_pipeline: GROUP verify — %d group-checks over %d selected "
                "of %d groups (%d multi-claim) / %d selected of %d claims, "
                "%d reconciliations (capped=%s, unchecked_selected=%d)",
                total_skeptics, total_passes, n_groups, multi,
                gate_funnel["selected_verify"], len(claims),
                len(group_reconciliations), budget_exceeded, unchecked_selected,
            )

        else:
            # --- Per-claim verification (legacy fallback / A/B baseline) -------
            # G-02: the queue is the gate's selection, NOT triage.py's stakes map.
            # This branch held the stakes triage's ONLY production call, and that
            # triage returned 0 skeptics for every low-stakes claim — the hidden
            # filter this phase removed. The BRANCH survives (it is the A/B
            # baseline, and `_one_skeptic` above is shared with the coverage-gate
            # re-entry in BOTH modes); only its selector changed.
            selected_claims = [
                c for c in claims if (c.get("gate") or {}).get("strict") == "VERIFY"
            ]
            n_selected = len(selected_claims)
            _verified_count = 0

            # 21-03: this branch's dispatch header. It and the grouped branch's
            # are mutually exclusive at runtime, so the stage still gets exactly
            # ONE header either way.
            stage_events.emit_verify_batch_dispatch(
                run_id, selected=n_selected, total=len(claims),
            )
            await set_stage(
                run_id, tenant_id, "verify",
                detail={"items": [{
                    "name": f"0 / {n_selected} selected claims verified",
                    "status": "running",
                }]},
            )

            pending = []
            owners = []

            async def _flush_batch() -> None:
                nonlocal _verified_count
                if not pending:
                    return
                batch_size = len(owners)
                results = await asyncio.gather(*pending)
                for owner, verdict in zip(owners, results):
                    if verdict is not None:
                        verdicts_by_claim[id(owner)].append(verdict)
                pending.clear()
                owners.clear()
                _verified_count += batch_size
                # 21-03: this branch's per-flush progress row.
                stage_events.emit_verify_batch_done(
                    run_id, _verify_budget,
                    verified=_verified_count, selected=n_selected,
                )
                await set_stage(
                    run_id, tenant_id, "verify",
                    detail={"items": [{
                        "name": (f"{min(_verified_count, n_selected)} / {n_selected} "
                                 f"selected claims verified"),
                        "status": "running",
                    }]},
                )

            for claim in selected_claims:
                if budget_exceeded:
                    # Bucket-3 site (b), per-claim mode.
                    _book_unchecked([claim], "budget cap reached")
                    continue
                sources = _extract_sources_for_claim(claim, provider_results)
                for _ in range(_PER_CLAIM_SKEPTICS):
                    pending.append(_one_skeptic(claim, sources))
                    owners.append(claim)
                    total_skeptics += 1
                if len(pending) >= _SKEPTIC_CONCURRENCY:
                    await _flush_batch()
                    await raise_if_cancelled(run_id, tenant_id)
                    try:
                        if await over_budget(run_id, tenant_id, _MAX_BUDGET_USD, _sm):
                            budget_exceeded = True
                            log.warning(
                                "tribunal_pipeline: budget cap (%.2f USD) hit — "
                                "remaining claims wave through", _MAX_BUDGET_USD,
                            )
                    except Exception as exc:
                        log.warning("tribunal_pipeline: budget check failed: %s", exc)
            await _flush_batch()

            log.info(
                "tribunal_pipeline: PER-CLAIM verify — ran %d skeptics over %d "
                "gate-selected of %d claims (capped=%s, unchecked_selected=%d)",
                total_skeptics, n_selected, len(claims), budget_exceeded,
                unchecked_selected,
            )

        # ------------------------------------------------------------------
        # Stage 5: Adjudication
        # ------------------------------------------------------------------
        adjudication_result = adjudicate_all(
            claims, verdicts_by_claim, SURVIVAL_RULE
        )
        survivors = adjudication_result["survivors"]
        dropped = adjudication_result["dropped"]
        await set_stage(
            run_id, tenant_id, "adjudicate",
            detail={"items": [{
                "name": f"{len(survivors)} survived · {len(dropped)} dropped of {len(claims)} claims",
                "status": "done",
            }]},
        )

        # Build the adjudications mapping for the coverage gate: id(claim) -> True
        # ONLY when at least one skeptic verdict actually came back for that claim.
        #
        # WR-01 (`15.1-UAT.md` § Deferred to Phase 15.2). The previous test was
        # `if id(c) in verdicts_by_claim`, which is UNCONDITIONALLY TRUE: the seed
        # above builds `{id(c): [] for c in claims}`, so every claim is a key from
        # the moment the verify stage starts, verdict or no verdict. Consequences,
        # all of them silent: `coverage["pass"]` was always True, `uncovered` was
        # always empty, the re-entry loop below was unreachable dead code, bucket-3
        # site (c) could never fire, and `reentry_count` was permanently 0.
        #
        # The funnel stayed HONEST throughout — WR-01 removed a RECOVERY path, it
        # did not lie about what was checked. A claim that lost its verdict was
        # still booked into bucket 3 by the ground-truth reconciliation below; it
        # just never got the second chance the coverage gate exists to give it.
        #
        # This is a closure rather than a one-off comprehension because the mapping
        # must be REBUILT from observed verdicts after a re-entry pass, not
        # pre-seeded with True (see the loop below).
        def _adjudications_now() -> dict[int, Any]:
            return {id(c): True for c in claims if verdicts_by_claim.get(id(c))}

        adjudications: dict[int, Any] = _adjudications_now()

        # ------------------------------------------------------------------
        # Stage 6: Coverage gate (bounded re-entry)
        # ------------------------------------------------------------------
        # THE COST TRAP, at the one place in the engine where it costs money
        # (D-07-B). `selected_only=True` is the default, and it is passed
        # EXPLICITLY here anyway: without the intersection, the recorded 4cbb5311
        # population's 738 gate-DROPped / SKIP_STABLE claims all read as uncovered
        # and the loop below fans out roughly 2,100 Anthropic sessions against a
        # stage the gates exist to shrink to ~150. The budget governor is inert
        # (`NESTOR_TRIBUNAL_UNCAPPED=1`) and will not stop it.
        await set_stage(run_id, tenant_id, "coverage")
        coverage = check_coverage(claims, adjudications, selected_only=True)
        reentry_count = 0

        # `budget_exceeded` is retained as the Phase-20 seam ONLY — `over_budget()`
        # always returns False today (D-11), so this term is inert and is NOT the
        # bound on this loop. The bounds that are real: MAX_REENTRY (one pass) and
        # the breaker gate inside `_coverage_reentry_pass` (D-07-C).
        while not coverage["pass"] and reentry_count < MAX_REENTRY and not budget_exceeded:
            reentry_count += 1
            log.warning(
                "tribunal_pipeline: coverage gate FAIL — re-entry %d/%d for %d uncovered high-stakes claims",
                reentry_count, MAX_REENTRY, len(coverage["uncovered"]),
            )
            reentry = await _coverage_reentry_pass(
                uncovered=coverage["uncovered"],
                verdicts_by_claim=verdicts_by_claim,
                superseded_notes=superseded_notes,
                provider_results=provider_results,
                audited=audited,
                run_id=run_id,
                tenant_id=tenant_id,
                sem=sem,
                breaker=skeptic_breaker,
                book_unchecked=_book_unchecked,
            )
            if reentry["blocked_reason"]:
                # The fan-out was refused because the skeptic circuit is not closed.
                # Every uncovered claim has already been booked into bucket 3 by the
                # helper; here the loss is NAMED for the operator, through the run's
                # ONE accumulator (never a locally-declared list).
                _note_degradation(reentry["blocked_reason"])
                log.warning(
                    "tribunal_pipeline: coverage re-entry BLOCKED — %s",
                    reentry["blocked_reason"],
                )
                break
            # Rebuild from OBSERVED verdicts, so a re-entry that came back with
            # nothing is visible to the second evaluation. The deleted pre-seeding
            # lines (`verdicts_by_claim[id(claim)] = []` and
            # `adjudications[id(claim)] = True`) made that impossible: the first was
            # a no-op by construction (an uncovered claim's verdict list is empty —
            # that is WHY it is uncovered) and the second declared the claim
            # adjudicated BEFORE its session ran.
            adjudications = _adjudications_now()
            coverage = check_coverage(claims, adjudications, selected_only=True)

        # Final adjudication after any re-entry
        if reentry_count > 0:
            adjudication_result = adjudicate_all(claims, verdicts_by_claim, SURVIVAL_RULE)
            survivors = adjudication_result["survivors"]
            dropped = adjudication_result["dropped"]

        # ------------------------------------------------------------------
        # The funnel is final here — and so is what the feed must say about it
        # ------------------------------------------------------------------
        # Bucket 3, reconciled against GROUND TRUTH before it is published: a claim
        # the gates selected that ended with no verdict was not checked, whatever
        # the cause — including causes the three counted sites do not name (a group
        # session that returned but skipped an index, a claim lost between batches).
        # The counters above exist to LOG the cause at the moment of loss; this line
        # decides the number, so no unnamed path can quietly read as verified.
        #
        # This runs HERE rather than down at the synthesis bundle because every
        # skeptic call is now behind us — the main verify stage AND the coverage-gate
        # re-entry, which is the last thing that can turn an unchecked claim into a
        # checked one. Nothing between here and synthesis adds a verdict (conflict
        # resolution only moves claims between survivors and dropped). Computing it
        # here is what lets the VERIFY stage's closing line be written while verify
        # is still the stage being reported: a `set_stage(..., "verify", ...)` issued
        # after synthesis had started would rewind `run.current_stage`.
        _observed_unchecked = sum(
            1 for c in claims
            if (c.get("gate") or {}).get("strict") == "VERIFY"
            and not verdicts_by_claim.get(id(c))
        )
        if _observed_unchecked != unchecked_selected:
            log.warning(
                "tribunal_pipeline: bucket-3 reconciliation — counted %d at the loss "
                "sites, observed %d selected claims with no verdict; publishing the "
                "observed number", unchecked_selected, _observed_unchecked,
            )
        unchecked_selected = _observed_unchecked

        # WR-10 / D-10 Option 2, counted from the SAME ground truth and at the same
        # moment as bucket 3, because it answers the mirror-image question: which
        # claims did the gates NOT select, yet a skeptic checked anyway?
        incidental = _count_incidental(claims, verdicts_by_claim)
        if incidental["checked_incidentally"]:
            log.info(
                "tribunal_pipeline: %d claim(s) were checked incidentally — the "
                "gates dropped them or marked them stable, but they rode along as "
                "members of a selected group and came back with a verdict. They "
                "move OUT of 'not checkable' and into their own accounting line; "
                "their verdicts are real and can still scrub a passage.",
                incidental["checked_incidentally"],
                extra={"run_id": str(run_id)},
            )

        # The ONE funnel for this run: built once, then carried on the synthesis
        # bundle, the verification report and the pipeline's return value, so the
        # feed, the operator report and run.verification_summary cannot disagree.
        verification_funnel = _build_funnel(
            gate_funnel,
            unchecked_selected=unchecked_selected,
            verify_sessions=total_skeptics,
            incidental=incidental,
            # Plan 15.2-07's ONE run-scoped accumulator, already in scope here.
            # Read, never re-declared — a second binding of this name would rebind
            # it to a fresh empty list and discard every reason appended upstream.
            degradation_reasons=degradation_reasons,
        )
        # D-F (e): sessions run, verdicts written. `total_skeptics` is the
        # session counter the funnel is built from; the verdict count is the
        # length of the per-claim verdict lists this stage filled.
        _stage_log_counts(
            run_id, "verify",
            sessions=int(total_skeptics),
            verdicts=sum(len(v or []) for v in verdicts_by_claim.values()),
            claims_with_a_verdict=sum(1 for v in verdicts_by_claim.values() if v),
        )
        # G-10: the closing summary states degradation in words, not with an icon.
        #
        # 21-03: BOUND ONCE, THEN SHARED. The feed row and the stage detail must
        # be the SAME sentence — composing it twice is how the run page and the
        # intake card come to report different degradation for one run, and
        # `_verify_closing_item` is deliberately the only place that sentence
        # exists.
        _verify_closing = _verify_closing_item(verification_funnel)
        stage_events.emit_verify_closing(run_id, text=_verify_closing["name"])
        await set_stage(
            run_id, tenant_id, "verify",
            detail={"items": [_verify_closing]},
        )
        # 21-03: the stage's row budget is spent — state any elision as a row
        # HERE, so it lands inside `verify` and before the next stage's divider.
        _verify_budget.flush("cluster")
        if verification_funnel["should_have_been_checked"]:
            log.warning(
                "tribunal_pipeline: VERIFICATION DEGRADED — %d of %d selected claims "
                "were never checked",
                verification_funnel["should_have_been_checked"],
                verification_funnel["selected_verify"],
                extra={"run_id": str(run_id)},
            )

        # Snapshot which claims were dropped by FACT-CHECK (skeptic adjudication)
        # BEFORE conflict resolution adds its own losers — so each rejected claim
        # can be labelled with WHY it was removed (failed_factcheck vs lost_conflict).
        _factcheck_dropped_ids = {id(c) for c in dropped}

        # ------------------------------------------------------------------
        # Stage 6.5: Conflict detection (horizontal axis) + resolution
        # ------------------------------------------------------------------
        # The skeptic checks each claim against the web (is it true?). Conflict
        # detection checks survivors against EACH OTHER (do two grounded claims
        # contradict?). Where one side is clearly weaker it is dropped (and later
        # scrubbed from the research); genuine ties become contested_notes that the
        # synthesiser must present as open disagreements.
        # Group skeptics already reconciled same-entity variants during verify;
        # carry their scoped/disputed findings into the contested notes so the
        # synthesiser presents them as open disagreements (this is the cross-claim
        # contradiction catch the per-claim path structurally cannot do).
        contested_notes: list[str] = []
        for r in group_reconciliations:
            label = f"{r.get('entity', '?')} — {r.get('attribute', '?')}"
            note = (r.get("note") or "").strip()
            if note:
                tag = "DISPUTED" if r.get("disputed") else "scope-dependent"
                contested_notes.append(f"[{tag}] {label}: {note}")
        # CR-01 / G-07: the superseded caveats collected in _flush_groups join the
        # SAME list, because contested_notes is what synthesize_report actually
        # receives (see _write_final_report). De-duplicated so a claim checked twice
        # (e.g. a coverage re-entry) does not repeat its caveat, and capped at
        # _SUPERSEDED_NOTE_CAP to bound the synthesis prompt — NOT to hide anything:
        # a truncation is logged loudly with the exact number dropped.
        _deduped_superseded = list(dict.fromkeys(superseded_notes))
        if len(_deduped_superseded) > _SUPERSEDED_NOTE_CAP:
            log.warning(
                "tribunal_pipeline: %d superseded caveat(s) DROPPED — %d collected, "
                "cap is %d; the dropped claims ship without their caveat",
                len(_deduped_superseded) - _SUPERSEDED_NOTE_CAP,
                len(_deduped_superseded), _SUPERSEDED_NOTE_CAP,
                extra={"run_id": str(run_id)},
            )
        contested_notes.extend(_deduped_superseded[:_SUPERSEDED_NOTE_CAP])
        await set_stage(
            run_id, tenant_id, "conflict",
            detail={"items": [{
                "name": (f"{len(group_reconciliations)} group reconciliations carried in"
                         if group_reconciliations else "checking survivors for contradictions"),
                "status": "running",
            }]},
        )
        conflicts: list[dict] = []
        if len(survivors) >= 2:
            try:
                conflicts = await conflict_detector(
                    claims=survivors,
                    audited=audited,
                    run_id=run_id,
                    tenant_id=tenant_id,
                )
            except Exception as exc:
                log.warning("tribunal_pipeline: conflict_detector failed: %s", exc)
                conflicts = []

            loser_idxs: set[int] = set()
            for conflict in conflicts:
                if conflict.get("contested") or conflict.get("loser") is None:
                    note = conflict.get("tension") or conflict.get("note") or ""
                    if note:
                        contested_notes.append(note)
                else:
                    loser_idxs.add(conflict["loser"])

            if loser_idxs:
                kept = [c for i, c in enumerate(survivors) if i not in loser_idxs]
                conflict_losers = [survivors[i] for i in sorted(loser_idxs)]
                log.info(
                    "tribunal_pipeline: conflict resolution dropped %d claim(s), "
                    "%d contested point(s) flagged",
                    len(conflict_losers), len(contested_notes),
                )
                dropped = dropped + conflict_losers
                survivors = kept

        # --- D-R8: THE ASSIGNMENT-YIELD COMPLETION SEAM ------------------------
        # WHY EXACTLY HERE — the one thing a later reader cannot re-derive.
        # `survivors` is bound THREE times in this method: by `adjudicate_all`,
        # again after the coverage re-entry re-adjudicates, and again by conflict
        # resolution twelve lines up (`survivors = kept`). A seam placed above ANY
        # of them counts claims the run went on to DISCARD, and would over-count
        # every assignment that lost a conflict. This is the first line at which
        # `survivors` is final, and it is above the `rejected_claims` ledger so it
        # stays that way.
        #
        # THE ROW SET IS THE ONE THE INSERT SEAM CAPTURED, and is deliberately NOT
        # re-derived from `provider_results`: reusing the captured rows is what
        # GUARANTEES the two halves address the same natural keys. Recomputing
        # would let any mid-run mutation of `provider_results` silently orphan a
        # row — and the emitter's "0 rows affected" warning would then read that as
        # "the INSERT half never landed", a confident and completely wrong
        # diagnosis in the one run there is.
        try:
            if _yield_rows:
                _survivor_total = 0
                for _row in _yield_rows:
                    _n = sum(
                        1 for _s in survivors
                        if _claim_matches_assignment(
                            _s,
                            provider=_row.get("provider"),
                            group_id=_row.get("group_id"),
                            client_question=_row.get("client_question"),
                        )
                    )
                    _survivor_total += _n
                    # Row and count BOTH bound as default arguments, never
                    # captured — a captured `_row` is resolved when the thunk runs
                    # and would put the LAST row in every call.
                    await yield_records.complete_assignment_safe(
                        run_id, tenant_id,
                        build=lambda _r=_row, _c=_n: {
                            "provider": _r.get("provider"),
                            "group_id": _r.get("group_id"),
                            "client_question": _r.get("client_question"),
                            # A 0 here is a MEASUREMENT: verification DID run for
                            # this assignment and kept nothing of it. `verified_at`
                            # being set is precisely what tells that apart from
                            # "verification never ran".
                            "claims_surviving_verification": _c,
                        },
                    )
                # The total CAN EXCEED `len(survivors)`, and that is by design: a
                # claim found by two providers is attributed to BOTH assignments,
                # consistently with `claims_kept`. Said here so the first person to
                # compare the two numbers does not file a bug against a decision.
                log.info(
                    "tribunal_pipeline: D-R8 completed %d assignment_yield row(s); "
                    "%d survivor attribution(s) over %d final survivor(s) — the "
                    "total exceeds the survivor count when a claim was found by "
                    "more than one provider, by design",
                    len(_yield_rows), _survivor_total, len(survivors),
                )
            else:
                # An UPDATE with no INSERT is the completer's "0 rows affected"
                # warning arriving from the wrong direction. Say so here instead.
                log.warning(
                    "tribunal_pipeline: no assignment_yield rows were captured at "
                    "the INSERT seam, so nothing is completed — the verification "
                    "half of this run's yield measurement is absent, and any 0-row "
                    "warning from the completer would be misleading",
                )
        except Exception as exc:  # noqa: BLE001 — telemetry may never end a paid run
            log.warning(
                "tribunal_pipeline: the assignment-yield COMPLETION seam failed "
                "(%s: %s) — claims_surviving_verification is lost for this run; "
                "the run itself is unaffected",
                type(exc).__name__, exc,
            )

        # Rejected-claims ledger — the claims the Tribunal fact-checked and removed
        # (failed live-web verification) or dropped as the weaker side of a conflict.
        # Persisted by the worker as Output('rejected_claims') so the Deep Content
        # Compare can show what THIS engine threw out — and cross-check whether the
        # other engine's report still asserts it (a verified-vs-unverified signal).
        rejected_claims: list[dict[str, str]] = []
        for _c in dropped:
            _txt = (_c.get("text") or _c.get("claim_text") or "").strip()
            if not _txt:
                continue
            rejected_claims.append({
                "text": _txt,
                "facet": (_c.get("facet") or _c.get("focus_area") or "").strip(),
                "reason": "failed_factcheck" if id(_c) in _factcheck_dropped_ids else "lost_conflict",
            })

        # ------------------------------------------------------------------
        # Stage 7: Resolve gemini redirects, THEN persist fine-grained survivor
        # claims (RECALL MECHANISM)
        # ------------------------------------------------------------------
        # The body lives in `_resolve_then_persist_claims` above, at module
        # level, for ONE reason: the order of its two halves is load-bearing
        # (D-V01-11) and a module-level function can be driven directly by the
        # ordering test that pins it. Nothing about the persistence call itself
        # changed — the `except Exception` that deliberately does not block
        # synthesis on a persistence failure moved with it.
        await _resolve_then_persist_claims(
            survivors=survivors,
            dropped=dropped,
            verdicts_by_claim=verdicts_by_claim,
            research_gaps=research_gaps,
            run_id=run_id,
            tenant_id=tenant_id,
        )

        # ------------------------------------------------------------------
        # Stage 8: Scrub discredited content, then synthesise from FULL research
        # ------------------------------------------------------------------
        # SUBTRACTIVE VERIFICATION: synthesis runs on the full research prose (so no
        # information is lost to a claim cap), but every passage that states or
        # depends on a discredited claim — dropped by adjudication OR by conflict
        # resolution — is physically removed from the research first. This keeps
        # ADK-style richness while making the fact-checking actually stick.
        await raise_if_cancelled(run_id, tenant_id)
        await set_stage(
            run_id, tenant_id, "synthesize",
            detail={"items": [{
                "name": f"writing report from {len(survivors)} verified claims",
                "status": "running",
            }]},
        )
        cleaned_reports = await scrub_research(
            provider_reports=provider_results,
            removed_claims=dropped,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )

        # Build the SERIALIZABLE verification bundle from the live objects — needed
        # whether we synthesise now or pause for interactive shaping and resume from
        # cache later (id()-keyed verdicts can't cross a pause, so flatten here).
        per_claim_verdicts: dict[str, list] = {}
        for claim in claims:
            ckey = claim.get("text", "")[:80]
            per_claim_verdicts[ckey] = verdicts_by_claim.get(id(claim), [])
        n_unverified = sum(1 for c in claims if not verdicts_by_claim.get(id(c)))

        # (Bucket 3 was reconciled against ground truth and `verification_funnel`
        # built right after the coverage gate — see the block above. Both are final
        # by the time we get here; nothing since then could add a verdict.)
        claims_per_facet: dict[str, int] = {}
        for c in claims:
            f = c.get("facet") or "?"
            claims_per_facet[f] = claims_per_facet.get(f, 0) + 1
        for fa in (mission_brief.get("focus_areas") or []):
            label = fa.get("focus_area")
            if label:
                claims_per_facet.setdefault(label, 0)

        # D-17 FACTS for `terminal_state()` (plan 15.2-16). The pipeline reports;
        # the worker decides. `streams_total` is the angle count and
        # `streams_lost` is how many of them produced nothing — so losing one or
        # two of four streams lands on `completed_degraded` (their angles are a
        # minority), while losing them all lands on `parked`, which is exactly
        # D-17's boundary. `synthesis_ran` is True on this path by construction:
        # we are one call away from writing the report.
        _streams_total = max(1, len(angles))
        _streams_lost = max(0, len(angles) - len(provider_results))
        terminal_inputs = {
            "streams_lost": _streams_lost,
            "streams_total": _streams_total,
            "verify_ran": bool(verify_ran),
            "synthesis_ran": True,
            "hard_wall": False,
            "degradation_reasons": list(degradation_reasons),
        }

        synthesis_bundle = {
            "mission_brief": mission_brief,
            "cleaned_reports": cleaned_reports,
            "contested_notes": contested_notes,
            "rejected_claims": rejected_claims,
            # D-08 inputs for the two deterministic report sections.
            #
            # 1. WHY IT LIVES ON THE BUNDLE. `_write_final_report` is shared by
            #    the zero-touch path and the interactive-report RESUME path,
            #    which rebuilds everything from this cached `synthesis_cache`
            #    row. Anything the report needs must be serializable and travel
            #    here — exactly the reason `contested_notes` is on the bundle.
            #    All three values below are plain str/bool/dict data.
            # 2. WHY `superseded_notes` IS THE UNCAPPED DEDUPED LIST while
            #    `contested_notes` above gets `[:_SUPERSEDED_NOTE_CAP]`: that cap
            #    bounds a PROMPT ("NOT to hide anything" — the comment at the cap
            #    site says so). The D-08 section is not a prompt, and dropping
            #    caveats from the operator's report would be precisely the silent
            #    loss the cap is explicitly not for.
            # 3. `brief_conflicts` IS POPULATED HERE (plan 15.2-13, wave 6). They
            #    are the workshop's D4 brief-vs-world flags, produced by 15.2-10's
            #    emit_orientation, carried through stage B untouched and handed
            #    straight to 15.2-06's "Disputed & changed" renderer. Nothing in
            #    this module reads or reinterprets them — an empty list simply
            #    means the orientation found no assumption worth flagging, and the
            #    subgroup does not render.
            # 4. `not_found_by_provider` is DELIBERATELY NOT HERE.
            #    `_write_final_report` reads `research_gap` directly, so the
            #    section works on the resume path and needs no wiring hand-off
            #    from 15.2-15 (which owns the WRITE path) beyond the rows.
            # 5. WAVE 3 ANNOTATES THOSE FLAGS ON THE WAY PAST, and this is the only
            #    place it happens. A discovered question is written ONTO the conflict
            #    that provoked it — `annotate_conflicts` returns a new list of the
            #    same length and order, adding `researched_as` to the matching
            #    entries — and is NEVER appended as an extra row. Appending would
            #    print the same conflict twice in "Where the brief did not match what
            #    the research found", once with the clause and once without, and a
            #    client reading it twice cannot tell which reading is true.
            #
            #    ONLY `discovery_dispatched` is passed, never the whole allocation:
            #    a question that was shed for prompt space or lost its group to a
            #    coverage repair must render as a plain brief-vs-world conflict with
            #    no clause, because no provider was ever asked it.
            #
            #    This is also what carries Art. 12 provenance into a CLIENT-FACING
            #    document. D5/D-01 forbids gating the workshop on an operator click,
            #    so transparency in the delivered report is the control that replaces
            #    the gate — which is why the annotation belongs on the bundle (it
            #    travels to the interactive-report resume path) and not in the
            #    renderer.
            "report_sections": {
                "group_reconciliations": group_reconciliations,
                "superseded_notes": _deduped_superseded,
                "brief_conflicts": discovery_bracket.annotate_conflicts(
                    brief_conflicts, discovery_dispatched
                ),
            },
            "verification": {
                "per_claim_verdicts": per_claim_verdicts,
                "n_claims": len(claims),
                "survivor_count": len(survivors),
                "dropped_count": len(dropped),
                "n_unverified": n_unverified,
                "contested_count": len(contested_notes),
                "coverage": coverage,
                "reentry_count": reentry_count,
                "conflicts": conflicts,
                "claims_per_facet": claims_per_facet,
                "budget_exceeded": budget_exceeded,
                # D-12's reason list — SURFACE 1 OF 2, and the carrier for the
                # other. This is `run()`'s ONE accumulator (declared at the top of
                # run(), written only through `_note_degradation`), not a copy and
                # not a second list. It rides on the bundle so the reasons survive
                # the interactive-report pause and the synthesis_cache round-trip,
                # exactly as `funnel` does — and `_write_final_report` lifts it back
                # out of here onto the TOP-LEVEL `result["degradation_reasons"]`
                # (surface 2), which is the key `runs/worker.py` reads and feeds to
                # `terminal_state()`. Both surfaces carry the SAME content from the
                # SAME list; neither is a second accumulator.
                #
                # NOT normalised or capped here: plan 15.2-08 owns the shared
                # `_normalise_degradation_reasons` (200-char / 8-entry caps) and the
                # FUNNEL-side surfacing, and will route both surfaces through it. Do
                # not write a second normaliser. Until 08 lands, the only reason this
                # plan produces is a code-authored sentence built from
                # `CircuitBreaker.snapshot()["reason"]`, which plan 02 already
                # redacts and truncates.
                #
                # Deliberately NOT added to the funnel: `_build_funnel` /
                # `_FUNNEL_KEYS` are frozen because `RECORDED_FUNNEL_COUNTS` is
                # compared by FULL DICT EQUALITY in two tests.
                "degradation_reasons": degradation_reasons,
                # D-14 (15.2-15): which research streams stated no facts of their
                # own and had their prose distilled instead, with 15.2-04's plain
                # reason and 15.2-14's count-bearing sentence. Entries are
                # `{"provider", "reason", "note"?}`.
                #
                # THIS IS NOT A DEGRADATION AND MUST NOT BECOME ONE. It rides here
                # beside `funnel` so it survives the interactive-report pause and
                # is available to 15.2-08/15.2-09's D-12 reason list — but it is
                # deliberately NOT in `degradation_reasons` above and must never be
                # fed to `_note_degradation` or `terminal_state()`. Per D-14 a
                # distiller fallback degrades ONE STREAM, not the run: the
                # provider's research still reached the merge in full. D-12's
                # degrading conditions are a non-zero bucket 3, a stream lost to a
                # tripped breaker, a workshop fallback, or a skipped stage — this
                # is none of them, and promoting it would drain
                # `completed_degraded` of meaning exactly as D-12 warns.
                #
                # ADDITIVE, and deliberately NOT on the funnel: `_build_funnel` /
                # `_FUNNEL_KEYS` are frozen because `RECORDED_FUNNEL_COUNTS` is
                # compared by FULL DICT EQUALITY.
                "factlist_fallbacks": factlist_fallbacks,
                # The 15.1 funnel — the gates' nine keys plus this stage's four.
                # Carried on the bundle so it survives the interactive-report pause:
                # the resume path rebuilds the result from this cache, and
                # _write_final_report lifts the funnel back out of it onto the
                # pipeline's `verification_summary` key, which is what the worker
                # persists onto run.verification_summary (plan 15.1-08).
                "funnel": verification_funnel,
                # D-17 (15.2-16). Rides on the bundle for the SAME reason
                # `degradation_reasons` does: the interactive-report resume path
                # rebuilds the whole result from this cached bundle, so anything
                # the worker's terminal-state decision needs has to survive the
                # pause. `_write_final_report` lifts it back out onto the
                # top-level `terminal_inputs` key the worker reads.
                "terminal_inputs": terminal_inputs,
            },
        }

        # R3: the verify checkpoint is the bundle's OWN verification block — the
        # already-flattened, already-serialisable shape this module builds for
        # `synthesis_cache` a few lines below (id()-keyed verdict maps cannot
        # cross a pause, and there is exactly one flattener in this file). Write-
        # only in this plan, as recorded at the merge checkpoint above.
        await ckpt.put("verify", synthesis_bundle["verification"])

        # Cache the scrubbed-research bundle so a "Rewrite report" — or the
        # interactive-gate resume — re-synthesises WITHOUT re-running deep research.
        await _write_output(run_id, tenant_id, "synthesis_cache", synthesis_bundle)

        # INTERACTIVE GATE (opt-in via [INTERACTIVE_REPORT] marker): pause BEFORE
        # synthesis so the user can shape the report. The worker parks the run as
        # 'needs_report_spec'; the user's spec re-queues it and the resume branch
        # at the top of run() writes the report from this cached bundle.
        if interactive_report:
            from nestor_pulse_sdk.pipeline.tribunal.report_planner import build_report_proposal
            proposal = await build_report_proposal(
                mission_brief=mission_brief, cleaned_reports=cleaned_reports,
                audited=audited, run_id=run_id, tenant_id=tenant_id,
            )
            await _write_output(run_id, tenant_id, "report_proposal", proposal)
            await set_stage(run_id, tenant_id, "report_spec", detail={"items": [
                {"name": "awaiting your report shape (focus areas · length · tables)",
                 "status": "running"}
            ]})
            log.info("tribunal_pipeline: paused for interactive report shaping")
            return {"needs_report_spec": True, "report_proposal": proposal}

        # Zero-touch default: the client's chosen report shape when the intake
        # carried one, and None when it did not.
        #
        # THIS LINE WAS THE OFF SWITCH (quick task 260806-lvt). It read
        # `report_spec=None` unconditionally, so `_spec_directives` returned "" on
        # every seam run and the "REPORT SHAPING (client-chosen - honor these)" block
        # it already knows how to emit never reached a single prompt. The intake has
        # asked "Gewenste omvang van het rapport" all along; the answer died here.
        # Run 368ff3a0 delivered 356,352 characters against a form whose LARGEST
        # option offers "approx. 10-20 pages" and whose help text reads
        # "Dikker != beter."
        #
        # `or None` is load-bearing: `_spec_directives` treats a falsy spec as "no
        # spec" and returns "", so an empty dict and None behave identically — but
        # passing None keeps this call byte-identical to the pre-change one for every
        # old intake, which is what the back-compat test pins.
        return await _write_final_report(
            bundle=synthesis_bundle,
            report_spec=(synthesis_bundle.get("mission_brief") or {}).get("report_spec") or None,
            audited=audited, run_id=run_id, tenant_id=tenant_id,
        )


#: Brief sentinel that turns on the interactive report-shaping gate (stripped
#: before research). The NewBriefing UI appends it when the user opts in.
_INTERACTIVE_MARKER = "[INTERACTIVE_REPORT]"


async def _read_output(run_id: uuid.UUID, tenant_id: uuid.UUID, fmt: str):
    """Read the latest Output(format=fmt) for a run as parsed JSON, or None."""
    import json as _json
    from sqlalchemy import text as _sql
    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                row = (await session.execute(
                    _sql("SELECT body FROM output WHERE run_id=:r AND format=:f "
                         "ORDER BY created_at DESC LIMIT 1"),
                    {"r": str(run_id), "f": fmt},
                )).first()
        if row and row[0]:
            return _json.loads(row[0])
    except Exception as exc:  # noqa: BLE001 — cache reads are best-effort
        log.warning("tribunal_pipeline: _read_output(%s) failed: %s", fmt, exc)
    return None


async def _read_research_gaps(
    run_id: uuid.UUID, tenant_id: uuid.UUID
) -> Optional[dict[str, list[str]]]:
    """Read this run's per-provider "couldn't find" list (D-08, migration 0013).

    THREE-STATE CONTRACT, and the difference between the first two is the whole
    reason this returns Optional:

      * ``None``      -> the list COULD NOT BE READ. `build_could_not_establish`
                         renders a named failure sentence for this state.
      * ``{}``        -> read fine, nothing to report.
      * non-empty     -> ``{provider: [text, ...]}``.

    Returning ``{}`` on a database error would render "No provider reported a
    research gap" over a failure — a false factual statement in a document the
    operator hands to a client, and exactly the silent green phase rule 6 forbids
    (T-15.2-33). So the except arm returns ``None``, never ``{}``.

    TENANT SCOPING (T-15.2-34): clones `_read_output`'s idiom exactly —
    `set_tenant_context` runs before the query, and the query filters on `run_id`
    ONLY. `tenant_id` is deliberately absent from the WHERE clause: `research_gap`
    carries FORCE RLS and the `research_gap_tenant_isolation` policy from
    migration 0013, so isolation is enforced by the DATABASE, not by application
    filtering (the broken-RLS class of bug must not recur). The
    `(tenant_id, run_id)` index still serves this plan.

    The ORDER BY is LOAD-BEARING for byte-stability: the section renders rows in
    the order they arrive, and an unordered SELECT could return them differently
    on two reads of the same data, breaking D-08's byte-identical guarantee.
    """
    from sqlalchemy import text as _sql
    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                rows = (await session.execute(
                    _sql("SELECT provider, text FROM research_gap WHERE run_id=:r "
                         "ORDER BY provider ASC, created_at ASC, id ASC"),
                    {"r": str(run_id)},
                )).all()
        out: dict[str, list[str]] = {}
        for row in rows or ():
            provider = str(row[0] or "").strip() or "?"
            out.setdefault(provider, []).append(str(row[1] or ""))
        return out
    except Exception as exc:  # noqa: BLE001 — a failed read is STATED, never hidden
        log.warning(
            "tribunal_pipeline: _read_research_gaps failed for run=%s: %r — the "
            "'What we could not establish' section will say so",
            run_id, exc,
        )
        return None


async def _load_citation_context(
    run_id: uuid.UUID, tenant_id: uuid.UUID
) -> tuple[list[dict], list[dict], dict[str, int]]:
    """Read this run's fact ledger + `[n]` numbering (Phase 15.2, D-05).

    Returns `(anchor_ledger, numbered, prefix_to_n)`:
      * `anchor_ledger` -- the facts the writing model is asked to anchor to;
      * `numbered`      -- the `[n]` -> source list the `## Sources` block renders;
      * `prefix_to_n`   -- what the post-pass resolves the model's anchors against.

    All three come from ONE read of the same rows, so the body's `[n]` markers and
    the `## Sources` list can never disagree.

    TENANT SCOPING (T-15.2-21): copies the `_read_output` idiom exactly --
    `set_tenant_context` runs before any query, and both queries filter on
    `run_id`. RLS then scopes claim/source/claim_source. No new table, no new
    endpoint, no new cross-tenant surface.

    Best-effort by design (shared pattern 6): a citation-context failure degrades
    the report's citations and is logged, it never breaks the run. On failure the
    report is written exactly as it would have been before 15.2.

    RESUME PATH: `_write_final_report` is also reached from the interactive-resume
    branch. Because the ledger and the numbering are read HERE from the DB rather
    than carried on the `synthesis_cache` bundle, a resumed run gets the same
    citations with no bundle schema change.
    """
    from nestor_pulse_sdk.citations.anchors import anchor_number_map, build_ledger
    from nestor_pulse_sdk.citations.numbering import (
        list_run_claims,
        number_citations_with_claims,
    )
    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                claim_rows = await list_run_claims(session, run_id)
                numbered, claim_to_n = await number_citations_with_claims(session, run_id)
        return build_ledger(claim_rows), numbered, anchor_number_map(claim_to_n)
    except Exception as exc:  # noqa: BLE001 — citations degrade, runs do not fail
        log.warning(
            "tribunal_pipeline: _load_citation_context failed, the report will carry "
            "no citation anchors and an unnumbered Sources list: %s",
            exc,
        )
        return [], [], {}


async def _write_output(run_id: uuid.UUID, tenant_id: uuid.UUID, fmt: str, payload) -> None:
    """Persist an Output(format=fmt) JSON row for a run (best-effort)."""
    import json as _json
    import uuid as _uuid
    from sqlalchemy import text as _sql
    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                await session.execute(
                    _sql("INSERT INTO output (id, tenant_id, run_id, format, body, created_at) "
                         "VALUES (:id,:tid,:rid,:fmt,:body,NOW())"),
                    {"id": str(_uuid.uuid4()), "tid": str(tenant_id), "rid": str(run_id),
                     "fmt": fmt, "body": _json.dumps(payload, ensure_ascii=False, default=str)},
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("tribunal_pipeline: _write_output(%s) failed: %s", fmt, exc)


async def _write_final_report(
    *,
    bundle: dict,
    report_spec: Optional[dict],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> dict:
    """Synthesis -> cite-strip -> quality gate -> verification appendix -> result.

    Shared by the zero-touch path (bundle freshly built) and the resume path
    (bundle loaded from the synthesis_cache). report_spec is None for the default
    report, or the user's interactive shaping choice.
    """
    mission_brief = bundle.get("mission_brief") or {}
    cleaned_reports = [tuple(r) for r in (bundle.get("cleaned_reports") or [])]
    contested_notes = bundle.get("contested_notes") or []
    rejected_claims = bundle.get("rejected_claims") or []
    # D-08 section inputs. `or {}` is the RESUME-PATH BACK-COMPAT guard: a
    # pre-15.2 synthesis_cache row replayed after deploy carries no
    # `report_sections` key at all, and must still produce both sections on their
    # empty paths rather than raise.
    report_sections = bundle.get("report_sections") or {}
    v = bundle.get("verification") or {}

    # D-F (d) — ONE OF THE TWO STAGE WRITES THAT SIT OUTSIDE `_run_staged`'s
    # `set_stage` closure. This function is module-level and is ALSO the resume
    # path's entry point (`run()` calls it directly from the synthesis cache), so
    # it is deliberately NOT re-plumbed through the closure: threading a logging
    # object through a paid path would change that path's call graph for the sake
    # of a log line, which is not a trade worth making. It calls the SAME
    # module-level recorder instead, which is why the shape of the line here is
    # identical to every other stage line in this module — and why the resume
    # path, where no closure ever ran, still reports its stages.
    _synthesize_detail = {"items": [{"name": "writing final report", "status": "running"}]}
    _stage_log_transition(run_id, "synthesize", _synthesize_detail)
    await set_stage(run_id, tenant_id, "synthesize", detail=_synthesize_detail)

    anchor_ledger, numbered, prefix_to_n = await _load_citation_context(run_id, tenant_id)
    log.info(
        "tribunal_pipeline: citation context loaded — %d ledger fact(s), "
        "%d numbered source(s)",
        len(anchor_ledger), len(numbered),
        extra={"run_id": str(run_id)},
    )

    # Pass the citation kwargs ONLY when there is something to pass. Semantically
    # identical for synthesize_report (it treats None and [] the same), but it
    # keeps the pre-15.2 call signature exactly intact on the no-citation path —
    # which is the path every existing monkeypatched `fake_synthesis` double in
    # test_tribunal_pipeline.py is written against (those doubles declare explicit
    # keyword-only params and no **kwargs, so an unconditional new kwarg raises
    # TypeError). Do NOT "tidy" this back into the literal call: it re-breaks
    # test_tribunal_pipeline.py. The durable fix is `**_kwargs` on those doubles,
    # which lives in a file this plan does not own — see the SUMMARY's deferred items.
    _citation_kwargs: dict = {}
    if anchor_ledger:
        _citation_kwargs["anchor_ledger"] = anchor_ledger
    if numbered:
        _citation_kwargs["numbered_citations"] = numbered

    synthesis_text = await synthesize_report(
        mission_brief=mission_brief,
        provider_reports=cleaned_reports,
        audited=audited,
        run_id=run_id,
        tenant_id=tenant_id,
        contested_notes=contested_notes,
        report_spec=report_spec,
        **_citation_kwargs,
    )

    # D-05 post-pass. Order matters and is load-bearing:
    #   1. count_model_numbers FIRST — at this instant no number in the text can
    #      have come from Python, so every bare [n] found is model-invented.
    #   2. apply_citation_anchors — resolve [[c:...]] to the numbers Python
    #      assigned; strip AND COUNT whatever does not resolve (D-06).
    #   3. strip_unresolved_cite_markers, UNCHANGED and still last: [cite: N] is
    #      the PROVIDER's mechanism, [[c:...]] is ours. Two mechanisms, two
    #      counts, never conflated.
    from nestor_pulse_sdk.citations.anchors import (
        apply_citation_anchors,
        count_model_numbers,
    )
    n_model_numbers = count_model_numbers(synthesis_text)
    synthesis_text, n_unresolved_anchors = apply_citation_anchors(
        synthesis_text, prefix_to_n
    )
    if n_model_numbers:
        log.warning(
            "tribunal_pipeline: the writing model wrote %d bare bracketed number(s) "
            "of its own before any numbering was applied. Those are not citations "
            "and resolve to nothing in the Sources list.",
            n_model_numbers,
        )
    if n_unresolved_anchors:
        log.warning(
            "tribunal_pipeline: %d citation anchor(s) matched no claim in this run "
            "and were removed from the report. The statements they were attached to "
            "are now uncited.",
            n_unresolved_anchors,
        )

    from nestor_pulse_sdk.audit.audited_llm_client import strip_unresolved_cite_markers
    synthesis_text, n_orphan_cites = strip_unresolved_cite_markers(synthesis_text)
    if n_orphan_cites:
        log.warning("tribunal_pipeline: stripped %d unresolved [cite:] marker(s)", n_orphan_cites)

    focus_areas = extract_focus_areas(mission_brief)
    gate = build_quality_gate()
    try:
        verdict_obj = await gate.grade(
            synthesis=synthesis_text, mission_brief=mission_brief, focus_areas=focus_areas,
            audited=audited, run_id=run_id, tenant_id=tenant_id,
        )
        verdict_dict = verdict_obj.as_dict()
    except Exception as exc:
        log.warning("tribunal_pipeline: quality gate error: %s", exc)
        verdict_dict = {"pass": None, "error": str(exc)}

    bmarker = budget_marker(bool(v.get("budget_exceeded")), BUDGET_BEHAVIOUR)
    per_claim_verdicts = v.get("per_claim_verdicts") or {}
    verification_report = {
        "per_claim_verdicts": per_claim_verdicts,
        "verdicts": per_claim_verdicts,  # alias for test compatibility
        "dropped_count": v.get("dropped_count", 0),
        "survivor_count": v.get("survivor_count", 0),
        "budget_marker": bmarker,
        "coverage": v.get("coverage") or {"pass": True, "uncovered": []},
        "reentry_count": v.get("reentry_count", 0),
        "conflicts": v.get("conflicts") or [],
        "contested_count": v.get("contested_count", 0),
        # The 15.1 funnel travels with the report so the superadmin surface can
        # show the three honest buckets. Same key, same shape, on the zero-claim
        # path too (RESEARCH Pitfall 10) — a consumer never branches on the path.
        "funnel": v.get("funnel") or _build_funnel(
            None, unchecked_selected=0, verify_sessions=0
        ),
        # D-06 citation-health counts, as siblings of "funnel" on this report.
        # `orphan_cite_markers` and `model_invented_numbers` STAY siblings and only
        # siblings: they diagnose the PROVIDER's `[cite: N]` mechanism, not D-06's
        # `[[c:...]]` anchor mechanism, and the operator reads them as report-writing
        # diagnostics rather than as verification accounting. `unresolved_anchors` is
        # the one 15.2-08 folds INTO the funnel just below (with the matching key
        # added to RECORDED_FUNNEL_COUNTS in the same commit, because the two key
        # sets are locked together by test_gate_selector.py).
        # Always present, 0 on a run with no anchors.
        "unresolved_anchors": n_unresolved_anchors,
        "orphan_cite_markers": n_orphan_cites,
        "model_invented_numbers": n_model_numbers,
    }

    # D-06, folded onto run.verification_summary. Read back FROM the sibling key on
    # this same payload rather than from `n_unresolved_anchors` a second time: that
    # makes the two copies mechanically identical, so the payload can never publish
    # two disagreeing numbers for one thing (the CR-02 failure mode). And
    # `verification_report["funnel"]` is the SAME DICT OBJECT as the returned
    # `result["verification_summary"]`, so this one assignment is what carries the
    # count all the way to the persisted `run.verification_summary` column.
    _n_unresolved_anchors = int(verification_report.get("unresolved_anchors") or 0)
    verification_report["funnel"]["unresolved_anchors"] = _n_unresolved_anchors

    # ------------------------------------------------------------------
    # D-08: the two deterministic report sections.
    #
    # THE INVARIANT: both blocks are built and appended HERE, after
    # synthesize_report has already returned and after the anchor/cite post-passes
    # above, so the writing model never receives them and cannot omit, merge,
    # truncate, reorder or paraphrase an item (T-15.2-37). The rejected
    # alternative — "the model presents them from a supplied list" (D14's literal
    # wording) — is unprovable without an LLM-judged test, and the "deterministic
    # list plus a model-written intro" variant only moves the drift one paragraph
    # up. The post-passes deliberately do NOT walk these blocks: they carry no
    # anchors and no provider cite markers, `_sanitize` having already removed
    # both from the pipeline data they are rendered from.
    #
    # The "\n\n---\n\n" separator matches the one _verification_appendix opens
    # with, so the three trailing sections read as three peers.
    # ------------------------------------------------------------------
    language = (mission_brief or {}).get("language") or ""
    gaps = await _read_research_gaps(run_id, tenant_id)  # None => unreadable
    disputed_section = build_disputed_and_changed(
        group_reconciliations=report_sections.get("group_reconciliations"),
        superseded_notes=report_sections.get("superseded_notes"),
        brief_conflicts=report_sections.get("brief_conflicts"),
        language=language,
    )
    could_not_section = build_could_not_establish(
        not_found_by_provider=gaps,
        language=language,
    )
    log.info(
        "tribunal_pipeline: D-08 sections rendered — disputed=%d chars, "
        "could_not_establish=%d chars, gaps=%s",
        len(disputed_section), len(could_not_section),
        "unreadable" if gaps is None else f"{len(gaps)} provider(s)",
        extra={"run_id": str(run_id)},
    )

    synthesis_text = (
        synthesis_text
        + "\n\n---\n\n" + disputed_section
        + "\n\n---\n\n" + could_not_section
    ) + _verification_appendix(
        n_claims=v.get("n_claims", 0),
        n_survivors=v.get("survivor_count", 0),
        n_dropped=v.get("dropped_count", 0),
        n_unverified=v.get("n_unverified", 0),
        n_contested=v.get("contested_count", 0),
        budget_exceeded=bool(v.get("budget_exceeded")),
        reentry_count=v.get("reentry_count", 0),
        # G-10: the appendix renders these keys as text, so they must carry the
        # client's full question exactly as the section headings do — one
        # resolver (`synthesis.steps.focus_area_questions`), not a second copy of
        # the rule here. Display only: nothing downstream joins on these keys.
        claims_per_facet=relabel_facets(v.get("claims_per_facet") or {}, mission_brief),
        n_unresolved_cites=n_orphan_cites,
    )

    _done_name = (f"{v.get('survivor_count', 0)} verified claims · "
                  f"{v.get('dropped_count', 0)} dropped · "
                  f"{v.get('contested_count', 0)} contested")
    if _n_unresolved_anchors:
        # D-06's "feed's closing summary" half — the count stated in words, where an
        # operator scanning the feed will actually meet it. The verification-report
        # half is verification/report.py's `unresolved_anchors_text`.
        _done_name += (
            f" · {_n_unresolved_anchors} citation anchor(s) could not be resolved "
            f"and were removed (the sentences remain)"
        )
    # D-F (c)/(d) — THE LAST STAGE, AND THE RUN'S CLOSING LINE. The `done` write
    # closes the run, so its own exit line has no successor transition to trigger
    # it: `_stage_log_close` emits it explicitly and then the ONE
    # `run_stages_complete` summary — stages entered and total wall seconds — that
    # an operator greps to answer "did this run get anywhere". Popping the
    # registry entry here is also what keeps the normal path from leaving state
    # behind; `run()`'s `finally` catches every other terminal.
    _done_detail = {"items": [{"name": _done_name, "status": "done"}]}
    _stage_log_transition(run_id, "done", _done_detail)
    await set_stage(run_id, tenant_id, "done", detail=_done_detail)
    _stage_log_close(run_id)
    log.info(
        "tribunal_pipeline_complete: %d survivors / %d dropped / budget_marker=%r",
        v.get("survivor_count", 0), v.get("dropped_count", 0), bmarker,
        extra={"run_id": str(run_id)},
    )
    return {
        "output_text": synthesis_text,
        "claim_count": v.get("survivor_count", 0),
        "verdict": verdict_dict,
        "verification_report": verification_report,
        "rejected_claims": rejected_claims,
        # The carrier the worker reads (plan 15.1-08), following the
        # `rejected_claims` precedent exactly: a top-level result key the worker
        # picks up defensively and persists in the SAME transaction that sets
        # status='completed', so a run can never report completed while its
        # degradation marker is missing (G-10). Same dict object as
        # verification_report["funnel"] — one funnel, three readers, no drift.
        "verification_summary": verification_report["funnel"],
        # D-12's reason list — SURFACE 2 OF 2, the TOP-LEVEL key `runs/worker.py`
        # reads (it does exactly `result.get("degradation_reasons")` and feeds the
        # value to `terminal_state()` and to the persisted verification_summary;
        # plan 15.2-09 landed that read in wave 2 with no writer, and THIS is the
        # line that makes it real).
        #
        # Sourced from `v` — the bundle's `verification` dict this function already
        # unpacked — rather than from a new parameter, and that is deliberate: the
        # RESUME-FROM-CACHE path rebuilds the whole result from the cached bundle,
        # so reading the bundle is the only way both paths publish the same reasons.
        # Same content as `synthesis_bundle["verification"]["degradation_reasons"]`,
        # from the same one list, and put through the SAME normaliser the funnel key
        # goes through (15.2-08): one accumulator, one normaliser, two published
        # surfaces, identical content — so the worker's terminal-state decision and
        # the superadmin report can never name different degradations for one run.
        # The normaliser also returns a fresh list, so a consumer cannot mutate the
        # bundle, and returns [] rather than raising for a pre-15.2 synthesis_cache
        # that carries no such key at all.
        "degradation_reasons": _normalise_degradation_reasons(v.get("degradation_reasons")),
        # D-17 FACTS (plan 15.2-16), ADDITIVE — every existing key above and
        # below is untouched. `runs/worker.py` feeds this straight to
        # `terminal_state()`; when it is absent (an ADK run, or a pre-15.2
        # synthesis_cache replayed after deploy) the worker falls back to its own
        # literals, so this key is safe to add and safe to miss.
        #
        # Read from `v` — the bundle's `verification` dict — for the same reason
        # `degradation_reasons` is: the RESUME-FROM-CACHE path rebuilds the whole
        # result from the cached bundle, and reading the bundle is the only way
        # both paths publish the same facts.
        "terminal_inputs": _read_terminal_inputs(v),
        # D-06 citation-health counts, following the `rejected_claims` precedent:
        # top-level result keys, siblings of verification_summary and NOT inside
        # the funnel dict. Present on every run, including runs with zero anchors
        # (value 0, never absent) — a consumer never has to branch on the path.
        "unresolved_anchors": n_unresolved_anchors,
        "orphan_cite_markers": n_orphan_cites,
        "model_invented_numbers": n_model_numbers,
    }


#: How each research provider is shown in the UI — the actual deep-research model,
#: not just the provider key, so "which DR model was called" is answerable at a glance.
def _dr_model_display(provider: str | None) -> str:
    """Map a research provider key to its deep-research model display name."""
    from nestor_pulse_sdk.audit.audited_llm_client import (
        GEMINI_DEEP_RESEARCH_AGENT,
        OPENAI_DEEP_RESEARCH_MODEL,
    )
    p = (provider or "").strip().lower()
    return {
        "gemini": f"Gemini {GEMINI_DEEP_RESEARCH_AGENT}",
        "claude": "Claude claude-sonnet-4-6 +web",
        "openai": f"OpenAI {OPENAI_DEEP_RESEARCH_MODEL}",
        "own": "Own researcher (web search + Claude)",
    }.get(p, provider or "?")


def _angle_label(angle: dict[str, Any], idx: int) -> str:
    """Short human label for a research angle's deep-research sub-progress row.

    Shows the focus area, the actual DR model the angle was routed to, stakes —
    so the live per-angle status answers "which model, for what, succeeded/failed"
    — and, when D-I fired, that this dispatch was REDACTED before it left the
    platform.

    THE REDACTION CLAUSE IS PLAN 15.2-23'S CARRY-FORWARD (its deviation 1). That
    plan installed the egress scrub in `research_division.run_angles`, logged the
    count at WARNING and recorded it additively as `angle["pii_removed"]` — but it
    could not surface it, because the operator's feed row is built HERE, in a file
    it did not own. Without this clause the must-have "the operator sees that a
    dispatch was redacted" is only half met: reported and recorded, never
    rendered. The `deep_research` rows are re-built from the live angle dicts on
    every `_on_angle_done` callback, so reading the key here is all it takes.

    THE COUNT, NEVER THE VALUE (T-15.2-232). What was removed is deliberately
    absent from this string, exactly as it is absent from 15.2-23's log line: the
    feed row is stored in `run.stage_detail` and rendered in the browser, which
    are two more places the removed identifier must not reach.
    """
    label = (angle.get("focus_area") or angle.get("label") or "").strip()
    provider = (angle.get("provider") or "").strip()
    stakes = (angle.get("stakes") or "med").strip()
    base = label[:40] if label else f"Angle {idx + 1}"
    # Read defensively: `pii_removed` is absent on every clean angle (15.2-23
    # sets it only when the scrub actually removed something), and a non-int
    # value must never reach the row.
    _pii = angle.get("pii_removed")
    redacted = (
        f" · {int(_pii)} personal identifier(s) removed"
        if isinstance(_pii, int) and not isinstance(_pii, bool) and _pii > 0
        else ""
    )
    if provider:
        return f"{base} → {_dr_model_display(provider)} · {stakes}{redacted}"
    return f"{base}{redacted}"


def _dispatch_was_uniform(
    angles: Any, groups: Any, streams: Optional[int] = None
) -> bool:
    """Did EVERY group go out on EVERY stream? PURE, never raises. (WR-06.)

    COUNTING KEYS CANNOT ANSWER THIS QUESTION AND THAT WAS THE DEFECT. The feed
    tested `_corroborated` for EQUALITY WITH the group count, where `_corroborated`
    is the number of DISTINCT `corroboration_key`s. (The literal expression is
    deliberately not reproduced here: this file's gate greps for it with `#` comments
    filtered out, and a docstring is not a `#` comment, so quoting it verbatim would
    make the gate red on the FIXED source.) A group dispatched on three streams and trimmed
    back to one still contributes exactly ONE key, so the arithmetic was satisfied
    and the operator was told "every one of those N group(s) went to all 3 research
    streams" about a run where one of them went to one. Counting COPIES per key is
    what makes that sentence true.

    THIS IS NOT A COSMETIC WORDING FIX. That sentence is written into the run's own
    record, and plan 15.8-15 reads the record as the measurement of the whole
    five-wave redesign. There is no second run to correct it.

    True only when ALL THREE hold:
      * `groups` is non-empty — a restored pre-Wave-3 checkpoint dispatches with no
        groups at all, and an empty `groups` must never read as uniform;
      * the number of distinct keys equals the number of groups — so a group that
        produced no surviving angle still yields the weaker wording;
      * EVERY key carries exactly `streams` copies — the half `_corroborated`
        could not see.

    `streams` defaults to `len(_D6_STREAMS)`, which `research_division` documents as
    the ONE place the stream count lives; it is a parameter so a test can pin the
    arithmetic without reaching for the module global.

    The tolerant iteration is written LOCALLY rather than imported from
    `research_division`, deliberately: a shared symbol imported across a seam that
    two plans in the same phase both edit is what turned phase 15.5's merged tree
    red. The duplication is three lines and it buys seam independence.
    """
    try:
        group_list = list(groups or [])
        angle_list = list(angles or [])
    except Exception:  # noqa: BLE001 — a feed header never raises into a paid run
        return False
    if not group_list or not angle_list:
        return False
    expected = len(_D6_STREAMS) if streams is None else streams
    copies: dict[str, int] = {}
    for angle in angle_list:
        try:
            if not angle.get("corroboration"):
                continue
            key = str(angle.get("corroboration_key") or "")
        except Exception:  # noqa: BLE001 — model-adjacent data, never trusted
            continue
        if not key:
            continue
        copies[key] = copies.get(key, 0) + 1
    if len(copies) != len(group_list):
        return False
    return all(count == expected for count in copies.values())


def _angle_copies(angles: list[dict[str, Any]], angle: dict[str, Any]) -> int:
    """How many streams share this angle's sub-question. PURE.

    Feeds the research-division row so an operator can SEE that a sub-question
    was deliberately given to several providers — the corroboration the merge
    later reads — instead of guessing why the same question appears four times.
    """
    key = angle.get("corroboration_key") or ""
    if not key:
        return 1
    return sum(1 for a in angles if (a.get("corroboration_key") or "") == key)


def _claim_matches_assignment(
    claim: Any, *, provider: Any, group_id: Any, client_question: Any
) -> bool:
    """Does this claim belong to that assignment? PURE, NEVER RAISES.

    ONE rule, in ONE place, because BOTH halves of the `assignment_yield` row use
    it: `claims_kept` at the distill boundary and `claims_surviving_verification`
    after the skeptics. If the two halves disagreed about what a claim belongs to,
    the ratio they exist to produce would be quietly wrong in the one run that
    gets measured, and nothing would say so.

    THE RULE. The provider must appear in the claim's `found_by`, and then:

      * the assignment HAS a `group_id` -> the claim's `corroboration_key` must
        equal it, and the `facet` is NOT consulted;
      * the assignment has NO `group_id` (the focus-area fallback path) -> the
        claim's `corroboration_key` must be absent AND its `facet` must equal the
        assignment's `client_question`.

    WHY THE GROUP ID IS TRIED FIRST AND WHY A FACET MATCH ALONE WOULD BE WRONG.
    A CROSS-CUTTING (`d1`) assignment records `client_question = NULL` by ruling
    (D-W5-2), while its claims file under `labels[0]` through `_group_angle`'s
    ORPHAN RULE. Matching on `facet` would therefore attribute the ENTIRE
    cross-cutting group's claims — and its spend — to client question 1.
    """
    try:
        if not isinstance(claim, dict):
            return False
        found_by = claim.get("found_by")
        if not isinstance(found_by, (list, tuple)):
            return False
        if provider not in found_by:
            return False
        raw_key = claim.get("corroboration_key")
        claim_key = raw_key if isinstance(raw_key, str) and raw_key else None
        if group_id:
            return claim_key == group_id
        if claim_key is not None:
            return False
        return claim.get("facet") == client_question
    except Exception:  # noqa: BLE001 — an attribution reader never raises
        return False


def _assignment_yield_rows(provider_results: Any, claims: Any) -> list[dict[str, Any]]:
    """One `assignment_yield` row per successful assignment. PURE, NEVER RAISES.

    Returns a list of dicts holding EXACTLY the eleven keyword fields
    `yield_records.record_assignment_safe`'s `build` must return. It reads the
    `_`-prefixed keys `run_angles` stamped on each enriched result and derives
    three values from the claims that match the assignment.

    NOTHING HERE IS COERCED, CLAMPED, SCRUBBED OR DEFAULTED. `runs/yield_records`
    owns every one of those rules — the PII scrub-then-clamp on `client_question`
    (whose ORDER is load-bearing: clamping first can bisect an email into a
    fragment the scrubber no longer matches), the label clamps, and the
    counters-are-`None`-and-never-`0` rule. A SECOND coercion authority here is
    exactly how two modules end up disagreeing about what a NULL means, and the
    emitter's natural key is built from ITS normalisation on both paths. Raw
    values go through untouched.

    ⚠ TWO IMPRECISIONS IN `claims_kept`, STATED HERE RATHER THAN IN A PLAN NOBODY
    READS AT QUERY TIME. Both are DESIGN, not defects:

      1. `_dedupe_claims` is FIRST-WINS on `corroboration_key` and MERGES
         `found_by`. A statement found in two groups is therefore counted against
         the FIRST group only, and SUMMING `claims_kept` across assignments does
         NOT equal `len(claims)`.
      2. A claim found by TWO providers counts for BOTH rows, because it really
         did come out of both assignments. A SUM over providers therefore EXCEEDS
         the claim count BY DESIGN.

    ⛔ A FAILED OR TIMED-OUT ANGLE HAS NO ROW AT ALL, SO `SUM(cost_usd)` OVER THIS
    TABLE IS A LOWER BOUND AND NOT THE TOTAL (WR-02). `research_division._one_angle`
    returns `(provider, _enriched)` only on the SUCCESS path; a timeout or a runner
    error falls through, the angle never reaches `all_results`, `provider_results`
    carries no entry for it and this function emits nothing. A deep-research call
    that ran for thirty minutes and was then billed and timed out leaves NO TRACE
    HERE — and a missing ROW is invisible to every diagnostic the three
    NULL-skipping warnings in `assignment_yield.py`, `yield_records.py` and
    `0018_yield_instrumentation.py` describe, because those are all about a NULL
    CELL. This is stated and not fixed: D-W5-1 froze the column set, and a row
    shape for a failed angle is a schema change this deploy will not take.
    RECONCILE `COUNT(*)` HERE AGAINST THE DISPATCHED-ANGLE COUNT, and
    `SUM(cost_usd)` against `run.cost_usd_total`, BEFORE quoting any
    cost-per-claim figure. A shortfall means paid-but-unrecorded angles.

    ⚠ `fact_list_parsed` AND `resolvable_sources` ARE READ OFF THE RESULT AND ARE
    NEVER DERIVED FROM `claims` HERE. THIS IS THE WHOLE POINT AND IT IS EASY TO
    UNDO BY ACCIDENT. Both WERE derived from the matching claims until review
    CR-01, and both were WRONG in the shape the redesigned engine actually
    produces. The claims this function receives have ALREADY been through
    `synthesis/steps.py::_dedupe_claims`, which keeps the FIRST occurrence's dict
    whole while (a) APPENDING the second provider to `found_by` and (b) UNIONING
    `source_urls`. `_claim_matches_assignment` then hands that one merged dict to
    EVERY provider in `found_by`, so:

      * `resolvable_sources` counted the UNION of every corroborating provider's
        URLs for EACH of their rows — a stream that cited one link read as having
        cited four;
      * `fact_list_parsed` reported the FIRST provider's `fact_source` for BOTH
        rows — a stream that fell back to the distiller read `True` because a
        corroborating stream's D8 block parsed.

    Both read plausibly, neither is detectable from the table, and the error grows
    with the cross-stream duplicate rate — i.e. it is WORST exactly when
    corroboration works, flattening the per-provider discrimination D-R8 exists to
    measure. THE POST-DEDUPE CLAIM LIST CANNOT ANSWER A PER-PROVIDER QUESTION.
    Nothing in this module can. `matching` is available three lines above the
    binding and it is the wrong answer; do not reach for it.

    WHERE THE TWO VALUES COME FROM INSTEAD. `collect_provider_facts` stamps them
    on each `reports` entry as `ANGLE_YIELD_FACT_LIST_PARSED` /
    `ANGLE_YIELD_RESOLVABLE_SOURCES` (imported symbols, not literals), computed
    INSIDE its report loop from that assignment's OWN claims and captured AS
    VALUES — a bool and a URL-string count. Two facts made that the only workable
    shape, both verified against running code rather than reasoned about:

      1. `_dedupe_claims` MUTATES THE SURVIVING DICT IN PLACE, so a `list(claims)`
         snapshot holds THE SAME OBJECTS and shows the merged `found_by` and the
         unioned `source_urls` afterwards. A shallow pre-dedupe capture is INERT,
         not a fix. (`test_pipeline_assignment_yield` still pins this.)
      2. THE MERGE HAS ALREADY HAPPENED BEFORE THIS MODULE SEES A CLAIM.
         `collect_provider_facts` calls `_dedupe_claims(d8_claims +
         fallback_claims)` and returns the result as `ProviderFactsResult.claims`;
         `pipeline.py` binds that at the distill stage, so the `_dedupe_claims`
         call at the merge stage is the documented near-no-op. There is NO
         pre-merge claim list anywhere in this module, at any depth of copy.

    Holding an AGGREGATE rather than a copied list is what makes (1) structurally
    impossible instead of merely avoided: nothing downstream is holding a claim
    for the merge to mutate.

    WHAT THE TWO COLUMNS NOW MEAN, because the semantics CHANGED with the source:

      * `fact_list_parsed` is the REAL per-report parse outcome and no longer an
        inference from `fact_source`. `True` = this assignment's own D8 block
        parsed (first pass, D-R2 corrective re-ask, or the own-researcher's
        forced tool). `False` = it fell back to the distiller — and it now reads
        `False` even when a corroborating stream's block parsed, which is the
        contamination CR-01 named. `None` = NOT RECORDED: no report text, or the
        entry raised. It is NO LONGER `None` merely because the assignment kept
        no claims — "the list parsed and yielded nothing" and "there was no list"
        are different facts and the column can finally tell them apart.
      * `resolvable_sources` counts DISTINCT non-empty URLs cited by this
        assignment's own pre-merge claims. `0` is a measurement. `None` means the
        attribution does not exist — chiefly a FELL-BACK angle, whose claims are
        produced by the ONE shared full-extraction distiller call that discards
        the angle (it passes `corroboration_key=None` for the same reason).
        So `fact_list_parsed=False` WITH `resolvable_sources=NULL` is the normal,
        correct shape for a fallback row, not a hole.

    ⚠ AND THEY CAN BOTH BE NULL FOR A REASON THAT IS NOT THE ENGINE'S FAULT: a
    run RESTORED FROM A CHECKPOINT written before this stamp existed carries
    neither key, and `.get()` records NULL rather than raising. Same rule as
    `_sub_question` / `_corroboration_key` two stages up (T-15.5-07).

    `claims_kept` IS DELIBERATELY UNCHANGED and still counts over the post-dedupe
    list: its two imprecisions above are ruled design, and it must keep sharing a
    denominator basis with `claims_surviving_verification`.
    """
    rows: list[dict[str, Any]] = []
    try:
        results = provider_results if isinstance(provider_results, (list, tuple)) else []
        claim_list = claims if isinstance(claims, (list, tuple)) else []
        for entry in results:
            try:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    continue
                provider, result = entry
                if not isinstance(result, dict):
                    continue

                group_id = result.get("_corroboration_key")
                client_question = result.get("_client_question")
                matching = [
                    c for c in claim_list
                    if _claim_matches_assignment(
                        c, provider=provider, group_id=group_id,
                        client_question=client_question,
                    )
                ]

                # CR-01. FROM THE RESULT, NEVER FROM `matching`. `matching` holds
                # POST-MERGE claims whose `found_by` and `source_urls` are the
                # UNION over every provider that found them, so no per-provider
                # answer can be read off them — writing a plausible number from
                # there is the one outcome this table cannot survive. These two
                # were measured pre-merge, inside `collect_provider_facts`, and
                # travelled here as a bool and an int. An absent key (a
                # pre-stamp checkpoint, or a report that was never read) records
                # NULL, which is the honest "not recorded".
                fact_list_parsed = result.get(ANGLE_YIELD_FACT_LIST_PARSED)
                resolvable_sources = result.get(ANGLE_YIELD_RESOLVABLE_SOURCES)

                rows.append({
                    "provider": provider,
                    "group_id": group_id,
                    "client_question": client_question,
                    "parent_kind": result.get("_parent_kind"),
                    "stakes": result.get("_stakes"),
                    "fact_list_parsed": fact_list_parsed,
                    "retry_used": result.get("_retry_used"),
                    # A real 0 here is a MEASUREMENT ("this provider kept no
                    # claims"), never an absence. The emitter preserves that
                    # distinction; do not turn it into None.
                    "claims_kept": len(matching),
                    "resolvable_sources": resolvable_sources,
                    "cost_usd": result.get("cost_usd"),
                    "duration_s": result.get("_duration_s"),
                })
            except Exception as exc:  # noqa: BLE001 — one bad result costs ITS row only
                log.warning(
                    "tribunal_pipeline._assignment_yield_rows: could not build a "
                    "yield row for %r (%s: %s) — that assignment's measurement is "
                    "lost, the rest of the batch is not",
                    (entry[0] if isinstance(entry, (list, tuple)) and entry else None),
                    type(exc).__name__, exc,
                )
    except Exception as exc:  # noqa: BLE001 — the outer backstop
        log.warning(
            "tribunal_pipeline._assignment_yield_rows: aggregation failed (%s: %s) "
            "— returning the %d row(s) accumulated so far; the run is unaffected",
            type(exc).__name__, exc, len(rows),
        )
    return rows


def _intake_detail(mission_brief: dict[str, Any]) -> dict[str, Any]:
    """Build the intake stage sub-progress: the research plan the engine chose.

    Clear path → one row per focus area (label · taxonomy · stakes). Vague path →
    one row per clarifying question the engine asked. This is what makes the
    adaptive-intake RESULT visible in the UI for the whole run and afterwards.
    """
    if mission_brief.get("needs_clarification"):
        qs = mission_brief.get("clarifying_questions") or []
        items = [{"name": f"❓ {q}", "status": "pending"} for q in qs]
        return {"items": items or [{"name": "brief needs clarification", "status": "pending"}]}

    items: list[dict[str, str]] = []
    for fa in (mission_brief.get("focus_areas") or []):
        label = (fa.get("focus_area") or "").strip()
        if not label:
            continue
        # The workshop does not assign taxonomy codes, and rendering a bare "?"
        # for a focus area that simply has none would read as a missing value.
        # Inventing a code instead would be a fabricated fact, so the segment is
        # dropped when there is nothing true to put in it.
        tax = TAXONOMY.get(fa.get("taxonomy"), fa.get("taxonomy") or "")
        stakes = fa.get("stakes") or "med"
        # The rewritten, self-contained research brief intake authored for THIS
        # focus area — clarification answers folded in. This is the real text
        # divide() sends to the researcher; the label above is only the display
        # key. Surfaced expandable so the rewrite is visible at its source.
        prompt = (fa.get("research_prompt") or "").strip()
        items.append({
            "name": (
                f"{label[:56]} · {tax} · {stakes} stakes" if tax
                else f"{label[:56]} · {stakes} stakes"
            ),
            "status": "done",
            "prompt": prompt,
        })
    if not items:
        items = [{"name": "no focus areas extracted", "status": "failed"}]
    return {"items": items}


def _recon_is_meaningful(recon: Any) -> bool:
    """True when a group reconciliation carries actual meaning.

    `disputed` defaults to False and `relation` to "single"/"agree"
    (`group_skeptic._parse_group_verdict`), so an unconditional attach would file
    every verdict of every group into the report's `reconciled` / `superseded`
    sections. Extracted from `_flush_groups` so the coverage re-entry path SHARES
    the rule instead of forking it — this is an extraction, not a redesign, and its
    behaviour must stay identical.

    PURE: plain data in, bool out. Never raises.
    """
    if not isinstance(recon, dict):
        return False
    return bool(
        recon.get("disputed")
        or recon.get("relation") == "scoped"
        or str(recon.get("note") or "").strip()
        or str(recon.get("canonical") or "").strip()
    )


async def _coverage_reentry_pass(
    *,
    uncovered: list[dict[str, Any]],
    verdicts_by_claim: dict[int, list[dict]],
    superseded_notes: list[str],
    provider_results: list[tuple[str, dict]],
    audited: "AuditedLLMClient",
    run_id: uuid.UUID,
    tenant_id: uuid.UUID,
    sem: "asyncio.Semaphore",
    breaker: Any,
    book_unchecked: Any,
    model: str = _SKEPTIC_MODEL,
) -> dict[str, Any]:
    """ONE bounded coverage-gate re-entry pass. Returns sessions / recovered / blocked_reason.

    This is the last chance a gate-selected claim gets at a verdict — the recovery
    path WR-01 made unreachable. Three decisions are load-bearing here; all three
    are recorded in the plan and must not be "simplified" away.

    D-07-A (F7 — WHY THIS ROUTES THROUGH THE **GROUP** SKEPTIC). `EMIT_VERDICT_TOOL`'s
    verdict enum is `["support","refute","insufficient"]` and `tools.py`'s DELIBERATE
    ASYMMETRY comment forbids extending it. So a re-entered claim that is
    true-but-overtaken would come back `insufficient` — survives, no caveat — instead
    of `superseded`, whose G-07 note reaches synthesis through `contested_notes`.
    Re-entry therefore calls `run_group_skeptic` with a SINGLE-MEMBER group: the
    cheapest correct move, and the only one that keeps the fourth verdict on exactly
    the claims that needed a second chance. Do NOT put this back on `_one_skeptic`.

    D-07-C (THE BREAKER GATE IS `state`, NOT `allow()`). `allow()` CONSUMES the single
    half-open probe, and this is a FAN-OUT of N sessions, not a probe — authorising N
    calls on one probe token is exactly the failure the breaker exists to prevent.
    Re-entry proceeds only from a fully CLOSED circuit; `open` and `half_open` both
    refuse, and the uncovered claims go to bucket 3 with a named reason. G-11's "fail
    toward MORE checking" does not apply: the alternative is not more checking, it is
    more hard-400s (776 of them in 55 seconds on 2026-07-22).

    D-07-D (ONE THOROUGH SESSION, NOT THREE SHALLOW ONES). This path used to loop
    three per-claim skeptic calls for every uncovered claim. It now runs ONE session
    at `_GROUP_DEPTH["high"] == (6, 8, 5)`, which is the engine's own stated
    economics ("stakes controls the DEPTH of that single session, NOT the number of
    sessions"), what the grouped production path already does for every checked
    claim, and sufficient under `adjudicate`'s majority-independent rule, which
    already treats one refute-with-independent-citation as authoritative. The old
    hard-coded three did not even match `_PER_CLAIM_SKEPTICS`, which is 2.

    MODULE-LEVEL, and `book_unchecked` is a CALLABLE PARAMETER, so this is drivable
    from a test without constructing a pipeline run.
    """
    if not uncovered:
        return {"sessions": 0, "recovered": 0, "blocked_reason": None}

    # -- D-07-C: the breaker gate. READ the state; never consume the probe. -----
    state = getattr(breaker, "state", "closed")
    if state != "closed":
        try:
            breaker_reason = (breaker.snapshot() or {}).get("reason") or ""
        except Exception:  # noqa: BLE001 — a snapshot that raises must not eat the reason
            breaker_reason = ""
        blocked_reason = (
            f"VERIFICATION DEGRADED — the last-chance re-check of "
            f"{len(uncovered)} claim(s) was not attempted because the "
            f"fact-checking provider's circuit is {state}"
            + (f" ({breaker_reason})" if breaker_reason else "")
            + "; their supporting passages ship unexamined."
        )
        book_unchecked(
            uncovered, f"coverage re-entry blocked — skeptic circuit {state}"
        )
        log.warning(
            "tribunal_pipeline: coverage re-entry NOT dispatched — skeptic circuit "
            "is %s; %d claim(s) booked into bucket 3 (%s)",
            state, len(uncovered), breaker_reason or "no reason recorded",
        )
        return {"sessions": 0, "recovered": 0, "blocked_reason": blocked_reason}

    turns, su, fu = _GROUP_DEPTH["high"]

    async def _one_reentry(claim: dict) -> dict | None:
        # The five-key group contract from `grouping._assemble_groups`, with its own
        # display fallbacks (entity -> claims[0].facet or "?", attribute -> "general").
        group = {
            "key": f"__reentry__:{id(claim)}",
            "entity": (claim.get("facet") or "?"),
            "attribute": "general",
            "claims": [claim],
            "stakes": "high",
        }
        sources = _extract_sources_for_claim(claim, provider_results)
        async with sem:
            try:
                async with asyncio.timeout(_SKEPTIC_TIMEOUT_S):
                    result = await run_group_skeptic(
                        group=group, sources=sources, audited=audited,
                        run_id=run_id, tenant_id=tenant_id, model=model,
                        max_turns=turns, max_search_uses=su, max_fetch_uses=fu,
                    )
                try:
                    breaker.record_success()
                except Exception:  # noqa: BLE001 — bookkeeping is best-effort
                    pass
                return result
            except Exception as exc:
                try:
                    breaker.record_failure(exc)
                except Exception:  # noqa: BLE001 — bookkeeping is best-effort
                    pass
                log.warning(
                    "tribunal_pipeline: coverage re-entry session failed for claim %r: %s",
                    claim.get("text", "")[:60], exc,
                )
                return None

    results = await asyncio.gather(*[_one_reentry(c) for c in uncovered])
    sessions = len(uncovered)
    recovered = 0

    for claim, res in zip(uncovered, results):
        if not isinstance(res, dict):
            continue
        vbi = res.get("verdicts_by_index") or {}
        v = vbi.get(0)
        if isinstance(v, dict):
            recon = res.get("reconciliation") or {}
            if _recon_is_meaningful(recon):
                # dict(...) COPIES rather than aliases, matching _flush_groups.
                v["reconciliation"] = dict(recon)
            verdicts_by_claim.setdefault(id(claim), []).append(v)
            recovered += 1
        # D-07-A's whole point: harvest the G-07 caveat BEFORE the caller builds
        # contested_notes, exactly as _flush_groups does.
        superseded_notes.extend(_collect_superseded_notes([claim], vbi))
        # NOT appended to `group_reconciliations`: a synthetic single-member group's
        # `relation` defaults to "single" and its entity/attribute are display
        # fallbacks, so filing it there would print noise into the report's disputed
        # section under a made-up heading.

    # Bucket-3 site (c), unchanged in meaning and in WORDING — this is the recorded
    # cause string; do not reword it.
    for claim in uncovered:
        if not verdicts_by_claim.get(id(claim)):
            book_unchecked([claim], "coverage-gate re-entry returned no verdict")

    log.info(
        "tribunal_pipeline: coverage re-entry — %d session(s) dispatched, "
        "%d claim(s) recovered a verdict, %d still unchecked",
        sessions, recovered, sessions - recovered,
    )
    return {"sessions": sessions, "recovered": recovered, "blocked_reason": None}


def _one_line(text: Any) -> str:
    """Collapse ALL whitespace (newlines included) to single spaces, then strip.

    The prompt-block containment primitive for `_collect_superseded_notes`: a
    caveat is untrusted model output pasted into a prompt another model reads, so
    it must never be able to open a new line there.
    """
    return " ".join(str(text or "").split())


def _collect_superseded_notes(
    claims: Any,
    verdicts_by_index: Any,
) -> list[str]:
    """Format a group's `superseded` verdicts as `[SUPERSEDED] <claim>: <note>` lines.

    CR-01 / G-07. `group_skeptic._parse_group_verdict` produces `superseded_note`,
    and until this helper existed nothing consumed it: the caveat died inside
    `verdicts_by_claim` while the report body went on asserting the obsolete fact
    as current (the KPAnG failure, live run 4cbb5311). The lines returned here are
    merged into `contested_notes` — the list `synthesize_report` actually receives
    — so the caveat reaches synthesis as DATA the writing model PRESENTS, rather
    than something it phrases from memory.

    Tag convention imitates the existing `[DISPUTED]` / `[scope-dependent]` notes
    built from `group_reconciliations`.

    PROMPT-INJECTION CONTAINMENT (T-15.1-63): both the claim text and the note are
    untrusted model output about to be concatenated into a prompt block a second
    model reads. Newlines in either are collapsed to spaces and the claim text is
    truncated to `_SUPERSEDED_CLAIM_CHARS`, so a single note can neither open a new
    prompt line nor impersonate another entry.

    PURE by construction — plain data in, list of strings out; no DB, no LLM, no
    closure over pipeline state, which is what makes it testable without a run.
    NEVER raises: a malformed verdict dict yields no line rather than an exception,
    because this runs inside the verify stage's gather loop where one bad dict
    would otherwise cost a whole batch of group results.
    """
    notes: list[str] = []
    if not claims or not isinstance(verdicts_by_index, dict):
        return notes
    for i, c in enumerate(claims):
        try:
            v = verdicts_by_index.get(i)
            if not isinstance(v, dict) or v.get("verdict") != "superseded":
                continue
            raw_note = v.get("superseded_note")
            if not isinstance(raw_note, str):
                continue
            note = _one_line(raw_note)
            if not note:
                continue
            raw_text = (c.get("text") or c.get("claim_text") or "") if isinstance(c, dict) else ""
            text = _one_line(raw_text)[:_SUPERSEDED_CLAIM_CHARS]
            notes.append(f"[SUPERSEDED] {text}: {note}")
        except Exception:  # noqa: BLE001 — a bad verdict costs one line, not the batch
            continue
    return notes


def _verification_appendix(
    *,
    n_claims: int,
    n_survivors: int,
    n_dropped: int,
    n_unverified: int,
    n_contested: int,
    budget_exceeded: bool,
    reentry_count: int,
    claims_per_facet: dict[str, int] | None = None,
    n_unresolved_cites: int = 0,
) -> str:
    """Deterministic verification-scope section appended to the report.

    Honesty contract: the reader must be able to see how much of the report was
    actually fact-checked, what was removed, and whether the budget cap limited
    verification — without access to the audit database.
    """
    lines = [
        "\n\n---\n\n## Verification",
        "",
        f"*   **Factual statements extracted and reviewed:** {n_claims}",
        f"*   **Independently fact-checked against the live web:** {n_claims - n_unverified}",
        f"*   **Removed after failing fact-checking or losing a conflict:** {n_dropped} "
        "(the supporting passages were deleted from the research before this report was written)",
        # WR-11: this line used to describe these claims as "low-stakes supporting
        # detail". Under G-02 stakes no longer selects what gets
        # checked — the gates do — so n_unverified is now "claims with no verdict"
        # (gate-dropped + skipped-stable + members of unselected clusters) and has
        # nothing to do with stakes. The sentence was factually wrong about its own
        # engine. The operator reopened and resolved this in the 2026-07-25 gap-
        # closure scope: the sentence is CORRECTED without introducing any 15.1
        # gate vocabulary, so G-14's containment rule stands unchanged.
        f"*   **Not independently fact-checked:** {n_unverified}",
    ]
    if claims_per_facet:
        breakdown = ", ".join(
            f"{label}: {count}" for label, count in claims_per_facet.items()
        )
        lines.append(f"*   **Statements per research question:** {breakdown}")
        zeroes = [label for label, count in claims_per_facet.items() if count == 0]
        if zeroes:
            lines.append(
                "*   ⚠ **No checkable statements were extracted for:** "
                + ", ".join(zeroes)
                + " — content on these topics was NOT independently verified."
            )
    if n_contested:
        lines.append(
            f"*   **Open disagreements between sources:** {n_contested} "
            "(presented as contested in the body, not resolved)"
        )
    if reentry_count:
        lines.append(
            f"*   **Verification re-runs for under-covered high-stakes claims:** {reentry_count}"
        )
    if n_unresolved_cites:
        lines.append(
            f"*   ⚠ **Unresolvable source markers removed:** {n_unresolved_cites} "
            "(deep research emitted a citation marker the provider never tied to a "
            "URL; the empty markers were stripped rather than shown as dead references)"
        )
    if budget_exceeded:
        lines.append(
            "*   ⚠ **The verification budget cap was reached during this run** — "
            "claims processed after the cap were NOT independently fact-checked."
        )
    return "\n".join(lines)


def _propagate_stakes(
    claims: list[dict[str, Any]],
    mission_brief: dict[str, Any],
) -> None:
    """Copy each focus-area's stakes tier onto the claims that belong to it.

    claim_distiller emits {text, facet, evidence} with NO stakes key, so without
    this the triage saw every claim as unknown-tier and gave it 2 skeptics -- the
    ADR-006 high=3 / low=0 adaptive tiering never differentiated anything. We map a
    claim's facet back to its focus_area's stakes (default 'med' when unmatched).
    Mutates claims in place.
    """
    stakes_by_facet = {
        fa.get("focus_area"): fa.get("stakes")
        for fa in (mission_brief.get("focus_areas") or [])
        if fa.get("focus_area")
    }
    for c in claims:
        if c.get("stakes") in ("low", "med", "high"):
            continue  # already tagged (future-proofing)
        tier = stakes_by_facet.get(c.get("facet"))
        c["stakes"] = tier if tier in ("low", "med", "high") else "med"


def _extract_sources_for_claim(
    claim: dict[str, Any],
    provider_results: list[tuple[str, dict]],
) -> list[dict[str, Any]]:
    """Build a sources list for a claim's skeptic context.

    Extracts URLs from provider_results reports that are relevant to the
    claim's facet. Falls back to all provider URLs if no facet match.
    """
    claim_facet = claim.get("facet", "")
    sources: list[dict] = []

    for provider_name, result in provider_results:
        if not result or result.get("status") != "success":
            continue
        angle = result.get("_angle", "")
        if claim_facet and angle and claim_facet != angle:
            continue  # Not relevant to this claim's facet
        report = result.get("report") or ""
        # Build a minimal source dict with a URL placeholder + snippet
        sources.append({
            "url": f"provider:{provider_name}",
            "snippet": report[:500],
        })

    return sources


def _extract_sources_for_group(
    group: dict[str, Any],
    provider_results: list[tuple[str, dict]],
) -> list[dict[str, Any]]:
    """Merge the per-claim source context for every claim in a group, deduped.

    A group spans claims that may carry different facets, so union their sources
    (the group skeptic should see the evidence base for all variants at once)."""
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for claim in group.get("claims", []):
        for s in _extract_sources_for_claim(claim, provider_results):
            key = s.get("url", "")
            if key not in seen:
                seen.add(key)
                merged.append(s)
    return merged
