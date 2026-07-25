# ===========================================================================
# THIS FILE CONTAINS NO PASS/FAIL THRESHOLD.
#
# It measures and it REPORTS. There is no agreement figure it will fail on, no
# minimum it demands, no comparison that can turn a build red. Nothing in this
# module is a CI gate, and nothing in it may ever become one.
#
# The reason is G-01. The recorded 456/424 labels came from blind LLM agents
# reading each claim and thinking about it. A production classifier cannot hit
# those labels exactly, and it is not supposed to: judgment about materiality is
# not arithmetic. Turning a wobbly agreement figure into a build gate would mean a
# green phase depends on a coin the model flips, and the honest engineering
# response to a red build like that is to weaken the check — which is how a
# meaningless gate teaches a team to ignore its own tests.
#
# The phase gate lives in test_gate_replay.py: deterministic, free, and exact. THIS
# file is the other half of G-01 — the informational calibration the operator runs
# by hand, whose numbers feed 15.2's live validation and nothing else.
# ===========================================================================
"""Gate calibration — the operator-run August measurement (Phase 15.1, G-01 + G-05).

WHY. Two questions the deterministic replay cannot answer, because it replays a
recorded answer key rather than consulting a model:

  G-01  How closely does the REAL materiality / error-likelihood classifier agree
        with the blind selection experiment that produced the recorded funnel? A
        low figure does not mean the pipeline is broken — it means the gate prompt
        needs work, and it tells the operator by how much.
  G-05  Do the four contradictions that SHIPPED on 2026-07-22 actually land in one
        cluster now? Aral at 16% and at 21%; LUKOIL NL at 46 stations and at
        ~70/75; Zeeland "sold to Carlyle" and "bought by TotalEnergies"; Gunvor and
        Carlyle. Exact-string bucketing put 92% of claims in singleton groups and
        let all four pairs through into the delivered report. Real clustering is
        supposed to collide each pair into ONE skeptic session.

HOW TO RUN (operator, by hand):

    NESTOR_GATE_CALIBRATION=1 \\
      pytest -m live nestor_pulse_sdk/tests/test_gate_calibration.py -s

  `-s` is required: the entire output of this file is print(). `-m live` selects
  it; the opt-in env var arms it. Both are needed — see the fencing note below.

REQUIREMENTS.
  - Real Google credentials for gemini-2.5-flash (ADC or GOOGLE_API_KEY). No
    Anthropic key is used or needed: this file never touches the capped account.
  - No database and no audit bucket. The audit sinks are local, in-memory
    stand-ins; the provider path, the cost table and the hash chain are the real
    ones, so the run also prints its own real cost.
  - NOT BEFORE 2026-08-01. The Anthropic monthly cap that produced the 776
    hard-400 incident resets then; the project's standing rule is no live LLM runs
    before that date, and this file is the only 15.1 test that makes any.

COST. gemini-2.5-flash with thinking disabled, a few hundred claims by default —
small change, and the exact spend is printed at the end of each test rather than
guessed at here. The full 1,162-claim sweep is an env var away (below).

TUNING (all optional):
  NESTOR_GATE_CALIBRATION          "1" arms the tests. Anything else skips them.
  NESTOR_GATE_CALIBRATION_SAMPLE   claims sampled for the agreement run (default
                                   300; set to 0 for the full recorded population).
  NESTOR_GATE_CALIBRATION_CLUSTER  claims fed to the clustering run (default 0 =
                                   the full population — a contradiction pair can
                                   only collide if BOTH members are in the input).

FENCED OUT OF CI TWO WAYS, DELIBERATELY:
  1. `@pytest.mark.live` on every test. `cloudbuild.test-gates.yaml` passes
     `-m "not live"`, which deselects them.
  2. A first-statement `pytest.skip(...)` behind NESTOR_GATE_CALIBRATION. This is
     not belt-and-braces theatre: `pyproject.toml` only REGISTERS the `live`
     marker (so --strict-markers accepts it) — registration does NOT deselect
     anything. A full-suite run with no marker filter would otherwise fire real
     provider calls from CI.
"""
from __future__ import annotations

import os

import pytest

#: Set to "1" to arm the calibration. Anything else (including unset) skips.
_OPT_IN_ENV = "NESTOR_GATE_CALIBRATION"

#: Grep-able prefix on every headline line, so the operator can pull the numbers
#: out of a long -s log with a single grep.
_TAG = "[15.1-CALIBRATION]"


