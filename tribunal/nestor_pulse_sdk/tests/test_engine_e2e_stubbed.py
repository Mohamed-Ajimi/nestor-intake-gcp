"""Stubbed end-to-end engine proof — D-02's single gating test (Phase 15.2).

WHY. Phase 15.2 rebuilt the research engine around a new spine: a question
workshop replaces the single-call intake, four peer research streams replace
three, every stream is asked for a machine-readable fact list, the cross-provider
merge moved ABOVE the verification gates, and a park/resume checkpoint layer
wraps the lot. Sixteen plans changed the wiring. Nothing until this file drove
the whole thing from `TribunalPipeline.run(...)` to a finished report in one
command. Every other test in the phase proves one component's contract; this one
proves the components are actually connected to each other — which is the failure
class the phase keeps catching, and the one a per-component suite structurally
cannot see.

It matters twice over right now: the Anthropic account is at its monthly usage
cap until 2026-08-01, so the redesigned pipeline CANNOT be exercised against a
real provider before it is deployed. This file is the only thing that can say
"the wiring runs" before then.

THIS FILE MAKES ZERO LLM CALLS. Every provider call is served by
`_ScriptedProvidersAudited`, a hand-written duck-typed fake defined in this
module. No network, no database, no mocking library for the provider surface, no
API key, no spend, and nothing that can flake.

NON-GOAL, stated explicitly because a reader will otherwise assume the opposite.
This file does NOT judge whether the tournament picks good questions, whether
real providers emit well-formed fact lists, whether the merge clusters real
phrasings, whether the gates select the right claims, or whether the
own-researcher is useful. Every one of those is a judgement about MODEL OUTPUT,
and a CI test that pretended to make it would be judging its own script. Per
D-02 they are V-01/V-02 items for the August live run. What is under test here is
the PLUMBING: that each stage receives what the previous stage produced, in the
shape it expects, and that the observable effects of the run — the stage
sequence, the funnel arithmetic, the report sections, the provenance that reaches
persistence, the degradation vocabulary — are the ones the phase's decisions
specify.

Cloud Build gate:
  gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml

NO PYTEST MARKER, deliberately. This file touches no provider and no Postgres, so
it carries neither `live` nor `slow` nor `integration` — the engine gate runs
`-m "not live"` and this file must be SELECTED by it. `asyncio_mode = "auto"` is
set in `tribunal/pyproject.toml`, so the tests below are plain `async def`.
"""
from __future__ import annotations

import re
import uuid
from typing import Any, Optional

# ---------------------------------------------------------------------------
# COUPLING GUARDS.
#
# Every format literal this file needs is IMPORTED FROM PRODUCTION and the
# scripted provider output is BUILT from it. That is deliberate, and it is the
# same discipline `test_gate_replay.py:77-84` applies to its 240-character
# truncation: the script is keyed on the production format ON PURPOSE. If
# `facts.py` renames a sentinel, or `steps.py` retranslates a heading, the
# scripted reports stop parsing and `_ScriptedProvidersAudited.unexpected` fills
# up — which the assertions below report BY NAME rather than swallowing into a
# plausible-looking default.
# ---------------------------------------------------------------------------
from nestor_pulse_sdk.pipeline.tribunal import gates as _gates_mod
from nestor_pulse_sdk.pipeline.tribunal import grouping as _grouping_mod
from nestor_pulse_sdk.pipeline.tribunal import research_division as _division_mod
from nestor_pulse_sdk.pipeline.tribunal import serpapi as _serpapi_mod
from nestor_pulse_sdk.pipeline.tribunal import workshop as _workshop_mod
from nestor_pulse_sdk.pipeline.tribunal import workshop_rank as _rank_mod
from nestor_pulse_sdk.pipeline.tribunal import budget as _budget_mod
from nestor_pulse_sdk.pipeline.tribunal import pipeline as _pipeline_mod
from nestor_pulse_sdk.pipeline.deep_researchers import degraded_parallel as _degraded_mod
from nestor_pulse_sdk.pipeline.tribunal.facts import (
    CERTAINTY_VALUES,
    FACTS_END,
    FACTS_START,
    NOT_FOUND_END,
    NOT_FOUND_START,
    QUALITY_VALUES,
    VERTEX_REDIRECT_HOST,
)
from nestor_pulse_sdk.pipeline.tribunal.pipeline import TribunalPipeline
from nestor_pulse_sdk.pipeline.tribunal.reliability import terminal_state
from nestor_pulse_sdk.pipeline.synthesis.steps import _SECTION_STRINGS
from nestor_pulse_sdk.runs.stages import ENGINE_STAGES
from nestor_pulse_sdk.verification.report import shape_verification_report

#: The two D-08 headings, read from production rather than retyped. The run has
#: no `language`, so `_norm_lang` resolves to English.
_DISPUTED_H = _SECTION_STRINGS["english"]["disputed_h"]
_COULD_NOT_H = _SECTION_STRINGS["english"]["gaps_h"]
_SUB_CONTRADICTIONS = _SECTION_STRINGS["english"]["sub_contradictions"]
_SUB_SUPERSEDED = _SECTION_STRINGS["english"]["sub_superseded"]
_SUB_BRIEF = _SECTION_STRINGS["english"]["sub_brief"]

#: Written by `_verification_appendix` / `_extract_sources_section`, which emit
#: English headings on every run regardless of run language (their own docstrings
#: say so), so these two are safe to name directly.
_VERIFICATION_H = "## Verification"
_SOURCES_H = "## Sources"

#: The stage keys `ENGINE_STAGES["tribunal"]` declares. The WR-03 guard below
#: reads this rather than a retyped list, so a stage this run reports being in
#: that the schema never declared fails HERE instead of rendering as a bare
#: unlabelled key in the operator's UI.
_DECLARED_STAGE_KEYS = {row["key"] for row in ENGINE_STAGES["tribunal"]} | {"done"}


# ===========================================================================
# The brief, and the scripted research corpus.
# ===========================================================================

#: ONE enumerated question, so `intake.detect_explicit_questions` yields exactly
#: one client-validated question and the whole downstream section structure (D4:
#: one focus area per CLIENT question) is a single, assertable label.
_CLIENT_QUESTION = (
    "What share of the Benelux fuel-retail market does LUKOIL hold in 2026?"
)
_BRIEF = (
    "We are preparing a competitive briefing on fuel retail in the Benelux.\n"
    f"1. {_CLIENT_QUESTION}\n"
)

#: A Gemini grounded-search redirect URL. Pitfall 10: Gemini does not return
#: source URLs, it returns opaque redirects on this host, and the real domain
#: survives ONLY as the markdown link LABEL in the report's trailing source
#: list. Putting one in the scripted corpus is what exercises
#: `facts.display_domain` on the path that actually matters in production.
_REDIRECT_URL = f"https://{VERTEX_REDIRECT_HOST}/grounding-api-redirect/AB12CD34"
_REDIRECT_REAL_DOMAIN = "statbel.fgov.be"

_URL_OFFICIAL_BE = "https://economie.fgov.be/nl/brandstof-2026"
_URL_PRESS_BENELUX = "https://www.tijd.be/benelux-brandstofmarkt-2026"
_URL_PRESS_GUNVOR = "https://www.reuters.com/lukoil-gunvor-2026"
_URL_PRESS_CARLYLE = "https://www.bloomberg.com/lukoil-carlyle-2026"
_URL_OFFICIAL_NL = "https://www.cbs.nl/marges-2026"
_URL_OWN = "https://www.fps-economy.example/stations-2026"

#: THE CORROBORATED FACT. Stated by gemini AND openai in BYTE-IDENTICAL wording,
#: because `steps._dedupe_claims` unions `found_by` on NORMALISED TEXT EQUALITY —
#: two different phrasings stay two claims (they corroborate at the CLUSTER
#: level, which is a different signal). This is the one that must reach
#: persistence with `len(found_by) == 2`.
_FACT_CORROBORATED = "The Benelux fuel-retail market was worth EUR 38 billion in 2026."

#: THE CONTRADICTORY PAIR. Same entity, same attribute, incompatible values —
#: exactly the shape that shipped twice in run 4cbb5311 because the two claims
#: were checked in two unrelated skeptic sessions. D9/D11 moved the merge above
#: the gates so a pair like this lands in ONE session; the clean-run test asserts
#: that it did.
_FACT_GUNVOR = "LUKOIL's international operations were sold to Gunvor in 2026."
_FACT_CARLYLE = "LUKOIL's international operations were sold to Carlyle in 2026."

#: SINGLE-SOURCE facts — one stream each, so `found_by` stays at one entry.
_FACT_SHARE = "LUKOIL held a 4.1% share of the Belgian fuel-retail market in 2026."
_FACT_REDIRECT = "Belgian road-fuel volumes fell 2.3% year on year in 2026."
_FACT_EXCISE = "Belgian fuel excise duty rose by 3 cents per litre on 1 April 2026."
_FACT_MARGIN = "Dutch fuel-retail margins averaged 12 cents per litre in 2026."
_FACT_OWN = "LUKOIL operates 173 filling stations across the Benelux in 2026."

#: The provider's own "I looked and could not establish this" lines. They become
#: `research_gap` rows in stage 7 and are what makes D-08's "What we could not
#: establish" section render with REAL content instead of its empty placeholder.
_NOT_FOUND_CLAUDE = [
    "LUKOIL's 2026 Benelux revenue split between retail and wholesale.",
    "Whether the Carlyle transaction closed before the 2026 sanctions deadline.",
]
_NOT_FOUND_OWN = ["The number of LUKOIL-branded stations in Luxembourg in 2026."]


