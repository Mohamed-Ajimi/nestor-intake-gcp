"""Tests for Tribunal Phase-3 grouping: grouping.py + group_skeptic.py.

All tests use fakes — no Cloud SQL, no real provider keys, no network.

Covers:
  - group_claims: tags claims, blocks them by entity and CLUSTERS same-fact claims
    within each block (G-03); untagged and unclustered claims become their own
    singleton (never merged blindly, never dropped); a group inherits its members'
    HIGHEST stakes; the NESTOR_TRIBUNAL_CLUSTER=false exact-key path is UNWIRED
    (D-03, 15.2-15) but `_exact_keys` is still in-tree and still callable.
  - _parse_group_verdict: maps per-index verdicts; fills missing claims with
    'insufficient' (never silently drops a claim); surfaces reconciliation.
  - run_group_skeptic: server/client tool protocol; emit_group_verdict
    terminates and produces one verdict per claim.

Cloud Build gate:
  pytest nestor_pulse_sdk/tests/test_tribunal_grouping.py -v
(no Postgres, no provider keys, no network -- every LLM call is a hand-written fake)
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from nestor_pulse_sdk.pipeline.tribunal import grouping
from nestor_pulse_sdk.pipeline.tribunal.grouping import (
    group_claims, _norm, _parse_cluster_lines, _parse_tag_lines,
)
from nestor_pulse_sdk.pipeline.tribunal.group_skeptic import run_group_skeptic, _parse_group_verdict


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------
class _FakeGeminiResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeGrouperAudited:
    """Returns a canned plain-text tag block for gemini_generate."""
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls = 0

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        self.calls += 1
        return _FakeGeminiResp(self._text)


# Cluster answers the fake can COMPUTE from the block the clusterer actually sent,
# so a test never has to know how production chunked the block.
_ALL_ONE = "ALL_ONE"      # every claim in the chunk -> cluster 0 (same fact)
_EACH_OWN = "EACH_OWN"    # every claim in the chunk -> its own cluster


class _PromptAwareGrouperAudited:
    """Answers TAG calls and CLUSTER calls separately, recording both.

    The clusterer makes two DIFFERENT kinds of call (tag, then cluster), so one
    canned response is no longer enough. `cluster` is either _ALL_ONE / _EACH_OWN
    (computed from the block sent), a canned string (to inject garbage or omit an
    index), or a list of canned strings -- one per cluster call, in call order.
    """

    def __init__(self, tag_text: str, cluster: Any = _ALL_ONE) -> None:
        self._tag_text = tag_text
        self._cluster = cluster
        self.tag_calls: list[str] = []
        self.cluster_calls: list[str] = []

    @staticmethod
    def _block_indices(contents: str) -> list[int]:
        """The claim indices the prompt's block actually carries."""
        out: list[int] = []
        for line in contents.splitlines():
            head = line.split("|", 1)[0].strip() if "|" in line else ""
            if head.isdigit():
                out.append(int(head))
        return out

    def _cluster_answer(self, contents: str) -> str:
        spec = self._cluster
        if isinstance(spec, list):
            i = len(self.cluster_calls) - 1
            spec = spec[i] if i < len(spec) else (spec[-1] if spec else "")
        idxs = self._block_indices(contents)
        if spec == _ALL_ONE:
            return "\n".join(f"{i} | 0" for i in idxs)
        if spec == _EACH_OWN:
            return "\n".join(f"{i} | {i}" for i in idxs)
        return spec

    async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
        if "CLUSTER_ID" in contents:          # _CLUSTER_PROMPT's output contract
            self.cluster_calls.append(contents)
            return _FakeGeminiResp(self._cluster_answer(contents))
        self.tag_calls.append(contents)       # _TAG_PROMPT
        return _FakeGeminiResp(self._tag_text)


class _FakeBlock:
    def __init__(self, type: str, **kw: Any) -> None:
        self.type = type
        for k, v in kw.items():
            setattr(self, k, v)


