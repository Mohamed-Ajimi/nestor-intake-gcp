"""
LLMJudgeGate — homegrown reverse-engineered Anthropic Outcomes.

Architecture (per ADR-005 + user-directive, 2026-05-27):
  - One AuditedLLMClient.anthropic_messages call per ENABLED rubric dimension.
  - Per-dim CoT prompt with bad/good anchor examples (see prompts.py).
  - Scores 1-5 per dim; weighted average over enabled-only (weights renormalised
    to sum to 1.0) gives the overall pass signal.
  - Verdict.pass_ = (weighted_avg >= rubric.pass_threshold)
                    AND (every enabled dim score >= its per-dim threshold).
  - Fixes are collected freeform from each dim's judge response; Plan 09's
    synthesis loop concatenates them into the next-iteration prompt.
  - ZERO direct provider SDK calls — every LLM call routes through
    AuditedLLMClient so hash-chain + cost_usd + GCS blob land in audit_log.

Concurrency:
  - All enabled-dim calls fire in parallel via asyncio.gather().
  - AuditedLLMClient.anthropic_messages takes a per-worker semaphore (size 8)
    so we never overshoot Anthropic rate limits even at full plan-wide parallelism.

Failure handling:
  - If a single dim's judge call fails, we record the failure via
    AuditedLLMClient.write_failure(...) and assign that dim a score of 1.0
    (worst). The overall verdict reflects the failure rather than masking it.
  - If judge JSON parsing fails, we fall back to a regex score-extractor and
    flag the response as "parse_fallback" in the raw payload for the auditor.

For Plan 08 (this plan), `samples: 1` in the YAML means a single judge call per
dim. Phase 1.5+ may flip to samples=3-5 for self-consistency (median aggregation);
the judge is structured so that change is local to `_grade_one_dimension`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

from ..protocol import Verdict
from .rubric import Rubric, RubricDimension, load_rubric
from .prompts import build_user_prompt, system_prompt

log = logging.getLogger(__name__)


class LLMJudgeGate:
    """
    Homegrown rubric-based judge — routes every grading call through AuditedLLMClient.

    Constructor args:
      rubric: Rubric, optional. If None, loads from rubrics/default.yaml.
      judge_model: override the rubric's judge_model (e.g. for testing).
      max_tokens_per_dim: per-dim Anthropic max_tokens (default 1024).
    """

    name = "outcomes"  # matches the env-flag value NESTOR_QUALITY_GATE=outcomes

    def __init__(
        self,
        rubric: Optional[Rubric] = None,
        judge_model: Optional[str] = None,
        max_tokens_per_dim: int = 1024,
    ) -> None:
        self._rubric = rubric or load_rubric()
        self._judge_model = judge_model or self._rubric.judge_model
        self._max_tokens = max_tokens_per_dim

    # -----------------------------------------------------------------------
    # Public surface
    # -----------------------------------------------------------------------

    async def grade(
        self,
        *,
        synthesis: str,
        mission_brief: Optional[dict] = None,
        focus_areas: Optional[list[str]] = None,
        audited: Optional[Any] = None,
        run_id: Optional[Any] = None,
        tenant_id: Optional[Any] = None,
    ) -> Verdict:
        """
        Grade the synthesis against every ENABLED rubric dimension.

        `audited`, `run_id`, `tenant_id` are REQUIRED. Direct provider SDK use
        is forbidden in this code path (Plan 07 contract).

        Returns:
          Verdict with pass_, per_dim_scores (enabled dims only), fixes list,
          weighted_avg, legacy_verdict/feedback for backward compatibility.
        """
        if audited is None:
            raise ValueError(
                "LLMJudgeGate.grade requires an AuditedLLMClient via "
                "`audited=` (direct provider SDK use is forbidden — Plan 07 contract)."
            )
        if run_id is None or tenant_id is None:
            raise ValueError(
                "LLMJudgeGate.grade requires run_id and tenant_id for audit row linkage."
            )

        enabled = self._rubric.enabled_dimensions()
        if not enabled:
            raise ValueError("Rubric has no enabled dimensions — nothing to grade.")

        # Fire one judge call per enabled dim in parallel
        dim_tasks = [
            self._grade_one_dimension(
                dim,
                synthesis=synthesis,
                mission_brief=mission_brief,
                focus_areas=focus_areas,
                audited=audited,
                run_id=run_id,
                tenant_id=tenant_id,
            )
            for dim in enabled
        ]
        dim_results = await asyncio.gather(*dim_tasks, return_exceptions=True)

        return self._aggregate(enabled, dim_results)

    # -----------------------------------------------------------------------
    # Per-dimension judge call
    # -----------------------------------------------------------------------

    async def _grade_one_dimension(
        self,
        dimension: RubricDimension,
        *,
        synthesis: str,
        mission_brief: Optional[dict],
        focus_areas: Optional[list[str]],
        audited: Any,
        run_id: Any,
        tenant_id: Any,
    ) -> dict:
        """
        Grade one dimension. Returns dict {dim_id, score, reason, fixes, raw}.

        On API or parsing failure, returns score=1 + flagged raw payload + a
        write_failure() audit row.
        """
        prompt = build_user_prompt(
            dimension=dimension,
            synthesis=synthesis,
            mission_brief=mission_brief,
            focus_areas=focus_areas,
        )

        try:
            resp = await audited.anthropic_messages(
                run_id=run_id,
                tenant_id=tenant_id,
                model=self._judge_model,
                max_tokens=self._max_tokens,
                system=system_prompt(),
                messages=[{"role": "user", "content": prompt}],
            )
        except Exception as exc:
            log.error("[LLMJudgeGate] dim=%s API call failed: %s", dimension.id, exc)
            # Record the failure for hash-chain continuity (Plan 07 contract).
            try:
                await audited.write_failure(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    provider="anthropic",
                    error=exc,
                )
            except Exception:
                log.exception("[LLMJudgeGate] write_failure also raised")
            return {
                "dim_id": dimension.id,
                "score": 1,
                "reason": f"Judge API call failed: {exc}",
                "fixes": [],
                "raw": {"api_error": str(exc), "error_type": type(exc).__name__},
            }

        # Extract text from Anthropic response shape
        raw_text = self._extract_text(resp)
        parsed = self._parse_judge_response(raw_text, dimension.id)
        return parsed

    # -----------------------------------------------------------------------
    # Response parsing + aggregation
    # -----------------------------------------------------------------------

    @staticmethod
    def _extract_text(resp: Any) -> str:
        """Pull the text content out of an Anthropic Messages response."""
        try:
            if hasattr(resp, "content") and resp.content:
                # anthropic.types.Message.content is a list[ContentBlock]
                first = resp.content[0]
                if hasattr(first, "text"):
                    return first.text
                if isinstance(first, dict) and "text" in first:
                    return first["text"]
            if isinstance(resp, dict):
                content = resp.get("content")
                if content and isinstance(content, list):
                    block = content[0]
                    if isinstance(block, dict):
                        return block.get("text", "")
        except Exception as exc:
            log.warning("[LLMJudgeGate] _extract_text failed: %s", exc)
        return ""

    def _parse_judge_response(self, text: str, dim_id: str) -> dict:
        """
        Parse the judge's JSON output. Falls back to regex-based score extraction
        if JSON parsing fails so we never crash mid-grade.
        """
        if not text:
            return {
                "dim_id": dim_id,
                "score": 1,
                "reason": "Empty judge response",
                "fixes": [],
                "raw": {"parse_status": "empty"},
            }

        # Strip markdown fences if the judge added them despite instructions
        cleaned = re.sub(r'^```(?:json)?\s*', '', text.strip(), flags=re.MULTILINE)
        cleaned = re.sub(r'\s*```$', '', cleaned.strip(), flags=re.MULTILINE)

        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError as exc:
            log.warning(
                "[LLMJudgeGate] JSON parse failed for dim=%s; using regex fallback (%s)",
                dim_id, exc,
            )
            return self._regex_fallback(text, dim_id, exc)

        # Validate the shape
        score = data.get("score")
        if not isinstance(score, int) or score < 1 or score > 5:
            log.warning(
                "[LLMJudgeGate] dim=%s invalid score %r; clamping to 1",
                dim_id, score,
            )
            try:
                score = max(1, min(5, int(score)))
            except (TypeError, ValueError):
                score = 1

        fixes = data.get("fixes", [])
        if not isinstance(fixes, list):
            fixes = [str(fixes)]
        fixes = [str(f)[:500] for f in fixes]  # bound length defensively

        return {
            "dim_id": dim_id,
            "score": int(score),
            "reason": str(data.get("reason", "")),
            "fixes": fixes,
            "raw": data,
        }

    @staticmethod
    def _regex_fallback(text: str, dim_id: str, exc: Exception) -> dict:
        """Extract a 1-5 score from arbitrary text when JSON parsing fails."""
        m = re.search(r'"score"\s*:\s*([1-5])', text)
        if not m:
            m = re.search(r'\bscore\s*[:=]\s*([1-5])\b', text, flags=re.IGNORECASE)
        score = int(m.group(1)) if m else 1
        return {
            "dim_id": dim_id,
            "score": score,
            "reason": "Parse fallback (JSON malformed); regex score extraction used.",
            "fixes": [],
            "raw": {
                "parse_status": "regex_fallback",
                "parse_error": str(exc),
                "raw_text": text[:1000],
            },
        }

    def _aggregate(
        self,
        enabled_dims: tuple[RubricDimension, ...],
        dim_results: list,
    ) -> Verdict:
        """
        Combine per-dim results into the final Verdict.

        Weighted average uses renormalised weights (sum to 1.0 over enabled dims).
        Verdict.pass_ requires BOTH:
          - weighted_avg >= rubric.pass_threshold
          - every enabled dim's score >= its per-dim threshold
        """
        weights = self._rubric.enabled_weights()
        per_dim_scores: dict[str, float] = {}
        fixes_collected: list[str] = []
        raw_payload: dict[str, Any] = {"dim_results": []}

        all_dim_thresholds_met = True

        for dim, result in zip(enabled_dims, dim_results):
            if isinstance(result, Exception):
                # asyncio.gather wrapped the exception
                log.error("[LLMJudgeGate] dim=%s gathered exception: %s", dim.id, result)
                score = 1.0
                fix = f"[{dim.id}] judge call raised: {result}"
                raw_payload["dim_results"].append({
                    "dim_id": dim.id, "score": score, "exception": str(result),
                })
                fixes_collected.append(fix)
            else:
                score = float(result["score"])
                if result.get("fixes"):
                    fixes_collected.extend(
                        f"[{dim.id}] {fix}" for fix in result["fixes"]
                    )
                # Also include the per-dim reason as a fix-line when the dim is below threshold
                if score < dim.threshold and result.get("reason"):
                    fixes_collected.append(f"[{dim.id}] (below threshold): {result['reason']}")
                raw_payload["dim_results"].append(result)

            per_dim_scores[dim.id] = score
            if score < dim.threshold:
                all_dim_thresholds_met = False

        # Weighted average over enabled dims
        weighted_avg = sum(
            per_dim_scores[d.id] * weights[d.id] for d in enabled_dims
        )
        raw_payload["weights"] = weights
        raw_payload["weighted_avg"] = weighted_avg
        raw_payload["pass_threshold"] = self._rubric.pass_threshold

        pass_ = (
            weighted_avg >= self._rubric.pass_threshold
            and all_dim_thresholds_met
        )

        # Legacy verdict mapping for ADK pipeline compatibility
        if pass_:
            legacy_verdict = "pass"
            legacy_feedback = ""
        elif weighted_avg >= (self._rubric.pass_threshold - 0.5):
            legacy_verdict = "iterate"
            legacy_feedback = " | ".join(fixes_collected[:3]) if fixes_collected else "Below pass threshold."
        else:
            legacy_verdict = "fail"
            legacy_feedback = " | ".join(fixes_collected[:3]) if fixes_collected else "Significant quality gaps."

        return Verdict(
            pass_=pass_,
            per_dim_scores=per_dim_scores,
            fixes=fixes_collected,
            weighted_avg=weighted_avg,
            legacy_verdict=legacy_verdict,
            legacy_feedback=legacy_feedback,
            raw=raw_payload,
        )