#: The skip message, written once and used by the guard at the top of each test
#: body. The guard is INLINE in both bodies rather than hidden behind a helper:
#: "the first statement of this test refuses to run it" should be readable without
#: following a call, because that statement is the only thing standing between a
#: full-suite run and a real provider bill.
_SKIP_REASON = (
    f"G-01 calibration is operator-run and makes REAL LLM calls. It is not a CI "
    f"gate — the phase gate is test_gate_replay.py. Arm it with {_OPT_IN_ENV}=1 "
    f"and run with -m live -s. Not before 2026-08-01: the Anthropic monthly cap "
    f"resets then and the project bars live runs until it does."
)


def _int_env(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    try:
        return int(raw)
    except ValueError:
        return default


def _sample(rows: list, size: int) -> list:
    """An evenly-spaced sample, not the first N.

    The distilled TSV is ordered by facet and by producing researcher, so the head
    of the file is a biased slice of one topic. A stride keeps the sample's mix of
    facets close to the population's, which is what makes a partial agreement
    figure worth reading at all.
    """
    if size <= 0 or size >= len(rows):
        return list(rows)
    stride = len(rows) / size
    return [rows[int(i * stride)] for i in range(size)]


def _pct(part: int, whole: int) -> str:
    return "n/a" if not whole else f"{100.0 * part / whole:.1f}%"


# ---------------------------------------------------------------------------
# Local audit sinks.
#
# Provider egress is REAL — that is the entire point of this file. Audit
# PERSISTENCE is not: this is a measurement over a committed fixture, not a tenant
# run, so there is no `run` row for an audit_log foreign key to reference and no
# reason to push bodies into the audit bucket. Only the two sinks are replaced;
# the gemini client, the cost table and the hash-chain module are the production
# ones, so the chain still links and the printed cost is the real cost.
# ---------------------------------------------------------------------------

class _LocalBlobSink:
    def __init__(self) -> None:
        self.bodies = 0

    async def upload_audit_body(self, *, run_id, audit_id, provider, model,
                                request_dict, response_dict):
        self.bodies += 1
        return f"memory://15.1-calibration/{audit_id}"


class _LocalAuditWriter:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def get_prev_hash_and_seq(self, run_id, tenant_id):
        prev = self.rows[-1]["hash"] if self.rows else "0" * 64
        return prev, len(self.rows) + 1

    async def write_full_row(self, **row):
        self.rows.append(row)

    def total_cost(self):
        total = 0.0
        for row in self.rows:
            cost = row.get("cost_usd")
            if cost is not None:
                total += float(cost)
        return total


def _calibration_client():
    """A real AuditedLLMClient over the real gemini client, with local sinks.

    Built through the production factory so no provider client is constructed
    outside `audit/audited_llm_client.py` (the centralised-construction rule).
    `anthropic_client` is handed a placeholder so the factory never builds an
    Anthropic client: this file must not touch the capped account, and saying so
    in code is stronger than saying so in a comment.
    """
    from nestor_pulse_sdk.audit.audited_llm_client import build_audited_client

    client = build_audited_client(
        sessionmaker=object(),          # never used: the writer below replaces it
        anthropic_client=object(),      # never used: gemini-only file
    )
    client._audit = _LocalAuditWriter()
    client._gcs = _LocalBlobSink()
    return client


# ===========================================================================
# G-01 — agreement between the REAL classifier and the blind answer key
# ===========================================================================

@pytest.mark.live
def test_gate_agreement_against_the_blind_answer_key():
    """Report how far the real gate lands from the recorded blind labels.

    Real API test. Skipped by default; run with:
      NESTOR_GATE_CALIBRATION=1 pytest -m live \\
        nestor_pulse_sdk/tests/test_gate_calibration.py -s

    Report only — no threshold, no pass/fail, no comparison this test can fail
    on. Reading the numbers is the operator's job, and acting on them is a prompt
    change, not a code change.
    """
    if os.environ.get(_OPT_IN_ENV) != "1":
        pytest.skip(_SKIP_REASON)

    import asyncio
    import uuid
    from collections import Counter

    from nestor_pulse_sdk.pipeline.tribunal.gates import apply_gates
    from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import load_selection_experiment

    claims, classified, strict = load_selection_experiment()
    sample = _sample(claims, _int_env("NESTOR_GATE_CALIBRATION_SAMPLE", 300))

    audited = _calibration_client()
    decision_context = (
        "falsifiable-specific AND load-bearing for the LUKOIL BeNeLux "
        "dynamic-pricing report"
    )
    result = asyncio.get_event_loop().run_until_complete(apply_gates(
        claims=[dict(c) for c in sample],
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        decision_context=decision_context,
    ))
    graded = result["claims"]
    funnel = result["funnel"]

    # --- overall + the KEEP/DROP confusion matrix -------------------------
    matrix: Counter = Counter()          # (recorded, gate) -> n
    reason_hits: Counter = Counter()     # recorded DROP reason -> gate also DROPped
    reason_total: Counter = Counter()
    strict_hits = strict_total = 0
    gate_dropped_a_kept_claim: list[dict] = []
    gate_kept_a_dropped_claim: list[dict] = []

    for claim in graded:
        recorded_reason = classified.get(claim["id"])
        if recorded_reason is None:
            continue
        recorded = "KEEP" if recorded_reason == "KEEP" else "DROP"
        got = claim["gate"]["decision"]
        matrix[(recorded, got)] += 1

        if recorded == "DROP":
            reason_total[recorded_reason] += 1
            if got == "DROP":
                reason_hits[recorded_reason] += 1
            else:
                gate_kept_a_dropped_claim.append(claim)
        else:
            if got == "DROP":
                gate_dropped_a_kept_claim.append(claim)
            recorded_strict = strict.get(claim["id"])
            if recorded_strict and claim["gate"]["strict"]:
                strict_total += 1
                if claim["gate"]["strict"] == recorded_strict:
                    strict_hits += 1

    total = sum(matrix.values())
    agreed = matrix[("KEEP", "KEEP")] + matrix[("DROP", "DROP")]

    print("")
    print("=" * 78)
    print(f"{_TAG} G-01 gate agreement vs the blind answer key")
    print("=" * 78)
    print(f"claims graded            : {total} of {len(claims)} recorded")
    print(f"overall agreement        : {agreed}/{total} ({_pct(agreed, total)})")
    print(f"gate errors (defaulted)  : {funnel['gate_errors']}")
    print("")
    print("KEEP/DROP confusion matrix (rows = recorded, cols = gate):")
    print(f"{'':>10} {'KEEP':>10} {'DROP':>10}")
    for recorded in ("KEEP", "DROP"):
        print(f"{recorded:>10} {matrix[(recorded, 'KEEP')]:>10} "
              f"{matrix[(recorded, 'DROP')]:>10}")
    print("")
    print("agreement per recorded DROP reason:")
    for reason in ("NOT_FALSIFIABLE", "NOT_LOAD_BEARING", "BOTH"):
        print(f"  {reason:<18} {reason_hits[reason]:>5}/{reason_total[reason]:<5} "
              f"({_pct(reason_hits[reason], reason_total[reason])})")
    print("")
    print(f"VERIFY / SKIP_STABLE agreement among the recorded KEEPs: "
          f"{strict_hits}/{strict_total} ({_pct(strict_hits, strict_total)})")
    print("")
    print("the gate's own funnel on this sample:")
    for key in ("distilled", "kept", "dropped", "selected_verify", "skipped_stable"):
        print(f"  {key:<18} {funnel[key]}")

    # The dangerous direction first: a claim the blind experiment considered
    # material that the gate threw out never gets checked, and its passage ships
    # unexamined. The reverse direction only costs money.
    print("")
    print("THE COSTLY DISAGREEMENTS — recorded KEEP, gate DROP (up to 10):")
    if not gate_dropped_a_kept_claim:
        print("  none")
    for claim in gate_dropped_a_kept_claim[:10]:
        print(f"  id {claim['id']:<5} reason={claim['gate']['reason']:<18} "
              f"{claim['text'][:110]}")
    print("")
    print("THE CHEAP DISAGREEMENTS — recorded DROP, gate KEEP (up to 10):")
    if not gate_kept_a_dropped_claim:
        print("  none")
    for claim in gate_kept_a_dropped_claim[:10]:
        print(f"  id {claim['id']:<5} recorded={classified[claim['id']]:<18} "
              f"{claim['text'][:110]}")

    print("")
    print(f"{_TAG} agreement {_pct(agreed, total)} over {total} claims · "
          f"{len(gate_dropped_a_kept_claim)} material claims the gate would not "
          f"have checked · measured cost ${audited._audit.total_cost():.4f}")
    print("=" * 78)


# ===========================================================================
# G-05 — do the four SHIPPED contradictions cluster together now?
# ===========================================================================

#: Each pair member is located by substrings that must ALL appear in the claim
#: text (case-insensitive). Locating by text rather than by a hard-coded id keeps
#: the probe readable and keeps a fixture edit from silently pointing at the wrong
#: claim — a miss is printed as NOT FOUND, never inferred as a clustering failure.
_CONTRADICTION_PAIRS: list[tuple[str, list[str], list[str]]] = [
    (
        "Aral market share: 16% vs 21%",
        ["aral", "16"],
        ["aral", "21"],
    ),
    (
        "LUKOIL NL station count: 46 vs ~70/75",
        ["lukoil", "46"],
        ["lukoil", "7"],
    ),
    (
        "Zeeland: sold to Carlyle vs bought by TotalEnergies",
        ["zeeland", "carlyle"],
        ["zeeland", "total"],
    ),
    (
        "Buyer identity: Gunvor vs Carlyle",
        ["gunvor"],
        ["carlyle"],
    ),
]


def _find(claims: list[dict], needles: list[str]) -> list[dict]:
    out = []
    for claim in claims:
        text = (claim.get("text") or "").lower()
        if all(n in text for n in needles):
            out.append(claim)
    return out


@pytest.mark.live
def test_known_contradiction_pairs_cluster_together():
    """Report whether the four contradictions that SHIPPED now share a cluster.

    Real API test. Skipped by default; run with:
      NESTOR_GATE_CALIBRATION=1 pytest -m live \\
        nestor_pulse_sdk/tests/test_gate_calibration.py -s

    Report only — no threshold, no pass/fail. Clustering quality is a prompt
    property measured here and acted on in 15.2, not a build gate.

    Contradictory variants of the same fact have to reach ONE skeptic session:
    that session is where "16% or 21%?" gets reconciled. When they land in
    different sessions, both numbers pass their own check in isolation and both
    ship — which is exactly what happened on 2026-07-22.
    """
    if os.environ.get(_OPT_IN_ENV) != "1":
        pytest.skip(_SKIP_REASON)

    import asyncio
    import uuid

    from nestor_pulse_sdk.pipeline.tribunal.grouping import group_claims
    from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import load_selection_experiment

    claims, _classified, _strict = load_selection_experiment()
    population = _sample(claims, _int_env("NESTOR_GATE_CALIBRATION_CLUSTER", 0))

    audited = _calibration_client()
    groups = asyncio.get_event_loop().run_until_complete(group_claims(
        claims=[dict(c) for c in population],
        audited=audited,
        run_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    ))

    # claim id -> cluster key. group_claims keeps the original claim dicts.
    cluster_of: dict[int, str] = {}
    for group in groups:
        for claim in group.get("claims") or ():
            if claim.get("id") is not None:
                cluster_of[claim["id"]] = group.get("key", "")

    sizes = sorted((len(g.get("claims") or ()) for g in groups), reverse=True)
    singletons = sum(1 for n in sizes if n == 1)

    print("")
    print("=" * 78)
    print(f"{_TAG} G-05 contradiction clustering")
    print("=" * 78)
    print(f"claims clustered   : {len(population)}")
    print(f"clusters formed    : {len(groups)}")
    print(f"singleton clusters : {singletons} ({_pct(singletons, len(groups))}) "
          f"— the 2026-07-22 run was 92% singletons")
    print(f"largest clusters   : {sizes[:8]}")
    print("")

    collided = 0
    for label, left_needles, right_needles in _CONTRADICTION_PAIRS:
        left = _find(population, left_needles)
        right = _find(population, right_needles)
        print(f"PAIR: {label}")
        if not left or not right:
            # A fixture edit must never masquerade as a clustering failure.
            print(f"  NOT FOUND IN FIXTURE — probe {left_needles} matched "
                  f"{len(left)} claims, probe {right_needles} matched "
                  f"{len(right)}. Nothing about clustering can be concluded "
                  f"from this pair; fix the probe, not the clusterer.")
            print("")
            continue
        left_keys = {cluster_of.get(c["id"]) for c in left}
        right_keys = {cluster_of.get(c["id"]) for c in right}
        shared = {k for k in left_keys & right_keys if k}
        print(f"  side A ids {[c['id'] for c in left][:6]} -> clusters "
              f"{sorted(k for k in left_keys if k)[:4]}")
        print(f"  side B ids {[c['id'] for c in right][:6]} -> clusters "
              f"{sorted(k for k in right_keys if k)[:4]}")
        if shared:
            collided += 1
            print(f"  SAME CLUSTER: yes ({sorted(shared)[:3]}) — one skeptic "
                  f"session would see both variants and have to reconcile them")
        else:
            print("  SAME CLUSTER: no — each variant would be checked in "
                  "isolation, pass on its own terms, and both would ship")
        print(f"  A: {left[0]['text'][:110]}")
        print(f"  B: {right[0]['text'][:110]}")
        print("")

    print(f"{_TAG} {collided} of {len(_CONTRADICTION_PAIRS)} known shipped "
          f"contradictions collided into one cluster · {len(groups)} clusters "
          f"over {len(population)} claims · measured cost "
          f"${audited._audit.total_cost():.4f}")
    print("=" * 78)


# ---------------------------------------------------------------------------
# WHERE THESE NUMBERS GO. Into 15.2's live validation (V-01 / V-02 / V-03) and
# nowhere else. They do not gate 15.1, they do not gate 15.2, and they are not a
# regression baseline: a later run producing a different figure is information
# about the prompt, not a defect report. If either number is disappointing, the
# fix is a better gate prompt or a better clustering prompt — never a lower bar.
# ---------------------------------------------------------------------------