class _FakeUsage:
    """Token-usage stand-in. Hand-rolled: this suite uses no mocking library."""

    def __init__(self) -> None:
        self.input_tokens = 10
        self.output_tokens = 10
        self.cache_read_input_tokens = 0
        self.cache_creation_input_tokens = 0


class _FakeResp:
    def __init__(self, stop_reason: str, content: list[Any]) -> None:
        self.stop_reason = stop_reason
        self.content = content
        self.usage = _FakeUsage()


class _FakeSkepticAudited:
    def __init__(self, responses: list[_FakeResp]) -> None:
        self._responses = responses
        self._i = 0
        self.recorded_messages: list[list[dict]] = []

    async def anthropic_messages(self, *, run_id, tenant_id, model, messages, tools, tool_choice=None, **kw):
        self.recorded_messages.append(list(messages))
        r = self._responses[self._i]
        self._i += 1
        return r


# ---------------------------------------------------------------------------
# grouping.group_claims
# ---------------------------------------------------------------------------
class TestGroupClaims:
    def _claims(self):
        return [
            {"text": "FootballGPT costs $4.99/mo", "facet": "competitors", "stakes": "high"},
            {"text": "Football GPT pricing starts at $9.99/mo", "facet": "competitors", "stakes": "med"},
            {"text": "Wyscout has 600 competitions", "facet": "competitors", "stakes": "low"},
        ]

    def test_groups_same_entity_attribute_together(self):
        # Tagger maps the two FootballGPT pricing claims to the same entity; the
        # cluster pass then confirms they are the same fact. (Prompt-aware fake:
        # the clusterer makes a second, different call the canned fake can't serve.)
        tag_text = "0 | FootballGPT | pricing\n1 | Football GPT | pricing\n2 | Wyscout | capability"
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        groups = _run(group_claims(claims=self._claims(), audited=audited,
                                   run_id=uuid.uuid4(), tenant_id=uuid.uuid4()))
        # FootballGPT pricing (2 claims) + Wyscout capability (1 claim) = 2 groups
        assert len(groups) == 2
        fg = next(g for g in groups if "footballgpt" in g["key"])
        assert len(fg["claims"]) == 2          # the two pricing variants merged
        assert fg["stakes"] == "high"          # inherits the highest stakes of members

    def test_untagged_claim_becomes_singleton(self):
        # Tagger returns nothing for claim 1 -> it must still be verified (own group).
        tag_text = "0 | FootballGPT | pricing\n2 | Wyscout | capability"
        audited = _FakeGrouperAudited(tag_text)
        groups = _run(group_claims(claims=self._claims(), audited=audited,
                                   run_id=uuid.uuid4(), tenant_id=uuid.uuid4()))
        all_claims = [c for g in groups for c in g["claims"]]
        assert len(all_claims) == 3            # no claim dropped
        assert any(g["key"].startswith("__singleton__") for g in groups)

    def test_empty_claims_returns_empty(self):
        audited = _FakeGrouperAudited("")
        assert _run(group_claims(claims=[], audited=audited,
                                 run_id=uuid.uuid4(), tenant_id=uuid.uuid4())) == []