def _fact_line(statement: str, url: str, quality: str, certainty: str) -> str:
    """One D8 fact line, in the production column order.

    STATEMENT<TAB>SOURCE_URL<TAB>QUALITY<TAB>CERTAINTY<TAB>EVIDENCE — built here
    from the imported vocabulary tuples rather than from hand-typed words, so a
    change to `QUALITY_VALUES` / `CERTAINTY_VALUES` breaks the script loudly.

    EVIDENCE is the statement itself: `scrub_research` locates a discredited
    passage by matching this span byte-for-byte against the prose, and the prose
    below quotes each statement verbatim for exactly that reason.
    """
    assert quality in QUALITY_VALUES, quality
    assert certainty in CERTAINTY_VALUES, certainty
    return "\t".join([statement, url, quality, certainty, statement])


def _report(prose_facts: list[str], fact_lines: list[str], not_found: list[str],
            *, source_list: str = "") -> str:
    """A whole scripted provider report: prose, source list, then the D8 blocks.

    The prose repeats each statement verbatim so `scrub_research`'s evidence
    assertion has something real to delete, and the trailing markdown source list
    is what `facts.build_label_index` reads to resolve a redirect URL back to its
    display domain.
    """
    body = ["## Findings", ""]
    body += [f"- {line}" for line in prose_facts]
    if source_list:
        body += ["", "## Sources consulted", "", source_list]
    body += ["", FACTS_START]
    body += fact_lines
    body += [FACTS_END, NOT_FOUND_START]
    body += not_found
    body += [NOT_FOUND_END]
    return "\n".join(body)


_GEMINI_REPORT = _report(
    [_FACT_SHARE, _FACT_CORROBORATED, _FACT_GUNVOR, _FACT_REDIRECT],
    [
        _fact_line(_FACT_SHARE, _URL_OFFICIAL_BE, "official", "certain"),
        _fact_line(_FACT_CORROBORATED, _URL_PRESS_BENELUX, "press", "single"),
        _fact_line(_FACT_GUNVOR, _URL_PRESS_GUNVOR, "press", "single"),
        # Pitfall 10: a BARE redirect URL on the fact line. It resolves only
        # through the label index built from the source list below.
        _fact_line(_FACT_REDIRECT, _REDIRECT_URL, "official", "single"),
    ],
    [],
    source_list=f"44. [{_REDIRECT_REAL_DOMAIN}]({_REDIRECT_URL})",
)

_OPENAI_REPORT = _report(
    [_FACT_CORROBORATED, _FACT_EXCISE],
    [
        _fact_line(_FACT_CORROBORATED, _URL_PRESS_BENELUX, "press", "single"),
        _fact_line(_FACT_EXCISE, _URL_OFFICIAL_BE, "official", "certain"),
    ],
    [],
)

_CLAUDE_REPORT = _report(
    [_FACT_CARLYLE, _FACT_MARGIN],
    [
        _fact_line(_FACT_CARLYLE, _URL_PRESS_CARLYLE, "press", "single"),
        _fact_line(_FACT_MARGIN, _URL_OFFICIAL_NL, "press", "single"),
    ],
    _NOT_FOUND_CLAUDE,
)

#: The own-researcher does NOT emit a prose fact block: 15.2-12 gives it a forced
#: `emit_fact_list` client tool, and `own_researcher.render_report` renders the
#: D8 block from the already-parsed facts. So the fake supplies the TOOL INPUT
#: and production does the rendering.
_OWN_TOOL_INPUT = {
    "facts": [
        {
            "statement": _FACT_OWN,
            "source_url": _URL_OWN,
            "quality": "official",
            "certainty": "single",
            "evidence": _FACT_OWN,
        }
    ],
    "not_found": list(_NOT_FOUND_OWN),
}

#: text -> the cluster id the scripted merge assigns it. The contradictory pair
#: SHARES an id; everything else is its own cluster. This is the only place the
#: test decides the merge's shape, and it decides it by CLAIM TEXT — the same
#: thing the production clusterer is shown.
_CLUSTER_OF: dict[str, int] = {
    _FACT_GUNVOR: 0,
    _FACT_CARLYLE: 0,
    _FACT_SHARE: 1,
    _FACT_CORROBORATED: 2,
    _FACT_REDIRECT: 3,
    _FACT_EXCISE: 4,
    _FACT_MARGIN: 5,
    _FACT_OWN: 6,
}

#: The scripted workshop output. Three candidates so the near-duplicate clusterer
#: has something to do (it needs >= 2) and the Swiss tournament has a real pair
#: plus a bye.
_CANDIDATES = [
    "How large is LUKOIL's Benelux fuel-retail footprint by station count in 2026?",
    "What is LUKOIL's 2026 market share by fuel volume in Belgium specifically?",
    "Which owners hold LUKOIL's Benelux retail assets after the 2026 divestment?",
]

_ORIENTATION_INPUT = {
    "findings": [
        "Belgian fuel-retail share is reported by volume, not by station count.",
        "LUKOIL's Benelux retail assets changed hands during 2026.",
    ],
    "brief_conflicts": [
        {
            "assumption": "LUKOIL still owns its Benelux retail network outright.",
            "world_says": (
                "Reporting from 2026 describes a divestment of LUKOIL's "
                "international operations."
            ),
            "source_url": _URL_PRESS_GUNVOR,
        }
    ],
}


# ===========================================================================
# The scripted provider fake.
# ===========================================================================

_INDEXED_LINE_RE = re.compile(r"^\s*(\d+)\s*\|\s*(.*)$")

#: Prompt-HEADER markers, one per consumer. Every one of them is read from the
#: text BEFORE the indexed item block, or from the tool list — never from an
#: item's own text — so no scripted claim, candidate or provider sentence can
#: misroute an answer. That is `gates.py:296-301`'s rule, applied to the fake.
_M_TAG = "INDEX | ENTITY | ATTRIBUTE"
_M_CLUSTER = "INDEX | CLUSTER_ID"
_M_MATERIALITY = "TEST 1 - FALSIFIABLE-SPECIFIC"
_M_STABILITY = "STABLE NOTORIOUS FACTS"
_M_CRITIQUE = "INDEX | KEEP|WEAK|KILL"
_M_TOURNAMENT = "MATCH_INDEX | A"
_M_CONFLICT = "Identify direct contradictions"
_M_SCRUB = "DISCREDITED CLAIMS"
_M_SECTION = "YOUR ASSIGNMENT: write ONE markdown section"
_M_WRAP = "Below are the finished body sections"
_M_CANDIDATES = "CANDIDATE: <one sharp"
_M_EVOLVE = "sharpening the winning research sub-questions"
_M_DISTILLER = "You are a claim distiller."

#: The 240-character truncation `gates._gate_batch`, `grouping._cluster_block`
#: and `workshop_rank._candidate_block` all apply to an item before it enters a
#: prompt. It is a SECURITY control (truncate + address by index), not
#: formatting, and the fake keys its answer map on the SAME width so a change to
#: it surfaces as an `unexpected` entry rather than as a silent default.
_PROMPT_TRUNCATION = 240


def _prompt_key(text: str) -> str:
    """The prompt-visible form of an item: truncated, then whitespace-trimmed."""
    return (text or "")[:_PROMPT_TRUNCATION].strip()


_CLUSTER_BY_KEY = {_prompt_key(t): cid for t, cid in _CLUSTER_OF.items()}


def _indexed_items(prompt: str, header_marker: str) -> list[tuple[str, str]]:
    """Every `INDEX | BODY` line in the block AFTER `header_marker`.

    Splitting on the marker is what keeps the fake reading the ITEM BLOCK only.
    A `|` inside a candidate or a claim cannot forge a line, because production
    collapses newlines out of every item before rendering it.
    """
    _, _, block = prompt.rpartition(header_marker)
    out: list[tuple[str, str]] = []
    for raw in block.splitlines():
        match = _INDEXED_LINE_RE.match(raw)
        if match:
            out.append((match.group(1), match.group(2).strip()))
    return out


