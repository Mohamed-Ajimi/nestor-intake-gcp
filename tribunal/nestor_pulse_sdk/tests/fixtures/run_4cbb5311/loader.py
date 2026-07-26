"""
run_4cbb5311 fixture loader -- reconstructs the recorded 2026-07-22 tribunal
run (4cbb5311) from its COMMITTED extracts (Phase 15 ENGINE-09).

Every downstream Phase-15 surface (cost report, verification report, citations,
D15 feed, seam, UI) reads from this fixture. It reconstructs, from the committed
`docs/tribunal-run-reports/run-20260722-4cbb5311/` material ONLY (no GCS pull):

  - a `run` row + `audit_log` rows ordered by GCS object MTIME (NOT seq --
    every blob in this OLD run carries seq=0, Pitfall 6);
  - `verification_verdict` rows extracted from the committed group_skeptic
    `emit_group_verdict` blocks (see verdict_extract.py);
  - an ENRICHED `run.stage_detail` JSONB (per-row cost_usd + audit_id + facts +
    task_prompt + retry, plus a per-stage summary) so the D15 feed (Plan 15-05)
    renders REAL recorded data at UAT -- NOT flat {name,status} rows;
  - `run.verification_summary` populated with the recorded gate-funnel counts.

Provenance (Q4 acceptance): all rows come from the committed extracts, so the
fixture has NO GCS dependency at test time. The raw blobs would otherwise live
at gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/
9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63/ -- recorded here for lineage only.
"""

from __future__ import annotations

import copy
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any

from nestor_pulse_sdk.tests.fixtures.run_4cbb5311.verdict_extract import (
    extract_group_verdicts,
)

# The stable GCS run id of the recorded run (for lineage/provenance only -- the
# fixture never reads GCS; all data comes from the committed extracts).
RECORDED_GCS_RUN_ID = "9c84e5a9-1bb9-4b6e-a3ce-2351eda9df63"
RECORDED_AUDIT_BUCKET = (
    "gs://project-cb01b861-cb4a-438d-b9a-nestor-audit/runs/"
    f"{RECORDED_GCS_RUN_ID}/"
)

