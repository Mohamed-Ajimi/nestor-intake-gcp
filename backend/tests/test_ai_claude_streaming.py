"""Quick 261009-ib5 — every Claude skill call STREAMS (fix the AI-review timeouts).

Prod skill_runs 6bd63c35 / b7f44d5a (apply-intake-skill, claude-sonnet-4-5) failed with
``APITimeoutError`` after 543 s / 542 s = 3 attempts x the 180 s client timeout. The call
was non-streaming, so the HTTP response stayed silent until Claude had finished the whole
answer; healthy runs already took 176-180 s. Streaming turns the 180 s into a between-
chunks read timeout instead of a whole-answer limit.

What this suite pins — NO network, NO key, NO database:

| Case                                   | Proves                                                |
|----------------------------------------|-------------------------------------------------------|
| ``helper_returns_final_message``       | ``create_message`` opens ``messages.stream`` once,    |
|                                        | returns ``get_final_message()`` and closes the stream.|
| ``helper_real_sdk_message_shape``      | against the INSTALLED anthropic SDK (MockTransport):  |
|                                        | the request is ``stream: true`` and the result is an  |
|                                        | ``anthropic.types.Message`` with ``.content[0].text``,|
|                                        | ``.stop_reason``, ``.usage.*_tokens``.               |
| ``pre_output_error_is_retried``        | an overload BEFORE any output is retried by the SDK.  |
| ``mid_stream_timeout_not_retried``     | a timeout AFTER output started propagates once — the  |
|                                        | generation is never re-run (billing).                 |
| ``client_timeout_is_per_read``         | the factory keeps the 180 s read timeout and sets no  |
|                                        | whole-request cap.                                    |
| ``no_call_site_uses_create``           | no ``backend/app`` source mentions the non-streaming  |
|                                        | create call; all four skills use the helper.          |

The DB-backed "stream timeout -> skill run failed" case lives in
``test_ai_apply_skill.py::test_apply_skill_stream_timeout_marks_failed``.
"""

from __future__ import annotations

import json
import pathlib

import pytest

anthropic = pytest.importorskip("anthropic")
httpx = pytest.importorskip("httpx")

import app.ai.clients as ai_clients_mod  # noqa: E402

_APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
_SKILL_MODULES = ("apply", "context_pack", "extract_insights", "structure_answers")


# ---------------------------------------------------------------------------
# Helpers — a minimal Anthropic SSE stream served by httpx.MockTransport
# ---------------------------------------------------------------------------


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


def _stream_chunks(text_parts: list[str], *, stop_reason: str = "end_turn") -> list[bytes]:
    chunks = [
        _sse(
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-5",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 11, "output_tokens": 1},
                },
            },
        ),
        _sse(
            "content_block_start",
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        ),
        _sse("ping", {"type": "ping"}),
    ]
    for part in text_parts:
        chunks.append(
            _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": part},
                },
            )
        )
    chunks += [
        _sse("content_block_stop", {"type": "content_block_stop", "index": 0}),
        _sse(
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": stop_reason, "stop_sequence": None},
                "usage": {"output_tokens": 7},
            },
        ),
        _sse("message_stop", {"type": "message_stop"}),
    ]
    return chunks


class _ChunkStream(httpx.SyncByteStream):
    """Yields SSE chunks; optionally raises a read timeout after ``fail_after`` chunks."""

    def __init__(self, chunks: list[bytes], fail_after: int | None = None) -> None:
        self._chunks = chunks
        self._fail_after = fail_after

    def __iter__(self):
        for i, chunk in enumerate(self._chunks):
            if self._fail_after is not None and i == self._fail_after:
                raise httpx.ReadTimeout("The read operation timed out")
            yield chunk


def _sse_response(chunks: list[bytes], fail_after: int | None = None) -> "httpx.Response":
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=_ChunkStream(chunks, fail_after),
    )