class TestClustering:
    """G-03: same-fact claims must reach ONE skeptic session.

    INCIDENT (live run 4cbb5311, 2026-07-22): exact-string bucketing on
    `entity│attribute` left the overwhelming majority of groups as singletons,
    because near-miss labels across languages never met -- e.g.
    `lukoil|verkoop_internationale_operaties` vs `lukoil benelux|status_rapport`.
    FOUR flat contradictions shipped to the client as a result: Aral 16% vs 21%
    market share; LUKOIL NL 46 vs ~70/75 stations; the Zeeland refinery "sold to
    Carlyle" vs "bought by TotalEnergies"; and the Gunvor-vs-Carlyle buyer
    conflict. Every test below is a guard on one link of that failure chain.
    """

    @staticmethod
    def _ids():
        return {"run_id": uuid.uuid4(), "tenant_id": uuid.uuid4()}

    def test_differently_worded_same_fact_claims_merge(self):
        # The exact near-miss pattern that shipped the buyer contradiction: ONE
        # entity, THREE different attribute labels in two languages. Exact-key
        # bucketing gives three lonely groups; clustering gives one session.
        claims = [
            {"text": "LUKOIL verkoopt zijn internationale operaties",
             "facet": "market", "stakes": "high"},
            {"text": "Lukoil's international operations are being sold, per the status report",
             "facet": "market", "stakes": "med"},
            {"text": "De overname van Lukoil's buitenlandse activiteiten loopt",
             "facet": "market", "stakes": "low"},
        ]
        tag_text = ("0 | lukoil | verkoop_internationale_operaties\n"
                    "1 | LUKOIL | status_rapport\n"
                    "2 | Lukoil | overname")
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        assert len(groups) == 1, \
            "contradictory variants must meet in one skeptic session or the contradiction ships"
        assert len(groups[0]["claims"]) == 3, \
            "a variant left outside the group finds its own supporting source and 'passes'"
        assert len(audited.cluster_calls) == 1, \
            "one entity block of three claims must cost exactly one clustering call"

    def test_conflicting_values_share_a_group(self):
        # The Aral 16%-vs-21% shape: same fact, incompatible numbers, different
        # attribute words. Split apart, BOTH pass; together, the skeptic must pick.
        claims = [
            {"text": "Aral heeft een marktaandeel van 16%", "facet": "market", "stakes": "high"},
            {"text": "Aral's market share is 21 percent", "facet": "market", "stakes": "high"},
        ]
        tag_text = "0 | Aral | marktaandeel\n1 | Aral | market_share"
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        assert len(groups) == 1, \
            "two incompatible values for the same fact must be judged side by side, not separately"
        assert len(groups[0]["claims"]) == 2, \
            "both values must reach the skeptic; one alone always finds a source that agrees"

    def test_every_claim_survives_clustering(self):
        # The never-drop contract. A claim that leaves grouping is never verified
        # and never appears in the report -- silently.
        claims = [
            {"text": "Aral heeft een marktaandeel van 16%", "facet": "market", "stakes": "high"},
            {"text": "Aral's market share is 21 percent", "facet": "market", "stakes": "med"},
            {"text": "Een claim die de tagger niet kon labelen", "facet": "market", "stakes": "low"},
            {"text": "Shell operates a network of stations", "facet": "market", "stakes": "low"},
            {"text": "Nog een ongelabelde claim", "facet": "market", "stakes": "high"},
        ]
        # Indices 2 and 4 come back untagged; the rest tag and cluster normally.
        tag_text = "0 | Aral | share\n1 | Aral | share\n3 | Shell | stations"
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        flat = [c for g in groups for c in g["claims"]]
        assert len(flat) == len(claims), \
            "clustering must conserve claims exactly; a lost claim is silently never verified"
        for claim in claims:
            assert any(claim is member for member in flat), \
                "every input claim object must still be reachable in some group"

    def test_unclustered_claim_becomes_singleton(self):
        # The model omits index 1 and emits a junk line. That claim must still be
        # verified -- on its own -- rather than vanish.
        claims = [
            {"text": "Aral A", "facet": "market", "stakes": "low"},
            {"text": "Aral B", "facet": "market", "stakes": "low"},
            {"text": "Aral C", "facet": "market", "stakes": "low"},
        ]
        tag_text = "0 | Aral | share\n1 | Aral | share\n2 | Aral | share"
        audited = _PromptAwareGrouperAudited(tag_text, "0 | 0\n2 | 0\nI refuse to answer")
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        flat = [c for g in groups for c in g["claims"]]
        assert len(flat) == 3, "an unplaceable claim must still be verified, not dropped"
        singletons = [g for g in groups if g["key"].startswith("__singleton__")]
        assert len(singletons) == 1, "exactly the unplaced claim gets its own group"
        assert singletons[0]["claims"][0] is claims[1], \
            "the singleton must be the claim the model failed to place"

    def test_cluster_call_failure_does_not_lose_claims(self):
        # A provider 500 on the cluster call must degrade to 'everyone is their own
        # singleton' -- more sessions, never fewer verified claims.
        class _ClusterFailsAudited(_PromptAwareGrouperAudited):
            async def gemini_generate(self, *, run_id, tenant_id, model, contents, **kwargs):
                if "CLUSTER_ID" in contents:
                    raise RuntimeError("provider 500")
                return await super().gemini_generate(
                    run_id=run_id, tenant_id=tenant_id, model=model,
                    contents=contents, **kwargs,
                )

        claims = [
            {"text": "Aral A", "facet": "market", "stakes": "low"},
            {"text": "Aral B", "facet": "market", "stakes": "low"},
            {"text": "Aral C", "facet": "market", "stakes": "low"},
        ]
        tag_text = "0 | Aral | share\n1 | Aral | share\n2 | Aral | share"
        audited = _ClusterFailsAudited(tag_text)
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        flat = [c for g in groups for c in g["claims"]]
        assert len(flat) == 3, "a failed clustering call must never cost a claim its verification"
        assert all(g["key"].startswith("__singleton__") for g in groups), \
            "the neutral default is 'own singleton', so every claim is still checked"

    def test_oversized_block_is_chunked(self):
        # Blob guard: one runaway entity must not become a single unreadable
        # mega-group, and cluster id 0 from two chunks must not silently merge.
        claims = [{"text": f"Aral fact {i}", "facet": "market", "stakes": "low"}
                  for i in range(5)]
        tag_text = "\n".join(f"{i} | Aral | share" for i in range(5))
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        old_max, old_batch = grouping._CLUSTER_MAX_BLOCK, grouping._CLUSTER_BATCH
        grouping._CLUSTER_MAX_BLOCK, grouping._CLUSTER_BATCH = 2, 2
        try:
            groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        finally:
            grouping._CLUSTER_MAX_BLOCK, grouping._CLUSTER_BATCH = old_max, old_batch
        assert len(audited.cluster_calls) == 2, \
            "a 5-claim block over the cap splits 2+2+1; the lone chunk costs no call"
        keys = [g["key"] for g in groups]
        assert len(set(keys)) == len(keys), \
            "chunk namespacing must keep two chunks' cluster id 0 from colliding into one group"
        assert all("#" in key for key in keys), \
            "clustered keys carry the block#chunk#id namespace that makes them collision-proof"
        flat = [c for g in groups for c in g["claims"]]
        assert len(flat) == 5, "chunking must not lose a claim"

    def test_stakes_inheritance_is_max(self):
        # Depth (turns / searches / fetches) follows group stakes: a high-stakes
        # claim buried in a low-stakes group would be checked shallowly.
        claims = [
            {"text": "Aral A", "facet": "market", "stakes": "low"},
            {"text": "Aral B", "facet": "market", "stakes": "high"},
        ]
        tag_text = "0 | Aral | share\n1 | Aral | share"
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        assert len(groups) == 1
        assert groups[0]["stakes"] == "high", \
            "a group is only as low-stakes as its most important claim, or that claim gets checked shallowly"

    def test_exact_key_path_is_unwired_but_still_in_tree(self):
        """D-03: `NESTOR_TRIBUNAL_CLUSTER=false` no longer changes anything.

        UPDATED, NOT DELETED (15.2-15). This test used to be
        `test_cluster_disabled_falls_back_to_exact_key_bucketing`, and it asserted
        the OPPOSITE: that flipping `_CLUSTER_ENABLED` off reproduced the pre-15.1
        `entity│attribute` bucketing exactly, at no extra cost. That was a real
        guarantee and this file kept it honest.

        D9/D11 removed the guarantee on purpose. The cross-provider merge now runs
        BEFORE the verification gates and LLM clustering is the ONLY merge in the
        engine (B-04) — an exact-key baseline is no longer a behaviour this
        pipeline can be in, so `group_claims` no longer branches on the flag.

        The test is FLIPPED rather than removed, the same treatment
        `test_fail_loud.py:95` gave its own deliberate negative, because "the A/B
        path is gone" is a claim that deserves an executable assertion of its own.
        It pins BOTH halves of D-03: unreferenced, and still in-tree —
        `_exact_keys` stays importable and still computes the old keys when called
        directly, so 15.2-18's V-03 cleanup commit has something real to delete
        and an operator comparison run can still reach the old rule. The original
        claim fixture is kept verbatim so the two versions are comparable.
        """
        claims = [
            {"text": "FootballGPT costs $4.99/mo", "facet": "competitors", "stakes": "high"},
            {"text": "Football GPT pricing starts at $9.99/mo", "facet": "competitors", "stakes": "med"},
            {"text": "Wyscout has 600 competitions", "facet": "competitors", "stakes": "low"},
        ]
        tag_text = "0 | FootballGPT | pricing\n1 | Football GPT | pricing\n2 | Wyscout | capability"
        audited = _PromptAwareGrouperAudited(tag_text, _ALL_ONE)
        old_enabled = grouping._CLUSTER_ENABLED
        grouping._CLUSTER_ENABLED = False
        try:
            groups = _run(group_claims(claims=claims, audited=audited, **self._ids()))
        finally:
            grouping._CLUSTER_ENABLED = old_enabled

        # 1. UNWIRED: the flag is dead. Clustering ran anyway.
        assert audited.cluster_calls, \
            "the exact-key path is unwired (D-03) — clustering must run even with " \
            "_CLUSTER_ENABLED=False, or the flag is still reachable"
        assert all("│" not in g["key"] for g in groups), \
            "every key must be a CLUSTER key; a `entity│attribute` key means the " \
            "exact-key branch is still wired into group_claims"

        # 2. NOT DELETED: `_exact_keys` still exists and still does its old job.
        assert hasattr(grouping, "_exact_keys"), \
            "D-03 is unreference-then-delete-later: _exact_keys must stay in-tree " \
            "until 15.2-18's V-03 cleanup commit"
        old_keys = grouping._exact_keys(
            claims,
            [("FootballGPT", "pricing"), ("Football GPT", "pricing"), ("Wyscout", "capability")],
        )
        assert len(old_keys) == 3
        assert all("│" in k for k in old_keys), \
            "called directly, _exact_keys still emits the old entity│attribute key"
        assert old_keys[0] == old_keys[1] != old_keys[2], \
            "and still buckets by exact normalised match"

        # 3. NEVER-DROP holds on the one surviving path.
        flat = [c for g in groups for c in g["claims"]]
        assert len(flat) == 3, "clustering must not lose a claim"


