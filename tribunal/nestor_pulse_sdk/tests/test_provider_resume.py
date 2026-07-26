"""R7 — reconnect to an in-flight deep-research job instead of paying twice (15.2-16).

WHY this file exists
--------------------
Gemini and OpenAI deep research are dispatched with `background: true`: the call
returns a JOB ID immediately and the engine polls it for up to ~35 minutes. Those
jobs are the single most expensive thing this engine buys. Before R7 a worker
restart — or a park — threw the id away, so the resumed run dispatched a SECOND,
separately billed job for research that was already running and already paid for.

These tests pin the three properties that make a resume honest:

  1. a fresh dispatch REPORTS its job id (`on_job_started`), so there is
     something to reconnect to at all;
  2. a resume RECONNECTS — the dispatch call count is EXACTLY ZERO;
  3. an expired job id DEGRADES that one stream with a named reason — it never
     crashes the run, and it never silently re-dispatches (DEC-2).

ZERO LLM CALLS, ZERO NETWORK, ZERO KEYS, NO MOCKING LIBRARY. Every provider is a
hand-written duck-typed fake with call counters, in the register of
`test_gate_replay.py::_AnswerKeyGateAudited`. There is deliberately NO
`@pytest.mark.live` test here — nothing in this file touches a provider — which
matters twice over while the Anthropic account sits at its monthly cap.

Cloud Build gate:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import logging
import uuid

import pytest

httpx = pytest.importorskip("httpx")

from nestor_pulse_sdk.audit import audited_llm_client as alc  # noqa: E402
from nestor_pulse_sdk.audit.audited_llm_client import AuditedLLMClient  # noqa: E402
from nestor_pulse_sdk.pipeline.tribunal import research_division as rd  # noqa: E402

_RUN = uuid.uuid4()
_TENANT = uuid.uuid4()


# ---------------------------------------------------------------------------
# The Gemini fake: an httpx.AsyncClient shape with post/get counters.
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class _FakeHTTP:
    """Duck-typed `httpx.AsyncClient`. Counts posts, records every GET url.

    `get_script` is consumed one entry per GET: a dict is returned as the
    interaction body, an int is raised as an `httpx.HTTPStatusError` carrying
    that status code.
    """

    def __init__(self, *, get_script: list, post_id: str = "interaction-abc123") -> None:
        self.posts: list[str] = []
        self.gets: list[str] = []
        self._script = list(get_script)
        self._post_id = post_id

    async def __aenter__(self) -> "_FakeHTTP":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url, **_kw):
        self.posts.append(url)
        return _FakeResp({"id": self._post_id})

    async def get(self, url, **_kw):
        self.gets.append(url)
        item = self._script.pop(0) if self._script else {"status": "completed"}
        if isinstance(item, int):
            request = httpx.Request("GET", "https://example.invalid/x")
            raise httpx.HTTPStatusError(
                f"HTTP {item}", request=request,
                response=httpx.Response(item, request=request),
            )
        return _FakeResp(item)


def _install_gemini(monkeypatch, fake: _FakeHTTP) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "not-a-real-key-and-never-sent")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_kw: fake)


def _client() -> AuditedLLMClient:
    """An AuditedLLMClient built without touching a provider or a database.

    Only the two raw poll methods are exercised; they construct their own HTTP
    client (faked above) and never reach `start_call` / `end_call`.
    """
    return AuditedLLMClient.__new__(AuditedLLMClient)


# ---------------------------------------------------------------------------
# Gemini — fresh dispatch reports its job id
# ---------------------------------------------------------------------------


async def test_gemini_fresh_dispatch_reports_the_job_id_it_then_polls(monkeypatch):
    """`on_job_started` fires ONCE with the id the poll loop then GETs.

    If these two ever diverged, the recorded id would point at a job nobody is
    polling and every resume would 404.
    """
    fake = _FakeHTTP(get_script=[{"status": "completed", "output_text": "done"}])
    _install_gemini(monkeypatch, fake)

    seen: list[str] = []

    async def _record(job_id: str) -> None:
        seen.append(job_id)

    result = await _client().gemini_deep_research_raw(
        "q", poll_interval=0, on_job_started=_record,
    )

    assert result["status"] == "success"
    assert seen == ["interaction-abc123"], (
        "a fresh background job must be reported exactly once, with its id"
    )
    assert len(fake.posts) == 1, "a fresh dispatch posts exactly one interaction"
    assert fake.gets and fake.gets[0].endswith("/interactions/interaction-abc123"), (
        "the polled id must be the id that was reported — otherwise a resume "
        "reconnects to a job that does not exist"
    )


async def test_gemini_on_job_started_that_raises_does_not_break_the_call(
    monkeypatch, caplog
):
    """A checkpoint write is best-effort. It must never cost a paid research call."""
    fake = _FakeHTTP(get_script=[{"status": "completed", "output_text": "done"}])
    _install_gemini(monkeypatch, fake)

    async def _boom(_job_id: str) -> None:
        raise RuntimeError("the checkpoint write failed")

    with caplog.at_level(logging.WARNING):
        result = await _client().gemini_deep_research_raw(
            "q", poll_interval=0, on_job_started=_boom,
        )

    assert result["status"] == "success", (
        "a failed checkpoint write must not discard a paid deep-research call"
    )
    assert any(
        "on_job_started callback failed" in record.getMessage()
        for record in caplog.records
    ), "the failure must be named at WARNING, never swallowed silently"


# ---------------------------------------------------------------------------
# Gemini — resume
# ---------------------------------------------------------------------------


async def test_gemini_resume_dispatches_no_second_job(monkeypatch):
    """THE MONEY ASSERTION: the dispatch POST count is EXACTLY 0 on a resume."""
    fake = _FakeHTTP(get_script=[{"status": "completed", "output_text": "done"}])
    _install_gemini(monkeypatch, fake)

    result = await _client().gemini_deep_research_raw(
        "q", poll_interval=0, resume_job_id="interaction-in-flight-99",
    )

    assert result["status"] == "success"
    assert len(fake.posts) == 0, (
        "a resume must reconnect to the running job — a single POST here is a "
        "second, separately billed deep-research job"
    )
    assert fake.gets[0].endswith("/interactions/interaction-in-flight-99"), (
        "the first poll must target the resumed interaction"
    )


async def test_gemini_resume_with_a_traversal_id_never_builds_that_url(monkeypatch):
    """A poisoned `output` row must not reach the URL builder (T-15.2-125).

    The hostile id is refused by `safe_job_id`, so the call falls through to a
    fresh dispatch. What must NEVER happen is the traversal string appearing in
    a request path.
    """
    fake = _FakeHTTP(get_script=[{"status": "completed", "output_text": "done"}])
    _install_gemini(monkeypatch, fake)

    result = await _client().gemini_deep_research_raw(
        "q", poll_interval=0, resume_job_id="../../../secrets",
    )

    assert result["status"] == "success"
    assert all("../" not in url for url in fake.gets), (
        "a traversal segment must never be interpolated into a provider URL"
    )
    assert all("secrets" not in url for url in fake.gets)
    assert len(fake.posts) == 1, (
        "a refused resume id falls through to a fresh dispatch rather than "
        "polling a hostile path"
    )


async def test_gemini_resume_that_is_gone_degrades_and_does_not_redispatch(monkeypatch):
    """A 404 on a RESUMED id is a lost stream with a named reason — not a crash."""
    monkeypatch.setattr(alc, "RESUME_REDISPATCH", False)
    fake = _FakeHTTP(get_script=[404])
    _install_gemini(monkeypatch, fake)

    result = await _client().gemini_deep_research_raw(
        "q", poll_interval=0, resume_job_id="interaction-expired",
    )

    assert result["status"] == "error"
    assert "no longer retrievable" in result["error_message"]
    assert "NOT re-dispatched" in result["error_message"]
    assert len(fake.posts) == 0, "a gone resume must not silently buy the job again"


# ---------------------------------------------------------------------------
# OpenAI — the fake responses client
# ---------------------------------------------------------------------------


class _FakeOpenAIResponse:
    def __init__(self, rid: str, status: str, text: str = "report body") -> None:
        self.id = rid
        self.status = status
        self.output_text = text


class _NotFoundError(Exception):
    """Duck-typed stand-in: `_is_not_found` keys on the class NAME."""


_NotFoundError.__name__ = "NotFoundError"


class _FakeResponses:
    def __init__(self, *, retrieve_script: list) -> None:
        self.creates = 0
        self.retrieved: list[str] = []
        self._script = list(retrieve_script)

    async def create(self, **_kw):
        self.creates += 1
        return _FakeOpenAIResponse("resp_fresh_001", "in_progress")

    async def retrieve(self, response_id):
        self.retrieved.append(response_id)
        item = self._script.pop(0) if self._script else _FakeOpenAIResponse(
            str(response_id), "completed"
        )
        if isinstance(item, Exception):
            raise item
        return item


class _FakeOpenAI:
    def __init__(self, *, retrieve_script: list) -> None:
        self.responses = _FakeResponses(retrieve_script=retrieve_script)


def _install_openai(monkeypatch, fake: _FakeOpenAI) -> None:
    openai = pytest.importorskip("openai")
    monkeypatch.setenv("OPENAI_API_KEY", "not-a-real-key-and-never-sent")
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **_kw: fake)


async def test_openai_fresh_create_reports_the_response_id(monkeypatch):
    fake = _FakeOpenAI(retrieve_script=[
        _FakeOpenAIResponse("resp_fresh_001", "completed"),
    ])
    _install_openai(monkeypatch, fake)

    seen: list[str] = []

    async def _record(job_id: str) -> None:
        seen.append(job_id)

    result = await _client().openai_deep_research_raw(
        "q", poll_interval=0, on_job_started=_record,
    )

    assert result["status"] == "success"
    assert seen == ["resp_fresh_001"]
    assert fake.responses.creates == 1


async def test_openai_resume_calls_create_zero_times(monkeypatch):
    """THE MONEY ASSERTION for OpenAI: `responses.create` is EXACTLY 0."""
    fake = _FakeOpenAI(retrieve_script=[
        _FakeOpenAIResponse("resp_in_flight_42", "completed"),
    ])
    _install_openai(monkeypatch, fake)

    result = await _client().openai_deep_research_raw(
        "q", poll_interval=0, resume_job_id="resp_in_flight_42",
    )

    assert result["status"] == "success"
    assert fake.responses.creates == 0, (
        "a resume must reconnect — a create here is a second paid job"
    )
    assert fake.responses.retrieved[0] == "resp_in_flight_42", (
        "the first retrieve must target the resumed response id"
    )


async def test_openai_resume_404_degrades_when_redispatch_is_off(monkeypatch):
    """DEC-2 default: name the loss, degrade the stream, buy nothing twice."""
    monkeypatch.setattr(alc, "RESUME_REDISPATCH", False)
    fake = _FakeOpenAI(retrieve_script=[_NotFoundError("response not found")])
    _install_openai(monkeypatch, fake)

    result = await _client().openai_deep_research_raw(
        "q", poll_interval=0, resume_job_id="resp_expired_7",
    )

    # No pytest.raises anywhere: an expired resume must NEVER escape as an
    # exception — it is a degraded stream, not a broken run.
    assert result["status"] == "error"
    assert "no longer retrievable" in result["error_message"]
    assert fake.responses.creates == 0, (
        "with the knob off, a gone resume must not dispatch a replacement job"
    )


async def test_openai_resume_404_redispatches_exactly_once_when_the_knob_is_on(
    monkeypatch,
):
    """The escape hatch, and its price: exactly ONE fresh, separately billed job."""
    monkeypatch.setattr(alc, "RESUME_REDISPATCH", True)
    fake = _FakeOpenAI(retrieve_script=[
        _NotFoundError("response not found"),
        _FakeOpenAIResponse("resp_fresh_001", "completed"),
    ])
    _install_openai(monkeypatch, fake)

    result = await _client().openai_deep_research_raw(
        "q", poll_interval=0, resume_job_id="resp_expired_7",
    )

    assert result["status"] == "success"
    assert fake.responses.creates == 1, (
        "the redispatch knob buys exactly one replacement job — never more"
    )


# ---------------------------------------------------------------------------
# The two adapters forward the kwargs verbatim
# ---------------------------------------------------------------------------


class _RecordingAudited:
    """Records what the adapter forwarded to the raw method. No audit chain."""

    def __init__(self) -> None:
        self.forwarded: dict = {}

    async def start_call(self, **_kw):
        return object()

    async def end_call(self, _handle, **_kw):
        return None

    async def write_failure(self, **_kw):
        return None

    async def gemini_deep_research_raw(self, query, **kwargs):
        self.forwarded = dict(kwargs)
        return {"status": "success", "report": "r"}

    async def openai_deep_research_raw(self, query, **kwargs):
        self.forwarded = dict(kwargs)
        return {"status": "success", "report": "r"}


@pytest.mark.parametrize("module_path", [
    "nestor_pulse_sdk.tools.gemini_adapter",
    "nestor_pulse_sdk.tools.openai_adapter",
])
async def test_both_adapters_forward_the_resume_kwargs_verbatim(module_path):
    """The adapter is a pass-through. If it dropped these, R7 would be dead code."""
    import importlib

    adapter = importlib.import_module(module_path)
    audited = _RecordingAudited()

    async def _cb(_job_id: str) -> None:
        return None

    await adapter.deep_research_audited(
        query="q", audited=audited, run_id=_RUN, tenant_id=_TENANT,
        resume_job_id="job-abc", on_job_started=_cb,
    )

    assert audited.forwarded.get("resume_job_id") == "job-abc", (
        f"{module_path} must forward resume_job_id to the raw method"
    )
    assert audited.forwarded.get("on_job_started") is _cb, (
        f"{module_path} must forward on_job_started verbatim"
    )


# ---------------------------------------------------------------------------
# run_angles — a restored angle is never dispatched
# ---------------------------------------------------------------------------


async def test_a_restored_angle_is_never_re_dispatched(monkeypatch, caplog):
    """Two angles, one restored ⇒ the scripted runner is called EXACTLY once.

    This is R3's whole economic claim, asserted as a call count rather than as a
    log line. It also pins that a restored angle counts as COVERED: if it did
    not, the angle-coverage retry below would fire and the counter would read 2.
    """
    calls: list[str] = []

    async def _fake_runner(*, query, audited, run_id, tenant_id, **_kw):
        calls.append(query)
        return {"status": "success", "report": "fresh report"}

    monkeypatch.setattr(
        rd, "_PROVIDER_RUNNERS", {"openai": _fake_runner, "claude": _fake_runner}
    )
    monkeypatch.setattr(
        rd, "_enabled_providers",
        lambda: [("openai", _fake_runner), ("claude", _fake_runner)],
    )

    angles = [
        {"query": "q0", "focus_area": "fa-0", "stakes": "med", "provider": "openai"},
        {"query": "q1", "focus_area": "fa-1", "stakes": "med", "provider": "openai"},
    ]
    restored_result = {
        "status": "success", "report": "already paid for", "_angle": "fa-0",
        "_stakes": "med", "_d8_prompted": False,
    }

    recorded: list[tuple[int, str]] = []

    async def _on_angle_result(idx: int, provider: str, result: dict) -> None:
        recorded.append((idx, provider))

    with caplog.at_level(logging.WARNING):
        results = await rd.run_angles(
            angles=angles,
            audited=_RecordingAudited(),
            run_id=_RUN,
            tenant_id=_TENANT,
            # The recorded tuple arrives as a LIST, exactly as it would after a
            # JSON round-trip through the `output` table.
            resume_results={0: ["openai", restored_result]},
            on_angle_result=_on_angle_result,
        )

    assert len(calls) == 1, (
        "exactly one angle may be dispatched — the restored angle must cost "
        f"nothing, but the runner was called {len(calls)} time(s)"
    )
    assert calls[0].startswith("q1"), "the angle that ran must be the UNrestored one"
    assert len(results) == 2, "both angles must reach the merge"

    by_angle = {r[1].get("_angle") for r in results}
    assert by_angle == {"fa-0", "fa-1"}, (
        "the restored tuple must keep its `_angle` key, or the angle-coverage "
        "gate would treat its focus area as unresearched and re-buy it"
    )
    assert recorded == [(1, "openai")], (
        "only the freshly researched angle is checkpointed; re-recording a "
        "restored one would be a pointless write"
    )
    assert any("RESTORED" in record.getMessage() for record in caplog.records), (
        "a restored angle must be named in the log — never a silent skip"
    )


async def test_a_recorded_job_for_a_different_provider_is_ignored(monkeypatch, caplog):
    """A re-routed angle must not poll another provider's job id."""
    seen_kwargs: list[dict] = []

    async def _fake_runner(*, query, audited, run_id, tenant_id, **kw):
        seen_kwargs.append(kw)
        return {"status": "success", "report": "r"}

    monkeypatch.setattr(rd, "_PROVIDER_RUNNERS", {"openai": _fake_runner})
    monkeypatch.setattr(rd, "_enabled_providers", lambda: [("openai", _fake_runner)])

    angles = [{"query": "q0", "focus_area": "fa-0", "stakes": "med", "provider": "openai"}]

    with caplog.at_level(logging.WARNING):
        await rd.run_angles(
            angles=angles, audited=_RecordingAudited(), run_id=_RUN, tenant_id=_TENANT,
            resume_jobs={0: {"provider": "gemini", "job_id": "interaction-xyz"}},
        )

    assert "resume_job_id" not in seen_kwargs[0], (
        "a gemini job id must never be handed to the openai poll — it can only 404"
    )
    assert any("IGNORED" in record.getMessage() for record in caplog.records)


