"""Live smoke of every tribunal Gemini site config (quick task 261006-kzr).

Sends ONE tiny request per call site to the real Gemini Developer API, using the
REAL site config builders imported from the production modules -- so the model id
and the GenerateContentConfig sent here are exactly what production sends:

  gates      gates._make_config()                         with gates._GATE_MODEL
  grouping   grouping._make_config()                      with grouping._GROUPER_MODEL
  planner    report_planner._make_config()                with report_planner._PLANNER_MODEL
  rank       gates._make_config(model=_RANK_MODEL, level=_RANK_THINKING)
             (also what evolve meta-review and the admission classifier send)
  conflict   steps._make_conflict_config()                with steps._CONFLICT_MODEL
  scrub      steps._make_scrub_config()                   with steps._SCRUB_MODEL
  distiller  steps._make_distiller_config()               with steps._DISTILLER_MODEL

Per site it asserts: no exception, non-empty text, finish_reason != MAX_TOKENS,
and a parseable output in the site's contract shape. It prints one line per site
(model, thinking level and temperature actually sent, max_output_tokens,
finish_reason, prompt / candidates / thoughts tokens, latency, PASS/FAIL) and
exits non-zero if any site fails.

DELIBERATELY NOT AuditedLLMClient: no DB writes, no audit rows, no GCS. This is a
config-acceptance probe, not a run.

Usage (the key lives only in this one process's env; it is never printed,
logged or written):

    GOOGLE_API_KEY="$(gcloud secrets versions access latest --secret=Nestor_Gemini \
        --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a)" \
        python tribunal/nestor_pulse_sdk/scripts/gemini_model_smoke.py
"""
from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

_TRIBUNAL_ROOT = Path(__file__).resolve().parents[2]
if str(_TRIBUNAL_ROOT) not in sys.path:
    sys.path.insert(0, str(_TRIBUNAL_ROOT))


