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
# These constants let downstream funnel tests assert the EXACT recorded numbers.
# ---------------------------------------------------------------------------
RECORDED_FUNNEL_COUNTS: dict[str, int] = {
    "distilled": 1162,
    "kept": 456,
    "dropped": 706,
    "selected_verify": 424,
    "skipped_stable": 32,
    "verify_sessions": 176,
}


def _report_dir() -> Path:
    """Locate the committed run-report dir by walking up from this module.

    Robust to worktree vs main-checkout layout: searches ancestors for
    `docs/tribunal-run-reports/run-20260722-4cbb5311`.
    """
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


def build_verification_summary() -> dict[str, int]:
    """The run-level verification funnel (recorded counts) for run.verification_summary."""
    return dict(RECORDED_FUNNEL_COUNTS)


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