class TestNormAndParse:
    def test_norm_merges_variants(self):
        assert _norm("FootballGPT") == _norm("football gpt") == "footballgpt" or \
               _norm("FootballGPT") == "footballgpt"

    def test_parse_tag_lines_fills_missing(self):
        out = _parse_tag_lines("0 | A | x\n2 | C | z", 3)
        assert out[0] == ("A", "x")
        assert out[1] == ("", "")   # missing -> empty -> singleton downstream
        assert out[2] == ("C", "z")

    def test_parse_cluster_lines_is_bounds_checked(self):
        # Untrusted model text: an out-of-range index must not write into another
        # claim's slot, and garbage must not raise.
        out = _parse_cluster_lines("0 | 7\n99 | 3\nnot a line\n2 | oops", 3)
        assert out[0] == 7
        assert out[1] == -1, "an unaddressed claim keeps the sentinel and becomes a singleton"
        assert out[2] == -1, "a non-numeric cluster id is ignored, not guessed"
        assert len(out) == 3, "the result is always exactly one entry per claim"


# ---------------------------------------------------------------------------
# group_skeptic._parse_group_verdict
# ---------------------------------------------------------------------------
class TestParseGroupVerdict:
    def test_maps_per_index_and_fills_missing(self):
        block = {"input": {
            "verdicts": [
                {"claim_index": 0, "verdict": "support", "confidence": 0.9},
                # index 1 omitted on purpose
                {"claim_index": 2, "verdict": "refute", "confidence": 0.8},
            ],
            "reconciliation": {"disputed": True, "relation": "disputed",
                               "note": "two prices, no scope", "canonical": "$4.99/mo"},
            "evidence_refs": ["https://example.com/pricing"],
        }}
        out = _parse_group_verdict(block, n_claims=3, citations=["https://src"])
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        assert out["verdicts_by_index"][1]["verdict"] == "insufficient"  # missing -> filled
        assert out["verdicts_by_index"][2]["verdict"] == "refute"
        assert out["reconciliation"]["disputed"] is True
        assert out["reconciliation"]["canonical"] == "$4.99/mo"

    def test_bad_index_ignored_not_crash(self):
        block = {"input": {"verdicts": [{"claim_index": 99, "verdict": "support", "confidence": 1.0}],
                           "reconciliation": {"disputed": False, "relation": "single", "note": ""}}}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["verdict"] == "insufficient"  # 99 dropped, 0 filled

    # F-01 regression (live run 4cbb5311, 2026-07-22): the model returned the
    # reconciliation field as a JSON-encoded STRING -> "'str' object has no
    # attribute 'get'" crash, and ALL of the group's verdicts were discarded
    # (24 "BUG:recon-as-str" rows). The parser must coerce JSON-string fields.
    def test_reconciliation_as_json_string_parsed_verdicts_preserved(self):
        block = {"input": {
            "verdicts": [{"claim_index": 0, "verdict": "support", "confidence": 0.9}],
            "reconciliation": '{"disputed": true, "relation": "disputed", '
                              '"note": "two prices, no scope", "canonical": "$4.99/mo"}',
        }}
        out = _parse_group_verdict(block, n_claims=1, citations=["https://src"])
        assert out["verdicts_by_index"][0]["verdict"] == "support"  # not discarded
        assert out["reconciliation"]["disputed"] is True
        assert out["reconciliation"]["canonical"] == "$4.99/mo"

    def test_reconciliation_garbage_string_falls_back_default(self):
        block = {"input": {
            "verdicts": [{"claim_index": 0, "verdict": "refute", "confidence": 0.8}],
            "reconciliation": "not json {{",
        }}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["verdict"] == "refute"   # verdicts preserved
        assert out["reconciliation"]["disputed"] is False           # default reconciliation
        assert out["reconciliation"]["relation"] == "single"

    def test_verdicts_as_json_string_parsed(self):
        block = {"input": {
            "verdicts": '[{"claim_index": 0, "verdict": "support", "confidence": 0.9}]',
            "reconciliation": {"disputed": False, "relation": "single", "note": ""},
        }}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["verdict"] == "support"

    def test_evidence_refs_as_json_string_parsed(self):
        block = {"input": {
            "verdicts": [{"claim_index": 0, "verdict": "support", "confidence": 0.9}],
            "reconciliation": {"disputed": False, "relation": "single", "note": ""},
            "evidence_refs": '["https://example.com/pricing"]',
        }}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["evidence_refs"] == ["https://example.com/pricing"]

    def test_whole_input_as_json_string_no_crash(self):
        block = {"input": '{"verdicts": [{"claim_index": 0, "verdict": "support", '
                          '"confidence": 0.9}], "reconciliation": '
                          '{"disputed": false, "relation": "single", "note": ""}}'}
        out = _parse_group_verdict(block, n_claims=1, citations=[])
        assert out["verdicts_by_index"][0]["verdict"] == "support"


