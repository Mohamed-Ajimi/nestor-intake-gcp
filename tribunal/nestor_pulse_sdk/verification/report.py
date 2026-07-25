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
(`verification_verdict` + `run` + `claim`, plus `source`/`claim_source` via
`citations.numbering.number_citations` for the SC4 [n] citations list). It
performs NO GCS / storage / blob read -- the verdicts were already parsed +
persisted by Plan 15-01's verdict_extract. There is intentionally no
`google.cloud`, `storage`, `gcs`, or `blob` import anywhere in this file.

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

from nestor_pulse_sdk.citations.numbering import number_citations
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
# G-08 three-bucket accounting (15.1) -- FUNNEL-driven, never a row join.
#
# The old two-way arithmetic (`total_claims - claims_with_verdict`) lumps "this
# claim was never checkable" together with "this claim should have been checked
# and the fact-checker died" -- the exact P1 defect. The three buckets are:
#
#   1. CHECKED                          -- a fact-checker actually looked at it.
#   2. NOT CHECKABLE                    -- gated out, WITH the specific reason.
#   3. SHOULD HAVE BEEN CHECKED BUT WASN'T -- crash, usage cap, budget
#      exhaustion, gate error. This is the phase's most important number: an
#      unchecked claim leaves its passage STANDING in the delivered prose
#      (only a refutation triggers scrubbing), so bucket 3 counts passages that
#      shipped unexamined. It must be ZERO on a healthy run.
#
# Why the funnel and not a join over `verification_verdict` -> `claim`:
# `claim_id` is NULL on every recorded verdict row (the recorded run predates
# claim linkage, see verification_verdict.py and loader.py), so a join reports
# `claims_with_verdict == 0` and dumps all 1,162 claims into bucket 3. The gate
# stage owns the funnel; the funnel is the honest source.
# ---------------------------------------------------------------------------

# Bucket-2 reasons, in funnel-key form. `skipped_stable` is the error-likelihood
# gate's "stable known fact" skip; the other three are the materiality gates'.
_NOT_CHECKABLE_KEYS = ("not_falsifiable", "not_load_bearing", "both", "skipped_stable")

# Every funnel key the accounting block needs. A funnel missing ANY of them is a
# pre-15.1 run: we report `accounting = None` (no gate data) rather than a dict
# of zeros, which would read as a clean bucket 3 and lie about an old run.
_ACCOUNTING_KEYS = ("checked", "should_have_been_checked", "gate_errors") + _NOT_CHECKABLE_KEYS


def _accounting(funnel: dict | None) -> dict | None:
    """G-08's three buckets, derived from the funnel. None when there is no gate data."""
    if not isinstance(funnel, dict):
        return None
    if any(key not in funnel for key in _ACCOUNTING_KEYS):
        return None

    not_falsifiable = int(funnel["not_falsifiable"] or 0)
    not_load_bearing = int(funnel["not_load_bearing"] or 0)
    both = int(funnel["both"] or 0)
    stable_known_fact = int(funnel["skipped_stable"] or 0)

    return {
        # Bucket 1.
        "checked": int(funnel["checked"] or 0),
        # Bucket 2 -- never a bare total; every gated-out claim carries its reason.
        "not_checkable": {
            "total": not_falsifiable + not_load_bearing + both + stable_known_fact,
            "not_falsifiable": not_falsifiable,
            "not_load_bearing": not_load_bearing,
            "both": both,
            "stable_known_fact": stable_known_fact,
        },
        # Bucket 3 -- the headline. Zero on a healthy run.
        "should_have_been_checked": int(funnel["should_have_been_checked"] or 0),
        # Gate batches that errored out (G-11 records them; they never absorb
        # bucket 3, they are reported alongside it).
        "gate_errors": int(funnel["gate_errors"] or 0),
    }


