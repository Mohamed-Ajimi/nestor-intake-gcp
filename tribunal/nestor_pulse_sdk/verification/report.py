"""
build_verification_report -- shape persisted verdicts + funnel + true cost into the
operator's post-run verification-report (Phase 15 ENGINE-09, Plan 15-03).

STAKEHOLDER-NOTES §2026-07-24 REQUIRED content (six areas):
  1. funnel            -- distilled / kept / dropped / selected / sessions / skipped /
                          verdicts / failed, from `run.verification_summary`.
  2. refuted           -- refute verdicts WITH skeptic evidence (evidence_refs).
  3. superseded        -- scoped/temporal findings: a reconciliation.note or
                          reconciliation.relation=='scoped' with a canonical value.
  4. reconciled        -- disputed contradictions with a chosen canonical
                          (reconciliation.disputed==True).
  5. unverified        -- an HONEST list/count of claims with NO verdict row.
  6. true_cost         -- run.cost_usd_total + a cost_pending flag (Plan 15-02).

CRITICAL (Plan 15-03 acceptance): this module reads ONLY persisted rows
(`verification_verdict` + `run` + `claim`). It performs NO GCS / storage / blob
read -- the verdicts were already parsed + persisted by Plan 15-01's
verdict_extract. There is intentionally no `google.cloud`, `storage`, `gcs`, or
`blob` import anywhere in this file.

Split design (dev-box has no Python/Postgres):
  - `shape_verification_report(...)` is a PURE function over already-materialised
    verdict rows + a funnel dict + cost values. It is unit-testable with NO DB
    (drive it from the run_4cbb5311 fixture's `_fixture_verdict_rows`).
  - `build_verification_report(session, run)` is the thin async DB-facing wrapper
    the endpoint calls: it fetches the run's verdict rows + the claim count under
    the caller's tenant context (RLS), then delegates to the pure shaper.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from nestor_pulse_sdk.db.models.verification_verdict import VerificationVerdict


# ---------------------------------------------------------------------------
# Row-shape helpers (work on ORM rows OR plain objects with the same attrs)
# ---------------------------------------------------------------------------

def _reconciliation(row: Any) -> dict | None:
    recon = getattr(row, "reconciliation", None)
    return recon if isinstance(recon, dict) else None


def _evidence_refs(row: Any) -> list | None:
    refs = getattr(row, "evidence_refs", None)
    if isinstance(refs, list):
        return refs
    return None


def _verdict_dto(row: Any) -> dict[str, Any]:
    """A single verdict row in the report shape (never leaks tenant_id/hashes)."""
    return {
        "claim_id": str(row.claim_id) if getattr(row, "claim_id", None) else None,
        "verdict": row.verdict,
        "confidence": getattr(row, "confidence", None),
        "evidence_refs": _evidence_refs(row),
        "reconciliation": _reconciliation(row),
    }


# ---------------------------------------------------------------------------
# Pure shaper -- NO DB, NO GCS. Unit-testable from the recorded fixture rows.
# ---------------------------------------------------------------------------

def shape_verification_report(
    *,
    verdict_rows: Iterable[Any],
    funnel: dict | None,
    claim_count: int,
    cost_usd_total: Decimal | None,
    cost_pending: bool,
) -> dict[str, Any]:
    """Shape the six STAKEHOLDER-NOTES content areas from materialised rows.

    Args:
      verdict_rows:   the run's `verification_verdict` rows (ORM rows or any object
                      exposing verdict / confidence / evidence_refs / reconciliation
                      / claim_id). Read-only; never mutated.
      funnel:         `run.verification_summary` dict (may be None for legacy runs).
      claim_count:    total persisted `claim` rows for the run (for the honest
                      UNVERIFIED count: claims - claims-with-a-verdict).
      cost_usd_total: `run.cost_usd_total` (Decimal or None).
      cost_pending:   `run.cost_pending` -- True while Plan 15-02's recompute is
                      still reconciling some per-call costs.

    Returns a JSON-safe dict with keys:
      funnel, verdicts{support,refute,insufficient}, refuted, superseded,
      reconciled, unverified{count,claims_with_verdict,total_claims},
      true_cost{cost_usd_total,cost_pending}, counts.
    """
    rows = list(verdict_rows)

    support: list[dict] = []
    refute: list[dict] = []
    insufficient: list[dict] = []
    refuted: list[dict] = []       # refute WITH evidence (the operator's "why refuted")
    superseded: list[dict] = []    # scoped / temporal findings with a canonical
    reconciled: list[dict] = []    # disputed contradictions with a chosen canonical

    claim_ids_with_verdict: set[str] = set()

    for row in rows:
        dto = _verdict_dto(row)
        if dto["claim_id"] is not None:
            claim_ids_with_verdict.add(dto["claim_id"])

        v = (dto["verdict"] or "").lower()
        if v == "support":
            support.append(dto)
        elif v == "refute":
            refute.append(dto)
            # Refuted-with-evidence: skeptic must cite to refute (group_skeptic
            # rule); surface those refute rows carrying real evidence_refs.
            if dto["evidence_refs"]:
                refuted.append(dto)
        else:
            insufficient.append(dto)

        recon = dto["reconciliation"]
        if recon:
            canonical = recon.get("canonical") or ""
            relation = (recon.get("relation") or "").lower()
            note = recon.get("note") or ""
            disputed = bool(recon.get("disputed"))

            # Reconciled contradiction: genuinely disputed variants with a chosen
            # canonical value (the "we picked X over Y" area).
            if disputed and canonical:
                reconciled.append(dto)
            # Superseded / scoped-temporal finding: a scoped relation OR a
            # temporal/scope caveat note, carrying a canonical current value.
            elif (relation == "scoped" or note) and canonical:
                superseded.append(dto)

    # HONEST unverified accounting: claims with NO verdict row. We can only
    # distinguish by claim_id linkage; the recorded run predates claim linkage
    # (claim_id is NULL) so we report the count derivable from claim_count minus
    # the number of DISTINCT claims that DO carry a verdict.
    claims_with_verdict = len(claim_ids_with_verdict)
    unverified_count = max(0, int(claim_count) - claims_with_verdict)

    return {
        "funnel": dict(funnel) if isinstance(funnel, dict) else None,
        "verdicts": {
            "support": support,
            "refute": refute,
            "insufficient": insufficient,
        },
        "refuted": refuted,
        "superseded": superseded,
        "reconciled": reconciled,
        "unverified": {
            "count": unverified_count,
            "claims_with_verdict": claims_with_verdict,
            "total_claims": int(claim_count),
        },
        "true_cost": {
            "cost_usd_total": (
                str(cost_usd_total) if cost_usd_total is not None else None
            ),
            "cost_pending": bool(cost_pending),
        },
        "counts": {
            "verdicts_total": len(rows),
            "support": len(support),
            "refute": len(refute),
            "insufficient": len(insufficient),
            "refuted_with_evidence": len(refuted),
            "superseded": len(superseded),
            "reconciled": len(reconciled),
        },
    }


# ---------------------------------------------------------------------------
# Async DB-facing wrapper -- the endpoint calls THIS. RLS-scoped reads only.
# ---------------------------------------------------------------------------

async def build_verification_report(
    session: AsyncSession,
    run: Any,
) -> dict[str, Any]:
    """Fetch the run's persisted verdicts + claim count (RLS-scoped) and shape them.

    Reads ONLY persisted rows: `verification_verdict` (via the ORM, RLS-scoped) and
    the run's `claim` count (raw count, RLS-scoped). No GCS blob is ever read here.
    The caller (the /verification endpoint) has already loaded `run` under the
    caller's tenant context, so these follow-on reads see the same tenant only.
    """
    verdict_rows = (
        await session.execute(
            select(VerificationVerdict)
            .where(VerificationVerdict.run_id == run.id)
            .order_by(VerificationVerdict.created_at.asc())
        )
    ).scalars().all()

    # Total persisted claims for the run (RLS-scoped) -- the denominator for the
    # honest UNVERIFIED count. EXISTS-free plain count keeps it cheap.
    claim_count = (
        await session.execute(
            text("SELECT count(*) FROM claim WHERE run_id = :rid"),
            {"rid": str(run.id)},
        )
    ).scalar_one()

    return shape_verification_report(
        verdict_rows=verdict_rows,
        funnel=getattr(run, "verification_summary", None),
        claim_count=int(claim_count or 0),
        cost_usd_total=getattr(run, "cost_usd_total", None),
        cost_pending=bool(getattr(run, "cost_pending", False)),
    )
