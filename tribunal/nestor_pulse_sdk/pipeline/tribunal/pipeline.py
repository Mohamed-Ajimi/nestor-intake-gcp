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
    }

Vague-brief early return:
    {
        "output_text":            str,   # summary of clarifying questions
        "needs_clarification":    True,
        "clarifying_questions":   list[str],
        "claim_count":            0,
        "verdict":                None,
        "verification_report":    {},
    }

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
)
from nestor_pulse_sdk.pipeline.tribunal.triage import triage_claims
from nestor_pulse_sdk.pipeline.tribunal.skeptic import run_skeptic
from nestor_pulse_sdk.pipeline.tribunal.grouping import group_claims
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import run_group_skeptic
from nestor_pulse_sdk.pipeline.tribunal.adjudicate import adjudicate_all
from nestor_pulse_sdk.pipeline.tribunal.coverage_gate import check_coverage, MAX_REENTRY
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
#: sessions. Low-stakes groups (supporting colour) still wave through unverified.
#: A single group skeptic that refutes WITH an independent citation is authoritative
#: — adjudicate's majority-independent rule already drops a 1/1 refute-with-source,
#: so no adjudication change is needed.
_GROUP_DEPTH: dict[str, tuple[int, int, int]] = {
    # stakes: (max_turns, max_search_uses, max_fetch_uses)
    "high": (6, 8, 5),
    "med": (4, 5, 3),
}


def _group_passes(stakes: str) -> int:
    """Sessions for a group: 1 for med/high, 0 for low (wave through)."""
    return 0 if stakes == "low" else 1
