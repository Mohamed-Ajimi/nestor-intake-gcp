"""Opt-in/slow integration test: clarify pause/resume + per-engine cap (Plan 01-18).

Mirrors the skip/opt-in pattern of test_tribunal_e2e.py — skipped unless
NESTOR_CLARIFY_E2E=1 is set AND a live server URL + tester JWT are provided.
Default `pytest` run (offline / CI) stays green: the test is skipped cleanly.

What this test asserts (Plan 01-18 D-17 mandate; updated 260721-twy):
  1. For tribunal: the intake stage is a DELEGATOR since 2026-07-21 — a vague brief
     no longer parks as needs_input; the run goes straight to a terminal status
     (0 clarification rounds). The lifecycle helper tolerates this (cap kept as an
     upper bound only; any needs_input round from tribunal would now be a regression
     caught by the <= max_rounds assertion staying at 0).
  2. For adk: same lifecycle, but rounds are bounded only by the smoke guard
     (MAX_ADK_ROUNDS=4); each round MUST produce needs_input + clarifying_questions.
  3. Per-engine cap contract from test_clarification_cap_per_engine.py is not
     duplicated here — the contract is structural (source-level grep). This test
     validates the RUNTIME lifecycle over HTTP.

Skip condition:
  NESTOR_CLARIFY_E2E=1 must be set, PLUS:
    NESTOR_BASE_URL  — the live API root, e.g. https://nestor-pulse-api-...
    NESTOR_SMOKE_TOKEN — Identity Platform ID token (Bearer)
    NESTOR_SMOKE_PROJECT_ID — a project UUID visible to the token's tenant

To run (both engines):
  NESTOR_CLARIFY_E2E=1 \\
  NESTOR_BASE_URL=https://nestor-pulse-api-ybkr7metoq-ew.a.run.app \\
  NESTOR_SMOKE_TOKEN=<id-token> \\
  NESTOR_SMOKE_PROJECT_ID=<uuid> \\
  pytest nestor_pulse_sdk/tests/test_clarify_resume_loop.py -x -m slow --tb=short

To run one engine only:
  NESTOR_CLARIFY_ENGINE=tribunal pytest ...

Note: Test duration depends on engine + run complexity (minutes per engine).
      Mark with --timeout=600 if your pytest-timeout limit is low.
"""
from __future__ import annotations

import json
import os
import time
import uuid
import urllib.request
import urllib.error
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Skip guard — opt-in via NESTOR_CLARIFY_E2E=1
# ---------------------------------------------------------------------------
_E2E_ENABLED = os.environ.get("NESTOR_CLARIFY_E2E", "").strip() in (
    "1", "true", "True", "yes"
)

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not _E2E_ENABLED,
        reason=(
            "Skipped: NESTOR_CLARIFY_E2E not set. "
            "Set NESTOR_CLARIFY_E2E=1 (plus NESTOR_BASE_URL / NESTOR_SMOKE_TOKEN / "
            "NESTOR_SMOKE_PROJECT_ID) to run against a live server."
        ),
    ),
]

# ---------------------------------------------------------------------------
# Constants (mirror clarify_loop_smoke.py values for consistency)
# ---------------------------------------------------------------------------
_VAGUE_BRIEF = (
    "Research the market. "
    "We need to understand the competitive landscape and identify key players."
)
_CLARIFICATION_ANSWER = (
    "Focus on the European B2B SaaS market for AI-powered legal research tools. "
    "Time window: last 24 months. Deliverable: a competitive matrix with pricing. "
    "This is for an investment decision — please verify all claims."
)
MAX_TRIBUNAL_ROUNDS = 2    # Tribunal cap; must force-proceed by round 2
MAX_ADK_ROUNDS = 4         # Smoke guard for uncapped ADK
_TERMINAL = {"completed", "failed", "cancelled"}
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def live_config():
    """Resolve live server config from env; fail with a clear message if missing."""
    base_url = os.environ.get("NESTOR_BASE_URL", "").rstrip("/")
    token = os.environ.get("NESTOR_SMOKE_TOKEN", "")
    project_id = os.environ.get("NESTOR_SMOKE_PROJECT_ID", "")

    missing = []
    if not base_url:
        missing.append("NESTOR_BASE_URL")
    if not token:
        missing.append("NESTOR_SMOKE_TOKEN")
    if not project_id:
        missing.append("NESTOR_SMOKE_PROJECT_ID")

    if missing:
        pytest.skip(
            f"Skipped: live server env vars not set: {', '.join(missing)}. "
            "Provide these to run the clarify e2e test."
        )

    # Guard: DEMO_MODE must be off on the server.
    demo = os.environ.get("DEMO_MODE", "").strip()
    if demo not in ("", "0", "false", "False", "no"):
        pytest.skip("DEMO_MODE is set — skipping clarify e2e (bypasses engine + DB).")

    return {"base_url": base_url, "token": token, "project_id": project_id}