class _FakeTextResponse:
    """A Gemini-shaped completion: `.text` is what every reader here looks at."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.candidates: list[Any] = []


class _FakeToolUseBlock(dict):
    """A tool_use content block.

    A `dict` subclass on purpose: `skeptic._block_get` and every parser in the
    engine read a block through `.get(...)` OR `getattr(...)`, and the recorded
    provider responses this stands in for arrive as plain mappings after the SDK
    deserialises them.
    """

    def __init__(self, name: str, payload: Any) -> None:
        super().__init__(
            type="tool_use", id=f"toolu_{name}", name=name, input=payload
        )


class _FakeTextBlock(dict):
    def __init__(self, text: str) -> None:
        super().__init__(type="text", text=text)


class _FakeMessage:
    """An Anthropic-shaped response: `.stop_reason` plus a `.content` block list."""

    def __init__(self, blocks: list[Any], *, stop_reason: str = "tool_use") -> None:
        self.content = list(blocks)
        self.stop_reason = stop_reason


class _FakeHandle:
    """What `start_call` hands back — copied from `FakeAudited._FakeHandle`."""

    def __init__(self, run_id, tenant_id, provider, model) -> None:
        self.audit_id = uuid.uuid4()
        self.run_id = run_id
        self.tenant_id = tenant_id
        self.provider = provider
        self.model = model


class _ScriptedProvidersAudited:
    """A duck-typed stand-in for the MODEL and the third-party research providers.

    IT IS NOT A STUB OF THE PIPELINE. Everything between `TribunalPipeline.run(...)`
    and this object is production code doing its real job: the workshop's
    orientation loop and its forced-tool final turn, the candidate sentinel
    parser, the near-duplicate clusterer, the Swiss pairing and the Elo, the
    evolve fence, the angle distribution over four streams, the D8 fact-list
    parser, the cross-provider merge, the gate batching and its inverted default,
    the group-skeptic tool-use protocol, the adjudication rule, the coverage gate,
    the conflict detector, the deterministic scrub, the citation post-pass, the
    funnel arithmetic and both deterministic report sections. This object only
    ever answers, in the consumer's OWN plain-text or tool-input format, the
    question production actually asked.

    THE HONESTY RULE, taken from `test_gate_replay.py`'s `unmatched` ledger: a
    prompt the router does not recognise is RECORDED in `self.unexpected` and
    answered with an empty response. It is never defaulted to a plausible answer,
    because a plausible default would make this file pass while proving that the
    script is self-consistent rather than that the engine is wired.
    """

    def __init__(self) -> None:
        self.calls = 0
        self.models: list[str] = []
        self.unexpected: list[str] = []
        #: Per-route call counters. `calls` must equal their sum — an unaccounted
        #: call means a route answered without booking itself.
        self.routes: dict[str, int] = {}
        #: Third-party provider names whose scripted report carried NO D8 fact
        #: block. Empty on the clean run; the Task-2 subclass fills it.
        self.factless_providers: list[str] = []
        #: The deep-research / audit bookkeeping surface, copied from
        #: `test_graceful_degradation.FakeAudited`.
        self.start_calls: list[dict] = []
        self.end_calls: list[dict] = []
        self.failures: list[dict] = []
        #: Every `serpapi_search` the own-researcher asked for. Non-empty is what
        #: makes "the real serpapi.search was never entered" a real assertion.
        self.serpapi_searches: list[dict] = []
        #: One entry per group-skeptic session: the CLAIM TEXTS that session was
        #: asked to evaluate. Recorded as the parsed block rather than as the raw
        #: prompt on purpose — the prompt also carries a PRIOR SOURCES context
        #: block built from the research prose, which quotes every scripted fact.
        #: Searching the whole prompt for a claim would therefore match in EVERY
        #: session and turn the shared-session assertion into a tautology.
        self.group_claim_blocks: list[list[str]] = []
        self._own_turns = 0
        #: Route names whose FIRST call raises a transient error and whose second
        #: succeeds — D-12's recovered-retry carve-out, driven without a mocking
        #: library. `forced_failures` is what keeps the assertion non-vacuous: a
        #: test that never actually tripped the failure proves nothing.
        self.fail_once_on: set[str] = set()
        self.forced_failures = 0
        self._already_failed: set[str] = set()

    # -- bookkeeping --------------------------------------------------------

    def _book(self, route: str) -> None:
        """Count the call, then apply any scripted once-only transient failure.

        Counted BEFORE the failure is raised, on purpose: a retried call really
        did reach the provider twice, and a counter that hid the failed attempt
        would understate what the run cost.
        """
        self.calls += 1
        self.routes[route] = self.routes.get(route, 0) + 1
        if route in self.fail_once_on and route not in self._already_failed:
            self._already_failed.add(route)
            self.forced_failures += 1
            # "503" is in `reliability._TRANSIENT_MARKERS`, so `classify` calls it
            # transient and `with_retry` retries it. A cap/billing wording would
            # be a HARD wall and would be re-raised after ONE attempt — which is
            # the OTHER carve-out, and not the one this drives.
            raise RuntimeError(f"503 Service Unavailable (scripted, route={route})")

    def _unexpected(self, kind: str, prompt: str) -> None:
        self.unexpected.append(f"{kind}: {prompt[:160]!r}")

    def _fill_audit_out(self, audit_out: Any) -> None:
        if isinstance(audit_out, dict):
            audit_out["audit_id"] = f"aud-{self.calls:04d}"
            audit_out["cost_usd"] = "0.0100"
            audit_out["duration_ms"] = 1

    # -- the Gemini surface -------------------------------------------------

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        prompt = contents if isinstance(contents, str) else str(contents)
        self.models.append(model)
        self._fill_audit_out(kwargs.get("audit_out"))

        # Order matters: the most specific marker first. Every marker below is
        # unique to ONE production prompt template.
        if _M_STABILITY in prompt:
            self._book("gate_stability")
            return _FakeTextResponse(self._answer_stability(prompt))
        if _M_MATERIALITY in prompt:
            self._book("gate_materiality")
            return _FakeTextResponse(self._answer_materiality(prompt))
        if _M_TAG in prompt:
            self._book("merge_tag")
            return _FakeTextResponse(self._answer_tag(prompt))
        if _M_CLUSTER in prompt:
            self._book("merge_cluster")
            return _FakeTextResponse(self._answer_cluster(prompt))
        if _M_CRITIQUE in prompt:
            self._book("workshop_critique")
            return _FakeTextResponse(self._answer_critique(prompt))
        if _M_TOURNAMENT in prompt:
            self._book("workshop_tournament")
            return _FakeTextResponse(self._answer_tournament(prompt))
        if _M_DISTILLER in prompt:
            # D-14's per-provider safety net. Reached only when a stream returned
            # no usable fact list; the clean run never gets here, which is why
            # the route counter is asserted as ZERO there and non-zero in the
            # degraded test.
            self._book("distiller_fallback")
            return _FakeTextResponse(self._answer_distiller())
        if _M_CONFLICT in prompt:
            self._book("conflict_detector")
            return _FakeTextResponse("[]")
        if _M_SCRUB in prompt:
            self._book("scrub_research")
            # An empty span list on purpose: layer 3 of `scrub_research` is the
            # DETERMINISTIC one, and returning [] here is what forces the run to
            # depend on it rather than on the model's compliance.
            return _FakeTextResponse("[]")
        if _M_SECTION in prompt:
            self._book("synthesis_section")
            return _FakeTextResponse(self._answer_section())
        if _M_WRAP in prompt:
            self._book("synthesis_wrap")
            return _FakeTextResponse(self._answer_wrap())

        self._book("gemini_unrouted")
        self._unexpected("gemini", prompt)
        return _FakeTextResponse("")

    def _answer_materiality(self, prompt: str) -> str:
        """KEEP everything. The gates' SELECTION quality is a V-02 item (D-02)."""
        return "\n".join(
            f"{idx} | KEEP | KEEP" for idx, _ in _indexed_items(prompt, "\nClaims:\n")
        )

    def _answer_stability(self, prompt: str) -> str:
        return "\n".join(
            f"{idx} | VERIFY" for idx, _ in _indexed_items(prompt, "\nClaims:\n")
        )

    def _answer_tag(self, prompt: str) -> str:
        """One entity for every claim, so the whole run forms ONE blocking key.

        `grouping` blocks by `_norm(entity)` ALONE before it clusters, so a
        contradictory pair can only meet if both sides carry the same entity tag.
        Tagging them apart here would make the shared-session assertion below pass
        or fail on the fake's tagging rather than on D11's reordering.
        """
        return "\n".join(
            f"{idx} | lukoil | benelux_retail"
            for idx, _ in _indexed_items(prompt, "\nClaims:\n")
        )

    def _answer_cluster(self, prompt: str) -> str:
        """`INDEX | CLUSTER_ID`, from the scripted map.

        ONE route serves two callers — the cross-provider merge AND the
        workshop's near-duplicate collapse — because both go through
        `grouping._cluster_block` and therefore send the identical template. They
        are told apart by CONTENT, not by a second marker: an item the scripted
        claim map knows gets its scripted cluster, and anything else (i.e. a
        workshop candidate) is its own singleton. Neither is `unexpected` —
        a singleton is a legitimate clustering answer, and recording it as a miss
        would cry wolf on every run.
        """
        lines: list[str] = []
        next_singleton = 1000
        for idx, body in _indexed_items(prompt, "\nClaims:\n"):
            cid = _CLUSTER_BY_KEY.get(body)
            if cid is None:
                cid = next_singleton
                next_singleton += 1
            lines.append(f"{idx} | {cid}")
        return "\n".join(lines)

    def _answer_critique(self, prompt: str) -> str:
        return "\n".join(
            f"{idx} | KEEP | -" for idx, _ in _indexed_items(prompt, "\nQuestions:\n")
        )

    def _answer_tournament(self, prompt: str) -> str:
        """Always pick side A. WHICH question wins is a V-02 judgement (D-02)."""
        return "\n".join(
            f"{idx} | A" for idx, _ in _indexed_items(prompt, "\nMatches:\n")
        )

    def _answer_distiller(self) -> str:
        """`FACET<TAB>CLAIM_TEXT<TAB>EVIDENCE`, the distiller's own line format.

        The facet MUST be a real focus-area label — `_parse_distiller_response`
        validates it against the labels the prompt listed, and an unmatched facet
        silently falls back to the provider name, which would make the
        stakes-propagation join miss.

        The two claims are the SAME two the factless stream states in prose, so
        the contradictory pair still meets at the merge even when one side of it
        arrived through the fallback rather than through a fact list. That is the
        point of D-14: a fallback degrades ONE STREAM's metadata, not the run's
        ability to catch a contradiction.
        """
        return "\n".join([
            "\t".join([_CLIENT_QUESTION, _FACT_CARLYLE, _FACT_CARLYLE]),
            "\t".join([_CLIENT_QUESTION, _FACT_MARGIN, _FACT_MARGIN]),
        ])

    def _answer_section(self) -> str:
        """One report section, carrying real markdown links and ONE anchor.

        The `[[c:...]]` anchor is deliberate and load-bearing. This run has no
        database, so the citation ledger is empty and NO anchor can resolve —
        which means `apply_citation_anchors` must strip this one and count it.
        That turns "no [[c: token survives into the report" from a vacuous
        assertion (nothing emitted one) into a real proof that the post-pass ran.
        """
        return (
            f"## {_CLIENT_QUESTION}\n\n"
            f"{_FACT_SHARE} [[c:deadbeef]]\n\n"
            f"{_FACT_CORROBORATED}\n\n"
            f"{_FACT_GUNVOR}\n\n"
            f"{_FACT_MARGIN}\n\n"
            f"See [economie.fgov.be]({_URL_OFFICIAL_BE}) and "
            f"[tijd.be]({_URL_PRESS_BENELUX}).\n"
        )

    def _answer_wrap(self) -> str:
        return (
            "## Executive Summary\n\n"
            "LUKOIL's Benelux position shrank through 2026.\n\n"
            "## Cross-cutting Synthesis\n\n"
            "Volume decline and divestment reinforce each other.\n\n"
            "## Decision Framework\n\n"
            "Re-price the Benelux exposure before the next quarter.\n\n"
            "## Confidence & Gaps\n\n"
            "STRONG: market sizing. LIMITED: ownership. OPEN: Luxembourg.\n"
        )

    # -- the Anthropic surface ----------------------------------------------

    async def anthropic_messages(self, *, run_id, tenant_id, model, **kwargs):
        self.models.append(model)
        self._fill_audit_out(kwargs.get("audit_out"))
        tool_names = {
            str((t or {}).get("name") or "") for t in (kwargs.get("tools") or [])
        }
        prompt = _anthropic_prompt_text(kwargs)

        # ROUTED ON THE TOOL LIST, not on prompt text, wherever a client tool
        # exists: the tool list is engine-authored and nothing a provider or a
        # client brief says can change it.
        if "emit_orientation" in tool_names:
            self._book("workshop_orientation")
            return _FakeMessage([_FakeToolUseBlock("emit_orientation", _ORIENTATION_INPUT)])
        if "emit_group_verdict" in tool_names:
            self._book("group_skeptic")
            block_texts = _group_block_texts(prompt)
            self.group_claim_blocks.append(block_texts)
            return _FakeMessage(
                [_FakeToolUseBlock("emit_group_verdict", self._group_verdict(block_texts))]
            )
        if "emit_fact_list" in tool_names:
            return self._own_researcher_turn()
        if "emit_verdict" in tool_names:
            # The per-claim skeptic, reached only through the coverage-gate
            # re-entry. A clean run never gets here; booked rather than refused so
            # a run that DOES reach it is visible in the counters.
            self._book("per_claim_skeptic")
            return _FakeMessage(
                [_FakeToolUseBlock("emit_verdict", {
                    "verdict": "support", "confidence": 0.8, "evidence_refs": [_URL_OFFICIAL_BE],
                })]
            )

        if _M_CANDIDATES in prompt:
            self._book("workshop_candidates")
            return _FakeMessage(
                [_FakeTextBlock(self._answer_candidates())], stop_reason="end_turn"
            )
        if _M_EVOLVE in prompt:
            self._book("workshop_evolve")
            return _FakeMessage(
                [_FakeTextBlock(self._answer_evolve(prompt))], stop_reason="end_turn"
            )

        self._book("anthropic_unrouted")
        self._unexpected("anthropic", prompt)
        return _FakeMessage([], stop_reason="end_turn")

    def _answer_candidates(self) -> str:
        lines = [_workshop_mod._CANDIDATES_START]
        lines += [f"CANDIDATE: {text} | PARENT: {_CLIENT_QUESTION}" for text in _CANDIDATES]
        lines.append(_workshop_mod._CANDIDATES_END)
        return "\n".join(lines)

    def _answer_evolve(self, prompt: str) -> str:
        """Echo each winner unchanged inside the fence, with a language tag.

        Echoing rather than rewriting is deliberate: whether the evolve step
        SHARPENS a question well is a V-02 judgement, and a rewrite here would
        only prove that the fake can write.
        """
        lines = [_rank_mod._WINNERS_START]
        for idx, body in _indexed_items(prompt, "\nQuestions:\n"):
            lines.append(f"{idx} | {body} | LANGS: nl,en")
        lines.append(_rank_mod._WINNERS_END)
        return "\n".join(lines)

    def _group_verdict(self, block_texts: list[str]) -> dict:
        """A per-claim verdict for every member of the group, plus a reconciliation.

        Three shapes, chosen by which scripted claim texts are in the block:

          * the CONTRADICTORY pair -> `disputed: true` with a note, index 0
            supported and index 1 REFUTED with an independent source. One refute
            of one verdict is a majority under the locked `majority-independent`
            rule, so that claim is dropped, `scrub_research` runs on real input
            and the D-08 "Contradictions settled" subgroup renders.
          * the corroborated fact  -> `superseded` with a note, so the D-08
            "Findings overtaken by newer information" subgroup renders too.
          * everything else        -> supported.
        """
        joined = "\n".join(block_texts)
        n = max(1, len(block_texts))

        if _FACT_GUNVOR in joined and _FACT_CARLYLE in joined:
            verdicts = []
            for i, text in enumerate(block_texts):
                if text.strip() == _FACT_CARLYLE:
                    verdicts.append({
                        "claim_index": i, "verdict": "refute", "confidence": 0.9,
                    })
                else:
                    verdicts.append({
                        "claim_index": i, "verdict": "support", "confidence": 0.9,
                    })
            return {
                "verdicts": verdicts,
                "evidence_refs": [_URL_PRESS_GUNVOR],
                "reconciliation": {
                    "disputed": True,
                    "relation": "disputed",
                    "note": (
                        "Two research streams named different buyers for the same "
                        "assets; the Gunvor transaction is the one an independent "
                        "source confirms."
                    ),
                    "canonical": _FACT_GUNVOR,
                },
            }

        if _FACT_CORROBORATED in joined:
            return {
                "verdicts": [{
                    "claim_index": i, "verdict": "superseded", "confidence": 0.7,
                    "superseded_note": (
                        "The EUR 38 billion figure was correct for 2025; the 2026 "
                        "revision published in March puts it at EUR 36 billion."
                    ),
                } for i in range(n)],
                "evidence_refs": [_URL_PRESS_BENELUX],
                "reconciliation": {
                    "disputed": False, "relation": "agree", "note": "", "canonical": "",
                },
            }

        return {
            "verdicts": [
                {"claim_index": i, "verdict": "support", "confidence": 0.8}
                for i in range(n)
            ],
            "evidence_refs": [_URL_OFFICIAL_BE],
            "reconciliation": {
                "disputed": False,
                "relation": "single" if n == 1 else "agree",
                "note": "", "canonical": "",
            },
        }

    def _own_researcher_turn(self):
        """Turn 1 asks for a web search; turn 2 emits the fact list.

        Two turns rather than one on purpose: a single-turn script would never
        reach `_run_one_search`, and the "the real `serpapi.search` was never
        entered" assertion would then be vacuous — it would hold because nothing
        searched at all, not because the seam held.
        """
        self._own_turns += 1
        if self._own_turns == 1:
            self._book("own_research_search")
            return _FakeMessage([_FakeToolUseBlock("serpapi_search", {
                "q": "LUKOIL filling stations Benelux 2026", "hl": "nl", "gl": "be", "num": 5,
            })])
        self._book("own_research_facts")
        return _FakeMessage([_FakeToolUseBlock("emit_fact_list", _OWN_TOOL_INPUT)])

    # -- the deep-research / search / audit surface -------------------------

    async def gemini_deep_research_raw(self, query, **kwargs) -> dict:
        self._book("deep_research_gemini")
        return {"status": "success", "report": self._third_party_report("gemini", _GEMINI_REPORT)}

    async def openai_deep_research_raw(self, query, **kwargs) -> dict:
        self._book("deep_research_openai")
        return {"status": "success", "report": self._third_party_report("openai", _OPENAI_REPORT)}

    def _third_party_report(self, provider: str, report: str) -> str:
        """Hook the Task-2 subclass overrides to strip a stream's fact block."""
        return report

    async def serpapi_search(self, *, run_id, tenant_id, q, hl, gl, num, plan=None):
        self._book("serpapi_search")
        self.serpapi_searches.append({"q": q, "hl": hl, "gl": gl, "num": num})
        return {
            "results": [{
                "title": "Benelux station count 2026",
                "url": _URL_OWN,
                "snippet": _FACT_OWN,
            }],
            "billable": True,
            "cost_usd": "0.0050",
        }

    async def start_call(self, *, run_id, tenant_id, provider, model, request):
        self.start_calls.append({
            "run_id": run_id, "tenant_id": tenant_id,
            "provider": provider, "model": model, "request": request,
        })
        return _FakeHandle(run_id, tenant_id, provider, model)

    async def end_call(self, handle, *, response, status):
        self.end_calls.append({
            "handle": handle, "response": response, "status": status,
            "provider": handle.provider,
        })

    async def write_failure(self, *, run_id, tenant_id, provider, error):
        self.failures.append({
            "run_id": run_id, "tenant_id": tenant_id,
            "provider": provider, "error": error,
        })


