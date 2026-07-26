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

Intake is a DELEGATOR (quick task 260721-twy): the brief is operator-validated, so
adaptive_intake always produces a research plan and never asks clarifying questions.
The old vague-brief clarification-cap / force-proceed / early-return machinery is
gone. The ``needs_clarification`` / ``clarifying_questions`` keys survive only as
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
import uuid
from typing import Any, Optional, TYPE_CHECKING

from nestor_pulse_sdk.pipeline.tribunal.intake import adaptive_intake
from nestor_pulse_sdk.pipeline.tribunal.research_division import run_angles, divide
from nestor_pulse_sdk.pipeline.synthesis.steps import (
    claim_distiller,
    synthesize_report,
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
from nestor_pulse_sdk.pipeline.tribunal.reliability import BreakerSet
from nestor_pulse_sdk.pipeline.tribunal.budget import (
    over_budget,
    budget_marker,
    DEFAULT_MAX_BUDGET_USD,
    BUDGET_BEHAVIOUR,
    SURVIVAL_RULE,
)
from nestor_pulse_sdk.pipeline.synthesis.quality_gate import build_quality_gate
from nestor_pulse_sdk.runs.stages import set_stage, raise_if_cancelled
from nestor_pulse_sdk.pipeline.tribunal.taxonomy import TAXONOMY
from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims
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
#: one — but a long brief would crowd the claims out of the 4096-token gate
#: budget, so the text is bounded here (gates.py truncates again at its own
#: _CONTEXT_MAX_CHARS ceiling; this is the tighter of the two).
_GATE_DECISION_CONTEXT_CHARS = int(
    os.environ.get("NESTOR_TRIBUNAL_GATE_BRIEF_CHARS", "1200")
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
    handed the sharpened research prompt plus the focus-area labels. Bounded by
    _GATE_DECISION_CONTEXT_CHARS: a long brief must never crowd the claims out of
    the gate's own output budget.
    """
    parts: list[str] = []
    prompt = (mission_brief.get("deep_research_prompt") or "").strip()
    if prompt:
        parts.append(prompt)
    labels = [
        (fa.get("focus_area") or "").strip()
        for fa in (mission_brief.get("focus_areas") or [])
    ]
    labels = [lbl for lbl in labels if lbl]
    if labels:
        parts.append("Focus areas: " + " · ".join(labels))
    return "\n".join(parts).strip()[:_GATE_DECISION_CONTEXT_CHARS]


def _build_funnel(
    gate_funnel: dict[str, Any] | None,
    *,
    unchecked_selected: int,
    verify_sessions: int,
) -> dict[str, Any]:
    """The one funnel dict — the gates' nine keys plus the four this stage owns.

    Built in ONE place so the zero-claim early return and the full path cannot
    report different shapes (RESEARCH Pitfall 10): a downstream consumer must
    never have to branch on which path produced the report.

    The four pipeline-owned keys (G-08 / G-10 / G-13):
      checked                  -- selected for checking AND actually checked
      should_have_been_checked -- bucket 3: selected and NOT checked, whatever the
                                  cause (crash, timeout, usage cap, budget cap).
                                  This is the phase's most important number and
                                  must be ZERO on a healthy run.
      verification_degraded    -- the loud marker; true iff bucket 3 is non-empty.
      verify_sessions          -- skeptic sessions actually launched. G-13: a
                                  recorded pass-through measure of throughput, NOT
                                  a gate assertion — never assert on it.

    Keys are ADDITIVE ONLY. Phase-15 surfaces and test_hash_chain_replay.py assert
    on the existing names; renaming one breaks them silently.
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

    counts = (
        f"{checked} of {selected} selected claims checked · "
        f"{dropped} not checkable · {stable} stable facts skipped · "
        f"{sessions} skeptic sessions"
    )
    if gate_errors:
        counts += f" · {gate_errors} gate errors (sent for checking)"

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
        # Stage 1: Adaptive intake — DELEGATE (always produce a research plan)
        # ------------------------------------------------------------------
        # The brief is operator-validated (the intake backend is the only caller),
        # so adaptive_intake is a delegator now: it always returns a real plan and
        # never asks clarifying questions. The old clarification-cap / force-proceed
        # / early-return machinery is gone (quick task 260721-twy).
        await set_stage(run_id, tenant_id, "intake")
        mission_brief = await adaptive_intake(
            brief=brief,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )

        # Surface the adaptive-intake RESULT (focus areas + taxonomy + stakes) so it
        # stays visible for the whole run and afterwards — the research plan the
        # engine decided on.
        await set_stage(
            run_id, tenant_id, "intake", detail=_intake_detail(mission_brief)
        )

        # Bail before spending on deep research if the user already cancelled.
        await raise_if_cancelled(run_id, tenant_id)

        # ------------------------------------------------------------------
        # Stage 2: Hybrid research division
        # ------------------------------------------------------------------
        _n_fa = len(mission_brief.get("focus_areas") or [])
        angles = divide(mission_brief)
        # Show the ACTUAL division: each angle, the provider/model it was routed to,
        # and its stakes — a summary header line first.
        _division_items = [{
            "name": f"{_n_fa} focus area(s) → {len(angles)} research angle(s)",
            "status": "done",
        }]
        _division_items += [
            {
                "name": (
                    f"{(a.get('focus_area') or '').strip()[:48]} → "
                    f"{_dr_model_display(a.get('provider'))} · {a.get('stakes', 'med')}"
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

        provider_results = await run_angles(
            angles=angles,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
            on_angle_done=_on_angle_done,
        )

        # ------------------------------------------------------------------
        # Stage 3: Claim distillation
        # ------------------------------------------------------------------
        n_ok_angles = sum(1 for _, r in provider_results if r and r.get("status") == "success")
        await set_stage(
            run_id, tenant_id, "distill",
            detail={"items": [{
                "name": f"extracting claims from {n_ok_angles} research report(s)…",
                "status": "running",
            }]},
        )
        claims = await claim_distiller(
            provider_reports=provider_results,
            mission_brief=mission_brief,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
        )
        await set_stage(
            run_id, tenant_id, "distill",
            detail={"items": [{"name": f"{len(claims)} claims distilled", "status": "done"}]},
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
        _propagate_stakes(claims, mission_brief)

        # ------------------------------------------------------------------
        # Stage 3.5: Verification gates (G-01 / G-02 / G-11)
        # ------------------------------------------------------------------
        # Two cheap per-claim gates decide WHICH claims are worth fact-checking:
        # materiality (falsifiable-specific AND load-bearing for THIS client's
        # decision) and error-likelihood (a stable, notorious fact is skipped).
        # From here on the gate result is the SINGLE answer to "what gets
        # checked" — stakes no longer selects, it only sets how deep a surviving
        # session goes (G-02, _GROUP_DEPTH).
        #
        # G-04 ordering note: the gates run PER CLAIM and BEFORE the clusterer is
        # consulted for survival, so the per-claim keep/drop numbers reproduce;
        # clustering happens below and a cluster survives if ANY member survived.
        #
        # The gate is a cheap flash fan-out, but it is still a fan-out, and every
        # other fan-out in this pipeline cancel-checks first.
        await raise_if_cancelled(run_id, tenant_id)
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
        n_groups = 0
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

        if _GROUP_VERIFY:
            # --- Grouped verification (plan Phase 3) ---------------------------
            # Claims about the same entity|attribute are verified TOGETHER in ONE
            # thorough skeptic session that also reconciles contradictions. Stakes
            # controls the DEPTH of that single session (searches/fetches), NOT the
            # number of sessions — so the call count drops from ~3-per-claim to
            # ~1-session-per-GROUP. WHICH groups run is the gates' call (G-02), not
            # stakes': a low-stakes group with a load-bearing claim is now checked
            # (shallowly), and a high-stakes group of unfalsifiable claims is not.
            await set_stage(
                run_id, tenant_id, "verify",
                detail={"items": [{"name": f"grouping {len(claims)} claims…", "status": "running"}]},
            )
            groups = await group_claims(
                claims=claims, audited=audited, run_id=run_id, tenant_id=tenant_id,
            )
            n_groups = len(groups)
            multi = sum(1 for g in groups if len(g["claims"]) > 1)
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
                    for i, c in enumerate(grp["claims"]):
                        v = vbi.get(i)
                        if v is not None:
                            if recon_meaningful:
                                # dict(...) COPIES rather than aliases: a later
                                # mutation of the group result must not reach a
                                # verdict already built.
                                v["reconciliation"] = dict(recon)
                            verdicts_by_claim[id(c)].append(v)
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
                    continue
                sources = _extract_sources_for_group(group, provider_results)
                # ONE thorough session per selected group; stakes sets its depth.
                pending.append(_one_group_pass(group, sources))
                owners.append(group)
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

        # The ONE funnel for this run: built once, then carried on the synthesis
        # bundle, the verification report and the pipeline's return value, so the
        # feed, the operator report and run.verification_summary cannot disagree.
        verification_funnel = _build_funnel(
            gate_funnel,
            unchecked_selected=unchecked_selected,
            verify_sessions=total_skeptics,
        )
        # G-10: the closing summary states degradation in words, not with an icon.
        await set_stage(
            run_id, tenant_id, "verify",
            detail={"items": [_verify_closing_item(verification_funnel)]},
        )
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
        # Stage 7: Persist fine-grained survivor claims (RECALL MECHANISM)
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
                    # list the rejected_claims ledger just above was built from.
                    await persist_tribunal_claims(
                        claims=survivors,
                        dropped_claims=dropped,
                        verdicts_by_claim=verdicts_by_claim,
                        run_id=run_id,
                        tenant_id=tenant_id,
                        session=session,
                    )
        except Exception as exc:
            # Do NOT block synthesis on persistence failures; log for audit
            log.error("tribunal_pipeline: persist_tribunal_claims failed: %s", exc, exc_info=True)

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
            # 3. `brief_conflicts` IS POPULATED BY PLAN 15.2-13 (wave 6), which
            #    wires the question workshop into run(); the workshop's D4
            #    brief-vs-world flags (from 15.2-10's emit_orientation) are in
            #    scope at this point once that lands. Until then the list is
            #    empty and the subgroup simply does not render.
            # 4. `not_found_by_provider` is DELIBERATELY NOT HERE.
            #    `_write_final_report` reads `research_gap` directly, so the
            #    section works on the resume path and needs no wiring hand-off
            #    from 15.2-15 (which owns the WRITE path) beyond the rows.
            "report_sections": {
                "group_reconciliations": group_reconciliations,
                "superseded_notes": _deduped_superseded,
                "brief_conflicts": [],
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
                # The 15.1 funnel — the gates' nine keys plus this stage's four.
                # Carried on the bundle so it survives the interactive-report pause:
                # the resume path rebuilds the result from this cache, and
                # _write_final_report lifts the funnel back out of it onto the
                # pipeline's `verification_summary` key, which is what the worker
                # persists onto run.verification_summary (plan 15.1-08).
                "funnel": verification_funnel,
            },
        }
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

        # Zero-touch default: write the report now with no shaping spec.
        return await _write_final_report(
            bundle=synthesis_bundle, report_spec=None,
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

    await set_stage(run_id, tenant_id, "synthesize", detail={"items": [
        {"name": "writing final report", "status": "running"}]})

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
        # D-06 citation-health counts. SIBLINGS OF "funnel", never members of it:
        # verification_summary IS the same dict object as
        # verification_report["funnel"], and RECORDED_FUNNEL_COUNTS is compared by
        # FULL DICT EQUALITY in two tests — adding a key inside the funnel would
        # break them. This plan only guarantees the numbers exist and travel;
        # 15.2-08 owns folding them onto run.verification_summary and owns the
        # operator-facing wording. Always present, 0 on a run with no anchors.
        "unresolved_anchors": n_unresolved_anchors,
        "orphan_cite_markers": n_orphan_cites,
        "model_invented_numbers": n_model_numbers,
    }

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
        claims_per_facet=v.get("claims_per_facet") or {},
        n_unresolved_cites=n_orphan_cites,
    )

    await set_stage(run_id, tenant_id, "done", detail={"items": [{
        "name": (f"{v.get('survivor_count', 0)} verified claims · "
                 f"{v.get('dropped_count', 0)} dropped · "
                 f"{v.get('contested_count', 0)} contested"),
        "status": "done",
    }]})
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
        # from the same one list; a copy is taken so a consumer cannot mutate the
        # bundle. `or []` is the pre-15.2 synthesis_cache back-compat guard.
        "degradation_reasons": list(v.get("degradation_reasons") or []),
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
    }.get(p, provider or "?")


def _angle_label(angle: dict[str, Any], idx: int) -> str:
    """Short human label for a research angle's deep-research sub-progress row.

    Shows the focus area, the actual DR model the angle was routed to, and stakes —
    so the live per-angle status answers "which model, for what, succeeded/failed".
    """
    label = (angle.get("focus_area") or angle.get("label") or "").strip()
    provider = (angle.get("provider") or "").strip()
    stakes = (angle.get("stakes") or "med").strip()
    base = label[:40] if label else f"Angle {idx + 1}"
    if provider:
        return f"{base} → {_dr_model_display(provider)} · {stakes}"
    return base


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
        tax = TAXONOMY.get(fa.get("taxonomy"), fa.get("taxonomy") or "?")
        stakes = fa.get("stakes") or "med"
        # The rewritten, self-contained research brief intake authored for THIS
        # focus area — clarification answers folded in. This is the real text
        # divide() sends to the researcher; the label above is only the display
        # key. Surfaced expandable so the rewrite is visible at its source.
        prompt = (fa.get("research_prompt") or "").strip()
        items.append({
            "name": f"{label[:56]} · {tax} · {stakes} stakes",
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