# ---------------------------------------------------------------------------
# run_group_skeptic loop
# ---------------------------------------------------------------------------
class TestRunGroupSkeptic:
    def test_emit_group_verdict_terminates_with_per_claim_verdicts(self):
        group_verdict_block = _FakeBlock(
            "tool_use", name="emit_group_verdict",
            input={
                "verdicts": [
                    {"claim_index": 0, "verdict": "support", "confidence": 0.9},
                    {"claim_index": 1, "verdict": "refute", "confidence": 0.7},
                ],
                "reconciliation": {"disputed": True, "relation": "disputed",
                                   "note": "conflicting prices", "canonical": "$4.99"},
                "evidence_refs": ["http://x"],
            },
        )
        audited = _FakeSkepticAudited([_FakeResp("tool_use", [group_verdict_block])])
        group = {"entity": "FootballGPT", "attribute": "pricing", "stakes": "high",
                 "claims": [{"text": "costs $4.99"}, {"text": "costs $9.99"}]}
        out = _run(run_group_skeptic(group=group, sources=[], audited=audited,
                                     run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-x"))
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        assert out["verdicts_by_index"][1]["verdict"] == "refute"
        assert out["reconciliation"]["disputed"] is True

    def test_server_tool_then_verdict_no_synthetic_tool_result(self):
        search_block = _FakeBlock("web_search_tool_result", tool_use_id="t1",
                                  content=[{"type": "text", "text": "found"}])
        verdict_block = _FakeBlock("tool_use", name="emit_group_verdict",
            input={"verdicts": [{"claim_index": 0, "verdict": "support", "confidence": 0.8}],
                   "reconciliation": {"disputed": False, "relation": "single", "note": ""}})
        audited = _FakeSkepticAudited([
            _FakeResp("tool_use", [search_block]),
            _FakeResp("tool_use", [verdict_block]),
        ])
        group = {"entity": "X", "attribute": "y", "stakes": "med", "claims": [{"text": "c"}]}
        out = _run(run_group_skeptic(group=group, sources=[], audited=audited,
                                     run_id=uuid.uuid4(), tenant_id=uuid.uuid4(), model="claude-x"))
        assert out["verdicts_by_index"][0]["verdict"] == "support"
        # No synthetic tool_result appended for the server tool (HTTP-400 trap).
        for msgs in audited.recorded_messages:
            for m in msgs:
                if m.get("role") == "user":
                    for blk in (m.get("content") or []):
                        if isinstance(blk, dict):
                            assert blk.get("type") != "tool_result"


# ---------------------------------------------------------------------------
# Single-session adjudication semantics (one group skeptic is authoritative)
# ---------------------------------------------------------------------------
from nestor_pulse_sdk.pipeline.tribunal.adjudicate import adjudicate


class TestSingleVerdictAdjudication:
    """With one session per group, each claim gets ONE verdict. Confirm the
    existing majority-independent rule does the right thing without changes."""

    def test_single_refute_with_citation_drops(self):
        v = [{"verdict": "refute", "confidence": 0.9, "citations": ["http://x"]}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is False  # dropped

    def test_single_refute_without_citation_survives(self):
        # Locked rule: refuting REQUIRES an independent source.
        v = [{"verdict": "refute", "confidence": 0.9, "citations": [], "evidence_refs": []}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is True   # survives

    def test_single_support_survives(self):
        v = [{"verdict": "support", "confidence": 0.9, "citations": ["http://x"]}]
        assert adjudicate({"text": "c", "stakes": "high"}, v) is True

    def test_no_verdict_low_stakes_waves_through(self):
        assert adjudicate({"text": "c", "stakes": "low"}, []) is True
