"""
Verification report shaping + endpoint RLS-denial tests (Phase 15 ENGINE-09).

Two parts (per Plan 15-03 Task 3 acceptance):

  (a) FUNNEL/VERDICT SHAPING -- shape_verification_report over the REAL recorded
      run_4cbb5311 verdict rows (from the committed fixture) matches the recorded
      funnel constants and splits verdicts by class, with a refuted-with-evidence
      section and a reconciled/superseded section derived from real reconciliation.
      Pure, NO DB -- uses load_recorded_run(session=None) (dev box has no Postgres).

  (b) RLS DENIAL -- GET /api/runs/{foreign_run_id}/verification returns EXACTLY 404
      (RLS miss reads absent -> scalar_one_or_none None -> 404), and the foreign
      run_id string does NOT appear in the response body (no id leak). Mirrors the
      FastAPI TestClient + fake-db-session pattern of test_run_status_resilience.py
      / test_seam_denial.py -- the RLS miss is modelled by a session whose run
      SELECT returns None (exactly what Postgres RLS produces for a cross-tenant id).

Cloud Build gate:
  pytest nestor_pulse_sdk/tests/test_citation_numbering.py \
         nestor_pulse_sdk/tests/test_verification_report_endpoint.py -x
"""

from __future__ import annotations

import uuid

import pytest

from nestor_pulse_sdk.tests.fixtures.run_4cbb5311 import (
    RECORDED_FUNNEL_COUNTS,
    load_recorded_run,
)
from nestor_pulse_sdk.verification.report import shape_verification_report


# ===========================================================================
# Part (a): funnel + verdict shaping over the REAL recorded verdict rows (no DB)
# ===========================================================================

def _report_from_fixture(claim_count: int = 0, cost="1.23", pending=False):
    tenant_id = uuid.uuid4()
    run = load_recorded_run(session=None, tenant_id=tenant_id)
    verdict_rows = run._fixture_verdict_rows  # type: ignore[attr-defined]
    from decimal import Decimal

    return shape_verification_report(
        verdict_rows=verdict_rows,
        funnel=run.verification_summary,
        claim_count=claim_count,
        cost_usd_total=Decimal(cost),
        cost_pending=pending,
    )


def test_funnel_matches_recorded_constants():
    """The report's funnel is exactly run.verification_summary (recorded counts)."""
    report = _report_from_fixture()
    assert report["funnel"] == RECORDED_FUNNEL_COUNTS
    assert report["funnel"]["distilled"] == 1162
    assert report["funnel"]["verify_sessions"] == 176


def test_verdicts_split_by_class_and_total_matches_rows():
    """Verdicts split into support/refute/insufficient; the split covers all rows."""
    report = _report_from_fixture()
    groups = report["verdicts"]
    total = len(groups["support"]) + len(groups["refute"]) + len(groups["insufficient"])
    assert total == report["counts"]["verdicts_total"], (
        "every verdict row must land in exactly one class bucket"
    )
    # The recorded run carries refute rows (31 per Plan 15-01 extract).
    assert len(groups["refute"]) >= 1, "recorded run must have >=1 refute verdict"


def test_refuted_section_carries_real_evidence():
    """Refuted-with-evidence surfaces refute rows that carry non-null evidence_refs."""
    report = _report_from_fixture()
    assert report["refuted"], "expected >=1 refuted-with-evidence entry from real data"
    for entry in report["refuted"]:
        assert entry["verdict"].lower() == "refute"
        assert entry["evidence_refs"], "a refuted entry must carry real evidence_refs"


def test_reconciled_or_superseded_present_from_real_reconciliation():
    """Real reconciliation dicts drive the reconciled/superseded areas (>=1 total)."""
    report = _report_from_fixture()
    total_recon = len(report["reconciled"]) + len(report["superseded"])
    assert total_recon >= 1, (
        "recorded run's refute rows carry non-null reconciliation -> at least one "
        "reconciled or superseded finding must be shaped"
    )


def test_unverified_is_honest_count():
    """UNVERIFIED = total claims minus claims carrying a verdict (honest accounting)."""
    # Recorded verdict rows have claim_id=None (run predates claim linkage), so
    # claims_with_verdict == 0 and unverified == the full claim_count.
    report = _report_from_fixture(claim_count=50)
    assert report["unverified"]["total_claims"] == 50
    assert report["unverified"]["claims_with_verdict"] == 0
    assert report["unverified"]["count"] == 50


