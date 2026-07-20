"""
Phase 1 spike for ADR-005 — Anthropic Outcomes as synthesis quality gate.

NOT production code. This file is archived after the ADR-005 decision lands.
See .planning/decisions/ADR-005-outcomes-quality-gate.md for the decision.

=============================================================================
SPIKE FINDINGS SUMMARY (recorded during Task 1 execution, 2026-05-27)
=============================================================================

Finding 1 — Outcomes API availability:
  The Anthropic Outcomes feature (rubric grader) is implemented in SDK 0.104.1
  as part of the Managed Agents Session lifecycle. It requires:
    a) A pre-registered Agent (via client.beta.agents.create)
    b) A pre-provisioned Environment (container infrastructure)
    c) A Session wrapping both
    d) Sending a `user.define_outcome` event into the session stream

  This is NOT a standalone text-evaluation endpoint. There is no API call of
  the form  evaluate(text=..., rubric=...) -> score. Outcomes is a loop-level
  primitive, not a document-level grader you can call against arbitrary text.

  Consequence for this spike: direct Outcomes API calls are not feasible without
  pre-provisioned Agent + Environment IDs from a Managed Agents account.

Finding 2 — Proxy measurement approach:
  To measure "what would Outcomes-level evaluation add", this spike implements
  an equivalent structured-judge prompt running against claude-sonnet-4-6 via
  the standard Messages API. The rubric mirrors what an Outcomes rubric would
  contain. This is documented as a PROXY, not as Outcomes itself.

  The proxy is a valid approximation because the Outcomes feature explicitly
  states it "runs an independent grader in a separate context window" — which
  is exactly what our judge prompt does. The rubric content is the same.

Finding 3 — Cost model:
  Outcomes pricing is not publicly documented separately from Managed Agents
  session costs (which include container runtime). The proxy measurement
  captures the LLM call cost (input + output tokens via Anthropic Messages API)
  as the lower bound on what Outcomes would cost. Container + orchestration
  overhead would be additional in the real Outcomes path.

Finding 4 — API prerequisite for production adoption:
  To use Outcomes in production, Nestor would need to:
    a) Register an Agent on the Anthropic console (or via SDK)
    b) Provision an Environment (container configuration)
    c) Create Sessions per synthesis run
    d) Stream events to/from the Session

  This represents a significantly deeper integration than the current
  single-call Gemini judge pattern. It requires always-on session management,
  webhook handling for terminal events, and container startup latency
  (typically 5-30 seconds per Anthropic docs).

=============================================================================
AUDIT LOGGING NOTE:
  This spike logs all LLM calls to a local list (spike_audit_log) since
  Plan 07 (AuditedLLMClient) runs in parallel with this plan. The production
  quality_gate.py will use the real AuditedLLMClient once Plan 07 merges.
  See quality_gate.py for the production integration pattern.
=============================================================================
"""

from __future__ import annotations

import asyncio
import os
import re
import time
import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spike-local audit log (replaces AuditedLLMClient while Plan 07 is in flight)
# ---------------------------------------------------------------------------

spike_audit_log: list[dict] = []


def _record_audit(
    call_type: str,
    model: str,
    provider: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float,
    latency_ms: int,
    sample_id: str,
) -> None:
    """Write a synthetic audit record. Production code uses AuditedLLMClient."""
    record = {
        "call_type": call_type,
        "model": model,
        "provider": provider,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cost_usd": cost_usd,
        "latency_ms": latency_ms,
        "sample_id": sample_id,
    }
    spike_audit_log.append(record)
    log.info("[SpikeAudit] %s", record)


# ---------------------------------------------------------------------------
# Anthropic token cost constants (claude-sonnet-4-6, May 2026)
# Source: https://www.anthropic.com/pricing
# ---------------------------------------------------------------------------

_SONNET_46_INPUT_USD_PER_1K = 0.003   # $3 / 1M tokens
_SONNET_46_OUTPUT_USD_PER_1K = 0.015  # $15 / 1M tokens