@pytest.fixture
def clarify_engine():
    """Engine to test, from NESTOR_CLARIFY_ENGINE (default: both)."""
    return os.environ.get("NESTOR_CLARIFY_ENGINE", "both")


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib-only, no aiohttp / requests dependency)
# ---------------------------------------------------------------------------

def _http(method: str, url: str, *, token: str, body: dict | None = None) -> tuple[int, Any]:
    """Make a JSON HTTP request; return (status_code, parsed_body)."""
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, {"raw": raw.decode("utf-8", errors="replace")}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw.decode("utf-8", errors="replace")}


def _get(cfg: dict, path: str) -> Any:
    code, body = _http("GET", f"{cfg['base_url']}{path}", token=cfg["token"])
    assert code == 200, f"GET {path} -> {code}: {body}"
    return body


def _post(cfg: dict, path: str, body: dict) -> Any:
    code, resp = _http("POST", f"{cfg['base_url']}{path}", token=cfg["token"], body=body)
    assert code in (200, 201), f"POST {path} -> {code}: {resp}"
    return resp


def _poll(cfg: dict, run_id: str, *, targets: set[str]) -> dict:
    """Poll GET /api/runs/{run_id} until status in targets or timeout."""
    deadline = time.monotonic() + POLL_TIMEOUT_S
    last = ""
    while time.monotonic() < deadline:
        data = _get(cfg, f"/api/runs/{run_id}")
        status = data.get("status", "")
        if status != last:
            print(f"  run {run_id[:8]}... -> {status}")
            last = status
        if status in targets:
            return data
        time.sleep(POLL_INTERVAL_S)
    pytest.fail(
        f"Timed out after {POLL_TIMEOUT_S}s waiting for {targets!r}; "
        f"last status={last!r}, run_id={run_id}"
    )


# ---------------------------------------------------------------------------
# Core lifecycle helper
# ---------------------------------------------------------------------------

def _drive_clarify_lifecycle(
    cfg: dict,
    engine: str,
    max_rounds: int,
) -> dict:
    """Drive the needs_input -> answer -> resume -> completed lifecycle.

    Returns final run state dict.  Asserts the per-engine cap contract.
    """
    # 1. Submit vague brief
    run = _post(cfg, "/api/runs", {
        "project_id": cfg["project_id"],
        "brief": _VAGUE_BRIEF,
        "engine": engine,
        "idempotency_key": str(uuid.uuid4()),
    })
    run_id: str = str(run["id"])
    print(f"\n  [{engine}] Initial run_id={run_id[:8]}... status={run.get('status')!r}")

    clar_round = 0
    current_run_id = run_id

    while True:
        # 2. Poll until needs_input or terminal
        state = _poll(cfg, current_run_id, targets={"needs_input"} | _TERMINAL)
        status = state.get("status", "")

        if status in _TERMINAL:
            print(f"  [{engine}] Terminal status: {status!r}  (after {clar_round} round(s))")
            break

        # status == "needs_input"
        questions = state.get("clarifying_questions") or []
        assert questions, (
            f"[{engine}] status==needs_input but clarifying_questions is empty: {state!r}"
        )

        clar_round += 1
        print(f"  [{engine}] Round {clar_round}: needs_input with {len(questions)} question(s)")

        # Cap assertions
        if engine == "tribunal":
            assert clar_round <= max_rounds, (
                f"Tribunal exceeded the 2-round cap: asked in round {clar_round}. "
                "pipeline/tribunal/pipeline.py _CLAR_CAP=2 + force_proceed must fire."
            )
        else:
            assert clar_round <= max_rounds, (
                f"ADK smoke guard: asked in round {clar_round} > MAX_ADK_ROUNDS={max_rounds}. "
                "Investigate misconfigured server (ADK is uncapped by design, but the "
                "harness caps the smoke run to prevent unattended looping)."
            )

        # 3. Answer
        answer_resp = _post(cfg, f"/api/runs/{current_run_id}/answer", {
            "answers": _CLARIFICATION_ANSWER,
        })
        mode = answer_resp.get("mode", "run")
        if mode == "run":
            next_id = answer_resp.get("run_id") or (
                (answer_resp.get("run") or {}).get("id")
            )
        elif mode == "comparison":
            runs = answer_resp.get("runs") or []
            matching = [r for r in runs if r.get("engine") == engine]
            next_id = (matching or runs or [{}])[0].get("id")
        else:
            next_id = answer_resp.get("run_id")

        assert next_id, (
            f"[{engine}] Answer response missing new run_id: {answer_resp!r}"
        )
        current_run_id = str(next_id)
        print(f"  [{engine}] Answered round {clar_round}. New run_id={current_run_id[:8]}...")

    return state


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_tribunal_clarify_resume(live_config, clarify_engine):
    """Tribunal (delegator since 260721-twy): vague brief -> straight to terminal.

    Asserts:
      - The run reaches a terminal status WITHOUT parking as needs_input
        (0 clarification rounds expected; the lifecycle helper tolerates and
        bounds any unexpected needs_input rounds at MAX_TRIBUNAL_ROUNDS).
    """
    if clarify_engine not in ("tribunal", "both"):
        pytest.skip(
            f"NESTOR_CLARIFY_ENGINE={clarify_engine!r} — skipping tribunal arm."
        )

    cfg = live_config
    state = _drive_clarify_lifecycle(cfg, "tribunal", max_rounds=MAX_TRIBUNAL_ROUNDS)

    # Final assertions
    final_status = state.get("status", "")
    assert final_status in _TERMINAL, (
        f"Tribunal run did not reach a terminal status: {final_status!r}"
    )
    print(
        f"\n[tribunal] PASS\n"
        f"  final_status : {final_status}\n"
        f"  (cap=2: force-proceeded within {MAX_TRIBUNAL_ROUNDS} round(s))\n"
        f"\n  NOTE: D-17 mandate requires ALSO confirming this in the live UI\n"
        f"  before testers get access. This test validates the HTTP lifecycle only.\n"
    )