# ---------------------------------------------------------------------------
# Recorded gate-funnel counts (documented constant).
# Sourced from the committed selection-experiment TSVs:
#   claims-distilled-full.tsv  -> 1162 distilled claim rows (no header).
#   claims-classified-full.tsv -> header id/decision/reason; KEEP=456 DROP=706.
#   keep-strict.tsv            -> header id/decision;       VERIFY=424 SKIP_STABLE=32.
# group_skeptic verify SESSIONS = 176 (index.json stage=group_skeptic call count;
#   163 single-claim + 13 multi-claim, per GROUPS.md).
# ~24 sessions returned reconciliation-as-string (BUG:recon-as-str) and were
#   DISCARDED by the live pipeline; the loader reproduces that by skipping
#   malformed emit blocks (see verdict_extract._parse_one_extract).
#
# 15.1 ADDITIVE keys -- G-08 accounting buckets, G-10 marker, G-11 gate errors.
# The six keys above are NEVER renamed: Phase-15 surfaces and
# test_hash_chain_replay.py assert on them. Sources, per key:
#   not_falsifiable 358 / not_load_bearing 320 / both 28
#       `reason` column tallies of claims-classified-full.tsv. They sum to
#       `dropped`: 358 + 320 + 28 == 706.
#   checked 198
#       summed `#claims` across the 176 rows of recorded/GROUPS.md -- per
#       recorded/REPORT.md §3.5 the 176 COMPLETED group-skeptic passes covered
#       198 claim slots.
#   should_have_been_checked 226
#       DERIVED ARITHMETIC, not a directly recorded number:
#       selected_verify 424 - checked 198 == 226. These are the claims the gates
#       selected that the 776 cap-rejected passes never reached. G-08 bucket 3 --
#       MUST be 0 on a healthy run.
#   gate_errors 0
#       zero by construction: the recorded run had no gate stage at all.
#   verification_degraded True
#       G-10 marker. The recorded run WAS degraded (776 Anthropic cap-400s in
#       55 seconds).
#
# 15.2 ADDITIVE keys -- WR-10/D-10 incidental checking, D-06 anchors, D-12 reasons.
# Every one of the seven is a FACT ABOUT THE RECORDED RUN, not a placeholder, and
# not an estimate (operator rule, verbatim: "NO ESTIMATES -- facts and correct
# calculations only"). Sources, per key:
#   checked_incidentally 0, and its four reason keys 0
#       The recorded run had NO GATE STAGE AT ALL -- the same fact that makes
#       `gate_errors 0`. No claim was gate-DROPped or SKIP_STABLE at run time, so
#       no claim COULD be checked incidentally: incidental checking is defined as
#       "the gates did not select it, yet it came back with a verdict", and a run
#       with no gates has no such population. The blind selection experiment's
#       KEEP/DROP classification is RETROSPECTIVE -- it was applied to the recorded
#       claims afterwards and never to that run's grouping. The fixture books all
#       198 covered claim slots inside `selected_verify` (which is what makes
#       `should_have_been_checked = 424 - 198` correct), and recorded/GROUPS.md
#       records per-group claim COUNTS with truncated claim text -- not ids
#       joinable to the answer-key TSVs -- so any non-zero figure here would be an
#       invention, not a derivation.
#   unresolved_anchors 0
#       Definitional: the recorded run predates D-05 entirely, so no [[c:...]]
#       anchor was ever emitted and none could fail to resolve. NOTE this is a
#       DIFFERENT mechanism from the recorded run's provider `[cite: N]` markers,
#       which are counted separately (`orphan_cite_markers`) and are NOT in the
#       funnel.
#   degradation_reasons []
#       The recorded run's degradation is recorded as `verification_degraded: True`
#       plus PROSE in recorded/REPORT.md (776 Anthropic cap-400s in 55 seconds),
#       never as a machine-readable reason list -- D-12's list did not exist in
#       2026-07. verification/report.py DERIVES the bucket-3 sentence at read time,
#       so the operator surface still names this run's degradation in words;
#       synthesising a sentence into the fixture would fabricate a recorded
#       artifact.
#
# Invariants these values satisfy:
#   distilled == kept + dropped                            1162 == 456 + 706
#   kept      == selected_verify + skipped_stable            456 == 424 + 32
#   dropped   == not_falsifiable + not_load_bearing + both   706 == 358 + 320 + 28
#   distilled == checked + (dropped + skipped_stable) + should_have_been_checked
#                                                          1162 == 198 + 738 + 226
#   verification_degraded == (should_have_been_checked > 0)
#   WR-10 one-claim-one-bucket, the 15.2 form of the line above -- bucket 2 is
#   reduced by exactly the claims that were checked incidentally:
#     distilled == checked + checked_incidentally
#                  + (dropped + skipped_stable - checked_incidentally)
#                  + should_have_been_checked
#   which reduces to the recorded 1162 == 198 + 738 + 226 while
#   checked_incidentally is 0.
#
# These constants let downstream funnel tests assert the EXACT recorded numbers.
# ---------------------------------------------------------------------------
RECORDED_FUNNEL_COUNTS: dict[str, int | bool | list[str]] = {
    "distilled": 1162,
    "kept": 456,
    "dropped": 706,
    "selected_verify": 424,
    "skipped_stable": 32,
    # G-13: 176 counts the group-skeptic calls that RETURNED on 2026-07-22 (776
    # more were hard-400'd by the Anthropic usage cap). It measures an outage,
    # not the funnel -- a recorded pass-through constant only.
    "verify_sessions": 176,  # incident-derived (G-13) -- NOT a gate assertion
    # --- 15.1 additive keys (per-key sources in the block above) ---
    "not_falsifiable": 358,
    "not_load_bearing": 320,
    "both": 28,
    "checked": 198,
    "should_have_been_checked": 226,
    "gate_errors": 0,
    "verification_degraded": True,
    # --- 15.2 additive keys (per-key sources in the block above) ---
    # WR-10 / D-10 Option 2: no gate stage on this run => no incidental checking
    # was possible. Zero is a FACT here, not a placeholder.
    "checked_incidentally": 0,
    "checked_incidentally_not_falsifiable": 0,
    "checked_incidentally_not_load_bearing": 0,
    "checked_incidentally_both": 0,
    "checked_incidentally_stable": 0,
    # D-06: the run predates the [[c:...]] anchor mechanism entirely.
    "unresolved_anchors": 0,
    # D-12: degradation was recorded as the boolean above plus prose, never as a
    # machine-readable list. verification/report.py derives the bucket-3 sentence.
    "degradation_reasons": [],
}


