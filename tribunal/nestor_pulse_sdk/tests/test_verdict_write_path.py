"""No-DB proof that the Tribunal verdict write path actually writes.

CR-02 / the 15.1 SC2 gap. Before plan 15.1-14 NOTHING in production wrote a
`verification_verdict` row: `persist_tribunal_claims` inserted claim + source +
claim_source only, and the sole writer anywhere in the repo was the recorded-
fixture loader. `build_verification_report` therefore selected zero rows on
every real run and published
`verdicts.{support,refute,insufficient,superseded} == []` with
`counts.verdicts_total == 0` directly beside an honest, gate-derived `checked`
figure -- two numbers on one operator screen that contradicted each other.

Test 1 below is the assertion whose absence let that ship: the verdict-row count
used to be zero.

These tests are PURE:
  - no Postgres -- the session is a hand-written fake that records statements
  - no network, no provider client, no API key (the Anthropic account is at its
    monthly cap, so a CI-fired model call would be a real cost defect)
  - no pytest marker at all, so the fast gate collects them by default

INVOCATION:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-gates.yaml \
    --project="$GOOGLE_PROJECT"

`asyncio_mode = "auto"` is set in pyproject.toml, so the async tests below need
no decorator. They deliberately do NOT reach for the deprecated
loop-fetch-then-run_until_complete idiom (review IN-04): it is deprecated on
3.11, its behaviour is gone on 3.12+, and it breaks in a full-suite run as soon
as a sibling test closes the loop.
"""
from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_RUN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# SQL needles. "INSERT INTO claim (" keeps claim rows distinct from the
# "INSERT INTO claim_source (" join rows.
_VERDICT_INSERT = "INSERT INTO verification_verdict"
_CLAIM_INSERT = "INSERT INTO claim ("
_TENANT_CONTEXT = "set_config"


# ---------------------------------------------------------------------------
# Fake session -- records every statement, opens no connection
# ---------------------------------------------------------------------------

class _FakeResult:
    """Enough of a Result for `_upsert_source`'s RETURNING path."""

    def __init__(self) -> None:
        self._row = SimpleNamespace(id=uuid.uuid4())

    def first(self):
        return self._row


class _FakeSession:
    """Records `(sql_text, params)` per execute. No begin/commit on purpose:
    `persist_tribunal_claims` is documented as running inside a transaction the
    CALLER opens."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _FakeResult()


def _sql(calls: list[tuple[str, dict]], needle: str) -> list[tuple[str, dict]]:
    """The recorded calls whose SQL text contains `needle`, in call order."""
    return [(s, p) for s, p in calls if needle in s]


def _params(calls: list[tuple[str, dict]], needle: str) -> list[dict]:
    return [p for _, p in _sql(calls, needle)]


# ---------------------------------------------------------------------------
# Fixture: two survivors + one dropped claim
# ---------------------------------------------------------------------------

def _fixture() -> tuple[list[dict], list[dict], dict]:
    """Returns (survivors, dropped, verdicts_by_claim).

    `verdicts_by_claim` is keyed by `id(claim)` -- object identity -- so the
    returned lists MUST stay referenced for the keys to remain valid.
    """
    survivor_a = {"text": "Rate X stood at 21 percent in 2025.", "facet": "market"}
    survivor_b = {"text": "Scheme Y grants a 30 percent deduction.", "facet": "policy"}
    dropped_c = {"text": "Company Z holds a 90 percent share.", "facet": "market"}

    verdict_a = {
        "verdict": "support",
        "confidence": 0.9,
        "evidence_refs": ["https://a.example/one", "https://a.example/two"],
        "citations": [],
        "superseded_note": "",
    }
    verdict_b = {
        "verdict": "superseded",
        "confidence": 0.4,
        "evidence_refs": [],
        "citations": [],
        "superseded_note": "applied until 1 April 2026",
        "reconciliation": {
            "disputed": False,
            "relation": "scoped",
            "note": "the rule changed on 1 April 2026",
            "canonical": "25 percent from 1 April 2026",
        },
    }
    verdict_c = {
        "verdict": "refute",
        "confidence": 0.8,
        "evidence_refs": ["https://c.example/proof"],
        "citations": [],
        "superseded_note": "",
    }

    verdicts_by_claim = {
        id(survivor_a): [verdict_a],
        id(survivor_b): [verdict_b],
        id(dropped_c): [verdict_c],
    }
    return [survivor_a, survivor_b], [dropped_c], verdicts_by_claim


async def _run() -> tuple[_FakeSession, dict]:
    survivors, dropped, verdicts_by_claim = _fixture()
    session = _FakeSession()
    result = await persist_tribunal_claims(
        claims=survivors,
        dropped_claims=dropped,
        verdicts_by_claim=verdicts_by_claim,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )
    return session, result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

async def test_a_verdict_row_is_written_for_every_verdict():
    """THE regression assertion. Before 15.1-14 this count was zero on every
    production run, which is why the report's four verdict lists were empty."""
    session, _ = await _run()
    assert len(_sql(session.calls, _VERDICT_INSERT)) == 3