def _install_transport(monkeypatch, handler) -> None:
    """Route the REAL ``anthropic_client()`` factory through a MockTransport.

    The factory itself runs (key read at call time, its timeout / retry settings kept);
    only the HTTP transport is swapped via the SDK's own ``with_options``.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    real_factory = ai_clients_mod.anthropic_client

    def _factory():
        return real_factory().with_options(
            http_client=httpx.Client(transport=httpx.MockTransport(handler))
        )

    monkeypatch.setattr(ai_clients_mod, "anthropic_client", _factory)


_KW = dict(
    model="claude-sonnet-4-5",
    max_tokens=20000,
    system="sys",
    messages=[{"role": "user", "content": "hi"}],
)


# ---------------------------------------------------------------------------
# (a) the helper returns the final message from a stream
# ---------------------------------------------------------------------------


def test_create_message_returns_final_message_from_stream(monkeypatch, fake_anthropic):
    fake = fake_anthropic('{"ok": true}', input_tokens=5, output_tokens=9)
    monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: fake)

    message = ai_clients_mod.create_message(**_KW)

    assert len(fake.calls) == 1, f"expected exactly one stream, got {len(fake.calls)}."
    assert fake.calls[0] == _KW, "the request kwargs must pass through unchanged."
    assert message is fake.streams[0].final_message, "must return get_final_message()."
    assert message.content[0].text == '{"ok": true}'
    assert (message.usage.input_tokens, message.usage.output_tokens) == (5, 9)
    assert fake.streams[0].closed, "the stream context must be exited (connection released)."


def test_create_message_real_sdk_returns_message_shape(monkeypatch):
    seen: list[dict] = []

    def handler(request: "httpx.Request") -> "httpx.Response":
        seen.append(json.loads(request.content))
        return _sse_response(_stream_chunks(['{"decision', '_or_goal": null}']))

    _install_transport(monkeypatch, handler)

    message = ai_clients_mod.create_message(**_KW)

    assert len(seen) == 1
    assert seen[0]["stream"] is True, "the Claude call must be a streaming request."
    assert seen[0]["max_tokens"] == 20000 and seen[0]["model"] == "claude-sonnet-4-5"
    assert isinstance(message, anthropic.types.Message), (
        f"helper must return the SDK Message type, got {type(message)!r}."
    )
    assert message.content[0].text == '{"decision_or_goal": null}'
    assert message.stop_reason == "end_turn"
    assert message.usage.input_tokens == 11
    assert message.usage.output_tokens == 7


def test_create_message_real_sdk_surfaces_max_tokens_stop_reason(monkeypatch):
    """The D-4 truncation guard keys off ``stop_reason``; the stream must carry it."""

    def handler(request: "httpx.Request") -> "httpx.Response":
        return _sse_response(_stream_chunks(['{"cut'], stop_reason="max_tokens"))

    _install_transport(monkeypatch, handler)

    message = ai_clients_mod.create_message(**_KW)
    assert message.stop_reason == "max_tokens"


# ---------------------------------------------------------------------------
# Retry semantics — SDK retries only before output; never re-runs a generation
# ---------------------------------------------------------------------------


def test_pre_output_overload_is_retried_by_sdk(monkeypatch):
    attempts: list[int] = []

    def handler(request: "httpx.Request") -> "httpx.Response":
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(
                529,
                headers={"retry-after-ms": "1"},
                json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}},
            )
        return _sse_response(_stream_chunks(["{}"]))

    _install_transport(monkeypatch, handler)

    message = ai_clients_mod.create_message(**_KW)
    assert len(attempts) == 2, "an error before any output must be retried by the SDK."
    assert message.content[0].text == "{}"


def test_mid_stream_timeout_is_not_retried(monkeypatch):
    attempts: list[int] = []

    def handler(request: "httpx.Request") -> "httpx.Response":
        attempts.append(1)
        # message_start + content_block_start + ping + one delta, then the read times out.
        return _sse_response(_stream_chunks(["{\"a\":", " 1}"]), fail_after=4)

    _install_transport(monkeypatch, handler)

    with pytest.raises((httpx.TimeoutException, anthropic.APITimeoutError)):
        ai_clients_mod.create_message(**_KW)
    assert len(attempts) == 1, (
        "a timeout after output started must NOT re-run the (billed) generation; "
        f"saw {len(attempts)} requests."
    )


# ---------------------------------------------------------------------------
# Timeout configuration — per-read, no whole-request cap
# ---------------------------------------------------------------------------


def test_anthropic_client_timeout_is_per_read_with_no_total_cap(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")
    client = ai_clients_mod.anthropic_client()

    timeout = httpx.Timeout(client.timeout)
    assert timeout.read == 180.0, f"read (between-chunks) timeout must stay 180 s, got {timeout!r}."
    # httpx has no whole-request timeout; the only way a total cap could appear is a
    # non-httpx deadline. Pin the shape: connect/read/write/pool, nothing else.
    assert set(timeout.as_dict()) == {"connect", "read", "write", "pool"}
    assert client.max_retries == anthropic.DEFAULT_MAX_RETRIES == 2


# ---------------------------------------------------------------------------
# (c) no call site uses the non-streaming create call anymore
# ---------------------------------------------------------------------------


def test_no_app_source_uses_messages_create():
    offenders = [
        f"{path.relative_to(_APP_DIR.parent)}:{lineno}"
        for path in sorted(_APP_DIR.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "messages." + "create" in line
    ]
    assert offenders == [], f"non-streaming Claude call(s) still present: {offenders}"


@pytest.mark.parametrize("module", _SKILL_MODULES)
def test_every_claude_skill_uses_the_streaming_helper(module):
    source = (_APP_DIR / "ai" / "skills" / f"{module}.py").read_text(encoding="utf-8")
    assert "clients.create_message(" in source, (
        f"app/ai/skills/{module}.py must call Claude through clients.create_message."
    )