def _report_dir() -> Path:
    """Locate the committed run-report dir.

    Prefers the in-package `recorded/` copy — required in Cloud Build, where
    `gcloud builds submit tribunal` ships only the tribunal/ subtree and the
    repo-root `docs/` dir is absent from /workspace. Falls back to walking up
    for `docs/tribunal-run-reports/run-20260722-4cbb5311` (dev checkouts).
    """
    local = Path(__file__).resolve().parent / "recorded"
    if (local / "index.json").is_file():
        return local
    rel = Path("docs/tribunal-run-reports/run-20260722-4cbb5311")
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / rel
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        f"recorded run-report dir not found above {here} (looked for {rel})"
    )


def _load_index(report_dir: Path) -> list[dict[str, Any]]:
    """Load index.json (per-call provenance: audit_id, mtime, tokens, stage)."""
    return json.loads((report_dir / "index.json").read_text(encoding="utf-8"))


def _stage_cost_usd(
    provider: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cache_read: int,
) -> Decimal | None:
    """Facts-only per-stage cost via the SAME math audit cost_usd uses.

    Returns None (never a guess) when the model is unknown to cost_table --
    exactly the Pitfall-5 contract (write NULL, never fabricate).
    """
    from nestor_pulse_sdk.audit import cost_table

    return cost_table.compute(provider, model, tokens_in, tokens_out, cache_read)