#: The two literals `group_skeptic.run_group_skeptic` uses to fence its claim
#: block. Read from the prompt HEADER, so no claim's own text can move the fence.
_GROUP_CLAIMS_HEADER = "CLAIMS TO EVALUATE"
_GROUP_SOURCES_HEADER = "PRIOR SOURCES"
_GROUP_LINE_RE = re.compile(r"^\[(\d+)\]\s+(.*)$")


def _group_block_texts(prompt: str) -> list[str]:
    """The `[i] text` claim lines of ONE group-skeptic prompt, in index order.

    Bounded to the region BETWEEN the two headers. The prior-sources block that
    follows is built from the research prose and quotes every scripted fact
    verbatim, so an unbounded scan would find every claim in every session.
    """
    _, _, tail = prompt.partition(_GROUP_CLAIMS_HEADER)
    body, _, _ = tail.partition(_GROUP_SOURCES_HEADER)
    out: list[str] = []
    for line in body.splitlines():
        match = _GROUP_LINE_RE.match(line.strip())
        if match:
            out.append(match.group(2).strip())
    return out


#: A report that IGNORED the D8 instruction: prose, then a plain numbered
#: markdown source list, and no FACTS_START anywhere. That is precisely the shape
#: every deep-research provider produced in the recorded 4cbb5311 run, i.e. the
#: shape D-14's fallback exists for.
_CLAUDE_PROSE_ONLY_REPORT = "\n".join([
    "## Findings",
    "",
    f"- {_FACT_CARLYLE}",
    f"- {_FACT_MARGIN}",
    "",
    "## Sources",
    "",
    f"1. [bloomberg.com]({_URL_PRESS_CARLYLE})",
    f"2. [cbs.nl]({_URL_OFFICIAL_NL})",
])