def test_true_cost_surfaces_total_and_pending_flag():
    """True cost carries the run total (as string) + the cost_pending flag."""
    report = _report_from_fixture(cost="4.56", pending=True)
    assert report["true_cost"]["cost_usd_total"] == "4.56"
    assert report["true_cost"]["cost_pending"] is True


def test_all_six_stakeholder_content_areas_present():
    """All six STAKEHOLDER-NOTES content areas exist as report keys (+ SC4 citations)."""
    report = _report_from_fixture()
    for key in ("funnel", "verdicts", "refuted", "superseded", "reconciled",
                "unverified", "true_cost", "citations"):
        assert key in report, f"missing STAKEHOLDER-NOTES content area {key!r}"


def test_citations_ride_through_shaper():
    """SC4 / D13: the DB-numbered citations list rides through the report shape.

    The pure shaper defaults `citations` to [] (it is DB-free); when the async
    wrapper supplies number_citations() entries they must pass through VERBATIM
    -- the frontend renders its clickable [n] markers from exactly this list,
    which is what guarantees every rendered [n] resolves.
    """
    from decimal import Decimal

    # Default: key present, empty list (pure shaper, no DB numbering here).
    assert _report_from_fixture()["citations"] == []

    tenant_id = uuid.uuid4()
    run = load_recorded_run(session=None, tenant_id=tenant_id)
    entries = [
        {
            "n": 1,
            "source_id": str(uuid.uuid4()),
            "title": "SEC filing 10-K",
            "url": "https://www.sec.gov/x",
            "provider": "google",
            "publication_date": "2026-01-01T00:00:00+00:00",
            "quality_tier": 1,
            "single_source": False,
            "first_claim_id": None,
            "first_claim_position": 0,
        },
    ]
    report = shape_verification_report(
        verdict_rows=run._fixture_verdict_rows,  # type: ignore[attr-defined]
        funnel=run.verification_summary,
        claim_count=0,
        cost_usd_total=Decimal("1.00"),
        cost_pending=False,
        citations=entries,
    )
    assert report["citations"] == entries, "citations must ride through verbatim"


# ===========================================================================
# Part (b): endpoint RLS denial -- foreign run_id -> EXACTLY 404, no id leak
# ===========================================================================

pytest.importorskip("fastapi")
pytest.importorskip("httpx")  # fastapi.testclient transport


class _MissResult:
    """A SELECT result that yields no row -- exactly what RLS returns for a
    cross-tenant run_id (the row is invisible, so scalar_one_or_none is None)."""

    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return 0


class _RLSMissSession:
    """Fake AsyncSession modelling a cross-tenant read: the run SELECT (and every
    read) returns absent, mirroring Postgres RLS hiding another tenant's rows."""

    async def execute(self, *_args, **_kwargs):
        return _MissResult()


def _build_app():
    from fastapi import FastAPI

    from nestor_pulse_sdk.auth.deps import get_db_session
    from nestor_pulse_sdk.runs.api import router as runs_router

    app = FastAPI()
    app.include_router(runs_router)

    async def _fake_db_session():
        yield _RLSMissSession()

    app.dependency_overrides[get_db_session] = _fake_db_session
    return app


def test_verification_cross_tenant_run_returns_exactly_404_no_id_leak():
    """A run_id invisible under the caller's tenant context -> EXACTLY 404 (T-15-06).

    RLS makes a cross-tenant run read as absent, so the endpoint's
    scalar_one_or_none is None -> HTTPException(404). The foreign run_id string must
    NOT appear anywhere in the response body (no id leak; no distinguishable 403).
    """
    from fastapi.testclient import TestClient

    app = _build_app()
    try:
        foreign_run_id = uuid.uuid4()
        client = TestClient(app)
        resp = client.get(f"/api/runs/{foreign_run_id}/verification")

        assert resp.status_code == 404, (
            f"cross-tenant run_id must be EXACTLY 404 (RLS-miss == absent, "
            f"T-15-06), got {resp.status_code} (body={resp.text!r})."
        )
        assert str(foreign_run_id) not in resp.text, (
            "404 body leaked the foreign run_id -- must not echo the id back."
        )
    finally:
        app.dependency_overrides.clear()