async def test_survivor_verdicts_are_linked_to_the_claim_row_just_inserted():
    """The claim_id linkage is what makes `unverified.claims_with_verdict` a
    real number instead of the claim_id-IS-NULL workaround report.py carries."""
    session, _ = await _run()
    claim_ids = [p["id"] for p in _params(session.calls, _CLAIM_INSERT)]
    verdict_claim_ids = [p["cid"] for p in _params(session.calls, _VERDICT_INSERT)]

    assert len(claim_ids) == 2
    assert claim_ids[0] != claim_ids[1], "each survivor gets its own claim row"
    # Verdicts are written in survivor order, each carrying its own claim's id.
    assert verdict_claim_ids[:2] == claim_ids


async def test_dropped_claim_verdicts_are_written_with_a_null_claim_id():
    """A refuted claim has no `claim` row -- the claim table is the survivor
    recall mechanism -- so its verdict carries claim_id NULL. Without this row
    `report["verdicts"]["refute"]` is structurally empty forever."""
    session, _ = await _run()
    rows = _params(session.calls, _VERDICT_INSERT)
    null_linked = [p for p in rows if p["cid"] is None]

    assert len(null_linked) == 1
    assert null_linked[0]["verdict"] == "refute"


async def test_tenant_context_is_set_before_any_verdict_insert():
    """RUNTIME ordering proof -- source line order cannot establish this.

    `_insert_verdict` is DEFINED above `persist_tribunal_claims` (it is grouped
    with the other write helpers), so comparing source positions would invert
    and prove nothing. What matters is that every verdict INSERT is executed
    AFTER `set_tenant_context` in the SAME transaction, binding the SAME
    tenant_id: that is what puts the write under migration 0011's FORCE-RLS
    `WITH CHECK` policy rather than around it.
    """
    session, _ = await _run()
    context_idx = min(
        i for i, (s, _) in enumerate(session.calls) if _TENANT_CONTEXT in s
    )
    verdict_idx = [
        i for i, (s, _) in enumerate(session.calls) if _VERDICT_INSERT in s
    ]

    assert verdict_idx, "no verdict INSERT was recorded at all"
    assert all(i > context_idx for i in verdict_idx)

    bound_tenant = session.calls[context_idx][1]["tid"]
    assert bound_tenant == str(_TENANT_ID)
    assert {p["tid"] for p in _params(session.calls, _VERDICT_INSERT)} == {bound_tenant}


async def test_jsonb_columns_are_json_encoded_and_null_when_empty():
    session, _ = await _run()
    row_a, row_b, row_c = _params(session.calls, _VERDICT_INSERT)

    assert json.loads(row_a["evidence"]) == [
        "https://a.example/one",
        "https://a.example/two",
    ]
    assert json.loads(row_c["evidence"]) == ["https://c.example/proof"]
    assert json.loads(row_b["recon"])["canonical"] == "25 percent from 1 April 2026"

    # Empty/absent must bind SQL NULL -- never the strings "null" or "{}".
    assert row_b["evidence"] is None
    assert row_a["recon"] is None
    assert row_c["recon"] is None


async def test_superseded_note_is_persisted_and_empty_notes_become_null():
    session, _ = await _run()
    row_a, row_b, _row_c = _params(session.calls, _VERDICT_INSERT)

    assert row_b["note"] == "applied until 1 April 2026"
    # superseded_note == "" on a non-superseded verdict -> NULL, not "".
    assert row_a["note"] is None


async def test_confidence_is_stringified():
    """The parser emits a float; the column is TEXT."""
    session, _ = await _run()
    row_a = _params(session.calls, _VERDICT_INSERT)[0]

    assert isinstance(row_a["confidence"], str)
    assert row_a["confidence"] == "0.9"


async def test_a_claim_with_no_verdicts_writes_no_verdict_row():
    claim = {"text": "A fact nobody checked.", "facet": "market"}
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )

    assert len(_sql(session.calls, _CLAIM_INSERT)) == 1
    assert _sql(session.calls, _VERDICT_INSERT) == []


async def test_a_malformed_verdict_dict_does_not_raise_and_defaults_the_verdict():
    """A NOT NULL column must never receive NULL because a model emitted junk."""
    claim = {"text": "A fact with a broken verdict payload.", "facet": ""}
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={id(claim): [{}]},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )

    row = _params(session.calls, _VERDICT_INSERT)[0]
    assert row["verdict"] == "insufficient"
    assert row["confidence"] is None
    assert row["evidence"] is None
    assert row["recon"] is None
    assert row["note"] is None


async def test_the_return_value_reports_how_many_verdicts_were_written():
    """A run that persists zero verdicts must be observable, not silent."""
    _session, result = await _run()

    assert result["verdict_count"] == 3
    assert len(result["verdict_ids"]) == 3
    # The pre-existing keys are untouched.
    assert len(result["claim_ids"]) == 2


async def test_the_writer_is_callable_without_dropped_claims():
    """`dropped_claims` is keyword-optional so every pre-existing call shape --
    including the two monkeypatched doubles in test_tribunal_pipeline.py --
    stays valid."""
    survivors, _dropped, verdicts_by_claim = _fixture()
    session = _FakeSession()

    result = await persist_tribunal_claims(
        claims=survivors,
        verdicts_by_claim=verdicts_by_claim,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )

    assert result["verdict_count"] == 2
    assert all(p["cid"] is not None for p in _params(session.calls, _VERDICT_INSERT))