class _LostStreamProvidersAudited(_ScriptedProvidersAudited):
    """The same run, with ONE third-party stream returning no fact list at all.

    A thin subclass overriding exactly one hook, in the shape
    `test_gate_replay.py`'s `_OutageAnswerKeyGateAudited` uses: everything else —
    the workshop, the merge, the gates, the skeptic, the report — is inherited
    unchanged, so any difference in the outcome is attributable to the one thing
    that changed.
    """

    #: Which stream ignores the D8 instruction. Named rather than hard-coded into
    #: the override so the assertion can quote it.
    FACTLESS_PROVIDER = "claude"

    def _third_party_report(self, provider: str, report: str) -> str:
        if provider != self.FACTLESS_PROVIDER:
            return report
        if provider not in self.factless_providers:
            self.factless_providers.append(provider)
        return _CLAUDE_PROSE_ONLY_REPORT


def _anthropic_prompt_text(kwargs: dict) -> str:
    """Flatten a messages payload plus the system prompt into one string.

    Exactly what the provider would have received, so a prompt assertion is an
    assertion about the real payload rather than about a reconstruction.
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


# ===========================================================================
# The no-database session.
# ===========================================================================


class _FakeRow(tuple):
    """A result row that answers both `row[0]` and `row.id`."""

    def __new__(cls, value):
        return super().__new__(cls, (value,))

    @property
    def id(self):
        return self[0]


class _FakeGapRow(tuple):
    """A `research_gap` row as `_read_research_gaps` reads it: `row[0]`, `row[1]`."""

    def __new__(cls, provider: str, text: str):
        return super().__new__(cls, (provider, text))


class _FakeResult:
    """The narrow result surface the engine's raw-SQL callers use."""

    def __init__(self, rows: Optional[list] = None) -> None:
        self._rows = list(rows or [])

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def scalar(self):
        return None

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _NoDbSession:
    """Records every statement a production writer executes; opens no socket.

    Modelled on `test_gate_replay.py:777-802`, widened just enough for the
    persistence path. The ROUTING matters and is not decoration: `_read_output`
    reads `SELECT body FROM output` and takes the resume-from-cache short-circuit
    the moment it gets a row, while `_upsert_source` RAISES if its
    `INSERT ... RETURNING id` yields nothing and the follow-up SELECT also yields
    nothing. One blanket answer cannot satisfy both, so each statement gets the
    answer a real database would give for a run with no prior rows.

    ONE THING IS ECHOED RATHER THAN LEFT EMPTY: `research_gap`. 15.2-06's "What
    we could not establish" section deliberately does NOT take a hand-off through
    the synthesis bundle — it re-reads the table, so the section also works on
    the interactive-resume path. Stage 7 writes those rows and
    `_write_final_report` reads them back a moment later, so a real database
    WOULD return them. Answering the SELECT with `[]` would not be a simpler
    fake, it would be an UNFAITHFUL one: the section would render its "no
    provider reported a research gap" placeholder and this file would assert
    that a real, stated gap is correctly omitted.
    """

    def __init__(self, log: list[tuple[str, Any]], gaps: list[tuple[str, str]]) -> None:
        self._log = log
        self._gaps = gaps

    def begin(self):
        return _NoDbTxn()

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        self._log.append((sql, params))
        if "INSERT INTO research_gap" in sql and isinstance(params, dict):
            self._gaps.append((str(params.get("provider") or ""), str(params.get("text") or "")))
            return _FakeResult([])
        if "FROM research_gap" in sql and sql.strip().upper().startswith("SELECT"):
            # `ORDER BY provider ASC, created_at ASC, id ASC` — the ordering is
            # load-bearing for D-08's byte-stability, so the echo reproduces it.
            ordered = sorted(self._gaps, key=lambda row: row[0])
            return _FakeResult([_FakeGapRow(p, t) for p, t in ordered])
        if "INSERT INTO source" in sql and "RETURNING id" in sql:
            # A fresh row: the INSERT wins the conflict check and returns its id.
            return _FakeResult([_FakeRow(uuid.uuid4())])
        return _FakeResult([])

    # The ORM surface. Nothing in the tribunal write path uses it today, but a
    # future writer that does must fail on an assertion, not on an AttributeError
    # swallowed by the caller's `except`.
    def add(self, obj) -> None:
        self._log.append(("ORM_ADD", obj))

    async def flush(self) -> None:
        return None

    async def refresh(self, obj) -> None:
        return None


class _NoDbTxn:
    async def __aenter__(self):
        return None

    async def __aexit__(self, *args):
        return False


class _NoDbSessionCtx:
    def __init__(self, log: list[tuple[str, Any]], gaps: list[tuple[str, str]]) -> None:
        self._log = log
        self._gaps = gaps

    async def __aenter__(self):
        return _NoDbSession(self._log, self._gaps)

    async def __aexit__(self, *args):
        return False


def _no_db_sessionmaker(log: list[tuple[str, Any]]):
    """One statement log and one `research_gap` store, shared by every session.

    A run opens a new session per write; the store has to outlive them, exactly
    as a table does.
    """
    gaps: list[tuple[str, str]] = []

    def get_sessionmaker(*args, **kwargs):
        def factory():
            return _NoDbSessionCtx(log, gaps)
        return factory
    return get_sessionmaker


# ===========================================================================
# The run driver.
# ===========================================================================


async def _engine_run(audited, *, monkeypatch, serpapi_key: Optional[str] = "scripted-key"):
    """Drive the real pipeline against `audited`. Returns (result, statements).

    EVERY SEAM THIS INSTALLS, AND WHAT IS THEREFORE NOT UNDER TEST:

    | Seam                                   | Not under test                        |
    |----------------------------------------|---------------------------------------|
    | `TribunalPipeline(audited=...)`         | the real `AuditedLLMClient`: its audit |
    |  (a PRODUCTION constructor parameter)   | row writing, hash chain and GCS upload |
    | `db.base.get_sessionmaker` +            | Postgres itself: RLS enforcement, the  |
    |  `pipeline.get_sessionmaker`            | ARRAY(Text) bind round-trip, real SQL  |
    | `degraded_parallel.ALLOW_DEEP_RESEARCH_*`| provider enable/disable via env       |
    | `claude_adapter.legacy_claude_deep_research` | the legacy Claude researcher     |
    | `serpapi.fetch_plan` / `serpapi.search` | the SerpApi HTTP client and its prices |
    | `budget.TRIBUNAL_UNCAPPED`              | the budget governor's SELECT sum()     |
    | tournament rounds / max winners         | tournament CONVERGENCE at real sizes   |

    The knobs below are set as MODULE ATTRIBUTES, not environment variables, and
    that is not a style choice: every one of them is resolved at IMPORT time
    (`os.environ.get(...)` at module scope), so `monkeypatch.setenv` after import
    would silently do nothing — the exact false-green this phase keeps catching.
    """
    statements: list[tuple[str, Any]] = []
    sessionmaker = _no_db_sessionmaker(statements)

    # BOTH bindings. `runs.stages`, `pipeline._read_output`, `pipeline._write_output`
    # and `serpapi.record_plan_for_run` import it lazily from `db.base`; `pipeline`
    # binds it at MODULE level and uses it un-guarded in the verify stage.
    monkeypatch.setattr(
        "nestor_pulse_sdk.db.base.get_sessionmaker", sessionmaker, raising=True
    )
    monkeypatch.setattr(_pipeline_mod, "get_sessionmaker", sessionmaker, raising=True)

    # All four peer research streams enabled.
    monkeypatch.setattr(_degraded_mod, "ALLOW_DEEP_RESEARCH_GEMINI", True)
    monkeypatch.setattr(_degraded_mod, "ALLOW_DEEP_RESEARCH_CLAUDE", True)
    monkeypatch.setattr(_degraded_mod, "ALLOW_DEEP_RESEARCH_OPENAI", True)
    monkeypatch.setattr(_degraded_mod, "ALLOW_DEEP_RESEARCH_OWN", True)

    # The Claude stream is the one provider that does NOT go through an `audited`
    # method — `claude_adapter` calls the legacy researcher directly — so its
    # seam is the module function, and the fake still books the call.
    from nestor_pulse_sdk.tools import claude_adapter

    async def _claude(query):
        audited._book("deep_research_claude")
        return {
            "status": "success",
            "report": audited._third_party_report("claude", _CLAUDE_REPORT),
        }

    monkeypatch.setattr(claude_adapter, "legacy_claude_deep_research", _claude)

    # The own-researcher's SerpApi seam. `fetch_plan` is an HTTP call; `search` is
    # the real HTTP client, replaced by a tripwire because production reaches the
    # endpoint through `audited.serpapi_search` and NOTHING should enter this.
    if serpapi_key is None:
        monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    else:
        monkeypatch.setenv("SERPAPI_API_KEY", serpapi_key)
    _serpapi_mod.reset_breaker()

    async def _fetch_plan(*args, **kwargs):
        # `unknown()` is production's own honest "the plan could not be
        # established" value. It is the right shape here: this run has no
        # account, and inventing a unit price would put a guessed number into
        # the cost path (D-16 forbids exactly that).
        return _serpapi_mod.SerpApiPlan.unknown()

    async def _tripwire_search(*args, **kwargs):
        raise AssertionError(
            "serpapi.search was entered — the own-researcher must reach the "
            "endpoint through audited.serpapi_search, which the fake serves. A "
            "live HTTP call from CI costs money and leaks the key into the log."
        )

    monkeypatch.setattr(_serpapi_mod, "fetch_plan", _fetch_plan)
    monkeypatch.setattr(_serpapi_mod, "search", _tripwire_search)

    # Keep the run small and DETERMINISTIC. Each value is set explicitly rather
    # than inherited, so a future default change cannot silently make this test
    # slower or differently shaped.
    monkeypatch.setattr(_rank_mod, "_TOURNAMENT_ROUNDS", 1)
    monkeypatch.setattr(_rank_mod, "_RANK_BACKOFF_S", 0.0)
    monkeypatch.setattr(_workshop_mod, "_CANDIDATES_PER_QUESTION", len(_CANDIDATES))
    # ONE winner -> one corroboration group -> exactly one angle per stream, so
    # all four streams run and each contributes its own scripted report once.
    monkeypatch.setattr(_division_mod, "_D6_MAX_WINNERS", 1)
    monkeypatch.setattr(_budget_mod, "TRIBUNAL_UNCAPPED", True)
    monkeypatch.setattr(_gates_mod, "_GATE_BACKOFF_S", 0.0)

    pipeline = TribunalPipeline(audited=audited)
    result = await pipeline.run(
        brief=_BRIEF, run_id=uuid.uuid4(), tenant_id=uuid.uuid4()
    )
    return result, statements


