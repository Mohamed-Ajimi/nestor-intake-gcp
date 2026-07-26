"""Hand-written duck-typed fakes for the question-workshop tests (plan 15.2-10).

THIS MODULE MAKES ZERO LLM CALLS, OPENS NO DATABASE, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. It is a stand-in for the MODEL only: everything between a
`workshop.*` entry point and this object — the loop, the pause branch, the retry
policy, the prompt rendering, the sentinel parser, the PARENT stamping, the
clusterer reuse, the feed writes — is production code doing its real job. The
template is `test_gate_replay.py::_AnswerKeyGateAudited`, including its HONESTY
RULE: an unmatched or exhausted script entry is RECORDED in `self.unscripted`
rather than silently defaulted, because a silent default would move the result and
read as a production bug instead of a fixture-drift bug.

It has no `test_` prefix, so pytest does not collect it as a test module (the same
shape as `tests/fixtures/run_4cbb5311/loader.py`).

Nothing here is marked `live`, nothing can flake on the network, and nothing spends
— which matters twice over while the Anthropic account sits at its monthly cap
(resets 2026-08-01).

Plan 15.2-11 IMPORTS this module rather than re-writing these fakes.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Optional, Sequence

__all__ = [
    "FakeTextResponse",
    "FakeToolUseResponse",
    "ScriptedWorkshopAudited",
    "search_result_block",
    "text_block",
]


# ---------------------------------------------------------------------------
# Response shapes
# ---------------------------------------------------------------------------


def text_block(text: str) -> dict[str, Any]:
    """An Anthropic-shaped `text` content block."""
    return {"type": "text", "text": text}


def search_result_block(*urls: str) -> dict[str, Any]:
    """A `web_search_tool_result` block carrying `urls`.

    Gives `skeptic._collect_citation_urls` something real to find, and gives the
    loop a legitimate reason to append an assistant turn — which is what makes
    "never append a synthetic tool_result" an assertable property rather than a
    vacuous one.
    """
    return {
        "type": "web_search_tool_result",
        "tool_use_id": "srvtoolu_fake",
        "content": [
            {"type": "web_search_result", "url": url, "title": url} for url in urls
        ],
    }


class FakeTextResponse:
    """A plain text completion.

    Carries BOTH shapes on purpose: `.text` (what the Gemini readers in
    `grouping._cluster_block` look at) and `.content` as a one-element list of
    Anthropic-shaped text blocks (what `intake._intake_once`'s extractor and this
    phase's candidate reader look at). One class therefore serves both providers.
    """

    def __init__(self, text: str = "", *, stop_reason: str = "end_turn") -> None:
        self.text = text
        self.stop_reason = stop_reason
        self.content: list[dict[str, Any]] = [text_block(text)] if text else []


class FakeToolUseResponse:
    """A tool-use turn: optional server-tool blocks plus an optional client tool.

    `name=None` emits NO client tool block — that is how a test drives the
    "server tools were used, go round again" branch and the forced-final-turn
    branch without ever producing an `emit_orientation`.
    """

    def __init__(
        self,
        name: Optional[str],
        input_dict: Any = None,
        *,
        stop_reason: str = "tool_use",
        extra_blocks: Sequence[dict[str, Any]] = (),
    ) -> None:
        self.stop_reason = stop_reason
        self.text = ""
        blocks: list[dict[str, Any]] = [dict(b) for b in extra_blocks]
        if name is not None:
            blocks.append(
                {
                    "type": "tool_use",
                    "id": f"toolu_{name}",
                    "name": name,
                    "input": input_dict if input_dict is not None else {},
                }
            )
        self.content = blocks


# ---------------------------------------------------------------------------
# The scripted audited client
# ---------------------------------------------------------------------------


class ScriptedWorkshopAudited:
    """A duck-typed `AuditedLLMClient` that answers from a caller-supplied script.

    Scripts may be either:
      * a LIST — responses are served in order (FIFO); when it runs dry the last
        entry is reused and the exhaustion is recorded in `self.unscripted`;
      * a DICT keyed by a discriminator SUBSTRING the caller nominates — the first
        key found in the rendered prompt text wins, and a `""` key (or the absence
        of any match) falls back to round-robin over the dict's `None` entry.

    `audit_out` is populated with a DETERMINISTIC `audit_id` (``aud-0001``,
    ``aud-0002``, …) and a fixed `cost_usd`, so feed-row assertions are exact rather
    than approximate.
    """

    #: The per-call cost the fake reports. A fixed, exact cent string (never a
    #: float) because `StageDetailItem.cost_usd` is `str | None`.
    COST_USD = "0.0100"

    def __init__(
        self,
        *,
        anthropic_script: Any = None,
        gemini_script: Any = None,
        raise_on_call: Any = None,
    ) -> None:
        self._anthropic_script = anthropic_script
        self._gemini_script = gemini_script
        #: An Exception INSTANCE raised on every call, or a callable
        #: ``(kind, call_index, prompt) -> Exception | None``. Drives the
        #: never-raise paths without a mocking library.
        self._raise_on_call = raise_on_call

        self.anthropic_calls: list[dict[str, Any]] = []
        self.gemini_calls: list[dict[str, Any]] = []
        self.models: list[str] = []
        #: Script misses and exhaustions. Recorded, never silently defaulted.
        self.unscripted: list[str] = []
        self._audit_seq = 0
        self._anthropic_cursor = 0
        self._gemini_cursor = 0

    # -- introspection ------------------------------------------------------

    @property
    def call_count(self) -> int:
        return len(self.anthropic_calls) + len(self.gemini_calls)

    @property
    def last_anthropic(self) -> dict[str, Any]:
        assert self.anthropic_calls, "the fake recorded no anthropic call"
        return self.anthropic_calls[-1]

    def anthropic_prompts(self) -> list[str]:
        return [call["prompt_text"] for call in self.anthropic_calls]

    # -- the two provider surfaces -----------------------------------------

    async def anthropic_messages(
        self,
        *,
        run_id,
        tenant_id,
        model: str,
        audit_out: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ):
        # `audit_out` is an EXPLICIT keyword-only parameter ahead of **kwargs
        # precisely so it never reaches the provider payload, where an unknown key
        # is an HTTP 400. Pinned here so a regression in the real client's signature
        # shows up as a test failure and not as a live 400.
        assert "audit_out" not in kwargs, (
            "audit_out leaked into the provider kwargs — it must stay an explicit "
            "keyword-only parameter, never part of the forwarded payload"
        )
        prompt_text = _anthropic_prompt_text(kwargs)
        self.models.append(model)
        self.anthropic_calls.append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "model": model,
                # Deep-copied: the loop MUTATES its messages list, so a shallow
                # reference would let later turns leak into an earlier recorded
                # "snapshot" and make the assertions lie.
                "messages": copy.deepcopy(kwargs.get("messages")),
                "tools": copy.deepcopy(kwargs.get("tools")),
                "tool_choice": copy.deepcopy(kwargs.get("tool_choice")),
                "system": kwargs.get("system"),
                "max_tokens": kwargs.get("max_tokens"),
                "prompt_text": prompt_text,
            }
        )

        self._maybe_raise("anthropic", len(self.anthropic_calls), prompt_text)
        self._fill_audit_out(audit_out, provider="anthropic", model=model)

        response = self._serve(
            self._anthropic_script, prompt_text, kind="anthropic"
        )
        if response is None:
            return FakeTextResponse("")
        return response

    async def gemini_generate(
        self, *, run_id, tenant_id, model: str, contents: Any = "", **kwargs: Any
    ):
        prompt_text = contents if isinstance(contents, str) else str(contents)
        self.models.append(model)
        self.gemini_calls.append(
            {
                "run_id": run_id,
                "tenant_id": tenant_id,
                "model": model,
                "contents": prompt_text,
                "prompt_text": prompt_text,
            }
        )

        self._maybe_raise("gemini", len(self.gemini_calls), prompt_text)
        self._fill_audit_out(kwargs.get("audit_out"), provider="google", model=model)

        response = self._serve(self._gemini_script, prompt_text, kind="gemini")
        if response is None:
            return FakeTextResponse("")
        if isinstance(response, str):
            return FakeTextResponse(response)
        return response

    # -- internals ----------------------------------------------------------

    def _maybe_raise(self, kind: str, index: int, prompt_text: str) -> None:
        hook = self._raise_on_call
        if hook is None:
            return
        if isinstance(hook, BaseException):
            raise hook
        if isinstance(hook, type) and issubclass(hook, BaseException):
            raise hook(f"{kind} call {index} refused by the fake")
        if callable(hook):
            exc = hook(kind, index, prompt_text)
            if exc is not None:
                raise exc

    def _fill_audit_out(
        self, audit_out: Any, *, provider: str, model: str
    ) -> None:
        if not isinstance(audit_out, dict):
            return
        self._audit_seq += 1
        audit_out["audit_id"] = f"aud-{self._audit_seq:04d}"
        audit_out["cost_usd"] = self.COST_USD
        audit_out["provider"] = provider
        audit_out["model"] = model
        audit_out["duration_ms"] = 1

    def _serve(self, script: Any, prompt_text: str, *, kind: str) -> Any:
        if script is None:
            self.unscripted.append(f"{kind}: no script supplied")
            return None

        queue = script
        if isinstance(script, dict):
            queue = None
            for marker, entry in script.items():
                if marker and marker in prompt_text:
                    queue = entry
                    break
            if queue is None:
                queue = script.get("")
            if queue is None:
                self.unscripted.append(
                    f"{kind}: no script key matched (prompt starts {prompt_text[:60]!r})"
                )
                return None

        if not isinstance(queue, (list, tuple)):
            return queue

        items = list(queue)
        if not items:
            self.unscripted.append(f"{kind}: empty script queue")
            return None

        cursor = self._anthropic_cursor if kind == "anthropic" else self._gemini_cursor
        if isinstance(script, dict):
            # Per-key queues are round-robined on their own length so two keys do
            # not share one cursor.
            index = min(cursor, len(items) - 1)
        else:
            index = cursor
        if index >= len(items):
            self.unscripted.append(
                f"{kind}: script exhausted after {len(items)} response(s) — reusing the last"
            )
            index = len(items) - 1

        if kind == "anthropic":
            self._anthropic_cursor += 1
        else:
            self._gemini_cursor += 1
        return items[index]


def _anthropic_prompt_text(kwargs: dict[str, Any]) -> str:
    """Flatten a messages payload (plus the system prompt) into one string.

    Used for script routing AND for the prompt-content assertions: what the tests
    check is exactly what the provider would have received.
    """
    parts: list[str] = []
    system = kwargs.get("system")
    if isinstance(system, str):
        parts.append(system)
    for message in kwargs.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            parts.append(content)
            continue
        for block in content or []:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts)
