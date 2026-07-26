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
    """A single verdict row in the report shape, SIX keys (never leaks tenant_id/hashes).

    The sixth key, `superseded_note`, is the G-07 caveat the group skeptic must
    supply alongside a `superseded` verdict -- WHAT changed, and FROM WHEN --
    persisted in the `verification_verdict.superseded_note` column added by
    migration 0012. `runs/schemas.py` has DECLARED the field on
    VerificationVerdictItem since 15.1-03, but this DTO never emitted it, so
    pydantic's `extra="ignore"` had nothing to carry and the wire value was
    unconditionally None no matter what was stored (CR-01 leg b). The DTO is the
    gate: a key it does not emit cannot reach the API response.

    `getattr(..., None)` rather than a bare attribute access is load-bearing.
    Rows arrive here in three shapes: ORM rows that carry the column; ORM rows
    built by tests/fixtures/run_4cbb5311/loader.py, whose constructor omits it
    (attribute present, value None); and SimpleNamespace fakes in
    test_verification_buckets.py that set exactly the five legacy attributes and
    nothing else. A bare attribute access would AttributeError on the third.
    """
    return {
        "claim_id": str(row.claim_id) if getattr(row, "claim_id", None) else None,
        "verdict": row.verdict,
        "confidence": getattr(row, "confidence", None),
        "evidence_refs": _evidence_refs(row),
        "reconciliation": _reconciliation(row),
        # G-07 caveat (CR-01 leg b) -- getattr default, see the docstring note.
        "superseded_note": getattr(row, "superseded_note", None),
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

# WR-10 / D-10 Option 2 (15.2): the four "checked incidentally" counts, POSITIONALLY
# PAIRED with _NOT_CHECKABLE_KEYS above -- index i here is the incidental count for
# bucket-2 reason i there. Keep the two tuples in the same order; the zip below
# depends on it.
#
# ⚠ THE TRAP -- READ BEFORE TOUCHING _ACCOUNTING_KEYS ⚠
# These keys are read with `funnel.get(key, 0)` and are DELIBERATELY NOT part of
# `_ACCOUNTING_KEYS`. `_accounting` returns None when ANY `_ACCOUNTING_KEYS` member
# is missing from the funnel, and that is not a bug — it is how the shaper DETECTS a
# pre-15.1 run and reports "no gate data" instead of a dict of zeros that would read
# as a clean bucket 3. Adding one of these (or `unresolved_anchors`, or
# `degradation_reasons`) to that tuple would make EVERY funnel written before 15.2 —
# including every run already in the database — fail the membership test, so the
# operator's accounting block would go blank on runs that have perfectly good gate
# data. `test_accounting_keys_tuple_excludes_the_incidental_keys` in
# test_verification_buckets.py asserts the tuple's exact membership, so this is
# enforced rather than merely requested.
_INCIDENTAL_KEYS = (
    "checked_incidentally_not_falsifiable",
    "checked_incidentally_not_load_bearing",
    "checked_incidentally_both",
    "checked_incidentally_stable",
)

# D-12 caps, mirroring pipeline._normalise_degradation_reasons. Restated here on
# purpose: this shaper must also survive a hand-built or legacy funnel that never
# went through the producer-side normaliser.
_DEGRADATION_REASON_CHARS = 200
_MAX_DEGRADATION_REASONS = 8


def _accounting(funnel: dict | None) -> dict | None:
    """G-08's buckets, derived from the funnel. None when there is no gate data.

    FOUR accounting lines since 15.2 (D-10 / WR-10):

      1. `checked`                  -- selected by the gates AND actually checked.
      2. `checked_incidentally`     -- NOT selected, yet checked anyway as a member
         of a selected group. Its verdicts are real: they reach adjudication and a
         refutation still scrubs the passage. Reported with the gate reason the
         claim carried, so the operator can see WHICH not-checkable claims got
         checked after all.
      3. `not_checkable`            -- gated out AND never checked, with the
         specific reason. Reduced by line 2, PER REASON, so its four printed
         reasons still add up to its own printed total on the page.
      4. `should_have_been_checked` -- the headline. Zero on a healthy run.

    The arithmetic a reader can check by hand:
        distilled == checked
                   + checked_incidentally.total
                   + not_checkable.total
                   + should_have_been_checked

    `checked_incidentally.total` is computed HERE as the sum of the same four
    clamped values the subtraction uses — never as a read of the funnel's flat
    `checked_incidentally` key — so the one-claim-one-bucket invariant holds by
    construction even for a hand-built funnel. (The pipeline's flat key is the
    producer's ground truth; a test asserts the two agree.)
    """
    if not isinstance(funnel, dict):
        return None
    if any(key not in funnel for key in _ACCOUNTING_KEYS):
        return None

    raw = {key: int(funnel[key] or 0) for key in _NOT_CHECKABLE_KEYS}
    # Read with `.get` — NEVER a membership gate, see the trap note above. Clamped
    # to its own raw bucket-2 reason so a malformed funnel can never drive a reason
    # negative; same defensive register as pipeline._build_funnel's
    # `min(unchecked_selected, selected)`.
    incidental = {
        nc_key: min(max(0, int(funnel.get(inc_key, 0) or 0)), raw[nc_key])
        for nc_key, inc_key in zip(_NOT_CHECKABLE_KEYS, _INCIDENTAL_KEYS)
    }
    reduced = {key: raw[key] - incidental[key] for key in _NOT_CHECKABLE_KEYS}

    return {
        # Bucket 1.
        "checked": int(funnel["checked"] or 0),
        # Bucket 1b (WR-10) -- the same five-key shape as bucket 2, and the same
        # `stable_known_fact` rename on the way out (the funnel says
        # `skipped_stable` / `checked_incidentally_stable`; this block has always
        # spelled it for a reader rather than for the gate stage).
        "checked_incidentally": {
            "total": sum(incidental.values()),
            "not_falsifiable": incidental["not_falsifiable"],
            "not_load_bearing": incidental["not_load_bearing"],
            "both": incidental["both"],
            "stable_known_fact": incidental["skipped_stable"],
        },
        # Bucket 2 -- never a bare total; every gated-out claim carries its reason.
        # A claim subtracted here is NOT lost: it is in the `checked_incidentally`
        # block directly above, and the two blocks together still account for every
        # gated-out claim. `total` is the sum of the four REDUCED values, so an
        # operator who adds up the printed reasons gets the printed total.
        "not_checkable": {
            "total": sum(reduced.values()),
            "not_falsifiable": reduced["not_falsifiable"],
            "not_load_bearing": reduced["not_load_bearing"],
            "both": reduced["both"],
            "stable_known_fact": reduced["skipped_stable"],
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
        # WR-02: `gate_errors` is a per-CLAIM counter -- gates.py:557-558 bumps it
        # once for every claim whose gate decision was defaulted, and
        # test_gate_failure_modes.py:168 pins that (3 claims -> 3). This sentence
        # used to render it in batch units, so at the default _GATE_BATCH = 40 one
        # failed batch was reported to the operator as forty of them: a 40x
        # overstatement of how much of the gate stage broke. pipeline.py:297
        # already words the same counter correctly ("gate errors (sent for
        # checking)"); only this line was wrong. State CLAIMS, in claim units.
        text += f" {gate_errors} claim(s) were sent for checking on a defaulted gate answer."
    return True, text


def _degradation_reasons(
    funnel: dict | None,
    verification_degraded_text: str | None,
) -> list[str]:
    """D-12: every reason this run degraded, as sentences the operator reads.

    A SIBLING of `_degradation`, never a change to it: that function carries G-10
    semantics `test_fail_loud.py` pins.

    Two sources, one list:

      * the pipeline's own reasons, carried on `funnel["degradation_reasons"]` —
        a lost research stream, a question-workshop fallback, a fact-list fallback,
        a blocked coverage re-entry. They are written by ONE run-scoped accumulator
        in `pipeline.run()` and normalised by ONE normaliser
        (`pipeline._normalise_degradation_reasons`). The same normalisation is
        restated below because this shaper must also survive a hand-built or legacy
        funnel that never passed through the producer.
      * the BUCKET-3 sentence, DERIVED here and prepended. The pipeline deliberately
        never writes it, so exactly one wording of it exists in the codebase — which
        is also what lets the recorded run, whose funnel carries
        `degradation_reasons: []`, still name its degradation to the operator.

    Never invents a reason from anything else. Per D-12, a RECOVERED retry is
    recovery, not shortfall, and `cost_pending` is the designed
    pending-then-backfill-exact path; neither is a degradation reason, and demoting
    them would drain `completed_degraded` of its meaning.

    This function shapes the operator's WORDS. It does not decide the run's status:
    that is `terminal_state()` (15.2-02) and the worker (15.2-16), which read
    `should_have_been_checked` and this list off `run.verification_summary`.
    """
    if not isinstance(funnel, dict):
        return []

    raw = funnel.get("degradation_reasons")
    if not isinstance(raw, list):
        raw = []

    kept: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if not text:
            continue
        text = text[:_DEGRADATION_REASON_CHARS]
        if text in seen:
            continue
        seen.add(text)
        kept.append(text)

    if isinstance(verification_degraded_text, str) and verification_degraded_text.strip():
        bucket_three = verification_degraded_text.strip()
        if bucket_three not in seen:
            kept.insert(0, bucket_three)

    return kept[:_MAX_DEGRADATION_REASONS]


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
      unverified_from_accounting, unverified_note,
      unresolved_anchors, unresolved_anchors_text, degradation_reasons,
      true_cost{cost_usd_total,cost_pending}, citations, counts.

    CR-02: `unverified` keeps its exact three keys, but when a run carries ZERO
    verdict rows AND real gate data its VALUES are derived from the same funnel
    `accounting` reads, and `unverified_note` says so in words. That makes it
    impossible to publish "checked: 380" beside "unverified: 1162 of 1162" in
    one payload. A run WITH verdict rows, and a pre-15.1 run with no gate data,
    both keep the row-derived arithmetic untouched.

    `verdicts["superseded"]` (the G-06 VERDICT CLASS) and the top-level
    `superseded` (a reconciliation-derived scoped/temporal finding) are two
    different things that happen to share a word -- see the classing branch.

    G-08's buckets (`accounting`), four lines since 15.2's D-10 / WR-10:
      1. `checked`                     -- a fact-checker looked at it.
      1b. `checked_incidentally`       -- NOT selected by the gates, but checked
         anyway as a member of a selected group, with the SPECIFIC gate reason.
         Subtracted from bucket 2 per reason (see `_accounting`).
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

    # D-12: every reason, in sentences (the derived bucket-3 one first).
    degradation_reasons = _degradation_reasons(funnel, verification_degraded_text)
    # D-06: the citation anchors the writing model emitted that matched no claim in
    # this run. `funnel or {}` because a pre-15.1 run carries no funnel at all.
    unresolved_anchors = max(0, int((funnel or {}).get("unresolved_anchors", 0) or 0))
    # A healthy run says NOTHING -- the same rule `_degradation` follows. A marker
    # that renders on every run is background noise, and the operator stops reading
    # it exactly when it starts mattering.
    unresolved_anchors_text: str | None = None
    if unresolved_anchors:
        unresolved_anchors_text = (
            f"{unresolved_anchors} citation anchor(s) in the written report could "
            "not be matched to a numbered source from this run, so they were "
            "removed and no broken [n] marker ships. The sentences they were "
            "attached to are UNCHANGED and still stand -- they are simply uncited. "
            "This count is the measure of how closely the writing model followed "
            "the citation-anchor instruction: the higher it is, the more of the "
            "report's apparent sourcing the model produced from memory rather than "
            "from the evidence this run actually gathered."
        )

    # -----------------------------------------------------------------------
    # CR-02 (the 15.1 SC2 gap): the unverified block must never contradict the
    # accounting block it sits next to.
    #
    # Nothing in production wrote a `verification_verdict` row before plan
    # 15.1-14's writer -- the only writer in the repo was the fixture loader. On
    # a real run that made `claim_ids_with_verdict` empty, so this shaper
    # published `unverified.count == total_claims` in the SAME payload as the
    # honest `accounting.checked`: the operator read "checked: 380" directly
    # beside "unverified: 1162 of 1162" with no way to tell which number to
    # believe. Two sibling numbers that disagree destroy trust in the whole
    # surface, so the report must not be ABLE to emit them.
    #
    # 15.1-14's writer is the PRIMARY fix. This is the regression guard that
    # holds even if that writer breaks, or for a run that predates it: with zero
    # verdict rows and real gate data, the unverified figure is derived from the
    # SAME funnel `_accounting` reads, so the two agree by construction.
    #
    # Both guards are ANDed and both are load-bearing:
    #   * verdict rows present -> the row-derived arithmetic above stands
    #     untouched (test_verification_report_endpoint::test_unverified_is_honest_count
    #     depends on it for the recorded claim_id-NULL fixture).
    #   * `accounting is None` (a pre-15.1 run carrying no gate data) -> report
    #     the legacy figure rather than invent one from numbers we do not have.
    #
    # The two new keys are TOP-LEVEL SIBLINGS of `unverified`. Nothing is added
    # INSIDE `unverified`: two tests assert its key set is exactly
    # {count, claims_with_verdict, total_claims} and the shipped operator
    # surface binds to that shape.
    # -----------------------------------------------------------------------
    verdicts_total = len(rows)
    unverified_from_accounting = False
    unverified_note: str | None = None

    if verdicts_total == 0 and accounting is not None:
        unverified_from_accounting = True
        # The clamp is load-bearing: `claim_count` counts persisted survivor
        # `claim` rows while `checked` counts gated claims -- two different
        # denominators, so an unclamped subtraction could go negative.
        claims_with_verdict = min(int(claim_count), int(accounting["checked"]))
        unverified_count = max(0, int(claim_count) - claims_with_verdict)
        unverified_note = (
            "No verification_verdict row was persisted for this run, so the "
            "unverified figure is derived from the gate funnel's checked count "
            "and therefore agrees with the accounting block above it. The "
            "per-claim verdict lists are empty because nothing wrote them -- "
            "not because nothing was checked."
        )

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
        # CR-02: the fallback is VISIBLE, not silent. These two are siblings of
        # `unverified` (never keys inside it) and are declared explicitly on
        # VerificationReport so they cannot be dropped at the API boundary.
        "unverified_from_accounting": unverified_from_accounting,
        "unverified_note": unverified_note,
        # D-06 / D-12, TOP-LEVEL SIBLINGS beside the other CR-02-style honesty keys.
        # Nothing is added inside `unverified`: two tests assert its key set is
        # exactly {count, claims_with_verdict, total_claims}.
        "unresolved_anchors": unresolved_anchors,
        "unresolved_anchors_text": unresolved_anchors_text,
        "degradation_reasons": degradation_reasons,
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
            "verdicts_total": verdicts_total,
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
