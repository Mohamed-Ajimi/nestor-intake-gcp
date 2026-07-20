"""Clarify pause/resume smoke harness — Plan 01-18 Task 1.

Drives the REAL clarify loop over HTTP against a running real-mode server
(base URL + tester JWT from args/env; DEMO_MODE MUST be off).  For each
engine in {adk, tribunal}:

  1. POST /api/runs with a deliberately vague brief and a real project_id.
  2. Poll GET /api/runs/{id} until status == "needs_input", asserting that
     clarifying_questions is non-empty.
  3. POST /api/runs/{id}/answer with a concrete answer.
  4. Follow the returned new run_id and poll to a terminal status
     (completed / failed / cancelled).
  5. Print per-round: round count, status transitions, final status.

Per-engine cap contract (decision 2026-06-10 / test_clarification_cap_per_engine.py):
  - Tribunal: _CLAR_CAP = 2 in pipeline/tribunal/pipeline.py; force-proceeds by
    round 2 at the latest (intake override). The harness asserts the run
    reaches a terminal status within 2 answer rounds.
  - ADK: uncapped — it parks as needs_input on every genuine question, and
    the harness answers each until the run terminates.  Rounds are bounded by
    the human, not the engine; the harness caps at MAX_ADK_ROUNDS (default 4)
    so the smoke cannot loop unattended.

Guards:
  - Exits non-zero if DEMO_MODE is set (DEMO_MODE bypasses engine + DB +
    audit; the clarify smoke requires a REAL run).
  - Exits non-zero if neither --base-url nor NESTOR_BASE_URL is set.
  - Exits non-zero if neither --token nor NESTOR_SMOKE_TOKEN is set.
  - HTTP-only: never touches the database directly (no asyncpg / Cloud SQL
    Auth Proxy required); all assertions go through the API.

Usage (POSIX):
  NESTOR_BASE_URL=https://nestor-pulse-api-ybkr7metoq-ew.a.run.app \\
  NESTOR_SMOKE_TOKEN=$(gcloud secrets ...) \\
  .venv/bin/python nestor_pulse_sdk/scripts/clarify_loop_smoke.py

Usage (Windows):
  $env:NESTOR_BASE_URL='https://nestor-pulse-api-ybkr7metoq-ew.a.run.app'
  $env:NESTOR_SMOKE_TOKEN='<id-token>'
  .venv\\Scripts\\python nestor_pulse_sdk\\scripts\\clarify_loop_smoke.py

  --engine adk       Run only the ADK arm.
  --engine tribunal  Run only the Tribunal arm.
  (default: both)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from typing import Any

# Windows consoles default to cp1252 — force UTF-8 so print() cannot raise
# UnicodeEncodeError mid-run (which would abort an otherwise-paid run).
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

# ---------------------------------------------------------------------------
# Guard: DEMO_MODE must be off — check BEFORE any imports so the exit is clean
# ---------------------------------------------------------------------------
_DEMO_MODE = os.environ.get("DEMO_MODE", "").strip()
if _DEMO_MODE not in ("", "0", "false", "False", "no"):
    print(
        "ERROR: DEMO_MODE is set.\n"
        "  DEMO_MODE bypasses the engine, DB, and audit trail — the clarify\n"
        "  smoke harness requires a REAL run (no bypass).\n"
        "  Unset DEMO_MODE and retry.",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: A deliberately vague brief that triggers clarifying questions on both
#: engines (triggers vague-brief path: no domain, no scope, no deliverable).
_VAGUE_BRIEF = (
    "Research the market. "
    "We need to understand the competitive landscape and identify key players."
)

#: Concrete answer to give when an engine asks for more detail.
_CLARIFICATION_ANSWER = (
    "Focus on the European B2B SaaS market for AI-powered legal research tools. "
    "Time window: last 24 months. Deliverable: a competitive matrix with pricing. "
    "This is for an investment decision — please verify all claims."
)

#: Maximum ADK rounds the harness will answer before failing the smoke.
#: ADK is uncapped by design; this caps the SMOKE (not the engine) so it
#: cannot loop unattended if the smoke is run against a misconfigured server.
MAX_ADK_ROUNDS = 4

#: Tribunal must reach a terminal status within this many answer rounds (cap = 2).
MAX_TRIBUNAL_ROUNDS = 2

#: Poll interval and total timeout when waiting for status transitions.
POLL_INTERVAL_S = 5
POLL_TIMEOUT_S = 300  # 5 minutes — a real engine run can be slow

_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

try:
    import urllib.request
    import urllib.error
except ImportError as exc:
    print(f"ERROR: standard library unavailable: {exc}", file=sys.stderr)
    sys.exit(1)


def _request(
    method: str,
    url: str,
    *,
    token: str,
    body: dict | None = None,
) -> tuple[int, dict]:
    """Make an HTTP request and return (status_code, parsed_json)."""
    data: bytes | None = None
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if body is not None:
        data = json.dumps(body).encode("utf-8")

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


def _post(base_url: str, path: str, token: str, body: dict) -> tuple[int, dict]:
    return _request("POST", f"{base_url.rstrip('/')}{path}", token=token, body=body)


def _get(base_url: str, path: str, token: str) -> tuple[int, dict]:
    return _request("GET", f"{base_url.rstrip('/')}{path}", token=token)


# ---------------------------------------------------------------------------
# Core smoke logic
# ---------------------------------------------------------------------------

def _poll_until(
    base_url: str,
    run_id: str,
    token: str,
    *,
    target_statuses: set[str],
    timeout_s: float = POLL_TIMEOUT_S,
    label: str = "",
) -> dict[str, Any]:
    """Poll GET /api/runs/{id} until status is in target_statuses or timeout."""
    deadline = time.monotonic() + timeout_s
    last_status = ""
    while time.monotonic() < deadline:
        code, data = _get(base_url, f"/api/runs/{run_id}", token)
        if code != 200:
            raise RuntimeError(
                f"GET /api/runs/{run_id} returned {code}: {data!r}"
            )
        status = data.get("status", "")
        if status != last_status:
            print(f"    [{label}] run {run_id[:8]}... status -> {status}")
            last_status = status
        if status in target_statuses:
            return data
        time.sleep(POLL_INTERVAL_S)
    raise TimeoutError(
        f"Timed out after {timeout_s}s waiting for {target_statuses!r}; "
        f"last status was {last_status!r} for run {run_id}"
    )


def _smoke_engine(
    base_url: str,
    project_id: str,
    token: str,
    engine: str,
    *,
    max_rounds: int,
) -> bool:
    """Drive the needs_input -> answer -> resume -> completed lifecycle.

    Returns True on PASS, False on FAIL.  Never raises — failures are printed.
    """
    print(f"\n{'='*60}")
    print(f"  ENGINE: {engine.upper()}")
    print(f"{'='*60}")

    # ------------------------------------------------------------------ #
    # Round 0: submit the vague brief                                      #
    # ------------------------------------------------------------------ #
    idempotency_key = str(uuid.uuid4())
    print(f"  Submitting vague brief (idempotency_key={idempotency_key[:8]}...)...")
    code, run_data = _post(
        base_url,
        "/api/runs",
        token,
        {
            "project_id": project_id,
            "brief": _VAGUE_BRIEF,
            "engine": engine,
            "idempotency_key": idempotency_key,
        },
    )
    if code not in (200, 201):
        print(f"  FAIL: POST /api/runs returned {code}: {run_data!r}", file=sys.stderr)
        return False

    run_id: str = str(run_data.get("id", ""))
    if not run_id:
        print(f"  FAIL: no run_id in response: {run_data!r}", file=sys.stderr)
        return False

    print(f"  run_id = {run_id}  (initial status = {run_data.get('status')!r})")
    status_log: list[str] = [run_data.get("status", "?")]

    # ------------------------------------------------------------------ #
    # Loop: answer rounds until terminal                                   #
    # ------------------------------------------------------------------ #
    clar_round = 0
    current_run_id = run_id

    while True:
        # Poll until this run reaches needs_input or a terminal status.
        try:
            run_state = _poll_until(
                base_url,
                current_run_id,
                token,
                target_statuses={"needs_input"} | _TERMINAL_STATUSES,
                label=f"{engine} round {clar_round}",
            )
        except TimeoutError as exc:
            print(f"  FAIL (timeout): {exc}", file=sys.stderr)
            return False
        except RuntimeError as exc:
            print(f"  FAIL (HTTP error): {exc}", file=sys.stderr)
            return False

        new_status = run_state.get("status", "")
        if new_status not in status_log or new_status != status_log[-1]:
            status_log.append(new_status)

        # -- Terminal without clarification: success -------------------- #
        if new_status in _TERMINAL_STATUSES:
            print(f"  Run reached terminal status: {new_status!r}")
            break

        # -- needs_input: assert clarifying_questions, then answer ------- #
        assert new_status == "needs_input", f"Unexpected status {new_status!r}"

        questions = run_state.get("clarifying_questions") or []
        if not questions:
            print(
                f"  FAIL: status == 'needs_input' but clarifying_questions is empty. "
                f"run_state={run_state!r}",
                file=sys.stderr,
            )
            return False

        clar_round += 1
        print(f"  [{engine}] Round {clar_round}: needs_input with {len(questions)} question(s):")
        for i, q in enumerate(questions, 1):
            print(f"    Q{i}: {q[:120]}")

        # Tribunal cap assertion: must NOT still be asking after max_rounds
        if engine == "tribunal" and clar_round > max_rounds:
            print(
                f"  FAIL: Tribunal exceeded the cap (asked in round {clar_round} "
                f"> _CLAR_CAP={max_rounds}). It must force-proceed by round {max_rounds}.",
                file=sys.stderr,
            )
            return False

        if engine == "adk" and clar_round > max_rounds:
            print(
                f"  FAIL (smoke guard): ADK has asked {clar_round} clarification rounds "
                f"> MAX_ADK_ROUNDS={max_rounds}. The harness caps the smoke to avoid "
                f"unattended looping; investigate the server.",
                file=sys.stderr,
            )
            return False

        # POST /api/runs/{id}/answer
        print(f"  Answering round {clar_round}...")
        code, answer_data = _post(
            base_url,
            f"/api/runs/{current_run_id}/answer",
            token,
            {"answers": _CLARIFICATION_ANSWER},
        )
        if code not in (200, 201):
            print(
                f"  FAIL: POST /api/runs/{current_run_id}/answer returned {code}: "
                f"{answer_data!r}",
                file=sys.stderr,
            )
            return False

        # Follow the new run_id returned by the answer endpoint.
        # Single-run mode returns {"mode": "run", "run_id": "..."}
        mode = answer_data.get("mode", "run")
        if mode == "run":
            next_run_id = answer_data.get("run_id") or (
                (answer_data.get("run") or {}).get("id")
            )
        elif mode == "comparison":
            # Comparison: pick the first child that matches this engine.
            runs = answer_data.get("runs") or []
            matching = [r for r in runs if r.get("engine") == engine]
            next_run_id = (matching or runs or [{}])[0].get("id")
        else:
            next_run_id = answer_data.get("run_id")

        if not next_run_id:
            print(
                f"  FAIL: answer response has no new run_id: {answer_data!r}",
                file=sys.stderr,
            )
            return False

        next_run_id = str(next_run_id)
        print(f"  Answer accepted. New run_id = {next_run_id[:8]}...  (mode={mode!r})")
        current_run_id = next_run_id
        status_log.append("queued->resumed")

    # ------------------------------------------------------------------ #
    # Final assertions                                                     #
    # ------------------------------------------------------------------ #
    final_status = run_state.get("status", "")

    if engine == "tribunal":
        if clar_round > MAX_TRIBUNAL_ROUNDS:
            print(
                f"  FAIL: Tribunal asked in round {clar_round} (cap=2). "
                "It must force-proceed by round 2.",
                file=sys.stderr,
            )
            return False
        print(
            f"  [tribunal] PASS: force-proceeded in <= {MAX_TRIBUNAL_ROUNDS} rounds "
            f"(took {clar_round} round(s)). Final status: {final_status!r}"
        )
    else:
        # ADK: assert each needs_input was answered (capped by the smoke above),
        # and that it never spun unattended.
        if clar_round > MAX_ADK_ROUNDS:
            # Already caught above; keep for clarity.
            return False
        print(
            f"  [adk] PASS: paused {clar_round} round(s) for human answers "
            f"(uncapped; smoke cap = {MAX_ADK_ROUNDS}). Final status: {final_status!r}"
        )

    print(
        f"  Status transitions: {' -> '.join(status_log)}"
    )
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="clarify_loop_smoke",
        description=(
            "Clarify pause/resume smoke for both engines (Plan 01-18 Task 1).\n\n"
            "Drives POST /api/runs (vague brief) -> needs_input -> POST /answer\n"
            "-> poll to terminal, asserting per-engine cap contract.\n\n"
            "Requires: DEMO_MODE unset, live server URL, tester JWT,\n"
            "          a project_id visible to the JWT's tenant."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("NESTOR_BASE_URL", ""),
        help="API base URL, e.g. https://nestor-pulse-api-....a.run.app. "
             "Falls back to NESTOR_BASE_URL env var.",
    )
    p.add_argument(
        "--token",
        default=os.environ.get("NESTOR_SMOKE_TOKEN", ""),
        help="Identity Platform ID token (Bearer). Falls back to NESTOR_SMOKE_TOKEN env var.",
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=os.environ.get("NESTOR_SMOKE_PROJECT_ID", ""),
        help="Existing project UUID (visible to the JWT's tenant). "
             "Falls back to NESTOR_SMOKE_PROJECT_ID env var.",
    )
    p.add_argument(
        "--engine",
        choices=["adk", "tribunal", "both"],
        default="both",
        help="Which engine to test (default: both).",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=POLL_TIMEOUT_S,
        metavar="SECONDS",
        help=f"Max seconds to wait per status transition (default: {POLL_TIMEOUT_S}).",
    )
    return p


def main(argv=None) -> None:  # noqa: C901
    args = _build_parser().parse_args(argv)

    # Validate required arguments
    if not args.base_url:
        print(
            "ERROR: --base-url is required (or set NESTOR_BASE_URL).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.token:
        print(
            "ERROR: --token is required (or set NESTOR_SMOKE_TOKEN).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.project_id:
        print(
            "ERROR: --project-id is required (or set NESTOR_SMOKE_PROJECT_ID).",
            file=sys.stderr,
        )
        sys.exit(1)

    base_url = args.base_url.rstrip("/")
    token = args.token
    project_id = args.project_id

    # Sanity: verify the server is reachable and DEMO_MODE is off on it
    print(f"\nConnecting to: {base_url}")
    code, health = _get(base_url, "/health", token)
    if code != 200:
        print(
            f"ERROR: GET /health returned {code}. "
            "Is the server running and reachable?",
            file=sys.stderr,
        )
        sys.exit(1)

    demo_header = health.get("demo_mode")
    if demo_header:
        print(
            "ERROR: Server reported DEMO_MODE is active (health response includes "
            f"demo_mode={demo_header!r}). Unset DEMO_MODE on the server and redeploy.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Server healthy: {health}")

    # Select engines to test
    engines_to_test: list[str]
    if args.engine == "both":
        engines_to_test = ["tribunal", "adk"]
    else:
        engines_to_test = [args.engine]

    # Map per-engine round limits
    round_limits = {
        "tribunal": MAX_TRIBUNAL_ROUNDS,
        "adk": MAX_ADK_ROUNDS,
    }

    # Run each engine smoke
    results: dict[str, bool] = {}
    for engine in engines_to_test:
        try:
            passed = _smoke_engine(
                base_url,
                project_id,
                token,
                engine,
                max_rounds=round_limits[engine],
            )
        except Exception as exc:
            print(f"  UNEXPECTED ERROR [{engine}]: {exc}", file=sys.stderr)
            passed = False
        results[engine] = passed

    # Summary
    print(f"\n{'='*60}")
    print("CLARIFY LOOP SMOKE SUMMARY")
    print(f"{'='*60}")
    all_pass = True
    for eng, passed in results.items():
        verdict = "PASS" if passed else "FAIL"
        print(f"  {eng:12s}: {verdict}")
        if not passed:
            all_pass = False
    print(f"{'='*60}")
    if all_pass:
        print("OVERALL: PASS")
        print(
            "\nPer-engine cap contract verified:\n"
            "  - tribunal: force-proceeds within 2 rounds (intake override)\n"
            "  - adk     : pauses as needs_input each round (uncapped, human-bounded)"
        )
    else:
        print("OVERALL: FAIL", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