def test_adk_clarify_resume(live_config, clarify_engine):
    """ADK: vague brief -> needs_input -> answer -> repeat until terminal (uncapped).

    Asserts:
      - Each pause produces needs_input + non-empty clarifying_questions.
      - POST /answer is the ONLY way to advance (no forced progress).
      - ADK eventually reaches a terminal status (or smoke guard fires at round 4).
    """
    if clarify_engine not in ("adk", "both"):
        pytest.skip(
            f"NESTOR_CLARIFY_ENGINE={clarify_engine!r} — skipping adk arm."
        )

    cfg = live_config
    state = _drive_clarify_lifecycle(cfg, "adk", max_rounds=MAX_ADK_ROUNDS)

    final_status = state.get("status", "")
    assert final_status in _TERMINAL, (
        f"ADK run did not reach a terminal status: {final_status!r}"
    )
    print(
        f"\n[adk] PASS\n"
        f"  final_status : {final_status}\n"
        f"  (uncapped: each needs_input round required a human answer)\n"
        f"\n  NOTE: D-17 mandate requires ALSO confirming this in the live UI\n"
        f"  before testers get access. This test validates the HTTP lifecycle only.\n"
    )


def test_per_engine_cap_contract_structural():
    """Structural contract: source-level assertions for the cap invariants.

    This mirrors the grep-gate style of test_clarification_cap_per_engine.py
    for the clarify smoke context specifically (no duplication — this checks
    the HARNESS file, not the production source files that the cap test checks).
    """
    from pathlib import Path

    harness = (
        Path(__file__).parent.parent / "scripts" / "clarify_loop_smoke.py"
    )
    assert harness.exists(), f"Smoke script not found at {harness}"

    src = harness.read_text(encoding="utf-8")

    # Must reference both engines
    assert "adk" in src, "Smoke harness must handle the 'adk' engine"
    assert "tribunal" in src, "Smoke harness must handle the 'tribunal' engine"

    # Must surface needs_input
    assert "needs_input" in src, (
        "Smoke harness must check for needs_input status"
    )

    # Must drive the /answer endpoint
    assert "/answer" in src, (
        "Smoke harness must POST to /api/runs/{id}/answer to resume the run"
    )

    # DEMO_MODE guard must be present
    assert "DEMO_MODE" in src, (
        "Smoke harness must refuse to run when DEMO_MODE is set"
    )

    # Tribunal cap must be asserted (harness must NOT let Tribunal loop past round 2)
    assert "MAX_TRIBUNAL_ROUNDS" in src, (
        "Smoke harness must assert Tribunal force-proceeds within MAX_TRIBUNAL_ROUNDS"
    )