def _estimate_cost(input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a claude-sonnet-4-6 call."""
    return (
        (input_tokens / 1000) * _SONNET_46_INPUT_USD_PER_1K
        + (output_tokens / 1000) * _SONNET_46_OUTPUT_USD_PER_1K
    )


# ---------------------------------------------------------------------------
# Existing deterministic quality gate (ported read-only from steps.py)
# ---------------------------------------------------------------------------

def existing_quality_gate(synthesis: str, focus_areas: list[str]) -> tuple[str, str]:
    """
    Port of nestor_pulse/synthesis_pipeline/steps.py:quality_gate.
    Read-only — the ADK pipeline keeps its own copy. This port exists solely
    so the spike can run both gates without importing from nestor_pulse/.
    """
    issues: list[str] = []

    word_count = len(synthesis.split())
    if word_count < 300:
        return "fail", f"Too short: {word_count} words (minimum 300)"

    headers = re.findall(r'^#{1,6}\s+.+', synthesis, re.MULTILINE)
    if len(headers) < 3:
        issues.append(
            f"Insufficient structure: only {len(headers)} section headers (need at least 3)"
        )

    non_empty_lines = [l.strip() for l in synthesis.split('\n') if l.strip()]
    bullet_lines = sum(1 for l in non_empty_lines if l.startswith(('-', '*', '•')))
    if non_empty_lines and (bullet_lines / len(non_empty_lines)) > 0.75:
        issues.append("Too many bullet points — needs more narrative prose")

    if not issues:
        return "pass", ""

    feedback = " | ".join(issues)
    verdict = "iterate" if (word_count >= 400 and len(issues) == 1) else "fail"
    return verdict, feedback


# ---------------------------------------------------------------------------
# Judge rubric
# ---------------------------------------------------------------------------

SYNTHESIS_JUDGE_RUBRIC = """You are an expert evaluator grading a strategic research synthesis document.
Score the document on the following 5 criteria. Each criterion is worth 1 point.

CRITERIA:
1. GROUNDEDNESS: Every factual claim is supported by evidence referenced in the text
   (specific statistics, named sources, dates, or quantified findings). Score 1 if
   80%+ of claims have evidence; 0 if the document makes unsubstantiated assertions.

2. COHERENCE: The document presents a logically consistent narrative. Claims do not
   contradict each other. The argument flows from evidence to conclusions. Score 1 if
   coherent throughout; 0 if there are internal contradictions or logical gaps.

3. STRUCTURAL COMPLETENESS: The document covers the stated focus areas and has clear
   sections (headers) corresponding to key topics. Score 1 if all stated focus areas
   are addressed with dedicated sections; 0 if major focus areas are missing.

4. ACTIONABILITY: The document provides concrete, specific recommendations, next steps,
   or strategic implications — not just descriptive summaries. Score 1 if there are
   at least 3 specific actionable recommendations; 0 if recommendations are vague
   or absent.

5. EXECUTIVE CLARITY: The document can be read by a non-specialist business decision-maker.
   Jargon is explained; the most important finding is prominent; the document is not
   overly technical. Score 1 if the opening or executive summary clearly states the
   key strategic insight; 0 if the reader must parse dense technical text to find it.

RESPONSE FORMAT (JSON only, no preamble):
{
  "groundedness": 0 or 1,
  "groundedness_reason": "one sentence",
  "coherence": 0 or 1,
  "coherence_reason": "one sentence",
  "structural_completeness": 0 or 1,
  "structural_completeness_reason": "one sentence",
  "actionability": 0 or 1,
  "actionability_reason": "one sentence",
  "executive_clarity": 0 or 1,
  "executive_clarity_reason": "one sentence",
  "total_score": 0-5,
  "overall_verdict": "pass" or "needs_revision" or "fail",
  "overall_explanation": "one paragraph"
}

Thresholds:
- total_score 4-5 → "pass"
- total_score 3   → "needs_revision"
- total_score 0-2 → "fail"
"""


# ---------------------------------------------------------------------------
# Spike result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SpikeResult:
    sample_id: str
    existing_verdict: str         # "pass" | "iterate" | "fail"
    existing_feedback: str
    judge_score: float             # 0.0 – 1.0 (normalised from 0-5 rubric)
    judge_breakdown: dict          # per-criterion scores + reasons
    judge_overall_verdict: str     # "pass" | "needs_revision" | "fail"
    cost_usd_judge: float
    latency_ms_judge: int
    agreement: bool                # both gates agree on "good enough"
    outcomes_api_available: bool   # False = proxy judge used
    proxy_note: str                # explanation of what was measured


def _gate_verdict_to_good_enough(verdict: str) -> bool:
    """Map gate verdicts to a binary 'good enough' for agreement comparison."""
    return verdict == "pass"


def _judge_verdict_to_good_enough(verdict: str) -> bool:
    """Map judge verdicts to a binary 'good enough'."""
    return verdict == "pass"


# ---------------------------------------------------------------------------
# Judge call (proxy for Outcomes)
# ---------------------------------------------------------------------------

async def grade_with_judge(
    sample_id: str,
    brief_topic: str,
    focus_areas: list[str],
    synthesis: str,
    dry_run: bool = False,
) -> tuple[dict, float, int]:
    """
    Call claude-sonnet-4-6 with a structured judge prompt.

    This is a PROXY for Anthropic Outcomes. The rubric is equivalent to what
    an Outcomes rubric would contain. See module docstring for why direct
    Outcomes API calls are not feasible without pre-provisioned infrastructure.

    Returns: (breakdown_dict, cost_usd, latency_ms)
    """
    if dry_run:
        # Return a synthetic result for unit testing without API calls
        return {
            "groundedness": 1,
            "groundedness_reason": "mock",
            "coherence": 1,
            "coherence_reason": "mock",
            "structural_completeness": 1,
            "structural_completeness_reason": "mock",
            "actionability": 1,
            "actionability_reason": "mock",
            "executive_clarity": 1,
            "executive_clarity_reason": "mock",
            "total_score": 5,
            "overall_verdict": "pass",
            "overall_explanation": "Dry-run mock result. No API call made.",
        }, 0.0, 0

    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "anthropic SDK not installed. Run: pip install anthropic>=0.104"
        )

    api_key = os.getenv("ANTHROPIC_API_KEY") or _load_dotenv_key()
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Set it in nestor_pulse/.env or environment."
        )

    prompt = f"""{SYNTHESIS_JUDGE_RUBRIC}

---
BRIEF TOPIC: {brief_topic}
FOCUS AREAS: {', '.join(focus_areas)}

SYNTHESIS DOCUMENT TO GRADE:
{synthesis}
"""

    client = anthropic.Anthropic(api_key=api_key)

    t0 = time.monotonic()
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        log.error("[SpikeJudge] API call failed for %s: %s", sample_id, exc)
        raise

    latency_ms = int((time.monotonic() - t0) * 1000)

    raw_text = response.content[0].text if response.content else ""
    input_tokens = response.usage.input_tokens if response.usage else 0
    output_tokens = response.usage.output_tokens if response.usage else 0
    cost_usd = _estimate_cost(input_tokens, output_tokens)

    # Parse JSON response
    try:
        # Strip markdown code fences if present
        clean = re.sub(r'^```(?:json)?\s*', '', raw_text.strip(), flags=re.MULTILINE)
        clean = re.sub(r'\s*```$', '', clean.strip(), flags=re.MULTILINE)
        breakdown = json.loads(clean)
    except json.JSONDecodeError as exc:
        log.warning("[SpikeJudge] JSON parse failed (%s): %s", sample_id, exc)
        breakdown = {
            "parse_error": str(exc),
            "raw_response": raw_text[:500],
            "total_score": 0,
            "overall_verdict": "fail",
            "overall_explanation": f"Parse error: {exc}",
        }

    _record_audit(
        call_type="outcomes_proxy_judge",
        model="claude-sonnet-4-6",
        provider="anthropic",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        latency_ms=latency_ms,
        sample_id=sample_id,
    )

    return breakdown, cost_usd, latency_ms


def _load_dotenv_key() -> Optional[str]:
    """Try to load ANTHROPIC_API_KEY from nestor_pulse/.env."""
    try:
        from dotenv import dotenv_values
        # Search up to 4 parent dirs from this file
        here = Path(__file__).resolve()
        for _ in range(6):
            env_path = here / "nestor_pulse" / ".env"
            if env_path.exists():
                vals = dotenv_values(env_path)
                return vals.get("ANTHROPIC_API_KEY")
            here = here.parent
    except ImportError:
        pass
    return None


# ---------------------------------------------------------------------------
# Main spike runner
# ---------------------------------------------------------------------------

async def run_spike(dry_run: bool = False) -> list[SpikeResult]:
    """Run the spike on all 5 canned samples. Returns SpikeResult list."""
    from nestor_pulse_sdk.tests.fixtures.synthesis_samples.sample_data import ALL_SAMPLES

    results: list[SpikeResult] = []

    for sample in ALL_SAMPLES:
        log.info("[Spike] Running sample: %s", sample.sample_id)

        # Existing deterministic gate (latency is effectively 0)
        existing_verdict, existing_feedback = existing_quality_gate(
            sample.synthesis, sample.focus_areas
        )
        _record_audit(
            call_type="existing_heuristic_gate",
            model="deterministic",
            provider="local",
            input_tokens=0,
            output_tokens=0,
            cost_usd=0.0,
            latency_ms=0,
            sample_id=sample.sample_id,
        )

        # Judge call (Outcomes proxy)
        try:
            breakdown, cost_usd, latency_ms = await grade_with_judge(
                sample_id=sample.sample_id,
                brief_topic=sample.brief_topic,
                focus_areas=sample.focus_areas,
                synthesis=sample.synthesis,
                dry_run=dry_run,
            )
            outcomes_available = False  # proxy, not real Outcomes
            proxy_note = (
                "Proxy judge (claude-sonnet-4-6 Messages API) used. "
                "Real Outcomes API requires Managed Agents Session infrastructure "
                "(agent + environment + container). See module docstring."
            )
        except Exception as exc:
            log.error("[Spike] Judge failed for %s: %s", sample.sample_id, exc)
            breakdown = {
                "total_score": 0,
                "overall_verdict": "fail",
                "overall_explanation": f"Judge call error: {exc}",
            }
            cost_usd = 0.0
            latency_ms = 0
            outcomes_available = False
            proxy_note = f"Judge call failed: {exc}"

        judge_score = breakdown.get("total_score", 0) / 5.0
        judge_overall = breakdown.get("overall_verdict", "fail")

        existing_good = _gate_verdict_to_good_enough(existing_verdict)
        judge_good = _judge_verdict_to_good_enough(judge_overall)
        agreement = existing_good == judge_good

        result = SpikeResult(
            sample_id=sample.sample_id,
            existing_verdict=existing_verdict,
            existing_feedback=existing_feedback,
            judge_score=judge_score,
            judge_breakdown=breakdown,
            judge_overall_verdict=judge_overall,
            cost_usd_judge=cost_usd,
            latency_ms_judge=latency_ms,
            agreement=agreement,
            outcomes_api_available=outcomes_available,
            proxy_note=proxy_note,
        )
        results.append(result)

        log.info(
            "[Spike] %s: existing=%s judge=%s agreement=%s cost=$%.4f latency=%dms",
            sample.sample_id, existing_verdict, judge_overall,
            agreement, cost_usd, latency_ms,
        )

    return results


def _write_report(results: list[SpikeResult], report_path: Path) -> None:
    """Write the spike report to the given path."""
    total = len(results)
    agreed = sum(1 for r in results if r.agreement)
    agreement_pct = (agreed / total * 100) if total else 0

    total_cost = sum(r.cost_usd_judge for r in results)
    avg_cost = total_cost / total if total else 0
    avg_latency = sum(r.latency_ms_judge for r in results) / total if total else 0

    lines = [
        "# 01-08 Spike Report — ADR-005: Anthropic Outcomes Quality Gate",
        "",
        f"> Generated: 2026-05-27  |  SDK: anthropic==0.104.1  |  Samples: {total}",
        "",
        "---",
        "",
        "## 1. Methodology",
        "",
        "### Sample Set",
        f"{total} synthetic canned synthesis outputs were designed to cover the full verdict",
        "range of the existing rule-based QualityGate:",
        "",
        "| Sample ID | Topic Domain | Expected Existing Verdict |",
        "|-----------|-------------|--------------------------|",
    ]
    for r in results:
        lines.append(
            f"| `{r.sample_id}` | see fixture | `{r.existing_verdict}` |"
        )

    lines += [
        "",
        "None of the samples contain real client data (T-08-01 mitigation: synthetic only).",
        "",
        "### Outcomes API Finding",
        "",
        "**The Anthropic Outcomes API is not callable as a standalone document evaluator.**",
        "",
        "Investigation of Anthropic SDK 0.104.1 revealed that Outcomes is a Managed Agents",
        "Session primitive. It requires pre-registered Agent and Environment resources.",
        "The API shape is:",
        "",
        "```",
        "POST /v1/sessions  ->  session_id",
        "POST /v1/sessions/{id}/events  body: {type: 'user.define_outcome', rubric: ...}",
        "GET  /v1/sessions/{id}/events  ->  stream of outcome_evaluation events",
        "```",
        "",
        "There is no `evaluate(text=..., rubric=...) -> score` endpoint.",
        "Outcome evaluation is loop-level (the agent iterates), not document-level",
        "(grade this text once).",
        "",
        "### Proxy Measurement",
        "",
        "To measure the qualitative value of rubric-based evaluation, this spike used a",
        "**structured judge prompt** running against `claude-sonnet-4-6` via the standard",
        "Messages API. The rubric (5 criteria, 1pt each) mirrors what an Outcomes rubric",
        "would contain:",
        "",
        "1. Groundedness (claims have evidence)",
        "2. Coherence (logical narrative, no contradictions)",
        "3. Structural completeness (focus areas covered with headers)",
        "4. Actionability (concrete recommendations present)",
        "5. Executive clarity (readable by non-specialist decision-makers)",
        "",
        "This proxy is documented as a **lower-bound approximation**. Real Outcomes would",
        "add container startup latency (5-30s) and session orchestration overhead on top.",
        "",
        "---",
        "",
        "## 2. Results Table",
        "",
        "| Sample ID | Existing Gate | Existing Feedback | Judge Score | Judge Verdict | Agreement | Cost (USD) | Latency (ms) |",
        "|-----------|--------------|-------------------|-------------|---------------|-----------|------------|-------------|",
    ]

    for r in results:
        feedback_short = (r.existing_feedback[:50] + "…") if len(r.existing_feedback) > 50 else r.existing_feedback or "—"
        lines.append(
            f"| `{r.sample_id}` | `{r.existing_verdict}` | {feedback_short} "
            f"| {r.judge_score:.2f}/1.0 | `{r.judge_overall_verdict}` "
            f"| {'YES' if r.agreement else 'NO'} "
            f"| ${r.cost_usd_judge:.4f} | {r.latency_ms_judge} |"
        )

    lines += [
        "",
        f"**Agreement rate: {agreed}/{total} ({agreement_pct:.0f}%)**",
        f"**Total judge cost: ${total_cost:.4f}  |  Avg per brief: ${avg_cost:.4f}**",
        f"**Avg judge latency: {avg_latency:.0f} ms**",
        "",
        "---",
        "",
        "## 3. Cost + Latency Delta vs Existing QualityGate",
        "",
        "| Gate | LLM Calls | Avg Cost/Brief | Avg Latency/Brief | Notes |",
        "|------|-----------|---------------|-------------------|-------|",
        "| Existing deterministic | 0 | $0.0000 | <1 ms | Pure Python, no LLM |",
        f"| Proxy judge (Outcomes equivalent) | 1 | ${avg_cost:.4f} | {avg_latency:.0f} ms | claude-sonnet-4-6 Messages API |",
        f"| Real Outcomes (estimated) | 1+ | ${avg_cost:.4f} + session overhead | {avg_latency:.0f} ms + 5,000-30,000 ms container | Add Session creation + container startup |",
        "",
        "**Key delta:** The LLM call cost is approximately $"
        + f"{avg_cost:.4f} per brief. The existing gate is $0.",
        "Real Outcomes adds session management overhead (container startup, streaming,",
        "event polling) on top of the LLM cost. This is estimated at 5–30 additional",
        "seconds per synthesis run.",
        "",
        "---",
        "",
        "## 4. False-Positive / False-Negative Analysis",
        "",
    ]

    disagreements = [r for r in results if not r.agreement]
    if disagreements:
        lines.append(
            f"**{len(disagreements)} disagreement(s) found between existing gate and judge:**"
        )
        lines.append("")
        for r in disagreements:
            expl = r.judge_breakdown.get("overall_explanation", "—")
            lines += [
                f"### `{r.sample_id}`",
                f"- Existing gate: `{r.existing_verdict}` ({r.existing_feedback or 'no feedback'})",
                f"- Judge verdict: `{r.judge_overall_verdict}` (score {r.judge_score:.2f})",
                f"- Judge explanation: {expl}",
                "",
            ]
    else:
        lines += [
            "No disagreements found — both gates agreed on all samples.",
            "",
        ]

    lines += [
        "### Interpretation",
        "",
        "The existing deterministic gate catches structural failures (too short, missing headers,",
        "bullet-only) reliably. The judge proxy adds qualitative dimensions the existing gate",
        "cannot measure:",
        "",
        "- Whether factual claims are grounded in evidence (existing gate: cannot check)",
        "- Whether recommendations are actionable (existing gate: cannot check)",
        "- Whether the document serves a non-specialist reader (existing gate: cannot check)",
        "",
        "The judge also reveals a gap: `no_headers` fails the existing gate for missing headers,",
        "but the judge would evaluate it on qualitative criteria the existing gate ignores,",
        "and vice versa. They are complementary, not redundant.",
        "",
        "---",
        "",
        "## 5. Recommendation",
        "",
        "**ACCEPT WITH FLAG (recommended)**",
        "",
        "Rationale:",
        "",
        "1. **The Outcomes API (in its current form) is not drop-in replaceable** for the",
        "   existing QualityGate. It requires Managed Agents infrastructure that adds",
        "   significant operational complexity and 5-30s latency. For a synchronous",
        "   synthesis pipeline, this is a non-trivial regression.",
        "",
        "2. **The proxy judge demonstrates real qualitative value.** Groundedness, actionability,",
        "   and executive clarity are quality dimensions the deterministic gate cannot measure.",
        f"   At ${avg_cost:.4f}/brief, the LLM judge cost is acceptable for high-value synthesis runs.",
        "",
        "3. **ACCEPT WITH FLAG preserves optionality.** Ship `ExistingHeuristicGate` as",
        "   default (zero cost, zero latency), expose `OutcomesGate` (or equivalent judge)",
        "   behind `NESTOR_QUALITY_GATE=outcomes`. This enables A/B testing in production",
        "   and lets Yannick opt-in for specific high-stakes briefs.",
        "",
        "4. **The rubric authorship value (Yannick's key benefit) is achievable via judge**",
        "   **prompt without full Managed Agents adoption.** If Nestor adopts Managed Agents",
        "   in Phase 2-3, the Outcomes integration becomes trivially easy to upgrade.",
        "",
        "---",
        "",
        "## 6. Risk Register",
        "",
        "| Risk | Likelihood | Impact | Mitigation |",
        "|------|-----------|--------|------------|",
        f"| Cost regression: judge adds $~{avg_cost:.4f}/brief | Medium | Low | ACCEPT-WITH-FLAG keeps default=$0 |",
        "| Rubric drift: judge prompt changes across model updates | Medium | Medium | Pin model version; review rubric quarterly |",
        "| Vendor lock: Anthropic-only judge | Low | Low | Rubric prompt is model-agnostic; can be ported to Gemini |",
        "| Outcomes API deprecation or change | Low | Medium | ACCEPT-WITH-FLAG defers Outcomes coupling; easy to remove |",
        "| False negatives: judge misses structural issues existing gate catches | Low | Medium | Keep existing gate as pre-check; judge runs after |",
        "",
        "---",
        "",
        "## 7. Audit Log Summary",
        "",
        f"Total API calls recorded: {len(spike_audit_log)}",
        "Provider breakdown:",
    ]

    provider_counts: dict[str, int] = {}
    for entry in spike_audit_log:
        p = entry.get("provider", "unknown")
        provider_counts[p] = provider_counts.get(p, 0) + 1
    for provider, count in sorted(provider_counts.items()):
        lines.append(f"- {provider}: {count} calls")

    lines += [
        "",
        "---",
        "",
        "## 8. Data Appendix",
        "",
        "Full per-sample judge breakdowns:",
        "",
    ]
    for r in results:
        lines.append(f"### `{r.sample_id}` — Judge Breakdown")
        lines.append("```json")
        lines.append(json.dumps(r.judge_breakdown, indent=2))
        lines.append("```")
        lines.append("")

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    log.info("[Spike] Report written to %s", report_path)


async def main(dry_run: bool = False) -> list[SpikeResult]:
    """Entry point for the spike. Returns results for programmatic use."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    log.info("[Spike] Starting ADR-005 outcomes spike (dry_run=%s)", dry_run)
    results = await run_spike(dry_run=dry_run)

    # Determine report path relative to repo root
    here = Path(__file__).resolve()
    repo_root = here
    for _ in range(10):
        if (repo_root / ".planning").exists():
            break
        repo_root = repo_root.parent

    # SPIKE-REPORT corruption guard (.continue-here.md constraint #5):
    # The canonical 01-08-SPIKE-REPORT.md is a one-shot artifact from the
    # Task 1 real-API run ($0.0563 total, 60% agreement). dry_run=True runs
    # (including any pytest invocation of this main()) MUST NOT overwrite it
    # with mock zeros. When dry_run is True we redirect the write to a tempdir
    # so the canonical file stays intact.
    if dry_run:
        import tempfile
        report_path = Path(tempfile.gettempdir()) / "01-08-SPIKE-REPORT.dryrun.md"
        log.info("[Spike] dry_run mode: redirecting report write to %s", report_path)
    else:
        report_path = (
            repo_root
            / ".planning"
            / "phases"
            / "01-production-foundation"
            / "01-08-SPIKE-REPORT.md"
        )
    _write_report(results, report_path)

    # Print summary to stdout
    total = len(results)
    agreed = sum(1 for r in results if r.agreement)
    total_cost = sum(r.cost_usd_judge for r in results)
    avg_latency = sum(r.latency_ms_judge for r in results) / total if total else 0

    print("\n" + "=" * 60)
    print("SPIKE COMPLETE")
    print(f"  Samples:      {total}")
    print(f"  Agreement:    {agreed}/{total} ({agreed/total*100:.0f}%)")
    print(f"  Total cost:   ${total_cost:.4f}")
    print(f"  Avg latency:  {avg_latency:.0f} ms/brief")
    print(f"  Report:       {report_path}")
    print("=" * 60 + "\n")

    return results


if __name__ == "__main__":
    asyncio.run(main())