def _degradation(funnel: dict | None, accounting: dict | None) -> tuple[bool, str | None]:
    """G-10's loud marker: (verification_degraded, verification_degraded_text).

    The run KEEPS status `completed` -- four API endpoints gate on that string and
    15.2's R6 owns the real terminal-state vocabulary. What changes is that the
    verification report says, in WORDS and at the top, that its own fact-checking
    was gutted. Not an icon, not a colour: a sentence.
    """
    if not isinstance(funnel, dict):
        return False, None

    if accounting is not None:
        shortfall = accounting["should_have_been_checked"]
        gate_errors = accounting["gate_errors"]
    else:
        shortfall = int(funnel.get("should_have_been_checked") or 0)
        gate_errors = int(funnel.get("gate_errors") or 0)

    # The gate stage sets the marker explicitly; derive it when the funnel predates
    # the key, so an old-but-gated run cannot read as green by omission.
    if "verification_degraded" in funnel:
        degraded = bool(funnel["verification_degraded"])
    else:
        degraded = shortfall > 0

    if not degraded:
        return False, None

    distilled = funnel.get("distilled")
    scope = f"{shortfall} of {int(distilled)} claims" if distilled else f"{shortfall} claims"
    text = (
        f"VERIFICATION DEGRADED -- {scope} were selected for fact-checking but were "
        "not checked (crash, usage cap, budget exhaustion or gate error). Their "
        "supporting passages are still in the research text: only a refutation "
        "removes a passage, so an unchecked claim ships unexamined. This run's "
        "verification is incomplete -- do not read it as green."
    )
    if gate_errors:
        text += f" {gate_errors} gate batch(es) also errored."
    return True, text


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
    citations: list[dict] | None = None,
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
      citations:      the run's ordered `[n] -> source` entries from
                      `citations.numbering.number_citations` (SC4 / D13 -- numbers
                      GENERATED from the DB, never the model). Optional so the pure
                      shaper stays DB-free; defaults to an empty list.

    Returns a JSON-safe dict with keys:
      funnel, accounting, verification_degraded, verification_degraded_text,
      verdicts{support,refute,insufficient,superseded}, refuted, superseded,
      reconciled, unverified{count,claims_with_verdict,total_claims},
      true_cost{cost_usd_total,cost_pending}, citations, counts.

    `verdicts["superseded"]` (the G-06 VERDICT CLASS) and the top-level
    `superseded` (a reconciliation-derived scoped/temporal finding) are two
    different things that happen to share a word -- see the classing branch.

    G-08's three buckets (`accounting`):
      1. `checked`                     -- a fact-checker looked at it.
      2. `not_checkable`               -- gated out, with the SPECIFIC reason
         (not_falsifiable / not_load_bearing / both / stable_known_fact).
      3. `should_have_been_checked`    -- selected for checking and never
         checked (crash, usage cap, budget, gate error). ZERO on a healthy run;
         non-zero means passages shipped unexamined.
    They are derived from the FUNNEL, not from a verdict-row join: `claim_id` is
    NULL on the recorded rows, so a join would put every claim in bucket 3.

    `accounting` is a SIBLING of `unverified`, which keeps its exact shape (the
    operator surface binds to it). When `funnel` is None -- or is missing any
    gate key, i.e. a pre-15.1 run -- `accounting` is **None**, never a dict of
    zeros: "no gate data" must not read as "a clean bucket 3".

    G-10: `verification_degraded` / `verification_degraded_text` say in a full
    sentence that a run whose status is still `completed` had its fact-checking
    gutted. No status changes here (15.2's R6 owns that).

    Deliberately absent: any coverage percentage. The delivered report is written
    from SCRUBBED PROSE, not from the claim list, so "X of Y statements verified"
    has a false denominator -- which is exactly why G-09 keeps this surface
    superadmin-only rather than client-facing.
    """
    rows = list(verdict_rows)

    support: list[dict] = []
    refute: list[dict] = []
    insufficient: list[dict] = []
    refuted: list[dict] = []       # refute WITH evidence (the operator's "why refuted")
    superseded: list[dict] = []    # scoped / temporal findings with a canonical
    reconciled: list[dict] = []    # disputed contradictions with a chosen canonical

    # G-06 (15.1): the VERDICT CLASS bucket. NOT the same thing as `superseded`
    # above -- see the name-collision note on the classing branch below.
    superseded_verdicts: list[dict] = []

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
        elif v == "superseded":
            # G-06 (15.1): the fourth verdict class the group skeptic can emit
            # (plan 15.1-03 added it to EMIT_VERDICT_TOOL). Before this branch
            # existed it fell through to `else: insufficient` and was silently
            # swallowed -- a claim the skeptic said "was true, has since changed"
            # was reported as "we could not tell".
            #
            # ⚠ NAME COLLISION -- TWO DIFFERENT `superseded` KEYS, ON PURPOSE:
            #   report["verdicts"]["superseded"]  (THIS list, counted as
            #       counts["superseded_verdicts"]) = the VERDICT CLASS.
            #   report["superseded"]              (the TOP-LEVEL list built from
            #       `reconciliation` a few lines below) = a reconciliation-derived
            #       scoped/temporal finding carrying a canonical value. It is bound
            #       by runs/schemas.py, the frontend VerificationReport.tsx and
            #       test_verification_report_endpoint.py.
            # Do NOT unify them: they answer different questions and one of them
            # is a shipped surface.
            superseded_verdicts.append(dto)
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

    # G-08 / G-10 (15.1). `accounting` is a SIBLING of `unverified`, not a
    # replacement: the operator surface binds to unverified.{count,
    # claims_with_verdict,total_claims} and keeps working untouched.
    accounting = _accounting(funnel)
    verification_degraded, verification_degraded_text = _degradation(funnel, accounting)

    return {
        "funnel": dict(funnel) if isinstance(funnel, dict) else None,
        # G-08: the three honest buckets (None when the run carries no gate data).
        "accounting": accounting,
        # G-10: stated in words, at the top, for a run that still says `completed`.
        "verification_degraded": verification_degraded,
        "verification_degraded_text": verification_degraded_text,
        "verdicts": {
            "support": support,
            "refute": refute,
            "insufficient": insufficient,
            # G-06 verdict class -- distinct from the top-level "superseded" key.
            "superseded": superseded_verdicts,
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
        # SC4 / D13: the numbered [n] citation entries the operator surface renders
        # as clickable markers -- every [n] resolves (generated from the DB).
        "citations": list(citations) if citations else [],
        "counts": {
            "verdicts_total": len(rows),
            "support": len(support),
            "refute": len(refute),
            "insufficient": len(insufficient),
            "refuted_with_evidence": len(refuted),
            # "superseded" counts the reconciliation-derived findings (unchanged);
            # "superseded_verdicts" counts the G-06 verdict class. Two keys because
            # they are two different things (see the classing branch above).
            "superseded": len(superseded),
            "superseded_verdicts": len(superseded_verdicts),
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

    # SC4 / D13: the run's numbered [n] citation entries -- deterministic DB
    # numbering (claim/source/claim_source rows only, RLS-scoped, no GCS). This
    # is what makes the operator surface's [n] markers resolvable: every marker
    # rendered comes from THIS list, so no number can dangle.
    citations = await number_citations(session, run.id)

    return shape_verification_report(
        verdict_rows=verdict_rows,
        funnel=getattr(run, "verification_summary", None),
        claim_count=int(claim_count or 0),
        cost_usd_total=getattr(run, "cost_usd_total", None),
        cost_pending=bool(getattr(run, "cost_pending", False)),
        citations=citations,
    )