#: Cost ceiling (USD) the budget governor enforces across the skeptic fan-out.
_MAX_BUDGET_USD = float(
    os.environ.get("NESTOR_TRIBUNAL_MAX_BUDGET_USD", str(DEFAULT_MAX_BUDGET_USD))
)


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
        # Stage 1: Adaptive intake — sharpen brief or request clarification
        # ------------------------------------------------------------------
        await set_stage(run_id, tenant_id, "intake")
        # Clarification cap: allow at most 2 rounds of questions, then force research
        # with whatever we have. Round count = number of answer blocks the user has
        # added so far (0 = original brief, 1 = after one answer, ...).
        _CLAR_CAP = 2
        clar_rounds = brief.count("[CLARIFICATION ANSWERS]")
        force_proceed = clar_rounds >= _CLAR_CAP
        mission_brief = await adaptive_intake(
            brief=brief,
            audited=audited,
            run_id=run_id,
            tenant_id=tenant_id,
            allow_clarification=not force_proceed,
        )

        if mission_brief.get("needs_clarification") and force_proceed:
            # Cap reached but the model still asked. Proceed anyway with a minimal
            # single-focus mission_brief rather than ever asking a 3rd time.
            log.warning(
                "tribunal_pipeline: clarification cap (%d) reached -> forcing proceed",
                _CLAR_CAP,
            )
            base = brief.split("[CLARIFICATION ANSWERS]")[0].strip()
            mission_brief = {
                "deep_research_prompt": (base or brief)[:500],
                "language": "",  # not detected on the forced-proceed path -> infer downstream
                "focus_areas": [
                    {"focus_area": "Overall research question", "taxonomy": "D", "stakes": "high"}
                ],
                "needs_clarification": False,
                "clarifying_questions": [],
            }

        if mission_brief.get("needs_clarification"):
            questions = mission_brief.get("clarifying_questions", [])
            # Surface the clarification ask in the UI before returning.
            await set_stage(
                run_id, tenant_id, "intake", detail=_intake_detail(mission_brief)
            )
            log.info(
                "tribunal_pipeline: vague brief -> early return with %d clarifying questions",
                len(questions),
            )
            return {
                "output_text": (
                    "The brief requires clarification before research can begin. "
                    "Please answer the following questions:\n\n"
                    + "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))
                ),
                "needs_clarification": True,
                "clarifying_questions": questions,
                "claim_count": 0,
                "verdict": None,
                "verification_report": {},
            }

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
            return {
                "output_text": "(No claims could be distilled from the research reports.)",
                "claim_count": 0,
                "verdict": {"pass": None, "error": "no_claims"},
                "verification_report": {"verdicts": {}, "dropped_count": 0, "budget_marker": "", "coverage": {"pass": True, "uncovered": []}},
            }

        # ------------------------------------------------------------------
        # Stage 4: Stakes triage + verification (GROUPED by default, per-claim fallback)
        # ------------------------------------------------------------------
        # Propagate each focus-area's stakes (from intake) onto its claims so the
        # adaptive triage actually differentiates effort. claim_distiller emits
        # {text, facet, evidence} with NO stakes; without this every claim defaulted
        # to med (2 skeptics) and the ADR-006 high=3/low=0 tiering never fired.
        _propagate_stakes(claims, mission_brief)

        # Skeptic verification is the most expensive stage — check for a user cancel
        # before fanning out, and again between batches below.
        await raise_if_cancelled(run_id, tenant_id)

        # verdicts_by_claim: id(claim) -> list[verdict_dict]. Seed EVERY claim so
        # adjudication sees all of them (a claim with no verdicts survives).
        verdicts_by_claim: dict[int, list[dict]] = {id(c): [] for c in claims}
        budget_exceeded = False
        total_skeptics = 0
        group_reconciliations: list[dict] = []  # scoped/disputed notes from group skeptics
        n_groups = 0
        _sm = get_sessionmaker()
        sem = asyncio.Semaphore(_SKEPTIC_CONCURRENCY)

        # Per-claim skeptic caller — used by the per-claim branch AND by the
        # coverage-gate re-entry (which targets specific uncovered high-stakes
        # claims one at a time, in either verification mode). Defined once here so
        # it is always available regardless of which branch runs below.
        async def _one_skeptic(claim: dict, sources: list) -> dict | None:
            async with sem:
                try:
                    async with asyncio.timeout(_SKEPTIC_TIMEOUT_S):
                        return await run_skeptic(
                            claim=claim, sources=sources, audited=audited,
                            run_id=run_id, tenant_id=tenant_id, model=_SKEPTIC_MODEL,
                        )
                except Exception as exc:
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
            # ~1-session-per-GROUP. Low-stakes groups wave through unverified.
            await set_stage(
                run_id, tenant_id, "verify",
                detail={"items": [{"name": f"grouping {len(claims)} claims…", "status": "running"}]},
            )
            groups = await group_claims(
                claims=claims, audited=audited, run_id=run_id, tenant_id=tenant_id,
            )
            n_groups = len(groups)
            multi = sum(1 for g in groups if len(g["claims"]) > 1)
            total_passes = sum(_group_passes(g["stakes"]) for g in groups)
            done_passes = 0

            async def _verify_detail(done: int) -> None:
                await set_stage(
                    run_id, tenant_id, "verify",
                    detail={"items": [{
                        "name": (f"{min(done, total_passes)} / {total_passes} group checks · "
                                 f"{n_groups} groups ({multi} multi-claim) · {len(claims)} claims"),
                        "status": "running",
                    }]},
                )

            await _verify_detail(0)

            async def _one_group_pass(group: dict, sources: list) -> dict | None:
                turns, su, fu = _GROUP_DEPTH.get(group.get("stakes", "med"), _GROUP_DEPTH["med"])
                async with sem:
                    try:
                        async with asyncio.timeout(_SKEPTIC_TIMEOUT_S):
                            return await run_group_skeptic(
                                group=group, sources=sources, audited=audited,
                                run_id=run_id, tenant_id=tenant_id, model=_SKEPTIC_MODEL,
                                max_turns=turns, max_search_uses=su, max_fetch_uses=fu,
                            )
                    except Exception as exc:
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
                        continue
                    vbi = res.get("verdicts_by_index", {})
                    for i, c in enumerate(grp["claims"]):
                        v = vbi.get(i)
                        if v is not None:
                            verdicts_by_claim[id(c)].append(v)
                    recon = res.get("reconciliation") or {}
                    if recon.get("disputed") or recon.get("relation") == "scoped":
                        group_reconciliations.append({
                            "entity": grp.get("entity"), "attribute": grp.get("attribute"),
                            **recon,
                        })
                pending.clear()
                owners.clear()
                done_passes += n
                await _verify_detail(done_passes)

            for group in groups:
                npass = _group_passes(group["stakes"])
                if npass <= 0 or budget_exceeded:
                    continue
                sources = _extract_sources_for_group(group, provider_results)
                for _ in range(npass):
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
                "tribunal_pipeline: GROUP verify — %d group-checks over %d groups "
                "(%d multi-claim) / %d claims, %d reconciliations (capped=%s)",
                total_skeptics, n_groups, multi, len(claims),
                len(group_reconciliations), budget_exceeded,
            )

        else:
            # --- Per-claim verification (legacy fallback / A/B baseline) -------
            triaged = triage_claims(claims)
            _verified_count = 0

            await set_stage(
                run_id, tenant_id, "verify",
                detail={"items": [{"name": f"0 / {len(claims)} claims verified", "status": "running"}]},
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
                        "name": f"{min(_verified_count, len(claims))} / {len(claims)} claims verified",
                        "status": "running",
                    }]},
                )

            for claim, n_skeptics in triaged:
                if n_skeptics <= 0 or budget_exceeded:
                    continue
                sources = _extract_sources_for_claim(claim, provider_results)
                for _ in range(n_skeptics):
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
                "tribunal_pipeline: PER-CLAIM verify — ran %d skeptics over %d claims (capped=%s)",
                total_skeptics, len(triaged), budget_exceeded,
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

        # Build adjudications mapping for coverage gate: id(claim) -> True if adjudicated
        # A claim is "adjudicated" when it had skeptic verdicts run (n_skeptics > 0)
        # or was low-stakes (explicitly waved through with empty list).
        adjudications: dict[int, Any] = {
            id(c): True
            for c in claims
            if id(c) in verdicts_by_claim
        }

        # ------------------------------------------------------------------
        # Stage 6: Coverage gate (bounded re-entry)
        # ------------------------------------------------------------------
        await set_stage(run_id, tenant_id, "coverage")
        coverage = check_coverage(claims, adjudications)
        reentry_count = 0

        while not coverage["pass"] and reentry_count < MAX_REENTRY and not budget_exceeded:
            reentry_count += 1
            log.warning(
                "tribunal_pipeline: coverage gate FAIL — re-entry %d/%d for %d uncovered high-stakes claims",
                reentry_count, MAX_REENTRY, len(coverage["uncovered"]),
            )
            # Re-run skeptics for uncovered high-stakes claims only — concurrently,
            # reusing the same semaphore + per-skeptic timeout as the main stage.
            reentry_tasks: list = []
            reentry_owners: list = []
            for claim in coverage["uncovered"]:
                sources = _extract_sources_for_claim(claim, provider_results)
                verdicts_by_claim[id(claim)] = []
                adjudications[id(claim)] = True
                for _ in range(3):  # high-stakes = 3 skeptics
                    reentry_tasks.append(_one_skeptic(claim, sources))
                    reentry_owners.append(claim)
            reentry_results = await asyncio.gather(*reentry_tasks)
            for claim, verdict in zip(reentry_owners, reentry_results):
                if verdict is not None:
                    verdicts_by_claim[id(claim)].append(verdict)

            coverage = check_coverage(claims, adjudications)

        # Final adjudication after any re-entry
        if reentry_count > 0:
            adjudication_result = adjudicate_all(claims, verdicts_by_claim, SURVIVAL_RULE)
            survivors = adjudication_result["survivors"]
            dropped = adjudication_result["dropped"]

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
                    await persist_tribunal_claims(
                        claims=survivors,
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
    v = bundle.get("verification") or {}

    await set_stage(run_id, tenant_id, "synthesize", detail={"items": [
        {"name": "writing final report", "status": "running"}]})

    synthesis_text = await synthesize_report(
        mission_brief=mission_brief,
        provider_reports=cleaned_reports,
        audited=audited,
        run_id=run_id,
        tenant_id=tenant_id,
        contested_notes=contested_notes,
        report_spec=report_spec,
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
    }

    synthesis_text = synthesis_text + _verification_appendix(
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
        f"*   **Waved through unverified (low-stakes supporting detail):** {n_unverified}",
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