# --- readers over the captured statements ----------------------------------

_STAGE_UPDATE = "UPDATE run SET current_stage"


def _stage_sequence(statements: list[tuple[str, Any]]) -> list[str]:
    """The stage keys the run reported, in execution order.

    Decoded from the BOUND PARAMETER of every `set_stage` UPDATE rather than
    from a log line, so this is what the database would have been told.
    """
    out: list[str] = []
    for sql, params in statements:
        if _STAGE_UPDATE in sql and isinstance(params, dict) and params.get("stage"):
            out.append(str(params["stage"]))
    return out


def _claim_inserts(statements: list[tuple[str, Any]]) -> list[dict]:
    """The bound parameters of every `INSERT INTO claim` the run executed.

    Stage 7 SWALLOWS persistence errors by design (`pipeline.py`'s
    `except Exception` around `persist_tribunal_claims`), so a persistence bug is
    SILENT. Asserting on the recorded statements — rather than on "nothing
    raised" — is the only way to prove the write actually happened.
    """
    return [
        params for sql, params in statements
        if sql.startswith("INSERT INTO claim ") and isinstance(params, dict)
    ]


def _research_gap_inserts(statements: list[tuple[str, Any]]) -> list[dict]:
    return [
        params for sql, params in statements
        if "INSERT INTO research_gap" in sql and isinstance(params, dict)
    ]


def _output_body(statements: list[tuple[str, Any]], fmt: str) -> Optional[dict]:
    """The JSON body of the LAST `Output(format=fmt)` row the run wrote.

    This is how the scrubbed research becomes OBSERVABLE. `cleaned_reports` never
    reaches the returned result — it is consumed by synthesis and then only the
    prose the model wrote comes back — so asserting on the delivered report would
    prove nothing about whether the scrub ran: the report simply never quotes the
    discredited sentence. The `synthesis_cache` row is the real artefact, and it
    is the same row a "Rewrite report" would replay from.
    """
    import json

    bodies = [
        params["body"] for sql, params in statements
        if "INSERT INTO output" in sql
        and isinstance(params, dict) and params.get("fmt") == fmt
    ]
    if not bodies:
        return None
    try:
        return json.loads(bodies[-1])
    except Exception:  # noqa: BLE001 — an unparseable body is a real failure
        return None


def _stage_detail_entries(statements: list[tuple[str, Any]], stage_key: str) -> list[str]:
    """The raw `:entry` JSON of every `set_stage` write for one stage key."""
    return [
        str(params["entry"])
        for sql, params in statements
        if _STAGE_UPDATE in sql
        and isinstance(params, dict)
        and params.get("stage") == stage_key
        and params.get("entry")
    ]


def _terminal_state_of(result: dict) -> str:
    """`terminal_state()` fed the run's OWN D-17 facts, exactly as the worker does."""
    return terminal_state(**result["terminal_inputs"])


# ===========================================================================
# 1. THE D-02 GATE — the clean four-stream run
# ===========================================================================


async def test_clean_four_stream_run_completes_end_to_end(monkeypatch):
    """Workshop -> dispatch -> fact lists -> merge -> gates -> verify -> report.

    Every assertion below names what breaks in PRODUCTION if it fires, because a
    diff of two values tells a reader nothing about whether to ship.
    """
    audited = _ScriptedProvidersAudited()
    result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert not audited.unexpected, (
        "the pipeline sent a prompt this file does not recognise, so some stage "
        "was answered with an EMPTY response and whatever it did next was driven "
        "by a parser fallback rather than by the engine: "
        f"{audited.unexpected}"
    )

    # -- the report ---------------------------------------------------------
    text = result.get("output_text") or ""
    assert text.strip(), (
        "the run produced no report body — every stage may have 'succeeded' while "
        "the deliverable is empty, which is exactly the silent-green class this "
        "phase exists to close"
    )
    for heading in (_DISPUTED_H, _COULD_NOT_H, _VERIFICATION_H, _SOURCES_H):
        assert heading in text, (
            f"the report is missing {heading!r}. These sections are rendered by "
            f"PYTHON after synthesis precisely so the writing model cannot omit "
            f"them; a missing one means the append site itself is unwired."
        )
    assert text.index(_DISPUTED_H) < text.index(_COULD_NOT_H) < text.index(_VERIFICATION_H), (
        "D-08's two deterministic sections must both precede the verification "
        f"appendix. Order found: disputed@{text.index(_DISPUTED_H)}, "
        f"could-not@{text.index(_COULD_NOT_H)}, verification@{text.index(_VERIFICATION_H)}"
    )

    # The three subgroups the scripted run genuinely produced. Each is driven by
    # a different upstream mechanism, so together they prove three hand-offs.
    assert _SUB_CONTRADICTIONS in text, (
        "the group skeptic reported a DISPUTED reconciliation and the report does "
        "not show it — the reconciliation never reached `report_sections`, so a "
        "settled contradiction ships invisibly"
    )
    assert _SUB_SUPERSEDED in text, (
        "a `superseded` verdict carried a note and the report does not show it — "
        "CR-01/G-07's caveat died between the verdict and the section again"
    )
    assert _SUB_BRIEF in text, (
        "the workshop orientation flagged a brief-vs-world conflict and the "
        "report does not show it — D4's `brief_conflicts` are not reaching the "
        "renderer"
    )
    for line in _NOT_FOUND_CLAUDE + _NOT_FOUND_OWN:
        assert line in text, (
            "a provider said out loud that it could not establish something and "
            f"the report does not repeat it: {line!r}. The `research_gap` rows "
            "are the only record of an absent fact; losing them turns a stated "
            "gap into a silent omission."
        )

    # -- citations ----------------------------------------------------------
    assert "[[c:" not in text, (
        "a raw citation anchor survived into the delivered report. The post-pass "
        "either did not run or ran before synthesis; either way the client sees "
        "engine internals in a document they are handed."
    )
    assert result["unresolved_anchors"] == 1, (
        "the scripted section emitted exactly one anchor and this run has no "
        "claim rows for it to resolve against, so exactly one anchor must be "
        f"COUNTED as removed. Got {result['unresolved_anchors']} — if it is 0 the "
        "post-pass silently dropped the token without booking the loss, which is "
        "how an uncited sentence starts looking cited."
    )
    assert result["verification_summary"]["unresolved_anchors"] == 1, (
        "the funnel and the top-level key disagree about one number — the CR-02 "
        "failure mode of two surfaces publishing different values for one thing"
    )
    assert result["model_invented_numbers"] == 0, (
        "the writing model emitted a bare bracketed number that resolves to "
        "nothing in the Sources list"
    )
    for url in (_URL_OFFICIAL_BE, _URL_PRESS_BENELUX):
        assert url in text.split(_SOURCES_H, 1)[1], (
            f"{url} is linked in the body but absent from the Sources list — the "
            f"reader cannot follow a reference the report itself used"
        )

    # -- the funnel ---------------------------------------------------------
    funnel = result["verification_summary"]
    for key in ("distilled", "kept", "dropped", "selected_verify", "skipped_stable",
                "checked", "should_have_been_checked", "checked_incidentally",
                "unresolved_anchors", "degradation_reasons", "verification_degraded"):
        assert key in funnel, (
            f"the funnel is missing {key!r}; a consumer that reads it would have "
            f"to branch on which pipeline path produced the run (Pitfall 10)"
        )
    assert funnel["distilled"] > 0, (
        "no claim reached the gates. Either the D8 fact blocks did not parse or "
        "the merge dropped everything — in both cases the run would ship an "
        "unverified report while reporting a clean funnel."
    )

    # The arithmetic, asserted THROUGH the production shaper rather than
    # re-derived here: `verification/report.py::_accounting` owns the bucket-2
    # expression (and its `checked_incidentally` subtraction), and a second copy
    # of it in a test is a second thing to drift.
    report = shape_verification_report(
        verdict_rows=[], funnel=funnel, claim_count=funnel["distilled"],
        cost_usd_total=None, cost_pending=False,
    )
    accounting = report["accounting"]
    assert accounting is not None, (
        "a gated run produced no accounting block — the operator's report would "
        "read 'no gate data' for a run that WAS gated"
    )
    total = (
        accounting["checked"]
        + accounting["checked_incidentally"]["total"]
        + accounting["not_checkable"]["total"]
        + accounting["should_have_been_checked"]
    )
    assert total == funnel["distilled"], (
        f"one-claim-one-bucket is broken: the buckets account for {total} of "
        f"{funnel['distilled']} claims, so some claims fell between them and "
        f"nobody can say what happened to them. {accounting}"
    )
    assert accounting["should_have_been_checked"] == 0, (
        "a run where every selected claim came back with a verdict reported a "
        "non-empty bucket 3 — the phase's most important number is crying wolf"
    )

    # -- the terminal state -------------------------------------------------
    assert funnel["degradation_reasons"] == [], (
        f"a clean run named a degradation: {funnel['degradation_reasons']}. A "
        f"marker that is always on is a marker the operator learns to ignore."
    )
    assert _terminal_state_of(result) == "completed", (
        f"terminal_state() on this run's own D-17 facts returned "
        f"{_terminal_state_of(result)!r}; the worker would persist that status. "
        f"inputs={result['terminal_inputs']}"
    )

    # -- the stage sequence -------------------------------------------------
    stages = _stage_sequence(statements)
    assert stages, "no stage was ever reported — the operator watches a dead feed"
    observed = set(stages)
    expected = {
        "workshop", "intake", "research_division", "deep_research", "distill",
        "merge", "gate", "verify", "adjudicate", "coverage", "conflict",
        "synthesize", "done",
    }
    assert expected <= observed, (
        f"the run never reported these stages: {sorted(expected - observed)}. A "
        f"stage that reports nothing is a stage the operator cannot see fail."
    )
    assert stages[-1] == "done", f"the run did not close on 'done': {stages[-5:]}"

    # WR-03, restated at RUN level: 15.2-03 declared the schema, and a key the
    # run reports that the schema never declared renders as a bare unlabelled
    # key in the UI and is omitted from RunMetrics.stages.
    undeclared = observed - _DECLARED_STAGE_KEYS
    assert not undeclared, (
        f"the run reported stage key(s) {sorted(undeclared)} that "
        f"ENGINE_STAGES['tribunal'] does not declare — the UI would render the "
        f"raw key with no label"
    )

    # D9/D11, THE REORDERING THIS PHASE IS FOR.
    assert stages.index("merge") < stages.index("gate"), (
        "the gates ran before the cross-provider merge. That is the pre-15.2 "
        "order, and it is exactly how run 4cbb5311 published Aral's share at both "
        "16% and 21%: two streams' contradicting claims were gated and checked as "
        "unrelated claims, each found its own supporting source, and both passed."
    )

    # -- provenance survives to persistence ---------------------------------
    inserts = _claim_inserts(statements)
    assert inserts, (
        "no claim row was written. Stage 7 swallows persistence errors BY DESIGN, "
        "so this failure is silent in production: the recall mechanism would be "
        "empty and nothing in the run would say so."
    )
    by_text = {p["text"]: p for p in inserts}
    assert _FACT_CORROBORATED in by_text, (
        "the fact two streams independently stated never reached persistence"
    )
    assert sorted(by_text[_FACT_CORROBORATED]["found_by"]) == ["gemini", "openai"], (
        "the corroborated fact reached persistence with "
        f"{by_text[_FACT_CORROBORATED]['found_by']!r}. `found_by` IS the "
        "corroboration signal: collapsing two streams' identical statement into "
        "one provider makes an independently confirmed fact indistinguishable "
        "from a single-source one."
    )
    assert by_text[_FACT_SHARE]["found_by"] == ["gemini"], (
        "a single-source fact was credited to more than one stream, which would "
        "overstate the evidence behind it"
    )
    assert by_text[_FACT_SHARE]["certainty"] == "certain", (
        "the provider's own certainty word did not survive the merge to the "
        "claim row (D-13)"
    )
    assert by_text[_FACT_CORROBORATED]["certainty"] == "single", (
        "G-11: when either side of a merge says `single`, the merged claim must "
        "stay `single` — failing toward MORE checking, never less"
    )

    gaps = _research_gap_inserts(statements)
    gap_texts = {p["text"] for p in gaps}
    for line in _NOT_FOUND_CLAUDE + _NOT_FOUND_OWN:
        assert line in gap_texts, (
            f"the provider's own 'could not establish' line was never written to "
            f"research_gap: {line!r}"
        )

    # -- the contradiction reached ONE session ------------------------------
    assert audited.group_claim_blocks, "no group-skeptic session ran at all"
    shared = [
        block for block in audited.group_claim_blocks
        if _FACT_GUNVOR in block and _FACT_CARLYLE in block
    ]
    assert len(shared) == 1, (
        f"the two contradicting claims were shown to {len(shared)} skeptic "
        f"session(s) together; exactly one is required. Two (i.e. one each) is "
        f"the 4cbb5311 defect: each session finds its own supporting source and "
        f"both claims pass. Zero means the merge never put them together at all. "
        f"Blocks seen: {audited.group_claim_blocks}"
    )
    # And they were not merely co-located: the session had to see BOTH and only
    # those two, which is what makes reconciliation possible at all.
    assert sorted(shared[0]) == sorted([_FACT_CARLYLE, _FACT_GUNVOR]), shared[0]
    assert any(c["text"] == _FACT_CARLYLE for c in (result.get("rejected_claims") or [])), (
        "the refuted claim is missing from the rejected-claims ledger, so the "
        "Deep Content Compare cannot show what this engine threw out"
    )

    # -- subtractive verification actually stuck ----------------------------
    # Asserted on the SCRUBBED RESEARCH, not on the delivered report. The report
    # never quotes the discredited sentence anyway (the scripted writer did not
    # write it), so a report-level assertion would pass whether or not the scrub
    # ran. `cleaned_reports` is the input synthesis was actually given.
    bundle = _output_body(statements, "synthesis_cache")
    assert bundle is not None, (
        "no synthesis_cache row was written — a 'Rewrite report' or an "
        "interactive-gate resume would have to re-run the whole paid research"
    )
    cleaned = "\n".join(
        (entry[1] or {}).get("report") or ""
        for entry in (bundle.get("cleaned_reports") or [])
        if isinstance(entry, (list, tuple)) and len(entry) == 2
    )
    assert cleaned.strip(), "the scrubbed research handed to synthesis was empty"
    assert _FACT_CARLYLE not in cleaned, (
        "the passage stating a REFUTED claim survived into the research that "
        "synthesis was written from. Only a refutation scrubs a passage, so a "
        "surviving one ships as written — this is precisely how run 4cbb5311 "
        "published Aral's share at both 16% and 21%."
    )
    assert _FACT_GUNVOR in cleaned, (
        "the scrub removed a SURVIVING claim's passage as well. Over-scrubbing "
        "silently deletes verified findings from the deliverable."
    )