def _safe_err(exc: BaseException) -> str:
    """Status code + message only -- never request objects, headers or the key."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = getattr(exc, "message", None) or str(exc)
    key = os.environ.get("GOOGLE_API_KEY") or ""
    if key and key in msg:
        msg = msg.replace(key, "<redacted>")
    return f"{code} {msg}"[:400]


def _sent_level(cfg: Any) -> str:
    tc = getattr(cfg, "thinking_config", None)
    if tc is None:
        return "none"
    if getattr(tc, "thinking_level", None) is not None:
        v = tc.thinking_level
        return str(getattr(v, "value", v)).lower()
    if getattr(tc, "thinking_budget", None) is not None:
        return f"budget={tc.thinking_budget}"
    return "none"


def _sent_temp(cfg: Any) -> str:
    t = getattr(cfg, "temperature", None) if cfg is not None else None
    return "omitted" if t is None else str(t)


# ── per-site shape checks ───────────────────────────────────────────────────


def _check_gates(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if re.match(r"^\s*\d+\s*:\s*(KEEP|DROP)\b", ln)]
    return len(lines) == 2


def _check_grouping(text: str) -> bool:
    lines = [
        ln for ln in text.splitlines()
        if ln.count("|") == 2 and all(p.strip() for p in ln.split("|"))
    ]
    return len(lines) == 2


def _check_planner(text: str) -> bool:
    return bool(
        re.search(r"^LENGTH_RECOMMENDED:\s*(brief|standard|comprehensive)\b", text, re.M | re.I)
        and re.search(r"^TABLES_RECOMMENDED:\s*(none|key|heavy)\b", text, re.M | re.I)
        and len(re.findall(r"^FOCUS:.*\|\s*INCLUDE:.*\|\s*DEPTH:.*\|\s*RATIONALE:", text, re.M)) == 2
    )


def _check_rank(text: str) -> bool:
    return text.strip().strip(".").upper() in {"A", "B"}


def main() -> int:
    key = os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("GOOGLE_API_KEY is not set -- see the module docstring.", file=sys.stderr)
        return 2

    from google import genai

    from nestor_pulse_sdk.pipeline.synthesis import steps
    from nestor_pulse_sdk.pipeline.tribunal import gates, grouping, report_planner, workshop_rank

    client = genai.Client(api_key=key, vertexai=False)
    del key

    def check_conflict(text: str) -> bool:
        return isinstance(steps._extract_json_array(text), list) and "[" in text

    def check_scrub(text: str) -> bool:
        arr = steps._extract_json_array(text)
        return "[" in text and isinstance(arr, list) and all(isinstance(s, str) for s in arr)

    def check_distiller(text: str) -> bool:
        good = 0
        for ln in text.splitlines():
            cols = steps._split_distiller_line(ln.strip()) if ln.strip() else None
            if cols and len(cols) == 3 and all(cols):
                good += 1
        return good >= 1

    planner_prompt = report_planner._PROMPT_TEMPLATE.format(
        focus_block="1. Coffee prices in Belgium\n2. Competitor pricing",
        research=(
            "Average retail espresso price in Brussels was EUR 2.80 in 2025.\n"
            "Competitor X charges EUR 3.10 for a flat white.\n"
            "No data was found on wholesale bean prices."
        ),
    )

    sites: list[tuple[str, str, Callable[[], Any], str, Callable[[str], bool]]] = [
        (
            "gates", gates._GATE_MODEL, gates._make_config,
            "Screen these research claims. For EACH claim output exactly one line "
            "'<n>: KEEP' or '<n>: DROP' and nothing else.\n"
            "1: Company X reported revenue of EUR 41.2 million in 2024.\n"
            "2: Coffee is a popular drink.\n",
            _check_gates,
        ),
        (
            "grouping", grouping._GROUPER_MODEL, grouping._make_config,
            "Label each claim with its main ENTITY and ATTRIBUTE. Output exactly one "
            "line per claim: '<n> | <entity> | <attribute>' and nothing else.\n"
            "1: Lukoil Benelux operates 120 fuel stations.\n"
            "2: Lukoil Benelux was sold in 2024.\n",
            _check_grouping,
        ),
        (
            "planner", report_planner._PLANNER_MODEL, report_planner._make_config,
            planner_prompt,
            _check_planner,
        ),
        (
            "rank", workshop_rank._RANK_MODEL,
            lambda: gates._make_config(
                model=workshop_rank._RANK_MODEL, level=workshop_rank._RANK_THINKING
            ),
            "A client wants to decide whether to open a coffee bar in Ghent. Which "
            "research question is more useful?\n"
            "A: What is the average rent per square metre for retail units in central Ghent?\n"
            "B: What is the history of coffee?\n"
            "Answer with a single letter, A or B, and nothing else.",
            _check_rank,
        ),
        (
            "conflict", steps._CONFLICT_MODEL, steps._make_conflict_config,
            "Do any of these claims contradict each other?\n"
            "[0] Company X had 250 employees at the end of 2024.\n"
            "[1] Company X employed 40 people at the end of 2024.\n"
            "[2] Company X is headquartered in Antwerp.\n"
            "Return ONLY a JSON array (use [] if there are no contradictions). Each element:\n"
            '{"claims": [<indices>], "tension": "<what conflicts>", '
            '"loser": <index to drop, or null if neither side is clearly stronger>, '
            '"contested": <true if genuinely unresolved, else false>, '
            '"note": "<one-sentence explanation>"}',
            check_conflict,
        ),
        (
            "scrub", steps._SCRUB_MODEL, steps._make_scrub_config,
            "Find every passage in the report that states, or DEPENDS ON, the "
            "discredited claim. Return ONLY a JSON array of strings; each string must "
            "be one such passage COPIED VERBATIM from the report. Use [] if nothing matches.\n\n"
            "--- DISCREDITED CLAIMS ---\n- Company X has 250 employees.\n\n"
            "--- REPORTS ---\n\nCompany X is based in Antwerp. Company X has 250 "
            "employees, which makes it the largest roaster in the region. Its main "
            "product is a single-origin espresso blend.\n\n--- END REPORTS ---",
            check_scrub,
        ),
        (
            "distiller", steps._DISTILLER_MODEL, steps._make_distiller_config,
            "Extract every specific, checkable factual claim from the report below. "
            "Output one line per claim, exactly: FACET ||| CLAIM_TEXT ||| EVIDENCE "
            "(three columns separated by the three characters |||). No other text.\n\n"
            "REPORT:\nCompany X is based in Antwerp. It reported revenue of EUR 41.2 "
            "million in 2024. Its main product is a single-origin espresso blend.",
            check_distiller,
        ),
    ]

    failures = 0
    totals = {"prompt": 0, "candidates": 0, "thoughts": 0}
    per_model: dict[str, dict[str, int]] = {}
    print(
        "site      | model                 | think   | temp    | max_out | finish     "
        "| prompt | cand | thoughts | ms    | result"
    )
    for name, model, build, prompt, check in sites:
        cfg = build()
        level_sent = _sent_level(cfg)
        attempts = [(cfg, level_sent)]
        result_line = None
        for attempt, (c, lvl) in enumerate(attempts):
            kwargs = {"config": c} if c is not None else {}
            t0 = time.monotonic()
            try:
                resp = client.models.generate_content(model=model, contents=prompt, **kwargs)
            except Exception as exc:  # noqa: BLE001
                ms = int((time.monotonic() - t0) * 1000)
                err = _safe_err(exc)
                if (
                    name == "distiller"
                    and attempt == 0
                    and "400" in err
                    and "thinking" in err.lower()
                ):
                    from nestor_pulse_sdk.pipeline.gemini_config import build_generate_config

                    retry = build_generate_config(
                        model, level="low",
                        max_output_tokens=steps._DISTILLER_MAX_TOKENS, legacy_temperature=0.0,
                    )
                    print(f"distiller | {lvl} rejected: {err} -- retrying once at 'low'")
                    attempts.append((retry, _sent_level(retry)))
                    continue
                result_line = (
                    f"{name:<9} | {model:<21} | {lvl:<7} | {_sent_temp(c):<7} | "
                    f"{str(getattr(c, 'max_output_tokens', None)):<7} | ERROR      | "
                    f"{'-':>6} | {'-':>4} | {'-':>8} | {ms:>5} | FAIL ({err})"
                )
                failures += 1
                break
            ms = int((time.monotonic() - t0) * 1000)
            text = getattr(resp, "text", None) or ""
            cands = getattr(resp, "candidates", None) or []
            finish = str(getattr(cands[0], "finish_reason", None)) if cands else "NONE"
            finish = finish.split(".")[-1]
            um = getattr(resp, "usage_metadata", None)
            p = int(getattr(um, "prompt_token_count", 0) or 0)
            cnd = int(getattr(um, "candidates_token_count", 0) or 0)
            th = int(getattr(um, "thoughts_token_count", 0) or 0)
            totals["prompt"] += p
            totals["candidates"] += cnd
            totals["thoughts"] += th
            pm = per_model.setdefault(model, {"prompt": 0, "out": 0})
            pm["prompt"] += p
            pm["out"] += cnd + th
            ok = bool(text.strip()) and "MAX_TOKENS" not in finish and check(text)
            if not ok:
                failures += 1
            result_line = (
                f"{name:<9} | {model:<21} | {lvl:<7} | {_sent_temp(c):<7} | "
                f"{str(getattr(c, 'max_output_tokens', None)):<7} | {finish:<10} | "
                f"{p:>6} | {cnd:>4} | {th:>8} | {ms:>5} | {'PASS' if ok else 'FAIL'}"
            )
            if not ok:
                result_line += f" (text={text[:200]!r})"
            break
        print(result_line)

    print(
        f"TOTAL tokens: prompt={totals['prompt']} candidates={totals['candidates']} "
        f"thoughts={totals['thoughts']}"
    )
    try:
        from decimal import Decimal

        from nestor_pulse_sdk.audit import cost_table as ct

        spend = Decimal("0")
        for model, t in per_model.items():
            # thoughts are billed as OUTPUT by Google -> priced as completion here
            c = ct.compute("google", model, t["prompt"], t["out"], 0, 0)
            if c is not None:
                spend += c
        print(f"APPROX SPEND (thoughts billed as output): ${spend:.6f}")
    except Exception as exc:  # noqa: BLE001
        print(f"(spend not computed: {type(exc).__name__})")

    print(f"{len(sites) - failures}/{len(sites)} PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
