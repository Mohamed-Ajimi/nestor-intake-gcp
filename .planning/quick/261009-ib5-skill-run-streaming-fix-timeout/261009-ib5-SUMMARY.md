---
quick_id: 261009-ib5
type: quick
subsystem: backend/app/ai (Claude skill transport)
tags: [anthropic, streaming, timeout, skill_runs, D-09]
key-files:
  created:
    - backend/tests/test_ai_claude_streaming.py
  modified:
    - backend/app/ai/clients.py
    - backend/app/ai/skills/apply.py
    - backend/app/ai/skills/context_pack.py
    - backend/app/ai/skills/extract_insights.py
    - backend/app/ai/skills/structure_answers.py
    - backend/tests/conftest.py
    - backend/tests/test_ai_apply_skill.py
decisions:
  - Every Claude skill call goes through one helper, clients.create_message, which runs messages.stream(**kw) and returns get_final_message()
  - The 180 s Anthropic client timeout stays; on a stream it limits the silence between chunks, not the whole answer. No total cap is set.
  - Retries are left to the SDK (default max_retries=2), which only retries before the response starts. Nothing in the app re-runs a whole generation after a timeout.
  - _APPLY_MAX_TOKENS left at 20000. Raising it is a separate decision because it costs money.
commits:
  - 6f83aab test(261009-ib5) RED
  - cbd7410 feat(261009-ib5) GREEN
completed: 2026-10-09
---

# Quick 261009-ib5: Claude skill calls now stream, which fixes the AI-review timeouts

**What changed:** the four Claude skills (apply, context_pack, extract_insights, structure_answers) all call one new helper, `clients.create_message`. It uses `messages.stream(...)` and returns `get_final_message()`. Before, a single silent non-streaming request had to finish within 180 s. Now the 180 s only limits the gap between two chunks, so a long but healthy generation (prod apply runs already take 176–180 s) no longer dies with `APITimeoutError` after 3 × 180 s.

## What was done

- `backend/app/ai/clients.py`: added `create_message(**kwargs) -> anthropic.types.Message`. It gets the client from `anthropic_client()` each time it is called, so the key is still read per call (D-07) and the test monkeypatch seam still works. A `with` block closes the stream on success and on error. Comments document the timeout and retry behaviour.
- The four skill modules: `clients.anthropic_client().messages.create(` was replaced by `clients.create_message(`. The arguments are unchanged, and so is the parsing, cost and truncation logic.
- `apply.py`: rewrote the comment block about the "~21333 non-streaming ceiling". Removed the now-unused `_ANTHROPIC_NON_STREAMING_MAX_TOKENS` constant. The truncation error text no longer says "switch to streaming"; it still names the 20000 budget, which the test asserts. `_APPLY_MAX_TOKENS = 20000` is unchanged.
- `grep -rn "messages.create" backend/app --include=*.py` now returns **0** matches. Comments are included in that count, and a test enforces it.

## SDK verification (installed anthropic==0.113.0, matching the pyproject pin)

- **The API exists and returns the same type.** `Messages.stream(...)` (resources/messages/messages.py:1085) returns a `MessageStreamManager`. `MessageStream.get_final_message()` (lib/streaming/_messages.py:89) returns a `ParsedMessage`, whose base classes are `ParsedMessage -> Message -> BaseModel` (checked at runtime). The tests confirm that `isinstance(result, anthropic.types.Message)` holds and that `.content[0].text`, `.stop_reason` (including `"max_tokens"`) and `.usage.input_tokens/.output_tokens` are filled in. These tests send a mock SSE stream through the real SDK using `httpx.MockTransport`.
- **Timeouts:** the client is built with `timeout=180.0`, which becomes `httpx.Timeout(180)`: connect, read, write and pool are each 180 s, and httpx has no total timeout. `stream()` does not use the SDK's non-streaming timeout calculation. With `stream=True`, the read timeout applies to each socket read, so it measures the silence between SSE chunks. The API also sends `ping` events during generation.
  - Side finding: in `create()` (messages.py:1030), the non-streaming timeout and token-ceiling check (`_calculate_nonstreaming_timeout`) only runs when the client timeout is the SDK default. Our client sets 180 s, so the "~21333 ceiling" in the old apply.py comment never actually applied to this code. The real limit was the 180 s read timeout on a silent response.