# ===========================================================================
# 2. ZERO LIVE CALLS — asserted, never assumed
# ===========================================================================


async def test_the_stubbed_run_made_no_live_calls(monkeypatch):
    """The fake served every call, and no real client or engine was constructed.

    Asserted rather than assumed, because "the test passed" is compatible with
    "a real client answered and the org was billed".
    """
    from nestor_pulse_sdk.db import base as db_base

    # An earlier test in the same session may have populated the engine cache;
    # clearing it first is what makes the miss count below meaningful.
    db_base.get_engine.cache_clear()

    audited = _ScriptedProvidersAudited()
    result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert type(audited).__module__ == __name__, (
        "the object the pipeline talked to was not defined in this test module — "
        "a real client reached CI, which costs money and, before the cap resets "
        "on 2026-08-01, returns nothing but 400s"
    )
    for attr in ("_a", "_g", "_audit", "_gcs"):
        assert not hasattr(audited, attr), (
            f"the fake carries {attr!r}, an attribute only the real "
            f"AuditedLLMClient has — this file must instantiate no provider client"
        )

    assert audited.unexpected == [], (
        f"unrouted prompt(s), reported by name rather than defaulted away: "
        f"{audited.unexpected}"
    )
    assert audited.routes.get("gemini_unrouted", 0) == 0
    assert audited.routes.get("anthropic_unrouted", 0) == 0

    # Every route the redesigned pipeline MUST have used. Naming them one by one
    # is the point: a stage that silently stopped being called would otherwise
    # leave this test green.
    for route in (
        "workshop_orientation", "workshop_candidates", "workshop_critique",
        "workshop_tournament", "workshop_evolve",
        "deep_research_gemini", "deep_research_openai", "deep_research_claude",
        "own_research_search", "own_research_facts", "serpapi_search",
        "merge_tag", "merge_cluster",
        "gate_materiality", "gate_stability",
        "group_skeptic", "conflict_detector", "scrub_research",
        "synthesis_section", "synthesis_wrap",
    ):
        assert audited.routes.get(route, 0) > 0, (
            f"the {route!r} route was never exercised, so this run did not drive "
            f"the stage it belongs to. Routes seen: {sorted(audited.routes)}"
        )

    assert audited.calls == sum(audited.routes.values()), (
        f"unaccounted provider call: calls={audited.calls}, "
        f"routes sum={sum(audited.routes.values())}"
    )

    assert db_base.get_engine.cache_info().misses == 0, (
        "db.base.get_engine was constructed, so a real TCP connect to Cloud SQL "
        "was attempted. The engine gate provisions no database: a socket here "
        "hangs the fast gate rather than failing it."
    )

    # The SerpApi seam. The real `serpapi.search` is a tripwire that raises, so
    # reaching it would already have failed the run; asserting the SCRIPTED seam
    # recorded traffic is what makes that non-vacuous.
    assert audited.serpapi_searches, (
        "the own-researcher never asked for a search, so 'the real search was "
        "never entered' holds for the wrong reason"
    )

    # Deep-research adapters must still write their audit rows on the stubbed
    # path: a resumed or stubbed call that skips start_call/end_call would leave
    # a hole in the Art. 12 chain.
    assert len(audited.start_calls) == len(audited.end_calls) > 0, (
        f"start_call/end_call are unbalanced: {len(audited.start_calls)} started, "
        f"{len(audited.end_calls)} ended"
    )
    assert audited.failures == [], (
        f"a provider failure was booked on a clean run: {audited.failures}"
    )
    assert result["verification_summary"]["distilled"] > 0
    assert statements, "the run executed no statement at all"

    # D-15 / D-03: the distiller is DEMOTED, not primary. On a run where every
    # stream supplied its own fact list it must not be called at all — a
    # fallback that fires on the healthy path is a paid re-read of data the
    # provider already handed over structured.
    assert audited.routes.get("distiller_fallback", 0) == 0, (
        "the fallback distiller ran on a run where all four streams returned a "
        "usable fact list — D-03's unwiring has come undone and every stream's "
        "prose is being re-shredded at full cost"
    )


# ===========================================================================
# 3. THE DEGRADED RUN — a lost stream, a D-14 fallback, an honest terminal state
# ===========================================================================