def build_stage_detail(index: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the ENRICHED stage_detail JSONB the D15 feed (Plan 15-05) consumes.

    Shape (NOT flat {name,status}):
      { <stage_key>: {
          "items": [ {name, status, task_prompt, cost_usd, facts, retry, audit_id}, ... ],
          "summary": {duration_s, actions, items_read, cost_usd},
      }, ... }

    Every enriched field is derived from the committed index.json:
      - task_prompt : the call's `purpose` header line.
      - cost_usd    : facts-only cost via cost_table.compute over the recorded
                      token counts (NULL when the model is unknown -- never guessed).
      - facts       : recorded output size proxy (output_bytes) attributable to
                      the call/stage.
      - audit_id    : the call's audit-record id (the SAME id the 15-04
                      audit-body proxy resolves).
      - retry       : populated only if the recorded run marks a retry (the
                      recorded 4cbb5311 run has none -> field absent).
    stage_detail is JSONB -- OUTSIDE the frozen hashed payload; all additive.
    """
    stages: dict[str, Any] = {}
    for call in index:
        stage = call.get("stage") or "unknown"
        bucket = stages.setdefault(stage, {"items": [], "_mtimes": []})

        provider = call.get("provider", "")
        model = call.get("model", "")
        cost = _stage_cost_usd(
            provider,
            model,
            call.get("tokens_in", 0) or 0,
            call.get("tokens_out", 0) or 0,
            call.get("cache_read", 0) or 0,
        )
        item: dict[str, Any] = {
            "name": call.get("purpose") or f"{provider}/{model}",
            "status": "done",
            "task_prompt": call.get("purpose"),
            # JSONB is JSON -- serialise Decimal cost as a string (NULL preserved).
            "cost_usd": None if cost is None else str(cost),
            "facts": call.get("output_bytes", 0) or 0,
            "audit_id": call.get("audit_id"),
        }
        bucket["items"].append(item)
        if call.get("mtime"):
            bucket["_mtimes"].append(call["mtime"])

    # Per-stage summary (duration_s, actions, items_read, cost_usd) from the
    # recorded aggregates.
    out: dict[str, Any] = {}
    for stage, bucket in stages.items():
        items = bucket["items"]
        costs = [Decimal(i["cost_usd"]) for i in items if i["cost_usd"] is not None]
        mtimes = sorted(bucket["_mtimes"])
        duration_s = _mtime_span_seconds(mtimes) if len(mtimes) >= 2 else 0
        out[stage] = {
            "items": items,
            "summary": {
                "duration_s": duration_s,
                "actions": len(items),
                "items_read": sum(i["facts"] for i in items),
                "cost_usd": None if not costs else str(sum(costs)),
            },
        }
    return out


def _mtime_span_seconds(sorted_mtimes: list[str]) -> int:
    """Whole seconds between the first and last ISO-Z mtime in a stage."""
    from datetime import datetime

    def _parse(s: str) -> datetime:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    return int((_parse(sorted_mtimes[-1]) - _parse(sorted_mtimes[0])).total_seconds())


def build_verification_summary() -> dict[str, int | bool | list[str]]:
    """The run-level verification funnel (recorded counts) for run.verification_summary.

    Carries every contract key: the six original funnel counts, the G-08
    accounting buckets (not_falsifiable / not_load_bearing / both / checked /
    should_have_been_checked), the G-11 gate_errors line, the G-10
    `verification_degraded` marker, and the 15.2 additive keys (WR-10's five
    `checked_incidentally*` counts, D-06's `unresolved_anchors`, D-12's
    `degradation_reasons`).

    Returns a COPY so callers cannot mutate the constant. The body is
    deliberately a pure copy of the constant: two tests compare this against
    RECORDED_FUNNEL_COUNTS by FULL DICT EQUALITY (test_hash_chain_replay.py,
    test_verification_report_endpoint.py), so keeping it a pure copy makes both
    hold by construction whenever the constant gains keys.

    DEEP copy since 15.2: the funnel now carries a LIST value
    (`degradation_reasons`), and a shallow `dict()` copy would SHARE that list
    object with the module constant — a single caller that appended to it would
    silently corrupt G-13's single source of the recorded numbers for the rest of
    the process, and every later test in the same session. A deep copy still
    satisfies both equality assertions, which compare by value.
    """
    return copy.deepcopy(RECORDED_FUNNEL_COUNTS)


# ---------------------------------------------------------------------------
# The blind selection experiment (documented fixture contract).
#
# Three committed TSVs under `_report_dir()/selection-experiment/` -- resolved
# through _report_dir() so Cloud Build, which ships only the tribunal/ subtree,
# finds the in-package `recorded/` copy (a repo-root docs/ path would NOT exist
# in /workspace):
#
#   claims-distilled-full.tsv   1162 rows, NO HEADER (line 1 is data), CRLF.
#       columns: facet <TAB> claim_text <TAB> evidence
#       74 of the 1162 rows carry LITERAL TABS inside `evidence` -- it is a
#       verbatim copy of report prose and sometimes a flattened table row. The
#       reader MUST therefore use split("\t", 2) (maxsplit 2), exactly like the
#       production parser `_parse_distiller_response`
#       (pipeline/synthesis/steps.py:690). A bare split("\t") or a
#       csv.reader(delimiter="\t") mis-shapes those 74 rows.
#
#   claims-classified-full.tsv  header `id/decision/reason` + 1162 rows, CRLF.
#       Gates 1+2 answer key. Use the `reason` column, NOT `decision`: `reason`
#       is literally KEEP on KEEP rows (456), and DROP rows (706) carry
#       NOT_FALSIFIABLE (358) / NOT_LOAD_BEARING (320) / BOTH (28).
#
#   keep-strict.tsv             header `id/decision` + 456 rows, LF-only.
#       Gate 3 (error-likelihood) answer key over exactly the 456 KEEP ids.
#       decision is VERIFY (424) or SKIP_STABLE (32).
#
# CLAIM ID = the 1-BASED LINE NUMBER of claims-distilled-full.tsv. That file has
# no id column; the other two TSVs join on that line number (ids span 1..1162
# with no gaps).
#
# Line endings DIFFER across the three files (CRLF vs LF-only) and a Windows
# checkout may renormalise either way, so every line is rstrip("\r")-ed
# individually rather than trusting one file-level convention. Encoding is
# always explicit utf-8: the TSVs carry em-dashes, `€` and accented Dutch.
#
# This is the phase's SINGLE fixture parser -- one correct reader instead of
# eight subtly-wrong ones.
# ---------------------------------------------------------------------------


def _read_headed_tsv(path: Path) -> list[list[str]]:
    r"""Rows of a HEADED tsv: header dropped, blank lines skipped, CR-tolerant.

    Only for the two answer-key files, which have a FIXED small column count
    (3 and 2), so a plain split("\t") is safe. NEVER use this for
    claims-distilled-full.tsv -- that file needs maxsplit=2 (see the block above).
    """
    raw = path.read_text(encoding="utf-8")
    rows: list[list[str]] = []
    for line in raw.split("\n")[1:]:  # [1:] drops the header line
        line = line.rstrip("\r")
        if not line.strip():
            continue
        rows.append(line.split("\t"))
    return rows


def load_selection_experiment() -> tuple[list[dict], dict[int, str], dict[int, str]]:
    """Load the blind selection experiment: claims + both gate answer keys.

    Returns `(claims, classified, strict)`:
      - `claims`     list of 1162 dicts in the EXACT shape `claim_distiller`
                     emits, plus the join key:
                     {"id": int, "text": str, "facet": str, "evidence": str}.
                     `id` is the 1-BASED LINE NUMBER in claims-distilled-full.tsv.
      - `classified` {id -> reason} for all 1162 claims; reason is one of
                     KEEP / NOT_FALSIFIABLE / NOT_LOAD_BEARING / BOTH.
      - `strict`     {id -> decision} for exactly the 456 KEEP ids; decision is
                     one of VERIFY / SKIP_STABLE.

    Pure: no DB, no GCS, no network -- mirrors the `load_recorded_run(session=None)`
    convention so no-DB unit tests can assert on the returned objects directly.
    """
    exp_dir = _report_dir() / "selection-experiment"

    # --- claims-distilled-full.tsv: NO header; id = 1-based line number. ---
    # Enumerate BEFORE skipping blanks so a blank line could never renumber ids.
    claims: list[dict] = []
    distilled_raw = (exp_dir / "claims-distilled-full.tsv").read_text(encoding="utf-8")
    for lineno, line in enumerate(distilled_raw.split("\n"), start=1):
        line = line.rstrip("\r")
        if not line.strip():
            continue
        # maxsplit=2 is load-bearing: 74 rows have literal tabs inside `evidence`.
        parts = line.split("\t", 2)
        claims.append(
            {
                "id": lineno,
                "facet": parts[0].strip(),
                "text": parts[1].strip() if len(parts) > 1 else "",
                "evidence": parts[2].strip() if len(parts) > 2 else "",
            }
        )

    # --- claims-classified-full.tsv: header id/decision/reason -> use `reason`. ---
    classified: dict[int, str] = {
        int(row[0]): row[2].strip()
        for row in _read_headed_tsv(exp_dir / "claims-classified-full.tsv")
    }

    # --- keep-strict.tsv: header id/decision, the 456 KEEP ids only. ---
    strict: dict[int, str] = {
        int(row[0]): row[1].strip()
        for row in _read_headed_tsv(exp_dir / "keep-strict.tsv")
    }

    return claims, classified, strict


def load_recorded_run(session: Any, tenant_id: uuid.UUID) -> "Run":  # noqa: F821
    """Reconstruct + seed the recorded run 4cbb5311 for a tenant.

    Seeds (all from committed extracts, NO GCS):
      - one `run` row with an ENRICHED stage_detail + verification_summary;
      - `audit_log` rows ordered by GCS object MTIME (Pitfall 6 -- NOT seq);
      - `verification_verdict` rows from the committed emit_group_verdict blocks.

    `session` may be a live AsyncSession (adds the ORM objects) or None (pure
    construction -- the returned objects are still fully populated so no-DB unit
    tests can assert on run.stage_detail / the verdict rows directly).

    Returns the constructed `Run` ORM instance.
    """
    from nestor_pulse_sdk.db.models.audit_log import AuditLog
    from nestor_pulse_sdk.db.models.run import Run
    from nestor_pulse_sdk.db.models.verification_verdict import VerificationVerdict

    report_dir = _report_dir()
    index = _load_index(report_dir)

    # ------------------------------------------------------------------ run
    run = Run(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        project_id=uuid.uuid4(),
        engine="sdk",
        brief="[recorded run 4cbb5311] dynamic pricing in European fuel retail",
        status="completed",
        idempotency_key=uuid.uuid4(),
        current_stage="done",
        cost_pending=False,
        stage_detail=build_stage_detail(index),
        verification_summary=build_verification_summary(),
    )

    # ------------------------------------------------------------ audit_log
    # Order by GCS object mtime, NOT seq: every recorded blob has seq=0
    # (Pitfall 6). We assign a fresh monotonic seq HERE so a re-derived hash
    # chain is well-formed; the recorded seq=0 is intentionally ignored.
    ordered = sorted(index, key=lambda c: c.get("mtime", ""))
    audit_rows: list[AuditLog] = []
    for new_seq, call in enumerate(ordered, start=1):
        audit_rows.append(
            AuditLog(
                id=uuid.UUID(call["audit_id"]),
                tenant_id=tenant_id,
                run_id=run.id,
                seq=new_seq,
                provider=call.get("provider", ""),
                model=call.get("model", ""),
                started_at=_iso(call.get("mtime")),
                duration_ms=0,
                prompt_tokens=call.get("tokens_in", 0) or 0,
                completion_tokens=call.get("tokens_out", 0) or 0,
                cached_tokens=call.get("cache_read", 0) or 0,
                cache_creation_tokens=call.get("cache_create", 0) or 0,
                gcs_uri=RECORDED_AUDIT_BUCKET + f"{call['audit_id']}.json",
                prev_hash="0" * 64,
                hash="0" * 64,
            )
        )

    # ---------------------------------------------------- verification_verdict
    verdict_rows: list[VerificationVerdict] = []
    for v in extract_group_verdicts(report_dir / "calls"):
        verdict_rows.append(
            VerificationVerdict(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                run_id=run.id,
                claim_id=None,  # recorded run predates claim.id linkage
                verdict=v["verdict"],
                confidence=v["confidence"],
                evidence_refs=v["evidence_refs"],
                reconciliation=v["reconciliation"],
            )
        )

    if session is not None:
        session.add(run)
        for row in audit_rows:
            session.add(row)
        for row in verdict_rows:
            session.add(row)

    # Attach for no-DB assertions.
    run._fixture_audit_rows = audit_rows  # type: ignore[attr-defined]
    run._fixture_verdict_rows = verdict_rows  # type: ignore[attr-defined]
    return run


def _iso(mtime: str | None):
    """Parse an ISO-Z mtime string into a tz-aware datetime (now() fallback)."""
    from datetime import datetime, timezone

    if not mtime:
        return datetime.now(timezone.utc)
    return datetime.fromisoformat(mtime.replace("Z", "+00:00"))