async def test_a_matching_recorded_job_is_handed_to_the_provider(monkeypatch):
    """The happy path: same provider, so the angle reconnects instead of re-buying."""
    seen_kwargs: list[dict] = []

    async def _fake_runner(*, query, audited, run_id, tenant_id, **kw):
        seen_kwargs.append(kw)
        return {"status": "success", "report": "r"}

    monkeypatch.setattr(rd, "_PROVIDER_RUNNERS", {"openai": _fake_runner})
    monkeypatch.setattr(rd, "_enabled_providers", lambda: [("openai", _fake_runner)])

    angles = [{"query": "q0", "focus_area": "fa-0", "stakes": "med", "provider": "openai"}]

    await rd.run_angles(
        angles=angles, audited=_RecordingAudited(), run_id=_RUN, tenant_id=_TENANT,
        resume_jobs={0: {"provider": "openai", "job_id": "resp_in_flight_42"}},
    )

    assert seen_kwargs[0].get("resume_job_id") == "resp_in_flight_42"


async def test_a_hostile_recorded_job_id_never_reaches_a_runner(monkeypatch):
    """`safe_job_id` runs on the way OUT of the checkpoint too (T-15.2-125)."""
    seen_kwargs: list[dict] = []

    async def _fake_runner(*, query, audited, run_id, tenant_id, **kw):
        seen_kwargs.append(kw)
        return {"status": "success", "report": "r"}

    monkeypatch.setattr(rd, "_PROVIDER_RUNNERS", {"openai": _fake_runner})
    monkeypatch.setattr(rd, "_enabled_providers", lambda: [("openai", _fake_runner)])

    angles = [{"query": "q0", "focus_area": "fa-0", "stakes": "med", "provider": "openai"}]

    await rd.run_angles(
        angles=angles, audited=_RecordingAudited(), run_id=_RUN, tenant_id=_TENANT,
        resume_jobs={0: {"provider": "openai", "job_id": "../../etc/passwd"}},
    )

    assert "resume_job_id" not in seen_kwargs[0], (
        "a poisoned checkpoint row must be refused before it reaches a provider"
    )