async def test_lost_stream_and_fallback_run_completes_degraded(monkeypatch):
    """Two independent losses, one honest deliverable, both named out loud.

    The own-researcher is refused before any call (no search credential) and one
    third-party stream ignores the D8 fact-list instruction. Neither is fatal, so
    D-17's answer is `completed_degraded` — NOT a park, and emphatically not a
    silent `completed`.
    """
    audited = _LostStreamProvidersAudited()
    result, statements = await _engine_run(
        audited, monkeypatch=monkeypatch, serpapi_key=None
    )

    assert not audited.unexpected, f"unrouted prompt(s): {audited.unexpected}"

    # -- it completed, and it did NOT park ----------------------------------
    assert "park" not in result, (
        f"the run PARKED. Two losses that each still permit an honest deliverable "
        f"are D-17's `completed_degraded`; parking them puts a Resume button in "
        f"front of an operator whose report is already finished. {result.get('park')}"
    )
    text = result.get("output_text") or ""
    assert text.strip(), "a degraded run must still ship a report, not an empty one"
    for heading in (_DISPUTED_H, _COULD_NOT_H, _VERIFICATION_H):
        assert heading in text, f"the degraded report is missing {heading!r}"

    assert _terminal_state_of(result) == "completed_degraded", (
        f"terminal_state() returned {_terminal_state_of(result)!r} on a run that "
        f"lost one of four research streams. `completed` would hide the loss; "
        f"`parked` would overstate it. inputs={result['terminal_inputs']}"
    )
    assert result["terminal_inputs"]["streams_lost"] == 1, (
        f"exactly one stream (the own-researcher) should be recorded as lost: "
        f"{result['terminal_inputs']}"
    )

    # -- the loss is stated in WORDS a human reads --------------------------
    reasons = result["verification_summary"]["degradation_reasons"]
    assert reasons, (
        "the run degraded and named no reason. `terminal_state` degrades anyway "
        "and logs the inconsistency, but the operator is told a run is degraded "
        "with nothing to act on — the alarm without the cause."
    )
    # The availability PROBE returns the machine-readable code; the operator
    # surface returns a SENTENCE. Both are asserted, because the plan's
    # expectation that the literal code reaches `degradation_reasons` is not what
    # the merged tree does — and must not be, per T-15.2-65 (a reason string may
    # never quote the credential, its variable name or the endpoint URL).
    assert _serpapi_mod.unavailable_reason() == _serpapi_mod.REASON_KEY_MISSING, (
        "with no credential the availability probe must refuse the stream BEFORE "
        "any call — zero HTTP, zero LLM, zero spend"
    )
    stream_loss = [
        r for r in reasons if "three streams instead of four" in r
    ]
    assert stream_loss, (
        f"no reason names the lost research stream in plain words: {reasons}"
    )
    assert len(stream_loss[0]) > 40, (
        f"the degradation reason must be a sentence a human reads, not a code: "
        f"{stream_loss[0]!r}"
    )
    assert audited.routes.get("serpapi_search", 0) == 0, (
        "the own-researcher searched despite having no credential — the refusal "
        "must happen BEFORE any call is made"
    )
    assert audited.routes.get("own_research_facts", 0) == 0, (
        "the refused stream still ran its model loop, which is spend on a stream "
        "that cannot produce evidence"
    )

    # -- the D-14 fallback is surfaced, and is NOT a degradation ------------
    assert audited.factless_providers == [_LostStreamProvidersAudited.FACTLESS_PROVIDER], (
        f"the scripted factless stream never fired: {audited.factless_providers}"
    )
    assert audited.routes.get("distiller_fallback", 0) == 1, (
        f"the stream that returned no fact list was not distilled "
        f"({audited.routes.get('distiller_fallback', 0)} call(s)) — its whole "
        f"report would contribute nothing and the loss would be silent"
    )
    bundle = _output_body(statements, "synthesis_cache")
    assert bundle is not None, "no synthesis_cache row was written"
    fallbacks = (bundle.get("verification") or {}).get("factlist_fallbacks") or []
    assert len(fallbacks) == 1, (
        f"the fallback is not recorded on the surface an operator reads: {fallbacks}"
    )
    entry = fallbacks[0]
    assert entry["provider"] == _LostStreamProvidersAudited.FACTLESS_PROVIDER
    note = entry.get("note") or ""
    assert len(note) > 40 and entry["provider"] in note, (
        f"the fallback note must be a sentence naming the provider, not a code: "
        f"{note!r}"
    )
    # THE THREE-WAY VOCABULARY. A distiller fallback degrades ONE STREAM, not the
    # run (D-14): the provider's research still reached the merge in full. Letting
    # it into `degradation_reasons` would mean nearly every real run is degraded,
    # which drains `completed_degraded` of the meaning D-12 gives it.
    for reason in reasons:
        assert "distill" not in reason.lower(), (
            f"a D-14 fact-list fallback was promoted into the run's degradation "
            f"reasons: {reason!r}. It is not one of D-12's degrading conditions."
        )

    # -- the fallback stream's claims still reached the gates ---------------
    funnel = result["verification_summary"]
    assert funnel["distilled"] > 0
    inserts = _claim_inserts(statements)
    by_text = {p["text"]: p for p in inserts}
    assert _FACT_MARGIN in by_text, (
        "a claim extracted by the FALLBACK distiller never reached persistence — "
        "the fallback ran and its output was then dropped, which is the worst of "
        "both worlds: paid for and unused"
    )
    fallback_claim = by_text[_FACT_MARGIN]
    assert fallback_claim["certainty"] is None, (
        f"the fallback path invented a certainty ({fallback_claim['certainty']!r}). "
        f"A distilled claim carries no provider-stated confidence, and filling one "
        f"in would present a guess as the provider's own word (D-13)."
    )
    assert fallback_claim["found_by"] == [_LostStreamProvidersAudited.FACTLESS_PROVIDER], (
        f"the fallback claim lost its attribution: {fallback_claim['found_by']!r}"
    )

    # -- three streams, not four, and the funnel still reconciles -----------
    stages = _stage_sequence(statements)
    assert "deep_research" in stages and "merge" in stages, (
        f"a degraded run still researches and still merges: {stages}"
    )
    assert not (set(stages) - _DECLARED_STAGE_KEYS), (
        f"undeclared stage key(s): {sorted(set(stages) - _DECLARED_STAGE_KEYS)}"
    )
    report = shape_verification_report(
        verdict_rows=[], funnel=funnel, claim_count=funnel["distilled"],
        cost_usd_total=None, cost_pending=True,
    )
    accounting = report["accounting"]
    assert accounting is not None, "a degraded run must still produce accounting"
    total = (
        accounting["checked"]
        + accounting["checked_incidentally"]["total"]
        + accounting["not_checkable"]["total"]
        + accounting["should_have_been_checked"]
    )
    assert total == funnel["distilled"], (
        f"one-claim-one-bucket broke on the degraded path: {total} of "
        f"{funnel['distilled']}. {accounting}"
    )

    # -- the contradiction STILL met, even across the fallback --------------
    shared = [
        block for block in audited.group_claim_blocks
        if _FACT_GUNVOR in block and _FACT_CARLYLE in block
    ]
    assert len(shared) == 1, (
        f"losing a stream's fact list also lost the contradiction: the two "
        f"incompatible claims reached {len(shared)} shared session(s). D-14 is "
        f"supposed to degrade a stream's METADATA, not the engine's ability to "
        f"catch a contradiction."
    )


async def test_recovered_retry_and_cost_pending_do_not_degrade(monkeypatch):
    """D-12's two explicit carve-outs, and why the degraded marker keeps meaning.

    A retry that RECOVERED is recovery, and a pending cost is the designed
    pending-then-backfill-exact path. Neither is a shortfall. A marker that is
    always on is a marker the operator learns to ignore — so both must leave the
    run `completed` while still being VISIBLE (R5: recovery is shown, not
    punished, and not hidden either).
    """
    audited = _ScriptedProvidersAudited()
    audited.fail_once_on = {"workshop_critique"}
    result, statements = await _engine_run(audited, monkeypatch=monkeypatch)

    assert audited.forced_failures == 1, (
        "the scripted transient failure never fired, so this test proves nothing "
        "about retries"
    )
    assert audited.routes.get("workshop_critique", 0) >= 2, (
        f"the failed call was not retried at all "
        f"({audited.routes.get('workshop_critique', 0)} call(s)) — a transient "
        f"503 must be retried, or every blip becomes a lost stage"
    )
    assert not audited.unexpected, f"unrouted prompt(s): {audited.unexpected}"

    reasons = result["verification_summary"]["degradation_reasons"]
    assert reasons == [], (
        f"a RECOVERED retry degraded the run: {reasons}. Demoting recovery would "
        f"make nearly every run degraded and drain `completed_degraded` of its "
        f"meaning — the alarm fatigue D-12 explicitly rejects."
    )
    assert _terminal_state_of(result) == "completed", (
        f"terminal_state() returned {_terminal_state_of(result)!r} after a retry "
        f"that succeeded. inputs={result['terminal_inputs']}"
    )

    # R5: the recovery is SHOWN. A retried call otherwise looks stalled — a row
    # sitting at `running` with no explanation while a backoff sleeps.
    workshop_entries = _stage_detail_entries(statements, "workshop")
    assert workshop_entries, "the workshop stage wrote no feed detail at all"
    assert any('"retry"' in entry for entry in workshop_entries), (
        "the retry is invisible in the operator's feed. R5 requires recovery to "
        "be shown, not silently absorbed: without it the operator sees a stalled "
        "row and cannot tell a slow call from a wedged one."
    )

    # cost_pending: this run's SerpApi plan is deliberately UNKNOWN, so the spend
    # is recorded as pending rather than guessed (D-16). That is a designed path,
    # not a shortfall, and it must not add a reason either.
    for reason in reasons:
        assert "cost" not in reason.lower(), (
            f"a pending cost was reported as a degradation: {reason!r}"
        )
    report = shape_verification_report(
        verdict_rows=[], funnel=result["verification_summary"],
        claim_count=result["verification_summary"]["distilled"],
        cost_usd_total=None, cost_pending=True,
    )
    assert report["verification_degraded"] is False, (
        "a run whose only anomalies were a recovered retry and a pending cost "
        "raised the verification-degraded marker"
    )