- **Retries** (`_base_client.py` ~1130–1190 and `_should_retry`):
  - The SDK retry loop wraps only `_attempt_request`, which for a stream returns as soon as the response headers arrive. So connection errors, timeouts before the response starts, and status codes 408, 409, 429, 5xx and 529 are retried, up to `max_retries=2`. All of these happen before any output exists.
  - After a 200, the body is read inside `get_final_message()`, outside that loop. A read timeout mid-stream comes out as a **raw `httpx.ReadTimeout`** ("The read operation timed out"), not wrapped as `APITimeoutError`. A mid-stream SSE `error` event raises `APIStatusError`. Neither is retried.
  - Each skill's `on_error` (D-09) catches any `Exception`, so the run ends `failed` with that message.
  - Tests cover both cases: a 529 before output is retried (2 requests), and a timeout after output started is raised once (1 request).

## Tests (TDD)

- **RED (6f83aab).** The `fake_anthropic` fixture now has a `messages.stream` that returns a context-manager stream (with `final_message` and `closed`), and **no `create`**. A regression to the non-streaming call would therefore finalize `failed` and turn the success assertions red. The truncation test now marks the stream's final message as `max_tokens`. New cases:
  - `test_ai_claude_streaming.py`: 11 tests. They check that the helper returns the final message and closes the stream, the real-SDK `stream:true` request and Message shape, the real-SDK `max_tokens` stop_reason, the SDK retry before output, that a mid-stream timeout is not retried, the timeout configuration (read=180, no total, max_retries=2), the "no `messages.create` in app/" guard, and that all four skills use the helper.
  - `test_ai_apply_skill.py::test_apply_skill_stream_timeout_marks_failed` (DB-backed): a stream that raises `httpx.ReadTimeout` leaves the run `failed` with the timeout message in `error_message` and `output_parsed` NULL. The stream is opened once and closed.
  - RED run: 13 failed and 2 passed. The two passes were the timeout-configuration test, which pins existing behaviour, and the pre-existing bad-JSON test.
- **GREEN (cbd7410).** The AI suites (streaming, apply, context_pack, context_pack_cas, structure_extract, router_gate, status_contract, session_release, cross_tenant) gave **70 passed**.
- **Full backend suite** (Docker up, testcontainers): **996 passed, 2 skipped**, 0 failed, in 203 s. The 2 skips have nothing to do with this change: `test_tribunal_seam_denial.py:70` needs `nestor_pulse_sdk`, which is not on the backend path, and `test_research_runs_migration.py:382` only runs when `RUNTIME_DB_USER` is set. A second full run gave the same result. This run includes 12 new tests.

## Cherry-pick onto prod base c26107a

The only commits touching these files between `c26107a..HEAD` are the two from this task. I simulated the cherry-pick with `git merge-tree --write-tree` (6f83aab, then cbd7410 on top of c26107a): **both apply without conflicts**, and the resulting `clients.py`, `apply.py`, `conftest.py` and `test_ai_apply_skill.py` are byte-identical to HEAD. A real worktree checkout of c26107a failed on Windows path length (`.planning/...` files), so it was removed; no tests were run on the c26107a tree itself. `intake_routes.py` and all files outside `backend/app/ai` and `backend/tests` were not touched.

## Deviations from Plan

- **[Rule 1, stale message]** The apply truncation error text told operators that raising the budget "requires switching to a streaming call — the non-streaming SDK ceiling is ~21333". That is no longer true, so I rewrote it to point at `_APPLY_MAX_TOKENS`. The test still requires the message to name the budget (`20000`). The now-unused `_ANTHROPIC_NON_STREAMING_MAX_TOKENS` constant was removed. Commit cbd7410.
- **Not wrapped:** a mid-stream timeout surfaces as `httpx.ReadTimeout`, not `anthropic.APITimeoutError`. I left it as is. `on_error` catches it either way and the recorded message is clear ("The read operation timed out"). Note that the prod error text therefore changes from "Request timed out or interrupted..." to this one if a stream ever stalls for 180 s.

## Not done / notes

- No deploy, no push, no gcloud. Docs were not committed (per instructions); this SUMMARY is uncommitted.
- STATE.md and ROADMAP.md were not updated; that is left to the orchestrator for this quick task.
- Not observed live: no real Claude call was made. The streaming path has only been exercised against the installed SDK through MockTransport.

## Self-Check: PASSED
- FOUND: backend/tests/test_ai_claude_streaming.py
- FOUND: 6f83aab, cbd7410 in `git log`
- `grep messages.create backend/app` (*.py): 0
